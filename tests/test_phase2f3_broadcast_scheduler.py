from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from bson import ObjectId

from app.models.user_model import UserRole
from app.repositories import whatsapp_broadcast_repository as repository
from app.services.whatsapp_sender import send_whatsapp_template
from test_phase2c1_template_send import _headers, _user
from test_phase2e3_broadcast_execution import _confirm, _prepared


WORKER_HEADERS = {"X-Worker-Token": "test-only-worker-token-at-least-32-characters"}


def _scheduled(client, database, monkeypatch, *, count=1, seconds=3600):
    _admin, headers, prepared, contacts = _prepared(client, database, monkeypatch, count=count)
    confirmed = _confirm(client, headers, prepared)
    scheduled_for = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    response = client.post(
        f"/whatsapp-broadcasts/{prepared['id']}/schedule",
        headers=headers,
        json={"version": confirmed["version"], "scheduledFor": scheduled_for.isoformat()},
    )
    assert response.status_code == 200
    return headers, prepared["id"], response.json()["data"], contacts


def _make_due(database, broadcast_id):
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    database.whatsapp_broadcasts.update_one({"_id": ObjectId(broadcast_id)}, {"$set": {"nextRunAt": past}})
    database.whatsapp_broadcast_recipients.update_many(
        {"broadcastId": ObjectId(broadcast_id), "status": "FAILED_RETRYABLE"},
        {"$set": {"retryEligibleAt": past, "retryNotBefore": past}},
    )


def test_schedule_reschedule_past_rejection_unschedule_and_authorization(client, database, monkeypatch):
    headers, broadcast_id, scheduled, _contacts = _scheduled(client, database, monkeypatch)
    assert scheduled["schedulerState"] == "SCHEDULED"
    assert scheduled["scheduledFor"].endswith("Z") or "+00:00" in scheduled["scheduledFor"]

    later = datetime.now(timezone.utc) + timedelta(hours=2)
    rescheduled = client.post(
        f"/whatsapp-broadcasts/{broadcast_id}/schedule",
        headers=headers,
        json={"version": scheduled["version"], "scheduledFor": later.isoformat()},
    )
    assert rescheduled.status_code == 200 and rescheduled.json()["data"]["version"] == scheduled["version"] + 1
    current = rescheduled.json()["data"]

    past = client.post(
        f"/whatsapp-broadcasts/{broadcast_id}/schedule",
        headers=headers,
        json={"version": current["version"], "scheduledFor": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()},
    )
    assert past.status_code == 422 and past.json()["error"]["code"] == "WHATSAPP_BROADCAST_SCHEDULE_IN_PAST"

    _user(database, "scheduler-counsellor@example.com", UserRole.COUNSELLOR.value)
    assert client.get(f"/whatsapp-broadcasts/{broadcast_id}/schedule", headers=_headers(client, "scheduler-counsellor@example.com")).status_code == 403
    removed = client.delete(f"/whatsapp-broadcasts/{broadcast_id}/schedule?version={current['version']}", headers=headers)
    assert removed.status_code == 200 and removed.json()["data"]["schedulerState"] == "UNSCHEDULED"
    actions = {item["action"] for item in database.audit_logs.find({"entityId": broadcast_id})}
    assert {"WHATSAPP_BROADCAST_SCHEDULED", "WHATSAPP_BROADCAST_RESCHEDULED", "WHATSAPP_BROADCAST_UNSCHEDULED"}.issubset(actions)


def test_due_worker_is_protected_claims_atomically_and_never_resends_success(client, database, monkeypatch):
    _headers_value, broadcast_id, _scheduled_state, _contacts = _scheduled(client, database, monkeypatch, count=2)
    _make_due(database, broadcast_id)
    assert client.post("/internal/whatsapp-broadcasts/run-due", json={"batchSize": 1}).status_code == 401
    assert client.post("/internal/whatsapp-broadcasts/run-due", headers={"X-Worker-Token": "wrong"}, json={"batchSize": 1}).status_code == 401

    now = datetime.now(timezone.utc)
    first_claim = repository.claim_due_broadcast("worker-a", now, now + timedelta(minutes=5))
    second_claim = repository.claim_due_broadcast("worker-b", now, now + timedelta(minutes=5))
    assert first_claim and second_claim is None
    repository.release_scheduler_claim(first_claim["_id"], "worker-a", {"schedulerState": "SCHEDULED", "nextRunAt": now, "updatedAt": now})

    sender = Mock(side_effect=[
        {"success": True, "statusCode": 200, "response": {"messages": [{"id": "wamid.scheduled-1"}]}},
        {"success": True, "statusCode": 200, "response": {"messages": [{"id": "wamid.scheduled-2"}]}},
    ])
    monkeypatch.setattr("app.services.whatsapp_broadcast_execution_service.send_whatsapp_template", sender)
    first = client.post("/internal/whatsapp-broadcasts/run-due", headers=WORKER_HEADERS, json={"batchSize": 1, "maxBroadcasts": 1})
    second = client.post("/internal/whatsapp-broadcasts/run-due", headers=WORKER_HEADERS, json={"batchSize": 1, "maxBroadcasts": 1})
    third = client.post("/internal/whatsapp-broadcasts/run-due", headers=WORKER_HEADERS, json={"batchSize": 1, "maxBroadcasts": 1})
    assert first.status_code == second.status_code == third.status_code == 200
    assert first.json()["data"]["claimedRecipients"] == second.json()["data"]["claimedRecipients"] == 1
    assert third.json()["data"]["claimedBroadcasts"] == 0 and sender.call_count == 2
    assert database.whatsapp_broadcast_recipients.count_documents({"broadcastId": ObjectId(broadcast_id), "status": "ACCEPTED"}) == 2
    assert database.whatsapp_messages.count_documents({"providerMessageId": {"$in": ["wamid.scheduled-1", "wamid.scheduled-2"]}}) == 2
    assert database.audit_logs.count_documents({"action": "WHATSAPP_BROADCAST_AUTOMATIC_BATCH_EXECUTED"}) == 2


def test_retry_after_exponential_backoff_delayed_retry_and_exhaustion(client, database, monkeypatch):
    _headers_value, broadcast_id, _scheduled_state, _contacts = _scheduled(client, database, monkeypatch)
    _make_due(database, broadcast_id)
    sender = Mock(side_effect=[
        {"success": False, "statusCode": 429, "error": "WHATSAPP_API_ERROR", "retryAfterSeconds": 900, "response": {"token": "never-store"}},
        {"success": False, "statusCode": 500, "error": "WHATSAPP_API_ERROR", "response": {}},
        {"success": False, "statusCode": 500, "error": "WHATSAPP_API_ERROR", "response": {}},
        {"success": False, "statusCode": 500, "error": "WHATSAPP_API_ERROR", "response": {}},
    ])
    monkeypatch.setattr("app.services.whatsapp_broadcast_execution_service.send_whatsapp_template", sender)

    first_started = datetime.now(timezone.utc)
    first = client.post("/internal/whatsapp-broadcasts/run-due", headers=WORKER_HEADERS, json={"batchSize": 1, "maxBroadcasts": 1})
    assert first.status_code == 200 and first.json()["data"]["retryableFailure"] == 1
    recipient = database.whatsapp_broadcast_recipients.find_one({"broadcastId": ObjectId(broadcast_id)})
    retry_at = recipient["retryEligibleAt"].replace(tzinfo=timezone.utc) if recipient["retryEligibleAt"].tzinfo is None else recipient["retryEligibleAt"]
    assert retry_at >= first_started + timedelta(seconds=895)
    assert recipient["retryNotBefore"] == recipient["retryEligibleAt"] and recipient["attemptCount"] == 1

    too_early = client.post("/internal/whatsapp-broadcasts/run-due", headers=WORKER_HEADERS, json={"batchSize": 1, "maxBroadcasts": 1})
    assert too_early.json()["data"]["claimedBroadcasts"] == 0 and sender.call_count == 1

    _make_due(database, broadcast_id)
    second_started = datetime.now(timezone.utc)
    client.post("/internal/whatsapp-broadcasts/run-due", headers=WORKER_HEADERS, json={"batchSize": 1, "maxBroadcasts": 1})
    recipient = database.whatsapp_broadcast_recipients.find_one({"broadcastId": ObjectId(broadcast_id)})
    second_retry = recipient["retryEligibleAt"].replace(tzinfo=timezone.utc) if recipient["retryEligibleAt"].tzinfo is None else recipient["retryEligibleAt"]
    assert second_retry >= second_started + timedelta(seconds=120) and recipient["attemptCount"] == 2

    _make_due(database, broadcast_id)
    client.post("/internal/whatsapp-broadcasts/run-due", headers=WORKER_HEADERS, json={"batchSize": 1, "maxBroadcasts": 1})
    _make_due(database, broadcast_id)
    final = client.post("/internal/whatsapp-broadcasts/run-due", headers=WORKER_HEADERS, json={"batchSize": 1, "maxBroadcasts": 1})
    recipient = database.whatsapp_broadcast_recipients.find_one({"broadcastId": ObjectId(broadcast_id)})
    assert final.json()["data"]["retryExhausted"] == 1
    assert recipient["status"] == "FAILED_FINAL" and recipient["failureCode"] == "WHATSAPP_RETRY_ATTEMPTS_EXHAUSTED"
    assert recipient["attemptCount"] == 4 and sender.call_count == 4
    assert "never-store" not in str(list(database.whatsapp_broadcast_recipients.find({})))
    assert "never-store" not in str(list(database.audit_logs.find({})))
    assert database.audit_logs.count_documents({"action": "WHATSAPP_BROADCAST_RETRY_EXHAUSTED"}) == 1


def test_sender_reduces_retry_after_header_to_safe_seconds(monkeypatch):
    response = Mock(status_code=429, headers={"Retry-After": "321"}, content=b"{}")
    response.json.return_value = {"error": {"message": "rate limited"}}
    monkeypatch.setattr("app.services.whatsapp_sender.WHATSAPP_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr("app.services.whatsapp_sender.WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setattr("app.services.whatsapp_sender.requests.post", Mock(return_value=response))
    result = send_whatsapp_template("919876543210", "approved_template")
    assert result["retryAfterSeconds"] == 321 and "headers" not in result


def test_cancellation_stops_scheduled_work_and_indexes_exist(client, database, monkeypatch):
    headers, broadcast_id, scheduled, _contacts = _scheduled(client, database, monkeypatch)
    cancelled = client.post(f"/whatsapp-broadcasts/{broadcast_id}/cancel", headers=headers, json={"version": scheduled["version"]})
    assert cancelled.status_code == 200
    invalid = client.post(
        f"/whatsapp-broadcasts/{broadcast_id}/schedule",
        headers=headers,
        json={"version": cancelled.json()["data"]["version"], "scheduledFor": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()},
    )
    assert invalid.status_code == 409
    _make_due(database, broadcast_id)
    worker = client.post("/internal/whatsapp-broadcasts/run-due", headers=WORKER_HEADERS, json={"batchSize": 10, "maxBroadcasts": 10})
    assert worker.json()["data"]["claimedBroadcasts"] == 0
    assert database.whatsapp_broadcasts.find_one({"_id": ObjectId(broadcast_id)})["schedulerState"] == "CANCELLED"
    assert {"ix_whatsapp_broadcast_scheduler_due"}.issubset(database.whatsapp_broadcasts.index_information())
    assert {"ix_whatsapp_broadcast_retry_due"}.issubset(database.whatsapp_broadcast_recipients.index_information())

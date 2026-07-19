from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from bson import ObjectId

from app.models.user_model import UserRole
from app.repositories import whatsapp_broadcast_repository as repository
from test_phase2c1_template_send import _headers, _user
from test_phase2e1_broadcasts import _contact, _lead, _payload, _template


def _prepared(client, database, monkeypatch, *, count=1):
    monkeypatch.setattr("app.services.whatsapp_broadcast_service.WHATSAPP_WABA_ID", "waba-broadcast")
    admin = _user(database, "execution-admin@example.com", UserRole.SUPER_ADMIN.value)
    headers = _headers(client, "execution-admin@example.com"); template_id = _template(database, "UTILITY")
    contacts = []
    for index in range(count):
        contact = _contact(database, f"Person {index}", str(919876543210 + index)); _lead(database, contact); contacts.append(contact)
    created = client.post("/whatsapp-broadcasts", headers=headers, json=_payload(template_id)).json()["data"]
    prepared = client.post(f"/whatsapp-broadcasts/{created['id']}/prepare", headers=headers, json={"version": created["version"]}).json()["data"]
    return admin, headers, prepared, contacts


def _confirm(client, headers, prepared):
    response = client.post(f"/whatsapp-broadcasts/{prepared['id']}/confirm", headers=headers, json={"version": prepared["version"]})
    assert response.status_code == 200
    return response.json()["data"]


def test_authorization_confirmation_and_version_protection(client, database, monkeypatch):
    _admin, headers, prepared, _contacts = _prepared(client, database, monkeypatch)
    _user(database, "execution-counsellor@example.com", UserRole.COUNSELLOR.value)
    assert client.post(f"/whatsapp-broadcasts/{prepared['id']}/confirm", headers=_headers(client, "execution-counsellor@example.com"), json={"version": prepared["version"]}).status_code == 403
    assert client.post(f"/whatsapp-broadcasts/{prepared['id']}/confirm", headers=headers, json={"version": prepared["version"] + 1}).status_code == 409
    confirmed = _confirm(client, headers, prepared)
    assert confirmed["status"] == "EXECUTING" and confirmed["totals"]["remaining"] == 1
    assert client.post(f"/whatsapp-broadcasts/{prepared['id']}/confirm", headers=headers, json={"version": prepared["version"]}).status_code == 409


def test_immutable_snapshot_persistence_and_same_batch_replay(client, database, monkeypatch):
    _admin, headers, prepared, contacts = _prepared(client, database, monkeypatch)
    recipient_before = database.whatsapp_broadcast_recipients.find_one({"broadcastId": ObjectId(prepared["id"])})
    rendered = recipient_before["renderedText"]; components = recipient_before["providerComponents"]
    confirmed = _confirm(client, headers, prepared)
    database.contacts.update_one({"_id": contacts[0]}, {"$set": {"normalizedPhone": "919999999999", "firstName": "Changed"}})
    database.leads.update_one({"contactId": contacts[0]}, {"$set": {"preferredMode": "OFFLINE"}})
    sent = Mock(return_value={"success": True, "statusCode": 200, "response": {"messages": [{"id": "wamid.broadcast-1"}]}})
    monkeypatch.setattr("app.services.whatsapp_broadcast_execution_service.send_whatsapp_template", sent)
    first = client.post(f"/whatsapp-broadcasts/{prepared['id']}/execute-batch", headers=headers, json={"batchSize": 10})
    second = client.post(f"/whatsapp-broadcasts/{prepared['id']}/execute-batch", headers=headers, json={"batchSize": 10})
    assert first.status_code == 200 and second.status_code == 200 and second.json()["data"]["batch"]["claimed"] == 0 and sent.call_count == 1
    assert sent.call_args.args[0] == "919876543210" and sent.call_args.kwargs["template_components"] == components
    recipient = database.whatsapp_broadcast_recipients.find_one({"broadcastId": ObjectId(prepared["id"])})
    assert recipient["status"] == "ACCEPTED" and recipient["idempotencyKey"]
    message = database.whatsapp_messages.find_one({"providerMessageId": "wamid.broadcast-1"})
    assert message["renderedText"] == rendered and message["status"] == "ACCEPTED" and message["contactId"] == contacts[0]
    assert len(recipient["idempotencyKey"]) == 64


def test_partial_failures_retry_without_resending_success_and_safe_storage(client, database, monkeypatch):
    _admin, headers, prepared, _contacts = _prepared(client, database, monkeypatch, count=3); confirmed = _confirm(client, headers, prepared)
    send = Mock(side_effect=[
        {"success": True, "statusCode": 200, "response": {"messages": [{"id": "wamid.ok"}]}},
        {"success": False, "statusCode": 429, "error": "WHATSAPP_API_ERROR", "response": {"access_token": "never-store"}},
        {"success": False, "statusCode": 400, "error": "WHATSAPP_API_ERROR", "response": {"authorization": "never-store"}},
    ])
    monkeypatch.setattr("app.services.whatsapp_broadcast_execution_service.send_whatsapp_template", send)
    response = client.post(f"/whatsapp-broadcasts/{prepared['id']}/execute-batch", headers=headers, json={"batchSize": 3})
    assert response.status_code == 200
    assert database.whatsapp_broadcast_recipients.count_documents({"status": "ACCEPTED"}) == 1
    assert database.whatsapp_broadcast_recipients.count_documents({"status": "FAILED_RETRYABLE"}) == 1
    assert database.whatsapp_broadcast_recipients.count_documents({"status": "FAILED_FINAL"}) == 1
    assert "never-store" not in str(list(database.whatsapp_broadcast_recipients.find({})))
    database.whatsapp_broadcast_recipients.update_many({"status": "FAILED_RETRYABLE"}, {"$set": {"retryEligibleAt": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    retry = client.post(f"/whatsapp-broadcasts/{prepared['id']}/retry-failures", headers=headers, json={"version": confirmed["version"]})
    assert retry.status_code == 200 and retry.json()["data"]["approved"] == 1
    monkeypatch.setattr("app.services.whatsapp_broadcast_execution_service.send_whatsapp_template", Mock(return_value={"success": True, "response": {"messages": [{"id": "wamid.retry"}]}}))
    assert client.post(f"/whatsapp-broadcasts/{prepared['id']}/execute-batch", headers=headers, json={"batchSize": 3}).status_code == 200
    assert database.whatsapp_broadcast_recipients.count_documents({"status": "ACCEPTED"}) == 2
    assert database.whatsapp_messages.count_documents({}) == 2


def test_atomic_claims_cancellation_and_expired_lease_recovery(client, database, monkeypatch):
    _admin, headers, prepared, _contacts = _prepared(client, database, monkeypatch, count=4); confirmed = _confirm(client, headers, prepared)
    broadcast_id = ObjectId(prepared["id"]); now = datetime.now(timezone.utc)
    first = repository.claim_next_recipient(broadcast_id, "worker-a", now, now + timedelta(seconds=10))
    second = repository.claim_next_recipient(broadcast_id, "worker-b", now, now + timedelta(seconds=10))
    assert first["_id"] != second["_id"]
    database.whatsapp_broadcast_recipients.update_one({"_id": first["_id"]}, {"$set": {"leaseExpiresAt": now - timedelta(seconds=1)}})
    database.whatsapp_broadcast_recipients.update_one({"_id": second["_id"]}, {"$set": {"leaseExpiresAt": now - timedelta(seconds=1), "providerCallStartedAt": now}})
    recovered = repository.recover_expired_leases(broadcast_id, now)
    assert recovered == {"requeued": 1, "uncertainFinal": 1}
    accepted = repository.claim_next_recipient(broadcast_id, "worker-c", now, now + timedelta(seconds=10))
    repository.finish_recipient(accepted["_id"], "worker-c", {"status": "ACCEPTED", "providerMessageId": "wamid.already-sent", "updatedAt": now})
    cancel = client.post(f"/whatsapp-broadcasts/{prepared['id']}/cancel", headers=headers, json={"version": confirmed["version"]})
    assert cancel.status_code == 200
    assert database.whatsapp_broadcast_recipients.count_documents({"status": "SKIPPED", "exclusionReason": "BROADCAST_CANCELLED"}) == 2
    assert database.whatsapp_broadcast_recipients.count_documents({"status": "FAILED_FINAL", "failureCode": "PROVIDER_RESULT_UNCERTAIN"}) == 1
    assert database.whatsapp_broadcast_recipients.count_documents({"status": "ACCEPTED", "providerMessageId": "wamid.already-sent"}) == 1


def test_execution_indexes_exist(database):
    indexes = database.whatsapp_broadcast_recipients.index_information()
    assert {"ix_whatsapp_broadcast_execution_claim", "ix_whatsapp_broadcast_processing_lease", "uq_whatsapp_broadcast_recipient_idempotency"}.issubset(indexes)

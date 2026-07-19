from datetime import datetime, timedelta, timezone

from bson import ObjectId

from app.models.user_model import UserRole
from test_phase2c1_template_send import _headers, _user


def _broadcast(database, creator_id, *, name, status="EXECUTING", scheduler="UNSCHEDULED", created_at=None):
    created_at = created_at or datetime.now(timezone.utc)
    return database.whatsapp_broadcasts.insert_one({
        "templateName": name, "templateLanguage": "en_US", "templateCategory": "UTILITY",
        "status": status, "schedulerState": scheduler, "createdBy": creator_id, "createdAt": created_at,
        "scheduledFor": created_at + timedelta(hours=1) if scheduler == "SCHEDULED" else None,
    }).inserted_id


def _recipient(database, broadcast_id, *, status="PENDING", delivery=None, reason=None):
    database.whatsapp_broadcast_recipients.insert_one({
        "broadcastId": broadcast_id, "contactId": ObjectId(), "status": status, "executionStatus": status,
        **({"deliveryStatus": delivery} if delivery else {}),
        **({"exclusionReason": reason} if reason else {}),
    })


def test_history_is_super_admin_only_and_returns_safe_newest_first_summaries(client, database):
    admin = _user(database, "history-admin@example.com", UserRole.SUPER_ADMIN.value)
    _user(database, "history-counsellor@example.com", UserRole.COUNSELLOR.value)
    now = datetime.now(timezone.utc)
    older = _broadcast(database, admin["_id"], name="older_template", created_at=now - timedelta(days=1))
    newer = _broadcast(database, admin["_id"], name="newer_template", scheduler="SCHEDULED", created_at=now)
    _recipient(database, older, status="ACCEPTED", delivery="DELIVERED")
    _recipient(database, newer, status="PENDING")
    _recipient(database, newer, status="FAILED_FINAL")

    denied = client.get("/whatsapp-broadcasts", headers=_headers(client, "history-counsellor@example.com"))
    assert denied.status_code == 403
    response = client.get("/whatsapp-broadcasts?page=1&pageSize=1", headers=_headers(client, "history-admin@example.com"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"]["totalRecords"] == 2 and payload["pagination"]["hasNext"] is True
    summary = payload["data"][0]
    assert summary["id"] == str(newer) and summary["template"] == {"name": "newer_template", "language": "en_US", "category": "UTILITY"}
    assert summary["schedulerState"] == "SCHEDULED" and summary["createdBy"]["displayName"] == "history-admin"
    assert summary["executionTotals"] == {"pending": 1, "accepted": 0, "failed": 1, "remaining": 1}
    assert not ({"recipientSnapshots", "providerComponents", "providerMessageId", "idempotencyKey", "accessToken"} & summary.keys())


def test_history_filters_by_state_scheduler_template_and_date_range(client, database):
    admin = _user(database, "history-filter@example.com", UserRole.SUPER_ADMIN.value)
    now = datetime.now(timezone.utc)
    matching = _broadcast(database, admin["_id"], name="Admission Followup", status="COMPLETED", scheduler="COMPLETED", created_at=now - timedelta(days=2))
    _broadcast(database, admin["_id"], name="Other", status="EXECUTING", scheduler="SCHEDULED", created_at=now)
    headers = _headers(client, "history-filter@example.com")
    response = client.get("/whatsapp-broadcasts", headers=headers, params={
        "state": "COMPLETED", "schedulerState": "COMPLETED", "templateName": "follow", 
        "createdFrom": (now - timedelta(days=3)).isoformat(), "createdTo": (now - timedelta(days=1)).isoformat(),
    })
    assert response.status_code == 200 and response.json()["pagination"]["totalRecords"] == 1
    assert response.json()["data"][0]["id"] == str(matching)
    invalid_range = client.get("/whatsapp-broadcasts", headers=headers, params={"createdFrom": now.isoformat(), "createdTo": (now - timedelta(days=1)).isoformat()})
    assert invalid_range.status_code == 422 and invalid_range.json()["error"]["code"] == "WHATSAPP_BROADCAST_DATE_RANGE_INVALID"


def test_history_summary_reuses_preparation_execution_and_delivery_totals(client, database):
    admin = _user(database, "history-totals@example.com", UserRole.SUPER_ADMIN.value)
    broadcast = _broadcast(database, admin["_id"], name="totals")
    _recipient(database, broadcast, status="PENDING")
    _recipient(database, broadcast, status="ACCEPTED", delivery="READ")
    _recipient(database, broadcast, status="SKIPPED", reason="DO_NOT_CONTACT")
    _recipient(database, broadcast, status="REJECTED", reason="TEMPLATE_VARIABLE_MISSING")
    response = client.get("/whatsapp-broadcasts", headers=_headers(client, "history-totals@example.com"))
    assert response.status_code == 200
    summary = response.json()["data"][0]
    assert summary["preparationTotals"] == {"prepared": 4, "eligible": 2, "skipped": 1, "rejected": 1}
    assert summary["executionTotals"] == {"pending": 1, "accepted": 1, "failed": 0, "remaining": 1}
    assert summary["deliveryTotals"] == {"delivered": 0, "read": 1}


def test_history_indexes_exist(database):
    indexes = database.whatsapp_broadcasts.index_information()
    assert {"ix_whatsapp_broadcast_history_created", "ix_whatsapp_broadcast_scheduler_created"}.issubset(indexes)

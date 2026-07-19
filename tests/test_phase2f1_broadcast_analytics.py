from datetime import datetime, timezone
from unittest.mock import Mock

from app.models.user_model import UserRole
from app.services.whatsapp_message_service import process_extracted_event
from test_phase2c1_template_send import _headers, _user
from test_phase2e3_broadcast_execution import _confirm, _prepared


def _accepted_broadcast(client, database, monkeypatch):
    _admin, headers, prepared, _contacts = _prepared(client, database, monkeypatch)
    _confirm(client, headers, prepared)
    sender = Mock(return_value={"success": True, "statusCode": 200, "response": {"messages": [{"id": "wamid.analytics-1"}]}})
    monkeypatch.setattr("app.services.whatsapp_broadcast_execution_service.send_whatsapp_template", sender)
    response = client.post(f"/whatsapp-broadcasts/{prepared['id']}/execute-batch", headers=headers, json={"batchSize": 1})
    assert response.status_code == 200
    return headers, prepared["id"], sender


def _status(message_id, status, event_key, failure_code=None):
    event = {
        "eventType": "message_status", "waMessageId": message_id, "status": status,
        "timestamp": "1710000000", "eventKey": event_key, "phoneNumberId": "phone-analytics",
    }
    if failure_code:
        event["failureCode"] = failure_code
    return event


def test_status_webhooks_correlate_monotonically_without_duplicate_counts(client, database, monkeypatch):
    headers, broadcast_id, _sender = _accepted_broadcast(client, database, monkeypatch)
    for status, key in [("sent", "sent-1"), ("delivered", "delivered-1"), ("read", "read-1")]:
        assert process_extracted_event(_status("wamid.analytics-1", status, key)) is False
    recipient = database.whatsapp_broadcast_recipients.find_one({"providerMessageId": "wamid.analytics-1"})
    assert recipient["executionStatus"] == "ACCEPTED"
    assert recipient["deliveryStatus"] == "READ"
    assert [item["status"] for item in recipient["deliveryTimeline"]] == ["ACCEPTED", "SENT", "DELIVERED", "READ"]

    # Duplicate and late provider events cannot regress delivery state or append a second timeline entry.
    assert process_extracted_event(_status("wamid.analytics-1", "read", "read-duplicate")) is False
    assert process_extracted_event(_status("wamid.analytics-1", "sent", "sent-late")) is False
    recipient = database.whatsapp_broadcast_recipients.find_one({"providerMessageId": "wamid.analytics-1"})
    assert recipient["deliveryStatus"] == "READ"
    assert len(recipient["deliveryTimeline"]) == 4

    analytics = client.get(f"/whatsapp-broadcasts/{broadcast_id}/analytics", headers=headers)
    assert analytics.status_code == 200
    totals = analytics.json()["data"]["totals"]
    assert totals["totalPrepared"] == totals["eligible"] == totals["read"] == 1
    assert totals["accepted"] == totals["sent"] == totals["delivered"] == 0


def test_confirmed_failure_is_safe_and_never_downgrades_delivered_recipient(client, database, monkeypatch):
    _headers_value, _broadcast_id, _sender = _accepted_broadcast(client, database, monkeypatch)
    assert process_extracted_event(_status("wamid.analytics-1", "failed", "failed-1", "131026")) is False
    recipient = database.whatsapp_broadcast_recipients.find_one({"providerMessageId": "wamid.analytics-1"})
    assert recipient["deliveryStatus"] == "FAILED" and recipient["deliveryFailureCode"] == "131026"
    assert process_extracted_event(_status("wamid.analytics-1", "delivered", "delivered-late")) is False
    assert database.whatsapp_broadcast_recipients.find_one({"providerMessageId": "wamid.analytics-1"})["deliveryStatus"] == "FAILED"


def test_report_detail_filters_authorization_and_safe_fields(client, database, monkeypatch):
    headers, broadcast_id, _sender = _accepted_broadcast(client, database, monkeypatch)
    process_extracted_event(_status("wamid.analytics-1", "sent", "sent-report"))
    report = client.get(f"/whatsapp-broadcasts/{broadcast_id}/report?deliveryStatus=SENT&page=1&pageSize=1", headers=headers)
    assert report.status_code == 200 and report.json()["pagination"]["totalRecords"] == 1
    recipient = report.json()["data"][0]
    assert recipient["phone"] and recipient["displayName"] and recipient["renderedText"]
    assert recipient["executionStatus"] == "ACCEPTED" and recipient["deliveryStatus"] == "SENT"
    assert not ({"providerMessageId", "providerComponents", "idempotencyKey", "rawPayload", "accessToken"} & recipient.keys())
    detail = client.get(f"/whatsapp-broadcasts/{broadcast_id}/recipients/{recipient['id']}", headers=headers)
    assert detail.status_code == 200 and detail.json()["data"]["timeline"][-1]["status"] == "SENT"

    _user(database, "analytics-counsellor@example.com", UserRole.COUNSELLOR.value)
    denied = client.get(f"/whatsapp-broadcasts/{broadcast_id}/analytics", headers=_headers(client, "analytics-counsellor@example.com"))
    assert denied.status_code == 403


def test_single_send_status_remains_compatible_without_broadcast_recipient(database):
    database.whatsapp_messages.insert_one({
        "providerMessageId": "wamid.single-send", "status": "ACCEPTED", "direction": "OUTBOUND",
        "messageType": "TEMPLATE", "createdAt": datetime.now(timezone.utc),
    })
    assert process_extracted_event(_status("wamid.single-send", "delivered", "single-delivered")) is False
    assert database.whatsapp_messages.find_one({"providerMessageId": "wamid.single-send"})["status"] == "DELIVERED"
    assert database.whatsapp_broadcast_recipients.count_documents({"providerMessageId": "wamid.single-send"}) == 0


def test_analytics_indexes_exist(database):
    indexes = database.whatsapp_broadcast_recipients.index_information()
    assert {"uq_whatsapp_broadcast_recipient_provider_message", "ix_whatsapp_broadcast_recipient_report"}.issubset(indexes)

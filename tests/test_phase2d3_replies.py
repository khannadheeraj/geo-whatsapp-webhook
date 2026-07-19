from datetime import datetime, timedelta
from unittest.mock import Mock

from app.models.crm_model import WHATSAPP_CHANNEL
from test_phase2d1_inbox import _headers, _message, _seed


def _window(database, conversation_id, age=timedelta(hours=1)):
    _message(database, conversation_id, created_at=datetime.now() - age, text="Need help")


def _enable(database):
    contact = database.contacts.find_one({"displayName": "Asha Sen"})
    database.contacts.update_one({"_id": contact["_id"]}, {"$set": {"isActive": True}})
    database.contact_preferences.insert_one({"contactId": contact["_id"], "channel": WHATSAPP_CHANNEL, "whatsappAllowed": True, "marketingAllowed": False, "doNotContact": False})


def test_reply_authorization_and_unknown_number(client, database, monkeypatch):
    _admin, _owner, _other, matched, unknown = _seed(database); _enable(database); _window(database, matched); _window(database, unknown)
    monkeypatch.setattr("app.services.whatsapp_inbox_service.send_whatsapp_text", lambda *args: {"success": True, "response": {"messages": [{"id": "wamid.auth"}]}})
    assert client.post(f"/whatsapp-conversations/{matched}/replies", headers={**_headers(client, "admin@example.com"), "Idempotency-Key": "reply-admin-01"}, json={"text": "Hello"}).status_code == 200
    assert client.post(f"/whatsapp-conversations/{matched}/replies", headers={**_headers(client, "owner@example.com"), "Idempotency-Key": "reply-owner-01"}, json={"text": "Hello"}).status_code == 200
    assert client.post(f"/whatsapp-conversations/{matched}/replies", headers={**_headers(client, "other@example.com"), "Idempotency-Key": "reply-other-01"}, json={"text": "Hello"}).status_code == 403
    assert client.post(f"/whatsapp-conversations/{unknown}/replies", headers={**_headers(client, "owner@example.com"), "Idempotency-Key": "reply-unknown-01"}, json={"text": "Hello"}).status_code == 403


def test_window_empty_text_suppression_and_persistence(client, database, monkeypatch):
    _admin, _owner, _other, matched, _unknown = _seed(database); _enable(database); _window(database, matched)
    monkeypatch.setattr("app.services.whatsapp_inbox_service.send_whatsapp_text", lambda *args: {"success": True, "response": {"messages": [{"id": "wamid.persist"}]}})
    headers = {**_headers(client, "admin@example.com"), "Idempotency-Key": "reply-persist-01"}
    assert client.post(f"/whatsapp-conversations/{matched}/replies", headers=headers, json={"text": "   "}).status_code == 422
    response = client.post(f"/whatsapp-conversations/{matched}/replies", headers=headers, json={"text": "  Exact reply  "})
    assert response.status_code == 200
    message = database.whatsapp_messages.find_one({"providerMessageId": "wamid.persist"})
    assert message["direction"] == "OUTBOUND" and message["type"] == "TEXT" and message["status"] == "ACCEPTED"
    assert "rawProviderPayload" not in str(message) and "access_token" not in str(message)


def test_expired_missing_and_contact_ineligible_replies_are_blocked(client, database, monkeypatch):
    _admin, _owner, _other, matched, _unknown = _seed(database); _enable(database)
    monkeypatch.setattr("app.services.whatsapp_inbox_service.send_whatsapp_text", lambda *args: {"success": True, "response": {"messages": [{"id": "wamid.blocked"}]}})
    headers = {**_headers(client, "admin@example.com"), "Idempotency-Key": "reply-block-01"}
    assert client.post(f"/whatsapp-conversations/{matched}/replies", headers=headers, json={"text": "Hello"}).status_code == 422
    _message(database, matched, created_at=datetime(2020, 1, 1), text="Old request")
    assert client.post(f"/whatsapp-conversations/{matched}/replies", headers={**headers, "Idempotency-Key": "reply-expired-01"}, json={"text": "Hello"}).status_code == 422
    database.contact_preferences.update_one({"contactId": database.contacts.find_one({"displayName": "Asha Sen"})["_id"], "channel": WHATSAPP_CHANNEL}, {"$set": {"whatsappAllowed": False, "doNotContact": True}})
    assert client.post(f"/whatsapp-conversations/{matched}/replies", headers={**headers, "Idempotency-Key": "reply-suppressed-01"}, json={"text": "Hello"}).status_code == 422


def test_same_key_replays_without_meta_call_and_failure_is_safe(client, database, monkeypatch):
    _admin, _owner, _other, matched, _unknown = _seed(database); _enable(database); _window(database, matched)
    send = Mock(return_value={"success": True, "response": {"messages": [{"id": "wamid.once"}]}}); monkeypatch.setattr("app.services.whatsapp_inbox_service.send_whatsapp_text", send)
    headers = {**_headers(client, "admin@example.com"), "Idempotency-Key": "reply-replay-01"}
    first = client.post(f"/whatsapp-conversations/{matched}/replies", headers=headers, json={"text": "Hello"}); second = client.post(f"/whatsapp-conversations/{matched}/replies", headers=headers, json={"text": "Hello"})
    assert first.status_code == second.status_code == 200 and send.call_count == 1
    monkeypatch.setattr("app.services.whatsapp_inbox_service.send_whatsapp_text", lambda *args: {"success": False, "error": "WHATSAPP_API_ERROR", "response": {"access_token": "secret"}})
    failure = client.post(f"/whatsapp-conversations/{matched}/replies", headers={**_headers(client, "admin@example.com"), "Idempotency-Key": "reply-failure-01"}, json={"text": "Again"})
    assert failure.status_code == 422 and "secret" not in failure.text

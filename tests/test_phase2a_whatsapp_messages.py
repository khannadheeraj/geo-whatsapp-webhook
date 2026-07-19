import hashlib
import hmac
import json
from datetime import datetime

from app.repositories import whatsapp_message_repository
from app.services.whatsapp_extractor import extract_whatsapp_events
from app.services.whatsapp_message_service import record_outbound_template_message


TEST_APP_SECRET = b"test-only-meta-app-secret-32-characters"


def _signature(raw_body: bytes) -> str:
    digest = hmac.new(TEST_APP_SECRET, raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _post(client, raw_body: bytes):
    return client.post(
        "/webhooks/whatsapp",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _signature(raw_body),
        },
    )


def test_conversation_upsert_keeps_mutable_paths_out_of_set_on_insert(monkeypatch):
    calls = []

    class ConversationCollection:
        def update_one(self, identity, update, upsert=False):
            calls.append((identity, update, upsert))
            assert not (set(update["$set"]) & set(update["$setOnInsert"]))

        def find_one(self, identity):
            return {"_id": "conversation-id", **identity}

    monkeypatch.setattr(
        "app.repositories.whatsapp_message_repository.get_collection",
        lambda name: ConversationCollection(),
    )
    identity = {"channel": "WHATSAPP", "phoneNumberId": "business-1", "normalizedPhone": "919876543210"}
    whatsapp_message_repository.upsert_conversation(
        identity,
        {"contactId": "contact-id", "leadId": "lead-id", "conversationId": "ignored", "updatedAt": datetime(2026, 7, 19)},
        {**identity, "createdAt": datetime(2026, 7, 19)},
    )

    _, update, upsert = calls[0]
    assert upsert is True
    assert update["$set"]["contactId"] == "contact-id"
    assert update["$set"]["leadId"] == "lead-id"
    assert set(update["$setOnInsert"]) == {"channel", "phoneNumberId", "normalizedPhone", "createdAt"}


def test_extractor_normalizes_text_buttons_templates_and_omits_raw_payloads():
    payload = {
        "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "business-1"},
            "messages": [
                {"id": "m-text", "from": "919876543210", "timestamp": "100", "type": "text", "text": {"body": "  Hello   GEO  "}},
                {"id": "m-button", "from": "919876543210", "timestamp": "101", "type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": "yes", "title": " Yes "}}},
                {"id": "m-list", "from": "919876543210", "timestamp": "102", "type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"id": "course-1", "title": "UPSC"}}},
                {"id": "m-template", "from": "919876543210", "timestamp": "103", "type": "template", "template": {"name": "welcome", "language": {"code": "en_US"}}},
            ],
        }}]}]
    }

    events = extract_whatsapp_events(payload)

    assert events[0]["text"] == "Hello GEO"
    assert events[1]["replyType"] == "BUTTON_REPLY"
    assert events[1]["buttonPayload"] == "yes"
    assert events[2]["replyType"] == "LIST_REPLY"
    assert events[3]["templateName"] == "welcome"
    assert events[3]["templateLanguage"] == "en_US"
    assert all("rawMessage" not in event and "rawValue" not in event for event in events)


def test_verified_inbound_is_linked_and_replay_does_not_repeat_legacy_handler(
    client, database, monkeypatch
):
    contact_id = database.contacts.insert_one({
        "entityType": "CONTACT", "normalizedPhone": "919876543210"
    }).inserted_id
    lead_id = database.leads.insert_one({
        "entityType": "ADMISSION_LEAD", "contactId": contact_id, "isActive": True
    }).inserted_id
    processed = []
    monkeypatch.setattr(
        "app.api.routes.whatsapp_webhook.process_text_message", processed.append
    )
    raw_body = (
        b'{"entry":[{"changes":[{"value":{"metadata":{"phone_number_id":"business-1"},'
        b'"messages":[{"id":"wamid.inbound-1","from":"919876543210","timestamp":"1700000000",'
        b'"type":"text","text":{"body":"Please call me"}}]}}]}]}'
    )

    assert _post(client, raw_body).status_code == 200
    assert _post(client, raw_body).status_code == 200

    message = database.whatsapp_messages.find_one({"providerMessageId": "wamid.inbound-1"})
    conversation = database.conversations.find_one({"_id": message["conversationId"]})
    assert message["contactId"] == contact_id
    assert message["leadId"] == lead_id
    assert message["renderedText"] == "Please call me"
    assert conversation["reconciliationStatus"] == "MATCHED"
    assert database.whatsapp_messages.count_documents({}) == 1
    assert database.whatsapp_events.count_documents({}) == 1
    assert len(processed) == 1
    assert database.raw_webhooks.count_documents({}) == 0


def test_unknown_number_is_retained_for_reconciliation(client, database):
    raw_body = (
        b'{"entry":[{"changes":[{"value":{"metadata":{"phone_number_id":"business-1"},'
        b'"messages":[{"id":"wamid.unknown-1","from":"919812345678","timestamp":"1700000000",'
        b'"type":"interactive","interactive":{"type":"button_reply",'
        b'"button_reply":{"id":"interested","title":"Interested"}}}]}}]}]}'
    )

    assert _post(client, raw_body).status_code == 200

    message = database.whatsapp_messages.find_one({"providerMessageId": "wamid.unknown-1"})
    conversation = database.conversations.find_one({"_id": message["conversationId"]})
    assert message["contactId"] is None
    assert message["selectedButton"] == {"id": "interested", "title": "Interested"}
    assert conversation["normalizedPhone"] == "919812345678"
    assert conversation["reconciliationStatus"] == "UNKNOWN_NUMBER"


def test_outbound_template_preserves_rendered_text_and_statuses_are_monotonic(
    client, database
):
    record_outbound_template_message(
        provider_message_id="wamid.outbound-1",
        phone="9876543210",
        template_name="admission_welcome",
        template_language="en_US",
        rendered_text="Hello Asha, your rendered admission message.",
        accepted_at=datetime(2026, 7, 18, 10, 0, 0),
    )

    for status, timestamp in [("read", "1700000300"), ("delivered", "1700000200"), ("sent", "1700000100")]:
        raw_body = json.dumps({
            "entry": [{"changes": [{"value": {
                "metadata": {"phone_number_id": "business-1"},
                "statuses": [{
                    "id": "wamid.outbound-1",
                    "recipient_id": "919876543210",
                    "status": status,
                    "timestamp": timestamp,
                }],
            }}]}]
        }, separators=(",", ":")).encode()
        assert _post(client, raw_body).status_code == 200

    message = database.whatsapp_messages.find_one({"providerMessageId": "wamid.outbound-1"})
    assert message["status"] == "READ"
    assert message["acceptedAt"] == datetime(2026, 7, 18, 10, 0, 0)
    assert message["sentAt"] < message["deliveredAt"] < message["readAt"]
    assert message["renderedText"] == "Hello Asha, your rendered admission message."


def test_failed_status_keeps_only_sanitized_temporary_details(client, database):
    raw_body = (
        b'{"entry":[{"changes":[{"value":{"statuses":[{"id":"wamid.failed-1",'
        b'"recipient_id":"919876543210","status":"failed","timestamp":"1700000000",'
        b'"errors":[{"code":131026,"title":"Undeliverable",'
        b'"message":"Message undeliverable","error_data":{"details":"Recipient unavailable"},'
        b'"href":"https://sensitive.example"}]}]}}]}]}'
    )

    assert _post(client, raw_body).status_code == 200

    message = database.whatsapp_messages.find_one({"providerMessageId": "wamid.failed-1"})
    details = database.whatsapp_failure_details.find_one({"providerMessageId": "wamid.failed-1"})
    event = database.whatsapp_events.find_one({"waMessageId": "wamid.failed-1"})
    assert message["status"] == "FAILED"
    assert message["failureCode"] == "131026"
    assert details["details"] == {"title": "Undeliverable", "details": "Recipient unavailable"}
    assert details["expiresAt"] > details["createdAt"]
    assert "failureDetails" not in event
    assert "errors" not in event
    assert "href" not in str(details)


def test_status_before_sender_correlation_enriches_without_regression(client, database):
    raw_body = json.dumps({
        "entry": [{"changes": [{"value": {"statuses": [{
            "id": "wamid.race-1",
            "recipient_id": "919876543210",
            "status": "read",
            "timestamp": "1700000300",
        }]}}]}]
    }, separators=(",", ":")).encode()
    assert _post(client, raw_body).status_code == 200

    record_outbound_template_message(
        provider_message_id="wamid.race-1",
        phone="9876543210",
        template_name="late_correlation",
        rendered_text="Rendered before send and retained after webhook correlation.",
        accepted_at=datetime(2023, 11, 14, 22, 15, 0),
    )

    message = database.whatsapp_messages.find_one({"providerMessageId": "wamid.race-1"})
    assert message["status"] == "READ"
    assert message["templateName"] == "late_correlation"
    assert message["renderedText"] == "Rendered before send and retained after webhook correlation."

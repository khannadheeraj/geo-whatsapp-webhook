import hashlib
import hmac
import json

import pytest

from app.api.routes import whatsapp_webhook as webhook_route


TEST_APP_SECRET = b"test-only-meta-app-secret-32-characters"


def signature_for(raw_body: bytes) -> str:
    digest = hmac.new(TEST_APP_SECRET, raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def post_raw(client, raw_body: bytes, signature=None):
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
    return client.post("/webhooks/whatsapp", content=raw_body, headers=headers)


def test_valid_signature_allows_webhook_processing(client, database):
    raw_body = b'{"object":"whatsapp_business_account","entry":[]}'
    response = post_raw(client, raw_body, signature_for(raw_body))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert database.raw_webhooks.count_documents({}) == 0


def test_invalid_signature_is_rejected_with_safe_error(client, database):
    response = post_raw(client, b"{}", "sha256=" + ("0" * 64))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "WEBHOOK_SIGNATURE_INVALID"
    assert response.json()["error"]["message"] == "Webhook signature validation failed."
    assert database.raw_webhooks.count_documents({}) == 0
    assert "traceback" not in response.text.lower()


def test_missing_signature_is_rejected(client, database):
    response = post_raw(client, b"{}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "WEBHOOK_SIGNATURE_INVALID"
    assert database.raw_webhooks.count_documents({}) == 0


@pytest.mark.parametrize(
    "signature",
    ["", "sha1=" + ("0" * 40), "sha256=not-hex", "sha256=" + ("0" * 63), "sha256=" + ("0" * 65)],
)
def test_malformed_signature_is_rejected(client, signature):
    response = post_raw(client, b"{}", signature)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "WEBHOOK_SIGNATURE_INVALID"


def test_changed_body_after_signature_generation_is_rejected(client):
    signed_body = b'{"entry":[{"id":"original"}]}'
    changed_body = b'{"entry":[{"id":"changed"}]}'
    response = post_raw(client, changed_body, signature_for(signed_body))
    assert response.status_code == 401


def test_signature_is_checked_against_exact_raw_body(client, database):
    compact_body = b'{"entry":[]}'
    spaced_body = b'{ "entry": [] }'
    assert json.loads(compact_body) == json.loads(spaced_body)
    rejected = post_raw(client, spaced_body, signature_for(compact_body))
    assert rejected.status_code == 401
    accepted = post_raw(client, spaced_body, signature_for(spaced_body))
    assert accepted.status_code == 200
    assert database.raw_webhooks.count_documents({}) == 0


def test_verified_payload_reaches_existing_extractor_and_handler(client, database, monkeypatch):
    raw_body = b'{"object":"whatsapp_business_account","entry":[{"id":"sentinel-entry"}]}'
    received_payloads = []
    processed_events = []
    event = {
        "eventType": "incoming_message",
        "eventKey": "message:sentinel-id",
        "waMessageId": "sentinel-id",
        "messageType": "text",
        "text": "sentinel-message-text",
        "from": "919999999999",
    }

    def fake_extract(payload):
        received_payloads.append(payload)
        return [event]

    monkeypatch.setattr(webhook_route, "extract_whatsapp_events", fake_extract)
    monkeypatch.setattr(webhook_route, "process_extracted_event", lambda value: True)
    monkeypatch.setattr(webhook_route, "process_text_message", processed_events.append)

    response = post_raw(client, raw_body, signature_for(raw_body))
    assert response.status_code == 200
    assert received_payloads == [json.loads(raw_body)]
    assert processed_events == [event]


def test_app_secret_signature_and_raw_payload_do_not_appear_in_errors_or_logs(client, caplog, capsys):
    raw_body = b'{"privateSentinel":"do-not-log-this-payload"}'
    response = post_raw(client, raw_body, "sha256=" + ("f" * 64))
    captured = capsys.readouterr()
    combined = response.text + caplog.text + captured.out + captured.err
    assert "test-only-meta-app-secret-32-characters" not in combined
    assert "do-not-log-this-payload" not in combined
    assert "sha256=" + ("f" * 64) not in combined


def test_get_challenge_verification_is_unchanged(client):
    response = client.get("/webhooks/whatsapp", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "test-webhook-verification-token",
        "hub.challenge": "challenge-value",
    })
    assert response.status_code == 200
    assert response.text == "challenge-value"

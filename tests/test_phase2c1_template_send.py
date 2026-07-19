from app.models.crm_model import ADMISSION_LEAD_ENTITY_TYPE, CONTACT_ENTITY_TYPE, WHATSAPP_CHANNEL
from app.models.user_model import UserRole
from app.repositories.user_repository import insert_staff_user
from app.services.password_service import hash_password


PASSWORD = "Temporary!Pass4827"


def _user(database, email, role):
    return insert_staff_user({
        "email": email, "displayName": email.split("@")[0], "role": role,
        "passwordHash": hash_password(PASSWORD), "isActive": True, "mustChangePassword": False,
    })


def _headers(client, email):
    response = client.post("/auth/login", json={"emailId": email, "password": PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['accessToken']}"}


def _seed_contact_template(database, *, assigned_user_id=None, do_not_contact=False, phone="919876543210"):
    contact_id = database.contacts.insert_one({
        "entityType": CONTACT_ENTITY_TYPE, "normalizedPhone": phone, "isActive": True,
    }).inserted_id
    database.contact_preferences.insert_one({
        "contactId": contact_id, "channel": WHATSAPP_CHANNEL, "whatsappAllowed": True,
        "marketingAllowed": False, "doNotContact": do_not_contact,
    })
    if assigned_user_id:
        database.leads.insert_one({
            "entityType": ADMISSION_LEAD_ENTITY_TYPE, "contactId": contact_id,
            "isActive": True, "assignedCounsellorId": assigned_user_id,
        })
    template_id = database.whatsapp_templates.insert_one({
        "businessAccountId": "waba-test-1", "providerTemplateKey": "welcome-id",
        "name": "admission_welcome", "language": "en_US", "category": "UTILITY",
        "status": "APPROVED", "isActive": True,
        "headers": [{"type": "HEADER", "format": "TEXT", "text": "Welcome {{1}}"}],
        "body": {"type": "BODY", "text": "Hello {{1}}, batch {{2}} is open."},
        "footer": {"type": "FOOTER", "text": "GEO IAS"},
        "buttons": [{"type": "QUICK_REPLY", "text": "Call me"}],
        "variables": [],
    }).inserted_id
    return contact_id, template_id


def _configure(monkeypatch):
    monkeypatch.setattr("app.services.whatsapp_template_send_service.WHATSAPP_WABA_ID", "waba-test-1")
    monkeypatch.setattr("app.services.whatsapp_template_send_service.WHATSAPP_PHONE_NUMBER_ID", "phone-number-id")


def _payload(contact_id, template_id):
    return {"contactId": str(contact_id), "templateId": str(template_id), "variableValues": ["Asha", "Asha", "Foundation"]}


def test_super_admin_send_records_normalized_message_activity_and_audit(client, database, monkeypatch):
    admin = _user(database, "admin@example.com", UserRole.SUPER_ADMIN.value)
    contact_id, template_id = _seed_contact_template(database)
    _configure(monkeypatch)
    sent = []
    monkeypatch.setattr(
        "app.services.whatsapp_template_send_service.send_whatsapp_template",
        lambda *args, **kwargs: sent.append((args, kwargs)) or {"success": True, "response": {"messages": [{"id": "wamid.send-1"}]}},
    )

    response = client.post("/whatsapp-template-sends", headers={**_headers(client, "admin@example.com"), "Idempotency-Key": "send-success-001"}, json=_payload(contact_id, template_id))

    assert response.status_code == 200
    assert response.json()["data"] == {
        "contactId": str(contact_id), "templateId": str(template_id), "providerMessageId": "wamid.send-1",
        "status": "ACCEPTED", "renderedText": "Welcome Asha\n\nHello Asha, batch Foundation is open.\n\nGEO IAS\n\nCall me", "idempotentReplay": False,
    }
    assert sent[0][0] == ("919876543210", "admission_welcome")
    assert sent[0][1]["language_code"] == "en_US"
    assert sent[0][1]["template_components"] == [
        {"type": "header", "parameters": [{"type": "text", "text": "Asha"}]},
        {"type": "body", "parameters": [{"type": "text", "text": "Asha"}, {"type": "text", "text": "Foundation"}]},
    ]
    message = database.whatsapp_messages.find_one({"providerMessageId": "wamid.send-1"})
    assert message["status"] == "ACCEPTED"
    assert message["renderedText"] == response.json()["data"]["renderedText"]
    assert database.lead_activities.find_one({"type": "WHATSAPP_TEMPLATE_SENT", "contactId": contact_id})
    assert database.audit_logs.find_one({"action": "WHATSAPP_TEMPLATE_SEND", "outcome": "SUCCEEDED"})
    assert admin


def test_only_assigned_counsellor_or_super_admin_may_send(client, database, monkeypatch):
    owner = _user(database, "owner@example.com", UserRole.COUNSELLOR.value)
    _user(database, "other@example.com", UserRole.COUNSELLOR.value)
    contact_id, template_id = _seed_contact_template(database, assigned_user_id=owner["_id"])
    _configure(monkeypatch)
    monkeypatch.setattr("app.services.whatsapp_template_send_service.send_whatsapp_template", lambda *args, **kwargs: {"success": True, "response": {"messages": [{"id": "wamid.owner"}]}})

    forbidden = client.post("/whatsapp-template-sends", headers={**_headers(client, "other@example.com"), "Idempotency-Key": "send-other-001"}, json=_payload(contact_id, template_id))
    allowed = client.post("/whatsapp-template-sends", headers={**_headers(client, "owner@example.com"), "Idempotency-Key": "send-owner-001"}, json=_payload(contact_id, template_id))

    assert forbidden.status_code == 403
    assert allowed.status_code == 200


def test_variable_count_and_suppression_block_meta_send(client, database, monkeypatch):
    _user(database, "admin@example.com", UserRole.SUPER_ADMIN.value)
    contact_id, template_id = _seed_contact_template(database, do_not_contact=True)
    _configure(monkeypatch)
    send = __import__("unittest.mock").mock.Mock()
    monkeypatch.setattr("app.services.whatsapp_template_send_service.send_whatsapp_template", send)
    headers = _headers(client, "admin@example.com")

    invalid = client.post("/whatsapp-template-sends", headers={**headers, "Idempotency-Key": "send-invalid-001"}, json={**_payload(contact_id, template_id), "variableValues": ["Asha"]})
    suppressed = client.post("/whatsapp-template-sends", headers={**headers, "Idempotency-Key": "send-suppressed-001"}, json=_payload(contact_id, template_id))

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "CONTACT_WHATSAPP_NOT_ELIGIBLE"
    assert suppressed.status_code == 422
    assert suppressed.json()["error"]["code"] == "CONTACT_WHATSAPP_NOT_ELIGIBLE"
    assert send.call_count == 0


def test_exact_variable_count_is_enforced_for_eligible_contact(client, database, monkeypatch):
    _user(database, "admin@example.com", UserRole.SUPER_ADMIN.value)
    contact_id, template_id = _seed_contact_template(database)
    _configure(monkeypatch)
    monkeypatch.setattr("app.services.whatsapp_template_send_service.send_whatsapp_template", __import__("unittest.mock").mock.Mock())

    response = client.post("/whatsapp-template-sends", headers={**_headers(client, "admin@example.com"), "Idempotency-Key": "send-variable-001"}, json={**_payload(contact_id, template_id), "variableValues": ["Asha"]})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TEMPLATE_VARIABLE_COUNT_INVALID"


def test_normalized_template_without_placeholders_accepts_empty_values_and_ignores_examples(client, database, monkeypatch):
    _user(database, "admin@example.com", UserRole.SUPER_ADMIN.value)
    contact_id, template_id = _seed_contact_template(database)
    database.whatsapp_templates.update_one({"_id": template_id}, {"$set": {
        "headers": [{"type": "HEADER", "format": "TEXT", "text": "Admission update", "example": {"header_text": ["sample only"]}}],
        "body": {"type": "BODY", "text": "Your application is under review.", "example": {"body_text": [["sample only"]]}},
        "buttons": [{"type": "URL", "text": "Open portal", "url": "https://example.test/portal"}],
    }})
    _configure(monkeypatch)
    monkeypatch.setattr(
        "app.services.whatsapp_template_send_service.send_whatsapp_template",
        lambda *args, **kwargs: {"success": True, "response": {"messages": [{"id": "wamid.no-vars-1"}]}},
    )

    response = client.post(
        "/whatsapp-template-sends",
        headers={**_headers(client, "admin@example.com"), "Idempotency-Key": "send-no-vars-001"},
        json={"contactId": str(contact_id), "templateId": str(template_id), "variableValues": []},
    )

    assert response.status_code == 200


def test_idempotency_replays_success_without_resending(client, database, monkeypatch):
    _user(database, "admin@example.com", UserRole.SUPER_ADMIN.value)
    contact_id, template_id = _seed_contact_template(database)
    _configure(monkeypatch)
    send = __import__("unittest.mock").mock.Mock(return_value={"success": True, "response": {"messages": [{"id": "wamid.replay-1"}]}})
    monkeypatch.setattr("app.services.whatsapp_template_send_service.send_whatsapp_template", send)
    headers = {**_headers(client, "admin@example.com"), "Idempotency-Key": "send-replay-001"}

    first = client.post("/whatsapp-template-sends", headers=headers, json=_payload(contact_id, template_id))
    second = client.post("/whatsapp-template-sends", headers=headers, json=_payload(contact_id, template_id))

    assert first.status_code == second.status_code == 200
    assert second.json()["data"]["idempotentReplay"] is True
    assert send.call_count == 1
    assert database.whatsapp_template_send_operations.count_documents({}) == 1


def test_meta_failure_is_sanitized_and_not_persisted_raw(client, database, monkeypatch):
    _user(database, "admin@example.com", UserRole.SUPER_ADMIN.value)
    contact_id, template_id = _seed_contact_template(database)
    _configure(monkeypatch)
    monkeypatch.setattr(
        "app.services.whatsapp_template_send_service.send_whatsapp_template",
        lambda *args, **kwargs: {"success": False, "error": "WHATSAPP_API_ERROR", "response": {"access_token": "never-store", "message": "provider-private-detail"}},
    )

    response = client.post("/whatsapp-template-sends", headers={**_headers(client, "admin@example.com"), "Idempotency-Key": "send-failure-001"}, json=_payload(contact_id, template_id))

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "WHATSAPP_TEMPLATE_SEND_FAILED"
    assert "provider-private-detail" not in response.text
    assert "never-store" not in str(database.whatsapp_template_send_operations.find_one())
    assert database.audit_logs.find_one({"action": "WHATSAPP_TEMPLATE_SEND", "outcome": "FAILED"})


def test_template_send_idempotency_indexes_exist(database):
    indexes = database.whatsapp_template_send_operations.index_information()
    assert "uq_whatsapp_template_send_actor_key" in indexes
    assert "ix_whatsapp_template_send_contact_created" in indexes

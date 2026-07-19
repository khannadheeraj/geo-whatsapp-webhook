from app.models.crm_model import ADMISSION_LEAD_ENTITY_TYPE, CONTACT_ENTITY_TYPE, WHATSAPP_CHANNEL
from app.models.user_model import UserRole
from test_phase2c1_template_send import _headers, _user


def _template(database, category="MARKETING"):
    return database.whatsapp_templates.insert_one({"businessAccountId": "waba-broadcast", "providerTemplateKey": f"broadcast-{category}", "name": "broadcast_template", "language": "en_US", "category": category, "status": "APPROVED", "isActive": True, "headers": [], "body": {"text": "Hello {{1}}, {{2}}"}, "footer": {"text": "GEO IAS"}, "buttons": [], "variables": []}).inserted_id


def _contact(database, name, phone, **preference):
    contact = database.contacts.insert_one({"entityType": CONTACT_ENTITY_TYPE, "displayName": name, "firstName": name, "normalizedPhone": phone, "isActive": preference.pop("isActive", True), "city": "Kolkata"}).inserted_id
    database.contact_preferences.insert_one({"contactId": contact, "channel": WHATSAPP_CHANNEL, "whatsappAllowed": True, "marketingAllowed": True, "doNotContact": False, **preference})
    return contact


def _lead(database, contact, **overrides):
    database.leads.insert_one({"entityType": ADMISSION_LEAD_ENTITY_TYPE, "contactId": contact, "isActive": True, "status": "INTERESTED", "priority": "HIGH", "preferredMode": "ONLINE", **overrides})


def _payload(template_id):
    return {"templateId": str(template_id), "recipientFilters": {"contact": {"city": "Kolkata"}, "lead": {"status": "INTERESTED"}}, "variableMappings": [{"source": "CONTACT", "field": "firstName"}, {"source": "LEAD", "field": "preferredMode"}]}


def _create(client, headers, template_id):
    response = client.post("/whatsapp-broadcasts", headers=headers, json=_payload(template_id))
    assert response.status_code == 200
    return response.json()["data"]


def test_broadcasts_are_super_admin_only(client, database, monkeypatch):
    monkeypatch.setattr("app.services.whatsapp_broadcast_service.WHATSAPP_WABA_ID", "waba-broadcast")
    _user(database, "broadcast-admin@example.com", UserRole.SUPER_ADMIN.value); _user(database, "broadcast-owner@example.com", UserRole.COUNSELLOR.value)
    template_id = _template(database)
    assert client.post("/whatsapp-broadcasts", headers=_headers(client, "broadcast-owner@example.com"), json=_payload(template_id)).status_code == 403
    assert _create(client, _headers(client, "broadcast-admin@example.com"), template_id)["version"] == 1


def test_preparation_classifies_recipients_renders_snapshot_and_paginates(client, database, monkeypatch):
    monkeypatch.setattr("app.services.whatsapp_broadcast_service.WHATSAPP_WABA_ID", "waba-broadcast")
    _user(database, "broadcast-admin@example.com", UserRole.SUPER_ADMIN.value); headers = _headers(client, "broadcast-admin@example.com")
    template_id = _template(database)
    eligible = _contact(database, "Asha", "919876543210"); _lead(database, eligible)
    inactive = _contact(database, "Inactive", "919876543211", isActive=False); _lead(database, inactive)
    dnc = _contact(database, "Dnc", "919876543212", doNotContact=True); _lead(database, dnc)
    disabled = _contact(database, "Disabled", "919876543213", whatsappAllowed=False); _lead(database, disabled)
    no_consent = _contact(database, "Consent", "919876543214", marketingAllowed=False); _lead(database, no_consent)
    missing = _contact(database, "Missing", "919876543215"); _lead(database, missing, preferredMode=None)
    draft = _create(client, headers, template_id)
    prepared = client.post(f"/whatsapp-broadcasts/{draft['id']}/prepare", headers=headers, json={"version": draft["version"]})
    assert prepared.status_code == 200
    counts = prepared.json()["data"]["preparationCounts"]
    assert counts["eligible"] == 1 and counts["skipped"] == 4 and counts["rejected"] == 1
    page = client.get(f"/whatsapp-broadcasts/{draft['id']}/recipients", headers=headers, params={"status": "ELIGIBLE", "pageSize": 1})
    assert page.status_code == 200 and page.json()["data"][0]["renderedText"] == "Hello Asha, ONLINE\n\nGEO IAS"


def test_preparation_replaces_draft_results_with_version_protection(client, database, monkeypatch):
    monkeypatch.setattr("app.services.whatsapp_broadcast_service.WHATSAPP_WABA_ID", "waba-broadcast")
    _user(database, "broadcast-admin@example.com", UserRole.SUPER_ADMIN.value); headers = _headers(client, "broadcast-admin@example.com")
    template_id = _template(database, "UTILITY"); contact = _contact(database, "Asha", "919876543210"); _lead(database, contact)
    draft = _create(client, headers, template_id)
    assert client.post(f"/whatsapp-broadcasts/{draft['id']}/prepare", headers=headers, json={"version": 1}).status_code == 200
    assert database.whatsapp_broadcast_recipients.count_documents({}) == 1
    assert client.post(f"/whatsapp-broadcasts/{draft['id']}/prepare", headers=headers, json={"version": 1}).status_code == 409
    assert client.post(f"/whatsapp-broadcasts/{draft['id']}/prepare", headers=headers, json={"version": 2}).status_code == 200
    assert database.whatsapp_broadcast_recipients.count_documents({}) == 1


def test_invalid_mapping_is_rejected(client, database, monkeypatch):
    monkeypatch.setattr("app.services.whatsapp_broadcast_service.WHATSAPP_WABA_ID", "waba-broadcast")
    _user(database, "broadcast-admin@example.com", UserRole.SUPER_ADMIN.value); template_id = _template(database)
    payload = _payload(template_id); payload["variableMappings"] = [{"source": "CONTACT", "field": "unknown"}, {"source": "FIXED", "value": "x"}]
    assert client.post("/whatsapp-broadcasts", headers=_headers(client, "broadcast-admin@example.com"), json=payload).status_code == 422


def test_broadcast_indexes_exist(database):
    assert "ix_whatsapp_broadcast_status_created" in database.whatsapp_broadcasts.index_information()
    indexes = database.whatsapp_broadcast_recipients.index_information()
    assert "ix_whatsapp_broadcast_recipient_preview" in indexes and "uq_whatsapp_broadcast_recipient_contact" in indexes

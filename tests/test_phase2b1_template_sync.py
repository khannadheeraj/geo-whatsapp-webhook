from app.models.user_model import UserRole
from app.repositories.user_repository import insert_staff_user
from app.services.password_service import hash_password


PASSWORD = "Temporary!Pass4827"


def _make_user(database, email="admin@example.com", role=UserRole.SUPER_ADMIN.value):
    return insert_staff_user({
        "email": email,
        "displayName": "Template Test User",
        "role": role,
        "passwordHash": hash_password(PASSWORD),
        "isActive": True,
        "mustChangePassword": False,
    })


def _headers(client, email="admin@example.com"):
    response = client.post("/auth/login", json={"emailId": email, "password": PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['accessToken']}"}


class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def _configure_meta(monkeypatch):
    monkeypatch.setattr("app.services.template_service.WHATSAPP_ACCESS_TOKEN", "test-access-token")
    monkeypatch.setattr("app.services.template_service.WHATSAPP_WABA_ID", "waba-test-1")
    monkeypatch.setattr("app.services.whatsapp_template_sync_service.WHATSAPP_WABA_ID", "waba-test-1")


def test_manual_sync_paginates_normalizes_deactivates_and_audits(client, database, monkeypatch):
    _make_user(database)
    _configure_meta(monkeypatch)
    database.whatsapp_templates.insert_one({
        "businessAccountId": "waba-test-1", "providerTemplateKey": "old-id",
        "language": "en_US", "name": "old_template", "status": "APPROVED", "isActive": True,
    })
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            return _Response(200, {
                "data": [{
                    "id": "template-1", "name": "admission_welcome", "language": "en_US",
                    "status": "APPROVED", "category": "UTILITY",
                    "components": [
                        {"type": "HEADER", "format": "TEXT", "text": "Welcome {{1}}"},
                        {"type": "BODY", "text": "Hi {{1}}, batch {{2}} is open."},
                        {"type": "FOOTER", "text": "GEO IAS"},
                        {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Call me", "payload": "call"}]},
                        {"type": "UNSUPPORTED", "raw": "do-not-persist"},
                    ],
                }],
                "paging": {"next": "https://graph.facebook.com/v20.0/next-page"},
            })
        return _Response(200, {"data": [{
            "id": "template-2", "name": "not_approved", "language": "hi",
            "status": "PENDING", "category": "MARKETING", "components": [],
        }]})

    monkeypatch.setattr("app.services.template_service.requests.get", fake_get)
    response = client.post("/whatsapp-templates/sync", headers=_headers(client))

    assert response.status_code == 200
    assert response.json()["data"] == {
        "fetched": 2, "created": 2, "updated": 0, "skipped": 0, "deactivated": 1,
    }
    assert len(calls) == 2
    assert calls[0][1]["params"]["limit"] == 100
    template = database.whatsapp_templates.find_one({"providerTemplateId": "template-1"})
    assert template["isActive"] is True
    assert template["body"]["text"] == "Hi {{1}}, batch {{2}} is open."
    assert template["variables"] == [
        {"componentType": "HEADER", "position": 1},
        {"componentType": "BODY", "position": 1},
        {"componentType": "BODY", "position": 2},
    ]
    assert template["buttons"] == [{"type": "QUICK_REPLY", "text": "Call me", "payload": "call"}]
    assert "raw" not in str(template)
    assert database.whatsapp_templates.find_one({"providerTemplateKey": "old-id"})["isActive"] is False
    audit = database.audit_logs.find_one({"action": "WHATSAPP_TEMPLATE_SYNC", "outcome": "SUCCEEDED"})
    assert audit["compactMetadata"]["deactivated"] == 1


def test_approved_active_catalogue_and_detail_are_authorized_and_filterable(client, database, monkeypatch):
    admin = _make_user(database)
    monkeypatch.setattr("app.services.whatsapp_template_sync_service.WHATSAPP_WABA_ID", "waba-test-1")
    _make_user(database, "counsellor@example.com", UserRole.COUNSELLOR.value)
    approved_id = database.whatsapp_templates.insert_one({
        "businessAccountId": "waba-test-1", "providerTemplateKey": "template-1", "name": "admission_welcome",
        "normalizedName": "admission_welcome", "language": "en_US", "category": "UTILITY",
        "status": "APPROVED", "isActive": True, "components": [], "variables": [], "headers": [],
        "body": {"type": "BODY", "text": "Hi {{1}}"}, "footer": None, "buttons": [],
    }).inserted_id
    database.whatsapp_templates.insert_one({
        "businessAccountId": "waba-test-1", "providerTemplateKey": "template-2", "name": "pending_template",
        "normalizedName": "pending_template", "language": "en_US", "category": "MARKETING",
        "status": "PENDING", "isActive": False,
    })
    counsellor_headers = _headers(client, "counsellor@example.com")

    assert client.get("/whatsapp-templates").status_code == 401
    listed = client.get(
        "/whatsapp-templates", headers=counsellor_headers,
        params={"search": "WELCOME", "category": "utility", "language": "en_US"},
    )
    assert listed.status_code == 200
    assert listed.json()["pagination"]["totalRecords"] == 1
    assert listed.json()["data"][0]["name"] == "admission_welcome"
    detail = client.get(f"/whatsapp-templates/{approved_id}", headers=counsellor_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["body"]["text"] == "Hi {{1}}"
    assert client.get("/whatsapp-templates/not-an-object-id", headers=counsellor_headers).status_code == 404
    assert client.post("/whatsapp-templates/sync", headers=counsellor_headers).status_code == 403
    assert admin


def test_failed_sync_is_sanitized_and_does_not_deactivate_existing_templates(client, database, monkeypatch):
    _make_user(database)
    _configure_meta(monkeypatch)
    database.whatsapp_templates.insert_one({
        "businessAccountId": "waba-test-1", "providerTemplateKey": "existing", "language": "en_US",
        "status": "APPROVED", "isActive": True,
    })
    monkeypatch.setattr(
        "app.services.template_service.requests.get",
        lambda *args, **kwargs: _Response(500, {"error": {"message": "secret-provider-detail"}}),
    )

    response = client.post("/whatsapp-templates/sync", headers=_headers(client))

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "WHATSAPP_TEMPLATE_SYNC_FAILED"
    assert "secret-provider-detail" not in response.text
    assert database.whatsapp_templates.find_one({"providerTemplateKey": "existing"})["isActive"] is True
    assert database.audit_logs.find_one({"action": "WHATSAPP_TEMPLATE_SYNC", "outcome": "FAILED"})


def test_phase2b1_indexes_exist(database):
    indexes = database.whatsapp_templates.index_information()
    assert "uq_whatsapp_template_provider_language" in indexes
    assert "ix_whatsapp_template_active_catalogue" in indexes
    assert "ix_whatsapp_template_sync_marker" in indexes

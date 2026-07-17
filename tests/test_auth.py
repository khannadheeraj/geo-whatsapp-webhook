from datetime import datetime, timedelta, timezone
import hashlib
import hmac

import jwt
import pytest
from pymongo.errors import DuplicateKeyError

from app.config import get_security_settings
from app import config
from app.errors import ConflictError
from app.models.user_model import UserRole
from app.repositories.user_repository import insert_staff_user
from app.services.bootstrap_service import bootstrap_users
from app.services.password_service import hash_password, verify_password
from app.services.token_service import decode_access_token


PASSWORD = "Temporary!Pass4827"
NEW_PASSWORD = "Replacement!Pass5938"


def make_user(database, email="admin@example.com", role=UserRole.SUPER_ADMIN.value,
              active=True, must_change=False, password=PASSWORD):
    return insert_staff_user({
        "email": email,
        "displayName": "Test User",
        "role": role,
        "passwordHash": hash_password(password),
        "isActive": active,
        "mustChangePassword": must_change,
    })


def login(client, email="admin@example.com", password=PASSWORD):
    return client.post("/auth/login", json={"emailId": email, "password": password})


def auth_header(response):
    return {"Authorization": f"Bearer {response.json()['data']['accessToken']}"}


def test_password_is_argon2_hashed_and_plaintext_not_stored(database):
    user = make_user(database)
    assert user["passwordHash"].startswith("$argon2id$")
    assert PASSWORD not in user["passwordHash"]
    assert "password" not in user
    assert verify_password(user["passwordHash"], PASSWORD)[0]


def test_login_current_user_and_signed_token(client, database):
    user = make_user(database)
    response = login(client)
    assert response.status_code == 200
    assert "passwordHash" not in str(response.json())
    claims = decode_access_token(response.json()["data"]["accessToken"])
    assert claims["sub"] == str(user["_id"])
    me = client.get("/auth/me", headers=auth_header(response))
    assert me.status_code == 200
    assert me.json()["data"]["user"]["role"] == UserRole.SUPER_ADMIN.value


@pytest.mark.parametrize("email,password", [("missing@example.com", PASSWORD), ("admin@example.com", "Wrong!Pass4827")])
def test_invalid_login_is_generic(client, database, email, password):
    make_user(database)
    response = login(client, email, password)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "LOGIN_FAILED"
    assert response.json()["error"]["message"] == "Invalid email or password."


def test_inactive_user_uses_same_generic_login_error(client, database):
    make_user(database, active=False)
    response = login(client)
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid email or password."


def test_forced_password_change_allows_me_but_denies_business_route(client, database):
    make_user(database, must_change=True)
    response = login(client)
    headers = auth_header(response)
    assert client.get("/auth/me", headers=headers).status_code == 200
    denied = client.get("/template/all", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"


def test_password_change_rejects_old_password_and_invalidates_session(client, database):
    make_user(database, must_change=True)
    response = login(client)
    headers = auth_header(response)
    rejected = client.post("/auth/change-password", headers=headers,
                           json={"currentPassword": "Wrong!Pass4827", "newPassword": NEW_PASSWORD})
    assert rejected.status_code == 401
    changed = client.post("/auth/change-password", headers=headers,
                          json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD})
    assert changed.status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 401
    assert login(client, password=PASSWORD).status_code == 401
    assert login(client, password=NEW_PASSWORD).status_code == 200


def test_refresh_rotates_and_replay_revokes_family(client, database):
    make_user(database)
    response = login(client)
    cookie_name = get_security_settings().refresh_cookie_name
    old_cookie = response.cookies.get(cookie_name)
    refreshed = client.post("/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.cookies.get(cookie_name) != old_cookie
    replay = client.post("/auth/refresh", cookies={cookie_name: old_cookie})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "REFRESH_REPLAYED"
    assert client.post("/auth/refresh").status_code == 401


def test_logout_revokes_refresh_session(client, database):
    make_user(database)
    response = login(client)
    access = auth_header(response)
    assert client.post("/auth/logout").status_code == 200
    assert client.post("/auth/refresh").status_code == 401
    assert client.get("/auth/me", headers=access).status_code == 401


def test_invalid_and_expired_tokens_are_rejected(client, database):
    make_user(database)
    assert client.get("/auth/me", headers={"Authorization": "Bearer malformed"}).status_code == 401
    settings = get_security_settings()
    now = datetime.now(timezone.utc)
    expired = jwt.encode({"iss": settings.jwt_issuer, "aud": settings.jwt_audience, "sub": "x", "role": "SUPER_ADMIN",
                          "sid": "x", "ver": 1, "jti": "x", "iat": now - timedelta(hours=2),
                          "exp": now - timedelta(hours=1)}, settings.jwt_secret_key, algorithm="HS256")
    result = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert result.status_code == 401
    assert result.json()["error"]["code"] == "TOKEN_INVALID"


def test_role_enforcement_and_anonymous_rejection(client, database):
    admin = make_user(database)
    counsellor = make_user(database, "counsellor@example.com", UserRole.COUNSELLOR.value)
    assert admin and counsellor
    anonymous = client.get("/users")
    assert anonymous.status_code == 401
    counsellor_login = login(client, "counsellor@example.com")
    assert client.get("/users", headers=auth_header(counsellor_login)).status_code == 403
    admin_login = login(client)
    assert client.get("/users", headers=auth_header(admin_login)).status_code == 200


def test_authenticated_template_route_accepts_both_roles(client, database, monkeypatch):
    make_user(database, "counsellor@example.com", UserRole.COUNSELLOR.value)
    monkeypatch.setattr("app.api.routes.template.get_templates", lambda: [])
    response = login(client, "counsellor@example.com")
    assert client.get("/template/all", headers=auth_header(response)).status_code == 200


def test_webhook_and_health_remain_public(client, database):
    assert client.get("/").status_code == 200
    verification = client.get("/webhooks/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "test-webhook-verification-token", "hub.challenge": "12345"
    })
    assert verification.status_code == 200
    assert verification.text == "12345"
    raw_body = b"{}"
    signature = hmac.new(
        b"test-only-meta-app-secret-32-characters",
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    assert client.post(
        "/webhooks/whatsapp",
        content=raw_body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={signature}"},
    ).status_code == 200


def manifest():
    return [
        {"email": "admin1@example.com", "displayName": "Admin One", "role": "SUPER_ADMIN"},
        {"email": "admin2@example.com", "displayName": "Admin Two", "role": "SUPER_ADMIN"},
        {"email": "c1@example.com", "displayName": "Counsellor One", "role": "COUNSELLOR"},
        {"email": "c2@example.com", "displayName": "Counsellor Two", "role": "COUNSELLOR"},
        {"email": "c3@example.com", "displayName": "Counsellor Three", "role": "COUNSELLOR"},
    ]


def test_bootstrap_first_run_idempotency_and_no_plaintext(database):
    first = bootstrap_users(manifest(), lambda _: PASSWORD)
    second = bootstrap_users(manifest(), lambda _: pytest.fail("password must not be requested for existing users"))
    assert first == {"created": 5, "existing": 0, "total": 5}
    assert second == {"created": 0, "existing": 5, "total": 5}
    assert database.users.count_documents({"entityType": "STAFF_USER"}) == 5
    assert database.users.count_documents({"passwordHash": PASSWORD}) == 0
    assert all(user["mustChangePassword"] for user in database.users.find({"entityType": "STAFF_USER"}))


def test_duplicate_staff_email_is_prevented(database):
    make_user(database)
    with pytest.raises(ConflictError):
        make_user(database)


def test_required_indexes_exist(database):
    assert "uq_staff_user_email" in database.users.index_information()
    sessions = database.user_sessions.index_information()
    assert "uq_user_session_token_hash" in sessions
    assert sessions["ttl_user_session_expiry"]["expireAfterSeconds"] == 0
    assert "ix_audit_entity_time" in database.audit_logs.index_information()


def test_safe_validation_error_has_request_id(client, database):
    response = client.post("/auth/login", json={"emailId": "x"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "REQUEST_VALIDATION_FAILED"
    assert error["requestId"]
    assert "traceback" not in str(response.json()).lower()


def test_auth_cookie_mutations_reject_untrusted_browser_origin(client, database):
    make_user(database)
    response = client.post("/auth/login", headers={"Origin": "https://untrusted.example"},
                           json={"emailId": "admin@example.com", "password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"


def test_refresh_cookie_uses_http_only_scoped_security_attributes(client, database):
    make_user(database)
    response = login(client)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/auth" in cookie


def test_production_configuration_requires_meta_secret_and_secure_cookie(monkeypatch):
    monkeypatch.setattr(config, "ENVIRONMENT", "PROD")
    monkeypatch.setattr(config, "MONGODB_URI", "mongodb://configuration-test.invalid")
    monkeypatch.setattr(config, "WHATSAPP_VERIFY_TOKEN", "configured-for-test")
    monkeypatch.setenv("AUTH_ALLOWED_ORIGINS", "https://crm.example.invalid")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setattr(config, "WHATSAPP_APP_SECRET", "")
    with pytest.raises(RuntimeError, match="WHATSAPP_APP_SECRET"):
        config.validate_security_configuration()

    monkeypatch.setattr(config, "WHATSAPP_APP_SECRET", "test-only-meta-app-secret-32-characters")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    with pytest.raises(RuntimeError, match="AUTH_COOKIE_SECURE"):
        config.validate_security_configuration()

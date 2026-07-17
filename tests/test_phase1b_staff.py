from app.models.user_model import UserRole
from app.repositories.user_repository import insert_staff_user
from app.services.password_service import hash_password

PASSWORD = "Temporary!Pass4827"
NEW_PASSWORD = "Replacement!Pass5938"


def make_user(database, email="admin@example.com", role=UserRole.SUPER_ADMIN.value):
    return insert_staff_user({
        "email": email, "displayName": "Test User", "role": role,
        "passwordHash": hash_password(PASSWORD), "isActive": True,
        "mustChangePassword": False,
    })


def headers(client, email="admin@example.com", password=PASSWORD):
    response = client.post("/auth/login", json={"emailId": email, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['accessToken']}"}


def test_admin_staff_lifecycle_is_audited_and_secrets_are_not_returned(client, database):
    make_user(database)
    admin_headers = headers(client)
    created = client.post("/users", headers=admin_headers, json={
        "displayName": "Asha Counsellor", "email": "ASHA@example.com",
        "role": "COUNSELLOR", "temporaryPassword": NEW_PASSWORD,
        "confirmTemporaryPassword": NEW_PASSWORD,
    })
    assert created.status_code == 201
    user = created.json()["data"]
    assert user["email"] == "asha@example.com"
    assert user["mustChangePassword"] is True
    assert "passwordHash" not in created.json()["data"]
    assert "temporaryPassword" not in created.json()["data"]
    assert client.get("/users", headers=admin_headers).json()["pagination"]["totalRecords"] == 2
    updated = client.patch(f"/users/{user['id']}", headers=admin_headers, json={
        "version": user["version"], "displayName": "Asha Sen",
    })
    assert updated.status_code == 200
    reset = client.post(f"/users/{user['id']}/reset-password", headers=admin_headers, json={
        "temporaryPassword": NEW_PASSWORD, "confirmTemporaryPassword": NEW_PASSWORD,
    })
    assert reset.status_code == 200
    actions = {item["action"] for item in database.audit_logs.find({"entityId": str(database.users.find_one({"emailNormalized": "asha@example.com"})["_id"])})}
    assert {"AUTH_USER_CREATED", "AUTH_USER_UPDATED", "AUTH_USER_PASSWORD_RESET"}.issubset(actions)


def test_staff_management_authorization_and_safety_guards(client, database):
    admin = make_user(database)
    make_user(database, "counsellor@example.com", UserRole.COUNSELLOR.value)
    counsellor_headers = headers(client, "counsellor@example.com")
    assert client.get("/users", headers=counsellor_headers).status_code == 403
    assert client.get("/users/counsellor-options", headers=counsellor_headers).status_code == 200
    admin_headers = headers(client)
    self_deactivate = client.patch(f"/users/{admin['_id']}", headers=admin_headers, json={"version": admin["version"], "isActive": False})
    assert self_deactivate.status_code == 403
    self_reset = client.post(f"/users/{admin['_id']}/reset-password", headers=admin_headers, json={"temporaryPassword": NEW_PASSWORD, "confirmTemporaryPassword": NEW_PASSWORD})
    assert self_reset.status_code == 403


def test_duplicate_staff_email_and_stale_version_are_rejected(client, database):
    make_user(database)
    existing = make_user(database, "counsellor@example.com", UserRole.COUNSELLOR.value)
    admin_headers = headers(client)
    duplicate = client.post("/users", headers=admin_headers, json={"displayName": "Duplicate", "email": "COUNSELLOR@example.com", "role": "COUNSELLOR", "temporaryPassword": NEW_PASSWORD, "confirmTemporaryPassword": NEW_PASSWORD})
    assert duplicate.status_code == 409
    first = client.patch(f"/users/{existing['_id']}", headers=admin_headers, json={"version": existing["version"], "displayName": "First change"})
    assert first.status_code == 200
    stale = client.patch(f"/users/{existing['_id']}", headers=admin_headers, json={"version": existing["version"], "displayName": "Stale change"})
    assert stale.status_code == 409

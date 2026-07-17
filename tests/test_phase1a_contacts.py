from bson import ObjectId
import pytest

from app.models.user_model import UserRole
from app.repositories.user_repository import insert_staff_user
from app.services.password_service import hash_password
from app.services.preference_service import get_contact_communication_eligibility
from app.utils.time_utils import utc_now


PASSWORD = "Temporary!Pass4827"


def make_user(database, email, role=UserRole.SUPER_ADMIN.value, active=True):
    return insert_staff_user(
        {
            "email": email,
            "displayName": email.split("@")[0].replace(".", " ").title(),
            "role": role,
            "passwordHash": hash_password(PASSWORD),
            "isActive": active,
            "mustChangePassword": False,
        }
    )


def login_headers(client, email):
    response = client.post("/auth/login", json={"emailId": email, "password": PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['accessToken']}"}


def contact_payload(phone="98765 43210", **overrides):
    payload = {
        "firstName": "Asha",
        "lastName": "Sen",
        "phone": phone,
        "email": "ASHA@example.com",
        "city": "Kolkata",
        "source": "manual enquiry",
    }
    payload.update(overrides)
    return payload


def test_admin_contact_creation_normalizes_and_creates_foundation_records(client, database):
    admin = make_user(database, "admin@example.com")
    response = client.post(
        "/contacts",
        headers=login_headers(client, "admin@example.com"),
        json=contact_payload(),
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["contact"]["normalizedPhone"] == "919876543210"
    assert data["contact"]["normalizedEmail"] == "asha@example.com"
    assert data["contact"]["normalizedDisplayName"] == "asha sen"
    assert data["contact"]["createdBy"] == str(admin["_id"])
    assert data["preferences"]["marketingAllowed"] is False
    assert data["preferences"]["doNotContact"] is False
    assert data["lead"]["status"] == "NEW"
    assert data["lead"]["assignedCounsellorId"] is None
    assert database.contacts.count_documents({}) == 1
    assert database.contact_preferences.count_documents({}) == 1
    assert database.leads.count_documents({}) == 1
    assert database.lead_activities.count_documents({"type": "CONTACT_CREATED"}) == 1
    assert database.audit_logs.count_documents({"action": "CONTACT_CREATED"}) == 1


def test_counsellor_contact_creation_assigns_the_new_lead_to_self(client, database):
    counsellor = make_user(database, "counsellor@example.com", UserRole.COUNSELLOR.value)
    headers = login_headers(client, "counsellor@example.com")
    response = client.post("/contacts", headers=headers, json=contact_payload())
    assert response.status_code == 201
    lead = response.json()["data"]["lead"]
    assert lead["assignedCounsellorId"] == str(counsellor["_id"])
    assert database.lead_assignments.count_documents(
        {"toCounsellorId": counsellor["_id"]}
    ) == 1
    denied = client.post(
        "/contacts",
        headers=headers,
        json=contact_payload("9876543211", createLead=False),
    )
    assert denied.status_code == 422
    assert denied.json()["error"]["code"] == "COUNSELLOR_LEAD_REQUIRED"


@pytest.mark.parametrize("phone", ["", "NA", "0000000000", "9999999999", "12345", "+1 212 555 0100"])
def test_invalid_or_fake_primary_phone_is_rejected(client, database, phone):
    make_user(database, "admin@example.com")
    response = client.post(
        "/contacts",
        headers=login_headers(client, "admin@example.com"),
        json=contact_payload(phone),
    )
    assert response.status_code == 422
    assert database.contacts.count_documents({}) == 0


def test_duplicate_normalized_phone_is_rejected(client, database):
    make_user(database, "admin@example.com")
    headers = login_headers(client, "admin@example.com")
    assert client.post("/contacts", headers=headers, json=contact_payload("9876543210")).status_code == 201
    duplicate = client.post("/contacts", headers=headers, json=contact_payload("+91-98765-43210"))
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "CONTACT_PHONE_DUPLICATE"
    assert database.contacts.count_documents({}) == 1


def test_name_and_phone_corrections_are_versioned_audited_and_keep_contact_id(client, database):
    make_user(database, "admin@example.com")
    headers = login_headers(client, "admin@example.com")
    created = client.post("/contacts", headers=headers, json=contact_payload()).json()["data"]["contact"]
    corrected = client.patch(
        f"/contacts/{created['id']}",
        headers=headers,
        json={"version": created["version"], "firstName": "Ananya", "lastName": "Roy"},
    )
    assert corrected.status_code == 200
    result = corrected.json()["data"]
    assert result["id"] == created["id"]
    assert result["displayName"] == "Ananya Roy"
    assert result["normalizedDisplayName"] == "ananya roy"
    assert database.audit_logs.count_documents({"action": "CONTACT_NAME_CORRECTED"}) == 1
    name_activity = database.lead_activities.find_one({"type": "CONTACT_NAME_CORRECTED"})
    assert any(item["field"] == "firstName" for item in name_activity["metadata"]["changedFields"])

    phone_result = client.patch(
        f"/contacts/{created['id']}",
        headers=headers,
        json={"version": result["version"], "phone": "91 98765 43211"},
    )
    assert phone_result.status_code == 200
    assert phone_result.json()["data"]["normalizedPhone"] == "919876543211"
    assert database.audit_logs.count_documents({"action": "CONTACT_PHONE_CORRECTED"}) == 1
    stale = client.patch(
        f"/contacts/{created['id']}",
        headers=headers,
        json={"version": created["version"], "city": "Howrah"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CONTACT_VERSION_CONFLICT"


def test_phone_correction_duplicate_conflict_does_not_modify_contact(client, database):
    make_user(database, "admin@example.com")
    headers = login_headers(client, "admin@example.com")
    first = client.post("/contacts", headers=headers, json=contact_payload("9876543210")).json()["data"]["contact"]
    second = client.post("/contacts", headers=headers, json=contact_payload("9876543211")).json()["data"]["contact"]
    response = client.patch(
        f"/contacts/{second['id']}",
        headers=headers,
        json={"version": second["version"], "phone": "+91 98765 43210"},
    )
    assert response.status_code == 409
    stored = database.contacts.find_one({"_id": ObjectId(second["id"])})
    assert stored["normalizedPhone"] == "919876543211"
    assert database.contacts.find_one({"_id": ObjectId(first["id"])})


def test_contact_access_is_limited_to_current_owner(client, database):
    make_user(database, "admin@example.com")
    make_user(database, "owner@example.com", UserRole.COUNSELLOR.value)
    other = make_user(database, "other@example.com", UserRole.COUNSELLOR.value)
    owner_headers = login_headers(client, "owner@example.com")
    contact = client.post("/contacts", headers=owner_headers, json=contact_payload()).json()["data"]["contact"]
    assert client.get(f"/contacts/{contact['id']}", headers=owner_headers).status_code == 200
    owner_correction = client.patch(
        f"/contacts/{contact['id']}",
        headers=owner_headers,
        json={"version": contact["version"], "firstName": "Corrected"},
    )
    assert owner_correction.status_code == 200
    assert owner_correction.json()["data"]["displayName"] == "Corrected Sen"
    other_headers = login_headers(client, "other@example.com")
    assert client.get(f"/contacts/{contact['id']}", headers=other_headers).status_code == 403
    assert client.patch(
        f"/contacts/{contact['id']}",
        headers=other_headers,
        json={"version": contact["version"], "city": "Howrah"},
    ).status_code == 403
    listed = client.get("/contacts", headers=other_headers)
    assert listed.status_code == 200
    assert listed.json()["pagination"]["totalRecords"] == 0
    unresolved_id = database.contacts.insert_one(
        {
            "entityType": "CONTACT",
            "phone": "9876543211",
            "normalizedPhone": "919876543211",
            "isActive": True,
            "version": 1,
            "createdBy": other["_id"],
            "createdAt": utc_now(),
            "updatedBy": other["_id"],
            "updatedAt": utc_now(),
        }
    ).inserted_id
    unresolved_list = client.get("/contacts", headers=other_headers)
    assert unresolved_list.json()["pagination"]["totalRecords"] == 1
    assert client.get(f"/contacts/{unresolved_id}", headers=other_headers).status_code == 200


def test_suppression_overrides_permissions_updates_lead_and_requires_admin_to_reverse(client, database):
    make_user(database, "admin@example.com")
    make_user(database, "counsellor@example.com", UserRole.COUNSELLOR.value)
    admin_headers = login_headers(client, "admin@example.com")
    created = client.post("/contacts", headers=admin_headers, json=contact_payload()).json()["data"]
    contact_id = created["contact"]["id"]
    preference = created["preferences"]
    suppressed = client.patch(
        f"/contacts/{contact_id}/preferences",
        headers=admin_headers,
        json={
            "version": preference["version"],
            "whatsappAllowed": True,
            "marketingAllowed": True,
            "doNotContact": True,
            "optOutSource": "manual request",
            "reason": "Contact explicitly asked to stop",
        },
    )
    assert suppressed.status_code == 200
    updated_preference = suppressed.json()["data"]
    assert updated_preference["doNotContact"] is True
    assert updated_preference["whatsappAllowed"] is False
    assert updated_preference["marketingAllowed"] is False
    lead = database.leads.find_one({"contactId": ObjectId(contact_id)})
    assert lead["status"] == "DO_NOT_CONTACT"
    assert get_contact_communication_eligibility(ObjectId(contact_id))["reasonCode"] == "DO_NOT_CONTACT"
    assert database.audit_logs.count_documents({"action": "CONTACT_DO_NOT_CONTACT_ENABLED"}) == 1

    counsellor_headers = login_headers(client, "counsellor@example.com")
    denied = client.patch(
        f"/contacts/{contact_id}/preferences",
        headers=counsellor_headers,
        json={"version": updated_preference["version"], "doNotContact": False, "reason": "Not allowed"},
    )
    assert denied.status_code == 403
    restored = client.patch(
        f"/contacts/{contact_id}/preferences",
        headers=admin_headers,
        json={
            "version": updated_preference["version"],
            "doNotContact": False,
            "whatsappAllowed": True,
            "marketingAllowed": True,
            "reason": "Super Admin verified renewed consent",
        },
    )
    assert restored.status_code == 200
    assert restored.json()["data"]["doNotContact"] is False
    assert get_contact_communication_eligibility(ObjectId(contact_id))["allowed"] is True


def test_contact_deactivation_moves_active_lead_out_of_communication_queue(client, database):
    make_user(database, "admin@example.com")
    headers = login_headers(client, "admin@example.com")
    created = client.post("/contacts", headers=headers, json=contact_payload()).json()["data"]
    deactivated = client.patch(
        f"/contacts/{created['contact']['id']}",
        headers=headers,
        json={"version": created["contact"]["version"], "isActive": False},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["data"]["isActive"] is False
    lead = database.leads.find_one({"contactId": ObjectId(created["contact"]["id"])})
    assert lead["status"] == "INVALID_CONTACT"
    assert get_contact_communication_eligibility(created["contact"]["id"])["allowed"] is False
    assert database.lead_activities.count_documents({"type": "LEAD_STATUS_CHANGED"}) == 1


def test_preserved_phone_suppression_is_applied_when_contact_is_created(client, database):
    make_user(database, "admin@example.com")
    headers = login_headers(client, "admin@example.com")
    database.suppression_entries.insert_one(
        {
            "normalizedPhone": "919876543210",
            "channel": "WHATSAPP",
            "isActive": True,
            "source": "PRESERVED_LEGACY_DNC",
            "reason": "Existing unsubscribe",
        }
    )
    response = client.post(
        "/contacts",
        headers=headers,
        json=contact_payload(),
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["preferences"]["doNotContact"] is True
    assert data["lead"]["status"] == "DO_NOT_CONTACT"
    restored = client.patch(
        f"/contacts/{data['contact']['id']}/preferences",
        headers=headers,
        json={
            "version": data["preferences"]["version"],
            "doNotContact": False,
            "whatsappAllowed": True,
            "marketingAllowed": True,
            "reason": "Verified renewed consent",
        },
    )
    assert restored.status_code == 200
    suppression = database.suppression_entries.find_one({"normalizedPhone": "919876543210"})
    assert suppression["isActive"] is False
    assert suppression["deactivationReason"] == "Verified renewed consent"
    assert get_contact_communication_eligibility(data["contact"]["id"])["allowed"] is True


def test_contact_lists_are_bounded_filtered_and_stably_paginated(client, database):
    make_user(database, "admin@example.com")
    headers = login_headers(client, "admin@example.com")
    for index in range(3):
        response = client.post(
            "/contacts",
            headers=headers,
            json=contact_payload(f"987654321{index}", city="Kolkata" if index < 2 else "Howrah"),
        )
        assert response.status_code == 201
    page = client.get("/contacts", headers=headers, params={"page": 1, "pageSize": 1, "city": "Kolkata"})
    assert page.status_code == 200
    assert len(page.json()["data"]) == 1
    assert page.json()["pagination"]["totalRecords"] == 2
    assert page.json()["pagination"]["hasNext"] is True
    assert client.get("/contacts", headers=headers, params={"pageSize": 101}).status_code == 422

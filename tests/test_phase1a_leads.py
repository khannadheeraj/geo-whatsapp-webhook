from bson import ObjectId
import pytest
from pymongo.errors import DuplicateKeyError

from app.db.mongodb import ensure_phase1a_indexes
from app.errors import ConflictError
from app.models.user_model import UserRole
from app.repositories.lead_repository import insert_course_interest
from app.repositories.user_repository import insert_staff_user
from app.services.password_service import hash_password
from app.utils.time_utils import utc_now


PASSWORD = "Temporary!Pass4827"


def make_user(database, email, role=UserRole.SUPER_ADMIN.value, active=True):
    return insert_staff_user(
        {
            "email": email,
            "displayName": email.split("@")[0].title(),
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


def create_contact(client, headers, phone, create_lead=False):
    response = client.post(
        "/contacts",
        headers=headers,
        json={
            "firstName": "Test",
            "lastName": phone[-2:],
            "phone": phone,
            "source": "website enquiry",
            "createLead": create_lead,
        },
    )
    assert response.status_code == 201
    return response.json()["data"]


def test_lead_creation_enforces_one_active_lead_and_valid_enums(client, database):
    make_user(database, "admin@example.com")
    headers = login_headers(client, "admin@example.com")
    contact = create_contact(client, headers, "9876543210")["contact"]
    created = client.post(
        "/leads",
        headers=headers,
        json={
            "contactId": contact["id"],
            "status": "INTERESTED",
            "priority": "HIGH",
            "preferredMode": "OFFLINE",
            "targetExamYear": 2027,
        },
    )
    assert created.status_code == 201
    lead = created.json()["data"]
    assert lead["status"] == "INTERESTED"
    assert lead["priority"] == "HIGH"
    assert lead["score"] == 0
    duplicate = client.post("/leads", headers=headers, json={"contactId": contact["id"]})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "ACTIVE_LEAD_DUPLICATE"
    invalid = client.post(
        "/leads",
        headers=headers,
        json={"contactId": contact["id"], "status": "HOT", "priority": "CRITICAL"},
    )
    assert invalid.status_code == 422


def test_suppressed_contact_can_only_create_do_not_contact_lead(client, database):
    make_user(database, "admin@example.com")
    headers = login_headers(client, "admin@example.com")
    contact_data = create_contact(client, headers, "9876543210")
    contact = contact_data["contact"]
    preference = contact_data["preferences"]
    suppress = client.patch(
        f"/contacts/{contact['id']}/preferences",
        headers=headers,
        json={
            "version": preference["version"],
            "doNotContact": True,
            "reason": "Explicit opt out",
        },
    )
    assert suppress.status_code == 200
    lead = client.post(
        "/leads",
        headers=headers,
        json={"contactId": contact["id"], "status": "INTERESTED"},
    )
    assert lead.status_code == 201
    assert lead.json()["data"]["status"] == "DO_NOT_CONTACT"


def test_role_scoped_lead_access_filters_and_pagination(client, database):
    make_user(database, "admin@example.com")
    make_user(database, "owner@example.com", UserRole.COUNSELLOR.value)
    make_user(database, "other@example.com", UserRole.COUNSELLOR.value)
    owner_headers = login_headers(client, "owner@example.com")
    owner_lead = create_contact(client, owner_headers, "9876543210", create_lead=True)["lead"]
    other_headers = login_headers(client, "other@example.com")
    other_lead = create_contact(client, other_headers, "9876543211", create_lead=True)["lead"]

    owner_list = client.get("/leads", headers=owner_headers, params={"pageSize": 1})
    assert owner_list.status_code == 200
    assert owner_list.json()["pagination"]["totalRecords"] == 1
    assert owner_list.json()["data"][0]["id"] == owner_lead["id"]
    assert client.get(f"/leads/{other_lead['id']}", headers=owner_headers).status_code == 403
    assert client.get("/leads", headers=owner_headers, params={"unassigned": True}).status_code == 403
    admin_headers = login_headers(client, "admin@example.com")
    filtered = client.get("/leads", headers=admin_headers, params={"status": "NEW", "priority": "MEDIUM"})
    assert filtered.status_code == 200
    assert filtered.json()["pagination"]["totalRecords"] == 2
    assert client.get("/leads", headers=admin_headers, params={"pageSize": 101}).status_code == 422


def test_assigned_counsellor_can_patch_permitted_fields_but_not_attribution(client, database):
    make_user(database, "owner@example.com", UserRole.COUNSELLOR.value)
    make_user(database, "other@example.com", UserRole.COUNSELLOR.value)
    headers = login_headers(client, "owner@example.com")
    lead = create_contact(client, headers, "9876543210", create_lead=True)["lead"]
    updated = client.patch(
        f"/leads/{lead['id']}",
        headers=headers,
        json={"version": lead["version"], "status": "INTERESTED", "priority": "HIGH"},
    )
    assert updated.status_code == 200
    result = updated.json()["data"]
    assert result["status"] == "INTERESTED"
    assert result["priority"] == "HIGH"
    assert database.lead_activities.count_documents({"type": "LEAD_STATUS_CHANGED"}) == 1
    assert database.lead_activities.count_documents({"type": "LEAD_PRIORITY_CHANGED"}) == 1
    assert database.audit_logs.count_documents({"action": "LEAD_UPDATED"}) == 1

    forbidden = client.patch(
        f"/leads/{lead['id']}",
        headers=headers,
        json={"version": result["version"], "source": "referral"},
    )
    assert forbidden.status_code == 403
    stale = client.patch(
        f"/leads/{lead['id']}",
        headers=headers,
        json={"version": lead["version"], "priority": "URGENT"},
    )
    assert stale.status_code == 409
    other_headers = login_headers(client, "other@example.com")
    assert client.patch(
        f"/leads/{lead['id']}",
        headers=other_headers,
        json={"version": result["version"], "priority": "URGENT"},
    ).status_code == 403


def test_admitted_and_direct_do_not_contact_transitions_are_deferred_to_owning_workflows(client, database):
    make_user(database, "admin@example.com")
    headers = login_headers(client, "admin@example.com")
    lead = create_contact(client, headers, "9876543210", create_lead=True)["lead"]
    admitted = client.patch(
        f"/leads/{lead['id']}",
        headers=headers,
        json={"version": lead["version"], "status": "ADMITTED"},
    )
    assert admitted.status_code == 422
    assert admitted.json()["error"]["code"] == "ADMISSION_WORKFLOW_REQUIRED"
    dnc = client.patch(
        f"/leads/{lead['id']}",
        headers=headers,
        json={"version": lead["version"], "status": "DO_NOT_CONTACT"},
    )
    assert dnc.status_code == 422
    assert dnc.json()["error"]["code"] == "LEAD_STATUS_REQUIRES_SUPPRESSION"


def test_course_interest_repository_supports_one_primary_without_placeholder_ids(client, database):
    make_user(database, "admin@example.com")
    headers = login_headers(client, "admin@example.com")
    lead = create_contact(client, headers, "9876543210", create_lead=True)["lead"]
    lead_id = ObjectId(lead["id"])
    first = insert_course_interest(
        {
            "leadId": lead_id,
            "temporaryCourseLabel": "UPSC FOUNDATION",
            "isPrimary": True,
            "interestLevel": "INTERESTED",
            "createdAt": utc_now(),
            "updatedAt": utc_now(),
        }
    )
    assert "courseId" not in first
    with pytest.raises(ConflictError):
        insert_course_interest(
            {
                "leadId": lead_id,
                "temporaryCourseLabel": "PRELIMS TEST SERIES",
                "isPrimary": True,
                "interestLevel": "EXPLORING",
                "createdAt": utc_now(),
                "updatedAt": utc_now(),
            }
        )


def test_phase1a_indexes_are_idempotent_and_enforce_core_uniqueness(database):
    ensure_phase1a_indexes()
    ensure_phase1a_indexes()
    contact_indexes = database.contacts.index_information()
    assert "uq_contact_normalized_phone" in contact_indexes
    assert "ix_contact_source_created" in contact_indexes
    lead_indexes = database.leads.index_information()
    assert "uq_active_admission_lead_per_contact" in lead_indexes
    assert "ix_lead_owner_status_updated" in lead_indexes
    assert "uq_pending_reassignment_per_lead" in database.reassignment_requests.index_information()
    assert "uq_primary_course_interest_per_lead" in database.lead_course_interests.index_information()
    assert "ix_activity_lead_created" in database.lead_activities.index_information()
    database.contacts.insert_one(
        {"entityType": "CONTACT", "normalizedPhone": "919876543210"}
    )
    with pytest.raises(DuplicateKeyError):
        database.contacts.insert_one(
            {"entityType": "CONTACT", "normalizedPhone": "919876543210"}
        )


def test_all_phase1a_data_routes_reject_anonymous_requests(client, database):
    lead_id = str(ObjectId())
    contact_id = str(ObjectId())
    request_id = str(ObjectId())
    routes = [
        ("post", "/contacts", {"phone": "9876543210"}),
        ("get", "/contacts", None),
        ("get", f"/contacts/{contact_id}", None),
        ("patch", f"/contacts/{contact_id}", {"version": 1, "city": "Kolkata"}),
        (
            "patch",
            f"/contacts/{contact_id}/preferences",
            {"version": 1, "doNotContact": True, "reason": "Anonymous request"},
        ),
        ("post", "/leads", {"contactId": contact_id}),
        ("get", "/leads", None),
        ("get", f"/leads/{lead_id}", None),
        ("patch", f"/leads/{lead_id}", {"version": 1, "priority": "HIGH"}),
        (
            "post",
            f"/leads/{lead_id}/assignments",
            {
                "counsellorId": str(ObjectId()),
                "reasonCode": "WORKLOAD",
                "reason": "Anonymous request",
                "version": 1,
            },
        ),
        ("get", f"/leads/{lead_id}/assignments", None),
        ("get", f"/leads/{lead_id}/activities", None),
        (
            "post",
            f"/leads/{lead_id}/reassignment-requests",
            {"reasonCode": "WORKLOAD"},
        ),
        ("get", "/reassignment-requests", None),
        (
            "post",
            f"/reassignment-requests/{request_id}/approve",
            {"targetCounsellorId": str(ObjectId()), "version": 1},
        ),
        (
            "post",
            f"/reassignment-requests/{request_id}/reject",
            {"decisionNote": "Anonymous request"},
        ),
        ("post", f"/reassignment-requests/{request_id}/cancel", None),
    ]
    for method, path, payload in routes:
        kwargs = {"json": payload} if payload is not None else {}
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 401, path

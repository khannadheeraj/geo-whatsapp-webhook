from bson import ObjectId
import pytest

from app.models.user_model import UserRole
from app.repositories.user_repository import insert_staff_user
from app.services.assignment_service import assign_lead
from app.services.password_service import hash_password


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


def create_contact(client, headers, phone="9876543210", create_lead=True):
    response = client.post(
        "/contacts",
        headers=headers,
        json={"firstName": "Lead", "phone": phone, "createLead": create_lead},
    )
    assert response.status_code == 201
    return response.json()["data"]


def test_admin_assignment_validates_target_and_uses_version_guard(client, database):
    admin = make_user(database, "admin@example.com")
    counsellor = make_user(database, "c1@example.com", UserRole.COUNSELLOR.value)
    other = make_user(database, "c2@example.com", UserRole.COUNSELLOR.value)
    inactive = make_user(database, "inactive@example.com", UserRole.COUNSELLOR.value, active=False)
    headers = login_headers(client, "admin@example.com")
    lead = create_contact(client, headers)["lead"]

    assigned = client.post(
        f"/leads/{lead['id']}/assignments",
        headers=headers,
        json={
            "counsellorId": str(counsellor["_id"]),
            "reasonCode": "ADMIN_ASSIGNMENT",
            "reason": "Initial workload assignment",
            "version": lead["version"],
        },
    )
    assert assigned.status_code == 200
    result = assigned.json()["data"]
    assert result["lead"]["assignedCounsellorId"] == str(counsellor["_id"])
    assert result["assignment"]["fromCounsellorId"] is None
    assert result["assignment"]["toCounsellorId"] == str(counsellor["_id"])
    assert database.lead_assignments.count_documents({}) == 1
    assert database.lead_activities.count_documents({"type": "LEAD_ASSIGNED"}) == 1
    assert database.audit_logs.count_documents({"action": "LEAD_ASSIGNED"}) == 1

    stale = client.post(
        f"/leads/{lead['id']}/assignments",
        headers=headers,
        json={
            "counsellorId": str(other["_id"]),
            "reasonCode": "WORKLOAD",
            "reason": "Stale administrator view",
            "version": lead["version"],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "LEAD_VERSION_CONFLICT"
    current_version = result["lead"]["version"]
    inactive_response = client.post(
        f"/leads/{lead['id']}/assignments",
        headers=headers,
        json={
            "counsellorId": str(inactive["_id"]),
            "reasonCode": "WORKLOAD",
            "reason": "Invalid inactive target",
            "version": current_version,
        },
    )
    assert inactive_response.status_code == 422
    assert inactive_response.json()["error"]["code"] == "ASSIGNMENT_TARGET_INACTIVE"
    wrong_role = client.post(
        f"/leads/{lead['id']}/assignments",
        headers=headers,
        json={
            "counsellorId": str(admin["_id"]),
            "reasonCode": "WORKLOAD",
            "reason": "Invalid role target",
            "version": current_version,
        },
    )
    assert wrong_role.status_code == 422
    assert wrong_role.json()["error"]["code"] == "ASSIGNMENT_TARGET_ROLE_INVALID"
    missing_target = client.post(
        f"/leads/{lead['id']}/assignments",
        headers=headers,
        json={
            "counsellorId": str(ObjectId()),
            "reasonCode": "WORKLOAD",
            "reason": "Missing user target",
            "version": current_version,
        },
    )
    assert missing_target.status_code == 404
    assert missing_target.json()["error"]["code"] == "COUNSELLOR_NOT_FOUND"


def test_counsellor_cannot_directly_assign_or_reassign(client, database):
    make_user(database, "owner@example.com", UserRole.COUNSELLOR.value)
    target = make_user(database, "target@example.com", UserRole.COUNSELLOR.value)
    headers = login_headers(client, "owner@example.com")
    lead = create_contact(client, headers)["lead"]
    response = client.post(
        f"/leads/{lead['id']}/assignments",
        headers=headers,
        json={
            "counsellorId": str(target["_id"]),
            "reasonCode": "WORKLOAD",
            "reason": "Attempted direct reassignment",
            "version": lead["version"],
        },
    )
    assert response.status_code == 403


def test_assignment_retry_repairs_history_without_transactions(client, database, monkeypatch):
    admin = make_user(database, "admin@example.com")
    target = make_user(database, "target@example.com", UserRole.COUNSELLOR.value)
    lead = create_contact(client, login_headers(client, "admin@example.com"))["lead"]
    from app.services import assignment_service

    real_upsert = assignment_service.upsert_assignment_history
    attempts = {"count": 0}

    def fail_once(document):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("simulated history write interruption")
        return real_upsert(document)

    monkeypatch.setattr(assignment_service, "upsert_assignment_history", fail_once)
    operation_id = "assignment:test-repair"
    with pytest.raises(RuntimeError, match="simulated history"):
        assign_lead(
            ObjectId(lead["id"]),
            target["_id"],
            reason_code="WORKLOAD",
            reason="Repair test",
            expected_version=lead["version"],
            actor=admin,
            request_id="repair-test",
            operation_id=operation_id,
        )
    stored = database.leads.find_one({"_id": ObjectId(lead["id"])})
    assert stored["assignedCounsellorId"] == target["_id"]
    assert database.lead_assignments.count_documents({}) == 0
    repaired_lead, history = assign_lead(
        ObjectId(lead["id"]),
        target["_id"],
        reason_code="WORKLOAD",
        reason="Repair test",
        expected_version=lead["version"],
        actor=admin,
        request_id="repair-test",
        operation_id=operation_id,
    )
    assert repaired_lead["assignedCounsellorId"] == target["_id"]
    assert history["operationId"] == operation_id
    assert database.lead_assignments.count_documents({"operationId": operation_id}) == 1


def test_assignment_history_is_visible_only_in_authorized_scope(client, database):
    make_user(database, "owner@example.com", UserRole.COUNSELLOR.value)
    make_user(database, "other@example.com", UserRole.COUNSELLOR.value)
    owner_headers = login_headers(client, "owner@example.com")
    lead = create_contact(client, owner_headers)["lead"]
    history = client.get(f"/leads/{lead['id']}/assignments", headers=owner_headers)
    assert history.status_code == 200
    assert history.json()["pagination"]["totalRecords"] == 1
    assert client.get(
        f"/leads/{lead['id']}/assignments",
        headers=login_headers(client, "other@example.com"),
    ).status_code == 403


def test_owner_can_request_and_cancel_but_non_owner_and_duplicates_are_rejected(client, database):
    make_user(database, "owner@example.com", UserRole.COUNSELLOR.value)
    make_user(database, "other@example.com", UserRole.COUNSELLOR.value)
    owner_headers = login_headers(client, "owner@example.com")
    lead = create_contact(client, owner_headers)["lead"]
    request = client.post(
        f"/leads/{lead['id']}/reassignment-requests",
        headers=owner_headers,
        json={"reasonCode": "WORKLOAD", "note": "Current workload is temporarily high"},
    )
    assert request.status_code == 201
    request_data = request.json()["data"]
    assert request_data["status"] == "PENDING"
    duplicate = client.post(
        f"/leads/{lead['id']}/reassignment-requests",
        headers=owner_headers,
        json={"reasonCode": "COUNSELLOR_UNAVAILABLE"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "REASSIGNMENT_PENDING_DUPLICATE"
    other_headers = login_headers(client, "other@example.com")
    assert client.post(
        f"/leads/{lead['id']}/reassignment-requests",
        headers=other_headers,
        json={"reasonCode": "WORKLOAD"},
    ).status_code == 403
    assert client.post(
        f"/reassignment-requests/{request_data['id']}/cancel",
        headers=other_headers,
    ).status_code == 403
    cancelled = client.post(
        f"/reassignment-requests/{request_data['id']}/cancel",
        headers=owner_headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "CANCELLED"
    assert database.lead_activities.count_documents({"type": "REASSIGNMENT_CANCELLED"}) == 1
    assert database.audit_logs.count_documents({"action": "REASSIGNMENT_CANCELLED"}) == 1


def test_super_admin_approval_runs_central_assignment_and_changes_owner(client, database):
    make_user(database, "admin@example.com")
    make_user(database, "owner@example.com", UserRole.COUNSELLOR.value)
    target = make_user(database, "target@example.com", UserRole.COUNSELLOR.value)
    owner_headers = login_headers(client, "owner@example.com")
    lead = create_contact(client, owner_headers)["lead"]
    request = client.post(
        f"/leads/{lead['id']}/reassignment-requests",
        headers=owner_headers,
        json={
            "requestedTargetCounsellorId": str(target["_id"]),
            "reasonCode": "LANGUAGE_REQUIREMENT",
            "note": "Lead requested a different language",
        },
    ).json()["data"]
    approved = client.post(
        f"/reassignment-requests/{request['id']}/approve",
        headers=login_headers(client, "admin@example.com"),
        json={"version": lead["version"], "decisionNote": "Target confirmed availability"},
    )
    assert approved.status_code == 200
    assert approved.json()["data"]["status"] == "APPROVED"
    current_lead = database.leads.find_one({"_id": ObjectId(lead["id"])})
    assert current_lead["assignedCounsellorId"] == target["_id"]
    assert database.lead_assignments.count_documents({}) == 2
    assert database.lead_assignments.count_documents({"reassignmentRequestId": ObjectId(request["id"])}) == 1
    assert database.lead_activities.count_documents({"type": "REASSIGNMENT_APPROVED"}) == 1
    assert database.audit_logs.count_documents({"action": "REASSIGNMENT_APPROVED"}) == 1
    assert client.get(f"/leads/{lead['id']}", headers=owner_headers).status_code == 403
    assert client.get(
        f"/leads/{lead['id']}", headers=login_headers(client, "target@example.com")
    ).status_code == 200


def test_super_admin_rejection_does_not_change_ownership(client, database):
    make_user(database, "admin@example.com")
    owner = make_user(database, "owner@example.com", UserRole.COUNSELLOR.value)
    owner_headers = login_headers(client, "owner@example.com")
    lead = create_contact(client, owner_headers)["lead"]
    request = client.post(
        f"/leads/{lead['id']}/reassignment-requests",
        headers=owner_headers,
        json={"reasonCode": "OTHER", "note": "Requested review"},
    ).json()["data"]
    rejected = client.post(
        f"/reassignment-requests/{request['id']}/reject",
        headers=login_headers(client, "admin@example.com"),
        json={"decisionNote": "No transfer is required"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "REJECTED"
    stored_lead = database.leads.find_one({"_id": ObjectId(lead["id"])})
    assert stored_lead["assignedCounsellorId"] == owner["_id"]
    assert database.lead_assignments.count_documents({}) == 1
    assert database.lead_activities.count_documents({"type": "REASSIGNMENT_REJECTED"}) == 1
    assert database.audit_logs.count_documents({"action": "REASSIGNMENT_REJECTED"}) == 1


def test_reassignment_lists_are_admin_global_and_counsellor_requester_scoped(client, database):
    make_user(database, "admin@example.com")
    make_user(database, "owner1@example.com", UserRole.COUNSELLOR.value)
    make_user(database, "owner2@example.com", UserRole.COUNSELLOR.value)
    first_headers = login_headers(client, "owner1@example.com")
    second_headers = login_headers(client, "owner2@example.com")
    first_lead = create_contact(client, first_headers, "9876543210")["lead"]
    second_lead = create_contact(client, second_headers, "9876543211")["lead"]
    for lead, headers in ((first_lead, first_headers), (second_lead, second_headers)):
        assert client.post(
            f"/leads/{lead['id']}/reassignment-requests",
            headers=headers,
            json={"reasonCode": "WORKLOAD"},
        ).status_code == 201
    first_list = client.get("/reassignment-requests", headers=first_headers)
    assert first_list.status_code == 200
    assert first_list.json()["pagination"]["totalRecords"] == 1
    admin_list = client.get(
        "/reassignment-requests",
        headers=login_headers(client, "admin@example.com"),
        params={"status": "PENDING"},
    )
    assert admin_list.status_code == 200
    assert admin_list.json()["pagination"]["totalRecords"] == 2
    assert client.get(
        "/reassignment-requests",
        headers=login_headers(client, "admin@example.com"),
        params={"pageSize": 101},
    ).status_code == 422

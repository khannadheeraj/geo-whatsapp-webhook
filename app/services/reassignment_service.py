from typing import Any, Dict, List, Optional, Tuple

from app.errors import AuthorizationError, ConflictError, NotFoundError, ValidationApiError
from app.models.crm_model import ActivityType, ReassignmentStatus
from app.models.user_model import UserRole
from app.repositories.lead_repository import find_lead_by_id, find_leads_by_ids
from app.repositories.contact_repository import find_contacts_by_ids
from app.repositories.user_repository import find_staff_users_by_ids
from app.repositories.reassignment_repository import (
    claim_reassignment_approval,
    decide_reassignment_request,
    finalize_reassignment_approval,
    find_reassignment_request,
    insert_reassignment_request,
    list_reassignment_requests as repository_list_requests,
    release_reassignment_approval_claim,
)
from app.schemas.reassignment_schema import (
    ReassignmentApproveModel,
    ReassignmentCreateModel,
    ReassignmentRejectModel,
)
from app.services.activity_service import record_activity
from app.services.assignment_service import assign_lead, validate_counsellor
from app.services.audit_service import write_audit_event
from app.utils.mongo_utils import object_id_or_not_found
from app.utils.time_utils import utc_now


def create_reassignment_request(
    lead_id_value: Any,
    payload: ReassignmentCreateModel,
    actor: Dict[str, Any],
    request_id: Optional[str],
) -> Dict[str, Any]:
    if actor.get("role") != UserRole.COUNSELLOR.value:
        raise AuthorizationError(
            "REASSIGNMENT_REQUEST_ROLE_INVALID",
            "Only the assigned Counsellor may request reassignment.",
        )
    lead_id = object_id_or_not_found(lead_id_value, "lead")
    lead = find_lead_by_id(lead_id)
    if not lead:
        raise NotFoundError("LEAD_NOT_FOUND", "The requested lead was not found.")
    if str(lead.get("assignedCounsellorId")) != str(actor["_id"]):
        raise AuthorizationError(
            "REASSIGNMENT_OWNER_REQUIRED",
            "Only the currently assigned Counsellor may request reassignment.",
        )
    target = None
    if payload.requestedTargetCounsellorId:
        target = validate_counsellor(payload.requestedTargetCounsellorId)
        if str(target["_id"]) == str(actor["_id"]):
            raise ValidationApiError(
                "REASSIGNMENT_TARGET_UNCHANGED",
                "The requested target must be a different Counsellor.",
            )
    now = utc_now()
    document: Dict[str, Any] = {
        "leadId": lead_id,
        "contactId": lead["contactId"],
        "requestedBy": actor["_id"],
        "reasonCode": payload.reasonCode.value,
        "status": ReassignmentStatus.PENDING.value,
        "leadVersionAtRequest": lead["version"],
        "createdAt": now,
        "updatedAt": now,
    }
    if target:
        document["requestedTargetCounsellorId"] = target["_id"]
    if payload.note and payload.note.strip():
        document["note"] = payload.note.strip()
    request_document = insert_reassignment_request(document)
    operation_id = f"reassignment-request:{request_document['_id']}"
    record_activity(
        ActivityType.REASSIGNMENT_REQUESTED.value,
        "Lead reassignment requested.",
        contact_id=lead["contactId"],
        lead_id=lead_id,
        actor_user_id=actor["_id"],
        metadata={"reasonCode": payload.reasonCode.value},
        related_entity_type="REASSIGNMENT_REQUEST",
        related_entity_id=request_document["_id"],
        operation_id=operation_id,
    )
    write_audit_event(
        "REASSIGNMENT_REQUESTED",
        "SUCCEEDED",
        actor_user_id=actor["_id"],
        entity_type="REASSIGNMENT_REQUEST",
        entity_id=request_document["_id"],
        request_id=request_id,
        compact_metadata={"leadId": lead_id, "reasonCode": payload.reasonCode.value},
        operation_id=operation_id,
    )
    return request_document


def list_reassignment_requests(
    actor: Dict[str, Any],
    *,
    page: int,
    page_size: int,
    status: Optional[str] = None,
    lead_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    query: Dict[str, Any] = {}
    if actor.get("role") != UserRole.SUPER_ADMIN.value:
        query["requestedBy"] = actor["_id"]
    if status:
        query["status"] = status
    if lead_id:
        query["leadId"] = object_id_or_not_found(lead_id, "lead")
    return repository_list_requests(query, page=page, page_size=page_size)


def reassignment_list_context(
    requests: List[Dict[str, Any]],
) -> Dict[str, Dict[Any, Dict[str, Any]]]:
    leads = find_leads_by_ids([item["leadId"] for item in requests])
    contacts = find_contacts_by_ids([lead["contactId"] for lead in leads])
    user_ids = set()
    for item in requests:
        user_ids.add(item.get("requestedBy"))
        user_ids.add(item.get("requestedTargetCounsellorId"))
        user_ids.add(item.get("decidedBy"))
        user_ids.add(item.get("approvedCounsellorId"))
    for lead in leads:
        user_ids.add(lead.get("assignedCounsellorId"))
    users = find_staff_users_by_ids([item for item in user_ids if item])
    return {
        "leads": {item["_id"]: item for item in leads},
        "contacts": {item["_id"]: item for item in contacts},
        "users": {item["_id"]: item for item in users},
    }


def cancel_reassignment_request(
    request_id_value: Any,
    actor: Dict[str, Any],
    request_id: Optional[str],
) -> Dict[str, Any]:
    request_object_id = object_id_or_not_found(request_id_value, "reassignment_request")
    current = find_reassignment_request(request_object_id)
    if not current:
        raise NotFoundError(
            "REASSIGNMENT_REQUEST_NOT_FOUND",
            "The requested reassignment request was not found.",
        )
    if actor.get("role") != UserRole.COUNSELLOR.value or str(current.get("requestedBy")) != str(actor["_id"]):
        raise AuthorizationError(
            "REASSIGNMENT_CANCEL_FORBIDDEN",
            "Only the requesting Counsellor may cancel this request.",
        )
    now = utc_now()
    updated = decide_reassignment_request(
        request_object_id,
        {"status": ReassignmentStatus.CANCELLED.value, "updatedAt": now},
    )
    if not updated:
        raise ConflictError(
            "REASSIGNMENT_REQUEST_NOT_PENDING",
            "Only a pending reassignment request can be cancelled.",
        )
    operation_id = f"reassignment-cancel:{request_object_id}"
    record_activity(
        ActivityType.REASSIGNMENT_CANCELLED.value,
        "Lead reassignment request cancelled.",
        contact_id=current["contactId"],
        lead_id=current["leadId"],
        actor_user_id=actor["_id"],
        related_entity_type="REASSIGNMENT_REQUEST",
        related_entity_id=request_object_id,
        operation_id=operation_id,
    )
    write_audit_event(
        "REASSIGNMENT_CANCELLED",
        "SUCCEEDED",
        actor_user_id=actor["_id"],
        entity_type="REASSIGNMENT_REQUEST",
        entity_id=request_object_id,
        request_id=request_id,
        changed_fields=[
            {"field": "status", "previousValue": "PENDING", "newValue": "CANCELLED"}
        ],
        operation_id=operation_id,
    )
    return updated


def approve_reassignment_request(
    request_id_value: Any,
    payload: ReassignmentApproveModel,
    actor: Dict[str, Any],
    request_id: Optional[str],
) -> Dict[str, Any]:
    if actor.get("role") != UserRole.SUPER_ADMIN.value:
        raise AuthorizationError()
    request_object_id = object_id_or_not_found(request_id_value, "reassignment_request")
    current = find_reassignment_request(request_object_id)
    if not current:
        raise NotFoundError(
            "REASSIGNMENT_REQUEST_NOT_FOUND",
            "The requested reassignment request was not found.",
        )
    if current.get("status") != ReassignmentStatus.PENDING.value:
        raise ConflictError(
            "REASSIGNMENT_REQUEST_NOT_PENDING",
            "Only a pending reassignment request can be approved.",
        )
    target_id = payload.targetCounsellorId or current.get("requestedTargetCounsellorId")
    if not target_id:
        raise ValidationApiError(
            "REASSIGNMENT_TARGET_REQUIRED",
            "Select a Counsellor before approving the request.",
            {"targetCounsellorId": "Select a Counsellor."},
        )
    now = utc_now()
    approval_operation_id = f"reassignment:{request_object_id}:approval"
    claimed = claim_reassignment_approval(request_object_id, approval_operation_id, now)
    if not claimed:
        raise ConflictError(
            "REASSIGNMENT_DECISION_CONFLICT",
            "Another reassignment decision is already in progress or complete.",
        )
    try:
        lead, assignment = assign_lead(
            current["leadId"],
            target_id,
            reason_code="REASSIGNMENT_APPROVED",
            reason=payload.decisionNote or current.get("note") or current.get("reasonCode", "Reassignment approved"),
            expected_version=payload.version,
            actor=actor,
            request_id=request_id,
            operation_id=f"reassignment:{request_object_id}:assignment",
            reassignment_request_id=request_object_id,
        )
    except Exception:
        release_reassignment_approval_claim(request_object_id, approval_operation_id)
        raise
    updated = finalize_reassignment_approval(
        request_object_id,
        approval_operation_id,
        {
            "status": ReassignmentStatus.APPROVED.value,
            "reviewedBy": actor["_id"],
            "reviewedAt": now,
            "decisionNote": payload.decisionNote,
            "approvedCounsellorId": lead["assignedCounsellorId"],
            "assignmentId": assignment["_id"],
            "updatedAt": now,
        },
    )
    if not updated:
        raise ConflictError(
            "REASSIGNMENT_DECISION_CONFLICT",
            "The reassignment request changed during approval. Refresh and verify ownership.",
        )
    operation_id = f"reassignment:{request_object_id}:approved"
    record_activity(
        ActivityType.REASSIGNMENT_APPROVED.value,
        "Lead reassignment request approved.",
        contact_id=current["contactId"],
        lead_id=current["leadId"],
        actor_user_id=actor["_id"],
        metadata={"newCounsellorId": lead["assignedCounsellorId"]},
        related_entity_type="REASSIGNMENT_REQUEST",
        related_entity_id=request_object_id,
        operation_id=operation_id,
    )
    write_audit_event(
        "REASSIGNMENT_APPROVED",
        "SUCCEEDED",
        actor_user_id=actor["_id"],
        entity_type="REASSIGNMENT_REQUEST",
        entity_id=request_object_id,
        request_id=request_id,
        changed_fields=[
            {"field": "status", "previousValue": "PENDING", "newValue": "APPROVED"}
        ],
        compact_metadata={"leadId": current["leadId"]},
        operation_id=operation_id,
    )
    return updated


def reject_reassignment_request(
    request_id_value: Any,
    payload: ReassignmentRejectModel,
    actor: Dict[str, Any],
    request_id: Optional[str],
) -> Dict[str, Any]:
    if actor.get("role") != UserRole.SUPER_ADMIN.value:
        raise AuthorizationError()
    request_object_id = object_id_or_not_found(request_id_value, "reassignment_request")
    current = find_reassignment_request(request_object_id)
    if not current:
        raise NotFoundError(
            "REASSIGNMENT_REQUEST_NOT_FOUND",
            "The requested reassignment request was not found.",
        )
    now = utc_now()
    updated = decide_reassignment_request(
        request_object_id,
        {
            "status": ReassignmentStatus.REJECTED.value,
            "reviewedBy": actor["_id"],
            "reviewedAt": now,
            "decisionNote": payload.decisionNote.strip(),
            "updatedAt": now,
        },
    )
    if not updated:
        raise ConflictError(
            "REASSIGNMENT_REQUEST_NOT_PENDING",
            "Only a pending reassignment request can be rejected.",
        )
    operation_id = f"reassignment:{request_object_id}:rejected"
    record_activity(
        ActivityType.REASSIGNMENT_REJECTED.value,
        "Lead reassignment request rejected.",
        contact_id=current["contactId"],
        lead_id=current["leadId"],
        actor_user_id=actor["_id"],
        metadata={"decisionNote": payload.decisionNote.strip()},
        related_entity_type="REASSIGNMENT_REQUEST",
        related_entity_id=request_object_id,
        operation_id=operation_id,
    )
    write_audit_event(
        "REASSIGNMENT_REJECTED",
        "SUCCEEDED",
        actor_user_id=actor["_id"],
        entity_type="REASSIGNMENT_REQUEST",
        entity_id=request_object_id,
        request_id=request_id,
        changed_fields=[
            {"field": "status", "previousValue": "PENDING", "newValue": "REJECTED"}
        ],
        operation_id=operation_id,
    )
    return updated

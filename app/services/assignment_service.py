import uuid
from typing import Any, Dict, Optional, Tuple

from bson import ObjectId

from app.errors import AuthorizationError, ConflictError, NotFoundError, ValidationApiError
from app.models.crm_model import ActivityType
from app.models.user_model import UserRole
from app.repositories.lead_repository import (
    find_assignment_by_operation,
    find_lead_by_id,
    update_assignment,
    upsert_assignment_history,
)
from app.repositories.user_repository import find_staff_user_by_id
from app.services.activity_service import record_activity
from app.services.audit_service import write_audit_event
from app.utils.crm_validation import normalize_code
from app.utils.mongo_utils import object_id_or_not_found
from app.utils.time_utils import utc_now


def validate_counsellor(user_id: Any) -> Dict[str, Any]:
    counsellor_id = object_id_or_not_found(user_id, "counsellor")
    user = find_staff_user_by_id(counsellor_id)
    if not user:
        raise NotFoundError("COUNSELLOR_NOT_FOUND", "The requested counsellor was not found.")
    if user.get("role") != UserRole.COUNSELLOR.value:
        raise ValidationApiError(
            "ASSIGNMENT_TARGET_ROLE_INVALID",
            "The assignment target must be a Counsellor.",
            {"counsellorId": "Select a Counsellor."},
        )
    if not user.get("isActive"):
        raise ValidationApiError(
            "ASSIGNMENT_TARGET_INACTIVE",
            "The selected Counsellor is inactive.",
            {"counsellorId": "Select an active Counsellor."},
        )
    return user


def record_initial_assignment(
    lead: Dict[str, Any],
    counsellor: Dict[str, Any],
    actor: Dict[str, Any],
    *,
    reason_code: str,
    reason: str,
    request_id: Optional[str],
    operation_id: str,
) -> Dict[str, Any]:
    assigned_at = lead.get("assignedAt") or utc_now()
    history = upsert_assignment_history(
        {
            "operationId": operation_id,
            "leadId": lead["_id"],
            "contactId": lead["contactId"],
            "fromCounsellorId": None,
            "toCounsellorId": counsellor["_id"],
            "reasonCode": normalize_code(reason_code),
            "reason": reason[:500],
            "assignedBy": actor["_id"],
            "assignedAt": assigned_at,
        }
    )
    record_activity(
        ActivityType.LEAD_ASSIGNED.value,
        "Lead assigned to a Counsellor.",
        contact_id=lead["contactId"],
        lead_id=lead["_id"],
        actor_user_id=actor["_id"],
        metadata={
            "previousCounsellorId": None,
            "newCounsellorId": counsellor["_id"],
            "reasonCode": normalize_code(reason_code),
        },
        related_entity_type="LEAD_ASSIGNMENT",
        related_entity_id=history["_id"],
        operation_id=operation_id,
    )
    write_audit_event(
        "LEAD_ASSIGNED",
        "SUCCEEDED",
        actor_user_id=actor["_id"],
        entity_type="ADMISSION_LEAD",
        entity_id=lead["_id"],
        request_id=request_id,
        changed_fields=[
            {
                "field": "assignedCounsellorId",
                "previousValue": None,
                "newValue": counsellor["_id"],
            }
        ],
        compact_metadata={"reasonCode": normalize_code(reason_code)},
        operation_id=operation_id,
    )
    return history


def assign_lead(
    lead_id: ObjectId,
    target_counsellor_id: Any,
    *,
    reason_code: str,
    reason: str,
    expected_version: int,
    actor: Dict[str, Any],
    request_id: Optional[str],
    operation_id: Optional[str] = None,
    reassignment_request_id: Optional[ObjectId] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if actor.get("role") != UserRole.SUPER_ADMIN.value:
        raise AuthorizationError()
    operation_id = operation_id or f"assignment:{uuid.uuid4()}"
    target = validate_counsellor(target_counsellor_id)
    existing_history = find_assignment_by_operation(operation_id)
    if existing_history:
        current = find_lead_by_id(lead_id)
        if current and str(current.get("assignedCounsellorId")) == str(target["_id"]):
            return current, existing_history
        raise ConflictError(
            "ASSIGNMENT_OPERATION_CONFLICT",
            "The assignment operation conflicts with the current ownership state.",
        )

    lead = find_lead_by_id(lead_id)
    if not lead:
        raise NotFoundError("LEAD_NOT_FOUND", "The requested lead was not found.")
    previous_counsellor_id = lead.get("assignedCounsellorId")
    if (
        lead.get("lastAssignmentOperationId") == operation_id
        and str(previous_counsellor_id) == str(target["_id"])
    ):
        recovered_document: Dict[str, Any] = {
            "operationId": operation_id,
            "leadId": lead_id,
            "contactId": lead["contactId"],
            "fromCounsellorId": lead.get("lastAssignmentPreviousCounsellorId"),
            "toCounsellorId": target["_id"],
            "reasonCode": lead.get("lastAssignmentReasonCode") or normalize_code(reason_code),
            "reason": lead.get("lastAssignmentReason") or reason[:500],
            "assignedBy": lead.get("assignedBy") or actor["_id"],
            "assignedAt": lead.get("lastAssignmentAt") or lead.get("assignedAt") or utc_now(),
        }
        recovered_request_id = lead.get("lastAssignmentRequestId")
        if recovered_request_id is not None:
            recovered_document["reassignmentRequestId"] = recovered_request_id
        history = upsert_assignment_history(recovered_document)
        record_activity(
            ActivityType.LEAD_ASSIGNED.value,
            "Lead assignment changed.",
            contact_id=lead["contactId"],
            lead_id=lead_id,
            actor_user_id=actor["_id"],
            metadata={
                "previousCounsellorId": recovered_document["fromCounsellorId"],
                "newCounsellorId": target["_id"],
                "reasonCode": recovered_document["reasonCode"],
            },
            related_entity_type="LEAD_ASSIGNMENT",
            related_entity_id=history["_id"],
            operation_id=operation_id,
        )
        write_audit_event(
            "LEAD_ASSIGNED",
            "SUCCEEDED",
            actor_user_id=actor["_id"],
            entity_type="ADMISSION_LEAD",
            entity_id=lead_id,
            request_id=request_id,
            changed_fields=[
                {
                    "field": "assignedCounsellorId",
                    "previousValue": recovered_document["fromCounsellorId"],
                    "newValue": target["_id"],
                }
            ],
            compact_metadata={"reasonCode": recovered_document["reasonCode"], "recovered": True},
            operation_id=operation_id,
        )
        return lead, history
    if str(previous_counsellor_id) == str(target["_id"]):
        raise ConflictError("LEAD_ALREADY_ASSIGNED", "The lead is already assigned to this Counsellor.")

    now = utc_now()
    assignment_updates: Dict[str, Any] = {
        "assignedCounsellorId": target["_id"],
        "assignedAt": now,
        "assignedBy": actor["_id"],
        "updatedBy": actor["_id"],
        "updatedAt": now,
        "lastActivityAt": now,
        "lastAssignmentOperationId": operation_id,
        "lastAssignmentPreviousCounsellorId": previous_counsellor_id,
        "lastAssignmentReasonCode": normalize_code(reason_code),
        "lastAssignmentReason": reason[:500],
        "lastAssignmentAt": now,
    }
    if reassignment_request_id is not None:
        assignment_updates["lastAssignmentRequestId"] = reassignment_request_id
    updated = update_assignment(
        lead_id,
        expected_version,
        assignment_updates,
    )
    if not updated:
        raise ConflictError(
            "LEAD_VERSION_CONFLICT",
            "The lead changed after it was loaded. Refresh and try again.",
        )

    history_document: Dict[str, Any] = {
        "operationId": operation_id,
        "leadId": lead_id,
        "contactId": lead["contactId"],
        "fromCounsellorId": previous_counsellor_id,
        "toCounsellorId": target["_id"],
        "reasonCode": normalize_code(reason_code),
        "reason": reason[:500],
        "assignedBy": actor["_id"],
        "assignedAt": now,
    }
    if reassignment_request_id is not None:
        history_document["reassignmentRequestId"] = reassignment_request_id
    history = upsert_assignment_history(history_document)
    record_activity(
        ActivityType.LEAD_ASSIGNED.value,
        "Lead assignment changed.",
        contact_id=lead["contactId"],
        lead_id=lead_id,
        actor_user_id=actor["_id"],
        metadata={
            "previousCounsellorId": previous_counsellor_id,
            "newCounsellorId": target["_id"],
            "reasonCode": normalize_code(reason_code),
        },
        related_entity_type="LEAD_ASSIGNMENT",
        related_entity_id=history["_id"],
        operation_id=operation_id,
    )
    write_audit_event(
        "LEAD_ASSIGNED",
        "SUCCEEDED",
        actor_user_id=actor["_id"],
        entity_type="ADMISSION_LEAD",
        entity_id=lead_id,
        request_id=request_id,
        changed_fields=[
            {
                "field": "assignedCounsellorId",
                "previousValue": previous_counsellor_id,
                "newValue": target["_id"],
            }
        ],
        compact_metadata={"reasonCode": normalize_code(reason_code)},
        operation_id=operation_id,
    )
    return updated, history

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.errors import AuthorizationError, ConflictError, NotFoundError, ValidationApiError
from app.models.crm_model import ADMISSION_LEAD_ENTITY_TYPE, ActivityType, LeadStatus
from app.models.user_model import UserRole
from app.repositories.contact_repository import find_contact_by_id, find_contact_preference
from app.repositories.lead_repository import (
    find_active_lead_by_contact,
    find_lead_by_id,
    insert_lead,
    list_course_interests,
    list_leads as repository_list_leads,
    update_lead,
)
from app.schemas.lead_schema import LeadCreateModel, LeadPatchModel
from app.services.access_service import assert_lead_access, is_super_admin
from app.services.activity_service import record_activity
from app.services.assignment_service import record_initial_assignment, validate_counsellor
from app.services.audit_service import write_audit_event
from app.services.preference_service import is_contact_suppressed
from app.utils.crm_validation import clean_optional_text, normalize_code
from app.utils.mongo_utils import object_id_or_not_found
from app.utils.time_utils import utc_now


def _changed_fields(
    current: Dict[str, Any],
    updates: Dict[str, Any],
    unset_fields: List[str],
) -> List[Dict[str, Any]]:
    changed = []
    for field, new_value in updates.items():
        if field in {"updatedAt", "updatedBy", "lastActivityAt"}:
            continue
        if current.get(field) != new_value:
            changed.append(
                {"field": field, "previousValue": current.get(field), "newValue": new_value}
            )
    for field in unset_fields:
        if field in current:
            changed.append(
                {"field": field, "previousValue": current.get(field), "newValue": None}
            )
    return changed


def create_lead(
    payload: LeadCreateModel,
    actor: Dict[str, Any],
    request_id: Optional[str],
    *,
    operation_id: Optional[str] = None,
) -> Dict[str, Any]:
    contact_id = object_id_or_not_found(payload.contactId, "contact")
    contact = find_contact_by_id(contact_id)
    if not contact:
        raise NotFoundError("CONTACT_NOT_FOUND", "The requested contact was not found.")
    if not contact.get("isActive"):
        raise ValidationApiError("CONTACT_INACTIVE", "An active lead cannot be created for an inactive contact.")
    if find_active_lead_by_contact(contact_id):
        raise ConflictError(
            "ACTIVE_LEAD_DUPLICATE",
            "This contact already has an active admission lead.",
        )

    assigned_counsellor = None
    if actor.get("role") == UserRole.COUNSELLOR.value:
        if str(contact.get("createdBy")) != str(actor["_id"]):
            raise AuthorizationError(
                "LEAD_CREATE_FORBIDDEN",
                "A Counsellor may create a lead only for a Contact they just created.",
            )
        if payload.assignedCounsellorId and str(payload.assignedCounsellorId) != str(actor["_id"]):
            raise AuthorizationError("DIRECT_ASSIGNMENT_FORBIDDEN", "Counsellors cannot assign leads.")
        assigned_counsellor = validate_counsellor(actor["_id"])
    elif payload.assignedCounsellorId:
        assigned_counsellor = validate_counsellor(payload.assignedCounsellorId)

    status = payload.status.value
    suppressed = is_contact_suppressed(contact)
    if status == LeadStatus.ADMITTED.value:
        raise ValidationApiError(
            "ADMISSION_WORKFLOW_REQUIRED",
            "Admission confirmation is not available in this phase.",
        )
    if suppressed:
        status = LeadStatus.DO_NOT_CONTACT.value
    elif status == LeadStatus.DO_NOT_CONTACT.value:
        raise ValidationApiError(
            "LEAD_STATUS_REQUIRES_SUPPRESSION",
            "Enable do-not-contact through communication preferences.",
        )

    now = utc_now()
    operation_id = operation_id or f"lead-create:{uuid.uuid4()}"
    source = normalize_code(payload.source) or contact.get("source")
    document: Dict[str, Any] = {
        "entityType": ADMISSION_LEAD_ENTITY_TYPE,
        "contactId": contact_id,
        "status": status,
        "priority": payload.priority.value,
        "score": 0,
        "assignedCounsellorId": assigned_counsellor["_id"] if assigned_counsellor else None,
        "isActive": True,
        "version": 1,
        "createdBy": actor["_id"],
        "createdAt": now,
        "updatedBy": actor["_id"],
        "updatedAt": now,
        "lastActivityAt": now,
    }
    optional_values = {
        "preferredMode": payload.preferredMode.value if payload.preferredMode else None,
        "targetExamYear": payload.targetExamYear,
        "source": source,
        "sourceDetails": clean_optional_text(payload.sourceDetails),
    }
    document.update({key: value for key, value in optional_values.items() if value is not None})
    if assigned_counsellor:
        document.update({"assignedAt": now, "assignedBy": actor["_id"]})
    lead = insert_lead(document)

    record_activity(
        ActivityType.LEAD_CREATED.value,
        "Admission lead created.",
        contact_id=contact_id,
        lead_id=lead["_id"],
        actor_user_id=actor["_id"],
        metadata={"status": status, "priority": payload.priority.value},
        operation_id=operation_id,
    )
    write_audit_event(
        "LEAD_CREATED",
        "SUCCEEDED",
        actor_user_id=actor["_id"],
        entity_type=ADMISSION_LEAD_ENTITY_TYPE,
        entity_id=lead["_id"],
        request_id=request_id,
        compact_metadata={"contactId": contact_id, "status": status},
        operation_id=operation_id,
    )
    if assigned_counsellor:
        record_initial_assignment(
            lead,
            assigned_counsellor,
            actor,
            reason_code="INITIAL_ASSIGNMENT",
            reason="Assigned during lead creation",
            request_id=request_id,
            operation_id=f"{operation_id}:assignment",
        )
    return lead


def get_lead(lead_id_value: Any, actor: Dict[str, Any]) -> Dict[str, Any]:
    lead_id = object_id_or_not_found(lead_id_value, "lead")
    lead = find_lead_by_id(lead_id)
    if not lead:
        raise NotFoundError("LEAD_NOT_FOUND", "The requested lead was not found.")
    assert_lead_access(actor, lead)
    return lead


def get_lead_detail(lead_id_value: Any, actor: Dict[str, Any]) -> Dict[str, Any]:
    lead = get_lead(lead_id_value, actor)
    return {
        "lead": lead,
        "contact": find_contact_by_id(lead["contactId"]),
        "preferences": find_contact_preference(lead["contactId"]),
        "courseInterests": list_course_interests(lead["_id"]),
    }


def list_leads(
    actor: Dict[str, Any],
    *,
    page: int,
    page_size: int,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_counsellor_id: Optional[str] = None,
    unassigned: Optional[bool] = None,
    source: Optional[str] = None,
    preferred_mode: Optional[str] = None,
    target_year: Optional[int] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    activity_from: Optional[datetime] = None,
    activity_to: Optional[datetime] = None,
    sort: str = "-createdAt",
) -> Tuple[List[Dict[str, Any]], int]:
    if created_from and created_to and created_from > created_to:
        raise ValidationApiError("DATE_RANGE_INVALID", "createdFrom must be before createdTo.")
    if activity_from and activity_to and activity_from > activity_to:
        raise ValidationApiError("DATE_RANGE_INVALID", "lastActivityFrom must be before lastActivityTo.")
    query: Dict[str, Any] = {"entityType": ADMISSION_LEAD_ENTITY_TYPE}
    if not is_super_admin(actor):
        if assigned_counsellor_id and str(assigned_counsellor_id) != str(actor["_id"]):
            raise AuthorizationError("LEAD_SCOPE_FORBIDDEN", "Counsellors may list only their assigned leads.")
        if unassigned:
            raise AuthorizationError("LEAD_SCOPE_FORBIDDEN", "Counsellors may list only their assigned leads.")
        query["assignedCounsellorId"] = actor["_id"]
    elif unassigned is True:
        query["assignedCounsellorId"] = None
    elif unassigned is False:
        query["assignedCounsellorId"] = {"$ne": None}
    elif assigned_counsellor_id:
        query["assignedCounsellorId"] = object_id_or_not_found(assigned_counsellor_id, "counsellor")
    if status:
        query["status"] = status
    if priority:
        query["priority"] = priority
    if source:
        query["source"] = normalize_code(source)
    if preferred_mode:
        query["preferredMode"] = preferred_mode
    if target_year is not None:
        query["targetExamYear"] = target_year
    if created_from or created_to:
        query["createdAt"] = {}
        if created_from:
            query["createdAt"]["$gte"] = created_from
        if created_to:
            query["createdAt"]["$lte"] = created_to
    if activity_from or activity_to:
        query["lastActivityAt"] = {}
        if activity_from:
            query["lastActivityAt"]["$gte"] = activity_from
        if activity_to:
            query["lastActivityAt"]["$lte"] = activity_to
    allowed_sorts = {"createdAt", "updatedAt", "lastActivityAt", "priority", "status"}
    descending = sort.startswith("-")
    sort_field = sort[1:] if descending else sort
    if sort_field not in allowed_sorts:
        raise ValidationApiError("SORT_INVALID", "The requested lead sort is not supported.")
    return repository_list_leads(
        query,
        page=page,
        page_size=page_size,
        sort_field=sort_field,
        sort_direction=-1 if descending else 1,
    )


def patch_lead(
    lead_id_value: Any,
    payload: LeadPatchModel,
    actor: Dict[str, Any],
    request_id: Optional[str],
) -> Dict[str, Any]:
    lead = get_lead(lead_id_value, actor)
    if lead.get("status") == LeadStatus.ADMITTED.value:
        raise ConflictError(
            "LEAD_TERMINAL",
            "An admitted lead cannot be changed through the general lead endpoint.",
        )
    supplied = payload.model_dump(exclude_unset=True)
    supplied.pop("version", None)
    if not is_super_admin(actor) and ({"source", "sourceDetails"} & set(supplied)):
        raise AuthorizationError(
            "LEAD_FIELD_FORBIDDEN",
            "Counsellors cannot change lead attribution fields.",
        )

    updates: Dict[str, Any] = {}
    unset_fields: List[str] = []
    for field, value in supplied.items():
        if field == "status":
            value = value.value
            if value == LeadStatus.ADMITTED.value:
                raise ValidationApiError(
                    "ADMISSION_WORKFLOW_REQUIRED",
                    "Admission confirmation is not available through this endpoint.",
                )
            contact = find_contact_by_id(lead["contactId"])
            suppressed = is_contact_suppressed(contact)
            if value == LeadStatus.DO_NOT_CONTACT.value and not suppressed:
                raise ValidationApiError(
                    "LEAD_STATUS_REQUIRES_SUPPRESSION",
                    "Enable do-not-contact through communication preferences.",
                )
            if value != LeadStatus.DO_NOT_CONTACT.value and suppressed:
                raise ValidationApiError(
                    "LEAD_STATUS_SUPPRESSION_CONFLICT",
                    "A suppressed Contact must remain in Do Not Contact status.",
                )
        elif field == "priority":
            value = value.value
        elif field == "preferredMode":
            value = value.value if value else None
        elif field == "source":
            value = normalize_code(value)
        elif field in {"sourceDetails", "lostReason"}:
            value = clean_optional_text(value)
        elif field == "nextActionAt" and value is not None and value.tzinfo is None:
            raise ValidationApiError(
                "NEXT_ACTION_TIMEZONE_REQUIRED",
                "nextActionAt must include a timezone offset.",
                {"nextActionAt": "Include a timezone offset."},
            )
        if value is None:
            unset_fields.append(field)
        else:
            updates[field] = value

    changed_fields = _changed_fields(lead, updates, unset_fields)
    if not changed_fields:
        return lead
    now = utc_now()
    updates.update({"updatedBy": actor["_id"], "updatedAt": now, "lastActivityAt": now})
    updated = update_lead(lead["_id"], payload.version, updates, unset_fields)
    if not updated:
        raise ConflictError(
            "LEAD_VERSION_CONFLICT",
            "The lead changed after it was loaded. Refresh and try again.",
        )

    operation_id = f"lead-update:{uuid.uuid4()}"
    changed_names = {item["field"] for item in changed_fields}
    if "status" in changed_names:
        record_activity(
            ActivityType.LEAD_STATUS_CHANGED.value,
            "Lead status changed.",
            contact_id=lead["contactId"],
            lead_id=lead["_id"],
            actor_user_id=actor["_id"],
            metadata={"changedFields": [item for item in changed_fields if item["field"] == "status"]},
            operation_id=operation_id,
        )
    if "priority" in changed_names:
        record_activity(
            ActivityType.LEAD_PRIORITY_CHANGED.value,
            "Lead priority changed.",
            contact_id=lead["contactId"],
            lead_id=lead["_id"],
            actor_user_id=actor["_id"],
            metadata={"changedFields": [item for item in changed_fields if item["field"] == "priority"]},
            operation_id=operation_id,
        )
    if changed_names - {"status", "priority"}:
        record_activity(
            ActivityType.LEAD_UPDATED.value,
            "Lead details updated.",
            contact_id=lead["contactId"],
            lead_id=lead["_id"],
            actor_user_id=actor["_id"],
            metadata={"changedFields": changed_fields},
            operation_id=operation_id,
        )
    write_audit_event(
        "LEAD_UPDATED",
        "SUCCEEDED",
        actor_user_id=actor["_id"],
        entity_type=ADMISSION_LEAD_ENTITY_TYPE,
        entity_id=lead["_id"],
        request_id=request_id,
        changed_fields=changed_fields,
        operation_id=operation_id,
    )
    return updated

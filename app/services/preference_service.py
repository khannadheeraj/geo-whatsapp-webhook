import uuid
from typing import Any, Dict, Optional

from app.errors import AuthorizationError, ConflictError, ValidationApiError
from app.models.crm_model import (
    ActivityType,
    ActorType,
    CONTACT_PREFERENCE_ENTITY_TYPE,
    WHATSAPP_CHANNEL,
)
from app.models.user_model import UserRole
from app.repositories.contact_repository import (
    deactivate_phone_suppression,
    find_active_phone_suppression,
    find_contact_by_id,
    find_contact_preference,
    update_contact_preference,
    upsert_initial_preference,
)
from app.repositories.lead_repository import find_active_lead_by_contact, set_do_not_contact_for_active_lead
from app.schemas.contact_schema import ContactPreferencePatchModel
from app.services.activity_service import record_activity
from app.services.audit_service import write_audit_event
from app.utils.crm_validation import clean_optional_text, normalize_code
from app.utils.time_utils import utc_now


def initialize_contact_preference(
    contact: Dict[str, Any],
    actor_user_id: Any,
) -> Dict[str, Any]:
    now = utc_now()
    suppression = find_active_phone_suppression(contact["normalizedPhone"])
    is_suppressed = suppression is not None
    document: Dict[str, Any] = {
        "entityType": CONTACT_PREFERENCE_ENTITY_TYPE,
        "contactId": contact["_id"],
        "channel": WHATSAPP_CHANNEL,
        "whatsappAllowed": not is_suppressed,
        "marketingAllowed": False,
        "doNotContact": is_suppressed,
        "changedByType": ActorType.SYSTEM.value if is_suppressed else ActorType.USER.value,
        "changedBy": actor_user_id,
        "version": 1,
        "createdAt": now,
        "updatedAt": now,
    }
    if suppression:
        document.update(
            {
                "optOutSource": suppression.get("source", "PRESERVED_SUPPRESSION"),
                "optOutReason": suppression.get("reason", "Preserved do-not-contact state"),
                "optOutAt": suppression.get("effectiveAt") or suppression.get("createdAt") or now,
            }
        )
    return upsert_initial_preference(document)


def is_contact_suppressed(contact: Dict[str, Any]) -> bool:
    preference = find_contact_preference(contact["_id"])
    return bool(
        (preference and preference.get("doNotContact"))
        or find_active_phone_suppression(contact["normalizedPhone"])
    )


def get_contact_communication_eligibility(
    contact_id: Any,
    *,
    promotional: bool = True,
) -> Dict[str, Any]:
    try:
        from bson import ObjectId

        normalized_contact_id = contact_id if isinstance(contact_id, ObjectId) else ObjectId(str(contact_id))
    except Exception:
        return {"allowed": False, "reasonCode": "CONTACT_INACTIVE_OR_MISSING"}
    contact = find_contact_by_id(normalized_contact_id)
    if not contact or not contact.get("isActive"):
        return {"allowed": False, "reasonCode": "CONTACT_INACTIVE_OR_MISSING"}
    if find_active_phone_suppression(contact["normalizedPhone"]):
        return {"allowed": False, "reasonCode": "PHONE_SUPPRESSED"}
    preference = find_contact_preference(contact["_id"])
    if not preference:
        return {"allowed": False, "reasonCode": "PREFERENCE_MISSING"}
    if preference.get("doNotContact"):
        return {"allowed": False, "reasonCode": "DO_NOT_CONTACT"}
    if not preference.get("whatsappAllowed"):
        return {"allowed": False, "reasonCode": "WHATSAPP_NOT_ALLOWED"}
    if promotional and not preference.get("marketingAllowed"):
        return {"allowed": False, "reasonCode": "MARKETING_NOT_ALLOWED"}
    return {"allowed": True, "reasonCode": "ELIGIBLE"}


def _apply_lead_do_not_contact(
    contact: Dict[str, Any],
    actor_user_id: Optional[Any],
    request_id: Optional[str],
    operation_id: str,
) -> Optional[Dict[str, Any]]:
    previous = find_active_lead_by_contact(contact["_id"])
    if not previous or previous.get("status") in {"DO_NOT_CONTACT", "ADMITTED"}:
        return previous
    now = utc_now()
    updated = set_do_not_contact_for_active_lead(
        contact["_id"],
        {
            "status": "DO_NOT_CONTACT",
            "updatedBy": actor_user_id,
            "updatedAt": now,
            "lastActivityAt": now,
        },
    )
    if not updated:
        return None
    record_activity(
        ActivityType.LEAD_STATUS_CHANGED.value,
        "Lead status changed to Do Not Contact.",
        contact_id=contact["_id"],
        lead_id=updated["_id"],
        actor_user_id=actor_user_id,
        actor_type=ActorType.USER.value if actor_user_id else ActorType.SYSTEM.value,
        metadata={"previousStatus": previous.get("status"), "newStatus": "DO_NOT_CONTACT"},
        operation_id=operation_id,
    )
    write_audit_event(
        "LEAD_STATUS_CHANGED",
        "SUCCEEDED",
        actor_user_id=actor_user_id,
        entity_type="ADMISSION_LEAD",
        entity_id=updated["_id"],
        request_id=request_id,
        changed_fields=[
            {"field": "status", "previousValue": previous.get("status"), "newValue": "DO_NOT_CONTACT"}
        ],
        operation_id=operation_id,
    )
    return updated


def update_preferences(
    contact: Dict[str, Any],
    payload: ContactPreferencePatchModel,
    actor: Dict[str, Any],
    request_id: Optional[str],
) -> Dict[str, Any]:
    if actor.get("role") != UserRole.SUPER_ADMIN.value:
        raise AuthorizationError(
            "SUPPRESSION_ADMIN_REQUIRED",
            "Only a Super Admin may change communication suppression.",
        )
    current = find_contact_preference(contact["_id"])
    if not current:
        current = initialize_contact_preference(contact, actor["_id"])
    supplied = payload.model_dump(exclude_unset=True)
    desired = {
        "whatsappAllowed": current.get("whatsappAllowed", False),
        "marketingAllowed": current.get("marketingAllowed", False),
        "doNotContact": current.get("doNotContact", False),
    }
    for field in ("whatsappAllowed", "marketingAllowed", "doNotContact"):
        if field in supplied:
            desired[field] = supplied[field]

    if current.get("doNotContact") and "doNotContact" not in supplied and (
        desired["whatsappAllowed"] or desired["marketingAllowed"]
    ):
        raise ValidationApiError(
            "SUPPRESSION_EXPLICIT_REVERSAL_REQUIRED",
            "Do-not-contact must be explicitly disabled before communication is re-enabled.",
        )
    if desired["doNotContact"]:
        desired["whatsappAllowed"] = False
        desired["marketingAllowed"] = False
    if desired["marketingAllowed"] and not desired["whatsappAllowed"]:
        raise ValidationApiError(
            "PREFERENCE_COMBINATION_INVALID",
            "Marketing communication requires WhatsApp communication to be allowed.",
            {"marketingAllowed": "Enable WhatsApp communication first."},
        )

    reason = clean_optional_text(payload.reason) or ""
    now = utc_now()
    if current.get("doNotContact") and not desired["doNotContact"]:
        deactivate_phone_suppression(
            contact["normalizedPhone"],
            {
                "deactivatedBy": actor["_id"],
                "deactivatedAt": now,
                "deactivationReason": reason,
                "updatedAt": now,
            },
        )
    updates: Dict[str, Any] = {
        **desired,
        "changedByType": ActorType.USER.value,
        "changedBy": actor["_id"],
        "updatedAt": now,
    }
    if desired["doNotContact"]:
        updates.update(
            {
                "optOutSource": normalize_code(payload.optOutSource) or "MANUAL_ADMIN",
                "optOutReason": reason,
                "optOutAt": now,
            }
        )
    elif current.get("doNotContact"):
        updates.update({"optOutSource": None, "optOutReason": None, "optOutAt": None})
    elif "optOutSource" in supplied:
        updates["optOutSource"] = normalize_code(payload.optOutSource)

    changed_fields = []
    for field, new_value in updates.items():
        if field in {"changedByType", "changedBy", "updatedAt"}:
            continue
        if current.get(field) != new_value:
            changed_fields.append(
                {"field": field, "previousValue": current.get(field), "newValue": new_value}
            )
    if not changed_fields:
        return current

    updated = update_contact_preference(contact["_id"], payload.version, updates)
    if not updated:
        raise ConflictError(
            "CONTACT_PREFERENCE_VERSION_CONFLICT",
            "Communication preferences changed after they were loaded. Refresh and try again.",
        )
    operation_id = f"preference:{uuid.uuid4()}"
    if not current.get("doNotContact") and updated.get("doNotContact"):
        activity_type = ActivityType.DO_NOT_CONTACT_ENABLED.value
        action = "CONTACT_DO_NOT_CONTACT_ENABLED"
    elif current.get("doNotContact") and not updated.get("doNotContact"):
        activity_type = ActivityType.DO_NOT_CONTACT_DISABLED.value
        action = "CONTACT_DO_NOT_CONTACT_DISABLED"
    else:
        activity_type = ActivityType.COMMUNICATION_PREFERENCE_CHANGED.value
        action = "CONTACT_PREFERENCE_CHANGED"
    lead = find_active_lead_by_contact(contact["_id"])
    record_activity(
        activity_type,
        "Contact communication preferences changed.",
        contact_id=contact["_id"],
        lead_id=lead["_id"] if lead else None,
        actor_user_id=actor["_id"],
        metadata={"changedFields": changed_fields, "reason": reason},
        operation_id=operation_id,
    )
    write_audit_event(
        action,
        "SUCCEEDED",
        actor_user_id=actor["_id"],
        entity_type="CONTACT_PREFERENCE",
        entity_id=updated["_id"],
        request_id=request_id,
        changed_fields=changed_fields,
        compact_metadata={"reason": reason},
        operation_id=operation_id,
    )
    if updated.get("doNotContact"):
        _apply_lead_do_not_contact(contact, actor["_id"], request_id, operation_id)
    return updated


def enforce_preserved_phone_suppression(
    contact: Dict[str, Any],
    *,
    actor_user_id: Optional[Any],
    request_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    suppression = find_active_phone_suppression(contact["normalizedPhone"])
    if not suppression:
        return None
    current = find_contact_preference(contact["_id"])
    if not current or current.get("doNotContact"):
        return current
    now = utc_now()
    operation_id = f"preserved-suppression:{uuid.uuid4()}"
    updated = update_contact_preference(
        contact["_id"],
        current["version"],
        {
            "whatsappAllowed": False,
            "marketingAllowed": False,
            "doNotContact": True,
            "optOutSource": suppression.get("source", "PRESERVED_SUPPRESSION"),
            "optOutReason": suppression.get("reason", "Preserved do-not-contact state"),
            "optOutAt": suppression.get("effectiveAt") or suppression.get("createdAt") or now,
            "changedByType": ActorType.SYSTEM.value,
            "changedBy": actor_user_id,
            "updatedAt": now,
        },
    )
    if not updated:
        raise ConflictError(
            "CONTACT_PREFERENCE_VERSION_CONFLICT",
            "Communication preferences changed after they were loaded. Refresh and try again.",
        )
    record_activity(
        ActivityType.DO_NOT_CONTACT_ENABLED.value,
        "Preserved phone suppression applied to the Contact.",
        contact_id=contact["_id"],
        actor_user_id=actor_user_id,
        actor_type=ActorType.SYSTEM.value,
        metadata={"source": updated.get("optOutSource")},
        operation_id=operation_id,
    )
    write_audit_event(
        "CONTACT_DO_NOT_CONTACT_ENABLED",
        "SUCCEEDED",
        actor_user_id=actor_user_id,
        entity_type="CONTACT_PREFERENCE",
        entity_id=updated["_id"],
        request_id=request_id,
        changed_fields=[
            {"field": "doNotContact", "previousValue": False, "newValue": True}
        ],
        operation_id=operation_id,
    )
    _apply_lead_do_not_contact(contact, actor_user_id, request_id, operation_id)
    return updated

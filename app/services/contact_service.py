import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId

from app.errors import AuthorizationError, ConflictError, NotFoundError, ValidationApiError
from app.models.crm_model import CONTACT_ENTITY_TYPE, ActivityType
from app.models.user_model import UserRole
from app.repositories.contact_repository import (
    find_contact_by_id,
    find_contact_by_normalized_phone,
    find_contact_preference,
    find_contact_preferences,
    insert_contact,
    list_contacts as repository_list_contacts,
    preference_contact_ids,
    self_created_contact_ids,
    update_contact,
)
from app.repositories.lead_repository import (
    assigned_contact_ids,
    contact_ids_by_assignment,
    contact_ids_with_active_lead,
    find_active_leads_by_contacts,
    find_active_lead_by_contact,
    insert_course_interest,
    set_invalid_for_inactive_contact,
)
from app.repositories.user_repository import find_staff_users_by_ids
from app.schemas.contact_schema import ContactCreateModel, ContactPatchModel
from app.schemas.lead_schema import LeadCreateModel
from app.services.access_service import assert_contact_access, is_super_admin
from app.services.activity_service import record_activity
from app.services.audit_service import write_audit_event
from app.services.preference_service import enforce_preserved_phone_suppression, initialize_contact_preference
from app.utils.crm_validation import (
    clean_optional_text,
    derive_display_name,
    normalize_contact_email,
    normalize_display_name,
    normalize_lead_source,
)
from app.utils.mongo_utils import object_id_or_not_found
from app.utils.phone_utils import normalize_indian_phone
from app.utils.time_utils import utc_now


_TEXT_FIELDS = {
    "firstName",
    "lastName",
    "displayName",
    "city",
    "state",
    "companyOrCollege",
    "instagramProfile",
    "facebookProfile",
    "linkedinProfile",
    "sourceDetails",
    "notes",
}


def _base_contact_values(payload: ContactCreateModel) -> Dict[str, Any]:
    first_name = clean_optional_text(payload.firstName)
    last_name = clean_optional_text(payload.lastName)
    display_name = clean_optional_text(payload.displayName) or derive_display_name(first_name, last_name)
    normalized_phone = normalize_indian_phone(payload.phone)
    alternate_phone = clean_optional_text(payload.alternatePhone)
    normalized_alternate_phone = (
        normalize_indian_phone(alternate_phone, "alternatePhone") if alternate_phone else None
    )
    if normalized_alternate_phone == normalized_phone:
        raise ValidationApiError(
            "CONTACT_ALTERNATE_PHONE_DUPLICATE",
            "The alternate phone must differ from the primary phone.",
            {"alternatePhone": "Use a different phone number."},
        )
    normalized_email = normalize_contact_email(payload.email)
    values: Dict[str, Any] = {
        "firstName": first_name,
        "lastName": last_name,
        "displayName": display_name or None,
        "normalizedDisplayName": normalize_display_name(display_name) or None,
        "phone": clean_optional_text(payload.phone),
        "normalizedPhone": normalized_phone,
        "alternatePhone": alternate_phone,
        "normalizedAlternatePhone": normalized_alternate_phone,
        "email": clean_optional_text(payload.email),
        "normalizedEmail": normalized_email,
        "city": clean_optional_text(payload.city),
        "state": clean_optional_text(payload.state),
        "companyOrCollege": clean_optional_text(payload.companyOrCollege),
        "instagramProfile": clean_optional_text(payload.instagramProfile),
        "facebookProfile": clean_optional_text(payload.facebookProfile),
        "linkedinProfile": clean_optional_text(payload.linkedinProfile),
        "source": normalize_lead_source(payload.source),
        "sourceDetails": clean_optional_text(payload.sourceDetails),
        "notes": clean_optional_text(payload.notes),
        "isIncomplete": not bool(display_name),
    }
    return {key: value for key, value in values.items() if value is not None}


def create_contact(
    payload: ContactCreateModel,
    actor: Dict[str, Any],
    request_id: Optional[str],
    *,
    operation_id: Optional[str] = None,
    contact_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if actor.get("role") == UserRole.COUNSELLOR.value and not payload.createLead:
        raise ValidationApiError(
            "COUNSELLOR_LEAD_REQUIRED",
            "A Counsellor-created Contact must include its assigned admission lead.",
        )
    if not payload.createLead and (
        payload.assignedCounsellorId
        or payload.courseInterest
        or payload.preferredMode
        or payload.targetExamYear
        or payload.leadPriority.value != "MEDIUM"
    ):
        raise ValidationApiError(
            "CONTACT_LEAD_OPTIONS_INVALID",
            "Lead options require active Lead creation.",
        )
    values = _base_contact_values(payload)
    if actor.get("role") == UserRole.COUNSELLOR.value:
        values["source"] = "COUNSELLOR_MANUAL_ENTRY"
    elif not values.get("source"):
        values["source"] = "MANUAL_ENTRY"
    existing = find_contact_by_normalized_phone(values["normalizedPhone"])
    if existing:
        field_errors: Dict[str, Any] = {"phone": "Duplicate normalized phone"}
        try:
            assert_contact_access(actor, existing)
            field_errors["existingContactId"] = str(existing["_id"])
        except AuthorizationError:
            pass
        raise ConflictError(
            "CONTACT_PHONE_DUPLICATE",
            "A contact with this phone number already exists.",
            field_errors,
        )
    now = utc_now()
    operation_id = operation_id or f"contact-create:{uuid.uuid4()}"
    contact = insert_contact(
        {
            "entityType": CONTACT_ENTITY_TYPE,
            **values,
            **(contact_metadata or {}),
            "isActive": True,
            "version": 1,
            "createdBy": actor["_id"],
            "createdAt": now,
            "updatedBy": actor["_id"],
            "updatedAt": now,
        }
    )
    preference = initialize_contact_preference(contact, actor["_id"])
    record_activity(
        ActivityType.CONTACT_CREATED.value,
        "Contact created.",
        contact_id=contact["_id"],
        actor_user_id=actor["_id"],
        metadata={"source": contact.get("source")},
        operation_id=operation_id,
    )
    write_audit_event(
        "CONTACT_CREATED",
        "SUCCEEDED",
        actor_user_id=actor["_id"],
        entity_type=CONTACT_ENTITY_TYPE,
        entity_id=contact["_id"],
        request_id=request_id,
        compact_metadata={"source": contact.get("source")},
        operation_id=operation_id,
    )
    if preference.get("doNotContact"):
        record_activity(
            ActivityType.DO_NOT_CONTACT_ENABLED.value,
            "Preserved phone suppression applied during Contact creation.",
            contact_id=contact["_id"],
            actor_user_id=actor["_id"],
            metadata={"source": preference.get("optOutSource")},
            operation_id=f"{operation_id}:suppression",
        )
        write_audit_event(
            "CONTACT_DO_NOT_CONTACT_ENABLED",
            "SUCCEEDED",
            actor_user_id=actor["_id"],
            entity_type="CONTACT_PREFERENCE",
            entity_id=preference["_id"],
            request_id=request_id,
            changed_fields=[
                {"field": "doNotContact", "previousValue": False, "newValue": True}
            ],
            compact_metadata={"source": preference.get("optOutSource")},
            operation_id=f"{operation_id}:suppression",
        )

    lead = None
    if payload.createLead:
        from app.services.lead_service import create_lead

        lead = create_lead(
            LeadCreateModel(
                contactId=str(contact["_id"]),
                status=payload.leadStatus,
                source=contact.get("source"),
                priority=payload.leadPriority,
                preferredMode=payload.preferredMode,
                targetExamYear=payload.targetExamYear,
                assignedCounsellorId=payload.assignedCounsellorId,
            ),
            actor,
            request_id,
            operation_id=f"{operation_id}:lead",
        )
        course_interest = clean_optional_text(payload.courseInterest)
        if course_interest:
            insert_course_interest(
                {
                    "leadId": lead["_id"],
                    "temporaryCourseLabel": course_interest,
                    "isPrimary": True,
                    "preferredMode": payload.preferredMode.value if payload.preferredMode else None,
                    "createdBy": actor["_id"],
                    "createdAt": now,
                    "updatedBy": actor["_id"],
                    "updatedAt": now,
                }
            )
    return {"contact": contact, "preferences": preference, "lead": lead}


def get_contact(contact_id_value: Any, actor: Dict[str, Any]) -> Dict[str, Any]:
    contact_id = object_id_or_not_found(contact_id_value, "contact")
    contact = find_contact_by_id(contact_id)
    if not contact:
        raise NotFoundError("CONTACT_NOT_FOUND", "The requested contact was not found.")
    assert_contact_access(actor, contact)
    return contact


def get_contact_detail(contact_id_value: Any, actor: Dict[str, Any]) -> Dict[str, Any]:
    contact = get_contact(contact_id_value, actor)
    active_lead = find_active_lead_by_contact(contact["_id"])
    assigned_counsellor = None
    if active_lead and active_lead.get("assignedCounsellorId"):
        users = find_staff_users_by_ids([active_lead["assignedCounsellorId"]])
        assigned_counsellor = users[0] if users else None
    return {
        "contact": contact,
        "preferences": find_contact_preference(contact["_id"]),
        "activeLead": active_lead,
        "assignedCounsellor": assigned_counsellor,
    }


def list_contacts(
    actor: Dict[str, Any],
    *,
    page: int,
    page_size: int,
    search: Optional[str] = None,
    city: Optional[str] = None,
    source: Optional[str] = None,
    is_active: Optional[bool] = None,
    do_not_contact: Optional[bool] = None,
    assigned_counsellor_id: Optional[str] = None,
    unassigned: Optional[bool] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    sort: str = "-createdAt",
) -> Tuple[
    List[Dict[str, Any]],
    int,
    Dict[ObjectId, Dict[str, Any]],
    Dict[ObjectId, Dict[str, Any]],
    Dict[ObjectId, Dict[str, Any]],
]:
    if created_from and created_to and created_from > created_to:
        raise ValidationApiError("DATE_RANGE_INVALID", "createdFrom must be before createdTo.")
    query: Dict[str, Any] = {"entityType": CONTACT_ENTITY_TYPE}
    scoped_contact_ids: Optional[List[ObjectId]] = None
    if not is_super_admin(actor):
        if assigned_counsellor_id and str(assigned_counsellor_id) != str(actor["_id"]):
            raise AuthorizationError("CONTACT_SCOPE_FORBIDDEN", "Counsellors may access only their assigned Contacts.")
        if unassigned:
            raise AuthorizationError("CONTACT_SCOPE_FORBIDDEN", "Counsellors may access only their assigned Contacts.")
        assigned_ids = assigned_contact_ids(actor["_id"])
        created_ids = self_created_contact_ids(actor["_id"])
        resolved_ids = set(contact_ids_with_active_lead(created_ids))
        unresolved_ids = [contact_id for contact_id in created_ids if contact_id not in resolved_ids]
        scoped_contact_ids = list(dict.fromkeys([*assigned_ids, *unresolved_ids]))
    if assigned_counsellor_id or unassigned is not None:
        assignment_ids = contact_ids_by_assignment(
            object_id_or_not_found(assigned_counsellor_id, "counsellor")
            if assigned_counsellor_id
            else None,
            unassigned,
        )
        if scoped_contact_ids is None:
            scoped_contact_ids = assignment_ids
        else:
            allowed = set(assignment_ids)
            scoped_contact_ids = [item for item in scoped_contact_ids if item in allowed]
    if do_not_contact is not None:
        preference_ids = preference_contact_ids(do_not_contact)
        if scoped_contact_ids is None:
            scoped_contact_ids = preference_ids
        else:
            allowed = set(preference_ids)
            scoped_contact_ids = [item for item in scoped_contact_ids if item in allowed]
    if scoped_contact_ids is not None:
        query["_id"] = {"$in": scoped_contact_ids}
    if search and search.strip():
        cleaned_search = " ".join(search.strip().split())
        digits = re.sub(r"\D", "", cleaned_search)
        alternatives = [
            {"normalizedDisplayName": {"$regex": re.escape(cleaned_search.casefold())}},
            {"normalizedEmail": {"$regex": re.escape(cleaned_search.casefold())}},
        ]
        if digits:
            alternatives.append({"normalizedPhone": {"$regex": re.escape(digits)}})
            alternatives.append({"normalizedAlternatePhone": {"$regex": re.escape(digits)}})
        query["$or"] = alternatives
    if city:
        query["city"] = {"$regex": f"^{re.escape(city.strip())}$", "$options": "i"}
    if source:
        query["source"] = normalize_lead_source(source)
    if is_active is not None:
        query["isActive"] = is_active
    if created_from or created_to:
        query["createdAt"] = {}
        if created_from:
            query["createdAt"]["$gte"] = created_from
        if created_to:
            query["createdAt"]["$lte"] = created_to
    allowed_sorts = {"createdAt", "updatedAt", "normalizedDisplayName"}
    descending = sort.startswith("-")
    sort_field = sort[1:] if descending else sort
    if sort_field not in allowed_sorts:
        raise ValidationApiError("SORT_INVALID", "The requested contact sort is not supported.")
    documents, total = repository_list_contacts(
        query,
        page=page,
        page_size=page_size,
        sort_field=sort_field,
        sort_direction=-1 if descending else 1,
    )
    preferences = find_contact_preferences([document["_id"] for document in documents])
    leads = find_active_leads_by_contacts([document["_id"] for document in documents])
    owner_ids = list({lead["assignedCounsellorId"] for lead in leads if lead.get("assignedCounsellorId")})
    owners = find_staff_users_by_ids(owner_ids)
    return (
        documents,
        total,
        {item["contactId"]: item for item in preferences},
        {item["contactId"]: item for item in leads},
        {item["_id"]: item for item in owners},
    )


def _contact_changed_fields(
    current: Dict[str, Any],
    updates: Dict[str, Any],
    unset_fields: List[str],
) -> List[Dict[str, Any]]:
    changed = []
    for field, new_value in updates.items():
        if field in {"updatedAt", "updatedBy"}:
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


def patch_contact(
    contact_id_value: Any,
    payload: ContactPatchModel,
    actor: Dict[str, Any],
    request_id: Optional[str],
) -> Dict[str, Any]:
    contact = get_contact(contact_id_value, actor)
    supplied_fields = payload.model_fields_set - {"version"}
    protected_fields = {"source", "sourceDetails", "isActive"}
    if not is_super_admin(actor) and (supplied_fields & protected_fields):
        raise AuthorizationError(
            "CONTACT_FIELD_FORBIDDEN",
            "Counsellors cannot change Contact source or active state.",
        )
    supplied = payload.model_dump(exclude_unset=True)
    supplied.pop("version", None)
    updates: Dict[str, Any] = {}
    unset_fields: List[str] = []

    if "phone" in supplied:
        if payload.phone is None:
            raise ValidationApiError(
                "CONTACT_PHONE_REQUIRED",
                "A normal Contact requires a primary phone number.",
                {"phone": "Phone is required."},
            )
        updates["phone"] = clean_optional_text(payload.phone)
        updates["normalizedPhone"] = normalize_indian_phone(payload.phone)
    if "alternatePhone" in supplied:
        cleaned_alternate = clean_optional_text(payload.alternatePhone)
        if cleaned_alternate:
            updates["alternatePhone"] = cleaned_alternate
            updates["normalizedAlternatePhone"] = normalize_indian_phone(
                cleaned_alternate, "alternatePhone"
            )
        else:
            unset_fields.extend(["alternatePhone", "normalizedAlternatePhone"])
    resulting_primary = updates.get("normalizedPhone", contact["normalizedPhone"])
    resulting_alternate = updates.get(
        "normalizedAlternatePhone", contact.get("normalizedAlternatePhone")
    )
    if resulting_alternate and resulting_alternate == resulting_primary:
        raise ValidationApiError(
            "CONTACT_ALTERNATE_PHONE_DUPLICATE",
            "The alternate phone must differ from the primary phone.",
            {"alternatePhone": "Use a different phone number."},
        )

    if "email" in supplied:
        normalized_email = normalize_contact_email(payload.email)
        cleaned_email = clean_optional_text(payload.email)
        if normalized_email:
            updates.update({"email": cleaned_email, "normalizedEmail": normalized_email})
        else:
            unset_fields.extend(["email", "normalizedEmail"])

    for field in _TEXT_FIELDS - {"firstName", "lastName", "displayName", "sourceDetails"}:
        if field in supplied:
            value = clean_optional_text(supplied[field])
            if value is None:
                unset_fields.append(field)
            else:
                updates[field] = value
    if "sourceDetails" in supplied:
        value = clean_optional_text(payload.sourceDetails)
        if value is None:
            unset_fields.append("sourceDetails")
        else:
            updates["sourceDetails"] = value
    if "source" in supplied:
        value = normalize_lead_source(payload.source)
        if value is None:
            unset_fields.append("source")
        else:
            updates["source"] = value
    if "isActive" in supplied:
        if payload.isActive is None:
            raise ValidationApiError(
                "CONTACT_ACTIVE_STATE_INVALID",
                "isActive must be true or false.",
                {"isActive": "Choose true or false."},
            )
        updates["isActive"] = payload.isActive

    for field in ("firstName", "lastName"):
        if field in supplied:
            value = clean_optional_text(supplied[field])
            if value is None:
                unset_fields.append(field)
            else:
                updates[field] = value
    name_parts_changed = bool({"firstName", "lastName"} & supplied_fields)
    if "displayName" in supplied or name_parts_changed:
        first_name = updates.get("firstName", None if "firstName" in unset_fields else contact.get("firstName"))
        last_name = updates.get("lastName", None if "lastName" in unset_fields else contact.get("lastName"))
        display_name = (
            clean_optional_text(payload.displayName)
            if "displayName" in supplied
            else derive_display_name(first_name, last_name)
        )
        display_name = display_name or derive_display_name(first_name, last_name)
        if display_name:
            updates["displayName"] = display_name
            updates["normalizedDisplayName"] = normalize_display_name(display_name)
        else:
            unset_fields.extend(["displayName", "normalizedDisplayName"])
        updates["isIncomplete"] = not bool(display_name)

    unset_fields = sorted(set(unset_fields) - set(updates))
    changed_fields = _contact_changed_fields(contact, updates, unset_fields)
    if not changed_fields:
        return contact
    now = utc_now()
    updates.update({"updatedBy": actor["_id"], "updatedAt": now})
    updated = update_contact(contact["_id"], payload.version, updates, unset_fields)
    if not updated:
        raise ConflictError(
            "CONTACT_VERSION_CONFLICT",
            "The Contact changed after it was loaded. Refresh and try again.",
        )

    changed_names = {item["field"] for item in changed_fields}
    if "normalizedPhone" in changed_names:
        activity_type = ActivityType.CONTACT_PHONE_CORRECTED.value
        action = "CONTACT_PHONE_CORRECTED"
    elif changed_names & {"firstName", "lastName", "displayName", "normalizedDisplayName"}:
        activity_type = ActivityType.CONTACT_NAME_CORRECTED.value
        action = "CONTACT_NAME_CORRECTED"
    else:
        activity_type = ActivityType.CONTACT_CORRECTED.value
        action = "CONTACT_CORRECTED"
    operation_id = f"contact-update:{uuid.uuid4()}"
    lead = find_active_lead_by_contact(contact["_id"])
    record_activity(
        activity_type,
        "Contact details corrected.",
        contact_id=contact["_id"],
        lead_id=lead["_id"] if lead else None,
        actor_user_id=actor["_id"],
        metadata={"changedFields": changed_fields},
        operation_id=operation_id,
    )
    write_audit_event(
        action,
        "SUCCEEDED",
        actor_user_id=actor["_id"],
        entity_type=CONTACT_ENTITY_TYPE,
        entity_id=contact["_id"],
        request_id=request_id,
        changed_fields=changed_fields,
        operation_id=operation_id,
    )
    if "isActive" in changed_names and updated.get("isActive") is False and lead:
        invalid_lead = set_invalid_for_inactive_contact(
            contact["_id"],
            {
                "status": "INVALID_CONTACT",
                "updatedBy": actor["_id"],
                "updatedAt": now,
                "lastActivityAt": now,
            },
        )
        if invalid_lead:
            record_activity(
                ActivityType.LEAD_STATUS_CHANGED.value,
                "Lead status changed because the Contact was deactivated.",
                contact_id=contact["_id"],
                lead_id=lead["_id"],
                actor_user_id=actor["_id"],
                metadata={"previousStatus": lead.get("status"), "newStatus": "INVALID_CONTACT"},
                operation_id=f"{operation_id}:lead-status",
            )
            write_audit_event(
                "LEAD_STATUS_CHANGED",
                "SUCCEEDED",
                actor_user_id=actor["_id"],
                entity_type="ADMISSION_LEAD",
                entity_id=lead["_id"],
                request_id=request_id,
                changed_fields=[
                    {
                        "field": "status",
                        "previousValue": lead.get("status"),
                        "newValue": "INVALID_CONTACT",
                    }
                ],
                operation_id=f"{operation_id}:lead-status",
            )
    if "normalizedPhone" in changed_names:
        enforce_preserved_phone_suppression(
            updated,
            actor_user_id=actor["_id"],
            request_id=request_id,
        )
    return updated

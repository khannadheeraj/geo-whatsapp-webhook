from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.db.mongodb import get_collection
from app.errors import ConflictError
from app.models.crm_model import ADMISSION_LEAD_ENTITY_TYPE


def insert_lead(document: Dict[str, Any]) -> Dict[str, Any]:
    try:
        result = get_collection("leads").insert_one(document)
    except DuplicateKeyError as exc:
        raise ConflictError(
            "ACTIVE_LEAD_DUPLICATE",
            "This contact already has an active admission lead.",
        ) from exc
    document["_id"] = result.inserted_id
    return document


def find_lead_by_id(lead_id: ObjectId) -> Optional[Dict[str, Any]]:
    return get_collection("leads").find_one(
        {"_id": lead_id, "entityType": ADMISSION_LEAD_ENTITY_TYPE}
    )


def find_leads_by_ids(lead_ids: List[ObjectId]) -> List[Dict[str, Any]]:
    if not lead_ids:
        return []
    return list(
        get_collection("leads").find(
            {"_id": {"$in": lead_ids}, "entityType": ADMISSION_LEAD_ENTITY_TYPE}
        )
    )


def find_active_lead_by_contact(contact_id: ObjectId) -> Optional[Dict[str, Any]]:
    return get_collection("leads").find_one(
        {
            "contactId": contact_id,
            "entityType": ADMISSION_LEAD_ENTITY_TYPE,
            "isActive": True,
        }
    )


def find_active_leads_by_contacts(contact_ids: List[ObjectId]) -> List[Dict[str, Any]]:
    if not contact_ids:
        return []
    return list(
        get_collection("leads").find(
            {
                "contactId": {"$in": contact_ids},
                "entityType": ADMISSION_LEAD_ENTITY_TYPE,
                "isActive": True,
            }
        )
    )


def contact_ids_by_assignment(
    assigned_counsellor_id: Optional[ObjectId], unassigned: Optional[bool]
) -> List[ObjectId]:
    query: Dict[str, Any] = {"entityType": ADMISSION_LEAD_ENTITY_TYPE, "isActive": True}
    if assigned_counsellor_id is not None:
        query["assignedCounsellorId"] = assigned_counsellor_id
    elif unassigned is True:
        query["assignedCounsellorId"] = None
    elif unassigned is False:
        query["assignedCounsellorId"] = {"$ne": None}
    return list(get_collection("leads").distinct("contactId", query))


def assigned_contact_ids(counsellor_id: ObjectId) -> List[ObjectId]:
    return list(
        get_collection("leads").distinct(
            "contactId",
            {
                "entityType": ADMISSION_LEAD_ENTITY_TYPE,
                "assignedCounsellorId": counsellor_id,
            },
        )
    )


def contact_ids_with_active_lead(contact_ids: List[ObjectId]) -> List[ObjectId]:
    if not contact_ids:
        return []
    return list(
        get_collection("leads").distinct(
            "contactId",
            {
                "entityType": ADMISSION_LEAD_ENTITY_TYPE,
                "contactId": {"$in": contact_ids},
                "isActive": True,
            },
        )
    )


def list_leads(
    query: Dict[str, Any],
    *,
    page: int,
    page_size: int,
    sort_field: str,
    sort_direction: int,
) -> Tuple[List[Dict[str, Any]], int]:
    collection = get_collection("leads")
    total = collection.count_documents(query)
    documents = list(
        collection.find(query)
        .sort([(sort_field, sort_direction), ("_id", sort_direction)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return documents, total


def update_lead(
    lead_id: ObjectId,
    version: int,
    updates: Dict[str, Any],
    unset_fields: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    update_document: Dict[str, Any] = {"$set": updates, "$inc": {"version": 1}}
    if unset_fields:
        update_document["$unset"] = {field: "" for field in unset_fields}
    return get_collection("leads").find_one_and_update(
        {"_id": lead_id, "entityType": ADMISSION_LEAD_ENTITY_TYPE, "version": version},
        update_document,
        return_document=ReturnDocument.AFTER,
    )


def update_assignment(
    lead_id: ObjectId,
    version: int,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    return get_collection("leads").find_one_and_update(
        {"_id": lead_id, "entityType": ADMISSION_LEAD_ENTITY_TYPE, "version": version},
        {"$set": updates, "$inc": {"version": 1}},
        return_document=ReturnDocument.AFTER,
    )


def set_do_not_contact_for_active_lead(
    contact_id: ObjectId,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    return get_collection("leads").find_one_and_update(
        {
            "contactId": contact_id,
            "entityType": ADMISSION_LEAD_ENTITY_TYPE,
            "isActive": True,
            "status": {"$nin": ["DO_NOT_CONTACT", "ADMITTED"]},
        },
        {"$set": updates, "$inc": {"version": 1}},
        return_document=ReturnDocument.AFTER,
    )


def set_invalid_for_inactive_contact(
    contact_id: ObjectId,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    return get_collection("leads").find_one_and_update(
        {
            "contactId": contact_id,
            "entityType": ADMISSION_LEAD_ENTITY_TYPE,
            "isActive": True,
            "status": {"$nin": ["INVALID_CONTACT", "ADMITTED", "DO_NOT_CONTACT"]},
        },
        {"$set": updates, "$inc": {"version": 1}},
        return_document=ReturnDocument.AFTER,
    )


def upsert_assignment_history(document: Dict[str, Any]) -> Dict[str, Any]:
    collection = get_collection("lead_assignments")
    collection.update_one(
        {"operationId": document["operationId"]},
        {"$setOnInsert": document},
        upsert=True,
    )
    return collection.find_one({"operationId": document["operationId"]})


def find_assignment_by_operation(operation_id: str) -> Optional[Dict[str, Any]]:
    return get_collection("lead_assignments").find_one({"operationId": operation_id})


def list_assignment_history(
    lead_id: ObjectId,
    *,
    page: int,
    page_size: int,
) -> Tuple[List[Dict[str, Any]], int]:
    query = {"leadId": lead_id}
    collection = get_collection("lead_assignments")
    total = collection.count_documents(query)
    documents = list(
        collection.find(query)
        .sort([("assignedAt", -1), ("_id", -1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return documents, total


def list_course_interests(lead_id: ObjectId) -> List[Dict[str, Any]]:
    return list(
        get_collection("lead_course_interests")
        .find({"leadId": lead_id})
        .sort([("isPrimary", -1), ("createdAt", 1), ("_id", 1)])
    )


def insert_course_interest(document: Dict[str, Any]) -> Dict[str, Any]:
    """Internal repository contract; public mutation APIs are intentionally deferred."""
    temporary_label = str(document.get("temporaryCourseLabel") or "").strip()
    if not document.get("courseId") and not temporary_label:
        from app.errors import ValidationApiError

        raise ValidationApiError(
            "COURSE_INTEREST_REFERENCE_REQUIRED",
            "A course interest requires a formal Course reference or a temporary normalized label.",
        )
    if temporary_label:
        document["temporaryCourseLabel"] = " ".join(temporary_label.upper().split())[:200]
    try:
        result = get_collection("lead_course_interests").insert_one(document)
    except DuplicateKeyError as exc:
        raise ConflictError(
            "PRIMARY_COURSE_INTEREST_DUPLICATE",
            "This lead already has a primary course interest.",
        ) from exc
    document["_id"] = result.inserted_id
    return document

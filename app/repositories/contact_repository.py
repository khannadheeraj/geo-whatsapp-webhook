from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.db.mongodb import get_collection
from app.errors import ConflictError
from app.models.crm_model import CONTACT_ENTITY_TYPE, WHATSAPP_CHANNEL


def insert_contact(document: Dict[str, Any]) -> Dict[str, Any]:
    try:
        result = get_collection("contacts").insert_one(document)
    except DuplicateKeyError as exc:
        raise ConflictError(
            "CONTACT_PHONE_DUPLICATE",
            "A contact with this phone number already exists.",
            {"phone": "Duplicate normalized phone"},
        ) from exc
    document["_id"] = result.inserted_id
    return document


def find_contact_by_id(contact_id: ObjectId) -> Optional[Dict[str, Any]]:
    return get_collection("contacts").find_one(
        {"_id": contact_id, "entityType": CONTACT_ENTITY_TYPE}
    )


def find_contact_by_normalized_phone(normalized_phone: str) -> Optional[Dict[str, Any]]:
    return get_collection("contacts").find_one(
        {"entityType": CONTACT_ENTITY_TYPE, "normalizedPhone": normalized_phone}
    )


def update_contact(
    contact_id: ObjectId,
    version: int,
    updates: Dict[str, Any],
    unset_fields: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    update_document: Dict[str, Any] = {"$set": updates, "$inc": {"version": 1}}
    if unset_fields:
        update_document["$unset"] = {field: "" for field in unset_fields}
    try:
        return get_collection("contacts").find_one_and_update(
            {"_id": contact_id, "entityType": CONTACT_ENTITY_TYPE, "version": version},
            update_document,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError as exc:
        raise ConflictError(
            "CONTACT_PHONE_DUPLICATE",
            "A contact with this phone number already exists.",
            {"phone": "Duplicate normalized phone"},
        ) from exc


def list_contacts(
    query: Dict[str, Any],
    *,
    page: int,
    page_size: int,
    sort_field: str,
    sort_direction: int,
) -> Tuple[List[Dict[str, Any]], int]:
    collection = get_collection("contacts")
    total = collection.count_documents(query)
    documents = list(
        collection.find(query)
        .sort([(sort_field, sort_direction), ("_id", sort_direction)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return documents, total


def self_created_contact_ids(user_id: ObjectId) -> List[ObjectId]:
    return list(
        get_collection("contacts").distinct(
            "_id", {"entityType": CONTACT_ENTITY_TYPE, "createdBy": user_id}
        )
    )


def upsert_initial_preference(document: Dict[str, Any]) -> Dict[str, Any]:
    collection = get_collection("contact_preferences")
    collection.update_one(
        {"contactId": document["contactId"], "channel": WHATSAPP_CHANNEL},
        {"$setOnInsert": document},
        upsert=True,
    )
    return collection.find_one(
        {"contactId": document["contactId"], "channel": WHATSAPP_CHANNEL}
    )


def find_contact_preference(contact_id: ObjectId) -> Optional[Dict[str, Any]]:
    return get_collection("contact_preferences").find_one(
        {"contactId": contact_id, "channel": WHATSAPP_CHANNEL}
    )


def find_contact_preferences(contact_ids: List[ObjectId]) -> List[Dict[str, Any]]:
    if not contact_ids:
        return []
    return list(
        get_collection("contact_preferences").find(
            {"contactId": {"$in": contact_ids}, "channel": WHATSAPP_CHANNEL}
        )
    )


def preference_contact_ids(do_not_contact: bool) -> List[ObjectId]:
    return list(
        get_collection("contact_preferences").distinct(
            "contactId", {"channel": WHATSAPP_CHANNEL, "doNotContact": do_not_contact}
        )
    )


def update_contact_preference(
    contact_id: ObjectId,
    version: int,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    return get_collection("contact_preferences").find_one_and_update(
        {"contactId": contact_id, "channel": WHATSAPP_CHANNEL, "version": version},
        {"$set": updates, "$inc": {"version": 1}},
        return_document=ReturnDocument.AFTER,
    )


def find_active_phone_suppression(normalized_phone: str) -> Optional[Dict[str, Any]]:
    return get_collection("suppression_entries").find_one(
        {
            "normalizedPhone": normalized_phone,
            "channel": WHATSAPP_CHANNEL,
            "isActive": True,
        }
    )


def deactivate_phone_suppression(
    normalized_phone: str,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    return get_collection("suppression_entries").find_one_and_update(
        {
            "normalizedPhone": normalized_phone,
            "channel": WHATSAPP_CHANNEL,
            "isActive": True,
        },
        {"$set": {**updates, "isActive": False}},
        return_document=ReturnDocument.AFTER,
    )

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from pymongo.errors import DuplicateKeyError

from app.db.mongodb import get_collection


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def upsert_conversation(
    identity: Dict[str, Any], updates: Dict[str, Any], defaults: Dict[str, Any]
) -> Dict[str, Any]:
    collection = get_collection("conversations")
    collection.update_one(
        identity,
        {"$set": updates, "$setOnInsert": defaults},
        upsert=True,
    )
    return collection.find_one(identity)


def insert_inbound_message(document: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    collection = get_collection("whatsapp_messages")
    try:
        result = collection.insert_one(document)
        document["_id"] = result.inserted_id
        return document, True
    except DuplicateKeyError:
        return collection.find_one({"providerMessageId": document["providerMessageId"]}), False


def upsert_outbound_message(document: Dict[str, Any]) -> Dict[str, Any]:
    collection = get_collection("whatsapp_messages")
    collection.update_one(
        {"providerMessageId": document["providerMessageId"]},
        {"$setOnInsert": document},
        upsert=True,
    )
    return collection.find_one({"providerMessageId": document["providerMessageId"]})


def enrich_message_if_missing(
    provider_message_id: str, fields: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    collection = get_collection("whatsapp_messages")
    for field, value in fields.items():
        if value is not None:
            collection.update_one(
                {"providerMessageId": provider_message_id, field: None},
                {"$set": {field: value, "updatedAt": _now()}},
            )
    return collection.find_one({"providerMessageId": provider_message_id})


def apply_status(
    provider_message_id: str,
    status: str,
    occurred_at: datetime,
    failure_code: Optional[str] = None,
    failure_message: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    collection = get_collection("whatsapp_messages")
    timestamp_field = {
        "ACCEPTED": "acceptedAt",
        "SENT": "sentAt",
        "DELIVERED": "deliveredAt",
        "READ": "readAt",
        "FAILED": "failedAt",
    }[status]
    set_values: Dict[str, Any] = {"updatedAt": _now()}
    if status == "FAILED":
        set_values.update(
            {"failureCode": failure_code, "failureMessage": failure_message}
        )
    collection.update_one(
        {"providerMessageId": provider_message_id},
        {"$min": {timestamp_field: occurred_at}, "$set": set_values},
    )

    allowed_previous = {
        "ACCEPTED": [None, "ACCEPTED"],
        "SENT": [None, "ACCEPTED", "SENT"],
        "DELIVERED": [None, "ACCEPTED", "SENT", "DELIVERED"],
        "READ": [None, "ACCEPTED", "SENT", "DELIVERED", "READ"],
        "FAILED": [None, "ACCEPTED", "SENT", "FAILED"],
    }[status]
    collection.update_one(
        {
            "providerMessageId": provider_message_id,
            "status": {"$in": allowed_previous},
        },
        {"$set": {"status": status, "updatedAt": _now()}},
    )
    return collection.find_one({"providerMessageId": provider_message_id})


def insert_compatibility_event_once(event: Dict[str, Any]) -> bool:
    event_key = event.get("eventKey")
    if not event_key:
        return False
    result = get_collection("whatsapp_events").update_one(
        {"eventKey": event_key}, {"$setOnInsert": event}, upsert=True
    )
    return result.upserted_id is not None


def store_temporary_failure_details(
    provider_message_id: str,
    event_key: str,
    details: Dict[str, Any],
    expires_at: datetime,
) -> None:
    if not details:
        return
    get_collection("whatsapp_failure_details").update_one(
        {"eventKey": event_key},
        {
            "$setOnInsert": {
                "eventKey": event_key,
                "providerMessageId": provider_message_id,
                "details": details,
                "createdAt": _now(),
                "expiresAt": expires_at,
            }
        },
        upsert=True,
    )


def find_legacy_outbound(provider_message_id: str) -> Optional[Dict[str, Any]]:
    return get_collection("whatsapp_message_logs").find_one(
        {"waMessageId": provider_message_id}
    )

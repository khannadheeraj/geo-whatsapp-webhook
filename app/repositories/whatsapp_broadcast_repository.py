from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from pymongo import ReturnDocument

from app.db.mongodb import get_collection


def insert_broadcast(document: Dict[str, Any]) -> Dict[str, Any]:
    result = get_collection("whatsapp_broadcasts").insert_one(document)
    document["_id"] = result.inserted_id
    return document


def find_broadcast(broadcast_id: ObjectId) -> Optional[Dict[str, Any]]:
    return get_collection("whatsapp_broadcasts").find_one({"_id": broadcast_id})


def claim_preparation(broadcast_id: ObjectId, version: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return get_collection("whatsapp_broadcasts").find_one_and_update(
        {"_id": broadcast_id, "status": "DRAFT", "version": version},
        {"$set": updates, "$inc": {"version": 1}}, return_document=ReturnDocument.AFTER,
    )


def finish_preparation(broadcast_id: ObjectId, version: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return get_collection("whatsapp_broadcasts").find_one_and_update(
        {"_id": broadcast_id, "status": "PREPARING", "version": version},
        {"$set": updates}, return_document=ReturnDocument.AFTER,
    )


def replace_recipients(broadcast_id: ObjectId, recipients: List[Dict[str, Any]]) -> None:
    collection = get_collection("whatsapp_broadcast_recipients")
    collection.delete_many({"broadcastId": broadcast_id, "status": {"$in": ["ELIGIBLE", "SKIPPED", "REJECTED"]}})
    if recipients:
        collection.insert_many(recipients, ordered=True)


def list_recipients(query: Dict[str, Any], *, page: int, page_size: int) -> Tuple[List[Dict[str, Any]], int]:
    collection = get_collection("whatsapp_broadcast_recipients")
    total = collection.count_documents(query)
    documents = list(collection.find(query).sort([("status", 1), ("displayName", 1), ("_id", 1)]).skip((page - 1) * page_size).limit(page_size))
    return documents, total


def delete_draft(broadcast_id: ObjectId, version: int) -> bool:
    result = get_collection("whatsapp_broadcasts").delete_one({"_id": broadcast_id, "status": "DRAFT", "version": version})
    if result.deleted_count:
        get_collection("whatsapp_broadcast_recipients").delete_many({"broadcastId": broadcast_id})
        return True
    return False

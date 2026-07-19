from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId

from app.db.mongodb import get_collection


def upsert_template(identity: Dict[str, Any], document: Dict[str, Any]) -> bool:
    result = get_collection("whatsapp_templates").update_one(
        identity,
        {"$set": document, "$setOnInsert": {"createdAt": document["updatedAt"]}},
        upsert=True,
    )
    return result.upserted_id is not None


def deactivate_templates_missing_from_sync(
    business_account_id: str, sync_id: str, updates: Dict[str, Any]
) -> int:
    result = get_collection("whatsapp_templates").update_many(
        {
            "businessAccountId": business_account_id,
            "lastSeenSyncId": {"$ne": sync_id},
            "isActive": True,
        },
        {"$set": updates},
    )
    return result.modified_count


def list_approved_active_templates(
    query: Dict[str, Any], *, page: int, page_size: int
) -> Tuple[List[Dict[str, Any]], int]:
    collection = get_collection("whatsapp_templates")
    total = collection.count_documents(query)
    documents = list(
        collection.find(query)
        .sort([("category", 1), ("name", 1), ("language", 1), ("_id", 1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return documents, total


def find_approved_active_template(
    template_id: str, business_account_id: str
) -> Optional[Dict[str, Any]]:
    try:
        object_id = ObjectId(template_id)
    except Exception:
        return None
    return get_collection("whatsapp_templates").find_one(
        {
            "_id": object_id,
            "businessAccountId": business_account_id,
            "status": "APPROVED",
            "isActive": True,
        }
    )

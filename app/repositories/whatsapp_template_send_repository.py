from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from pymongo.errors import DuplicateKeyError

from app.db.mongodb import get_collection


def claim_send_operation(document: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    collection = get_collection("whatsapp_template_send_operations")
    try:
        result = collection.insert_one(document)
        document["_id"] = result.inserted_id
        return document, True
    except DuplicateKeyError:
        existing = collection.find_one(
            {"actorUserId": document["actorUserId"], "idempotencyKey": document["idempotencyKey"]}
        )
        return existing, False


def complete_send_operation(
    operation_id: Any, updates: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    collection = get_collection("whatsapp_template_send_operations")
    collection.update_one({"_id": operation_id}, {"$set": updates})
    return collection.find_one({"_id": operation_id})

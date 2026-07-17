from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId

from app.db.mongodb import get_collection


def append_activity(document: Dict[str, Any]) -> Dict[str, Any]:
    collection = get_collection("lead_activities")
    operation_id = document.get("operationId")
    if operation_id:
        collection.update_one(
            {"operationId": operation_id, "type": document["type"]},
            {"$setOnInsert": document},
            upsert=True,
        )
        return collection.find_one(
            {"operationId": operation_id, "type": document["type"]}
        )
    result = collection.insert_one(document)
    document["_id"] = result.inserted_id
    return document


def list_lead_activities(
    lead_id: ObjectId,
    *,
    page: int,
    page_size: int,
    activity_type: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    query: Dict[str, Any] = {"leadId": lead_id}
    if activity_type:
        query["type"] = activity_type
    collection = get_collection("lead_activities")
    total = collection.count_documents(query)
    documents = list(
        collection.find(query)
        .sort([("createdAt", -1), ("_id", -1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return documents, total

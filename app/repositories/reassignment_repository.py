from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.db.mongodb import get_collection
from app.errors import ConflictError


def insert_reassignment_request(document: Dict[str, Any]) -> Dict[str, Any]:
    try:
        result = get_collection("reassignment_requests").insert_one(document)
    except DuplicateKeyError as exc:
        raise ConflictError(
            "REASSIGNMENT_PENDING_DUPLICATE",
            "This lead already has a pending reassignment request.",
        ) from exc
    document["_id"] = result.inserted_id
    return document


def find_reassignment_request(request_id: ObjectId) -> Optional[Dict[str, Any]]:
    return get_collection("reassignment_requests").find_one({"_id": request_id})


def decide_reassignment_request(
    request_id: ObjectId,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    return get_collection("reassignment_requests").find_one_and_update(
        {
            "_id": request_id,
            "status": "PENDING",
            "decisionOperationId": {"$exists": False},
        },
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )


def claim_reassignment_approval(
    request_id: ObjectId,
    operation_id: str,
    updated_at: Any,
) -> Optional[Dict[str, Any]]:
    return get_collection("reassignment_requests").find_one_and_update(
        {
            "_id": request_id,
            "status": "PENDING",
            "$or": [
                {"decisionOperationId": {"$exists": False}},
                {"decisionOperationId": operation_id},
            ],
        },
        {"$set": {"decisionOperationId": operation_id, "updatedAt": updated_at}},
        return_document=ReturnDocument.AFTER,
    )


def release_reassignment_approval_claim(request_id: ObjectId, operation_id: str) -> None:
    get_collection("reassignment_requests").update_one(
        {"_id": request_id, "status": "PENDING", "decisionOperationId": operation_id},
        {"$unset": {"decisionOperationId": ""}},
    )


def finalize_reassignment_approval(
    request_id: ObjectId,
    operation_id: str,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    return get_collection("reassignment_requests").find_one_and_update(
        {"_id": request_id, "status": "PENDING", "decisionOperationId": operation_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )


def list_reassignment_requests(
    query: Dict[str, Any],
    *,
    page: int,
    page_size: int,
) -> Tuple[List[Dict[str, Any]], int]:
    collection = get_collection("reassignment_requests")
    total = collection.count_documents(query)
    documents = list(
        collection.find(query)
        .sort([("createdAt", -1), ("_id", -1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return documents, total

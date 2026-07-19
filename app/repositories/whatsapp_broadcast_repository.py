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


def confirm_broadcast(broadcast_id: ObjectId, version: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return get_collection("whatsapp_broadcasts").find_one_and_update(
        {"_id": broadcast_id, "status": "DRAFT", "version": version, "preparedAt": {"$exists": True}},
        {"$set": updates, "$inc": {"version": 1}}, return_document=ReturnDocument.AFTER,
    )


def freeze_eligible_recipients(broadcast_id: ObjectId, now: Any) -> int:
    result = get_collection("whatsapp_broadcast_recipients").update_many(
        {"broadcastId": broadcast_id, "status": "ELIGIBLE"},
        {"$set": {"status": "PENDING", "executionStatus": "PENDING", "confirmedAt": now, "attemptCount": 0, "updatedAt": now}},
    )
    return result.modified_count


def claim_next_recipient(broadcast_id: ObjectId, worker_id: str, now: Any, lease_until: Any) -> Optional[Dict[str, Any]]:
    return get_collection("whatsapp_broadcast_recipients").find_one_and_update(
        {"broadcastId": broadcast_id, "status": "PENDING"},
        {"$set": {"status": "PROCESSING", "executionStatus": "PROCESSING", "workerId": worker_id, "leaseExpiresAt": lease_until, "processingStartedAt": now, "updatedAt": now}, "$inc": {"attemptCount": 1}},
        sort=[("_id", 1)], return_document=ReturnDocument.AFTER,
    )


def mark_provider_call_started(recipient_id: ObjectId, worker_id: str, now: Any) -> bool:
    return get_collection("whatsapp_broadcast_recipients").update_one(
        {"_id": recipient_id, "status": "PROCESSING", "workerId": worker_id},
        {"$set": {"providerCallStartedAt": now, "updatedAt": now}},
    ).modified_count == 1


def finish_recipient(recipient_id: ObjectId, worker_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    clean = {**updates, "executionStatus": updates["status"]}
    return get_collection("whatsapp_broadcast_recipients").find_one_and_update(
        {"_id": recipient_id, "status": "PROCESSING", "workerId": worker_id},
        {"$set": clean, "$unset": {"workerId": "", "leaseExpiresAt": ""}}, return_document=ReturnDocument.AFTER,
    )


def recover_expired_leases(broadcast_id: ObjectId, now: Any) -> Dict[str, int]:
    collection = get_collection("whatsapp_broadcast_recipients")
    uncertain = collection.update_many(
        {"broadcastId": broadcast_id, "status": "PROCESSING", "leaseExpiresAt": {"$lte": now}, "providerCallStartedAt": {"$exists": True}},
        {"$set": {"status": "FAILED_FINAL", "executionStatus": "FAILED_FINAL", "failureCode": "PROVIDER_RESULT_UNCERTAIN", "updatedAt": now}, "$unset": {"workerId": "", "leaseExpiresAt": ""}},
    ).modified_count
    safe = collection.update_many(
        {"broadcastId": broadcast_id, "status": "PROCESSING", "leaseExpiresAt": {"$lte": now}, "providerCallStartedAt": {"$exists": False}},
        {"$set": {"status": "PENDING", "executionStatus": "PENDING", "updatedAt": now}, "$unset": {"workerId": "", "leaseExpiresAt": ""}},
    ).modified_count
    return {"requeued": safe, "uncertainFinal": uncertain}


def approve_retryable_failures(broadcast_id: ObjectId, now: Any) -> int:
    return get_collection("whatsapp_broadcast_recipients").update_many(
        {"broadcastId": broadcast_id, "status": "FAILED_RETRYABLE", "retryEligibleAt": {"$lte": now}},
        {"$set": {"status": "PENDING", "executionStatus": "PENDING", "updatedAt": now}, "$unset": {"failureCode": "", "failureStatusCode": "", "providerCallStartedAt": "", "retryEligibleAt": ""}},
    ).modified_count


def cancel_unsent(broadcast_id: ObjectId, now: Any) -> int:
    return get_collection("whatsapp_broadcast_recipients").update_many(
        {"broadcastId": broadcast_id, "status": {"$in": ["PENDING", "FAILED_RETRYABLE"]}},
        {"$set": {"status": "SKIPPED", "executionStatus": "SKIPPED", "exclusionReason": "BROADCAST_CANCELLED", "updatedAt": now}},
    ).modified_count


def update_broadcast(broadcast_id: ObjectId, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return get_collection("whatsapp_broadcasts").find_one_and_update({"_id": broadcast_id}, {"$set": updates}, return_document=ReturnDocument.AFTER)


def update_active_broadcast(broadcast_id: ObjectId, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return get_collection("whatsapp_broadcasts").find_one_and_update({"_id": broadcast_id, "status": {"$ne": "CANCELLED"}}, {"$set": updates}, return_document=ReturnDocument.AFTER)


def transition_broadcast(broadcast_id: ObjectId, version: int, statuses: List[str], updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return get_collection("whatsapp_broadcasts").find_one_and_update(
        {"_id": broadcast_id, "version": version, "status": {"$in": statuses}},
        {"$set": updates, "$inc": {"version": 1}}, return_document=ReturnDocument.AFTER,
    )


def execution_counts(broadcast_id: ObjectId) -> Dict[str, int]:
    counts = {item["_id"]: item["count"] for item in get_collection("whatsapp_broadcast_recipients").aggregate([{"$match": {"broadcastId": broadcast_id}}, {"$group": {"_id": "$status", "count": {"$sum": 1}}}])}
    return {
        "processed": counts.get("ACCEPTED", 0) + counts.get("FAILED_RETRYABLE", 0) + counts.get("FAILED_FINAL", 0),
        "accepted": counts.get("ACCEPTED", 0), "retryableFailure": counts.get("FAILED_RETRYABLE", 0),
        "finalFailure": counts.get("FAILED_FINAL", 0), "remaining": counts.get("PENDING", 0) + counts.get("PROCESSING", 0),
        "skipped": counts.get("SKIPPED", 0), "processing": counts.get("PROCESSING", 0),
    }


def correlate_delivery_status(provider_message_id: str, status: str, occurred_at: Any, failure_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
    allowed = {
        "ACCEPTED": [None],
        "SENT": [None, "ACCEPTED"],
        "DELIVERED": [None, "ACCEPTED", "SENT"],
        "READ": [None, "ACCEPTED", "SENT", "DELIVERED"],
        "FAILED": [None, "ACCEPTED"],
    }[status]
    field = {"ACCEPTED": "deliveryAcceptedAt", "SENT": "deliverySentAt", "DELIVERED": "deliveryDeliveredAt", "READ": "deliveryReadAt", "FAILED": "deliveryFailedAt"}[status]
    updates: Dict[str, Any] = {"deliveryStatus": status, field: occurred_at, "updatedAt": occurred_at}
    if status == "FAILED": updates["deliveryFailureCode"] = (str(failure_code or "WHATSAPP_DELIVERY_FAILED")[:100])
    timeline = {"status": status, "at": occurred_at}
    if status == "FAILED": timeline["failureCode"] = updates["deliveryFailureCode"]
    return get_collection("whatsapp_broadcast_recipients").find_one_and_update(
        {"providerMessageId": provider_message_id, "deliveryStatus": {"$in": allowed}},
        {"$set": updates, "$push": {"deliveryTimeline": {"$each": [timeline], "$slice": -10}}},
        return_document=ReturnDocument.AFTER,
    )


def analytics_counts(broadcast_id: ObjectId) -> Dict[str, int]:
    rows = list(get_collection("whatsapp_broadcast_recipients").find({"broadcastId": broadcast_id}, {"status": 1, "executionStatus": 1, "deliveryStatus": 1, "exclusionReason": 1}))
    execution = lambda row: row.get("executionStatus") or row.get("status")
    count = lambda predicate: sum(1 for row in rows if predicate(row))
    return {
        "totalPrepared": len(rows),
        "eligible": count(lambda row: not (execution(row) == "REJECTED" or (execution(row) == "SKIPPED" and row.get("exclusionReason") != "BROADCAST_CANCELLED"))),
        "skipped": count(lambda row: execution(row) == "SKIPPED" and row.get("exclusionReason") != "BROADCAST_CANCELLED"),
        "rejected": count(lambda row: execution(row) == "REJECTED"),
        "pending": count(lambda row: execution(row) == "PENDING"), "processing": count(lambda row: execution(row) == "PROCESSING"),
        "accepted": count(lambda row: row.get("deliveryStatus") == "ACCEPTED" or (execution(row) == "ACCEPTED" and not row.get("deliveryStatus"))),
        "sent": count(lambda row: row.get("deliveryStatus") == "SENT"), "delivered": count(lambda row: row.get("deliveryStatus") == "DELIVERED"),
        "read": count(lambda row: row.get("deliveryStatus") == "READ"), "failedRetryable": count(lambda row: execution(row) == "FAILED_RETRYABLE"),
        "failedFinal": count(lambda row: execution(row) == "FAILED_FINAL"), "cancelled": count(lambda row: execution(row) == "SKIPPED" and row.get("exclusionReason") == "BROADCAST_CANCELLED"),
    }


def list_report(query: Dict[str, Any], *, page: int, page_size: int) -> Tuple[List[Dict[str, Any]], int]:
    collection = get_collection("whatsapp_broadcast_recipients")
    total = collection.count_documents(query)
    return list(collection.find(query).sort([("displayName", 1), ("_id", 1)]).skip((page - 1) * page_size).limit(page_size)), total


def find_recipient(broadcast_id: ObjectId, recipient_id: ObjectId) -> Optional[Dict[str, Any]]:
    return get_collection("whatsapp_broadcast_recipients").find_one({"_id": recipient_id, "broadcastId": broadcast_id})

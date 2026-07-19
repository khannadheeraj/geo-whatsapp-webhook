from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.errors import NotFoundError
from app.repositories import whatsapp_broadcast_repository as repository
from app.utils.mongo_utils import object_id_or_not_found


def _now(): return datetime.now(timezone.utc)


def correlate_delivery_status(provider_message_id: str, status: str, occurred_at: datetime, failure_code: Optional[str] = None) -> bool:
    recipient = repository.correlate_delivery_status(provider_message_id, status, occurred_at, failure_code)
    if not recipient: return False
    return True


def _broadcast(value: str) -> Dict[str, Any]:
    document = repository.find_broadcast(object_id_or_not_found(value, "broadcast"))
    if not document: raise NotFoundError("WHATSAPP_BROADCAST_NOT_FOUND", "The requested broadcast was not found.")
    return document


def analytics(value: str) -> Dict[str, Any]:
    broadcast = _broadcast(value); totals = repository.analytics_counts(broadcast["_id"])
    return {"broadcastId": str(broadcast["_id"]), "status": broadcast.get("status"), "totals": totals, "updatedAt": _now()}


def _safe_recipient(document: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(document["_id"]), "contactId": str(document["contactId"]) if document.get("contactId") else None,
        "leadId": str(document["leadId"]) if document.get("leadId") else None, "displayName": document.get("displayName"),
        "phone": document.get("normalizedPhone"), "renderedText": document.get("renderedText"),
        "executionStatus": document.get("executionStatus") or document.get("status"), "deliveryStatus": document.get("deliveryStatus") or ("ACCEPTED" if (document.get("executionStatus") or document.get("status")) == "ACCEPTED" else None),
        "acceptedAt": document.get("deliveryAcceptedAt") or document.get("acceptedAt"), "sentAt": document.get("deliverySentAt"), "deliveredAt": document.get("deliveryDeliveredAt"), "readAt": document.get("deliveryReadAt"), "failedAt": document.get("deliveryFailedAt"),
        "failureCode": document.get("deliveryFailureCode") or document.get("failureCode"),
        "timeline": document.get("deliveryTimeline") or [],
    }


def report(value: str, execution_status: Optional[str], delivery_status: Optional[str], page: int, page_size: int) -> Tuple[List[Dict[str, Any]], int]:
    broadcast = _broadcast(value); query: Dict[str, Any] = {"broadcastId": broadcast["_id"]}
    filters: List[Dict[str, Any]] = []
    if execution_status:
        filters.append({"$or": [{"executionStatus": execution_status}, {"executionStatus": {"$exists": False}, "status": execution_status}]})
    if delivery_status:
        delivery_filter: Dict[str, Any] = {"deliveryStatus": delivery_status}
        if delivery_status == "ACCEPTED":
            delivery_filter = {"$or": [delivery_filter, {"deliveryStatus": {"$exists": False}, "status": "ACCEPTED", "executionStatus": "ACCEPTED"}]}
        filters.append(delivery_filter)
    if filters:
        query["$and"] = filters
    documents, total = repository.list_report(query, page=page, page_size=page_size)
    return [_safe_recipient(document) for document in documents], total


def recipient_detail(value: str, recipient_value: str) -> Dict[str, Any]:
    broadcast = _broadcast(value); recipient = repository.find_recipient(broadcast["_id"], object_id_or_not_found(recipient_value, "broadcast recipient"))
    if not recipient: raise NotFoundError("WHATSAPP_BROADCAST_RECIPIENT_NOT_FOUND", "The requested broadcast recipient was not found.")
    return _safe_recipient(recipient)

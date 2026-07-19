import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.errors import ValidationApiError
from app.repositories import whatsapp_broadcast_repository as repository
from app.db.mongodb import get_collection


def _creator_summary(user: Optional[Dict[str, Any]], user_id: Any) -> Dict[str, Optional[str]]:
    return {
        "id": str(user_id) if user_id else None,
        "displayName": user.get("displayName") if user else None,
        "email": user.get("email") or user.get("emailNormalized") if user else None,
    }


def _summary(broadcast: Dict[str, Any], creators: Dict[Any, Dict[str, Any]]) -> Dict[str, Any]:
    analytics = repository.analytics_counts(broadcast["_id"])
    execution = repository.execution_counts(broadcast["_id"])
    return {
        "id": str(broadcast["_id"]),
        "template": {
            "name": broadcast.get("templateName"),
            "language": broadcast.get("templateLanguage"),
            "category": broadcast.get("templateCategory"),
        },
        "state": broadcast.get("status"),
        "schedulerState": broadcast.get("schedulerState") or "UNSCHEDULED",
        "scheduledFor": broadcast.get("scheduledFor"),
        "createdAt": broadcast.get("createdAt"),
        "createdBy": _creator_summary(creators.get(broadcast.get("createdBy")), broadcast.get("createdBy")),
        "preparationTotals": {
            "prepared": analytics["totalPrepared"], "eligible": analytics["eligible"],
            "skipped": analytics["skipped"], "rejected": analytics["rejected"],
        },
        "executionTotals": {
            "pending": max(0, execution["remaining"] - execution["processing"]),
            "accepted": execution["accepted"],
            "failed": execution["retryableFailure"] + execution["finalFailure"],
            "remaining": execution["remaining"],
        },
        "deliveryTotals": {"delivered": analytics["delivered"], "read": analytics["read"]},
    }


def list_history(
    *, state: Optional[str], scheduler_state: Optional[str], template_name: Optional[str],
    created_from: Optional[datetime], created_to: Optional[datetime], page: int, page_size: int,
) -> Tuple[List[Dict[str, Any]], int]:
    if created_from and created_to and created_from > created_to:
        raise ValidationApiError("WHATSAPP_BROADCAST_DATE_RANGE_INVALID", "createdFrom must be before or equal to createdTo.")
    query: Dict[str, Any] = {}
    if state:
        query["status"] = state
    if scheduler_state:
        query["schedulerState"] = scheduler_state
    if template_name and template_name.strip():
        query["templateName"] = {"$regex": re.escape(template_name.strip()), "$options": "i"}
    if created_from or created_to:
        query["createdAt"] = {**({"$gte": created_from} if created_from else {}), **({"$lte": created_to} if created_to else {})}
    broadcasts, total = repository.list_broadcasts(query, page=page, page_size=page_size)
    creator_ids = [item.get("createdBy") for item in broadcasts if item.get("createdBy")]
    creators = {item["_id"]: item for item in get_collection("users").find({"_id": {"$in": creator_ids}}, {"displayName": 1, "email": 1, "emailNormalized": 1})} if creator_ids else {}
    return [_summary(broadcast, creators) for broadcast in broadcasts], total

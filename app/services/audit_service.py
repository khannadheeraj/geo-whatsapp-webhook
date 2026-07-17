import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.db.mongodb import get_collection


logger = logging.getLogger("geo-ias-auth")


def write_audit_event(
    action: str,
    outcome: str,
    *,
    actor_user_id: Optional[Any] = None,
    entity_type: str = "SECURITY",
    entity_id: Optional[Any] = None,
    request_id: Optional[str] = None,
    compact_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    document = {
        "actorUserId": actor_user_id,
        "action": action,
        "entityType": entity_type,
        "entityId": str(entity_id) if entity_id is not None else None,
        "occurredAt": datetime.now(timezone.utc),
        "requestId": request_id,
        "outcome": outcome,
        "compactMetadata": compact_metadata or {},
    }
    try:
        get_collection("audit_logs").insert_one(document)
    except Exception:
        logger.error("Security audit write failed for action=%s outcome=%s", action, outcome)

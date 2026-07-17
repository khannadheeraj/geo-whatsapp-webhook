from typing import Any, Dict, Optional

from app.models.crm_model import ActorType
from app.repositories.activity_repository import append_activity
from app.utils.mongo_utils import serialize_value
from app.utils.time_utils import utc_now


def record_activity(
    activity_type: str,
    summary: str,
    *,
    contact_id: Optional[Any] = None,
    lead_id: Optional[Any] = None,
    actor_user_id: Optional[Any] = None,
    actor_type: str = ActorType.USER.value,
    metadata: Optional[Dict[str, Any]] = None,
    related_entity_type: Optional[str] = None,
    related_entity_id: Optional[Any] = None,
    operation_id: Optional[str] = None,
) -> Dict[str, Any]:
    document: Dict[str, Any] = {
        "type": activity_type,
        "actorType": actor_type,
        "actorUserId": actor_user_id,
        "summary": summary[:500],
        "metadata": serialize_value(metadata or {}),
        "createdAt": utc_now(),
    }
    if contact_id is not None:
        document["contactId"] = contact_id
    if lead_id is not None:
        document["leadId"] = lead_id
    if related_entity_type:
        document["relatedEntityType"] = related_entity_type
    if related_entity_id is not None:
        document["relatedEntityId"] = related_entity_id
    if operation_id:
        document["operationId"] = operation_id
    return append_activity(document)

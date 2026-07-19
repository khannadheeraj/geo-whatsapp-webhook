from datetime import datetime, timezone
from typing import Any, Dict

from bson import ObjectId

from app.errors import NotFoundError


def object_id_or_not_found(value: Any, entity: str) -> ObjectId:
    try:
        return value if isinstance(value, ObjectId) else ObjectId(str(value))
    except Exception as exc:
        raise NotFoundError(
            f"{entity.upper()}_NOT_FOUND",
            f"The requested {entity.lower()} was not found.",
        ) from exc


def serialize_value(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        # Legacy PyMongo values may be naive but represent UTC; state that UTC
        # explicitly in every API response.
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat()
    if isinstance(value, dict):
        return {key: serialize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    return value


def public_document(document: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if document is None:
        return None
    result = {
        key: serialize_value(value)
        for key, value in document.items()
        if key not in {"_id", "operationId", "decisionOperationId"}
        and not key.startswith("lastAssignment")
    }
    result["id"] = str(document["_id"])
    return result

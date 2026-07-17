from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bson import ObjectId

from app.db.mongodb import get_collection


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def insert_session(document: Dict[str, Any]) -> Dict[str, Any]:
    session_document = {**document}
    session_document.setdefault("_id", ObjectId())
    get_collection("user_sessions").insert_one(session_document)
    return session_document


def find_session_by_token_hash(token_hash: str) -> Optional[Dict[str, Any]]:
    return get_collection("user_sessions").find_one({"tokenHash": token_hash})


def find_session_by_id(session_id: Any) -> Optional[Dict[str, Any]]:
    try:
        object_id = session_id if isinstance(session_id, ObjectId) else ObjectId(str(session_id))
    except Exception:
        return None
    return get_collection("user_sessions").find_one({"_id": object_id})


def mark_session_rotated(session: Dict[str, Any], new_session_id: ObjectId) -> bool:
    result = get_collection("user_sessions").update_one(
        {
            "_id": session["_id"],
            "tokenHash": session["tokenHash"],
            "revokedAt": None,
        },
        {
            "$set": {
                "revokedAt": utc_now(),
                "revokeReason": "ROTATED",
                "replacedBySessionId": new_session_id,
                "lastUsedAt": utc_now(),
            }
        },
    )
    return result.modified_count == 1


def revoke_session_by_hash(token_hash: str, reason: str) -> Optional[Dict[str, Any]]:
    session = find_session_by_token_hash(token_hash)
    if not session:
        return None
    get_collection("user_sessions").update_one(
        {"_id": session["_id"], "revokedAt": None},
        {"$set": {"revokedAt": utc_now(), "revokeReason": reason}},
    )
    return session


def revoke_session_family(session_family_id: str, reason: str) -> int:
    result = get_collection("user_sessions").update_many(
        {"sessionFamilyId": session_family_id, "revokedAt": None},
        {"$set": {"revokedAt": utc_now(), "revokeReason": reason}},
    )
    return result.modified_count


def revoke_user_sessions(user_id: Any, reason: str) -> int:
    object_id = user_id if isinstance(user_id, ObjectId) else ObjectId(str(user_id))
    result = get_collection("user_sessions").update_many(
        {"userId": object_id, "revokedAt": None},
        {"$set": {"revokedAt": utc_now(), "revokeReason": reason}},
    )
    return result.modified_count

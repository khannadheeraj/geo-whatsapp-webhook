import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.db.mongodb import get_collection
from app.errors import ConflictError, ValidationApiError
from app.models.user_model import STAFF_USER_ENTITY_TYPE


_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    normalized = (email or "").strip().lower()
    if len(normalized) > 254 or not _EMAIL_PATTERN.match(normalized):
        raise ValidationApiError(
            "EMAIL_INVALID",
            "Enter a valid email address.",
            {"emailId": "Enter a valid email address."},
        )
    return normalized


def find_staff_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    return get_collection("users").find_one(
        {"entityType": STAFF_USER_ENTITY_TYPE, "emailNormalized": normalize_email(email)}
    )


def find_staff_user_by_id(user_id: Any) -> Optional[Dict[str, Any]]:
    try:
        object_id = user_id if isinstance(user_id, ObjectId) else ObjectId(str(user_id))
    except Exception:
        return None
    return get_collection("users").find_one(
        {"_id": object_id, "entityType": STAFF_USER_ENTITY_TYPE}
    )


def find_staff_users_by_ids(user_ids: List[ObjectId]) -> List[Dict[str, Any]]:
    if not user_ids:
        return []
    return list(
        get_collection("users").find(
            {"_id": {"$in": user_ids}, "entityType": STAFF_USER_ENTITY_TYPE}
        )
    )


def insert_staff_user(document: Dict[str, Any]) -> Dict[str, Any]:
    now = utc_now()
    user_document = {
        **document,
        "entityType": STAFF_USER_ENTITY_TYPE,
        "emailNormalized": normalize_email(document["email"]),
        "email": normalize_email(document["email"]),
        "isActive": bool(document.get("isActive", True)),
        "mustChangePassword": bool(document.get("mustChangePassword", True)),
        "credentialVersion": int(document.get("credentialVersion", 1)),
        "version": int(document.get("version", 1)),
        "createdAt": document.get("createdAt", now),
        "updatedAt": document.get("updatedAt", now),
    }
    try:
        result = get_collection("users").insert_one(user_document)
    except DuplicateKeyError as exc:
        raise ConflictError("USER_EMAIL_DUPLICATE", "A user with this email already exists.") from exc
    user_document["_id"] = result.inserted_id
    return user_document


def update_last_login(user_id: Any) -> None:
    get_collection("users").update_one(
        {"_id": ObjectId(str(user_id)), "entityType": STAFF_USER_ENTITY_TYPE},
        {"$set": {"lastLoginAt": utc_now(), "updatedAt": utc_now()}},
    )


def update_password(user_id: Any, password_hash: str) -> Optional[Dict[str, Any]]:
    now = utc_now()
    get_collection("users").update_one(
        {"_id": ObjectId(str(user_id)), "entityType": STAFF_USER_ENTITY_TYPE},
        {
            "$set": {
                "passwordHash": password_hash,
                "mustChangePassword": False,
                "passwordChangedAt": now,
                "updatedAt": now,
            },
            "$inc": {"credentialVersion": 1},
        },
    )
    return find_staff_user_by_id(user_id)


def replace_password_hash(user_id: Any, password_hash: str) -> None:
    get_collection("users").update_one(
        {"_id": ObjectId(str(user_id)), "entityType": STAFF_USER_ENTITY_TYPE},
        {"$set": {"passwordHash": password_hash, "updatedAt": utc_now()}},
    )


def list_staff_users(
    query: Dict[str, Any], *, page: int, page_size: int
) -> Tuple[List[Dict[str, Any]], int]:
    collection = get_collection("users")
    full_query = {"entityType": STAFF_USER_ENTITY_TYPE, **query}
    total = collection.count_documents(full_query)
    documents = list(
        collection.find(full_query)
        .sort([("displayName", 1), ("_id", 1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return documents, total


def update_staff_user(
    user_id: Any,
    version: int,
    updates: Dict[str, Any],
    *,
    increment_credentials: bool = False,
) -> Optional[Dict[str, Any]]:
    object_id = user_id if isinstance(user_id, ObjectId) else ObjectId(str(user_id))
    version_query: Dict[str, Any] = {"version": version}
    if version == 1:
        version_query = {"$or": [{"version": 1}, {"version": {"$exists": False}}]}
    update_document: Dict[str, Any] = {"$set": updates, "$inc": {"version": 1}}
    if increment_credentials:
        update_document["$inc"]["credentialVersion"] = 1
    try:
        return get_collection("users").find_one_and_update(
            {"_id": object_id, "entityType": STAFF_USER_ENTITY_TYPE, **version_query},
            update_document,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError as exc:
        raise ConflictError("USER_EMAIL_DUPLICATE", "A user with this email already exists.") from exc


def reset_staff_password(user_id: Any, password_hash: str) -> Optional[Dict[str, Any]]:
    now = utc_now()
    object_id = user_id if isinstance(user_id, ObjectId) else ObjectId(str(user_id))
    return get_collection("users").find_one_and_update(
        {"_id": object_id, "entityType": STAFF_USER_ENTITY_TYPE},
        {
            "$set": {
                "passwordHash": password_hash,
                "mustChangePassword": True,
                "passwordChangedAt": now,
                "updatedAt": now,
            },
            "$inc": {"credentialVersion": 1, "version": 1},
        },
        return_document=ReturnDocument.AFTER,
    )


def count_active_super_admins() -> int:
    return get_collection("users").count_documents(
        {
            "entityType": STAFF_USER_ENTITY_TYPE,
            "role": "SUPER_ADMIN",
            "isActive": True,
        }
    )

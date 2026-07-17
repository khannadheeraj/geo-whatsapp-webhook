from enum import Enum
from typing import Any, Dict


STAFF_USER_ENTITY_TYPE = "STAFF_USER"
LEGACY_CONTACT_ENTITY_TYPE = "LEGACY_CONTACT"


class UserRole(str, Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    COUNSELLOR = "COUNSELLOR"


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(user["_id"]),
        "displayName": user.get("displayName", ""),
        "email": user.get("email", user.get("emailNormalized", "")),
        "role": user.get("role"),
        "isActive": bool(user.get("isActive", False)),
        "mustChangePassword": bool(user.get("mustChangePassword", False)),
        "lastLoginAt": user.get("lastLoginAt"),
    }

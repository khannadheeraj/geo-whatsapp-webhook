import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.errors import AuthorizationError, ConflictError, NotFoundError, ValidationApiError
from app.models.user_model import UserRole
from app.repositories.session_repository import revoke_user_sessions
from app.repositories.user_repository import (
    count_active_super_admins,
    find_staff_user_by_id,
    insert_staff_user,
    list_staff_users as repository_list_staff_users,
    normalize_email,
    reset_staff_password as repository_reset_staff_password,
    update_staff_user,
)
from app.schemas.user_schema import StaffPasswordResetModel, StaffUserCreateModel, StaffUserPatchModel
from app.services.audit_service import write_audit_event
from app.services.password_service import hash_password
from app.utils.mongo_utils import object_id_or_not_found
from app.utils.time_utils import utc_now


def _clean_name(value: str) -> str:
    cleaned = " ".join((value or "").strip().split())
    if not 2 <= len(cleaned) <= 100:
        raise ValidationApiError(
            "USER_DISPLAY_NAME_INVALID",
            "Display name must contain between 2 and 100 characters.",
            {"displayName": "Enter a display name between 2 and 100 characters."},
        )
    return cleaned


def get_staff_user(user_id_value: Any) -> Dict[str, Any]:
    user_id = object_id_or_not_found(user_id_value, "user")
    user = find_staff_user_by_id(user_id)
    if not user:
        raise NotFoundError("USER_NOT_FOUND", "The requested staff user was not found.")
    return user


def list_staff(
    *, page: int, page_size: int, role: Optional[str], is_active: Optional[bool], search: Optional[str]
) -> Tuple[List[Dict[str, Any]], int]:
    query: Dict[str, Any] = {}
    if role:
        if role not in {item.value for item in UserRole}:
            raise ValidationApiError("USER_ROLE_INVALID", "Choose a supported staff role.")
        query["role"] = role
    if is_active is not None:
        query["isActive"] = is_active
    if search and search.strip():
        value = re.escape(" ".join(search.strip().split()))
        query["$or"] = [
            {"displayName": {"$regex": value, "$options": "i"}},
            {"emailNormalized": {"$regex": value.casefold()}},
        ]
    return repository_list_staff_users(query, page=page, page_size=page_size)


def list_active_counsellors() -> List[Dict[str, Any]]:
    users, _ = repository_list_staff_users(
        {"role": UserRole.COUNSELLOR.value, "isActive": True}, page=1, page_size=100
    )
    return users


def create_staff(
    payload: StaffUserCreateModel, actor: Dict[str, Any], request_id: Optional[str]
) -> Dict[str, Any]:
    user = insert_staff_user(
        {
            "displayName": _clean_name(payload.displayName),
            "email": normalize_email(payload.email),
            "role": payload.role.value,
            "passwordHash": hash_password(payload.temporaryPassword),
            "isActive": True,
            "mustChangePassword": True,
            "createdBy": actor["_id"],
            "updatedBy": actor["_id"],
        }
    )
    write_audit_event(
        "AUTH_USER_CREATED",
        "SUCCEEDED",
        actor_user_id=actor["_id"],
        entity_type="STAFF_USER",
        entity_id=user["_id"],
        request_id=request_id,
        compact_metadata={"role": user["role"]},
        operation_id=f"staff-create:{user['_id']}",
    )
    return user


def patch_staff(
    user_id_value: Any,
    payload: StaffUserPatchModel,
    actor: Dict[str, Any],
    request_id: Optional[str],
) -> Tuple[Dict[str, Any], bool]:
    current = get_staff_user(user_id_value)
    supplied = payload.model_dump(exclude_unset=True)
    supplied.pop("version", None)
    updates: Dict[str, Any] = {}
    changed_fields = []
    if "displayName" in supplied:
        updates["displayName"] = _clean_name(payload.displayName or "")
    if "email" in supplied:
        normalized_email = normalize_email(payload.email or "")
        updates.update({"email": normalized_email, "emailNormalized": normalized_email})
    if "isActive" in supplied:
        if payload.isActive is None:
            raise ValidationApiError("USER_ACTIVE_STATE_INVALID", "isActive must be true or false.")
        if not payload.isActive and str(current["_id"]) == str(actor["_id"]):
            raise AuthorizationError("USER_SELF_DEACTIVATION_FORBIDDEN", "You cannot deactivate your own account.")
        if (
            not payload.isActive
            and current.get("isActive")
            and current.get("role") == UserRole.SUPER_ADMIN.value
            and count_active_super_admins() <= 1
        ):
            raise ConflictError("LAST_SUPER_ADMIN_REQUIRED", "The last active Super Admin cannot be deactivated.")
        updates["isActive"] = payload.isActive
    for field, value in updates.items():
        if current.get(field) != value and field != "emailNormalized":
            changed_fields.append(
                {"field": field, "previousValue": current.get(field), "newValue": value}
            )
    if not changed_fields:
        return current, False
    updates.update({"updatedAt": utc_now(), "updatedBy": actor["_id"]})
    security_change = any(item["field"] in {"email", "isActive"} for item in changed_fields)
    updated = update_staff_user(
        current["_id"], payload.version, updates, increment_credentials=security_change
    )
    if not updated:
        raise ConflictError("USER_VERSION_CONFLICT", "The staff user changed after it was loaded. Refresh and try again.")
    if security_change:
        revoke_user_sessions(current["_id"], "STAFF_USER_SECURITY_CHANGED")
    write_audit_event(
        "AUTH_USER_UPDATED",
        "SUCCEEDED",
        actor_user_id=actor["_id"],
        entity_type="STAFF_USER",
        entity_id=current["_id"],
        request_id=request_id,
        changed_fields=changed_fields,
        operation_id=f"staff-update:{uuid.uuid4()}",
    )
    return updated, security_change and str(current["_id"]) == str(actor["_id"])


def reset_password(
    user_id_value: Any,
    payload: StaffPasswordResetModel,
    actor: Dict[str, Any],
    request_id: Optional[str],
) -> Dict[str, Any]:
    current = get_staff_user(user_id_value)
    if str(current["_id"]) == str(actor["_id"]):
        raise AuthorizationError(
            "USER_SELF_PASSWORD_RESET_FORBIDDEN",
            "Use Change Password to update your own password.",
        )
    updated = repository_reset_staff_password(
        current["_id"], hash_password(payload.temporaryPassword)
    )
    revoke_user_sessions(current["_id"], "PASSWORD_RESET_BY_ADMIN")
    write_audit_event(
        "AUTH_USER_PASSWORD_RESET",
        "SUCCEEDED",
        actor_user_id=actor["_id"],
        entity_type="STAFF_USER",
        entity_id=current["_id"],
        request_id=request_id,
        compact_metadata={"mustChangePassword": True},
        operation_id=f"staff-password-reset:{uuid.uuid4()}",
    )
    return updated

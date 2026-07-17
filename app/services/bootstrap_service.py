from typing import Any, Callable, Dict, Iterable, List

from app.errors import ConflictError, ValidationApiError
from app.models.user_model import UserRole
from app.repositories.user_repository import find_staff_user_by_email, insert_staff_user, normalize_email
from app.services.audit_service import write_audit_event
from app.services.password_service import hash_password


def validate_manifest(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    users = list(entries)
    if len(users) not in {5, 6}:
        raise ValidationApiError("BOOTSTRAP_COUNT_INVALID", "Bootstrap requires exactly 2 Super Admins and 3 or 4 Counsellors.")
    emails = [normalize_email(item.get("email", "")) for item in users]
    if len(emails) != len(set(emails)):
        raise ConflictError("BOOTSTRAP_EMAIL_DUPLICATE", "Bootstrap emails must be unique.")
    roles = [item.get("role") for item in users]
    if roles.count(UserRole.SUPER_ADMIN.value) != 2 or roles.count(UserRole.COUNSELLOR.value) not in {3, 4}:
        raise ValidationApiError("BOOTSTRAP_ROLE_COUNT_INVALID", "Bootstrap requires exactly 2 Super Admins and 3 or 4 Counsellors.")
    normalized = []
    for item, email in zip(users, emails):
        if set(item) - {"email", "displayName", "role"}:
            raise ValidationApiError("BOOTSTRAP_FIELD_INVALID", "Bootstrap manifest contains unsupported fields.")
        display_name = str(item.get("displayName", "")).strip()
        if not 2 <= len(display_name) <= 100:
            raise ValidationApiError("BOOTSTRAP_NAME_INVALID", "Every bootstrap user requires a display name between 2 and 100 characters.")
        normalized.append({"email": email, "displayName": display_name, "role": item["role"]})
    return normalized


def bootstrap_users(entries: Iterable[Dict[str, Any]], password_provider: Callable[[Dict[str, Any]], str]) -> Dict[str, int]:
    created = 0
    existing = 0
    for entry in validate_manifest(entries):
        if find_staff_user_by_email(entry["email"]):
            existing += 1
            continue
        password = password_provider(entry)
        user = insert_staff_user({**entry, "passwordHash": hash_password(password), "isActive": True, "mustChangePassword": True})
        write_audit_event("AUTH_USER_BOOTSTRAP", "CREATED", actor_user_id=user["_id"], entity_type="STAFF_USER", entity_id=user["_id"])
        created += 1
    return {"created": created, "existing": existing, "total": created + existing}

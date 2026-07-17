from typing import Any, Dict

from app.errors import AuthorizationError
from app.models.user_model import UserRole
from app.repositories.lead_repository import find_active_lead_by_contact


def is_super_admin(user: Dict[str, Any]) -> bool:
    return user.get("role") == UserRole.SUPER_ADMIN.value


def assert_lead_access(user: Dict[str, Any], lead: Dict[str, Any]) -> None:
    if not is_super_admin(user) and str(lead.get("assignedCounsellorId")) != str(user["_id"]):
        raise AuthorizationError(
            "LEAD_ACCESS_FORBIDDEN",
            "You are not permitted to access this lead.",
        )


def assert_contact_access(user: Dict[str, Any], contact: Dict[str, Any]) -> None:
    if is_super_admin(user):
        return
    lead = find_active_lead_by_contact(contact["_id"])
    if lead and str(lead.get("assignedCounsellorId")) == str(user["_id"]):
        return
    if not lead and str(contact.get("createdBy")) == str(user["_id"]):
        return
    raise AuthorizationError(
        "CONTACT_ACCESS_FORBIDDEN",
        "You are not permitted to access this contact.",
    )

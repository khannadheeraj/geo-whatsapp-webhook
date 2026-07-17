from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.errors import AuthenticationError, AuthorizationError
from app.models.user_model import UserRole
from app.repositories.session_repository import find_session_by_id
from app.repositories.user_repository import find_staff_user_by_id
from app.services.token_service import decode_access_token


bearer = HTTPBearer(auto_error=False)


async def get_current_user_raw(credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> Dict[str, Any]:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise AuthenticationError()
    claims = decode_access_token(credentials.credentials)
    user = find_staff_user_by_id(claims["sub"])
    session = find_session_by_id(claims["sid"])
    if (
        not user or not user.get("isActive") or not session or session.get("revokedAt") is not None
        or str(session.get("userId")) != str(user["_id"])
        or int(claims["ver"]) != int(user.get("credentialVersion", 1))
        or int(session.get("credentialVersion", 1)) != int(user.get("credentialVersion", 1))
        or claims.get("role") != user.get("role")
        or session.get("expiresAt") is None
        or (session["expiresAt"].replace(tzinfo=timezone.utc) if session["expiresAt"].tzinfo is None else session["expiresAt"]) <= datetime.now(timezone.utc)
    ):
        raise AuthenticationError("SESSION_INVALID", "The session is invalid or has expired.")
    return user


async def require_authenticated_user(user: Dict[str, Any] = Depends(get_current_user_raw)) -> Dict[str, Any]:
    if user.get("mustChangePassword"):
        raise AuthorizationError("PASSWORD_CHANGE_REQUIRED", "Change your temporary password before continuing.")
    return user


async def require_super_admin(user: Dict[str, Any] = Depends(require_authenticated_user)) -> Dict[str, Any]:
    if user.get("role") != UserRole.SUPER_ADMIN.value:
        raise AuthorizationError()
    return user


def assert_super_admin_or_assigned(user: Dict[str, Any], assigned_user_id: Any) -> None:
    if user.get("role") != UserRole.SUPER_ADMIN.value and str(user["_id"]) != str(assigned_user_id):
        raise AuthorizationError()

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from bson import ObjectId

from app.config import get_security_settings
from app.errors import AuthenticationError, ValidationApiError
from app.models.user_model import public_user
from app.repositories.session_repository import (
    find_session_by_token_hash,
    insert_session,
    mark_session_rotated,
    revoke_session_by_hash,
    revoke_session_family,
    revoke_user_sessions,
)
from app.repositories.user_repository import (
    find_staff_user_by_email,
    find_staff_user_by_id,
    replace_password_hash,
    update_last_login,
    update_password,
)
from app.services.audit_service import write_audit_event
from app.services.password_service import hash_password, validate_password, verify_password
from app.services.token_service import create_access_token, generate_refresh_token, hash_refresh_token
from app.utils.mongo_utils import serialize_value


_DUMMY_HASH: Optional[str] = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _response(user: Dict[str, Any], session: Dict[str, Any], refresh_token: str) -> Tuple[Dict[str, Any], str]:
    access_token, expires_at = create_access_token(user, session["_id"])
    return {
        "accessToken": access_token,
        "tokenType": "bearer",
        "expiresAt": serialize_value(expires_at),
        "user": public_user(user),
    }, refresh_token


def _new_session(user: Dict[str, Any], family_id: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    settings = get_security_settings()
    refresh_token = generate_refresh_token()
    now = utc_now()
    session = insert_session({
        "_id": ObjectId(),
        "userId": user["_id"],
        "sessionFamilyId": family_id or str(ObjectId()),
        "tokenHash": hash_refresh_token(refresh_token),
        "credentialVersion": int(user.get("credentialVersion", 1)),
        "createdAt": now,
        "lastUsedAt": now,
        "expiresAt": now + timedelta(days=settings.refresh_token_days),
        "revokedAt": None,
        "revokeReason": None,
    })
    return session, refresh_token


def login(email: str, password: str, request_id: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    global _DUMMY_HASH
    user = find_staff_user_by_email(email)
    if user:
        valid, needs_rehash = verify_password(user.get("passwordHash", ""), password)
    else:
        if _DUMMY_HASH is None:
            _DUMMY_HASH = hash_password("Dummy-Only-Auth!4827")
        verify_password(_DUMMY_HASH, password)
        valid, needs_rehash = False, False
    if not user or not valid or not user.get("isActive", False):
        write_audit_event("AUTH_LOGIN", "FAILED", request_id=request_id, compact_metadata={"reason": "INVALID_CREDENTIALS"})
        raise AuthenticationError("LOGIN_FAILED", "Invalid email or password.")
    if needs_rehash:
        replace_password_hash(user["_id"], hash_password(password))
    update_last_login(user["_id"])
    session, refresh_token = _new_session(user)
    write_audit_event("AUTH_LOGIN", "SUCCEEDED", actor_user_id=user["_id"], request_id=request_id)
    return _response(user, session, refresh_token)


def refresh(refresh_token: str, request_id: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    token_hash = hash_refresh_token(refresh_token)
    session = find_session_by_token_hash(token_hash)
    if not session:
        raise AuthenticationError("REFRESH_INVALID", "The session is invalid or has expired.")
    if session.get("revokedAt") is not None:
        revoke_session_family(session["sessionFamilyId"], "REPLAY_DETECTED")
        write_audit_event("AUTH_REFRESH_REPLAY", "REJECTED", actor_user_id=session.get("userId"), request_id=request_id)
        raise AuthenticationError("REFRESH_REPLAYED", "The session is invalid or has expired.")
    if _aware(session["expiresAt"]) <= utc_now():
        revoke_session_by_hash(token_hash, "EXPIRED")
        raise AuthenticationError("REFRESH_EXPIRED", "The session is invalid or has expired.")
    user = find_staff_user_by_id(session["userId"])
    if not user or not user.get("isActive") or int(user.get("credentialVersion", 1)) != int(session.get("credentialVersion", 1)):
        revoke_session_family(session["sessionFamilyId"], "USER_INVALIDATED")
        raise AuthenticationError("REFRESH_INVALID", "The session is invalid or has expired.")
    new_session, new_token = _new_session(user, session["sessionFamilyId"])
    if not mark_session_rotated(session, new_session["_id"]):
        revoke_session_family(session["sessionFamilyId"], "REPLAY_DETECTED")
        raise AuthenticationError("REFRESH_REPLAYED", "The session is invalid or has expired.")
    write_audit_event("AUTH_REFRESH", "SUCCEEDED", actor_user_id=user["_id"], request_id=request_id)
    return _response(user, new_session, new_token)


def logout(refresh_token: Optional[str], request_id: Optional[str] = None) -> None:
    session = revoke_session_by_hash(hash_refresh_token(refresh_token), "LOGOUT") if refresh_token else None
    write_audit_event("AUTH_LOGOUT", "SUCCEEDED", actor_user_id=session.get("userId") if session else None, request_id=request_id)


def change_password(user: Dict[str, Any], current_password: str, new_password: str, request_id: Optional[str] = None) -> None:
    valid, _ = verify_password(user.get("passwordHash", ""), current_password)
    if not valid:
        raise AuthenticationError("CURRENT_PASSWORD_INVALID", "The current password is incorrect.")
    if current_password == new_password:
        raise ValidationApiError("PASSWORD_UNCHANGED", "The new password must be different.", {"newPassword": "Choose a different password."})
    validate_password(new_password)
    update_password(user["_id"], hash_password(new_password))
    revoke_user_sessions(user["_id"], "PASSWORD_CHANGED")
    write_audit_event("AUTH_PASSWORD_CHANGE", "SUCCEEDED", actor_user_id=user["_id"], request_id=request_id)

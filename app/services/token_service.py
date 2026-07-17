import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Tuple

import jwt
from jwt import InvalidTokenError

from app.config import get_security_settings
from app.errors import AuthenticationError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(user: Dict[str, Any], session_id: Any) -> Tuple[str, datetime]:
    settings = get_security_settings()
    now = utc_now()
    expires_at = now + timedelta(minutes=settings.access_token_minutes)
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(user["_id"]),
        "role": user["role"],
        "sid": str(session_id),
        "ver": int(user.get("credentialVersion", 1)),
        "jti": secrets.token_urlsafe(18),
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm), expires_at


def decode_access_token(token: str) -> Dict[str, Any]:
    settings = get_security_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["iss", "aud", "sub", "role", "sid", "ver", "jti", "iat", "exp"]},
        )
    except InvalidTokenError as exc:
        raise AuthenticationError("TOKEN_INVALID", "The session is invalid or has expired.") from exc

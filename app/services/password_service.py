import re
from typing import Tuple

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
try:
    from argon2.exceptions import InvalidHashError
except ImportError:  # argon2-cffi < 23 uses the earlier class name
    from argon2.exceptions import InvalidHash as InvalidHashError

from app.config import get_security_settings
from app.errors import ValidationApiError


_PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
_PROHIBITED_PASSWORDS = {
    "admin@123",
    "password",
    "password123",
    "changeme",
    "change-me",
    "geoias",
}


def validate_password(password: str) -> None:
    settings = get_security_settings()
    field_errors = {}
    if len(password) < settings.password_min_length:
        field_errors["newPassword"] = (
            f"Password must contain at least {settings.password_min_length} characters."
        )
    elif len(password) > 128:
        field_errors["newPassword"] = "Password must not exceed 128 characters."
    elif password.lower() in _PROHIBITED_PASSWORDS:
        field_errors["newPassword"] = "Choose a password that is not a common or default password."
    elif not re.search(r"[a-z]", password):
        field_errors["newPassword"] = "Password must contain a lowercase letter."
    elif not re.search(r"[A-Z]", password):
        field_errors["newPassword"] = "Password must contain an uppercase letter."
    elif not re.search(r"\d", password):
        field_errors["newPassword"] = "Password must contain a number."
    elif not re.search(r"[^A-Za-z0-9]", password):
        field_errors["newPassword"] = "Password must contain a special character."
    if field_errors:
        raise ValidationApiError(
            "PASSWORD_POLICY_FAILED",
            "The password does not meet the security requirements.",
            field_errors,
        )


def hash_password(password: str) -> str:
    validate_password(password)
    return _PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> Tuple[bool, bool]:
    try:
        verified = _PASSWORD_HASHER.verify(password_hash, password)
        return bool(verified), bool(verified and _PASSWORD_HASHER.check_needs_rehash(password_hash))
    except (VerifyMismatchError, VerificationError, InvalidHashError, TypeError):
        return False, False

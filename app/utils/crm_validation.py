import re
from typing import Optional

from app.errors import ValidationApiError


_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = " ".join(str(value).strip().split())
    return cleaned or None


def normalize_display_name(value: Optional[str]) -> str:
    return (clean_optional_text(value) or "").casefold()


def derive_display_name(first_name: Optional[str], last_name: Optional[str]) -> str:
    return " ".join(part for part in (clean_optional_text(first_name), clean_optional_text(last_name)) if part)


def normalize_contact_email(value: Optional[str]) -> Optional[str]:
    cleaned = clean_optional_text(value)
    if cleaned is None:
        return None
    normalized = cleaned.casefold()
    if len(normalized) > 254 or not _EMAIL_PATTERN.match(normalized):
        raise ValidationApiError(
            "CONTACT_EMAIL_INVALID",
            "Enter a valid contact email address.",
            {"email": "Enter a valid email address."},
        )
    return normalized


def normalize_code(value: Optional[str]) -> Optional[str]:
    cleaned = clean_optional_text(value)
    if cleaned is None:
        return None
    return re.sub(r"[^A-Z0-9]+", "_", cleaned.upper()).strip("_") or None

import re
from typing import Optional

from app.errors import ValidationApiError
from app.models.crm_model import LeadSource


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


_SOURCE_ALIASES = {
    "ADMIN_MANUAL_ENTRY": LeadSource.MANUAL_ENTRY.value,
    "MANUAL_ENQUIRY": LeadSource.MANUAL_ENTRY.value,
    "MANUAL": LeadSource.MANUAL_ENTRY.value,
    "EXCEL": LeadSource.EXCEL_IMPORT.value,
    "XLSX": LeadSource.EXCEL_IMPORT.value,
    "CSV": LeadSource.CSV_IMPORT.value,
    "META_LEAD_AD": LeadSource.META_LEAD_FORM.value,
    "WEBSITE_ENQUIRY": LeadSource.WEBSITE.value,
}


def normalize_lead_source(value: Optional[str], *, default: Optional[str] = None) -> Optional[str]:
    normalized = normalize_code(value) or default
    if normalized is None:
        return None
    normalized = _SOURCE_ALIASES.get(normalized, normalized)
    if normalized not in {item.value for item in LeadSource}:
        raise ValidationApiError(
            "LEAD_SOURCE_INVALID",
            "Choose a supported lead source.",
            {"source": "Choose a supported lead source."},
        )
    return normalized

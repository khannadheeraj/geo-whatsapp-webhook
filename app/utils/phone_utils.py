import re

from app.errors import ValidationApiError


def clean_phone_number(phone: str) -> str:
    if not phone:
        return ""

    digits = re.sub(r"\D", "", str(phone))

    # 09732236767 -> 9732236767
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    # 9732236767 -> 919732236767
    if len(digits) == 10:
        return "91" + digits

    # 919732236767 -> 919732236767
    if len(digits) == 12 and digits.startswith("91"):
        return digits

    return digits


def normalize_indian_phone(phone: str, field_name: str = "phone") -> str:
    raw_value = str(phone or "").strip()
    if not raw_value or raw_value.upper() in {"NA", "N/A", "NONE", "NULL"}:
        raise ValidationApiError(
            "CONTACT_PHONE_INVALID",
            "Enter a valid Indian phone number.",
            {field_name: "Enter a valid Indian phone number."},
        )
    digits = re.sub(r"\D", "", raw_value)
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 12 and digits.startswith("91"):
        national_number = digits[2:]
    elif len(digits) == 10:
        national_number = digits
    else:
        national_number = ""
    if (
        len(national_number) != 10
        or national_number[0] not in "6789"
        or len(set(national_number)) == 1
    ):
        raise ValidationApiError(
            "CONTACT_PHONE_INVALID",
            "Enter a valid Indian phone number.",
            {field_name: "Enter a valid Indian phone number."},
        )
    return f"91{national_number}"

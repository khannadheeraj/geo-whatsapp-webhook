import re


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
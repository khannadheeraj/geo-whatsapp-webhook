import re


def clean_phone_number(phone: str) -> str:
    if not phone:
        return ""

    digits = re.sub(r"\D", "", phone)

    # If number starts with 0 and has 11 digits: 09732236767
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    # If number is 10 digit Indian mobile number
    if len(digits) == 10:
        return "91" + digits

    # If number is already 12 digit Indian number
    if len(digits) == 12 and digits.startswith("91"):
        return digits

    return digits
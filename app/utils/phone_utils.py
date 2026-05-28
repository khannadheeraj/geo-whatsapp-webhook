def clean_phone_number(phone: str) -> str:
    if not phone:
        return ""

    return (
        phone.strip()
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )
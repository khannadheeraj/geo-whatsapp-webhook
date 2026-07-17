import hashlib
import hmac
import re

from app.config import WHATSAPP_APP_SECRET
from app.errors import WebhookSignatureError


_META_SIGNATURE_PATTERN = re.compile(r"^sha256=([0-9a-fA-F]{64})$")


def verify_meta_webhook_signature(raw_body: bytes, signature_header: str | None) -> None:
    match = _META_SIGNATURE_PATTERN.fullmatch(signature_header or "")
    if not WHATSAPP_APP_SECRET or not match:
        raise WebhookSignatureError()

    expected_digest = hmac.new(
        WHATSAPP_APP_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(match.group(1).lower(), expected_digest):
        raise WebhookSignatureError()

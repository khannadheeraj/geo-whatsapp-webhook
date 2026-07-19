import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, List, Optional

import requests

from app.config import (
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_GRAPH_API_VERSION,
    TEMPLATE_LANGUAGE_CODE,
)

logger = logging.getLogger("whatsapp-webhook")


def _retry_after_seconds(response) -> Optional[int]:
    raw_value = str((getattr(response, "headers", {}) or {}).get("Retry-After") or "").strip()
    if not raw_value:
        return None
    try:
        return max(0, min(int(raw_value), 86400))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw_value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0, min(int((retry_at - datetime.now(timezone.utc)).total_seconds()), 86400))
        except (TypeError, ValueError, OverflowError):
            return None


def send_whatsapp_template(
    phone: str,
    template_name: str,
    name: str = "",
    body_parameters: Optional[List[str]] = None,
    *,
    language_code: Optional[str] = None,
    template_components: Optional[List[dict[str, Any]]] = None,
):
    if not WHATSAPP_ACCESS_TOKEN:
        logger.error("WHATSAPP_ACCESS_TOKEN is not configured.")
        return {
            "success": False,
            "error": "WHATSAPP_ACCESS_TOKEN_NOT_CONFIGURED",
            "response": None
        }

    if not WHATSAPP_PHONE_NUMBER_ID:
        logger.error("WHATSAPP_PHONE_NUMBER_ID is not configured.")
        return {
            "success": False,
            "error": "WHATSAPP_PHONE_NUMBER_ID_NOT_CONFIGURED",
            "response": None
        }

    url = (
        f"https://graph.facebook.com/"
        f"{WHATSAPP_GRAPH_API_VERSION}/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": language_code or TEMPLATE_LANGUAGE_CODE
            }
        }
    }

    # Backward compatibility:
    # Old templates use only name as {{1}}
    if body_parameters is None:
        if name:
            body_parameters = [name.strip()]
        else:
            body_parameters = []

    if template_components is not None:
        payload["template"]["components"] = template_components
    elif body_parameters:
        payload["template"]["components"] = [
            {
                "type": "body",
                "parameters": [
                    {
                        "type": "text",
                        "text": str(value)
                    }
                    for value in body_parameters
                ]
            }
        ]

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=20
        )

        try:
            response_data = response.json()
        except Exception:
            response_data = {
                "rawText": response.text
            }

        if response.status_code >= 400:
            result = {
                "success": False,
                "error": "WHATSAPP_API_ERROR",
                "statusCode": response.status_code,
                "response": response_data
            }
            retry_after = _retry_after_seconds(response)
            if retry_after is not None:
                result["retryAfterSeconds"] = retry_after
            return result

        return {
            "success": True,
            "error": None,
            "statusCode": response.status_code,
            "response": response_data
        }

    except Exception as exc:
        logger.exception(
            "WhatsApp template request failed | error_type=%s",
            type(exc).__name__
        )

        return {
            "success": False,
            "error": "WHATSAPP_REQUEST_FAILED",
            "response": None
        }


def send_whatsapp_text(phone: str, text: str):
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        return {"success": False, "error": "WHATSAPP_NOT_CONFIGURED", "response": None}
    try:
        response = requests.post(f"https://graph.facebook.com/{WHATSAPP_GRAPH_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages", headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}", "Content-Type": "application/json"}, json={"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": text}}, timeout=20)
        return {"success": response.status_code < 400, "error": None if response.status_code < 400 else "WHATSAPP_API_ERROR", "response": response.json() if response.content else {}}
    except Exception:
        logger.exception("WhatsApp text request failed")
        return {"success": False, "error": "WHATSAPP_REQUEST_FAILED", "response": None}

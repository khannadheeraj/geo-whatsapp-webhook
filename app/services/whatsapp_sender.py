import logging
from typing import List, Optional

import requests

from app.config import (
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_GRAPH_API_VERSION,
    TEMPLATE_LANGUAGE_CODE,
)

logger = logging.getLogger("whatsapp-webhook")


def send_whatsapp_template(
    phone: str,
    template_name: str,
    name: str = "",
    body_parameters: Optional[List[str]] = None
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
                "code": TEMPLATE_LANGUAGE_CODE
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

    if body_parameters:
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
            return {
                "success": False,
                "error": "WHATSAPP_API_ERROR",
                "statusCode": response.status_code,
                "response": response_data
            }

        return {
            "success": True,
            "error": None,
            "statusCode": response.status_code,
            "response": response_data
        }

    except Exception as e:
        logger.exception(
            "Exception while sending WhatsApp template | phone=%s template=%s error=%s",
            phone,
            template_name,
            str(e)
        )

        return {
            "success": False,
            "error": str(e),
            "response": None
        }
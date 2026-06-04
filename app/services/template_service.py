import logging
from datetime import datetime

import requests

from app.config import (
    TEMPLATE_COUNSELLING,
    TEMPLATE_INVITE,
    TEMPLATE_INVITE_FALLBACK_UTILITY,
    TEMPLATE_UPSC_FOUNDATION_ADMISSION_OPEN,
    TEMPLATE_UPSC_FOUNDATION_ADMISSION_OPEN_END_DATE,
    UPSC_ORIENTATION_MAY31_END_DATE,
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_GRAPH_API_VERSION,
    WHATSAPP_WABA_ID,
)


logger = logging.getLogger("whatsapp-webhook")

ALLOWED_TEMPLATE_NAMES = {
    TEMPLATE_UPSC_FOUNDATION_ADMISSION_OPEN,
    TEMPLATE_INVITE_FALLBACK_UTILITY,
    TEMPLATE_INVITE,
    TEMPLATE_COUNSELLING,
}

TEMPLATE_CAMPAIGN_END_DATES = {
    TEMPLATE_UPSC_FOUNDATION_ADMISSION_OPEN: (
        TEMPLATE_UPSC_FOUNDATION_ADMISSION_OPEN_END_DATE
    ),
    TEMPLATE_INVITE_FALLBACK_UTILITY: UPSC_ORIENTATION_MAY31_END_DATE,
    TEMPLATE_INVITE: UPSC_ORIENTATION_MAY31_END_DATE,
    TEMPLATE_COUNSELLING: UPSC_ORIENTATION_MAY31_END_DATE,
}


def is_campaign_over(template_name: str):
    end_date = TEMPLATE_CAMPAIGN_END_DATES.get(template_name)

    if not end_date:
        return False

    try:
        campaign_end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        logger.warning(
            "Invalid campaign end date configured | template=%s endDate=%s",
            template_name,
            end_date
        )
        return False

    return datetime.now().date() > campaign_end_date


def get_templates():
    if not WHATSAPP_ACCESS_TOKEN:
        logger.error("WHATSAPP_ACCESS_TOKEN is not configured.")
        raise RuntimeError("WHATSAPP_ACCESS_TOKEN_NOT_CONFIGURED")

    if not WHATSAPP_WABA_ID:
        logger.error("WHATSAPP_WABA_ID is not configured.")
        raise RuntimeError("WHATSAPP_WABA_ID_NOT_CONFIGURED")

    base_url = f"https://graph.facebook.com/{WHATSAPP_GRAPH_API_VERSION}"
    url = f"{base_url}/{WHATSAPP_WABA_ID}/message_templates"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=20
    )

    try:
        data = response.json()
    except Exception:
        data = {
            "rawText": response.text
        }

    if response.status_code >= 400:
        logger.error(
            "Failed to fetch WhatsApp templates | status=%s response=%s",
            response.status_code,
            data
        )
        raise RuntimeError("WHATSAPP_TEMPLATE_FETCH_FAILED")

    templates = []

    for template in data.get("data", []):
        template_name = template.get("name")

        if template_name not in ALLOWED_TEMPLATE_NAMES:
            continue

        # if is_campaign_over(template_name):
        #     continue

        templates.append(
            {
                "name": template_name,
                "status": template.get("status"),
                "category": template.get("category"),
                "campaignEndDate": TEMPLATE_CAMPAIGN_END_DATES.get(template_name),
                "isCampaignOver": False
            }
        )

    return templates

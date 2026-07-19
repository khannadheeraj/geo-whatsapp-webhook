import logging
from datetime import datetime
from urllib.parse import urlparse
from typing import Any, Dict, List

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


class MetaTemplateFetchError(RuntimeError):
    """Provider details are intentionally kept out of API responses and storage."""

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


def fetch_meta_templates() -> List[Dict[str, Any]]:
    if not WHATSAPP_ACCESS_TOKEN:
        logger.error("WHATSAPP_ACCESS_TOKEN is not configured.")
        raise MetaTemplateFetchError("WHATSAPP_ACCESS_TOKEN_NOT_CONFIGURED")

    if not WHATSAPP_WABA_ID:
        logger.error("WHATSAPP_WABA_ID is not configured.")
        raise MetaTemplateFetchError("WHATSAPP_WABA_ID_NOT_CONFIGURED")

    base_url = f"https://graph.facebook.com/{WHATSAPP_GRAPH_API_VERSION}"
    url = f"{base_url}/{WHATSAPP_WABA_ID}/message_templates"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"
    }

    templates: List[Dict[str, Any]] = []
    params = {"fields": "id,name,language,status,category,components", "limit": 100}
    while url:
        try:
            response = requests.get(url, headers=headers, params=params, timeout=20)
        except requests.RequestException as exc:
            logger.error("WhatsApp template fetch request failed | error_type=%s", type(exc).__name__)
            raise MetaTemplateFetchError("WHATSAPP_TEMPLATE_FETCH_FAILED") from exc

        try:
            data = response.json()
        except (ValueError, TypeError) as exc:
            logger.error("WhatsApp template fetch returned invalid JSON | status=%s", response.status_code)
            raise MetaTemplateFetchError("WHATSAPP_TEMPLATE_FETCH_FAILED") from exc

        if response.status_code >= 400 or not isinstance(data, dict):
            logger.error("WhatsApp template fetch failed | status=%s", response.status_code)
            raise MetaTemplateFetchError("WHATSAPP_TEMPLATE_FETCH_FAILED")

        page_templates = data.get("data", [])
        if not isinstance(page_templates, list):
            logger.error("WhatsApp template fetch returned an invalid data shape")
            raise MetaTemplateFetchError("WHATSAPP_TEMPLATE_FETCH_FAILED")
        templates.extend(item for item in page_templates if isinstance(item, dict))

        next_url = data.get("paging", {}).get("next") if isinstance(data.get("paging"), dict) else None
        if next_url:
            parsed = urlparse(str(next_url))
            if parsed.scheme != "https" or parsed.netloc != "graph.facebook.com":
                logger.error("WhatsApp template pagination returned an unsupported host")
                raise MetaTemplateFetchError("WHATSAPP_TEMPLATE_FETCH_FAILED")
            url = str(next_url)
            params = None
        else:
            url = ""

    return templates


def get_templates():
    data = fetch_meta_templates()

    templates = []

    for template in data:
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

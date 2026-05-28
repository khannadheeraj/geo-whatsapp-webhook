import logging
from typing import Any, Dict

from app.config import (
    DEFAULT_CAMPAIGN_NAME,
    TEMPLATE_SEAT_CONFIRMED,
    TEMPLATE_COUNSELLING,
)
from app.db.mongodb import get_collection
from app.services.whatsapp_sender import send_whatsapp_template
import time

from loguru import logger




# logger = logging.getLogger("whatsapp-webhook")


def normalize_button_response(button_text: str):
    if not button_text:
        return None

    cleaned_button_text = button_text.strip().lower()

    if cleaned_button_text == "yes, i will attend":
        return {
            "normalizedResponse": "YES_ATTEND",
            "leadStatus": "SEAT_CONFIRMED",
            "nextTemplate": TEMPLATE_SEAT_CONFIRMED,
        }

    if cleaned_button_text == "talk to counselor":
        return {
            "normalizedResponse": "TALK_COUNSELOR",
            "leadStatus": "COUNSELLOR_REQUESTED",
            "nextTemplate": TEMPLATE_COUNSELLING,
        }

    return None


def process_button_click(event: Dict[str, Any]):
    phone = event.get("from")
    button_text = event.get("buttonText")

    if not phone or not button_text:
        return

    button_action = normalize_button_response(button_text)

    logger.critical(f"button_action======>{button_action}")

    if not button_action:
        
        logger.info("Unknown button clicked | phone=%s button=%s", phone,button_text )
        
        return

    campaign_recipients = get_collection("campaign_recipients")

    recipient = campaign_recipients.find_one(
        {
            "phone": phone,
            "campaignName": DEFAULT_CAMPAIGN_NAME,
        }
    )

    logger.critical(f"recipient_data======>{recipient}")

    if not recipient:
        logger.warning(
            "No campaign recipient found for phone=%s campaign=%s",
            phone,
            DEFAULT_CAMPAIGN_NAME
        )
        return

    # First click wins.
    # If responseLocked is already true, do not send another template.
    if recipient.get("responseLocked") is True:
        logger.info(
            "Response already locked. Ignoring button click | phone=%s button=%s existingResponse=%s",
            phone,
            button_text,
            recipient.get("normalizedResponse")
        )

        ignored_clicks = get_collection("ignored_button_clicks")

        ignored_clicks.insert_one(
            {
                "phone": phone,
                "campaignName": DEFAULT_CAMPAIGN_NAME,
                "buttonText": button_text,
                "buttonPayload": event.get("buttonPayload"),
                "reason": "response_already_locked",
                "existingResponse": recipient.get("normalizedResponse"),
                "rawEvent": event,
                "createTime":  int(time.time() * 1000),
                "updateTime":  int(time.time() * 1000),
            }
        )

        return

    # Atomic update protects against duplicate webhook race condition.
    update_result = campaign_recipients.update_one(
        {
            "_id": recipient["_id"],
            "responseLocked": {"$ne": True}
        },
        {
            "$set": {
                "responseLocked": True,
                "firstButtonClicked": button_text,
                "buttonPayload": event.get("buttonPayload"),
                "normalizedResponse": button_action["normalizedResponse"],
                "currentLeadStatus": button_action["leadStatus"],
                "followupTemplateToSend": button_action["nextTemplate"],
                "responseAt":  int(time.time() * 1000),
                "updateTime":  int(time.time() * 1000),
            }
        }
    )


    logger.critical(f"update_result======>{update_result}")

    if update_result.modified_count == 0:
        logger.info(
            "Button click skipped because response was already locked by another request | phone=%s",
            phone
        )
        return

    lead_name = recipient.get("name", "")

    send_result = send_whatsapp_template(
        phone=phone,
        template_name=button_action["nextTemplate"],
        name=lead_name
    )

    template_sent = bool(send_result.get("success"))

    campaign_recipients.update_one(
        {
            "_id": recipient["_id"]
        },
        {
            "$set": {
                "followupTemplateSent": (
                    button_action["nextTemplate"]
                    if template_sent
                    else None
                ),
                "followupTemplateStatus": (
                    "SENT"
                    if template_sent
                    else "FAILED"
                ),
                "followupTemplateSentAt": (
                     int(time.time() * 1000)
                    if template_sent
                    else None
                ),
                "followupTemplateApiResponse": send_result.get("response"),
                "followupTemplateError": send_result.get("error"),
                "updateTime":  int(time.time() * 1000),
            }
        }
    )

    whatsapp_message_logs = get_collection("whatsapp_message_logs")

    whatsapp_message_logs.insert_one(
        {
            "phone": phone,
            "name": lead_name,
            "campaignName": DEFAULT_CAMPAIGN_NAME,
            "direction": "OUTBOUND",
            "templateName": button_action["nextTemplate"],
            "status": "SENT" if template_sent else "FAILED",
            "apiResponse": send_result.get("response"),
            "error": send_result.get("error"),
            "createTime":  int(time.time() * 1000),
            "updateTime":  int(time.time() * 1000),
        }
    )
from typing import Any, Dict
import time

from loguru import logger

from app.config import (
    DEFAULT_CAMPAIGN_NAME,
    TEMPLATE_INVITE,
    TEMPLATE_SEAT_CONFIRMED,
    TEMPLATE_COUNSELLING,
    TEMPLATE_FINAL_DAY_REMINDER,
)
from app.db.mongodb import get_collection
from app.services.whatsapp_sender import send_whatsapp_template










def process_text_message(event: Dict[str, Any]):
    phone = event.get("from")
    text = event.get("text")
    now = int(time.time() * 1000)

    if not phone or not text:
        return

    campaign_recipients = get_collection("campaign_recipients")
    user_text_messages = get_collection("user_text_messages")

    recipient = campaign_recipients.find_one(
        {
            "phone": phone,
            "campaignName": DEFAULT_CAMPAIGN_NAME,
        }
    )

    user_text_messages.insert_one(
        {
            "phone": phone,
            "name": recipient.get("name", "") if recipient else "",
            "campaignName": DEFAULT_CAMPAIGN_NAME,
            "messageType": "text",
            "text": text,
            "waMessageId": event.get("waMessageId"),
            "contextMessageId": event.get("contextMessageId"),
            "rawEvent": event,
            "createTime": now,
            "updateTime": now,
        }
    )

    if recipient:
        campaign_recipients.update_one(
            {
                "_id": recipient["_id"]
            },
            {
                "$set": {
                    "lastTextMessage": text,
                    "lastTextMessageAt": now,
                    "updateTime": now,
                },
                "$inc": {
                    "textMessageCount": 1
                }
            }
        )

def extract_wa_message_id(send_result: Dict[str, Any]):
    try:
        return (
            send_result
            .get("response", {})
            .get("messages", [{}])[0]
            .get("id")
        )
    except Exception:
        return None


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


def normalize_final_day_button(
    button_text: str = "",
    button_payload: str = ""
):
    cleaned_text = (button_text or "").strip().lower()
    cleaned_payload = (button_payload or "").strip().lower()

    if (
        cleaned_text == "know more"
        or cleaned_payload in [
            "know_more",
            "know more",
            "know-more",
            "knowmore",
        ]
    ):
        return {
            "action": "KNOW_MORE",
            "buttonLabel": "Know More"
        }

    if (
        cleaned_text == "call now"
        or cleaned_payload in [
            "call_now",
            "call now",
            "call-now",
            "call",
        ]
    ):
        return {
            "action": "CALL_NOW",
            "buttonLabel": "Call Now"
        }

    if (
        cleaned_text == "get location"
        or cleaned_payload in [
            "get_location",
            "get location",
            "get-location",
            "location",
        ]
    ):
        return {
            "action": "GET_LOCATION",
            "buttonLabel": "Get Location"
        }

    return None


def get_outbound_log_for_context(event: Dict[str, Any]):
    context_message_id = event.get("contextMessageId")

    if not context_message_id:
        return None

    whatsapp_message_logs = get_collection("whatsapp_message_logs")

    return whatsapp_message_logs.find_one(
        {
            "waMessageId": context_message_id
        }
    )


def is_final_day_reminder_click(event: Dict[str, Any]) -> bool:
    outbound_log = get_outbound_log_for_context(event)

    if not outbound_log:
        return False

    return outbound_log.get("messagePurpose") == "FINAL_DAY_UTILITY_REMINDER"


def process_final_day_reminder_click(
    event: Dict[str, Any],
    recipient: Dict[str, Any]
):
    phone = event.get("from")
    button_text = event.get("buttonText")
    button_payload = event.get("buttonPayload")
    now = int(time.time() * 1000)

    if not phone or not (button_text or button_payload):
        return

    final_day_action = normalize_final_day_button(
        button_text=button_text,
        button_payload=button_payload
    )

    if not final_day_action:
        logger.info(
            "Unknown final day reminder button | phone={} buttonText={} buttonPayload={}",
            phone,
            button_text,
            button_payload
        )
        return

    campaign_recipients = get_collection("campaign_recipients")
    reminder_button_clicks = get_collection("reminder_button_clicks")
    whatsapp_message_logs = get_collection("whatsapp_message_logs")

    outbound_log = get_outbound_log_for_context(event)

    reminder_button_clicks.insert_one(
        {
            "phone": phone,
            "name": recipient.get("name", ""),
            "campaignName": DEFAULT_CAMPAIGN_NAME,
            "templateName": TEMPLATE_FINAL_DAY_REMINDER,
            "messagePurpose": "FINAL_DAY_UTILITY_REMINDER",
            "buttonText": button_text,
            "buttonPayload": button_payload,
            "normalizedAction": final_day_action["action"],
            "buttonLabel": final_day_action["buttonLabel"],
            "contextMessageId": event.get("contextMessageId"),
            "outboundLogId": outbound_log.get("_id") if outbound_log else None,
            "waMessageId": event.get("waMessageId"),
            "rawEvent": event,
            "createTime": now,
            "updateTime": now,
        }
    )

    campaign_recipients.update_one(
        {
            "_id": recipient["_id"]
        },
        {
            "$set": {
                "finalDayReminderLastClickedButton": final_day_action["buttonLabel"],
                "finalDayReminderLastClickedAction": final_day_action["action"],
                "finalDayReminderLastClickedAt": now,
                "updateTime": now,
            },
            "$addToSet": {
                "finalDayReminderClickedButtons": final_day_action["buttonLabel"],
                "finalDayReminderClickedActions": final_day_action["action"],
            },
            "$inc": {
                "finalDayReminderClickCount": 1
            }
        }
    )

    if final_day_action["action"] == "KNOW_MORE":
        send_result = send_whatsapp_template(
            phone=phone,
            template_name=TEMPLATE_INVITE,
            name=recipient.get("name", "")
        )

        marketing_sent = bool(send_result.get("success"))
        retry_wa_message_id = extract_wa_message_id(send_result)

        now = int(time.time() * 1000)

        campaign_recipients.update_one(
            {
                "_id": recipient["_id"]
            },
            {
                "$set": {
                    "finalDayKnowMoreClicked": True,
                    "finalDayKnowMoreClickedAt": now,
                    "finalDayKnowMoreMarketingTemplateName": TEMPLATE_INVITE,
                    "finalDayKnowMoreMarketingStatus": "SENT" if marketing_sent else "FAILED",
                    "finalDayKnowMoreMarketingWaMessageId": retry_wa_message_id,
                    "finalDayKnowMoreMarketingError": None if marketing_sent else send_result.get("error"),
                    "finalDayKnowMoreMarketingApiResponse": send_result.get("response"),
                    "updateTime": now,
                }
            }
        )

        whatsapp_message_logs.insert_one(
            {
                "phone": phone,
                "name": recipient.get("name", ""),
                "campaignName": DEFAULT_CAMPAIGN_NAME,
                "direction": "OUTBOUND",
                "templateName": TEMPLATE_INVITE,
                "messagePurpose": "FINAL_DAY_KNOW_MORE_MARKETING_INVITE",
                "waMessageId": retry_wa_message_id,
                "status": "SENT" if marketing_sent else "FAILED",
                "apiResponse": send_result.get("response"),
                "error": send_result.get("error"),
                "createTime": now,
                "updateTime": now,
            }
        )


def process_button_click(event: Dict[str, Any]):
    phone = event.get("from")
    button_text = event.get("buttonText")
    button_payload = event.get("buttonPayload")

    if not phone or not (button_text or button_payload):
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
            "No campaign recipient found for phone={} campaign={}",
            phone,
            DEFAULT_CAMPAIGN_NAME
        )
        return

    # ==================================================
    # Final-day reminder buttons:
    # Know More, Call Now, Get Location
    #
    # These should NOT use responseLocked.
    # User can click all 3 buttons.
    # ==================================================

    if is_final_day_reminder_click(event):
        process_final_day_reminder_click(event, recipient)
        return

    button_action = normalize_button_response(button_text)

    logger.critical(f"button_action======>{button_action}")

    if not button_action:
        logger.info(
            "Unknown button clicked | phone={} buttonText={} buttonPayload={}",
            phone,
            button_text,
            button_payload
        )
        return

    # First click wins for old marketing invite final-response buttons.
    # This does NOT apply to final-day reminder buttons above.
    if recipient.get("responseLocked") is True:
        logger.info(
            "Response already locked. Ignoring button click | phone={} button={} existingResponse={}",
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
                "buttonPayload": button_payload,
                "reason": "response_already_locked",
                "existingResponse": recipient.get("normalizedResponse"),
                "rawEvent": event,
                "createTime": int(time.time() * 1000),
                "updateTime": int(time.time() * 1000),
            }
        )

        return

    now = int(time.time() * 1000)

    update_result = campaign_recipients.update_one(
        {
            "_id": recipient["_id"],
            "responseLocked": {"$ne": True}
        },
        {
            "$set": {
                "responseLocked": True,
                "firstButtonClicked": button_text,
                "buttonPayload": button_payload,
                "normalizedResponse": button_action["normalizedResponse"],
                "currentLeadStatus": button_action["leadStatus"],
                "followupTemplateToSend": button_action["nextTemplate"],
                "responseAt": now,
                "updateTime": now,
            }
        }
    )

    logger.critical(f"update_result======>{update_result}")

    if update_result.modified_count == 0:
        logger.info(
            "Button click skipped because response was already locked by another request | phone={}",
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
                "updateTime": int(time.time() * 1000),
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
            "messagePurpose": "FINAL_RESPONSE_FOLLOWUP",
            "status": "SENT" if template_sent else "FAILED",
            "apiResponse": send_result.get("response"),
            "error": send_result.get("error"),
            "createTime": int(time.time() * 1000),
            "updateTime": int(time.time() * 1000),
        }
    )
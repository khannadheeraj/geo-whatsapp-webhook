from typing import Any, Dict, Optional
import time

from loguru import logger

from app.config import (
    DEFAULT_CAMPAIGN_NAME,
    TEMPLATE_INVITE,
    TEMPLATE_SEAT_CONFIRMED,
    TEMPLATE_COUNSELLING,
    TEMPLATE_FINAL_DAY_REMINDER,
    SCHOLARSHIP_MOCK_TEST_CAMPAIGN_NAME,
    TEMPLATE_SCHOLARSHIP_MOCK_TEST,
    FREE_DEMO_CLASS_CAMPAIGN_NAME,
    TEMPLATE_FREE_DEMO_CLASS_INVITATION,
    TEMPLATE_UPSC_DEMO_CLASS_REMINDER
)
from app.db.mongodb import get_collection
from app.services.whatsapp_sender import send_whatsapp_template


# =========================================================
# Common Helpers
# =========================================================

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


def normalize_free_demo_class_reminder_button(
    button_text: str = "",
    button_payload: str = ""
):
    cleaned_text = (button_text or "").strip().lower()
    cleaned_payload = (button_payload or "").strip().lower()

    if (
        cleaned_text in [
            "yes i will attend",
            "yes, i will attend",
            "yes i'll attend",
            "yes, i'll attend",
            "yes attend",
            "yes"
        ]
        or cleaned_payload in [
            "yes_i_will_attend",
            "yes-i-will-attend",
            "yes_i_will_attend_demo",
            "demo_class_yes_attend",
            "yes"
        ]
    ):
        return {
            "action": "FREE_DEMO_CLASS_REMINDER_YES_ATTEND",
            "buttonLabel": "Yes I will attend"
        }

    return None


def process_free_demo_class_reminder_button_click(
    event: Dict[str, Any],
    recipient: Dict[str, Any],
    outbound_log: Optional[Dict[str, Any]] = None
):
    phone = event.get("from")
    button_text = event.get("buttonText")
    button_payload = event.get("buttonPayload")
    now = int(time.time() * 1000)

    if not phone or not (button_text or button_payload):
        return

    reminder_action = normalize_free_demo_class_reminder_button(
        button_text=button_text,
        button_payload=button_payload
    )

    if not reminder_action:
        logger.info(
            "Unknown free demo class reminder button | phone={} buttonText={} buttonPayload={}",
            phone,
            button_text,
            button_payload
        )
        return

    campaign_recipients = get_collection("campaign_recipients")
    demo_class_button_clicks = get_collection("demo_class_button_clicks")

    if outbound_log is None:
        outbound_log = get_outbound_log_for_context(event)

    demo_class_button_clicks.insert_one(
        {
            "phone": phone,
            "name": recipient.get("name", ""),
            "campaignName": FREE_DEMO_CLASS_CAMPAIGN_NAME,
            "templateName": TEMPLATE_UPSC_DEMO_CLASS_REMINDER,
            "messagePurpose": "FREE_DEMO_CLASS_REMINDER",
            "buttonText": button_text,
            "buttonPayload": button_payload,
            "normalizedAction": reminder_action["action"],
            "buttonLabel": reminder_action["buttonLabel"],
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
                "freeDemoClassReminderLastClickedButton": reminder_action["buttonLabel"],
                "freeDemoClassReminderLastClickedAction": reminder_action["action"],
                "freeDemoClassReminderLastClickedAt": now,
                "currentLeadStatus": reminder_action["action"],
                "updateTime": now,
            },
            "$addToSet": {
                "freeDemoClassReminderClickedButtons": reminder_action["buttonLabel"],
                "freeDemoClassReminderClickedActions": reminder_action["action"],
            },
            "$inc": {
                "freeDemoClassReminderClickCount": 1
            }
        }
    )


def get_outbound_log_for_context(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    WhatsApp button/text reply usually contains:
        context.id = outbound message id

    We use that contextMessageId to find the original outbound message
    from whatsapp_message_logs.

    This tells us:
        - which campaign the reply belongs to
        - which template was replied to
        - what purpose that message had
    """

    context_message_id = event.get("contextMessageId")

    if not context_message_id:
        return None

    whatsapp_message_logs = get_collection("whatsapp_message_logs")

    return whatsapp_message_logs.find_one(
        {
            "waMessageId": context_message_id
        }
    )


def find_recipient_by_campaign(
    phone: str,
    campaign_name: str
):
    campaign_recipients = get_collection("campaign_recipients")

    return campaign_recipients.find_one(
        {
            "phone": phone,
            "campaignName": campaign_name,
        }
    )


# =========================================================
# Old Orientation Campaign Button Normalization
# =========================================================

def normalize_button_response(
    button_text: str = "",
    button_payload: str = ""
):
    cleaned_button_text = (button_text or "").strip().lower()
    cleaned_button_payload = (button_payload or "").strip().lower()

    if (
        cleaned_button_text in [
            "yes, i will attend",
            "yes i will attend",
            "yes, i'll attend",
            "yes i'll attend",
            "yes",
        ]
        or cleaned_button_payload in [
            "yes_attend",
            "yes_i_will_attend",
            "yes-i-will-attend",
            "yes, i will attend",
            "yes i will attend",
        ]
    ):
        return {
            "normalizedResponse": "YES_ATTEND",
            "leadStatus": "SEAT_CONFIRMED",
            "nextTemplate": TEMPLATE_SEAT_CONFIRMED,
        }

    if (
        cleaned_button_text in [
            "talk to counselor",
            "talk to counsellor",
            "talk counselor",
            "talk counsellor",
        ]
        or cleaned_button_payload in [
            "talk_to_counselor",
            "talk_to_counsellor",
            "talk-counselor",
            "talk-counsellor",
            "talk to counselor",
            "talk to counsellor",
        ]
    ):
        return {
            "normalizedResponse": "TALK_COUNSELOR",
            "leadStatus": "COUNSELLOR_REQUESTED",
            "nextTemplate": TEMPLATE_COUNSELLING,
        }

    return None


# =========================================================
# Final Day Reminder Button Normalization
# appointment_reminder_2
# Buttons:
#   Know More
#   Call Now
#   Get Location
# =========================================================

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


# =========================================================
# Scholarship Mock Test Button Normalization
# Template: upsc_scholarship_mock_test_invitation
# Buttons:
#   Interested
#   Location
#   Talk with Management
# =========================================================

def normalize_scholarship_button(
    button_text: str = "",
    button_payload: str = ""
):
    cleaned_text = (button_text or "").strip().lower()
    cleaned_payload = (button_payload or "").strip().lower()

    if (
        cleaned_text == "interested"
        or cleaned_payload in [
            "interested",
            "scholarship_interested",
        ]
    ):
        return {
            "action": "SCHOLARSHIP_INTERESTED",
            "buttonLabel": "Interested"
        }

    if (
        cleaned_text == "location"
        or cleaned_payload in [
            "location",
            "scholarship_location",
            "get location",
            "get_location",
        ]
    ):
        return {
            "action": "SCHOLARSHIP_LOCATION_REQUESTED",
            "buttonLabel": "Location"
        }

    if (
        cleaned_text == "talk with management"
        or cleaned_payload in [
            "talk with management",
            "talk_with_management",
            "management",
            "talk management",
        ]
    ):
        return {
            "action": "SCHOLARSHIP_MANAGEMENT_REQUESTED",
            "buttonLabel": "Talk with Management"
        }

    return None


# =========================================================
# Final Day Reminder Click Processor
# Allows all 3 buttons.
# Does NOT use responseLocked.
# Know More sends marketing invite again.
# =========================================================

def process_final_day_reminder_click(
    event: Dict[str, Any],
    recipient: Dict[str, Any],
    outbound_log: Optional[Dict[str, Any]] = None
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

    if outbound_log is None:
        outbound_log = get_outbound_log_for_context(event)

    # Store every click separately.
    # User may click Know More + Call Now + Get Location.
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

    # Know More sends marketing invite again.
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


# =========================================================
# Scholarship Mock Test Click Processor
# Allows all 3 buttons.
# Does NOT use responseLocked.
# Tracks every click in scholarship_button_clicks.
# =========================================================

def process_scholarship_button_click(
    event: Dict[str, Any],
    recipient: Dict[str, Any],
    outbound_log: Optional[Dict[str, Any]] = None
):
    phone = event.get("from")
    button_text = event.get("buttonText")
    button_payload = event.get("buttonPayload")
    now = int(time.time() * 1000)

    if not phone or not (button_text or button_payload):
        return

    scholarship_action = normalize_scholarship_button(
        button_text=button_text,
        button_payload=button_payload
    )

    if not scholarship_action:
        logger.info(
            "Unknown scholarship button | phone={} buttonText={} buttonPayload={}",
            phone,
            button_text,
            button_payload
        )
        return

    campaign_recipients = get_collection("campaign_recipients")
    scholarship_button_clicks = get_collection("scholarship_button_clicks")

    if outbound_log is None:
        outbound_log = get_outbound_log_for_context(event)

    scholarship_button_clicks.insert_one(
        {
            "phone": phone,
            "name": recipient.get("name", ""),
            "campaignName": SCHOLARSHIP_MOCK_TEST_CAMPAIGN_NAME,
            "templateName": TEMPLATE_SCHOLARSHIP_MOCK_TEST,
            "messagePurpose": "SCHOLARSHIP_MOCK_TEST_INVITE",
            "buttonText": button_text,
            "buttonPayload": button_payload,
            "normalizedAction": scholarship_action["action"],
            "buttonLabel": scholarship_action["buttonLabel"],
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
                "scholarshipLastClickedButton": scholarship_action["buttonLabel"],
                "scholarshipLastClickedAction": scholarship_action["action"],
                "scholarshipLastClickedAt": now,
                "currentLeadStatus": scholarship_action["action"],
                "updateTime": now,
            },
            "$addToSet": {
                "scholarshipClickedButtons": scholarship_action["buttonLabel"],
                "scholarshipClickedActions": scholarship_action["action"],
            },
            "$inc": {
                "scholarshipClickCount": 1
            }
        }
    )


# =========================================================
# Text Message Processor
# Stores typed user messages.
# Uses contextMessageId to attach text to correct campaign/template.
# =========================================================

def process_text_message(event: Dict[str, Any]):
    phone = event.get("from")
    text = event.get("text")
    now = int(time.time() * 1000)

    if not phone or not text:
        return

    outbound_log = get_outbound_log_for_context(event)

    campaign_name = (
        outbound_log.get("campaignName")
        if outbound_log
        else DEFAULT_CAMPAIGN_NAME
    )

    template_name = (
        outbound_log.get("templateName")
        if outbound_log
        else None
    )

    message_purpose = (
        outbound_log.get("messagePurpose")
        if outbound_log
        else None
    )

    campaign_recipients = get_collection("campaign_recipients")
    user_text_messages = get_collection("user_text_messages")

    recipient = campaign_recipients.find_one(
        {
            "phone": phone,
            "campaignName": campaign_name,
        }
    )

    cleaned_text = (
        text
        .strip()
        .lower()
        .replace(".", "")
        .replace(",", "")
        .replace("!", "")
    )

    is_stop_request = cleaned_text == "stop"

    # ==========================================
    # Store every typed message
    # ==========================================

    user_text_messages.insert_one(
        {
            "phone": phone,
            "name": recipient.get("name", "") if recipient else "",
            "campaignName": campaign_name,
            "templateName": template_name,
            "messagePurpose": message_purpose,
            "messageType": "text",
            "text": text,
            "cleanedText": cleaned_text,
            "isStopRequest": is_stop_request,
            "waMessageId": event.get("waMessageId"),
            "contextMessageId": event.get("contextMessageId"),
            "contextFrom": event.get("contextFrom"),
            "rawEvent": event,
            "createTime": now,
            "updateTime": now,
        }
    )

    # ==========================================
    # Update recipient latest text summary
    # ==========================================

    if recipient:
        campaign_recipients.update_one(
            {
                "_id": recipient["_id"]
            },
            {
                "$set": {
                    "lastTextMessage": text,
                    "lastTextMessageAt": now,
                    "lastTextMessageCampaignName": campaign_name,
                    "lastTextMessageTemplateName": template_name,
                    "lastTextMessagePurpose": message_purpose,
                    "updateTime": now,
                },
                "$inc": {
                    "textMessageCount": 1
                }
            }
        )

    # ==========================================
    # STOP / Unsubscribe Handling
    # ==========================================

    if is_stop_request:
        whatsapp_unsubscribed_users = get_collection("whatsapp_unsubscribed_users")

        whatsapp_unsubscribed_users.update_one(
            {
                "phone": phone
            },
            {
                "$set": {
                    "phone": phone,
                    "name": recipient.get("name", "") if recipient else "",
                    "isUnsubscribed": True,
                    "unsubscribeText": text,
                    "sourceCampaignName": campaign_name,
                    "sourceTemplateName": template_name,
                    "sourceMessagePurpose": message_purpose,
                    "unsubscribedAt": now,
                    "updateTime": now,
                },
                "$setOnInsert": {
                    "createTime": now,
                }
            },
            upsert=True
        )

        if recipient:
            campaign_recipients.update_one(
                {
                    "_id": recipient["_id"]
                },
                {
                    "$set": {
                        "isUnsubscribed": True,
                        "unsubscribeText": text,
                        "unsubscribedAt": now,
                        "currentLeadStatus": "UNSUBSCRIBED",
                        "updateTime": now,
                    }
                }
            )

        logger.info(
            "User unsubscribed via STOP | phone={} campaign={} template={}",
            phone,
            campaign_name,
            template_name
        )
# =========================================================
# Main Button Router
# This routes button clicks based on contextMessageId.
# =========================================================

def process_button_click(event: Dict[str, Any]):
    phone = event.get("from")
    button_text = event.get("buttonText")
    button_payload = event.get("buttonPayload")

    if not phone or not (button_text or button_payload):
        return

    # Find original outbound message using contextMessageId
    outbound_log = get_outbound_log_for_context(event)

    campaign_name = (
        outbound_log.get("campaignName")
        if outbound_log
        else DEFAULT_CAMPAIGN_NAME
    )

    message_purpose = (
        outbound_log.get("messagePurpose")
        if outbound_log
        else None
    )

    campaign_recipients = get_collection("campaign_recipients")

    recipient = campaign_recipients.find_one(
        {
            "phone": phone,
            "campaignName": campaign_name,
        }
    )

    logger.critical(
        "BUTTON_CLICK | phone={} campaign={} buttonText={} buttonPayload={} purpose={} recipient_found={}",
        phone,
        campaign_name,
        button_text,
        button_payload,
        message_purpose,
        recipient is not None
    )

    if not recipient:
        logger.warning(
            "No campaign recipient found for phone={} campaign={}",
            phone,
            campaign_name
        )
        return

    # ==================================================
    # Scholarship Mock Test Campaign
    # Buttons:
    # Interested / Location / Talk with Management
    # No lock. Track every click.
    # ==================================================

    if message_purpose == "SCHOLARSHIP_MOCK_TEST_INVITE":
        process_scholarship_button_click(
            event=event,
            recipient=recipient,
            outbound_log=outbound_log
        )
        return

    # ==================================================
    # Final Day Reminder Campaign
    # Buttons:
    # Know More / Call Now / Get Location
    # No lock. Track every click.
    # ==================================================

    if message_purpose == "FINAL_DAY_UTILITY_REMINDER":
        process_final_day_reminder_click(
            event=event,
            recipient=recipient,
            outbound_log=outbound_log
        )
        return

    # ==================================================
    # Free Demo Class Campaign
    # Template:
    # upsc_free_demo_class_invitation
    #
    # Trackable button:
    # Interested
    #
    # Location and Talk to Counsellor are CTA buttons,
    # so webhook tracking is not guaranteed for them.
    # ==================================================

    if message_purpose == "FREE_DEMO_CLASS_INVITE":
        process_free_demo_class_button_click(
            event=event,
            recipient=recipient,
            outbound_log=outbound_log
        )
        return

    if message_purpose == "FREE_DEMO_CLASS_REMINDER":
        process_free_demo_class_reminder_button_click(...)
        return

    # ==================================================
    # Old Orientation Invite Campaign
    # Buttons:
    # Yes, I will attend / Talk to Counselor
    # First click wins.
    # ==================================================

    button_action = normalize_button_response(
        button_text=button_text,
        button_payload=button_payload
    )

    logger.critical("button_action======>{}", button_action)

    if not button_action:
        logger.info(
            "Unknown button clicked | phone={} buttonText={} buttonPayload={}",
            phone,
            button_text,
            button_payload
        )
        return

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
                "campaignName": campaign_name,
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

    logger.critical("update_result======>{}", update_result)

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
    followup_wa_message_id = extract_wa_message_id(send_result)

    now = int(time.time() * 1000)

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
                    now
                    if template_sent
                    else None
                ),
                "followupTemplateWaMessageId": followup_wa_message_id,
                "followupTemplateApiResponse": send_result.get("response"),
                "followupTemplateError": send_result.get("error"),
                "updateTime": now,
            }
        }
    )

    whatsapp_message_logs = get_collection("whatsapp_message_logs")

    whatsapp_message_logs.insert_one(
        {
            "phone": phone,
            "name": lead_name,
            "campaignName": campaign_name,
            "direction": "OUTBOUND",
            "templateName": button_action["nextTemplate"],
            "messagePurpose": "FINAL_RESPONSE_FOLLOWUP",
            "waMessageId": followup_wa_message_id,
            "status": "SENT" if template_sent else "FAILED",
            "apiResponse": send_result.get("response"),
            "error": send_result.get("error"),
            "createTime": now,
            "updateTime": now,
        }
    )

def normalize_free_demo_class_button(
    button_text: str = "",
    button_payload: str = ""
):
    cleaned_text = (button_text or "").strip().lower()
    cleaned_payload = (button_payload or "").strip().lower()

    if (
        cleaned_text == "interested"
        or cleaned_payload in [
            "interested",
            "demo_class_interested",
            "free_demo_class_interested",
        ]
    ):
        return {
            "action": "FREE_DEMO_CLASS_INTERESTED",
            "buttonLabel": "Interested"
        }

    return None


def process_free_demo_class_button_click(
    event: Dict[str, Any],
    recipient: Dict[str, Any],
    outbound_log: Optional[Dict[str, Any]] = None
):
    phone = event.get("from")
    button_text = event.get("buttonText")
    button_payload = event.get("buttonPayload")
    now = int(time.time() * 1000)

    if not phone or not (button_text or button_payload):
        return

    demo_action = normalize_free_demo_class_button(
        button_text=button_text,
        button_payload=button_payload
    )

    if not demo_action:
        logger.info(
            "Unknown free demo class button | phone={} buttonText={} buttonPayload={}",
            phone,
            button_text,
            button_payload
        )
        return

    campaign_recipients = get_collection("campaign_recipients")
    demo_class_button_clicks = get_collection("demo_class_button_clicks")

    if outbound_log is None:
        outbound_log = get_outbound_log_for_context(event)

    demo_class_button_clicks.insert_one(
        {
            "phone": phone,
            "name": recipient.get("name", ""),
            "campaignName": FREE_DEMO_CLASS_CAMPAIGN_NAME,
            "templateName": TEMPLATE_FREE_DEMO_CLASS_INVITATION,
            "messagePurpose": "FREE_DEMO_CLASS_INVITE",
            "buttonText": button_text,
            "buttonPayload": button_payload,
            "normalizedAction": demo_action["action"],
            "buttonLabel": demo_action["buttonLabel"],
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
                "freeDemoClassLastClickedButton": demo_action["buttonLabel"],
                "freeDemoClassLastClickedAction": demo_action["action"],
                "freeDemoClassLastClickedAt": now,
                "currentLeadStatus": demo_action["action"],
                "updateTime": now,
            },
            "$addToSet": {
                "freeDemoClassClickedButtons": demo_action["buttonLabel"],
                "freeDemoClassClickedActions": demo_action["action"],
            },
            "$inc": {
                "freeDemoClassClickCount": 1
            }
        }
    )
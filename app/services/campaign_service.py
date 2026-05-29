# import logging
# from typing import Any, Dict

# from app.config import (
#     DEFAULT_CAMPAIGN_NAME,
#     TEMPLATE_SEAT_CONFIRMED,
#     TEMPLATE_COUNSELLING,
# )
# from app.db.mongodb import get_collection
# from app.services.whatsapp_sender import send_whatsapp_template
# import time

# from loguru import logger




# # logger = logging.getLogger("whatsapp-webhook")


# def normalize_button_response(button_text: str):
#     if not button_text:
#         return None

#     cleaned_button_text = button_text.strip().lower()

#     if cleaned_button_text == "yes, i will attend":
#         return {
#             "normalizedResponse": "YES_ATTEND",
#             "leadStatus": "SEAT_CONFIRMED",
#             "nextTemplate": TEMPLATE_SEAT_CONFIRMED,
#         }

#     if cleaned_button_text == "talk to counselor":
#         return {
#             "normalizedResponse": "TALK_COUNSELOR",
#             "leadStatus": "COUNSELLOR_REQUESTED",
#             "nextTemplate": TEMPLATE_COUNSELLING,
#         }

#     return None


# def process_button_click(event: Dict[str, Any]):
#     phone = event.get("from")
#     button_text = event.get("buttonText")

#     if not phone or not button_text:
#         return

#     button_action = normalize_button_response(button_text)

#     logger.critical(f"button_action======>{button_action}")

#     if not button_action:
        
#         logger.info("Unknown button clicked | phone=%s button=%s", phone,button_text )
        
#         return

#     campaign_recipients = get_collection("campaign_recipients")

#     recipient = campaign_recipients.find_one(
#         {
#             "phone": phone,
#             "campaignName": DEFAULT_CAMPAIGN_NAME,
#         }
#     )

#     logger.critical(f"recipient_data======>{recipient}")

#     if not recipient:
#         logger.warning(
#             "No campaign recipient found for phone=%s campaign=%s",
#             phone,
#             DEFAULT_CAMPAIGN_NAME
#         )
#         return

#     # First click wins.
#     # If responseLocked is already true, do not send another template.
#     if recipient.get("responseLocked") is True:
#         logger.info(
#             "Response already locked. Ignoring button click | phone=%s button=%s existingResponse=%s",
#             phone,
#             button_text,
#             recipient.get("normalizedResponse")
#         )

#         ignored_clicks = get_collection("ignored_button_clicks")

#         ignored_clicks.insert_one(
#             {
#                 "phone": phone,
#                 "campaignName": DEFAULT_CAMPAIGN_NAME,
#                 "buttonText": button_text,
#                 "buttonPayload": event.get("buttonPayload"),
#                 "reason": "response_already_locked",
#                 "existingResponse": recipient.get("normalizedResponse"),
#                 "rawEvent": event,
#                 "createTime":  int(time.time() * 1000),
#                 "updateTime":  int(time.time() * 1000),
#             }
#         )

#         return

#     # Atomic update protects against duplicate webhook race condition.
#     update_result = campaign_recipients.update_one(
#         {
#             "_id": recipient["_id"],
#             "responseLocked": {"$ne": True}
#         },
#         {
#             "$set": {
#                 "responseLocked": True,
#                 "firstButtonClicked": button_text,
#                 "buttonPayload": event.get("buttonPayload"),
#                 "normalizedResponse": button_action["normalizedResponse"],
#                 "currentLeadStatus": button_action["leadStatus"],
#                 "followupTemplateToSend": button_action["nextTemplate"],
#                 "responseAt":  int(time.time() * 1000),
#                 "updateTime":  int(time.time() * 1000),
#             }
#         }
#     )


#     logger.critical(f"update_result======>{update_result}")

#     if update_result.modified_count == 0:
#         logger.info(
#             "Button click skipped because response was already locked by another request | phone=%s",
#             phone
#         )
#         return

#     lead_name = recipient.get("name", "")

#     send_result = send_whatsapp_template(
#         phone=phone,
#         template_name=button_action["nextTemplate"],
#         name=lead_name
#     )

#     template_sent = bool(send_result.get("success"))

#     campaign_recipients.update_one(
#         {
#             "_id": recipient["_id"]
#         },
#         {
#             "$set": {
#                 "followupTemplateSent": (
#                     button_action["nextTemplate"]
#                     if template_sent
#                     else None
#                 ),
#                 "followupTemplateStatus": (
#                     "SENT"
#                     if template_sent
#                     else "FAILED"
#                 ),
#                 "followupTemplateSentAt": (
#                      int(time.time() * 1000)
#                     if template_sent
#                     else None
#                 ),
#                 "followupTemplateApiResponse": send_result.get("response"),
#                 "followupTemplateError": send_result.get("error"),
#                 "updateTime":  int(time.time() * 1000),
#             }
#         }
#     )

#     whatsapp_message_logs = get_collection("whatsapp_message_logs")

#     whatsapp_message_logs.insert_one(
#         {
#             "phone": phone,
#             "name": lead_name,
#             "campaignName": DEFAULT_CAMPAIGN_NAME,
#             "direction": "OUTBOUND",
#             "templateName": button_action["nextTemplate"],
#             "status": "SENT" if template_sent else "FAILED",
#             "apiResponse": send_result.get("response"),
#             "error": send_result.get("error"),
#             "createTime":  int(time.time() * 1000),
#             "updateTime":  int(time.time() * 1000),
#         }
#     )


#===============================================================================================================================================================================



from typing import Any, Dict
import time

from loguru import logger

from app.config import (
    DEFAULT_CAMPAIGN_NAME,
    TEMPLATE_INVITE,
    TEMPLATE_SEAT_CONFIRMED,
    TEMPLATE_COUNSELLING,
)
from app.db.mongodb import get_collection
from app.services.whatsapp_sender import send_whatsapp_template


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


def normalize_button_response(
    button_text: str = "",
    button_payload: str = ""
):
    cleaned_button_text = (button_text or "").strip().lower()
    cleaned_button_payload = (button_payload or "").strip().lower()

    # Utility fallback button
    # appointment_reminder_2 has button: Know More
    if (
        cleaned_button_text == "know more"
        or cleaned_button_payload in [
            "know_more",
            "know-more",
            "know more",
            "knowmore",
        ]
    ):
        return {
            "normalizedResponse": "KNOW_MORE",
            "leadStatus": "KNOW_MORE_CLICKED",
            "nextTemplate": TEMPLATE_INVITE,
            "actionType": "RETRY_MARKETING_INVITE",
        }

    # Final response button 1
    if cleaned_button_text == "yes, i will attend":
        return {
            "normalizedResponse": "YES_ATTEND",
            "leadStatus": "SEAT_CONFIRMED",
            "nextTemplate": TEMPLATE_SEAT_CONFIRMED,
            "actionType": "FINAL_RESPONSE",
        }

    # Final response button 2
    if cleaned_button_text == "talk to counselor":
        return {
            "normalizedResponse": "TALK_COUNSELOR",
            "leadStatus": "COUNSELLOR_REQUESTED",
            "nextTemplate": TEMPLATE_COUNSELLING,
            "actionType": "FINAL_RESPONSE",
        }

    return None


def process_know_more_click(
    event: Dict[str, Any],
    recipient: Dict[str, Any]
):
    phone = event.get("from")
    lead_name = recipient.get("name", "")
    now = int(time.time() * 1000)

    campaign_recipients = get_collection("campaign_recipients")
    whatsapp_message_logs = get_collection("whatsapp_message_logs")

    if not phone:
        return

    # Prevent duplicate marketing invite if user clicks Know More many times
    if recipient.get("retryMarketingInviteStatus") == "SENT":
        logger.info(
            "Retry marketing invite already sent after Know More | phone={}",
            phone
        )

        ignored_clicks = get_collection("ignored_button_clicks")

        ignored_clicks.insert_one(
            {
                "phone": phone,
                "campaignName": DEFAULT_CAMPAIGN_NAME,
                "buttonText": event.get("buttonText"),
                "buttonPayload": event.get("buttonPayload"),
                "reason": "retry_marketing_invite_already_sent",
                "existingStatus": recipient.get("retryMarketingInviteStatus"),
                "rawEvent": event,
                "createTime": now,
                "updateTime": now,
            }
        )

        return

    campaign_recipients.update_one(
        {
            "_id": recipient["_id"]
        },
        {
            "$set": {
                "knowMoreClicked": True,
                "knowMoreClickedAt": now,
                "knowMoreButtonText": event.get("buttonText"),
                "knowMoreButtonPayload": event.get("buttonPayload"),
                "currentLeadStatus": "KNOW_MORE_CLICKED",
                "updateTime": now,
            }
        }
    )

    send_result = send_whatsapp_template(
        phone=phone,
        template_name=TEMPLATE_INVITE,
        name=lead_name
    )

    retry_sent = bool(send_result.get("success"))
    retry_wa_message_id = extract_wa_message_id(send_result)

    now = int(time.time() * 1000)

    campaign_recipients.update_one(
        {
            "_id": recipient["_id"]
        },
        {
            "$set": {
                "retryMarketingInviteTemplateName": TEMPLATE_INVITE,
                "retryMarketingInviteStatus": "SENT" if retry_sent else "FAILED",
                "retryMarketingInviteSentAt": now if retry_sent else None,
                "retryMarketingInviteWaMessageId": retry_wa_message_id,
                "retryMarketingInviteError": None if retry_sent else send_result.get("error"),
                "retryMarketingInviteApiResponse": send_result.get("response"),
                "currentLeadStatus": (
                    "RETRY_MARKETING_INVITE_SENT"
                    if retry_sent
                    else "RETRY_MARKETING_INVITE_FAILED"
                ),
                "updateTime": now,
            }
        }
    )

    whatsapp_message_logs.insert_one(
        {
            "phone": phone,
            "name": lead_name,
            "campaignName": DEFAULT_CAMPAIGN_NAME,
            "direction": "OUTBOUND",
            "templateName": TEMPLATE_INVITE,
            "messagePurpose": "RETRY_MARKETING_INVITE_AFTER_KNOW_MORE",
            "waMessageId": retry_wa_message_id,
            "status": "SENT" if retry_sent else "FAILED",
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

    campaign_recipients = get_collection("campaign_recipients")

    recipient = campaign_recipients.find_one(
        {
            "phone": phone,
            "campaignName": DEFAULT_CAMPAIGN_NAME,
        }
    )

    logger.critical("recipient_data======>{}", recipient)

    if not recipient:
        logger.warning(
            "No campaign recipient found for phone={} campaign={}",
            phone,
            DEFAULT_CAMPAIGN_NAME
        )
        return

    # ==================================================
    # Know More is not a final response.
    # It should NOT lock the user response.
    # It only retries sending the marketing invitation.
    # ==================================================

    if button_action.get("actionType") == "RETRY_MARKETING_INVITE":
        process_know_more_click(event, recipient)
        return

    # ==================================================
    # Final response starts here.
    # Only Yes / Talk to Counselor should lock response.
    # ==================================================

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
                "followupTemplateApiResponse": send_result.get("response"),
                "followupTemplateError": send_result.get("error"),
                "followupRetryRequired": not template_sent,
                "updateTime": now,
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
            "createTime": now,
            "updateTime": now,
        }
    )
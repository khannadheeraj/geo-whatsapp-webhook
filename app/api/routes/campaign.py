# import logging
# import time

# from fastapi import APIRouter, HTTPException

# from app.config import (
#     DEFAULT_CAMPAIGN_NAME,
#     TEMPLATE_INVITE,
# )
# from app.db.mongodb import get_collection
# from app.schemas.campaign_schema import CampaignInviteRequestModel
# from app.services.whatsapp_sender import send_whatsapp_template
# from app.utils.phone_utils import clean_phone_number
# import time


# logger = logging.getLogger("whatsapp-webhook")

# router = APIRouter(
#     prefix="/campaigns",
#     tags=["Campaigns"]
# )


# @router.post("/upsc-orientation/send-invite")
# async def send_upsc_orientation_invite(
#     payload: CampaignInviteRequestModel
# ):

#     try:
#         campaign_recipients = get_collection("campaign_recipients")
#         whatsapp_message_logs = get_collection("whatsapp_message_logs")

#         results = []

#         for lead in payload.leads:

#             name = lead.name.strip()
#             phone = clean_phone_number(lead.phone)

#             if not name or not phone:
#                 results.append(
#                     {
#                         "name": lead.name,
#                         "phone": lead.phone,
#                         "success": False,
#                         "message": "Name and phone are required"
#                     }
#                 )
#                 continue

#             # ==========================================
#             # Upsert Campaign Recipient
#             # ==========================================

#             campaign_recipients.update_one(
#                 {
#                     "phone": phone,
#                     "campaignName": DEFAULT_CAMPAIGN_NAME
#                 },
#                 {
#                     "$set": {
#                         "name": name,
#                         "phone": phone,
#                         "campaignName": DEFAULT_CAMPAIGN_NAME,
#                         "initialTemplateName": TEMPLATE_INVITE,
#                         "updateTime":  int(time.time() * 1000),
#                     },
#                     "$setOnInsert": {
#                         "initialTemplateStatus": "PENDING",
#                         "responseLocked": False,
#                         "firstButtonClicked": None,
#                         "buttonPayload": None,
#                         "normalizedResponse": "NO_RESPONSE",
#                         "currentLeadStatus": "INVITE_PENDING",
#                         "followupTemplateToSend": None,
#                         "followupTemplateSent": None,
#                         "followupTemplateStatus": None,
#                         "followupTemplateSentAt": None,
#                         "responseAt": None,
#                         "createTime":  int(time.time() * 1000),
#                     }
#                 },
#                 upsert=True
#             )

#             # ==========================================
#             # Send WhatsApp Invite Template
#             # ==========================================

#             send_result = send_whatsapp_template(
#                 phone=phone,
#                 template_name=TEMPLATE_INVITE,
#                 name=name
#             )

#             if send_result.get("success"):

#                 wa_message_id = None

#                 try:
#                     wa_message_id = (
#                         send_result
#                         .get("response", {})
#                         .get("messages", [{}])[0]
#                         .get("id")
#                     )
#                 except Exception:
#                     wa_message_id = None

#                 campaign_recipients.update_one(
#                     {
#                         "phone": phone,
#                         "campaignName": DEFAULT_CAMPAIGN_NAME
#                     },
#                     {
#                         "$set": {
#                             "initialTemplateStatus": "SENT",
#                             "initialTemplateSentAt":  int(time.time() * 1000),
#                             "initialWaMessageId": wa_message_id,
#                             "currentLeadStatus": "INVITE_SENT",
#                             "updateTime":  int(time.time() * 1000),
#                         }
#                     }
#                 )

#                 whatsapp_message_logs.insert_one(
#                     {
#                         "phone": phone,
#                         "name": name,
#                         "campaignName": DEFAULT_CAMPAIGN_NAME,
#                         "direction": "OUTBOUND",
#                         "templateName": TEMPLATE_INVITE,
#                         "waMessageId": wa_message_id,
#                         "status": "SENT",
#                         "apiResponse": send_result.get("response"),
#                         "createTime":  int(time.time() * 1000),
#                         "updateTime":  int(time.time() * 1000),
#                     }
#                 )

#                 results.append(
#                     {
#                         "name": name,
#                         "phone": phone,
#                         "success": True,
#                         "message": "Invite sent successfully",
#                         "waMessageId": wa_message_id
#                     }
#                 )

#             else:

#                 campaign_recipients.update_one(
#                     {
#                         "phone": phone,
#                         "campaignName": DEFAULT_CAMPAIGN_NAME
#                     },
#                     {
#                         "$set": {
#                             "initialTemplateStatus": "FAILED",
#                             "initialTemplateError": send_result.get("error"),
#                             "initialTemplateApiResponse": send_result.get("response"),
#                             "currentLeadStatus": "INVITE_FAILED",
#                             "updateTime":  int(time.time() * 1000),
#                         }
#                     }
#                 )

#                 whatsapp_message_logs.insert_one(
#                     {
#                         "phone": phone,
#                         "name": name,
#                         "campaignName": DEFAULT_CAMPAIGN_NAME,
#                         "direction": "OUTBOUND",
#                         "templateName": TEMPLATE_INVITE,
#                         "status": "FAILED",
#                         "error": send_result.get("error"),
#                         "apiResponse": send_result.get("response"),
#                         "createTime":  int(time.time() * 1000),
#                         "updateTime":  int(time.time() * 1000),
#                     }
#                 )

#                 results.append(
#                     {
#                         "name": name,
#                         "phone": phone,
#                         "success": False,
#                         "message": "Failed to send invite",
#                         "error": send_result.get("error"),
#                         "apiResponse": send_result.get("response")
#                     }
#                 )

#         return {
#             "success": True,
#             "campaignName": DEFAULT_CAMPAIGN_NAME,
#             "templateName": TEMPLATE_INVITE,
#             "total": len(payload.leads),
#             "sent": len([r for r in results if r.get("success")]),
#             "failed": len([r for r in results if not r.get("success")]),
#             "results": results
#         }

#     except Exception as e:

#         logger.exception(
#             "Failed to send UPSC orientation invite: %s",
#             str(e)
#         )

#         raise HTTPException(
#             status_code=500,
#             detail="Something went wrong while sending invite"
#         )

# ==================================================================================================================================================================================================================================================================================================================================

import logging
import time

from fastapi import APIRouter, HTTPException

from app.config import (
    DEFAULT_CAMPAIGN_NAME,
    TEMPLATE_INVITE,
    TEMPLATE_INVITE_FALLBACK_UTILITY,
)
from app.db.mongodb import get_collection
from app.schemas.campaign_schema import CampaignInviteRequestModel
from app.services.whatsapp_sender import send_whatsapp_template
from app.utils.phone_utils import clean_phone_number


# logger = logging.getLogger("whatsapp-webhook")

from loguru import logger



router = APIRouter(
    prefix="/campaigns",
    tags=["Campaigns"]
)


def extract_wa_message_id(send_result: dict):
    
    try:
        return ( send_result .get("response", {}) .get("messages", [{}])[0] .get("id"))
    except Exception:
        return None


@router.post("/upsc-orientation/send-invite")
async def send_upsc_orientation_invite(
    payload: CampaignInviteRequestModel
):
    try:
        campaign_recipients = get_collection("campaign_recipients")
        whatsapp_message_logs = get_collection("whatsapp_message_logs")

        results = []

        for lead in payload.leads:
            now = int(time.time() * 1000)

            name = lead.name.strip()
            phone = clean_phone_number(lead.phone)

            if not name or not phone:
                results.append(
                    {
                        "name": lead.name,
                        "phone": lead.phone,
                        "success": False,
                        "message": "Name and phone are required"
                    }
                )
                continue

            # ==========================================
            # Optional safety: skip if user already gave final response
            # ==========================================

            existing_recipient = campaign_recipients.find_one(
                {
                    "phone": phone,
                    "campaignName": DEFAULT_CAMPAIGN_NAME
                }
            )

            if existing_recipient and existing_recipient.get("responseLocked") is True:
                results.append(
                    {
                        "name": name,
                        "phone": phone,
                        "success": True,
                        "skipped": True,
                        "message": "Recipient already responded. Invite not resent.",
                        "currentLeadStatus": existing_recipient.get("currentLeadStatus"),
                        "normalizedResponse": existing_recipient.get("normalizedResponse"),
                    }
                )
                continue

            # ==========================================
            # Upsert Campaign Recipient
            # ==========================================

            campaign_recipients.update_one(
                {
                    "phone": phone,
                    "campaignName": DEFAULT_CAMPAIGN_NAME
                },
                {
                    "$set": {
                        "name": name,
                        "phone": phone,
                        "campaignName": DEFAULT_CAMPAIGN_NAME,
                        "initialTemplateName": TEMPLATE_INVITE,
                        "updateTime": now,
                    },
                    "$setOnInsert": {
                        "initialTemplateStatus": "PENDING",
                        "responseLocked": False,
                        "firstButtonClicked": None,
                        "buttonPayload": None,
                        "normalizedResponse": "NO_RESPONSE",
                        "currentLeadStatus": "INVITE_PENDING",
                        "followupTemplateToSend": None,
                        "followupTemplateSent": None,
                        "followupTemplateStatus": None,
                        "followupTemplateSentAt": None,
                        "responseAt": None,

                        # fallback utility fields
                        "fallbackUtilityRequired": False,
                        "fallbackUtilityTemplateName": None,
                        "fallbackUtilityStatus": None,
                        "fallbackUtilitySentAt": None,
                        "fallbackUtilityWaMessageId": None,
                        "fallbackUtilityError": None,
                        "fallbackUtilityApiResponse": None,

                        # know more retry fields
                        "knowMoreClicked": False,
                        "knowMoreClickedAt": None,
                        "retryMarketingInviteTemplateName": None,
                        "retryMarketingInviteStatus": None,
                        "retryMarketingInviteSentAt": None,
                        "retryMarketingInviteWaMessageId": None,
                        "retryMarketingInviteError": None,
                        "retryMarketingInviteApiResponse": None,

                        "createTime": now,
                    }
                },
                upsert=True
            )

            # ==========================================
            # First Try: Send Marketing Invite Template
            # ==========================================

            send_result = send_whatsapp_template(
                phone=phone,
                template_name=TEMPLATE_INVITE,
                name=name
            )

            if send_result.get("success"):
                wa_message_id = extract_wa_message_id(send_result)
                now = int(time.time() * 1000)

                campaign_recipients.update_one(
                    {
                        "phone": phone,
                        "campaignName": DEFAULT_CAMPAIGN_NAME
                    },
                    {
                        "$set": {
                            "initialTemplateStatus": "SENT",
                            "initialTemplateSentAt": now,
                            "initialWaMessageId": wa_message_id,
                            "initialTemplateError": None,
                            "initialTemplateApiResponse": send_result.get("response"),
                            "currentLeadStatus": "MARKETING_INVITE_SENT",
                            "updateTime": now,
                        }
                    }
                )

                whatsapp_message_logs.insert_one(
                    {
                        "phone": phone,
                        "name": name,
                        "campaignName": DEFAULT_CAMPAIGN_NAME,
                        "direction": "OUTBOUND",
                        "templateName": TEMPLATE_INVITE,
                        "messagePurpose": "INITIAL_MARKETING_INVITE",
                        "waMessageId": wa_message_id,
                        "status": "SENT",
                        "apiResponse": send_result.get("response"),
                        "error": None,
                        "createTime": now,
                        "updateTime": now,
                    }
                )

                results.append(
                    {
                        "name": name,
                        "phone": phone,
                        "success": True,
                        "message": "Marketing invite sent successfully",
                        "waMessageId": wa_message_id
                    }
                )

                continue

            # ==========================================
            # If Marketing Invite Failed: Save Failure
            # ==========================================

            now = int(time.time() * 1000)

            campaign_recipients.update_one(
                {
                    "phone": phone,
                    "campaignName": DEFAULT_CAMPAIGN_NAME
                },
                {
                    "$set": {
                        "initialTemplateStatus": "FAILED",
                        "initialTemplateError": send_result.get("error"),
                        "initialTemplateApiResponse": send_result.get("response"),
                        "currentLeadStatus": "MARKETING_INVITE_FAILED",
                        "fallbackUtilityRequired": True,
                        "updateTime": now,
                    }
                }
            )

            whatsapp_message_logs.insert_one(
                {
                    "phone": phone,
                    "name": name,
                    "campaignName": DEFAULT_CAMPAIGN_NAME,
                    "direction": "OUTBOUND",
                    "templateName": TEMPLATE_INVITE,
                    "messagePurpose": "INITIAL_MARKETING_INVITE",
                    "status": "FAILED",
                    "waMessageId": None,
                    "error": send_result.get("error"),
                    "apiResponse": send_result.get("response"),
                    "createTime": now,
                    "updateTime": now,
                }
            )

            # ==========================================
            # Send Utility Fallback Template
            # ==========================================

            fallback_send_result = send_whatsapp_template(
                phone=phone,
                template_name=TEMPLATE_INVITE_FALLBACK_UTILITY,
                name=name
            )

            fallback_sent = bool(fallback_send_result.get("success"))
            fallback_wa_message_id = extract_wa_message_id(fallback_send_result)

            now = int(time.time() * 1000)

            campaign_recipients.update_one(
                {
                    "phone": phone,
                    "campaignName": DEFAULT_CAMPAIGN_NAME
                },
                {
                    "$set": {
                        "fallbackUtilityTemplateName": TEMPLATE_INVITE_FALLBACK_UTILITY,
                        "fallbackUtilityStatus": "SENT" if fallback_sent else "FAILED",
                        "fallbackUtilitySentAt": now if fallback_sent else None,
                        "fallbackUtilityWaMessageId": fallback_wa_message_id,
                        "fallbackUtilityError": None if fallback_sent else fallback_send_result.get("error"),
                        "fallbackUtilityApiResponse": fallback_send_result.get("response"),
                        "currentLeadStatus": (
                            "UTILITY_FALLBACK_SENT"
                            if fallback_sent
                            else "MARKETING_INVITE_AND_UTILITY_FAILED"
                        ),
                        "updateTime": now,
                    }
                }
            )

            whatsapp_message_logs.insert_one(
                {
                    "phone": phone,
                    "name": name,
                    "campaignName": DEFAULT_CAMPAIGN_NAME,
                    "direction": "OUTBOUND",
                    "templateName": TEMPLATE_INVITE_FALLBACK_UTILITY,
                    "messagePurpose": "UTILITY_FALLBACK_AFTER_MARKETING_INVITE_FAILED",
                    "waMessageId": fallback_wa_message_id,
                    "status": "SENT" if fallback_sent else "FAILED",
                    "error": fallback_send_result.get("error"),
                    "apiResponse": fallback_send_result.get("response"),
                    "createTime": now,
                    "updateTime": now,
                }
            )

            results.append(
                {
                    "name": name,
                    "phone": phone,
                    "success": fallback_sent,
                    "message": (
                        "Marketing invite failed, utility fallback sent"
                        if fallback_sent
                        else "Marketing invite and utility fallback both failed"
                    ),
                    "initialMarketingInvite": {
                        "templateName": TEMPLATE_INVITE,
                        "success": False,
                        "error": send_result.get("error"),
                        "apiResponse": send_result.get("response"),
                    },
                    "utilityFallback": {
                        "templateName": TEMPLATE_INVITE_FALLBACK_UTILITY,
                        "success": fallback_sent,
                        "waMessageId": fallback_wa_message_id,
                        "error": fallback_send_result.get("error"),
                        "apiResponse": fallback_send_result.get("response"),
                    }
                }
            )

        sent_count = len([
            r for r in results
            if r.get("success") and not r.get("skipped")
        ])

        skipped_count = len([
            r for r in results
            if r.get("skipped")
        ])

        failed_count = len([
            r for r in results
            if not r.get("success")
        ])

        return {
            "success": True,
            "campaignName": DEFAULT_CAMPAIGN_NAME,
            "initialMarketingTemplate": TEMPLATE_INVITE,
            "fallbackUtilityTemplate": TEMPLATE_INVITE_FALLBACK_UTILITY,
            "total": len(payload.leads),
            "sent": sent_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "results": results
        }

    except Exception as e:
        logger.exception(
            "Failed to send UPSC orientation invite: %s",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Something went wrong while sending invite"
        )
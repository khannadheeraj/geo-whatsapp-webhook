import logging

from fastapi import APIRouter, HTTPException

from app.config import (
    DEFAULT_CAMPAIGN_NAME,
    TEMPLATE_INVITE,
)
from app.db.mongodb import get_collection
from app.schemas.campaign_schema import CampaignInviteRequestModel
from app.services.whatsapp_sender import send_whatsapp_template
from app.utils.phone_utils import clean_phone_number
from app.utils.time_utils import now_utc


logger = logging.getLogger("whatsapp-webhook")

router = APIRouter(
    prefix="/campaigns",
    tags=["Campaigns"]
)


@router.post("/upsc-orientation/send-invite")
async def send_upsc_orientation_invite(
    payload: CampaignInviteRequestModel
):

    try:
        campaign_recipients = get_collection("campaign_recipients")
        whatsapp_message_logs = get_collection("whatsapp_message_logs")

        results = []

        for lead in payload.leads:

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
                        "updatedAt": now_utc(),
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
                        "createdAt": now_utc(),
                    }
                },
                upsert=True
            )

            # ==========================================
            # Send WhatsApp Invite Template
            # ==========================================

            send_result = send_whatsapp_template(
                phone=phone,
                template_name=TEMPLATE_INVITE,
                name=name
            )

            if send_result.get("success"):

                wa_message_id = None

                try:
                    wa_message_id = (
                        send_result
                        .get("response", {})
                        .get("messages", [{}])[0]
                        .get("id")
                    )
                except Exception:
                    wa_message_id = None

                campaign_recipients.update_one(
                    {
                        "phone": phone,
                        "campaignName": DEFAULT_CAMPAIGN_NAME
                    },
                    {
                        "$set": {
                            "initialTemplateStatus": "SENT",
                            "initialTemplateSentAt": now_utc(),
                            "initialWaMessageId": wa_message_id,
                            "currentLeadStatus": "INVITE_SENT",
                            "updatedAt": now_utc(),
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
                        "waMessageId": wa_message_id,
                        "status": "SENT",
                        "apiResponse": send_result.get("response"),
                        "createdAt": now_utc(),
                        "updatedAt": now_utc(),
                    }
                )

                results.append(
                    {
                        "name": name,
                        "phone": phone,
                        "success": True,
                        "message": "Invite sent successfully",
                        "waMessageId": wa_message_id
                    }
                )

            else:

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
                            "currentLeadStatus": "INVITE_FAILED",
                            "updatedAt": now_utc(),
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
                        "status": "FAILED",
                        "error": send_result.get("error"),
                        "apiResponse": send_result.get("response"),
                        "createdAt": now_utc(),
                        "updatedAt": now_utc(),
                    }
                )

                results.append(
                    {
                        "name": name,
                        "phone": phone,
                        "success": False,
                        "message": "Failed to send invite",
                        "error": send_result.get("error"),
                        "apiResponse": send_result.get("response")
                    }
                )

        return {
            "success": True,
            "campaignName": DEFAULT_CAMPAIGN_NAME,
            "templateName": TEMPLATE_INVITE,
            "total": len(payload.leads),
            "sent": len([r for r in results if r.get("success")]),
            "failed": len([r for r in results if not r.get("success")]),
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
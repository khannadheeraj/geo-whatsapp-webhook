import logging
import time

from fastapi import APIRouter, HTTPException

# from app.config import (
#     DEFAULT_CAMPAIGN_NAME,
#     TEMPLATE_INVITE,
#     TEMPLATE_FINAL_DAY_REMINDER,
#     SCHOLARSHIP_MOCK_TEST_CAMPAIGN_NAME,
#     TEMPLATE_SCHOLARSHIP_MOCK_TEST,
# )

from app.config import (
    DEFAULT_CAMPAIGN_NAME,
    TEMPLATE_INVITE,
    TEMPLATE_FINAL_DAY_REMINDER,
    SCHOLARSHIP_MOCK_TEST_CAMPAIGN_NAME,
    TEMPLATE_SCHOLARSHIP_MOCK_TEST,
    FREE_DEMO_CLASS_CAMPAIGN_NAME,
    TEMPLATE_FREE_DEMO_CLASS_INVITATION,
    FREE_DEMO_CLASS_TEMPLATE_DISPLAY_NAME,
    TEMPLATE_UPSC_DEMO_CLASS_REMINDER
)
from app.db.mongodb import get_collection
from app.schemas.campaign_schema import (
    CampaignInviteRequestModel,
    UpscFoundationAdmissionOpenRequestModel,
)
from app.services.whatsapp_sender import send_whatsapp_template
from app.utils.phone_utils import clean_phone_number


logger = logging.getLogger("whatsapp-webhook")

router = APIRouter(
    prefix="/campaigns",
    tags=["Campaigns"]
)


def extract_wa_message_id(send_result: dict):
    try:
        return (
            send_result
            .get("response", {})
            .get("messages", [{}])[0]
            .get("id")
        )
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
                        "createTime": now,
                    }
                },
                upsert=True
            )

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
                            "currentLeadStatus": "INVITE_SENT",
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
                        "message": "Invite sent successfully",
                        "waMessageId": wa_message_id
                    }
                )

            else:

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
                            "currentLeadStatus": "INVITE_FAILED",
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


@router.post("/upsc-orientation/send-final-day-reminder")
async def send_final_day_reminder(
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
            # Upsert / Update Campaign Recipient
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
                        "finalDayReminderTemplateName": TEMPLATE_FINAL_DAY_REMINDER,
                        "updateTime": now,
                    },
                    "$setOnInsert": {
                        "responseLocked": False,
                        "firstButtonClicked": None,
                        "buttonPayload": None,
                        "normalizedResponse": "NO_RESPONSE",
                        "currentLeadStatus": "FINAL_DAY_REMINDER_PENDING",
                        "responseAt": None,
                        "createTime": now,
                    }
                },
                upsert=True
            )

            # ==========================================
            # Avoid duplicate final-day reminder
            # ==========================================

            existing_recipient = campaign_recipients.find_one(
                {
                    "phone": phone,
                    "campaignName": DEFAULT_CAMPAIGN_NAME
                }
            )

            if existing_recipient and existing_recipient.get("finalDayReminderStatus") == "SENT":
                results.append(
                    {
                        "name": name,
                        "phone": phone,
                        "success": True,
                        "skipped": True,
                        "message": "Final day reminder already sent",
                        "waMessageId": existing_recipient.get("finalDayReminderWaMessageId")
                    }
                )
                continue

            # ==========================================
            # Send appointment_reminder_2
            # It has 1 variable: {{1}} = name
            # ==========================================

            send_result = send_whatsapp_template(
                phone=phone,
                template_name=TEMPLATE_FINAL_DAY_REMINDER,
                name=name
            )

            reminder_sent = bool(send_result.get("success"))
            wa_message_id = extract_wa_message_id(send_result)

            now = int(time.time() * 1000)

            campaign_recipients.update_one(
                {
                    "phone": phone,
                    "campaignName": DEFAULT_CAMPAIGN_NAME
                },
                {
                    "$set": {
                        "finalDayReminderTemplateName": TEMPLATE_FINAL_DAY_REMINDER,
                        "finalDayReminderStatus": "SENT" if reminder_sent else "FAILED",
                        "finalDayReminderSentAt": now if reminder_sent else None,
                        "finalDayReminderWaMessageId": wa_message_id,
                        "finalDayReminderError": None if reminder_sent else send_result.get("error"),
                        "finalDayReminderApiResponse": send_result.get("response"),

                        "finalDayReminderClickedButtons": [],
                        "finalDayReminderClickedActions": [],
                        "finalDayReminderClickCount": 0,
                        "finalDayReminderLastClickedButton": None,
                        "finalDayReminderLastClickedAction": None,
                        "finalDayReminderLastClickedAt": None,

                        "currentLeadStatus": (
                            "FINAL_DAY_REMINDER_SENT"
                            if reminder_sent
                            else "FINAL_DAY_REMINDER_FAILED"
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
                    "templateName": TEMPLATE_FINAL_DAY_REMINDER,
                    "messagePurpose": "FINAL_DAY_UTILITY_REMINDER",
                    "waMessageId": wa_message_id,
                    "status": "SENT" if reminder_sent else "FAILED",
                    "apiResponse": send_result.get("response"),
                    "error": send_result.get("error"),
                    "createTime": now,
                    "updateTime": now,
                }
            )

            results.append(
                {
                    "name": name,
                    "phone": phone,
                    "success": reminder_sent,
                    "message": (
                        "Final day reminder sent"
                        if reminder_sent
                        else "Final day reminder failed"
                    ),
                    "waMessageId": wa_message_id,
                    "error": send_result.get("error"),
                    "apiResponse": send_result.get("response"),
                }
            )

        sent_count = len(
            [
                r for r in results
                if r.get("success") and not r.get("skipped")
            ]
        )

        skipped_count = len(
            [
                r for r in results
                if r.get("skipped")
            ]
        )

        failed_count = len(
            [
                r for r in results
                if not r.get("success")
            ]
        )

        return {
            "success": True,
            "campaignName": DEFAULT_CAMPAIGN_NAME,
            "templateName": TEMPLATE_FINAL_DAY_REMINDER,
            "total": len(payload.leads),
            "sent": sent_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "results": results
        }

    except Exception as e:
        logger.exception(
            "Failed to send final day reminder: %s",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Something went wrong while sending final day reminder"
        )

        failed_count = len(
            [
                r for r in results
                if not r.get("success")
            ]
        )

        return {
            "success": True,
            "campaignName": DEFAULT_CAMPAIGN_NAME,
            "templateName": TEMPLATE_FINAL_DAY_REMINDER,
            "total": len(results),
            "sent": sent_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "results": results
        }

    except Exception as e:

        logger.exception(
            "Failed to send final day reminder: %s",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Something went wrong while sending final day reminder"
        )


@router.post("/upsc-foundation/send-admission-open")
async def send_upsc_foundation_admission_open(
    payload: UpscFoundationAdmissionOpenRequestModel
):
    try:
        campaign_recipients = get_collection("campaign_recipients")
        whatsapp_message_logs = get_collection("whatsapp_message_logs")


        results = []
        campaign_name = payload.campaignName.strip()

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

            existing_recipient = campaign_recipients.find_one(
                {
                    "phone": phone,
                    "campaignName": campaign_name
                }
            )

            if (
                existing_recipient
                and existing_recipient.get("foundationAdmissionOpenStatus") == "SENT"
            ):
                results.append(
                    {
                        "name": name,
                        "phone": phone,
                        "success": True,
                        "skipped": True,
                        "message": "UPSC foundation admission open template already sent",
                        "waMessageId": existing_recipient.get("foundationAdmissionOpenWaMessageId")
                    }
                )
                continue

            campaign_recipients.update_one(
                {
                    "phone": phone,
                    "campaignName": campaign_name
                },
                {
                    "$set": {
                        "name": name,
                        "phone": phone,
                        "campaignName": campaign_name,

                        "foundationAdmissionOpenTemplateName": TEMPLATE_UPSC_FOUNDATION_ADMISSION_OPEN,
                        "foundationAdmissionOpenAdmissionFrom": payload.admissionOpenFrom,
                        "foundationAdmissionOpenAdmissionTo": payload.admissionOpenTo,
                        "foundationAdmissionOpenClassesStart": payload.classesStart,

                        "updateTime": now,
                    },
                    "$setOnInsert": {
                        "responseLocked": False,
                        "firstButtonClicked": None,
                        "buttonPayload": None,
                        "normalizedResponse": "NO_RESPONSE",
                        "currentLeadStatus": "UPSC_FOUNDATION_ADMISSION_OPEN_PENDING",
                        "responseAt": None,
                        "createTime": now,
                    }
                },
                upsert=True
            )

            send_result = send_whatsapp_template(
                phone=phone,
                template_name=TEMPLATE_UPSC_FOUNDATION_ADMISSION_OPEN,
                body_parameters=[
                    name,
                    payload.admissionOpenFrom,
                    payload.admissionOpenTo,
                    payload.classesStart,
                ]
            )

            template_sent = bool(send_result.get("success"))
            wa_message_id = extract_wa_message_id(send_result)

            now = int(time.time() * 1000)

            campaign_recipients.update_one(
                {
                    "phone": phone,
                    "campaignName": campaign_name
                },
                {
                    "$set": {
                        "foundationAdmissionOpenStatus": "SENT" if template_sent else "FAILED",
                        "foundationAdmissionOpenSentAt": now if template_sent else None,
                        "foundationAdmissionOpenWaMessageId": wa_message_id,
                        "foundationAdmissionOpenError": None if template_sent else send_result.get("error"),
                        "foundationAdmissionOpenApiResponse": send_result.get("response"),

                        "foundationAdmissionOpenTalkCounselorClicked": False,
                        "foundationAdmissionOpenTalkCounselorClickedAt": None,
                        "foundationAdmissionOpenTalkCounselorButtonText": None,
                        "foundationAdmissionOpenTalkCounselorButtonPayload": None,

                        "currentLeadStatus": (
                            "UPSC_FOUNDATION_ADMISSION_OPEN_SENT"
                            if template_sent
                            else "UPSC_FOUNDATION_ADMISSION_OPEN_FAILED"
                        ),
                        "updateTime": now,
                    }
                }
            )

            whatsapp_message_logs.insert_one(
                {
                    "phone": phone,
                    "name": name,
                    "campaignName": campaign_name,
                    "direction": "OUTBOUND",
                    "templateName": TEMPLATE_UPSC_FOUNDATION_ADMISSION_OPEN,
                    "messagePurpose": "UPSC_FOUNDATION_ADMISSION_OPEN",
                    "waMessageId": wa_message_id,
                    "status": "SENT" if template_sent else "FAILED",
                    "apiResponse": send_result.get("response"),
                    "error": send_result.get("error"),
                    "templateVariables": {
                        "name": name,
                        "admissionOpenFrom": payload.admissionOpenFrom,
                        "admissionOpenTo": payload.admissionOpenTo,
                        "classesStart": payload.classesStart,
                    },
                    "createTime": now,
                    "updateTime": now,
                }
            )

            results.append(
                {
                    "name": name,
                    "phone": phone,
                    "success": template_sent,
                    "message": (
                        "UPSC foundation admission open template sent"
                        if template_sent
                        else "UPSC foundation admission open template failed"
                    ),
                    "waMessageId": wa_message_id,
                    "error": send_result.get("error"),
                    "apiResponse": send_result.get("response"),
                }
            )

        sent_count = len(
            [
                r for r in results
                if r.get("success") and not r.get("skipped")
            ]
        )

        skipped_count = len(
            [
                r for r in results
                if r.get("skipped")
            ]
        )

        failed_count = len(
            [
                r for r in results
                if not r.get("success")
            ]
        )

        return {
            "success": True,
            "campaignName": campaign_name,
            "templateName": TEMPLATE_UPSC_FOUNDATION_ADMISSION_OPEN,
            "total": len(payload.leads),
            "sent": sent_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "results": results
        }

    except Exception as e:
        logger.exception(
            "Failed to send UPSC foundation admission open template: %s",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Something went wrong while sending UPSC foundation admission open template"
        )


@router.post("/upsc-scholarship-mock-test/send-invite")
async def send_scholarship_mock_test_invite(
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

            campaign_recipients.update_one(
                {
                    "phone": phone,
                    "campaignName": SCHOLARSHIP_MOCK_TEST_CAMPAIGN_NAME
                },
                {
                    "$set": {
                        "name": name,
                        "phone": phone,
                        "campaignName": SCHOLARSHIP_MOCK_TEST_CAMPAIGN_NAME,
                        "scholarshipTemplateName": TEMPLATE_SCHOLARSHIP_MOCK_TEST,
                        "updateTime": now,
                    },
                    "$setOnInsert": {
                        "scholarshipInviteStatus": "PENDING",
                        "currentLeadStatus": "SCHOLARSHIP_INVITE_PENDING",

                        "scholarshipClickedButtons": [],
                        "scholarshipClickedActions": [],
                        "scholarshipClickCount": 0,
                        "scholarshipLastClickedButton": None,
                        "scholarshipLastClickedAction": None,
                        "scholarshipLastClickedAt": None,

                        "lastTextMessage": None,
                        "lastTextMessageAt": None,
                        "textMessageCount": 0,

                        "createTime": now,
                    }
                },
                upsert=True
            )

            # Template has 1 variable: {{1}} = name / Aspirant
            send_result = send_whatsapp_template(
                phone=phone,
                template_name=TEMPLATE_SCHOLARSHIP_MOCK_TEST,
                name=name
            )

            invite_sent = bool(send_result.get("success"))
            wa_message_id = extract_wa_message_id(send_result)

            now = int(time.time() * 1000)

            campaign_recipients.update_one(
                {
                    "phone": phone,
                    "campaignName": SCHOLARSHIP_MOCK_TEST_CAMPAIGN_NAME
                },
                {
                    "$set": {
                        "scholarshipInviteStatus": "SENT" if invite_sent else "FAILED",
                        "scholarshipInviteSentAt": now if invite_sent else None,
                        "scholarshipInviteWaMessageId": wa_message_id,
                        "scholarshipInviteError": None if invite_sent else send_result.get("error"),
                        "scholarshipInviteApiResponse": send_result.get("response"),
                        "currentLeadStatus": (
                            "SCHOLARSHIP_INVITE_SENT"
                            if invite_sent
                            else "SCHOLARSHIP_INVITE_FAILED"
                        ),
                        "updateTime": now,
                    }
                }
            )

            whatsapp_message_logs.insert_one(
                {
                    "phone": phone,
                    "name": name,
                    "campaignName": SCHOLARSHIP_MOCK_TEST_CAMPAIGN_NAME,
                    "direction": "OUTBOUND",
                    "templateName": TEMPLATE_SCHOLARSHIP_MOCK_TEST,
                    "messagePurpose": "SCHOLARSHIP_MOCK_TEST_INVITE",
                    "waMessageId": wa_message_id,
                    "status": "SENT" if invite_sent else "FAILED",
                    "apiResponse": send_result.get("response"),
                    "error": send_result.get("error"),
                    "createTime": now,
                    "updateTime": now,
                }
            )

            results.append(
                {
                    "name": name,
                    "phone": phone,
                    "success": invite_sent,
                    "message": (
                        "Scholarship mock test invite sent"
                        if invite_sent
                        else "Scholarship mock test invite failed"
                    ),
                    "waMessageId": wa_message_id,
                    "error": send_result.get("error"),
                    "apiResponse": send_result.get("response"),
                }
            )

        sent_count = len([r for r in results if r.get("success")])
        failed_count = len([r for r in results if not r.get("success")])

        return {
            "success": True,
            "campaignName": SCHOLARSHIP_MOCK_TEST_CAMPAIGN_NAME,
            "templateName": TEMPLATE_SCHOLARSHIP_MOCK_TEST,
            "total": len(payload.leads),
            "sent": sent_count,
            "failed": failed_count,
            "results": results
        }

    except Exception as e:
        logger.exception(
            "Failed to send scholarship mock test invite: %s",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Something went wrong while sending scholarship mock test invite"
        )


@router.post("/upsc-free-demo-class/send-invite")
async def send_free_demo_class_invite(
    payload: CampaignInviteRequestModel
):
    try:
        campaign_recipients = get_collection("campaign_recipients")
        whatsapp_message_logs = get_collection("whatsapp_message_logs")

        results = []

        for lead in payload.leads:
            now = int(time.time() * 1000)

            # Real name stored in DB
            db_name = lead.name.strip() if lead.name else "Aspirant"

            # WhatsApp template always receives Aspirant
            template_name_value = FREE_DEMO_CLASS_TEMPLATE_DISPLAY_NAME

            phone = clean_phone_number(lead.phone)

            if not phone:
                results.append(
                    {
                        "name": db_name,
                        "phone": lead.phone,
                        "success": False,
                        "message": "Phone is required"
                    }
                )
                continue

            unsubscribed_users = get_collection("whatsapp_unsubscribed_users")

            existing_unsubscribe = unsubscribed_users.find_one(
                {
                    "phone": phone,
                    "isUnsubscribed": True
                }
            )

            if existing_unsubscribe:
                results.append(
                    {
                        "name": db_name,
                        "templateDisplayNameSent": template_name_value,
                        "phone": phone,
                        "success": False,
                        "skipped": True,
                        "message": "User has unsubscribed"
                    }
                )
                continue

            # ==========================================
            # Upsert campaign recipient
            # ==========================================

            campaign_recipients.update_one(
                {
                    "phone": phone,
                    "campaignName": FREE_DEMO_CLASS_CAMPAIGN_NAME
                },
                {
                    "$set": {
                        "name": db_name,
                        "phone": phone,
                        "campaignName": FREE_DEMO_CLASS_CAMPAIGN_NAME,
                        "freeDemoClassTemplateName": TEMPLATE_FREE_DEMO_CLASS_INVITATION,
                        "templateDisplayNameSent": template_name_value,
                        "updateTime": now,
                    },
                    "$setOnInsert": {
                        "freeDemoClassInviteStatus": "PENDING",
                        "currentLeadStatus": "FREE_DEMO_CLASS_INVITE_PENDING",

                        "freeDemoClassClickedButtons": [],
                        "freeDemoClassClickedActions": [],
                        "freeDemoClassClickCount": 0,
                        "freeDemoClassLastClickedButton": None,
                        "freeDemoClassLastClickedAction": None,
                        "freeDemoClassLastClickedAt": None,

                        "lastTextMessage": None,
                        "lastTextMessageAt": None,
                        "textMessageCount": 0,

                        "createTime": now,
                    }
                },
                upsert=True
            )

            # ==========================================
            # Send template
            # {{1}} = Aspirant
            # ==========================================

            send_result = send_whatsapp_template(
                phone=phone,
                template_name=TEMPLATE_FREE_DEMO_CLASS_INVITATION,
                name=template_name_value
            )

            invite_sent = bool(send_result.get("success"))
            wa_message_id = extract_wa_message_id(send_result)

            now = int(time.time() * 1000)

            campaign_recipients.update_one(
                {
                    "phone": phone,
                    "campaignName": FREE_DEMO_CLASS_CAMPAIGN_NAME
                },
                {
                    "$set": {
                        "freeDemoClassInviteStatus": "SENT" if invite_sent else "FAILED",
                        "freeDemoClassInviteSentAt": now if invite_sent else None,
                        "freeDemoClassInviteWaMessageId": wa_message_id,
                        "freeDemoClassInviteError": None if invite_sent else send_result.get("error"),
                        "freeDemoClassInviteApiResponse": send_result.get("response"),
                        "currentLeadStatus": (
                            "FREE_DEMO_CLASS_INVITE_SENT"
                            if invite_sent
                            else "FREE_DEMO_CLASS_INVITE_FAILED"
                        ),
                        "updateTime": now,
                    }
                }
            )

            whatsapp_message_logs.insert_one(
                {
                    "phone": phone,
                    "name": db_name,
                    "templateDisplayNameSent": template_name_value,
                    "campaignName": FREE_DEMO_CLASS_CAMPAIGN_NAME,
                    "direction": "OUTBOUND",
                    "templateName": TEMPLATE_FREE_DEMO_CLASS_INVITATION,
                    "messagePurpose": "FREE_DEMO_CLASS_INVITE",
                    "waMessageId": wa_message_id,
                    "status": "SENT" if invite_sent else "FAILED",
                    "apiResponse": send_result.get("response"),
                    "error": send_result.get("error"),
                    "createTime": now,
                    "updateTime": now,
                }
            )

            results.append(
                {
                    "name": db_name,
                    "templateDisplayNameSent": template_name_value,
                    "phone": phone,
                    "success": invite_sent,
                    "message": (
                        "Free demo class invite sent"
                        if invite_sent
                        else "Free demo class invite failed"
                    ),
                    "waMessageId": wa_message_id,
                    "error": send_result.get("error"),
                    "apiResponse": send_result.get("response"),
                }
            )

        sent_count = len(
            [
                r for r in results
                if r.get("success") and not r.get("skipped")
            ]
        )

        skipped_count = len(
            [
                r for r in results
                if r.get("skipped")
            ]
        )

        failed_count = len(
            [
                r for r in results
                if not r.get("success") and not r.get("skipped")
            ]
        )

        return {
                "success": True,
                "campaignName": FREE_DEMO_CLASS_CAMPAIGN_NAME,
                "templateName": TEMPLATE_FREE_DEMO_CLASS_INVITATION,
                "templateDisplayNameSent": FREE_DEMO_CLASS_TEMPLATE_DISPLAY_NAME,
                "total": len(payload.leads),
                "sent": sent_count,
                "skipped": skipped_count,
                "failed": failed_count,
                "results": results
            }

    except Exception as e:
        logger.exception(
            "Failed to send free demo class invite: %s",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Something went wrong while sending free demo class invite"
        )


@router.post("/upsc-free-demo-class/send-reminder")
async def send_free_demo_class_reminder(
    payload: CampaignInviteRequestModel
):
    try:
        campaign_recipients = get_collection("campaign_recipients")
        whatsapp_message_logs = get_collection("whatsapp_message_logs")
        unsubscribed_users = get_collection("whatsapp_unsubscribed_users")

        results = []

        for lead in payload.leads:
            now = int(time.time() * 1000)

            # Real name stored in DB
            db_name = lead.name.strip() if lead.name else "Aspirant"

            # WhatsApp template always receives Aspirant
            template_name_value = FREE_DEMO_CLASS_TEMPLATE_DISPLAY_NAME

            phone = clean_phone_number(lead.phone)

            if not phone:
                results.append(
                    {
                        "name": db_name,
                        "phone": lead.phone,
                        "success": False,
                        "message": "Phone is required"
                    }
                )
                continue

            # ==========================================
            # Skip unsubscribed users
            # ==========================================

            existing_unsubscribe = unsubscribed_users.find_one(
                {
                    "phone": phone,
                    "isUnsubscribed": True
                }
            )

            if existing_unsubscribe:
                results.append(
                    {
                        "name": db_name,
                        "templateDisplayNameSent": template_name_value,
                        "phone": phone,
                        "success": False,
                        "skipped": True,
                        "message": "User has unsubscribed"
                    }
                )
                continue

            # ==========================================
            # Upsert / update campaign recipient
            # ==========================================

            campaign_recipients.update_one(
                {
                    "phone": phone,
                    "campaignName": FREE_DEMO_CLASS_CAMPAIGN_NAME
                },
                {
                    "$set": {
                        "name": db_name,
                        "phone": phone,
                        "campaignName": FREE_DEMO_CLASS_CAMPAIGN_NAME,
                        "freeDemoClassReminderTemplateName": TEMPLATE_UPSC_DEMO_CLASS_REMINDER,
                        "freeDemoClassReminderTemplateDisplayNameSent": template_name_value,
                        "updateTime": now,
                    },
                    "$setOnInsert": {
                        "currentLeadStatus": "FREE_DEMO_CLASS_REMINDER_PENDING",

                        "freeDemoClassReminderClickedButtons": [],
                        "freeDemoClassReminderClickedActions": [],
                        "freeDemoClassReminderClickCount": 0,
                        "freeDemoClassReminderLastClickedButton": None,
                        "freeDemoClassReminderLastClickedAction": None,
                        "freeDemoClassReminderLastClickedAt": None,

                        "lastTextMessage": None,
                        "lastTextMessageAt": None,
                        "textMessageCount": 0,

                        "createTime": now,
                    }
                },
                upsert=True
            )

            # ==========================================
            # Avoid duplicate reminder
            # ==========================================

            existing_recipient = campaign_recipients.find_one(
                {
                    "phone": phone,
                    "campaignName": FREE_DEMO_CLASS_CAMPAIGN_NAME
                }
            )

            if (
                existing_recipient
                and existing_recipient.get("freeDemoClassReminderStatus") == "SENT"
            ):
                results.append(
                    {
                        "name": db_name,
                        "templateDisplayNameSent": template_name_value,
                        "phone": phone,
                        "success": True,
                        "skipped": True,
                        "message": "Free demo class reminder already sent",
                        "waMessageId": existing_recipient.get("freeDemoClassReminderWaMessageId")
                    }
                )
                continue

            # ==========================================
            # Send utility reminder template
            # {{1}} = Aspirant
            # ==========================================

            send_result = send_whatsapp_template(
                phone=phone,
                template_name=TEMPLATE_UPSC_DEMO_CLASS_REMINDER,
                name=template_name_value
            )

            reminder_sent = bool(send_result.get("success"))
            wa_message_id = extract_wa_message_id(send_result)

            now = int(time.time() * 1000)

            campaign_recipients.update_one(
                {
                    "phone": phone,
                    "campaignName": FREE_DEMO_CLASS_CAMPAIGN_NAME
                },
                {
                    "$set": {
                        "freeDemoClassReminderStatus": "SENT" if reminder_sent else "FAILED",
                        "freeDemoClassReminderSentAt": now if reminder_sent else None,
                        "freeDemoClassReminderWaMessageId": wa_message_id,
                        "freeDemoClassReminderError": None if reminder_sent else send_result.get("error"),
                        "freeDemoClassReminderApiResponse": send_result.get("response"),

                        "freeDemoClassReminderClickedButtons": [],
                        "freeDemoClassReminderClickedActions": [],
                        "freeDemoClassReminderClickCount": 0,
                        "freeDemoClassReminderLastClickedButton": None,
                        "freeDemoClassReminderLastClickedAction": None,
                        "freeDemoClassReminderLastClickedAt": None,

                        "currentLeadStatus": (
                            "FREE_DEMO_CLASS_REMINDER_SENT"
                            if reminder_sent
                            else "FREE_DEMO_CLASS_REMINDER_FAILED"
                        ),
                        "updateTime": now,
                    }
                }
            )

            whatsapp_message_logs.insert_one(
                {
                    "phone": phone,
                    "name": db_name,
                    "templateDisplayNameSent": template_name_value,
                    "campaignName": FREE_DEMO_CLASS_CAMPAIGN_NAME,
                    "direction": "OUTBOUND",
                    "templateName": TEMPLATE_UPSC_DEMO_CLASS_REMINDER,
                    "messagePurpose": "FREE_DEMO_CLASS_REMINDER",
                    "waMessageId": wa_message_id,
                    "status": "SENT" if reminder_sent else "FAILED",
                    "apiResponse": send_result.get("response"),
                    "error": send_result.get("error"),
                    "createTime": now,
                    "updateTime": now,
                }
            )

            results.append(
                {
                    "name": db_name,
                    "templateDisplayNameSent": template_name_value,
                    "phone": phone,
                    "success": reminder_sent,
                    "message": (
                        "Free demo class reminder sent"
                        if reminder_sent
                        else "Free demo class reminder failed"
                    ),
                    "waMessageId": wa_message_id,
                    "error": send_result.get("error"),
                    "apiResponse": send_result.get("response"),
                }
            )

        sent_count = len(
            [
                r for r in results
                if r.get("success") and not r.get("skipped")
            ]
        )

        skipped_count = len(
            [
                r for r in results
                if r.get("skipped")
            ]
        )

        failed_count = len(
            [
                r for r in results
                if not r.get("success") and not r.get("skipped")
            ]
        )

        return {
            "success": True,
            "campaignName": FREE_DEMO_CLASS_CAMPAIGN_NAME,
            "templateName": TEMPLATE_UPSC_DEMO_CLASS_REMINDER,
            "templateDisplayNameSent": FREE_DEMO_CLASS_TEMPLATE_DISPLAY_NAME,
            "total": len(payload.leads),
            "sent": sent_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "results": results
        }

    except Exception as e:
        logger.exception(
            "Failed to send free demo class reminder: %s",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Something went wrong while sending free demo class reminder"
        )
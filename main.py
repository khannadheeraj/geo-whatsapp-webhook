import os
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List
import requests
from dotenv import load_dotenv

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError
import time
import jwt
import time

from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware




# =========================================================
# Load Environment Variables
# =========================================================

load_dotenv()


# =========================================================
# FastAPI App
# =========================================================

app = FastAPI()


# =========================================================
# CORS Config
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# Logger Config
# =========================================================

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("whatsapp-webhook")


# =========================================================
# Environment Variables
# =========================================================

WHATSAPP_VERIFY_TOKEN = os.getenv(
    "WHATSAPP_VERIFY_TOKEN",
    "geo_ias_whatsapp_verify_token"
)

MONGODB_URI = (
    os.getenv("MONGODB_URI", "")
    .strip()
    .replace('"', "")
    .replace("'", "")
)

ADMIN_USER_EMAIL = os.getenv(
    "ADMIN_USER_EMAIL",
    "admin@gmail.com"
)

ADMIN_USER_PASSWORD = os.getenv(
    "ADMIN_USER_PASSWORD",
    "Admin@123"
)



WHATSAPP_ACCESS_TOKEN = os.getenv(
    "WHATSAPP_ACCESS_TOKEN",
    ""
).strip()

WHATSAPP_PHONE_NUMBER_ID = os.getenv(
    "WHATSAPP_PHONE_NUMBER_ID",
    ""
).strip()

WHATSAPP_GRAPH_API_VERSION = os.getenv(
    "WHATSAPP_GRAPH_API_VERSION",
    "v25.0"
).strip()

DEFAULT_CAMPAIGN_NAME = "upsc_orientation_may31"

TEMPLATE_INVITE = "upsc_orientation_invite_may31"

TEMPLATE_SEAT_CONFIRMED = "upsc_orientation_seat_confirmed_may31"

TEMPLATE_COUNSELLING = "upsc_orientation_counselling_31st"

TEMPLATE_LANGUAGE_CODE = "en_US"


# =========================================================
# MongoDB Globals
# =========================================================

mongo_client = None
db = None


# =========================================================
# Common Helper Functions
# =========================================================

def now_utc():
    return datetime.now(timezone.utc)


def get_collection(collection_name: str) -> Collection:

    if db is None:
        raise RuntimeError("MongoDB is not connected.")

    return db[collection_name]

def clean_phone_number(phone: str) -> str:
    """
    WhatsApp Cloud API expects country code without +.
    Example:
    +91 98765 43210 -> 919876543210
    """

    if not phone:
        return ""

    cleaned = (
        phone.strip()
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )

    return cleaned


def send_whatsapp_template(
    phone: str,
    template_name: str,
    name: str = ""
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

    variable_name = name.strip() if name else "there"

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": TEMPLATE_LANGUAGE_CODE
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "text": variable_name
                        }
                    ]
                }
            ]
        }
    }

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

            logger.error(
                "Failed to send WhatsApp template | phone=%s template=%s response=%s",
                phone,
                template_name,
                response_data
            )

            return {
                "success": False,
                "error": "WHATSAPP_API_ERROR",
                "statusCode": response.status_code,
                "response": response_data
            }

        logger.info(
            "WhatsApp template sent successfully | phone=%s template=%s response=%s",
            phone,
            template_name,
            response_data
        )

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


# =========================================================
# Startup Event
# =========================================================

@app.on_event("startup")
def startup_event():

    global mongo_client, db

    try:

        if not MONGODB_URI:
            logger.warning("MONGODB_URI is not configured.")
            return

        # ==========================================
        # MongoDB Connection
        # ==========================================

        mongo_client = MongoClient(MONGODB_URI)

        # Test MongoDB Connection
        mongo_client.admin.command("ping")

        db = mongo_client["geo_whatsapp"]

        logger.info("MongoDB connected successfully.")

        # ==========================================
        # Admin User Upsert
        # ==========================================

        admin_collection = db["admin_users"]

        admin_collection.update_one(
            {
                "emailId": ADMIN_USER_EMAIL
            },
            {
                "$set": {
                    "emailId": ADMIN_USER_EMAIL,
                    "password": ADMIN_USER_PASSWORD,
                    "updateTime":int(time.time() * 1000),
                },
                "$setOnInsert": {
                    "createTime": int(time.time() * 1000),
                }
            },
            upsert=True
        )

        logger.info("Default admin user initialized successfully.")

    except PyMongoError as e:

        logger.exception(
            "MongoDB connection failed: %s",
            str(e)
        )

    except Exception as e:

        logger.exception(
            "Application startup failed: %s",
            str(e)
        )


# =========================================================
# Shutdown Event
# =========================================================

@app.on_event("shutdown")
def shutdown_event():

    global mongo_client

    if mongo_client:

        mongo_client.close()

        logger.info("MongoDB connection closed.")


# =========================================================
# Extract WhatsApp Events
# =========================================================

def extract_whatsapp_events(
    payload: Dict[str, Any]
) -> List[Dict[str, Any]]:

    extracted_events = []

    entries = payload.get("entry", [])

    for entry in entries:

        changes = entry.get("changes", [])

        for change in changes:

            value = change.get("value", {})

            metadata = value.get("metadata", {})

            phone_number_id = metadata.get("phone_number_id")

            display_phone_number = metadata.get(
                "display_phone_number"
            )

            # ==========================================
            # Incoming Messages
            # ==========================================

            for message in value.get("messages", []):

                message_type = message.get("type")

                text_body = None
                button_text = None
                button_payload = None

                # Normal text message
                if message_type == "text":

                    text_body = (
                        message.get("text", {})
                        .get("body")
                    )

                # Template quick reply button
                elif message_type == "button":

                    button = message.get("button", {})

                    button_text = button.get("text")
                    button_payload = button.get("payload")

                # Interactive button reply
                elif message_type == "interactive":

                    interactive = message.get("interactive", {})
                    interactive_type = interactive.get("type")

                    if interactive_type == "button_reply":

                        button_reply = interactive.get(
                            "button_reply",
                            {}
                        )

                        button_text = button_reply.get("title")
                        button_payload = button_reply.get("id")

                event = {
                    "eventType": "incoming_message",
                    "waMessageId": message.get("id"),
                    "from": message.get("from"),
                    "timestamp": message.get("timestamp"),
                    "messageType": message_type,
                    "text": text_body,
                    "buttonText": button_text,
                    "buttonPayload": button_payload,
                    "phoneNumberId": phone_number_id,
                    "displayPhoneNumber": display_phone_number,
                    "rawMessage": message,
                    "rawValue": value,
                    "createdAt": now_utc(),
                    "updatedAt": now_utc(),
                }

                extracted_events.append(event)

            # ==========================================
            # Message Status Updates
            # ==========================================

            for status in value.get("statuses", []):

                event = {
                    "eventType": "message_status",
                    "waMessageId": status.get("id"),
                    "recipientId": status.get("recipient_id"),
                    "status": status.get("status"),
                    "timestamp": status.get("timestamp"),
                    "conversation": status.get("conversation"),
                    "pricing": status.get("pricing"),
                    "errors": status.get("errors"),
                    "phoneNumberId": phone_number_id,
                    "displayPhoneNumber": display_phone_number,
                    "rawStatus": status,
                    "rawValue": value,
                    "createdAt": now_utc(),
                    "updatedAt": now_utc(),
                }

                extracted_events.append(event)

    return extracted_events




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


def send_whatsapp_template(
    phone: str,
    template_name: str,
    name: str = ""
):

    if not WHATSAPP_ACCESS_TOKEN:
        logger.error("WHATSAPP_ACCESS_TOKEN is not configured.")
        return False

    if not WHATSAPP_PHONE_NUMBER_ID:
        logger.error("WHATSAPP_PHONE_NUMBER_ID is not configured.")
        return False

    url = (
        f"https://graph.facebook.com/"
        f"{WHATSAPP_GRAPH_API_VERSION}/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    # Fallback name if lead name is missing
    template_name_value = name.strip() if name else "there"

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": TEMPLATE_LANGUAGE_CODE
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "text": template_name_value
                        }
                    ]
                }
            ]
        }
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=20
        )

        response_data = response.json()

        if response.status_code >= 400:

            logger.error(
                "Failed to send WhatsApp template | phone=%s template=%s response=%s",
                phone,
                template_name,
                response_data
            )

            return False

        logger.info(
            "WhatsApp template sent successfully | phone=%s template=%s response=%s",
            phone,
            template_name,
            response_data
        )

        # Optional log
        whatsapp_message_logs = get_collection(
            "whatsapp_message_logs"
        )

        whatsapp_message_logs.insert_one(
            {
                "phone": phone,
                "templateName": template_name,
                "direction": "OUTBOUND",
                "requestPayload": payload,
                "responsePayload": response_data,
                "createdAt": now_utc(),
                "updatedAt": now_utc(),
            }
        )

        return True

    except Exception as e:

        logger.exception(
            "Exception while sending WhatsApp template | phone=%s template=%s error=%s",
            phone,
            template_name,
            str(e)
        )

        return False


def process_button_click(event: Dict[str, Any]):

    phone = event.get("from")
    button_text = event.get("buttonText")

    if not phone or not button_text:
        return

    button_action = normalize_button_response(
        button_text
    )

    if not button_action:

        logger.info(
            "Unknown button clicked | phone=%s button=%s",
            phone,
            button_text
        )

        return

    campaign_recipients = get_collection(
        "campaign_recipients"
    )

    recipient = campaign_recipients.find_one(
        {
            "phone": phone,
            "campaignName": DEFAULT_CAMPAIGN_NAME,
        }
    )

    if not recipient:

        logger.warning(
            "No campaign recipient found for phone=%s campaign=%s",
            phone,
            DEFAULT_CAMPAIGN_NAME
        )

        return

    # ==========================================
    # First Click Wins
    # ==========================================

    if recipient.get("responseLocked") is True:

        logger.info(
            "Response already locked. Ignoring button click | phone=%s button=%s existingResponse=%s",
            phone,
            button_text,
            recipient.get("normalizedResponse")
        )

        # Optional: store ignored click for debugging
        ignored_clicks = get_collection(
            "ignored_button_clicks"
        )

        ignored_clicks.insert_one(
            {
                "phone": phone,
                "campaignName": DEFAULT_CAMPAIGN_NAME,
                "buttonText": button_text,
                "buttonPayload": event.get("buttonPayload"),
                "reason": "response_already_locked",
                "existingResponse": recipient.get("normalizedResponse"),
                "rawEvent": event,
                "createdAt": now_utc(),
                "updatedAt": now_utc(),
            }
        )

        return

    # Atomic update:
    # This protects from duplicate webhook race condition.
    update_result = campaign_recipients.update_one(
        {
            "_id": recipient["_id"],
            "responseLocked": {
                "$ne": True
            }
        },
        {
            "$set": {
                "responseLocked": True,
                "firstButtonClicked": button_text,
                "buttonPayload": event.get("buttonPayload"),
                "normalizedResponse": button_action["normalizedResponse"],
                "currentLeadStatus": button_action["leadStatus"],
                "followupTemplateToSend": button_action["nextTemplate"],
                "responseAt": now_utc(),
                "updatedAt": now_utc(),
            }
        }
    )

    if update_result.modified_count == 0:

        logger.info(
            "Button click skipped because response was already locked by another request | phone=%s",
            phone
        )

        return

    lead_name = recipient.get("name", "")

    template_sent = send_whatsapp_template(
        phone=phone,
        template_name=button_action["nextTemplate"],
        name=lead_name
    )

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
                    now_utc()
                    if template_sent
                    else None
                ),
                "updatedAt": now_utc(),
            }
        }
    )


# =========================================================
# Health Check API
# =========================================================

@app.get("/")
async def health_check():

    return {
        "status": "ok",
        "service": "geo-whatsapp-webhook"
    }


# =========================================================
# WhatsApp Webhook Verification
# =========================================================

@app.get("/webhooks/whatsapp")
async def verify_whatsapp_webhook(request: Request):

    mode = request.query_params.get("hub.mode")

    token = request.query_params.get("hub.verify_token")

    challenge = request.query_params.get("hub.challenge")

    logger.info(
        "Webhook verification request received | mode=%s token_match=%s",
        mode,
        token == WHATSAPP_VERIFY_TOKEN
    )

    if (
        mode == "subscribe"
        and token == WHATSAPP_VERIFY_TOKEN
    ):

        return PlainTextResponse(content=challenge)

    raise HTTPException(
        status_code=403,
        detail="Invalid verify token"
    )


# =========================================================
# Receive WhatsApp Webhook
# =========================================================

@app.post("/webhooks/whatsapp")
async def receive_whatsapp_webhook(request: Request):

    payload = await request.json()

    logger.info("WhatsApp webhook payload received:")

    logger.info(json.dumps(payload, indent=2))

    try:

        raw_webhooks = get_collection(
            "raw_webhooks"
        )

        whatsapp_events = get_collection(
            "whatsapp_events"
        )

        # ==========================================
        # Save Raw Webhook Payload
        # ==========================================

        raw_webhooks.insert_one(
            {
                "source": "whatsapp",
                "payload": payload,
                "createdAt": now_utc(),
            }
        )

        # ==========================================
        # Extract Events
        # ==========================================

        extracted_events = extract_whatsapp_events(
            payload
        )

        if extracted_events:

            whatsapp_events.insert_many(
                extracted_events
            )

            logger.info(
                "Saved %s WhatsApp event(s) to MongoDB.",
                len(extracted_events)
            )

            for event in extracted_events:


                if event.get("eventType") != "incoming_message":
                    continue

                if not event.get("buttonText"):
                    continue

                process_button_click(event)

        else:

            logger.info(
                "No messages/statuses found in webhook payload."
            )

    except Exception as e:

        logger.exception(
            "Failed to save WhatsApp webhook payload to MongoDB: %s",
            str(e)
        )

        # Important:
        # Return 200 to Meta to avoid retries

        return {
            "status": "ok",
            "warning": "received_but_not_saved"
        }

    return {
        "status": "ok"
    }




# =========================================================
# JWT Config
# =========================================================

JWT_SECRET_KEY = "geo_whatsapp_secret_key"

JWT_ALGORITHM = "HS256"

JWT_EXPIRE_HOURS = 24


# =========================================================
# Login Request Model
# =========================================================

class LoginRequestModel(BaseModel):

    emailId: str
    password: str


class LeadInviteModel(BaseModel):
    name: str
    phone: str


class CampaignInviteRequestModel(BaseModel):
    leads: List[LeadInviteModel]

# =========================================================
# Generate JWT Token
# =========================================================

def generate_jwt_token(admin_user_data):

    payload = {
        "adminUserId": str(admin_user_data.get("_id")),
        "emailId": admin_user_data.get("emailId"),
        "exp": int(time.time()) + (JWT_EXPIRE_HOURS * 60 * 60)
    }

    token = jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM
    )

    return token

# =========================================================
# Send UPSC Orientation Invite API
# =========================================================

@app.post("/campaigns/upsc-orientation/send-invite")
async def send_upsc_orientation_invite(
    payload: CampaignInviteRequestModel
):

    try:

        campaign_recipients = get_collection(
            "campaign_recipients"
        )

        whatsapp_message_logs = get_collection(
            "whatsapp_message_logs"
        )

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
# =========================================================
# Admin Login API
# =========================================================

@app.post("/admin/login")
async def admin_login(
    payload: LoginRequestModel
):

    try:

        admin_collection = get_collection(
            "admin_users"
        )

        admin_user = admin_collection.find_one(
            {
                "emailId": payload.emailId,
                "password": payload.password
            }
        )

        if not admin_user:

            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        token = generate_jwt_token(
            admin_user
        )

        return {
            "success": True,
            "message": "Login successful",
            "token": token,
            "userData": {
                "id": str(admin_user.get("_id")),
                "emailId": admin_user.get("emailId")
            }
        }

    except HTTPException:
        raise

    except Exception as e:

        logger.exception(
            "Admin login failed: %s",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Something went wrong"
        )
import os
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

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




# =========================================================
# Load Environment Variables
# =========================================================

load_dotenv()


# =========================================================
# FastAPI App
# =========================================================

app = FastAPI()


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

                if message_type == "text":

                    text_body = (
                        message.get("text", {})
                        .get("body")
                    )

                event = {
                    "eventType": "incoming_message",
                    "waMessageId": message.get("id"),
                    "from": message.get("from"),
                    "timestamp": message.get("timestamp"),
                    "messageType": message_type,
                    "text": text_body,
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
import os
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from pymongo import MongoClient
from pymongo.collection import Collection

app = FastAPI()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whatsapp-webhook")

WHATSAPP_VERIFY_TOKEN = os.getenv(
    "WHATSAPP_VERIFY_TOKEN",
    "geo_ias_whatsapp_verify_token"
)

MONGODB_URI = os.getenv("MONGODB_URI")

mongo_client = None
db = None


@app.on_event("startup")
def startup_event():
    global mongo_client, db

    if not MONGODB_URI:
        logger.warning("MONGODB_URI is not configured. Webhook will not save to MongoDB.")
        return

    mongo_client = MongoClient(MONGODB_URI)
    db = mongo_client["geo_whatsapp"]

    logger.info("MongoDB connected successfully.")


@app.on_event("shutdown")
def shutdown_event():
    global mongo_client

    if mongo_client:
        mongo_client.close()
        logger.info("MongoDB connection closed.")


def get_collection(collection_name: str) -> Collection:
    if db is None:
        raise RuntimeError("MongoDB is not connected.")
    return db[collection_name]


def now_utc():
    return datetime.now(timezone.utc)


def extract_whatsapp_events(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract useful events from WhatsApp webhook payload.

    WhatsApp webhook can contain:
    1. messages  -> incoming user messages
    2. statuses  -> sent/delivered/read/failed updates
    """

    extracted_events = []

    entries = payload.get("entry", [])

    for entry in entries:
        changes = entry.get("changes", [])

        for change in changes:
            value = change.get("value", {})
            metadata = value.get("metadata", {})

            phone_number_id = metadata.get("phone_number_id")
            display_phone_number = metadata.get("display_phone_number")

            # Incoming messages
            for message in value.get("messages", []):
                message_type = message.get("type")

                text_body = None
                if message_type == "text":
                    text_body = message.get("text", {}).get("body")

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

            # Message statuses
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


@app.get("/")
async def health_check():
    return {
        "status": "ok",
        "service": "geo-whatsapp-webhook"
    }


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

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(content=challenge)

    raise HTTPException(status_code=403, detail="Invalid verify token")


@app.post("/webhooks/whatsapp")
async def receive_whatsapp_webhook(request: Request):
    payload = await request.json()

    logger.info("WhatsApp webhook payload received:")
    logger.info(json.dumps(payload, indent=2))

    try:
        raw_webhooks = get_collection("raw_webhooks")
        whatsapp_events = get_collection("whatsapp_events")

        # Store full raw payload for debugging/audit.
        raw_webhooks.insert_one({
            "source": "whatsapp",
            "payload": payload,
            "createdAt": now_utc(),
        })

        extracted_events = extract_whatsapp_events(payload)

        if extracted_events:
            whatsapp_events.insert_many(extracted_events)
            logger.info("Saved %s WhatsApp event(s) to MongoDB.", len(extracted_events))
        else:
            logger.info("No messages/statuses found in webhook payload.")

    except Exception as e:
        logger.exception("Failed to save WhatsApp webhook payload to MongoDB: %s", str(e))

        # Important:
        # Still return 200 to Meta, otherwise Meta may retry many times.
        return {"status": "ok", "warning": "received_but_not_saved"}

    return {"status": "ok"}
import json
import time

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse
from loguru import logger

from app.config import WHATSAPP_VERIFY_TOKEN
from app.db.mongodb import get_collection
from app.services.whatsapp_extractor import extract_whatsapp_events
from app.services.campaign_service import (
    process_button_click,
    process_text_message,
)


router = APIRouter(
    prefix="/webhooks",
    tags=["WhatsApp Webhook"]
)


# =========================================================
# WhatsApp Webhook Verification
# =========================================================

@router.get("/whatsapp")
async def verify_whatsapp_webhook(request: Request):

    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    logger.info(
        "Webhook verification request received | mode={} token_match={}",
        mode,
        token == WHATSAPP_VERIFY_TOKEN
    )

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(content=challenge)

    raise HTTPException(
        status_code=403,
        detail="Invalid verify token"
    )


# =========================================================
# Receive WhatsApp Webhook
# =========================================================

@router.post("/whatsapp")
async def receive_whatsapp_webhook(request: Request):

    try:
        payload = await request.json()

        logger.critical("webhook Payload======>{}", payload)

        raw_webhooks = get_collection("raw_webhooks")
        whatsapp_events = get_collection("whatsapp_events")

        now = int(time.time() * 1000)

        # ==========================================
        # Save Raw Webhook Payload
        # ==========================================

        raw_webhooks.insert_one(
            {
                "source": "whatsapp",
                "payload": payload,
                "createTime": now,
                "updateTime": now,
            }
        )

        # ==========================================
        # Extract Events
        # ==========================================

        extracted_events = extract_whatsapp_events(payload)

        if not extracted_events:
            logger.info("No messages/statuses found in webhook payload.")
            return {
                "status": "ok"
            }

        # ==========================================
        # Save Extracted Events
        # ==========================================

        whatsapp_events.insert_many(extracted_events)

        logger.info(
            "Saved {} WhatsApp event(s) to MongoDB.",
            len(extracted_events)
        )

        # ==========================================
        # Process Incoming Messages
        # ==========================================

        for event in extracted_events:

            event_type = event.get("eventType")
            message_type = event.get("messageType")
            button_text = event.get("buttonText")
            text = event.get("text")

            # We currently process only incoming user messages here.
            # Status events like sent/delivered/read/failed are only stored for now.
            if event_type != "incoming_message":
                continue

            # Button clicks:
            # - Orientation buttons
            # - Final day reminder buttons
            # - Scholarship mock test buttons
            if button_text:
                logger.info(
                    "Processing button click | from={} buttonText={} contextMessageId={}",
                    event.get("from"),
                    button_text,
                    event.get("contextMessageId")
                )

                process_button_click(event)
                continue

            # Typed user messages:
            # Example: "I want to join", "Please call me", etc.
            if message_type == "text" and text:
                logger.info(
                    "Processing text message | from={} text={} contextMessageId={}",
                    event.get("from"),
                    text,
                    event.get("contextMessageId")
                )

                process_text_message(event)
                continue

        return {
            "status": "ok"
        }

    except Exception as e:

        logger.exception(
            "Failed to process WhatsApp webhook payload: {}",
            str(e)
        )

        # Important:
        # Return 200 to Meta to avoid repeated retries.
        # We still log the error above.
        return {
            "status": "ok",
            "warning": "received_but_not_processed"
        }
import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse

from app.config import WHATSAPP_VERIFY_TOKEN
from app.db.mongodb import get_collection
from app.services.whatsapp_extractor import extract_whatsapp_events
from app.services.campaign_service import process_button_click
from app.utils.time_utils import now_utc


logger = logging.getLogger("whatsapp-webhook")

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

@router.post("/whatsapp")
async def receive_whatsapp_webhook(request: Request):

    try:
        payload = await request.json()

        logger.info("WhatsApp webhook payload received:")
        logger.info(json.dumps(payload, indent=2))

        raw_webhooks = get_collection("raw_webhooks")
        whatsapp_events = get_collection("whatsapp_events")

        # ==========================================
        # Save Raw Webhook Payload
        # ==========================================

        raw_webhooks.insert_one(
            {
                "source": "whatsapp",
                "payload": payload,
                "createdAt": now_utc(),
                "updatedAt": now_utc(),
            }
        )

        # ==========================================
        # Extract Events
        # ==========================================

        extracted_events = extract_whatsapp_events(payload)

        if extracted_events:

            whatsapp_events.insert_many(extracted_events)

            logger.info(
                "Saved %s WhatsApp event(s) to MongoDB.",
                len(extracted_events)
            )

            # ==========================================
            # Process Button Clicks
            # ==========================================

            for event in extracted_events:

                if event.get("eventType") != "incoming_message":
                    continue

                if not event.get("buttonText"):
                    continue

                process_button_click(event)

        else:
            logger.info("No messages/statuses found in webhook payload.")

        return {
            "status": "ok"
        }

    except Exception as e:

        logger.exception(
            "Failed to process WhatsApp webhook payload: %s",
            str(e)
        )

        # Important:
        # Return 200 to Meta to avoid repeated retries.
        # We still log the error above.
        return {
            "status": "ok",
            "warning": "received_but_not_processed"
        }
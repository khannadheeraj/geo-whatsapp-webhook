import os
import json
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse

app = FastAPI()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whatsapp-webhook")

WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")


@app.get("/")
async def health_check():
    return {
        "status": "ok",
        "service": "geo-whatsapp-webhook"
    }


@app.get("/webhooks/whatsapp")
async def verify_whatsapp_webhook(request: Request):
    """
    Meta calls this GET endpoint once when you configure webhook.

    Meta sends:
    hub.mode
    hub.verify_token
    hub.challenge

    If token matches, we return hub.challenge as plain text.
    """

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
    """
    Meta calls this POST endpoint whenever:
    - user sends message
    - message delivered
    - message read
    - message failed
    - button/list reply received
    """

    body = await request.json()

    logger.info("WhatsApp webhook payload received:")
    logger.info(json.dumps(body, indent=2))

    return {"status": "ok"}
import secrets

from fastapi import Header

from app.config import WHATSAPP_BROADCAST_WORKER_TOKEN
from app.errors import AuthenticationError


async def require_broadcast_worker(
    worker_token: str = Header(default="", alias="X-Worker-Token"),
) -> None:
    if (
        len(WHATSAPP_BROADCAST_WORKER_TOKEN) < 32
        or not worker_token
        or not secrets.compare_digest(worker_token, WHATSAPP_BROADCAST_WORKER_TOKEN)
    ):
        raise AuthenticationError("WORKER_AUTHENTICATION_FAILED", "Worker authentication failed.")

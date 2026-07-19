from fastapi import APIRouter, Depends, Request

from app.api.dependencies.internal_worker import require_broadcast_worker
from app.schemas.whatsapp_broadcast_schema import DueBroadcastRunModel
from app.services.whatsapp_broadcast_scheduler_service import run_due


router = APIRouter(prefix="/internal/whatsapp-broadcasts", tags=["Internal WhatsApp Broadcast Worker"])


@router.post("/run-due", dependencies=[Depends(require_broadcast_worker)])
async def run_due_route(payload: DueBroadcastRunModel, request: Request):
    return {"data": run_due(payload.batchSize, payload.maxBroadcasts, request.state.request_id)}

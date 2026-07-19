from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies.auth import require_super_admin
from app.api.response_helpers import pagination_metadata
from app.schemas.whatsapp_broadcast_schema import BroadcastCreateModel, BroadcastPrepareModel
from app.services.whatsapp_broadcast_service import create_broadcast, delete_broadcast, get_broadcast, prepare_broadcast, recipients
from app.utils.mongo_utils import public_document

router = APIRouter(prefix="/whatsapp-broadcasts", tags=["WhatsApp Broadcasts"])

@router.post("")
async def create(payload: BroadcastCreateModel, request: Request, user=Depends(require_super_admin)):
    return {"data": public_document(create_broadcast(payload, user, request.state.request_id))}

@router.get("/{broadcastId}")
async def detail(broadcastId: str, user=Depends(require_super_admin)):
    return {"data": public_document(get_broadcast(broadcastId))}

@router.post("/{broadcastId}/prepare")
async def prepare(broadcastId: str, payload: BroadcastPrepareModel, request: Request, user=Depends(require_super_admin)):
    return {"data": public_document(prepare_broadcast(broadcastId, payload.version, user, request.state.request_id))}

@router.get("/{broadcastId}/recipients")
async def list_recipients(broadcastId: str, status: Optional[str] = Query(default=None, pattern="^(ELIGIBLE|SKIPPED|REJECTED)$"), page: int = Query(1, ge=1), pageSize: int = Query(25, ge=1, le=100), user=Depends(require_super_admin)):
    documents, total = recipients(broadcastId, status, page, pageSize)
    return {"data": [public_document(document) for document in documents], "pagination": pagination_metadata(page, pageSize, total)}

@router.delete("/{broadcastId}")
async def delete(broadcastId: str, request: Request, version: int = Query(..., ge=1), user=Depends(require_super_admin)):
    delete_broadcast(broadcastId, version, user, request.state.request_id)
    return {"data": {"deleted": True}}

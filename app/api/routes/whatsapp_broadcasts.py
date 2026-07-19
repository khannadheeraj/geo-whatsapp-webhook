from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies.auth import require_super_admin
from app.api.response_helpers import pagination_metadata
from app.schemas.whatsapp_broadcast_schema import BroadcastBatchModel, BroadcastCreateModel, BroadcastPrepareModel, BroadcastVersionModel
from app.services.whatsapp_broadcast_service import create_broadcast, delete_broadcast, get_broadcast, prepare_broadcast, recipients
from app.services.whatsapp_broadcast_execution_service import cancel, confirm, execute_batch, execution, retry_failures
from app.services.whatsapp_broadcast_analytics_service import analytics, recipient_detail, report
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

@router.post("/{broadcastId}/confirm")
async def confirm_route(broadcastId: str, payload: BroadcastVersionModel, request: Request, user=Depends(require_super_admin)):
    return {"data": confirm(broadcastId, payload.version, user, request.state.request_id)}

@router.post("/{broadcastId}/execute-batch")
async def execute_batch_route(broadcastId: str, payload: BroadcastBatchModel, request: Request, user=Depends(require_super_admin)):
    return {"data": execute_batch(broadcastId, payload.batchSize, user, request.state.request_id)}

@router.get("/{broadcastId}/execution")
async def execution_route(broadcastId: str, user=Depends(require_super_admin)):
    return {"data": execution(broadcastId)}

@router.get("/{broadcastId}/analytics")
async def analytics_route(broadcastId: str, user=Depends(require_super_admin)):
    return {"data": analytics(broadcastId)}

@router.get("/{broadcastId}/report")
async def report_route(broadcastId: str, executionStatus: Optional[str] = Query(default=None, max_length=50), deliveryStatus: Optional[str] = Query(default=None, pattern="^(ACCEPTED|SENT|DELIVERED|READ|FAILED)$"), page: int = Query(1, ge=1), pageSize: int = Query(25, ge=1, le=100), user=Depends(require_super_admin)):
    documents, total = report(broadcastId, executionStatus, deliveryStatus, page, pageSize)
    return {"data": documents, "pagination": pagination_metadata(page, pageSize, total)}

@router.get("/{broadcastId}/recipients/{recipientId}")
async def recipient_detail_route(broadcastId: str, recipientId: str, user=Depends(require_super_admin)):
    return {"data": recipient_detail(broadcastId, recipientId)}

@router.post("/{broadcastId}/retry-failures")
async def retry_failures_route(broadcastId: str, payload: BroadcastVersionModel, request: Request, user=Depends(require_super_admin)):
    return {"data": retry_failures(broadcastId, payload.version, user, request.state.request_id)}

@router.post("/{broadcastId}/cancel")
async def cancel_route(broadcastId: str, payload: BroadcastVersionModel, request: Request, user=Depends(require_super_admin)):
    return {"data": cancel(broadcastId, payload.version, user, request.state.request_id)}

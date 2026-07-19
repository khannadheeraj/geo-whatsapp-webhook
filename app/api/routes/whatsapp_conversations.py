from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.dependencies.auth import require_authenticated_user
from app.api.response_helpers import pagination_metadata
from app.services.whatsapp_inbox_service import list_inbox, mark_conversation_viewed, message_history
from app.utils.mongo_utils import public_document

router = APIRouter(prefix="/whatsapp-conversations", tags=["WhatsApp Inbox"])

@router.get("")
async def list_conversations(page: int = Query(1, ge=1), pageSize: int = Query(25, ge=1, le=100), search: Optional[str] = Query(None, max_length=200), reconciliationStatus: Optional[str] = Query(None, max_length=50), assignedCounsellorId: Optional[str] = Query(None, min_length=24, max_length=24), unreadOnly: bool = False, user=Depends(require_authenticated_user)):
    data, total = list_inbox(user, page=page, page_size=pageSize, search=search, reconciliation_status=reconciliationStatus, assigned_counsellor_id=assignedCounsellorId, unread_only=unreadOnly)
    return {"data": data, "pagination": pagination_metadata(page, pageSize, total)}

@router.get("/{conversationId}/messages")
async def list_messages(conversationId: str, cursor: Optional[str] = None, pageSize: int = Query(50, ge=1, le=100), user=Depends(require_authenticated_user)):
    data, pagination = message_history(conversationId, user, cursor=cursor, page_size=pageSize)
    return {"data": [public_document(message) for message in data], "pagination": pagination}

@router.post("/{conversationId}/view")
async def view_conversation(conversationId: str, user=Depends(require_authenticated_user)):
    return {"data": public_document(mark_conversation_viewed(conversationId, user))}

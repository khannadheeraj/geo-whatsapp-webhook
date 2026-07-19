from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from app.api.dependencies.auth import require_authenticated_user
from app.api.response_helpers import list_response
from app.schemas.follow_up_schema import FollowUpActionModel, FollowUpCreateModel, FollowUpPatchModel
from app.services.follow_up_service import action, create, get, list_follow_ups, patch
from app.utils.mongo_utils import public_document
router = APIRouter(prefix="/follow-ups", tags=["Follow-ups"])
@router.post("")
async def create_route(payload: FollowUpCreateModel, request: Request, user=Depends(require_authenticated_user)): return {"data": public_document(create(payload, user, request.state.request_id))}
@router.get("")
async def list_route(page:int=Query(1,ge=1), pageSize:int=Query(25,ge=1,le=100), assignedCounsellorId:Optional[str]=None, status:Optional[str]=Query(None,pattern="^(PENDING|COMPLETED|CANCELLED)$"), type:Optional[str]=Query(None,pattern="^(CALL|WHATSAPP|MEETING|DOCUMENT|PAYMENT|GENERAL)$"), priority:Optional[str]=Query(None,pattern="^(LOW|MEDIUM|HIGH|URGENT)$"), dueFrom:Optional[datetime]=None, dueTo:Optional[datetime]=None, overdue:Optional[bool]=None, search:Optional[str]=Query(None,max_length=200), user=Depends(require_authenticated_user)):
    docs,total=list_follow_ups(user,assigned=assignedCounsellorId,status=status,task_type=type,priority=priority,due_from=dueFrom,due_to=dueTo,overdue=overdue,search=search,page=page,page_size=pageSize); return list_response(docs,page,pageSize,total)
@router.get("/{followUpId}")
async def detail_route(followUpId:str,user=Depends(require_authenticated_user)): return {"data":public_document(get(followUpId,user))}
@router.patch("/{followUpId}")
async def patch_route(followUpId:str,payload:FollowUpPatchModel,request:Request,user=Depends(require_authenticated_user)): return {"data":public_document(patch(followUpId,payload,user,request.state.request_id))}
@router.post("/{followUpId}/complete")
async def complete_route(followUpId:str,payload:FollowUpActionModel,request:Request,user=Depends(require_authenticated_user)): return {"data":public_document(action(followUpId,payload,user,request.state.request_id,"COMPLETED"))}
@router.post("/{followUpId}/cancel")
async def cancel_route(followUpId:str,payload:FollowUpActionModel,request:Request,user=Depends(require_authenticated_user)): return {"data":public_document(action(followUpId,payload,user,request.state.request_id,"CANCELLED"))}

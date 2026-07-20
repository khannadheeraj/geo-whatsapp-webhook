from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from app.api.dependencies.auth import require_authenticated_user
from app.api.response_helpers import list_response
from app.schemas.follow_up_schema import FollowUpActionModel, FollowUpCreateModel, FollowUpPatchModel, FollowUpOutcome
from app.services.follow_up_service import action, completion_recommendation, create, get, list_follow_ups, patch, work_queue
from app.utils.mongo_utils import public_document, serialize_value
router = APIRouter(prefix="/follow-ups", tags=["Follow-ups"])
@router.post("")
async def create_route(payload: FollowUpCreateModel, request: Request, user=Depends(require_authenticated_user)): return {"data": public_document(create(payload, user, request.state.request_id))}
@router.get("")
async def list_route(page:int=Query(1,ge=1), pageSize:int=Query(25,ge=1,le=100), assignedCounsellorId:Optional[str]=None, status:Optional[str]=Query(None,pattern="^(PENDING|COMPLETED|CANCELLED)$"), type:Optional[str]=Query(None,pattern="^(CALL|WHATSAPP|MEETING|DOCUMENT|PAYMENT|GENERAL)$"), priority:Optional[str]=Query(None,pattern="^(LOW|MEDIUM|HIGH|URGENT)$"), dueFrom:Optional[datetime]=None, dueTo:Optional[datetime]=None, overdue:Optional[bool]=None, search:Optional[str]=Query(None,max_length=200), user=Depends(require_authenticated_user)):
    docs,total=list_follow_ups(user,assigned=assignedCounsellorId,status=status,task_type=type,priority=priority,due_from=dueFrom,due_to=dueTo,overdue=overdue,search=search,page=page,page_size=pageSize); return list_response(docs,page,pageSize,total)
@router.get("/work-queue")
async def work_queue_route(page:int=Query(1,ge=1), pageSize:int=Query(25,ge=1,le=100), group:Optional[str]=Query("OVERDUE",pattern="^(OVERDUE|DUE_TODAY|UPCOMING|COMPLETED_TODAY|LEADS_WITHOUT_PENDING_FOLLOW_UP)$"), assignedCounsellorId:Optional[str]=None, user=Depends(require_authenticated_user)):
    docs,counts,total=work_queue(user, group=group, assigned=assignedCounsellorId, page=page, page_size=pageSize); return {"data":[serialize_value(item) for item in docs], "summary":counts, "pagination":{"page":page,"pageSize":pageSize,"totalRecords":total,"totalPages":max(1,(total+pageSize-1)//pageSize),"hasNext":page*pageSize<total,"hasPrevious":page>1}}
@router.get("/work-queue/summary")
async def work_queue_summary_route(assignedCounsellorId:Optional[str]=None, user=Depends(require_authenticated_user)):
    _,counts,_=work_queue(user, group="OVERDUE", assigned=assignedCounsellorId, page=1, page_size=1); return {"data":counts}
@router.get("/{followUpId}/completion-recommendation")
async def completion_recommendation_route(followUpId:str, outcome:Optional[FollowUpOutcome]=None, user=Depends(require_authenticated_user)): return {"data":serialize_value(completion_recommendation(followUpId, user, outcome))}
@router.get("/{followUpId}")
async def detail_route(followUpId:str,user=Depends(require_authenticated_user)): return {"data":public_document(get(followUpId,user))}
@router.patch("/{followUpId}")
async def patch_route(followUpId:str,payload:FollowUpPatchModel,request:Request,user=Depends(require_authenticated_user)): return {"data":public_document(patch(followUpId,payload,user,request.state.request_id))}
@router.post("/{followUpId}/complete")
async def complete_route(followUpId:str,payload:FollowUpActionModel,request:Request,user=Depends(require_authenticated_user)): return {"data":public_document(action(followUpId,payload,user,request.state.request_id,"COMPLETED"))}
@router.post("/{followUpId}/cancel")
async def cancel_route(followUpId:str,payload:FollowUpActionModel,request:Request,user=Depends(require_authenticated_user)): return {"data":public_document(action(followUpId,payload,user,request.state.request_id,"CANCELLED"))}

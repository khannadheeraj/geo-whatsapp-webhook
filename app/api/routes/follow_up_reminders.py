from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from app.api.dependencies.auth import require_authenticated_user
from app.api.response_helpers import pagination_metadata
from app.schemas.follow_up_reminder_schema import FollowUpReminderSnoozeModel
from app.services.follow_up_reminder_service import dismiss, list_reminders, snooze
from app.utils.mongo_utils import serialize_value
router=APIRouter(prefix="/follow-up-reminders",tags=["Follow-up reminders"])
@router.get("")
async def list_route(page:int=Query(1,ge=1),pageSize:int=Query(25,ge=1,le=100),category:Optional[str]=Query(None,pattern="^(OVERDUE|DUE_NOW|DUE_SOON)$"),assignedCounsellorId:Optional[str]=None,user=Depends(require_authenticated_user)):
    docs,counts,total=list_reminders(user,assigned=assignedCounsellorId,category=category,page=page,page_size=pageSize); return {"data":[serialize_value(doc) for doc in docs],"counts":counts,"pagination":pagination_metadata(page,pageSize,total)}
@router.get("/summary")
async def summary_route(assignedCounsellorId:Optional[str]=None,user=Depends(require_authenticated_user)):
    _,counts,_=list_reminders(user,assigned=assignedCounsellorId,category=None,page=1,page_size=1); return {"data":counts}
@router.post("/{followUpId}/snooze")
async def snooze_route(followUpId:str,payload:FollowUpReminderSnoozeModel,request:Request,user=Depends(require_authenticated_user)): return {"data":serialize_value(snooze(followUpId,payload,user,request.state.request_id))}
@router.post("/{followUpId}/dismiss")
async def dismiss_route(followUpId:str,request:Request,user=Depends(require_authenticated_user)): return {"data":serialize_value(dismiss(followUpId,user,request.state.request_id))}

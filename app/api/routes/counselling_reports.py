from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.dependencies.auth import require_authenticated_user
from app.api.response_helpers import pagination_metadata
from app.services.counselling_report_service import follow_up_rows, outcomes, productivity, summary
from app.utils.mongo_utils import serialize_value

router = APIRouter(prefix="/counselling-reports", tags=["Counselling reports"])

@router.get("/summary")
async def summary_route(assignedCounsellorId: Optional[str] = None, dateFrom: Optional[datetime] = None, dateTo: Optional[datetime] = None, user=Depends(require_authenticated_user)):
    return {"data": serialize_value(summary(user, assignedCounsellorId, dateFrom, dateTo))}
@router.get("/outcomes")
async def outcomes_route(assignedCounsellorId: Optional[str] = None, dateFrom: Optional[datetime] = None, dateTo: Optional[datetime] = None, user=Depends(require_authenticated_user)):
    return {"data": serialize_value(outcomes(user, assignedCounsellorId, dateFrom, dateTo))}
@router.get("/productivity")
async def productivity_route(assignedCounsellorId: Optional[str] = None, dateFrom: Optional[datetime] = None, dateTo: Optional[datetime] = None, user=Depends(require_authenticated_user)):
    return {"data": serialize_value(productivity(user, assignedCounsellorId, dateFrom, dateTo))}
@router.get("/follow-ups")
async def follow_up_route(page: int = Query(1, ge=1), pageSize: int = Query(25, ge=1, le=100), assignedCounsellorId: Optional[str] = None, dateFrom: Optional[datetime] = None, dateTo: Optional[datetime] = None, user=Depends(require_authenticated_user)):
    docs, total = follow_up_rows(user, assignedCounsellorId, dateFrom, dateTo, page, pageSize)
    return {"data": serialize_value(docs), "pagination": pagination_metadata(page, pageSize, total)}

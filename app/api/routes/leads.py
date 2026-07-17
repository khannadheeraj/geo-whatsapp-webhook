from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.dependencies.auth import require_authenticated_user, require_super_admin
from app.api.response_helpers import list_response
from app.models.crm_model import ActivityType, LeadPriority, LeadStatus, PreferredMode
from app.repositories.activity_repository import list_lead_activities
from app.repositories.lead_repository import list_assignment_history
from app.schemas.lead_schema import LeadAssignmentModel, LeadCreateModel, LeadPatchModel
from app.services.assignment_service import assign_lead
from app.services.lead_service import (
    create_lead,
    get_lead,
    get_lead_detail,
    list_leads,
    patch_lead,
)
from app.utils.mongo_utils import public_document


router = APIRouter(prefix="/leads", tags=["Leads"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_lead_route(
    payload: LeadCreateModel,
    request: Request,
    user=Depends(require_authenticated_user),
):
    lead = create_lead(payload, user, request.state.request_id)
    return {"data": public_document(lead)}


@router.get("")
async def list_leads_route(
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=100),
    statusValue: Optional[LeadStatus] = Query(default=None, alias="status"),
    priority: Optional[LeadPriority] = None,
    assignedCounsellorId: Optional[str] = Query(default=None, min_length=24, max_length=24),
    unassigned: Optional[bool] = None,
    source: Optional[str] = Query(default=None, max_length=100),
    preferredMode: Optional[PreferredMode] = None,
    targetYear: Optional[int] = Query(default=None, ge=2020, le=2100),
    createdFrom: Optional[datetime] = None,
    createdTo: Optional[datetime] = None,
    lastActivityFrom: Optional[datetime] = None,
    lastActivityTo: Optional[datetime] = None,
    sort: str = Query("-createdAt", max_length=50),
    user=Depends(require_authenticated_user),
):
    documents, total = list_leads(
        user,
        page=page,
        page_size=pageSize,
        status=statusValue.value if statusValue else None,
        priority=priority.value if priority else None,
        assigned_counsellor_id=assignedCounsellorId,
        unassigned=unassigned,
        source=source,
        preferred_mode=preferredMode.value if preferredMode else None,
        target_year=targetYear,
        created_from=createdFrom,
        created_to=createdTo,
        activity_from=lastActivityFrom,
        activity_to=lastActivityTo,
        sort=sort,
    )
    return list_response(documents, page, pageSize, total)


@router.get("/{leadId}")
async def get_lead_route(
    leadId: str,
    user=Depends(require_authenticated_user),
):
    result = get_lead_detail(leadId, user)
    return {
        "data": {
            "lead": public_document(result["lead"]),
            "contact": public_document(result["contact"]),
            "preferences": public_document(result["preferences"]),
            "courseInterests": [public_document(item) for item in result["courseInterests"]],
        }
    }


@router.patch("/{leadId}")
async def patch_lead_route(
    leadId: str,
    payload: LeadPatchModel,
    request: Request,
    user=Depends(require_authenticated_user),
):
    lead = patch_lead(leadId, payload, user, request.state.request_id)
    return {"data": public_document(lead)}


@router.post("/{leadId}/assignments")
async def assign_lead_route(
    leadId: str,
    payload: LeadAssignmentModel,
    request: Request,
    user=Depends(require_super_admin),
):
    lead = get_lead(leadId, user)
    updated, history = assign_lead(
        lead["_id"],
        payload.counsellorId,
        reason_code=payload.reasonCode,
        reason=payload.reason,
        expected_version=payload.version,
        actor=user,
        request_id=request.state.request_id,
        operation_id=f"assignment-request:{request.state.request_id}",
    )
    return {"data": {"lead": public_document(updated), "assignment": public_document(history)}}


@router.get("/{leadId}/assignments")
async def list_lead_assignments_route(
    leadId: str,
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=100),
    user=Depends(require_authenticated_user),
):
    lead = get_lead(leadId, user)
    documents, total = list_assignment_history(lead["_id"], page=page, page_size=pageSize)
    return list_response(documents, page, pageSize, total)


@router.get("/{leadId}/activities")
async def list_lead_activities_route(
    leadId: str,
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=100),
    activityType: Optional[ActivityType] = None,
    user=Depends(require_authenticated_user),
):
    lead = get_lead(leadId, user)
    documents, total = list_lead_activities(
        lead["_id"],
        page=page,
        page_size=pageSize,
        activity_type=activityType.value if activityType else None,
    )
    return list_response(documents, page, pageSize, total)

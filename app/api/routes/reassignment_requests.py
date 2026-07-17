from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.dependencies.auth import require_authenticated_user, require_super_admin
from app.api.response_helpers import list_response
from app.models.crm_model import ReassignmentStatus
from app.models.user_model import public_user
from app.schemas.reassignment_schema import (
    ReassignmentApproveModel,
    ReassignmentCreateModel,
    ReassignmentRejectModel,
)
from app.services.reassignment_service import (
    approve_reassignment_request,
    cancel_reassignment_request,
    create_reassignment_request,
    list_reassignment_requests,
    reassignment_list_context,
    reject_reassignment_request,
)
from app.utils.mongo_utils import public_document


router = APIRouter(tags=["Reassignment Requests"])


@router.post("/leads/{leadId}/reassignment-requests", status_code=status.HTTP_201_CREATED)
async def create_reassignment_request_route(
    leadId: str,
    payload: ReassignmentCreateModel,
    request: Request,
    user=Depends(require_authenticated_user),
):
    result = create_reassignment_request(leadId, payload, user, request.state.request_id)
    return {"data": public_document(result)}


@router.get("/reassignment-requests")
async def list_reassignment_requests_route(
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=100),
    statusValue: Optional[ReassignmentStatus] = Query(default=None, alias="status"),
    leadId: Optional[str] = Query(default=None, min_length=24, max_length=24),
    user=Depends(require_authenticated_user),
):
    documents, total = list_reassignment_requests(
        user,
        page=page,
        page_size=pageSize,
        status=statusValue.value if statusValue else None,
        lead_id=leadId,
    )
    context = reassignment_list_context(documents)
    data = []
    for document in documents:
        item = public_document(document)
        lead = context["leads"].get(document["leadId"])
        contact = context["contacts"].get(lead.get("contactId")) if lead else None
        item["lead"] = public_document(lead)
        item["contact"] = public_document(contact)
        for source_field, response_field in (
            ("requestedBy", "requester"),
            ("requestedTargetCounsellorId", "requestedCounsellor"),
            ("approvedCounsellorId", "approvedCounsellor"),
            ("decidedBy", "decidedByUser"),
        ):
            related = context["users"].get(document.get(source_field))
            item[response_field] = public_user(related) if related else None
        current_owner = context["users"].get(lead.get("assignedCounsellorId")) if lead else None
        item["currentCounsellor"] = public_user(current_owner) if current_owner else None
        data.append(item)
    return {"data": data, "pagination": list_response([], page, pageSize, total)["pagination"]}


@router.post("/reassignment-requests/{requestId}/approve")
async def approve_reassignment_request_route(
    requestId: str,
    payload: ReassignmentApproveModel,
    request: Request,
    user=Depends(require_super_admin),
):
    result = approve_reassignment_request(requestId, payload, user, request.state.request_id)
    return {"data": public_document(result)}


@router.post("/reassignment-requests/{requestId}/reject")
async def reject_reassignment_request_route(
    requestId: str,
    payload: ReassignmentRejectModel,
    request: Request,
    user=Depends(require_super_admin),
):
    result = reject_reassignment_request(requestId, payload, user, request.state.request_id)
    return {"data": public_document(result)}


@router.post("/reassignment-requests/{requestId}/cancel")
async def cancel_reassignment_request_route(
    requestId: str,
    request: Request,
    user=Depends(require_authenticated_user),
):
    result = cancel_reassignment_request(requestId, user, request.state.request_id)
    return {"data": public_document(result)}

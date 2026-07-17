from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.dependencies.auth import require_authenticated_user, require_super_admin
from app.api.response_helpers import pagination_metadata
from app.models.user_model import UserRole, public_user
from app.schemas.user_schema import StaffPasswordResetModel, StaffUserCreateModel, StaffUserPatchModel
from app.services.staff_service import (
    create_staff,
    get_staff_user,
    list_active_counsellors,
    list_staff,
    patch_staff,
    reset_password,
)


router = APIRouter(prefix="/users", tags=["Staff Users"])


@router.get("/counsellor-options")
async def counsellor_options_route(user=Depends(require_authenticated_user)):
    return {
        "data": [
            {"id": str(item["_id"]), "displayName": item.get("displayName", "")}
            for item in list_active_counsellors()
        ]
    }


@router.get("")
async def list_staff_route(
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=100),
    role: Optional[UserRole] = None,
    isActive: Optional[bool] = None,
    search: Optional[str] = Query(default=None, max_length=200),
    user=Depends(require_super_admin),
):
    documents, total = list_staff(
        page=page,
        page_size=pageSize,
        role=role.value if role else None,
        is_active=isActive,
        search=search,
    )
    return {
        "data": [public_user(document) for document in documents],
        "pagination": pagination_metadata(page, pageSize, total),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_staff_route(
    payload: StaffUserCreateModel,
    request: Request,
    user=Depends(require_super_admin),
):
    return {"data": public_user(create_staff(payload, user, request.state.request_id))}


@router.get("/{userId}")
async def get_staff_route(userId: str, user=Depends(require_super_admin)):
    return {"data": public_user(get_staff_user(userId))}


@router.patch("/{userId}")
async def patch_staff_route(
    userId: str,
    payload: StaffUserPatchModel,
    request: Request,
    user=Depends(require_super_admin),
):
    updated, reauthentication_required = patch_staff(
        userId, payload, user, request.state.request_id
    )
    return {
        "data": {
            "user": public_user(updated),
            "reauthenticationRequired": reauthentication_required,
        }
    }


@router.post("/{userId}/reset-password")
async def reset_staff_password_route(
    userId: str,
    payload: StaffPasswordResetModel,
    request: Request,
    user=Depends(require_super_admin),
):
    updated = reset_password(userId, payload, user, request.state.request_id)
    return {"data": {"user": public_user(updated), "sessionsRevoked": True}}

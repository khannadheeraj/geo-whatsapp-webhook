from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies.auth import require_authenticated_user, require_super_admin
from app.api.response_helpers import pagination_metadata
from app.services.whatsapp_template_sync_service import (
    get_template_detail,
    list_templates,
    sync_templates,
)
from app.utils.mongo_utils import public_document


router = APIRouter(prefix="/whatsapp-templates", tags=["WhatsApp Templates"])


@router.post("/sync")
async def sync_whatsapp_templates_route(
    request: Request,
    user=Depends(require_super_admin),
):
    return {"data": sync_templates(user, request.state.request_id)}


@router.get("")
async def list_whatsapp_templates_route(
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=100),
    search: Optional[str] = Query(default=None, max_length=200),
    category: Optional[str] = Query(default=None, max_length=100),
    language: Optional[str] = Query(default=None, max_length=100),
    user=Depends(require_authenticated_user),
):
    documents, total = list_templates(
        page=page, page_size=pageSize, search=search,
        category=category, language=language,
    )
    return {
        "data": [public_document(document) for document in documents],
        "pagination": pagination_metadata(page, pageSize, total),
    }


@router.get("/{templateId}")
async def get_whatsapp_template_route(
    templateId: str,
    user=Depends(require_authenticated_user),
):
    return {"data": public_document(get_template_detail(templateId))}

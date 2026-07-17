from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import Response

from app.api.dependencies.auth import require_super_admin
from app.schemas.contact_import_schema import ContactImportPreviewModel
from app.services.contact_import_service import (
    MAX_IMPORT_FILE_BYTES,
    analyze_import,
    commit_import,
    import_detail,
    preview_import,
    rejection_report,
)
from app.utils.mongo_utils import public_document


router = APIRouter(prefix="/contact-imports", tags=["Contact Imports"])


@router.post("/analyze", status_code=status.HTTP_201_CREATED)
async def analyze_contact_import_route(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(require_super_admin),
):
    content = await file.read(MAX_IMPORT_FILE_BYTES + 1)
    job = analyze_import(
        filename=file.filename,
        content_type=file.content_type,
        content=content,
        actor=user,
        request_id=request.state.request_id,
    )
    data = public_document(job)
    data.pop("fileHash", None)
    return {"data": data}


@router.post("/{importId}/preview")
async def preview_contact_import_route(
    importId: str,
    payload: ContactImportPreviewModel,
    request: Request,
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=100),
    user=Depends(require_super_admin),
):
    return {
        "data": preview_import(
            importId, payload, user, request.state.request_id, page=page, page_size=pageSize
        )
    }


@router.post("/{importId}/commit")
async def commit_contact_import_route(
    importId: str,
    request: Request,
    user=Depends(require_super_admin),
):
    result = public_document(commit_import(importId, user, request.state.request_id))
    result.pop("fileHash", None)
    return {"data": result}


@router.get("/{importId}")
async def get_contact_import_route(
    importId: str,
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=100),
    user=Depends(require_super_admin),
):
    return {"data": import_detail(importId, page=page, page_size=pageSize)}


@router.get("/{importId}/rejections")
async def download_contact_import_rejections_route(
    importId: str,
    user=Depends(require_super_admin),
):
    filename, content = rejection_report(importId)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

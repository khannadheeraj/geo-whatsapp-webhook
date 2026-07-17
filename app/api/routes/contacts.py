from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.dependencies.auth import require_authenticated_user, require_super_admin
from app.api.response_helpers import pagination_metadata
from app.schemas.contact_schema import (
    ContactCreateModel,
    ContactPatchModel,
    ContactPreferencePatchModel,
)
from app.services.contact_service import (
    create_contact,
    get_contact,
    get_contact_detail,
    list_contacts,
    patch_contact,
)
from app.services.preference_service import update_preferences
from app.utils.mongo_utils import public_document


router = APIRouter(prefix="/contacts", tags=["Contacts"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_contact_route(
    payload: ContactCreateModel,
    request: Request,
    user=Depends(require_authenticated_user),
):
    result = create_contact(payload, user, request.state.request_id)
    return {
        "data": {
            "contact": public_document(result["contact"]),
            "preferences": public_document(result["preferences"]),
            "lead": public_document(result["lead"]),
        }
    }


@router.get("")
async def list_contacts_route(
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=100),
    search: Optional[str] = Query(default=None, max_length=200),
    city: Optional[str] = Query(default=None, max_length=100),
    source: Optional[str] = Query(default=None, max_length=100),
    isActive: Optional[bool] = None,
    doNotContact: Optional[bool] = None,
    createdFrom: Optional[datetime] = None,
    createdTo: Optional[datetime] = None,
    sort: str = Query("-createdAt", max_length=50),
    user=Depends(require_authenticated_user),
):
    documents, total, preferences = list_contacts(
        user,
        page=page,
        page_size=pageSize,
        search=search,
        city=city,
        source=source,
        is_active=isActive,
        do_not_contact=doNotContact,
        created_from=createdFrom,
        created_to=createdTo,
        sort=sort,
    )
    data = []
    for document in documents:
        item = public_document(document)
        preference = preferences.get(document["_id"])
        item["communicationPreferences"] = (
            {
                "whatsappAllowed": bool(preference.get("whatsappAllowed")),
                "marketingAllowed": bool(preference.get("marketingAllowed")),
                "doNotContact": bool(preference.get("doNotContact")),
                "version": preference.get("version"),
            }
            if preference
            else None
        )
        data.append(item)
    return {"data": data, "pagination": pagination_metadata(page, pageSize, total)}


@router.get("/{contactId}")
async def get_contact_route(
    contactId: str,
    user=Depends(require_authenticated_user),
):
    result = get_contact_detail(contactId, user)
    return {
        "data": {
            "contact": public_document(result["contact"]),
            "preferences": public_document(result["preferences"]),
            "activeLead": public_document(result["activeLead"]),
        }
    }


@router.patch("/{contactId}")
async def patch_contact_route(
    contactId: str,
    payload: ContactPatchModel,
    request: Request,
    user=Depends(require_authenticated_user),
):
    contact = patch_contact(contactId, payload, user, request.state.request_id)
    return {"data": public_document(contact)}


@router.patch("/{contactId}/preferences")
async def patch_contact_preferences_route(
    contactId: str,
    payload: ContactPreferencePatchModel,
    request: Request,
    user=Depends(require_super_admin),
):
    contact = get_contact(contactId, user)
    preference = update_preferences(contact, payload, user, request.state.request_id)
    return {"data": public_document(preference)}

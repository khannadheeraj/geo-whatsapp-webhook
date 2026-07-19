from fastapi import APIRouter, Depends, Header, Request

from app.api.dependencies.auth import require_authenticated_user
from app.schemas.whatsapp_template_send_schema import WhatsAppTemplateSendModel
from app.services.whatsapp_template_send_service import send_template_to_contact


router = APIRouter(prefix="/whatsapp-template-sends", tags=["WhatsApp Template Sends"])


@router.post("")
async def send_whatsapp_template_route(
    payload: WhatsAppTemplateSendModel,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=200),
    user=Depends(require_authenticated_user),
):
    return {"data": send_template_to_contact(
        contact_id_value=payload.contactId, template_id_value=payload.templateId,
        variable_values=payload.variableValues, idempotency_key=idempotency_key,
        actor=user, request_id=request.state.request_id,
    )}

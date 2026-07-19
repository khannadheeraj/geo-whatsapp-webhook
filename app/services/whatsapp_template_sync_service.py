import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import WHATSAPP_WABA_ID
from app.errors import ApiError, NotFoundError
from app.repositories import whatsapp_template_repository as repository
from app.services.audit_service import write_audit_event
from app.services.template_service import MetaTemplateFetchError, fetch_meta_templates


VARIABLE_PATTERN = re.compile(r"{{\s*(\d+)\s*}}")
MAX_TEXT_LENGTH = 4096


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: Any, limit: int = MAX_TEXT_LENGTH) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned[:limit] or None


def _variables(component_type: str, text: Optional[str]) -> List[Dict[str, Any]]:
    if not text:
        return []
    return [
        {"componentType": component_type, "position": int(position)}
        for position in sorted({int(match) for match in VARIABLE_PATTERN.findall(text)})
    ]


def _button(button: Dict[str, Any]) -> Dict[str, Any]:
    fields = ("type", "text", "url", "phone_number", "flow_id", "flow_action", "payload")
    return {
        field: _text(button.get(field), 1000) if field != "type" else _text(button.get(field), 100)
        for field in fields if _text(button.get(field), 1000 if field != "type" else 100)
    }


def _button_variables(button: Dict[str, Any], button_index: int) -> List[Dict[str, Any]]:
    variables: List[Dict[str, Any]] = []
    for field in ("text", "url"):
        for variable in _variables("BUTTON", button.get(field)):
            variables.append({**variable, "buttonIndex": button_index, "field": field})
    return variables


def normalize_meta_template(template: Dict[str, Any], business_account_id: str) -> Optional[Dict[str, Any]]:
    provider_id = _text(template.get("id"), 200)
    name = _text(template.get("name"), 512)
    language = _text(template.get("language"), 100)
    if not name or not language:
        return None
    provider_key = provider_id or name
    components: List[Dict[str, Any]] = []
    headers: List[Dict[str, Any]] = []
    body: Optional[Dict[str, Any]] = None
    footer: Optional[Dict[str, Any]] = None
    buttons: List[Dict[str, Any]] = []
    variables: List[Dict[str, Any]] = []

    source_components = template.get("components", [])
    if not isinstance(source_components, list):
        source_components = []
    for source in source_components:
        if not isinstance(source, dict):
            continue
        component_type = (_text(source.get("type"), 100) or "").upper()
        if component_type not in {"HEADER", "BODY", "FOOTER", "BUTTONS"}:
            continue
        normalized = {"type": component_type}
        component_format = _text(source.get("format"), 100)
        text = _text(source.get("text"))
        if component_format:
            normalized["format"] = component_format.upper()
        if text:
            normalized["text"] = text
        component_variables = _variables(component_type, text)
        if component_variables:
            normalized["variables"] = component_variables
            variables.extend(component_variables)
        if component_type == "BUTTONS":
            component_buttons = source.get("buttons", [])
            if isinstance(component_buttons, list):
                normalized["buttons"] = [_button(item) for item in component_buttons if isinstance(item, dict)]
                buttons.extend(normalized["buttons"])
                for index, button in enumerate(normalized["buttons"]):
                    button_variables = _button_variables(button, index)
                    variables.extend(button_variables)
                    if button_variables:
                        normalized.setdefault("variables", []).extend(button_variables)
        components.append(normalized)
        if component_type == "HEADER":
            headers.append(normalized)
        elif component_type == "BODY":
            body = normalized
        elif component_type == "FOOTER":
            footer = normalized

    status = (_text(template.get("status"), 100) or "UNKNOWN").upper()
    category = (_text(template.get("category"), 100) or "UNKNOWN").upper()
    now = _now()
    return {
        "businessAccountId": business_account_id,
        "providerTemplateId": provider_id,
        "providerTemplateKey": provider_key,
        "name": name,
        "normalizedName": name.casefold(),
        "language": language,
        "category": category,
        "status": status,
        "isActive": status == "APPROVED",
        "components": components,
        "variables": variables,
        "headers": headers,
        "body": body,
        "footer": footer,
        "buttons": buttons,
        "updatedAt": now,
    }


def sync_templates(actor: Dict[str, Any], request_id: str) -> Dict[str, int]:
    if not WHATSAPP_WABA_ID:
        raise ApiError(503, "WHATSAPP_TEMPLATE_SYNC_UNAVAILABLE", "WhatsApp template sync is not configured.")
    sync_id = str(uuid.uuid4())
    try:
        source_templates = fetch_meta_templates()
    except MetaTemplateFetchError as exc:
        write_audit_event(
            "WHATSAPP_TEMPLATE_SYNC", "FAILED", actor_user_id=actor["_id"],
            entity_type="WHATSAPP_TEMPLATE_SYNC", request_id=request_id,
            compact_metadata={"reasonCode": str(exc)}, operation_id=f"whatsapp-template-sync:{sync_id}",
        )
        raise ApiError(502, "WHATSAPP_TEMPLATE_SYNC_FAILED", "WhatsApp templates could not be synchronized.") from exc

    created = 0
    skipped = 0
    for source in source_templates:
        normalized = normalize_meta_template(source, WHATSAPP_WABA_ID)
        if not normalized:
            skipped += 1
            continue
        normalized["lastSeenSyncId"] = sync_id
        normalized["lastSyncedAt"] = normalized["updatedAt"]
        created += int(repository.upsert_template(
            {
                "businessAccountId": WHATSAPP_WABA_ID,
                "providerTemplateKey": normalized["providerTemplateKey"],
                "language": normalized["language"],
            }, normalized,
        ))

    now = _now()
    deactivated = repository.deactivate_templates_missing_from_sync(
        WHATSAPP_WABA_ID, sync_id,
        {"isActive": False, "deactivatedAt": now, "updatedAt": now},
    )
    counts = {
        "fetched": len(source_templates), "created": created,
        "updated": len(source_templates) - created - skipped,
        "skipped": skipped, "deactivated": deactivated,
    }
    write_audit_event(
        "WHATSAPP_TEMPLATE_SYNC", "SUCCEEDED", actor_user_id=actor["_id"],
        entity_type="WHATSAPP_TEMPLATE_SYNC", request_id=request_id,
        compact_metadata=counts, operation_id=f"whatsapp-template-sync:{sync_id}",
    )
    return counts


def list_templates(*, page: int, page_size: int, search: Optional[str], category: Optional[str], language: Optional[str]):
    query: Dict[str, Any] = {
        "businessAccountId": WHATSAPP_WABA_ID,
        "status": "APPROVED",
        "isActive": True,
    }
    if search and search.strip():
        query["normalizedName"] = {"$regex": re.escape(search.strip().casefold())}
    if category and category.strip():
        query["category"] = category.strip().upper()
    if language and language.strip():
        query["language"] = language.strip()
    return repository.list_approved_active_templates(query, page=page, page_size=page_size)


def get_template_detail(template_id: str) -> Dict[str, Any]:
    document = repository.find_approved_active_template(template_id, WHATSAPP_WABA_ID)
    if not document:
        raise NotFoundError("WHATSAPP_TEMPLATE_NOT_FOUND", "The requested approved template was not found.")
    return document

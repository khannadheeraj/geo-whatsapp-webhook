import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from app.api.dependencies.auth import assert_super_admin_or_assigned
from app.config import WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_WABA_ID
from app.errors import ApiError, ConflictError, NotFoundError, ValidationApiError
from app.models.crm_model import ActivityType
from app.repositories import whatsapp_template_send_repository as operation_repository
from app.repositories.contact_repository import find_contact_by_id
from app.repositories.lead_repository import find_active_lead_by_contact
from app.repositories.whatsapp_template_repository import find_approved_active_template
from app.services.activity_service import record_activity
from app.services.audit_service import write_audit_event
from app.services.preference_service import get_contact_communication_eligibility
from app.services.whatsapp_message_service import record_outbound_template_message
from app.services.whatsapp_sender import send_whatsapp_template
from app.utils.mongo_utils import object_id_or_not_found
from app.utils.phone_utils import normalize_indian_phone


VARIABLE_PATTERN = re.compile(r"{{\s*(\d+)\s*}}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _template_variables(template: Dict[str, Any]) -> List[Dict[str, Any]]:
    variables: List[Dict[str, Any]] = []
    for header in template.get("headers") or []:
        if not isinstance(header, dict):
            raise ValidationApiError("TEMPLATE_COMPONENT_INVALID", "The approved template has an invalid component.")
        text = header.get("text")
        positions = sorted({int(value) for value in VARIABLE_PATTERN.findall(text or "")})
        if positions:
            if header.get("format") not in {None, "TEXT"}:
                raise ValidationApiError("TEMPLATE_COMPONENT_UNSUPPORTED", "The approved template has an unsupported variable component.")
            variables.extend({"componentType": "HEADER", "position": position} for position in positions)
    body = template.get("body") or {}
    if body and not isinstance(body, dict):
        raise ValidationApiError("TEMPLATE_COMPONENT_INVALID", "The approved template has an invalid component.")
    variables.extend(
        {"componentType": "BODY", "position": position}
        for position in sorted({int(value) for value in VARIABLE_PATTERN.findall(body.get("text") or "")})
    )
    footer = template.get("footer") or {}
    if footer and VARIABLE_PATTERN.search(footer.get("text") or ""):
        raise ValidationApiError("TEMPLATE_COMPONENT_UNSUPPORTED", "The approved template has an unsupported variable component.")
    for index, button in enumerate(template.get("buttons") or []):
        if not isinstance(button, dict):
            raise ValidationApiError("TEMPLATE_COMPONENT_INVALID", "The approved template has an invalid component.")
        for position in sorted({int(value) for value in VARIABLE_PATTERN.findall(button.get("url") or "")}):
            if str(button.get("type") or "").upper() != "URL":
                raise ValidationApiError("TEMPLATE_COMPONENT_UNSUPPORTED", "The approved template has an unsupported variable component.")
            variables.append({"componentType": "BUTTON", "position": position, "buttonIndex": index, "field": "url"})
        if VARIABLE_PATTERN.search(button.get("text") or ""):
            raise ValidationApiError("TEMPLATE_COMPONENT_UNSUPPORTED", "The approved template has an unsupported variable component.")
    return variables


def _validated_values(values: List[str], expected: List[Dict[str, Any]]) -> List[str]:
    if len(values) != len(expected):
        raise ValidationApiError(
            "TEMPLATE_VARIABLE_COUNT_INVALID",
            "Provide exactly the required number of template variables.",
            {"variableValues": f"Expected {len(expected)} value(s)."},
        )
    normalized: List[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or len(cleaned) > 1000:
            raise ValidationApiError(
                "TEMPLATE_VARIABLE_INVALID",
                "Each template variable must contain a value up to 1000 characters.",
                {"variableValues": "Enter a valid template variable."},
            )
        normalized.append(cleaned)
    return normalized


def _render(text: str, values_by_position: Dict[int, str]) -> str:
    return VARIABLE_PATTERN.sub(lambda match: values_by_position[int(match.group(1))], text)


def _render_and_build_components(
    template: Dict[str, Any], expected: List[Dict[str, Any]], values: List[str]
) -> Tuple[str, List[Dict[str, Any]]]:
    grouped: Dict[str, Dict[int, str]] = {"HEADER": {}, "BODY": {}, "BUTTON": {}}
    button_values: Dict[int, Dict[int, str]] = {}
    for descriptor, value in zip(expected, values):
        if descriptor["componentType"] == "BUTTON":
            button_values.setdefault(int(descriptor["buttonIndex"]), {})[int(descriptor["position"])] = value
        else:
            grouped[descriptor["componentType"]][int(descriptor["position"])] = value

    components: List[Dict[str, Any]] = []
    rendered_parts: List[str] = []
    for header in template.get("headers") or []:
        text = header.get("text")
        if text:
            rendered_parts.append(_render(text, grouped["HEADER"]))
        if grouped["HEADER"]:
            components.append({
                "type": "header",
                "parameters": [{"type": "text", "text": grouped["HEADER"][position]} for position in sorted(grouped["HEADER"])],
            })
    body = template.get("body") or {}
    body_text = body.get("text")
    if body_text:
        rendered_parts.append(_render(body_text, grouped["BODY"]))
    if grouped["BODY"]:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": grouped["BODY"][position]} for position in sorted(grouped["BODY"])],
        })
    footer = (template.get("footer") or {}).get("text")
    if footer:
        rendered_parts.append(footer)
    for index, button in enumerate(template.get("buttons") or []):
        text = button.get("text")
        if text:
            rendered_parts.append(text)
        if index in button_values:
            components.append({
                "type": "button", "sub_type": "url", "index": str(index),
                "parameters": [{"type": "text", "text": button_values[index][position]} for position in sorted(button_values[index])],
            })
    return "\n\n".join(rendered_parts), components


def _request_hash(contact_id: str, template_id: str, variable_values: List[str]) -> str:
    material = json.dumps(
        {"contactId": contact_id, "templateId": template_id, "variableValues": variable_values},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _safe_result(operation: Dict[str, Any], *, replayed: bool) -> Dict[str, Any]:
    return {
        "contactId": str(operation["contactId"]),
        "templateId": str(operation["templateId"]),
        "providerMessageId": operation.get("providerMessageId"),
        "status": operation.get("status"),
        "renderedText": operation.get("renderedText"),
        "idempotentReplay": replayed,
    }


def send_template_to_contact(
    *, contact_id_value: str, template_id_value: str, variable_values: List[str],
    idempotency_key: str, actor: Dict[str, Any], request_id: str,
) -> Dict[str, Any]:
    contact_id = object_id_or_not_found(contact_id_value, "contact")
    contact = find_contact_by_id(contact_id)
    if not contact:
        raise NotFoundError("CONTACT_NOT_FOUND", "The requested contact was not found.")
    if not contact.get("isActive"):
        raise ValidationApiError("CONTACT_INACTIVE", "The Contact is inactive.")
    lead = find_active_lead_by_contact(contact_id)
    assert_super_admin_or_assigned(actor, lead.get("assignedCounsellorId") if lead else None)
    try:
        phone = normalize_indian_phone(contact.get("normalizedPhone"), "contactId")
    except ValidationApiError as exc:
        raise ValidationApiError("CONTACT_WHATSAPP_PHONE_INVALID", "The Contact has no valid WhatsApp phone number.") from exc
    template = find_approved_active_template(template_id_value, WHATSAPP_WABA_ID)
    if not template:
        raise NotFoundError("WHATSAPP_TEMPLATE_NOT_FOUND", "The requested approved template was not found.")
    if not template.get("language"):
        raise ValidationApiError("TEMPLATE_LANGUAGE_INVALID", "The approved template has no valid language.")
    eligibility = get_contact_communication_eligibility(
        contact_id, promotional=template.get("category") == "MARKETING"
    )
    if not eligibility.get("allowed"):
        raise ValidationApiError(
            "CONTACT_WHATSAPP_NOT_ELIGIBLE",
            "WhatsApp sending is not allowed for this Contact.",
            {"contactId": eligibility.get("reasonCode", "NOT_ELIGIBLE")},
        )
    expected = _template_variables(template)
    values = _validated_values(variable_values, expected)
    rendered_text, provider_components = _render_and_build_components(template, expected, values)
    if not rendered_text:
        raise ValidationApiError("TEMPLATE_COMPONENT_INVALID", "The approved template has no renderable content.")
    request_hash = _request_hash(contact_id_value, template_id_value, values)
    operation_id = f"whatsapp-template-send:{uuid.uuid4()}"
    operation, claimed = operation_repository.claim_send_operation({
        "actorUserId": actor["_id"], "idempotencyKey": idempotency_key,
        "requestHash": request_hash, "operationId": operation_id,
        "contactId": contact_id, "templateId": template["_id"], "templateName": template["name"],
        "templateLanguage": template["language"], "status": "PENDING",
        "createdAt": _now(), "updatedAt": _now(),
    })
    if not claimed:
        if operation.get("requestHash") != request_hash:
            raise ConflictError("IDEMPOTENCY_KEY_REUSED", "The idempotency key was already used for a different request.")
        if operation.get("status") == "ACCEPTED":
            return _safe_result(operation, replayed=True)
        if operation.get("status") == "FAILED":
            raise ApiError(502, operation.get("failureCode", "WHATSAPP_TEMPLATE_SEND_FAILED"), "The previous send attempt did not complete.")
        raise ConflictError("WHATSAPP_TEMPLATE_SEND_IN_PROGRESS", "A template send with this idempotency key is already in progress.")

    result = send_whatsapp_template(
        phone, template["name"], language_code=template["language"],
        template_components=provider_components or None,
    )
    if not result.get("success"):
        failure_code = result.get("error") or "WHATSAPP_TEMPLATE_SEND_FAILED"
        operation_repository.complete_send_operation(operation["_id"], {
            "status": "FAILED", "failureCode": failure_code, "updatedAt": _now(), "completedAt": _now(),
        })
        write_audit_event(
            "WHATSAPP_TEMPLATE_SEND", "FAILED", actor_user_id=actor["_id"],
            entity_type="WHATSAPP_TEMPLATE_SEND", entity_id=operation["_id"], request_id=request_id,
            compact_metadata={"reasonCode": failure_code, "contactId": contact_id, "templateId": template["_id"]},
            operation_id=operation_id,
        )
        raise ApiError(502, "WHATSAPP_TEMPLATE_SEND_FAILED", "WhatsApp template could not be sent.")
    provider_message_id = ((result.get("response") or {}).get("messages") or [{}])[0].get("id")
    if not provider_message_id:
        operation_repository.complete_send_operation(operation["_id"], {
            "status": "FAILED", "failureCode": "WHATSAPP_PROVIDER_RESPONSE_INVALID", "updatedAt": _now(), "completedAt": _now(),
        })
        raise ApiError(502, "WHATSAPP_TEMPLATE_SEND_FAILED", "WhatsApp template could not be sent.")
    message = record_outbound_template_message(
        provider_message_id=provider_message_id, phone=phone, template_name=template["name"],
        template_language=template["language"], rendered_text=rendered_text,
        phone_number_id=WHATSAPP_PHONE_NUMBER_ID or None,
    )
    operation = operation_repository.complete_send_operation(operation["_id"], {
        "status": "ACCEPTED", "providerMessageId": provider_message_id, "messageId": message["_id"],
        "renderedText": rendered_text, "updatedAt": _now(), "completedAt": _now(),
    })
    record_activity(
        ActivityType.WHATSAPP_TEMPLATE_SENT.value, "Approved WhatsApp template sent.",
        contact_id=contact_id, lead_id=lead["_id"] if lead else None, actor_user_id=actor["_id"],
        metadata={"templateId": template["_id"], "templateName": template["name"], "providerMessageId": provider_message_id},
        related_entity_type="WHATSAPP_MESSAGE", related_entity_id=message["_id"], operation_id=operation_id,
    )
    write_audit_event(
        "WHATSAPP_TEMPLATE_SEND", "SUCCEEDED", actor_user_id=actor["_id"],
        entity_type="WHATSAPP_MESSAGE", entity_id=message["_id"], request_id=request_id,
        compact_metadata={"contactId": contact_id, "templateId": template["_id"], "providerMessageId": provider_message_id},
        operation_id=operation_id,
    )
    return _safe_result(operation, replayed=False)

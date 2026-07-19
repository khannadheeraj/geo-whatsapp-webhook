from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from bson import ObjectId

from app.config import WHATSAPP_WABA_ID
from app.errors import ConflictError, NotFoundError, ValidationApiError
from app.repositories import whatsapp_broadcast_repository as repository
from app.repositories.whatsapp_template_repository import find_approved_active_template
from app.services.audit_service import write_audit_event
from app.services.whatsapp_template_send_service import _render_and_build_components, _template_variables
from app.utils.mongo_utils import object_id_or_not_found
from app.utils.phone_utils import normalize_indian_phone
from app.db.mongodb import get_collection


CONTACT_FIELDS = {"firstName", "lastName", "displayName", "email", "city", "state", "normalizedPhone", "phone", "source"}
LEAD_FIELDS = {"status", "priority", "source", "preferredMode", "targetExamYear", "coursePreference"}
FILTER_FIELDS = {"contact": {"source", "city", "state"}, "lead": {"status", "priority", "source", "preferredMode", "targetExamYear", "assignedCounsellorId"}}


def _now(): return datetime.now(timezone.utc)


def _mapping_dict(item) -> Dict[str, Any]:
    return item.model_dump() if hasattr(item, "model_dump") else dict(item)


def _validate_filters(filters: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(filters, dict):
        raise ValidationApiError("BROADCAST_FILTERS_INVALID", "Recipient filters must be an object.")
    clean = {"contact": {}, "lead": {}}
    for group in clean:
        supplied = filters.get(group, {})
        if supplied is None: supplied = {}
        if not isinstance(supplied, dict) or any(key not in FILTER_FIELDS[group] for key in supplied):
            raise ValidationApiError("BROADCAST_FILTERS_INVALID", "Recipient filters contain an unsupported field.")
        clean[group] = {key: value for key, value in supplied.items() if value not in (None, "", [])}
    return clean


def _validate_mappings(template: Dict[str, Any], mappings: List[Any]) -> List[Dict[str, Any]]:
    expected = _template_variables(template)
    if len(mappings) != len(expected):
        raise ValidationApiError("BROADCAST_VARIABLE_MAPPING_COUNT_INVALID", "Provide one mapping for every required template variable.")
    clean = []
    for mapping in mappings:
        value = _mapping_dict(mapping)
        source = value.get("source")
        field = (value.get("field") or "").strip()
        fixed = (value.get("value") or "").strip()
        if source == "CONTACT" and field not in CONTACT_FIELDS:
            raise ValidationApiError("BROADCAST_VARIABLE_MAPPING_INVALID", "The Contact variable field is not supported.")
        if source == "LEAD" and field not in LEAD_FIELDS:
            raise ValidationApiError("BROADCAST_VARIABLE_MAPPING_INVALID", "The Lead variable field is not supported.")
        if source == "FIXED" and not fixed:
            raise ValidationApiError("BROADCAST_VARIABLE_MAPPING_INVALID", "A fixed variable value is required.")
        clean.append({"source": source, **({"field": field} if source != "FIXED" else {"value": fixed})})
    return clean


def create_broadcast(payload, actor: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    template = find_approved_active_template(payload.templateId, WHATSAPP_WABA_ID)
    if not template: raise NotFoundError("WHATSAPP_TEMPLATE_NOT_FOUND", "The requested approved template was not found.")
    filters = _validate_filters(payload.recipientFilters)
    mappings = _validate_mappings(template, payload.variableMappings)
    now = _now()
    document = repository.insert_broadcast({
        "status": "DRAFT", "version": 1, "templateId": template["_id"], "templateName": template["name"],
        "templateLanguage": template["language"], "templateCategory": template.get("category"),
        "recipientFilters": filters, "variableMappings": mappings, "createdBy": actor["_id"], "createdAt": now, "updatedAt": now,
        "preparationCounts": {"eligible": 0, "skipped": 0, "rejected": 0, "byReason": {}},
    })
    write_audit_event("WHATSAPP_BROADCAST_CREATED", "SUCCEEDED", actor_user_id=actor["_id"], entity_type="WHATSAPP_BROADCAST", entity_id=document["_id"], request_id=request_id, compact_metadata={"templateId": template["_id"]})
    return document


def get_broadcast(value: str) -> Dict[str, Any]:
    document = repository.find_broadcast(object_id_or_not_found(value, "broadcast"))
    if not document: raise NotFoundError("WHATSAPP_BROADCAST_NOT_FOUND", "The requested broadcast was not found.")
    return document


def _matches(document: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    return all(document.get(field) == value or (isinstance(value, list) and document.get(field) in value) for field, value in filters.items())


def _value(mapping: Dict[str, Any], contact: Dict[str, Any], lead: Dict[str, Any]):
    if mapping["source"] == "FIXED": return mapping["value"]
    source = contact if mapping["source"] == "CONTACT" else lead
    value = source.get(mapping["field"]) if source else None
    return str(value).strip() if value is not None else ""


def _candidate_contacts(filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    query = {"entityType": "CONTACT", **filters["contact"]}
    return list(get_collection("contacts").find(query))


def prepare_broadcast(value: str, version: int, actor: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    broadcast_id = object_id_or_not_found(value, "broadcast")
    broadcast = repository.claim_preparation(broadcast_id, version, {"status": "PREPARING", "updatedAt": _now(), "preparationStartedAt": _now()})
    if not broadcast:
        current = repository.find_broadcast(broadcast_id)
        if not current: raise NotFoundError("WHATSAPP_BROADCAST_NOT_FOUND", "The requested broadcast was not found.")
        raise ConflictError("WHATSAPP_BROADCAST_VERSION_CONFLICT", "The broadcast was changed by another request.")
    template = find_approved_active_template(str(broadcast["templateId"]), WHATSAPP_WABA_ID)
    if not template: raise ConflictError("WHATSAPP_BROADCAST_TEMPLATE_UNAVAILABLE", "The draft template is no longer approved and active.")
    leads = {lead["contactId"]: lead for lead in get_collection("leads").find({"entityType": "ADMISSION_LEAD", "isActive": True})}
    preferences = {item["contactId"]: item for item in get_collection("contact_preferences").find({"channel": "WHATSAPP"})}
    phones = Counter(contact.get("normalizedPhone") for contact in _candidate_contacts(broadcast["recipientFilters"]) if contact.get("normalizedPhone"))
    recipients: List[Dict[str, Any]] = []
    now = _now()
    for contact in _candidate_contacts(broadcast["recipientFilters"]):
        lead = leads.get(contact["_id"])
        if not _matches(lead or {}, broadcast["recipientFilters"]["lead"]): continue
        status, reason, rendered, provider_components = "ELIGIBLE", None, None, None
        if not contact.get("isActive"): status, reason = "SKIPPED", "CONTACT_INACTIVE"
        else:
            try: phone = normalize_indian_phone(contact.get("normalizedPhone"), "phone")
            except ValidationApiError: status, reason, phone = "SKIPPED", "PHONE_INVALID", None
            if phone and phones[phone] > 1: status, reason = "SKIPPED", "PHONE_DUPLICATE"
            pref = preferences.get(contact["_id"], {})
            if status == "ELIGIBLE" and pref.get("doNotContact"): status, reason = "SKIPPED", "DO_NOT_CONTACT"
            if status == "ELIGIBLE" and not pref.get("whatsappAllowed"): status, reason = "SKIPPED", "WHATSAPP_DISABLED"
            if status == "ELIGIBLE" and broadcast.get("templateCategory") == "MARKETING" and not pref.get("marketingAllowed"): status, reason = "SKIPPED", "MARKETING_CONSENT_MISSING"
            if status == "ELIGIBLE":
                values = [_value(mapping, contact, lead or {}) for mapping in broadcast["variableMappings"]]
                if any(not item for item in values): status, reason = "REJECTED", "TEMPLATE_VARIABLE_MISSING"
                else: rendered, provider_components = _render_and_build_components(template, _template_variables(template), values)
        recipients.append({"broadcastId": broadcast_id, "contactId": contact["_id"], "leadId": lead.get("_id") if lead else None, "normalizedPhone": contact.get("normalizedPhone"), "displayName": contact.get("displayName"), "status": status, "exclusionReason": reason, "renderedText": rendered, "providerComponents": provider_components, "preparedAt": now})
    repository.replace_recipients(broadcast_id, recipients)
    reasons = Counter(item["exclusionReason"] for item in recipients if item["exclusionReason"])
    counts = {"eligible": sum(item["status"] == "ELIGIBLE" for item in recipients), "skipped": sum(item["status"] == "SKIPPED" for item in recipients), "rejected": sum(item["status"] == "REJECTED" for item in recipients), "byReason": dict(reasons)}
    result = repository.finish_preparation(broadcast_id, broadcast["version"], {"status": "DRAFT", "updatedAt": _now(), "preparedAt": now, "preparationCounts": counts})
    if not result: raise ConflictError("WHATSAPP_BROADCAST_VERSION_CONFLICT", "The broadcast was changed while recipients were prepared.")
    write_audit_event("WHATSAPP_BROADCAST_PREPARED", "SUCCEEDED", actor_user_id=actor["_id"], entity_type="WHATSAPP_BROADCAST", entity_id=broadcast_id, request_id=request_id, compact_metadata=counts)
    return result


def recipients(value: str, status: str | None, page: int, page_size: int) -> Tuple[List[Dict[str, Any]], int]:
    broadcast = get_broadcast(value)
    query: Dict[str, Any] = {"broadcastId": broadcast["_id"]}
    if status: query["status"] = status
    return repository.list_recipients(query, page=page, page_size=page_size)


def delete_broadcast(value: str, version: int, actor: Dict[str, Any], request_id: str) -> None:
    broadcast_id = object_id_or_not_found(value, "broadcast")
    if not repository.delete_draft(broadcast_id, version): raise ConflictError("WHATSAPP_BROADCAST_VERSION_CONFLICT", "Only an unchanged draft broadcast can be deleted.")
    write_audit_event("WHATSAPP_BROADCAST_DELETED", "SUCCEEDED", actor_user_id=actor["_id"], entity_type="WHATSAPP_BROADCAST", entity_id=broadcast_id, request_id=request_id)

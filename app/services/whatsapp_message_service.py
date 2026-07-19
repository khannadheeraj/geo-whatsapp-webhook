from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from app.repositories import contact_repository, lead_repository
from app.repositories import whatsapp_message_repository as repository
from app.errors import ValidationApiError
from app.utils.phone_utils import clean_phone_number, normalize_indian_phone


CHANNEL = "WHATSAPP"
FAILURE_DETAIL_RETENTION_DAYS = 7
SUPPORTED_STATUSES = {"accepted", "sent", "delivered", "read", "failed"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _provider_time(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return _now()


def _normalized_phone(value: Any) -> Optional[str]:
    if not value:
        return None
    try:
        return normalize_indian_phone(str(value), "whatsappPhone")
    except ValidationApiError:
        cleaned = clean_phone_number(str(value))
        return cleaned[:20] or None


def _links(normalized_phone: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if not normalized_phone:
        return None, None
    contact = contact_repository.find_contact_by_normalized_phone(normalized_phone)
    lead = lead_repository.find_active_lead_by_contact(contact["_id"]) if contact else None
    return contact, lead


def _conversation(
    normalized_phone: str,
    phone_number_id: Optional[str],
    contact: Optional[Dict[str, Any]],
    lead: Optional[Dict[str, Any]],
    occurred_at: datetime,
    *,
    direction: str,
    preview: Optional[str] = None,
) -> Dict[str, Any]:
    now = _now()
    identity = {
        "channel": CHANNEL,
        "phoneNumberId": str(phone_number_id or ""),
        "normalizedPhone": normalized_phone,
    }
    updates: Dict[str, Any] = {
        "latestMessageAt": occurred_at,
        "updatedAt": now,
        "reconciliationStatus": "MATCHED" if contact else "UNKNOWN_NUMBER",
    }
    if direction == "INBOUND":
        updates["latestInboundAt"] = occurred_at
    else:
        updates["latestOutboundAt"] = occurred_at
    if preview:
        updates["latestMessagePreview"] = preview[:160]
    if contact:
        updates["contactId"] = contact["_id"]
    if lead:
        updates["leadId"] = lead["_id"]
        updates["assignedCounsellorId"] = lead.get("assignedCounsellorId")
    defaults = {
        **identity,
        "createdAt": now,
    }
    return repository.upsert_conversation(identity, updates, defaults)


def _base_message(
    provider_message_id: str,
    conversation: Optional[Dict[str, Any]],
    normalized_phone: Optional[str],
    contact: Optional[Dict[str, Any]],
    lead: Optional[Dict[str, Any]],
    occurred_at: datetime,
    direction: str,
) -> Dict[str, Any]:
    now = _now()
    return {
        "conversationId": conversation.get("_id") if conversation else None,
        "contactId": contact.get("_id") if contact else None,
        "leadId": lead.get("_id") if lead else None,
        "normalizedPhone": normalized_phone,
        "providerMessageId": provider_message_id,
        "direction": direction,
        "providerTimestamp": occurred_at,
        "receivedAt": now,
        "createdAt": now,
        "updatedAt": now,
    }


def record_outbound_template_message(
    *,
    provider_message_id: str,
    phone: str,
    template_name: str,
    rendered_text: Optional[str],
    template_language: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    accepted_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Foundation contract for senders; Phase 2A does not alter sending workflows."""
    occurred_at = accepted_at or _now()
    normalized_phone = _normalized_phone(phone)
    contact, lead = _links(normalized_phone)
    conversation = (
        _conversation(
            normalized_phone,
            phone_number_id,
            contact,
            lead,
            occurred_at,
            direction="OUTBOUND",
            preview=rendered_text,
        )
        if normalized_phone else None
    )
    document = {
        **_base_message(
            provider_message_id, conversation, normalized_phone, contact, lead,
            occurred_at, "OUTBOUND"
        ),
        "type": "TEMPLATE",
        "templateName": template_name,
        "templateLanguage": template_language,
        "renderedText": rendered_text,
        "status": "ACCEPTED",
        "acceptedAt": occurred_at,
    }
    repository.upsert_outbound_message(document)
    repository.enrich_message_if_missing(
        provider_message_id,
        {
            "conversationId": conversation.get("_id") if conversation else None,
            "contactId": contact.get("_id") if contact else None,
            "leadId": lead.get("_id") if lead else None,
            "normalizedPhone": normalized_phone,
            "type": "TEMPLATE",
            "templateName": template_name,
            "templateLanguage": template_language,
            "renderedText": rendered_text,
            "acceptedAt": occurred_at,
        },
    )
    return repository.apply_status(provider_message_id, "ACCEPTED", occurred_at)


def record_outbound_text_message(*, provider_message_id: str, conversation: Dict[str, Any], contact: Dict[str, Any], lead: Optional[Dict[str, Any]], text: str) -> Dict[str, Any]:
    occurred_at = _now()
    document = {**_base_message(provider_message_id, conversation, conversation.get("normalizedPhone"), contact, lead, occurred_at, "OUTBOUND"), "type": "TEXT", "renderedText": text, "status": "ACCEPTED", "acceptedAt": occurred_at}
    repository.upsert_outbound_message(document)
    return repository.apply_status(provider_message_id, "ACCEPTED", occurred_at)


def _record_inbound(event: Dict[str, Any]) -> bool:
    provider_message_id = event.get("waMessageId")
    normalized_phone = _normalized_phone(event.get("from"))
    if not provider_message_id or not normalized_phone:
        return False
    occurred_at = _provider_time(event.get("timestamp"))
    contact, lead = _links(normalized_phone)
    rendered_text = event.get("text") or event.get("buttonText")
    conversation = _conversation(
        normalized_phone,
        event.get("phoneNumberId"),
        contact,
        lead,
        occurred_at,
        direction="INBOUND",
        preview=rendered_text,
    )
    message_type = str(event.get("messageType") or "unknown").upper()
    if event.get("replyType"):
        message_type = event["replyType"]
    document = {
        **_base_message(
            provider_message_id, conversation, normalized_phone, contact, lead,
            occurred_at, "INBOUND"
        ),
        "providerContextMessageId": event.get("contextMessageId"),
        "type": message_type,
        "renderedText": rendered_text,
        "selectedButton": (
            {"id": event.get("buttonPayload"), "title": event.get("buttonText")}
            if event.get("buttonText") or event.get("buttonPayload") else None
        ),
        "templateName": event.get("templateName"),
        "templateLanguage": event.get("templateLanguage"),
        "status": "ACCEPTED",
        "acceptedAt": occurred_at,
    }
    _, inserted = repository.insert_inbound_message(document)
    return inserted


def _record_status(event: Dict[str, Any]) -> None:
    provider_message_id = event.get("waMessageId")
    status = str(event.get("status") or "").lower()
    if not provider_message_id or status not in SUPPORTED_STATUSES:
        return
    occurred_at = _provider_time(event.get("timestamp"))
    existing = repository.upsert_outbound_message({
        **_base_message(provider_message_id, None, None, None, None, occurred_at, "OUTBOUND"),
        "type": "TEMPLATE",
        "status": "ACCEPTED",
    })
    if not existing.get("conversationId"):
        legacy = repository.find_legacy_outbound(provider_message_id) or {}
        normalized_phone = _normalized_phone(event.get("recipientId") or legacy.get("phone"))
        contact, lead = _links(normalized_phone)
        conversation = (
            _conversation(
                normalized_phone, event.get("phoneNumberId"), contact, lead,
                occurred_at, direction="OUTBOUND", preview=legacy.get("renderedText")
            ) if normalized_phone else None
        )
        updates = {
            "conversationId": conversation.get("_id") if conversation else None,
            "contactId": contact.get("_id") if contact else None,
            "leadId": lead.get("_id") if lead else None,
            "normalizedPhone": normalized_phone,
            "templateName": legacy.get("templateName"),
            "renderedText": legacy.get("renderedText"),
        }
        repository.enrich_message_if_missing(provider_message_id, updates)
    repository.apply_status(
        provider_message_id,
        status.upper(),
        occurred_at,
        event.get("failureCode"),
        event.get("failureMessage"),
    )
    details = event.get("failureDetails")
    if status == "failed" and details and event.get("eventKey"):
        repository.store_temporary_failure_details(
            provider_message_id,
            event["eventKey"],
            details,
            _now() + timedelta(days=FAILURE_DETAIL_RETENTION_DAYS),
        )


def process_extracted_event(event: Dict[str, Any]) -> bool:
    """Persist a normalized event and return whether legacy inbound handlers may run."""
    is_new_inbound = False
    if event.get("eventType") == "incoming_message":
        is_new_inbound = _record_inbound(event)
    elif event.get("eventType") == "message_status":
        _record_status(event)

    compatibility_event = {
        key: value for key, value in event.items() if key != "failureDetails"
    }
    repository.insert_compatibility_event_once(compatibility_event)
    return is_new_inbound

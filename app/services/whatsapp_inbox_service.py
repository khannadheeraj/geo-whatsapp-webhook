import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from bson import ObjectId

from app.errors import AuthorizationError, NotFoundError, ValidationApiError
from app.models.user_model import UserRole, public_user
from app.repositories import contact_repository, lead_repository, user_repository
from app.repositories import whatsapp_inbox_repository as repository
from app.utils.mongo_utils import object_id_or_not_found, public_document
from app.repositories import whatsapp_template_send_repository as operations
from app.services.preference_service import get_contact_communication_eligibility
from app.services.whatsapp_sender import send_whatsapp_text
from app.services.whatsapp_message_service import record_outbound_text_message


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _active_leads(contact_ids):
    return {lead["contactId"]: lead for lead in lead_repository.find_active_leads_by_contacts(contact_ids)}


def _visible(conversation: Dict[str, Any], user: Dict[str, Any], leads: Dict[Any, Dict[str, Any]]) -> bool:
    if user.get("role") == UserRole.SUPER_ADMIN.value:
        return True
    lead = leads.get(conversation.get("contactId"))
    return bool(lead and str(lead.get("assignedCounsellorId")) == str(user["_id"]))


def _summary(conversation, contact, lead, owner, unread_count):
    latest = repository.latest_message(conversation["_id"])
    return {
        "id": str(conversation["_id"]), "phone": conversation.get("normalizedPhone"),
        "reconciliationStatus": conversation.get("reconciliationStatus"),
        "lastMessagePreview": conversation.get("latestMessagePreview"),
        "lastMessageDirection": latest.get("direction") if latest else None,
        "lastMessageType": latest.get("type") if latest else None, "lastMessageAt": conversation.get("latestMessageAt"),
        "unreadCount": unread_count,
        "contact": {"id": str(contact["_id"]), "displayName": contact.get("displayName"), "phone": contact.get("normalizedPhone")} if contact else None,
        "activeLead": {"id": str(lead["_id"]), "status": lead.get("status"), "assignedCounsellorId": str(lead.get("assignedCounsellorId")) if lead.get("assignedCounsellorId") else None} if lead else None,
        "assignedCounsellor": public_user(owner) if owner else None,
    }


def list_inbox(user: Dict[str, Any], *, page: int, page_size: int, search: Optional[str], reconciliation_status: Optional[str], assigned_counsellor_id: Optional[str], unread_only: bool):
    query = {"reconciliationStatus": reconciliation_status} if reconciliation_status else {}
    conversations = repository.list_conversations(query)
    contact_ids = [item.get("contactId") for item in conversations if item.get("contactId")]
    contacts = {item["_id"]: item for item in contact_repository.find_contacts_by_ids(contact_ids)}
    leads = _active_leads(contact_ids)
    owner_ids = [lead.get("assignedCounsellorId") for lead in leads.values() if lead.get("assignedCounsellorId")]
    owners = {item["_id"]: item for item in user_repository.find_staff_users_by_ids(owner_ids)}
    requested_owner = object_id_or_not_found(assigned_counsellor_id, "user") if assigned_counsellor_id else None
    search_value = (search or "").casefold().strip()
    results = []
    for conversation in conversations:
        contact, lead = contacts.get(conversation.get("contactId")), leads.get(conversation.get("contactId"))
        if not _visible(conversation, user, leads):
            continue
        if requested_owner and (not lead or lead.get("assignedCounsellorId") != requested_owner):
            continue
        if search_value and search_value not in str(conversation.get("normalizedPhone") or "").casefold() and search_value not in str(contact.get("displayName") if contact else "").casefold():
            continue
        read = repository.find_inbox_read(user["_id"], conversation["_id"])
        unread = repository.messages_after_view(conversation["_id"], read.get("viewedAt") if read else None)
        if unread_only and not unread:
            continue
        results.append(_summary(conversation, contact, lead, owners.get(lead.get("assignedCounsellorId")) if lead else None, unread))
    total = len(results)
    start = (page - 1) * page_size
    return results[start:start + page_size], total


def _authorized_conversation(conversation_id_value: str, user: Dict[str, Any]):
    conversation = repository.find_conversation(object_id_or_not_found(conversation_id_value, "conversation"))
    if not conversation:
        raise NotFoundError("WHATSAPP_CONVERSATION_NOT_FOUND", "The requested conversation was not found.")
    leads = _active_leads([conversation.get("contactId")] if conversation.get("contactId") else [])
    if not _visible(conversation, user, leads):
        raise AuthorizationError()
    return conversation


def _decode_cursor(value: Optional[str]) -> Optional[Tuple[datetime, ObjectId]]:
    if not value:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(value.encode()).decode())
        return datetime.fromisoformat(data["createdAt"]), ObjectId(data["id"])
    except Exception as exc:
        raise ValidationApiError("MESSAGE_CURSOR_INVALID", "The message cursor is invalid.") from exc


def _cursor(message: Dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps({"createdAt": message["createdAt"].isoformat(), "id": str(message["_id"])}).encode()).decode()


def message_history(conversation_id: str, user: Dict[str, Any], *, cursor: Optional[str], page_size: int):
    conversation = _authorized_conversation(conversation_id, user)
    messages = repository.list_messages_after_cursor(conversation["_id"], _decode_cursor(cursor), page_size + 1)
    has_next = len(messages) > page_size
    page = messages[:page_size]
    allowed = {"_id", "conversationId", "contactId", "leadId", "normalizedPhone", "providerMessageId", "direction", "type", "renderedText", "selectedButton", "templateName", "templateLanguage", "status", "providerTimestamp", "createdAt", "acceptedAt", "sentAt", "deliveredAt", "readAt", "failedAt"}
    return [{key: value for key, value in message.items() if key in allowed} for message in page], {"hasNext": has_next, "nextCursor": _cursor(page[-1]) if has_next and page else None}


def mark_conversation_viewed(conversation_id: str, user: Dict[str, Any]):
    conversation = _authorized_conversation(conversation_id, user)
    return repository.mark_viewed(user["_id"], conversation["_id"], _now())


def send_reply(conversation_id: str, text: str, key: str, user: Dict[str, Any]):
    conversation = _authorized_conversation(conversation_id, user)
    contact = contact_repository.find_contact_by_id(conversation.get("contactId")) if conversation.get("contactId") else None
    if not contact or not get_contact_communication_eligibility(contact["_id"], promotional=False).get("allowed"):
        raise ValidationApiError("CONVERSATION_REPLY_NOT_ALLOWED", "WhatsApp replies are not allowed for this Contact.")
    inbound = repository.latest_inbound_message(conversation["_id"])
    if not inbound or (_now() - inbound["createdAt"]).total_seconds() > 86400:
        raise ValidationApiError("WHATSAPP_REPLY_WINDOW_EXPIRED", "The 24-hour customer-service window has expired. Send an approved template instead.")
    cleaned = " ".join(text.strip().split())
    if not cleaned or len(cleaned) > 4096: raise ValidationApiError("WHATSAPP_REPLY_TEXT_INVALID", "Enter a reply up to 4096 characters.")
    request_hash = hashlib.sha256(f"REPLY|{conversation_id}|{cleaned}".encode()).hexdigest()
    operation, claimed = operations.claim_send_operation({"actorUserId": user["_id"], "idempotencyKey": key, "requestHash": request_hash, "operationType": "TEXT_REPLY", "status": "PENDING", "createdAt": _now(), "updatedAt": _now()})
    if not claimed:
        if operation.get("requestHash") != request_hash: raise ValidationApiError("IDEMPOTENCY_KEY_REUSED", "The idempotency key was used for another request.")
        if operation.get("status") == "ACCEPTED": return {"message": operation.get("message"), "idempotentReplay": True}
        raise ValidationApiError("WHATSAPP_REPLY_IN_PROGRESS", "This reply is still being processed.")
    result = send_whatsapp_text(contact["normalizedPhone"], cleaned)
    if not result.get("success"):
        operations.complete_send_operation(operation["_id"], {"status": "FAILED", "updatedAt": _now()}); raise ValidationApiError("WHATSAPP_REPLY_FAILED", "WhatsApp reply could not be sent.")
    provider_id = ((result.get("response") or {}).get("messages") or [{}])[0].get("id")
    if not provider_id: raise ValidationApiError("WHATSAPP_REPLY_FAILED", "WhatsApp reply could not be sent.")
    lead = _active_leads([contact["_id"]]).get(contact["_id"])
    message = record_outbound_text_message(provider_message_id=provider_id, conversation=conversation, contact=contact, lead=lead, text=cleaned)
    operations.complete_send_operation(operation["_id"], {"status": "ACCEPTED", "message": message, "updatedAt": _now()})
    return {"message": message, "idempotentReplay": False}

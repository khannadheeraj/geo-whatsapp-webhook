import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from app.config import WHATSAPP_PHONE_NUMBER_ID
from app.db.mongodb import get_collection
from app.errors import ConflictError, NotFoundError, ValidationApiError
from app.repositories import whatsapp_broadcast_repository as repository
from app.services.audit_service import write_audit_event
from app.services.whatsapp_message_service import record_outbound_template_message
from app.services.whatsapp_sender import send_whatsapp_template
from app.utils.mongo_utils import object_id_or_not_found


LEASE_SECONDS = 120
RETRY_DELAY_SECONDS = 60
ACTIVE_BROADCAST_STATES = {"CONFIRMED", "EXECUTING", "PAUSED_RETRYABLE"}


def _now(): return datetime.now(timezone.utc)


def _broadcast(value: str) -> Dict[str, Any]:
    result = repository.find_broadcast(object_id_or_not_found(value, "broadcast"))
    if not result: raise NotFoundError("WHATSAPP_BROADCAST_NOT_FOUND", "The requested broadcast was not found.")
    return result


def _idempotency_key(broadcast_id: Any, recipient_id: Any) -> str:
    material = f"whatsapp-broadcast:{broadcast_id}:recipient:{recipient_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _safe_execution(broadcast: Dict[str, Any]) -> Dict[str, Any]:
    return {"broadcastId": str(broadcast["_id"]), "status": broadcast["status"], "version": broadcast["version"], "totals": repository.execution_counts(broadcast["_id"]), "confirmedAt": broadcast.get("confirmedAt"), "cancelledAt": broadcast.get("cancelledAt"), "completedAt": broadcast.get("completedAt")}


def confirm(value: str, version: int, actor: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    broadcast_id = object_id_or_not_found(value, "broadcast")
    current = repository.find_broadcast(broadcast_id)
    if not current: raise NotFoundError("WHATSAPP_BROADCAST_NOT_FOUND", "The requested broadcast was not found.")
    if current.get("status") != "DRAFT" or current.get("version") != version or not current.get("preparedAt"):
        raise ConflictError("WHATSAPP_BROADCAST_CONFIRM_CONFLICT", "Only the current successfully prepared draft can be confirmed.")
    eligible = list(get_collection("whatsapp_broadcast_recipients").find({"broadcastId": broadcast_id, "status": "ELIGIBLE"}))
    if not eligible: raise ValidationApiError("WHATSAPP_BROADCAST_NO_ELIGIBLE_RECIPIENTS", "The prepared draft has no eligible recipients.")
    if any(not item.get("renderedText") or "providerComponents" not in item for item in eligible):
        raise ConflictError("WHATSAPP_BROADCAST_SNAPSHOT_INCOMPLETE", "Re-prepare the draft before confirmation.")
    now = _now()
    broadcast = repository.confirm_broadcast(broadcast_id, version, {"status": "CONFIRMED", "confirmedAt": now, "confirmedBy": actor["_id"], "updatedAt": now})
    if not broadcast: raise ConflictError("WHATSAPP_BROADCAST_CONFIRM_CONFLICT", "The draft changed before confirmation.")
    frozen = repository.freeze_eligible_recipients(broadcast_id, now)
    broadcast = repository.update_broadcast(broadcast_id, {"status": "EXECUTING", "frozenEligibleCount": frozen, "updatedAt": _now()})
    write_audit_event("WHATSAPP_BROADCAST_CONFIRMED", "SUCCEEDED", actor_user_id=actor["_id"], entity_type="WHATSAPP_BROADCAST", entity_id=broadcast_id, request_id=request_id, compact_metadata={"eligibleRecipients": frozen})
    return _safe_execution(broadcast)


def _retryable(result: Dict[str, Any]) -> bool:
    status_code = result.get("statusCode")
    return result.get("error") == "WHATSAPP_REQUEST_FAILED" or status_code == 429 or (isinstance(status_code, int) and status_code >= 500)


def _process(recipient: Dict[str, Any], broadcast: Dict[str, Any], worker_id: str) -> str:
    now = _now()
    key = _idempotency_key(broadcast["_id"], recipient["_id"])
    if not repository.mark_provider_call_started(recipient["_id"], worker_id, now): return "CLAIM_LOST"
    result = send_whatsapp_template(recipient["normalizedPhone"], broadcast["templateName"], language_code=broadcast["templateLanguage"], template_components=recipient.get("providerComponents") or None)
    if not result.get("success"):
        retryable = _retryable(result)
        status = "FAILED_RETRYABLE" if retryable else "FAILED_FINAL"
        updates = {"status": status, "failureCode": str(result.get("error") or "WHATSAPP_BROADCAST_SEND_FAILED")[:100], "failureStatusCode": result.get("statusCode"), "idempotencyKey": key, "updatedAt": _now()}
        if retryable: updates["retryEligibleAt"] = _now() + timedelta(seconds=RETRY_DELAY_SECONDS)
        repository.finish_recipient(recipient["_id"], worker_id, updates)
        return status
    provider_id = ((result.get("response") or {}).get("messages") or [{}])[0].get("id")
    if not provider_id:
        repository.finish_recipient(recipient["_id"], worker_id, {"status": "FAILED_FINAL", "failureCode": "WHATSAPP_PROVIDER_RESPONSE_INVALID", "idempotencyKey": key, "updatedAt": _now()})
        return "FAILED_FINAL"
    try:
        message = record_outbound_template_message(provider_message_id=provider_id, phone=recipient["normalizedPhone"], template_name=broadcast["templateName"], template_language=broadcast["templateLanguage"], rendered_text=recipient["renderedText"], phone_number_id=WHATSAPP_PHONE_NUMBER_ID or None, contact_id=recipient.get("contactId"), lead_id=recipient.get("leadId"))
    except Exception:
        repository.finish_recipient(recipient["_id"], worker_id, {"status": "FAILED_FINAL", "failureCode": "PROVIDER_ACCEPTED_PERSISTENCE_FAILED", "providerMessageId": provider_id, "idempotencyKey": key, "updatedAt": _now()})
        return "FAILED_FINAL"
    repository.finish_recipient(recipient["_id"], worker_id, {"status": "ACCEPTED", "providerMessageId": provider_id, "messageId": message["_id"], "idempotencyKey": key, "acceptedAt": _now(), "updatedAt": _now()})
    return "ACCEPTED"


def execute_batch(value: str, batch_size: int, actor: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    broadcast = _broadcast(value)
    if broadcast.get("status") == "COMPLETED":
        return {**_safe_execution(broadcast), "batch": {"claimed": 0, "accepted": 0, "retryableFailure": 0, "finalFailure": 0}, "leaseRecovery": {"requeued": 0, "uncertainFinal": 0}}
    if broadcast.get("status") not in ACTIVE_BROADCAST_STATES: raise ConflictError("WHATSAPP_BROADCAST_NOT_EXECUTABLE", "The broadcast is not available for batch execution.")
    now = _now(); recovery = repository.recover_expired_leases(broadcast["_id"], now); worker_id = f"broadcast-worker:{uuid.uuid4()}"; outcomes = {"claimed": 0, "accepted": 0, "retryableFailure": 0, "finalFailure": 0}
    for _ in range(batch_size):
        recipient = repository.claim_next_recipient(broadcast["_id"], worker_id, _now(), _now() + timedelta(seconds=LEASE_SECONDS))
        if not recipient: break
        outcomes["claimed"] += 1; outcome = _process(recipient, broadcast, worker_id)
        if outcome == "ACCEPTED": outcomes["accepted"] += 1
        elif outcome == "FAILED_RETRYABLE": outcomes["retryableFailure"] += 1
        elif outcome == "FAILED_FINAL": outcomes["finalFailure"] += 1
    totals = repository.execution_counts(broadcast["_id"])
    state = "EXECUTING" if totals["remaining"] else ("PAUSED_RETRYABLE" if totals["retryableFailure"] else "COMPLETED")
    updates = {"status": state, "executionTotals": totals, "updatedAt": _now()}
    if state == "COMPLETED": updates["completedAt"] = _now()
    broadcast = repository.update_active_broadcast(broadcast["_id"], updates) or repository.find_broadcast(broadcast["_id"])
    write_audit_event("WHATSAPP_BROADCAST_BATCH_EXECUTED", "SUCCEEDED", actor_user_id=actor["_id"], entity_type="WHATSAPP_BROADCAST", entity_id=broadcast["_id"], request_id=request_id, compact_metadata={**outcomes, **recovery})
    return {**_safe_execution(broadcast), "batch": outcomes, "leaseRecovery": recovery}


def execution(value: str) -> Dict[str, Any]: return _safe_execution(_broadcast(value))


def retry_failures(value: str, version: int, actor: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    broadcast = _broadcast(value)
    broadcast = repository.transition_broadcast(broadcast["_id"], version, ["PAUSED_RETRYABLE", "EXECUTING"], {"status": "EXECUTING", "updatedAt": _now()})
    if not broadcast: raise ConflictError("WHATSAPP_BROADCAST_RETRY_CONFLICT", "The current broadcast cannot approve retries.")
    approved = repository.approve_retryable_failures(broadcast["_id"], _now())
    write_audit_event("WHATSAPP_BROADCAST_RETRY_APPROVED", "SUCCEEDED", actor_user_id=actor["_id"], entity_type="WHATSAPP_BROADCAST", entity_id=broadcast["_id"], request_id=request_id, compact_metadata={"approved": approved})
    return {**_safe_execution(broadcast), "approved": approved}


def cancel(value: str, version: int, actor: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    broadcast = _broadcast(value)
    now = _now(); broadcast = repository.transition_broadcast(broadcast["_id"], version, list(ACTIVE_BROADCAST_STATES), {"status": "CANCELLED", "cancelledAt": now, "cancelledBy": actor["_id"], "updatedAt": now})
    if not broadcast: raise ConflictError("WHATSAPP_BROADCAST_CANCEL_CONFLICT", "The current broadcast cannot be cancelled.")
    cancelled = repository.cancel_unsent(broadcast["_id"], now)
    broadcast = repository.update_broadcast(broadcast["_id"], {"executionTotals": repository.execution_counts(broadcast["_id"]), "updatedAt": now})
    write_audit_event("WHATSAPP_BROADCAST_CANCELLED", "SUCCEEDED", actor_user_id=actor["_id"], entity_type="WHATSAPP_BROADCAST", entity_id=broadcast["_id"], request_id=request_id, compact_metadata={"cancelledUnsent": cancelled})
    return {**_safe_execution(broadcast), "cancelledUnsent": cancelled}

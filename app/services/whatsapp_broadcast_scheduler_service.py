import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from app.errors import ConflictError, NotFoundError, ValidationApiError
from app.repositories import whatsapp_broadcast_repository as repository
from app.services.audit_service import write_audit_event
from app.services.whatsapp_broadcast_execution_service import MAX_RETRY_ATTEMPTS, execute_batch
from app.utils.mongo_utils import object_id_or_not_found


SCHEDULER_LEASE_SECONDS = 300
WORKER_ERROR_DELAY_SECONDS = 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _display_time(value: Any) -> Any:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _broadcast(value: str) -> Dict[str, Any]:
    document = repository.find_broadcast(object_id_or_not_found(value, "broadcast"))
    if not document:
        raise NotFoundError("WHATSAPP_BROADCAST_NOT_FOUND", "The requested broadcast was not found.")
    return document


def _safe_schedule(broadcast: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "broadcastId": str(broadcast["_id"]),
        "broadcastStatus": broadcast.get("status"),
        "version": broadcast.get("version"),
        "schedulerState": broadcast.get("schedulerState") or "UNSCHEDULED",
        "scheduledFor": _display_time(broadcast.get("scheduledFor")),
        "nextRunAt": _display_time(broadcast.get("nextRunAt")),
        "lastRunStartedAt": _display_time(broadcast.get("lastSchedulerRunStartedAt")),
        "lastRunCompletedAt": _display_time(broadcast.get("lastSchedulerRunCompletedAt")),
        "lastBatch": broadcast.get("lastSchedulerBatch"),
    }


def schedule(value: str, version: int, scheduled_for: datetime, actor: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    now = _now()
    scheduled_utc = scheduled_for.astimezone(timezone.utc)
    if scheduled_utc <= now:
        raise ValidationApiError("WHATSAPP_BROADCAST_SCHEDULE_IN_PAST", "The broadcast schedule must be in the future.")
    current = _broadcast(value)
    if current.get("status") != "EXECUTING" or current.get("version") != version:
        raise ConflictError("WHATSAPP_BROADCAST_SCHEDULE_CONFLICT", "Only the current confirmed, uncompleted broadcast can be scheduled.")
    if repository.has_execution_started(current["_id"]):
        raise ConflictError("WHATSAPP_BROADCAST_ALREADY_STARTED", "A broadcast cannot be scheduled or rescheduled after execution starts.")
    action = "WHATSAPP_BROADCAST_RESCHEDULED" if current.get("schedulerState") == "SCHEDULED" else "WHATSAPP_BROADCAST_SCHEDULED"
    updated = repository.schedule_broadcast(current["_id"], version, scheduled_utc, actor["_id"], now)
    if not updated:
        raise ConflictError("WHATSAPP_BROADCAST_SCHEDULE_CONFLICT", "The broadcast schedule changed before it could be saved.")
    write_audit_event(action, "SUCCEEDED", actor_user_id=actor["_id"], entity_type="WHATSAPP_BROADCAST", entity_id=current["_id"], request_id=request_id, compact_metadata={"scheduledFor": scheduled_utc})
    return _safe_schedule(updated)


def unschedule(value: str, version: int, actor: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    current = _broadcast(value)
    if repository.has_execution_started(current["_id"]):
        raise ConflictError("WHATSAPP_BROADCAST_ALREADY_STARTED", "A schedule cannot be removed after execution starts.")
    updated = repository.unschedule_broadcast(current["_id"], version, _now())
    if not updated:
        raise ConflictError("WHATSAPP_BROADCAST_UNSCHEDULE_CONFLICT", "The current broadcast schedule cannot be removed.")
    write_audit_event("WHATSAPP_BROADCAST_UNSCHEDULED", "SUCCEEDED", actor_user_id=actor["_id"], entity_type="WHATSAPP_BROADCAST", entity_id=current["_id"], request_id=request_id)
    return _safe_schedule(updated)


def scheduler_state(value: str) -> Dict[str, Any]:
    return _safe_schedule(_broadcast(value))


def _release_after_batch(broadcast: Dict[str, Any], worker_id: str, result: Dict[str, Any], now: datetime) -> None:
    totals = result["totals"]
    if result["status"] in {"COMPLETED", "CANCELLED"}:
        state = result["status"]
        next_run = None
    elif totals.get("remaining"):
        state = "SCHEDULED"
        next_run = now
    else:
        next_run = repository.next_retry_time(broadcast["_id"])
        state = "WAITING_RETRY" if next_run else "COMPLETED"
    updates: Dict[str, Any] = {
        "schedulerState": state,
        "lastSchedulerRunCompletedAt": now,
        "lastSchedulerBatch": result.get("batch") or {},
        "updatedAt": now,
    }
    if next_run is not None:
        updates["nextRunAt"] = next_run
    else:
        updates["nextRunAt"] = None
    repository.release_scheduler_claim(broadcast["_id"], worker_id, updates)


def run_due(batch_size: int, max_broadcasts: int, request_id: str) -> Dict[str, Any]:
    worker_id = f"scheduled-broadcast-worker:{uuid.uuid4()}"
    summary = {"claimedBroadcasts": 0, "completedBatches": 0, "claimedRecipients": 0, "accepted": 0, "retryableFailure": 0, "finalFailure": 0, "retryExhausted": 0}
    for _ in range(max_broadcasts):
        now = _now()
        broadcast = repository.claim_due_broadcast(worker_id, now, now + timedelta(seconds=SCHEDULER_LEASE_SECONDS))
        if not broadcast:
            break
        summary["claimedBroadcasts"] += 1
        try:
            activation = repository.activate_due_retryable_failures(broadcast["_id"], now, MAX_RETRY_ATTEMPTS)
            if activation["exhausted"]:
                summary["retryExhausted"] += activation["exhausted"]
                write_audit_event("WHATSAPP_BROADCAST_RETRY_EXHAUSTED", "SUCCEEDED", entity_type="WHATSAPP_BROADCAST", entity_id=broadcast["_id"], request_id=request_id, compact_metadata={"count": activation["exhausted"]})
            result = execute_batch(str(broadcast["_id"]), batch_size, {"_id": None}, request_id, automatic=True)
            batch = result.get("batch") or {}
            summary["completedBatches"] += 1
            summary["claimedRecipients"] += batch.get("claimed", 0)
            summary["accepted"] += batch.get("accepted", 0)
            summary["retryableFailure"] += batch.get("retryableFailure", 0)
            summary["finalFailure"] += batch.get("finalFailure", 0)
            summary["retryExhausted"] += batch.get("retryExhausted", 0)
            _release_after_batch(broadcast, worker_id, result, _now())
        except Exception:
            retry_at = _now() + timedelta(seconds=WORKER_ERROR_DELAY_SECONDS)
            repository.release_scheduler_claim(broadcast["_id"], worker_id, {"schedulerState": "SCHEDULED", "nextRunAt": retry_at, "lastSchedulerErrorCode": "SCHEDULED_BATCH_FAILED", "lastSchedulerRunCompletedAt": _now(), "updatedAt": _now()})
            write_audit_event("WHATSAPP_BROADCAST_AUTOMATIC_EXECUTION", "FAILED", entity_type="WHATSAPP_BROADCAST", entity_id=broadcast["_id"], request_id=request_id, compact_metadata={"errorCode": "SCHEDULED_BATCH_FAILED"})
    return summary

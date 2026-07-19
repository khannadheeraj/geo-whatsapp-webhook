from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from bson import ObjectId
from app.db.mongodb import get_collection
from app.errors import AuthorizationError, ConflictError, NotFoundError, ValidationApiError
from app.models.user_model import UserRole
from app.repositories import follow_up_repository as repository
from app.services.activity_service import record_activity
from app.services.assignment_service import validate_counsellor
from app.services.audit_service import write_audit_event
from app.utils.mongo_utils import object_id_or_not_found

def _now(): return datetime.now(timezone.utc)
def _lead(contact_id):
    value = get_collection("leads").find_one({"contactId": contact_id, "entityType": "ADMISSION_LEAD", "isActive": True})
    if not value: raise ValidationApiError("FOLLOW_UP_ACTIVE_LEAD_REQUIRED", "The Contact must have an active admission Lead.")
    return value
def _scope(task, user):
    lead = _lead(task["contactId"])
    if user.get("role") != UserRole.SUPER_ADMIN.value and (str(task.get("assignedCounsellorId")) != str(user["_id"]) or str(lead.get("assignedCounsellorId")) != str(user["_id"])): raise AuthorizationError()
    return lead
def _due(value):
    if value.tzinfo is None or value.utcoffset() is None or value.astimezone(timezone.utc) <= _now(): raise ValidationApiError("FOLLOW_UP_DUE_AT_INVALID", "The follow-up due time must be in the future.")
    return value.astimezone(timezone.utc)
def _event(action, task, actor, request_id):
    record_activity(f"FOLLOW_UP_{action}", f"Follow-up {action.lower()}.", contact_id=task["contactId"], lead_id=task["leadId"], actor_user_id=actor["_id"], metadata={"followUpId": task["_id"], "status": task["status"]}, related_entity_type="FOLLOW_UP", related_entity_id=task["_id"])
    write_audit_event(f"FOLLOW_UP_{action}", "SUCCEEDED", actor_user_id=actor["_id"], entity_type="FOLLOW_UP", entity_id=task["_id"], request_id=request_id, compact_metadata={"status": task["status"]})
def create(payload, user, request_id):
    contact_id = object_id_or_not_found(payload.contactId, "contact"); contact = get_collection("contacts").find_one({"_id": contact_id, "entityType": "CONTACT"})
    if not contact: raise NotFoundError("CONTACT_NOT_FOUND", "The requested Contact was not found.")
    lead = _lead(contact_id); owner = validate_counsellor(payload.assignedCounsellorId)
    if user.get("role") != UserRole.SUPER_ADMIN.value and (str(user["_id"]) != str(owner["_id"]) or str(lead.get("assignedCounsellorId")) != str(user["_id"])): raise AuthorizationError()
    now = _now(); task = repository.insert({"contactId": contact_id, "leadId": lead["_id"], "assignedCounsellorId": owner["_id"], "type": payload.type, "dueAt": _due(payload.dueAt), "priority": payload.priority, "status": "PENDING", "purpose": payload.purpose.strip(), **({"internalNote": payload.internalNote.strip()} if payload.internalNote and payload.internalNote.strip() else {}), "createdBy": user["_id"], "createdAt": now, "updatedBy": user["_id"], "updatedAt": now, "version": 1})
    _event("CREATED", task, user, request_id); return task
def get(value, user):
    task = repository.find(object_id_or_not_found(value, "follow_up"));
    if not task: raise NotFoundError("FOLLOW_UP_NOT_FOUND", "The requested follow-up was not found.")
    _scope(task, user); return task
def patch(value, payload, user, request_id):
    task = get(value, user)
    if task["status"] != "PENDING": raise ConflictError("FOLLOW_UP_NOT_PENDING", "Only pending follow-ups can be updated.")
    updates = {"updatedAt": _now(), "updatedBy": user["_id"]}
    for key in ("type", "priority", "purpose", "internalNote"):
        val = getattr(payload, key, None)
        if val is not None: updates[key] = val.strip() if isinstance(val, str) else val
    if payload.dueAt is not None: updates["dueAt"] = _due(payload.dueAt)
    if payload.assignedCounsellorId is not None:
        if user.get("role") != UserRole.SUPER_ADMIN.value: raise AuthorizationError()
        updates["assignedCounsellorId"] = validate_counsellor(payload.assignedCounsellorId)["_id"]
    updated = repository.update(task["_id"], payload.version, {}, updates)
    if not updated: raise ConflictError("FOLLOW_UP_VERSION_CONFLICT", "The follow-up changed elsewhere. Refresh and try again.")
    _event("UPDATED", updated, user, request_id); return updated
def action(value, payload, user, request_id, status):
    task = get(value, user)
    if task["status"] != "PENDING": raise ConflictError("FOLLOW_UP_NOT_PENDING", "Only pending follow-ups can be completed or cancelled.")
    now = _now(); updates = {"status": status, "updatedAt": now, "updatedBy": user["_id"], ("completedAt" if status == "COMPLETED" else "cancelledAt"): now, ("completedBy" if status == "COMPLETED" else "cancelledBy"): user["_id"]}
    note = payload.completionNote if status == "COMPLETED" else payload.cancellationNote
    if note and note.strip(): updates["completionNote" if status == "COMPLETED" else "cancellationNote"] = note.strip()
    updated = repository.update(task["_id"], payload.version, {}, updates)
    if not updated: raise ConflictError("FOLLOW_UP_VERSION_CONFLICT", "The follow-up changed elsewhere. Refresh and try again.")
    _event(status, updated, user, request_id); return updated
def list_follow_ups(user, *, assigned, status, task_type, priority, due_from, due_to, overdue, search, page, page_size) -> Tuple[list, int]:
    query: Dict[str, Any] = {}
    if user.get("role") != UserRole.SUPER_ADMIN.value: query["assignedCounsellorId"] = user["_id"]
    elif assigned: query["assignedCounsellorId"] = object_id_or_not_found(assigned, "counsellor")
    for key, value in (("status", status), ("type", task_type), ("priority", priority)):
        if value: query[key] = value
    if due_from or due_to: query["dueAt"] = {**({"$gte": due_from} if due_from else {}), **({"$lte": due_to} if due_to else {})}
    if overdue: query.update({"status": "PENDING", "dueAt": {"$lt": _now()}})
    if search:
        contacts = list(get_collection("contacts").find({"$or": [{"displayName": {"$regex": search[:100], "$options": "i"}}, {"normalizedPhone": {"$regex": search[:100]}}]}, {"_id": 1})); query["contactId"] = {"$in": [x["_id"] for x in contacts]}
    if user.get("role") != UserRole.SUPER_ADMIN.value:
        lead_ids = [x["_id"] for x in get_collection("leads").find({"entityType": "ADMISSION_LEAD", "isActive": True, "assignedCounsellorId": user["_id"]}, {"_id": 1})]; query["leadId"] = {"$in": lead_ids}
    return repository.list_tasks(query, page, page_size)

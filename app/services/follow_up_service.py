from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional, Tuple
from bson import ObjectId
from app.db.mongodb import get_collection
from app.errors import AuthorizationError, ConflictError, NotFoundError, ValidationApiError
from app.models.user_model import UserRole
from app.models.crm_model import LeadStatus
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
    metadata = {"followUpId": task["_id"], "status": task["status"]}
    for key in ("previousLeadStatus", "recommendedLeadStatus", "appliedLeadStatus", "leadStatusDecision"):
        if key in task: metadata[key] = task[key]
    record_activity(f"FOLLOW_UP_{action}", f"Follow-up {action.lower()}.", contact_id=task["contactId"], lead_id=task["leadId"], actor_user_id=actor["_id"], metadata=metadata, related_entity_type="FOLLOW_UP", related_entity_id=task["_id"])
    write_audit_event(f"FOLLOW_UP_{action}", "SUCCEEDED", actor_user_id=actor["_id"], entity_type="FOLLOW_UP", entity_id=task["_id"], request_id=request_id, compact_metadata=metadata)

_OUTCOME_RECOMMENDATIONS = {
    "CONNECTED_INTERESTED": LeadStatus.INTERESTED.value,
    "CONNECTED_NOT_INTERESTED": LeadStatus.LOST.value,
    "CALLBACK_REQUESTED": LeadStatus.NEEDS_CONTACT.value,
    "NO_ANSWER": LeadStatus.NEEDS_CONTACT.value,
    "BUSY": LeadStatus.NEEDS_CONTACT.value,
    "WRONG_NUMBER": LeadStatus.NEEDS_CONTACT.value,
}
_PROTECTED_RECOMMENDATION_STATUSES = {
    LeadStatus.DEMO_REGISTERED.value, LeadStatus.DEMO_ATTENDED.value,
    LeadStatus.ADMISSION_IN_PROGRESS.value, LeadStatus.ADMITTED.value,
    LeadStatus.DO_NOT_CONTACT.value, LeadStatus.INVALID_CONTACT.value, LeadStatus.LOST.value,
}

def _recommendation(lead, outcome):
    current = lead.get("status") or LeadStatus.NEW.value
    suggested = _OUTCOME_RECOMMENDATIONS.get(outcome)
    if suggested and current in _PROTECTED_RECOMMENDATION_STATUSES and current != suggested:
        return None, "CURRENT_STATUS_PROTECTED"
    return suggested, None

def completion_recommendation(value, user, outcome=None):
    task = get(value, user)
    if task.get("status") != "PENDING": raise ConflictError("FOLLOW_UP_NOT_PENDING", "Only pending follow-ups can be completed.")
    lead = _lead(task["contactId"])
    current = lead.get("status") or LeadStatus.NEW.value
    recommended, reason = _recommendation(lead, outcome) if outcome else (None, None)
    return {"followUpId": task["_id"], "currentLeadStatus": current, "recommendedLeadStatus": recommended, "recommendationUnavailableReason": reason, "recommendations": _OUTCOME_RECOMMENDATIONS, "protectedCurrentStatus": current in _PROTECTED_RECOMMENDATION_STATUSES}
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
    if task["status"] != "PENDING":
        if status == "COMPLETED" and task["status"] == "COMPLETED": return task
        raise ConflictError("FOLLOW_UP_NOT_PENDING", "Only pending follow-ups can be completed or cancelled.")
    now = _now(); updates = {"status": status, "updatedAt": now, "updatedBy": user["_id"], ("completedAt" if status == "COMPLETED" else "cancelledAt"): now, ("completedBy" if status == "COMPLETED" else "cancelledBy"): user["_id"]}
    note = payload.completionNote if status == "COMPLETED" else payload.cancellationNote
    if note and note.strip(): updates["completionNote" if status == "COMPLETED" else "cancellationNote"] = note.strip()
    if status == "COMPLETED":
        if not payload.outcome: raise ValidationApiError("FOLLOW_UP_OUTCOME_REQUIRED", "Select a counselling outcome.")
        if payload.outcome in {"CONNECTED_INTERESTED", "CONNECTED_NOT_INTERESTED"} and not (payload.discussionSummary or "").strip(): raise ValidationApiError("FOLLOW_UP_DISCUSSION_REQUIRED", "A discussion summary is required for connected outcomes.")
        updates["outcome"] = payload.outcome
        for key, field in (("discussionSummary", "discussionSummary"), ("studentQuestionsOrObjections", "studentQuestionsOrObjections"), ("nextAction", "nextAction")):
            item = getattr(payload, field, None)
            if item and item.strip(): updates[key] = item.strip()
        lead = _lead(task["contactId"])
        previous_status = lead.get("status") or LeadStatus.NEW.value
        recommended_status, protection_reason = _recommendation(lead, payload.outcome)
        requested_status = payload.leadStatus.value if payload.leadStatus else None
        decision = payload.leadStatusDecision
        if requested_status:
            decision = "MANUAL_OVERRIDE"
            applied_status = requested_status
        elif decision == "RECOMMENDATION_ACCEPTED":
            if not recommended_status: raise ValidationApiError("FOLLOW_UP_RECOMMENDATION_UNAVAILABLE", "No Lead-status recommendation is available for this outcome and current Lead status.")
            applied_status = recommended_status
        else:
            decision = "KEPT_CURRENT"
            applied_status = previous_status
        updates.update({"previousLeadStatus": previous_status, "recommendedLeadStatus": recommended_status, "appliedLeadStatus": applied_status, "leadStatusDecision": decision})
    updated = repository.update(task["_id"], payload.version, {}, updates)
    if not updated: raise ConflictError("FOLLOW_UP_VERSION_CONFLICT", "The follow-up changed elsewhere. Refresh and try again.")
    if status == "COMPLETED" and updated.get("appliedLeadStatus") != updated.get("previousLeadStatus"):
        get_collection("leads").update_one({"_id": task["leadId"], "isActive": True}, {"$set": {"status": updated["appliedLeadStatus"], "updatedAt": now, "updatedBy": user["_id"]}, "$inc": {"version": 1}})
    if status == "COMPLETED" and payload.nextFollowUpAt:
        due_at = _due(payload.nextFollowUpAt)
        next_task = repository.insert({"contactId": task["contactId"], "leadId": task["leadId"], "assignedCounsellorId": task["assignedCounsellorId"], "type": payload.nextFollowUpType or task["type"], "dueAt": due_at, "priority": payload.nextFollowUpPriority or task["priority"], "status": "PENDING", "purpose": (payload.nextAction or task["purpose"]).strip(), "createdBy": user["_id"], "createdAt": now, "updatedBy": user["_id"], "updatedAt": now, "version": 1, "previousFollowUpId": task["_id"]})
        updated["nextFollowUpId"] = next_task["_id"]
        _event("CREATED", next_task, user, request_id)
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

def work_queue(user, *, group, assigned, page, page_size):
    def aware(value): return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else (value or _now())
    now = _now(); india = ZoneInfo("Asia/Kolkata"); local_now = now.astimezone(india); start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc); end = local_now.replace(hour=23, minute=59, second=59, microsecond=999999).astimezone(timezone.utc)
    lead_query = {"entityType": "ADMISSION_LEAD", "isActive": True}
    if user.get("role") != UserRole.SUPER_ADMIN.value: lead_query["assignedCounsellorId"] = user["_id"]
    elif assigned: lead_query["assignedCounsellorId"] = object_id_or_not_found(assigned, "counsellor")
    leads = list(get_collection("leads").find(lead_query)); lead_ids = [lead["_id"] for lead in leads]
    tasks = list(get_collection("follow_up_tasks").find({"leadId": {"$in": lead_ids}}))
    pending = [task for task in tasks if task.get("status") == "PENDING"]
    completed_today = [task for task in tasks if task.get("status") == "COMPLETED" and start <= aware(task.get("completedAt")) <= end]
    groups = {"OVERDUE": [task for task in pending if aware(task.get("dueAt")) < now], "DUE_TODAY": [task for task in pending if now <= aware(task.get("dueAt")) <= end], "UPCOMING": [task for task in pending if aware(task.get("dueAt")) > end], "COMPLETED_TODAY": completed_today}
    pending_leads = {task["leadId"] for task in pending}; groups["LEADS_WITHOUT_PENDING_FOLLOW_UP"] = [lead for lead in leads if lead["_id"] not in pending_leads]
    selected = groups.get(group or "OVERDUE", groups["OVERDUE"])
    priorities = {"URGENT": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    selected.sort(key=lambda item: (priorities.get(item.get("priority"), 9), item.get("dueAt", item.get("lastActivityAt", item.get("createdAt", now))), item.get("_id")))
    contacts = {item["_id"]: item for item in get_collection("contacts").find({"_id": {"$in": [lead["contactId"] for lead in leads]}})}; users = {item["_id"]: item for item in get_collection("users").find({"_id": {"$in": [lead.get("assignedCounsellorId") for lead in leads if lead.get("assignedCounsellorId")]}})}; lead_map = {lead["_id"]: lead for lead in leads}
    result=[]
    for item in selected[(page-1)*page_size:page*page_size]:
        lead = item if group == "LEADS_WITHOUT_PENDING_FOLLOW_UP" else lead_map[item["leadId"]]; contact = contacts.get(lead["contactId"], {}); owner = users.get(lead.get("assignedCounsellorId"), {})
        result.append({"queueGroup": group or "OVERDUE", "task": None if group == "LEADS_WITHOUT_PENDING_FOLLOW_UP" else {**item, "id": item["_id"]}, "contact": {"id": contact.get("_id"), "displayName": contact.get("displayName"), "normalizedPhone": contact.get("normalizedPhone")}, "lead": {"id": lead["_id"], "status": lead.get("status"), "lastActivityAt": lead.get("lastActivityAt"), "createdAt": lead.get("createdAt")}, "assignedCounsellor": {"id": owner.get("_id"), "displayName": owner.get("displayName")}})
    return result, {key: len(value) for key, value in groups.items()}, len(selected)

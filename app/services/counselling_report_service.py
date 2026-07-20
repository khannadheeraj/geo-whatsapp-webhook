from datetime import datetime, timedelta, timezone
from typing import Optional

from app.db.mongodb import get_collection
from app.errors import AuthorizationError, ValidationApiError
from app.models.user_model import UserRole
from app.utils.mongo_utils import object_id_or_not_found

OUTCOMES = ("CONNECTED_INTERESTED", "CONNECTED_NOT_INTERESTED", "CALLBACK_REQUESTED", "NO_ANSWER", "BUSY", "WRONG_NUMBER", "GENERAL_COMPLETED")


def _now(): return datetime.now(timezone.utc)
def _aware(value): return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value
def _period(value, name):
    if value is not None and (value.tzinfo is None or value.utcoffset() is None): raise ValidationApiError("REPORT_DATE_TIMEZONE_REQUIRED", f"{name} must include a timezone offset.")
    return value.astimezone(timezone.utc) if value else None
def _scope(user, assigned):
    query = {"entityType": "ADMISSION_LEAD", "isActive": True}
    if user.get("role") != UserRole.SUPER_ADMIN.value:
        if assigned and str(assigned) != str(user["_id"]): raise AuthorizationError()
        query["assignedCounsellorId"] = user["_id"]
    elif assigned: query["assignedCounsellorId"] = object_id_or_not_found(assigned, "counsellor")
    return list(get_collection("leads").find(query))
def _in_period(value, start, end):
    value = _aware(value)
    return bool(value and (not start or value >= start) and (not end or value <= end))
def _reminder_counts(tasks):
    now = _now(); due_now = now + timedelta(minutes=5); due_soon = now + timedelta(minutes=60)
    counts = {"overdue": 0, "dueNow": 0, "dueSoon": 0}
    for task in tasks:
        if task.get("status") != "PENDING": continue
        due = _aware(task.get("dueAt"))
        if due < now: counts["overdue"] += 1
        elif due <= due_now: counts["dueNow"] += 1
        elif due <= due_soon: counts["dueSoon"] += 1
    return counts


def _metrics(leads, start, end):
    lead_ids = [lead["_id"] for lead in leads]
    tasks = list(get_collection("follow_up_tasks").find({"leadId": {"$in": lead_ids}})) if lead_ids else []
    pending = [task for task in tasks if task.get("status") == "PENDING"]
    completed = [task for task in tasks if task.get("status") == "COMPLETED" and _in_period(task.get("completedAt"), start, end)]
    cancelled = [task for task in tasks if task.get("status") == "CANCELLED" and _in_period(task.get("cancelledAt"), start, end)]
    created = [task for task in tasks if _in_period(task.get("createdAt"), start, end)]
    on_time = [task for task in completed if _aware(task.get("completedAt")) <= _aware(task.get("dueAt"))]
    late = [task for task in completed if task not in on_time]
    late_minutes = [max(0, (_aware(task["completedAt"]) - _aware(task["dueAt"])).total_seconds() / 60) for task in completed]
    outcomes = {outcome: sum(1 for task in completed if task.get("outcome") == outcome) for outcome in OUTCOMES}
    pending_lead_ids = {task.get("leadId") for task in pending}
    final = len(completed) + len(cancelled)
    changed = sum(1 for task in completed if task.get("previousLeadStatus") and task.get("appliedLeadStatus") and task.get("previousLeadStatus") != task.get("appliedLeadStatus"))
    return {"activeLeads": len(leads), "leadsWithoutPendingFollowUp": sum(1 for lead in leads if lead["_id"] not in pending_lead_ids), "followUpsCreated": len(created), "pending": len(pending), "overdue": sum(1 for task in pending if _aware(task.get("dueAt")) < _now()), "completed": len(completed), "cancelled": len(cancelled), "completionRate": (len(completed) / final) if final else 0, "completedOnTime": len(on_time), "completedLate": len(late), "averageCompletionDelayMinutes": (sum(late_minutes) / len(late_minutes)) if late_minutes else 0, "outcomeCounts": outcomes, "nextFollowUpCreationRate": (sum(1 for task in completed if task.get("nextFollowUpId")) / len(completed)) if completed else 0, "leadStatusChangesFromCompletion": changed, "reminders": _reminder_counts(tasks), "_tasks": tasks}


def summary(user, assigned=None, date_from=None, date_to=None):
    start, end = _period(date_from, "dateFrom"), _period(date_to, "dateTo")
    if start and end and start > end: raise ValidationApiError("REPORT_DATE_RANGE_INVALID", "dateFrom must be before dateTo.")
    data = _metrics(_scope(user, assigned), start, end); data.pop("_tasks"); data["dateFrom"] = start; data["dateTo"] = end; return data
def outcomes(user, assigned=None, date_from=None, date_to=None):
    data = summary(user, assigned, date_from, date_to); return {"outcomes": data["outcomeCounts"], "completed": data["completed"], "dateFrom": data["dateFrom"], "dateTo": data["dateTo"]}
def productivity(user, assigned=None, date_from=None, date_to=None):
    leads = _scope(user, assigned); start, end = _period(date_from, "dateFrom"), _period(date_to, "dateTo")
    owners = {item["_id"]: item for item in get_collection("users").find({"_id": {"$in": [lead.get("assignedCounsellorId") for lead in leads if lead.get("assignedCounsellorId")]}})}
    rows = []
    for owner_id in sorted({lead.get("assignedCounsellorId") for lead in leads if lead.get("assignedCounsellorId")}, key=str):
        metrics = _metrics([lead for lead in leads if lead.get("assignedCounsellorId") == owner_id], start, end); metrics.pop("_tasks")
        owner = owners.get(owner_id, {}); rows.append({"counsellor": {"id": owner_id, "displayName": owner.get("displayName")}, "metrics": metrics})
    return rows
def follow_up_rows(user, assigned=None, date_from=None, date_to=None, page=1, page_size=25):
    leads = _scope(user, assigned); start, end = _period(date_from, "dateFrom"), _period(date_to, "dateTo"); lead_map = {lead["_id"]: lead for lead in leads}
    tasks = list(get_collection("follow_up_tasks").find({"leadId": {"$in": list(lead_map)}})) if lead_map else []
    selected = [task for task in tasks if _in_period(task.get("completedAt") or task.get("createdAt"), start, end)]
    selected.sort(key=lambda task: (_aware(task.get("completedAt") or task.get("createdAt")), task["_id"]), reverse=True)
    contacts = {contact["_id"]: contact for contact in get_collection("contacts").find({"_id": {"$in": [lead["contactId"] for lead in leads]}})}
    docs = []
    for task in selected[(page - 1) * page_size: page * page_size]:
        lead = lead_map[task["leadId"]]; contact = contacts.get(lead["contactId"], {})
        docs.append({"id": task["_id"], "contact": {"id": contact.get("_id"), "displayName": contact.get("displayName"), "normalizedPhone": contact.get("normalizedPhone")}, "lead": {"id": lead["_id"], "status": lead.get("status")}, "assignedCounsellorId": lead.get("assignedCounsellorId"), "type": task.get("type"), "priority": task.get("priority"), "status": task.get("status"), "dueAt": task.get("dueAt"), "createdAt": task.get("createdAt"), "completedAt": task.get("completedAt"), "cancelledAt": task.get("cancelledAt"), "outcome": task.get("outcome"), "leadStatusDecision": task.get("leadStatusDecision")})
    return docs, len(selected)

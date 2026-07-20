from datetime import datetime, timedelta, timezone
from typing import Optional
from bson import ObjectId
from app.db.mongodb import get_collection
from app.errors import AuthorizationError, NotFoundError, ValidationApiError
from app.models.user_model import UserRole
from app.services.audit_service import write_audit_event
from app.utils.mongo_utils import object_id_or_not_found

def _now(): return datetime.now(timezone.utc)
def _aware(value): return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value
def _scope(user, assigned):
    query={"entityType":"ADMISSION_LEAD","isActive":True}
    if user.get("role") != UserRole.SUPER_ADMIN.value: query["assignedCounsellorId"]=user["_id"]
    elif assigned: query["assignedCounsellorId"]=object_id_or_not_found(assigned,"counsellor")
    return list(get_collection("leads").find(query))
def _category(due, now):
    due=_aware(due)
    return "OVERDUE" if due < now else "DUE_NOW" if due <= now + timedelta(minutes=5) else "DUE_SOON" if due <= now + timedelta(minutes=60) else None
def list_reminders(user, *, assigned:Optional[str], category:Optional[str], page:int, page_size:int):
    now=_now(); leads=_scope(user, assigned); ids=[lead["_id"] for lead in leads]; lead_map={lead["_id"]:lead for lead in leads}
    states={(item["followUpId"],item["userId"]):item for item in get_collection("follow_up_reminder_states").find({"userId":user["_id"]})}
    tasks=list(get_collection("follow_up_tasks").find({"leadId":{"$in":ids},"status":"PENDING"})); contacts={item["_id"]:item for item in get_collection("contacts").find({"_id":{"$in":[lead["contactId"] for lead in leads]}})}
    docs=[]
    for task in tasks:
        kind=_category(task.get("dueAt"),now); state=states.get((task["_id"],user["_id"]))
        if not kind or (state and (state.get("dismissedAt") or (_aware(state.get("snoozedUntil")) and _aware(state["snoozedUntil"]) > now))): continue
        if category and kind != category: continue
        lead=lead_map[task["leadId"]]; contact=contacts.get(lead["contactId"],{}); docs.append({"followUpId":task["_id"],"category":kind,"taskType":task.get("type"),"priority":task.get("priority"),"dueAt":task.get("dueAt"),"purpose":task.get("purpose"),"contact":{"id":contact.get("_id"),"displayName":contact.get("displayName"),"normalizedPhone":contact.get("normalizedPhone")},"lead":{"id":lead["_id"],"status":lead.get("status")},"assignedCounsellorId":lead.get("assignedCounsellorId")})
    order={"OVERDUE":0,"DUE_NOW":1,"DUE_SOON":2}; docs.sort(key=lambda doc:(order[doc["category"]],_aware(doc["dueAt"])))
    counts={key:sum(1 for doc in docs if doc["category"]==key) for key in ("OVERDUE","DUE_NOW","DUE_SOON")}; total=len(docs); return docs[(page-1)*page_size:page*page_size],counts,total
def _task_for_user(value,user):
    task=get_collection("follow_up_tasks").find_one({"_id":object_id_or_not_found(value,"follow-up")})
    if not task: raise NotFoundError("FOLLOW_UP_NOT_FOUND","The requested follow-up was not found.")
    lead=get_collection("leads").find_one({"_id":task["leadId"],"entityType":"ADMISSION_LEAD","isActive":True})
    if not lead or (user.get("role")!=UserRole.SUPER_ADMIN.value and lead.get("assignedCounsellorId")!=user["_id"]): raise AuthorizationError()
    return task
def snooze(value,payload,user,request_id):
    task=_task_for_user(value,user); until=_aware(payload.snoozedUntil)
    if until <= _now(): raise ValidationApiError("FOLLOW_UP_REMINDER_SNOOZE_INVALID","Snooze time must be in the future.")
    get_collection("follow_up_reminder_states").update_one({"followUpId":task["_id"],"userId":user["_id"]},{"$set":{"snoozedUntil":until,"dismissedAt":None,"updatedAt":_now()}},upsert=True); write_audit_event("FOLLOW_UP_REMINDER_SNOOZED","SUCCEEDED",actor_user_id=user["_id"],entity_type="FOLLOW_UP",entity_id=task["_id"],request_id=request_id); return {"followUpId":task["_id"],"snoozedUntil":until}
def dismiss(value,user,request_id):
    task=_task_for_user(value,user); get_collection("follow_up_reminder_states").update_one({"followUpId":task["_id"],"userId":user["_id"]},{"$set":{"dismissedAt":_now(),"snoozedUntil":None,"updatedAt":_now()}},upsert=True); write_audit_event("FOLLOW_UP_REMINDER_DISMISSED","SUCCEEDED",actor_user_id=user["_id"],entity_type="FOLLOW_UP",entity_id=task["_id"],request_id=request_id); return {"followUpId":task["_id"],"dismissed":True}

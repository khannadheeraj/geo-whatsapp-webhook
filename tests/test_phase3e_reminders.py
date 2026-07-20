from datetime import datetime, timedelta, timezone
from app.models.user_model import UserRole
from test_phase2c1_template_send import _headers, _user
from test_phase3a_follow_ups import _lead

def test_reminders_scope_categories_state_and_reassignment(client,database):
    admin=_user(database,"rem-admin@example.com",UserRole.SUPER_ADMIN.value); owner=_user(database,"rem-owner@example.com",UserRole.COUNSELLOR.value); other=_user(database,"rem-other@example.com",UserRole.COUNSELLOR.value); contact,lead=_lead(database,owner["_id"]); now=datetime.now(timezone.utc)
    task=database.follow_up_tasks.insert_one({"contactId":contact,"leadId":lead,"assignedCounsellorId":owner["_id"],"type":"CALL","priority":"HIGH","purpose":"Call","status":"PENDING","dueAt":now-timedelta(minutes=1),"createdAt":now,"updatedAt":now,"version":1}).inserted_id
    soon=database.follow_up_tasks.insert_one({"contactId":contact,"leadId":lead,"assignedCounsellorId":owner["_id"],"type":"CALL","priority":"LOW","purpose":"Soon","status":"PENDING","dueAt":now+timedelta(minutes=30),"createdAt":now,"updatedAt":now,"version":1}).inserted_id
    headers=_headers(client,"rem-owner@example.com"); listed=client.get("/follow-up-reminders",headers=headers); assert listed.status_code==200 and listed.json()["counts"]=={"OVERDUE":1,"DUE_NOW":0,"DUE_SOON":1}
    assert client.post(f"/follow-up-reminders/{task}/snooze",headers=headers,json={"snoozedUntil":(now+timedelta(hours=2)).isoformat()}).status_code==200
    assert client.post(f"/follow-up-reminders/{soon}/dismiss",headers=headers).status_code==200
    assert client.get("/follow-up-reminders",headers=headers).json()["pagination"]["totalRecords"]==0
    database.leads.update_one({"_id":lead},{"$set":{"assignedCounsellorId":other["_id"]}})
    assert client.get("/follow-up-reminders",headers=headers).json()["pagination"]["totalRecords"]==0
    assert client.get("/follow-up-reminders",headers=_headers(client,"rem-admin@example.com"),params={"assignedCounsellorId":str(other["_id"])}).status_code==200
    assert database.audit_logs.find_one({"action":"FOLLOW_UP_REMINDER_SNOOZED"}) and database.audit_logs.find_one({"action":"FOLLOW_UP_REMINDER_DISMISSED"})

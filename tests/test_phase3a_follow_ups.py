from datetime import datetime, timedelta, timezone
from bson import ObjectId
from app.models.user_model import UserRole
from test_phase2c1_template_send import _headers, _user

def _lead(database, owner):
    contact=database.contacts.insert_one({"entityType":"CONTACT","displayName":"Asha","normalizedPhone":"919876543210","isActive":True}).inserted_id
    lead=database.leads.insert_one({"entityType":"ADMISSION_LEAD","contactId":contact,"assignedCounsellorId":owner,"isActive":True,"version":1}).inserted_id
    return contact,lead
def _payload(contact, owner, **extra):
    return {"contactId":str(contact),"assignedCounsellorId":str(owner),"type":"CALL","dueAt":(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),"priority":"HIGH","purpose":"Admission follow-up","internalNote":"Internal only",**extra}

def test_follow_up_authorization_validation_activity_and_audit(client,database):
    admin=_user(database,"fu-admin@example.com",UserRole.SUPER_ADMIN.value); owner=_user(database,"fu-owner@example.com",UserRole.COUNSELLOR.value); other=_user(database,"fu-other@example.com",UserRole.COUNSELLOR.value); contact,lead=_lead(database,owner["_id"])
    created=client.post("/follow-ups",headers=_headers(client,"fu-owner@example.com"),json=_payload(contact,owner["_id"])); assert created.status_code==200
    task=created.json()["data"]; assert task["status"]=="PENDING" and task["leadId"]==str(lead) and "Internal only"==task["internalNote"]
    assert client.get(f"/follow-ups/{task['id']}",headers=_headers(client,"fu-other@example.com")).status_code==403
    assert client.post("/follow-ups",headers=_headers(client,"fu-owner@example.com"),json=_payload(contact,other["_id"])).status_code==403
    past=client.post("/follow-ups",headers=_headers(client,"fu-admin@example.com"),json=_payload(contact,owner["_id"],dueAt=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat())); assert past.status_code==422
    assert database.lead_activities.find_one({"type":"FOLLOW_UP_CREATED","leadId":lead}) and database.audit_logs.find_one({"action":"FOLLOW_UP_CREATED"})

def test_follow_up_scope_reassignment_version_completion_cancellation_and_filters(client,database):
    admin=_user(database,"fu-admin2@example.com",UserRole.SUPER_ADMIN.value); owner=_user(database,"fu-owner2@example.com",UserRole.COUNSELLOR.value); new_owner=_user(database,"fu-new@example.com",UserRole.COUNSELLOR.value); contact,lead=_lead(database,owner["_id"]); headers=_headers(client,"fu-admin2@example.com")
    task=client.post("/follow-ups",headers=headers,json=_payload(contact,owner["_id"],type="MEETING")).json()["data"]
    listed=client.get("/follow-ups",headers=headers,params={"assignedCounsellorId":str(owner["_id"]),"type":"MEETING","priority":"HIGH","search":"Asha"}); assert listed.status_code==200 and listed.json()["pagination"]["totalRecords"]==1
    database.leads.update_one({"_id":lead},{"$set":{"assignedCounsellorId":new_owner["_id"]}})
    assert client.get(f"/follow-ups/{task['id']}",headers=_headers(client,"fu-owner2@example.com")).status_code==403
    changed=client.patch(f"/follow-ups/{task['id']}",headers=headers,json={"version":1,"assignedCounsellorId":str(new_owner["_id"]),"dueAt":(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()}); assert changed.status_code==200
    assert client.patch(f"/follow-ups/{task['id']}",headers=headers,json={"version":1,"purpose":"stale"}).status_code==409
    completed=client.post(f"/follow-ups/{task['id']}/complete",headers=_headers(client,"fu-new@example.com"),json={"version":2,"completionNote":"Done"}); assert completed.status_code==200 and completed.json()["data"]["status"]=="COMPLETED"
    task2=client.post("/follow-ups",headers=headers,json=_payload(contact,new_owner["_id"],type="GENERAL")).json()["data"]
    cancelled=client.post(f"/follow-ups/{task2['id']}/cancel",headers=_headers(client,"fu-new@example.com"),json={"version":1,"cancellationNote":"No longer needed"}); assert cancelled.status_code==200 and cancelled.json()["data"]["status"]=="CANCELLED"
    assert database.audit_logs.find_one({"action":"FOLLOW_UP_COMPLETED"}) and database.audit_logs.find_one({"action":"FOLLOW_UP_CANCELLED"})

def test_follow_up_indexes_exist(database):
    indexes=database.follow_up_tasks.index_information(); assert {"ix_follow_up_owner_due","ix_follow_up_status_due","ix_follow_up_lead_due","ix_follow_up_overdue"}.issubset(indexes)

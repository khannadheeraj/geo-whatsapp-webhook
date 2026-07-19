from datetime import datetime, timedelta, timezone
from app.models.user_model import UserRole
from test_phase2c1_template_send import _headers, _user

def seed(database, owner, *, due, status="PENDING", priority="MEDIUM", activity=None):
    contact = database.contacts.insert_one({"entityType":"CONTACT","displayName":"Queue Contact","normalizedPhone":"919876543" + str(database.contacts.count_documents({"entityType":"CONTACT"})).zfill(4),"isActive":True}).inserted_id
    lead = database.leads.insert_one({"entityType":"ADMISSION_LEAD","contactId":contact,"assignedCounsellorId":owner,"isActive":True,"status":"NEW","lastActivityAt":activity or due,"version":1}).inserted_id
    task = database.follow_up_tasks.insert_one({"contactId":contact,"leadId":lead,"assignedCounsellorId":owner,"type":"CALL","dueAt":due,"priority":priority,"status":status,"purpose":"Queue task","createdAt":due,"updatedAt":due,"version":1, **({"completedAt": due} if status == "COMPLETED" else {})}).inserted_id
    return contact, lead, task

def test_work_queue_authorization_groups_ordering_pagination_and_no_creation(client, database):
    admin = _user(database, "queue-admin@example.com", UserRole.SUPER_ADMIN.value); owner = _user(database, "queue-owner@example.com", UserRole.COUNSELLOR.value); other = _user(database, "queue-other@example.com", UserRole.COUNSELLOR.value)
    now = datetime.now(timezone.utc); seed(database, owner["_id"], due=now-timedelta(hours=2), priority="HIGH"); seed(database, owner["_id"], due=now+timedelta(hours=1), priority="URGENT"); seed(database, owner["_id"], due=now+timedelta(days=2), priority="LOW"); seed(database, owner["_id"], due=now-timedelta(hours=3), status="COMPLETED")
    no_contact = database.contacts.insert_one({"entityType":"CONTACT","displayName":"No Task","normalizedPhone":"919876543211","isActive":True}).inserted_id; database.leads.insert_one({"entityType":"ADMISSION_LEAD","contactId":no_contact,"assignedCounsellorId":owner["_id"],"isActive":True,"status":"NEW","lastActivityAt":now,"version":1})
    admin_queue = client.get("/follow-ups/work-queue", headers=_headers(client,"queue-admin@example.com"), params={"group":"OVERDUE"}); assert admin_queue.status_code == 200 and admin_queue.json()["summary"]["OVERDUE"] == 1
    assert client.get("/follow-ups/work-queue", headers=_headers(client,"queue-admin@example.com"), params={"group":"DUE_TODAY"}).json()["pagination"]["totalRecords"] == 1
    assert client.get("/follow-ups/work-queue", headers=_headers(client,"queue-admin@example.com"), params={"group":"UPCOMING"}).json()["pagination"]["totalRecords"] == 1
    assert client.get("/follow-ups/work-queue", headers=_headers(client,"queue-admin@example.com"), params={"group":"COMPLETED_TODAY"}).json()["pagination"]["totalRecords"] == 1
    assert client.get("/follow-ups/work-queue", headers=_headers(client,"queue-admin@example.com"), params={"group":"LEADS_WITHOUT_PENDING_FOLLOW_UP"}).json()["pagination"]["totalRecords"] == 2
    assert client.get("/follow-ups/work-queue", headers=_headers(client,"queue-owner@example.com"), params={"group":"OVERDUE"}).status_code == 200
    assert client.get("/follow-ups/work-queue", headers=_headers(client,"queue-admin@example.com"), params={"group":"OVERDUE","pageSize":1}).json()["pagination"]["hasNext"] is False
    database.leads.update_many({"assignedCounsellorId": owner["_id"]}, {"$set": {"assignedCounsellorId": other["_id"]}})
    assert client.get("/follow-ups/work-queue", headers=_headers(client,"queue-owner@example.com"), params={"group":"OVERDUE"}).json()["pagination"]["totalRecords"] == 0
    assert database.follow_up_tasks.count_documents({}) == 4

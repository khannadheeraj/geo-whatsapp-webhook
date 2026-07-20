from datetime import datetime, timedelta, timezone

from bson import ObjectId
from app.models.user_model import UserRole
from test_phase2c1_template_send import _headers, _user


def _lead(database, owner, suffix):
    contact = database.contacts.insert_one({"entityType": "CONTACT", "displayName": f"Student {suffix}", "normalizedPhone": f"91990000{suffix:04d}", "isActive": True}).inserted_id
    return contact, database.leads.insert_one({"entityType": "ADMISSION_LEAD", "contactId": contact, "assignedCounsellorId": owner, "status": "NEW", "isActive": True}).inserted_id
def _task(database, contact, lead, owner, status, now, **extra):
    document = {"contactId": contact, "leadId": lead, "assignedCounsellorId": owner, "type": "CALL", "priority": "HIGH", "purpose": "Safe purpose", "internalNote": "private", "status": status, "dueAt": now - timedelta(hours=1), "createdAt": now - timedelta(days=1), "updatedAt": now}
    document.update(extra); return database.follow_up_tasks.insert_one(document).inserted_id


def test_global_filtered_and_counsellor_scoped_metrics(client, database):
    admin = _user(database, "report-admin@example.com", UserRole.SUPER_ADMIN.value); first = _user(database, "report-first@example.com", UserRole.COUNSELLOR.value); second = _user(database, "report-second@example.com", UserRole.COUNSELLOR.value)
    now = datetime.now(timezone.utc); contact1, lead1 = _lead(database, first["_id"], 1); contact2, lead2 = _lead(database, second["_id"], 2)
    _task(database, contact1, lead1, first["_id"], "COMPLETED", now, dueAt=now, completedAt=now - timedelta(minutes=30), outcome="CONNECTED_INTERESTED", nextFollowUpId=ObjectId(), previousLeadStatus="NEW", appliedLeadStatus="INTERESTED")
    _task(database, contact1, lead1, first["_id"], "COMPLETED", now, completedAt=now, outcome="NO_ANSWER")
    _task(database, contact1, lead1, first["_id"], "CANCELLED", now, cancelledAt=now)
    _task(database, contact1, lead1, first["_id"], "PENDING", now)
    _task(database, contact2, lead2, second["_id"], "PENDING", now, dueAt=now + timedelta(minutes=3))
    headers = _headers(client, "report-admin@example.com")
    global_data = client.get("/counselling-reports/summary", headers=headers, params={"dateFrom": (now - timedelta(days=2)).isoformat(), "dateTo": (now + timedelta(days=1)).isoformat()}).json()["data"]
    assert global_data["activeLeads"] == 2 and global_data["completed"] == 2 and global_data["cancelled"] == 1 and global_data["completionRate"] == 2 / 3
    assert global_data["completedOnTime"] == 1 and global_data["completedLate"] == 1 and global_data["outcomeCounts"]["CONNECTED_INTERESTED"] == 1 and global_data["nextFollowUpCreationRate"] == 0.5 and global_data["leadStatusChangesFromCompletion"] == 1
    filtered = client.get("/counselling-reports/summary", headers=headers, params={"assignedCounsellorId": str(first["_id"])}).json()["data"]
    assert filtered["activeLeads"] == 1 and filtered["reminders"]["overdue"] == 1
    own = client.get("/counselling-reports/summary", headers=_headers(client, "report-first@example.com")).json()["data"]
    assert own["activeLeads"] == 1 and client.get("/counselling-reports/summary", headers=_headers(client, "report-first@example.com"), params={"assignedCounsellorId": str(second["_id"])}).status_code == 403
    productivity = client.get("/counselling-reports/productivity", headers=headers).json()["data"]
    assert len(productivity) == 2


def test_date_boundaries_reassignment_empty_and_safe_drill_down(client, database):
    admin = _user(database, "report-admin2@example.com", UserRole.SUPER_ADMIN.value); first = _user(database, "report-first2@example.com", UserRole.COUNSELLOR.value); second = _user(database, "report-second2@example.com", UserRole.COUNSELLOR.value)
    now = datetime.now(timezone.utc).replace(microsecond=0); contact, lead = _lead(database, first["_id"], 3)
    _task(database, contact, lead, first["_id"], "COMPLETED", now, completedAt=now, outcome="BUSY")
    headers = _headers(client, "report-admin2@example.com")
    exact = client.get("/counselling-reports/outcomes", headers=headers, params={"dateFrom": now.isoformat(), "dateTo": now.isoformat()})
    assert exact.status_code == 200 and exact.json()["data"]["outcomes"]["BUSY"] == 1
    database.leads.update_one({"_id": lead}, {"$set": {"assignedCounsellorId": second["_id"]}})
    assert client.get("/counselling-reports/summary", headers=_headers(client, "report-first2@example.com")).json()["data"]["activeLeads"] == 0
    rows = client.get("/counselling-reports/follow-ups", headers=_headers(client, "report-second2@example.com")).json()
    assert rows["pagination"]["totalRecords"] == 1 and "internalNote" not in rows["data"][0] and "discussionSummary" not in rows["data"][0]
    assert client.get("/counselling-reports/summary", headers=headers, params={"dateFrom": "2026-01-01T00:00:00"}).status_code == 422
    empty = _user(database, "report-empty@example.com", UserRole.COUNSELLOR.value)
    assert client.get("/counselling-reports/summary", headers=_headers(client, "report-empty@example.com")).json()["data"]["activeLeads"] == 0

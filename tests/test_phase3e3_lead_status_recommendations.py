from datetime import datetime, timedelta, timezone
from bson import ObjectId

from app.models.user_model import UserRole
from test_phase2c1_template_send import _headers, _user
from test_phase3a_follow_ups import _lead, _payload


def _task(client, contact, owner, email):
    return client.post("/follow-ups", headers=_headers(client, email), json=_payload(contact, owner["_id"])).json()["data"]


def test_outcome_recommendations_and_explicit_choices(client, database):
    admin = _user(database, "recommend-admin@example.com", UserRole.SUPER_ADMIN.value)
    owner = _user(database, "recommend-owner@example.com", UserRole.COUNSELLOR.value)
    contact, lead = _lead(database, owner["_id"])
    headers = _headers(client, "recommend-admin@example.com")
    task = _task(client, contact, owner, "recommend-admin@example.com")
    recommendation = client.get(f"/follow-ups/{task['id']}/completion-recommendation", headers=headers)
    assert recommendation.status_code == 200
    assert recommendation.json()["data"]["recommendations"] == {"CONNECTED_INTERESTED": "INTERESTED", "CONNECTED_NOT_INTERESTED": "LOST", "CALLBACK_REQUESTED": "NEEDS_CONTACT", "NO_ANSWER": "NEEDS_CONTACT", "BUSY": "NEEDS_CONTACT", "WRONG_NUMBER": "NEEDS_CONTACT"}
    completed = client.post(f"/follow-ups/{task['id']}/complete", headers=headers, json={"version": 1, "outcome": "CONNECTED_INTERESTED", "discussionSummary": "Interested.", "leadStatusDecision": "RECOMMENDATION_ACCEPTED"})
    assert completed.status_code == 200
    data = completed.json()["data"]
    assert data["previousLeadStatus"] == "NEW" and data["recommendedLeadStatus"] == "INTERESTED" and data["appliedLeadStatus"] == "INTERESTED" and data["leadStatusDecision"] == "RECOMMENDATION_ACCEPTED"
    assert database.leads.find_one({"_id": lead})["status"] == "INTERESTED"
    manual = _task(client, contact, owner, "recommend-admin@example.com")
    response = client.post(f"/follow-ups/{manual['id']}/complete", headers=headers, json={"version": 1, "outcome": "NO_ANSWER", "leadStatus": "FOLLOW_UP_REQUIRED"})
    assert response.status_code == 200 and response.json()["data"]["leadStatusDecision"] == "MANUAL_OVERRIDE"
    assert database.leads.find_one({"_id": lead})["status"] == "FOLLOW_UP_REQUIRED"
    kept = _task(client, contact, owner, "recommend-admin@example.com")
    response = client.post(f"/follow-ups/{kept['id']}/complete", headers=headers, json={"version": 1, "outcome": "BUSY", "leadStatusDecision": "KEPT_CURRENT"})
    assert response.status_code == 200 and response.json()["data"]["appliedLeadStatus"] == "FOLLOW_UP_REQUIRED"
    assert database.leads.find_one({"_id": lead})["status"] == "FOLLOW_UP_REQUIRED"


def test_protected_status_authorization_idempotency_and_events(client, database):
    admin = _user(database, "recommend-admin2@example.com", UserRole.SUPER_ADMIN.value)
    owner = _user(database, "recommend-owner2@example.com", UserRole.COUNSELLOR.value)
    other = _user(database, "recommend-other@example.com", UserRole.COUNSELLOR.value)
    contact, lead = _lead(database, owner["_id"])
    database.leads.update_one({"_id": lead}, {"$set": {"status": "ADMITTED"}})
    headers = _headers(client, "recommend-admin2@example.com")
    task = _task(client, contact, owner, "recommend-admin2@example.com")
    assert client.get(f"/follow-ups/{task['id']}/completion-recommendation", headers=_headers(client, "recommend-other@example.com")).status_code == 403
    blocked = client.post(f"/follow-ups/{task['id']}/complete", headers=headers, json={"version": 1, "outcome": "NO_ANSWER", "leadStatusDecision": "RECOMMENDATION_ACCEPTED"})
    assert blocked.status_code == 422
    completed = client.post(f"/follow-ups/{task['id']}/complete", headers=headers, json={"version": 1, "outcome": "NO_ANSWER", "leadStatusDecision": "KEPT_CURRENT"})
    assert completed.status_code == 200 and completed.json()["data"]["recommendedLeadStatus"] is None
    replay = client.post(f"/follow-ups/{task['id']}/complete", headers=headers, json={"version": 1, "outcome": "NO_ANSWER", "leadStatusDecision": "KEPT_CURRENT"})
    assert replay.status_code == 200 and database.leads.find_one({"_id": lead})["status"] == "ADMITTED"
    assert database.lead_activities.count_documents({"metadata.followUpId": task["id"], "type": "FOLLOW_UP_COMPLETED"}) == 1
    assert database.audit_logs.count_documents({"entityId": task["id"], "action": "FOLLOW_UP_COMPLETED"}) == 1
    conflict = _task(client, contact, owner, "recommend-admin2@example.com")
    database.follow_up_tasks.update_one({"_id": ObjectId(conflict["id"])}, {"$set": {"version": 2}})
    assert client.post(f"/follow-ups/{conflict['id']}/complete", headers=headers, json={"version": 1, "outcome": "GENERAL_COMPLETED"}).status_code == 409

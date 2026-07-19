from datetime import datetime, timedelta, timezone
from bson import ObjectId
from app.models.user_model import UserRole
from test_phase2c1_template_send import _headers, _user
from test_phase3a_follow_ups import _lead, _payload


def test_completion_requires_summary_and_creates_next_follow_up(client, database):
    admin = _user(database, "outcome-admin@example.com", UserRole.SUPER_ADMIN.value); owner = _user(database, "outcome-owner@example.com", UserRole.COUNSELLOR.value)
    contact, _ = _lead(database, owner["_id"])
    task = client.post("/follow-ups", headers=_headers(client, "outcome-admin@example.com"), json=_payload(contact, owner["_id"])).json()["data"]
    missing = client.post(f"/follow-ups/{task['id']}/complete", headers=_headers(client, "outcome-admin@example.com"), json={"version": 1, "outcome": "CONNECTED_INTERESTED"})
    assert missing.status_code == 422
    result = client.post(f"/follow-ups/{task['id']}/complete", headers=_headers(client, "outcome-admin@example.com"), json={"version": 1, "outcome": "CONNECTED_INTERESTED", "discussionSummary": "Interested in the course.", "nextAction": "Call with fee details", "nextFollowUpAt": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(), "leadStatus": "INTERESTED"})
    assert result.status_code == 200 and result.json()["data"]["outcome"] == "CONNECTED_INTERESTED"
    assert database.follow_up_tasks.count_documents({"previousFollowUpId": ObjectId(task["id"])}) == 1

from datetime import datetime, timedelta

from app.models.crm_model import ADMISSION_LEAD_ENTITY_TYPE, CONTACT_ENTITY_TYPE
from app.models.user_model import UserRole
from app.repositories.user_repository import insert_staff_user
from app.services.password_service import hash_password

PASSWORD = "Temporary!Pass4827"


def _user(database, email, role):
    return insert_staff_user({"email": email, "displayName": email.split("@")[0], "role": role, "passwordHash": hash_password(PASSWORD), "isActive": True, "mustChangePassword": False})


def _headers(client, email):
    response = client.post("/auth/login", json={"emailId": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {response.json()['data']['accessToken']}"}


def _conversation(database, *, phone, contact_id=None, latest=None, status="MATCHED"):
    latest = latest or datetime(2026, 7, 19, 10, 0)
    conversation_id = database.conversations.insert_one({"channel": "WHATSAPP", "phoneNumberId": "business-1", "normalizedPhone": phone, "contactId": contact_id, "reconciliationStatus": status, "latestMessageAt": latest, "latestInboundAt": latest, "latestMessagePreview": "Latest inbound"}).inserted_id
    return conversation_id


def _message(database, conversation_id, *, created_at, text, direction="INBOUND"):
    database.whatsapp_messages.insert_one({"providerMessageId": f"wamid.{conversation_id}.{created_at.timestamp()}", "conversationId": conversation_id, "direction": direction, "type": "TEXT", "renderedText": text, "status": "READ", "createdAt": created_at, "rawProviderPayload": "must-not-leak", "failureMessage": "must-not-leak"})


def _seed(database):
    admin = _user(database, "admin@example.com", UserRole.SUPER_ADMIN.value)
    owner = _user(database, "owner@example.com", UserRole.COUNSELLOR.value)
    other = _user(database, "other@example.com", UserRole.COUNSELLOR.value)
    contact_id = database.contacts.insert_one({"entityType": CONTACT_ENTITY_TYPE, "displayName": "Asha Sen", "normalizedPhone": "919876543210"}).inserted_id
    database.leads.insert_one({"entityType": ADMISSION_LEAD_ENTITY_TYPE, "contactId": contact_id, "isActive": True, "status": "NEW", "assignedCounsellorId": owner["_id"]})
    matched = _conversation(database, phone="919876543210", contact_id=contact_id)
    unknown = _conversation(database, phone="919811111111", status="UNKNOWN_NUMBER", latest=datetime(2026, 7, 19, 11, 0))
    return admin, owner, other, matched, unknown


def test_inbox_access_filters_unknown_numbers_and_hides_raw_data(client, database):
    _admin, _owner, _other, matched, unknown = _seed(database)
    _message(database, matched, created_at=datetime(2026, 7, 19, 10, 0), text="Hello")
    _message(database, unknown, created_at=datetime(2026, 7, 19, 11, 0), text="Unknown")
    admin = client.get("/whatsapp-conversations", headers=_headers(client, "admin@example.com"))
    owner = client.get("/whatsapp-conversations", headers=_headers(client, "owner@example.com"))
    other = client.get("/whatsapp-conversations", headers=_headers(client, "other@example.com"))
    assert admin.status_code == owner.status_code == other.status_code == 200
    assert {item["id"] for item in admin.json()["data"]} == {str(matched), str(unknown)}
    assert [item["id"] for item in owner.json()["data"]] == [str(matched)]
    assert other.json()["data"] == []
    history = client.get(f"/whatsapp-conversations/{matched}/messages", headers=_headers(client, "owner@example.com"))
    assert "rawProviderPayload" not in str(history.json()) and "must-not-leak" not in str(history.json())
    assert client.get(f"/whatsapp-conversations/{matched}/messages", headers=_headers(client, "other@example.com")).status_code == 403


def test_inbox_pagination_filters_cursor_and_per_user_view_state(client, database):
    _admin, owner, _other, matched, _unknown = _seed(database)
    second_contact = database.contacts.insert_one({"entityType": CONTACT_ENTITY_TYPE, "displayName": "Bina Roy", "normalizedPhone": "919876543211"}).inserted_id
    database.leads.insert_one({"entityType": ADMISSION_LEAD_ENTITY_TYPE, "contactId": second_contact, "isActive": True, "status": "NEW", "assignedCounsellorId": owner["_id"]})
    second = _conversation(database, phone="919876543211", contact_id=second_contact, latest=datetime(2020, 7, 19, 12, 0))
    start = datetime(2020, 7, 19, 10, 0)
    for offset in range(3): _message(database, matched, created_at=start + timedelta(minutes=offset), text=f"Message {offset}")
    _message(database, second, created_at=datetime(2020, 7, 19, 12, 0), text="Bina")
    headers = _headers(client, "owner@example.com")
    filtered = client.get("/whatsapp-conversations", params={"search": "Asha", "unreadOnly": True, "pageSize": 1}, headers=headers)
    assert filtered.status_code == 200 and filtered.json()["data"][0]["id"] == str(matched)
    first = client.get(f"/whatsapp-conversations/{matched}/messages", params={"pageSize": 2}, headers=headers).json()
    second_page = client.get(f"/whatsapp-conversations/{matched}/messages", params={"pageSize": 2, "cursor": first["pagination"]["nextCursor"]}, headers=headers).json()
    assert [item["renderedText"] for item in first["data"]] == ["Message 0", "Message 1"]
    assert [item["renderedText"] for item in second_page["data"]] == ["Message 2"]
    assert client.post(f"/whatsapp-conversations/{matched}/view", headers=headers).status_code == 200
    viewed = client.get("/whatsapp-conversations", params={"unreadOnly": True}, headers=headers).json()["data"]
    assert [item["id"] for item in viewed] == [str(second)]
    admin_unread = client.get("/whatsapp-conversations", params={"unreadOnly": True}, headers=_headers(client, "admin@example.com")).json()["data"]
    assert str(matched) in {item["id"] for item in admin_unread}

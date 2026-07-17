from datetime import datetime, timedelta, timezone
from io import BytesIO

from openpyxl import Workbook

from app.models.user_model import UserRole
from app.repositories.user_repository import insert_staff_user
from app.services.password_service import hash_password

PASSWORD = "Temporary!Pass4827"


def make_admin(database):
    return insert_staff_user({"email": "admin@example.com", "displayName": "Admin", "role": UserRole.SUPER_ADMIN.value, "passwordHash": hash_password(PASSWORD), "isActive": True, "mustChangePassword": False})


def headers(client):
    response = client.post("/auth/login", json={"emailId": "admin@example.com", "password": PASSWORD})
    return {"Authorization": f"Bearer {response.json()['data']['accessToken']}"}


def analyze_csv(client, auth, content=b"Name,Phone,City\nAsha Sen,9876543210,Kolkata\n"):
    return client.post("/contact-imports/analyze", headers=auth, files={"file": ("contacts.csv", content, "text/csv")})


def preview(client, auth, import_id, duplicate_mode="SKIP"):
    return client.post(f"/contact-imports/{import_id}/preview", headers=auth, json={"mapping": {"fullName": "Name", "phone": "Phone", "city": "City"}, "defaults": {"source": "CSV_IMPORT", "status": "NEW", "priority": "MEDIUM"}, "duplicateMode": duplicate_mode})


def test_csv_import_preview_commit_and_retry_are_idempotent(client, database):
    make_admin(database); auth = headers(client)
    analyzed = analyze_csv(client, auth)
    assert analyzed.status_code == 201
    import_id = analyzed.json()["data"]["id"]
    reviewed = preview(client, auth, import_id)
    assert reviewed.status_code == 200
    assert reviewed.json()["data"]["import"]["counts"]["validRows"] == 1
    committed = client.post(f"/contact-imports/{import_id}/commit", headers=auth)
    assert committed.status_code == 200
    assert committed.json()["data"]["counts"]["importedContacts"] == 1
    retried = client.post(f"/contact-imports/{import_id}/commit", headers=auth)
    assert retried.status_code == 200
    assert database.contacts.count_documents({}) == 1
    assert database.leads.count_documents({}) == 1
    assert database.import_job_rows.index_information()["ttl_import_row_expiry"]["expireAfterSeconds"] == 0


def test_import_detects_file_and_database_duplicates_and_exports_rejections(client, database):
    make_admin(database); auth = headers(client)
    content = b"Name,Phone,City\nAsha,9876543210,Kolkata\nDuplicate,9876543210,Delhi\nInvalid,123,Delhi\n"
    first = analyze_csv(client, auth, content); first_id = first.json()["data"]["id"]
    reviewed = preview(client, auth, first_id).json()["data"]
    assert reviewed["import"]["counts"]["withinFileDuplicates"] == 1
    assert reviewed["import"]["counts"]["rejectedRows"] == 1
    report = client.get(f"/contact-imports/{first_id}/rejections", headers=auth)
    assert report.status_code == 200
    assert "Invalid" in report.text
    clean = analyze_csv(client, auth); clean_id = clean.json()["data"]["id"]
    assert preview(client, auth, clean_id).status_code == 200
    client.post(f"/contact-imports/{clean_id}/commit", headers=auth)
    again = analyze_csv(client, auth); again_id = again.json()["data"]["id"]
    duplicate = preview(client, auth, again_id)
    assert duplicate.json()["data"]["import"]["counts"]["existingDuplicates"] == 1


def test_xlsx_magic_formula_and_authorization_controls(client, database):
    make_admin(database); auth = headers(client)
    assert client.post("/contact-imports/analyze", files={"file": ("contacts.csv", b"Name,Phone\nA,9876543210", "text/csv")}).status_code == 401
    bad_magic = client.post("/contact-imports/analyze", headers=auth, files={"file": ("contacts.xlsx", b"not-a-zip", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert bad_magic.status_code == 422
    workbook = Workbook(); sheet = workbook.active; sheet.append(["Name", "Phone"]); sheet.append(["Asha", "=1+1"])
    stream = BytesIO(); workbook.save(stream)
    formula = client.post("/contact-imports/analyze", headers=auth, files={"file": ("contacts.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert formula.status_code == 422


def test_import_rejects_duplicate_headers_and_oversized_file(client, database):
    make_admin(database); auth = headers(client)
    duplicate_headers = analyze_csv(client, auth, b"Phone,phone\n9876543210,9876543211\n")
    assert duplicate_headers.status_code == 422
    oversized = client.post("/contact-imports/analyze", headers=auth, files={"file": ("contacts.csv", b"x" * (5 * 1024 * 1024 + 1), "text/csv")})
    assert oversized.status_code == 413


def test_import_mapping_validation_partial_rows_and_audit(client, database):
    make_admin(database); auth = headers(client)
    analyzed = analyze_csv(client, auth, b"Name,Phone,City\nAsha,9876543210,Kolkata\nBad,123,Delhi\n")
    import_id = analyzed.json()["data"]["id"]
    missing_phone = client.post(f"/contact-imports/{import_id}/preview", headers=auth, json={"mapping": {"fullName": "Name"}, "defaults": {}, "duplicateMode": "SKIP"})
    assert missing_phone.status_code == 422
    reviewed = preview(client, auth, import_id)
    counts = reviewed.json()["data"]["import"]["counts"]
    assert counts["validRows"] == 1 and counts["rejectedRows"] == 1
    client.post(f"/contact-imports/{import_id}/commit", headers=auth)
    assert database.contacts.count_documents({}) == 1
    assert database.audit_logs.count_documents({"action": "CONTACT_IMPORT_ANALYZED"}) == 1
    assert database.audit_logs.count_documents({"action": "CONTACT_IMPORT_PREVIEWED"}) == 1
    assert database.audit_logs.count_documents({"action": "CONTACT_IMPORT_COMMITTED"}) == 1


def test_update_empty_fields_only_preserves_existing_values(client, database):
    make_admin(database); auth = headers(client)
    created = client.post("/contacts", headers=auth, json={"firstName": "Corrected", "phone": "9876543210", "source": "MANUAL_ENTRY"})
    assert created.status_code == 201
    analyzed = analyze_csv(client, auth, b"Name,Phone,City\nWrong Name,9876543210,Kolkata\n")
    import_id = analyzed.json()["data"]["id"]
    reviewed = preview(client, auth, import_id, "UPDATE_EMPTY_FIELDS")
    assert reviewed.json()["data"]["import"]["counts"]["updateEligibleRows"] == 1
    client.post(f"/contact-imports/{import_id}/commit", headers=auth)
    contact = database.contacts.find_one({})
    assert contact["firstName"] == "Corrected"
    assert contact["city"] == "Kolkata"


def test_import_expiry_invalid_extension_and_counsellor_denial(client, database):
    make_admin(database)
    insert_staff_user({"email": "counsellor@example.com", "displayName": "Counsellor", "role": UserRole.COUNSELLOR.value, "passwordHash": hash_password(PASSWORD), "isActive": True, "mustChangePassword": False})
    auth = headers(client)
    invalid = client.post("/contact-imports/analyze", headers=auth, files={"file": ("contacts.txt", b"Name,Phone\nA,9876543210", "text/plain")})
    assert invalid.status_code == 422
    analyzed = analyze_csv(client, auth); import_id = analyzed.json()["data"]["id"]
    database.import_jobs.update_one({}, {"$set": {"artifactExpiresAt": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    assert preview(client, auth, import_id).status_code == 410
    login = client.post("/auth/login", json={"emailId": "counsellor@example.com", "password": PASSWORD})
    counsellor_auth = {"Authorization": f"Bearer {login.json()['data']['accessToken']}"}
    denied = client.post("/contact-imports/analyze", headers=counsellor_auth, files={"file": ("contacts.csv", b"Name,Phone\nA,9876543210", "text/csv")})
    assert denied.status_code == 403

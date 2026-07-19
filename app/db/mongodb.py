import logging
from typing import Any, Optional

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.config import MONGODB_URI


logger = logging.getLogger("whatsapp-webhook")

mongo_client: Optional[MongoClient] = None
db: Optional[Any] = None


def ensure_auth_indexes() -> None:
    users = get_collection("users")
    sessions = get_collection("user_sessions")
    audits = get_collection("audit_logs")

    users.create_index(
        [("emailNormalized", ASCENDING)],
        unique=True,
        partialFilterExpression={"entityType": "STAFF_USER"},
        name="uq_staff_user_email",
    )
    users.create_index(
        [("entityType", ASCENDING), ("role", ASCENDING), ("isActive", ASCENDING)],
        name="ix_staff_user_role_active",
    )
    sessions.create_index(
        [("tokenHash", ASCENDING)],
        unique=True,
        name="uq_user_session_token_hash",
    )
    sessions.create_index(
        [("userId", ASCENDING), ("revokedAt", ASCENDING)],
        name="ix_user_session_user_revoked",
    )
    sessions.create_index(
        [("sessionFamilyId", ASCENDING)],
        name="ix_user_session_family",
    )
    sessions.create_index(
        [("expiresAt", ASCENDING)],
        expireAfterSeconds=0,
        name="ttl_user_session_expiry",
    )
    audits.create_index(
        [("entityType", ASCENDING), ("entityId", ASCENDING), ("occurredAt", DESCENDING)],
        name="ix_audit_entity_time",
    )
    audits.create_index(
        [("actorUserId", ASCENDING), ("occurredAt", DESCENDING)],
        name="ix_audit_actor_time",
    )
    audits.create_index(
        [("action", ASCENDING), ("occurredAt", DESCENDING)],
        name="ix_audit_action_time",
    )
    audits.create_index(
        [("requestId", ASCENDING)],
        sparse=True,
        name="ix_audit_request",
    )


def ensure_phase1a_indexes() -> None:
    contacts = get_collection("contacts")
    preferences = get_collection("contact_preferences")
    suppressions = get_collection("suppression_entries")
    leads = get_collection("leads")
    interests = get_collection("lead_course_interests")
    assignments = get_collection("lead_assignments")
    requests = get_collection("reassignment_requests")
    activities = get_collection("lead_activities")

    contacts.create_index(
        [("normalizedPhone", ASCENDING)],
        unique=True,
        partialFilterExpression={"entityType": "CONTACT"},
        name="uq_contact_normalized_phone",
    )
    contacts.create_index(
        [("normalizedEmail", ASCENDING)],
        sparse=True,
        name="ix_contact_normalized_email",
    )
    contacts.create_index(
        [("source", ASCENDING), ("createdAt", DESCENDING)],
        name="ix_contact_source_created",
    )
    contacts.create_index(
        [("isActive", ASCENDING), ("createdAt", DESCENDING)],
        name="ix_contact_active_created",
    )
    contacts.create_index(
        [("normalizedDisplayName", ASCENDING), ("_id", ASCENDING)],
        name="ix_contact_name",
    )

    preferences.create_index(
        [("contactId", ASCENDING), ("channel", ASCENDING)],
        unique=True,
        name="uq_contact_preference_channel",
    )
    preferences.create_index(
        [("doNotContact", ASCENDING), ("updatedAt", DESCENDING)],
        name="ix_preference_dnc_updated",
    )
    preferences.create_index(
        [("marketingAllowed", ASCENDING), ("updatedAt", DESCENDING)],
        name="ix_preference_marketing_updated",
    )

    suppressions.create_index(
        [("normalizedPhone", ASCENDING), ("channel", ASCENDING)],
        unique=True,
        name="uq_suppression_phone_channel",
    )
    suppressions.create_index(
        [("isActive", ASCENDING), ("updatedAt", DESCENDING)],
        name="ix_suppression_active_updated",
    )

    leads.create_index(
        [("contactId", ASCENDING)],
        unique=True,
        partialFilterExpression={"entityType": "ADMISSION_LEAD", "isActive": True},
        name="uq_active_admission_lead_per_contact",
    )
    leads.create_index(
        [
            ("assignedCounsellorId", ASCENDING),
            ("status", ASCENDING),
            ("priority", DESCENDING),
            ("updatedAt", DESCENDING),
        ],
        name="ix_lead_owner_status_updated",
    )
    leads.create_index(
        [("status", ASCENDING), ("priority", DESCENDING), ("createdAt", DESCENDING)],
        name="ix_lead_status_priority_created",
    )
    leads.create_index(
        [("source", ASCENDING), ("createdAt", DESCENDING)],
        name="ix_lead_source_created",
    )
    leads.create_index(
        [("lastActivityAt", DESCENDING), ("_id", DESCENDING)],
        name="ix_lead_last_activity",
    )
    leads.create_index(
        [("preferredMode", ASCENDING), ("targetExamYear", ASCENDING)],
        name="ix_lead_mode_target_year",
    )

    interests.create_index(
        [("leadId", ASCENDING), ("isPrimary", ASCENDING)],
        unique=True,
        partialFilterExpression={"isPrimary": True},
        name="uq_primary_course_interest_per_lead",
    )
    interests.create_index(
        [("leadId", ASCENDING), ("createdAt", ASCENDING)],
        name="ix_course_interest_lead_created",
    )

    assignments.create_index(
        [("operationId", ASCENDING)],
        unique=True,
        partialFilterExpression={"operationId": {"$exists": True}},
        name="uq_assignment_operation",
    )
    assignments.create_index(
        [("leadId", ASCENDING), ("assignedAt", DESCENDING)],
        name="ix_assignment_lead_time",
    )
    assignments.create_index(
        [("toCounsellorId", ASCENDING), ("assignedAt", DESCENDING)],
        name="ix_assignment_counsellor_time",
    )

    requests.create_index(
        [("leadId", ASCENDING), ("status", ASCENDING)],
        unique=True,
        partialFilterExpression={"status": "PENDING"},
        name="uq_pending_reassignment_per_lead",
    )
    requests.create_index(
        [("status", ASCENDING), ("createdAt", ASCENDING)],
        name="ix_reassignment_status_created",
    )
    requests.create_index(
        [("requestedBy", ASCENDING), ("createdAt", DESCENDING)],
        name="ix_reassignment_requester_created",
    )

    activities.create_index(
        [("operationId", ASCENDING), ("type", ASCENDING)],
        unique=True,
        partialFilterExpression={"operationId": {"$exists": True}},
        name="uq_activity_operation_type",
    )
    activities.create_index(
        [("leadId", ASCENDING), ("createdAt", DESCENDING)],
        name="ix_activity_lead_created",
    )
    activities.create_index(
        [("contactId", ASCENDING), ("createdAt", DESCENDING)],
        name="ix_activity_contact_created",
    )
    activities.create_index(
        [("type", ASCENDING), ("createdAt", DESCENDING)],
        name="ix_activity_type_created",
    )


def ensure_phase1b_indexes() -> None:
    import_jobs = get_collection("import_jobs")
    import_rows = get_collection("import_job_rows")

    import_jobs.create_index(
        [("createdBy", ASCENDING), ("createdAt", DESCENDING)],
        name="ix_import_actor_created",
    )
    import_jobs.create_index(
        [("status", ASCENDING), ("updatedAt", ASCENDING)],
        name="ix_import_status_updated",
    )
    import_jobs.create_index(
        [("fileHash", ASCENDING), ("createdBy", ASCENDING), ("createdAt", DESCENDING)],
        name="ix_import_hash_actor_created",
    )
    import_rows.create_index(
        [("importId", ASCENDING), ("rowNumber", ASCENDING)],
        unique=True,
        name="uq_import_row_number",
    )
    import_rows.create_index(
        [("importId", ASCENDING), ("validationStatus", ASCENDING), ("rowNumber", ASCENDING)],
        name="ix_import_row_status",
    )
    import_rows.create_index(
        [("expiresAt", ASCENDING)],
        expireAfterSeconds=0,
        name="ttl_import_row_expiry",
    )


def ensure_phase2a_indexes() -> None:
    conversations = get_collection("conversations")
    messages = get_collection("whatsapp_messages")
    compatibility_events = get_collection("whatsapp_events")
    failure_details = get_collection("whatsapp_failure_details")

    conversations.create_index(
        [("channel", ASCENDING), ("phoneNumberId", ASCENDING), ("normalizedPhone", ASCENDING)],
        unique=True,
        name="uq_whatsapp_conversation_phone",
    )
    conversations.create_index(
        [("contactId", ASCENDING), ("latestMessageAt", DESCENDING)],
        name="ix_whatsapp_conversation_contact_latest",
    )
    conversations.create_index(
        [("reconciliationStatus", ASCENDING), ("latestInboundAt", DESCENDING)],
        name="ix_whatsapp_conversation_reconciliation",
    )
    messages.create_index(
        [("providerMessageId", ASCENDING)],
        unique=True,
        name="uq_whatsapp_message_provider_id",
    )
    messages.create_index(
        [("conversationId", ASCENDING), ("createdAt", DESCENDING)],
        name="ix_whatsapp_message_conversation_created",
    )
    messages.create_index(
        [("contactId", ASCENDING), ("createdAt", DESCENDING)],
        name="ix_whatsapp_message_contact_created",
    )
    messages.create_index(
        [("status", ASCENDING), ("failedAt", DESCENDING)],
        name="ix_whatsapp_message_status_failed",
    )
    compatibility_events.create_index(
        [("eventKey", ASCENDING)],
        unique=True,
        partialFilterExpression={"eventKey": {"$exists": True}},
        name="uq_whatsapp_event_key",
    )
    failure_details.create_index(
        [("eventKey", ASCENDING)],
        unique=True,
        name="uq_whatsapp_failure_event",
    )
    failure_details.create_index(
        [("expiresAt", ASCENDING)],
        expireAfterSeconds=0,
        name="ttl_whatsapp_failure_details",
    )


def ensure_phase2b1_indexes() -> None:
    templates = get_collection("whatsapp_templates")
    templates.create_index(
        [
            ("businessAccountId", ASCENDING),
            ("providerTemplateKey", ASCENDING),
            ("language", ASCENDING),
        ],
        unique=True,
        name="uq_whatsapp_template_provider_language",
    )
    templates.create_index(
        [
            ("status", ASCENDING),
            ("isActive", ASCENDING),
            ("category", ASCENDING),
            ("name", ASCENDING),
        ],
        name="ix_whatsapp_template_active_catalogue",
    )
    templates.create_index(
        [("businessAccountId", ASCENDING), ("lastSeenSyncId", ASCENDING)],
        name="ix_whatsapp_template_sync_marker",
    )


def ensure_phase2c1_indexes() -> None:
    operations = get_collection("whatsapp_template_send_operations")
    operations.create_index(
        [("actorUserId", ASCENDING), ("idempotencyKey", ASCENDING)],
        unique=True,
        name="uq_whatsapp_template_send_actor_key",
    )
    operations.create_index(
        [("contactId", ASCENDING), ("createdAt", DESCENDING)],
        name="ix_whatsapp_template_send_contact_created",
    )


def ensure_phase2d1_indexes() -> None:
    conversations = get_collection("conversations")
    messages = get_collection("whatsapp_messages")
    reads = get_collection("whatsapp_inbox_reads")
    conversations.create_index([("latestMessageAt", DESCENDING), ("_id", DESCENDING)], name="ix_whatsapp_conversation_latest")
    conversations.create_index([("reconciliationStatus", ASCENDING), ("latestMessageAt", DESCENDING)], name="ix_whatsapp_conversation_inbox_filter")
    messages.create_index([("conversationId", ASCENDING), ("direction", ASCENDING), ("createdAt", ASCENDING)], name="ix_whatsapp_message_inbox_unread")
    reads.create_index([("userId", ASCENDING), ("conversationId", ASCENDING)], unique=True, name="uq_whatsapp_inbox_read_user_conversation")


def ensure_phase2e1_indexes() -> None:
    broadcasts = get_collection("whatsapp_broadcasts")
    recipients = get_collection("whatsapp_broadcast_recipients")
    broadcasts.create_index([("status", ASCENDING), ("createdAt", DESCENDING)], name="ix_whatsapp_broadcast_status_created")
    broadcasts.create_index([("createdBy", ASCENDING), ("createdAt", DESCENDING)], name="ix_whatsapp_broadcast_creator_created")
    recipients.create_index([("broadcastId", ASCENDING), ("status", ASCENDING), ("displayName", ASCENDING)], name="ix_whatsapp_broadcast_recipient_preview")
    recipients.create_index([("broadcastId", ASCENDING), ("contactId", ASCENDING)], unique=True, name="uq_whatsapp_broadcast_recipient_contact")


def connect_to_mongo() -> None:
    global mongo_client, db

    if db is not None:
        ensure_auth_indexes()
        ensure_phase1a_indexes()
        ensure_phase1b_indexes()
        ensure_phase2a_indexes()
        ensure_phase2b1_indexes()
        ensure_phase2c1_indexes()
        ensure_phase2d1_indexes()
        ensure_phase2e1_indexes()
        return
    if not MONGODB_URI:
        raise RuntimeError("MongoDB configuration is missing")
    try:
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command("ping")
        db = mongo_client["geo_whatsapp"]
        ensure_auth_indexes()
        ensure_phase1a_indexes()
        ensure_phase1b_indexes()
        ensure_phase2a_indexes()
        ensure_phase2b1_indexes()
        ensure_phase2c1_indexes()
        ensure_phase2d1_indexes()
        ensure_phase2e1_indexes()
        logger.info("MongoDB connected and application indexes verified.")
    except PyMongoError as exc:
        logger.error("MongoDB connection or index validation failed (%s).", type(exc).__name__)
        raise RuntimeError("MongoDB is unavailable") from exc


def close_mongo_connection() -> None:
    global mongo_client, db
    if mongo_client:
        mongo_client.close()
    mongo_client = None
    db = None


def get_collection(collection_name: str) -> Collection:
    if db is None:
        raise RuntimeError("MongoDB is not connected")
    return db[collection_name]


def set_database_for_testing(database: Any) -> None:
    global db, mongo_client
    mongo_client = None
    db = database

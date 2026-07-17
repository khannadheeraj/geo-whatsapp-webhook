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


def connect_to_mongo() -> None:
    global mongo_client, db

    if db is not None:
        ensure_auth_indexes()
        return
    if not MONGODB_URI:
        raise RuntimeError("MongoDB configuration is missing")
    try:
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command("ping")
        db = mongo_client["geo_whatsapp"]
        ensure_auth_indexes()
        logger.info("MongoDB connected and authentication indexes verified.")
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

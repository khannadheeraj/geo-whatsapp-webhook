import time
import logging
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.config import (
    MONGODB_URI,
    ADMIN_USER_EMAIL,
    ADMIN_USER_PASSWORD,
)

logger = logging.getLogger("whatsapp-webhook")

mongo_client = None
db = None


def connect_to_mongo():

    global mongo_client, db

    try:
        if not MONGODB_URI:
            logger.warning("MONGODB_URI is not configured.")
            return

        mongo_client = MongoClient(MONGODB_URI)
        mongo_client.admin.command("ping")

        db = mongo_client["geo_whatsapp"]

        logger.info("MongoDB connected successfully.")

        admin_collection = db["admin_users"]

        admin_collection.update_one(
            {"emailId": ADMIN_USER_EMAIL},
            {
                "$set": {
                    "emailId": ADMIN_USER_EMAIL,
                    "password": ADMIN_USER_PASSWORD,
                    "updateTime": int(time.time() * 1000),
                },
                "$setOnInsert": {
                    "createTime": int(time.time() * 1000),
                }
            },
            upsert=True
        )

        logger.info("Default admin user initialized successfully.")

    except PyMongoError as e:
        logger.exception("MongoDB connection failed: %s", str(e))

    except Exception as e:
        logger.exception("Application startup failed: %s", str(e))


def close_mongo_connection():

    global mongo_client

    if mongo_client:
        mongo_client.close()
        logger.info("MongoDB connection closed.")


def get_collection(collection_name: str) -> Collection:

    if db is None:
        raise RuntimeError("MongoDB is not connected.")

    return db[collection_name]
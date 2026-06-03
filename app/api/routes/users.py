import time
import logging

from fastapi import APIRouter, HTTPException

from app.db.mongodb import get_collection
from app.schemas.user_schema import BulkUserUploadRequestModel
from app.utils.phone_utils import clean_phone_number

logger = logging.getLogger("whatsapp-webhook")

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)


@router.post("/bulk-upload")
async def bulk_upload_users(payload: BulkUserUploadRequestModel):
    try:
        user_collection = get_collection("users")

        now = int(time.time() * 1000)
        valid_users = []
        invalid_users = []

        for user in payload.users:
            username = user.username.strip() if user.username else ""
            normalized_phone = clean_phone_number(user.phoneNumber)

            if not username or not normalized_phone:
                invalid_users.append(
                    {
                        "username": user.username,
                        "phoneNumber": user.phoneNumber,
                        "message": "Username and valid phoneNumber are required"
                    }
                )
                continue

            valid_users.append(
                {
                    "username": username,
                    "phoneNumber": user.phoneNumber,
                    "normalizedPhone": normalized_phone,
                    "createTime": now,
                    "updateTime": now,
                }
            )

        if not valid_users:
            return {
                "success": True,
                "message": "No valid users to upload",
                "total": len(payload.users),
                "uploaded": 0,
                "alreadyPresent": [],
                "invalidUsers": invalid_users,
            }

        normalized_phones = [user["normalizedPhone"] for user in valid_users]
        existing_users = list(
            user_collection.find(
                {"normalizedPhone": {"$in": normalized_phones}}
            )
        )

        existing_phone_map = {
            user["normalizedPhone"]: user for user in existing_users
        }

        inserted_phones = set()
        already_present = []
        insert_docs = []

        for user in valid_users:
            normalized_phone = user["normalizedPhone"]

            if normalized_phone in existing_phone_map:
                existing = existing_phone_map[normalized_phone]
                already_present.append(
                    {
                        "username": existing.get("username"),
                        "phoneNumber": existing.get("phoneNumber"),
                    }
                )
                continue

            if normalized_phone in inserted_phones:
                already_present.append(
                    {
                        "username": user["username"],
                        "phoneNumber": user["phoneNumber"],
                    }
                )
                continue

            insert_docs.append(user)
            inserted_phones.add(normalized_phone)

        if insert_docs:
            user_collection.insert_many(insert_docs)

        uploaded_count = len(insert_docs)
        already_present_count = len(already_present)

        if uploaded_count and already_present_count:
            message = (
                f"{uploaded_count} user uploaded successfully, "
                f"{already_present_count} users are already present"
            )
        elif uploaded_count:
            message = f"{uploaded_count} users successfully uploaded"
        elif already_present_count:
            message = f"{already_present_count} users are already present"
        else:
            message = "No valid users to upload"

        return {
            "success": True,
            "message": message,
            "total": len(payload.users),
            "uploaded": uploaded_count,
            "alreadyPresent": already_present,
            "invalidUsers": invalid_users,
        }

    except Exception as e:
        logger.exception("Failed to bulk upload users: %s", str(e))
        raise HTTPException(
            status_code=500,
            detail="Something went wrong while uploading users"
        )

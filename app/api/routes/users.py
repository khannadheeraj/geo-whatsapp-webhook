import time
import logging

from fastapi import APIRouter, HTTPException, Query

from app.db.mongodb import get_collection
from app.schemas.user_schema import BulkUserUploadRequestModel
from app.utils.phone_utils import clean_phone_number

logger = logging.getLogger("whatsapp-webhook")

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)


@router.get("/all")
async def get_users(
    page: int = Query(1, ge=1, description="Page number starting from 1"),
    pageSize: int = Query(10, ge=1, le=100, description="Number of users per page"),
    search: str = Query("", description="Search by username or phone number"),
):
    try:
        user_collection = get_collection("users")

        # Build search filter
        search_filter = {}
        if search.strip():
            search_filter = {
                "$or": [
                    {"username": {"$regex": search.strip(), "$options": "i"}},
                    {"phoneNumber": {"$regex": search.strip(), "$options": "i"}},
                    {"normalizedPhone": {"$regex": search.strip(), "$options": "i"}},
                ]
            }

        total_count = user_collection.count_documents(search_filter)

        skip = (page - 1) * pageSize
        limit = pageSize

        users = list(
            user_collection.find(search_filter)
            .sort("createTime", -1)
            .skip(skip)
            .limit(limit)
        )

        total_pages = (total_count + pageSize - 1) // pageSize

        formatted_users = []
        for user in users:
            formatted_users.append(
                {
                    "id": str(user.get("_id")),
                    "username": user.get("username"),
                    "phoneNumber": user.get("phoneNumber"),
                    "normalizedPhone": user.get("normalizedPhone"),
                    "createTime": user.get("createTime"),
                    "updateTime": user.get("updateTime"),
                }
            )

        return {
            "success": True,
            "data": formatted_users,
            "pagination": {
                "page": page,
                "pageSize": pageSize,
                "totalRecords": total_count,
                "totalPages": total_pages,
                "hasNextPage": page < total_pages,
                "hasPrevPage": page > 1,
            },
            "searchQuery": search.strip() if search.strip() else None
        }

    except Exception as e:
        logger.exception("Failed to fetch users: %s", str(e))
        raise HTTPException(
            status_code=500,
            detail="Something went wrong while fetching users"
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

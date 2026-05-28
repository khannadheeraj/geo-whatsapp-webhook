import logging

from fastapi import APIRouter, HTTPException

from app.db.mongodb import get_collection
from app.schemas.admin_schema import LoginRequestModel
from app.utils.jwt_utils import generate_jwt_token


logger = logging.getLogger("whatsapp-webhook")

router = APIRouter(
    prefix="/admin",
    tags=["Admin"]
)


@router.post("/login")
async def admin_login(
    payload: LoginRequestModel
):

    try:

        admin_collection = get_collection(
            "admin_users"
        )

        admin_user = admin_collection.find_one(
            {
                "emailId": payload.emailId,
                "password": payload.password
            }
        )

        if not admin_user:

            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        token = generate_jwt_token(
            admin_user
        )

        return {
            "success": True,
            "message": "Login successful",
            "token": token,
            "userData": {
                "id": str(admin_user.get("_id")),
                "emailId": admin_user.get("emailId")
            }
        }

    except HTTPException:
        raise

    except Exception as e:

        logger.exception(
            "Admin login failed: %s",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Something went wrong"
        )
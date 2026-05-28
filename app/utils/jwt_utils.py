import time
import jwt

from app.config import (
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
    JWT_EXPIRE_HOURS,
)


def generate_jwt_token(admin_user_data):

    payload = {
        "adminUserId": str(admin_user_data.get("_id")),
        "emailId": admin_user_data.get("emailId"),
        "exp": int(time.time()) + (JWT_EXPIRE_HOURS * 60 * 60)
    }

    token = jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM
    )

    return token
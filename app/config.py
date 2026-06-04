import os
from dotenv import load_dotenv

load_dotenv()


MONGODB_URI = (
    os.getenv("MONGODB_URI", "")
    .strip()
    .replace('"', "")
    .replace("'", "")
)

WHATSAPP_VERIFY_TOKEN = os.getenv(
    "WHATSAPP_VERIFY_TOKEN",
    "geo_ias_whatsapp_verify_token"
)

WHATSAPP_ACCESS_TOKEN = os.getenv(
    "WHATSAPP_ACCESS_TOKEN",
    ""
).strip()

WHATSAPP_PHONE_NUMBER_ID = os.getenv(
    "WHATSAPP_PHONE_NUMBER_ID",
    ""
).strip()

WHATSAPP_WABA_ID = os.getenv(
    "WHATSAPP_WABA_ID",
    ""
).strip()

WHATSAPP_GRAPH_API_VERSION = "v20.0"

TEMPLATE_LANGUAGE_CODE = "en_US"

DEFAULT_CAMPAIGN_NAME = "upsc_orientation_may31"
UPSC_ORIENTATION_MAY31_END_DATE = os.getenv(
    "UPSC_ORIENTATION_MAY31_END_DATE",
    "2026-05-31"
).strip()

TEMPLATE_UPSC_FOUNDATION_ADMISSION_OPEN = "upsc_foundation_admission_open"
TEMPLATE_UPSC_FOUNDATION_ADMISSION_OPEN_END_DATE = os.getenv(
    "TEMPLATE_UPSC_FOUNDATION_ADMISSION_OPEN_END_DATE",
    ""
).strip()

TEMPLATE_INVITE = "upsc_orientation_invite_may31"

TEMPLATE_INVITE_FALLBACK_UTILITY = "appointment_reminder_2"

TEMPLATE_FINAL_DAY_REMINDER = "appointment_reminder_2"

TEMPLATE_SEAT_CONFIRMED = "upsc_orientation_seat_confirmed_may31"
TEMPLATE_COUNSELLING = "upsc_orientation_counselling_31st"

ADMIN_USER_EMAIL = os.getenv(
    "ADMIN_USER_EMAIL",
    "admin@gmail.com"
)

ADMIN_USER_PASSWORD = os.getenv(
    "ADMIN_USER_PASSWORD",
    "Admin@123"
)

JWT_SECRET_KEY = "geo_whatsapp_secret_key"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

ENVIRONMENT = os.getenv("ENVIRONMENT", "LOCAL")

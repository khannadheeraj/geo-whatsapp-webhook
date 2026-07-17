import os
from dataclasses import dataclass
from typing import Optional, Tuple

from dotenv import load_dotenv


load_dotenv()


def _clean_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip().replace('"', "").replace("'", "")


def _int_env(name: str, default: int) -> int:
    raw_value = _clean_env(name)
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _bool_env(name: str, default: bool) -> bool:
    raw_value = _clean_env(name)
    if not raw_value:
        return default
    normalized = raw_value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")


def _origins_env() -> Tuple[str, ...]:
    raw_value = _clean_env("AUTH_ALLOWED_ORIGINS", "http://localhost:3000")
    return tuple(origin.strip().rstrip("/") for origin in raw_value.split(",") if origin.strip())


MONGODB_URI = _clean_env("MONGODB_URI")
WHATSAPP_VERIFY_TOKEN = _clean_env("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_ACCESS_TOKEN = _clean_env("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = _clean_env("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_WABA_ID = _clean_env("WHATSAPP_WABA_ID")
WHATSAPP_GRAPH_API_VERSION = "v20.0"

TEMPLATE_LANGUAGE_CODE = "en_US"
DEFAULT_CAMPAIGN_NAME = "upsc_orientation_may31"
UPSC_ORIENTATION_MAY31_END_DATE = _clean_env(
    "UPSC_ORIENTATION_MAY31_END_DATE",
    "2026-05-31",
)
TEMPLATE_UPSC_FOUNDATION_ADMISSION_OPEN = "upsc_foundation_admission_open"
TEMPLATE_UPSC_FOUNDATION_ADMISSION_OPEN_END_DATE = _clean_env(
    "TEMPLATE_UPSC_FOUNDATION_ADMISSION_OPEN_END_DATE"
)
TEMPLATE_INVITE = "upsc_orientation_invite_may31"
TEMPLATE_INVITE_FALLBACK_UTILITY = "appointment_reminder_2"
TEMPLATE_FINAL_DAY_REMINDER = "appointment_reminder_2"
TEMPLATE_SEAT_CONFIRMED = "upsc_orientation_seat_confirmed_may31"
TEMPLATE_COUNSELLING = "upsc_orientation_counselling_31st"
SCHOLARSHIP_MOCK_TEST_CAMPAIGN_NAME = "upsc_scholarship_mock_test_7_june"
TEMPLATE_SCHOLARSHIP_MOCK_TEST = "upsc_scholarship_mock_test_invitation"
FREE_DEMO_CLASS_CAMPAIGN_NAME = "upsc_free_demo_class_27_28_june_reminder"
TEMPLATE_FREE_DEMO_CLASS_INVITATION = "template_name_upsc_free_demo_class_invitation"
TEMPLATE_UPSC_DEMO_CLASS_REMINDER = "upsc_demo_class_reminder"
FREE_DEMO_CLASS_TEMPLATE_DISPLAY_NAME = "Aspirant"
DEMO_CLASS_27_JUN_CAMPAIGN_NAME = "upsc_demo_class_online_offline_27_jun"
TEMPLATE_DEMO_CLASS_ONLINE_OFFLINE_27_JUN = "upsc_demo_class_online_offline_27_jun"
DEMO_CLASS_27_JUN_TEMPLATE_DISPLAY_NAME = "Aspirants"
APPOINTMENT_CONFIRMATION_CAMPAIGN_NAME = "appointment_confirmation_1"
TEMPLATE_APPOINTMENT_CONFIRMATION_1 = "appointment_confirmation_1"
APPOINTMENT_CONFIRMATION_TEMPLATE_DISPLAY_NAME = "Aspirants"

ENVIRONMENT = _clean_env("ENVIRONMENT", "LOCAL").upper()
JWT_ALGORITHM = "HS256"


@dataclass(frozen=True)
class SecuritySettings:
    jwt_secret_key: str
    jwt_algorithm: str
    jwt_issuer: str
    jwt_audience: str
    access_token_minutes: int
    refresh_token_days: int
    password_min_length: int
    refresh_cookie_name: str
    refresh_cookie_secure: bool
    refresh_cookie_samesite: str
    refresh_cookie_domain: Optional[str]
    allowed_origins: Tuple[str, ...]


def get_security_settings() -> SecuritySettings:
    default_cookie_secure = ENVIRONMENT in {"DEV", "PROD", "PRODUCTION"}
    domain = _clean_env("AUTH_COOKIE_DOMAIN") or None
    return SecuritySettings(
        jwt_secret_key=_clean_env("JWT_SECRET_KEY"),
        jwt_algorithm=JWT_ALGORITHM,
        jwt_issuer=_clean_env("AUTH_JWT_ISSUER", "geo-ias-crm"),
        jwt_audience=_clean_env("AUTH_JWT_AUDIENCE", "geo-ias-crm-frontend"),
        access_token_minutes=_int_env("AUTH_ACCESS_TOKEN_MINUTES", 15),
        refresh_token_days=_int_env("AUTH_REFRESH_TOKEN_DAYS", 7),
        password_min_length=_int_env("AUTH_PASSWORD_MIN_LENGTH", 12),
        refresh_cookie_name=_clean_env("AUTH_REFRESH_COOKIE_NAME", "geo_ias_refresh"),
        refresh_cookie_secure=_bool_env("AUTH_COOKIE_SECURE", default_cookie_secure),
        refresh_cookie_samesite=_clean_env("AUTH_COOKIE_SAMESITE", "lax").lower(),
        refresh_cookie_domain=domain,
        allowed_origins=_origins_env(),
    )


def validate_security_configuration() -> SecuritySettings:
    settings = get_security_settings()
    if len(settings.jwt_secret_key) < 32:
        raise RuntimeError("JWT_SECRET_KEY must be configured with at least 32 characters")
    if settings.jwt_secret_key.lower() in {
        "geo_whatsapp_secret_key",
        "change-me",
        "changeme",
    }:
        raise RuntimeError("JWT_SECRET_KEY uses a prohibited default value")
    if settings.jwt_algorithm != "HS256":
        raise RuntimeError("Unsupported JWT algorithm")
    if not 5 <= settings.access_token_minutes <= 60:
        raise RuntimeError("AUTH_ACCESS_TOKEN_MINUTES must be between 5 and 60")
    if not 1 <= settings.refresh_token_days <= 30:
        raise RuntimeError("AUTH_REFRESH_TOKEN_DAYS must be between 1 and 30")
    if not 10 <= settings.password_min_length <= 128:
        raise RuntimeError("AUTH_PASSWORD_MIN_LENGTH must be between 10 and 128")
    if settings.refresh_cookie_samesite not in {"lax", "strict", "none"}:
        raise RuntimeError("AUTH_COOKIE_SAMESITE must be lax, strict, or none")
    if settings.refresh_cookie_samesite == "none" and not settings.refresh_cookie_secure:
        raise RuntimeError("AUTH_COOKIE_SECURE must be true when SameSite is none")
    if not settings.allowed_origins or "*" in settings.allowed_origins:
        raise RuntimeError("AUTH_ALLOWED_ORIGINS must list explicit origins")
    if ENVIRONMENT in {"DEV", "PROD", "PRODUCTION"} and not MONGODB_URI:
        raise RuntimeError("MONGODB_URI must be configured")
    if ENVIRONMENT in {"DEV", "PROD", "PRODUCTION"} and not WHATSAPP_VERIFY_TOKEN:
        raise RuntimeError("WHATSAPP_VERIFY_TOKEN must be configured")
    return settings

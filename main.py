from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.dependencies.auth import require_authenticated_user, require_super_admin
from app.api.error_handlers import api_error_handler, request_id_middleware, unhandled_error_handler, validation_error_handler
from app.api.routes.analytics_router import router as analytics_router
from app.api.routes.auth import router as auth_router
from app.api.routes.campaign import router as campaign_router
from app.api.routes.contacts import router as contacts_router
from app.api.routes.contact_imports import router as contact_imports_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.health import router as health_router
from app.api.routes.leads import router as leads_router
from app.api.routes.reassignment_requests import router as reassignment_requests_router
from app.api.routes.template import router as template_router
from app.api.routes.users import router as users_router
from app.api.routes.whatsapp_webhook import router as whatsapp_webhook_router
from app.api.routes.whatsapp_templates import router as whatsapp_templates_router
from app.api.routes.whatsapp_template_sends import router as whatsapp_template_sends_router
from app.api.routes.whatsapp_conversations import router as whatsapp_conversations_router
from app.config import ENVIRONMENT, get_security_settings, validate_security_configuration
from app.db.mongodb import close_mongo_connection, connect_to_mongo
from app.errors import ApiError


IS_PRODUCTION = ENVIRONMENT in {"DEV", "PROD", "PRODUCTION"}
settings = get_security_settings()
app = FastAPI(
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)
app.middleware("http")(request_id_middleware)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
)


@app.on_event("startup")
def startup_event():
    validate_security_configuration()
    connect_to_mongo()


@app.on_event("shutdown")
def shutdown_event():
    close_mongo_connection()


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(whatsapp_webhook_router)
app.include_router(contacts_router)
app.include_router(contact_imports_router)
app.include_router(dashboard_router)
app.include_router(leads_router)
app.include_router(reassignment_requests_router)
app.include_router(template_router, dependencies=[Depends(require_authenticated_user)])
app.include_router(whatsapp_templates_router)
app.include_router(whatsapp_template_sends_router)
app.include_router(whatsapp_conversations_router)
app.include_router(users_router)
app.include_router(campaign_router, dependencies=[Depends(require_super_admin)])
app.include_router(analytics_router, dependencies=[Depends(require_super_admin)])

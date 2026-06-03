from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.mongodb import connect_to_mongo, close_mongo_connection
from app.api.routes.health import router as health_router
from app.api.routes.admin import router as admin_router
from app.api.routes.whatsapp_webhook import router as whatsapp_webhook_router
from app.api.routes.campaign import router as campaign_router
from app.api.routes.analytics_router import router as analytics_router
from app.api.routes.users import router as users_router

from app.config import *

IS_PRODUCTION = ENVIRONMENT.upper() in ["DEV", "PROD"]

# app = FastAPI()

app = FastAPI(
    # lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    connect_to_mongo()


@app.on_event("shutdown")
def shutdown_event():
    close_mongo_connection()


app.include_router(health_router)
app.include_router(admin_router)
app.include_router(whatsapp_webhook_router)
app.include_router(campaign_router)
app.include_router(analytics_router)
app.include_router(users_router)
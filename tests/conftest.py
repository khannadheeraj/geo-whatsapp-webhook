import os

os.environ["ENVIRONMENT"] = "TEST"
os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-at-least-32-characters"
os.environ["AUTH_ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["AUTH_COOKIE_SECURE"] = "false"
os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-webhook-verification-token"
os.environ["WHATSAPP_APP_SECRET"] = "test-only-meta-app-secret-32-characters"

import mongomock
import pytest
from fastapi.testclient import TestClient

from app.db.mongodb import (
    ensure_auth_indexes,
    ensure_phase1a_indexes,
    ensure_phase1b_indexes,
    ensure_phase2a_indexes,
    set_database_for_testing,
)
from main import app


@pytest.fixture()
def database():
    database = mongomock.MongoClient().geo_whatsapp_test
    set_database_for_testing(database)
    ensure_auth_indexes()
    ensure_phase1a_indexes()
    ensure_phase1b_indexes()
    ensure_phase2a_indexes()
    return database


@pytest.fixture()
def client(database):
    with TestClient(app) as test_client:
        yield test_client

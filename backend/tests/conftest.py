"""Shared environment setup and fixtures for the backend test suite.

The environment variables are assigned at import time rather than from a
fixture: pytest imports conftest before the test modules, and importing
app.main pulls in application configuration, so a fixture would run too late.
"""

import os

EXTENSION_API_KEY = "test-extension-key"

os.environ.setdefault("AI_BUILDER_BASE_URL", "https://example.com")
os.environ.setdefault("AI_BUILDER_TOKEN", "test-token")
os.environ.setdefault("UPSTASH_REDIS_REST_URL", "https://test.upstash.io")
os.environ.setdefault("UPSTASH_REDIS_REST_TOKEN", "test")
os.environ.setdefault("HMAC_SECRET", "test-hmac-secret")
os.environ.setdefault("FINGERPRINT_SECRET", "test-fingerprint-secret")
os.environ.setdefault("EXTENSION_API_KEY", EXTENSION_API_KEY)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

AUTH_HEADERS = {"X-Extension-Key": EXTENSION_API_KEY}


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict:
    return dict(AUTH_HEADERS)


@pytest.fixture
def valid_lookup_body() -> dict:
    """A body that passes schema validation, so tests built on it exercise the
    behavior under test rather than tripping over request validation."""
    return {
        "client_request_id": "550e8400-e29b-41d4-a716-446655440000",
        "install_id": "550e8400-e29b-41d4-a716-446655440001",
        "selected_text": "hello",
        "full_context": None,
        "target_language": None,
        "mode": "meaning_only",
        "page_url": "https://example.com/page",
        "extension_version": "1.0.0",
    }

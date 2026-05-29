"""API tests for Define & Translate backend."""

import pytest
from fastapi.testclient import TestClient

# Mock settings before importing app
import os
os.environ.setdefault("AI_BUILDER_BASE_URL", "https://example.com")
os.environ.setdefault("AI_BUILDER_TOKEN", "test-token")
os.environ.setdefault("UPSTASH_REDIS_REST_URL", "https://test.upstash.io")
os.environ.setdefault("UPSTASH_REDIS_REST_TOKEN", "test")
os.environ.setdefault("HMAC_SECRET", "test-hmac-secret")
os.environ.setdefault("FINGERPRINT_SECRET", "test-fingerprint-secret")

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_lookup_malformed_json():
    r = client.post("/api/lookup", content="not json")
    assert r.status_code == 400
    data = r.json()
    assert data["error_code"] == "REQUEST_MALFORMED"
    assert "server_request_id" in data


def test_lookup_validation_empty_body():
    r = client.post("/api/lookup", json={})
    assert r.status_code == 422


def test_lookup_validation_selection_too_long():
    r = client.post("/api/lookup", json={
        "client_request_id": "550e8400-e29b-41d4-a716-446655440000",
        "install_id": "550e8400-e29b-41d4-a716-446655440001",
        "selected_text": "x" * 301,
        "full_context": None,
        "target_language": None,
        "mode": "meaning_only",
        "page_url": "https://example.com/page",
        "extension_version": "1.0.0",
    })
    assert r.status_code == 422
    data = r.json()
    assert data["error_code"] == "SELECTION_TOO_LONG"


def test_lookup_validation_invalid_uuid():
    r = client.post("/api/lookup", json={
        "client_request_id": "not-a-uuid",
        "install_id": "550e8400-e29b-41d4-a716-446655440001",
        "selected_text": "hello",
        "full_context": None,
        "target_language": None,
        "mode": "meaning_only",
        "page_url": "https://example.com/page",
        "extension_version": "1.0.0",
    })
    assert r.status_code == 422


def test_lookup_validation_http_page():
    r = client.post("/api/lookup", json={
        "client_request_id": "550e8400-e29b-41d4-a716-446655440000",
        "install_id": "550e8400-e29b-41d4-a716-446655440001",
        "selected_text": "hello",
        "full_context": None,
        "target_language": None,
        "mode": "meaning_only",
        "page_url": "http://example.com/page",
        "extension_version": "1.0.0",
    })
    assert r.status_code == 422

"""Request-validation tests for POST /api/lookup.

This file covers the LookupRequest schema/body validation behavior only.
Credentials come from the auth_headers fixture so these tests exercise
validation rather than the auth dependency.
"""


def test_lookup_malformed_json(client, auth_headers):
    r = client.post("/api/lookup", content="not json", headers=auth_headers)
    assert r.status_code == 400
    data = r.json()
    assert data["error_code"] == "REQUEST_MALFORMED"
    assert "server_request_id" in data


def test_lookup_validation_empty_body(client, auth_headers):
    r = client.post("/api/lookup", json={}, headers=auth_headers)
    assert r.status_code == 422
    data = r.json()
    assert data["error_code"] == "REQUEST_INVALID"


def test_lookup_validation_selection_too_long(client, auth_headers, valid_lookup_body):
    r = client.post(
        "/api/lookup",
        json={**valid_lookup_body, "selected_text": "x" * 301},
        headers=auth_headers,
    )
    assert r.status_code == 422
    data = r.json()
    assert data["error_code"] == "SELECTION_TOO_LONG"


def test_lookup_validation_invalid_uuid(client, auth_headers, valid_lookup_body):
    r = client.post(
        "/api/lookup",
        json={**valid_lookup_body, "client_request_id": "not-a-uuid"},
        headers=auth_headers,
    )
    assert r.status_code == 422
    data = r.json()
    assert data["error_code"] == "REQUEST_INVALID"


def test_lookup_validation_http_page(client, auth_headers, valid_lookup_body):
    r = client.post(
        "/api/lookup",
        json={**valid_lookup_body, "page_url": "http://example.com/page"},
        headers=auth_headers,
    )
    assert r.status_code == 422
    data = r.json()
    assert data["error_code"] == "HTTPS_ONLY"

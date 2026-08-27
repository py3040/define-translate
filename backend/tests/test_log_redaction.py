"""Log-redaction tests for POST /api/lookup validation-error paths.

Scope: confirm that raw `selected_text`, `full_context`, `page_url`, and
client IP values never reach the structured JSON logs emitted for a request
that fails validation. `_sanitize_pydantic_errors` (app/services/errors.py)
is the only place these fields could otherwise leak into `internal_message`,
so these tests drive the real HTTP interface and inspect the actual log
output, rather than unit-testing `_sanitize_pydantic_errors` in isolation,
so they also catch a future call site that passes raw errors instead of the
sanitized string.

This complements test_lookup_validation.py (response-body/status-code
behavior) and test_lookup_auth.py (auth-failure log fields) without
duplicating either.
"""

import io
import json
import logging

from upstash_redis.errors import UpstashError

from app.routers import lookup as lookup_router
from app.services.logging_config import JSON_HANDLER_NAME

# Distinctive marker strings so a substring match in the log output can only
# be explained by the raw field value leaking through.
_SECRET_SELECTED_TEXT = "SELECTED-TEXT-MARKER-" + ("x" * 301)
_SECRET_FULL_CONTEXT = "FULL-CONTEXT-MARKER-" + ("y" * 5000)
_SECRET_PAGE_URL = "http://leak-marker.example.com/page"
_SECRET_CLIENT_IP = "203.0.113.99"


class _FailingRedis:
    """Stand-in for the Upstash client, the external system at this boundary.

    Reads raise so the handler takes its own error path; every other command is
    a no-op so the record_failure background task doesn't reach the network.
    """

    def get(self, *args, **kwargs):
        raise UpstashError("simulated redis failure")

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _capture_root_log_output(make_request):
    """Swap the stream on the app's real logging handler (installed once by
    setup_logging() in app.main) so we can inspect the actual JSON lines it
    emits, not just in-memory LogRecord attributes."""
    handlers = [h for h in logging.getLogger().handlers if h.name == JSON_HANDLER_NAME]
    assert len(handlers) == 1, f"expected one {JSON_HANDLER_NAME} handler, got {handlers}"
    handler = handlers[0]
    original_stream = handler.stream
    buffer = io.StringIO()
    handler.stream = buffer
    try:
        response = make_request()
    finally:
        handler.stream = original_stream
    lines = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
    return response, lines


def _assert_marker_absent(log_lines: list[dict], marker: str):
    raw_output = json.dumps(log_lines)
    assert marker not in raw_output, (
        f"found raw value {marker[:40]!r}... in logged output: {raw_output[:500]}"
    )


def test_oversized_selected_text_not_logged_raw(client, auth_headers, valid_lookup_body):
    response, log_lines = _capture_root_log_output(
        lambda: client.post(
            "/api/lookup",
            json={**valid_lookup_body, "selected_text": _SECRET_SELECTED_TEXT},
            headers=auth_headers,
        )
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "SELECTION_TOO_LONG"
    assert len(log_lines) >= 1
    _assert_marker_absent(log_lines, _SECRET_SELECTED_TEXT)


def test_oversized_full_context_not_logged_raw(client, auth_headers, valid_lookup_body):
    response, log_lines = _capture_root_log_output(
        lambda: client.post(
            "/api/lookup",
            json={**valid_lookup_body, "full_context": _SECRET_FULL_CONTEXT},
            headers=auth_headers,
        )
    )

    assert response.status_code == 422
    assert len(log_lines) >= 1
    _assert_marker_absent(log_lines, _SECRET_FULL_CONTEXT)


def test_invalid_page_url_not_logged_raw(client, auth_headers, valid_lookup_body):
    response, log_lines = _capture_root_log_output(
        lambda: client.post(
            "/api/lookup",
            json={**valid_lookup_body, "page_url": _SECRET_PAGE_URL},
            headers=auth_headers,
        )
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "HTTPS_ONLY"
    assert len(log_lines) >= 1
    _assert_marker_absent(log_lines, _SECRET_PAGE_URL)


def test_client_ip_not_logged_raw_on_handler_error(
    client, auth_headers, valid_lookup_body, monkeypatch
):
    """The raw client IP is only ever used in-memory to compute a hashed IP for
    rate limiting (get_client_ip/hash_client_ip in routers/lookup.py) and must
    never reach log_error. Both run inside the handler, so the body must be
    valid and the failure injected at the Redis boundary to get there.
    """
    monkeypatch.setattr(lookup_router, "get_redis", lambda settings: _FailingRedis())

    response, log_lines = _capture_root_log_output(
        lambda: client.post(
            "/api/lookup",
            json=valid_lookup_body,
            headers={
                # Every hop is the marker, so get_client_ip selects it whatever
                # trusted_proxy_hops is set to and the test can't go vacuous if
                # that setting changes.
                **auth_headers,
                "X-Forwarded-For": ", ".join([_SECRET_CLIENT_IP] * 3),
            },
        )
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "REDIS_ERROR"
    assert len(log_lines) >= 1
    _assert_marker_absent(log_lines, _SECRET_CLIENT_IP)


def test_malformed_json_body_not_logged_raw(client, auth_headers):
    """Malformed JSON bodies go through a different branch of the
    RequestValidationError handler (REQUEST_MALFORMED) than field-level
    validation errors; confirm it's covered too."""
    secret_body = f'{{"selected_text": "{_SECRET_SELECTED_TEXT}"'  # intentionally truncated/invalid JSON

    response, log_lines = _capture_root_log_output(
        lambda: client.post("/api/lookup", content=secret_body, headers=auth_headers)
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "REQUEST_MALFORMED"
    assert len(log_lines) >= 1
    _assert_marker_absent(log_lines, _SECRET_SELECTED_TEXT)

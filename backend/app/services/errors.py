"""Error response helpers per Requirements_backend.csv."""

import logging

from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def error_response(
    status_code: int,
    error_code: str,
    error_message: str,
    server_request_id: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error_code,
            "error_message": error_message,
            "server_request_id": server_request_id,
        },
    )


def _classify_validation_error(errors: list) -> tuple[int, str, str]:
    """Return (http_status, error_code, error_message) for a Pydantic error list."""
    for err in errors:
        loc = err.get("loc", [])
        msg = str(err.get("msg", "")).lower()
        ctx = err.get("ctx", {})
        if "selected_text" in str(loc) or "full_context" in str(loc):
            if "300" in msg or "max" in msg or "length" in str(ctx):
                return (
                    422,
                    "SELECTION_TOO_LONG",
                    "Selection exceeds 300 chars. Please select less text.",
                )
        if "target_language" in str(loc):
            return (
                422,
                "LANGUAGE_NOT_SUPPORTED",
                "This language isn't supported yet. Please choose a different language.",
            )
        if "page_url" in str(loc):
            if "https" in msg:
                return (422, "HTTPS_ONLY", "Lookup is not supported on this page.")
            if "unsupported keyword" in msg:
                return (422, "UNSUPPORTED_PAGE", "Lookup is not supported on this page.")
    return (422, "REQUEST_INVALID", "Couldn't process the selection. Please try again.")


def _sanitize_pydantic_errors(errors: list) -> str:
    """Serialise Pydantic validation errors per TR-1.05-03a.

    Only type, loc, and msg are included.  The input and ctx fields are
    deliberately excluded because they may contain raw field values such as
    selected_text or full_context.
    """
    parts = []
    for err in errors:
        loc = list(err.get("loc", []))
        typ = err.get("type", "")
        msg = err.get("msg", "")
        parts.append(f"validation error on field {loc}: {typ} — {msg}")
    return "; ".join(parts)


def map_validation_error(errors: list, server_request_id: str) -> JSONResponse:
    """Map Pydantic validation errors to TR-1.01-09 error codes."""
    http_status, error_code, error_message = _classify_validation_error(errors)
    return error_response(http_status, error_code, error_message, server_request_id)


def log_error(
    server_request_id: str,
    client_request_id: str | None,
    install_id: str | None,
    hashed_ip: str | None,
    extension_version: str | None,
    mode: str | None,
    http_status: int,
    error_code: str,
    error_message: str = "",
    internal_message: str | None = None,
    upstream_status: int | None = None,
    exc_info: bool = False,
) -> None:
    """Emit one structured JSON error event per TR-1.05.

    Never pass selected_text, full_context, or page_url to this function.
    For Pydantic validation errors use _sanitize_pydantic_errors() to build
    internal_message so that the raw input and ctx fields are excluded.
    """
    logger.error(
        "lookup_error",
        exc_info=exc_info,
        extra={
            "server_request_id": server_request_id,
            "client_request_id": client_request_id,
            "install_id": install_id,
            "hashed_ip": hashed_ip,
            "extension_version": extension_version,
            "mode": mode,
            "http_status": http_status,
            "error_code": error_code,
            "error_message": error_message,
            "internal_message": internal_message,
            "upstream_status": upstream_status,
        },
    )

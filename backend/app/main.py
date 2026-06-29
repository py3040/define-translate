"""Define & Translate FastAPI backend."""

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError

from app.config import Settings
from app.routers import analytics, lookup
from app.services.errors import (
    _classify_validation_error,
    _sanitize_pydantic_errors,
    error_response,
    log_error,
    map_validation_error,
)
from app.services.logging_config import request_route, setup_logging

setup_logging()
logging.getLogger("httpx").setLevel(logging.WARNING)

# TEMPORARY — retention test marker. Remove once retention period is confirmed.
logging.getLogger(__name__).info("RETENTION_TEST_MARKER_XK7Q")

settings = Settings()
_docs_enabled = settings.environment == "development"

app = FastAPI(
    title="Define & Translate API",
    version="1.0.0",
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

app.include_router(lookup.router, prefix="/api", tags=["lookup"])
app.include_router(analytics.router, prefix="/api", tags=["analytics"])


@app.middleware("http")
async def set_route_context(request: Request, call_next):
    request_route.set(request.url.path)
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    server_request_id = str(uuid.uuid4())
    errors = exc.errors()
    for err in errors:
        err_type = err.get("type", "")
        msg = str(err.get("msg", "")).lower()
        loc = err.get("loc", ())
        is_body_error = "body" in loc or ("body",) == loc[:1]
        if (
            err_type == "json_invalid"
            or (err_type == "model_attributes_type" and is_body_error)
            or "json" in msg
            or "parse" in msg
            or ("dictionary or object" in msg and is_body_error)
        ):
            log_error(
                server_request_id,
                client_request_id=None,
                install_id=None,
                hashed_ip=None,
                extension_version=None,
                mode=None,
                http_status=400,
                error_code="REQUEST_MALFORMED",
                error_message="Invalid request format. Please try again.",
                internal_message=_sanitize_pydantic_errors(errors),
            )
            return error_response(
                400,
                "REQUEST_MALFORMED",
                "Invalid request format. Please try again.",
                server_request_id,
            )
    http_status, error_code, error_message = _classify_validation_error(errors)
    log_error(
        server_request_id,
        client_request_id=None,
        install_id=None,
        hashed_ip=None,
        extension_version=None,
        mode=None,
        http_status=http_status,
        error_code=error_code,
        error_message=error_message,
        internal_message=_sanitize_pydantic_errors(errors),
    )
    return map_validation_error(errors, server_request_id)


@app.exception_handler(Exception)
async def unexpected_exception_handler(request: Request, exc: Exception):
    server_request_id = str(uuid.uuid4())
    log_error(
        server_request_id,
        client_request_id=None,
        install_id=None,
        hashed_ip=None,
        extension_version=None,
        mode=None,
        http_status=500,
        error_code="INTERNAL_ERROR_UNEXPECTED",
        error_message="Something went wrong. Please try again later.",
        internal_message=str(exc),
        exc_info=True,
    )
    return error_response(
        500,
        "INTERNAL_ERROR_UNEXPECTED",
        "Something went wrong. Please try again later.",
        server_request_id,
    )


@app.get("/health")
def health():
    return {"status": "ok"}

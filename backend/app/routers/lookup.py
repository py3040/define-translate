"""Lookup API router."""

import asyncio
import json as _json
import logging
import time
import uuid
from urllib.parse import urlparse, urlunparse

import httpx
from upstash_redis.errors import UpstashError
from fastapi import APIRouter, BackgroundTasks, Request

from app.models.schemas import LookupRequest, LookupSuccessResponse, LookupErrorResponse

logger = logging.getLogger(__name__)
from app.config import Settings
from app.services.redis_client import (
    get_redis,
    get_cache,
    set_cache,
    check_burst,
    check_usage,
    incr_usage,
    acquire_inflight,
    release_inflight,
    poll_cache_for_inflight,
)
from app.services.normalize import normalize_text, normalize_language
from app.services.fingerprint import compute_fingerprint
from app.services.ip_hash import hash_client_ip
from app.services.analytics import record_failure, record_success
from app.services.errors import error_response, log_error
from fastapi.responses import JSONResponse


def get_settings() -> Settings:
    return Settings()


def get_client_ip(request: Request, trusted_hops: int) -> str:
    """Return the real client IP for rate limiting.

    Behind this platform, a fixed number of trusted proxies (platform proxy +
    Cloudflare) append to ``X-Forwarded-For``, so the genuine client IP is the
    entry ``trusted_hops`` positions from the right. Anything further left is
    client-supplied and must not be trusted (it can be spoofed to bypass
    per-IP limits). Verified empirically via GET /api/_debug/ip across home,
    VPN and cellular networks.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if len(parts) >= trusted_hops >= 1:
            return parts[-trusted_hops]
        if parts:
            # Fewer entries than expected (e.g. local/dev): fall back to the
            # right-most, which is still the closest trusted-proxy value.
            return parts[-1]
    return request.client.host if request.client else "0.0.0.0"


def canonicalize_page_url(url: str) -> str:
    """Strip query and fragment for abuse control."""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


async def wait_for_disconnect(request: Request) -> None:
    """
    Block until the client disconnects.
    Reads from the ASGI receive stream until http.disconnect.
    Used to cancel in-flight AI Builder Space calls when the extension aborts.
    """
    receive = getattr(request, "receive", None) or request.scope.get("receive")
    if not receive:
        return
    while True:
        message = await receive()
        if message.get("type") == "http.disconnect":
            return


def _classify_redis_error(e: UpstashError) -> str:
    """Map an UpstashError message to a specific error code for troubleshooting."""
    msg = str(e).upper()
    if "OOM" in msg or "MAXMEMORY" in msg:
        return "REDIS_OOM"
    if "NOAUTH" in msg or "WRONGPASS" in msg:
        return "REDIS_AUTH_ERROR"
    return "REDIS_ERROR"


router = APIRouter()


@router.post("/lookup")
async def lookup(
    body: LookupRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    t_start = time.perf_counter()
    timing_ms: dict[str, float] = {}
    server_request_id = str(uuid.uuid4())
    settings = get_settings()
    redis = get_redis(settings)
    from datetime import datetime, timezone
    utc_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    page_url_canonical = canonicalize_page_url(body.page_url)
    client_ip = get_client_ip(request, settings.trusted_proxy_hops)
    hashed_ip = hash_client_ip(client_ip, settings.hmac_secret)

    def _err(
        http_status: int,
        error_code: str,
        error_message: str,
        internal_message: str | None = None,
        upstream_status: int | None = None,
    ) -> JSONResponse:
        """Log one structured error event, enqueue analytics, then return the error response."""
        log_error(
            server_request_id,
            body.client_request_id,
            body.install_id,
            hashed_ip,
            body.extension_version,
            body.mode,
            page_url_canonical,
            http_status,
            error_code,
            error_message,
            internal_message,
            upstream_status,
        )
        background_tasks.add_task(record_failure, redis, body.install_id, utc_date)
        return error_response(http_status, error_code, error_message, server_request_id)

    selected_text_norm = normalize_text(body.selected_text)
    if not selected_text_norm:
        return _err(
            422,
            "REQUEST_INVALID",
            "Couldn't process the selection. Please try again.",
        )

    full_context_norm = normalize_text(body.full_context)
    target_language_norm = normalize_language(body.target_language)

    fingerprint = compute_fingerprint(
        selected_text_norm,
        full_context_norm,
        target_language_norm,
        body.mode,
        settings.fingerprint_secret,
    )

    try:
        t_before_cache = time.perf_counter()
        cached = get_cache(redis, fingerprint)
        timing_ms["redis_get_cache"] = (time.perf_counter() - t_before_cache) * 1000
        if cached is not None:
            timing_ms["total"] = (time.perf_counter() - t_start) * 1000
            timing_ms["cache_hit"] = True
            logger.info("Lookup timing (cache hit) server_request_id=%s timing_ms=%s", server_request_id, timing_ms)
            background_tasks.add_task(record_success, redis, body.install_id, utc_date)
            return cached.get("response_payload")

        t_before_pre_ai = time.perf_counter()
        burst_ok, burst_err = check_burst(redis, body.install_id, hashed_ip)
        if not burst_ok:
            timing_ms["total"] = (time.perf_counter() - t_start) * 1000
            logger.info("Lookup timing (burst rejected) server_request_id=%s timing_ms=%s", server_request_id, timing_ms)
            return _err(
                429,
                burst_err or "TOO_MANY_REQUESTS",
                "Too many requests. Please try again in a few seconds.",
            )

        usage_ok, usage_err = check_usage(redis, body.install_id, hashed_ip)
        if not usage_ok:
            timing_ms["total"] = (time.perf_counter() - t_start) * 1000
            logger.info("Lookup timing (usage exceeded) server_request_id=%s timing_ms=%s", server_request_id, timing_ms)
            return _err(
                429,
                usage_err or "EXCEED_LIMITS",
                "Daily limit reached. Resets at midnight UTC",
            )

        lock_acquired = acquire_inflight(redis, fingerprint, server_request_id)
        if not lock_acquired:
            t_before_poll = time.perf_counter()
            polled = poll_cache_for_inflight(redis, fingerprint)
            timing_ms["redis_poll_inflight"] = (time.perf_counter() - t_before_poll) * 1000
            timing_ms["redis_pre_ai"] = (t_before_poll - t_before_pre_ai) * 1000
            timing_ms["total"] = (time.perf_counter() - t_start) * 1000
            logger.info("Lookup timing (in-flight poll) server_request_id=%s timing_ms=%s", server_request_id, timing_ms)
            if polled is not None:
                background_tasks.add_task(record_success, redis, body.install_id, utc_date)
                return polled
            return _err(
                503,
                "INFLIGHT_WAIT_TIMEOUT",
                "This lookup is taking longer than expected. Please try again in a few seconds.",
            )

        timing_ms["redis_pre_ai"] = (time.perf_counter() - t_before_pre_ai) * 1000
    except httpx.ConnectError as e:
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        return _err(
            503, "REDIS_CONNECT_ERROR",
            "Service is temporarily unavailable. Please try again later.",
            internal_message=str(e),
        )
    except UpstashError as e:
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        return _err(
            503, _classify_redis_error(e),
            "Service is temporarily unavailable. Please try again later.",
            internal_message=str(e),
        )
    except httpx.TransportError as e:
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        return _err(
            503, "REDIS_TRANSPORT_ERROR",
            "Service is temporarily unavailable. Please try again later.",
            internal_message=str(e),
        )
    except _json.JSONDecodeError as e:
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        return _err(
            503, "REDIS_RESPONSE_INVALID",
            "Service is temporarily unavailable. Please try again later.",
            internal_message=str(e),
        )
    except Exception as e:
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        return _err(
            503, "REDIS_ERROR",
            "Service is temporarily unavailable. Please try again later.",
            internal_message=str(e),
        )

    from app.services.ai_builder import (
        call_ai_builder_space,
        UpstreamAuthError,
        UpstreamRateLimitedError,
        UpstreamTimeoutError,
        UpstreamError,
        UpstreamRequestFailedError,
        UpstreamClientError,
        UpstreamResponseInvalidError,
        UpstreamResponseTooLongError,
    )

    async def run_ai_call():
        return await call_ai_builder_space(
            settings=settings,
            selected_text_norm=selected_text_norm,
            full_context_norm=full_context_norm,
            target_language_norm=target_language_norm,
            mode=body.mode,
            server_request_id=server_request_id,
        )

    ai_task = asyncio.create_task(run_ai_call())
    disconnect_task = asyncio.create_task(wait_for_disconnect(request))

    try:
        done, pending = await asyncio.wait(
            [ai_task, disconnect_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if disconnect_task in done:
            ai_task.cancel()
            try:
                await ai_task
            except asyncio.CancelledError:
                pass
            release_inflight(redis, fingerprint)
            logger.info(
                "Lookup cancelled (client disconnected) server_request_id=%s",
                server_request_id,
            )
            background_tasks.add_task(record_failure, redis, body.install_id, utc_date)
            return error_response(
                499,
                "CLIENT_CLOSED_REQUEST",
                "Request cancelled by client.",
                server_request_id,
            )

        disconnect_task.cancel()
        try:
            await disconnect_task
        except asyncio.CancelledError:
            pass

        response_payload, ai_builder_elapsed_sec = ai_task.result()
        timing_ms["ai_builder"] = ai_builder_elapsed_sec * 1000

        t_before_post_ai = time.perf_counter()
        try:
            incr_usage(redis, body.install_id, hashed_ip)
            set_cache(redis, fingerprint, response_payload)
        except httpx.ConnectError as e:
            log_error(
                server_request_id, body.client_request_id, body.install_id, hashed_ip,
                body.extension_version, body.mode, page_url_canonical,
                200, "REDIS_CONNECT_ERROR",
                internal_message=str(e),
            )
        except UpstashError as e:
            log_error(
                server_request_id, body.client_request_id, body.install_id, hashed_ip,
                body.extension_version, body.mode, page_url_canonical,
                200, _classify_redis_error(e),
                internal_message=str(e),
            )
        except httpx.TransportError as e:
            log_error(
                server_request_id, body.client_request_id, body.install_id, hashed_ip,
                body.extension_version, body.mode, page_url_canonical,
                200, "REDIS_TRANSPORT_ERROR",
                internal_message=str(e),
            )
        except _json.JSONDecodeError as e:
            log_error(
                server_request_id, body.client_request_id, body.install_id, hashed_ip,
                body.extension_version, body.mode, page_url_canonical,
                200, "REDIS_RESPONSE_INVALID",
                internal_message=str(e),
            )
        except Exception as e:
            log_error(
                server_request_id, body.client_request_id, body.install_id, hashed_ip,
                body.extension_version, body.mode, page_url_canonical,
                200, "REDIS_ERROR",
                internal_message=str(e),
            )
        timing_ms["redis_post_ai"] = (time.perf_counter() - t_before_post_ai) * 1000
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        logger.info("Lookup timing (cache miss) server_request_id=%s timing_ms=%s", server_request_id, timing_ms)
        background_tasks.add_task(record_success, redis, body.install_id, utc_date)
        return response_payload
    except asyncio.CancelledError:
        ai_task.cancel()
        disconnect_task.cancel()
        try:
            await ai_task
        except asyncio.CancelledError:
            pass
        try:
            await disconnect_task
        except asyncio.CancelledError:
            pass
        release_inflight(redis, fingerprint)
        raise
    except UpstreamAuthError as e:
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        logger.info("Lookup timing (error: upstream auth) server_request_id=%s timing_ms=%s", server_request_id, timing_ms)
        return _err(
            503, "UPSTREAM_AUTH_ERROR",
            "Service is temporarily unavailable. Please try again later.",
            internal_message=e.upstream_body,
            upstream_status=e.status_code,
        )
    except UpstreamRateLimitedError as e:
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        logger.info("Lookup timing (error: upstream rate limited) server_request_id=%s timing_ms=%s", server_request_id, timing_ms)
        return _err(
            503, "UPSTREAM_RATE_LIMITED",
            "Service is temporarily unavailable. Please try again later.",
            internal_message=e.upstream_body,
            upstream_status=e.status_code,
        )
    except UpstreamTimeoutError as e:
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        logger.info("Lookup timing (error: upstream gateway timeout) server_request_id=%s timing_ms=%s", server_request_id, timing_ms)
        return _err(
            503, "UPSTREAM_GATEWAY_TIMEOUT",
            "Service is taking too long. Please try again.",
            internal_message=e.upstream_body,
            upstream_status=e.status_code,
        )
    except UpstreamRequestFailedError as e:
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        logger.info("Lookup timing (error: upstream request failed) server_request_id=%s timing_ms=%s", server_request_id, timing_ms)
        return _err(
            500, "UPSTREAM_REQUEST_FAILED",
            "Couldn't complete the lookup. Please try again.",
            internal_message=e.upstream_body,
            upstream_status=e.status_code,
        )
    except UpstreamResponseInvalidError as e:
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        logger.info("Lookup timing (error: upstream response invalid) server_request_id=%s timing_ms=%s", server_request_id, timing_ms)
        return _err(
            502, "UPSTREAM_RESPONSE_INVALID",
            "We couldn't process the response. Please try again.",
            internal_message=e.upstream_body,
            upstream_status=e.status_code,
        )
    except UpstreamResponseTooLongError as e:
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        logger.info("Lookup timing (error: upstream response too long) server_request_id=%s timing_ms=%s", server_request_id, timing_ms)
        return _err(
            502, "UPSTREAM_RESPONSE_TOO_LONG",
            "We couldn't process the response. Please try again.",
            internal_message=e.upstream_body,
            upstream_status=e.status_code,
        )
    except UpstreamClientError as e:
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        logger.info("Lookup timing (error: upstream client error) server_request_id=%s timing_ms=%s", server_request_id, timing_ms)
        return _err(
            503, "UPSTREAM_CLIENT_ERROR",
            "Service is temporarily unavailable. Please try again later.",
            internal_message=e.upstream_body,
            upstream_status=e.status_code,
        )
    except UpstreamError as e:
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        logger.info("Lookup timing (error: upstream error) server_request_id=%s timing_ms=%s", server_request_id, timing_ms)
        return _err(
            503, "UPSTREAM_ERROR",
            "Service is temporarily unavailable. Please try again later.",
            internal_message=e.upstream_body,
            upstream_status=e.status_code,
        )
    except httpx.TimeoutException as e:
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        logger.info("Lookup timing (error: httpx timeout) server_request_id=%s timing_ms=%s", server_request_id, timing_ms)
        return _err(
            503, "UPSTREAM_TIMEOUT",
            "Service is taking too long. Please try again.",
            internal_message=str(e),
        )
    except httpx.ConnectError as e:
        timing_ms["total"] = (time.perf_counter() - t_start) * 1000
        logger.info("Lookup timing (error: httpx connect) server_request_id=%s timing_ms=%s", server_request_id, timing_ms)
        req_url = getattr(e.request, "url", None)
        cause = str(e.__cause__) if e.__cause__ else ""
        return _err(
            503, "UPSTREAM_CONNECT_ERROR",
            "Could not reach the AI service. Please check your connection and try again.",
            internal_message=str(e),
        )

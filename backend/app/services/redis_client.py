"""Upstash Redis client for usage, cache, and in-flight dedupe."""

import json
import random
import time
from datetime import datetime, timezone
from upstash_redis import Redis

from app.config import Settings


def get_redis(settings: Settings) -> Redis:
    return Redis(
        url=settings.upstash_redis_rest_url,
        token=settings.upstash_redis_rest_token,
        allow_telemetry=False,
    )


def _utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# Usage limits: 50/day per install_id, 200/day per hashed_ip
DAILY_LIMIT_INSTALL = 50
DAILY_LIMIT_IP = 200
BURST_LIMIT_INSTALL = 10
BURST_LIMIT_IP = 60
BURST_WINDOW_SEC = 10
CACHE_TTL_SEC = 86400  # 24 hours
INFLIGHT_TTL_SEC = 120
USAGE_KEY_TTL_SEC = 172800  # 48 hours for cleanup


def check_usage(redis: Redis, install_id: str, hashed_ip: str) -> tuple[bool, str | None]:
    """
    Check if usage is within daily limits. Returns (ok, error_code).
    Call before making AI Builder Space request.
    """
    date = _utc_date()
    install_key = f"usage:install:{install_id}:{date}"
    ip_key = f"usage:ip:{hashed_ip}:{date}"

    install_val = redis.get(install_key)
    ip_val = redis.get(ip_key)
    install_count = int(install_val) if install_val else 0
    ip_count = int(ip_val) if ip_val else 0

    if install_count >= DAILY_LIMIT_INSTALL or ip_count >= DAILY_LIMIT_IP:
        return False, "EXCEED_LIMITS"
    return True, None


def incr_usage(redis: Redis, install_id: str, hashed_ip: str) -> None:
    """Increment usage counters. Call after successful AI Builder Space response."""
    date = _utc_date()
    install_key = f"usage:install:{install_id}:{date}"
    ip_key = f"usage:ip:{hashed_ip}:{date}"

    install_count = redis.incr(install_key)
    if install_count == 1:
        redis.expire(install_key, USAGE_KEY_TTL_SEC)

    ip_count = redis.incr(ip_key)
    if ip_count == 1:
        redis.expire(ip_key, USAGE_KEY_TTL_SEC)


def check_burst(redis: Redis, install_id: str, hashed_ip: str) -> tuple[bool, str | None]:
    """
    Check burst limits. Returns (ok, error_code).
    Call before incr_usage. Uses sliding window via INCR + EXPIRE.
    """
    burst_install_key = f"burst:install:{install_id}"
    burst_ip_key = f"burst:ip:{hashed_ip}"

    install_count = redis.incr(burst_install_key)
    if install_count == 1:
        redis.expire(burst_install_key, BURST_WINDOW_SEC)

    ip_count = redis.incr(burst_ip_key)
    if ip_count == 1:
        redis.expire(burst_ip_key, BURST_WINDOW_SEC)

    if install_count > BURST_LIMIT_INSTALL or ip_count > BURST_LIMIT_IP:
        return False, "TOO_MANY_REQUESTS"
    return True, None


def get_cache(redis: Redis, fingerprint: str) -> dict | None:
    """Get cached response if present."""
    key = f"cache:{fingerprint}"
    val = redis.get(key)
    if val is None:
        return None
    return json.loads(val) if isinstance(val, str) else val


def set_cache(redis: Redis, fingerprint: str, response_payload: dict) -> None:
    """Store response in cache with 24h TTL."""
    from datetime import datetime, timezone
    key = f"cache:{fingerprint}"
    value = json.dumps({
        "response_payload": response_payload,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    })
    redis.set(key, value, ex=CACHE_TTL_SEC)


def acquire_inflight(redis: Redis, fingerprint: str, server_request_id: str) -> bool:
    """
    Try to acquire in-flight lock. Returns True if acquired, False if already held.
    """
    key = f"inflight:{fingerprint}"
    return redis.set(key, server_request_id, nx=True, ex=INFLIGHT_TTL_SEC)


def release_inflight(redis: Redis, fingerprint: str) -> None:
    """
    Release in-flight lock. Call when request is cancelled (e.g. client disconnect)
    so another request for the same fingerprint can proceed immediately.
    """
    key = f"inflight:{fingerprint}"
    redis.delete(key)


def poll_cache_for_inflight(redis: Redis, fingerprint: str, max_wait_sec: float = 3.0) -> dict | None:
    """
    When in-flight lock is held, poll cache at 200-300ms intervals for up to max_wait_sec.
    Returns cached response if found, else None.
    """
    start = time.monotonic()
    while (time.monotonic() - start) < max_wait_sec:
        cached = get_cache(redis, fingerprint)
        if cached is not None:
            return cached.get("response_payload")
        time.sleep(random.uniform(0.2, 0.3))
    return None

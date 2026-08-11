"""Analytics writes for lookup requests."""

import logging
from datetime import datetime, timezone, timedelta

from upstash_redis import Redis

logger = logging.getLogger(__name__)

_EXPIRE_AFTER_DAYS = 15


def _expiry_ts(date_str: str) -> int:
    """
    Return the Unix timestamp (seconds) for midnight UTC exactly
    _EXPIRE_AFTER_DAYS calendar days after the given YYYY-MM-DD date.
    """
    key_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    expiry = key_date + timedelta(days=_EXPIRE_AFTER_DAYS)
    return int(expiry.timestamp())


def record_success(redis: Redis, install_id: str, date_str: str) -> None:
    """
    Record one successful lookup for install_id on date_str.
    Intended to be called as a FastAPI BackgroundTask.
    All exceptions are caught and logged; failures are never propagated.
    """
    try:
        expiry = _expiry_ts(date_str)
        dau_key = f"analytics:dau:{date_str}"
        success_key = f"analytics:success:{date_str}"

        redis.sadd(dau_key, install_id)
        redis.expireat(dau_key, expiry)

        redis.incr(success_key)
        redis.expireat(success_key, expiry)
    except Exception:
        logger.exception(
            "Analytics write failed (success) date=%s install_id=%s",
            date_str,
            install_id,
        )


def record_failure(redis: Redis, install_id: str, date_str: str) -> None:
    """
    Record one failed lookup for install_id on date_str.
    Intended to be called as a FastAPI BackgroundTask.
    All exceptions are caught and logged; failures are never propagated.
    """
    try:
        expiry = _expiry_ts(date_str)
        dau_key = f"analytics:dau:{date_str}"
        fail_key = f"analytics:fail:{date_str}"

        redis.sadd(dau_key, install_id)
        redis.expireat(dau_key, expiry)

        redis.incr(fail_key)
        redis.expireat(fail_key, expiry)
    except Exception:
        logger.exception(
            "Analytics write failed (failure) date=%s install_id=%s",
            date_str,
            install_id,
        )

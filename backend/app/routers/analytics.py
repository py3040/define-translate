"""Admin analytics router for recording and retrieving daily active users and lookup success/failure counts."""

import hmac
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from app.config import Settings
from app.services.redis_client import get_redis

logger = logging.getLogger(__name__)

_MAX_DAYS = 14

router = APIRouter()


def require_admin(
    x_admin_key: Annotated[str | None, Header()] = None,
) -> None:
    key = Settings().admin_key
    server_request_id = str(uuid.uuid4())

    if not key:
        http_status, error_code, error_message = (
            503,
            "ADMIN_NOT_CONFIGURED",
            "Admin endpoint is not available.",
        )
        logger.error(
            "admin_auth_failure",
            extra={
                "server_request_id": server_request_id,
                "auth_reason": "not_configured",
                "http_status": http_status,
                "error_code": error_code,
                "error_message": error_message,
            },
        )
        raise HTTPException(
            status_code=http_status,
            detail={
                "error_code": error_code,
                "error_message": error_message,
                "server_request_id": server_request_id,
            },
        )
    if not x_admin_key or not hmac.compare_digest(x_admin_key, key):
        http_status, error_code, error_message = (
            401,
            "UNAUTHORIZED_ADMIN_KEY",
            "Unauthorized.",
        )
        logger.warning(
            "admin_auth_failure",
            extra={
                "server_request_id": server_request_id,
                "auth_reason": "missing_key" if not x_admin_key else "invalid_key",
                "http_status": http_status,
                "error_code": error_code,
                "error_message": error_message,
            },
        )
        raise HTTPException(
            status_code=http_status,
            detail={
                "error_code": error_code,
                "error_message": error_message,
                "server_request_id": server_request_id,
            },
        )


@router.get("/admin/analytics", dependencies=[Depends(require_admin)])
async def get_analytics(
    days: Annotated[int, Query(ge=1, le=_MAX_DAYS, description="Number of UTC dates to include, ending today.")] = 7,
) -> JSONResponse:
    settings = Settings()
    redis = get_redis(settings)

    today = datetime.now(timezone.utc).date()
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]

    daily = []
    period_dau_union: set[str] = set()
    period_success = 0
    period_fail = 0

    try:
        for date_str in dates:
            dau_key = f"analytics:dau:{date_str}"
            success_key = f"analytics:success:{date_str}"
            fail_key = f"analytics:fail:{date_str}"

            dau_members: set[str] = redis.smembers(dau_key) or set()
            raw_success = redis.get(success_key)
            raw_fail = redis.get(fail_key)

            success_count = int(raw_success) if raw_success is not None else 0
            fail_count = int(raw_fail) if raw_fail is not None else 0

            period_dau_union.update(dau_members)
            period_success += success_count
            period_fail += fail_count

            daily.append({
                "date": date_str,
                "dau": len(dau_members),
                "success_count": success_count,
                "fail_count": fail_count,
                "total_lookups": success_count + fail_count,
            })
    except Exception:
        logger.exception("Analytics query failed")
        return JSONResponse(status_code=503, content={"error": "Analytics unavailable"})

    return JSONResponse({
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period": {
            "from": dates[-1],
            "to": dates[0],
            "days": days,
        },
        "summary": {
            "active_users": len(period_dau_union),
            "success_count": period_success,
            "fail_count": period_fail,
            "total_lookups": period_success + period_fail,
        },
        "daily": daily,
    })

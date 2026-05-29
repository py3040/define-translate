"""Admin analytics endpoint.

GET /api/admin/analytics?days=N

Returns DAU, active-user count, and daily success/failure counts for the
last N UTC dates (today inclusive), where N defaults to 7 and is capped at
14 (the maximum number of days for which data may still be present given the
15-calendar-day Redis TTL).  The period-level active-user count and lookup
totals are computed at query time by aggregating the N daily Redis keys; they
are not stored separately.

Missing keys (no lookups that day, or key already expired) are treated
as zero per TR-1.06-06.
"""

import hmac
import logging
from datetime import datetime, timezone, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from app.config import Settings
from app.services.redis_client import get_redis

logger = logging.getLogger(__name__)

_MAX_DAYS = 14

router = APIRouter()


def require_admin(x_admin_key: Annotated[str | None, Header()] = None) -> None:
    """Guard the admin endpoint with a static key compared in constant time.

    Fails closed: if ADMIN_KEY is not configured, the endpoint is locked (503)
    rather than left publicly readable.
    """
    key = Settings().admin_key
    if not key:
        raise HTTPException(status_code=503, detail="Admin endpoint not configured")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, key):
        raise HTTPException(status_code=401, detail="Unauthorized")


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

"""Temporary IP diagnostic endpoint.

Purpose: discover how the deployment platform (AI Builder Space / Koyeb edge)
forwards the client IP to this FastAPI app, so the rate limiter in
``lookup.get_client_ip`` can be configured to use a value that is both
correct (real user IP) and not client-spoofable.

This router is DISABLED unless the ``IP_DEBUG_TOKEN`` environment variable is
set. Requests must pass that token as ``?token=...``. Remove this router (and
the setting) once the IP behaviour has been confirmed.
"""

import hmac

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.routers.lookup import get_client_ip

router = APIRouter()

# Headers a reverse proxy / CDN might use to convey the originating client IP.
# We surface all of them so we can see exactly which ones the platform sets.
_IP_HEADER_CANDIDATES = [
    "x-forwarded-for",
    "x-real-ip",
    "forwarded",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-forwarded-port",
    "x-client-ip",
    "cf-connecting-ip",
    "true-client-ip",
    "fastly-client-ip",
    "fly-client-ip",
    "x-cluster-client-ip",
]


@router.get("/_debug/ip")
async def debug_ip(request: Request, token: str = "") -> JSONResponse:
    settings = Settings()

    # Disabled unless a token is configured server-side.
    if not settings.ip_debug_token:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    # Constant-time compare so this can't be used as a timing oracle.
    if not hmac.compare_digest(token, settings.ip_debug_token):
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})

    headers_lower = {k.lower(): v for k, v in request.headers.items()}

    xff_raw = headers_lower.get("x-forwarded-for")
    xff_chain = [p.strip() for p in xff_raw.split(",")] if xff_raw else []

    # The TCP peer as seen by the app. Behind a proxy this is the proxy, not
    # the real user.
    peer_host = request.client.host if request.client else None
    peer_port = request.client.port if request.client else None

    return JSONResponse(
        {
            # The immediate connection (proxy when deployed behind an edge LB).
            "tcp_peer": {"host": peer_host, "port": peer_port},
            # What the CURRENT rate limiter would key on for this request.
            # Compare this against the real source IP you sent from.
            "current_limiter_ip": get_client_ip(request),
            # Forwarding headers, parsed.
            "x_forwarded_for_raw": xff_raw,
            "x_forwarded_for_chain": xff_chain,
            "x_forwarded_for_count": len(xff_chain),
            # Convenience: the right-most XFF entry is the one appended by the
            # closest trusted proxy and is the spoof-resistant candidate.
            "x_forwarded_for_leftmost": xff_chain[0] if xff_chain else None,
            "x_forwarded_for_rightmost": xff_chain[-1] if xff_chain else None,
            # All forwarding-related headers the platform actually sent.
            "forwarding_headers": {
                name: headers_lower.get(name)
                for name in _IP_HEADER_CANDIDATES
                if name in headers_lower
            },
            # Any vendor/platform-specific headers (helps spot Koyeb markers).
            "platform_headers": {
                k: v
                for k, v in headers_lower.items()
                if k.startswith(("koyeb", "x-koyeb", "x-amzn", "via", "x-request-id"))
            },
            # Full header dump for completeness (authorization redacted).
            "all_headers": {
                k: ("<redacted>" if k in ("authorization", "cookie") else v)
                for k, v in headers_lower.items()
            },
        }
    )

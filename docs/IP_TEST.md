# Client IP behaviour test (AI Builder Space / Koyeb)

## Why

The rate limiter (`lookup.get_client_ip` → `hash_client_ip` → `check_burst` /
`check_usage`) keys on the client IP. AI Builder Space runs your container on
**Koyeb behind an edge load balancer**, so:

- `request.client.host` is the **proxy**, not the user.
- The real user IP arrives in a forwarding header (expected: `X-Forwarded-For`).
- The current code trusts the **left-most** `X-Forwarded-For` entry, which is
  the position a client can **spoof**. If that's what reaches the limiter on the
  real platform, per-IP limits can be bypassed.

This test confirms, on the live deployment, exactly what your app sees so you
can fix `get_client_ip` correctly before relying on it.

## What was added (temporary, remove after)

- `app/routers/debug.py` — `GET /api/_debug/ip`, disabled unless the
  `IP_DEBUG_TOKEN` env var is set; requires `?token=<IP_DEBUG_TOKEN>`.
- `app/config.py` — `ip_debug_token` setting.
- `scripts/ip_probe.py` — runs a clean request + a spoofing request and prints a
  verdict.

Safety: with no `IP_DEBUG_TOKEN` set the endpoint returns 404. Wrong/missing
token returns 403 (constant-time compare). `authorization`/`cookie` headers are
redacted in the dump.

## How to run

1. Deploy with the diagnostic enabled by adding to your `POST /v1/deployments`
   `env_vars` (use a long random value):

   ```json
   { "env_vars": { "IP_DEBUG_TOKEN": "<long-random-string>" } }
   ```

2. From **each** network you care about (home wifi, phone hotspot/cellular, a
   VPN exit), first note that network's real public IP:

   ```bash
   curl https://api.ipify.org
   ```

   then run the probe:

   ```bash
   python scripts/ip_probe.py \
     --base-url https://<service>.ai-builders.space \
     --token <IP_DEBUG_TOKEN>
   ```

   (Local sanity check: `python scripts/ip_probe.py --base-url http://127.0.0.1:8000 --token devsecret`
   after starting uvicorn with `IP_DEBUG_TOKEN=devsecret`.)

## How to read the results

For the **clean** request:

- Find which field equals the public IP from `api.ipify.org`. That is the field
  carrying the real user IP on this platform.
- Note the `x_forwarded_for_chain` length and which position (left-most vs
  right-most) holds your real IP. On a single-proxy setup the real IP is usually
  the **right-most** entry the platform appended; left-most is client-supplied.
- `tcp_peer.host` is the Koyeb proxy IP — never use it for rate limiting.

For the **spoofed** request (script injects `X-Forwarded-For: 203.0.113.99`):

- If `current_limiter_ip (spoofed)` becomes `203.0.113.99`, the limiter is
  **spoofable today** — a client can forge the key. Fix required.
- If the platform strips/overrides the injected header, the spoof won't take
  effect; still verify the clean value matches your real IP.

## Turning results into the fix

Once you know the trustworthy field/position, change `get_client_ip` to use it
instead of the blind left-most value. Typical correct pattern behind exactly one
trusted proxy:

```python
def get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # right-most = appended by the trusted proxy = not client-spoofable
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "0.0.0.0"
```

Adjust the index to match what the test shows for Koyeb (e.g. if Koyeb adds N
hops, take the entry N from the right). Re-run the probe to confirm the spoof no
longer changes `current_limiter_ip`.

## Cleanup

After you've confirmed the behaviour and fixed `get_client_ip`:

1. Remove the `IP_DEBUG_TOKEN` env var from the deployment (this alone disables
   the endpoint → 404).
2. Optionally delete `app/routers/debug.py`, its include in `app/main.py`, the
   `ip_debug_token` setting, and `scripts/ip_probe.py`.

#!/usr/bin/env python3
"""Redeploy / status helper for the AI Builder Space deployment.

Secrets are read at runtime from ``backend/.env`` (which is gitignored), so this
script contains no secrets and is safe to commit.

Usage:
    python deploy.py            # trigger a deployment (POST /v1/deployments)
    python deploy.py status     # show deployment status + probe /health
    python deploy.py logs       # fetch build logs
    python deploy.py logs runtime   # fetch runtime logs

Notes:
    - Pushing to GitHub does NOT auto-redeploy; run `python deploy.py` after a push.
    - AI_BUILDER_TOKEN is injected by the platform at runtime and is intentionally
      NOT sent in env_vars.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# --- Deployment parameters (non-secret) -------------------------------------
REPO_URL = "https://github.com/py3040/define-translate"
SERVICE_NAME = "define-translate"
BRANCH = "main"
PORT = 8000
PUBLIC_URL = f"https://{SERVICE_NAME}.ai-builders.space"

# Env var KEYS to forward to the container. Values come from backend/.env.
# AI_BUILDER_TOKEN is deliberately excluded (the platform injects it).
ENV_VAR_KEYS = [
    "AI_BUILDER_BASE_URL",
    "UPSTASH_REDIS_REST_URL",
    "UPSTASH_REDIS_REST_TOKEN",
    "HMAC_SECRET",
    "FINGERPRINT_SECRET",
    "ADMIN_KEY",
]

ENV_PATH = Path(__file__).resolve().parent / "backend" / ".env"


def load_env(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"ERROR: {path} not found. Copy backend/.env.example to backend/.env first.")
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k] = v
    return out


def request(method: str, url: str, token: str, body: dict | None = None, timeout: float = 180.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"raw": e.read().decode()[:2000] if e.fp else str(e)}


def print_safe(data: dict):
    for k in ("status", "state", "message", "service_name", "public_url"):
        if k in data:
            print(f"{k}: {json.dumps(data[k])[:1500]}")


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "deploy"
    env = load_env(ENV_PATH)
    token = env["AI_BUILDER_TOKEN"]
    base = env.get("AI_BUILDER_BASE_URL", "https://space.ai-builders.com/backend").rstrip("/")

    if action == "deploy":
        env_vars = {k: env[k] for k in ENV_VAR_KEYS if env.get(k)}
        print("Forwarding env var KEYS (values hidden):", sorted(env_vars))
        payload = {
            "repo_url": REPO_URL,
            "service_name": SERVICE_NAME,
            "branch": BRANCH,
            "port": PORT,
            "env_vars": env_vars,
            "streaming_log_timeout_seconds": 120,
        }
        status, data = request("POST", f"{base}/v1/deployments", token, payload)
        print("HTTP", status)
        print_safe(data)
        logs = data.get("streaming_logs")
        if logs:
            text = logs if isinstance(logs, str) else json.dumps(logs)
            print("--- streaming_logs (tail) ---")
            print(text[-3000:])

    elif action == "status":
        status, data = request("GET", f"{base}/v1/deployments/{SERVICE_NAME}", token, timeout=60)
        print("HTTP", status)
        print_safe(data)
        try:
            hs, hd = request("GET", f"{PUBLIC_URL}/health", token, timeout=30)
            print(f"HEALTH {hs}: {json.dumps(hd)}")
        except Exception as e:
            print("HEALTH probe error:", type(e).__name__, str(e)[:200])

    elif action == "logs":
        log_type = sys.argv[2] if len(sys.argv) > 2 else "build"
        url = f"{base}/v1/deployments/{SERVICE_NAME}/logs?log_type={log_type}"
        if log_type == "runtime":
            url += "&timeout=300"
        http_timeout = 320 if log_type == "runtime" else 90
        status, data = request("GET", url, token, timeout=http_timeout)
        print("HTTP", status)
        print(json.dumps(data, indent=2)[:6000])

    else:
        sys.exit(f"Unknown action: {action!r}. Use: deploy | status | logs")


if __name__ == "__main__":
    main()

# Define & Translate

Look up the **contextual meaning** and **translation** of any word or phrase on a
web page — without leaving the page. Select text, and an in-page panel returns a
definition that accounts for the surrounding context, plus a translation into your
chosen language.

The project has two parts: a **Chrome extension** (Manifest V3) for the in-page UI
and a **FastAPI backend** that talks to the AI Builder Space API, with rate
limiting, caching, and abuse protection.

## Features

- **Context-aware definitions** — uses the sentence around the selection, not just the word.
- **On-demand translation** into 14 languages (see `extension/shared/constants.js`).
- **In-page panel** — no popups or new tabs; works on any `https://` site.
- **Abuse & cost controls** — per-install and per-IP daily/burst limits via Redis.
- **Response caching** — identical lookups are served from cache (24h TTL).
- **Privacy-conscious** — client IPs are HMAC-hashed; no raw IPs or secrets are logged.

## Tech stack

| Layer      | Technology                                              |
| ---------- | ------------------------------------------------------- |
| Extension  | Chrome Manifest V3, vanilla JS, content + service worker |
| Backend    | Python, FastAPI, Uvicorn, Pydantic                      |
| Data/cache | Upstash Redis (REST)                                    |
| AI         | AI Builder Space API                                    |
| Hosting    | Docker → Koyeb via `ai-builders.space`                  |

## Repository structure

```
Code/
├── extension/            # Chrome extension (Manifest V3)
│   ├── manifest.json
│   ├── background/       # service worker (proxies API calls)
│   ├── content/          # in-page UI (content script + CSS)
│   └── shared/           # shared constants (incl. API base URL)
├── backend/              # FastAPI server
│   ├── app/
│   │   ├── main.py       # app entrypoint, middleware, error handlers
│   │   ├── routers/      # lookup, analytics, debug
│   │   └── services/     # redis, hashing, normalization, AI client
│   ├── requirements.txt
│   └── .env.example      # template for required env vars (no secrets)
├── docs/                 # architecture, secrets, deployment, verification
├── Dockerfile            # builds the backend for deployment
└── deploy.py             # helper to (re)deploy and check status
```

## Getting started

### Prerequisites

- Python 3.11+
- An Upstash Redis database (REST URL + token)
- An AI Builder Space token
- Google Chrome (or any Chromium browser)

### 1. Backend

```bash
cd Code/backend
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux:        source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then fill in the values (see Configuration below)
python -m uvicorn app.main:app --reload
```

Your **local** dev server is now at `http://localhost:8000` (health check at
`/health`). This is only for local development.

### 2. Extension

1. Open `chrome://extensions/`
2. Enable **Developer mode**
3. **Load unpacked** → select `Code/extension`
4. Select text on any `https://` page to use it.

By default the extension talks to the **deployed** backend. To point it at your
local server, run this in the extension's service-worker console:

```js
chrome.storage.local.set({ api_base_url: "http://localhost:8000" })
```

## Configuration

Backend configuration is read from environment variables (`backend/.env` locally;
injected at deploy time in production). See [`docs/SECRETS.md`](docs/SECRETS.md) and
[`backend/.env.example`](backend/.env.example). **Never commit `.env` or real secrets.**

| Variable                   | Required | Purpose                                          |
| -------------------------- | -------- | ------------------------------------------------ |
| `AI_BUILDER_BASE_URL`      | yes      | AI Builder Space API base URL                    |
| `AI_BUILDER_TOKEN`         | yes      | Bearer token (auto-injected by the platform)     |
| `UPSTASH_REDIS_REST_URL`   | yes      | Upstash Redis REST URL                           |
| `UPSTASH_REDIS_REST_TOKEN` | yes      | Upstash Redis REST token                         |
| `HMAC_SECRET`              | yes      | Secret for hashing client IPs                    |
| `FINGERPRINT_SECRET`       | yes      | Secret for request fingerprinting (cache keys)   |
| `ADMIN_KEY`                | no       | Unlocks `GET /api/admin/analytics`               |
| `IP_DEBUG_TOKEN`           | no       | Enables `GET /api/_debug/ip` diagnostics         |

## API

| Method | Endpoint                | Description                                      |
| ------ | ----------------------- | ----------------------------------------------- |
| `POST` | `/api/lookup`           | Context-aware definition and/or translation     |
| `GET`  | `/health`               | Health check                                    |
| `GET`  | `/api/admin/analytics`  | Usage analytics (requires `X-Admin-Key` header) |
| `GET`  | `/api/_debug/ip`        | IP-forwarding diagnostics (requires `?token=`)  |

## Deployment

The backend is containerized (`Dockerfile`) and deployed to the
`ai-builders.space` platform. After pushing changes to `main`, redeploy with:

```bash
cd Code
python deploy.py            # trigger a redeploy
python deploy.py status     # check status + health
python deploy.py logs       # build logs (use `logs runtime` for runtime)
```

> Pushing to GitHub does **not** auto-redeploy — you must run `python deploy.py`.

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the full guide.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system overview
- [docs/SECRETS.md](docs/SECRETS.md) — managing tokens and keys
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — deployment guide
- [docs/VERIFICATION.md](docs/VERIFICATION.md) — verification steps

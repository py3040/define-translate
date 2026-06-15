# Define & Translate

Look up the **contextual meaning** and **contextual translation** of any word, phrase, or sentence(s) (up to 300 chars) on a web page — without leaving the page. Select text, and an in-page panel returns a definition and a translation (if chosen) that accounts for the surrounding context.

The project has two parts: a **Chrome extension** (Manifest V3) for the in-page UI
and a **FastAPI backend** that talks to the AI Builder Space API, with rate
limiting, caching, and abuse protection.

## Features

- **Context-aware definitions** — uses the surrounding sentence for context, with up to 300 chars included.
- **Context-aware translation** into 14 languages (see `extension/shared/constants.js`).
- **In-page panel** — less distraction.
- **Abuse & cost controls** — per-install and per-IP daily/burst limits.
- **Response caching** — identical lookups are served from cache (24h TTL).
- **Privacy-conscious** — client IPs are HMAC-hashed; no raw IPs are logged. Works on `https://` sites only (excluding payment or login pages)

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
│   └── shared/           # shared constants
├── backend/              # FastAPI server
│   ├── app/
│   │   ├── main.py       # app entrypoint, middleware, error handlers
│   │   ├── routers/      # lookup, analytics
│   │   └── services/     # redis, hashing, normalization, AI client
│   ├── requirements.txt
│   └── .env.example      # template for required env vars
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

### Local deployment

1. Deploy FastAPI locally
2. Load unpacked to Chrome extension
3. Select text on any `https://` page to use it (except payment or login page)

## Configuration

Backend configuration is read from environment variables (`backend/.env` locally;
injected at deploy time in production). See [`backend/.env.example`](backend/.env.example). **Never commit `.env` or real secrets.**


## API

| Method | Endpoint                | Description                                      |
| ------ | ----------------------- | ----------------------------------------------- |
| `POST` | `/api/lookup`           | Context-aware definition and/or translation     |
| `GET`  | `/health`               | Health check                                    |
| `GET`  | `/api/admin/analytics`  | Usage analytics (requires `X-Admin-Key` header) |

## Deployment

The backend is containerized (`Dockerfile`) and deployed to the
`ai-builders.space` platform. After pushing changes to `main`on GitHub, redeploy with:

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
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — deployment guide
- [docs/VERIFICATION.md](docs/VERIFICATION.md) — verification steps

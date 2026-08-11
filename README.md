# Define & Translate

Look up the **contextual meaning** and **contextual translation** of any word, phrase, or sentence(s) (up to 300 chars) on a web page — without leaving the page. Select text, and an in-page panel returns a definition and a translation that accounts for the surrounding context.

## Features

- **Context-aware definitions** — uses the surrounding sentence for context, with up to 300 chars included.
- **Context-aware translation** — into 14 languages.
- **In-page panel** — less distraction.
- **Abuse & cost controls** — per-install and per-IP daily/burst limits.
- **Response caching** — identical lookups are served from cache (24h TTL).
- **Privacy-conscious** — client IPs are HMAC-hashed; no raw IPs are logged. Works on `https://` sites only (excluding payment or login pages)

## Tech stack

| Layer      | Technology                                              |
| ---------- | ------------------------------------------------------- |
| Extension  | Chrome Manifest V3, vanilla JS, content + service worker|
| Backend    | Python, FastAPI, Uvicorn, Pydantic                      |
| Data/cache | Upstash Redis (REST)                                    |
| AI         | AI Builder Space API                                    |
| Hosting    | Docker → Koyeb via `ai-builders.space`                  |

## Repository structure

```
├── extension/            # Chrome extension (Manifest V3)
│   ├── manifest.json
│   ├── background/       # service worker (proxies API calls)
│   ├── content/          # in-page UI (content script + CSS)
│   ├── onboarding/       # first-run consent page
│   └── shared/           # shared constants
├── backend/              # FastAPI server
│   ├── app/
│   │   ├── main.py       # app entrypoint, middleware, error handlers
│   │   ├── models/       # request/response schemas
│   │   ├── routers/      # lookup, analytics
│   │   └── services/     # redis, hashing, normalization, AI client
│   ├── requirements.txt
│   ├── README.md         # local backend setup
│   └── .env.example      # template for required env vars
├── docs/                 # architecture
└── Dockerfile            # builds the backend for deployment
```

## Getting started

### Prerequisites

- Python 3.11+
- An Upstash Redis database (REST URL + token)
- An AI Builder Space token
- Google Chrome (or any Chromium browser)

### Local deployment

1. Deploy FastAPI locally — see [`backend/README.md`](backend/README.md)
2. Load unpacked to Chrome extension
3. Select text on any `https://` page to use it (except payment or login page)

## Configuration

Backend configuration is read from environment variables (`backend/.env` locally;
injected at deploy time in production). See [`backend/.env.example`](backend/.env.example). **Never commit** `.env` **or real secrets.**

## API

| Method | Endpoint               | Auth         | Description                                 |
| ------ | ---------------------- | ------------ | ------------------------------------------- |
| `POST` | `/api/lookup`          | Key required | Context-aware definition and translation |
| `GET`  | `/health`              | None         | Health check                                |
| `GET`  | `/api/admin/analytics` | Key required | Usage analytics                             |

## Deployment

The backend is containerized (`Dockerfile`) and deployed to the `ai-builders.space` platform, which provides its own deployment guide. Pushing to `main` on GitHub does **not** trigger a deployment — you must redeploy manually after pushing backend changes.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system overview

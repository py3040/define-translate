# Secrets Management

**Never commit tokens, API keys, or secrets to version control.**

## Required Variables

| Variable | Description | Where Used |
|----------|-------------|------------|
| `AI_BUILDER_TOKEN` | Bearer token for AI Builder Space | Backend |
| `UPSTASH_REDIS_REST_URL` | Upstash Redis REST URL | Backend |
| `UPSTASH_REDIS_REST_TOKEN` | Upstash Redis REST token | Backend |
| `HMAC_SECRET` | Secret for IP hashing (abuse control) | Backend |
| `FINGERPRINT_SECRET` | Secret for request fingerprinting (cache) | Backend |

## Setup

1. Copy `.env.example` to `.env` in the backend directory
2. Fill in values from your environment
3. Ensure `.env` is in `.gitignore` (it is by default)

## Backend Configuration

The FastAPI app reads from environment variables via `pydantic-settings`. No secrets should appear in code or logs.

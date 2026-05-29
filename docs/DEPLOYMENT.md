# Deployment Guide

The backend is containerized with the root [`Dockerfile`](../Dockerfile) and
deployed to the **AI Builder Space** platform (Koyeb under the hood). The live
service is at **https://define-translate.ai-builders.space**.

## How it works

The platform clones the **public** GitHub repo, builds the image from the
`Dockerfile`, and runs it as a single process on the `PORT` it injects at
runtime. Secrets are **not** committed — they are passed as runtime environment
variables at deploy time (the `deploy.py` helper reads them from `backend/.env`).
`AI_BUILDER_TOKEN` is injected automatically by the platform, so it is never sent.

## Prerequisites

- The repo is public: https://github.com/py3040/define-translate
- `backend/.env` exists locally and is filled in (see [SECRETS.md](SECRETS.md)).
  It is gitignored and must never be committed.
- Python 3.11+ available locally (the `deploy.py` helper uses only the standard library).

## Deploy / redeploy

> Pushing to GitHub does **not** auto-redeploy. After pushing, you must trigger
> a deploy explicitly.

1. Commit and push your changes:

   ```bash
   cd Code
   git add -A
   git commit -m "your message"
   git push origin main
   ```

2. Trigger the deployment:

   ```bash
   cd Code
   python deploy.py
   ```

   `deploy.py` reads the secret values from `backend/.env`, forwards them as
   `env_vars`, and calls `POST /v1/deployments`. Provisioning takes ~5–10 minutes.

3. Check status and the live health endpoint:

   ```bash
   python deploy.py status
   ```

4. If a build fails, inspect logs:

   ```bash
   python deploy.py logs          # build logs
   python deploy.py logs runtime  # runtime logs
   ```

## Environment variables

Set these in `backend/.env`; `deploy.py` forwards all but `AI_BUILDER_TOKEN`
(which the platform injects). See [SECRETS.md](SECRETS.md) for details.

| Variable                   | Forwarded by `deploy.py` | Notes                                    |
| -------------------------- | ------------------------ | ---------------------------------------- |
| `AI_BUILDER_BASE_URL`      | yes                      | API base URL                             |
| `AI_BUILDER_TOKEN`         | no (auto-injected)       | Provided by the platform at runtime      |
| `UPSTASH_REDIS_REST_URL`   | yes                      | Upstash Redis REST URL                   |
| `UPSTASH_REDIS_REST_TOKEN` | yes                      | Upstash Redis REST token                 |
| `HMAC_SECRET`              | yes                      | IP hashing                               |
| `FINGERPRINT_SECRET`       | yes                      | Cache-key fingerprinting                 |
| `ADMIN_KEY`                | yes (if set)             | Unlocks `GET /api/admin/analytics`       |
| `IP_DEBUG_TOKEN`           | yes (if set)             | Enables `GET /api/_debug/ip`             |

## Platform constraints

- **Public repo only** — private repositories cannot be deployed.
- **Single process / single port** — the app must honor the `PORT` env var
  (the `Dockerfile` uses `sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"`).
- **256 MB RAM** (nano container) — keep dependencies lean.
- **Free hosting** for 12 months from the first successful deployment. Contact
  your instructor to delete a service or extend hosting.

## Extension → backend

The extension defaults to the deployed backend (set in
`extension/shared/constants.js`). To point it at a local server during
development, run this in the extension's service-worker console:

```js
chrome.storage.local.set({ api_base_url: "http://localhost:8000" })
```

## Extension packaging

1. Update `manifest.json` `version` for releases.
2. Package/zip the `extension/` directory.
3. Load unpacked for development (`chrome://extensions/` → Developer mode →
   Load unpacked), or submit to the Chrome Web Store for distribution.

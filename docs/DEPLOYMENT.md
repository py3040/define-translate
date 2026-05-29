# Deployment Guide

## Backend (FastAPI)

1. Set all environment variables (see SECRETS.md)
2. Deploy to a platform that supports Python (e.g., Railway, Render, Fly.io)
3. Ensure HTTPS is enabled
4. Configure trusted proxy headers if behind a load balancer (for IP source)

## Extension

1. Build/package the extension from `Code/extension/`
2. Update `manifest.json` version for releases
3. Submit to Chrome Web Store (or distribute unpacked for dev)

## Extension → Backend

Configure the FastAPI base URL in the extension. For development, use a local URL or ngrok. For production, use your deployed backend URL.

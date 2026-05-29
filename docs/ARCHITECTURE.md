# Define & Translate - Architecture

## Overview

The extension allows users to select text on HTTPS pages and view AI-generated contextual meaning and translation in a floating panel. The FastAPI backend validates requests, enforces limits, and calls AI Builder Space.

## Components

```
Extension (Content Script) → FastAPI → AI Builder Space
                    ↓
              Upstash Redis (usage, cache, in-flight)
```

## Data Flow

1. User selects text → Define button appears (if supported)
2. User clicks Define → Panel opens, request sent to FastAPI
3. FastAPI validates, checks usage, cache, in-flight dedupe
4. On cache miss: call AI Builder Space, cache response
5. Extension displays meaning/translation

## Security

- All secrets in environment variables
- IP hashing (HMAC-SHA256) for abuse control
- HTTPS only, no raw IP storage

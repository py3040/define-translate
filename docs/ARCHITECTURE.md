# Define & Translate - Architecture

## Overview

The extension allows users to select text on HTTPS pages (excluding login and payment pages) and view AI-generated contextual meaning and translation in a floating panel. The FastAPI backend validates requests, enforces limits, and calls AI Builder Space. Upstash Redis stores usage counters, cache, in-flight locks and simple analytics.

## Components

```
Extension → FastAPI → AI Builder Space
                ↓
          Upstash Redis
```

## Sequence of events

1. User selects text → Define button appears (if supported)
2. User clicks Define → Panel opens, request sent to FastAPI
3. FastAPI validates request, checks cache, usage, and in-flight dedupe
4. On cache miss: FastAPI calls AI Builder Space
5. FastAPI validates AI response, increases usage, caches response and records analytics
5. Extension displays meaning/translation



# Define & Translate - Verification Guide

## Prerequisites

- Python 3.10+ (for backend tests)
- Chrome browser (for extension)

## Backend

### Run tests

```bash
cd Code/backend
python -m pip install -r requirements.txt
python -m pytest tests/ -v
```

### Manual API test

1. Set up `.env` with real credentials (AI_BUILDER_TOKEN, Upstash Redis, etc.)
2. Run: `uvicorn app.main:app --reload`
3. Test health: `curl http://localhost:8000/health`
4. Test lookup (requires valid credentials):

```bash
curl -X POST http://localhost:8000/api/lookup \
  -H "Content-Type: application/json" \
  -d '{
    "client_request_id": "550e8400-e29b-41d4-a716-446655440000",
    "install_id": "550e8400-e29b-41d4-a716-446655440001",
    "selected_text": "hello world",
    "full_context": "hello world",
    "target_language": "es",
    "mode": "meaning_and_translation",
    "page_url": "https://example.com",
    "extension_version": "1.0.0"
  }'
```

## Extension

### Load extension

1. Open `chrome://extensions/`
2. Enable Developer mode
3. Load unpacked → select `Code/extension`

### Flow: Panel NOT activated

1. Go to an HTTPS page (e.g. https://example.com)
2. Select text (not in an input/textarea)
3. Define button should appear above or below selection
4. Click elsewhere → button hides
5. Select again, click Define → panel opens, loading spinner shows
6. Result: meaning + language dropdown
7. Select language → translation appears
8. Select new text → panel refreshes with new lookup
9. Click Close → panel closes

### Flow: Panel activated

1. With panel open, select new text on the page
2. Panel refreshes with new lookup
3. Select text in an editable field → nothing happens
4. Select text > 300 chars → "Please keep selection within 300 characters"

### Error paths

- Non-HTTPS page: Define button does not appear
- URL with "login" or "payment": Define button does not appear (manifest exclude)
- Close panel before result loads: request is aborted
- Select new text while loading: previous request is aborted

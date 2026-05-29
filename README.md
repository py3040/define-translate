# Define & Translate

Chrome extension for contextual meaning and translation lookup without leaving the current webpage.

## Structure

- **extension/** - Chrome extension (Manifest V3)
- **backend/** - FastAPI server
- **docs/** - Documentation

## Quick Start

### Backend

```bash
cd Code/backend
pip install -r requirements.txt
# Copy .env.example to .env and fill in secrets
uvicorn app.main:app --reload
```

### Extension

1. Open `chrome://extensions/`
2. Enable Developer mode
3. Load unpacked → select `Code/extension`

## Documentation

- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - System overview
- [SECRETS.md](docs/SECRETS.md) - How to manage tokens/keys
- [DEPLOYMENT.md](docs/DEPLOYMENT.md) - Deployment guide

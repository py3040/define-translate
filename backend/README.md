# Define & Translate Backend Local Setup

Local FastAPI backend for the Define & Translate Chrome extension.

## Setup

```bash
# Create and activate virtual environment (recommended)
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# Windows CMD
# .\.venv\Scripts\activate.bat

# macOS/Linux
# source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and edit environment file
cp .env.example .env
# Edit .env with your secrets
```

## Run

```bash
# With venv activated
python -m uvicorn app.main:app --reload
```

## API

- `POST /api/lookup` - Lookup contextual meaning and/or translation
- `GET /health` - Health check

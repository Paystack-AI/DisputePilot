# Backend

Placeholder FastAPI app (`GET /health`). Replace with real work once the team agrees on the API
design.

## Setup

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv\Scripts\Activate.ps1 in PowerShell
pip install -r requirements-dev.txt
cp .env.example .env
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

## Checks (same ones CI and pre-commit run)

```bash
ruff check .
ruff format --check .
pytest -q
pip-audit -r requirements.txt
```

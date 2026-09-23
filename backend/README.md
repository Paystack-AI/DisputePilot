# Backend

Placeholder FastAPI app (`GET /health`). Replace with real work once the team agrees on the API
design.

## Setup

Uses [uv](https://docs.astral.sh/uv/) for dependency management — no separate venv activation step,
`uv run` handles that for you.

```bash
cd backend
uv sync --extra dev
cp .env.example .env
```

## Run

```bash
uv run uvicorn app.main:app --reload --port 8000
```

## Checks (same ones CI and pre-commit run)

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run pip-audit
```

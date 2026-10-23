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
# Persistent AI memory

AI context is persisted in the `ai_memories` table and scoped by both `tenant_id` and
`merchant_id`, with optional `dispute_id` scope. In the current product each merchant account
is its own tenant; the database check constraint requires those identifiers to match until an
organization model is introduced. Evidence revisions and TrustLayer snapshots are the authoritative source
records; memory entries retain source ids, hashes, timestamps, and deletion/correction history.
PostgreSQL row-level security is forced for memory and access-audit tables, with a transaction-local
tenant context set only from authenticated/server-side scope.
Only a configurable number of relevant entries (`AI_MEMORY_CONTEXT_LIMIT`, default 20) is sent
to a model. Historical AI output is context only and cannot override current dispute facts or
the deterministic TrustLayer policy. Merchants can correct or soft-delete memory through the
authenticated `/api/v1/ai/memory/{memory_id}/correction` and `/api/v1/ai/memory/{memory_id}`
endpoints.

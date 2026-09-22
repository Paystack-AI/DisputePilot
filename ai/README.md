# AI

Placeholder Python package. Replace with real work once the team agrees on the AI stack and scope.

## Setup

```bash
cd ai
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv\Scripts\Activate.ps1 in PowerShell
pip install -r requirements-dev.txt
cp .env.example .env
```

## Checks (same ones CI and pre-commit run)

```bash
ruff check .
ruff format --check .
pytest -q
pip-audit -r requirements.txt
```

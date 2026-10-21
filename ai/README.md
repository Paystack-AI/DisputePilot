# AI

The AI worker. It reads jobs the backend adds to a Redis stream (`ai:stream:requests`), runs them, and adds results to `ai:stream:results` for the backend. Both sides use the same message fields: `event`, `job_id`, `version`, `payload` (JSON) and `created_at`.

- `src/streams.py`: `AiRequestConsumer` (consumer group with acks, replay of unacked jobs, retries, and a `:dead` dead-letter stream) and `AiResultPublisher`.
- `src/handlers/`: one handler per job event and `build_handlers()`, the event -> handler map. Each handler validates the payload, calls the LLM client, publishes its `ai:result:*`, and publishes `ai:error` on failure.
- `src/llm/`: the ordered provider chain (Gemini primary, Groq fallback), per-attempt timeouts, failover rules, the strict-JSON retry, and Redis-backed provider cooldowns.
- `src/schemas/`: request, result and validated LLM-output models for every job.
- `src/prompts/`: the system prompts and `load_prompt()`.

## Providers

Set `GEMINI_API_KEY` and/or `GROQ_API_KEY`; a provider with an empty key is skipped. `LLM_PROVIDER_ORDER` sets the chain (default `gemini,groq`: Gemini first, Groq on retryable failures or rate limits). Both providers are called over their REST APIs through `httpx`, so no provider SDK is needed.

The default model ids target the free tiers (`gemini-3.8-flash` and `openai/gpt-oss-120b`). Moving to a paid plan or a different model is only an env change: set the `GEMINI_MODEL_*` / `GROQ_MODEL_*` values and restart the worker. See `.env.example` for the full list.

## Contract with the backend

| Job (backend -> ai) | Prompt | Result (ai -> backend) | Backend handler |
|---|---|---|---|
| `ai:dispute:classify` | `classifier.txt` | `ai:result:classified` | `dispute_ai.on_classified` |
| `ai:dispute:generate-evidence` | `evidence.txt` | `ai:result:evidence-generated` | `dispute_ai.on_generated` |
| `ai:dispute:score-quality` | `scorer.txt` | `ai:result:quality-scored` | `dispute_ai.on_scored` |
| `ai:trust:explain` | `trust_explainer.txt` | `ai:result:trust-explained` | `trust_ai.on_trust_explained` |
| `ai:trust:recommend` | `trust_recommender.txt` | `ai:result:trust-explained` | `trust_ai.on_trust_explained` |
| `ai:trust:state-change` | `trust_state_change.txt` | `ai:result:state-change-summarized` | `trust_ai.on_state_change_summarized` |

Any failure is published as `ai:error`; the backend falls back to its templates for disputes. Amounts in job payloads are in the currency's minor unit (kobo). `tests/test_contract.py` holds payloads shaped exactly as the backend sends them: change both sides together.

## Run the worker

```bash
python -m src.worker
```

It needs Redis (`REDIS_URL`). Ctrl+C stops it cleanly; unacked jobs are replayed on the next start.

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

# AI

The AI worker. It reads jobs the backend adds to a Redis stream (`ai:stream:requests`), runs them, and adds results to `ai:stream:results` for the backend. Both sides use the same message fields: `event`, `job_id`, `version`, `payload` (JSON) and `created_at`.

- `src/streams.py`: `AiRequestConsumer` (consumer group with acks, replay of unacked jobs, retries, and a `:dead` dead-letter stream), `AiResultPublisher`, and `REQUEST_HANDLERS`, the map from job event (e.g. `ai:dispute:classify`) to its handler.
- `src/worker.py`: runs the consumer loop.

A handler does the work and publishes its result with the job's `job_id`:

```python
async def classify(message: StreamMessage):
    result = ...  # call the model with message.payload
    await publisher.publish("ai:result:classified", message.job_id, result)

REQUEST_HANDLERS["ai:dispute:classify"] = classify
```

Jobs with no handler go to the dead-letter stream (`ai:stream:requests:dead`) instead of being retried forever.

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

import asyncio
from contextlib import asynccontextmanager

import sentry_sdk
import sentry_sdk.logger as sentry_logger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.clients.minio import create_minio_storage
from app.api.clients.paystack import create_async_http_client
from app.api.routers import router
from app.api.services import trust_ai  # noqa: F401  registers the trust ai handlers
from app.api.services.ai_streams import AI_RESULT_HANDLERS, AiResultConsumer, stop_task
from app.api.services.dispute_ai import run_timeout_sweeps  # registers the ai handlers
from app.core.config import get_settings
from app.core.exception_handlers import ExceptionHandler
from app.core.exceptions import StorageUpstreamError
from app.core.security import Security
from app.database.session import redis_client
from app.middleware import RequestIDMiddleware

SECURITY = Security()
SETTINGS = get_settings()

# before the app is created so the sdk can instrument it; empty dsn disables sentry
if SETTINGS.SENTRY_SDK_DSN:
    sentry_sdk.init(
        dsn=SETTINGS.SENTRY_SDK_DSN,
        environment=SETTINGS.ENVIRONMENT,
        enable_logs=True,
        send_default_pii=False,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        profile_lifecycle="trace",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await SECURITY.register_oauth()

    app.state.limiters = {}
    app.state.redis = redis_client
    app.state.paystack_http = create_async_http_client()
    # one client for the whole app; the sdk pools connections and is thread-safe
    app.state.minio = create_minio_storage()

    # off in tests, where the lifespan runs for every test and no storage is running
    if SETTINGS.MINIO_ENSURE_BUCKET_ON_STARTUP:
        try:
            await app.state.minio.ensure_bucket(SETTINGS.MINIO_BUCKET)
        except StorageUpstreamError:
            # storage being down (or not configured yet) should not stop the api from
            # starting; uploads fail with 502 until it is reachable, the next start retries
            sentry_logger.error(
                "Bucket {bucket} could not be ensured", bucket=SETTINGS.MINIO_BUCKET
            )

    # one loop reading ai results (ai -> backend); jobs for the ai are added on demand
    ai_result_task: asyncio.Task | None = None
    # evidence steps with no result in time fall back to the templates
    evidence_sweep_task: asyncio.Task | None = None
    if SETTINGS.AI_RESULT_CONSUMER_ENABLED:
        consumer = AiResultConsumer(app.state.redis, AI_RESULT_HANDLERS)
        ai_result_task = asyncio.create_task(consumer.run(), name="ai-result-consumer")
        evidence_sweep_task = asyncio.create_task(
            run_timeout_sweeps(), name="evidence-timeout-sweep"
        )

    yield

    await stop_task(ai_result_task)
    await stop_task(evidence_sweep_task)
    await app.state.paystack_http.aclose()
    await app.state.redis.aclose()


app = FastAPI(
    title=SETTINGS.API_TITLE,
    description=SETTINGS.API_DESCRIPTION,
    version=SETTINGS.API_VERSION,
    lifespan=lifespan,
)


app.include_router(router.router)

app.add_middleware(RequestIDMiddleware)

# signed cookie holding the oauth state between the redirect to google and the callback;
# only used by the google sign in flow, tokens are never put in it
app.add_middleware(
    SessionMiddleware,
    max_age=600,
    same_site="lax",
    secret_key=SETTINGS.SESSION_SECRET_KEY,
    https_only=SETTINGS.ENVIRONMENT == "production",
)

# added last so it runs first: preflights are answered before anything else sees them
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip() for origin in SETTINGS.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()
    ],
    # the access token cookie on direct GET /events calls
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
    expose_headers=["Retry-After", "X-Request-ID"],
)

app_exception_handler = ExceptionHandler(app)
app_exception_handler.include_handlers()
app_exception_handler.override_validation_handler()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

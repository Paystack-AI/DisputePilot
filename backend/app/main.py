import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.clients.paystack import create_async_http_client
from app.api.routers import router
from app.api.services.ai_streams import AI_RESULT_HANDLERS, AiResultConsumer, stop_task
from app.core.config import get_settings
from app.core.exception_handlers import ExceptionHandler
from app.core.security import Security
from app.database.session import redis_client
from app.middleware import RequestIDMiddleware

SECURITY = Security()
SETTINGS = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await SECURITY.register_oauth()

    app.state.limiters = {}
    app.state.redis = redis_client
    app.state.paystack_http = create_async_http_client()

    # one loop reading ai results (ai -> backend); jobs for the ai are added on demand
    ai_result_task: asyncio.Task | None = None
    if SETTINGS.AI_RESULT_CONSUMER_ENABLED:
        consumer = AiResultConsumer(app.state.redis, AI_RESULT_HANDLERS)
        ai_result_task = asyncio.create_task(consumer.run(), name="ai-result-consumer")

    yield

    await stop_task(ai_result_task)
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

app_exception_handler = ExceptionHandler(app)
app_exception_handler.include_handlers()
app_exception_handler.override_validation_handler()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.exception_handlers import ExceptionHandler
from app.database.session import redis_client
from app.middleware import RequestIDMiddleware

SETTINGS = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.limiters = {}
    app.state.redis = redis_client

    yield

    await app.state.redis.aclose()


app = FastAPI(
    title=SETTINGS.API_TITLE,
    description=SETTINGS.API_DESCRIPTION,
    version=SETTINGS.API_VERSION,
    lifespan=lifespan,
)


app.add_middleware(RequestIDMiddleware)

app_exception_handler = ExceptionHandler(app)
app_exception_handler.include_handlers()
app_exception_handler.override_validation_handler()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

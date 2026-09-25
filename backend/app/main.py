from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.exception_handlers import ExceptionHandler
from app.database.session import redis_client
from app.middleware import RequestIDMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.limiters = {}
    app.state.redis = redis_client

    yield

    await app.state.redis.aclose()


app = FastAPI(title="Backend", lifespan=lifespan)


app.add_middleware(RequestIDMiddleware)

app_exception_handler = ExceptionHandler(app)
app_exception_handler.include_handlers()
app_exception_handler.override_validation_handler()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

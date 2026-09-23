from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_encoding="utf-8", extra="allow", case_sensitive=False
    )

    # environment
    ENVIRONMENT: str = "development"

    # api details
    API_PREFIX: str = "/api/v1"
    API_TITLE: str = "DisputePilot"
    API_VERSION: str = "v1.0"
    API_DESCRIPTION: str = ""

    # async db
    ASYNC_DB_URL: str

    # sync db
    SYNC_DB_URL: str

    # test db
    ASYNC_TEST_DB_URL: str

    # redis
    REDIS_URL: str

    # rabbitmq
    BROKER_URL: str


@lru_cache(maxsize=1)
def get_settings():
    return Settings()

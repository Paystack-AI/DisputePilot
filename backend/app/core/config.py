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

    # resend email
    API_EMAIL: str  # sender address, on a domain verified in resend
    RESEND_API_KEY: str

    # rate limit keys
    READ_LIMIT_KEY: str = "limiter:read"
    WRITE_LIMIT_KEY: str = "limiter:write"

    # paystack
    ENCRYPTION_KEY: str
    PAYSTACK_BASE_URL: str = "https://api.paystack.co"
    PAYSTACK_TIMEOUT: float = 15.0  # seconds

    # JWT
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_TIME: int
    REFRESH_TOKEN_EXPIRE_TIME: int
    ACCESS_TOKEN_SECRET_KEY: str
    REFRESH_TOKEN_SECRET_KEY: str

    # otp
    OTP_EXPIRE_TIME: int = 15  # minutes
    OTP_MAX_ATTEMPTS: int = 5
    OTP_SECRET_KEY: str  # hmac key, codes are never stored in plain text

    # frontend, where oauth sign in redirects back to
    FRONTEND_URL: str = "http://localhost:3000"

    # signs the session cookie that carries the oauth state between redirects
    SESSION_SECRET_KEY: str

    # google oauth
    # set when the api runs behind a proxy, otherwise built from the request url
    GOOGLE_REDIRECT_URI: str | None = None
    GOOGLE_CLIENT_ID: str
    GOOGLE_OAUTH_URL: str = "https://accounts.google.com/.well-known/openid-configuration"
    GOOGLE_CLIENT_SECRET: str

    # Argon2
    ARGON2_PASSWORD_PEPPER: str

    # Minio
    MINIO_ENDPOINT: str
    MINIO_SECRET_KEY: str
    MINIO_ACCESS_KEY: str
    # https; true when minio sits behind tls (production), false for local docker
    MINIO_SECURE: bool = False
    # must match the region the minio server is configured with (MINIO_SITE_REGION)
    MINIO_REGION: str = "eu-west-1"
    MINIO_BUCKET: str = "disputepilot"


@lru_cache(maxsize=1)
def get_settings():
    return Settings()

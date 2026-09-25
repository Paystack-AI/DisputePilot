import base64
import json
from binascii import Error as binascii_error
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from authlib.integrations.starlette_client import OAuth
from cryptography.fernet import Fernet
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey
from pwdlib.hashers.argon2 import Argon2Hasher

from app.api.schemas.auth import TokenData
from app.core.config import get_settings


class Security:
    SETTINGS = get_settings()
    # exp is always set when issuing, so a token without one is rejected.
    CLAIMS_REGISTRY = jwt.JWTClaimsRegistry(exp={"essential": True})

    def __init__(self):
        self.oauth: OAuth = OAuth()
        self.arg2_hasher = Argon2Hasher()

    def _encode_jwt(self, payload: dict, key: str) -> str:
        return jwt.encode(
            {"alg": self.SETTINGS.JWT_ALGORITHM},
            payload,
            OctKey.import_key(key),
            algorithms=[self.SETTINGS.JWT_ALGORITHM],
        )

    async def register_oauth(self):
        self.oauth.register(
            name="google",
            client_id=self.SETTINGS.GOOGLE_CLIENT_ID,
            client_secret=self.SETTINGS.GOOGLE_CLIENT_SECRET,
            server_metadata_url=self.SETTINGS.GOOGLE_OAUTH_URL,
            client_kwargs={
                "scope": "openid email profile",
            },
        )

    async def encrypt_secret_key(self, secret_key: str) -> str:
        f = Fernet(self.SETTINGS.ENCRYPTION_KEY.encode())
        return f.encrypt(secret_key.encode()).decode()

    async def decrypt_secret_key(self, encrypted_key: str) -> str:
        f = Fernet(self.SETTINGS.ENCRYPTION_KEY.encode())
        return f.decrypt(encrypted_key.encode()).decode()

    async def encode_cursor(self, payload: dict) -> str:
        payload_string: str = json.dumps(payload)
        return base64.b64encode(payload_string.encode()).decode()

    async def decode_cursor(self, cursor_string: str, curr_order: str) -> dict:
        try:
            if not cursor_string:
                return

            cursor_string = base64.b64decode(cursor_string)
            cursor_payload = json.loads(cursor_string)

            if cursor_payload["order"] != curr_order.lower():
                return
            return cursor_payload
        except (json.JSONDecodeError, UnicodeDecodeError, binascii_error):
            return

    async def hash_password(self, password: str) -> str:
        password: str = password + self.SETTINGS.ARGON2_PASSWORD_PEPPER
        return self.arg2_hasher.hash(password)

    async def verify_password(self, password: str, hash_password: str) -> bool:
        password: str = password + self.SETTINGS.ARGON2_PASSWORD_PEPPER
        return self.arg2_hasher.verify(password, hash_password)

    async def create_access_token(
        self, token_data: TokenData, expire_time: int | None = None
    ) -> str:
        if not expire_time:
            expire_time: datetime = datetime.now(UTC) + timedelta(
                minutes=self.SETTINGS.ACCESS_TOKEN_EXPIRE_TIME
            )
        else:
            expire_time: datetime = datetime.now(UTC) + timedelta(minutes=expire_time)

        payload: dict = {
            "sub": token_data.email,
            "exp": expire_time,
            "iat": datetime.now(UTC),
            "usertype": token_data.user_type,
        }

        return self._encode_jwt(payload, self.SETTINGS.ACCESS_TOKEN_SECRET_KEY)

    async def create_refresh_token(
        self, token_data: TokenData, expire_time: int | None = None
    ) -> tuple:
        if not expire_time:
            expire_time: datetime = datetime.now(UTC) + timedelta(
                days=self.SETTINGS.REFRESH_TOKEN_EXPIRE_TIME
            )
        else:
            expire_time: datetime = datetime.now(UTC) + timedelta(days=expire_time)

        payload: dict = {
            "sub": token_data.email,
            "exp": expire_time,
            "iat": datetime.now(UTC),
            "jti": str(uuid4()),
            "usertype": token_data.user_type,
        }

        token: str = self._encode_jwt(payload, self.SETTINGS.REFRESH_TOKEN_SECRET_KEY)

        return token, payload["jti"], payload["usertype"]

    async def decode_token(self, token: str, key: str):
        try:
            if token is None:
                return

            decoded = jwt.decode(
                token,
                OctKey.import_key(key),
                algorithms=[self.SETTINGS.JWT_ALGORITHM],
            )
            self.CLAIMS_REGISTRY.validate(decoded.claims)
            return decoded.claims
        except JoseError:
            return

    async def prepare_tokens(self, token_data: TokenData):
        access_token: str = await self.create_access_token(token_data)
        refresh_token, refresh_token_id, user_type = await self.create_refresh_token(token_data)

        refresh_token_expire_time: int = get_settings().REFRESH_TOKEN_EXPIRE_TIME * 24 * 3600

        refresh_token_payload: dict = {
            "email": token_data.email,
            "user_type": user_type,
            "refresh_token_id": refresh_token_id,
            "refresh_token": refresh_token,
            "refresh_token_expire_time": refresh_token_expire_time,
        }

        return access_token, refresh_token_payload

from fastapi import Depends

from app.core.config import get_settings
from app.limiter import _limiter_handler

SETTINGS = get_settings()


# ------------------------ Limiter -------------------------------- #
write_limiter = Depends(
    _limiter_handler(key=SETTINGS.WRITE_LIMIT_KEY, limit=10, unit="minutes", multiplier=15)
)

read_limiter = Depends(
    _limiter_handler(key=SETTINGS.READ_LIMIT_KEY, limit=10, unit="minutes", multiplier=1)
)

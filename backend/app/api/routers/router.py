from fastapi import APIRouter

from app.api.routers import auth, onboarding, paystack, settings
from app.core.config import get_settings

SETTINGS = get_settings()

router = APIRouter(prefix=SETTINGS.API_PREFIX)
router.include_router(auth.router, tags=["Auth"])
router.include_router(paystack.router, tags=["Paystack"])
router.include_router(onboarding.router, tags=["Onboarding"])
router.include_router(settings.router, tags=["Settings"])

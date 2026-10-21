"""TrustLayer for the merchant (profile, settings, signals, history) and the public page
and badge. Everything here reads the stored profile; the worker computes it."""

from datetime import UTC, datetime, timedelta

import sentry_sdk
import sentry_sdk.logger as sentry_logger

from app.api.models.enums import TrustState
from app.api.models.merchant_settings import MerchantSettings
from app.api.models.merchants import Merchant
from app.api.models.trust_profiles import TrustProfile
from app.api.models.trust_snapshots import TrustSnapshot
from app.api.repo.trust import TrustRepository
from app.api.repo.uow import UnitOfWorkRepository
from app.api.schemas.trust import (
    PublicTrustBadge,
    PublicTrustPage,
    TrustAction,
    TrustActions,
    TrustHistory,
    TrustHistoryPoint,
    TrustProfileResponse,
    TrustSample,
    TrustSettingsUpdate,
    TrustSignal,
    TrustSignalsBreakdown,
    TrustStateChange,
)
from app.api.services.trust_policy import (
    BUILDING,
    NEW_BELOW_DAYS,
    NEW_BELOW_PAYMENTS,
    RECONCILIATION_DAYS,
    VERIFIED,
    reading,
)
from app.api.services.trust_triggers import request_trust_update
from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ServerError

SETTINGS = get_settings()

LABELS: dict[TrustState, str] = {
    TrustState.VERIFIED: "Verified",
    TrustState.BUILDING: "Building",
    TrustState.NEW: "New",
    TrustState.REVIEW: "Review",
}
MEANINGS: dict[TrustState, str] = {
    TrustState.VERIFIED: "Strong, verified operational practices.",
    TrustState.BUILDING: "Establishing operational practices.",
    TrustState.NEW: "Not enough activity yet to assess.",
    TrustState.REVIEW: "Operational practices need improvement.",
}
NEXT_STATE: dict[TrustState, TrustState | None] = {
    TrustState.REVIEW: TrustState.BUILDING,
    TrustState.BUILDING: TrustState.VERIFIED,
    TrustState.NEW: TrustState.BUILDING,
    TrustState.VERIFIED: None,
}
# the public page and badge never show review (project path 19.2)
PUBLIC_STATES: tuple[TrustState, ...] = (TrustState.VERIFIED, TrustState.BUILDING, TrustState.NEW)
PUBLIC_CACHE_SECONDS: int = 300

# key -> label, profile column, what to do when it is not strong
SIGNALS: tuple[tuple[str, str, str, str], ...] = (
    (
        "reconciliation_rate",
        "Reconciliation",
        "reconciliation_rate",
        "Match more of your Paystack payments to orders.",
    ),
    (
        "fulfillment_rate",
        "Fulfillment",
        "fulfillment_rate",
        "Log fulfillment with a photo, tracking number or recipient for paid orders.",
    ),
    (
        "dispute_rate",
        "Dispute rate",
        "dispute_rate",
        "Fewer disputes follow clear descriptions and proof of delivery.",
    ),
    (
        "dispute_win_rate",
        "Disputes won",
        "dispute_win_rate",
        "Respond to disputes with evidence before the deadline.",
    ),
    (
        "avg_response_time",
        "Response time",
        "avg_response_time_pct",
        "Respond to disputes earlier in the response window.",
    ),
    (
        "evidence_readiness",
        "Evidence readiness",
        "evidence_readiness_avg",
        "Attach delivery photos and tracking to matched orders.",
    ),
)


def _threshold(key: str, policy: dict[str, float]) -> str | None:
    if key not in policy:
        return None
    word: str = "at most" if key == "dispute_rate" else "at least"
    return f"{word} {policy[key]:g}%"


def signals_of(profile: TrustProfile) -> list[TrustSignal]:
    signals: list[TrustSignal] = []
    for key, label, column, action in SIGNALS:
        value: float | None = getattr(profile, column)
        signal_reading: str = reading(key, value)
        signals.append(
            TrustSignal(
                key=key,
                label=label,
                value=round(value, 1) if value is not None else None,
                reading=signal_reading,
                verified_threshold=_threshold(key, VERIFIED),
                building_threshold=_threshold(key, BUILDING),
                action=None if signal_reading == "strong" else action,
            )
        )
    return signals


def sample_of(profile: TrustProfile) -> TrustSample | None:
    if profile.payments_30d is None or profile.days_on_platform is None:
        return None
    return TrustSample(
        payments_30d=profile.payments_30d,
        days_on_platform=profile.days_on_platform,
        min_sample_met=(
            profile.payments_30d >= NEW_BELOW_PAYMENTS
            and profile.days_on_platform >= NEW_BELOW_DAYS
        ),
    )


def verification_summary(profile: TrustProfile) -> str:
    """Words, not percentages, for the public page"""
    if profile.current_state == TrustState.NEW:
        return "This merchant is new to TrustLayer; there is not enough activity to assess yet."
    phrases: dict[str, dict[str, str]] = {
        "reconciliation_rate": {
            "strong": "reconciles nearly all of its Paystack payments",
            "fair": "reconciles most of its Paystack payments",
        },
        "fulfillment_rate": {
            "strong": "fulfills nearly all orders with verifiable evidence",
            "fair": "fulfills many orders with verifiable evidence",
        },
    }
    parts: list[str] = []
    for key, column in (
        ("reconciliation_rate", "reconciliation_rate"),
        ("fulfillment_rate", "fulfillment_rate"),
    ):
        phrase = phrases[key].get(reading(key, getattr(profile, column)))
        if phrase:
            parts.append(phrase)
    if not parts:
        return "This merchant's operations are being verified from its Paystack activity."
    return f"This merchant {' and '.join(parts)}."


class TrustService:
    def _setup(self, uow: UnitOfWorkRepository):
        self._uow = uow
        self._repo = uow.repo(TrustRepository)

    async def _profile(self, merchant: Merchant, create: bool = True):
        """create=False is for readers who must not write (an admin viewing a merchant):
        a merchant with no profile yet is a 404 instead"""
        found = await self._repo.profile_with_settings(merchant.id)
        if found:
            return found
        if not create:
            raise NotFoundError("Trust profile")
        # first visit: an empty profile now, the first computation queued
        await self._repo.ensure_profile(merchant.id)
        await self._uow.commit()
        await request_trust_update(merchant.id, "first_view")
        return await self._repo.profile_with_settings(merchant.id)

    @staticmethod
    def _public_url(profile: TrustProfile) -> str:
        return f"{SETTINGS.FRONTEND_URL.rstrip('/')}/public/trust/{profile.public_token}"

    async def get_profile(
        self, merchant: Merchant, uow: UnitOfWorkRepository, create: bool = True
    ) -> TrustProfileResponse:
        self._setup(uow)
        profile, public_enabled, widget_enabled, stable_since = await self._profile(
            merchant, create
        )
        return TrustProfileResponse(
            state=profile.current_state,
            label=LABELS[profile.current_state],
            meaning=MEANINGS[profile.current_state],
            internal_score=profile.internal_score,
            signals=signals_of(profile),
            sample=sample_of(profile),
            public_enabled=public_enabled,
            widget_enabled=widget_enabled,
            public_url=self._public_url(profile),
            last_computed_at=profile.last_computed_at,
            stable_since=stable_since,
            explanation=profile.explanation,
            explained_at=profile.explained_at,
        )

    async def update_settings(
        self, merchant: Merchant, payload: TrustSettingsUpdate, uow: UnitOfWorkRepository
    ) -> TrustProfileResponse:
        """The public page and badge switches; turning the page off takes effect at once
        (public responses are cached for PUBLIC_CACHE_SECONDS at most)"""
        self._setup(uow)
        settings: MerchantSettings | None = await self._repo.settings_for_update(merchant.id)
        if not settings:
            raise NotFoundError("Settings")
        if payload.public_enabled is not None:
            settings.trust_public_enabled = payload.public_enabled
        if payload.widget_enabled is not None:
            settings.trust_widget_enabled = payload.widget_enabled
        settings.updated_at = datetime.now(UTC)
        try:
            await uow.commit()
        except Exception as exc:
            await uow.rollback()
            sentry_sdk.capture_exception(exc)
            raise ServerError() from exc

        sentry_logger.info(
            "Merchant {merchant_id} set trust public={public} widget={widget}",
            merchant_id=str(merchant.id),
            public=str(settings.trust_public_enabled),
            widget=str(settings.trust_widget_enabled),
        )
        return await self.get_profile(merchant, uow)

    async def signals(
        self, merchant: Merchant, uow: UnitOfWorkRepository, create: bool = True
    ) -> TrustSignalsBreakdown:
        self._setup(uow)
        profile, *_ = await self._profile(merchant, create)
        signals: list[TrustSignal] = signals_of(profile)
        next_state: TrustState | None = NEXT_STATE[profile.current_state]
        target: dict[str, float] = VERIFIED if next_state == TrustState.VERIFIED else BUILDING
        wanted: str = "strong" if next_state == TrustState.VERIFIED else "fair"
        rank: dict[str, int] = {"strong": 2, "fair": 1, "weak": 0, "insufficient": 0}

        blocking: list[str] = []
        if next_state:
            for signal in signals:
                if signal.key not in target:
                    continue
                # no resolved disputes is fine for verified
                if signal.key == "dispute_win_rate" and signal.value is None:
                    continue
                if rank[signal.reading] < rank[wanted]:
                    blocking.append(signal.key)

        return TrustSignalsBreakdown(
            state=profile.current_state,
            next_state=next_state,
            blocking=blocking,
            contributing=[s.key for s in signals if s.reading == "strong"],
            signals=signals,
            sample=sample_of(profile),
        )

    async def history(
        self, merchant: Merchant, days: int, uow: UnitOfWorkRepository
    ) -> TrustHistory:
        self._setup(uow)
        snapshots: list[TrustSnapshot] = await self._repo.snapshots(
            merchant.id, datetime.now(UTC) - timedelta(days=days)
        )
        changes: list[TrustStateChange] = []
        previous: TrustState | None = None
        for snapshot in snapshots:
            if snapshot.state != previous:
                changes.append(
                    TrustStateChange(
                        at=snapshot.created_at,
                        from_state=previous,
                        to_state=snapshot.state,
                        reason=snapshot.reason,
                        summary=snapshot.summary,
                    )
                )
            previous = snapshot.state
        return TrustHistory(
            days=days,
            points=[
                TrustHistoryPoint(
                    at=s.created_at,
                    state=s.state,
                    internal_score=s.internal_score,
                    reason=s.reason,
                    signals=s.signals,
                    summary=s.summary,
                )
                for s in snapshots
            ],
            changes=changes,
        )

    async def actions(
        self, merchant: Merchant, uow: UnitOfWorkRepository, create: bool = True
    ) -> TrustActions:
        """The ai's recommended actions from the last explanation"""
        self._setup(uow)
        profile, *_ = await self._profile(merchant, create)
        return TrustActions(
            actions=[TrustAction.model_validate(item) for item in profile.recommendations or []],
            generated_at=profile.explained_at,
        )

    # ------------------------------ public ------------------------------ #

    async def _public(self, token: str, widget: bool, uow: UnitOfWorkRepository):
        """A disabled page, a review state and an unknown token all look the same: 404"""
        self._setup(uow)
        row = await self._repo.public_profile(token)
        enabled: bool = bool(
            row and (row.trust_widget_enabled if widget else row.trust_public_enabled)
        )
        if not enabled or row.current_state not in PUBLIC_STATES:
            raise NotFoundError("Trust profile")
        return row

    async def public_page(self, token: str, uow: UnitOfWorkRepository) -> PublicTrustPage:
        row = await self._public(token, widget=False, uow=uow)
        profile = TrustProfile(
            current_state=row.current_state,
            reconciliation_rate=row.reconciliation_rate,
            fulfillment_rate=row.fulfillment_rate,
        )
        return PublicTrustPage(
            merchant_name=row.business_name,
            state=row.current_state,
            label=LABELS[row.current_state],
            meaning=MEANINGS[row.current_state],
            verification_summary=verification_summary(profile),
            payments_30d=row.payments_30d or 0,
            window_days=RECONCILIATION_DAYS,
            updated_at=row.last_computed_at,
            stable_since=row.stable_since,
        )

    async def public_badge(self, token: str, uow: UnitOfWorkRepository) -> PublicTrustBadge:
        row = await self._public(token, widget=True, uow=uow)
        return PublicTrustBadge(
            merchant_name=row.business_name,
            state=row.current_state,
            label=LABELS[row.current_state],
            verified_since=row.stable_since if row.current_state == TrustState.VERIFIED else None,
            updated_at=row.last_computed_at,
        )

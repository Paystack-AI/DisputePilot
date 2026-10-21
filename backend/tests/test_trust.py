import itertools
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.api.models.disputes import Dispute
from app.api.models.enums import (
    Currency,
    DisputeStatus,
    FulfillmentType,
    OrderSource,
    OrderStatus,
    ReconciliationStatus,
    TransactionChannel,
    TransactionStatus,
    TrustState,
)
from app.api.models.fulfillments import Fulfillment
from app.api.models.merchants import Merchant
from app.api.models.orders import Order
from app.api.models.transactions import Transaction
from app.api.models.trust_profiles import TrustProfile
from app.api.models.trust_snapshots import TrustSnapshot
from app.api.services.trust_policy import TrustSignals, reading, score_for, state_for
from app.worker.services.trust import recompute_trust_profile
from app.worker.tasks.trust import recompute_trust
from tests.conftest import SIGN_UP_PAYLOAD
from tests.factories import add_transaction, merchant_id
from tests.test_transaction_sync import _merchant

SessionMaker = async_sessionmaker[AsyncSession]
_ids = itertools.count(9_000_000)


def _signals(**fields) -> TrustSignals:
    values: dict = {
        "reconciliation_rate": 90.0,
        "fulfillment_rate": 80.0,
        "dispute_rate": 1.0,
        "dispute_win_rate": None,
        "avg_response_time": None,
        "evidence_readiness": 75.0,
        "payments_30d": 40,
        "days_on_platform": 60,
    }
    values.update(fields)
    return TrustSignals(**values)


class TestPolicy:
    def test_verified(self):
        assert state_for(_signals()) == TrustState.VERIFIED

    def test_new_below_the_minimum_sample(self):
        assert state_for(_signals(payments_30d=9)) == TrustState.NEW
        assert state_for(_signals(days_on_platform=13)) == TrustState.NEW

    def test_verified_needs_30_payments(self):
        assert state_for(_signals(payments_30d=20)) == TrustState.BUILDING

    def test_losing_disputes_blocks_verified(self):
        assert state_for(_signals(dispute_win_rate=50.0)) == TrustState.BUILDING
        assert state_for(_signals(dispute_win_rate=60.0)) == TrustState.VERIFIED

    def test_building(self):
        assert state_for(_signals(reconciliation_rate=60.0, fulfillment_rate=45.0)) == (
            TrustState.BUILDING
        )

    def test_review(self):
        assert state_for(_signals(dispute_rate=6.0)) == TrustState.REVIEW
        assert state_for(_signals(reconciliation_rate=30.0)) == TrustState.REVIEW

    def test_between_building_and_review_is_review(self):
        # 45% reconciliation: not under 40 (review) but not 50 (building) either
        assert state_for(_signals(reconciliation_rate=45.0)) == TrustState.REVIEW

    def test_no_orders_fulfilled_counts_as_zero(self):
        assert state_for(_signals(fulfillment_rate=None)) == TrustState.REVIEW

    def test_score(self):
        assert score_for(_signals()) == round(
            90 * 0.25 + 80 * 0.25 + 80 * 0.20 + 100 * 0.15 + 75 * 0.10 + 100 * 0.05
        )
        worst = _signals(
            reconciliation_rate=0.0,
            fulfillment_rate=0.0,
            dispute_rate=50.0,
            dispute_win_rate=0.0,
            avg_response_time=100.0,
            evidence_readiness=0.0,
        )
        assert score_for(worst) == 0

    def test_readings(self):
        assert reading("reconciliation_rate", 85) == "strong"
        assert reading("reconciliation_rate", 55) == "fair"
        assert reading("reconciliation_rate", 10) == "weak"
        assert reading("dispute_rate", 3) == "fair"
        assert reading("dispute_win_rate", None) == "insufficient"


def _payment(db: Session, merchant: Merchant, order: Order | None = None) -> Transaction:
    paystack_id: int = next(_ids)
    transaction = Transaction(
        merchant_id=merchant.id,
        paystack_transaction_id=paystack_id,
        paystack_reference=f"T{paystack_id}",
        order_id=order.id if order else None,
        amount=5000,
        currency=Currency.NGN,
        channel=TransactionChannel.CARD,
        status=TransactionStatus.SUCCESS,
        reconciliation_status=(
            ReconciliationStatus.AUTO_MATCHED if order else ReconciliationStatus.UNMATCHED
        ),
        paystack_created_at=datetime.now(UTC) - timedelta(days=2),
        paid_at=datetime.now(UTC) - timedelta(days=2),
    )
    db.add(transaction)
    return transaction


def _shop(db: Session, payments: int = 30, matched: int = 30, fulfilled: int = 30) -> Merchant:
    """A merchant 60 days old with payments, some matched to fulfilled orders"""
    merchant: Merchant = _merchant(db)
    merchant.created_at = datetime.now(UTC) - timedelta(days=60)
    for number in range(payments):
        order = None
        if number < matched:
            order = Order(
                merchant_id=merchant.id,
                amount=5000,
                currency=Currency.NGN,
                source=OrderSource.WEBSITE,
                status=OrderStatus.PAID,
                created_at=datetime.now(UTC) - timedelta(days=3),
            )
            db.add(order)
            db.flush()
            if number < fulfilled:
                db.add(
                    Fulfillment(
                        merchant_id=merchant.id,
                        order_id=order.id,
                        type=FulfillmentType.DELIVERY,
                        delivery_date=datetime.now(UTC) - timedelta(days=1),
                        tracking_number=f"GIG-{number}",
                    )
                )
        _payment(db, merchant, order)
    db.commit()
    return merchant


def _snapshots(db: Session, merchant: Merchant) -> list[TrustSnapshot]:
    return list(
        db.scalars(
            select(TrustSnapshot)
            .where(TrustSnapshot.merchant_id == merchant.id)
            .order_by(TrustSnapshot.created_at)
        )
    )


class TestRecompute:
    @pytest.mark.asyncio
    async def test_verified_merchant(self, sync_db: Session):
        merchant: Merchant = _shop(sync_db)

        outcome = recompute_trust_profile(sync_db, merchant.id, "scheduled")

        assert outcome.state == TrustState.VERIFIED
        assert outcome.changed
        profile: TrustProfile = sync_db.scalar(
            select(TrustProfile).where(TrustProfile.merchant_id == merchant.id)
        )
        assert profile.reconciliation_rate == 100
        assert profile.fulfillment_rate == 100
        assert profile.dispute_rate == 0
        assert profile.dispute_win_rate is None
        assert profile.payments_30d == 30
        assert profile.public_token
        (snapshot,) = _snapshots(sync_db, merchant)
        assert (snapshot.state, snapshot.reason) == (TrustState.VERIFIED, "scheduled")
        assert snapshot.signals["payments_30d"] == 30

    @pytest.mark.asyncio
    async def test_snapshot_only_when_something_changes(self, sync_db: Session):
        merchant: Merchant = _shop(sync_db)
        recompute_trust_profile(sync_db, merchant.id, "scheduled")

        unchanged = recompute_trust_profile(sync_db, merchant.id, "scheduled")
        assert not unchanged.changed
        assert len(_snapshots(sync_db, merchant)) == 1

        # a lost dispute moves the score (and the win rate below verified)
        payment = sync_db.scalar(
            select(Transaction).where(Transaction.merchant_id == merchant.id).limit(1)
        )
        sync_db.add(
            Dispute(
                merchant_id=merchant.id,
                transaction_id=payment.id,
                paystack_dispute_id=next(_ids),
                paystack_reference=payment.paystack_reference,
                amount=5000,
                due_at=datetime.now(UTC),
                status=DisputeStatus.LOST,
            )
        )
        sync_db.commit()

        changed = recompute_trust_profile(sync_db, merchant.id, "dispute_resolved")

        assert changed.changed
        assert changed.previous_state == TrustState.VERIFIED
        assert changed.state == TrustState.BUILDING
        snapshots = _snapshots(sync_db, merchant)
        assert [s.reason for s in snapshots] == ["scheduled", "dispute_resolved"]
        assert snapshots[1].signals["dispute_win_rate"] == 0

    @pytest.mark.asyncio
    async def test_unmatched_and_unfulfilled(self, sync_db: Session):
        merchant: Merchant = _shop(sync_db, payments=20, matched=9, fulfilled=2)

        outcome = recompute_trust_profile(sync_db, merchant.id, "scheduled")

        profile: TrustProfile = sync_db.scalar(
            select(TrustProfile).where(TrustProfile.merchant_id == merchant.id)
        )
        assert profile.reconciliation_rate == 45
        assert round(profile.fulfillment_rate, 1) == 22.2
        assert outcome.state == TrustState.REVIEW

    @pytest.mark.asyncio
    async def test_new_merchant(self, sync_db: Session):
        merchant: Merchant = _merchant(sync_db)
        assert recompute_trust_profile(sync_db, merchant.id, "scheduled").state == TrustState.NEW


class TestTask:
    @pytest.mark.asyncio
    async def test_skips_when_a_newer_run_happened(self, sync_db: Session):
        merchant: Merchant = _shop(sync_db, payments=10, matched=10, fulfilled=10)
        with (
            patch("app.worker.tasks.trust.sync_session", lambda: nullcontext(sync_db)),
            patch("app.worker.tasks.trust.publish") as publish,
        ):
            requested: str = datetime.now(UTC).isoformat()
            recompute_trust(str(merchant.id), "fulfillment_logged", requested)
            # a second event of the same burst: the first run already covered it
            recompute_trust(str(merchant.id), "fulfillment_logged", requested)

        assert len(_snapshots(sync_db, merchant)) == 1
        publish.assert_called_once()
        assert publish.call_args.args[1] == "trust.updated"


async def _profile_row(session_maker: SessionMaker, merchant: UUID) -> TrustProfile:
    async with session_maker() as session:
        return await session.scalar(
            select(TrustProfile).where(TrustProfile.merchant_id == merchant)
        )


async def _set_profile(session_maker: SessionMaker, merchant: UUID, **values):
    async with session_maker() as session:
        await session.execute(
            update(TrustProfile).where(TrustProfile.merchant_id == merchant).values(**values)
        )
        await session.commit()


class TestEndpoints:
    @pytest.mark.asyncio
    async def test_first_view_creates_and_queues(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        queued_trust: MagicMock,
    ):
        res: Response = await async_client.get("/trust/profile", headers=auth_headers)

        assert res.status_code == 200, res.text
        data: dict = res.json()["data"]
        assert data["state"] == "new"
        assert data["public_enabled"] is False
        assert "/public/trust/" in data["public_url"]
        assert [s["key"] for s in data["signals"]] == [
            "reconciliation_rate",
            "fulfillment_rate",
            "dispute_rate",
            "dispute_win_rate",
            "avg_response_time",
            "evidence_readiness",
        ]
        queued_trust.assert_called_once()
        assert queued_trust.call_args.kwargs["kwargs"]["reason"] == "first_view"

    @pytest.mark.asyncio
    async def test_signals_breakdown(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        await async_client.get("/trust/profile", headers=auth_headers)
        merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        await _set_profile(
            session_maker,
            merchant,
            current_state=TrustState.BUILDING,
            reconciliation_rate=85.0,
            fulfillment_rate=55.0,
            dispute_rate=1.0,
            payments_30d=40,
            days_on_platform=40,
        )

        data: dict = (await async_client.get("/trust/signals", headers=auth_headers)).json()["data"]

        assert data["next_state"] == "verified"
        # fulfillment (55%) is below verified's 70%
        assert data["blocking"] == ["fulfillment_rate"]
        assert "reconciliation_rate" in data["contributing"]
        fulfillment = next(s for s in data["signals"] if s["key"] == "fulfillment_rate")
        assert (fulfillment["reading"], fulfillment["verified_threshold"]) == (
            "fair",
            "at least 70%",
        )
        assert fulfillment["action"]

    @pytest.mark.asyncio
    async def test_public_page_follows_the_switch(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        profile: dict = (await async_client.get("/trust/profile", headers=auth_headers)).json()[
            "data"
        ]
        token: str = profile["public_url"].rsplit("/", 1)[1]
        merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        await _set_profile(
            session_maker,
            merchant,
            current_state=TrustState.VERIFIED,
            internal_score=88,
            reconciliation_rate=95.0,
            fulfillment_rate=90.0,
            payments_30d=142,
            last_computed_at=datetime.now(UTC),
        )

        # off by default: indistinguishable from an unknown token
        assert (await async_client.get(f"/public/trust/{token}")).status_code == 404
        assert (await async_client.get("/public/trust/nope")).status_code == 404

        res: Response = await async_client.put(
            "/trust/profile/settings", json={"public_enabled": True}, headers=auth_headers
        )
        assert res.json()["data"]["public_enabled"] is True

        res = await async_client.get(f"/public/trust/{token}")
        assert res.status_code == 200
        assert res.headers["cache-control"].startswith("public, max-age=300")
        page: dict = res.json()["data"]
        assert page["merchant_name"] == SIGN_UP_PAYLOAD["business_name"]
        assert page["state"] == "verified"
        assert page["payments_30d"] == 142
        assert "reconciles nearly all" in page["verification_summary"]
        # nothing internal leaks
        assert "88" not in res.text and "95" not in res.text
        assert set(page) == {
            "merchant_name",
            "state",
            "label",
            "meaning",
            "verification_summary",
            "payments_30d",
            "window_days",
            "updated_at",
            "stable_since",
        }

        # the badge has its own switch
        assert (await async_client.get(f"/public/trust/{token}/badge")).status_code == 404
        await async_client.put(
            "/trust/profile/settings", json={"widget_enabled": True}, headers=auth_headers
        )
        badge: dict = (await async_client.get(f"/public/trust/{token}/badge")).json()["data"]
        assert badge["state"] == "verified"

        # review is never public
        await _set_profile(session_maker, merchant, current_state=TrustState.REVIEW)
        assert (await async_client.get(f"/public/trust/{token}")).status_code == 404

    @pytest.mark.asyncio
    async def test_history(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        now: datetime = datetime.now(UTC)
        async with session_maker() as session:
            for days_ago, state, score, reason in (
                (20, TrustState.NEW, 30, "scheduled"),
                (10, TrustState.BUILDING, 60, "fulfillment_logged"),
                (5, TrustState.BUILDING, 64, "reconciliation_completed"),
                (100, TrustState.NEW, 10, "scheduled"),  # outside the window
            ):
                session.add(
                    TrustSnapshot(
                        merchant_id=merchant,
                        state=state,
                        internal_score=score,
                        signals={},
                        reason=reason,
                        created_at=now - timedelta(days=days_ago),
                    )
                )
            await session.commit()

        data: dict = (
            await async_client.get("/trust/history?days=30", headers=auth_headers)
        ).json()["data"]

        assert [p["internal_score"] for p in data["points"]] == [30, 60, 64]
        assert [(c["from_state"], c["to_state"]) for c in data["changes"]] == [
            (None, "new"),
            ("new", "building"),
        ]
        res = await async_client.get("/trust/history?days=45", headers=auth_headers)
        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_matching_queues_a_recompute(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
        session_maker: SessionMaker,
        queued_trust: MagicMock,
    ):
        merchant: UUID = await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])
        order = (
            await async_client.post("/orders", json={"amount": 4500000}, headers=auth_headers)
        ).json()["data"]
        transaction_id: UUID = await add_transaction(session_maker, merchant)
        async with session_maker() as session:
            reference: str = await session.scalar(
                select(Transaction.paystack_reference).where(Transaction.id == transaction_id)
            )
        queued_trust.reset_mock()

        res: Response = await async_client.put(
            f"/transactions/{reference}/match", json={"order_id": order["id"]}, headers=auth_headers
        )

        assert res.status_code == 200
        kwargs: dict = queued_trust.call_args.kwargs
        assert kwargs["kwargs"]["reason"] == "reconciliation_updated"
        assert kwargs["countdown"] == 5

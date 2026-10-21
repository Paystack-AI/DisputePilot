from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.models.enums import (
    DisputeStatus,
    ReconciliationSessionStatus,
    ReconciliationStatus,
    TrustState,
)
from app.api.models.orders import Order
from app.api.models.reconciliation_sessions import ReconciliationSession
from app.api.models.trust_snapshots import TrustSnapshot
from app.api.repo.dashboard import DashboardRepository
from tests.conftest import SIGN_UP_PAYLOAD
from tests.factories import add_fulfillment, add_transaction, merchant_id
from tests.test_disputes import _dispute

SessionMaker = async_sessionmaker[AsyncSession]


async def _merchant(session_maker: SessionMaker) -> UUID:
    return await merchant_id(session_maker, SIGN_UP_PAYLOAD["email"])


async def _order(async_client: AsyncClient, headers: dict, **fields) -> dict:
    res: Response = await async_client.post(
        "/orders", json={"amount": 4500000, **fields}, headers=headers
    )
    assert res.status_code == 201, res.text
    return res.json()["data"]


class TestDashboard:
    @pytest.mark.asyncio
    async def test_empty_merchant(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await async_client.get("/dashboard", headers=auth_headers)

        assert res.status_code == 200, res.text
        data: dict = res.json()["data"]
        metrics: dict = data["metrics"]
        assert metrics["transactions"] == {"count": 0, "successful": 0, "delta_pct": None}
        assert metrics["disputes"] == {"open": 0, "critical": 0, "opened": 0, "resolved": 0}
        assert metrics["readiness"]["score"] is None
        assert metrics["reconciliation"]["matched_pct"] is None
        assert data["critical_dispute"] is None
        assert data["trust"] is None  # no profile computed yet
        assert data["prompts"] == [] and data["recent_transactions"] == []
        assert data["activity"] == []
        # the last 7 days against the 7 before them
        period: dict = data["period"]
        assert period["date_from"] < period["date_to"]
        assert period["previous_to"] < period["date_from"]

    @pytest.mark.asyncio
    async def test_metrics_against_the_previous_period(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant(session_maker)
        now: datetime = datetime.now(UTC)
        for _ in range(4):
            await add_transaction(session_maker, merchant, paid_at=now - timedelta(days=1))
        for _ in range(2):
            await add_transaction(session_maker, merchant, paid_at=now - timedelta(days=9))

        order = await _order(async_client, auth_headers, order_number="A-1")
        matched: UUID = await add_transaction(
            session_maker,
            merchant,
            order_id=UUID(order["id"]),
            reconciliation_status=ReconciliationStatus.AUTO_MATCHED,
            paid_at=now - timedelta(hours=2),
        )
        await add_fulfillment(session_maker, merchant, UUID(order["id"]), matched)

        data: dict = (await async_client.get("/dashboard", headers=auth_headers)).json()["data"]

        transactions: dict = data["metrics"]["transactions"]
        assert transactions["successful"] == 5
        # 5 this week against 2 the week before
        assert transactions["delta_pct"] == 150.0
        reconciliation: dict = data["metrics"]["reconciliation"]
        assert reconciliation["matched_pct"] == 20.0
        assert reconciliation["unmatched"] == 6
        readiness: dict = data["metrics"]["readiness"]
        assert readiness["score"] is not None
        assert sum(readiness["distribution"].values()) == 100
        assert len(data["recent_transactions"]) == 5

    @pytest.mark.asyncio
    async def test_critical_dispute_prompts_and_activity(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant(session_maker)
        soon: UUID = await _dispute(session_maker, merchant, due_in=timedelta(hours=3))
        await _dispute(session_maker, merchant, due_in=timedelta(hours=30))
        await _order(async_client, auth_headers, order_number="1048")
        paid = await _order(async_client, auth_headers, order_number="1049")
        async with session_maker() as session:
            await session.execute(
                update(Order).where(Order.id == UUID(paid["id"])).values(status="paid")
            )
            session.add(
                ReconciliationSession(
                    merchant_id=merchant,
                    date_range_start=datetime.now(UTC).date(),
                    date_range_end=datetime.now(UTC).date(),
                    status=ReconciliationSessionStatus.COMPLETED,
                    matched_count=7,
                    completed_at=datetime.now(UTC),
                )
            )
            now: datetime = datetime.now(UTC)
            for minutes, state in ((30, TrustState.NEW), (10, TrustState.BUILDING)):
                session.add(
                    TrustSnapshot(
                        merchant_id=merchant,
                        state=state,
                        internal_score=50,
                        signals={},
                        reason="scheduled",
                        created_at=now - timedelta(minutes=minutes),
                    )
                )
            await session.commit()

        data: dict = (await async_client.get("/dashboard", headers=auth_headers)).json()["data"]

        assert data["critical_dispute"]["id"] == str(soon)
        assert data["metrics"]["disputes"]["open"] == 2
        assert data["metrics"]["disputes"]["critical"] == 1
        assert [p["order_number"] for p in data["prompts"]] == ["1049"]
        types: list[str] = [item["type"] for item in data["activity"]]
        assert "dispute_created" in types
        assert "reconciliation_completed" in types
        assert "trust_changed" in types
        trust = next(item for item in data["activity"] if item["type"] == "trust_changed")
        assert trust["title"] == "Trust state changed: New to Building"
        dispute = next(item for item in data["activity"] if item["type"] == "dispute_created")
        assert dispute["title"] == "New dispute for NGN 45,000.00"
        assert dispute["link"]["type"] == "dispute"

    @pytest.mark.asyncio
    async def test_a_failing_block_is_null(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant(session_maker)
        await _dispute(session_maker, merchant, due_in=timedelta(hours=2))

        with patch.object(
            DashboardRepository, "critical_dispute", side_effect=RuntimeError("boom")
        ):
            res: Response = await async_client.get("/dashboard", headers=auth_headers)

        assert res.status_code == 200
        data: dict = res.json()["data"]
        assert data["critical_dispute"] is None
        # the rest still rendered, on the same database session
        assert data["metrics"]["disputes"]["open"] == 1
        assert data["activity"]

    @pytest.mark.asyncio
    async def test_period_validation(self, async_client: AsyncClient, auth_headers: dict):
        res: Response = await async_client.get(
            "/dashboard?date_from=2026-10-10", headers=auth_headers
        )
        assert res.status_code == 422
        res = await async_client.get(
            "/dashboard?date_from=2026-10-10&date_to=2026-10-01", headers=auth_headers
        )
        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_custom_period(self, async_client: AsyncClient, auth_headers: dict):
        data: dict = (
            await async_client.get(
                "/dashboard?date_from=2026-10-01&date_to=2026-10-21", headers=auth_headers
            )
        ).json()["data"]
        assert data["period"] == {
            "date_from": "2026-10-01",
            "date_to": "2026-10-21",
            "previous_from": "2026-09-10",
            "previous_to": "2026-09-30",
        }


class TestCharts:
    @pytest.mark.asyncio
    async def test_dispute_timeline(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant(session_maker)
        await _dispute(session_maker, merchant)
        await _dispute(
            session_maker,
            merchant,
            status=DisputeStatus.WON,
            resolved_at=datetime.now(UTC),
        )

        data: dict = (
            await async_client.get("/dashboard/dispute-timeline?days=30", headers=auth_headers)
        ).json()["data"]

        assert data["days"] == 30
        assert len(data["series"]) == 30
        today: dict = data["series"][-1]
        assert (today["opened"], today["won"]) == (2, 1)
        assert sum(day["opened"] for day in data["series"]) == 2

        res = await async_client.get("/dashboard/dispute-timeline?days=7", headers=auth_headers)
        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_reconciliation_health(
        self, async_client: AsyncClient, auth_headers: dict, session_maker: SessionMaker
    ):
        merchant: UUID = await _merchant(session_maker)
        today = datetime.now(UTC).date()
        async with session_maker() as session:
            for status, unmatched, flagged in (
                (ReconciliationSessionStatus.COMPLETED, 2, 1),
                (ReconciliationSessionStatus.COMPLETED, 4, 1),
                (ReconciliationSessionStatus.IN_PROGRESS, 0, 0),
            ):
                session.add(
                    ReconciliationSession(
                        merchant_id=merchant,
                        date_range_start=today,
                        date_range_end=today,
                        status=status,
                        unmatched_payments_count=unmatched,
                        unmatched_orders_count=0,
                        flagged_count=flagged,
                    )
                )
            await session.commit()
        await add_transaction(session_maker, merchant)
        order = await _order(async_client, auth_headers)
        await add_transaction(
            session_maker,
            merchant,
            order_id=UUID(order["id"]),
            reconciliation_status=ReconciliationStatus.AUTO_MATCHED,
        )

        data: dict = (
            await async_client.get("/dashboard/reconciliation-health", headers=auth_headers)
        ).json()["data"]

        assert (data["sessions_started"], data["sessions_completed"]) == (3, 2)
        assert data["completion_rate"] == 66.7
        # (2 + 1) and (4 + 1) mismatches
        assert data["avg_mismatches"] == 4.0
        assert data["series"][-1] == {
            "date": today.isoformat(),
            "payments": 2,
            "matched": 1,
            "matched_pct": 50.0,
        }

"""Rows the paystack sync and later modules will write; inserted directly until they exist"""

import itertools
from datetime import UTC, datetime, timedelta
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.models.disputes import Dispute
from app.api.models.enums import (
    Currency,
    FulfillmentType,
    ReconciliationStatus,
    TransactionChannel,
    TransactionStatus,
)
from app.api.models.fulfillments import Fulfillment
from app.api.models.merchants import Merchant
from app.api.models.orders import Order
from app.api.models.transactions import Transaction
from tests.conftest import OTP_CODE

_ids = itertools.count(4600021345)

SessionMaker = async_sessionmaker[AsyncSession]


async def merchant_id(session_maker: SessionMaker, email: str) -> UUID:
    async with session_maker() as session:
        return (
            await session.execute(select(Merchant.id).where(Merchant.email == email))
        ).scalar_one()


async def sign_in_merchant(async_client: AsyncClient, email: str, business_name: str) -> dict:
    """Registers, verifies and logs in another merchant; returns its auth headers"""
    payload: dict = {
        "email": email,
        "password": "other_merchant_password",  # pragma: allowlist secret
        "business_name": business_name,
    }
    await async_client.post("/auth/register", json=payload)
    await async_client.post("/auth/verify", json={"email": email, "otp_code": OTP_CODE})
    res = await async_client.post(
        "/auth/login", json={"email": email, "password": payload["password"]}
    )
    return {"Authorization": f"Bearer {res.json()['data']['access_token']}"}


async def add_transaction(
    session_maker: SessionMaker,
    merchant: UUID,
    customer_id: UUID | None = None,
    order_id: UUID | None = None,
    amount: int = 4500000,
    status: TransactionStatus = TransactionStatus.SUCCESS,
    reconciliation_status: ReconciliationStatus = ReconciliationStatus.UNMATCHED,
    paid_at: datetime | None = None,
    created_at: datetime | None = None,
    customer_email: str | None = None,
) -> UUID:
    paystack_id: int = next(_ids)

    async with session_maker() as session:
        transaction = Transaction(
            merchant_id=merchant,
            paystack_transaction_id=paystack_id,
            paystack_reference=f"T{paystack_id}",
            customer_id=customer_id,
            order_id=order_id,
            amount=amount,
            currency=Currency.NGN,
            channel=TransactionChannel.CARD,
            status=status,
            reconciliation_status=reconciliation_status,
            paid_at=paid_at or datetime.now(UTC),
            paystack_created_at=created_at or paid_at or datetime.now(UTC),
            customer_email=customer_email,
        )
        session.add(transaction)
        await session.commit()
        return transaction.id


async def add_dispute(session_maker: SessionMaker, merchant: UUID, transaction_id: UUID) -> UUID:
    paystack_id: int = next(_ids)

    async with session_maker() as session:
        dispute = Dispute(
            merchant_id=merchant,
            transaction_id=transaction_id,
            paystack_dispute_id=paystack_id,
            paystack_reference=f"D{paystack_id}",
            amount=4500000,
            due_at=datetime.now(UTC) + timedelta(hours=16),
        )
        session.add(dispute)
        await session.commit()
        return dispute.id


async def add_fulfillment(
    session_maker: SessionMaker,
    merchant: UUID,
    order_id: UUID,
    transaction_id: UUID | None = None,
) -> UUID:
    async with session_maker() as session:
        fulfillment = Fulfillment(
            merchant_id=merchant,
            order_id=order_id,
            transaction_id=transaction_id,
            type=FulfillmentType.DELIVERY,
            delivery_date=datetime.now(UTC),
            tracking_number="GIG-0012",
        )
        session.add(fulfillment)
        await session.commit()
        return fulfillment.id


async def set_order(session_maker: SessionMaker, order_id: str, **values) -> None:
    """e.g. mark an order paid, which only reconciliation does"""
    async with session_maker() as session:
        await session.execute(update(Order).where(Order.id == UUID(order_id)).values(**values))
        await session.commit()

"""migrate_010

Revision ID: f2a8d4c6b0e1
Revises: e5b9c3a7d1f4
Create Date: 2026-10-17 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a8d4c6b0e1"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "e5b9c3a7d1f4"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_CHANNELS: list[str] = ["bank", "qr", "eft", "apple_pay", "other"]


def upgrade() -> None:
    """Upgrade schema."""
    # merchants: where the next transaction sync starts from
    op.add_column(
        "merchants",
        sa.Column("last_transaction_sync_at", sa.DateTime(timezone=True), nullable=True),
    )

    # transactions: references are only unique within one paystack account
    op.drop_index("ix_transactions_paystack_reference", table_name="transactions")
    op.create_index(
        op.f("ix_transactions_paystack_reference"),
        "transactions",
        ["paystack_reference"],
        unique=False,
    )
    op.create_unique_constraint(
        "transactions_merchant_reference_uq", "transactions", ["merchant_id", "paystack_reference"]
    )
    # the sync upserts on the paystack id
    op.create_unique_constraint(
        "transactions_merchant_paystack_id_uq",
        "transactions",
        ["merchant_id", "paystack_transaction_id"],
    )

    # every channel paystack reports, plus other for ones added later
    for channel in NEW_CHANNELS:
        op.execute(f"ALTER TYPE transaction_channel ADD VALUE IF NOT EXISTS '{channel}'")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "UPDATE transactions SET channel = 'card' WHERE channel::text IN "
        "('bank', 'qr', 'eft', 'apple_pay', 'other')"
    )
    op.execute("ALTER TYPE transaction_channel RENAME TO transaction_channel_old")
    op.execute(
        "CREATE TYPE transaction_channel AS ENUM ('card', 'bank_transfer', 'mobile_money', 'ussd')"
    )
    op.execute(
        "ALTER TABLE transactions ALTER COLUMN channel TYPE transaction_channel "
        "USING channel::text::transaction_channel"
    )
    op.execute("DROP TYPE transaction_channel_old")

    op.drop_constraint("transactions_merchant_paystack_id_uq", "transactions", type_="unique")
    op.drop_constraint("transactions_merchant_reference_uq", "transactions", type_="unique")
    op.drop_index(op.f("ix_transactions_paystack_reference"), table_name="transactions")
    op.create_index(
        "ix_transactions_paystack_reference", "transactions", ["paystack_reference"], unique=True
    )

    op.drop_column("merchants", "last_transaction_sync_at")

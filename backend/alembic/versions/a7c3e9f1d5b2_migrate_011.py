"""migrate_011

Revision ID: a7c3e9f1d5b2
Revises: f2a8d4c6b0e1
Create Date: 2026-10-17 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3e9f1d5b2"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "f2a8d4c6b0e1"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # transactions: why and when the merchant flagged a payment for review
    op.add_column("transactions", sa.Column("flag_reason", sa.VARCHAR(length=255), nullable=True))
    op.add_column(
        "transactions", sa.Column("flagged_at", sa.DateTime(timezone=True), nullable=True)
    )

    # transactions: when the attempt started on paystack, so date filters cover unpaid
    # attempts too. Rows synced before this only have paid_at (or synced_at); the next
    # sync of their window overwrites the estimate with paystack's value
    op.add_column(
        "transactions",
        sa.Column("paystack_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE transactions SET paystack_created_at = coalesce(paid_at, synced_at)")
    op.alter_column("transactions", "paystack_created_at", nullable=False)
    op.create_index(
        "transactions_merchant_created_at_idx",
        "transactions",
        ["merchant_id", "paystack_created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("transactions_merchant_created_at_idx", table_name="transactions")
    op.drop_column("transactions", "paystack_created_at")
    op.drop_column("transactions", "flagged_at")
    op.drop_column("transactions", "flag_reason")

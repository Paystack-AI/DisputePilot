"""migrate_020

Revision ID: a1c3e5f7b9d2
Revises: d7a9c1e3f5b8
Create Date: 2026-10-22 04:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c3e5f7b9d2"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "d7a9c1e3f5b8"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # when the sale happened, set by the merchant; existing orders keep the only date they
    # had, when they were logged
    op.add_column("orders", sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE orders SET ordered_at = created_at")
    op.alter_column("orders", "ordered_at", nullable=False)
    op.create_index("orders_merchant_ordered_at_idx", "orders", ["merchant_id", "ordered_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("orders_merchant_ordered_at_idx", table_name="orders")
    op.drop_column("orders", "ordered_at")

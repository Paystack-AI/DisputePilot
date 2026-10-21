"""migrate_017

Revision ID: b5e7a9c1d3f6
Revises: a4d6f8b0c2e5
Create Date: 2026-10-21 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5e7a9c1d3f6"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "a4d6f8b0c2e5"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # the sample behind a trust state, shown as "based on N payments in 30 days"
    op.add_column("trust_profiles", sa.Column("payments_30d", sa.INTEGER(), nullable=True))
    op.add_column("trust_profiles", sa.Column("days_on_platform", sa.INTEGER(), nullable=True))
    # the history endpoint reads a merchant's snapshots by time
    op.create_index(
        "trust_snapshots_merchant_created_idx", "trust_snapshots", ["merchant_id", "created_at"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("trust_snapshots_merchant_created_idx", table_name="trust_snapshots")
    op.drop_column("trust_profiles", "days_on_platform")
    op.drop_column("trust_profiles", "payments_30d")

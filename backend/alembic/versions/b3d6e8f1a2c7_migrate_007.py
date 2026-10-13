"""migrate_007

Revision ID: b3d6e8f1a2c7
Revises: 5f81c2d9b7e4
Create Date: 2026-10-13 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d6e8f1a2c7"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "5f81c2d9b7e4"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # filled from paystack data after connecting, no longer asked at sign up
    op.alter_column(
        "merchants",
        "paystack_integration_id",
        existing_type=sa.VARCHAR(length=100),
        nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "merchants",
        "paystack_integration_id",
        existing_type=sa.VARCHAR(length=100),
        nullable=False,
    )

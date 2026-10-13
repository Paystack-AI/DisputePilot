"""migrate_006

Revision ID: 5f81c2d9b7e4
Revises: 9e3b71c4a8d2
Create Date: 2026-10-13 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5f81c2d9b7e4"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "9e3b71c4a8d2"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "merchants",
        sa.Column("is_verified", sa.BOOLEAN(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "merchants",
        sa.Column("is_active", sa.BOOLEAN(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "merchants", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("merchants", "deactivated_at")
    op.drop_column("merchants", "is_active")
    op.drop_column("merchants", "is_verified")

"""migrate_005

Revision ID: 9e3b71c4a8d2
Revises: 4c2d9e7a1f03
Create Date: 2026-10-13 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9e3b71c4a8d2"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "4c2d9e7a1f03"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("merchants", sa.Column("hashed_password", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("merchants", "hashed_password")

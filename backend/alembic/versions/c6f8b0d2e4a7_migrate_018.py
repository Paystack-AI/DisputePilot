"""migrate_018

Revision ID: c6f8b0d2e4a7
Revises: b5e7a9c1d3f6
Create Date: 2026-10-21 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6f8b0d2e4a7"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "b5e7a9c1d3f6"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # what the ai writes back for trust: an explanation and actions per profile, and a
    # one-line account of each state change
    op.add_column("trust_profiles", sa.Column("explanation", sa.Text(), nullable=True))
    op.add_column(
        "trust_profiles",
        sa.Column("recommendations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "trust_profiles", sa.Column("explained_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "trust_profiles", sa.Column("explain_job_id", sa.VARCHAR(length=64), nullable=True)
    )
    op.add_column("trust_snapshots", sa.Column("summary", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("trust_snapshots", "summary")
    op.drop_column("trust_profiles", "explain_job_id")
    op.drop_column("trust_profiles", "explained_at")
    op.drop_column("trust_profiles", "recommendations")
    op.drop_column("trust_profiles", "explanation")

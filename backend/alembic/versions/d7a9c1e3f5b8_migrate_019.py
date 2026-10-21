"""migrate_019

Revision ID: d7a9c1e3f5b8
Revises: c6f8b0d2e4a7
Create Date: 2026-10-21 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a9c1e3f5b8"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "c6f8b0d2e4a7"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # operator accounts are separate from merchants and log in through /admin/auth/login
    op.create_table(
        "admins",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("email", sa.VARCHAR(length=255), nullable=False),
        sa.Column("name", sa.VARCHAR(length=255), nullable=True),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column("is_active", sa.BOOLEAN(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="admins_pk"),
        sa.UniqueConstraint("email", name="admins_email_uq"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("admins")

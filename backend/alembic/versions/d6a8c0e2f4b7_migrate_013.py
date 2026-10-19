"""migrate_013

Revision ID: d6a8c0e2f4b7
Revises: b8d2f4a6c1e3
Create Date: 2026-10-19 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d6a8c0e2f4b7"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "b8d2f4a6c1e3"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # whatsapp alerts are off the product until the business is verified with meta;
    # notifications go by email and in-app
    op.drop_column("merchant_settings", "notification_whatsapp")

    op.execute("DELETE FROM notifications_log WHERE channel = 'whatsapp'")
    op.execute("ALTER TYPE notification_channel RENAME TO notification_channel_old")
    op.execute("CREATE TYPE notification_channel AS ENUM ('email', 'in_app')")
    op.execute(
        "ALTER TABLE notifications_log ALTER COLUMN channel TYPE notification_channel "
        "USING channel::text::notification_channel"
    )
    op.execute("DROP TYPE notification_channel_old")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM notifications_log WHERE channel = 'in_app'")
    op.execute("ALTER TYPE notification_channel RENAME TO notification_channel_old")
    op.execute("CREATE TYPE notification_channel AS ENUM ('whatsapp', 'email')")
    op.execute(
        "ALTER TABLE notifications_log ALTER COLUMN channel TYPE notification_channel "
        "USING channel::text::notification_channel"
    )
    op.execute("DROP TYPE notification_channel_old")

    op.add_column(
        "merchant_settings",
        sa.Column("notification_whatsapp", sa.VARCHAR(length=50), nullable=True),
    )

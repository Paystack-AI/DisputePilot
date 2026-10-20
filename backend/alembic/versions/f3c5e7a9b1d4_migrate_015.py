"""migrate_015

Revision ID: f3c5e7a9b1d4
Revises: e7b1d3f5a9c2
Create Date: 2026-10-20 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3c5e7a9b1d4"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "e7b1d3f5a9c2"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # the optional dispute webhook: a per-merchant url and when it last delivered
    op.add_column("merchants", sa.Column("webhook_token", sa.VARCHAR(length=64), nullable=True))
    op.add_column(
        "merchants",
        sa.Column("webhook_last_received_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("merchants_webhook_token_key", "merchants", ["webhook_token"])

    op.create_table(
        "webhook_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("event", sa.VARCHAR(length=100), nullable=False),
        sa.Column("body_hash", sa.VARCHAR(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.PrimaryKeyConstraint("id", name="webhook_events_pk"),
        sa.UniqueConstraint("merchant_id", "body_hash", name="webhook_events_merchant_body_uq"),
    )
    op.create_index(
        "webhook_events_unprocessed_idx",
        "webhook_events",
        ["received_at"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )

    # disputes are upserted from webhooks and the poller
    op.add_column("disputes", sa.Column("paystack_status", sa.VARCHAR(length=50), nullable=True))
    op.add_column("disputes", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "disputes", sa.Column("paystack_synced_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "disputes", sa.Column("last_deadline_warning_hours", sa.SMALLINT(), nullable=True)
    )
    # the deadline watcher reads open disputes by deadline
    op.create_index("disputes_due_at_idx", "disputes", ["due_at"])
    op.create_unique_constraint(
        "disputes_merchant_paystack_id_uq", "disputes", ["merchant_id", "paystack_dispute_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("disputes_merchant_paystack_id_uq", "disputes", type_="unique")
    op.drop_index("disputes_due_at_idx", table_name="disputes")
    op.drop_column("disputes", "last_deadline_warning_hours")
    op.drop_column("disputes", "paystack_synced_at")
    op.drop_column("disputes", "resolved_at")
    op.drop_column("disputes", "paystack_status")

    op.drop_index("webhook_events_unprocessed_idx", table_name="webhook_events")
    op.drop_table("webhook_events")

    op.drop_constraint("merchants_webhook_token_key", "merchants", type_="unique")
    op.drop_column("merchants", "webhook_last_received_at")
    op.drop_column("merchants", "webhook_token")

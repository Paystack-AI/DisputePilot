"""migrate_004

Revision ID: 4c2d9e7a1f03
Revises: b0a5f6be9cf6
Create Date: 2026-10-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c2d9e7a1f03"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "b0a5f6be9cf6"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_CURRENCIES = ("USD", "GHS", "ZAR", "KES", "XOF")

currency_enum = postgresql.ENUM(name="currency_enum", create_type=False)
paystack_mode = postgresql.ENUM("live", "test", name="paystack_mode")
onboarding_step = postgresql.ENUM(
    "connect_paystack",
    "configure_notifications",
    "initial_sync",
    "first_reconciliation",
    "completed",
    name="onboarding_step",
)
initial_sync_status = postgresql.ENUM(
    "not_started", "in_progress", "completed", "failed", name="initial_sync_status"
)


def upgrade() -> None:
    """Upgrade schema."""
    # autogenerate does not detect new enum values
    for code in NEW_CURRENCIES:
        op.execute(f"ALTER TYPE currency_enum ADD VALUE IF NOT EXISTS '{code}'")

    paystack_mode.create(op.get_bind(), checkfirst=True)
    op.add_column("merchants", sa.Column("paystack_mode", paystack_mode, nullable=True))
    op.add_column(
        "merchants",
        sa.Column("paystack_connected_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "merchant_settings",
        sa.Column("timezone", sa.VARCHAR(length=64), server_default="UTC", nullable=False),
    )
    op.add_column(
        "merchant_settings",
        sa.Column("default_currency", currency_enum, server_default="NGN", nullable=False),
    )

    op.create_table(
        "merchant_onboarding",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("uuid_generate_v7()"),
            nullable=False,
        ),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("current_step", onboarding_step, nullable=False),
        sa.Column("initial_sync_status", initial_sync_status, nullable=False),
        sa.Column("initial_sync_total", sa.INTEGER(), nullable=True),
        sa.Column("initial_sync_processed", sa.INTEGER(), nullable=False),
        sa.Column("first_reconciliation_skipped", sa.BOOLEAN(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
        ),
        sa.PrimaryKeyConstraint("id", name="merchant_onboarding_pk"),
        sa.UniqueConstraint("merchant_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("merchant_onboarding")
    initial_sync_status.drop(op.get_bind(), checkfirst=True)
    onboarding_step.drop(op.get_bind(), checkfirst=True)

    op.drop_column("merchant_settings", "default_currency")
    op.drop_column("merchant_settings", "timezone")

    op.drop_column("merchants", "paystack_connected_at")
    op.drop_column("merchants", "paystack_mode")
    paystack_mode.drop(op.get_bind(), checkfirst=True)

    # Postgres cannot drop enum values; the added currencies stay on currency_enum.

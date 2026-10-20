"""migrate_014

Revision ID: e7b1d3f5a9c2
Revises: d6a8c0e2f4b7
Create Date: 2026-10-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7b1d3f5a9c2"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "d6a8c0e2f4b7"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

match_suggestion_status = postgresql.ENUM("pending", "rejected", name="match_suggestion_status")
order_resolution = postgresql.ENUM("cash_payment", "payment_failed", name="order_resolution")


def upgrade() -> None:
    """Upgrade schema."""
    match_suggestion_status.create(op.get_bind(), checkfirst=True)
    order_resolution.create(op.get_bind(), checkfirst=True)

    # likely matches waiting for the merchant, and the pairs they rejected
    op.create_table(
        "match_suggestions",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("tier", sa.SMALLINT(), nullable=False),
        sa.Column("confidence", sa.SMALLINT(), nullable=False),
        sa.Column("reason", sa.VARCHAR(length=255), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="match_suggestion_status", create_type=False),
            nullable=False,
        ),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="match_suggestions_pk"),
        sa.UniqueConstraint("transaction_id", "order_id", name="match_suggestions_pair_uq"),
    )
    op.create_index(
        "match_suggestions_merchant_status_idx", "match_suggestions", ["merchant_id", "status"]
    )
    op.create_index("match_suggestions_order_idx", "match_suggestions", ["order_id"])

    op.add_column("transactions", sa.Column("match_tier", sa.SMALLINT(), nullable=True))
    op.add_column("transactions", sa.Column("match_confidence", sa.SMALLINT(), nullable=True))

    op.add_column(
        "orders",
        sa.Column(
            "resolution",
            postgresql.ENUM(name="order_resolution", create_type=False),
            nullable=True,
        ),
    )
    op.add_column("orders", sa.Column("flag_reason", sa.VARCHAR(length=255), nullable=True))
    op.add_column("orders", sa.Column("flagged_at", sa.DateTime(timezone=True), nullable=True))

    # one open session per merchant
    op.create_index(
        "reconciliation_sessions_merchant_open_uq",
        "reconciliation_sessions",
        ["merchant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'in_progress'"),
    )
    op.create_index(
        "reconciliation_sessions_merchant_created_idx",
        "reconciliation_sessions",
        ["merchant_id", "created_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "reconciliation_sessions_merchant_created_idx", table_name="reconciliation_sessions"
    )
    op.drop_index("reconciliation_sessions_merchant_open_uq", table_name="reconciliation_sessions")

    op.drop_column("orders", "flagged_at")
    op.drop_column("orders", "flag_reason")
    op.drop_column("orders", "resolution")

    op.drop_column("transactions", "match_confidence")
    op.drop_column("transactions", "match_tier")

    op.drop_index("match_suggestions_order_idx", table_name="match_suggestions")
    op.drop_index("match_suggestions_merchant_status_idx", table_name="match_suggestions")
    op.drop_table("match_suggestions")

    order_resolution.drop(op.get_bind(), checkfirst=True)
    match_suggestion_status.drop(op.get_bind(), checkfirst=True)

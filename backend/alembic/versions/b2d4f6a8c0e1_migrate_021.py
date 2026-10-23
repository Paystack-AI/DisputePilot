"""migrate_021

Revision ID: b2d4f6a8c0e1
Revises: a1c3e5f7b9d2
Create Date: 2026-10-23 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2d4f6a8c0e1"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "a1c3e5f7b9d2"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, constraint, column, referenced table, on delete action)
# owned records are removed with their parent; optional links are cleared; a record that
# cannot exist without the row it references (a dispute needs its transaction) goes too
FOREIGN_KEYS: list[tuple[str, str, str, str, str]] = [
    ("customers", "customers_merchant_id_fkey", "merchant_id", "merchants", "CASCADE"),
    (
        "merchant_settings",
        "merchant_settings_merchant_id_fkey",
        "merchant_id",
        "merchants",
        "CASCADE",
    ),
    (
        "reconciliation_sessions",
        "reconciliation_sessions_merchant_id_fkey",
        "merchant_id",
        "merchants",
        "CASCADE",
    ),
    (
        "trust_profiles",
        "trust_profiles_merchant_id_fkey",
        "merchant_id",
        "merchants",
        "CASCADE",
    ),
    (
        "trust_snapshots",
        "trust_snapshots_merchant_id_fkey",
        "merchant_id",
        "merchants",
        "CASCADE",
    ),
    ("orders", "orders_customer_id_fkey", "customer_id", "customers", "SET NULL"),
    ("orders", "orders_merchant_id_fkey", "merchant_id", "merchants", "CASCADE"),
    (
        "transactions",
        "transactions_customer_id_fkey",
        "customer_id",
        "customers",
        "SET NULL",
    ),
    ("transactions", "transactions_merchant_id_fkey", "merchant_id", "merchants", "CASCADE"),
    ("transactions", "transactions_order_id_fkey", "order_id", "orders", "SET NULL"),
    ("disputes", "disputes_merchant_id_fkey", "merchant_id", "merchants", "CASCADE"),
    ("disputes", "disputes_transaction_id_fkey", "transaction_id", "transactions", "CASCADE"),
    ("fulfillments", "fulfillments_merchant_id_fkey", "merchant_id", "merchants", "CASCADE"),
    ("fulfillments", "fulfillments_order_id_fkey", "order_id", "orders", "CASCADE"),
    (
        "fulfillments",
        "fulfillments_transaction_id_fkey",
        "transaction_id",
        "transactions",
        "SET NULL",
    ),
    (
        "dispute_evidence_files",
        "dispute_evidence_files_dispute_id_fkey",
        "dispute_id",
        "disputes",
        "CASCADE",
    ),
    (
        "notifications_log",
        "notifications_log_dispute_id_fkey",
        "dispute_id",
        "disputes",
        "SET NULL",
    ),
    (
        "notifications_log",
        "notifications_log_merchant_id_fkey",
        "merchant_id",
        "merchants",
        "CASCADE",
    ),
    (
        "merchant_onboarding",
        "merchant_onboarding_merchant_id_fkey",
        "merchant_id",
        "merchants",
        "CASCADE",
    ),
    ("files", "files_dispute_id_fkey", "dispute_id", "disputes", "SET NULL"),
    ("files", "files_fulfillment_id_fkey", "fulfillment_id", "fulfillments", "SET NULL"),
    ("files", "files_merchant_id_fkey", "merchant_id", "merchants", "CASCADE"),
    (
        "match_suggestions",
        "match_suggestions_merchant_id_fkey",
        "merchant_id",
        "merchants",
        "CASCADE",
    ),
    ("webhook_events", "webhook_events_merchant_id_fkey", "merchant_id", "merchants", "CASCADE"),
    (
        "evidence_revisions",
        "evidence_revisions_dispute_id_fkey",
        "dispute_id",
        "disputes",
        "CASCADE",
    ),
    (
        "evidence_revisions",
        "evidence_revisions_merchant_id_fkey",
        "merchant_id",
        "merchants",
        "CASCADE",
    ),
]


def upgrade() -> None:
    """Upgrade schema."""
    for table, name, column, ref_table, ondelete in FOREIGN_KEYS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, ref_table, [column], ["id"], ondelete=ondelete)


def downgrade() -> None:
    """Downgrade schema."""
    for table, name, column, ref_table, _ in reversed(FOREIGN_KEYS):
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, ref_table, [column], ["id"])

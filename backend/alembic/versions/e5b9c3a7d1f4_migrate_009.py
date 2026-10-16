"""migrate_009

Revision ID: e5b9c3a7d1f4
Revises: c8a4e2f6d913
Create Date: 2026-10-16 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b9c3a7d1f4"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "c8a4e2f6d913"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (index, table, column) for every column the customer and order searches match with
# ILIKE '%term%'; a btree index can't serve a leading wildcard, a trigram index can
TRGM_INDEXES: list[tuple[str, str, str]] = [
    ("customers_name_trgm_idx", "customers", "name"),
    ("customers_email_trgm_idx", "customers", "email"),
    ("orders_order_number_trgm_idx", "orders", "order_number"),
    ("orders_description_trgm_idx", "orders", "description"),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    for index_name, table, column in TRGM_INDEXES:
        op.create_index(
            index_name,
            table,
            [column],
            unique=False,
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )


def downgrade() -> None:
    """Downgrade schema."""
    for index_name, table, _ in reversed(TRGM_INDEXES):
        op.drop_index(index_name, table_name=table)

    # pg_trgm is left installed: other objects in the database may depend on it

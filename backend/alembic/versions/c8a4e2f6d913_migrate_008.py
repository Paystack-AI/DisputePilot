"""migrate_008

Revision ID: c8a4e2f6d913
Revises: b3d6e8f1a2c7
Create Date: 2026-10-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8a4e2f6d913"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "b3d6e8f1a2c7"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # customers: one per payer email per merchant, stats counted on read (no money totals)
    op.drop_column("customers", "total_transactions")
    op.drop_column("customers", "total_spent")
    op.drop_column("customers", "total_outstanding")
    op.drop_column("customers", "total_disputes")
    op.alter_column("customers", "name", existing_type=sa.VARCHAR(length=255), nullable=True)
    op.add_column(
        "customers",
        sa.Column("is_shared", sa.BOOLEAN(), server_default=sa.false(), nullable=False),
    )
    op.add_column("customers", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE customers SET email = lower(email) WHERE email IS NOT NULL")
    op.create_unique_constraint(
        "customers_merchant_email_uq", "customers", ["merchant_id", "email"]
    )
    op.create_unique_constraint(
        "customers_merchant_paystack_code_uq",
        "customers",
        ["merchant_id", "paystack_customer_code"],
    )

    # transactions: ledger key, set at sync
    op.add_column("transactions", sa.Column("customer_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "transactions_customer_id_fkey", "transactions", "customers", ["customer_id"], ["id"]
    )
    op.create_index(
        op.f("ix_transactions_customer_id"), "transactions", ["customer_id"], unique=False
    )

    # orders: optional merchant-entered order number, unique per merchant ignoring case
    op.alter_column("orders", "order_number", existing_type=sa.VARCHAR(length=50), nullable=True)
    op.create_index(
        "orders_merchant_order_number_uq",
        "orders",
        ["merchant_id", sa.text("lower(order_number)")],
        unique=True,
        postgresql_where=sa.text("order_number IS NOT NULL"),
    )
    op.create_index(op.f("ix_orders_customer_id"), "orders", ["customer_id"], unique=False)

    # orders: partially_paid removed; amount mismatches are reconciliation flags instead
    op.execute("UPDATE orders SET status = 'pending' WHERE status = 'partially_paid'")
    op.execute("ALTER TYPE order_status RENAME TO order_status_old")
    op.execute("CREATE TYPE order_status AS ENUM ('pending', 'paid', 'fulfilled', 'cancelled')")
    op.execute(
        "ALTER TABLE orders ALTER COLUMN status TYPE order_status USING status::text::order_status"
    )
    op.execute("DROP TYPE order_status_old")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TYPE order_status RENAME TO order_status_old")
    op.execute(
        "CREATE TYPE order_status AS ENUM "
        "('pending', 'paid', 'partially_paid', 'fulfilled', 'cancelled')"
    )
    op.execute(
        "ALTER TABLE orders ALTER COLUMN status TYPE order_status USING status::text::order_status"
    )
    op.execute("DROP TYPE order_status_old")

    op.drop_index(op.f("ix_orders_customer_id"), table_name="orders")
    op.drop_index("orders_merchant_order_number_uq", table_name="orders")
    # orders without a number can not go back to a required column
    op.execute("UPDATE orders SET order_number = id::text WHERE order_number IS NULL")
    op.alter_column("orders", "order_number", existing_type=sa.VARCHAR(length=50), nullable=False)

    op.drop_index(op.f("ix_transactions_customer_id"), table_name="transactions")
    op.drop_constraint("transactions_customer_id_fkey", "transactions", type_="foreignkey")
    op.drop_column("transactions", "customer_id")

    op.drop_constraint("customers_merchant_paystack_code_uq", "customers", type_="unique")
    op.drop_constraint("customers_merchant_email_uq", "customers", type_="unique")
    op.drop_column("customers", "updated_at")
    op.drop_column("customers", "is_shared")
    op.execute("UPDATE customers SET name = coalesce(email, '') WHERE name IS NULL")
    op.alter_column("customers", "name", existing_type=sa.VARCHAR(length=255), nullable=False)
    op.add_column(
        "customers",
        sa.Column("total_disputes", sa.INTEGER(), server_default="0", nullable=False),
    )
    op.add_column(
        "customers",
        sa.Column("total_outstanding", sa.BIGINT(), server_default="0", nullable=False),
    )
    op.add_column(
        "customers", sa.Column("total_spent", sa.BIGINT(), server_default="0", nullable=False)
    )
    op.add_column(
        "customers",
        sa.Column("total_transactions", sa.INTEGER(), server_default="0", nullable=False),
    )

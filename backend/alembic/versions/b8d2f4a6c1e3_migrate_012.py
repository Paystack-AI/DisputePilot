"""migrate_012

Revision ID: b8d2f4a6c1e3
Revises: a7c3e9f1d5b2
Create Date: 2026-10-19 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8d2f4a6c1e3"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "a7c3e9f1d5b2"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # uploaded images, shared by fulfillments and (later) disputes
    op.create_table(
        "files",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("fulfillment_id", sa.UUID(), nullable=True),
        sa.Column("dispute_id", sa.UUID(), nullable=True),
        sa.Column("object_name", sa.Text(), nullable=False),
        sa.Column("file_name", sa.VARCHAR(length=255), nullable=False),
        sa.Column("content_type", sa.VARCHAR(length=100), nullable=False),
        sa.Column("size", sa.BIGINT(), nullable=False),
        sa.Column("width", sa.INTEGER(), nullable=False),
        sa.Column("height", sa.INTEGER(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.ForeignKeyConstraint(["fulfillment_id"], ["fulfillments.id"]),
        sa.ForeignKeyConstraint(["dispute_id"], ["disputes.id"]),
        sa.PrimaryKeyConstraint("id", name="files_pk"),
        sa.UniqueConstraint("object_name", name="files_object_name_uq"),
    )
    op.create_index("files_merchant_id_idx", "files", ["merchant_id"])
    op.create_index("files_fulfillment_id_idx", "files", ["fulfillment_id"])
    op.create_index("files_dispute_id_idx", "files", ["dispute_id"])
    op.create_index(
        "files_unattached_created_at_idx",
        "files",
        ["created_at"],
        postgresql_where=sa.text("fulfillment_id IS NULL AND dispute_id IS NULL"),
    )

    # proof photos move to files (several per fulfillment)
    op.drop_column("fulfillments", "proof_photo_url")
    op.drop_column("fulfillments", "proof_document_url")
    op.add_column(
        "fulfillments", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    # a retried create (same Idempotency-Key) returns the first record
    op.add_column(
        "fulfillments", sa.Column("idempotency_key", sa.VARCHAR(length=255), nullable=True)
    )
    op.create_unique_constraint(
        "fulfillments_merchant_idempotency_key_uq",
        "fulfillments",
        ["merchant_id", "idempotency_key"],
    )
    op.create_index(
        "fulfillments_merchant_delivery_date_idx", "fulfillments", ["merchant_id", "delivery_date"]
    )
    op.create_index("fulfillments_order_id_idx", "fulfillments", ["order_id"])
    op.create_index("fulfillments_transaction_id_idx", "fulfillments", ["transaction_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("fulfillments_transaction_id_idx", table_name="fulfillments")
    op.drop_index("fulfillments_order_id_idx", table_name="fulfillments")
    op.drop_index("fulfillments_merchant_delivery_date_idx", table_name="fulfillments")
    op.drop_constraint("fulfillments_merchant_idempotency_key_uq", "fulfillments", type_="unique")
    op.drop_column("fulfillments", "idempotency_key")
    op.drop_column("fulfillments", "updated_at")
    op.add_column("fulfillments", sa.Column("proof_document_url", sa.Text(), nullable=True))
    op.add_column("fulfillments", sa.Column("proof_photo_url", sa.Text(), nullable=True))

    op.drop_index("files_unattached_created_at_idx", table_name="files")
    op.drop_index("files_dispute_id_idx", table_name="files")
    op.drop_index("files_fulfillment_id_idx", table_name="files")
    op.drop_index("files_merchant_id_idx", table_name="files")
    op.drop_table("files")

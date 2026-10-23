"""add persistent AI memory

Revision ID: f4a6c8e0b2d5
Revises: f3c5e7a9b1d4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4a6c8e0b2d5"
down_revision: str | Sequence[str] | None = "f3c5e7a9b1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_memories",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("dispute_id", sa.UUID(), nullable=True),
        sa.Column("memory_type", sa.VARCHAR(length=50), nullable=False),
        sa.Column("source_type", sa.VARCHAR(length=50), nullable=False),
        sa.Column("source_id", sa.VARCHAR(length=100), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.VARCHAR(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("corrected_by_id", sa.UUID(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deletion_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="ai_memories_pk"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.ForeignKeyConstraint(["dispute_id"], ["disputes.id"]),
        sa.ForeignKeyConstraint(["corrected_by_id"], ["ai_memories.id"]),
        sa.UniqueConstraint(
            "merchant_id", "source_type", "source_id", name="ai_memories_source_uq"
        ),
    )
    op.create_index(
        "ai_memories_merchant_scope_idx",
        "ai_memories",
        ["merchant_id", "dispute_id", "occurred_at"],
    )
    op.create_index(
        "ai_memories_source_idx", "ai_memories", ["merchant_id", "source_type", "source_id"]
    )


def downgrade() -> None:
    op.drop_index("ai_memories_source_idx", table_name="ai_memories")
    op.drop_index("ai_memories_merchant_scope_idx", table_name="ai_memories")
    op.drop_table("ai_memories")

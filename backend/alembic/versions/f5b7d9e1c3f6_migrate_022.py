"""enforce tenant-scoped AI memory and access audit

Revision ID: f5b7d9e1c3f6
Revises: f4a6c8e0b2d5
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f5b7d9e1c3f6"
down_revision: str | Sequence[str] | None = "f4a6c8e0b2d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing memories are assigned only from their non-null FK-backed merchant_id. There
    # is no user-supplied value or ambiguous historical ownership to infer here.
    op.add_column("ai_memories", sa.Column("tenant_id", sa.UUID(), nullable=True))
    op.execute("UPDATE ai_memories SET tenant_id = merchant_id WHERE tenant_id IS NULL")
    op.alter_column("ai_memories", "tenant_id", nullable=False)
    op.create_foreign_key(
        "ai_memories_tenant_fk", "ai_memories", "merchants", ["tenant_id"], ["id"]
    )
    op.drop_constraint("ai_memories_source_uq", "ai_memories", type_="unique")
    op.create_check_constraint(
        "ai_memories_tenant_merchant_ck", "ai_memories", "tenant_id = merchant_id"
    )
    op.create_unique_constraint(
        "ai_memories_source_uq",
        "ai_memories",
        ["tenant_id", "merchant_id", "source_type", "source_id"],
    )
    op.drop_index("ai_memories_merchant_scope_idx", table_name="ai_memories")
    op.drop_index("ai_memories_source_idx", table_name="ai_memories")
    op.create_index(
        "ai_memories_tenant_scope_idx",
        "ai_memories",
        ["tenant_id", "merchant_id", "dispute_id", "occurred_at"],
    )
    op.create_index(
        "ai_memories_source_idx",
        "ai_memories",
        ["tenant_id", "merchant_id", "source_type", "source_id"],
    )
    op.create_table(
        "ai_memory_access_audit",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.VARCHAR(length=20), nullable=False),
        sa.Column("memory_ids", postgresql.JSONB(), nullable=True),
        sa.Column("memory_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="ai_memory_access_audit_pk"),
        sa.ForeignKeyConstraint(["tenant_id"], ["merchants.id"]),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.CheckConstraint("tenant_id = merchant_id", name="ai_memory_audit_tenant_merchant_ck"),
    )
    op.create_index(
        "ai_memory_audit_scope_idx",
        "ai_memory_access_audit",
        ["tenant_id", "merchant_id", "created_at"],
    )
    for table in ("ai_memories", "ai_memory_access_audit"):
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        op.execute(
            sa.text(
                f"""
                CREATE POLICY {table}_tenant_isolation ON {table}
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                """
            )
        )


def downgrade() -> None:
    for table in ("ai_memories", "ai_memory_access_audit"):
        op.execute(sa.text(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
    op.drop_index("ai_memory_audit_scope_idx", table_name="ai_memory_access_audit")
    op.drop_table("ai_memory_access_audit")
    op.drop_index("ai_memories_source_idx", table_name="ai_memories")
    op.drop_index("ai_memories_tenant_scope_idx", table_name="ai_memories")
    op.drop_constraint("ai_memories_source_uq", "ai_memories", type_="unique")
    op.drop_constraint("ai_memories_tenant_merchant_ck", "ai_memories", type_="check")
    op.create_unique_constraint(
        "ai_memories_source_uq", "ai_memories", ["merchant_id", "source_type", "source_id"]
    )
    op.create_index(
        "ai_memories_merchant_scope_idx", "ai_memories", ["merchant_id", "dispute_id", "occurred_at"]
    )
    op.create_index(
        "ai_memories_source_idx", "ai_memories", ["merchant_id", "source_type", "source_id"]
    )
    op.drop_constraint("ai_memories_tenant_fk", "ai_memories", type_="foreignkey")
    op.drop_column("ai_memories", "tenant_id")

"""migrate_016

Revision ID: a4d6f8b0c2e5
Revises: f3c5e7a9b1d4
Create Date: 2026-10-21 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4d6f8b0c2e5"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "f3c5e7a9b1d4"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUMS: dict[str, tuple[str, ...]] = {
    "evidence_state": ("generating", "ready"),
    "evidence_step": ("classify", "generate", "score"),
    "generation_source": ("ai", "template"),
    "submission_state": ("submitting", "accepting", "submitted", "accepted", "failed"),
    "evidence_change": ("generated", "text", "documents", "text_and_documents", "submitted"),
}


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(op.get_bind(), checkfirst=True)
    # the submission email with the evidence pdf attached
    op.execute("ALTER TYPE notification_message_type ADD VALUE IF NOT EXISTS 'dispute_submitted'")

    # the evidence draft, the ai chain producing it, and the submission to paystack
    columns: list[sa.Column] = [
        sa.Column("evidence_state", _enum("evidence_state"), nullable=True),
        sa.Column("evidence_step", _enum("evidence_step"), nullable=True),
        sa.Column("ai_job_id", sa.VARCHAR(length=64), nullable=True),
        sa.Column("evidence_step_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generation_source", _enum("generation_source"), nullable=True),
        sa.Column("evidence_strategy", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("special_instructions", sa.Text(), nullable=True),
        sa.Column("evidence_conclusion", sa.Text(), nullable=True),
        sa.Column("missing_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "evidence_items_referenced", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("evidence_quality", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("evidence_version", sa.INTEGER(), server_default="0", nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submission_state", _enum("submission_state"), nullable=True),
        sa.Column("submission_error", sa.Text(), nullable=True),
        sa.Column("evidence_pdf_object", sa.Text(), nullable=True),
        sa.Column("paystack_uploaded_filename", sa.VARCHAR(length=255), nullable=True),
    ]
    for column in columns:
        op.add_column("disputes", column)
    # the timeout sweep's lookup of chains still running
    op.create_index(
        "disputes_generating_idx",
        "disputes",
        ["evidence_step_started_at"],
        postgresql_where=sa.text("evidence_state = 'generating'"),
    )

    op.add_column("files", sa.Column("caption", sa.VARCHAR(length=255), nullable=True))

    op.create_table(
        "evidence_revisions",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v7()"), nullable=False),
        sa.Column("dispute_id", sa.UUID(), nullable=False),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.INTEGER(), nullable=False),
        sa.Column("change", _enum("evidence_change"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("conclusion", sa.Text(), nullable=True),
        sa.Column("documents", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dispute_id"], ["disputes.id"]),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.PrimaryKeyConstraint("id", name="evidence_revisions_pk"),
        sa.UniqueConstraint("dispute_id", "version", name="evidence_revisions_dispute_version_uq"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("evidence_revisions")
    op.drop_column("files", "caption")

    op.drop_index("disputes_generating_idx", table_name="disputes")
    for column in (
        "paystack_uploaded_filename",
        "evidence_pdf_object",
        "submission_error",
        "submission_state",
        "edited_at",
        "generated_at",
        "evidence_version",
        "evidence_quality",
        "evidence_items_referenced",
        "missing_evidence",
        "evidence_conclusion",
        "special_instructions",
        "evidence_strategy",
        "generation_source",
        "evidence_step_started_at",
        "ai_job_id",
        "evidence_step",
        "evidence_state",
    ):
        op.drop_column("disputes", column)

    for name in ENUMS:
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)

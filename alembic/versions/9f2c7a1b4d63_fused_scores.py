"""fused_scores table for the report-only fused stylometric score

Revision ID: 9f2c7a1b4d63
Revises: 7c4d1e88a3b5
Create Date: 2026-08-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "9f2c7a1b4d63"
down_revision: str | None = "7c4d1e88a3b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fused_scores",
        sa.Column("submission_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("student_id", sa.Text(), nullable=False),
        sa.Column("fused_log_odds", sa.Float(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("band", sa.Text(), nullable=False),
        sa.Column("channels_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("model_version", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Recoverability for the baseline-volume confound (C1, 2026-08 fix
        # pass) — see original/db/models/live.py:FusedScore for why these
        # are needed on every row, not just aggregated later.
        sa.Column("baseline_samples", sa.Integer(), nullable=True),
        sa.Column("reference_profiles", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_fused_scores_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint("submission_id", name=op.f("pk_fused_scores")),
    )
    op.create_index(
        "idx_fused_scores_tenant_student",
        "fused_scores",
        ["tenant_id", "student_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_fused_scores_tenant_student", table_name="fused_scores")
    op.drop_table("fused_scores")

"""rule_d_profiles: rule D's derived statistics per approved past paper

Additive only: one new table, nothing existing is altered. One row per student per
teacher-approved past paper, keyed by the full scoped student id plus the SHA-256 of the
paper's text. Holds character n-gram and topic-masked profiles, feature vectors and
punctuation rates for the report-only, testing-phase rule D observation
(RULE_D_OBSERVATION, default off). No paper text. Deleted with the student's data and when
the approval is withdrawn.

Revision ID: c3e7a9d1f5b8
Revises: a1d5f3c7e9b2
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c3e7a9d1f5b8"
down_revision: str | None = "a1d5f3c7e9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_d_profiles",
        sa.Column("profile_key", sa.Text(), nullable=False),
        sa.Column("student_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("text_sha256", sa.Text(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("profile_key", name=op.f("pk_rule_d_profiles")),
    )
    op.create_index(op.f("ix_rule_d_profiles_student_id"), "rule_d_profiles", ["student_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_rule_d_profiles_student_id"), table_name="rule_d_profiles")
    op.drop_table("rule_d_profiles")

"""Bluebook round 2: per-question answers, marks and feedback, result release

Revision ID: f4c9a2d71b30
Revises: e8d2b4a6c1f0
Create Date: 2026-10-01

Every new column is nullable or defaulted, so the code that predates this
revision keeps working against the upgraded schema and the migration can run
before the deploy that reads it.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f4c9a2d71b30"
down_revision: str | None = "e8d2b4a6c1f0"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "bluebook_exams",
        sa.Column("questions_json", _JSON, server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "bluebook_exams",
        sa.Column("results_released_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "bluebook_submissions",
        sa.Column("answers_json", _JSON, server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column("bluebook_submissions", sa.Column("mark", sa.Text(), nullable=True))
    op.add_column("bluebook_submissions", sa.Column("feedback", sa.Text(), nullable=True))
    op.add_column(
        "bluebook_submissions",
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("bluebook_submissions", sa.Column("graded_by", sa.Text(), nullable=True))


def downgrade() -> None:
    for col in ("graded_by", "graded_at", "feedback", "mark", "answers_json"):
        op.drop_column("bluebook_submissions", col)
    op.drop_column("bluebook_exams", "results_released_at")
    op.drop_column("bluebook_exams", "questions_json")

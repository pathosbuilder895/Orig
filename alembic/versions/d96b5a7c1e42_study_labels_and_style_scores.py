"""study labels and server-side Original style scores

Revision ID: d96b5a7c1e42
Revises: a7d3c9e1b5f2
Create Date: 2026-10-13

Revision adds staff-only study labels and the report-only Original style
score captured for a sealed Collections submission. Student-facing
serializers intentionally do not include these columns.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d96b5a7c1e42"
down_revision: str | None = "a7d3c9e1b5f2"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("bluebook_submissions", sa.Column("study_label", sa.Text(), nullable=True))
    op.add_column(
        "bluebook_submissions",
        sa.Column("imitated_student_id", sa.Text(), nullable=True),
    )
    op.add_column("bluebook_submissions", sa.Column("style_score", sa.Float(), nullable=True))
    op.add_column(
        "bluebook_submissions",
        sa.Column(
            "style_features_json",
            _JSON,
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "bluebook_submissions",
        sa.Column("style_engine_version", sa.Text(), nullable=True),
    )
    op.add_column(
        "bluebook_submissions",
        sa.Column("style_threshold_version", sa.Text(), nullable=True),
    )
    op.add_column(
        "bluebook_submissions",
        sa.Column("style_scored_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    for column in (
        "style_scored_at",
        "style_threshold_version",
        "style_engine_version",
        "style_features_json",
        "style_score",
        "imitated_student_id",
        "study_label",
    ):
        op.drop_column("bluebook_submissions", column)

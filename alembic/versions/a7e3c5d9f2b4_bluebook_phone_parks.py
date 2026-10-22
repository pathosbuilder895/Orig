"""bluebook_phone_parks: a student's own parked phone for one collection

Additive only: one new table, nothing existing is altered. One row per
(exam, student) records that the student parked their phone for a sitting
of a collection with phone parking switched on (scanned from their own
briefing QR code, so it is tied to their account), whether the phone page is
still open, and any proctor override for a missing phone. Deleted with the
student's data on withdrawal.

Revision ID: a7e3c5d9f2b4
Revises: d4b8e2f6a1c3
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "a7e3c5d9f2b4"
down_revision: str | None = "d4b8e2f6a1c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bluebook_phone_parks",
        sa.Column("exam_id", sa.Text(), nullable=False),
        sa.Column("student_key", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), server_default="", nullable=False),
        sa.Column("parked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("override_by", sa.Text(), server_default="", nullable=False),
        sa.Column("override_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("override_note", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("exam_id", "student_key", name=op.f("pk_bluebook_phone_parks")),
    )


def downgrade() -> None:
    op.drop_table("bluebook_phone_parks")

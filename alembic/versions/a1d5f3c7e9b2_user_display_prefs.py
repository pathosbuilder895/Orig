"""user_display_prefs: each account's chosen text font and size

Additive only: one new table, nothing existing is altered. One row per
account (teacher or student) holds the display font and text size the
person picked in Settings, so the choice follows them to another device.
Display only: it never touches submitted text or anything measured.
Deleted with the student's data on withdrawal.

Revision ID: a1d5f3c7e9b2
Revises: b8f4d2a6c9e1
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "a1d5f3c7e9b2"
down_revision: str | None = "b8f4d2a6c9e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_display_prefs",
        sa.Column("account_key", sa.Text(), nullable=False),
        sa.Column("font", sa.Text(), server_default="serif", nullable=False),
        sa.Column("size", sa.Text(), server_default="default", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("account_key", name=op.f("pk_user_display_prefs")),
    )


def downgrade() -> None:
    op.drop_table("user_display_prefs")

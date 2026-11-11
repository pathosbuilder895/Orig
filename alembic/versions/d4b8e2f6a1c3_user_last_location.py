"""user_last_location: where each signed-in account last was, for resume

Additive only: one new table, nothing existing is altered. One row per
account (teacher or student) holds the screen, the selected item, the tab
and the scroll position, so signing in on another device can return there.
Visible only to its owner; deleted with the student's data on withdrawal.

Revision ID: d4b8e2f6a1c3
Revises: c9f2a4e6b8d1
Create Date: 2026-10-21
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "d4b8e2f6a1c3"
down_revision: str | None = "c9f2a4e6b8d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_last_location",
        sa.Column("account_key", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("screen", sa.Text(), nullable=False),
        sa.Column("entity_kind", sa.Text(), server_default="", nullable=False),
        sa.Column("entity_id", sa.Text(), server_default="", nullable=False),
        sa.Column("tab", sa.Text(), server_default="", nullable=False),
        sa.Column("scroll_fraction", sa.Float(), server_default="0", nullable=False),
        sa.Column("scroll_anchor", sa.Text(), server_default="", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("account_key", name=op.f("pk_user_last_location")),
    )


def downgrade() -> None:
    op.drop_table("user_last_location")

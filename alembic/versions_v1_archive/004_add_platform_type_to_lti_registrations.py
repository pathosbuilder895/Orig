"""Add platform_type to lti_registrations.

Revision ID: 004
Revises: 003
Create Date: 2026-04-10

Adds a platform_type column to lti_registrations so Original can normalise
LTI 1.3 claim differences between Canvas, Blackboard, and other LMS vendors.

Existing rows default to 'canvas' (backward-compatible).
"""

from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lti_registrations",
        sa.Column(
            "platform_type",
            sa.String(20),
            nullable=False,
            server_default="canvas",
        ),
    )
    op.create_index(
        "ix_lti_registrations_platform_type",
        "lti_registrations",
        ["platform_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_lti_registrations_platform_type", table_name="lti_registrations")
    op.drop_column("lti_registrations", "platform_type")

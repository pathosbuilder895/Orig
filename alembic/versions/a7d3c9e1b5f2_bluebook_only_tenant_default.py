"""Bluebook-only default for new tenant rows

Revision ID: a7d3c9e1b5f2
Revises: f4c9a2d71b30
Create Date: 2026-10-05

A tenants row inserted without a products list (the repository's placeholder
row for a write that names an unregistered tenant, for one) used to default to
both products, so a workspace could hold Original without an operator
switching it on. New rows now default to Bluebook only. Existing rows keep
whatever products they hold; the downgrade restores the old default.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "a7d3c9e1b5f2"
down_revision: str | None = "f4c9a2d71b30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("tenants", "products_json", server_default=sa.text("""'["bluebook"]'"""))


def downgrade() -> None:
    op.alter_column(
        "tenants", "products_json", server_default=sa.text("""'["original", "bluebook"]'""")
    )

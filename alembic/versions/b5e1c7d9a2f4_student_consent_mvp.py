"""Student consent MVP: consent_records, pilot_agreements, course original switch

Revision ID: b5e1c7d9a2f4
Revises: a7d3c9e1b5f2
Create Date: 2026-10-12

Append-only consent decisions (no IP, no user agent), the school/department
pilot agreement record that gates student invites, and the teacher's
per-course Original switch (off by default). See original/consent/policy.py.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b5e1c7d9a2f4"
down_revision: str | None = "a7d3c9e1b5f2"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "consent_records",
        sa.Column("record_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("student_id", sa.Text(), nullable=False),
        sa.Column("course_id", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("doc_version", sa.Text(), nullable=False),
        sa.Column("body_sha256", sa.Text(), nullable=False),
        sa.Column("typed_name", sa.Text(), server_default="", nullable=False),
        sa.Column("age_attested", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("record_id", name=op.f("pk_consent_records")),
    )
    op.create_index(
        "idx_consent_records_student",
        "consent_records",
        ["tenant_id", "student_id", "scope", "created_at"],
    )
    op.create_table(
        "pilot_agreements",
        sa.Column("agreement_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("entity_name", sa.Text(), nullable=False),
        sa.Column("signer_name", sa.Text(), nullable=False),
        sa.Column("signer_title", sa.Text(), server_default="", nullable=False),
        sa.Column("signer_email", sa.Text(), server_default="", nullable=False),
        sa.Column("doc_version", sa.Text(), nullable=False),
        sa.Column("doc_sha256", sa.Text(), nullable=False),
        sa.Column("signed_on", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "breach_contacts_json",
            _JSON,
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("agreement_id", name=op.f("pk_pilot_agreements")),
    )
    op.create_index("idx_pilot_agreements_tenant", "pilot_agreements", ["tenant_id", "recorded_at"])
    op.add_column(
        "bluebook_courses",
        sa.Column("original_enabled", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("bluebook_courses", "original_enabled")
    op.drop_index("idx_pilot_agreements_tenant", table_name="pilot_agreements")
    op.drop_table("pilot_agreements")
    op.drop_index("idx_consent_records_student", table_name="consent_records")
    op.drop_table("consent_records")

"""Canvas LTI 1.3 integration tables + data policy columns.

Revision ID: 003
Revises: 002
Create Date: 2026-03-19

Adds:
  - lti_registrations     Canvas LTI 1.3 platform registrations
  - lti_nonces            Short-lived OIDC replay-prevention nonces
  - canvas_submissions    Canvas submission pipeline tracking
  - institutions.data_policy_json  Per-institution data retention / indexing policy
  - students.external_id  Canvas cross-reference (already present from 001; no DDL here)
"""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── LTI Registrations ──────────────────────────────────────────────────────
    op.create_table(
        "lti_registrations",
        sa.Column("id",             sa.String(36),  nullable=False),
        sa.Column("platform_iss",   sa.String(255), nullable=False),
        sa.Column("client_id",      sa.String(255), nullable=False),
        sa.Column("deployment_id",  sa.String(255), nullable=True),
        sa.Column("auth_endpoint",  sa.String(500), nullable=False),
        sa.Column("jwks_url",       sa.String(500), nullable=False),
        sa.Column("api_token",      sa.String(500), nullable=True),
        sa.Column("institution_id", sa.String(36),  nullable=True),
        sa.Column("label",          sa.String(255), nullable=False, server_default="Canvas"),
        sa.Column("is_active",      sa.Boolean(),   nullable=False, server_default="true"),
        sa.Column("created_at",     sa.DateTime(),  server_default=sa.func.now()),
        sa.Column("updated_at",     sa.DateTime(),  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_lti_reg_iss",       "lti_registrations", ["platform_iss"])
    op.create_index("idx_lti_reg_client_id", "lti_registrations", ["client_id"])
    op.create_index("idx_lti_reg_active",    "lti_registrations", ["is_active"])

    # ── LTI Nonces ─────────────────────────────────────────────────────────────
    op.create_table(
        "lti_nonces",
        sa.Column("id",              sa.String(36), nullable=False),
        sa.Column("nonce",           sa.String(64), nullable=False),
        sa.Column("state",           sa.String(64), nullable=False),
        sa.Column("registration_id", sa.String(36), nullable=False),
        sa.Column("expires_at",      sa.Integer(),  nullable=False),
        sa.Column("created_at",      sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nonce"),
        sa.ForeignKeyConstraint(["registration_id"], ["lti_registrations.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_lti_nonce",           "lti_nonces", ["nonce"])
    op.create_index("idx_lti_nonce_reg",       "lti_nonces", ["registration_id"])

    # ── Canvas Submissions ──────────────────────────────────────────────────────
    op.create_table(
        "canvas_submissions",
        sa.Column("id",                    sa.String(36),  nullable=False),
        sa.Column("canvas_submission_id",  sa.String(255), nullable=False),
        sa.Column("canvas_assignment_id",  sa.String(255), nullable=False),
        sa.Column("canvas_course_id",      sa.String(255), nullable=False),
        sa.Column("canvas_user_id",        sa.String(255), nullable=False),
        sa.Column("submission_type",       sa.String(50),  nullable=False, server_default="online_text_entry"),
        sa.Column("canvas_url",            sa.String(500), nullable=True),
        sa.Column("access_token",          sa.String(500), nullable=True),
        sa.Column("original_submission_id",sa.String(36),  nullable=True),
        sa.Column("status",                sa.String(20),  nullable=False, server_default="pending"),
        sa.Column("report_posted_at",      sa.DateTime(),  nullable=True),
        sa.Column("error_message",         sa.String(500), nullable=True),
        sa.Column("created_at",            sa.DateTime(),  server_default=sa.func.now()),
        sa.Column("updated_at",            sa.DateTime(),  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canvas_submission_id"),
        sa.ForeignKeyConstraint(
            ["original_submission_id"], ["submissions.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("idx_canvas_sub_id",     "canvas_submissions", ["canvas_submission_id"])
    op.create_index("idx_canvas_sub_status", "canvas_submissions", ["status"])
    op.create_index("idx_canvas_sub_orig",   "canvas_submissions", ["original_submission_id"])

    # students.external_id is created in 001_initial_schema (required Canvas/LMS id).
    # Do not add it again here.

    # ── Add data_policy_json to institutions ────────────────────────────────────
    # Stored as JSON in the existing settings column — no new column needed.
    # The application reads/writes institution.settings["data_policy"].
    # This migration is a no-op for the column itself; recorded for audit trail.


def downgrade() -> None:
    op.drop_index("idx_canvas_sub_orig",   "canvas_submissions")
    op.drop_index("idx_canvas_sub_status", "canvas_submissions")
    op.drop_index("idx_canvas_sub_id",     "canvas_submissions")
    op.drop_table("canvas_submissions")

    op.drop_index("idx_lti_nonce_reg", "lti_nonces")
    op.drop_index("idx_lti_nonce",     "lti_nonces")
    op.drop_table("lti_nonces")

    op.drop_index("idx_lti_reg_active",    "lti_registrations")
    op.drop_index("idx_lti_reg_client_id", "lti_registrations")
    op.drop_index("idx_lti_reg_iss",       "lti_registrations")
    op.drop_table("lti_registrations")

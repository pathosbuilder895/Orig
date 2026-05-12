"""Add performance indexes for common query patterns.

Indexes added:
  submissions.submitted_at       — dashboard date-range filtering + sorting
  scoring_results.recommended_action — filter escalate/monitor/clear
  scoring_results.deviation_score   — flag high-risk submissions
  instructor_decisions.created_at   — audit log chronological ordering
  baseline_samples.submitted_at     — recency ordering in baseline matching
  refresh_tokens.expires_at         — expired-token cleanup job
  refresh_tokens.(user_id, revoked) — composite for logout-all active tokens

Revision ID: 007
Revises: 006
Create Date: 2026-05-09
"""

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # submissions — date-range queries and dashboard ordering
    op.create_index(
        "ix_submissions_submitted_at",
        "submissions",
        ["submitted_at"],
    )
    # scoring_results — filter by action and risk level
    op.create_index(
        "ix_scoring_results_recommended_action",
        "scoring_results",
        ["recommended_action"],
    )
    op.create_index(
        "ix_scoring_results_deviation_score",
        "scoring_results",
        ["deviation_score"],
    )
    # instructor_decisions — audit log ordering
    op.create_index(
        "ix_instructor_decisions_created_at",
        "instructor_decisions",
        ["created_at"],
    )
    # baseline_samples — recency sort for baseline matching
    op.create_index(
        "ix_baseline_samples_submitted_at",
        "baseline_samples",
        ["submitted_at"],
    )
    # refresh_tokens — expiry cleanup + active-session lookup
    op.create_index(
        "ix_refresh_tokens_expires_at",
        "refresh_tokens",
        ["expires_at"],
    )
    op.create_index(
        "ix_refresh_tokens_user_id_revoked",
        "refresh_tokens",
        ["user_id", "revoked"],
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_user_id_revoked", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_expires_at", table_name="refresh_tokens")
    op.drop_index("ix_baseline_samples_submitted_at", table_name="baseline_samples")
    op.drop_index("ix_instructor_decisions_created_at", table_name="instructor_decisions")
    op.drop_index("ix_scoring_results_deviation_score", table_name="scoring_results")
    op.drop_index("ix_scoring_results_recommended_action", table_name="scoring_results")
    op.drop_index("ix_submissions_submitted_at", table_name="submissions")

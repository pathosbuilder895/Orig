"""Initial schema creation.

Revision ID: 001
Revises:
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all initial tables."""

    # Institutions table
    op.create_table(
        "institutions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("subdomain", sa.String(100), nullable=False, unique=True),
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("subdomain"),
    )
    op.create_index("ix_institutions_subdomain", "institutions", ["subdomain"])
    op.create_index("ix_institutions_is_active", "institutions", ["is_active"])

    # Users table
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="instructor"),
        sa.Column("institution_id", sa.String(36), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_login", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_institution_id", "users", ["institution_id"])
    op.create_index("ix_users_is_active", "users", ["is_active"])

    # RefreshTokens table
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])
    op.create_index("ix_refresh_tokens_revoked", "refresh_tokens", ["revoked"])

    # Courses table
    op.create_table(
        "courses",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("institution_id", sa.String(36), nullable=False),
        sa.Column("instructor_id", sa.String(36), nullable=True),
        sa.Column("semester", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["instructor_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_courses_institution_id", "courses", ["institution_id"])
    op.create_index("ix_courses_instructor_id", "courses", ["instructor_id"])
    op.create_index("ix_courses_is_active", "courses", ["is_active"])

    # Students table
    op.create_table(
        "students",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("institution_id", sa.String(36), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id", "institution_id", name="uq_student_ext_id_inst"),
    )
    op.create_index("ix_students_external_id", "students", ["external_id"])
    op.create_index("ix_students_institution_id", "students", ["institution_id"])
    op.create_index("ix_students_is_active", "students", ["is_active"])

    # StudentEnrollments table
    op.create_table(
        "student_enrollments",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", "course_id", name="uq_enrollment"),
    )
    op.create_index("ix_student_enrollments_student_id", "student_enrollments", ["student_id"])
    op.create_index("ix_student_enrollments_course_id", "student_enrollments", ["course_id"])

    # BaselineSamples table
    op.create_table(
        "baseline_samples",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=True),
        sa.Column("assignment", sa.String(255), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("feature_vector", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.String(20), nullable=False, server_default="verified"),
        sa.Column("auth_weight", sa.Float(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("added_by_id", sa.String(36), nullable=True),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["added_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("text_hash"),
    )
    op.create_index("ix_baseline_samples_student_id", "baseline_samples", ["student_id"])
    op.create_index("ix_baseline_samples_text_hash", "baseline_samples", ["text_hash"])
    op.create_index("ix_baseline_samples_provenance", "baseline_samples", ["provenance"])
    op.create_index("ix_baseline_samples_is_active", "baseline_samples", ["is_active"])

    # Submissions table
    op.create_table(
        "submissions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=True),   # optional — not all submissions are course-linked
        sa.Column("assignment", sa.String(255), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("text_hash"),
    )
    op.create_index("ix_submissions_student_id", "submissions", ["student_id"])
    op.create_index("ix_submissions_course_id", "submissions", ["course_id"])
    op.create_index("ix_submissions_text_hash", "submissions", ["text_hash"])
    op.create_index("ix_submissions_status", "submissions", ["status"])
    op.create_index(
        "ix_submissions_student_course_assignment",
        "submissions",
        ["student_id", "course_id", "assignment"],
    )

    # ScoringResults table
    op.create_table(
        "scoring_results",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("submission_id", sa.String(36), nullable=False, unique=True),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("deviation_score", sa.Float(), nullable=False),
        sa.Column("authorship_probability", sa.Float(), nullable=False),
        sa.Column("recommended_action", sa.String(50), nullable=False),
        sa.Column("baseline_confidence", sa.JSON(), nullable=False),
        sa.Column("full_result", sa.JSON(), nullable=False),
        sa.Column("feature_vector", sa.JSON(), nullable=False),
        sa.Column("scored_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id"),
    )
    op.create_index("ix_scoring_results_submission_id", "scoring_results", ["submission_id"])

    # InstructorDecisions table (immutable)
    op.create_table(
        "instructor_decisions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("submission_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("notes", sa.String(2000), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_instructor_decisions_submission_id", "instructor_decisions", ["submission_id"])
    op.create_index("ix_instructor_decisions_action", "instructor_decisions", ["action"])


def downgrade() -> None:
    """Drop all tables."""

    op.drop_index("ix_instructor_decisions_action", table_name="instructor_decisions")
    op.drop_index("ix_instructor_decisions_submission_id", table_name="instructor_decisions")
    op.drop_table("instructor_decisions")

    op.drop_index("ix_scoring_results_submission_id", table_name="scoring_results")
    op.drop_table("scoring_results")

    op.drop_index("ix_submissions_student_course_assignment", table_name="submissions")
    op.drop_index("ix_submissions_status", table_name="submissions")
    op.drop_index("ix_submissions_text_hash", table_name="submissions")
    op.drop_index("ix_submissions_course_id", table_name="submissions")
    op.drop_index("ix_submissions_student_id", table_name="submissions")
    op.drop_table("submissions")

    op.drop_index("ix_baseline_samples_is_active", table_name="baseline_samples")
    op.drop_index("ix_baseline_samples_provenance", table_name="baseline_samples")
    op.drop_index("ix_baseline_samples_text_hash", table_name="baseline_samples")
    op.drop_index("ix_baseline_samples_student_id", table_name="baseline_samples")
    op.drop_table("baseline_samples")

    op.drop_index("ix_student_enrollments_course_id", table_name="student_enrollments")
    op.drop_index("ix_student_enrollments_student_id", table_name="student_enrollments")
    op.drop_table("student_enrollments")

    op.drop_index("ix_students_is_active", table_name="students")
    op.drop_index("ix_students_institution_id", table_name="students")
    op.drop_index("ix_students_external_id", table_name="students")
    op.drop_table("students")

    op.drop_index("ix_courses_is_active", table_name="courses")
    op.drop_index("ix_courses_instructor_id", table_name="courses")
    op.drop_index("ix_courses_institution_id", table_name="courses")
    op.drop_table("courses")

    op.drop_index("ix_refresh_tokens_revoked", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index("ix_users_is_active", table_name="users")
    op.drop_index("ix_users_institution_id", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_institutions_is_active", table_name="institutions")
    op.drop_index("ix_institutions_subdomain", table_name="institutions")
    op.drop_table("institutions")

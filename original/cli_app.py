"""
cli.py — Command-line management interface for Original.

Usage:
    python -m original.cli <command> [options]

Commands:
    create-admin       Create an administrator account
    list-users         List all users (optionally filter by institution)
    rebuild-baselines  Re-extract features for all baseline samples that have raw_text stored

All configuration is read from environment variables / .env, exactly
the same as the running API.  No config flags needed.

Examples
--------
    # Minimal — reads FIRST_ADMIN_EMAIL / FIRST_ADMIN_PASSWORD from env
    python -m original.cli create-admin

    # Override inline
    ADMIN_EMAIL=alice@seminary.edu ADMIN_PASSWORD=S3cr3t! \\
        python -m original.cli create-admin

    # List users
    python -m original.cli list-users
"""

from __future__ import annotations

import argparse
import os
import sys


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_db_session():
    """Return a raw SQLAlchemy Session connected to the configured database."""
    from original.db.session import SessionLocal, init_db

    init_db()
    return SessionLocal()


def _print_ok(msg: str) -> None:
    print(f"\033[32m✓\033[0m  {msg}")


def _print_err(msg: str) -> None:
    print(f"\033[31m✗\033[0m  {msg}", file=sys.stderr)


# ── Commands ───────────────────────────────────────────────────────────────────

def cmd_create_admin(args: argparse.Namespace) -> int:
    """
    Create an admin user.

    Email / password are read from (in priority order):
      1. --email / --password CLI flags
      2. ADMIN_EMAIL / ADMIN_PASSWORD environment variables
      3. FIRST_ADMIN_EMAIL / FIRST_ADMIN_PASSWORD from Settings
    """
    from original.auth.password import hash_password, validate_password_strength
    from original.core.config import get_settings
    from original.db.models import Institution, User, UserRole

    settings = get_settings()

    email = (
        args.email
        or os.environ.get("ADMIN_EMAIL")
        or settings.FIRST_ADMIN_EMAIL
    )
    password = (
        args.password
        or os.environ.get("ADMIN_PASSWORD")
        or settings.FIRST_ADMIN_PASSWORD
    )
    institution_name = args.institution or "Default Seminary"

    # Validate password strength before touching the DB
    try:
        validate_password_strength(password)
    except ValueError as exc:
        _print_err(f"Weak password: {exc}")
        return 1

    db = _get_db_session()
    try:
        # Check for duplicate
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            _print_err(f"User '{email}' already exists (id={existing.id}).")
            _print_err("Use --email to specify a different address.")
            return 1

        # Ensure institution exists
        institution = (
            db.query(Institution)
            .filter(Institution.name == institution_name)
            .first()
        )
        if not institution:
            subdomain = institution_name.lower().replace(" ", "-")
            institution = Institution(name=institution_name, subdomain=subdomain)
            db.add(institution)
            db.flush()
            _print_ok(f"Created institution '{institution_name}'")

        # Create admin user
        admin = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=args.full_name or "Administrator",
            role=UserRole.ADMIN,
            institution_id=institution.id,
            is_active=True,
        )
        db.add(admin)
        db.commit()

        _print_ok(f"Admin created: {email} (institution: {institution_name})")
        return 0

    except Exception as exc:
        db.rollback()
        _print_err(f"Failed to create admin: {exc}")
        return 1

    finally:
        db.close()


def cmd_list_users(args: argparse.Namespace) -> int:
    """Print a table of all users."""
    from original.db.models import User

    db = _get_db_session()
    try:
        query = db.query(User)
        if args.institution:
            from original.db.models import Institution

            inst = (
                db.query(Institution)
                .filter(Institution.name.ilike(f"%{args.institution}%"))
                .first()
            )
            if inst:
                query = query.filter(User.institution_id == inst.id)

        users = query.order_by(User.email).all()
        if not users:
            print("No users found.")
            return 0

        fmt = "{:<36}  {:<30}  {:<12}  {}"
        print(fmt.format("ID", "Email", "Role", "Active"))
        print("-" * 90)
        for u in users:
            role = u.role.value if hasattr(u.role, "value") else str(u.role)
            print(fmt.format(u.id, u.email, role, "yes" if u.is_active else "no"))

        return 0

    finally:
        db.close()


def cmd_rebuild_baselines(args: argparse.Namespace) -> int:
    """
    Re-extract features for every active baseline sample that has raw_text stored.

    Use this after updating the feature extraction pipeline (tier1/tier2/tier3)
    to ensure all stored feature_vectors are consistent with the current extractor
    version.  Samples without raw_text (submitted before migration 002) are
    skipped and counted in the 'skipped' total.

    Options
    -------
    --student-id   Rebuild only for a specific student (UUID)
    --dry-run      Print what would be updated, but write nothing to the DB
    """
    from original.core.config import get_settings
    from original.db.models import BaselineSample
    from original.features.pipeline import extract_features

    settings = get_settings()
    db = _get_db_session()

    try:
        query = db.query(BaselineSample).filter(BaselineSample.is_active == True)  # noqa: E712

        if args.student_id:
            query = query.filter(BaselineSample.student_id == args.student_id)
            print(f"Filtering to student {args.student_id}")

        samples = query.order_by(BaselineSample.created_at).all()

        total = len(samples)
        rebuilt = 0
        skipped = 0
        errors = 0

        print(f"Found {total} active baseline sample(s) to inspect.")
        if args.dry_run:
            print("DRY RUN — no changes will be written.\n")

        for sample in samples:
            if not sample.raw_text:
                skipped += 1
                if args.verbose:
                    print(f"  SKIP  {sample.id[:8]}… (no raw_text stored)")
                continue

            try:
                new_features = extract_features(sample.raw_text)

                if args.dry_run:
                    print(
                        f"  WOULD UPDATE  {sample.id[:8]}…  "
                        f"student={sample.student_id[:8]}…  "
                        f"assignment={sample.assignment}"
                    )
                    rebuilt += 1
                    continue

                sample.feature_vector = new_features
                sample.model_version = settings.MODEL_VERSION
                rebuilt += 1

                if args.verbose:
                    print(
                        f"  REBUILT  {sample.id[:8]}…  "
                        f"student={sample.student_id[:8]}…  "
                        f"assignment={sample.assignment}"
                    )

            except Exception as exc:
                errors += 1
                _print_err(
                    f"  ERROR  {sample.id[:8]}… — {exc}"
                )

        if not args.dry_run and rebuilt > 0:
            db.commit()

        print()
        _print_ok(f"Rebuilt : {rebuilt}")
        if skipped:
            print(f"   Skipped (no raw_text) : {skipped}")
        if errors:
            _print_err(f"Errors : {errors}")

        if skipped:
            print(
                "\n  ℹ  Skipped samples were submitted before migration 002\n"
                "     and cannot be rebuilt without their original text.\n"
                "     Ask instructors to re-submit those baseline samples."
            )

        return 0 if errors == 0 else 1

    except Exception as exc:
        db.rollback()
        _print_err(f"rebuild-baselines failed: {exc}")
        return 1

    finally:
        db.close()


# ── Argument parser ────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m original.cli",
        description="Original management CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # create-admin
    p_admin = sub.add_parser("create-admin", help="Create an administrator account")
    p_admin.add_argument("--email", help="Admin email (overrides env / settings)")
    p_admin.add_argument("--password", help="Admin password (overrides env / settings)")
    p_admin.add_argument("--full-name", dest="full_name", default="Administrator")
    p_admin.add_argument(
        "--institution",
        default=None,
        help="Institution name (created if it does not exist)",
    )

    # list-users
    p_list = sub.add_parser("list-users", help="List all users")
    p_list.add_argument(
        "--institution",
        default=None,
        help="Filter by institution name (partial match)",
    )

    # rebuild-baselines
    p_rebuild = sub.add_parser(
        "rebuild-baselines",
        help="Re-extract features for baseline samples (run after extractor changes)",
    )
    p_rebuild.add_argument(
        "--student-id",
        dest="student_id",
        default=None,
        help="Limit rebuild to a single student UUID",
    )
    p_rebuild.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Preview what would be rebuilt without writing to the DB",
    )
    p_rebuild.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Print one line per sample processed",
    )

    return parser


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "create-admin": cmd_create_admin,
        "list-users": cmd_list_users,
        "rebuild-baselines": cmd_rebuild_baselines,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    sys.exit(handler(args))


if __name__ == "__main__":
    main()

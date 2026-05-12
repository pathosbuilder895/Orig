"""
original/cli/security_audit.py — Self-audit script for security configuration.

Performs automated security checks including:
- JWT token configuration (expiry, secret strength)
- Raw SQL detection (injection vulnerability scanning)
- Rate limiting configuration
- Input validation
- RBAC middleware verification
- pip audit (if available)

Usage:
    python -m original.cli.security_audit [--fix] [--verbose]

Options:
    --fix       Attempt to auto-fix identified issues (where safe)
    --verbose   Show detailed output for each check
    --exit-code Return non-zero exit code if issues found

Example:
    python -m original.cli.security_audit --verbose
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from original.auth.jwt import TokenData
from original.core.config import get_settings
from original.core.logging import get_logger

log = get_logger(__name__)


class SecurityAudit:
    """Performs security audits on the Original codebase."""

    def __init__(self, verbose: bool = False, fix: bool = False):
        self.verbose = verbose
        self.fix = fix
        self.issues: list[str] = []
        self.warnings: list[str] = []
        self.passes: list[str] = []

    def _print_header(self, title: str) -> None:
        """Print section header."""
        print(f"\n{'=' * 60}")
        print(f"  {title}")
        print(f"{'=' * 60}")

    def _print_ok(self, msg: str) -> None:
        """Print a pass message."""
        print(f"\033[32m✓\033[0m  {msg}")
        self.passes.append(msg)

    def _print_warn(self, msg: str) -> None:
        """Print a warning message."""
        print(f"\033[33m!\033[0m  {msg}")
        self.warnings.append(msg)

    def _print_err(self, msg: str) -> None:
        """Print an error message."""
        print(f"\033[31m✗\033[0m  {msg}")
        self.issues.append(msg)

    def _print_info(self, msg: str) -> None:
        """Print an info message."""
        if self.verbose:
            print(f"\033[36mℹ\033[0m  {msg}")

    # ── JWT Configuration ────────────────────────────────────────────────────────

    def check_jwt_config(self) -> None:
        """Check JWT token configuration."""
        self._print_header("JWT Token Configuration")

        settings = get_settings()

        # Check access token expiry
        if settings.ACCESS_TOKEN_EXPIRE_MINUTES < 5:
            self._print_warn(
                f"Access token expiry is very short: {settings.ACCESS_TOKEN_EXPIRE_MINUTES} min"
            )
        elif settings.ACCESS_TOKEN_EXPIRE_MINUTES > 60:
            self._print_warn(
                f"Access token expiry is very long: {settings.ACCESS_TOKEN_EXPIRE_MINUTES} min "
                "(recommended < 60)"
            )
        else:
            self._print_ok(
                f"Access token expiry is reasonable: {settings.ACCESS_TOKEN_EXPIRE_MINUTES} min"
            )

        # Check refresh token expiry
        if settings.REFRESH_TOKEN_EXPIRE_DAYS > 30:
            self._print_warn(
                f"Refresh token expiry is very long: {settings.REFRESH_TOKEN_EXPIRE_DAYS} days "
                "(recommended <= 30)"
            )
        else:
            self._print_ok(
                f"Refresh token expiry is reasonable: {settings.REFRESH_TOKEN_EXPIRE_DAYS} days"
            )

        # Check secret key strength
        if len(settings.SECRET_KEY) < 32:
            self._print_err(
                f"SECRET_KEY is too short: {len(settings.SECRET_KEY)} chars (min 32)"
            )
        else:
            self._print_ok(f"SECRET_KEY is strong: {len(settings.SECRET_KEY)} chars")

        # Check algorithm
        if settings.ALGORITHM != "HS256":
            self._print_warn(f"JWT algorithm is {settings.ALGORITHM} (HS256 recommended)")
        else:
            self._print_ok("JWT algorithm is HS256")

    # ── Raw SQL Detection ────────────────────────────────────────────────────────

    def check_raw_sql(self) -> None:
        """Scan codebase for raw SQL patterns (SQL injection risk)."""
        self._print_header("Raw SQL Detection")

        repo_root = Path(__file__).parent.parent.parent
        py_files = list(repo_root.glob("**/*.py"))

        self._print_info(f"Scanning {len(py_files)} Python files for raw SQL...")

        sql_patterns = [
            r"\.execute\s*\(\s*['\"]",  # .execute("SELECT ...")
            r"text\s*\(\s*['\"].*SELECT",  # text("SELECT ...")
            r"\.query\s*\(\s*text\s*\(\s*['\"]",  # .query(text("..."))
        ]

        issues_found = []

        for py_file in py_files:
            try:
                content = py_file.read_text(encoding="utf-8")

                # Skip test files
                if "/test" in str(py_file) or py_file.name.startswith("test_"):
                    continue

                for pattern in sql_patterns:
                    matches = re.finditer(pattern, content)
                    for match in matches:
                        # Check if it's commented out
                        line_num = content[: match.start()].count("\n") + 1
                        line = content.split("\n")[line_num - 1]

                        if not line.strip().startswith("#"):
                            issues_found.append(
                                f"{py_file.relative_to(repo_root)}:{line_num} — {line.strip()}"
                            )

            except (UnicodeDecodeError, Exception):
                continue

        if issues_found:
            self._print_err(f"Found {len(issues_found)} potential raw SQL usage(s):")
            for issue in issues_found:
                self._print_info(f"  {issue}")
        else:
            self._print_ok("No obvious raw SQL patterns detected")

    # ── Rate Limiting ────────────────────────────────────────────────────────────

    def check_rate_limiting(self) -> None:
        """Check rate limiting configuration."""
        self._print_header("Rate Limiting Configuration")

        settings = get_settings()

        # Check default rate limit
        self._print_info(f"Default rate limit: {settings.RATE_LIMIT_DEFAULT}")
        if "60/minute" in settings.RATE_LIMIT_DEFAULT:
            self._print_ok("Default rate limit is reasonable (60/minute)")
        else:
            self._print_warn(f"Default rate limit is {settings.RATE_LIMIT_DEFAULT}")

        # Check auth rate limit
        self._print_info(f"Auth rate limit: {settings.RATE_LIMIT_AUTH}")
        if "5/minute" in settings.RATE_LIMIT_AUTH:
            self._print_ok("Auth rate limit is strict (5/minute)")
        elif int(settings.RATE_LIMIT_AUTH.split("/")[0]) <= 10:
            self._print_ok("Auth rate limit is reasonable")
        else:
            self._print_warn("Auth rate limit is very permissive (allows brute force)")

        # Check scoring rate limit
        self._print_info(f"Scoring rate limit: {settings.RATE_LIMIT_SCORING}")
        if int(settings.RATE_LIMIT_SCORING.split("/")[0]) <= 10:
            self._print_ok("Scoring rate limit is strict (prevents abuse)")

    # ── Input Validation ─────────────────────────────────────────────────────────

    def check_input_validation(self) -> None:
        """Check for input validation in schemas and models."""
        self._print_header("Input Validation")

        repo_root = Path(__file__).parent.parent.parent

        # Check schemas
        schemas_dir = repo_root / "original" / "schemas_v1"
        if schemas_dir.exists():
            schema_files = list(schemas_dir.glob("*.py"))
            self._print_info(f"Found {len(schema_files)} schema files")

            has_validators = False
            for schema_file in schema_files:
                content = schema_file.read_text()
                if "field_validator" in content or "validator" in content:
                    has_validators = True
                    break

            if has_validators:
                self._print_ok("Pydantic validators found in schemas")
            else:
                self._print_warn("No obvious input validators found in schemas")
        else:
            self._print_warn("schemas_v1 directory not found")

    # ── RBAC Middleware ──────────────────────────────────────────────────────────

    def check_rbac_middleware(self) -> None:
        """Check for RBAC middleware implementation."""
        self._print_header("RBAC Middleware")

        repo_root = Path(__file__).parent.parent.parent
        middleware_dir = repo_root / "original" / "middleware"

        if middleware_dir.exists():
            rbac_file = middleware_dir / "rbac.py"
            if rbac_file.exists():
                self._print_ok("RBAC middleware file exists (original/middleware/rbac.py)")
            else:
                self._print_warn("RBAC middleware not yet implemented")
        else:
            self._print_warn("Middleware directory not found (original/middleware/)")

        # Check auth middleware in main.py or api.py
        api_file = repo_root / "original" / "api.py"
        if api_file.exists():
            content = api_file.read_text()
            if "middleware" in content.lower() or "depend" in content.lower():
                self._print_ok("Auth/dependency injection found in API")

    # ── pip audit ────────────────────────────────────────────────────────────────

    def check_pip_audit(self) -> None:
        """Run pip audit to check for known vulnerabilities."""
        self._print_header("Dependency Vulnerabilities (pip audit)")

        try:
            result = subprocess.run(
                ["pip", "audit", "--format", "json"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                self._print_ok("No known vulnerabilities in dependencies")
            else:
                # Parse pip audit output
                output = result.stdout
                if "vulnerable" in output.lower() or result.returncode > 0:
                    self._print_warn("pip audit found potential vulnerabilities")
                    self._print_info("Run 'pip audit' for details")

        except FileNotFoundError:
            self._print_warn("pip audit not installed. Run: pip install pip-audit")
        except subprocess.TimeoutExpired:
            self._print_warn("pip audit timed out")
        except Exception as e:
            self._print_warn(f"pip audit check failed: {e}")

    # ── HTTPS/TLS Readiness ──────────────────────────────────────────────────────

    def check_tls_readiness(self) -> None:
        """Check TLS/HTTPS configuration."""
        self._print_header("TLS/HTTPS Readiness")

        settings = get_settings()

        # Check if HTTPS is enforced
        if settings.ENVIRONMENT == "production":
            if settings.ORIGINAL_BASE_URL.startswith("https://"):
                self._print_ok("Production base URL is HTTPS")
            else:
                self._print_err(f"Production base URL is not HTTPS: {settings.ORIGINAL_BASE_URL}")

            # Check DEBUG mode
            if settings.DEBUG:
                self._print_err("DEBUG mode is enabled in production!")
            else:
                self._print_ok("DEBUG mode is disabled")

        else:
            self._print_ok(f"Environment is {settings.ENVIRONMENT} (non-production)")

    # ── Database Security ────────────────────────────────────────────────────────

    def check_database_security(self) -> None:
        """Check database connection security."""
        self._print_header("Database Connection Security")

        settings = get_settings()

        # Check database URL
        db_url = settings.DATABASE_URL
        if "sqlite://" in db_url:
            if settings.ENVIRONMENT == "production":
                self._print_err("SQLite detected in production (use PostgreSQL)")
            else:
                self._print_ok("SQLite used in development")
        elif "postgresql://" in db_url:
            self._print_ok("PostgreSQL detected")

            # Check for SSL
            if "sslmode=" in db_url:
                self._print_ok("SSL/TLS configured for database connection")
            elif settings.ENVIRONMENT == "production":
                self._print_warn("SSL/TLS not explicitly configured in DATABASE_URL")
        else:
            self._print_warn(f"Unknown database type: {db_url[:30]}...")

    # ── CORS Configuration ───────────────────────────────────────────────────────

    def check_cors_configuration(self) -> None:
        """Check CORS (Cross-Origin Resource Sharing) configuration."""
        self._print_header("CORS Configuration")

        settings = get_settings()

        origins = settings.ALLOWED_ORIGINS
        self._print_info(f"Allowed CORS origins: {origins}")

        if "*" in origins:
            self._print_err("CORS is configured to allow all origins (*)")
        elif "localhost" in str(origins) and settings.ENVIRONMENT == "production":
            self._print_warn("localhost allowed in production CORS origins")
        else:
            self._print_ok("CORS origins are restricted")

    # ── Overall Summary ──────────────────────────────────────────────────────────

    def print_summary(self) -> None:
        """Print audit summary."""
        print(f"\n{'=' * 60}")
        print("  SECURITY AUDIT SUMMARY")
        print(f"{'=' * 60}")

        print(f"\n\033[32m✓ Passes:   {len(self.passes)}\033[0m")
        print(f"\033[33m! Warnings: {len(self.warnings)}\033[0m")
        print(f"\033[31m✗ Issues:   {len(self.issues)}\033[0m")

        if self.issues:
            print("\n\033[31m[ISSUES]\033[0m")
            for issue in self.issues:
                print(f"  - {issue}")

        if self.warnings:
            print("\n\033[33m[WARNINGS]\033[0m")
            for warning in self.warnings:
                print(f"  - {warning}")

        print()

    def run_all_checks(self) -> int:
        """Run all security checks."""
        try:
            self.check_jwt_config()
            self.check_raw_sql()
            self.check_rate_limiting()
            self.check_input_validation()
            self.check_rbac_middleware()
            self.check_pip_audit()
            self.check_tls_readiness()
            self.check_database_security()
            self.check_cors_configuration()

            self.print_summary()

            if self.issues:
                log.warning(f"Security audit found {len(self.issues)} issue(s)")
                return 1

            if self.warnings:
                log.info(f"Security audit completed with {len(self.warnings)} warning(s)")
                return 0

            log.info("Security audit completed successfully")
            return 0

        except Exception as e:
            print(f"\n\033[31m✗ Audit failed: {e}\033[0m")
            log.exception("Security audit failed")
            return 1


def main(args: Optional[list[str]] = None) -> int:
    """
    Main entry point for the security audit CLI command.

    Args:
        args: Command-line arguments (if None, uses sys.argv[1:])

    Returns:
        0 on success, 1 on failure or if issues found
    """
    parser = argparse.ArgumentParser(
        prog="original-security-audit",
        description="Run a self-audit of Original's security configuration.",
        epilog="Example: python -m original.cli.security_audit --verbose",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output for each check",
    )

    parser.add_argument(
        "--fix",
        action="store_true",
        help="Attempt to auto-fix identified issues (where safe)",
    )

    parser.add_argument(
        "--exit-code",
        action="store_true",
        help="Return non-zero exit code if issues found",
    )

    parsed_args = parser.parse_args(args)

    audit = SecurityAudit(verbose=parsed_args.verbose, fix=parsed_args.fix)
    return audit.run_all_checks()


if __name__ == "__main__":
    sys.exit(main())

#!/bin/bash

################################################################################
# Original Security Testing Script — OWASP ZAP Integration
#
# This script sets up and runs OWASP ZAP security scans against the Original API.
#
# Usage:
#   ./deploy/security_test.sh [options]
#
# Options:
#   --help              Show this help message
#   --install           Install OWASP ZAP (if not already installed)
#   --target URL        Target URL (default: http://localhost:8000)
#   --report FILE       Output report file (default: zap-report.html)
#   --api-key KEY       ZAP API key (for authentication)
#   --baseline          Run baseline scan only (faster)
#   --full              Run full scan (slower, more thorough)
#   --check-config      Check configuration and exit
#
# Examples:
#   # Check if ZAP is installed
#   ./deploy/security_test.sh --check-config
#
#   # Install ZAP
#   ./deploy/security_test.sh --install
#
#   # Run baseline scan against local API
#   ./deploy/security_test.sh --baseline --target http://localhost:8000
#
#   # Run full scan and save to custom report
#   ./deploy/security_test.sh --full --target https://api.original.edu --report security-report.html
#
################################################################################

set -e

# ────────────────────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$SCRIPT_DIR/security_test_config.yaml"

# Defaults
TARGET_URL="http://localhost:8000"
REPORT_FILE="${SCRIPT_DIR}/zap-report.html"
SCAN_TYPE="baseline"  # baseline or full
INSTALL_ZAP=false
CHECK_CONFIG=false
API_KEY=""

# OWASP ZAP paths
ZAP_HOME="${ZAP_HOME:-$HOME/.zaproxy}"
ZAP_BIN=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;36m'
NC='\033[0m' # No Color

# ────────────────────────────────────────────────────────────────────────────
# Functions
# ────────────────────────────────────────────────────────────────────────────

print_header() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_ok() {
    echo -e "${GREEN}✓${NC}  $1"
}

print_err() {
    echo -e "${RED}✗${NC}  $1" >&2
}

print_warn() {
    echo -e "${YELLOW}!${NC}  $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC}  $1"
}

show_help() {
    head -n 40 "$0" | tail -n +2
}

# ────────────────────────────────────────────────────────────────────────────
# Parse Command-Line Arguments
# ────────────────────────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            show_help
            exit 0
            ;;
        --install)
            INSTALL_ZAP=true
            shift
            ;;
        --target)
            TARGET_URL="$2"
            shift 2
            ;;
        --report)
            REPORT_FILE="$2"
            shift 2
            ;;
        --api-key)
            API_KEY="$2"
            shift 2
            ;;
        --baseline)
            SCAN_TYPE="baseline"
            shift
            ;;
        --full)
            SCAN_TYPE="full"
            shift
            ;;
        --check-config)
            CHECK_CONFIG=true
            shift
            ;;
        *)
            print_err "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# ────────────────────────────────────────────────────────────────────────────
# Detect OWASP ZAP Installation
# ────────────────────────────────────────────────────────────────────────────

detect_zap() {
    # Check common installation paths
    if command -v zaproxy &> /dev/null; then
        ZAP_BIN="zaproxy"
    elif [ -f "/Applications/OWASP ZAP.app/Contents/MacOS/OWASP ZAP" ]; then
        ZAP_BIN="/Applications/OWASP ZAP.app/Contents/MacOS/OWASP ZAP"
    elif [ -f "$ZAP_HOME/zaproxy" ]; then
        ZAP_BIN="$ZAP_HOME/zaproxy"
    elif [ -f "/usr/bin/zaproxy" ]; then
        ZAP_BIN="/usr/bin/zaproxy"
    fi

    if [ -z "$ZAP_BIN" ]; then
        return 1
    fi
    return 0
}

# ────────────────────────────────────────────────────────────────────────────
# Install OWASP ZAP
# ────────────────────────────────────────────────────────────────────────────

install_zap() {
    print_header "Installing OWASP ZAP"

    OS_TYPE=$(uname -s)

    if [ "$OS_TYPE" == "Darwin" ]; then
        # macOS installation via Homebrew
        print_info "Detected macOS. Installing via Homebrew..."
        if ! command -v brew &> /dev/null; then
            print_err "Homebrew not found. Please install Homebrew first."
            exit 1
        fi
        brew install owasp-zap
    elif [ "$OS_TYPE" == "Linux" ]; then
        # Linux installation (Ubuntu/Debian)
        print_info "Detected Linux. Installing via apt..."
        if command -v apt-get &> /dev/null; then
            sudo apt-get update
            sudo apt-get install -y zaproxy
        else
            print_err "apt-get not found. Please install OWASP ZAP manually."
            exit 1
        fi
    else
        print_err "Unsupported OS. Please install OWASP ZAP manually from https://www.zaproxy.org/"
        exit 1
    fi

    print_ok "OWASP ZAP installed successfully"
    detect_zap
}

# ────────────────────────────────────────────────────────────────────────────
# Check Configuration
# ────────────────────────────────────────────────────────────────────────────

check_configuration() {
    print_header "Security Testing Configuration"

    # Check if ZAP is installed
    if ! detect_zap; then
        print_warn "OWASP ZAP not detected"
        print_info "Install ZAP with: $0 --install"
        return 1
    else
        print_ok "OWASP ZAP found: $ZAP_BIN"
    fi

    # Check if config file exists
    if [ -f "$CONFIG_FILE" ]; then
        print_ok "Security config file found: $CONFIG_FILE"
    else
        print_warn "Security config file not found: $CONFIG_FILE"
    fi

    # Check if target is reachable
    print_info "Testing target availability..."
    if curl -s -f -m 5 "$TARGET_URL/health" > /dev/null 2>&1; then
        print_ok "Target is reachable: $TARGET_URL"
    else
        print_warn "Target may not be reachable: $TARGET_URL"
        print_info "Ensure the API is running before running security tests"
    fi

    # Check for Python (required for some ZAP scripts)
    if command -v python3 &> /dev/null; then
        print_ok "Python 3 found: $(python3 --version)"
    else
        print_warn "Python 3 not found (optional)"
    fi

    # Show test configuration
    echo ""
    print_info "Test Configuration:"
    echo "  Target URL:      $TARGET_URL"
    echo "  Scan Type:       $SCAN_TYPE"
    echo "  Report File:     $REPORT_FILE"
    echo "  ZAP Binary:      $ZAP_BIN"
    echo "  Config File:     $CONFIG_FILE"
    echo ""

    return 0
}

# ────────────────────────────────────────────────────────────────────────────
# Common API Endpoints to Test
# ────────────────────────────────────────────────────────────────────────────

get_api_endpoints() {
    cat << 'EOF'
# Original API Endpoints for Security Testing

## Authentication Endpoints
/api/v1/auth/login
/api/v1/auth/refresh
/api/v1/auth/logout

## Student Endpoints
/api/v1/students/me
/api/v1/students/{student_id}

## Submission Endpoints
/api/v1/submissions
/api/v1/submissions/{submission_id}
/api/v1/submissions/{submission_id}/score

## Baseline Endpoints
/api/v1/baselines
/api/v1/baselines/{baseline_id}

## Course Endpoints
/api/v1/courses
/api/v1/courses/{course_id}

## Admin Endpoints
/api/v1/admin/users
/api/v1/admin/institutions
/api/v1/admin/settings

## Health/Status
/health
/metrics
/api/v1/status
EOF
}

# ────────────────────────────────────────────────────────────────────────────
# Run ZAP Baseline Scan
# ────────────────────────────────────────────────────────────────────────────

run_baseline_scan() {
    print_header "Running OWASP ZAP Baseline Scan"

    if ! detect_zap; then
        print_err "OWASP ZAP not found. Install with: $0 --install"
        return 1
    fi

    print_info "Target URL: $TARGET_URL"
    print_info "This scan checks for common web vulnerabilities (10-30 minutes)"

    # Run ZAP baseline scan
    "$ZAP_BIN" \
        -cmd \
        -quickurl "$TARGET_URL" \
        -quickout "$REPORT_FILE" \
        2>&1 | tee "${REPORT_FILE%.html}.log"

    if [ $? -eq 0 ]; then
        print_ok "Baseline scan completed"
        print_info "Report saved to: $REPORT_FILE"
    else
        print_warn "Baseline scan completed with warnings"
    fi
}

# ────────────────────────────────────────────────────────────────────────────
# Run ZAP Full Scan
# ────────────────────────────────────────────────────────────────────────────

run_full_scan() {
    print_header "Running OWASP ZAP Full Scan"

    if ! detect_zap; then
        print_err "OWASP ZAP not found. Install with: $0 --install"
        return 1
    fi

    print_warn "Full scan is time-consuming (1-3 hours)"
    print_info "Target URL: $TARGET_URL"

    # Run ZAP full scan with config
    if [ -f "$CONFIG_FILE" ]; then
        print_info "Using config file: $CONFIG_FILE"
        "$ZAP_BIN" \
            -cmd \
            -configfile "$CONFIG_FILE" \
            -url "$TARGET_URL" \
            -quickout "$REPORT_FILE" \
            2>&1 | tee "${REPORT_FILE%.html}.log"
    else
        print_warn "Config file not found. Running default full scan..."
        "$ZAP_BIN" \
            -cmd \
            -scan "$TARGET_URL" \
            -quickout "$REPORT_FILE" \
            2>&1 | tee "${REPORT_FILE%.html}.log"
    fi

    if [ $? -eq 0 ]; then
        print_ok "Full scan completed"
        print_info "Report saved to: $REPORT_FILE"
    else
        print_warn "Full scan completed with warnings"
    fi
}

# ────────────────────────────────────────────────────────────────────────────
# Print Recommendations
# ────────────────────────────────────────────────────────────────────────────

print_recommendations() {
    print_header "Security Testing Recommendations"

    cat << 'EOF'
Before Running Tests
====================
1. Ensure the API is running on the target URL
2. Set up a test/staging environment (not production)
3. Configure authentication credentials if needed
4. Disable rate limiting for security tests (may cause false positives)

What Gets Tested
================
✓ Cross-Site Scripting (XSS)
✓ SQL Injection
✓ Cross-Site Request Forgery (CSRF)
✓ Broken Authentication
✓ Sensitive Data Exposure
✓ XML External Entities (XXE)
✓ Broken Access Control
✓ Security Misconfiguration
✓ Using Components with Known Vulnerabilities
✓ Insufficient Logging & Monitoring

Common API Endpoints to Include
================================
- Authentication endpoints (/auth/login, /auth/refresh)
- Student data endpoints (/students, /submissions)
- Admin endpoints (/admin/users, /admin/institutions)
- Public endpoints (/health, /metrics)

Post-Scan Actions
=================
1. Review the HTML report in a web browser
2. Assess each finding for severity (High, Medium, Low)
3. Create tickets for high-severity issues
4. Verify fixes with follow-up scans
5. Document false positives and exceptions

Additional Security Resources
=============================
- OWASP Top 10: https://owasp.org/www-project-top-ten/
- ZAP Documentation: https://www.zaproxy.org/docs/
- CWE/CVSS Database: https://cwe.mitre.org/

EOF
}

# ────────────────────────────────────────────────────────────────────────────
# Main Script
# ────────────────────────────────────────────────────────────────────────────

main() {
    print_header "Original Security Testing Script"

    # Handle check-config mode
    if [ "$CHECK_CONFIG" = true ]; then
        check_configuration
        exit $?
    fi

    # Handle install mode
    if [ "$INSTALL_ZAP" = true ]; then
        install_zap
        echo ""
        print_ok "Installation complete. Run security tests with:"
        echo "    $0 --baseline --target $TARGET_URL"
        exit 0
    fi

    # Check if ZAP is available
    if ! detect_zap; then
        print_err "OWASP ZAP not found"
        print_info "Install with: $0 --install"
        exit 1
    fi

    # Verify configuration
    echo ""
    if ! check_configuration; then
        print_warn "Some configuration issues detected. Tests may not run correctly."
    fi

    # Run appropriate scan
    echo ""
    case "$SCAN_TYPE" in
        baseline)
            run_baseline_scan
            ;;
        full)
            run_full_scan
            ;;
        *)
            print_err "Unknown scan type: $SCAN_TYPE"
            exit 1
            ;;
    esac

    # Print recommendations
    echo ""
    print_recommendations

    print_ok "Security testing script completed"
    exit 0
}

# ────────────────────────────────────────────────────────────────────────────
# Entry Point
# ────────────────────────────────────────────────────────────────────────────

main "$@"

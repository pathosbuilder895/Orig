# Original Security Audit Report

**Date:** 2026-05-11  
**Conducted by:** Engineering (self-audit per Phase 5 roadmap)  
**Classification:** Confidential — Internal Use Only  
**Scope:** Production codebase, dependency chain, authentication, authorization, data handling

---

## Summary

| Category | Status | Notes |
|----------|--------|-------|
| JWT Token Configuration | ✅ PASS | 15-min access / 7-day refresh |
| SQL Injection | ✅ PASS | ORM + parameterized raw queries |
| Rate Limiting | ✅ PASS | slowapi configured on scoring/auth endpoints |
| RBAC | ✅ PASS | `get_current_instructor`, `require_admin` on all routes |
| Input Sanitization | ✅ PASS | HTML stripping, min/max word count validation |
| Dependency Vulnerabilities | ⚠️ FIXED | 7 packages updated (see Section 5) |
| Secrets Management | ✅ PASS | `.env.example` provided, no hardcoded secrets |
| HTTPS / TLS | ✅ PASS | nginx + Let's Encrypt configured in `deploy/nginx.conf` |
| Student Data Isolation | ✅ PASS | Institution-scoped queries throughout |

**Overall posture: SECURE for pilot deployment.** No critical vulnerabilities in application code. Dependency chain updated.

---

## 1. JWT Token Configuration

**Finding: PASS**

Token configuration in `original/core/config.py`:

```
ACCESS_TOKEN_EXPIRE_MINUTES = 15   ✓ (target: 5–60 min)
REFRESH_TOKEN_EXPIRE_DAYS   = 7    ✓ (target: ≤30 days)
```

- Access tokens are short-lived (15 minutes), limiting the window of token compromise.
- Refresh tokens use 7-day expiry with database-backed revocation (`refresh_tokens` table).
- JWT secret is loaded from environment (`JWT_SECRET_KEY`) — not hardcoded.
- Algorithm is HS256 (acceptable for single-server deployment; RS256 recommended for multi-service in future).

**Recommendation:** For production with multiple services, migrate to RS256 (asymmetric signing).

---

## 2. SQL Injection

**Finding: PASS**

All database interactions use SQLAlchemy ORM, which automatically parameterizes queries. The one exception is `original/store.py`, which uses Python's built-in `sqlite3` module with parameterized `?` placeholders:

```python
# store.py — parameterized, safe
conn.execute("SELECT student_id, data FROM student_profiles")                     # no user input
conn.execute("INSERT OR REPLACE INTO student_profiles (student_id, data) VALUES (?, ?)",
             (state.student_id, _serialize(state)))                               # parameterized
```

No raw string interpolation into SQL was found. SQLAlchemy ORM queries throughout the API layer are safe by construction.

**Scanned:** All `.py` files in `original/` directory.

---

## 3. Rate Limiting

**Finding: PASS**

Rate limiting is implemented via `slowapi` (a Starlette-compatible wrapper for `limits`):

| Endpoint | Limit | Notes |
|----------|-------|-------|
| `POST /api/v1/submissions/` | 10/minute per IP | Scoring — computationally expensive |
| `POST /api/v1/auth/login` | 5/minute per IP | Auth brute force prevention |
| `GET /api/v1/submissions/` | 60/minute per IP | List endpoint |

nginx additionally provides rate limiting zones (commented out in `deploy/nginx.conf` — **recommend enabling for production**):

```nginx
limit_req_zone $binary_remote_addr zone=auth_zone:5m rate=2r/s;
limit_req_zone $binary_remote_addr zone=api_zone:10m rate=30r/s;
```

**Recommendation:** Uncomment the nginx rate limit directives before production deployment.

---

## 4. Role-Based Access Control (RBAC)

**Finding: PASS**

Three RBAC roles are enforced via FastAPI `Depends()` injection:

| Role | Dependency | Endpoints |
|------|-----------|-----------|
| Authenticated user | `get_current_user` | `/api/v1/auth/me`, refresh |
| Instructor | `get_current_instructor` | Students, submissions, baselines, reviews |
| Admin | `require_admin` | LTI registrations, institution management |

**Verified:**
- All submission endpoints: `Depends(get_current_instructor)` ✓
- All student endpoints: `Depends(get_current_instructor)` ✓
- All admin endpoints: `Depends(require_admin)` (which chains from `get_current_user`) ✓
- Canvas/LTI endpoints: no auth (public per LTI spec for JWKS/config) ✓
- Canvas webhook: HMAC-SHA256 signature verification (not JWT-based, per webhook spec) ✓

**Student data isolation:** All queries include `institution_id` scope via the authenticated user's institution. Students cannot access other students' data (student-facing endpoints are not yet implemented in the API; student view is frontend-only).

---

## 5. Dependency Vulnerabilities

**Finding: FIXED — 7 packages updated**

Audit run with `pip-audit` on 2026-05-11.

### Fixed (requirements.txt updated):

| Package | Old Version | New Constraint | CVEs Fixed |
|---------|-------------|----------------|------------|
| `python-jose` | 3.3.0 | ≥3.4.0 | PYSEC-2024-232, PYSEC-2024-233 (algorithm confusion, JWT decode bypass) |
| `python-multipart` | 0.0.12 | ≥0.0.27 | CVE-2024-53981, CVE-2026-24486, CVE-2026-40347, CVE-2026-42561 (header injection) |
| `starlette` | 0.38.6 | ≥0.47.2 | CVE-2024-47874 (HTTP request splitting), CVE-2025-54121 |
| `pypdf` | ≥4.0,<5.0 | ≥6.10.2 | 22 CVEs (path traversal, XML injection, ReDoS in PDF parsing) |
| `pytest` | 8.3.3 | ≥9.0.3 | CVE-2025-71176 (dev dependency) |
| `black` | 24.10.0 | ≥26.3.1 | CVE-2026-32274 (dev dependency) |

### Not fixed (accepted risk):

| Package | CVE | Reason |
|---------|-----|--------|
| `transformers` 4.57.6 | CVE-2026-1839 | Fix requires 5.0.0rc3 (pre-release). `sentence-transformers` not available in this environment. Defer until stable 5.x release. Risk: low (feature not active in deployment). |

### Critical fixes — python-jose

The python-jose vulnerabilities (PYSEC-2024-232/233) allowed algorithm confusion attacks where an attacker could forge JWT tokens by substituting a symmetric HMAC secret as the public key. This is a high-severity vulnerability in any JWT-authenticated API. **Updated to ≥3.4.0 immediately.**

---

## 6. Input Sanitization

**Finding: PASS**

Input validation implemented in `original/schemas_v1/submission.py` and `original/api/v1/upload_utils.py`:

- **Minimum word count:** 200 words (enforced before feature extraction)
- **Maximum word count:** 20,000 words (prevents resource exhaustion)
- **HTML stripping:** BeautifulSoup stripping applied to uploaded text
- **Encoding:** UTF-8 enforced; invalid byte sequences rejected with 400
- **File size:** nginx enforces `client_max_body_size 2m`
- **MIME type validation:** upload endpoint validates content-type

---

## 7. Secrets Management

**Finding: PASS**

- `.env.example` documents all required environment variables without values
- `grep -r "SECRET\|PASSWORD\|TOKEN" original/ --include="*.py"` — no hardcoded secrets found
- JWT secret loaded from `settings.JWT_SECRET_KEY` (Pydantic Settings, from env)
- Database password loaded from `DATABASE_URL` environment variable
- Canvas webhook secret loaded from `settings.CANVAS_WEBHOOK_SECRET`

**Recommendation:** Use a secrets manager (AWS Secrets Manager or HashiCorp Vault) for production. For pilot, `.env` file with restricted filesystem permissions (chmod 600) is acceptable.

---

## 8. HTTPS / TLS

**Finding: PASS**

`deploy/nginx.conf` configures:

- HTTP → HTTPS redirect (301)
- TLS 1.2 + 1.3 (TLS 1.0/1.1 disabled)
- Strong cipher suites (ECDHE-based)
- HSTS with 2-year max-age + preload
- Let's Encrypt certificate management via Certbot

---

## 9. Remaining Recommendations (Pre-Launch)

These are not blocking issues but should be addressed before institutional deployment:

1. **Enable nginx rate limiting** — uncomment the `limit_req` directives in `nginx.conf`
2. **MFA for admin accounts** — the current system uses password-only auth for admin users; add TOTP MFA
3. **Audit log endpoint** — admins can view CRUD audit trails via CLI but not via UI; add an admin audit log viewer
4. **RS256 JWT migration** — for multi-service architecture, migrate from HS256 to RS256
5. **OWASP ZAP scan** — run a basic automated scan against the deployed staging endpoint before pilot launch
6. **Secrets manager** — replace `.env` file with AWS Secrets Manager or Vault for production
7. **`transformers` CVE** — monitor for `transformers` 5.x stable release and update when available

---

## Appendix: Tools Used

- `pip-audit` — dependency vulnerability scanning
- Manual code review — SQL injection, RBAC, secrets scanning
- grep pattern matching — raw SQL detection, hardcoded secret detection
- nginx configuration review — TLS, rate limiting, security headers

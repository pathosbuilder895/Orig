# Phase 3 follow-up — httpOnly cookie authentication

Today, the API returns JWTs in JSON from `POST /api/v1/auth/login` and `POST /api/v1/auth/refresh` ([original/api/v1/auth.py](../original/api/v1/auth.py)). The static frontend ([frontend/auth.js](../frontend/auth.js)) stores tokens in **sessionStorage** (with an in-memory preference noted in comments).

## Goal

- Set **httpOnly**, **Secure**, **SameSite** cookies for access and/or refresh tokens so JavaScript cannot read them (XSS hardening).
- Keep **CORS** and **CSRF** correct when the browser sends cookies to `https://api...` or same-site `https://app...`.

## High-level design options

1. **Access + refresh in httpOnly cookies**  
   - Login response: `Set-Cookie` for both; body may omit raw tokens or return non-sensitive metadata only.  
   - `Authorization: Bearer` optional for API clients; browser uses cookies.

2. **Access in memory / header, refresh in httpOnly only** (common)  
   - Short-lived access token still returned in JSON for SPA, or use a **BFF** pattern.

3. **Double-submit or CSRF token**  
   - If cookies are sent on `POST` from the SPA, use **SameSite=strict** or **lax** where possible, and add a **CSRF** header for mutating requests when `SameSite` cannot be strict (cross-site iframes, etc.).

## Code touchpoints (when implementing)

- [original/api/v1/auth.py](../original/api/v1/auth.py): on login/refresh, attach `Response.set_cookie()` with paths (`/api/v1` or `/`), `max_age` aligned with token expiry, `httponly=True`, `secure=True` in production, `samesite` per deployment.
- [original/api/deps.py](../original/api/deps.py) (or equivalent): resolve current user from **Cookie** if `Authorization` is absent.
- [original/core/config.py](../original/core/config.py): `COOKIE_DOMAIN`, `COOKIE_SAMESITE`, `COOKIE_SECURE` envs.
- Logout: clear cookies; keep DB refresh-token revocation behavior.

## Session expiry (frontend)

- Rely on **401** from API and a single **refresh** attempt, then redirect to login; avoid trusting client clocks for expiry when using httpOnly cookies.
- [frontend/auth.js](../frontend/auth.js) would use `fetch(..., { credentials: 'include' })` and drop manual `Authorization` header when cookies carry the session.

This is intentionally a design stub for **Phase 3**; Phase 2 ships with Bearer + sessionStorage as today.

# Canvas LTI 1.3 — Operator Runbook

How to take one institution from "no integration" to "students launch exams
from Canvas." The admin-facing one-pager to send is `docs/canvas_developer_key.md`.
Routes live in `original/lti.py`; config keys in `.env.example`.

## 0. Prerequisites

- Pilot service live with a final, never-changing host (the key bakes it in).
- `LTI_PRIVATE_KEY` set: `openssl genrsa 2048 > lti_private.pem`, paste the PEM
  into the Render env (escape newlines as `\n`, or use `LTI_PRIVATE_KEY_FILE`).
- Confirm `https://<host>/lti/jwks` returns a non-empty `keys` array.
- The institution's tenant exists (`docs/PROVISIONING_CHECKLIST.md`).

## 1. The ask (Day 1 — this is the schedule's critical path)

Email the Canvas admin: the one-pager + the DPA (`docs/dpa_template.md`) for
their compliance office in parallel. You need back exactly two values:
**Client ID** and **Deployment ID**.

## 2. Configure the binding

Set `LTI_PLATFORMS` on the pilot service (JSON, one entry per platform):

```json
[{"issuer": "https://canvas.instructure.com",
  "client_id": "125900000000000123",
  "auth_login_url": "https://<inst>.instructure.com/api/lti/authorize_redirect",
  "jwks_url": "https://<inst>.instructure.com/api/lti/security/jwks",
  "deployment_ids": ["1:abc123..."],
  "tenant_id": "<tenant-slug>",
  "name": "<Institution> Canvas"}]
```

Notes:
- `issuer` for Canvas cloud is always `https://canvas.instructure.com` (NOT the
  institution's vanity domain); self-hosted Canvas uses its own domain.
- `tenant_id` is the binding that drops every launch into the right tenant —
  double-check it; a typo silently creates a new namespace.
- `deployment_ids` is an allow-list; leave `[]` only during initial testing.

Redeploy (env change restarts the service).

## 3. Verify in a sandbox course (before any professor)

| Check | Expect |
|---|---|
| Instructor clicks course-nav placement | lands signed-in on the Bluebook dashboard, tenant-scoped |
| Student clicks an exam link (target `/bluebook/`) | lands on the examination briefing, no login, candidate bound (`bluebook_student_id` in localStorage) |
| Same student submits | proctored sample appears on their profile (`GET /students/<id>` sample_count +1) |
| Launch with a bogus deployment_id | 401 "unrecognised deployment_id" |
| Replayed/stale launch | 401 "invalid or expired state" |

## 4. Troubleshooting

| Symptom | Likely cause → fix |
|---|---|
| 400 "unknown platform issuer" at /lti/login | `LTI_PLATFORMS` issuer mismatch (vanity domain vs canvas.instructure.com) or JSON didn't parse — check service logs at boot |
| 401 "id_token verification failed: Signature…" | wrong `jwks_url` (must be the institution's, not the tool's) |
| 401 "nonce mismatch" | launch replay, or the browser blocked the form_post round-trip — retry once; persistent → check for an intermediate redirect stripping `state` |
| 401 "invalid or expired state" | >10 min between login and launch (clock skew or the user parked on a Canvas interstitial) — relaunch |
| 401 "unrecognised deployment_id" | the admin created a second deployment (account vs course level) — add it to `deployment_ids` |
| 501 "LTI requires python-jose" | service deployed with requirements-demo instead of requirements-pilot |
| Launch works but lands in the wrong data | `tenant_id` in `LTI_PLATFORMS` doesn't match the provisioned tenant slug |
| Blank page inside Canvas iframe | expected — exam launches break out of the iframe to full-page (`window.top.location`); if blocked, Canvas's "open in new tab" setting on the placement fixes it |

## 5. After it works

- Record Client ID / Deployment ID / date in the password manager alongside the keys.
- Walk ONE professor through creating an exam + Canvas assignment link before announcing to the department.

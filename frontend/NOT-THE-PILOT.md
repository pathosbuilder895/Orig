# ⚠️ This is NOT the pilot UI

These pages belong to the **dormant v1 backend** (`original/main.py` +
`original/api/`, Postgres path). They are not served by the pilot deployment
and are not maintained.

The live UI professors use is **`demo/`** (dashboards) and **`demo/bluebook/`**
(secure exams), served by `original/api.py` via `run.py --demo`.

See `docs/ARCHITECTURE.md` for the full map. Do not link, register, or
document anything in this directory for the pilot — in particular, the
v1 LTI routes (`/canvas/lti/*`) are NOT the pilot's LTI routes (`/lti/*`).

# Canvas Developer Key Application — Original + Bluebook

One-pager for the Canvas administrator. Values below assume the pilot host
`https://original-pilot.onrender.com` — substitute the custom domain if one is
configured (the key must be re-issued if the host ever changes).

## Application Details

| Field | Value |
|-------|-------|
| **Tool Name** | Original — Authorship Verification |
| **Tool Description** | Stylometric authorship verification for academic integrity. Builds per-student writing profiles from verified baselines and flags deviations using a 103-feature linguistic analysis engine. Includes Bluebook, a secure in-class examination environment for proctored baseline capture. |
| **Company/Organization** | Original Academic Integrity |
| **Contact Email** | admin@original-integrity.edu |
| **Tool URL** | `https://original-pilot.onrender.com` |
| **Redirect URIs** | `https://original-pilot.onrender.com/lti/launch` |
| **Target Link URI** | `https://original-pilot.onrender.com/lti/launch` |
| **OpenID Connect Initiation URL** | `https://original-pilot.onrender.com/lti/login` |
| **JWK Method** | Public JWK URL |
| **Public JWK URL** | `https://original-pilot.onrender.com/lti/jwks` |

## LTI 1.3 Scopes Required

**None.** The pilot uses the basic LTI 1.3 launch only (OIDC + id_token).
No Assignment & Grade Services, no Names & Role Provisioning — Original does
not read rosters or write grades. (AGS grade passback may be requested in a
future version; it would be a new, separate review.)

## Placements

- **Course Navigation** — instructors open the Original/Bluebook dashboard from the course nav.
- **Assignment Selection / Link Selection** — for proctored Bluebook examinations, set the placement's **Target Link URI** to `https://original-pilot.onrender.com/bluebook/` (the `/bluebook` path is what routes a student launch into the locked examination; alternatively set custom field `bluebook=1`).

---

## Privacy Policy

### Data Collection

Original collects the following exclusively for authorship verification:

1. **Submission text** — essays submitted for analysis.
2. **LTI subject identifier and email** — hashed into an opaque, institution-scoped student id (`{tenant}:{sha256(...)[:16]}`); the email itself never appears in URLs or stored ids.
3. **Assignment metadata** — assignment title, course label, timestamps.
4. **Derived feature vectors** — 103 numerical stylometric features.
5. **During proctored Bluebook examinations only:** keystroke timing dynamics (inter-key intervals, deletion rate, pauses), paste attempts, and window-focus/fullscreen events. These feed the behavioural tier of the authorship profile and are disclosed to students before each examination begins.

### Data Usage

- Text is processed to extract stylometric features (vocabulary, sentence structure, discourse, rhetorical patterns); vectors build the student's baseline.
- **No student text is shared with third parties.**
- **No student data is used to train machine-learning models.**
- **No student data is sold or monetized.**

### Data Storage & Retention

- Pilot data is stored on dedicated infrastructure provisioned for the institution, isolated per tenant and inaccessible to any other institution or to the public demo.
- Feature vectors and scores are retained for the student's enrollment plus one academic year.
- Institutions may request complete deletion at any time; per-student erasure is supported (`DELETE /students/{id}` removes profile, samples, scores, manifests).

### FERPA Compliance

- Acts as a "school official" with legitimate educational interest under 34 CFR § 99.31(a)(1).
- Maintains an audit log of every significant action (logins, launches, baseline additions, scores, deletions).
- Supports institution-managed retention; no re-disclosure of student records.
- A signed DPA (see `docs/dpa_template.md`) precedes any real student data.

---

## Terms of Service

### Appropriate Use

Original is an **advisory tool** to support academic-integrity conversations.
Results must be interpreted by qualified instructors and must **never be used
as sole evidence** for academic-dishonesty determinations. The four-tier
recommendation system (no action → monitor → schedule conversation → escalate)
is designed for pastoral, conversation-first handling.

### Accuracy & Limitations

- Minimum 3 baseline samples per student before scoring (5+ recommended).
- Calibration is per-cohort and currently rated **Limited** (see MODEL_CARD.md) — scores open a conversation, never decide one.
- Legitimate writing development can elevate deviation scores; non-native English speakers' scores are monitored for demographic bias.
- Bluebook's browser lockdown (fullscreen, clipboard, focus monitoring) is deterrence and signal capture, not a hard technical guarantee.

---

## Canvas Admin Setup Instructions

### 1. Create the Developer Key

1. **Admin → Developer Keys → + Developer Key → LTI Key**
2. Method: **Manual Entry** (or Paste JSON), fill the Application Details table above
3. Set **Key State** to **ON**
4. Send back to the Original operator: the **Client ID** (the long number above the key) and the **Deployment ID** (visible after the app is added to a course/account)

### 2. Operator configures Original (not the Canvas admin)

The operator sets two environment variables on the pilot service:

```env
LTI_TOOL_URL=https://original-pilot.onrender.com
LTI_PLATFORMS=[{
  "issuer": "https://canvas.instructure.com",
  "client_id": "<Client ID from step 1>",
  "auth_login_url": "https://<institution>.instructure.com/api/lti/authorize_redirect",
  "jwks_url": "https://<institution>.instructure.com/api/lti/security/jwks",
  "deployment_ids": ["<Deployment ID>"],
  "tenant_id": "<institution tenant slug>",
  "name": "<Institution> Canvas"
}]
```

(Plus `LTI_PRIVATE_KEY` — the tool's RSA key backing `/lti/jwks`.)

### 3. Add the app to the course

**Course → Settings → Apps → + App → By Client ID** → paste the Client ID → Submit.

### 4. Create a proctored examination link

1. Instructor creates the examination inside Bluebook (Course Navigation placement → Examinations → + New Examination).
2. In Canvas, add an **External Tool** assignment/module item pointing at the Original app with Target Link URI `https://original-pilot.onrender.com/bluebook/`.
3. When a student clicks it, Canvas launches them — already identified — straight into the examination briefing; no separate login.

### 5. Baselines before scoring

Each student needs ≥3 baseline samples before take-home submissions are scored — the recommended path is one short proctored Bluebook sitting in week 1 plus imported prior essays (professor dashboard → Import Papers).

---

## Technical Requirements

| Requirement | Specification |
|-------------|---------------|
| **Protocol** | LTI 1.3 (OIDC third-party initiation, RS256 id_token, JWKS verification, state+nonce, deployment_id allow-list) |
| **Canvas Version** | 2022.01+ |
| **Network** | HTTPS; Canvas must reach the tool URLs above; tool fetches the platform JWKS |
| **Grade passback** | Not used in pilot |

# Canvas Developer Key Application — Original

## Application Details

| Field | Value |
|-------|-------|
| **Tool Name** | Original — Authorship Verification |
| **Tool Description** | Stylometric authorship verification for academic integrity. Builds per-student writing profiles and detects deviations using a 62-feature linguistic analysis engine. |
| **Company/Organization** | Original Academic Integrity |
| **Contact Email** | admin@original-integrity.edu |
| **Tool URL** | `https://your-domain.edu/original` |
| **Redirect URIs** | `https://your-domain.edu/canvas/lti/callback` |
| **Target Link URI** | `https://your-domain.edu/canvas/lti/launch` |
| **OpenID Connect Initiation URL** | `https://your-domain.edu/canvas/lti/login` |
| **JWK Method** | Public JWK URL |
| **Public JWK URL** | `https://your-domain.edu/canvas/lti/jwks.json` |

---

## LTI 1.3 Scopes Required

```
https://purl.imsglobal.org/spec/lti-ags/scope/lineitem
https://purl.imsglobal.org/spec/lti-ags/scope/result.readonly
https://purl.imsglobal.org/spec/lti-ags/scope/score
https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly
```

## Placements

- **Assignment Selection** — Instructors select Original when creating assignments
- **Course Navigation** — Link in course nav to Original dashboard
- **Submission Type** — Document Processor / Plagiarism Framework

---

## Privacy Policy

### Data Collection

Original collects the following student data exclusively for authorship verification:

1. **Submission text** — Essay text submitted through Canvas assignments configured with Original
2. **Canvas user ID** — Used solely to link submissions to the correct student profile
3. **Assignment metadata** — Assignment ID, course ID, submission timestamp
4. **Derived feature vectors** — 62 numerical stylometric features extracted from text (not the text itself for long-term storage)

### Data Usage

- Student text is processed to extract stylometric features (vocabulary patterns, sentence structure, discourse markers, rhetorical patterns)
- Feature vectors are stored to build the student's authorship baseline
- Raw text may be cached during processing but is not retained beyond the scoring pipeline unless configured by the institution
- **No student text is shared with third parties**
- **No student text is used to train machine learning models**
- **No student data is sold or monetized**

### Data Storage & Retention

- All data is stored on infrastructure controlled by the subscribing institution (self-hosted) or on dedicated infrastructure provisioned for the institution
- Feature vectors and scoring results are retained for the duration of the student's enrollment plus one academic year
- Institutions may request complete data deletion at any time
- Individual students may request deletion of their baseline data through their institution's registrar

### FERPA Compliance

Original is designed for FERPA compliance:
- Acts as a "school official" with legitimate educational interest under 34 CFR § 99.31(a)(1)
- Does not constitute "outsourcing institutional functions" that would require separate consent
- Maintains audit logs of all data access
- Supports institution-managed data retention policies
- No re-disclosure of student records

---

## Terms of Service

### Service Description

Original provides stylometric authorship verification as an LTI 1.3 tool integrated with Canvas LMS. The service analyses student writing submissions to build individualized authorship profiles and flags submissions that deviate significantly from a student's established writing patterns.

### Appropriate Use

Original is designed as an **advisory tool** to support academic integrity conversations. Results should be interpreted by qualified instructors and should **never be used as sole evidence** for academic dishonesty determinations.

The four-tier recommendation system (no action, monitor, schedule conversation, escalate) is designed to support pastoral approaches to academic integrity.

### Accuracy & Limitations

- Original requires a minimum of 3 baseline samples to establish a student profile
- Accuracy improves with more baseline samples (recommended: 5+)
- The system may produce elevated deviation scores for students experiencing legitimate writing development
- Non-native English speakers' scores are monitored for demographic bias
- Results should always be considered alongside other evidence

### Availability

- 99.5% uptime SLA for hosted deployments
- Self-hosted deployments are managed by the institution
- Scoring latency target: < 500ms per submission

### Support

- Email support: support@original-integrity.edu
- Documentation: https://docs.original-integrity.edu
- Integration support during initial Canvas setup

---

## Data Usage Description (for Canvas Admin Console)

**Short description (appears in Canvas):**
> Original analyses student writing patterns to verify authorship. It builds a stylometric profile from verified baseline samples and flags submissions that deviate from the student's established writing identity.

**What data does this tool access?**
> Submission text, Canvas user IDs, assignment metadata. No access to grades, attendance, or non-submission student data.

**How is student data protected?**
> All data is processed and stored on institution-controlled infrastructure. No student text is shared with third parties or used for model training. FERPA-compliant by design.

---

## Canvas Admin Setup Instructions

### 1. Create Developer Key

1. Navigate to **Admin → Developer Keys → + Developer Key → LTI Key**
2. Fill in the fields from the table above
3. Set **Key State** to **ON**
4. Copy the **Client ID** — you'll need this for Original's configuration

### 2. Configure Original

Add the following to Original's `.env` file:

```env
CANVAS_CLIENT_ID=<client_id_from_step_1>
CANVAS_BASE_URL=https://your-institution.instructure.com
CANVAS_DEPLOYMENT_ID=<deployment_id>
LTI_PLATFORM_ISSUER=https://canvas.instructure.com
LTI_PLATFORM_AUTH_URL=https://your-institution.instructure.com/api/lti/authorize_redirect
LTI_PLATFORM_TOKEN_URL=https://your-institution.instructure.com/login/oauth2/token
LTI_PLATFORM_JWKS_URL=https://your-institution.instructure.com/api/lti/security/jwks
```

### 3. Enable in Course

1. Navigate to **Course → Settings → Apps → + App**
2. Select **By Client ID**
3. Enter the Client ID from step 1
4. Submit

### 4. Configure Assignments

1. Create or edit an assignment
2. Under **Submission Type**, select **Online → Text Entry**
3. Under **Plagiarism Review**, select **Original — Authorship Verification**
4. Save

### 5. Import Baselines

Before scoring begins, import baseline samples for each student:

1. Navigate to the Original dashboard within Canvas
2. Select **Import Baselines** for each student
3. Choose 3–5 verified submissions from previous courses
4. Original will build the student's authorship profile

---

## Technical Requirements

| Requirement | Specification |
|-------------|---------------|
| **Protocol** | LTI 1.3 Advantage |
| **Authentication** | OIDC + JWT (RS256) |
| **Canvas Version** | 2022.01+ (LTI 1.3 support) |
| **Network** | HTTPS required, outbound access to Canvas API |
| **Webhook** | Canvas Plagiarism Framework or Document Processor |

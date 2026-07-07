# Student Data Inventory

**Last Updated:** 2026-07-07
**Classification:** Internal / Sensitive
**Compliance:** FERPA, GDPR, CCPA

> **Accuracy note (2026-07-07):** This document previously marked every
> data category `AES-256`, claimed raw text is "NOT stored by default,"
> and described an automatic/scheduled deletion job. None of that is
> accurate to the live pilot stack. Encryption claims have been corrected
> to "Render disk encryption (platform)" — see `docs/encryption_policy.md`
> for the full explanation. Raw text storage and deletion claims have been
> corrected below; automatic-deletion language is marked **Planned — not
> implemented** rather than removed outright, so the intended design isn't
> lost. This document now describes only the live stack
> (`original/api.py` + `demo/`).

This document provides a complete inventory of all student data collected, processed, and stored by Original.

---

## 1. Data Inventory Overview

| Category | Data Type | Collection Method | Retention | Access | Encryption |
|----------|-----------|-------------------|-----------|--------|------------|
| PII | Student name, ID, email | LTI / Canvas API | 1 year after relationship (policy; not auto-enforced — see §10) | Teachers, Admins | Render disk encryption (platform) |
| Submissions | Essay text, metadata | Student upload | 1 year after submission (policy; not auto-enforced — see §10) | Student, Teachers | Render disk encryption (platform) |
| Baseline | Authorized writing samples | Instructor upload | Duration + 1 year (policy; not auto-enforced — see §10) | Admins, Teachers | Render disk encryption (platform) |
| Results | Authorship scores, vectors | Original computation | 1 year after generation (policy; not auto-enforced — see §10) | Student, Teachers | Render disk encryption (platform) |
| Audit | Access logs, decisions | System logging | 2 years (policy; not auto-enforced — see §10) | Admins only | Render disk encryption (platform) |

Application-level encryption (e.g., AES-256) is **not** implemented for
any of these categories. "Render disk encryption (platform)" is Render's
managed-disk encryption guarantee, inherited from the hosting platform —
not something the application implements itself. See
`docs/encryption_policy.md` §2.1 for the full explanation, including why
this differs from encrypting row data at the application layer.

---

## 2. Personally Identifiable Information (PII)

### 2.1 Student Identity Data

**Data Elements:**
- Student name (first + last)
- Student ID (institutional)
- External ID (SIS ID from Canvas/institutional system)
- Email address
- Institution ID (foreign key)
- Enrollment status (is_active boolean)

**Collection Source:**
- LTI 1.3 launch from Canvas
- Manual upload by instructors
- Canvas API synchronization

**Storage Location:**
```
Database: original_db.students table
Fields: id, external_id, full_name, email, institution_id, is_active
Size: ~150 bytes per student
```

**Access:**
- **Read:** Students (own record), teachers (enrolled courses), admins (institution)
- **Write:** Teachers, Admins
- **Delete:** Admins only (upon student request)

**Retention:**
- **Active Period:** While student enrolled + 1 year after
- **Automatic Deletion:** > Planned — not implemented in the pilot stack (no retention scheduler runs). Retention beyond the active period is a policy target, not a code-enforced trigger.
- **Manual Deletion:** Via `original.cli.delete_student` command (real, live — see §10.2)

**Security:**
- Render disk encryption at rest (platform-level; not application-level — see `docs/encryption_policy.md`)
- Encrypted in transit (TLS 1.3)
- Indexed for fast lookup (by external_id)
- Password-hashed for auth (bcrypt)

### 2.2 Course Enrollment Data

**Data Elements:**
- Student ID (FK)
- Course ID (FK)
- Enrollment date (timestamp)
- Course name
- Course code
- Instructor name(s)

**Storage Location:**
```
Database: student_enrollments table
Database: courses table
Relationship: Many-to-many (student_enrollments join table)
```

**Access:**
- **Read:** Enrolled student, course instructors, admins
- **Write:** Instructors, admins
- **Delete:** Admins only

**Retention:**
- Same as student data (1 year after relationship ends; policy target, not auto-enforced — see §10)

**Security:**
- Render disk encryption at rest (platform-level)
- Access controlled by RBAC middleware

---

## 3. Student Writing Samples

### 3.1 Submission Texts

**Data Elements:**
- Raw essay/assignment text (stored — see Security below)
- Text hash (SHA-256)
- Word count, character count
- Assignment name/title
- Submission timestamp
- Course context
- Submission status (pending, scoring, scored, failed)

**Collection Source:**
- Direct student upload via Canvas LTI submission
- Manual paste in Original dashboard
- Canvas Submissions API

**Storage Location:**
```
Database: submissions table (SQLite, live pilot store)
Fields: id, student_id, course_id, assignment, text_hash, raw_text, word_count, char_count, submitted_at, status
```

**Text Hash Computation:**
```python
text_hash = SHA-256(submission_text.encode('utf-8'))
```

**Access:**
- **Read:** Student (own submission), course instructors, admins
- **Write:** Student (create), admins (delete)
- **Raw Text Access:** Raw baseline/submission text **is stored** and is
  retrievable by authorized instructors via the live endpoint
  `GET /students/{id}/samples/{index}/text` (`original/api.py:889`), gated
  by the endpoint's normal authn/authz. This matches
  `PILOT_RUNBOOK.md:150` ("Raw text is stored.").

**Retention:**
- **Active Period:** For 1 year after submission (policy target)
- **Automatic Deletion:** > Planned — not implemented in the pilot stack (no retention scheduler runs). No background job deletes or nulls out submission text.
- **Manual Deletion:** Via `original.cli.delete_student` (real, live — see §10.2)

**Security:**
- Text hash computed immediately upon receipt (used for deduplication, not for hiding the text)
- Raw text **is stored** in plain form in SQLite; it is not
  application-level encrypted (see `docs/encryption_policy.md`)
- Protected by Render disk encryption at rest (platform-level) and by the
  endpoint's access control, not by encryption or by omission
- Hashes indexed for fast deduplication

### 3.2 Baseline Writing Samples

**Data Elements:**
- Raw baseline text (used for feature extraction)
- Text hash (SHA-256)
- Feature vector (JSON: lexical, syntactic, quantum metrics)
- Provenance level (proctored, verified, unverified)
- Assignment context
- Word count
- Authentication weight
- Model version used

**Collection Source:**
- Instructor uploads of proctored essays
- Verified in-class writing samples
- Unverified previous work (for comparative analysis)

**Storage Location:**
```
Database: baseline_samples table
Fields: id, student_id, course_id, assignment, text_hash, raw_text, feature_vector, provenance, auth_weight, word_count, submitted_at, added_by_id, model_version, is_active
Size: ~2 KB per sample (includes feature vector)
```

**Access:**
- **Read:** Admins, baseline-approval role, course instructors
- **Write:** Instructors, admins
- **Delete:** Admins only

**Retention:**
- **Active Period:** For 1 year after student relationship ends (policy target)
- **Automatic Deletion:** > Planned — not implemented in the pilot stack (no retention scheduler runs).
- **Manual Deletion:** Via admin-triggered `delete_student` CLI (real, live — see §10.2)

**Security:**
- Raw text is stored in plain form; not application-level encrypted (Render disk encryption at rest applies — see `docs/encryption_policy.md`)
- Feature vector JSON stored unencrypted (non-reversible by construction, not by encryption)
- Provenance tracked to assess confidence
- is_active flag allows soft-delete

---

## 4. Derived Data: Authorship Profiles

### 4.1 Student Authorship Signature

**Data Elements:**
- Baseline confidence scores (per feature category)
- Aggregated feature vector (average across baselines)
- Confidence level (high, medium, low)
- Feature count, model version
- Creation/update timestamp
- Status (active, inactive)

**Computation:**
```
Authorship Profile = {
  "baseline_count": N,
  "features": {...},  // averaged across N baselines
  "confidence": "high" if N >= MIN_BASELINE else "low",
  "model_version": "1.0.0",
  "created_at": ISO timestamp,
  "updated_at": ISO timestamp
}
```

**Storage Location:**
```
Database: baseline_samples table (aggregated view)
Cache: Redis (if ENABLE_REDIS_CACHE=True, TTL 1 hour)
```

**Access:**
- **Read:** Student (dashboard), instructors, admins
- **Write:** System (generated automatically)
- **Delete:** Admins only

**Retention:**
- Same as baseline samples (1 year after relationship)

**Security:**
- Derived from baseline text (baseline text itself is not application-level encrypted — see §3.2)
- Not a reversible representation of original text (non-reversible by construction)
- Quantum-weighted metrics non-attributable

---

## 5. Scoring Results and Decisions

### 5.1 Authorship Verification Scores

**Data Elements:**
- Submission ID (FK)
- Deviation score (0.0 — 1.0, compared to baseline)
- Authorship probability (%)
- Recommended action (escalate, monitor, clear)
- Baseline confidence (per-feature scores)
- Full result JSON (detailed metrics)
- Feature vector (derived from submission)
- Model version used
- Scored timestamp

**Storage Location:**
```
Database: scoring_results table
Fields: id, submission_id, model_version, deviation_score, authorship_probability, recommended_action, baseline_confidence, full_result, feature_vector, scored_at
Size: ~3 KB per scoring result
Indexed: submission_id, scored_at
```

**Access:**
- **Read:** Student (own score), course instructors, admins
- **Write:** System (generated), admins (override decision)
- **Delete:** Admins only

**Retention:**
- **Active Period:** 1 year after submission (policy target)
- **Automatic Deletion:** > Planned — not implemented in the pilot stack (no retention scheduler runs).
- **Manual Deletion:** Via `delete_student` CLI (real, live — see §10.2)

**Security:**
- Render disk encryption at rest (platform-level; not application-level)
- Indexed for fast retrieval
- Full audit trail of changes (InstructorDecision table)

### 5.1b AI-Likelihood Scores (shadow / enabled mode)

**Data Elements:** submission ID, student ID, calibrated AI-likelihood
probability, band (low/elevated/strong), detector model version, timestamp.

**Storage Location:** `ai_likelihood_scores` table (SQLite, pilot store).
One row per scored submission whenever `AI_LIKELIHOOD_SHADOW=1` or
`AI_LIKELIHOOD_ENABLED=1`; no rows when both are off. In shadow mode this
table is the only footprint — nothing is surfaced to professors or students.

**Access:** ops only (via `scripts/shadow_report.py` / `scripts/pilot_report.py`,
read-only). Not exposed by any student- or professor-facing endpoint while in
shadow mode.

**Deletion:** purged by `DELETE /students/{student_id}` together with all
other per-student data; counted in the data-inventory endpoint
(`GET /students/{id}/data-inventory`, category `ai_likelihood_scores`).

### 5.2 Instructor Decisions

**Data Elements:**
- Submission ID (FK)
- Instructor ID (FK)
- Action taken (escalate, schedule_conversation, monitor, clear, override_clear)
- Notes (optional, up to 2000 chars)
- Decision timestamp

**Storage Location:**
```
Database: instructor_decisions table
Fields: id, submission_id, user_id, action, notes, created_at, updated_at
Size: ~500 bytes per decision
Immutable: Decisions are immutable; new decisions replace old ones
```

**Access:**
- **Read:** Instructors, admins, academic integrity office
- **Write:** Instructors
- **Delete:** Admins only (with audit trail retained)

**Retention:**
- **Active Period:** 2 years (for institutional records)
- **Automatic Deletion:** > Planned — not implemented in the pilot stack (no retention scheduler runs). No job currently purges decisions after 2 years.
- **Legal Hold:** Indefinite if subject to investigation

**Security:**
- Immutable (append-only semantics)
- Timestamped and attributed
- Full audit trail maintained

---

## 6. Feature Vectors and ML Artifacts

### 6.1 Stylometric Features

**Data Elements:**
- Lexical features (vocabulary richness, word frequency, word length)
- Syntactic features (sentence structure, punctuation patterns, grammar patterns)
- Semantic features (word embeddings, topic distribution)
- Quantum-weighted confidence metrics (original innovation)
- Feature version, model version

**Storage Location:**
```
Database: baseline_samples.feature_vector (JSON)
Database: scoring_results.feature_vector (JSON)
Cache: Redis (feature cache, TTL 1 hour)
Size: ~1 KB per feature vector
```

**Example Feature Vector:**
```json
{
  "lexical": {
    "avg_word_length": 4.8,
    "vocabulary_richness": 0.62,
    "stop_word_ratio": 0.38
  },
  "syntactic": {
    "avg_sentence_length": 14.3,
    "semicolon_frequency": 0.02
  },
  "quantum": {
    "interference_pattern": 0.765,
    "superposition_confidence": 0.88
  },
  "model_version": "1.0.0"
}
```

**Access:**
- **Read:** Instructors, admins, Original support
- **Write:** System (generated by Original ML engine)
- **Delete:** Admins only

**Retention:**
- 1 year after submission

**Security:**
- Non-reversible (cannot reconstruct original text)
- Stored unencrypted (already de-identified)
- Quantum metrics provide additional privacy
- Cannot be used to identify individuals

### 6.2 ML Model Artifacts

**Data Elements:**
- Baseline centroid (aggregated feature vector per student)
- Feature importance weights
- Confidence calibration parameters
- Model version, training date

**Storage Location:**
```
Cache: Redis / in-memory (ephemeral)
Database: baseline_samples table (aggregated)
```

**Access:**
- **Read:** Original ML team, admins
- **Write:** System (generated during baseline aggregation)

**Retention:**
- Regenerated on-demand
- No permanent storage needed

**Security:**
- Cleared from cache after 1 hour
- Never written to audit logs

---

## 7. System Audit Logs

### 7.1 Data Access Logs

**Data Elements:**
- User ID (who accessed the data)
- Resource ID (submission_id, student_id, etc.)
- Action (read, create, update, delete)
- Timestamp (UTC)
- IP address (optional)
- User agent (optional)
- Result (success, denied, error)
- Reason (for denials)

**Storage Location:**
```
Database: audit_logs table (or separate logging system)
Retention: 2 years
Rotation: Monthly log files (if file-based)
```

**Access:**
- **Read:** Admins, compliance officer
- **Write:** System (automatic logging)
- **Delete:** Admins only (with retention policy compliance)

**Retention:**
- **Default:** 2 years
- **Legal Hold:** Indefinite if subject to investigation

**Security:**
- Render disk encryption at rest (platform-level; not application-level)
- Immutable (write-once)
- Centralized logging for audit trail
- Log integrity verification (HMAC signed)

### 7.2 Administrative Actions

**Data Elements:**
- Admin ID (who took the action)
- Action type (create user, delete student, modify retention, etc.)
- Target resource
- Change details
- Timestamp
- Approval status (if required)

**Storage Location:**
```
Database: admin_audit_log table
Retention: 2 years
```

**Access:**
- **Read:** Admins, compliance officer
- **Write:** System (automatic)

**Retention:**
- 2 years

**Security:**
- Immutable
- Render disk encryption at rest (platform-level; not application-level)
- Signed and timestamped

---

## 8. Summary Statistics and Reporting Data

### 8.1 Institutional Reports

**Data Elements:**
- Institution ID
- Date range
- Total submissions scored
- Flagging rate (%)
- False positive rate (%)
- Average deviation score
- Action distribution (escalate, monitor, clear)

**Storage Location:**
```
Database: institutional_stats table
or computed on-demand from scoring_results
```

**Access:**
- **Read:** Institution admin, teachers
- **Write:** System (generated)

**Retention:**
- Indefinite (historical metrics)

**Security:**
- Aggregated (no individual student identification)
- De-identified

### 8.2 System Health Metrics

**Data Elements:**
- API uptime
- Average response time
- Error rates
- Cache hit rate
- Database query performance
- Model accuracy metrics

**Storage Location:**
```
Time-series database: Prometheus, InfluxDB (optional)
Retention: 1 year
```

**Access:**
- **Read:** Ops team, admins
- **Write:** System

**Retention:**
- 1 year rolling window

**Security:**
- No student data
- Operational only

---

## 9. Data Access Control Matrix

| Role | PII Access | Submission Text | Baselines | Scores | Decisions | Audit Logs | Delete Capability |
|------|------------|-----------------|-----------|--------|-----------|------------|------------------|
| Student | Own only | Own only | View profile only | Own only | Own only | No | Request own deletion |
| Teacher | Enrolled students | Enrolled courses | Own submissions | Enrolled courses | Own decisions | No | No |
| Admin | All | All | All | All | All | Yes | Yes, with confirmation |
| Compliance Officer | Sensitive queries | Audit only | Audit only | Audit only | Audit only | Yes | No |

---

## 10. Data Deletion Procedures

### 10.1 Automatic Deletion

> **Planned — not implemented in the pilot stack (no retention scheduler
> runs).** The design below describes the intended future behavior. A
> retention-scheduler with this shape exists only in the dormant v1
> package (`original/core/config.py:135` `DEFAULT_RETENTION_DAYS`,
> `original/api/v1/admin.py:289-290`); no scheduled job runs against the
> live database today. Retention periods in §1 and elsewhere in this
> document are policy targets, not code-enforced triggers, until this is
> built. Today, deletion happens only via the manual path in §10.2.

**Trigger (planned):** Student reaches retention period (default 1 year after last activity)

**Scope (planned):**
1. Baseline samples (all for student)
2. Submissions (all for student)
3. Scoring results (all related submissions)
4. Instructor decisions (soft-delete; metadata retained)
5. Feature vectors (all)
6. Student enrollment records (cascade delete)
7. Student record itself (only if no remaining data)

**Process (planned):**
```python
def delete_student_data(student_id):
  1. Begin transaction
  2. Delete from instructor_decisions (by submission)
  3. Delete from scoring_results (by submission)
  4. Delete from submissions (by student_id)
  5. Delete from baseline_samples (by student_id)
  6. Delete from student_enrollments (by student_id)
  7. Mark student as deleted (soft-delete if audit required)
  8. Commit transaction
  9. Log deletion event with timestamp
```

### 10.2 Manual Deletion

**Trigger:** Student or school requests deletion via FERPA request

**Procedure:** Run `original.cli.delete_student --student-id [ID] --confirm`

**Confirmation:** Requires both:
- `--confirm` flag on command line
- Operator confirmation prompt before deletion

**Scope:** Deletes the student's baselines, submissions, scoring results,
and enrollment records via `store.delete_student()` (`original/store.py:1027`)
— the real, live implementation this section describes. The §10.1 scope
list above documents the same intended coverage for the (not-yet-built)
automatic path.

**Audit Trail:** Deletion logged with timestamp, reason, and operator

---

## 11. Data Handling Procedures

### 11.1 Data Export (Student Request)

**Request Method:** Student submits SAR (Subject Access Request) to institution

**Institution Routes Request to Original**

**Original Response:** Provides ZIP containing:
- Student profile (demographics)
- All submissions (including raw text, which is stored — see §3.1)
- All baseline samples (with feature vectors)
- All scoring results
- All instructor decisions
- Audit log excerpts (for own data only)

**Format:** CSV, JSON, or structured XML

**Delivery:** Secure download link (48-hour expiry) or encrypted email

**Timeline:** 30 days from request

### 11.2 Data Portability

**Request Method:** Student requests data in portable format

**Original Response:** Exports all data in CSV/JSON

**Format:** Standard, non-proprietary formats

**Timeline:** 30 days from request

### 11.3 Data Correction

**Request Method:** Student notifies school of inaccuracy

**School Forwards to Original**

**Original Action:** Corrects PII, flags feature vectors as stale

**Validation:** Requires institutional authorization

**Timeline:** 10 business days

---

## 12. Third-Party Data Sharing

**Current Practice:** Original does NOT share student data with third parties.

**Exceptions:**
- Cloud hosting provider (Render — infrastructure only; data at rest benefits from Render's platform-level disk encryption, see `docs/encryption_policy.md`)
- Monitoring vendor (anonymized metrics only)

**All Exceptions:** Require school's written approval

---

## 13. Compliance Checklist

- [ ] DPA signed with institution
- [ ] Student privacy notice provided
- [ ] Retention policy documented
- [ ] Deletion procedures tested
- [ ] Access controls enforced
- [ ] Audit logging enabled
- [ ] Encryption keys rotated annually
- [ ] Security audit completed (SOC 2 or equivalent)
- [ ] Staff trained on FERPA compliance
- [ ] Breach notification procedures documented
- [ ] Data inventory reviewed (annually)

---

**END OF INVENTORY**

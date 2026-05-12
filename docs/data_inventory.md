# Student Data Inventory

**Last Updated:** 2026-03-25
**Classification:** Internal / Sensitive
**Compliance:** FERPA, GDPR, CCPA

This document provides a complete inventory of all student data collected, processed, and stored by Original.

---

## 1. Data Inventory Overview

| Category | Data Type | Collection Method | Retention | Access | Encryption |
|----------|-----------|-------------------|-----------|--------|------------|
| PII | Student name, ID, email | LTI / Canvas API | 1 year after relationship | Teachers, Admins | AES-256 |
| Submissions | Essay text, metadata | Student upload | 1 year after submission | Student, Teachers | AES-256 |
| Baseline | Authorized writing samples | Instructor upload | Duration + 1 year | Admins, Teachers | AES-256 |
| Results | Authorship scores, vectors | Original computation | 1 year after generation | Student, Teachers | AES-256 |
| Audit | Access logs, decisions | System logging | 2 years | Admins only | AES-256 |

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
- **Automatic Deletion:** Triggers 1 year after last submission or enrollment ends
- **Manual Deletion:** Via `original.cli.delete_student` command

**Security:**
- Encrypted at rest (AES-256-GCM)
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
- Same as student data (1 year after relationship ends)

**Security:**
- Encrypted at rest
- Access controlled by RBAC middleware

---

## 3. Student Writing Samples

### 3.1 Submission Texts

**Data Elements:**
- Raw essay/assignment text (stored as hash only by default)
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
Database: submissions table
Fields: id, student_id, course_id, assignment, text_hash, word_count, char_count, submitted_at, status
Size: ~500 bytes per submission (hash-only)
Optional: raw_text column (encrypted, disabled by default)
```

**Text Hash Computation:**
```python
text_hash = SHA-256(submission_text.encode('utf-8'))
```

**Access:**
- **Read:** Student (own submission), course instructors, admins
- **Write:** Student (create), admins (delete)
- **Raw Text Access:** Disabled by default; enabled only for instructors with explicit "view raw text" permission

**Retention:**
- **Active Period:** For 1 year after submission
- **Automatic Deletion:** Via background job; overwrites with null
- **Manual Deletion:** Via `original.cli.delete_student`

**Security:**
- Text hash computed immediately upon receipt
- Raw text NOT stored by default (privacy-preserving mode)
- If stored: encrypted with institution key (AES-256-GCM)
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
- **Active Period:** For 1 year after student relationship ends
- **Automatic Deletion:** Via background job
- **Manual Deletion:** Via admin interface or delete_student CLI

**Security:**
- Raw text encrypted (AES-256-GCM) if stored
- Feature vector JSON stored unencrypted (non-reversible)
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
- Derived from encrypted baselines
- Not a reversible representation of original text
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
- **Active Period:** 1 year after submission
- **Automatic Deletion:** Via background job
- **Manual Deletion:** Via delete_student CLI

**Security:**
- Encrypted at rest
- Indexed for fast retrieval
- Full audit trail of changes (InstructorDecision table)

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
- **Automatic Deletion:** After 2 years
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
- Encrypted at rest
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
- Encrypted at rest
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

**Trigger:** Student reaches retention period (default 1 year after last activity)

**Scope:**
1. Baseline samples (all for student)
2. Submissions (all for student)
3. Scoring results (all related submissions)
4. Instructor decisions (soft-delete; metadata retained)
5. Feature vectors (all)
6. Student enrollment records (cascade delete)
7. Student record itself (only if no remaining data)

**Process:**
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

**Scope:** Same as automatic deletion

**Audit Trail:** Deletion logged with timestamp, reason, and operator

---

## 11. Data Handling Procedures

### 11.1 Data Export (Student Request)

**Request Method:** Student submits SAR (Subject Access Request) to institution

**Institution Routes Request to Original**

**Original Response:** Provides ZIP containing:
- Student profile (demographics)
- All submissions (with hashes, not raw text by default)
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
- Cloud hosting provider (infrastructure only, encrypted data)
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

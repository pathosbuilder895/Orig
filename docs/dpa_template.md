# Data Processing Agreement (DPA) Template

**BETWEEN:** Original Authorship Verification Platform ("Processor")
**AND:** [Institution Name] ("School")

---

## 1. Purpose and Scope

This Data Processing Agreement (DPA) establishes the terms under which Original serves as a "school official" with legitimate educational interest under the Family Educational Rights and Privacy Act (FERPA, 20 U.S.C. § 1232g) and operates as a Data Processor under applicable data protection laws (GDPR, CCPA, state data privacy laws).

### 1.1 Authorized Uses
Original processes student educational records and personally identifiable information (PII) solely for the following purposes:
- Authorship verification and plagiarism detection
- Building and maintaining student authorship profiles
- Generating academic integrity reports
- Supporting institutional compliance with academic integrity policies

### 1.2 School Official Status
The School designates Original as a "school official" with legitimate educational interest in student academic records pursuant to FERPA 34 CFR § 99.37.

---

## 2. Data Subject to Processing

### 2.1 Categories of Data
Original processes the following categories of student data:
- **Personally Identifiable Information (PII):**
  - Student name
  - Student ID / SIS ID
  - Email address
  - Course enrollment information
  - Instructor name and email

- **Educational Records:**
  - Essay text and written submissions
  - Assignment titles and metadata
  - Submission timestamps
  - Course identifiers
  - Baseline writing samples

- **Derived Data:**
  - Stylometric feature vectors (lexical, syntactic, and linguistic patterns)
  - Authorship probability scores
  - Deviation scores from baseline
  - Quantum-weighted confidence metrics
  - Scoring results and flagging decisions

### 2.2 Data Categories NOT Processed
- Student grades (only submission text)
- Student health or medical records
- Student disciplinary records beyond academic integrity
- Family income or financial aid information
- Biometric data or facial recognition data

---

## 3. Roles and Responsibilities

### 3.1 School's Responsibilities (Data Controller)
The School shall:
- Provide lawful authorization for Original to access student records
- Notify students of Original's use of their data via student handbook or privacy notice
- Maintain parental consent where required by applicable law
- Define the scope of Original's access (which courses, which students)
- Designate an administrator with authority to manage the relationship
- Promptly notify Original of any breach or unauthorized access discovered by the School

### 3.2 Original's Responsibilities (Data Processor)
Original shall:
- Process student data only as directed by the School
- Implement technical and organizational security measures
- Maintain strict access controls (RBAC)
- Not use student data for any purpose other than those authorized
- Cooperate with audit requests and regulatory inquiries
- Delete student data upon request or contract termination
- Notify the School of any suspected breach within 48 hours
- Implement encryption at rest and in transit
- Maintain an audit log of all data access and modifications

---

## 4. Data Security and Confidentiality

### 4.1 Technical Controls
Original implements the following technical security measures:
- **Encryption at Rest:** Student data encrypted using AES-256-GCM
- **Encryption in Transit:** TLS 1.3 for all network communication
- **Access Control:** Role-based access control (RBAC) limiting access to authorized users
- **Authentication:** Multi-factor authentication (MFA) for admin accounts
- **Audit Logging:** All data access logged with timestamp, user, and action
- **Network Security:** Firewall rules, DDoS protection, IP allowlisting
- **Data Isolation:** Student data segregated by institution

### 4.2 Organizational Controls
Original implements the following organizational measures:
- **Data Minimization:** Process only data necessary for authorship verification
- **Purpose Limitation:** Use student data only for authorized purposes
- **Access Restriction:** Only authorized employees access student data
- **Confidentiality Agreements:** All employees sign confidentiality clauses
- **Background Checks:** Security screening of personnel with data access
- **Training:** Annual security and privacy training for all staff
- **Vendor Management:** Third-party subprocessors bound by equivalent commitments

### 4.3 Subprocessors
Original may engage subprocessors (cloud hosting, monitoring services) only with School's written consent. Current subprocessors:
- [Cloud Provider] — Infrastructure hosting
- [Monitoring Vendor] — Security monitoring (optional)

The School may object to new subprocessors by written notice within 10 business days.

---

## 5. Data Subject Rights

### 5.1 Student Access and Transparency
Students have the right to:
- Request access to their own data and authorship profile (via their institution)
- Know what features are extracted from their writing
- Understand how their authorship probability is calculated
- Request correction of inaccurate data
- Request deletion of their data (subject to retention periods)

### 5.2 Exercising Rights
To exercise these rights, students shall submit requests to their institution (School). The School shall forward requests to Original, which shall respond within 30 days.

### 5.3 Right to Deletion
Students may request deletion of their data. Original shall delete:
- All submission text and feature vectors
- All baseline samples and authorship profiles
- All scoring results and audit logs
- All associated metadata

within 30 days of receiving the deletion request, subject to legal holds or retention requirements.

---

## 6. Data Retention and Deletion

### 6.1 Default Retention Period
Original retains student data as follows:
- **Active Period:** For the duration of the School's use of Original's services
- **Retention Period:** One (1) year after the student's final submission or institutional relationship ends
- **Legal Hold:** Longer retention if required by law, regulation, or legal proceeding

### 6.2 Automatic Deletion
After the retention period expires, Original automatically deletes all student data unless the School requests an extension in writing.

### 6.3 Early Deletion
The School may request deletion of any student's data at any time. Original shall complete deletion within 30 days.

### 6.4 Data Destruction
Deleted data is securely destroyed by:
- Overwriting all storage sectors (Gutmann method or equivalent)
- Cryptographic key deletion (making encrypted data unrecoverable)
- Destruction of physical media (if applicable)

---

## 7. Audit Rights and Compliance

### 7.1 Audit Rights
The School and its authorized representatives have the right to:
- Request a security audit report from Original (at most twice per year)
- Conduct onsite security inspections (with reasonable notice)
- Review access logs and data handling procedures
- Interview Original personnel regarding data security
- Request evidence of compliance with this DPA

### 7.2 Regulatory Inquiries
Original shall:
- Cooperate with any regulatory inquiry from the School
- Provide documentation necessary to demonstrate FERPA compliance
- Support audits by state education departments or Department of Education
- Respond to inquiries within 15 business days

### 7.3 Third-Party Audits
Original shall maintain SOC 2 Type II certification or equivalent, updated annually. Original shall provide a copy of the audit report to the School upon request.

---

## 8. Data Breach Notification

### 8.1 Breach Definition
A "Breach" is the unauthorized access, use, or disclosure of student data where reasonable belief exists that the breach compromises the security or privacy of the information.

### 8.2 Notification Timeline
Original shall notify the School of any suspected Breach within 48 hours of discovery.

### 8.3 Breach Notification Content
Original shall provide:
- Description of the Breach and data affected
- Date and time of the Breach
- Likely cause and scope of unauthorized access
- Steps Original has taken to mitigate harm
- Recommendations for additional measures the School should take
- Point of contact at Original for further inquiry

### 8.4 Student Notification
The School is responsible for notifying affected students. Original shall assist as reasonably requested.

### 8.5 Regulatory Notification
Original shall cooperate with any notification required to state attorneys general, credit bureaus, or other regulatory bodies.

---

## 9. Limitations on Data Use

### 9.1 Prohibited Uses
Original shall NOT:
- Use student data for marketing or advertising purposes
- Sell student data to third parties
- Use student data to build general-purpose language models or AI systems
- Share student data with any subprocessor not approved by the School
- Use student data for any purpose other than authorship verification
- Conduct experiments or research using student data without explicit consent

### 9.2 Permitted Uses
Original may:
- Use feature vectors and aggregate statistics to improve the authorship verification model (de-identified)
- Generate institutional reports showing flagging rates, accuracy metrics, and usage statistics
- Maintain audit logs to demonstrate compliance with this DPA
- Use anonymized data for algorithm improvement (no attribution to students)

---

## 10. Term and Termination

### 10.1 Term
This DPA is effective as of [DATE] and continues for the duration of the Service Agreement between Original and the School.

### 10.2 Termination
Either party may terminate this DPA with ninety (90) days' written notice to the other party.

### 10.3 Data Disposition Upon Termination
Upon termination of the Service Agreement or this DPA, Original shall, at the School's election:
- Return all student data to the School in a structured, commonly used format, or
- Delete all student data within thirty (30) days of termination

The School shall provide written instructions for data return or deletion.

---

## 11. Governing Law and Jurisdiction

This DPA shall be governed by the laws of [STATE/COUNTRY], without regard to conflicts of law principles.

Both parties consent to the jurisdiction of the courts of [STATE/COUNTRY] for any dispute arising from this DPA.

---

## 12. Modifications to This DPA

Original may not modify this DPA without the School's written consent. The School shall have thirty (30) days to review and object to any proposed modifications.

If the School objects to material modifications, the School may terminate the Service Agreement without penalty.

---

## 13. Contact Information

### 13.1 School Contact
**Data Protection Officer / Administrator:**
- Name: [NAME]
- Title: [TITLE]
- Email: [EMAIL]
- Phone: [PHONE]

### 13.2 Original Contact
**Data Protection Officer:**
- Email: privacy@originalverification.com
- Phone: +1 (XXX) XXX-XXXX
- Address: [Original's Legal Address]

---

## 14. Appendices

### Appendix A: Processing Instruction Log
[To be maintained by Original — records all changes to data processing scope]

### Appendix B: Subprocessor List
[Current approved subprocessors and service descriptions]

### Appendix C: Security Controls Inventory
[Detailed technical controls, audit results, and compliance certifications]

---

**SIGNATURE PAGE**

**ON BEHALF OF [SCHOOL NAME]:**

Signature: _________________________ Date: _____________

Print Name: ________________________

Title: ________________________

**ON BEHALF OF ORIGINAL AUTHORSHIP VERIFICATION PLATFORM:**

Signature: _________________________ Date: _____________

Print Name: ________________________

Title: ________________________

---

**END OF AGREEMENT**

# Encryption Policy: Data at Rest and In Transit

**Last Updated:** 2026-07-07
**Classification:** Internal / Technical
**Compliance:** FERPA, GDPR, CCPA, HIPAA-adjacent

> **Accuracy note (2026-07-07):** This document previously described an
> AES-256-GCM application-level encryption layer with per-institution keys
> and a PostgreSQL backing store. **None of that is implemented in the live
> pilot stack.** The section below has been rewritten to describe what
> actually runs today. See `docs/ARCHITECTURE.md` for the live-vs-dormant
> split; this document now describes only the live stack
> (`original/api.py` + `demo/`).

This document defines Original's encryption posture for protecting student data both at rest (stored) and in transit (on the network).

---

## 1. Executive Summary

- **Encryption at Rest:** Render's managed-disk encryption (platform-level).
  The application does **not** encrypt row data at the application layer —
  see §2 for what that means in practice.
- **Encryption in Transit:** TLS 1.3 (minimum), terminated at the Render edge.
- **Key Management:** The only cryptographic key material the application
  itself manages is an RSA key pair used for LTI JWT signing
  (`original/canvas/keys.py`) — see §2.3. There are no per-institution
  encryption keys and no application-level master key.
- **Non-reversibility as a substitute control:** Stylometric feature vectors
  (the primary derived artifact the scoring pipeline relies on) are
  non-reversible by construction — they cannot be inverted back into the
  original text. This is a safe-by-construction property, not encryption,
  and it does not apply to the raw text itself (see §2.1).
- **Compliance:** Meets FERPA's "reasonable methods" standard for a
  school-official processor at current pilot scale. Does not claim SOC 2 or
  HIPAA-level controls. See `docs/dpa_template.md` for the DPA-level
  commitments (its banner explicitly forbids aspirational security claims —
  this document is held to the same bar).

---

## 2. Encryption at Rest

### 2.1 Storage Scope — what is actually true today

The live store is a single SQLite database file
(`original/store.py:41`, `_DB_PATH = os.environ.get("ORIGINAL_DB", …)`,
opened via `sqlite3.connect`). It is **not** PostgreSQL, and there is
**no** application-level encryption of the data inside it.

| Data Type | Application-level encryption | At-rest protection | Stored Where |
|-----------|------------------------------|---------------------|--------------|
| Student PII | None | Render disk encryption (platform) | SQLite (`original_db`) |
| Submission text (raw) | None | Render disk encryption (platform) | SQLite (`original_db`) |
| Baseline text (raw) | None | Render disk encryption (platform) | SQLite (`original_db`) |
| Feature vectors | None (non-reversible by construction, not by encryption) | Render disk encryption (platform) | SQLite (`original_db`) |
| Scoring results | None | Render disk encryption (platform) | SQLite (`original_db`) |
| Audit logs | None | Render disk encryption (platform) | SQLite (`original_db`) |
| Admin credentials | bcrypt hash (one-way, not encryption) | Render disk encryption (platform) | SQLite (`original_db`) |
| API tokens | HMAC-SHA256 hash (one-way, not encryption) | Render disk encryption (platform) | SQLite (`original_db`) |
| LTI signing key | RSA private key, `NoEncryption()` PEM serialization (see §2.3) | Render disk encryption (platform) | Environment variable or in-process cache |

**What "Render disk encryption (platform)" means:** Render's managed disks
are encrypted at rest as part of the hosting platform's infrastructure
guarantee. This is **not** something Original implements — it is inherited
from the hosting provider, the same way any application hosted on Render
inherits it. It protects against physical theft of the underlying storage
media. It does **not** protect data from anyone with authorized application
or database access (which is the threat model application-level encryption
would address, and which this stack does not implement).

**Practical implication:** raw baseline and submission text is stored in
plain, readable form in the SQLite database (subject only to OS/file
permissions and Render's platform-level disk encryption). It is retrievable
by authorized instructors via the live endpoint
`GET /students/{id}/samples/{index}/text` (`original/api.py:889`). This
matches `PILOT_RUNBOOK.md:150` ("Raw text is stored.") and should not be
described elsewhere as encrypted or hashed-only.

**Why this is an acceptable posture for the pilot, not a gap to hide:**
access to raw text is gated by the app's own authn/authz (principal tokens,
RBAC), not by encryption. The scoring pipeline's derived artifact — the
feature vector — is non-reversible by construction, so even if the vector
alone were exposed it cannot be turned back into the student's writing.
That is a different (and weaker) guarantee than encrypting the raw text
itself, and this document should not conflate the two.

### 2.2 Encryption Algorithm

There is no AES-GCM (or any other symmetric-cipher) implementation
anywhere in the live `original/` package
(`grep -rniE "aes|fernet|GCM" original/ --include=*.py` returns nothing
outside the dormant v1 stack and tests). Any prior version of this document
describing an `encrypt_data` / `decrypt_data` AES-256-GCM implementation,
PBKDF2-derived per-institution keys, or a master key for audit logs was
describing a design that was never built. That content has been removed
from this document rather than left in place as an aspirational claim.

### 2.3 The one real cryptographic key material: LTI RSA keys

The only cryptography the application itself manages is the RSA key pair
used to sign LTI 1.3 JWTs for Canvas launches
(`original/canvas/keys.py`).

**What it is:**
- A 2048-bit RSA key pair (`_KEY_SIZE = 2048`, `canvas/keys.py:28-30`,
  using `cryptography.hazmat`).
- Used to sign JWTs for LTI launch/JWKS flows (`jose_jwt` signing) so
  Canvas can verify the tool's identity.
- Loaded from `LTI_PRIVATE_KEY_PEM` (or generated fresh at process start if
  unset) and cached for the process lifetime (`@lru_cache`,
  `canvas/keys.py`).

**How it's stored at rest today:** when the private key is serialized to
PEM (`get_private_key_pem()`, `canvas/keys.py:91`), it uses
`serialization.NoEncryption()` — i.e., the PEM is **not**
passphrase/cipher-protected at the serialization layer. Stated plainly
rather than glossed over: the private key material's confidentiality
currently rests on (a) not persisting the PEM to disk outside the
environment-variable / in-memory path, and (b) Render's platform-level
protections around environment variables and disk. There is no
application-level encryption wrapping this key today.

**Key rotation:** there is no automated rotation. Rotating the key means
setting a new `LTI_PRIVATE_KEY_PEM` and restarting the process, which
generates a new `kid` and requires re-registering the JWKS with Canvas.

---

## 3. Encryption in Transit

### 3.1 TLS Configuration

All network communication to/from Original is encrypted using TLS 1.3 (minimum).

**Protocol:** TLS 1.3 (RFC 8446)
**Fallback:** TLS 1.2 (if client doesn't support TLS 1.3)
**Minimum Key Exchange:** 2048-bit RSA or 256-bit ECDH

### 3.2 Certificate Management

#### 3.2.1 Server Certificates

**Certificate Authority:** Let's Encrypt (free, automatic renewal)
**Duration:** 90 days (auto-renewed at 30-day mark)
**Key Size:** 2048-bit RSA (or 256-bit ECDSA for modern clients)

**Configuration (nginx):**
```nginx
server {
    listen 443 ssl http2;
    server_name api.originalverification.com;

    ssl_certificate /etc/letsencrypt/live/api.originalverification.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.originalverification.com/privkey.pem;

    ssl_protocols TLSv1.3 TLSv1.2;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
    ssl_prefer_server_ciphers on;

    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_stapling on;
}
```

#### 3.2.2 Client Certificates (Optional)

For sensitive integrations (Canvas, institutions), Original can require mutual TLS (mTLS):

**Configuration:**
```nginx
ssl_client_certificate /etc/original/ca-bundle.pem;
ssl_verify_client optional;
ssl_verify_depth 2;
```

**Use Cases:**
- Canvas LTI launches (verify Canvas identity)
- System-to-system API calls (verify caller identity)

### 3.3 HSTS (HTTP Strict Transport Security)

Enforces TLS for all future connections.

**Header:**
```
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
```

**Effect:**
- Browsers cache this policy for 1 year
- All http:// requests redirected to https://
- Prevents downgrade attacks

### 3.4 Perfect Forward Secrecy (PFS)

All TLS configurations use ephemeral key exchanges (ECDHE, DHE) to ensure forward secrecy:

- If server private key is compromised in the future, past encrypted sessions remain secure
- Recommended cipher suites:
  - ECDHE-ECDSA-AES128-GCM-SHA256
  - ECDHE-RSA-AES128-GCM-SHA256
  - ECDHE-RSA-CHACHA20-POLY1305

### 3.5 API Transport Security

#### 3.5.1 Authentication Headers

All API requests include Bearer tokens transmitted over TLS:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Token Security:**
- Tokens contain no sensitive data
- Tokens expire (access: 15 min, refresh: 7 days)
- Tokens are signed (HMAC-SHA256) and verified server-side

#### 3.5.2 Request Validation

Original validates all incoming requests:

```python
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Validate TLS
        if request.client.scheme != 'https':
            return Response("HTTPS required", status_code=403)

        # Validate Host header
        if request.headers.get('host') not in ALLOWED_HOSTS:
            return Response("Invalid Host header", status_code=403)

        response = await call_next(request)

        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'"

        return response
```

### 3.6 Data in Flight: Database Connections

There is no network database connection to secure — the live store is a
local SQLite file accessed in-process via `sqlite3.connect`
(`original/store.py:41,63`), not a client/server database reached over the
network. This section previously described a PostgreSQL connection string
with `sslmode=require`; that describes the dormant v1 stack's intended
design, not the live pilot, and has been removed rather than left as a
misleading claim.

---

## 4. Data Lifecycle (accurate to the live stack)

### 4.1 Data Creation

1. **Receive:** User submits essay text via web form or API.
2. **Validate:** Check text size, encoding, format.
3. **Hash:** Compute SHA-256 hash (used for deduplication).
4. **Store:** Write the raw text and its hash to SQLite. There is no
   application-level encryption step — see §2.1.
5. **Log:** Record the action in the application's audit trail.

### 4.2 Data Access

1. **Request:** Instructor requests a student's raw baseline/submission
   text via `GET /students/{id}/samples/{index}/text`.
2. **Authorize:** The endpoint checks the caller's role/permissions
   (principal token + RBAC).
3. **Read:** Retrieve the plain-text row from SQLite — there is no
   decryption step, because the text was never encrypted.
4. **Display:** Show the text in the UI.
5. **Log:** Record the access.

### 4.3 Data Deletion

Two real paths exist; there is no third automatic path (see §4.3.1).

**Manual deletion (real, live):**
- `store.delete_student()` (`original/store.py:1027`) deletes a student's
  data (baselines, submissions, scoring results, enrollments) from SQLite.
- The CLI `python -m original.cli.delete_student` wraps this for
  operator-initiated deletion (e.g., in response to a FERPA request), and
  requires an explicit `--confirm` plus an interactive confirmation prompt.
- Deletion is logged with a timestamp.

**Automatic/scheduled deletion:**
> **Planned — not implemented in the pilot stack.** A retention-scheduler
> ("delete after N days automatically") exists only in the dormant v1
> package (`original/core/config.py:135` `DEFAULT_RETENTION_DAYS`,
> `original/api/v1/admin.py:289-290`). No scheduled job runs against the
> live database. Retention today is enforced by policy and manual deletion,
> not by code.

### 4.4 Data Backup

Backups are file-level copies of the SQLite database directory
(`BACKUP_DIR`, `BACKUP_INTERVAL_MINUTES`, `BACKUP_KEEP` env vars govern an
in-app backup routine — see `docs/OPS_RUNBOOK.md`). Backups inherit
whatever at-rest protection the underlying storage provides (Render disk
encryption); the application does not apply a separate encryption layer to
backup files. There is no S3/AWS KMS backup path in the live stack — any
prior claim to that effect described infrastructure that was never
provisioned.

---

## 5. Key Rotation

- **LTI RSA signing key** (`canvas/keys.py`): no automated rotation exists
  today. Rotating it means setting a new `LTI_PRIVATE_KEY_PEM` and
  restarting the process, then re-registering the resulting JWKS `kid`
  with Canvas. See §2.3.
- **TLS certificates:** managed automatically by Render at the edge; not
  something the application configures.
- There is no institution-key or master-key rotation process, because
  those keys do not exist (see §2.2).

---

## 6. Compliance Verification

### 6.1 Honest Posture Checklist

- [x] Render platform-level disk encryption at rest
- [x] TLS 1.3 (minimum) for all traffic, terminated at the Render edge
- [x] Admin credentials hashed (bcrypt, one-way)
- [x] API tokens hashed (HMAC-SHA256, one-way)
- [x] LTI RSA key pair used for JWT signing (`canvas/keys.py`)
- [x] Feature vectors non-reversible by construction
- [x] Manual deletion path (`delete_student`) implemented and auditable
- [ ] Application-level encryption of row data — **not implemented**
- [ ] Per-institution encryption keys — **not implemented**
- [ ] Automatic/scheduled data deletion — **not implemented** (manual only)
- [ ] SOC 2 Type II or equivalent third-party audit — **not completed**

This checklist intentionally replaces the previous "all boxes checked"
version, which asserted controls (AES-256-GCM at rest, PBKDF2-derived
per-institution keys, SOC 2 verification) that do not exist. Per
`docs/dpa_template.md`'s own banner, this document does not make
aspirational security claims.

### 6.2 TLS Testing

**Manual Testing:**
```bash
# Verify TLS configuration
openssl s_client -connect <render-host>:443 -servername <render-host>

# Verify cipher suite / protocol version
curl -I --tlsv1.3 https://<render-host>/health
```

There is no encryption/decryption round-trip test to run at the
application layer, because the application does not implement
application-level encryption.

---

## 7. Environment / Secret Handling

**What secrets actually exist in the live stack:**
- `LTI_PRIVATE_KEY_PEM` / `LTI_PRIVATE_KEY_FILE` — the RSA signing key
  material described in §2.3.
- `MAINTENANCE_TOKEN` — guards destructive admin operations (see
  `docs/OPS_RUNBOOK.md`; owned by the ops-runbook documentation, not this
  policy).
- Admin/API credentials, stored hashed (not this document's concern —
  they are never stored in reversible form to begin with).

There is no `MASTER_ENCRYPTION_KEY` or `INSTITUTION_SECRET_<INST_ID>` in
the live stack; both were part of the fictional application-encryption
design described in earlier revisions of this document and have been
removed. Standard practice still applies to whatever secrets do exist:
keep them out of source control, inject via environment variables or a
secrets manager, and never log them.

---

## 8. Incident Response

### 8.1 Suspected LTI Key Compromise

1. Rotate `LTI_PRIVATE_KEY_PEM` immediately (see §5).
2. Re-register the new JWKS with affected Canvas instances.
3. Review LTI launch logs for anomalous activity under the old key.
4. Notify affected institutions per the DPA's breach-notification terms
   (`docs/dpa_template.md`) if unauthorized use is confirmed.

### 8.2 Suspected Unauthorized Data Access

Because there is no encryption layer to "fail," an incident here means
unauthorized access to the plain SQLite data or to an authenticated
endpoint. Response follows `docs/INCIDENT_RESPONSE.md` (see WS-3 task 7):
contain access (rotate credentials/tokens), assess scope via audit logs,
notify per the DPA's 48-hour commitment if confirmed, publish a
post-mortem.

---

## 9. References

- RFC 8446: TLS 1.3
- FERPA 34 CFR 99.3 (Definitions)
- GDPR Article 32 (Security of Processing)
- CCPA § 1798.150 (Data Security)
- `docs/ARCHITECTURE.md` — live vs. dormant stack split
- `docs/dpa_template.md` — DPA-level commitments and its no-aspirational-claims banner
- `original/canvas/keys.py` — LTI RSA key implementation
- `original/store.py` — SQLite store implementation

---

**END OF POLICY**

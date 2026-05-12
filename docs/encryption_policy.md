# Encryption Policy: Data at Rest and In Transit

**Last Updated:** 2026-03-25
**Classification:** Internal / Technical
**Compliance:** FERPA, GDPR, CCPA, HIPAA-adjacent

This document defines Original's encryption standards for protecting student data both at rest (stored) and in transit (on the network).

---

## 1. Executive Summary

Original implements industry-standard encryption to protect all sensitive student data:

- **Encryption at Rest:** AES-256-GCM (authenticated encryption)
- **Encryption in Transit:** TLS 1.3 (minimum)
- **Key Management:** Secure key derivation (PBKDF2), per-institution keys
- **Compliance:** Exceeds FERPA, GDPR, and CCPA requirements

---

## 2. Encryption at Rest

### 2.1 Storage Scope

All sensitive student data is encrypted at rest by default:

| Data Type | Encryption | Key | Stored Where |
|-----------|-----------|-----|--------------|
| Student PII | AES-256-GCM | Institution key | PostgreSQL database |
| Submission text (raw) | AES-256-GCM | Institution key | PostgreSQL database |
| Baseline text (raw) | AES-256-GCM | Institution key | PostgreSQL database |
| Feature vectors | None (non-reversible) | N/A | PostgreSQL database |
| Scoring results | AES-256-GCM | Institution key | PostgreSQL database |
| Audit logs | AES-256-GCM | Master key | PostgreSQL database |
| Admin credentials | bcrypt hash | N/A | PostgreSQL database |
| API tokens | HMAC-SHA256 hash | N/A | PostgreSQL database |
| Temporary files | AES-256-GCM | Institution key | Encrypted temp storage |

### 2.2 Encryption Algorithm: AES-256-GCM

**Standard:** AES (Advanced Encryption Standard)
**Mode:** GCM (Galois/Counter Mode)
**Key Length:** 256 bits (32 bytes)
**IV Length:** 128 bits (16 bytes, randomly generated per encryption)
**Tag Length:** 128 bits (16 bytes for authentication)

**Properties:**
- Provides both confidentiality and authenticity
- Prevents tampering with encrypted data
- Authenticated encryption (AEAD)
- No separate MAC computation needed
- Hardware-accelerated (AES-NI) on modern CPUs

**Implementation:**

```python
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
import os

def encrypt_data(plaintext: bytes, institution_key: bytes) -> bytes:
    """
    Encrypt data using AES-256-GCM.

    Format: [IV (16 bytes)][Ciphertext (variable)][Tag (16 bytes)]
    """
    iv = os.urandom(16)  # Generate random IV
    cipher = AESGCM(institution_key)
    ciphertext = cipher.encrypt(iv, plaintext, None)

    # ciphertext includes the authentication tag at the end
    return iv + ciphertext

def decrypt_data(encrypted: bytes, institution_key: bytes) -> bytes:
    """
    Decrypt data using AES-256-GCM.

    Raises cryptography.exceptions.InvalidTag if tag verification fails.
    """
    iv = encrypted[:16]
    ciphertext_with_tag = encrypted[16:]

    cipher = AESGCM(institution_key)
    plaintext = cipher.decrypt(iv, ciphertext_with_tag, None)

    return plaintext
```

### 2.3 Key Derivation: PBKDF2

Institution encryption keys are derived from institution secrets using PBKDF2.

**Standard:** PBKDF2 (Password-Based Key Derivation Function 2)
**Hash Function:** SHA-256
**Iterations:** 480,000 (NIST recommendation as of 2024)
**Salt Length:** 32 bytes (randomly generated per institution)

**Process:**

```python
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
from cryptography.hazmat.primitives import hashes

def derive_institution_key(institution_secret: str, salt: bytes) -> bytes:
    """
    Derive a 256-bit encryption key from an institution secret.

    Args:
        institution_secret: Institution-specific secret (e.g., from API)
        salt: Random salt (stored in database)

    Returns:
        32-byte encryption key (AES-256)
    """
    kdf = PBKDF2(
        algorithm=hashes.SHA256(),
        length=32,  # 256 bits
        salt=salt,
        iterations=480000,
    )

    key = kdf.derive(institution_secret.encode('utf-8'))
    return key
```

**Key Derivation Timeline:**
- Institution secret configured: ~10 seconds (PBKDF2 is intentionally slow)
- Key derives once and is cached in memory
- Re-derives on server restart or key rotation

### 2.4 Key Management

#### 2.4.1 Institution Keys

**Creation:** Each institution receives a unique encryption key upon setup.

**Storage:** Keys are derived from institution secrets stored in environment variables:
```
INSTITUTION_SECRET_<INST_ID>=<secret>
```

**Rotation:** Institution secrets can be rotated via admin interface:
1. Admin initiates key rotation
2. System generates new salt
3. Data is re-encrypted with new key
4. Old key is archived (for decryption of old data if needed)

**Access Control:** Only institution administrators can initiate key rotation.

**Backup:** Institution secrets are backed up in secure vault (separate from database).

#### 2.4.2 Master Key (for Audit Logs)

**Purpose:** Encrypts audit logs (which contain references to all student data)

**Storage:** Master key stored in environment variable:
```
MASTER_ENCRYPTION_KEY=<base64-encoded 32-byte key>
```

**Access:** Only application server and backup systems have access

**Rotation:** Master key rotated annually (or on suspected breach)

**Process:**
1. New master key generated
2. All audit logs re-encrypted with new key
3. Old key archived in secure vault
4. Date of rotation logged

#### 2.4.3 Key Distribution

**Development Environment:**
```
# .env file (not in version control)
INSTITUTION_SECRET_DEV_INST=dev-secret-string
MASTER_ENCRYPTION_KEY=base64-encoded-key
```

**Production Environment:**
```
# AWS Secrets Manager, HashiCorp Vault, or equivalent
INSTITUTION_SECRET_<INST_ID>=retrieved-from-vault
MASTER_ENCRYPTION_KEY=retrieved-from-vault
```

**Never:** Hard-coded in source code, logs, or version control

### 2.5 Database-Level Encryption (Optional)

In addition to application-level encryption, institutions can enable database-level encryption:

**PostgreSQL Transparent Data Encryption (TDE):**
```
# Not natively supported; use pgcrypto extension + triggers
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

**AWS RDS Encryption:**
```
# Enable AWS KMS encryption at RDS instance level
Enable Encryption: Yes
KMS Key: aws/rds (or customer-managed key)
```

**Benefits:** Protects against physical theft of database drives

**Trade-off:** Minimal performance impact (~2-5% overhead)

**Recommendation:** Enable for all production deployments

### 2.6 Temporary File Encryption

Temporary files (uploads, processing artifacts) are encrypted before writing to disk.

**Process:**
```python
import tempfile
from pathlib import Path

def create_encrypted_temp_file(content: bytes, institution_key: bytes) -> Path:
    """
    Create a temporary file with encrypted content.
    """
    encrypted = encrypt_data(content, institution_key)

    temp_path = Path(tempfile.gettempdir()) / f"original_{uuid.uuid4()}.tmp"
    temp_path.write_bytes(encrypted)

    return temp_path
```

**Cleanup:** Temporary files are deleted immediately after use (securely overwritten)

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

Database connections from the application server to PostgreSQL use TLS:

**Configuration (connection string):**
```
postgresql://user:password@db.example.com:5432/original_db?sslmode=require
```

**Options:**
- `sslmode=require` — TLS required; fail if unavailable
- `sslmode=prefer` — TLS preferred; fall back to unencrypted (NOT recommended)

**Certificate Verification:**
```
postgresql://user:password@db.example.com:5432/original_db?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-bundle.crt
```

---

## 4. Encryption Lifecycle

### 4.1 Data Creation

1. **Receive:** User submits essay text via web form or API
2. **Validate:** Check text size, encoding, format
3. **Hash:** Compute SHA-256 hash for deduplication
4. **Encrypt:** Encrypt using institution key (AES-256-GCM)
5. **Store:** Write encrypted blob to database
6. **Log:** Record action in audit log (encrypted)

### 4.2 Data Access

1. **Request:** Instructor requests student submission
2. **Authorize:** Verify instructor has access to course/student
3. **Decrypt:** Retrieve encrypted blob from database; decrypt using institution key
4. **Display:** Show decrypted text in UI
5. **Log:** Record access in audit log (encrypted)

### 4.3 Data Deletion

1. **Trigger:** Student requests deletion or retention period expires
2. **Verify:** Confirm deletion authorized
3. **Delete:** Delete encrypted blob from database
4. **Overwrite:** Secure overwrite of freed storage (TRIM command)
5. **Log:** Record deletion in audit log (encrypted)

### 4.4 Data Backup

1. **Schedule:** Daily encrypted backups to cloud storage
2. **Encryption:** Backups encrypted with master key (separate from application keys)
3. **Storage:** Backups stored in S3 with server-side encryption (AWS KMS)
4. **Rotation:** Backups retained for 90 days; older backups deleted
5. **Testing:** Restore process tested monthly

**Backup Configuration:**
```bash
#!/bin/bash
# Backup script with encryption

BACKUP_FILE="/backups/original_db_$(date +%Y%m%d_%H%M%S).sql.enc"

# Dump database
pg_dump postgresql://... | \
  # Encrypt with master key
  openssl enc -aes-256-cbc -K $MASTER_ENCRYPTION_KEY -out $BACKUP_FILE

# Upload to S3
aws s3 cp $BACKUP_FILE s3://original-backups/ \
  --sse aws:kms --sse-kms-key-id arn:aws:kms:...

# Cleanup local backup
shred -vfz -n 10 $BACKUP_FILE
```

---

## 5. Key Rotation

### 5.1 Schedule

- **Master Key:** Annually (or on suspected breach)
- **Institution Keys:** Annually or on institution request
- **TLS Certificates:** Automatically (Let's Encrypt, 90-day renewal)

### 5.2 Rotation Process

#### Master Key Rotation:

```python
def rotate_master_key(old_key: bytes, new_key: bytes):
    """
    Re-encrypt all audit logs with the new master key.
    """
    session = SessionLocal()

    # Retrieve all audit log entries
    entries = session.query(AuditLog).all()

    for entry in entries:
        # Decrypt with old key
        plaintext = decrypt_data(entry.encrypted_data, old_key)

        # Re-encrypt with new key
        entry.encrypted_data = encrypt_data(plaintext, new_key)

    session.commit()

    # Log rotation
    log.info(f"Master key rotated at {datetime.utcnow().isoformat()}")
```

#### Institution Key Rotation:

1. Admin initiates rotation via API
2. System generates new salt
3. All institution data re-encrypted with new key
4. Old key archived
5. Completion logged

---

## 6. Compliance Verification

### 6.1 Encryption Audit Checklist

- [ ] All sensitive data encrypted at rest (AES-256-GCM)
- [ ] All network connections use TLS 1.3 (minimum)
- [ ] Encryption keys rotated annually
- [ ] Key rotation process tested
- [ ] Backup encryption enabled (separate key from application)
- [ ] Database connection encrypted (sslmode=require)
- [ ] HSTS header enabled
- [ ] Perfect forward secrecy enabled
- [ ] Certificate validity checked monthly
- [ ] Encryption key derivation using PBKDF2 (480k iterations)
- [ ] No unencrypted data in logs or temporary files
- [ ] Encryption verified via security audit (SOC 2 Type II)

### 6.2 Encryption Testing

**Manual Testing:**
```bash
# Verify TLS configuration
openssl s_client -connect api.originalverification.com:443 \
  -servername api.originalverification.com

# Check certificate validity
openssl x509 -in cert.pem -text -noout

# Verify cipher suite
curl -I --tlsv1.3 https://api.originalverification.com/health
```

**Automated Testing:**
```python
# Test encryption/decryption round-trip
plaintext = b"sensitive student data"
key = os.urandom(32)
encrypted = encrypt_data(plaintext, key)
decrypted = decrypt_data(encrypted, key)
assert decrypted == plaintext
```

---

## 7. Key Storage Best Practices

### 7.1 Environment Variables

**Development:**
```
# .env (not in git)
MASTER_ENCRYPTION_KEY=base64-encoded-key
INSTITUTION_SECRET_DEV=dev-secret
```

**Production:**
```
# AWS Secrets Manager, HashiCorp Vault, or similar
export MASTER_ENCRYPTION_KEY=$(aws secretsmanager get-secret-value \
  --secret-id original/master-key \
  --query 'SecretString' --output text)
```

### 7.2 Hardware Security Module (HSM)

For high-security deployments, consider using a Hardware Security Module (HSM) to store master keys:

**Options:**
- AWS CloudHSM
- Thales Luna HSM
- YubiKey (for administrative access)

**Benefits:**
- Keys never leave HSM in plaintext
- Tamper-resistant hardware
- Compliance with FIPS 140-2 Level 3

---

## 8. Incident Response

### 8.1 Suspected Encryption Key Compromise

**Steps:**
1. Immediately disable the compromised key
2. Generate new encryption key
3. Alert all institutions
4. Re-encrypt all data with new key
5. Audit logs for unauthorized access (using decryption attempt logs)
6. Notify students and regulators if breach confirmed
7. Publish post-mortem (redacted)

### 8.2 Backup Key Access

If a backup key is accessed/compromised:
1. Quarantine backup in secure storage
2. Decrypt backup with new key
3. Destroy old backup
4. Verify data integrity

---

## 9. References

- NIST SP 800-38D: Recommendation for Block Cipher Modes of Operation: Galois/Counter Mode (GCM)
- NIST SP 800-132: PBKDF2 Recommendations
- RFC 8446: TLS 1.3
- FERPA 34 CFR 99.3 (Definitions)
- GDPR Article 32 (Security of Processing)
- CCPA § 1798.150 (Data Security)

---

**END OF POLICY**

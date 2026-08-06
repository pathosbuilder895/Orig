#!/usr/bin/env python3
"""backup_offbox.py — push the newest on-disk backup to S3-compatible object storage.

Closes the gap described in ``docs/OPS_RUNBOOK.md`` §Backups: ``original/backup.py``
(and its manual twin ``scripts/backup_db.sh``) write consistent SQLite backups to
``BACKUP_DIR``, but that directory lives on the *same* Render disk as the live
database — a disk loss takes the backups with it. This script copies the newest
backup off-box to object storage using a hand-rolled AWS SigV4 signer (stdlib
``hmac``/``hashlib`` only — no new dependency), so it works against real S3,
Cloudflare R2, Backblaze B2 (S3-compatible), MinIO, or DigitalOcean Spaces alike.

**No-op without config** (matches this repo's env-flag philosophy — see
CLAUDE.md's flag table): unless ``BACKUP_OFFBOX_ENABLED=1`` *and* a bucket,
endpoint, and credentials are all set, this script logs why it's skipping and
exits 0. It never invents or hardcodes a bucket/endpoint/credential.

Configuration (env):
    BACKUP_OFFBOX_ENABLED           "1" to actually upload. Default "0" (no-op).
    BACKUP_OFFBOX_BUCKET            destination bucket name. Required.
    BACKUP_OFFBOX_ENDPOINT          S3-compatible endpoint, e.g.
                                     "https://s3.us-east-1.amazonaws.com" or
                                     "https://<accountid>.r2.cloudflarestorage.com".
                                     Required.
    BACKUP_OFFBOX_ACCESS_KEY_ID     access key. Required.
    BACKUP_OFFBOX_SECRET_ACCESS_KEY secret key. Required. Never log this value.
    BACKUP_OFFBOX_REGION            signing region. Default "us-east-1"
                                     (R2/MinIO/B2 generally accept "auto" or
                                     "us-east-1" — check your provider).
    BACKUP_OFFBOX_PREFIX            key prefix within the bucket.
                                     Default "original-backups/".
    BACKUP_OFFBOX_URL_STYLE         "path" (default) or "virtual". Path-style
                                     (``{endpoint}/{bucket}/{key}``) works
                                     everywhere including MinIO/R2; virtual-hosted
                                     (``{bucket}.{endpoint-host}/{key}``) is what
                                     AWS prefers for new S3 buckets.
    BACKUP_DIR                      source directory of on-disk backups
                                     (same variable ``original/backup.py`` uses).

Usage:
    scripts/backup_offbox.py                 # upload the newest local backup
    scripts/backup_offbox.py /path/to/file.db # upload a specific file

Exit codes: 0 on success or clean no-op (disabled/unconfigured), 1 on any
attempted-but-failed upload (missing local backup, network/auth error, etc.)
so a cron/Render-cron-job wrapper sees a real failure signal.

Intended wiring (see docs/OPS_RUNBOOK.md): a Render cron job running this
script every 30-60 min, since Render web services have no crontab of their
own (the same constraint that pushed the on-disk scheduler in-process).
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger("backup_offbox")

BACKUP_PREFIX = "profiles-"


class OffboxConfig:
    """Resolved off-box config, or the reason it's unavailable."""

    def __init__(self, env: dict) -> None:
        self.enabled = env.get("BACKUP_OFFBOX_ENABLED", "0").strip() == "1"
        self.bucket = env.get("BACKUP_OFFBOX_BUCKET", "").strip()
        self.endpoint = env.get("BACKUP_OFFBOX_ENDPOINT", "").strip().rstrip("/")
        self.access_key = env.get("BACKUP_OFFBOX_ACCESS_KEY_ID", "").strip()
        self.secret_key = env.get("BACKUP_OFFBOX_SECRET_ACCESS_KEY", "").strip()
        self.region = env.get("BACKUP_OFFBOX_REGION", "us-east-1").strip() or "us-east-1"
        self.prefix = env.get("BACKUP_OFFBOX_PREFIX", "original-backups/").strip()
        self.url_style = (env.get("BACKUP_OFFBOX_URL_STYLE", "path").strip() or "path").lower()
        if self.prefix and not self.prefix.endswith("/"):
            self.prefix += "/"

    def missing(self) -> list:
        """Names of required-but-unset fields (only meaningful when enabled)."""
        missing = []
        if not self.bucket:
            missing.append("BACKUP_OFFBOX_BUCKET")
        if not self.endpoint:
            missing.append("BACKUP_OFFBOX_ENDPOINT")
        if not self.access_key:
            missing.append("BACKUP_OFFBOX_ACCESS_KEY_ID")
        if not self.secret_key:
            missing.append("BACKUP_OFFBOX_SECRET_ACCESS_KEY")
        return missing

    def ready(self) -> bool:
        return self.enabled and not self.missing()


def find_latest_backup(dest_dir: Path) -> Path | None:
    """Newest ``profiles-*.db`` in ``dest_dir``, or None if there isn't one."""
    if not dest_dir.is_dir():
        return None
    backups = sorted(
        dest_dir.glob(f"{BACKUP_PREFIX}*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return backups[0] if backups else None


# --- Minimal AWS SigV4 signer for a single PUT (stdlib only) ---------------
# Follows the standard AWS Signature Version 4 recipe for a single-chunk PUT.
# Deliberately does not depend on boto3 (not currently a project dependency)
# and works against any S3-compatible provider that implements SigV4.


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date = _hmac(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    return _hmac(k_service, "aws4_request")


def build_put_request(
    cfg: OffboxConfig, key: str, body: bytes, now: datetime.datetime | None = None
) -> tuple:
    """Build (url, headers) for a SigV4-signed PUT of ``body`` to ``key``.

    Pure function (no I/O) so it can be exercised in tests without hitting a
    network. ``now`` is injectable for deterministic tests.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    endpoint_no_scheme = cfg.endpoint.split("://", 1)[-1]
    scheme = cfg.endpoint.split("://", 1)[0] if "://" in cfg.endpoint else "https"

    if cfg.url_style == "virtual":
        host = f"{cfg.bucket}.{endpoint_no_scheme}"
        canonical_uri = "/" + quote(key, safe="/")
    else:
        host = endpoint_no_scheme
        canonical_uri = "/" + quote(f"{cfg.bucket}/{key}", safe="/")

    payload_hash = _sha256_hex(body)
    canonical_headers = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join(
        ["PUT", canonical_uri, "", canonical_headers, signed_headers, payload_hash]
    )

    credential_scope = f"{date_stamp}/{cfg.region}/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            _sha256_hex(canonical_request.encode("utf-8")),
        ]
    )

    signing_key = _signing_key(cfg.secret_key, date_stamp, cfg.region, "s3")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={cfg.access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    url = f"{scheme}://{host}{canonical_uri}"
    headers = {
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
        "Authorization": authorization,
        "Content-Length": str(len(body)),
    }
    return url, headers


def build_get_request(cfg: OffboxConfig, key: str, now: datetime.datetime | None = None) -> tuple:
    """Build (url, headers) for a SigV4-signed GET of ``key``. Empty-body PUT
    logic is reused with an empty payload hash, per the SigV4 spec for GET."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    endpoint_no_scheme = cfg.endpoint.split("://", 1)[-1]
    scheme = cfg.endpoint.split("://", 1)[0] if "://" in cfg.endpoint else "https"

    if cfg.url_style == "virtual":
        host = f"{cfg.bucket}.{endpoint_no_scheme}"
        canonical_uri = "/" + quote(key, safe="/")
    else:
        host = endpoint_no_scheme
        canonical_uri = "/" + quote(f"{cfg.bucket}/{key}", safe="/")

    payload_hash = _sha256_hex(b"")
    canonical_headers = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join(
        ["GET", canonical_uri, "", canonical_headers, signed_headers, payload_hash]
    )

    credential_scope = f"{date_stamp}/{cfg.region}/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            _sha256_hex(canonical_request.encode("utf-8")),
        ]
    )

    signing_key = _signing_key(cfg.secret_key, date_stamp, cfg.region, "s3")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={cfg.access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    url = f"{scheme}://{host}{canonical_uri}"
    headers = {
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
        "Authorization": authorization,
    }
    return url, headers


def download_latest(cfg: OffboxConfig, dest_path: Path, key: str) -> None:
    """Download object ``key`` from the configured bucket to ``dest_path``.
    Raises on failure. Used by ``restore_drill.py`` to fetch the off-box copy
    rather than trusting whatever is still on the (possibly compromised) disk."""
    url, headers = build_get_request(cfg, key)
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (internal, config-gated)
        if resp.status != 200:
            raise RuntimeError(f"off-box download failed: HTTP {resp.status}")
        dest_path.write_bytes(resp.read())


def list_keys(cfg: OffboxConfig) -> list:
    """List object keys under ``cfg.prefix`` via a SigV4-signed GET ?list-type=2.

    Returns keys sorted lexically, which sorts newest-last for this project's
    ``profiles-YYYYmmdd-HHMMSS.db`` naming (matches ``find_latest_backup``'s
    mtime-based ordering for the common case of one upload per run)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    endpoint_no_scheme = cfg.endpoint.split("://", 1)[-1]
    scheme = cfg.endpoint.split("://", 1)[0] if "://" in cfg.endpoint else "https"

    query = f"list-type=2&prefix={quote(cfg.prefix, safe='')}"
    if cfg.url_style == "virtual":
        host = f"{cfg.bucket}.{endpoint_no_scheme}"
        canonical_uri = "/"
    else:
        host = endpoint_no_scheme
        canonical_uri = "/" + quote(cfg.bucket, safe="/") + "/"

    payload_hash = _sha256_hex(b"")
    canonical_headers = f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join(
        ["GET", canonical_uri, query, canonical_headers, signed_headers, payload_hash]
    )
    credential_scope = f"{date_stamp}/{cfg.region}/s3/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, credential_scope, _sha256_hex(canonical_request.encode("utf-8"))]
    )
    signing_key = _signing_key(cfg.secret_key, date_stamp, cfg.region, "s3")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"AWS4-HMAC-SHA256 Credential={cfg.access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    url = f"{scheme}://{host}{canonical_uri}?{query}"
    headers = {
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
        "Authorization": authorization,
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (internal, config-gated)
        body = resp.read().decode("utf-8", errors="replace")
    import re

    keys = re.findall(r"<Key>([^<]+)</Key>", body)
    return sorted(keys)


def upload(cfg: OffboxConfig, file_path: Path) -> None:
    """Upload ``file_path`` to the configured bucket. Raises on failure."""
    body = file_path.read_bytes()
    key = f"{cfg.prefix}{file_path.name}"
    url, headers = build_put_request(cfg, key, body)
    req = urllib.request.Request(url, data=body, headers=headers, method="PUT")
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (internal, config-gated)
        if resp.status not in (200, 201):
            raise RuntimeError(f"off-box upload failed: HTTP {resp.status}")
    log.info("off-box: uploaded %s -> %s/%s", file_path.name, cfg.bucket, key)


def main(argv: list) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = OffboxConfig(os.environ)

    if not cfg.enabled:
        log.info("off-box backup: disabled (BACKUP_OFFBOX_ENABLED != 1) — no-op.")
        return 0

    missing = cfg.missing()
    if missing:
        log.warning(
            "off-box backup: enabled but not configured (missing %s) — no-op. "
            "Set these in the deploy environment to activate.",
            ", ".join(missing),
        )
        return 0

    if argv:
        src = Path(argv[0])
    else:
        dest_dir = Path(os.environ.get("BACKUP_DIR", "").strip() or "backups")
        src = find_latest_backup(dest_dir)
        if src is None:
            log.error("off-box backup: no backup found in %s — nothing to upload.", dest_dir)
            return 1

    if not src.is_file():
        log.error("off-box backup: %s does not exist.", src)
        return 1

    try:
        upload(cfg, src)
    except (urllib.error.URLError, OSError, RuntimeError) as exc:
        log.error("off-box backup: upload failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

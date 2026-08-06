#!/usr/bin/env bash
# export_backup_offbox.sh — pull the newest on-disk backup off the Render
# persistent disk to a durable off-box destination, automating the step
# docs/OPS_RUNBOOK.md currently prescribes as a manual daily
# `render ssh original-pilot -- cat /data/backups/...` pull.
#
# This script deliberately requires no cloud-storage account: it automates
# exactly the manual step the runbook already describes — shell out to
# `render ssh` to read backup bytes off the remote disk and write them to a
# local destination directory. Point OFFBOX_DIR at an already-mounted cloud
# location (rclone mount, gcsfuse, an EBS/NFS volume, etc.) and this becomes
# a genuine off-box copy without any change to this script — that mount is
# a separate, infra-level concern.
#
# scripts/backup_offbox.py is a second, complementary off-box mechanism: it
# *pushes* the newest local backup straight to S3-compatible object storage
# (opt-in via BACKUP_OFFBOX_*, no-op until a bucket is configured). Use that
# one once you have a bucket provisioned; use this one today, since it needs
# nothing beyond the `render` CLI the manual runbook step already assumed.
# scripts/restore_drill.py drills a backup pulled by either mechanism.
#
# Naming/retention conventions match original/backup.py and
# scripts/backup_db.sh: files are `profiles-YYYYmmdd-HHMMSS.db`; after each
# pull, only the newest OFFBOX_KEEP copies are retained in OFFBOX_DIR.
#
# Configuration (env — follows the BACKUP_* convention documented in
# CLAUDE.md / render.yaml):
#   RENDER_SERVICE     Render service name to pull from
#                      (default: original-pilot)
#   REMOTE_BACKUP_DIR  backup directory on the remote disk
#                      (default: /data/backups — matches render.yaml's
#                      BACKUP_DIR for original-pilot)
#   OFFBOX_DIR         local/mounted destination directory
#                      (default: ~/orig-backups)
#   OFFBOX_KEEP        how many pulled copies to retain in OFFBOX_DIR
#                      (default: 60)
#   REMOTE_FETCH_CMD   advanced/test override for the remote-exec prefix.
#                      Unset (default) -> `render ssh "$RENDER_SERVICE" --`.
#                      Set to "" -> run the listed/cat commands directly on
#                      the local filesystem (used by
#                      tests/test_export_backup_offbox.sh to drill this
#                      script against a scratch fixture dir instead of a
#                      real Render disk).
#
# Usage:
#   scripts/export_backup_offbox.sh                # pull the newest backup
#   scripts/export_backup_offbox.sh --list-remote   # just list what's remote
#
# Cron example (daily at 03:10, from the operator's machine or any small
# always-on box with the render CLI installed and `render login` done once):
#   10 3 * * *  RENDER_SERVICE=original-pilot OFFBOX_DIR=/mnt/offsite-backups \
#     /path/to/scripts/export_backup_offbox.sh >> ~/orig-backups/export.log 2>&1
#
# Manual fallback: if this script, cron, or the render CLI itself is broken,
# docs/OPS_RUNBOOK.md still documents the raw `render ssh ... cat` command —
# use it directly until the automation is fixed.
set -euo pipefail

RENDER_SERVICE="${RENDER_SERVICE:-original-pilot}"
REMOTE_BACKUP_DIR="${REMOTE_BACKUP_DIR:-/data/backups}"
OFFBOX_DIR="${OFFBOX_DIR:-$HOME/orig-backups}"
OFFBOX_KEEP="${OFFBOX_KEEP:-60}"
BACKUP_PREFIX="profiles-"

# Build the remote-exec argv as an array so quoting is correct whether
# REMOTE_FETCH_CMD is unset (production default), empty (test/local mode),
# or a multi-word override. `${VAR+x}` tests "is it set at all" (including
# set-to-empty), which `${VAR:-...}` cannot distinguish from unset.
if [ -n "${REMOTE_FETCH_CMD+x}" ]; then
  # shellcheck disable=SC2206 # intentional word-splitting of an operator-supplied command
  REMOTE_EXEC_ARR=(${REMOTE_FETCH_CMD})
else
  REMOTE_EXEC_ARR=(render ssh "$RENDER_SERVICE" --)
fi

remote_run() {
  if [ "${#REMOTE_EXEC_ARR[@]}" -eq 0 ]; then
    "$@"
  else
    "${REMOTE_EXEC_ARR[@]}" "$@"
  fi
}

list_remote_backups() {
  remote_run bash -c "ls -1 '$REMOTE_BACKUP_DIR'/${BACKUP_PREFIX}*.db 2>/dev/null | xargs -n1 basename 2>/dev/null | sort"
}

latest_remote_name() {
  list_remote_backups | tail -n1
}

fetch_remote_file() {
  local name="$1"
  remote_run bash -c "cat '$REMOTE_BACKUP_DIR/$name'"
}

if [ "${1:-}" = "--list-remote" ]; then
  echo "Backups on $RENDER_SERVICE:$REMOTE_BACKUP_DIR:"
  list_remote_backups
  exit 0
fi

mkdir -p "$OFFBOX_DIR"

latest="$(latest_remote_name || true)"
if [ -z "$latest" ]; then
  echo "No backups found in $REMOTE_BACKUP_DIR on $RENDER_SERVICE — nothing to pull." >&2
  exit 1
fi

dest="$OFFBOX_DIR/$latest"
if [ -f "$dest" ]; then
  echo "Already have $latest locally at $dest — skipping pull."
else
  tmp="$dest.partial"
  fetch_remote_file "$latest" > "$tmp"

  if [ ! -s "$tmp" ]; then
    rm -f "$tmp"
    echo "Fetched file for $latest was empty — aborting without touching existing backups." >&2
    exit 1
  fi
  if command -v sqlite3 >/dev/null 2>&1; then
    if ! sqlite3 "$tmp" "PRAGMA quick_check;" >/dev/null 2>&1; then
      rm -f "$tmp"
      echo "Fetched file for $latest failed a SQLite quick_check — aborting without touching existing backups." >&2
      exit 1
    fi
  fi
  mv "$tmp" "$dest"
  echo "Pulled $latest -> $dest"
fi

# Prune: keep only the newest OFFBOX_KEEP copies in the off-box destination.
ls -1t "$OFFBOX_DIR"/${BACKUP_PREFIX}*.db 2>/dev/null | tail -n +"$((OFFBOX_KEEP + 1))" | while read -r old; do
  rm -f "$old" && echo "Pruned $old"
done

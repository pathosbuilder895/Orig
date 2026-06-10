#!/usr/bin/env bash
# backup_db.sh — consistent online backup of the SQLite store (ADR-003, Phase 1).
#
# Uses SQLite's online .backup API, which is safe while the server is running
# (WAL mode). Keeps a timestamped copy and prunes to the most recent N.
#
# Usage:  scripts/backup_db.sh [backup_dir] [keep_count]
# Cron:   */30 * * * *  /path/to/scripts/backup_db.sh /var/backups/original 48
set -euo pipefail

DB="${ORIGINAL_DB:-$(cd "$(dirname "$0")/.." && pwd)/profiles.db}"
DEST="${1:-$(cd "$(dirname "$0")/.." && pwd)/backups}"
KEEP="${2:-24}"

mkdir -p "$DEST"
TS="$(date +%Y%m%d-%H%M%S)"
OUT="$DEST/profiles-$TS.db"

if [ ! -f "$DB" ]; then
  echo "No database at $DB — nothing to back up." >&2
  exit 0
fi

# Online, consistent backup (do NOT just cp a WAL database).
sqlite3 "$DB" ".backup '$OUT'"
echo "Backed up $DB -> $OUT"

# Prune: keep only the newest $KEEP backups.
ls -1t "$DEST"/profiles-*.db 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  rm -f "$old" && echo "Pruned $old"
done

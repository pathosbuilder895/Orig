#!/usr/bin/env bash
# Build the static site for the fictional professor demo (no API, no data).
# Publishes an explicit allowlist: demo/ also holds seed.db and the old
# Original pages, none of which belong on a public static origin.
set -euo pipefail
out="${1:?usage: build_teacher_demo_site.sh OUT_DIR}"
root="$(cd "$(dirname "$0")/.." && pwd)"
rm -rf "$out"
mkdir -p "$out/bluebook" "$out/assets/fonts"
for f in teacher-demo.html teacher-demo.bundle.js teacher-demo.bundle.css fonts.css; do
  cp "$root/demo/bluebook/$f" "$out/bluebook/$f"
done
cp "$root/demo/assets/codrington-library.jpeg" "$out/assets/"
cp "$root"/demo/assets/fonts/* "$out/assets/fonts/"
cat > "$out/index.html" <<'HTML'
<!doctype html><meta charset="utf-8"><title>Bluebook demonstration</title>
<meta http-equiv="refresh" content="0; url=bluebook/teacher-demo.html">
<a href="bluebook/teacher-demo.html">Open the Bluebook demonstration</a>
HTML

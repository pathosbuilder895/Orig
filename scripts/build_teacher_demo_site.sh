#!/usr/bin/env bash
# Build the static site for the fictional demos (no API, no data): the navy
# teacher/student suite and the interactive Bluebook walkthrough.
# Publishes an explicit allowlist: demo/ also holds seed.db and the old
# Original pages, none of which belong on a public static origin.
set -euo pipefail
out="${1:?usage: build_teacher_demo_site.sh OUT_DIR}"
root="$(cd "$(dirname "$0")/.." && pwd)"
rm -rf "$out"
mkdir -p "$out/bluebook" "$out/assets/fonts" "$out/prototypes"
for f in teacher-demo.html teacher-demo.bundle.js teacher-demo.bundle.css fonts.css; do
  cp "$root/demo/bluebook/$f" "$out/bluebook/$f"
done
cp "$root/demo/assets/codrington-library.jpeg" "$out/assets/"
cp "$root"/demo/assets/fonts/* "$out/assets/fonts/"
# Same relative path as in demo/, so the suite's ../../assets/fonts links hold.
cp -R "$root/demo/prototypes/navy" "$out/prototypes/navy"
cat > "$out/index.html" <<'HTML'
<!doctype html><meta charset="utf-8"><title>Original and Bluebook demonstration</title>
<meta http-equiv="refresh" content="0; url=prototypes/navy/index.html">
<a href="prototypes/navy/index.html">Open the fictional demonstration</a>
HTML

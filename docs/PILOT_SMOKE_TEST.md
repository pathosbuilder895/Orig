# Pilot Smoke Test (run against the LIVE pilot URL)

Run top-to-bottom before go-live and within 48h of any deploy that precedes an
exam. ~15 minutes. `$HOST` = the pilot URL. Use a throwaway "smoketest" course.

## A. Platform health

- [ ] `curl $HOST/health` → 200, JSON includes `feature_dim: 103`.
- [ ] Render dashboard: deployed SHA == `main` HEAD; memory < 80% steady-state.
- [ ] `curl -s -D- -o /dev/null $HOST/health | grep -i strict-transport` → HSTS present.
- [ ] CORS locked: `curl -s -D- -o /dev/null -H "Origin: https://evil.example" $HOST/health | grep -i access-control-allow-origin` → no header echoed for foreign origin.
- [ ] Backup: newest file in the backup destination is < 24h old.

## B. Staff auth + tenant isolation

- [ ] Professor login at `$HOST/bluebook/` works; sidebar shows `professor · <tenant>`.
- [ ] Wrong password → error message (and 11 rapid failures → "Too many sign-in attempts").
- [ ] `GET $HOST/students` with the professor's token → only `<tenant>:*` ids.
- [ ] Anonymous `GET $HOST/students/<tenant>:anything` → 403.
- [ ] Sign Out returns to the landing page; dashboard no longer reachable without login.

## C. Examination loop (the heart)

- [ ] Professor: + New Examination → publish → it appears in Examinations (persisted: reload the page, still there).
- [ ] Canvas **instructor** launch (course nav) → Bluebook dashboard, signed in, right tenant.
- [ ] Canvas **student** launch (exam link) → briefing screen, no login prompt; conditions list matches the exam's toggles.
- [ ] Begin Examination → fullscreen engages; leaving fullscreen shows the warning + Restore control.
- [ ] Paste attempt is blocked with the examiner's notice; Ctrl/Cmd+P blocked.
- [ ] Type past the minimum → Seal & Surrender → "Examination Sealed" + "✓ Proctored baseline transmitted to Original".
- [ ] `GET $HOST/students/<bound id>` → sample_count incremented, provenance `proctored`.
- [ ] Bluebook → Results: the sitting is listed with a Stylometric score; AI Score populated if the student already had a baseline (— if first sitting: expected).

## D. Scoring loop

- [ ] Professor dashboard: paste a known-authentic text for a student with ≥3 baselines → Analyze → deviation score + plain-English explanation render.
- [ ] The recommendation tier matches expectations (authentic text ≠ Escalate).

## E. Paperwork (go-live only)

- [ ] DPA signed. Syllabus disclosure in all participating courses.
- [ ] All 5 professors have logged in at least once.
- [ ] Quickstart delivered; onboarding session held.

**Failure handling:** any C-item failing blocks scheduled exams; any B-item
failing blocks everything — fix, redeploy, rerun the whole list.

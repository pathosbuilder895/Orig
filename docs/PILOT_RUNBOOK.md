# Pilot Runbook — taking Original to a seminary

The operational playbook for a first institutional pilot: what to verify
before launch, how to collect baselines, how the AI-likelihood detector's
shadow period works, and what numbers decide the go/no-go at each step.
Companion docs: `PROVISIONING_CHECKLIST.md` (tenant setup),
`CANVAS_RUNBOOK.md` (LTI), `OPS_RUNBOOK.md` (day-2 operations),
`MODEL_CARD.md` (model claims + the enablement gate), `data_inventory.md`
(FERPA holdings).

---

## 1. Pre-launch checklist

Run the preflight against the deployment's environment and database:

```bash
.venv/bin/python scripts/pilot_preflight.py --db /data/profiles.db --backup-dir /data/backups
```

Exit 0 = ready. Every FAIL row must be fixed; WARN rows are judgment calls.
The checks mirror the app's own fail-fast rules: `ORIGINAL_ENV=pilot`,
pinned `SECRET_KEY`, `GUARD_DESTRUCTIVE=1` + `MAINTENANCE_TOKEN`,
https-only `ALLOWED_ORIGINS`, WAL database with all expected tables,
detector artifact validity, backup recency, spaCy model.

Deploy-surface flags (render.yaml, original-pilot service):

| Flag | Pilot value | Meaning |
|---|---|---|
| `AI_LIKELIHOOD_ENABLED` | `"0"` (pinned in git) | Detector never surfaces to professors |
| `AI_LIKELIHOOD_SHADOW` | dashboard-managed | Silent persistence for FPR measurement |
| `CONTEXT_MANIFEST_ENABLED` / `ADAPTIVE_WEIGHTS_ENABLED` | `"1"` | Adaptive scoring pipeline |

## 2. Baseline collection protocol

The per-student verification is only as good as the baseline. Protocol:

1. **First sample proctored.** The student's first essay is written in
   Bluebook (proctored mode) so the profile is anchored to provenance
   nobody can dispute.
2. **Target 5–8 authenticated samples** per student before scores carry
   weight. Confidence saturates around 5; below 3 effective samples the
   system itself appends a limited-confidence note.
3. **300+ words per sample.** Below ~300 words feature estimates get
   unstable (measured: validation/stability/); short submissions are
   scored but carry a provisional-confidence note.
4. **Spread across assignments** — one assignment's register is not a
   student's range.

Check any student's status at a glance:

```bash
curl -s $BASE/students/<id>/readiness | jq .verdict,.recommendations
```

Verdicts: `ready` (≥5 authenticated AND ≥3 effective) · `developing`
(≥2 authenticated) · `insufficient`. Don't lean on scores for students
below `ready`; the endpoint says exactly what to collect next.

## 3. AI-likelihood shadow period (weeks 1–4)

The detector passed its synthetic-corpus gate (MODEL_CARD.md), but the
pilot is its first contact with real student writing. So it runs silent
first:

- Set `AI_LIKELIHOOD_SHADOW=1`, keep `AI_LIKELIHOOD_ENABLED=0`.
- Every scored submission persists a probability/band row to
  `ai_likelihood_scores`. **Nothing is surfaced** — responses, narratives,
  and dashboards are byte-identical to the flag-off state (tested).
- Professors keep correcting verdicts as usual (§4) — those corrections
  are the ground-truth labels the shadow analysis joins against.

Weekly, run the shadow report against a backup copy:

```bash
.venv/bin/python scripts/shadow_report.py --db backups/profiles-<latest>.db \
    --out-md shadow_week<N>.md
```

**Week-5 go/no-go for flipping `AI_LIKELIHOOD_ENABLED=1`:**

- [ ] Real-world FPR at `t_elevated` ≤ 5% on instructor-confirmed
      authentic submissions (the MODEL_CARD gate, now on real data)
- [ ] ≥ 30 instructor-labeled submissions in the join (below that, the
      percentage is noise — extend the shadow period instead)
- [ ] Band distribution sane (no single student absorbing the flags —
      check `per_student_flag_concentration`)
- [ ] Institutional sign-off (§7)

If any box is unchecked, stay in shadow. There is no cost to waiting;
there is a large cost to a false accusation.

### 3b. Topic-shadow telemetry (optional, score-neutral)

One more shadow measurement is free once real traffic exists, and answers
a question the 2026-08 cross-genre study could not: do real student
submissions ever drift far enough from their baseline topic for the
topic-variance correction to matter?

- Set `TOPIC_VARIANCE_INFLATION=shadow` (dashboard env var, restart in a
  maintenance window). Shadow attaches `deviation_score_inflated` and
  `topic_distance` diagnostics to each scoring result **without touching
  `deviation_score` or the recommendation** — tested to equal exactly
  what `on` would produce.
- After 2+ weeks, pull the distribution of `topic_distance` from scoring
  audit records. If it clusters at or below 0.25 (the structural no-op
  bound), the mechanism would never fire on this cohort and `on` is moot
  regardless of its corpus performance — exactly the trap the
  genre-invariant flag fell into. If a real tail exists above 0.25, gate
  G7 becomes worth *running*: it is implemented as of 2026-08-14
  (`validation/calibration_gate.py:evaluate_g7_cross_topic_fpr`, wired into
  `run_all()`) but has never returned a verdict, because its corpus is not
  committed — on a fresh checkout it reports `uninformative` and
  `--strict` exits 1. Note also that a shadow run can never produce a G7
  pass: shadow leaves `deviation_score` and the recommendation untouched,
  so all three legs come out identical to flag-off, and G7 downgrades that
  to `uninformative` rather than letting it read as a pass.

**Not free, despite appearances:** the cold-start prior's
`bayesian_prior outcome=hit|miss` log line only fires when
`BAYESIAN_PRIOR_ENABLED=1`, and that flag **changes scores** — do not
enable it to collect telemetry. Measure prior coverage offline instead:
`scripts/measure_genre_prior_scope.py` against pilot data (the 2026-07-29
attempt found no genre-labelled dataset; re-try once real genre-tagged
submissions accumulate).

### 3c. Genre-resolver shadow (optional, score-neutral)

The second score-neutral measurement, and the higher priority of the two:
it is the only way to get the one number no corpus can supply — **how often
the genre classifier abstains on real student writing**. Everything known
about v2 comes from 19th-century published prose plus 25 seminary papers.

- Set `GENRE_RESOLVER_V2=shadow` (dashboard env var, restart in a
  maintenance window). Inert by construction: `primary` still comes from
  the v1 rules and nothing downstream moves. Shadow attaches
  `shadow_primary` / `shadow_confidence` and emits one
  `genre_shadow v1=… v2=…` INFO line per call. Both baseline ingestion and
  scoring call `resolve_genre`, so every submission emits a line.
- After 2+ weeks:
  `render logs --tail 100000 | .venv/bin/python validation/genre_2026-08/read_shadow_log.py`.
  The reader distinguishes "shadow ran and never abstained" from "shadow
  was never on" — in a bare abstention rate those are identical and only
  one of them is a measurement.
- **What the number means.** The hold-out abstention rate is 33.3%
  (ceiling 50%). Substantially higher on real submissions means the
  3-class taxonomy does not fit seminary writing and the class set needs
  revisiting before `on` is considered. Substantially *lower* is not good
  news either — it would mean the classifier is confidently labelling
  genres it was never trained on. Sermons are the known gap: v2 carries no
  `sermon` label and, on the one out-of-taxonomy corpus measured, abstained
  on only 7 of 11 such documents rather than all 11
  (`docs/research/2026-08-13-genre-resolver-fix-scoping.md` §Addendum).
- ⚠️ Do **not** skip to `GENRE_RESOLVER_V2=on` on the strength of gate G8.
  G8 passes, but `on` changes scores: the genre label drives tier-16
  muting and T8/T13 anchor expansion, and is a Bayesian-prior pooling key.

## 4. Professor correction workflow

Corrections are how the pilot learns. When a professor reviews a scored
submission:

```
POST /submissions/{submission_id}/correct
{ "is_correct": true|false, "corrected_verdict": "authentic"|"uncertain"|"anomalous",
  "corrected_action": "...", "reviewer": "...", "notes": "..." }
```

The `is_authentic` ground truth is derived as: verdict was correct and the
action was `no_action` → authentic; verdict was correct and the action was
anything else → anomalous; verdict was wrong and corrected to `authentic`
→ authentic; otherwise anomalous. This single feedback stream powers both
the conformal calibration of the per-student verification AND the shadow
FPR measurement — every correction makes both systems more trustworthy.

Train professors on one sentence: *"If the system's read doesn't match
what you know about the student, say so in two clicks — that's the pilot."*

## 5. Weekly ops report + success criteria

```bash
.venv/bin/python scripts/pilot_report.py --db /data/profiles.db --since-days 7 --out week<N>.md
```

Suggested success-criteria table (agree on the numbers with the seminary
BEFORE launch; fill weekly from the report):

| Metric | Target | W1 | W2 | W3 | W4 |
|---|---|---|---|---|---|
| Students at readiness `ready` | growing → 100% | | | | |
| Submissions scored | (volume) | | | | |
| Correction rate (corrections / scored) | professors engaged: > 10% early | | | | |
| Professor-confirmed false positives | < 5% of corrections | | | | |
| Shadow FPR @ t_elevated (labeled authentic) | ≤ 5% by week 4 | | | | |
| Escalations handled per policy (§7) | 100% | | | | |

## 6. Backups

On-disk backups are **automatic**: the server process runs an in-app
scheduler (`original/backup.py`) that writes a consistent SQLite backup to
`BACKUP_DIR` (`/data/backups` on Render) every 30 minutes, pruned to the
newest 48. Check `GET /admin/health` → `last_backup_age_seconds` to confirm
it is running.

What stays manual: copy at least one backup per day **off the box** (the
disk and its backups die together), and run one restore drill in week 1
(restore a backup to a scratch path, run
`scripts/pilot_preflight.py --db <scratch>` against it — the table check
doubles as a restore validation). See `OPS_RUNBOOK.md` for the full
backup/restore procedure.

## 7. FERPA + policy notes

- **Raw text is stored.** Baseline sample prose lives in the student
  profile (it powers the professor's read-the-sample view) until the
  student's data is deleted. Deletion is one call:
  `DELETE /students/{student_id}` — it purges profile, fidelity scores,
  AI-likelihood scores, manifests, and corrections. `GET
  /students/{id}/data-inventory` enumerates current holdings per student.
- **Student notice**: use `STUDENT_DISCLOSURE.md` as the base for the
  seminary's notice/consent language. The AI-likelihood shadow table is
  covered by the same deletion path and inventory (see
  `data_inventory.md` §5.1b).
- **A flag is a conversation, never a sanction.** The written agreement
  with the seminary should state: Original's output is evidence for a
  pastoral conversation; no academic-integrity action is taken on a score
  alone. This matches the product's own language (non-accusatory
  narrative, innocent explanations first) — the institution's process
  must not be harsher than the tool's vocabulary.
- **Escalation path**: agree in advance who sees `escalate` actions, what
  the conversation template is, and how outcomes get recorded (the
  corrections endpoint is the system-of-record for "we talked, it was
  fine").

## 8. Professor onboarding (15 minutes)

1. Dashboard tour (built into professor.html).
2. The three ideas: *baseline* (5–8 samples of the student's real voice),
   *deviation* (how far today's essay sits from that voice, with
   plain-English reasons), *action* (what to do next — usually nothing).
3. What the tool cannot do: verify against a genre it has never seen,
   judge very short texts confidently, or prove anything — it surfaces
   evidence for a conversation.
4. The two-click correction flow (§4).
5. Where to ask for help.

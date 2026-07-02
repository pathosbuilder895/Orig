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

```
*/30 * * * * bash /opt/original/scripts/backup_db.sh /data/backups 48
```

Copy at least one backup per day off the box. Run one restore drill in
week 1 (restore a backup to a scratch path, run
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

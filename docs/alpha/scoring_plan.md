# Scoring plan: rolling batch scoring, labelled ground truth, calibration

**Purpose (Andrew, 2026-10-19): this alpha is CALIBRATION, not a pass/fail product test.** The volunteers are adults Andrew knows, who have no reason to misrepresent their writing, so their labels are treated as known truth. The aim is to fine-tune weights/thresholds **toward** catching ≥75% of shadow papers while holding false flags on natural papers at ≤5%. Those are **targets to calibrate toward, not claims**: nothing is claimed publicly until validated on genuinely independent, consented student writing (see `/workspace/engine_cautious_plan.md` guardrails, summarised below).

## Why batch scoring, and why rolling
On main, sealing does not score. Exams run with writing consistency OFF; students never see scores. Staff score afterwards, offline, through the same `/score` code path (`scripts/score_documents.py`), via `scripts/alpha/batch_score_alpha.py`. Async alpha: **score as submissions arrive** (e.g. weekly batches, or when a volunteer's A+B are both in), not in one post-session run.

## Labels — evaluation-only, outside the scored text, blind
`labels.csv` (staff only, never committed, never shown to students) is the **only** place shadow truth lives. It is read by the batch process *after* scores exist, only to compute rates. It is **never passed to the scoring subprocess** (`batch_score_alpha.score()` forwards only baseline/submission directories to `score_documents.py`), never becomes an engine feature, and no label text is inside any scored paper.

Canonical header (v2):
```csv
submission_id,label,author_true,writer_true,shadow_kind,imitated_student_id,prompt_id,paired_submission_id,shadow_source_paper_id,generator_tool
```
- `label`: `natural` or `shadow` (legacy `not_own` and the old `true_author` header are accepted and normalised).
- `author_true`: the student whose baseline/voice a paper is compared against (for shadow: the student imitated). `writer_true`: who actually wrote/generated it — **for a shadow this must not be the imitated student** (validated).
- `shadow_kind`: `human_partner` | `ai_staff` | `injected_other` | `public_domain`. `ai_staff` requires `generator_tool` (staff-created only; a volunteer never generates an `ai_staff` shadow of themselves).
  - `ai_own` (the **"AI imitation"** collection in the simplified design, 2026-10-25): the volunteer pasted an AI imitation of **their own** piece. Requires `generator_tool`; `imitated_student_id` must equal `author_true` (the volunteer), and `writer_true` may be the volunteer. By default it **counts as a main shadow kind**: it is in the headline catch rate, the PASS/FAIL gate, the threshold sweep and the baseline-source breakout, and it has its own row in *Catch by shadow kind*. To report it separately instead (the old Exam C behaviour), run with `--primary-shadow-kinds human_partner,ai_staff,injected_other,public_domain`; a kind left out is still validated and shown on its own line, never pooled.
- `imitated_student_id`, `prompt_id`, `paired_submission_id` (the same-prompt genuine paper, where the paired design is used), `shadow_source_paper_id` (the one sample the writer/generator saw).
- Current Exam A/B use different prompts (`night-market` vs `letter-2076`): record both `prompt_id`s honestly; do not call them a same-prompt pair. The same-prompt paired wording in `prompts.md` needs Andrew's approval.

## Split-derived baselines — tagged, never silently pooled
If a volunteer has 3+ individual papers, use those. If not, one long paper **may** be split into sections treated as baseline papers (consent Q7), because the gate counts papers. Split pieces are correlated, not independent papers, so:
- Tag them in the export: `baselines.csv` next to the export folders, header exactly `student,baseline_file,baseline_source,parent_paper_id` (`baseline_source` = `independent`|`split`; split requires the parent paper id). The batch scorer validates it; without it, everything is tagged `independent` and the report says that was by staff attestation. The API export (`--base-url`) now writes `baselines.csv` itself from papers students shared in the app (matched by text; an approved paper marked as a section becomes `split` with `parent_paper_id` = `<student folder>:<longer paper title>`); it never overwrites an existing `baselines.csv`, so if you also hand-imported split papers, add their rows to the generated file.
- `per_submission.csv`/`report.md` carry `baseline_source` (`independent`|`split`|`mixed`), `n_split_baselines`, `n_independent_baselines`, `baseline_parent_ids` per student. The **minimum-baseline gate still counts papers**; the split count is shown separately.
- The report's **Baseline-source breakout** breaks false-flag (and catch) rates out split vs independent vs mixed. **Never pool them silently**: if split-derived baselines flag differently, that is a calibration finding to act on, not noise to average away.

## Pre-registered targets (fix in writing before tuning; Andrew to confirm)
- **False-flag target:** ≤5% of natural papers strictly flagged (`schedule_conversation`/`escalate`; `monitor` reported separately as lenient).
- **Catch target:** ≥75% of shadow papers strictly flagged.
- INCONCLUSIVE/insufficient-baseline papers (fewer than 3 baseline papers or <300 words) are excluded from both rates and reported separately.
- **Small-sample caveat:** with ~20 per arm, 0/20 false flags still allows ~16% true rate (Wilson). Meeting the targets on this set is "no red flags yet", not validation.

## Calibration protocol (guardrail — tunes on a subset, validates held-out)
1. Split **by student** (never by paper), ~60/40, stratified so both parts contain split-derived and independent baselines and both prompt ids (in the simplified design, every student's natural piece and `ai_own` imitation stay together in the same part, because the split is by student): a **tune** set and a **held-out** set the tuning never sees. Record the split (student ids + seed) in the staff report before tuning.
2. Tune weights/thresholds **only** on the tune set, and **never on unlabelled papers**. Keep the current scorer as the frozen control; change one component at a time and run head-to-head on identical splits.
3. Report tune and held-out results separately, at fixed false-flag rates, with student-clustered intervals and abstention/insufficient rates. A change is promoted only if it beats the control on held-out students/topics — and even then it is an internal calibration result, not a public claim.
4. Do not tune on the same data and then report the tuned numbers as the result.

## Running it (rolling)
From Render → `original-pilot` → **Shell**, or a private local checkout (preferred for labels). Never put the token in command text/history/reports.
```sh
read -s -p 'Teacher bearer token: ' ALPHA_TOKEN; printf '\n'; export ALPHA_TOKEN
python scripts/alpha/batch_score_alpha.py \
  --base-url https://original-pilot.onrender.com --exam "$EXAM_A_ID" --exam "$EXAM_B_ID" \
  --labels /tmp/alpha-labels.csv --repo "$PWD" --out /tmp/alpha-score-report \
  --throttle-seconds 2
unset ALPHA_TOKEN
```
Local rescoring: `--from-dir /path/to/export` (with `labels.csv`, and `baselines.csv` if any baseline is split-derived) `--throttle-seconds 0`.
- **Output:** `report.md` + `per_submission.csv`, staff-only. Exit 0 = targets met or no labels, 1 = targets missed, 2 = invalid labels/baselines, non-finite or nondeterministic scores.
- **Shadow kinds in the headline:** `--primary-shadow-kinds all` (default) counts every shadow kind, `ai_own` included; pass a comma list to narrow it. The report's catch line names the kinds counted.
- **Report contents:** pooled false-flag/catch rates, **baseline-source breakout**, threshold sweep 0.05–0.95, INCONCLUSIVE rate, Wilson + student-bootstrap CIs, determinism and timing checks, baseline-size effect (all vs first 3).

## Previous rehearsals (synthetic only)
2026-10-15 local rehearsal: pipeline ran end-to-end (10/10 scored, deterministic); 20-student rehearsal is `tests/alpha/test_alpha_scripts.py::test_local_runbook_rehearsal_twenty_concurrent_students_full_delete`. Synthetic texts prove engineering, not accuracy. See `sample_report_synthetic.md`.

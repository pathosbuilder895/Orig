# 06 — Scientific validation: gates, certification, and how results may be cited

Scope: `validation/` (the gate battery, corpora, contracts, floors),
`validation/termsim/` (on the unmerged `claude/termsim-validation-harness-b04ef3`),
and the relationship between "the tests pass" and "the instrument works".

This document does **not** re-plan gate repair, corpus regeneration, or
TermSim — those are `docs/superpowers/plans/2026-08-26-codex-campaign-0{1,2,4}`.
It says what the *testing strategy* needs from them, adds the one certification
test the campaign did not name, and fixes how results are reported.

---

## 1. Where the battery stands

| Gate | Measures | Status (newest committed report 2026-07-31; CLAUDE.md for G8) |
|---|---|---|
| G1 | pooled same-author false-flag rate, LOO | `passed: true` but text says *uninformative* (p-floor 0.200 at n≤4) — a pass-by-floor, never citable |
| G2 / G2b | impostors not more typical than holdout; paraphrase proxy | pass / pass |
| G3 | top-1 attribution ≥ 0.70 | pass 0.727 |
| G4 | career drift monotone | pass |
| G5 | label-destruction control over G1/G3/G4 | machinery fix **merged** (`4de85b84`, drift-gate holds carved out of leg health); **no post-fix committed report** — verdict unknown |
| G6 | native/non-native flag-rate parity | same fix merged; threshold still unreachable at n=4 → expect `uninformative`, not yet confirmed by a committed run |
| G7 | cross-topic FPR conjunction | **never returned a verdict** — corpus uncommittable (copyright) |
| G8 | genre resolver v2 precision/abstention/control | pass per CLAUDE.md; **not in any committed report** |
| G-P3 | `CHARACTERISTIC_WEIGHTS` validation | **no evaluator exists** |
| T-1…T-4 | TermSim term-shaped gates | **merged** (`0d35d486`), registered in `gate_contracts.py`; first-light report 2026-08-27 at 3 seeds shows honest-term flag probability saturating at monitor+ and `LLR_ACTION_MODE=gate` never exceeding `llr-shadow` on TRANSFER |

The battery is in CI as `calibration-battery.yml` (weekly, `--strict`, 30-minute
cap, `continue-on-error`) but see §7: it cannot finish. The unit layer (`test_calibration_gate.py`,
`test_gate_falsifiability.py`, `test_gate_properties.py`, `test_corpus_policy.py`,
`test_measurability.py`) runs on every commit and is fast.

## 2. What the strategy asks of the campaign plans

- **Plan 01** (gate repair): the G5/G6 fix and the weekly workflow are
  merged. Still owed: a fresh committed `--strict` report (none since
  2026-07-31), and the workflow must fail its *own* step if any gate returns
  `ERROR` even though the job is non-blocking for merges — today
  `continue-on-error: true` swallows both. Machinery breakage hid for a
  month because nothing distinguished it from a science result.
- **Plan 02** (corpora): G7 and G-P3 first verdicts. The strategy adds: the
  regeneration script must be run by the weekly workflow on a self-hosted or
  cached runner, or G7 stays permanently uninformative in CI and the
  `TOPIC_VARIANCE_INFLATION=on` decision stays un-testable. If that is
  impossible, say so in the gate's `notes` and in the flag's CLAUDE.md row.
- **Plan 04** (TermSim): merged at `0d35d486`; that commit fixed three of the
  four merge caveats from the 2026-09-02 review. The fourth — a fresh
  committed G1–G8 battery report — is still absent and is the same item Plan
  01 owes. TermSim's own evidence (`validation/termsim/reports/latest.json`)
  is committed and byte-read by the first-light report.

## 3. The certification test the campaign did not name

The pilot-blocking finding is simple to state and has no test:

> A genuine author with the pilot's modal three baselines, scored through the
> production path with flags off, must not land in `schedule_conversation` or
> `escalate`.

It fails today at 0.75–0.82. Add `tests/certification/test_cold_start_fpr.py`:

```python
@pytest.mark.certification
@pytest.mark.parametrize("n_baselines", [3, 5, 10])
def test_same_author_action_at_pilot_baseline_counts(live_client, store_reset,
                                                     corpus_authors, n_baselines):
    """Three-valued: uninformative below 8 authors, else pass/fail."""
    if len(corpus_authors) < 8:
        record_verdict("uninformative", reason="<8 authors in committed corpus")
        pytest.skip("uninformative — see report")
    flagged = 0
    for author in corpus_authors:
        sid = provision_student(live_client, author.baselines[:n_baselines])
        r = live_client.post(f"/students/{sid}/score", json={"text": author.holdout}).json()
        flagged += r["recommendation"]["action"] in {"schedule_conversation", "escalate"}
    rate = flagged / len(corpus_authors)
    record_verdict("pass" if rate <= 0.10 else "fail", value=rate, n=len(corpus_authors))
    assert rate <= 0.10, f"same-author flag rate {rate:.2f} at N={n_baselines}"
```

Notes on the design (response shape: `recommendation` is an object whose
`action` carries the tier; the deviation lives at `authorship.deviation_score`):

- **Through the API**, not `score()` — the review showed the unit path (G1 via
  typicality) and the production path (fixed `ACTION_THRESHOLDS`) disagree.
  The certification must run where the product runs.
- **Flags off.** Certifying the default config first. A second parametrise
  axis over the demo-mode flag set (`CONTEXT_MANIFEST`, `ADAPTIVE_WEIGHTS`,
  `NULL_MODEL=impostor`) comes after.
- **The 0.10 bar** is a pilot-acceptance number, deliberately looser than
  G1's 0.05, because the corpus is small and the goal is to catch
  saturation, not to calibrate. Register a failure witness in
  `validation/gate_contracts.py` (a fixture where every holdout is a
  different author) or `test_gate_falsifiability.py` will reject it — which
  is the correct reflex.
- **Speed.** Baselines are re-extracted server-side — the baseline route
  accepts text only, not pre-extracted vectors — so this is not the
  sub-minute run it looks like on paper: measured 5:31 for the package. It
  runs in the `known-red` job, not per PR.
- **Reporting.** `record_verdict` writes to a JSON, `certification-report.json`,
  written locally by the certification tests and not yet uploaded by any CI
  step — same shape as the battery report so the weekly workflow can merge
  them once that lands.

Until the saturation fix lands (readiness-gated actions, N-aware thresholds,
or a joint floor+threshold recalibration — the review's three shapes), this
test is red on `main`. **Do not mark it xfail.** Red is the honest state; the
register carries it as the pilot go-live blocker.

## 4. Citation rules (make them a test)

The suite already enforces three-valued verdicts in code. The *documents* do
not: CLAUDE.md quotes G8 from a run that is in no committed report;
`calibration_report_2026-07-31.json` says `passed: true` next to
"UNINFORMATIVE". Add `tests/validation/test_report_consistency.py`:

- Every `calibration_report_*.json` entry has a `verdict` field (the
  pre-`verdict` reports are migrated once with a script, or listed in an
  explicit legacy allowlist with a reason).
- `passed == (verdict == "pass")` in every committed report.
- Every gate named in CLAUDE.md's flag table with a status word
  ("passes", "fails") has a matching verdict in the *newest* committed report,
  or the row says "not in a committed report".

The last one will fail on the day it lands (G8). That is the finding.

## 5. Corpus hygiene as tests

- **Manifest ↔ files.** Every entry in each `manifest.json` points at a file
  that exists, and every corpus file is in a manifest. Today this is spot-
  checked per corpus in `tests/validation/`; one generic test over all
  manifests replaces the per-corpus copies.
- **Floors.** `check_attribution_pool()` is the only enforced floor. Add a
  test that `VERIFICATION_MIN_WORDS` is either wired to a production caller
  or documented as unwired *in the constant's docstring* — a constant that
  looks like a rule and enforces nothing is a trap for the next reader.
- **Copyright fence.** A test that `validation/genre_crossgenre_2026-08/`
  contains no `raw/`, `clean/`, `chunks.json`, or `vectors.npy` in the git
  index (`git ls-files`). The `.gitignore` lines are on `main` now; this test
  makes the fence hold even if they are reverted again (one branch already
  did).

## 6. What a gate may and may not be used for

Write this into `validation/README.md` and pin it with the falsifiability test
where possible:

| Claim | Requires |
|---|---|
| "Gate X passes" | `--strict` run, committed report, verdict `pass`, report date in the sentence |
| "Flag F is validated" | the gate its CLAUDE.md row names, plus a TermSim scorecard, plus either a shadow-soak result or the exact soak command awaiting data |
| "FPR is Y %" | which path (typicality vs `ACTION_THRESHOLDS`), which N, which corpus — all three, or the number is not citable |
| "The suite is green" | full CI command, Postgres up, 0 failed; certification tests reported separately |

## 7. Battery in CI — what exists and why it cannot finish

`calibration-battery.yml` exists: weekly Monday, `workflow_dispatch`, one job,
`ubuntu-latest`, `timeout-minutes: 30`, `continue-on-error: true`, runs
`python -m validation.calibration_gate --strict --out calibration-report.json`
and uploads it. It carries a TODO for regenerating the G7 corpus.

The runtime does not fit. The 2026-09-07 merge session measured the full
G-battery at **20+ CPU-hours** because every gate re-parses every corpus
document through spaCy; TermSim's standard matrix alone is 18–34 minutes of
wall on a 12-core machine at 7 workers. A 30-minute two-core GitHub job will
time out every week, and `continue-on-error` will make that look like a
yellow tick rather than a failure. Nothing offline could confirm a completed
run; treat the job as unproven.

Fix, in order:

1. **Feature-vector cache for the G-battery.** TermSim already has an
   auditable vector cache (`0d491bba`, `.benchmark_cache/termsim/`). Give the
   G-gates the same: cache `(sha256(text), pipeline_version) → vector` under
   `.benchmark_cache/gates/`, restored via `actions/cache`. Extraction is the
   cost; scoring is seconds. Add a test that a cache hit and a fresh extract
   are byte-identical (the determinism suite's pattern) so the cache can
   never lie.
2. **One job per gate** (matrix over `G1…G8`, `T-1…T-4`), each with its own
   cap, a `combine` job that merges the JSONs. A slow gate then times out
   alone and is reported as `ERROR` for that gate, not as a lost run.
3. **Fail the step on `ERROR`.** Drop `continue-on-error`; parse the JSON and
   `exit 1` if any verdict is `ERROR`. Science `fail` stays non-blocking via
   the schedule-only trigger.
4. **Record runtime.** Each gate writes its wall time into the report; a
   test asserts the job cap exceeds the newest recorded max by 2×, so the cap
   is derived from measurement (the `test.yml` comment's own rule).

Until 1–2 land, run the battery on the 12-core machine by hand and commit the
report; that is the only path to the post-fix G5/G6 verdicts Plan 01 owes.

The weekly workflow, once it can finish, also hosts: `pytest -m certification`
(also per PR), TermSim standard matrix at 3 seeds, the mutation run
(§02 §5), `scripts/load_smoke.py` (§07 §8), the restore drill (§08 §6), and
visual regression (§05 §5). A red weekly run is Monday reading, not a merge
blocker — except for the certification step, which is also per-PR and *is* a
blocker once it is green on `main`.

## 8. Acceptance for this slice

- `tests/certification/test_cold_start_fpr.py` exists, has a registered
  witness, and is red on `main` with a register entry.
- `test_report_consistency.py` exists; CLAUDE.md's G8 row is either backed by
  a committed report or reworded.
- `calibration-battery.yml` completes inside its cap (vector cache +
  per-gate matrix) and fails its step on `ERROR`; one post-fix `--strict`
  report is committed.
- `validation/README.md` carries the citation table.

# A per-writer line for the verdict (`WRITER_LINE`)

*2026-11-16. Asked for by Andrew. Status: built default-off; negative result; see CLAUDE.md WRITER_LINE row.*

## Why

Today one set of cut-offs (`ACTION_THRESHOLDS`) decides the verdict for every student. A student's honest papers score at a level of their own, so one line sits too high for some writers and too low for others. That costs catches and causes false alarms.

Measured 2026-11-16 on the G-REBIND records (`validation/rebind/records/` on branch `claude/llr-rebind`: PAN20, public_authors, synthetic seminary). Each result is averaged over 200 author-disjoint splits, with the line set at 5% false alarms on the derivation half:

| Method | Catch at sc+ | Honest false alarms |
|---|---|---|
| One shared line, `deviation_score` | 35.1% | 7.8% |
| One shared line, `llr_deviation_score` | 47.7% | 9.7% |
| One shared line, both (min) | 54.5% | 10.4% |
| **Per-writer line, `deviation_score`** | **49.6%** | **6.1%** |
| Per-writer line, `llr_deviation_score` | 48.4% | 6.1% |

The per-writer line is the only method that improves both rates at once. The `rebind` mode (an llr-only shared line) lost to `gate` and stays off.

Limits:
- Each writer had 2 to 4 honest papers.
- No real student writing was used.
- The hold-out split pattern was inspected during this exploration, so the numbers above are exploratory and not a validation result.

## How it relates to typicality

`typicality_band` already self-calibrates per student. It compares the paper with `state.loo_distances` (leave-one-out `rms_z` of the baseline papers) using a conformal p-value.

Its `1/(N+1)` floor makes the band unreachable below about 33 baseline papers, so it rarely fires. `TYPICALITY_POOLED_CALIBRATION` tried to fill that gap by pooling peers, and its G1p gate failed.

The per-writer line uses the same leave-one-out idea, with two differences:
- It is parametric: a z-score against the writer's own mean and spread, with a floor on the spread. That lets it work from 2 papers.
- It is measured on `deviation_score`, the number the verdict already uses.

## Goals

- New flag `WRITER_LINE` with values `off` (the default), `shadow` and `on`.
- When at least `WRITER_LINE_MIN_PAPERS` baseline papers exist (proposed: 3):
  - compute each baseline paper's leave-one-out `deviation_score` against the rest;
  - convert the submission's score to `z = (d - mean) / max(std, WRITER_LINE_STD_FLOOR)`;
  - map z to a tier through `WRITER_LINE_Z_THRESHOLDS`.
- Below the minimum, or on any degraded path, fall back exactly to today's behaviour (NORTH_STAR rule 3).
- `shadow` logs `writer_line_would=` and `writer_line_z=` and changes nothing.

## Non-goals

- No change to the features, `deviation_score`, `llr_deviation_score`, or the impostor pool.
- **It does not solve early papers.** Papers 1 and 2 still use the shared line. It improves verdicts only once a student has a history.
- No `on` in production.

## Anti-goals

These would count as failure even if the code works:
- Honest students are flagged more often than they are today.
- A writer whose own papers vary a lot gets a line so wide that nothing is ever flagged. The spread floor and a cap on the spread both guard against this, and the report counts how often it happens.
- Cut-offs are tuned on the hold-out.

## Decisions proposed

1. **Order with `LLR_ACTION_MODE=gate`.** The writer line replaces the base tier, then `gate` may still lower it one step. The catastrophic-drift escalate override is unchanged.
2. **Cost.** The leave-one-out scores need N extra scoring passes over the baseline. Compute them when the baseline changes and store them with the student state, next to `loo_distances`, not on every request.
3. **Minimum papers: 3,** so each leave-one-out line rests on at least 2 papers. The exploratory data could not compare 2 against 3.

## Validation (`G-WRITERLINE`)

- The new gate gets a failure witness in `validation/gate_contracts.py`.
- z cut-offs are chosen on a derivation split only. The hold-out is touched once.
- It reports catch and false alarms against `gate` mode, by corpus, with Wilson intervals.
- It passes only if all three hold on the hold-out:
  - the false-alarm rate is no higher than `gate`'s;
  - the false-alarm rate is at or below 5%;
  - catch is higher than `gate`'s.
- It returns `uninformative` when n_genuine is under about 74, which the current records are.
- **A pass needs a larger honest corpus first.** Candidates: more PAN authors with at least 4 papers each, or `public_authors` works split into more documents.
- TermSim cell `writer-line`, with its scorecard diff against `baseline`.

## Left to the builder

- Exact constant values, chosen from the derivation split.
- Where the stored leave-one-out scores live (a state field or a repository column).
- Test names.

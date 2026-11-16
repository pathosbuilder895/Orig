# Let the peer-relative score decide the verdict (`LLR_ACTION_MODE=rebind`)

*2026-11-16. Asked for by Andrew. Status: design, awaiting approval. Nothing here is enabled.*

## Why

The verdict a teacher sees comes from `deviation_score`, and that score is weak. Every figure below was measured on published or corpus writing, none on real students:

- New topic (PAN, 12 authors): it catches 11.1% of papers at a 1% false-alarm rate.
- Genre change (Lewis vs Chesterton): its AUC is 0.387, which is worse than chance. Even with the `gate` downgrade, 42% of honest papers land at `schedule_conversation` or above.

`llr_deviation_score` compares the paper with the student's own baseline *and* with same-tenant peers. It is already computed on every scoring call when `NULL_MODEL=impostor`, but it can only downgrade a verdict by one step.

| Test (MODEL_CARD.md) | Catch rate | False-alarm rate |
|---|---|---|
| Cross-work, published authors | 61.1% | 1% |
| Cross-topic | 30.6% | 1% |
| Seminary, N=3 baselines | 0.8 | 5% |

Andrew wants more not-own papers caught, especially early papers, with a very low false-alarm rate. The pilot target is 75% catch at 5% false alarms or fewer (`docs/alpha/scoring_plan.md`). That target is a direction to calibrate toward, not a claim.

## Goals

- Add a new `LLR_ACTION_MODE` value, `rebind`, in which the action tier is derived from `llr_deviation_score` whenever a real one exists.
- Choose the rebind cut-offs on a derivation corpus. Report catch and false-alarm rates on a held-out corpus, author-disjoint, separately for each corpus.

## Non-goals

- No changes to `deviation_score`, `quantum_fidelity`, the features, or the impostor pool itself.
- No `on` flip in production. Today's default stays `gate`.
- This is not AI detection, and no new claim is made to teachers.

## Anti-goals

These would count as failure even if the code works:

- Honest students are flagged more often than they are today.
- Cut-offs are tuned on the hold-out.
- A shadow soak never fires, and that is read as a pass.

## Constraints

- **NORTH_STAR rule 4.** Ship default-off, enable only after a validation gate passes and Andrew approves, and run in shadow first.
- **Rule 3.** With no peer pool (no impostor stats, or fewer than 3 students or 5 vectors), fall back to today's behaviour exactly. Never guess.
- **Flag-off byte identity.** `gate`, `shadow`, `trigger` and `blend` must produce output identical to today's. `score-integrity-reviewer` must sign off.
- **The new gate needs a failure witness** in `validation/gate_contracts.py`.
- **Coverage.** CI requires 98% coverage, branches included.

## Approaches considered

1. **Rebind (picked).** The action tier comes from `llr_deviation_score`, with today's behaviour as the fallback. It targets both the low catch rate and the topic-shift false alarms.
2. **Both-must-agree.** Rejected. `deviation_score` is worse than chance on genre change, so requiring agreement throws away most of llr's catches.
3. **Also let llr raise the verdict one step.** Rejected as too small to reach the target.

## Design

1. In `quantum/scoring.py`, `_llr_action_candidates` gains a `"rebind"` candidate. It maps `llr_deviation_score` to a tier through a new constant, `LLR_REBIND_THRESHOLDS`: monotone cut-offs for `monitor`, `schedule_conversation` and `escalate`. The candidate is applied only under `mode == "rebind"`.
2. `shadow` mode logs `rebind_would=` alongside the existing candidates, so a pilot soak measures it with nothing changed.
3. **Catastrophic drift.** The override that forces `escalate` stays as it is (proposed). Its firing rate on honest genre-shift papers is reported, because it could undo rebind's false-alarm gain.
4. **New calibration gate** (`G-REBIND`).
   - Cut-offs are chosen on a derivation split only, and hold-out results are reported apart from them.
   - Corpora: seminary, `public_authors`, and PAN.
   - It passes only if all three hold:
     - catch at `schedule_conversation`+ beats `gate` mode;
     - honest false-alarm rate at `schedule_conversation`+ is at or below 5%, and also at or below `gate` mode;
     - escalate false-alarm rate is at or below `gate` mode.
   - Each result carries a Wilson interval. When the corpus is too small to reach the 5% bar, the verdict is `uninformative`.
5. Update the CLAUDE.md flag-table row, MODEL_CARD.md, and STATUS.

## Left to the builder

- The exact threshold values, from the derivation split.
- Test names.
- Whether `rebind` should also read `typicality_band`. Default: no.

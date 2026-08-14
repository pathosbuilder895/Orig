# Does a compression / character-LM channel improve the pan_stack same-author fusion?

Every same-author signal in this repo derives from a curated inventory: the
109-dim feature pipeline, LUAR embeddings, Burrows' Delta word frequencies,
LambdaG POSNoise grammars. A compression channel measures character-sequence
predictability directly and should fail differently. Nothing in the codebase
did compression-based verification before this study — the 2026-08-05
literature sweep did not even list it as a candidate.

Two backends were built (`validation/verify/compression_signals.py`):

- `compression_delta` — cross-entropy in bits/char of the unknown text under a
  Kneser-Ney character LM (order 4, `NGramLM` from
  `validation/attribution/lambdag.py` fed character tuples) trained on the
  author's known texts, minus the same quantity under a pooled peer model.
  Positive ⇒ the author's own model predicts the text better. Plus
  `compression_h_author`, the raw self cross-entropy, for ablation.
- `compression_ncd` — stdlib zlib normalized compression distance.

The ablation (`validation/verify/pan_stack_compression.py`) mirrors
`pan_stack_delta.py` exactly: identical 120-development / 20-fusion /
20-threshold / 12-locked author split, identical base signals, identical
`fit_grouped_fusion` helper. The only variable between arms is which
compression signals are present.

## Pre-registered gate: G-P1 on `compression_delta`

**Verdict: FAIL** (1 of 3 criteria met).

| | base only | + compression_delta |
|---|---:|---:|
| AUC | 0.8455 | 0.8422 |
| Brier | 0.1031 | 0.1207 |
| Cllr | 0.8844 | 1.0240 |
| Recall @ 1% FPR (transferred threshold) | 30.6% | 38.9% |
| Precision @ 1% FPR | 78.6% | 63.6% |
| Recall @ 5% FPR | 61.1% | 72.2% |
| Precision @ 5% FPR | 61.1% | 51.0% |

- cllr strictly improves: **no** (+0.1396 — it got worse, and crossed 1.0,
  the uninformative line)
- ΔAUC ≥ +0.005: **no** (−0.0032)
- recall @ 1% FPR does not regress: **yes** (+8.3 points)

Abstention was 0.000 on every partition, so this is a real null result and not
an unfired mechanism — the trap `GENRE_INVARIANT_WEIGHTS_ENABLED` fell into.

The recall gain is not what it looks like. At the *locked-optimal* 1% FPR
operating point, `tpr_at_fpr["0.01"]` moves 38.9% → 27.8% — the channel makes
locked recall worse. The +8.3 points in the table come from the threshold
transferred from the calibration partition landing in a luckier place, while
FPR simultaneously drifts 0.76% → 2.02% (i.e. the "1%" bar was not held).
Together with Brier and cllr both worsening, this reads as a calibration
failure layered on a discrimination non-result, not as evidence of benefit.

Honest size statement: 36 genuine and 396 impostor locked trials. Recall moves
in 1/36 = 2.8-point steps, and ΔAUC −0.0032 is indistinguishable from zero.
The correct reading is **"no evidence that `compression_delta` helps"**, not
"evidence that it harms." The FAIL is carried by cllr, the criterion least
sensitive to that noise.

`compression_h_author` is inert: in the all-signals arm its standardized
coefficient is 0.017, versus 1.29 for `compression_delta` and −1.09 for
`compression_ncd`. Raw self-entropy carries nothing the peer-relative
difference does not already carry.

## The unregistered NCD arm — reported, deliberately not claimed

`compression_ncd` clears all three bars (AUC 0.8455 → 0.8814, cllr 0.8844 →
0.7637, recall @ 1% FPR 30.6% → 55.6% at 1.77% FPR), and it was also the
better of the two on the development partition.

**This is not a pass, and must not be cited as one.** G-P1 pre-registered
`compression_delta`; the NCD arm's locked numbers have now been observed, and
a criterion applied after seeing the held-out result is not a held-out
criterion. Claiming it would convert the locked partition into a tuning set —
the exact failure mode `TOPIC_INFLATE_GAIN`'s note warns about.

There is also a substantive reason for suspicion. Adding NCD flips
`character_similarity`'s coefficient from +1.08 to −0.48, which is the
signature of NCD partly *substituting* for the existing LUAR character channel
rather than contributing orthogonal evidence. A fusion that reshuffles weight
between two correlated channels can improve on one split without generalizing.

If NCD is worth pursuing, it needs a fresh pre-registration against a locked
set that has not been used here — a new study, not a re-reading of this one.

## Consequence

No production compression channel ships. Phase 1B of
`docs/superpowers/plans/` — the `original/compression_authorship.py` expert and
its four attach sites — is **not** built. The two validation modules and this
document are the whole deliverable.

## Reproducing

```bash
~/Desktop/Original/.venv/bin/python -m validation.verify.pan_stack_compression
```

Requires the PAN 2020 cache at `.benchmark_cache/pan/2020`
(`scripts/fetch_benchmark_data.py --pan`). Runtime ~65 s. The run is
deterministic: reports written 2026-08-08 and 2026-08-10 are byte-identical in
every metric. Report:
`validation/benchmarks/2026-08-10/pan_stack_compression_ablation.json`.

Hyperparameters (order 4, 200k-char peer pool, zlib, 16k-char NCD cap) were
selected by standalone signal AUC on the **fusion_development** partition only;
the locked partition was read once, for the numbers above.

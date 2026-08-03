# ⚠️ This run is INVALID — do not quote its numbers

Superseded by `validation/benchmarks/2026-08-02/public_authors/`.

This run scored a **contaminated** public-author corpus, fixed on `main` in
`9fa2092e` ("Import decontaminated public-author corpus"):

- **`edwards` was a French science-fiction novel** — *Aventures
  Extraordinaires d'un Savant Russe* (PG 24962), filed under
  `a_treatise_concerning_religious_affections_part_*.txt`. Verified in the
  scored file: 1,399 French markers, 0 English.
- **`james`** ended in roughly 32,000 words of index and footnote
  back-matter rather than prose.

**7 of this run's 22 held-out essays (32%) belonged to those two authors.**
All three `edwards` essays were attributed correctly by all three engines,
which is unsurprising — separating French from English is trivial for any
stylometric method — so every engine's accuracy was inflated by free
correct answers.

The run is kept rather than deleted because it is an honest record of what
was measured, and because the size of the correction is itself informative.
Rewriting or deleting a stored run to match a later conclusion is the
specific failure this validation layer exists to prevent.

## How much it mattered

| | this run (contaminated, n=22, 9 authors) | 2026-08-02 (clean, n=27, 11 authors) |
|---|---|---|
| `mfw_delta` | 90.91% | 100.00% |
| `cosine_delta` | 77.27% | 81.48% |
| `deviation_calibrated` | 74.07%¹ | 74.07% |
| raw argmin (retired rule) | **36.36%** | **70.37%** |

¹ 72.73% in this run.

The raw-argmin row is the one that matters. This run's headline finding —
that the retired rule collapsed to 36% and dumped **all 14** of its
misattributions on `emerson`, a worse "black hole" than the Instrument
Report's original 11-of-12 — **does not survive decontamination**. On the
clean corpus the retired rule scores 70.37% and makes only 8 errors in 27,
concentrated on `mill` (7 of 8), not `emerson`.

The concentration phenomenon is real and reproduces. Its magnitude here was
mostly an artifact of a French novel sitting in the candidate pool and
distorting the shared scale.

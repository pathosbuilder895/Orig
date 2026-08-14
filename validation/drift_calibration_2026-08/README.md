# Drift-Gate Calibration Study (2026-08)

Calibrates `StudentState.check_drift`'s threshold (original/quantum/state.py)
against real single-author corpora: genuine per-upload false-hold rate vs.
cross-author / AI-text catch rate, swept over threshold × anchor-tier set ×
`consecutive_required` × cold-start baseline size.

**Outcome (2026-08-13): default threshold raised 0.25 → 0.30.** Full write-up
with tables and the decision rationale:
`docs/calibration/drift_gate_threshold_2026-08-13.md`.

Files:

- `extract_vectors.py` — extracts the production 109-dim feature vector once
  per corpus doc (seminary + historical + public_authors + AI/ghost, 535
  docs) into an `.npz` cache (~9 min on 8 cores).
- `calibrate.py` — the sweep. Verifies its simulator against the real
  `check_drift` bit-for-bit before running (fails hard on divergence).
- `results_2026-08-13.json` — committed sweep output backing the write-up.

Reproduction:

```
~/Desktop/Original/.venv/bin/python validation/drift_calibration_2026-08/extract_vectors.py /tmp/drift_vectors.npz
~/Desktop/Original/.venv/bin/python validation/drift_calibration_2026-08/calibrate.py /tmp/drift_vectors.npz /tmp/out.json
```

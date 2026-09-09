# 02 — Unit, property, and math-invariant tests

Scope: `original/features/` (18 tiers + pipeline), `original/quantum/`
(state, scoring, narrative, conformal, drift), `original/context/`,
`original/fusion/`, `original/voice.py`, `original/db/tenancy_shim.py`, and
the pure helpers under `original/`.

The coverage effort already made every line run. This document is about
whether the tests would *notice a wrong number*. Three instruments: property
tests over the math, an explicit oracle for each tier, and a mutation score.

---

## 1. Feature tiers

### 1.1 The tier-8 hole

`original/features/tier8.py` (prosodic rhythm, stress entropy) is the only
tier without a dedicated test file. Add `tests/test_tier8.py` following the
`test_tier7.py` shape. Minimum content:

- **Oracle cases.** Three hand-computed inputs: a monotone text (all stressed
  syllables identical) → entropy 0 → normalised value at the low bound; an
  alternating iambic line → known entropy; empty/one-word text → the neutral
  0.5 placeholder, not an exception.
- **Bounds.** Every returned code is in `[0, 1]` for 200 random strings of
  1–2,000 words (hypothesis `st.text()` filtered to printable ASCII plus
  curly quotes — the tier-6 bug class).
- **Determinism.** Same text, same vector, across `PYTHONHASHSEED` — reuse the
  subprocess helper from `test_feature_pipeline_determinism.py`.
- **Registry pin.** `tier8` codes appear in `ALL_FEATURE_CODES` in the
  documented order (guards the "don't reorder" rule).

### 1.2 One invariant file for all tiers

`tests/test_tier_invariants.py`, parametrised over every `extract_tierN`:

| Invariant | Why |
|---|---|
| Output keys == the tier's slice of `ALL_FEATURE_CODES`, no more, no fewer | catches a renamed code silently padding with 0.5 |
| All values finite and in `[0, 1]` | NORM_BOUNDS clipping is load-bearing |
| Text with only whitespace/punctuation returns placeholders, never raises | the 0.5 neutral contract |
| Doubling the text (`t + " " + t`) moves rate-type features by < ε | length-invariance claim for rate features; length-*sensitive* features are listed explicitly and excluded |
| Curly vs straight quotes give identical dialogue/quotation features | the Gutenberg bug class, pinned once for every tier |

### 1.3 Measurability is a test subject too

`validation/measurability.py` decides what may be averaged. Add a test that
walks `ALL_FEATURE_CODES` and asserts every code has a status and that
`DISABLED_FEATURE_GROUPS` changes are reflected live (monkeypatch the set, ask
again). Today the status table can go stale silently when a tier is added.

## 2. Quantum scoring invariants

`quantum/scoring.py` (2,177 lines) has 22 referencing test files but its tests
are overwhelmingly *example* tests. The properties below are the ones the
architecture review would have needed. Put them in
`tests/quantum/test_scoring_properties.py` with hypothesis, `max_examples=50`,
`deadline=None`.

### 2.1 Baseline-count monotonicity (the saturation property)

> For a fixed submission drawn from the same distribution as the baseline,
> `deviation_score(N)` must be non-increasing in expectation as N grows, and at
> the pilot floor N=3 the *same-author* median must sit below the `monitor`
> ceiling (0.60).

This is the test that fails today. Build it from committed corpora
(`validation/public_authors/`, `validation/corpus/seminary_*`): for each author,
sample N ∈ {3, 5, 10, 20} baseline chunks, score a held-out chunk through
`score()` with the production `ScoringConfig` (flags off), record
`deviation_score`. Assert the medians are monotone and the N=3 median < 0.60.
Mark it `@pytest.mark.certification` (new marker, §09) so it can be reported
three-valued: `uninformative` if fewer than 8 authors are available.

This is the unit-level twin of §06 §3's certification gate. Keep both: this one
runs in seconds on chunk vectors; that one runs through the API.

### 2.2 Sigma-floor properties

`state.py:271`, `adaptive_floor = max(0.005, 0.15 / sqrt(N))`.

- The fraction of features *on* the floor is reported by the state (add a
  diagnostic property `floor_fraction` if absent) and a test asserts it drops
  below 0.5 by N=10 on real corpus chunks. Today it is 63–83 % at N=3.
- With `baseline_std` forced to zero on every feature, `rms_z` is finite and
  equals the value computed with `sigma = floor` — i.e. the floor is a floor,
  not an additive term.

### 2.3 Weight-vector energy conservation

The `CHARACTERISTIC_WEIGHTS` rescale preserves `Σ(w²)` over the *active* set.
Assert it directly: for random active masks and random ratio vectors,
`sum(w[active]**2)` before == after within 1e-9, and `w[~active] == 1.0`
exactly. The CLAUDE.md row documents why the wrong normalisation inflated
every score; the test should make the right one unbreakable.

### 2.4 Action-tier ordering

`_apply_llr_action_mode` under `gate` may only *downgrade* one step; under
`trigger` may only *upgrade* `no_action → monitor`; under `shadow` never
changes the action. Property: for all `(deviation, llr, mode)` triples, the
output action's rank differs from the input's by at most one, in the permitted
direction only. `blend` is documented as do-not-enable; still assert it is
deterministic so the do-not-enable is a policy decision, not a crash.

### 2.5 Trajectory adjustment bounds

`D_adjusted` differs from `D_raw` by at most the documented trajectory band;
with fewer than `TRAJECTORY_MIN_SAMPLES` the adjustment is exactly zero.

### 2.6 Shadow ≡ on

For every shadow-capable flag (`TOPIC_VARIANCE_INFLATION`,
`CHARACTERISTIC_WEIGHTS`, `GENRE_RESOLVER_V2`, `FUSED_SCORE`,
`AI_LIKELIHOOD`): the preview field under `shadow` equals the primary field
under `on`, bit-for-bit, for random inputs. Some of these exist as example
tests; make them properties in one place so a new shadow flag inherits the
check by adding one row to a parametrise list.

## 3. Redaction: `voice.py`

`test_voice_leak.py` is one file guarding the "students never see raw scores"
promise. Strengthen it into an *allowlist* test:

```python
ALLOWED_VOICE_KEYS = {...}  # the ADR-005 wire contract, spelled out

def test_voice_payload_is_exactly_the_allowlist(live_client, seeded_student):
    body = live_client.get("/me/voice", headers=student_headers).json()
    assert set(walk_keys(body)) <= ALLOWED_VOICE_KEYS

@pytest.mark.parametrize("forbidden", ["deviation_score", "rms_z", "llr_deviation_score",
                                       "recommendation", "quantum_fidelity", "z_scores"])
def test_forbidden_field_never_appears_anywhere(forbidden, voice_payload_text):
    assert forbidden not in voice_payload_text
```

`walk_keys` recurses into nested dicts and lists. The second test operates on
the serialised JSON text so a value smuggled inside a string is also caught.

## 4. Pure helpers that deserve property tests

| Module | Property |
|---|---|
| `db/tenancy_shim.py` | `join(split(x)) == x` for all scoped ids; `split("demo:foo")` and legacy flat ids produce the documented, distinct shapes; no input raises |
| `principal.py` token sign/verify | round-trip; any single-byte flip fails verification; expiry boundary is exclusive |
| `student_auth.py` HMAC launch tokens | same as above; tokens for tenant A never verify under tenant B's key material |
| `upload_utils.py` extraction | every supported extension round-trips a known string; unsupported raises the documented error, never a bare exception |
| `quantum/conformal.py` | interval contains the point estimate; width non-increasing in N |

## 5. Mutation testing — measuring assertion strength

Coverage cannot distinguish a test that asserts from a test that runs. Add
`mutmut` (or `cosmic-ray`; pick one, pin it in `requirements-dev.txt`) and run
it **weekly, non-blocking**, on a fixed module list:

```
original/quantum/scoring.py
original/quantum/state.py
original/features/pipeline.py
original/principal.py
original/db/tenancy_shim.py
original/voice.py
```

Report the surviving-mutant list into the workflow summary. Target ≥ 80 % kill
rate per module; the first run will be lower and *that number is the finding*.
Do not run mutation on the whole package — at 35k lines it is days of compute
for no additional signal. Do not make it blocking until it has been green three
weeks running.

Expect these to survive on the first run, and treat each as a test to write:
constant tweaks in `ACTION_THRESHOLDS` boundaries (are `<` vs `<=` pinned?),
sign flips in the trajectory adjustment, off-by-one in the `n_active` divisor.

## 6. Narrative and explanation text

`professor_narrative.py` (806 lines, 3 test files) generates prose professors
act on. Do not snapshot the prose — it should be free to improve. Assert
*content obligations* instead:

- The narrative names every feature in the top-k contributors list and no
  feature outside it.
- If `recommendation == "no_action"`, the narrative contains no escalation
  vocabulary (maintain a short forbidden-word list).
- If typicality was withheld (inflation or characteristic weights active), the
  narrative says so in the documented sentence.
- The narrative never contains a student id, email, or raw z-score array.

The coverage effort found a `_FEATURE_PLAIN` key mismatch that made a test pass
vacuously; add a test that every key in `_FEATURE_PLAIN` is a real feature
code and every active feature code has a plain-English entry.

## 7. What this document deliberately leaves alone

- Tier 17 (behavioural biometrics) and tier 18 (uniformity) are disabled and
  gated on external data; keep their existing tests, add nothing.
- The density matrix / Born projection. It is a consistency check, not the
  score driver (see `scoring.py`'s own docstring). Its existing round-trip and
  PSD tests are adequate.

## 8. Acceptance for this slice

- `tests/test_tier8.py` and `tests/test_tier_invariants.py` exist and pass.
- `tests/quantum/test_scoring_properties.py` exists; §2.1 is red until the
  saturation fix lands and is reported as such, not skipped.
- `voice.py` allowlist test passes.
- A weekly mutation workflow posts a kill rate for the six modules.

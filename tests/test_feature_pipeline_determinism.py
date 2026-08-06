"""The FEATURE_DIM-feature pipeline must produce a byte-identical vector across processes.

Why a subprocess test: several tier modules build per-sentence content-word
sets (``tier2._content_words``) and then treat their iteration order as
meaningful (e.g. splitting a sentence's content words into a "first half"
and "last half" for theme/rheme analysis). Python randomises string hashing
per interpreter, so a *set's* iteration order is fixed for the life of one
process but varies between processes. A same-process "call ``feature_vector``
twice" assertion would therefore always pass and catch nothing; only separate
interpreters expose the churn.

We drive ``PYTHONHASHSEED`` explicitly rather than relying on chance. Against
the pre-fix code, ``thematic_progression_score`` (tier2.py) differed between
seeds on ordinary multi-sentence prose because ``thematic_progression_score``
did ``list(_content_words(sentence))`` on a ``set``, then sliced that list in
half to approximate sentence-order theme/rheme position — an operation that
is only meaningful, and only deterministic, if the list preserves the
sentence's original word order.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Hash seeds that provably straddled differing set-iteration orders for the
# pre-fix code on the sample text below.
HASH_SEEDS = ["0", "1", "2"]

SAMPLE_500_WORD_TEXT = """
Epistemology narrative structure allegory metaphor rhetoric persuasion syntax diction
cadence imagery symbolism theme motif characterization dialogue exposition denouement.

The relationship between authorial intent and textual meaning has occupied literary
theorists for generations, spanning formalist, structuralist, and post-structuralist
frameworks. Scholars debate whether a text's significance resides primarily in the
author's original purpose or emerges independently through reader interpretation.
Contemporary criticism increasingly favors a synthesis, acknowledging both the
historical context of composition and the interpretive latitude granted to readers
across different cultural moments. This tension between production and reception
animates much of modern hermeneutics, particularly when applied to canonical works
whose meanings have shifted considerably since their initial publication.

Consider how allegorical narrative structures encode multiple layers of signification
simultaneously, permitting surface-level engagement alongside deeper symbolic reading.
A skilled author calibrates diction and cadence to reinforce thematic concerns, using
rhetorical devices not merely for ornamentation but as load-bearing elements of
argumentative persuasion. Dialogue serves characterization while exposition establishes
the narrative's governing logic; denouement then resolves accumulated tension through
catharsis, verisimilitude, or deliberate ambiguity, depending on authorial intent and
generic convention.

Rhetorical analysis further reveals how sentence-level choices accumulate into a
recognizable authorial voice. Syntax patterns, preferred transitions, and habitual
imagery form a fingerprint distinct from any single stylistic flourish. Motif
recurrence across a longer work strengthens thematic coherence, while variation in
sentence length modulates pacing and emotional register. These structural and stylistic
signals, taken together, distinguish one writer's prose from another's even when
surface topics converge, which is precisely why stylometric analysis treats them as
load-bearing evidence rather than incidental texture.
""".strip()

# Child program: import the live pipeline, extract the fixed sample text, and
# write the resulting feature vector (in ALL_FEATURE_CODES order) as JSON.
# Writing to a file (not stdout) keeps model-loading warnings/logs from any
# tier backend (spaCy, sentence-transformers) out of the payload.
_CHILD = """
import json, sys
from original.features.pipeline import feature_vector

text = sys.argv[2]
vec = feature_vector(text)
with open(sys.argv[1], "w") as fh:
    json.dump(vec.tolist(), fh)
"""


def _feature_vector_in_subprocess(hash_seed: str, out_path: Path, env_extra: dict) -> list:
    """Extract the fixed sample text's feature vector in a fresh interpreter."""
    env = dict(env_extra)
    env["PYTHONHASHSEED"] = hash_seed
    env["PYTHONPATH"] = str(REPO_ROOT)

    result = subprocess.run(
        [sys.executable, "-c", _CHILD, str(out_path), SAMPLE_500_WORD_TEXT],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert (
        result.returncode == 0
    ), f"feature extraction failed (PYTHONHASHSEED={hash_seed}):\n{result.stderr}"
    return json.loads(out_path.read_text())


@pytest.fixture(scope="module")
def _base_env() -> dict:
    """A minimal, inherited-PATH environment for the child interpreters."""
    import os

    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
    return {k: v for k, v in os.environ.items() if k in keep}


@pytest.mark.slow
def test_feature_vector_is_identical_across_processes(tmp_path, _base_env):
    """Two separate interpreters must extract a bit-identical feature vector."""
    first = _feature_vector_in_subprocess(HASH_SEEDS[0], tmp_path / "first.json", _base_env)
    second = _feature_vector_in_subprocess(HASH_SEEDS[1], tmp_path / "second.json", _base_env)

    assert first == second, (
        "feature_vector() differs between processes — some tier module's "
        "output depends on per-process set/dict iteration order."
    )


@pytest.mark.slow
def test_feature_vector_is_stable_across_hash_seeds(tmp_path, _base_env):
    """Sweep several seeds; every one must agree with the first, index for index."""
    from original.constants import ALL_FEATURE_CODES

    vectors = {
        seed: _feature_vector_in_subprocess(seed, tmp_path / f"vec-{seed}.json", _base_env)
        for seed in HASH_SEEDS
    }

    reference_seed = HASH_SEEDS[0]
    reference = vectors[reference_seed]
    churn = {
        ALL_FEATURE_CODES[i]
        for seed, vec in vectors.items()
        for i in range(len(reference))
        if vec[i] != reference[i]
    }
    if churn:
        pytest.fail(
            f"feature_vector() is not reproducible across PYTHONHASHSEED; "
            f"unstable feature codes: {sorted(churn)}"
        )

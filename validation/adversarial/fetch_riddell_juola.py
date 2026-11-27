"""
validation/adversarial/fetch_riddell_juola.py — import the Riddell-Juola
adversarial-stylometry corpus (Task 16).

Downloads the CC0-licensed reproducibility bundle for Wang, Juola & Riddell,
"Reproduction and Replication of an Adversarial Stylometry Experiment"
(Zenodo DOI 10.5281/zenodo.18729526), verifies its integrity by MD5, and
extracts the three human-written "attack" splits — control, obfuscation,
and imitation essays — into flat per-split directories under
validation/adversarial/corpus/riddell_juola/.

Run:
    .venv/bin/python validation/adversarial/fetch_riddell_juola.py

Participant baselines: `main()` also extracts each split participant's
PRE-EXISTING writing (the bundle's corpus/<hex_id>/<hex_id>_NN.txt chunks,
which the original study built its stylometric models from) into
corpus/riddell_juola/baselines/ via `extract_participant_baselines`. The
SP1 harness needs them to score an attack essay as verification, against
the participant's own earlier writing. Task 16 extracted only the three
attack splits; until baselines/ is committed, the harness reports its
Riddell-Juola cells as not measured.

Loader: `load_riddell_juola_split(name)` at the bottom of this module is
the runtime loader used by tests/adversarial/test_riddell_juola.py and any
future SP1 harness code. It lives in this file (rather than a separate
validation/adversarial/riddell_juola.py) because it's a handful of lines
with no extraction logic of its own — reading committed .txt files off
disk — and keeping fetch + load together avoids a near-empty second module
for one function. If a later task grows real loader logic (caching,
filtering, pairing with metadata.csv) it should probably move out to its
own module at that point.
"""

from __future__ import annotations

import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
CORPUS_DIR = _HERE / "corpus" / "riddell_juola"

ZENODO_DOI = "10.5281/zenodo.18729526"
ZENODO_RECORD_URL = "https://zenodo.org/api/records/18729526"
DOWNLOAD_URL = "https://zenodo.org/api/records/18729526/files/rr_bundle.zip/content"

EXPECTED_SIZE_BYTES = 2427488
EXPECTED_MD5 = "3b4dbe6edde117d80a0f5e764f594d53"

# Path of the three attack-condition folders inside the zip, relative to
# the zip root. Files directly inside each are "<6-char-hex-id>.txt".
_BUNDLE_CORPUS_PREFIX = (
    "rr_bundle/resource/defending-against-authorship-attribution-corpus/corpus/"
)

# Maps the bundle's on-disk folder name to this module's split name.
SPLITS = {
    "control": "attacks_control",
    "obfuscation": "attacks_obfuscation",
    "imitation": "attacks_imitation",
}


class IntegrityError(RuntimeError):
    """Raised when the downloaded bundle fails its size/MD5 check."""


def download_bundle(url: str = DOWNLOAD_URL) -> bytes:
    """Download the Zenodo bundle zip into memory and return its bytes."""
    with urllib.request.urlopen(url) as response:  # noqa: S310 (fixed https URL)
        return response.read()


def verify_integrity(data: bytes) -> None:
    """Fail loudly if `data` doesn't match the bundle's known size/MD5.

    This is the integrity check called for by the task brief — a
    mismatch means the file was truncated, corrupted, or is not the
    bundle it claims to be, and must not be silently extracted.
    """
    actual_size = len(data)
    if actual_size != EXPECTED_SIZE_BYTES:
        raise IntegrityError(
            f"riddell_juola bundle size mismatch: expected "
            f"{EXPECTED_SIZE_BYTES} bytes, got {actual_size} bytes"
        )
    actual_md5 = hashlib.md5(data).hexdigest()
    if actual_md5 != EXPECTED_MD5:
        raise IntegrityError(
            f"riddell_juola bundle MD5 mismatch: expected {EXPECTED_MD5}, "
            f"got {actual_md5} — refusing to extract an unverified bundle"
        )


def extract_splits(data: bytes, dest: Path = CORPUS_DIR) -> dict[str, int]:
    """Extract the three attack-condition splits' .txt files into `dest`.

    Flattens each `attacks_<split>/<hex_id>.txt` member directly into
    `dest/<split>/<hex_id>.txt` — the full `rr_bundle/resource/.../corpus/`
    nesting is not preserved. Returns a dict of split name -> file count
    extracted.
    """
    counts: dict[str, int] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for split_name, bundle_folder in SPLITS.items():
            prefix = f"{_BUNDLE_CORPUS_PREFIX}{bundle_folder}/"
            split_dir = dest / split_name
            split_dir.mkdir(parents=True, exist_ok=True)
            n = 0
            for member in zf.namelist():
                if not member.startswith(prefix):
                    continue
                rel = member[len(prefix) :]
                # Only flat files directly in this folder, not nested
                # per-participant subdirectories elsewhere in the bundle.
                if not rel or "/" in rel or not rel.endswith(".txt"):
                    continue
                out_path = split_dir / rel
                out_path.write_bytes(zf.read(member))
                n += 1
            counts[split_name] = n
    return counts


def extract_participant_baselines(data: bytes, dest: Path = CORPUS_DIR) -> dict[str, int]:
    """Extract every participant's PRE-EXISTING writing into
    `dest/baselines/<hex_id>/<hex_id>_NN.txt`, for the participants who
    appear in one of the three committed attack splits.

    These are the chunks the original study built its stylometric models
    from (see PROVENANCE.md "What was NOT extracted"). The SP1 harness needs
    them to score the attack essays as VERIFICATION, i.e. against the
    participant's own earlier writing; the attack splits alone have one
    essay per person and no reference to compare it with. Participants
    outside the three splits are skipped. Returns hex id -> chunk count.
    """
    wanted = {
        path.stem
        for split_name in SPLITS
        for path in (dest / split_name).glob("*.txt")
    }
    counts: dict[str, int] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.namelist():
            if not member.startswith(_BUNDLE_CORPUS_PREFIX):
                continue
            parts = member[len(_BUNDLE_CORPUS_PREFIX) :].split("/")
            if len(parts) != 2 or parts[0] not in wanted or not parts[1].endswith(".txt"):
                continue
            out_dir = dest / "baselines" / parts[0]
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / parts[1]).write_bytes(zf.read(member))
            counts[parts[0]] = counts.get(parts[0], 0) + 1
    return counts


def load_riddell_juola_split_by_id(name: str, corpus_dir: Path = CORPUS_DIR) -> dict[str, str]:
    """Like `load_riddell_juola_split`, keyed by participant hex id (the
    file stem), which the harness needs to pair an essay with its author's
    own prior writing."""
    if name not in SPLITS:
        raise ValueError(f"unknown riddell_juola split {name!r}; expected one of {sorted(SPLITS)}")
    split_dir = corpus_dir / name
    if not split_dir.is_dir():
        raise FileNotFoundError(f"riddell_juola split directory not found: {split_dir}")
    return {
        path.stem: path.read_text(encoding="utf-8") for path in sorted(split_dir.glob("*.txt"))
    }


def load_riddell_juola_baselines(corpus_dir: Path = CORPUS_DIR) -> dict[str, list[str]]:
    """Participant hex id -> that participant's prior-writing chunks, in
    filename order. Empty dict when `baselines/` was never extracted (the
    state Task 16 left the corpus in), so a caller can report the
    Riddell-Juola cells as not measured instead of crashing."""
    root = corpus_dir / "baselines"
    if not root.is_dir():
        return {}
    return {
        participant.name: [
            path.read_text(encoding="utf-8") for path in sorted(participant.glob("*.txt"))
        ]
        for participant in sorted(root.iterdir())
        if participant.is_dir()
    }


def load_riddell_juola_split(name: str, corpus_dir: Path = CORPUS_DIR) -> list[str]:
    """Load all essay texts for one split ("control", "obfuscation",
    "imitation") from the committed corpus directory.

    Returns a list of text contents, one per participant file, sorted by
    filename for determinism. Raises FileNotFoundError if the split
    directory doesn't exist (i.e. fetch_riddell_juola hasn't been run).
    """
    if name not in SPLITS:
        raise ValueError(f"unknown riddell_juola split {name!r}; expected one of {sorted(SPLITS)}")
    split_dir = corpus_dir / name
    if not split_dir.is_dir():
        raise FileNotFoundError(
            f"riddell_juola split directory not found: {split_dir} — "
            "run validation/adversarial/fetch_riddell_juola.py first"
        )
    texts = []
    for path in sorted(split_dir.glob("*.txt")):
        texts.append(path.read_text(encoding="utf-8"))
    return texts


def main() -> None:
    print(f"Downloading {DOWNLOAD_URL} ...")
    data = download_bundle()
    print(f"Downloaded {len(data)} bytes; verifying integrity ...")
    verify_integrity(data)
    print(f"MD5 verified: {EXPECTED_MD5}")
    counts = extract_splits(data)
    for split_name, n in counts.items():
        print(f"  {split_name}: {n} files -> {CORPUS_DIR / split_name}")
    baseline_counts = extract_participant_baselines(data)
    print(
        f"  baselines: {sum(baseline_counts.values())} chunks for "
        f"{len(baseline_counts)} participants -> {CORPUS_DIR / 'baselines'}"
    )
    print("Done.")


if __name__ == "__main__":
    main()
    sys.exit(0)

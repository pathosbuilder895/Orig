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

What this does NOT do: it does not touch the per-participant pre-existing
baseline-writing subdirectories also present in the bundle
(corpus/<hex_id>/<hex_id>_NN.txt) — those are a fourth, separate corpus
(each participant's own prior writing samples, used upstream by the
original study to build stylometric models) and are out of scope for this
task, which only asks for the three attack-condition splits. See
PROVENANCE.md for the exact path, in case a future task wants to extract
it.

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
    print("Done.")


if __name__ == "__main__":
    main()
    sys.exit(0)

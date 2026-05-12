"""
lab/datasets.py — Named datasets the lab can run calibration against.

A dataset is a `(corpus_dir, manifest_path, label, description)` tuple.
The lab UI exposes a dropdown of these; each entry maps to a path on
disk that ``validation.calibration.run_calibration`` can consume directly.

The "Federalist" dataset is a subset of the multi-author manifest
(filtered to Hamilton/Madison/Jay/disputed) so users can run the
classic study quickly without scoring Paine/Burke/Lincoln/Douglass.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


# Repository root, used to resolve default corpus + manifest paths.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class DatasetSpec:
    """One named dataset the lab knows how to run."""
    label: str            # short stable identifier, e.g. "federalist"
    name: str             # human-readable name for the dropdown
    description: str      # one-line explanation
    corpus_dir: str       # path to the directory of essay files
    manifest_path: str    # path to the JSON manifest
    author_filter: List[str]   # only run these author_ids; [] = all

    def to_dict(self) -> Dict:
        return {
            "label":         self.label,
            "name":          self.name,
            "description":   self.description,
            "author_filter": self.author_filter,
        }


# ── Registry ─────────────────────────────────────────────────────────────────

_REGISTRY: Dict[str, DatasetSpec] = {
    "multi_author": DatasetSpec(
        label="multi_author",
        name="Multi-Author (8 authors)",
        description=(
            "Federalist Papers + Paine, Burke, Lincoln, Douglass. Cross-era "
            "and cross-genre. Best for evaluating real-world generalisation."
        ),
        corpus_dir=str(_REPO_ROOT / "validation" / "corpus"),
        manifest_path=str(_REPO_ROOT / "validation" / "manifest.json"),
        author_filter=[],
    ),
    "federalist": DatasetSpec(
        label="federalist",
        name="Federalist Papers Only",
        description=(
            "Hamilton, Madison, Jay + disputed papers. Classic Mosteller & "
            "Wallace 1964 setup. Faster to run than the full multi-author corpus."
        ),
        corpus_dir=str(_REPO_ROOT / "validation" / "corpus"),
        manifest_path=str(_REPO_ROOT / "validation" / "manifest.json"),
        author_filter=["hamilton", "madison", "jay", "disputed_vs_madison"],
    ),
}


def list_datasets() -> List[Dict]:
    """Return the registry as a JSON-friendly list (for the dropdown)."""
    return [spec.to_dict() for spec in _REGISTRY.values()]


def get_dataset(label: str) -> DatasetSpec:
    """Look up a dataset by label; raise KeyError if unknown."""
    if label not in _REGISTRY:
        raise KeyError(f"unknown dataset: {label!r}; "
                       f"known: {sorted(_REGISTRY)}")
    return _REGISTRY[label]

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
    requires_build: bool = False
    build_cmd: str = ""

    def to_dict(self) -> Dict:
        return {
            "label":          self.label,
            "name":           self.name,
            "description":    self.description,
            "author_filter":  self.author_filter,
            "requires_build": self.requires_build,
            "build_cmd":      self.build_cmd,
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

    # Wide-benchmark datasets — the corpus + manifest are generated on the
    # fly by `validation/wide/run.py` from the cached public datasets, so
    # the lab UI must build them before running. The build_cmd is shown
    # to the user as the next-step instruction.
    "raid": DatasetSpec(
        label="raid",
        name="RAID — AI vs Human (8 domains)",
        description=(
            "Robust AI Detection benchmark: per-domain human prose vs LLM "
            "generations across wikipedia, news, books, etc. Tests how well "
            "Original separates real human writing from generated text in "
            "the same domain."
        ),
        corpus_dir="",   # set at run time by the wide orchestrator
        manifest_path="",
        author_filter=[],
        requires_build=True,
        build_cmd="python -m validation.wide.run --dataset raid",
    ),
    "pan_av_2021": DatasetSpec(
        label="pan_av_2021",
        name="PAN 2021 Authorship Verification",
        description=(
            "PAN 2021 authorship verification dataset, regrouped per author. "
            "Cross-topic same-author pairs — the classic hard test."
        ),
        corpus_dir="",
        manifest_path="",
        author_filter=[],
        requires_build=True,
        build_cmd="python -m validation.wide.run --dataset pan --pan-year 2021",
    ),
    "m4_en": DatasetSpec(
        label="m4_en",
        name="M4 — Multi-domain AI Detection (English)",
        description=(
            "M4 sample, English-only. Per-domain human vs AI text across "
            "arxiv, peerread, reddit, wikihow, wikipedia. Multiple "
            "generators (ChatGPT, davinci, cohere, dolly)."
        ),
        corpus_dir="",
        manifest_path="",
        author_filter=[],
        requires_build=True,
        build_cmd="python -m validation.wide.run --dataset m4",
    ),
    "autextification_en": DatasetSpec(
        label="autextification_en",
        name="AuTexTification — Human vs AI (IberLEF 2023)",
        description=(
            "English subtask-1 shared-task corpus: tweets, legal text, "
            "wikihow. The exact dataset the StyloAI paper "
            "(arxiv.org/html/2405.10129v1) reports 81% accuracy / 0.88 AUC "
            "on — built to run a real head-to-head, not an inference from "
            "two abstracts."
        ),
        corpus_dir="",
        manifest_path="",
        author_filter=[],
        requires_build=True,
        build_cmd="python -m validation.wide.run --dataset autextification",
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

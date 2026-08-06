"""Contract checks for the deploy-safe prototype feature registry."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from original.constants import (
    ALL_FEATURE_CODES,
    FEATURE_DIM,
    FEATURE_NAMES,
    FEATURE_TIER,
)
from original.explainer import FEATURE_PLAIN_NAMES

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE_DIR = ROOT / "demo" / "prototypes"
GENERATED = PROTOTYPE_DIR / "feature-registry.generated.js"
GENERATOR = PROTOTYPE_DIR / "generate-feature-registry.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("prototype_feature_registry_generator", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _generated_rows() -> list[list[object]]:
    source = GENERATED.read_text(encoding="utf-8")
    match = re.search(
        r"const FEATURE_ROWS = Object\.freeze\((\[.*?\])\);\n\nexport const LOCALIZATION_KINDS",
        source,
        flags=re.DOTALL,
    )
    assert match, "generated registry must expose a JSON-compatible FEATURE_ROWS payload"
    return json.loads(match.group(1))


def test_generated_registry_is_current() -> None:
    generator = _load_generator()
    assert GENERATED.read_text(encoding="utf-8") == generator.render_registry()


def test_generated_registry_matches_backend_contract() -> None:
    rows = _generated_rows()
    assert len(rows) == FEATURE_DIM
    assert [row[0] for row in rows] == list(ALL_FEATURE_CODES)

    for code, name, plain, tier, localization_kind in rows:
        assert name == FEATURE_NAMES[code]
        assert plain == FEATURE_PLAIN_NAMES[code]
        assert tier == FEATURE_TIER[code]
        assert localization_kind in {
            "token",
            "character",
            "sentence",
            "paragraph",
            "document",
            "behavioral",
        }


def test_localization_policy_is_complete_and_honest_about_resolution() -> None:
    by_code = {row[0]: row[4] for row in _generated_rows()}
    assert set(by_code) == set(ALL_FEATURE_CODES)

    # Representative guardrails prevent the UI from collapsing aggregate,
    # sentence, and live-session evidence into misleading word highlights.
    assert by_code["hedging_density"] == "token"
    assert by_code["semicolon_colon_rate"] == "character"
    assert by_code["clause_depth_mean"] == "sentence"
    assert by_code["thematic_progression_score"] == "paragraph"
    assert by_code["type_token_ratio"] == "document"
    assert by_code["char_trigram_profile_divergence"] == "document"
    assert all(
        by_code[code] == "behavioral" for code in ALL_FEATURE_CODES if FEATURE_TIER[code] == 17
    )


def test_feature_universe_has_no_untracked_app_dependency() -> None:
    source = (PROTOTYPE_DIR / "feature-universe-data.js").read_text(encoding="utf-8")
    assert "../app/" not in source
    assert "./feature-registry.generated.js" in source

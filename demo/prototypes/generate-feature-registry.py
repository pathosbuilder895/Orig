#!/usr/bin/env python3
"""Generate the prototype's deploy-safe feature registry.

Canonical code order, tier membership, and technical labels come from
``original.constants``. Professor-facing descriptions come from
``original.explainer``. Evidence localization is a presentation policy kept
here because the backend currently exposes scalar feature values rather than
text-offset evidence.

Run from the repository root:

    .venv/bin/python demo/prototypes/generate-feature-registry.py

Use ``--check`` in CI to fail when the generated JavaScript has drifted.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from importlib import import_module
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
OUTPUT: Final = Path(__file__).with_name("feature-registry.generated.js")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_constants = import_module("original.constants")
ALL_FEATURE_CODES = _constants.ALL_FEATURE_CODES
FEATURE_NAMES = _constants.FEATURE_NAMES
FEATURE_TIER = _constants.FEATURE_TIER


TIER_META: Final = {
    0: "Comparison",
    1: "Surface Stylometrics",
    2: "Discourse Analysis",
    3: "Rhetorical Register",
    4: "Char & Punctuation",
    5: "POS & Syntax",
    6: "Idiosyncratic Patterns",
    7: "Voice Authenticity",
    8: "Prosodic Rhythm",
    9: "Cognitive Sequencing",
    10: "Semantic Gravity",
    11: "Error Ecology",
    12: "Tension Arc",
    13: "Prosodic Depth",
    14: "Error Topology",
    15: "Lexical Architecture",
    16: "Citation Fingerprint",
    17: "Behavioral Biometrics",
}

# Localization describes the smallest honest evidence unit the interface may
# select. It is deliberately not inferred from tier alone: a density can have
# exact word occurrences, while a profile divergence is document-level.
LOCALIZATION_GROUPS: Final = {
    "character": {
        "char_trigram_entropy",
        "punctuation_diversity",
        "comma_rate",
        "semicolon_colon_rate",
        "parenthetical_rate",
        "dash_rate",
        "quote_rate",
        "punctuation_error_ratio",
    },
    "token": {
        "hapax_legomena_rate",
        "function_word_ratio",
        "modal_verb_ratio",
        "stop_word_ratio",
        "discourse_marker_density",
        "additive_ratio",
        "adversative_ratio",
        "causal_ratio",
        "temporal_ratio",
        "pronoun_reference_density",
        "lexical_chain_density",
        "cohesion_device_ratio",
        "transition_density",
        "epistemic_certainty_ratio",
        "hedging_density",
        "first_person_ratio",
        "theological_register_score",
        "noun_verb_ratio",
        "adjective_rate",
        "adverb_rate",
        "contraction_rate",
        "that_which_ratio",
        "list_marker_preference",
        "abbreviation_tendency",
        "filler_hedge_cluster_rate",
        "polysyndeton_ratio",
        "latinate_ratio",
        "nominalization_density",
        "signal_verb_entropy",
        "signal_verb_assertiveness",
        "ibid_usage_rate",
    },
    "sentence": {
        "mean_sentence_length",
        "sentence_length_variance",
        "passive_voice_ratio",
        "sentence_opener_variety",
        "assertion_density",
        "source_integration_style",
        "counter_argument_ratio",
        "claim_density",
        "question_ratio",
        "imperative_density",
        "appeal_to_authority_density",
        "pos_bigram_entropy",
        "pos_trigram_entropy",
        "subordination_ratio",
        "clause_depth_mean",
        "sentence_initial_conjunction_rate",
        "stress_entropy_unigram",
        "stress_entropy_bigram",
        "clausulae_consistency",
        "breath_group_variance",
        "clausula_type_consistency",
        "breath_group_regularity",
        "vowel_sonority_ratio",
        "clausula_shape_preference",
        "error_topology_consistency",
        "article_omission_rate",
        "pronoun_ambiguity_rate",
        "comma_splice_rate",
        "chiasmus_rate",
        "citation_position_pref",
        "paraphrase_density",
    },
    "paragraph": {
        "thematic_progression_score",
        "paragraph_topic_position",
        "avg_paragraph_length",
        "conclusion_strategy_score",
        "transition_predictability",
        "vocabulary_introduction_rate",
        "structural_centrist_penalty",
        "argument_sequence_likelihood",
        "catastrophe_index",
        "arc_resolution_score",
        "metric_flatness_score",
        "block_quote_rate",
        "citation_density_cv",
    },
    "document": {
        "type_token_ratio",
        "avg_word_length",
        "citation_style_consistency",
        "burstiness",
        "perplexity_proxy",
        "repetition_gap_entropy",
        "semantic_field_dispersion",
        "semantic_centroid_proximity",
        "error_kl_divergence",
        "stumble_rate_consistency",
        "semantic_field_concentration",
        "source_loyalty_index",
        "char_trigram_profile_divergence",
        "function_word_profile_divergence",
    },
    "behavioral": {
        "typing_speed_cv",
        "burst_ratio",
        "deletion_rate",
        "pause_density",
        "paste_event_rate",
        "revision_depth",
    },
}


def _literal_dict(path: Path, name: str) -> dict[str, str]:
    """Read a literal module assignment without importing its heavy graph."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id == name and node.value is not None:
            value = ast.literal_eval(node.value)
            if not isinstance(value, dict):
                break
            return value
    raise RuntimeError(f"Could not read {name} from {path}")


def localization_by_code() -> dict[str, str]:
    """Return a complete one-to-one localization policy for all features."""

    result: dict[str, str] = {}
    duplicates: list[str] = []
    for kind, codes in LOCALIZATION_GROUPS.items():
        for code in codes:
            if code in result:
                duplicates.append(code)
            result[code] = kind

    canonical = set(ALL_FEATURE_CODES)
    missing = canonical - result.keys()
    extra = result.keys() - canonical
    if duplicates or missing or extra:
        raise RuntimeError(
            "Invalid localization policy: "
            f"duplicates={sorted(duplicates)}, missing={sorted(missing)}, "
            f"extra={sorted(extra)}"
        )
    return result


def feature_rows() -> list[list[object]]:
    plain_names = _literal_dict(ROOT / "original" / "explainer.py", "FEATURE_PLAIN_NAMES")
    localization = localization_by_code()

    missing_names = set(ALL_FEATURE_CODES) - FEATURE_NAMES.keys()
    missing_plain = set(ALL_FEATURE_CODES) - plain_names.keys()
    if missing_names or missing_plain:
        raise RuntimeError(
            f"Incomplete canonical metadata: names={sorted(missing_names)}, "
            f"plain={sorted(missing_plain)}"
        )

    return [
        [
            code,
            FEATURE_NAMES[code],
            plain_names[code],
            FEATURE_TIER[code],
            localization[code],
        ]
        for code in ALL_FEATURE_CODES
    ]


def render_registry() -> str:
    rows = json.dumps(feature_rows(), ensure_ascii=False, indent=2)
    tiers = json.dumps(
        {str(key): value for key, value in TIER_META.items()}, ensure_ascii=False, indent=2
    )
    return f"""// GENERATED FILE — DO NOT EDIT.
// Sources: original/constants.py + original/explainer.py
// Regenerate: .venv/bin/python demo/prototypes/generate-feature-registry.py

const FEATURE_ROWS = Object.freeze({rows});

export const LOCALIZATION_KINDS = Object.freeze({{
  character: Object.freeze({{
    label: 'Exact character marks',
    guidance: 'Highlight only the exact character or short character sequence '
      + 'returned by trusted evidence offsets.',
    supportsInlineHighlight: true
  }}),
  token: Object.freeze({{
    label: 'Exact words or phrases',
    guidance: 'Highlight exact word or phrase occurrences; explain that the paper-level '
      + 'value aggregates those occurrences.',
    supportsInlineHighlight: true
  }}),
  sentence: Object.freeze({{
    label: 'Sentence-level evidence',
    guidance: 'Highlight the complete sentence needed to interpret the grammatical, '
      + 'rhetorical, or rhythmic pattern.',
    supportsInlineHighlight: true
  }}),
  paragraph: Object.freeze({{
    label: 'Paragraph-level evidence',
    guidance: 'Highlight a complete paragraph or adjacent paragraph sequence; do not '
      + 'reduce the pattern to a single word.',
    supportsInlineHighlight: true
  }}),
  document: Object.freeze({{
    label: 'Whole-document measure',
    guidance: 'Present a document-level summary or distribution. Do not manufacture an '
      + 'inline highlight for this aggregate signal.',
    supportsInlineHighlight: false
  }}),
  behavioral: Object.freeze({{
    label: 'Live drafting behavior',
    guidance: 'Present a timeline or event range from captured drafting telemetry; this '
      + 'signal is not derivable from uploaded prose.',
    supportsInlineHighlight: false
  }})
}});

export const CODES = Object.freeze(FEATURE_ROWS.map(([code]) => code));

export const FEATURES = Object.freeze(Object.fromEntries(FEATURE_ROWS.map(
  ([code, name, plain, tier, localizationKind]) => {{
    const localization = LOCALIZATION_KINDS[localizationKind];
    return [code, Object.freeze({{
      name,
      plain,
      tier,
      localizationKind,
      localizationLabel: localization.label,
      localizationGuidance: localization.guidance,
      supportsInlineHighlight: localization.supportsInlineHighlight
    }})];
  }}
)));

export const TIER_META = Object.freeze({tiers});

export const FEATURE_REGISTRY_SOURCE = Object.freeze({{
  schemaVersion: 1,
  totalCount: FEATURE_ROWS.length,
  canonicalSources: Object.freeze(['original/constants.py', 'original/explainer.py']),
  generatedBy: 'demo/prototypes/generate-feature-registry.py'
}});
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of writing when the generated registry is stale",
    )
    args = parser.parse_args()
    expected = render_registry()

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != expected:
            print(f"{OUTPUT.relative_to(ROOT)} is stale; regenerate it", file=sys.stderr)
            return 1
        print(f"{OUTPUT.relative_to(ROOT)} is current")
        return 0

    OUTPUT.write_text(expected, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

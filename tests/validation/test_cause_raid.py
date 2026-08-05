import csv
import io

import numpy as np

from validation.cause.padben import (
    CAUSES,
    PadBenBundle,
    fit_ai_subtype_discriminator,
    fit_calibrated_cause_model,
)
from validation.cause.raid import (
    DIRECT_AI,
    HUMAN,
    HUMANIZED_AI,
    _rows_from_chunks,
    _matched_attack_rows,
    assess_attack_family_promotion,
    cause_for,
    evaluate_cross_attack_family_subtype,
    evaluate_ai_origin_invariance,
    evaluate_external_ai_origin,
    evaluate_cross_generator_subtype,
    padben_depth_rows,
    _select_binary_subtype,
)


def test_raid_cause_labels_keep_human_paraphrases_human() -> None:
    assert cause_for({"model": "human", "attack": "paraphrase"}) == HUMAN
    assert cause_for({"model": "gpt4", "attack": "none"}) == DIRECT_AI
    assert cause_for({"model": "gpt4", "attack": "paraphrase"}) == HUMANIZED_AI


def test_matched_attack_selection_requires_same_original_generation() -> None:
    rows = []
    for root in ("a", "b"):
        rows.append(
            {"id": root, "adv_source_id": root, "model": "gpt4", "attack": "none", "generation": "x " * 20}
        )
        for attack in ("synonym", "paraphrase"):
            rows.append(
                {"id": f"{root}-{attack}", "adv_source_id": root, "model": "gpt4", "attack": attack, "generation": "y " * 20}
            )
    # An unmatched attack must not enter the output.
    rows.append(
        {"id": "orphan", "adv_source_id": "missing", "model": "gpt4", "attack": "paraphrase", "generation": "z " * 20}
    )
    selected = _matched_attack_rows(
        rows,
        models=["gpt4"],
        attacks=["synonym", "paraphrase"],
        rows_per_model=2,
        min_words=10,
    )
    assert len(selected) == 6
    for index in range(0, len(selected), 3):
        clean, synonym, paraphrase = selected[index : index + 3]
        assert synonym["adv_source_id"] == clean["id"] == paraphrase["adv_source_id"]


def test_overlapping_subtype_thresholds_abstain() -> None:
    predicted = _select_binary_subtype(
        np.asarray([0.2, 0.6, 0.9]),
        direct_threshold=0.7,
        humanized_threshold=0.5,
    )
    assert predicted.tolist() == [DIRECT_AI, "unknown_other", HUMANIZED_AI]


def test_range_parser_preserves_complete_multiline_records() -> None:
    fields = [
        "id",
        "adv_source_id",
        "source_id",
        "model",
        "decoding",
        "repetition_penalty",
        "attack",
        "domain",
        "title",
        "prompt",
        "generation",
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for suffix in ("1", "2", "3"):
        writer.writerow(
            {
                "id": f"00000000-0000-0000-0000-00000000000{suffix}",
                "adv_source_id": f"10000000-0000-0000-0000-00000000000{suffix}",
                "source_id": f"20000000-0000-0000-0000-00000000000{suffix}",
                "model": "gpt4",
                "attack": "paraphrase",
                "domain": "books",
                "generation": f"first line {suffix}\nsecond line {suffix}",
            }
        )
    raw = stream.getvalue().encode()
    header, body = raw.split(b"\r\n", 1)
    rows = _rows_from_chunks(header, [b"partial\n" + body + b"partial tail"])
    assert [row["generation"] for row in rows] == [
        "first line 1\nsecond line 1",
        "first line 2\nsecond line 2",
    ]


def test_calibrated_model_uses_source_held_predictions() -> None:
    rng = np.random.default_rng(1729)
    labels = np.asarray(list(CAUSES) * 18, dtype=object)
    sources = np.repeat(["a", "b", "c"], 18)
    centers = {cause: index * 4.0 for index, cause in enumerate(CAUSES)}
    X = np.asarray([[centers[label] + rng.normal(scale=0.2)] for label in labels])
    model, thresholds = fit_calibrated_cause_model(X, labels, sources)
    assert set(model.named_steps["logistic"].classes_) == set(CAUSES)
    assert set(thresholds) == set(CAUSES)
    assert all(0.6 <= value <= 1.01 for value in thresholds.values())
    subtype = fit_ai_subtype_discriminator(X, labels)
    assert list(subtype.named_steps["logistic"].classes_) == [False, True]


def test_cross_generator_subtype_removes_shared_source_prompts() -> None:
    rows = []
    X = []
    for generator_index, generator in enumerate(("a", "b")):
        for humanized in (False, True):
            for index in range(8):
                source = "shared" if index == 0 else f"{generator}:{humanized}:{index}"
                rows.append(
                    {
                        "model": generator,
                        "attack": "paraphrase" if humanized else "none",
                        "source_id": source,
                    }
                )
                X.append([float(humanized) * 4.0 + generator_index * 0.1])
    result = evaluate_cross_generator_subtype(np.asarray(X), rows)
    assert result["n_locked"] == 28
    assert result["pooled_auc"] == 1.0
    assert all(fold["excluded_shared_source_prompts"] == 2 for fold in result["folds"].values())


def _attack_family_fixture() -> tuple[np.ndarray, list[dict]]:
    rows = []
    X = []
    for generator_index, generator in enumerate(("a", "b", "c")):
        for attack_index, attack in enumerate(("none", "paraphrase", "synonym")):
            for index in range(30):
                rows.append(
                    {
                        "model": generator,
                        "attack": attack,
                        "source_id": f"{generator}:{attack}:{index}",
                    }
                )
                X.append(
                    [
                        (0.0 if attack == "none" else 5.0)
                        + generator_index * 0.05
                        + attack_index * 0.01
                    ]
                )
    return np.asarray(X), rows


def test_cross_attack_family_is_source_disjoint_and_selective() -> None:
    X, rows = _attack_family_fixture()
    result = evaluate_cross_attack_family_subtype(X, rows)
    assert result["attack_families"] == ["paraphrase", "synonym"]
    assert all(fold["source_overlap"] == 0 for fold in result["folds"].values())
    assert all(fold["auc"] == 1.0 for fold in result["folds"].values())
    assert result["promotion_gate"]["passed"]


def test_cross_attack_family_requires_two_families() -> None:
    X, rows = _attack_family_fixture()
    keep = np.asarray([row["attack"] != "synonym" for row in rows])
    try:
        evaluate_cross_attack_family_subtype(X[keep], [row for row, use in zip(rows, keep) if use])
    except ValueError as exc:
        assert "at least two" in str(exc)
    else:
        raise AssertionError("single-family input must be rejected")


def test_ai_origin_invariance_holds_out_generator_attack_and_sources() -> None:
    rows = []
    X = []
    for model in ("human", "generator-a", "generator-b"):
        for index in range(200):
            root = f"{model}:{index}"
            for attack in ("none", "paraphrase", "synonym"):
                rows.append(
                    {
                        "id": root if attack == "none" else f"{root}:{attack}",
                        "adv_source_id": root,
                        "source_id": root,
                        "model": model,
                        "attack": attack,
                    }
                )
                # Rewriting does not erase the synthetic AI-origin signal, and
                # rewritten human controls remain negative.
                X.append([3.0 if model != "human" else -3.0, index / 1000])
    result = evaluate_ai_origin_invariance(np.asarray(X), rows)
    assert len(result["folds"]) == 4
    assert all(fold["source_overlap"] == 0 for fold in result["folds"].values())
    assert all(fold["human_fpr"] == 0.0 for fold in result["folds"].values())
    assert all(fold["held_attack_ai_tpr"] == 1.0 for fold in result["folds"].values())
    assert result["promotion_gate"]["passed"]


def test_external_ai_origin_uses_raid_calibration_only() -> None:
    rows = []
    X_train = []
    for model in ("human", "generator-a", "generator-b"):
        for index in range(100):
            root = f"{model}:{index}"
            for attack in ("none", "paraphrase", "synonym"):
                rows.append(
                    {
                        "id": root if attack == "none" else f"{root}:{attack}",
                        "adv_source_id": root,
                        "model": model,
                        "attack": attack,
                    }
                )
                X_train.append([4.0 if model != "human" else -4.0])
    bundles = []
    X_external = []
    for cause, value in ((HUMAN, -4.0), (DIRECT_AI, 4.0), (HUMANIZED_AI, 4.0)):
        for index in range(40):
            bundles.append(PadBenBundle(str(index), "external", cause, cause, (index,), "text"))
            X_external.append([value])
    result = evaluate_external_ai_origin(
        np.asarray(X_train), rows, np.asarray(X_external), bundles
    )
    assert result["development_external_source_overlap"] == 0
    assert result["human_fpr"] == 0.0
    assert result["direct_ai_tpr"] == 1.0
    assert result["humanized_ai_tpr"] == 1.0
    assert result["passed"]
def test_promotion_gate_fails_missing_selective_predictions() -> None:
    result = {
        "folds": {
            "synonym": {
                "auc": 0.95,
                "selective_metrics": {
                    "coverage": 0.0,
                    "per_class": {
                        DIRECT_AI: {"precision": None, "recall": 0.0, "support": 25},
                        HUMANIZED_AI: {"precision": None, "recall": 0.0, "support": 25},
                    },
                },
            }
        }
    }
    gate = assess_attack_family_promotion(result)
    assert not gate["passed"]
    assert any("coverage" in failure for failure in gate["failures"])


def test_padben_depth_mapping_preserves_paired_source_group() -> None:
    class Bundle:
        def __init__(self, cause, variant):
            self.cause = cause
            self.variant = variant
            self.source = "paws"
            self.row_ids = (1, 2, 3)

    bundles = [
        Bundle(DIRECT_AI, "type2"),
        Bundle(HUMANIZED_AI, "llm_paraphrased_generated_text(type5)-1st"),
        Bundle(HUMANIZED_AI, "llm_paraphrased_generated_text(type5)-3rd"),
        Bundle(HUMAN, "human_original"),
    ]
    rows, indices = padben_depth_rows(bundles)
    assert indices.tolist() == [0, 1, 2]
    assert [row["attack"] for row in rows] == [
        "none",
        "paraphrase_1st",
        "paraphrase_3rd",
    ]
    assert len({row["source_id"] for row in rows}) == 1

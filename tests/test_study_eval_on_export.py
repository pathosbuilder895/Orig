"""The study export against the study CSV contract.

The export (``original.study_export``, Codex's PR #274) and the analysis
(``validation/study_eval.py``, built against ``validation/study_contract.py``)
are written in parallel. These tests are where they meet:

  - the contract's header is pinned to a literal string here, so changing a
    column name means changing this file on purpose, in the same PR;
  - a CSV built by ``original.study_export.export_csv`` must load under the
    contract and run through the evaluation. On a checkout without the export
    module those tests skip, saying why; once both PRs are in, they run.

The rows fed to the export are invented (no real student). They carry the
v2 field names and also #274's first names for the same values, so either
row shape reaches the export, and a seal-time ``status`` that disagrees with
the verdict, so an export that reads the wrong one is caught.
"""

from __future__ import annotations

import csv
import importlib
import importlib.util
import inspect
import io

import pytest

from validation import study_eval
from validation.study_contract import (
    CONTRACT_VERSION,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    StudyContractError,
    parse_study_csv,
)

# The shared contract, as a string. Edit it only together with the contract.
PINNED_VERSION = "study-csv-v2"
PINNED_REQUIRED = (
    "submission_id,student_id,study_label,verdict,deviation_score,baseline_count,word_count"
)
PINNED_OPTIONAL = (
    "imitated_student_id,claimed_student_id,authorship_probability,exam_id,"
    "llr_deviation_score,scored_at,engine_version,threshold_version"
)

EXPORT_MODULE = "original.study_export"
SALT = "test-only-study-salt-0123456789"  # not a secret: 16+ bytes, used nowhere else


class TestPinnedHeader:
    def test_contract_version_is_pinned(self):
        assert CONTRACT_VERSION == PINNED_VERSION

    def test_required_columns_are_pinned(self):
        assert ",".join(REQUIRED_COLUMNS) == PINNED_REQUIRED

    def test_optional_columns_are_pinned(self):
        assert ",".join(OPTIONAL_COLUMNS) == PINNED_OPTIONAL

    def test_the_pinned_header_alone_is_a_valid_study_csv(self):
        csv_text = "\n".join(
            [
                PINNED_REQUIRED + ",imitated_student_id",
                "a,s1,natural,SUBMITTED,0.21,5,400,",
                "b,s2,shadow,FLAGGED,0.64,5,400,s1",
            ]
        )
        data = parse_study_csv(csv_text.encode())
        by_id = {r.submission_id: r for r in data.rows}
        assert by_id["b"].student_id == "s2" and by_id["b"].claimed_student_id == "s1"


# ── the export, when this checkout has it ─────────────────────────────────────


def _export_module():
    if importlib.util.find_spec(EXPORT_MODULE) is None:
        pytest.skip(
            f"{EXPORT_MODULE} is not on this checkout: the study export lands with Codex's "
            "PR #274 (codex/study-labels-export). The pinned-header tests above still run; "
            "these run once both PRs are merged."
        )
    # Present: import it for real, so a broken module fails instead of skipping.
    return importlib.import_module(EXPORT_MODULE)


# (submission, writer, label, imitated, deviation, verdict, baseline, words, prob)
_ROWS = [
    ("sub-1", "t1:stu-a", "natural", None, 0.21, "SUBMITTED", 5, 420, 0.84),
    ("sub-2", "t1:stu-b", "natural", None, 0.18, "SUBMITTED", 6, 515, 0.86),
    ("sub-3", "t1:stu-c", "natural", None, 0.43, "FLAGGED", 4, 380, 0.62),
    ("sub-4", "t1:stu-d", "natural", None, 0.25, "SUBMITTED", 7, 610, 0.80),
    ("sub-5", "t1:stu-a", "shadow", "t1:stu-b", 0.58, "FLAGGED", 6, 450, 0.47),
    ("sub-6", "t1:stu-b", "shadow", "t1:stu-c", 0.39, "SUBMITTED", 4, 390, 0.71),
    ("sub-7", "t1:stu-c", "shadow", "t1:stu-d", 0.66, "FLAGGED", 7, 505, 0.41),
    ("sub-8", "t1:stu-d", "shadow", "t1:stu-a", 0.52, "FLAGGED", 5, 470, 0.55),
]


def _submission(sub, writer, label, imitated, deviation, verdict, baseline, words, prob) -> dict:
    features = {"type_token_ratio": 0.5 + deviation / 10, "mean_sentence_length": 18.0 + deviation}
    return {
        "id": sub,
        "submission_id": sub,
        "exam_id": "exam-study-n" if label == "natural" else "exam-study-s",
        "student_id": writer,
        "study_label": label,
        "imitated_student_id": imitated,
        "word_count": words,
        # study-csv-v2 names
        "deviation_score": deviation,
        "verdict": verdict,
        "baseline_count": baseline,
        "authorship_probability": prob,
        "features": features,
        "engine_version": "original-layer7-style-v1",
        "threshold_version": "thresholds-sha256:test",
        # PR #274's first names for the same values
        "style_score": deviation,
        "style_features": features,
        "style_engine_version": "original-layer7-style-v1",
        "style_threshold_version": "thresholds-sha256:test",
        # The seal-time status, against the WRITER's baseline: never the verdict.
        "status": "SUBMITTED",
    }


def _export(module, rows: list[dict]) -> str:
    fn = module.export_csv
    params = inspect.signature(fn).parameters
    supplied = {"salt": SALT, "study_id": "study-test"}
    kwargs = {k: v for k, v in supplied.items() if k in params}
    first = next(iter(params))
    missing = [
        n
        for n, p in params.items()
        if n != first
        and n not in kwargs
        and p.default is inspect.Parameter.empty
        and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
    ]
    if missing:
        pytest.fail(
            f"export_csv now requires {missing}; teach this test to supply them "
            "(it pins the export to the study contract)"
        )
    out = fn(rows, **kwargs)
    return out.decode("utf-8") if isinstance(out, bytes) else out


class TestExportMeetsTheContract:
    @pytest.fixture(scope="class")
    def exported(self) -> str:
        return _export(_export_module(), [_submission(*r) for r in _ROWS])

    def test_export_columns_cover_the_contract(self):
        cols = getattr(_export_module(), "EXPORT_COLUMNS", None)
        if cols is None:
            pytest.skip("the export module does not publish EXPORT_COLUMNS")
        missing = [c for c in REQUIRED_COLUMNS if c not in cols]
        assert not missing, f"EXPORT_COLUMNS lacks {CONTRACT_VERSION} column(s) {missing}"

    def test_exported_header_has_every_required_column(self, exported):
        header = next(csv.reader(io.StringIO(exported)))
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        assert not missing, (
            f"the export's header lacks {CONTRACT_VERSION} column(s) {missing}; "
            f"header was {header}"
        )
        assert any(c.startswith("f_") for c in header), "the export carries no f_<feature> columns"

    def test_exported_csv_loads_under_the_contract(self, exported):
        try:
            data = parse_study_csv(exported.encode(), source_name="export.csv")
        except StudyContractError as e:
            pytest.fail(f"the export does not meet {CONTRACT_VERSION}:\n" + "\n".join(e.problems))
        assert len(data.rows) == len(_ROWS) and data.unlabelled == 0
        assert {"type_token_ratio", "mean_sentence_length"} <= set(data.feature_codes)

        want = {r[0]: r for r in _ROWS}
        for row in data.rows:
            sub, _writer, label, imitated, deviation, verdict, baseline, words, _p = want[
                row.submission_id
            ]
            assert row.label == label, sub
            assert row.verdict == verdict, f"{sub}: verdict is not the exported verdict"
            assert row.deviation_score == pytest.approx(deviation), sub
            assert (row.baseline_count, row.word_count) == (baseline, words), sub
            if label == "shadow":
                # Pseudonymised or not, the writer is never the claimed student.
                assert row.imitated_student_id and row.student_id != row.claimed_student_id, sub

    def test_pseudonyms_are_consistent_across_writer_and_imitated(self, exported):
        # A shadow row's claimed student is a writer elsewhere in the export:
        # the same student must carry the same id in both columns.
        data = parse_study_csv(exported.encode())
        writers = {r.student_id for r in data.rows}
        assert {r.claimed_student_id for r in data.rows} <= writers
        assert not any("never appears as a writer" in w for w in data.warnings)

    def test_study_eval_accepts_the_export(self, exported, tmp_path):
        path = tmp_path / "export.csv"
        path.write_text(exported)
        report = study_eval.run(
            path, tmp_path / "out", charts=False, n_bootstrap=50, n_permutations=50
        )
        assert report["contract"]["version"] == CONTRACT_VERSION
        assert report["counts"]["attempts"] == len(_ROWS)
        assert report["counts"]["conclusive_natural"] == report["counts"]["conclusive_shadow"] == 4
        assert report["auc"]["value"] is not None
        assert (tmp_path / "out" / "study_eval.md").exists()

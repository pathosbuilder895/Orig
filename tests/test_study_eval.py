"""validation/study_eval.py and the study CSV contract, end to end.

The fixture (tests/fixtures/study_synthetic.csv) is FICTIONAL: invented rows
for 20 synthetic students, built by tests/fixtures/make_study_synthetic.py.
Numbers asserted here are properties of that fixture, never of Original.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
from pathlib import Path

import numpy as np
import pytest

from validation import study_eval
from validation.study_contract import (
    StudyContractError,
    load_study_csv,
    parse_study_csv,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CSV = FIXTURES / "study_synthetic.csv"

HEADER = (
    "submission_id,writer_student_id,study_label,imitated_student_id,status,"
    "consistency_score,baseline_size,word_count"
)


def _csv(*lines: str, header: str = HEADER) -> bytes:
    return ("\n".join((header,) + lines) + "\n").encode()


def _run(tmp_path: Path, name: str, csv_path: Path = CSV, **kw) -> tuple[dict, Path]:
    out = tmp_path / name
    report = study_eval.run(csv_path, out, **kw)
    return report, out


# ── the contract ──────────────────────────────────────────────────────────────


class TestContract:
    def test_fixture_meets_the_contract(self):
        data = load_study_csv(CSV)
        assert len(data.rows) == 80
        assert {r.label for r in data.rows} == {"natural", "shadow"}
        assert [r.submission_id for r in data.rows] == sorted(r.submission_id for r in data.rows)

    def test_fixture_is_reproducible_from_its_generator(self):
        spec = importlib.util.spec_from_file_location(
            "make_study_synthetic", FIXTURES / "make_study_synthetic.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.build() == CSV.read_text()

    def test_claimed_student_is_the_imitated_one_on_a_shadow_row(self):
        data = parse_study_csv(
            _csv("a,s1,shadow,s2,SUBMITTED,80,5,400", "b,s2,natural,,SUBMITTED,90,5,400")
        )
        by_id = {r.submission_id: r for r in data.rows}
        assert by_id["a"].claimed_student_id == "s2"
        assert by_id["b"].claimed_student_id == "s2"

    def test_every_problem_is_reported_at_once(self):
        with pytest.raises(StudyContractError) as exc:
            parse_study_csv(
                _csv(
                    "a,s1,shadow,,SUBMITTED,80,5,400",  # shadow without imitated
                    "a,s1,natural,s2,SUBMITTED,80,5,400",  # duplicate id; natural naming imitated
                    "c,s1,shadow,s1,SUBMITTED,80,5,400",  # imitates itself
                    "d,s1,maybe,,SUBMITTED,80,5,400",  # bad label
                    "e,s1,natural,,PASSED,180,5,-3",  # bad status, score, word count
                )
            )
        text = "\n".join(exc.value.problems)
        for needle in (
            "without imitated_student_id",
            "duplicate submission_id",
            "natural row names an imitated_student_id",
            "imitates its own writer",
            "study_label must be",
            "status must be",
            "outside 0-100",
            "word_count",
        ):
            assert needle in text, needle

    def test_missing_required_column_is_named(self):
        with pytest.raises(StudyContractError, match="baseline_size"):
            parse_study_csv(
                b"submission_id,writer_student_id,study_label,status,consistency_score,word_count\n"
            )

    def test_claimed_student_must_follow_the_rule_when_present(self):
        header = HEADER + ",claimed_student_id"
        with pytest.raises(StudyContractError, match="should be the imitated student"):
            parse_study_csv(_csv("a,s1,shadow,s2,SUBMITTED,80,5,400,s1", header=header))

    def test_unambiguous_aliases_are_applied_and_reported(self):
        header = "submission_id,writer_student_id,label,imitated_student_id,status,ai_score,baseline_size,words"
        data = parse_study_csv(_csv("a,s1,natural,,SUBMITTED,80,5,400", header=header))
        assert data.aliases_applied == {
            "ai_score": "consistency_score",
            "label": "study_label",
            "words": "word_count",
        }
        assert data.rows[0].score == 80

    def test_student_id_is_not_guessed(self):
        header = (
            "submission_id,student_id,study_label,status,consistency_score,baseline_size,word_count"
        )
        with pytest.raises(StudyContractError, match="writer_student_id"):
            parse_study_csv(_csv("a,s1,natural,SUBMITTED,80,5,400", header=header))

    def test_inconclusive_and_unscored_are_kept_apart(self):
        data = parse_study_csv(
            _csv(
                "a,s1,natural,,INCONCLUSIVE,,2,400",
                "b,s1,natural,,SUBMITTED,,5,400",
                "c,s1,natural,,INCONCLUSIVE,55,2,400",
            )
        )
        by_id = {r.submission_id: r for r in data.rows}
        assert by_id["a"].inconclusive and not by_id["a"].unscored
        assert by_id["b"].unscored and not by_id["b"].conclusive
        assert by_id["c"].score is None  # an INCONCLUSIVE row's score is ignored ...
        assert any("INCONCLUSIVE row carries a score" in w for w in data.warnings)  # ... loudly

    def test_two_columns_for_one_field_are_refused(self):
        header = "submission_id,writer_student_id,study_label,status,ai_score,aiScore,baseline_size,word_count"
        with pytest.raises(StudyContractError, match="both map to 'consistency_score'"):
            parse_study_csv(_csv("a,s1,natural,SUBMITTED,90,10,5,400", header=header))

    def test_status_that_follows_the_wrong_baseline_is_flagged(self):
        data = parse_study_csv(
            _csv(
                "a,s1,shadow,s2,INCONCLUSIVE,,6,400",  # target ready, yet inconclusive
                "b,s2,shadow,s1,SUBMITTED,80,2,400",  # target thin, yet scored
                "c,s1,natural,,SUBMITTED,80,5,400",
                "d,s2,natural,,SUBMITTED,80,5,400",
            )
        )
        joined = " ".join(data.warnings)
        assert "line 2: INCONCLUSIVE with 6 approved samples" in joined
        assert "line 3: scored with only 2 approved samples" in joined

    def test_an_imitated_student_who_never_wrote_is_warned_about(self):
        data = parse_study_csv(
            _csv("a,s1,shadow,s9,SUBMITTED,80,5,400", "b,s1,natural,,SUBMITTED,80,5,400")
        )
        assert any("'s9' never appears as a writer" in w for w in data.warnings)

    def test_unknown_feature_columns_are_ignored_with_a_warning(self):
        header = HEADER + ",f_type_token_ratio,f_not_a_feature"
        data = parse_study_csv(_csv("a,s1,natural,,SUBMITTED,80,5,400,0.5,1", header=header))
        assert data.feature_codes == ("type_token_ratio",)
        assert any("not_a_feature" in w for w in data.warnings)


# ── the evaluation ────────────────────────────────────────────────────────────


class TestEvaluation:
    @pytest.fixture(scope="class")
    def report(self, tmp_path_factory):
        return study_eval.run(CSV, tmp_path_factory.mktemp("eval") / "out")

    def test_strict_threshold_defaults_to_the_live_rule(self, report):
        assert report["settings"]["strict_threshold"] == 70
        assert report["confusion_at_strict"]["rule"] == "flagged when consistency_score < 70"

    def test_confusion_matrix_accounts_for_every_attempt(self, report):
        m = report["confusion_at_strict"]["matrix"]
        for label, n in (("natural", 40), ("shadow", 40)):
            x = m[label]
            assert (
                x["flagged"] + x["not_flagged"] + x["inconclusive"] + x["unscored"]
                == x["total"]
                == n
            )
        assert m["natural"]["inconclusive"] == 4 and m["shadow"]["inconclusive"] == 4
        assert m["natural"]["unscored"] == 1

    def test_confusion_matches_the_stored_status(self, report):
        # The fixture stores FLAGGED exactly when score < 70, as Exam.jsx does.
        assert report["confusion_at_strict"]["stored_status_disagrees_with_rule"] == 0

    def test_auc_matches_a_brute_force_count(self, report):
        rows = report["rows"]
        nat = [r["score"] for r in rows if r["conclusive"] and r["label"] == "natural"]
        sh = [r["score"] for r in rows if r["conclusive"] and r["label"] == "shadow"]
        wins = sum((s < n) + 0.5 * (s == n) for s in sh for n in nat)
        assert report["auc"]["value"] == pytest.approx(wins / (len(sh) * len(nat)), abs=1e-4)
        lo, hi = report["auc"]["ci95"]
        assert lo <= report["auc"]["value"] <= hi

    def test_sweep_is_monotone_and_ends_at_all_or_nothing(self, report):
        sweep = report["sweep"]
        assert [r["threshold"] for r in sweep] == list(range(0, 102))
        ff = [r["false_flags"]["k"] for r in sweep]
        ca = [r["catches"]["k"] for r in sweep]
        assert ff == sorted(ff) and ca == sorted(ca)
        assert ff[0] == ca[0] == 0
        assert ff[-1] == sweep[-1]["false_flags"]["n"] and ca[-1] == sweep[-1]["catches"]["n"]

    def test_sweep_at_the_strict_threshold_equals_the_confusion_matrix(self, report):
        row = report["sweep"][70]
        cm = report["confusion_at_strict"]
        assert row["false_flags"] == {
            k: v for k, v in cm["false_flag_rate_conclusive"].items() if k != "student_bootstrap95"
        }

    def test_inconclusive_rate_is_reported_per_label(self, report):
        inc = report["inconclusive"]
        # 80 attempts, one unscored: unscored rows are in no denominator.
        assert inc["all"]["inconclusive"]["k"] == 8 and inc["all"]["inconclusive"]["n"] == 79
        assert inc["natural"]["inconclusive"]["n"] == 39 and inc["natural"]["unscored"] == 1
        all_ff = report["confusion_at_strict"]["false_flag_rate_all_attempts"]
        assert all_ff["n"] == 39

    def test_roc_area_is_the_reported_auc(self, report):
        pts = [(0.0, 0.0)] + [(p["false_flag_rate"], p["catch_rate"]) for p in report["roc"]]
        area = sum((x1 - x0) * (y0 + y1) / 2 for (x0, y0), (x1, y1) in zip(pts, pts[1:]))
        assert area == pytest.approx(report["auc"]["value"], abs=2e-3)

    def test_breakdowns_partition_the_attempts(self, report):
        for key in ("by_baseline_size", "by_word_count"):
            bins = report[key]
            assert sum(b["natural_attempts"] for b in bins) == 40, key
            assert sum(b["shadow_attempts"] for b in bins) == 40, key
        thin = report["by_baseline_size"][0]
        assert thin["bin"] == "0-2" and thin["inconclusive"]["rate"] == 1.0

    def test_per_student_gap(self, report):
        ps = report["per_student"]
        students = {s["claimed_student_id"]: s for s in ps["students"]}
        assert len(students) == 20
        assert students["synth-01"]["gap"] is None  # thin baseline: nothing to compare
        both = [s for s in students.values() if s["gap"] is not None]
        assert ps["summary"]["students_with_both_kinds"] == len(both) == 18
        for s in both:
            assert s["gap"] == pytest.approx(s["natural_mean"] - s["shadow_mean"], abs=1e-3)

    def test_feature_importance_respects_measurability(self, report):
        fi = report["feature_importance"]
        tested = [f["feature"] for f in fi["tested"]]
        assert "char_trigram_profile_divergence" not in tested
        assert "catastrophe_index" not in tested
        assert fi["excluded"] == {
            "catastrophe_index": "not measurable (structurally_blank)",
            "char_trigram_profile_divergence": "not measurable (scoring_only)",
        }
        # The two columns the generator shifts on shadow attempts come first.
        assert set(tested[:2]) == {"mean_sentence_length", "hedging_density"}
        assert all(0 < f["perm_p"] <= 1 and 0 < f["bh_q"] <= 1 for f in fi["tested"])

    def test_small_sample_caveat_leads_the_report(self, tmp_path):
        report, out = _run(tmp_path, "caveat", charts=False)
        ss = report["small_sample"]
        assert ss["students"] == 20
        assert ss["false_flag_bar_decidable"] == "undecided"
        assert ss["min_natural_attempts_to_demonstrate_cap"] > ss["conclusive_natural"]
        md = (out / "study_eval.md").read_text()
        assert md.index("Read this first: small sample") < md.index("## Separation")
        assert "not an accuracy figure for Original" in md
        assert "FICTIONAL DATA" in md  # synth-NN writers are detected

    def test_real_looking_ids_get_no_fictional_banner(self, tmp_path):
        src = CSV.read_text().replace("synth-", "stu-")
        path = tmp_path / "renamed.csv"
        path.write_text(src)
        report, out = _run(tmp_path, "renamed", csv_path=path, charts=False)
        assert report["settings"]["fictional"] is False
        assert "FICTIONAL DATA" not in (out / "study_eval.md").read_text()

    def test_experiment_spec_is_embedded(self, report):
        exp = report["experiment"]
        assert exp["task"] == "verification"
        assert exp["corpora"]["study"]["provenance"] == "student_pilot"
        assert exp["created_at"] == "unrecorded (deterministic output)"


# ── determinism ───────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_two_runs_are_byte_identical(self, tmp_path):
        _, a = _run(tmp_path, "a")
        _, b = _run(tmp_path, "b")
        for name in ("study_eval.json", "study_eval.md"):
            assert (a / name).read_bytes() == (b / name).read_bytes(), name
        pngs = sorted(p.name for p in (a / "charts").glob("*.png"))
        assert pngs == [
            "feature_separation.png",
            "per_student_gap.png",
            "roc.png",
            "score_distributions.png",
            "threshold_sweep.png",
        ]
        for name in pngs:
            assert (a / "charts" / name).read_bytes() == (b / "charts" / name).read_bytes(), name

    def test_row_order_does_not_matter(self, tmp_path):
        reader = list(csv.reader(io.StringIO(CSV.read_text())))
        header, body = reader[0], reader[1:]
        rng = np.random.default_rng(7)
        shuffled = [body[i] for i in rng.permutation(len(body))]
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerows([header] + shuffled)
        path = tmp_path / "shuffled.csv"
        path.write_text(buf.getvalue())
        a, _ = _run(tmp_path, "orig", charts=False)
        b, _ = _run(tmp_path, "shuf", csv_path=path, charts=False)
        for key in ("input", "experiment"):  # differ by file name and hash only
            a.pop(key), b.pop(key)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_seed_changes_only_the_resampled_numbers(self, tmp_path):
        a, _ = _run(tmp_path, "s1", charts=False, seed=1)
        b, _ = _run(tmp_path, "s2", charts=False, seed=2)
        assert a["auc"]["value"] == b["auc"]["value"]
        assert a["sweep"] == b["sweep"]
        assert a["auc"]["ci95"] != b["auc"]["ci95"]


class TestCli:
    def test_main_writes_reports(self, tmp_path, capsys):
        out = tmp_path / "cli"
        assert study_eval.main(["--csv", str(CSV), "--out-dir", str(out), "--no-charts"]) == 0
        assert (out / "study_eval.json").exists() and (out / "study_eval.md").exists()
        assert not (out / "charts").exists()
        assert "read the intervals" in capsys.readouterr().out

    def test_a_cap_that_can_never_be_demonstrated_is_refused(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            study_eval.main(["--csv", str(CSV), "--out-dir", str(tmp_path / "c"), "--cap", "0"])
        assert exc.value.code == 2
        with pytest.raises(ValueError, match="cap"):
            study_eval.run(CSV, tmp_path / "c2", cap=0.0, charts=False)

    def test_contract_errors_exit_2(self, tmp_path, capsys):
        bad = tmp_path / "bad.csv"
        bad.write_text("submission_id\n1\n")
        assert study_eval.main(["--csv", str(bad), "--out-dir", str(tmp_path / "x")]) == 2
        assert "missing required column" in capsys.readouterr().err

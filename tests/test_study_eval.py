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
    CONTRACT_VERSION,
    SCORE_COLUMN,
    SCORE_DIRECTION,
    StudyContractError,
    load_study_csv,
    parse_study_csv,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CSV = FIXTURES / "study_synthetic.csv"

HEADER = (
    "submission_id,student_id,study_label,imitated_student_id,verdict,"
    "deviation_score,baseline_count,word_count"
)


def _csv(*lines: str, header: str = HEADER) -> bytes:
    return ("\n".join((header,) + lines) + "\n").encode()


def _run(tmp_path: Path, name: str, csv_path: Path = CSV, **kw) -> tuple[dict, Path]:
    out = tmp_path / name
    report = study_eval.run(csv_path, out, **kw)
    return report, out


# ── the contract ──────────────────────────────────────────────────────────────


class TestContract:
    def test_contract_is_v2_on_deviation_score(self):
        assert CONTRACT_VERSION == "study-csv-v2"
        assert SCORE_COLUMN == "deviation_score"
        assert SCORE_DIRECTION == "higher_is_less_consistent"

    def test_fixture_meets_the_contract(self):
        data = load_study_csv(CSV)
        assert len(data.rows) == 80
        assert {r.label for r in data.rows} == {"natural", "shadow"}
        assert [r.submission_id for r in data.rows] == sorted(r.submission_id for r in data.rows)
        assert data.aliases_applied == {} and data.unlabelled == 0

    def test_fixture_is_reproducible_from_its_generator(self):
        spec = importlib.util.spec_from_file_location(
            "make_study_synthetic", FIXTURES / "make_study_synthetic.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.build() == CSV.read_text()

    def test_student_id_is_the_writer_and_claimed_is_the_imitated_one(self):
        data = parse_study_csv(
            _csv("a,s1,shadow,s2,SUBMITTED,0.6,5,400", "b,s2,natural,,SUBMITTED,0.1,5,400")
        )
        by_id = {r.submission_id: r for r in data.rows}
        assert (by_id["a"].student_id, by_id["a"].claimed_student_id) == ("s1", "s2")
        assert (by_id["b"].student_id, by_id["b"].claimed_student_id) == ("s2", "s2")

    def test_every_problem_is_reported_at_once(self):
        with pytest.raises(StudyContractError) as exc:
            parse_study_csv(
                _csv(
                    "a,s1,shadow,,SUBMITTED,0.2,5,400",  # shadow without imitated
                    "a,s1,natural,s2,SUBMITTED,0.2,5,400",  # duplicate id; natural naming imitated
                    "c,s1,shadow,s1,SUBMITTED,0.2,5,400",  # imitates itself
                    "d,s1,maybe,,SUBMITTED,0.2,5,400",  # bad label
                    "e,s1,natural,,PASSED,1.8,5,-3",  # bad verdict, score, word count
                    "f,,natural,,SUBMITTED,0.2,5,400",  # no writer
                )
            )
        text = "\n".join(exc.value.problems)
        for needle in (
            "without imitated_student_id",
            "duplicate submission_id",
            "natural row names an imitated_student_id",
            "imitates its own writer",
            "study_label must be",
            "verdict must be",
            "deviation_score 1.8 is outside 0-1",
            "word_count",
            "blank student_id (the writer)",
        ):
            assert needle in text, needle

    def test_missing_required_column_is_named(self):
        with pytest.raises(StudyContractError, match="baseline_count"):
            parse_study_csv(
                b"submission_id,student_id,study_label,verdict,deviation_score,word_count\n"
            )

    def test_claimed_student_must_follow_the_rule_when_present(self):
        header = HEADER + ",claimed_student_id"
        with pytest.raises(StudyContractError, match="should be the imitated student"):
            parse_study_csv(_csv("a,s1,shadow,s2,SUBMITTED,0.2,5,400,s1", header=header))

    def test_unambiguous_v1_aliases_are_applied_and_reported(self):
        header = (
            "submission_id,writer_student_id,label,imitated_student_id,verdict,deviation_score,"
            "baseline_size,words"
        )
        data = parse_study_csv(_csv("a,s1,natural,,SUBMITTED,0.2,5,400", header=header))
        assert data.aliases_applied == {
            "baseline_size": "baseline_count",
            "label": "study_label",
            "words": "word_count",
            "writer_student_id": "student_id",
        }
        row = data.rows[0]
        assert (row.student_id, row.deviation_score, row.baseline_count) == ("s1", 0.2, 5)

    def test_v1_status_is_never_read_as_the_verdict(self):
        # A stored status is the seal-time one, against the WRITER's baseline.
        header = HEADER.replace("verdict", "status")
        with pytest.raises(StudyContractError, match="'status' is not read"):
            parse_study_csv(_csv("a,s1,natural,,SUBMITTED,0.2,5,400", header=header))
        # Beside a verdict it is just another column.
        data = parse_study_csv(
            _csv("a,s1,natural,,FLAGGED,0.2,5,400,SUBMITTED", header=HEADER + ",status")
        )
        assert data.rows[0].verdict == "FLAGGED"

    def test_v1_consistency_score_is_refused_not_converted(self):
        header = HEADER.replace("deviation_score", "consistency_score")
        with pytest.raises(StudyContractError, match="cannot be converted"):
            parse_study_csv(_csv("a,s1,natural,,SUBMITTED,80,5,400", header=header))
        data = parse_study_csv(
            _csv("a,s1,natural,,SUBMITTED,0.2,5,400,80", header=HEADER + ",ai_score")
        )
        assert data.rows[0].deviation_score == 0.2
        assert any("ignoring ai_score" in w for w in data.warnings)

    def test_inconclusive_and_unscored_are_kept_apart(self):
        data = parse_study_csv(
            _csv(
                "a,s1,natural,,INCONCLUSIVE,,2,400",
                "b,s1,natural,,SUBMITTED,,5,400",
                "c,s1,natural,,INCONCLUSIVE,0.55,2,400",
            )
        )
        by_id = {r.submission_id: r for r in data.rows}
        assert by_id["a"].inconclusive and not by_id["a"].unscored
        assert by_id["b"].unscored and not by_id["b"].conclusive
        assert by_id["c"].deviation_score is None  # an INCONCLUSIVE row's score is ignored ...
        assert any("INCONCLUSIVE row carries a score" in w for w in data.warnings)  # ... loudly

    def test_two_columns_for_one_field_are_refused(self):
        header = HEADER.replace("student_id,", "student_id,writer_student_id,", 1)
        with pytest.raises(StudyContractError, match="both map to 'student_id'"):
            parse_study_csv(_csv("a,s1,s1,natural,SUBMITTED,0.2,5,400", header=header))

    def test_verdict_that_follows_the_wrong_baseline_is_flagged(self):
        data = parse_study_csv(
            _csv(
                "a,s1,shadow,s2,INCONCLUSIVE,,6,400",  # target ready, yet inconclusive
                "b,s2,shadow,s1,SUBMITTED,0.2,2,400",  # target thin, yet scored
                "c,s1,natural,,SUBMITTED,0.2,5,400",
                "d,s2,natural,,SUBMITTED,0.2,5,400",
            )
        )
        joined = " ".join(data.warnings)
        assert "line 2: INCONCLUSIVE with 6 approved samples" in joined
        assert "line 3: scored with only 2 approved samples" in joined

    def test_an_imitated_student_who_never_wrote_is_warned_about(self):
        data = parse_study_csv(
            _csv("a,s1,shadow,s9,SUBMITTED,0.2,5,400", "b,s1,natural,,SUBMITTED,0.2,5,400")
        )
        assert any("'s9' never appears as a writer" in w for w in data.warnings)

    def test_unknown_feature_columns_are_ignored_with_a_warning(self):
        header = HEADER + ",f_type_token_ratio,f_not_a_feature"
        data = parse_study_csv(_csv("a,s1,natural,,SUBMITTED,0.2,5,400,0.5,1", header=header))
        assert data.feature_codes == ("type_token_ratio",)
        assert any("not_a_feature" in w for w in data.warnings)

    def test_unlabelled_rows_are_left_out_and_counted(self):
        data = parse_study_csv(
            _csv("a,s1,natural,,SUBMITTED,0.2,5,400", "b,s2,,,SUBMITTED,0.3,5,400")
        )
        assert [r.submission_id for r in data.rows] == ["a"]
        assert data.unlabelled == 1
        assert any("1 row(s) have no study_label" in w for w in data.warnings)
        with pytest.raises(StudyContractError, match="no labelled rows"):
            parse_study_csv(_csv("b,s2,,,SUBMITTED,0.3,5,400"))

    def test_a_row_with_more_fields_than_the_header_is_refused(self):
        with pytest.raises(StudyContractError, match="line 2: 1 more field"):
            parse_study_csv(_csv("a,s1,natural,,SUBMITTED,0.2,5,400,stray"))

    def test_a_blank_submission_id_is_one_problem(self):
        with pytest.raises(StudyContractError) as exc:
            parse_study_csv(_csv(",s1,,,,,,"))
        assert exc.value.problems == ["line 2: blank submission_id"]

    def test_flagged_without_a_score_is_warned_about(self):
        data = parse_study_csv(_csv("a,s1,natural,,FLAGGED,,5,400"))
        assert data.rows[0].unscored
        assert any("FLAGGED with no deviation_score" in w for w in data.warnings)

    def test_authorship_probability_is_range_checked(self):
        header = HEADER + ",authorship_probability"
        with pytest.raises(StudyContractError, match="authorship_probability 1.2 is outside"):
            parse_study_csv(_csv("a,s1,natural,,SUBMITTED,0.2,5,400,1.2", header=header))


# ── the evaluation ────────────────────────────────────────────────────────────


class TestEvaluation:
    @pytest.fixture(scope="class")
    def report(self, tmp_path_factory):
        return study_eval.run(CSV, tmp_path_factory.mktemp("eval") / "out")

    def test_report_states_the_score_and_its_direction(self, report):
        assert report["score"] == {
            "column": "deviation_score",
            "direction": "higher_is_less_consistent",
            "range": [0.0, 1.0],
            "flag_rule": "flagged when deviation_score >= cut-off",
        }

    def test_reference_cutoffs_are_the_action_bands(self, report):
        assert report["settings"]["reference_cutoffs"] == {
            "monitor": 0.4,
            "schedule_conversation": 0.6,
            "escalate": 0.75,
        }
        assert report["settings"]["live_flag_if_score_below"] == 70

    def test_confusion_matrix_is_the_exported_verdict(self, report):
        rows = load_study_csv(CSV).rows
        m = report["confusion_at_verdict"]["matrix"]
        for label in ("natural", "shadow"):
            flagged = sum(
                1 for r in rows if r.label == label and r.conclusive and r.verdict == "FLAGGED"
            )
            assert m[label]["flagged"] == flagged, label
        assert "exported verdict" in report["confusion_at_verdict"]["rule"]

    def test_confusion_matrix_accounts_for_every_attempt(self, report):
        m = report["confusion_at_verdict"]["matrix"]
        for label, n in (("natural", 40), ("shadow", 40)):
            x = m[label]
            assert (
                x["flagged"] + x["not_flagged"] + x["inconclusive"] + x["unscored"]
                == x["total"]
                == n
            )
        assert m["natural"]["inconclusive"] == 4 and m["shadow"]["inconclusive"] == 4
        assert m["natural"]["unscored"] == 1

    def test_verdict_matches_the_live_rule_on_the_fixture(self, report):
        # The fixture derives its verdict from authorship_probability the way
        # Exam.jsx does, so every conclusive row checks out.
        vc = report["confusion_at_verdict"]["verdict_check"]
        assert vc["rows_checked"] == 71 and vc["disagreements"] == 0

    def test_a_verdict_the_live_rule_would_not_give_is_counted(self, tmp_path):
        header = HEADER + ",authorship_probability"
        path = tmp_path / "mismatch.csv"
        path.write_bytes(
            _csv(
                "a,s1,natural,,FLAGGED,0.2,5,400,0.9",  # 90 >= 70: the live rule would not flag
                "b,s1,shadow,s2,FLAGGED,0.7,5,400,0.3",
                "c,s2,natural,,SUBMITTED,0.1,5,400,0.695",  # rounds to 70 (JS rounds halves up)
                "d,s2,shadow,s1,SUBMITTED,0.4,5,400",
                header=header,
            )
        )
        report, out = _run(tmp_path, "mismatch", csv_path=path, charts=False)
        vc = report["confusion_at_verdict"]["verdict_check"]
        assert vc["rows_checked"] == 3 and vc["disagreements"] == 1
        assert vc["disagreeing_submissions"] == ["a"]
        assert "is not the live rule's" in (out / "study_eval.md").read_text()

    def test_collections_score_rounds_halves_up_like_javascript(self):
        # Math.round(0.685 * 100) is 69 in JavaScript; Python's round() says 68.
        for prob, js in (
            (0.695, 70),
            (0.685, 69),
            (0.705, 71),
            (0.125, 13),
            (0.69, 69),
            (1.0, 100),
        ):
            assert study_eval.collections_score(prob) == js, prob

    def test_auc_matches_a_brute_force_count(self, report):
        rows = report["rows"]
        nat = [r[SCORE_COLUMN] for r in rows if r["conclusive"] and r["label"] == "natural"]
        sh = [r[SCORE_COLUMN] for r in rows if r["conclusive"] and r["label"] == "shadow"]
        wins = sum((s > n) + 0.5 * (s == n) for s in sh for n in nat)
        assert report["auc"]["value"] == pytest.approx(wins / (len(sh) * len(nat)), abs=1e-4)
        assert report["auc"]["value"] > 0.5  # shadow reads less consistent on this fixture
        lo, hi = report["auc"]["ci95"]
        assert lo <= report["auc"]["value"] <= hi

    def test_sweep_is_monotone_and_runs_from_all_to_nothing(self, report):
        sweep = report["sweep"]
        assert [r["threshold"] for r in sweep] == list(study_eval.THRESHOLD_GRID)
        assert sweep[0]["threshold"] == 0.0 and sweep[-1]["threshold"] == study_eval.FLAG_NOTHING
        ff = [r["false_flags"]["k"] for r in sweep]
        ca = [r["catches"]["k"] for r in sweep]
        assert ff == sorted(ff, reverse=True) and ca == sorted(ca, reverse=True)
        assert ff[0] == sweep[0]["false_flags"]["n"] and ca[0] == sweep[0]["catches"]["n"]
        assert ff[-1] == ca[-1] == 0

    def test_sweep_flags_at_or_above_the_cut_off(self, report):
        rows = report["rows"]
        nat = [r[SCORE_COLUMN] for r in rows if r["conclusive"] and r["label"] == "natural"]
        sh = [r[SCORE_COLUMN] for r in rows if r["conclusive"] and r["label"] == "shadow"]
        by_t = {r["threshold"]: r for r in report["sweep"]}
        for t in (0.3, 0.4, 0.6):
            assert by_t[t]["false_flags"]["k"] == sum(1 for v in nat if v >= t), t
            assert by_t[t]["catches"]["k"] == sum(1 for v in sh if v >= t), t

    def test_sweep_table_marks_the_action_bands(self, tmp_path):
        _, out = _run(tmp_path, "md", charts=False)
        md = (out / "study_eval.md").read_text()
        for mark in (
            "| 0.40 (monitor) |",
            "| 0.60 (schedule_conversation) |",
            "| 0.75 (escalate) |",
        ):
            assert mark in md, mark

    def test_inconclusive_rate_is_reported_per_label(self, report):
        inc = report["inconclusive"]
        # 80 attempts, one unscored: unscored rows are in no denominator.
        assert inc["all"]["inconclusive"]["k"] == 8 and inc["all"]["inconclusive"]["n"] == 79
        assert inc["natural"]["inconclusive"]["n"] == 39 and inc["natural"]["unscored"] == 1
        all_ff = report["confusion_at_verdict"]["false_flag_rate_all_attempts"]
        assert all_ff["n"] == 39

    def test_roc_area_is_the_reported_auc(self, report):
        pts = [(p["false_flag_rate"], p["catch_rate"]) for p in report["roc"]]
        assert pts[0] == (0.0, 0.0) and pts[-1] == (1.0, 1.0)
        area = sum(
            (x1 - x0) * (y0 + y1) / 2 for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False)
        )
        assert area == pytest.approx(report["auc"]["value"], abs=2e-3)

    def test_breakdowns_partition_the_attempts(self, report):
        for key in ("by_baseline_count", "by_word_count"):
            bins = report[key]
            assert sum(b["natural_attempts"] for b in bins) == 40, key
            assert sum(b["shadow_attempts"] for b in bins) == 40, key
        thin = report["by_baseline_count"][0]
        assert thin["bin"] == "0-2" and thin["inconclusive"]["rate"] == 1.0
        verdict_ff = report["confusion_at_verdict"]["false_flag_rate_conclusive"]["k"]
        assert (
            sum(b["false_flags_at_verdict"]["k"] for b in report["by_baseline_count"]) == verdict_ff
        )

    def test_per_student_gap(self, report):
        ps = report["per_student"]
        students = {s["claimed_student_id"]: s for s in ps["students"]}
        assert len(students) == 20
        assert students["synth-01"]["gap"] is None  # thin baseline: nothing to compare
        both = [s for s in students.values() if s["gap"] is not None]
        assert ps["summary"]["students_with_both_kinds"] == len(both) == 18
        for s in both:
            # Positive = the imitation read as less consistent (higher deviation).
            assert s["gap"] == pytest.approx(s["shadow_mean"] - s["natural_mean"], abs=1e-3)
        assert ps["summary"]["positive_gap"] > ps["summary"]["negative_gap"]

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
        assert "higher means LESS consistent" in md

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

"""The LENGTH_MATCHED_BASELINE soak reader keeps "never on" apart from "never
fired", and reads the line the route actually writes."""

import logging

from validation.length_match_thresholds.read_shadow_log import main, parse, summarise


def _line(**kw):
    base = {
        "mode": "shadow",
        "source": "staff",
        "pieces": "16",
        "papers_cut": "4",
        "n_tokens": "350",
        "body_words": "300",
        "deviation": "0.6500",
        "action": "schedule_conversation",
        "deviation_preview": "0.4100",
        "action_preview": "no_action",
    }
    base.update(kw)
    return "2026-11-19 INFO original.routers.students_scoring, length_match " + " ".join(
        f"{k}={v}" for k, v in base.items()
    )


def test_no_lines_means_shadow_was_never_on():
    assert summarise(parse(["unrelated line", "another"])) == {"status": "never_on", "n_lines": 0}


def test_lines_without_pieces_mean_the_flag_never_fired():
    s = summarise(parse([_line(pieces="0", deviation_preview="None", action_preview="None")]))
    assert s["status"] == "never_fired"
    assert s["by_source"]["staff"]["engaged"] == 0


def test_engaged_lines_give_the_shift_and_the_action_change_per_source():
    rows = parse(
        [
            _line(),
            _line(source="exam"),
            _line(source="practice", pieces="0", deviation_preview="None"),
            _line(n_tokens="300"),
        ]
    )
    s = summarise(rows)
    assert s["status"] == "engaged"
    staff = s["by_source"]["staff"]
    assert staff["n"] == 2 and staff["engaged"] == 2
    assert staff["with_back_matter"] == 1
    assert staff["deviation_shift_when_engaged"]["median"] == -0.24
    assert staff["action_today_to_on"] == {"schedule_conversation->no_action": 2}
    assert s["by_source"]["practice"]["engaged_share"] == 0.0


def test_the_reader_parses_the_route_s_own_line(caplog):
    """Pinned to the format string in students_scoring.py, not to a copy."""
    import inspect

    from original.routers import students_scoring

    src = inspect.getsource(students_scoring)
    start = src.index('"length_match mode=')
    fmt = "".join(
        part.strip().strip('"') for part in src[start : src.index(",\n", start)].split("\n")
    )
    values = ("shadow", "exam", 16, 4, 350, 300, 0.65, "monitor", 0.41, "no_action")
    with caplog.at_level(logging.INFO):
        logging.getLogger("t").info(fmt, *values)
    rows = parse(caplog.messages)
    assert rows[0]["source"] == "exam"
    assert rows[0]["action"] == "monitor"
    assert rows[0]["action_preview"] == "no_action"
    assert rows[0]["body_words"] == "300"


def test_main_reads_a_log_file(tmp_path, capsys):
    p = tmp_path / "pilot.log"
    p.write_text(_line() + "\n")
    assert main(["--log", str(p)]) == 0
    assert '"status": "engaged"' in capsys.readouterr().out

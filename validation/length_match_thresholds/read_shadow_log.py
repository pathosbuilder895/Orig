"""Read a LENGTH_MATCHED_BASELINE shadow soak out of the pilot's logs.

    render logs --tail 100000 \
        | .venv/bin/python -m validation.length_match_thresholds.read_shadow_log
    .venv/bin/python -m validation.length_match_thresholds.read_shadow_log --log pilot.log

The route writes one ``length_match`` line per scoring call while the flag is
not off (original/routers/students_scoring.py). This counts them; it prints no
identifier, because the line carries none.

The answer comes in three states, kept apart because a bare rate cannot tell
them apart:

  never_on     no length_match line at all: shadow was not running, and the
               soak measured nothing.
  never_fired  lines, but no paper was ever short enough for a past paper to
               be cut (pieces=0 throughout): the flag is inert on this traffic.
  engaged      at least one paper was compared with pieces; the report then
               gives, per source (staff, exam seal, student practice check),
               how often that happened, how far the score would move, and the
               action today's cut points gave against the one "on" would give.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter

_LINE = re.compile(r"length_match (mode=\S+.*)$")
_PAIR = re.compile(r"(\w+)=(\S+)")


def parse(lines) -> list[dict]:
    rows = []
    for line in lines:
        m = _LINE.search(line)
        if not m:
            continue
        rows.append(dict(_PAIR.findall(m.group(1))))
    return rows


def _num(v: str | None) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dist(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    v = sorted(values)
    return {
        "n": len(v),
        "median": round(statistics.median(v), 4),
        "p10": round(v[round((len(v) - 1) * 0.1)], 4),
        "p90": round(v[round((len(v) - 1) * 0.9)], 4),
    }


def summarise(rows: list[dict]) -> dict:
    if not rows:
        return {"status": "never_on", "n_lines": 0}
    engaged = [r for r in rows if (_num(r.get("pieces")) or 0) > 0]
    out: dict = {
        "status": "engaged" if engaged else "never_fired",
        "n_lines": len(rows),
        "modes": dict(Counter(r.get("mode", "?") for r in rows)),
        "by_source": {},
    }
    for source in sorted({r.get("source", "unknown") for r in rows}):
        rs = [r for r in rows if r.get("source", "unknown") == source]
        es = [r for r in rs if (_num(r.get("pieces")) or 0) > 0]
        back_matter = [
            r
            for r in rs
            if _num(r.get("n_tokens")) is not None
            and _num(r.get("body_words")) is not None
            and _num(r["n_tokens"]) > _num(r["body_words"])
        ]
        shifts = [
            _num(r["deviation_preview"]) - _num(r["deviation"])
            for r in es
            if _num(r.get("deviation_preview")) is not None and _num(r.get("deviation")) is not None
        ]
        out["by_source"][source] = {
            "n": len(rs),
            "engaged": len(es),
            "engaged_share": round(len(es) / len(rs), 4),
            "with_back_matter": len(back_matter),
            "body_words": _dist([_num(r["body_words"]) for r in rs if _num(r.get("body_words"))]),
            "deviation_shift_when_engaged": _dist(shifts),
            "action_today_to_on": dict(
                Counter(
                    f"{r.get('action', '?')}->{r.get('action_preview', '?')}"
                    for r in es
                    if r.get("mode") == "shadow"
                )
            ),
        }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", help="log file (default: stdin)")
    args = ap.parse_args(argv)
    if args.log:
        with open(args.log, encoding="utf-8", errors="replace") as f:
            rows = parse(f)
    else:
        rows = parse(sys.stdin)
    print(json.dumps(summarise(rows), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

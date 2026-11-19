# Action cut points for the length-matched reference (2026-11-19)

**Question.** PR #334's `LENGTH_MATCHED_BASELINE=on` compares a short new paper
with pieces of the student's long past papers instead of the whole papers. It
stopped false alarms on honest short papers, but at the product's cut points
(0.40 / 0.60 / 0.75, set for whole-paper references) it also stopped catching
other writers. Which cut points fit the matched reference, and do they hold on
writers they were not chosen on?

**Writing.** `validation/scholarly/`, humanities collection: published scholars'
single-author journal articles, mostly theology and religion, with at least 6
separate papers per author. **Not student writing.** The pilot will be the first
measurement on students.

**Design.** Fixed in `run.py` before the first run (commit `0a1e082`); the
criteria fingerprint `b45d5f695733f008` is checked by the hold-out.

- Per author: 4 past papers and 2 new papers, each a different article, cut to
  a fixed length; other-writer probes are 5 other authors' new papers.
- Cells (past, new words): 1200/300, 1500/450, 1200/600.
- Scored off and on through `quantum.scoring.score()`, pilot defaults
  (`NULL_MODEL` none, typicality off), sentence-transformers blocked.
- Cut points chosen on the `calibration` partition (56 authors): the smallest
  value whose honest share at or above it has a 95% Wilson upper bound of 20%
  (monitor), 5% (worth a conversation), 2% (very differently).
- Tested once on the author-disjoint `locked_test` partition (60 authors).

**Cut points** (`derived_cut_points.json`, committed before the hold-out):
monitor **0.517**, worth a conversation **0.622**, very differently **0.703**.

**Hold-out: PASS** (`report_2026-11-19.json`). 360 honest and 900 other-writer
trials; the match engaged on every honest trial.

| | Off, product cut points | On, product cut points | On, new cut points |
|---|---|---|---|
| Honest at "worth a conversation" or higher | 48.3% | 1.9% | **0.6%** (by author, 95%: 0.0-1.4%) |
| Honest at "very differently" | 1.1% | 0.0% | 0.0% |
| Honest at "monitor" or higher | 99.4% | 71.9% | **11.4%** |
| Other writers caught (conversation or higher) | 83.7% | 20.8% | **13.9%** |

AUC 0.767 (off) and 0.836 (on). Off moved to the same honest rate (0.6%)
catches 5.9%.

**How to read it.**

- Off catches 84% of other writers only by flagging 48% of honest papers. With
  false alarms held near 1%, the system tells writers apart on about one short
  paper in seven. The matched reference separates better than whole papers
  (higher AUC, more caught at an equal honest rate), but short papers carry
  little signal: this removes false alarms, it does not create detection.
- The large change for teachers is the monitor band: 99% of honest short papers
  read "Mostly like their own writing; a few habits differ" or worse today, 11%
  with these cut points.
- n is 56 and 60 authors on one kind of writing. The rows are not rates to
  quote for students.

**The hold-out was started twice.** The first attempt (2026-11-19T02:15) crashed
after loading its first cell, because the script dropped the study id the
loader needs on every load of `locked_test`. Nothing was printed or saved. The
same test was rerun with unchanged criteria after the fix (`LOCKED_OPENINGS.tsv`
has one line per cell load).

**Rerun.** Restore the texts, then derive (about 15 minutes on 3 workers); the
hold-out refuses a second run once its report exists.

```bash
.venv/bin/python -m validation.scholarly.fetch --collection humanities --restore
.venv/bin/python -m validation.length_match_thresholds.run derive --jobs 3
```

2,762 of 3,190 manifest papers restored on 2026-11-19 (396 hash mismatches from
the v1 to v2 cleaner change, 27 unreachable); authors missing a paper are
skipped, never partially used.

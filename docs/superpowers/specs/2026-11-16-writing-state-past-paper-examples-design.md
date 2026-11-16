# Writing State: real example sentences, with or without an analysis

*2026-11-16. Requested by Andrew. Builds on PR #340 (passages in the Writing State panel) and PR #341 (stacked on #340); this work is stacked on #341 and merges after both.*

## Intent and the why

A teacher looking at a student's writing on Writing State should see the student's own sentences, not only numbers. Andrew's words: "not just say next to analysis it doesn't look similar, examples which give the why it looks different first hand."

Two gaps stop that today:

1. **Sentence length shows the wrong past-paper sentences.** When a paper's sentences are shorter than the past papers', the past-paper column quotes the past papers' *shortest* sentences. Measured locally on 2026-11-16 with three Mill passages as past papers and a Chesterton passage as the paper:
   - the paper averages 19.8 words per sentence and the past papers 32.4 to 43.8;
   - the past-paper column still showed sentences of 14, 7 and 24 words.

   The cause is `original/evidence.py`, `build_feature_evidence` → `chosen` → `_length_pick(places, "mean", direction, …)`. It applies this paper's direction to both sides, so both sides get the same end of the range.
2. **No analysis, no examples.** Before a paper is analysed, Writing State's side-by-side panel (`#hero-evi`, the "This submission" and "Their own past work" columns) shows only a 0 to 1 average for the past work. Andrew wants the panel filled with real sentences from the student's past papers when no paper is being analysed, for instance sentence length and sentence variation.

## Goals

- **Typical sentences.** For sentence length, each side quotes typical sentences, so the contrast is honest and visible.
- **Examples before any analysis.** With no analysis on Writing State, the panel opens by itself on sentence length and shows the student's past papers side by side in their own sentences. Sentence variation is one click away, and any other quotable habit opens the same way.
- **Unchanged after analysis.** Once a paper is analysed, the panel behaves as #340 made it, this paper beside past papers, with fix 1 applied.

## Non-goals

- No change to any score, threshold, weight, action or stored data.
- No new environment flag.
- No change to what students see.
- No new page; the separate side-by-side page (`evidence.html`) gets fix 1 for free and nothing else.
- No examples for whole-text habits (they have no single sentence to quote, as today).

## Anti-goals: a failure even if it works

- **Cherry-picking that exaggerates.** For example, putting the past papers' longest sentences beside this paper's shortest. Every pick rule must be one that would read fairly to the student.
- **Any wording of judgment.** No "suspicious", no "doesn't match", no score shown in the no-analysis view.
- **Any route by which a student sees these examples,** or by which one workspace sees another's text.

## Constraints

- **Staff only and same workspace (NORTH_STAR rules 7 and 8, ADR-013).**
  - The new request refuses students with `_require_staff`.
  - It lives under `/students/{student_id}/…`, so the tenant-isolation middleware scopes it to the caller's workspace, as it does `GET /students/{id}`.
- **Gated by the existing flag.** `EVIDENCE_PASSAGES_ENABLED`, with the exact-"1" rule in `original/evidence.py:evidence_enabled`. With the flag off, the request answers 404 and Writing State behaves exactly as on #341. #340 already sets the flag to "1" for the pilot in `render.yaml`.
- **Same papers and labels as scoring.**
  - The past papers used are exactly those scoring's evidence uses: `state.samples` with `auth_weight > 0` and stored `text`.
  - They are labelled `past paper 1…N` in that order, with the same `baseline_papers` entries (title, date, provenance, word count), so labels and sources read the same before and after an analysis.
- **Same sentence finder.** Examples come from `read_paper` and `_quote` in `original/evidence.py`, so sentence boundaries, word counts and marked spans match the analysed view exactly. No sentence splitting in the browser.
- **Tests and coverage.** CI holds 98% combined statement and branch coverage. The new route, the new builder function and the new pick rule all need tests, and the page needs an e2e check.

## Approaches considered

- **A. Stack on #341 (chosen by Andrew, 2026-11-16).**
  - Reuse #340's passage panel on Writing State.
  - Add a staff-only request that reads the past papers alone.
  - Fix the pick rule in `evidence.py`.
  - Merges after #340 and #341.
- **B. Build on main.** Independent, but it rewrites the same panel #340 rewrites, so one of the two would be partly redone. Until #340 lands, there would also be no passages after an analysis.
- **C. Do the examples in the browser.** Ruled out: the browser never gets past-paper text today, and splitting sentences in JavaScript would disagree with the engine's own counts.

## The design

### Fix 1: typical sentences for sentence length (`original/evidence.py`)

- **Average sentence length** (`mean_sentence_length`, mode `"mean"`): each paper, this one and each past paper, quotes its sentences whose word count is closest to that paper's own average. Ties break by position in the paper. That is, `sorted(places, key=(abs(words − paper_mean), start))`, where `paper_mean` is that paper's `PaperReading.value`.
  - The pick no longer depends on the direction of the difference.
  - The past-paper side keeps its round-robin across papers, one typical sentence per paper per pass.
- **Sentence variation** (`sentence_length_variance`, mode `"spread"`): unchanged. Each side alternates its longest and shortest sentences.
- **Tests:** update `tests/test_evidence.py:496`, which pins the old shortest-first pick, and add a test with known sentence lengths showing each side's quotes are its typical ones.

### New request: past-paper examples (`GET /students/{student_id}/past-paper-examples?habit=<code>`)

- **One habit per request.** `habit` is one of the 23 codes in `LOCATABLE` (default `mean_sentence_length`; any other value gives 422). Baselines grow over a term, so one habit at a time keeps the answer small: at most 3 quotes of at most 360 characters per paper. *(Builder-check call.)*

- **Where:** in `original/routers/students_scoring.py` beside `_attach_staff_explainability`, or a small new router module; builder's call.
- **Order of checks:**
  1. Flag off: 404.
  2. Not staff: `_require_staff`'s 403 or 401.
  3. Unknown student: 404, as `GET /students/{id}`.
- **Response** (a new pydantic model in `original/schemas.py`):

  ```json
  {
    "baseline_papers": [ {"paper": "past paper 1", "assignment": "...", "submitted_at": "...", "provenance": "...", "word_count": 812} ],
    "feature": {
      "code": "mean_sentence_length", "name": "...", "description": "...", "unit": "words per sentence",
      "what_is_marked": "...", "kind": "located",
      "per_paper": [ {"paper": "past paper 1", "value": 40.3, "count": 21,
                      "examples": [ {"role": "typical", "quote": <quote>} ]} ]
    }
  }
  ```

- **`role` labels each quote, and the server sets it.** Values are `typical` for sentence length, `longest` or `shortest` for sentence variation, and `null` for every other habit. The browser never infers a role from position or word counts. *(Builder-check call.)*
- **Sentence variation shows exactly two quotes per paper:** its longest and its shortest sentence, or one quote if the paper has a single sentence. That way no middle sentence can be mislabelled "longest". *(Builder-check call.)* The analysed view's existing three-quote interleave is left as it is.
- **All papers are shown, in scoring's order** (`past paper 1…N`, the stored sample order), with no cap. Labels therefore always match the analysed view. *(Builder-check call.)*

- **`baseline_papers`:** identical in shape and order to `evidence.baseline_papers` on a score response. If #341 adds `source` there, include it here too.
- **`feature`:** the requested habit.
  - `<quote>` is exactly what `_quote` returns today, wrapped with its `role`.
  - `examples` holds at most 3 quotes per paper (2 for variation), chosen by the rule above: typical for sentence length, longest and shortest for variation, otherwise the first places in document order (`_pick`).
  - A paper whose habit cannot be located exactly (`places is None`) gets `examples: []`, and the feature carries `NOT_LOCATED_NOTE`.
- **Builder function:** a new pure function in `original/evidence.py`, for example `build_past_paper_examples(code, baselines)`, where `baselines` is the same `[(label, text)]` list scoring builds. The route only gathers samples and calls it, so it is testable without HTTP. Factor the shared label-and-papers code (including `source`, which `_attach_staff_explainability` already adds) out of that function rather than copying it.
- **No past papers with text:** `200` with empty `baseline_papers` and `per_paper`.
- **Failure:** any exception while building is logged and answered with 503. It never breaks the page; the page treats any non-200 as "no examples".

### Writing State (`demo/original/writing-state.html`)

- **When it loads:** past-paper mode applies only while **no analysis result is on the page**. That means a visit with nothing analysed, including when the page does not restore a stored result for this student (`restoreLast`).
  - With no result, fetch sentence length once. On 200 with at least one paper that has examples, enter **past-paper mode**; on anything else, nothing changes.
  - A page that starts with a restored result does not fetch. It shows the analysed view, as on #341.
  - Fetch other habits on demand and cache each one for the page's life. *(Builder-check call.)*
- **Past-paper mode** (no analysis yet):
  - **Opening:** the side-by-side panel opens on its own on **sentence length**. The decorative pattern stays behind it, and "Back to the pattern" still closes it, as today.
  - **Habit switch:** two small buttons at the top of the panel, **Sentence length** and **Sentence variation**, switch between the two.
  - **Other habits:** clicking any habit (a bar, a tier chip, a row) opens that habit's past-paper examples if it is one of the 23 quotable habits. Otherwise it shows today's numbers-only panel.
  - **Columns:** the panel's two columns become **one column per past paper**. Each column is headed with the paper's title and date, using the same `EV.pastSource` wording as the analysed view, then that paper's own number with its unit (e.g. "40.3 words per sentence"), then its quoted sentences with the counted part marked (`EV.markParts`), each with its word count and, where the server gave one, its role ("typical", "longest", "shortest"). With more than two past papers, columns wrap two to a row and the panel scrolls.
  - **Plain line:** one plain line under the columns, for example "These are sentences from <name>'s own past papers, so you can see their usual writing before you analyse anything." No comparison wording, no score.
- **After an analysis:** the panel switches to #340's this-paper-beside-past-papers view, and the page stays as #341 leaves it.
  - "Analyse another" only reopens the form, as today. No new control clears a result, so the triage, packet and evidence flows are untouched.
  - Past-paper mode returns on the next visit with no result shown. *(Builder-check call.)*
- **Flag off or 404:** Writing State is unchanged from #341.

### Tests

- **`tests/test_evidence.py`:** the typical pick, the unchanged spread pick, and `build_past_paper_examples` on known texts:
  - labels and order;
  - at most 3 examples, or exactly 2 for variation, with the right roles;
  - a single-sentence paper;
  - the not-located case;
  - empty input;
  - an unknown habit.
- **Route tests:**
  - flag off gives 404;
  - a student principal gets 403, including the student's own id;
  - another workspace's student is refused, the same as for `GET /students/{id}`;
  - a student with no text gives empty lists;
  - staff get examples whose labels match what `POST /students/{id}/score` puts in `evidence.baseline_papers`.
- **Voice leak:** extend `tests/test_voice_leak.py` so no student route ever returns past-paper example text.
- **Playwright e2e** (`demo/bluebook/e2e/`), with the flag on, a writer with three past papers and no analysis:
  - the panel is open on sentence length with one column per paper and real quotes;
  - Sentence variation switches;
  - after an analysis the panel shows this paper beside the past papers;
  - with the flag off, the panel stays closed.
- **CI command:** run the full command with `--cov-branch` and check that coverage holds at 98%.

## Left to the builder

- Where the route lives, and the exact model names.
- CSS for the per-paper columns, within the existing panel's look.
- Exact wording of the plain line and button labels, within the anti-goals above.
- Whether the e2e reuses #340's evidence fixtures.

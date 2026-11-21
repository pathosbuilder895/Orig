# Document parts v2: a labelled test set and harness

**Diagnostic, not validation, and not a gate.** No verdict here is a pass or a
fail; nothing in `original/` and no flag default changed.

**Question.** How well does Original separate a paper's title page, heading
block, abstract, section headings, notes, bibliography and appendix from the
student's prose, with the matter splitter (`MATTER_SPLITTER_ENABLED`) off and
on, for pasted text, .docx and .pdf? And how much do the parts it misses move a
reading?

## What is in the set

- **Writers.** The nine authors of `../document_parts_2026-11-18/` (the
  `validation/public_authors/corpus/` authors with five `*part_0*.txt` files).
  Past papers: parts 1 to 4; the paper: part 5. Each is cut to whole
  paragraphs of about 1,450 words (the 2026-11-18 run cut at 9,000
  characters), with wrapped lines joined and Gutenberg apparatus (chapter
  headings, all-caps summaries, "CH. I." abstracts, "(1) Psalm ..." note
  lists) dropped, so the body reads like a paper's paragraphs. The past papers
  are cleaned the same way and pasted, so they carry no parts.
- **Split.** `content.SPLIT`, a committed list drawn once with
  `random.Random(20261120)`: dev = augustine, boethius, douglass, edwards,
  james, newman; holdout = chesterton, kempis, mill. Everything below is dev.
- **Cases** (per author; `make_cases.py`):

  | Group | Variants |
  |---|---|
  | MLA | `mla`: heading block (name, teacher, course, date), centred title, Works Cited with hanging indents |
  | APA 7 | `apa_student`: title page (title, name, department and institution, course, teacher, due date), "Abstract" page (a 180-200 word abstract written for that prose, not copied from it) with a "Keywords:" line, the title again, prose with 3 section headings, References (DOIs, URLs, one "n.d."). `apa_professional`: "Running head:" line, Author Note, running head in the header |
  | Turabian | `turabian`: separate title page ("A Paper Submitted to Dr. ... In Partial Fulfillment of the Requirements for the Course ... by ... City, State, Month Year"), 6 numbered notes (pasted: endnotes under "Notes"; .docx/.pdf: real footnotes), Bibliography with year-less web entries. `turabian_appendix`: plus "Appendix A" of the author's own later prose after the bibliography |
  | Edge | `apa_reference_list` ("Reference List"), `apa_literature_cited` ("Literature Cited"), `mla_unheaded_refs` (no heading over the Works Cited entries), `mla_short_long_refs` (4 paragraphs, about 450 words, and 22 entries), `apa_bold_abstract` ("**Abstract**"), `markdown_apa` ("# Title", "## Abstract", "## " section headings, "## References") |
  | Negative controls | student writing using the words the rules look for, inside an MLA wrapper: `neg_abstract_word` (a paragraph opening "Abstract as this distinction may sound ... The abstract nature of the question"), `neg_references_sentence` (a mid-paper paragraph opening "References to Augustine in this paper ..."), `neg_sermon_prayer` (a sermon ending in a 7-line closing prayer, "Let us pray." to "Amen."), `neg_letter` (a letter-to-a-friend assignment: "Dear Thomas," ... "With affection," / first name) |
  | Prose alone | `prose`, `prose_short`, and the four negative controls' prose without the wrapper: what each case's reading is compared with |

- **Input types.** Each case four ways: `paste` (a blank line between
  paragraphs, like a Google Docs paste), `paste_word` (one newline between
  paragraphs, like a Word paste), `docx` (python-docx with Title and Heading 1
  styles, page breaks after the title page and abstract and before the
  references, the running head or page number as a PAGE field in the header or
  footer, real footnotes for Turabian) and `pdf` (that .docx printed by
  LibreOffice 24.2 headless). The .docx and .pdf text is what
  `original.upload_utils.extract_text_from_bytes` returns, the same extraction
  as the teacher's "open a file" route (`/students/{id}/upload`).
- **Labels.** Every character of the text as Original sees it carries its true
  part. Pasted text is labelled as it is built. Extracted text is labelled by
  matching it back to the source (`labels.py`): the body word by word, then the
  running heads and footnotes the PDF printed in the middle of the flow. A part
  that cannot be found is counted as lost in extraction, never guessed; a
  character that matches nothing is counted as unattributed (0 in this build).
- **Size.** 9 authors x 21 documents x 4 inputs = 756 records, all in
  `cases.jsonl.xz` (text, labels as runs, what extraction lost). The .docx and
  .pdf files for one dev author (edwards: the five main formats and
  `markdown_apa`) are in `samples/`; the rest are rebuilt into `build/`
  (ignored) by `make_cases.py`, to keep the folder small.

## Results (dev: 6 authors)

For scale: the prose alone reads "monitor" for 4 of 6 dev authors and "no
action" for 2 (paste, docx, pdf); the ~450-word short prose reads "schedule a
conversation" for 4 of 6. Reading changes below are against those, in the same
input type. All rows n = 6, so every band count below ("4 of 6 up a band") is
**uninformative** as a proportion: it shows direction, not a rate.

**No result here authorises `MATTER_SPLITTER_ENABLED=1`.** How often these
parts appear in real submissions, and how they are shaped, is exactly what this
corpus cannot supply. And `mla_short_long_refs` is a splitter-on regression
against off (+0.120 on, +0.022 off, pasted).

**No prose set aside was seen, on these templates.** In all 504 dev papers x 2
settings, not one character of true prose was left out of the measured body,
negative controls included ("Abstract as this distinction may sound ...",
"References to Augustine ...", a closing prayer, a letter's greeting and
sign-off). With the splitter on, the four negative controls read exactly as
their prose alone in pasted text and .docx (0.000 on all 6). This is a bounded
claim: the prose was cleaned of headings, all-caps lines and numbered lists
before it was wrapped, and the negative controls are 4 fixed trigger texts
repeated over 6 authors, so their effective n is 4, not 24. Real student prose
(short lines, lists, numbered points) can still be set aside by these rules.

**What the splitter catches** (on, pasted or .docx): the MLA heading block and
title (100%), the APA student title page (100%), APA section headings (100%
with a blank line between paragraphs, 81% without), "Works Cited",
"References", "Bibliography" and "## References" lists (100%), and everything
after "Notes" in Turabian except the year-less short notes (about half the
notes text). Where it catches every part, the reading does not move: MLA with a
blank-line paste or .docx, 0.000 on all 6 papers; with the splitter off the same papers moved
+0.032 on average and 2 of 6 went up a band.

**The biggest failures, by effect on the reading** (splitter on unless said):

1. **Turabian as a PDF: +0.112 on average, 4 of 6 up a band** (+0.078, 4 of 6
   with the appendix). In the PDF the footnotes are printed at the foot of each
   page, inside the prose (14-18% set aside), and the bibliography is no longer
   recognised: its entries wrap, so most lines no longer start like an entry
   ("Hollis, Margaret A. "Reading ... Journal of" / "Humanities Pedagogy 14 ..."),
   and the check that most lines after the heading are entries fails (0% set
   aside, against 100% with the splitter off, where the old rule cuts at the
   heading). Example (edwards): 0.574 "monitor" alone, 0.645 "schedule a
   conversation" as a Turabian PDF; 0.579 with the splitter off.
2. **A short paper with a long list: +0.120 to +0.132, 4 to 6 of 6 up a
   band, in every input type, where the splitter off gave +0.001 to +0.022.**
   With 4 paragraphs and 22 entries the "Works Cited" heading falls in the first
   40% of the paper's lines, so the list is not trusted and is measured as
   prose. Example (newman, pasted): 0.615 "schedule a conversation" alone,
   0.754 "escalate" with its Works Cited (0.619 with the splitter off).
3. **Headings neither rule knows, and no heading: +0.065 to +0.114 on average
   (lowest for a Word-style paste), 4 of 6 up a band with a blank-line paste,
   .docx or PDF, both settings.** "Reference List" and
   "Literature Cited" are not in either rule's heading list (0-2% set aside);
   an unheaded Works Cited list is never found (0%). Example (boethius,
   "Reference List", pasted): 0.431 alone, 0.534 on (0.546 off), both
   "monitor".
4. **MLA as a PDF: +0.057 on average, 4 of 6 up a band** (off: +0.024, 3 of 6;
   the effect size is **uninformative at n = 6**).
   The same wrapped-entry problem as 1: the Works Cited list is set aside for
   only 1 of 6 papers (augustine; 16% of the characters pooled). The negative controls inherit it
   in PDF form (+0.047, +0.048).
5. **Abstracts, and title pages outside pasted text.** Only the word
   "Abstract" is ever set aside (1% of abstract characters); the 180-200 word
   abstract, its "Keywords:" line and the APA title repeated over the first
   page are measured as prose. In a PDF the APA title page is never set aside
   (0%), nor is the Turabian title page beyond its first line (12%), and with a
   Word-style paste the APA professional title page ("Running head:", Author
   Note) is missed entirely. The reading moves less than for a bibliography and
   in both directions (APA student, pasted: +0.019, -0.012 to +0.042, 2 of 6 up;
   Word-style paste: -0.026, down to -0.115). Whether this is distortion more
   than false alarm is **uninformative at n = 6**.

**Input type alone moves readings.** The same prose with one newline between
paragraphs (a Word-style paste) reads +0.022 to +0.063 higher than with a blank
line (6 of 6 higher, both settings; 3 of 6 moved up a band: douglass and james
from "no action" to "monitor", edwards from "monitor" to "schedule a
conversation"), and as a PDF from
-0.040 to +0.051. .docx extraction gives exactly the blank-line paste. This is
not about parts, but it is as large as most part effects above.

**What extraction loses.** .docx (python-docx paragraphs): the running head
and page numbers (100%), the footnotes (100%) and the footnote numbers in the
prose (100%); everything else arrives, with styles and page breaks gone. PDF
(pypdf): nothing is lost, but the running head and page number are inserted at
every page boundary (the splitter sets 100% of them aside; with it off, 0-27%,
only those after the cut), footnotes land mid-paragraph, and every line is
hard-wrapped, which is what defeats the list-of-sources check. Pasted text
carries no headers or footnotes by construction.

## Tables (dev)

Generated by `run.py` from `summary_dev.json`; n is papers per row (one per dev
author).

<!-- tables:dev -->
Each cell: share of that part's characters set aside, splitter **off / on**; last column: share of the true prose set aside (false set-aside), off / on. Non-whitespace characters, pooled over the n papers in the row.

#### By format

| Format | Input | n | title page | heading block | title | abstract | section headings | references | notes | appendix | running head | **prose set aside** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MLA | paste | 42 |  | 0% / 100% | 0% / 100% |  |  | 85% / 46% |  |  |  | **0% / 0%** |
| MLA | paste_word | 42 |  | 0% / 100% | 0% / 100% |  |  | 85% / 46% |  |  |  | **0% / 0%** |
| MLA | docx | 42 |  | 0% / 100% | 0% / 100% |  |  | 85% / 46% |  |  |  | **0% / 0%** |
| MLA | pdf | 42 |  | 0% / 100% | 0% / 100% |  |  | 85% / 10% |  |  | 3% / 100% | **0% / 0%** |
| APA | paste | 36 | 0% / 72% |  | 0% / 78% | 0% / 1% | 0% / 100% | 49% / 67% |  |  |  | **0% / 0%** |
| APA | paste_word | 36 | 0% / 64% |  | 0% / 0% | 0% / 1% | 0% / 81% | 49% / 67% |  |  |  | **0% / 0%** |
| APA | docx | 36 | 0% / 72% |  | 0% / 78% | 0% / 1% | 0% / 100% | 49% / 67% |  |  |  | **0% / 0%** |
| APA | pdf | 36 | 0% / 0% |  | 0% / 0% | 0% / 0% | 0% / 75% | 49% / 66% |  |  | 0% / 30% | **0% / 0%** |
| Turabian | paste | 12 | 0% / 96% |  |  |  |  | 100% / 100% | 100% / 49% | 100% / 100% |  | **0% / 0%** |
| Turabian | paste_word | 12 | 0% / 12% |  |  |  |  | 100% / 100% | 100% / 47% | 100% / 100% |  | **0% / 0%** |
| Turabian | docx | 12 | 0% / 96% |  |  |  |  | 100% / 100% |  | 100% / 100% |  | **0% / 0%** |
| Turabian | pdf | 12 | 0% / 12% |  |  |  |  | 100% / 0% | 0% / 16% | 100% / 0% | 21% / 100% | **0% / 0%** |
| prose only | paste | 36 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose only | paste_word | 36 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose only | docx | 36 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose only | pdf | 36 |  |  |  |  |  |  |  |  |  | **0% / 0%** |

#### By variant

| Variant | Input | n | title page | heading block | title | abstract | section headings | references | notes | appendix | running head | **prose set aside** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| mla | paste | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| mla | paste_word | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| mla | docx | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| mla | pdf | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 16% |  |  | 0% / 100% | **0% / 0%** |
| apa_student | paste | 6 | 0% / 100% |  | 0% / 80% | 0% / 1% | 0% / 100% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_student | paste_word | 6 | 0% / 100% |  | 0% / 0% | 0% / 1% | 0% / 81% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_student | docx | 6 | 0% / 100% |  | 0% / 80% | 0% / 1% | 0% / 100% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_student | pdf | 6 | 0% / 0% |  | 0% / 0% | 0% / 0% | 0% / 75% | 100% / 100% |  |  | 0% / 100% | **0% / 0%** |
| apa_professional | paste | 6 | 0% / 22% |  | 0% / 80% | 0% / 1% | 0% / 100% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_professional | paste_word | 6 | 0% / 0% |  | 0% / 0% | 0% / 0% | 0% / 81% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_professional | docx | 6 | 0% / 22% |  | 0% / 80% | 0% / 1% | 0% / 100% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_professional | pdf | 6 | 0% / 0% |  | 0% / 0% | 0% / 0% | 0% / 75% | 100% / 100% |  |  | 0% / 12% | **0% / 0%** |
| turabian | paste | 6 | 0% / 96% |  |  |  |  | 100% / 100% | 100% / 49% |  |  | **0% / 0%** |
| turabian | paste_word | 6 | 0% / 12% |  |  |  |  | 100% / 100% | 100% / 48% |  |  | **0% / 0%** |
| turabian | docx | 6 | 0% / 96% |  |  |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| turabian | pdf | 6 | 0% / 12% |  |  |  |  | 100% / 0% | 0% / 14% |  | 14% / 100% | **0% / 0%** |
| turabian_appendix | paste | 6 | 0% / 96% |  |  |  |  | 100% / 100% | 100% / 49% | 100% / 100% |  | **0% / 0%** |
| turabian_appendix | paste_word | 6 | 0% / 12% |  |  |  |  | 100% / 100% | 100% / 47% | 100% / 100% |  | **0% / 0%** |
| turabian_appendix | docx | 6 | 0% / 96% |  |  |  |  | 100% / 100% |  | 100% / 100% |  | **0% / 0%** |
| turabian_appendix | pdf | 6 | 0% / 12% |  |  |  |  | 100% / 0% | 0% / 18% | 100% / 0% | 27% / 100% | **0% / 0%** |
| apa_reference_list | paste | 6 | 0% / 100% |  | 0% / 80% | 0% / 1% | 0% / 100% | 0% / 1% |  |  |  | **0% / 0%** |
| apa_reference_list | paste_word | 6 | 0% / 100% |  | 0% / 0% | 0% / 1% | 0% / 81% | 0% / 1% |  |  |  | **0% / 0%** |
| apa_reference_list | docx | 6 | 0% / 100% |  | 0% / 80% | 0% / 1% | 0% / 100% | 0% / 1% |  |  |  | **0% / 0%** |
| apa_reference_list | pdf | 6 | 0% / 0% |  | 0% / 0% | 0% / 0% | 0% / 75% | 0% / 0% |  |  | 0% / 100% | **0% / 0%** |
| apa_literature_cited | paste | 6 | 0% / 100% |  | 0% / 80% | 0% / 1% | 0% / 100% | 0% / 2% |  |  |  | **0% / 0%** |
| apa_literature_cited | paste_word | 6 | 0% / 100% |  | 0% / 0% | 0% / 1% | 0% / 81% | 0% / 2% |  |  |  | **0% / 0%** |
| apa_literature_cited | docx | 6 | 0% / 100% |  | 0% / 80% | 0% / 1% | 0% / 100% | 0% / 2% |  |  |  | **0% / 0%** |
| apa_literature_cited | pdf | 6 | 0% / 0% |  | 0% / 0% | 0% / 0% | 0% / 75% | 0% / 0% |  |  | 0% / 100% | **0% / 0%** |
| mla_unheaded_refs | paste | 6 |  | 0% / 100% | 0% / 100% |  |  | 0% / 0% |  |  |  | **0% / 0%** |
| mla_unheaded_refs | paste_word | 6 |  | 0% / 100% | 0% / 100% |  |  | 0% / 0% |  |  |  | **0% / 0%** |
| mla_unheaded_refs | docx | 6 |  | 0% / 100% | 0% / 100% |  |  | 0% / 0% |  |  |  | **0% / 0%** |
| mla_unheaded_refs | pdf | 6 |  | 0% / 100% | 0% / 100% |  |  | 0% / 0% |  |  | 0% / 100% | **0% / 0%** |
| mla_short_long_refs | paste | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 0% |  |  |  | **0% / 0%** |
| mla_short_long_refs | paste_word | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 0% |  |  |  | **0% / 0%** |
| mla_short_long_refs | docx | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 0% |  |  |  | **0% / 0%** |
| mla_short_long_refs | pdf | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 0% |  |  | 25% / 100% | **0% / 0%** |
| apa_bold_abstract | paste | 6 | 0% / 100% |  | 0% / 80% | 0% / 1% | 0% / 100% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_bold_abstract | paste_word | 6 | 0% / 100% |  | 0% / 0% | 0% / 1% | 0% / 81% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_bold_abstract | docx | 6 | 0% / 100% |  | 0% / 80% | 0% / 1% | 0% / 100% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_bold_abstract | pdf | 6 | 0% / 0% |  | 0% / 0% | 0% / 0% | 0% / 75% | 100% / 100% |  |  | 0% / 100% | **0% / 0%** |
| markdown_apa | paste | 6 | 0% / 100% |  | 0% / 65% | 0% / 1% | 0% / 100% | 0% / 100% |  |  |  | **0% / 0%** |
| markdown_apa | paste_word | 6 | 0% / 100% |  | 0% / 0% | 0% / 1% | 0% / 81% | 0% / 100% |  |  |  | **0% / 0%** |
| markdown_apa | docx | 6 | 0% / 100% |  | 0% / 65% | 0% / 1% | 0% / 100% | 0% / 100% |  |  |  | **0% / 0%** |
| markdown_apa | pdf | 6 | 0% / 0% |  | 0% / 0% | 0% / 0% | 0% / 74% | 0% / 100% |  |  | 0% / 100% | **0% / 0%** |
| neg_abstract_word | paste | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| neg_abstract_word | paste_word | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| neg_abstract_word | docx | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| neg_abstract_word | pdf | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 33% |  |  | 0% / 100% | **0% / 0%** |
| neg_references_sentence | paste | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| neg_references_sentence | paste_word | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| neg_references_sentence | docx | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| neg_references_sentence | pdf | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 16% |  |  | 0% / 100% | **0% / 0%** |
| neg_sermon_prayer | paste | 6 |  | 0% / 100% | 0% / 100% |  |  |  |  |  |  | **0% / 0%** |
| neg_sermon_prayer | paste_word | 6 |  | 0% / 100% | 0% / 100% |  |  |  |  |  |  | **0% / 0%** |
| neg_sermon_prayer | docx | 6 |  | 0% / 100% | 0% / 100% |  |  |  |  |  |  | **0% / 0%** |
| neg_sermon_prayer | pdf | 6 |  | 0% / 100% | 0% / 100% |  |  |  |  |  | 0% / 100% | **0% / 0%** |
| neg_letter | paste | 6 |  | 0% / 100% |  |  |  |  |  |  |  | **0% / 0%** |
| neg_letter | paste_word | 6 |  | 0% / 100% |  |  |  |  |  |  |  | **0% / 0%** |
| neg_letter | docx | 6 |  | 0% / 100% |  |  |  |  |  |  |  | **0% / 0%** |
| neg_letter | pdf | 6 |  | 0% / 100% |  |  |  |  |  |  | 0% / 100% | **0% / 0%** |
| prose | paste | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose | paste_word | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose | docx | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose | pdf | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_short | paste | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_short | paste_word | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_short | docx | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_short | pdf | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_abstract_word | paste | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_abstract_word | paste_word | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_abstract_word | docx | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_abstract_word | pdf | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_references_sentence | paste | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_references_sentence | paste_word | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_references_sentence | docx | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_references_sentence | pdf | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_sermon_prayer | paste | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_sermon_prayer | paste_word | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_sermon_prayer | docx | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_sermon_prayer | pdf | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_letter | paste | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_letter | paste_word | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_letter | docx | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_letter | pdf | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |

#### Reading change (deviation with the parts minus the same prose alone, same input type)

| Variant | Input | n | mean change off / on | range on | within 0.01 on | band up off / on |
|---|---|---|---|---|---|---|
| mla | paste | 6 | +0.032 / +0.000 | +0.000 to +0.000 | 6 | 2 / 0 |
| mla | paste_word | 6 | -0.006 / +0.000 | +0.000 to +0.000 | 6 | 0 / 0 |
| mla | docx | 6 | +0.032 / +0.000 | +0.000 to +0.000 | 6 | 2 / 0 |
| mla | pdf | 6 | +0.024 / +0.057 | -0.011 to +0.120 | 1 | 3 / 4 |
| apa_student | paste | 6 | +0.029 / +0.019 | -0.012 to +0.042 | 1 | 3 / 2 |
| apa_student | paste_word | 6 | -0.023 / -0.026 | -0.115 to +0.004 | 3 | 0 / 0 |
| apa_student | docx | 6 | +0.029 / +0.019 | -0.012 to +0.042 | 1 | 3 / 2 |
| apa_student | pdf | 6 | -0.013 / -0.011 | -0.055 to +0.005 | 4 | 0 / 0 |
| apa_professional | paste | 6 | +0.026 / +0.017 | -0.011 to +0.056 | 1 | 2 / 1 |
| apa_professional | paste_word | 6 | -0.022 / -0.026 | -0.115 to +0.009 | 3 | 0 / 0 |
| apa_professional | docx | 6 | +0.026 / +0.017 | -0.011 to +0.056 | 1 | 2 / 1 |
| apa_professional | pdf | 6 | +0.010 / +0.006 | -0.033 to +0.029 | 2 | 0 / 0 |
| turabian | paste | 6 | +0.038 / +0.034 | +0.012 to +0.049 | 0 | 3 / 2 |
| turabian | paste_word | 6 | -0.003 / +0.001 | -0.006 to +0.008 | 6 | 0 / 0 |
| turabian | docx | 6 | +0.038 / -0.002 | -0.015 to +0.000 | 5 | 3 / 0 |
| turabian | pdf | 6 | -0.003 / +0.112 | +0.050 to +0.156 | 0 | 0 / 4 |
| turabian_appendix | paste | 6 | +0.038 / +0.034 | +0.009 to +0.052 | 1 | 3 / 2 |
| turabian_appendix | paste_word | 6 | -0.003 / +0.001 | -0.006 to +0.005 | 6 | 0 / 0 |
| turabian_appendix | docx | 6 | +0.038 / -0.002 | -0.015 to +0.000 | 5 | 3 / 0 |
| turabian_appendix | pdf | 6 | -0.002 / +0.078 | +0.013 to +0.129 | 0 | 0 / 4 |
| apa_reference_list | paste | 6 | +0.121 / +0.112 | +0.074 to +0.132 | 0 | 4 / 4 |
| apa_reference_list | paste_word | 6 | +0.083 / +0.079 | +0.051 to +0.132 | 0 | 1 / 1 |
| apa_reference_list | docx | 6 | +0.121 / +0.112 | +0.074 to +0.132 | 0 | 4 / 4 |
| apa_reference_list | pdf | 6 | +0.101 / +0.102 | +0.045 to +0.139 | 0 | 4 / 4 |
| apa_literature_cited | paste | 6 | +0.124 / +0.114 | +0.073 to +0.138 | 0 | 4 / 4 |
| apa_literature_cited | paste_word | 6 | +0.087 / +0.082 | +0.053 to +0.133 | 0 | 1 / 1 |
| apa_literature_cited | docx | 6 | +0.124 / +0.114 | +0.073 to +0.138 | 0 | 4 / 4 |
| apa_literature_cited | pdf | 6 | +0.107 / +0.107 | +0.056 to +0.140 | 0 | 4 / 4 |
| mla_unheaded_refs | paste | 6 | +0.108 / +0.100 | +0.073 to +0.121 | 0 | 4 / 4 |
| mla_unheaded_refs | paste_word | 6 | +0.067 / +0.065 | +0.044 to +0.104 | 0 | 1 / 1 |
| mla_unheaded_refs | docx | 6 | +0.108 / +0.100 | +0.073 to +0.121 | 0 | 4 / 4 |
| mla_unheaded_refs | pdf | 6 | +0.082 / +0.080 | +0.011 to +0.120 | 0 | 4 / 4 |
| mla_short_long_refs | paste | 6 | +0.022 / +0.120 | +0.075 to +0.219 | 0 | 1 / 5 |
| mla_short_long_refs | paste_word | 6 | +0.001 / +0.127 | +0.072 to +0.206 | 0 | 1 / 6 |
| mla_short_long_refs | docx | 6 | +0.022 / +0.120 | +0.075 to +0.219 | 0 | 1 / 5 |
| mla_short_long_refs | pdf | 6 | +0.012 / +0.132 | +0.079 to +0.215 | 0 | 1 / 4 |
| apa_bold_abstract | paste | 6 | +0.029 / +0.019 | -0.012 to +0.042 | 1 | 3 / 2 |
| apa_bold_abstract | paste_word | 6 | -0.023 / -0.026 | -0.115 to +0.004 | 3 | 0 / 0 |
| apa_bold_abstract | docx | 6 | +0.029 / +0.019 | -0.012 to +0.042 | 1 | 3 / 2 |
| apa_bold_abstract | pdf | 6 | -0.013 / -0.011 | -0.055 to +0.005 | 4 | 0 / 0 |
| markdown_apa | paste | 6 | +0.128 / +0.017 | -0.011 to +0.044 | 2 | 4 / 2 |
| markdown_apa | paste_word | 6 | +0.089 / -0.028 | -0.113 to +0.001 | 3 | 1 / 0 |
| markdown_apa | docx | 6 | +0.128 / +0.017 | -0.011 to +0.044 | 2 | 4 / 2 |
| markdown_apa | pdf | 6 | +0.111 / -0.015 | -0.054 to +0.000 | 3 | 4 / 0 |
| neg_abstract_word | paste | 6 | +0.036 / +0.000 | +0.000 to +0.000 | 6 | 2 / 0 |
| neg_abstract_word | paste_word | 6 | -0.006 / +0.000 | +0.000 to +0.000 | 6 | 0 / 0 |
| neg_abstract_word | docx | 6 | +0.036 / +0.000 | +0.000 to +0.000 | 6 | 2 / 0 |
| neg_abstract_word | pdf | 6 | +0.026 / +0.047 | -0.013 to +0.120 | 1 | 3 / 3 |
| neg_references_sentence | paste | 6 | +0.035 / +0.000 | +0.000 to +0.000 | 6 | 2 / 0 |
| neg_references_sentence | paste_word | 6 | -0.005 / +0.000 | +0.000 to +0.000 | 6 | 0 / 0 |
| neg_references_sentence | docx | 6 | +0.035 / +0.000 | +0.000 to +0.000 | 6 | 2 / 0 |
| neg_references_sentence | pdf | 6 | +0.023 / +0.048 | -0.012 to +0.111 | 1 | 2 / 3 |
| neg_sermon_prayer | paste | 6 | +0.001 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| neg_sermon_prayer | paste_word | 6 | -0.004 / +0.000 | +0.000 to +0.000 | 6 | 0 / 0 |
| neg_sermon_prayer | docx | 6 | +0.001 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| neg_sermon_prayer | pdf | 6 | -0.000 / +0.004 | -0.010 to +0.013 | 5 | 0 / 0 |
| neg_letter | paste | 6 | +0.002 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| neg_letter | paste_word | 6 | -0.002 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| neg_letter | docx | 6 | +0.002 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| neg_letter | pdf | 6 | +0.001 / +0.002 | -0.002 to +0.010 | 6 | 0 / 0 |

#### Lost in extraction (share of each part's source characters not found in the extracted text)

| Input | abstract | appendix | footnote | heading_block | note_marker | notes | page_header | prose | references | section_heading | title | title_page | unattributed chars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| paste | 0% | 0% |  | 0% | 0% | 0% |  | 0% | 0% | 0% | 0% | 0% | 0 |
| paste_word | 0% | 0% |  | 0% | 0% | 0% |  | 0% | 0% | 0% | 0% | 0% | 0 |
| docx | 0% | 0% | 100% | 0% | 100% |  | 100% | 0% | 0% | 0% | 0% | 0% | 0 |
| pdf | 0% | 0% | 0% | 0% | 0% |  | 0% | 0% | 0% | 0% | 0% | 0% | 0 |
<!-- /tables:dev -->

## After steps 2, 3 and 6 (dev)

Steps 2, 3 and 6 of the parts plan, as revised after the score-integrity
review:

- **Uploads store page markers.** The extractor returns exactly the text it
  returned before, plus a page marker (U+001F, alone on a line) where the file
  breaks a page: one mark for a .docx page or section break, two between PDF
  pages, and a PDF tag (a newline and three marks) at the end of every PDF
  with text, so a one-page PDF is known as a PDF too. Nothing else in the
  stored text changes, whatever the switch says.
  Every measurement, the raw-text experts and every duplicate hash drop the
  marker first. A form feed a teacher pasted is ordinary text, measured as
  before.
- **The matter rules** (`features/matter.py`) gained the title page, abstract,
  notes, appendix and unheaded-list rules, and read the page markers.
- **A PDF is cleaned up only when it is measured with the splitter on**: the
  rules set aside its running heads, page numbers and footnote blocks in the
  raw text, and `features/pdf_reflow.py` rejoins the hard-wrapped lines of
  what is left into paragraphs. So the `v1` and `matter` measurements of the
  same stored paper always come from the same text.
- **Papers stored before page markers existed** carry none: the rules then
  work from the text alone (no title-page-by-page-break, no page-bottom
  footnote rule, no reflow), which is how they read pasted text.
- **Score risk: upload date.** The original file bytes are not kept, so this
  cannot be repaired after the fact. With the switch on, a student whose past
  papers are PDFs stored before page markers existed is measured on those
  papers without page rules or reflow, while a new PDF upload gets both: the
  two sides of the comparison are then cut differently, and the reading can
  move for that reason alone. The remedy is to upload those past papers
  again. (Switch off, nothing differs.)
- **The length match** cuts what the reading cuts.

Rebuilt with:

```bash
.venv/bin/python validation/diagnostics/document_parts_v2/make_cases.py --reextract   # cases_after.jsonl.xz (needs LibreOffice)
.venv/bin/python -I validation/diagnostics/document_parts_v2/run.py --after           # summary_dev_after.json, rows_dev_after.json
```

`cases_after.jsonl.xz` is the same set read by today's extractor: pasted
records unchanged, each .docx/.pdf record's `text` the extraction with page
markers. `cases.jsonl.xz` and the "before" results above are untouched. The
rules were tuned on this dev split, so these are not out-of-sample numbers;
the hold-out has not been run against them.

**Byte identity.** All 504 switch-off rows (every dev paper, every input type)
score exactly as before: same deviation to the last bit, same action. All
756 extracted texts (both splits), with their page markers dropped, are byte
for byte the texts in `cases.jsonl.xz`.

**Segmentation, splitter on, before / after.** Share of each part's
characters set aside; last column: share of the true prose set aside.

| Format | Input | n | title page | heading block | title | abstract | section headings | references | notes | appendix | running head | prose set aside |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MLA | paste | 42 |  | 100% / 100% | 100% / 100% |  |  | 46% / 100% |  |  |  | **0% / 0%** |
| MLA | paste_word | 42 |  | 100% / 100% | 100% / 100% |  |  | 46% / 100% |  |  |  | **0% / 0%** |
| MLA | docx | 42 |  | 100% / 100% | 100% / 100% |  |  | 46% / 100% |  |  |  | **0% / 0%** |
| MLA | pdf | 42 |  | 100% / 100% | 100% / 100% |  |  | 10% / 100% |  |  | 100% / 100% | **0% / 0%** |
| APA | paste | 36 | 72% / 100% |  | 78% / 100% | 1% / 100% | 100% / 100% | 67% / 100% |  |  |  | **0% / 0%** |
| APA | paste_word | 36 | 64% / 100% |  | 0% / 100% | 1% / 100% | 81% / 94% | 67% / 100% |  |  |  | **0% / 0%** |
| APA | docx | 36 | 72% / 100% |  | 78% / 100% | 1% / 100% | 100% / 100% | 67% / 100% |  |  |  | **0% / 0%** |
| APA | pdf | 36 | 0% / 100% |  | 0% / 100% | 0% / 100% | 75% / 94% | 66% / 100% |  |  | 30% / 100% | **0% / 0%** |
| Turabian | paste | 12 | 96% / 100% |  |  |  |  | 100% / 100% | 49% / 100% | 100% / 1% |  | **0% / 0%** |
| Turabian | paste_word | 12 | 12% / 100% |  |  |  |  | 100% / 100% | 47% / 100% | 100% / 1% |  | **0% / 0%** |
| Turabian | docx | 12 | 96% / 100% |  |  |  |  | 100% / 100% |  | 100% / 1% |  | **0% / 0%** |
| Turabian | pdf | 12 | 12% / 100% |  |  |  |  | 0% / 100% | 16% / 94% | 0% / 0% | 100% / 100% | **0% / 0%** |
| prose only | paste | 36 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose only | paste_word | 36 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose only | docx | 36 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose only | pdf | 36 |  |  |  |  |  |  |  |  |  | **0% / 0%** |

Notes on the table:

- Appendix: lower is the intended result. The appendix is the author's own
  prose, and the list of sources now ends at its heading, so at most the
  "Appendix A" heading is set aside; before, the whole appendix went with the
  list.
- MLA references "before" 46% pools `mla_short_long_refs` and
  `mla_unheaded_refs` (0% each) with lists that were found; Turabian notes'
  "before" 49% (pasted) was 27-64% per paper.
- Turabian PDF notes at 94%: the one note missed (edwards, both variants) has
  its marker run into a paragraph number ("5.1 And"), which the rules read as
  a reference (like "Romans 8.1") and leave as prose.
- Section headings at 94%: the misses are headings whose preceding line does
  not end a sentence (a paragraph ending in a colon before a quotation),
  which the rules leave as prose on purpose.
- On the dev split, only that one footnote is listed as `possible`.

**Reading, splitter on.** Every variant except `turabian_appendix` now reads
within 0.0024 of its prose alone, for all 6 papers in every input type
(exactly 0 for most; james's APA variants +0.0003 to +0.0006, the one
section heading left as prose; edwards's Turabian PDF +0.0024, the one
footnote left as prose). Before: up to +0.219, and 28 of 66 paper-variants
up a band with a blank-line paste, 28 of 66 as a PDF; after: 0 up.
`turabian_appendix` reads -0.066 to +0.004 against the prose alone, 2 of 6
down a band with a single-newline paste: that is the appendix being
measured, not a part leaking in (the prose alone has no appendix). The
negative controls read exactly as their prose alone in every input type, PDF
included (before: +0.047 and +0.048 as PDFs).

**Input type.** With the splitter on, the same prose as a PDF now reads as the
blank-line paste (0.000 on 5 of 6, -0.001 on one; before -0.040 to +0.051),
because the reflowed PDF has the same paragraphs. The single-newline paste
still reads +0.022 to +0.063 above the blank-line paste in both settings: that
finding is not addressed here (see "Paragraph breaks" below).

<!-- tables:dev_after -->
Each cell: share of that part's characters set aside, splitter **off / on**; last column: share of the true prose set aside (false set-aside), off / on. Non-whitespace characters, pooled over the n papers in the row.

#### By format

| Format | Input | n | title page | heading block | title | abstract | section headings | references | notes | appendix | running head | **prose set aside** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MLA | paste | 42 |  | 0% / 100% | 0% / 100% |  |  | 85% / 100% |  |  |  | **0% / 0%** |
| MLA | paste_word | 42 |  | 0% / 100% | 0% / 100% |  |  | 85% / 100% |  |  |  | **0% / 0%** |
| MLA | docx | 42 |  | 0% / 100% | 0% / 100% |  |  | 85% / 100% |  |  |  | **0% / 0%** |
| MLA | pdf | 42 |  | 0% / 100% | 0% / 100% |  |  | 85% / 100% |  |  | 3% / 100% | **0% / 0%** |
| APA | paste | 36 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 100% | 49% / 100% |  |  |  | **0% / 0%** |
| APA | paste_word | 36 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 94% | 49% / 100% |  |  |  | **0% / 0%** |
| APA | docx | 36 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 100% | 49% / 100% |  |  |  | **0% / 0%** |
| APA | pdf | 36 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 94% | 49% / 100% |  |  | 0% / 100% | **0% / 0%** |
| Turabian | paste | 12 | 0% / 100% |  |  |  |  | 100% / 100% | 100% / 100% | 100% / 1% |  | **0% / 0%** |
| Turabian | paste_word | 12 | 0% / 100% |  |  |  |  | 100% / 100% | 100% / 100% | 100% / 1% |  | **0% / 0%** |
| Turabian | docx | 12 | 0% / 100% |  |  |  |  | 100% / 100% |  | 100% / 1% |  | **0% / 0%** |
| Turabian | pdf | 12 | 0% / 100% |  |  |  |  | 100% / 100% | 0% / 94% | 100% / 0% | 21% / 100% | **0% / 0%** |
| prose only | paste | 36 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose only | paste_word | 36 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose only | docx | 36 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose only | pdf | 36 |  |  |  |  |  |  |  |  |  | **0% / 0%** |

#### By variant

| Variant | Input | n | title page | heading block | title | abstract | section headings | references | notes | appendix | running head | **prose set aside** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| mla | paste | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| mla | paste_word | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| mla | docx | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| mla | pdf | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  | 0% / 100% | **0% / 0%** |
| apa_student | paste | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 100% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_student | paste_word | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 94% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_student | docx | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 100% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_student | pdf | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 94% | 100% / 100% |  |  | 0% / 100% | **0% / 0%** |
| apa_professional | paste | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 100% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_professional | paste_word | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 94% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_professional | docx | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 100% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_professional | pdf | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 94% | 100% / 100% |  |  | 0% / 100% | **0% / 0%** |
| turabian | paste | 6 | 0% / 100% |  |  |  |  | 100% / 100% | 100% / 100% |  |  | **0% / 0%** |
| turabian | paste_word | 6 | 0% / 100% |  |  |  |  | 100% / 100% | 100% / 100% |  |  | **0% / 0%** |
| turabian | docx | 6 | 0% / 100% |  |  |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| turabian | pdf | 6 | 0% / 100% |  |  |  |  | 100% / 100% | 0% / 93% |  | 14% / 100% | **0% / 0%** |
| turabian_appendix | paste | 6 | 0% / 100% |  |  |  |  | 100% / 100% | 100% / 100% | 100% / 1% |  | **0% / 0%** |
| turabian_appendix | paste_word | 6 | 0% / 100% |  |  |  |  | 100% / 100% | 100% / 100% | 100% / 1% |  | **0% / 0%** |
| turabian_appendix | docx | 6 | 0% / 100% |  |  |  |  | 100% / 100% |  | 100% / 1% |  | **0% / 0%** |
| turabian_appendix | pdf | 6 | 0% / 100% |  |  |  |  | 100% / 100% | 0% / 94% | 100% / 0% | 27% / 100% | **0% / 0%** |
| apa_reference_list | paste | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 100% | 0% / 100% |  |  |  | **0% / 0%** |
| apa_reference_list | paste_word | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 94% | 0% / 100% |  |  |  | **0% / 0%** |
| apa_reference_list | docx | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 100% | 0% / 100% |  |  |  | **0% / 0%** |
| apa_reference_list | pdf | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 94% | 0% / 100% |  |  | 0% / 100% | **0% / 0%** |
| apa_literature_cited | paste | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 100% | 0% / 100% |  |  |  | **0% / 0%** |
| apa_literature_cited | paste_word | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 94% | 0% / 100% |  |  |  | **0% / 0%** |
| apa_literature_cited | docx | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 100% | 0% / 100% |  |  |  | **0% / 0%** |
| apa_literature_cited | pdf | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 94% | 0% / 100% |  |  | 0% / 100% | **0% / 0%** |
| mla_unheaded_refs | paste | 6 |  | 0% / 100% | 0% / 100% |  |  | 0% / 100% |  |  |  | **0% / 0%** |
| mla_unheaded_refs | paste_word | 6 |  | 0% / 100% | 0% / 100% |  |  | 0% / 100% |  |  |  | **0% / 0%** |
| mla_unheaded_refs | docx | 6 |  | 0% / 100% | 0% / 100% |  |  | 0% / 100% |  |  |  | **0% / 0%** |
| mla_unheaded_refs | pdf | 6 |  | 0% / 100% | 0% / 100% |  |  | 0% / 100% |  |  | 0% / 100% | **0% / 0%** |
| mla_short_long_refs | paste | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| mla_short_long_refs | paste_word | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| mla_short_long_refs | docx | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| mla_short_long_refs | pdf | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  | 25% / 100% | **0% / 0%** |
| apa_bold_abstract | paste | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 100% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_bold_abstract | paste_word | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 94% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_bold_abstract | docx | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 100% | 100% / 100% |  |  |  | **0% / 0%** |
| apa_bold_abstract | pdf | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 94% | 100% / 100% |  |  | 0% / 100% | **0% / 0%** |
| markdown_apa | paste | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 100% | 0% / 100% |  |  |  | **0% / 0%** |
| markdown_apa | paste_word | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 94% | 0% / 100% |  |  |  | **0% / 0%** |
| markdown_apa | docx | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 100% | 0% / 100% |  |  |  | **0% / 0%** |
| markdown_apa | pdf | 6 | 0% / 100% |  | 0% / 100% | 0% / 100% | 0% / 94% | 0% / 100% |  |  | 0% / 100% | **0% / 0%** |
| neg_abstract_word | paste | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| neg_abstract_word | paste_word | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| neg_abstract_word | docx | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| neg_abstract_word | pdf | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  | 0% / 100% | **0% / 0%** |
| neg_references_sentence | paste | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| neg_references_sentence | paste_word | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| neg_references_sentence | docx | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  |  | **0% / 0%** |
| neg_references_sentence | pdf | 6 |  | 0% / 100% | 0% / 100% |  |  | 100% / 100% |  |  | 0% / 100% | **0% / 0%** |
| neg_sermon_prayer | paste | 6 |  | 0% / 100% | 0% / 100% |  |  |  |  |  |  | **0% / 0%** |
| neg_sermon_prayer | paste_word | 6 |  | 0% / 100% | 0% / 100% |  |  |  |  |  |  | **0% / 0%** |
| neg_sermon_prayer | docx | 6 |  | 0% / 100% | 0% / 100% |  |  |  |  |  |  | **0% / 0%** |
| neg_sermon_prayer | pdf | 6 |  | 0% / 100% | 0% / 100% |  |  |  |  |  | 0% / 100% | **0% / 0%** |
| neg_letter | paste | 6 |  | 0% / 100% |  |  |  |  |  |  |  | **0% / 0%** |
| neg_letter | paste_word | 6 |  | 0% / 100% |  |  |  |  |  |  |  | **0% / 0%** |
| neg_letter | docx | 6 |  | 0% / 100% |  |  |  |  |  |  |  | **0% / 0%** |
| neg_letter | pdf | 6 |  | 0% / 100% |  |  |  |  |  |  | 0% / 100% | **0% / 0%** |
| prose | paste | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose | paste_word | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose | docx | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose | pdf | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_short | paste | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_short | paste_word | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_short | docx | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_short | pdf | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_abstract_word | paste | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_abstract_word | paste_word | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_abstract_word | docx | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_abstract_word | pdf | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_references_sentence | paste | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_references_sentence | paste_word | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_references_sentence | docx | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_references_sentence | pdf | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_sermon_prayer | paste | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_sermon_prayer | paste_word | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_sermon_prayer | docx | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_sermon_prayer | pdf | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_letter | paste | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_letter | paste_word | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_letter | docx | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |
| prose_letter | pdf | 6 |  |  |  |  |  |  |  |  |  | **0% / 0%** |

#### Reading change (deviation with the parts minus the same prose alone, same input type)

| Variant | Input | n | mean change off / on | range on | within 0.01 on | band up off / on |
|---|---|---|---|---|---|---|
| mla | paste | 6 | +0.032 / +0.000 | +0.000 to +0.000 | 6 | 2 / 0 |
| mla | paste_word | 6 | -0.006 / +0.000 | +0.000 to +0.000 | 6 | 0 / 0 |
| mla | docx | 6 | +0.032 / +0.000 | +0.000 to +0.000 | 6 | 2 / 0 |
| mla | pdf | 6 | +0.024 / +0.000 | +0.000 to +0.000 | 6 | 3 / 0 |
| apa_student | paste | 6 | +0.029 / +0.000 | +0.000 to +0.000 | 6 | 3 / 0 |
| apa_student | paste_word | 6 | -0.023 / +0.000 | +0.000 to +0.000 | 6 | 0 / 0 |
| apa_student | docx | 6 | +0.029 / +0.000 | +0.000 to +0.000 | 6 | 3 / 0 |
| apa_student | pdf | 6 | -0.013 / +0.000 | +0.000 to +0.001 | 6 | 0 / 0 |
| apa_professional | paste | 6 | +0.026 / +0.000 | +0.000 to +0.000 | 6 | 2 / 0 |
| apa_professional | paste_word | 6 | -0.022 / +0.000 | +0.000 to +0.000 | 6 | 0 / 0 |
| apa_professional | docx | 6 | +0.026 / +0.000 | +0.000 to +0.000 | 6 | 2 / 0 |
| apa_professional | pdf | 6 | +0.010 / +0.000 | +0.000 to +0.001 | 6 | 0 / 0 |
| turabian | paste | 6 | +0.038 / +0.000 | +0.000 to +0.000 | 6 | 3 / 0 |
| turabian | paste_word | 6 | -0.003 / +0.000 | +0.000 to +0.000 | 6 | 0 / 0 |
| turabian | docx | 6 | +0.038 / +0.000 | +0.000 to +0.000 | 6 | 3 / 0 |
| turabian | pdf | 6 | -0.003 / +0.000 | +0.000 to +0.002 | 6 | 0 / 0 |
| turabian_appendix | paste | 6 | +0.038 / -0.014 | -0.049 to -0.002 | 3 | 3 / 0 |
| turabian_appendix | paste_word | 6 | -0.003 / -0.009 | -0.017 to +0.000 | 3 | 0 / 0 |
| turabian_appendix | docx | 6 | +0.038 / -0.014 | -0.049 to -0.002 | 3 | 3 / 0 |
| turabian_appendix | pdf | 6 | -0.002 / -0.018 | -0.066 to +0.004 | 3 | 0 / 0 |
| apa_reference_list | paste | 6 | +0.121 / +0.000 | +0.000 to +0.000 | 6 | 4 / 0 |
| apa_reference_list | paste_word | 6 | +0.083 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| apa_reference_list | docx | 6 | +0.121 / +0.000 | +0.000 to +0.000 | 6 | 4 / 0 |
| apa_reference_list | pdf | 6 | +0.101 / +0.000 | +0.000 to +0.001 | 6 | 4 / 0 |
| apa_literature_cited | paste | 6 | +0.124 / +0.000 | +0.000 to +0.000 | 6 | 4 / 0 |
| apa_literature_cited | paste_word | 6 | +0.087 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| apa_literature_cited | docx | 6 | +0.124 / +0.000 | +0.000 to +0.000 | 6 | 4 / 0 |
| apa_literature_cited | pdf | 6 | +0.107 / +0.000 | +0.000 to +0.001 | 6 | 4 / 0 |
| mla_unheaded_refs | paste | 6 | +0.108 / +0.000 | +0.000 to +0.000 | 6 | 4 / 0 |
| mla_unheaded_refs | paste_word | 6 | +0.067 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| mla_unheaded_refs | docx | 6 | +0.108 / +0.000 | +0.000 to +0.000 | 6 | 4 / 0 |
| mla_unheaded_refs | pdf | 6 | +0.082 / +0.000 | +0.000 to +0.000 | 6 | 4 / 0 |
| mla_short_long_refs | paste | 6 | +0.022 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| mla_short_long_refs | paste_word | 6 | +0.001 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| mla_short_long_refs | docx | 6 | +0.022 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| mla_short_long_refs | pdf | 6 | +0.012 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| apa_bold_abstract | paste | 6 | +0.029 / +0.000 | +0.000 to +0.000 | 6 | 3 / 0 |
| apa_bold_abstract | paste_word | 6 | -0.023 / +0.000 | +0.000 to +0.000 | 6 | 0 / 0 |
| apa_bold_abstract | docx | 6 | +0.029 / +0.000 | +0.000 to +0.000 | 6 | 3 / 0 |
| apa_bold_abstract | pdf | 6 | -0.013 / +0.000 | +0.000 to +0.001 | 6 | 0 / 0 |
| markdown_apa | paste | 6 | +0.128 / +0.000 | +0.000 to +0.000 | 6 | 4 / 0 |
| markdown_apa | paste_word | 6 | +0.089 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| markdown_apa | docx | 6 | +0.128 / +0.000 | +0.000 to +0.000 | 6 | 4 / 0 |
| markdown_apa | pdf | 6 | +0.111 / +0.000 | +0.000 to +0.001 | 6 | 4 / 0 |
| neg_abstract_word | paste | 6 | +0.036 / +0.000 | +0.000 to +0.000 | 6 | 2 / 0 |
| neg_abstract_word | paste_word | 6 | -0.006 / +0.000 | +0.000 to +0.000 | 6 | 0 / 0 |
| neg_abstract_word | docx | 6 | +0.036 / +0.000 | +0.000 to +0.000 | 6 | 2 / 0 |
| neg_abstract_word | pdf | 6 | +0.026 / +0.000 | +0.000 to +0.000 | 6 | 3 / 0 |
| neg_references_sentence | paste | 6 | +0.035 / +0.000 | +0.000 to +0.000 | 6 | 2 / 0 |
| neg_references_sentence | paste_word | 6 | -0.005 / +0.000 | +0.000 to +0.000 | 6 | 0 / 0 |
| neg_references_sentence | docx | 6 | +0.035 / +0.000 | +0.000 to +0.000 | 6 | 2 / 0 |
| neg_references_sentence | pdf | 6 | +0.023 / +0.000 | +0.000 to +0.000 | 6 | 2 / 0 |
| neg_sermon_prayer | paste | 6 | +0.001 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| neg_sermon_prayer | paste_word | 6 | -0.004 / +0.000 | +0.000 to +0.000 | 6 | 0 / 0 |
| neg_sermon_prayer | docx | 6 | +0.001 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| neg_sermon_prayer | pdf | 6 | -0.000 / +0.000 | +0.000 to +0.000 | 6 | 0 / 0 |
| neg_letter | paste | 6 | +0.002 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| neg_letter | paste_word | 6 | -0.002 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| neg_letter | docx | 6 | +0.002 / +0.000 | +0.000 to +0.000 | 6 | 1 / 0 |
| neg_letter | pdf | 6 | +0.001 / +0.000 | +0.000 to +0.000 | 6 | 0 / 0 |

#### Lost in extraction (share of each part's source characters not found in the extracted text)

| Input | abstract | appendix | footnote | heading_block | note_marker | notes | page_header | prose | references | section_heading | title | title_page | unattributed chars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| paste | 0% | 0% |  | 0% | 0% | 0% |  | 0% | 0% | 0% | 0% | 0% | 0 |
| paste_word | 0% | 0% |  | 0% | 0% | 0% |  | 0% | 0% | 0% | 0% | 0% | 0 |
| docx | 0% | 0% | 100% | 0% | 100% |  | 100% | 0% | 0% | 0% | 0% | 0% | 0 |
| pdf | 0% | 0% | 0% | 0% | 0% |  | 0% | 0% | 0% | 0% | 0% | 0% | 0 |

#### Listed as possible, splitter on (measured as prose, shown to the teacher)

Share of each part's characters, and of the true prose, inside a `possible` range and not set aside.

| Format | Input | n | title page | heading block | title | abstract | section headings | references | notes | appendix | running head | prose |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MLA | paste | 42 |  | 0% | 0% |  |  | 0% |  |  |  | 0% |
| MLA | paste_word | 42 |  | 0% | 0% |  |  | 0% |  |  |  | 0% |
| MLA | docx | 42 |  | 0% | 0% |  |  | 0% |  |  |  | 0% |
| MLA | pdf | 42 |  | 0% | 0% |  |  | 0% |  |  | 0% | 0% |
| APA | paste | 36 | 0% |  | 0% | 0% | 0% | 0% |  |  |  | 0% |
| APA | paste_word | 36 | 0% |  | 0% | 0% | 0% | 0% |  |  |  | 0% |
| APA | docx | 36 | 0% |  | 0% | 0% | 0% | 0% |  |  |  | 0% |
| APA | pdf | 36 | 0% |  | 0% | 0% | 0% | 0% |  |  | 0% | 0% |
| Turabian | paste | 12 | 0% |  |  |  |  | 0% | 0% | 0% |  | 0% |
| Turabian | paste_word | 12 | 0% |  |  |  |  | 0% | 0% | 0% |  | 0% |
| Turabian | docx | 12 | 0% |  |  |  |  | 0% |  | 0% |  | 0% |
| Turabian | pdf | 12 | 0% |  |  |  |  | 0% | 6% | 0% | 0% | 0% |
| prose only | paste | 36 |  |  |  |  |  |  |  |  |  | 0% |
| prose only | paste_word | 36 |  |  |  |  |  |  |  |  |  | 0% |
| prose only | docx | 36 |  |  |  |  |  |  |  |  |  | 0% |
| prose only | pdf | 36 |  |  |  |  |  |  |  |  |  | 0% |
<!-- /tables:dev_after -->

## Paragraph breaks (dev)

**Diagnostic, dev split only, published prose, not student writing; n = 6 papers
per row.** The hold-out was not run or opened for this.

**Root cause.** Every paragraph reader splits at blank lines
(`features/tier1.py:_split_paragraphs`, which feeds `TextDoc.paragraphs`;
`tension_arc.py:_split_paragraphs`; `preprocess.py`'s per-paragraph citation
counts). A paste with one newline between paragraphs has no blank line, so the
whole paper is one paragraph. Feature-vector diff of the dev `prose` papers,
single-newline minus blank-line paste (`v1`): `avg_paragraph_length`
(tier2.py:237, 6 of 6, +0.27 to +0.93), `paragraph_topic_position`
(tier2.py:205, 6 of 6, -0.14 to -0.58), `transition_predictability`
(tier7.py:175, 6 of 6, +0.05 to +0.44), `metric_flatness_score`
(prosodic.py:224, 6 of 6, -0.34 to +0.16), `catastrophe_index`
(tension_arc.py:269 via pipeline.py:79, 1 of 6, -0.83) and
`error_topology_consistency` (prosodic.py:335, 1 of 6, +0.35). Nothing else
moves.

**The fix: a new measurement, `para`** (`PARAGRAPH_BREAKS_ENABLED`, off by
default; ids `para`, `fs2+para`, `matter+para`, `fs2+matter+para`, ADR-014).
`original/features/paragraphs.py`: a measured body with no blank line at all
whose paragraph-length lines (25 or more words, ending a sentence or a colon,
with closing quotes, dashes or a note number allowed after it) hold at least
75% of its words has each line break read as a paragraph break; anything else
is measured unchanged. The rule was tuned on this dev split (the colon and
note-number endings were added after james's prose, whose quotations are
introduced by ":" plus a dash, failed the first version at 69% of its words),
so these are not out-of-sample numbers.

**Result.** With `para` (or `matter+para`) the single-newline paste reads
exactly as the blank-line paste: +0.000 for all 6 papers in `prose` and
`prose_short` (before: +0.022 to +0.063 and +0.004 to +0.051), and no band
change (before: 3 of 6 up, douglass and james to "monitor", edwards to
"schedule a conversation"). Every other variant: +0.000 under `para`, and
-0.001 to +0.000 under `matter+para` (the APA variants, where the splitter
removing a heading leaves one more blank line in the blank-line paste than in
the other). The blank-line paste, .docx and PDF read identically, to the last
bit and the same action, under `para` as under `v1` and under `matter+para` as
under `matter` (126 of 126 papers each). The `v1` and `matter` rows of this run
equal `rows_dev_after.json` (made before this measurement existed) for all
1008 rows. n = 6 throughout: the band counts are **uninformative** as rates.
Whether student papers pasted from Word look like this (paragraph-length lines,
no blank lines) and whether any student text is split wrongly is not measured
here.

Nothing here authorises `PARAGRAPH_BREAKS_ENABLED=1`. How often the rule fires on
real student pastes, and how often it splits a real student paste wrongly, is
the number no corpus here can supply, and it is needed before `on`. In the
summary, `commit` is the parent commit (the run predates the commit that added
`para`); `code_hash` is the reliable pin.

Rebuilt with (about 25 minutes on 4 cores; dev only, no hold-out mode):

```bash
.venv/bin/python -I validation/diagnostics/document_parts_v2/run_paragraphs.py   # rows/summary/tables_dev_paragraphs
```

<!-- tables:dev_paragraphs -->
Published prose, not student writing; diagnostic; dev split only; n = 6 papers per row, so band counts show direction, not rates (**uninformative** as proportions).

#### Single-newline paste minus blank-line paste (same paper), per author

| Variant | Measurement | augustine | boethius | douglass | edwards | james | newman | mean | band up / down |
|---|---|---|---|---|---|---|---|---|---|
| prose | v1 | +0.026 | +0.050 | +0.040 (+1 band) | +0.028 (+1 band) | +0.022 (+1 band) | +0.063 | +0.038 | 3 / 0 |
| prose | matter | +0.026 | +0.050 | +0.040 (+1 band) | +0.028 (+1 band) | +0.022 (+1 band) | +0.063 | +0.038 | 3 / 0 |
| prose | para | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | 0 / 0 |
| prose | matter+para | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | 0 / 0 |
| prose_short | v1 | +0.004 | +0.012 | +0.017 | +0.007 | +0.015 | +0.051 | +0.018 | 0 / 0 |
| prose_short | matter | +0.004 | +0.012 | +0.017 | +0.007 | +0.015 | +0.051 | +0.018 | 0 / 0 |
| prose_short | para | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | 0 / 0 |
| prose_short | matter+para | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | +0.000 | 0 / 0 |

#### Single-newline minus blank-line paste, every variant (mean; range; band up / down)

| Variant | v1 | matter | para | matter+para |
|---|---|---|---|---|
| apa_bold_abstract | -0.013; -0.094 to +0.024; 0 / 2 | +0.038; +0.022 to +0.063; 3 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | -0.000; -0.001 to +0.000; 0 / 0 |
| apa_literature_cited | +0.000; -0.022 to +0.014; 0 / 0 | +0.038; +0.022 to +0.063; 3 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | -0.000; -0.001 to +0.000; 0 / 0 |
| apa_professional | -0.010; -0.091 to +0.028; 1 / 1 | +0.038; +0.022 to +0.063; 3 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | -0.000; -0.001 to +0.000; 0 / 0 |
| apa_reference_list | -0.000; -0.023 to +0.015; 0 / 0 | +0.038; +0.022 to +0.063; 3 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | -0.000; -0.001 to +0.000; 0 / 0 |
| apa_student | -0.013; -0.094 to +0.024; 0 / 2 | +0.038; +0.022 to +0.063; 3 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | -0.000; -0.001 to +0.000; 0 / 0 |
| markdown_apa | -0.001; -0.021 to +0.011; 0 / 0 | +0.038; +0.022 to +0.063; 3 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | -0.000; -0.001 to +0.000; 0 / 0 |
| mla | +0.000; -0.019 to +0.022; 1 / 1 | +0.038; +0.022 to +0.063; 3 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 |
| mla_short_long_refs | -0.004; -0.038 to +0.021; 0 / 0 | +0.018; +0.004 to +0.051; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 |
| mla_unheaded_refs | -0.003; -0.024 to +0.009; 0 / 0 | +0.038; +0.022 to +0.063; 3 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 |
| neg_abstract_word | -0.002; -0.024 to +0.022; 0 / 1 | +0.039; +0.021 to +0.065; 2 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 |
| neg_letter | -0.002; -0.023 to +0.019; 1 / 0 | +0.002; -0.015 to +0.021; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 |
| neg_references_sentence | -0.002; -0.022 to +0.021; 0 / 1 | +0.039; +0.020 to +0.063; 2 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 |
| neg_sermon_prayer | -0.006; -0.030 to +0.017; 0 / 2 | -0.001; -0.023 to +0.019; 1 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 |
| prose | +0.038; +0.022 to +0.063; 3 / 0 | +0.038; +0.022 to +0.063; 3 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 |
| prose_abstract_word | +0.039; +0.021 to +0.065; 2 / 0 | +0.039; +0.021 to +0.065; 2 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 |
| prose_letter | +0.002; -0.015 to +0.021; 0 / 0 | +0.002; -0.015 to +0.021; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 |
| prose_references_sentence | +0.039; +0.020 to +0.063; 2 / 0 | +0.039; +0.020 to +0.063; 2 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 |
| prose_sermon_prayer | -0.001; -0.023 to +0.019; 1 / 0 | -0.001; -0.023 to +0.019; 1 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 |
| prose_short | +0.018; +0.004 to +0.051; 0 / 0 | +0.018; +0.004 to +0.051; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 |
| turabian | -0.003; -0.025 to +0.018; 0 / 0 | +0.038; +0.022 to +0.063; 3 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 |
| turabian_appendix | -0.003; -0.025 to +0.018; 0 / 0 | +0.043; +0.023 to +0.072; 1 / 0 | +0.000; +0.000 to +0.000; 0 / 0 | +0.000; +0.000 to +0.000; 0 / 0 |

#### The new measurement against the one it adds to, per input type

Papers: every dev variant x author (21 x 6). Identical: same deviation to the last bit and same action.

| Comparison | Input | papers | identical | moved | prose: mean change | prose: band up / down |
|---|---|---|---|---|---|---|
| para vs v1 | paste | 126 | 126 | 0 | +0.000 | 0 / 0 |
| para vs v1 | paste_word | 126 | 0 | 126 | -0.038 | 0 / 3 |
| para vs v1 | docx | 126 | 126 | 0 | +0.000 | 0 / 0 |
| para vs v1 | pdf | 126 | 126 | 0 | +0.000 | 0 / 0 |
| matter+para vs matter | paste | 126 | 126 | 0 | +0.000 | 0 / 0 |
| matter+para vs matter | paste_word | 126 | 0 | 126 | -0.038 | 0 / 3 |
| matter+para vs matter | docx | 126 | 126 | 0 | +0.000 | 0 / 0 |
| matter+para vs matter | pdf | 126 | 126 | 0 | +0.000 | 0 / 0 |

`v1` and `matter` rows against `rows_dev_after.json` (`run.py --after`): 1008 of 1008 identical.
<!-- /tables:dev_paragraphs -->

## Caveats

- Published 19th-century prose with fabricated parts, not student writing. The
  parts are realistic in shape (the styles' own rules), but one set of them,
  written once; real papers vary more, and the true false set-aside on student
  prose (short lines, lists, numbered points) is not measured here.
- Diagnostic, not validation. n = 6 papers per row; the reading rows show
  direction and rough size, not false-alarm rates.
- The splitter's rules were developed against the 2026-11-18 experiment and
  similar texts; this set is new to them, but its dev split will now be looked
  at while rules are tuned. The holdout exists for that reason.
- A PDF is one LibreOffice rendering (Liberation Serif, US Letter, double
  spaced). Word's or Google Docs' PDFs wrap and order text differently.
- Note markers (the superscript numbers in the prose) are reported but are not
  the splitter's job: they sit inside prose lines, and the citation cleaner in
  `features/preprocess.py` handles them later; segmentation here is
  `body_segments` only.
- Past papers are prose only. A student whose past papers also carry parts
  would be compared differently.

## Hold-out

`run.py --split holdout` computes the same numbers for chesterton, kempis and
mill and writes `rows_holdout.json` and `summary_holdout.json`, marked
`HOLDOUT_LOOKED_AT` with the time it ran. It refuses to run once that file
exists. Its numbers are not reported here. Anyone who opens that file before a
rule change is tested on it should say so.

**Its independence is weakened.** Chesterton's, Kempis's and Mill's prose was in
the 2026-11-18 experiment the splitter's rules were developed against, and the
part templates and heading words are shared across the two splits. So hold-out
recall cannot test whether a rule generalises to parts it was not written for;
the hold-out can only test false set-aside of prose and the reading change, on
3 authors.

## Rerun

From the repository root:

```bash
.venv/bin/python -I validation/diagnostics/document_parts_v2/run.py          # dev, about 6.5 minutes on 4 cores
.venv/bin/python -I validation/diagnostics/document_parts_v2/run.py --segment-only   # segmentation only, seconds
.venv/bin/python validation/diagnostics/document_parts_v2/make_cases.py      # rebuild the set (needs LibreOffice)
```

`run.py` reads only `cases.jsonl.xz` (the papers and the four past papers per
author), so it needs no LibreOffice. Scoring uses the live `/students/{id}/score` route in-process
with the 2026-11-18 harness's pilot-like flags (`CONTEXT_MANIFEST_ENABLED=0`,
`ADAPTIVE_WEIGHTS_ENABLED=0`, `NULL_MODEL=none`, `DRIFT_GATE=advisory`, no
`sentence-transformers`), two report-only extras off for speed
(`EVIDENCE_PASSAGES_ENABLED=0`, `RULE_D_OBSERVATION=off`; neither can change the
score or the action), and `UPLOAD_ALSO_MEASURE=matter`, so the four past
papers also carry the splitter's measurement and a flag-on score compares like
with like (ADR-014; every flag-on row checks `measurement.used == "matter"`).
Each score runs on a fresh copy of the author's student, so no score sees
another's history; `summary_dev.json` records a check that the same text
scores identically on two copies (it does). Scores are cached per task in
`build/score_cache/`, so a stopped run resumes. The cache key includes a hash
of every file in `original/` (`run.py:code_hash`), so any change to the engine
or the rules is rescored, never served stale; each run also scores one case
fresh and asserts it matches the main run (`determinism.main_run_matches_fresh`).
`--segment-only` writes `rows_dev_segment_only.json` and
`summary_dev_segment_only.json`, never the full run's files.

## Holdout after the final rules (run once, 2026-11-21)

`run.py --split holdout --after` was run once on the final rules (engine `code_hash` `c2a0f40b81442000`, the same as `summary_dev_after.json`), stamped `HOLDOUT_LOOKED_AT` 2026-11-21T00:01:48Z, with `determinism.main_run_matches_fresh` true. Files: `summary_holdout_after.json`, `rows_holdout_after.json`. Nothing was tuned on it.

Corpus: 3 authors (chesterton, kempis, mill), published 19th-century prose with fabricated parts, not student writing. Independence is weakened (their prose was in the 2026-11-18 experiment the rules were developed against; templates and heading words are shared with dev), so recall here does not show the rules generalise. Every band count, mean and rate below is `uninformative` beyond these 3 authors.

- **Prose set aside, splitter on:** 0 of 252 cases, every format and input type (as on dev). The four negative controls read exactly as their prose alone in all input types (holdout before: up to +0.070 as PDF).
- **New, not seen on dev:** in 19 kempis PDF cases some true prose is listed to the teacher as a `possible` part (7.8% of prose characters in the prose-only PDFs, 14.5% in Turabian PDFs). It is measured, so it does not move the reading, but a teacher would see it.
- **Recall, splitter on (prose set aside 0% beside each):** pasted and .docx every part 100% except MLA references 95% (kempis's unheaded list, 0%); PDF: APA title page 84% (kempis 28%), Turabian footnotes 50% (lowest 3%), against 100% and 94% on dev.
- **Reading change against the prose alone:** chesterton and mill read exactly as their prose alone except `turabian_appendix` (-0.011 to +0.014, the appendix being measured) and mill's Turabian PDF (+0.0006). Kempis: +0.131 on `mla_unheaded_refs` (pasted, .docx, PDF; +0.083 single-newline paste), +0.095 on five APA PDF variants, +0.020 on Turabian PDF. No paper changed band. Dev's "within 0.0024" did not hold here.
- **Switch off:** all 252 holdout rows score exactly as before.

The holdout is now used: any rule change made because of the kempis findings is tuned on it, and it can no longer test those rules. Nothing here authorises `MATTER_SPLITTER_ENABLED=1`; how often these parts appear in real submissions, and how they are shaped, is what no corpus here can supply.

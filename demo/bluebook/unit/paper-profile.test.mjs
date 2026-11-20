import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

// The "About the papers" table Writing State and the side-by-side page share
// (demo/original/js/paper-profile.js): server numbers in plain words, nothing
// from the paper's own text, nothing drawn without a profile.
const require = createRequire(import.meta.url);
const PP = require('../../original/js/paper-profile.js');

const mla = {
  words: 216, front_matter_words: 18, headings: 0,
  sources: { count: 3, list_heading: 'Works Cited', earliest_year: 2000, latest_year: 2008, kinds: { book: 1, 'journal or periodical': 1, other: 1 } },
  in_text_citations: { count: 2, per_100_words: 1.27 }, footnote_markers: 0,
  quotes: { short_quotes: 1, block_quote_words: 44 },
  citation_style: { guess: 'MLA', words: 'Best guess: MLA style.', signs: ['the list of sources is headed \u201cWorks Cited\u201d'], caveat: 'A best guess from the formatting, not a check of the citations.' },
};
const none = {
  words: 90, front_matter_words: 0, headings: 1, sources: { count: 0, list_heading: null, earliest_year: null, latest_year: null, kinds: {} },
  in_text_citations: { count: 0, per_100_words: 0 }, footnote_markers: 0, quotes: { short_quotes: 0, block_quote_words: 0 },
  citation_style: { guess: null, words: 'No citations found to guess a style from.', signs: [], caveat: 'A best guess from the formatting, not a check of the citations.' },
};
const profile = { note: 'Descriptive only.', this_paper: mla, past_papers: [{ paper: 'past paper 1', ...none }] };

test('one column per paper, one plain row per fact', () => {
  const html = PP.table(profile);
  assert.match(html, /<th scope="col">This paper<\/th><th scope="col">Past paper 1<\/th>/);
  assert.match(html, /<td>3 sources under “Works Cited”<\/td><td>None found<\/td>/);
  assert.match(html, /<td>2000 to 2008<\/td><td>–<\/td>/);
  assert.match(html, /<td>1 book, 1 journal or periodical, 1 other<\/td>/);
  assert.match(html, /<td title="Signs: the list of sources is headed “Works Cited”\.">Best guess: MLA style\.<\/td><td>No citations found to guess a style from\.<\/td>/);
  assert.match(html, /<td>2 \(1\.27 per 100 words\)<\/td><td>None<\/td>/);
  assert.match(html, /<td>18 words<\/td><td>None<\/td>/);
  assert.match(html, /<td>1 short quote, 44 words in block quotes<\/td><td>No short quotes<\/td>/);
  assert.match(html, /Descriptive only\. Citation style: a best guess from the formatting, not a check of the citations\./);
  assert.equal((html.match(/<tr>/g) || []).length, PP.rows.length + 1);
});

test('nothing is drawn without a profile, and odd values never break the table', () => {
  assert.equal(PP.table(null), '');
  assert.equal(PP.table({ past_papers: [] }), '');
  assert.equal(PP.has({}), false);
  assert.equal(PP.has({ paper_profile: profile }), true);
  const odd = PP.table({ this_paper: { sources: 'x', quotes: null, citation_style: 3 } });
  assert.match(odd, /<td>None found<\/td>/);
  assert.doesNotMatch(odd, /undefined|NaN|null/);
});

test('server strings are escaped', () => {
  const html = PP.table({ this_paper: { ...mla, sources: { ...mla.sources, list_heading: '<b>Works</b>' } }, past_papers: [{ paper: '<i>p</i>' }] });
  assert.doesNotMatch(html, /<b>Works<\/b>|<i>p<\/i>/);
  assert.match(html, /&lt;b&gt;Works&lt;\/b&gt;/);
});

// Parts of the paper (paper_profile.parts, only with MATTER_SPLITTER_ENABLED on).
const parts = [
  { kind: 'title_page', label: 'Title page', possible: false, rules_status: 'set_aside', status: 'set_aside', by: 'rules', words: 34, first_line: 'A Strong Rod Broken', ranges: [[0, 187]] },
  { kind: 'abstract', label: 'Abstract', possible: false, rules_status: 'set_aside', status: 'measured', by: 'teacher', words: 182, first_line: 'Abstract', ranges: [[189, 1375]] },
  { kind: 'notes', label: 'Notes', possible: true, rules_status: 'measured', status: 'measured', by: 'rules', words: 40, first_line: 'Notes', ranges: [[5000, 5300]] },
  { kind: 'back_matter', label: 'References', possible: false, rules_status: 'set_aside', status: 'set_aside', by: 'rules', words: 1, first_line: '<b>References</b>', ranges: [[10087, 11163]] },
];

test('each part in plain words', () => {
  assert.equal(PP.partWords(parts[0]), 'Title page: set aside, 34 words');
  assert.equal(PP.partWords(parts[1]), 'Abstract: measured (your choice), 182 words');
  assert.equal(PP.partWords(parts[2]), 'Possible notes: measured, 40 words');
  assert.equal(PP.partWords(parts[3]), 'References: set aside, 1 word');
  assert.equal(PP.partWords(null), '');
});

test('the parts row appears only when the server listed parts', () => {
  assert.doesNotMatch(PP.table(profile), /Parts of the paper/);
  const withParts = PP.table({ ...profile, this_paper: { ...mla, parts }, past_papers: [{ paper: 'past paper 1', ...none, parts: [] }] });
  assert.match(withParts, /<th scope="row">Parts of the paper<\/th><td><div class="pp-pl">Title page: set aside, 34 words<\/div><div class="pp-pl">Abstract: measured \(your choice\), 182 words<\/div><div class="pp-pl">Possible notes: measured, 40 words<\/div><div class="pp-pl">References: set aside, 1 word<\/div><\/td><td>Nothing set aside<\/td>/);
  assert.equal(PP.hasParts({ paper_profile: profile }), false);
  assert.equal(PP.hasParts({ paper_profile: { this_paper: { parts: [] } } }), true);
});

test('the list carries one button per part, worded for what it would do, escaped', () => {
  const html = PP.partsList(parts);
  assert.equal((html.match(/<button/g) || []).length, 4);
  assert.match(html, /data-part="0" data-act="measured">Measure this part</);
  assert.match(html, /data-part="1" data-act="set_aside">Set this part aside</);
  assert.match(html, /data-part="2" data-act="set_aside">Set this part aside</);
  assert.match(html, /&lt;b&gt;References&lt;\/b&gt;/);
  assert.doesNotMatch(html, /<b>References/);
  assert.equal(PP.partsList([]), '');
  assert.doesNotMatch(PP.partsList(parts, { control: false }), /<button/);
});

test('the choice is read from the server and changed one part at a time', () => {
  const now = PP.choiceOf({ parts, choice: { exclude_ranges: [], include_ranges: [[189, 1375]] } });
  assert.deepEqual(now, { exclude_ranges: [], include_ranges: [[189, 1375]] });
  assert.deepEqual(PP.choiceOf({ exclude_ranges: [[3, 4], [1, 2]], include_ranges: 'x' }), { exclude_ranges: [[1, 2], [3, 4]], include_ranges: [] });
  assert.deepEqual(PP.choiceOf(null), { exclude_ranges: [], include_ranges: [] });
  // Set the possible notes aside: a new range set aside.
  const a = PP.nextChoice(now, parts[2], 'set_aside');
  assert.deepEqual(a, { exclude_ranges: [[5000, 5300]], include_ranges: [[189, 1375]] });
  // The abstract back to what the rules do: it leaves both lists.
  const b = PP.nextChoice(a, parts[1], 'set_aside');
  assert.deepEqual(b, { exclude_ranges: [[5000, 5300]], include_ranges: [] });
  // Measure the title page, then set it aside again: back to the rules.
  const c = PP.nextChoice(b, parts[0], 'measured');
  assert.deepEqual(c.include_ranges, [[0, 187]]);
  assert.deepEqual(PP.nextChoice(c, parts[0], 'set_aside'), b);
  // A part inside a range of the opposite choice is cut out of it, never both.
  const d = PP.nextChoice({ exclude_ranges: [[0, 2000]], include_ranges: [] }, parts[1], 'measured');
  assert.deepEqual(d, { exclude_ranges: [[0, 189], [1375, 2000]], include_ranges: [[189, 1375]] });
  assert.deepEqual(PP.nextChoice(null, { ranges: 'x', rules_status: 'measured' }, 'set_aside'), { exclude_ranges: [], include_ranges: [] });
});

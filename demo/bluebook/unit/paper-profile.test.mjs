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

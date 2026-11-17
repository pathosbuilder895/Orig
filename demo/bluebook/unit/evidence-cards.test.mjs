import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

// The one card builder Writing State, the side-by-side page and the packet
// share (demo/original/js/evidence-cards.js): the same quotes, marks, labels
// and lines on all three, student text escaped, nothing invented.
const require = createRequire(import.meta.url);
const EV = require('../../original/js/evidence-view.js');
const EC = require('../../original/js/evidence-cards.js')(EV);

const past = (values) => values.map((value, i) => ({ paper: `past paper ${i + 1}`, value }));
const quote = (paper, passage, match, extra = {}) => {
  const i = passage.indexOf(match);
  return { paper, passage, passage_start: 50, passage_end: 50 + passage.length, match, match_start: 50 + i, match_end: 50 + i + match.length, ...extra };
};
const papers = [
  { paper: 'past paper 1', assignment: 'On Gardens', submitted_at: '2026-09-08' },
  { paper: 'past paper 2', assignment: 'The Ferry' },
];
function comma(over = {}) {
  return {
    rank: 1, code: 'comma_rate', name: 'Comma Rate', group: 4, in_top_list: true, kind: 'located',
    engine_scale: { this_paper: 0.2, past_papers: past([0.6, 0.64]), past_range: [0.6, 0.64], difference: -0.42, outside_past_range: true },
    plain: { unit: 'per 100 words', this_paper: 3.25, past_papers: past([8.01, 8.23]), past_range: [8.01, 8.23] },
    what_is_marked: 'comma',
    this_paper: { count: 2, examples: [quote('this paper', 'He left, quietly.', ',')] },
    past_papers: { count: 9, per_paper: [{ paper: 'past paper 1', count: 5 }, { paper: 'past paper 2', count: 4 }],
      examples: [quote('past paper 1', 'We went, and then, we stayed.', ','), quote('past paper 2', 'Ilse, the captain, waited.', ',')] },
    ...over,
  };
}
const ctx = { papers, thisSource: 'This paper · The Lighthouse · analysed Nov 17, 2026' };

test('a located habit: both sides quoted, the counted part marked, every quote labelled with source and date', () => {
  const html = EC.card(comma(), ctx);
  assert.match(html, /^<div class="ex" data-code="comma_rate">/);
  assert.match(html, /<b>Comma Rate<\/b><span class="ex-diff">This paper uses far fewer commas: 3\.25 vs 8\.01 to 8\.23 per 100 words\.<\/span>/);
  assert.equal((html.match(/<mark class="tiny">,<\/mark>/g) || []).length, 3);
  assert.match(html, /This paper · The Lighthouse · analysed Nov 17, 2026 · Counted: “,”/);
  const day = new Date(2026, 8, 8).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  assert.ok(html.includes('On Gardens · ' + day + ' · Counted: “,”'));
  assert.ok(html.includes('The Ferry · date not recorded · Counted: “,”'));
  assert.match(html, /<b>What to notice:<\/b> This paper is lower than the past papers on comma rate/);
});

test('a side that never uses the habit shows its longest sentences, nothing marked', () => {
  const f = comma({
    plain: { ...comma().plain, this_paper: 0 },
    note: 'No comma appears in this paper.',
    this_paper: { count: 0, examples: [], unmarked: [{ paper: 'this paper', passage: 'The paint is old <now>.', passage_start: 0, passage_end: 22, words: 5 }] },
  });
  const html = EC.card(f, ctx);
  assert.match(html, /This paper uses no commas: 0 vs/);
  assert.match(html, /<p class="none-line">No comma appears in this paper\.<\/p><p class="um-lead">This paper’s longest sentences, none with a comma:<\/p>/);
  assert.match(html, /<div class="ex-q unmarked" data-mark="">The paint is old &lt;now&gt;\.<\/div>/);
  assert.match(html, /This paper · The Lighthouse · analysed Nov 17, 2026 · 5 words/);
});

test('a whole-text habit shows numbers for every paper, with dates, and says there is no sentence to quote', () => {
  const f = {
    code: 'pronoun_ambiguity_rate', name: 'Pronoun Ambiguity Rate', kind: 'whole_text', in_top_list: true,
    engine_scale: { this_paper: 0.167, past_papers: past([0.625, 0.875]), past_range: [0.625, 0.875], difference: -0.6, outside_past_range: true },
    note: 'Whole-text measurement, no single sentence to point to.',
  };
  const html = EC.card(f, ctx);
  assert.match(html, /<span class="ex-big">0\.167<\/span>/);
  assert.ok(html.includes('<li><span>The Ferry · date not recorded</span><b>0.875</b></li>'));
  assert.match(html, /It is measured across the whole text, so there is no single sentence to quote\./);
  assert.doesNotMatch(html, /<mark/);
});

test('the top list resolves to full-list entries in the server’s order; rows can drop the name', () => {
  const full = comma();
  const ev = { features: [{ code: 'x_whole', name: 'X' }, { code: 'comma_rate', name: 'Comma Rate' }], all_features: [full], baseline_papers: papers };
  const top = EC.topList(ev);
  assert.deepEqual(top.map((f) => f.code), ['x_whole', 'comma_rate']);
  assert.equal(top[1], full);
  assert.deepEqual(EC.papersOf(ev), papers);
  assert.deepEqual(EC.topList(null), []);
  assert.doesNotMatch(EC.card(full, { ...ctx, noHead: true }), /<b>Comma Rate<\/b>/);
  assert.equal(EC.card(null, ctx), '');
  assert.equal(EC.hasQuotes(full), true);
});

test('student text and server names are escaped, banned wording never shows', () => {
  const f = comma({ name: 'Cheating <script>', this_paper: { count: 1, examples: [quote('this paper', 'A <b>bold</b>, claim.', ',')] } });
  const html = EC.card(f, ctx);
  assert.doesNotMatch(html, /<script>|<b>bold<\/b>|Cheating/);
  assert.match(html, /A &lt;b&gt;bold&lt;\/b&gt;<mark class="tiny">,<\/mark> claim\./);
});

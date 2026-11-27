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
    rank: 1, code: 'comma_rate', name: 'Comma Rate', group: 4, in_top_list: true, kind: 'located', display: { style: 'unit', unit: 'per 100 words' },
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
  assert.match(html, /<b>Comma Rate<\/b><span class="ex-diff">This paper uses far fewer commas: 3\.3 vs 8\.0 to 8\.2 per 100 words\.<\/span>/);
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

test('a whole-text habit with no everyday unit says where it sits in words, the exact position folded away', () => {
  const f = {
    code: 'catastrophe_index', name: 'Loose ends across paragraphs', kind: 'whole_text', in_top_list: true, display: { style: 'compare', whole_paper: 'x' },
    engine_scale: { this_paper: 0.524, past_papers: past([0, 0]), past_range: [0, 0], difference: 0.52, outside_past_range: true },
    note: 'This is one score for the whole paper, built from all of it at once. No single sentence shows it.',
  };
  const html = EC.card(f, ctx);
  assert.match(html, /<span class="ex-diff">This paper is higher than both past papers on loose ends across paragraphs\.<\/span>/);
  assert.match(html, /<p class="ex-rel">This paper is higher than both past papers\.<\/p>/);
  assert.ok(html.includes('<li><span>The Ferry · date not recorded</span><b class="rel">lower than this paper</b></li>'));
  assert.match(html, /No single sentence shows it\./);
  assert.match(html, /<details class="ex-exact"><summary>Exact position<\/summary><p>[^<]*this paper 0\.52; past papers 0\.00\.<\/p><\/details>/);
  // Outside the folded details no raw position, and nowhere a "0 to 1" scale or a percent.
  const open = html.replace(/<details[\s\S]*?<\/details>/g, '');
  assert.doesNotMatch(open, /0\.524|0\.52\b/);
  assert.doesNotMatch(html, /0 to 1|%/);
  assert.doesNotMatch(html, /<mark/);
});

test('a share read from the engine\u2019s own value shows as a percent in the card', () => {
  const f = {
    code: 'first_person_ratio', name: 'First person', kind: 'whole_text', display: { style: 'percent', of: 'of personal pronouns', engine_is_raw: true },
    engine_scale: { this_paper: 0.38, past_papers: past([0.05, 0.072]), past_range: [0.05, 0.072], difference: 0.3, outside_past_range: true },
  };
  const html = EC.card(f, ctx);
  assert.match(html, /<span class="ex-big">38%<\/span><div class="ex-unit">of personal pronouns<\/div>/);
  assert.ok(html.includes('<b>5%</b>') && html.includes('<b>7.2%</b>'));
  assert.doesNotMatch(html, /ex-exact|0\.38/);
});

test('the top list leads with quoted habits; the rest go to Other patterns, hidden habits nowhere', () => {
  const whole = { code: 'burstiness', name: 'Unevenness', kind: 'whole_text', display: { style: 'compare' }, note: 'A whole-paper pattern. No single sentence shows it.',
    engine_scale: { this_paper: 0.3, past_papers: past([0.5, 0.6]), past_range: [0.5, 0.6], difference: -0.25, outside_past_range: true } };
  const hidden = { ...whole, code: 'conclusion_strategy_score', name: 'Conclusion', display: { style: 'hidden' } };
  const ev = { features: [{ code: 'burstiness' }, { code: 'conclusion_strategy_score' }, { code: 'comma_rate' }], all_features: [whole, hidden, comma()] };
  const split = EC.splitTop(ev);
  assert.deepEqual(split.quoted.map((f) => f.code), ['comma_rate']);
  assert.deepEqual(split.other.map((f) => f.code), ['burstiness']);
  assert.deepEqual(EC.topList(ev).map((f) => f.code), ['burstiness', 'comma_rate']);
  const html = EC.otherList(split.other, ctx);
  assert.match(html, /^<ul class="ex-other"><li class="ex-other-row" data-code="burstiness"><b>Unevenness<\/b><span class="ex-other-line">This paper is lower than both past papers on unevenness\.<\/span><span class="ex-other-why">A whole-paper pattern\. No single sentence shows it\.<\/span><details class="ex-exact">/);
  assert.equal(EC.otherList([], ctx), '');
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

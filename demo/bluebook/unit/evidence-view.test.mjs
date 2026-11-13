import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

// The side-by-side page's words (demo/original/js/evidence-view.js): every
// sentence is a template filled from the staff evidence payload's numbers
// (ADR-013), and nothing it shows carries the banned wording.
const require = createRequire(import.meta.url);
const EV = require('../../original/js/evidence-view.js');

const past = (values) => values.map((value, i) => ({ paper: `past paper ${i + 1}`, value }));
function feature(over = {}) {
  const base = {
    rank: 1, code: 'comma_rate', name: 'Comma Rate', group: 4, in_top_list: true, kind: 'located',
    description: 'How often commas appear.',
    engine_scale: {
      this_paper: 0.2, past_papers: past([0.6, 0.62, 0.64]), past_papers_average: 0.62, past_range: [0.6, 0.64],
      difference: -0.42, weighted_size: 0.4, group_weight: 1, outside_past_range: true,
    },
    plain: { unit: 'per 100 words', this_paper: 3.25, past_papers: past([8.01, 8.04, 8.23]), past_range: [8.01, 8.23] },
    what_is_marked: 'comma',
    this_paper: { count: 47, examples: [] },
    past_papers: { count: 321, per_paper: [{ paper: 'past paper 1', count: 105 }, { paper: 'past paper 2', count: 111 }, { paper: 'past paper 3', count: 105 }], examples: [] },
  };
  return { ...base, ...over };
}

test('the banned-word check catches every banned phrase and passes ordinary prose', () => {
  for (const bad of ['AI detection', 'ai-detector', 'Cheating', 'cheated', 'authorship verification', 'Fingerprint',
    'accuracy of 92%', 'accurate', 'characteristic of generated prose', 'academic misconduct', 'written by AI']) {
    assert.equal(EV.isClean(bad), false, bad);
  }
  for (const ok of ['Counting each comma: this paper has 47.', 'vowel pairs (ee, ea, oo, ou, ai)', 'The past papers are within range.', '', null]) {
    assert.equal(EV.isClean(ok), true, String(ok));
  }
  assert.equal(EV.clean('Proof of cheating', 'Comma Rate'), 'Comma Rate');
  assert.equal(EV.clean('cheating', 'misconduct'), '');
  assert.equal(EV.clean('Comma Rate', 'x'), 'Comma Rate');
});

test('numbers print at three significant figures, never in exponent form', () => {
  assert.equal(EV.fmt(3.2512), '3.25');
  assert.equal(EV.fmt(0.000123), '0.000123');
  assert.equal(EV.fmt(1234.6), '1235');
  assert.equal(EV.fmt(0), '0');
  assert.equal(EV.fmt(null), '\u2013');
  assert.equal(EV.fmt(NaN), '\u2013');
  assert.equal(EV.signed(-0.42), '\u22120.42');
  assert.equal(EV.signed(0.1), '+0.1');
  assert.equal(EV.signed(0), '0');
  assert.equal(EV.signed(undefined), '\u2013');
});

test('a counted measurement\u2019s note gives the counts, the plain values and the side of the range', () => {
  const note = EV.noteFor(feature(), [{ paper: 'past paper 2', assignment: 'On Liberty' }]);
  assert.equal(note,
    'Counting each comma: this paper has 47 (3.25 per 100 words). Past paper 1 has 105 (8.01), On Liberty has 111 (8.04) and Past paper 3 has 105 (8.23). ' +
    'On Original\u2019s 0 to 1 scale this paper is below the lowest of the 3 past papers.');
  const above = feature({ engine_scale: { ...feature().engine_scale, difference: 0.3 } });
  assert.match(EV.noteFor(above, []), /above the highest of the 3 past papers\.$/);
  const inside = feature({ engine_scale: { ...feature().engine_scale, outside_past_range: false } });
  assert.match(EV.noteFor(inside, []), /within the past papers\u2019 range\.$/);
});

test('a whole-text measurement\u2019s note lists each paper\u2019s value, in plain units or the 0 to 1 scale', () => {
  const whole = feature({ kind: 'whole_text', code: 'burstiness', what_is_marked: undefined, this_paper: undefined, past_papers: undefined,
    plain: { unit: 'variance \u00f7 mean', this_paper: 6.31, past_papers: past([7.53, 13, 20.8]), past_range: [7.53, 20.8] } });
  assert.equal(EV.noteFor(whole, []),
    'This paper: 6.31 (variance \u00f7 mean). Past papers: Past paper 1 7.53, Past paper 2 13 and Past paper 3 20.8. ' +
    'On Original\u2019s 0 to 1 scale this paper is below the lowest of the 3 past papers.');
  const scale = { ...whole, plain: null, engine_scale: { ...whole.engine_scale, past_papers: past([0.5]), past_range: [0.5, 0.5], outside_past_range: false } };
  assert.equal(EV.noteFor(scale, []),
    'This paper: 0.2 (on Original\u2019s 0 to 1 scale). Past papers: Past paper 1 0.5. On Original\u2019s 0 to 1 scale this paper matches the past paper.');
  assert.equal(EV.oneLine(scale), 'This paper 0.2; past papers 0.5 (on Original\u2019s 0 to 1 scale).');
  assert.equal(EV.oneLine(feature()), 'This paper 3.25; past papers 8.01 to 8.23 (per 100 words).');
  const lonely = { ...scale, engine_scale: { ...scale.engine_scale, past_papers: [], past_range: null } };
  assert.equal(EV.noteFor(lonely, []), 'This paper: 0.2 (on Original\u2019s 0 to 1 scale). There are no past papers to compare with.');
  assert.equal(EV.noteFor(null), '');
  const one = { ...scale, engine_scale: { ...scale.engine_scale, outside_past_range: true, difference: -0.3 } };
  assert.match(EV.noteFor(one, []), /this paper is below the past paper\.$/);
});

test('a sentence-length measurement is described by its values, not as a count', () => {
  const longest = feature({ code: 'sentence_length_variance', what_is_marked: 'the longest and shortest sentences',
    this_paper: { count: 2, examples: [{ passage: 'A b c.', words: 3 }] } });
  assert.match(EV.noteFor(longest, []), /^This paper: 3\.25 \(per 100 words\)\. Past papers: /);
});

test('the note never carries banned wording, even from a server name', () => {
  const sneaky = feature({ kind: 'whole_text', plain: { unit: 'cheating units', this_paper: 1, past_papers: past([1]), past_range: [1, 1] } });
  const note = EV.noteFor(sneaky, []);
  assert.equal(EV.isClean(note), true);
  assert.equal(note, 'On Original\u2019s 0 to 1 scale this paper is below the lowest of the 3 past papers.');
});

const flat = (v) => ({ this_paper: v, past_papers: past([v, v, v]), past_papers_average: v, past_range: [v, v], difference: 0, weighted_size: 0, group_weight: 1, outside_past_range: false });

const notCompared = (es) => ({ this_paper: 1, past_papers: past([null, null, null]), past_papers_average: null, past_range: null,
  difference: null, weighted_size: null, group_weight: 1, outside_past_range: null, ...es });

test('a comparison measurement past papers have no value for is never listed or compared', () => {
  const one = feature({ kind: 'not_compared', code: 'punctuation_error_ratio', direction: 'not_compared', plain: null, engine_scale: notCompared({}) });
  assert.equal(EV.isNotCompared(one), true);
  assert.equal(EV.NOT_COMPARED_WORDS, 'not compared: past papers have no value for this');
  assert.equal(EV.noteFor(one, []), 'This paper: 1 (on Original\u2019s 0 to 1 scale). Not compared: past papers have no value for this.');
  assert.equal(EV.noteFor({ ...one, engine_scale: notCompared({ this_paper: null }) }, []), 'Not compared: past papers have no value for this.');
  assert.equal(EV.isListed(one), false);
  assert.equal(EV.isActive(one), false);
  assert.equal(EV.isNotCompared({ ...one, kind: 'located' }), false);
  assert.equal(EV.isNotCompared(null), false);
  assert.equal(EV.isConstant(feature({ engine_scale: flat(0.5) })), true);
  assert.equal(EV.isListed(feature({ kind: 'off', engine_scale: flat(0.5) })), false);
  assert.equal(EV.isListed(null), false);
});

test('the summary counts active measurements, the outside ones, groups and the unused', () => {
  const ev = {
    features: [feature()],
    all_features: [
      feature(),
      feature({ rank: 2, code: 'b', group: 4, kind: 'whole_text', engine_scale: { ...feature().engine_scale, outside_past_range: false, difference: 0.01 } }),
      feature({ rank: 3, code: 'c', group: 1, kind: 'whole_text', engine_scale: { ...feature().engine_scale, outside_past_range: false, difference: 0.02 } }),
      feature({ rank: 4, code: 'd', group: 17, kind: 'off', engine_scale: flat(0.5) }),
      feature({ rank: 5, code: 'e', group: 0, kind: 'not_compared', engine_scale: notCompared({ this_paper: 0.5 }) }),
      feature({ rank: 6, code: 'f', group: 0, kind: 'not_compared', engine_scale: notCompared({}) }),
      // Even with differing numbers a not-compared row is never listed or counted.
      feature({ rank: 7, code: 'g', group: 0, kind: 'not_compared', engine_scale: { ...flat(0.5), this_paper: 1, outside_past_range: true } }),
      feature({ rank: 8, code: 'h', group: 17, kind: 'off', engine_scale: { ...flat(0.5), past_papers: past([0.5, 0.4, 0.5]) } }),
    ],
  };
  const names = { 1: 'Word & Sentence Habits', 4: 'Punctuation Habits' };
  const sum = EV.summarize(ev, (g) => names[g] || '');
  assert.deepEqual({ ...sum, groups: undefined }, { total: 8, active: 3, outside: 1, within: 2, off: 1, notCompared: 3, otherListed: 1, groups: undefined, pastCount: 3, topCount: 1 });
  assert.deepEqual(sum.groups.map((g) => [g.name, g.outside, g.active]), [['Word & Sentence Habits', 0, 1], ['Punctuation Habits', 1, 2]]);
  const lines = EV.summarySentences(sum);
  assert.equal(lines[0], 'This paper is outside the past-paper range on 1 of 3 active measurements, and within that range on 2.');
  assert.match(lines[1], /^Each range is simply the lowest to the highest of 3 past papers/);
  assert.equal(lines[2], 'By group: Word & Sentence Habits 0 of 1 outside; Punctuation Habits 1 of 2 outside.');
  assert.equal(lines[3], '1 measurement that Original does not normally compare had differing values here, so it is listed below but not counted here.');
  assert.equal(lines[4], 'Not used in this comparison: 1 measurement switched off and 3 comparison measurements not compared, because past papers have no value for them.');
  assert.equal(lines.length, 5);
  assert.equal(EV.summarySentences({ ...sum, off: 0, notCompared: 1 }).pop(), 'Not used in this comparison: 1 comparison measurement not compared, because past papers have no value for it.');
  lines.forEach((l) => assert.equal(EV.isClean(l), true));
  assert.deepEqual(EV.summarySentences(sum, { groups: false }), [lines[0], lines[1], lines[3], lines[4]]);
  assert.deepEqual(ev.all_features.filter(EV.isListed).map((f) => f.code), ['comma_rate', 'b', 'c', 'h']);
  assert.deepEqual(EV.summarySentences(EV.summarize({ all_features: [] })), ['No measurement in this analysis could be compared with past papers.']);
  assert.equal(EV.summarize(null).active, 0);
});

test('where it held steady: in range, closest first, text cards before whole-text ones', () => {
  const es = (difference, outside = false) => ({ ...feature().engine_scale, difference, outside_past_range: outside });
  const quote = { passage: 'x' };
  const located = (code, d, rank) => feature({ code, rank, engine_scale: es(d), this_paper: { count: 1, examples: [quote] }, past_papers: { count: 1, per_paper: [], examples: [quote] } });
  const ev = {
    all_features: [
      located('far', 0.3, 1), located('near', -0.01, 9), located('mid', 0.1, 3), located('tie', 0.1, 2), located('fifth', 0.2, 4),
      feature({ code: 'out', engine_scale: es(0.001, true) }),
      feature({ code: 'w1', kind: 'whole_text', engine_scale: es(0.05) }),
      feature({ code: 'w2', kind: 'whole_text', engine_scale: es(-0.02) }),
      feature({ code: 'w3', kind: 'whole_text', engine_scale: es(0.5) }),
      feature({ code: 'empty', engine_scale: es(0), this_paper: { count: 0, examples: [] } }),
      feature({ code: 'off', kind: 'off', engine_scale: es(0) }),
    ],
  };
  assert.deepEqual(EV.steady(ev).map((f) => f.code), ['near', 'tie', 'mid', 'w2', 'w1']);
  assert.deepEqual(EV.steady(ev, 1, 0).map((f) => f.code), ['near']);
  assert.deepEqual(EV.steady({}), []);
});

test('the counted words are marked only when they are exactly the passage slice the offsets name', () => {
  const q = { passage: 'He said, then left.', passage_start: 100, match: ',', match_start: 107, match_end: 108 };
  assert.deepEqual(EV.markParts(q), { before: 'He said', mark: ',', after: ' then left.', tiny: true });
  assert.deepEqual(EV.markParts({ ...q, match: ';' }), { before: q.passage, mark: '', after: '', tiny: false });
  assert.deepEqual(EV.markParts({ ...q, match_end: 200 }), { before: q.passage, mark: '', after: '', tiny: false });
  assert.deepEqual(EV.markParts({ passage: 'abc' }), { before: 'abc', mark: '', after: '', tiny: false });
  assert.deepEqual(EV.markParts(null), { before: '', mark: '', after: '', tiny: false });
  const long = { passage: 'He said however that', passage_start: 0, match: 'however', match_start: 8, match_end: 15 };
  assert.equal(EV.markParts(long).tiny, false);
});

test('past papers are called by their stored title when there is one', () => {
  const papers = [{ paper: 'past paper 1', assignment: '  On Liberty ' }, { paper: 'past paper 2', assignment: '' }];
  assert.equal(EV.paperName('past paper 1', papers), 'On Liberty');
  assert.equal(EV.paperName('past paper 2', papers), 'Past paper 2');
  assert.equal(EV.paperName('this paper', papers), 'This paper');
  assert.equal(EV.paperName('past paper 3'), 'Past paper 3');
  assert.equal(EV.plural(1, 'word'), '1 word');
  assert.equal(EV.isActive({ kind: 'not_compared' }), false);
  assert.equal(EV.position({ engine_scale: {} }), 'none');
});

// The plain-language "What to notice" line (noticeFor): one or two short
// sentences from the entry's own direction, range and kind, plus a fixed
// caution. It never names a cause specific to the student.
const CAUTION = 'A shift like this can come from a new topic, genre, length, revision or permitted help; on its own it does not show who wrote the paper.';

test('noticeFor: a located measurement above or below the past range says which way, by how much, and the fixed caution', () => {
  assert.equal(EV.noticeFor(feature(), []),
    'This paper is lower than the past papers on comma rate (3.25 against 8.01 to 8.23 per 100 words). ' + CAUTION);
  const above = feature({ engine_scale: { ...feature().engine_scale, difference: 0.3 } });
  assert.match(EV.noticeFor(above, []), /^This paper is higher than the past papers on comma rate \(/);
  // One past paper: a single value, not a range. Original's 0 to 1 scale when no plain units were sent.
  const scale = feature({ plain: null, engine_scale: { ...feature().engine_scale, past_papers: past([0.5]), past_range: [0.5, 0.5], difference: 0.3 } });
  assert.equal(EV.noticeFor(scale, []),
    'This paper is higher than the past papers on comma rate (0.2 against 0.5 on Original’s 0 to 1 scale). ' + CAUTION);
  // No numbers to quote: the direction alone.
  const bare = feature({ plain: null, engine_scale: { ...feature().engine_scale, this_paper: null, past_range: null } });
  assert.equal(EV.noticeFor(bare, []), 'This paper is lower than the past papers on comma rate. ' + CAUTION);
  // Acronym-style names keep their capitals; a missing name falls back to "this habit".
  assert.match(EV.noticeFor(feature({ name: 'TTR Level' }), []), /^This paper is lower than the past papers on TTR level/);
  assert.match(EV.noticeFor(feature({ name: '' }), []), /^This paper is lower than the past papers on this habit/);
});

test('noticeFor: within the range, one plain sentence (plus the whole-text note when there is no sentence to quote)', () => {
  const inside = feature({ engine_scale: { ...feature().engine_scale, outside_past_range: false } });
  assert.equal(EV.noticeFor(inside, []), 'This habit is in line with the past papers.');
  const whole = { ...inside, kind: 'whole_text' };
  assert.equal(EV.noticeFor(whole, []),
    'This habit is in line with the past papers. It is measured across the whole text, so there is no single sentence to quote.');
});

test('noticeFor: a whole-text shift says there is no single sentence to quote', () => {
  const whole = feature({ kind: 'whole_text', name: 'Burstiness' });
  assert.equal(EV.noticeFor(whole, []),
    'This paper is lower than the past papers on burstiness (3.25 against 8.01 to 8.23 per 100 words). ' +
    'It is measured across the whole text, so there is no single sentence to quote. ' + CAUTION);
});

test('noticeFor: no past papers, not compared and switched off each get a plain reason', () => {
  const none = feature({ engine_scale: { ...feature().engine_scale, past_papers: [], past_range: null } });
  assert.equal(EV.noticeFor(none, []), 'There are no past papers to compare this with.');
  const nc = feature({ kind: 'not_compared', engine_scale: notCompared({}) });
  assert.equal(EV.noticeFor(nc, []), 'Original does not compare this one: past papers have no value for it, so it plays no part in the score.');
  const off = feature({ kind: 'off', engine_scale: flat(0.5) });
  assert.equal(EV.noticeFor(off, []), 'This measurement is switched off, so it plays no part in the score.');
  assert.equal(EV.noticeFor(null, []), '');
  assert.equal(EV.noticeFor('x', []), '');
  assert.equal(EV.noticeFor({ kind: 'mystery' }, []), '');
});

test('noticeFor: banned wording from a server name falls back to a generic sentence and every output is clean', () => {
  const sneaky = feature({ name: 'cheating rate' });
  const out = EV.noticeFor(sneaky, []);
  assert.equal(out, 'This paper is lower than the past papers on this habit (3.25 against 8.01 to 8.23 per 100 words). ' + CAUTION);
  const bad = feature({ plain: { unit: 'AI units', this_paper: 1, past_papers: past([2]), past_range: [2, 2] } });
  assert.equal(EV.noticeFor(bad, []), 'This paper is lower than the past papers on comma rate. ' + CAUTION);
  const all = [
    feature(), feature({ kind: 'whole_text' }), feature({ engine_scale: { ...feature().engine_scale, outside_past_range: false } }),
    feature({ engine_scale: { ...feature().engine_scale, past_papers: [], past_range: null } }),
    feature({ kind: 'not_compared', engine_scale: notCompared({}) }), feature({ kind: 'off', engine_scale: flat(0.5) }), sneaky,
  ].map((f) => EV.noticeFor(f, []));
  for (const s of all) {
    assert.equal(EV.isClean(s), true, s);
    assert.doesNotMatch(s, /fingerprint|proves|verifies|cheat|\bAI\b|accura|\u2014|\u2015/i);
  }
});

// One rule for quotes on Writing State, the side-by-side page and the packet.
test('a short counted match is one of three characters or fewer, or has no letter or digit', () => {
  for (const m of [',', ';', 'of', 'the', ' an ', '----', '...']) assert.equal(EV.isShortMatch(m), true, m);
  for (const m of ['however', 'that is', 'four']) assert.equal(EV.isShortMatch(m), false, m);
  assert.equal(EV.isShortMatch(''), false);
  assert.equal(EV.isShortMatch(null), false);
});

test('dayOf gives the calendar day a stored date names, and nothing for anything else', () => {
  const day = new Date(2025, 0, 24).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  assert.equal(EV.dayOf('2025-01-24'), day);
  // A full timestamp is read as the day it was written on, never shifted by the time zone.
  assert.equal(EV.dayOf('2025-01-24T23:59:00Z'), day);
  assert.equal(EV.dayOf('2025-01-24 08:00'), day);
  for (const bad of ['', null, undefined, 'yesterday', '24/01/2025', '2025-1-24']) assert.equal(EV.dayOf(bad), '', String(bad));
});

test('a past paper\u2019s source is its stored title (else "Past paper N") and its day, with one separator', () => {
  const day = new Date(2025, 0, 24).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  const papers = [{ paper: 'past paper 1', assignment: 'On Liberty', submitted_at: '2025-01-24' }, { paper: 'past paper 2', assignment: '' }, null];
  assert.equal(EV.SEP, ' \u00b7 ');
  assert.equal(EV.pastSource('past paper 1', papers), 'On Liberty \u00b7 ' + day);
  assert.equal(EV.pastSource('past paper 2', papers), 'Past paper 2');
  assert.equal(EV.pastSource('past paper 3', papers), 'Past paper 3');
  assert.equal(EV.pastSource('past paper 1'), 'Past paper 1');
});

test('a quote\u2019s source line names the paper, its length, a short match and set-aside text', () => {
  const q = { passage: 'He said, then left.', passage_start: 100, match: ',', match_start: 107, match_end: 108, words: 4 };
  assert.equal(EV.quoteSource(q, 'This paper'), 'This paper \u00b7 4 words \u00b7 Counted: \u201c,\u201d');
  assert.equal(EV.quoteSource({ ...q, words: 1, crosses_set_aside: true }, 'Past paper 1'),
    'Past paper 1 \u00b7 1 word \u00b7 Counted: \u201c,\u201d \u00b7 runs into text set aside from measuring');
  const long = { passage: 'He said however that', passage_start: 0, match: 'however', match_start: 8, match_end: 15 };
  assert.equal(EV.quoteSource(long, 'This paper'), 'This paper');
  assert.equal(EV.quoteSource({ ...long, match: 'x' }, 'This paper'), 'This paper');
});

test('the not-compared sentence is built from the shared words', () => {
  assert.equal(EV.NOT_COMPARED_LINE, 'Not compared: past papers have no value for this.');
  assert.ok(EV.NOT_COMPARED_LINE.toLowerCase().startsWith(EV.NOT_COMPARED_WORDS));
});

test('a habit name loses its capitals inside a sentence, but acronyms and proper nouns keep theirs', () => {
  const nm = (name) => EV.habitName({ name });
  assert.equal(nm('Comma Rate'), 'comma rate');
  assert.equal(nm('Type\u2013Token Ratio'), 'type\u2013token ratio');
  assert.equal(nm('POS Bigram Entropy'), 'POS bigram entropy');
  assert.equal(nm('Flesch Reading Ease'), 'Flesch reading ease');
  assert.equal(nm('"Ibid." Usage Rate'), '"ibid." usage rate');
  assert.equal(nm('Counter-Argument Ratio'), 'counter-argument ratio');
  assert.equal(nm(''), 'this habit');
  assert.equal(nm(null), 'this habit');
});

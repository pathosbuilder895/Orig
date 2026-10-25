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

test('a comparison computed for this paper only says its past papers are on the placeholder', () => {
  const one = feature({ kind: 'placeholder', code: 'punctuation_error_ratio', plain: null, engine_scale: { ...flat(0.5), this_paper: 1, difference: 0.5, outside_past_range: true } });
  assert.equal(EV.isOneSided(one), true);
  assert.equal(EV.noteFor(one, []),
    'This paper: 1 (on Original\u2019s 0 to 1 scale). Every past paper has 0.5, the placeholder Original gives a paper when this comparison is not computed for it. ' +
    'The two numbers are not measured the same way, so this gap says little on its own.');
  const single = { ...one, engine_scale: { ...one.engine_scale, past_papers: past([0.5]) } };
  assert.match(EV.noteFor(single, []), /The past paper has 0\.5,/);
  assert.equal(EV.isOneSided({ ...one, engine_scale: flat(0.5) }), false);
  assert.equal(EV.isOneSided({ ...one, kind: 'located' }), false);
  assert.equal(EV.isOneSided({ ...one, engine_scale: { ...one.engine_scale, past_papers: [] } }), false);
  assert.equal(EV.isOneSided({ ...one, engine_scale: { ...one.engine_scale, past_papers: past([0.5, 0.4]) } }), false);
  assert.equal(EV.isOneSided({ ...one, engine_scale: { ...one.engine_scale, past_papers: [{ paper: 'p', value: null }] } }), false);
  assert.equal(EV.isConstant(feature({ engine_scale: flat(0.5) })), true);
  assert.equal(EV.isListed(one), true);
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
      feature({ rank: 5, code: 'e', group: 0, kind: 'placeholder', engine_scale: flat(0.5) }),
      feature({ rank: 6, code: 'f', group: 0, kind: 'placeholder', engine_scale: flat(0.5) }),
      feature({ rank: 7, code: 'g', group: 0, kind: 'placeholder', engine_scale: { ...flat(0.5), this_paper: 1 } }),
      feature({ rank: 8, code: 'h', group: 17, kind: 'off', engine_scale: { ...flat(0.5), past_papers: past([0.5, 0.4, 0.5]) } }),
    ],
  };
  const names = { 1: 'Word & Sentence Habits', 4: 'Punctuation Habits' };
  const sum = EV.summarize(ev, (g) => names[g] || '');
  assert.deepEqual({ ...sum, groups: undefined }, { total: 8, active: 3, outside: 1, within: 2, off: 1, placeholder: 2, oneSided: 1, otherListed: 1, groups: undefined, pastCount: 3, topCount: 1 });
  assert.deepEqual(sum.groups.map((g) => [g.name, g.outside, g.active]), [['Word & Sentence Habits', 0, 1], ['Punctuation Habits', 1, 2]]);
  const lines = EV.summarySentences(sum);
  assert.equal(lines[0], 'This paper is outside the past-paper range on 1 of 3 active measurements, and within that range on 2.');
  assert.match(lines[1], /^Each range is simply the lowest to the highest of 3 past papers/);
  assert.equal(lines[2], 'By group: Word & Sentence Habits 0 of 1 outside; Punctuation Habits 1 of 2 outside.');
  assert.equal(lines[3], '1 comparison measurement had a value for this paper only, with every past paper on the placeholder value, so it is listed below but not counted here.');
  assert.equal(lines[4], '1 measurement that Original does not normally compare had differing values here, so it is listed below but not counted here.');
  assert.equal(lines[5], 'Not used in this comparison: 1 measurement switched off and 2 measurements not computed for these papers.');
  lines.forEach((l) => assert.equal(EV.isClean(l), true));
  assert.deepEqual(EV.summarySentences(sum, { groups: false }), [lines[0], lines[1], lines[3], lines[4], lines[5]]);
  assert.deepEqual(ev.all_features.filter(EV.isListed).map((f) => f.code), ['comma_rate', 'b', 'c', 'g', 'h']);
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
  assert.deepEqual(EV.markParts(q), { before: 'He said', mark: ',', after: ' then left.' });
  assert.deepEqual(EV.markParts({ ...q, match: ';' }), { before: q.passage, mark: '', after: '' });
  assert.deepEqual(EV.markParts({ ...q, match_end: 200 }), { before: q.passage, mark: '', after: '' });
  assert.deepEqual(EV.markParts({ passage: 'abc' }), { before: 'abc', mark: '', after: '' });
  assert.deepEqual(EV.markParts(null), { before: '', mark: '', after: '' });
});

test('past papers are called by their stored title when there is one', () => {
  const papers = [{ paper: 'past paper 1', assignment: '  On Liberty ' }, { paper: 'past paper 2', assignment: '' }];
  assert.equal(EV.paperName('past paper 1', papers), 'On Liberty');
  assert.equal(EV.paperName('past paper 2', papers), 'Past paper 2');
  assert.equal(EV.paperName('this paper', papers), 'This paper');
  assert.equal(EV.paperName('past paper 3'), 'Past paper 3');
  assert.equal(EV.plural(1, 'word'), '1 word');
  assert.equal(EV.isActive({ kind: 'placeholder' }), false);
  assert.equal(EV.position({ engine_scale: {} }), 'none');
});

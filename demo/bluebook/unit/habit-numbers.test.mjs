import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

// The one formatter for a habit's number on Writing State, the side-by-side
// page and the packet (EvidenceView.readable, driven by the server's
// `display`, original/evidence_features.py display_info): a percent only for
// a true share, a plain unit for a rate, a plain comparison otherwise, and
// never "0 to 1".
const require = createRequire(import.meta.url);
const EV = require('../../original/js/evidence-view.js');
const EC = require('../../original/js/evidence-cards.js')(EV);

const past = (values) => values.map((value, i) => ({ paper: `past paper ${i + 1}`, value }));
function entry(display, engine, plain, over = {}) {
  const [t, ...p] = engine;
  return {
    code: 'x', name: 'Some habit', kind: 'whole_text', in_top_list: true, display,
    engine_scale: { this_paper: t, past_papers: past(p), past_range: [Math.min(...p), Math.max(...p)], difference: t - p[0], outside_past_range: t > Math.max(...p) || t < Math.min(...p) },
    plain: plain ? { unit: 'u', this_paper: plain[0], past_papers: past(plain.slice(1)), past_range: [Math.min(...plain.slice(1)), Math.max(...plain.slice(1))] } : undefined,
    ...over,
  };
}

test('percent: whole numbers, one decimal under 10%, never a negative zero', () => {
  assert.equal(EV.pct(0.38), '38%');
  assert.equal(EV.pct(0.3849), '38%');
  assert.equal(EV.pct(0.072), '7.2%');
  assert.equal(EV.pct(0.0999), '10%');
  assert.equal(EV.pct(0.05), '5%');
  assert.equal(EV.pct(0), '0%');
  assert.equal(EV.pct(1), '100%');
  assert.equal(EV.pct(null), '–');
  const f = entry({ style: 'percent', of: 'of sentences' }, [0.9, 0.1, 0.2], [0.38, 0.2, 0.25]);
  const n = EV.readable(f);
  assert.equal(n.mode, 'percent');
  assert.equal(n.words(n.thisValue), '38% of sentences');
  assert.equal(EV.rangeWords(n), '20% to 25% of sentences');
  assert.equal(EV.oneLine(f), 'This paper 38%; past papers 20% to 25% (of sentences).');
});

test('a share with no plain values is read from the engine only where the engine value is the raw one', () => {
  const raw = entry({ style: 'percent', of: 'of paragraphs', engine_is_raw: true }, [0.5, 0.75, 1]);
  assert.equal(EV.oneLine(raw), 'This paper 50%; past papers 75% to 100% (of paragraphs).');
  // Engine value is a calibration position (bounds are not 0 and 1): never a percent.
  const pos = entry({ style: 'percent', of: 'of sentences' }, [0.5, 0.75, 1]);
  assert.equal(EV.readable(pos).mode, 'compare');
  assert.equal(EV.oneLine(pos), 'This paper is lower than both past papers.');
});

test('rates show their plain unit; a scaled extractor value is shown in its own unit, capped as "or more"', () => {
  const rate = entry({ style: 'unit', unit: 'commas per 100 words' }, [0.2, 0.6, 0.64], [2.43, 8.01, 8.23]);
  assert.equal(EV.oneLine(rate), 'This paper 2.4; past papers 8.0 to 8.2 (commas per 100 words).');
  assert.equal(EV.unitNum(18.44), '18.4');
  assert.equal(EV.unitNum(123.6), '124');
  assert.equal(EV.unitNum(0.4321), '0.43');
  const splice = entry({ style: 'unit', unit: 'likely comma splices per 100 sentences', scale: 30, cap: 1, engine_is_raw: true }, [0.1, 1, 0]);
  const n = EV.readable(splice);
  assert.equal(n.words(0.1), '3.0 likely comma splices per 100 sentences');
  assert.equal(n.show(1), '30.0 or more');
  assert.equal(n.show(0), '0');
});

test('a kind, not an amount, is named', () => {
  const lists = entry({ style: 'category', labels: { 0: 'no lists', 0.2: 'numbered lists', 1: 'lists inside sentences' } }, [0.2, 0, 0], [0.2, 0, 0]);
  const n = EV.readable(lists);
  assert.equal(n.show(0.2), 'numbered lists');
  assert.equal(n.show(0), 'no lists');
  assert.equal(EV.oneLine(lists), 'This paper numbered lists; past papers no lists.');
});

test('no everyday unit: a plain comparison with the past papers, the exact value only as a position', () => {
  const c = (t, p) => entry({ style: 'compare' }, [t, ...p]);
  assert.equal(EV.compareWords(c(0.9, [0.1, 0.2, 0.3])), 'higher than all 3 past papers');
  assert.equal(EV.compareWords(c(0.1, [0.2, 0.3, 0.4])), 'lower than all 3 past papers');
  assert.equal(EV.compareWords(c(0.25, [0.1, 0.3, 0.4])), 'lower than 2 of 3 past papers');
  assert.equal(EV.compareWords(c(0.35, [0.1, 0.3, 0.4])), 'higher than 2 of 3 past papers');
  assert.equal(EV.compareWords(c(0.3, [0.1, 0.3, 0.5])), 'within the range of the past papers');
  assert.equal(EV.compareWords(c(0.3, [0.3, 0.3])), 'the same as both past papers');
  assert.equal(EV.compareWords(c(0.3, [0.1])), 'higher than the past paper');
  const f = c(0.85, [0.4, 0.5, 0.61]);
  assert.equal(EV.oneLine(f), 'This paper is higher than all 3 past papers.');
  assert.equal(EV.differenceLine(f), 'This paper is higher than all 3 past papers on some habit.');
  const d = EV.positionDetail(f);
  assert.match(d, /this paper 0\.85; past papers 0\.40 to 0\.61\.$/);
  assert.match(d, /not a share or a count/);
  assert.doesNotMatch(d, /%|0 to 1/);
});

test('the neutral 0.5 an extractor records for "nothing to count" is said out loud', () => {
  const f = entry({ style: 'percent', of: 'of lists', neutral: 'Original records 50% when there is nothing to count, so 50% can also mean none.', engine_is_raw: true }, [0.5, 0.2, 0.3]);
  assert.match(EV.noteFor(f, []), /50% can also mean none\.$/);
  const g = entry({ style: 'percent', of: 'of lists', neutral: 'n', engine_is_raw: true }, [0.4, 0.2, 0.3]);
  assert.doesNotMatch(EV.noteFor(g, []), /\bn$/);
});

test('hidden habits are not shown, and no output anywhere says "0 to 1"', () => {
  assert.equal(EV.isHidden({ display: { style: 'hidden' } }), true);
  assert.equal(EV.isHidden({}), false);
  const styles = [
    { style: 'percent', of: 'of sentences', engine_is_raw: true }, { style: 'percent', of: 'of sentences' },
    { style: 'unit', unit: 'per 100 words' }, { style: 'unit', unit: 'per 100 sentences', scale: 30, cap: 1, engine_is_raw: true },
    { style: 'category', labels: { 0: 'none' } }, { style: 'compare' }, undefined,
  ];
  for (const display of styles) {
    for (const [engine, plain] of [[[0.85, 0.5, 0.42, 0.61], [3.2, 1.1, 2, 2.5]], [[0.2, 0.5, 0.6, 0.7], null], [[0.5, 0.5, 0.5, 0.5], null]]) {
      const f = entry(display, engine, plain);
      const outs = [EV.oneLine(f), EV.noteFor(f, []), EV.noticeFor(f, []), EV.differenceLine(f), EV.positionDetail(f), EC.card(f, {}), EC.otherList([f], {})];
      for (const o of outs) {
        assert.doesNotMatch(o, /0 to 1|scale from 0|on a scale/i, JSON.stringify(display) + ': ' + o);
        assert.equal(EV.isClean(o), true, o);
      }
      // Only a true share is ever written as a percent (the folded exact position never is).
      const text = outs.join(' ').replace(/<details[\s\S]*?<\/details>/g, '');
      if (!(display && display.style === 'percent')) assert.doesNotMatch(text, /\d%/, JSON.stringify(display) + ': ' + text);
    }
  }
});

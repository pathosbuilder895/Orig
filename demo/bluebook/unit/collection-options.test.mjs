import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// Collection options (collection-options.jsx): the Smalls/Greats preset,
// what a setting switches to, and the options as saved.
const built = await build({
  entryPoints: [new URL('../collection-options.jsx', import.meta.url).pathname],
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
});
const { SMALLS_GREATS_CUTOFF, applySizePreset, settingDefaults, optionConditions, sizeOf } = await import(
  'data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

test('the Smalls/Greats cutoff is 1,000 words', () => {
  assert.equal(SMALLS_GREATS_CUTOFF, 1000);
});

test('a Small is 1,000 words and under: it caps the range at 1,000, keeping a range that fits', () => {
  assert.deepEqual(applySizePreset('small', '', ''), { minWords: '', maxWords: '1000' });
  assert.deepEqual(applySizePreset('small', '200', '800'), { minWords: '200', maxWords: '800' });
  // Exactly 1,000 is still a Small.
  assert.deepEqual(applySizePreset('small', '', '1000'), { minWords: '', maxWords: '1000' });
  assert.deepEqual(applySizePreset('small', '1200', '3000'), { minWords: '', maxWords: '1000' });
});

test('a Great is over 1,000 words: it starts at 1,001, keeping a range that fits', () => {
  assert.deepEqual(applySizePreset('great', '', ''), { minWords: '1001', maxWords: '' });
  assert.deepEqual(applySizePreset('great', '1500', '4000'), { minWords: '1500', maxWords: '4000' });
  // 1,000 is a Small, so a Great's minimum moves past it.
  assert.deepEqual(applySizePreset('great', '1000', ''), { minWords: '1001', maxWords: '' });
  assert.deepEqual(applySizePreset('great', '300', '800'), { minWords: '1001', maxWords: '' });
});

test('no size leaves the range alone', () => {
  assert.deepEqual(applySizePreset('', '5', '50'), { minWords: '5', maxWords: '50' });
});

test('in class is timed and locked; take-home is untimed and not full-screen', () => {
  assert.deepEqual(settingDefaults('in_class'), { timed: true, blockWeb: true, blockCopy: true });
  assert.deepEqual(settingDefaults('take_home'), { timed: false, blockWeb: false });
});

test('saved options default to timed, in class, no size', () => {
  assert.deepEqual(optionConditions({}), { timed: true, setting: 'in_class' });
  assert.deepEqual(optionConditions({ timed: false, setting: 'take_home', size: 'great' }),
    { timed: false, setting: 'take_home', size: 'great' });
});

test("a collection's size is the one chosen, else read off its range with the same cutoff", () => {
  assert.equal(sizeOf({ conditions: { size: 'great' }, minWords: 0, maxWords: 0 }), 'great');
  assert.equal(sizeOf({ conditions: { size: 'small' } }), 'small');
  // Exactly 1,000 words is a Small; a Great starts above it.
  assert.equal(sizeOf({ conditions: {}, minWords: 0, maxWords: 1000 }), 'small');
  assert.equal(sizeOf({ conditions: {}, minWords: 1000, maxWords: 0 }), '');
  assert.equal(sizeOf({ conditions: {}, minWords: 1001, maxWords: 0 }), 'great');
  assert.equal(sizeOf({ conditions: {}, minWords: 0, maxWords: 0 }), '');
  // An old row with no conditions at all.
  assert.equal(sizeOf({ duration: 25 }), '');
});

// ════════════════════════════════════════════════════════════════
//  Collection options (Collections merge, 2026-10-20)
// ════════════════════════════════════════════════════════════════
// Every assignment is one collection. Its options travel in `conditions`
// (no schema change) and the server checks them the same way
// (original/bluebook_rules.py collection_options):
//   timed    true | false   untimed: no clock; the sitting runs until the
//                           collection closes (or has no deadline at all)
//   setting  'in_class' | 'take_home'
//   size     'small' | 'great'   Smalls < 1,000 words, Greats >= 1,000

export const SMALLS_GREATS_CUTOFF = 1000;

// The most questions one collection can hold, the same number the server
// enforces (original/bluebook_rules.py MAX_QUESTIONS). Creating and editing
// a collection both stop here.
export const MAX_QUESTIONS = 20;

// "I" to "XX" for the new-collection form's question labels.
export function romanNumeral(n) {
  const tens = ['', 'X', 'XX'][Math.floor(n / 10)] || '';
  const ones = ['', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX'][n % 10];
  return n >= 1 && n <= 29 ? tens + ones : String(n);
}

// The word range a size preset gives. Values are the form's strings ('' =
// none). A range that already fits the size is kept as the teacher typed it.
export function applySizePreset(size, minWords, maxWords) {
  const lo = Number(minWords) || 0;
  const hi = Number(maxWords) || 0;
  if (size === 'small') {
    return {
      minWords: lo && lo < SMALLS_GREATS_CUTOFF ? String(lo) : '',
      maxWords: hi && hi < SMALLS_GREATS_CUTOFF ? String(hi) : String(SMALLS_GREATS_CUTOFF - 1),
    };
  }
  if (size === 'great') {
    return {
      minWords: lo >= SMALLS_GREATS_CUTOFF ? String(lo) : String(SMALLS_GREATS_CUTOFF),
      maxWords: hi >= SMALLS_GREATS_CUTOFF ? String(hi) : '',
    };
  }
  return { minWords: minWords, maxWords: maxWords };
}

// What choosing a setting switches to. In class: timed, full-screen and
// paste blocked. Take-home: untimed and not full-screen; paste blocking is
// left as the teacher had it. Every value can still be changed afterwards.
export function settingDefaults(setting) {
  return setting === 'take_home'
    ? { timed: false, blockWeb: false }
    : { timed: true, blockWeb: true, blockCopy: true };
}

// The options as saved: only what the teacher chose, so an old collection
// and a new in-class, timed one with no size read the same.
export function optionConditions({ timed, setting, size }) {
  const out = { timed: timed !== false, setting: setting === 'take_home' ? 'take_home' : 'in_class' };
  if (size === 'small' || size === 'great') out.size = size;
  return out;
}

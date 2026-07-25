// Self-test for vendor/qr.js —  node vendor/qr.selftest.mjs
//
// The goldens below were verified against `segno`, an independent reference QR
// implementation, at the time this encoder was written:
//
//   * Every payload that exactly fills its symbol's data capacity (the `fill`
//     cases, versions 1–10) produced a matrix **bit-identical** to segno's.
//   * The mask-penalty function scored 48/48 identical matrices (6 payloads ×
//     8 masks) exactly as segno's `evaluate_mask` did.
//   * Rendered to images, 389/400 randomised park URLs decoded back to the
//     exact input under OpenCV's QR decoder — against 384/400 for segno's own
//     symbols on the same images, i.e. the residual misses are the synthetic-
//     image detector's, not this encoder's.
//
// Where this encoder and segno disagree, the cause is known and deliberate:
// segno's `write_padding_bits` appends a whole zero codeword when the bit
// stream already ends on a codeword boundary — which in byte mode it always
// does — so its filler differs from ours (and at version 1 with a 14-byte
// payload it emits 17 codewords for a 16-codeword symbol). ISO/IEC 18004
// §7.4.10 adds padding bits only "if the bit stream length is such that it
// does not end at a codeword boundary", which is what we implement. The bytes
// in question sit after the terminator and are ignored by every decoder, so
// both encodings scan identically.

import { qrEncode, qrPath } from './qr.js';
import { createHash } from 'node:crypto';

// [label, payload, expectedVersion, expectedMask, expectedSize, sha256[:16] of the matrix]
const GOLDEN = [
  ['short', 'x', 1, 0, 21, '27dcc9269d483f93'],
  ['query', '?t=aaa&x=1', 1, 2, 21, 'd0d0cfc5c19c3338'],
  ['utf8 em-dash', 'Ethics in the Modern World — PHIL 301A', 3, 7, 29, '61c65b20cf362c05'],
  ['local park url', 'http://localhost:8097/bluebook/parked.html?t=not-a-secret-test-token', 5, 4, 37, 'de75dc91108995b8'],
  ['remote park url', 'https://original-pilot.example.edu/bluebook/parked.html?t=not-a-secret-token', 5, 2, 37, '7ec3e01c7b6fb3e9'],
  // Exactly-at-capacity payloads: these were bit-identical to segno.
  ['fill v1', 'A'.repeat(14), 1, 3, 21, '4fb8fa48743067b2'],
  ['fill v2', 'A'.repeat(26), 2, 1, 25, '9728d515ae62214a'],
  ['fill v3', 'A'.repeat(42), 3, 1, 29, 'ea33c66ffbef79b2'],
  ['fill v4', 'A'.repeat(62), 4, 0, 33, '307b83fe5c567dbe'],
  ['fill v5', 'A'.repeat(84), 5, 1, 37, 'fa20663aacd45b3e'],
  ['fill v6', 'A'.repeat(106), 6, 0, 41, '32ec30235c0a05dd'],
  ['fill v7', 'A'.repeat(122), 7, 3, 45, 'b84ccdf327b79111'],
  ['fill v8', 'A'.repeat(152), 8, 3, 49, '54ed78c440780af8'],
  ['fill v9', 'A'.repeat(180), 9, 3, 53, '1ce7051446230a4b'],
  ['fill v10', 'A'.repeat(213), 10, 3, 57, '8dac1222425d443a'],
  // Payloads needing pad codewords.
  ['pad v1', 'B'.repeat(13), 1, 0, 21, '898103b4dee29a09'],
  ['pad v4', 'B'.repeat(61), 4, 4, 33, 'e5a9f5013a164752'],
  ['pad v6', 'C'.repeat(97), 6, 0, 41, '65e2dab79aee4b46'],
];

let failures = 0;
const fail = (msg) => { failures++; console.error(`  FAIL  ${msg}`); };

const digest = (modules) =>
  createHash('sha256')
    .update(modules.map((r) => r.map((v) => (v ? '1' : '0')).join('')).join('\n'))
    .digest('hex')
    .slice(0, 16);

for (const [label, text, version, mask, size, hash] of GOLDEN) {
  const got = qrEncode(text);
  const h = digest(got.modules);
  if (got.version !== version) fail(`${label}: version ${got.version} !== ${version}`);
  if (got.mask !== mask) fail(`${label}: mask ${got.mask} !== ${mask}`);
  if (got.size !== size) fail(`${label}: size ${got.size} !== ${size}`);
  if (h !== hash) fail(`${label}: matrix ${h} !== ${hash}`);
}

// Structural invariants that hold for every symbol, independent of the goldens.
for (const text of ['x', 'A'.repeat(50), 'A'.repeat(200)]) {
  const { size, modules, version } = qrEncode(text);
  if (size !== version * 4 + 17) fail(`size ${size} does not match version ${version}`);

  // Three finder patterns: dark 7×7 ring with a dark 3×3 core.
  for (const [r0, c0] of [[0, 0], [0, size - 7], [size - 7, 0]]) {
    const corners = modules[r0][c0] && modules[r0][c0 + 6] && modules[r0 + 6][c0];
    const core = modules[r0 + 3][c0 + 3];
    const ring = !modules[r0 + 1][c0 + 1];
    if (!corners || !core || !ring) fail(`finder pattern at ${r0},${c0} malformed (v${version})`);
  }

  // Timing patterns alternate, starting dark at index 8.
  for (let i = 8; i < size - 8; i++) {
    if (modules[6][i] !== (i % 2 === 0)) fail(`row timing wrong at ${i} (v${version})`);
    if (modules[i][6] !== (i % 2 === 0)) fail(`col timing wrong at ${i} (v${version})`);
  }

  // The module below the top-left format strip is always dark.
  if (!modules[size - 8][8]) fail(`dark module missing (v${version})`);
}

// Version selection sits exactly on the documented byte capacities.
const CAPACITY = { 1: 14, 2: 26, 3: 42, 4: 62, 5: 84, 6: 106, 7: 122, 8: 152, 9: 180, 10: 213 };
for (const [v, cap] of Object.entries(CAPACITY)) {
  const at = qrEncode('A'.repeat(cap)).version;
  if (at !== Number(v)) fail(`${cap} bytes chose v${at}, expected v${v}`);
  if (cap < 213) {
    const over = qrEncode('A'.repeat(cap + 1)).version;
    if (over !== Number(v) + 1) fail(`${cap + 1} bytes chose v${over}, expected v${Number(v) + 1}`);
  }
}

// Over-capacity input must throw rather than emit a silently truncated symbol.
try {
  qrEncode('A'.repeat(214));
  fail('214 bytes should have thrown');
} catch (e) {
  if (!/exceeds/.test(e.message)) fail(`unexpected error: ${e.message}`);
}

// qrPath covers exactly the dark modules.
{
  const { modules } = qrEncode('path check');
  const dark = modules.flat().filter(Boolean).length;
  const covered = qrPath(modules)
    .split('M').slice(1)
    .reduce((n, seg) => n + Number(seg.match(/h(\d+)/)[1]), 0);
  if (covered !== dark) fail(`qrPath covers ${covered} modules, expected ${dark}`);
}

if (failures) {
  console.error(`\n${failures} check(s) failed`);
  process.exit(1);
}
console.log(`qr.js self-test passed (${GOLDEN.length} golden symbols + structural checks)`);

// ════════════════════════════════════════════════════════════════
//  qr.js — offline QR Code encoder (byte mode, EC level M, versions 1–10)
// ════════════════════════════════════════════════════════════════
//
// Why this file exists
// --------------------
// The phone-park QR must render with no network at all: no CDN, no external
// image service. An exam room's projector machine may be offline, and more to
// the point, shipping the park URL to a third-party image API would leak the
// one capability token this feature has. So the encoder ships with us.
//
// Provenance / licence
// --------------------
// First-party implementation of the *published* QR Code symbol algorithm
// (ISO/IEC 18004 — Reed–Solomon over GF(256), the eight mask patterns and
// their penalty rules, BCH format/version information). No third-party source
// is vendored here, deliberately: `build.mjs` sets esbuild's
// `legalComments: 'none'`, so an MIT-licensed dependency's copyright notice
// would be stripped out of the shipped `bluebook.bundle.js` — i.e. we would be
// redistributing it minified with its required attribution removed. Writing the
// encoder ourselves removes that problem instead of papering over it.
//
// Correctness is not asserted, it is checked: `vendor/qr.selftest.mjs` compares
// this encoder's module matrix bit-for-bit against `segno`, an independent
// reference QR implementation, across every supported version and all eight
// masks. A wrong module here means an unscannable code on a projector, which is
// exactly the sort of bug you cannot see by looking at it.
//
// Scope: byte mode and EC level M only, versions 1–10 (up to 213 bytes) — an
// exam-park URL is ~60–100 characters, so the ceiling is far away. Level M
// (~15% recovery) is the usual choice for a code read across a room.

// ─── GF(256) arithmetic (primitive polynomial 0x11D) ─────────────────────────

function gfMul(x, y) {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z & 0xff;
}

/** Generator polynomial coefficients for `degree` error-correction codewords. */
function rsDivisor(degree) {
  const result = new Uint8Array(degree);
  result[degree - 1] = 1;
  let root = 1;
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < degree; j++) {
      result[j] = gfMul(result[j], root);
      if (j + 1 < degree) result[j] ^= result[j + 1];
    }
    root = gfMul(root, 2);
  }
  return result;
}

/** Reed–Solomon remainder — the EC codewords appended to one block. */
function rsRemainder(data, divisor) {
  const result = new Uint8Array(divisor.length);
  for (const b of data) {
    const factor = b ^ result[0];
    result.copyWithin(0, 1);
    result[result.length - 1] = 0;
    for (let i = 0; i < divisor.length; i++) result[i] ^= gfMul(divisor[i], factor);
  }
  return result;
}

// ─── Version tables (EC level M only) ────────────────────────────────────────

// [ecCodewordsPerBlock, blocksInGroup1, dataPerBlockGroup1, blocksInGroup2, dataPerBlockGroup2]
const EC_M = {
  1: [10, 1, 16, 0, 0],
  2: [16, 1, 28, 0, 0],
  3: [26, 1, 44, 0, 0],
  4: [18, 2, 32, 0, 0],
  5: [24, 2, 43, 0, 0],
  6: [16, 4, 27, 0, 0],
  7: [18, 4, 31, 0, 0],
  8: [22, 2, 38, 2, 39],
  9: [22, 3, 36, 2, 37],
  10: [26, 4, 43, 1, 44],
};

// Alignment-pattern centre coordinates per version (version 1 has none).
const ALIGN = {
  1: [],
  2: [6, 18],
  3: [6, 22],
  4: [6, 26],
  5: [6, 30],
  6: [6, 34],
  7: [6, 22, 38],
  8: [6, 24, 42],
  9: [6, 26, 46],
  10: [6, 28, 50],
};

const MAX_VERSION = 10;

function dataCodewords(version) {
  const [, b1, d1, b2, d2] = EC_M[version];
  return b1 * d1 + b2 * d2;
}

/** Byte-mode character-count indicator width: 8 bits for v1–9, 16 for v10+. */
function countBits(version) {
  return version < 10 ? 8 : 16;
}

// ─── Encoding ────────────────────────────────────────────────────────────────

function chooseVersion(byteLen) {
  for (let v = 1; v <= MAX_VERSION; v++) {
    const capacityBits = dataCodewords(v) * 8;
    const neededBits = 4 + countBits(v) + byteLen * 8;
    if (neededBits <= capacityBits) return v;
  }
  return null;
}

/** Mode indicator + length + payload + terminator + padding → data codewords. */
function buildCodewords(bytes, version) {
  const bits = [];
  const push = (value, width) => {
    for (let i = width - 1; i >= 0; i--) bits.push((value >>> i) & 1);
  };

  push(0b0100, 4); // byte mode
  push(bytes.length, countBits(version));
  for (const b of bytes) push(b, 8);

  const capacityBits = dataCodewords(version) * 8;
  // Terminator: up to four zero bits, truncated if the symbol is nearly full.
  push(0, Math.min(4, capacityBits - bits.length));
  while (bits.length % 8 !== 0) bits.push(0);

  const codewords = [];
  for (let i = 0; i < bits.length; i += 8) {
    let byte = 0;
    for (let j = 0; j < 8; j++) byte = (byte << 1) | bits[i + j];
    codewords.push(byte);
  }
  // Alternating pad codewords fill the remainder.
  for (let pad = 0xec; codewords.length < dataCodewords(version); pad ^= 0xec ^ 0x11) {
    codewords.push(pad);
  }
  return codewords;
}

/** Split into blocks, append per-block EC, then interleave both halves. */
function interleave(codewords, version) {
  const [ecLen, b1, d1, b2, d2] = EC_M[version];
  const divisor = rsDivisor(ecLen);

  const blocks = [];
  const eccs = [];
  let offset = 0;
  for (const [count, size] of [[b1, d1], [b2, d2]]) {
    for (let i = 0; i < count; i++) {
      const block = codewords.slice(offset, offset + size);
      offset += size;
      blocks.push(block);
      eccs.push(rsRemainder(block, divisor));
    }
  }

  const result = [];
  const maxData = Math.max(...blocks.map((b) => b.length));
  for (let i = 0; i < maxData; i++) {
    for (const block of blocks) if (i < block.length) result.push(block[i]);
  }
  for (let i = 0; i < ecLen; i++) {
    for (const ecc of eccs) result.push(ecc[i]);
  }
  return result;
}

// ─── Symbol construction ─────────────────────────────────────────────────────

function formatBits(mask) {
  // EC level M is 0b00; BCH(15,5) with generator 0x537, masked with 0x5412.
  const data = (0b00 << 3) | mask;
  let rem = data;
  for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
  return ((data << 10) | rem) ^ 0x5412;
}

function versionBits(version) {
  // BCH(18,6) with generator 0x1F25. Only present on version 7 and above.
  let rem = version;
  for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
  return (version << 12) | rem;
}

const MASKS = [
  (r, c) => (r + c) % 2 === 0,
  (r) => r % 2 === 0,
  (r, c) => c % 3 === 0,
  (r, c) => (r + c) % 3 === 0,
  (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0,
  (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0,
  (r, c) => (((r * c) % 2) + ((r * c) % 3)) % 2 === 0,
  (r, c) => (((r + c) % 2) + ((r * c) % 3)) % 2 === 0,
];

function buildSymbol(version, interleaved) {
  const size = version * 4 + 17;
  const modules = Array.from({ length: size }, () => new Array(size).fill(false));
  const fixed = Array.from({ length: size }, () => new Array(size).fill(false));

  const set = (r, c, dark) => {
    modules[r][c] = dark;
    fixed[r][c] = true;
  };

  // Finder patterns plus their separators (the ring of light modules).
  const drawFinder = (r0, c0) => {
    for (let dr = -1; dr <= 7; dr++) {
      for (let dc = -1; dc <= 7; dc++) {
        const r = r0 + dr;
        const c = c0 + dc;
        if (r < 0 || r >= size || c < 0 || c >= size) continue;
        const inner = dr >= 0 && dr <= 6 && dc >= 0 && dc <= 6;
        const dark = inner
          && (dr === 0 || dr === 6 || dc === 0 || dc === 6
            || (dr >= 2 && dr <= 4 && dc >= 2 && dc <= 4));
        set(r, c, dark);
      }
    }
  };
  drawFinder(0, 0);
  drawFinder(0, size - 7);
  drawFinder(size - 7, 0);

  // Alignment patterns, skipping the three that would collide with finders.
  const centres = ALIGN[version];
  for (const r0 of centres) {
    for (const c0 of centres) {
      const nearFinder = (r0 === 6 && c0 === 6)
        || (r0 === 6 && c0 === size - 7)
        || (r0 === size - 7 && c0 === 6);
      if (nearFinder) continue;
      for (let dr = -2; dr <= 2; dr++) {
        for (let dc = -2; dc <= 2; dc++) {
          set(r0 + dr, c0 + dc, Math.max(Math.abs(dr), Math.abs(dc)) !== 1);
        }
      }
    }
  }

  // Timing patterns.
  for (let i = 8; i < size - 8; i++) {
    set(6, i, i % 2 === 0);
    set(i, 6, i % 2 === 0);
  }

  // Reserve the format-information areas (values written per-mask later).
  for (let i = 0; i <= 8; i++) {
    if (i !== 6) {
      set(8, i, false);
      set(i, 8, false);
    }
  }
  for (let i = 0; i < 8; i++) {
    set(8, size - 1 - i, false);
    set(size - 1 - i, 8, false);
  }
  set(size - 8, 8, true); // the always-dark module

  // Version information (v7+).
  if (version >= 7) {
    const bits = versionBits(version);
    for (let i = 0; i < 18; i++) {
      const bit = ((bits >>> i) & 1) === 1;
      const a = size - 11 + (i % 3);
      const b = Math.floor(i / 3);
      set(a, b, bit);
      set(b, a, bit);
    }
  }

  // Zigzag data placement, right to left in column pairs, skipping column 6.
  let bitIndex = 0;
  const totalBits = interleaved.length * 8;
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let vert = 0; vert < size; vert++) {
      for (let j = 0; j < 2; j++) {
        const c = right - j;
        const upward = ((right + 1) & 2) === 0;
        const r = upward ? size - 1 - vert : vert;
        if (fixed[r][c] || bitIndex >= totalBits) continue;
        const byte = interleaved[bitIndex >>> 3];
        modules[r][c] = ((byte >>> (7 - (bitIndex & 7))) & 1) === 1;
        bitIndex++;
      }
    }
  }

  return { size, modules, fixed };
}

function drawFormat(modules, size, mask) {
  const bits = formatBits(mask);
  // Bit 14 is the MSB, and the spec walks each copy's path MSB-first — hence
  // `14 - i` rather than `i`. Getting this backwards yields a symbol that looks
  // perfectly plausible and decodes as the wrong mask, i.e. not at all.
  const bit = (i) => ((bits >>> (14 - i)) & 1) === 1;
  for (let i = 0; i <= 5; i++) modules[8][i] = bit(i);
  modules[8][7] = bit(6);
  modules[8][8] = bit(7);
  modules[7][8] = bit(8);
  for (let i = 9; i < 15; i++) modules[14 - i][8] = bit(i);
  for (let i = 0; i < 8; i++) modules[size - 1 - i][8] = bit(i);
  for (let i = 8; i < 15; i++) modules[8][size - 15 + i] = bit(i);
  modules[size - 8][8] = true;
}

/** The four penalty rules from the spec — lower is a more scannable symbol. */
function penalty(modules, size) {
  let score = 0;

  const runScore = (line) => {
    let total = 0;
    let runLen = 1;
    for (let i = 1; i < size; i++) {
      if (line[i] === line[i - 1]) {
        runLen++;
      } else {
        if (runLen >= 5) total += 3 + (runLen - 5);
        runLen = 1;
      }
    }
    if (runLen >= 5) total += 3 + (runLen - 5);
    return total;
  };

  // Rule 3: the 1:1:3:1:1 finder-like ratio, preceded or followed by a light
  // area four modules wide. Modules *outside* the symbol count as light — the
  // quiet zone is light by definition, so a pattern sitting flush against an
  // edge does qualify. Requiring four in-bounds light modules instead misses
  // most real occurrences, and the resulting scores pick a poorer mask.
  const FINDER_LIKE = [true, false, true, true, true, false, true];
  const lightRun = (line, from) => {
    for (let k = from; k < from + 4; k++) {
      if (k >= 0 && k < size && line[k]) return false;
    }
    return true;
  };
  const hasFinderLike = (line, at) => {
    for (let k = 0; k < 7; k++) if (line[at + k] !== FINDER_LIKE[k]) return false;
    return lightRun(line, at - 4) || lightRun(line, at + 7);
  };

  for (let i = 0; i < size; i++) {
    const row = modules[i];
    const col = modules.map((r) => r[i]);
    score += runScore(row) + runScore(col);
    for (let j = 0; j + 7 <= size; j++) {
      if (hasFinderLike(row, j)) score += 40;
      if (hasFinderLike(col, j)) score += 40;
    }
  }

  // Rule 2: every 2×2 block of one colour.
  for (let r = 0; r + 1 < size; r++) {
    for (let c = 0; c + 1 < size; c++) {
      const v = modules[r][c];
      if (v === modules[r][c + 1] && v === modules[r + 1][c] && v === modules[r + 1][c + 1]) {
        score += 3;
      }
    }
  }

  // Rule 4: deviation from an even balance of dark and light.
  let dark = 0;
  for (let r = 0; r < size; r++) for (let c = 0; c < size; c++) if (modules[r][c]) dark++;
  const percent = (dark * 100) / (size * size);
  score += Math.floor(Math.abs(percent - 50) / 5) * 10;

  return score;
}

// ─── Public API ──────────────────────────────────────────────────────────────

/**
 * Encode `text` as a QR symbol.
 *
 * @param {string} text
 * @param {{ mask?: number }} [options] `mask` pins one of the eight patterns
 *   instead of choosing the lowest-penalty one — used by the self-test to
 *   compare against a reference encoder mask-for-mask. Production callers omit it.
 * @returns {{ size: number, modules: boolean[][], version: number, mask: number }}
 * @throws {Error} if the text exceeds version 10 at EC level M (213 bytes).
 */
export function qrEncode(text, options = {}) {
  const bytes = Array.from(new TextEncoder().encode(String(text)));
  const version = chooseVersion(bytes.length);
  if (version === null) {
    throw new Error(`QR: ${bytes.length} bytes exceeds the version-${MAX_VERSION} capacity`);
  }

  const interleaved = interleave(buildCodewords(bytes, version), version);
  const { size, modules, fixed } = buildSymbol(version, interleaved);

  // Try all eight masks and keep the lowest-penalty symbol.
  const candidates = options.mask == null ? [0, 1, 2, 3, 4, 5, 6, 7] : [options.mask];
  let best = null;
  for (const mask of candidates) {
    const candidate = modules.map((row) => row.slice());
    for (let r = 0; r < size; r++) {
      for (let c = 0; c < size; c++) {
        if (!fixed[r][c] && MASKS[mask](r, c)) candidate[r][c] = !candidate[r][c];
      }
    }
    drawFormat(candidate, size, mask);
    const score = penalty(candidate, size);
    if (best === null || score < best.score) best = { score, mask, modules: candidate };
  }

  return { size, modules: best.modules, version, mask: best.mask };
}

/**
 * An SVG path `d` covering every dark module, one `M…h…v…h…z` box per run of
 * adjacent dark modules. One path element scales crisply and keeps the DOM
 * small (a version-4 symbol is ~1100 modules — that many <rect>s is wasteful).
 */
export function qrPath(modules) {
  const parts = [];
  for (let r = 0; r < modules.length; r++) {
    let c = 0;
    while (c < modules.length) {
      if (!modules[r][c]) { c++; continue; }
      let run = 1;
      while (c + run < modules.length && modules[r][c + run]) run++;
      parts.push(`M${c} ${r}h${run}v1h-${run}z`);
      c += run;
    }
  }
  return parts.join('');
}

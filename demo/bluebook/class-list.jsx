// ════════════════════════════════════════════════════════════════
//  BLUEBOOK, Class list upload: reading a roster file in the browser
//  A Canvas gradebook export, or any CSV with name and email columns.
//  Pure functions (no React, no DOM), so the file never leaves this
//  computer: the roster screen sends only the names and emails it keeps.
// ════════════════════════════════════════════════════════════════

export const MAX_CLASS_LIST_BYTES = 2 * 1024 * 1024;
export const MAX_CLASS_LIST_ROWS = 5000;

// One CSV record per array, every cell a string. Handles quoted cells
// (with doubled quotes, separators and line breaks inside), CRLF, CR or LF
// line ends, and a leading byte-order mark.
export function parseCsv(text, delimiter = ',') {
  const s = String(text || '').replace(/^﻿/, '');
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (quoted) {
      if (ch === '"') {
        if (s[i + 1] === '"') { cell += '"'; i++; } else quoted = false;
      } else cell += ch;
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === delimiter) {
      row.push(cell); cell = '';
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && s[i + 1] === '\n') i++;
      row.push(cell); rows.push(row); row = []; cell = '';
    } else cell += ch;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

// The separator the header line uses most: comma, semicolon (spreadsheets
// in many European locales) or tab. Quoted text does not count.
export function detectDelimiter(text) {
  const s = String(text || '').replace(/^﻿/, '');
  const counts = { ',': 0, ';': 0, '\t': 0 };
  let quoted = false;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (ch === '"') quoted = !quoted;
    else if (!quoted && (ch === '\n' || ch === '\r')) break;
    else if (!quoted && ch in counts) counts[ch]++;
  }
  return Object.keys(counts).reduce((best, d) => (counts[d] > counts[best] ? d : best), ',');
}

const norm = h => String(h || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

// Header spellings for each kind of column, most specific first.
const HEADERS = {
  email: ['email', 'e mail', 'email address', 'e mail address', 'student email', 'primary email', 'mail'],
  name: ['name', 'student name', 'full name', 'display name', 'sortable name', 'student'],
  first: ['first name', 'given name', 'firstname', 'first'],
  last: ['last name', 'surname', 'family name', 'lastname', 'last'],
  // Values that can be turned into an email address: login first.
  idCol: ['sis login id', 'login id', 'login', 'username', 'user name', 'sis user id', 'student id', 'sis id', 'id'],
};

function findColumn(headers, names) {
  const n = headers.map(norm);
  for (const want of names) {
    const i = n.indexOf(want);
    if (i >= 0) return i;
  }
  return -1;
}

// A Canvas gradebook export: Student, ID, SIS User ID, SIS Login ID, Section...
export function isCanvasExport(headers) {
  const n = (headers || []).map(norm);
  return n.includes('student') && n.includes('id') && n.includes('section');
}

const EMAIL_RE = /^[^\s@,;<>"]+@[^\s@,;<>"]+\.[^\s@,;<>"]+$/;
export function looksLikeEmail(s) {
  return String(s || '').length <= 254 && EMAIL_RE.test(String(s || ''));
}

// Guess which column holds what. Any index may be -1 (no such column).
// `last` is set only when names come as separate first and last columns.
export function detectColumns(headers, rows = []) {
  const map = {
    name: findColumn(headers, HEADERS.name),
    last: -1,
    email: findColumn(headers, HEADERS.email),
    idCol: findColumn(headers, HEADERS.idCol),
  };
  if (map.name < 0) {
    const first = findColumn(headers, HEADERS.first);
    const last = findColumn(headers, HEADERS.last);
    if (first >= 0) { map.name = first; map.last = last; }
  }
  if (map.email < 0) {
    // No email header: a column whose values are mostly addresses will do
    // (some schools set SIS Login ID to the student's email address).
    const sample = rows.slice(0, 50);
    let best = -1;
    let bestHits = 0;
    (headers || []).forEach((_, c) => {
      const hits = sample.filter(r => looksLikeEmail(String(r[c] || '').trim())).length;
      if (hits > bestHits) { best = c; bestHits = hits; }
    });
    if (best >= 0 && bestHits * 2 >= sample.filter(r => r.some(v => String(v).trim())).length) map.email = best;
  }
  if (map.idCol === map.email) map.idCol = -1;
  return map;
}

// Rows Canvas adds that are not students: "Points Possible" (sometimes
// indented), the posting-policy rows with no student name, and the course's
// test student from Student View.
function canvasExtraRow(name) {
  const n = name.trim().toLowerCase();
  if (n === 'points possible') return 'Points possible row';
  if (n === 'student, test' || n === 'test student') return 'Test student';
  return '';
}

// "Doe, Jane" -> "Jane Doe" (Canvas lists students last name first).
export function firstNameFirst(name) {
  const parts = String(name || '').split(',');
  if (parts.length !== 2) return String(name || '').trim();
  const [last, first] = parts.map(p => p.trim());
  return first && last ? `${first} ${last}` : (first || last);
}

function cleanDomain(domain) {
  return String(domain || '').trim().toLowerCase().replace(/^@+/, '');
}

// Everything the preview shows, from the file's records (header first), the
// column choice, and the email domain for files with no email column.
// `rosterEmails` are the course's current students (lower case).
//
// Returns { headers, canvas, fresh, existing, problems, skipped,
// needsEmailFormat }: fresh and existing are [{ row, name, email, made }],
// problems are [{ row, name, reason }], skipped are [{ row, reason }].
// `row` is the record number counting the header as 1, as a spreadsheet
// shows it.
export function buildPreview(records, map, { domain = '', rosterEmails = [] } = {}) {
  const [headers = [], ...rows] = records || [];
  const canvas = isCanvasExport(headers);
  const swap = canvas || norm(headers[map.name]) === 'sortable name';
  const onRoster = new Set((rosterEmails || []).map(e => String(e || '').toLowerCase()));
  const dom = cleanDomain(domain);
  const out = { headers, canvas, fresh: [], existing: [], problems: [], skipped: [], needsEmailFormat: false };
  const seen = new Map();
  const cellOf = (r, c) => (c >= 0 ? String(r[c] == null ? '' : r[c]).trim() : '');
  rows.slice(0, MAX_CLASS_LIST_ROWS).forEach((r, i) => {
    const rowNo = i + 2;
    if (!r.some(v => String(v).trim())) return;  // blank line
    let name = cellOf(r, map.name);
    const extra = canvasExtraRow(name);
    if (extra) { out.skipped.push({ row: rowNo, reason: extra }); return; }
    let email = cellOf(r, map.email).replace(/^<|>$/g, '').toLowerCase();
    const id = cellOf(r, map.idCol);
    if (canvas && !name && !email && !id) { out.skipped.push({ row: rowNo, reason: 'No student on this row' }); return; }
    if (map.last >= 0) name = [name, cellOf(r, map.last)].filter(Boolean).join(' ');
    else if (swap) name = firstNameFirst(name);
    name = name.slice(0, 120);
    let made = false;
    if (!email && id) {
      if (id.includes('@')) email = id.toLowerCase();
      else if (dom) { email = `${id}@${dom}`.toLowerCase(); made = true; }
      else out.needsEmailFormat = true;
    }
    if (!email) { out.problems.push({ row: rowNo, name, reason: 'No email address' }); return; }
    if (!looksLikeEmail(email)) { out.problems.push({ row: rowNo, name, reason: `Not a valid email address: ${email}` }); return; }
    if (seen.has(email)) { out.problems.push({ row: rowNo, name, reason: `Listed twice in this file (also row ${seen.get(email)})` }); return; }
    seen.set(email, rowNo);
    (onRoster.has(email) ? out.existing : out.fresh).push({ row: rowNo, name, email, made });
  });
  return out;
}

// Read a file's text, refusing anything too large to be a class list.
export function readClassList(file) {
  return new Promise((resolve, reject) => {
    if (!file) { reject(new Error('Choose a CSV file.')); return; }
    if (file.size > MAX_CLASS_LIST_BYTES) { reject(new Error('That file is too large for a class list. Export only the students, as CSV.')); return; }
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('We could not read that file. Save it as CSV and try again.'));
    reader.readAsText(file);
  });
}

// Records from a file's text, with its separator detected.
export function recordsFromText(text) {
  return parseCsv(text, detectDelimiter(text));
}

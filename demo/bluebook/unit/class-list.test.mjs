import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// Upload class list (class-list.jsx): a Canvas gradebook export, a simple
// CSV with name and email columns, and the rows neither should import. The
// file is read in the browser only; the roster screen sends the `fresh` rows
// to the same "Add students" route the paste box uses.
const built = await build({
  entryPoints: [new URL('../class-list.jsx', import.meta.url).pathname],
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic', logLevel: 'silent',
});
const m = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

const preview = (text, opts = {}, override = {}) => {
  const records = m.recordsFromText(text);
  const map = { ...m.detectColumns(records[0], records.slice(1)), ...override };
  return { map, ...m.buildPreview(records, map, opts) };
};
const emails = rows => rows.map(r => r.email);

// What Canvas's Grades > Export gives: "Last, First" names, an indented
// Points Possible row, a posting-policy row with no student, and the
// course's test student. No email column.
const CANVAS = [
  'Student,ID,SIS User ID,SIS Login ID,Section,Essay 1 (101),Current Score',
  '    Points Possible,,,,,10.00,(read only)',
  ',,,,,Manual Posting,',
  '"Lovelace, Ada",1001,S1001,alovelace,Ethics 101,9.00,90.00',
  '"Hopper, Grace",1002,S1002,ghopper,Ethics 101,8.00,80.00',
  '"Student, Test",9999,,,Ethics 101,,',
  '"Turing, Alan",1003,S1003,,Ethics 101,,',
].join('\r\n');

test('a Canvas export is recognised and its extra rows are skipped', () => {
  const p = preview(CANVAS);
  assert.equal(p.canvas, true);
  assert.deepEqual(p.skipped.map(s => s.reason), ['Points possible row', 'No student on this row', 'Test student']);
  assert.deepEqual(p.skipped.map(s => s.row), [2, 3, 6]);
});

test('a Canvas export with logins but no emails asks for an email format', () => {
  const p = preview(CANVAS);
  assert.equal(p.map.email, -1);
  assert.equal(p.map.idCol, 3, 'SIS Login ID, not the numeric Canvas ID');
  assert.equal(p.needsEmailFormat, true);
  assert.deepEqual(p.fresh, []);
  // Without a format, each student is a row with no email, by name.
  assert.deepEqual(p.problems.map(x => [x.row, x.name, x.reason]), [
    [4, 'Ada Lovelace', 'No email address'],
    [5, 'Grace Hopper', 'No email address'],
    [7, 'Alan Turing', 'No email address'],
  ]);
});

test('given a domain, logins become emails, and a student with no login is reported', () => {
  const p = preview(CANVAS, { domain: '@School.edu ' });
  assert.equal(p.needsEmailFormat, false);
  assert.deepEqual(p.fresh, [
    { row: 4, name: 'Ada Lovelace', email: 'alovelace@school.edu', made: true },
    { row: 5, name: 'Grace Hopper', email: 'ghopper@school.edu', made: true },
  ]);
  // Alan has an SIS User ID but no login; the teacher can pick that column.
  assert.deepEqual(p.problems.map(x => [x.name, x.reason]), [['Alan Turing', 'No email address']]);
  const bySis = preview(CANVAS, { domain: 'school.edu' }, { idCol: 2 });
  assert.deepEqual(emails(bySis.fresh), ['s1001@school.edu', 's1002@school.edu', 's1003@school.edu']);
});

test('a Canvas export whose login is the email address uses it as is', () => {
  const text = [
    'Student,ID,SIS User ID,SIS Login ID,Section,Essay 1',
    'Points Possible,,,,,10',
    '"Lovelace, Ada",1001,S1001,ada@school.edu,Ethics,9',
    '"Hopper, Grace",1002,S1002,GHopper@School.edu,Ethics,8',
  ].join('\n');
  const p = preview(text);
  assert.equal(p.map.email, 3, 'a column of addresses is the email column');
  assert.equal(p.needsEmailFormat, false);
  assert.deepEqual(p.fresh.map(r => [r.name, r.email, r.made]), [
    ['Ada Lovelace', 'ada@school.edu', false],
    ['Grace Hopper', 'ghopper@school.edu', false],
  ]);
});

test('a login that already holds an @ is never given a second domain', () => {
  const text = 'Student,ID,SIS Login ID,Section\n"Doe, Jane",1,jane@uni.edu,A\n"Roe, Rich",2,rroe,A\n';
  const p = m.buildPreview(m.recordsFromText(text), { name: 0, last: -1, email: -1, idCol: 2 }, { domain: 'school.edu' });
  assert.deepEqual(emails(p.fresh), ['jane@uni.edu', 'rroe@school.edu']);
  assert.deepEqual(p.fresh.map(r => r.made), [false, true]);
});

test('a generic CSV with name and email columns', () => {
  const text = '﻿Name,Email\r\nAda Lovelace,ada@school.edu\r\n"Hopper, Grace",<grace@school.edu>\r\n';
  const p = preview(text);
  assert.equal(p.canvas, false);
  assert.deepEqual(p.map, { name: 0, last: -1, email: 1, idCol: -1 });
  // A comma inside quotes stays in the cell; names are not reordered outside Canvas.
  assert.deepEqual(p.fresh.map(r => [r.row, r.name, r.email]), [
    [2, 'Ada Lovelace', 'ada@school.edu'],
    [3, 'Hopper, Grace', 'grace@school.edu'],
  ]);
  assert.deepEqual([p.problems, p.skipped, p.needsEmailFormat], [[], [], false]);
});

test('separate first and last name columns, in a semicolon file', () => {
  const text = 'First name;Last name;E-mail address\nAda;Lovelace;ada@school.edu\nGrace;Hopper;grace@school.edu\n';
  assert.equal(m.detectDelimiter(text), ';');
  const p = preview(text);
  assert.deepEqual(p.fresh.map(r => r.name), ['Ada Lovelace', 'Grace Hopper']);
});

test('tab-separated text pasted from a spreadsheet', () => {
  const text = 'Student Name\tStudent Email\nAda Lovelace\tada@school.edu\n';
  assert.equal(m.detectDelimiter(text), '\t');
  assert.deepEqual(emails(preview(text).fresh), ['ada@school.edu']);
});

test('quoted cells may hold doubled quotes and line breaks', () => {
  const rows = m.parseCsv('a,b\n"say ""hi""","two\nlines"\n', ',');
  assert.deepEqual(rows, [['a', 'b'], ['say "hi"', 'two\nlines']]);
  assert.deepEqual(m.parseCsv('x,y', ','), [['x', 'y']], 'no final line break');
  assert.deepEqual(m.parseCsv('', ','), []);
  assert.equal(m.detectDelimiter('"a,b";c;d\n1'), ';', 'separators inside quotes do not count');
});

test('bad rows: missing, invalid and repeated emails, blank lines', () => {
  const text = [
    'Name,Email',
    'Ada Lovelace,ada@school.edu',
    'No Email,',
    'Bad Email,not-an-address',
    '',
    ',,',
    'Ada Again,ADA@school.edu',
    'Spaces,"has space@school.edu"',
  ].join('\n');
  const p = preview(text);
  assert.deepEqual(emails(p.fresh), ['ada@school.edu']);
  assert.deepEqual(p.problems.map(x => [x.row, x.reason]), [
    [3, 'No email address'],
    [4, 'Not a valid email address: not-an-address'],
    [7, 'Listed twice in this file (also row 2)'],
    [8, 'Not a valid email address: has space@school.edu'],
  ]);
});

test('students already on the roster are listed apart, not invited again', () => {
  const text = 'Name,Email\nAda,ada@school.edu\nGrace,grace@school.edu\n';
  const p = preview(text, { rosterEmails: ['ADA@school.edu'] });
  assert.deepEqual(emails(p.existing), ['ada@school.edu']);
  assert.deepEqual(emails(p.fresh), ['grace@school.edu']);
});

test('the teacher can fix a wrong column guess', () => {
  const text = 'Name,Personal email,School email\nAda,ada@gmail.com,ada@school.edu\n';
  const p = preview(text);
  assert.equal(p.map.email, 1, 'the first email-like header wins the guess');
  const fixed = preview(text, {}, { email: 2 });
  assert.deepEqual(emails(fixed.fresh), ['ada@school.edu']);
  const noName = preview(text, {}, { name: -1 });
  assert.deepEqual(noName.fresh.map(r => r.name), ['']);
});

test('a file with no recognisable columns imports nothing', () => {
  const p = preview('foo,bar\n1,2\n');
  assert.deepEqual(p.map, { name: -1, last: -1, email: -1, idCol: -1 });
  assert.deepEqual(p.fresh, []);
  assert.deepEqual(p.problems.map(x => x.reason), ['No email address']);
  assert.deepEqual(m.buildPreview([], { name: -1, last: -1, email: -1, idCol: -1 }).fresh, []);
});

test('names are cut to the length the server keeps', () => {
  const p = preview(`Name,Email\n${'x'.repeat(200)},a@school.edu\n`);
  assert.equal(p.fresh[0].name.length, 120);
});

test('"Last, First" becomes "First Last" only when it is exactly that', () => {
  assert.equal(m.firstNameFirst('Lovelace, Ada'), 'Ada Lovelace');
  assert.equal(m.firstNameFirst('Ada Lovelace'), 'Ada Lovelace');
  assert.equal(m.firstNameFirst('King, Martin, Jr.'), 'King, Martin, Jr.');
  assert.equal(m.firstNameFirst('Cher,'), 'Cher');
});

test('email shape check', () => {
  assert.equal(m.looksLikeEmail('a@b.edu'), true);
  for (const bad of ['', 'a@b', 'a b@c.edu', '@b.edu', 'a@b.edu,c@d.edu', `${'x'.repeat(250)}@b.edu`]) {
    assert.equal(m.looksLikeEmail(bad), false, bad);
  }
});

test('reading a file refuses one too large to be a class list', async () => {
  await assert.rejects(m.readClassList(null), /Choose a CSV file/);
  await assert.rejects(m.readClassList({ size: m.MAX_CLASS_LIST_BYTES + 1 }), /too large/);
});

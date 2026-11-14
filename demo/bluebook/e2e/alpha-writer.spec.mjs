/**
 * alpha-writer.spec.mjs: what the alpha workflow adds beyond add-writer,
 * writing-state-files and analyse-sealed.
 *
 * - A take-home exam the teacher approved as reference writing reads as
 *   "approved by you" at a lower weight on Voice baseline and Writing State
 *   (never "0 teacher-approved"), and a student's own upload still reads as a
 *   student upload. The words are Live.approvalWords (demo/original/live.js).
 * - A writer added by name is analysed from a .docx file in one flow.
 * - A student session sees none of the new controls.
 * - @evidence-on: the side-by-side past-paper table says the same, and the
 *   writer's analysis shows quotes.
 *
 * Papers are public-domain passages: J. S. Mill (On Liberty, 1859) for the
 * baseline, G. K. Chesterton (Orthodoxy, 1908) to analyse.
 */

import { readFileSync } from 'node:fs'
import { isolatedTest as test, expect } from './fixtures/tenancy.mjs'
import { addBaselineFor, createCourse, staffStorageState, studentStorageState } from './fixtures/api-setup.mjs'

const FIXTURES = new URL('./fixtures/evidence/', import.meta.url)
const read = name => readFileSync(new URL(name, FIXTURES), 'utf8')
const uid = () => `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`
const PAPER = read('chesterton.txt')
const TAKE_HOME_ANSWER =
  'Augustine argues that the restless heart finds rest only in God, and he builds the argument ' +
  'slowly, from memory and desire, through the long middle books of the work, until the reader ' +
  'sees that the search was the subject all along. I find the account of desire persuasive.'
const LOW_WEIGHT = '(1 take-home exam counts at a lower weight)'

// The first ~120 words of the Chesterton passage as one paragraph, in a .docx
// built by hand (a stored ZIP), so no dependency is added.
const DOCX_PARAGRAPH = PAPER.replace(/\s+/g, ' ').trim().split(' ').slice(0, 120).join(' ')
const CRC = (() => {
  const t = new Uint32Array(256)
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0 }
  return t
})()
const crc32 = buf => { let c = 0xffffffff; for (const b of buf) c = CRC[(c ^ b) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0 }
function makeDocx(paragraph) {
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
  const files = {
    '[Content_Types].xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
    '_rels/.rels': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
    'word/document.xml': `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t xml:space="preserve">${esc(paragraph)}</w:t></w:r></w:p></w:body></w:document>`,
  }
  const local = [], central = []
  let offset = 0
  for (const [name, text] of Object.entries(files)) {
    const nameB = Buffer.from(name), data = Buffer.from(text), crc = crc32(data)
    const lh = Buffer.alloc(30)
    lh.writeUInt32LE(0x04034b50, 0); lh.writeUInt16LE(20, 4); lh.writeUInt32LE(crc, 14)
    lh.writeUInt32LE(data.length, 18); lh.writeUInt32LE(data.length, 22); lh.writeUInt16LE(nameB.length, 26)
    local.push(lh, nameB, data)
    const ch = Buffer.alloc(46)
    ch.writeUInt32LE(0x02014b50, 0); ch.writeUInt16LE(20, 4); ch.writeUInt16LE(20, 6); ch.writeUInt32LE(crc, 16)
    ch.writeUInt32LE(data.length, 20); ch.writeUInt32LE(data.length, 24); ch.writeUInt16LE(nameB.length, 28)
    ch.writeUInt32LE(offset, 42)
    central.push(ch, nameB)
    offset += 30 + nameB.length + data.length
  }
  const cd = Buffer.concat(central)
  const end = Buffer.alloc(22)
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(3, 8); end.writeUInt16LE(3, 10)
  end.writeUInt32LE(cd.length, 12); end.writeUInt32LE(offset, 16)
  return Buffer.concat([...local, cd, end])
}

// The tenant's student (testTenant.student) with three verified Mill papers,
// a take-home exam they sealed and the teacher approved, and one paper they
// uploaded themselves.
async function takeHomeBaseline(request, { staff, student }) {
  const teacher = { Authorization: `Bearer ${staff.token}` }
  const asStudent = { Authorization: `Bearer ${student.token}` }
  for (const i of [1, 2, 3]) {
    await addBaselineFor(request, student.student_id, staff.token, { text: read(`mill-${i}.txt`), provenance: 'verified', assignment: `On Liberty, part ${i}`, submittedAt: `2026-0${i}-1${i}` })
  }
  const id = uid()
  const course = await createCourse(request, staff.token, { name: `Take-home course ${id}` })
  const examTitle = `Take-home exam ${id}`
  const created = await request.post('/bluebook/exams', {
    headers: teacher,
    data: {
      title: examTitle, course: course.code, course_id: course.id, duration: 30, prompt: 'Discuss.', status: 'ACTIVE',
      conditions: { timed: false, setting: 'take_home', size: 'small', blockCopy: false },
    },
  })
  expect(created.status(), await created.text()).toBe(201)
  const examId = (await created.json()).id
  const added = await request.post(`/bluebook/courses/${encodeURIComponent(course.id)}/students`, {
    headers: teacher, data: { students: [{ email: student.email, name: 'E2E Student' }] },
  })
  expect(added.status(), await added.text()).toBe(200)
  const started = await request.post(`/bluebook/me/exams/${encodeURIComponent(examId)}/start`, { headers: asStudent })
  expect(started.ok(), await started.text()).toBe(true)
  const sealed = await request.post('/bluebook/submissions', {
    headers: asStudent,
    data: {
      exam_id: examId, student_id: student.student_id, candidate: 'E2E Student',
      word_count: 60, text: TAKE_HOME_ANSWER, answers: [TAKE_HOME_ANSWER], submission_uuid: `uuid-${id}`,
    },
  })
  expect(sealed.status(), await sealed.text()).toBe(201)
  const submissionId = (await sealed.json()).id
  const approved = await request.post(`/bluebook/submissions/${encodeURIComponent(submissionId)}/baseline`, { headers: teacher })
  expect(approved.status(), await approved.text()).toBe(200)
  expect((await approved.json()).status).toBe('added')
  await addBaselineFor(request, student.student_id, student.token, { text: read('mill-1.txt').split(/\n\s*\n/).reverse().join('\n\n'), provenance: 'unverified', assignment: 'Own upload' })
  const got = await (await request.get(`/students/${encodeURIComponent(student.student_id)}`, { headers: teacher })).json()
  expect(got.samples.map(s => s.source).sort()).toEqual(['staff_or_supervised', 'staff_or_supervised', 'staff_or_supervised', 'student_upload', 'take_home'])
  return { examTitle }
}

test('a take-home approved as reference writing reads as approved by you, a student upload as an upload', async ({ browser, request, testTenant }) => {
  test.setTimeout(120_000)
  const { staff, student, baseURL } = testTenant
  await takeHomeBaseline(request, testTenant)
  const context = await browser.newContext({ storageState: staffStorageState(baseURL, staff) })
  const page = await context.newPage()
  const enc = encodeURIComponent(student.student_id)

  await page.goto(`/original/baseline.html?student=${enc}`)
  await expect(page.locator('#meta')).toContainText('5 samples: 4 approved by you ' + LOW_WEIGHT + ', 1 student upload', { timeout: 20_000 })
  const wording = await page.locator('body').innerText()
  expect(wording).not.toMatch(/0 teacher-approved/)
  expect(wording).toContain('Take-home exam approved by you')
  expect(wording).toContain('Student upload')

  await page.goto(`/original/writing-state.html?student=${enc}`)
  await expect(page.locator('#an-form')).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('body')).toContainText('5 counted samples', { timeout: 20_000 })
  const state = await page.locator('body').innerText()
  expect(state).toContain('5 counted samples (4 approved by you, 1 student upload)')
  expect(state).toContain('Take-home exams and shared papers you approved count at a lower weight.')
  expect(state).not.toMatch(/0 teacher-approved/)
  await context.close()
})

test('a student session sees none of the add or analyse controls', async ({ browser, testTenant }) => {
  const { student, baseURL } = testTenant
  const context = await browser.newContext({ storageState: studentStorageState(baseURL, student) })
  const page = await context.newPage()
  for (const path of ['students.html', `writing-state.html?student=${encodeURIComponent(student.student_id)}`]) {
    await page.goto(`/original/${path}`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('button', { name: 'Add a writer' })).toHaveCount(0)
    await expect(page.locator('#an-form, #writer-form, #an-go')).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Analyse against baseline' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^Analyse/ })).toHaveCount(0)
    await expect(page.locator('body')).not.toContainText('deviation')
  }
  await context.close()
})

// A writer added by name on Students, three verified papers, the fourth read
// from a .docx. Returns the page left on Writing State's result.
async function writerFromDocx(browser, testTenant) {
  const { staff, baseURL } = testTenant
  const name = `Docx Writer ${uid()}`
  const teacher = { Authorization: `Bearer ${staff.token}` }
  const context = await browser.newContext({ storageState: staffStorageState(baseURL, staff), viewport: { width: 1440, height: 1000 } })
  const page = await context.newPage()
  await page.goto('/original/students.html')
  await page.getByRole('button', { name: 'Add a writer' }).click()
  await page.getByLabel('Their name').fill(name)
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(page).toHaveURL(url => url.pathname === '/original/baseline.html' && url.hash === '#add-writing')
  const writerId = new URL(page.url()).searchParams.get('student')
  await expect(page.locator('#paste-text')).toBeVisible({ timeout: 20_000 })
  for (const i of [1, 2, 3]) {
    await page.locator('#paste-text').fill(read(`mill-${i}.txt`))
    await page.locator('#paste-assign').fill(`On Liberty, part ${i}`)
    await page.locator('#paste-go').click()
    await expect(page.locator('#add-msg')).toContainText(`Added as sample ${i}.`, { timeout: 30_000 })
  }
  await page.goto(`/original/writing-state.html?student=${encodeURIComponent(writerId)}`)
  await expect(page.locator('#an-form')).toBeVisible({ timeout: 20_000 })
  await page.locator('#an-file').setInputFiles({ name: 'Orthodoxy notes.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: makeDocx(DOCX_PARAGRAPH) })
  await expect(page.locator('#an-msg')).toHaveText(/^Read \d+ words? from Orthodoxy notes\.docx/, { timeout: 20_000 })
  await expect(page.locator('#an-assign')).toHaveValue('Orthodoxy notes')
  const scored = page.waitForResponse(r => r.url().endsWith('/score') && r.request().method() === 'POST', { timeout: 90_000 })
  await page.locator('#an-go').click()
  const res = await scored
  expect(res.ok()).toBe(true)
  await expect(page.locator('#an-done')).toBeVisible({ timeout: 30_000 })
  return { page, context, writerId, name, body: await res.json(), cleanup: () => context.request.delete(`/students/${encodeURIComponent(writerId)}`, { headers: teacher }) }
}

test('a writer added by name is analysed from a .docx in one flow', async ({ browser, testTenant }) => {
  test.setTimeout(180_000)
  const { page, context, body, cleanup } = await writerFromDocx(browser, testTenant)
  // Flags off: no passages are sent and the page promises none.
  expect(body.evidence ?? null).toBeNull()
  await expect(page.locator('#tri-evidence')).toBeHidden()
  await cleanup()
  await context.close()
})

test('a take-home and a student upload in the side-by-side table, and a writer analysis with quotes @evidence-on', async ({ browser, request, testTenant }) => {
  test.setTimeout(240_000)
  const { staff, student, baseURL } = testTenant
  await takeHomeBaseline(request, testTenant)
  const context = await browser.newContext({ storageState: staffStorageState(baseURL, staff), viewport: { width: 1440, height: 1000 } })
  const page = await context.newPage()
  await page.goto(`/original/writing-state.html?student=${encodeURIComponent(student.student_id)}`)
  await expect(page.locator('#an-form')).toBeVisible({ timeout: 20_000 })
  await page.locator('#an-assign').fill('Orthodoxy, chapter 1')
  await page.locator('#an-text').fill(PAPER)
  const scored = page.waitForResponse(r => r.url().endsWith('/score') && r.request().method() === 'POST', { timeout: 90_000 })
  await page.locator('#an-go').click()
  const res = await scored
  expect(res.ok()).toBe(true)
  const sources = (await res.json()).evidence.baseline_papers.map(p => p.source).sort()
  expect(sources).toEqual(['staff_or_supervised', 'staff_or_supervised', 'staff_or_supervised', 'student_upload', 'take_home'])
  await expect(page.locator('#an-done')).toBeVisible({ timeout: 30_000 })
  await page.locator('#tri-evidence').click()
  await expect(page).toHaveURL(/\/original\/evidence\.html/)
  const table = page.locator('#p-past table.prov')
  await expect(table).toBeVisible({ timeout: 15_000 })
  await expect(table.locator('.how', { hasText: 'Take-home exam approved by you' })).toHaveCount(1)
  await expect(table.locator('.how', { hasText: 'Student upload' })).toHaveCount(1)
  await expect(table.locator('.how', { hasText: 'Verified by teacher' })).toHaveCount(3)
  await expect(page.locator('#p-past')).toContainText('Take-home exams and shared papers you approved count in the baseline at a lower weight.')
  await expect(page.locator('#p-past')).not.toContainText('0 teacher-approved')
  await context.close()

  const writer = await writerFromDocx(browser, testTenant)
  expect(writer.body.evidence, 'this run needs EVIDENCE_PASSAGES_ENABLED=1').toBeTruthy()
  await writer.page.locator('#tri-evidence').click()
  await expect(writer.page).toHaveURL(/\/original\/evidence\.html/)
  await expect(writer.page.locator('.ex .ex-q mark').first()).toBeVisible({ timeout: 15_000 })
  await writer.cleanup()
  await writer.context.close()
})

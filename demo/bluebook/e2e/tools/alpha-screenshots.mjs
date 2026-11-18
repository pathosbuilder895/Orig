/**
 * alpha-screenshots.mjs: capture the alpha-workflow pages for the PR
 * (docs/audits/alpha-workflow/). NOT a spec and not run by CI.
 *
 *   MAINTENANCE_TOKEN=ci-test-only ALPHA_BASE_URL=http://localhost:8047 \
 *     ALPHA_OUT=docs/audits/alpha-workflow node demo/bluebook/e2e/tools/alpha-screenshots.mjs
 *
 * ALPHA_MODE=before captures only the two wording views that exist on the
 * base commit (Voice baseline and Writing State with an approved take-home),
 * for a before/after pair. The server must be a pilot-mode one
 * (ORIGINAL_ENV=pilot MAINTENANCE_TOKEN=ci-test-only ... --skip-seed).
 * JPEG q80, device scale 1, 1440x1000.
 */

import { readFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { chromium, request as pwRequest } from '@playwright/test'
import { provisionTenantWithStaff, studentLogin, addBaselineFor, createCourse, staffStorageState } from '../fixtures/api-setup.mjs'

const BASE = process.env.ALPHA_BASE_URL || 'http://localhost:8001'
const OUT = process.env.ALPHA_OUT
const BEFORE = process.env.ALPHA_MODE === 'before'
if (!OUT) { console.error('ALPHA_OUT is required'); process.exit(2) }
mkdirSync(OUT, { recursive: true })

const FIXTURES = new URL('../fixtures/evidence/', import.meta.url)
const read = name => readFileSync(new URL(name, FIXTURES), 'utf8')
const VIEWPORT = { width: 1440, height: 1000 }
const ANSWERS = [
  'Augustine argues that the restless heart finds rest only in God, and he builds the argument slowly, from memory and desire, through the long middle books of the work, until the reader sees that the search was the subject all along. I find the account of desire persuasive.',
  'Boethius writes from prison, and the consolation he is offered is philosophy rather than escape. Lady Philosophy asks him what he thinks he has lost, and slowly shows him that fortune never belonged to him at all. I think the argument works better as comfort than as proof.',
]
const enc = encodeURIComponent
const PAPER = read('chesterton.txt')

async function shot(page, name) {
  await page.waitForTimeout(600)
  await page.screenshot({ path: join(OUT, `${name}.jpg`), type: 'jpeg', quality: 80 })
  console.log('wrote', join(OUT, `${name}.jpg`))
}

// A student with three verified papers, one sealed take-home exam the teacher
// approved and one upload of their own; optionally also an in-class sealed exam.
async function seed(api, staff, { sealedInClass }) {
  const student = await studentLogin(api, { staffToken: staff.token, name: 'Dana Whitfield' })
  const teacher = { Authorization: `Bearer ${staff.token}` }
  const asStudent = { Authorization: `Bearer ${student.token}` }
  for (const i of [1, 2, 3]) {
    await addBaselineFor(api, student.student_id, staff.token, { text: read(`mill-${i}.txt`), provenance: 'verified', assignment: `On Liberty, part ${i}`, submittedAt: `2026-0${i}-1${i}` })
  }
  const course = await createCourse(api, staff.token, { name: 'Early Church Readings' })
  await api.post(`/bluebook/courses/${enc(course.id)}/students`, { headers: teacher, data: { students: [{ email: student.email, name: 'Dana Whitfield' }] } })
  const seal = async (title, conditions, answers) => {
    const made = await (await api.post('/bluebook/exams', { headers: teacher, data: { title, course: course.code, course_id: course.id, duration: 30, prompt: 'Discuss.', status: 'ACTIVE', ...(conditions ? { conditions } : {}), questions: answers.length > 1 ? ['What does Augustine say about rest?', 'What does Philosophy offer Boethius?'] : undefined } })).json()
    await api.post(`/bluebook/me/exams/${enc(made.id)}/start`, { headers: asStudent })
    const sealed = await api.post('/bluebook/submissions', { headers: asStudent, data: { exam_id: made.id, student_id: student.student_id, candidate: 'Dana Whitfield', word_count: 80, ...(answers.length === 1 ? { text: answers[0] } : {}), answers, submission_uuid: `uuid-${title}-${Date.now()}` } })
    return (await sealed.json()).id
  }
  const takeHome = await seal('Confessions, take-home', { timed: false, setting: 'take_home', size: 'small', blockCopy: false }, [ANSWERS[0]])
  await api.post(`/bluebook/submissions/${enc(takeHome)}/baseline`, { headers: teacher })
  await addBaselineFor(api, student.student_id, student.token, { text: read('mill-1.txt').split(/\n\s*\n/).reverse().join('\n\n'), provenance: 'unverified', assignment: 'Own upload' })
  const sealedId = sealedInClass ? await seal('Midterm: Augustine and Boethius', null, ANSWERS) : null
  return { student, sealedId }
}

async function main() {
  const api = await pwRequest.newContext({ baseURL: BASE })
  const { staff } = await provisionTenantWithStaff(api, { role: 'professor' })
  const { student, sealedId } = await seed(api, staff, { sealedInClass: !BEFORE })
  const sid = enc(student.student_id)
  const browser = await chromium.launch()
  const context = await browser.newContext({ baseURL: BASE, viewport: VIEWPORT, deviceScaleFactor: 1, storageState: staffStorageState(BASE, staff) })
  const page = await context.newPage()

  if (!BEFORE) {
    await page.goto('/original/students.html')
    await page.getByRole('button', { name: 'Add a writer' }).click()
    await page.getByLabel('Their name').fill('Priya Raman')
    await shot(page, '01-students-add-a-writer')

    await page.getByRole('button', { name: 'Add', exact: true }).click()
    await page.waitForURL(/baseline\.html/)
    const writerId = new URL(page.url()).searchParams.get('student')
    await page.locator('#paste-text').waitFor({ state: 'visible', timeout: 20_000 })
    for (const i of [1, 2, 3]) {
      await page.locator('#paste-text').fill(read(`mill-${i}.txt`))
      await page.locator('#paste-assign').fill(`On Liberty, part ${i}`)
      await page.locator('#paste-go').click()
      await page.locator('#add-msg', { hasText: `Added as sample ${i}.` }).waitFor({ timeout: 30_000 })
    }
    await page.goto(`/original/baseline.html?student=${enc(writerId)}`)
    await page.waitForLoadState('networkidle')
    await shot(page, '02-voice-baseline-three-papers')

    await page.goto(`/original/writing-state.html?student=${enc(writerId)}`)
    await page.locator('#an-form').waitFor({ state: 'visible', timeout: 20_000 })
    await page.locator('#an-file').setInputFiles({ name: 'Orthodoxy notes.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: makeDocx(PAPER.replace(/\s+/g, ' ').trim().split(' ').slice(0, 160).join(' ')) })
    await page.locator('#an-msg', { hasText: /^Read \d+ words?/ }).waitFor({ timeout: 20_000 })
    await shot(page, '03-writing-state-docx-loaded')
    const scored = page.waitForResponse(r => r.url().endsWith('/score') && r.request().method() === 'POST', { timeout: 90_000 })
    await page.locator('#an-go').click()
    await scored
    await page.locator('#an-done').waitFor({ state: 'visible', timeout: 30_000 })
    await shot(page, '04-writing-state-result')

    await page.goto('/original/submissions.html')
    await page.getByRole('link', { name: 'Analyse against baseline' }).first().waitFor({ timeout: 30_000 })
    await shot(page, '05-submissions-analyse-link')

    await page.goto(`/original/writing-state.html?student=${sid}&submission=${enc(sealedId)}`)
    await page.locator('#an-from').waitFor({ state: 'visible', timeout: 20_000 })
    await shot(page, '06-writing-state-from-sealed-exam')
  }

  await page.goto(`/original/baseline.html?student=${sid}`)
  await page.waitForLoadState('networkidle')
  await page.locator('#meta').getByText('samples', { exact: false }).waitFor({ timeout: 20_000 }).catch(() => {})
  await shot(page, '07-voice-baseline-take-home')
  await page.goto(`/original/writing-state.html?student=${sid}`)
  await page.locator('#an-form').waitFor({ state: 'visible', timeout: 20_000 })
  await page.waitForLoadState('networkidle')
  await shot(page, '08-writing-state-take-home')
  await browser.close()
  await api.dispose()
}

// A minimal .docx: a ZIP with stored entries (same builder as the e2e specs).
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

main().catch(e => { console.error(e); process.exit(1) })

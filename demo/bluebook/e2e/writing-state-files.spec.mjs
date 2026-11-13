/**
 * writing-state-files.spec.mjs: Writing State opens .docx and .pdf papers.
 *
 * The teacher chooses a file on #an-file; .docx and .pdf are read by the
 * server's extraction route (POST /students/{id}/upload, which stores nothing)
 * and the text lands in the paper box. Analysing is unchanged. The files are
 * built here by hand (a stored ZIP and a one-page PDF), so no dependency is
 * added.
 */

import { readFileSync } from 'node:fs'
import { isolatedTest as test, expect } from './fixtures/tenancy.mjs'
import { addBaselineFor, staffStorageState } from './fixtures/api-setup.mjs'

const FIXTURES = new URL('./fixtures/evidence/', import.meta.url)
const read = name => readFileSync(new URL(name, FIXTURES), 'utf8')
const DATES = ['2026-01-14', '2026-02-11', '2026-03-10']

// The first ~120 words of the Chesterton passage, as one paragraph.
const PAPER = read('chesterton.txt').replace(/\s+/g, ' ').trim().split(' ').slice(0, 120).join(' ')
const WORDS = PAPER.split(' ').length

const CRC = (() => {
  const t = new Uint32Array(256)
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0 }
  return t
})()
function crc32(buf) { let c = 0xffffffff; for (const b of buf) c = CRC[(c ^ b) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0 }

// A minimal valid .docx: a ZIP with stored (uncompressed) entries.
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

// A one-page PDF with a Helvetica text layer, one line per ~10 words.
function makePdf(text) {
  const words = text.split(' '), lines = []
  for (let i = 0; i < words.length; i += 10) lines.push(words.slice(i, i + 10).join(' '))
  const pdfStr = s => s.replace(/[\\()]/g, m => '\\' + m)
  const stream = 'BT /F1 10 Tf 12 TL 40 760 Td ' + lines.map(l => `(${pdfStr(l)}) Tj T*`).join(' ') + ' ET'
  const objs = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  let out = '%PDF-1.4\n'
  const offsets = []
  objs.forEach((o, i) => { offsets.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n` })
  const xref = out.length
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offsets.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('')
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(out, 'latin1')
}

async function openPage(browser, request, testTenant) {
  const { staff, student, baseURL } = testTenant
  for (let i = 1; i <= 3; i++) {
    await addBaselineFor(request, student.student_id, student.token, { text: read(`mill-${i}.txt`), provenance: 'verified', assignment: `On Liberty, part ${i}`, submittedAt: DATES[i - 1] })
  }
  const context = await browser.newContext({ storageState: staffStorageState(baseURL, staff) })
  const page = await context.newPage()
  await page.goto(`/original/writing-state.html?student=${encodeURIComponent(student.student_id)}`)
  await expect(page.locator('#an-form')).toBeVisible({ timeout: 20_000 })
  return page
}

test.describe('Writing State opens .docx and .pdf', () => {
  test('a .docx fills the paper box, then analyses', async ({ browser, request, testTenant }) => {
    test.setTimeout(120_000)
    const page = await openPage(browser, request, testTenant)
    await expect(page.locator('label.an-file')).toContainText('.docx, .pdf or .txt')
    await page.locator('#an-file').setInputFiles({ name: 'Orthodoxy notes.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: makeDocx(PAPER) })
    await expect(page.locator('#an-text')).toHaveValue(new RegExp('^' + PAPER.slice(0, 40).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), { timeout: 20_000 })
    await expect(page.locator('#an-words')).toContainText(String(WORDS))
    await expect(page.locator('#an-msg')).toHaveText(/^Read \d+ words? from/)
    await expect(page.locator('#an-assign')).toHaveValue('Orthodoxy notes')
    const scored = page.waitForResponse(r => r.url().endsWith('/score') && r.request().method() === 'POST', { timeout: 90_000 })
    await page.locator('#an-go').click()
    expect((await scored).ok()).toBe(true)
    await expect(page.locator('#an-done')).toBeVisible({ timeout: 30_000 })
  })

  test('a .pdf with a text layer fills the paper box', async ({ browser, request, testTenant }) => {
    test.setTimeout(90_000)
    const page = await openPage(browser, request, testTenant)
    await page.locator('#an-assign').fill('Kept name')
    await page.locator('#an-file').setInputFiles({ name: 'paper.pdf', mimeType: 'application/pdf', buffer: makePdf(PAPER) })
    await expect(page.locator('#an-msg')).toHaveText(/^Read \d+ words? from paper\.pdf/, { timeout: 20_000 })
    const got = (await page.locator('#an-text').inputValue()).replace(/\s+/g, ' ').trim()
    expect(got.split(' ').length).toBe(WORDS)
    expect(got.startsWith(PAPER.slice(0, 40))).toBe(true)
    // A filled assignment is left alone.
    await expect(page.locator('#an-assign')).toHaveValue('Kept name')
  })

  test('a PDF with no text and an unsupported type say so plainly', async ({ browser, request, testTenant }) => {
    test.setTimeout(90_000)
    const page = await openPage(browser, request, testTenant)
    await page.locator('#an-file').setInputFiles({ name: 'scan.pdf', mimeType: 'application/pdf', buffer: makePdf('') })
    await expect(page.locator('#an-msg')).toHaveText('This file has no text Original can read. If it is a scan, paste the text instead.', { timeout: 20_000 })
    await expect(page.locator('#an-text')).toHaveValue('')
    await page.locator('#an-file').setInputFiles({ name: 'notes.rtf', mimeType: 'application/rtf', buffer: Buffer.from('{\\rtf1 hello}') })
    await expect(page.locator('#an-msg')).toContainText('Original reads .docx, .pdf and .txt files')
    await expect(page.locator('#an-msg')).toHaveClass(/err/)
    await expect(page.locator('#an-text')).toHaveValue('')
  })
})

/**
 * paper-parts.spec.mjs: Writing State lists the parts of a paper and lets the
 * teacher set a part aside or measure it.
 *
 * Needs a server with MATTER_SPLITTER_ENABLED=1, PAPER_PROFILE_ENABLED=1 and
 * UPLOAD_ALSO_MEASURE=matter (so the past papers carry the splitter's
 * measurement and the score uses it). Without them the parts list is never
 * drawn, so the spec skips.
 *
 * The paper is a real APA 7 student paper as Word saves it, from the
 * document-parts test set (validation/diagnostics/document_parts_v2/samples):
 * a title page, an abstract, the body and a reference list.
 */

import { readFileSync } from 'node:fs'
import { isolatedTest as test, expect } from './fixtures/tenancy.mjs'
import { addBaselineFor, staffStorageState } from './fixtures/api-setup.mjs'

const FIXTURES = new URL('./fixtures/evidence/', import.meta.url)
const read = name => readFileSync(new URL(name, FIXTURES), 'utf8')
const APA_DOCX = readFileSync(new URL('../../../validation/diagnostics/document_parts_v2/samples/apa_student.docx', import.meta.url))
const DATES = ['2026-01-14', '2026-02-11', '2026-03-10']

test.describe('Parts of this paper', () => {
  test('an APA paper lists its title page, abstract and references as set aside, and the abstract can be measured', async ({ browser, request, testTenant }) => {
    test.setTimeout(240_000)
    const { staff, student, baseURL } = testTenant
    for (let i = 1; i <= 3; i++) {
      await addBaselineFor(request, student.student_id, student.token, { text: read(`mill-${i}.txt`), provenance: 'verified', assignment: `On Liberty, part ${i}`, submittedAt: DATES[i - 1] })
    }
    const context = await browser.newContext({ storageState: staffStorageState(baseURL, staff) })
    const page = await context.newPage()
    await page.goto(`/original/writing-state.html?student=${encodeURIComponent(student.student_id)}`)
    await expect(page.locator('#an-form')).toBeVisible({ timeout: 20_000 })

    await page.locator('#an-file').setInputFiles({ name: 'A Strong Rod Broken.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: APA_DOCX })
    await expect(page.locator('#an-msg')).toHaveText(/^Read \d+ words? from/, { timeout: 20_000 })
    const first = page.waitForResponse(r => r.url().endsWith('/score') && r.request().method() === 'POST', { timeout: 120_000 })
    await page.locator('#an-go').click()
    const before = await (await first).json()
    await expect(page.locator('#an-done')).toBeVisible({ timeout: 30_000 })
    const parts = before.evidence && before.evidence.paper_profile && before.evidence.paper_profile.this_paper.parts
    test.skip(!Array.isArray(parts), 'the server runs without MATTER_SPLITTER_ENABLED / PAPER_PROFILE_ENABLED / UPLOAD_ALSO_MEASURE=matter')

    const box = page.locator('#ppp')
    await expect(box).toBeVisible()
    const row = what => box.locator('.pp-part').filter({ has: page.locator('.pp-part-what', { hasText: new RegExp('^' + what) }) })
    await expect(row('Title page: set aside, \\d+ words')).toHaveCount(1)
    await expect(row('Abstract: set aside, \\d+ words')).toHaveCount(1)
    await expect(row('References: set aside, \\d+ words')).toHaveCount(1)
    // The same parts in the "About the papers" table.
    await expect(page.locator('#pp .pp-parts-row td').first()).toContainText('Abstract: set aside')
    const numbersBefore = await page.locator('#ess-nums').innerText()

    const again = page.waitForResponse(r => r.url().endsWith('/score') && r.request().method() === 'POST', { timeout: 120_000 })
    await row('Abstract: set aside').getByRole('button', { name: 'Measure this part' }).click()
    const resp = await again
    const sent = resp.request().postDataJSON()
    const abstract = parts.find(p => p.kind === 'abstract')
    expect(sent.include_ranges).toEqual(abstract.ranges)
    expect(sent.exclude_ranges).toEqual([])
    const after = await resp.json()
    expect(after.authorship.deviation_score).not.toBe(before.authorship.deviation_score)

    await expect(page.locator('#ppp-msg')).toHaveText('Analysed again with the abstract measured.', { timeout: 30_000 })
    await expect(row('Abstract: measured \\(your choice\\), \\d+ words')).toHaveCount(1)
    await expect(row('Abstract: measured').getByRole('button', { name: 'Set this part aside' })).toBeVisible()
    await expect(row('Title page: set aside')).toHaveCount(1)
    await expect(page.locator('#ess-nums')).not.toHaveText(numbersBefore)
    await context.close()
  })
})

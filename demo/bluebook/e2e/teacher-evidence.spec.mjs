/**
 * teacher-evidence.spec.mjs: the teacher's side-by-side page
 * (demo/original/evidence.html, ADR-013).
 *
 * The page shows the staff-only `evidence` field of POST /students/{id}/score,
 * which the server sends only when EVIDENCE_PASSAGES_ENABLED=1 (and the
 * preliminary chip only when PRELIMINARY_SCORE_ENABLED=1). So the suite runs
 * this file twice, against two servers (.github/workflows/test.yml):
 *
 * - the main run (flags off, the default): Writing State shows no new link,
 *   the score response carries neither field, and evidence.html opened by hand
 *   shows nothing but its empty state;
 * - "@evidence-on" (a server started with both flags on): the cards render,
 *   every marked word is the exact slice of the passage the API named, every
 *   measurement is listed, and a student session never sees any of it.
 *
 * The writing is public domain: three passages of J. S. Mill's On Liberty
 * (1859) as the student's past papers, and a passage of G. K. Chesterton's
 * Orthodoxy (1908) as the paper analysed.
 */

import { readFileSync } from 'node:fs'
import AxeBuilder from '@axe-core/playwright'
import { isolatedTest as test, expect } from './fixtures/tenancy.mjs'
import { addBaselineFor, staffStorageState } from './fixtures/api-setup.mjs'

const FIXTURES = new URL('./fixtures/evidence/', import.meta.url)
const read = name => readFileSync(new URL(name, FIXTURES), 'utf8')
const PAST = [1, 2, 3].map(i => ({ text: read(`mill-${i}.txt`), assignment: `On Liberty, part ${i}` }))
const PAPER = read('chesterton.txt')

async function seedPastPapers(request, student) {
  for (const p of PAST) {
    await addBaselineFor(request, student.student_id, student.token, { text: p.text, provenance: 'verified', assignment: p.assignment })
  }
}

// Analyse the paper on Writing State as the teacher; returns the score response.
async function analyse(page, studentId) {
  await page.goto(`/original/writing-state.html?student=${encodeURIComponent(studentId)}`)
  await expect(page.locator('#an-form')).toBeVisible({ timeout: 20_000 })
  await page.locator('#an-assign').fill('Orthodoxy, chapter 1')
  await page.locator('#an-text').fill(PAPER)
  const scored = page.waitForResponse(r => r.url().endsWith('/score') && r.request().method() === 'POST', { timeout: 90_000 })
  await page.locator('#an-go').click()
  const res = await scored
  expect(res.ok()).toBe(true)
  await expect(page.locator('#an-done')).toBeVisible({ timeout: 30_000 })
  return res.json()
}

test.describe('side by side, flags off (the default)', () => {
  test('Writing State shows no new link and the page shows nothing', async ({ browser, request, testTenant }) => {
    test.setTimeout(120_000)
    const { staff, student, baseURL } = testTenant
    await seedPastPapers(request, student)
    const context = await browser.newContext({ storageState: staffStorageState(baseURL, staff) })
    const page = await context.newPage()
    const body = await analyse(page, student.student_id)
    expect(body.evidence ?? null).toBeNull()
    expect(body.preliminary ?? null).toBeNull()
    await expect(page.locator('#tri-packet')).toBeVisible()
    await expect(page.locator('#tri-evidence')).toBeHidden()

    await page.goto('/original/evidence.html')
    await expect(page.locator('#ev-empty')).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('#ev-empty')).toContainText('No side-by-side comparison for this analysis')
    await expect(page.locator('#paper')).toBeHidden()
    await expect(page.locator('.ex')).toHaveCount(0)
    await expect(page.locator('#prelim-chip')).toHaveCount(0)
    await context.close()
  })
})

test.describe('side by side, flags on @evidence-on', () => {
  test('cards render, marks are API slices, every measurement is listed @evidence-on', async ({ browser, request, testTenant }) => {
    test.setTimeout(180_000)
    const { staff, student, baseURL } = testTenant
    await seedPastPapers(request, student)
    const context = await browser.newContext({ storageState: staffStorageState(baseURL, staff), viewport: { width: 1440, height: 1000 } })
    const page = await context.newPage()
    const body = await analyse(page, student.student_id)
    const ev = body.evidence
    expect(ev, 'this run needs a server started with EVIDENCE_PASSAGES_ENABLED=1').toBeTruthy()
    expect(Array.isArray(ev.all_features)).toBe(true)
    expect(body.preliminary.label).toBe('Preliminary · unvalidated · not a judgment')
    expect(ev.baseline_papers.map(p => p.assignment)).toEqual(PAST.map(p => p.assignment))

    const link = page.locator('#tri-evidence')
    await expect(link).toBeVisible()
    await link.click()
    await expect(page).toHaveURL(/\/original\/evidence\.html/)
    await expect(page.locator('#paper')).toBeVisible({ timeout: 15_000 })

    // The summary is the API's own counts.
    const active = ev.all_features.filter(f => f.kind === 'located' || f.kind === 'whole_text')
    const outside = active.filter(f => f.engine_scale.outside_past_range).length
    await expect(page.locator('#p-summary .lead')).toHaveText(
      `This paper is outside the past-paper range on ${outside} of ${active.length} active measurements, and within that range on ${active.length - outside}.`)
    await expect(page.locator('#prelim-chip')).toContainText('Preliminary · unvalidated · not a judgment')
    await expect(page.locator('.notice')).toContainText('This is a starting point, not a verdict.')
    // Three past papers: the thin-baseline caution is shown.
    await expect(page.locator('#thin-note')).toBeVisible()

    // Biggest differences: Original's top list, in its order.
    await expect(page.locator('#p-diff > .ex')).toHaveCount(ev.features.length)
    const topCodes = await page.locator('#p-diff > .ex').evaluateAll(els => els.map(e => e.dataset.code))
    expect(topCodes).toEqual(ev.features.map(f => f.code))
    await expect(page.locator('#p-steady > .ex').first()).toBeVisible()

    // Every marked word is the exact slice of its passage the API named.
    const slices = new Set()
    const quotes = []
    for (const f of ev.all_features) {
      for (const side of [f.this_paper, f.past_papers]) {
        for (const q of (side && side.examples) || []) quotes.push(q)
      }
    }
    for (const q of quotes) slices.add(q.passage.slice(q.match_start - q.passage_start, q.match_end - q.passage_start))
    const marks = await page.locator('.ex-q mark').allTextContents()
    expect(marks.length).toBeGreaterThan(0)
    for (const m of marks) expect(slices.has(m), m).toBe(true)
    // The first top-list card with sentences marks the API's first example exactly.
    const firstLocated = ev.features.find(f => f.locatable && f.this_paper && f.this_paper.examples.length)
    if (firstLocated) {
      const q = ev.all_features.find(f => f.code === firstLocated.code).this_paper.examples[0]
      const card = page.locator(`#p-diff > .ex[data-code="${firstLocated.code}"]`)
      await expect(card.locator('.ex-q mark').first()).toHaveText(q.passage.slice(q.match_start - q.passage_start, q.match_end - q.passage_start))
    }

    // Every measurement is listed: the compared ones, and any whose papers do not
    // all share one value, as rows; the ones where every paper has the same
    // fixed value, and the comparison measurements past papers have no value
    // for, in "not used".
    const constant = f => [f.engine_scale.this_paper, ...f.engine_scale.past_papers.map(p => p.value)].every((v, _, a) => v === a[0])
    const notCompared = ev.all_features.filter(f => f.kind === 'not_compared')
    expect(notCompared.map(f => f.code).sort()).toEqual(['argument_sequence_likelihood', 'char_trigram_profile_divergence', 'error_kl_divergence',
      'function_word_profile_divergence', 'punctuation_error_ratio', 'semantic_centroid_proximity', 'stumble_rate_consistency'])
    for (const f of notCompared) {
      expect(f.engine_scale.difference).toBeNull()
      expect(f.in_top_list).toBe(false)
      expect(ev.features.map(t => t.code)).not.toContain(f.code)
    }
    const unused = ev.all_features.filter(f => f.kind === 'not_compared' || (!(f.kind === 'located' || f.kind === 'whole_text') && constant(f)))
    for (const f of notCompared) await expect(page.locator(`#m-not-used li[data-code="${f.code}"]`)).toContainText('Not compared: past papers have no value for this.')
    await expect(page.locator('#p-summary')).toContainText('7 comparison measurements not compared, because past papers have no value for them')
    await expect(page.locator('#p-all > details.m:not(.notused)')).toHaveCount(ev.all_features.length - unused.length)
    await expect(page.locator('#m-not-used li')).toHaveCount(unused.length)
    const listed = await page.locator('#p-all [data-code]').evaluateAll(els => els.filter(e => e.matches('details.m, li')).map(e => e.dataset.code))
    expect(listed.sort()).toEqual(ev.all_features.map(f => f.code).sort())
    expect(ev.all_features.length).toBe(109)

    // A row opens from the keyboard and shows its side-by-side card.
    const located = active.find(f => f.kind === 'located' && f.this_paper.examples.length && f.past_papers.examples.length)
    const row = page.locator(`#m-${located.code}`)
    await row.locator('summary').focus()
    await page.keyboard.press('Enter')
    await expect(row).toHaveAttribute('open', '')
    await expect(row.locator('.ex .ex-q mark').first()).toBeVisible()

    // Where the past papers came from: their stored titles.
    for (const p of PAST) await expect(page.locator('#p-past')).toContainText(p.assignment)

    // WCAG 2 A/AA on the paper, with a row open (contrast included).
    await page.locator('#m-not-used summary').click()
    const axe = await new AxeBuilder({ page }).include('#paper').withTags(['wcag2a', 'wcag2aa']).analyze()
    expect(axe.violations.map(v => `${v.id}: ${v.nodes.length}`)).toEqual([])
    await context.close()
  })

  test('a student never sees the side-by-side page or its data @evidence-on', async ({ request, studentPage, testTenant }) => {
    test.setTimeout(120_000)
    const { student } = testTenant
    await seedPastPapers(request, student)
    // The score route never hands a student session the evidence or the chip.
    const res = await request.post(`/students/${encodeURIComponent(student.student_id)}/score`, {
      headers: { Authorization: `Bearer ${student.token}` },
      data: { text: PAPER, assignment: 'Orthodoxy' },
    })
    if (res.ok()) {
      const body = await res.json()
      expect(body.evidence ?? null).toBeNull()
      expect(body.preliminary ?? null).toBeNull()
    } else {
      expect([401, 403, 404, 409, 422]).toContain(res.status())
    }
    // The page itself sends a student session to Collections.
    await studentPage.goto('/original/evidence.html')
    await expect(studentPage).not.toHaveURL(/\/original\/evidence\.html/, { timeout: 15_000 })
    await expect(studentPage.locator('.ex')).toHaveCount(0)
    for (const path of ['/original/voice.html', '/original/my-work.html']) {
      await studentPage.goto(path)
      await studentPage.waitForLoadState('networkidle')
      await expect(studentPage.locator('a[href*="evidence.html"]')).toHaveCount(0)
      await expect(studentPage.getByText('Side by side')).toHaveCount(0)
    }
  })
})

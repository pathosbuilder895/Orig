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
const DATES = ['2026-01-14', '2026-02-11', '2026-03-10']
const PAST = [1, 2, 3].map(i => ({ text: read(`mill-${i}.txt`), assignment: `On Liberty, part ${i}`, date: DATES[i - 1] }))
const PAPER = read('chesterton.txt')

async function seedPastPapers(request, student) {
  for (const p of PAST) {
    await addBaselineFor(request, student.student_id, student.token, { text: p.text, provenance: 'verified', assignment: p.assignment, submittedAt: p.date })
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

    // A habit opens with its two numbers only: no quote, no mark, no side-by-side link.
    await page.locator('#heatmap [data-code]').first().click()
    await expect(page.locator('#hero-evi')).toBeVisible()
    await expect(page.locator('#evi-name')).not.toHaveText('')
    await expect(page.locator('#evi-sub-lbl')).toHaveText('This submission')
    await expect(page.locator('#hero-evi .evi-q')).toHaveCount(0)
    await expect(page.locator('#hero-evi mark')).toHaveCount(0)
    await expect(page.locator('#evi-side')).toBeHidden()

    // The packet is the numbers-only one: no side-by-side section.
    await page.locator('#tri-packet').click()
    await expect(page).toHaveURL(/\/original\/packet\.html/)
    await page.waitForLoadState('networkidle')
    await expect(page.locator('#p-side')).toHaveCount(0)
    await expect(page.locator('.ex-q mark')).toHaveCount(0)
    await expect(page.getByText('Side by side')).toHaveCount(0)

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

  test('every habit opens its passages on Writing State, the packet quotes the API @evidence-on', async ({ browser, request, testTenant }) => {
    test.setTimeout(240_000)
    const { staff, student, baseURL } = testTenant
    await seedPastPapers(request, student)
    const context = await browser.newContext({ storageState: staffStorageState(baseURL, staff), viewport: { width: 1440, height: 1000 } })
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', e => errors.push(String(e)))
    const body = await analyse(page, student.student_id)
    const ev = body.evidence
    expect(ev, 'this run needs a server started with EVIDENCE_PASSAGES_ENABLED=1').toBeTruthy()
    const byCode = new Map(ev.all_features.map(f => [f.code, f]))
    const slice = q => q.passage.slice(q.match_start - q.passage_start, q.match_end - q.passage_start)
    const dayOf = iso => page.evaluate(d => {
      const [y, m, day] = d.split('-').map(Number)
      return new Date(y, m - 1, day).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
    }, iso)
    // The stored titles and dates of the past papers, as the panel labels them.
    expect(ev.baseline_papers.map(p => (p.submitted_at || '').slice(0, 10))).toEqual(DATES)
    const labelOf = async paper => {
      const p = ev.baseline_papers.find(x => x.paper === paper)
      return `${p.assignment} · ${await dayOf(p.submitted_at.slice(0, 10))}`
    }
    const examples = (f, side) => (f && f[side] && f[side].examples) || []

    // Habit codes, tiers and names from the heatmap bars themselves.
    const bars = await page.locator('#heatmap [data-code]').evaluateAll(els => els.map(e => ({
      code: e.dataset.code, tier: e.dataset.tier, name: (/^(.*?): (?:baseline \d|no baseline yet)/.exec(e.title) || [])[1] || '' })))
    expect(bars.length).toBeGreaterThan(80)

    const panelFor = async (code, name) => {
      await expect(page.locator('#hero-evi')).toBeVisible()
      if (name) await expect(page.locator('#evi-name')).toHaveText(name)
      const f = byCode.get(code)
      const tp = f && f.kind === 'located' ? examples(f, 'this_paper').slice(0, 3) : []
      const pp = f && f.kind === 'located' ? examples(f, 'past_papers').slice(0, 3) : []
      await expect(page.locator('#evi-sub-lbl')).toHaveText('This paper')
      if (tp.length && pp.length) {
        const sub = page.locator('#evi-sub .evi-q mark'), base = page.locator('#evi-base .evi-q mark')
        expect(await sub.count(), `${code} this paper marks`).toBeGreaterThan(0)
        expect(await base.count(), `${code} past marks`).toBeGreaterThan(0)
        expect(await sub.first().textContent(), code).toBe(slice(tp[0]))
        expect(await base.first().textContent(), code).toBe(slice(pp[0]))
        // Past source label: stored title and date.
        await expect(page.locator('#evi-base-src')).toContainText(await labelOf(pp[0].paper))
      } else {
        await expect(page.locator('#hero-evi .none').first()).toBeVisible()
        // A side with no passage shows no mark.
        if (!tp.length) await expect(page.locator('#evi-sub .evi-q')).toHaveCount(0)
        if (!pp.length) await expect(page.locator('#evi-base .evi-q')).toHaveCount(0)
      }
    }

    // 1. Every habit with a heatmap bar.
    let both = 0
    for (const b of bars) {
      await page.locator(`#heatmap [data-code="${b.code}"]`).click()
      await panelFor(b.code, byCode.get(b.code) ? byCode.get(b.code).name : b.name)
      const f = byCode.get(b.code)
      if (f && f.kind === 'located' && examples(f, 'this_paper').length && examples(f, 'past_papers').length) both++
    }
    expect(both, 'some habits quote both sides').toBeGreaterThan(0)

    // 2. Every Largest differences row.
    const rowCodes = await page.locator('#fd-body .fd-row[data-code]').evaluateAll(els => els.map(e => e.dataset.code))
    expect(rowCodes.length).toBeGreaterThan(0)
    for (const code of rowCodes) {
      await page.locator(`#fd-body .fd-row[data-code="${code}"]`).click()
      await panelFor(code, byCode.get(code).name)
    }

    // 3. One chip per tier opens a habit of that tier; the panel's rows open too.
    const tiers = await page.locator('.tchip[data-tier]').evaluateAll(els => els.map(e => e.dataset.tier))
    expect(tiers.length).toBeGreaterThan(5)
    for (const tier of tiers) {
      await page.locator(`.tchip[data-tier="${tier}"]`).click()
      const mine = bars.filter(b => b.tier === tier)
      if (!mine.length) continue
      await expect(page.locator('#hero-evi')).toBeVisible()
      const shown = await page.locator('#evi-name').textContent()
      expect(mine.map(b => byCode.get(b.code).name), tier).toContain(shown)
      const code = mine.find(b => byCode.get(b.code).name === shown).code
      await panelFor(code, shown)
      for (const rc of await page.locator('#fd-body .fd-row[data-code]').evaluateAll(els => els.map(e => e.dataset.code))) {
        await page.locator(`#fd-body .fd-row[data-code="${rc}"]`).click()
        await panelFor(rc, byCode.get(rc).name)
      }
    }
    // Family headers pin without error (and again to unpin).
    const heads = page.locator('.tgrp-h')
    for (let i = 0; i < await heads.count(); i++) { await heads.nth(i).click(); await heads.nth(i).click() }
    expect(errors).toEqual([])

    // 4. With a located habit open, the triage buttons are visible and not covered.
    await page.goto(`/original/writing-state.html?student=${encodeURIComponent(student.student_id)}`)
    await expect(page.locator('#heatmap [data-code]').first()).toBeVisible({ timeout: 20_000 })
    const target = ev.all_features.find(f => f.kind === 'located' && examples(f, 'this_paper').length && examples(f, 'past_papers').length && bars.some(b => b.code === f.code))
    await page.locator(`#heatmap [data-code="${target.code}"]`).click()
    await panelFor(target.code, target.name)
    for (const sel of ['#tri-packet', '#tri-evidence']) {
      const el = page.locator(sel)
      await expect(el).toBeVisible()
      await el.scrollIntoViewIfNeeded()
      const top = await el.evaluate(n => {
        const r = n.getBoundingClientRect()
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
        return !!hit && (hit === n || n.contains(hit))
      })
      expect(top, `${sel} is not covered`).toBe(true)
    }
    // The in-panel link, with a normal click, opens that habit's row.
    await page.locator('#evi-side').click()
    await expect(page).toHaveURL(new RegExp(`/original/evidence\\.html.*#m-${target.code}$`))
    await expect(page.locator(`#m-${target.code}`)).toHaveAttribute('open', '', { timeout: 15_000 })

    // 5. The packet quotes the API's own sentences.
    await page.goto(`/original/writing-state.html?student=${encodeURIComponent(student.student_id)}`)
    await expect(page.locator('#heatmap [data-code]').first()).toBeVisible({ timeout: 20_000 })
    await page.locator(`#heatmap [data-code="${target.code}"]`).click()
    await page.locator('#tri-packet').click()
    await expect(page).toHaveURL(/\/original\/packet\.html/)
    await expect(page.locator('#p-side .ex').first()).toBeVisible({ timeout: 15_000 })
    expect(await page.locator('#p-side .ex').count()).toBeLessThanOrEqual(5)
    const slices = new Set()
    for (const f of ev.all_features) for (const side of ['this_paper', 'past_papers']) for (const q of examples(f, side)) slices.add(slice(q))
    const marks = await page.locator('#p-side .ex-q mark').allTextContents()
    expect(marks.length).toBeGreaterThan(0)
    for (const m of marks) expect(slices.has(m), m).toBe(true)
    // The top habit's first sentences, exactly.
    const top = ev.features.map(t => byCode.get(t.code)).find(f => f.kind === 'located' && examples(f, 'this_paper').length && examples(f, 'past_papers').length)
    await expect(page.locator('#p-side .ex').first().locator('.ex-q mark').first()).toHaveText(slice(examples(top, 'this_paper')[0]))
    // No page along the way (the panel, the side-by-side link, the packet) threw.
    expect(errors).toEqual([])
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
    // Staff pages send a student away and show no evidence, quote, mark or preliminary label.
    for (const path of ['/original/writing-state.html', '/original/packet.html', '/original/evidence.html']) {
      await studentPage.goto(path)
      await expect(studentPage).not.toHaveURL(new RegExp(path.replace(/\./g, '\\.') + '$'), { timeout: 15_000 })
      for (const sel of ['.evi-q', '.ex', 'mark']) await expect(studentPage.locator(sel)).toHaveCount(0)
      await expect(studentPage.getByText('Preliminary')).toHaveCount(0)
    }
    for (const path of ['/original/voice.html', '/original/my-work.html']) {
      await studentPage.goto(path)
      await studentPage.waitForLoadState('networkidle')
      await expect(studentPage.locator('a[href*="evidence.html"]')).toHaveCount(0)
      await expect(studentPage.getByText('Side by side')).toHaveCount(0)
    }
  })
})

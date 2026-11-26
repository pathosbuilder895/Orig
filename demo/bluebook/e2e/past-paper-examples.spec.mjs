/**
 * past-paper-examples.spec.mjs: Writing State before any analysis
 * (demo/original/writing-state.html, ADR-013).
 *
 * With no analysis on the page, the habit panel shows real sentences from the
 * student's own past papers, one family of related habits at a time, from the
 * staff-only GET /students/{id}/past-paper-examples. That route answers only
 * when EVIDENCE_PASSAGES_ENABLED=1, so the suite runs this file twice, against
 * two servers (.github/workflows/test.yml):
 *
 * - the main run (flags set to 0; on is the default since 2026-11): the request answers 404 and the
 *   panel stays closed, as before;
 * - "@evidence-on" (a server started with the flags on): the panel opens on
 *   sentence length with one column per past paper, related habits and family
 *   buttons switch what it shows, an analysis replaces it with this paper
 *   beside the past papers, a late reply never takes the panel back, student
 *   markup is shown as text, and a student session gets nothing.
 *
 * The writing is public domain: three passages of J. S. Mill's On Liberty
 * (1859) as the student's past papers, and a passage of G. K. Chesterton's
 * Orthodoxy (1908) as the paper analysed.
 */

import { isolatedTest as test, expect } from './fixtures/tenancy.mjs'
import { addBaselineFor, staffStorageState } from './fixtures/api-setup.mjs'
import { DATES, PAST, seedPastPapers, analyse, openLookCloser } from './fixtures/evidence-papers.mjs'

// The name the roster gives the student (fixtures/api-setup.mjs studentLogin).
const ROSTER_NAME = 'E2E Student'
const JUDGMENT = /suspicious|does(n.t| not) match|deviation/i

const isExamples = url => url.includes('/past-paper-examples')
const slice = q => q.passage.slice(q.match_start - q.passage_start, q.match_end - q.passage_start)
// A related row quotes about this many characters of each passage (writing-state.html REL_CHARS).
const REL_CHARS = 140
// The quotes a related row shows for one paper: one, or the longest and the shortest.
const relShown = p => p.examples.slice(0, p.examples.some(x => x.role === 'longest' || x.role === 'shortest') ? 2 : 1)

// The route's own answer, read with the teacher's token, for comparison.
async function examplesFor(page, staff, studentId, habit) {
  const res = await page.request.get(`/students/${encodeURIComponent(studentId)}/past-paper-examples?habit=${habit}`, {
    headers: { Authorization: `Bearer ${staff.token}` },
  })
  expect(res.status(), 'this run needs a server started with EVIDENCE_PASSAGES_ENABLED=1').toBe(200)
  return res.json()
}

async function staffPage(browser, testTenant) {
  const { staff, baseURL } = testTenant
  const context = await browser.newContext({ storageState: staffStorageState(baseURL, staff), viewport: { width: 1440, height: 1000 } })
  return { context, page: await context.newPage() }
}

test.describe('past-paper examples, flags set to 0', () => {
  test('no analysis yet: no examples panel, flags off', async ({ browser, request, testTenant }) => {
    test.setTimeout(120_000)
    const { student } = testTenant
    await seedPastPapers(request, student, testTenant.staff)
    const { context, page } = await staffPage(browser, testTenant)
    const examples = page.waitForResponse(r => isExamples(r.url()), { timeout: 30_000 })
    await page.goto(`/original/writing-state.html?student=${encodeURIComponent(student.student_id)}`)
    expect((await examples).status()).toBe(404)
    await expect(page.locator('#an-form')).toBeVisible({ timeout: 20_000 })
    // The roster's reply re-renders the page with the student's name.
    await expect(page.locator('#hero-name')).toHaveText(ROSTER_NAME, { timeout: 20_000 })
    await expect(page.locator('#hero-evi')).toBeHidden()
    await expect(page.locator('#evi-past')).toBeHidden()
    // A tier chip only pins its tier, as before.
    await openLookCloser(page)
    const chip = page.locator('.tchip[data-tier="tier2"]')
    await chip.click()
    await expect(chip).toHaveClass(/\bon\b/)
    await expect(page.locator('#hero-evi')).toBeHidden()
    await context.close()
  })
})

test.describe('past-paper examples, flags on @evidence-on', () => {
  test('past papers fill the panel before any analysis @evidence-on', async ({ browser, request, testTenant }) => {
    test.setTimeout(120_000)
    const { staff, student } = testTenant
    await seedPastPapers(request, student, testTenant.staff)
    const { context, page } = await staffPage(browser, testTenant)
    const errors = []
    page.on('pageerror', e => errors.push(String(e)))
    const api = await examplesFor(page, staff, student.student_id, 'mean_sentence_length')
    expect(api.family).toBe('Sentence shape')
    expect(api.baseline_papers.map(p => p.assignment)).toEqual(PAST.map(p => p.assignment))
    const msl = api.features.find(f => f.code === 'mean_sentence_length')
    const first = msl.per_paper[0].examples[0]
    expect(first.role).toBe('typical')

    // Hold the roster's readiness reply until the panel is open, so the
    // roster's late re-render is sure to come after it (Review Focus 2).
    let releaseRoster
    const rosterHeld = new Promise(r => { releaseRoster = r })
    await page.route('**/readiness', async route => { await rosterHeld; await route.continue() })
    await page.goto(`/original/writing-state.html?student=${encodeURIComponent(student.student_id)}`)
    await expect(page.locator('#evi-past')).toBeVisible({ timeout: 30_000 })
    releaseRoster()
    await expect(page.locator('#hero-name')).toHaveText(ROSTER_NAME, { timeout: 20_000 })

    // Still open on sentence length after the roster's re-render.
    await expect(page.locator('#hero-evi')).toBeVisible()
    await expect(page.locator('#evi-past')).toBeVisible()
    await expect(page.locator('#evi-name')).toHaveText(msl.name)
    // The analysed view's parts are out of the way.
    await expect(page.locator('#hero-evi .evi-cols')).toBeHidden()
    await expect(page.locator('#evi-tabs')).toBeHidden()
    await expect(page.locator('#evi-foot')).toBeHidden()
    await expect(page.locator('#evi-flag')).toBeHidden()
    // The family buttons, the current one pressed.
    await expect(page.locator('#evi-fams button')).toHaveText(api.families.map(f => f.name))
    await expect(page.locator('#evi-fams button[aria-pressed="true"]')).toHaveText('Sentence shape')

    // One column per past paper, headed with its stored title.
    const cols = page.locator('#evi-pcols .evi-pcol')
    await expect(cols).toHaveCount(3)
    for (let i = 0; i < PAST.length; i++) await expect(cols.nth(i)).toContainText(PAST[i].assignment)
    // The first marked words are the API's first example, exactly; its source says why it was picked.
    await expect(cols.first().locator('.evi-q mark').first()).toHaveText(slice(first.quote))
    await expect(cols.first().locator('.evi-psrc').first()).toContainText('Typical')
    expect(msl.unit).toBeTruthy()
    await expect(cols.first()).toContainText(`${msl.unit}`)

    // The family's other habits, one compact row each, in a box of bounded height.
    await expect(page.locator('#evi-rel .evi-rel-row')).toHaveCount(6)
    await expect(page.locator('#evi-rel')).toContainText('Related: how these sentences are built')
    const relBox = await page.locator('#evi-rel').boundingBox()
    expect(relBox.height).toBeLessThanOrEqual(600)
    // Each row's quotes are short verbatim windows of the API's passages. A counted part
    // that fits is marked whole, exactly the API's slice; one longer than the window (a
    // long sentence, for sentence length) shows the sentence's start with no mark.
    // The button's name is the habit's, not the whole row's text.
    let marked = 0, windowed = 0
    for (const f of api.features.filter(x => x.code !== msl.code)) {
      const row = page.locator(`#evi-rel .evi-rel-row[data-code="${f.code}"]`)
      await expect(row).toHaveAccessibleName(`${f.name}, show in full`)
      for (const [i, p] of f.per_paper.entries()) {
        const quotes = row.locator('.evi-rel-cell').nth(i).locator('.evi-q')
        const shown = p.count ? relShown(p) : []
        await expect(quotes).toHaveCount(shown.length)
        for (const [k, x] of shown.entries()) {
          const q = quotes.nth(k), m = slice(x.quote)
          if (x.quote.passage.length <= REL_CHARS || m.length <= REL_CHARS) {
            await expect(q.locator('mark')).toHaveText(m)
            marked++
          } else {
            await expect(q.locator('mark')).toHaveCount(0)
          }
          if (x.quote.passage.length <= REL_CHARS) continue
          // Cut at spaces with "…" where cut; what is left is the passage's own characters.
          const text = await q.textContent()
          expect(text).toContain('\u2026')
          const inner = text.replace(/^\u2026 /, '').replace(/ \u2026$/, '')
          expect(x.quote.passage).toContain(inner)
          expect(inner.length).toBeLessThan(x.quote.passage.length)
          expect(inner.length).toBeLessThanOrEqual(REL_CHARS + 40)
          windowed++
        }
      }
    }
    expect(marked, 'some related quote is marked').toBeGreaterThan(0)
    expect(windowed, 'some related quote is a window of a long passage').toBeGreaterThan(0)

    // One plain line, and no wording of judgment or score anywhere in the panel's own
    // words. The quoted sentences are the student's and are left out of this check:
    // Mill himself writes "an intelligent deviation from custom".
    await expect(page.locator('#evi-pline')).toContainText('own past papers')
    await expect(page.locator('#evi-pline')).toContainText(ROSTER_NAME)
    const ownWords = await page.locator('#hero-evi').evaluate(el => {
      const copy = el.cloneNode(true)
      copy.querySelectorAll('.evi-q').forEach(q => q.remove())
      return copy.textContent
    })
    expect(ownWords).not.toMatch(JUDGMENT)
    await expect(page.locator('#evi-nums')).not.toContainText('this paper')

    // "Back to the pattern" closes it, as today.
    await page.locator('#evi-close').click()
    await expect(page.locator('#hero-evi')).toBeHidden()
    expect(errors).toEqual([])
    await context.close()
  })

  test('a related row and a family button switch the habit @evidence-on', async ({ browser, request, testTenant }) => {
    test.setTimeout(120_000)
    const { staff, student } = testTenant
    await seedPastPapers(request, student, testTenant.staff)
    const { context, page } = await staffPage(browser, testTenant)
    const errors = []
    page.on('pageerror', e => errors.push(String(e)))
    const shape = await examplesFor(page, staff, student.student_id, 'mean_sentence_length')
    const voice = await examplesFor(page, staff, student.student_id, 'first_person_ratio')
    const sent = []
    page.on('request', r => { if (isExamples(r.url())) sent.push(r.url()) })

    await page.goto(`/original/writing-state.html?student=${encodeURIComponent(student.student_id)}`)
    await expect(page.locator('#evi-past')).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('#hero-name')).toHaveText(ROSTER_NAME, { timeout: 20_000 })
    expect(sent.length).toBe(1)

    // A related row becomes the habit in full, with no new request.
    const variance = shape.features.find(f => f.code === 'sentence_length_variance')
    await page.locator('#evi-rel .evi-rel-row[data-code="sentence_length_variance"]').click({ timeout: 15_000 })
    await expect(page.locator('#evi-name')).toHaveText(variance.name)
    const col1 = page.locator('#evi-pcols .evi-pcol').first()
    await expect(col1.locator('.evi-q')).toHaveCount(2)
    await expect(col1.locator('.evi-psrc').nth(0)).toContainText('Longest')
    await expect(col1.locator('.evi-psrc').nth(1)).toContainText('Shortest')
    await expect(col1.locator('.evi-q mark').first()).toHaveText(slice(variance.per_paper[0].examples[0].quote))
    // Sentence length is now a related row.
    await expect(page.locator('#evi-rel .evi-rel-row[data-code="mean_sentence_length"]')).toHaveCount(1)
    await expect(page.locator('#evi-rel .evi-rel-row[data-code="sentence_length_variance"]')).toHaveCount(0)
    expect(sent.length).toBe(1)

    // The Voice button fetches that family once and opens its first habit.
    const firstPerson = voice.features.find(f => f.code === 'first_person_ratio')
    const voiceReq = page.waitForRequest(r => isExamples(r.url()) && r.url().includes('habit=first_person_ratio'))
    await page.locator('#evi-fams button', { hasText: 'Voice' }).click()
    await voiceReq
    await expect(page.locator('#evi-name')).toHaveText(firstPerson.name)
    await expect(page.locator('#evi-fams button[aria-pressed="true"]')).toHaveText('Voice')
    await expect(page.locator('#evi-rel')).toContainText('Related: how the writer speaks')
    expect(sent.length).toBe(2)

    // A habit that never occurs in a paper reads "none in this paper" there (Review Focus 4).
    // The contraction counter does find a few in the Mill papers (it counts forms like
    // "nation's"), so questions, absent from part 1, keep this check from passing vacuously.
    let papersWithNone = 0
    for (const f of voice.features.filter(x => x.code !== 'first_person_ratio')) {
      const row = page.locator(`#evi-rel .evi-rel-row[data-code="${f.code}"]`)
      await expect(row).toHaveCount(1)
      await expect(row.locator('.evi-rel-cell')).toHaveCount(f.per_paper.length)
      for (const [i, p] of f.per_paper.entries()) {
        if (p.count !== 0) continue
        papersWithNone++
        await expect(row.locator('.evi-rel-cell').nth(i)).toContainText('none in this paper')
        await expect(row.locator('.evi-rel-cell').nth(i).locator('.evi-q')).toHaveCount(0)
      }
    }
    expect(papersWithNone, 'some Voice habit is absent from some Mill paper').toBeGreaterThan(0)
    const question = voice.features.find(f => f.code === 'question_ratio')
    const noQuestions = question.per_paper.findIndex(p => p.count === 0)
    expect(noQuestions).toBeGreaterThanOrEqual(0)
    // In full, that paper's column says so in place of quotes.
    await page.locator('#evi-rel .evi-rel-row[data-code="question_ratio"]').click()
    await expect(page.locator('#evi-name')).toHaveText(question.name)
    const empty = page.locator('#evi-pcols .evi-pcol').nth(noQuestions)
    await expect(empty).toContainText('None in this paper.')
    await expect(empty.locator('.evi-q')).toHaveCount(0)
    expect(sent.length).toBe(2)

    // Back to Sentence shape: from the cache, no new request.
    await page.locator('#evi-fams button', { hasText: 'Sentence shape' }).click()
    await expect(page.locator('#evi-name')).toHaveText(shape.features[0].name)
    expect(sent.length).toBe(2)

    // A bar elsewhere on the page opens its family with that habit in full.
    const passive = voice.features.find(f => f.code === 'passive_voice_ratio')
    await openLookCloser(page)
    await page.locator('#heatmap [data-code="passive_voice_ratio"]').click()
    await expect(page.locator('#evi-name')).toHaveText(passive.name)
    await expect(page.locator('#evi-fams button[aria-pressed="true"]')).toHaveText('Voice')
    expect(sent.length).toBe(2)
    expect(errors).toEqual([])
    await context.close()
  })

  test('a habit with no examples shows its numbers, and the newest choice wins over a slow family @evidence-on', async ({ browser, request, testTenant }) => {
    test.setTimeout(120_000)
    const { student } = testTenant
    await seedPastPapers(request, student, testTenant.staff)
    const { context, page } = await staffPage(browser, testTenant)
    const errors = []
    page.on('pageerror', e => errors.push(String(e)))
    // Hold the Voice and Linking ideas families until told.
    const gates = new Map([['first_person_ratio', null], ['causal_ratio', null]])
    const opened = new Map()
    for (const habit of gates.keys()) opened.set(habit, new Promise(r => gates.set(habit, r)))
    await page.route(url => isExamples(url.href) && [...gates.keys()].some(h => url.href.includes(`habit=${h}`)), async route => {
      const habit = [...gates.keys()].find(h => route.request().url().includes(`habit=${h}`))
      await opened.get(habit)
      await route.continue()
    })
    await page.goto(`/original/writing-state.html?student=${encodeURIComponent(student.student_id)}`)
    await expect(page.locator('#evi-past')).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('#hero-name')).toHaveText(ROSTER_NAME, { timeout: 20_000 })

    // A habit that is not one of the quotable ones: today's numbers-only panel.
    await openLookCloser(page)
    await page.locator('#heatmap [data-code="type_token_ratio"]').click()
    await expect(page.locator('#evi-past')).toBeHidden()
    await expect(page.locator('#hero-evi .evi-cols')).toBeVisible()
    await expect(page.locator('#evi-sub-lbl')).toHaveText('This submission')
    await expect(page.locator('#evi-sub')).toContainText('Analyse a paper to see where it sits on this habit.')

    // A Voice bar asks for its family; the teacher closes the panel before it answers.
    const late = habit => page.waitForResponse(r => r.url().includes(`habit=${habit}`), { timeout: 30_000 })
    const voiceAnswer = late('first_person_ratio')
    await page.locator('#heatmap [data-code="first_person_ratio"]').click()
    await page.locator('#evi-close').click()
    await expect(page.locator('#hero-evi')).toBeHidden()
    gates.get('first_person_ratio')()
    await (await voiceAnswer).finished()
    await page.waitForTimeout(1_000)
    await expect(page.locator('#hero-evi')).toBeHidden()

    // A Linking ideas bar, then a numbers-only habit before it answers: the later choice stays.
    const linkingAnswer = late('causal_ratio')
    await page.locator('#heatmap [data-code="causal_ratio"]').click()
    await page.locator('#heatmap [data-code="type_token_ratio"]').click()
    await expect(page.locator('#hero-evi .evi-cols')).toBeVisible()
    gates.get('causal_ratio')()
    await (await linkingAnswer).finished()
    await page.waitForTimeout(1_000)
    await expect(page.locator('#evi-past')).toBeHidden()
    await expect(page.locator('#evi-sub-lbl')).toHaveText('This submission')

    // Both families are kept now: a Voice habit opens at once.
    await page.locator('#heatmap [data-code="question_ratio"]').click()
    await expect(page.locator('#evi-past')).toBeVisible()
    await expect(page.locator('#evi-fams button[aria-pressed="true"]')).toHaveText('Voice')
    expect(errors).toEqual([])
    await context.close()
  })

  test('a choice from the cache wins over a slow family, and a tier chip opens its family @evidence-on', async ({ browser, request, testTenant }) => {
    test.setTimeout(120_000)
    const { staff, student } = testTenant
    await seedPastPapers(request, student, testTenant.staff)
    const { context, page } = await staffPage(browser, testTenant)
    const errors = []
    page.on('pageerror', e => errors.push(String(e)))
    const shape = await examplesFor(page, staff, student.student_id, 'mean_sentence_length')
    const name = code => shape.features.find(f => f.code === code).name
    // Hold the Voice and Claims and confidence families until told.
    const gates = new Map([['first_person_ratio', null], ['hedging_density', null]])
    const opened = new Map()
    for (const habit of gates.keys()) opened.set(habit, new Promise(r => gates.set(habit, r)))
    await page.route(url => isExamples(url.href) && [...gates.keys()].some(h => url.href.includes(`habit=${h}`)), async route => {
      const habit = [...gates.keys()].find(h => route.request().url().includes(`habit=${h}`))
      await opened.get(habit)
      await route.continue()
    })
    const late = habit => page.waitForResponse(r => r.url().includes(`habit=${habit}`), { timeout: 30_000 })
    await page.goto(`/original/writing-state.html?student=${encodeURIComponent(student.student_id)}`)
    await expect(page.locator('#evi-past')).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('#hero-name')).toHaveText(ROSTER_NAME, { timeout: 20_000 })

    // The Voice button asks for its family; a related row from the cached family is chosen
    // before it answers. The row's habit stays, and the late reply moves no focus.
    const voiceAnswer = late('first_person_ratio')
    await page.locator('#evi-fams button', { hasText: 'Voice' }).click()
    await page.locator('#evi-rel .evi-rel-row[data-code="sentence_length_variance"]').click()
    await expect(page.locator('#evi-name')).toHaveText(name('sentence_length_variance'))
    gates.get('first_person_ratio')()
    await (await voiceAnswer).finished()
    await page.waitForTimeout(1_000)
    await expect(page.locator('#evi-name')).toHaveText(name('sentence_length_variance'))
    await expect(page.locator('#evi-fams button[aria-pressed="true"]')).toHaveText('Sentence shape')
    expect(await page.evaluate(() => document.activeElement && document.activeElement.id)).toBe('evi-pcols')

    // A bar in a family not yet asked for, then a bar in a cached one: the cached one stays.
    const claimsAnswer = late('hedging_density')
    await openLookCloser(page)
    await page.locator('#heatmap [data-code="hedging_density"]').click()
    await page.locator('#heatmap [data-code="comma_rate"]').click()
    await expect(page.locator('#evi-name')).toHaveText(name('comma_rate'))
    gates.get('hedging_density')()
    await (await claimsAnswer).finished()
    await page.waitForTimeout(1_000)
    await expect(page.locator('#evi-name')).toHaveText(name('comma_rate'))
    await expect(page.locator('#evi-fams button[aria-pressed="true"]')).toHaveText('Sentence shape')

    // With the panel closed, a tier chip opens it on that tier's first habit, in its family;
    // a second click on the pinned chip unpins it and closes the panel, as after an analysis.
    await page.locator('#evi-close').click()
    await expect(page.locator('#hero-evi')).toBeHidden()
    await openLookCloser(page)
    const chip = page.locator('.tchip[data-tier="tier2"]')
    await chip.click()
    await expect(page.locator('#hero-evi')).toBeVisible()
    await expect(page.locator('#evi-past')).toBeVisible()
    await expect(page.locator('#evi-fams button[aria-pressed="true"]')).toHaveText('Linking ideas')
    await expect(chip).toHaveClass(/\bon\b/)
    await chip.click()
    await expect(page.locator('#hero-evi')).toBeHidden()
    await expect(chip).not.toHaveClass(/\bon\b/)
    expect(errors).toEqual([])
    await context.close()
  })

  test('an analysis replaces past papers with this paper beside them @evidence-on', async ({ browser, request, testTenant }) => {
    test.setTimeout(180_000)
    const { student } = testTenant
    await seedPastPapers(request, student, testTenant.staff)
    const { context, page } = await staffPage(browser, testTenant)
    const errors = []
    page.on('pageerror', e => errors.push(String(e)))
    // Past papers are on the panel first, so the analysis is what takes them away.
    const body = await analyse(page, student.student_id, {
      beforeFill: () => expect(page.locator('#evi-past')).toBeVisible({ timeout: 30_000 }),
    })
    expect(body.evidence, 'this run needs a server started with EVIDENCE_PASSAGES_ENABLED=1').toBeTruthy()
    await expect(page.locator('#hero-name')).toHaveText(ROSTER_NAME, { timeout: 20_000 })
    await expect(page.locator('#hero-evi')).toBeHidden()

    // A habit now opens this paper beside the past papers, as before.
    await openLookCloser(page)
    await page.locator('#heatmap [data-code="comma_rate"]').click()
    await expect(page.locator('#hero-evi')).toBeVisible()
    await expect(page.locator('#evi-sub-lbl')).toHaveText('This paper')
    await expect(page.locator('#hero-evi .evi-cols')).toBeVisible()
    await expect(page.locator('#evi-past')).toBeHidden()

    // A reload shows the kept analysis and asks for no examples.
    const sent = []
    page.on('request', r => { if (isExamples(r.url())) sent.push(r.url()) })
    await page.reload()
    await expect(page.locator('#an-restored')).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('#hero-name')).toHaveText(ROSTER_NAME, { timeout: 20_000 })
    await page.waitForLoadState('networkidle')
    expect(sent).toEqual([])
    await expect(page.locator('#hero-evi')).toBeHidden()
    await expect(page.locator('#evi-past')).toBeHidden()
    expect(errors).toEqual([])
    await context.close()
  })

  test('a late examples reply never covers an analysis @evidence-on', async ({ browser, request, testTenant }) => {
    test.setTimeout(180_000)
    const { student } = testTenant
    await seedPastPapers(request, student, testTenant.staff)
    const { context, page } = await staffPage(browser, testTenant)
    // Hold the first examples reply until the analysis is on the page (Review Focus 1).
    let releaseExamples
    const held = new Promise(r => { releaseExamples = r })
    let holding = true
    const asked = page.waitForRequest(r => isExamples(r.url()), { timeout: 30_000 })
    await page.route('**/past-paper-examples*', async route => {
      if (holding) { holding = false; await held }
      await route.continue()
    })
    const body = await analyse(page, student.student_id)
    expect(body.evidence, 'this run needs a server started with EVIDENCE_PASSAGES_ENABLED=1').toBeTruthy()
    await asked
    const late = page.waitForResponse(r => isExamples(r.url()), { timeout: 30_000 })
    releaseExamples()
    const res = await late
    expect(res.status()).toBe(200)
    await res.finished()
    // Give the page time to act on the reply; it must not.
    await page.waitForTimeout(1_000)
    await expect(page.locator('#evi-past')).toBeHidden()
    await expect(page.locator('#hero-evi')).toBeHidden()
    await expect(page.locator('#an-done')).toBeVisible()
    await context.close()
  })

  test('student markup in a past paper is shown as text @evidence-on', async ({ browser, request, testTenant }) => {
    test.setTimeout(120_000)
    const { student } = testTenant
    // Three sentences of about one length, so all three are the paper's typical ones.
    const text = 'The note said <img src=x onerror="window.__x=1"> & <b>bold</b> in the margin of the old book. '
      + 'The second sentence is a plain one about the weather in the old town today. '
      + 'The third sentence tells of a long walk along the river in the cool evening.'
    await addBaselineFor(request, student.student_id, testTenant.staff.token, { text, provenance: 'verified', assignment: 'A <b>marked</b> & paper', submittedAt: DATES[0] })
    const { context, page } = await staffPage(browser, testTenant)
    await page.goto(`/original/writing-state.html?student=${encodeURIComponent(student.student_id)}`)
    await expect(page.locator('#evi-past')).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('#hero-name')).toHaveText(ROSTER_NAME, { timeout: 20_000 })
    const col1 = page.locator('#evi-pcols .evi-pcol').first()
    await expect(col1).toContainText('<b>bold</b>')
    await expect(col1).toContainText('<img src=x onerror="window.__x=1"> &')
    await expect(col1).toContainText('A <b>marked</b> & paper')
    await expect(page.locator('#evi-pcols img')).toHaveCount(0)
    await expect(page.locator('#hero-evi img, #hero-evi b:not(#evi-name)')).toHaveCount(0)
    expect(await page.evaluate(() => window.__x)).toBeUndefined()
    await context.close()
  })

  test('a student session gets no examples @evidence-on', async ({ request, testTenant }) => {
    // Three teacher-added papers (verified also runs the tension-arc read) can
    // outlast the 30 s default on a busy runner, as every other seeding test here allows.
    test.setTimeout(120_000)
    const { student } = testTenant
    await seedPastPapers(request, student, testTenant.staff)
    const res = await request.get(`/students/${encodeURIComponent(student.student_id)}/past-paper-examples`, {
      headers: { Authorization: `Bearer ${student.token}` },
    })
    expect(res.status()).toBe(403)
    const body = await res.text()
    for (const p of PAST) expect(body).not.toContain(p.text.slice(0, 40))
  })
})

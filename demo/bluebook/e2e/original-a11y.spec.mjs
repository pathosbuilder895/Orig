/**
 * original-a11y.spec.mjs: axe and tap-target checks on every page of the
 * Original staff suite (demo/original/).
 *
 * a11y.spec.mjs covers the Collections (Bluebook) screens; this file covers
 * the twelve plain HTML pages of Original: the ten teacher pages (index,
 * students, submissions, bluebook, reports, settings, baseline, writing-state,
 * evidence, packet) opened as staff, and the two student pages (voice,
 * my-work) opened as a student. Each is scanned at a desktop size (1440x1000)
 * and a phone size (390x844) with WCAG 2 A and AA rules, and the run fails on
 * any `serious` or `critical` violation. Writing State is scanned twice: with
 * the analyse form showing (before) and with a reading rendered (after
 * seedPastPapers + analyse); the packet and the side-by-side page are scanned
 * both empty and holding that reading.
 *
 * The scans measure settled UI (see settle() in a11y.spec.mjs for why: a
 * fade in flight makes axe report contrast failures that do not exist).
 *
 * Exclusions: none by rule. The only `exclude` is the decorative canvases
 * (the fingerprint and the voice portrait). They carry no text and
 * aria-hidden, so axe has nothing to say about them; excluding them keeps a
 * future canvas-only rule from tripping on pixels that are pure decoration.
 *
 * The tap-target test opens every page at 390x844 and measures every visible
 * `a, button, [role=button], summary, input, select` in the nav and the page
 * body. Each must be at least 44px tall; icon-only controls (no visible text)
 * must also be at least 44px wide. One kind of element is exempt, and only
 * one: an inline text link inside a sentence (computed display `inline`,
 * inside a parent that has text of its own outside the link; a button
 * styled as plain words, like Writing State's habit names in its summary
 * sentence, counts as one). WCAG 2.5.8 excepts those, and making them 44px
 * tall would pull the lines of the paragraph apart.
 *
 * Nothing here is tagged @evidence-on or @serial-lockout, so CI's main e2e
 * step runs it against the flags-off server.
 */

import AxeBuilder from '@axe-core/playwright'
import { test, isolatedTest, expect } from './fixtures/tenancy.mjs'
import { staffStorageState, studentStorageState } from './fixtures/api-setup.mjs'
import { seedPastPapers, analyse, openLookCloser } from './fixtures/evidence-papers.mjs'

const DESKTOP = { width: 1440, height: 1000 }
const PHONE = { width: 390, height: 844 }
const SIZES = [['1440', DESKTOP], ['390', PHONE]]

const TEACHER_PAGES = ['index', 'students', 'submissions', 'bluebook', 'reports', 'settings', 'baseline', 'writing-state', 'evidence', 'packet']
const STUDENT_PAGES = ['voice', 'my-work']

const pathFor = (name, studentId) =>
  (name === 'baseline' || name === 'writing-state') && studentId
    ? `/original/${name}.html?student=${encodeURIComponent(studentId)}`
    : `/original/${name}.html`

async function settle(page) {
  await page.waitForLoadState('networkidle')
  await page.waitForFunction(() => document.getAnimations()
    .filter((a) => a.effect?.getComputedTiming?.().iterations !== Infinity)
    .every((a) => a.playState === 'finished'))
}

// Serious and critical violations, one line per node, so a failure names the element.
async function axeProblems(page, label) {
  await settle(page)
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    // Decorative canvases only (see the header).
    .exclude('canvas')
    .analyze()
  const lines = []
  for (const v of results.violations) {
    if (v.impact !== 'serious' && v.impact !== 'critical') continue
    for (const n of v.nodes) {
      lines.push(`${label} · ${v.id} (${v.impact}) · ${n.target.join(' ')} · ` +
        String(n.failureSummary || '').replace(/\s+/g, ' ').slice(0, 200))
    }
  }
  return lines
}

// Every visible control under 44px, as one line each. Runs in the page.
async function smallTargets(page, label) {
  await settle(page)
  const found = await page.evaluate(() => {
    const MIN = 44
    const out = []
    const visible = (el) => {
      if (!el.getClientRects().length) return false
      const cs = getComputedStyle(el)
      if (cs.visibility === 'hidden' || cs.display === 'none' || Number(cs.opacity) === 0) return false
      const r = el.getBoundingClientRect()
      return r.width > 1 && r.height > 1
    }
    // An inline text link inside a sentence: the only exemption (see the header).
    // A link laid out inline, or a button styled as plain words (no padding, no
    // border: Writing State's habit names in its summary sentence), whose
    // parent has text of its own outside it.
    const inlineTextLink = (el) => {
      const cs = getComputedStyle(el)
      const asWords = cs.display === 'inline' ||
        (el.tagName === 'BUTTON' && cs.display === 'inline-block' &&
          parseFloat(cs.paddingTop) === 0 && parseFloat(cs.paddingBottom) === 0 &&
          parseFloat(cs.borderTopWidth) === 0 && parseFloat(cs.borderBottomWidth) === 0)
      if (!asWords || (el.tagName !== 'A' && el.tagName !== 'BUTTON')) return false
      const parent = el.parentElement
      if (!parent) return false
      let own = ''
      for (const node of parent.childNodes) {
        if (node.nodeType === Node.TEXT_NODE) own += node.textContent || ''
      }
      return own.trim().length > 0
    }
    // A stretched link (an ::after laid over its row, e.g. a student's name on
    // Students) is tapped anywhere on that row: measure the row it covers.
    const hitArea = (el) => {
      const after = getComputedStyle(el, '::after')
      if (after.content !== 'none' && after.position === 'absolute') {
        let box = el.parentElement
        while (box && getComputedStyle(box).position === 'static') box = box.parentElement
        if (box) return box.getBoundingClientRect()
      }
      return el.getBoundingClientRect()
    }
    const label = (el) => {
      const id = el.id ? `#${el.id}` : ''
      const cls = typeof el.className === 'string' && el.className.trim() ? `.${el.className.trim().split(/\s+/).join('.')}` : ''
      const txt = (el.textContent || el.value || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 40)
      return `${el.tagName.toLowerCase()}${id}${cls} "${txt}"`
    }
    for (const el of document.querySelectorAll('a, button, [role=button], summary, input, select')) {
      if (!visible(el) || inlineTextLink(el)) continue
      if (el.closest('[aria-hidden="true"], [inert]')) continue
      const r = hitArea(el)
      const iconOnly = !(el.textContent || '').trim() && !!el.querySelector('svg, img')
      const short = r.height < MIN - 0.5
      const narrow = iconOnly && r.width < MIN - 0.5
      if (short || narrow) out.push(`${label(el)} ${Math.round(r.width)}x${Math.round(r.height)}`)
    }
    return out
  })
  return found.map((f) => `${label} · ${f}`)
}

async function openAs(browser, storageState, viewport) {
  const context = await browser.newContext({ storageState, viewport })
  return { context, page: await context.newPage() }
}

async function visit(page, path) {
  await page.goto(path)
  await page.waitForLoadState('networkidle')
}

for (const [size, viewport] of SIZES) {
  test(`teacher pages, empty workspace, ${size}px: no serious or critical axe violation`, async ({ browser, workerTenant }) => {
    test.setTimeout(120_000)
    const { context, page } = await openAs(browser, staffStorageState(workerTenant.baseURL, workerTenant.staff), viewport)
    const problems = []
    for (const name of TEACHER_PAGES) {
      await visit(page, pathFor(name, workerTenant.student.student_id))
      problems.push(...await axeProblems(page, `${name} ${size}`))
    }
    await context.close()
    expect(problems, problems.join('\n')).toEqual([])
  })

  test(`student pages, ${size}px: no serious or critical axe violation`, async ({ browser, workerTenant }) => {
    test.setTimeout(60_000)
    const { context, page } = await openAs(browser, studentStorageState(workerTenant.baseURL, workerTenant.student), viewport)
    const problems = []
    for (const name of STUDENT_PAGES) {
      await visit(page, pathFor(name))
      problems.push(...await axeProblems(page, `${name} ${size}`))
    }
    await context.close()
    expect(problems, problems.join('\n')).toEqual([])
  })
}

isolatedTest('a reading: Writing State before and after, its packet and side-by-side page, at both sizes: no serious or critical axe violation', async ({ browser, request, testTenant }) => {
  isolatedTest.setTimeout(240_000)
  const { staff, student, baseURL } = testTenant
  await seedPastPapers(request, student, testTenant.staff)
  const { context, page } = await openAs(browser, staffStorageState(baseURL, staff), DESKTOP)
  const problems = []
  for (const [size, viewport] of SIZES) {
    await page.setViewportSize(viewport)
    await visit(page, pathFor('writing-state', student.student_id))
    await expect(page.locator('#an-form')).toBeVisible({ timeout: 20_000 })
    problems.push(...await axeProblems(page, `writing-state (form, papers on file) ${size}`))
    await visit(page, pathFor('baseline', student.student_id))
    problems.push(...await axeProblems(page, `baseline (papers on file) ${size}`))
  }
  await page.setViewportSize(DESKTOP)
  await analyse(page, student.student_id)
  for (const [size, viewport] of SIZES) {
    await page.setViewportSize(viewport)
    // Writing State keeps the last reading of this student and shows it again on load.
    await visit(page, pathFor('writing-state', student.student_id))
    await expect(page.locator('#an-done')).toBeVisible({ timeout: 20_000 })
    problems.push(...await axeProblems(page, `writing-state (reading) ${size}`))
    for (const name of ['packet', 'evidence', 'index', 'submissions', 'students']) {
      await visit(page, pathFor(name, student.student_id))
      problems.push(...await axeProblems(page, `${name} (with a reading) ${size}`))
    }
  }
  await context.close()
  expect(problems, problems.join('\n')).toEqual([])
})

isolatedTest('tap targets: every control on every page is at least 44px at 390px', async ({ browser, request, testTenant }) => {
  isolatedTest.setTimeout(240_000)
  const { staff, student, baseURL } = testTenant
  await seedPastPapers(request, student, testTenant.staff)
  const { context, page } = await openAs(browser, staffStorageState(baseURL, staff), PHONE)
  const problems = []
  await visit(page, pathFor('writing-state', student.student_id))
  await expect(page.locator('#an-form')).toBeVisible({ timeout: 20_000 })
  problems.push(...await smallTargets(page, 'writing-state (form)'))
  await analyse(page, student.student_id)
  for (const name of TEACHER_PAGES) {
    await visit(page, pathFor(name, student.student_id))
    problems.push(...await smallTargets(page, name))
  }
  // Writing State's closed sections and a habit's evidence panel hold the
  // tier chips, the heatmap and the evidence tabs.
  await visit(page, pathFor('writing-state', student.student_id))
  await openLookCloser(page)
  await page.locator('#heatmap [data-code]').first().click()
  await expect(page.locator('#hero-evi')).toBeVisible()
  problems.push(...await smallTargets(page, 'writing-state (look closer open, a habit chosen)'))
  // The account menu, open.
  await visit(page, pathFor('index'))
  const avatar = page.locator('.nav-right .avatar').first()
  if (await avatar.isVisible()) {
    await avatar.click()
    problems.push(...await smallTargets(page, 'index (account menu open)'))
  }
  await context.close()

  const s = await openAs(browser, studentStorageState(baseURL, student), PHONE)
  for (const name of STUDENT_PAGES) {
    await visit(s.page, pathFor(name))
    problems.push(...await smallTargets(s.page, name))
  }
  await s.context.close()
  expect(problems, problems.join('\n')).toEqual([])
})

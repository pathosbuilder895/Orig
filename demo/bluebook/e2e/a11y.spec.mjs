/**
 * a11y.spec.mjs — WS-9 Stage 2 breadth
 * (docs/implementation/WS-9-e2e-release-hygiene.md, Stage 2).
 *
 * Axe scan per Bluebook page + a keyboard-walk smoke. Tagged @a11y and
 * NON-BLOCKING for now — per the doc, a page's @a11y case is promoted to
 * blocking only once WS-8 lands that page's React rebuild and it actually
 * passes axe (flipping early red-walls CI on legacy markup WS-4 only
 * hot-fixed). Until then, failures here are signal to read, not a gate.
 *
 * Scope: the Bluebook screens the professor journey touches (Landing, Login,
 * Dashboard, Examinations, Courses, Students, Results, NewExam in both its
 * has-courses and no-courses-yet shapes), the student Briefing screen, and —
 * added with T10 — the Proctor screen in both its idle and code-projected
 * states plus the standalone parked.html a student's phone holds.
 * professor.html/operator.html (legacy, non-Bluebook) are out of scope — WS-8's
 * React migration doesn't cover them, so there's no promotion path to hang a
 * blocking gate on.
 */

import { test as base, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { test as tenancyTest } from './fixtures/tenancy.mjs'
import { createCourse, provisionTenantWithStaff, staffStorageState } from './fixtures/api-setup.mjs'

/**
 * Wait until the screen has stopped moving, so axe measures the UI a person
 * actually reads rather than a frame of it on the way in.
 *
 * Why this exists. Every Bluebook screen is wrapped in a re-keyed fade
 * (app.jsx: `<div key={screen} style={{ animation: 'bbFadeIn 0.65s ease both' }}>`),
 * and three screens fade their own content again on top of it (Courses.jsx:67,
 * Results.jsx:49, Exam.jsx:585). While a fade is in flight the wrapper's
 * opacity is fractional, and axe's colour-contrast check is obliged to honour
 * that: it composites each text colour against what shows through and reports
 * the blend. Scanning mid-fade therefore invented contrast failures on
 * ordinary, passing text and inflated this file's node counts roughly ten-fold
 * — 169 nodes across the file before, 18 after, with no change to the markup
 * (Results 31 → 2, New Examination 39 → 4, Login 12 → 0). Nothing is filtered
 * or suppressed here; the scan is simply taken once the pixels have settled.
 *
 * `document.getAnimations()` asks the question directly — "is anything still
 * animating?" — and covers every fade on the page at once, including the
 * per-card ones this file would otherwise have to enumerate. Two animations in
 * the app are infinite by design (bbPulse on the ACTIVE badge dot,
 * components.jsx:256; `pulse` on parked.html's status dot, parked.html:95).
 * Both are empty decorative dots with no text in or under them, so neither can
 * move a contrast reading — and waiting on `finished` for an animation that
 * never finishes would simply hang. They're skipped by iteration count rather
 * than by name so a third one can't quietly reintroduce the hang.
 *
 * The `networkidle` wait comes first for a related reason: a list fetch landing
 * after the scan would both change what was measured and start a fresh round
 * of card fades behind it.
 */
async function settle(page) {
  await page.waitForLoadState('networkidle')
  await page.waitForFunction(() => document.getAnimations()
    .filter((a) => a.effect?.getComputedTiming?.().iterations !== Infinity)
    .every((a) => a.playState === 'finished'))
}

async function runAxe(page) {
  await settle(page)
  return new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
}

function logViolations(results, label) {
  if (!results.violations.length) return
  console.log(`[@a11y non-blocking] ${label}: ${results.violations.length} violation(s) — ` +
    results.violations.map(v => `${v.id} (${v.nodes.length})`).join(', '))
  // A count alone is not the "signal to read" this file promises — "2 nodes"
  // says nothing about whether they are the known shared chrome or a fresh
  // regression. One line per node, with the selector, so the log answers that.
  for (const v of results.violations) {
    for (const n of v.nodes) {
      console.log(`    ${label} · ${v.id} · ${n.target.join(' ')} · ` +
        String(n.failureSummary || '').replace(/\s+/g, ' ').slice(0, 180))
    }
  }
}

// Screens whose React rebuild (WS-8) has landed and verified passing axe
// with zero violations. A screen's @a11y case is blocking (hard-fails on
// any violation) only once its label is added here -- until then, scans
// only log. Empty until WS-8 R1 lands; add labels one at a time as each
// screen is migrated and confirmed clean, never as a batch.
const MIGRATED_SCREENS = []

function checkA11y(results, label) {
  logViolations(results, label)
  if (MIGRATED_SCREENS.includes(label)) {
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([])
  }
}

base.describe('Axe scan — public screens @a11y', () => {
  base('Landing screen', async ({ page }) => {
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    // React has painted the screen — see the SCREENS comment below on why
    // every scan waits on real markup before `settle()` looks for animations.
    await expect(page.getByRole('button', { name: 'Sign in' }).first()).toBeVisible()
    const results = await runAxe(page)
    checkA11y(results, 'Landing')
  })

  base('Login screen', async ({ page }) => {
    await page.goto('/bluebook/')
    await page.getByRole('button', { name: 'Sign in' }).first().click()
    await expect(page.getByPlaceholder('you@institution.edu')).toBeVisible()
    const results = await runAxe(page)
    checkA11y(results, 'Login')
  })

  base('Briefing screen (student launch)', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('bluebook_student_id', 'demo:e2e-a11y-student')
      window.BB_EXAM_CONFIG = {
        title: 'A11y Scan Exam', course: 'PHIL 301A', courseTitle: 'PHIL 301A',
        candidate: 'A11y Candidate', duration: 60, minWords: 0, maxWords: null,
      }
    })
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Preliminary Instructions')).toBeVisible({ timeout: 10_000 })
    const results = await runAxe(page)
    checkA11y(results, 'Briefing')
  })

  // parked.html — the standalone page a student's phone holds during a sitting
  // (T9). Public and unauthenticated by design: the phone has no login, so it
  // belongs in this describe rather than the tenancy one. Scanned in its
  // name-entry state, which is where every control on the page lives.
  //
  // `?t=a11y` is deliberately a non-token: parked.html only checks that `t` is
  // PRESENT before showing the form (it never validates it until the first
  // beat, which this test never sends), so a real token would buy nothing and
  // would put a high-entropy string in a spec for gitleaks to find. The
  // round-trip against a real token is e2e/proctor.spec.mjs's job.
  base('Parked phone page (parked.html, name entry)', async ({ page }) => {
    await page.goto('/bluebook/parked.html?t=a11y')
    await expect(page.getByRole('heading', { name: 'Park your phone' })).toBeVisible()
    const results = await runAxe(page)
    checkA11y(results, 'Parked phone page')
  })
})

tenancyTest.describe('Axe scan — authenticated professor screens @a11y', () => {
  // `heading` is the screen's own <h1>. It is not decoration: `settle()` can
  // only observe a fade that has been registered on the document timeline, so
  // each scan first waits on markup that only the target screen renders. That
  // also stops a nav click which silently did nothing from producing a green
  // scan of whatever screen was already showing.
  const SCREENS = [
    { label: 'Dashboard', navLabel: 'Overview', heading: /^Good morning,/ },
    { label: 'Examinations', navLabel: 'Examinations', heading: 'Examinations' },
    { label: 'Courses', navLabel: 'Courses', heading: 'Courses' },
    { label: 'Students', navLabel: 'Students', heading: 'Students' },
    { label: 'Results', navLabel: 'Results', heading: 'Results' },
    { label: 'Proctor', navLabel: 'Proctor', heading: 'Phone Park' },
  ]

  for (const { label, navLabel, heading } of SCREENS) {
    tenancyTest(`${label} screen`, async ({ staffPage }) => {
      await staffPage.goto('/bluebook/')
      await staffPage.waitForLoadState('networkidle')
      if (navLabel !== 'Dashboard') {
        await staffPage.getByRole('button', { name: navLabel }).click()
      }
      await expect(staffPage.getByRole('heading', { name: heading })).toBeVisible({ timeout: 10_000 })
      const results = await runAxe(staffPage)
      checkA11y(results, label)
    })
  }

  // The SCREENS entry above scans the Proctor screen idle. Its actual content
  // — the projected QR and the tiles — only exists once a park is open, so it
  // gets its own case for the same reason New Examination does: one extra
  // interaction stands between navigation and the markup worth scanning.
  tenancyTest('Proctor screen (code projected, one tile)', async ({ staffPage, workerTenant, request }) => {
    await staffPage.goto('/bluebook/')
    await staffPage.waitForLoadState('networkidle')
    await staffPage.getByRole('button', { name: 'Proctor' }).click()
    await staffPage.locator('#park-session').fill(`e2e-park-a11y-${workerTenant.tenant.tenant_id}`)
    await staffPage.getByRole('button', { name: 'Start Phone Park' }).click()

    const urlText = staffPage.locator('p', { hasText: /\/bluebook\/parked\.html\?t=/ })
    await expect(urlText).toBeVisible({ timeout: 10_000 })
    // Token read off the page, never a literal — see e2e/proctor.spec.mjs.
    const token = new URL((await urlText.innerText()).trim()).searchParams.get('t')
    await request.post('/proctor/park/beat', {
      data: { park_token: token, student_hint: 'A11y.', state: 'parked' },
    })
    // Tiles poll every 5s (POLL_MS, ProctorTiles.jsx) — wait for the tile
    // rather than scanning an empty grid.
    const tile = staffPage.getByRole('button', { name: /^A11y\. — Parked/ })
    await expect(tile).toBeVisible({ timeout: 15_000 })
    await tile.click()   // expanded timeline is part of the surface
    await expect(staffPage.getByText('Timeline', { exact: true })).toBeVisible()

    const results = await runAxe(staffPage)
    checkA11y(results, 'Proctor (code projected)')
  })

  // New Examination has two shapes, because its Course field is now fed by
  // GET /bluebook/courses (NewExam.jsx) rather than a hardcoded list: a
  // <select> once the professor has courses, and a typed code plus a pointer
  // to the Courses screen when they don't. Both are screens a real professor
  // reaches — the second is what every first-run professor sees — so both are
  // scanned, and each is put in a state it cannot drift out of rather than
  // taking whatever this worker's tenant happens to hold.
  tenancyTest('New Examination screen', async ({ staffPage, workerTenant, request }) => {
    await createCourse(request, workerTenant.staff.token, { code: 'A11Y 100', name: 'A11y Scan Course' })
    await staffPage.goto('/bluebook/')
    await staffPage.waitForLoadState('networkidle')
    await staffPage.getByRole('button', { name: 'Examinations' }).click()
    await expect(staffPage.getByRole('heading', { name: 'Examinations' })).toBeVisible()
    await staffPage.getByRole('button', { name: '+ New Examination' }).click()
    await expect(staffPage.getByRole('heading', { name: 'New Examination' })).toBeVisible()
    // The picker itself, not the empty-state fallback — settle() would
    // otherwise be timing the difference rather than the animation.
    await expect(staffPage.locator('#neCourse')).toHaveJSProperty('tagName', 'SELECT')
    const results = await runAxe(staffPage)
    checkA11y(results, 'New Examination')
  })

  // A tenant of its own, not this worker's: the worker tenant accumulates
  // courses from the tests above and from professor-journey.spec.mjs, so a
  // genuinely empty roster has to be provisioned rather than assumed.
  tenancyTest('New Examination screen (no courses yet)', async ({ browser, baseURL, request }) => {
    const { staff } = await provisionTenantWithStaff(request)
    const context = await browser.newContext({ storageState: staffStorageState(baseURL, staff) })
    const page = await context.newPage()
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: 'Examinations' }).click()
    await expect(page.getByRole('heading', { name: 'Examinations' })).toBeVisible()
    await page.getByRole('button', { name: '+ New Examination' }).click()
    await expect(page.getByRole('heading', { name: 'New Examination' })).toBeVisible()
    await expect(page.getByText('No courses yet')).toBeVisible({ timeout: 10_000 })
    const results = await runAxe(page)
    checkA11y(results, 'New Examination (no courses yet)')
    await context.close()
  })
})

base.describe('Keyboard-walk smoke @a11y', () => {
  base('Landing → Login is reachable and operable by keyboard alone', async ({ page }) => {
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')

    // Walk focus forward and confirm it never gets stuck (each Tab actually
    // moves to a different element) and never silently leaves the document.
    const seen = new Set()
    for (let i = 0; i < 15; i++) {
      await page.keyboard.press('Tab')
      const info = await page.evaluate(() => {
        const el = document.activeElement
        return el ? `${el.tagName}#${el.id}.${el.className}`.slice(0, 80) : null
      })
      expect(info, `Tab ${i + 1} left focus outside the document`).not.toBeNull()
      seen.add(info)
    }
    expect(seen.size, 'Tabbing 15 times never moved focus at all — likely a keyboard trap').toBeGreaterThan(1)

    // The "Sign in" control must itself be keyboard-operable (Enter activates
    // native <button> elements per the HTML spec — this just proves it's a
    // real button and not a div/span pretending to be one).
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    const signIn = page.getByRole('button', { name: 'Sign in' }).first()
    await signIn.focus()
    await page.keyboard.press('Enter')
    await expect(page.getByPlaceholder('you@institution.edu')).toBeVisible({ timeout: 5_000 })
  })
})

/**
 * a11y.spec.mjs — WS-9 Stage 2 breadth
 * (docs/implementation/WS-9-e2e-release-hygiene.md, Stage 2).
 *
 * Axe scan per Bluebook page + a keyboard-walk smoke. Tagged @a11y. Every
 * screen this file scans is now BLOCKING: a wcag2a/wcag2aa violation on any of
 * them fails the run. `MIGRATED_SCREENS` below carries the entry criterion and
 * the evidence; a screen that stops passing comes back out of that list rather
 * than having the check relaxed around it.
 *
 * The scans measure SETTLED UI — see `settle()`. That is not a cosmetic
 * detail: while a screen is still fading in, axe reads every text colour as
 * composited against what shows through, and reports contrast failures that do
 * not exist. That artefact is what kept this whole file non-blocking, and
 * removing it (#105) is most of what made these promotions possible.
 *
 * Scope: the Bluebook screens the professor journey touches (Landing, Login,
 * Dashboard, Examinations, Courses, Students, Results, NewExam in both its
 * has-courses and no-courses-yet shapes), the student Briefing screen, and —
 * added with T10 — the Proctor screen in both its idle and code-projected
 * states plus the standalone parked.html a student's phone holds.
 * professor.html/operator.html (legacy, non-Bluebook) are out of scope — WS-8's
 * React migration doesn't cover them, so there's no promotion path to hang a
 * blocking gate on.
 *
 * Known scope edge, stated rather than left to be discovered: the Results scan
 * measures the collapsed submissions list. Results.jsx's ExpandedRow — and the
 * CorrectionPanel #79 put inside it — only render once a row is expanded, which
 * needs a scored submission this file does not provision (professor-journey.spec.mjs
 * does, at ~90s). So "Results: 0 violations" is a claim about the list, not
 * about the correction UI.
 */

import { test as base, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { test as tenancyTest } from './fixtures/tenancy.mjs'
import { createCourse, createExam, provisionTenantWithStaff, staffStorageState } from './fixtures/api-setup.mjs'

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
  const gate = MIGRATED_SCREENS.includes(label) ? 'BLOCKING' : 'non-blocking'
  console.log(`[@a11y ${gate}] ${label}: ${results.violations.length} violation(s) — ` +
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

/**
 * Every screen label this file scans. Both `MIGRATED_SCREENS` and `checkA11y`
 * are validated against it, so a renamed screen fails loudly instead of
 * silently dropping its blocking gate — `MIGRATED_SCREENS` would name a screen
 * that no longer exists, and this file would refuse to load.
 */
const ALL_SCREENS = [
  'Landing', 'Login', 'Briefing', 'Parked phone page',
  'Dashboard', 'Examinations', 'Courses', 'Students', 'Results',
  'Proctor', 'Proctor (code projected)',
  'New Examination', 'New Examination (no courses yet)',
  'Account',
  // Self-serve screens, each scanned at desktop and at phone width (375px).
  ...['Sign up', 'Forgot password', 'Set password (invite)', 'Course roster',
    'Manage examination', 'Student home', 'Student account', 'Exam with separate answers']
    .flatMap(l => [l, `${l} (375px)`]),
]

/**
 * Screens held to a BLOCKING axe standard: any wcag2a/wcag2aa violation fails
 * the run. Anything not listed here only logs.
 *
 * Every label here was measured at zero violations, settled (see `settle()`),
 * against the committed `bluebook.bundle.js` at this commit. That measurement
 * is the entire entry criterion: a screen is listed because it passes, not
 * because it is expected to. All 30 currently do, so the list is complete —
 * which means the next screen added to this file starts outside the gate and
 * has to earn its way in, exactly as these did.
 *
 * Three notes for whoever reads this next.
 *
 * 1. This list was empty until two things landed. The first was the `settle()`
 *    fix (#105): the scans had been running mid-fade, so every screen "failed"
 *    with 10–40 nodes of contrast findings that were artefacts of the
 *    measurement, not of the markup. Nothing was suppressed to fill this list.
 *    The second was two real markup fixes: the shared sidebar's `Original
 *    Analysis` and `Sign Out` controls (Dashboard.jsx, #105, which blocked all
 *    six professor screens at once), and New Examination's own de-emphasis
 *    (NewExam.jsx — three 3.85:1 FormField hints and one 2.05:1 validation
 *    note, fixed in the commit before this one).
 *
 * 2. This gate's entry criterion is measurement, not the WS-8 handshake WS-9's
 *    plan originally worded it as. That reading was recorded here as a
 *    deliberate deviation when these screens were promoted; it has since been
 *    RATIFIED: ADR-008 (Accepted 2026-08-02) makes Bluebook's esbuild pipeline
 *    the permanent exam-app frontend — there is no future "React rebuild in a
 *    Vite workspace" for these screens to wait on, so measured-green on the
 *    shipped markup is the criterion, full stop. The original concern ("don't
 *    red-wall CI on legacy markup WS-4 only hot-fixed") still governs the
 *    NON-Bluebook statics, which stay out of scope here until WS-8 R3 rebuilds
 *    them in app/.
 *
 * 3. What a green run does and does not certify. It certifies the states this
 *    file actually puts each screen into. Results is scanned as a collapsed
 *    list, so its ExpandedRow and the CorrectionPanel inside it (#79) are not
 *    under this gate — see the file header. A screen with a state worth
 *    gating should get its own labelled case, the way New Examination has two.
 */
const MIGRATED_SCREENS = [
  'Landing',
  'Login',
  'Briefing',
  'Parked phone page',
  'Dashboard',
  'Examinations',
  'Courses',
  'Students',
  'Results',
  'Proctor',
  'Proctor (code projected)',
  'New Examination',
  'New Examination (no courses yet)',
  // Measured at zero violations on 2026-10-01, at desktop and 375px, when the
  // self-serve screens were rebuilt on bluebook-app.css.
  'Account',
  ...['Sign up', 'Forgot password', 'Set password (invite)', 'Course roster',
    'Manage examination', 'Student home', 'Student account', 'Exam with separate answers']
    .flatMap(l => [l, `${l} (375px)`]),
]

for (const label of MIGRATED_SCREENS) {
  if (!ALL_SCREENS.includes(label)) {
    throw new Error(`MIGRATED_SCREENS names a screen this file does not scan: "${label}"`)
  }
}

function checkA11y(results, label) {
  expect(ALL_SCREENS, `checkA11y called with a label ALL_SCREENS does not know: "${label}"`)
    .toContain(label)
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
    await expect(page.getByPlaceholder('you@school.edu')).toBeVisible()
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
    { label: 'Dashboard', navLabel: 'Overview', heading: /^(Welcome back|Begin with the writing)/ },
    { label: 'Examinations', navLabel: 'Examinations', heading: 'Examinations' },
    { label: 'Courses', navLabel: 'Courses', heading: 'Courses' },
    { label: 'Students', navLabel: 'Students', heading: 'Students' },
    { label: 'Results', navLabel: 'Submissions', heading: 'Results' },
    { label: 'Proctor', navLabel: 'Proctor', heading: 'Live examination' },
    { label: 'Account', navLabel: 'Account', heading: 'Your account' },
  ]

  for (const { label, navLabel, heading } of SCREENS) {
    tenancyTest(`${label} screen`, async ({ staffPage }) => {
      await staffPage.goto('/bluebook/')
      await staffPage.waitForLoadState('networkidle')
      if (navLabel !== 'Dashboard') {
        await staffPage.getByRole('button', { name: navLabel, exact: true }).click()
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
    await staffPage.getByRole('button', { name: 'Proctor', exact: true }).click()
    await staffPage.getByRole('tab', { name: 'Phone park' }).click()
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
    await staffPage.getByRole('button', { name: 'Examinations', exact: true }).click()
    await expect(staffPage.getByRole('heading', { name: 'Examinations' })).toBeVisible()
    await staffPage.getByRole('button', { name: '+ New examination' }).click()
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
    await page.getByRole('button', { name: 'Examinations', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Examinations' })).toBeVisible()
    await page.getByRole('button', { name: '+ New examination' }).click()
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
    await expect(page.getByPlaceholder('you@school.edu')).toBeVisible({ timeout: 5_000 })
  })
})


// ── Self-serve screens (round 2, 2026-10) ────────────────────────────────────
// Every screen the public self-serve journey adds, scanned at desktop width and
// again at 375px, because the same markup reflows into cards on a phone and a
// contrast or target problem can exist in only one of the two layouts.

function studentAccountState(baseURL, s) {
  return {
    cookies: [],
    origins: [{
      origin: baseURL,
      localStorage: [
        { name: 'original_session_token', value: s.token },
        { name: 'original_student_id', value: s.student_id },
        { name: 'original_role', value: 'student' },
        { name: 'original_tenant', value: s.tenant_id },
        { name: 'original_name', value: s.name || 'E2E Student' },
        { name: 'original_email', value: s.email || '' },
        { name: 'original_products', value: JSON.stringify(s.products || ['original', 'bluebook']) },
      ],
    }],
  }
}

for (const viewport of [null, { width: 375, height: 812 }]) {
  const tag = viewport ? ' (375px)' : ''

  base.describe(`Axe scan — public self-serve screens${tag} @a11y`, () => {
    if (viewport) base.use({ viewport })
    for (const { label, path, ready } of [
      { label: 'Sign up', path: '/bluebook/', ready: async p => { await p.getByRole('button', { name: 'Create a free workspace' }).first().click(); await expect(p.getByLabel('Your name')).toBeVisible() } },
      { label: 'Forgot password', path: '/bluebook/', ready: async p => { await p.getByRole('button', { name: 'Sign in' }).first().click(); await p.getByRole('button', { name: 'Forgot your password?' }).click(); await expect(p.getByLabel('Email')).toBeVisible() } },
      { label: 'Set password (invite)', path: '/bluebook/?invite=a11y-not-a-real-token', ready: async p => { await expect(p.getByLabel('New password')).toBeVisible() } },
    ]) {
      base(`${label}${tag}`, async ({ page }) => {
        await page.goto(path)
        await page.waitForLoadState('networkidle')
        await ready(page)
        checkA11y(await runAxe(page), label + tag)
      })
    }
  })

  tenancyTest.describe(`Axe scan — self-serve teacher and student screens${tag} @a11y`, () => {
    if (viewport) tenancyTest.use({ viewport })

    tenancyTest(`Course roster${tag}`, async ({ staffPage, request, workerTenant }) => {
      const course = await createCourse(request, workerTenant.staff.token, { name: `A11y Roster ${Date.now()}` })
      await request.post(`/bluebook/courses/${course.id}/students`, {
        headers: { Authorization: `Bearer ${workerTenant.staff.token}` },
        data: { students: [{ email: `a11y-${Date.now()}@e2e.test`, name: 'A11y Student' }] },
      })
      await staffPage.goto('/bluebook/')
      await staffPage.waitForLoadState('networkidle')
      await staffPage.getByRole('button', { name: 'Courses', exact: true }).click()
      await staffPage.getByRole('button', { name: course.name }).first().click()
      await expect(staffPage.getByRole('heading', { name: course.name })).toBeVisible({ timeout: 10_000 })
      checkA11y(await runAxe(staffPage), 'Course roster' + tag)
    })

    tenancyTest(`Manage examination${tag}`, async ({ staffPage, request, workerTenant }) => {
      const exam = await createExam(request, workerTenant.staff.token, { title: `A11y Manage ${Date.now()}` })
      await staffPage.goto('/bluebook/')
      await staffPage.waitForLoadState('networkidle')
      await staffPage.getByRole('button', { name: 'Examinations', exact: true }).click()
      await staffPage.getByRole('button', { name: exam.title }).click()
      await expect(staffPage.getByRole('button', { name: 'Save changes' })).toBeVisible({ timeout: 10_000 })
      checkA11y(await runAxe(staffPage), 'Manage examination' + tag)
    })

    tenancyTest(`Student home, submission and account${tag}`, async ({ browser, baseURL, workerTenant }) => {
      const context = await browser.newContext({
        storageState: studentAccountState(baseURL, workerTenant.student),
        ...(viewport ? { viewport } : {}),
      })
      const page = await context.newPage()
      await page.goto('/bluebook/')
      await page.waitForLoadState('networkidle')
      await expect(page.getByRole('heading', { name: /^Welcome,/ })).toBeVisible({ timeout: 10_000 })
      checkA11y(await runAxe(page), 'Student home' + tag)
      await page.getByRole('button', { name: 'Account' }).click()
      await expect(page.getByLabel('Current password')).toBeVisible()
      checkA11y(await runAxe(page), 'Student account' + tag)
      await context.close()
    })

    tenancyTest(`Exam with separate answers${tag}`, async ({ browser, baseURL, request, workerTenant }) => {
      const res = await request.post('/bluebook/exams', {
        headers: { Authorization: `Bearer ${workerTenant.staff.token}` },
        data: { title: `A11y Questions ${Date.now()}`, status: 'ACTIVE', duration: 30, questions: ['First question?', 'Second question?'] },
      })
      const exam = await res.json()
      const context = await browser.newContext({
        storageState: studentAccountState(baseURL, workerTenant.student),
        ...(viewport ? { viewport } : {}),
      })
      const page = await context.newPage()
      await page.addInitScript(() => { Element.prototype.requestFullscreen = function () { return Promise.resolve() } })
      await page.goto('/bluebook/')
      await page.waitForLoadState('networkidle')
      await page.getByRole('row', { name: new RegExp(exam.title) }).getByRole('button', { name: /Open|Resume/ }).click()
      await page.getByRole('button', { name: /Begin Examination/ }).click()
      await expect(page.getByLabel('Your answer to question 1')).toBeVisible({ timeout: 10_000 })
      checkA11y(await runAxe(page), 'Exam with separate answers' + tag)
      await context.close()
    })
  })
}

/**
 * auth.spec.mjs — WS-9 Stage 2 breadth
 * (docs/implementation/WS-9-e2e-release-hygiene.md, Stage 2).
 *
 * Staff login/logout through the Bluebook LoginScreen (Landing.jsx), the
 * throttle-lockout message, bad-credential errors, and the routing
 * consequence of a student arriving via a bound launch (the mechanism a
 * magic link / LTI launch delivers).
 *
 * IMPORTANT — WS-4 gap found while writing this spec: the doc's Stage 2
 * bullet for this file assumes the login error is announced via
 * role="alert" ("pairs with WS-4 W4 role=alert"). It is NOT — Landing.jsx's
 * LoginScreen error is a plain `<p>{error}</p>` with no id on either input
 * and no role="alert" on the error text (verified against the current
 * committed file, not a stale read). Selectors below use placeholder text
 * and the error's literal copy instead of id/role. Flag this to whoever
 * owns WS-4 — the pairing this doc describes hasn't landed.
 *
 * Scope note on "student magic-link": there is no student-facing magic-link
 * *login form* inside the Bluebook React app itself (demo/student.html has
 * the passwordless /student-auth/login flow; /lti/launch is a server-side
 * OIDC redirect). Both are already covered by pytest (tests/test_lti.py
 * signs a real RSA id_token; see the lti.spec decision-gate note in this
 * directory). What we test here is the one thing pytest can't: that once a
 * student identity IS bound (the actual effect any of those paths produce —
 * localStorage.bluebook_student_id set), app.jsx's routing takes them
 * straight to the exam briefing rather than the login/landing screen.
 */

import { test, expect } from '@playwright/test'
import { provisionTenantWithStaff } from './fixtures/api-setup.mjs'

async function fillLogin(page, email, password) {
  await page.getByPlaceholder('you@institution.edu').fill(email)
  await page.getByPlaceholder('••••••••••').fill(password)
}

test.describe('Staff login / logout @smoke', () => {
  test('valid credentials sign in and land on the dashboard', async ({ page, request }) => {
    const { staff } = await provisionTenantWithStaff(request)
    await page.goto('/bluebook/')
    await page.getByRole('button', { name: 'Sign in' }).first().click()
    await fillLogin(page, staff.email, staff.password)
    await page.getByRole('button', { name: 'Enter' }).click()
    await expect(page.getByRole('button', { name: 'Overview' })).toBeVisible({ timeout: 10_000 })
  })

  test('bad credentials show the exact server error', async ({ page, request }) => {
    const { staff } = await provisionTenantWithStaff(request)
    await page.goto('/bluebook/')
    await page.getByRole('button', { name: 'Sign in' }).first().click()
    await fillLogin(page, staff.email, 'definitely-the-wrong-password')
    await page.getByRole('button', { name: 'Enter' }).click()
    await expect(page.getByText('Invalid email or password')).toBeVisible({ timeout: 10_000 })
  })

  test('signed-in staff can sign out back to landing', async ({ page, request }) => {
    const { staff } = await provisionTenantWithStaff(request)
    await page.goto('/bluebook/')
    await page.getByRole('button', { name: 'Sign in' }).first().click()
    await fillLogin(page, staff.email, staff.password)
    await page.getByRole('button', { name: 'Enter' }).click()
    await expect(page.getByRole('button', { name: 'Overview' })).toBeVisible({ timeout: 10_000 })

    await page.getByRole('button', { name: 'Sign Out' }).click()
    await expect(page.getByText('Academic integrity,')).toBeVisible({ timeout: 10_000 })
    expect(await page.evaluate(() => localStorage.getItem('original_principal_token'))).toBeNull()
  })
})

test.describe('Bound student launch (magic-link / LTI launch consequence)', () => {
  test('a bound student id routes straight to the exam briefing, not login', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('bluebook_student_id', 'demo:e2e-auth-spec-bound-student')
      window.BB_EXAM_CONFIG = {
        title: 'Auth Spec Bound Launch', course: 'PHIL 301A', courseTitle: 'PHIL 301A',
        candidate: 'Bound Candidate', duration: 60, minWords: 0, maxWords: null,
      }
    })
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    // BriefingScreen renders the exam title + "Preliminary Instructions" —
    // never the sign-in form — confirming isStudentLaunch() short-circuited
    // routing straight past login/landing (app.jsx: BB_API.isStudentLaunch()).
    await expect(page.getByText('Preliminary Instructions')).toBeVisible({ timeout: 10_000 })
    await expect(page.getByPlaceholder('you@institution.edu')).toHaveCount(0)
  })

  // The identity a launch binds must also be the identity the sitting SHOWS.
  // GET /bluebook/launch stores the canonical Original student id, but the
  // links roster_links.py hands out are name-free by default (FERPA), so the
  // screens used to keep displaying the demo's stock "Candidate No. 00042"
  // over a correctly bound sitting (wire proof 2026-08-13, observation 2).
  // Name-free binding must surface the opaque short id instead.
  const BOUND_SID = 'demo:ab12cd34ef567890'
  const BOUND_SHORT = 'Candidate ab12cd34'
  const STOCK_CANDIDATE = 'Candidate No. 00042'

  test('a name-free bound launch shows the short bound id, not the stock number',
    async ({ page }) => {
      await page.addInitScript((sid) => {
        localStorage.setItem('bluebook_student_id', sid)
        // No `candidate` key: exactly what a name-free launch leaves behind,
        // since /bluebook/launch only appends ?candidate= when the operator
        // opted into --include-name.
        window.BB_EXAM_CONFIG = {
          title: 'Name-free Bound Launch', course: 'PHIL 301A', courseTitle: 'PHIL 301A',
          duration: 60, minWords: 0, maxWords: null,
        }
      }, BOUND_SID)
      await page.goto('/bluebook/')
      await page.waitForLoadState('networkidle')

      // Instructions screen (BriefingScreen) — the Candidate meta row.
      await expect(page.getByText(BOUND_SHORT)).toBeVisible({ timeout: 10_000 })
      await expect(page.getByText(STOCK_CANDIDATE)).toHaveCount(0)

      // Exam room masthead (ExamScreen) — same identity, right of the title.
      await page.locator('button', { hasText: /begin/i }).first().click()
      await expect(page.locator('textarea[placeholder="Begin writing here…"]'))
        .toBeVisible({ timeout: 10_000 })
      await expect(page.getByText(BOUND_SHORT)).toBeVisible()
      await expect(page.getByText(STOCK_CANDIDATE)).toHaveCount(0)
    })

  test('a launch that carried a name (--include-name) shows the name', async ({ page }) => {
    await page.addInitScript((sid) => {
      localStorage.setItem('bluebook_student_id', sid)
      // index.html's bootstrap copies ?candidate= into cfg.candidate.
      window.BB_EXAM_CONFIG = {
        title: 'Named Bound Launch', course: 'PHIL 301A', courseTitle: 'PHIL 301A',
        candidate: 'Jane Doe', duration: 60, minWords: 0, maxWords: null,
      }
    }, BOUND_SID)
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Jane Doe')).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText(BOUND_SHORT)).toHaveCount(0)
    await expect(page.getByText(STOCK_CANDIDATE)).toHaveCount(0)
  })
})

// Runs in true isolation: exhausts the server's IP-keyed login throttle
// (_LOGIN_MAX_ATTEMPTS=10 per 300s, original/api.py) for 5 minutes — every
// other spec's staff login would 429 if this ran concurrently with them.
// Tag @serial-lockout and invoke separately, e.g.:
//   npx playwright test --workers=1 -g "throttle lockout"
// Do NOT fold this into the default parallel run.
test.describe('Login throttle lockout @serial-lockout', () => {
  test('throttle lockout after repeated bad attempts shows the server message', async ({
    page, request,
  }) => {
    const { staff } = await provisionTenantWithStaff(request)
    await page.goto('/bluebook/')
    await page.getByRole('button', { name: 'Sign in' }).first().click()
    await page.getByPlaceholder('you@institution.edu').fill(staff.email)

    // _LOGIN_MAX_ATTEMPTS = 10 (original/api.py) — drive it past the limit.
    for (let i = 0; i < 11; i++) {
      await page.getByPlaceholder('••••••••••').fill(`still-wrong-${i}`)
      await page.getByRole('button', { name: /^Enter$|^Verifying…$/ }).click()
      await page.waitForTimeout(200)
    }
    await expect(page.getByText('Too many sign-in attempts. Try again in a few minutes.'))
      .toBeVisible({ timeout: 10_000 })
  })
})

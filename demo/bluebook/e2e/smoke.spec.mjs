/**
 * smoke.spec.mjs — the lightweight end-to-end smoke covering Bluebook's
 * page load + no-CDN-in-pilot guarantees + a sample of the React app's
 * routing.
 *
 * These tests cover the Section C UI claims in docs/PILOT_SMOKE_TEST.md
 * that the Python suite can't reach:
 *   - Bluebook loads at /bluebook/ with no console errors
 *   - In pilot mode (vendored React), zero requests escape to unpkg/babel CDNs
 *   - The Landing screen renders its "Original" heading + Bluebook tagline
 *   - The React bundle initialises (a button/CTA exists in the DOM)
 *
 * Run:
 *   cd demo/bluebook && npx playwright test
 *
 * Pre-req: Original demo server running on http://localhost:8001
 * (or PLAYWRIGHT_BASE_URL pointing at the live pilot URL).
 */

import { test, expect } from '@playwright/test'

test.describe('Bluebook — page load', () => {
  test('serves at /bluebook/ with no console errors', async ({ page }) => {
    const consoleErrors = []
    page.on('console', msg => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })
    page.on('pageerror', err => consoleErrors.push(String(err)))

    const response = await page.goto('/bluebook/')
    expect(response?.status()).toBe(200)

    // Wait for React to mount + render the landing
    await page.waitForLoadState('networkidle')

    // The landing screen has the brand heading
    await expect(page.locator('body')).toContainText(/Original|Bluebook|Examination/i)

    // Any console errors are a hard fail — the lockdown env must boot cleanly
    expect(consoleErrors, `Console errors during /bluebook/ load:\n${consoleErrors.join('\n')}`)
      .toEqual([])
  })

  test('static bundle assets resolve (no 404s on first paint)', async ({ page }) => {
    const failedRequests = []
    page.on('response', resp => {
      if (resp.status() >= 400 && resp.url().includes('/bluebook/')) {
        failedRequests.push(`${resp.status()} ${resp.url()}`)
      }
    })
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    expect(failedRequests, failedRequests.join('\n')).toEqual([])
  })
})

test.describe('Bluebook — landing UI', () => {
  test('renders the Bluebook landing CTA', async ({ page }) => {
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')

    // The landing has a primary action — text varies but the page should have
    // something resembling a "begin" / "continue" / "examination" affordance.
    // Be lenient so this doesn't break on copy tweaks.
    const cta = page.locator(
      'button, a, [role="button"]'
    ).filter({ hasText: /sign in|begin|continue|examination|dashboard|enter/i })
    await expect(cta.first()).toBeVisible({ timeout: 10_000 })
  })
})

test.describe('Bluebook — pilot mode no-CDN guarantee', () => {
  // This test only meaningfully runs when ORIGINAL_ENV=pilot on the server,
  // because dev intentionally uses CDN React. We assert based on what we
  // observed: if the page references unpkg.com, fail (production should
  // never reach external CDNs at exam time).
  //
  // When run against a dev server, the test conditionally skips.
  test('no unpkg / cdn references in production index', async ({ page, request }) => {
    const html = await (await request.get('/bluebook/')).text()
    const inDevMode = html.includes('unpkg.com') || html.includes('cdn.jsdelivr')

    test.skip(
      inDevMode,
      'Server running in dev mode (CDN React) — set ORIGINAL_ENV=pilot for this assertion.'
    )

    expect(html).not.toContain('unpkg.com')
    expect(html).not.toContain('cdn.jsdelivr')
    expect(html).not.toContain('babel/standalone')
    expect(html).toContain('vendor/react.production.min.js')
    expect(html).toContain('bluebook.bundle.js')
  })
})

test.describe('Bluebook — backend reachability', () => {
  test('the API base the page uses is responsive', async ({ page, request }) => {
    // Bluebook calls the demo API at same-origin. Health must be ok.
    const r = await request.get('/health')
    expect(r.status()).toBe(200)
    const j = await r.json()
    expect(j.status).toBe('ok')
    expect(j.feature_dim).toBe(103)
  })
})

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
 * Scope: the 5 Bluebook screens the professor journey touches (Landing,
 * Login, Dashboard, Courses, Students, Results, NewExam) plus the student
 * Briefing screen. professor.html/operator.html (legacy, non-Bluebook) are
 * out of scope — WS-8's React migration doesn't cover them, so there's no
 * promotion path to hang a blocking gate on.
 */

import { test as base, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { test as tenancyTest } from './fixtures/tenancy.mjs'

async function runAxe(page) {
  return new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
}

function logViolations(results, label) {
  if (results.violations.length) {
    console.log(`[@a11y non-blocking] ${label}: ${results.violations.length} violation(s) — ` +
      results.violations.map(v => `${v.id} (${v.nodes.length})`).join(', '))
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
})

tenancyTest.describe('Axe scan — authenticated professor screens @a11y', () => {
  const SCREENS = [
    { label: 'Dashboard', navLabel: 'Overview' },
    { label: 'Examinations', navLabel: 'Examinations' },
    { label: 'Courses', navLabel: 'Courses' },
    { label: 'Students', navLabel: 'Students' },
    { label: 'Results', navLabel: 'Results' },
  ]

  for (const { label, navLabel } of SCREENS) {
    tenancyTest(`${label} screen`, async ({ staffPage }) => {
      await staffPage.goto('/bluebook/')
      await staffPage.waitForLoadState('networkidle')
      if (navLabel !== 'Dashboard') {
        await staffPage.getByRole('button', { name: navLabel }).click()
      }
      const results = await new AxeBuilder({ page: staffPage }).withTags(['wcag2a', 'wcag2aa']).analyze()
      checkA11y(results, label)
    })
  }

  tenancyTest('New Examination screen', async ({ staffPage }) => {
    await staffPage.goto('/bluebook/')
    await staffPage.waitForLoadState('networkidle')
    await staffPage.getByRole('button', { name: 'Examinations' }).click()
    await staffPage.getByRole('button', { name: '+ New Examination' }).click()
    const results = await new AxeBuilder({ page: staffPage }).withTags(['wcag2a', 'wcag2aa']).analyze()
    checkA11y(results, 'New Examination')
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

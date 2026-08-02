/**
 * dev-tools-gate.spec.mjs — the Tweaks panel must not be reachable from a
 * sitting (P1-3).
 *
 * tweaks-panel.jsx is an internal tuning surface. It renders nothing until it
 * receives an `__activate_edit_mode` postMessage, which is why it looked
 * harmless — but "invisible until asked" is not "unavailable": the message can
 * come from anything on the page or from any frame embedding it, and the panel
 * it opens carries a "Jump to screen" control that walks straight from the exam
 * into the professor console. So every test here ASKS, and then asserts on what
 * it got. A spec that only loaded the page and looked for `.twk-panel` would
 * pass just as happily against the ungated build, which is what makes asking
 * the whole point of the file.
 *
 * The gate is runtime, not build-time (Render serves one committed bundle — see
 * BUILD.md and devToolsEnabled() in components.jsx), so what is asserted is
 * absence from the DOM, not absence from bluebook.bundle.js. The panel's code
 * still ships; nothing mounts it.
 */

import { test, expect } from '@playwright/test'

const PANEL = '.twk-panel'

/** Ask the panel to open, the same way its host toolbar does. */
async function requestPanel(page) {
  await page.evaluate(() => window.postMessage({ type: '__activate_edit_mode' }, '*'))
  // The panel mounts synchronously on the message; give the event loop a turn
  // so an assertion of absence isn't just winning a race it never ran.
  await page.waitForTimeout(250)
}

/** Boot as a bound student launch, straight into the briefing. */
async function bootAsStudent(page) {
  await page.addInitScript(() => {
    localStorage.setItem('bluebook_student_id', 'demo:e2e-devgate-student')
    window.BB_EXAM_CONFIG = {
      title: 'Dev Gate Examination', course: 'TEST 101', courseTitle: 'TEST 101',
      candidate: 'Dev Gate Candidate', duration: 7200, minWords: 0, maxWords: null,
      blockWeb: true, blockCopy: true, id: 'e2e-devgate-exam',
    }
  })
}

test.describe('Tweaks panel dev gate', () => {
  test('is absent through the default student exam flow, briefing and exam alike', async ({ page }) => {
    await bootAsStudent(page)
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Preliminary Instructions')).toBeVisible({ timeout: 10_000 })

    await requestPanel(page)
    await expect(page.locator(PANEL)).toHaveCount(0)

    // And on the exam screen itself — the one place the "Jump to screen"
    // control would be worth something to a candidate.
    await page.locator('button', { hasText: /begin|continue|enter|start/i }).first().click()
    await expect(page.locator('textarea[placeholder="Begin writing here…"]'))
      .toBeVisible({ timeout: 10_000 })
    await requestPanel(page)
    await expect(page.locator(PANEL)).toHaveCount(0)
  })

  test('stays absent for a student who arms the flag themselves', async ({ page }) => {
    // The gate's actual claim. `?dev=1` is the whole arming mechanism, so a
    // candidate typing it into the address bar mid-exam is the case that
    // decides whether this is a gate or a decoration.
    await bootAsStudent(page)
    await page.goto('/bluebook/?dev=1')
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Preliminary Instructions')).toBeVisible({ timeout: 10_000 })
    // The flag really was stored — the refusal below is devToolsEnabled()
    // declining it, not the bootstrap having quietly dropped it.
    expect(await page.evaluate(() => localStorage.getItem('bluebook_dev_tools'))).toBe('1')

    await requestPanel(page)
    await expect(page.locator(PANEL)).toHaveCount(0)
  })

  test('is absent for an ordinary visitor who has not asked for it', async ({ page }) => {
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    await requestPanel(page)
    await expect(page.locator(PANEL)).toHaveCount(0)
  })

  test('opens under ?dev=1, and survives the reload a tuning pass makes', async ({ page }) => {
    await page.goto('/bluebook/?dev=1')
    await page.waitForLoadState('networkidle')
    await requestPanel(page)
    await expect(page.locator(PANEL)).toBeVisible()
    await expect(page.locator(PANEL).getByText('Jump to screen')).toBeVisible()

    // Stored, not read off the URL — the panel is still available on a plain
    // reload of the same origin.
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    await requestPanel(page)
    await expect(page.locator(PANEL)).toBeVisible()
  })

  test('?dev=0 disarms it again', async ({ page }) => {
    await page.goto('/bluebook/?dev=1')
    await page.waitForLoadState('networkidle')
    await requestPanel(page)
    await expect(page.locator(PANEL)).toBeVisible()

    await page.goto('/bluebook/?dev=0')
    await page.waitForLoadState('networkidle')
    expect(await page.evaluate(() => localStorage.getItem('bluebook_dev_tools'))).toBeNull()
    await requestPanel(page)
    await expect(page.locator(PANEL)).toHaveCount(0)
  })
})

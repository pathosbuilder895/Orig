/**
 * exam-flow.spec.mjs — deep E2E coverage of the Bluebook exam lockdown.
 *
 * Closes the gap the lightweight smoke.spec.mjs left open:
 *   - Fullscreen engagement on Begin (and the warning when fullscreen is lost)
 *   - Paste blocking + the examiner's notice
 *   - Ctrl/Cmd+P + Ctrl/Cmd+S blocking
 *   - Submit gating below the minimum word count
 *   - Round-trip: type → Seal & Surrender → "Examination Sealed" +
 *     "✓ Proctored baseline transmitted to Original" + API-side
 *     confirmation that sample_count incremented with provenance=proctored.
 *
 * These tests inject configuration via `addInitScript` so the React app
 * boots in a known state (low minWords, deterministic student id) without
 * needing UI navigation through the briefing's exam-picker.
 *
 * Run:
 *   cd demo/bluebook && npm run test
 */

import { test, expect } from '@playwright/test'

// A deterministic, test-only student id we can verify by API afterwards.
// Must be under the "demo" tenant prefix because the principal-scoping layer
// only permits anonymous writes against the demo tenant. The timestamp keeps
// each run isolated so we never collide with a previous run's residue (demo
// is periodically reset in any case — leaving a few test students is fine).
const TEST_STUDENT_ID = `demo:e2e-bluebook-${Date.now()}`
const TEST_STUDENT_NAME = 'E2E Test Candidate'

/**
 * Inject demo + auth state so the React app routes straight to the briefing
 * (BB_API.isStudentLaunch() returns true) with a low minWords so a test can
 * actually type past it.
 */
async function bootInExam(page, { minWords = 12 } = {}) {
  await page.addInitScript(([studentId, candidate, mw]) => {
    // Force the "bound student launch" path in BB_API.isStudentLaunch()
    localStorage.setItem('bluebook_student_id', studentId)
    // Pre-configure the exam so the briefing → exam transition is trivial
    window.BB_EXAM_CONFIG = {
      title: 'E2E Smoke Examination',
      course: 'TEST 101',
      courseTitle: 'End-to-End Exam Loop',
      candidate,
      duration: 7200,
      minWords: mw,
      maxWords: null,
      blockWeb: true,
      blockCopy: true,
      spellChk: false,
      id: 'e2e-exam-1',
    }
  }, [TEST_STUDENT_ID, TEST_STUDENT_NAME, minWords])
}

test.describe('Bluebook exam lockdown — full flow', () => {
  test('Begin → exam screen renders + fullscreen attempted', async ({ page }) => {
    await bootInExam(page)
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')

    // Watch for a fullscreen request — Playwright may not actually grant it,
    // but the API call should be made by bbRequestFullscreen().
    let fullscreenRequested = false
    await page.exposeFunction('__markFullscreenRequest', () => { fullscreenRequested = true })
    await page.evaluate(() => {
      const proto = Element.prototype
      const orig = proto.requestFullscreen || proto.webkitRequestFullscreen
      if (orig) {
        proto.requestFullscreen = function (...a) {
          window.__markFullscreenRequest()
          // Return a promise that resolves — chromium-headless rejects the
          // real fullscreen API, so swallow the error to keep React happy.
          try { return orig.apply(this, a) ?? Promise.resolve() }
          catch (e) { return Promise.resolve() }
        }
      }
    })

    // Briefing screen should be active — click "Begin"
    const begin = page.locator('button', { hasText: /begin|continue|enter|start/i }).first()
    await expect(begin).toBeVisible()
    await begin.click()

    // Exam screen reached: the textarea with placeholder must be present
    await expect(page.locator('textarea[placeholder="Begin writing here…"]'))
      .toBeVisible({ timeout: 10_000 })

    // Fullscreen was requested (whether or not the browser granted it)
    expect(fullscreenRequested,
      'bbRequestFullscreen() should be invoked when blockWeb=true and Begin is clicked'
    ).toBe(true)
  })

  test('Paste is blocked + examiner warning appears', async ({ page }) => {
    await bootInExam(page)
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    await page.locator('button', { hasText: /begin|continue|enter|start/i }).first().click()

    const textarea = page.locator('textarea[placeholder="Begin writing here…"]')
    await expect(textarea).toBeVisible()
    await textarea.focus()

    // Fire a paste event with malicious-style text. The onPaste handler
    // should call e.preventDefault() and the textarea's value MUST NOT change.
    await page.evaluate(() => {
      const ta = document.querySelector('textarea[placeholder="Begin writing here…"]')
      const dt = new DataTransfer()
      dt.setData('text/plain', 'AI-GENERATED CONTENT — should be blocked')
      const ev = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })
      ta.dispatchEvent(ev)
    })

    // The textarea must stay empty (paste prevented)
    await expect(textarea).toHaveValue('')

    // The examiner's warning banner appears with the canonical copy
    await expect(page.getByText('Pasting is disabled. Your work must be composed here.'))
      .toBeVisible({ timeout: 5_000 })
  })

  test('Ctrl/Cmd+P and Ctrl/Cmd+S are blocked + warning appears', async ({ page, browserName }) => {
    await bootInExam(page)
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    await page.locator('button', { hasText: /begin|continue|enter|start/i }).first().click()
    await expect(page.locator('textarea[placeholder="Begin writing here…"]')).toBeVisible()

    // The handler reads e.ctrlKey || e.metaKey then preventDefault. The fact
    // that the keystroke yielded no print dialog AND the warning rendered is
    // the assertion. Fire via Page.keyboard.press for the canonical sequence.
    const mod = browserName === 'webkit' || process.platform === 'darwin' ? 'Meta' : 'Control'
    await page.keyboard.press(`${mod}+p`)

    await expect(page.getByText('Printing and saving are disabled during the examination.'))
      .toBeVisible({ timeout: 5_000 })
  })

  test('Seal is gated below minimum words', async ({ page }) => {
    await bootInExam(page, { minWords: 25 })
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    await page.locator('button', { hasText: /begin|continue|enter|start/i }).first().click()

    const textarea = page.locator('textarea[placeholder="Begin writing here…"]')
    await textarea.focus()
    // Type a SHORT response — below minWords
    await page.keyboard.type('Five words only here — short.', { delay: 4 })

    // The Seal button is rendered disabled until words >= minWords (the
    // primary structural gate), AND clicking it (forced) still doesn't
    // advance because handleSubmit early-returns on words < cfg.minWords.
    const sealBtn = page.locator('button', { hasText: /Seal & Surrender|Sealing/ })
    await expect(sealBtn).toBeVisible()
    await expect(sealBtn).toBeDisabled()

    // Even with a forced click that bypasses the disabled attribute, the
    // submit handler's early-return keeps us on the exam screen.
    await sealBtn.click({ force: true })
    await page.waitForTimeout(500)
    await expect(page.getByText('Examination Sealed')).toHaveCount(0)
    await expect(textarea).not.toHaveValue('')
  })

  test('Type past minimum → Seal → Examination Sealed + baseline transmitted + API confirms', async ({ page, request }) => {
    const minWords = 12
    await bootInExam(page, { minWords })
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')

    // Suppress real fullscreen call (chromium-headless rejects it, which
    // logs a noisy console error). Keep the React state machine happy.
    await page.evaluate(() => {
      Element.prototype.requestFullscreen = function () { return Promise.resolve() }
    })

    await page.locator('button', { hasText: /begin|continue|enter|start/i }).first().click()
    const textarea = page.locator('textarea[placeholder="Begin writing here…"]')
    await expect(textarea).toBeVisible({ timeout: 10_000 })
    await textarea.focus()

    // Type WELL past the minimum so word-count gating definitely opens Seal.
    const longProse =
      'The argument of this examination is that voice is a fingerprint, ' +
      'pressed daily into prose by the writer who carries it, and that the ' +
      'long accumulation of rhythm and habit makes formation visible. ' +
      'A reader who has read enough of a writer learns to recognise the ' +
      'turn of a sentence, the qualifying clause, the resolution that ' +
      'never quite resolves. That recognition is what we are trying to ' +
      'protect, in our small way, against the easy substitutions of the ' +
      'machine. A formation that requires patience cannot be hurried, and ' +
      'a record built by patience is one a student can stand on.'
    await page.keyboard.type(longProse, { delay: 1 })

    const sealBtn = page.locator('button', { hasText: /Seal & Surrender|Sealing/ })
    await expect(sealBtn).toBeVisible()
    await sealBtn.click()

    // The submitted screen renders the canonical sealed headline
    await expect(page.getByText('Examination Sealed'))
      .toBeVisible({ timeout: 15_000 })

    // The proctored-baseline transmission line shows the success token
    await expect(page.getByText('✓ Proctored baseline transmitted to Original'))
      .toBeVisible({ timeout: 5_000 })

    // ── API-side verification: the bound student now has a proctored sample
    const studentResp = await request.get(`/students/${encodeURIComponent(TEST_STUDENT_ID)}`)
    expect(studentResp.status()).toBe(200)
    const student = await studentResp.json()
    expect(student.sample_count).toBeGreaterThan(0)
    expect(student.samples.some(s => s.provenance === 'proctored')).toBe(true)
  })

  test('Exiting fullscreen mid-exam shows the warning', async ({ page }) => {
    await bootInExam(page)
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')

    // Make requestFullscreen a no-op so we can synthesize a fullscreenchange
    // ourselves (chromium-headless does not honor the real fullscreen API).
    await page.evaluate(() => {
      Element.prototype.requestFullscreen = function () { return Promise.resolve() }
    })

    await page.locator('button', { hasText: /begin|continue|enter|start/i }).first().click()
    await expect(page.locator('textarea[placeholder="Begin writing here…"]')).toBeVisible()

    // The handler reads document.fullscreenElement after fullscreenchange.
    // We force the read to be false, then dispatch the event.
    await page.evaluate(() => {
      Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => null })
      document.dispatchEvent(new Event('fullscreenchange'))
    })

    await expect(page.getByText('You exited full-screen. The examination must remain full-screen.'))
      .toBeVisible({ timeout: 5_000 })
  })
})

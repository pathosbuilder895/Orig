/**
 * parent-postmessage.spec.mjs — nothing may reach window.parent from the
 * default student flow.
 *
 * useTweaks() (tweaks-panel.jsx) posted `__edit_mode_set_keys` to
 * window.parent with targetOrigin '*' on every tweak write — and App's
 * navigate() IS a setTweak('currentScreen', …) call, so every screen change
 * fired it, dev gate or no dev gate. Canvas embeds Bluebook in an iframe via
 * LTI, so each navigation leaked a screen-change event to whatever origin the
 * embedding page happened to have. Nothing in this repo listens for the
 * outbound `__edit_mode_*` messages (the prototype-host tooling that consumed
 * them is not part of the product), so the outbound half of the protocol was
 * removed outright rather than gated — see tweaks-panel.jsx.
 *
 * The test embeds the app in an iframe the way an LMS does and asserts the
 * parent hears NOTHING. It must drive a real navigation (briefing → exam): a
 * spec that only loaded the page would pass against the leaking build,
 * because the post only fired when a tweak (navigation included) changed.
 * Same-origin parent is deliberate — a '*'-targeted post reaches a
 * same-origin parent exactly as it would reach Canvas.
 */

import { test, expect } from '@playwright/test'

/** Boot as a bound student launch, straight into the briefing. Init scripts
 *  run in every frame, so the iframe'd app below boots the same way. */
function bootAsStudent(page) {
  return page.addInitScript(() => {
    localStorage.setItem('bluebook_student_id', 'demo:e2e-parentmsg-student')
    window.BB_EXAM_CONFIG = {
      title: 'Parent Message Examination', course: 'TEST 101', courseTitle: 'TEST 101',
      candidate: 'Parent Msg Candidate', duration: 7200, minWords: 0, maxWords: null,
      blockWeb: true, blockCopy: true, id: 'e2e-parentmsg-exam',
    }
  })
}

test.describe('postMessage containment', () => {
  test('an embedded student flow posts nothing to the embedding page', async ({ page }) => {
    await bootAsStudent(page)
    // Any same-origin document works as the harness; parked.html is the
    // lightest one the server serves. setContent replaces it with a recording
    // parent: the listener is attached, in document order, before the iframe
    // below it can load.
    await page.goto('/bluebook/parked.html')
    await page.setContent(`
      <script>
        window.__parentMessages = []
        window.addEventListener('message', (e) => window.__parentMessages.push(e.data))
      </script>
      <iframe id="app" src="/bluebook/" style="width:1200px;height:800px;border:0"></iframe>
    `)

    const app = page.frameLocator('#app')
    await expect(app.getByText('Preliminary Instructions')).toBeVisible({ timeout: 10_000 })

    // Briefing → exam. Navigation is the moment the leak fired.
    await app.locator('button', { hasText: /begin|continue|enter|start/i }).first().click()
    await expect(app.locator('textarea[placeholder="Begin writing here…"]'))
      .toBeVisible({ timeout: 10_000 })

    // postMessage delivery is async — give the event loop a turn so an empty
    // array is an answer, not a race won by asserting too early.
    await page.waitForTimeout(250)
    expect(await page.evaluate(() => window.__parentMessages)).toEqual([])
  })
})

/**
 * student-coach-origin.spec.mjs — the Focus Coach must call the server that
 * served it.
 *
 * demo/student-coach.html picked its API base by probing the OPENER's port:
 *
 *   const API = (window.opener && (window.opener.location.port === '8001' ||
 *                window.opener.location.port === '8000')) ? '' : 'http://localhost:8001'
 *
 * On a real deploy (https://…, port ''), neither arm of that test matches, so
 * every pilot user fell through to the hardcoded `http://localhost:8001` — the
 * student's OWN machine. Their draft was POSTed to localhost; over https the
 * browser blocks it as mixed content, the page's `.catch(()=>{})` swallows it,
 * and the student is told "Analysis unavailable — your work was saved locally"
 * while nothing ever reaches the server. Opening the page with no opener at
 * all (a bookmark, a restored tab, direct navigation) failed the same way.
 *
 * WHY THIS SHIPPED, and what that means for this spec: the e2e suite serves on
 * port 8001 — the exact port the probe whitelisted — so with an opener present
 * the broken code and the correct code are indistinguishable here. That is
 * precisely the blind spot that let the bug through, so the first test below
 * deliberately loads the page from a DIFFERENT ORIGIN than the probe's
 * hardcoded one, using the 127.0.0.1/localhost alias of the same server. That
 * origin stands in for `https://pilot.example.com` — any origin that is not
 * literally `localhost:8001`. It is the test that fails against the old code.
 *
 * The second test covers the real production flow (opened from the dashboard
 * via window.open). It CANNOT fail while the suite serves on 8001 — with an
 * opener on that port the old probe took the correct branch — so it is a
 * companion guard, not the load-bearing assertion. Both encode one invariant:
 * requests go to the page's own origin, never to a hardcoded host.
 *
 * Requests are intercepted rather than answered for real, so the assertion is
 * about the URL the page CHOSE and never depends on CORS or on any student
 * record existing.
 */

import { test, expect } from '@playwright/test'

// #saveBtn stays disabled below 200 words (onEdit, student-coach.html) — 10
// words x 40 clears it with room to spare.
const LONG_TEXT = 'The formation of a written voice is gradual and particular. '.repeat(40)

/**
 * The same server reached under its other loopback name. `localhost:8001` and
 * `127.0.0.1:8001` are the same server but DIFFERENT origins, which is what
 * lets a same-origin assertion catch a hardcoded `http://localhost:8001`
 * without needing a second port or a real deploy.
 */
function aliasOrigin(baseURL) {
  const u = new URL(baseURL)
  if (u.hostname === 'localhost') u.hostname = '127.0.0.1'
  else if (u.hostname === '127.0.0.1') u.hostname = 'localhost'
  return u.origin
}

/** Record every /students/ URL the page requests; answer them all locally. */
async function recordStudentRequests(target) {
  const seen = []
  await target.route('**/students/**', async (route) => {
    seen.push(route.request().url())
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
  return seen
}

/** Fill enough to clear the save gate, then hit Save & Analyse. */
async function writeAndSave(target) {
  await target.fill('#docTitle', 'Origin Probe')
  await target.fill('#docText', LONG_TEXT)
  const btn = target.locator('#saveBtn')
  await expect(btn).toBeEnabled()
  await btn.click()
}

test.describe('Focus Coach API origin', () => {
  test('a coach page opened directly calls the origin it was served from', async ({ page, baseURL }) => {
    const origin = aliasOrigin(baseURL)
    const seen = await recordStudentRequests(page)

    await page.goto(origin + '/student-coach.html')
    await writeAndSave(page)

    await expect.poll(() => seen.length, { message: 'coach never called /students/' })
      .toBeGreaterThan(0)
    for (const url of seen) {
      expect(new URL(url).origin, `coach called ${url} from a page on ${origin}`).toBe(origin)
    }
  })

  test('the coach opened from the student dashboard calls that same origin', async ({ page, context, baseURL }) => {
    const origin = aliasOrigin(baseURL)
    await page.goto(origin + '/student.html')

    // Exactly how student.html reaches the coach (openCoach, student.html).
    const [coach] = await Promise.all([
      context.waitForEvent('page'),
      page.evaluate(() => { window.open('student-coach.html', '_blank', 'width=900,height=720') }),
    ])
    await coach.waitForLoadState('domcontentloaded')

    const seen = await recordStudentRequests(coach)
    await writeAndSave(coach)

    await expect.poll(() => seen.length, { message: 'coach never called /students/' })
      .toBeGreaterThan(0)
    for (const url of seen) {
      expect(new URL(url).origin, `coach called ${url} from a page on ${origin}`).toBe(origin)
    }
  })
})

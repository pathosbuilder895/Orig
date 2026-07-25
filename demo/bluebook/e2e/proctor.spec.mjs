/**
 * proctor.spec.mjs — the QR phone-park Proctor screen (T10, closing the first
 * of the two gaps flagged when T9 merged: nothing in CI noticed if this screen
 * broke). The axe half of T10 lives in a11y.spec.mjs's SCREENS list.
 *
 * Covers, in one browser, the loop the feature actually is: professor opens a
 * park → a code is projected → a phone beats against that code → a tile
 * appears → the proctor can read its timeline → the professor closes the park
 * and the room's phones are released. Plus parked.html itself, the standalone
 * page the phone holds, driven with a REAL token minted by the professor's own
 * screen in the same test.
 *
 * The close half (tests 7–9) is about one server behaviour: a park that is
 * gone answers 404, on BOTH `DELETE /proctor/park/{id}` and
 * `GET /proctor/park/status`. "Gone" is the outcome the professor asked for,
 * so neither 404 may surface as an error — the three tests pin the button
 * path, the already-deleted race, and the poll loop respectively.
 *
 * Deliberately not covered here:
 *  - The 30s `dropped` transition. It is derived server-side from a clock
 *    (original/routers/proctor.py `park_status`) and is proven there with a
 *    fake clock; the only way to reach it from a browser is a 31s wall-clock
 *    sleep, which is precisely the flake generator this suite avoids.
 *  - Cross-tenant park isolation — endpoint-level, already covered by the T8
 *    backend tests; nothing about it is visible on this screen.
 *
 * Two conventions this file keeps and a reviewer should check:
 *  - Every wait is an auto-waiting `expect`, never a sleep. The tile view
 *    polls every 5s (POLL_MS, ProctorTiles.jsx), so tile assertions carry a
 *    generous timeout rather than a hand-rolled delay.
 *  - The park token is read off the live page, never written into this file.
 *    A literal would be a lie (the server mints a fresh one per session) and
 *    a high-entropy string in a spec is a CI secret-scan hit.
 */

import { test, expect } from './fixtures/tenancy.mjs'

/** The hint one "phone" types on parked.html — initials, which is all this
 *  feature ever stores about a student (see the router's privacy banner). */
const HINT = 'E2E.'

/** A tile's accessible name is `<hint> — <state>, last seen Ns ago. <Show|Hide>
 *  timeline.` (ProctorTiles.jsx Tile). Anchor on the prefix: it carries the
 *  hint AND the state, while the seconds and the show/hide verb both move. */
const PARKED_TILE = /^E2E\. — Parked, last seen \d+s ago\./

/**
 * A park session id unique to this worker's tenant *and* this test, so the
 * file's tests never share park state. Park sessions are keyed on this string
 * globally (`park_get_session_by_exam`) and live 6h, so a fixed id would make
 * one test's phones visible to the next — and to a concurrent worker.
 */
function parkId(workerTenant, suffix) {
  return `e2e-park-${suffix}-${workerTenant.tenant.tenant_id}`
}

/** Matches professor-journey.spec.mjs's openScreen() — sidebar navigation, not a URL. */
async function openProctorScreen(page) {
  await page.getByRole('button', { name: 'Proctor' }).click()
  await expect(page.getByRole('heading', { name: 'Phone Park' })).toBeVisible({ timeout: 10_000 })
}

async function gotoProctorScreen(page) {
  await page.goto('/bluebook/')
  await page.waitForLoadState('networkidle')
  await openProctorScreen(page)
}

/**
 * Open a park from the UI and read back the projected code.
 *
 * Returns the `qr_url` exactly as the professor sees it plus the token parsed
 * out of it — the text fallback under the QR is the only place the token is
 * legible, which is also why it exists (a phone that cannot scan types it in).
 */
async function startPark(page, examSessionId) {
  await page.locator('#park-session').fill(examSessionId)
  await page.getByRole('button', { name: 'Start Phone Park' }).click()
  const urlText = page.locator('p', { hasText: /\/bluebook\/parked\.html\?t=/ })
  await expect(urlText).toBeVisible({ timeout: 10_000 })
  const qrUrl = (await urlText.innerText()).trim()
  return { qrUrl, token: new URL(qrUrl).searchParams.get('t') }
}

/**
 * One heartbeat, exactly as a parked phone sends it: no Authorization header.
 * Beats are anonymous by design — issuing a parked device credentials would
 * create the roster linkage this feature exists without (proctor.py `beat`).
 */
function postBeat(request, token, hint, state = 'parked') {
  return request.post('/proctor/park/beat', {
    data: { park_token: token, student_hint: hint, state },
  })
}

/**
 * Delete a park out of band, as staff — i.e. NOT through the button under
 * test. Used to put the server in the two states the close path has to
 * survive without showing the professor an error: "already deleted" (the
 * button then gets a 404) and "deleted while the tile poll is running".
 *
 * `proctor.py delete_park_session` is `_require_staff` + own-tenant, so this
 * carries the worker's staff bearer token; the plain `request` fixture is
 * anonymous, which is right for `postBeat` above and wrong here.
 */
function deleteParkAsStaff(request, workerTenant, examSessionId) {
  return request.delete(`/proctor/park/${encodeURIComponent(examSessionId)}`, {
    headers: { Authorization: `Bearer ${workerTenant.staff.token}` },
  })
}

/**
 * The idle state the screen must return to after a close: no code, no tiles,
 * no error, and the start control back. Identical to the state test 1 asserts
 * on a screen that was never started — which is the point. Closing a park has
 * to leave the screen honest, not in some third "was running" limbo.
 */
async function expectIdleAndErrorFree(page) {
  await expect(page.getByRole('img', { name: /QR code for the phone park/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Start Phone Park' })).toBeVisible()
  await expect(page.getByText('Not started')).toBeVisible()
  await expect(page.getByText('Start a phone park above to see tiles here.')).toBeVisible()
  // The error paragraph is the only role="alert" on this screen
  // (ProctorScreen), so its absence is the assertion that nothing failed.
  await expect(page.locator('[role="alert"]')).toHaveCount(0)
}

test.describe('Proctor screen — QR phone park', () => {
  // ── 1 ──────────────────────────────────────────────────────────────────
  test('the Proctor screen opens from the sidebar with an idle, honest empty state', async ({
    staffPage,
  }) => {
    await gotoProctorScreen(staffPage)

    // Nothing is running yet: the button is gated on a session id, the tile
    // view says so rather than showing a "Loading…" that would be a lie.
    await expect(staffPage.getByRole('button', { name: 'Start Phone Park' })).toBeDisabled()
    await expect(staffPage.getByRole('heading', { name: 'Parked Phones' })).toBeVisible()
    await expect(staffPage.getByText('Not started')).toBeVisible()
    await expect(staffPage.getByText('Start a phone park above to see tiles here.')).toBeVisible()
    // No park was opened, so no code is projected.
    await expect(staffPage.getByRole('img', { name: /QR code for the phone park/ })).toHaveCount(0)

    // ── The framing this feature lives or dies on ──────────────────────────
    // "Deterrence and signal, never proof" (proctor.py's module docstring,
    // docs/PROCTOR_SCRIPT.md). The screen must never claim it prevents phone
    // use or verifies anybody, so the claim vocabulary is pinned as absent.
    const copy = await staffPage.locator('body').innerText()
    expect(copy, 'the Proctor screen must not claim it secures anything').not.toMatch(/\bsecur\w*/i)
    expect(copy, 'the Proctor screen must not claim it verifies anybody').not.toMatch(/\bverif\w*/i)
    // "locked" is the third claim word T9's review asked about, and it IS on
    // this screen — once, inside "a locked screen", listed as an innocent
    // reason a phone goes quiet. Asserting its literal absence would delete a
    // sentence that exists to stop proctors over-reading a tile, so pin the
    // shape instead: any OTHER lock word ("lockdown", "locked down", "locks
    // the phone") changes this array and fails the test.
    expect(copy.match(/\block\w*/gi), 'the only lock-word allowed here is "a locked screen"')
      .toEqual(['locked'])
    expect(copy).toContain('a locked screen')

    // And the disclaimers themselves are present, not merely un-contradicted.
    await expect(staffPage.getByText('Deterrence and signal — never proof')).toBeVisible()
    await expect(staffPage.getByText(/This cannot stop anyone using a phone/)).toBeVisible()
    await expect(staffPage.getByText(/never as a finding/)).toBeVisible()
  })

  // ── 2 ──────────────────────────────────────────────────────────────────
  test('starting a park projects a QR code with a legible text fallback', async ({
    staffPage, workerTenant,
  }) => {
    await gotoProctorScreen(staffPage)
    const { qrUrl, token } = await startPark(staffPage, parkId(workerTenant, 'qr'))

    // Encoded in-process (vendor/qr.js), so it is a real inline SVG on the
    // page rather than a CDN image — an offline exam room still gets a code.
    await expect(staffPage.getByRole('img', { name: /QR code for the phone park page/ }))
      .toBeVisible()
    await expect(staffPage.getByText('Scan to park a phone')).toBeVisible()

    expect(qrUrl).toContain('/bluebook/parked.html?t=')
    expect(token, 'the projected URL must carry a park token').toBeTruthy()
    await expect(staffPage.getByText('A phone that cannot scan can type this in instead.'))
      .toBeVisible()

    // Started, but nothing has scanned it yet — a distinct empty state from
    // the "Not started" one above.
    await expect(staffPage.getByText('No phones parked yet — students scan the code to appear here.'))
      .toBeVisible({ timeout: 15_000 })
  })

  // ── 3 ──────────────────────────────────────────────────────────────────
  test('a beat against the projected token raises a parked tile', async ({
    staffPage, workerTenant, request,
  }) => {
    await gotoProctorScreen(staffPage)
    const { token } = await startPark(staffPage, parkId(workerTenant, 'tile'))

    const beat = await postBeat(request, token, HINT)
    expect(beat.status(), await beat.text()).toBe(200)

    // The view polls every 5s; auto-waiting expectation, generous timeout.
    await expect(staffPage.getByRole('button', { name: PARKED_TILE })).toBeVisible({ timeout: 15_000 })
    await expect(staffPage.getByText('1 phone', { exact: true })).toBeVisible()
    await expect(staffPage.getByText(HINT, { exact: true })).toBeVisible()
  })

  // ── 4 ──────────────────────────────────────────────────────────────────
  // T7's role="button" pattern (components.jsx rowKeyDown): a click-only div
  // is not an affordance. Asserted by keyboard alone — this test never clicks
  // the tile.
  test('a tile expands its timeline from the keyboard alone', async ({
    staffPage, workerTenant, request,
  }) => {
    await gotoProctorScreen(staffPage)
    const { token } = await startPark(staffPage, parkId(workerTenant, 'kbd'))
    const beat = await postBeat(request, token, HINT)
    expect(beat.status(), await beat.text()).toBe(200)

    const tile = staffPage.getByRole('button', { name: PARKED_TILE })
    await expect(tile).toBeVisible({ timeout: 15_000 })
    await expect(tile).toHaveAttribute('aria-expanded', 'false')

    await tile.focus()
    await staffPage.keyboard.press('Enter')

    await expect(tile).toHaveAttribute('aria-expanded', 'true')
    await expect(staffPage.getByText('Timeline', { exact: true })).toBeVisible()
    // The first beat is itself the first recorded transition (store.park_beat
    // seeds transitions_json on insert), so the timeline is never empty here.
    await expect(staffPage.getByText('No changes recorded yet.')).toHaveCount(0)
    await expect(staffPage.getByText('Phone present and idle.')).toBeVisible()
  })

  // ── 5 ──────────────────────────────────────────────────────────────────
  // The guarantee that keeps a mid-exam reload from stranding every phone
  // already parked on the old code (proctor.py `open_park_session`: re-opening
  // a live session hands back the SAME token).
  test('reopening the same session after a reload projects the same code', async ({
    staffPage, workerTenant,
  }) => {
    await gotoProctorScreen(staffPage)
    const examSession = parkId(workerTenant, 'reload')
    const first = await startPark(staffPage, examSession)

    // A professor's browser reload: React state is gone, the screen has to be
    // reopened and the park restarted by hand.
    await staffPage.reload()
    await staffPage.waitForLoadState('networkidle')
    await openProctorScreen(staffPage)
    await expect(staffPage.getByText('Not started')).toBeVisible()

    const second = await startPark(staffPage, examSession)
    expect(second.token).toBe(first.token)
    expect(second.qrUrl).toBe(first.qrUrl)
  })

  // ── 6 ──────────────────────────────────────────────────────────────────
  // parked.html end to end, on a real token, in a real browser. `page` is the
  // unauthenticated context on purpose: the phone has no login and never will.
  test('the parked page a phone holds reaches its parked state and raises a tile', async ({
    staffPage, workerTenant, page,
  }) => {
    await gotoProctorScreen(staffPage)
    const { token } = await startPark(staffPage, parkId(workerTenant, 'phone'))

    await page.goto(`/bluebook/parked.html?t=${encodeURIComponent(token)}`)
    await expect(page.getByRole('heading', { name: 'Park your phone' })).toBeVisible()
    await page.getByLabel('Name or initials').fill(HINT)
    await page.getByRole('button', { name: 'Park my phone' }).click()

    // The parked display state: the clock, the student's own echo, the calm
    // status line. `screen-notice` staying hidden is the assertion that the
    // beat was ACCEPTED — a rejected token flips the page to "This exam link
    // has expired" within the first beat.
    await expect(page.locator('#screen-parked')).toBeVisible()
    await expect(page.locator('#screen-name')).toBeHidden()
    await expect(page.locator('#screen-notice')).toBeHidden()
    await expect(page.locator('#hint-echo')).toHaveText(HINT)
    await expect(page.locator('#status-text')).toHaveText('Parked')
    await expect(page.locator('#timer')).toBeVisible()

    // ...and the professor watching the other screen sees that phone arrive.
    await expect(staffPage.getByRole('button', { name: PARKED_TILE })).toBeVisible({ timeout: 15_000 })
  })

  // ── 7 ──────────────────────────────────────────────────────────────────
  // The other end of the loop: the sitting finishes and the professor closes
  // the park. This is the deletion path the privacy claim rests on ("the beats
  // are deleted"), so what the screen does afterwards has to be unambiguous —
  // a stale tile left on a wall display would say a phone is still parked in a
  // room that has emptied.
  test('closing the park clears the tiles and returns the screen to idle', async ({
    staffPage, workerTenant, request,
  }) => {
    await gotoProctorScreen(staffPage)
    const { token } = await startPark(staffPage, parkId(workerTenant, 'close'))
    const beat = await postBeat(request, token, HINT)
    expect(beat.status(), await beat.text()).toBe(200)

    const tile = staffPage.getByRole('button', { name: PARKED_TILE })
    await expect(tile).toBeVisible({ timeout: 15_000 })

    await staffPage.getByRole('button', { name: 'Close Phone Park' }).click()

    // The tile goes, and it goes because the park is gone — not because the
    // grid was merely hidden behind a spinner.
    await expect(tile).toHaveCount(0)
    await expect(staffPage.getByRole('button', { name: 'Close Phone Park' })).toHaveCount(0)
    await expectIdleAndErrorFree(staffPage)

    // Politely announced, and it states the two things a professor needs to
    // believe about a closed park.
    const closedNotice = staffPage.locator('[role="status"]', { hasText: 'Phone park closed.' })
    await expect(closedNotice).toBeVisible()
    await expect(closedNotice).toContainText('The code no longer works and the beats are deleted.')

    // And the server agrees: the park it was reporting on is gone, so the
    // status endpoint 404s rather than returning an empty tile list.
    const after = await request.get('/proctor/park/status', {
      params: { exam_session_id: parkId(workerTenant, 'close') },
      headers: { Authorization: `Bearer ${workerTenant.staff.token}` },
    })
    expect(after.status(), await after.text()).toBe(404)
  })

  // ── 8 ──────────────────────────────────────────────────────────────────
  // A close that races another close (two proctors, or a professor on a laptop
  // and a podium machine). The server's answer to "delete something already
  // deleted" is 404, and the UI has to read that as "already gone" — the one
  // outcome the click was asking for — instead of showing the room an error.
  test('closing a park the server already deleted reads as already gone, not an error', async ({
    staffPage, workerTenant, request,
  }) => {
    await gotoProctorScreen(staffPage)
    const examSession = parkId(workerTenant, 'gone')
    const { token } = await startPark(staffPage, examSession)

    // Two phones, so the delete count below is unambiguous about what it counts.
    for (const hint of ['A.B.', 'C.D.']) {
      const beat = await postBeat(request, token, hint)
      expect(beat.status(), await beat.text()).toBe(200)
    }
    await expect(staffPage.getByRole('button', { name: /^A\.B\. — Parked/ }))
      .toBeVisible({ timeout: 15_000 })

    // Someone else closes it first.
    const deleted = await deleteParkAsStaff(request, workerTenant, examSession)
    expect(deleted.status(), await deleted.text()).toBe(200)
    // `deleted` counts ROWS — the session row plus one beat row per phone — so
    // two parked phones delete three rows. Pinned here precisely because the
    // number reads like a phone count and is not one: showing it to a proctor
    // as "3 phones released" would be a lie, which is why ProctorScreen's
    // close handler throws the response away (components.jsx parkDelete).
    expect((await deleted.json()).deleted, 'deleted counts rows, not phones').toBe(3)

    // Now the button. Server says 404; the professor must not see a failure.
    await staffPage.getByRole('button', { name: 'Close Phone Park' }).click()
    await expectIdleAndErrorFree(staffPage)
    await expect(staffPage.locator('[role="status"]', { hasText: 'Phone park closed.' }))
      .toBeVisible()
  })

  // ── 9 ──────────────────────────────────────────────────────────────────
  // The same 404, arriving on the other channel. `GET /proctor/park/status`
  // answers 404 — not an empty list — for a park that has been deleted, and
  // the 5s poll loop walks into it the moment anyone else closes the sitting.
  // `parkStatus` maps that 404 to `{ tiles: [], missing: true }` on purpose
  // (components.jsx); this is the browser-side proof it renders as an empty
  // state rather than blanking the view or raising a banner.
  test('a park deleted while the poll is running empties the tiles without an error', async ({
    staffPage, workerTenant, request,
  }) => {
    await gotoProctorScreen(staffPage)
    const examSession = parkId(workerTenant, 'vanish')
    const { token } = await startPark(staffPage, examSession)
    const beat = await postBeat(request, token, HINT)
    expect(beat.status(), await beat.text()).toBe(200)

    const tile = staffPage.getByRole('button', { name: PARKED_TILE })
    await expect(tile).toBeVisible({ timeout: 15_000 })

    const deleted = await deleteParkAsStaff(request, workerTenant, examSession)
    expect(deleted.status(), await deleted.text()).toBe(200)

    // Next poll (POLL_MS = 5s) — auto-waiting, no sleep.
    await expect(tile).toHaveCount(0, { timeout: 15_000 })
    await expect(staffPage.getByText('No phone park is open for this examination yet.'))
      .toBeVisible()
    await expect(staffPage.locator('[role="alert"]')).toHaveCount(0)
    // Distinct from the never-started empty state: this screen still HAS an
    // open park as far as React knows, so it must not claim otherwise.
    await expect(staffPage.getByText('Start a phone park above to see tiles here.')).toHaveCount(0)
  })

  // ── 10 ─────────────────────────────────────────────────────────────────
  // The control for tests 7–9. Those three assert `[role="alert"]` has count
  // zero; that assertion is only worth anything if the banner can actually
  // reach count one. A close that genuinely fails — 503, not 404 — has to say
  // so, because the park is still live and the professor needs to know the
  // code in front of the room still works.
  test('a close that really fails does raise the error banner', async ({
    staffPage, workerTenant,
  }) => {
    await gotoProctorScreen(staffPage)
    const examSession = parkId(workerTenant, 'fail')
    await startPark(staffPage, examSession)

    await staffPage.route(`**/proctor/park/${examSession}`, (route) =>
      route.request().method() === 'DELETE'
        ? route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Could not reach the park store.' }),
        })
        : route.fallback())

    await staffPage.getByRole('button', { name: 'Close Phone Park' }).click()

    await expect(staffPage.locator('[role="alert"]')).toHaveText('Could not reach the park store.')
    // ...and the screen did NOT pretend the park closed: the code is still
    // projected and the close control is still there to retry with.
    await expect(staffPage.getByRole('img', { name: /QR code for the phone park/ })).toBeVisible()
    await expect(staffPage.getByRole('button', { name: 'Close Phone Park' })).toBeEnabled()
    await expect(staffPage.locator('[role="status"]', { hasText: 'Phone park closed.' }))
      .toHaveCount(0)
  })
})

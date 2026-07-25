/**
 * proctor.spec.mjs — the QR phone-park Proctor screen (T10, closing the first
 * of the two gaps flagged when T9 merged: nothing in CI noticed if this screen
 * broke). The axe half of T10 lives in a11y.spec.mjs's SCREENS list.
 *
 * Covers, in one browser, the loop the feature actually is: professor opens a
 * park → a code is projected → a phone beats against that code → a tile
 * appears → the proctor can read its timeline. Plus parked.html itself, the
 * standalone page the phone holds, driven with a REAL token minted by the
 * professor's own screen in the same test.
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
})

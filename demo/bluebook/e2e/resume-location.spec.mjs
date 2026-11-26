/**
 * resume-location.spec.mjs — cross-device "resume where you left off"
 * (Andrew, 2026-10-21). Browser A leaves a place (a student's work open on
 * Students, scrolled down; the Phone park tab of the live view); browser B,
 * a phone-sized window, signs in and lands there. A student who was writing
 * lands on the exam's briefing, never inside the sitting.
 */
import { test, expect } from '@playwright/test'

const uid = () => `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`
const TPASS = 'e2e-teacher-pass-1'
const SPASS = 'e2e-student-pass-1'
const PHONE = { viewport: { width: 390, height: 780 }, isMobile: true, hasTouch: true }

async function api(request, method, path, token, data) {
  const r = await request.fetch(path, {
    method, data, headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  expect(r.ok(), `${method} ${path}: ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

// A teacher with a long roster (so Students scrolls) and one student, X, who
// has sealed work to open.
async function setup(request, nStudents = 28) {
  const id = uid()
  const email = `rl-teacher-${id}@e2e.test`
  const t = await api(request, 'POST', '/auth/signup', null, { name: 'E2E Teacher', email, password: TPASS, accept_terms: true })
  const course = await api(request, 'POST', '/bluebook/courses', t.token, { name: 'Alpha', code: 'A1' })
  const students = Array.from({ length: nStudents }, (_, i) => ({ email: `rl-s${i}-${id}@e2e.test`, name: `Student ${String(i).padStart(2, '0')}` }))
  const roster = (await api(request, 'POST', `/bluebook/courses/${course.id}/students`, t.token, { students, send_email: false })).students
  const x = roster.find(r => r.name === 'Student 20') || roster[roster.length - 1]
  const token = new URL(x.invite_path, 'http://x').searchParams.get('invite')
  const s = await api(request, 'POST', '/auth/invite/redeem', null, { token, password: SPASS, accept_terms: true })
  const exam = await api(request, 'POST', '/bluebook/exams', t.token, {
    title: `Resume ${id}`, status: 'ACTIVE', duration: 25, questions: ['Say something.'], conditions: { aiDetect: false },
  })
  await api(request, 'POST', `/bluebook/me/exams/${exam.id}/start`, s.token)
  await api(request, 'POST', '/bluebook/submissions', s.token, {
    exam_id: exam.id, student_id: x.student_id, word_count: 3, text: 'three short words', answers: ['three short words'],
  })
  return { email, exam, x, xEmail: students.find(r => r.name === x.name).email }
}

async function signIn(page, email, password) {
  await page.goto('/bluebook/')
  await page.getByRole('button', { name: /^Sign in$/ }).first().click()
  await page.locator('#bbLoginEmail').fill(email)
  await page.locator('#bbLoginPass').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).last().click()
}

// The next save whose body matches `want` (earlier saves of the same screen are skipped).
const savedLocation = (page, want = () => true) => page.waitForResponse(r => r.url().endsWith('/bluebook/me/location')
  && r.request().method() === 'PUT' && r.ok() && want(JSON.parse(r.request().postData() || '{}')), { timeout: 15_000 })

test('a student\'s work, scrolled, on a laptop opens in the same place on a phone', async ({ browser, request }) => {
  test.setTimeout(120_000)
  const { email, x } = await setup(request)

  // Browser A (laptop): Students, open X's work, scroll it to the top.
  const A = await browser.newContext({ viewport: { width: 1280, height: 800 } })
  const a = await A.newPage()
  await signIn(a, email, TPASS)
  await expect(a.getByRole('button', { name: 'Overview', exact: true })).toBeVisible({ timeout: 10_000 })
  await a.getByRole('button', { name: 'Students', exact: true }).first().click()
  const row = a.getByRole('row', { name: new RegExp(x.name) })
  await row.getByRole('button', { name: 'View work' }).click()
  const work = a.getByRole('region', { name: `Work by ${x.name}` })
  await expect(work).toBeVisible()
  // Scrolled so X's row is at the top of the list.
  const saved = savedLocation(a, b => b.scroll_fraction > 0 && b.scroll_anchor === `row-${x.student_id}`)
  await a.locator(`[data-resume-anchor="row-${x.student_id}"]`).evaluate(el => el.scrollIntoView({ block: "start" }))
  const put = JSON.parse((await saved).request().postData())
  expect(put).toMatchObject({ screen: 'students', entity_kind: 'student', entity_id: x.student_id })
  await A.close()

  // Browser B (phone): sign in, land on Students with X's work open and
  // X's row at the top of the screen.
  const B = await browser.newContext(PHONE)
  const b = await B.newPage()
  await signIn(b, email, TPASS)
  await expect(b.getByRole('region', { name: `Work by ${x.name}` })).toBeAttached({ timeout: 15_000 })
  await expect(b.getByRole('button', { name: 'Hide work' })).toBeVisible()
  const brow = b.locator(`[data-resume-anchor="row-${x.student_id}"]`)
  await expect.poll(async () => {
    const box = await brow.boundingBox()
    return box ? Math.round(box.y) : -1
  }, { timeout: 10_000 }).toBeLessThan(120)
  expect(await brow.boundingBox().then(bx => bx.y)).toBeGreaterThan(-40)
  expect(await b.evaluate(() => { const p = document.querySelector('[data-resume-scroll]'); return Math.max(window.scrollY, p ? p.scrollTop : 0) })).toBeGreaterThan(300)
  expect(b.url()).not.toContain('invite=')
  await B.close()
})

test('the live view\'s Phone park tab is reopened on another device', async ({ browser, request }) => {
  test.setTimeout(90_000)
  const { email, exam } = await setup(request, 2)
  const A = await browser.newContext()
  const a = await A.newPage()
  await signIn(a, email, TPASS)
  await expect(a.getByRole('button', { name: 'Overview', exact: true })).toBeVisible({ timeout: 10_000 })
  await a.goto(`/bluebook/#live/${exam.id}`)
  await expect(a.getByRole('tab', { name: 'Phone park' })).toBeVisible({ timeout: 10_000 })
  const saved = savedLocation(a, b => b.tab === 'phones')
  await a.getByRole('tab', { name: 'Phone park' }).click()
  expect(JSON.parse((await saved).request().postData())).toMatchObject({ screen: 'proctor', entity_id: exam.id, tab: 'phones' })
  await A.close()

  const B = await browser.newContext(PHONE)
  const b = await B.newPage()
  await signIn(b, email, TPASS)
  await expect(b.getByRole('tab', { name: 'Phone park' })).toHaveAttribute('aria-selected', 'true', { timeout: 15_000 })
  await B.close()
})

test('a deleted item falls back to Overview', async ({ browser, request }) => {
  test.setTimeout(90_000)
  const id = uid()
  const email = `rl-del-${id}@e2e.test`
  const t = await api(request, 'POST', '/auth/signup', null, { name: 'E2E Teacher', email, password: TPASS, accept_terms: true })
  const exam = await api(request, 'POST', '/bluebook/exams', t.token, {
    title: `Gone ${id}`, status: 'ACTIVE', duration: 25, questions: ['Q'], conditions: { aiDetect: false },
  })
  await api(request, 'PUT', '/bluebook/me/location', t.token, { screen: 'manage-exam', entity_kind: 'exam', entity_id: exam.id })
  await api(request, 'DELETE', `/bluebook/exams/${exam.id}`, t.token)
  const B = await browser.newContext(PHONE)
  const b = await B.newPage()
  await signIn(b, email, TPASS)
  await expect(b.getByRole('button', { name: 'Overview', exact: true })).toBeVisible({ timeout: 10_000 })
  await expect(b.getByText(`Gone ${id}`)).toHaveCount(0)
  await B.close()
})

test('a student who was writing lands on the exam briefing, not inside the sitting', async ({ browser, request }) => {
  test.setTimeout(90_000)
  const id = uid()
  const email = `rl-t2-${id}@e2e.test`
  const t = await api(request, 'POST', '/auth/signup', null, { name: 'E2E Teacher', email, password: TPASS, accept_terms: true })
  const course = await api(request, 'POST', '/bluebook/courses', t.token, { name: 'Beta', code: 'B1' })
  const sEmail = `rl-st-${id}@e2e.test`
  const [row] = (await api(request, 'POST', `/bluebook/courses/${course.id}/students`, t.token, { students: [{ email: sEmail, name: 'Sam' }], send_email: false })).students
  const s = await api(request, 'POST', '/auth/invite/redeem', null, { token: new URL(row.invite_path, 'http://x').searchParams.get('invite'), password: SPASS, accept_terms: true })
  const exam = await api(request, 'POST', '/bluebook/exams', t.token, {
    title: `Sitting ${id}`, status: 'ACTIVE', duration: 25, questions: ['Q'], conditions: { aiDetect: false },
  })
  // Saved from inside the sitting: kept as the briefing.
  await api(request, 'PUT', '/bluebook/me/location', s.token, { screen: 'exam', entity_kind: 'exam', entity_id: exam.id })
  const B = await browser.newContext(PHONE)
  const b = await B.newPage()
  await b.addInitScript(() => { Element.prototype.requestFullscreen = () => Promise.resolve() })
  await signIn(b, sEmail, SPASS)
  await expect(b.getByRole('button', { name: /Begin writing|Resume writing/ })).toBeVisible({ timeout: 15_000 })
  await expect(b.getByLabel('Your answer', { exact: true })).toHaveCount(0)
  await B.close()
})

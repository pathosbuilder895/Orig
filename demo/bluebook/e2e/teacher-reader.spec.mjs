/**
 * teacher-reader.spec.mjs: reading and marking one sealed submission.
 *
 *   - While the submission loads, the reader says so (a status line), instead
 *     of a heading that reads "Loading…" and stays that way on a failure.
 *   - A submission that cannot be loaded says so and offers to try again.
 *   - An exam's submission list says it is loading rather than claiming
 *     "Nobody has submitted yet." before the list has arrived.
 *   - Print gives a clean sheet of the sealed submission (no app chrome, no
 *     form fields), and the text can be downloaded as a plain file.
 */

import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { createCourse, provisionTenantWithStaff, staffStorageState } from './fixtures/api-setup.mjs'

const uid = () => `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`
const QUESTION = 'Does the mean between rashness and cowardice depend on the person?'
const ANSWER =
  'Aristotle places courage between rashness and cowardice, and the mean is relative to us: ' +
  'what is brave for one person may be rash for another, which is why practice matters.'

async function workspace(request, { seal = true } = {}) {
  const id = uid()
  const { tenant, staff } = await provisionTenantWithStaff(request)
  const teacher = { Authorization: `Bearer ${staff.token}` }
  const course = await createCourse(request, staff.token, { name: `Reader course ${id}` })
  const examTitle = `Reader exam ${id}`
  const created = await request.post('/bluebook/exams', {
    headers: teacher,
    data: { title: examTitle, course: course.code, course_id: course.id, duration: 30, questions: [QUESTION], status: 'ACTIVE' },
  })
  expect(created.status(), await created.text()).toBe(201)
  const examId = (await created.json()).id
  if (seal) {
    const added = await request.post(`/bluebook/courses/${encodeURIComponent(course.id)}/students`, {
      headers: teacher, data: { students: [{ email: `reader-${id}@e2e.test`, name: 'Reader Student' }] },
    })
    const invite = new URL((await added.json()).students[0].invite_path, 'http://x').searchParams.get('invite')
    const student = await (await request.post('/auth/invite/redeem', { data: { token: invite, password: 'e2e-passw0rd!' } })).json()
    const asStudent = { Authorization: `Bearer ${student.token}` }
    await request.post(`/bluebook/me/exams/${encodeURIComponent(examId)}/start`, { headers: asStudent })
    const sealed = await request.post('/bluebook/submissions', {
      headers: asStudent,
      data: {
        exam_id: examId, student_id: student.student_id, candidate: 'Reader Student',
        word_count: 34, time_min: 12, text: ANSWER, answers: [ANSWER], submission_uuid: `uuid-${id}`,
        warnings: [{ type: 'focus_lost', at: new Date().toISOString() }],
      },
    })
    expect(sealed.status(), await sealed.text()).toBe(201)
  }
  return { tenant, staff, examTitle }
}

async function teacherPage(browser, baseURL, { tenant, staff }) {
  const ctx = await browser.newContext({
    storageState: staffStorageState(baseURL, { token: staff.token, role: 'professor', tenant_id: tenant.tenant_id }),
  })
  const page = await ctx.newPage()
  await page.addInitScript(() => localStorage.setItem('original_products', JSON.stringify(['bluebook'])))
  return { ctx, page }
}

async function openExam(page, examTitle) {
  await page.goto('/bluebook/')
  await page.getByRole('button', { name: 'Collections' }).first().click()
  await page.getByRole('button', { name: examTitle }).click()
}

const isDetail = route => route.request().method() === 'GET' && /\/bluebook\/submissions\/[^/]+$/.test(new URL(route.request().url()).pathname)

test.describe('Teacher reading and marking a sealed submission', () => {
  test('the reader says it is loading, then shows the submission', async ({ browser, request, baseURL }) => {
    const ws = await workspace(request)
    const { ctx, page } = await teacherPage(browser, baseURL, ws)
    let release
    const held = new Promise(r => { release = r })
    await page.route('**/bluebook/submissions/*', async route => {
      if (!isDetail(route)) return route.continue()
      await held
      return route.continue()
    })
    await openExam(page, ws.examTitle)
    await page.getByRole('button', { name: 'Read & mark' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Loading the submission…' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Loading…' })).toHaveCount(0)
    release()
    await expect(page.getByRole('heading', { name: 'Reader Student' })).toBeVisible()
    await expect(page.getByText(ANSWER)).toBeVisible()
    await ctx.close()
  })

  test('a submission that cannot be loaded says so and can be tried again', async ({ browser, request, baseURL }) => {
    const ws = await workspace(request)
    const { ctx, page } = await teacherPage(browser, baseURL, ws)
    let failures = 1
    await page.route('**/bluebook/submissions/*', route => {
      if (!isDetail(route) || failures-- <= 0) return route.continue()
      return route.fulfill({ status: 500, body: 'Internal Server Error' })
    })
    await openExam(page, ws.examTitle)
    await page.getByRole('button', { name: 'Read & mark' }).click()
    await expect(page.getByText('We could not load this submission.')).toBeVisible()
    await page.getByRole('button', { name: 'Try again' }).click()
    await expect(page.getByText(ANSWER)).toBeVisible()
    await ctx.close()
  })

  test("an exam's submission list says it is loading before it says nobody has submitted", async ({ browser, request, baseURL }) => {
    const ws = await workspace(request, { seal: false })
    const { ctx, page } = await teacherPage(browser, baseURL, ws)
    let release
    const held = new Promise(r => { release = r })
    await page.route('**/bluebook/submissions', async route => {
      if (route.request().method() === 'GET') await held
      return route.continue()
    })
    await openExam(page, ws.examTitle)
    await expect(page.getByText('Loading submissions…')).toBeVisible()
    await expect(page.getByText(/Nobody has submitted yet/)).toHaveCount(0)
    release()
    await expect(page.getByText('Nobody has submitted yet. Sealed booklets appear here as students submit them.')).toBeVisible()
    await ctx.close()
  })

  test("an exam's submission list that failed to load clears its error once Try again works", async ({ browser, request, baseURL }) => {
    const ws = await workspace(request)
    const { ctx, page } = await teacherPage(browser, baseURL, ws)
    await page.goto('/bluebook/')
    await page.getByRole('button', { name: 'Collections' }).first().click()
    // Fail only the exam screen's own list request, not the dashboard's.
    let failures = 1
    await page.route('**/bluebook/submissions', route => {
      if (route.request().method() !== 'GET' || failures-- <= 0) return route.continue()
      return route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Briefly unavailable."}' })
    })
    await page.getByRole('button', { name: ws.examTitle }).click()
    await expect(page.getByText('Briefly unavailable.')).toBeVisible()
    await page.getByRole('button', { name: 'Try again' }).click()
    await expect(page.getByRole('button', { name: 'Read & mark' })).toBeVisible()
    await expect(page.getByText('Briefly unavailable.')).toHaveCount(0)
    await ctx.close()
  })

  test('print gives a clean sheet of the sealed submission', async ({ browser, request, baseURL }) => {
    const ws = await workspace(request)
    const { ctx, page } = await teacherPage(browser, baseURL, ws)
    // Record whether the sheet was on the page at the moment print was asked for.
    await page.addInitScript(() => {
      window.__printed = []
      window.print = () => { window.__printed.push(!!document.querySelector('.bb-print-root .bb-print-sheet')) }
    })
    await openExam(page, ws.examTitle)
    await page.getByRole('button', { name: 'Read & mark' }).click()
    await expect(page.getByText(ANSWER)).toBeVisible()
    await page.getByLabel('Mark (optional)').fill('B+')
    await page.getByLabel('Feedback for the student (optional)').fill('A careful reading of the mean.')
    await page.getByRole('button', { name: 'Save mark and feedback' }).click()
    await expect(page.getByRole('status').filter({ hasText: /Saved/ })).toBeVisible()

    await page.getByRole('button', { name: 'Print' }).click()
    expect(await page.evaluate(() => window.__printed)).toEqual([true])
    // Outside printing the sheet is not on the page at all: one copy of the text.
    await expect(page.locator('.bb-print-root')).toHaveCount(0)

    // The browser's own Print (Ctrl/Cmd+P) fires beforeprint: same sheet.
    await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')))
    await page.emulateMedia({ media: 'print' })
    const sheet = page.locator('.bb-print-root')
    await expect(sheet).toBeVisible()
    await expect(page.locator('#root')).toBeHidden()
    for (const text of [ws.examTitle, 'Reader Student', QUESTION, ANSWER, 'Left the window × 1', 'B+', 'A careful reading of the mean.']) {
      await expect(sheet.getByText(text, { exact: false }).first()).toBeVisible()
    }
    await expect(sheet.locator('input, textarea, button')).toHaveCount(0)

    await page.emulateMedia({ media: 'screen' })
    await page.evaluate(() => window.dispatchEvent(new Event('afterprint')))
    await expect(page.locator('.bb-print-root')).toHaveCount(0)
    await expect(page.locator('#root')).toBeVisible()
    await ctx.close()
  })

  test('the open reader passes an axe scan', async ({ browser, request, baseURL }) => {
    const ws = await workspace(request)
    const { ctx, page } = await teacherPage(browser, baseURL, ws)
    await openExam(page, ws.examTitle)
    await page.getByRole('button', { name: 'Read & mark' }).click()
    await expect(page.getByText(ANSWER)).toBeVisible()
    await page.waitForLoadState('networkidle')
    await page.waitForFunction(() => document.getAnimations()
      .filter(a => a.effect?.getComputedTiming?.().iterations !== Infinity)
      .every(a => a.playState === 'finished'))
    const results = await new AxeBuilder({ page }).include('.bb-reader').withTags(['wcag2a', 'wcag2aa']).analyze()
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([])
    await ctx.close()
  })

  test('the sealed text can be downloaded as a plain file', async ({ browser, request, baseURL }) => {
    const ws = await workspace(request)
    const { ctx, page } = await teacherPage(browser, baseURL, ws)
    await openExam(page, ws.examTitle)
    await page.getByRole('button', { name: 'Read & mark' }).click()
    await expect(page.getByText(ANSWER)).toBeVisible()
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: 'Download as text' }).click(),
    ])
    expect(download.suggestedFilename()).toMatch(/^Reader-exam-.*Reader-Student\.txt$/)
    const body = Buffer.concat(await (await download.createReadStream()).toArray()).toString('utf8')
    for (const text of [ws.examTitle, 'Reader Student', QUESTION, ANSWER, 'Session notes: Left the window × 1']) {
      expect(body).toContain(text)
    }
    await ctx.close()
  })
})

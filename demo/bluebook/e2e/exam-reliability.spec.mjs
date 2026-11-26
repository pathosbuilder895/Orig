/**
 * exam-reliability.spec.mjs: a dropped connection or a refresh during a
 * timed sitting must never lose work, and sealing must never submit twice.
 *
 * exam-robustness.spec.mjs covers the server-pinned clock and the plain
 * retry. This file covers what happens around it:
 *   - the draft is written as the student types, so a refresh right after a
 *     keystroke keeps it;
 *   - once the student confirms the seal, the answers are final: they lock,
 *     and a refresh (or the failure screen's "Try again") finishes that same
 *     seal with the same submission id instead of reopening the booklet;
 *   - a response lost after the server recorded the row is not a second row;
 *   - a refusal (4xx) stops at once instead of retrying for a minute;
 *   - an offline seal waits and then submits;
 *   - one student's unsent draft is never restored into another's booklet;
 *   - a browser that cannot keep a draft says so.
 *
 * Boot pattern: exam-robustness.spec.mjs's (a real exam, a launch-bound
 * student), so the session and submission routes have rows to work on.
 */

import { isolatedTest as test, expect } from './fixtures/tenancy.mjs'
import { studentStorageState } from './fixtures/api-setup.mjs'
import { confirmSeal } from './fixtures/seal.mjs'

const BOX = 'textarea[placeholder="Begin writing here…"]'
const ESSAY =
  'Aristotle treats courage as a mean between rashness and cowardice, and ' +
  'the student who practises it learns where that mean lies by acting well.'

function staffAuth(testTenant) {
  return { Authorization: `Bearer ${testTenant.staff.token}` }
}

async function createExam(request, testTenant, title) {
  const res = await request.post('/bluebook/exams', {
    headers: staffAuth(testTenant),
    data: {
      title, course: 'PHIL 220', duration: 120, minWords: 12, maxWords: 5000,
      prompt: 'Discuss.', status: 'PUBLISHED',
    },
  })
  expect(res.ok()).toBe(true)
  return res.json()
}

async function rowsFor(request, testTenant, examId) {
  const res = await request.get('/bluebook/submissions', { headers: staffAuth(testTenant) })
  expect(res.ok()).toBe(true)
  const body = await res.json()
  return (body.submissions || []).filter(s => s.exam_id === examId)
}

async function bootInExam(page, exam, testTenant, { studentId, blockWeb = false } = {}) {
  await page.addInitScript(([examArg, sid, bw]) => {
    localStorage.setItem('bluebook_student_id', sid)
    window.BB_EXAM_CONFIG = {
      id: examArg.id, title: examArg.title, course: examArg.course, courseTitle: examArg.course,
      candidate: 'Reliability Candidate', duration: 7200, minWords: 12, maxWords: null,
      blockWeb: bw, blockCopy: false, spellChk: true,
    }
    Element.prototype.requestFullscreen = function () { return Promise.resolve() }
  }, [exam, studentId || testTenant.student.student_id, blockWeb])
  await page.goto('/bluebook/')
  await page.waitForLoadState('networkidle')
}

async function enter(page) {
  await page.getByRole('button', { name: /Begin writing|Resume writing/ }).click()
}

async function writeAndSeal(page) {
  await enter(page)
  await page.locator(BOX).click()
  await page.keyboard.type(ESSAY, { delay: 1 })
  await page.getByRole('button', { name: /Seal & Submit/ }).click()
  await confirmSeal(page)
}

test.describe('Exam reliability @robustness', () => {
  test('text typed just before a refresh is still there afterwards', async ({ studentPage, testTenant, request }) => {
    const exam = await createExam(request, testTenant, 'Reliability refresh exam')
    await bootInExam(studentPage, exam, testTenant)
    await enter(studentPage)
    await studentPage.locator(BOX).click()
    await studentPage.keyboard.type('Every word up to the last one counts.', { delay: 1 })
    // No wait: the draft must already be on the device.
    await studentPage.reload()
    await studentPage.waitForLoadState('networkidle')
    await enter(studentPage)
    await expect(studentPage.locator(BOX)).toHaveValue('Every word up to the last one counts.')
  })

  test('confirmed answers lock while the seal is on its way', async ({ studentPage, testTenant, request }) => {
    const exam = await createExam(request, testTenant, 'Reliability lock exam')
    // Hold the submission so the seal stays in flight.
    await studentPage.route('**/bluebook/submissions', () => {})
    await bootInExam(studentPage, exam, testTenant)
    await writeAndSeal(studentPage)
    await expect(studentPage.locator(BOX)).toHaveAttribute('readonly', '')
    await expect(studentPage.getByRole('button', { name: /Submitting/ })).toBeDisabled()
  })

  test('a refresh while sealing finishes the same seal, once', async ({ studentPage, testTenant, request }) => {
    test.setTimeout(60_000)
    const exam = await createExam(request, testTenant, 'Reliability resume exam')
    const uuids = []
    await studentPage.route('**/bluebook/submissions', route => {
      if (route.request().method() !== 'POST') return route.continue()
      uuids.push(route.request().postDataJSON().submission_uuid)
      // The first attempt never answers: the student refreshes mid-seal.
      if (uuids.length === 1) return undefined
      return route.continue()
    })
    await bootInExam(studentPage, exam, testTenant)
    await writeAndSeal(studentPage)
    await expect.poll(() => uuids.length).toBe(1)

    await studentPage.reload()
    await studentPage.waitForLoadState('networkidle')
    await enter(studentPage)
    // No second confirmation and no second chance to edit: the seal resumes.
    await expect(studentPage.getByRole('heading', { name: 'Collection Sealed' })).toBeVisible({ timeout: 30_000 })
    expect(new Set(uuids).size).toBe(1)
    const rows = await rowsFor(request, testTenant, exam.id)
    expect(rows).toHaveLength(1)
    expect(rows[0].submission_uuid).toBe(uuids[0])
  })

  test('a reply lost after the server recorded the seal is not a second submission', async ({
    studentPage, testTenant, request,
  }) => {
    test.setTimeout(60_000)
    const exam = await createExam(request, testTenant, 'Reliability lost reply exam')
    const uuids = []
    await studentPage.route('**/bluebook/submissions', async route => {
      if (route.request().method() !== 'POST') return route.continue()
      uuids.push(route.request().postDataJSON().submission_uuid)
      if (uuids.length === 1) {
        await route.fetch()          // the server writes the row...
        return route.abort()         // ...and the reply never arrives
      }
      return route.continue()
    })
    await bootInExam(studentPage, exam, testTenant)
    await writeAndSeal(studentPage)
    await expect(studentPage.getByRole('heading', { name: 'Collection Sealed' })).toBeVisible({ timeout: 30_000 })
    expect(uuids.length).toBeGreaterThan(1)
    expect(new Set(uuids).size).toBe(1)
    expect(await rowsFor(request, testTenant, exam.id)).toHaveLength(1)
  })

  test('a refusal stops at once and keeps the draft', async ({ studentPage, testTenant, request }) => {
    const exam = await createExam(request, testTenant, 'Reliability refusal exam')
    let posts = 0
    await studentPage.route('**/bluebook/submissions', route => {
      if (route.request().method() !== 'POST') return route.continue()
      posts += 1
      return route.fulfill({ status: 422, contentType: 'application/json', body: '{"detail":"Not accepted."}' })
    })
    await bootInExam(studentPage, exam, testTenant)
    await writeAndSeal(studentPage)
    // A 422 will not change on retry: no 2s/5s backoff before saying so.
    await studentPage.waitForFunction(() => window.BB_LAST_SUBMISSION && window.BB_LAST_SUBMISSION.ok === false,
      undefined, { timeout: 4_000 })
    expect(posts).toBe(1)
    const kept = await studentPage.evaluate(() => {
      const key = Object.keys(localStorage).find(k => k.startsWith('bb_draft_'))
      return key && JSON.parse(localStorage.getItem(key)).answers.join(' ')
    })
    expect(kept).toContain(ESSAY)
  })

  test('"Try again" on the failure screen resubmits the same answers under the same id', async ({
    studentPage, testTenant, request,
  }) => {
    test.setTimeout(60_000)
    const exam = await createExam(request, testTenant, 'Reliability try again exam')
    const uuids = []
    let refuse = true
    await studentPage.route('**/bluebook/submissions', route => {
      if (route.request().method() !== 'POST') return route.continue()
      uuids.push(route.request().postDataJSON().submission_uuid)
      if (refuse) return route.fulfill({ status: 403, contentType: 'application/json', body: '{"detail":"Not now."}' })
      return route.continue()
    })
    await bootInExam(studentPage, exam, testTenant)
    await writeAndSeal(studentPage)
    await expect(studentPage.getByRole('button', { name: /Try again/i })).toBeVisible({ timeout: 10_000 })

    refuse = false
    await studentPage.getByRole('button', { name: /Try again/i }).click()
    await expect(studentPage.getByRole('heading', { name: 'Collection Sealed' })).toBeVisible({ timeout: 30_000 })
    expect(new Set(uuids).size).toBe(1)
    const rows = await rowsFor(request, testTenant, exam.id)
    expect(rows).toHaveLength(1)
    const sealed = await request.get(`/bluebook/submissions/${rows[0].id}`, { headers: staffAuth(testTenant) })
    expect((await sealed.json()).text).toContain(ESSAY)
  })

  test('leaving the window while the seal is retrying is not noted', async ({ studentPage, testTenant, request }) => {
    test.setTimeout(60_000)
    const exam = await createExam(request, testTenant, 'Reliability no notes while sealing exam')
    let attempts = 0
    await studentPage.route('**/bluebook/submissions', route => {
      if (route.request().method() !== 'POST') return route.continue()
      attempts += 1
      if (attempts > 1) return route.continue()
      // The first attempt hangs, then fails: the seal is in flight for a while.
      return new Promise(r => setTimeout(r, 3000)).then(() => route.abort())
    })
    // Lockdown on, so leaving the window is noted while the student writes.
    await bootInExam(studentPage, exam, testTenant, { blockWeb: true })
    await enter(studentPage)
    await studentPage.locator(BOX).click()
    await studentPage.keyboard.type(ESSAY, { delay: 1 })
    await studentPage.getByRole('button', { name: /Seal & Submit/ }).click()
    await confirmSeal(studentPage)
    // While the seal is in flight (and past the 1.5s that absorbs the confirm
    // dialog's own blur), the student looks away.
    await expect.poll(() => attempts).toBe(1)
    await studentPage.waitForTimeout(1800)
    await studentPage.evaluate(() => window.dispatchEvent(new Event('blur')))
    await expect(studentPage.getByRole('heading', { name: 'Collection Sealed' })).toBeVisible({ timeout: 30_000 })
    const rows = await rowsFor(request, testTenant, exam.id)
    const sealed = await (await request.get(`/bluebook/submissions/${rows[0].id}`, { headers: staffAuth(testTenant) })).json()
    expect(sealed.warnings).toEqual([])
  })

  test('a seal started offline waits, then submits once the connection returns', async ({
    studentPage, testTenant, request,
  }) => {
    test.setTimeout(60_000)
    const exam = await createExam(request, testTenant, 'Reliability offline exam')
    await bootInExam(studentPage, exam, testTenant)
    await enter(studentPage)
    await studentPage.locator(BOX).click()
    await studentPage.keyboard.type(ESSAY, { delay: 1 })

    await studentPage.context().setOffline(true)
    await expect(studentPage.getByText(/You are offline/)).toBeVisible()
    await studentPage.getByRole('button', { name: /Seal & Submit/ }).click()
    await confirmSeal(studentPage)
    await expect(studentPage.getByText(/will be submitted when the connection returns/)).toBeVisible()
    await studentPage.waitForTimeout(1500)
    expect(await rowsFor(request, testTenant, exam.id)).toHaveLength(0)

    await studentPage.context().setOffline(false)
    await expect(studentPage.getByRole('heading', { name: 'Collection Sealed' })).toBeVisible({ timeout: 30_000 })
    expect(await rowsFor(request, testTenant, exam.id)).toHaveLength(1)
  })

  test('two tabs on the same exam submit once, and the second is told calmly', async ({
    browser, testTenant, request,
  }) => {
    test.setTimeout(60_000)
    const exam = await createExam(request, testTenant, 'Reliability two tabs exam')
    const context = await browser.newContext({ storageState: studentStorageState(testTenant.baseURL, testTenant.student) })
    const [tabA, tabB] = [await context.newPage(), await context.newPage()]
    for (const tab of [tabA, tabB]) {
      await bootInExam(tab, exam, testTenant)
      await enter(tab)
    }
    await tabA.locator(BOX).click()
    await tabA.keyboard.type(ESSAY, { delay: 1 })
    await tabB.locator(BOX).click()
    await tabB.keyboard.type('A second attempt written in another tab, long enough to be sealed on its own too.', { delay: 1 })

    await tabA.getByRole('button', { name: /Seal & Submit/ }).click()
    await confirmSeal(tabA)
    await expect(tabA.getByRole('heading', { name: 'Collection Sealed' })).toBeVisible({ timeout: 20_000 })

    await tabB.getByRole('button', { name: /Seal & Submit/ }).click()
    await confirmSeal(tabB)
    await expect(tabB.getByRole('heading', { name: 'This collection was already submitted' })).toBeVisible({ timeout: 10_000 })
    await expect(tabB.getByText(/so this copy was not sent/)).toBeVisible()
    await expect(tabB.getByRole('button', { name: /Try again/ })).toHaveCount(0)

    const rows = await rowsFor(request, testTenant, exam.id)
    expect(rows).toHaveLength(1)
    const sealed = await (await request.get(`/bluebook/submissions/${rows[0].id}`, { headers: staffAuth(testTenant) })).json()
    expect(sealed.text).toContain(ESSAY)
    await context.close()
  })

  test('a tab opened after the seal says so before the student writes', async ({ studentPage, testTenant, request }) => {
    test.setTimeout(60_000)
    const exam = await createExam(request, testTenant, 'Reliability later tab exam')
    await bootInExam(studentPage, exam, testTenant)
    await writeAndSeal(studentPage)
    await expect(studentPage.getByRole('heading', { name: 'Collection Sealed' })).toBeVisible({ timeout: 20_000 })

    const later = await studentPage.context().newPage()
    await bootInExam(later, exam, testTenant)
    await enter(later)
    await expect(later.getByText(/You have already submitted this collection/)).toBeVisible()
    await expect(later.getByRole('button', { name: 'Already submitted' })).toBeDisabled()
    await expect(later.locator(BOX)).toHaveAttribute('readonly', '')
    expect(await rowsFor(request, testTenant, exam.id)).toHaveLength(1)
  })

  test("another student's unsent draft on this browser is never restored", async ({
    studentPage, testTenant, request,
  }) => {
    const exam = await createExam(request, testTenant, 'Reliability shared computer exam')
    const theirs = JSON.stringify({ content: 'SOMEONE ELSE WROTE THIS', answers: ['SOMEONE ELSE WROTE THIS'], seal: null, warnings: [] })
    await studentPage.addInitScript(([id, draft]) => {
      // Left behind by an earlier student, under the old shared key and under their own.
      if (!sessionStorage.getItem('seeded')) {
        localStorage.setItem('bb_draft_' + id, draft)
        localStorage.setItem('bb_draft_tenant:someone-else|' + id, draft)
        sessionStorage.setItem('seeded', '1')
      }
    }, [exam.id, theirs])
    await bootInExam(studentPage, exam, testTenant)
    await enter(studentPage)
    await expect(studentPage.locator(BOX)).toHaveValue('')
  })

  test('a browser that cannot keep a draft tells the student to keep the window open', async ({
    studentPage, testTenant, request,
  }) => {
    const exam = await createExam(request, testTenant, 'Reliability no storage exam')
    await studentPage.addInitScript(() => {
      const real = Storage.prototype.setItem
      Storage.prototype.setItem = function (k, v) {
        if (String(k).startsWith('bb_draft_')) throw new DOMException('full', 'QuotaExceededError')
        return real.call(this, k, v)
      }
    })
    await bootInExam(studentPage, exam, testTenant)
    await enter(studentPage)
    await studentPage.locator(BOX).click()
    await studentPage.keyboard.type('A few words.', { delay: 1 })
    await expect(studentPage.getByText(/cannot keep a copy of your writing/)).toBeVisible()
  })
})

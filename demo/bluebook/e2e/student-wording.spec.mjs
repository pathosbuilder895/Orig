/**
 * student-wording.spec.mjs: what a student reads should be plain, calm and
 * kind. Nothing accusatory, no threats, no rules restated as warnings, and
 * notes about leaving the exam window read as neutral notices.
 *
 * This walks the screens a student meets, in the states that carry the most
 * charged wording (every kind of note for the teacher, offline, a failed
 * seal, time running out with nothing written), and checks the visible text
 * against words that have no place in front of a student. It reads the page
 * a student sees, not the source, so a word in a comment cannot fail it and
 * a word assembled at run time cannot slip past it.
 */

import { isolatedTest as test, expect } from './fixtures/tenancy.mjs'

// Whole words or stems, matched case-insensitively against visible text.
const UNKIND = [
  /\bcheat/i, /\bviolat/i, /\bsuspicio/i, /\bprohibit/i, /\bforbid/i,
  /\bdetect/i, /\bfingerprint/i, /\blie detector/i, /\bmisconduct/i,
  /\bpenalt/i, /\bwarning/i, /\benforced\b/i, /\bnot permitted\b/i,
  /\bmust\b/i, /\bauthorship\b/i, /\bintegrity\b/i, /\bmonitor/i,
  /\bflagged\b/i, /\bwatched closely\b/i, /\bheld against\b/i,
]

function unkindIn(text) {
  return UNKIND.filter(re => re.test(text)).map(re => `${re} in: ${text.match(new RegExp(`.{0,40}${re.source}.{0,40}`, 'i'))[0]}`)
}

async function visibleText(page) {
  return page.evaluate(() => document.body.innerText)
}

async function createExam(request, testTenant, title, extra = {}) {
  const res = await request.post('/bluebook/exams', {
    headers: { Authorization: `Bearer ${testTenant.staff.token}` },
    data: {
      title, course: 'HIST 110', duration: 90, minWords: 8, maxWords: 600,
      prompt: 'What changed in 1848?', status: 'PUBLISHED', ...extra,
    },
  })
  expect(res.ok()).toBe(true)
  return res.json()
}

async function boot(page, exam, testTenant, extra = {}) {
  await page.addInitScript(([e, sid, more]) => {
    localStorage.setItem('bluebook_student_id', sid)
    window.BB_EXAM_CONFIG = {
      id: e.id, title: e.title, course: e.course, courseTitle: e.course, candidate: 'Wording Candidate',
      duration: 90, minWords: 8, maxWords: 600, prompt: e.prompt,
      blockAI: true, blockWeb: true, blockCopy: true, phoneBlk: true, spellChk: false, ...more,
    }
    Element.prototype.requestFullscreen = function () { return Promise.resolve() }
  }, [exam, testTenant.student.student_id, extra])
  await page.goto('/bluebook/')
  await page.waitForLoadState('networkidle')
}

const ESSAY = 'The revolutions of 1848 spread quickly and mostly failed, yet they changed what people expected of government.'

test.describe('Student-facing wording', () => {
  test('the briefing, the exam with every kind of note, and the sealed screen read calmly', async ({
    studentPage, testTenant, request,
  }) => {
    test.setTimeout(60_000)
    const exam = await createExam(request, testTenant, 'Wording exam')
    await boot(studentPage, exam, testTenant)
    await expect(studentPage.getByRole('button', { name: 'Begin Examination' })).toBeVisible()
    expect(unkindIn(await visibleText(studentPage))).toEqual([])

    await studentPage.getByRole('button', { name: 'Begin Examination' }).click()
    const box = studentPage.getByLabel('Your examination answer')
    await expect(box).toBeFocused()
    await studentPage.keyboard.type(ESSAY, { delay: 1 })

    // Every note the page can make for the teacher, one after another.
    await studentPage.evaluate(async () => {
      const pause = () => new Promise(r => setTimeout(r, 1600))   // past the 1.5s dedupe
      window.dispatchEvent(new Event('blur')); await pause()
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
      document.dispatchEvent(new Event('visibilitychange'))
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
      await pause()
      Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => null })
      document.dispatchEvent(new Event('fullscreenchange')); await pause()
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'p', ctrlKey: true, bubbles: true, cancelable: true })); await pause()
      const ta = document.querySelector('textarea')
      const dt = new DataTransfer(); dt.setData('text/plain', 'pasted')
      ta.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }))
    })
    await expect(studentPage.getByRole('heading', { name: /Notes for your teacher \(5\)/ })).toBeVisible()
    await studentPage.context().setOffline(true)
    await expect(studentPage.getByText(/You are offline/)).toBeVisible()
    expect(unkindIn(await visibleText(studentPage))).toEqual([])
    await studentPage.context().setOffline(false)

    studentPage.once('dialog', async d => {
      expect(unkindIn(d.message())).toEqual([])
      await d.accept()
    })
    await studentPage.getByRole('button', { name: 'Seal & Submit' }).click()
    await expect(studentPage.getByRole('heading', { name: 'Examination Sealed' })).toBeVisible({ timeout: 20_000 })
    expect(unkindIn(await visibleText(studentPage))).toEqual([])
  })

  test('a seal that could not be delivered is explained kindly, without server jargon', async ({
    studentPage, testTenant, request,
  }) => {
    const exam = await createExam(request, testTenant, 'Wording failure exam')
    await studentPage.route('**/bluebook/submissions', route => (route.request().method() === 'POST'
      ? route.fulfill({ status: 403, contentType: 'application/json', body: '{"detail":"Session does not match the submission\'s student_id."}' })
      : route.continue()))
    await boot(studentPage, exam, testTenant, { blockWeb: false })
    await studentPage.getByRole('button', { name: 'Begin Examination' }).click()
    await studentPage.keyboard.type(ESSAY, { delay: 1 })
    studentPage.once('dialog', d => d.accept())
    await studentPage.getByRole('button', { name: 'Seal & Submit' }).click()
    await expect(studentPage.getByRole('heading', { name: 'Your exam has not been submitted yet' })).toBeVisible({ timeout: 10_000 })
    await expect(studentPage.getByText(/Your writing is saved on this device/)).toBeVisible()
    const text = await visibleText(studentPage)
    expect(unkindIn(text)).toEqual([])
    // The server's own words are kept for the teacher, out of the student's way.
    expect(text).not.toMatch(/student_id/)
    await expect(studentPage.getByText(/Details for your teacher/)).toBeAttached()
  })

  test('time running out with nothing written says so plainly', async ({ studentPage, testTenant, request }) => {
    // An id the server does not hold: no session pins a 90-minute deadline,
    // so the local three-second clock runs out (exam-flow.spec.mjs does the same).
    const exam = { id: `wording-empty-${Date.now()}`, title: 'Wording empty exam', course: 'HIST 110', prompt: 'What changed in 1848?' }
    await boot(studentPage, exam, testTenant, { blockWeb: false, duration: 0.05 })
    await studentPage.getByRole('button', { name: 'Begin Examination' }).click()
    await expect(studentPage.getByRole('heading', { name: 'Time is up' })).toBeVisible({ timeout: 20_000 })
    await expect(studentPage.getByText(/Nothing was written in this booklet/)).toBeVisible()
    await expect(studentPage.getByRole('button', { name: /Try again/ })).toHaveCount(0)
    expect(unkindIn(await visibleText(studentPage))).toEqual([])
  })

  test('the public, sign-in, reset, invite and phone pages read calmly', async ({ page }) => {
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Your own words,')).toBeVisible()
    expect(unkindIn(await visibleText(page))).toEqual([])
    // The wordmark says the product's name, not the internal one.
    expect(await visibleText(page)).not.toMatch(/bluebook/i)

    await page.getByRole('button', { name: 'Sign in' }).first().click()
    await expect(page.getByLabel('Email')).toBeVisible()
    expect(unkindIn(await visibleText(page))).toEqual([])
    expect(await visibleText(page)).not.toMatch(/bluebook/i)
    await page.getByRole('button', { name: 'Forgot your password?' }).click()
    await expect(page.getByRole('button', { name: 'Email me a reset link' })).toBeVisible()
    expect(unkindIn(await visibleText(page))).toEqual([])

    await page.goto('/bluebook/?invite=not-a-real-code')
    await page.getByLabel('New password').fill('a-new-password-1')
    await page.getByLabel('Confirm password').fill('a-new-password-1')
    await page.getByRole('button', { name: 'Save and continue' }).click()
    await expect(page.getByText(/link/i).last()).toBeVisible()
    expect(unkindIn(await visibleText(page))).toEqual([])

    await page.goto('/bluebook/parked.html')
    await page.waitForLoadState('networkidle')
    expect(unkindIn(await visibleText(page))).toEqual([])
  })

  test("a student's home, sealed work and account read calmly", async ({ browser, testTenant, request }) => {
    const exam = await createExam(request, testTenant, 'Wording home exam')
    const s = testTenant.student
    const sealed = await request.post('/bluebook/submissions', {
      headers: { Authorization: `Bearer ${s.token}` },
      data: { exam_id: exam.id, student_id: s.student_id, candidate: 'Wording Student', exam_title: exam.title,
        word_count: 18, text: ESSAY, answers: [ESSAY], submission_uuid: `wording-${Date.now()}` },
    })
    expect(sealed.ok()).toBe(true)
    const context = await browser.newContext({ storageState: {
      cookies: [],
      origins: [{ origin: testTenant.baseURL, localStorage: [
        { name: 'original_session_token', value: s.token },
        { name: 'original_student_id', value: s.student_id },
        { name: 'original_role', value: 'student' },
        { name: 'original_tenant', value: s.tenant_id },
        { name: 'original_name', value: 'Wording Student' },
        { name: 'original_products', value: JSON.stringify(['bluebook']) },
      ] }],
    } })
    const page = await context.newPage()
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('heading', { name: /^Welcome/ })).toBeVisible()
    expect(unkindIn(await visibleText(page))).toEqual([])

    await page.getByRole('button', { name: /Read/ }).first().click()
    await expect(page.getByText(ESSAY)).toBeVisible()
    expect(unkindIn(await visibleText(page))).toEqual([])

    await page.getByRole('button', { name: 'Account' }).click()
    await expect(page.getByLabel('Current password')).toBeVisible()
    // A wrong current password says so, rather than "sign in again".
    await page.getByLabel('Current password').fill('not-my-password')
    await page.getByLabel('New password', { exact: true }).fill('a-new-password-1')
    await page.getByLabel('Confirm new password').fill('a-new-password-1')
    await page.getByRole('button', { name: 'Change password' }).click()
    await expect(page.getByText('Current password is incorrect.')).toBeVisible()
    expect(unkindIn(await visibleText(page))).toEqual([])
    await context.close()
  })

  test('the briefing and the landing page point students to the student notice', async ({
    studentPage, testTenant, request,
  }) => {
    const exam = await createExam(request, testTenant, 'Wording notice exam')
    await boot(studentPage, exam, testTenant)
    const link = studentPage.getByRole('link', { name: /What Collections keeps/ })
    await expect(link).toHaveAttribute('href', '../legal/student-notice.html')
    await expect(link).toHaveAttribute('target', '_blank')
    const res = await studentPage.request.get('/legal/student-notice.html')
    expect(res.ok()).toBe(true)

    const visitor = await studentPage.context().browser().newPage()
    await visitor.goto('/bluebook/')
    await expect(visitor.getByRole('link', { name: 'Student notice' })).toHaveAttribute('href', '../legal/student-notice.html')
    await visitor.close()
  })

  test('an exam that is closed or not yet open is explained kindly', async ({ studentPage, testTenant, request }) => {
    const exam = await createExam(request, testTenant, 'Wording closed exam')
    await boot(studentPage, exam, testTenant, { loaded: true, state: 'closed' })
    await expect(studentPage.getByText(/This exam has closed/)).toBeVisible()
    expect(unkindIn(await visibleText(studentPage))).toEqual([])
  })
})

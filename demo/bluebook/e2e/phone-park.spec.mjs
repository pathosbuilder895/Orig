/**
 * phone-park.spec.mjs — phone parking tied to the student's account
 * (Andrew, 2026-10-22). With the option on for a collection, the briefing
 * shows the student's own code and Begin waits; opening that code on a phone
 * (no sign-in) parks it and Begin unlocks. With it off, nothing changes.
 */
import { isolatedTest as test, test as sharedTest, expect } from './fixtures/tenancy.mjs'

const PHONE = { viewport: { width: 390, height: 780 }, isMobile: true, hasTouch: true }

async function createExam(request, testTenant, title, conditions) {
  const res = await request.post('/bluebook/exams', {
    headers: { Authorization: `Bearer ${testTenant.staff.token}` },
    data: { title, duration: 25, questions: ['Say something.'], status: 'ACTIVE', conditions },
  })
  expect(res.ok(), await res.text()).toBe(true)
  return res.json()
}

async function boot(page, exam, testTenant, extra) {
  await page.addInitScript(([e, sid, more]) => {
    localStorage.setItem('bluebook_student_id', sid)
    window.BB_EXAM_CONFIG = {
      id: e.id, title: e.title, candidate: 'Phone Candidate', duration: 25 * 60,
      questions: ['Say something.'], blockAI: true, blockWeb: false, blockCopy: true, ...more,
    }
  }, [exam, testTenant.student.student_id, extra])
  await page.goto('/bluebook/')
  await page.waitForLoadState('networkidle')
}

test('with phone parking on, Begin waits for the student\'s own phone', async ({ studentPage, testTenant, request, browser }) => {
  test.setTimeout(60_000)
  const exam = await createExam(request, testTenant, 'Phone exam', { phonePark: true, aiDetect: false })
  await boot(studentPage, exam, testTenant, { phonePark: true })
  const begin = studentPage.getByRole('button', { name: 'Begin Examination' })
  await expect(studentPage.getByRole('heading', { name: 'Park your phone' })).toBeVisible()
  await expect(studentPage.getByRole('img', { name: /Your own code for parking your phone/ })).toBeVisible()
  await expect(begin).toBeDisabled()

  // The phone opens the student's own code: no sign-in.
  const r = await request.get(`/bluebook/me/exams/${exam.id}/phone-park`, {
    headers: { Authorization: `Bearer ${testTenant.student.token}` },
  })
  const { qr_url } = await r.json()
  const phoneCtx = await browser.newContext(PHONE)
  const phone = await phoneCtx.newPage()
  await phone.goto(new URL(qr_url).pathname + new URL(qr_url).search)
  await expect(phone.getByText('Parked for your account on this exam only.', { exact: false })).toBeVisible()
  await expect(phone.locator('#status-text')).toHaveText('Parked')
  expect(phone.url()).not.toContain('s=')
  await phoneCtx.close()

  await expect(studentPage.getByText('Your phone is parked.', { exact: false })).toBeVisible({ timeout: 10_000 })
  await expect(begin).toBeEnabled()
})

test('with phone parking off, the briefing is unchanged', async ({ studentPage, testTenant, request }) => {
  const exam = await createExam(request, testTenant, 'No phone exam', { aiDetect: false })
  await boot(studentPage, exam, testTenant, {})
  await expect(studentPage.getByRole('button', { name: 'Begin Examination' })).toBeEnabled()
  await expect(studentPage.getByRole('heading', { name: 'Park your phone' })).toHaveCount(0)
})

sharedTest('the teacher sees who is waiting and can let a student begin without a phone', async ({ staffPage, workerTenant, request }) => {
  const title = `Phones ${Date.now()}`
  const res = await request.post('/bluebook/exams', {
    headers: { Authorization: `Bearer ${workerTenant.staff.token}` },
    data: { title, duration: 25, questions: ['Say something.'], status: 'ACTIVE', conditions: { phonePark: true, aiDetect: false } },
  })
  const exam = await res.json()
  await staffPage.goto(`/bluebook/#exam/${exam.id}`)
  await expect(staffPage.getByRole('heading', { name: 'Phone parking' })).toBeVisible({ timeout: 10_000 })
  const allow = staffPage.getByRole('button', { name: 'Let begin without phone' }).first()
  await expect(allow).toBeVisible()
  staffPage.once('dialog', d => d.accept('Left it at home'))
  await allow.click()
  await expect(staffPage.getByText(/Allowed .*Left it at home/).first()).toBeVisible()
})

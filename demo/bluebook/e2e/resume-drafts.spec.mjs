/**
 * resume-drafts.spec.mjs — closing the browser or a lapsed sign-in never
 * loses what was typed (Andrew, 2026-10-21):
 *   - the New collection form is kept per teacher, restored, cleared on Publish;
 *   - the "Share a past paper" text is kept per student until sent;
 *   - a teacher is warned about 10 minutes before the 8-hour sign-in ends;
 *   - a student whose seal is refused for a lapsed sign-in is sent to sign
 *     in, and the same answers are submitted after signing back in.
 */
import { test, expect } from '@playwright/test'
import { isolatedTest } from './fixtures/tenancy.mjs'
import { staffStorageState } from './fixtures/api-setup.mjs'

const uid = () => `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`

async function signUpTeacher(page, id) {
  await page.goto('/bluebook/')
  await page.getByRole('button', { name: 'Create a free workspace' }).click()
  await page.getByLabel('Your name').fill('E2E Teacher')
  await page.getByLabel('Email').fill(`rd-teacher-${id}@e2e.test`)
  await page.getByLabel('Password').fill('e2e-teacher-pass-1')
  await page.locator('#bbSignupTerms').check()
  await page.getByRole('button', { name: 'Create workspace' }).click()
  await expect(page.getByRole('button', { name: 'Overview', exact: true })).toBeVisible({ timeout: 10_000 })
}

// A workspace with Original on (the past-paper form needs it), as the alpha has.
async function setupClass(browser, T) {
  const id = uid()
  const tctx = await browser.newContext({ storageState: staffStorageState(T.baseURL, T.staff) })
  const teacher = await tctx.newPage()
  await teacher.goto('/bluebook/')
  await expect(teacher.getByRole('button', { name: 'Courses', exact: true })).toBeVisible({ timeout: 10_000 })
  await teacher.getByRole('button', { name: 'Courses', exact: true }).click()
  await teacher.getByRole('button', { name: '+ New course' }).click()
  await teacher.getByLabel('Course name').fill('Alpha')
  await teacher.getByRole('button', { name: 'Create course' }).click()
  const email = `rd-student-${id}@e2e.test`
  await teacher.locator('#rosterInput').fill(`Ann Student, ${email}`)
  await teacher.getByRole('button', { name: 'Add students' }).click()
  const linkBox = teacher.getByLabel('Invite link').first()
  await expect(linkBox).toBeVisible({ timeout: 10_000 })
  const invite = new URL(await linkBox.inputValue())
  const title = `Resume exam ${id}`
  await teacher.getByRole('button', { name: 'Collections', exact: true }).click()
  await teacher.getByRole('button', { name: '+ New collection' }).click()
  await teacher.locator('#neTitle').fill(title)
  await teacher.locator('#neDuration').fill('30')
  await teacher.locator('#nePrompt0').fill('Say something.')
  await teacher.getByRole('button', { name: 'Publish Collection' }).click()
  await expect(teacher.getByText('Collection Created')).toBeVisible({ timeout: 10_000 })
  const sctx = await browser.newContext()
  const student = await sctx.newPage()
  await student.addInitScript(() => { Element.prototype.requestFullscreen = () => Promise.resolve() })
  await student.goto(invite.pathname + invite.search)
  await student.getByLabel('New password').fill('e2e-student-pass-1')
  await student.getByLabel('Confirm password').fill('e2e-student-pass-1')
  await student.getByRole('checkbox').check()
  await student.getByRole('button', { name: 'Save and continue' }).click()
  await expect(student.getByText(title)).toBeVisible({ timeout: 10_000 })
  return { teacher, student, email, title }
}

test('the New collection form survives a reload and is cleared by Publish', async ({ page }) => {
  test.setTimeout(90_000)
  await signUpTeacher(page, uid())
  await page.getByRole('button', { name: 'Collections', exact: true }).click()
  await page.getByRole('button', { name: '+ New collection' }).click()
  await page.locator('#neTitle').fill('Kept title')
  await page.locator('#nePrompt0').fill('Kept prompt')
  await page.waitForTimeout(300)
  await page.reload()
  await page.getByRole('button', { name: 'Collections', exact: true }).click().catch(() => {})
  if (!(await page.locator('#neTitle').isVisible())) await page.getByRole('button', { name: '+ New collection' }).click()
  await expect(page.locator('#neTitle')).toHaveValue('Kept title')
  await expect(page.locator('#nePrompt0')).toHaveValue('Kept prompt')
  await expect(page.getByTestId('draft-restored')).toBeVisible()
  await page.getByRole('button', { name: 'Publish Collection' }).click()
  await expect(page.getByText('Collection Created')).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('button', { name: '+ New collection' })).toBeVisible({ timeout: 10_000 })
  await page.getByRole('button', { name: '+ New collection' }).click()
  await expect(page.locator('#neTitle')).toHaveValue('')
  await expect(page.getByTestId('draft-restored')).toHaveCount(0)
})

test('a teacher is warned about 10 minutes before the sign-in ends', async ({ page }) => {
  test.setTimeout(60_000)
  await page.clock.install()
  await signUpTeacher(page, uid())
  await expect(page.getByTestId('signin-expiring')).toHaveCount(0)
  await page.clock.fastForward('07:51:00')
  await expect(page.getByTestId('signin-expiring')).toBeVisible()
  await expect(page.getByTestId('signin-expiring')).toContainText('about 10 minutes')
})

isolatedTest('past-paper text is kept until sent, and a lapsed seal resumes after sign-in', async ({ browser, testTenant }) => {
  isolatedTest.setTimeout(150_000)
  const { student, email, title } = await setupClass(browser, testTenant)

  const paper = 'A paper I wrote last year about the rivers near our town and how they flood each spring. '.repeat(4).trim()
  const sec = student.getByRole('form', { name: 'Share a past paper' })
  await expect(sec).toBeVisible({ timeout: 10_000 })
  await sec.getByLabel('Or paste the text').fill(paper)
  await sec.getByLabel('Title (optional)').fill('Rivers')
  await student.waitForTimeout(300)
  await student.reload()
  const sec2 = student.getByRole('form', { name: 'Share a past paper' })
  await expect(sec2.getByLabel('Or paste the text')).toHaveValue(paper, { timeout: 10_000 })
  await expect(sec2.getByLabel('Title (optional)')).toHaveValue('Rivers')
  await sec2.getByRole('button', { name: 'Share paper' }).click()
  await expect(sec2.getByRole('status')).toHaveText(/Received/, { timeout: 15_000 })
  await student.reload()
  await expect(student.getByRole('form', { name: 'Share a past paper' }).getByLabel('Or paste the text')).toHaveValue('', { timeout: 10_000 })

  await student.getByRole('row', { name: new RegExp(title) }).getByRole('button', { name: 'Open' }).click()
  await student.getByRole('button', { name: /Begin Examination|Resume Examination/ }).click()
  const answer = 'These words must reach the teacher after signing back in.'
  await student.getByLabel('Your examination answer').focus()
  await student.keyboard.type(answer, { delay: 1 })
  // The sign-in lapses while writing.
  await student.evaluate(() => localStorage.setItem('original_session_token', 'expired.token'))
  student.once('dialog', d => d.accept())
  await student.locator('button', { hasText: /Seal & Submit|Sealing/ }).click()
  await expect(student.getByTestId('signin-expired')).toContainText('finish submitting your exam', { timeout: 30_000 })
  await student.locator('#bbLoginEmail').fill(email)
  await student.locator('#bbLoginPass').fill('e2e-student-pass-1')
  await student.getByRole('button', { name: 'Sign in' }).click()
  // Signing back in reopens this exam; Resume finishes the confirmed seal.
  await student.getByRole('button', { name: 'Resume Examination' }).click({ timeout: 15_000 })
  await expect(student.getByText('Examination Sealed')).toBeVisible({ timeout: 30_000 })
})

/**
 * teacher-view-refresh.spec.mjs — alpha bug 2026-10-20 (live pilot 859436e).
 *
 * The teacher reported (1) no way to see a student's work from Students and
 * (2) after a refresh, "No examinations yet" and no submissions. Cause: one
 * browser holds one sign-in in localStorage; redeeming a student invite in
 * the teacher's browser replaced the teacher session, so a refresh opened the
 * student home. These pin the fixes:
 *   - separate browsers: teacher refresh on Students stays on Students and
 *     "View work" shows the sealed answer;
 *   - same browser: the student link warns before signing the teacher out,
 *     and the teacher tab says it was signed out instead of showing empties.
 */
import { test, expect } from '@playwright/test'

const uid = () => `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`

async function setup(browser) {
  const id = uid()
  const tctx = await browser.newContext()
  const teacher = await tctx.newPage()
  await teacher.goto('/bluebook/')
  await teacher.getByRole('button', { name: 'Create a free workspace' }).click()
  await teacher.getByLabel('Your name').fill('E2E Teacher')
  await teacher.getByLabel('Email').fill(`tv-teacher-${id}@e2e.test`)
  await teacher.getByLabel('Password').fill('e2e-teacher-pass-1')
  await teacher.locator('#bbSignupTerms').check()
  await teacher.getByRole('button', { name: 'Create workspace' }).click()
  await expect(teacher.getByRole('button', { name: 'Overview', exact: true })).toBeVisible({ timeout: 10_000 })
  await teacher.getByRole('button', { name: 'Courses', exact: true }).click()
  await teacher.getByRole('button', { name: '+ New course' }).click()
  await teacher.getByLabel('Course name').fill('Alpha')
  await teacher.getByRole('button', { name: 'Create course' }).click()
  await teacher.locator('#rosterInput').fill(`Ann Student, tv-student-${id}@e2e.test`)
  await teacher.getByRole('button', { name: 'Add students' }).click()
  const linkBox = teacher.getByLabel('Invite link').first()
  await expect(linkBox).toBeVisible({ timeout: 10_000 })
  const invite = new URL(await linkBox.inputValue())
  const title = `Refresh exam ${id}`
  await teacher.getByRole('button', { name: 'Examinations', exact: true }).click()
  await teacher.getByRole('button', { name: '+ New examination' }).click()
  await teacher.locator('#neTitle').fill(title)
  await teacher.locator('#neDuration').fill('30')
  await teacher.locator('#neMinWords').fill('3')
  await teacher.locator('#nePrompt0').fill('Say something.')
  await teacher.getByRole('button', { name: 'Publish Examination' }).click()
  await expect(teacher.getByText('Examination Created')).toBeVisible({ timeout: 10_000 })
  return { tctx, teacher, invite: invite.pathname + invite.search, title }
}

async function redeem(page) {
  await page.getByLabel('New password').fill('e2e-student-pass-1')
  await page.getByLabel('Confirm password').fill('e2e-student-pass-1')
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Save and continue' }).click()
}

test('separate browsers: teacher refresh keeps Students and shows the student\'s sealed work', async ({ browser }) => {
  test.setTimeout(120_000)
  const { teacher, invite, title } = await setup(browser)
  const sctx = await browser.newContext()
  const student = await sctx.newPage()
  await student.addInitScript(() => { Element.prototype.requestFullscreen = () => Promise.resolve() })
  await student.goto(invite)
  await expect(student.getByTestId('invite-signs-out-teacher')).toHaveCount(0)
  await redeem(student)
  await expect(student.getByText(title)).toBeVisible({ timeout: 10_000 })
  await student.getByRole('button', { name: 'Open' }).click()
  await student.getByRole('button', { name: /Begin Examination|Resume Examination/ }).click()
  const answer = 'Refresh must never hide this sealed answer.'
  await student.getByLabel('Your examination answer').focus()
  await student.keyboard.type(answer, { delay: 1 })
  student.once('dialog', d => d.accept())
  await student.locator('button', { hasText: /Seal & Submit|Sealing/ }).click()
  await expect(student.getByText('Examination Sealed')).toBeVisible({ timeout: 30_000 })

  await teacher.getByRole('button', { name: 'Students', exact: true }).click()
  await expect(teacher).toHaveURL(/#students$/)
  await teacher.reload()
  await expect(teacher.getByRole('heading', { name: 'Students' })).toBeVisible({ timeout: 10_000 })
  await expect(teacher.getByText('Ann Student')).toBeVisible({ timeout: 10_000 })
  await teacher.getByRole('button', { name: 'View work' }).click()
  await teacher.getByRole('button', { name: 'Read & mark' }).click()
  await expect(teacher.getByText(answer)).toBeVisible({ timeout: 10_000 })
  // The exams list survives a refresh too.
  await teacher.getByRole('button', { name: 'Examinations', exact: true }).click()
  await teacher.reload()
  await expect(teacher.getByText(title)).toBeVisible({ timeout: 10_000 })
})

test('same browser: student invite warns, teacher tab reports the sign-out instead of empty pages', async ({ browser }) => {
  test.setTimeout(120_000)
  const { tctx, teacher, invite } = await setup(browser)
  await teacher.getByRole('button', { name: 'Students', exact: true }).click()
  const studentTab = await tctx.newPage()
  await studentTab.goto(invite)
  await expect(studentTab.getByTestId('invite-signs-out-teacher')).toBeVisible()
  await redeem(studentTab)
  await expect(studentTab.getByText(/No examinations|Refresh exam/).first()).toBeVisible({ timeout: 10_000 })
  await expect(teacher.getByTestId('session-switched')).toBeVisible({ timeout: 10_000 })
  await expect(teacher.getByText(/private \(incognito\) window/)).toBeVisible()
})

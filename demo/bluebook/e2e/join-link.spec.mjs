/**
 * join-link.spec.mjs — the forwardable course sign-up link, through the UI.
 *
 * A teacher turns on a course's sign-up link and copies it. A student who
 * was never added by email opens it, must tick the student-notice consent
 * box, creates their own account and lands on the course. Replacing the
 * link kills the old one.
 */

import { test, expect } from '@playwright/test'

const uid = () => `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`

test('teacher turns on a sign-up link; a student uses it to join with consent', async ({ browser }) => {
  test.setTimeout(90_000)
  const id = uid()
  const course = `Join Link Ethics ${id}`

  // ── Teacher: sign up, make a course, turn the link on ──────────────────
  const tctx = await browser.newContext({ permissions: ['clipboard-read', 'clipboard-write'] })
  const teacher = await tctx.newPage()
  await teacher.goto('/bluebook/')
  await teacher.getByRole('button', { name: 'Create a free workspace' }).click()
  await teacher.getByLabel('Your name').fill('Link Teacher')
  await teacher.getByLabel('Email').fill(`teacher-${id}@e2e.test`)
  await teacher.getByLabel('Password').fill('e2e-teacher-pass-1')
  await teacher.locator('#bbSignupTerms').check()
  await teacher.getByRole('button', { name: 'Create workspace' }).click()
  await expect(teacher.getByRole('button', { name: 'Overview', exact: true })).toBeVisible({ timeout: 10_000 })
  await teacher.getByRole('button', { name: 'Courses', exact: true }).click()
  await teacher.getByRole('button', { name: '+ New course' }).click()
  await teacher.getByLabel('Course name').fill(course)
  await teacher.getByRole('button', { name: 'Create course' }).click()
  await expect(teacher.getByRole('heading', { name: course })).toBeVisible({ timeout: 10_000 })

  await expect(teacher.getByRole('heading', { name: 'Sign-up link' })).toBeVisible()
  await teacher.getByRole('button', { name: 'Turn on sign-up link' }).click()
  const box = teacher.getByLabel('Sign-up link')
  await expect(box).toBeVisible({ timeout: 10_000 })
  const joinUrl = await box.inputValue()
  expect(joinUrl).toMatch(/^https?:\/\/.+\/bluebook\/\?join=/)

  // ── Student: open the link, consent is required ────────────────────────
  const sctx = await browser.newContext()
  const student = await sctx.newPage()
  await student.goto(joinUrl)
  await expect(student.getByTestId('join-course')).toContainText(course)
  await expect(student.getByTestId('join-course')).toContainText('Link Teacher')
  await student.getByLabel('Your name').fill('Forwarded Student')
  await student.getByLabel('Email').fill(`student-${id}@e2e.test`)
  await student.getByLabel('Password', { exact: true }).fill('e2e-student-pass-1')
  await student.getByLabel('Confirm password').fill('e2e-student-pass-1')
  await student.getByRole('button', { name: 'Create account and join' }).click()
  await expect(student.getByText(/tick the box/i)).toBeVisible()
  await student.locator('#bbJoinTerms').check()
  await student.getByRole('button', { name: 'Create account and join' }).click()
  // Signed in and on the course: the link code has left the address bar.
  await expect(student.getByRole('heading', { name: 'Welcome, Forwarded Student.' })).toBeVisible({ timeout: 10_000 })
  await expect(student.getByText(course).first()).toBeVisible()
  expect(student.url()).not.toContain('join=')

  // ── Teacher: replace the link; the old one stops working ──────────────
  teacher.once('dialog', d => d.accept())
  await teacher.getByRole('button', { name: 'Replace link' }).click()
  await expect(box).not.toHaveValue(joinUrl, { timeout: 10_000 })
  const other = await (await browser.newContext()).newPage()
  await other.goto(joinUrl)
  await expect(other.getByRole('alert')).toContainText('not active')

  await tctx.close()
  await sctx.close()
})

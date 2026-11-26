/**
 * server-draft.spec.mjs — a student's unsealed draft is also kept on the
 * server, so a sitting resumes from another browser (Andrew, 2026-10-21).
 * After the seal the draft is gone and cannot be saved again.
 */
import { test, expect } from '@playwright/test'
import { confirmSeal } from './fixtures/seal.mjs'

const uid = () => `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`
const PASS = 'e2e-student-pass-1'

async function setup(browser) {
  const id = uid()
  const tctx = await browser.newContext()
  const teacher = await tctx.newPage()
  await teacher.goto('/bluebook/')
  await teacher.getByRole('button', { name: 'Create a free workspace' }).click()
  await teacher.getByLabel('Your name').fill('E2E Teacher')
  await teacher.getByLabel('Email').fill(`sd-teacher-${id}@e2e.test`)
  await teacher.getByLabel('Password').fill('e2e-teacher-pass-1')
  await teacher.locator('#bbSignupTerms').check()
  await teacher.getByRole('button', { name: 'Create workspace' }).click()
  await expect(teacher.getByRole('button', { name: 'Overview', exact: true })).toBeVisible({ timeout: 10_000 })
  await teacher.getByRole('button', { name: 'Courses', exact: true }).click()
  await teacher.getByRole('button', { name: '+ New course' }).click()
  await teacher.getByLabel('Course name').fill('Alpha')
  await teacher.getByRole('button', { name: 'Create course' }).click()
  const email = `sd-student-${id}@e2e.test`
  await teacher.locator('#rosterInput').fill(`Ann Student, ${email}`)
  await teacher.getByRole('button', { name: 'Add students' }).click()
  const linkBox = teacher.getByLabel('Invite link').first()
  await expect(linkBox).toBeVisible({ timeout: 10_000 })
  const invite = new URL(await linkBox.inputValue())
  const title = `Server draft ${id}`
  await teacher.getByRole('button', { name: 'Collections', exact: true }).click()
  await teacher.getByRole('button', { name: '+ New collection' }).click()
  await teacher.locator('#neTitle').fill(title)
  await teacher.locator('#neDuration').fill('30')
  await teacher.locator('#nePrompt0').fill('Say something.')
  await teacher.getByRole('button', { name: 'Publish Collection' }).click()
  await expect(teacher.getByText('Collection Created')).toBeVisible({ timeout: 10_000 })
  return { email, title, invite: invite.pathname + invite.search }
}

async function studentPage(browser) {
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  await page.addInitScript(() => { Element.prototype.requestFullscreen = () => Promise.resolve() })
  return { ctx, page }
}

test('an unsealed draft written in one browser opens in another, and is gone after the seal', async ({ browser }) => {
  test.setTimeout(150_000)
  const { email, title, invite } = await setup(browser)

  // Browser A: join, start writing, close the page.
  const A = await studentPage(browser)
  await A.page.goto(invite)
  await A.page.getByLabel('New password').fill(PASS)
  await A.page.getByLabel('Confirm password').fill(PASS)
  await A.page.getByRole('checkbox').check()
  await A.page.getByRole('button', { name: 'Save and continue' }).click()
  await A.page.getByRole('row', { name: new RegExp(title) }).getByRole('button', { name: 'Open' }).click({ timeout: 10_000 })
  await A.page.getByRole('button', { name: /Begin writing|Resume writing/ }).click()
  const words = 'Written on the first computer and carried to the second.'
  await A.page.getByLabel('Your answer', { exact: true }).focus()
  await A.page.keyboard.type(words, { delay: 1 })
  const saved = A.page.waitForResponse(r => r.url().includes('/draft') && r.request().method() === 'PUT')
  await A.page.evaluate(() => window.dispatchEvent(new Event('pagehide')))
  expect((await saved).status()).toBe(200)
  await A.ctx.close()

  // Browser B: sign in, open the same exam: the writing is there.
  const B = await studentPage(browser)
  await B.page.goto('/bluebook/')
  await B.page.getByRole('button', { name: /^Sign in$/ }).first().click()
  await B.page.locator('#bbLoginEmail').fill(email)
  await B.page.locator('#bbLoginPass').fill(PASS)
  await B.page.getByRole('button', { name: 'Sign in' }).last().click()
  // Signing in resumes at the exam's briefing (resume-location.jsx), or the
  // student opens it from their list.
  const begin = B.page.getByRole('button', { name: /Begin writing|Resume writing/ })
  const openRow = B.page.getByRole('row', { name: new RegExp(title) }).getByRole('button', { name: /^(Open|Resume)$/ })
  await expect(begin.or(openRow)).toBeVisible({ timeout: 10_000 })
  if (!(await begin.isVisible())) await openRow.click()
  await begin.click()
  const box = B.page.getByLabel('Your answer', { exact: true })
  await expect(box).toHaveValue(words, { timeout: 10_000 })
  await B.page.locator('button', { hasText: /Seal & Submit|Sealing/ }).click()
  await confirmSeal(B.page)
  await expect(B.page.getByText('Collection Sealed')).toBeVisible({ timeout: 30_000 })

  // After the seal: no draft, and a save is refused.
  const examId = await B.page.evaluate(async (t) => {
    const tok = localStorage.getItem('original_session_token')
    const r = await fetch('/bluebook/me/exams', { headers: { Authorization: 'Bearer ' + tok } })
    const j = await r.json()
    const list = Array.isArray(j) ? j : (j.exams || [])
    return (list.find(e => (e.title || '').includes(t)) || {}).exam_id
  }, title)
  expect(examId).toBeTruthy()
  const after = await B.page.evaluate(async (id) => {
    const h = { Authorization: 'Bearer ' + localStorage.getItem('original_session_token'), 'Content-Type': 'application/json' }
    const g = await (await fetch(`/bluebook/exams/${id}/draft`, { headers: h })).json()
    const p = await fetch(`/bluebook/exams/${id}/draft`, { method: 'PUT', headers: h, body: JSON.stringify({ content: 'x', answers: ['x'], client_saved_at: Date.now() }) })
    return { g, put: p.status }
  }, examId)
  expect(after.g).toEqual({ draft: null, submitted: true })
  expect(after.put).toBe(409)
})

/**
 * original-switch.spec.mjs — Original switched on or off while a student is
 * mid-exam.
 *
 * The operator can turn Original on or off for a workspace at any time
 * (scripts/set_products.py, or PATCH /tenants/{id}), and any home-page load
 * refreshes the products a browser has stored. A sitting decides whether it
 * goes to Original once, when the student enters the exam, and keeps that
 * decision in its draft:
 *
 *  - Switched OFF mid-exam: the sitting still holds Original, so the seal
 *    calls Original's score route (the seal only compares; it never writes a
 *    baseline), which now answers 403. The seal must treat that as "this
 *    workspace no longer holds Original" and record the submission like a
 *    Bluebook-only workspace does, instead of retrying three times and
 *    leaving the exam unsealed.
 *  - Switched ON mid-exam: the student was told their writing would not be
 *    compared, so the seal must not call Original at all, even after another
 *    tab has stored the new products.
 *
 * Needs MAINTENANCE_TOKEN set to the server's value (staff registration and
 * the guarded tenant PATCH send it as X-Guard-Token).
 */

import { test, expect } from '@playwright/test'
import { createCourse, provisionStaff, provisionTenantWithStaff } from './fixtures/api-setup.mjs'

const uid = () => `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`

const COMPARED_LINE = 'After you submit, your writing is compared with your own past work'
const CONTEXT_LINE = 'Session duration and coarse writing information are noted as context, not proof of authorship'

// A workspace (the fixture creates it with both products), its operator, and
// an open exam with one invited student.
async function provisionExam(request, { examTitle, question, id }) {
  const { tenant, staff } = await provisionTenantWithStaff(request)
  const operator = await provisionStaff(request, {
    tenantId: tenant.tenant_id, role: 'operator', name: 'E2E Operator',
  })
  const teacher = { Authorization: `Bearer ${staff.token}` }
  const course = await createCourse(request, staff.token, { name: `Switch course ${id}` })
  const exam = await request.post('/bluebook/exams', {
    headers: teacher,
    data: {
      title: examTitle, course: course.code, course_id: course.id,
      duration: 30, minWords: 5, prompt: question, status: 'ACTIVE',
    },
  })
  expect(exam.status(), await exam.text()).toBe(201)
  const examId = (await exam.json()).id
  const added = await request.post(`/bluebook/courses/${encodeURIComponent(course.id)}/students`, {
    headers: teacher,
    data: { students: [{ email: `student-${id}@e2e.test`, name: 'E2E Student' }] },
  })
  expect(added.status(), await added.text()).toBe(200)
  const invitePath = (await added.json()).students[0].invite_path
  expect(invitePath).toContain('invite=')
  return { tenant, operator, teacher, examId, invitePath }
}

// The operator switches the workspace's products (PATCH /tenants/{id}).
async function setProducts(request, { tenant, operator }, products) {
  const patched = await request.patch(`/tenants/${encodeURIComponent(tenant.tenant_id)}`, {
    headers: {
      Authorization: `Bearer ${operator.token}`,
      ...(process.env.MAINTENANCE_TOKEN ? { 'X-Guard-Token': process.env.MAINTENANCE_TOKEN } : {}),
    },
    data: { products },
  })
  expect(patched.status(), await patched.text()).toBe(200)
  expect((await patched.json()).products).toEqual(products)
}

async function newStudentPage(ctx) {
  const page = await ctx.newPage()
  await page.addInitScript(() => {
    // chromium-headless rejects requestFullscreen; the exam must not care.
    Element.prototype.requestFullscreen = function () { return Promise.resolve() }
  })
  return page
}

async function redeemInvite(student, invitePath, examTitle) {
  await student.goto(invitePath)
  await student.getByLabel('New password').fill('e2e-student-pass-1')
  await student.getByLabel('Confirm password').fill('e2e-student-pass-1')
  await student.getByRole('button', { name: 'Save and continue' }).click()
  await expect(student.getByText(examTitle)).toBeVisible({ timeout: 10_000 })
}

const storedProductsOf = page => page.evaluate(() => JSON.parse(localStorage.getItem('original_products')))

async function sealAnswer(student, answer) {
  const box = student.getByLabel('Your examination answer')
  await box.focus()
  await student.keyboard.type(answer, { delay: 1 })
  student.once('dialog', d => d.accept())
  const [sealRes] = await Promise.all([
    student.waitForResponse(
      r => r.url().endsWith('/bluebook/submissions') && r.request().method() === 'POST',
      { timeout: 30_000 },
    ),
    student.locator('button', { hasText: /Seal & Submit|Sealing/ }).click(),
  ])
  return sealRes
}

test('a seal still lands when Original is switched off mid-exam', async ({ browser, request }) => {
  test.setTimeout(120_000)
  const id = uid()
  const examTitle = `Switch exam ${id}`
  const question = 'Is courage a mean between two vices?'
  const answer = 'Courage sits between cowardice and rashness, as Aristotle argues in Book Three.'

  // A workspace that holds Original (the fixture sends both products).
  const ws = await provisionExam(request, { examTitle, question, id })

  // ── Student: sign in, open the exam while the workspace holds Original ──
  const ctx = await browser.newContext()
  const student = await newStudentPage(ctx)
  const originalCalls = []
  student.on('response', r => {
    const path = new URL(r.url()).pathname
    if (/^\/students\//.test(path)) originalCalls.push({ path, status: r.status() })
  })
  await redeemInvite(student, ws.invitePath, examTitle)
  const storedProducts = () => storedProductsOf(student)
  expect((await storedProducts()).sort()).toEqual(['bluebook', 'original'])
  await student.getByRole('button', { name: 'Open' }).click()
  await expect(student.getByText('Preliminary Instructions')).toBeVisible({ timeout: 10_000 })
  await student.getByRole('button', { name: /Begin Examination|Resume Examination/ }).click()
  const box = student.getByLabel('Your examination answer')
  await expect(box).toBeVisible({ timeout: 10_000 })

  // ── Operator: switch the workspace to Bluebook only ─────────────────────
  await setProducts(request, ws, ['bluebook'])

  // ── Student: write and seal; the page still believes Original is on ────
  const sealRes = await sealAnswer(student, answer)
  expect(sealRes.status()).toBe(201)
  const sealBody = sealRes.request().postDataJSON()
  expect(sealBody.stylometric).toBeNull()
  expect(sealBody.ai_score).toBeNull()
  expect(sealBody.status).toBe('SUBMITTED')
  await expect(student.getByText('Examination Sealed')).toBeVisible({ timeout: 30_000 })
  await expect(student.getByText('✓ Delivered to your teacher')).toBeVisible()
  // The seal did try Original (the page believed it was on) and was refused.
  expect(originalCalls.some(c => c.path.endsWith('/score') && c.status === 403)).toBe(true)
  expect(originalCalls.every(c => c.status === 403)).toBe(true)
  // ...and this page has stopped believing it.
  expect(await storedProducts()).toEqual(['bluebook'])

  // ── The teacher has the submission ───────────────────────────────────────
  const subs = await request.get('/bluebook/submissions', { headers: ws.teacher })
  expect(subs.status(), await subs.text()).toBe(200)
  const mine = (await subs.json()).submissions.filter(s => s.exam_id === ws.examId)
  expect(mine).toHaveLength(1)
  expect(mine[0].status).toBe('SUBMITTED')
  expect(mine[0].stylometric ?? null).toBeNull()

  await ctx.close()
})

test('a sitting begun without Original is not compared when Original is switched on', async ({ browser, request }) => {
  test.setTimeout(120_000)
  const id = uid()
  const examTitle = `Switch-on exam ${id}`
  const question = 'Is temperance a virtue of the appetites alone?'
  const answer = 'Temperance orders the appetites, but Aristotle also ties it to the reasoning part of the soul.'

  // A Bluebook-only workspace.
  const ws = await provisionExam(request, { examTitle, question, id })
  await setProducts(request, ws, ['bluebook'])

  // ── Student: sign in and begin the exam; the briefing promises no comparison ──
  const ctx = await browser.newContext()
  const student = await newStudentPage(ctx)
  let switched = false
  const callsAfterSwitch = []
  student.on('request', r => {
    const path = new URL(r.url()).pathname
    if (switched && /^\/students\//.test(path)) callsAfterSwitch.push(path)
  })
  await redeemInvite(student, ws.invitePath, examTitle)
  expect(await storedProductsOf(student)).toEqual(['bluebook'])
  await student.getByRole('button', { name: 'Open' }).click()
  await expect(student.getByText('Preliminary Instructions')).toBeVisible({ timeout: 10_000 })
  await expect(student.getByText('Enforced Conditions')).toBeVisible()
  await expect(student.getByText(COMPARED_LINE)).toHaveCount(0)
  await expect(student.getByText(CONTEXT_LINE)).toHaveCount(0)
  await student.getByRole('button', { name: /Begin Examination|Resume Examination/ }).click()
  await expect(student.getByLabel('Your examination answer')).toBeVisible({ timeout: 10_000 })
  // The sitting's decision is on this device before anything is written.
  const decisions = () => student.evaluate(() => Object.keys(localStorage)
    .filter(k => k.startsWith('bb_draft_'))
    .map(k => JSON.parse(localStorage.getItem(k)).seal.withOriginal))
  await expect.poll(decisions).toEqual([false])

  // ── Operator: switch Original on for the workspace ───────────────────────
  await setProducts(request, ws, ['bluebook', 'original'])
  switched = true

  // ── Student: the home page in another tab stores the new products ───────
  const home = await newStudentPage(ctx)
  await home.goto('/bluebook/')
  await expect(home.getByText(examTitle)).toBeVisible({ timeout: 10_000 })
  await expect.poll(async () => (await storedProductsOf(home)).sort()).toEqual(['bluebook', 'original'])
  await home.close()

  // ── Student: back on the exam page, write and seal ───────────────────────
  await student.bringToFront()
  const sealRes = await sealAnswer(student, answer)
  expect(sealRes.status()).toBe(201)
  const sealBody = sealRes.request().postDataJSON()
  expect(sealBody.stylometric).toBeNull()
  expect(sealBody.ai_score).toBeNull()
  expect(sealBody.status).toBe('SUBMITTED')
  await expect(student.getByText('Examination Sealed')).toBeVisible({ timeout: 30_000 })
  await expect(student.getByText(/compared with your own past work/)).toHaveCount(0)
  // Nothing from the exam page reached Original after the switch.
  expect(callsAfterSwitch).toEqual([])

  // ── The teacher has the submission, Bluebook-only ────────────────────────
  const subs = await request.get('/bluebook/submissions', { headers: ws.teacher })
  expect(subs.status(), await subs.text()).toBe(200)
  const mine = (await subs.json()).submissions.filter(s => s.exam_id === ws.examId)
  expect(mine).toHaveLength(1)
  expect(mine[0].status).toBe('SUBMITTED')
  expect(mine[0].stylometric ?? null).toBeNull()

  await ctx.close()
})

test('the decision is locked when the student clicks Begin, before the exam screen mounts', async ({ browser, request }) => {
  test.setTimeout(120_000)
  const id = uid()
  const examTitle = `Switch-lock exam ${id}`
  const ws = await provisionExam(request, {
    examTitle, question: 'Is justice a virtue of the whole soul?', id,
  })
  await setProducts(request, ws, ['bluebook'])

  const ctx = await browser.newContext()
  const student = await newStudentPage(ctx)
  await redeemInvite(student, ws.invitePath, examTitle)
  expect(await storedProductsOf(student)).toEqual(['bluebook'])
  await student.getByRole('button', { name: 'Open' }).click()
  await expect(student.getByText('Enforced Conditions')).toBeVisible({ timeout: 10_000 })
  await expect(student.getByText(COMPARED_LINE)).toHaveCount(0)

  // Another tab refreshes the stored products after the briefing has shown
  // "not compared" but before the student clicks Begin.
  await student.evaluate(() => localStorage.setItem('original_products', JSON.stringify(['bluebook', 'original'])))
  await student.getByRole('button', { name: /Begin Examination|Resume Examination/ }).click()
  await expect(student.getByLabel('Your examination answer')).toBeVisible({ timeout: 10_000 })

  // The sitting keeps what the briefing displayed, not the products now stored.
  const decisions = () => student.evaluate(() => Object.keys(localStorage)
    .filter(k => k.startsWith('bb_draft_'))
    .map(k => JSON.parse(localStorage.getItem(k)).seal.withOriginal))
  await expect.poll(decisions).toEqual([false])
  expect((await storedProductsOf(student)).sort()).toEqual(['bluebook', 'original'])

  await ctx.close()
})

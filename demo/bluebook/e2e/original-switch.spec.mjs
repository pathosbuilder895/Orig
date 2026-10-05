/**
 * original-switch.spec.mjs — Original switched off while a student is mid-exam.
 *
 * The operator can turn Original on or off for a workspace at any time
 * (scripts/set_products.py, or PATCH /tenants/{id}). A student whose page was
 * loaded while the workspace held Original still believes it does, so the
 * seal calls Original's score and baseline routes, which now answer 403.
 * The seal must treat that as "this workspace no longer holds Original" and
 * record the submission like a Bluebook-only workspace does, instead of
 * retrying three times and leaving the exam unsealed.
 *
 * Needs MAINTENANCE_TOKEN set to the server's value (staff registration and
 * the guarded tenant PATCH send it as X-Guard-Token).
 */

import { test, expect } from '@playwright/test'
import { createCourse, provisionStaff, provisionTenantWithStaff } from './fixtures/api-setup.mjs'

const uid = () => `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`

test('a seal still lands when Original is switched off mid-exam', async ({ browser, request }) => {
  test.setTimeout(120_000)
  const id = uid()
  const examTitle = `Switch exam ${id}`
  const question = 'Is courage a mean between two vices?'
  const answer = 'Courage sits between cowardice and rashness, as Aristotle argues in Book Three.'

  // A workspace that holds Original (the fixture sends both products).
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

  // ── Student: sign in, open the exam while the workspace holds Original ──
  const ctx = await browser.newContext()
  const student = await ctx.newPage()
  await student.addInitScript(() => {
    // chromium-headless rejects requestFullscreen; the exam must not care.
    Element.prototype.requestFullscreen = function () { return Promise.resolve() }
  })
  const originalCalls = []
  student.on('response', r => {
    const path = new URL(r.url()).pathname
    if (/^\/students\//.test(path)) originalCalls.push({ path, status: r.status() })
  })
  await student.goto(invitePath)
  await student.getByLabel('New password').fill('e2e-student-pass-1')
  await student.getByLabel('Confirm password').fill('e2e-student-pass-1')
  await student.getByRole('button', { name: 'Save and continue' }).click()
  await expect(student.getByText(examTitle)).toBeVisible({ timeout: 10_000 })
  const storedProducts = () => student.evaluate(() => JSON.parse(localStorage.getItem('original_products')))
  expect((await storedProducts()).sort()).toEqual(['bluebook', 'original'])
  await student.getByRole('button', { name: 'Open' }).click()
  await expect(student.getByText('Preliminary Instructions')).toBeVisible({ timeout: 10_000 })
  await student.getByRole('button', { name: /Begin Examination|Resume Examination/ }).click()
  const box = student.getByLabel('Your examination answer')
  await expect(box).toBeVisible({ timeout: 10_000 })

  // ── Operator: switch the workspace to Bluebook only ─────────────────────
  const patched = await request.patch(`/tenants/${encodeURIComponent(tenant.tenant_id)}`, {
    headers: {
      Authorization: `Bearer ${operator.token}`,
      ...(process.env.MAINTENANCE_TOKEN ? { 'X-Guard-Token': process.env.MAINTENANCE_TOKEN } : {}),
    },
    data: { products: ['bluebook'] },
  })
  expect(patched.status(), await patched.text()).toBe(200)
  expect((await patched.json()).products).toEqual(['bluebook'])

  // ── Student: write and seal; the page still believes Original is on ────
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
  expect(sealRes.status()).toBe(201)
  const sealBody = sealRes.request().postDataJSON()
  expect(sealBody.stylometric).toBeNull()
  expect(sealBody.ai_score).toBeNull()
  expect(sealBody.status).toBe('SUBMITTED')
  await expect(student.getByText('Examination Sealed')).toBeVisible({ timeout: 30_000 })
  await expect(student.getByText('✓ Delivered to your teacher')).toBeVisible()
  // The seal did try Original (the page believed it was on) and was refused.
  expect(originalCalls.some(c => c.path.endsWith('/baseline') && c.status === 403)).toBe(true)
  expect(originalCalls.every(c => c.status === 403)).toBe(true)
  // ...and this page has stopped believing it.
  expect(await storedProducts()).toEqual(['bluebook'])

  // ── The teacher has the submission ───────────────────────────────────────
  const subs = await request.get('/bluebook/submissions', { headers: teacher })
  expect(subs.status(), await subs.text()).toBe(200)
  const mine = (await subs.json()).submissions.filter(s => s.exam_id === examId)
  expect(mine).toHaveLength(1)
  expect(mine[0].status).toBe('SUBMITTED')
  expect(mine[0].stylometric ?? null).toBeNull()

  await ctx.close()
})

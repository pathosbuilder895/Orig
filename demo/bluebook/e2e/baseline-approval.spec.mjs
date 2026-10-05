/**
 * baseline-approval.spec.mjs — a professor approves sealed exams as writing
 * baselines (plan Phase 7): add one from the reader, see it marked, remove
 * it, then add a whole examination's submissions in bulk. A Bluebook-only
 * workspace sees none of these controls.
 *
 * Needs MAINTENANCE_TOKEN set to the server's value (staff registration and
 * the guarded tenant PATCH send it as X-Guard-Token).
 */

import { test, expect } from '@playwright/test'
import { createCourse, provisionStaff, provisionTenantWithStaff, staffStorageState } from './fixtures/api-setup.mjs'

const uid = () => `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`
const ANSWER =
  'Augustine argues that the restless heart finds rest only in God, and he builds the argument ' +
  'slowly, from memory and desire, through the long middle books of the work, until the reader ' +
  'sees that the search was the subject all along. I find the account of desire persuasive.'

async function sealedExam(request, { products }) {
  const id = uid()
  const { tenant, staff } = await provisionTenantWithStaff(request)
  const teacher = { Authorization: `Bearer ${staff.token}` }
  if (products) {
    const operator = await provisionStaff(request, { tenantId: tenant.tenant_id, role: 'operator', name: 'E2E Operator' })
    const patched = await request.patch(`/tenants/${encodeURIComponent(tenant.tenant_id)}`, {
      headers: {
        Authorization: `Bearer ${operator.token}`,
        ...(process.env.MAINTENANCE_TOKEN ? { 'X-Guard-Token': process.env.MAINTENANCE_TOKEN } : {}),
      },
      data: { products },
    })
    expect(patched.status(), await patched.text()).toBe(200)
  }
  const course = await createCourse(request, staff.token, { name: `Baseline course ${id}` })
  const examTitle = `Baseline exam ${id}`
  const created = await request.post('/bluebook/exams', {
    headers: teacher,
    data: { title: examTitle, course: course.code, course_id: course.id, duration: 30, prompt: 'Discuss.', status: 'ACTIVE' },
  })
  expect(created.status(), await created.text()).toBe(201)
  const examId = (await created.json()).id
  const added = await request.post(`/bluebook/courses/${encodeURIComponent(course.id)}/students`, {
    headers: teacher, data: { students: [{ email: `stu-${id}@e2e.test`, name: 'Baseline Student' }] },
  })
  expect(added.status(), await added.text()).toBe(200)
  const invite = new URL((await added.json()).students[0].invite_path, 'http://x').searchParams.get('invite')
  const redeemed = await request.post('/auth/invite/redeem', { data: { token: invite, password: 'e2e-passw0rd!' } })
  expect(redeemed.status(), await redeemed.text()).toBe(200)
  const student = await redeemed.json()
  const asStudent = { Authorization: `Bearer ${student.token}` }
  await request.post(`/bluebook/me/exams/${encodeURIComponent(examId)}/start`, { headers: asStudent })
  const sealed = await request.post('/bluebook/submissions', {
    headers: asStudent,
    data: {
      exam_id: examId, student_id: student.student_id, candidate: 'Baseline Student',
      word_count: 60, text: ANSWER, answers: [ANSWER], submission_uuid: `uuid-${id}`,
    },
  })
  expect(sealed.status(), await sealed.text()).toBe(201)
  return { tenant, staff, examTitle }
}

async function teacherPage(browser, baseURL, { tenant, staff }, products) {
  const ctx = await browser.newContext({
    storageState: staffStorageState(baseURL, { token: staff.token, role: 'professor', tenant_id: tenant.tenant_id }),
  })
  const page = await ctx.newPage()
  await page.addInitScript(p => localStorage.setItem('original_products', JSON.stringify(p)), products)
  return { ctx, page }
}

async function openExam(page, examTitle) {
  await page.goto('/bluebook/')
  await page.getByRole('button', { name: 'Examinations' }).first().click()
  await page.getByRole('button', { name: examTitle }).click()
}

test('a professor adds, removes and bulk-adds sealed exams as baselines', async ({ browser, request, baseURL }) => {
  test.setTimeout(90_000)
  const ws = await sealedExam(request, {})  // fixture tenants hold both products
  const { ctx, page } = await teacherPage(browser, baseURL, ws, ['bluebook', 'original'])

  await openExam(page, ws.examTitle)
  await page.getByRole('button', { name: 'Read & mark' }).first().click()
  await expect(page.getByText('Not in baseline')).toBeVisible()
  await page.getByRole('button', { name: 'Add to baseline' }).click()
  await expect(page.getByText("Added to Baseline Student's baseline.")).toBeVisible({ timeout: 30_000 })
  // The status shares its paragraph with the "Writing baseline:" label, so match the whole line.
  await expect(page.getByText('Writing baseline: In baseline', { exact: true })).toBeVisible()

  page.once('dialog', d => d.accept())
  await page.getByRole('button', { name: 'Remove from baseline' }).click()
  await expect(page.getByText("Removed from Baseline Student's baseline.")).toBeVisible({ timeout: 30_000 })

  page.once('dialog', d => d.accept())
  await page.getByRole('button', { name: 'Add all sealed submissions to baselines' }).click()
  await expect(page.getByText('1 added · 0 already in baseline · 0 held for review.')).toBeVisible({ timeout: 30_000 })
  await ctx.close()
})

test('a failed baseline status load can be retried', async ({ browser, request, baseURL }) => {
  test.setTimeout(90_000)
  const ws = await sealedExam(request, {})
  const { ctx, page } = await teacherPage(browser, baseURL, ws, ['bluebook', 'original'])

  const statusUrl = '**/bluebook/exams/*/baseline'
  await page.route(statusUrl, route => (route.request().method() === 'GET'
    ? route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'Temporarily unavailable' }) })
    : route.continue()))
  await openExam(page, ws.examTitle)
  await page.getByRole('button', { name: 'Read & mark' }).first().click()
  await expect(page.getByText('Writing baseline: unavailable', { exact: true })).toBeVisible()
  await expect(page.getByText('Temporarily unavailable')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Add to baseline' })).toHaveCount(0)

  await page.unroute(statusUrl)
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('Writing baseline: Not in baseline', { exact: true })).toBeVisible()
  await expect(page.getByText('Temporarily unavailable')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Try again' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Add to baseline' })).toBeVisible()
  await ctx.close()
})

test('the bulk add shows progress and cannot be started twice', async ({ browser, request, baseURL }) => {
  test.setTimeout(90_000)
  const ws = await sealedExam(request, {})
  const { ctx, page } = await teacherPage(browser, baseURL, ws, ['bluebook', 'original'])

  let posts = 0
  await page.route('**/bluebook/exams/*/baseline', async route => {
    if (route.request().method() !== 'POST') return route.continue()
    posts += 1
    await new Promise(resolve => setTimeout(resolve, 1500))
    return route.continue()
  })
  await openExam(page, ws.examTitle)
  page.once('dialog', d => d.accept())
  await page.getByRole('button', { name: 'Add all sealed submissions to baselines' }).click()
  const running = page.getByRole('button', { name: 'Adding…' })
  await expect(running).toBeVisible()
  await expect(running).toBeDisabled()
  await expect(page.getByText('1 added · 0 already in baseline · 0 held for review.')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('button', { name: 'Add all sealed submissions to baselines' })).toBeEnabled()
  expect(posts).toBe(1)
  await ctx.close()
})

test('a Bluebook-only workspace sees no baseline controls', async ({ browser, request, baseURL }) => {
  const ws = await sealedExam(request, { products: ['bluebook'] })
  const { ctx, page } = await teacherPage(browser, baseURL, ws, ['bluebook'])

  await openExam(page, ws.examTitle)
  await page.getByRole('button', { name: 'Read & mark' }).first().click()
  await expect(page.getByText('Save mark and feedback')).toBeVisible()
  await expect(page.getByText('Writing baseline')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Add all sealed submissions to baselines' })).toHaveCount(0)
  await ctx.close()
})

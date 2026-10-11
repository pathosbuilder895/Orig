/**
 * student-original-links.spec.mjs: a student can reach their Original pages
 * from Bluebook (2026-10-11 button audit).
 *
 * "My voice" (/original/voice.html) and "My work" (/original/my-work.html)
 * sit in the student navigation only while the student's workspace holds
 * Original. Switching Original off removes them the next time the student
 * home loads (/bluebook/me refreshes the stored products). A Bluebook-only
 * workspace never offers them.
 *
 * Needs MAINTENANCE_TOKEN set to the server's value (staff registration and
 * the guarded tenant PATCH send it as X-Guard-Token).
 */

import { test, expect } from '@playwright/test'
import { provisionStaff, provisionTenantWithStaff, studentLogin } from './fixtures/api-setup.mjs'

async function setProducts(request, operator, tenantId, products) {
  const patched = await request.patch(`/tenants/${encodeURIComponent(tenantId)}`, {
    headers: {
      Authorization: `Bearer ${operator.token}`,
      ...(process.env.MAINTENANCE_TOKEN ? { 'X-Guard-Token': process.env.MAINTENANCE_TOKEN } : {}),
    },
    data: { products },
  })
  expect(patched.status(), await patched.text()).toBe(200)
}

test('a student reaches My voice and My work only while Original is on', async ({ browser, request, baseURL }) => {
  test.setTimeout(90_000)
  const { tenant, staff } = await provisionTenantWithStaff(request)
  const operator = await provisionStaff(request, { tenantId: tenant.tenant_id, role: 'operator', name: 'E2E Operator' })
  const session = await studentLogin(request, { staffToken: staff.token })

  // The browser state a student sign-in leaves (components.jsx _storeSession).
  const ctx = await browser.newContext({
    storageState: {
      cookies: [],
      origins: [{
        origin: baseURL,
        localStorage: [
          { name: 'original_session_token', value: session.token },
          { name: 'original_student_id', value: session.student_id },
          { name: 'original_role', value: 'student' },
          { name: 'original_tenant', value: session.tenant_id },
          { name: 'original_name', value: session.name || '' },
          { name: 'original_products', value: JSON.stringify(session.products) },
        ],
      }],
    },
  })
  const page = await ctx.newPage()
  const nav = page.getByRole('navigation', { name: 'Student navigation' })

  // Original is on: both links, to the student pages.
  await page.goto('/bluebook/')
  await expect(nav.getByRole('button', { name: 'My exams' })).toBeVisible({ timeout: 10_000 })
  const voice = nav.getByRole('link', { name: 'My voice' })
  const work = nav.getByRole('link', { name: 'My work' })
  await expect(voice).toBeVisible()
  await expect(work).toBeVisible()
  expect(new URL(await voice.evaluate(a => a.href)).pathname).toBe('/original/voice.html')
  expect(new URL(await work.evaluate(a => a.href)).pathname).toBe('/original/my-work.html')

  // The links are on the Account screen's navigation too, and they lead to the pages.
  await nav.getByRole('button', { name: 'Account' }).click()
  await expect(nav.getByRole('link', { name: 'My work' })).toBeVisible()
  await nav.getByRole('link', { name: 'My voice' }).click()
  await expect(page).toHaveURL(/\/original\/voice\.html$/)
  await expect(page.getByText('Sign in to continue')).toHaveCount(0)

  // Original is switched off: the next home load drops the links.
  await setProducts(request, operator, tenant.tenant_id, ['bluebook'])
  await page.goto('/bluebook/')
  await expect(nav.getByRole('button', { name: 'My exams' })).toBeVisible({ timeout: 10_000 })
  await expect(nav.getByRole('link', { name: 'My voice' })).toHaveCount(0, { timeout: 10_000 })
  await expect(nav.getByRole('link', { name: 'My work' })).toHaveCount(0)

  await ctx.close()
})

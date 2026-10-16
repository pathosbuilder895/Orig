/**
 * student-original-links.spec.mjs: the student navigation offers no Original
 * pages during the pilot (2026-10-15, alpha polish).
 *
 * "My voice" (/original/voice.html) and "My work" (/original/my-work.html)
 * show a student Original's reading of their writing. During the pilot a
 * student never sees a comparison (NORTH_STAR "Not doing now" defers the "My
 * Voice" pages), so the Collections navigation does not link to them, even
 * where the workspace holds Original (Account.jsx SHOW_STUDENT_ORIGINAL_PAGES).
 * The pages themselves are unchanged and still check the session themselves.
 *
 * Needs MAINTENANCE_TOKEN set to the server's value (staff registration sends
 * it as X-Guard-Token).
 */

import { test, expect } from '@playwright/test'
import { provisionTenantWithStaff, studentLogin } from './fixtures/api-setup.mjs'

test('a student in a workspace with Original sees no My voice or My work link', async ({ browser, request, baseURL }) => {
  test.setTimeout(90_000)
  const { staff } = await provisionTenantWithStaff(request)
  const session = await studentLogin(request, { staffToken: staff.token })
  expect(session.products).toContain('original')

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

  await page.goto('/bluebook/')
  await expect(nav.getByRole('button', { name: 'My exams' })).toBeVisible({ timeout: 10_000 })
  await expect(nav.getByRole('link', { name: 'My voice' })).toHaveCount(0)
  await expect(nav.getByRole('link', { name: 'My work' })).toHaveCount(0)

  // Nor on the Account screen's navigation.
  await nav.getByRole('button', { name: 'Account' }).click()
  await expect(nav.getByRole('button', { name: 'Account' })).toHaveAttribute('aria-current', 'page')
  await expect(nav.getByRole('link')).toHaveCount(0)

  await ctx.close()
})

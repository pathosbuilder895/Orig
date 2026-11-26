/**
 * fixtures/tenancy.mjs — per-worker tenancy isolation + auth storage-state
 * fixtures (WS-9 Stage 0.2/0.3).
 *
 * Each Playwright worker provisions its own tenant, staff (professor),
 * operator, and student identity exactly once (worker-scoped fixture),
 * then every test on that worker reuses them by seeding a fresh browser
 * context's storageState — no per-test login round-trip through the UI.
 *
 * Raising `workers` above 1 (playwright.config.mjs) is only safe because
 * workers never share a tenant this way. See
 * e2e/tenancy-isolation.spec.mjs for the explicit negative assertion this
 * relies on: a staff principal in one tenant must not read another
 * tenant's exams/courses.
 */

import { test as base } from '@playwright/test'
import {
  provisionTenantWithStaff, provisionStaff, studentLogin,
  staffStorageState, studentStorageState,
} from './api-setup.mjs'

export const test = base.extend({
  workerTenant: [async ({ playwright }, use, workerInfo) => {
    // baseURL is a test-scoped built-in fixture, not visible to a worker-scoped
    // one — read it off the project config instead (same value, worker-visible).
    const baseURL = workerInfo.project.use.baseURL
    const request = await playwright.request.newContext({ baseURL })
    const { tenant, staff } = await provisionTenantWithStaff(request, { role: 'professor' })
    const operator = await provisionStaff(request, {
      tenantId: tenant.tenant_id, role: 'operator', name: 'E2E Operator',
    })
    const student = await studentLogin(request, { staffToken: staff.token })
    await request.dispose()
    await use({ tenant, staff, operator, student, baseURL })
  }, { scope: 'worker' }],

  staffPage: async ({ browser, workerTenant }, use) => {
    const context = await browser.newContext({
      storageState: staffStorageState(workerTenant.baseURL, workerTenant.staff),
    })
    const page = await context.newPage()
    await use(page)
    await context.close()
  },

  operatorPage: async ({ browser, workerTenant }, use) => {
    const context = await browser.newContext({
      storageState: staffStorageState(workerTenant.baseURL, workerTenant.operator),
    })
    const page = await context.newPage()
    await use(page)
    await context.close()
  },

  studentPage: async ({ browser, workerTenant }, use) => {
    const context = await browser.newContext({
      storageState: studentStorageState(workerTenant.baseURL, workerTenant.student),
    })
    const page = await context.newPage()
    await use(page)
    await context.close()
  },
})

/**
 * `isolatedTest`: the same fixtures, plus `testTenant`, a tenant (teacher and
 * one student) provisioned for a single test, and a `studentPage` signed in as
 * that student. For specs that SEAL submissions: the worker's tenant is shared
 * by every spec that lands on that worker, and professor-journey.spec.mjs
 * counts the submissions in it, so a seal written there by another spec turns
 * its "1 submissions" into "2". Costs one staff login per test.
 */
export const isolatedTest = test.extend({
  testTenant: async ({ playwright }, use, testInfo) => {
    const baseURL = testInfo.project.use.baseURL
    const request = await playwright.request.newContext({ baseURL })
    const { tenant, staff } = await provisionTenantWithStaff(request, { role: 'professor' })
    const student = await studentLogin(request, { staffToken: staff.token })
    await request.dispose()
    await use({ tenant, staff, student, baseURL })
  },

  studentPage: async ({ browser, testTenant }, use) => {
    const context = await browser.newContext({
      storageState: studentStorageState(testTenant.baseURL, testTenant.student),
    })
    const page = await context.newPage()
    await use(page)
    await context.close()
  },
})

export { expect } from '@playwright/test'

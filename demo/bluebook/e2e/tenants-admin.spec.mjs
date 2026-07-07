/**
 * tenants-admin.spec.mjs — WS-9 Stage 2 breadth
 * (docs/implementation/WS-9-e2e-release-hygiene.md, Stage 2).
 *
 * Tenant CRUD through the Operator console (demo/operator.html — same live
 * stack, not Bluebook; see baselines.spec.mjs header) plus the E2E
 * complement of tests/test_tenant_isolation.py: a student who belongs to
 * tenant A must be invisible from tenant B's session, from both the roster
 * listing and a direct fetch by id.
 *
 * operator.html has no dedicated tenant *delete* — only
 * DELETE /tenants/{id}/students (bulk-delete the tenant's students, not the
 * tenant record itself; original/api.py has no plain tenant DELETE route at
 * all). CRUD here means Create + Read, which is what the product offers.
 */

import { test, expect } from '@playwright/test'
import { provisionTenantWithStaff, studentLogin } from './fixtures/api-setup.mjs'

test.describe('Tenant CRUD via the Operator console @smoke', () => {
  test('registering a school through the UI creates it and it appears in the tenant grid', async ({ page, request }) => {
    // Tenant creation itself needs an authenticated staff token (see
    // fixtures/api-setup.mjs createTenant) — provision one tenant purely to
    // get an operator credential, then register a SECOND tenant through the
    // UI, which is the thing under test.
    const { staff: operator } = await provisionTenantWithStaff(request, { role: 'operator' })
    await page.addInitScript(([token, role, tenantId]) => {
      localStorage.setItem('original_principal_token', token)
      localStorage.setItem('original_role', role)
      localStorage.setItem('original_tenant', tenantId)
    }, [operator.token, operator.role, operator.tenant_id])

    const newTenantId = `e2e-registered-${Date.now()}`
    const newTenantName = `E2E Registered School ${Date.now()}`

    await page.goto('/operator.html')
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: '+ Register school' }).click()
    await page.locator('#rfId').fill(newTenantId)
    await page.locator('#rfName').fill(newTenantName)

    const [registerResponse] = await Promise.all([
      page.waitForResponse(r => r.url().endsWith('/tenants') && r.request().method() === 'POST'),
      page.getByRole('button', { name: 'Save' }).click(),
    ])
    expect(registerResponse.ok()).toBe(true)
    await expect(page.getByText(newTenantName)).toBeVisible({ timeout: 10_000 })

    const getRes = await request.get(`/tenants/${encodeURIComponent(newTenantId)}`, {
      headers: { Authorization: `Bearer ${operator.token}` },
    })
    expect(getRes.ok()).toBe(true)
    expect((await getRes.json()).name).toBe(newTenantName)
  })
})

test.describe('Cross-tenant student visibility (complements test_tenant_isolation.py)', () => {
  test('a student in tenant A is invisible from tenant B — neither in the roster nor by direct fetch', async ({ request }) => {
    const a = await provisionTenantWithStaff(request)
    const b = await provisionTenantWithStaff(request)
    const studentA = await studentLogin(request, { institution: a.tenant.name, name: 'Tenant A Student' })

    // Direct fetch: tenant B's staff gets 403 on tenant A's student.
    const directRes = await request.get(`/students/${encodeURIComponent(studentA.student_id)}`, {
      headers: { Authorization: `Bearer ${b.staff.token}` },
    })
    expect(directRes.status()).toBe(403)

    // Roster listing: tenant B's staff never sees tenant A's student id.
    const rosterRes = await request.get('/students', {
      headers: { Authorization: `Bearer ${b.staff.token}` },
    })
    expect(rosterRes.ok()).toBe(true)
    const roster = await rosterRes.json()
    const ids = (roster.roster || roster.students || []).map(s => (typeof s === 'string' ? s : s.id))
    expect(ids).not.toContain(studentA.student_id)

    // Sanity: tenant A's own staff CAN see their student (isolation isn't blanket denial).
    const ownRes = await request.get(`/students/${encodeURIComponent(studentA.student_id)}`, {
      headers: { Authorization: `Bearer ${a.staff.token}` },
    })
    expect(ownRes.ok()).toBe(true)
  })

  test('an operator (super role) can cross tenant boundaries by design', async ({ request }) => {
    const a = await provisionTenantWithStaff(request)
    const studentA = await studentLogin(request, { institution: a.tenant.name, name: 'Tenant A Student 2' })
    // A genuinely different tenant than A's — proves this is cross-tenant
    // access, not same-tenant access that happens to also be an operator.
    const c = await provisionTenantWithStaff(request, { role: 'operator' })

    const res = await request.get(`/students/${encodeURIComponent(studentA.student_id)}`, {
      headers: { Authorization: `Bearer ${c.staff.token}` },
    })
    expect(res.ok()).toBe(true)
  })
})

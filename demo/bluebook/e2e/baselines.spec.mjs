/**
 * baselines.spec.mjs — WS-9 Stage 2 breadth
 * (docs/implementation/WS-9-e2e-release-hygiene.md, Stage 2).
 *
 * Batch baseline upload via the keyboard-reachable file input, the
 * proctored-baseline magic-link request, and the readiness surface
 * reflecting new samples.
 *
 * Scope note: this UI lives in demo/professor.html, not the Bluebook React
 * app — Bluebook has no baseline-management screen at all. professor.html
 * is part of the same live stack (original/api.py + demo/, per CLAUDE.md)
 * and served by the same baseURL, so testing it from here is in-scope; the
 * testDir just happens to be under demo/bluebook/e2e for historical reasons.
 */

import { test, expect } from '@playwright/test'
import { provisionTenantWithStaff, studentLogin } from './fixtures/api-setup.mjs'

test.describe('Baseline batch upload (keyboard path) @smoke', () => {
  test('uploading files through the (keyboard-focusable) file input updates readiness', async ({ page, request }) => {
    const { tenant, staff } = await provisionTenantWithStaff(request)
    const student = await studentLogin(request, { institution: tenant.name, name: 'Baseline Test Student' })

    await page.addInitScript(([token, role, tenantId]) => {
      localStorage.setItem('original_principal_token', token)
      localStorage.setItem('original_role', role)
      localStorage.setItem('original_tenant', tenantId)
    }, [staff.token, staff.role, staff.tenant_id])

    await page.goto('/professor.html')
    await page.waitForLoadState('networkidle')

    // The freshly-created student auto-selects as STUDENTS[0] once the
    // authenticated roster hydrates (hydrateRosterFromServer in
    // professor.html) — confirm we're looking at them before uploading.
    await expect(page.locator('#panelStudentName')).toHaveText(/Baseline Test Student/, { timeout: 10_000 })

    await page.getByRole('button', { name: 'Baselines' }).click()

    // #blFileInput is visually hidden (clip-rect technique) but present in
    // the DOM and tab order — the "keyboard path" the doc calls for. Not
    // display:none, so Playwright can target and set files on it directly
    // (the real click→native-file-dialog step can't be scripted in any
    // browser automation tool; setInputFiles works regardless of the
    // input's display:none — Playwright sets files via CDP, not a real
    // click, so visibility isn't a precondition here).
    const fileInput = page.locator('#blFileInput')
    await expect(fileInput).toBeAttached()
    await fileInput.setInputFiles({
      name: 'baseline-sample.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from(
        'This is a verified baseline writing sample submitted through the batch upload path for end-to-end testing.',
      ),
    })

    // Picking a file queues it client-side (text extracted per file); "Add
    // All to Baseline" then submits each queued file via API.addBaseline(),
    // which — despite the drop-zone's "batch" framing — POSTs to the same
    // single-sample /students/{id}/baseline endpoint once per file, not
    // /baseline/upload-batch (professor.html:1715, submitAllFiles:2556).
    await page.getByRole('button', { name: 'Add All to Baseline' }).click()
    await page.waitForResponse(r => /\/students\/.+\/baseline$/.test(new URL(r.url()).pathname) && r.request().method() === 'POST')

    const readinessRes = await request.get(`/students/${encodeURIComponent(student.student_id)}/readiness`, {
      headers: { Authorization: `Bearer ${staff.token}` },
    })
    expect(readinessRes.ok()).toBe(true)
    const readiness = await readinessRes.json()
    expect(readiness.sample_count).toBeGreaterThan(0)
  })
})

test.describe('Proctored baseline request (magic link)', () => {
  test('POST /students/{id}/request-baseline without Bbook configured returns a clear 503, not a silent failure', async ({ request }) => {
    const { tenant, staff } = await provisionTenantWithStaff(request)
    const student = await studentLogin(request, { institution: tenant.name, name: 'Magic Link Student' })

    // BBOOK_API_URL/BBOOK_EXTERNAL_SECRET are unset in this test environment
    // (no-op-without-config flags, CLAUDE.md) — the contract worth locking
    // down is that the endpoint fails loudly (503) rather than pretending to
    // send a link. Full magic-link issuance requires a live Bbook sandbox,
    // out of scope for this suite.
    const res = await request.post(`/students/${encodeURIComponent(student.student_id)}/request-baseline`, {
      headers: { Authorization: `Bearer ${staff.token}` },
      data: { student_email: 'candidate@e2e.test', student_name: 'Magic Link Student' },
    })
    expect(res.status()).toBe(503)
  })
})

test.describe('Readiness surface', () => {
  test('a student with zero samples reads as insufficient; readiness reflects sample_count', async ({ request }) => {
    const { tenant, staff } = await provisionTenantWithStaff(request)
    const student = await studentLogin(request, { institution: tenant.name, name: 'Readiness Student' })

    const before = await (await request.get(`/students/${encodeURIComponent(student.student_id)}/readiness`, {
      headers: { Authorization: `Bearer ${staff.token}` },
    })).json()
    expect(before.sample_count).toBe(0)
    expect(before.verdict).toBe('insufficient')

    await request.post(`/students/${encodeURIComponent(student.student_id)}/baseline`, {
      headers: { Authorization: `Bearer ${staff.token}` },
      data: { text: 'One verified sample to move the readiness needle for this student.', provenance: 'verified' },
    })

    const after = await (await request.get(`/students/${encodeURIComponent(student.student_id)}/readiness`, {
      headers: { Authorization: `Bearer ${staff.token}` },
    })).json()
    expect(after.sample_count).toBe(1)
  })
})

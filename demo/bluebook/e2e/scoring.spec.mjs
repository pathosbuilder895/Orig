/**
 * scoring.spec.mjs — WS-9 Stage 2 breadth
 * (docs/implementation/WS-9-e2e-release-hygiene.md, Stage 2).
 *
 * Submit → score → recommendation renders and matches the API payload;
 * blend-detection surface. Lives in demo/professor.html (same live stack,
 * see baselines.spec.mjs header) — Bluebook has no scoring-review screen.
 *
 * Known gap, not worked around: professor.html's #profExplanation only
 * renders `report.professor_explanation`, which is populated from the
 * Phase-3 context manifest/Phase-6 report pipeline. In this test
 * environment that pipeline returns `report: null` even though
 * CONTEXT_MANIFEST_ENABLED defaults on for --demo — a pre-existing gap
 * upstream of this suite. The always-available `human_explanation` field
 * (verdict/severity/top_reasons) is never rendered anywhere in
 * professor.html at all — dead data on the wire. We assert what the UI
 * actually renders (#recBadge, always populated by renderResults()) against
 * the API's `recommendation.action`, and separately assert the API payload
 * itself carries `human_explanation` — proving the pipeline still owes the
 * frontend a render path for it.
 */

import { test, expect } from '@playwright/test'
import { provisionTenantWithStaff, studentLogin, addBaselineFor } from './fixtures/api-setup.mjs'

async function openStudentInProfessorConsole(page, staff, studentName) {
  await page.addInitScript(([token, role, tenantId]) => {
    localStorage.setItem('original_principal_token', token)
    localStorage.setItem('original_role', role)
    localStorage.setItem('original_tenant', tenantId)
  }, [staff.token, staff.role, staff.tenant_id])
  await page.goto('/professor.html')
  await page.waitForLoadState('networkidle')
  await expect(page.locator('#panelStudentName')).toHaveText(new RegExp(studentName), { timeout: 10_000 })
}

test.describe('Submit → score → recommendation @smoke', () => {
  test('analyzing a submission renders a recommendation matching the API payload', async ({ page, request }) => {
    const { tenant, staff } = await provisionTenantWithStaff(request)
    const student = await studentLogin(request, { institution: tenant.name, name: 'Scoring Test Student' })
    await addBaselineFor(request, student.student_id, staff.token, {
      text: 'An established baseline essay with a clear and consistent authorial voice used to score against, written some weeks ago.',
    })

    await openStudentInProfessorConsole(page, staff, 'Scoring Test Student')

    const submissionText =
      'This second submission is stylistically distinct from the established baseline in several ' +
      'measurable ways, including sentence structure, vocabulary choice, and argument construction, ' +
      'which the scorer should pick up on when comparing the two writing samples directly.'
    await page.locator('#subText').fill(submissionText)

    const [scoreResponse] = await Promise.all([
      page.waitForResponse(r => /\/students\/.+\/score$/.test(new URL(r.url()).pathname) && r.request().method() === 'POST'),
      page.getByRole('button', { name: 'Analyze Writing' }).click(),
    ])
    const scoreBody = await scoreResponse.json()
    expect(scoreBody.recommendation).toBeTruthy()
    expect(scoreBody.human_explanation).toBeTruthy() // see file header — rendered nowhere today, but on the wire

    await expect(page.locator('#recBadge')).toBeVisible({ timeout: 10_000 })
    await expect(page.locator('#recBadge')).toHaveClass(new RegExp(scoreBody.recommendation.action))
  })
})

test.describe('Blend-detection surface', () => {
  test('Run blend check surfaces blend_detected/blend_index matching the API payload', async ({ page, request }) => {
    const { tenant, staff } = await provisionTenantWithStaff(request)
    const student = await studentLogin(request, { institution: tenant.name, name: 'Blend Test Student' })
    await addBaselineFor(request, student.student_id, staff.token, {
      text: 'An established baseline essay with a clear and consistent authorial voice used to score against, written some weeks ago.',
    })

    await openStudentInProfessorConsole(page, staff, 'Blend Test Student')

    const submissionText =
      'The opening portion of this submission reads in one register before shifting abruptly into a ' +
      'noticeably different one partway through, the kind of seam a blend detector is built to notice ' +
      'when two distinct sources have been stitched together into a single piece of writing.'
    await page.locator('#subText').fill(submissionText)
    await Promise.all([
      page.waitForResponse(r => /\/students\/.+\/score$/.test(new URL(r.url()).pathname) && r.request().method() === 'POST'),
      page.getByRole('button', { name: 'Analyze Writing' }).click(),
    ])
    await expect(page.locator('#recBadge')).toBeVisible({ timeout: 10_000 })

    const [blendResponse] = await Promise.all([
      page.waitForResponse(r => r.url().includes('/score/blend') && r.request().method() === 'POST'),
      page.locator('#blendBtn').click(),
    ])
    const blendBody = await blendResponse.json()

    await expect(page.locator('#blendCard')).toBeVisible({ timeout: 10_000 })
    await expect(page.locator('#blendDetectedV')).toHaveText(blendBody.blend_detected ? 'Yes' : 'No')
    await expect(page.locator('#blendIndexV')).toHaveText(blendBody.blend_index.toFixed(3))
  })
})

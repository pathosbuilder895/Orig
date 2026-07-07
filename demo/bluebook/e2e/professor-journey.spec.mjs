/**
 * professor-journey.spec.mjs — WS-9 Stage 1, the T7 acceptance gate
 * (docs/implementation/WS-9-e2e-release-hygiene.md).
 *
 * Walks the professor's use of sealed evidence end-to-end: create course →
 * create exam (ToggleRow lockdown states) → a student seals a submission →
 * the exam appears on Dashboard → Results shows the score → drill into the
 * per-submission analysis → file a correction → correction visible in audit.
 *
 * Two honest gaps in the current Bluebook React frontend, worked around
 * rather than glossed over:
 *  - NewExamScreen's course picker is a hardcoded local list (COURSES in
 *    NewExam.jsx), not wired to the courses just created via the UI. We
 *    create our course under one of those hardcoded codes so the journey
 *    stays coherent; this is a known frontend gap, not a test bug.
 *  - Results.jsx has NO correction-filing UI at all — "Mark Reviewed" in
 *    ExpandedRow is local component state, never sent to the server. The
 *    real correction endpoint (POST /submissions/{id}/correct) and audit
 *    trail (GET /admin/audit, GET /admin/manifests) exist server-side but
 *    aren't wired to any page. We exercise them directly via the API so
 *    the pipeline itself is proven, and flag the missing UI rather than
 *    silently only testing the API.
 */

import { test, expect } from './fixtures/tenancy.mjs'
import { addBaselineFor } from './fixtures/api-setup.mjs'

const HARDCODED_COURSE_CODE = 'PHIL 301A' // must match a NewExam.jsx COURSES entry

test.describe('Professor journey — sealed evidence review @smoke', () => {
  test('course → exam → student seal → dashboard → results → explanation → correction → audit', async ({
    staffPage, studentPage, workerTenant, request,
  }) => {
    // A full course→exam→seal→review round-trip does real quantum scoring
    // against a live baseline (not the fast-fail no-baseline path the other
    // specs exercise) — comfortably over the 30s default in a cold run.
    test.setTimeout(90_000)
    const uniqueSuffix = workerTenant.tenant.tenant_id
    const courseName = `E2E Ethics Seminar ${uniqueSuffix}`
    const examTitle = `E2E Professor Journey Exam ${uniqueSuffix}`
    // Results.jsx truncates result.exam past 28 chars but never truncates
    // result.student — use the candidate name (unique per worker) to find
    // our row instead of the (truncated) exam title.
    const candidateName = `E2E Candidate ${uniqueSuffix}`

    // ── 1. Create course (Courses screen) ──────────────────────────────
    await staffPage.goto('/bluebook/')
    await staffPage.waitForLoadState('networkidle')
    await staffPage.getByRole('button', { name: 'Courses' }).click()
    await staffPage.getByRole('button', { name: '+ New Course' }).click()
    await staffPage.getByPlaceholder('PHIL 401').fill(HARDCODED_COURSE_CODE)
    await staffPage.getByPlaceholder('e.g. Philosophy of Language').fill(courseName)
    await staffPage.getByRole('button', { name: 'Create Course' }).click()
    await expect(staffPage.getByText(courseName)).toBeVisible({ timeout: 10_000 })

    // ── 2. Create exam (New Examination screen, ToggleRow lockdown states) ──
    await staffPage.getByRole('button', { name: 'Examinations' }).click()
    await staffPage.getByRole('button', { name: '+ New Examination' }).click()
    await staffPage.locator('#neTitle').fill(examTitle)
    // #neCourse defaults to HARDCODED_COURSE_CODE already — leave as-is.
    await staffPage.locator('#neMinWords').fill('12')
    await staffPage.locator('#neMaxWords').fill('5000')
    await staffPage.locator('#nePrompt0').fill('Describe the categorical imperative in your own words.')
    // Touch a subset of the ToggleRow lockdown/secondary conditions the doc
    // calls out explicitly — flip spell-check ON, leave the secure defaults.
    await staffPage.getByRole('switch', { name: 'Allow spell check' }).click()
    await expect(staffPage.getByRole('switch', { name: 'Allow spell check' })).toHaveAttribute('aria-checked', 'true')

    const [createExamResponse] = await Promise.all([
      staffPage.waitForResponse(r => r.url().includes('/bluebook/exams') && r.request().method() === 'POST'),
      staffPage.getByRole('button', { name: 'Publish Examination' }).click(),
    ])
    const createdExam = await createExamResponse.json()
    expect(createdExam.id).toBeTruthy()
    await expect(staffPage.getByText('Examination Created')).toBeVisible({ timeout: 10_000 })
    await expect(staffPage.getByText(examTitle)).toBeVisible({ timeout: 10_000 })

    // ── 3. Student seals a submission against that exam ─────────────────
    // Seed one verified baseline sample first: POST /students/{id}/score
    // 422s with zero authenticated samples, so without this the exam-seal
    // flow's scoring call would silently no-op (aiScore=null) and never
    // write the manifest/audit entry the correction step below needs —
    // exactly the "cold start" case a real returning student wouldn't hit.
    await addBaselineFor(request, workerTenant.student.student_id, workerTenant.student.token, {
      text: 'An earlier verified writing sample establishing this student’s baseline voice profile for comparison.',
    })

    // Mirrors exam-flow.spec.mjs's bootInExam(): inject BB_EXAM_CONFIG so
    // the briefing→exam transition is immediate, using the real exam id
    // captured from the create response above.
    await studentPage.addInitScript(([exam, studentId, candidate]) => {
      localStorage.setItem('bluebook_student_id', studentId)
      window.BB_EXAM_CONFIG = {
        id: exam.id,
        title: exam.title,
        course: exam.course,
        courseTitle: exam.course,
        candidate,
        duration: 7200,
        minWords: 12,
        maxWords: null,
        blockWeb: true,
        blockCopy: true,
        spellChk: true,
      }
    }, [createdExam, workerTenant.student.student_id, candidateName])

    await studentPage.evaluate(() => {
      Element.prototype.requestFullscreen = function () { return Promise.resolve() }
    })
    await studentPage.goto('/bluebook/')
    await studentPage.waitForLoadState('networkidle')
    await studentPage.locator('button', { hasText: /begin|continue|enter|start/i }).first().click()

    const textarea = studentPage.locator('textarea[placeholder="Begin writing here…"]')
    await expect(textarea).toBeVisible({ timeout: 10_000 })
    await textarea.focus()
    const essay =
      'Kant argues that a maxim is morally permissible only if one could ' +
      'will it to become a universal law without contradiction. This ' +
      'categorical imperative binds regardless of the consequences that ' +
      'follow from acting on it, distinguishing duty from mere inclination ' +
      'and grounding obligation in reason rather than in outcome.'
    await studentPage.keyboard.type(essay, { delay: 1 })

    const sealBtn = studentPage.locator('button', { hasText: /Seal & Submit|Sealing/ })
    await expect(sealBtn).toBeVisible()
    await sealBtn.click()
    await expect(studentPage.getByText('Examination Sealed')).toBeVisible({ timeout: 45_000 })

    // ── 4. Exam appears in Dashboard ─────────────────────────────────────
    await staffPage.getByRole('button', { name: 'Overview' }).click();
    await expect(staffPage.getByText(examTitle)).toBeVisible({ timeout: 10_000 });

    // ── 5. Results shows the score, drill into the analysis ─────────────
    await staffPage.getByRole('button', { name: 'Results' }).click()
    const resultsRow = staffPage.locator('div', { hasText: candidateName }).last()
    await expect(resultsRow).toBeVisible({ timeout: 10_000 })
    await resultsRow.click()
    await expect(staffPage.getByText('Integrity Analysis')).toBeVisible({ timeout: 5_000 })
    await expect(staffPage.getByText('Typing Consistency').first()).toBeVisible()
    await expect(staffPage.getByText('Authenticity').first()).toBeVisible()

    // ── 6. File a correction + confirm it's visible in the audit trail ──
    // No frontend affordance exists for this (see file header) — exercised
    // directly against the API that a UI would eventually call. The score
    // call the seal triggered always writes an audit_log(action="score")
    // row carrying its submission_id (original/api.py) — that's the id
    // /submissions/{id}/correct is keyed on, independent of the Phase-3
    // context-manifest feature (CONTEXT_MANIFEST_ENABLED, off by default).
    const scoreAuditRes = await request.get(
      `/admin/audit?student_id=${encodeURIComponent(workerTenant.student.student_id)}&action=score`,
      { headers: { Authorization: `Bearer ${workerTenant.staff.token}` } },
    )
    expect(scoreAuditRes.ok()).toBe(true)
    const scoreAudit = await scoreAuditRes.json()
    expect(scoreAudit.items.length).toBeGreaterThan(0)
    const submissionId = scoreAudit.items[0].details.submission_id
    expect(submissionId).toBeTruthy()

    const correctionRes = await request.post(`/submissions/${encodeURIComponent(submissionId)}/correct`, {
      headers: { Authorization: `Bearer ${workerTenant.staff.token}` },
      data: {
        is_correct: false,
        corrected_verdict: 'authentic',
        corrected_action: 'no_action',
        reviewer: workerTenant.staff.email,
        notes: 'E2E professor-journey correction',
      },
    })
    expect(correctionRes.ok()).toBe(true)
    const correction = await correctionRes.json()
    expect(correction.submission_id).toBe(submissionId)

    const correctionsListRes = await request.get(
      `/admin/corrections?submission_id=${encodeURIComponent(submissionId)}`,
      { headers: { Authorization: `Bearer ${workerTenant.staff.token}` } },
    )
    expect(correctionsListRes.ok()).toBe(true)
    const correctionsList = await correctionsListRes.json()
    expect(correctionsList.items.some(c => c.notes === 'E2E professor-journey correction')).toBe(true)

    const auditRes = await request.get(
      `/admin/audit?student_id=${encodeURIComponent(workerTenant.student.student_id)}&action=correction`,
      { headers: { Authorization: `Bearer ${workerTenant.staff.token}` } },
    )
    expect(auditRes.ok()).toBe(true)
    const audit = await auditRes.json()
    expect(audit.total).toBeGreaterThan(0)
    expect(audit.items.some(i => i.action === 'correction')).toBe(true)
  })
})

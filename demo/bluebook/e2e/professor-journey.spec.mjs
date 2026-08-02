/**
 * professor-journey.spec.mjs — WS-9 Stage 1, the T7 acceptance gate
 * (docs/implementation/WS-9-e2e-release-hygiene.md).
 *
 * Walks the professor's use of sealed evidence end-to-end as a serial chain
 * of focused tests sharing one worker-scoped tenant (fixtures/tenancy.mjs):
 * create course → publish exam (ToggleRow lockdown states) → save a second
 * exam as DRAFT → preview the briefing → a student seals a submission that
 * Original scores live → Dashboard → Results (score matches the API
 * payload) → drill into the integrity narrative → Students roster → file a
 * correction → correction visible in corrections + audit.
 *
 * Serial-mode notes:
 *  - `journey` below carries state forward (created exam, recorded
 *    submission). Producers always run before consumers; if a step fails,
 *    the rest of the chain is skipped rather than failing confusingly.
 *  - On a CI retry Playwright restarts the worker, so the whole group
 *    reruns against a FRESH tenant with fresh module state — no residue
 *    from the failed attempt can collide with the retry.
 *
 * The course link between steps 1 and 2 is now real. NewExamScreen's picker
 * used to be a hardcoded local list (COURSES in NewExam.jsx) and this file
 * worked around it by creating its course under one of those hardcoded codes;
 * the picker now reads GET /bluebook/courses, so step 2 selects the course
 * step 1 created in this tenant and asserts it round-trips onto the exam.
 * That is the assertion the workaround could not make.
 *
 * Results.jsx's ExpandedRow now has a real CorrectionPanel (Correct/
 * Incorrect, verdict/action selects, notes, "File Correction") that calls
 * POST /submissions/{id}/correct and lists history via GET
 * /admin/corrections — the correction test below drives that UI directly
 * rather than hitting the API standalone. The old "Mark Reviewed" button
 * (local component state only, never persisted) is gone; step 8 now
 * asserts on the CorrectionPanel heading instead.
 *
 * The two non-serial describes at the bottom are Stage-2 breadth on the
 * same surface: NewExam form gating, and the fresh-tenant empty states
 * (an authenticated tenant must see its own — empty — data, never the
 * hardcoded demo mocks).
 */

import { test, expect } from './fixtures/tenancy.mjs'
import {
  addBaselineFor, provisionTenantWithStaff, staffStorageState,
} from './fixtures/api-setup.mjs'

// The code step 1 creates and step 2 then picks out of the live course list.
// Any code would do now that the picker is server-backed — it stays 'PHIL 301A'
// only so the journey still reads like a philosophy seminar.
const JOURNEY_COURSE_CODE = 'PHIL 301A'

function staffAuth(workerTenant) {
  return { Authorization: `Bearer ${workerTenant.staff.token}` }
}

/** Stable per-worker names — Results.jsx truncates result.exam past 28
 *  chars but never truncates result.student, so rows are found by the
 *  candidate name (unique per worker), not the (truncated) exam title. */
function names(workerTenant) {
  const suffix = workerTenant.tenant.tenant_id
  return {
    courseName: `E2E Ethics Seminar ${suffix}`,
    examTitle: `E2E Professor Journey Exam ${suffix}`,
    draftTitle: `E2E Draft Regulations Exam ${suffix}`,
    candidateName: `E2E Candidate ${suffix}`,
  }
}

async function openScreen(page, navLabel) {
  await page.goto('/bluebook/')
  await page.waitForLoadState('networkidle')
  if (navLabel) await page.getByRole('button', { name: navLabel }).click()
}

test.describe('Professor journey — sealed evidence review @smoke', () => {
  test.describe.configure({ mode: 'serial' })

  // Shared journey state (see serial-mode notes in the file header).
  const journey = {}

  // ── 1 ────────────────────────────────────────────────────────────────
  test('the professor creates a course through the Courses screen', async ({
    staffPage, workerTenant, request,
  }) => {
    const { courseName } = names(workerTenant)
    await openScreen(staffPage, 'Courses')
    await staffPage.getByRole('button', { name: '+ New Course' }).click()
    await staffPage.getByPlaceholder('PHIL 401').fill(JOURNEY_COURSE_CODE)
    await staffPage.getByPlaceholder('e.g. Philosophy of Language').fill(courseName)
    await staffPage.getByRole('button', { name: 'Create Course' }).click()
    await expect(staffPage.getByText(courseName)).toBeVisible({ timeout: 10_000 })

    // Recorded server-side, scoped to this worker's tenant.
    const coursesRes = await request.get('/bluebook/courses', { headers: staffAuth(workerTenant) })
    expect(coursesRes.ok()).toBe(true)
    const { courses } = await coursesRes.json()
    const mine = courses.find(c => c.name === courseName)
    expect(mine).toBeTruthy()
    expect(mine.code).toBe(JOURNEY_COURSE_CODE)
  })

  // ── 2 ────────────────────────────────────────────────────────────────
  test('the professor publishes an exam through New Examination and the lockdown toggles round-trip', async ({
    staffPage, workerTenant,
  }) => {
    const { examTitle } = names(workerTenant)
    await openScreen(staffPage, 'Examinations')
    await staffPage.getByRole('button', { name: '+ New Examination' }).click()

    // The ToggleRow states the WS-9 doc calls out explicitly. Defaults
    // first: the lockdown trio is the secure baseline (ON), spell check
    // starts permissive-OFF, the two extras start ON.
    const SWITCH_DEFAULTS = [
      ['Block AI assistants', 'true'],
      ['Block web & external tabs', 'true'],
      ['Block copy & paste', 'true'],
      ['Allow spell check', 'false'],
      ['Phone blocker', 'true'],
      ['AI detection (Original)', 'true'],
    ]
    for (const [name, checked] of SWITCH_DEFAULTS) {
      await expect(staffPage.getByRole('switch', { name })).toHaveAttribute('aria-checked', checked)
    }
    // Flip one OFF→ON and one ON→OFF so both directions are proven.
    await staffPage.getByRole('switch', { name: 'Allow spell check' }).click()
    await expect(staffPage.getByRole('switch', { name: 'Allow spell check' })).toHaveAttribute('aria-checked', 'true')
    await staffPage.getByRole('switch', { name: 'Phone blocker' }).click()
    await expect(staffPage.getByRole('switch', { name: 'Phone blocker' })).toHaveAttribute('aria-checked', 'false')

    await staffPage.locator('#neTitle').fill(examTitle)
    // #neCourse is populated from GET /bluebook/courses, so the course step 1
    // created in this tenant is selectable here by its own code. Selected
    // explicitly rather than left on the default: this worker's tenant may
    // hold more than one course by now (a11y.spec.mjs provisions its own on
    // the same worker-scoped tenant), and "whatever happens to be first" is
    // not what this step is asserting.
    await staffPage.locator('#neCourse').selectOption(JOURNEY_COURSE_CODE)
    await staffPage.locator('#neMinWords').fill('12')
    await staffPage.locator('#neMaxWords').fill('5000')
    await staffPage.locator('#nePrompt0').fill('Describe the categorical imperative in your own words.')

    const [createExamResponse] = await Promise.all([
      staffPage.waitForResponse(r => r.url().includes('/bluebook/exams') && r.request().method() === 'POST'),
      staffPage.getByRole('button', { name: 'Publish Examination' }).click(),
    ])
    const createdExam = await createExamResponse.json()
    expect(createdExam.id).toBeTruthy()
    expect(createdExam.status).toBe('ACTIVE')
    // The picker's whole point: the code that reached the API is the one this
    // tenant's own course carries, not a value baked into the frontend.
    expect(createdExam.course).toBe(JOURNEY_COURSE_CODE)
    // The exact toggle states set above must round-trip through the API.
    expect(createdExam.conditions).toEqual({
      blockAI: true, blockWeb: true, blockCopy: true,
      spellChk: true, phoneBlk: false, aiDetect: true,
    })
    await expect(staffPage.getByText('Examination Created')).toBeVisible({ timeout: 10_000 })
    await expect(staffPage.getByText(examTitle)).toBeVisible({ timeout: 10_000 })
    journey.exam = createdExam
  })

  // ── 3 ────────────────────────────────────────────────────────────────
  test('Save as Draft records a DRAFT exam without publishing it', async ({
    staffPage, workerTenant, request,
  }) => {
    const { draftTitle } = names(workerTenant)
    await openScreen(staffPage, 'Examinations')
    await staffPage.getByRole('button', { name: '+ New Examination' }).click()
    await staffPage.locator('#neTitle').fill(draftTitle)
    await staffPage.locator('#nePrompt0').fill('Outline the sources of constitutional authority.')

    const [draftResponse] = await Promise.all([
      staffPage.waitForResponse(r => r.url().includes('/bluebook/exams') && r.request().method() === 'POST'),
      staffPage.getByRole('button', { name: 'Save as Draft' }).click(),
    ])
    const draftExam = await draftResponse.json()
    expect(draftExam.status).toBe('DRAFT')
    await expect(staffPage.getByText('Examination Created')).toBeVisible({ timeout: 10_000 })
    await expect(staffPage.getByText(draftTitle)).toBeVisible({ timeout: 10_000 })
    await expect(staffPage.getByText('draft', { exact: true })).toBeVisible()

    // The tenant listing now carries both, each under its own status.
    const examsRes = await request.get('/bluebook/exams', { headers: staffAuth(workerTenant) })
    expect(examsRes.ok()).toBe(true)
    const { exams } = await examsRes.json()
    expect(exams.find(e => e.id === draftExam.id)?.status).toBe('DRAFT')
    expect(exams.find(e => e.id === journey.exam.id)?.status).toBe('ACTIVE')
  })

  // ── 4 ────────────────────────────────────────────────────────────────
  test("the professor can preview the published exam's briefing from the Examinations list", async ({
    staffPage, workerTenant,
  }) => {
    const { examTitle } = names(workerTenant)
    await openScreen(staffPage, 'Examinations')
    // Clicking the row loads the exam's config and enters its briefing —
    // the same screen a candidate sees (Dashboard.jsx openExam()).
    await staffPage.getByText(examTitle, { exact: true }).click()
    await expect(staffPage.getByText('Preliminary Instructions')).toBeVisible({ timeout: 10_000 })
    await expect(staffPage.getByText(examTitle)).toBeVisible()
  })

  // ── 5 ────────────────────────────────────────────────────────────────
  test('the student sits the exam and seals a submission that Original scores live', async ({
    studentPage, workerTenant, request,
  }) => {
    // A seal does real quantum scoring against a live baseline — comfortably
    // over the 30s default on a cold run.
    test.setTimeout(90_000)
    const { candidateName } = names(workerTenant)

    // Seed one verified baseline sample first: POST /students/{id}/score
    // 422s with zero authenticated samples, so without this the exam-seal
    // flow's scoring call would silently no-op (aiScore=null) and never
    // write the audit entry the correction step below needs — exactly the
    // "cold start" case a real returning student wouldn't hit.
    await addBaselineFor(request, workerTenant.student.student_id, workerTenant.student.token, {
      text: 'An earlier verified writing sample establishing this student’s baseline voice profile for comparison.',
    })

    // Mirrors exam-flow.spec.mjs's bootInExam(): inject BB_EXAM_CONFIG so
    // the briefing→exam transition is immediate, using the real exam id
    // captured from the publish step (and the same toggle states).
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
    }, [journey.exam, workerTenant.student.student_id, candidateName])

    await studentPage.goto('/bluebook/')
    await studentPage.waitForLoadState('networkidle')
    // Suppress the real fullscreen call — chromium-headless rejects it.
    await studentPage.evaluate(() => {
      Element.prototype.requestFullscreen = function () { return Promise.resolve() }
    })
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
    // The proctored-baseline transmission succeeded (recordSubmission only
    // runs when it does — Exam.jsx handleSubmit).
    await expect(studentPage.getByText('✓ Your writing sample was delivered to Original'))
      .toBeVisible({ timeout: 5_000 })

    // API-side: the submission is recorded against the published exam with
    // a live authorship score, not a null cold-start placeholder.
    // (Exam.jsx awaits recordSubmission before rendering the sealed screen,
    // so there is no race here.)
    const subsRes = await request.get('/bluebook/submissions', { headers: staffAuth(workerTenant) })
    expect(subsRes.ok()).toBe(true)
    const { submissions } = await subsRes.json()
    const mine = submissions.find(s => s.student === candidateName)
    expect(mine).toBeTruthy()
    expect(mine.exam_id).toBe(journey.exam.id)
    expect(typeof mine.aiScore).toBe('number')
    expect(mine.aiScore).toBeGreaterThanOrEqual(0)
    expect(mine.aiScore).toBeLessThanOrEqual(100)
    expect(mine.words).toBeGreaterThan(0)
    expect(['SUBMITTED', 'FLAGGED']).toContain(mine.status)
    journey.submission = mine
  })

  // ── 6 ────────────────────────────────────────────────────────────────
  test('the examinations surface on the Dashboard overview', async ({
    staffPage, workerTenant,
  }) => {
    const { examTitle, draftTitle } = names(workerTenant)
    await openScreen(staffPage) // authed staff land on the dashboard
    await expect(staffPage.getByText(/Good morning/)).toBeVisible({ timeout: 10_000 })
    // Recent Examinations lists this tenant's own exams — both of them.
    await expect(staffPage.getByText(examTitle)).toBeVisible({ timeout: 10_000 })
    await expect(staffPage.getByText(draftTitle)).toBeVisible()
  })

  // ── 7 ────────────────────────────────────────────────────────────────
  test('Results lists the sealed submission with the scores the API reported', async ({
    staffPage, workerTenant,
  }) => {
    const { candidateName } = names(workerTenant)
    await openScreen(staffPage, 'Results')
    await expect(staffPage.getByText(/1 submissions/)).toBeVisible({ timeout: 10_000 })
    await expect(staffPage.getByText(candidateName)).toBeVisible()
    // This is the tenant's only submission, so the rendered percentages are
    // unambiguous — they must match the API payload captured at seal time.
    await expect(staffPage.getByText(`${journey.submission.aiScore}%`).first()).toBeVisible()
    await expect(staffPage.getByText(`${journey.submission.stylometric}%`).first()).toBeVisible()
  })

  // ── 8 ────────────────────────────────────────────────────────────────
  test('drilling into the row reveals the integrity analysis narrative', async ({
    staffPage, workerTenant,
  }) => {
    const { candidateName } = names(workerTenant)
    await openScreen(staffPage, 'Results')
    const resultsRow = staffPage.locator('div', { hasText: candidateName }).last()
    await expect(resultsRow).toBeVisible({ timeout: 10_000 })
    await resultsRow.click()
    await expect(staffPage.getByText('Integrity Analysis')).toBeVisible({ timeout: 5_000 })
    await expect(staffPage.getByText('Typing Consistency').first()).toBeVisible()
    await expect(staffPage.getByText('Authenticity').first()).toBeVisible()
    // The plain-English explanation line under the Authenticity score.
    await expect(staffPage.getByText(/scored via Original/)).toBeVisible()
    // The right-hand panel is the real CorrectionPanel (see step 10 below for
    // the full filing flow) — "Mark Reviewed"/"Examiner's Notes" were the
    // pre-CorrectionPanel local-state placeholder this test used to assert
    // on; both were removed when the real panel replaced them.
    await expect(staffPage.getByText("Examiner's Correction")).toBeVisible()
  })

  // ── 9 ────────────────────────────────────────────────────────────────
  test('the candidate appears on the Students roster built from sealed submissions', async ({
    staffPage, workerTenant,
  }) => {
    const { candidateName } = names(workerTenant)
    await openScreen(staffPage, 'Students')
    await expect(staffPage.getByText(/1 enrolled/)).toBeVisible({ timeout: 10_000 })
    await expect(staffPage.getByText(candidateName)).toBeVisible()

    // The Flagged Only filter behaves per the status recorded at seal time
    // (deterministic — read from the API payload, not guessed).
    await staffPage.getByRole('button', { name: 'Flagged Only' }).click()
    if (journey.submission.status === 'FLAGGED') {
      await expect(staffPage.getByText(candidateName)).toBeVisible()
    } else {
      await expect(staffPage.getByText(candidateName)).toHaveCount(0)
    }
  })

  // ── WS-4 / T7 — click-only rows must be keyboard-operable ─────────────
  // Three rows are `<div>`s wired with onClick only (Dashboard.jsx
  // ExamsScreen, Results.jsx, Students.jsx) — Tab must reach each one and
  // Enter/Space must fire the same handler a click would. Reuses the
  // course/exam/submission this describe block already built rather than
  // re-seeding data, matching the file's stated approach.

  // ── 9a ───────────────────────────────────────────────────────────────
  test('the Examinations list row is keyboard-operable', async ({
    staffPage, workerTenant,
  }) => {
    const { examTitle } = names(workerTenant)
    await openScreen(staffPage, 'Examinations')
    const row = staffPage.getByRole('button', { name: examTitle })
    await expect(row).toBeVisible({ timeout: 10_000 })
    await row.focus()
    await staffPage.keyboard.press('Enter')
    await expect(staffPage.getByText('Preliminary Instructions')).toBeVisible({ timeout: 10_000 })
  })

  // ── 9b ───────────────────────────────────────────────────────────────
  test('the Results row is keyboard-operable and expands the integrity analysis', async ({
    staffPage, workerTenant,
  }) => {
    const { candidateName } = names(workerTenant)
    await openScreen(staffPage, 'Results')
    const row = staffPage.getByRole('button', { name: candidateName })
    await expect(row).toBeVisible({ timeout: 10_000 })
    await expect(row).toHaveAttribute('aria-expanded', 'false')
    await row.focus()
    await staffPage.keyboard.press(' ')
    await expect(staffPage.getByText('Integrity Analysis')).toBeVisible({ timeout: 5_000 })
    await expect(row).toHaveAttribute('aria-expanded', 'true')
  })

  // ── 9c ───────────────────────────────────────────────────────────────
  test('the Students roster row is keyboard-operable', async ({
    staffPage, workerTenant,
  }) => {
    const { candidateName } = names(workerTenant)
    await openScreen(staffPage, 'Students')
    const row = staffPage.getByRole('button', { name: candidateName })
    await expect(row).toBeVisible({ timeout: 10_000 })
    await row.focus()
    await staffPage.keyboard.press('Enter')
    await expect(staffPage.getByText(/1 submissions/)).toBeVisible({ timeout: 10_000 })
  })

  // ── 10 ───────────────────────────────────────────────────────────────
  test('a correction filed against the scored submission lands in corrections and the audit trail', async ({
    workerTenant, request, staffPage,
  }) => {
    await openScreen(staffPage, 'Results')
    // The row rendered for this journey's candidate — same locator the
    // "drilling into the row" test above (step 8) already uses/proves:
    // `div:has-text(candidateName)` picks the innermost matching div (the
    // name/course cell), and the click bubbles up to the row's onClick.
    const { candidateName } = names(workerTenant)
    const row = staffPage.locator('div', { hasText: candidateName }).last()
    await expect(row).toBeVisible({ timeout: 10_000 })
    await row.click()

    // exact:true matters here — Playwright's role-name matching is a
    // substring match by default, and "Correct" is a substring of both
    // "Incorrect" and "File Correction".
    await expect(staffPage.getByRole('button', { name: 'Correct', exact: true })).toBeVisible({ timeout: 10_000 })
    await staffPage.getByRole('button', { name: 'Incorrect' }).click()
    await staffPage.locator('select').first().selectOption('authentic')
    await staffPage.locator('select').nth(1).selectOption('no_action')
    await staffPage.getByPlaceholder('Record observations, decision rationale, or marginal notes…')
      .fill('E2E professor-journey correction')

    const [correctionResponse] = await Promise.all([
      staffPage.waitForResponse(r => r.url().includes('/submissions/') && r.url().includes('/correct') && r.request().method() === 'POST'),
      staffPage.getByRole('button', { name: 'File Correction' }).click(),
    ])
    expect(correctionResponse.ok()).toBe(true)
    const correction = await correctionResponse.json()
    const submissionId = correction.submission_id

    // The filed correction appears in the panel's history immediately.
    await expect(staffPage.getByText('✗ Verdict overridden')).toBeVisible({ timeout: 5_000 })
    await expect(staffPage.getByText('E2E professor-journey correction')).toBeVisible()

    // API-level verification alongside the UI-level one: the pipeline is
    // proven end to end (click → write → audit), not just the click.
    const headers = staffAuth(workerTenant)
    const correctionsListRes = await request.get(
      `/admin/corrections?submission_id=${encodeURIComponent(submissionId)}`,
      { headers },
    )
    expect(correctionsListRes.ok()).toBe(true)
    const correctionsList = await correctionsListRes.json()
    expect(correctionsList.items.some(c => c.notes === 'E2E professor-journey correction')).toBe(true)

    const auditRes = await request.get(
      `/admin/audit?student_id=${encodeURIComponent(workerTenant.student.student_id)}&action=correction`,
      { headers },
    )
    expect(auditRes.ok()).toBe(true)
    const audit = await auditRes.json()
    expect(audit.total).toBeGreaterThan(0)
    expect(audit.items.some(i => i.action === 'correction')).toBe(true)
  })

  // ── 11 ───────────────────────────────────────────────────────────────
  test('a cold-start sitting with no AI score shows the disabled correction state', async ({
    staffPage, request, workerTenant,
  }) => {
    // Record a Bluebook submission the way a real cold-start sitting looks:
    // the seal always generates a submission_uuid (it's threaded into both
    // the submission record and the score call), but scoring 422'd because
    // there was no baseline yet to compare against, so ai_score is null.
    // This is the actual reachable cold-start shape -- not a submission with
    // no uuid at all, which the real Exam.jsx flow never produces.
    //
    // The uuid MUST be unique per run, not a fixed literal: submission_uuid
    // carries a global UNIQUE index (it is the seal idempotency key and is
    // deliberately NOT tenant-scoped), so a hardcoded value would be replayed
    // rather than inserted on any second run against the same database --
    // the POST would still return 200, but it would hand back the *previous*
    // run's row in a different tenant, and this tenant's Results screen would
    // never show the candidate. Deriving it from the per-worker tenant id
    // (itself pid+timestamp-unique, see fixtures/api-setup.mjs:unique) keeps
    // the row genuinely new every run.
    const headers = staffAuth(workerTenant)
    const res = await request.post('/bluebook/submissions', {
      headers,
      data: {
        student_id: `${workerTenant.tenant.tenant_id}:cold-start-candidate`,
        candidate: 'Cold Start Candidate',
        exam_title: 'Unscored Exam',
        course: 'TEST 000',
        word_count: 10,
        time_min: 1,
        status: 'SUBMITTED',
        submission_uuid: `cold-start-seal-${workerTenant.tenant.tenant_id}`,
        ai_score: null,
      },
    })
    expect(res.ok()).toBe(true)

    await openScreen(staffPage, 'Results')
    const row = staffPage.locator('div', { hasText: 'Cold Start Candidate' }).last()
    await expect(row).toBeVisible({ timeout: 10_000 })
    await row.click()
    await expect(staffPage.getByText("This submission wasn't scored — no verdict to correct.")).toBeVisible({ timeout: 10_000 })
    await expect(staffPage.getByRole('button', { name: 'Correct', exact: true })).toHaveCount(0)
  })
})

// ═══════════════════════════════════════════════════════════════════════
// Stage-2 breadth on the same surface (non-serial — no shared state).
// ═══════════════════════════════════════════════════════════════════════

// The picker's two unhappy answers. The happy one — a real course selected and
// round-tripped onto the exam — is journey step 2; these are the two that used
// to be impossible, because a hardcoded list is never empty and never fails.
test.describe('New Examination course picker', () => {
  test('a tenant with no courses gets a typed code and a pointer to Courses, not the demo list', async ({
    browser, baseURL, request,
  }) => {
    const { staff } = await provisionTenantWithStaff(request)
    const context = await browser.newContext({ storageState: staffStorageState(baseURL, staff) })
    const page = await context.newPage()
    await openScreen(page, 'Examinations')
    await page.getByRole('button', { name: '+ New Examination' }).click()
    await expect(page.getByRole('heading', { name: 'New Examination' })).toBeVisible()

    await expect(page.getByText('No courses yet')).toBeVisible({ timeout: 10_000 })
    await expect(page.getByRole('button', { name: /add one on the Courses screen/ })).toBeVisible()
    // MOCK_COURSES leak guard — the same rule the describe below enforces on
    // Dashboard/Results/Students: an authenticated tenant sees its own data.
    await expect(page.getByText('Ethics in the Modern World')).toHaveCount(0)
    // Still usable: the code is typed, and the form gates on title+prompt only.
    await page.locator('#neCourse').fill('PHIL 401')
    await page.locator('#neTitle').fill('Typed-course examination')
    await page.locator('#nePrompt0').fill('A prompt.')
    const [created] = await Promise.all([
      page.waitForResponse(r => r.url().includes('/bluebook/exams') && r.request().method() === 'POST'),
      page.getByRole('button', { name: 'Save as Draft' }).click(),
    ])
    expect((await created.json()).course).toBe('PHIL 401')
    await context.close()
  })

  test('a failed course fetch says so and leaves the form usable', async ({ staffPage }) => {
    // The one state a hardcoded list could not reach. Aborting the request is
    // what BB_API.listCourses() turns into `null` — distinct from an empty
    // roster, and the screen must not present it as one.
    await staffPage.route('**/bluebook/courses', route => route.abort())
    await openScreen(staffPage, 'Examinations')
    await staffPage.getByRole('button', { name: '+ New Examination' }).click()

    await expect(staffPage.getByText(/Your courses could not be loaded/)).toBeVisible({ timeout: 10_000 })
    // A failure is not an empty roster: it must not offer to send the
    // professor off to create a course they may well already have.
    await expect(staffPage.getByText('No courses yet')).toHaveCount(0)
    await expect(staffPage.getByRole('button', { name: /add one on the Courses screen/ })).toHaveCount(0)
    // Publish stays reachable — the failure is non-blocking by construction.
    await staffPage.locator('#neCourse').fill('PHIL 402')
    await staffPage.locator('#neTitle').fill('Degraded-fetch examination')
    await staffPage.locator('#nePrompt0').fill('A prompt.')
    await expect(staffPage.getByRole('button', { name: 'Publish Examination' })).toBeEnabled()
  })
})

test.describe('New Examination form gating', () => {
  test('Publish and Save as Draft stay gated until a title and a prompt exist', async ({ staffPage }) => {
    await openScreen(staffPage, 'Examinations')
    await staffPage.getByRole('button', { name: '+ New Examination' }).click()

    const publish = staffPage.getByRole('button', { name: 'Publish Examination' })
    const draft = staffPage.getByRole('button', { name: 'Save as Draft' })
    await expect(publish).toBeDisabled()
    await expect(draft).toBeDisabled()
    await expect(staffPage.getByText('Title and at least one prompt are required')).toBeVisible()

    await staffPage.locator('#neTitle').fill('Gating check')
    await expect(publish).toBeDisabled() // title alone is not enough

    await staffPage.locator('#nePrompt0').fill('A single prompt unlocks submission.')
    await expect(publish).toBeEnabled()
    await expect(draft).toBeEnabled()
    await expect(staffPage.getByText('Title and at least one prompt are required')).toHaveCount(0)
    // Deliberately do NOT submit — this test owns form gating, not creation.
  })

  test('prompt questions can be added and removed', async ({ staffPage }) => {
    await openScreen(staffPage, 'Examinations')
    await staffPage.getByRole('button', { name: '+ New Examination' }).click()

    await expect(staffPage.getByText('Question I', { exact: true })).toBeVisible()
    await expect(staffPage.getByRole('button', { name: 'Remove' })).toHaveCount(0)

    await staffPage.getByRole('button', { name: '+ Add another question' }).click()
    await expect(staffPage.getByText('Question II', { exact: true })).toBeVisible()
    // With two prompts, every prompt row grows a Remove control.
    await expect(staffPage.getByRole('button', { name: 'Remove' })).toHaveCount(2)

    await staffPage.getByRole('button', { name: 'Remove' }).first().click()
    await expect(staffPage.getByText('Question II', { exact: true })).toHaveCount(0)
    await expect(staffPage.getByRole('button', { name: 'Remove' })).toHaveCount(0)
  })
})

// An authenticated tenant with no data yet must see its own empty surfaces —
// never the hardcoded demo mocks (MOCK_EXAMS / MOCK_RESULTS / MOCK_STUDENTS
// render only for the unauthenticated demo session). A mock leaking into a
// real tenant's console would present fabricated candidates as real people.
test.describe('First-run professor surfaces (fresh tenant, empty states)', () => {
  async function freshStaffPage(browser, baseURL, request) {
    const { staff } = await provisionTenantWithStaff(request)
    const context = await browser.newContext({
      storageState: staffStorageState(baseURL, staff),
    })
    const page = await context.newPage()
    return { page, context }
  }

  test('Dashboard shows the empty tenant, not the demo mock exams', async ({ browser, baseURL, request }) => {
    const { page, context } = await freshStaffPage(browser, baseURL, request)
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    await expect(page.getByText(/Good morning/)).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('Recent Examinations')).toBeVisible()
    await expect(page.getByText('Ethics in the Modern World')).toHaveCount(0) // MOCK_EXAMS leak guard
    await context.close()
  })

  test('Results shows zero submissions, not the demo mock candidates', async ({ browser, baseURL, request }) => {
    const { page, context } = await freshStaffPage(browser, baseURL, request)
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: 'Results' }).click()
    await expect(page.getByText(/0 submissions/)).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('James Thornton')).toHaveCount(0) // MOCK_RESULTS leak guard
    await context.close()
  })

  test('Students shows zero enrolled, not the demo mock roster', async ({ browser, baseURL, request }) => {
    const { page, context } = await freshStaffPage(browser, baseURL, request)
    await page.goto('/bluebook/')
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: 'Students' }).click()
    await expect(page.getByText(/0 enrolled/)).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('James Thornton')).toHaveCount(0) // MOCK_STUDENTS leak guard
    await context.close()
  })
})

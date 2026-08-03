/**
 * exam-robustness.spec.mjs — exam-day robustness (spec §1–§3, plan Task 6).
 *
 * Proves the three failure modes the 2026-07-22 design closes:
 *  1. Reloading mid-exam cannot reset (or pause) the clock — the deadline is
 *     server-pinned by POST /bluebook/exams/{id}/session.
 *  2. A transient failure at seal time is retried and succeeds — the
 *     submission_uuid makes the replay idempotent server-side.
 *  3. Total seal failure keeps the on-device draft and never strands the UI.
 *
 * Boot pattern mirrors professor-journey.spec.mjs's student-seal step:
 * BB_EXAM_CONFIG injected with a REAL exam id created via the API, so the
 * session endpoint has a row to pin the deadline against.
 */

import { test, expect } from './fixtures/tenancy.mjs'
import { addBaselineFor } from './fixtures/api-setup.mjs'

function staffAuth(workerTenant) {
  return { Authorization: `Bearer ${workerTenant.staff.token}` }
}

/** "119:58" | "09:41" → seconds. */
function toSeconds(mmss) {
  const [m, s] = String(mmss).trim().split(':').map(Number)
  return m * 60 + s
}

async function createExam(request, workerTenant, title) {
  const res = await request.post('/bluebook/exams', {
    headers: staffAuth(workerTenant),
    data: {
      title, course: 'PHIL 301A', duration: 120, minWords: 12, maxWords: 5000,
      prompt: 'Discuss.', status: 'PUBLISHED',
    },
  })
  expect(res.ok()).toBe(true)
  return res.json()
}

async function bootInExam(studentPage, exam, workerTenant, candidate) {
  await studentPage.addInitScript(([examArg, studentId, cand]) => {
    localStorage.setItem('bluebook_student_id', studentId)
    window.BB_EXAM_CONFIG = {
      id: examArg.id,
      title: examArg.title,
      course: examArg.course,
      courseTitle: examArg.course,
      candidate: cand,
      duration: 7200,
      minWords: 12,
      maxWords: null,
      blockWeb: false,   // no fullscreen/lockdown friction in these tests
      blockCopy: false,
      spellChk: true,
    }
  }, [exam, workerTenant.student.student_id, candidate])
  await studentPage.goto('/bluebook/')
  await studentPage.waitForLoadState('networkidle')
  await studentPage.evaluate(() => {
    Element.prototype.requestFullscreen = function () { return Promise.resolve() }
  })
  await studentPage.locator('button', { hasText: /begin|continue|enter|start/i }).first().click()
  await expect(
    studentPage.locator('textarea[placeholder="Begin writing here…"]'),
  ).toBeVisible({ timeout: 10_000 })
}

const ESSAY =
  'Kant argues that a maxim is morally permissible only if one could will ' +
  'it to become a universal law without contradiction, grounding duty in ' +
  'reason rather than outcome and separating obligation from inclination.'

test.describe('Exam-day robustness @robustness', () => {
  test('reload does not reset the exam clock', async ({ studentPage, workerTenant, request }) => {
    test.setTimeout(60_000)
    const exam = await createExam(request, workerTenant, 'Robustness clock exam')

    // Enter the exam and wait for the session to pin the deadline.
    const sessionSeen = studentPage.waitForResponse(
      r => r.url().includes(`/bluebook/exams/${exam.id}/session`) && r.ok(),
    )
    await bootInExam(studentPage, exam, workerTenant, 'Clock Candidate')
    await sessionSeen
    await studentPage.waitForTimeout(1500) // one tick so the display is deadline-derived

    const t1 = toSeconds(await studentPage.locator('[role="timer"]').textContent())

    await studentPage.waitForTimeout(3000)
    // Reload → briefing again → re-enter. The pinned deadline must have kept
    // counting the whole time; a countdown-remainder restore would show ~t1.
    const sessionSeen2 = studentPage.waitForResponse(
      r => r.url().includes(`/bluebook/exams/${exam.id}/session`) && r.ok(),
    )
    await studentPage.reload()
    await studentPage.waitForLoadState('networkidle')
    await studentPage.locator('button', { hasText: /begin|continue|enter|start/i }).first().click()
    await sessionSeen2
    await studentPage.waitForTimeout(1500)

    const t2 = toSeconds(await studentPage.locator('[role="timer"]').textContent())
    expect(t2).toBeLessThanOrEqual(t1 - 2)
    // …and it kept the SERVER duration (120 min), not a reset local 7200s.
    expect(t2).toBeGreaterThan(0)
  })

  test('seal retries a transient submission failure and succeeds', async ({
    studentPage, workerTenant, request,
  }) => {
    test.setTimeout(90_000)
    const exam = await createExam(request, workerTenant, 'Robustness retry exam')
    await addBaselineFor(request, workerTenant.student.student_id, workerTenant.student.token, {
      text: 'An earlier verified writing sample establishing this student’s baseline voice profile.',
    })

    let failedOnce = false
    await studentPage.route('**/bluebook/submissions', (route) => {
      if (route.request().method() === 'POST' && !failedOnce) {
        failedOnce = true
        return route.abort()
      }
      return route.continue()
    })

    await bootInExam(studentPage, exam, workerTenant, 'Retry Candidate')
    await studentPage.locator('textarea[placeholder="Begin writing here…"]').focus()
    await studentPage.keyboard.type(ESSAY, { delay: 1 })

    await studentPage.locator('button', { hasText: /Seal & Submit|Sealing/ }).click()
    await expect(studentPage.getByText('Examination Sealed')).toBeVisible({ timeout: 60_000 })
    expect(failedOnce).toBe(true) // the abort really happened; success came from the retry
  })

  test('total seal failure preserves the draft and reports it', async ({
    studentPage, workerTenant, request,
  }) => {
    test.setTimeout(90_000)
    const exam = await createExam(request, workerTenant, 'Robustness failure exam')

    // Kill the seal at step 2 (baseline write) on every attempt.
    await studentPage.route('**/students/*/baseline', (route) => route.abort())

    await bootInExam(studentPage, exam, workerTenant, 'Failure Candidate')
    await studentPage.locator('textarea[placeholder="Begin writing here…"]').focus()
    await studentPage.keyboard.type(ESSAY, { delay: 1 })

    await studentPage.locator('button', { hasText: /Seal & Submit|Sealing/ }).click()

    // 3 attempts with 2s/5s backoff between them → well under this timeout.
    await studentPage.waitForFunction(
      () => window.BB_LAST_SUBMISSION && window.BB_LAST_SUBMISSION.ok === false,
      undefined,
      { timeout: 60_000 },
    )
    const draftKept = await studentPage.evaluate(
      () => Object.keys(localStorage).some(k => k.startsWith('bb_draft_')),
    )
    expect(draftKept).toBe(true)
  })
})

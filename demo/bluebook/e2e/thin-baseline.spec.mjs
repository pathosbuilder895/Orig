/**
 * thin-baseline.spec.mjs: NORTH_STAR rule 3 ("Inconclusive is a valid
 * answer") at the seal.
 *
 * With fewer than 3 approved reference samples Original cannot tell, so a
 * sealed exam is recorded INCONCLUSIVE with no score, never marked "worth a
 * look". With 3 it is read normally. The seal decides this from
 * baseline_integrity.readiness in the /students/{id}/score response
 * (Exam.jsx, bbScoreWithOriginal and bbSealStatus).
 *
 * Each test gets a fresh student so earlier specs' baseline samples on the
 * worker's shared student cannot change the count.
 */

import { test, expect } from './fixtures/tenancy.mjs'
import { addBaselineFor, studentLogin, studentStorageState } from './fixtures/api-setup.mjs'

const staffAuth = workerTenant => ({ Authorization: `Bearer ${workerTenant.staff.token}` })

const ESSAY =
  'Kant argues that a maxim is morally permissible only if one could will ' +
  'it to become a universal law without contradiction, grounding duty in ' +
  'reason rather than outcome and separating obligation from inclination.'

const SAMPLES = [
  'An earlier verified writing sample establishing this student’s baseline voice profile for comparison.',
  'A second approved piece in which the student reflects on duty, consequence and the shape of a good argument.',
  'A third approved essay where the student weighs inclination against obligation in ordinary moral choices.',
]

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

async function sealAsNewStudent({ browser, request, workerTenant }, samples, title) {
  const student = await studentLogin(request, { staffToken: workerTenant.staff.token })
  for (const text of samples) {
    await addBaselineFor(request, student.student_id, student.token, { text })
  }
  const exam = await createExam(request, workerTenant, title)
  const candidate = `Thin ${samples.length} ${Date.now()}`

  const context = await browser.newContext({
    storageState: studentStorageState(workerTenant.baseURL, student),
  })
  const page = await context.newPage()
  await page.addInitScript(([examArg, studentId, cand]) => {
    localStorage.setItem('bluebook_student_id', studentId)
    window.BB_EXAM_CONFIG = {
      id: examArg.id, title: examArg.title, course: examArg.course,
      courseTitle: examArg.course, candidate: cand, duration: 7200,
      minWords: 12, maxWords: null, blockWeb: false, blockCopy: false, spellChk: true,
      aiDetect: true, // writing consistency is off by default
    }
  }, [exam, student.student_id, candidate])
  await page.goto('/bluebook/')
  await page.waitForLoadState('networkidle')
  await page.locator('button', { hasText: /begin|continue|enter|start/i }).first().click()
  const box = page.locator('textarea[placeholder="Begin writing here…"]')
  await expect(box).toBeVisible({ timeout: 10_000 })
  await box.focus()
  await page.keyboard.type(ESSAY, { delay: 1 })
  page.once('dialog', d => d.accept())
  await page.locator('button', { hasText: /Seal & Submit|Sealing/ }).click()
  await expect(page.getByText('✓ Delivered to your teacher')).toBeVisible({ timeout: 60_000 })
  await context.close()

  const res = await request.get('/bluebook/submissions', { headers: staffAuth(workerTenant) })
  expect(res.ok()).toBe(true)
  const { submissions } = await res.json()
  const mine = submissions.find(s => s.exam_id === exam.id)
  expect(mine).toBeTruthy()
  return mine
}

test.describe('Thin baselines read as inconclusive @original', () => {
  test('one approved sample: the exam is INCONCLUSIVE with no score', async ({
    browser, request, workerTenant,
  }) => {
    test.setTimeout(90_000)
    const sub = await sealAsNewStudent({ browser, request, workerTenant }, SAMPLES.slice(0, 1), 'Thin baseline exam')
    expect(sub.status).toBe('INCONCLUSIVE')
    expect(sub.aiScore).toBeNull()
  })

  test('three approved samples: the exam is read normally', async ({
    browser, request, workerTenant,
  }) => {
    test.setTimeout(90_000)
    const sub = await sealAsNewStudent({ browser, request, workerTenant }, SAMPLES, 'Ready baseline exam')
    expect(['SUBMITTED', 'FLAGGED']).toContain(sub.status)
    expect(typeof sub.aiScore).toBe('number')
  })
})

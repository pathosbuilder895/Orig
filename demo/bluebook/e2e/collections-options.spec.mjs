/**
 * collections-options.spec.mjs: the collection options on the one
 * New collection form (Collections merge PR 2): in class vs take-home,
 * timed vs untimed, and the Smalls/Greats preset (cutoff 1,000 words).
 * The server rules are covered by tests/test_collections_options.py.
 */

import { test, expect } from './fixtures/tenancy.mjs'
import { isolatedTest } from './fixtures/tenancy.mjs'

test('a take-home Great is untimed, starts at 1,000 words and is listed as such', async ({ staffPage, workerTenant }) => {
  const title = `E2E Take-home Great ${workerTenant.tenant.tenant_id}`
  await staffPage.goto('/bluebook/')
  await staffPage.waitForLoadState('networkidle')
  await staffPage.getByRole('button', { name: 'Collections', exact: true }).click()
  await staffPage.getByRole('button', { name: '+ New collection' }).click()
  await staffPage.locator('#neTitle').fill(title)
  await staffPage.locator('#nePrompt0').fill('Write about a place you know well.')
  await staffPage.locator('#neMore summary').click()

  await staffPage.locator('#neSetting').selectOption('take_home')
  await expect(staffPage.getByRole('switch', { name: 'Timed' })).toHaveAttribute('aria-checked', 'false')
  await expect(staffPage.getByRole('switch', { name: 'Full-screen, tabs watched' })).toHaveAttribute('aria-checked', 'false')
  await expect(staffPage.getByText('No time limit', { exact: true })).toBeVisible()
  await staffPage.locator('#neSize').selectOption('great')
  await expect(staffPage.locator('#neMinWords')).toHaveValue('1000')

  const [created] = await Promise.all([
    staffPage.waitForResponse(r => r.url().endsWith('/bluebook/exams') && r.request().method() === 'POST'),
    staffPage.getByRole('button', { name: 'Publish Collection' }).click(),
  ])
  const body = await created.json()
  expect(body.conditions).toMatchObject({ timed: false, setting: 'take_home', size: 'great' })
  expect(body.minWords).toBe(1000)

  await expect(staffPage.getByRole('heading', { name: 'Collections' })).toBeVisible({ timeout: 10_000 })
  const row = staffPage.getByRole('row', { name: new RegExp(title) })
  await expect(row).toContainText('Take-home · Great')
  await expect(row).toContainText('untimed')
})

isolatedTest('an untimed sitting shows no clock', async ({ studentPage, testTenant, request }) => {
  const res = await request.post('/bluebook/exams', {
    headers: { Authorization: `Bearer ${testTenant.staff.token}` },
    data: { title: 'Untimed', course: 'HIST 110', duration: 25, prompt: 'Describe a walk.', status: 'ACTIVE', conditions: { timed: false } },
  })
  expect(res.ok()).toBe(true)
  const exam = await res.json()
  await studentPage.addInitScript(([e, sid]) => {
    localStorage.setItem('bluebook_student_id', sid)
    window.BB_EXAM_CONFIG = {
      id: e.id, title: e.title, course: e.course, courseTitle: e.course, candidate: 'Untimed Candidate',
      duration: 25, minWords: 0, maxWords: 0, prompt: e.prompt, timed: false,
      blockAI: true, blockWeb: false, blockCopy: true, phoneBlk: false, spellChk: false,
    }
  }, [exam, testTenant.student.student_id])
  await studentPage.goto('/bluebook/')
  await studentPage.waitForLoadState('networkidle')
  await expect(studentPage.getByText(/no time limit/i).first()).toBeVisible()
  await studentPage.getByRole('button', { name: 'Begin Examination' }).click()
  await expect(studentPage.getByLabel('Your examination answer')).toBeVisible()
  await expect(studentPage.getByText('No time limit')).toBeVisible()
  await expect(studentPage.getByRole('timer')).toHaveCount(0)
})

/**
 * collections-options.spec.mjs: the collection options on the one
 * New collection form (Collections merge PR 2): in class vs take-home,
 * timed vs untimed, and the Smalls/Greats preset (Smalls 1,000 words and under, Greats over 1,000).
 * The server rules are covered by tests/test_collections_options.py.
 */

import { test, expect } from './fixtures/tenancy.mjs'
import { isolatedTest } from './fixtures/tenancy.mjs'

test('a take-home Great is untimed, starts above 1,000 words and is listed as such', async ({ staffPage, workerTenant }) => {
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
  await expect(staffPage.locator('#neMinWords')).toHaveValue('1001')

  const [created] = await Promise.all([
    staffPage.waitForResponse(r => r.url().endsWith('/bluebook/exams') && r.request().method() === 'POST'),
    staffPage.getByRole('button', { name: 'Publish Collection' }).click(),
  ])
  const body = await created.json()
  expect(body.conditions).toMatchObject({ timed: false, setting: 'take_home', size: 'great' })
  expect(body.minWords).toBe(1001)

  await expect(staffPage.getByRole('heading', { name: 'Collections' })).toBeVisible({ timeout: 10_000 })
  const card = staffPage.getByRole('article', { name: title })
  await expect(card.getByRole('list', { name: 'Options' })).toContainText('Great')
  await expect(card).toContainText('Untimed')
  await expect(card).toContainText('Take-home')
})

test('the Collections list is cards with filters and search; a card opens only when its title is clicked', async ({ browser, request, workerTenant }) => {
  const T = workerTenant
  const auth = { Authorization: `Bearer ${T.staff.token}` }
  const tag = `${T.tenant.tenant_id.slice(-6)}-${Date.now()}`
  const make = async (title, extra) => {
    const r = await request.post('/bluebook/exams', { headers: auth, data: { title, course: 'CARD 101', duration: 25, prompt: 'Write.', status: 'ACTIVE', ...extra } })
    expect(r.ok(), await r.text()).toBe(true)
  }
  await make(`Card small take-home ${tag}`, { conditions: { timed: false, setting: 'take_home', size: 'small', blockCopy: false } })
  await make(`Card great locked ${tag}`, { conditions: { size: 'great', blockCopy: true } })
  await make(`Card plain ${tag}`, { conditions: { blockCopy: true } })
  const { staffStorageState } = await import('./fixtures/api-setup.mjs')
  const ctx = await browser.newContext({ storageState: staffStorageState(T.baseURL, T.staff) })
  const page = await ctx.newPage()
  await page.goto('/bluebook/#collections')
  await expect(page.getByRole('heading', { name: 'Collections' })).toBeVisible({ timeout: 10_000 })
  const titles = () => page.locator('.bb-coll-title').allInnerTexts()
  // Search narrows to this test's three collections.
  await page.locator('#collSearch').fill(tag)
  await expect(page.locator('.bb-coll')).toHaveCount(3)
  // Filters.
  await page.locator('#collSize').selectOption('great')
  await expect(page.locator('.bb-coll')).toHaveCount(1)
  expect(await titles()).toEqual([`Card great locked ${tag}`])
  await page.locator('#collSize').selectOption('')
  await page.locator('#collTiming').selectOption('untimed')
  expect(await titles()).toEqual([`Card small take-home ${tag}`])
  await page.locator('#collTiming').selectOption('')
  await page.locator('#collPaste').selectOption('open')
  expect(await titles()).toEqual([`Card small take-home ${tag}`])
  await page.locator('#collPaste').selectOption('locked')
  await expect(page.locator('.bb-coll')).toHaveCount(2)
  await page.locator('#collSetting').selectOption('take_home')
  await expect(page.getByText('No collections match these filters.')).toBeVisible()
  await page.getByRole('button', { name: 'Clear filters' }).first().click()
  await expect(page.locator('#collSearch')).toHaveValue('')
  // The card for an untimed take-home Small says so.
  const small = page.getByRole('article', { name: `Card small take-home ${tag}` })
  await expect(small.getByRole('list', { name: 'Options' })).toHaveText(/Small.*Untimed.*Open · paste allowed.*Take-home/s)
  // Only the title opens a collection.
  await small.locator('.bb-coll-tags').click()
  await expect(page.getByRole('heading', { name: 'Collections' })).toBeVisible()
  await small.getByRole('button', { name: `Card small take-home ${tag}` }).click()
  await expect(page.getByRole('heading', { name: `Card small take-home ${tag}` })).toBeVisible({ timeout: 10_000 })
  await ctx.close()
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

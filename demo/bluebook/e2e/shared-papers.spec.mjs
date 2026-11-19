/**
 * shared-papers.spec.mjs — Voice Baseline's "Papers students shared" (2026-11,
 * four-paper alpha). A volunteer shares four papers; the teacher approves
 * three, reads the fourth without adding it (it is the held-out paper they
 * paste into Writing State), and undoes an approval made by mistake. Nothing
 * else moves: the other papers stay in the baseline, and the student still
 * sees statuses only.
 *
 * Its own tenant (isolatedTest), so the baseline counts are its own.
 * SHOT_DIR=/some/folder saves screenshots of the actions (local runs only).
 */

import { isolatedTest as test, expect } from './fixtures/tenancy.mjs'
import { staffStorageState } from './fixtures/api-setup.mjs'

const paper = (n, topic) => `Paper ${n}. ` + `I have been thinking about ${topic} for a long time, and the more I look the less simple it seems. `.repeat(6)
const TOPICS = ['the river behind our house', 'learning to cook', 'my first job', 'why I keep a notebook']
const shot = async (page, name) => {
  if (process.env.SHOT_DIR) await page.screenshot({ path: `${process.env.SHOT_DIR}/${name}.png`, fullPage: false })
}

test('read a held-out paper without adding it, and undo an approval', async ({ browser, testTenant, request }) => {
  test.setTimeout(120_000)
  const T = testTenant
  const staff = { Authorization: `Bearer ${T.staff.token}` }
  const student = { Authorization: `Bearer ${T.student.token}` }
  const sid = T.student.student_id
  for (let k = 0; k < 4; k++) {
    const r = await request.post('/bluebook/me/papers', { headers: student, multipart: { text: paper(k + 1, TOPICS[k]), title: `Paper ${k + 1}` } })
    expect(r.status(), await r.text()).toBe(201)
  }
  const ids = Object.fromEntries((await (await request.get('/bluebook/past-papers', { headers: staff })).json()).papers.map(p => [p.title, p.paper_id]))
  // Andrew approves all four by mistake, then takes Paper 4 back out.
  for (let k = 1; k <= 4; k++) {
    const r = await request.post(`/bluebook/past-papers/${ids[`Paper ${k}`]}/approve`, { headers: staff })
    expect(r.ok(), await r.text()).toBe(true)
  }

  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, storageState: staffStorageState(T.baseURL, T.staff) })
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: T.baseURL })
  const page = await ctx.newPage()
  await page.goto(`/original/baseline.html?student=${encodeURIComponent(sid)}`)
  const sec = page.locator('#shared-sec')
  const row = n => sec.locator('.ex', { hasText: `Paper ${n}` })
  await expect(row(4)).toContainText('In the baseline', { timeout: 15_000 })
  await expect(row(4).getByRole('button', { name: 'Approve' })).toHaveCount(0)
  await row(4).scrollIntoViewIfNeeded()
  await shot(page, '1-approved-with-undo')

  await test.step('undo takes only that paper out; it waits for approval again', async () => {
    await row(4).getByRole('button', { name: 'Undo approval' }).click()
    await expect(row(4)).toContainText('Taken back out of the baseline. It is waiting for your approval again.', { timeout: 15_000 })
    await expect(row(4)).toContainText('Waiting for approval')
    await expect(row(4).getByRole('button', { name: 'Approve' })).toBeVisible()
    for (const n of [1, 2, 3]) await expect(row(n)).toContainText('In the baseline')
    const listed = (await (await request.get('/bluebook/past-papers', { headers: staff })).json()).papers
    expect(Object.fromEntries(listed.map(p => [p.title, p.status]))).toEqual({
      'Paper 1': 'approved', 'Paper 2': 'approved', 'Paper 3': 'approved', 'Paper 4': 'pending',
    })
    const prof = await (await request.get(`/students/${encodeURIComponent(sid)}`, { headers: staff })).json()
    expect(prof.sample_count).toBe(3)
    await shot(page, '2-after-undo')
  })

  await test.step('read the held-out paper: its text, copy, and a way to Writing State; nothing is added', async () => {
    await row(4).getByRole('button', { name: 'Read this paper' }).click()
    const panel = row(4).locator('.sh-read')
    await expect(panel.locator('.pb')).toContainText('I have been thinking about why I keep a notebook', { timeout: 15_000 })
    await expect(row(4).getByRole('button', { name: 'Hide paper' })).toHaveAttribute('aria-expanded', 'true')
    const link = panel.getByRole('link', { name: /Open Writing State for/ })
    await expect(link).toHaveAttribute('href', `writing-state.html?student=${encodeURIComponent(sid)}`)
    await panel.getByRole('button', { name: 'Copy text' }).click()
    await expect(panel.getByRole('button', { name: 'Copied' })).toBeVisible()
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(paper(4, TOPICS[3]).trim())
    await shot(page, '3-read-held-out-paper')
    await panel.getByRole('button', { name: 'Close' }).click()
    await expect(row(4).locator('.sh-read')).toHaveCount(0)
    await expect(row(4)).toContainText('Waiting for approval')
    const prof = await (await request.get(`/students/${encodeURIComponent(sid)}`, { headers: staff })).json()
    expect(prof.sample_count).toBe(3)
  })

  await test.step('the student sees statuses only', async () => {
    const mine = await (await request.get('/bluebook/me/papers', { headers: student })).json()
    expect(mine.papers.map(p => p.status).sort()).toEqual(['approved', 'approved', 'approved', 'pending'])
    expect(JSON.stringify(mine)).not.toMatch(/score|feature|drift|sample_count|removed/i)
  })

  await test.step('the actions honour the Text setting', async () => {
    await page.evaluate(() => { localStorage.setItem('bb.display.v1', JSON.stringify({ font: 'sans', size: 'xxlarge' })) })
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-bb-size', 'xxlarge')
    await expect(row(4)).toContainText('Waiting for approval', { timeout: 15_000 })
    await row(4).getByRole('button', { name: 'Read this paper' }).click()
    await expect(row(4).locator('.sh-read .pb')).toContainText('notebook', { timeout: 15_000 })
    await row(4).scrollIntoViewIfNeeded()
    await shot(page, '4-read-largest-text')
    // No sideways scroll at the largest size.
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1280)
  })
  await ctx.close()
})

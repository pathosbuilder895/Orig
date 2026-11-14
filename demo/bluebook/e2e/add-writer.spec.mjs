/**
 * add-writer.spec.mjs: a teacher adds an alpha writer by name, with no
 * course, email, invite or account, makes a baseline from three papers and
 * analyses a fourth.
 *
 * "Add a writer" on Original's Students page posts to POST /students (staff
 * only) and opens the new writer's Voice baseline at Add writing. The papers
 * are public-domain passages: three of J. S. Mill's On Liberty (1859) for the
 * baseline and one of G. K. Chesterton's Orthodoxy (1908) to analyse.
 */

import { readFileSync } from 'node:fs'
import { isolatedTest as test, expect } from './fixtures/tenancy.mjs'
import { staffStorageState } from './fixtures/api-setup.mjs'

const FIXTURES = new URL('./fixtures/evidence/', import.meta.url)
const read = name => readFileSync(new URL(name, FIXTURES), 'utf8')
const uid = () => `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`

test('a teacher adds a writer, builds their baseline and analyses a paper', async ({ browser, request, testTenant }) => {
  test.setTimeout(180_000)
  const { staff, baseURL } = testTenant
  const name = `Alpha Writer ${uid()}`
  const context = await browser.newContext({ storageState: staffStorageState(baseURL, staff) })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', e => errors.push(e.message))

  await page.goto('/original/students.html')
  await expect(page.getByRole('link', { name: 'Add to a Collections course' })).toHaveAttribute('href', '/bluebook/#students')
  const open = page.getByRole('button', { name: 'Add a writer' })
  const field = page.getByLabel('Their name')

  // Escape closes the form and hands focus back to the button.
  await open.click()
  await expect(open).toHaveAttribute('aria-expanded', 'true')
  await expect(field).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.locator('#writer-form')).toBeHidden()
  await expect(open).toBeFocused()

  // An empty name is refused on the page, with nothing sent.
  await open.click()
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(page.locator('#writer-msg')).toHaveText('Type the writer’s name.')

  await field.fill(`  ${name}  `)
  const created = page.waitForResponse(r => new URL(r.url()).pathname === '/students' && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  const res = await created
  expect(res.status()).toBe(201)
  expect(JSON.parse(res.request().postData())).toEqual({ name })
  // The page leaves at once, so the new id is read off the address it opens.
  await expect(page).toHaveURL(url => url.pathname === '/original/baseline.html' && url.hash === '#add-writing')
  const writerId = new URL(page.url()).searchParams.get('student')
  expect(writerId).toMatch(new RegExp(`^${staff.tenant_id}:[0-9a-f]{16}$`))
  const enc = encodeURIComponent(writerId)
  expect(new URL(page.url()).search).toBe(`?student=${enc}`)

  // Three papers verified by the teacher, pasted on the Voice baseline.
  await expect(page.locator('#paste-text')).toBeVisible({ timeout: 20_000 })
  for (const i of [1, 2, 3]) {
    await page.locator('#paste-text').fill(read(`mill-${i}.txt`))
    await page.locator('#paste-assign').fill(`On Liberty, part ${i}`)
    await page.locator('#paste-go').click()
    await expect(page.locator('#add-msg')).toContainText(`Added as sample ${i}.`, { timeout: 30_000 })
  }

  // The writer is on the roster under their name, like any student.
  await page.goto('/original/students.html')
  const row = page.locator('.r-row').filter({ hasText: name })
  await expect(row).toHaveCount(1, { timeout: 20_000 })
  await expect(row.getByRole('link', { name })).toHaveAttribute('href', `baseline.html?student=${enc}`)

  // The fourth paper, analysed on Writing State.
  await row.getByRole('link', { name: 'Writing State' }).click()
  await expect(page.locator('#an-form')).toBeVisible({ timeout: 20_000 })
  await page.locator('#an-assign').fill('Orthodoxy, chapter 1')
  await page.locator('#an-text').fill(read('chesterton.txt'))
  const scored = page.waitForResponse(r => r.url().endsWith('/score') && r.request().method() === 'POST', { timeout: 90_000 })
  await page.locator('#an-go').click()
  const score = await scored
  expect(score.ok()).toBe(true)
  expect(new URL(score.url()).pathname).toBe(`/students/${enc}/score`)
  await expect(page.locator('#an-done')).toBeVisible({ timeout: 30_000 })
  expect(errors).toEqual([])
  await context.close()

  // Erasing the writer takes them off the roster.
  const teacher = { Authorization: `Bearer ${staff.token}` }
  const gone = await request.delete(`/students/${enc}`, { headers: teacher })
  expect(gone.status(), await gone.text()).toBe(200)
  const roster = await (await request.get('/students', { headers: teacher })).json()
  expect(roster.roster.map(r => r.id)).not.toContain(writerId)
})

test('a student cannot add a writer', async ({ request, testTenant }) => {
  const { staff, student } = testTenant
  const res = await request.post('/students', {
    headers: { Authorization: `Bearer ${student.token}` }, data: { name: 'Not Allowed' },
  })
  // A real deploy (this server runs ORIGINAL_ENV=pilot, like CI's) refuses a
  // student on the staff-only /students path before the route runs, with 401;
  // off one the route's own staff check answers 403 (tests/test_add_writer.py).
  expect(res.status(), await res.text()).toBe(401)
  const roster = await (await request.get('/students', { headers: { Authorization: `Bearer ${staff.token}` } })).json()
  expect(roster.roster.map(r => r.name)).not.toContain('Not Allowed')
})

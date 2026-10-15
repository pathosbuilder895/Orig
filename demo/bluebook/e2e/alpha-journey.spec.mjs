/**
 * alpha-journey.spec.mjs: the alpha test's whole journey, through the UI.
 *
 * A teacher (in a workspace that holds Original, as the alpha's does) creates
 * a course and two 25-minute exams with paste blocked and writing consistency
 * off, adds students with email off and copies every invite link at once.
 * Students join from a phone: they set a password, accept the terms and land
 * in the course. One writes exam A, tries to paste, refreshes in the middle,
 * comes back to the same booklet and seals it; nothing they see hints at a
 * score. The teacher watches the sitting live, exports the submissions, and
 * checks every student has enough reference papers on the Original page.
 *
 * Its own tenant (isolatedTest): it seals submissions, and the shared worker
 * tenant's submission counts belong to professor-journey.spec.mjs.
 */

import { readFileSync } from 'node:fs'
import { isolatedTest as test, expect } from './fixtures/tenancy.mjs'
import { staffStorageState } from './fixtures/api-setup.mjs'

const PHONE = { width: 375, height: 812 }
const LAPTOP = { width: 1280, height: 800 }
const PASSWORD = 'alpha-e2e-pass-1'
const ESSAY = 'At midnight the market wakes. The stall at the end of the lane sells hours that people lost, weighed on a brass scale. '

// Every dialog the journey meets is one a person would accept: the seal's
// "Ready to submit?", "Issue fresh links?", and the exam's leave-page guard.
function acceptDialogs(page) {
  page.on('dialog', d => d.accept().catch(() => {}))
}

async function newPage(browser, baseURL, { viewport = LAPTOP, storageState } = {}) {
  const context = await browser.newContext({ viewport, storageState })
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: baseURL })
  await context.addInitScript(() => {
    // Headless Chromium's full screen is real but flaky to leave; the exam only needs the call to succeed.
    Element.prototype.requestFullscreen = function () { return Promise.resolve() }
  })
  const page = await context.newPage()
  acceptDialogs(page)
  return page
}

async function createExamThroughTheForm(teacher, title, question) {
  await teacher.getByRole('navigation', { name: 'Teacher navigation' }).getByRole('button', { name: 'Examinations', exact: true }).click()
  await teacher.getByRole('button', { name: '+ New examination' }).click()
  // Optional word limits start empty: a minimum nobody asked for would hold back the submit button.
  await expect(teacher.locator('#neMinWords')).toHaveValue('')
  await expect(teacher.locator('#neMaxWords')).toHaveValue('')
  await teacher.locator('#neTitle').fill(title)
  await teacher.locator('#neDuration').fill('25')
  await teacher.locator('#nePrompt0').fill(question)
  await expect(teacher.getByRole('switch', { name: 'Block copy & paste' })).toHaveAttribute('aria-checked', 'true')
  await expect(teacher.getByRole('switch', { name: /Writing consistency \(in testing\)/ })).toHaveAttribute('aria-checked', 'false')
  await teacher.getByRole('button', { name: 'Publish Examination' }).click()
  await expect(teacher.getByRole('heading', { name: 'Examinations' })).toBeVisible({ timeout: 10_000 })
}

test.describe('Alpha journey @alpha', () => {
  test('course, two exams, invites, a phone join, a sitting with a refresh, live view, export and reference papers', async ({
    browser, testTenant, request,
  }) => {
    test.setTimeout(240_000)
    const T = testTenant
    const staffAuth = { Authorization: `Bearer ${T.staff.token}` }
    const tag = T.tenant.tenant_id.slice(-6)
    const people = ['Alpha Ada', 'Alpha Ben', 'Alpha Cy'].map((name, i) => ({ name, email: `alpha-${tag}-${i + 1}@e2e.test` }))
    const teacher = await newPage(browser, T.baseURL, { storageState: staffStorageState(T.baseURL, T.staff) })

    await test.step('the teacher frame says Collections and labels Original as in testing', async () => {
      await teacher.goto('/bluebook/')
      const nav = teacher.getByRole('navigation', { name: 'Teacher navigation' })
      await expect(nav.getByRole('button', { name: 'Sessions', exact: true })).toBeVisible({ timeout: 10_000 })
      await expect(nav.locator('.teacher-brand')).toHaveText('Collections')
      await expect(nav.getByRole('button', { name: 'Original (in testing) ↗' })).toBeVisible()
    })

    let links
    await test.step('course and students with email off; one button copies every invite link', async () => {
      await teacher.getByRole('navigation', { name: 'Teacher navigation' }).getByRole('button', { name: 'Courses', exact: true }).click()
      await teacher.getByRole('button', { name: '+ New course' }).click()
      await teacher.getByLabel('Course name').fill(`Alpha test ${tag}`)
      await teacher.getByLabel('Code (optional)').fill('ALPHA1')
      await teacher.getByRole('button', { name: 'Create course' }).click()
      await expect(teacher.locator('.bb-eyebrow', { hasText: 'Course roster' })).toBeVisible({ timeout: 10_000 })
      // Pasted in reverse order: the copied list still comes out sorted by name.
      await teacher.getByLabel('Add students').fill(people.slice().reverse().map(p => `${p.name}, ${p.email}`).join('\n'))
      await teacher.getByRole('button', { name: 'Add students' }).click()
      const copy = teacher.getByRole('button', { name: 'Copy all invite links' })
      await expect(copy).toBeVisible({ timeout: 10_000 })
      await copy.click()
      await expect(teacher.getByRole('button', { name: 'Copied 3 links' })).toBeVisible()
      const lines = (await teacher.evaluate(() => navigator.clipboard.readText())).split('\n')
      expect(lines).toHaveLength(3)
      links = lines.map(l => l.split('\t'))
      expect(links.map(l => l[0])).toEqual(people.map(p => p.name))
      expect(links.map(l => l[1])).toEqual(people.map(p => p.email))
      for (const [, , link] of links) expect(link).toMatch(/^https?:\/\/[^/]+\/bluebook\/\?invite=[A-Za-z0-9_-]+$/)
    })

    await test.step('exams A and B: 25 minutes, paste blocked, writing consistency off', async () => {
      await createExamThroughTheForm(teacher, `Practice prompt 1 ${tag}`, 'Describe one stall in a market that opens only at night.')
      await createExamThroughTheForm(teacher, `Practice prompt 2 ${tag}`, 'Reply to a letter from 2076 in your partner\'s voice.')
      const exams = (await (await request.get('/bluebook/exams', { headers: staffAuth })).json()).exams
      for (const e of exams) {
        expect(e.duration).toBe(25)
        expect(e.conditions.blockCopy).toBe(true)
        expect(e.conditions.aiDetect).toBe(false)
        expect(e.minWords ?? e.min_words ?? 0).toBe(0)
      }
    })

    const path = link => new URL(link).pathname + new URL(link).search
    const student = await newPage(browser, T.baseURL, { viewport: PHONE })
    await test.step('a student joins on a phone: password, terms and student notice, then their course', async () => {
      await student.goto(path(links[0][2]))
      await expect(student.getByText(/I have read the student notice/)).toBeVisible()
      await student.getByLabel('New password').fill(PASSWORD)
      await student.getByLabel('Confirm password').fill(PASSWORD)
      await student.getByRole('button', { name: /save and continue/i }).click()
      await expect(student.getByRole('alert')).toContainText('student notice')
      await student.getByRole('checkbox').check()
      await student.getByRole('button', { name: /save and continue/i }).click()
      await expect(student.getByRole('heading', { name: 'Welcome, Alpha Ada.' })).toBeVisible({ timeout: 10_000 })
      // No comparison pages for students in the pilot, even with Original on.
      const nav = student.getByRole('navigation', { name: 'Student navigation' })
      await expect(nav.getByRole('link')).toHaveCount(0)
      // The first exam the teacher set is listed first.
      const titles = await student.getByRole('table', { name: 'Your examinations' }).locator('td.lead').allInnerTexts()
      expect(titles[0]).toContain(`Practice prompt 1 ${tag}`)
      expect(titles[1]).toContain(`Practice prompt 2 ${tag}`)
      expect(await student.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(PHONE.width)
    })

    await test.step('the same link again is refused with a way forward', async () => {
      const again = await newPage(browser, T.baseURL, { viewport: PHONE })
      await again.goto(path(links[0][2]))
      await again.getByLabel('New password').fill('another-pass-1')
      await again.getByLabel('Confirm password').fill('another-pass-1')
      await again.getByRole('checkbox').check()
      await again.getByRole('button', { name: /save and continue/i }).click()
      await expect(again.getByRole('alert')).toContainText('This link has already been used, or it has expired.')
      await again.getByRole('button', { name: 'Go to sign in' }).click()
      await expect(again.locator('#bbLoginEmail')).toBeVisible()
      expect(new URL(again.url()).search).toBe('')
      await again.context().close()
    })

    await test.step('exam A: instructions, timer, paste notice, a refresh, sealing and the done state', async () => {
      await student.getByRole('row', { name: new RegExp(`Practice prompt 1 ${tag}`) }).getByRole('button', { name: 'Open' }).click()
      await expect(student.getByRole('heading', { name: 'How this exam works' })).toBeVisible()
      await expect(student.getByText('Copy and paste are turned off in the answer box.')).toBeVisible()
      const brief = await student.evaluate(() => document.body.innerText)
      expect(brief).not.toMatch(/compar|score|consisten|Original/i)
      await expect(student.getByText('1 question · 25 minutes.')).toBeVisible()
      await student.getByRole('button', { name: 'Begin Examination' }).click()
      await expect(student.getByRole('timer')).toHaveText(/^2[45]:\d\d$/, { timeout: 10_000 })
      const box = student.getByRole('textbox', { name: 'Your examination answer' })
      await box.click()
      await box.pressSequentially(ESSAY, { delay: 2 })
      await expect(student.getByText(/\d+ words?/).first()).toBeVisible()
      // Ctrl/Cmd+V is stopped at the key press; the student is told why.
      await student.evaluate(() => navigator.clipboard.writeText('PASTED FROM ELSEWHERE'))
      await box.press('ControlOrMeta+v')
      await expect(student.getByText('Pasting is turned off for this exam, so nothing was added.').first()).toBeVisible()
      expect(await box.inputValue()).not.toContain('PASTED')
      await student.waitForTimeout(1600)   // the notice's 1.5s de-duplication, then a fresh save
      // A refresh in the middle comes back to this exam, not the exam list.
      await student.reload()
      await expect(student.getByText('You have already started this exam.')).toBeVisible({ timeout: 10_000 })
      await student.getByRole('button', { name: 'Resume Examination' }).click()
      await expect(student.getByRole('textbox', { name: 'Your examination answer' })).toHaveValue(ESSAY)
      await student.getByRole('button', { name: 'Seal & Submit' }).click()
      await expect(student.getByRole('heading', { name: 'Examination Sealed' })).toBeVisible({ timeout: 30_000 })
      const done = await student.locator('.bk-done').innerText()
      expect(done).not.toMatch(/compar|score|consisten/i)
      expect(done).toContain('Your teacher may choose to keep this booklet as reference writing')
      await student.getByRole('button', { name: 'Back to my exams' }).click()
      await expect(student.getByRole('row', { name: new RegExp(`Practice prompt 1 ${tag}`) }).locator('.bb-badge')).toHaveText('submitted')
    })

    await test.step('the live view opens on the exam being written, even when a newer one is open', async () => {
      const token = new URL(links[1][2]).searchParams.get('invite')
      const ben = await (await request.post('/auth/invite/redeem', { data: { token, password: PASSWORD } })).json()
      const exams = (await (await request.get('/bluebook/exams', { headers: staffAuth })).json()).exams
      const examA = exams.find(e => e.title === `Practice prompt 1 ${tag}`)
      const started = await request.post(`/bluebook/me/exams/${examA.id}/start`, { headers: { Authorization: `Bearer ${ben.token}` } })
      expect(started.ok()).toBe(true)
      await teacher.getByRole('navigation', { name: 'Teacher navigation' }).getByRole('button', { name: 'Proctor', exact: true }).click()
      await expect(teacher.locator('#proctorExam')).toHaveValue(examA.id, { timeout: 10_000 })
      await expect(teacher.locator('.bb-stat', { hasText: 'Writing now' }).locator('strong')).toHaveText('1')
      await expect(teacher.locator('.bb-stat', { hasText: 'Submitted' }).locator('strong')).toHaveText('1')
      await teacher.getByRole('button', { name: 'Refresh now' }).click()
      await expect(teacher.getByRole('row', { name: /Alpha Ben/ }).getByText('writing')).toBeVisible()
    })

    await test.step('submissions list and export', async () => {
      await teacher.getByRole('navigation', { name: 'Teacher navigation' }).getByRole('button', { name: 'Examinations', exact: true }).click()
      await teacher.getByRole('button', { name: `Practice prompt 1 ${tag}`, exact: true }).click()
      await expect(teacher.getByText('1 submission', { exact: false }).first()).toBeVisible({ timeout: 10_000 })
      const [download] = await Promise.all([
        teacher.waitForEvent('download'),
        teacher.getByRole('button', { name: 'Export CSV' }).click(),
      ])
      const csv = readFileSync(await download.path(), 'utf8')
      expect(csv.split('\n')[0]).toContain('name,email')
      expect(csv).toContain(people[0].email)
      expect(csv).toContain('The stall at the end of the lane')
    })

    await test.step('back on the roster, fresh links for whoever has not joined', async () => {
      await teacher.getByRole('navigation', { name: 'Teacher navigation' }).getByRole('button', { name: 'Courses', exact: true }).click()
      await teacher.getByRole('button', { name: new RegExp(`Alpha test ${tag}`) }).first().click()
      await expect(teacher.getByText('Links are shown only once, when they are made')).toBeVisible({ timeout: 10_000 })
      await teacher.getByRole('button', { name: 'Get fresh links for all 1 waiting' }).click()
      await teacher.getByRole('button', { name: 'Copy all invite links' }).click()
      const lines = (await teacher.evaluate(() => navigator.clipboard.readText())).split('\n')
      expect(lines).toHaveLength(1)
      expect(lines[0].split('\t')[1]).toBe(people[2].email)
    })

    await test.step('the reference-papers page counts papers per student and warns below the minimum', async () => {
      const roster = (await (await request.get('/bluebook/students', { headers: staffAuth })).json()).students
      const ada = roster.find(r => r.email === people[0].email)
      const paper = n => `Paper ${n}. ` + 'I grew up near the river, and most of what I know about patience I learned there, waiting. '.repeat(7)
      for (const n of [1, 2, 3]) {
        const r = await request.post(`/students/${encodeURIComponent(ada.student_id)}/baseline`, {
          headers: staffAuth, data: { text: paper(n), provenance: 'verified', assignment: `Essay ${n}` },
        })
        expect(r.ok()).toBe(true)
      }
      await teacher.goto('/original/baseline.html')
      await expect(teacher.locator('#ref-sum')).toHaveText(`1 of ${roster.length} students meet the minimum`, { timeout: 15_000 })
      await expect(teacher.getByRole('row', { name: /Alpha Ada/ })).toContainText('Meets the minimum')
      await expect(teacher.getByRole('row', { name: /Alpha Cy/ })).toContainText('No papers yet')
      await teacher.getByRole('link', { name: 'Alpha Cy' }).click()
      await expect(teacher.locator('#s-min')).toHaveText('No papers', { timeout: 15_000 })
      await expect(teacher.locator('#add-min')).toContainText('Add at least 3 papers and 300 words in all.')
    })
  })

  test('an invite link with no code says so and offers sign-in', async ({ browser, testTenant }) => {
    const page = await newPage(browser, testTenant.baseURL, { viewport: PHONE })
    await page.goto('/bluebook/?invite=')
    await expect(page.getByRole('alert')).toContainText('This link is incomplete')
    await expect(page.getByLabel('New password')).toHaveCount(0)
    await page.getByRole('button', { name: 'Go to sign in' }).click()
    await expect(page.locator('#bbLoginEmail')).toBeVisible()
  })

  test('the new examination form fits a phone', async ({ browser, testTenant }) => {
    const page = await newPage(browser, testTenant.baseURL, {
      viewport: PHONE, storageState: staffStorageState(testTenant.baseURL, testTenant.staff),
    })
    await page.goto('/bluebook/')
    await page.getByRole('navigation', { name: 'Teacher navigation' }).getByRole('button', { name: 'Examinations', exact: true }).click()
    await page.getByRole('button', { name: '+ New examination' }).click()
    await expect(page.locator('#neTitle')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(PHONE.width)
  })
})

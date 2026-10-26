/**
 * course-join.spec.mjs, the two new ways onto a course roster, end to end
 * through the real UI: a Canvas gradebook export uploaded as a class list,
 * and a student joining by the course's join link with approval on.
 *
 * Server-side rules (codes, reset, domain limit, approval, duplicate
 * emails, rate limits) are pinned in tests/test_course_join.py; the parser
 * in unit/class-list.test.mjs. This proves the screens wire them together.
 *
 * Every identity is unique per run, so the spec is parallel-safe.
 */

import { test, expect } from '@playwright/test'

const uid = () => `${process.pid}${Date.now()}${Math.floor(Math.random() * 1e6)}`

test.describe('Course join link and class list upload', () => {
  test('teacher uploads a Canvas export and opens a join link; a student joins and is approved', async ({ browser }) => {
    test.setTimeout(120_000)
    const id = uid()
    const teacherEmail = `teacher-${id}@e2e.test`
    const studentEmail = `joiner-${id}@e2e.test`
    const canvas = [
      'Student,ID,SIS User ID,SIS Login ID,Section,Essay 1 (101),Current Score',
      '    Points Possible,,,,,10.00,(read only)',
      `"Lovelace, Ada",1001,S1001,ada${id},Ethics,9.00,90.00`,
      `"Hopper, Grace",1002,S1002,grace${id},Ethics,8.00,80.00`,
      '"Student, Test",9999,,,Ethics,,',
    ].join('\r\n')

    // ── Teacher: sign up and make a course (which opens its roster) ─────
    const tctx = await browser.newContext()
    const teacher = await tctx.newPage()
    await teacher.goto('/bluebook/')
    await teacher.getByRole('button', { name: 'Create a free workspace' }).click()
    await teacher.getByLabel('Your name').fill('E2E Teacher')
    await teacher.getByLabel('Email').fill(teacherEmail)
    await teacher.getByLabel('Password').fill('e2e-teacher-pass-1')
    await teacher.locator('#bbSignupTerms').check()
    await teacher.getByRole('button', { name: 'Create workspace' }).click()
    await expect(teacher.getByRole('button', { name: 'Overview', exact: true })).toBeVisible({ timeout: 10_000 })
    await teacher.getByRole('button', { name: 'Courses', exact: true }).click()
    await teacher.getByRole('button', { name: '+ New course' }).click()
    await teacher.getByLabel('Course name').fill('Introduction to Ethics')
    await teacher.getByLabel('Code (optional)').fill('ETH 101')
    await teacher.getByRole('button', { name: 'Create course' }).click()
    await expect(teacher.getByRole('heading', { name: 'Introduction to Ethics' })).toBeVisible({ timeout: 10_000 })

    // ── Teacher: upload the gradebook export ─────────────────────────────
    await teacher.getByTestId('open-class-list').click()
    await teacher.getByTestId('class-list-file').setInputFiles({
      name: 'gradebook.csv', mimeType: 'text/csv', buffer: Buffer.from(canvas),
    })
    await expect(teacher.getByText('Canvas gradebook export')).toBeVisible()
    // No email column: the import waits for a decision about email format.
    await expect(teacher.getByTestId('class-list-import')).toBeDisabled()
    await teacher.locator('#clDomain').fill('school.edu')
    await expect(teacher.getByTestId('class-list-summary')).toContainText('2 new · 0 already on the roster · 0 with problems · 2 skipped')
    await teacher.getByTestId('class-list-import').click()
    // The same Invite links panel as the paste box, with its bulk actions.
    await expect(teacher.getByRole('heading', { name: 'Invite links (2)' })).toBeVisible({ timeout: 10_000 })
    await expect(teacher.getByRole('button', { name: 'Copy all invite links' })).toBeVisible()
    const [linksFile] = await Promise.all([
      teacher.waitForEvent('download'),
      teacher.getByRole('button', { name: 'Download links (CSV)' }).click(),
    ])
    const linksCsv = Buffer.concat(await (await linksFile.createReadStream()).toArray()).toString('utf8')
    expect(linksCsv).toContain(`ada${id}@school.edu`)
    expect(linksCsv).toContain('Ada Lovelace')
    expect(linksCsv).not.toContain('Test')
    // The upload panel closes, and nothing of the file is shown any more.
    await expect(teacher.getByTestId('class-list-file')).toHaveCount(0)

    // ── Teacher: turn the join link on, with approval ────────────────────
    await teacher.getByTestId('join-enabled').click()
    const codeBox = teacher.getByTestId('join-code')
    await expect(codeBox).toBeVisible({ timeout: 10_000 })
    const code = (await codeBox.textContent()).trim()
    expect(code).toMatch(/^[A-HJKMNP-Z2-9]{6}$/)
    const joinUrl = await teacher.getByLabel('Join link').inputValue()
    expect(joinUrl).toContain(`/bluebook/?join=${code}`)
    await teacher.getByTestId('join-approval').click()
    await expect(teacher.getByTestId('join-approval')).toBeChecked({ timeout: 10_000 })

    // ── Student: open the link, join, wait for approval ──────────────────
    const sctx = await browser.newContext()
    const student = await sctx.newPage()
    await student.goto(joinUrl)
    await expect(student.getByRole('heading', { name: 'Join Introduction to Ethics' })).toBeVisible({ timeout: 10_000 })
    await expect(student.getByText(/Create your Original Collections account/)).toBeVisible()
    await student.locator('#bbJoinName').fill('Mary Shelley')
    await student.locator('#bbJoinEmail').fill(studentEmail)
    await student.locator('#bbJoinPass').fill('e2e-student-pass-1')
    await student.locator('#bbJoinConfirm').fill('e2e-student-pass-1')
    await student.locator('#bbJoinTerms').check()
    await student.getByRole('button', { name: 'Join course' }).click()
    await expect(student.getByText('Waiting for your teacher to approve you for Introduction to Ethics.', { exact: false })).toBeVisible({ timeout: 10_000 })
    // No join code is left in the address bar.
    expect(new URL(student.url()).searchParams.has('join')).toBe(false)

    // ── Teacher: the joiner shows as Pending; approve them ───────────────
    await teacher.getByRole('button', { name: '← Courses' }).click()
    await teacher.getByRole('button', { name: /Students & invitations/ }).first().click()
    const row = teacher.getByRole('row', { name: new RegExp(studentEmail) })
    await expect(row).toContainText('pending', { timeout: 10_000 })
    await row.getByRole('button', { name: 'Approve' }).click()
    await expect(row).toContainText('active', { timeout: 10_000 })

    // ── Student: the course is theirs now ────────────────────────────────
    await student.reload()
    await expect(student.getByText('Waiting for your teacher to approve you', { exact: false })).toHaveCount(0, { timeout: 10_000 })
    await expect(student.getByText('ETH 101')).toBeVisible()

    await sctx.close()
    await tctx.close()
  })

  test('a code that does not work is refused with one plain message', async ({ page }) => {
    await page.goto('/bluebook/')
    await page.getByRole('button', { name: /sign in/i }).first().click()
    await page.getByTestId('join-with-code').click()
    await page.getByLabel('Class code').fill('ZZZZZZ')
    await page.getByRole('button', { name: 'Continue' }).click()
    await expect(page.getByText("This join link or code isn't working.", { exact: false })).toBeVisible({ timeout: 10_000 })
  })
})

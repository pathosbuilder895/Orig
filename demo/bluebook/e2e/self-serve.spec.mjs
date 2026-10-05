/**
 * self-serve.spec.mjs — the public self-serve Bluebook journey, end to end
 * through the real UI (docs/superpowers/specs/2026-09-28-bluebook-self-serve-dashboards-design.md).
 *
 * A teacher signs up (a private, Bluebook-only workspace), creates a course
 * and an exam with two questions, and adds a student. The student redeems
 * the invite, sits the teacher's actual exam, and seals it. The teacher then
 * reads the answer and the recorded warning, and exports the CSV.
 *
 * Also pins what a Bluebook-only workspace must never do: call Original's
 * scoring or baseline routes during a seal.
 *
 * Every identity is unique per run, so the spec is parallel-safe and needs
 * no guard token (signup is public).
 */

import { test, expect } from '@playwright/test'

const uid = () => `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`

async function noFullscreen(page) {
  // chromium-headless rejects requestFullscreen; the exam must not care.
  await page.addInitScript(() => {
    Element.prototype.requestFullscreen = function () { return Promise.resolve() }
  })
}

test.describe('Public self-serve journey', () => {
  test('teacher signs up, invites a student, student sits the real exam, teacher reads and exports it', async ({ browser }) => {
    test.setTimeout(120_000)
    const id = uid()
    const teacherEmail = `teacher-${id}@e2e.test`
    const studentEmail = `student-${id}@e2e.test`
    const examTitle = `Self-serve exam ${id}`
    const q1 = 'Is courage a mean between two vices?'
    const q2 = 'Name one virtue Aristotle omits.'
    const answer = 'Courage sits between cowardice and rashness, as Aristotle argues in Book Three.'
    const answer2 = 'Humility, which the magnanimous man of Book Four lacks entirely.'
    const feedback = 'A clear reading of the mean. Say more about Book Four.'

    // ── Teacher: sign up ────────────────────────────────────────────────
    const tctx = await browser.newContext()
    const teacher = await tctx.newPage()
    await teacher.goto('/bluebook/')
    await teacher.getByRole('button', { name: 'Create a free workspace' }).click()
    await teacher.getByLabel('Your name').fill('E2E Teacher')
    await teacher.getByLabel('Email').fill(teacherEmail)
    await teacher.getByLabel('Password').fill('e2e-teacher-pass-1')
    // Signup records which version of the terms the teacher accepted.
    await teacher.locator('#bbSignupTerms').check()
    await teacher.getByRole('button', { name: 'Create workspace' }).click()
    await expect(teacher.getByRole('button', { name: 'Overview', exact: true })).toBeVisible({ timeout: 10_000 })
    // A Bluebook-only workspace has no Original cross-link.
    await expect(teacher.getByRole('button', { name: /Original Analysis/ })).toHaveCount(0)

    // ── Teacher: course (creating it opens its roster) ─────────────────
    await teacher.getByRole('button', { name: 'Courses', exact: true }).click()
    await teacher.getByRole('button', { name: '+ New course' }).click()
    await teacher.getByLabel('Course name').fill('Introduction to Ethics')
    await teacher.getByLabel('Code (optional)').fill('ETH 101')
    await teacher.getByRole('button', { name: 'Create course' }).click()
    await expect(teacher.getByRole('heading', { name: 'Introduction to Ethics' })).toBeVisible({ timeout: 10_000 })

    // ── Teacher: add the student, take the links in bulk ────────────────
    await teacher.locator('#rosterInput').fill(`E2E Student, ${studentEmail}`)
    await teacher.getByRole('button', { name: 'Add students' }).click()
    const linkBox = teacher.getByLabel('Invite link').first()
    await expect(linkBox).toBeVisible({ timeout: 10_000 })
    const inviteUrl = await linkBox.inputValue()
    expect(inviteUrl).toContain('/bluebook/?invite=')
    // The bulk download carries the same one-time link, ready for a class email.
    const [linksFile] = await Promise.all([
      teacher.waitForEvent('download'),
      teacher.getByRole('button', { name: 'Download links (CSV)' }).click(),
    ])
    const linksCsv = Buffer.concat(await (await linksFile.createReadStream()).toArray()).toString('utf8')
    expect(linksCsv).toContain(studentEmail)
    expect(linksCsv).toContain(inviteUrl)

    // ── Teacher: exam with two questions, linked to the course ─────────
    await teacher.getByRole('button', { name: 'Examinations', exact: true }).click()
    await teacher.getByRole('button', { name: '+ New examination' }).click()
    await teacher.locator('#neTitle').fill(examTitle)
    await teacher.locator('#neDuration').fill('30')
    await teacher.locator('#neMinWords').fill('5')
    await teacher.locator('#nePrompt0').fill(q1)
    await teacher.getByRole('button', { name: /Add another question/ }).click()
    await teacher.locator('#nePrompt1').fill(q2)
    const [createRes] = await Promise.all([
      teacher.waitForResponse(r => r.url().endsWith('/bluebook/exams') && r.request().method() === 'POST'),
      teacher.getByRole('button', { name: 'Publish Examination' }).click(),
    ])
    expect((await createRes.json()).questions).toEqual([q1, q2])
    await expect(teacher.getByText('Examination Created')).toBeVisible({ timeout: 10_000 })

    // ── Student: redeem, see the exam, sit it ───────────────────────────
    const sctx = await browser.newContext()
    const student = await sctx.newPage()
    await noFullscreen(student)
    const originalCalls = []
    student.on('request', r => { if (/\/students\//.test(new URL(r.url()).pathname)) originalCalls.push(r.url()) })
    await student.goto(new URL(inviteUrl).pathname + new URL(inviteUrl).search)
    await student.getByLabel('New password').fill('e2e-student-pass-1')
    await student.getByLabel('Confirm password').fill('e2e-student-pass-1')
    await student.getByRole('button', { name: 'Save and continue' }).click()
    await expect(student.getByText(examTitle)).toBeVisible({ timeout: 10_000 })
    await expect(student).not.toHaveURL(/invite=/)
    await student.getByRole('button', { name: 'Open' }).click()
    await expect(student.getByText('Preliminary Instructions')).toBeVisible({ timeout: 10_000 })
    // Honest conditions: nothing claims AI tools are blocked.
    await expect(student.getByText(/AI .*blocked/i)).toHaveCount(0)
    await student.getByRole('button', { name: /Begin Examination/ }).click()

    // One question at a time, one answer box each.
    await expect(student.getByText(q1, { exact: false })).toBeVisible({ timeout: 10_000 })
    const box1 = student.getByLabel('Your answer to question 1')
    await box1.focus()
    await student.keyboard.type(answer, { delay: 1 })
    await student.getByRole('button', { name: 'Next →' }).click()
    await expect(student.getByText(q2, { exact: false })).toBeVisible()
    const box2 = student.getByLabel('Your answer to question 2')
    await expect(box2).toHaveValue('')
    await box2.focus()
    await student.keyboard.type(answer2, { delay: 1 })
    await student.evaluate(() => window.dispatchEvent(new Event('blur')))
    // The recorder collapses events inside 1.5s into one, so wait it out:
    // otherwise the deliberate blur above would mask a false one at seal time.
    await student.waitForTimeout(1700)
    // Browsers may fire window blur (and a trailing one) around a native dialog.
    // Headless Chromium does not, so simulate it: the confirm must not be
    // recorded as the student leaving the exam.
    await student.evaluate(() => {
      const nativeConfirm = window.confirm.bind(window)
      window.confirm = (msg) => {
        window.dispatchEvent(new Event('blur'))
        const ok = nativeConfirm(msg)
        setTimeout(() => {
          window.dispatchEvent(new Event('blur'))
          window.dispatchEvent(new Event('focus'))
        }, 0)
        return ok
      }
    })
    student.once('dialog', d => d.accept())
    const [sealRes] = await Promise.all([
      student.waitForResponse(r => r.url().endsWith('/bluebook/submissions') && r.request().method() === 'POST'),
      student.locator('button', { hasText: /Seal & Submit|Sealing/ }).click(),
    ])
    const sealBody = sealRes.request().postDataJSON()
    expect(sealBody.answers).toEqual([answer, answer2])
    // Exactly the one warning this test caused on purpose: the seal
    // confirmation itself records nothing.
    expect(sealBody.warnings.map(w => w.type)).toEqual(['focus_lost'])
    await expect(student.getByText('Examination Sealed')).toBeVisible({ timeout: 30_000 })
    await expect(student.getByText('✓ Delivered to your teacher')).toBeVisible()
    // A Bluebook-only workspace never reaches Original.
    expect(originalCalls).toEqual([])

    await student.getByRole('button', { name: 'Back to my exams' }).click()
    await expect(student.getByText('Not yet released')).toBeVisible({ timeout: 10_000 })

    // ── Teacher: read each answer and the warning, mark, release ────────
    await teacher.getByRole('button', { name: 'Examinations', exact: true }).click()
    await teacher.getByRole('button', { name: examTitle, exact: true }).click()
    await expect(teacher.getByRole('button', { name: 'Export CSV' })).toBeVisible({ timeout: 10_000 })
    await teacher.getByRole('button', { name: 'Read & mark' }).click()
    await expect(teacher.getByText(answer)).toBeVisible({ timeout: 10_000 })
    await expect(teacher.getByText(answer2)).toBeVisible()
    await expect(teacher.getByText(/Left the window × 1/)).toBeVisible()
    await teacher.getByLabel('Mark (optional)').fill('18/20')
    await teacher.getByLabel('Feedback for the student (optional)').fill(feedback)
    await teacher.getByRole('button', { name: 'Save mark and feedback' }).click()
    await expect(teacher.getByRole('status').filter({ hasText: /Saved/ })).toBeVisible({ timeout: 10_000 })

    const [download] = await Promise.all([
      teacher.waitForEvent('download'),
      teacher.getByRole('button', { name: 'Export CSV' }).click(),
    ])
    const body = Buffer.concat(await (await download.createReadStream()).toArray()).toString('utf8')
    expect(body).toContain(studentEmail)
    expect(body).toContain('Courage sits between cowardice and rashness')
    expect(body).toContain('18/20')
    expect(body.split('\n')[0]).toContain('answer_2')

    // Until release the student still sees nothing of the mark.
    await student.reload()
    await expect(student.getByText('Not yet released')).toBeVisible({ timeout: 10_000 })
    await teacher.getByRole('button', { name: 'Release results' }).click()
    await expect(teacher.getByRole('button', { name: 'Hide results' })).toBeVisible({ timeout: 10_000 })

    await student.reload()
    await expect(student.getByRole('cell', { name: '18/20' })).toBeVisible({ timeout: 10_000 })
    await student.getByRole('button', { name: 'Read →' }).click()
    await expect(student.getByText(feedback)).toBeVisible({ timeout: 10_000 })
    await expect(student.getByText(answer2)).toBeVisible()

    await tctx.close()
    await sctx.close()
  })
})

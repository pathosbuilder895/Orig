/**
 * analyse-sealed.spec.mjs: a teacher analyses a sealed Collections exam
 * against the student's baseline without copying and pasting it.
 *
 * Writing State takes ?student=<id>&submission=<sealed submission id>: it reads
 * the sealed exam (GET /bluebook/submissions/{id}, staff only), fills the paper
 * with the answers joined by a blank line (never the "Question N." headings)
 * and the Assignment with the exam title, and waits for the teacher to press
 * Analyse. Reached from a row of Original's Submissions page ("Analyse against
 * baseline") and from the Collections reader ("Analyse in Original").
 *
 * The baseline is three public-domain passages of J. S. Mill's On Liberty
 * (1859), added the way a teacher adds verified writing on the Voice baseline.
 */

import { readFileSync } from 'node:fs'
import { isolatedTest as test, expect } from './fixtures/tenancy.mjs'
import { COLLECTIONS_HOME, addBaselineFor, createCourse, staffStorageState } from './fixtures/api-setup.mjs'

const FIXTURES = new URL('./fixtures/evidence/', import.meta.url)
const read = name => readFileSync(new URL(name, FIXTURES), 'utf8')
const uid = () => `${process.pid}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`

const ANSWERS = [
  'Augustine argues that the restless heart finds rest only in God, and he builds the argument ' +
  'slowly, from memory and desire, through the long middle books of the work, until the reader ' +
  'sees that the search was the subject all along. I find the account of desire persuasive.',
  'Boethius writes from prison, and the consolation he is offered is philosophy rather than ' +
  'escape. Lady Philosophy asks him what he thinks he has lost, and slowly shows him that fortune ' +
  'never belonged to him at all. I think the argument works better as comfort than as proof.',
]

async function verifiedBaseline(request, studentId, staffToken) {
  for (const i of [1, 2, 3]) {
    await addBaselineFor(request, studentId, staffToken, { text: read(`mill-${i}.txt`), provenance: 'verified', assignment: `On Liberty, part ${i}` })
  }
}

// A course, a two-question exam, an enrolled student who sits and seals it.
async function sealedExam(request, staff) {
  const id = uid()
  const teacher = { Authorization: `Bearer ${staff.token}` }
  const course = await createCourse(request, staff.token, { name: `Sealed course ${id}` })
  const examTitle = `Sealed exam ${id}`
  const created = await request.post('/bluebook/exams', {
    headers: teacher,
    data: {
      title: examTitle, course: course.code, course_id: course.id, duration: 30, status: 'ACTIVE',
      questions: ['What does Augustine say about rest?', 'What does Philosophy offer Boethius?'],
    },
  })
  expect(created.status(), await created.text()).toBe(201)
  const examId = (await created.json()).id
  const added = await request.post(`/bluebook/courses/${encodeURIComponent(course.id)}/students`, {
    headers: teacher, data: { students: [{ email: `sealer-${id}@e2e.test`, name: 'Sealed Student' }] },
  })
  expect(added.status(), await added.text()).toBe(200)
  const invite = new URL((await added.json()).students[0].invite_path, 'http://x').searchParams.get('invite')
  const redeemed = await request.post('/auth/invite/redeem', { data: { token: invite, password: 'e2e-passw0rd!' } })
  expect(redeemed.status(), await redeemed.text()).toBe(200)
  const student = await redeemed.json()
  const asStudent = { Authorization: `Bearer ${student.token}` }
  await request.post(`/bluebook/me/exams/${encodeURIComponent(examId)}/start`, { headers: asStudent })
  // No `text`: the server stores the answers under "Question N." headings.
  const sealed = await request.post('/bluebook/submissions', {
    headers: asStudent,
    data: {
      exam_id: examId, student_id: student.student_id, candidate: 'Sealed Student',
      word_count: 100, answers: ANSWERS, submission_uuid: `uuid-${id}`,
    },
  })
  expect(sealed.status(), await sealed.text()).toBe(201)
  const submissionId = (await sealed.json()).id
  const stored = await request.get(`/bluebook/submissions/${encodeURIComponent(submissionId)}`, { headers: teacher })
  expect(stored.status()).toBe(200)
  expect((await stored.json()).text).toContain('Question 1.')
  return { examTitle, student, submissionId }
}

const writingStateUrl = (studentId, submissionId) =>
  `/original/writing-state.html?student=${encodeURIComponent(studentId)}&submission=${encodeURIComponent(submissionId)}`

test('a sealed exam opens in Writing State prefilled, from Submissions and from the Collections reader', async ({ browser, request, testTenant }) => {
  test.setTimeout(180_000)
  const { staff, student: other, baseURL } = testTenant
  const { examTitle, student, submissionId } = await sealedExam(request, staff)
  await verifiedBaseline(request, student.student_id, staff.token)
  await verifiedBaseline(request, other.student_id, staff.token)
  const target = writingStateUrl(student.student_id, submissionId)

  const context = await browser.newContext({ storageState: staffStorageState(baseURL, staff) })
  const page = await context.newPage()

  // An earlier analysis of a different paper is kept for this tab...
  await page.goto(`/original/writing-state.html?student=${encodeURIComponent(student.student_id)}`)
  await expect(page.locator('#an-form')).toBeVisible({ timeout: 20_000 })
  await page.locator('#an-assign').fill('Orthodoxy, chapter 1')
  await page.locator('#an-text').fill(read('chesterton.txt'))
  let scored = page.waitForResponse(r => r.url().endsWith('/score') && r.request().method() === 'POST', { timeout: 90_000 })
  await page.locator('#an-go').click()
  expect((await scored).ok()).toBe(true)
  await expect(page.locator('#an-done')).toBeVisible({ timeout: 30_000 })

  // ...and the Submissions row's link still opens the sealed exam, not that analysis.
  await page.goto('/original/submissions.html')
  const row = page.locator('.q-item').filter({ hasText: examTitle })
  const analyseLink = row.getByRole('link', { name: 'Analyse against baseline' })
  await expect(analyseLink).toBeVisible({ timeout: 30_000 })
  await expect(row.locator('a.q-row a')).toHaveCount(0)  // never nested in the row link
  await analyseLink.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(url => url.pathname + url.search === target)

  await expect(page.locator('#an-form')).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('#an-text')).toHaveValue(ANSWERS.join('\n\n'))
  await expect(page.locator('#an-text')).not.toHaveValue(/Question 1\./)
  await expect(page.locator('#an-assign')).toHaveValue(new RegExp(`^${examTitle}, sealed `))
  await expect(page.locator('#an-from')).toBeVisible()
  await expect(page.locator('#an-from')).toContainText(`Loaded from Collections: ${examTitle}, sealed `)
  await expect(page.locator('#an-done')).toBeHidden()

  // Nothing is analysed until the teacher presses Analyse.
  scored = page.waitForResponse(r => r.url().endsWith('/score') && r.request().method() === 'POST', { timeout: 90_000 })
  await page.locator('#an-go').click()
  const res = await scored
  expect(res.ok()).toBe(true)
  expect(JSON.parse(res.request().postData()).text).toBe(ANSWERS.join('\n\n'))
  await expect(page.locator('#an-done')).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('#an-done-t')).toContainText(examTitle)

  // The Collections reader links to the same address; there it shows this
  // exam's analysis again, the one kept for this tab.
  await page.goto(COLLECTIONS_HOME)
  await page.getByRole('button', { name: 'Collections' }).first().click()
  await page.getByRole('button', { name: examTitle }).click()
  await page.getByRole('button', { name: 'Read & mark' }).first().click()
  const readerLink = page.getByRole('link', { name: 'Analyse in Original' })
  await expect(readerLink).toHaveAttribute('href', target)
  await readerLink.click()
  await expect(page).toHaveURL(url => url.pathname + url.search === target)
  await expect(page.locator('#an-done')).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('#an-restored')).toBeVisible()
  await expect(page.locator('#an-done-t')).toContainText(examTitle)

  // A sealed exam opened under a different student: a plain message, an empty form.
  await page.goto(writingStateUrl(other.student_id, submissionId))
  await expect(page.locator('#an-form')).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('#an-msg')).toHaveText(/written by a different student, so it was not loaded/)
  await expect(page.locator('#an-text')).toHaveValue('')
  await expect(page.locator('#an-assign')).toHaveValue('')
  await expect(page.locator('#an-from')).toBeHidden()
  await context.close()
})

test('a student who has no baseline gets "Add writing first" on Submissions', async ({ browser, request, testTenant }) => {
  test.setTimeout(90_000)
  const { staff, baseURL } = testTenant
  const { examTitle, student } = await sealedExam(request, staff)
  const context = await browser.newContext({ storageState: staffStorageState(baseURL, staff) })
  const page = await context.newPage()
  await page.goto('/original/submissions.html')
  const row = page.locator('.q-item').filter({ hasText: examTitle })
  const add = row.getByRole('link', { name: 'Add writing first' })
  await expect(add).toBeVisible({ timeout: 30_000 })
  await expect(add).toHaveAttribute('href', `baseline.html?student=${encodeURIComponent(student.student_id)}#add-writing`)
  await expect(row.getByRole('link', { name: 'Analyse against baseline' })).toHaveCount(0)
  await context.close()
})

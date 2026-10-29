/**
 * deep-link.spec.mjs: a link opens one exam in the Bluebook app (2026-10-11).
 *
 *   /bluebook/#exam/<id>  Manage examination for that exam
 *   /bluebook/#live/<id>  the live (proctor) view of that exam
 *   /bluebook/#students   the teacher's Students screen
 *   /bluebook/#courses    the teacher's Courses screen
 *
 * Only a signed-in teacher is taken there. A signed-out visitor gets the
 * landing page and, after signing in, the exam (or screen). An unknown id or another
 * workspace's id lands on the normal dashboard with no error. A student's
 * screens ignore the hash. See deep-link.jsx and app.jsx.
 */

import { test, expect } from './fixtures/tenancy.mjs'
import { createCourse, createExam, provisionTenantWithStaff } from './fixtures/api-setup.mjs'

function staffAuth(workerTenant) {
  return { Authorization: `Bearer ${workerTenant.staff.token}` }
}

async function examFor(request, workerTenant, title) {
  const course = await createCourse(request, workerTenant.staff.token, { name: `Deep link course ${Date.now()}` })
  const exam = await createExam(request, workerTenant.staff.token, {
    title, course: course.code, prompt: 'Explain one idea from this week in your own words.',
  })
  // Attach the course so the exam reads like one a teacher set up.
  const res = await request.patch(`/bluebook/exams/${encodeURIComponent(exam.id)}`, {
    headers: staffAuth(workerTenant), data: { course_id: course.id },
  })
  expect(res.ok()).toBe(true)
  return exam
}

// The teacher overview (TeacherWorkspace.jsx TeacherOverview): the e2e staff
// storage state carries no name, so its heading is the unnamed greeting.
async function expectDashboard(page) {
  await expect(page.getByRole('heading', { name: 'Begin with the writing.' })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByText('Opening the collection…')).toHaveCount(0)
  expect(new URL(page.url()).hash).toBe('')
}

// The overview, whatever the address says.
async function expectDashboardOnly(page) {
  await expect(page.getByRole('heading', { name: 'Begin with the writing.' })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('heading', { name: 'Reset your password' })).toHaveCount(0)
}

test.describe('Deep links into one exam', () => {
  test('#exam/<id> opens Manage examination for a signed-in teacher', async ({ staffPage, workerTenant, request }) => {
    const title = `Deep link exam ${workerTenant.tenant.tenant_id}`
    const exam = await examFor(request, workerTenant, title)
    await staffPage.goto(`/bluebook/#exam/${exam.id}`)
    await expect(staffPage.getByRole('heading', { name: title })).toBeVisible({ timeout: 10_000 })
    await expect(staffPage.getByRole('heading', { name: 'Submissions' })).toBeVisible()
    await expect(staffPage.getByRole('button', { name: 'Watch live' })).toBeVisible()
    // The address still names the exam while it is open, so a reload reopens it.
    expect(new URL(staffPage.url()).hash).toBe(`#exam/${exam.id}`)
    await staffPage.reload()
    await expect(staffPage.getByRole('heading', { name: title })).toBeVisible({ timeout: 10_000 })
    // Leaving the exam drops its id; the list it returns to keeps its own
    // place across a reload (alpha bug 2026-10-20).
    await staffPage.getByRole('button', { name: '← Collections' }).click()
    await expect.poll(() => new URL(staffPage.url()).hash).toBe('#collections')
  })

  test('#live/<id> opens the live view of that exam', async ({ staffPage, workerTenant, request }) => {
    const title = `Deep link live ${workerTenant.tenant.tenant_id}`
    const exam = await examFor(request, workerTenant, title)
    await staffPage.goto(`/bluebook/#live/${exam.id}`)
    await expect(staffPage.getByRole('heading', { name: 'Live sitting' })).toBeVisible({ timeout: 10_000 })
    await expect(staffPage.locator('#proctorExam')).toHaveValue(exam.id)
    await expect(staffPage.getByText('Updated ')).toBeVisible({ timeout: 10_000 })
  })

  test('a link followed while the app is open opens that exam', async ({ staffPage, workerTenant, request }) => {
    const title = `Deep link hashchange ${workerTenant.tenant.tenant_id}`
    const exam = await examFor(request, workerTenant, title)
    await staffPage.goto('/bluebook/')
    await expect(staffPage.getByRole('button', { name: 'Overview' })).toBeVisible({ timeout: 10_000 })
    await staffPage.evaluate(id => { window.location.hash = `#exam/${id}` }, exam.id)
    await expect(staffPage.getByRole('heading', { name: title })).toBeVisible({ timeout: 10_000 })
  })

  test('a link still being checked is dropped when the teacher moves on', async ({ staffPage, workerTenant, request }) => {
    const title = `Deep link pending ${workerTenant.tenant.tenant_id}`
    const exam = await examFor(request, workerTenant, title)
    // Hold the exam check so the link is still pending while the teacher uses the navigation.
    let release
    const held = new Promise(resolve => { release = resolve })
    await staffPage.route(`**/bluebook/exams/${exam.id}`, async route => { await held; await route.continue() })
    await staffPage.goto(`/bluebook/#exam/${exam.id}`)
    await expect(staffPage.getByText('Opening the collection…')).toBeVisible({ timeout: 10_000 })
    await staffPage.getByRole('button', { name: 'Courses' }).click()
    await expect(staffPage.getByRole('heading', { name: 'Courses' })).toBeVisible({ timeout: 10_000 })
    // Back on the overview: the dropped link does not come back.
    await staffPage.getByRole('button', { name: 'Overview' }).click()
    await expectDashboard(staffPage)
    release()
    await staffPage.waitForTimeout(800)
    await expectDashboard(staffPage)
    await expect(staffPage.getByRole('heading', { name: title })).toHaveCount(0)
  })

  test('#students and #courses open those screens for a signed-in teacher', async ({ staffPage }) => {
    await staffPage.goto('/bluebook/#students')
    await expect(staffPage.getByRole('heading', { name: 'Students' })).toBeVisible({ timeout: 10_000 })
    await expect(staffPage.getByText('Opening…')).toHaveCount(0)
    expect(new URL(staffPage.url()).hash).toBe('#students')
    // Moving on names the new screen, so a reload stays there.
    await staffPage.getByRole('button', { name: 'Courses' }).click()
    await expect(staffPage.getByRole('heading', { name: 'Courses' })).toBeVisible({ timeout: 10_000 })
    await expect.poll(() => new URL(staffPage.url()).hash).toBe('#courses')
    await staffPage.goto('/bluebook/#courses')
    await expect(staffPage.getByRole('heading', { name: 'Courses' })).toBeVisible({ timeout: 10_000 })
    // A link followed while the app is open works too.
    await staffPage.getByRole('button', { name: 'Overview' }).click()
    await expectDashboard(staffPage)
    await staffPage.evaluate(() => { window.location.hash = '#students' })
    await expect(staffPage.getByRole('heading', { name: 'Students' })).toBeVisible({ timeout: 10_000 })
  })

  test('a signed-out visitor following #students gets the landing page, then the Students screen after signing in', async ({ page, workerTenant }) => {
    await page.goto('/bluebook/#students')
    await expect(page.getByText('Your own words,')).toBeVisible({ timeout: 10_000 })
    await page.getByRole('button', { name: 'Sign in' }).first().click()
    await page.getByPlaceholder('you@school.edu').fill(workerTenant.staff.email)
    await page.getByPlaceholder('••••••••••').fill(workerTenant.staff.password)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Students' })).toBeVisible({ timeout: 10_000 })
  })

  test('#forgot opens the reset form for a visitor, and a signed-in teacher still gets the dashboard', async ({ page, staffPage }) => {
    // The sign-in page's "Forgot your password?" link (demo/index.html).
    await page.goto('/bluebook/#forgot')
    await expect(page.getByRole('heading', { name: 'Reset your password' })).toBeVisible({ timeout: 10_000 })
    await expect(page.getByRole('button', { name: 'Email me a reset link' })).toBeVisible()
    await staffPage.goto('/bluebook/#forgot')
    await expectDashboardOnly(staffPage)
  })

  test('an unknown id falls back to the dashboard with no error', async ({ staffPage }) => {
    await staffPage.goto('/bluebook/#exam/0000000000000000')
    await expectDashboard(staffPage)
    await staffPage.goto('/bluebook/#live/not-an-exam')
    await expectDashboard(staffPage)
  })

  test("another workspace's exam falls back to the dashboard", async ({ staffPage, request }) => {
    const other = await provisionTenantWithStaff(request)
    const theirs = await createExam(request, other.staff.token, { title: 'Another workspace exam' })
    await staffPage.goto(`/bluebook/#exam/${theirs.id}`)
    await expectDashboard(staffPage)
    await expect(staffPage.getByText('Another workspace exam')).toHaveCount(0)
    await staffPage.goto(`/bluebook/#live/${theirs.id}`)
    await expectDashboard(staffPage)
  })

  test('a signed-out visitor gets the landing page, then the exam after signing in', async ({ page, workerTenant, request }) => {
    const title = `Deep link after sign-in ${workerTenant.tenant.tenant_id}`
    const exam = await examFor(request, workerTenant, title)
    await page.goto(`/bluebook/#exam/${exam.id}`)
    await expect(page.getByText('Your own words,')).toBeVisible({ timeout: 10_000 })
    await page.getByRole('button', { name: 'Sign in' }).first().click()
    await page.getByPlaceholder('you@school.edu').fill(workerTenant.staff.email)
    await page.getByPlaceholder('••••••••••').fill(workerTenant.staff.password)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('heading', { name: title })).toBeVisible({ timeout: 10_000 })
  })

  test("the hash changes nothing for a student", async ({ browser, workerTenant, request }) => {
    const title = `Deep link student ${workerTenant.tenant.tenant_id}`
    const exam = await examFor(request, workerTenant, title)
    const { student, baseURL } = workerTenant
    const context = await browser.newContext({
      storageState: {
        cookies: [],
        origins: [{
          origin: baseURL,
          localStorage: [
            { name: 'original_session_token', value: student.token },
            { name: 'original_student_id', value: student.student_id },
            { name: 'original_tenant', value: student.tenant_id },
            { name: 'original_role', value: 'student' },
          ],
        }],
      },
    })
    const page = await context.newPage()
    for (const hash of [`#exam/${exam.id}`, '#students', '#courses']) {
      await page.goto(`/bluebook/${hash}`)
      await expect(page.getByRole('heading', { name: 'Collections', exact: true })).toBeVisible({ timeout: 10_000 })
      await expect(page.getByRole('heading', { name: 'My submissions' })).toBeVisible()
    }
    await expect(page.getByRole('button', { name: 'Watch live' })).toHaveCount(0)
    await expect(page.getByText('Opening the collection…')).toHaveCount(0)
    await context.close()
  })
})

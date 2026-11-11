/**
 * text-settings.spec.mjs: the site-wide Text setting (2026-11).
 *
 * Every page's text scales from one root size, and the Text panel (Aa Text)
 * changes the font and size at once, everywhere. The choice stays across a
 * reload (this browser) and follows a signed-in account (the server). It is
 * display only: opening it mid-collection leaves the writing, the word count
 * and the session notes exactly as they were. At the largest size no key
 * screen scrolls sideways, on a phone or a laptop.
 */

import { isolatedTest as test, expect } from './fixtures/tenancy.mjs'

const BASE_PX = 18
const SCALE = { small: 0.875, default: 1, large: 1.15, xlarge: 1.3, xxlarge: 1.5 }

async function rootPx(page) {
  return page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize))
}

async function pickText(page, { font, size }) {
  await page.getByTestId('text-settings-button').first().click()
  const panel = page.getByTestId('text-settings')
  await expect(panel).toBeVisible()
  if (font) await panel.locator(`[role=radio][data-value="${font}"]`).click()
  if (size) await panel.locator(`[role=radio][data-value="${size}"]`).click()
  await panel.getByRole('button', { name: 'Done' }).click()
  await expect(panel).toHaveCount(0)
}

// Nothing on the page is wider than the window (no sideways scroll), and
// each named element sits fully inside it.
async function expectNoOverflow(page, selectors = []) {
  const res = await page.evaluate((sels) => {
    const vw = document.documentElement.clientWidth
    const out = { vw, sw: document.documentElement.scrollWidth, clipped: [] }
    for (const s of sels) {
      for (const el of document.querySelectorAll(s)) {
        const r = el.getBoundingClientRect()
        if (r.width === 0 && r.height === 0) continue
        if (r.left < -1 || r.right > vw + 1) out.clipped.push(`${s} ${Math.round(r.left)}..${Math.round(r.right)} > ${vw}`)
      }
    }
    return out
  }, selectors)
  expect(res.clipped, 'elements outside the window').toEqual([])
  expect(res.sw, 'page scrolls sideways').toBeLessThanOrEqual(res.vw + 1)
}

async function createExam(request, testTenant, title, extra = {}) {
  const res = await request.post('/bluebook/exams', {
    headers: { Authorization: `Bearer ${testTenant.staff.token}` },
    data: {
      title, course: 'HIST 110', duration: 90, minWords: 8, maxWords: 600,
      prompt: 'What changed in 1848, and why did so much of it fail to last?', status: 'PUBLISHED', ...extra,
    },
  })
  expect(res.ok()).toBe(true)
  return res.json()
}

async function bootExam(page, exam, testTenant) {
  await page.addInitScript(([e, sid]) => {
    localStorage.setItem('bluebook_student_id', sid)
    window.BB_EXAM_CONFIG = {
      id: e.id, title: e.title, course: e.course, courseTitle: e.course, candidate: 'Text Candidate',
      duration: 90, minWords: 8, maxWords: 600, prompt: e.prompt,
      blockAI: true, blockWeb: true, blockCopy: true, phoneBlk: true, spellChk: false,
    }
    Element.prototype.requestFullscreen = function () { return Promise.resolve() }
  }, [exam, testTenant.student.student_id])
  await page.goto('/bluebook/')
  await page.waitForLoadState('networkidle')
}

test.describe('Text setting', () => {
  test('defaults to an 18px root and a readable serif before sign-in', async ({ page }) => {
    await page.goto('/bluebook/')
    expect(await rootPx(page)).toBeCloseTo(BASE_PX, 1)
    expect(await page.evaluate(() => document.documentElement.dataset.bbFont)).toBe('serif')
    await expect(page.getByTestId('text-settings-button')).toBeVisible()
  })

  test('changing size and font updates the page at once and survives a reload', async ({ page }) => {
    await page.goto('/bluebook/')
    const bodyFont = () => page.evaluate(() => getComputedStyle(document.body).fontFamily)
    await pickText(page, { font: 'readable', size: 'xxlarge' })
    expect(await rootPx(page)).toBeCloseTo(BASE_PX * SCALE.xxlarge, 1)
    expect(await bodyFont()).toContain('OpenDyslexic')
    await page.reload()
    expect(await rootPx(page)).toBeCloseTo(BASE_PX * SCALE.xxlarge, 1)
    expect(await bodyFont()).toContain('OpenDyslexic')
    await pickText(page, { font: 'sans', size: 'small' })
    expect(await rootPx(page)).toBeCloseTo(BASE_PX * SCALE.small, 1)
    expect(await bodyFont()).toContain('Atkinson Hyperlegible')
    // Reset returns to the defaults.
    await page.getByTestId('text-settings-button').click()
    await page.getByRole('button', { name: 'Reset to default' }).click()
    await page.getByRole('button', { name: 'Done' }).click()
    expect(await rootPx(page)).toBeCloseTo(BASE_PX, 1)
  })

  test('the panel works from the keyboard and closes with Escape', async ({ page }) => {
    await page.goto('/bluebook/')
    const btn = page.getByTestId('text-settings-button')
    await btn.focus()
    await page.keyboard.press('Enter')
    await expect(page.getByTestId('text-settings')).toBeVisible()
    await page.keyboard.press('ArrowRight') // serif → sans
    expect(await page.evaluate(() => document.documentElement.dataset.bbFont)).toBe('sans')
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('text-settings')).toHaveCount(0)
    await expect(btn).toBeFocused()
  })

  test('mid-collection the setting changes only the display, never the writing or the session', async ({
    studentPage, testTenant, request,
  }) => {
    test.setTimeout(60_000)
    const exam = await createExam(request, testTenant, 'Text mid-exam')
    await bootExam(studentPage, exam, testTenant)
    await studentPage.getByRole('button', { name: /Begin/ }).click()
    const box = studentPage.locator('.bk-writing textarea')
    await expect(box).toBeVisible()
    const essay = 'The revolutions of 1848 spread quickly and mostly failed, yet they changed what people expected.'
    await box.fill(essay)
    const words = await studentPage.locator('.bk-wc-n b').innerText()
    const notesBefore = await studentPage.locator('.bk-notices li').count()
    const before = await box.evaluate(el => parseFloat(getComputedStyle(el).fontSize))
    await pickText(studentPage, { font: 'readable', size: 'xxlarge' })
    const after = await box.evaluate(el => parseFloat(getComputedStyle(el).fontSize))
    expect(after).toBeGreaterThan(before * 1.4)
    await expect(box).toHaveValue(essay)
    await expect(studentPage.locator('.bk-wc-n b')).toHaveText(words)
    await expect(studentPage.locator('.bk-notices li')).toHaveCount(notesBefore)
    await expect(studentPage.locator('.bk-writing textarea')).toBeVisible()
    await expect(studentPage.getByRole('button', { name: /Submit|Seal/ }).first()).toBeVisible()
  })

  for (const [label, viewport] of [['phone', { width: 375, height: 812 }], ['laptop', { width: 1280, height: 800 }]]) {
    test(`student briefing and writing screens fit at the largest size (${label})`, async ({
      studentPage, testTenant, request,
    }) => {
      test.setTimeout(60_000)
      await studentPage.setViewportSize(viewport)
      await studentPage.addInitScript(() => localStorage.setItem('bb.display.v1', JSON.stringify({ font: 'readable', size: 'xxlarge' })))
      const exam = await createExam(request, testTenant, 'A rather long collection title for overflow checks')
      await bootExam(studentPage, exam, testTenant)
      await expect(studentPage.getByRole('button', { name: /Begin/ })).toBeVisible()
      await expectNoOverflow(studentPage, ['.bk-begin', '.bk-fields', '.bk-conditions', '[data-testid=text-settings-button]'])
      await studentPage.getByRole('button', { name: /Begin/ }).click()
      await expect(studentPage.locator('.bk-writing textarea')).toBeVisible()
      await expectNoOverflow(studentPage, ['.bk-timer', '.bk-finish', '.bk-writing textarea', '.bk-wc', '[data-testid=text-settings-button]'])
    })

    test(`teacher screens fit at the largest size (${label})`, async ({ staffPage }) => {
      await staffPage.setViewportSize(viewport)
      await staffPage.addInitScript(() => localStorage.setItem('bb.display.v1', JSON.stringify({ font: 'serif', size: 'xxlarge' })))
      await staffPage.goto('/bluebook/')
      await staffPage.waitForLoadState('networkidle')
      // The pill strip scrolls inside itself by design (phone-nav.spec.mjs).
      await expectNoOverflow(staffPage, ['h1', '.teacher-nav-right button', '.bb-stat', '[data-testid=text-settings-button]'])
      await staffPage.goto('/bluebook/#students')
      await staffPage.waitForLoadState('networkidle')
      await expectNoOverflow(staffPage, ['h1'])
    })

    test(`sign-in screen fits at the largest size (${label})`, async ({ page }) => {
      await page.setViewportSize(viewport)
      await page.addInitScript(() => localStorage.setItem('bb.display.v1', JSON.stringify({ font: 'readable', size: 'xxlarge' })))
      await page.goto('/bluebook/')
      await page.waitForLoadState('networkidle')
      await expectNoOverflow(page, ['h1', 'button', 'input'])
    })
  }

  test('a signed-in teacher keeps the setting on the account (another browser picks it up)', async ({
    staffPage, browser, testTenant,
  }) => {
    await staffPage.goto('/bluebook/')
    await staffPage.waitForLoadState('networkidle')
    const saved = staffPage.waitForResponse(r => r.url().endsWith('/bluebook/me/display') && r.request().method() === 'PUT')
    await pickText(staffPage, { font: 'classic', size: 'large' })
    expect((await saved).ok()).toBe(true)
    // A fresh browser for the same account: no local copy, the server's applies.
    const state = await staffPage.context().storageState()
    const fresh = await browser.newContext({ storageState: {
      cookies: state.cookies,
      origins: state.origins.map(o => ({ ...o, localStorage: o.localStorage.filter(i => i.name !== 'bb.display.v1') })),
    } })
    const p2 = await fresh.newPage()
    await p2.goto('/bluebook/')
    await expect.poll(() => p2.evaluate(() => document.documentElement.dataset.bbFont)).toBe('classic')
    expect(await rootPx(p2)).toBeCloseTo(BASE_PX * SCALE.large, 1)
    await fresh.close()
  })

  test('the account page offers the Text setting', async ({ staffPage }) => {
    await staffPage.goto('/bluebook/')
    await staffPage.waitForLoadState('networkidle')
    await staffPage.evaluate(() => { location.hash = '' })
    await expect(staffPage.getByTestId('text-settings-button').first()).toBeVisible()
  })
})

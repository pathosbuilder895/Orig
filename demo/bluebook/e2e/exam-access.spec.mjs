/**
 * exam-access.spec.mjs: the student writing screen for someone who uses a
 * keyboard only, a screen reader, or 200% zoom.
 *
 * a11y.spec.mjs runs axe over the same screens. Axe cannot judge everything
 * that matters here, so this file checks it directly:
 *   - a whole sitting (begin, write, seal) works from the keyboard alone,
 *     and focus lands somewhere sensible at each step;
 *   - every control, and the answer box, shows a visible focus indicator;
 *   - the timer has a spoken label, and time and word-count milestones are
 *     announced through a POLITE live region (never an interrupting alert);
 *   - the answer box's description carries the word count, and the disabled
 *     seal button says why it is disabled;
 *   - the blue cover's text clears WCAG AA contrast against the LIGHTEST
 *     point of its gradient (axe skips gradient backgrounds as "incomplete",
 *     so it never measured these);
 *   - at 200% zoom (a 1280x800 window is 640x400 CSS pixels) and at 320px
 *     wide, nothing scrolls sideways, the timer stays in view, and the
 *     answer box and seal button stay usable.
 */

import { isolatedTest as test, expect } from './fixtures/tenancy.mjs'

const BOX = 'textarea[placeholder="Begin writing here…"]'
const ESSAY =
  'Hume holds that reason alone cannot move us to act, so that a moral ' +
  'judgement must draw on sentiment as well as on any argument we give.'

async function createExam(request, testTenant, title, extra = {}) {
  const res = await request.post('/bluebook/exams', {
    headers: { Authorization: `Bearer ${testTenant.staff.token}` },
    data: {
      title, course: 'PHIL 210', duration: 120, minWords: 12, maxWords: 400,
      prompt: 'Explain the role of sentiment in moral judgement.', status: 'PUBLISHED', ...extra,
    },
  })
  expect(res.ok()).toBe(true)
  return res.json()
}

async function boot(page, exam, testTenant, { blockWeb = false, minWords = 12, maxWords = 400 } = {}) {
  await page.addInitScript(([examArg, sid, bw, mn, mx]) => {
    localStorage.setItem('bluebook_student_id', sid)
    window.BB_EXAM_CONFIG = {
      id: examArg.id, title: examArg.title, course: examArg.course, courseTitle: examArg.course,
      candidate: 'Access Candidate', duration: 120, minWords: mn, maxWords: mx,
      prompt: examArg.prompt, blockWeb: bw, blockCopy: false, spellChk: true,
    }
    Element.prototype.requestFullscreen = function () { return Promise.resolve() }
  }, [exam, testTenant.student.student_id, blockWeb, minWords, maxWords])
  await page.goto('/bluebook/')
  await page.waitForLoadState('networkidle')
}

async function tabTo(page, name, max = 25) {
  for (let i = 0; i < max; i++) {
    await page.keyboard.press('Tab')
    const label = await page.evaluate(() => {
      const el = document.activeElement
      return el ? (el.getAttribute('aria-label') || el.textContent || '').trim() : ''
    })
    if (name.test(label)) return
  }
  throw new Error(`Tab never reached ${name}`)
}

const focusRing = (page, selector) => page.evaluate((sel) => {
  const el = document.querySelector(sel)
  const s = getComputedStyle(el)
  return { style: s.outlineStyle, width: parseFloat(s.outlineWidth) }
}, selector)

test.describe('Exam screen access @a11y', () => {
  test('a whole sitting works from the keyboard alone', async ({ studentPage, testTenant, request }) => {
    test.setTimeout(60_000)
    const exam = await createExam(request, testTenant, 'Access keyboard exam')
    await boot(studentPage, exam, testTenant)
    await tabTo(studentPage, /^Begin Examination$/)
    await studentPage.keyboard.press('Enter')

    // Focus lands in the answer box: the student can start writing at once.
    await expect(studentPage.locator(BOX)).toBeFocused()
    await studentPage.keyboard.type(ESSAY, { delay: 1 })

    // Tab leaves the answer box (no keyboard trap) and reaches the seal.
    await tabTo(studentPage, /^Seal & Submit$/, 6)
    studentPage.once('dialog', d => d.accept())
    await studentPage.keyboard.press('Enter')

    const done = studentPage.getByRole('heading', { name: 'Examination Sealed' })
    await expect(done).toBeVisible({ timeout: 20_000 })
    // Focus moves to the result, so a screen reader reads it out.
    await expect(done).toBeFocused()
  })

  test('the answer box and every control show a visible focus indicator', async ({ studentPage, testTenant, request }) => {
    const exam = await createExam(request, testTenant, 'Access focus exam')
    await boot(studentPage, exam, testTenant)
    await studentPage.getByRole('button', { name: 'Begin Examination' }).click()
    await expect(studentPage.locator(BOX)).toBeFocused()
    const box = await focusRing(studentPage, '.bk-writing')
    expect(box.style).not.toBe('none')
    expect(box.width).toBeGreaterThanOrEqual(2)

    // A disabled button takes no focus: write enough to enable the seal.
    await studentPage.keyboard.type(ESSAY, { delay: 1 })
    await tabTo(studentPage, /^Seal & Submit$/, 6)
    const seal = await focusRing(studentPage, '.bk-finish')
    expect(seal.style).toBe('solid')
    expect(seal.width).toBeGreaterThanOrEqual(2)

    await studentPage.keyboard.press('Shift+Tab')
    await studentPage.keyboard.press('Shift+Tab')
    const q = await studentPage.evaluate(() => {
      const s = getComputedStyle(document.activeElement)
      return { tag: document.activeElement.tagName, style: s.outlineStyle, width: parseFloat(s.outlineWidth) }
    })
    expect(q.tag).toBe('BUTTON')
    expect(q.style).toBe('solid')
    expect(q.width).toBeGreaterThanOrEqual(2)
  })

  test('the timer has a spoken label and the clock shows hours', async ({ studentPage, testTenant, request }) => {
    const exam = await createExam(request, testTenant, 'Access timer exam')
    const session = studentPage.waitForResponse(r => r.url().includes(`/bluebook/exams/${exam.id}/session`) && r.ok())
    await boot(studentPage, exam, testTenant)
    await studentPage.getByRole('button', { name: 'Begin Examination' }).click()
    await session
    const timer = studentPage.getByRole('timer')
    await expect(timer).toHaveText(/^1:59:\d\d$/, { timeout: 5_000 })
    await expect(timer).toHaveAccessibleName(/^Time remaining: 1 hour 59 minutes$/)
    // The start is announced once, politely.
    await expect(studentPage.locator('[role="status"][aria-live="polite"]').first())
      .toHaveText(/2 hours remaining|1 hour 59 minutes remaining/)
  })

  test('the word count is in the answer box description and milestones are announced politely', async ({
    studentPage, testTenant, request,
  }) => {
    const exam = await createExam(request, testTenant, 'Access words exam')
    await boot(studentPage, exam, testTenant)
    await studentPage.getByRole('button', { name: 'Begin Examination' }).click()
    const box = studentPage.locator(BOX)
    await expect(box).toHaveAccessibleDescription(/0 words written\. Write at least 12 words to submit\./)
    const seal = studentPage.getByRole('button', { name: 'Seal & Submit' })
    await expect(seal).toBeDisabled()
    await expect(seal).toHaveAccessibleDescription('Write 12 more words to submit.')

    await studentPage.keyboard.type(ESSAY, { delay: 1 })
    await expect(box).toHaveAccessibleDescription(/You have reached the 12-word minimum\./)
    await expect(studentPage.locator('.bk-sr[role="status"][aria-live="polite"]'))
      .toHaveText('You have reached the 12-word minimum.')
    await expect(seal).toBeEnabled()
  })

  test('a notice about leaving the window is polite, never an alert', async ({ studentPage, testTenant, request }) => {
    const exam = await createExam(request, testTenant, 'Access notice exam')
    await boot(studentPage, exam, testTenant, { blockWeb: true })
    await studentPage.getByRole('button', { name: 'Begin Examination' }).click()
    await expect(studentPage.locator(BOX)).toBeVisible()
    await studentPage.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
      document.dispatchEvent(new Event('visibilitychange'))
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
    })
    await expect(studentPage.getByRole('region', { name: /Notes for your teacher/ })).toBeVisible()
    await expect(studentPage.locator('[role="alert"], [aria-live="assertive"]')).toHaveCount(0)
    await expect(studentPage.locator('.bk-sr[role="status"][aria-live="polite"]')).toHaveText(/noted/i)
  })

  test("the blue cover's text clears AA contrast at the lightest point of its gradient", async ({
    studentPage, testTenant, request,
  }) => {
    const exam = await createExam(request, testTenant, 'Access contrast exam')
    await boot(studentPage, exam, testTenant)
    await expect(studentPage.getByText('Before you begin')).toBeVisible()
    await studentPage.waitForFunction(() => document.getAnimations().every(a => a.playState === 'finished'))
    const failures = await studentPage.evaluate(() => {
      const LIGHTEST = [0x43, 0x66, 0xac]   // .bk-cover's first gradient stop
      const parse = (c) => {
        const m = c.match(/rgba?\(([^)]+)\)/)
        const p = m[1].split(',').map(Number)
        return { rgb: p.slice(0, 3), a: p.length > 3 ? p[3] : 1 }
      }
      const over = (fg, bg) => fg.rgb.map((v, i) => fg.a * v + (1 - fg.a) * bg[i])
      const lum = (rgb) => {
        const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }
        return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2])
      }
      const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05) }
      const cover = document.querySelector('.bk-cover')
      const out = []
      for (const el of cover.querySelectorAll('*')) {
        const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())
        if (!own || !el.getClientRects().length) continue
        // Background: the lightest stop, with every translucent layer between
        // the cover and this element laid over it.
        const chain = []
        for (let p = el; p && p !== cover; p = p.parentElement) chain.unshift(p)
        let bg = LIGHTEST
        for (const p of chain) {
          const b = parse(getComputedStyle(p).backgroundColor)
          if (b.a > 0) bg = over(b, bg)
        }
        const s = getComputedStyle(el)
        const fg = over(parse(s.color), bg)
        const size = parseFloat(s.fontSize)
        const large = size >= 24 || (size >= 18.66 && Number(s.fontWeight) >= 700)
        const r = ratio(fg, bg)
        if (r < (large ? 3 : 4.5)) out.push(`${el.className || el.tagName} "${el.textContent.trim().slice(0, 30)}" ${r.toFixed(2)}`)
      }
      return out
    })
    expect(failures).toEqual([])
  })

  for (const [label, viewport] of [['200% zoom', { width: 640, height: 400 }], ['320px wide', { width: 320, height: 568 }]]) {
    test(`at ${label} nothing scrolls sideways and the sitting stays usable`, async ({
      browser, testTenant, request,
    }) => {
      const exam = await createExam(request, testTenant, `Access reflow exam ${label}`)
      const context = await browser.newContext({ viewport })
      const page = await context.newPage()
      await boot(page, exam, testTenant)
      const noSideways = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)

      const begin = page.getByRole('button', { name: 'Begin Examination' })
      await begin.scrollIntoViewIfNeeded()
      await expect(begin).toBeInViewport()
      expect(await noSideways()).toBe(true)
      await begin.click()

      const box = page.locator(BOX)
      await expect(box).toBeFocused()
      expect((await box.boundingBox()).height).toBeGreaterThanOrEqual(150)
      await page.keyboard.type(ESSAY, { delay: 1 })
      expect(await noSideways()).toBe(true)

      // Scrolled to the very bottom, the clock is still on screen...
      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
      await expect(page.getByRole('timer')).toBeInViewport()
      // ...and the seal button is reachable and not covered by anything.
      const seal = page.getByRole('button', { name: 'Seal & Submit' })
      await seal.scrollIntoViewIfNeeded()
      await expect(seal).toBeInViewport()
      const onTop = await seal.evaluate((el) => {
        const r = el.getBoundingClientRect()
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
        return el === hit || el.contains(hit)
      })
      expect(onTop).toBe(true)
      await context.close()
    })
  }
})

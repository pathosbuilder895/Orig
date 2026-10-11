/**
 * phone-nav.spec.mjs: the teacher navigation says it scrolls at phone width
 * (2026-10-11 button audit).
 *
 * At 375px the pill strip scrolls inside itself, and the pills past its edge
 * were out of sight with no hint. The strip now fades on the edge that has more
 * pills (.fade-end / .fade-start, TeacherWorkspace.jsx usePillFade), and every
 * pill can still be reached.
 */

import { test, expect } from './fixtures/tenancy.mjs'

test('the teacher pill strip fades on the edge that has more pills at phone width', async ({ staffPage }) => {
  await staffPage.setViewportSize({ width: 375, height: 812 })
  await staffPage.goto('/bluebook/')
  const strip = staffPage.locator('.teacher-pills')
  await expect(strip).toBeVisible({ timeout: 10_000 })
  // More pills to the right: the right edge fades, the left does not.
  await expect(strip).toHaveClass(/fade-end/)
  await expect(strip).not.toHaveClass(/fade-start/)
  const fade = await strip.evaluate(el => getComputedStyle(el).maskImage || getComputedStyle(el).webkitMaskImage)
  expect(fade).toContain('linear-gradient')
  // Scrolled to the end: the right edge is clear, the left fades.
  await strip.evaluate(el => { el.scrollLeft = el.scrollWidth })
  await expect(strip).toHaveClass(/fade-start/)
  await expect(strip).not.toHaveClass(/fade-end/)
  // The last pill is reachable.
  await expect(staffPage.getByRole('button', { name: 'Proctor' })).toBeVisible()
})

test('the strip does not fade where every pill fits', async ({ staffPage }) => {
  await staffPage.setViewportSize({ width: 1600, height: 900 })
  await staffPage.goto('/bluebook/')
  const strip = staffPage.locator('.teacher-pills')
  await expect(strip).toBeVisible({ timeout: 10_000 })
  await expect(strip).not.toHaveClass(/fade-(start|end)/)
})

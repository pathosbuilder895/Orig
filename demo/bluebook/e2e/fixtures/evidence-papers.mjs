/**
 * fixtures/evidence-papers.mjs: the writer the staff-only evidence specs share
 * (teacher-evidence.spec.mjs, past-paper-examples.spec.mjs, ADR-013).
 *
 * The writing is public domain: three passages of J. S. Mill's On Liberty
 * (1859) as the student's past papers, and a passage of G. K. Chesterton's
 * Orthodoxy (1908) as the paper analysed.
 */

import { readFileSync } from 'node:fs'
import { expect } from '@playwright/test'
import { addBaselineFor } from './api-setup.mjs'

const FIXTURES = new URL('./evidence/', import.meta.url)
const read = name => readFileSync(new URL(name, FIXTURES), 'utf8')
export const DATES = ['2026-01-14', '2026-02-11', '2026-03-10']
export const PAST = [1, 2, 3].map(i => ({ text: read(`mill-${i}.txt`), assignment: `On Liberty, part ${i}`, date: DATES[i - 1] }))
export const PAPER = read('chesterton.txt')

// The teacher adds the three past papers (verified). A student's own upload is
// kept as unverified and, since rule B (original/approved_papers.py), does not
// count toward the three-paper floor, so seeding with the student's token would
// leave Writing State nothing it may analyse.
export async function seedPastPapers(request, student, staff) {
  for (const p of PAST) {
    await addBaselineFor(request, student.student_id, staff.token, { text: p.text, provenance: 'verified', assignment: p.assignment, submittedAt: p.date })
  }
}

// Analyse the paper on Writing State as the teacher; returns the score response.
// `beforeFill` runs once the form is on the page, before anything is typed into it.
// Since 2026-10-30 Writing State leads with the essentials and keeps the
// heatmap, the tier chips and the detail rows in closed "Look closer"
// sections. A teacher opens them with one click on each heading; the specs do
// the same before they reach for a bar, a chip or a row.
export async function openLookCloser(page) {
  for (const id of ['deep-habits', 'deep-tiers']) {
    const fold = page.locator(`#${id}`)
    if (!(await fold.evaluate(el => el.open))) await fold.locator(':scope > summary').click()
    await expect(fold).toHaveAttribute('open', '')
  }
}

export async function analyse(page, studentId, { beforeFill } = {}) {
  await page.goto(`/original/writing-state.html?student=${encodeURIComponent(studentId)}`)
  await expect(page.locator('#an-form')).toBeVisible({ timeout: 20_000 })
  if (beforeFill) await beforeFill()
  await page.locator('#an-assign').fill('Orthodoxy, chapter 1')
  await page.locator('#an-text').fill(PAPER)
  const scored = page.waitForResponse(r => r.url().endsWith('/score') && r.request().method() === 'POST', { timeout: 90_000 })
  await page.locator('#an-go').click()
  const res = await scored
  expect(res.ok()).toBe(true)
  await expect(page.locator('#an-done')).toBeVisible({ timeout: 30_000 })
  return res.json()
}

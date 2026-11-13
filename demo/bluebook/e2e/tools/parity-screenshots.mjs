/**
 * parity-screenshots.mjs: capture the real Original staff pages (demo/original/)
 * for the demo-parity audit (docs/audits/demo-parity.md). NOT a spec and not run
 * by CI. Reusable: run it before and after a change and diff the JPEGs.
 *
 *   MAINTENANCE_TOKEN=ci-test-only PARITY_BASE_URL=http://localhost:8017 \
 *     PARITY_OUT=docs/audits/demo-parity/before \
 *     node demo/bluebook/e2e/tools/parity-screenshots.mjs
 *
 * The server must be a pilot-mode one with the staff-only evidence flags on
 * (ORIGINAL_ENV=pilot MAINTENANCE_TOKEN=ci-test-only EVIDENCE_PASSAGES_ENABLED=1
 * PRELIMINARY_SCORE_ENABLED=1 ... python run.py --demo --frontend-dir demo --skip-seed).
 * MAINTENANCE_TOKEN must equal the server's (the fixtures send it as X-Guard-Token).
 * It provisions its own tenant, teacher and student through the same helpers the
 * e2e specs use, seeds the three public-domain past papers, analyses the
 * Chesterton passage on Writing State, and screenshots at 1440x1000.
 *
 * Optional: PARITY_DEMO_URL=http://localhost:8018 (demo/prototypes/navy served
 * statically) and PARITY_DEMO_OUT=<dir> also capture the navy prototype pages.
 */

import { readFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { chromium, request as pwRequest } from '@playwright/test'
import {
  provisionTenantWithStaff, studentLogin, addBaselineFor, staffStorageState,
} from '../fixtures/api-setup.mjs'

const BASE = process.env.PARITY_BASE_URL || 'http://localhost:8001'
const OUT = process.env.PARITY_OUT
const DEMO_URL = process.env.PARITY_DEMO_URL
const DEMO_OUT = process.env.PARITY_DEMO_OUT
if (!OUT) { console.error('PARITY_OUT is required'); process.exit(2) }

const FIXTURES = new URL('../fixtures/evidence/', import.meta.url)
const read = name => readFileSync(new URL(name, FIXTURES), 'utf8')
const PAST = [1, 2, 3].map(i => ({ text: read(`mill-${i}.txt`), assignment: `On Liberty, part ${i}` }))
const PAPER = read('chesterton.txt')
const VIEWPORT = { width: 1440, height: 1000 }

mkdirSync(OUT, { recursive: true })
if (DEMO_OUT) mkdirSync(DEMO_OUT, { recursive: true })

async function shot(page, dir, name, fullPage = false) {
  await page.waitForTimeout(600) // let transitions settle
  await page.screenshot({ path: join(dir, `${name}.jpg`), type: 'jpeg', quality: 80, fullPage })
  console.log('wrote', join(dir, `${name}.jpg`))
}

async function realPages() {
  const api = await pwRequest.newContext({ baseURL: BASE })
  const { staff } = await provisionTenantWithStaff(api, { role: 'professor' })
  const student = await studentLogin(api, { staffToken: staff.token })
  for (const p of PAST) {
    await addBaselineFor(api, student.student_id, student.token, { text: p.text, provenance: 'verified', assignment: p.assignment })
  }
  await api.dispose()

  const browser = await chromium.launch()
  const context = await browser.newContext({ baseURL: BASE, viewport: VIEWPORT, deviceScaleFactor: 1, storageState: staffStorageState(BASE, staff) })
  const page = await context.newPage()
  const sid = encodeURIComponent(student.student_id)

  await page.goto('/original/index.html')
  await page.waitForLoadState('networkidle')
  await shot(page, OUT, '01-overview')

  await page.goto('/original/students.html')
  await page.waitForLoadState('networkidle')
  await shot(page, OUT, '02-students')

  await page.goto(`/original/writing-state.html?student=${sid}`)
  await page.locator('#an-form').waitFor({ state: 'visible', timeout: 20_000 })
  await page.locator('#an-assign').fill('Orthodoxy, chapter 1')
  await page.locator('#an-text').fill(PAPER)
  const scored = page.waitForResponse(r => r.url().endsWith('/score') && r.request().method() === 'POST', { timeout: 90_000 })
  await page.locator('#an-go').click()
  const res = await scored
  if (!res.ok()) throw new Error(`score failed: ${res.status()}`)
  await page.locator('#an-done').waitFor({ state: 'visible', timeout: 30_000 })
  await shot(page, OUT, '03-writing-state-result')

  // First habit: the first heatmap bar (a real habit, whatever the engine ranks).
  await page.locator('#heatmap [data-code]').first().click()
  await shot(page, OUT, '04-writing-state-habit-open')
  await page.keyboard.press('Escape')

  // Packet and Side by side take the result Writing State stored for them.
  async function viaButton(sel, name, urlRe) {
    await page.goto(`/original/writing-state.html?student=${sid}`)
    await page.locator('#an-done').waitFor({ state: 'visible', timeout: 30_000 })
    await page.locator(sel).click({ timeout: 10_000 })
    await page.waitForURL(urlRe, { timeout: 15_000 })
    await page.waitForLoadState('networkidle')
    await shot(page, OUT, name)
  }
  await viaButton('#tri-evidence', '05-side-by-side', /evidence\.html/)
  await viaButton('#tri-packet', '06-packet', /packet\.html/)

  await page.goto(`/original/baseline.html?student=${sid}`)
  await page.waitForLoadState('networkidle')
  await shot(page, OUT, '07-voice-baseline')

  await browser.close()
}

async function demoPages() {
  const browser = await chromium.launch()
  const page = await (await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1 })).newPage()
  const open = async (file, name) => {
    await page.goto(`${DEMO_URL}/${file}`)
    await page.waitForLoadState('networkidle')
    await shot(page, DEMO_OUT, name)
  }
  await open('original-dashboard.html', 'original-dashboard')
  await open('original-students.html', 'original-students')
  await open('original-quantum.html', 'original-quantum')
  // One habit clicked open on the state vector, as a visitor would.
  // The demo builds each habit bar as a div with data-code inside #heatmap
  // (original-quantum.html); a missing bar or evidence panel is a failure.
  await page.locator('#heatmap > [data-code]').first().click({ timeout: 5_000 })
  await page.locator('#hero-evi.show').first().waitFor({ state: 'visible', timeout: 5_000 })
  await shot(page, DEMO_OUT, 'original-quantum-habit-open')
  await open('original-flagged.html', 'original-flagged')
  await open('original-baseline-voice.html', 'original-baseline-voice')
  await browser.close()
}

await realPages()
if (DEMO_URL && DEMO_OUT) await demoPages()

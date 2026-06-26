// playwright.config.mjs — E2E tests for the Bluebook lockdown exam UI.
//
// Run locally:           npx playwright test
// Run a single test:     npx playwright test exam-flow.spec.mjs
// Open the test runner:  npx playwright test --ui
//
// The tests expect the Original demo server to be reachable at
// PLAYWRIGHT_BASE_URL (defaults to http://localhost:8001). CI starts the
// server via the workflow; local dev should start it manually with:
//     python run.py --demo --frontend-dir demo --port 8001
//
// NOTE: a separate worker per test is too expensive given the seed-load cost
// of the demo server (~1.5s). Stay single-worker.

import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.mjs',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['list'], ['github']] : 'list',
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:8001',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})

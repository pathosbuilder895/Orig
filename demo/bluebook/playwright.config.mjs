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
// WS-9 Stage 0.2: workers now run concurrently. This used to be single-
// worker because specs shared the one seeded demo tenant; specs that need
// isolated data now provision their own tenant via REST instead
// (fixtures/api-setup.mjs + fixtures/tenancy.mjs give each worker its own
// tenant/staff/operator/student). tenancy-isolation.spec.mjs is the
// negative assertion that isolation actually holds — don't raise workers
// further without keeping that spec green. Specs still touching the
// shared "demo" tenant (smoke/exam-flow) use timestamp-unique ids and are
// read-mostly, so they tolerate concurrent runs.
//
// workers is capped (not left unbounded) for a second reason: every worker
// mints a staff login via /auth/login, which shares one IP-keyed throttle
// bucket across the whole run (_LOGIN_MAX_ATTEMPTS=10 per 300s,
// original/api.py). Uncapped parallelism on a many-core CI runner can
// exceed that just from legitimate per-worker logins, 429-ing unrelated
// specs. 4 stays comfortably under it even with a11y.spec's per-screen
// workers; raise it only alongside raising the server's login throttle.
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.mjs',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  workers: 4,
  // WS-9 Stage 3: single retry in CI only, matching the audit's stated
  // posture (docs/implementation/WS-9-e2e-release-hygiene.md §Stage 3) —
  // this line previously said 2, which the audit flagged as a drift.
  retries: process.env.CI ? 1 : 0,
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

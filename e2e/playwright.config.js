// E2E test platform config (docs/designs/e2e-testing.md).
//
// Port-collision safety: phase 1 reuses the standard 8000/9000 ports with
// reuseExistingServer: false, so Playwright FAILS FAST if anything is already
// listening — a running dev stack can never be silently reused (that would
// point the tests at the dev DB). Stop your dev servers before an E2E run.
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './specs',
  globalSetup: './seed/global-setup.js', // resets minibini_e2e unless PW_KEEP_DB
  workers: 1, // shared DB → serial to start; revisit after factories mature (§9)
  retries: 0, // flakes get fixed, not retried (revisit for CI)
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:9000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: '../venv/bin/python ../manage.py runserver 8000 --noreload',
      env: { DATABASE_NAME: 'minibini_e2e' },
      url: 'http://localhost:8000/api/auth/me/', // 401 counts as "up"
      reuseExistingServer: false,
      stdout: 'ignore',
    },
    {
      command: 'npx vite',
      cwd: '../frontend',
      url: 'http://localhost:9000',
      reuseExistingServer: false,
    },
  ],
  projects: [
    // testDir override: auth.setup.js lives outside ./specs — without it the
    // setup project would match nothing and no persona would ever log in.
    { name: 'setup', testDir: './setup', testMatch: /auth\.setup\.js/ },
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      dependencies: ['setup'],
    },
  ],
});

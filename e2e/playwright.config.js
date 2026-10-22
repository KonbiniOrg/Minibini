// E2E test platform config (docs/designs/e2e-testing.md).
//
// E2E owns dedicated ports 8100 (Django, minibini_e2e DB) and 9100 (vite,
// via the VITE_PORT/VITE_API_TARGET overrides in frontend/vite.config.js),
// so the dev stack on 8000/9000 can stay up during a run. MINIBINI_SLOT=1..9
// moves a checkout to its own DB and ports (lib/slot.js) so checkouts can
// run e2e in parallel.
// reuseExistingServer: false makes Playwright FAIL FAST if anything is
// already listening on the E2E ports — a stray server can never be silently
// reused (that could point the tests at the wrong DB).
import { defineConfig, devices } from '@playwright/test';
import { baseURL, dbName, djangoPort, slot, vitePort } from './lib/slot.js';

export default defineConfig({
  testDir: './specs',
  globalSetup: './seed/global-setup.js', // resets the e2e DB unless PW_KEEP_DB
  workers: 1, // shared DB → serial to start; revisit after factories mature (§9)
  retries: 0, // flakes get fixed, not retried (revisit for CI)
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      // ensure_db.sh: first run of a new slot has no DB yet, and webServer
      // starts before globalSetup's reset.
      command: `bash seed/ensure_db.sh && ../venv/bin/python ../manage.py runserver ${djangoPort} --noreload`,
      env: { DATABASE_NAME: dbName, MINIBINI_SLOT: slot ? String(slot) : '' },
      url: `http://localhost:${djangoPort}/api/auth/me/`, // 401 counts as "up"
      reuseExistingServer: false,
      stdout: 'ignore',
    },
    {
      command: 'npx vite',
      cwd: '../frontend',
      env: { VITE_PORT: String(vitePort), VITE_API_TARGET: `http://127.0.0.1:${djangoPort}` },
      url: baseURL,
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

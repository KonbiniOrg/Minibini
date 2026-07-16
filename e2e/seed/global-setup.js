// Playwright globalSetup: rebuild the E2E database before every run.
// PW_KEEP_DB=1 skips the reset for fast local iteration, accepting that the
// kept DB may be stale/dirty (docs/designs/e2e-testing.md §3).
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const seedDir = path.dirname(fileURLToPath(import.meta.url));

export default function globalSetup() {
  if (process.env.PW_KEEP_DB) {
    console.log('PW_KEEP_DB set — skipping E2E database reset (kept DB may be stale or dirty)');
    return;
  }
  execFileSync('bash', [path.join(seedDir, 'reset_db.sh')], {
    stdio: 'inherit',
    env: { ...process.env, DATABASE_NAME: 'minibini_e2e' },
  });
}

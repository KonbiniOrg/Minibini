# E2E test platform — Playwright Test setup

> **Status: setup spec, approved direction (2026-07-07).** Not yet
> implemented — this doc is the complete instruction set for standing the
> platform up (RM will execute it soon; other developers follow §3 for
> their one-time setup). Written against main; **nothing here changes
> working app code** except the two flagged items in §10, which are
> deferred and need explicit sign-off. When implemented, the durable
> how-to graduates to `docs/designs/e2e-testing.md` (companion to
> `frontend-testing.md`) and this plan retires.

## 1. What this adds

A third test suite, driving the real stack in a real browser:

| Suite | Command | Scope | Data |
|---|---|---|---|
| Backend | `python manage.py test` | services/API | Django-managed throwaway test DB |
| Frontend | `cd frontend && npm run test:run` | components (Vitest, API mocked) | mocks |
| **E2E (new)** | `cd e2e && npx playwright test` | full stack, real browser | dedicated `minibini_e2e` DB, rebuilt per run |

Framework: **`@playwright/test`** — the Playwright project's own test
runner. It *contains* the browser-automation library (one install, not
two) and adds `test()`/`expect()`, fixtures, parallel workers,
per-failure screenshots/video, and the trace viewer. The
`docs/ui-flows/` checklists are the test scripts it will execute: one
`test.step()` per `[ ]` checkbox (that mapping is what those docs were
written for).

## 2. Directory structure

Everything lives in a top-level `e2e/` directory, fully separate from
the app — its own `package.json`, its own `node_modules`, nothing added
to `frontend/` and nothing imported from it:

```
e2e/
├── package.json            # sole dep: @playwright/test (pin the version)
├── package-lock.json       # committed — the lockfile IS the pin
├── playwright.config.js    # webServer, projects, baseURL, trace settings
├── seed/
│   ├── prepare_seed.py     # fixtures/playwright/seed.json → rebased.json (dates rebased, passwords normalized)
│   ├── reset_db.sh         # drop/create minibini_e2e, migrate, loaddata
│   └── global-setup.js     # Playwright globalSetup — runs reset_db.sh unless PW_KEEP_DB
├── setup/
│   └── auth.setup.js       # logs in each persona, saves storageState
├── fixtures/
│   ├── personas.js         # persona → storageState path + user facts
│   └── factories.js        # API-driven entity creation (jobs, tasks, bleps…)
├── specs/
│   ├── expenses.spec.js    # one spec file per docs/ui-flows/ doc
│   └── …
├── .auth/                  # storageState files   (gitignored)
├── test-results/           #                      (gitignored)
└── playwright-report/      #                      (gitignored)
```

`.gitignore` additions: `e2e/node_modules/`, `e2e/.auth/`,
`e2e/test-results/`, `e2e/playwright-report/`,
`fixtures/playwright/rebased.json`.

The seed lives outside `e2e/`: `fixtures/playwright/seed.json` is the
committed source (see §3.3), and the run-time rebased copy
`fixtures/playwright/rebased.json` sits beside it, gitignored (§4.1).

`e2e/package.json` (created when standing the platform up — `npm install`
does nothing useful in a directory without one; it just writes an empty
stub `package-lock.json`):

```json
{
  "name": "minibini-e2e",
  "private": true,
  "type": "module",
  "devDependencies": {
    "@playwright/test": "1.61.1"
  }
}
```

(1.61.1 was current as of 2026-07; pin whatever is current when standing
up, then bump deliberately per §8. The exact-version pin plus the
committed `package-lock.json` keeps every machine on the same runner.)

## 3. One-time developer setup

### 3.1 MySQL: the dedicated E2E database

E2E drives a live Django server, so it cannot use Django's transient
test DB — it gets its own schema, created once per machine. As
`root` (or any account with GRANT):

```sql
CREATE DATABASE minibini_e2e
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- The app's existing MySQL account drives it. Db-level ALL includes
-- CREATE and DROP *of this schema*, which reset_db.sh needs each run.
GRANT ALL PRIVILEGES ON `minibini_e2e`.* TO 'minibini_user'@'localhost';
FLUSH PRIVILEGES;
```

(Docker/remote-MySQL developers: repeat the GRANT for
`'minibini_user'@'%'` to match however their dev grant is written.)

No Django settings change is needed: `minibini/settings.py` already
reads `DATABASE_NAME` from the environment, so every E2E invocation of
Django is just prefixed `DATABASE_NAME=minibini_e2e` — the dev database
is untouchable by construction as long as that prefix is present, and
`reset_db.sh` hard-fails if it isn't (see §4.3).

### 3.2 Node side

`npm install` reads `e2e/package.json` (committed, see §2). If it doesn't
exist yet — i.e. you are standing the platform up for the first time —
create the directory and the `package.json` from §2 first; a bare
`npm install` in an empty directory installs nothing and leaves only a
stub `package-lock.json` (delete it or let the real install overwrite it).

```bash
cd e2e
npm install                      # installs @playwright/test per package.json
npx playwright install chromium  # one-time ~95 MB browser download
                                 # (lands in ~/Library/Caches/ms-playwright)
```

### 3.3 Seed dataset

The seed is `fixtures/playwright/seed.json`, a **committed** fixture (a
`dumpdata` export of a populated dev database) — a fresh checkout already
has it; nothing to generate or fetch. (The original plan used the
gitignored nealsdata converter output, `nealsdata/datasets/converted.json`;
a committed fixture was chosen instead so setup needs no out-of-band
files.)

**Seed hygiene — before (re-)committing the file:**

- **Strip `qbo.qboconnection` rows.** Not primarily for secrecy (the dev
  QBO credentials are sandbox-only, and RM has OK'd sandbox tokens in
  git) but for behavior: Playwright can't exercise a real QBO exchange,
  so the seed deliberately represents the *not-connected* state and
  specs assert the app's documented failure/disabled behavior in that
  state. (`qbo.qbosynclog` rows, if present, may stay — they FK only to
  a user, and "previously synced, now disconnected" is a reachable
  state.)
- **Drop rows for models that no longer exist** — a stale dump fails
  `loaddata` outright (e.g. `inventory.inventoryadjustment` after the
  InventoryHistory migration).
- `sessions.session` rows are harmless either way (sandbox data; E2E
  logs in through the real form regardless, §4.2).

## 4. Test data pipeline

### 4.1 The aging problem and the fix: date rebasing

The seed is `fixtures/playwright/seed.json` (committed; see §3.3). It is
frozen history — left alone, the 7-day Recent Time window, the 30-hour
blep-edit window, board retention, schedule forecasting, and estimate
expiry all drift out of test reach as it ages.

**Faking the clock is ruled out**: Playwright's `page.clock` only fakes
the *browser*; Django keeps real time, and frontend/backend clock skew
is exactly the bug class we don't want to manufacture. Instead the data
comes to the clock: `prepare_seed.py` rewrites the fixture JSON before
every load —

- Anchor on the newest **`core.jobhistory` timestamp** and compute the
  exact **whole-day** delta that lands it on yesterday (yesterday, not
  today, so a rebased afternoon timestamp can't sit in the test run's
  future). Job history is written at action time, so it can never
  postdate the dump and is always very recent in a fresh export — unlike
  the raw dataset maximum, which is typically a deadline (estimate
  expirations and job due dates legitimately sit in the dataset's
  future) or a session `expire_date` (dump-time + 2 weeks), and would
  drag recent activity weeks into the past, out of every window named
  above. Deadlines still shift by the same delta, so unexpired stays
  unexpired.
- Shift every ISO value by that delta. Matching is by *shape*, not by a
  per-field list, so it needs no maintenance as models grow: full
  timestamps (`YYYY-MM-DDTHH:MM:SS…`) and whole-string bare dates
  (`YYYY-MM-DD`). Strings that merely contain digits — `"JOB-2025-0001"`,
  `"EST-08013-2"` — match neither pattern and are never touched.
- A whole-day delta preserves everything the app derives from time:
  causal ordering, shift↔blep minute alignment, time-of-day patterns,
  relative gaps.
- Same pass, second job: overwrite every `core.user` `password` with the
  pre-computed pbkdf2 hash of `e2e_password` (constant baked into the
  script). The export's hashes have no known plaintext; this gives every
  persona a known login without any post-load DB writes.

Output: `fixtures/playwright/rebased.json`, peered with the source
(gitignored — it's derived and timestamped to the run; `reset_db.sh`
loads this file, never `seed.json`). The committed `seed.json` is
**never modified by a test run**: it only changes when deliberately
re-exported for model-shape changes (§8), like any normal file. The
delta is recomputed from the frozen source each run, so it simply grows
as the seed ages — no cumulative drift, no daily commits.

### 4.2 Personas (from the seed's real users)

| Persona | Username | Atoms |
|---|---|---|
| Worker | `schen` | none |
| Time manager | `arivera` | `can_manage_time` |
| Financials | `jkim` | `can_manage_financials`, `can_manage_jobs` |
| Config admin | `tbrooks` | `can_manage_config`, `can_manage_time` |
| Superuser | `dev_user` | is_superuser |

All log in with `e2e_password` (see §4.1). `auth.setup.js` (a Playwright
"setup" project that runs before the specs) logs each persona in once
through the real login form and saves the session to
`e2e/.auth/<persona>.json`; specs declare their persona by pointing
`storageState` at that file — the ui-flows docs' Personas sections map
onto this directly.

### 4.3 Reset per run — and why migrations never drift

`reset_db.sh` (invoked from Playwright's `globalSetup`):

```bash
#!/usr/bin/env bash
set -euo pipefail
# Refuse to run against anything but the e2e schema — belt & braces.
[ "${DATABASE_NAME:-}" = "minibini_e2e" ] || { echo "DATABASE_NAME must be minibini_e2e" >&2; exit 1; }
export DATABASE_NAME

# (Implemented version derives REPO_ROOT/SCRIPT_DIR from its own location
# and prefers venv/bin/python, so it runs from any cwd.)
# Credential defaults mirror minibini/settings.py so an unconfigured dev
# shell works; Django also reads .env, the mysql CLI does not.
mysql -u "${DATABASE_USER:-minibini_user}" -p"${DATABASE_PASSWORD:-dev_password}" \
  -h "${DATABASE_HOST:-localhost}" \
  -e "DROP DATABASE IF EXISTS minibini_e2e; CREATE DATABASE minibini_e2e CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
python "$REPO_ROOT/manage.py" migrate --no-input
python "$SCRIPT_DIR/prepare_seed.py"           # seed.json → rebased.json
python "$REPO_ROOT/manage.py" loaddata "$REPO_ROOT/fixtures/playwright/rebased.json"
```

The `DATABASE_NAME` guard is unit-tested (`tests/test_e2e_reset_db.py`)
so it can never silently rot — it must fail before any mysql/Django
command runs.

Because the schema is **dropped and rebuilt from current migrations on
every run**, there is no second database to remember to migrate — the
"how do we keep the e2e DB migrated" problem is designed out rather
than managed. The cost is a few seconds per run (the fixture is ~21 MB);
`PW_KEEP_DB=1 npx playwright test` skips the reset for fast local
iteration, accepting that the kept DB may be stale/dirty.

### 4.4 The layering rule for spec authors

- The rebased seed is the **backdrop**: lists, catalogs, history, the
  populated board — read-mostly assertions.
- The **subject** of a mutating test is created *by the test* through
  the API (`fixtures/factories.js` using Playwright's
  `APIRequestContext`): a spec exercising the settle-first stop starts
  its *own* blep seconds before asserting on it. Foreground state is
  genuinely "now", tests don't fight over shared rows, and reruns
  without a reset stay mostly coherent.

## 5. Playwright config (sketch — implemented; `e2e/playwright.config.js` is authoritative and adds a reporter line, the venv python path, and webServer `env`/`cwd` options)

```js
// e2e/playwright.config.js
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './specs',
  globalSetup: './seed/global-setup.js',   // runs reset_db.sh unless PW_KEEP_DB
  workers: 1,          // shared DB → serial to start; revisit after factories mature
  retries: 0,          // flakes get fixed, not retried (revisit for CI)
  use: {
    baseURL: 'http://localhost:9000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: 'DATABASE_NAME=minibini_e2e python ../manage.py runserver 8000 --noreload',
      url: 'http://localhost:8000/api/auth/me/',   // any responding route
      reuseExistingServer: false,
      stdout: 'ignore',
    },
    {
      command: 'cd ../frontend && npx vite',
      url: 'http://localhost:9000',
      reuseExistingServer: false,
    },
  ],
  projects: [
    // testDir override: auth.setup.js lives in setup/, outside ./specs —
    // without it the setup project matches nothing and no persona logs in.
    { name: 'setup', testDir: './setup', testMatch: /auth\.setup\.js/ },
    { name: 'chromium', dependencies: ['setup'] },
  ],
});
```

**Port-collision safety (important):** phase 1 reuses the standard
8000/9000 ports with `reuseExistingServer: false`, which makes Playwright
**fail fast if anything is already listening** — so a running dev stack
can never be silently reused (that would point the tests at the dev DB).
The tradeoff: stop your dev servers before an E2E run. §10 flags the
2-line change that would lift this later.

## 6. Writing specs from ui-flows docs

House pattern (establish with `expenses.spec.js` as the exemplar —
`docs/ui-flows/Expenses.md` is the most complete flow doc):

- One spec file per flow doc, named after it.
- One `test()` per numbered flow section; one `test.step('Label: action
  → expected result')` per `[ ]` checkbox, same wording — the doc stays
  the source of truth and diffs against the spec are eyeball-able.
- Personas come from the doc's Personas section via `storageState`.
- **Guard steps** (the "should be blocked" boxes) are first-class:
  assert the control is absent/disabled or the API answer is the
  documented 4xx — the flow docs call these the highest-value to
  automate.
- Subject entities via `factories.js`, backdrop from the seed (§4.4).
- Selectors: prefer `getByRole`/`getByLabel`/`getByText` against the
  semantic HTML the SPA already uses — no test-id attributes unless a
  surface is genuinely unaddressable (adding test-ids would touch app
  code → flag it first).

## 7. Running

```bash
cd e2e
npx playwright test                       # full run (resets DB first)
PW_KEEP_DB=1 npx playwright test          # skip the reset (fast iteration)
npx playwright test specs/expenses.spec.js
npx playwright test --ui                  # interactive UI mode (watch, pick, time-travel)
npx playwright test --headed              # visible browser
npx playwright show-report                # HTML report of the last run
npx playwright show-trace test-results/…/trace.zip   # replay a failure
```

Dev servers must be **stopped** first (§5). MySQL must be up.

## 8. Keeping it current as the app changes

- **Migrations:** nothing to remember — §4.3 rebuilds the schema from
  current migrations every run. If a migration lands mid-day, the next
  E2E run simply uses it.
- **Fixture drift:** the seed is a `dumpdata` snapshot, so when models
  change shape it lags the schema. A failing `loaddata` in `reset_db.sh`
  is the tripwire. The fix is to re-export from a migrated, populated
  dev database (`python manage.py dumpdata …` is read-only, so it's
  safe against the dev DB), re-apply the §3.3 hygiene strip
  (sessions, QBO tokens, retired models), and commit the refreshed
  `fixtures/playwright/seed.json`. For a *removed* model, deleting the
  dead rows from the existing file is fine too — that's schema repair,
  not data invention.
- **Rebase script:** shape-based matching (§4.1) means new datetime
  fields are picked up automatically; it only needs attention if a
  model ever stores a *string* shaped exactly like a bare ISO date that
  must not shift (none today; note it in the script header if one
  appears).
- **Specs vs ui-flows docs:** same rule as `docs/designs/` — when a
  session changes UI behavior, update the flow doc and its spec
  together. The checkbox↔step mirroring makes the diff obvious.
- **Playwright version:** pinned in `e2e/package.json`; bump
  deliberately (a bump can require re-running
  `npx playwright install chromium`).

## 9. Later / optional

- **CI:** the suite is CI-shaped already (own DB, own servers,
  `reuseExistingServer: false`); needs a MySQL service container and
  `npx playwright install --with-deps chromium`. Retries `1` in CI only.
- **Parallel workers:** once mutating specs are strictly
  factory-subject-based, `workers` can rise; specs asserting on shared
  backdrop rows (counts, totals) should then move to `test.describe.
  configure({ mode: 'serial' })` or assert on test-created entities.
- **`/run` project skill:** the same servers+login recipe doubles as
  the agent's app-driving skill; generate after implementation.

## 10. Deferred working-code touches (flagged, NOT done — need sign-off)

Per RM's instruction these are noted, not implemented; everything above
works without them:

1. **Dedicated E2E ports** (run E2E alongside a live dev stack):
   2-line env-var override in `frontend/vite.config.js` —
   `port: Number(process.env.VITE_PORT || 9000)` and
   `proxy: { '/api': process.env.VITE_API_TARGET || 'http://localhost:8000' }`
   — inert without the env vars; lets the webServer block use 8100/9100.
2. **Test-ids** — only if some surface proves unaddressable by
   role/label/text selectors (none known); each one is an app-template
   touch and gets flagged when proposed.

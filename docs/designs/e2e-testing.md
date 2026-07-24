# E2E testing (Playwright)

The third test suite, driving the real stack in a real browser. Companion
to `frontend-testing.md` (Vitest component tests) — this doc covers the
full-stack suite.

| Suite | Command | Scope | Data |
|---|---|---|---|
| Backend | `python manage.py test` | services/API | Django-managed throwaway test DB |
| Frontend | `cd frontend && npm run test:run` | components (Vitest, API mocked) | mocks |
| **E2E** | `cd e2e && npx playwright test` | full stack, real browser | dedicated `minibini_e2e` DB, rebuilt per run |

Framework: **`@playwright/test`** (pinned in `e2e/package.json`; the
committed `package-lock.json` is the pin). The `docs/ui-flows/`
checklists are the test scripts it executes — one `test.step()` per
`[ ]` checkbox.

## 1. One-time developer setup

### 1.1 MySQL: the dedicated E2E database

E2E drives a live Django server, so it cannot use Django's transient
test DB — it gets its own schema, created once per machine. As `root`
(or any account with GRANT):

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

No Django settings change is needed: `minibini/settings.py` reads
`DATABASE_NAME` from the environment, so every E2E invocation of Django
runs with `DATABASE_NAME=minibini_e2e` — the dev database is untouchable
by construction, and `reset_db.sh` hard-fails without that value (the
guard is unit-tested in `tests/test_e2e_reset_db.py`).

### 1.2 Node side

```bash
cd e2e
npm install                      # installs @playwright/test per package.json
npx playwright install chromium  # one-time ~95 MB browser download
                                 # (lands in ~/Library/Caches/ms-playwright)
```

That's it — the seed fixture is committed, so a fresh checkout needs
nothing else.

## 2. Layout and test structure

```
e2e/
├── package.json            # sole dep: @playwright/test (exact-version pin)
├── playwright.config.js    # webServer, projects, baseURL, trace settings
├── seed/
│   ├── prepare_seed.py     # fixtures/playwright/seed.json → rebased.json
│   ├── reset_db.sh         # drop/create minibini_e2e, migrate, load rebased seed
│   └── global-setup.js     # Playwright globalSetup — runs reset_db.sh unless PW_KEEP_DB
├── setup/
│   └── auth.setup.js       # logs in each persona, saves storageState
├── fixtures/
│   ├── personas.js         # persona → storageState path + user facts
│   └── api.js              # persona-authenticated APIRequestContexts (CSRF wired)
├── specs/
│   ├── smoke.spec.js       # platform smoke test
│   └── <flow-doc>/…        # a directory per docs/ui-flows/ doc (see below)
├── .auth/                  # storageState files   (gitignored)
├── test-results/           #                      (gitignored)
└── playwright-report/      #                      (gitignored)

fixtures/playwright/
├── seed.json               # committed seed (a dumpdata export; see §3)
└── rebased.json            # derived per run                    (gitignored)
```

Two Playwright projects run in order: **setup** (`setup/auth.setup.js`
logs each persona in once through the real login form and saves the
session to `e2e/.auth/<persona>.json`), then **chromium** (the specs).
Specs never see the login form — they pick a persona:

```js
import { personas } from '../fixtures/personas.js';
test.use({ storageState: personas.worker.storageState });
```

### Personas (all password `e2e_password`)

Usernames state the permissions, so a failure reads as "worker
couldn't…". They are stamped onto the seed's dev-DB users by
`prepare_seed.py`'s `PERSONA_RENAMES` map (the dev DB keeps its own
names — that divergence is deliberate, and the map is the single source
of the e2e names; `check_personas` fails the run if a seed refresh no
longer matches it).

| Persona key | Username | Display name | Atoms | Seed/dev user |
|---|---|---|---|---|
| `worker` | `worker` | Worker NoAtoms | none | `schen` |
| `timemgr` | `timemgr` | Time Manager | `can_manage_time` | `arivera` |
| `finjobs` | `finjobs` | Financials AndJobs | `can_manage_financials`, `can_manage_jobs` | `jkim` |
| `configtime` | `configtime` | Config AndTime | `can_manage_config`, `can_manage_time` | `tbrooks` |
| `superuser` | `superuser` | Super User | is_superuser | `dev_user` |

### Writing specs from ui-flows docs

House pattern (exemplar: `specs/smoke.spec.js` for the mechanics; the
first full flow spec should follow `docs/ui-flows/Expenses.md`):

- A **directory per flow doc** (`specs/expenses/` for
  `docs/ui-flows/Expenses.md`), containing **multiple spec files** — the
  flow docs each hold many numbered flows (Expenses has 11), so group a
  few related flows per file where they share setup (e.g.
  `reimbursement.spec.js` for the reimbursement + reject flows). Don't
  force a doc's every flow into one file, and don't mandate one file per
  flow either; file granularity is free (Playwright parallelizes across
  files when `workers` rises, and small files run selectively).
- Traceability to the doc lives in the titles, not the file layout: one
  `test()` per numbered flow section (title it `'§5 Stock receipts &
  cost-at-consumption'`), one `test.step('Label: action → expected
  result')` per `[ ]` checkbox, same wording — the doc stays the source
  of truth and diffs against the spec are eyeball-able.
- Personas come from the doc's Personas section via `storageState`.
- **Guard steps** (the "should be blocked" boxes) are first-class:
  assert the control is absent/disabled or the API answer is the
  documented 4xx.
- **Layering rule:** lean on the seed. Use existing backdrop data
  (jobs, catalog items, contacts, history) for everything a flow merely
  *references*, and create a new object only when the flow under test is
  the **making of that object** — an expenses-creation spec creates
  expenses through the UI but anchors them to a seed job. Stamp created
  objects with a per-run marker (e.g. `` `e2e-${Date.now().toString(36)}` ``)
  so list assertions can't collide with seed rows or `PW_KEEP_DB`
  reruns. When a spec does need API-side setup, `fixtures/api.js`
  provides persona-authenticated request contexts.
- Selectors: prefer `getByRole`/`getByLabel`/`getByText` against the
  semantic HTML the SPA already uses — no test-id attributes unless a
  surface is genuinely unaddressable (adding test-ids touches app code →
  flag it first).
- `workers: 1` — the DB is shared, so specs run serially for now.

## 3. Seed data pipeline

**Source:** `fixtures/playwright/seed.json`, a committed `dumpdata`
export of a populated dev database. It is never modified by a test run.

The export was augmented by hand 2026-07-23 with **email fixtures**
(10 `EmailRecord` + `TempEmail` pairs, appended in dumpdata format):
one thread per job lifecycle state — a draft-job inquiry, estimate
sends with acceptance replies (approved, in_progress), invoice sends
with replies (work_complete, completed), threaded via
`in_reply_to`/`references` and linked to their jobs — plus one
**unlinked vendor-invoice email** used by
`specs/email/inbox-and-po-link.spec.js` to exercise the
link-email-to-PO breadcrumb. Outbound bodies mirror the app's default
estimate/invoice templates (including the `{payment_link}` URL shape).
Job 67 was flipped to `completed` in the same pass so that state
exists in the seed (its deliverable has no pickup shipment — a
lifecycle shortcut acceptable in fake data). Also note the seed still
carries 13 inert legacy Bill rows (retired schema; kept deliberately).

A **QBO import snapshot** Configuration row (`qbo_import_snapshot`) was
appended 2026-07-23: two customers (one clean, one whose email collides
with seeded contact 1), empty items/terms/vendors lists so ONLY the
contacts panel renders anywhere. Exercised by
`specs/contacts/import-skip-report.spec.js` (partial commit + skip
report). Panels need no live QBO connection — only the pull button does.

**Rebase:** the seed is frozen history — left alone, the 7-day Recent
Time window, the 30-hour blep-edit window, board retention, schedule
forecasting, and estimate expiry would all drift out of test reach as it
ages. (Faking the clock is ruled out: Playwright can only fake the
*browser's* clock; Django keeps real time, and frontend/backend clock
skew is exactly the bug class we don't want to manufacture.) So the data
comes to the clock: before every run, `prepare_seed.py` writes
`fixtures/playwright/rebased.json` (gitignored):

- Anchors on the newest **`core.jobhistory` timestamp** — job history is
  written at action time, so it can never postdate the dump and is
  always very recent in a fresh export. (The raw dataset maximum would
  be wrong: estimate expirations, job due dates, and session expiry
  legitimately sit in the dataset's future.)
- Shifts every date/datetime string by the exact **whole-day** delta
  that lands that anchor on yesterday (not today, so a rebased afternoon
  timestamp can't sit in the test run's future). A whole-day delta
  preserves causal ordering, shift↔blep minute alignment, time-of-day
  patterns, and relative gaps. Matching is by *shape*, not a per-field
  list — whole-string ISO datetimes and whole-string bare dates — so new
  datetime fields are picked up automatically and strings like
  `"JOB-2025-0001"` or dates embedded in prose are never touched.
- Overwrites every `core.user` password with the pre-computed hash of
  `e2e_password`.
- Renames the persona users to their permission names (`PERSONA_RENAMES`;
  see the personas table in §2), rewriting the natural-key user FKs
  (`["schen"]` → `["worker"]`) in the same pass.

Unit tests: `tests/test_e2e_prepare_seed.py`.

**Reset per run:** Playwright's `globalSetup` runs `reset_db.sh`, which
drops and rebuilds `minibini_e2e` **from current migrations**, then runs
`prepare_seed.py` and loads `rebased.json`. Because the schema is
rebuilt from migrations every run, there is no second database to
remember to migrate. `PW_KEEP_DB=1` skips the reset for fast local
iteration, accepting that the kept DB may be stale/dirty.

**Refreshing the seed** (only for model-shape changes — a failing
`loaddata` in `reset_db.sh` is the tripwire): re-export from a migrated,
populated dev database (`dumpdata` is read-only, so it's safe against
the dev DB), in the shape the current seed uses:

```bash
venv/bin/python manage.py dumpdata --natural-foreign --indent 2 \
  -e contenttypes -e auth.permission > fixtures/playwright/seed.json
```

then apply the hygiene strip before committing:

- **Remove `qbo.qboconnection` rows.** Not for secrecy (dev QBO creds
  are sandbox-only) but for behavior: Playwright can't exercise a real
  QBO exchange, so the seed deliberately represents the *not-connected*
  state and specs assert the app's documented failure/disabled behavior.
  (`qbo.qbosynclog` rows may stay — they FK only to a user, and
  "previously synced, now disconnected" is a reachable state.)
- **Drop rows for models that no longer exist** — a stale dump fails
  `loaddata` outright.
- `sessions.session` rows are harmless either way (sandbox data; E2E
  logs in through the real form regardless).

For a *removed* model, deleting the dead rows from the existing file is
fine too — that's schema repair, not data invention.

## 4. Running

MySQL must be up; the dev stack can stay running. E2E owns dedicated
ports — Django on **8100** (with `DATABASE_NAME=minibini_e2e`) and Vite
on **9100** (via the `VITE_PORT`/`VITE_API_TARGET` env overrides in
`frontend/vite.config.js`, which are inert in normal dev use) — so it
runs alongside the dev servers on 8000/9000. Playwright starts both,
tears them down after, and `reuseExistingServer: false` makes it **fail
fast if anything is already listening on the E2E ports**, so a stray
server can never be silently reused.

```bash
cd e2e
npx playwright test                       # full run (resets DB first)
PW_KEEP_DB=1 npx playwright test          # skip the reset (fast iteration)
npx playwright test specs/smoke.spec.js   # one spec file
npx playwright test --ui                  # interactive UI mode (watch, pick, time-travel)
npx playwright test --headed              # visible browser
npx playwright show-report                # HTML report of the last run
npx playwright show-trace test-results/…/trace.zip   # replay a failure
```

`reset_db.sh` can also be run by hand from any cwd:
`DATABASE_NAME=minibini_e2e bash e2e/seed/reset_db.sh`.

Failures keep a trace and screenshot (`trace: 'retain-on-failure'`,
`screenshot: 'only-on-failure'`) under `e2e/test-results/`.

## 5. Keeping it current

- **E2E is part of Definition of Done (RM, 2026-07-20):** every piece of
  NEW work and every FIX ships with an e2e spec covering its user-visible
  flow, in the same session — alongside the backend/Vitest tests, not
  instead of them. Backfilling e2e for *unchanged* areas is NOT implied:
  RM commissions those explicitly, area by area. (Work with no runtime
  surface a browser can reach — pure services, management commands — is
  exempt; say so in the session notes instead of stretching for a fake
  flow.)
- **Migrations:** nothing to remember — the schema is rebuilt from
  current migrations every run.
- **Fixture drift:** a failing `loaddata` means the seed lags the
  schema; refresh it per §3.
- **Specs vs ui-flows docs:** same rule as `docs/designs/` — when a
  session changes UI behavior, update the flow doc and its spec
  together. The checkbox↔step mirroring makes the diff obvious.
- **Playwright version:** exact-pinned in `e2e/package.json`; bump
  deliberately (a bump can require re-running
  `npx playwright install chromium`).

## 6. Later / optional

- **CI:** the suite is CI-shaped already (own DB, own servers,
  `reuseExistingServer: false`); needs a MySQL service container and
  `npx playwright install --with-deps chromium`. Retries `1` in CI only.
- **Parallel workers:** once mutating specs are strictly
  factory-subject-based, `workers` can rise; specs asserting on shared
  backdrop rows (counts, totals) should then move to
  `test.describe.configure({ mode: 'serial' })` or assert on
  test-created entities.
- **Test-ids** — only if some surface proves unaddressable by
  role/label/text selectors (none known); each one is an app-template
  touch and gets flagged when proposed.
- **`/run` project skill:** the same servers+login recipe doubles as
  the agent's app-driving skill.

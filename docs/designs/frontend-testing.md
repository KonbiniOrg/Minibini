# Front-End Testing

Durable reference for the Svelte SPA's component/unit test suite. Covers the harness, how to run tests, the patterns to follow when writing them, and what we deliberately don't test. The companion `frontend/README.md` has the quick run commands; this is the how-and-why.

> Routes (`frontend/src/routes/**`) are **not yet under test** — a separate future sweep. This doc and the current suite cover `src/components/**`, `src/stores/**`, and `src/lib/**`.

## Stack

- **[Vitest](https://vitest.dev/)** — test runner; reuses the Vite/Svelte toolchain.
- **[@testing-library/svelte](https://testing-library.com/docs/svelte-testing-library/intro/)** (v5+, required for Svelte 5 runes/`mount`) — mount a component, query the rendered DOM, fire events.
- **@testing-library/jest-dom** — DOM assertion matchers (`toBeInTheDocument`, `toHaveAttribute`, …).
- **jsdom** — headless DOM so tests run in Node without a real browser.

Scope is component/unit testing only. End-to-end (Playwright) is a separate, deliberately deferred effort.

## Layout & running

```
frontend/
├── src/                      # app source
├── tests/                    # all tests, mirroring src/
│   ├── setup.js              # jest-dom matchers + storage shim (see below)
│   ├── lib/<name>.test.js
│   ├── stores/<name>.test.js
│   └── components/<Name>.test.js   # + _<Name>Harness.svelte where needed
└── vitest.config.js          # test-only config
```

**Setup:** the test tooling is declared in `package.json` as `devDependencies`,
so a plain `npm install` in `frontend/` pulls it in — no separate install step.

```bash
cd frontend
npm test          # watch mode — for development
npm run test:run  # one-shot — for CI / a quick full pass
npm run test:run tests/lib/format.test.js   # scoped, while iterating
```

Import source via the `@` → `src/` alias: `import { linkify } from '@/lib/linkify.js'`.

## Harness configuration

- **`vitest.config.js` is separate from `vite.config.js`** on purpose: `vite build` only reads `vite.config.js`, so test config (jsdom env, setup file, includes, alias) never touches the production build. The test config re-declares the `svelte()` plugin and adds `svelteTesting()` (from `@testing-library/svelte/vite`), which auto-configures the resolve conditions Svelte 5 needs to mount components — the usual cause of "component won't mount" errors.
- Settings: `environment: 'jsdom'`, `globals: true`, `setupFiles: ['./tests/setup.js']`, `include: ['tests/**/*.{test,spec}.js']`.

### The localStorage / sessionStorage shim (`tests/setup.js`)

Node 22+ ships an **experimental built-in `localStorage` global** that is only functional when Node is launched with `--localstorage-file`. Under the test runner it isn't, so Node's stub *shadows* jsdom's working `localStorage`, and any code calling `localStorage.getItem(...)` throws `localStorage.getItem is not a function` — failing the whole test file at import time.

Rather than depend on Node/jsdom version quirks, `tests/setup.js` installs a small deterministic in-memory `Storage` (a `Map` behind `getItem`/`setItem`/`removeItem`/`clear`) on `globalThis.localStorage` and `globalThis.sessionStorage`, cleared after each test. This unblocks every component touching storage — view-mode and the job workspace's per-job position (`stores/jobWorkspace.js`, §9.6 of `jobs-and-tasks.md`) both live in `localStorage`. (`JobDetail`'s accordion `sessionStorage` state — the reason `sessionStorage` was shimmed alongside `localStorage` — was retired with the accordion pillars, 2026-07-09; the shim covers both storages regardless in case a future component needs `sessionStorage`.) It is shared harness setup, not per-test boilerplate.

## What we test, and what we don't (triage)

Each file is classified once:

- **Behavior** → full coverage. Has logic worth pinning: event-driven `$state` transitions, async/`api` calls, conditional rendering driven by state, `$derived` transforms, form submission/validation, bindable-prop logic, list filtering/selection, drag/resize handlers.
- **Display** → **no test**. Pure presentational: renders props/text/markup with at most a trivial `{#if}`/`{#each}` over passed-in data, no interaction, no async, no branching. Testing these only re-states the template and breaks when copy changes.
- **Skip** → trivial wrappers / thin re-exports (e.g. `FullOnly`, `lib/api.js` itself, placeholder lists, notifier-only stores).

The tiebreaker for the boundary cases: **is there a branch or an async call that could silently break?** If yes, it's Behavior.

The original whole-SPA per-file classification lived in a disposable sweep plan (2026-06-04, since deleted); classify new or changed components with the triage above.

## Adding tests as you work

Front-end testing is meant to grow with the code, the same way the Django suite
does — not in big retroactive sweeps.

- **When you add or change a behavior component, store, or lib module, add or
  update its test in the same change.** Run `npm run test:run` and leave the
  suite green.
- **Classify new files with the triage rubric above** (behavior / display /
  skip), not a checklist. If there's a branch or an async call that could
  silently break, it's behavior — test it. If it's pure presentation, skip it.
- **Pick the matching pattern** from the table below and copy the cited example —
  the existing tests are the template.
- The set of "what's tested" is recorded by the test files themselves; there's no
  separate coverage list to maintain.

## Conventions (apply to every test)

1. **Assert structure and outcomes, not copy.** Query by role/placeholder/relevant text; never assert decorative wording; **never use snapshot tests.** Rewording a label must not break a test.
2. **Mock the `lib/api.js` seam, never `fetch`.** `vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))`; `mockReset()` in `beforeEach`.
3. **`await` every interaction** (`await fireEvent.…`) — Svelte 5 updates the DOM asynchronously after state changes. Skipping the await is the #1 cause of flaky tests.
4. **Use `findBy*` / `waitFor` after anything async** (a mocked api call, a `$effect`), not synchronous `getBy*`.
5. **`children` snippets need a harness.** A component using `{@render children()}` can't take a snippet from a plain `.js` test; wrap it in an underscore-prefixed `_<Name>Harness.svelte` (not collected by the `*.test.js` glob, just imported).
6. **Timers:** components that tick live durations use `vi.useFakeTimers()` / `vi.advanceTimersByTimeAsync(...)`; restore with `vi.useRealTimers()` in `afterEach`.
7. **Drag-and-drop:** jsdom has no real DnD. Dispatch `dragstart`/`dragover`/`drop` events with a stub `dataTransfer`, and assert the store action / callback fired with the right args — not pixel movement.
8. **Module-level mutable state:** for modules/stores holding state between calls (e.g. `stores/schedule.js`'s offset, `lib/paymentAccounts.js`'s cache), reset between tests — `vi.resetModules()` + dynamic `import`, or a purpose-built invalidate export.
9. **No silent skips.** A Display/Skip file is *intentionally* uncovered — don't add a smoke test "for completeness."
10. **jsdom enforces `required` on submit.** Clicking a submit button with empty `required` fields silently blocks the submit (the handler never runs). Fill *every* required field before asserting a form submission, or the test sees zero calls.

## The four patterns (canonical examples)

Every test follows one of these; copy the matching committed example.

| Pattern | When | Reference file |
|---|---|---|
| **Pure JS module** | `lib/` functions, pure transforms | `tests/lib/linkify.test.js`, `tests/lib/format.test.js` |
| **Store** | `stores/` state + actions | `tests/stores/viewMode.test.js`; api-backed: `tests/stores/auth.test.js`; module-reset: `tests/stores/schedule.test.js` |
| **Interaction component** (no network) | toggles, local state, events | `tests/components/Accordion.test.js` (+ `_AccordionHarness.svelte`) |
| **Async / network component** | hits `api.js`, async rendering | `tests/components/ContactPicker.test.js` |

## Coverage status

- **Done:** all of `src/lib/**` and `src/stores/**` worth testing, and every **behavior** component in `src/components/**` (pickers, modals, forms, board/schedule interaction, jobs/tasks/time stateful, home lists). Suite is ~90 files / ~300 tests.
- **Intentionally uncovered:** display-only components and trivial wrappers (see the triage rubric).
- **Lighter coverage by design:** `JobDetail` is an orchestrator (flagged oversized in `LATER.md`) — only a mount/wiring test; its deep derivations (version timeline, CO delta layering) are best unit-tested once it's split out.
- **Out of scope (for now):** `src/routes/**` — a separate future sweep.

# Frontend

Svelte 5 SPA that consumes the Django REST API.

## Structure

```
frontend/
├── src/
│   ├── lib/              # API client, utilities
│   ├── stores/           # Shared state (viewMode, etc.)
│   ├── components/       # Reusable components
│   ├── routes/           # Page-level components (routing, wiring)
│   ├── css/              # Global styles
│   ├── App.svelte        # Root: nav + router outlet
│   └── main.js           # Entry point
├── index.html
├── package.json
└── vite.config.js
```

Flat structure with relative imports, no aliases. `components/` holds reusable pieces, `routes/` holds page-level wiring. Content density (full vs lite) is handled by a runtime view mode toggle, not separate builds. See `docs/designs/architecture-and-conventions.md` §6 (View mode).

## Prerequisites

- Node.js (v20+): `brew install node` on macOS, or download from https://nodejs.org

## Setup

```bash
cd frontend
npm install
```

## Development

Start the Vite dev server:

```bash
cd frontend
npx vite
```

This runs on http://localhost:9000 and proxies `/api/*` requests to Django on http://localhost:8000. You need Django running separately (`python manage.py runserver`), or use `./dev.sh` from the project root to start both.

## Build

```bash
cd frontend
npx vite build
```

Output goes to `frontend/dist/`. In production, nginx serves these files directly.

## Front-end testing

Component and unit tests use [Vitest](https://vitest.dev/) with
[@testing-library/svelte](https://testing-library.com/docs/svelte-testing-library/intro/).

### Setup

The test tooling is declared in `package.json` as devDependencies, so a normal
install picks it up — no separate install step:

```bash
npm install
```

### Running tests

```bash
npm test         # watch mode — re-runs on change; use this during development
npm run test:run # one-shot run — use for CI / a quick full pass
```

### Where tests live

All tests live under `frontend/tests/`, mirroring the `src/` tree:

- `tests/lib/<name>.test.js`        — pure module / function tests
- `tests/components/<Name>.test.js` — Svelte component tests

Import source with the `@` alias (e.g. `import { linkify } from '@/lib/linkify.js'`).
Config lives in `vitest.config.js`, separate from `vite.config.js` so the
production build is unaffected.

For how to write tests (patterns, the behavior-vs-display triage, conventions,
the jsdom storage shim), see `docs/designs/frontend-testing.md`.

## Design Decisions

### Modals

Every form modal rides the shared shell, `src/components/Modal.svelte`. The
shell owns everything cross-cutting so it can't drift per-modal:

- **Geometry:** one place on screen — horizontally centered, anchored
  `--modal-top` (50px) from the top — so a modal handing off to another
  (picker → form) never moves on the user. `maxWidth` is the single sanctioned
  size knob. Every modal is draggable by its grab bar (position resets on each
  open) to peek at the page behind.
- **Keyboard contract:**
  - Every modal passes `onCancel` — **Escape always closes**. A modal with an
    internal sub-state (confirm-delete, a nested prompt) passes a smarter
    `onCancel` that backs out one level before closing.
  - **Enter** is decided by one question: *is the content a native `<form>`?*
    If yes, the form owns Enter (native submit + `required` validation) and
    you omit `onSave` — binding both would double-fire. If no (button-driven
    content), pass `onSave`. Deliberately Esc-only modals (an ambiguous
    primary action, e.g. `StartWorkConflictModal`'s join-vs-takeover) omit
    `onSave` **with a comment saying why**.
  - Pass the modal's in-flight flag as `busy` — the shell suppresses Enter
    while it's true (the busy-guard lives once, in the shell), so a
    double-Enter during a slow save can never fire the API twice. The Save
    *button* still wants its own `disabled={busy}` for the click path.
- **Not on the shell (deliberate):** `TaskQuickCard` — a positioned popup
  card with backdrop-click close, not a form modal.

New modals: prefer native-`<form>` content where the modal is genuinely a
form (free `required` validation, one submit path); wrap it in `<Modal>` and
wire only `onCancel`. As of 2026-07-04 **every** form modal in the app is a
native form (`<form onsubmit>` + `type="submit"` save button, all other
buttons `type="button"` — the HTML default inside a form is submit, so an
untyped Cancel would save); the shell's `onSave`/`busy` path remains for
future button-driven modals with an unambiguous primary action.

### Loaders called from `$effect` are write-only

Runes track *reads* transitively: an `$effect` subscribes to every piece of
`$state` read synchronously anywhere down its call stack, including inside
helper functions. So a loader that both reads and writes the same state
(`if (!task || …) { … } task = await api.get(…)`) turns the mount effect
into an infinite refetch loop — the effect re-runs every time the loader
lands (2026-07-06: TaskDetailPage refetched its whole fan-out 4-5×/second).

The rule, which the whole codebase already followed implicitly:

- A function invoked from an `$effect` may **write** `$state` freely but
  must **not synchronously read** `$state` that it (or anything the effect
  triggers) writes.
- Loader bookkeeping — "have I already loaded this?", last-loaded ids,
  in-flight guards — lives in **plain variables, not `$state`** (see
  `loadedTaskId` in `TaskDetailPage.svelte`), with a comment marking the
  non-reactivity as deliberate. Version-counter subscriptions (the
  `lastBlepVersion` pattern) keep their guard in `$state` only because the
  effect must re-check it; they never feed it back into a loader's reads.
- If a loader genuinely must branch on reactive state, wrap the read in
  `untrack()` — and treat needing that as a design smell first.

### Docsurface kit

`src/components/docsurface/` holds a seven-component kit shared by the
estimate and invoice editing surfaces (`EstimateEditView.svelte`,
`InvoiceEditView.svelte`) — `DocModeBar`, `BackingChip`, `AtomChildRow`,
`UncoveredWorkSection`, `NewLineFromSelectedRow`, `DocCustomerView`,
`DocReorderView`. It replaced the old two-column `ReconcileMode` wizard
presentation (2026-08, "skeleton phase"): a document now has **three
modes** — Edit / Customer / Reorder — switched in place at one URL by
`DocModeBar`, never a navigation or a modal. Full component-by-component
reference, the shared `app.css` classes, the flip-in-place mode pattern,
and the no-dead-buttons rule live in
`docs/designs/architecture-and-conventions.md` §5.5b; this entry is
just the two idioms every consumer of the kit follows:

- **Silent refresh.** The hosting panel's loader accepts a `{silent:
  true}` option that updates `$state` without flipping the page's
  loading flag. An edit view calls back (`onChanged`) after every
  gesture; a non-silent refresh would swap the loading branch in and
  unmount the edit view mid-gesture, losing its local state (an open
  modal, the current selection).
- **409-refresh.** A claim conflict from the atom-pull endpoints can't
  be resolved by retrying blind. `handleMutationError(e, fallback)`
  branches on `e?.status === 409`: clear the local selection, `await`
  a silent refresh, then show a specific "…refreshed" message via the
  global overlay instead of the generic error text.

### Timestamps: day names expire after a week

App-wide display convention (RM, 2026-07-06): a bare day name ("Sat
2:05 PM") is only meaningful within the last 7 days — beyond that it's
ambiguous and must give way to the calendar date ("Mar 1, 2:05 PM"),
with the year appended when it isn't the current year ("Dec 30 2025,
9:30 AM"). A day name *alongside* a date ("Sun 3/1", ActivityPage event
rows) is fine at any age — the rule targets day-name-only timestamps.

Use `formatSessionDateTime` from `src/lib/format.js` (BlepLogTable and
ShiftLogTable already do) instead of hand-rolling per-component
formatters. **Most older surfaces predate this rule — fix violations as
you find them** and route the fix through the shared helper.

### API Responses

- All API responses return JSON with a 200 status, even for operations like DELETE that normally have no meaningful data to return. No 204 responses. An empty response is `{}`.
- Error responses return JSON with a `detail` field and an appropriate 4xx status code.
- Successful delete responses may return a `message` field with a human-readable confirmation (e.g., `{"message": "\"Acme Corp\" has been deleted. 2 contact(s) were disassociated."}`).

### Serializer Tiers

Each model has up to three serializer tiers, used in different contexts:

| Tier | Naming | Used when | Example fields |
|---|---|---|---|
| **Summary** | `FooSummarySerializer` | Nested inside other objects as supporting data | id, name, status |
| **Standard** | `FooSerializer` | List views, create, update | All own fields + summary-level nested objects |
| **Detail** | `FooDetailSerializer` | Retrieve (detail view) — the object is the main focus | All standard fields + related object lists |

The ViewSet switches serializers based on the action:

```python
def get_serializer_class(self):
    if self.action == 'retrieve':
        return FooDetailSerializer
    return FooSerializer
```

Key rules:
- **Detail serializers** include related object lists (e.g., `BusinessDetailSerializer` includes contacts and jobs). These use summary serializers for the nested objects to avoid deep nesting.
- **Standard serializers** include key FKs as nested summary objects for display (e.g., `ContactSerializer` includes `BusinessSummarySerializer` for the contact's business) but not reverse relation lists.
- **Summary serializers** include only what's needed to identify and link to the object (id, name/title, maybe status).
- Write-only `PrimaryKeyRelatedField` fields (e.g., `business_id`) are added alongside read-only nested serializers to accept foreign key IDs on create/update.

### Error Handling

The API error contract (two body shapes, status semantics, the central
backend handler) is documented in
`docs/designs/architecture-and-conventions.md` §3.9 — read that first.
Frontend rules:

- The API client (`src/lib/api.js`) attaches `.status` and `.data` to every
  thrown error; `.data` is `null` when the body wasn't JSON (HTML error
  pages still carry `.status`).

**The three display venues** (every message goes to exactly one; users
learn where to look):

1. **Under the input** — field validation errors. Place
   `<FieldError {errors} field="x" />` (components/) directly below each
   input; the label stays above. Set the bag (`errors = t.fields`) once in
   the catch; every slot lights up.
2. **Under the form's buttons** — operation errors ("Job is on hold"),
   `non_field_errors`, and the rare in-form success ack. Place
   `<FormMessage error={...} success={...} />` immediately after the
   button row. Conflict responses that carry a next step (`code` +
   machine payload, e.g. the referenced-scheme 409) render an action
   button in FormMessage's children — see RateSchemeManager for the
   pattern.
3. **The global red/green overlay** — everything with no form: failed row
   actions, infrastructure errors (backend down, 5xx), page-level success
   acknowledgements. Raise it with `showError(...)` / `showSuccess(...)`
   from `stores/messages.js`; `MessageOverlay.svelte` (mounted once in
   App.svelte) renders it. Pages never carry their own overlay markup.

**The uniform catch block** for forms:

```js
import { triageError } from '../lib/errorTriage.js';
import { showError } from '../stores/messages.js';

} catch (e) {
  const t = triageError(e);
  if (t.overlay) showError(t.overlay);      // infrastructure → venue 3
  else { formError = t.message; errors = t.fields; }  // venues 2 + 1
}
```

Clear `formError`/`errors` at submit start and on open/cancel.

- Never `JSON.stringify(e.data)`; never display bare `e.message`
  (field-keyed errors reduce it to "Request failed"); never
  `window.alert()` for API results (`confirm()` for irreversible deletes
  is fine). Branch on `err.status` / `err.data?.code` for flow decisions.
- Load errors (page/object not found on mount) are not "messages" — they
  replace the page content, per the existing convention.
- The exemplar conversion is `components/RateSchemeManager.svelte`; the
  primitives are `lib/errorTriage.js`, `components/FieldError.svelte`,
  `components/FormMessage.svelte`, `stores/messages.js`,
  `components/MessageOverlay.svelte`.

### CSS

- Global styles live in `frontend/src/css/app.css`, imported via `main.js`
  **and** `portal-main.js` — global changes reach the customer portal too.
- No CSS frameworks. Semantic HTML with minimal global styles.
- **app.css is organized in three sections** — (1) BASE: tokens, element
  defaults, utilities, the page frame; (2) SHARED: families any page may use;
  (3) PAGE KINDS: vocabulary tied to the three page categories of the
  `.page-body` rollout below (fully-individualized / banner pages / plain
  pages). Page `<style>` blocks arrange and tune; if you're re-typing a look
  that exists globally — or copying a rule out of another component — promote
  it to app.css instead. Components may locally override a global family's
  *sizing* for dense contexts (e.g. the job header's smaller `.status-badge`)
  but never its colors.
- **Shared vocabulary (where the classes live):** `.status-badge` +
  `.status-{status}` (one pill palette for document statuses *and* task
  activity keys), `.data-table`, `.badge-invoiced`, `.row-actions` (put it on
  a cell/container; the small white edit/del buttons inside pick up the
  look), the feedback overlays; banner-page kit: `.toolbar` (+ its buttons),
  `.back-link`, `.page-title`, `.action-link`, `.edit-link` (quiet links in a
  dark banner), `.action-band` (+ `primary`/`quiet` buttons), `.stat-chips` /
  `.stat-chip` (+ `money`), `.panel` / `.panel-head` / `.panel-scroll`;
  plain-page kit: `.page-tabs` (works with `<button>` or `<a>` items). The
  task detail page is the reference implementation of the banner-page kit.
- **The categories are stations, not a taxonomy** — pages move III→II as area
  headers land, and out of the generic-sweep pool once they get a bespoke
  detail pass. The pipeline model and the skip-list of detailed pages live in
  `docs/designs/architecture-and-conventions.md` §5.5a.
- Error overlays (`.error-overlay`) have a red border; success overlays (`.success-overlay`) have a green border. Both share the same layout pattern.
- **z-index scale:** cross-component stacking uses named tokens defined on
  `:root` in `app.css` — `--z-sticky` (100) < `--z-dropdown` (200) <
  `--z-popover` (400) < `--z-sidebar` (600) < `--z-modal` (800) <
  `--z-modal-nested` (900, a modal opened from within a popover/modal) <
  `--z-toast` (1000, the global feedback overlay, always on top). Use
  `z-index: var(--z-modal)` etc. rather than bare numbers. Self-contained local
  stacks (the schedule lane stack; the JobHeader / hold-reason popover) keep
  their own small values and are intentionally off this global ladder.
- **Tables:** don't use the `border="1"` attribute (the light grey cell border
  comes from the global `table, th, td` rule). For a table full of data, opt into
  the house style with `class="data-table"` — full-width, padded cells, a teal
  header band, and a subtle grey zebra stripe. The stripe is defined with
  `:where(.data-table)` (zero specificity) so a table's own row classes (e.g.
  `.subtask-row`) override it without a fight; components may add scoped styles to
  tweak any `.data-table`. Tables that aren't tabular data (layout, key-value
  one-offs) and intentionally bespoke tables keep their own styling — `.data-table`
  is opt-in, not a global default. Scope is the Svelte SPA only; Django HTML
  templates follow their own table conventions (see root `CLAUDE.md`).
- **Page frame (`.page-body`):** the router wrapper (`.page-content` in
  `App.svelte`) has no padding, so raw page content sits flush at the left edge
  and gets covered by the slide-in sidebar. Give a page's main content a 10px
  left/right gutter by wrapping it in `<div class="page-body">`. The class is
  just `padding: 0 10px` — fluid width, zero-specificity, so scoped component
  styles always win. It is **opt-in** (like `.data-table`): a page gets the
  gutter only by adopting the wrapper.
  - **Structure:** a full-bleed header (a dark edge-to-edge band such as
    `JobHeader` or `CustomerHeader`) stays a sibling **outside** `.page-body` so
    it can still run edge to edge; only the body beneath it is wrapped. Pages with
    no banner — just a plain flush-left `<h2>` — wrap all their content, heading
    included. Fixed-position modals/overlays are unaffected by the padding and may
    sit inside or outside.
  - **Full-bleed header components (peers):** `JobHeader`
    (`components/jobs/JobHeader.svelte`) and `CustomerHeader`
    (`components/contacts/CustomerHeader.svelte`, used by both the contact and
    business detail pages) are peer banner components. Each is rendered by the
    route **above** `.page-body` and gets its own background color to signal the
    area — job = gray-800 `#1f2937`, contacts/business = red-950 `#450a0a`. More
    area headers with their own colors are planned. On job pages, `JobHeader` is
    always paired with `JobNavRail` (an eight-link section strip) and an
    optional collapsible `JobContextBand`; the trio is packaged as
    `components/jobs/JobShell.svelte` — **every** job route, including the
    overview (since the 2026-07-09 six-block redesign), renders
    `<JobShell>` and passes its content as the slotted children — one
    section panel for the other seven routes, the six summary blocks for
    the overview. See "Job workspace state" below and
    `docs/designs/jobs-and-tasks.md` §9.6, §9.1a.
  - **Subheaders:** anything a page wants to render *inside* the body that reads
    as a sub-bar (toolbars, filter rows) lives inside `.page-body` and aligns to
    the 10px gutter (drop any of its own horizontal padding so it lines up). A
    formal subheader class vocabulary is anticipated but not yet built.
  - **Tab headers:** the page-level tab bars (`catalog-tabs`, `settings-tabs`,
    `home-tabs` on Home + Users) share a `flex` + `border-bottom: 2px #ccc`
    idiom. To make the grey underline run edge-to-edge while the tabs stay
    indented, they break out of the gutter with `margin: 0 -10px` and push the
    tabs in with `padding-left: 120px`. This works because each tab `<nav>` is a
    direct child of `.page-body`. (In-content sub-tabs — `DocSubnav.svelte`'s
    per-document pills on the Estimates/Invoices section pages, the history
    tablist — are not page tab headers and keep their own styling. The job
    overview's old est/inv/po tab bars were retired with the accordion pillars,
    2026-07-09.)
  - **Rollout — three page categories:**
    1. **Fully individualized (no buffer):** Job board (`#/jobs/board`) and
       `#/schedule` own their whole layout; the login screen and the shipment
       packing-list *print* page aren't sidebar-framed pages. These deliberately
       do **not** get `.page-body`. **The job overview left this category
       2026-07-09** — see category 2.
    2. **Pages with a full-bleed banner header (buffer under the header):** every
       page that renders the shared `JobHeader` band — every job page, the
       overview included since 2026-07-09 (estimate, tasks/task-detail, invoice,
       shipments, POs, emails, history, overview, all sharing the `JobShell`
       header+rail+band layout) and the standalone change-order detail page —
       plus the contact/business detail pages (which render the peer
       `CustomerHeader`). The banner stays a full-bleed sibling; the body
       beneath it is wrapped in `.page-body`. Where such a page had a sub-bar
       with its own `24px` side padding (a `.toolbar` or `.page-header`), that
       padding was zeroed so it aligns to the 10px gutter. (The estimate/
       invoice "wizard" is no longer a separate page — it's a mode of the
       estimate/invoice panel at the same route; see "Job workspace state"
       below.) The overview's `.page-body` holds its six summary blocks
       (`docs/designs/jobs-and-tasks.md` §9.1a) — a bespoke,
       individualized body inside the shared `JobShell` chrome, not a kit
       consumer; see `docs/designs/architecture-and-conventions.md` §5.5a for
       the "hybrid" categorization this creates.
    3. **Everything else (whole content buffered):** all remaining list/form/
       detail/send pages, including search and the contacts/business list+form
       pages — wrapped in full.

    The only route-level `.svelte` files without `.page-body` are the four
    Category-1 pages above (job board, schedule, login, shipment print).

### Routing

- Hash-based routing (`#/path`). All internal links use the `#/` prefix.
- The `svelte-spa-router` library handles client-side navigation.

### View Mode (Full / Lite)

- A `viewMode` Svelte store (`'full'` or `'lite'`) controls content density at runtime.
- Defaults to `'lite'`, persisted in `localStorage`. (Server-side user preference planned.)
- Components use a `<FullOnly>` wrapper to hide sections in lite mode — avoids scattering `$viewMode` checks throughout components.
- Lite mode still fetches full data; hidden sections can be expanded inline without extra API calls.
- Responsive layout (mobile, kiosk) is handled separately via CSS media queries, independent of view mode.

### Job workspace state

- `stores/jobWorkspace.js` is the per-job equivalent of the `viewMode`
  pattern above: one `localStorage` key (`minibini_job_ws`), an
  LRU-capped map (50 jobs) instead of a key-per-job, so retention stays
  trivial. Per job it remembers which document each section (estimate,
  invoice) last showed, each document's `lines`/`reconcile` mode (keyed
  by document id, not section), and the job context band's
  collapsed/expanded state.
- The URL is always the source of truth for *what's currently
  displayed* (`#/jobs/:jobId/estimate/:docId`, etc.) — the store only
  answers "where did I leave off" when a bare section route or the
  context band mounts. `getJobWs(jobId)` reads the whole per-job
  record; `rememberSection` / `rememberMode` / `rememberBand` write one
  slice each.
- Restoring a remembered `reconcile` mode is validated against the
  document's live status (only offered on a draft) before being
  applied — see `docs/designs/jobs-and-tasks.md` §9.6.
- Routes: every job section is a real route under `#/jobs/:jobId/…`
  (`estimate[/:docId]`, `invoice[/:docId]`, `tasks[/:taskId]`,
  `shipments`, `pos`, `emails`, `history`). Old top-level document
  routes (`#/estimates/:id`, `#/invoices/:id`, and their `/wizard`
  variants) still resolve — via small redirect-shim route components
  that translate to the job-scoped URL (and, for the wizard variants,
  remember reconcile mode first) — so existing bookmarks and emitted
  links keep working.

### Material status vocabulary

- `lib/materialStatus.js` derives **one display status per material row** from
  serializer fields (no backend state): **Needs pricing / Needed / Ordered —
  PO-NNNN / Awaiting customer / On Hand / Consumed / Released** (precedence in
  that file), plus a `costUnconfirmed` ⚠ when `cost_source === 'estimated'`.
- **One row fragment, full actions everywhere** (the old task-view-page-only
  venue rule was retired 2026-07-13): material rows render through the shared
  `components/materials/MaterialRow.svelte` on every surface (job task list,
  task detail page, parent-task subtask tree), task rows through
  `components/tasks/TaskRow.svelte`, with row math in `lib/taskTotals.js`.
  The full per-material action set is available wherever rows render —
  gating is by material status, permissions, and job state only (each button
  still renders only when its callback is wired). Handler halves are shared
  too: `lib/materialOps.js` and the Order / Mark-received dialogs in
  `components/materials/MaterialFulfillmentModals.svelte`. The job overview
  doesn't render material rows at all — its Materials block is an aggregate
  Coverage stat only (`docs/designs/jobs-and-tasks.md` §9.1a).
- Full vocabulary + backend contract: `docs/designs/materials-inventory-and-purchasing.md` §16.

### Delete Flow

- First DELETE request (no `?confirm=true`) returns impact information and `confirm_required: true`.
- Frontend shows a confirmation prompt with the impact details.
- On confirm, the confirmation prompt is cleared immediately (returning the page to its normal state) and the confirmed DELETE is sent.
- On success, a success overlay displays the server's message. On error, an error overlay is shown.

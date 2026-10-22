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

**Sub-state, not stacking (RM 2026-10-10).** The shell has no stacking
contract: two open modals would both receive Escape (each attaches its own
window listener) and share one `--z-modal`. When a modal needs a nested
prompt — the create forms' duplicate-contact/business detection is the
standing example — render the prompt *inside* the modal as a sub-state:
keep the form mounted but `hidden` (never `{#if}`, so typed values survive),
render a plain fragment (`DuplicateContactNotice`) in its place, and pass
an `onCancel` that backs out one level (prompt → form → closed). Revisit a
real stack only if nested prompts multiply.

**`OrderModal` (PO order flow, 2026-10-15).** `components/purchaseorders/OrderModal.svelte`
is the one Order modal, with three `source`s: `material` (MaterialRow Order),
`item` (catalog Inventory/Earmarks "order") and `email` (email action panel "Create
new" PO — sender resolution as in-modal sub-states, like `EmailCreateJobModal`).
It creates nothing until Submit. It replaces `StockOrderDialog` (deleted) and
`EmailCreatePOPage` (deleted; `/email/:id/create-po` is a `RedirectTo` stub).
Picks a vendor with `VendorPicker`; see materials doc §15.

**Record forms are modals; create navigates, edit stays.** Since 2026-10-10
the contact, business, job, user, email create-job/link, document send,
reply, expense, catalog merge/write-off, service item, accounting
category, reimbursement batch, change-order deliverable and password forms
all open in the shell over whatever page the user is on (the page behind
stays visible for reference). A successful **create** closes and `push`es
to the new record's detail page; a successful **edit** calls `onSaved` and
the host reloads in place; **cancel** stays. Prefill context travels as
props (`defaultContactId`, `defaultBusinessId`), never query strings. The
retired `/new`, `/edit` and `/send` routes are `RedirectTo` stubs
(`routes/RedirectTo.svelte`, `wrap({ component, props: { to } })` in
`App.svelte`) that bounce stale links to the host page.

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
estimate, invoice, and change-order editing surfaces
(`EstimateEditView.svelte`, `InvoiceEditView.svelte`,
`COEditView.svelte`) — `DocModeBar`, `BackingChip`, `AtomChildRow`,
`UncoveredWorkSection`, `NewLineFromSelectedRow`, `DocCustomerView`,
`DocReorderView`. `COEditView` (2026-08-09) reuses `BackingChip` /
`AtomChildRow` / `UncoveredWorkSection` / `NewLineFromSelectedRow` over
the server-composed amended agreement rather than a document's own line
items — it is itself the Edit-mode content only; `ChangeOrderPanel`
wraps it in the same `DocModeBar` (Edit/Customer/Reorder, added
2026-08-09) the estimate/invoice panels use, with `COCustomerView` (a
sibling of `DocCustomerView`, not a reuse — a CO's customer-facing
document is a delta, not the whole agreement) and `DocReorderView`
(reused as-is) filling Customer/Reorder. It replaced the old two-column `ReconcileMode` wizard
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

### Job tab structure

Every tab of the job page (Overview, Estimates — change orders ride this
tab — Tasks, Invoices, Shipments, POs, Emails, History) has one semantic
shape (2026-10-21):

```
<section class="page-body" aria-labelledby="tab-<name>">   one region per tab
  <TabHeader id="tab-<name>" title=… {badges} {actions} />  <header><h2>…</h2> badges, actions right
  key numbers (the document tabs' stat chips), own row
  <section><h3>Sub-section</h3> … table (thead; tfoot for totals)</section>
  <EmptyState text="One sentence saying what to do next." {action} />
</section>
```

- **Headings:** the job's `<h1>` (JobHeader) → one `<h2>` per tab (the
  TabHeader title) → `<h3>` per sub-section. No skipped levels; modals are
  their own outline. Overview's six summary-block titles are `<h3>`s.
- **`TabHeader.svelte`** (`src/components/`): `id`, `title`, optional
  `badges` / `actions` snippets, `muted` (superseded document), `class`,
  `titleHidden`. With `titleHidden` the h2 stays (screen readers, heading
  order) but isn't shown: Overview, Tasks, Shipments, POs, Emails, and
  History pass it, because their title only repeats the rail tab. The rail
  tab is the visible title there (`JobNavRail` marks it `aria-current="page"`
  and weights it). The document tabs keep a visible title: it's the
  document's number, not the tab name. With no documents yet, the Estimates
  and Invoices tabs hide their title too ("Estimates" / "Invoices" only
  repeats the rail).
  The document tabs (estimate, change order, invoice) and Tasks pass
  `class="toolbar"` to keep the shared `.toolbar` button look. Shaped like
  the shadcn plan's PageHeader so it can be swapped later.
- **Document tabs:** the document's title ("Estimate: EST-…-2", "CO-3",
  "Invoice: …") is the h2; status pill/select goes in `badges`;
  `DocSubnav` stays above the region and `DocModeBar` inside it,
  unchanged. With no document yet, the h2 is the tab name ("Estimates").
- **Actions** that persist live in the header's right-hand group. An
  action that only exists because the tab is empty (Start Estimate, Start
  Invoice, Add Deposit Invoice) rides the empty state instead.
- **Empty states:** `EmptyState.svelte` (`text`, optional `action`
  snippet). A text-only empty list inside a `DataTable` keeps using its
  `emptyText` (same muted look).
- **Loading:** `LoadState` everywhere, including the Emails tab.

Tests: `tests/routes/JobTabStructure.test.js` (one case per tab: region,
h2 in the header, actions in the header, heading order) and
`e2e/specs/job-tabs-structure.spec.js` (same checks on a seeded job).

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
- Semantic HTML with minimal global styles.
- **One app font: Inter.** Self-hosted (`@fontsource-variable/inter`,
  imported in both entry points), set once on `body` as `var(--font-sans)`
  with `tabular-nums` (Inter's default digits vary in width; ours don't, so
  number columns align and counts don't shift nearby controls); form
  controls inherit it. Components never name their own sans face —
  only `var(--font-sans)`, `inherit`, or a monospace stack for code-like
  fields and board figures. `tests/appFont.test.js` enforces this.
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
  `.stat-chip` (+ `money`), `.panel` / `.panel-head` / `.panel-scroll`,
  `.section-title` (the 13px small-caps title of a section or summary block —
  `.panel-head` is the quieter 10px micro-label for identity panels);
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
- **Document colorways (`--doc-*` tokens):** four page-level custom
  properties — `--doc-accent`, `--doc-soft`, `--doc-border`, `--doc-faint`
  (zebra) — paint an area's chrome: the `.data-table` header band, zebra
  stripe, `.doc-subnav`/`.doc-mode-bar` bands, `tr.grand` totals, pool
  heading, stat-chip headers, and modal titles/grab bar. Job-area pages opt
  in via JobShell's `colorway` prop (`cw-estimate` indigo for estimates/COs,
  `cw-tasks` amber, `cw-invoice` sage, `cw-neutral` near-grey for
  POs/shipments/history/email); the `:root` defaults are the legacy house
  teal, so unclassed (non-Job) pages are unchanged. Hues are *place, not
  state* — never reuse them for status meaning. Palette lives in
  `css/app.css` (RM-approved 2026-08-14).
- **Tables:** don't use the `border="1"` attribute (the light grey cell border
  comes from the global `table, th, td` rule). For a table full of data, opt into
  the house style with `class="data-table"` — full-width, padded cells, a
  colorway-tinted header band (teal by default — see Document colorways
  above), and a subtle zebra stripe in the colorway's palest tint. The stripe is defined with
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
    area headers with their own colors are planned. `JobHeader`'s top-of-band
    notice slot holds `FrozenPartyBanner` (inactive contact) or, on an archived
    job, `components/jobs/ArchivedJobBanner.svelte`, which takes precedence
    (`docs/designs/jobs-and-tasks.md` §3.8). On job pages, `JobHeader` is
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
    3. **Everything else (whole content buffered):** all remaining list/
       detail pages, including search and the contacts/business lists —
       wrapped in full. (The former form/send pages are modals now; see
       "Modals" above.)

    The only route-level `.svelte` files without `.page-body` are the four
    Category-1 pages above (job board, schedule, login, shipment print).

### Routing

- Hash-based routing (`#/path`). All internal links use the `#/` prefix.
- The `svelte-spa-router` library handles client-side navigation.

### View mode: density and layout

- Two independent axes. **Density** (`stores/viewMode.js`, `'lite' | 'full'`)
  is a user preference, defaults to `'lite'`, persisted in `localStorage`.
  **Layout** (`stores/layout.js`, `'desktop' | 'phone'`) is a device fact
  from `matchMedia('(max-width: 720px)')`. Nothing infers one from the other.
- Mode-dependent behaviour lives in four seams only: `<FullOnly>` for
  sections, `$derived` filters for rows/labels, `components/DataTable.svelte`
  for columns (`lite: false` / `phone: false` flags; cards on phone), and the
  app shell. Routes never import either store.
- New list tables use `DataTable`; label/value layouts use `<dl>`. Editing
  grids and document line tables stay hand-written (architecture doc §6.2).
- Every fetch site wraps its content in `components/LoadState.svelte`
  (`{loading} {error}` + optional `loadingText`, default "Loading...");
  the error text comes from `errorMessage()` in the catch block. Never
  hand-write a loading/error branch. `TasksPanel` degrades partially by
  design and shows a `role="status"` notice naming what failed; the one
  remaining silent site (`SchedulePage`) is logged in LATER.md.
- Lite-content decisions are just starting: the only `lite:`/`phone:` flags
  set so far are on the Settings QBO sync log (`components/qbo/QBOSyncLog.svelte`,
  2026-10-17); every other table renders identically in lite and full.
- Lite still fetches full data; toggling density re-renders without a refetch.
- Full reference: `docs/designs/architecture-and-conventions.md` §6.

### Job workspace state

- `stores/jobWorkspace.js` is the per-job equivalent of the `viewMode`
  pattern above: one `localStorage` key (`minibini_job_ws`), an
  LRU-capped map (50 jobs) instead of a key-per-job, so retention stays
  trivial. Per job it remembers which document each section (estimate,
  invoice) last showed, each document's `edit`/`customer`/`reorder` mode
  (keyed by document id — `est:`/`inv:`/`co:` + id — not section), and
  the job context band's collapsed/expanded state.
- The URL is always the source of truth for *what's currently
  displayed* (`#/jobs/:jobId/estimate/:docId`, etc.) — the store only
  answers "where did I leave off" when a bare section route or the
  context band mounts. `getJobWs(jobId)` reads the whole per-job
  record; `rememberSection` / `rememberMode` / `rememberBand` write one
  slice each.
- Restoring a remembered mode is validated at the read site: a
  remembered `reorder` falls back to `edit` when the document can't be
  edited (not a draft, or no manage rights), and the legacy values
  `lines`/`reconcile` from the old two-mode panel normalize to `edit`
  (`EstimatePanel` / `InvoicePanel`) — see `docs/designs/jobs-and-tasks.md`
  §9.6.
- Routes: every job section is a real route under `#/jobs/:jobId/…`
  (`estimate[/:docId]`, `invoice[/:docId]`, `tasks[/:taskId]`,
  `shipments`, `pos`, `emails`, `history`). Old top-level document
  routes (`#/estimates/:id`, `#/invoices/:id`, and their `/wizard`
  variants) still resolve — via small redirect-shim route components
  that translate to the job-scoped URL (and, for the wizard variants,
  remember `edit` mode first) — so existing bookmarks and emitted
  links keep working.
- All `#/jobs/:id[/section]` routes resolve to **one** component,
  `routes/jobs/JobWorkspace.svelte`, registered through a single shared
  `wrap()` object (`routes/jobs/jobWorkspaceRoutes.js`). svelte-spa-router
  remounts whenever a route's component object changes, and every
  `wrap()` call (or bare component entry) is a distinct object — sharing
  one object is what keeps the shell mounted across rail clicks (issue
  #511); the job is then silently revalidated on each in-workspace
  navigation and re-assigned only if it changed, so freshness matches the
  old remount-per-route layout without the flicker. The section *and* the route params come
from `$location`, not the router's `params` prop, which lands a tick
later and would hand a freshly-mounted body the previous section's id;
  per-section bodies live in `routes/jobs/bodies/`. `onJobChange` still
  flows callback-up to the workspace's `loadJob`, which hands a new `job`
  object props-down; bodies key their reloads on that identity. Task
  detail (`#/jobs/:jobId/tasks/:taskId`) stays a separate page.
- **Convention — sibling routes that share chrome share one route object.**
  `svelte-spa-router` remounts the page component whenever the matched
  route's component object differs from the previous one, and *every*
  entry in the route table is its own object (each `wrap()` call, and
  each bare component entry, which the router wraps in a fresh closure).
  So a group of routes meant to behave like tabs under one persistent
  header — or to share any fetched context — must point at a single
  shared `wrap({ component })` value and derive what to show from
  `$location`/`params`, as `routes/jobs/jobWorkspaceRoutes.js` does.
  Listing the same component several times, or calling `wrap()` per
  route, silently gives you a full remount on every tab switch. (Known
  latent case: `/`, `/profile`, `/help` → `Home` are three entries today — #515.)

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

### Pagination

Every paged list renders `components/Pager.svelte` (`page`, `count`, optional
`pageSize` / `label`, `onPage(n)`); it hides itself when everything fits on
one page. Both buttons are always in the DOM — Previous is disabled on page 1
and Next on the last page, never removed — so the buttons sit in the same
place on every page and the pointer never has to chase Next after a click.
Don't hand-roll `{#if page > 1}` pagers.

### Delete Flow

- First DELETE request (no `?confirm=true`) returns impact information and `confirm_required: true`.
- Frontend shows a confirmation prompt with the impact details.
- On confirm, the confirmation prompt is cleared immediately (returning the page to its normal state) and the confirmed DELETE is sent.
- On success, a success overlay displays the server's message. On error, an error overlay is shown.

# Job workspace restructure — design

_2026-07-08, RM + Claude. Agreed direction; implementation on its own branch._

## The shift

From hub-and-spoke ("the overview is the job; everything else is a document
page you visit") to a **workspace model** ("every job page *is* the job,
focused on one aspect"). The job nav rail (shipped on `feature/ui`,
`9fde8cf7`) made lateral movement free; this restructure makes the job's
context travel with the user.

## Agreed shape

1. **The overview remains** the landing page at `#/jobs/:id`. The accordion
   pillars are **killed**, replaced by an as-yet-undefined full overview of
   all the bits at the bottom of the page. (Design the replacement during
   implementation — status/count cards are the working hypothesis; do this
   step LAST, after the section pages prove out.)
2. **The JobHeader expands** to include description, deliverables, and
   email, and gains a **collapse option** so the expanded context is
   hidable. Collapsed/expanded state persists like other local UI state.
3. **The nav rail stays always available** on every job page, **including
   the reworked overview** (whether it docks into the collapsible header
   block alongside the three detail sections or stays its own strip is an
   implementation-time call — RM is agnostic). Every rail link is always
   valid: empty sections are real destinations (see 6), so no dimming.
4. **Wizards are an alternate view type of Estimate or Invoice** from the
   user's perspective — a *mode* of the document surface, not a separate
   destination. Restores the user to whatever mode they left the page in.
5. **No combo views yet.** The architecture leaves room for them (see
   taxonomy) but none ship in this pass.
6. **Section pages, one panel each** (confirmed 2026-07-08: NOT all
   five panels stacked on every page). Each panel carries **subnavigation
   over all associated objects of its type** (estimate versions + change
   orders; the job's invoices; tasks; shipments; the job's POs). Which
   document is shown is **per-job persisted user state** — restored on
   return, defaulting to the latest when no state exists for that job.
7. **Empty sections still display** — a job fresh from creation has none
   of these; a job awaiting approval has no invoices — rendering the
   panel frame with a create affordance (like today's "Start Estimate"
   pillar), not a dead end.
8. **The rail grows to eight: Overview · Estimates · Tasks · Invoices ·
   Shipments · POs · Emails · History** (decided 2026-07-08; nine if
   Notes graduates — see 11). With the rail on the overview page too,
   Overview stops being an "up a level" escape (the ‹ chevron grammar
   dissolves) and becomes the first sibling destination, lit like any
   other when you're on it — kept first, with its wider gap, as the
   anchor. Email and History are taxonomically distinct from the
   Big Five (paper trail, not sub-object work surfaces) and have
   different lifecycle uses — email is a live reference used constantly
   while estimating/task setup/work happen; history is forensic (what
   happened when, after the fact) and owner review across jobs. They get
   **separate section pages**, but everything lives in the one rail —
   fewer places to learn navigation beats taxonomy purity. Optional
   polish: a wider gap or hairline divider between POs and Emails to
   mark the seam. **History comes out of the Actions menu** (it was
   navigation, not an action), leaving Actions = Edit + Duplicate.
9. **Job edit (and Duplicate) become modals** — the job's own fields are
   a thin record (name, contact, PM, dates, customer PO, description);
   a modal lets you edit from any job page without disturbing panel
   state. Old `/jobs/:id/edit` route shims or retires.
10. **The email panel is the full reading surface** — wide, master-detail
   (thread list + full conversation; first consumer of the LATER.md
   thread-view idea). The header band's email box stays as the
   glanceable live-reference preview with a "view all →" tether into the
   panel. Band = context that travels with you; panel = the full
   surface — that preview→surface relationship is the design's grammar
   (description and deliverables in the band work the same way), not
   duplication to eliminate.
11. **Notes** are flagged to become a first-class sub-object
   (LATER.md 2026-07-08) — they bridge live communication and the
   forensic record. Not scheduled in this pass; the workspace should
   just not paint them into the History corner architecturally.

## Architecture: section panels + a job shell

- **Section panels** — `EstimatePanel`, `TasksPanel`, `InvoicePanel`,
  `ShipmentsPanel`, `POPanel`, plus the paper-trail pair `EmailPanel`
  (master-detail thread reading) and `HistoryPanel` (the collated feed,
  absorbing today's JobHistoryPage): the working guts of today's route pages,
  extracted into components that take a job (plus their own document id)
  and own their data loading. This is the same extraction LATER.md already
  wants for the oversized route pages (TaskDetailPage 527 lines,
  JobTaskListPage 427, JobShipmentsPage 418…) — extract first, then
  unit-test the pieces.
- **The job shell** — one layout component: JobHeader (now with the
  collapsible description/deliverables/email band) + nav rail + one hosted
  panel. Route pages collapse to glue: resolve the job, pick the panel.
- **Page taxonomy** (the seam test: *does any interaction cross the seam?*):
  1. **Section page** — shell + one panel.
  2. **Combo page** (future) — shell + two *independent* read-mostly
     panels; zero cross-pane coupling. First candidate when the time
     comes: estimate|invoice (RM compares these daily today via two
     browser windows); also plausible: invoice|shipments, tasks|POs.
  3. **Reconciliation surface (wizard)** — shell + one *composite* panel
     with an internal two-column layout (atom pool ⇄ document lines) and
     owned cross-column state. The wizard composed itself; it is never a
     pane in a combo, and it needs full width.

## Wizards specifically

- Reconcile mode becomes a **mode of the document panel** (`EstimatePanel` /
  `InvoicePanel`): lines mode ↔ reconcile mode, flipped in place on the
  same route, same shell, one job load. This delivers two standing
  LATER.md entries: "merge the source-pull view into the detail page as an
  in-place toggle" (2026-06-02) and "make the estimate and invoice
  atom-pull UIs consistent" (2026-06-03).
- **Mode persistence:** RM explicitly does not care about routes here —
  the requirement is "the user goes back to the state they left the page
  in." Store the per-document view mode in localStorage alongside the
  app's other local UI state (the `viewMode` store is the pattern).
- One reconcile-mode component parameterized per document type, mirroring
  the backend's `BaseWizardService` config-block pattern.
- Reuse is **row-level, not panel-level**: the wizard's atom pool is NOT
  `TasksPanel` (different concerns — claim state vs. working tasks); they
  share row/table vocabulary (task rows, material rows, LineItemTable /
  WizardLineItemCard) so the surfaces stay visually consistent without
  sharing state machinery.

## Constraints & cautions carried over from the discussion

- **POs aren't job-owned**: `POPanel` is a job-filtered PO list with
  click-through, not a single document; the PO detail page stays global.
- **One route family, all under the job** (decided 2026-07-08 — RM wants
  past documents inside the structure too, with full job context):
  - `#/jobs/:jobId/estimate`, `#/jobs/:jobId/invoice`, etc. — the five
    section routes. The bare route restores the user's per-job document
    state (or the latest). Routes deliberately do NOT drive document
    selection — that's panel state persisted in localStorage (RM: "the
    user goes back to the state they left the page in"; routes are not
    the mechanism she cares about).
  - Superseded estimates and earlier invoices are reached through the
    panel's own subnavigation — same shell, same panel, full job context.
    An optional `/:docId` form (or the shim writing state before
    navigating) covers deep links that must land on a specific document
    (history `source_link`s, search results) — implementation detail.
  - The old document routes (`/estimates/:id`, `/invoices/:id`,
    `/change-orders/:id`) become **redirect shims** into the job-scoped
    structure. Existing emitters and bookmarks keep working; internal
    emitters migrate over time; the shim stays (it's cheap).
  - Consequence for the nav rail: every section link is always valid
    (empty sections render with a create affordance), so the rail needs
    no dimming and `nav_targets` retires.
- **Context band restraint**: description/deliverables/email on working
  pages must default collapsed (especially in reconcile mode) — glanceable
  context, not a vertical tax.
- **Width**: reconcile mode is intrinsically full-width. Combos, when they
  come, are read-mostly precisely so panels don't need a narrow-editing
  mode.

## Sequencing

1. Extract section panels from the route pages (pairs with the LATER.md
   componentization entry; unit-test extracted pieces).
2. Job shell (header + rail + collapsible context band); section routes
   render panels through it; rail targets flip over.
3. Wizard-as-mode of the document panels, with localStorage persistence.
4. Rework the overview: kill the pillars, design the replacement bottom
   overview.
5. (Future, separate decision) combo views.

---

# Implementation context (captured 2026-07-08, end of design session)

Facts a builder needs that live in this session's context and are easy to
lose. Verify against code before relying on any of it — it's a snapshot.

## Current inventory: what exists and where

**Pages that mount JobHeader today** (all fetch `/api/jobs/{id}/` detail,
so the full job payload incl. `can_manage` is already in hand on every one):

| Page | Route | Rail `current` today | Fate under this design |
|---|---|---|---|
| `components/jobs/JobDetail.svelte` (the overview; composed by `routes/jobs/JobDetailPage.svelte`) | `/jobs/:id` | (no rail yet) | keeps header; pillars die; gains rail |
| `routes/estimates/EstimateDetailPage.svelte` (344 ln) | `/estimates/:id` | estimate | → EstimatePanel + shim |
| `routes/estimates/EstimateWizardPage.svelte` | `/estimates/:id/wizard` | estimate | → EstimatePanel reconcile mode |
| `routes/change-orders/ChangeOrderDetailPage.svelte` (**1038 ln**, biggest extraction risk) | `/change-orders/:id` | estimate | → estimate-panel subnav + shim |
| `routes/invoices/InvoiceDetailPage.svelte` | `/invoices/:id` | invoice | → InvoicePanel + shim |
| `routes/invoices/InvoiceWizardPage.svelte` | `/invoices/:id/wizard` | invoice | → InvoicePanel reconcile mode |
| `routes/jobs/JobTaskListPage.svelte` (427 ln) | `/jobs/:id/tasklist` | tasks | → TasksPanel |
| `routes/jobs/TaskDetailPage.svelte` (527 ln; had its own detail pass 2026-07-07, see skip-list in architecture doc §5.5a) | `/jobs/:jobId/tasks/:taskId` | tasks | task detail within TasksPanel subnav — route already job-scoped, may survive as-is |
| `routes/jobs/JobShipmentsPage.svelte` (418 ln) | `/jobs/:jobId/shipments` | shipments | → ShipmentsPanel (recommended FIRST extraction: no wizard, no version chain) |
| `routes/jobs/JobHistoryPage.svelte` | `/jobs/:id/history` | (none lit) | → history section page |

The **send pages** (`EstimateSendPage`, `InvoiceSendPage`,
`PurchaseOrderSendPage`, `ChangeOrderSendPage`) do NOT mount JobHeader and
are untouched by this design. `PurchaseOrderDetailPage` is global (POs
span jobs) and stays outside the shell; the job's POs section is a
filtered list (`/api/purchase-orders/?job=<id>` — resolves via
Material(job=X, po_line_item→line) join, see
`apps/api/purchasing/views.py` get_queryset).

## JobHeader internals (as of `feature/ui` HEAD)

`components/jobs/JobHeader.svelte` — fixed **110px**, grid
`minmax(0,1fr) auto`. Left: truncating title (`title` attr hover), customer
line, status row. Right: facts line (dates/PO/PM, 14px, `top: -3px` nudge)
over the money grid (Estimate|Spent|Invoiced|Profit — detail-only
serializer fields, `$—` when null). Status row holds:

- **Actions menu** (solid `#e5e7eb` pill, matches status-pill shape):
  Edit / Duplicate… / History links. Under this design History leaves,
  Edit/Duplicate become modals — at 2 items consider dissolving the menu.
- **Trigger pill** (`<select>`): local `VALID_TRANSITIONS` (a deliberate
  subset of the model's), trigger options with `__`-prefixed values —
  `__hold` opens the hold-reason modal (a `Modal.svelte` dialog already in
  this component — the edit modal will be its sibling), `__release_hold`
  posts release. approved→in_progress is labeled "Release to floor".
  Held jobs: pill shows striped **HOLD** (true status masked), reason
  inline with "WHY:" label. Pill snaps back (`e.target.value = job.status`)
  when a trigger is picked.
- Gating: everything keys off `job.can_manage` (per-object, PM-scoped;
  NOT the global atom store) — panels must carry this through.

The expansion (description/deliverables/email band + collapse) goes on TOP
of this. JobDetail's midband today: `grid 1fr 1fr 320px`, 200px fixed,
description panel + DeliverablesSection + EmailPanel; overview accordion
assumes `min-height: calc(100vh - 310px)` (110 header + 200 midband) —
killing pillars/midband frees this but check `.job-detail-page`
(100vh flex column, overflow hidden).

## JobNavRail internals

`components/jobs/JobNavRail.svelte` — light strip `#f9fafb`, 28px,
2px `#9ca3af` top/bottom borders, `padding: 0 24px 0 76px` (aligns with
header title block), 11px caps 600 weight. Links at
`rgba(31,41,55,0.65)`, hover/active full, active = 2px dark underline,
empties `.empty` at 0.28 + `title="Nothing here yet"`. Sections wrapped in
`.rail-sections { flex:1; justify-content: space-evenly }`; "‹ Overview"
outside that wrapper with `margin-right: 48px`. Under this design: the
chevron goes away, Overview becomes item #1 with an active state, Emails +
History append, empties become real links (create-affordance pages), so
the `.empty` branch and the `sections` href-null logic go away.

## nav_targets retirement checklist

When rail links flip to job-scoped section routes, remove: the
`nav_targets` SerializerMethodField + `get_nav_targets` in
`apps/api/jobs/serializers.py`; `tests/test_api_job_nav_targets.py`; and
**re-pin the job-detail query count** in
`tests/test_api_jobs.py::test_job_detail_invoice_claims_single_query`
(currently pinned **18** = 13 base + fees prefetch + estimate-claim set +
3 nav_targets queries → drops back to 15; the pin's comment documents
this). Frontend: `JobNavRail.test.js` asserts the target-id hrefs — rewrite.

## Wizard facts for reconcile mode

- Backend: `BaseWizardService` (`apps/core/wizard.py`);
  `EstimateWizardService`/`InvoiceWizardService` subclass with config
  blocks — mirror that shape for the one parameterized frontend component.
- Wizard owns `…LineItemSource` rows; line-item writes go through
  `LineItemService.save_line_item` (adjustment recompute) — never raw save.
- Claim conflicts: 409 with `code: 'atoms_already_claimed'` + `atom_ids` —
  branch on `err.data?.code` per the error contract; render via
  `triageError` venues.
- Billability gates differ per atom type: Tasks must be `complete`,
  Materials `consumed`, Expenses immediate (deliberate; LATER.md records
  it) — the pool renders these states.
- LATER.md entries this delivers: "Merge the source-pull view into the
  detail page as an in-place toggle" (2026-06-02), "Make the Estimate and
  Invoice atom-pull UIs consistent" (2026-06-03), "wizard's by-hand line
  item uses an inline editor, not LineItemModal" (2026-06-03 — converge
  while in there).

## Per-job persisted state (the "browser thingie")

Pattern to follow: `stores/viewMode.js` (writable + localStorage,
key `minibini_view_mode`). Suggest one store module for job workspace
state keyed per job (e.g. `minibini_job_ws_<jobId>`) holding: per-section
selected document id, per-DOCUMENT wizard/reconcile mode (keyed by doc id,
NOT just section — leaving invoice #22 in reconcile must not open #23 in
reconcile), and band collapsed/expanded. Restore on mount, default latest
/ lines-mode / expanded(?). Decide retention (localStorage grows per job
forever — consider pruning or capping).

## Conventions that bite here

- **Svelte style scoping** (§5.5): shared chrome goes in `app.css`, never
  copied between components. The shell/panel split will tempt copies —
  promote instead. The three page categories (§5.5a pipeline): these pages
  are Category II (banner pages); JobDetail overview is Category I.
- **Per-tab routes convention** (Catalog pattern, LATER.md entry): tabs as
  routes — but RM explicitly chose persisted panel state over routes for
  document selection here. The section routes themselves ARE real routes.
  Don't route-ify the panel subnav without asking.
- **Existing name collision**: `components/HistoryPanel.svelte` already
  exists (contact/business/PO timeline). Name the job section panel
  something else (`JobHistorySection`?).
- Tables: `<tbody>` required; DELETEs return 200 JSON; TDD both stacks
  (backend `tests/`, frontend Vitest `frontend/tests/` — behavior vs
  display triage per `docs/designs/frontend-testing.md`).
- Never run vitest from repo root (creates a stray root `node_modules/`
  — happened twice this session); run from `frontend/`.
- `docs/designs/jobs-tasks-and-worksheets.md` §9 (and the rail paragraph
  added 2026-07-08, plus §9.1's JobHeader description) must be rewritten
  when this ships — they describe the pillar overview being killed.

## Open questions deliberately left

1. Overview bottom area design (step 4 — design when reached).
2. Rail docks into collapsible header vs stays its own strip (RM agnostic).
3. PO/Emails hairline divider polish (optional).
4. Actions menu at 2 items: keep menu vs direct buttons.
5. Band default state per page kind (collapsed on reconcile surfaces at
   minimum).
6. Notes as ninth rail item (LATER.md; not this pass).
7. Combos (future; read-mostly; estimate|invoice first — RM compares
   these daily via two browser windows today).
8. Whether TaskDetailPage's existing route survives inside TasksPanel
   subnav or becomes panel state like documents.
9. LATER.md "superseded estimate's tab" question (2026-06-03) — the
   estimate panel's subnav is where that gets answered.

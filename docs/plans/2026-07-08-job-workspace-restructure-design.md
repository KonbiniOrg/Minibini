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

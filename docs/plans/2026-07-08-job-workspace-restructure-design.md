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
3. **The nav rail stays always available** on every job page (it may also
   join the overview — decide when the overview is reworked).
4. **Wizards are an alternate view type of Estimate or Invoice** from the
   user's perspective — a *mode* of the document surface, not a separate
   destination. Restores the user to whatever mode they left the page in.
5. **No combo views yet.** The architecture leaves room for them (see
   taxonomy) but none ship in this pass.

## Architecture: section panels + a job shell

- **Section panels** — `EstimatePanel`, `TasksPanel`, `InvoicePanel`,
  `ShipmentsPanel`, `POPanel`: the working guts of today's route pages,
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
- **Document identity survives**: keep `/estimates/:id` etc. for
  superseded versions, history links, and search; job-scoped routes
  resolve to the latest and render the same panel in the same shell.
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

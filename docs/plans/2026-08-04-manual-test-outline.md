# Manual test outline — task-owned money (Phases 1–5)

Rough path checklist for RM's own browser pass. Not scripts — paths, one
line each, so nothing gets missed. Grouped by area; a final section
collects the accumulated judgment calls ("your call" items) surfaced
during implementation review.

## 0. Setup (do first, in order)

- [ ] Run `python manage.py migrate`
- [ ] Run `python manage.py validate_data` — confirm clean output
- [ ] Settings → Accounting Categories: create/designate the fallback
      category ("Uncategorized income" or similar; recommend taxable = yes)
- [ ] Settings → "Uncategorized lines" fieldset → pick that category as
      `fallback_accounting_category` → Save
- [ ] Settings → Accounting Categories table → find the fallback row (it
      stays visible/editable here even though excluded from normal
      pickers elsewhere) → set its **Fallback QBO Item** mapping
- [ ] Settings → Rate Schemes (preset manager) → "Default preset" picker →
      choose a task-applicable preset → Save
- [ ] Verify/set `default_material_markup_percent` in Configuration — this
      key used to be material-only; PO reconciliation's task-rate prompt
      now reuses it too (see §9 below), so confirm the value you have is
      still the one you want for that new purpose

## 1. Presets (RateScheme)

- [ ] Settings → Rate Schemes: create a new preset
- [ ] Edit a preset that's already referenced by existing stamped tasks —
      no 409/supersede prompt; existing tasks' prices don't move
- [ ] Retire a preset (Active toggle/Retire) — disappears from task-create
      dropdowns; already-stamped tasks unaffected
- [ ] Reactivate a retired preset
- [ ] Change the default preset, then clear it — task/Work forms
      preselect correctly (or start blank when cleared)
- [ ] Confirm percentage-type presets never show up in task-applicable
      dropdowns (only in adjustment-line pickers)

## 2. Stamped task creation & money permissions

- [ ] As a worker (no manage perms): create a task by picking a preset —
      money fields (rate, AC, modifiers, qty source) are read-only,
      stamped verbatim from the preset
- [ ] As a worker: confirm there's no way to type a custom rate / create a
      flat (typed-rate) task
- [ ] As the job's PM (not global `can_manage_jobs`) or as a
      `can_manage_jobs`/`can_manage_financials` user: create/edit a task's
      money block directly (rate, AC, modifiers, qty source) — succeeds
- [ ] Task detail: "Scheme" stat chip carries the rate/modifier tooltip
      now (relocated there) — check it reads fine
- [ ] Task detail shows a provenance chip for the stamping preset; editing
      that preset afterward does not re-price the task

## 3. Hand-line kinds (Work / Material / Fee-Credit) + crystallization

- [ ] Estimate footer "Add Line": Work / Material / Fee-Credit buttons
      (no bare checkbox, no default fallthrough)
- [ ] Add a Work hand-line: preset dropdown is optional (default
      preselected when configured); picking one stamps rate/units/AC into
      editable fields; typing over them works
- [ ] Add a Material hand-line (existing behavior; AC prefills from config
      default)
- [ ] Add a Fee/Credit hand-line: qty (default 1) × signed amount, AC
      required
- [ ] Accept the estimate: Work line → flat entered-qty Task (no
      `source_scheme`); Material line → provisional Material; Fee line →
      Fee
- [ ] Change Order: add/replace/remove each of the three kinds; CO line
      tables show kind badges same as estimate tables
- [ ] Job work area "Add Task" still uses the same preset-stamp form
      (three atom buttons unchanged)

## 4. Credits end-to-end

- [ ] Create a negative Fee (Credit) on a job — form echoes "this will
      appear as a credit"
- [ ] Zero-amount fee is rejected
- [ ] Credit flows onto an estimate/invoice line with a negative amount
- [ ] Invoice wizard source pool and composed line both show it negative
- [ ] Send/preview the invoice PDF — credit renders as **-$X.XX**
      correctly
- [ ] Job overview / CO totals with a negative amount render cleanly (no
      stray "+-$" prefix)
- [ ] Fee modal has no task field; signed-amount UI matches the above

## 5. Nullable AC / fallback flow

- [ ] Create a flat (non-hour) task with no AC — task form offers
      "— none (categorize at invoicing) —"
- [ ] Compose that task onto a draft invoice — line gets the fallback AC
      stamped, amber "Uncategorized → \<fallback name> · taxable/non-taxable"
      badge shown
- [ ] Correct the AC on one flagged line via the line edit modal — badge
      clears without a manual reload
- [ ] Leave a second flagged line as-is — Send Invoice is still enabled
      (no hard block)
- [ ] Delete a fallback-stamped line and re-add the same atom — badge
      regenerates (atoms keep their honest null; no silent inheritance)
- [ ] Add a targeted percentage adjustment alongside a fallback-flagged
      line — coexistence warning banner appears
- [ ] If QBO is connected: push and confirm no null-AC error; fallback
      AC's mapped Item resolves

## 6. Quantity structures (parent × per-unit subtasks)

- [ ] Job work area: Add Task ("Widgets, 10 ea") then Add Subtask — build
      an ad hoc structure (no template)
- [ ] Add a per-unit subtask (flag defaults true when parent's unit is
      `ea`) — inline derived expectation shown ("X/unit × N = Y expected")
- [ ] Add a per-batch subtask (flag false) — inline expectation is fixed
      regardless of parent qty
- [ ] Leave parent `est_qty` blank — derived-expectation line shows an
      explicit "parent quantity not set" state, never a silently computed
      ×1
- [ ] Parent task detail: non-startable (no Start Work/assign/blep);
      children table shows expected-vs-logged
- [ ] Try adding a subtask to an in_progress parent — rejected with a
      clear error
- [ ] Blep time against a child (parent has no blep affordance)
- [ ] Complete all children — parent completion is *offered*, not
      automatic, and prompts "quantity made?"
- [ ] Estimate/invoice wizard source pool shows ONLY the parent (children
      never appear), priced at the derived per-unit price
- [ ] Detach a subtask — works when the parent isn't claimed by a
      non-draft document; blocked with a clear error when it is
- [ ] Materials section on a parent task: try "Move" and note the known
      papercut — it still offers subtask radios as targets even though
      the server now rejects moving a material onto a subtask (400)

## 7. Deliverables bridge

- [ ] From a quantity-bearing parent task: "Add as Deliverable" — copies
      description/qty/units into a new Deliverable; button hides once
      linked
- [ ] From a Deliverable: "Create work structure" — mints a top-level
      task with the same three fields; hides once linked
- [ ] Diverge the task's est qty from the deliverable's `qty_ordered` —
      passive mismatch badge appears (est vs ordered, not actuals)

## 8. Template-N apply

- [ ] Note: no SPA UI exists yet to author/toggle `is_product_structure`
      on a WorkTemplate — set it first via a direct API call, e.g.
      `PATCH /api/work-templates/{id}/` with body
      `{"is_product_structure": true}` (requires `can_manage_config`)
- [ ] With such a template: job task list → Apply Template → a required
      positive Quantity field appears only for this template
- [ ] Apply it — one parent + one per-unit subtask per template item is
      created atomically
- [ ] Apply a normal (non-product-structure) template — unchanged flat
      generation, no quantity field

## 9. PO reconciliation (outsourced work)

- [ ] Create/edit a PO line with a task link — picker only offers
      top-level, job-bearing tasks; linking a subtask is rejected
- [ ] Issue and fully receive the PO — "Awaiting Reconciliation" badge on
      the PO list/detail; list filter checkbox works
- [ ] Reconcile: enter bill total, vendor invoice ref, a per-line final
      price on the linked line
- [ ] Append an invoice-only line (e.g. freight), optionally attributed to
      a task
- [ ] Re-reconcile and remove a previously appended invoice-only line —
      persisted-removal notice appears with a one-click re-add
- [ ] Variance displays correctly (bill total − ordered total, no
      proration); a multi-job PO reports variance per-PO
- [ ] After reconcile, with a clean final price on an un-invoiced linked
      task: the rate-prompt dialog appears (financials users only) —
      Accept updates the task's rate through the normal PATCH path
- [ ] Taste-check the suggested rate: it applies
      `default_material_markup_percent` (the materials markup config) to
      the final cost — confirm that's the right number to reuse for task
      rates too, or flag if it should be a separate setting
- [ ] Decline the prompt on a second qualifying line of the same PO —
      no-op, task rate unchanged
- [ ] Invoice wizard reflects the task's current rate live (not cached)
      after an accepted rate update
- [ ] Confirm no hard block: invoice a task whose PO is still
      unreceived/unreconciled — succeeds
- [ ] Job detail: per-PO ordered-vs-final variance rollup is **not**
      shown in the UI yet (API-only `linked_po_variances` on
      `GET /api/jobs/{id}/`) — check via the API if you want to see it now

## 10. RM-judgment items ("your call" — accumulated from phase reviews)

- [ ] Disabled-vs-hidden treatment for template-driven modifier checkboxes
      when applying a template to a task (Phase 1)
- [ ] Rate/modifier tooltip's new home on the task detail "Scheme" stat
      chip — does the relocation read okay?
- [ ] Work hand-line's preset dropdown being optional rather than forced
      — intended?
- [ ] The fallback/targeted-adjustment warning banner is not status-gated
      and still shows on already-sent invoices — intended, or should it
      hide post-send?
- [ ] Under-run billing on a per-batch subtask: complete a child with
      actual qty less than its estimate and check you're comfortable with
      the resulting parent unit price (this is the spec's own formula,
      not a bug)
- [ ] Reusing `default_material_markup_percent` for PO reconciliation's
      task-rate suggestion (see §9) — keep shared, or split into its own
      key?
- [ ] `linked_po_variances` job-costing data being API-only with no
      job-detail display yet — fine for now, or worth a UI slot?
- [ ] `is_product_structure` (and template authoring generally) being
      API-only with no WorkTemplate management UI at all — fine for now?
- [ ] A Change Order's mirrored/replacement task drops its
      `source_scheme` provenance chip (price still copies correctly,
      just loses the "stamped from X" label) — acceptable?
- [ ] Materials "Move" UI papercut on structured (parent) tasks (see §6)
      — acceptable to leave as a known issue for now?

# Wizard service consolidation

## Goal

`InvoiceWizardService` (`apps/invoicing/services.py`) and
`EstimateWizardService` (`apps/estimates/services.py`) are near-duplicates
— ~14 parallel methods that differ only in model types and a few rules.
The bundle-summary fix had to be written twice. Extract the shared logic
into one `BaseWizardService` so future changes land in a single place.

This is a **pure refactor** — no behavior change. The existing wizard
test suites (135 tests across `test_invoice_wizard_*` /
`test_estimate_wizard_*` / `test_wizard_bundle_summary`) are the safety
net; they must stay green throughout.

## Scope

**Lifted into `BaseWizardService`** (shared, identical logic bar model
types / a few hooks):

- `_resolve_atom`, `_atom_source_type`, `_atom_category`,
  `_atom_description`, `_atom_units`, `_atom_qty_and_price`,
  `_atom_computed_amount`
- `_sum_sources`, `_expected_per_unit`, `_is_in_sync`,
  `_uniform_scheme_bundle`, `_resync_in_sync_line_item`
- `add_atoms_to_new_line_item`, `add_atoms_to_line_item`,
  `remove_atoms_from_line_item`

**Stays per-service** (genuinely divergent — out of scope):

- `get_source_pool` — the two return *different shapes* (invoice: a
  task-grouped tree `{'tasks': [...]}`; estimate: a flat
  `{'atoms': [...]}`) with different SPA consumers. Unifying it would
  change a frontend contract — not worth it here.
- `open_for_job` / `open_for_worksheet` — container creation.
- `send_all_atoms_to_estimate` (estimate-only),
  `BILLABLE_JOB_STATUSES` (invoice-only).

## Design

New module `apps/core/wizard.py` holding `BaseWizardService`. It imports
no concrete models — everything model-specific comes from subclass
configuration. The two concrete services subclass it and shrink to a
config block plus their per-service methods.

**Subclass config (class attributes):**

- `line_item_model` — `InvoiceLineItem` / `EstimateLineItem`
- `source_model` — `InvoiceLineItemSource` / `EstimateLineItemSource`
- `container_attr` — the line item's parent FK name: `'invoice'` /
  `'estimate'`
- `line_item_fk` — the source model's FK name to the line item:
  `'invoice_line_item'` / `'estimate_line_item'`
- `claim_conflict_exc` — `ClaimConflict` / `EstimateClaimConflict`
- `atom_models` — maps `atom_ref['type']` → model class, e.g.
  `{'task': Task, 'material': Material}` /
  `{'plan_task': PlanTask, 'plan_material': PlanMaterial}`. Drives
  `_resolve_atom` and `_atom_source_type`.
- `task_model` / `material_model` — for the `isinstance` checks in
  `_atom_units`, `_atom_qty_and_price`, `_uniform_scheme_bundle`.

**Subclass hooks (overridable methods) — the genuine behavior
divergences:**

- `_task_qty_and_price(task, total)` — single-atom task copy-over:
  invoice → `(1, total)`; estimate → `(est_qty, effective_rate())`.
- `_task_actual_qty(task)` — the quantity summed in
  `_uniform_scheme_bundle`: invoice → `scheme.get_actual_qty(task)`;
  estimate → `task.est_qty`.

**One divergence to unify deliberately:** invoice's `_sum_sources` sums
per-atom *quantized* amounts (`_atom_computed_amount`); estimate's sums
raw `compute_amount()`. The base will quantize per-atom uniformly (the
invoice behavior — it matches what `_uniform_scheme_bundle`'s total
implies). Verify the estimate wizard tests still pass; a stray cent in a
sum is the thing to watch.

## Steps

1. Create `apps/core/wizard.py` with `BaseWizardService` — the 14 shared
   methods, written against the config attributes + 2 hooks above.
2. `InvoiceWizardService` → `class InvoiceWizardService(BaseWizardService)`:
   set the config block, implement the 2 hooks, keep `open_for_job`,
   `get_source_pool`, `BILLABLE_JOB_STATUSES`. Delete the now-inherited
   methods.
3. `EstimateWizardService` → same: config + hooks, keep
   `open_for_worksheet`, `get_source_pool`, `send_all_atoms_to_estimate`,
   `_validate_draft_worksheet`. Delete the inherited methods.
4. Run `test_invoice_wizard_*`, `test_estimate_wizard_*`,
   `test_wizard_bundle_summary`, then the full suite — all green.

## Tests

Pure refactor — no new behavior, so no new behavior tests. The existing
135 wizard tests are the safety net and must stay green. If any shared
method ends up thinly covered after the move, add a direct
`BaseWizardService` unit test (via one concrete subclass) to close the
gap.

## Docs

`architecture-and-conventions.md` (service-layer section) and the wizard
sections of `estimates-and-prices.md` / `invoicing-and-expenses.md` —
note that the shared wizard logic lives in `BaseWizardService` and the
two concrete services are thin subclasses.

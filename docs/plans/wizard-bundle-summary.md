# Wizard — summarize same-scheme task bundles

## Problem

When a wizard user bundles 2+ atoms into one line item, the multi-atom
branch hardcodes `units='none'`, `qty=1`, `price=total`. That loses the
real units/quantity. Desired: when the bundled atoms are all tasks sharing
a rate scheme, summarize them properly.

Affects both wizards — the same `add_atoms_to_new_line_item` method:
- Invoice wizard: `apps/invoicing/services.py:542` (Task/Material atoms).
- Estimate wizard: `apps/estimates/services.py:725` (PlanTask/PlanMaterial).

## Decisions

A bundle qualifies for the summarized treatment only when **every atom is
a Task/PlanTask, all share one RateScheme, and all carry identical
`active_modifiers`** (compared as a set — order-insensitive).

When it qualifies:
- `units` = `scheme.unit_label`
- `qty`   = sum of actuals — invoice: `scheme.get_actual_qty(task)` per
  task; estimate: each PlanTask's `est_qty`
- `price` = the common effective rate, `scheme.effective_rate(modifiers)`
  (equals the base rate when modifiers are empty), quantized to cents

Any other bundle — contains a Material/PlanMaterial, mixes schemes, mixes
modifiers, or isn't all-tasks — falls back to the current behavior
(`units='none'`, `qty=1`, `price=total`). Single-atom creation is
unchanged. `description` stays blank for multi-atom (unchanged).

**Rounding note:** `price × qty` (effective_rate × Σactuals) may differ by
a sub-cent from the sum of per-atom quantized amounts for elapsed-time
bundles. The line could occasionally read as "overridden" by a cent. This
is accepted — the effective rate is the exact per-unit price.

## Changes

In each wizard service, add a helper `_uniform_scheme_bundle(instances)`
returning `(units, qty, price)` when the bundle qualifies, else `None`.
The multi-atom branch of `add_atoms_to_new_line_item` calls it and uses
the result, or falls back.

`add_atoms_to_line_item` and `remove_atoms_from_line_item` must keep a
summarized bundle consistent: when the line item is in sync, after the
source-set change re-derive units/qty/price — if the new source set is a
uniform same-scheme task bundle, summarize it; otherwise keep qty and
recompute the per-unit price (existing behavior). Overridden line items
are still left untouched. A shared `_resync_in_sync_line_item(line_item)`
helper does this.

- `apps/invoicing/services.py` — `InvoiceWizardService` (Task atoms).
- `apps/estimates/services.py` — `EstimateWizardService` (PlanTask atoms).

## Tests (TDD)

For each wizard:
- Bundle of 2 same-scheme tasks, no modifiers → units = scheme unit_label,
  qty = summed actuals, price = base rate.
- Bundle of 2 same-scheme tasks, identical non-empty modifiers → price =
  effective (modified) rate.
- Bundle of 2 tasks with different schemes → fall back.
- Bundle of 2 same-scheme tasks with different modifiers → fall back.
- Bundle including a material atom → fall back.
- Single atom → unchanged.

## Docs

`estimates-and-prices.md` covers the wizard / billable atoms — note the
summarized bundling behavior there if it describes line-item creation.

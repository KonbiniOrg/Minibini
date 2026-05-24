# Per-item priced flat fees with quantity — design

**Date:** 2026-05-17
**Status:** Approved design, pending implementation plan

## Problem

`RateScheme` flat-fee billing has two limitations:

1. **Per-item price proliferation.** Every distinct flat fee (setup $100, coating-plywood
   $30, tapping-hole $1.00) needs its own `RateScheme`, because the price lives in
   `RateScheme.rate`. Configuring a saleable item's price should belong to a
   `TaskTemplate`, but `TaskTemplate` has no price field.
2. **Quantity ignored.** `RateScheme.get_actual_qty()` hardcodes `Decimal('1')` for
   `FLAT_FEE`. That works for a one-off setup fee, but not for hole-tapping where the
   count varies. `est_qty` exists on `Task`/`PlanTask` and `default_billable_qty` on
   `TaskTemplate`, but neither feeds the flat-fee charge.

## Core idea

`flat_fee` stops meaning "fixed charge, qty 1" and becomes **"fixed unit price ×
estimated quantity."**

- The unit price is **not** stored on the `RateScheme`. It rides on the atom
  (`TaskTemplate` → `PlanTask` → `Task`), stored in the existing
  `active_modifiers` / `default_active_modifiers` JSON field.
- One shared "Flat Fee" `RateScheme` serves every flat-fee item. Creating a new
  flat-fee saleable item is just a new `TaskTemplate` with its own price — no new
  `RateScheme`, so `RateScheme.FROZEN_FIELDS` / supersession never enters the picture.
- Quantity comes from `est_qty` (set on the worksheet, carried to the `Task`,
  editable on the `Task` by editing — not a worker-completion prompt like
  `entered_qty`'s `actual_qty`).

## Data shape

The `(default_)active_modifiers` field carries a different shape per algorithm:

- **Time/qty schemes** (unchanged): a list of modifier keys — `["rush", "weekend"]`
- **flat_fee**: a dict with the price — `{"flat_fee_price": "30.00"}`

The field's `default=list` is unchanged; an unpriced flat-fee atom is `[]` or `{}`.
The price is stored as a string to preserve decimal precision through JSON.

This is a deliberate overload of one column. A `flat_fee` atom does not take
percentage modifiers — if the price differs, it is simply a different number.

## Model layer — `apps/jobs/models.py`

- **`RateScheme.effective_rate(active_modifiers)`** — branch on `algorithm`.
  - `flat_fee`: read `flat_fee_price` out of `active_modifiers`; **fall back to
    `self.rate`** when absent.
  - other algorithms: existing additive-percentage logic, untouched.
- **`RateScheme.compute_charge(qty, active_modifiers)`** — unchanged
  (`qty × effective_rate`); now correct for flat_fee.
- **`RateScheme.get_actual_qty(task)`** — the `flat_fee` branch returns
  `task.est_qty` (fallback `Decimal('1')` when null) instead of hardcoded `1`.
- **`PlanTask.compute_amount`** — already `compute_charge(self.est_qty,
  self.active_modifiers)`; works once `effective_rate` is fixed.
- A small helper reads the price out of the JSON, e.g.
  `_flat_fee_price(active_modifiers)`.

**Backward compatible:** existing flat-fee schemes/tasks with empty
`active_modifiers` fall back to `scheme.rate × 1` — exactly today's behavior. No
data migration of old schemes required.

## TaskTemplate — `apps/estimates/models.py`

- `default_active_modifiers` holds `{"flat_fee_price": ...}` for flat-fee templates;
  `default_billable_qty` already supplies the quantity.
- Add `TaskTemplate.clean()`: a flat-fee template must carry a positive
  `flat_fee_price`; non-flat templates keep the list-of-keys form.
- `generate_task` already copies `default_active_modifiers → active_modifiers` and
  `est_qty` — price and quantity carry to `Task`/`PlanTask` with no change.
- Carry-over (`PlanTask → Task`) already copies `active_modifiers` and `est_qty`.

## Task / PlanTask validation

- flat-fee `TaskTemplate`: positive `flat_fee_price` required.
- flat-fee `Task`/`PlanTask`: price optional at the model level (falls back to
  scheme rate for back-compat), but the UI always supplies one.

## API — `apps/api/`

Serializers already pass `(default_)active_modifiers` through as raw JSON and expose
`effective_rate` / `computed_charge` via method fields. The flat price flows through
automatically — no structural change.

## Frontend

- **`TaskTemplateManager.svelte`** & **`WorkItemForm.svelte`**: when the selected
  scheme's `algorithm === 'flat_fee'`, render a single price
  `<input type="number" step="0.01">` (writing `{flat_fee_price: ...}`) instead of
  the modifier checkbox list.
- **`RateSchemeManager.svelte`** (RateScheme CRUD): for a `flat_fee` scheme, hide the
  `modifiers` catalog editor (it is inert for flat-fee) and relabel `rate` as a
  default/fallback price. Time/qty schemes are unchanged.
- `TaskTree` and the Task/PlanTask detail pages: show flat fees as `price × qty`.

## Data setup

The shared "Flat Fee" `RateScheme` will be created by the user (or added to fixture
files). Its `rate` becomes a default/fallback only. Existing per-item flat-fee
schemes keep working as-is; consolidating them onto the shared scheme is optional
and out of scope.

## Testing (TDD)

Write failing tests first:

- `effective_rate` for `flat_fee` with a price, and the fallback to `scheme.rate`.
- `compute_amount` / `compute_charge` honoring `est_qty` (qty > 1).
- `TaskTemplate.generate_task` carrying the price into `Task`/`PlanTask`.
- `PlanTask → Task` carry-over preserving price and quantity.
- `TaskTemplate.clean()` rejecting a flat-fee template with no/zero price.

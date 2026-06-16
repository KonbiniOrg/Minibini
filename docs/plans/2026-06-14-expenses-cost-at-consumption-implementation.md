# Expenses — inventoried cost-at-consumption — implementation plan

> Implements the decisions in `2026-06-14-expenses-cost-model-redesign.md` §11.
> TDD; commit per phase. **Never write to the dev DB** (`makemigrations` OK,
> `migrate` not; tests use a separate DB; one test process at a time).

**Goal:** Single-amount expenses, no joining existing materials, cost recognized
by mode — **cost expense** (amount at purchase, creates a consumable material) vs
**stock receipt** (inventoried PLI → QOH ↑, amount *not* job-costed, cost at
consumption). Remove the recost/clobber machinery. Leave a functional app.

Scope note: **many-materials-per-expense (the FK flip) is NOT in this increment** —
it's a separate later step. This increment keeps a single optional consumable per
expense and adds the stock-receipt mode.

## Model (target)

`Expense` (single amount) is one of two modes:
- **Cost:** `material` (≤1 consumable it created) or none. `amount` is job cost.
- **Stock receipt:** `stock_pli` (FK PriceListItem, inventoried) + `stock_qty`.
  QOH ↑ by `stock_qty`; `amount` is **not** in `_spent`; cost flows at consumption.
- Validation: not both modes; `stock_pli` must be `is_inventoried`.

---

### Phase 1 — Model: stock-receipt fields

**Files:** `apps/expenses/models.py`; migration; `tests/test_expense_model.py`.

- [ ] Tests: an Expense with `stock_pli`+`stock_qty` validates; setting both a
  `material` and `stock_pli` raises; `stock_pli` not inventoried raises;
  `stock_qty` required/positive when `stock_pli` set.
- [ ] Implement: add `stock_pli = FK('inventory.PriceListItem', SET_NULL, null,
  blank, related_name='+')` and `stock_qty = DecimalField(null, blank)`. In
  `clean()`: if `stock_pli` set → require `stock_qty > 0`, require
  `stock_pli.is_inventoried`, forbid `material`. `makemigrations expenses`.
- [ ] Run model tests.
- [ ] Commit.

### Phase 2 — Service: modes, remove recost/clobber/link

**Files:** `apps/expenses/services.py`, `apps/inventory/services.py` (a receipt
helper if needed); `tests/test_expense_service.py`.

- [ ] Tests:
  - `submit(stock_pli=…, stock_qty=3)` bumps the PLI `qty_on_hand` by 3, creates
    no material, no recost.
  - `submit(new_material={inventoried PLI})` is rerouted to a stock receipt (no
    consumable material created; `stock_pli`/`stock_qty` set).
  - `submit(new_material={freeform})` creates a consumable material with the
    user's `unit_cost` (no division, no recost).
  - linking an existing material is no longer accepted (param dropped/ignored).
  - editing a stock-receipt expense's `stock_qty` adjusts QOH by the delta.
- [ ] Implement:
  - Delete `_recost_material_from_expenses`, `_recost_after_unlink`,
    `_assert_no_cost_clobber`, and the link-existing path. Drop the `material=`
    *existing-link* acceptance (creating via `new_material` stays).
  - `submit`/`update`: if the chosen PLI `is_inventoried` → **stock receipt**: set
    `stock_pli`/`stock_qty`, bump QOH (reuse/extend `InventoryService` receipt;
    **no** consumable material, **no** earmark). Else (freeform / non-inventoried
    PLI) → create one consumable material with the user-entered `quantity` /
    `unit_cost` (cost-at-purchase; no recost).
  - On edit of `stock_qty`, apply the QOH delta; on delete, reverse the QOH bump.
  - Keep invoiced-freeze + reimbursed-money-lock guards.
- [ ] Run service tests + `tests.test_expense_material_inventory`.
- [ ] Commit.

### Phase 3 — Job cost rollup excludes stock receipts

**Files:** `apps/jobs/financials.py`; `tests/test_job_financials.py`.

- [ ] Tests: a stock-receipt expense (`stock_pli` set) is **excluded** from
  `_spent`; the inventoried material's cost is counted at **consumption**
  (existing `consumed_no_expense` term); the plywood top-up (planned 10-sheet
  material consumed + a 3-sheet stock-receipt expense) counts **once** (10×cost).
- [ ] Implement: in `_spent`, `expenses_total = …filter(job=job).exclude(
  status=REJECTED).exclude(stock_pli__isnull=False).sum('amount')`. Update the
  docstring (stock receipts are inventory, costed at consumption).
- [ ] Run + `tests.test_board_service`.
- [ ] Commit.

### Phase 4 — Serializer / API

**Files:** `apps/api/expenses/serializers.py`, `views.py`; `tests/test_api_expenses.py`.

- [ ] Tests: POST with `stock_pli`+`stock_qty` → 201, QOH bumped, no material;
  POST inventoried `new_material` → stock receipt; `?…` list shows the stock
  fields; linking an existing material id is rejected/ignored.
- [ ] Implement: expose `stock_pli`/`stock_qty` (writable); surface in the
  serializer; drop the existing-material write path. `select_related('stock_pli')`.
- [ ] Run API tests.
- [ ] Commit.

### Phase 5 — Frontend: stock-purchase vs cost, drop existing-material picker

**Files:** `frontend/src/components/expenses/ExpenseForm.svelte`,
`MaterialPicker.svelte`; tests.

- [ ] Tests: choosing an **inventoried** PLI shows a "stock purchase" (quantity)
  control and submits `stock_pli`/`stock_qty` (no material); a freeform/non-inv
  item submits `new_material`; the **existing-material list is gone**.
- [ ] Implement: rework the material sub-control — pick a PLI or freeform;
  inventoried PLI → quantity-only stock purchase; else → freeform consumable
  (desc/qty/unit_cost). Remove the existing-materials list entirely. Keep job
  anchor + overhead.
- [ ] Run frontend tests.
- [ ] Commit.

### Phase 6 — Shortfall-block UX (reduce-and-split suggestion)

**Files:** the consume error surfacing (task-start / `MaterialService.consume`
message and the SPA error display); tests.

- [ ] When `consume()` fails for short stock, the surfaced message suggests the
  trust-the-user workaround: *"Only N on hand. Reduce this material to N to start
  now, and add a second task/material for the remainder while it's procured."*
- [ ] Implement (backend message and/or SPA presentation of the start-work
  error). Test the message text.
- [ ] Commit.

### Phase 7 — Docs

- [ ] Update `docs/designs/invoicing-and-expenses.md` (Expense modes; stock
  receipt; cost-at-consumption; no link-existing; recost removed),
  `materials-inventory-and-purchasing.md` (inventoried expense = receipt; cost at
  consumption), and the as-built redesign doc's superseded notes.
- [ ] Commit.

## Migration / data notes
- Existing expenses keep `material` (the as-built single link). Any inventoried
  `material` previously created by an expense stays a consumable for now (no
  retro-conversion to stock receipt); the new mode applies going forward. Note
  this in the migration so we don't silently double-count legacy rows — a
  follow-up data audit may be warranted.
- The earlier defensive recost fix (`f57b5bc`) is superseded by Phase 2.

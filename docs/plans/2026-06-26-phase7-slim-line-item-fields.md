# Phase 7 — Slim the frozen line-item models

> REQUIRED SUB-SKILL when executing: superpowers:subagent-driven-development.
> Design draft §5.5 + §14 step 6. Backend (migrations). **Do Phase 6 first** — these
> fields must have no readers before removal.

**Goal:** Make `EstimateLineItem` / `InvoiceLineItem` pure frozen rows. Remove
`source_template` from `EstimateLineItem`, and remove the **authoring/carry-over use
of `inventory_item`** on estimate/invoice lines. Keep: description, qty, units,
price, accounting_category, tax overrides, line_number, the `…LineItemSource` claim,
and (for now) the adjustment fields.

**Depends on:** Phase 6 (removed the authoring + Phase B that read these). **Note
the shared-base + Change-Order complication below — this needs a decision.**

## The complication (read before planning tasks)
`inventory_item` lives on **`BaseLineItem`** (`apps/core/models.py:333`), shared by
`EstimateLineItem`, `InvoiceLineItem`, **and `ChangeOrderLineItem`**. CO `add` lines
still legitimately author from a PLI (CO is direct-authored — design §6.2), and
`BaseLineItem._populate_from_pli()` / `save()` use `inventory_item`; `InventoryItem.merge()`
and `can_be_deleted()` also reference it across line types. So you **cannot** simply
drop `inventory_item` from `BaseLineItem`. `source_template`, by contrast, is a field
on `EstimateLineItem` only (CO has its *own* `source_template`), so it's a clean
removal.

## Global constraints
- Migrations involved → run the suite at least once **WITHOUT `--keepdb`** (fresh
  build) — `feedback_fresh_db_after_migrations`. Hand-write nothing unusual;
  `makemigrations` for field drops is fine. Never edit historical migrations. Never
  write the dev DB; one test process.

## Reference (from exploration)
- `EstimateLineItem.source_template` (FK TaskTemplate, `apps/estimates/models.py`
  ~L562). Readers after Phase 6: `revise_estimate` copies it (`services.py:153`);
  the dedicated `tests/test_estimate_line_item_source_template.py`; nealsdata
  `build.py` sets it `None` (~L922/1144/1182). CO's own `source_template`
  (`models.py` ~L656) + `ChangeOrderLineItemSerializer` (keep).
- `BaseLineItem.inventory_item` (`apps/core/models.py:333`); `_populate_from_pli()`
  (~L378) + `save()` (~L392) use it; `InventoryItem.merge()` (`inventory/services.py`
  ~L174) + `can_be_deleted()` (`inventory/models.py` ~L95) reference est/invoice LIs;
  serializers expose `inventory_item` (`apps/api/estimates/serializers.py:36`,
  `apps/api/invoicing/serializers.py:49`); `revise_estimate` copies it
  (`services.py:152`).
- Migrations that created these: `estimates/0011` (source_template),
  `estimates/0025` + `invoicing/0014` (price_list_item→inventory_item rename).

## Tasks (TDD)

### Task 1 — Remove `EstimateLineItem.source_template`
Drop the field + its serializer/`revise_estimate` references + the dedicated test;
`makemigrations estimates` (AlterField/RemoveField). Confirm CO's own
`source_template` is untouched. Fresh-build test run.

### Task 2 — Decide & apply the `inventory_item` slim (see Decision)
Per the chosen option (below): either (A) leave `inventory_item` on `BaseLineItem`
but stop exposing/populating it on the **estimate/invoice** serializers and drop the
`revise_estimate` copy and the est/invoice arms of `merge()`/`can_be_deleted()`
(no migration; field stays for CO); or (B) move `inventory_item` off `BaseLineItem`
onto `ChangeOrderLineItem` only and remove it from estimate/invoice (migrations +
adjust `_populate_from_pli`/`save` to be CO-scoped). Update tests accordingly.

### Task 3 — Sweep + gate
Grep the whole repo (apps/frontend/tests/nealsdata/fixtures) for remaining
`…LineItem.source_template` / est-or-invoice `.inventory_item` readers (the
exploration listed them). Full backend (fresh build) + frontend suites green.

## Out of scope
- Adjustment fields (`adjustment_service` / `adjustment_target_categories`) — they
  change in Phase 8 (job-scoped), not here.
- ChangeOrderLineItem provenance fields (kept — CO is direct-authored).
- nealsdata regeneration (Phase 9 picks up the field removals).

## Decisions to confirm
- **`inventory_item` — Option A (leave field, stop using on est/invoice) vs Option B
  (relocate to CO only).** Lean: **A** for the first pass (smaller, no risky base
  migration; the field just sits unused on est/invoice and the serializers stop
  exposing it), with B as a later cleanup. The design only requires dropping the
  *use*, which A satisfies.
- Confirm Phase 6 shipped first (no remaining authoring/carry-over readers).

# Inventory — UI flow

**Purpose:** A from-the-user's-perspective walkthrough of the inventory feature
(the 2026-06 catalog-vs-lots reframe). It guides manual/user testing today and
seeds the automated UI test platform later — each checklist item maps to an
assertion. Keep it current as the inventory UI evolves.

**Model (catalog-vs-lots reframe):** one `InventoryItem` table holds every
physical thing. A **catalog item** (`is_catalog=True`) is a reorderable *type*
(survives at zero stock, allocation uncapped). A **transient lot**
(`is_catalog=False`) is a one-time batch minted behind a freeform goods-Material;
when it's **finished** (on-hand 0 AND no earmarks) it's **hidden**, not deleted.
Quantity tracking is **universal** — every item-backed material earmarks/consumes.
See `docs/plans/2026-06-14-inventory-catalog-vs-lots-spec.md` and
`docs/designs/materials-inventory-and-purchasing.md` §2.

## Personas

- **Worker** — no atoms. Can browse inventory (read), but no manage actions.
- **Financials** — `can_manage_financials`. Full inventory CRUD + write-off + merge.
- **Config** — `can_manage_config`. Same full inventory access (either atom works).

## Prerequisites (test-data setup)

Several flows are silent no-ops without the right data — set these up first:

- [ ] **At least two catalog items** with the same `units` (e.g. two "felt"
  rows in `sheet`) — needed to exercise **merge** (units must match) and the
  duplicate-consolidation story.
- [ ] **A transient lot** (`is_catalog=False`) with stock — easiest to make by
  recording a **freeform cost-item expense** on a job (see `Expenses.md` §3), or
  by creating an item and unchecking *Catalog*. Needed for **write-off**, the
  **finished-lot** hide behavior, and merge (the discard must be a lot).
- [ ] **An item earmarked by a job** — add a Material that draws a catalog item
  on an approved/in-progress job (so `qty_earmarked > 0`) — needed for the
  **allocation warning** (§7) and the available-vs-on-hand columns.
- [ ] **An AccountingCategory** — required to create any item.
- [ ] **Two users** — a plain worker and a financials/config user — for the
  persona-gated steps.

---

## 1. Browsing the list

The list lives at **`#/inventory`** (sidebar **Inventory**, shown to financials
*or* config users; hidden from workers).

- [ ] **Columns:** Code, Description, Units, **On hand / Earmarked / Available**,
  **Kind** (`catalog` / `lot`, plus `· inactive`), Cost, Sell.
- [ ] **Available = On hand − Earmarked** for each row.
- [ ] **Search** (code or description) filters the loaded list client-side.
- [ ] **Active only** (default on) hides deactivated items; unchecking shows them.
- [ ] **Worker view:** a worker reaching `#/inventory` sees the table but **no**
  New / edit / write-off / merge controls (and no Inventory sidebar link).

## 2. Hide-on-spend (finished lots)

- [ ] **A finished lot is hidden by default.** A lot at on-hand 0 with no
  earmarks does **not** appear in the default list.
- [ ] **Show finished lots** toggle (`?include_finished=true`) reveals them
  (greyed/italic) so they can be merged or written off.
- [ ] **Catalog items survive at zero.** A catalog item at on-hand 0 **stays**
  visible (the catalog flag exempts it) — contrast with the hidden lot.
- [ ] **A lot with a live earmark stays visible** even at on-hand 0 (the earmark
  clause) — it's a demand waiting to be sourced, not a finished lot.

## 3. Create / edit + catalog checkbox

- [ ] **+ New item:** code, description, units, purchase price, **selling price
  (blank ⇒ markup applied)**, **Catalog item** checkbox (default on), accounting
  category. Save → appears in the list.
- [ ] **Markup default:** create an item with a purchase price and **no** selling
  price → its sell is `cost × (1 + default_material_markup_percent/100)` (config
  default 0 ⇒ sell == cost). Editing later never re-applies markup.
- [ ] **Edit:** the edit button (per row) opens the form seeded with the item;
  changing rows re-seeds it.
- [ ] **Promote a lot → catalog:** edit a lot, **check** Catalog, save → it now
  survives at zero / is offered uncapped.
- [ ] **Demote a catalog → lot:** uncheck Catalog → it becomes a lot (and, if
  on-hand 0 with no earmarks, drops out of the default list as a finished lot).
- [ ] **Deactivate:** uncheck Active (edit) → it leaves the active list; re-find
  it by unchecking *Active only*.

## 4. Write-off

- [ ] The **write off** button appears per row **only when on-hand > 0**.
- [ ] Clicking it **confirms** (irreversible), then zeroes on-hand and books the
  remainder to wasted. A lot then becomes a finished/hidden lot; a catalog item
  stays (emptied).
- [ ] The wastage is recorded in the item's history (§6) — the entry is written
  before the row is hidden, so it's never lost.

## 5. Merge (manual consolidation)

- [ ] **Merge items** opens the panel: pick a **Keep** (any item) and a
  **Discard** (lots only — catalog items aren't offered as discards).
- [ ] On merge: the discard's **on-hand and references fold into keep**, and the
  discard **disappears** from the list. Keep's on-hand rises by the discard's.
- [ ] **No data is orphaned:** any PO/estimate/invoice/bill line or template
  association that referenced the discard now references keep (the document's own
  text/price is unchanged — only the inventory link moves).
- [ ] **Unit mismatch is blocked:** try to merge two items with different units →
  error, no change.
- [ ] **Catalog-as-discard is blocked:** (the picker already excludes them; if
  forced, the server returns an error) — demote to a lot first.

## 6. History / review

- [ ] Every quantity event (receipt, consume, write-off, merge, PO receive/
  reverse, ad-hoc receive) records an **InventoryHistory** action entry with the
  quantity change, resulting on-hand, reason, and a code/description snapshot.
- [ ] **Survives deletion:** after a lot is merged away or a finished lot is
  gone, its history entries remain legible (the snapshot keeps the code/desc).
- [ ] *(Surfacing this trail in the UI — a per-item history panel — is a later
  refinement; today it's queryable via the InventoryHistory partition.)*

## 7. Earmark warning at allocation

In the **Add Material** modal (task list → Add Material; pick a catalog/lot item):

- [ ] **Earmarked elsewhere:** picking an item with `qty_earmarked > 0` shows
  "N on hand, M earmarked for other jobs (A available)".
- [ ] **Exceeds available:** entering a quantity greater than available shows
  "Only A of N available — M already earmarked for other jobs. You can still
  commit it (it will show a shortfall until restocked)." — i.e. trust-the-user,
  not a hard block at allocation (the hard block is at consume/task-start).
- [ ] **No warning** when the item is fully available (earmarked 0 and request ≤
  available).

## 8. Permissions

- [ ] **Either atom:** a `can_manage_financials` user and a `can_manage_config`
  user both get full inventory CRUD + write-off + merge.
- [ ] **Neither atom:** a plain worker gets read-only (no controls, no nav link),
  and write/write-off/merge endpoints return 403.

---

## Coverage matrix

| Dimension | Cases |
|---|---|
| Browse | columns (on-hand/earmarked/available) · search · active-only · worker read-only |
| Hide-on-spend | finished lot hidden · include-finished reveals · catalog survives at 0 · earmarked lot stays |
| CRUD | create (markup default) · edit/re-seed · promote · demote · deactivate |
| Write-off | shown only with stock · confirm · waste booked · history entry |
| Merge | keep/discard pick · fold + delete · refs repointed · unit-mismatch blocked · catalog-discard blocked |
| History | every QOH event logged · survives deletion |
| Allocation | earmarked breakdown · exceeds-available warning · no warning when free |
| Permissions | financials OR config full access · worker read-only / 403 |

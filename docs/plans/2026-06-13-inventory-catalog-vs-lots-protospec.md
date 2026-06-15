# Inventory reframe: catalog items vs. transient lots — proto-spec (future)

**Status:** Proto-spec / future direction. Captured 2026-06-13 during the
Expenses↔Job brainstorm. **Not** part of the expenses feature — sequenced as its
own spec to follow it. The expenses work builds on today's inventory model and
stays forward-compatible with this.

## The core idea

Today **PriceListItem is the universe** and `is_inventoried` is an opt-in flag
*within* it: only flagged catalog items get quantity tracking (QOH, earmarks,
restock, consumption). Everything else (non-inventoried PLIs, freeform Materials)
carries no on-hand tracking, so leftover physical stock is invisible — "lost
information that could be turned into money."

**Flip it.** Make **quantity tracking the universe**: every purchased physical
thing is tracked *while it is physically in the shop*. Then a flag (provisionally
**`pli`**, "is a catalog item") opts an item into *catalog* behavior, rather than
opting it into *tracking*.

Reframed: **a "Price List Item" is just an inventory item with the catalog flag
set.** The thing we call a PLI today is one kind of inventory item; transient
purchased lots are another.

### Table reuse / rename

Reuse the **current `PriceListItem` table** as the inventory-item table — it
already carries `code`, `units`, `qty_on_hand`, `qty_sold`, `qty_wasted`,
`purchase_price`, `selling_price`, `accounting_category`, `is_active`. **Rename
it** (e.g. `InventoryItem`) and replace `is_inventoried` with the catalog flag.
A PLI becomes "an inventory item with the catalog flag." (DB table is currently
`price_list`; `db_table` and all references across estimates/invoicing/
purchasing/inventory line items would need updating — see the field-rename rule
in CLAUDE.md.)

## What the catalog flag governs

Two distinct behaviors hang off `pli` / catalog:

1. **Lifecycle / persistence.**
   - **Catalog item:** survives at `qty_on_hand = 0`. It's a template you'll
     re-buy; never auto-deleted.
   - **Transient lot:** ephemeral. When qty hits 0 it can be deleted/disappear
     (it was one specific batch).

2. **Allocation semantics ("can we get more?").**
   - **Catalog item:** effectively infinite — do **not** cap allocation at QOH,
     and possibly **hide** QOH in the picker ("we can always get more").
   - **Transient lot:** finite — allocation is **capped at the actual QOH**; you
     can't assign more felt than the sheets you physically have.

Mental model: a catalog item is a **type you reorder**; a transient lot is a
**specific batch you bought once**. Their QOH semantics genuinely differ, and
that difference is the whole point.

## Scope clarifications from the discussion

- **Whole units, not fractions.** Track "bought 20, used 18, 2 left" and
  "assigned 20, used 18, 2 back into stock" (the existing `restocked_qty` /
  restock button already does this for inventoried PLIs — this generalizes it).
  **Do NOT** track fractional remnants (0.25 of a sheet). Real-world meaningful
  distinction; software-wise identical effort, but the product decision is
  whole-unit only. (Relates to the existing units-divisibility idea.)
- **Earmarking does not apply here.** Earmarks reserve *shared global stock*
  against competing jobs. A transient lot bought for one job and used on that job
  by mental habit.)
- **Restock-before-consume ordering** is an existing sharp edge (restock must be
  is *dedicated* — nothing to reserve. (It was only associated with "inventory"
  hit before consumption) that would now apply more broadly.

## Open problems to resolve before specing

1. **Where does QOH live for a transient lot?** Today QOH is a column on
   `PriceListItem`. Options: (a) every tracked lot becomes its own inventory-item
   row (a freeform Material gets promoted to / backed by an inventory-item row
   with real on-hand qty), or (b) Material itself grows real on-hand semantics.
   This is the actual structural work.

2. **Findability is the whole ballgame.** The payoff is "reuse the 2 leftover
   sheets → recover money," which only happens if the *next* job's planner can
   *find* those sheets. Catalog items are findable (codes, search). Transient
   lots are freeform text ("felt" / "specialty felt" / "grey 1/4in felt") — they
   don't dedupe and are hard to surface at allocation time. If they're not
   findable, this becomes tracked-but-never-reused: pure data-entry burden, no
   money recovered. **This is the risk that decides whether the feature is worth
   building.** Needs a real answer (search UX, optional promotion of a lot to a
   catalog item, dedupe-on-description, etc.).

3. **Dead-lot cleanup.** Need a "write off / discard" action for transient lots
   that sit at qty>0 forever because nobody ever wants that material again.

## Relationship to the expenses feature

- The expenses feature ships on **today's** inventory model: a freeform Material
  (no PLI) is just a job cost with no tracking; a PLI-inventoried Material does
  the existing QOH/earmark/restock dance.
- **Forward-compatible:** when this reframe lands, the expense "create a Material"
  path inherits universal tracking for free, with no expense-side rework.

## Pointers

- Models: `apps/inventory/models.py` (`PriceListItem`, `Material`, `Earmark`,
  `InventoryAdjustment`).
- Services: `apps/inventory/services.py` (`InventoryService`, `MaterialService`).
- Durable doc to update when built:
  `docs/designs/materials-inventory-and-purchasing.md`.

## Misc notes

- Inventory items will need a visible purchase history, maybe this is @History or maybe not

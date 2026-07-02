# Freeform materials ride the inventory rails (procure + track arrival)

> **Status: design spec — rough draft (direction agreed; mechanics being pinned).**
> Design-level, not yet a TDD task plan. Will get its own branch to implement.
> Decisions are tagged **[SETTLED]** (agreed in discussion), **[DEFAULT]** (chosen
> here; flag to change), **[OPEN]** (needs a decision before the task plan).
> Companion reference: `docs/designs/materials-inventory-and-purchasing.md` (the
> transient-lot design this finally implements).

## The problem

A **`Material` row means a major physical component of a job that must be tracked** —
the kind of thing you need to know has been *ordered* and has *arrived* before work can
proceed. Small consumables (primer, staples, screws, glue) are deliberately **not**
Materials and **not** inventoried; they never reach a Material row, so they are out of
scope here. **[SETTLED]**

Today the app tracks physical existence for **PLI/catalog-backed** materials only:

- The catalog `InventoryItem` carries `qty_on_hand` (QOH). Approval creates an
  **earmark**; `consume()` refuses to draw more than QOH; PO receipt / expense stock
  receipt bump QOH. Arrival gates consumption.

But for a **freeform** material (`Material.inventory_item is None`) there is **no
physical-existence signal at all**:

- No QOH, no earmark. `consume()` hits `if pli and qty > 0:` → the branch is skipped →
  it just flips `consumption_state = consumed` with **no arrival check**. Starting the
  task consumes the material whether or not it exists.
- A **PO** line attached to a freeform material contributes only a link + cost; receipt
  (`PurchaseOrderReceivingService.receive_items`) bumps QOH **only `if li.inventory_item`**
  and never touches the linked Material. `Material.quantity` is explicitly not synced.
- An **Expense** can only *create* a freeform material (supplying cost); it cannot mark
  it as arrived, and it cannot attach to a material that already exists.

The documented **transient lot** (`is_catalog=False`) design — "mint a lot behind each
freeform goods-Material" (`materials-inventory-and-purchasing.md` §2) — was never
implemented. Only the *management* machinery exists (the `is_catalog` flag,
`is_finished_lot`, the hide-on-spend list filter, write-off, merge). **Nothing mints the
lot.** The only `InventoryService.create_item` caller is the manual catalog-creation API.

Net effect: the app cannot answer "has this material been ordered?" / "has it arrived?"
for freeform materials, and — worse — **it is trivially easy to skip procurement
entirely** and start work as if the material were present. That skip should exist, but it
should be a *deliberate* act, not the silent default. **[SETTLED]**

## The core move

**Every freeform Material gets a private transient lot (`InventoryItem`,
`is_catalog=False`) minted behind it, so it rides the exact same inventory rails as a
catalog material.** After minting, `Material.inventory_item` points at that lot — the
material is no longer PLI-less; "freeform" becomes an *authoring* convenience, not a
persistent tracking hole.

The lot:

- starts `qty_on_hand = 0`;
- gets a **demand earmark** for the job (qty = `material.quantity`) at the same moment a
  catalog material would be earmarked today (see mint timing below), which keeps a QOH-0
  demand lot visible in pickers until it is fulfilled or released;
- snapshots the material's `description` / `units` / `unit_cost` / `sell_price` /
  `accounting_category` (like catalog items do at create);
- becomes a **finished lot** (QOH 0 + no earmark) once consumed → auto-hidden by the
  existing hide-on-spend filter.

Because the material now has a lot, **`consume()`'s existing QOH check runs** — task start
**blocks** on an unfulfilled major material ("can't start: the steel isn't here yet")
instead of silently consuming nothing. That gate *is the point*. **[SETTLED]**

Consumables (primer/staples/etc.) are unaffected because they are never Materials. **[SETTLED]**

**What `is_catalog` actually means.** The catalog flag is **not** a behavioral fork. The
*only* difference between a catalog item and a non-catalog (transient) lot is
**search-list visibility at QOH 0**: catalog items stay shown in pickers/lists even with
no stock (they're reorderable types); a non-catalog lot at QOH 0 with no earmark is a
finished lot and is hidden. Everything else — QOH, earmarks, `consume()`, receipt,
write-off, merge — is identical. (There may be a minor cosmetic exception in the inventory
view, nothing structural.) So all fulfillment behavior below applies uniformly to every
lot-backed material regardless of the flag; the flag just decides whether an empty lot
lingers in the picker. **[SETTLED]**

### Mint timing

Mirror the existing earmark rule so lots+earmarks appear exactly when a catalog
material's earmark appears today. **[DEFAULT]**

- **Approved (committed) job** — mint the lot + earmark at material create
  (`MaterialService.create_on_job`), alongside the existing `_mutate_earmark` call.
- **Pre-approval job (draft/submitted)** — no earmark today; materials are earmarked in
  bulk at acceptance (`InventoryService.create_earmarks_for_job`). Mint the lot there too,
  so pre-approval freeform materials get their lot + demand earmark at acceptance.

**[OPEN] Eager vs lazy minting.** Eager (above) makes consume-gating automatic but
produces a QOH-0 lot per freeform material (mitigated: finished lots auto-hide, and demand
lots are the point). Lazy (mint only when the user first Orders / Attaches / Marks-on-hand)
avoids lot proliferation but leaves a window where consume isn't gated. Leaning eager;
confirm during planning.

## Three fulfillment paths (how a demand lot gets its QOH)

Once a freeform material has a lot, fulfilling the demand = getting QOH into that lot. The
first two reuse machinery that already bumps `li.inventory_item.qty_on_hand`.

### Path 1 — Order it (generate a PO from the material) — the common case

Restore and extend the historical **"Order" affordance** (which only ever appeared for
catalog materials) so it works for freeform materials too. **[SETTLED]**

- From a freeform Material with an unfulfilled demand lot, **"Order"** creates (or appends
  to a draft) `PurchaseOrder` with a line linked to this Material. The link path already
  exists: `MaterialService.resolve_or_create_for_line` with an explicit `material_id`.
- The PO line's `inventory_item` = the material's **minted lot**. So **the existing PO
  receipt path Just Works** — `receive_items` already does
  `li.inventory_item.qty_on_hand += qty`, which now lands on the lot. No new receipt code.
- Answers both questions: **ordered?** = a linked PO line exists; **arrived?** =
  `qty_received` / lot QOH.

**[OPEN]** Does "Order" always mint a *new* PO, or offer to append to an open draft PO for
the same supplier? Supplier is often unknown at material-add time, which argues for a
lightweight "start a PO with this line" that the user then addresses to a vendor.

### Path 2 — Attach an Expense (bought off-process; it's here now) — new capability

"It's on the job, we went out and bought it without going through the official purchase
process, now it's *here* and work can continue." Today expenses can only **create** a
material; add an **attach-to-existing-material** mode. **[SETTLED]**

- Attaching supplies the **cost** (document `cost_source`, satisfying the freeform-cost
  rule) **and marks arrival**: bump the lot's QOH by the material quantity (a stock receipt
  against the private lot).
- Semantics: **attach == receipt.** After attaching, the lot has QOH and `consume()` can
  fire.

**[OPEN]** Preconditions: material pending + not already fulfilled? Interaction with a
partial PO receipt already on the same lot (attach the remainder vs. reject)?

### Path 3 — Mark on-hand without a document (deliberate escape) — the uncommon case

For a major material genuinely already present with no PO and no Expense. An explicit
**"Mark on-hand"** action bumps the lot QOH to satisfy the demand, recorded as a manual
inventory adjustment. **[SETTLED]** This *replaces* today's silent "consume works on
freeform regardless." It must be **visibly less prominent / more deliberate** than
"Order" — the design intent is that the normal flow is *order → arrive*, and skipping
straight to "it's here" is the exception, not the default. **[SETTLED]**

## consume() gating (falls out for free)

No change to `consume()` itself. Because every freeform material now has a lot, its
`if pli and qty > 0:` branch always runs, so `consume()` raises the existing
"Cannot consume N: only X on hand" until the lot is fulfilled. Task start therefore
blocks on unfulfilled major materials — surfacing procurement status at exactly the moment
it matters. The existing partial-shortfall guidance ("reduce this material and add a second
task/material for the remainder while it is procured") applies unchanged. **[SETTLED]**

## UI surface

- **Materials list** (job overview + task list): each freeform material shows a
  fulfillment state — **Needed / Ordered (PO #…) / Arrived** — driven by the lot QOH and
  any linked PO line.
- Per-material actions: **Order** (Path 1, prominent), **Attach Expense** (Path 2), and a
  de-emphasized **Mark on-hand** (Path 3).
- The "Order" button that historically existed for catalog materials becomes available for
  freeform materials as well.
- Because `is_catalog` is only a visibility flag (see above), **Order / Attach Expense /
  Mark on-hand apply uniformly to every lot-backed material** — there is no catalog-vs-
  freeform behavioral split to design around. **[SETTLED]**
- **[OPEN]** Exact placement/labels only.

## Cascade / lifecycle

- **Material delete** must collect/delete its private lot if reference-free (reuse
  `InventoryService.collect_if_finished` / the finished-lot rules), so deleting a freeform
  material doesn't strand a QOH-0 lot. **[DEFAULT]**
- **Job terminal states** already `release_earmarks_for_job`; a released demand lot with
  QOH 0 becomes finished/hidden, which is correct. **[SETTLED]**
- **[OPEN]** Un-mint on freeform→catalog conversion (if that path exists): repoint the
  material to the chosen catalog item and collect the private lot.

## Data / rollout

- **No data migration** for existing dev freeform materials — dev data is regenerated per
  project norms. New behavior applies going forward; the **converter / seed generator**
  must emit lot-backed freeform materials (or leave them freeform and let the mint hook
  fire). **[DEFAULT]**
- **Tests** (TDD, to specify in the plan): mint-on-create for an approved job;
  mint-at-acceptance for a pre-approval job; `consume()` blocks until the lot is received;
  PO receipt fulfills the lot and unblocks consume; expense-attach fulfills the lot;
  mark-on-hand override; material delete collects the private lot; the freeform earmark does
  NOT appear on draft/submitted jobs (existing invariant preserved).

## Open questions, collected

1. Eager vs lazy minting (see mint timing).
2. "Order": new PO vs append-to-draft; supplier-unknown ergonomics.
3. Expense-attach preconditions and interaction with partial PO receipts.
4. Partial receipt → partial consume policy (probably: keep all-or-nothing per material,
   lean on the split-the-material guidance).
5. Un-mint path on freeform→catalog conversion / delete edge cases.

(Resolved: catalog vs freeform is *not* a behavioral fork — `is_catalog` only governs
search-list visibility at QOH 0, so all affordances apply uniformly.)

## Why this is the right shape

- It **implements the design the docs already promised** rather than inventing a parallel
  mechanism — the transient-lot machinery (flag, hide-on-spend, write-off, merge) is
  already built and waiting for a minting hook.
- The **receipt wiring is nearly free**: once a freeform material has a lot, the existing
  PO-receipt and stock-receipt paths already bump `inventory_item.qty_on_hand`.
- It makes procurement **the default path and skipping it deliberate**, matching how the
  shop actually works: know it's ordered, know it's arrived, then work.

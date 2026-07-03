# Freeform materials ride the inventory rails (procure + track arrival)

> **Status: design spec — rough draft (direction agreed; mechanics being pinned).**
> Design-level, not yet a TDD task plan. Will get its own branch to implement.
> Decisions are tagged **[SETTLED]** (agreed in discussion), **[DEFAULT]** (chosen
> here; flag to change), **[OPEN]** (needs a decision before the task plan).
> Companion reference: `docs/designs/materials-inventory-and-purchasing.md` (the
> transient-lot design this finally implements).
>
> **Refined 2026-07-02 (mechanics pinned).** A Material is either **provisional** (no lot,
> pricing pending) or **established** (lot-backed); **establishment = pricing**, and the lot is
> minted/attached at that moment. There is **no permanently-unbacked Material** — the on-hand
> "drops" case is explicitly **parked** (see §Parked). Estimate integration is pinned too: the
> send-gate is on **sell price** (not cost), a material line may be sent before its cost is known
> (crystallizing to a provisional-cost Material via reverse-markup), and a "this line is a
> material" marker forks material-vs-fee at acceptance. Those sections below carry the detail.

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

## The core move — provisional vs. established Materials

**A Material is always in one of two states, and there is no permanently-unbacked Material:**

- **Provisional** — `inventory_item IS NULL`. A placeholder: we know we need *something*
  (description + rough qty, often a sell price), but pricing/backing isn't set up yet — e.g.
  "research M77 ABS and get prices." **Not orderable, not consumable.**
- **Established** — `inventory_item` points at a lot: a **catalog** `InventoryItem`, or a
  **transient lot** (`is_catalog=False`) minted for a one-off. Has a real cost and rides the full
  inventory rails (QOH, earmark, arrival-gated `consume`, Order/receipt).

**Establishment = pricing.** The act that turns provisional → established is supplying the price,
which mints or attaches the lot (the lot is what physically holds `unit_cost` / `sell_price`) —
"if there's a price, there can be a lot." Two ways to establish:

- **Attach a catalog item** — the material *is* a stocked/orderable type; cost and sell come from
  the catalog `InventoryItem` (sell overridable).
- **Mint a transient lot** — a genuine one-off; enter the researched/quoted `unit_cost`;
  `sell_price` defaults from the **existing default-markup config** (overridable); QOH 0.

So "freeform" stops being a persistent tracking hole — it's just the *provisional* phase before
establishment. Every Material that is actually acted on (ordered, quoted-and-accepted, consumed)
is lot-backed.

### Worked examples (RM's four)

| Material | State / backing |
|---|---|
| 3/4" baltic birch ply — used often, stocked | Established — **catalog**, usually has QOH |
| 1/4" clear acrylic — never stocked, always gettable | Established — **catalog**, ~always QOH 0 |
| 1/8" dragon skin — one-off, researched a source + quote | Established — **transient lot** at the quoted cost |
| 1/4" aluminum *drops* — on-hand, costed long ago | **Parked** (see §Parked) — the case "no unbacked" serves worst |

An established transient lot (the dragon-skin / one-off case) behaves identically to a catalog lot
(see "What `is_catalog` means"). Its lot:

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

### Establishment timing (when the lot is minted) — resolves eager-vs-lazy

The lot is minted/attached **at establishment — the moment pricing is supplied.** That resolves
the old eager-vs-lazy question: not unconditionally at material-create, and not lazily at
first-order, but exactly when the price is known. **[SETTLED]**

- **Priced at authoring** (common — catalog pick, or you already have the quote): the material is
  born **established**; the lot exists immediately.
- **Priced later** (deferred research, e.g. M77 ABS): the material is born **provisional** and is
  established when the research lands.
- **Crystallized from an estimate** (see next section): established at **acceptance** — with a
  *provisional cost* if only the sell price was known at send.

**Earmark timing is unchanged**, still keyed to job status: an established material on an
approved/committed job earmarks its lot at establishment (`_mutate_earmark`); on a pre-approval
job, earmarks are created in bulk at acceptance (`create_earmarks_for_job`). A **provisional**
material has no lot, so it cannot earmark until established — which is correct (there is nothing to
reserve yet).

## Materials on an estimate: sell-price send-gate, proto-Material, provisional cost

Estimates quote a **sell price**; cost is internal and legitimately deferrable. So the estimate
send-gate is on the **sell price**, not on establishment. **[SETTLED]**

- **A material line is sendable once it has a sell price** — the number the customer says yes to.
  It does **not** need a cost or a lot at send.
- If you can't even estimate a sell price, the escape is to **remove it from the estimate** (delete
  the line; keep the Material on the job as **provisional**) and note in the estimate email that
  pricing is TBD — bill it via a change order if the customer accepts. The invariant *"an estimate
  never carries a line with no sell price"* is never weakened; the escape removes the thing rather
  than sending a blank.

**The proto-Material marker — built here. [SETTLED, owned by this plan.]** A bare (no-descriptor)
estimate line must declare *what it will become* — a **material** vs. a **fee** (a task line already
carries a `service_item` descriptor from Part 1, so the ambiguity is only material-vs-fee). This is
the atom-type marker, and **because the material flow needs it first, it is built in this procurement
work** rather than deferred to the picker. It retires the standing LATER item (hand-typed material
lines silently becoming Fees): a bare line marked *material* crystallizes to a (provisional) Material;
unmarked / *fee* → Fee. A proto-Material line with a sell price but no lot is the **estimate face of a
provisional Material**. The unified picker (`2026-07-02-add-line-crystallization-and-unified-picker.md`
Part 2) later *consumes* this marker and wraps the full three-way selection UX around it — it does not
introduce the field.

**Provisional cost via reverse-markup (the museum-polycarbonate case). [SETTLED]** Worked example:
you're confident charging **$400/sheet** (your risk — remembered ~$300 two years ago + inflation +
markup) but don't know today's exact cost. You put **$400 as the sell price**, mark the line
proto-Material, and send. On **acceptance** it crystallizes as a real Material with a **transient
demand lot**:

- `sell_price = $400` — as quoted and accepted, **locked**;
- `unit_cost = $400 ÷ (1 + default markup)` — a **placeholder**, the existing default-markup config
  run **backwards**, flagged provisional (`cost_provisional = True` / `cost_source = 'estimated'`);
- when the **PO** is written, the **real purchase cost overrides** the placeholder and the flag
  clears; **sell stays $400**, so margin trues up against real cost — exactly where the writer chose
  to carry the risk.

Why crystallize a real Material (Option 2) instead of a **Fee** (Option 1): a Fee has no Order
affordance, no arrival gate, no COGS, and no reminder that a physical thing must be procured — it
drops the polycarbonate back into the untracked hole. The provisional-cost Material keeps it on the
materials list with an Order button and a visible "cost unconfirmed" state that *is* the reminder,
and keeps COGS/margin **computable** (against the placeholder) while flagging that the number isn't
real yet. (Rejected: **Option 3**, blocking send until cost is known — defeats the purpose of an
estimate. Rejected: **Option 1**, crystallizing to a Fee — loses all physical tracking.)

## Three fulfillment paths (how a demand lot gets its QOH)

Once a material is **established** (its transient lot exists), fulfilling the demand = getting QOH
into that lot. The first two reuse machinery that already bumps `li.inventory_item.qty_on_hand`.
(Applies to any lot-backed material; a catalog material fulfills the same way via normal receipt.)

### Path 1 — Order it (generate a PO from the material) — the common case

Restore and extend the historical **"Order" affordance** (which only ever appeared for
catalog materials) so it works for transient-lot (one-off) materials too. **[SETTLED]**

- From an established Material with an unfulfilled demand lot, **"Order"** creates (or appends
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

## consume() gating

**Established materials — falls out for free.** Because an established material has a lot, its
`if pli and qty > 0:` branch always runs, so `consume()` raises the existing "Cannot consume N:
only X on hand" until the lot is fulfilled. Task start therefore blocks on unfulfilled major
materials — surfacing procurement status at exactly the moment it matters. The existing
partial-shortfall guidance ("reduce this material and add a second task/material for the remainder
while it is procured") applies unchanged. **[SETTLED]**

**Provisional materials — must refuse, not silently flip. [SETTLED, behavior change].** Today a
material with `inventory_item IS NULL` hits the freeform branch and *silently* flips to consumed with
no check — that is the untracked hole. Under this design a null-lot material is **provisional**, and
`consume()` must **raise** ("establish and receive this material first"), never flip. You can't
consume what hasn't been priced, ordered, and received. (This is the one change to `consume()`
itself: replace the silent-freeform flip with a provisional-refusal.)

## UI surface

- **Materials list** (job overview + task list): each material shows a fulfillment state —
  **Provisional (needs pricing) / Needed / Ordered (PO #…) / Arrived** — driven by whether it's
  established, the lot QOH, and any linked PO line. A **provisional** material shows "needs pricing"
  and an **Establish** action; an established one shows the fulfillment states.
- Per-material actions: **Establish** (provisional → priced/lot), **Order** (Path 1, prominent),
  **Attach Expense** (Path 2), and a de-emphasized **Mark on-hand** (Path 3).
- The "Order" button that historically existed for catalog materials becomes available for
  transient-lot materials as well (and requires the material be established first).
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

- **No data migration** for existing dev materials — dev data is regenerated per project norms.
  New behavior applies going forward; the **converter / seed generator** must emit each material in
  a valid state — **established** (lot-backed, priced) where a price exists, or **provisional**
  (null lot) where it's a pending placeholder — consistent with the establishment rule. **[DEFAULT]**
- **Tests** (TDD, to specify in the plan): establishing a material mints/attaches its lot (catalog
  attach; transient mint with `sell_price` from default-markup config); a **provisional** material
  (`inventory_item IS NULL`) **cannot be ordered or consumed** — `consume()` **raises** instead of
  silently flipping; a proto-Material estimate line is **sendable with only a sell price** and
  crystallizes at acceptance into a Material with a transient demand lot whose `unit_cost` is the
  reverse-markup placeholder flagged `cost_provisional`; a PO write **overrides** that cost and
  clears the flag while `sell_price` stays put; `consume()` blocks an established material until its
  lot is received; PO receipt / expense-attach / mark-on-hand fulfill the lot; material delete
  collects the private lot; earmarks do NOT appear on draft/submitted jobs (existing invariant
  preserved).

## Parked — the on-hand "drops" case

Example 4 (1/4" aluminum drops: already in the shop, costed long ago, ad-hoc pricing) is the one
case the **"no permanently-unbacked Material"** rule serves worst — forcing a transient lot means
minting a lot with a made-up QOH and made-up price for a scrap you'll never track again. **RM is
deliberately parking this**: build the provisional→established / lot process first, exercise it,
and revisit whether the drops case justifies a genuine unbacked-Material category (a costed job
line with no lot and no arrival gate — correct because on-hand stock has nothing to *arrive*).
Until then: **require establishment (a lot) for every Material.** _Done when:_ the lot process is
in hand and RM has decided whether drops get an unbacked lane or a lightweight lot.

## Open questions, collected

1. **proto-Material marker — resolved: built in this plan.** The material-vs-fee bit on a bare
   estimate line is built here (materials need it first); the picker plan (Part 2) consumes it and
   adds the selection UX. (Previously flagged as a Part 2 dependency — ownership moved here.)
2. `cost_provisional` / `cost_source='estimated'` — exact field/flag shape on the lot (or Material)
   and where the "cost unconfirmed" state surfaces + clears (PO write).
3. Transient-lot **sell price** defaulting: use the **existing default-markup config** (resolved
   direction); confirm the config key and the reverse-markup arithmetic for the provisional-cost
   case.
4. "Order": new PO vs append-to-draft; supplier-unknown ergonomics.
5. Expense-attach preconditions and interaction with partial PO receipts.
6. Partial receipt → partial consume policy (probably: keep all-or-nothing per material, lean on
   the split-the-material guidance).
7. Un-mint path on established-transient → catalog conversion / delete edge cases.

(Resolved: eager-vs-lazy minting → mint **at establishment**. Sell-price default → **default-markup
config**. `is_catalog` is *not* a behavioral fork — it only governs search-list visibility at QOH 0,
so all affordances apply uniformly.)

## Why this is the right shape

- It **implements the design the docs already promised** rather than inventing a parallel
  mechanism — the transient-lot machinery (flag, hide-on-spend, write-off, merge) is
  already built and waiting for a minting hook.
- The **receipt wiring is nearly free**: once a material is established (has a lot), the existing
  PO-receipt and stock-receipt paths already bump `inventory_item.qty_on_hand`.
- It makes procurement **the default path and skipping it deliberate**, matching how the
  shop actually works: know it's ordered, know it's arrived, then work.

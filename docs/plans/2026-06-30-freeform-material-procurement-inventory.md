# Freeform materials ride the inventory rails (procure + track arrival)

> **Status: design spec — settled 2026-07-04; ready for the implementation task plan.**
> The **proto-Material marker** slice (the `is_material` field + bare marked estimate line
> crystallizing into a *provisional* Material at acceptance + the
> `default_material_accounting_category` config) SHIPPED in the 2026-07-03 unification batch.
> Everything else here is this plan's own future batch: transient-lot minting at establishment,
> the reverse-markup provisional cost, the **four** fulfillment paths (Order / Attach-Expense /
> Mark-on-hand / Customer-supplied), the `consume()`-refusal for provisional (null-lot) materials,
> **dropping `is_catalog`**, and the UI. Will get its own branch to implement.
> Decisions are tagged **[SETTLED]** (agreed in discussion), **[DEFAULT]** (chosen here; flag to
> change), **[OPEN]** (needs a decision before the task plan).
> Companion reference: `docs/designs/materials-inventory-and-purchasing.md`.
>
> **Refined 2026-07-02 (mechanics pinned).** A Material is either **provisional** (no lot,
> pricing pending) or **established** (lot-backed); **establishment = pricing**, and the lot is
> minted/attached at that moment. There is **no permanently-unbacked Material** — the on-hand
> "drops" case is explicitly **parked** (see §Parked). The estimate send-gate is on **sell price**
> (not cost); a material line may be sent before its cost is known (crystallizing to a
> provisional-cost Material via reverse-markup).
>
> **Refined 2026-07-04 (session with RM).** Aligned with the shipped **three-state Material
> lifecycle** (`pending → consumed | released`; release is the terminal tombstone — see the
> materials design doc §Consumption state machine). New decisions, all [SETTLED] below:
> **drop `is_catalog`** (manual `is_active` retirement + search ranking replace auto-hiding);
> Order = append-to-draft-or-create, actions live on the **task view page only** (pillar is
> passive); expense-attach may **establish** a provisional material; consume stays
> **all-or-nothing**; **customer-supplied materials** are pulled into this round; one
> **`cost_source` provenance enum**; plus a consumed **visual flag**, a settings UI for the
> default material AC, and the display-state vocabulary (final label: **On Hand**).

## The problem

A **`Material` row means a major physical component of a job that must be tracked** —
the kind of thing you need to know has been *ordered* and has *arrived* before work can
proceed. Small consumables (primer, staples, screws, glue) are deliberately **not**
Materials and **not** inventoried; they never reach a Material row, so they are out of
scope here. **[SETTLED]**

Today the app tracks physical existence for **PLI/catalog-backed** materials only:

- The `InventoryItem` carries `qty_on_hand` (QOH). Approval creates an **earmark**;
  `consume()` refuses to draw more than QOH; PO receipt / expense stock receipt bump QOH.
  Arrival gates consumption.

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

The documented **transient lot** design — "mint a lot behind each freeform goods-Material"
(`materials-inventory-and-purchasing.md` §2) — was never implemented. Only the *management*
machinery exists (`is_finished_lot`, the hide-on-spend list filter, write-off, merge).
**Nothing mints the lot.** The only `InventoryService.create_item` caller is the manual
catalog-creation API.

Net effect: the app cannot answer "has this material been ordered?" / "has it arrived?"
for freeform materials, and — worse — **it is trivially easy to skip procurement
entirely** and start work as if the material were present. That skip should exist, but it
should be a *deliberate* act, not the silent default. **[SETTLED]**

## The core move — provisional vs. established Materials

**A Material is always either provisional or established, and there is no
permanently-unbacked Material:**

- **Provisional** — `inventory_item IS NULL`. A placeholder: we know we need *something*
  (description + rough qty, often a sell price), but pricing/backing isn't set up yet — e.g.
  "research M77 ABS and get prices." **Not orderable, not consumable.**
- **Established** — `inventory_item` points at a lot with a real cost; rides the full
  inventory rails (QOH, earmark, arrival-gated `consume`, Order/receipt).

**Establishment = pricing.** The act that turns provisional → established is supplying the
price, which mints or attaches the lot (the lot is what physically holds `unit_cost` /
`sell_price`) — "if there's a price, there can be a lot." Ways to establish:

- **Attach an existing inventory item** — cost and sell come from the item (sell overridable).
- **Mint a lot** — enter the researched/quoted `unit_cost`; `sell_price` defaults from
  `default_material_markup_percent` (overridable); QOH 0.
- **Attach an expense** — the purchase document *is* the pricing event (see Path 2).
- **Customer-supplied toggle** — $0 is a deliberate price (see §Customer-supplied).

This is orthogonal to the (shipped) **consumption lifecycle**: `pending → consumed`
(reversible via unconsume) or `pending → released` (terminal tombstone; quantity moves to
`released_qty`, claims kept). Provisional/established says *what backs the row*;
pending/consumed/released says *where it is in its life*. A released material keeps its
`inventory_item` FK forever — the tombstone still references its lot. **[SETTLED]**

### Worked examples (RM's four)

| Material | State / backing |
|---|---|
| 3/4" baltic birch ply — used often, stocked | Established — stocked item, usually has QOH |
| 1/4" clear acrylic — never stocked, always gettable | Established — known item, ~always QOH 0 |
| 1/8" dragon skin — one-off, researched a source + quote | Established — minted lot at the quoted cost |
| 1/4" aluminum *drops* — on-hand, costed long ago | **Parked** (see §Parked) |

A minted lot behaves identically to any other inventory item. It:

- starts `qty_on_hand = 0`;
- gets a **demand earmark** for the job (qty = `material.quantity`) at the same moment a
  catalog material would be earmarked today (see establishment timing below);
- snapshots the material's `description` / `units` / `unit_cost` / `sell_price` /
  `accounting_category` (like catalog items do at create).

Because the material now has a lot, **`consume()`'s existing QOH check runs** — task start
**blocks** on an unfulfilled major material ("can't start: the steel isn't here yet")
instead of silently consuming nothing. That gate *is the point*. **[SETTLED]**

Consumables (primer/staples/etc.) are unaffected because they are never Materials. **[SETTLED]**

## Drop `is_catalog` — one item kind, manual retirement **[SETTLED 2026-07-04]**

The old framing kept a catalog-vs-transient-lot distinction whose *stated* job was
search-list visibility at QOH 0. Decision: **drop the `is_catalog` field entirely.**
An `InventoryItem` is just an item; `is_active` is the only flag.

- **`is_active` semantics:** "we can't get this any more / won't get it again, but it is
  still referenced by a Material or PO line." A *human judgment*, set manually. Everything
  active is visible and pickable.
- **No automatic hiding.** The computed `is_finished_lot` / hide-on-spend filter goes away.
  Searches show any item; there is no scrolled list to protect. Clutter is handled by
  **ranking, not hiding**: pickers sort QOH > 0 and recently-touched items first; dead
  QOH-0 lots sink but stay findable (useful history — "what did we pay last time").
  Accepted trade: the searchable namespace grows until someone flips things inactive;
  nothing can auto-retire a lot without re-inventing the type/lot distinction. **[SETTLED]**
- **Lot reuse replaces catalog conversion.** If next year someone searches "dragon skin"
  and picks last year's lot, the new material attaches to it, the demand earmark lands on
  it, Order writes a PO against it, receipt bumps its QOH — the lot *becomes* the ongoing
  home of that material type through use. No un-mint / promote / demote path needed
  (retires old open question 7). **[SETTLED]**

The doc previously claimed the flag was "not a behavioral fork" — false; it had three
behavioral uses, each of which re-homes:

1. **Hide-on-spend / `is_finished_lot`** → deleted (ranking replaces it, above).
2. **Expense classification** (`ExpenseService.create`: catalog item → stock receipt;
   otherwise → consumable Material; plus the `Expense.clean` stock-receipt validation) →
   rule becomes **"any inventory-item-backed purchase is a stock receipt"** — Path 2's
   attach == receipt applied uniformly. **[SETTLED]**
3. **Merge discard-guard** ("cannot discard a catalog item; demote first") and the
   expense job-change earmark-move guard (`pli.is_catalog`) → merge guard becomes an
   explicit confirm (**[DEFAULT]**: allow discarding any item, confirm dialog carries the
   weight); the earmark-move guard becomes `pli is not None` (correct anyway once minted
   lots carry demand earmarks).

Also removed: the `?is_catalog=` API filter, the `inventory_item_is_catalog` serializer
fields + catalog badge, the inventory list's catalog|lot column (replaced by
active/inactive), and the `is_catalog` merge-override field.

### Establishment timing (when the lot is minted)

The lot is minted/attached **at establishment — the moment pricing is supplied.**
Not unconditionally at material-create, and not lazily at first-order. **[SETTLED]**

- **Priced at authoring** (common — item pick, or you already have the quote): born
  **established**; the lot exists immediately.
- **Priced later** (deferred research, e.g. M77 ABS): born **provisional**, established
  when the research lands (or an expense attaches — Path 2).
- **Crystallized from an estimate**: established at **acceptance** — with a *provisional
  cost* if only the sell price was known at send.
- **Customer-supplied**: born established at $0 (see below).

**Earmark timing is unchanged**, still keyed to job status: an established material on an
approved/committed job earmarks its lot at establishment (`_mutate_earmark`); on a
pre-approval job, earmarks are created in bulk at acceptance (`create_earmarks_for_job`).
A **provisional** material has no lot, so it cannot earmark until established — correct
(there is nothing to reserve yet).

## Materials on an estimate: sell-price send-gate, proto-Material, provisional cost

Estimates quote a **sell price**; cost is internal and legitimately deferrable. So the
estimate send-gate is on the **sell price**, not on establishment. **[SETTLED]**

- **A material line is sendable once it has a sell price.** It does **not** need a cost
  or a lot at send.
- If you can't even estimate a sell price, the escape is to **remove it from the estimate**
  (delete the line; keep the Material on the job as **provisional**) and note in the
  estimate email that pricing is TBD — bill via change order if accepted. The invariant
  *"an estimate never carries a line with no sell price"* is never weakened.

**The proto-Material marker — ✅ SHIPPED (2026-07-03).** A bare (no-descriptor) freeform
estimate line carries one bit: **"is this a material?"** Checked → crystallizes to a
provisional Material at acceptance; unchecked → Fee. A checked line with a sell price but
no lot is the **estimate face of a provisional Material**.

**Provisional cost via reverse-markup (the museum-polycarbonate case). [SETTLED]** You're
confident charging **$400/sheet** but don't know today's exact cost. Put $400 as the sell
price, mark the line proto-Material, send. On **acceptance** it crystallizes as a Material
with a minted demand lot:

- `sell_price = $400` — as quoted and accepted, **locked**;
- `unit_cost = $400 ÷ (1 + default_material_markup_percent/100)` — a placeholder, flagged
  `cost_source = 'estimated'`;
- when the **PO** is written (or an expense attaches), the **real cost overrides** the
  placeholder and the provenance updates; **sell stays $400**, so margin trues up against
  real cost — exactly where the writer chose to carry the risk.

Why crystallize a Material rather than a Fee: a Fee has no Order affordance, no arrival
gate, no COGS, and no reminder that a physical thing must be procured. The
provisional-cost Material keeps the Order button and a visible "cost unconfirmed" state
that *is* the reminder, and keeps COGS/margin computable while flagging the number isn't
real yet.

## `cost_source` — one provenance enum **[SETTLED 2026-07-04]**

One field on `Material` answers both "is this cost real?" and "who owns this thing?":

| Value | Meaning |
|---|---|
| `NULL` | provisional — no lot, no meaningful pricing yet |
| `estimated` | reverse-markup placeholder from an accepted estimate line — **cost unconfirmed** |
| `entered` | user typed a researched/quoted cost (or attached an item and accepted its pricing) |
| `po` | real document cost from a PO line (overrides `estimated`/`entered`) |
| `expense` | real document cost from an attached expense |
| `customer_supplied` | $0, deliberate and locked — customer owns the thing |

"Cost unconfirmed" (`estimated`) is **not** a display state of its own — it can coexist
with Needed/Ordered/On Hand — so it rides as a small warning mark next to the cost until
a PO/expense clears it. **[OPEN — minor]** exact value name for the attach-an-item case
(`entered` vs a distinct `catalog`); decide in the task plan.

## Four fulfillment paths (how a demand lot gets its QOH)

Once a material is **established**, fulfilling the demand = getting QOH into its lot.
The first two reuse machinery that already bumps `li.inventory_item.qty_on_hand`.

### Path 1 — Order it (generate a PO from the material) — the common case

Restore the historical **"Order" affordance**, now for every established material. **[SETTLED]**

- From an established material with an unfulfilled demand lot, **Order**:
  **if open draft POs exist**, offer a small choice — "add to PO-2026-NNNN (vendor)" per
  draft, or "start new PO"; **if none exist, skip the dialog** and create a draft PO with
  this line, vendor left blank to address afterward. **[SETTLED]** Supplier-unknown stays
  painless.
- The PO line's `inventory_item` = the material's lot, linked via the existing
  `MaterialService.resolve_or_create_for_line` explicit path. **Existing PO receipt Just
  Works** — `receive_items` already bumps `li.inventory_item.qty_on_hand`. No new receipt
  code.
- Answers both questions: **ordered?** = linked PO line exists; **arrived?** = lot QOH.

### Path 2 — Attach an Expense (bought off-process; it's here now)

Today expenses can only **create** a material; add an **attach-to-existing-material**
mode. **Attaching an expense is a pricing event, so it is allowed on any pending
non-customer material — including a provisional one, where the attach itself
establishes.** **[SETTLED]**

- **Attach to established** — supplies/overrides cost (`cost_source = 'expense'`), bumps
  the lot QOH by the expense quantity. **Attach == receipt**; work can start.
- **Attach to provisional** — one move does everything: mints the lot at the expense's
  unit cost (sell from `default_material_markup_percent` unless a sell price already
  exists from an estimate line — that one stays locked), sets provenance, bumps QOH.
  Covers "bought it off-process before anyone ever priced it" with no separate
  Establish step.
- **Preconditions:** material `pending` and not customer-supplied. That's it. **[SETTLED]**
- **Partial-PO interaction — don't block.** Ordered 12, received 8, bought the last 4
  locally: the expense adds QOH on top of the partial receipt. The loose end (PO line
  still shows 4 outstanding) is the user's to settle by cancelling the remainder on the
  PO; existing PO surfaces already show outstanding quantities. Documented, not
  enforced. **[SETTLED]**

### Path 3 — Mark on-hand without a document (deliberate escape) — uncommon

For a major material genuinely already present with no PO and no Expense. An explicit
**"Mark on-hand"** action bumps the lot QOH, recorded as a manual inventory adjustment.
**[SETTLED]** Replaces today's silent "consume works on freeform regardless." Rendered
**deliberately quiet** — a text link, not a button; the normal flow is *order → arrive*,
and skipping straight to "it's here" is the exception. **[SETTLED]**

### Path 4 — Customer-supplied (they're sending it; we didn't buy it) **[SETTLED 2026-07-04, in scope]**

Not an exception to the establishment model — an established material at zero price:

- **Creation:** a "customer-supplied" toggle in the material form. Flipping it zeroes and
  **locks** the pricing fields and establishes on save (lot minted at cost $0 / sell $0,
  `cost_source = 'customer_supplied'`). That deliberate gesture is what makes $0 a real
  price rather than an unset one — a provisional material (no lot, "needs pricing") and a
  customer-owned one (lot + provenance marker) never look alike, in data or on screen.
- **Everything rides the same rails:** demand earmark at establishment; `consume()` blocks
  until QOH arrives ("can't start until the customer's panels show up"); COGS $0; and
  inventory valuation is right for free — cost × QOH = 0, so the customer's property never
  inflates inventory value while sitting on the shelf.
- **Arrival is a job-context action, not an inventory-page edit:** an "Awaiting customer"
  material shows **Mark received** on the task view page. Click, optionally adjust the
  quantity (they sent 8 of 12 — partial receipt, defaulting to the full remainder, same as
  PO receiving), done. Recorded in inventory history as a *customer delivery*.
  Mechanically Path 3's QOH bump, but a first-class named action because for this
  provenance "it arrived, no document" is the legitimate primary flow.
- **Suppressions:** no Order button, no pricing nag, no expense-attach (you don't buy the
  customer's own panels).
- **On the estimate:** omit, or show as a $0 line — the $0 line is nice documentation of
  what the customer owes in kind. **[DEFAULT]** allow both; no special handling.
- **Leftover after release:** QOH in the lot that is the *customer's* property —
  return-or-scrap is a human decision; write-off covers it.

## consume() gating

**Established materials — falls out for free.** The lot makes `consume()`'s existing QOH
check run: task start blocks on an unfulfilled major material until the lot is fulfilled.
**[SETTLED]**

**Provisional materials — must refuse, not silently flip. [SETTLED, behavior change].**
Today a null-lot material silently flips to consumed with no check. Under this design
`consume()` **raises** ("establish and receive this material first"), never flips. This is
the one change to `consume()` itself.

**All-or-nothing per material row. [SETTLED 2026-07-04].** Partial *consumption* is
rejected: a fractionally-consumed row would break the three-state lifecycle, prorate COGS,
and muddy invoice claims. Partial *arrival* stays a **user** action prompted by the
refusal message — split the row (restock the shortfall off this material, add a second
material for the remainder, start work on what's here). Each row stays fully pending or
fully consumed with clean claims. The system action is only ever the refusal. The
existing shortfall message gets a light polish since richer states now sit behind it
(ordered / awaiting customer).

## UI surface **[SETTLED 2026-07-04]**

**Venue rule: pillar items are passive; actions live on the task view page.** The job
overview pillar (TaskTree) shows each material's status word and the consumed/released
styling — no buttons, no links to act. All per-material actions appear on the task view
page (`JobTaskListPage`) only. (This resolves the absorbed LATER item about the lost
per-material "order" link — it comes back on the task view page, not the pillar.)

**Display status — one derived label per material row.** Computable from fields already
settled (lot present?, `cost_source`, lot QOH vs quantity, PO link, `consumption_state`);
no new state machine, display logic only:

| Status | Condition | Actions (task view page only) |
|---|---|---|
| **Needs pricing** | provisional (no lot) | *Set pricing* (opens the material modal — attaching an item or entering a cost on save *is* establishment; no separate ceremony), *Attach expense* (establishes + receives) |
| **Needed** | established, stock short, no PO link | **Order** (prominent), *Attach expense*, *Mark on-hand* (quiet text link) |
| **Ordered — PO-NNNN** | established, linked PO line outstanding | PO number links to the PO (receipt happens there); *Attach expense* stays for bought-the-remainder |
| **Awaiting customer** | `customer_supplied`, stock short | **Mark received** (qty prompt, default remainder) |
| **On Hand** | established, lot QOH covers quantity | none — the quiet good state |
| **Consumed** | `consumption_state = consumed` | none (unconsume is not a user action) — **the visual consumed flag** |
| **Released** | `consumption_state = released` | none — tombstone: greyed/struck, qty 0, visible as history |

Cross-cutting:

- **Cost-unconfirmed mark** (`cost_source = 'estimated'`): small warning next to the cost,
  coexists with Needed/Ordered/On Hand, cleared by PO write / expense attach.
- **Customer-supplied identity** comes from the status chip; no button-suppression
  weirdness to explain.
- **Pickers** (material modal item search, PO line form, etc.): show everything active,
  ranked QOH > 0 and recently-touched first (see §Drop `is_catalog`).
- **Settings UI for `default_material_accounting_category`:** the config key exists
  (read by estimate acceptance) but has no UI. Add a picker in the existing Accounting
  Categories settings block, gated `can_manage_config`. **[SETTLED]**
- **Inventory list:** catalog|lot column → active/inactive; `?include_finished` /
  hide-on-spend filtering removed.

## Cascade / lifecycle **[rewritten 2026-07-04 for the three-state world]**

- **Release, not delete, is the normal end-of-life** for anything referenced. A released
  material keeps its `inventory_item` FK forever; its lot is **never collected/deleted**.
  Hard-delete survives only for unreferenced pending scratch paper (existing
  `remove()` / restock-to-zero / sever rules — already shipped).
- **A released material's arrived-but-unused stock stays in inventory and is available
  for future work. [SETTLED]** Release backs out the demand earmark; real QOH stays in
  the lot, visible and pickable (it's genuinely on the shelf). A later material can
  attach to it (lot reuse). Write-off handles true scrap; return-to-customer is manual
  for customer-supplied leftovers.
- **Job terminal states** already `release_earmarks_for_job`; correct unchanged.

## Data / rollout

- **Migration:** drop `is_catalog` (plus the serializer fields, API filter, list filter,
  merge-override entry). Per project norms, run the suite **fresh, without `--keepdb`**
  after the migration lands.
- **No data migration** for existing dev materials — dev data is regenerated. The
  **nealsdata converter / seed generator** must emit each material in a valid state —
  established (lot-backed, priced, `cost_source` set) or provisional (null lot) — and
  stop writing `is_catalog`. Converter changes must run `tests.test_neals_builders`.
- **Tests** (TDD, to specify in the task plan): establishing mints/attaches the lot
  (item attach; mint with sell from `default_material_markup_percent`); a provisional
  material cannot be ordered or consumed — `consume()` raises; proto-Material line
  sendable with only a sell price, crystallizes to `cost_source='estimated'` with the
  reverse-markup placeholder; PO write overrides cost + provenance while sell stays put;
  `consume()` blocks an established material until its lot is fulfilled; PO receipt /
  expense-attach (established *and* provisional) / mark-on-hand / customer Mark-received
  (incl. partial) fulfill the lot; expense classification without `is_catalog` (any
  item-backed purchase = stock receipt); merge without the catalog guard; released
  material keeps its lot + QOH stays available; earmarks do NOT appear on draft/submitted
  jobs (existing invariant preserved).

## Parked — the on-hand "drops" case

Example 4 (1/4" aluminum drops: already in the shop, costed long ago, ad-hoc pricing) is
the case the **"no permanently-unbacked Material"** rule serves worst. **RM is
deliberately parking this**: build the provisional→established / lot process first,
exercise it, and revisit whether drops justify a genuine unbacked-Material category.
Until then: **require establishment (a lot) for every Material.** _Done when:_ the lot
process is in hand and RM has decided whether drops get an unbacked lane or a
lightweight lot. (Note: mark-on-hand + lot reuse may already cover most drops cases in
practice — a $0-ish minted lot marked on-hand.)

## Open questions, collected

All majors are settled. Remaining minors for the task plan:

1. `cost_source` value for the attach-an-item establishment case (`entered` vs distinct
   `catalog`).
2. Merge discard-guard replacement: plain confirm ([DEFAULT] above) vs requiring the
   discard side be inactive.
3. Picker ranking spec (QOH > 0 first, then recency — define "recently-touched").

(Resolved this session: Order append-vs-new → **offer append when drafts exist, else
create**; expense-attach preconditions → **pending + not customer-supplied; establishes
provisional; no partial-PO block**; partial receipt vs consume → **all-or-nothing, user
splits the row**; un-mint/conversion → **evaporated with `is_catalog`**; `cost_provisional`
shape → **the `cost_source` enum**; sell-price default + reverse-markup →
**`default_material_markup_percent`, sell = cost × (1 + pct/100), reverse = sell ÷ (1 +
pct/100)**. Resolved earlier: minting timing → at establishment.)

## Absorbed LATER items (2026-07-04)

Moved from `docs/designs/LATER.md`; work as part of this plan or consciously punt back.

- **Lost per-material "order" link when the Materials pillar was folded into Tasks &
  Materials.** — _added 2026-06-28; **RESOLVED by this plan's venue rule**_: the Order
  affordance returns on the **task view page only**; the pillar shows passive status
  (including Ordered — PO-NNNN) but no actions. RM explicitly reversed the earlier
  thought of putting "order" on the pillar — pillar items don't have actions.

- **PO line form needs an explicit "attach to existing material" picker.** — _added
  2026-06-20._ When adding a PO line for a job that already has materials, there's no way
  to deterministically attach the line to a *specific* existing pending material — the
  resolver only auto-claims on an exact single match, else silently creates a duplicate.
  Fix: once a Job is selected on the PO line form, surface that job's pending unlinked
  materials and let the user pick "attach to this one" (explicit `material_id`) or
  "create new". _Done when:_ deterministic attach with tests.

- **Reassigning a PO line's job/material is tricky — rethink the whole flow.** — _added
  2026-06-21._ Draft PO: inline Edit changes the job; issued/received: standalone Change
  Job modal gated by pending state. The rules differ by PO status × consumption state and
  the cost/earmark implications aren't surfaced. Want a coherent mental model before
  committing to a design. _Done when:_ settled and documented in
  `materials-inventory-and-purchasing.md`.

- **Earmarking is done per-material and then overwritten — do we need both layers?** —
  _added 2026-06-05._ `MaterialService.create_on_job` calls `_mutate_earmark`
  (incremental), but bulk job-population paths then call
  `InventoryService.create_earmarks_for_job`, which **overwrites** each Earmark to the
  absolute total. Work out the intended division of labor and whether one layer can be
  dropped without breaking idempotency. (Full history of the 2026-06-05 regression fix in
  git history of this file.) _Done when:_ documented why both exist or removed the
  redundant layer.

- **Mixed-receipt expense loses the non-inventory cost.** — _added 2026-06-14._ An expense
  is single-mode (cost OR stock receipt). One trip buying both an inventoried shortfall
  and a special non-item finish silently drops one side. Note: dropping `is_catalog`
  changes the classification rule (any item-backed purchase = stock receipt) but does
  **not** fix the mixed case. _Done when:_ multi-item expenses or a split prompt exist so
  a non-inventory cost can never be silently swallowed.

- **Expense didn't count as a cost in the job overview — and NO catalog item was picked.
  Investigate.** — _added 2026-06-18._ Reported: an expense missing from job cost with no
  catalog item selected, so the stock-receipt classification shouldn't have fired — cause
  unknown. Chase the actual row (`stock_pli_id`, `material_id`, `job_id`, `amount`) when
  reproducing. _Done when:_ root-caused and fixed (or shown expected), with a test.

## Why this is the right shape

- It **implements the design the docs already promised** rather than inventing a parallel
  mechanism — the lot machinery (write-off, merge) is built and waiting for a minting hook.
- The **receipt wiring is nearly free**: once a material has a lot, the existing PO-receipt
  and stock-receipt paths already bump `inventory_item.qty_on_hand`.
- It makes procurement **the default path and skipping it deliberate**, matching how the
  shop actually works: know it's ordered, know it's arrived, then work.
- Dropping `is_catalog` **dissolves a distinction instead of managing it**: frequently
  used items and one-off lots are the same thing at different usage frequencies, and lot
  reuse lets one graduate into the other with zero ceremony.

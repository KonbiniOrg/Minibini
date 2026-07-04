# Deletion doctrine: name the event, don't tombstone the row

> **Status: design spec — agreed in discussion 2026-07-03, not yet a TDD plan.**
> Decisions tagged **[SETTLED]** (agreed with RM), **[DEFAULT]** (chosen here; flag to
> change), **[OPEN]** (needs a decision before the task plan). Companion reference:
> the deletion-semantics map artifact (2026-07-03) and
> `docs/designs/estimates-and-prices.md` §6.2 (the source-row purge this partially
> supersedes).

## The principle

Most delete buttons on committed records are **a business event wearing a
disguise**. "Delete this fee" after acceptance doesn't mean "this row shouldn't
exist" — it means *"we're no longer charging for this,"* which is an agreement
change and already has a name: a change order. "Delete this material" means
*"the job planned stuff it didn't use"* — a release/return. Once the event is
named and given its own operation and state, the tombstone stops being a design
decision and becomes a residue of the event. **Tombstones are not the goal;
they fall out of properly named events.** [SETTLED]

What remains of deletion is **mistake correction**, which is legitimate exactly
and only while nothing references the row. Two composable rules confine it:

- **Rule 1 — delete only the unreferenced.** An atom may be hard-deleted only
  while nothing references it: no document claim in any lens (estimate / CO /
  invoice source rows), no bleps, not consumed, no PO or expense link. [SETTLED]
- **Rule 2 — claims move only in draft.** Claims are created and released only
  while the claiming document is draft (already true: wizard add/remove-atoms
  and line deletes are draft-only; acceptance-created claims never release;
  revision *moves* claims). "Sent" is therefore the freeze line, with no
  per-status special cases. [SETTLED]

Together: to delete a mistaken fee on a draft estimate, remove it from the line
(a draft-only op that makes you acknowledge the change) and then delete —
RM's "delete the line item first." Once the estimate is sent, everything behind
it is undeletable without a change order. A setup fee nobody ever claimed stays
deletable forever.

**The retention carve-out.** The one good reason to delete committed data is
retention policy — the email purge (`email_retention_days`) deletes other
people's cached content on a clock, not shop history. That stays. [SETTLED]

**Actuals gravity.** Records of what physically happened (bleps, consumed
materials, picked-up shipments, payments, HistoryEntry) are never deleted by
events; at most they are voided with a record. Task chose `cancelled` over
deletion *because* of bleps — that reasoning generalizes. [SETTLED]

## Per-object plan

### Fee — [SETTLED]

There is no legitimate reason to delete a deliberate, referenced Fee.

- Manual delete (`FeeService.delete`) **refuses while referenced** (any lens
  claim, any live invoice) with a message pointing at the change-order flow.
  Unreferenced accidental fees delete as today.
- CO acceptance retirement marks the fee **`retired`** instead of deleting it,
  and **stops purging its claim rows** — the estimate line's provenance stays
  resolvable forever (the whole point: "still history on the job, still
  supports an estimate line item").
- Retirement **nulls the OneToOne `task` link** (a retired fee must not block a
  replacement fee on the same task; MySQL has no conditional uniqueness).
- Field shape: a `retired` boolean or small status — [OPEN, minor].
- The dormant `Fee.task` FK itself (no UI reaches it) is a separate question —
  decide keep-and-wire vs drop during implementation. [OPEN, minor]

### Material — [SETTLED]

Every non-mistake deletion path is the same disguised event: *"this job planned
material it didn't end up using."* One rule replaces four per-path behaviors:

> **Restock-to-zero: delete the row if nothing references it, otherwise mark it
> `released`.**

- Applies uniformly to: manual full restock, the job-completion loose-material
  release (the acrylic bug's path), PO delete/sever with the delete decision,
  and CO acceptance retirement (which always retires → `released`, since a CO
  target is by definition claimed).
- **Unclaimed full restock hard-deletes** — lean hard on the scratch-paper
  analogy: an unclaimed, unconsumed, fully returned material never mattered.
- `released` keeps its claim rows (no purge), releases its earmark, and is
  excluded from live-work consumers. Earmark/QOH accounting is unchanged.
- Field shape: third `consumption_state` value vs a separate flag — [OPEN,
  minor]. A third state reads well (`pending / consumed / released`) but check
  every `consumption_state` comparison first.

### Expense reject — [SETTLED]

The exemplar of "fix the upstream event, not the deletion." Today reject
already refuses when the expense-created material is **consumed** ("adjust
inventory manually"). Extend the same guard to **claimed**: rejection is
disallowed while the material is referenced at all. Then reject's material
delete is always a Rule-1-legal delete of an artifact of the rejected claim.

### Task — [SETTLED]

- `cancelled` stays the retirement; bleps preserved (unchanged).
- `delete_task` additionally **refuses while claimed by a non-draft document**
  (Rule 1) — today a pending task claimed by a sent estimate is deletable.
  Existing guards (in-progress/complete, bleps) unchanged.

### Job — [DEFAULT]

Hard delete (the two-phase destroy) is restricted to **unworked jobs**: no
bleps, no invoices, no sent documents. Anything else uses `cancelled`, which
already exists and already releases earmarks. Job delete is currently the one
path that can destroy time actuals wholesale (cascades bleps).

### InventoryItem — [SETTLED, RM's reversal]

Keep rows; table size is a non-issue (search-driven pickers, indexed flags).
- `is_active` deactivation is the retirement ("we don't carry this anymore") —
  the model comment already says "use instead of hard deletion."
- **Write-off deactivates rather than collects** the spent lot; hide-on-spend
  already handles picker visibility.
- Hard delete only for never-referenced rows (mistake correction). Note
  `Material.inventory_item` is SET_NULL — deleting a referenced item silently
  demotes established materials to provisional, one more reason not to.
- Merge is unchanged: it repoints references first, so the discard is genuinely
  unreferenced (catalog-level mistake correction).

### Blep — [OPEN]

The own-blep 30-hour window stays (fat-finger fixes). The tension is
`can_manage_time` deleting anyone's blep at any age — "it *happened*." Candidate:
a `voided` flag (excluded from billing/payroll, retained as record), riding the
existing `BlepChangeRequest` review machinery. Decide separately — time-record
integrity may be its own pass.

### Expense (post-approval) / BillPayment — [OPEN]

An approved, uninvoiced expense is still hard-deletable; QBO already thinks in
voids, so a `voided` status likely fits better than delete. Payments are money
actuals and deserve the same voided-not-vanished look. Both deferred to their
own pass; noted here so the doctrine list is complete.

### Already compliant (no change)

Estimates, change orders, invoices, POs, bills (draft-only deletes + status
tombstones + supersession), deliverables (snapshots are the history; frozen
once shipped), shipments (prepared-and-empty only), RateScheme (supersession —
the exemplar), ServiceItem/WorkTemplate (PROTECT + `is_active`),
Contact/Business (PROTECT + two-phase), HistoryEntry / DeliverableSnapshot
(never).

## Consequences for the 2026-07-03 purge

`purge_source_rows_for_atom` (claims.py) stays as the **backstop for
mistake-deletes and cascades**, but stops being load-bearing for committed
records: CO retirement will no longer delete fees/materials (it retires them,
claims intact), so committed-world provenance survives instead of being purged.
The dangling-row serializer guards stay (defense against legacy data).

## Implementation sketch (when this becomes a task plan)

1. States: `Fee.retired` (+ null task on retire), Material `released`.
2. A shared **`.live()`** queryset idiom for atoms; sweep the aggregate
   consumers: `compute_job_financials`, both wizard source pools,
   `create_earmarks_for_job`, job-detail atom lists. (Schedule already excludes
   cancelled tasks; documents don't read atoms.)
3. Reroute the four Material paths + CO retirement to the one restock rule.
4. Rule-1 refusals on `FeeService.delete`, `TaskService.delete_task`,
   `ExpenseService.reject` (claimed guard), Job destroy (unworked-only).
5. Write-off → deactivate.
6. TDD throughout; no data migration (dev data regenerates); update
   `estimates-and-prices.md` §6.2/§14.11, `data-constraints.md`,
   `materials-inventory-and-purchasing.md` in the same pass.

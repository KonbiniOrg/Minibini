# Deliverables on the Estimate + deliverable versioning — design spec

**Status:** Approved in brainstorm; ready to carry into the CO-spec backfill.
**Date:** 2026-05-25
**Scope:** the first of three sequenced specs (the prerequisite the change-order
deliverables section depends on).

Sibling specs:
1. **Deliverables** — *this doc.*
2. **Change orders + `on_hold`** — `docs/plans/2026-05-25-change-orders-spec.md`
   (its §9 Deliverables gap is backfilled from this doc next; this doc also adds
   one requirement to the CO spec — shipments freeze during `on_hold`, §7).
3. **`cancelled-with-invoice`** — not yet written.

---

## 1. Problem & goals

Two gaps:

1. **Estimates don't show deliverables.** The customer should get the full
   picture on the estimate: *here are the exact things we're building* (the
   deliverables) next to *this is what we expect it to cost* (the line items).
   Today deliverables only appear on the Job detail page.
2. **Deliverables have no versioning.** Today a Deliverable is a flat job-level
   row, frozen permanently once any estimate is accepted, with no history model.
   Change orders need to amend the agreed deliverable scope while preserving what
   was originally agreed.

Non-goal: pricing deliverables. **Deliverables stay priceless** — the cost is the
line-item total shown alongside them.

---

## 2. Settled model

- **Display on the Estimate** (and each CO): the agreed scope (qty / units /
  description), beside the line items.
- **One live editing surface.** Users always edit the **live `Deliverable`
  list** (the existing job-level rows, existing editor). No separate per-document
  draft surface.
- **No pre-send history.** Freely editable until the estimate is sent; goes
  read-only at send; that read-only state *is* v1.
- **Versioned per document via write-once snapshots** (§3.2), captured lazily on
  two triggers (§5). v1 ↔ Estimate, v2 ↔ CO#1, v3 ↔ CO#2.
- **Proposed vs. effective:** while a CO is open the live list holds the
  *proposal*; it only becomes the agreed/effective set when the CO is accepted.
  Because the job is `on_hold` during negotiation (no work, no shipping — §7),
  the live list temporarily holding an un-agreed proposal is harmless.
- **Fulfillment continuity by anchoring (Option A):** an *unshipped* deliverable
  is freely editable in the live list; the instant it has *any* shipment it is
  **anchored** — frozen at its **ordered** quantity, never editable or removable.
  Shipments stay attached to the live row, so fulfillment never fragments.
- **No split mechanism** (rejected "Option B"). A change to an already-delivered
  deliverable would have to be a brand-new row — but in 11 years of running the
  shop this has never happened, so we don't build for it. The escape hatch for
  any change a CO can't express is the bound the whole CO feature rests on:
  **finalize the job (cancel-with-invoice) and start a new one.**

---

## 3. Data model

One **live** list (continuous, fulfillment-tracked) + per-document **write-once
snapshots** (the v1/v2/v3 records).

### 3.1 `Deliverable` (existing model, extended)

The **live, job-level, fulfillment-tracked, effective** scope. `ShipmentItem` →
`Deliverable` (PROTECT) unchanged — shipments always anchor here, so "4 of 10
shipped" stays correct for the life of the job. This single set is what users
edit, what work/shipments operate on, and what each snapshot is copied from.

Added behavior (no new persistent fields required):

- **Anchored** = "has ≥ 1 `ShipmentItem`." `DeliverableService.update`/`delete`
  reject an anchored row. (Delete is already PROTECT-guarded; this extends to
  edits.)
- Editability of *unanchored* rows is derived from document state (§5.4).

### 3.2 `DeliverableSnapshot` (new)

An immutable, **write-once** copy of a deliverable scope, attached to the document
it records. No `status` field — a snapshot is frozen the moment it's written. No
fulfillment data.

| Field | Type | Notes |
|---|---|---|
| `id` | AutoField PK | |
| `estimate` | FK Estimate (CASCADE, null) | Set iff this snapshot records an Estimate. |
| `change_order` | FK ChangeOrder (CASCADE, null) | Set iff it records a CO. Exactly one of `estimate`/`change_order` set (enforced in `clean()`). |
| `version` | PositiveInteger | 1 = Estimate, 2.. = successive COs (display ordinal). |
| `description` / `qty_ordered` / `units` / `sort_order` | mirror `Deliverable` | The frozen content. |
| `source_deliverable` | FK Deliverable (SET_NULL, null) | Traceability to the live row copied from; may be null if that row was later removed. |

`db_table = 'deliverable_snapshots'`. One document's snapshot = all rows sharing
its `(estimate|change_order)`. A document has **at most one** snapshot; whether it
records an *agreed* set (accepted-then-amended document) or a *proposed* set
(rejected CO) is derivable from the owning document's status — no `kind` field
needed.

Rationale for a snapshot table over version-stamping live rows: anchored rows must
carry forward across versions, which a version-stamped single list models
awkwardly (a row would belong to many versions), and it muddies the
one-row-per-shipment fulfillment invariant. Snapshots are flat frozen copies; the
live list stays one continuous set. Matches the codebase idiom of documents
snapshotting their own content.

---

## 4. How the pieces relate

- Users edit the **live list** only — for the estimate (pre-send) and for each CO
  (during its draft window).
- Snapshots are **derived records**, written automatically on the two triggers in
  §5. They are never hand-edited.
- The **effective** deliverables = the live list. The latest *accepted*
  document's deliverables also = the live list (until it's amended and thereby
  snapshotted). Every *superseded* or *rejected* document's deliverables = its
  snapshot.
- **Display rule:** a document's deliverables = its snapshot if it has one, else
  the live list.

---

## 5. Lifecycle

### 5.1 Estimate path

1. Pre-send: deliverables edited freely on the live list (existing rule).
2. Estimate sent (`open`): the live list goes read-only (existing). `mark_open`
   still rejects a zero-deliverable estimate (jobs-tasks §12.3). No snapshot yet —
   the live list *is* the v1 record while it stays read-only.
3. Estimate accepted: the live list is the committed effective scope.

### 5.2 Change-order path

1. **CO created** (`draft`; job is `on_hold`). **Trigger 1:** snapshot the current
   live list (the latest accepted agreement's deliverables) onto the document
   being amended (the Estimate, or the last accepted CO). That snapshot is both
   the amended document's permanent *agreed* record **and** the rollback target if
   this CO dies. Then the live list's **unanchored** rows become editable again.
2. CO `draft`: edit the live list freely (add / change qty / remove unanchored
   rows). Anchored rows stay locked.
3. CO sent (`open`): the live list goes read-only — this frozen state is the
   proposal the customer reviews.
4. CO **accepted**: the live list already *is* the new agreed set — **no reconcile
   step**. (When a later CO is created, Trigger 1 will snapshot this CO's agreed
   set onto it.)
5. CO **rejected**: **Trigger 2:** snapshot the current live list (this CO's final
   proposal) onto the rejected CO, preserving it. Then the human forks (CO spec
   §5.4):
   - **Resume original** — invoke the manual **"restore last agreed
     deliverables"** action, which reconciles the live list's unanchored rows back
     to the prior agreement's snapshot (the Trigger-1 snapshot). Anchored rows are
     untouched.
   - **Renegotiate** — revise the CO; keep editing the live list (the proposal is
     already preserved by Trigger 2).
   - **Stop and bill** — `cancelled-with-invoice` (spec 3); deliverable state moot.

### 5.3 How a CO's deliverable section reads

Show the **full new agreed set** with the changes **highlighted as a delta** —
`+ 5 brackets` (added), `~ widget 10→8` (changed), `− powder-coat` (removed). The
customer sees the complete resulting scope *and* what's changing, mirroring the
billing-line add/remove/replace deltas on the same CO.

### 5.4 Editability rules (replaces jobs-tasks §12.2 table)

Editability of the **live list** is derived (not stored):

| Situation | Live list | Notes |
|---|---|---|
| No estimate, or latest estimate `draft` | **Editable** | Existing behavior. |
| Latest estimate `open` (sent) | Read-only | Existing. |
| Estimate `accepted`, no live CO | Read-only | Until a CO opens (then editable for that CO). |
| A CO is `draft` | **Editable** (unanchored rows only) | This is the proposal being authored. `can_manage_jobs`. |
| A CO is `open` (sent) | Read-only | Frozen proposal under customer review. |
| Reject → resume (manual restore action) | Reconciled to prior snapshot | One-shot restore; then read-only. |
| Any time | Anchored (shipped) rows are **never** editable/removable | Option A. |

Live-list editability keys on **CO state**, never on `on_hold` alone — a non-CO
pause (backorder, deposit) leaves the agreed scope frozen.

---

## 6. Resolved decisions (were open in the prior draft)

- **Data-model shape:** live list + write-once `DeliverableSnapshot` (snapshot
  model). The version-stamped-rows alternative is rejected (§3.2 rationale).
- **Single editing surface:** users edit the live list throughout; no separate CO
  draft-snapshot surface; snapshots are derived. (The simplification that drove
  this rewrite.)
- **Snapshot timing:** lazy — Trigger 1 (new-CO creation) and Trigger 2 (CO
  rejection). Not eager-at-send.
- **Reject-and-forget?** No — Trigger 2 preserves the rejected proposal.
- **CO deliverable section:** full new set with highlighted delta (§5.3).
- **Estimate shows fulfillment?** No — agreed scope only (§8).

---

## 7. Required cross-spec change: freeze shipments during `on_hold`

Because the live list holds the *proposal* (not the last-agreed set) while a CO is
open, **`on_hold` must also freeze shipment creation** — otherwise someone could
ship against a proposed-but-unagreed deliverable, and a row could anchor
mid-negotiation. The CO spec's `on_hold` §2.3 (which froze bleps and hid
tasks) gets one addition: `ShipmentService.create` rejects when the job is
`on_hold`. Folded into the CO-spec backfill (task #3).

---

## 8. UI

- **Estimate detail + customer-facing render:** a **Deliverables section**
  (reusing the Job-detail `DeliverablesSection` chrome) showing agreed scope only
  — `qty units description`, **no fulfillment columns** (the estimate is a
  pre-work agreement; fulfillment lives on the Job/Shipments views).
- **Estimate draft:** the existing `DeliverablesEditModal` edits the live list.
- **CO detail:** the *same* `DeliverablesEditModal` edits the live list while the
  CO is `draft`; read-only once sent. The section renders the §5.3 delta view
  (diffing the live list against the amended document's snapshot).
- **Reject → resume:** a "Restore last agreed deliverables" button performs the
  §5.2 rollback.

---

## 9. Interaction with existing models — what changes

- `Deliverable`: extend the edit guard to reject anchored (shipped) rows; keep the
  PROTECT delete guard; editability derivation per §5.4.
- New `DeliverableSnapshot` model.
- `DeliverableService`: add `snapshot_document(doc)` (write-once),
  `restore_live_to_snapshot(snapshot)` (the reject→resume rollback, unanchored
  rows only); keep `create/update/delete/reorder` with the new guards.
- `Estimate`: expose its deliverables (live list or snapshot per §4) to detail +
  customer render. No snapshot on send (lazy).
- `ChangeOrder` (spec 2): Trigger 1 on its creation (snapshot the amended doc);
  Trigger 2 on its rejection (snapshot itself).
- `ShipmentService.create`: reject when job is `on_hold` (§7).
- Shipments otherwise unchanged — still anchor to live `Deliverable` rows.

---

## 10. Out of scope / non-goals

- Pricing on deliverables (always priceless).
- Split-at-delivery (Option B) and post-delivery deliverable edits (§2).
- The change-order model itself (spec 2) and `cancelled-with-invoice` (spec 3).
- Customer-visible fulfillment on the estimate (agreed scope only; §8).

---

## 11. Durable-doc updates owed on completion

- `docs/designs/jobs-tasks-and-worksheets.md` §12.2 (editability table), §12 intro
  (deliverable versioning + snapshots), §12.4 (shipments blocked on `on_hold`).
- `docs/designs/estimates-and-prices.md` — deliverables section on the Estimate.
- `docs/designs/data-constraints.md` — anchoring invariant, snapshot constraints,
  one-snapshot-per-document.
- Backfill `docs/plans/2026-05-25-change-orders-spec.md` §9 + §2.3 (shipments
  freeze) — task #3.

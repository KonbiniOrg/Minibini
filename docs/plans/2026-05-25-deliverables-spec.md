# Deliverables on the Estimate + deliverable versioning — design spec

**Status:** Draft for review. Recommended defaults are flagged where a mechanical
choice was open (§5.3, §6, §8).
**Date:** 2026-05-25
**Scope:** the first of three sequenced specs (the prerequisite the change-order
deliverables section depends on).

Sibling specs:
1. **Deliverables** — *this doc.*
2. **Change orders + `on_hold`** — `docs/plans/2026-05-25-change-orders-spec.md`
   (its §9 Deliverables gap is backfilled from this doc next).
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

## 2. Settled model (decisions locked in the brainstorm)

- **Display on the Estimate** (and each CO): the agreed scope (qty / units /
  description), beside the line items.
- **No pre-send history.** Freely editable until the estimate is sent; **frozen
  at send** → that's **v1**; never changes under the original estimate.
- **Versioned per document:** v1 ↔ Estimate, v2 ↔ CO#1, v3 ↔ CO#2. A new version
  is authored when a CO is created, frozen at **CO send**, cycle repeats.
- **Proposed vs. effective:** a CO's version is a *proposal* until the CO is
  *accepted*; the effective set stays the prior version during negotiation; a
  *rejected* CO's version stays in history as a frozen, never-effective proposal.
- **Fulfillment continuity by anchoring (Option A):** an *unshipped* deliverable
  carries forward into the next version freely; the instant it has *any* shipment
  it is **anchored** — frozen at its **ordered** quantity, never re-copied, never
  editable or removable. Shipments stay attached to the anchored row, so
  fulfillment never fragments.
- **No split mechanism** (the rejected "Option B"). A change to an
  already-delivered deliverable would have to be a brand-new row — but in 11 years
  of running the shop this has never happened, so we don't build for it. The
  escape hatch for any change a CO genuinely can't express is the same bound the
  whole CO feature rests on: **finalize the job (cancel-with-invoice) and start a
  new one.**

---

## 3. Data model (recommended)

> **Recommended shape — flagged for review (open decision §6).** This realizes
> the §2 behavior with the cleanest fulfillment story. The considered alternative
> (version-stamping the live rows directly) is in §6.

Two pieces: one **live** list (continuous, fulfillment-tracked) and per-document
**frozen snapshots** (the v1/v2/v3 records).

### 3.1 `Deliverable` (existing model, extended)

Stays the **live, job-level, fulfillment-tracked** entity. `ShipmentItem` →
`Deliverable` (PROTECT) is unchanged — shipments always anchor here, so "4 of 10
shipped" stays correct for the life of the job. This is the single set work and
shipments operate on; it is the **effective** agreement scope at any moment.

Added behavior (no new fields strictly required beyond what's derivable):

- **Anchored** = "has ≥ 1 `ShipmentItem`." An anchored Deliverable is frozen:
  `DeliverableService.update` / `delete` reject it. (Today PROTECT already blocks
  delete; this extends the guard to edits.)
- Editability of *unanchored* rows is governed by document state (§5.4), not
  stored.

### 3.2 `DeliverableSnapshot` (new)

An immutable, frozen copy of the agreed deliverable scope as of a document's
freeze point. These rows are the **v1/v2/v3 customer-facing records**; they carry
**no** fulfillment data.

| Field | Type | Notes |
|---|---|---|
| `id` | AutoField PK | |
| `estimate` | FK Estimate (CASCADE, null) | Set iff this snapshot belongs to an Estimate. |
| `change_order` | FK ChangeOrder (CASCADE, null) | Set iff it belongs to a CO. Exactly one of `estimate`/`change_order` is set (enforced in `clean()`). |
| `version` | PositiveInteger | 1 for the Estimate, 2.. for successive COs (display ordinal). |
| `status` | CharField | `draft` (CO authoring) / `frozen` (at send). Estimate snapshots are created already `frozen`. |
| `description` / `qty_ordered` / `units` / `sort_order` | mirror `Deliverable` | The frozen content. |
| `source_deliverable` | FK Deliverable (SET_NULL, null) | Traceability back to the live row this was copied from (may be null if that row was later removed). |

`db_table = 'deliverable_snapshots'`. One document version = all snapshot rows
sharing a `(estimate|change_order, version)`.

Rationale for a separate table over version-stamping live rows: the live list has
exactly one job (fulfillment), and anchored rows must be *shared forward* across
versions — which a version-stamped single list models awkwardly (a row would have
to belong to many versions). Snapshots are flat frozen copies; the live list is
one continuous set. This also matches the codebase idiom of documents snapshotting
their own content (e.g. line-item AC snapshots).

---

## 4. How the pieces relate

- **Estimate** authors its deliverables on the **live list** (existing behavior —
  least churn), then a **v1 snapshot** is frozen at estimate send.
- **ChangeOrder** authors its deliverables on its own **draft snapshot** (so the
  live/effective list is untouched during negotiation), frozen at CO send.
- On document **acceptance**, the live list is reconciled to the just-accepted
  snapshot (§5.2 / §5.3).
- The **effective** deliverables for the job = the live list, which always equals
  the latest *accepted* snapshot (post-reconcile), with anchored rows carried
  through.

---

## 5. Lifecycle

### 5.1 Estimate path

1. Pre-send: deliverables edited freely on the **live list** (existing rule —
   editable while no estimate / estimate `draft`).
2. Estimate sent (`open`): the live list goes read-only (existing), and a **v1
   `DeliverableSnapshot`** is frozen from it. `mark_open` already rejects a
   zero-deliverable estimate (jobs-tasks §12.3) — unchanged.
3. Estimate accepted: the live list is the committed effective scope (it already
   equals v1; no reconcile needed).

### 5.2 Change-order path

1. CO created (`draft`) — the job is `on_hold` (CO spec). A **draft snapshot**
   (v_n+1) is seeded by copying the current effective set (live list) — anchored
   rows included as read-only, unanchored rows editable.
2. CO `draft`: edit the draft snapshot freely (add / change qty / remove
   unanchored rows). The **live list is untouched** — the customer hasn't agreed.
3. CO sent (`open`): the snapshot is **frozen**. This is the proposed v_n+1.
4. CO **accepted**: the snapshot becomes effective. During the `approved` apply
   window (CO spec §5.3) the human **reconciles the live list** to the frozen
   snapshot by hand — edit unanchored rows, add new rows, remove unanchored rows
   that were dropped. **Anchored rows are excluded** (already committed; can't
   change). Consistent with the CO rule that a human applies the signed change.
5. CO **rejected**: the snapshot stays in history as a frozen, never-effective
   proposal. The live list is untouched; the effective scope remains the prior
   version.

### 5.3 How a CO's deliverable section reads — *recommended default*

> **Recommended (open decision §8):** show the **full new agreed set** with the
> changes **highlighted as a delta** — `+ 5 brackets` (added), `~ widget 10→8`
> (changed), `− powder-coat` (removed). The customer sees the complete resulting
> scope *and* exactly what's changing, mirroring the billing-line
> add/remove/replace deltas on the same CO.

### 5.4 Editability rules (replaces jobs-tasks §12.2 table)

Editability of the **live list** is derived (not stored):

| Situation | Live list | Notes |
|---|---|---|
| No estimate, or latest estimate `draft` | **Editable** | Existing behavior. |
| Latest estimate `open` (sent) | Read-only | Existing. |
| Estimate `accepted`, no live CO | Read-only | Existing ("permanently" — now "until a CO apply window"). |
| A CO is `draft`/`open` (negotiating) | Read-only | The **CO's draft snapshot** is what's editable, not the live list. |
| A CO is `accepted`, job in the `approved` apply window | **Editable** (unanchored rows only) | The reconcile step (§5.2). `can_manage_jobs`. |
| Any time | Anchored (shipped) rows are **never** editable/removable | Option A. |

Key correction carried from the CO brainstorm: live-list editability keys on **CO
state**, never on `on_hold` alone — a non-CO pause (backorder, deposit) leaves the
agreed scope frozen.

---

## 6. Open decision — data-model shape

**Recommended:** §3's live-list + `DeliverableSnapshot` (separate frozen copies).

**Alternative considered (not recommended):** version-stamp the live `Deliverable`
rows directly (`version` + document link + supersession chain), copying unshipped
rows per version and sharing anchored rows forward. Rejected because anchored rows
shared across versions create heterogeneous version membership, and the
fulfillment-critical single-row-per-shipment invariant is muddier. The snapshot
model keeps one clean live list for fulfillment and treats versions as flat frozen
records.

---

## 7. Fulfillment & anchoring (Option A) — worked example

- Estimate accepted, v1 = **10 brackets**. Work proceeds; **4 ship** →
  `ShipmentItem`s point at the bracket `Deliverable` (now anchored).
- Customer wants 15 → CO → draft snapshot seeded from effective set. The bracket
  row is anchored (read-only in the snapshot); the increase is authored as a
  **new** snapshot row `5 brackets`. Snapshot frozen at CO send; accepted.
- Apply: live list gains a new `5 brackets` Deliverable; the original `10
  brackets` row is untouched (anchored, keeps its 4 shipments).
- Fulfillment reads correctly across the two rows; nothing re-pointed.

Reductions/removals of a *partially-shipped* deliverable are unsupported by design
(§2) — finalize-and-restart is the escape hatch.

---

## 8. UI

- **Estimate detail + customer-facing render:** a **Deliverables section**
  (reusing the Job-detail `DeliverablesSection` chrome) showing agreed scope only
  — `qty units description`, **no fulfillment columns** (the estimate is a
  pre-work agreement; fulfillment lives on the Job/Shipments views). *Recommended
  default for the "show fulfillment?" question: no — agreed scope only.*
- **Estimate draft:** the existing `DeliverablesEditModal` edits the live list.
- **CO detail:** a deliverables section editing the CO's **draft snapshot** while
  the CO is `draft`; read-only (frozen) once sent. Renders the §5.3 delta view.
- **Apply window (job `approved` after accepted CO):** the live-list editor
  reopens for unanchored rows (the reconcile step), with anchored rows shown
  locked.

---

## 9. Interaction with existing models — what changes

- `Deliverable`: extend the edit guard to reject anchored (shipped) rows; keep the
  PROTECT delete guard. Editability derivation updated per §5.4.
- New `DeliverableSnapshot` model + service for create/freeze/reconcile.
- `Estimate`: snapshot v1 on `mark_open`; expose its snapshot to the detail +
  customer render.
- `ChangeOrder` (from spec 2): owns a draft→frozen deliverable snapshot; its accept
  handler triggers (or unlocks) the live-list reconcile.
- `DeliverableService`: add `snapshot_for_document`, `seed_co_snapshot`,
  `reconcile_live_to_snapshot`; keep `create/update/delete/reorder` for the live
  list with the new guards.
- Shipments: **no change** — they keep anchoring to live `Deliverable` rows.

---

## 10. Out of scope / non-goals

- Pricing on deliverables (always priceless).
- Split-at-delivery (Option B) and post-delivery deliverable edits (§2).
- The change-order model itself (spec 2) and `cancelled-with-invoice` (spec 3).
- Customer-visible fulfillment on the estimate (agreed scope only; §8).

---

## 11. Open decisions (recommended defaults in brackets)

1. **Data-model shape** — live-list + `DeliverableSnapshot` *[recommended]* vs
   version-stamped live rows. (§6)
2. **CO deliverable section reading** — full new set with highlighted delta
   *[recommended]* vs full set only vs pure delta. (§5.3)
3. **Estimate deliverables show fulfillment?** — no, agreed scope only
   *[recommended]*. (§8)
4. **Snapshot timing for the Estimate** — at send (`mark_open`) *[recommended,
   matches "frozen at send"]* vs lazily at first CO. (§5.1)

---

## 12. Durable-doc updates owed on completion

- `docs/designs/jobs-tasks-and-worksheets.md` §12.2 (editability table), §12 intro
  (deliverable versioning + snapshots).
- `docs/designs/estimates-and-prices.md` — deliverables section on the Estimate.
- `docs/designs/data-constraints.md` — anchoring invariant, snapshot constraints.
- Backfill `docs/plans/2026-05-25-change-orders-spec.md` §9 (task #3).

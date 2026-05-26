# Change Orders + the `on_hold` Job state — design spec

**Status:** Draft, ready for review. Deliverables (§9) backfilled from the
deliverables spec (`docs/plans/2026-05-25-deliverables-spec.md`).
**Date:** 2026-05-25
**Scope of this spec:** the middle of three related specs.

This is one of three specs that came out of the change-order brainstorm:

1. **Deliverables redesign** — deliverables section on the Estimate + write-once
   snapshot history. *Specced in `docs/plans/2026-05-25-deliverables-spec.md`; §9
   here is its CO-side summary.*
2. **Change orders + `on_hold`** — *this doc.*
3. **`cancelled-with-invoice`** — the terminal "stop the job but bill the work
   done" state. Referenced here only as a transition target (§5.4, §8).

Build order: draft (2) with deliverables gaps → spec (1) → backfill (2)'s gaps
[done] → spec (3) → only then implementation.

---

## 1. Problem

The Job pipeline today is: customer request → Estimate sent → customer accepts →
work proceeds with the agreement frozen. Once an Estimate is `accepted` it is
terminal and the Job's Deliverables become permanently read-only. There is **no
sanctioned way** to amend the agreement after acceptance — if the customer
changes their mind, or the shop discovers the job can't be done as planned, the
only escape today is developer intervention or scrapping the job.

A **change order (CO)** is the amendment instrument: a customer-approved (or
-rejected) document that alters the accepted Estimate. Estimate + accepted COs,
together, are the work agreement.

### 1.1 Bounding the feature (what a CO is *not*)

A CO holds **less than a job's worth of change**. If a change is large enough to
need a new worksheet, fresh PlanTasks, or a re-run of the estimate wizard, that
is *not* a change order — it's "cancel and start a new job" (or close the current
one early, bill for work done, and start fresh; see spec 3). Consequences:

- A CO never touches the planning side (no worksheet, no PlanTasks, no wizard).
- A CO is authored **directly** — manual line items, or items pulled from a
  `TaskTemplate` / `PriceListItem` via the catalog picker — exactly like the
  *direct-estimate* line-item path, not the worksheet path.
- **No automated Task/Material changes.** Accepting a CO does not spawn, mutate,
  or cancel any Task or Material. This is a trust-the-user situation: a human
  applies the agreed changes to the living Job by hand. (Tasks are mutable,
  living records of what actually happened — see jobs-tasks doc §4 — so editing
  them by hand is the normal motion, not a special path.)
- **Actuals are never deleted.** Work done under the contract-at-the-time stays
  done and stays billable, even if a CO removes or redirects what that work was
  for. A CO only ever redirects the *future*.

---

## 2. The `on_hold` Job status (foundational)

`on_hold` is a new `Job` status: a **general pause**. A change order is one
reason to be on hold, but not the only one (others: waiting on a customer
deposit, a backordered material, a shop-priority bump, customer gone quiet). The
status is a primitive; the CO is one consumer of it.

Conceptually: *the job has reverted to a planning posture, but with real work
already on it.*

### 2.1 Status machine changes

Add `STATUS_ON_HOLD = 'on_hold'` to `Job`. Augmented transitions
(`Job.clean()`):

```
draft         → submitted, rejected
submitted     → approved, rejected
approved      → in_progress, on_hold, cancelled
in_progress   → work_complete, on_hold, cancelled
on_hold       → approved, in_progress, cancelled          ← new state
work_complete → completed, cancelled, in_progress
cancelled     → in_progress
rejected, completed → (terminal)
```

`on_hold` is reachable **only from the active work band** (`approved`,
`in_progress`). Pre-approval "waiting" already has a home (an `open` estimate =
awaiting response), so `draft`/`submitted` jobs are never put on hold.

Exits:
- `on_hold → approved` — the **automatic** exit on CO acceptance (§5.3).
- `on_hold → approved` / `on_hold → in_progress` — **manual** exit (non-CO
  pause, or a rejected CO), restoring the job to where it was.
- `on_hold → cancelled` (or `cancelled-with-invoice`, spec 3) — the pause
  concludes "we're stopping."

### 2.2 New `Job` fields

| Field | Type | Notes |
|---|---|---|
| `hold_reason` | TextField, blank | Free text ("CO-2026-0007 in negotiation", "awaiting deposit"). No taxonomy. Surfaced on the board pill and job header. Cleared on exit to an active status. |
| `status_before_hold` | CharField, nullable | Recorded on entry to `on_hold`. Drives the default target when a human manually resumes (non-CO / rejected-CO exits). The CO-accept auto-advance ignores it (always → `approved`). |

No date side effects: `on_hold` is not terminal, so `Job.save()`'s
`completed_date` logic doesn't fire; `start_date` is already set (and immutable)
for any job that had real work.

### 2.3 What `on_hold` does to work — by being a status, not by mutating tasks

The single biggest design win: **`on_hold` freezes and hides work purely as a
query filter on the Job status. No Task is touched, so resume is instant and
lossless.**

| Surface | Mechanism | Change required |
|---|---|---|
| **New bleps** | `BlepService` job-status guard already permits work only when the Job is `approved`/`in_progress` (live) or also `work_complete` (backfill). `on_hold` is absent from both sets → new sessions are rejected. | **None** — falls out for free. |
| **Job board** | Columns are job-status queries (Pipeline = draft/submitted/approved; In Progress = in_progress; etc.). Worker task columns render only inside In Progress. An `on_hold` job stops matching In Progress → its tasks vanish from the worker columns. | Slot `on_hold` into the **Pipeline** lane (matches the "reverted to planning" framing) with a distinct sub-status ("on hold" / "applying change order"), so the job stays findable while showing no workable task columns. |
| **Schedule** | `ScheduleService` selects workers/tasks by **task status + assignee**, *not* job status (`apps/schedule/services.py` ~lines 142, 374). So `on_hold` tasks would still show. | Add `.exclude(job__status=Job.STATUS_ON_HOLD)` (or filter to active job statuses) to the worker-selection and lane task queries. Tasks are not mutated. |
| **Shipment creation** | A CO's proposed deliverables live on the *live* `Deliverable` list while the CO is open (deliverables spec §2, §7), so shipping during a hold could fulfill an un-agreed scope. | `ShipmentService.create` rejects when the job is `on_hold`. (New guard, required by the deliverables design.) |

Explicitly **rejected** approaches (both lose information and are hard to revert,
the same objection as mass-blocking): blocking every Task; removing every Task
assignment.

Open consideration: backfilling historical bleps is also blocked during
`on_hold` (the guard excludes it). If a need arises to log pre-hold time, a
manager lifts the hold first. Acceptable for now.

### 2.4 Open decision — open bleps at entry

When a manager moves a job to `on_hold`, a worker may still be clocked in. Two
options, both mirroring existing patterns:

- **Reject with a "coordinate offline" conflict** (like `block_task` does when
  open bleps exist). *Recommended* — pausing a job out from under an active
  worker should be deliberate.
- **Auto-close the open bleps** (like the logout endpoint does).

---

## 3. The `ChangeOrder` model

A separate, estimate-shaped model. Structurally parallels `Estimate`; reuses
`BaseLineItem`. Lives in `apps/estimates/` (alongside Estimate) or a new
`apps/changeorders/` app — TBD at implementation; this spec assumes the estimate
app for proximity to shared code.

### 3.1 Fields

| Field | Type | Notes |
|---|---|---|
| `change_order_id` | AutoField PK | |
| `job` | FK Job (CASCADE) | Primary anchor. |
| `estimate` | FK Estimate (PROTECT) | The accepted Estimate this CO amends (the job's accepted estimate). Explicit anchor for the agreement-of-record composition. |
| `change_order_number` | CharField, unique-ish | Auto-generated via `NumberGenerationService.generate_next_number('change_order')`. New Configuration keys `change_order_number_sequence` + `change_order_counter` (add to fixtures + test `setUp`). |
| `version` | IntegerField, default 1 | Revision lineage (negotiation rounds). |
| `parent` | FK self (SET_NULL, null) | Previous version. |
| `status` | CharField, choices | See §3.2. |
| `created_date` / `sent_date` / `closed_date` | DateTimeField | Same auto-set + immutability rules as Estimate. |

`@history`-decorated (status changes auto-write `HistoryEntry` rows), like
Estimate/Invoice.

`unique_together = ['change_order_number', 'version']` (mirrors Estimate).

### 3.2 Status machine

Mirrors Estimate, with one deliberate divergence (rejected is *not* a hard
dead-end — see §5.4):

| Status | Meaning |
|---|---|
| `draft` | Editable; line items can be added/removed. |
| `open` | Sent to customer; awaiting response. |
| `accepted` | Customer accepted. Terminal. Drives the agreement + auto-advances the Job (§5.3). |
| `rejected` | Customer rejected. Terminal-ish: the live thread ends, but the job is **not** auto-changed, and a rejected CO may be revised into a new version (§5.4). |
| `superseded` | Replaced by a newer revision. Terminal. |
| `expired` | (Optional parallel with Estimate; auto on an expiration date.) |

Transitions:

```
draft     → open, rejected
open      → accepted, rejected, superseded, expired
rejected  → (terminal, but see "revise" below)
accepted, superseded, expired → (terminal)
```

**Revision / negotiation.** A `revise` action creates v(n+1) as a new `draft`
with `parent` = the current version and a bumped `version`:
- Revising an `open` CO sets the parent `superseded` (the open offer is
  withdrawn in favor of the new one).
- Revising a `rejected` CO **leaves the parent `rejected`** (preserving the "the
  customer said no to this exact thing" record) and threads v(n+1) off it. This
  is the divergence from Estimate, motivated by the real-world fact that
  customers click Reject to mean "let's negotiate" (§5.4).

**One live CO per job.** At most one non-terminal (`draft`/`open`) CO exists per
job at a time — parallels "one draft estimate." Enforced in the service +
(optionally) a partial unique constraint.

### 3.3 `ChangeOrderLineItem`

Inherits `BaseLineItem` (description, qty, units, price, line_number,
accounting_category, taxable_override, tax_rate_override). Deletion goes through
`LineItemService.delete_line_item_with_renumber` per the project rule.

Adds:

| Field | Type | Notes |
|---|---|---|
| `change_order` | FK ChangeOrder (CASCADE) | |
| `action` | CharField, choices `add` / `remove` / `replace` | Explicit so the customer-facing doc reads as deltas. |
| `target_line_item` | FK EstimateLineItem (PROTECT, null) | The agreement line being removed/replaced. Null for `add`. |
| `source_template` | FK TaskTemplate (SET_NULL, null) | Catalog provenance for `add`/`replace` content (parallels EstimateLineItem). |
| `price_list_item` | FK PriceListItem (SET_NULL, null) | Same, for material-shaped lines. |

Semantics by action:

- **`add`** — `target_line_item` null; the line carries its own content (new
  scope/charge).
- **`remove`** — `target_line_item` set; content optional (display can pull from
  the target). Represents "this agreement line no longer applies."
- **`replace`** — `target_line_item` set **and** the line carries new content
  (the replacement).

`target_line_item` is `PROTECT` so a referenced agreement line can't vanish out
from under a CO that documents a change to it.

> **Note — referencing later versions of the agreement.** `target_line_item`
> points at an `EstimateLineItem`. Because the agreement-of-record is composed
> (§4) rather than materialized, a second CO that wants to change a line a *prior
> accepted CO* introduced needs a stable line identity to point at. For the first
> cut, COs reference the **original accepted Estimate's** line items only; chained
> CO-on-CO edits of CO-introduced lines are out of scope (a `remove` + `add` pair
> covers the rare case). Revisit if real use demands it.

---

## 4. Agreement of record (composition, not materialization)

The current effective agreement is **computed**, not stored:

1. Start from the accepted Estimate's line items.
2. Apply each `accepted` CO in version/date order:
   - `remove` → drop the target line.
   - `replace` → swap the target line for the CO line's content.
   - `add` → append the CO line's content.
3. The result is the current agreement line set + a running grand total.

The customer-facing CO document renders the **delta** plus the net price change
and the new agreement total (e.g. "REMOVE powder-coat −$50 / ADD bracket +$300 /
**net +$250**, new total $X"). Storage is reference-and-restate (§3.3);
presentation is delta — this split is intentional.

The original accepted Estimate is never mutated; it survives verbatim for
history. "Estimate + accepted COs" is the agreement.

---

## 5. Lifecycle, end to end

### 5.1 Entry

A manager (`can_manage_jobs`) flips the Job `approved`/`in_progress → on_hold`
via the status pill, setting `hold_reason`. Work freezes and tasks hide per §2.3.
`status_before_hold` is recorded.

### 5.2 Authoring + negotiation

- **Create CO** (`draft`). **Guarded: the Job must be `on_hold`.** (One-
  directional coupling: a CO requires `on_hold`; `on_hold` does not require a CO.)
- Author line-item deltas (`add`/`remove`/`replace`) against the accepted
  Estimate's lines, plus the deliverable changes, edited in place on the live
  list (§9).
- `draft → open` (sent). Negotiation rounds = revisions (§3.2), each a new
  version superseding/threading off the prior.

### 5.3 Acceptance (deterministic → auto-advance)

On `→ accepted`:

- The CO becomes part of the agreement of record (§4).
- A signal/handler (parallel to `estimate_accepted` →
  `estimate_status_changed_for_job`) advances the Job **`on_hold → approved`**.
  `approved` reuses its existing semantic exactly: "customer committed; a human
  sets up the details before releasing to the floor (again)."
- **Nothing on the execution side fires** — no Task/Material mutation. The
  handler writes a `HistoryEntry`, recomputes the derived agreement, and unlocks
  the apply affordances.
- The trusted user then **applies the changes by hand** (edit/add Tasks and
  Materials to match the agreed CO) while the Job sits in `approved`, then
  manually releases `approved → in_progress`. Deliverables need no apply step —
  they were edited in place during the CO draft, so they're already the agreed set
  (§9).

Verified non-issues with reusing `approved`:
- Carry-over does **not** re-fire (it's triggered by `estimate_accepted`, not by
  the Job entering `approved`) — so no duplicate tasks.
- `start_date` is immutable once set — the loop doesn't reset it.
- Behavioral nuance (by design, not a regression): `approved` is a *soft* work
  gate — bleps are permitted in `approved`. So the hard freeze ends at CO
  acceptance, returning the job to the same soft "approved → verify → release"
  rhythm a fresh estimate has. The hard freeze is the *negotiation* window's job
  (`on_hold`).

### 5.4 Rejection (ambiguous → no auto-change, human fork)

On `→ rejected`, the live deliverable list (this CO's final proposal) is
snapshotted onto the rejected CO for history (§9), and the **Job status does not
change** — it stays `on_hold`. Rationale: rejection is a genuine fork with no
machine-decidable answer, and the choice belongs to the shop, not the customer:

- **Resume the original contract** — human flips `on_hold →
  in_progress`/`approved` (default from `status_before_hold`), and (if the dead CO
  had edited deliverables) invokes **"restore last agreed deliverables"** to roll
  the live list back to the prior snapshot (§9). The agreement is unchanged; work
  resumes as originally agreed.
- **Stop and bill** — human moves to `cancelled-with-invoice` (spec 3). A
  rejected CO is one of the two doorways into that state (the other being any
  pause that concludes "stop").
- **Keep negotiating** — because a customer's "Reject" often *means* "send me a
  different version," the human can **revise the rejected CO** into a new version
  (§3.2), which threads off the rejected parent and keeps the negotiation as one
  numbered document. The job stays `on_hold` (the new CO is live).

The job rests in `on_hold` **visibly** (Pipeline lane + `hold_reason`) until a
human acts — no auto-timeout. On a manual resume, `hold_reason` is cleared.

### 5.5 Exit guard

A Job leaves `on_hold` only when **no CO is live** (every CO on the job is
`accepted` / `rejected` / `superseded` / discarded). You can't resume work under
an unresolved contract. The CO-accept auto-advance satisfies this automatically
(the CO is `accepted` at the same instant). A discarded `draft` CO (estimate-
style `discard_draft`) also clears the guard.

### 5.6 Sequential COs

Each CO is its own `on_hold` episode: resume → work → pause again for the next
CO. Accepted COs accumulate in order as the running agreement (§4).

---

## 6. Invariants (summary)

- A CO can be **created** only while the Job is `on_hold`.
- `on_hold` does **not** require a CO (general pause).
- **≤ 1 live CO** per job at any time.
- A Job **exits `on_hold`** only when no CO is live.
- **Acceptance auto-advances** the Job (`on_hold → approved`); **rejection
  changes nothing**.
- No CO ever mutates a Task or Material; actuals are never deleted.
- Deliverables/agreement editability keys on **CO state**, never on `on_hold`
  alone (§9).

---

## 7. Permissions

Reuse existing atoms (`docs/designs/users-and-permissions.md`):

- Enter/leave `on_hold` (Job status pill): `can_manage_jobs` (the pill already
  PATCHes `/api/jobs/{id}/`, which requires it).
- Create / send / revise / accept-reject a CO: `can_manage_jobs` (parallel to
  estimates).
- Apply changes (edit Tasks/Materials/deliverables during the `approved` window):
  `can_manage_jobs`.
- Read CO: `IsAuthenticated`.

---

## 8. API surface (sketch)

Parallels `EstimateViewSet`. Final shape at implementation.

| Verb + path | Purpose | Perm |
|---|---|---|
| `GET /api/change-orders/?job={id}` | List COs for a job | `IsAuthenticated` |
| `GET /api/change-orders/{id}/` | Retrieve | `IsAuthenticated` |
| `POST /api/change-orders/` | Create draft (guard: job `on_hold`) | `CanManageJobs` |
| `PATCH /api/change-orders/{id}/` | Edit draft / status transition | `CanManageJobs` |
| `POST /api/change-orders/{id}/mark-open/` | `draft → open` | `CanManageJobs` |
| `POST /api/change-orders/{id}/revise/` | New version (threads/supersedes per §3.2) | `CanManageJobs` |
| `DELETE /api/change-orders/{id}/` | Discard draft (200 + JSON per project rule) | `CanManageJobs` |
| line-item endpoints | via `LineItemMixin` (add/edit/remove/reorder) | `CanManageJobs` |
| `GET /api/jobs/{id}/agreement/` | Composed agreement-of-record (Estimate ⊕ accepted COs) | `IsAuthenticated` |

Job status transition to/from `on_hold` rides the existing
`PATCH /api/jobs/{id}/` status pill. The accept→`approved` auto-advance is a
signal/service side effect, not a separate endpoint.

DELETE returns 200 + JSON body (project convention). Claim/transition conflicts
→ HTTP 409.

---

## 9. Deliverables on a CO

Backfilled from the deliverables spec
(`docs/plans/2026-05-25-deliverables-spec.md`), which is the authority. This
section is the CO-side summary.

A CO amends the deliverable scope as well as the billing lines:

- **One editing surface.** The CO's proposed deliverables *are* the job's live
  `Deliverable` list, edited in place (the existing `DeliverablesEditModal`) while
  the CO is `draft`; read-only once the CO is sent. There is no separate CO-owned
  deliverables table.
- **Write-once snapshots** record history on two triggers (deliverables spec §5):
  on *this CO's creation*, the prior agreement's deliverables are snapshotted onto
  the document being amended (the Estimate or the last accepted CO) — serving as
  both its permanent agreed record and the rollback target; on a CO's *rejection*,
  the live list (its final proposal) is snapshotted onto that rejected CO.
- **Anchoring (Option A):** a deliverable with any shipment is frozen at its
  ordered qty — not editable, not removable. Changes to delivered items would be
  new rows (never happens in practice → finalize-and-restart escape hatch).
- **On acceptance:** the live list already *is* the agreed set — **no reconcile
  step for deliverables** (they were edited in place during the CO draft). Only
  Tasks/Materials are hand-applied on accept.
- **On rejection → resume:** a manual **"restore last agreed deliverables"**
  action rolls the live list's unanchored rows back to the prior agreement's
  snapshot. Anchored rows are untouched.
- **Editability keys on CO state**, never on `on_hold` alone (deliverables spec
  §5.4) — a non-CO pause leaves the agreed scope frozen.
- **Shipments freeze during `on_hold`** (§2.3) so nothing ships against an
  un-agreed proposal.
- **Customer-facing read:** the full new agreed set with changes highlighted as a
  delta (`+5 brackets` / `~widget 10→8` / `−powder-coat`), mirroring the billing
  add/remove/replace deltas.

See the deliverables spec for the `DeliverableSnapshot` model, the editability
table, and the worked example.

---

## 10. Out of scope / non-goals

- Automated application of a CO to Tasks/Materials (deliberately human; §1.1).
- Deleting or reversing actuals (never).
- Worksheet/PlanTask/wizard involvement (that's "new job" territory; §1.1).
- The `cancelled-with-invoice` state itself (spec 3) — referenced only as a
  transition target.
- Deliverable *model* internals — the `DeliverableSnapshot` table, anchoring
  mechanics, the on-estimate display — owned by the deliverables spec; §9 is only
  the CO-side summary.
- CO-on-CO chained edits of CO-introduced lines (§3.3 note).
- Estimate "send" (PDF + email) is still a stub project-wide; the CO send path
  will follow whatever pattern that work establishes.

---

## 11. Open decisions carried into implementation

1. **Open bleps at `on_hold` entry** — reject-and-coordinate (recommended) vs
   auto-close. (§2.4)
2. **Revise-from-rejected** — allowed, threading off the rejected parent
   (recommended/assumed) vs keeping `rejected` strictly terminal and forcing a
   brand-new CO. (§3.2, §5.4)
3. **Resume target** — `status_before_hold` as the pill's default with override
   (recommended) vs strict auto-restore vs free user pick. (§2.2, §5.4)
4. **App placement** — extend `apps/estimates/` vs new `apps/changeorders/`. (§3)

---

## 12. Durable-doc updates owed on completion

Per CLAUDE.md "keep these current," when this ships, update:

- `docs/designs/jobs-tasks-and-worksheets.md` — Job status machine (add
  `on_hold`), §12.4 (shipments blocked during `on_hold`), §12.9 (change orders no
  longer "deferred"), §13 (new CO signal).
- `docs/designs/estimates-and-prices.md` — the CO model + agreement-of-record
  composition, its relationship to Estimate.
- `docs/designs/users-and-permissions.md` — CO endpoints in the atom table.
- `docs/designs/data-constraints.md` — new invariants (§6) + Configuration keys.
- `docs/designs/schedule.md` — the `on_hold` exclusion in `ScheduleService`.

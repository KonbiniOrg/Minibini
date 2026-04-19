# PO–Job–Material Integration Design

**Date:** 2026-04-17
**Scope:** Link PO line items to Jobs end-to-end, so that creating a job-linked PO line creates (or claims) a Material on the Job, receiving the line brings physical stock in correctly, and lifecycle edges (cancel, reverse, reassign) keep the data coherent.

## Motivation

Today a `PurchaseOrderLineItem` has `job` and `task` FK fields, but:

- No UI exposes them at create/edit time (only a read-only "Job" column on the PO detail).
- On receipt, the Job's Material list is never updated. Even when `li.job` is set, nothing propagates to `apps.inventory.Material`.
- An orphaned helper (`InventoryService.receive_po_line_item`) does part of the work (QOH + earmark) but isn't wired into the live receiving service.

The result: buyers can't attribute a PO line to the job that needs it, and receipt events don't appear on the job where the work is actually happening.

## Goals

1. When a user is on a Job, they can start a PO for that Job (ordering a specific planned Material or ordering something new).
2. When a user is building a PO, they can attach any line item to a Job.
3. Creating a job-linked PO line creates or claims a Material on the Job, so the Job's plan is visible and earmarks are reserved from commit, not from receipt.
4. Receiving a job-linked line moves physical stock (QOH) and the PO's receipt bookkeeping without re-creating Materials or changing plans.
5. Lifecycle edges (reverse-receipt, cancel-line, cancel-PO, reassign-job, delete-draft) behave predictably and keep the data coherent.

## Out of Scope

- **Case B** from the brainstorming: splitting a single line across inventory + a specific job. Handled through existing workflows.
- **AccountingCategory-driven branching** (services vs. materials producing different artifacts). For this round, every job-linked PO line produces a Material regardless of category. Service lines use the existing "mark Material consumed" flow.
- **Multi-vendor bulk "order shortfall"** reports from a job. Nice-to-have; defer until the core flows land.
- **Appending to an existing draft PO** from the "Order this" action. Always creates a new draft for this round; revisit if users ask for it.
- **`Line.task` is reserved for a future feature** (service POs like powder coating). Stays on the model, untouched by this design — this feature's services and UI leave it null.

## Key design choices

### Material is the sole source of truth for a line's Job attribution

`PurchaseOrderLineItem.job` is dropped. A line's job is `line.linked_material.job` (or none). `PurchaseOrderLineItem.task` stays on the model but is unused by this feature (reserved for future service-PO work).

Rationale: `Line.job` duplicated what Material already tracks, and carried a drift risk. With Material as the single source, there's no resolver-at-receipt-time, no two-place updates, no chance of `line.job != material.job`.

### Materials are created at line-add time, not at receipt

When a user adds a PO line with job attribution, the service immediately creates (or claims) a Material and links it. Receipt no longer creates Materials — it only bumps `qty_received` and QOH.

Rationale: the Material represents a commitment. If we're ordering 10 bolts for Job X, the commitment is made at the moment the line is added to the draft PO (or certainly at issue) — the earmark should exist from then, not only from receipt. This also makes the Material immediately visible on the Job page, so the plan/ordering state is coherent throughout.

### Material.quantity is planned consumption, not received amount

`Material.quantity` is set to `Line.qty` at creation and is not changed by receipts. Physical progress shows through `Line.qty_received` and `PriceListItem.qty_on_hand`. Earmarks equal `Material.quantity` for inventoried items.

Rationale: this matches how worksheet-populated Materials already behave. Partial receipts of a job-ordered Material show up as "Material qty 10, QOH 3" — the plan hasn't changed, the physical stuff is arriving. A PO-created Material is indistinguishable from a worksheet-planned one in how downstream code (consume, restock, earmark preview) operates.

### No PO↔Job join table

PO↔Job traversal uses derived queries through `Material.po_line_item`:

- *All POs for a Job:* `PurchaseOrder.objects.filter(purchaseorderlineitem__material__job=X).distinct()`
- *All Jobs for a PO:* `Job.objects.filter(materials__po_line_item__purchase_order=po).distinct()`

Rationale: two joins on indexed FKs is cheap at this scale. A denormalized join table would cost sync maintenance (signals on Material save/delete) and a drift risk. Revisit if profiling shows a hotspot.

## Guiding principle: inventoried vs. non-inventoried

**Inventoried Materials** (PLI with `is_inventoried=True`) carry strict accounting: every unit is tracked through QOH, earmarks, and consume/restock bookkeeping.

**Non-inventoried Materials** (PLI-less lines, or PLI with `is_inventoried=False`) are loosely tracked. `quantity` represents an expectation, not a tracked balance. Extras on receipt are disregarded. Shortfalls are not enforced. Consumption is effectively a boolean state change, not a quantitative one.

This principle justifies the overage rules and the simpler handling for service lines.

---

## Data model

### Changes

**Add** `Material.po_line_item`:

```python
# apps/inventory/models.py, on Material
po_line_item = models.ForeignKey(
    'purchasing.PurchaseOrderLineItem',
    on_delete=models.SET_NULL,
    null=True, blank=True,
    related_name='+',
)
```

`SET_NULL`, not `OneToOneField` — the relationship passes through nullable states during severance and reassignment. Uniqueness (at most one Material per PO line at a time) is enforced in service code.

`related_name='+'` disables the reverse accessor; service/serializer code looks up the linked Material via a helper on `PurchaseOrderLineItem`:

```python
# apps/purchasing/models.py, on PurchaseOrderLineItem
@property
def linked_material(self):
    from apps.inventory.models import Material
    return Material.objects.filter(po_line_item=self).first()
```

**Remove** `PurchaseOrderLineItem.job`. (Database column dropped via migration.)

**Keep** `PurchaseOrderLineItem.task` as-is. Not used by this feature. Reserved for future service-PO work.

### Data migration

`Line.job` is currently unused by any UI code — no production data depends on it. The migration simply drops the field; no backfill required. Any downstream references (serializers, views, tests) are updated to route through `line.linked_material.job`.

### Invariants (service-enforced)

1. At most one Material references a given `PurchaseOrderLineItem` at any time.
2. Link changes (set, clear, replace) are allowed only when the Material is in `CONSUMPTION_STATE_PENDING`. Consumed Materials are locked from link mutation.
3. A PO line's job attribution is `line.linked_material.job` (or none). There is no other way to attribute a line to a job.

### Linkage resolver

A single function `MaterialService.resolve_or_create_for_line(po_line, job, price_list_item, qty, unit_cost, description, accounting_category, material_id=None)` implements the precedence at line creation / job-change:

1. **Explicit:** if `material_id` is given, link that Material (validating: same job, pending, unlinked). Error otherwise.
2. **Claim:** if `job` and `price_list_item` given, find pending Materials on `(job, price_list_item)` with no `po_line_item`. If **exactly one** matches, link it.
3. **Create:** else create a new Material on `job` (task=null) with `quantity=qty`, `unit_cost=unit_cost`, `description=description`, PLI, accounting_category. Link it. This routes through `MaterialService.create_on_job` so earmark is handled.

The resolver runs at two moments:

- When a PO line is added with job context (API contract below).
- When an existing line's job is being set or changed (sever from old, resolve on new).

### Severance

Any action that severs a PO line from its linked Material runs a single decision point: **"Is the Material still needed on its job?"**

- **Keep:** clear `Material.po_line_item`. Material stays pending on its job.
- **Delete:** delete the Material, back out earmark if inventoried.

Severance is triggered by:

- Cancelling a PO line item (`cancel_line_item`).
- Cancelling a whole PO (`cancel_po`) — per-line decisions.
- Reassigning a line's job (sever from old + resolve on new).
- Unlinking a line's job entirely (sever; line becomes plain inventory).
- Deleting a draft PO (per-line decisions).

The frontend always collects the decision before firing the request; backends reject requests that should have a decision but don't.

### Consumed-Material lock

Any sever or reassignment on a line whose Material is consumed raises `ValidationError("Cannot change link; linked Material on JOB-XXX has been consumed.")` The user must restock from the job first if they genuinely need to undo.

---

## Services and API

### `apps/inventory/services.py` additions (on `MaterialService`)

```python
@staticmethod
def link_to_po_line(material, po_line):
    """Set material.po_line_item. Validates pending + unlinked invariants."""

@staticmethod
def unlink_from_po_line(material):
    """Clear material.po_line_item. Validates pending state."""

@staticmethod
def resolve_or_create_for_line(po_line, *, job, price_list_item=None,
                                qty, unit_cost, description,
                                accounting_category=None, material_id=None):
    """Run the 3-step resolver. Returns the linked Material."""

@staticmethod
def sever(material, decision):
    """decision: 'keep' clears FK. 'delete' deletes the Material and backs out earmark.
    Raises if decision is not 'keep' or 'delete'. Raises if Material is consumed."""
```

### `apps/purchasing/services.py` changes

`PurchaseOrderService.add_line_item(...)`:
- Accept optional `job`, `material_id` (transient — not stored on the line).
- After creating the line: if `job` or `material_id` is set, call `resolve_or_create_for_line(line, job=job, price_list_item=line.price_list_item, qty=line.qty, unit_cost=line.price, description=line.description, accounting_category=line.accounting_category, material_id=material_id)`. The resolver handles explicit link, claim, or create.
- If neither is set, no Material created; plain inventory line.

`PurchaseOrderService.update_line_item(...)`:
- Existing draft-only gate for qty/price/description/units/task/category. Behavior unchanged.
- **No cascade from Line to Material.** Editing `Line.qty` or `Line.price` does not update the linked Material. The Material is a plan on the Job; if the user wants to revise it, they do so from the Job's Materials section. This keeps the two concerns separate and avoids surprise when a line happens to have claimed a pre-existing worksheet-planned Material.
- Line.job is gone, so no "change job via update_line_item."
- Job changes route through `change_line_job` below (draft or not).

`PurchaseOrderService.change_line_job(line_item_id, new_job_id, sever_decision=None)`:
- New method. Allowed on draft / issued / partly received / received-in-full POs (not cancelled).
- Validates: linked Material (if any) is pending; `sever_decision` provided when a linked Material exists.
- Applies severance (if linked), then runs `resolve_or_create_for_line(line, job=new_job_id, ...)` with the line's existing PLI/qty/price. Uses explicit-claim where possible on the new job.
- If `new_job_id` is None: sever only, no new Material created.

`PurchaseOrderReceivingService.receive_items(po, items, user)`:
- Existing behavior: bump `qty_received`, record receipt_note, update receiver/timestamp.
- QOH handling: if `li.price_list_item` is inventoried, `pli.qty_on_hand += received_qty`. Write an `InventoryAdjustment` row.
- **No Material creation, no resolver call, no Material.qty updates.** Material already exists from line-add time (or doesn't — plain inventory line).
- Overage allowed: see rules below.

`PurchaseOrderReceivingService.reverse_receipt(po, line_item_id, user, note)`:
- Existing behavior: reverse QOH (by `qty_received`), reset line receiving fields, write InventoryAdjustment, HistoryEntry.
- If the line has a linked Material that has been consumed → raise `ValidationError("Cannot reverse receipt; linked Material has been consumed. Restock first.")`.
- If the line has a linked pending Material: no Material changes. Material.quantity and its earmark are planning data and stay put.
- HistoryEntry records the reversal.

`PurchaseOrderReceivingService.cancel_line_item(po, line_item_id, user, note, sever_decision=None)`:
- New param `sever_decision`. Required if line has a linked pending Material; service calls `MaterialService.sever(material, sever_decision)`.

`PurchaseOrderService.cancel_po(pk, sever_decisions=None)`:
- New param `sever_decisions: dict[int, str]` keyed by `line_item_id`. Required to include an entry for every line that has a linked pending Material.

`PurchaseOrderService.delete_po(pk, sever_decisions=None)`:
- Same as `cancel_po`.

### Receipt overage rules

**Loosened restriction:** the current rejection in `receive_items` (`qty_received + qty_cancelled >= li.qty → no outstanding`) is replaced with `received_qty <= 0 → skip`. Overage is accepted.

**Inventoried + PLI lines:**
- QOH += full received amount (the goods physically exist).
- Material is untouched (`quantity`, earmark unchanged).
- Excess over `line.qty` lands in general inventory as `qty_available`.

**Non-inventoried PLI lines and PLI-less lines:**
- No QOH change.
- No Material change.

**PO status auto-transition:** `_update_po_status` changes `==` to `>=`:
```python
all_done = all(li.qty_received + li.qty_cancelled >= li.qty for li in all_items)
```

### API contract changes

**`POST /api/purchase-orders/:id/line-items/`** accepts additional optional fields:
- `job` (int, job_id) — transient param; drives Material creation via resolver.
- `material_id` (int) — explicit linkage, bypasses resolver (used by "Order this" flow).

Not accepted: `task` (reserved for future use; any value is ignored or rejected — decide at implementation time).

Validation: if `material_id` is set, Material must be pending and unlinked. If `job` is set, it must be a valid Job id. Neither field is stored on the line; both are consumed by the resolver.

**`PATCH /api/purchase-orders/:id/line-items/:lid/`** accepts:
- All current fields (qty/price/description/units/accounting_category — draft-only as today).
- `job` (int or null) — job change; triggers `change_line_job` regardless of PO status.
- `sever_decision` ("keep" | "delete") — required when `job` changes AND the line has a linked pending Material.

Dispatch: if the payload contains only `job` (and optional `sever_decision`), route to `change_line_job`. Otherwise apply the existing draft-only update path. Payloads that mix `job` with non-job fields on a non-draft PO return 400.

Qty/price/description edits on a line do not propagate to its linked Material. Material edits are done on the Job page.

**`POST /api/purchase-orders/:id/cancel-line-item/`** accepts:
- `line_item_id`, `note` (existing).
- `sever_decision` — required if linked pending Material exists.

**`POST /api/purchase-orders/:id/cancel/`** accepts:
- `reason` (existing).
- `sever_decisions` (dict keyed by line_item_id) — required when any line has a linked pending Material.

**`DELETE /api/purchase-orders/:id/`** (draft deletion) accepts:
- `sever_decisions` via body when any line has a linked pending Material.

**Serializer changes (`POLineItemSerializer`):**
- Remove `job` from `fields`. Keep `effective_job_id` / `effective_job_number` SerializerMethodFields, but change their source to `obj.linked_material.job` (still derived from the Material).
- Add read-only `material` field: `{material_id, description, quantity, consumption_state, job_id, job_number}` when linked, else `null`.

**Job serializer additions (Material serializer on `apps/api/jobs/`):**
- Add read-only fields: `po_line_item_id`, `po_number`, `po_status` for badge display.

### Permissions

- Setting `job` on a line (create or change): `can_manage_financials` (existing rule for line writes; `change_line_job` also requires this).
- "Order this" (from a Job Material): `can_manage_financials`.
- "Create PO for this job": `can_manage_financials`.
- Receipt and reverse-receipt: any authenticated user.

### Concurrency

All multi-row operations (link, sever, receipt, reverse-receipt, line add with resolver) run inside `transaction.atomic()` with `select_for_update` on the `PurchaseOrderLineItem` and its linked `Material` (if any). Mirrors the existing `receive_items` pattern.

---

## Frontend / UX

### Job detail page (`#/jobs/:id`)

**Action bar addition (behind `can_manage_financials`):**
- **"Create PO for this job"** button → `#/purchase-orders/new?job=X`.

**Materials section:**
- Pending Material rows gain an **"Order"** button (behind `can_manage_financials`) → `#/purchase-orders/new?job=X&material=Y`.
- Rows whose Material is linked to a PO line display an inline "Ordered on PO-XXXX · {status}" badge linking to the PO. The "Order" button is hidden for these rows.
- Rows whose Material is consumed display nothing order-related.

### PO create page (`#/purchase-orders/new`)

Reads `?job=X` and `?material=Y` query params.

- Page header shows "For job JOB-XXXX" when `job` is present.
- After the user picks a vendor and creates the draft PO, the form stays on the page and advances to line-item entry automatically (a deviation from the normal create-PO flow that pushes to detail).
- If `?material=Y` was given: fetch the Material, pre-fill a first line-item entry with its PLI, description, qty, units, purchase_price, accounting category. On submit, include `material_id=Y` so the link is explicit.
- If only `?job=X` was given: the line-item form defaults its Job field to JOB-XXXX for each subsequent line. User can override per line.

### `LineItemForm.svelte`

New **Job** picker (typeahead against `/api/jobs/?status_not=completed,rejected,cancelled,work_complete`). Pre-filled when the page arrived with `?job`. Users can clear or change it for any line.

Informational hint when the user picks a PLI and a Job: if the job has exactly one unlinked pending Material for that PLI, show "Will link to pending Material #123 (qty 10)." Purely informational — the resolver runs server-side.

### `PurchaseOrderDetail.svelte`

- **Line item inline edit row** (draft POs only, as today) gains a **Job** picker. Other fields remain draft-only.
- **"Change Job" action per line** (available on issued, partly received, and received-in-full POs, not cancelled) — a separate button that opens a small modal with a Job picker. Available as long as the linked Material is still pending. Hidden when the linked Material is consumed or when the PO is cancelled.
- On saving a change to the `job` field (either path): if the line has a linked Material, show the sever modal:

  > **This line is linked to a Material on JOB-XXXX (qty N).**
  > Is the Material still needed on JOB-XXXX?
  > [ Keep on JOB-XXXX ] [ Delete it ] [ Cancel ]

  The PATCH includes `sever_decision`.

- Same modal is shown on:
  - **Cancel Line** — when the line has a linked pending Material. Replaces the current simple prompt.
  - **Cancel PO** — one consolidated modal listing every affected Material across all lines, each with keep/delete radio. Submit sends `sever_decisions`.
  - **Delete PO** (draft) — same consolidated modal.

- "Job" column in the line-items table continues to show `effective_job_number` (now derived from `line.linked_material.job` on the serializer side).

---

## Edge cases

**Line added with a job whose resolver claims an unlinked pending Material that already has a different qty than line.qty:** the claim keeps the Material's existing qty (the plan is authoritative). The PO line's qty is what was ordered. This can legitimately differ: the job planned to use 10, the buyer ordered 12 to hedge. The earmark stays at 10, the extra 2 on receipt land in general inventory.

**User edits `Line.qty` on a draft line with a linked Material:** the Material's qty does NOT change. `Line.qty` is what's ordered; `Material.quantity` is what's planned. They can legitimately differ (order a spare, order less than planned, etc.). If the user wants the plan to change too, they edit the Material on the Job.

**Reverse-receipt with linked pending Material:** QOH reverses, Material is untouched. The plan didn't change just because the physical goods didn't arrive.

**Reverse-receipt with consumed Material:** raise. (Plan was consumed; reversing physical receipt would desync.)

**Sever with consumed Material:** raise. (Can't change link on a consumed Material.)

**"Order this" arriving at PO-new with a stale `material` param** (Material was consumed or linked since the user clicked): show an error toast, continue with the job-only flow, do not pre-fill the line.

**Deleting a draft PO with linked Materials:** UI collects sever decisions in a consolidated modal (same component as cancel-PO). Backend accepts `sever_decisions` dict.

**Concurrent receipt attempts on the same line:** `select_for_update` on the line and its Material serializes.

**Line added with `job=X` and PLI=P, but resolver step 2 finds zero matches** (no existing Material for this PLI on X): step 3 creates a new Material. Earmark added.

**Line added with `job=X` but no PLI** (manual entry, e.g., "Outside machining $500"): resolver step 2 can't key on PLI; always falls to step 3. Creates a PLI-less Material with qty=line.qty, unit_cost=line.price.

**Line added with `job=X` and PLI=P, but resolver finds multiple unlinked pending Materials for (X, P)** (e.g., two tasks both need bolts): step 2 refuses to auto-claim; step 3 creates a new Material. The user can later manually move consumption around via existing `assign_task` flows.

---

## Testing

### Automated tests (TDD)

**Service layer — `tests/inventory/`:**
- `MaterialService.link_to_po_line` validates pending, unlinked, existing-link states.
- `MaterialService.sever` with `keep` and `delete` decisions, including earmark backout verification.
- `MaterialService.resolve_or_create_for_line` — covers all three precedence branches (explicit, exactly-one claim, create-new).

**Service layer — `tests/purchasing/`:**
- `add_line_item` with `material_id` — explicit link path.
- `add_line_item` with `job` + PLI, existing single pending match → claim.
- `add_line_item` with `job` + PLI, no match → create.
- `add_line_item` with `job`, PLI-less → create non-PLI Material.
- `add_line_item` with `job`, PLI, multiple matches → create new (step 2 refuses).
- `add_line_item` without `job` and without `material_id` → no Material.
- `update_line_item` changing qty on draft with linked Material → Material.quantity unchanged.
- `update_line_item` changing price on draft with linked Material → Material.unit_cost unchanged.
- `change_line_job` on draft: pending-keep, pending-delete, consumed-raises, missing-sever-raises.
- `change_line_job` on issued: same matrix. Cancelled PO raises.
- `change_line_job` with `new_job_id=None` (unlink): sever applied, no new Material.
- `change_line_job` resolver behavior on new job: claim vs. create.
- `receive_items` with linked Material:
  - QOH += received (inventoried).
  - Material.quantity and earmark unchanged.
  - Overage on inventoried line → QOH += full, Material untouched, excess in general inventory.
  - Overage on non-inventoried PLI → no QOH change, Material untouched.
  - Overage on PLI-less line → no QOH change, Material untouched.
  - Receipt of 0 → skipped.
- `reverse_receipt`:
  - With pending Material → QOH reversed, Material untouched.
  - With consumed Material → raises.
  - With FK already null (Material was deleted via sever earlier) → QOH reversal only.
- `cancel_line_item` with linked Material: keep, delete, consumed-raises, missing-decision-raises.
- `cancel_po` with mixed lines (linked + unlinked): per-line decisions applied.
- `delete_po` (draft): same.

**API layer — `tests/api/purchasing/`:**
- `POST .../line-items/` with `job` — resolver-create path.
- `POST .../line-items/` with `material_id` — explicit link.
- `POST .../line-items/` with both — explicit wins, `job` validated for consistency.
- `PATCH .../line-items/:lid/` changing `job` requires `sever_decision`.
- `PATCH .../line-items/:lid/` on issued PO with only job/sever_decision fields works; with other fields returns 400.
- `cancel-line-item` and `cancel/` require `sever_decision(s)` when appropriate.
- `DELETE` draft PO with linked Materials requires `sever_decisions`.
- `receive/` and `receive-all/` produce expected QOH bumps; Materials unchanged.

**Fixture updates:** `unit_test_data.json` may need a pending Material on an existing test Job to cover the resolver step-2 claim. Add if not present.

### Manual verification script

Run each scenario end-to-end with the dev server and Vite proxy. Verify via UI where noted, and via `python manage.py shell` for earmark/QOH spot checks where noted.

**Prereqs:** Logged-in user with `can_manage_financials`. Seed data via `./scripts/seed_data.sh`. Have at least one Job in `approved` or `submitted` status with tasks. Have at least one vendor Business with a Contact. Have at least one inventoried PLI (`is_inventoried=True`) and one non-inventoried PLI.

**Scenario 1: "Order this" for an inventoried Material, happy path.**
1. Navigate to Job JOB-XXXX.
2. Populate the Job from an Estimate or WorkTemplate so pending Materials appear (use an inventoried PLI).
3. In the Materials section, find a pending Material. Note its qty. Click **Order**.
4. Expect to land on `#/purchase-orders/new?job=X&material=Y`. Header shows "For job JOB-XXXX". First line-item form is pre-filled with the Material's PLI, description, qty, units, purchase_price.
5. Pick a vendor Business + Contact. Submit. Add the line item.
6. Expect the draft PO detail to appear with one line item. The Job column on the line shows JOB-XXXX.
7. Back on JOB-XXXX, verify the original Material row now shows "Ordered on PO-XXXX · Draft". The Order button is gone.
8. Return to the PO, click **Issue & Send** or **Mark as Issued**.
9. Click **Receive All**. Confirm.
10. Back on JOB-XXXX, verify the Material's qty is unchanged (plan unchanged). State is pending. Badge reads "Ordered on PO-XXXX · Received in Full".
11. Via shell: QOH for the PLI increased by the received qty. Earmark for (PLI, JOB-XXXX) equals Material.quantity (unchanged). `qty_available` for other jobs unchanged.

**Scenario 2: "Create PO for this job", mixed lines.**
1. Navigate to Job JOB-XXXX.
2. Click **Create PO for this job**. Land on `#/purchase-orders/new?job=X`.
3. Create the draft PO (pick vendor). Add three line items:
   - **Line A:** inventoried PLI the job does NOT already have as a Material. Job defaults to JOB-XXXX.
   - **Line B:** same PLI as A, but clear the Job field (unlinked inventory line).
   - **Line C:** PLI-less, description "Outside machining". Job = JOB-XXXX.
4. Verify on JOB-XXXX immediately after adding: two new pending Materials — one for Line A's PLI (qty = A.qty, linked to Line A) and one for Line C (PLI null, qty = C.qty, linked to Line C). No Material for Line B.
5. Via shell: earmark for Line A's PLI on JOB-XXXX equals Line A qty. No earmark for Line B.
6. Issue. Receive All.
7. On JOB-XXXX, Materials unchanged in qty. Via shell: QOH for Line A's PLI increased by (Line A qty + Line B qty). Earmark on JOB-XXXX still equals Line A qty only.

**Scenario 3: Receipt overage on an inventoried line.**
1. Create a PO for a job-linked inventoried line. Line qty = 10. Verify Material on the Job shows qty = 10.
2. Issue.
3. Use **Receive Items** and record qty_received = 12 on that line.
4. Verify PO line shows qty_received = 12. PO status auto-transitions to `received_in_full`.
5. On the Job, Material qty is still 10 (planned consumption unchanged). Via shell: QOH bumped by 12. Earmark on (PLI, Job) is 10. `qty_available` for other jobs: +2.

**Scenario 4: Partial receipts leave Material alone.**
1. Create a PO for a job-linked inventoried line. Line qty = 10. Material on the Job at qty = 10, state pending, linked.
2. Issue.
3. Receive 3 via **Receive Items**. Material on Job still qty = 10, state pending. Via shell: QOH += 3. Earmark still 10.
4. Receive 5. Material still 10. QOH += 5 (total +8). Earmark 10.
5. Receive 2. Material still 10. QOH += 2 (total +10). Earmark 10.
6. On JOB-XXXX, no duplicate Materials appeared. One Material row throughout.

**Scenario 5: Reverse-receipt, pending Material.**
1. Start from Scenario 1 after Receive All, before any consumption.
2. On the PO detail, click **Reverse Receipt** on the line.
3. Confirm.
4. Back on JOB-XXXX, verify the Material is still there, qty unchanged, state pending (plan unchanged). Via shell: QOH back to pre-receipt value. Earmark unchanged.

**Scenario 6: Reverse-receipt after consumption is blocked.**
1. Start from Scenario 1 after Receive All.
2. Via UI or shell, consume the Material on the Job (`MaterialService.consume`).
3. On the PO detail, click **Reverse Receipt**.
4. Expect an error: "Cannot reverse receipt; linked Material has been consumed. Restock first."
5. PO and Material states unchanged.

**Scenario 7: Reassign a line's job on a draft PO — delete.**
1. On JOB-A's Materials, use "Order this" on a pending Material. Submit.
2. On the draft PO detail, open the inline edit row on the line and change Job to JOB-B.
3. Expect the sever dialog: "This line is linked to a Material on JOB-A (qty N). Is the Material still needed on JOB-A?" Pick **Delete it**.
4. Verify: PO line's job is now JOB-B. JOB-A's Material is gone, earmark backed out.
5. The resolver runs on JOB-B: a new Material appears on JOB-B immediately (before any receipt), linked to the line. Via shell: earmark on JOB-B for this PLI increased.
6. Issue. Receive All. Verify QOH += received, Materials unchanged.

**Scenario 8: Reassign on a draft PO — keep.**
1. Same setup as Scenario 7 step 1.
2. Edit the line's Job to JOB-B. Pick **Keep on JOB-A**.
3. Verify: PO line's job is JOB-B. JOB-A's Material is still pending with `po_line_item=null`. Earmark on JOB-A unchanged.
4. A new Material appears on JOB-B linked to the line.
5. Issue. Receive All. JOB-A's Material untouched. JOB-B's Material untouched in qty. QOH += received.

**Scenario 8b: Reassign on an issued PO via "Change Job" action.**
1. Draft PO linked to a Material on JOB-A (via "Order this"). Issue without receiving.
2. On the issued PO detail, the inline edit row is not available, but a **Change Job** button appears on the line (Material is pending).
3. Click **Change Job**, pick JOB-B, pick **Delete it** in the sever dialog.
4. Verify: line's job is JOB-B, JOB-A's Material deleted and earmark backed out. New Material on JOB-B linked to the line.
5. Confirm the **Change Job** button disappears after Receive All and consume (Material becomes consumed → button gone).

**Scenario 9: Cancel a whole PO with mixed linked/unlinked lines.**
1. Setup:
   - JOB-B has a pending Material M2 (from a template/worksheet populate) for some inventoried PLI X, unlinked.
   - Create a draft PO with three lines:
     - Line 1: use "Order this" on a Material M1 on JOB-A (explicit link).
     - Line 2: manual entry with `job = JOB-B` and `price_list_item = X`. Expect the resolver to claim M2 via step 2 (verify: M2 now shows `po_line_item = Line 2`).
     - Line 3: manual entry with no job (plain inventory line).
2. Issue the PO (draft POs are deleted, not cancelled — we need issued to exercise Cancel PO).
3. On the PO detail, click **Cancel PO**.
4. Expect a consolidated modal listing M1 and M2, each with Keep / Delete radios.
5. Pick Delete for M1, Keep for M2. Submit.
6. Verify: PO cancelled. M1 deleted, its earmark backed out. M2 still on JOB-B, `po_line_item=null`, earmark on JOB-B unchanged. Line 3 unaffected.

**Scenario 10: "Order this" on a Material that's already ordered.**
1. From Scenario 1 after creating the PO (still draft).
2. Return to JOB-XXXX's Material row. Verify the **Order** button is hidden; the "Ordered on PO-XXXX · Draft" badge is shown.
3. Attempt to call the order endpoint manually via curl with the same Material. Expect a 400 with a clear message.

**Scenario 11: Non-inventoried PLI and PLI-less lines — no stock impact.**
1. Create a PO with:
   - Line A: PLI is non-inventoried, job = JOB-XXXX.
   - Line B: PLI-less, job = JOB-XXXX.
2. Immediately verify Materials exist on JOB-XXXX for both lines, qty = line qty. No earmarks (non-inventoried). No QOH effects.
3. Issue. Receive All.
4. Via shell: no InventoryAdjustment rows. No QOH change on any PLI. No Earmark rows.
5. Materials still present on the Job, unchanged.

**Scenario 12: Edit line qty on a draft PO does NOT touch linked Material.**
1. Draft PO with a line at qty = 10, linked to Material M on JOB-XXXX (qty 10).
2. Edit the line's qty to 15. Save.
3. Verify Material M qty is still 10. Earmark on JOB-XXXX still 10.
4. Navigate to JOB-XXXX, edit Material M's qty to 15 via the existing Material edit flow. Verify earmark becomes 15.
5. This demonstrates the decoupling: line = what's ordered, Material = what's planned.

### What to watch during manual testing

- PO status transitions stay correct with overage and partial receipts.
- Job Material rows stay stable across PO line edits (qty/price edits on a line don't mutate the Material).
- The resolver hint on `LineItemForm.svelte` matches actual server behavior (informational; users will trust it).
- HistoryEntry timeline on the PO records receipts, cancels, severs, and job changes.

---

## Affected existing code (audit)

Everywhere `PurchaseOrderLineItem.job` is referenced today must change or be removed. Because Material's `.po_line_item` FK replaces Line.job entirely, most of these callsites switch from `line.job` / `filter(job=X)` to `line.linked_material.job` / `filter(material__job=X)`. A concrete pre-flight checklist for the implementation plan:

**Backend — models & migrations:**
- `apps/purchasing/models.py:358-363` — remove `PurchaseOrderLineItem.job` FK. Keep `task` FK (reserved for future service-PO work; this feature's code leaves it null).
- New migration in `apps/inventory/migrations/` — add `Material.po_line_item` nullable FK.
- New migration in `apps/purchasing/migrations/` — drop `PurchaseOrderLineItem.job` column.
- Add helper `PurchaseOrderLineItem.linked_material` property.

**Backend — services:**
- `apps/purchasing/services.py:90-145` — `add_line_item`, `update_line_item`: accept transient `job` and `material_id` params; delegate to resolver. Existing signature changes need to be coordinated with viewset callers.
- `apps/purchasing/services.py` — new `change_line_job(line_item_id, new_job_id, sever_decision)` method.
- `apps/purchasing/services.py:190-296` — `PurchaseOrderReceivingService.receive_items` and `reverse_receipt`: remove the overage rejection, stop creating Materials on receipt, stop using `li.job`, keep QOH/earmark semantics coherent with the new Material-at-creation model.
- `apps/purchasing/services.py:49-67` — `cancel_po`: accept `sever_decisions` dict.
- `apps/purchasing/services.py:70-80` — `delete_po`: accept `sever_decisions` dict.
- `apps/inventory/services.py:38-50` — delete the orphaned `InventoryService.receive_po_line_item` helper (uses `po_line_item.job`; subsumed by new flow).
- `apps/inventory/services.py` — add `MaterialService.link_to_po_line`, `unlink_from_po_line`, `resolve_or_create_for_line`, `sever`.

**Backend — API views & serializers:**
- `apps/api/purchasing/serializers.py:18-38` — `POLineItemSerializer`: remove `job` from `fields`; rewrite `_effective_job` helper (lines 45-50) to use `obj.linked_material` instead of `obj.job_id` / `obj.task_id`; add `material` read-only nested field.
- `apps/api/purchasing/views.py:49` — PO list `?job=X` filter uses `qs.filter(purchaseorderlineitem__job=job).distinct()`. Rewrite to `qs.filter(purchaseorderlineitem__material__job=job).distinct()`.
- `apps/api/purchasing/views.py` — line-item POST/PATCH viewset: accept and route `job`, `material_id`, `sever_decision`.
- `apps/api/purchasing/views.py` — cancel-line-item, cancel, destroy actions: accept and forward `sever_decision(s)`.
- `apps/api/jobs/serializers.py` — Material serializer: add `po_line_item_id`, `po_number`, `po_status` read-only fields.

**Backend — search:**
- `apps/search/services.py:341` — `Q(purchaseorderlineitem__job__job_number__icontains=query)` becomes `Q(purchaseorderlineitem__material__job__job_number__icontains=query)`. Verify within-search variant (line 789 area) doesn't repeat the old pattern.

**Backend — legacy HTML views:**
- `apps/jobs/views.py:136-139` — the job detail Django view queries `PurchaseOrderLineItem.objects.filter(job=job)` to populate the POs list. Rewrite to `PurchaseOrder.objects.filter(purchaseorderlineitem__material__job=job).distinct()`.
- `apps/purchasing/views.py:80-94` — `purchase_order_create_for_job` is the legacy Django HTML "Create PO for this job" view. It doesn't read `line.job` directly but is the server-rendered equivalent of the Svelte flow we're building. Leave it alone (HTML views are being deprecated), but verify nothing in its helpers depends on `line.job`.
- `templates/jobs/job_detail.html:205-227` — server-rendered PO list on the Django detail view. Relies on the view's query above; no template change needed beyond the view rewrite. Leave unchanged (deprecated template).

**Frontend:**
- `frontend/src/components/jobs/JobDetail.svelte:314-327` — reads `li.job` from PO line-item payloads to render "(other job)" badges. Switch to `li.effective_job_id` (already populated by the serializer, now sourced from the Material). Verify the cross-job filter still functions.
- `frontend/src/routes/jobs/JobDetailPage.svelte` — confirm the PO list fetch and rendering still works end-to-end (reads from the PO list endpoint filtered by job).
- `frontend/src/components/purchaseorders/PurchaseOrderDetail.svelte:186-211` — already uses `effective_job_id` / `effective_job_number`; no change needed as long as the serializer keeps these.
- `frontend/src/components/purchaseorders/LineItemForm.svelte` — add the new Job picker (fresh code).
- Add the new `MaterialSeverDialog.svelte` component (fresh code).
- Add "Create PO for this job" button on the job page (fresh code).
- Add "Order" action and PO-badge on pending Material rows (fresh code in the Materials section of the job page).

**Tests:**
- `tests/test_po_line_item_job.py` — every test in this file exercises `PurchaseOrderLineItem.job`. Rewrite to cover the new attribution path (Material.po_line_item + transient `job` at line creation). Tests that only verify the FK exists become obsolete; tests of the end-to-end behavior migrate to the new flow.
- `tests/test_api_purchasing.py:58` — uses `job=job` directly on a PO line item; rewrite to send `job` as a transient POST param and assert via `line.linked_material.job`.
- `tests/test_api_purchasing.py:74` — uses `?job=X` filter; that endpoint's filter behavior is preserved (internally routed through Material), so the test should continue to pass after the serializer change.

**Fixtures:**
- No fixture currently sets `job` on a `purchasing.purchaseorderlineitem` row (verified across `fixtures/` and `nealseed*.json`). No backfill needed.
- `fixtures/unit_test_data.json` — consider adding a pending `Material` on an existing test Job for resolver step-2 claim tests.

**Documentation:**
- `CLAUDE.md` — no explicit references to `Line.job`, but the Purchasing and Inventory sections will get more accurate once this feature lands. Update text to mention the PO↔Material link as the job-attribution mechanism if relevant.
- `docs/designs/2026-04-06-purchasing-workflow-design.md` — older spec that pre-dates this change; reference this newer design from it for anyone reading the purchasing arc.

## Implementation notes

- The `Material.po_line_item` migration is additive (nullable FK), no backfill needed.
- The `PurchaseOrderLineItem.job` removal migration is a field drop; no data migration required because no production code has written to it. Update serializer/view references before removing the field to avoid a broken intermediate state.
- `PurchaseOrderLineItem.task` stays on the model; leave it unused by this feature's services and UI.
- Existing `PurchaseOrderReceivingService.receive_items` already runs in `transaction.atomic` — extend inside the existing block rather than wrapping a new one.
- The orphaned `InventoryService.receive_po_line_item` helper should be deleted — its QOH+earmark logic is subsumed (QOH handled by receive_items; earmark handled at Material creation time).
- Frontend: the consolidated severance dialog is a new component `MaterialSeverDialog.svelte`, used by PO detail for cancel-line, cancel-PO, delete-PO, line-edit job-change, and change-job action. Parameterize on a list of `{material_id, job_number, quantity, suggested_default}` and emit `{material_id: "keep"|"delete"}` on submit.
- `sever_decision` backend params accept the three edge cases cleanly: omitted + no linked Material = OK; omitted + linked Material = 400; present but no linked Material = ignored.
- `Line.qty`/`Line.price` edits do not cascade to the linked Material. Material edits happen on the Job page via the existing Material edit flows.

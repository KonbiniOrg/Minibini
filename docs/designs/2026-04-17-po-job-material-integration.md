# PO–Job–Material Integration Design

**Date:** 2026-04-17
**Scope:** Link PO line items to Jobs end-to-end, so that receiving a job-linked PO line creates/updates a Material on the Job (with correct inventory, earmark, and lifecycle behavior).

## Motivation

Today a `PurchaseOrderLineItem` has `job` and `task` FK fields, but:

- No UI exposes them at create/edit time (only a read-only "Job" column on the PO detail).
- On receipt, the Job's Material list is never updated. Even when `li.job` is set, nothing propagates to `apps.inventory.Material`.
- An orphaned helper (`InventoryService.receive_po_line_item`) does part of the job (QOH + earmark) but isn't wired into the live receiving service.

The result: buyers can't attribute a PO line to the job that needs it, and receipt events don't appear on the job where the work is actually happening.

## Goals

1. When a user is on a Job, they can start a PO for that Job (ordering a specific planned Material or ordering something new).
2. When a user is building a PO, they can attach any line item to a Job.
3. When a PO line linked to a Job is received, a Material appears on the Job with correct inventory accounting.
4. Lifecycle edges (reverse-receipt, cancel-line, cancel-PO, reassign-job, unlink-job) behave predictably and keep the data coherent.

## Out of Scope

- **Case B** from the brainstorming: splitting a single line across inventory + a specific job. Handled through existing workflows.
- **AccountingCategory-driven branching** (services vs. materials producing different artifacts). For this round, every job-linked PO line produces a Material on receipt regardless of category. Service lines use the existing "mark Material consumed" flow.
- **Multi-vendor bulk "order shortfall"** reports from a job. Nice-to-have; defer until the core flows land.
- **Appending to an existing draft PO** from the "Order this" action. Always creates a new draft for this round; revisit if users ask for it.

## Guiding principle: inventoried vs. non-inventoried

**Inventoried Materials** (PLI with `is_inventoried=True`) carry strict accounting: every unit is tracked through QOH, earmarks, and consume/restock bookkeeping. Overages, shortfalls, and leftover quantities all matter.

**Non-inventoried Materials** (PLI-less lines, or PLI with `is_inventoried=False`) are loosely tracked. `quantity` represents an expectation, not a tracked balance. Extras on receipt are disregarded. Shortfalls are not enforced. Consumption is effectively a boolean state change, not a quantitative one.

This principle justifies the overage rules and the simpler handling for service lines.

---

## Data model

### New field

```python
# apps/inventory/models.py, on Material
po_line_item = models.ForeignKey(
    'purchasing.PurchaseOrderLineItem',
    on_delete=models.SET_NULL,
    null=True, blank=True,
    related_name='+',
)
```

`SET_NULL`, not `OneToOneField` — the relationship passes through nullable states during severance and reassignment. Uniqueness (at most one Material per PO line at a time) is enforced in service code, not via DB constraint.

`related_name='+'` disables the reverse accessor to prevent accidental misuse of a plural manager when the invariant is at-most-one. Service and serializer code looks up the linked Material via a helper property on `PurchaseOrderLineItem`:

```python
# apps/purchasing/models.py, on PurchaseOrderLineItem
@property
def linked_material(self):
    from apps.inventory.models import Material
    return Material.objects.filter(po_line_item=self).first()
```

### Invariants (service-enforced)

1. At most one Material references a given `PurchaseOrderLineItem` at any time.
2. If a Material has a `po_line_item`, `Material.job` must equal `po_line_item.job`.
3. Link changes (set, clear, replace) are allowed only when the Material is in `CONSUMPTION_STATE_PENDING`. Consumed Materials are locked from link mutation.

### Linkage resolver

A single function `MaterialService.resolve_link_for_po_line(po_line)` implements the precedence:

1. If `po_line.linked_material` already exists → return it.
2. Else, if the line has a `job` and a `price_list_item`, find pending Materials on `(job, price_list_item)` with no `po_line_item`. If **exactly one** matches, link it and return. If zero or multiple match → fall through.
3. Otherwise return `None` (defer — a new Material will be created on first receipt).

The resolver runs at two moments:

- After `add_line_item` or `update_line_item` if the request did not specify an explicit `material_id`.
- At first receipt of a line that still has no linked Material.

**Explicit linkage via `material_id`:** When the "Order this" flow creates a line, the client passes `material_id=Y` on the line-item POST. The service skips the resolver and links directly, validating invariants. This guarantees the user's intent is honored even when the resolver would defer (e.g., multiple unlinked Materials for the same PLI).

### Severance

Any action that severs a PO line from its linked Material runs a single decision point: **"Is the Material still needed on its job?"**

- **Keep:** clear `Material.po_line_item`. Material stays pending on its job.
- **Delete:** delete the Material, back out earmark if inventoried.

Severance is triggered by:

- Cancelling a PO line item (`cancel_line_item`).
- Cancelling a whole PO (`cancel_po`) — per-line decisions.
- Reassigning a line's `job` to a different job (sever from old + relink to new).
- Unlinking a line's `job` entirely (sever with no new job).
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
    """Set material.po_line_item = po_line. Validates invariants."""

@staticmethod
def unlink_from_po_line(material):
    """Clear material.po_line_item. Validates pending state."""

@staticmethod
def resolve_link_for_po_line(po_line):
    """Run the 3-step resolver. Returns the linked Material or None."""

@staticmethod
def sever(material, decision):
    """decision: 'keep' clears FK. 'delete' deletes the Material and backs out earmark."""
```

### `apps/purchasing/services.py` changes

`PurchaseOrderService.add_line_item(...)`:
- Accept optional `job`, `task`, `material_id`.
- If `material_id` is given: link explicitly after save (via `link_to_po_line`).
- Else if `job` is given: run `resolve_link_for_po_line`.

`PurchaseOrderService.update_line_item(...)`:
- Unchanged draft-only gate for qty/price/description/units/task/category. If the incoming kwargs are limited to a `job` change (plus optional `sever_decision`), skip the draft gate and delegate to `change_line_job` below. Otherwise apply the existing draft-only semantics and run `resolve_link_for_po_line` at the end if `job` was set (which is allowed in draft regardless of Material state).
- If `job` is being changed and the line has a linked Material: require a `sever_decision` kwarg. Apply severance to the old-job Material. Then set the new job. Then run `resolve_link_for_po_line` against the new job.
- If `job` is being cleared: same severance, then set `job=None`.
- If other fields change and `job` is unchanged: no-op on linkage.

`PurchaseOrderService.change_line_job(line_item_id, new_job_id, sever_decision=None)`:
- New method that allows job changes on non-draft POs.
- Validates: PO is not cancelled; linked Material (if any) is pending; `sever_decision` is provided when a linked Material exists.
- Applies severance (if linked), updates `line.job` (and clears `line.task` if task no longer belongs to the new job), runs `resolve_link_for_po_line` against the new job.
- Draft POs route through `update_line_item`; issued / partly received / received-in-full POs route through this method from the UI.

`PurchaseOrderReceivingService.receive_items(po, items, user)`:
- Existing behavior: bump `qty_received`, record receipt_note, update receiver/timestamp.
- After the existing loop body per line, when the line has a `job` set:
  - Call `resolve_link_for_po_line(li)` if not already linked.
  - If resolver returned an existing Material (step 1 or 2): bump its `quantity` by `min(received_qty, line.qty - material.quantity)` (the capped delta). Run `_mutate_earmark(pli, job, +delta)`.
  - If resolver returned `None`: create a new Material via `MaterialService.create_on_job` with `quantity=min(received_qty, line.qty)`, `unit_cost=line.price`, `description=line.description`, PLI from line, accounting_category from line. Then link via `link_to_po_line`. (Earmark handled by `create_on_job`.)
- QOH handling (existing): `pli.qty_on_hand += received_qty` if inventoried PLI. This now runs for every inventoried receipt, regardless of whether the line is job-linked — so overage stock lands in general inventory correctly.

`PurchaseOrderReceivingService.reverse_receipt(po, line_item_id, user, note)`:
- Existing behavior: reverse QOH, reset line receiving fields, write InventoryAdjustment, HistoryEntry.
- Extension: if the line has a linked Material:
  - If Material is consumed → raise `ValidationError("Cannot reverse receipt; linked Material has been consumed. Restock first.")`.
  - Else reduce `Material.quantity` by the reversed qty, adjust earmark. If quantity drops to zero AND `restocked_qty == 0` AND Material is pending → delete the Material.
- If FK is already null (e.g., Material was restocked out of existence) → proceed with just QOH reversal; HistoryEntry notes the state.

`PurchaseOrderReceivingService.cancel_line_item(po, line_item_id, user, note, sever_decision=None)`:
- New param `sever_decision`. Required if line has a linked pending Material; the service calls `MaterialService.sever(material, sever_decision)`. Otherwise ignored.

`PurchaseOrderService.cancel_po(pk, sever_decisions=None)`:
- New param `sever_decisions: dict[int, str]` keyed by `line_item_id`. Required to include an entry for every line that has a linked pending Material.

`PurchaseOrderService.delete_po(pk, sever_decisions=None)`:
- Same as `cancel_po` above.

### Receipt overage rules

**Loosened restriction:** the current rejection in `receive_items` (`qty_received + qty_cancelled >= li.qty → no outstanding`) is replaced with `received_qty <= 0 → skip`. Overage is accepted.

**Inventoried + PLI lines:**
- QOH += full received amount.
- Material.quantity advances by `min(received_qty, line.qty - material.quantity)` (caps at ordered qty).
- Earmark grows by the same capped delta.
- Excess units (received_qty − Material_delta) land in general inventory as `qty_available`.

**Non-inventoried PLI lines and PLI-less lines:**
- No QOH change.
- Material.quantity (if linked) caps at `line.qty`. Extras disregarded.

**PO status auto-transition:** `_update_po_status` changes `==` to `>=`:
```python
all_done = all(li.qty_received + li.qty_cancelled >= li.qty for li in all_items)
```

### API contract changes

**`POST /api/purchase-orders/:id/line-items/`** accepts additional optional fields:
- `job` (int, job_id)
- `task` (int, task_id)
- `material_id` (int) — explicit linkage, bypasses resolver.

Validation: if `task` is set, `task.job_id` must match `job` (or job must be derivable). If `material_id` is set, Material must be on `job`, pending, and unlinked.

**`PATCH /api/purchase-orders/:id/line-items/:lid/`** accepts:
- All current fields.
- `job` (int or null).
- `sever_decision` ("keep" | "delete") — required when `job` changes AND the line has a linked pending Material. Returns 400 with a clear message if missing.

The viewset dispatches: if the payload contains only `job` (and optional `sever_decision`), route to `change_line_job` so the request works on non-draft POs. Any other field in the payload triggers the existing draft-only `update_line_item`. Attempts to PATCH non-job fields on a non-draft PO continue to return 400 as today.

**`POST /api/purchase-orders/:id/cancel-line-item/`** accepts:
- `line_item_id`, `note` (existing).
- `sever_decision` ("keep" | "delete") — required if linked pending Material exists.

**`POST /api/purchase-orders/:id/cancel/`** accepts:
- `reason` (existing).
- `sever_decisions` (dict) — required when any line has a linked pending Material; must cover every such line.

**`DELETE /api/purchase-orders/:id/`** (draft deletion) accepts:
- `sever_decisions` via body or query string when any line has a linked pending Material.

**Serializer additions (`POLineItemSerializer`):**
- `job` and `task` become writable.
- New read-only `material` field: `{material_id, description, quantity, consumption_state, job_id}` when linked, else `null`.

**New per-job Material field (`apps/api/jobs/serializers.py`):**
- Material serializer gains read-only fields: `po_line_item_id`, `po_number` (derived), `po_status` (derived) for badge display on the job page.

### Permissions

- `job` field set/edit on a line: `can_manage_financials` (existing rule for line-item writes).
- "Order this" (creating a PO from a Material): `can_manage_financials`.
- "Create PO for this job": `can_manage_financials`.
- Receipt (including side-effect Material creation): any authenticated user.

### Concurrency

All multi-row operations (link, sever, receipt, reverse-receipt) run inside `transaction.atomic()` with `select_for_update` on both the `PurchaseOrderLineItem` and its linked `Material` (if any). Mirrors the existing `receive_items` pattern.

---

## Frontend / UX

### Job detail page (`#/jobs/:id`)

**Action bar addition (behind `can_manage_financials`):**
- **"Create PO for this job"** button → `#/purchase-orders/new?job=X`.

**Materials section:**
- Pending Material rows gain an **"Order"** button (behind `can_manage_financials`) → `#/purchase-orders/new?job=X&material=Y`.
- Rows whose Material is linked to a PO line display an inline "Ordered on PO-XXXX · {status}" badge, linking to the PO. The "Order" button is hidden for these rows.
- Rows whose Material is consumed display nothing order-related.

### PO create page (`#/purchase-orders/new`)

Reads `?job=X` and `?material=Y` query params.

- Page header shows "For job JOB-XXXX" when `job` is present.
- After the user picks a vendor and creates the draft PO, the form stays on the page and advances to line-item entry automatically (normal create-PO flow pushes to detail; this one continues inline).
- If `?material=Y` was given: fetch the Material, pre-fill a first line-item entry with its PLI, description, qty, units, purchase_price, accounting category. On submit, include `material_id=Y` so the link is explicit.
- If only `?job=X` was given: the line-item form defaults its Job field to JOB-XXXX for each subsequent line. User can override per line.

### `LineItemForm.svelte`

New **Job** picker (typeahead against `/api/jobs/?status_not=completed,rejected,cancelled,work_complete`). Pre-filled when the page arrived with `?job`. Users can clear or change it for any line.

Informational hint when the user picks a PLI and a Job: if the job has exactly one unlinked pending Material for that PLI, show "Will link to pending Material #123 (qty 10)." Purely informational — the resolver runs server-side.

### `PurchaseOrderDetail.svelte`

- **Line item inline edit row** (draft POs only, consistent with existing edit rules) gains a **Job** picker. The rest of the edit row's fields (qty, price, description) remain draft-only.
- **"Change Job" action per line** (available on issued, partly received, and received-in-full POs, not draft) — a separate button that opens a small modal with a Job picker. This exists because the job field's mutability is gated on Material state (pending), not PO status. On a draft PO, users change the job via the inline edit row; on non-draft POs, they use this action as long as the linked Material is still pending. Hidden when the linked Material is consumed or when the PO is cancelled.
- On saving a change to the `job` field (either path): if the line has a linked Material, show a modal confirm dialog:

  > **This line is linked to a Material on JOB-XXXX (qty N).**
  > Is the Material still needed on JOB-XXXX?
  > [ Keep on JOB-XXXX ] [ Delete it ] [ Cancel ]

  The PATCH includes `sever_decision`.

- Same modal is shown on:
  - **Cancel Line** — when the line has a linked pending Material. Replaces the current simple prompt.
  - **Cancel PO** — one consolidated modal listing every affected Material across all lines, each with keep/delete radio. Submit sends `sever_decisions`.
  - **Delete PO** (draft) — same consolidated modal.

### Other existing pages

No changes to receive flow dialogs. Receipt already works; Material creation is a side effect the user discovers by navigating to the Job page after receiving.

---

## Edge cases

**First receipt whose resolver step 2 would have matched earlier but the Material has since been consumed:** Resolver re-runs at receipt. Pending requirement fails, falls to step 3, new Material created. Consumed Material is untouched.

**Reverse-receipt when linked Material was restocked out of existence** (non-expense-bound, qty dropped to 0, Material deleted — FK cleared via `SET_NULL`): proceed with QOH reversal only. HistoryEntry notes the state.

**Reverse-receipt when linked Material is consumed:** raise.

**Sever with consumed Material:** raise.

**"Order this" arriving at PO-new with a stale `material` param** (Material was consumed or reassigned since the user clicked): show an error toast, continue with the job-only flow, do not pre-fill the line.

**Deleting a draft PO with linked Materials:** UI collects sever decisions in a consolidated modal (same component as cancel-PO). Backend accepts `sever_decisions` dict.

**Concurrent receipt attempts on the same line:** `select_for_update` on the line and its Material serializes.

**Line with `job` set but resolver deferred (no match at save time, no receipt yet), then user edits `job` to a new job:** No linked Material exists → sever is a no-op → update job → re-run resolver on the new job. All automatic.

---

## Testing

### Automated tests (TDD)

**Service layer — `tests/inventory/`:**
- `MaterialService.link_to_po_line` validates job match, pending state, unlinked state, existing-link state.
- `MaterialService.sever` with `keep` and `delete` decisions, including earmark backout verification.
- `MaterialService.resolve_link_for_po_line` — covers all three precedence branches (pre-linked, exactly-one claim, zero/multiple/consumed defer).

**Service layer — `tests/purchasing/`:**
- `add_line_item` with explicit `material_id` — explicit link path.
- `add_line_item` with `job` only — resolver path (each branch).
- `update_line_item` changing `job` on draft: no-material, pending-with-keep, pending-with-delete, consumed-raises, missing-sever-raises.
- `update_line_item` clearing `job` on draft: same matrix.
- `change_line_job` on issued/partly-received PO: pending-keep, pending-delete, consumed-raises, cancelled-PO-raises, missing-sever-raises.
- `update_line_item` on non-draft PO with non-job fields: still raises draft-only error.
- `receive_items` with `job` set:
  - No prior Material → creates + links + earmark.
  - Prior Material (step 1 linked) → bump quantity + earmark.
  - Prior Material (step 2 claimed) → same.
  - Overage on inventoried line → QOH += full, Material caps, earmark caps, excess goes to general inventory (check `qty_available`).
  - Overage on non-inventoried PLI → Material caps, no QOH change.
  - Overage on PLI-less → Material caps, no QOH change.
  - Receipt of 0 → skipped.
- `reverse_receipt` with linked Material: pending full undo → Material deleted; pending partial undo → Material qty reduced, earmark backed out; consumed → raises; FK null (restocked away) → proceeds QOH only.
- `cancel_line_item` with linked Material: keep, delete, consumed-raises, missing-decision-raises.
- `cancel_po` with mixed lines (linked + unlinked): per-line decisions applied.
- `delete_po` (draft): same.

**API layer — `tests/api/purchasing/`:**
- `POST .../line-items/` with `job`, `task`, `material_id` — successful link + validation errors for mismatched job, consumed, already-linked.
- `PATCH .../line-items/:lid/` changing `job` requires `sever_decision`.
- `cancel-line-item` and `cancel/` require `sever_decision(s)` as appropriate.
- `DELETE` draft PO with linked Materials requires `sever_decisions`.
- `receive/` and `receive-all/` produce the expected Material + QOH + earmark outcomes end-to-end.

**Fixture updates:** `unit_test_data.json` may need a pending Material on an existing test Job to cover the "Order this" flow and resolver step 2. Add if not present.

### Manual verification script

Run each scenario end-to-end with the dev server and Vite proxy. Verify via UI where noted, and via `python manage.py shell` for earmark/QOH spot checks where noted.

**Prereqs:** Logged-in user with `can_manage_financials`. Seed data via `./scripts/seed_data.sh`. Have at least one Job in `approved` or `submitted` status with tasks. Have at least one vendor Business with a Contact. Have at least one inventoried PLI (`is_inventoried=True`) and one non-inventoried PLI.

**Scenario 1: "Order this" for an inventoried Material, happy path.**
1. Navigate to Job JOB-XXXX.
2. Populate the Job from an Estimate or WorkTemplate so pending Materials appear (use an inventoried PLI).
3. In the Materials section, find a pending Material. Note its qty. Click **Order**.
4. Expect to land on `#/purchase-orders/new?job=X&material=Y`. Header shows "For job JOB-XXXX". First line-item form is pre-filled with the Material's PLI, description, qty, units, purchase_price.
5. Pick a vendor Business + Contact. Submit.
6. Expect the draft PO detail to appear with one line item. The Job column on the line shows JOB-XXXX.
7. Back on JOB-XXXX, verify the original Material row now shows "Ordered on PO-XXXX · Draft". The Order button is gone.
8. Return to the PO, click **Issue & Send** or **Mark as Issued**.
9. Click **Receive All**. Confirm.
10. Back on JOB-XXXX, verify the Material's qty is unchanged (we ordered the full planned qty), state is still pending, badge now reads "Ordered on PO-XXXX · Received in Full".
11. Via shell: confirm QOH for the PLI increased by qty, `Earmark` for (PLI, JOB-XXXX) equals the Material's qty, `qty_available` unchanged for other jobs.

**Scenario 2: "Create PO for this job", adding job-linked and unlinked lines.**
1. Navigate to Job JOB-XXXX.
2. Click **Create PO for this job**. Land on `#/purchase-orders/new?job=X`.
3. Create the draft PO (pick vendor). Add three line items:
   - **Line A:** manual entry, with Job defaulting to JOB-XXXX. Inventoried PLI the job does NOT already have as a Material.
   - **Line B:** manual entry, clear the Job on this line (unlinked). Same inventoried PLI as Line A.
   - **Line C:** manual entry, Job defaults to JOB-XXXX. PLI-less, description "Outside machining".
4. Issue. Receive All.
5. Back on JOB-XXXX, verify:
   - New pending Material for Line A's PLI, qty = line qty, unit_cost = line price, linked to Line A.
   - New pending Material for Line C, PLI null, description "Outside machining", qty = line qty, linked to Line C.
   - No Material corresponding to Line B (it was unlinked from the job).
6. Via shell: QOH for Line A's PLI increased by (Line A qty + Line B qty). Earmark for Line A's PLI on JOB-XXXX equals Line A qty only.

**Scenario 3: Receipt overage on an inventoried line.**
1. Create a PO for a job-linked inventoried line. Line qty = 10.
2. Issue.
3. Use **Receive Items** and record qty_received = 12 on that line.
4. Verify PO line shows qty_received = 12. PO status auto-transitions to `received_in_full`.
5. On the Job, the Material qty is 10 (capped). Via shell: QOH bumped by 12. Earmark on (PLI, Job) is 10. Available for other jobs: +2.

**Scenario 4: Partial receipts bump the same Material.**
1. Create a PO for a job-linked inventoried line. Line qty = 10.
2. Issue.
3. Receive 3 via **Receive Items**. On the Job, Material qty = 3, state pending.
4. Receive 5. Material qty = 8. Same Material row (same id).
5. Receive 2. Material qty = 10.
6. Via shell: one Material row throughout; QOH incremented by 3 + 5 + 2 = 10 across the three events; earmark matches Material qty at each step.

**Scenario 5: Reverse-receipt, pending Material.**
1. Start from Scenario 1 after Receive All, before any consumption.
2. On the PO detail, click **Reverse Receipt** on the line.
3. Confirm.
4. Back on JOB-XXXX, verify the Material is deleted (row gone). Via shell: QOH back to pre-receipt value. Earmark for (PLI, Job) absent or zero.

**Scenario 6: Reverse-receipt after consumption is blocked.**
1. Start from Scenario 1 after Receive All.
2. Via UI or shell, consume the Material on the Job (mark a task complete, or call `MaterialService.consume`).
3. On the PO detail, click **Reverse Receipt**.
4. Expect an error message: "Cannot reverse receipt; linked Material has been consumed. Restock first."
5. PO and Material states unchanged.

**Scenario 7: Reassign a line's job on a draft PO — delete.**
1. On JOB-A's Materials, use "Order this" on a pending Material to create a draft PO with one line explicitly linked. Verify the draft PO has the line with `job=JOB-A` and a linked Material.
2. On the draft PO detail, open the inline edit row on that line and change Job to JOB-B.
3. Expect the sever dialog: "This line is linked to a Material on JOB-A (qty N). Is the Material still needed on JOB-A?" Pick **Delete it**.
4. Verify: PO line's job is now JOB-B. The Material on JOB-A is gone. Earmark backed out. No Material on JOB-B yet (will create on first receipt).
5. Issue. Receive All. Verify a new Material appears on JOB-B, linked to the line.

**Scenario 8: Reassign a line's job on a draft PO — keep.**
1. Same setup as Scenario 7 step 1 (a new draft PO with a line linked to a Material on JOB-A).
2. Edit the line's Job to JOB-B. Pick **Keep on JOB-A**.
3. Verify: PO line's job is JOB-B. The Material on JOB-A is still there, pending, with `po_line_item=null`. Earmark on (PLI, JOB-A) unchanged.
4. Issue. Receive All. Verify a new Material appears on JOB-B, linked to the line. The JOB-A Material is untouched.

**Scenario 8b: Reassign a line's job on an issued PO via the "Change Job" action.**
1. Create a draft PO with one line linked to a Material on JOB-A (via "Order this"). Issue the PO without receiving.
2. On the issued PO detail, the inline edit row does not appear, but a **Change Job** button is shown on the line (because the linked Material is still pending).
3. Click **Change Job**, pick JOB-B, pick **Delete it** in the sever dialog.
4. Verify: line's job is JOB-B, JOB-A's Material is deleted with earmark backed out.
5. Confirm the button is hidden after a subsequent Receive All and consume (Material becomes consumed → no further reassignment allowed).

**Scenario 9: Cancel a whole PO with mixed linked/unlinked lines.**
1. Setup:
   - JOB-B has a pending Material M2 (from a template/worksheet populate) for some inventoried PLI X, unlinked.
   - Create a draft PO with three lines:
     - Line 1: use "Order this" on a Material M1 on JOB-A (explicit link).
     - Line 2: manual entry with `job = JOB-B` and `price_list_item = X`. Expect the resolver to claim M2 via step 2 (verify: M2 now shows `po_line_item = Line 2`).
     - Line 3: manual entry with no job.
2. Issue the PO (draft POs are deleted, not cancelled — we need issued to exercise Cancel PO).
3. On the PO detail, click **Cancel PO**.
4. Expect a consolidated modal listing M1 and M2, each with Keep / Delete radios.
5. Pick Delete for M1 and Keep for M2. Submit.
6. Verify: PO cancelled. M1 deleted, its earmark backed out. M2 still on JOB-B, `po_line_item=null`, earmark unchanged. Line 3 unaffected.

**Scenario 10: "Order this" on a Material that's already ordered.**
1. From Scenario 1 after creating the PO (still draft).
2. Return to JOB-XXXX's Material row. Verify the **Order** button is hidden; the "Ordered on PO-XXXX · Draft" badge is shown.
3. Attempt to call the order endpoint manually via curl with the same Material. Expect a 400 with a clear message.

**Scenario 11: Non-inventoried PLI and PLI-less lines — no stock impact.**
1. Create a PO with:
   - Line A: PLI is non-inventoried, job = JOB-XXXX.
   - Line B: PLI-less, job = JOB-XXXX.
2. Issue. Receive All.
3. On JOB-XXXX, verify Materials appear for both lines with quantities = line qty.
4. Via shell: no InventoryAdjustment rows. No QOH change on any PLI. No Earmark rows.

### What to watch during manual testing

- PO status transitions stay correct with overage and partial receipts.
- HistoryEntry timeline on the Job reflects receipt events (existing behavior — the PO's history is already shown; we're not adding new entries on the Job side for this round).
- Job Material rows repaint correctly after receipt/reverse without a hard reload.
- The resolver hint on `LineItemForm.svelte` matches actual server behavior (it's informational but users will trust it).

---

## Implementation notes

- The `Material.po_line_item` migration is additive (nullable FK), no data backfill needed.
- Existing `PurchaseOrderReceivingService.receive_items` already runs in `transaction.atomic` — extend inside the existing block rather than wrapping a new one.
- The orphaned `InventoryService.receive_po_line_item` helper can be deleted once its behavior is absorbed into the new receipt flow.
- Frontend: the consolidated severance dialog is a new component `MaterialSeverDialog.svelte`, used by PO detail for cancel-line, cancel-PO, delete-PO, and the line-edit job-change. Parameterize on a list of `{material_id, job_number, quantity, suggested_default}` and emit `{material_id: "keep"|"delete"}` on submit.
- The `sever_decision` backend parameters should accept the three edge cases cleanly: omitted + no linked Material = OK; omitted + linked Material = 400; present but no linked Material = ignored.

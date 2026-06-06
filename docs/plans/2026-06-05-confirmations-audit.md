# Confirmations audit — `confirm()` across the SPA

_added 2026-06-05 — addresses the LATER item "Audit confirmations site-wide — confirm only the irreversible."_

> **STATUS: executed 2026-06-06.** All 5 clean-win removals, all 4 judgment calls
> (resolved as remove), **plus** the wizard discard (user reclassified KEEP → REMOVE
> because the draft is easily remade on the page the user returns to) were applied —
> 10 `confirm()`s removed, 26 remain. Component-level removals (JobHeader, EmailActionPanel,
> WizardActions) got "fires without a prompt" tests; route-page removals were edited
> without new unit tests, per the route-pages-excluded-from-the-sweep convention. LATER
> entry deleted. Kept for the decision record.

## The rule (from CLAUDE.md → UI Decisions)

> Only prompt (`confirm()` / a modal) when an action is **irreversible or extremely
> arduous to undo** — deleting a persisted record, sending a document to a customer.
> **Never** confirm an action that's exactly undoable by another local action (editing
> a field, toggling, reordering, adding/removing a draft line that can be re-added or
> removed). A reversible action just does the thing.

Precedent already set on the change-orders branch: `confirm()` was removed from the CO
line/deliverable edits (Change / Delete-of-a-draft-delta / Undo / New) because each is
exactly undoable by another local action.

## Method

Grepped `frontend/src` for `confirm(`. Found **36 sites**. For each, classified the
guarded action as reversible / irreversible / arduous-to-undo by checking whether a
reverse path (opposite endpoint, status transition back, re-add, restock, reverse-receipt)
exists in the app. Reversibility findings were verified against the backend services.

## Summary

- **27 KEEP** — irreversible (deletes of persisted records, sends to customer, one-way
  status transitions, locks) or a genuine data-loss guard.
- **5 REMOVE** — a reverse action exists and is reachable in the UI.
- **4 JUDGMENT CALLS** — defensible either way; my lean + rationale given below.

The REMOVE + JUDGMENT set is what the LATER item is really about; the 27 KEEP sites are
listed for completeness so the audit is closed, not partial.

---

## REMOVE — reversible, undo path exists (recommend deleting the `confirm()`)

| # | Site | Action | Why reversible |
|---|------|--------|----------------|
| 1 | `components/jobs/JobHeader.svelte:102` | Release job to floor (approved → in_progress) | State machine allows `in_progress ↔ on_hold`; releasing is undoable by putting the job back on hold (`JobHeader.svelte:18-28`, `apps/jobs/services.py` transitions). |
| 2 | `components/email/EmailActionPanel.svelte:22` | Disassociate email from job/PO/bill | Just clears an FK; the "Link existing" action re-associates immediately (`EmailActionPanel.svelte:61-90`, `apps/api/email/views.py:78-112`). |
| 3 | `routes/worksheets/WorksheetDetailPage.svelte:216` | Send all unclaimed atoms to estimate as 1:1 lines | Creates line items on a **draft** estimate; each is deletable afterward via the normal line-item delete. |
| 4 | `routes/change-orders/ChangeOrderDetailPage.svelte:495` | Start a new change order (seed draft) | The created CO is a draft, trivially discardable via the existing discard action (`ChangeOrderDetailPage.svelte:483`). |
| 5 | `routes/jobs/JobTaskListPage.svelte:211` | Consume this material | `restock()` restores quantity to inventory and is offered as a sibling action right next to Consume (`JobTaskListPage.svelte:220-231`, `apps/inventory/services.py` consume/restock). |

These five are the clean wins: each has a symmetric, one-action reverse already in the UI.

---

## JUDGMENT CALLS — defensible either way

| # | Site | Action | My lean | Rationale |
|---|------|--------|---------|-----------|
| 6 | `routes/purchaseorders/PurchaseOrderDetailPage.svelte:235` | Receive all remaining items | **REMOVE (weak)** | By the letter of the rule it's reversible — `reverse_receipt()` exists and is reachable in the UI (`PurchaseOrderDetailPage.svelte:304-320`, `apps/purchasing/services.py`). But it's a bulk inventory commitment (touches `qty_on_hand` for every line), so a speed-bump is defensible. Keep if the team treats inventory events as weighty; otherwise remove. |
| 7 | `routes/invoices/InvoiceDetailPage.svelte:55` | Delete invoice line item | **REMOVE** | A draft-document line item — the exact case the CO precedent removed. Nuance: re-adding requires retyping the line's values, so it's not *exactly* undoable like a toggle. Recommend remove for consistency with CO, **assuming** the delete is only offered on draft/unsent invoices (verify the gate). |
| 8 | `routes/estimates/EstimateDetailPage.svelte:139` | Delete estimate line item | **REMOVE** | Same as #7 (draft estimate line). Same retype nuance + same draft-only assumption. |
| 9 | `routes/purchaseorders/PurchaseOrderDetailPage.svelte:209` | Delete PO line item | **REMOVE** | Same as #7 (draft PO line). Same nuance/assumption. |

For #7–#9, the cleanest end state is to remove the three `confirm()`s **and** confirm
each delete is only reachable while the parent document is editable/draft (it should be).
If any of these can fire on a finalized/sent document, keep the confirm there.

---

## KEEP — irreversible, send-to-customer, lock, or genuine data-loss guard

Listed so the audit is complete. No change recommended.

**Deletes of persisted records:**
- `components/TaskTemplateManager.svelte:134` — delete work template
- `components/RateSchemeManager.svelte:154` — delete rate scheme
- `components/time/TimeEditModal.svelte:127` — delete shift / time entry
- `routes/worksheets/WorksheetDetailPage.svelte:130` — delete plan task
- `routes/worksheets/WorksheetDetailPage.svelte:167` — delete plan material
- `routes/worksheets/WorksheetDetailPage.svelte:252` — delete worksheet (cascades)
- `routes/worksheets/PlanTaskDetailPage.svelte:122` — delete material
- `routes/jobs/JobTaskListPage.svelte:160` — delete task
- `routes/jobs/TaskDetailPage.svelte:225` — delete material
- `routes/jobs/TaskDetailPage.svelte:267` — delete material
- `routes/purchaseorders/PurchaseOrderDetailPage.svelte:158` — delete PO ("cannot be undone")
- `routes/jobs/JobShipmentsPage.svelte:153` — discard a **persisted** shipment + its items
- `routes/expenses/ExpenseListPage.svelte:74` — delete expense (also voids the QBO Purchase)
- `components/wizards/WizardActions.svelte:12` — discard draft (deletes the draft estimate/invoice and releases its claimed atoms)

**One-way status transitions (no reverse path in app):**
- `components/tasks/TaskActions.svelte:126` — cancel task (no un-cancel)
- `routes/jobs/JobTaskListPage.svelte:170` — cancel task (same endpoint)
- `components/expenses/UserReimbursementPanel.svelte:114` — reject expense (no un-reject)
- `routes/expenses/ExpenseListPage.svelte:64` — reject expense (same)
- `routes/estimates/EstimateDetailPage.svelte:41` — revise estimate (supersession is one-way)
- `routes/jobs/JobTaskListPage.svelte:298` — mark all work complete — **arduous-to-undo**: the state machine technically allows `work_complete → in_progress`, but completion can trigger downstream logic (invoicing, shipment), so a true reversal is messy. Keep.

**Locks / sends / external side effects:**
- `components/email/DocumentSendForm.svelte:49` — send email to customer (irreversible send)
- `components/QBOConnectionCard.svelte:28` — disconnect QBO (reconnect = full re-OAuth)
- `routes/change-orders/ChangeOrderDetailPage.svelte:455` — mark CO sent (locks line items)
- `routes/change-orders/ChangeOrderDetailPage.svelte:470` — accept/reject CO (moves job to approved)
- `routes/change-orders/ChangeOrderDetailPage.svelte:483` — discard CO ("cannot be undone")
- `routes/jobs/JobShipmentsPage.svelte:123` — mark shipment picked up (locks the shipment)

**Data-loss guard (not an action confirm — different category, keep):**
- `routes/jobs/JobShipmentsPage.svelte:122` — "you have unsaved cell changes" before marking
  picked up. This guards loss of *local unsaved edits*, which is exactly what a confirm is
  for; not subject to the reversible-action rule.

---

## Recommended plan

1. **Remove** the 5 clean-win `confirm()`s (REMOVE table, #1–#5). Each reverse action
   already exists in the UI, so the affordance just becomes "do the thing."
2. **Decide** the 4 judgment calls (#6–#9):
   - #7–#9 (line-item deletes): recommend remove to match the CO precedent, after confirming
     they're only offered on draft documents.
   - #6 (receive-all): pick based on how weighty inventory events should feel.
3. **Leave** the 27 KEEP sites as-is.

When acted on, update the LATER entry's _Done when_ (or delete it) and note the convention
holds. Each removed `confirm()` should get / keep a component test asserting the action
fires without a prompt (several of these components already have tests).

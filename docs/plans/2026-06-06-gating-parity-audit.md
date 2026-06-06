# Frontend ↔ Backend Permission-Gating Parity Audit

_2026-06-06. Addresses the LATER item "Audit frontend ↔ backend permission gating for parity."_

> **STATUS: executed 2026-06-06.** Added `frontend/src/stores/permissions.js` (per-atom
> derived stores `canManageJobs/Financials/Time/Config`, honoring `is_superuser`) and
> routed the mismatched gates through it. All 7 over-permissive findings fixed
> (invoice Send → `canManageFinancials`; task add-manual/edit/delete/reorder/assign →
> `canManageJobs`; contact/business edit/delete/tags + form pages → `canManageJobs`, with
> a read-only tag list for non-managers). **The cancel-task finding (#8) was resolved the
> OPPOSITE way from this audit's tentative suggestion** — see its updated entry. Shipments
> left intentional (above). Component-level fixes got tests; route-page fixes follow the
> route-pages-excluded convention. Touched files also had their hand-rolled atom
> derivations swapped to the store. Full migration of the remaining *already-correct*
> inline derivations is a follow-up.

This audit walks every permission-gated mutating action in the Svelte SPA and compares
the frontend visibility condition against the permission atom the action's endpoint
**actually** enforces in the DRF viewset (`get_permissions()` / `permission_classes` /
function-view decorators in `apps/api/**/views.py`, plus `apps/api/permissions.py`).
Backend atoms were verified against the viewset code, not the design doc. The recurring
failure mode is a frontend gate that is **broader** than the endpoint (button shown to a
user the backend rejects → 403) or **narrower** (button hidden from a user the backend
would allow).

## Summary

- **Actions checked:** 42
- **Matches:** 32
- **Over-permissive mismatches (button shown → 403):** 8
- **Over-restrictive mismatches (button hidden, backend would allow):** 1
- **Defensive (no pre-gate; relies on backend 403):** 1 (QBO card — acceptable)

The over-permissive findings cluster in two areas: (1) the **invoice Send** link (the
known example), and (2) the entire **task-management + contact/business-edit** surface,
where buttons are gated on status/lock flags (`!jobLocked`, callback-present) rather than
on `can_manage_jobs`. A worker without `can_manage_jobs` currently sees Add/Edit/Delete/
Assign/Reorder affordances throughout the task list, task detail, and contact/business
detail pages, all of which 403.

## Parity table

| action (page) | frontend gate (file:line) | endpoint | backend atom (file:line) | verdict |
|---|---|---|---|---|
| Send/Resend Invoice (InvoiceDetailPage) | `canEditInvoice` = jobs OR financials (`routes/invoices/InvoiceDetailPage.svelte:21`, gate at `:142`) | `POST /api/invoices/{id}/send/` | `CanManageFinancials` only (`invoicing/views.py:25`) | **OVER-PERMISSIVE** |
| Edit line items / add / delete (InvoiceDetailPage) | `canManageFinancials && draft` (`InvoiceDetailPage.svelte:29`) | invoice line-item CRUD | `CanManageFinancials` (`invoicing/views.py:25`) | match |
| Create Invoice (JobDetail) | `canManageJobs \|\| canManageFinancials` (`components/jobs/JobDetail.svelte:424`) | `POST /api/jobs/{id}/start-invoice-wizard/` and `POST /api/invoices/` | jobs OR financials (`jobs/views.py:55-57`, `invoicing/views.py:24`) | match |
| Send/Resend Estimate (EstimateDetailPage) | `canManageJobs` (`routes/estimates/EstimateDetailPage.svelte:205,208`) | `POST /api/estimates/{id}/send/` | `CanManageJobs` (`estimates/views.py:34`) | match |
| Revise Estimate (EstimateDetailPage) | `canManageJobs` (`:211`) | `POST /api/estimates/{id}/revise/` | `CanManageJobs` (`estimates/views.py:34`) | match |
| Estimate status change (EstimateDetailPage) | `canManageJobs` (`:188`) | `PATCH /api/estimates/{id}/` | `CanManageJobs` (`estimates/views.py:34`) | match |
| Create Estimate (JobDetail) | `canManageJobs` (`JobDetail.svelte:301`) | `POST /api/estimates/` | `CanManageJobs` (`estimates/views.py:34`) | match |
| Create Worksheet (JobDetail) | `canManageJobs` (`JobDetail.svelte:554`) | `POST /api/est-worksheets/` | `CanManageJobs` (`worksheets/views.py:29`) | match |
| Copy tasks from worksheet (JobDetail) | `canManageJobs` (`JobDetail.svelte:831`) | `POST /api/jobs/{id}/copy-from-worksheet/` | `CanManageJobs` (`jobs/views.py:58`) | match |
| New change order (JobDetail) | `canManageJobs` (`JobDetail.svelte:673`) | `POST /api/change-orders/` | `CanManageJobs` (`change_orders/views.py:41`) | match |
| Create PO (JobDetail / lists) | `canManageFinancials` (`JobDetail.svelte:1164`, `PurchaseOrderListPage.svelte:48`) | `POST /api/purchase-orders/` | `CanManageFinancials` (`purchasing/views.py:37`) | match |
| Order material → PO (JobDetail) | `canManageFinancials` (`JobDetail.svelte:973`) | navigates to PO create (financials) | `CanManageFinancials` (`purchasing/views.py:37`) | match |
| Worksheet edit / plan-task CRUD (WorksheetDetailPage, PlanTaskDetailPage) | `canManageJobs && editable` (`routes/worksheets/WorksheetDetailPage.svelte:38`, `PlanTaskDetailPage.svelte:34`) | worksheet `tasks`/`plan-materials` + plan-task `materials` | `CanManageJobs` (`worksheets/views.py:29`, `plan_tasks/views.py:44`) | match |
| Worksheet delete (WorksheetDetailPage) | `canManageJobs && editable && deletable` (`:248`) | `DELETE /api/est-worksheets/{id}/` | `CanManageJobs` (`worksheets/views.py:29`) | match |
| Change-order edits (ChangeOrderDetailPage, ~13 gates) | `canManageJobs && isDraft` (`routes/change-orders/ChangeOrderDetailPage.svelte:50,663…`) | CO + CO line-item mutations | `CanManageJobs` (`change_orders/views.py:41`) | match |
| Issue / Send / Resend / Cancel / Edit / Delete PO + line items (PurchaseOrderDetail) | `canManageFinancials` (+status) (`components/purchaseorders/PurchaseOrderDetail.svelte:168,174,181,204,271`) | PO mutations + `send`/`issue`/`cancel` | `CanManageFinancials` (`purchasing/views.py:37`) | match |
| Receive All / Receive Items / Cancel Line / Reverse Receipt (PurchaseOrderDetail) | `canReceive` = status only, **no perm** (`PurchaseOrderDetail.svelte:50,177,284,288`) | `receive`, `receive-all`, `cancel-line-item`, `reverse-receipt` | `IsAuthenticated` (`purchasing/views.py:30-34`) | match (both authenticated-only) |
| Bill mutations / send-to-qbo (Bill pages) | `canManageFinancials` | Bill CRUD + `send-to-qbo` | `CanManageFinancials` (`purchasing/views.py:396`) | match |
| Email → Job: create/link/disassociate (EmailActionPanel) | `canManageJobs` (`components/email/EmailActionPanel.svelte:48`) | `link_to_job`, `create_job_from_email`, `unlink_from_job` | `CanManageJobs` (`email/views.py:116,203,122`) | match |
| Email → PO/Bill: create/link/disassociate (EmailActionPanel) | `canManageFinancials` (`EmailActionPanel.svelte:69`) | `link_to_po`/`unlink_from_po`/`create_po_from_email`/`link_to_bill`/`unlink_from_bill` | `CanManageFinancials` (`email/views.py:128,135,152,140,147`) | match |
| Reply / Reply All (EmailActionPanel) | none (`EmailActionPanel.svelte:41,44`) | `POST /api/emails/{id}/reply/` | `IsAuthenticated` (`email/views.py:394`) | match |
| Settings save (SettingsPage) | sidebar `can_manage_config` (`components/Sidebar.svelte:75`) | `PATCH /api/settings/`, `units` | `CanManageConfig` (`templates_config/views.py:217,255`) | match |
| Template CRUD (templates pages) | sidebar `can_manage_config` | work/task template + AC mutations | `CanManageConfig` (`templates_config/views.py:35,108,132`) | match |
| User admin (UserDetailPage perms/activate/reset) | reached only via config-gated nav (`routes/users/UserDetailPage.svelte:100`) | `users` viewset | `CanManageConfig` (`users/views.py:27`) | match |
| QBO connect/disconnect (QBOConnectionCard) | **no pre-gate**; hides on 403 (`components/QBOConnectionCard.svelte:16`) | `/api/qbo/*` | `CanManageConfig` (`apps/qbo/views.py:91…`) | match (defensive) |
| Rate scheme CRUD | config-gated nav | rate-schemes viewset | `CanManageConfig` (`rate_schemes/views.py:29`) | match |
| Job status change / edit / duplicate (JobHeader) | `canManageJobs` (`components/jobs/JobHeader.svelte:119,120,128`) | job `update`, status actions, `duplicate` | `CanManageJobs` (`jobs/views.py:58`) | match |
| Job edit/create-worksheet/duplicate route guards | `{:else if !canManageJobs}` block (`JobEditPage.svelte:84`, `CreateWorksheetPage.svelte:80`, `DuplicateJobPage.svelte:57`) | job mutations | `CanManageJobs` | match |
| Expense submit (ExpenseForm) | none — any authenticated worker | `POST /api/expenses/` | `IsAuthenticated` (`expenses/views.py:21`) | match |
| Expense edit/delete/reject/retry-sync | `canManageFinancials` lists/detail | expense mutations | `CanManageFinancials` (`expenses/views.py:23`) | match |
| Reimbursement create/delete/retry-sync | `canManageFinancials` nav (`PurchaseOrderListPage`/reimbursement pages) | reimbursement viewset | `CanManageFinancials` (`reimbursements/views.py:28`) | match |
| Task start/stop/complete/block/unblock (TaskActions) | shown to all authenticated (`components/tasks/TaskActions.svelte:49-53`) | `start-work`/`stop-work`/`complete`/`block`/`unblock` | `IsAuthenticated` (`tasks/views.py:27`) | match |
| Task **cancel** (TaskActions) | `isManager` = `can_manage_jobs` (`TaskActions.svelte:54,57,142`) | `POST /api/tasks/{id}/cancel/` | `IsAuthenticated` (`tasks/views.py:27`) | **OVER-RESTRICTIVE** |
| Task material consume/restock/draw-more/assign + edit (TaskDetailPage, TaskTree) | no perm gate (`routes/jobs/TaskDetailPage.svelte:407,421`; `components/TaskTree.svelte:215-220`) | material actions + task-material CRUD | `IsAuthenticated` (`inventory/views.py:47`, `tasks/views.py:27`) | match |
| Add Subtask (TaskDetailPage / TaskTree) | no perm gate (`TaskDetailPage.svelte:455`, `TaskTree.svelte:183`) | `POST /api/tasks/{id}/subtasks/` | `IsAuthenticated` (`tasks/views.py:27`) | match |
| Record actual qty (TaskDetailPage) | no perm gate (`:364`) | `PATCH /api/tasks/{id}/actual-qty/` | `IsAuthenticated` (`tasks/views.py:301`) | match |
| Add Task **From Template** (JobTaskListPage / WorkItemForm) | `!jobLocked` only (`routes/jobs/JobTaskListPage.svelte:321`) | `POST /api/jobs/{id}/add-from-template/` | `IsAuthenticated` (`jobs/views.py:47`) | match |
| **Add Manual Task** (JobTaskListPage / WorkItemForm) | `!jobLocked` only (`JobTaskListPage.svelte:322`; posts `jobs/{id}/tasks/` at `WorkItemForm.svelte:229`) | `POST /api/jobs/{id}/tasks/` | `CanManageJobs` (`jobs/views.py:50-54`) | **OVER-PERMISSIVE** |
| **Edit task** (TaskTree, TaskDetailPage; WorkItemForm) | `!jobLocked` / ungated (`TaskTree.svelte:179`, `TaskDetailPage.svelte:314`; patches `jobs/{id}/tasks/{tid}/` at `WorkItemForm.svelte:208`) | `PATCH /api/jobs/{id}/tasks/{tid}/` | `CanManageJobs` (`jobs/views.py:58`, mixin `task_detail`) | **OVER-PERMISSIVE** |
| **Delete task** (TaskTree del; JobTaskListPage) | `!jobLocked` + `canDelete` (`TaskTree.svelte:180`; `JobTaskListPage.svelte:162`) | `DELETE /api/jobs/{id}/tasks/{tid}/` | `CanManageJobs` (`jobs/views.py:58`) | **OVER-PERMISSIVE** |
| **Reorder tasks** (TaskTree ▲▼) | `!jobLocked` only (`TaskTree.svelte:187`; `JobTaskListPage.svelte:279`) | `POST /api/jobs/{id}/reorder-tasks/` | `CanManageJobs` (`jobs/views.py:58`) | **OVER-PERMISSIVE** |
| **Assign task** (TaskTree, TaskDetailPage) | `!readonly && !isTerminal` only (`TaskTree.svelte:167`; `TaskDetailPage.svelte:340`) | `POST /api/tasks/{tid}/assign/` | `CanManageJobs` (`jobs/board_views.py:69`) | **OVER-PERMISSIVE** |
| Reassign task (schedule TaskQuickCard) | `canManageJobs` (`components/schedule/TaskQuickCard.svelte:173`) | `POST /api/tasks/{tid}/assign/` | `CanManageJobs` (`jobs/board_views.py:69`) | match |
| Board drag-assign / add worker (JobBoard WorkerColumns) | `canManage` = `can_manage_jobs` (`routes/jobs/JobBoardPage.svelte:61`, `components/board/WorkerColumns.svelte:13`) | `POST /api/tasks/{tid}/assign/` | `CanManageJobs` (`jobs/board_views.py:69`) | match |
| Mark Work Complete (JobTaskListPage) | `canManageJobs` (`JobTaskListPage.svelte:325`) | `POST /api/jobs/{id}/work-complete/` | `CanManageJobs` (`jobs/views.py:58`) | match |
| Contact/Business **Edit + Delete** (ContactDetail, BusinessDetail) | none — buttons render whenever callbacks set (`components/contacts/ContactDetail.svelte:212-216`, `BusinessDetail.svelte:192-196`) | contact/business `update`/`destroy` | `CanManageJobs` (`contacts/views.py:28,179`) | **OVER-PERMISSIVE** |
| Contact/Business tag add/remove + set-default (ContactDetail/BusinessDetail) | none (`TagEditor` at `ContactDetail.svelte:127`, `BusinessDetail.svelte:80`) | `add-tag`/`remove-tag`/`set-default-contact` | `CanManageJobs` (`contacts/views.py:28,179`) | **OVER-PERMISSIVE** |
| Contact/Business edit **form pages** | no `canManageJobs` route guard (`routes/contacts/ContactFormPage.svelte`, `BusinessFormPage.svelte`) | contact/business `create`/`update` | `CanManageJobs` (`contacts/views.py:28,179`) | **OVER-PERMISSIVE** |
| Add note on job/contact/business (HistoryPanel) | none | `notes` actions | `IsAuthenticated` (`jobs/views.py:45`, `contacts/views.py:26`) | match |
| Shipments: add/save/pick-up/discard (JobShipmentsPage) | none — all authenticated (`routes/jobs/JobShipmentsPage.svelte:296,331,337`) | shipment CRUD + `pick-up` + items | `IsAuthenticated` (`deliverables/views.py:126`) | match (see note) |

## Mismatches (detail + fix)

### Over-permissive (frontend shows it → backend 403)

1. **Send/Resend Invoice — InvoiceDetailPage.** Gate `canEditInvoice` = `can_manage_jobs OR can_manage_financials` (`routes/invoices/InvoiceDetailPage.svelte:21`, used at `:142`). The endpoint `POST /api/invoices/{id}/send/` requires `can_manage_financials` only (`invoicing/views.py:25`). _Symptom:_ a jobs-only user sees "Send Invoice", clicks it, lands on the send page, and the send POST 403s. _Fix:_ gate the Send link on `canManageFinancials`, not `canEditInvoice`.

2. **Add Manual Task — JobTaskListPage.** Button gated only on `!jobLocked` (`routes/jobs/JobTaskListPage.svelte:322`); `WorkItemForm` posts to `POST /api/jobs/{id}/tasks/` which requires `can_manage_jobs` (`jobs/views.py:50-54`). Note the sibling "Add Task From Template" posts to a different endpoint that IS `IsAuthenticated` — so the two buttons sitting next to each other have different real permissions. _Symptom:_ worker without `can_manage_jobs` sees "Add Manual Task", fills the form, save 403s. _Fix:_ wrap the Add Manual Task button in `{#if canManageJobs}`.

3. **Edit task — TaskTree + TaskDetailPage.** `edit` button gated on `!jobLocked` (`components/TaskTree.svelte:179`) and ungated on TaskDetailPage (`routes/jobs/TaskDetailPage.svelte:314`); `WorkItemForm` patches `PATCH /api/jobs/{id}/tasks/{tid}/` requiring `can_manage_jobs`. _Symptom:_ worker sees "edit task", save 403s. _Fix:_ gate the edit affordance on `canManageJobs` (pass a `canManage` prop into `TaskTree`).

4. **Delete task — TaskTree / JobTaskListPage.** `del` gated on `!jobLocked` + `canDelete()` (`TaskTree.svelte:180`); `DELETE /api/jobs/{id}/tasks/{tid}/` requires `can_manage_jobs`. _Symptom:_ worker sees "del", 403 on click. _Fix:_ add `canManageJobs` to the gate.

5. **Reorder tasks — TaskTree ▲▼.** Gated on `!jobLocked` (`TaskTree.svelte:187`); `POST /api/jobs/{id}/reorder-tasks/` requires `can_manage_jobs`. _Symptom:_ worker sees move arrows, 403 on click. _Fix:_ gate on `canManageJobs`.

6. **Assign task — TaskTree + TaskDetailPage.** "assign" gated only on `!readonly && !isTerminal` (`TaskTree.svelte:167`, `TaskDetailPage.svelte:340`); `POST /api/tasks/{tid}/assign/` requires `can_manage_jobs` (`jobs/board_views.py:69`). Inconsistent with the schedule card and the board, which both correctly gate on `canManageJobs`. _Symptom:_ worker sees "assign", 403 on save. _Fix:_ gate on `canManageJobs`.

7. **Contact / Business Edit + Delete + tags + set-default.** `ContactDetail`/`BusinessDetail` render Edit/Delete whenever the callbacks are set (always) (`components/contacts/ContactDetail.svelte:212-216`, `BusinessDetail.svelte:192-196`); `TagEditor` and set-default are likewise ungated. All map to `update`/`destroy`/`add-tag`/`remove-tag`/`set-default-contact`, which require `can_manage_jobs` (`contacts/views.py:28,179`). The edit **form pages** also lack the `{:else if !canManageJobs}` guard that JobEditPage has. _Symptom:_ worker without `can_manage_jobs` sees Edit/Delete/tag controls and a fully usable edit form; every save/delete 403s. _Fix:_ thread a `canManageJobs` prop into the detail components and guard the form pages (mirror `JobEditPage.svelte:84`).

### Over-restrictive (frontend hides it → backend would allow)

8. **Cancel task — TaskActions.** The Cancel button is shown only when `isManager` (`can_manage_jobs`) (`components/tasks/TaskActions.svelte:54,57,142`), but `POST /api/tasks/{id}/cancel/` is `IsAuthenticated` (`tasks/views.py:27` — the flat `TaskViewSet` has no per-action override). So a non-manager worker is denied a button the backend would honor.

   **RESOLVED 2026-06-06 — loosened the frontend (NOT the backend), reversing this audit's
   tentative "tighten the backend" suggestion.** On closer reading, the task viewset
   docstring is explicit and deliberate: *"Any authenticated user can drive task lifecycle
   (start, complete, block, unblock, **cancel**)... These are worker operations, not
   manager-only"* (`apps/api/tasks/views.py:21-24`). So `IsAuthenticated` on cancel is the
   intended design, and the frontend was the side out of step. Fix applied: `TaskActions`
   now shows Cancel to any authenticated user (`base.cancel = true`, `isManager` removed),
   matching `TaskTree`'s long-standing behavior (its cancel was always worker-visible —
   during this pass it was briefly gated on `canManageJobs` and then reverted to keep cancel
   a worker op). Backend unchanged. _If the shop actually wants cancel to be manager-only,
   that's a one-line backend change (`cancel`-specific `CanManageJobs` branch) plus
   re-gating both frontend surfaces — flagged for the user._

## Note on the Shipments page

`JobShipmentsPage.svelte` exposes add/save/pick-up/discard to **any authenticated user**
with no permission gate, and that happens to match the backend, because
`ShipmentViewSet.permission_classes = [IsAuthenticated]` for every action
(`deliverables/views.py:126`) — unlike the sibling `DeliverableViewSet`, which requires
`CanManageJobs` for mutations (`deliverables/views.py:34`).

**RESOLVED 2026-06-06 — intentional, no change.** The asymmetry is by design:
fulfillment is shop-floor work, so any authenticated user must be able to create a
shipment, add items, and mark it picked up. Shipment management is purposely *not*
parallel to deliverable management (which gates the agreed *scope* on `can_manage_jobs`).
The ungated frontend page is therefore correct. Recorded durably in
`docs/designs/jobs-tasks-and-worksheets.md` §12.1.

## Would a shared per-atom derived helper prevent recurrence?

Yes — and the spread of these findings argues strongly for it. Today every component
re-derives its own `canManageJobs` / `canManageFinancials` from
`$user.permissions.includes(...)` inline (20+ duplicated derivations across the files
above), and the misses are exactly the components that **forgot to derive one at all**
(TaskTree, ContactDetail, BusinessDetail, the contact/business form pages, the Add Manual
Task button). A single `frontend/src/stores/permissions.js` exporting derived stores —
`canManageJobs`, `canManageFinancials`, `canManageTime`, `canManageConfig` (each already
honoring `is_superuser`) — would (a) remove the boilerplate, (b) make "is this gated?"
greppable and reviewable, and (c) give a natural home for endpoint-shaped helpers like
`canSendInvoice = canManageFinancials` so the invoice-Send class of bug can't recur. It
won't by itself fix a component that forgets to apply the gate, but it makes the omission
obvious in review and removes the temptation to hand-roll a subtly-wrong condition
(e.g. `canEditInvoice` reused for Send). Pair it with a convention that every mutating
button names the atom it requires.

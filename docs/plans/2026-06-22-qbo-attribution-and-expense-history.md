# QBO Attribution & Expense History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the three QBO money records proper audit — domain history for `Expense` (via the `@history` decorator), adjunct lifecycle history for `BillPayment`→Bill and `Reimbursement`→Expense (imperative), and "who triggered it" on every QBO sync via `QBOSyncLog.triggered_by` — all attributed automatically from the existing request-user context, no actor threading. Also de-duplicate the two retry-sync endpoints (whose delete-branch `None` guard was just fixed per-endpoint in `c4d7b17f`) into one shared mixin.

**Note on the 500:** the delete-retry 500 the final review flagged is **already fixed** (commit `c4d7b17f` added the `if result is None` guard to both endpoints, with regression tests). Task 1 is therefore a **de-dup refactor** of that now-duplicated guard, not a bug fix.

**Architecture:** Attribution is uniform: `@history` already reads `request.user` from a request-scoped `HistoryContext` (set by middleware, resolved at write time); we make `record_action` (a new thin wrapper over `record_history` for `entry_type='action'`) and `QBOSyncLog`'s `log_sync` read the **same** context via a new `current_request_user()` accessor. So nothing threads an `actor`. Domain history: `Expense` gets `@history(exclude=[pk, qbo_*])` writing to a new `ExpensesHistory` partition (qbo_* excluded keeps the QBO seam); `BillPayment` and `Reimbursement` are adjuncts, so their lifecycle events are written imperatively to their primary's timeline (`object_type='bill'` / `object_type='expense'`) via `record_action`. QBO-mechanics audit stays in `QBOSyncLog` (the swap-the-backend seam).

**Tech Stack:** Django 5.2, DRF, MySQL, Svelte 5 SPA (frontend only lightly touched).

## Global Constraints

- **Never write the dev DB.** `makemigrations` only; the human runs `migrate`. Tests use the auto-created test DB. One test process at a time.
- **TDD.** Constants not literals. No `QuerySet.update()`/`bulk_*` where `save()` normalizes.
- **All DELETE API responses return 200 + JSON.** A refused delete returns 400.
- **QBO mock boundary:** `QBOService.get_client`/`log_sync` + SDK `.save`/`.get`/`.delete`.
- **The QBO seam:** QBO-coupled facts (qbo ids, sync status, errors, "who hit QBO") live only in `QBOSyncLog`; domain facts live in the history partitions. `@history(exclude=...)` must exclude the qbo_* fields so sync churn never enters a domain timeline.
- After behavior changes, update `docs/designs/quickbooks-integration.md` + the history docs (Task 7).

## Background (decisions already made in discussion)

- `@history` auto-tracks **create + field-update** (not delete), routes by `object_type = ClassName.lower()` to a partition (`_domain_models()` registry), and auto-attributes via `HistoryContext`. The three records here are **created and then sit ~forever**; deletes are rare — so **no `post_delete` extension** and **no decorator `anchor` param** this pass (both recorded in LATER as future ideas).
- Only `Expense` gets the decorator (it has a real edit/status lifecycle). `BillPayment`→Bill and `Reimbursement`→Expense are adjunct→primary, which the decorator can't express, so they stay imperative — the correct tool, not a workaround.
- `Reimbursement`'s effect (member expense `submitted↔reimbursed`) is **auto-captured** once `Expense` is decorated; the imperative entries add human context ("Reimbursed in batch #N: $X").

---

## File Structure

**Modified (backend):**
- `apps/api/mixins.py` — new `QBORetrySyncMixin` (the retry-sync action).
- `apps/api/expenses/views.py`, `apps/api/reimbursements/views.py` — use the mixin (fixes the 500).
- `apps/core/history.py` — `current_request_user()` accessor; `record_action()` helper; register `'expense'`/`'reimbursement'` → `ExpensesHistory`.
- `apps/core/models.py` — new `ExpensesHistory(HistoryEntryBase)` partition.
- `apps/qbo/models.py` — `QBOSyncLog.triggered_by` (nullable User FK).
- `apps/qbo/services.py` — `log_sync` auto-sets `triggered_by` from `current_request_user()`.
- `apps/expenses/models.py` — `@history(exclude=[...])` on `Expense`.
- `apps/expenses/services.py` — `ReimbursementService.create_batch`/`delete` write `record_action(object_type='expense', …)` per member; drop now-vestigial `actor` params where convenient.
- `apps/purchasing/services.py` — `record_payment` → `record_action`; add `record_action` to `update_payment`/`delete_payment` (`object_type='bill'`).

**Migrations:** `apps/core/migrations/` (ExpensesHistory table), `apps/qbo/migrations/` (triggered_by), `apps/expenses/migrations/` (none — `@history` adds no fields).

**Docs:** `docs/designs/quickbooks-integration.md`, the history reference doc (`architecture-and-conventions.md` or `data-constraints.md`), `docs/designs/LATER.md`.

---

## Phase 1 — Close the blocker + the standard helper

### Task 1: `QBORetrySyncMixin` (de-dup the retry-sync endpoints)

The delete-retry 500 is **already fixed** (commit `c4d7b17f`): both the Expense and Reimbursement `retry-sync` actions now capture the return and `if result is None: return {message}` (mirroring the bill-payment action). That guard is now **duplicated across the two endpoints** — extract it into one mixin so it can't drift. Behavior is unchanged; this is a pure refactor that should keep the existing (already-passing) regression tests green.

**Files:** `apps/api/mixins.py` (add mixin); `apps/api/expenses/views.py`, `apps/api/reimbursements/views.py` (use it); tests `tests/test_api_expenses.py`, `tests/test_api_reimbursements.py`.

**Interfaces:**
- `QBORetrySyncMixin` provides a `retry_sync` DRF action (`detail=True`, POST, `url_path='retry-sync'`). It resolves the target via `self.get_object()`, calls a configurable service retry (`self.retry_service_call(obj, request)`), and: on `DjangoValidationError` → 400; on `None` return → `Response({'message': self.retry_deleted_message})`; else 200 `Response(self.get_serializer(obj).data)` after `obj.refresh_from_db()`.

- [ ] **Step 1: Confirm the existing regression tests pass** — `c4d7b17f` already added delete-op retry tests to `tests/test_api_expenses.py` and `tests/test_api_reimbursements.py` (delete-pending retry → 200 + `'message'` + row gone). Run `python manage.py test tests.test_api_expenses tests.test_api_reimbursements -v 1` to confirm green BEFORE refactoring — these are the safety net for the de-dup.
- [ ] **Step 2: Implement the mixin** in `apps/api/mixins.py`:

```python
class QBORetrySyncMixin:
    """Shared `retry-sync` action: dispatch to a service retry that may return
    None (delete branch) and shape the response uniformly."""
    retry_deleted_message = 'Deleted.'

    def retry_service_call(self, obj, request):
        raise NotImplementedError

    @action(detail=True, methods=['post'], url_path='retry-sync', url_name='retry-sync')
    def retry_sync(self, request, pk=None):
        obj = self.get_object()
        try:
            result = self.retry_service_call(obj, request)
        except DjangoValidationError as e:
            return Response({'detail': e.messages[0]}, status=400)
        if result is None:
            return Response({'message': self.retry_deleted_message})
        obj.refresh_from_db()
        return Response(self.get_serializer(obj).data)
```

Wire the two viewsets: remove their hand-written `retry_sync` actions, mix in `QBORetrySyncMixin`, set `retry_deleted_message`, and implement `retry_service_call` (`ExpenseService.retry(expense=obj, actor=request.user)` / `ReimbursementService.retry(batch=obj, actor=request.user)`). (Bill payments keep their own action — it's a nested route with a different signature.)

- [ ] **Step 3: Run → still green** (behavior unchanged). Green gate: `python manage.py test tests.test_api_expenses tests.test_api_reimbursements -v 1`.
- [ ] **Step 4: Commit** `refactor(api): extract QBORetrySyncMixin; de-dup the retry-sync delete-branch guard`.

### Task 2: `current_request_user()` + `record_action()`

**Files:** `apps/core/history.py`; test `tests/test_history_helpers.py` (create).

**Interfaces:**
- `current_request_user() -> User|None` — the authenticated user on the active `HistoryContext`'s request, else `None`.
- `record_action(object_type, object_id, action, user=None) -> entry` — `record_history(entry_type='action', …, user=user or current_request_user(), changes={'_action': action})`.

- [ ] **Step 1: Write the failing test** — with a `HistoryContext` set holding a request whose `.user` is an authenticated user, `current_request_user()` returns that user and `record_action(...)` writes an `entry_type='action'` row with `_action` set and that user; with no context, both return/attribute `None`.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** both in `apps/core/history.py` (mirror the middleware's `request.user.is_authenticated` resolution for `current_request_user`). Do NOT migrate any existing call site yet.
- [ ] **Step 4: Run → pass.** `python manage.py test tests.test_history_helpers -v 1`.
- [ ] **Step 5: Commit** `feat(core): record_action helper + current_request_user accessor`.

---

## Phase 2 — QBO attribution seam

### Task 3: `QBOSyncLog.triggered_by`, auto-attributed

**Files:** `apps/qbo/models.py` (field), `apps/qbo/services.py` (`log_sync`), `apps/api/qbo/` serializer for the failures view if it surfaces it; migration `apps/qbo/migrations/`; tests `tests/test_qbo_sync_log_attribution.py` (create).

**Interfaces:** `QBOSyncLog.triggered_by` (FK to `core.User`, null=True, on_delete=SET_NULL). `QBOService.log_sync(...)` sets `triggered_by = current_request_user()` when not explicitly provided (add an optional `triggered_by=None` param; if falsy, fall back to `current_request_user()`).

- [ ] **Step 1: Write the failing test** — with a `HistoryContext` holding an authenticated request, `QBOService.log_sync(...)` writes a row whose `triggered_by` is that user; with no context, `triggered_by` is `None`. (Mock nothing but the context.)
- [ ] **Step 2: Run → fail** (no field / not set).
- [ ] **Step 3: Implement** the field + `makemigrations qbo` (AddField, nullable — no data migration) + `log_sync` reads `current_request_user()`. Every existing `log_sync` caller (save_and_log, delete_and_log, the push/void methods) is unchanged — attribution is automatic.
- [ ] **Step 4: Run → pass.** Also run `tests.test_qbo_bill_payment_push tests.test_qbo_expense_push tests.test_qbo_sync_failures` to confirm no regression.
- [ ] **Step 5: Commit** `feat(qbo): QBOSyncLog.triggered_by auto-attributed from request context`.

---

## Phase 3 — Domain history

### Task 4: `@history` on `Expense` + `ExpensesHistory` partition

**Files:** `apps/core/models.py` (partition), `apps/core/history.py` (register), `apps/expenses/models.py` (decorator); migration `apps/core/migrations/`; tests `tests/test_expense_history.py` (create). Optional: `apps/api/expenses/views.py` (`history` action) + serializer.

**Interfaces:** `ExpensesHistory(HistoryEntryBase)` (`db_table='expenses_history'`). `_domain_models()` maps `'expense'` and `'reimbursement'` → `ExpensesHistory`. `Expense` decorated `@history(exclude=[<pk>, 'qbo_id', 'qbo_sync_status', 'qbo_sync_error', 'qbo_pending_op'])` (confirm the pk name from the model — likely `id`; also exclude any auto timestamp fields).

- [ ] **Step 1: Write the failing tests** —
  - Editing an expense's `amount` writes an `ExpensesHistory` audit row (`object_type='expense'`, `object_id=pk`, `changes` has the amount diff), attributed to the request user (set a `HistoryContext`).
  - A status flip `submitted→reimbursed` writes a row.
  - A **qbo-only** save (`mark_failed`/`mark_synced`) writes **NO** row (qbo_* excluded → empty diff).
  - `history_model_for('expense')` returns `ExpensesHistory`.
- [ ] **Step 2: Run → fail** (no partition / `record_history` raises "no table for 'expense'").
- [ ] **Step 3: Implement** the partition + registration + decorator. `makemigrations core` (creates `expenses_history`; the decorator adds no model fields). Confirm the qbo-only-save case produces no entry (the `exclude` covers all four qbo fields).
- [ ] **Step 4 (optional): `GET /api/expenses/{id}/history/`** action + `HistoryEntrySerializer`, `IsAuthenticated`, mirroring the bill `history` action — so it's queryable. (A SPA panel is out of scope; note it.)
- [ ] **Step 5: Run → pass.** `python manage.py test tests.test_expense_history tests.test_expense_service tests.test_qbo_expense_push -v 1`.
- [ ] **Step 6: Commit** `feat(expenses): Expense @history audit (ExpensesHistory partition; qbo_* excluded)`.

### Task 5: BillPayment lifecycle → Bill (imperative, via `record_action`)

**Files:** `apps/purchasing/services.py`; tests `tests/test_bill_payment_service.py`.

- [ ] **Step 1: Write the failing tests** — recording, editing, and deleting a payment each write an `entry_type='action'` `PurchasingHistory` row with `object_type='bill'`, `object_id=bill.pk`, the right `_action` sentence, attributed to the request user (set a context). (Today only create writes one.)
- [ ] **Step 2: Run → fail** (no edit/delete entries).
- [ ] **Step 3: Implement** — migrate `record_payment`'s existing `record_history(entry_type='action', object_type='bill', …)` to `record_action(object_type='bill', object_id=bill.pk, action=history_action)` (drop the manual `user=` — context attributes; keep the enriched sentence). Add `record_action('bill', payment.bill_id, 'Payment edited: $X (…)')` in `update_payment` and `record_action('bill', payment.bill_id, 'Payment deleted: $X')` in `delete_payment` (before the row is removed, so `bill_id` is still available).
- [ ] **Step 4: Run → pass.** `python manage.py test tests.test_bill_payment_service tests.test_bill_payment_api -v 1`.
- [ ] **Step 5: Commit** `feat(purchasing): complete BillPayment lifecycle history on the bill timeline via record_action`.

### Task 6: Reimbursement lifecycle → Expense (imperative, via `record_action`)

**Files:** `apps/expenses/services.py`; tests `tests/test_reimbursement_service.py`.

- [ ] **Step 1: Write the failing tests** — `create_batch` writes a `record_action(object_type='expense', object_id=e.pk, 'Reimbursed in batch #N: $total to <worker>')` on EACH member expense; `delete` (unwind) writes `'Reimbursement unwound (batch #N)'` on each. Attributed to the request user. (The bare `submitted↔reimbursed` status diff is already auto-captured by Task 4's decorator — assert these add the human action line on top.)
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** the per-member `record_action` calls in `create_batch` and `delete`.
- [ ] **Step 4: Run → pass.** `python manage.py test tests.test_reimbursement_service tests.test_api_reimbursements -v 1`.
- [ ] **Step 5: Commit** `feat(expenses): reimbursement lifecycle history on the member expenses via record_action`.

---

## Phase 4 — Gate + docs

### Task 7: Full-suite gate + docs

- [ ] **Step 1: Full backend + frontend suites** — `python manage.py test --keepdb` (all OK), `cd frontend && npm run test:run && npm run build`. Grep for any stale `actor`-threading you chose to drop and confirm nothing references it.
- [ ] **Step 2: Docs** —
  - `docs/designs/quickbooks-integration.md`: `QBOSyncLog.triggered_by` (auto from request context); the attribution model (domain history vs the QBO seam); the `QBORetrySyncMixin`.
  - The history reference doc (`architecture-and-conventions.md`): the new `ExpensesHistory` partition + `'expense'`/`'reimbursement'` routing; the `record_action` convention (and that adjunct→primary history uses it); that `@history` excludes qbo_* to hold the seam.
  - `docs/designs/LATER.md`: the three deferred items were **already added 2026-06-22** — (a) drop `request.user` threading from imperative history / default to the request context; (b) a decorator `anchor=` param to route an adjunct's auto-history to its primary; (c) `post_delete` support in `@history`. Confirm they're present/accurate; no new note needed.
- [ ] **Step 3: Commit** `docs: QBO attribution, ExpensesHistory partition, record_action convention; defer anchor/post_delete`.

---

## Self-Review notes (gaps to watch during execution)

- **The qbo_* exclude is load-bearing for the seam.** Task 4 must exclude all four (`qbo_id`, `qbo_sync_status`, `qbo_sync_error`, `qbo_pending_op`) — a `mark_synced`/`mark_failed` save must produce **no** `ExpensesHistory` row. Test it explicitly.
- **Attribution is context-only — no actor threading.** `@history`, `record_action`, and `log_sync` all read `current_request_user()`. Non-request paths (poller, management commands, tests without a context) correctly attribute `None`. Don't reintroduce `actor=` params; drop the vestigial ones if convenient.
- **`delete_payment` must `record_action` BEFORE deleting** (needs `bill_id`), and after the QBO void decision (so a refused delete that raises doesn't leave a misleading "deleted" entry — put it on the success path).
- **Reimbursement double-entry:** the status diff (auto, Task 4) + the action line (Task 6) both appear on the expense timeline — that's intended (one machine-readable diff, one human sentence), not a duplicate to dedupe.
- **`ExpensesHistory` owns two object_types** (`expense`, `reimbursement`) but in practice everything writes `object_type='expense'` (reimbursement attaches to the expense). Registering `'reimbursement'` too is cheap insurance if a batch ever needs its own entry.
- The `QBORetrySyncMixin` covers expense + reimbursement; the bill-payment retry endpoint stays separate (nested route) and already handles `None`.

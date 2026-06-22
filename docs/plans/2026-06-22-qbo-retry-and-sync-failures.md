# QBO Retry & Sync-Failures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a `sync_failed` QBO record self-describing about *which* operation it owes (create / update / delete) via a stored `qbo_pending_op`, so retry re-runs the right verb — fixing the current bug where retry blindly create-pushes (silently no-ops a failed *update* and abandons a failed *delete*) — and surface all failures across the three money pushes (Expense, Reimbursement, BillPayment) in one place with retry-all.

**Architecture:** `QBOSyncable` gains `qbo_pending_op` (`''`/`create`/`update`/`delete`), written **only** by the orchestrator: `QBOSyncService.run_create`/`run_update`/`run_delete` each pass their verb into `mark_failed(error, op)`; `mark_synced` clears it. `run_resync` is renamed to **`run_update`** (it was the update-on-edit handler, never a retry). The three domain services (`ExpenseService`, `ReimbursementService`, `BillPaymentService`) are aligned onto one small sync-dispatch surface (`_push_create` / `_push_update` / `retry`), where `retry(record)` dispatches on `qbo_pending_op`. A cross-entity `GET /api/qbo/sync-failures/` aggregates the three types; the SPA lists them with per-row Retry + Retry-all, and the bill-payment row's misleading "— retry" text becomes a real button.

**Tech Stack:** Django 5.2, DRF, MySQL, `python-quickbooks`, Svelte 5 SPA (Vitest).

## Global Constraints

- **Never write to the dev DB.** `makemigrations` only; the human runs `migrate`. Tests use the auto-created test DB. Run **one** test process at a time (shared MySQL).
- **TDD.** Status/op via model constants, never string literals in app code.
- **No `QuerySet.update()`/`bulk_*`** where `save()` normalizes — iterate + `.save()`.
- **All DELETE API responses return 200 + JSON.** A refused delete returns 400 (existing behavior — unchanged here).
- **QBO mock boundary:** mock `QBOService.get_client` / `log_sync` and the SDK object's `.save`/`.get`/`.delete`; never deeper.
- **`mark_failed` write must commit** on a refused delete (outside any aborted `transaction.atomic()`) — this already holds in the three delete callers; do not regress it.
- Frontend gate = `npm run test:run` **and** `npm run build`, from `frontend/`.
- After behavior changes, update `docs/designs/quickbooks-integration.md` + `docs/ui-flows/QuickBooks-Sync.md` (Task 9).

## Vocabulary (lock this — the whole plan depends on it)

- **create / update / delete** — the three forward QBO operations. Each has one orchestrator (`run_create` / `run_update` / `run_delete`) and one `qbo_pending_op` value.
- **retry / resync** — re-attempting a *previously failed* sync, by dispatching on the stored `qbo_pending_op`. NOT an edit. (This is why `run_resync` is being renamed — it was the update-on-edit handler, a misnomer.)

---

## File Structure

**Modified (backend):**
- `apps/core/models.py` — `QBOSyncable`: add `qbo_pending_op` + constants; change `mark_failed(error, op)`; clear op in `mark_synced`.
- `apps/qbo/services.py` — `QBOSyncService`: rename `run_resync`→`run_update`; each orchestrator passes its verb to `mark_failed`.
- `apps/expenses/services.py` — `ExpenseService`: rename `_push_and_set_status`→`_push_create`, `_resync`→`_push_update`; add `retry`; `ReimbursementService`: add `_push_create`/`_push_update`/`retry`; both rewrite `retry_sync` to dispatch on `qbo_pending_op`.
- `apps/purchasing/services.py` — `BillPaymentService`: extract `_push_create`/`_push_update` from the inlined logic; add `retry`.
- `apps/api/purchasing/views.py` — new bill-payment `retry-sync` action.
- `apps/api/expenses/views.py`, `apps/api/reimbursements/views.py` — existing `retry-sync` actions now call the dispatching `retry` (no signature change).
- `apps/api/qbo/` — new `sync-failures` list + `retry-all` endpoints (or add to `apps/qbo/views.py` + `urls.py`).

**Modified (frontend):**
- `frontend/src/routes/bills/BillDetailPage.svelte` — the `sync_failed` cell becomes a Retry **button**.
- `frontend/src/routes/expenses/ExpenseListPage.svelte`, `frontend/src/components/expenses/UserReimbursementPanel.svelte` — existing retry buttons unchanged in shape (now hit the fixed dispatch).
- **New** `frontend/src/components/qbo/QBOSyncFailures.svelte` — the cross-entity failures panel (per-row Retry + Retry all), placed on `SettingsPage.svelte`.

**Migrations:** `apps/expenses/migrations/` (Expense + Reimbursement) and `apps/purchasing/migrations/` (BillPayment) — `AddField qbo_pending_op`. No data migration (default `''` is correct for existing rows; a stale `sync_failed` row would just retry as a create, which is the safe default).

**Docs:** `docs/designs/quickbooks-integration.md`, `docs/ui-flows/QuickBooks-Sync.md`, `docs/designs/LATER.md`.

---

## Phase 1 — The verb field + orchestrator

### Task 1: `qbo_pending_op` on `QBOSyncable`

**Files:**
- Modify: `apps/core/models.py` (`QBOSyncable`)
- Test: `tests/test_qbo_syncable_pending_op.py` (create)
- Migrations: `makemigrations expenses purchasing`

**Interfaces:**
- Produces on `QBOSyncable`: constants `OP_NONE=''`, `OP_CREATE='create'`, `OP_UPDATE='update'`, `OP_DELETE='delete'`; field `qbo_pending_op` (CharField 10, blank, default `''`, choices); `mark_failed(self, error, op)` (sets status=failed + error + op); `mark_synced(self, qbo_id)` (clears op).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_qbo_syncable_pending_op.py
from django.test import SimpleTestCase
from apps.purchasing.models import BillPayment  # a concrete QBOSyncable


class PendingOpTests(SimpleTestCase):
    def test_constants(self):
        self.assertEqual(BillPayment.OP_CREATE, 'create')
        self.assertEqual(BillPayment.OP_UPDATE, 'update')
        self.assertEqual(BillPayment.OP_DELETE, 'delete')

    def test_mark_failed_records_op(self):
        bp = BillPayment()
        bp.save = lambda *a, **k: None  # avoid DB
        bp.mark_failed('boom', BillPayment.OP_DELETE)
        self.assertEqual(bp.qbo_sync_status, BillPayment.SYNC_FAILED)
        self.assertEqual(bp.qbo_sync_error, 'boom')
        self.assertEqual(bp.qbo_pending_op, 'delete')

    def test_mark_synced_clears_op(self):
        bp = BillPayment()
        bp.save = lambda *a, **k: None
        bp.qbo_pending_op = 'update'
        bp.mark_synced('qbo-1')
        self.assertEqual(bp.qbo_sync_status, BillPayment.SYNC_SYNCED)
        self.assertEqual(bp.qbo_id, 'qbo-1')
        self.assertEqual(bp.qbo_pending_op, '')
```

- [ ] **Step 2: Run to verify it fails**

Run: `python manage.py test tests.test_qbo_syncable_pending_op -v 2`
Expected: FAIL — `OP_CREATE`/`qbo_pending_op` not defined; `mark_failed` takes one arg.

- [ ] **Step 3: Edit `QBOSyncable`**

In `apps/core/models.py`, add the constants + field and change the two methods:

```python
    OP_NONE = ''
    OP_CREATE = 'create'
    OP_UPDATE = 'update'
    OP_DELETE = 'delete'
    PENDING_OP_CHOICES = [
        (OP_CREATE, 'Create'),
        (OP_UPDATE, 'Update'),
        (OP_DELETE, 'Delete'),
    ]

    qbo_pending_op = models.CharField(
        max_length=10, blank=True, default='', choices=PENDING_OP_CHOICES)
```

```python
    def mark_synced(self, qbo_id):
        self.qbo_id = qbo_id
        self.qbo_sync_status = self.SYNC_SYNCED
        self.qbo_sync_error = ''
        self.qbo_pending_op = self.OP_NONE
        self.save(update_fields=['qbo_id', 'qbo_sync_status', 'qbo_sync_error', 'qbo_pending_op'])

    def mark_failed(self, error, op):
        self.qbo_sync_status = self.SYNC_FAILED
        self.qbo_sync_error = str(error)
        self.qbo_pending_op = op
        self.save(update_fields=['qbo_sync_status', 'qbo_sync_error', 'qbo_pending_op'])
```

- [ ] **Step 4: Create the migrations**

Run: `python manage.py makemigrations expenses purchasing`
Expected: an `AddField(qbo_pending_op)` migration for `expenses` (Expense + Reimbursement) and one for `purchasing` (BillPayment). No data migration. Do **not** run `migrate`.

- [ ] **Step 5: Run to verify pass**

Run: `python manage.py test tests.test_qbo_syncable_pending_op -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/core/models.py tests/test_qbo_syncable_pending_op.py apps/expenses/migrations/ apps/purchasing/migrations/
git commit -m "feat(qbo): add qbo_pending_op to QBOSyncable; mark_failed records the verb"
```

---

### Task 2: Rename `run_resync`→`run_update`; thread the verb through the orchestrators

**Files:**
- Modify: `apps/qbo/services.py` (`QBOSyncService`)
- Modify callers: `apps/purchasing/services.py:1008`, `apps/expenses/services.py:198,200`
- Test: `tests/test_qbo_sync_service.py` (extend — it exists)

**Interfaces:**
- Produces: `QBOSyncService.run_create` (on failure `record.mark_failed(e, OP_CREATE)`), `run_update` (renamed from `run_resync`; on failure `mark_failed(e, OP_UPDATE)`), `run_delete` (on failure `mark_failed(e, OP_DELETE)` + re-raise). All three reference `record.OP_*` constants.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_qbo_sync_service.py
def test_run_create_marks_failed_with_create_op(self):
    from apps.qbo.services import QBOSyncService
    rec = _FakeRecord()  # extend _FakeRecord with OP_* attrs + qbo_pending_op + 2-arg mark_failed
    QBOSyncService.run_create(rec, lambda: (_ for _ in ()).throw(ValueError('x')))
    self.assertEqual(rec.qbo_pending_op, 'create')

def test_run_update_marks_failed_with_update_op(self):
    from apps.qbo.services import QBOSyncService
    rec = _FakeRecord(); rec.qbo_id = 'q1'
    QBOSyncService.run_update(rec, lambda: (_ for _ in ()).throw(ValueError('x')))
    self.assertEqual(rec.qbo_pending_op, 'update')

def test_run_delete_marks_failed_with_delete_op_and_reraises(self):
    from apps.qbo.services import QBOSyncService
    rec = _FakeRecord(); rec.qbo_id = 'q1'
    with self.assertRaises(ValueError):
        QBOSyncService.run_delete(rec, lambda: (_ for _ in ()).throw(ValueError('x')))
    self.assertEqual(rec.qbo_pending_op, 'delete')
```

Extend `_FakeRecord` (in that file) so it has `OP_CREATE='create'`/`OP_UPDATE='update'`/`OP_DELETE='delete'`, a `qbo_pending_op` attr, and `mark_failed(self, error, op)` / `mark_synced(self, qbo_id)` that set `qbo_pending_op` accordingly.

- [ ] **Step 2: Run to verify it fails**

Run: `python manage.py test tests.test_qbo_sync_service -v 2`
Expected: FAIL — `run_update` undefined; `mark_failed` arity.

- [ ] **Step 3: Edit `QBOSyncService`**

Rename `run_resync`→`run_update` and pass the verb on every failure:

```python
    @staticmethod
    def run_create(record, push_callable):
        try:
            qbo_id = push_callable()
            if qbo_id:
                record.mark_synced(qbo_id)
            return qbo_id
        except Exception as e:  # noqa: BLE001
            logger.exception('QBO create sync failed for %r', record)
            record.mark_failed(e, record.OP_CREATE)
            return None

    @staticmethod
    def run_update(record, update_callable):
        try:
            update_callable()
            record.mark_synced(record.qbo_id)
        except Exception as e:  # noqa: BLE001
            logger.exception('QBO update sync failed for %r', record)
            record.mark_failed(e, record.OP_UPDATE)

    @staticmethod
    def run_delete(record, delete_callable):
        try:
            delete_callable()
        except Exception as e:  # noqa: BLE001
            record.mark_failed(e, record.OP_DELETE)
            raise
```

Update the docstring comment that says "run_create/run_resync, which swallow" → "run_create/run_update".

- [ ] **Step 4: Update the three callers**

- `apps/purchasing/services.py:~1008` (`update_payment`): `QBOSyncService.run_resync(` → `QBOSyncService.run_update(`.
- `apps/expenses/services.py:198,200` (`_resync`): both `run_resync` → `run_update`. (The method itself is renamed in Task 3; for now just fix the call names so the suite stays green.)

- [ ] **Step 5: Run tests**

Run: `python manage.py test tests.test_qbo_sync_service tests.test_bill_payment_qbo_lifecycle tests.test_expense_service tests.test_reimbursement_service -v 1`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/qbo/services.py apps/purchasing/services.py apps/expenses/services.py tests/test_qbo_sync_service.py
git commit -m "refactor(qbo): rename run_resync->run_update; orchestrators record the pending verb"
```

---

## Phase 2 — Align the domain services + retry dispatch

### Task 3: `ExpenseService` — align naming + dispatching retry

**Files:**
- Modify: `apps/expenses/services.py` (`ExpenseService`)
- Test: `tests/test_expense_service.py`, `tests/test_qbo_expense_push.py`

**Interfaces:**
- Produces: `ExpenseService._push_create(expense)` (was `_push_and_set_status`), `_push_update(expense)` (was `_resync` — keeps the personal→batch branch), `retry(expense, actor)` dispatching on `qbo_pending_op`; `retry_sync` delegates to `retry`. The `update` retry of a synced company expense now re-applies the update (no more create-push short-circuit).

- [ ] **Step 1: Write the failing test** — the load-bearing bug fix:

```python
# tests/test_qbo_expense_push.py — a company expense whose UPDATE failed must,
# on retry, actually re-run the UPDATE (not short-circuit to synced).
@patch('apps.qbo.services.QBOExpenseSyncService.update_expense')
@patch('apps.qbo.services.QBOExpenseSyncService.push_expense')
def test_retry_of_failed_update_calls_update_not_create(self, mock_push, mock_update):
    exp = self._company_expense(qbo_id='q1')  # helper: synced company expense
    exp.qbo_sync_status = Expense.SYNC_FAILED
    exp.qbo_pending_op = Expense.OP_UPDATE
    exp.save(update_fields=['qbo_sync_status', 'qbo_pending_op'])
    ExpenseService.retry(expense=exp, actor=self.user)
    mock_update.assert_called_once()
    mock_push.assert_not_called()
```

Plus a `test_retry_of_failed_delete_voids_and_removes` (op=delete → the expense is deleted on a successful void) and `test_retry_of_failed_create_pushes` (op=create / blank, no qbo_id → push_expense called).

- [ ] **Step 2: Run to verify it fails**

Run: `python manage.py test tests.test_qbo_expense_push -v 2`
Expected: FAIL — `ExpenseService.retry` undefined.

- [ ] **Step 3: Rename + add the dispatch**

Rename `_push_and_set_status`→`_push_create` and `_resync`→`_push_update` (update their call sites: `submit`/`_push_and_set_status` caller ~line 73 → `_push_create`; `update`'s `if expense.qbo_id: ExpenseService._resync(expense)` → `_push_update`). Add:

```python
    @staticmethod
    def retry(*, expense, actor):
        if expense.qbo_sync_status != Expense.SYNC_FAILED:
            raise ValidationError('Can only retry a sync that failed.')
        op = expense.qbo_pending_op
        if op == Expense.OP_DELETE:
            ExpenseService.delete(expense=expense, actor=actor)  # re-void + remove
            return None
        if op == Expense.OP_UPDATE:
            ExpenseService._push_update(expense)
        else:  # create (or blank → treat as create)
            ExpenseService._push_create(expense)
        expense.refresh_from_db()
        return expense

    # retry_sync kept as a thin alias for the existing endpoint name:
    @staticmethod
    def retry_sync(*, expense, actor):
        return ExpenseService.retry(expense=expense, actor=actor)
```

> Note: `_push_update` keeps its personal→batch branch (a personal expense's edit resyncs the BATCH). But a *personal* expense never carries its own `sync_failed` (the batch does), so `retry` on an Expense only ever sees a company expense — the `update` branch resyncs the expense itself. Leave `_push_update`'s branch intact; it's used by the edit path.

- [ ] **Step 4: Run tests**

Run: `python manage.py test tests.test_qbo_expense_push tests.test_expense_service -v 1`
Expected: PASS. (Update any test referencing `_push_and_set_status`/`_resync` by name to the new names.)

- [ ] **Step 5: Commit**

```bash
git add apps/expenses/services.py tests/test_qbo_expense_push.py tests/test_expense_service.py
git commit -m "refactor(expenses): align ExpenseService sync surface; retry dispatches on qbo_pending_op"
```

---

### Task 4: `ReimbursementService` — same alignment

**Files:** `apps/expenses/services.py` (`ReimbursementService`); tests `tests/test_reimbursement_service.py`.

**Interfaces:** `ReimbursementService._push_create(batch)`, `_push_update(batch)` (resync via `update_reimbursement`), `retry(batch, actor)` dispatching on `qbo_pending_op`; `retry_sync` delegates.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reimbursement_service.py
@patch('apps.qbo.services.QBOExpenseSyncService.update_reimbursement')
@patch('apps.qbo.services.QBOExpenseSyncService.push_reimbursement')
def test_retry_failed_update_calls_update(self, mock_push, mock_update):
    batch = self._batch(qbo_id='q1')
    batch.qbo_sync_status = Reimbursement.SYNC_FAILED
    batch.qbo_pending_op = Reimbursement.OP_UPDATE
    batch.save(update_fields=['qbo_sync_status', 'qbo_pending_op'])
    ReimbursementService.retry(batch=batch, actor=self.user)
    mock_update.assert_called_once()
    mock_push.assert_not_called()
```

Plus `test_retry_failed_delete_unwinds` (op=delete → batch deleted + expenses flipped to submitted on a successful void) and `test_retry_failed_create_pushes`.

- [ ] **Step 2: Run to verify it fails** — `python manage.py test tests.test_reimbursement_service -v 2` → FAIL (`retry` undefined).

- [ ] **Step 3: Implement** — extract `_push_create` (the `create_batch` post-commit push, ~line 326) and `_push_update` (`run_update(batch, update_reimbursement)`), and add `retry` mirroring Task 3 (delete → `ReimbursementService.delete(batch=..., actor=...)`; update → `_push_update`; else → `_push_create`). `retry_sync` delegates to `retry`. Have `create_batch` call `_push_create`.

- [ ] **Step 4: Run tests** — `python manage.py test tests.test_reimbursement_service tests.test_api_reimbursements -v 1` → PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/expenses/services.py tests/test_reimbursement_service.py
git commit -m "refactor(expenses): align ReimbursementService sync surface; retry dispatches on qbo_pending_op"
```

---

### Task 5: `BillPaymentService` — extract helpers + add `retry`

**Files:** `apps/purchasing/services.py` (`BillPaymentService`); tests `tests/test_bill_payment_service.py`, `tests/test_bill_payment_qbo_lifecycle.py`.

**Interfaces:** `BillPaymentService._push_create(payment)`, `_push_update(payment)` (extracted from the inlined `record_payment`/`update_payment` logic), `retry(payment_id)` dispatching on `qbo_pending_op`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bill_payment_qbo_lifecycle.py
@patch('apps.qbo.services.QBOBillSyncService.update_bill_payment')
@patch('apps.qbo.services.QBOBillSyncService.push_bill_payment')
def test_retry_failed_update_calls_update(self, mock_push, mock_update):
    pay = self._payment(qbo_id='q1')
    pay.qbo_sync_status = BillPayment.SYNC_FAILED
    pay.qbo_pending_op = BillPayment.OP_UPDATE
    pay.save(update_fields=['qbo_sync_status', 'qbo_pending_op'])
    BillPaymentService.retry(pay.pk)
    mock_update.assert_called_once()
    mock_push.assert_not_called()
```

Plus `test_retry_failed_delete_voids_and_removes` (op=delete → `delete_payment` re-run; payment gone on success) and `test_retry_failed_create_pushes`.

- [ ] **Step 2: Run to verify it fails** — FAIL (`retry`/`_push_create` undefined).

- [ ] **Step 3: Implement** — extract from the inlined code:

```python
    @staticmethod
    def _push_create(payment):
        from apps.qbo.services import QBOBillSyncService, QBOSyncService
        QBOSyncService.run_create(payment, lambda: QBOBillSyncService.push_bill_payment(payment))

    @staticmethod
    def _push_update(payment):
        from apps.qbo.services import QBOBillSyncService, QBOSyncService
        QBOSyncService.run_update(payment, lambda: QBOBillSyncService.update_bill_payment(payment))
```

Repoint `_push_to_qbo`/`record_payment` create path at `_push_create`, and `update_payment`'s `if payment.qbo_id: run_update(...) else: push_bill_payment(...)` at `_push_update` / `_push_create`. Add:

```python
    @staticmethod
    def retry(payment_id):
        from apps.purchasing.models import BillPayment
        payment = BillPayment.objects.get(pk=payment_id)
        if payment.qbo_sync_status != BillPayment.SYNC_FAILED:
            raise ValidationError('Can only retry a sync that failed.')
        op = payment.qbo_pending_op
        if op == BillPayment.OP_DELETE:
            BillPaymentService.delete_payment(payment_id)  # re-void + remove (raises if still failing)
            return None
        if op == BillPayment.OP_UPDATE:
            BillPaymentService._push_update(payment)
        else:
            BillPaymentService._push_create(payment)
        payment.refresh_from_db()
        return payment
```

- [ ] **Step 4: Run tests** — `python manage.py test tests.test_bill_payment_service tests.test_bill_payment_qbo_lifecycle tests.test_bill_payment_api -v 1` → PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/purchasing/services.py tests/test_bill_payment_service.py tests/test_bill_payment_qbo_lifecycle.py
git commit -m "refactor(purchasing): extract BillPaymentService push helpers; add retry dispatch"
```

---

## Phase 3 — API + frontend

### Task 6: Bill-payment `retry-sync` endpoint

**Files:** `apps/api/purchasing/views.py` (add a `retry-sync` action on the payment route); test `tests/test_bill_payment_api.py`.

**Interfaces:** `POST /api/bills/{id}/payments/{pid}/retry-sync/` → `BillPaymentService.retry(pid)`; `can_manage_financials`; 200 + serialized payment on success, 400 on a still-failing retry; for a `delete`-op retry that succeeds, returns `{'message': 'Payment deleted.'}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bill_payment_api.py
@patch('apps.qbo.services.QBOBillSyncService.push_bill_payment')
def test_retry_sync_endpoint(self, mock_push):
    from apps.purchasing.models import BillPayment
    pay = BillPayment.objects.create(
        bill=self.bill, amount=Decimal('10.00'), payment_date=timezone.now(),
        payment_account_id='35', qbo_sync_status=BillPayment.SYNC_FAILED,
        qbo_pending_op=BillPayment.OP_CREATE)
    resp = self.client.post(f'/api/bills/{self.bill.pk}/payments/{pay.pk}/retry-sync/')
    self.assertEqual(resp.status_code, 200)
    mock_push.assert_called_once()
```

- [ ] **Step 2: Run to verify it fails** — 404 (no route).

- [ ] **Step 3: Implement** — add the action (mirror the `payment_detail` action's permission + the existing expense `retry_sync` action's try/except → 400 shape). On `BillPaymentService.retry` returning `None` (delete branch) return the deleted-message body; else return the serialized payment.

- [ ] **Step 4: Run tests** — `python manage.py test tests.test_bill_payment_api -v 1` → PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/purchasing/views.py tests/test_bill_payment_api.py
git commit -m "feat(api): bill-payment retry-sync endpoint"
```

---

### Task 7: Cross-entity `GET /api/qbo/sync-failures/` + retry-all

**Files:** `apps/api/qbo/` (new views) or `apps/qbo/views.py` + `apps/qbo/urls.py`; service helper in `apps/qbo/services.py` (`QBOSyncFailureService`); test `tests/test_qbo_sync_failures.py` (create).

**Interfaces:**
- `QBOSyncFailureService.list_failures() -> list[dict]` — every `sync_failed` company `Expense`, `Reimbursement`, `BillPayment` as `{entity_type, id, label, amount, qbo_pending_op, qbo_sync_error}`.
- `GET /api/qbo/sync-failures/` (`can_manage_financials`) → `{'failures': [...]}`.
- `POST /api/qbo/sync-failures/retry-all/` (`can_manage_financials`) → iterates, calling each entity's `retry`; returns `{'retried': n, 'still_failing': m}`. Each retry is independent (one failure doesn't stop the rest).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_qbo_sync_failures.py — seed one sync_failed of each type, GET the
# list, assert all three appear with their entity_type + qbo_pending_op; then
# retry-all with the QBO push mocked to succeed and assert the count.
```

(Use the existing per-app fixtures/helpers to build one failed `Expense`, `Reimbursement`, `BillPayment`.)

- [ ] **Step 2: Run to verify it fails** — 404 / service missing.

- [ ] **Step 3: Implement** `QBOSyncFailureService.list_failures` (three querysets filtered on `qbo_sync_status=SYNC_FAILED`; for Expense restrict to company-paid — personal expenses never carry their own failure) + the two endpoints. retry-all dispatches by `entity_type` to `ExpenseService.retry` / `ReimbursementService.retry` / `BillPaymentService.retry`, each wrapped so one exception doesn't abort the loop.

- [ ] **Step 4: Run tests** — `python manage.py test tests.test_qbo_sync_failures -v 1` → PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/qbo/ apps/api/qbo/ tests/test_qbo_sync_failures.py
git commit -m "feat(qbo): cross-entity sync-failures list + retry-all"
```

---

### Task 8: Frontend — failures panel + real bill-payment retry button

**Files:**
- Create: `frontend/src/components/qbo/QBOSyncFailures.svelte` + `frontend/tests/QBOSyncFailures.test.js`
- Modify: `frontend/src/routes/SettingsPage.svelte` (mount the panel), `frontend/src/routes/bills/BillDetailPage.svelte` (the `sync_failed` cell → a Retry button)

**Interfaces:** `QBOSyncFailures.svelte` fetches `/api/qbo/sync-failures/`, lists rows (`label`, `qbo_pending_op`, `qbo_sync_error` in a tooltip), a per-row **Retry** posting to the right entity endpoint, and a **Retry all** posting to `/retry-all/`; reloads after each; surfaces errors via `errorMessage`.

- [ ] **Step 1: Write the component test**

```javascript
// frontend/tests/QBOSyncFailures.test.js — mock api.get to return 2 failures;
// assert both labels render and a Retry-all button exists; mock api.post and
// assert clicking Retry all calls /api/qbo/sync-failures/retry-all/ and reloads.
```

- [ ] **Step 2: Run to verify it fails** — component missing.

- [ ] **Step 3: Implement** the component; mount it on `SettingsPage` (financials/config visibility). In `BillDetailPage`, replace the static `<span>QBO sync failed — retry</span>` with a **button** wired to `POST /api/bills/{billId}/payments/{pid}/retry-sync/` then `load()` (surface errors via `errorMessage`); keep the `synced` indicator.

- [ ] **Step 4: Frontend gate** — `npm run test:run` AND `npm run build` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/qbo/QBOSyncFailures.svelte frontend/tests/QBOSyncFailures.test.js frontend/src/routes/SettingsPage.svelte frontend/src/routes/bills/BillDetailPage.svelte
git commit -m "feat(spa): QBO sync-failures panel + real bill-payment retry button"
```

---

### Task 9: Full-suite gate + docs

- [ ] **Step 1: Full backend + frontend suites** — `python manage.py test --keepdb` (all OK) and `cd frontend && npm run test:run && npm run build`. Grep for any leftover `run_resync` / `_resync` / `_push_and_set_status` in app code and fix.

- [ ] **Step 2: Docs** — in `docs/designs/quickbooks-integration.md`: document `qbo_pending_op` on `QBOSyncable`, the `run_resync`→`run_update` rename + the create/update/delete↔orchestrator↔verb mapping, the per-entity `retry` dispatch (and that it fixes the failed-update short-circuit), and the `sync-failures` list + retry-all. In `docs/ui-flows/QuickBooks-Sync.md`: add retry-flow steps (per-row retry on bill payments/expenses/reimbursements; the failures panel; that retry re-runs the *owed verb*). In `docs/designs/LATER.md`: close/replace the "failed-delete vs retry-sync" and "verb is lost" notes (now resolved); if customers/vendors/invoices-in-the-failures-view is still wanted, leave that as the remaining open item.

- [ ] **Step 3: Commit**

```bash
git add docs/
git commit -m "docs(qbo): qbo_pending_op retry model, run_update rename, sync-failures view; close ambiguity LATER items"
```

---

## Self-Review notes (gaps to watch during execution)

- **The load-bearing fix** is Task 3/4/5's `retry` dispatch: a failed *update* must call `update_X` (re-apply), NOT `push_X` (which short-circuits on `qbo_id` and silently marks synced). Each of those tasks has an explicit `mock_update.assert_called_once()` / `mock_push.assert_not_called()` test — do not let it regress to the old `_push_and_set_status` path.
- **`mark_failed` arity change** ripples to exactly three callers (the orchestrators). Any other caller is a bug — grep `mark_failed(` after Task 2.
- **Personal expenses never carry their own `sync_failed`** (their batch does), so the failures list filters Expense to company-paid and `retry` on an Expense only sees company expenses. Don't add personal expenses to the list.
- **Delete-retry deletes the record.** `retry` with `op='delete'` re-runs the full delete (void + local removal); on success the row disappears from the failures list. The endpoint/UI must handle a "deleted" outcome (not a serialized record).
- **`qbo_pending_op` is written only by the orchestrator** (via `mark_failed`/`mark_synced`). No service should set it by hand — that's what keeps it consistent with `qbo_id`/status.
- **Scope:** the failures view is the three `QBOSyncable` money pushes only. Customers/Vendors (Business `qbo_*_id`) and Invoices (bare `qbo_id`) are out — giving them the same base is a separate, larger decision (left in LATER if still wanted).

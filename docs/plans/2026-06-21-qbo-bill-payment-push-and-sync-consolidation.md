# QBO Bill-Payment Push & Sync Consolidation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the live QBO `BillPayment` push (create/update/void) inside the existing Minibini payment flow, and consolidate the QBO sync-state machinery shared by Expense, Reimbursement, and BillPayment into one abstract base + one orchestrator + one payment-account service. Also debug the always-failing reimbursement push and correct/record several docs.

**Architecture:** A new `QBOSyncable` abstract model base carries the three sync fields (`qbo_id`, `qbo_sync_status`, `qbo_sync_error`) plus `mark_synced`/`mark_failed`. A new `QBOSyncService` orchestrator wraps the push/resync try-except and calls those methods. A new `QBOPaymentAccountService` owns the `qbo_payment_accounts` config lookup. The per-entity QBO object builders (`Purchase` for expenses/reimbursements, `BillPayment` for bill payments) stay separate — only the shared scaffolding merges. A `<PaymentAccountSelect>` Svelte component is the reusable picker.

**Tech Stack:** Django 5.2, DRF, MySQL, `python-quickbooks` SDK, Svelte 5 SPA (Vitest).

## Global Constraints

- **Never write to the dev DB.** `makemigrations` is fine; **never** run `migrate`, `loaddata`, `shell` writes, or any DB-mutating script. Tests use a separate auto-created test DB. The human runs `migrate`.
- **TDD always:** failing test → verify it fails → minimal code → verify pass → commit.
- **Status constants, not string literals** (`BillPayment.SYNC_SYNCED`, never `'synced'`).
- **Document numbers only for new instances** — N/A here (no doc numbers added).
- **Line-item deletes** go through `LineItemService.delete_line_item_with_renumber` — N/A here.
- **No `QuerySet.update()`/`bulk_*`** for fields a `save()` normalizes — use per-instance `.save()`.
- **All DELETE API responses return 200 + JSON body**, never 204.
- **Money inputs:** send strings, normalize server-side via `Decimal(str(value))` (already done in `BillPaymentService._normalize_amount`).
- **QBO mock boundary:** tests mock at `QBOService.get_client` / `QBOService.log_sync`, never deeper in the SDK.
- **Config keys added to tests' `setUp` + fixtures.** The key `qbo_payment_accounts` already exists.
- After behavior changes, update the matching `docs/designs/` doc in the same session (handled by Task 14).
- Frontend tests: `cd frontend && npm run test:run` (never watch mode). Backend tests: `python manage.py test tests.<module>` — **only one test process at a time** (shared MySQL).

---

## File Structure

**New files:**
- `apps/core/models.py` — add `QBOSyncable` abstract base (neutral home importable by both `expenses` and `purchasing`).
- `frontend/src/components/qbo/PaymentAccountSelect.svelte` — reusable account picker.
- `frontend/tests/PaymentAccountSelect.test.js` — its unit test.

**Modified (backend):**
- `apps/qbo/services.py` — add `QBOPaymentAccountService`, `QBOSyncService`; rewrite `QBOBillSyncService.push_bill_payment` + add `update_bill_payment`/`void_bill_payment`; repoint expense/reimbursement pushes at the shared services; flip `qbo_payment_id`→`qbo_id` references.
- `apps/purchasing/models.py` — `BillPayment`: inherit `QBOSyncable`, rename `qbo_payment_id`→`qbo_id`, add `payment_account_id`.
- `apps/purchasing/services.py` — `BillPaymentService.record_payment`/`update_payment`/`delete_payment` wire the create/update/void sync.
- `apps/api/purchasing/serializers.py` — expose new fields; require `payment_account_id` when QBO connected.
- `apps/api/purchasing/views.py` — pass `payment_account_id` through the record-payment action.
- `apps/expenses/models.py` — `Expense` + `Reimbursement` inherit `QBOSyncable`; split Expense's fused status; rename Reimbursement's `status`→`qbo_sync_status`.
- `apps/expenses/services.py` — `_push_and_set_status`/`_resync`/`retry_sync` use `qbo_sync_status` + orchestrator.
- `apps/api/expenses/serializers.py`, `apps/api/reimbursements/serializers.py`, `apps/api/reimbursements/views.py` — field renames.

**Modified (frontend):**
- `frontend/src/components/RecordPaymentModal.svelte` — drop the `method` `<select>`, add the account picker.
- `frontend/src/routes/bills/BillDetailPage.svelte` — payments table shows account name + reference + sync state instead of `method`.
- `frontend/src/routes/expenses/ExpenseListPage.svelte`, `frontend/src/components/home/ExpensesList.svelte`, `frontend/src/components/expenses/UserReimbursementPanel.svelte` — `status`→`qbo_sync_status` for sync display/filter.

**Migrations:** new migrations under `apps/purchasing/migrations/` and `apps/expenses/migrations/` (created via `makemigrations`, including two data migrations). The human applies them.

**Docs:** `docs/designs/quickbooks-integration.md`, `docs/designs/materials-inventory-and-purchasing.md`, `docs/designs/LATER.md`.

---

## Phase 1 — Shared scaffolding

### Task 1: `QBOPaymentAccountService` (extract account lookup)

Pull the payment-account config access out of `QBOExpenseSyncService` into a standalone service both expenses and bill-payments call.

**Files:**
- Modify: `apps/qbo/services.py` (add class near top; repoint `QBOExpenseSyncService` private callers)
- Test: `tests/test_qbo_payment_account_service.py` (create)

**Interfaces:**
- Produces:
  - `QBOPaymentAccountService.load_accounts() -> list[dict]` — parsed `qbo_payment_accounts` JSON (`[]` if unset/blank).
  - `QBOPaymentAccountService.lookup(payment_account_id: str) -> dict` — the matching `{qbo_account_id, display_name, account_type}` dict, or raises `ValueError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_qbo_payment_account_service.py
import json
from django.test import TestCase
from apps.core.models import Configuration
from apps.qbo.services import QBOPaymentAccountService


class QBOPaymentAccountServiceTests(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': json.dumps([
                {'qbo_account_id': '35', 'display_name': 'Checking', 'account_type': 'Bank'},
                {'qbo_account_id': '42', 'display_name': 'Visa', 'account_type': 'Credit Card'},
            ])},
        )

    def test_load_accounts_returns_parsed_list(self):
        accounts = QBOPaymentAccountService.load_accounts()
        self.assertEqual(len(accounts), 2)
        self.assertEqual(accounts[0]['qbo_account_id'], '35')

    def test_load_accounts_empty_when_unset(self):
        Configuration.objects.filter(key='qbo_payment_accounts').delete()
        self.assertEqual(QBOPaymentAccountService.load_accounts(), [])

    def test_lookup_returns_matching_dict(self):
        acct = QBOPaymentAccountService.lookup('42')
        self.assertEqual(acct['account_type'], 'Credit Card')

    def test_lookup_unknown_raises(self):
        with self.assertRaises(ValueError):
            QBOPaymentAccountService.lookup('999')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_qbo_payment_account_service -v 2`
Expected: FAIL — `ImportError`/`AttributeError`: `QBOPaymentAccountService` not defined.

- [ ] **Step 3: Add the service and repoint expense callers**

In `apps/qbo/services.py`, add (near the other service classes, after imports — `json` and `Configuration` are already imported in this module):

```python
class QBOPaymentAccountService:
    """Owns the `qbo_payment_accounts` Configuration lookup. Shared by the
    expense/reimbursement Purchase push and the bill-payment push."""

    @staticmethod
    def load_accounts():
        """Parsed payment-account config JSON; [] if unset/blank."""
        try:
            raw = Configuration.objects.get(key='qbo_payment_accounts').value
        except Configuration.DoesNotExist:
            return []
        if not raw:
            return []
        return json.loads(raw)

    @staticmethod
    def lookup(payment_account_id):
        """Return the dict for a given qbo_account_id, or raise ValueError."""
        for a in QBOPaymentAccountService.load_accounts():
            if a['qbo_account_id'] == payment_account_id:
                return a
        raise ValueError(
            f"payment_account_id={payment_account_id!r} not in configured payment accounts"
        )
```

Then replace the bodies of the two existing private helpers in `QBOExpenseSyncService` so there is one implementation (delegate, keep names for now):

```python
    @staticmethod
    def _load_payment_accounts():
        return QBOPaymentAccountService.load_accounts()

    @staticmethod
    def _lookup_account(payment_account_id):
        return QBOPaymentAccountService.lookup(payment_account_id)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python manage.py test tests.test_qbo_payment_account_service tests.test_qbo_expense_push -v 2`
Expected: PASS (new tests pass; existing expense-push tests still pass via the delegating helpers).

- [ ] **Step 5: Commit**

```bash
git add apps/qbo/services.py tests/test_qbo_payment_account_service.py
git commit -m "refactor(qbo): extract QBOPaymentAccountService for shared account lookup"
```

---

### Task 2: `QBOSyncable` abstract base + `QBOSyncService` orchestrator

**Files:**
- Modify: `apps/core/models.py` (add abstract base)
- Modify: `apps/qbo/services.py` (add orchestrator)
- Test: `tests/test_qbo_sync_service.py` (create)

**Interfaces:**
- Produces:
  - Abstract `QBOSyncable` with fields `qbo_id` (CharField 50, blank), `qbo_sync_status` (CharField 20, choices, default `SYNC_PENDING`), `qbo_sync_error` (TextField, blank); constants `SYNC_PENDING='pending'`, `SYNC_SYNCED='synced'`, `SYNC_FAILED='sync_failed'`; methods `mark_synced(qbo_id)`, `mark_failed(error)`.
  - `QBOSyncService.run_create(record, push_callable) -> str|None` — runs `push_callable()` (returns a qbo_id string), then `record.mark_synced(qbo_id)`; on exception `record.mark_failed(e)`; never raises; returns the qbo_id or None.
  - `QBOSyncService.run_resync(record, resync_callable) -> None` — runs `resync_callable()` (no return needed), then `record.mark_synced(record.qbo_id)` (clears error, status→synced); on exception `record.mark_failed(e)`; never raises.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_qbo_sync_service.py
from django.test import SimpleTestCase
from apps.qbo.services import QBOSyncService


class _FakeRecord:
    def __init__(self):
        self.qbo_id = ''
        self.qbo_sync_status = 'pending'
        self.qbo_sync_error = ''
    def mark_synced(self, qbo_id):
        self.qbo_id = qbo_id
        self.qbo_sync_status = 'synced'
        self.qbo_sync_error = ''
    def mark_failed(self, error):
        self.qbo_sync_status = 'sync_failed'
        self.qbo_sync_error = str(error)


class QBOSyncServiceTests(SimpleTestCase):
    def test_run_create_marks_synced_on_success(self):
        rec = _FakeRecord()
        out = QBOSyncService.run_create(rec, lambda: 'qbo-99')
        self.assertEqual(out, 'qbo-99')
        self.assertEqual(rec.qbo_id, 'qbo-99')
        self.assertEqual(rec.qbo_sync_status, 'synced')

    def test_run_create_marks_failed_on_exception(self):
        rec = _FakeRecord()
        def boom():
            raise ValueError('No active QBO connection')
        out = QBOSyncService.run_create(rec, boom)
        self.assertIsNone(out)
        self.assertEqual(rec.qbo_sync_status, 'sync_failed')
        self.assertEqual(rec.qbo_sync_error, 'No active QBO connection')

    def test_run_resync_clears_error_on_success(self):
        rec = _FakeRecord()
        rec.qbo_id = 'qbo-1'
        rec.qbo_sync_status = 'sync_failed'
        rec.qbo_sync_error = 'old'
        QBOSyncService.run_resync(rec, lambda: None)
        self.assertEqual(rec.qbo_sync_status, 'synced')
        self.assertEqual(rec.qbo_sync_error, '')

    def test_run_resync_marks_failed_on_exception(self):
        rec = _FakeRecord()
        rec.qbo_id = 'qbo-1'
        def boom():
            raise RuntimeError('payload bad')
        QBOSyncService.run_resync(rec, boom)
        self.assertEqual(rec.qbo_sync_status, 'sync_failed')
        self.assertEqual(rec.qbo_sync_error, 'payload bad')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_qbo_sync_service -v 2`
Expected: FAIL — `QBOSyncService` not defined.

- [ ] **Step 3: Add the abstract base and the orchestrator**

In `apps/core/models.py` add:

```python
class QBOSyncable(models.Model):
    """Abstract base for records mirrored to a QBO object. Carries the QBO id
    and a sync-state machine (pending → synced | sync_failed). Adopters:
    Expense, Reimbursement, BillPayment."""
    SYNC_PENDING = 'pending'
    SYNC_SYNCED = 'synced'
    SYNC_FAILED = 'sync_failed'
    SYNC_STATUS_CHOICES = [
        (SYNC_PENDING, 'Pending'),
        (SYNC_SYNCED, 'Synced to QBO'),
        (SYNC_FAILED, 'QBO sync failed'),
    ]

    qbo_id = models.CharField(max_length=50, blank=True, default='')
    qbo_sync_status = models.CharField(
        max_length=20, choices=SYNC_STATUS_CHOICES, default=SYNC_PENDING)
    qbo_sync_error = models.TextField(blank=True, default='')

    class Meta:
        abstract = True

    def mark_synced(self, qbo_id):
        self.qbo_id = qbo_id
        self.qbo_sync_status = self.SYNC_SYNCED
        self.qbo_sync_error = ''
        self.save(update_fields=['qbo_id', 'qbo_sync_status', 'qbo_sync_error'])

    def mark_failed(self, error):
        self.qbo_sync_status = self.SYNC_FAILED
        self.qbo_sync_error = str(error)
        self.save(update_fields=['qbo_sync_status', 'qbo_sync_error'])
```

In `apps/qbo/services.py` add (`logger` already exists in this module):

```python
class QBOSyncService:
    """Wraps the push/resync try-except so every adopter records its sync
    outcome the same way. Never raises — a QBO hiccup must not block the local
    write that already committed."""

    @staticmethod
    def run_create(record, push_callable):
        """push_callable() does the QBO create and returns the new qbo_id."""
        try:
            qbo_id = push_callable()
            if qbo_id:
                record.mark_synced(qbo_id)
            return qbo_id
        except Exception as e:  # noqa: BLE001
            logger.exception('QBO create sync failed for %r', record)
            record.mark_failed(e)
            return None

    @staticmethod
    def run_resync(record, resync_callable):
        """resync_callable() updates the existing QBO object (qbo_id unchanged)."""
        try:
            resync_callable()
            record.mark_synced(record.qbo_id)
        except Exception as e:  # noqa: BLE001
            logger.exception('QBO resync failed for %r', record)
            record.mark_failed(e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_qbo_sync_service -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/core/models.py apps/qbo/services.py tests/test_qbo_sync_service.py
git commit -m "feat(qbo): add QBOSyncable abstract base and QBOSyncService orchestrator"
```

---

### Task 3: `BillPayment` adopts `QBOSyncable` (+ `payment_account_id`, rename `qbo_payment_id`→`qbo_id`)

**Files:**
- Modify: `apps/purchasing/models.py` (`BillPayment` ~line 444-460)
- Modify: `apps/qbo/services.py:438,442,1024` and `tests/test_qbo_bill_polling.py` (rename refs — deferred polling kept green, not implemented)
- Modify: `apps/api/purchasing/serializers.py:161,162,164` (rename `qbo_payment_id`→`qbo_id`; drop `method` from fields)
- Modify: `apps/purchasing/services.py:939,947-950,957,985` (drop `method` from `record_payment`/`update_payment`)
- Modify: `apps/api/purchasing/views.py:624` (drop `method` arg)
- Test: `tests/test_bill_payment_model.py` (create)
- Migration: `apps/purchasing/migrations/` (via `makemigrations purchasing`)

**Interfaces:**
- Produces: `BillPayment(QBOSyncable)` with new `payment_account_id` (CharField 50, blank), inherited `qbo_id`/`qbo_sync_status`/`qbo_sync_error`, existing `cleared_date`. Field `qbo_payment_id` no longer exists (now `qbo_id`). The `method` field + `METHOD_*` constants are **removed** — it drove no logic; the human descriptor is now derived from the chosen account's display name + `reference`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bill_payment_model.py
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from apps.purchasing.models import BillPayment
from apps.core.models import QBOSyncable


class BillPaymentSyncFieldsTests(TestCase):
    def test_billpayment_inherits_qbosyncable(self):
        self.assertTrue(issubclass(BillPayment, QBOSyncable))

    def test_new_payment_defaults_pending(self):
        bp = BillPayment()
        self.assertEqual(bp.qbo_sync_status, BillPayment.SYNC_PENDING)
        self.assertEqual(bp.qbo_id, '')
        self.assertEqual(bp.payment_account_id, '')

    def test_mark_synced_sets_qbo_id_and_status(self):
        # Build against a real Bill so save() works; reuse helpers if present.
        from tests.base import FixtureTestCase  # noqa: F401
```

Replace the third test with a concrete one once a `Bill` fixture helper is identified. Minimal version that needs no Bill (status machine only) — keep the first two tests; add this model-level check that does not hit the DB:

```python
    def test_has_payment_account_field(self):
        names = {f.name for f in BillPayment._meta.get_fields()}
        self.assertIn('payment_account_id', names)
        self.assertIn('qbo_id', names)
        self.assertNotIn('qbo_payment_id', names)
        self.assertNotIn('method', names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_bill_payment_model -v 2`
Expected: FAIL — `BillPayment` not a `QBOSyncable` subclass / `qbo_payment_id` still present.

- [ ] **Step 3: Edit the model**

In `apps/purchasing/models.py`, change the class declaration and fields:

```python
from apps.core.models import QBOSyncable  # add near top imports

class BillPayment(QBOSyncable):
    payment_id = models.AutoField(primary_key=True)
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE)
    # Payment OUT — entered in Minibini
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateTimeField()
    reference = models.CharField(max_length=100, blank=True, default='')
    # Which QBO bank/CC account the money came from (a qbo_account_id from
    # Configuration['qbo_payment_accounts']). Required by the QBO BillPayment push.
    # Drives the QBO PayType and replaces the old free-standing `method` field —
    # the human label is derived from the account display name + reference.
    payment_account_id = models.CharField(max_length=50, blank=True, default='')
    created_by = models.ForeignKey(
        'core.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='recorded_bill_payments',
    )
    created_date = models.DateTimeField(default=timezone.now)
    # qbo_id (the QBO BillPayment Id) + qbo_sync_status + qbo_sync_error come
    # from QBOSyncable. qbo_id is written by the PUSH; cleared_date is written
    # later by the (deferred) clearance poller.
    cleared_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'bill_payments'
```

Update the deferred references (keep them compiling — not implementing polling):
- `apps/qbo/services.py:438` `payment.qbo_payment_id` → `payment.qbo_id`
- `apps/qbo/services.py:442` `payment.qbo_payment_id` → `payment.qbo_id`
- `apps/qbo/services.py:1024` `.exclude(qbo_payment_id='')` → `.exclude(qbo_id='')`
- `apps/api/purchasing/serializers.py:162,164` `'qbo_payment_id'` → `'qbo_id'`
- `tests/test_qbo_bill_polling.py` — the `_create_bill_payment(qbo_payment_id=...)` helper kwarg and the model `qbo_payment_id=` assignment → `qbo_id`.

**Remove `method` atomically** (dropping the model field breaks `record_payment`'s constructor, so these must land in the same task to keep the suite green):
- `apps/purchasing/services.py:939` — drop the `method` param from `record_payment(...)`'s signature.
- `apps/purchasing/services.py:947-950` — drop `method=method` from the `BillPayment(...)` constructor.
- `apps/purchasing/services.py:957` — change the history string from `f'Payment recorded: {amount} via {method}'` to `f'Payment recorded: {amount}' + (f' (ref {reference})' if reference else '')` (the account-name flavor is added in Task 6 once `payment_account_id` is a param).
- `apps/purchasing/services.py:985` — drop `'method'` from the `update_payment` `allowed` set.
- `apps/api/purchasing/serializers.py:161` — drop `'method'` from the `BillPaymentSerializer` fields list.
- `apps/api/purchasing/views.py:624` — drop the `method=data.get('method')` argument from the `record_payment` call.

(The frontend still sends/shows `method` until Task 7 — harmless: the view ignores the extra key and `p.method` renders blank in the meantime.)

- [ ] **Step 4: Create the migration**

Run: `python manage.py makemigrations purchasing`
Expected: a migration that **renames** `qbo_payment_id`→`qbo_id`, **adds** `qbo_sync_status`, `qbo_sync_error`, `payment_account_id`, and **removes** `method`. Open it and confirm it emits `migrations.RenameField(model_name='billpayment', old_name='qbo_payment_id', new_name='qbo_id')` (Django usually prompts whether a removed+added field is a rename — if it generated AddField+RemoveField for the qbo id instead, hand-edit it to a `RenameField` so existing data is preserved) and a `migrations.RemoveField(model_name='billpayment', name='method')` (pre-production — dropping the column with its data is acceptable). Do **not** run `migrate`.

- [ ] **Step 5: Run tests to verify pass**

Run: `python manage.py test tests.test_bill_payment_model tests.test_qbo_bill_polling -v 2`
Expected: PASS (the test DB is built from migrations).

- [ ] **Step 6: Commit**

```bash
git add apps/purchasing/models.py apps/purchasing/services.py apps/qbo/services.py \
        apps/api/purchasing/serializers.py apps/api/purchasing/views.py \
        tests/test_bill_payment_model.py tests/test_qbo_bill_polling.py \
        apps/purchasing/migrations/
git commit -m "feat(purchasing): BillPayment adopts QBOSyncable, add payment_account_id, drop method, rename qbo_payment_id->qbo_id"
```

---

### Task 4: Live `push_bill_payment` (create) + builder

**Files:**
- Modify: `apps/qbo/services.py` (`QBOBillSyncService`: add `_build_qbo_bill_payment`, rewrite `push_bill_payment`)
- Test: `tests/test_qbo_bill_payment_push.py` (create)

**Interfaces:**
- Consumes: `QBOPaymentAccountService.lookup`, `QBOSyncService.run_create`, `QBOBillSyncService.push_bill`, `BillPayment.mark_synced/mark_failed`.
- Produces:
  - `QBOBillSyncService._build_qbo_bill_payment(payment, client) -> qbo_id` — builds + saves the QBO `BillPayment`, logs sync, returns the new id string.
  - `QBOBillSyncService.push_bill_payment(payment) -> str|None` — full create path used by `record_payment`; never raises; short-circuits if already `qbo_id`.

**Design notes (apply in the builder):**
- Short-circuit: if `payment.qbo_id` already set, return it (idempotent retry guard).
- Connection: `QBOService.get_client()`; if falsy, raise `ValueError('No active QBO connection')` so `run_create` records `sync_failed` with that message (mirrors expense).
- Account required: if `not payment.payment_account_id`, raise `ValueError('No payment account selected for this bill payment')`.
- Ensure the parent Bill (and thus vendor) exists in QBO: `if not payment.bill.qbo_id: QBOBillSyncService.push_bill(payment.bill)`.
- `account = QBOPaymentAccountService.lookup(payment.payment_account_id)`.
- PayType is driven by the account's `account_type` (this is what QBO requires for the attached account): `'Credit Card'` → `PayType='CreditCard'` + `CreditCardPayment.CCAccountRef`; anything else (`Bank`, `Other Current Asset`, incl. a Petty-Cash account used for cash) → `PayType='Check'` + `CheckPayment.BankAccountRef`.
- `VendorRef.value = payment.bill.business.qbo_vendor_id`.
- `TotalAmt = float(payment.amount)`.
- One `BillPaymentLine`: `Amount = float(payment.amount)`, one `LinkedTxn` with `TxnId = payment.bill.qbo_id`, `TxnType = 'Bill'`.
- `DocNumber = payment.reference` (if set).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_qbo_bill_payment_push.py
from decimal import Decimal
from unittest.mock import patch, MagicMock
import json
from django.test import TestCase
from django.utils import timezone
from apps.core.models import Configuration
from apps.purchasing.models import BillPayment
from apps.qbo.services import QBOBillSyncService
from tests.base import FixtureTestCase


class BillPaymentPushTests(FixtureTestCase):
    """FixtureTestCase provides loaded fixtures incl. a Bill + vendor business.
    Adjust the lookups below to the fixture's actual bill/business if needed."""

    def setUp(self):
        super().setUp()
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': json.dumps([
                {'qbo_account_id': '35', 'display_name': 'Checking', 'account_type': 'Bank'},
            ])},
        )
        from apps.purchasing.models import Bill
        self.bill = Bill.objects.filter(business__isnull=False).first()
        self.bill.qbo_id = 'qbo-bill-1'
        self.bill.business.qbo_vendor_id = 'qbo-vendor-1'
        self.bill.business.save()
        self.bill.save()
        self.payment = BillPayment.objects.create(
            bill=self.bill, amount=Decimal('100.00'),
            payment_date=timezone.now(),
            reference='1234', payment_account_id='35',
        )

    @patch('apps.qbo.services.QBOService.log_sync')
    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_builds_and_marks_synced(self, mock_get_client, mock_log):
        client = MagicMock()
        mock_get_client.return_value = client
        captured = {}
        def fake_save(qb=None):
            captured['obj'] = saved_self
            saved_self.Id = 'qbo-bp-77'
        # Patch the SDK BillPayment.save to set an Id.
        with patch('quickbooks.objects.billpayment.BillPayment.save', autospec=True) as mock_save:
            def _save(self, qb=None):
                self.Id = 'qbo-bp-77'
            mock_save.side_effect = _save
            out = QBOBillSyncService.push_bill_payment(self.payment)
        self.payment.refresh_from_db()
        self.assertEqual(out, 'qbo-bp-77')
        self.assertEqual(self.payment.qbo_id, 'qbo-bp-77')
        self.assertEqual(self.payment.qbo_sync_status, BillPayment.SYNC_SYNCED)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_without_connection_marks_failed(self, mock_get_client):
        mock_get_client.return_value = None
        out = QBOBillSyncService.push_bill_payment(self.payment)
        self.payment.refresh_from_db()
        self.assertIsNone(out)
        self.assertEqual(self.payment.qbo_sync_status, BillPayment.SYNC_FAILED)
        self.assertIn('No active QBO connection', self.payment.qbo_sync_error)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_without_account_marks_failed(self, mock_get_client):
        mock_get_client.return_value = MagicMock()
        self.payment.payment_account_id = ''
        self.payment.save(update_fields=['payment_account_id'])
        out = QBOBillSyncService.push_bill_payment(self.payment)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.qbo_sync_status, BillPayment.SYNC_FAILED)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_short_circuits_when_already_synced(self, mock_get_client):
        self.payment.qbo_id = 'already'
        self.payment.save(update_fields=['qbo_id'])
        out = QBOBillSyncService.push_bill_payment(self.payment)
        self.assertEqual(out, 'already')
        mock_get_client.assert_not_called()
```

> Note: if `FixtureTestCase` has no bill-with-business, add a minimal one in `setUp` using the contacts/purchasing fixture factories already used by `tests/test_qbo_bill_push.py` — copy that file's bill-construction pattern verbatim rather than inventing one.

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_qbo_bill_payment_push -v 2`
Expected: FAIL — `push_bill_payment` still the stub (returns the old logged value, no build, no mark).

- [ ] **Step 3: Implement the builder + push**

Replace `QBOBillSyncService.push_bill_payment` (currently `apps/qbo/services.py:422-442`) and add the builder:

```python
    @staticmethod
    def push_bill_payment(payment):
        """Create a QBO BillPayment for a recorded Minibini BillPayment.
        Idempotent on payment.qbo_id. Never raises — records sync state on the
        payment via QBOSyncService."""
        if payment.qbo_id:
            return payment.qbo_id
        return QBOSyncService.run_create(
            payment,
            lambda: QBOBillSyncService._build_qbo_bill_payment(payment),
        )

    @staticmethod
    def _build_qbo_bill_payment(payment):
        from quickbooks.objects.billpayment import (
            BillPayment as QBOBillPayment, BillPaymentLine,
            CheckPayment, BillPaymentCreditCard,
        )
        from quickbooks.objects.base import Ref, LinkedTxn

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')
        if not payment.payment_account_id:
            raise ValueError('No payment account selected for this bill payment')

        bill = payment.bill
        if not bill.qbo_id:
            QBOBillSyncService.push_bill(bill)

        account = QBOPaymentAccountService.lookup(payment.payment_account_id)

        qbp = QBOBillPayment()
        qbp.TotalAmt = float(payment.amount)
        if payment.reference:
            qbp.DocNumber = payment.reference

        vendor_ref = Ref()
        vendor_ref.value = bill.business.qbo_vendor_id
        qbp.VendorRef = vendor_ref

        acct_ref = Ref()
        acct_ref.value = account['qbo_account_id']
        if account['account_type'] == 'Credit Card':
            qbp.PayType = 'CreditCard'
            cc = BillPaymentCreditCard()
            cc.CCAccountRef = acct_ref
            qbp.CreditCardPayment = cc
        else:
            qbp.PayType = 'Check'
            chk = CheckPayment()
            chk.BankAccountRef = acct_ref
            qbp.CheckPayment = chk

        line = BillPaymentLine()
        line.Amount = float(payment.amount)
        linked = LinkedTxn()
        linked.TxnId = bill.qbo_id
        linked.TxnType = 'Bill'
        line.LinkedTxn = [linked]
        qbp.Line = [line]

        try:
            qbp.save(qb=client)
            qbo_id = str(qbp.Id)
            QBOService.log_sync(
                entity_type='bill_payment', entity_id=payment.pk,
                qbo_entity_type='BillPayment', qbo_entity_id=qbo_id,
                action='create', status='success',
            )
            return qbo_id
        except Exception as e:
            QBOService.log_sync(
                entity_type='bill_payment', entity_id=payment.pk,
                qbo_entity_type='BillPayment', qbo_entity_id='',
                action='create', status='failed', error_message=str(e),
            )
            raise
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python manage.py test tests.test_qbo_bill_payment_push -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/qbo/services.py tests/test_qbo_bill_payment_push.py
git commit -m "feat(qbo): live BillPayment create push with shared sync orchestration"
```

---

### Task 5: `update_bill_payment` / `void_bill_payment` + wire into the payment flow

**Files:**
- Modify: `apps/qbo/services.py` (`QBOBillSyncService`: add `update_bill_payment`, `void_bill_payment`)
- Modify: `apps/purchasing/services.py` (`record_payment` already calls `_push_to_qbo`; update `_push_to_qbo`, add resync to `update_payment`, add void to `delete_payment`)
- Test: `tests/test_bill_payment_qbo_lifecycle.py` (create)

**Interfaces:**
- Consumes: `QBOSyncService.run_resync`, `QBOBillSyncService.push_bill_payment`.
- Produces:
  - `QBOBillSyncService.update_bill_payment(payment)` — re-fetch the QBO `BillPayment` by `payment.qbo_id`, rebuild fields, save. Raises if no `qbo_id`.
  - `QBOBillSyncService.void_bill_payment(payment)` — delete the QBO `BillPayment`; logs but does **not** raise (caller is mid-delete).
  - `BillPaymentService.update_payment` — after local save, if `payment.qbo_id` resync, else create-push (covers a payment first recorded while disconnected).
  - `BillPaymentService.delete_payment` — before local delete, if `payment.qbo_id` void.

**Design notes:**
- The create-or-update boundary (cash is gone, so this mirrors Expense exactly): `update_payment` → `if payment.qbo_id: run_resync(payment, update_bill_payment) else: push_bill_payment(payment)`.
- `void_bill_payment` swallows errors (logs) like `void_expense`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bill_payment_qbo_lifecycle.py
from decimal import Decimal
from unittest.mock import patch, MagicMock
import json
from django.utils import timezone
from apps.core.models import Configuration
from apps.purchasing.models import BillPayment
from apps.purchasing.services import BillPaymentService
from tests.base import FixtureTestCase


class BillPaymentLifecycleTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': json.dumps([
                {'qbo_account_id': '35', 'display_name': 'Checking', 'account_type': 'Bank'},
            ])},
        )
        from apps.purchasing.models import Bill
        self.bill = Bill.objects.filter(business__isnull=False, status='received').first()
        self.bill.qbo_id = 'qbo-bill-1'
        self.bill.business.qbo_vendor_id = 'qbo-vendor-1'
        self.bill.business.save()
        self.bill.save()

    @patch('apps.qbo.services.QBOBillSyncService.update_bill_payment')
    @patch('apps.qbo.services.QBOBillSyncService.push_bill_payment')
    def test_edit_synced_payment_resyncs(self, mock_push, mock_update):
        pay = BillPayment.objects.create(
            bill=self.bill, amount=Decimal('50.00'), payment_date=timezone.now(),
            payment_account_id='35',
            qbo_id='qbo-bp-1', qbo_sync_status=BillPayment.SYNC_SYNCED,
        )
        BillPaymentService.update_payment(pay.pk, amount='75.00')
        mock_update.assert_called_once()
        mock_push.assert_not_called()

    @patch('apps.qbo.services.QBOBillSyncService.void_bill_payment')
    def test_delete_synced_payment_voids(self, mock_void):
        pay = BillPayment.objects.create(
            bill=self.bill, amount=Decimal('50.00'), payment_date=timezone.now(),
            payment_account_id='35',
            qbo_id='qbo-bp-2', qbo_sync_status=BillPayment.SYNC_SYNCED,
        )
        BillPaymentService.delete_payment(pay.pk)
        mock_void.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_bill_payment_qbo_lifecycle -v 2`
Expected: FAIL — `update_bill_payment`/`void_bill_payment` not defined; `update_payment`/`delete_payment` don't call them.

- [ ] **Step 3: Implement the QBO methods**

Add to `QBOBillSyncService` in `apps/qbo/services.py`:

```python
    @staticmethod
    def update_bill_payment(payment):
        from quickbooks.objects.billpayment import BillPayment as QBOBillPayment
        if not payment.qbo_id:
            raise ValueError('BillPayment has no qbo_id — use push_bill_payment')
        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')
        existing = QBOBillPayment.get(payment.qbo_id, qb=client)
        existing.TotalAmt = float(payment.amount)
        if payment.reference:
            existing.DocNumber = payment.reference
        if existing.Line:
            existing.Line[0].Amount = float(payment.amount)
        existing.save(qb=client)
        QBOService.log_sync(
            entity_type='bill_payment', entity_id=payment.pk,
            qbo_entity_type='BillPayment', qbo_entity_id=payment.qbo_id,
            action='update', status='success',
        )
        return payment.qbo_id

    @staticmethod
    def void_bill_payment(payment):
        from quickbooks.objects.billpayment import BillPayment as QBOBillPayment
        if not payment.qbo_id:
            return
        try:
            client = QBOService.get_client()
            if not client:
                return
            existing = QBOBillPayment.get(payment.qbo_id, qb=client)
            existing.delete(qb=client)
            QBOService.log_sync(
                entity_type='bill_payment', entity_id=payment.pk,
                qbo_entity_type='BillPayment', qbo_entity_id=payment.qbo_id,
                action='delete', status='success',
            )
        except Exception as e:  # noqa: BLE001 — caller is mid-delete; never block
            logger.exception('QBO bill-payment void failed for payment %s', payment.pk)
            QBOService.log_sync(
                entity_type='bill_payment', entity_id=payment.pk,
                qbo_entity_type='BillPayment', qbo_entity_id=payment.qbo_id,
                action='delete', status='failed', error_message=str(e),
            )
```

- [ ] **Step 4: Wire the service**

In `apps/purchasing/services.py`, update `_push_to_qbo` (keep create on record) and add resync/void. `_push_to_qbo` stays as-is (calls `push_bill_payment`, which already does run_create). Add to `update_payment` after the local save (find where it returns `payment`):

```python
        # QBO resync (best-effort; never blocks the local edit).
        from apps.qbo.services import QBOBillSyncService, QBOSyncService
        if payment.qbo_id:
            QBOSyncService.run_resync(
                payment, lambda: QBOBillSyncService.update_bill_payment(payment))
        else:
            QBOBillSyncService.push_bill_payment(payment)
```

Add to `delete_payment` before the local `payment.delete()`:

```python
        from apps.qbo.services import QBOBillSyncService
        if payment.qbo_id:
            QBOBillSyncService.void_bill_payment(payment)
```

> If `delete_payment`/`update_payment` don't currently load the `payment` object before mutating, adjust to fetch it first (they already do — `update_payment` loads via `BillPayment.objects.get`; confirm `delete_payment` does too and add the void before deletion).

- [ ] **Step 5: Run tests to verify pass**

Run: `python manage.py test tests.test_bill_payment_qbo_lifecycle tests.test_qbo_bill_payment_push -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/qbo/services.py apps/purchasing/services.py tests/test_bill_payment_qbo_lifecycle.py
git commit -m "feat(qbo): bill-payment update/void sync wired into edit/delete flows"
```

---

### Task 6: API serializer — expose sync fields + require account when QBO connected

**Files:**
- Modify: `apps/api/purchasing/serializers.py` (`BillPaymentSerializer` ~line 155-165)
- Modify: `apps/api/purchasing/views.py` (record-payment action ~line 615-631, pass `payment_account_id`)
- Test: `tests/test_api_bill_payments.py` (create or extend if exists)

**Interfaces:**
- Produces: `BillPaymentSerializer` exposes read-only `qbo_id`, `qbo_sync_status`, `qbo_sync_error`, `cleared_date`; writable `payment_account_id`. The record-payment endpoint requires `payment_account_id` when a QBO connection is active, else 400.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_bill_payments.py
from decimal import Decimal
from unittest.mock import patch
import json
from django.utils import timezone
from apps.core.models import Configuration
from tests.base import FixtureAPITestCase  # use the project's API test base


class BillPaymentApiTests(FixtureAPITestCase):
    def setUp(self):
        super().setUp()
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': json.dumps([
                {'qbo_account_id': '35', 'display_name': 'Checking', 'account_type': 'Bank'},
            ])},
        )
        # authenticate as a can_manage_financials user per the project's helper
        self.login_financials()
        from apps.purchasing.models import Bill
        self.bill = Bill.objects.filter(status='received').first()

    @patch('apps.qbo.services.QBOService.get_client', return_value=object())
    def test_record_payment_requires_account_when_connected(self, _c):
        resp = self.client.post(
            f'/api/bills/{self.bill.pk}/payments/',
            {'amount': '10.00', 'payment_date': timezone.now().isoformat()},
            format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('payment_account_id', resp.json())

    @patch('apps.qbo.services.QBOBillSyncService.push_bill_payment', return_value=None)
    @patch('apps.qbo.services.QBOService.get_client', return_value=object())
    def test_record_payment_accepts_account(self, _c, _p):
        resp = self.client.post(
            f'/api/bills/{self.bill.pk}/payments/',
            {'amount': '10.00', 'payment_date': timezone.now().isoformat(),
             'payment_account_id': '35'}, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertIn('qbo_sync_status', resp.json())
```

> Use the project's actual API test base/login helper names (check `tests/base.py` and an existing `tests/test_api_*` for `FixtureAPITestCase` / `login_financials` equivalents) — match them rather than the placeholders above.

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_bill_payments -v 2`
Expected: FAIL — serializer lacks fields / no account requirement.

- [ ] **Step 3: Implement**

In `apps/api/purchasing/serializers.py`, update `BillPaymentSerializer.Meta.fields` to include `payment_account_id`, `qbo_id`, `qbo_sync_status`, `qbo_sync_error`, `cleared_date`, and `read_only_fields` to include `qbo_id`, `qbo_sync_status`, `qbo_sync_error`, `cleared_date` (drop the old `qbo_payment_id`).

In `apps/api/purchasing/views.py` record-payment action, read `payment_account_id` and enforce:

```python
        payment_account_id = request.data.get('payment_account_id', '').strip()
        from apps.qbo.services import QBOService
        if QBOService.get_client() and not payment_account_id:
            return Response(
                {'payment_account_id': ['Required while QuickBooks is connected.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payment = BillPaymentService.record_payment(
            bill, amount=..., payment_date=..., reference=...,
            payment_account_id=payment_account_id, user=request.user,
        )
```

Add `payment_account_id=''` param to `BillPaymentService.record_payment` signature and pass it into the `BillPayment(...)` constructor. Now that the account id is in scope, enrich the history string (set in Task 3 to amount-only) to name the account: resolve `QBOPaymentAccountService.lookup(payment_account_id)['display_name']` (guard with try/except `ValueError` → fall back to amount-only when unset/disconnected), e.g. `f'Payment recorded: {amount} from {display_name}'` + the `(ref …)` suffix.

- [ ] **Step 4: Run tests to verify pass**

Run: `python manage.py test tests.test_api_bill_payments -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/purchasing/serializers.py apps/api/purchasing/views.py apps/purchasing/services.py tests/test_api_bill_payments.py
git commit -m "feat(api): bill-payment serializer exposes sync fields; require account when QBO connected"
```

---

### Task 7: `<PaymentAccountSelect>` component + Record Payment modal + sync display

**Files:**
- Create: `frontend/src/components/qbo/PaymentAccountSelect.svelte`
- Create: `frontend/tests/PaymentAccountSelect.test.js`
- Modify: `frontend/src/components/RecordPaymentModal.svelte` — **remove the `method` `<select>`** (state at line 6, control at line 35, POST field at line 18), add the account picker (required when accounts exist), include `payment_account_id` in the POST body.
- Modify: `frontend/src/routes/bills/BillDetailPage.svelte` — the payments table (`{p.method}` at line 227) shows the account display name (resolve `p.payment_account_id` via `getPaymentAccounts()`, fall back to `—`) + `{p.reference}`, plus the `qbo_sync_status`/`qbo_sync_error` indicator.

**Interfaces:**
- Produces: `<PaymentAccountSelect bind:value={qboAccountId} required={bool} />` — fetches via `getPaymentAccounts()` (`lib/paymentAccounts.js`), renders `<option value={a.qbo_account_id}>{a.display_name}</option>`; empty list → renders a disabled hint.

- [ ] **Step 1: Write the failing test**

```javascript
// frontend/tests/PaymentAccountSelect.test.js
import { render } from '@testing-library/svelte';
import { vi, test, expect, beforeEach } from 'vitest';
import PaymentAccountSelect from '../src/components/qbo/PaymentAccountSelect.svelte';

vi.mock('../src/lib/paymentAccounts.js', () => ({
  getPaymentAccounts: vi.fn(async () => ([
    { qbo_account_id: '35', display_name: 'Checking', account_type: 'Bank' },
    { qbo_account_id: '42', display_name: 'Visa', account_type: 'Credit Card' },
  ])),
}));

test('renders an option per configured account', async () => {
  const { findAllByRole } = render(PaymentAccountSelect, { props: { value: '' } });
  const opts = await findAllByRole('option');
  // placeholder + 2 accounts
  expect(opts.length).toBe(3);
  expect(opts.map(o => o.textContent)).toEqual(
    expect.arrayContaining(['Checking', 'Visa']));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test:run -- PaymentAccountSelect`
Expected: FAIL — component does not exist.

- [ ] **Step 3: Implement the component**

```svelte
<!-- frontend/src/components/qbo/PaymentAccountSelect.svelte -->
<script>
  import { getPaymentAccounts } from '../../lib/paymentAccounts.js';
  let { value = $bindable(''), required = false, id = 'payment-account' } = $props();
  let accounts = $state([]);
  $effect(() => { getPaymentAccounts().then(a => { accounts = a; }); });
</script>

{#if accounts.length === 0}
  <select {id} disabled><option>No payment accounts configured</option></select>
{:else}
  <select {id} bind:value {required}>
    <option value="">— select account —</option>
    {#each accounts as a (a.qbo_account_id)}
      <option value={a.qbo_account_id}>{a.display_name}</option>
    {/each}
  </select>
{/if}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test:run -- PaymentAccountSelect`
Expected: PASS.

- [ ] **Step 5: Wire into the Record Payment modal + bill detail**

In `RecordPaymentModal.svelte`: delete the `method` state (`let method = $state('check')`) and its `<select>`; import and place `<PaymentAccountSelect bind:value={paymentAccountId} required={true} />`; swap `method` for `payment_account_id` in the POST body. In `BillDetailPage.svelte`: replace the `{p.method}` cell with the resolved account display name + `{p.reference}`, and render each payment row's sync state, e.g. `{#if p.qbo_sync_status === 'sync_failed'}<span class="sync-error" title={p.qbo_sync_error}>QBO sync failed — retry</span>{:else if p.qbo_id}<span>synced</span>{/if}`. (No new test required for this wiring itself — it's route/integration glue; the picker is unit-tested.)

- [ ] **Step 6: Run the full frontend suite + commit**

Run: `cd frontend && npm run test:run`
Expected: PASS.

```bash
git add frontend/src/components/qbo/PaymentAccountSelect.svelte frontend/tests/PaymentAccountSelect.test.js \
        frontend/src/components/RecordPaymentModal.svelte frontend/src/routes/bills/BillDetailPage.svelte
git commit -m "feat(spa): reusable PaymentAccountSelect; record-payment account picker replaces method + sync status"
```

---

## Phase 2 — Expense / Reimbursement convergence

### Task 8: `Reimbursement` adopts `QBOSyncable` (rename `status`→`qbo_sync_status`)

**Files:**
- Modify: `apps/expenses/models.py` (`Reimbursement` ~line 128-157)
- Modify: `apps/expenses/services.py` (`create_batch`, `retry_push`, the `_resync` batch branch lines 219-224)
- Modify: `apps/api/reimbursements/serializers.py`, `apps/api/reimbursements/views.py`
- Modify: `frontend/src/components/expenses/UserReimbursementPanel.svelte:248`
- Modify: tests `tests/test_reimbursement_model.py`, `tests/test_reimbursement_service.py`
- Migration: `apps/expenses/migrations/` (RenameField)

**Interfaces:**
- Produces: `Reimbursement(QBOSyncable)` — `status` field gone; sync state now `qbo_sync_status` (`pending`/`synced`/`sync_failed`); `qbo_id`/`qbo_sync_error` from base. Constants `Reimbursement.SYNC_PENDING` etc. come from the base.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_reimbursement_model.py
def test_reimbursement_uses_qbosyncable(self):
    from apps.expenses.models import Reimbursement
    from apps.core.models import QBOSyncable
    self.assertTrue(issubclass(Reimbursement, QBOSyncable))
    names = {f.name for f in Reimbursement._meta.get_fields()}
    self.assertIn('qbo_sync_status', names)
    self.assertNotIn('status', names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_reimbursement_model -v 2`
Expected: FAIL — `Reimbursement` not a `QBOSyncable` subclass / still has `status`.

- [ ] **Step 3: Edit model + service + serializer + view + frontend**

`apps/expenses/models.py`: change `class Reimbursement(models.Model):` → `class Reimbursement(QBOSyncable):` (import `QBOSyncable` from `apps.core.models`); delete its own `STATUS_*` constants/choices, `status`, `qbo_id`, `qbo_sync_error` field definitions (all now from base). Keep its other fields (`payment_account_id`, `reference_number`, etc.).

Replace every `Reimbursement.STATUS_PENDING/SYNCED/SYNC_FAILED` with `Reimbursement.SYNC_PENDING/SYNC_SYNCED/SYNC_FAILED`, and every read/write of `batch.status` (sync sense) with `batch.qbo_sync_status`. Sites:
- `apps/expenses/services.py`: `create_batch` (sets initial status; use orchestrator instead — see below), `retry_push`, the `_resync` batch branch (lines 219-224 set `batch.status = Reimbursement.STATUS_SYNC_FAILED` → use `QBOSyncService.run_resync(batch, ...)` pattern or `batch.mark_failed(e)`).
- `apps/api/reimbursements/serializers.py:14`: rename `status` → `qbo_sync_status` in fields.
- `apps/api/reimbursements/views.py`: any `status` references in the create/retry responses.
- `frontend/src/components/expenses/UserReimbursementPanel.svelte:248`: `b.status === 'sync_failed'` → `b.qbo_sync_status === 'sync_failed'`.

Refactor `create_batch`'s push to use the orchestrator:

```python
        # after the batch + expenses commit:
        from apps.qbo.services import QBOExpenseSyncService, QBOSyncService
        QBOSyncService.run_create(
            batch, lambda: QBOExpenseSyncService.push_reimbursement(batch))
```

(`push_reimbursement` must return the qbo_id and no longer set status itself — verify in Task 11; for now keep its return value.)

- [ ] **Step 4: Create the migration**

Run: `python manage.py makemigrations expenses`
Expected: `RenameField(model_name='reimbursement', old_name='status', new_name='qbo_sync_status')` (confirm it's a rename, not drop+add). Do not run `migrate`.

- [ ] **Step 5: Run tests to verify pass**

Run: `python manage.py test tests.test_reimbursement_model tests.test_reimbursement_service -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/expenses/models.py apps/expenses/services.py apps/api/reimbursements/ \
        frontend/src/components/expenses/UserReimbursementPanel.svelte \
        tests/test_reimbursement_model.py tests/test_reimbursement_service.py \
        apps/expenses/migrations/
git commit -m "refactor(expenses): Reimbursement adopts QBOSyncable (status->qbo_sync_status)"
```

---

### Task 9: `Expense` adopts `QBOSyncable` (split fused status)

**Files:**
- Modify: `apps/expenses/models.py` (`Expense` ~line 14-76)
- Modify: `apps/expenses/services.py` (`_push_and_set_status` 80-92, `_resync` 205-228, `retry_sync` 283-291)
- Modify: tests `tests/test_expense_model.py`, `tests/test_expense_service.py`, `tests/test_api_expenses.py`, `tests/test_qbo_expense_push.py`
- Migration: `apps/expenses/migrations/` (AddField + **data migration**)

**Interfaces:**
- Produces: `Expense(QBOSyncable)` — `status` now business-only (`submitted`/`reimbursed`/`rejected`); sync via inherited `qbo_sync_status`; `qbo_id`/`qbo_sync_error` from base. `Expense.SYNC_SYNCED` etc. from base; `Expense.STATUS_SUBMITTED/REIMBURSED/REJECTED` remain.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_expense_model.py
def test_expense_status_is_business_only(self):
    from apps.expenses.models import Expense
    from apps.core.models import QBOSyncable
    self.assertTrue(issubclass(Expense, QBOSyncable))
    status_values = {c[0] for c in Expense.STATUS_CHOICES}
    self.assertEqual(status_values, {'submitted', 'reimbursed', 'rejected'})
    names = {f.name for f in Expense._meta.get_fields()}
    self.assertIn('qbo_sync_status', names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_expense_model -v 2`
Expected: FAIL — `synced`/`sync_failed` still in `STATUS_CHOICES`.

- [ ] **Step 3: Edit model + service**

`apps/expenses/models.py`: `class Expense(QBOSyncable):`; remove `STATUS_SYNCED`, `STATUS_SYNC_FAILED` constants and their choices tuples (keep `STATUS_SUBMITTED/REIMBURSED/REJECTED`); delete the model's own `qbo_id` and `qbo_sync_error` field definitions (now from base). Keep `status` default `STATUS_SUBMITTED`.

`apps/expenses/services.py`:
- `_push_and_set_status` (80-92): replace with the orchestrator:

```python
    @staticmethod
    def _push_and_set_status(expense):
        from apps.qbo.services import QBOExpenseSyncService, QBOSyncService
        QBOSyncService.run_create(
            expense, lambda: QBOExpenseSyncService.push_expense(expense))
```

- `_resync` (205-228): company branch uses `QBOSyncService.run_resync(expense, lambda: QBOExpenseSyncService.update_expense(expense))`; personal branch uses `QBOSyncService.run_resync(expense.reimbursement, lambda: QBOExpenseSyncService.update_reimbursement(expense.reimbursement))`. Remove the manual `expense.status = STATUS_SYNCED/SYNC_FAILED` writes.
- `retry_sync` (285): guard `if expense.qbo_sync_status != Expense.SYNC_FAILED:` and message accordingly.

> `push_expense`/`update_expense` (in `apps/qbo/services.py`) currently set `expense.qbo_id` + `log_sync` and raise on error — leave that QBO-layer behavior; the orchestrator now owns the status write (previously done by `_push_and_set_status`). Confirm `push_expense` no longer needs to set status (it never did — `_push_and_set_status` did).

- [ ] **Step 4: Create the data migration**

Run: `python manage.py makemigrations expenses`
Expected: AddField `qbo_sync_status`. Then add a **data migration** in the same `makemigrations` batch or a new empty migration (`python manage.py makemigrations expenses --empty -n expense_status_split`) with:

```python
def forward(apps, schema_editor):
    Expense = apps.get_model('expenses', 'Expense')
    for e in Expense.objects.filter(status__in=['synced', 'sync_failed']):
        e.qbo_sync_status = e.status  # 'synced' or 'sync_failed'
        e.status = 'submitted'
        e.save(update_fields=['status', 'qbo_sync_status'])

def backward(apps, schema_editor):
    Expense = apps.get_model('expenses', 'Expense')
    for e in Expense.objects.filter(qbo_sync_status__in=['synced', 'sync_failed']):
        e.status = e.qbo_sync_status
        e.save(update_fields=['status'])

class Migration(migrations.Migration):
    dependencies = [('expenses', '<the AddField migration>')]
    operations = [migrations.RunPython(forward, backward)]
```

Do **not** run `migrate`.

- [ ] **Step 5: Update the affected tests**

In `tests/test_expense_service.py`, `tests/test_api_expenses.py`, `tests/test_qbo_expense_push.py`: change assertions reading `expense.status == 'synced'`/`'sync_failed'` to `expense.qbo_sync_status == ...`. Status-filter tests for the list endpoint move to the `qbo_sync_status` filter (see Task 10 for the API filter field).

- [ ] **Step 6: Run tests to verify pass**

Run: `python manage.py test tests.test_expense_model tests.test_expense_service tests.test_qbo_expense_push tests.test_api_expenses -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/expenses/models.py apps/expenses/services.py tests/test_expense_model.py \
        tests/test_expense_service.py tests/test_api_expenses.py tests/test_qbo_expense_push.py \
        apps/expenses/migrations/
git commit -m "refactor(expenses): Expense adopts QBOSyncable, split fused status into business + sync"
```

---

### Task 10: Expense frontend — sync display/filter use `qbo_sync_status`

**Files:**
- Modify: `apps/api/expenses/serializers.py` (expose `qbo_sync_status`; keep `status` business-only) + the list filter (`apps/api/expenses/views.py` filterset, if status was filterable)
- Modify: `frontend/src/routes/expenses/ExpenseListPage.svelte` (filter options 138-139, display 200), `frontend/src/components/home/ExpensesList.svelte` (labels 38-39)

**Interfaces:**
- Produces: Expense API returns both `status` (business) and `qbo_sync_status` (sync). The list page's QBO filter targets `qbo_sync_status`.

- [ ] **Step 1: Write the failing test (backend serializer)**

```python
# add to tests/test_api_expenses.py
def test_expense_serializer_exposes_qbo_sync_status(self):
    # create a company-paid expense, GET it, assert both keys present
    resp = self.client.get(f'/api/expenses/{self.company_expense.pk}/')
    body = resp.json()
    self.assertIn('status', body)
    self.assertIn('qbo_sync_status', body)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python manage.py test tests.test_api_expenses -v 2`
Expected: FAIL — `qbo_sync_status` not serialized.

- [ ] **Step 3: Implement**

Add `qbo_sync_status`, `qbo_sync_error` (read-only) to `ExpenseSerializer.Meta.fields`. If the expenses list view has a `status` filter that included `synced`/`sync_failed`, split it: business `status` filter keeps `submitted`/`reimbursed`/`rejected`; add a `qbo_sync_status` filter.

Frontend:
- `ExpenseListPage.svelte`: move the `synced`/`sync_failed` `<option>`s (138-139) into a `qbo_sync_status` filter control; the row display at line 200 reads `e.qbo_sync_status === 'sync_failed'`.
- `ExpensesList.svelte` (home): the label map (38-39) keys off `qbo_sync_status`.

- [ ] **Step 4: Run tests to verify pass**

Run: `python manage.py test tests.test_api_expenses -v 2` and `cd frontend && npm run test:run`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/expenses/ frontend/src/routes/expenses/ExpenseListPage.svelte frontend/src/components/home/ExpensesList.svelte tests/test_api_expenses.py
git commit -m "refactor(expenses): SPA + API surface qbo_sync_status separately from business status"
```

---

## Phase 3 — Reimbursement push debug

### Task 11: Root-cause + fix the always-`sync_failed` reimbursement push

The LATER.md note (2026-06-14): creating a `Reimbursement` lands in `sync_failed` every time. Two candidate causes: (a) env-only — no QBO connection/credentials in dev → `push_reimbursement` raises `ValueError('No active QBO connection')`; (b) a real payload defect in `_build_qbo_purchase_for_reimbursement` (e.g. a line with no `AccountRef` because the expense's `accounting_category` has no `qbo_expense_account_id`, or an unset header `AccountRef`/`PaymentType`).

**Files:**
- Read: `apps/qbo/services.py` (`push_reimbursement` ~793-828, `_build_qbo_purchase_for_reimbursement` ~763, `_build_expense_line` 580, `_derive_payment_type` 570)
- Modify: whichever builder field is wrong (TBD by the test)
- Test: `tests/test_qbo_reimbursement_push.py` (create or extend)

- [ ] **Step 1: Write a characterization test that pushes a fully-valid batch with a mocked client**

```python
# tests/test_qbo_reimbursement_push.py
from unittest.mock import patch, MagicMock
import json
from apps.core.models import Configuration
from apps.qbo.services import QBOExpenseSyncService
from tests.base import FixtureTestCase


class ReimbursementPushTests(FixtureTestCase):
    def setUp(self):
        super().setUp()
        Configuration.objects.update_or_create(
            key='qbo_payment_accounts',
            defaults={'value': json.dumps([
                {'qbo_account_id': '35', 'display_name': 'Checking', 'account_type': 'Bank'},
            ])},
        )
        # Build a reimbursement batch of personal expenses whose accounting
        # categories DO have qbo_expense_account_id set. Reuse the batch-creation
        # helper from tests/test_reimbursement_service.py verbatim.

    @patch('apps.qbo.services.QBOService.log_sync')
    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_reimbursement_succeeds_with_valid_data(self, mock_client, mock_log):
        client = MagicMock()
        mock_client.return_value = client
        with patch('quickbooks.objects.purchase.Purchase.save', autospec=True) as mock_save:
            def _save(self, qb=None):
                self.Id = 'qbo-purch-1'
            mock_save.side_effect = _save
            qbo_id = QBOExpenseSyncService.push_reimbursement(self.batch)
        self.assertEqual(qbo_id, 'qbo-purch-1')
```

- [ ] **Step 2: Run it — observe the actual failure**

Run: `python manage.py test tests.test_qbo_reimbursement_push -v 2`
Expected: Either PASS (→ the dev failure is **env-only**: no QBO connection — document that and move on) or FAIL with a specific builder error (→ a real payload defect to fix).

- [ ] **Step 3: Branch on the result**

- **If it passes** (env-only): add an explicit assertion that `push_reimbursement` raises a clear `ValueError('No active QBO connection')` when `get_client` returns `None`, confirm `ReimbursementService.create_batch` records that as `qbo_sync_status='sync_failed'` with that message, and confirm `retry_push` works once connected. Document in Task 14 that the dev failure was a missing sandbox connection, and that `retry_sync`/`retry_push` is the recovery path.
- **If it fails** (payload defect): fix the offending field in `_build_qbo_purchase_for_reimbursement` / `_build_expense_line` (most likely: skip or error clearly on a line whose `accounting_category.qbo_expense_account_id` is blank; or set the header `AccountRef`/`PaymentType` correctly via `QBOPaymentAccountService.lookup` + `_derive_payment_type`). Make the characterization test pass.

- [ ] **Step 4: Run tests to verify pass**

Run: `python manage.py test tests.test_qbo_reimbursement_push tests.test_reimbursement_service -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/qbo/services.py tests/test_qbo_reimbursement_push.py
git commit -m "fix(qbo): reimbursement push (root-cause always-sync_failed) + characterization test"
```

---

## Phase 4 — Documentation

### Task 12: Full-suite green gate

Before docs, run everything once to catch cross-module fallout from the renames.

- [ ] **Step 1: Run the whole backend suite**

Run: `python manage.py test -v 1`
Expected: PASS. Fix any remaining `qbo_payment_id` / `Expense.STATUS_SYNCED` / `Reimbursement.STATUS_*` references the per-task runs didn't cover (grep: `grep -rn "qbo_payment_id\|STATUS_SYNCED\|STATUS_SYNC_FAILED" apps/ tests/`).

- [ ] **Step 2: Run the whole frontend suite**

Run: `cd frontend && npm run test:run`
Expected: PASS.

- [ ] **Step 3: Commit any fixups**

```bash
git add -A
git commit -m "test: green full suite after QBO sync consolidation"
```

---

### Task 13: Consolidate QBO save+log boilerplate (`QBOService.save_and_log`)

The per-entity create/update push methods each repeat a `try: obj.save(qb=client); qbo_id=str(obj.Id); log_sync(...success); return qbo_id / except: log_sync(...failed); raise` block. Factor it into one helper. This does NOT merge the per-entity classes (their *builders* genuinely differ); it removes the remaining save+log boilerplate, the level below the `run_create`/`run_resync` orchestration.

**Files:**
- Modify: `apps/qbo/services.py` (add `QBOService.save_and_log`; refactor 7 create + 3 update methods)
- Test: `tests/test_qbo_save_and_log.py` (create)

**Interfaces:**
- Produces: `QBOService.save_and_log(qbo_obj, client, *, entity_type, qbo_entity_type, entity_id, action='create') -> str` — `qbo_obj.save(qb=client)`, write a success `QBOSyncLog` row, return `str(qbo_obj.Id)`; on exception write a failed row (`qbo_entity_id=''`) and re-raise.

**Methods to refactor** (preserve each one's existing `entity_type`/`qbo_entity_type`/`entity_id` and use the right `action`):
- create (`action='create'`): `push_customer`, `push_contact_as_customer`, `push_vendor`, `push_bill`, `_build_qbo_bill_payment`, `push_expense`, `push_reimbursement`
- update (`action='update'`): `update_bill_payment`, `update_expense`, `update_reimbursement`
- **EXCLUDE** (different shape, leave as-is): the `void_*` methods (delete + swallow, never raise) and the invoice push in `InvoiceEmailService.send_invoice` (its `log_sync` lands *after* `_mark_as_sent`, so its sequence differs).

**Behavior must be identical** — same log rows, same return values, same exceptions. The record-id-persistence steps (e.g. `bill.qbo_id = qbo_id; bill.save(update_fields=['qbo_id'])`) move to *after* the `save_and_log` call in the caller (behaviorally equivalent — `log_sync` still records the same `qbo_entity_id`). Verify via the existing push/update tests (they assert the log rows + returns), which must stay green unchanged.

**Steps (TDD):** write `tests/test_qbo_save_and_log.py` (success → logs success + returns `str(Id)`; failure → logs failed with `qbo_entity_id=''` + re-raises) → confirm fail → add `save_and_log` → confirm pass → refactor the 10 methods one cluster at a time, re-running that cluster's tests → commit.

**Green gate (one process):** `python manage.py test tests.test_qbo_save_and_log tests.test_qbo_customer_sync tests.test_qbo_vendor_sync tests.test_qbo_bill_push tests.test_qbo_bill_payment_push tests.test_bill_payment_qbo_lifecycle tests.test_qbo_expense_push tests.test_qbo_reimbursement_push tests.test_expense_service tests.test_reimbursement_service -v 1` — all pass.

---

### Task 14: Correct the invoice-push docs

The QBO doc describes a non-existent `POST /api/invoices/{id}/send-to-qbo/` endpoint + `SendToQBODialog`. Reality: the invoice push is fused into `POST /api/invoices/{id}/send` (`InvoiceEmailService.send_invoice`). Bills are the only `send-to-qbo` endpoint.

**Files:** `docs/designs/quickbooks-integration.md`

- [ ] **Step 1: Fix the three stale spots**

- "Invoice push" entry-point (~line 145): change `Entry point: POST /api/invoices/{id}/send-to-qbo/` to `Entry point: POST /api/invoices/{id}/send (apps/api/invoicing/views.py InvoiceViewSet.send) — the QBO push is fused into the invoice's Send action via InvoiceEmailService.send_invoice; there is no separate send-to-qbo endpoint for invoices.`
- UI section (~308-312): replace the "Send to QuickBooks" button + `SendToQBODialog.svelte` description with the actual Send flow (the Send Email action pushes to QBO if `qbo_id` is unset, then emails both PDFs).
- API endpoints "Push endpoints" table (~331): change the invoice row path to `/api/invoices/{id}/send` and note the push is part of send.

- [ ] **Step 2: Commit**

```bash
git add docs/designs/quickbooks-integration.md
git commit -m "docs(qbo): correct invoice push — fused into /send, no send-to-qbo endpoint"
```

---

### Task 15: Record the bill-payment push, the sync consolidation, the write-off decision; close LATER items

**Files:** `docs/designs/quickbooks-integration.md`, `docs/designs/materials-inventory-and-purchasing.md`, `docs/designs/LATER.md`

- [ ] **Step 1: Update `quickbooks-integration.md`**

- "Bill push → `push_bill_payment` (stubbed seam)" section (~196-200): rewrite to describe the **live** push — builds a QBO `BillPayment` (`VendorRef`, `TotalAmt`, `PayType` from the selected payment account's `account_type`, `CheckPayment`/`CreditCardPayment` account ref, a `Line` with `LinkedTxn`→bill, `DocNumber` from `reference`), writes `qbo_id` back, records `qbo_sync_status`/`qbo_sync_error`. Note edit→`update_bill_payment`, delete→`void_bill_payment`. Note `payment_account_id` is required while QBO is connected, sourced from `Configuration['qbo_payment_accounts']` via the shared `QBOPaymentAccountService`.
- Add a short "Shared sync scaffolding" subsection: `QBOSyncable` base (`qbo_id`/`qbo_sync_status`/`qbo_sync_error` + `mark_synced`/`mark_failed`) adopted by Expense, Reimbursement, BillPayment; `QBOSyncService` orchestrator; `QBOPaymentAccountService`.
- Note the `qbo_payment_id`→`qbo_id` rename on BillPayment and that the push (not polling) writes it; `cleared_date` remains the (deferred) poller's field.
- "Unfinished work": remove the "Bill payment push (live QBO call)" bullet; keep the "Bill clearance polling" bullet (still deferred). Update the bill-clearance-polling section's `qbo_payment_id` references to `qbo_id`.
- Add a "Write-offs are inventory-only" note under expense/inventory mechanics: inventory cost is expensed at purchase time (bills/expenses post to expense/COGS accounts, not a capitalized inventory asset), so a write-off has no QBO consequence; pushing one would double-count. Revisit only if QBO switches to true inventory-asset tracking.

- [ ] **Step 2: Update `materials-inventory-and-purchasing.md`**

- The `BillPayment` field table (~line 1010): rename `qbo_payment_id`→`qbo_id`; add rows for `payment_account_id`, `qbo_sync_status`, `qbo_sync_error`; **remove the `method` row** (field dropped — descriptor now derived from the payment account + reference).

- [ ] **Step 3: Close the LATER.md items**

- "Reimbursement QBO push fails consistently" (2026-06-14): replace with the Task 11 outcome (env-only vs fixed-defect), or delete if fully resolved.
- "Write-off → QBO?" (2026-06-15): delete (decision now recorded in the QBO doc as inventory-only).

- [ ] **Step 4: Commit**

```bash
git add docs/designs/quickbooks-integration.md docs/designs/materials-inventory-and-purchasing.md docs/designs/LATER.md
git commit -m "docs(qbo): bill-payment push + sync consolidation; write-off=inventory-only; close LATER items"
```

---

## Phase 5 — Void symmetry (added mid-branch)

Make the QBO *delete* paths symmetric with create/update: a failed QBO delete must **refuse the local delete and retain the row** marked `sync_failed`, so retrying the delete re-attempts the QBO delete and completes locally on success — instead of silently accepting a QBO↔local mismatch. Confirmed decisions: (1) an already-gone QBO object counts as a successful delete (idempotent), so the local delete completes; (2) retry = re-invoke the delete action, no new state — `sync_failed` + the row's continued existence is the signal; (3) the three delete actions surface the failure to the user the same way other QBO failures surface.

### Task 16: `delete_and_log` + `run_delete` helpers

**Files:** Modify `apps/qbo/services.py`; Test `tests/test_qbo_delete_helpers.py`.

**Interfaces:**
- `QBOService.delete_and_log(qbo_obj, client, *, entity_type, qbo_entity_type, entity_id) -> None` — delete the QBO object; on an **already-gone / not-found** condition, treat as success (log success, return); on a real failure, log failed and **raise** (unlike the old swallow). Logs `action='delete'`.
- `QBOSyncService.run_delete(record, delete_callable) -> None` — run `delete_callable()`; on success return; on exception `record.mark_failed(e)` **and re-raise** (the re-raise aborts the caller's local delete; this is the deliberate difference from `run_create`/`run_resync`, which swallow).

TDD: helper tests for success, not-found-as-success, and failure (logs failed + re-raises; run_delete marks failed + re-raises).

### Task 17: Bill-payment void symmetry

**Files:** `apps/qbo/services.py` (`void_bill_payment` → `delete_and_log`, idempotent, raise); `apps/purchasing/services.py` (`delete_payment`); `apps/api/purchasing/views.py` (the payment-delete action returns 400 on QBO-void failure); tests.

Reorder `delete_payment`: if `payment.qbo_id`, run `QBOSyncService.run_delete(payment, lambda: void_bill_payment(payment))` **before** the local delete; on raise, `mark_failed` has committed and the local `payment.delete()` + bill-status recompute are NOT reached — surface as a 400/ValidationError. On success, proceed.

### Task 18: Expense void symmetry

**Files:** `apps/qbo/services.py` (`void_expense`); `apps/expenses/services.py` (`ExpenseService.delete`); `apps/api/expenses/views.py`; tests.

In `ExpenseService.delete`, run the QBO void (for a non-reimbursed company expense with `qbo_id`) via `run_delete` **before** the stock-receipt reversal + `expense.delete()`; a void failure aborts the whole local unwind (record + its stock/earmark effects stay intact) and surfaces as an error. Keep the existing `if expense.qbo_id and not expense.reimbursement_id` guard (reimbursed expenses void via the batch, not individually).

### Task 19: Reimbursement void symmetry

**Files:** `apps/qbo/services.py` (`void_reimbursement`); `apps/expenses/services.py` (`ReimbursementBatchService.cancel` / the void path); `apps/api/reimbursements/views.py`; tests.

Run the QBO void via `run_delete` **before** the local batch unwind; a failure aborts the unwind and surfaces as an error.

### Task 20: Frontend — surface delete-failure on the three actions

**Files:** the bill-payment delete (`RecordPaymentModal`/`BillDetailPage`), expense delete (`ExpenseListPage`), reimbursement cancel (`UserReimbursementPanel`) handlers.

Each delete/cancel handler now must surface the API error the same way the other QBO failures surface (the global `lib/api.js` overlay / the existing inline error row), so a refused delete tells the user the row was kept and to retry. No new component — match the existing error-surfacing pattern at each site.

---

## Self-Review notes (gaps to watch during execution)

- **Test base names** (`FixtureTestCase`, API test base, login helpers) are referenced from existing tests — confirm exact names in `tests/base.py` and copy the bill/expense/reimbursement construction helpers from `tests/test_qbo_bill_push.py` / `tests/test_reimbursement_service.py` verbatim rather than inventing fixtures.
- **`RenameField` confirmation:** both the BillPayment (`qbo_payment_id`→`qbo_id`) and Reimbursement (`status`→`qbo_sync_status`) migrations must be renames (data-preserving), not drop+add. Hand-edit the generated migration if Django guesses wrong.
- **Reimbursement `create_batch` status init:** ensure no code still writes `batch.status` after the rename; the orchestrator owns `qbo_sync_status` now.
- **PayType source:** the QBO `BillPayment` PayType is driven by the selected **account's** `account_type` (the `method` field is removed entirely this session). An `Other Current Asset` (e.g. Petty Cash for a cash payment) maps to `Check`+`BankAccountRef`; if QBO rejects that account as a bank ref it surfaces as `sync_failed` — acceptable and rare.
- **Polling stays deferred:** Task 3 only renames the field in the polling stub/its test to keep them compiling; no clearance-polling behavior is implemented this session.
```

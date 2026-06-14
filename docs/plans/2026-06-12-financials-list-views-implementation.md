# Financials List Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `can_manage_financials` list views for Invoices (A/R) and Bills (A/P) under a new "Financials" sidebar section, plus an interactive Bill detail/edit/create flow and a reusable `CustomerPicker`.

**Architecture:** Backend adds list serializers + annotated filtering/ordering to the existing `InvoiceViewSet` / `BillViewSet`, and a `BillService.update_bill` + expanded `status_actions` so bill writes go through the service layer (matching house convention). Frontend adds five Svelte routes and one shared dual-source typeahead, reusing existing patterns (`PurchaseOrderListPage`, `InvoiceDetailPage`, `LineItemModal`, `pagination.js`, `.data-table`).

**Tech Stack:** Django 5.2 + DRF (MySQL), Svelte 5 SPA (Vite, svelte-spa-router). Backend tests: Django `TestCase` via `python manage.py test`. Frontend tests: Vitest + `@testing-library/svelte` (`npm run test:run` from `frontend/`).

**Companion spec:** `docs/plans/2026-06-12-financials-list-views-design.md`

**Critical rules (from CLAUDE.md):**
- NEVER run `python manage.py migrate`, `shell`, `loaddata`, or any DB write against the dev DB. Tests use a separate auto-created test DB — that's fine. No model field changes in this plan, so no migrations are needed.
- Decimals are serialized as strings throughout the API.
- All DELETE responses return 200 with a JSON body.
- Run backend tests from only ONE process at a time (shared MySQL test DB).

---

## File Structure

**Backend (modify):**
- `apps/api/invoicing/serializers.py` — add `InvoiceSummarySerializer`.
- `apps/api/invoicing/views.py` — annotated `get_queryset`, `get_serializer_class`.
- `apps/api/purchasing/serializers.py` — extend `BillSummarySerializer`; add `due_date`/`paid_date`/`balance` to `BillSerializer`; make non-editable bill fields read-only.
- `apps/api/purchasing/views.py` — annotated `get_queryset`, `get_serializer_class`, `perform_update`, expanded `status_actions` on `BillViewSet`.
- `apps/purchasing/services.py` — add `BillService.update_bill`.

**Backend (create, tests):**
- `tests/test_api_invoice_list.py`
- `tests/test_api_bill_list.py`
- `tests/test_api_bill_editing.py`

**Frontend (create):**
- `frontend/src/components/CustomerPicker.svelte`
- `frontend/src/routes/invoices/InvoiceListPage.svelte`
- `frontend/src/routes/bills/BillListPage.svelte`
- `frontend/src/routes/bills/BillDetailPage.svelte`
- `frontend/src/routes/bills/BillFormPage.svelte`
- `frontend/tests/components/CustomerPicker.test.js`
- `frontend/tests/components/bills/BillListPage.test.js`

**Frontend (modify):**
- `frontend/src/components/Sidebar.svelte` — Financials section.
- `frontend/src/App.svelte` — register routes.
- `frontend/tests/components/Sidebar.test.js` — Financials section assertions.

**Docs (modify, final task):**
- `docs/designs/invoicing-and-expenses.md`, `docs/designs/materials-inventory-and-purchasing.md`, `docs/designs/architecture-and-conventions.md`.

---

## Phase 1 — Backend: Invoice list endpoint

### Task 1.1: `InvoiceSummarySerializer`

**Files:**
- Modify: `apps/api/invoicing/serializers.py`
- Test: `tests/test_api_invoice_list.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_invoice_list.py`:

```python
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job
from apps.invoicing.models import Invoice, InvoiceLineItem


class InvoiceListAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()

    def _invoice(self, status=Invoice.STATUS_OPEN, sent_days_ago=10,
                 qty='2', price='50.00', paid=None):
        inv = Invoice.objects.create(job=self.job, status=status)
        if sent_days_ago is not None:
            inv.sent_date = timezone.now() - timedelta(days=sent_days_ago)
        if paid is not None:
            inv.qbo_amount_paid = Decimal(paid)
        inv.save()
        InvoiceLineItem.objects.create(
            invoice=inv, line_number=1, description='Work',
            qty=Decimal(qty), units='ea', price=Decimal(price),
        )
        return inv

    def test_list_returns_total_paid_balance_and_customer(self):
        inv = self._invoice(qty='2', price='50.00', paid='30.00')
        resp = self.client.get('/api/invoices/?status=all')
        self.assertEqual(resp.status_code, 200)
        row = next(r for r in resp.data['results'] if r['invoice_id'] == inv.invoice_id)
        self.assertEqual(row['total'], '100.00')
        self.assertEqual(row['amount_paid'], '30.00')
        self.assertEqual(row['balance'], '70.00')
        self.assertIn('customer_name', row)
        self.assertIn('due_date', row)
        # list serializer is lightweight — no nested line_items
        self.assertNotIn('line_items', row)

    def test_null_qbo_amount_paid_treated_as_zero(self):
        inv = self._invoice(qty='1', price='40.00', paid=None)
        resp = self.client.get('/api/invoices/?status=all')
        row = next(r for r in resp.data['results'] if r['invoice_id'] == inv.invoice_id)
        self.assertEqual(row['amount_paid'], '0.00')
        self.assertEqual(row['balance'], '40.00')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_invoice_list -v 2`
Expected: FAIL — `KeyError: 'total'` (or `balance`), since the list serializer doesn't expose these yet.

- [ ] **Step 3: Add the serializer**

In `apps/api/invoicing/serializers.py`, after the existing `InvoiceSerializer` class, add (the module already imports `timedelta`, `Decimal`, `timezone`, `serializers`, `Invoice`, and defines `DEFAULT_INVOICE_NET_DAYS` and `UNPAID_STATUSES`):

```python
class InvoiceSummarySerializer(serializers.ModelSerializer):
    """Lightweight list serializer for the A/R list. Reads total/amount_paid/
    balance/due_date off annotations set by InvoiceViewSet.get_queryset; falls
    back to direct computation if accessed unannotated."""
    job_number = serializers.SerializerMethodField()
    job_name = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    due_date = serializers.SerializerMethodField()
    is_late = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    amount_paid = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            'invoice_id', 'invoice_number', 'status', 'job',
            'job_number', 'job_name', 'customer_name',
            'sent_date', 'due_date', 'is_late',
            'total', 'amount_paid', 'balance',
        ]

    def get_job_number(self, obj):
        return obj.job.job_number if obj.job else None

    def get_job_name(self, obj):
        return getattr(obj.job, 'name', None) if obj.job else None

    def get_customer_name(self, obj):
        contact = obj.job.contact if obj.job else None
        if not contact:
            return None
        if contact.business:
            return contact.business.business_name
        return contact.name

    def get_due_date(self, obj):
        if not obj.sent_date:
            return None
        due = obj.sent_date + timedelta(days=DEFAULT_INVOICE_NET_DAYS)
        return due.date().isoformat()

    def get_is_late(self, obj):
        if not obj.sent_date or obj.status not in UNPAID_STATUSES:
            return False
        due = obj.sent_date + timedelta(days=DEFAULT_INVOICE_NET_DAYS)
        return due < timezone.now()

    def get_total(self, obj):
        return str(getattr(obj, 'total_anno', None) or Decimal('0.00'))

    def get_amount_paid(self, obj):
        return str(getattr(obj, 'amount_paid_anno', None)
                   if getattr(obj, 'amount_paid_anno', None) is not None
                   else (obj.qbo_amount_paid or Decimal('0.00')))

    def get_balance(self, obj):
        return str(getattr(obj, 'balance_anno', None) or Decimal('0.00'))
```

- [ ] **Step 4: Wire `get_serializer_class` + annotations (see Task 1.2)**

This test passes only once Task 1.2 adds the annotations and `get_serializer_class`. Implement Task 1.2 now, then return here.

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_api_invoice_list -v 2`
Expected: PASS (after Task 1.2).

- [ ] **Step 6: Commit**

```bash
git add apps/api/invoicing/serializers.py apps/api/invoicing/views.py tests/test_api_invoice_list.py
git commit -m "Invoice list: summary serializer with total/paid/balance/customer"
```

### Task 1.2: Annotated filtering + ordering on `InvoiceViewSet`

**Files:**
- Modify: `apps/api/invoicing/views.py`
- Test: `tests/test_api_invoice_list.py` (add cases)

- [ ] **Step 1: Add filter/order tests**

Append to `tests/test_api_invoice_list.py` inside the class:

```python
    def test_default_filter_is_open_plus_partly_paid(self):
        open_inv = self._invoice(status=Invoice.STATUS_OPEN)
        partly = self._invoice(status=Invoice.STATUS_PARTLY_PAID)
        draft = self._invoice(status=Invoice.STATUS_DRAFT, sent_days_ago=None)
        paid = self._invoice(status=Invoice.STATUS_PAID)
        resp = self.client.get('/api/invoices/')  # no status param
        ids = {r['invoice_id'] for r in resp.data['results']}
        self.assertIn(open_inv.invoice_id, ids)
        self.assertIn(partly.invoice_id, ids)
        self.assertNotIn(draft.invoice_id, ids)
        self.assertNotIn(paid.invoice_id, ids)

    def test_status_paid_preset(self):
        paid = self._invoice(status=Invoice.STATUS_PAID)
        open_inv = self._invoice(status=Invoice.STATUS_OPEN)
        resp = self.client.get('/api/invoices/?status=paid')
        ids = {r['invoice_id'] for r in resp.data['results']}
        self.assertIn(paid.invoice_id, ids)
        self.assertNotIn(open_inv.invoice_id, ids)

    def test_default_ordering_is_due_date_ascending(self):
        # earlier sent_date => earlier due_date => most overdue => first
        old = self._invoice(sent_days_ago=60)
        recent = self._invoice(sent_days_ago=5)
        resp = self.client.get('/api/invoices/?status=open')
        ordered = [r['invoice_id'] for r in resp.data['results']]
        self.assertLess(ordered.index(old.invoice_id),
                        ordered.index(recent.invoice_id))

    def test_filter_by_business_rolls_up_contacts(self):
        contact = self.job.contact
        self.assertIsNotNone(contact)
        inv = self._invoice(status=Invoice.STATUS_OPEN)
        if contact.business:
            resp = self.client.get(
                f'/api/invoices/?status=all&business={contact.business_id}')
            ids = {r['invoice_id'] for r in resp.data['results']}
            self.assertIn(inv.invoice_id, ids)

    def test_filter_by_contact_exact(self):
        contact = self.job.contact
        inv = self._invoice(status=Invoice.STATUS_OPEN)
        resp = self.client.get(
            f'/api/invoices/?status=all&contact={contact.contact_id}')
        ids = {r['invoice_id'] for r in resp.data['results']}
        self.assertIn(inv.invoice_id, ids)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_api_invoice_list -v 2`
Expected: FAIL — default returns all statuses / wrong ordering (filters not implemented).

- [ ] **Step 3: Replace `InvoiceViewSet.get_queryset` and add `get_serializer_class`**

In `apps/api/invoicing/views.py`, add imports at top:

```python
from datetime import timedelta
from django.db.models import (
    F, Sum, Value, DecimalField, DateTimeField, ExpressionWrapper,
)
from django.db.models.functions import Coalesce
from apps.api.invoicing.serializers import InvoiceSummarySerializer
```

Add these module-level constants (after imports):

```python
_MONEY = DecimalField(max_digits=12, decimal_places=2)

INVOICE_STATUS_PRESETS = {
    'open': [Invoice.STATUS_OPEN, Invoice.STATUS_PARTLY_PAID],
    'paid': [Invoice.STATUS_PAID],
    'draft': [Invoice.STATUS_DRAFT],
    'cancelled': [Invoice.STATUS_CANCELLED],
}

INVOICE_ORDERING = {
    'due_date': F('due_date_anno').asc(nulls_last=True),
    '-due_date': F('due_date_anno').desc(nulls_last=True),
    '-balance': F('balance_anno').desc(nulls_last=True),
    '-total': F('total_anno').desc(nulls_last=True),
    'customer_name': F('customer_sort').asc(nulls_last=True),
    '-sent_date': F('sent_date').desc(nulls_last=True),
}
```

Add to the `InvoiceViewSet` body:

```python
    def get_serializer_class(self):
        if self.action == 'list':
            return InvoiceSummarySerializer
        return InvoiceSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        job = self.request.query_params.get('job')
        if job:
            qs = qs.filter(job_id=job)

        qs = qs.annotate(
            total_anno=Coalesce(
                Sum(ExpressionWrapper(
                    F('invoicelineitem__qty') * F('invoicelineitem__price'),
                    output_field=_MONEY)),
                Value(0), output_field=_MONEY),
            amount_paid_anno=Coalesce(F('qbo_amount_paid'), Value(0),
                                      output_field=_MONEY),
            due_date_anno=ExpressionWrapper(
                F('sent_date') + timedelta(days=30),
                output_field=DateTimeField()),
            customer_sort=Coalesce(
                F('job__contact__business__business_name'),
                F('job__contact__last_name'),
                Value('')),
        ).annotate(
            balance_anno=ExpressionWrapper(
                F('total_anno') - F('amount_paid_anno'), output_field=_MONEY),
        )

        status_param = self.request.query_params.get('status', 'open')
        if status_param != 'all':
            statuses = INVOICE_STATUS_PRESETS.get(status_param)
            if statuses is not None:
                qs = qs.filter(status__in=statuses)

        business = self.request.query_params.get('business')
        if business:
            qs = qs.filter(job__contact__business_id=business)
        contact = self.request.query_params.get('contact')
        if contact:
            qs = qs.filter(job__contact_id=contact)

        due_from = self.request.query_params.get('due_from')
        if due_from:
            qs = qs.filter(due_date_anno__date__gte=due_from)
        due_to = self.request.query_params.get('due_to')
        if due_to:
            qs = qs.filter(due_date_anno__date__lte=due_to)

        ordering = self.request.query_params.get('ordering', 'due_date')
        return qs.order_by(INVOICE_ORDERING.get(ordering,
                                                INVOICE_ORDERING['due_date']))
```

> If `InvoiceViewSet` already had a `get_queryset` that only filtered `?job=`, replace it entirely with the above (the `?job=` filter is preserved at the top).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_api_invoice_list -v 2`
Expected: PASS (all cases, including Task 1.1's).

- [ ] **Step 5: Commit** (combined with Task 1.1's commit if not yet committed)

```bash
git add apps/api/invoicing/views.py tests/test_api_invoice_list.py
git commit -m "Invoice list: status presets, customer filter, due-date range/sort"
```

---

## Phase 2 — Backend: Bill list endpoint

### Task 2.1: Extend `BillSummarySerializer` + annotated filtering/ordering

**Files:**
- Modify: `apps/api/purchasing/serializers.py`, `apps/api/purchasing/views.py`
- Test: `tests/test_api_bill_list.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_bill_list.py`:

```python
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.contacts.models import Business
from apps.purchasing.models import Bill, BillLineItem


class BillListAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.vendor = Business.objects.first()

    def _bill(self, status=Bill.STATUS_RECEIVED, due_days=10,
              qty='2', price='25.00', number='V-100'):
        bill = Bill.objects.create(
            business=self.vendor, vendor_invoice_number=number, status=status,
            due_date=timezone.now() + timedelta(days=due_days),
        )
        BillLineItem.objects.create(
            bill=bill, line_number=1, description='Parts',
            qty=Decimal(qty), units='ea', price=Decimal(price),
        )
        return bill

    def test_list_exposes_vendor_total_balance_and_dates(self):
        bill = self._bill(qty='2', price='25.00')  # total 50
        resp = self.client.get('/api/bills/?status=all')
        self.assertEqual(resp.status_code, 200)
        row = next(r for r in resp.data['results'] if r['bill_id'] == bill.bill_id)
        self.assertEqual(row['vendor_name'], self.vendor.business_name)
        self.assertEqual(row['total'], '50.00')
        self.assertEqual(row['balance'], '50.00')  # received => full balance
        self.assertIn('due_date', row)
        self.assertIn('received_date', row)

    def test_paid_in_full_balance_is_zero(self):
        bill = self._bill(status=Bill.STATUS_PAID_IN_FULL)
        resp = self.client.get('/api/bills/?status=all')
        row = next(r for r in resp.data['results'] if r['bill_id'] == bill.bill_id)
        self.assertEqual(row['balance'], '0.00')

    def test_default_filter_is_open(self):
        received = self._bill(status=Bill.STATUS_RECEIVED, number='V-OPEN')
        draft = self._bill(status=Bill.STATUS_DRAFT, number='V-DRAFT')
        paid = self._bill(status=Bill.STATUS_PAID_IN_FULL, number='V-PAID')
        resp = self.client.get('/api/bills/')  # no status param
        ids = {r['bill_id'] for r in resp.data['results']}
        self.assertIn(received.bill_id, ids)
        self.assertNotIn(draft.bill_id, ids)
        self.assertNotIn(paid.bill_id, ids)

    def test_default_ordering_due_date_ascending(self):
        soonest = self._bill(due_days=2, number='V-SOON')
        latest = self._bill(due_days=40, number='V-LATE')
        resp = self.client.get('/api/bills/?status=open')
        ordered = [r['bill_id'] for r in resp.data['results']]
        self.assertLess(ordered.index(soonest.bill_id),
                        ordered.index(latest.bill_id))
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_api_bill_list -v 2`
Expected: FAIL — `KeyError: 'vendor_name'` / default returns all statuses.

- [ ] **Step 3: Extend the bill summary serializer**

In `apps/api/purchasing/serializers.py`, replace the `BillSummarySerializer` class with:

```python
class BillSummarySerializer(serializers.ModelSerializer):
    contact_name = serializers.SerializerMethodField()
    vendor_name = serializers.SerializerMethodField()
    po_number = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    def get_contact_name(self, obj):
        return obj.contact.name if obj.contact else None

    def get_vendor_name(self, obj):
        return obj.business.business_name if obj.business else None

    def get_po_number(self, obj):
        return obj.purchase_order.po_number if obj.purchase_order else None

    def get_total(self, obj):
        return str(getattr(obj, 'total_anno', None) or Decimal('0.00'))

    def get_balance(self, obj):
        return str(getattr(obj, 'balance_anno', None) or Decimal('0.00'))

    class Meta:
        model = Bill
        fields = ['bill_id', 'status', 'vendor_invoice_number', 'created_date',
                  'due_date', 'received_date', 'contact_name', 'vendor_name',
                  'po_number', 'total', 'balance']
```

Ensure `from decimal import Decimal` is imported at the top of the file (add if missing).

- [ ] **Step 4: Add annotations, presets, ordering, and `get_serializer_class` to `BillViewSet`**

In `apps/api/purchasing/views.py`, add imports:

```python
from django.db.models import (
    F, Sum, Value, Case, When, DecimalField, ExpressionWrapper,
)
from django.db.models.functions import Coalesce
from apps.api.purchasing.serializers import BillSummarySerializer
```

Add module-level constants:

```python
_BILL_MONEY = DecimalField(max_digits=12, decimal_places=2)

BILL_STATUS_PRESETS = {
    'open': [Bill.STATUS_RECEIVED, Bill.STATUS_PARTLY_PAID],
    'paid': [Bill.STATUS_PAID_IN_FULL],
    'draft': [Bill.STATUS_DRAFT],
    'cancelled': [Bill.STATUS_CANCELLED],
    'refunded': [Bill.STATUS_REFUNDED],
}

BILL_ORDERING = {
    'due_date': F('due_date').asc(nulls_last=True),
    '-due_date': F('due_date').desc(nulls_last=True),
    '-balance': F('balance_anno').desc(nulls_last=True),
    '-total': F('total_anno').desc(nulls_last=True),
    'vendor_name': F('business__business_name').asc(nulls_last=True),
    '-received_date': F('received_date').desc(nulls_last=True),
}
```

Replace `BillViewSet.get_queryset` with (preserving the existing business/contact filters) and add `get_serializer_class`:

```python
    def get_serializer_class(self):
        if self.action == 'list':
            return BillSummarySerializer
        return BillSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        qs = qs.annotate(
            total_anno=Coalesce(
                Sum(ExpressionWrapper(
                    F('billlineitem__qty') * F('billlineitem__price'),
                    output_field=_BILL_MONEY)),
                Value(0), output_field=_BILL_MONEY),
        ).annotate(
            balance_anno=Case(
                When(status__in=[Bill.STATUS_PAID_IN_FULL,
                                 Bill.STATUS_CANCELLED,
                                 Bill.STATUS_REFUNDED],
                     then=Value(0, output_field=_BILL_MONEY)),
                default=F('total_anno'),
                output_field=_BILL_MONEY),
        )

        status_param = self.request.query_params.get('status', 'open')
        if status_param != 'all':
            statuses = BILL_STATUS_PRESETS.get(status_param)
            if statuses is not None:
                qs = qs.filter(status__in=statuses)

        business = self.request.query_params.get('business')
        if business:
            qs = qs.filter(business_id=business)
        contact = self.request.query_params.get('contact')
        if contact:
            qs = qs.filter(contact_id=contact)

        due_from = self.request.query_params.get('due_from')
        if due_from:
            qs = qs.filter(due_date__date__gte=due_from)
        due_to = self.request.query_params.get('due_to')
        if due_to:
            qs = qs.filter(due_date__date__lte=due_to)

        ordering = self.request.query_params.get('ordering', 'due_date')
        return qs.order_by(BILL_ORDERING.get(ordering, BILL_ORDERING['due_date']))
```

> If the existing `get_queryset` only did business/contact filtering, replace it entirely with the above (those filters are preserved). Keep the class's existing `queryset = Bill.objects.all().order_by('-created_date')` attribute — the explicit `order_by` here overrides per-request.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_api_bill_list -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/purchasing/serializers.py apps/api/purchasing/views.py tests/test_api_bill_list.py
git commit -m "Bill list: vendor/total/coarse-balance + status presets, due sort/filter"
```

---

## Phase 3 — Backend: Bill detail serializer

### Task 3.1: Add `due_date`, `paid_date`, coarse `balance` to `BillSerializer`

**Files:**
- Modify: `apps/api/purchasing/serializers.py`
- Test: `tests/test_api_bill_editing.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_bill_editing.py`:

```python
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.contacts.models import Business
from apps.purchasing.models import Bill, BillLineItem


class BillDetailSerializerTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.vendor = Business.objects.first()

    def test_detail_includes_due_paid_and_balance(self):
        bill = Bill.objects.create(
            business=self.vendor, vendor_invoice_number='V-DET',
            status=Bill.STATUS_RECEIVED,
            due_date=timezone.now() + timedelta(days=15),
        )
        BillLineItem.objects.create(
            bill=bill, line_number=1, description='X',
            qty=Decimal('3'), units='ea', price=Decimal('10.00'))
        resp = self.client.get(f'/api/bills/{bill.bill_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('due_date', resp.data)
        self.assertIn('paid_date', resp.data)
        self.assertEqual(resp.data['balance'], '30.00')
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_api_bill_editing.BillDetailSerializerTest -v 2`
Expected: FAIL — `'balance'`/`'due_date'` not in response.

- [ ] **Step 3: Update `BillSerializer`**

In `apps/api/purchasing/serializers.py`, replace the `BillSerializer` class with:

```python
class BillSerializer(serializers.ModelSerializer):
    line_items = BillLineItemSerializer(
        source='billlineitem_set', many=True, read_only=True
    )
    po_number = serializers.SerializerMethodField()
    vendor_name = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Bill
        fields = [
            'bill_id', 'purchase_order', 'po_number',
            'vendor_invoice_number', 'business', 'vendor_name', 'contact',
            'status', 'created_date', 'due_date', 'received_date',
            'paid_date', 'cancelled_date', 'line_items', 'balance',
            'qbo_id', 'qbo_payment_status',
        ]
        read_only_fields = [
            'bill_id', 'status', 'created_date', 'received_date',
            'paid_date', 'cancelled_date', 'qbo_id', 'qbo_payment_status',
        ]

    def get_po_number(self, obj):
        return obj.purchase_order.po_number if obj.purchase_order else None

    def get_vendor_name(self, obj):
        return obj.business.business_name if obj.business else None

    def get_balance(self, obj):
        if obj.status in (Bill.STATUS_PAID_IN_FULL, Bill.STATUS_CANCELLED,
                          Bill.STATUS_REFUNDED):
            return '0.00'
        total = sum((li.qty * li.price for li in obj.billlineitem_set.all()),
                    Decimal('0'))
        return str(total)
```

> `status`, `received_date`, `paid_date`, `cancelled_date` are now read-only — status moves only through the `status_actions` (Phase 4), and those dates are stamped by `Bill.save()`. `business`, `contact`, `vendor_invoice_number`, `due_date`, `purchase_order` remain writable for create/update.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_bill_editing.BillDetailSerializerTest -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/purchasing/serializers.py tests/test_api_bill_editing.py
git commit -m "Bill detail serializer: due_date, paid_date, vendor_name, coarse balance"
```

---

## Phase 4 — Backend: Bill editing (service + viewset)

### Task 4.1: `BillService.update_bill`

**Files:**
- Modify: `apps/purchasing/services.py`
- Test: `tests/test_api_bill_editing.py` (add class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_bill_editing.py`:

```python
from apps.purchasing.services import BillService
from django.core.exceptions import ValidationError


class BillUpdateServiceTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.vendor = Business.objects.first()

    def test_update_bill_changes_header_on_draft(self):
        bill = Bill.objects.create(business=self.vendor,
                                   vendor_invoice_number='OLD',
                                   status=Bill.STATUS_DRAFT)
        BillService.update_bill(bill.pk, vendor_invoice_number='NEW')
        bill.refresh_from_db()
        self.assertEqual(bill.vendor_invoice_number, 'NEW')

    def test_update_bill_rejected_on_non_draft(self):
        bill = Bill.objects.create(business=self.vendor,
                                   vendor_invoice_number='LOCK',
                                   status=Bill.STATUS_RECEIVED)
        with self.assertRaises(ValidationError):
            BillService.update_bill(bill.pk, vendor_invoice_number='NOPE')
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_api_bill_editing.BillUpdateServiceTest -v 2`
Expected: FAIL — `AttributeError: type object 'BillService' has no attribute 'update_bill'`.

- [ ] **Step 3: Add the method**

In `apps/purchasing/services.py`, inside `class BillService`, add after `create_bill_from_po` (the module already imports `ValidationError`, `NotFoundError`, `Bill`):

```python
    @staticmethod
    def update_bill(pk, **kwargs):
        """Update a draft bill's header fields. Draft-only."""
        try:
            bill = Bill.objects.get(pk=pk)
        except Bill.DoesNotExist:
            raise NotFoundError(f'Bill {pk} not found')
        if bill.status != Bill.STATUS_DRAFT:
            raise ValidationError('Can only edit draft bills.')
        for field, value in kwargs.items():
            setattr(bill, field, value)
        bill.full_clean()
        bill.save()
        return bill
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_bill_editing.BillUpdateServiceTest -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/purchasing/services.py tests/test_api_bill_editing.py
git commit -m "BillService.update_bill: draft-only header update"
```

### Task 4.2: `perform_update` + expanded `status_actions`

**Files:**
- Modify: `apps/api/purchasing/views.py`
- Test: `tests/test_api_bill_editing.py` (add class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_bill_editing.py`:

```python
class BillEditingAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.admin = User.objects.get(username='admin')
        self.worker = User.objects.get(username='johnq')
        self.client.force_authenticate(user=self.admin)
        self.vendor = Business.objects.first()

    def _draft(self, number='V-EDIT'):
        return Bill.objects.create(business=self.vendor,
                                   vendor_invoice_number=number,
                                   status=Bill.STATUS_DRAFT)

    def _draft_with_line(self, number='V-LINE'):
        bill = self._draft(number)
        BillLineItem.objects.create(bill=bill, line_number=1, description='X',
                                    qty=Decimal('1'), units='ea',
                                    price=Decimal('5.00'))
        return bill

    def test_patch_updates_draft_header(self):
        bill = self._draft()
        resp = self.client.patch(f'/api/bills/{bill.bill_id}/',
                                 {'vendor_invoice_number': 'V-NEW'},
                                 format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        bill.refresh_from_db()
        self.assertEqual(bill.vendor_invoice_number, 'V-NEW')

    def test_patch_non_draft_rejected(self):
        bill = self._draft_with_line('V-RX')
        self.client.post(f'/api/bills/{bill.bill_id}/receive/', format='json')
        resp = self.client.patch(f'/api/bills/{bill.bill_id}/',
                                 {'vendor_invoice_number': 'V-NO'},
                                 format='json')
        self.assertEqual(resp.status_code, 400)

    def test_receive_requires_line_item(self):
        bill = self._draft('V-EMPTY')
        resp = self.client.post(f'/api/bills/{bill.bill_id}/receive/',
                                format='json')
        self.assertEqual(resp.status_code, 400)

    def test_receive_then_mark_paid(self):
        bill = self._draft_with_line('V-PAY')
        r1 = self.client.post(f'/api/bills/{bill.bill_id}/receive/',
                              format='json')
        self.assertEqual(r1.status_code, 200, r1.data)
        bill.refresh_from_db()
        self.assertEqual(bill.status, Bill.STATUS_RECEIVED)
        r2 = self.client.post(f'/api/bills/{bill.bill_id}/mark_paid/',
                              format='json')
        self.assertEqual(r2.status_code, 200, r2.data)
        bill.refresh_from_db()
        self.assertEqual(bill.status, Bill.STATUS_PAID_IN_FULL)
        self.assertIsNotNone(bill.paid_date)

    def test_cancel_requires_reason(self):
        bill = self._draft_with_line('V-CXL')
        self.client.post(f'/api/bills/{bill.bill_id}/receive/', format='json')
        resp = self.client.post(f'/api/bills/{bill.bill_id}/cancel/',
                                format='json')
        self.assertEqual(resp.status_code, 400)

    def test_worker_cannot_edit(self):
        bill = self._draft('V-PERM')
        self.client.force_authenticate(user=self.worker)
        resp = self.client.patch(f'/api/bills/{bill.bill_id}/',
                                 {'vendor_invoice_number': 'V-X'},
                                 format='json')
        self.assertEqual(resp.status_code, 403)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_api_bill_editing.BillEditingAPITest -v 2`
Expected: FAIL — `receive`/`mark_paid` actions 404 (not registered); PATCH on non-draft may 200 (bypasses service).

- [ ] **Step 3: Add `perform_update` and expand `status_actions`**

In `apps/api/purchasing/views.py`, add import at top:

```python
from apps.purchasing.services import BillService
```

(`BillService` may already be imported — check; don't duplicate.)

Replace `BillViewSet.status_actions` with:

```python
    status_actions = {
        'receive': {
            'service': lambda pk, reason=None: BillService.update_status(
                pk, Bill.STATUS_RECEIVED),
        },
        'mark_paid': {
            'service': lambda pk, reason=None: BillService.update_status(
                pk, Bill.STATUS_PAID_IN_FULL),
        },
        'cancel': {
            'service': lambda pk, reason=None: BillService.update_status(
                pk, Bill.STATUS_CANCELLED),
            'requires_reason': True,
        },
    }
```

Add a `perform_update` method to `BillViewSet`:

```python
    def perform_update(self, serializer):
        bill = BillService.update_bill(
            serializer.instance.pk, **serializer.validated_data)
        serializer.instance = bill
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_api_bill_editing -v 2`
Expected: PASS (all classes in the file).

- [ ] **Step 5: Run the broader purchasing/invoicing suites for regressions**

Run: `python manage.py test tests.test_api_purchasing tests.test_api_invoicing tests.test_bill_status_transitions tests.test_api_line_item_mixin -v 2`
Expected: PASS (no regressions from the serializer read-only changes or status_actions).

- [ ] **Step 6: Commit**

```bash
git add apps/api/purchasing/views.py tests/test_api_bill_editing.py
git commit -m "Bill editing API: perform_update via service + receive/mark_paid actions"
```

---

## Phase 5 — Frontend: CustomerPicker

### Task 5.1: `CustomerPicker.svelte`

**Files:**
- Create: `frontend/src/components/CustomerPicker.svelte`
- Test: `frontend/tests/components/CustomerPicker.test.js`

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/components/CustomerPicker.test.js`:

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import CustomerPicker from '@/components/CustomerPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('CustomerPicker', () => {
  it('merges business + contact results and tags them', async () => {
    api.get.mockImplementation((url) => {
      if (url.includes('/api/businesses/')) {
        return Promise.resolve({ results: [{ business_id: 1, business_name: 'Acme' }] });
      }
      return Promise.resolve({
        results: [{ contact_id: 9, name: 'Jane Roe', business: { business_name: 'Acme' } }],
      });
    });

    const { getByPlaceholderText, findByText } = render(CustomerPicker);
    await fireEvent.input(getByPlaceholderText(/customer or vendor/i),
      { target: { value: 'ac' } });

    expect(await findByText(/Acme \(business\)/)).toBeInTheDocument();
    expect(await findByText(/Jane Roe.*\(contact\)/)).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/businesses/?search=ac&page_size=10');
    expect(api.get).toHaveBeenCalledWith('/api/contacts/?search=ac&page_size=10');
  });

  it('emits {type,id} on select and shows a Clear button', async () => {
    api.get.mockImplementation((url) =>
      url.includes('/api/businesses/')
        ? Promise.resolve({ results: [{ business_id: 1, business_name: 'Acme' }] })
        : Promise.resolve({ results: [] }));

    const onSelect = vi.fn();
    const { getByPlaceholderText, findByText, getByRole } =
      render(CustomerPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText(/customer or vendor/i),
      { target: { value: 'ac' } });
    await fireEvent.mouseDown(await findByText(/Acme \(business\)/));

    expect(onSelect).toHaveBeenCalledWith({ type: 'business', id: 1 });
    expect(getByRole('button', { name: 'Clear' })).toBeInTheDocument();
  });

  it('does not hit the server for a blank query', async () => {
    const { getByPlaceholderText } = render(CustomerPicker);
    await fireEvent.input(getByPlaceholderText(/customer or vendor/i),
      { target: { value: '  ' } });
    expect(api.get).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run (from `frontend/`): `npm run test:run -- CustomerPicker`
Expected: FAIL — component file does not exist.

- [ ] **Step 3: Create the component**

Create `frontend/src/components/CustomerPicker.svelte`:

```svelte
<script>
  // Dual-source typeahead for picking a customer OR vendor. Searches both
  // /api/contacts/ and /api/businesses/ in parallel and merges the results,
  // emitting { type: 'business' | 'contact', id }. Reusable wherever a party
  // needs picking. ContactPicker/JobPicker are left untouched.
  import { api } from '../lib/api.js';

  let { value = $bindable(null), onSelect = () => {} } = $props();

  let query = $state('');
  let results = $state([]);
  let showResults = $state(false);
  let selectedLabel = $state('');

  function businessLabel(b) {
    return `${b.business_name} (business)`;
  }
  function contactLabel(c) {
    const base = c.business ? `${c.name} — ${c.business.business_name}` : c.name;
    return `${base} (contact)`;
  }

  async function search() {
    const q = query.trim();
    if (!q) { results = []; showResults = false; return; }
    try {
      const [businesses, contacts] = await Promise.all([
        api.get(`/api/businesses/?search=${encodeURIComponent(q)}&page_size=10`),
        api.get(`/api/contacts/?search=${encodeURIComponent(q)}&page_size=10`),
      ]);
      const bRows = (businesses.results || businesses).map((b) => ({
        type: 'business', id: b.business_id, label: businessLabel(b),
      }));
      const cRows = (contacts.results || contacts).map((c) => ({
        type: 'contact', id: c.contact_id, label: contactLabel(c),
      }));
      results = [...bRows, ...cRows];
      showResults = true;
    } catch (e) {
      console.error(e);
    }
  }

  function pick(row) {
    value = { type: row.type, id: row.id };
    selectedLabel = row.label;
    query = '';
    results = [];
    showResults = false;
    onSelect(value);
  }

  function clear() {
    value = null;
    selectedLabel = '';
    query = '';
    results = [];
    showResults = false;
    onSelect(null);
  }
</script>

{#if value}
  <span>{selectedLabel} <button type="button" onclick={clear}>Clear</button></span>
{:else}
  <input type="text" bind:value={query} oninput={search}
         placeholder="Search customer or vendor…">
  {#if showResults && results.length}
    <ul>
      {#each results as row (row.type + ':' + row.id)}
        <li><button type="button" onmousedown={() => pick(row)}>{row.label}</button></li>
      {/each}
    </ul>
  {/if}
{/if}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npm run test:run -- CustomerPicker`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CustomerPicker.svelte frontend/tests/components/CustomerPicker.test.js
git commit -m "CustomerPicker: dual-source contact+business typeahead"
```

---

## Phase 6 — Frontend: Sidebar Financials section

### Task 6.1: Add Financials group, move Expenses

**Files:**
- Modify: `frontend/src/components/Sidebar.svelte`
- Test: `frontend/tests/components/Sidebar.test.js`

- [ ] **Step 1: Read the existing Sidebar test to learn how it stubs the auth/permission stores**

Run (from repo root): `sed -n '1,40p' frontend/tests/components/Sidebar.test.js`
Note how `user`/permission stores are set (likely by setting the `user` writable with a `permissions` array). Mirror that exact mechanism in Step 2.

- [ ] **Step 2: Add a failing test**

Add to `frontend/tests/components/Sidebar.test.js` (adapt the store-setup lines to match the existing file's pattern found in Step 1):

```javascript
  it('shows the Financials section with Invoices and Bills for financials users', async () => {
    // set the user store to a can_manage_financials user (match existing helper)
    setUser({ username: 'fin', permissions: ['can_manage_financials'] });
    const { getByText, queryByText } = render(Sidebar, { props: { open: true } });
    expect(getByText('Financials')).toBeInTheDocument();
    expect(getByText('Invoices')).toBeInTheDocument();
    expect(getByText('Bills')).toBeInTheDocument();
    expect(getByText('Expenses')).toBeInTheDocument();
  });

  it('hides Financials for users without the atom', async () => {
    setUser({ username: 'worker', permissions: [] });
    const { queryByText } = render(Sidebar, { props: { open: true } });
    expect(queryByText('Financials')).not.toBeInTheDocument();
    expect(queryByText('Invoices')).not.toBeInTheDocument();
  });
```

> Replace `setUser(...)` with whatever helper/import the existing test uses to populate the auth store. If the file has no such helper, import `{ user } from '@/stores/auth.js'` and call `user.set({...})` inside the test.

- [ ] **Step 3: Run to verify failure**

Run (from `frontend/`): `npm run test:run -- Sidebar`
Expected: FAIL — no "Financials" / "Invoices" / "Bills" text.

- [ ] **Step 4: Edit the Sidebar markup**

In `frontend/src/components/Sidebar.svelte`, replace the nav block from the Purchasing link through the Settings link (lines ~65–77) with:

```svelte
    <a href="/purchase-orders" use:link>Purchasing</a>
    {#if showFinancials}
      <div class="section-label">Financials</div>
      <a href="/invoices" use:link>Invoices</a>
      <a href="/bills" use:link>Bills</a>
      <a href="/expenses" use:link>Expenses</a>
    {/if}
    {#if $canManageConfig}
      <div class="section-label">Admin</div>
      <a href="/users" use:link>Users</a>
      <a href="/settings" use:link>Settings</a>
    {/if}
```

Then in the `<script>`, remove the now-unused `showAdminLabel` derived (keep `showFinancials`):

```javascript
  let showFinancials = $derived($canManageFinancials);
```

(Delete the line `let showAdminLabel = $derived($canManageFinancials || $canManageConfig);`.)

- [ ] **Step 5: Run tests to verify they pass**

Run (from `frontend/`): `npm run test:run -- Sidebar`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Sidebar.svelte frontend/tests/components/Sidebar.test.js
git commit -m "Sidebar: Financials section (Invoices, Bills, Expenses); Admin = config-only"
```

---

## Phase 7 — Frontend: Invoice list page

### Task 7.1: `InvoiceListPage.svelte`

**Files:**
- Create: `frontend/src/routes/invoices/InvoiceListPage.svelte`

- [ ] **Step 1: Create the page**

Create `frontend/src/routes/invoices/InvoiceListPage.svelte`:

```svelte
<script>
  import { api } from '../../lib/api.js';
  import { pageRange, pageFromUrl } from '../../lib/pagination.js';
  import CustomerPicker from '../../components/CustomerPicker.svelte';

  let invoices = $state(null);
  let page = $state(1);
  let loading = $state(true);
  let error = $state(null);
  let statusFilter = $state('open');
  let ordering = $state('due_date');
  let dueFrom = $state('');
  let dueTo = $state('');
  let customer = $state(null);

  function customerParam() {
    if (!customer) return '';
    return customer.type === 'business'
      ? `&business=${customer.id}` : `&contact=${customer.id}`;
  }

  async function load() {
    loading = true;
    error = null;
    try {
      let url = `/api/invoices/?page=${page}&status=${statusFilter}&ordering=${ordering}`;
      if (dueFrom) url += `&due_from=${dueFrom}`;
      if (dueTo) url += `&due_to=${dueTo}`;
      url += customerParam();
      invoices = await api.get(url);
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function money(v) { return v == null ? '' : `$${v}`; }

  $effect(() => {
    void page; void statusFilter; void ordering; void dueFrom; void dueTo; void customer;
    load();
  });
</script>

<h2>Invoices {invoices ? `(${invoices.count})` : ''}</h2>

<p>
  <label>Status:
    <select bind:value={statusFilter} onchange={() => { page = 1; }}>
      <option value="open">Open</option>
      <option value="paid">Paid</option>
      <option value="draft">Draft</option>
      <option value="cancelled">Cancelled</option>
      <option value="all">All</option>
    </select>
  </label>
  &nbsp;
  <label>Sort:
    <select bind:value={ordering} onchange={() => { page = 1; }}>
      <option value="due_date">Due date ↑</option>
      <option value="-due_date">Due date ↓</option>
      <option value="-balance">Balance ↓</option>
      <option value="-total">Amount ↓</option>
      <option value="customer_name">Customer A–Z</option>
      <option value="-sent_date">Sent ↓</option>
    </select>
  </label>
  &nbsp;
  <label>Due from <input type="date" bind:value={dueFrom} onchange={() => { page = 1; }}></label>
  <label>to <input type="date" bind:value={dueTo} onchange={() => { page = 1; }}></label>
</p>
<p>
  <label>Customer:
    <CustomerPicker bind:value={customer} onSelect={() => { page = 1; }} />
  </label>
</p>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else if invoices}
  <table class="data-table">
    <thead>
      <tr>
        <th>Invoice #</th><th>Job</th><th>Customer</th><th>Status</th>
        <th>Sent</th><th>Due</th>
        <th class="text-right">Amount</th><th class="text-right">Paid</th>
        <th class="text-right">Balance</th>
      </tr>
    </thead>
    <tbody>
      {#each invoices.results as inv (inv.invoice_id)}
        <tr>
          <td><a href={`#/invoices/${inv.invoice_id}`}>{inv.invoice_number}</a></td>
          <td>
            {#if inv.job}<a href={`#/jobs/${inv.job}`}>{inv.job_number}</a>{/if}
          </td>
          <td>{inv.customer_name || ''}</td>
          <td>{inv.status}</td>
          <td>{inv.sent_date ? inv.sent_date.slice(0, 10) : ''}</td>
          <td>{inv.due_date || ''}{#if inv.is_late} ⚠️{/if}</td>
          <td class="text-right">{money(inv.total)}</td>
          <td class="text-right">{money(inv.amount_paid)}</td>
          <td class="text-right">{money(inv.balance)}</td>
        </tr>
      {/each}
    </tbody>
  </table>

  {#if invoices.count > 25}
    <p>
      {pageRange(invoices)}
      {#if invoices.previous}
        | <button onclick={() => { page = pageFromUrl(invoices.previous); }}>Previous</button>
      {/if}
      {#if invoices.next}
        | <button onclick={() => { page = pageFromUrl(invoices.next); }}>Next</button>
      {/if}
    </p>
  {/if}
{/if}
```

- [ ] **Step 2: Verify it builds**

Run (from `frontend/`): `npm run build`
Expected: build succeeds (no Svelte compile errors). The route is wired in Phase 11.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/invoices/InvoiceListPage.svelte
git commit -m "Invoice list page (A/R) with status/sort/due/customer filters"
```

---

## Phase 8 — Frontend: Bill list page

### Task 8.1: `BillListPage.svelte`

**Files:**
- Create: `frontend/src/routes/bills/BillListPage.svelte`
- Test: `frontend/tests/components/bills/BillListPage.test.js`

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/components/bills/BillListPage.test.js`:

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, findByText } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => {} }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import BillListPage from '@/routes/bills/BillListPage.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('BillListPage', () => {
  it('renders bill rows from the API', async () => {
    user.set({ username: 'fin', permissions: ['can_manage_financials'] });
    api.get.mockResolvedValue({
      count: 1, next: null, previous: null,
      results: [{
        bill_id: 7, vendor_invoice_number: 'V-7', vendor_name: 'Acme',
        po_number: null, status: 'received', received_date: null,
        due_date: '2026-07-01T00:00:00Z', total: '50.00', balance: '50.00',
      }],
    });
    const { container } = render(BillListPage);
    expect(await findByText(container, 'V-7')).toBeInTheDocument();
    expect(await findByText(container, 'Acme')).toBeInTheDocument();
    expect(api.get.mock.calls[0][0]).toContain('status=open');
  });

  it('shows New Bill for financials users', async () => {
    user.set({ username: 'fin', permissions: ['can_manage_financials'] });
    api.get.mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    const { findByText: fbt } = render(BillListPage);
    expect(await fbt('New Bill')).toBeInTheDocument();
  });

  it('hides New Bill for non-financials users', async () => {
    user.set({ username: 'worker', permissions: [] });
    api.get.mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    const { queryByText } = render(BillListPage);
    // allow the initial load to settle
    await new Promise((r) => setTimeout(r, 0));
    expect(queryByText('New Bill')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run (from `frontend/`): `npm run test:run -- BillListPage`
Expected: FAIL — component does not exist.

- [ ] **Step 3: Create the page**

Create `frontend/src/routes/bills/BillListPage.svelte`:

```svelte
<script>
  import { api } from '../../lib/api.js';
  import { pageRange, pageFromUrl } from '../../lib/pagination.js';
  import CustomerPicker from '../../components/CustomerPicker.svelte';
  import { canManageFinancials as canManageFinancialsStore } from '../../stores/permissions.js';

  let bills = $state(null);
  let page = $state(1);
  let loading = $state(true);
  let error = $state(null);
  let statusFilter = $state('open');
  let ordering = $state('due_date');
  let dueFrom = $state('');
  let dueTo = $state('');
  let customer = $state(null);

  let canManageFinancials = $derived($canManageFinancialsStore);

  function customerParam() {
    if (!customer) return '';
    return customer.type === 'business'
      ? `&business=${customer.id}` : `&contact=${customer.id}`;
  }

  async function load() {
    loading = true;
    error = null;
    try {
      let url = `/api/bills/?page=${page}&status=${statusFilter}&ordering=${ordering}`;
      if (dueFrom) url += `&due_from=${dueFrom}`;
      if (dueTo) url += `&due_to=${dueTo}`;
      url += customerParam();
      bills = await api.get(url);
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function money(v) { return v == null ? '' : `$${v}`; }

  $effect(() => {
    void page; void statusFilter; void ordering; void dueFrom; void dueTo; void customer;
    load();
  });
</script>

<h2>Bills {bills ? `(${bills.count})` : ''}</h2>

<p>
  {#if canManageFinancials}
    <a href="#/bills/new">New Bill</a> |
  {/if}
  <label>Status:
    <select bind:value={statusFilter} onchange={() => { page = 1; }}>
      <option value="open">Open</option>
      <option value="paid">Paid</option>
      <option value="draft">Draft</option>
      <option value="cancelled">Cancelled</option>
      <option value="refunded">Refunded</option>
      <option value="all">All</option>
    </select>
  </label>
  &nbsp;
  <label>Sort:
    <select bind:value={ordering} onchange={() => { page = 1; }}>
      <option value="due_date">Due date ↑</option>
      <option value="-due_date">Due date ↓</option>
      <option value="-balance">Balance ↓</option>
      <option value="-total">Amount ↓</option>
      <option value="vendor_name">Vendor A–Z</option>
      <option value="-received_date">Received ↓</option>
    </select>
  </label>
  &nbsp;
  <label>Due from <input type="date" bind:value={dueFrom} onchange={() => { page = 1; }}></label>
  <label>to <input type="date" bind:value={dueTo} onchange={() => { page = 1; }}></label>
</p>
<p>
  <label>Vendor:
    <CustomerPicker bind:value={customer} onSelect={() => { page = 1; }} />
  </label>
</p>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else if bills}
  <table class="data-table">
    <thead>
      <tr>
        <th>Vendor Inv #</th><th>Vendor</th><th>PO #</th><th>Status</th>
        <th>Received</th><th>Due</th>
        <th class="text-right">Amount</th><th class="text-right">Balance</th>
      </tr>
    </thead>
    <tbody>
      {#each bills.results as bill (bill.bill_id)}
        <tr>
          <td><a href={`#/bills/${bill.bill_id}`}>{bill.vendor_invoice_number || '(no #)'}</a></td>
          <td>{bill.vendor_name || ''}</td>
          <td>
            {#if bill.po_number}<a href={`#/purchase-orders/${bill.purchase_order}`}>{bill.po_number}</a>{/if}
          </td>
          <td>{bill.status}</td>
          <td>{bill.received_date ? bill.received_date.slice(0, 10) : ''}</td>
          <td>{bill.due_date ? bill.due_date.slice(0, 10) : ''}</td>
          <td class="text-right">{money(bill.total)}</td>
          <td class="text-right">{money(bill.balance)}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  <p><small>Balance shows the full bill total for any bill that isn't fully paid — partial payments are not yet tracked.</small></p>

  {#if bills.count > 25}
    <p>
      {pageRange(bills)}
      {#if bills.previous}
        | <button onclick={() => { page = pageFromUrl(bills.previous); }}>Previous</button>
      {/if}
      {#if bills.next}
        | <button onclick={() => { page = pageFromUrl(bills.next); }}>Next</button>
      {/if}
    </p>
  {/if}
{/if}
```

> Note: the list serializer (`BillSummarySerializer`) exposes `po_number` but not `purchase_order` (the FK id). The PO link uses `bill.purchase_order`; add `purchase_order` to `BillSummarySerializer.Meta.fields` if a clickable PO link from the list is wanted. If you prefer to keep the list serializer lean, show `po_number` as plain text (no link) on the list and rely on the detail page for the PO link. **Decision for this plan:** add `'purchase_order'` to `BillSummarySerializer.Meta.fields` so the list link works; update Task 2.1's serializer field list accordingly.

- [ ] **Step 4: Run tests to verify they pass**

Run (from `frontend/`): `npm run test:run -- BillListPage`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/bills/BillListPage.svelte frontend/tests/components/bills/BillListPage.test.js apps/api/purchasing/serializers.py
git commit -m "Bill list page (A/P) with status/sort/due/vendor filters and New Bill"
```

---

## Phase 9 — Frontend: Bill detail page

### Task 9.1: `BillDetailPage.svelte`

**Files:**
- Create: `frontend/src/routes/bills/BillDetailPage.svelte`

This page reuses the shared `LineItemModal.svelte`. Before writing, confirm its props by reading the top of `frontend/src/components/LineItemModal.svelte` and how `InvoiceDetailPage.svelte` invokes it (which endpoints it POSTs/PATCHes). Mirror that usage exactly, swapping `/api/invoices/{id}/line-items/` for `/api/bills/{id}/line-items/`.

- [ ] **Step 1: Read the reuse references**

Run (from repo root):
```
sed -n '1,40p' frontend/src/components/LineItemModal.svelte
grep -n "LineItemModal\|line-items\|line_items\|status\|push" frontend/src/routes/invoices/InvoiceDetailPage.svelte | head -40
```
Note `LineItemModal`'s prop names (e.g. how it receives the parent id / endpoint and its `onSaved`/`onClose` callbacks) and how the invoice detail page refreshes after a save.

- [ ] **Step 2: Create the page**

Create `frontend/src/routes/bills/BillDetailPage.svelte`. Adapt the `LineItemModal` props in Step 2's code to match what Step 1 revealed (the skeleton below assumes a modal opened with a `billId` + `lineItem` and an `onSaved` callback — rename to match the real component):

```svelte
<script>
  import { onMount } from 'svelte';
  import { push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { canManageFinancials as canManageFinancialsStore } from '../../stores/permissions.js';
  import LineItemModal from '../../components/LineItemModal.svelte';

  let { params = {} } = $props();
  let billId = $derived(params.id);

  let bill = $state(null);
  let loading = $state(true);
  let error = $state(null);
  let modalOpen = $state(false);
  let editingLine = $state(null);
  let cancelReason = $state('');

  let canManageFinancials = $derived($canManageFinancialsStore);
  let isDraft = $derived(bill?.status === 'draft');

  async function load() {
    loading = true; error = null;
    try {
      bill = await api.get(`/api/bills/${billId}/`);
    } catch (e) { error = e.message; }
    finally { loading = false; }
  }

  onMount(load);

  function lineTotal(li) {
    return (Number(li.qty) * Number(li.price)).toFixed(2);
  }

  function addLine() { editingLine = null; modalOpen = true; }
  function editLine(li) { editingLine = li; modalOpen = true; }

  async function deleteLine(li) {
    if (!confirm('Delete this line item?')) return;
    await api.delete(`/api/bills/${billId}/line-items/${li.line_item_id}/`);
    await load();
  }

  async function onSaved() { modalOpen = false; await load(); }

  async function doAction(action, body = undefined) {
    try {
      await api.post(`/api/bills/${billId}/${action}/`, body);
      cancelReason = '';
      await load();
    } catch (e) {
      alert(e.message);
    }
  }

  async function deleteBill() {
    if (!confirm('Delete this draft bill? This cannot be undone.')) return;
    await api.delete(`/api/bills/${billId}/`);
    push('/bills');
  }
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else if bill}
  <h2>Bill {bill.vendor_invoice_number || `#${bill.bill_id}`}</h2>

  <table>
    <tbody>
      <tr><td><strong>Vendor</strong></td><td>{bill.vendor_name || ''}</td></tr>
      <tr><td><strong>Vendor Invoice #</strong></td><td>{bill.vendor_invoice_number || ''}</td></tr>
      <tr><td><strong>PO</strong></td><td>
        {#if bill.po_number}<a href={`#/purchase-orders/${bill.purchase_order}`}>{bill.po_number}</a>{:else}—{/if}
      </td></tr>
      <tr><td><strong>Status</strong></td><td>{bill.status}</td></tr>
      <tr><td><strong>Due</strong></td><td>{bill.due_date ? bill.due_date.slice(0, 10) : ''}</td></tr>
      <tr><td><strong>Received</strong></td><td>{bill.received_date ? bill.received_date.slice(0, 10) : ''}</td></tr>
      <tr><td><strong>Paid</strong></td><td>{bill.paid_date ? bill.paid_date.slice(0, 10) : ''}</td></tr>
      <tr><td><strong>Balance</strong></td><td>${bill.balance}</td></tr>
    </tbody>
  </table>

  {#if canManageFinancials && isDraft}
    <p><a href={`#/bills/${bill.bill_id}/edit`}>Edit header</a></p>
  {/if}

  <h3>Line Items</h3>
  <table class="data-table">
    <thead>
      <tr>
        <th>#</th><th>Description</th>
        <th class="text-right">Qty</th><th>Units</th>
        <th class="text-right">Price</th><th class="text-right">Total</th>
        {#if canManageFinancials && isDraft}<th></th>{/if}
      </tr>
    </thead>
    <tbody>
      {#each bill.line_items as li (li.line_item_id)}
        <tr>
          <td>{li.line_number}</td>
          <td>{li.description}</td>
          <td class="text-right">{li.qty}</td>
          <td>{li.units}</td>
          <td class="text-right">{li.price}</td>
          <td class="text-right">{lineTotal(li)}</td>
          {#if canManageFinancials && isDraft}
            <td>
              <button onclick={() => editLine(li)}>Edit</button>
              <button onclick={() => deleteLine(li)}>Delete</button>
            </td>
          {/if}
        </tr>
      {/each}
    </tbody>
  </table>

  {#if canManageFinancials && isDraft}
    <p><button onclick={addLine}>Add Line Item</button></p>
  {/if}

  {#if canManageFinancials}
    <h3>Actions</h3>
    {#if bill.status === 'draft'}
      <p>
        <button onclick={() => doAction('receive')}
                disabled={!bill.line_items.length}>Mark Received</button>
        {#if !bill.line_items.length}<small>Add a line item first.</small>{/if}
        <button onclick={deleteBill}>Delete</button>
      </p>
    {:else if bill.status === 'received'}
      <p>
        <button onclick={() => doAction('mark_paid')}>Mark Paid in Full</button>
      </p>
      <p>
        <input type="text" bind:value={cancelReason} placeholder="Reason for cancel">
        <button onclick={() => doAction('cancel', { reason: cancelReason })}
                disabled={!cancelReason.trim()}>Cancel Bill</button>
      </p>
    {/if}
  {/if}

  {#if modalOpen}
    <LineItemModal
      parentEndpoint={`/api/bills/${billId}/line-items/`}
      lineItem={editingLine}
      onSaved={onSaved}
      onClose={() => { modalOpen = false; }}
    />
  {/if}
{/if}
```

> **IMPORTANT:** `LineItemModal`'s real prop names almost certainly differ from the placeholder `parentEndpoint`/`onSaved`/`onClose` above. Use the exact names found in Step 1. The invoice detail page is the canonical caller — copy its `<LineItemModal ... />` invocation and change only the endpoint/parent id. Keep the rest of this page as written.

- [ ] **Step 3: Verify it builds**

Run (from `frontend/`): `npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/bills/BillDetailPage.svelte
git commit -m "Bill detail page: header, line-item CRUD (draft), status actions"
```

---

## Phase 10 — Frontend: Bill form page (new + edit)

### Task 10.1: `BillFormPage.svelte`

**Files:**
- Create: `frontend/src/routes/bills/BillFormPage.svelte`

This mirrors `PurchaseOrderFormPage` for vendor/contact selection. Read it first to copy the business+contact picking pattern.

- [ ] **Step 1: Read the PO form for the vendor/contact pattern**

Run (from repo root):
```
sed -n '1,120p' frontend/src/routes/purchaseorders/PurchaseOrderFormPage.svelte
sed -n '1,120p' frontend/src/components/purchaseorders/PurchaseOrderForm.svelte
```
Note how the vendor (business) and contact are chosen (likely a fetched `<select>` of businesses, then contacts filtered by business), and how new vs. edit mode is detected from `params`.

- [ ] **Step 2: Create the page**

Create `frontend/src/routes/bills/BillFormPage.svelte`. Use the business/contact selection mechanism observed in Step 1 (the skeleton uses simple `<select>`s populated from `/api/businesses/` and `/api/contacts/?business=` — replace with the exact PO pattern if it differs):

```svelte
<script>
  import { onMount } from 'svelte';
  import { push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';

  let { params = {} } = $props();
  let billId = $derived(params.id || null);
  let isEdit = $derived(!!billId);

  let businesses = $state([]);
  let contacts = $state([]);
  let businessId = $state('');
  let contactId = $state('');
  let vendorInvoiceNumber = $state('');
  let dueDate = $state('');
  let status = $state('draft');
  let loading = $state(true);
  let error = $state(null);
  let saving = $state(false);

  // Optional pre-link a PO when creating: #/bills/new?po=ID
  function poFromQuery() {
    const m = window.location.hash.match(/[?&]po=(\d+)/);
    return m ? m[1] : null;
  }

  async function loadBusinesses() {
    const data = await api.get('/api/businesses/?page_size=9999');
    businesses = data.results || data;
  }

  async function loadContacts(bizId) {
    if (!bizId) { contacts = []; return; }
    const data = await api.get(`/api/contacts/?business=${bizId}&page_size=9999`);
    contacts = data.results || data;
  }

  async function loadBill() {
    const bill = await api.get(`/api/bills/${billId}/`);
    status = bill.status;
    businessId = bill.business || '';
    contactId = bill.contact || '';
    vendorInvoiceNumber = bill.vendor_invoice_number || '';
    dueDate = bill.due_date ? bill.due_date.slice(0, 10) : '';
    await loadContacts(businessId);
  }

  onMount(async () => {
    try {
      await loadBusinesses();
      if (isEdit) await loadBill();
    } catch (e) { error = e.message; }
    finally { loading = false; }
  });

  async function save() {
    saving = true; error = null;
    try {
      const body = {
        business: businessId || null,
        contact: contactId || null,
        vendor_invoice_number: vendorInvoiceNumber,
        due_date: dueDate || null,
      };
      if (isEdit) {
        await api.patch(`/api/bills/${billId}/`, body);
        push(`/bills/${billId}`);
      } else {
        const po = poFromQuery();
        if (po) body.purchase_order = Number(po);
        const created = await api.post('/api/bills/', body);
        push(`/bills/${created.bill_id}`);
      }
    } catch (e) {
      error = e.message;
    } finally {
      saving = false;
    }
  }
</script>

<h2>{isEdit ? 'Edit Bill' : 'New Bill'}</h2>

{#if loading}
  <p>Loading...</p>
{:else if isEdit && status !== 'draft'}
  <p>This bill is <strong>{status}</strong> and can no longer be edited.</p>
  <p><a href={`#/bills/${billId}`}>Back to bill</a></p>
{:else}
  {#if error}<p>Error: {error}</p>{/if}
  <form onsubmit={(e) => { e.preventDefault(); save(); }}>
    <p>
      <label><strong>Vendor *</strong></label><br>
      <select bind:value={businessId} onchange={() => { contactId = ''; loadContacts(businessId); }} required>
        <option value="">-- Select vendor --</option>
        {#each businesses as b (b.business_id)}
          <option value={b.business_id}>{b.business_name}</option>
        {/each}
      </select>
    </p>
    <p>
      <label><strong>Contact</strong></label><br>
      <select bind:value={contactId}>
        <option value="">-- None --</option>
        {#each contacts as c (c.contact_id)}
          <option value={c.contact_id}>{c.name}</option>
        {/each}
      </select>
    </p>
    <p>
      <label><strong>Vendor Invoice #</strong></label><br>
      <input type="text" bind:value={vendorInvoiceNumber}>
    </p>
    <p>
      <label><strong>Due Date</strong></label><br>
      <input type="date" bind:value={dueDate}>
    </p>
    <p>
      <button type="submit" disabled={saving}>Save</button>
      <a href={isEdit ? `#/bills/${billId}` : '#/bills'}>Cancel</a>
    </p>
  </form>
{/if}
```

- [ ] **Step 3: Verify it builds**

Run (from `frontend/`): `npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/bills/BillFormPage.svelte
git commit -m "Bill form page: create + draft-only edit"
```

---

## Phase 11 — Frontend: Register routes

### Task 11.1: Add routes to `App.svelte`

**Files:**
- Modify: `frontend/src/App.svelte`

- [ ] **Step 1: Add imports**

In `frontend/src/App.svelte`, near the other route-component imports, add:

```javascript
import InvoiceListPage from './routes/invoices/InvoiceListPage.svelte';
import BillListPage from './routes/bills/BillListPage.svelte';
import BillFormPage from './routes/bills/BillFormPage.svelte';
import BillDetailPage from './routes/bills/BillDetailPage.svelte';
```

- [ ] **Step 2: Add route entries**

In the `routes` object, add (place `/bills/new` and `/bills/:id/edit` so they're matched correctly by svelte-spa-router — exact paths before the `:id` param route is fine, but `/bills/new` must be listed before `/bills/:id`):

```javascript
  '/invoices': InvoiceListPage,
  '/bills': BillListPage,
  '/bills/new': BillFormPage,
  '/bills/:id/edit': BillFormPage,
  '/bills/:id': BillDetailPage,
```

> svelte-spa-router matches the first key whose pattern matches; list `/bills/new` and `/bills/:id/edit` before `/bills/:id`. Keep the existing `/invoices/:id` (InvoiceDetailPage) and related invoice routes as they are.

- [ ] **Step 3: Verify build + run the full frontend suite**

Run (from `frontend/`):
```
npm run build
npm run test:run
```
Expected: build succeeds; all tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.svelte
git commit -m "Register /invoices and /bills routes"
```

---

## Phase 12 — Full regression + docs

### Task 12.1: Full test sweep

- [ ] **Step 1: Backend**

Run (from repo root, single process): `python manage.py test -v 1`
Expected: PASS (or no new failures vs. a pre-change baseline; investigate any failure touching invoicing/purchasing).

- [ ] **Step 2: Frontend**

Run (from `frontend/`): `npm run test:run`
Expected: PASS.

### Task 12.2: Update durable docs

**Files:**
- Modify: `docs/designs/invoicing-and-expenses.md`, `docs/designs/materials-inventory-and-purchasing.md`, `docs/designs/architecture-and-conventions.md`

- [ ] **Step 1: invoicing-and-expenses.md** — In "UI: Invoice list, detail, wizard" and "Unfinished work", replace the "no standalone invoice list / `#/invoices/` route" statements with the shipped `/invoices` list (columns, default Open filter, due-date sort, status/customer/due-range filters; read is `IsAuthenticated`, surfaced under the financials sidebar gate).

- [ ] **Step 2: materials-inventory-and-purchasing.md** — In §13/§15, document the Bill list (`/bills`), interactive Bill detail (`/bills/:id`), and Bill form (`/bills/new`, `/bills/:id/edit`); the new `BillService.update_bill`; the expanded `status_actions` (`receive`, `mark_paid`, `cancel`); and the coarse balance. (The `qbo_amount_paid`-needed note is already present.)

- [ ] **Step 3: architecture-and-conventions.md §8** — Update the sidebar link list: add the `─── Financials ───` section (Invoices, Bills, Expenses) above Admin; Admin is now Users + Settings.

- [ ] **Step 4: Commit**

```bash
git add docs/designs/invoicing-and-expenses.md docs/designs/materials-inventory-and-purchasing.md docs/designs/architecture-and-conventions.md
git commit -m "Docs: Financials list views, Bill editing, sidebar Financials section"
```

---

## Manual verification (after implementation, by the user)

The agent must not write to the dev DB. Hand these to the user to click through in the running app (`python manage.py runserver` + `cd frontend && npm run dev`):

1. As a `can_manage_financials` user, the sidebar shows a **Financials** section (Invoices, Bills, Expenses) above Admin; a non-financials user sees neither Financials nor those links.
2. `/invoices` defaults to Open, sorted most-overdue first; status/sort/due-range/customer filters all re-query.
3. `/bills` same; **New Bill** creates a draft → redirects to detail.
4. On a draft bill: edit header, add/edit/delete/reorder line items, **Mark Received** (blocked until a line exists), then **Mark Paid in Full**; **Cancel** requires a reason.
5. Balance column on bills reads as full total until paid-in-full (footnote present).

---

## Self-review notes (already reconciled)

- **Spec coverage:** nav (Phase 6), invoice list (1), bill list (2), bill detail (3/9), bill editing (4/9/10), CustomerPicker (5), routes (11), docs (12). All spec sections map to a task.
- **Type consistency:** annotation names (`total_anno`, `amount_paid_anno`, `due_date_anno`, `balance_anno`, `customer_sort`) are defined in the viewset `get_queryset` and read by the matching summary serializer's `get_*` methods. Status action names (`receive`, `mark_paid`, `cancel`) match the frontend `doAction` calls and the detail-page buttons. `CustomerPicker` emits `{ type, id }`, consumed identically by both list pages' `customerParam()`.
- **Known follow-ups (not blockers):** `LineItemModal` and `PurchaseOrderForm` prop shapes must be confirmed by reading those files during Tasks 9/10 (steps call this out explicitly); the placeholder prop names are flagged. `BillSummarySerializer` gains `'purchase_order'` for the list PO link (noted in Task 8 Step 3, applied in Task 2/8 commits).
```

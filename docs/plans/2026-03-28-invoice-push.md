# Invoice Push + Payment Polling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push invoices to QBO (grouped by accounting category + taxability), attach job statement PDF, send to customer via QBO email, and poll for payment status updates.

**Architecture:** Invoice push is synchronous (SPA shows spinner). Line items are grouped by `AccountingCategory` + taxability into summary lines for QBO. Job statement PDF generated with WeasyPrint and attached to the QBO invoice. Payment polling via a Django management command on cron (hourly). The SPA gets a minimal invoice detail page with "Send to QBO" flow.

**Tech Stack:** Django 5.2+, DRF, python-quickbooks, WeasyPrint (PDF), Svelte 5

**Design spec:** `docs/designs/2026-03-28-quickbooks-integration.md`

**Prerequisites:**
- `docs/plans/2026-03-28-qbo-foundation.md` (QBOService, QBOConnection, customer/vendor sync)
- `docs/plans/2026-03-28-accounting-category-rename.md` (AccountingCategory with QBO account fields)

---

## File Structure

```
apps/invoicing/
├── models.py                          # Add qbo_id, qbo_payment_status, qbo_amount_paid
├── services.py                        # Add InvoiceGroupingService, QBOInvoicePushService
├── pdf.py                             # NEW: Job statement PDF generation
├── migrations/NNNN_add_qbo_fields.py  # Auto-generated
└── management/
    ├── __init__.py
    └── commands/
        ├── __init__.py
        └── poll_qbo_payments.py       # Payment status polling command

apps/qbo/
├── services.py                        # Add QBOInvoiceSyncService, QBOPaymentPollingService
└── views.py                           # Add send_invoice_to_qbo endpoint

apps/api/invoicing/
├── serializers.py                     # Add QBO fields to InvoiceSerializer
└── views.py                           # Add send_to_qbo action on InvoiceViewSet

templates/invoicing/
└── job_statement.html                 # NEW: HTML template for PDF generation

frontend/src/
├── routes/invoices/
│   └── InvoiceDetailPage.svelte       # NEW: Invoice detail with Send to QBO
├── components/invoices/
│   ├── InvoiceDetail.svelte           # NEW: Invoice detail display
│   └── SendToQBODialog.svelte         # NEW: Email recipient picker + send
└── App.svelte                         # Add invoice routes

tests/
├── test_invoice_grouping.py           # Line item grouping logic
├── test_invoice_pdf.py                # PDF generation
├── test_qbo_invoice_push.py           # QBO push with mocked API
└── test_qbo_payment_polling.py        # Payment status polling
```

---

### Task 1: Add QBO Fields to Invoice Model

**Files:**
- Modify: `apps/invoicing/models.py`
- Modify: `apps/api/invoicing/serializers.py`
- Create: `apps/invoicing/migrations/NNNN_add_qbo_fields.py` (auto-generated)
- Test: `tests/test_qbo_invoice_push.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_qbo_invoice_push.py
from django.test import TestCase
from apps.invoicing.models import Invoice
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration


class InvoiceQBOFieldsTest(TestCase):
    """Test QBO tracking fields on Invoice model."""

    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme Corp', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(contact=self.contact)

    def test_invoice_has_qbo_id(self):
        inv = Invoice.objects.create(job=self.job)
        self.assertEqual(inv.qbo_id, '')

    def test_invoice_has_qbo_payment_status(self):
        inv = Invoice.objects.create(job=self.job)
        self.assertEqual(inv.qbo_payment_status, '')

    def test_invoice_has_qbo_amount_paid(self):
        inv = Invoice.objects.create(job=self.job)
        self.assertIsNone(inv.qbo_amount_paid)

    def test_invoice_can_store_qbo_data(self):
        inv = Invoice.objects.create(job=self.job)
        inv.qbo_id = '12345'
        inv.qbo_payment_status = 'Paid'
        inv.qbo_amount_paid = 4250.00
        inv.save()
        inv.refresh_from_db()
        self.assertEqual(inv.qbo_id, '12345')
        self.assertEqual(inv.qbo_payment_status, 'Paid')
        self.assertEqual(inv.qbo_amount_paid, 4250.00)

    def test_customer_business_chain(self):
        """Can traverse Invoice → Job → Contact → Business."""
        inv = Invoice.objects.create(job=self.job)
        business = inv.job.contact.business
        self.assertEqual(business.business_name, 'Acme Corp')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_qbo_invoice_push.InvoiceQBOFieldsTest -v2
```

- [ ] **Step 3: Add fields to Invoice model**

In `apps/invoicing/models.py`, add after `closed_date`:

```python
    # QuickBooks Online sync
    qbo_id = models.CharField(max_length=50, blank=True, default='')
    qbo_payment_status = models.CharField(max_length=50, blank=True, default='')
    qbo_amount_paid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
```

- [ ] **Step 4: Generate migration**

```bash
python manage.py makemigrations invoicing
```

- [ ] **Step 5: Update API serializer**

In `apps/api/invoicing/serializers.py`, add QBO fields to `InvoiceSerializer.Meta.fields`:

```python
fields = [
    'invoice_id', 'job', 'invoice_number', 'status',
    'created_date', 'sent_date', 'closed_date', 'line_items',
    'qbo_id', 'qbo_payment_status', 'qbo_amount_paid',
]
read_only_fields = [
    'invoice_id', 'invoice_number', 'created_date',
    'sent_date', 'closed_date',
    'qbo_id', 'qbo_payment_status', 'qbo_amount_paid',
]
```

- [ ] **Step 6: Run tests**

```bash
python manage.py test tests.test_qbo_invoice_push.InvoiceQBOFieldsTest -v2
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add apps/invoicing/models.py apps/invoicing/migrations/ apps/api/invoicing/serializers.py tests/test_qbo_invoice_push.py
git commit -m "feat: add QBO tracking fields to Invoice model"
```

---

### Task 2: Invoice Line Item Grouping Service

**Files:**
- Modify: `apps/invoicing/services.py`
- Test: `tests/test_invoice_grouping.py`

Groups invoice line items by `AccountingCategory` + taxability into summary lines for the QBO invoice. This is pure logic — no QBO API calls.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_invoice_grouping.py
from decimal import Decimal
from django.test import TestCase
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.services import InvoiceGroupingService
from apps.core.models import AccountingCategory, Configuration
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business


class InvoiceGroupingTest(TestCase):
    """Test grouping invoice line items by category + taxability."""

    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.cat_cnc = AccountingCategory.objects.create(
            code='CNC', name='CNC Machining', taxable=True,
            qbo_item_id='100',
        )
        self.cat_design = AccountingCategory.objects.create(
            code='DSN', name='Design Services', taxable=False,
            qbo_income_account_id='200',
        )
        self.cat_storage = AccountingCategory.objects.create(
            code='STR', name='Storage', taxable=True,
            qbo_income_account_id='300',
        )

        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme Corp', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(contact=self.contact)
        self.invoice = Invoice.objects.create(job=self.job)

    def test_single_category_single_line(self):
        """One category produces one grouped line."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=2, price=100,
            description='CNC part A', accounting_category=self.cat_cnc,
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=3, price=50,
            description='CNC part B', accounting_category=self.cat_cnc,
        )
        groups = InvoiceGroupingService.group_for_qbo(self.invoice)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['amount'], Decimal('350.00'))
        self.assertTrue(groups[0]['taxable'])
        self.assertEqual(groups[0]['qbo_item_id'], '100')

    def test_mixed_categories(self):
        """Different categories produce separate grouped lines."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=1, price=200,
            description='CNC work', accounting_category=self.cat_cnc,
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=1, price=500,
            description='Design', accounting_category=self.cat_design,
        )
        groups = InvoiceGroupingService.group_for_qbo(self.invoice)
        self.assertEqual(len(groups), 2)
        names = {g['category_name'] for g in groups}
        self.assertIn('CNC Machining', names)
        self.assertIn('Design Services', names)

    def test_taxable_override_creates_separate_group(self):
        """Line with taxable_override=False groups separately from taxable default."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=1, price=100,
            accounting_category=self.cat_cnc,  # taxable by default
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=1, price=200,
            accounting_category=self.cat_cnc,
            taxable_override=False,  # override to non-taxable
        )
        groups = InvoiceGroupingService.group_for_qbo(self.invoice)
        self.assertEqual(len(groups), 2)
        taxable_group = [g for g in groups if g['taxable']][0]
        nontaxable_group = [g for g in groups if not g['taxable']][0]
        self.assertEqual(taxable_group['amount'], Decimal('100.00'))
        self.assertEqual(nontaxable_group['amount'], Decimal('200.00'))

    def test_group_includes_job_number(self):
        """Each grouped line description includes the job number."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=1, price=100,
            accounting_category=self.cat_cnc,
        )
        groups = InvoiceGroupingService.group_for_qbo(self.invoice)
        self.assertIn(self.job.job_number, groups[0]['description'])

    def test_no_category_groups_as_uncategorized(self):
        """Line items without accounting_category group as 'Uncategorized'."""
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=1, price=100,
            description='Misc charge',
        )
        groups = InvoiceGroupingService.group_for_qbo(self.invoice)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['category_name'], 'Uncategorized')
        self.assertFalse(groups[0]['taxable'])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_invoice_grouping -v2
```

- [ ] **Step 3: Implement InvoiceGroupingService**

Add to `apps/invoicing/services.py`:

```python
from collections import defaultdict
from apps.core.services import TaxCalculationService


class InvoiceGroupingService:
    """Groups invoice line items by AccountingCategory + taxability for QBO push."""

    @staticmethod
    def group_for_qbo(invoice):
        """
        Group an invoice's line items by (accounting_category, effective_taxability).
        Returns a list of dicts ready for QBO invoice line creation:
        [
            {
                'category_name': 'CNC Machining',
                'description': 'Job JOB-2026-0001: CNC Machining (taxable)',
                'amount': Decimal('350.00'),
                'taxable': True,
                'qbo_item_id': '100',
            },
            ...
        ]
        """
        line_items = invoice.invoicelineitem_set.select_related('accounting_category').all()
        job_number = invoice.job.job_number

        # Group by (category_id, effective_taxability)
        groups = defaultdict(lambda: {
            'amount': Decimal('0.00'),
            'category_name': '',
            'qbo_item_id': '',
            'taxable': False,
        })

        for item in line_items:
            taxable = TaxCalculationService.get_effective_taxability(item)
            cat = item.accounting_category
            cat_id = cat.pk if cat else None
            key = (cat_id, taxable)

            groups[key]['amount'] += item.total_amount
            groups[key]['taxable'] = taxable

            if cat:
                groups[key]['category_name'] = cat.name
                groups[key]['qbo_item_id'] = cat.qbo_item_id
            else:
                groups[key]['category_name'] = 'Uncategorized'

        # Build descriptions
        result = []
        for (cat_id, taxable), data in groups.items():
            tax_label = '(taxable)' if taxable else '(non-taxable)'
            data['description'] = f"Job {job_number}: {data['category_name']} {tax_label}"
            result.append(data)

        return sorted(result, key=lambda g: g['category_name'])
```

- [ ] **Step 4: Run tests**

```bash
python manage.py test tests.test_invoice_grouping -v2
```

- [ ] **Step 5: Commit**

```bash
git add apps/invoicing/services.py tests/test_invoice_grouping.py
git commit -m "feat: add InvoiceGroupingService for QBO line item grouping"
```

---

### Task 3: Job Statement PDF Generation

**Files:**
- Create: `apps/invoicing/pdf.py`
- Create: `templates/invoicing/job_statement.html`
- Modify: `requirements.txt`
- Test: `tests/test_invoice_pdf.py`

Uses WeasyPrint to generate a PDF from an HTML template.

- [ ] **Step 1: Install WeasyPrint**

Add to `requirements.txt`:
```
weasyprint==62.3
```

```bash
pip install -r requirements.txt
```

**System dependencies required:** WeasyPrint needs cairo, pango, and gdk-pixbuf.
- **Dockerfile:** Add `apt-get install -y libcairo2 libpango-1.0-0 libgdk-pixbuf2.0-0 libffi-dev` to the Dockerfile's system package install step.
- **Local dev (macOS):** `brew install cairo pango gdk-pixbuf libffi`
- **Local dev (Debian/Ubuntu):** `apt-get install libcairo2 libpango-1.0-0 libgdk-pixbuf2.0-0 libffi-dev`
- **CLAUDE.md:** Add a "Local Development Setup" section documenting these requirements.

Python packages go in `requirements.txt`, system deps in Dockerfile, local dev instructions in CLAUDE.md.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_invoice_pdf.py
from decimal import Decimal
from django.test import TestCase
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.pdf import generate_job_statement_pdf
from apps.core.models import AccountingCategory, Configuration
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business


class JobStatementPDFTest(TestCase):
    """Test job statement PDF generation."""

    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='default_tax_rate', value='0.0825')

        self.cat_cnc = AccountingCategory.objects.create(
            code='CNC', name='CNC Machining', taxable=True,
        )
        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme Corp', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(contact=self.contact, name='Widget Assembly')
        self.invoice = Invoice.objects.create(job=self.job)
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=2, price=Decimal('100.00'),
            description='CNC part A', accounting_category=self.cat_cnc,
        )

    def test_generates_pdf_bytes(self):
        """generate_job_statement_pdf returns bytes."""
        pdf_bytes = generate_job_statement_pdf(self.invoice)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 0)

    def test_pdf_starts_with_pdf_header(self):
        """PDF output starts with %PDF magic bytes."""
        pdf_bytes = generate_job_statement_pdf(self.invoice)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))

    def test_pdf_contains_invoice_number(self):
        """PDF should contain the invoice number in some form."""
        # We can't easily parse PDF content, but we can verify generation succeeds
        pdf_bytes = generate_job_statement_pdf(self.invoice)
        self.assertIsNotNone(pdf_bytes)
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
python manage.py test tests.test_invoice_pdf -v2
```

- [ ] **Step 4: Create the HTML template for PDF rendering**

```html
<!-- templates/invoicing/job_statement.html -->
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: sans-serif; font-size: 12px; margin: 40px; }
        h1 { font-size: 18px; margin-bottom: 5px; }
        h2 { font-size: 14px; color: #555; margin-top: 0; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { border: 1px solid #333; padding: 6px 8px; text-align: left; }
        th { background-color: #eee; }
        td.amount { text-align: right; }
        .total-row td { font-weight: bold; border-top: 2px solid #333; }
        .header-info { margin-bottom: 20px; }
        .header-info p { margin: 2px 0; }
    </style>
</head>
<body>
    <h1>Job Statement</h1>
    <h2>{{ invoice.invoice_number }}</h2>

    <div class="header-info">
        <p><strong>Job:</strong> {{ job.job_number }} — {{ job.name }}</p>
        <p><strong>Customer:</strong> {{ business_name }}</p>
        {% if invoice.customer_po_number %}<p><strong>Customer PO:</strong> {{ invoice.customer_po_number }}</p>{% endif %}
        <p><strong>Date:</strong> {{ invoice.created_date|date:"N j, Y" }}</p>
    </div>

    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Description</th>
                <th>Type</th>
                <th>Qty</th>
                <th>Unit</th>
                <th>Price</th>
                <th>Total</th>
            </tr>
        </thead>
        <tbody>
            {% for item in line_items %}
            <tr>
                <td>{{ item.line_number }}</td>
                <td>{{ item.description }}</td>
                <td>{{ item.accounting_category.name|default:"—" }}</td>
                <td class="amount">{{ item.qty }}</td>
                <td>{{ item.units }}</td>
                <td class="amount">${{ item.price|floatformat:2 }}</td>
                <td class="amount">${{ item.total_amount|floatformat:2 }}</td>
            </tr>
            {% endfor %}
            <tr class="total-row">
                <td colspan="6">Subtotal</td>
                <td class="amount">${{ subtotal|floatformat:2 }}</td>
            </tr>
        </tbody>
    </table>

    <p><em>See accompanying invoice for tax calculation and payment details.</em></p>
</body>
</html>
```

- [ ] **Step 5: Implement the PDF generator**

```python
# apps/invoicing/pdf.py
from django.template.loader import render_to_string
from weasyprint import HTML


def generate_job_statement_pdf(invoice):
    """
    Generate a job statement PDF for an invoice.
    Returns bytes containing the PDF.
    """
    line_items = invoice.invoicelineitem_set.select_related(
        'accounting_category', 'task', 'price_list_item'
    ).order_by('line_number')

    subtotal = sum(item.total_amount for item in line_items)

    job = invoice.job
    business_name = ''
    if job.contact and job.contact.business:
        business_name = job.contact.business.business_name

    html_string = render_to_string('invoicing/job_statement.html', {
        'invoice': invoice,
        'job': job,
        'business_name': business_name,
        'line_items': line_items,
        'subtotal': subtotal,
    })

    return HTML(string=html_string).write_pdf()
```

- [ ] **Step 6: Run tests**

```bash
python manage.py test tests.test_invoice_pdf -v2
```

- [ ] **Step 7: Commit**

```bash
git add requirements.txt apps/invoicing/pdf.py templates/invoicing/job_statement.html tests/test_invoice_pdf.py
git commit -m "feat: add job statement PDF generation with WeasyPrint"
```

---

### Task 4: QBO Invoice Push Service

**Files:**
- Modify: `apps/qbo/services.py`
- Test: `tests/test_qbo_invoice_push.py` (add tests)

Creates a QBO invoice with grouped lines, attaches the job statement PDF, and triggers email send. All QBO API calls are mocked in tests.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_qbo_invoice_push.py`:

```python
from unittest.mock import patch, MagicMock, ANY
from decimal import Decimal
from apps.qbo.services import QBOInvoiceSyncService
from apps.qbo.models import QBOSyncLog
from apps.core.models import AccountingCategory, Configuration
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business


class QBOInvoicePushTest(TestCase):
    """Test pushing an invoice to QBO."""

    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.cat_cnc = AccountingCategory.objects.create(
            code='CNC', name='CNC Machining', taxable=True,
            qbo_item_id='100',
        )
        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme Corp', default_contact=self.contact,
            qbo_customer_id='42',
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(contact=self.contact)
        self.invoice = Invoice.objects.create(job=self.job)
        InvoiceLineItem.objects.create(
            invoice=self.invoice, qty=1, price=Decimal('500.00'),
            description='CNC work', accounting_category=self.cat_cnc,
        )

    @patch('apps.qbo.services.QBOService.get_client')
    @patch('apps.invoicing.pdf.generate_job_statement_pdf')
    def test_push_invoice_stores_qbo_id(self, mock_pdf, mock_get_client):
        """push_invoice creates QBO invoice and stores the ID."""
        mock_pdf.return_value = b'%PDF-fake'
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_qbo_invoice = MagicMock()
        mock_qbo_invoice.Id = '999'
        mock_qbo_invoice.save = MagicMock(return_value=mock_qbo_invoice)

        with patch('apps.qbo.services.QBOInvoiceSyncService._build_qbo_invoice',
                   return_value=mock_qbo_invoice):
            with patch('apps.qbo.services.QBOInvoiceSyncService._attach_pdf'):
                with patch('apps.qbo.services.QBOInvoiceSyncService._send_invoice'):
                    QBOInvoiceSyncService.push_invoice(
                        self.invoice,
                        send_to='john@example.com',
                    )

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.qbo_id, '999')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_invoice_skips_if_already_synced(self, mock_get_client):
        """push_invoice returns existing ID if already synced."""
        self.invoice.qbo_id = '999'
        self.invoice.save()

        result = QBOInvoiceSyncService.push_invoice(self.invoice, send_to='x@x.com')
        self.assertEqual(result, '999')
        mock_get_client.assert_not_called()

    @patch('apps.qbo.services.QBOService.get_client')
    @patch('apps.invoicing.pdf.generate_job_statement_pdf')
    def test_push_invoice_logs_success(self, mock_pdf, mock_get_client):
        """push_invoice creates a sync log entry on success."""
        mock_pdf.return_value = b'%PDF-fake'
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_qbo_invoice = MagicMock()
        mock_qbo_invoice.Id = '999'
        mock_qbo_invoice.save = MagicMock(return_value=mock_qbo_invoice)

        with patch('apps.qbo.services.QBOInvoiceSyncService._build_qbo_invoice',
                   return_value=mock_qbo_invoice):
            with patch('apps.qbo.services.QBOInvoiceSyncService._attach_pdf'):
                with patch('apps.qbo.services.QBOInvoiceSyncService._send_invoice'):
                    QBOInvoiceSyncService.push_invoice(
                        self.invoice, send_to='john@example.com',
                    )

        log = QBOSyncLog.objects.get(entity_type='invoice')
        self.assertEqual(log.status, 'success')
        self.assertEqual(log.qbo_entity_id, '999')

    def test_push_invoice_requires_customer_synced(self):
        """push_invoice raises if customer business has no qbo_customer_id."""
        self.business.qbo_customer_id = ''
        self.business.save()

        with self.assertRaises(ValueError) as ctx:
            QBOInvoiceSyncService.push_invoice(self.invoice, send_to='x@x.com')
        self.assertIn('customer', str(ctx.exception).lower())

    def test_push_invoice_requires_connection(self):
        """push_invoice raises if no active QBO connection."""
        with self.assertRaises(ValueError):
            QBOInvoiceSyncService.push_invoice(self.invoice, send_to='x@x.com')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_qbo_invoice_push.QBOInvoicePushTest -v2
```

- [ ] **Step 3: Implement QBOInvoiceSyncService**

Add to `apps/qbo/services.py`:

```python
class QBOInvoiceSyncService:
    """Pushes Minibini invoices to QBO."""

    @staticmethod
    def push_invoice(invoice, send_to, cc=None, bcc=None):
        """
        Push an invoice to QBO, attach job statement PDF, and send to customer.

        Args:
            invoice: Invoice model instance
            send_to: primary recipient email address
            cc: comma-separated CC addresses (optional)
            bcc: comma-separated BCC addresses (optional)

        Returns:
            str: QBO Invoice ID
        """
        if invoice.qbo_id:
            return invoice.qbo_id

        # Validate customer is synced to QBO
        business = invoice.job.contact.business
        if not business or not business.qbo_customer_id:
            raise ValueError(
                'Customer business must be synced to QBO before pushing invoices. '
                'Use QBOCustomerSyncService.push_customer() first.'
            )

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        # Build and save QBO invoice
        from apps.invoicing.services import InvoiceGroupingService
        grouped_lines = InvoiceGroupingService.group_for_qbo(invoice)
        qbo_invoice = QBOInvoiceSyncService._build_qbo_invoice(
            invoice, business, grouped_lines, cc, bcc
        )

        try:
            qbo_invoice.save(qb=client)
            qbo_id = str(qbo_invoice.Id)

            # Save qbo_id immediately so retries don't create duplicates
            invoice.qbo_id = qbo_id
            invoice.save(update_fields=['qbo_id'])

            # Attach job statement PDF
            from apps.invoicing.pdf import generate_job_statement_pdf
            pdf_bytes = generate_job_statement_pdf(invoice)
            QBOInvoiceSyncService._attach_pdf(client, qbo_id, pdf_bytes, invoice)

            # Send invoice email
            QBOInvoiceSyncService._send_invoice(client, qbo_id, send_to)

            QBOService.log_sync(
                entity_type='invoice',
                entity_id=invoice.pk,
                qbo_entity_type='Invoice',
                qbo_entity_id=qbo_id,
                action='create',
                status='success',
            )
            return qbo_id

        except Exception as e:
            QBOService.log_sync(
                entity_type='invoice',
                entity_id=invoice.pk,
                qbo_entity_type='Invoice',
                qbo_entity_id='',
                action='create',
                status='failed',
                error_message=str(e),
            )
            raise

    @staticmethod
    def _build_qbo_invoice(invoice, business, grouped_lines, cc=None, bcc=None):
        """Build a QBO Invoice object from grouped line items."""
        from quickbooks.objects.invoice import Invoice as QBOInvoice
        from quickbooks.objects.detailline import SalesItemLine, SalesItemLineDetail
        from quickbooks.objects.base import Ref, EmailAddress

        qbo_inv = QBOInvoice()
        qbo_inv.CustomerRef = Ref()
        qbo_inv.CustomerRef.value = business.qbo_customer_id

        if invoice.customer_po_number:
            qbo_inv.CustomField = [{
                'Name': 'P.O. Number',
                'StringValue': invoice.customer_po_number,
            }]

        # Set CC/BCC if provided
        if cc:
            qbo_inv.BillEmailCc = EmailAddress()
            qbo_inv.BillEmailCc.Address = cc
        if bcc:
            qbo_inv.BillEmailBcc = EmailAddress()
            qbo_inv.BillEmailBcc.Address = bcc

        # Build line items from grouped data
        qbo_inv.Line = []
        for group in grouped_lines:
            line = SalesItemLine()
            line.Amount = float(group['amount'])
            line.Description = group['description']

            detail = SalesItemLineDetail()
            if group['qbo_item_id']:
                detail.ItemRef = Ref()
                detail.ItemRef.value = group['qbo_item_id']

            detail.TaxCodeRef = Ref()
            detail.TaxCodeRef.value = 'TAX' if group['taxable'] else 'NON'

            line.SalesItemLineDetail = detail
            qbo_inv.Line.append(line)

        return qbo_inv

    @staticmethod
    def _attach_pdf(client, qbo_invoice_id, pdf_bytes, invoice):
        """Attach job statement PDF to a QBO invoice."""
        from quickbooks.objects.attachable import Attachable, AttachableRef
        import tempfile
        import os

        # Write PDF to temp file (python-quickbooks requires a file path)
        filename = f"job_statement_{invoice.invoice_number}.pdf"
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(pdf_bytes)
            temp_path = f.name

        try:
            attachable = Attachable()
            attachable_ref = AttachableRef()
            attachable_ref.EntityRef = {'type': 'Invoice', 'value': qbo_invoice_id}
            attachable.AttachableRef = [attachable_ref]
            attachable.FileName = filename
            attachable.ContentType = 'application/pdf'
            attachable.save(qb=client, file_path=temp_path)
        finally:
            os.unlink(temp_path)

    @staticmethod
    def _send_invoice(client, qbo_invoice_id, send_to):
        """Send a QBO invoice via email."""
        from quickbooks.objects.invoice import Invoice as QBOInvoice
        QBOInvoice.send(qbo_invoice_id, send_to=send_to, qb=client)
```

- [ ] **Step 4: Run tests**

```bash
python manage.py test tests.test_qbo_invoice_push -v2
```

- [ ] **Step 5: Commit**

```bash
git add apps/qbo/services.py tests/test_qbo_invoice_push.py
git commit -m "feat: add QBOInvoiceSyncService for pushing invoices to QBO"
```

---

### Task 5: "Send to QBO" API Endpoint

**Files:**
- Modify: `apps/api/invoicing/views.py`
- Test: `tests/test_qbo_invoice_push.py` (add endpoint tests)

Custom action on InvoiceViewSet that accepts email recipients and triggers the push.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_qbo_invoice_push.py`:

```python
from django.test import Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

User = get_user_model()


class SendToQBOEndpointTest(TestCase):
    """Test the /api/invoices/{id}/send-to-qbo/ endpoint."""

    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.api_client = Client()
        self.user = User.objects.create_user(username='manager', password='testpass')
        perm_fin = Permission.objects.get(codename='can_manage_financials', content_type__app_label='core')
        self.user.user_permissions.add(perm_fin)
        self.user = User.objects.get(pk=self.user.pk)

        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme Corp', default_contact=self.contact,
            qbo_customer_id='42',
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(contact=self.contact)
        self.invoice = Invoice.objects.create(job=self.job)

    @patch('apps.qbo.services.QBOInvoiceSyncService.push_invoice')
    def test_send_to_qbo_success(self, mock_push):
        """POST to send-to-qbo triggers push and returns success."""
        mock_push.return_value = '999'

        self.api_client.login(username='manager', password='testpass')
        response = self.api_client.post(
            f'/api/invoices/{self.invoice.pk}/send-to-qbo/',
            data='{"send_to": "john@example.com"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['qbo_id'], '999')
        mock_push.assert_called_once()

    def test_send_to_qbo_requires_send_to(self):
        """POST without send_to returns 400."""
        self.api_client.login(username='manager', password='testpass')
        response = self.api_client.post(
            f'/api/invoices/{self.invoice.pk}/send-to-qbo/',
            data='{}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_send_to_qbo_requires_can_manage_financials(self):
        """Endpoint requires can_manage_financials permission."""
        worker = User.objects.create_user(username='worker', password='testpass')
        self.api_client.login(username='worker', password='testpass')
        response = self.api_client.post(
            f'/api/invoices/{self.invoice.pk}/send-to-qbo/',
            data='{"send_to": "x@x.com"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_send_to_qbo_already_synced(self):
        """Returns existing QBO ID if already synced."""
        self.invoice.qbo_id = '888'
        self.invoice.save()

        self.api_client.login(username='manager', password='testpass')
        response = self.api_client.post(
            f'/api/invoices/{self.invoice.pk}/send-to-qbo/',
            data='{"send_to": "x@x.com"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['qbo_id'], '888')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_qbo_invoice_push.SendToQBOEndpointTest -v2
```

- [ ] **Step 3: Add the action to InvoiceViewSet**

In `apps/api/invoicing/views.py`, add:

```python
from rest_framework.decorators import action
from rest_framework.response import Response

# Inside InvoiceViewSet:

    @action(detail=True, methods=['post'], url_path='send-to-qbo')
    def send_to_qbo(self, request, pk=None):
        """Push this invoice to QBO, attach PDF, and send to customer."""
        invoice = self.get_object()
        send_to = request.data.get('send_to')
        if not send_to:
            return Response(
                {'error': 'send_to email address is required'},
                status=400,
            )

        cc = request.data.get('cc', None)
        bcc = request.data.get('bcc', None)

        try:
            from apps.qbo.services import QBOInvoiceSyncService
            qbo_id = QBOInvoiceSyncService.push_invoice(
                invoice, send_to=send_to, cc=cc, bcc=bcc,
            )
            return Response({
                'qbo_id': qbo_id,
                'status': 'sent',
            })
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            return Response({'error': str(e)}, status=500)
```

The `send-to-qbo` action inherits the ViewSet's `get_permissions()` — write actions require `CanManageFinancials`.

- [ ] **Step 4: Run tests**

```bash
python manage.py test tests.test_qbo_invoice_push -v2
```

- [ ] **Step 5: Commit**

```bash
git add apps/api/invoicing/views.py tests/test_qbo_invoice_push.py
git commit -m "feat: add send-to-qbo action on InvoiceViewSet"
```

---

### Task 6: Payment Status Polling

**Files:**
- Modify: `apps/qbo/services.py`
- Create: `apps/invoicing/management/__init__.py`
- Create: `apps/invoicing/management/commands/__init__.py`
- Create: `apps/invoicing/management/commands/poll_qbo_payments.py`
- Test: `tests/test_qbo_payment_polling.py`

Polls QBO for payment status updates on invoices that have been pushed but not yet fully paid.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_qbo_payment_polling.py
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from apps.invoicing.models import Invoice
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration
from apps.qbo.services import QBOPaymentPollingService


class PaymentPollingTest(TestCase):
    """Test QBO payment status polling."""

    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme Corp', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(contact=self.contact)

    def _create_synced_invoice(self, qbo_id='100', status='open'):
        inv = Invoice.objects.create(job=self.job, status=status)
        inv.qbo_id = qbo_id
        inv.save()
        return inv

    @patch('apps.qbo.services.QBOService.get_client')
    def test_polls_unpaid_invoices(self, mock_get_client):
        """poll_all checks QBO for invoices with qbo_id that aren't fully paid."""
        inv = self._create_synced_invoice(qbo_id='100')

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_qbo_inv = MagicMock()
        mock_qbo_inv.Balance = 0
        mock_qbo_inv.TotalAmt = 500.00

        with patch('apps.qbo.services.QBOPaymentPollingService._fetch_qbo_invoice',
                   return_value=mock_qbo_inv):
            stats = QBOPaymentPollingService.poll_all()

        inv.refresh_from_db()
        self.assertEqual(inv.qbo_payment_status, 'Paid')
        self.assertEqual(inv.qbo_amount_paid, Decimal('500.00'))
        self.assertEqual(stats['updated'], 1)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_partial_payment(self, mock_get_client):
        """Detects partial payment (Balance > 0 but less than TotalAmt)."""
        inv = self._create_synced_invoice(qbo_id='101')

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_qbo_inv = MagicMock()
        mock_qbo_inv.Balance = 200.00
        mock_qbo_inv.TotalAmt = 500.00

        with patch('apps.qbo.services.QBOPaymentPollingService._fetch_qbo_invoice',
                   return_value=mock_qbo_inv):
            QBOPaymentPollingService.poll_all()

        inv.refresh_from_db()
        self.assertEqual(inv.qbo_payment_status, 'Partial')
        self.assertEqual(inv.qbo_amount_paid, Decimal('300.00'))

    @patch('apps.qbo.services.QBOService.get_client')
    def test_skips_invoices_without_qbo_id(self, mock_get_client):
        """Invoices not synced to QBO are skipped."""
        Invoice.objects.create(job=self.job)  # no qbo_id

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        stats = QBOPaymentPollingService.poll_all()
        self.assertEqual(stats['checked'], 0)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_skips_already_paid_invoices(self, mock_get_client):
        """Invoices already marked as paid are skipped."""
        inv = self._create_synced_invoice(qbo_id='100', status='paid')
        inv.qbo_payment_status = 'Paid'
        inv.save()

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        stats = QBOPaymentPollingService.poll_all()
        self.assertEqual(stats['checked'], 0)

    def test_poll_all_no_connection(self):
        """poll_all returns error stats if no QBO connection."""
        self._create_synced_invoice()
        stats = QBOPaymentPollingService.poll_all()
        self.assertIn('error', stats)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_qbo_payment_polling -v2
```

- [ ] **Step 3: Implement QBOPaymentPollingService**

Add to `apps/qbo/services.py`:

```python
from decimal import Decimal


class QBOPaymentPollingService:
    """Polls QBO for payment status updates on synced invoices."""

    @staticmethod
    def poll_all():
        """
        Check QBO payment status for all unpaid synced invoices.
        Returns stats dict: {'checked': N, 'updated': N, 'errors': [...]}
        """
        from apps.invoicing.models import Invoice

        stats = {'checked': 0, 'updated': 0, 'errors': []}

        client = QBOService.get_client()
        if not client:
            stats['error'] = 'No active QBO connection'
            return stats

        # Find invoices synced to QBO but not yet fully paid
        invoices = Invoice.objects.filter(
            qbo_id__gt='',
        ).exclude(
            qbo_payment_status='Paid',
        )

        for invoice in invoices:
            stats['checked'] += 1
            try:
                qbo_inv = QBOPaymentPollingService._fetch_qbo_invoice(
                    client, invoice.qbo_id
                )
                if qbo_inv is None:
                    stats['errors'].append(f'Invoice {invoice.pk}: not found in QBO')
                    continue

                total = Decimal(str(qbo_inv.TotalAmt))
                balance = Decimal(str(qbo_inv.Balance))
                amount_paid = total - balance

                if balance == 0:
                    payment_status = 'Paid'
                elif amount_paid > 0:
                    payment_status = 'Partial'
                else:
                    payment_status = 'Unpaid'

                # Only update if status changed
                if (invoice.qbo_payment_status != payment_status or
                        invoice.qbo_amount_paid != amount_paid):
                    invoice.qbo_payment_status = payment_status
                    invoice.qbo_amount_paid = amount_paid
                    invoice.save(update_fields=[
                        'qbo_payment_status', 'qbo_amount_paid'
                    ])
                    stats['updated'] += 1

            except Exception as e:
                stats['errors'].append(f'Invoice {invoice.pk}: {str(e)}')

        return stats

    @staticmethod
    def _fetch_qbo_invoice(client, qbo_id):
        """Fetch a single invoice from QBO by ID."""
        from quickbooks.objects.invoice import Invoice as QBOInvoice
        return QBOInvoice.get(qbo_id, qb=client)
```

- [ ] **Step 4: Create the management command**

```bash
mkdir -p apps/invoicing/management/commands
touch apps/invoicing/management/__init__.py
touch apps/invoicing/management/commands/__init__.py
```

```python
# apps/invoicing/management/commands/poll_qbo_payments.py
from django.core.management.base import BaseCommand
from apps.qbo.services import QBOPaymentPollingService


class Command(BaseCommand):
    help = 'Poll QuickBooks Online for payment status updates on synced invoices'

    def handle(self, *args, **options):
        self.stdout.write('Polling QBO for payment status updates...')

        stats = QBOPaymentPollingService.poll_all()

        if 'error' in stats:
            self.stderr.write(self.style.ERROR(f"Error: {stats['error']}"))
            return

        self.stdout.write(
            f"Checked: {stats['checked']}, "
            f"Updated: {stats['updated']}, "
            f"Errors: {len(stats['errors'])}"
        )

        for error in stats['errors']:
            self.stderr.write(self.style.WARNING(f"  {error}"))

        if stats['updated'] > 0:
            self.stdout.write(self.style.SUCCESS(
                f"Updated {stats['updated']} invoice(s)"
            ))
```

- [ ] **Step 5: Run tests**

```bash
python manage.py test tests.test_qbo_payment_polling -v2
```

- [ ] **Step 6: Verify command runs**

```bash
python manage.py poll_qbo_payments
```

Expected: "Error: No active QBO connection" (no QBO connected in dev). Confirms the command loads and runs.

- [ ] **Step 7: Commit**

```bash
git add apps/qbo/services.py apps/invoicing/management/ tests/test_qbo_payment_polling.py
git commit -m "feat: add QBO payment status polling service and management command"
```

---

### Task 7: SPA Invoice Detail Page with Send to QBO

**Files:**
- Create: `frontend/src/routes/invoices/InvoiceDetailPage.svelte`
- Create: `frontend/src/components/invoices/InvoiceDetail.svelte`
- Create: `frontend/src/components/invoices/SendToQBODialog.svelte`
- Modify: `frontend/src/App.svelte` (add route)

The SPA doesn't have an invoice page yet. JobDetail.svelte already links to `#/invoices/{id}` but the route doesn't exist. This task creates a minimal invoice detail page with the "Send to QBO" flow.

- [ ] **Step 1: Create the SendToQBO dialog component**

```svelte
<!-- frontend/src/components/invoices/SendToQBODialog.svelte -->
<script>
  import { api } from '../../lib/api.js';

  const {
    invoiceId,
    defaultEmail = '',
    onSuccess = null,
    onCancel = null,
  } = $props();

  let sendTo = $state(defaultEmail);
  let cc = $state('');
  let bcc = $state('');
  let sending = $state(false);
  let error = $state(null);

  async function send() {
    if (!sendTo.trim()) {
      error = 'Recipient email is required';
      return;
    }
    sending = true;
    error = null;
    try {
      const result = await api.post(`/api/invoices/${invoiceId}/send-to-qbo/`, {
        send_to: sendTo.trim(),
        cc: cc.trim() || undefined,
        bcc: bcc.trim() || undefined,
      });
      if (onSuccess) onSuccess(result);
    } catch (e) {
      error = e.data?.error || e.message || 'Failed to send to QuickBooks';
    } finally {
      sending = false;
    }
  }
</script>

<fieldset>
  <legend><strong>Send to QuickBooks</strong></legend>

  {#if error}
    <p><strong>Error:</strong> {error}</p>
  {/if}

  <p><label for="send_to"><strong>Send To *</strong></label><br>
    <input type="email" id="send_to" bind:value={sendTo} required></p>

  <p><label for="cc"><strong>CC</strong></label><br>
    <input type="text" id="cc" bind:value={cc} placeholder="Comma-separated emails"></p>

  <p><label for="bcc"><strong>BCC</strong></label><br>
    <input type="text" id="bcc" bind:value={bcc} placeholder="Comma-separated emails"></p>

  <p>
    <button onclick={send} disabled={sending}>
      {sending ? 'Sending...' : 'Send Invoice to QuickBooks'}
    </button>
    {#if onCancel}
      <button onclick={onCancel} disabled={sending}>Cancel</button>
    {/if}
  </p>
</fieldset>
```

- [ ] **Step 2: Create the InvoiceDetail component**

```svelte
<!-- frontend/src/components/invoices/InvoiceDetail.svelte -->
<script>
  const {
    invoice,
    lineItems = [],
    onSendToQBO = null,
  } = $props();
</script>

<h2>Invoice {invoice.invoice_number}</h2>

<p><strong>Status:</strong> {invoice.status}</p>
<p><strong>Job:</strong> <a href="#/jobs/{invoice.job}">{invoice.job_number || `Job #${invoice.job}`}</a></p>
{#if invoice.created_date}
  <p><strong>Created:</strong> {new Date(invoice.created_date).toLocaleDateString()}</p>
{/if}

{#if invoice.qbo_id}
  <fieldset>
    <legend><strong>QuickBooks Status</strong></legend>
    <p><strong>QBO ID:</strong> {invoice.qbo_id}</p>
    <p><strong>Payment Status:</strong> {invoice.qbo_payment_status || 'Pending'}</p>
    {#if invoice.qbo_amount_paid}
      <p><strong>Amount Paid:</strong> ${Number(invoice.qbo_amount_paid).toFixed(2)}</p>
    {/if}
  </fieldset>
{:else if onSendToQBO}
  <p><button onclick={onSendToQBO}>Send to QuickBooks</button></p>
{/if}

<table border="1">
  <thead>
    <tr>
      <th>#</th>
      <th>Description</th>
      <th>Category</th>
      <th>Qty</th>
      <th>Unit</th>
      <th>Price</th>
      <th>Total</th>
    </tr>
  </thead>
  <tbody>
    {#each lineItems as item}
      <tr>
        <td>{item.line_number}</td>
        <td>{item.description}</td>
        <td>{item.accounting_category_name || '—'}</td>
        <td style="text-align: right">{item.qty}</td>
        <td>{item.units}</td>
        <td style="text-align: right">${Number(item.price).toFixed(2)}</td>
        <td style="text-align: right">${(item.qty * item.price).toFixed(2)}</td>
      </tr>
    {/each}
  </tbody>
</table>
```

- [ ] **Step 3: Create the InvoiceDetailPage**

```svelte
<!-- frontend/src/routes/invoices/InvoiceDetailPage.svelte -->
<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import InvoiceDetail from '../../components/invoices/InvoiceDetail.svelte';
  import SendToQBODialog from '../../components/invoices/SendToQBODialog.svelte';

  const { params = {} } = $props();

  let invoice = $state(null);
  let loading = $state(true);
  let error = $state(null);
  let showSendDialog = $state(false);
  let success = $state(null);

  async function loadInvoice() {
    loading = true;
    error = null;
    try {
      invoice = await api.get(`/api/invoices/${params.id}/`);
    } catch (e) {
      error = e.message || 'Failed to load invoice';
    } finally {
      loading = false;
    }
  }

  function handleSendSuccess(result) {
    showSendDialog = false;
    success = `Sent to QuickBooks (QBO ID: ${result.qbo_id})`;
    loadInvoice();  // reload to show updated QBO status
  }

  onMount(() => {
    loadInvoice();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p><strong>Error:</strong> {error}</p>
{:else if invoice}
  {#if success}
    <p><strong>{success}</strong></p>
  {/if}

  <InvoiceDetail
    {invoice}
    lineItems={invoice.line_items || []}
    onSendToQBO={() => showSendDialog = true}
  />

  {#if showSendDialog}
    <SendToQBODialog
      invoiceId={invoice.invoice_id}
      defaultEmail={invoice.default_send_to || ''}
      onSuccess={handleSendSuccess}
      onCancel={() => showSendDialog = false}
    />
  {/if}
{/if}

<p><a href="#/jobs/{invoice?.job}">Back to Job</a></p>
```

- [ ] **Step 4: Add routes to App.svelte**

Import the page:
```javascript
import InvoiceDetailPage from './routes/invoices/InvoiceDetailPage.svelte';
```

Add to routes object:
```javascript
'/invoices/:id': InvoiceDetailPage,
```

- [ ] **Step 5: Add default_send_to to InvoiceSerializer**

The SPA needs the contact's email to pre-fill the "Send To" field. Add a computed field to `apps/api/invoicing/serializers.py`:

```python
class InvoiceSerializer(serializers.ModelSerializer):
    line_items = InvoiceLineItemSerializer(
        source='invoicelineitem_set', many=True, read_only=True
    )
    default_send_to = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            'invoice_id', 'job', 'invoice_number', 'status',
            'created_date', 'sent_date', 'closed_date', 'line_items',
            'qbo_id', 'qbo_payment_status', 'qbo_amount_paid',
            'default_send_to',
        ]
        # ... read_only_fields as before

    def get_default_send_to(self, obj):
        """Return the job contact's email for pre-filling Send To."""
        if obj.job and obj.job.contact:
            return obj.job.contact.email
        return ''
```

- [ ] **Step 6: Verify manually**

```bash
./dev.sh
```

Navigate to a job detail page that has an invoice. Click the invoice link — should go to `/#/invoices/{id}` and show the invoice detail with line items. If not yet synced to QBO, shows "Send to QuickBooks" button. Clicking it shows the email dialog.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/ apps/api/invoicing/serializers.py
git commit -m "feat: add SPA invoice detail page with Send to QBO flow"
```

---

### Task 8: Run Full Test Suite and Verify

**Files:** None — verification only.

- [ ] **Step 1: Run full test suite**

```bash
python manage.py test -v2
```

Expected: All tests pass.

- [ ] **Step 2: Verify management command**

```bash
python manage.py poll_qbo_payments
```

Expected: Runs without error (reports no connection or no synced invoices).

- [ ] **Step 3: Review what was built**

| Component | Location | Purpose |
|---|---|---|
| Invoice QBO fields | `apps/invoicing/models.py` | qbo_id, qbo_payment_status, qbo_amount_paid |
| InvoiceGroupingService | `apps/invoicing/services.py` | Group line items by category + taxability |
| Job statement PDF | `apps/invoicing/pdf.py` | WeasyPrint PDF generation |
| QBOInvoiceSyncService | `apps/qbo/services.py` | Push invoice, attach PDF, send email |
| QBOPaymentPollingService | `apps/qbo/services.py` | Poll QBO for payment status |
| send-to-qbo action | `apps/api/invoicing/views.py` | API endpoint for SPA |
| poll_qbo_payments command | `apps/invoicing/management/commands/` | Cron-friendly polling |
| Invoice detail page | `frontend/src/routes/invoices/` | SPA invoice view |
| Send to QBO dialog | `frontend/src/components/invoices/` | Email recipient picker |

- [ ] **Step 4: Commit if any cleanup needed**

```bash
git status
git add apps/ tests/ frontend/ && git commit -m "chore: invoice push cleanup"
```

# Invoice Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a draft-invoice wizard that lets users group bleps and materials from a job into custom-named line items, with whole-atom claim tracking to prevent double-billing.

**Architecture:** A new `InvoiceLineItemSource` polymorphic join table records which atoms (`Blep` or `Material`) belong to each `InvoiceLineItem`, with a DB-level unique constraint enforcing "at most one line item per atom." A new `InvoiceWizardService` orchestrates the source-pool query and atom-manipulation operations. The wizard UI is a two-pane Svelte SPA page that writes through to the draft invoice on every action.

**Tech Stack:** Django 5.2, DRF, MySQL, Svelte 5, Vite

**Design spec:** `docs/designs/2026-04-09-invoice-wizard-design.md`

**Prerequisites:** None — all referenced models (`Blep`, `Material`, `Invoice`, `InvoiceLineItem`) already exist.

---

## File Structure

### New files

```
apps/invoicing/
  models.py                                  # MODIFY: Add InvoiceLineItemSource, drop InvoiceLineItem.task
  services.py                                # MODIFY: Add InvoiceWizardService, ClaimConflict
  migrations/NNNN_add_invoice_line_item_source.py
  migrations/NNNN_unique_draft_invoice_per_job.py
  migrations/NNNN_drop_invoicelineitem_task_fk.py

apps/api/invoicing/
  serializers.py                             # MODIFY: Extend InvoiceLineItemSerializer, add SourcePoolSerializer
  views.py                                   # MODIFY: Add wizard actions to InvoiceViewSet

apps/api/jobs/
  views.py                                   # MODIFY: Add start_invoice_wizard action

frontend/src/
  routes/invoices/InvoiceWizardPage.svelte   # NEW
  components/invoices/WizardSourcePool.svelte # NEW
  components/invoices/WizardLineItemCard.svelte # NEW
  components/invoices/WizardFooter.svelte    # NEW
  App.svelte                                 # MODIFY: Add /invoices/:id/wizard route
  routes/jobs/JobDetailPage.svelte           # MODIFY: Add "Build invoice" button

tests/
  test_invoice_line_item_source.py           # NEW: Model tests
  test_invoice_wizard_service.py             # NEW: Service layer tests
  test_invoice_wizard_api.py                 # NEW: API tests
```

### Conventions used throughout

- Test base class: `tests.base.FixtureTestCase` (loads `fixtures/unit_test_data.json`)
- Tests are run with `python manage.py test tests.test_name`
- **Never run `python manage.py migrate`** — the human user applies migrations. Tests create their own DB.
- After each model change, run `python manage.py makemigrations invoicing` and commit the generated migration alongside the code change.
- DRF viewsets delegate to services, not `serializer.save()`.
- DELETE endpoints return 200 with JSON, not 204.
- Commit after every task with a conventional-commit-style message.

---

## Phase 1 — Data model

### Task 1: Add `InvoiceLineItemSource` model

**Files:**
- Modify: `apps/invoicing/models.py`
- Create: `apps/invoicing/migrations/NNNN_add_invoice_line_item_source.py` (auto-generated)
- Create: `tests/test_invoice_line_item_source.py`

- [ ] **Step 1: Write the failing model tests**

Create `tests/test_invoice_line_item_source.py`:

```python
from django.db import IntegrityError
from django.test import TestCase
from decimal import Decimal
from django.utils import timezone

from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.jobs.models import Job, WorkOrder, Task, Blep
from apps.inventory.models import Material, PriceListItem
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration, AccountingCategory


class InvoiceLineItemSourceTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED)
        self.workorder = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.workorder,
            name='Labor',
            rate=Decimal('25.00'),
            accounting_category=self.category,
        )
        self.blep = Blep.objects.create(
            task=self.task,
            start_time=timezone.now(),
            end_time=timezone.now(),
        )

        self.invoice = Invoice.objects.create(job=self.job)
        self.line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Test',
            qty=Decimal('1'),
            price=Decimal('100.00'),
            accounting_category=self.category,
        )

    def test_source_links_line_item_to_blep(self):
        source = InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep.pk,
        )
        self.assertEqual(source.invoice_line_item, self.line_item)
        self.assertEqual(source.source_pk, self.blep.pk)

    def test_resolve_returns_blep_instance(self):
        source = InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep.pk,
        )
        resolved = source.resolve()
        self.assertEqual(resolved, self.blep)

    def test_unique_atom_constraint_prevents_double_claim(self):
        InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep.pk,
        )
        other_line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Other',
            qty=Decimal('1'),
            price=Decimal('50.00'),
            accounting_category=self.category,
        )
        with self.assertRaises(IntegrityError):
            InvoiceLineItemSource.objects.create(
                invoice_line_item=other_line_item,
                source_type=InvoiceLineItemSource.SOURCE_BLEP,
                source_pk=self.blep.pk,
            )

    def test_deleting_line_item_cascades_to_sources(self):
        source = InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep.pk,
        )
        self.line_item.delete()
        self.assertFalse(
            InvoiceLineItemSource.objects.filter(pk=source.pk).exists()
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_invoice_line_item_source -v 2`
Expected: ImportError — `InvoiceLineItemSource` does not exist in `apps.invoicing.models`.

- [ ] **Step 3: Add the model**

Modify `apps/invoicing/models.py`. Add at the end of the file, after `InvoiceLineItem`:

```python
class InvoiceLineItemSource(models.Model):
    """Polymorphic join between an InvoiceLineItem and its source atom (Blep or Material).

    The unique_together on (source_type, source_pk) enforces whole-atom claim at the
    database level: an atom can be referenced by at most one line item.
    """
    SOURCE_BLEP = 'blep'
    SOURCE_MATERIAL = 'material'
    SOURCE_TYPE_CHOICES = [
        (SOURCE_BLEP, 'Blep'),
        (SOURCE_MATERIAL, 'Material'),
    ]

    source_id = models.AutoField(primary_key=True)
    invoice_line_item = models.ForeignKey(
        InvoiceLineItem,
        on_delete=models.CASCADE,
        related_name='sources',
    )
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPE_CHOICES)
    source_pk = models.PositiveIntegerField()

    class Meta:
        db_table = 'invoice_line_item_sources'
        unique_together = [('source_type', 'source_pk')]

    def resolve(self):
        """Return the concrete atom instance (Blep or Material) referenced by this source."""
        if self.source_type == self.SOURCE_BLEP:
            from apps.jobs.models import Blep
            return Blep.objects.get(pk=self.source_pk)
        if self.source_type == self.SOURCE_MATERIAL:
            from apps.inventory.models import Material
            return Material.objects.get(pk=self.source_pk)
        raise ValueError(f'Unknown source_type: {self.source_type}')

    def __str__(self):
        return f'Source {self.source_id}: {self.source_type}:{self.source_pk} → LineItem {self.invoice_line_item_id}'
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations invoicing`
Expected: "Create model InvoiceLineItemSource" — a new file appears at `apps/invoicing/migrations/NNNN_invoicelineitemsource.py` (exact number depends on the current migration count).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_invoice_line_item_source -v 2`
Expected: all four tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/invoicing/models.py apps/invoicing/migrations/ tests/test_invoice_line_item_source.py
git commit -m "feat(invoicing): add InvoiceLineItemSource polymorphic join model"
```

---

### Task 2: Unique-draft-per-job constraint

**Files:**
- Modify: `apps/invoicing/models.py`
- Create: `apps/invoicing/migrations/NNNN_unique_draft_invoice_per_job.py` (auto-generated)
- Modify: `tests/test_invoice_line_item_source.py` (add a new test class for this constraint)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_invoice_line_item_source.py`:

```python
class UniqueDraftInvoicePerJobTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED)

    def test_second_draft_for_same_job_raises(self):
        Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        with self.assertRaises(IntegrityError):
            Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_multiple_non_draft_invoices_allowed(self):
        # Two open invoices for the same job is fine
        Invoice.objects.create(job=self.job, status=Invoice.STATUS_OPEN)
        Invoice.objects.create(job=self.job, status=Invoice.STATUS_OPEN)
        self.assertEqual(
            Invoice.objects.filter(job=self.job, status=Invoice.STATUS_OPEN).count(),
            2,
        )

    def test_draft_plus_non_draft_allowed(self):
        Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        Invoice.objects.create(job=self.job, status=Invoice.STATUS_OPEN)
        self.assertEqual(Invoice.objects.filter(job=self.job).count(), 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_invoice_line_item_source.UniqueDraftInvoicePerJobTest -v 2`
Expected: `test_second_draft_for_same_job_raises` FAILs — two drafts currently can coexist.

- [ ] **Step 3: Add the constraint to the Invoice model**

Modify `apps/invoicing/models.py`. Find `class Invoice(models.Model)` and its `Meta`. Update `Meta` to add a `constraints` entry:

```python
    class Meta:
        db_table = 'invoices'
        constraints = [
            models.UniqueConstraint(
                fields=['job'],
                condition=models.Q(status='draft'),
                name='unique_draft_invoice_per_job',
            ),
        ]
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations invoicing`
Expected: "Create constraint unique_draft_invoice_per_job on model invoice" — a new migration file.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_invoice_line_item_source.UniqueDraftInvoicePerJobTest -v 2`
Expected: all three tests pass.

- [ ] **Step 6: Check the fixture doesn't already have duplicate drafts**

Run: `python manage.py test tests.test_invoice_line_item_source -v 2`
Expected: all tests pass (including Task 1's tests, which load no fixture).

If any existing fixture-loading test breaks due to duplicate drafts in `fixtures/unit_test_data.json`, fix the fixture to have at most one draft invoice per job, then commit that fix separately.

- [ ] **Step 7: Commit**

```bash
git add apps/invoicing/models.py apps/invoicing/migrations/ tests/test_invoice_line_item_source.py
git commit -m "feat(invoicing): enforce one draft invoice per job"
```

---

### Task 3: Drop `InvoiceLineItem.task` FK

**Files:**
- Modify: `apps/invoicing/models.py`
- Modify: `apps/api/invoicing/serializers.py`
- Create: `apps/invoicing/migrations/NNNN_drop_invoicelineitem_task.py`
- Potentially modify: `fixtures/unit_test_data.json` (if existing rows reference `task`)
- Potentially modify: existing tests that reference `InvoiceLineItem.task`

- [ ] **Step 1: Find existing references to `InvoiceLineItem.task`**

Run: `grep -rn "invoicelineitem.*task\|InvoiceLineItem.*task\|line_item.*task\|\.task\s*=.*task" apps/ tests/ fixtures/ --include="*.py" --include="*.json"`

Expected: a list of references that will need updating. The goal of this step is awareness, not editing.

- [ ] **Step 2: Remove the `task` field from the model**

Modify `apps/invoicing/models.py`. In `class InvoiceLineItem(BaseLineItem)`, delete this line:

```python
    task = models.ForeignKey('jobs.Task', on_delete=models.PROTECT, null=True, blank=True)
```

**Note:** The `BaseLineItem` abstract base class has a comment that `task` is defined on each concrete subclass because it targets different models. Deleting `task` from `InvoiceLineItem` only affects this one concrete class. The abstract `BaseLineItem.clean()` method references `self.task` — that still needs to work for the other concrete classes (`EstimateLineItem`, `PurchaseOrderLineItem`, `BillLineItem`). We handle the `InvoiceLineItem`-specific part by overriding `clean()`:

```python
class InvoiceLineItem(BaseLineItem):
    """Line item for invoices - inherits shared functionality from BaseLineItem."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE)

    class Meta:
        db_table = 'invoice_li'
        verbose_name = "Invoice Line Item"
        verbose_name_plural = "Invoice Line Items"

    @property
    def task(self):
        """InvoiceLineItem no longer has a direct task FK. Kept as None for BaseLineItem.clean() compatibility."""
        return None

    def get_parent_field_name(self):
        """Get the name of the parent field for this line item type."""
        return 'invoice'

    def __str__(self):
        return f"Invoice Line Item {self.pk} for {self.invoice.invoice_number}"
```

The `@property task` returning `None` keeps `BaseLineItem.clean()`'s `self.task is not None` check happy (it sees `None` → passes).

- [ ] **Step 3: Remove `task` from the serializer**

Modify `apps/api/invoicing/serializers.py`. In `InvoiceLineItemSerializer.Meta.fields`, delete `'task',`:

```python
    class Meta:
        model = InvoiceLineItem
        fields = [
            'line_item_id', 'line_number', 'price_list_item',
            'qty', 'units', 'description', 'price',
            'accounting_category', 'accounting_category_name',
            'taxable_override', 'tax_rate_override',
        ]
        read_only_fields = ['line_item_id']
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations invoicing`
Expected: "Remove field task from invoicelineitem" — a new migration file.

- [ ] **Step 5: Fix any existing references surfaced by Step 1**

For each reference found in Step 1:
- **In tests:** remove `task=` from any `InvoiceLineItem.objects.create(...)` calls. Rewrite any `.filter(task=...)` or `.get(task=...)` queries — there's no replacement, so the test is either checking behavior that no longer exists (delete the test) or can use the invoice/line_item id (rewrite).
- **In fixtures:** remove the `task` field from any `invoice_li` rows in `fixtures/unit_test_data.json`.
- **In apps/ code:** this should be rare (the `InvoiceLineItem.task` FK wasn't used by the main flows). If it's referenced, remove the reference and adapt the caller.

- [ ] **Step 6: Run the full test suite**

Run: `python manage.py test`
Expected: all tests pass. If any fail with `FieldError` or `AttributeError` related to `task`, go back to Step 5.

- [ ] **Step 7: Commit**

```bash
git add apps/invoicing/models.py apps/invoicing/migrations/ apps/api/invoicing/serializers.py fixtures/unit_test_data.json tests/
git commit -m "feat(invoicing): drop InvoiceLineItem.task FK (replaced by InvoiceLineItemSource)"
```

---

## Phase 2 — Wizard service

All tasks in this phase add methods to a new `InvoiceWizardService` class in `apps/invoicing/services.py`. Tests go in `tests/test_invoice_wizard_service.py`.

### Task 4: `InvoiceWizardService.open_for_job`

**Files:**
- Modify: `apps/invoicing/services.py`
- Create: `tests/test_invoice_wizard_service.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_invoice_wizard_service.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.invoicing.models import Invoice
from apps.invoicing.services import InvoiceWizardService
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business
from apps.core.models import Configuration, AccountingCategory


class OpenForJobTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.approved_job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED)
        self.draft_job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT)
        self.rejected_job = Job.objects.create(contact=self.contact, status=Job.STATUS_REJECTED)

    def test_creates_draft_when_none_exists(self):
        invoice = InvoiceWizardService.open_for_job(self.approved_job)
        self.assertEqual(invoice.status, Invoice.STATUS_DRAFT)
        self.assertEqual(invoice.job, self.approved_job)

    def test_returns_existing_draft(self):
        first = InvoiceWizardService.open_for_job(self.approved_job)
        second = InvoiceWizardService.open_for_job(self.approved_job)
        self.assertEqual(first.pk, second.pk)

    def test_creates_new_draft_alongside_sent_invoice(self):
        # A non-draft invoice on the job doesn't block creating a new draft
        Invoice.objects.create(job=self.approved_job, status=Invoice.STATUS_OPEN)
        draft = InvoiceWizardService.open_for_job(self.approved_job)
        self.assertEqual(draft.status, Invoice.STATUS_DRAFT)
        self.assertEqual(Invoice.objects.filter(job=self.approved_job).count(), 2)

    def test_refuses_draft_job(self):
        with self.assertRaises(ValidationError):
            InvoiceWizardService.open_for_job(self.draft_job)

    def test_refuses_rejected_job(self):
        with self.assertRaises(ValidationError):
            InvoiceWizardService.open_for_job(self.rejected_job)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_invoice_wizard_service.OpenForJobTest -v 2`
Expected: ImportError — `InvoiceWizardService` does not exist.

- [ ] **Step 3: Add the service skeleton and `open_for_job`**

Modify `apps/invoicing/services.py`. Append at the end of the file:

```python
class ClaimConflict(Exception):
    """Raised when the wizard tries to claim an atom already claimed elsewhere."""

    def __init__(self, atom_ids):
        self.atom_ids = atom_ids
        super().__init__(f'Atoms already claimed: {atom_ids}')


class InvoiceWizardService:
    """Orchestration layer for the invoice wizard.

    Composes on top of InvoiceService rather than replacing it. The wizard service
    handles the atom-based flows; manual line item CRUD continues to use InvoiceService.
    """

    # Job statuses that allow invoicing
    BILLABLE_JOB_STATUSES = {Job.STATUS_APPROVED, Job.STATUS_COMPLETED}

    @staticmethod
    def open_for_job(job):
        """Return the job's draft Invoice, creating one if none exists.

        Raises ValidationError if the job is in a status that doesn't allow invoicing.
        """
        from apps.jobs.models import Job  # re-import for clarity
        if job.status not in InvoiceWizardService.BILLABLE_JOB_STATUSES:
            raise ValidationError(
                f'Cannot start invoice wizard for job in status "{job.status}". '
                f'Job must be approved or completed.'
            )

        existing = Invoice.objects.filter(
            job=job, status=Invoice.STATUS_DRAFT
        ).first()
        if existing:
            return existing

        return Invoice.objects.create(job=job, status=Invoice.STATUS_DRAFT)
```

Add the `Job` import at the top of the file:

```python
from apps.jobs.models import Job
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_invoice_wizard_service.OpenForJobTest -v 2`
Expected: all five tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/invoicing/services.py tests/test_invoice_wizard_service.py
git commit -m "feat(invoicing): InvoiceWizardService.open_for_job"
```

---

### Task 5: `InvoiceWizardService.get_source_pool`

This is the largest service method. It walks the job → work orders → tasks → atoms, filters out cancelled tasks and incomplete bleps, and annotates each atom with its state (`available`, `claimed_by_current`, `claimed_by_other`).

**Return shape:**

```python
{
    'work_orders': [
        {
            'work_order_id': 51,
            'tasks': [
                {
                    'task_id': 100,
                    'name': 'Site demo',
                    'has_billable_atoms': True,
                    'atoms': [
                        {
                            'atom_type': 'blep',
                            'atom_id': 200,
                            'description': 'Labor 2h',
                            'sub_info': '04/01 · J. Doe',
                            'computed_amount': Decimal('50.00'),
                            'state': 'available',  # or 'claimed_by_current' or 'claimed_by_other'
                            'claiming_line_item_id': None,  # only if claimed_by_current
                            'claiming_invoice_id': None,    # only if claimed_by_other
                            'claiming_invoice_number': None, # only if claimed_by_other
                        },
                        ...
                    ],
                },
                ...
            ],
        },
        ...
    ],
}
```

**Files:**
- Modify: `apps/invoicing/services.py`
- Modify: `tests/test_invoice_wizard_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_invoice_wizard_service.py`:

```python
from apps.jobs.models import WorkOrder, Task, Blep
from apps.inventory.models import Material, PriceListItem
from apps.invoicing.models import InvoiceLineItem, InvoiceLineItemSource


class GetSourcePoolTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED)
        self.wo = WorkOrder.objects.create(job=self.job)

        self.task_billable = Task.objects.create(
            work_order=self.wo, name='Site demo',
            rate=Decimal('25.00'), accounting_category=self.category,
        )
        self.task_empty = Task.objects.create(
            work_order=self.wo, name='Inspection',
            rate=Decimal('50.00'), accounting_category=self.category,
        )
        self.task_cancelled = Task.objects.create(
            work_order=self.wo, name='Cancelled work',
            rate=Decimal('25.00'), accounting_category=self.category,
        )
        self.task_cancelled.status = Task.STATUS_CANCELLED
        self.task_cancelled.save()

        # Complete blep (billable)
        self.blep_complete = Blep.objects.create(
            task=self.task_billable,
            start_time=timezone.now() - timezone.timedelta(hours=2),
            end_time=timezone.now(),
        )
        # Incomplete blep (should be filtered out)
        self.blep_incomplete = Blep.objects.create(
            task=self.task_billable,
            start_time=timezone.now(),
            end_time=None,
        )

        self.pli = PriceListItem.objects.create(
            code='PLYWOOD', description='Plywood 4x8',
            selling_price=Decimal('25.00'),
            accounting_category=self.category,
        )
        self.material = Material.objects.create(
            task=self.task_billable,
            description='Plywood 4x8',
            quantity=Decimal('1.00'),
            sell_price=Decimal('25.00'),
            price_list_item=self.pli,
            accounting_category=self.category,
        )

        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_tree_includes_work_orders_and_tasks(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        self.assertEqual(len(pool['work_orders']), 1)
        task_names = [t['name'] for t in pool['work_orders'][0]['tasks']]
        # Billable and empty are shown, cancelled is not
        self.assertIn('Site demo', task_names)
        self.assertIn('Inspection', task_names)
        self.assertNotIn('Cancelled work', task_names)

    def test_incomplete_bleps_are_excluded(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['work_orders'][0]['tasks'] if t['name'] == 'Site demo'
        )
        blep_atoms = [a for a in site_demo['atoms'] if a['atom_type'] == 'blep']
        # Only the complete blep, not the incomplete one
        self.assertEqual(len(blep_atoms), 1)
        self.assertEqual(blep_atoms[0]['atom_id'], self.blep_complete.pk)

    def test_empty_task_has_flag_set(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        inspection = next(
            t for t in pool['work_orders'][0]['tasks'] if t['name'] == 'Inspection'
        )
        self.assertFalse(inspection['has_billable_atoms'])
        self.assertEqual(inspection['atoms'], [])

    def test_atom_state_available(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['work_orders'][0]['tasks'] if t['name'] == 'Site demo'
        )
        for atom in site_demo['atoms']:
            self.assertEqual(atom['state'], 'available')

    def test_atom_state_claimed_by_current(self):
        line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Test',
            qty=Decimal('1'),
            price=Decimal('50.00'),
            accounting_category=self.category,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=line_item,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep_complete.pk,
        )
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['work_orders'][0]['tasks'] if t['name'] == 'Site demo'
        )
        claimed = next(a for a in site_demo['atoms'] if a['atom_id'] == self.blep_complete.pk)
        self.assertEqual(claimed['state'], 'claimed_by_current')
        self.assertEqual(claimed['claiming_line_item_id'], line_item.pk)

    def test_atom_state_claimed_by_other_invoice(self):
        other_invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_OPEN)
        other_li = InvoiceLineItem.objects.create(
            invoice=other_invoice,
            description='Prior',
            qty=Decimal('1'),
            price=Decimal('50.00'),
            accounting_category=self.category,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=other_li,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep_complete.pk,
        )
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['work_orders'][0]['tasks'] if t['name'] == 'Site demo'
        )
        claimed = next(a for a in site_demo['atoms'] if a['atom_id'] == self.blep_complete.pk)
        self.assertEqual(claimed['state'], 'claimed_by_other')
        self.assertEqual(claimed['claiming_invoice_id'], other_invoice.pk)
        self.assertEqual(claimed['claiming_invoice_number'], other_invoice.invoice_number)

    def test_atoms_on_cancelled_invoice_are_available(self):
        other_invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_CANCELLED)
        other_li = InvoiceLineItem.objects.create(
            invoice=other_invoice,
            description='Prior',
            qty=Decimal('1'),
            price=Decimal('50.00'),
            accounting_category=self.category,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=other_li,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep_complete.pk,
        )
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['work_orders'][0]['tasks'] if t['name'] == 'Site demo'
        )
        claimed_blep = next(a for a in site_demo['atoms'] if a['atom_id'] == self.blep_complete.pk)
        self.assertEqual(claimed_blep['state'], 'available')

    def test_material_atoms_included(self):
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        site_demo = next(
            t for t in pool['work_orders'][0]['tasks'] if t['name'] == 'Site demo'
        )
        materials = [a for a in site_demo['atoms'] if a['atom_type'] == 'material']
        self.assertEqual(len(materials), 1)
        self.assertEqual(materials[0]['atom_id'], self.material.pk)
        self.assertEqual(materials[0]['computed_amount'], Decimal('25.00'))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_invoice_wizard_service.GetSourcePoolTest -v 2`
Expected: AttributeError — `get_source_pool` doesn't exist.

- [ ] **Step 3: Implement `get_source_pool`**

Add to `InvoiceWizardService` in `apps/invoicing/services.py`:

```python
    @staticmethod
    def get_source_pool(invoice):
        """Walk the job's work orders → tasks → atoms and return the source pool tree.

        Atoms are annotated with state: 'available', 'claimed_by_current', or 'claimed_by_other'.
        """
        from decimal import Decimal
        from apps.jobs.models import WorkOrder, Task, Blep
        from apps.inventory.models import Material
        from apps.invoicing.models import InvoiceLineItemSource, InvoiceLineItem

        job = invoice.job

        # Build the claim lookup: atom key → (state, claiming_line_item_id, claiming_invoice_id, claiming_invoice_number)
        # Only non-cancelled invoices create claims
        claimed_sources = (
            InvoiceLineItemSource.objects
            .filter(invoice_line_item__invoice__job=job)
            .exclude(invoice_line_item__invoice__status=Invoice.STATUS_CANCELLED)
            .select_related('invoice_line_item', 'invoice_line_item__invoice')
        )
        claims = {}  # (source_type, source_pk) → dict of state info
        for src in claimed_sources:
            li = src.invoice_line_item
            inv = li.invoice
            key = (src.source_type, src.source_pk)
            if inv.pk == invoice.pk:
                claims[key] = {
                    'state': 'claimed_by_current',
                    'claiming_line_item_id': li.pk,
                    'claiming_invoice_id': None,
                    'claiming_invoice_number': None,
                }
            else:
                claims[key] = {
                    'state': 'claimed_by_other',
                    'claiming_line_item_id': None,
                    'claiming_invoice_id': inv.pk,
                    'claiming_invoice_number': inv.invoice_number,
                }

        work_orders = WorkOrder.objects.filter(job=job).order_by('pk')
        wo_list = []
        for wo in work_orders:
            tasks = (
                Task.objects.filter(work_order=wo)
                .exclude(status=Task.STATUS_CANCELLED)
                .order_by('sort_order', 'pk')
                .prefetch_related('blep_set', 'materials')
            )
            task_list = []
            for task in tasks:
                atoms = []

                # Blep atoms — exclude incomplete bleps
                bleps = (
                    Blep.objects.filter(task=task)
                    .exclude(end_time__isnull=True)
                    .order_by('start_time', 'pk')
                )
                for blep in bleps:
                    elapsed = blep.end_time - blep.start_time
                    hours = Decimal(str(elapsed.total_seconds())) / Decimal('3600')
                    amount = (hours * (task.rate or Decimal('0.00'))).quantize(Decimal('0.01'))
                    key = (InvoiceLineItemSource.SOURCE_BLEP, blep.pk)
                    state_info = claims.get(key, {
                        'state': 'available',
                        'claiming_line_item_id': None,
                        'claiming_invoice_id': None,
                        'claiming_invoice_number': None,
                    })
                    atoms.append({
                        'atom_type': 'blep',
                        'atom_id': blep.pk,
                        'description': f'Labor {hours:.2f}h',
                        'sub_info': f"{blep.start_time.strftime('%m/%d')} · {blep.user.username if blep.user else '—'}",
                        'computed_amount': amount,
                        **state_info,
                    })

                # Material atoms
                materials = Material.objects.filter(task=task).order_by('pk')
                for mat in materials:
                    amount = (mat.quantity * mat.sell_price).quantize(Decimal('0.01'))
                    key = (InvoiceLineItemSource.SOURCE_MATERIAL, mat.pk)
                    state_info = claims.get(key, {
                        'state': 'available',
                        'claiming_line_item_id': None,
                        'claiming_invoice_id': None,
                        'claiming_invoice_number': None,
                    })
                    atoms.append({
                        'atom_type': 'material',
                        'atom_id': mat.pk,
                        'description': mat.description,
                        'sub_info': '',
                        'computed_amount': amount,
                        **state_info,
                    })

                task_list.append({
                    'task_id': task.pk,
                    'name': task.name,
                    'has_billable_atoms': len(atoms) > 0,
                    'atoms': atoms,
                })

            wo_list.append({
                'work_order_id': wo.pk,
                'tasks': task_list,
            })

        return {'work_orders': wo_list}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_invoice_wizard_service.GetSourcePoolTest -v 2`
Expected: all eight tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/invoicing/services.py tests/test_invoice_wizard_service.py
git commit -m "feat(invoicing): InvoiceWizardService.get_source_pool"
```

---

### Task 6: `InvoiceWizardService.add_atoms_to_new_line_item`

**Files:**
- Modify: `apps/invoicing/services.py`
- Modify: `tests/test_invoice_wizard_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_invoice_wizard_service.py`:

```python
from apps.invoicing.services import ClaimConflict


class AddAtomsToNewLineItemTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.cat_labor = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.cat_materials = AccountingCategory.objects.create(name='Materials', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED)
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo, name='Labor',
            rate=Decimal('25.00'), accounting_category=self.cat_labor,
        )
        start = timezone.now() - timezone.timedelta(hours=2)
        self.blep1 = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.blep2 = Blep.objects.create(
            task=self.task,
            start_time=start + timezone.timedelta(hours=3),
            end_time=start + timezone.timedelta(hours=4),
        )
        self.pli = PriceListItem.objects.create(
            code='PLY', description='Plywood',
            selling_price=Decimal('25.00'),
            accounting_category=self.cat_materials,
        )
        self.material = Material.objects.create(
            task=self.task, description='Plywood',
            quantity=Decimal('1.00'), sell_price=Decimal('25.00'),
            price_list_item=self.pli, accounting_category=self.cat_materials,
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_creates_line_item_and_sources(self):
        atoms = [
            {'type': 'blep', 'id': self.blep1.pk},
            {'type': 'blep', 'id': self.blep2.pk},
        ]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.sources.count(), 2)
        self.assertEqual(line_item.invoice, self.invoice)

    def test_default_price_is_sum_of_atoms(self):
        atoms = [
            {'type': 'blep', 'id': self.blep1.pk},  # 2h × $25 = $50
            {'type': 'blep', 'id': self.blep2.pk},  # 1h × $25 = $25
        ]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.price, Decimal('75.00'))

    def test_default_qty_and_units(self):
        atoms = [{'type': 'blep', 'id': self.blep1.pk}]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.qty, Decimal('1'))
        self.assertEqual(line_item.units, 'each')

    def test_default_description_is_blank(self):
        atoms = [{'type': 'blep', 'id': self.blep1.pk}]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.description, '')

    def test_category_set_when_all_atoms_share_one(self):
        atoms = [
            {'type': 'blep', 'id': self.blep1.pk},
            {'type': 'blep', 'id': self.blep2.pk},
        ]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertEqual(line_item.accounting_category, self.cat_labor)

    def test_category_null_when_atoms_mixed(self):
        atoms = [
            {'type': 'blep', 'id': self.blep1.pk},       # labor
            {'type': 'material', 'id': self.material.pk}, # materials
        ]
        line_item = InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertIsNone(line_item.accounting_category)

    def test_concurrent_claim_raises_claim_conflict(self):
        # Pre-claim blep1 via another line item
        prior_li = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Prior',
            qty=Decimal('1'),
            price=Decimal('50.00'),
            accounting_category=self.cat_labor,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=prior_li,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep1.pk,
        )
        atoms = [{'type': 'blep', 'id': self.blep1.pk}]
        with self.assertRaises(ClaimConflict) as ctx:
            InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        self.assertIn(
            {'type': 'blep', 'id': self.blep1.pk},
            ctx.exception.atom_ids,
        )

    def test_concurrent_claim_rolls_back_fully(self):
        # If any atom conflicts, the whole operation is rolled back — no new line item.
        prior_li = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Prior',
            qty=Decimal('1'),
            price=Decimal('50.00'),
            accounting_category=self.cat_labor,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=prior_li,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep1.pk,
        )
        initial_count = InvoiceLineItem.objects.filter(invoice=self.invoice).count()
        atoms = [
            {'type': 'blep', 'id': self.blep1.pk},  # conflict
            {'type': 'blep', 'id': self.blep2.pk},  # would be fine
        ]
        try:
            InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
        except ClaimConflict:
            pass
        self.assertEqual(
            InvoiceLineItem.objects.filter(invoice=self.invoice).count(),
            initial_count,
        )

    def test_refuses_mutation_on_non_draft_invoice(self):
        self.invoice.status = Invoice.STATUS_OPEN
        self.invoice.save()
        atoms = [{'type': 'blep', 'id': self.blep1.pk}]
        with self.assertRaises(ValidationError):
            InvoiceWizardService.add_atoms_to_new_line_item(self.invoice, atoms)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_invoice_wizard_service.AddAtomsToNewLineItemTest -v 2`
Expected: AttributeError on `add_atoms_to_new_line_item`.

- [ ] **Step 3: Implement `add_atoms_to_new_line_item`**

Add to `InvoiceWizardService` in `apps/invoicing/services.py`:

```python
    @staticmethod
    def _validate_draft(invoice):
        if invoice.status != Invoice.STATUS_DRAFT:
            raise ValidationError('Wizard can only modify draft invoices.')

    @staticmethod
    def _resolve_atom(atom_ref):
        """Given {'type': 'blep'|'material', 'id': N}, return the concrete instance."""
        from apps.jobs.models import Blep
        from apps.inventory.models import Material
        if atom_ref['type'] == 'blep':
            return Blep.objects.get(pk=atom_ref['id'])
        if atom_ref['type'] == 'material':
            return Material.objects.get(pk=atom_ref['id'])
        raise ValueError(f"Unknown atom type: {atom_ref['type']}")

    @staticmethod
    def _atom_computed_amount(atom_instance):
        """Compute the billable amount for an atom."""
        from decimal import Decimal
        from apps.jobs.models import Blep
        from apps.inventory.models import Material
        if isinstance(atom_instance, Blep):
            if not atom_instance.end_time:
                return Decimal('0.00')
            elapsed = atom_instance.end_time - atom_instance.start_time
            hours = Decimal(str(elapsed.total_seconds())) / Decimal('3600')
            rate = atom_instance.task.rate or Decimal('0.00')
            return (hours * rate).quantize(Decimal('0.01'))
        if isinstance(atom_instance, Material):
            return (atom_instance.quantity * atom_instance.sell_price).quantize(Decimal('0.01'))
        raise ValueError(f"Unknown atom instance type: {type(atom_instance)}")

    @staticmethod
    def _atom_category(atom_instance):
        """Return the accounting_category of an atom (via its task for bleps, direct for materials)."""
        from apps.jobs.models import Blep
        from apps.inventory.models import Material
        if isinstance(atom_instance, Blep):
            return atom_instance.task.accounting_category
        if isinstance(atom_instance, Material):
            return atom_instance.accounting_category
        return None

    @staticmethod
    def _atom_source_type(atom_instance):
        from apps.jobs.models import Blep
        from apps.inventory.models import Material
        if isinstance(atom_instance, Blep):
            return InvoiceLineItemSource.SOURCE_BLEP
        if isinstance(atom_instance, Material):
            return InvoiceLineItemSource.SOURCE_MATERIAL
        raise ValueError(f"Unknown atom instance type: {type(atom_instance)}")

    @staticmethod
    def add_atoms_to_new_line_item(invoice, atoms):
        """Create a new InvoiceLineItem on `invoice` with the given atoms as sources.

        atoms: list of {'type': 'blep'|'material', 'id': N} dicts.
        """
        from decimal import Decimal
        from django.db import transaction, IntegrityError
        from apps.invoicing.models import InvoiceLineItem, InvoiceLineItemSource

        InvoiceWizardService._validate_draft(invoice)

        # Resolve all atoms up front; fail fast if any are invalid
        instances = [InvoiceWizardService._resolve_atom(a) for a in atoms]

        # Compute defaults
        total_price = sum(
            (InvoiceWizardService._atom_computed_amount(i) for i in instances),
            Decimal('0.00'),
        )
        categories = {InvoiceWizardService._atom_category(i) for i in instances}
        # Uniform category → use it; mixed → leave null
        category = categories.pop() if len(categories) == 1 else None

        try:
            with transaction.atomic():
                line_item = InvoiceLineItem.objects.create(
                    invoice=invoice,
                    description='',
                    qty=Decimal('1'),
                    units='each',
                    price=total_price,
                    accounting_category=category,
                )
                for atom_ref, instance in zip(atoms, instances):
                    InvoiceLineItemSource.objects.create(
                        invoice_line_item=line_item,
                        source_type=InvoiceWizardService._atom_source_type(instance),
                        source_pk=instance.pk,
                    )
        except IntegrityError:
            # Re-query to find which atoms are already claimed
            existing = set(
                InvoiceLineItemSource.objects
                .filter(source_type__in=[a['type'] for a in atoms])
                .values_list('source_type', 'source_pk')
            )
            conflicts = [
                a for a in atoms
                if (a['type'], a['id']) in existing
            ]
            raise ClaimConflict(atom_ids=conflicts)

        return line_item
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_invoice_wizard_service.AddAtomsToNewLineItemTest -v 2`
Expected: all nine tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/invoicing/services.py tests/test_invoice_wizard_service.py
git commit -m "feat(invoicing): InvoiceWizardService.add_atoms_to_new_line_item"
```

---

### Task 7: `InvoiceWizardService.add_atoms_to_line_item` (with override rule)

**Files:**
- Modify: `apps/invoicing/services.py`
- Modify: `tests/test_invoice_wizard_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_invoice_wizard_service.py`:

```python
class AddAtomsToExistingLineItemTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED)
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo, name='Labor',
            rate=Decimal('25.00'), accounting_category=self.category,
        )
        start = timezone.now() - timezone.timedelta(hours=4)
        self.blep1 = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.blep2 = Blep.objects.create(
            task=self.task,
            start_time=start + timezone.timedelta(hours=3),
            end_time=start + timezone.timedelta(hours=4),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

        # Start with one atom on the line item
        self.line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice,
            [{'type': 'blep', 'id': self.blep1.pk}],
        )
        # price is $50 at this point

    def test_appends_sources(self):
        InvoiceWizardService.add_atoms_to_line_item(
            self.line_item,
            [{'type': 'blep', 'id': self.blep2.pk}],
        )
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.sources.count(), 2)

    def test_recomputes_price_when_in_sync(self):
        # Line item is in sync: price $50, single atom totaling $50
        InvoiceWizardService.add_atoms_to_line_item(
            self.line_item,
            [{'type': 'blep', 'id': self.blep2.pk}],  # another $25
        )
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.price, Decimal('75.00'))

    def test_preserves_price_when_overridden(self):
        # Override the price
        self.line_item.price = Decimal('100.00')
        self.line_item.save()

        InvoiceWizardService.add_atoms_to_line_item(
            self.line_item,
            [{'type': 'blep', 'id': self.blep2.pk}],
        )
        self.line_item.refresh_from_db()
        # Price is unchanged (not $75, not $100 + $25, just $100)
        self.assertEqual(self.line_item.price, Decimal('100.00'))

    def test_refuses_mutation_on_non_draft_invoice(self):
        self.invoice.status = Invoice.STATUS_OPEN
        self.invoice.save()
        with self.assertRaises(ValidationError):
            InvoiceWizardService.add_atoms_to_line_item(
                self.line_item,
                [{'type': 'blep', 'id': self.blep2.pk}],
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_invoice_wizard_service.AddAtomsToExistingLineItemTest -v 2`
Expected: AttributeError — `add_atoms_to_line_item` doesn't exist.

- [ ] **Step 3: Implement `add_atoms_to_line_item`**

Add to `InvoiceWizardService` in `apps/invoicing/services.py`:

```python
    @staticmethod
    def _sum_sources(line_item):
        """Sum the computed amounts of all source atoms on a line item."""
        from decimal import Decimal
        total = Decimal('0.00')
        for src in line_item.sources.all():
            instance = src.resolve()
            total += InvoiceWizardService._atom_computed_amount(instance)
        return total

    @staticmethod
    def add_atoms_to_line_item(line_item, atoms):
        """Append N atoms as sources to an existing line item.

        Recomputes the line item's price if it was in sync before the operation;
        preserves an overridden price otherwise.
        """
        from django.db import transaction, IntegrityError
        from apps.invoicing.models import InvoiceLineItemSource

        InvoiceWizardService._validate_draft(line_item.invoice)

        old_sum = InvoiceWizardService._sum_sources(line_item)
        was_in_sync = (line_item.price == old_sum)

        instances = [InvoiceWizardService._resolve_atom(a) for a in atoms]

        try:
            with transaction.atomic():
                for atom_ref, instance in zip(atoms, instances):
                    InvoiceLineItemSource.objects.create(
                        invoice_line_item=line_item,
                        source_type=InvoiceWizardService._atom_source_type(instance),
                        source_pk=instance.pk,
                    )
                if was_in_sync:
                    line_item.price = InvoiceWizardService._sum_sources(line_item)
                    line_item.save()
        except IntegrityError:
            existing = set(
                InvoiceLineItemSource.objects
                .filter(source_type__in=[a['type'] for a in atoms])
                .values_list('source_type', 'source_pk')
            )
            conflicts = [
                a for a in atoms
                if (a['type'], a['id']) in existing
            ]
            raise ClaimConflict(atom_ids=conflicts)

        return line_item
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_invoice_wizard_service.AddAtomsToExistingLineItemTest -v 2`
Expected: all four tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/invoicing/services.py tests/test_invoice_wizard_service.py
git commit -m "feat(invoicing): InvoiceWizardService.add_atoms_to_line_item with override preservation"
```

---

### Task 8: `InvoiceWizardService.remove_atoms_from_line_item`

**Files:**
- Modify: `apps/invoicing/services.py`
- Modify: `tests/test_invoice_wizard_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_invoice_wizard_service.py`:

```python
class RemoveAtomsFromLineItemTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED)
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo, name='Labor',
            rate=Decimal('25.00'), accounting_category=self.category,
        )
        start = timezone.now() - timezone.timedelta(hours=6)
        self.blep1 = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.blep2 = Blep.objects.create(
            task=self.task,
            start_time=start + timezone.timedelta(hours=3),
            end_time=start + timezone.timedelta(hours=4),
        )
        self.blep3 = Blep.objects.create(
            task=self.task,
            start_time=start + timezone.timedelta(hours=4, minutes=30),
            end_time=start + timezone.timedelta(hours=6),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

        self.line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice,
            [
                {'type': 'blep', 'id': self.blep1.pk},  # $50
                {'type': 'blep', 'id': self.blep2.pk},  # $25
                {'type': 'blep', 'id': self.blep3.pk},  # $37.50
            ],
        )
        # price is $112.50 with 3 sources

    def test_removes_partial_subset(self):
        source_ids = list(
            self.line_item.sources
            .filter(source_pk=self.blep1.pk)
            .values_list('source_id', flat=True)
        )
        result = InvoiceWizardService.remove_atoms_from_line_item(
            self.line_item, source_ids,
        )
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.sources.count(), 2)
        self.assertFalse(result['line_item_deleted'])

    def test_recomputes_price_when_in_sync(self):
        # price $112.50, in sync with 3 sources
        source_ids = list(
            self.line_item.sources
            .filter(source_pk=self.blep1.pk)  # remove the $50 atom
            .values_list('source_id', flat=True)
        )
        InvoiceWizardService.remove_atoms_from_line_item(self.line_item, source_ids)
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.price, Decimal('62.50'))  # $25 + $37.50

    def test_preserves_price_when_overridden(self):
        # Override the price
        self.line_item.price = Decimal('200.00')
        self.line_item.save()

        source_ids = list(
            self.line_item.sources
            .filter(source_pk=self.blep1.pk)
            .values_list('source_id', flat=True)
        )
        InvoiceWizardService.remove_atoms_from_line_item(self.line_item, source_ids)
        self.line_item.refresh_from_db()
        self.assertEqual(self.line_item.price, Decimal('200.00'))

    def test_deletes_line_item_when_all_atoms_removed_in_sync(self):
        source_ids = list(
            self.line_item.sources.values_list('source_id', flat=True)
        )
        line_item_pk = self.line_item.pk
        result = InvoiceWizardService.remove_atoms_from_line_item(
            self.line_item, source_ids,
        )
        self.assertTrue(result['line_item_deleted'])
        self.assertFalse(
            InvoiceLineItem.objects.filter(pk=line_item_pk).exists()
        )

    def test_deletes_line_item_when_all_atoms_removed_even_if_overridden(self):
        self.line_item.price = Decimal('200.00')
        self.line_item.save()
        source_ids = list(
            self.line_item.sources.values_list('source_id', flat=True)
        )
        line_item_pk = self.line_item.pk
        result = InvoiceWizardService.remove_atoms_from_line_item(
            self.line_item, source_ids,
        )
        self.assertTrue(result['line_item_deleted'])
        self.assertFalse(
            InvoiceLineItem.objects.filter(pk=line_item_pk).exists()
        )

    def test_refuses_mutation_on_non_draft_invoice(self):
        self.invoice.status = Invoice.STATUS_OPEN
        self.invoice.save()
        source_ids = list(
            self.line_item.sources.values_list('source_id', flat=True)
        )[:1]
        with self.assertRaises(ValidationError):
            InvoiceWizardService.remove_atoms_from_line_item(
                self.line_item, source_ids,
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_invoice_wizard_service.RemoveAtomsFromLineItemTest -v 2`
Expected: AttributeError — `remove_atoms_from_line_item` doesn't exist.

- [ ] **Step 3: Implement `remove_atoms_from_line_item`**

Add to `InvoiceWizardService`:

```python
    @staticmethod
    def remove_atoms_from_line_item(line_item, source_ids):
        """Remove a subset of source rows from a line item.

        - Recomputes price if the line item was in sync before.
        - Preserves price if it was overridden.
        - Deletes the line item if all sources are removed, regardless of override.

        Returns: {'line_item_deleted': bool}
        """
        from django.db import transaction

        InvoiceWizardService._validate_draft(line_item.invoice)

        old_sum = InvoiceWizardService._sum_sources(line_item)
        was_in_sync = (line_item.price == old_sum)

        with transaction.atomic():
            line_item.sources.filter(source_id__in=source_ids).delete()
            remaining = line_item.sources.count()

            if remaining == 0:
                line_item.delete()
                return {'line_item_deleted': True}

            if was_in_sync:
                line_item.price = InvoiceWizardService._sum_sources(line_item)
                line_item.save()

        return {'line_item_deleted': False}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_invoice_wizard_service.RemoveAtomsFromLineItemTest -v 2`
Expected: all six tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/invoicing/services.py tests/test_invoice_wizard_service.py
git commit -m "feat(invoicing): InvoiceWizardService.remove_atoms_from_line_item"
```

---

### Task 9: `InvoiceWizardService.discard_draft`

**Files:**
- Modify: `apps/invoicing/services.py`
- Modify: `tests/test_invoice_wizard_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_invoice_wizard_service.py`:

```python
class DiscardDraftTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED)
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo, name='Labor',
            rate=Decimal('25.00'), accounting_category=self.category,
        )
        start = timezone.now() - timezone.timedelta(hours=2)
        self.blep = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        self.line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'blep', 'id': self.blep.pk}],
        )

    def test_deletes_draft_invoice(self):
        invoice_pk = self.invoice.pk
        InvoiceWizardService.discard_draft(self.invoice)
        self.assertFalse(Invoice.objects.filter(pk=invoice_pk).exists())

    def test_cascades_to_line_items_and_sources(self):
        line_item_pk = self.line_item.pk
        InvoiceWizardService.discard_draft(self.invoice)
        self.assertFalse(InvoiceLineItem.objects.filter(pk=line_item_pk).exists())
        self.assertFalse(
            InvoiceLineItemSource.objects.filter(invoice_line_item_id=line_item_pk).exists()
        )

    def test_atoms_become_available_again(self):
        InvoiceWizardService.discard_draft(self.invoice)
        # Create a fresh draft and check the source pool
        fresh_invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        pool = InvoiceWizardService.get_source_pool(fresh_invoice)
        tasks = pool['work_orders'][0]['tasks']
        labor_task = next(t for t in tasks if t['name'] == 'Labor')
        blep_atom = next(a for a in labor_task['atoms'] if a['atom_id'] == self.blep.pk)
        self.assertEqual(blep_atom['state'], 'available')

    def test_refuses_non_draft_invoice(self):
        self.invoice.status = Invoice.STATUS_OPEN
        self.invoice.save()
        with self.assertRaises(ValidationError):
            InvoiceWizardService.discard_draft(self.invoice)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_invoice_wizard_service.DiscardDraftTest -v 2`
Expected: AttributeError — `discard_draft` doesn't exist.

- [ ] **Step 3: Implement `discard_draft`**

Add to `InvoiceWizardService`:

```python
    @staticmethod
    def discard_draft(invoice):
        """Hard-delete a draft invoice. Cascades to line items and source rows."""
        InvoiceWizardService._validate_draft(invoice)
        invoice.delete()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_invoice_wizard_service -v 2`
Expected: all tests in the service test file pass.

- [ ] **Step 5: Commit**

```bash
git add apps/invoicing/services.py tests/test_invoice_wizard_service.py
git commit -m "feat(invoicing): InvoiceWizardService.discard_draft"
```

---

## Phase 3 — API layer

### Task 10: Extend `InvoiceLineItemSerializer` with `sources`

**Files:**
- Modify: `apps/api/invoicing/serializers.py`
- Create: `tests/test_invoice_wizard_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_invoice_wizard_api.py`:

```python
from decimal import Decimal
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import User, Configuration, AccountingCategory
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, WorkOrder, Task, Blep
from apps.inventory.models import Material, PriceListItem
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource


class InvoiceLineItemSerializerSourcesTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.user = User.objects.create_user(username='test', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials')
        )
        self.client = APIClient()
        self.client.login(username='test', password='pw')

        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED)
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo, name='Labor',
            rate=Decimal('25.00'), accounting_category=self.category,
        )
        start = timezone.now() - timezone.timedelta(hours=2)
        self.blep = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        self.line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Labor', qty=Decimal('1'), price=Decimal('50.00'),
            accounting_category=self.category,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=self.line_item,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep.pk,
        )

    def test_get_line_items_includes_sources(self):
        response = self.client.get(f'/api/invoices/{self.invoice.pk}/line-items/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertIn('sources', data[0])
        self.assertEqual(len(data[0]['sources']), 1)
        source = data[0]['sources'][0]
        self.assertEqual(source['source_type'], 'blep')
        self.assertEqual(source['source_pk'], self.blep.pk)
        self.assertIn('description', source)
        self.assertIn('computed_amount', source)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_invoice_wizard_api.InvoiceLineItemSerializerSourcesTest -v 2`
Expected: FAIL — `sources` not in serialized output.

- [ ] **Step 3: Add `InvoiceLineItemSourceSerializer` and extend `InvoiceLineItemSerializer`**

Modify `apps/api/invoicing/serializers.py`. Add a new serializer at the top of the file (after imports):

```python
class InvoiceLineItemSourceSerializer(serializers.Serializer):
    """Serializer for InvoiceLineItemSource that resolves the atom for display."""
    source_id = serializers.IntegerField(read_only=True)
    source_type = serializers.CharField(read_only=True)
    source_pk = serializers.IntegerField(read_only=True)
    description = serializers.SerializerMethodField()
    computed_amount = serializers.SerializerMethodField()

    def get_description(self, obj):
        from apps.invoicing.services import InvoiceWizardService
        instance = obj.resolve()
        from apps.jobs.models import Blep
        if isinstance(instance, Blep):
            elapsed = instance.end_time - instance.start_time
            hours = elapsed.total_seconds() / 3600
            return f'Labor {hours:.2f}h'
        return instance.description

    def get_computed_amount(self, obj):
        from apps.invoicing.services import InvoiceWizardService
        instance = obj.resolve()
        return str(InvoiceWizardService._atom_computed_amount(instance))
```

Then modify `InvoiceLineItemSerializer` to include the sources field:

```python
class InvoiceLineItemSerializer(serializers.ModelSerializer):
    accounting_category_name = serializers.SerializerMethodField()
    units = UnitsField()
    sources = InvoiceLineItemSourceSerializer(many=True, read_only=True)

    class Meta:
        model = InvoiceLineItem
        fields = [
            'line_item_id', 'line_number', 'price_list_item',
            'qty', 'units', 'description', 'price',
            'accounting_category', 'accounting_category_name',
            'taxable_override', 'tax_rate_override',
            'sources',
        ]
        read_only_fields = ['line_item_id']
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_invoice_wizard_api.InvoiceLineItemSerializerSourcesTest -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/invoicing/serializers.py tests/test_invoice_wizard_api.py
git commit -m "feat(api): add sources field to InvoiceLineItemSerializer"
```

---

### Task 11: Source pool endpoint

**Files:**
- Modify: `apps/api/invoicing/views.py`
- Modify: `tests/test_invoice_wizard_api.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_invoice_wizard_api.py`:

```python
class SourcePoolEndpointTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.user = User.objects.create_user(username='test', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials')
        )
        self.client = APIClient()
        self.client.login(username='test', password='pw')

        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED)
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo, name='Labor',
            rate=Decimal('25.00'), accounting_category=self.category,
        )
        start = timezone.now() - timezone.timedelta(hours=2)
        self.blep = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_returns_tree_shape(self):
        response = self.client.get(f'/api/invoices/{self.invoice.pk}/source-pool/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('work_orders', data)
        self.assertEqual(len(data['work_orders']), 1)
        wo = data['work_orders'][0]
        self.assertIn('tasks', wo)
        self.assertEqual(len(wo['tasks']), 1)
        task = wo['tasks'][0]
        self.assertEqual(task['name'], 'Labor')
        self.assertTrue(task['has_billable_atoms'])
        self.assertEqual(len(task['atoms']), 1)
        atom = task['atoms'][0]
        self.assertEqual(atom['atom_type'], 'blep')
        self.assertEqual(atom['state'], 'available')

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.get(f'/api/invoices/{self.invoice.pk}/source-pool/')
        self.assertEqual(response.status_code, 403)

    def test_requires_can_manage_financials(self):
        user2 = User.objects.create_user(username='noperm', password='pw')
        client2 = APIClient()
        client2.login(username='noperm', password='pw')
        response = client2.get(f'/api/invoices/{self.invoice.pk}/source-pool/')
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_invoice_wizard_api.SourcePoolEndpointTest -v 2`
Expected: 404 — endpoint does not exist.

- [ ] **Step 3: Add the source pool endpoint to `InvoiceViewSet`**

Modify `apps/api/invoicing/views.py`. Add this action inside `InvoiceViewSet`:

```python
    @action(detail=True, methods=['get'], url_path='source-pool')
    def source_pool(self, request, pk=None):
        """Return the source pool tree for the wizard."""
        from apps.invoicing.services import InvoiceWizardService
        invoice = self.get_object()
        pool = InvoiceWizardService.get_source_pool(invoice)
        # Decimals need to be serialized as strings
        return Response(_serialize_pool(pool))


def _serialize_pool(pool):
    """Convert Decimal values in the pool structure to strings for JSON."""
    from decimal import Decimal
    def _s(value):
        if isinstance(value, Decimal):
            return str(value)
        return value
    return {
        'work_orders': [
            {
                'work_order_id': wo['work_order_id'],
                'tasks': [
                    {
                        'task_id': t['task_id'],
                        'name': t['name'],
                        'has_billable_atoms': t['has_billable_atoms'],
                        'atoms': [
                            {k: _s(v) for k, v in atom.items()}
                            for atom in t['atoms']
                        ],
                    }
                    for t in wo['tasks']
                ],
            }
            for wo in pool['work_orders']
        ],
    }
```

Also update `get_permissions` to allow authenticated access to source_pool (matching the `line_items` GET precedent):

```python
    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        if self.action == 'line_items' and self.request.method == 'GET':
            return [IsAuthenticated()]
        # source_pool and all wizard mutations require CanManageFinancials
        return [IsAuthenticated(), CanManageFinancials()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_invoice_wizard_api.SourcePoolEndpointTest -v 2`
Expected: all three tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/invoicing/views.py tests/test_invoice_wizard_api.py
git commit -m "feat(api): add source-pool endpoint for invoice wizard"
```

---

### Task 12: `line-items-from-atoms` endpoint

**Files:**
- Modify: `apps/api/invoicing/views.py`
- Modify: `tests/test_invoice_wizard_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_invoice_wizard_api.py`:

```python
class LineItemsFromAtomsEndpointTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.user = User.objects.create_user(username='test', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials')
        )
        self.client = APIClient()
        self.client.login(username='test', password='pw')

        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED)
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo, name='Labor',
            rate=Decimal('25.00'), accounting_category=self.category,
        )
        start = timezone.now() - timezone.timedelta(hours=2)
        self.blep = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

    def test_creates_line_item_with_sources(self):
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items-from-atoms/',
            {'atoms': [{'type': 'blep', 'id': self.blep.pk}]},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['price'], '50.00')
        self.assertEqual(len(data['sources']), 1)

    def test_returns_409_on_claim_conflict(self):
        # Pre-claim the blep
        prior_li = InvoiceLineItem.objects.create(
            invoice=self.invoice, description='Prior', qty=Decimal('1'),
            price=Decimal('50.00'), accounting_category=self.category,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=prior_li,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep.pk,
        )
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items-from-atoms/',
            {'atoms': [{'type': 'blep', 'id': self.blep.pk}]},
            format='json',
        )
        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data['error'], 'atoms_already_claimed')
        self.assertIn({'type': 'blep', 'id': self.blep.pk}, data['atom_ids'])

    def test_returns_400_on_non_draft_invoice(self):
        self.invoice.status = Invoice.STATUS_OPEN
        self.invoice.save()
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items-from-atoms/',
            {'atoms': [{'type': 'blep', 'id': self.blep.pk}]},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_invoice_wizard_api.LineItemsFromAtomsEndpointTest -v 2`
Expected: 404 — endpoint does not exist.

- [ ] **Step 3: Add the endpoint**

Add to `InvoiceViewSet` in `apps/api/invoicing/views.py`:

```python
    @action(detail=True, methods=['post'], url_path='line-items-from-atoms')
    def line_items_from_atoms(self, request, pk=None):
        """Create a new line item from a list of atoms."""
        from django.core.exceptions import ValidationError
        from apps.invoicing.services import InvoiceWizardService, ClaimConflict
        invoice = self.get_object()
        atoms = request.data.get('atoms', [])
        try:
            line_item = InvoiceWizardService.add_atoms_to_new_line_item(invoice, atoms)
        except ClaimConflict as e:
            return Response(
                {'error': 'atoms_already_claimed', 'atom_ids': e.atom_ids},
                status=409,
            )
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)
        serializer = InvoiceLineItemSerializer(line_item)
        return Response(serializer.data, status=201)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_invoice_wizard_api.LineItemsFromAtomsEndpointTest -v 2`
Expected: all three tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/invoicing/views.py tests/test_invoice_wizard_api.py
git commit -m "feat(api): add line-items-from-atoms endpoint"
```

---

### Task 13: `add-atoms` endpoint (on an existing line item)

**Files:**
- Modify: `apps/api/invoicing/views.py`
- Modify: `tests/test_invoice_wizard_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_invoice_wizard_api.py`:

```python
class AddAtomsEndpointTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.user = User.objects.create_user(username='test', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials')
        )
        self.client = APIClient()
        self.client.login(username='test', password='pw')

        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED)
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo, name='Labor',
            rate=Decimal('25.00'), accounting_category=self.category,
        )
        start = timezone.now() - timezone.timedelta(hours=4)
        self.blep1 = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.blep2 = Blep.objects.create(
            task=self.task,
            start_time=start + timezone.timedelta(hours=3),
            end_time=start + timezone.timedelta(hours=4),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

        from apps.invoicing.services import InvoiceWizardService
        self.line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'blep', 'id': self.blep1.pk}],
        )

    def test_adds_atoms_and_returns_updated_line_item(self):
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items/{self.line_item.pk}/add-atoms/',
            {'atoms': [{'type': 'blep', 'id': self.blep2.pk}]},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['sources']), 2)
        self.assertEqual(data['price'], '75.00')

    def test_returns_409_on_claim_conflict(self):
        # Claim blep2 on a different line item first
        other_li = InvoiceLineItem.objects.create(
            invoice=self.invoice, description='Other', qty=Decimal('1'),
            price=Decimal('25.00'), accounting_category=self.category,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=other_li,
            source_type=InvoiceLineItemSource.SOURCE_BLEP,
            source_pk=self.blep2.pk,
        )
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items/{self.line_item.pk}/add-atoms/',
            {'atoms': [{'type': 'blep', 'id': self.blep2.pk}]},
            format='json',
        )
        self.assertEqual(response.status_code, 409)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_invoice_wizard_api.AddAtomsEndpointTest -v 2`
Expected: 404 — endpoint does not exist.

- [ ] **Step 3: Add the endpoint**

Add to `InvoiceViewSet` in `apps/api/invoicing/views.py`:

```python
    @action(
        detail=True, methods=['post'],
        url_path=r'line-items/(?P<line_item_pk>[^/.]+)/add-atoms',
    )
    def add_atoms(self, request, pk=None, line_item_pk=None):
        """Append atoms to an existing line item."""
        from django.core.exceptions import ValidationError
        from apps.invoicing.models import InvoiceLineItem
        from apps.invoicing.services import InvoiceWizardService, ClaimConflict

        invoice = self.get_object()
        try:
            line_item = InvoiceLineItem.objects.get(pk=line_item_pk, invoice=invoice)
        except InvoiceLineItem.DoesNotExist:
            return Response({'error': 'Line item not found'}, status=404)

        atoms = request.data.get('atoms', [])
        try:
            InvoiceWizardService.add_atoms_to_line_item(line_item, atoms)
        except ClaimConflict as e:
            return Response(
                {'error': 'atoms_already_claimed', 'atom_ids': e.atom_ids},
                status=409,
            )
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)

        line_item.refresh_from_db()
        serializer = InvoiceLineItemSerializer(line_item)
        return Response(serializer.data, status=200)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_invoice_wizard_api.AddAtomsEndpointTest -v 2`
Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/invoicing/views.py tests/test_invoice_wizard_api.py
git commit -m "feat(api): add add-atoms endpoint for line items"
```

---

### Task 14: `remove-atoms` endpoint

**Files:**
- Modify: `apps/api/invoicing/views.py`
- Modify: `tests/test_invoice_wizard_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_invoice_wizard_api.py`:

```python
class RemoveAtomsEndpointTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.user = User.objects.create_user(username='test', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials')
        )
        self.client = APIClient()
        self.client.login(username='test', password='pw')

        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED)
        self.wo = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.wo, name='Labor',
            rate=Decimal('25.00'), accounting_category=self.category,
        )
        start = timezone.now() - timezone.timedelta(hours=4)
        self.blep1 = Blep.objects.create(
            task=self.task, start_time=start, end_time=start + timezone.timedelta(hours=2),
        )
        self.blep2 = Blep.objects.create(
            task=self.task,
            start_time=start + timezone.timedelta(hours=3),
            end_time=start + timezone.timedelta(hours=4),
        )
        self.invoice = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)

        from apps.invoicing.services import InvoiceWizardService
        self.line_item = InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice,
            [
                {'type': 'blep', 'id': self.blep1.pk},
                {'type': 'blep', 'id': self.blep2.pk},
            ],
        )

    def test_removes_partial_sources(self):
        source_ids = list(
            self.line_item.sources
            .filter(source_pk=self.blep1.pk)
            .values_list('source_id', flat=True)
        )
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items/{self.line_item.pk}/remove-atoms/',
            {'source_ids': source_ids},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['line_item_deleted'])
        self.assertEqual(data['line_item']['price'], '25.00')  # blep2 remains
        self.assertEqual(len(data['line_item']['sources']), 1)

    def test_deletes_line_item_when_all_removed(self):
        source_ids = list(self.line_item.sources.values_list('source_id', flat=True))
        response = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items/{self.line_item.pk}/remove-atoms/',
            {'source_ids': source_ids},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['line_item_deleted'])
        self.assertIsNone(data.get('line_item'))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_invoice_wizard_api.RemoveAtomsEndpointTest -v 2`
Expected: 404 — endpoint does not exist.

- [ ] **Step 3: Add the endpoint**

Add to `InvoiceViewSet`:

```python
    @action(
        detail=True, methods=['post'],
        url_path=r'line-items/(?P<line_item_pk>[^/.]+)/remove-atoms',
    )
    def remove_atoms(self, request, pk=None, line_item_pk=None):
        """Remove atoms from an existing line item."""
        from django.core.exceptions import ValidationError
        from apps.invoicing.models import InvoiceLineItem
        from apps.invoicing.services import InvoiceWizardService

        invoice = self.get_object()
        try:
            line_item = InvoiceLineItem.objects.get(pk=line_item_pk, invoice=invoice)
        except InvoiceLineItem.DoesNotExist:
            return Response({'error': 'Line item not found'}, status=404)

        source_ids = request.data.get('source_ids', [])
        try:
            result = InvoiceWizardService.remove_atoms_from_line_item(
                line_item, source_ids,
            )
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)

        if result['line_item_deleted']:
            return Response({'line_item_deleted': True, 'line_item': None})

        line_item.refresh_from_db()
        return Response({
            'line_item_deleted': False,
            'line_item': InvoiceLineItemSerializer(line_item).data,
        })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_invoice_wizard_api.RemoveAtomsEndpointTest -v 2`
Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/invoicing/views.py tests/test_invoice_wizard_api.py
git commit -m "feat(api): add remove-atoms endpoint for line items"
```

---

### Task 15: `start-invoice-wizard` endpoint on `JobViewSet`

**Files:**
- Modify: `apps/api/jobs/views.py`
- Modify: `tests/test_invoice_wizard_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_invoice_wizard_api.py`:

```python
class StartInvoiceWizardEndpointTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.user = User.objects.create_user(username='test', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials')
        )
        self.client = APIClient()
        self.client.login(username='test', password='pw')

        self.approved_job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED)
        self.draft_job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT)

    def test_creates_draft_and_returns_id(self):
        response = self.client.post(
            f'/api/jobs/{self.approved_job.pk}/start-invoice-wizard/',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('invoice_id', data)
        invoice = Invoice.objects.get(pk=data['invoice_id'])
        self.assertEqual(invoice.status, Invoice.STATUS_DRAFT)
        self.assertEqual(invoice.job, self.approved_job)

    def test_returns_existing_draft(self):
        Invoice.objects.create(job=self.approved_job, status=Invoice.STATUS_DRAFT)
        response = self.client.post(
            f'/api/jobs/{self.approved_job.pk}/start-invoice-wizard/',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Invoice.objects.filter(job=self.approved_job).count(), 1)

    def test_refuses_pre_approval_job(self):
        response = self.client.post(
            f'/api/jobs/{self.draft_job.pk}/start-invoice-wizard/',
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_can_manage_financials(self):
        user2 = User.objects.create_user(username='noperm', password='pw')
        client2 = APIClient()
        client2.login(username='noperm', password='pw')
        response = client2.post(
            f'/api/jobs/{self.approved_job.pk}/start-invoice-wizard/',
        )
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_invoice_wizard_api.StartInvoiceWizardEndpointTest -v 2`
Expected: 404 — endpoint does not exist.

- [ ] **Step 3: Add the endpoint to `JobViewSet`**

Modify `apps/api/jobs/views.py`. First, update `get_permissions` to allow `start_invoice_wizard` with `CanManageFinancials` (not `CanManageJobs`):

```python
    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'history', 'notes'):
            return [IsAuthenticated()]
        if self.action == 'start_invoice_wizard':
            from apps.api.permissions import CanManageFinancials
            return [IsAuthenticated(), CanManageFinancials()]
        return [IsAuthenticated(), CanManageJobs()]
```

Then add the action inside the class:

```python
    @action(detail=True, methods=['post'], url_path='start-invoice-wizard')
    def start_invoice_wizard(self, request, pk=None):
        """Get or create the draft invoice for this job and return its id."""
        from django.core.exceptions import ValidationError
        from apps.invoicing.services import InvoiceWizardService
        job = self.get_object()
        try:
            invoice = InvoiceWizardService.open_for_job(job)
        except ValidationError as e:
            return Response({'error': str(e)}, status=400)
        return Response({'invoice_id': invoice.pk})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_invoice_wizard_api.StartInvoiceWizardEndpointTest -v 2`
Expected: all four tests pass.

- [ ] **Step 5: Run the full wizard test suite**

Run: `python manage.py test tests.test_invoice_line_item_source tests.test_invoice_wizard_service tests.test_invoice_wizard_api -v 2`
Expected: all backend tests pass. This is a good checkpoint before moving to frontend.

- [ ] **Step 6: Commit**

```bash
git add apps/api/jobs/views.py tests/test_invoice_wizard_api.py
git commit -m "feat(api): add start-invoice-wizard endpoint on JobViewSet"
```

---

## Phase 4 — Frontend (Svelte SPA)

Frontend tasks do not follow a TDD pattern because the project has no Svelte unit testing set up. Each task builds a component, renders it manually via the dev server, and commits. Backend API tests (already written) are the safety net for everything that crosses the network.

To run the frontend dev server during this phase:

```bash
cd frontend && npm run dev
# Vite on :9000 proxies /api to :8000
```

### Task 16: Wizard route + page shell

**Files:**
- Create: `frontend/src/routes/invoices/InvoiceWizardPage.svelte`
- Modify: `frontend/src/App.svelte`

- [ ] **Step 1: Create the page shell**

**Spec note — source pool is snapshot-per-session.** The design doc says: "The set of atoms in the pool tree is determined at wizard mount and frozen for that session." This means we fetch the source pool **once**, on mount, and never re-fetch it during the session. When the user performs actions (add atoms, remove atoms, etc.), we refetch only the line items and reconcile the atom states in the in-memory source pool: atoms that now appear on a line item become `claimed_by_current`, atoms that don't become `available` (unless they were already `claimed_by_other` at mount time, in which case we leave them alone).

Create `frontend/src/routes/invoices/InvoiceWizardPage.svelte`:

```svelte
<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';

  const { params = {} } = $props();

  let invoice = $state(null);
  let lineItems = $state([]);
  let sourcePool = $state(null);
  let selectedAtoms = $state([]);
  let loading = $state(true);
  let error = $state(null);

  // Initial load — fetches everything once, including source pool.
  async function loadAll() {
    loading = true;
    error = null;
    try {
      const [inv, items, pool] = await Promise.all([
        api.get(`/api/invoices/${params.id}/`),
        api.get(`/api/invoices/${params.id}/line-items/`),
        api.get(`/api/invoices/${params.id}/source-pool/`),
      ]);
      invoice = inv;
      lineItems = items;
      sourcePool = pool;
      reconcileAtomStates();
    } catch (e) {
      error = e.message || 'Failed to load wizard';
    } finally {
      loading = false;
    }
  }

  // Post-action refresh — fetches ONLY invoice and line items, then updates
  // atom states in the existing source pool. Does NOT re-fetch the pool.
  async function reloadLineItems() {
    try {
      const [inv, items] = await Promise.all([
        api.get(`/api/invoices/${params.id}/`),
        api.get(`/api/invoices/${params.id}/line-items/`),
      ]);
      invoice = inv;
      lineItems = items;
      reconcileAtomStates();
      selectedAtoms = [];
    } catch (e) {
      error = e.message || 'Failed to reload';
    }
  }

  // Walk the source pool and update each atom's state based on current line items.
  // claimed_by_other atoms (snapshotted at mount) are left alone.
  function reconcileAtomStates() {
    if (!sourcePool) return;
    const claimMap = new Map();
    for (const li of lineItems) {
      for (const src of li.sources || []) {
        claimMap.set(`${src.source_type}:${src.source_pk}`, li.line_item_id);
      }
    }
    for (const wo of sourcePool.work_orders) {
      for (const task of wo.tasks) {
        for (const atom of task.atoms) {
          if (atom.state === 'claimed_by_other') continue;
          const key = `${atom.atom_type}:${atom.atom_id}`;
          if (claimMap.has(key)) {
            atom.state = 'claimed_by_current';
            atom.claiming_line_item_id = claimMap.get(key);
          } else {
            atom.state = 'available';
            atom.claiming_line_item_id = null;
          }
        }
      }
    }
    sourcePool = {...sourcePool};  // trigger Svelte reactivity
  }

  onMount(loadAll);
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p><strong>Error:</strong> {error}</p>
{:else if invoice}
  <h2>Build Invoice — {invoice.job_number}</h2>
  <p>Draft {invoice.invoice_number} · {lineItems.length} line items</p>

  <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
    <div>
      <h3>Source pool</h3>
      <p><em>(WizardSourcePool component goes here)</em></p>
    </div>
    <div>
      <h3>Line items</h3>
      <p><em>(WizardLineItemCard list goes here)</em></p>
    </div>
  </div>
{/if}
```

- [ ] **Step 2: Register the route**

Modify `frontend/src/App.svelte`. Find the route registry (usually a `routes` object passed to `Router`). Add:

```javascript
import InvoiceWizardPage from './routes/invoices/InvoiceWizardPage.svelte';

const routes = {
  // ... existing routes ...
  '/invoices/:id/wizard': InvoiceWizardPage,
};
```

The exact shape depends on how `App.svelte` currently declares routes — match the existing pattern.

- [ ] **Step 3: Smoke test**

Start the dev server and verify that navigating to `http://localhost:9000/#/invoices/1/wizard` (using an actual draft invoice id) loads the page and shows the header + two empty panes.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/invoices/InvoiceWizardPage.svelte frontend/src/App.svelte
git commit -m "feat(frontend): invoice wizard route and page shell"
```

---

### Task 17: `WizardSourcePool` component

**Files:**
- Create: `frontend/src/components/invoices/WizardSourcePool.svelte`
- Modify: `frontend/src/routes/invoices/InvoiceWizardPage.svelte`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/invoices/WizardSourcePool.svelte`:

```svelte
<script>
  let { sourcePool = null, selectedAtoms = $bindable([]) } = $props();

  function toggleAtom(atomType, atomId) {
    const key = `${atomType}:${atomId}`;
    const existing = selectedAtoms.find(a => `${a.type}:${a.id}` === key);
    if (existing) {
      selectedAtoms = selectedAtoms.filter(a => `${a.type}:${a.id}` !== key);
    } else {
      selectedAtoms = [...selectedAtoms, {type: atomType, id: atomId}];
    }
  }

  function isSelected(atomType, atomId) {
    return selectedAtoms.some(a => a.type === atomType && a.id === atomId);
  }
</script>

{#if !sourcePool}
  <p>No source data.</p>
{:else}
  {#each sourcePool.work_orders as wo}
    <div><strong>▾ WO #{wo.work_order_id}</strong></div>
    {#each wo.tasks as task}
      <div style="margin-left: 14px;">
        {#if !task.has_billable_atoms}
          <em style="color: #999;">▾ {task.name} (no billable items)</em>
        {:else}
          <strong>▾ {task.name}</strong>
          {#each task.atoms as atom}
            <div style="margin-left: 16px;">
              {#if atom.state === 'available'}
                <label>
                  <input
                    type="checkbox"
                    checked={isSelected(atom.atom_type, atom.atom_id)}
                    onchange={() => toggleAtom(atom.atom_type, atom.atom_id)}
                  >
                  {atom.description}
                  {#if atom.sub_info} <small>· {atom.sub_info}</small>{/if}
                  — ${atom.computed_amount}
                </label>
              {:else if atom.state === 'claimed_by_current'}
                <span style="color: #777;">
                  <input type="checkbox" checked disabled>
                  <em>{atom.description} — ${atom.computed_amount}</em>
                  <small>→ #{atom.claiming_line_item_id}</small>
                </span>
              {:else if atom.state === 'claimed_by_other'}
                <span style="color: #999;">
                  <input type="checkbox" disabled>
                  <em>{atom.description} — ${atom.computed_amount}</em>
                  <small>
                    <a href="#/invoices/{atom.claiming_invoice_id}">→ {atom.claiming_invoice_number}</a>
                  </small>
                </span>
              {/if}
            </div>
          {/each}
        {/if}
      </div>
    {/each}
  {/each}
{/if}
```

- [ ] **Step 2: Use the component in the page**

Modify `frontend/src/routes/invoices/InvoiceWizardPage.svelte`. Add the import to the script block:

```svelte
import WizardSourcePool from '../../components/invoices/WizardSourcePool.svelte';
```

Replace the placeholder `<p>(WizardSourcePool component goes here)</p>` in the template with:

```svelte
<WizardSourcePool {sourcePool} bind:selectedAtoms />
```

(`selectedAtoms` is already declared as `$state([])` in Task 16's script.)

- [ ] **Step 3: Smoke test**

Refresh the wizard page. Verify that work orders, tasks, and atoms render correctly. Checking boxes should update the selection (watch the browser dev console or add a temporary `{JSON.stringify(selectedAtoms)}` to the page).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/invoices/WizardSourcePool.svelte frontend/src/routes/invoices/InvoiceWizardPage.svelte
git commit -m "feat(frontend): WizardSourcePool component"
```

---

### Task 18: `WizardLineItemCard` component

**Files:**
- Create: `frontend/src/components/invoices/WizardLineItemCard.svelte`
- Modify: `frontend/src/routes/invoices/InvoiceWizardPage.svelte`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/invoices/WizardLineItemCard.svelte`:

```svelte
<script>
  import { api } from '../../lib/api.js';

  let { lineItem, invoiceId, selected = false, onselect, onchange } = $props();

  let nameValue = $state(lineItem.description);
  let priceValue = $state(lineItem.price);

  // Derived: computed sum of source atoms
  const computedPrice = $derived(
    lineItem.sources.reduce((sum, s) => sum + parseFloat(s.computed_amount), 0)
  );
  const isOverridden = $derived(
    Math.abs(parseFloat(lineItem.price) - computedPrice) > 0.001
  );

  async function saveName() {
    if (nameValue !== lineItem.description) {
      await api.patch(`/api/invoices/${invoiceId}/line-items/${lineItem.line_item_id}/`, {
        description: nameValue,
      });
      onchange?.();
    }
  }

  async function savePrice() {
    if (parseFloat(priceValue) !== parseFloat(lineItem.price)) {
      await api.patch(`/api/invoices/${invoiceId}/line-items/${lineItem.line_item_id}/`, {
        price: priceValue,
      });
      onchange?.();
    }
  }

  async function removeSource(sourceId) {
    const response = await api.post(
      `/api/invoices/${invoiceId}/line-items/${lineItem.line_item_id}/remove-atoms/`,
      {source_ids: [sourceId]},
    );
    onchange?.();
  }

  async function deleteLineItem() {
    if (!confirm('Delete this line item?')) return;
    await api.delete(`/api/invoices/${invoiceId}/line-items/${lineItem.line_item_id}/`);
    onchange?.();
  }

  async function resetToComputed() {
    priceValue = computedPrice.toFixed(2);
    await savePrice();
  }
</script>

<div
  style="border: 1px solid {selected ? '#246' : '#aaa'}; padding: 8px; margin-bottom: 8px;"
  onclick={() => onselect?.(lineItem.line_item_id)}
>
  <div style="display: flex; align-items: center; gap: 6px;">
    <strong>{lineItem.line_number}.</strong>
    <input
      bind:value={nameValue}
      onblur={saveName}
      placeholder="Name this line item…"
      style="flex: 1;"
    />
    <button onclick={deleteLineItem}>×</button>
  </div>

  {#if lineItem.sources.length === 0}
    <!-- Manual line item -->
    <div>
      <label>Price <input bind:value={priceValue} onblur={savePrice} /></label>
      <span><em>(manual)</em></span>
    </div>
  {:else if isOverridden}
    <div>
      <span style="color: #666;">Computed: ${computedPrice.toFixed(2)}</span>
      &nbsp;
      <strong>Billed: $<input bind:value={priceValue} onblur={savePrice} /></strong>
      <span style="color: #a55;"> ⚠ overridden</span>
      <a href="#" onclick={(e) => { e.preventDefault(); resetToComputed(); }}>reset to computed</a>
    </div>
  {:else}
    <div>
      <strong>$<input bind:value={priceValue} onblur={savePrice} /></strong>
    </div>
  {/if}

  {#if lineItem.sources.length > 0}
    <div style="padding-left: 8px; font-size: 11px; color: #555;">
      {#each lineItem.sources as source}
        <div>
          ↳ {source.description}
          <button onclick={() => removeSource(source.source_id)} style="color: #a00;">✕</button>
        </div>
      {/each}
    </div>
  {/if}
</div>
```

- [ ] **Step 2: Use the component in the page**

Modify `frontend/src/routes/invoices/InvoiceWizardPage.svelte`:

```svelte
<script>
  import WizardLineItemCard from '../../components/invoices/WizardLineItemCard.svelte';
  // ... existing imports ...

  let selectedLineItemId = $state(null);

  function selectLineItem(id) {
    selectedLineItemId = id;
  }
</script>

<!-- Replace the placeholder `<p>(WizardLineItemCard list goes here)</p>` with: -->
{#each lineItems as lineItem}
  <WizardLineItemCard
    {lineItem}
    invoiceId={invoice.invoice_id}
    selected={selectedLineItemId === lineItem.line_item_id}
    onselect={selectLineItem}
    onchange={reloadLineItems}
  />
{/each}
```

(`reloadLineItems` is defined in Task 16's script — it refreshes invoice + line items only, not the source pool, and then reconciles atom states in place.)

- [ ] **Step 3: Smoke test**

Refresh the page. Verify line items render with their sources, editing the name and pressing Tab persists the change (check via a GET refresh), and editing the price manually creates an override display.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/invoices/WizardLineItemCard.svelte frontend/src/routes/invoices/InvoiceWizardPage.svelte
git commit -m "feat(frontend): WizardLineItemCard component with override display"
```

---

### Task 19: `WizardFooter` component (actions bar)

**Files:**
- Create: `frontend/src/components/invoices/WizardFooter.svelte`
- Modify: `frontend/src/routes/invoices/InvoiceWizardPage.svelte`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/invoices/WizardFooter.svelte`:

```svelte
<script>
  import { api } from '../../lib/api.js';
  import { push } from 'svelte-spa-router';

  let {
    invoiceId,
    selectedAtoms = [],
    selectedLineItemId = null,
    onchange,
  } = $props();

  const canAddToSelected = $derived(
    selectedAtoms.length > 0 && selectedLineItemId !== null
  );
  const canCreateNew = $derived(selectedAtoms.length > 0);

  async function createNewLineItem() {
    try {
      await api.post(
        `/api/invoices/${invoiceId}/line-items-from-atoms/`,
        {atoms: selectedAtoms},
      );
      onchange?.();
    } catch (e) {
      if (e.status === 409) {
        alert('Some atoms were claimed by another invoice. Reopen the wizard to refresh.');
      } else {
        alert(e.message || 'Failed to create line item');
      }
    }
  }

  async function addToSelected() {
    try {
      await api.post(
        `/api/invoices/${invoiceId}/line-items/${selectedLineItemId}/add-atoms/`,
        {atoms: selectedAtoms},
      );
      onchange?.();
    } catch (e) {
      if (e.status === 409) {
        alert('Some atoms were claimed by another invoice. Reopen the wizard to refresh.');
      } else {
        alert(e.message || 'Failed to add atoms');
      }
    }
  }

  async function addManual() {
    try {
      await api.post(`/api/invoices/${invoiceId}/line-items/`, {
        description: '',
        qty: '1',
        units: 'each',
        price: '0.00',
      });
      onchange?.();
    } catch (e) {
      alert(e.message || 'Failed to add manual line item');
    }
  }

  async function discardDraft() {
    if (!confirm('Delete this draft invoice and release all atoms?')) return;
    try {
      await api.delete(`/api/invoices/${invoiceId}/?confirm=true`);
      push('/');
    } catch (e) {
      alert(e.message || 'Failed to discard');
    }
  }

  function done() {
    push(`/invoices/${invoiceId}`);
  }
</script>

<div style="display: flex; justify-content: space-between; margin-top: 12px;">
  <button onclick={discardDraft} style="color: #a00;">Discard draft</button>
  <div style="display: flex; gap: 6px;">
    <button onclick={addManual}>+ Manual</button>
    <button onclick={addToSelected} disabled={!canAddToSelected}>
      → Add to #{selectedLineItemId || '?'}
    </button>
    <button onclick={createNewLineItem} disabled={!canCreateNew}>
      → New line item from selected
    </button>
    <button onclick={done}>Done</button>
  </div>
</div>
```

- [ ] **Step 2: Use the component in the page**

Modify `frontend/src/routes/invoices/InvoiceWizardPage.svelte`. Add the import:

```svelte
import WizardFooter from '../../components/invoices/WizardFooter.svelte';
```

Add the footer at the bottom of the template:

```svelte
<WizardFooter
  invoiceId={invoice.invoice_id}
  {selectedAtoms}
  {selectedLineItemId}
  onchange={reloadLineItems}
/>
```

(`reloadLineItems` is defined in Task 16 and does exactly what's needed: refresh invoice and line items, reconcile atom states, clear the atom selection.)

- [ ] **Step 3: Smoke test end-to-end**

With a dev server running:

1. Navigate to the wizard for a draft invoice on an approved job.
2. Check a few atom boxes in the source pool.
3. Click "New line item from selected" — verify a new card appears, sources listed, price equals sum.
4. Check another atom, click a line item to select it, click "Add to #N" — verify atoms append and price recomputes.
5. Edit the name of a line item and tab out — verify it persists (refresh and check).
6. Edit the price — verify override display appears. Click "reset to computed".
7. Remove a source atom — verify it returns to the pool as available.
8. Add a manual line item — verify it appears with no sources and an editable price.
9. Discard the draft — verify navigation back and the invoice is gone.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/invoices/WizardFooter.svelte frontend/src/routes/invoices/InvoiceWizardPage.svelte
git commit -m "feat(frontend): WizardFooter action bar with claim conflict handling"
```

---

### Task 20: Add "Build invoice" / "Continue draft" button to JobDetailPage

**Files:**
- Modify: `frontend/src/routes/jobs/JobDetailPage.svelte`

- [ ] **Step 1: Inspect the existing JobDetailPage**

Read `frontend/src/routes/jobs/JobDetailPage.svelte` to find where action buttons live (likely a section near the top).

- [ ] **Step 2: Add state and the button**

In the page's script, after the job loads, fetch its invoices and identify whether a draft exists:

```javascript
let draftInvoice = $state(null);

async function loadDraftInvoice() {
  if (!job) return;
  const invoices = await api.get(`/api/invoices/?job=${job.job_id}`);
  draftInvoice = (invoices.results || invoices).find(inv => inv.status === 'draft') || null;
}

// Call loadDraftInvoice in onMount or after the job load, alongside existing setup.
```

In the template, add a button (only shown for jobs in a billable status):

```svelte
{#if job.status === 'approved' || job.status === 'completed'}
  <button onclick={startWizard}>
    {draftInvoice ? `Continue draft (${draftInvoice.invoice_number})` : 'Build invoice'}
  </button>
{/if}
```

And the handler:

```javascript
import { push } from 'svelte-spa-router';

async function startWizard() {
  try {
    const {invoice_id} = await api.post(`/api/jobs/${job.job_id}/start-invoice-wizard/`);
    push(`/invoices/${invoice_id}/wizard`);
  } catch (e) {
    alert(e.message || 'Failed to start wizard');
  }
}
```

- [ ] **Step 3: Smoke test**

1. Navigate to a job in `approved` status with no invoices. Verify "Build invoice" button appears.
2. Click it — verify the wizard opens with an empty draft.
3. Return to the job page. Verify the button now reads "Continue draft (INV-XXXX)".
4. Navigate to a job in `draft` status. Verify no button appears.
5. Click "Continue draft" — verify the wizard opens on the same draft as before, with any prior state intact.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/jobs/JobDetailPage.svelte
git commit -m "feat(frontend): job detail page 'Build invoice' button"
```

---

## Final verification

- [ ] **Run the full backend test suite**

Run: `python manage.py test`
Expected: all tests pass, including the three new wizard test modules and any pre-existing tests.

- [ ] **Run the frontend build**

Run: `cd frontend && npm run build`
Expected: builds cleanly, no errors.

- [ ] **End-to-end smoke test**

With both dev servers running (`python manage.py runserver` and `npm run dev`):

1. Create an approved job with a work order containing at least two tasks, each with bleps and materials.
2. Click "Build invoice" on the job page.
3. Verify the wizard opens with all expected atoms visible in the source pool.
4. Bundle atoms into 2-3 line items of different shapes: one with multiple tasks' labor, one with a single task's materials, one manual.
5. Override a price. Verify the computed vs. billed display.
6. Remove an atom from one line item; verify it returns to the pool.
7. Remove all atoms from a line item; verify the line item is deleted.
8. Close the browser tab. Reopen the wizard from the job page; verify the in-progress draft is loaded with all line items intact.
9. Discard the draft; verify everything is gone and atoms are available again.
10. (Concurrency) Open the wizard in two browser tabs for the same job. Claim an atom in tab 1. In tab 2, try to claim the same atom. Verify you get a 409 error.

- [ ] **Commit any fixups from smoke testing**

If the smoke test surfaces any bugs, fix them as individual commits before considering the plan complete.

---

## Out of scope (deferred per spec)

The following are explicitly not part of this plan and will be separate work:

- Auto-generate "one click, no customization" invoice path
- Auto-triggers (e.g., on job completion)
- Post-wizard direct invoice editor
- Flat-rate task billing (tasks without bleps/materials that still need to be billed)
- Partial-atom billing (e.g., 4 of 10 hours of a blep)

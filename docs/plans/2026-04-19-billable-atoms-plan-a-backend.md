# Billable Atoms — Plan A: Backend Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay the backend foundation for the wizard-driven estimate flow described in `docs/designs/2026-04-19-billable-atoms-and-estimate-wizard-design.md` — new `EstimateLineItemSource` model, uniform `compute_amount()` atom interface, `EstimateWizardService`, and the REST endpoints that drive it. Old plan-side machinery (`PlanBundle`, `mapping_strategy`, `EstimateGenerationService`) stays in place; this plan adds the new path alongside.

**Architecture:** Mirror the existing `InvoiceWizardService` / `InvoiceLineItemSource` design point-for-point on the estimate side. Atoms (TaskCharge, PlanCharge, Material, PlanMaterial) gain a uniform `compute_amount(active_modifiers=None) -> Decimal` interface. A new polymorphic `EstimateLineItemSource` table joins atoms to estimate line items with one-claim-per-atom enforced at the DB level (no release on supersede on the plan side, asymmetric with invoices and intentional). The wizard service handles open/source-pool/add/remove operations on the estimate; a separate "send all atoms" service method does bulk 1:1 conversion from a worksheet.

**Tech Stack:** Django 5.2, DRF, MySQL, Python 3.12. Tests use Django TestCase.

**Reference files (existing patterns to mirror):**
- `apps/invoicing/services.py` — `InvoiceWizardService`, `ClaimConflict`
- `apps/invoicing/models.py` lines 157-194 — `InvoiceLineItemSource`
- `apps/api/invoicing/views.py` lines 46-136 — wizard REST endpoints
- `tests/test_invoice_wizard_service.py`, `tests/test_invoice_wizard_api.py` — test patterns

---

## Phase 1 — Model changes

### Task 1: Add `EstimateLineItem.source_template` field

**Files:**
- Modify: `apps/estimates/models.py:560-580`
- Migration: `apps/estimates/migrations/XXXX_estimateLineItem_source_template.py` (auto-generated)
- Test: `tests/test_estimate_line_item_source_template.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_estimate_line_item_source_template.py`:

```python
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import Estimate, EstimateLineItem, TaskTemplate
from apps.jobs.models import Job


class EstimateLineItemSourceTemplateTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='j@example.com', mobile_number='555-0001',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.estimate = Estimate.objects.create(job=self.job, status=Estimate.STATUS_DRAFT)
        self.template = TaskTemplate.objects.create(
            template_name='Setup', units='hours', rate=Decimal('95.00'),
            accounting_category=self.category,
        )

    def test_source_template_can_be_null(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate,
            qty=Decimal('1'), units='each', price=Decimal('100.00'),
            description='manual', accounting_category=self.category,
        )
        self.assertIsNone(li.source_template)

    def test_source_template_fk_to_task_template(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate,
            qty=Decimal('1'), units='hours', price=Decimal('95.00'),
            description='setup', accounting_category=self.category,
            source_template=self.template,
        )
        li.refresh_from_db()
        self.assertEqual(li.source_template, self.template)

    def test_template_deletion_sets_null(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate,
            qty=Decimal('1'), units='hours', price=Decimal('95.00'),
            description='setup', accounting_category=self.category,
            source_template=self.template,
        )
        self.template.delete()
        li.refresh_from_db()
        self.assertIsNone(li.source_template)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_estimate_line_item_source_template -v 2`
Expected: FAIL with `TypeError: ... got unexpected keyword arguments: 'source_template'` or similar attribute error.

- [ ] **Step 3: Add the field to `EstimateLineItem`**

Modify `apps/estimates/models.py` — locate the `EstimateLineItem` class (around line 560) and add the field next to `material`:

```python
class EstimateLineItem(BaseLineItem):
    """Line item for estimates - inherits shared functionality from BaseLineItem."""

    estimate = models.ForeignKey(Estimate, on_delete=models.CASCADE)
    task = models.ForeignKey('jobs.PlanTask', on_delete=models.PROTECT, null=True, blank=True)
    material = models.ForeignKey(
        'inventory.PlanMaterial', on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    source_template = models.ForeignKey(
        'estimates.TaskTemplate',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text='TaskTemplate this line item was created from (preserves catalog ref for direct-estimate carry-over).',
    )

    class Meta:
        db_table = 'est_li'
        verbose_name = "Estimate Line Item"
        verbose_name_plural = "Estimate Line Items"

    def get_parent_field_name(self):
        return 'estimate'

    def __str__(self):
        return f"Estimate Line Item {self.pk} for {self.estimate.estimate_number}"
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations estimates -n estimateLineItem_source_template`
Expected: A migration file is created adding the `source_template` column to `est_li`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_estimate_line_item_source_template -v 2`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/estimates/models.py apps/estimates/migrations/ tests/test_estimate_line_item_source_template.py
git commit -m "feat(estimates): add EstimateLineItem.source_template FK"
```

---

### Task 2: Add `EstimateLineItemSource` model

**Files:**
- Modify: `apps/estimates/models.py` (append `EstimateLineItemSource` after `EstimateLineItem`)
- Migration: `apps/estimates/migrations/XXXX_estimateLineItemSource.py` (auto-generated)
- Test: `tests/test_estimate_line_item_source.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_estimate_line_item_source.py`:

```python
from decimal import Decimal
from django.db import IntegrityError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource, EstWorksheet
from apps.inventory.models import PlanMaterial
from apps.jobs.models import Job, PlanTask, PlanCharge, RateScheme


class EstimateLineItemSourceTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='j@example.com', mobile_number='555-0001',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.estimate = Estimate.objects.create(job=self.job, status=Estimate.STATUS_DRAFT)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME, rate=Decimal('95'),
            unit_label='hour', accounting_category=self.cat,
        )
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Setup', units='hours',
            est_qty=Decimal('1'), accounting_category=self.cat,
        )
        self.plan_charge = PlanCharge.objects.create(
            plan_task=self.plan_task, rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('1'),
        )
        self.plan_material = PlanMaterial.objects.create(
            est_worksheet=self.worksheet, description='steel', quantity=Decimal('2'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )
        self.line_item = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('95'), description='', accounting_category=self.cat,
        )

    def test_create_source_for_plan_charge(self):
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_PLAN_CHARGE,
            source_pk=self.plan_charge.pk,
        )
        self.assertEqual(src.estimate_line_item, self.line_item)

    def test_create_source_for_plan_material(self):
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_PLAN_MATERIAL,
            source_pk=self.plan_material.pk,
        )
        self.assertEqual(src.source_pk, self.plan_material.pk)

    def test_unique_constraint_blocks_double_claim(self):
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_PLAN_CHARGE,
            source_pk=self.plan_charge.pk,
        )
        other_li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('1'), description='', accounting_category=self.cat,
        )
        with self.assertRaises(IntegrityError):
            EstimateLineItemSource.objects.create(
                estimate_line_item=other_li,
                source_type=EstimateLineItemSource.SOURCE_PLAN_CHARGE,
                source_pk=self.plan_charge.pk,
            )

    def test_resolve_returns_plan_charge(self):
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_PLAN_CHARGE,
            source_pk=self.plan_charge.pk,
        )
        self.assertEqual(src.resolve(), self.plan_charge)

    def test_resolve_returns_plan_material(self):
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_PLAN_MATERIAL,
            source_pk=self.plan_material.pk,
        )
        self.assertEqual(src.resolve(), self.plan_material)

    def test_cascade_on_line_item_delete(self):
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_PLAN_CHARGE,
            source_pk=self.plan_charge.pk,
        )
        li_pk = self.line_item.pk
        self.line_item.delete()
        self.assertFalse(EstimateLineItemSource.objects.filter(estimate_line_item_id=li_pk).exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_estimate_line_item_source -v 2`
Expected: FAIL with `ImportError: cannot import name 'EstimateLineItemSource' from 'apps.estimates.models'`.

- [ ] **Step 3: Add the model**

Append to `apps/estimates/models.py` (after `EstimateLineItem`):

```python
class EstimateLineItemSource(models.Model):
    """Polymorphic join between an EstimateLineItem and its source atom (PlanCharge or PlanMaterial).

    The unique_together on (source_type, source_pk) enforces whole-atom claim at the
    database level: an atom can be referenced by at most one estimate line item.

    Note: unlike InvoiceLineItemSource, this constraint is NOT scoped by Estimate status
    on the plan side. Worksheet revisions copy atoms (creating new instances), so the
    constraint never needs to fire across revisions in practice.
    """
    SOURCE_PLAN_CHARGE = 'plan_charge'
    SOURCE_PLAN_MATERIAL = 'plan_material'
    SOURCE_TYPE_CHOICES = [
        (SOURCE_PLAN_CHARGE, 'PlanCharge'),
        (SOURCE_PLAN_MATERIAL, 'PlanMaterial'),
    ]

    source_id = models.AutoField(primary_key=True)
    estimate_line_item = models.ForeignKey(
        EstimateLineItem,
        on_delete=models.CASCADE,
        related_name='sources',
    )
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPE_CHOICES)
    source_pk = models.PositiveIntegerField()

    class Meta:
        db_table = 'estimate_line_item_sources'
        unique_together = [('source_type', 'source_pk')]

    def resolve(self):
        """Return the concrete atom instance (PlanCharge or PlanMaterial) referenced by this source."""
        if self.source_type == self.SOURCE_PLAN_CHARGE:
            from apps.jobs.models import PlanCharge
            return PlanCharge.objects.get(pk=self.source_pk)
        if self.source_type == self.SOURCE_PLAN_MATERIAL:
            from apps.inventory.models import PlanMaterial
            return PlanMaterial.objects.get(pk=self.source_pk)
        raise ValueError(f'Unknown source_type: {self.source_type}')

    def __str__(self):
        return f'Source {self.source_id}: {self.source_type}:{self.source_pk} → EstLineItem {self.estimate_line_item_id}'
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations estimates -n estimateLineItemSource`
Expected: A migration file is created adding the `estimate_line_item_sources` table.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_estimate_line_item_source -v 2`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/estimates/models.py apps/estimates/migrations/ tests/test_estimate_line_item_source.py
git commit -m "feat(estimates): add EstimateLineItemSource polymorphic claim model"
```

---

## Phase 2 — Uniform `compute_amount()` interface on atoms

### Task 3: Add `compute_amount()` to `MaterialBase`

**Files:**
- Modify: `apps/inventory/models.py` — `MaterialBase` (around line 95)
- Test: `tests/test_atom_compute_amount.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_atom_compute_amount.py`:

```python
from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import EstWorksheet
from apps.inventory.models import Material, PlanMaterial
from apps.jobs.models import Job


class MaterialComputeAmountTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Materials', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)

    def test_material_compute_amount(self):
        m = Material.objects.create(
            job=self.job, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('10.50'), accounting_category=self.cat,
        )
        self.assertEqual(m.compute_amount(), Decimal('31.50'))

    def test_plan_material_compute_amount(self):
        pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('2'),
            sell_price=Decimal('5.00'), accounting_category=self.cat,
        )
        self.assertEqual(pm.compute_amount(), Decimal('10.00'))

    def test_compute_amount_ignores_active_modifiers(self):
        m = Material.objects.create(
            job=self.job, description='steel', quantity=Decimal('1'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )
        # Materials don't have modifiers; the parameter is accepted for uniform interface.
        self.assertEqual(m.compute_amount(active_modifiers=['rush']), Decimal('5'))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_atom_compute_amount -v 2`
Expected: FAIL — `AttributeError: 'Material' object has no attribute 'compute_amount'`.

- [ ] **Step 3: Add `compute_amount` to `MaterialBase`**

Modify `apps/inventory/models.py` — find `MaterialBase` and add the method after `total_sell`:

```python
class MaterialBase(models.Model):
    """Abstract base for PlanMaterial (planning) and Material (actual)."""
    # ... existing fields ...

    @property
    def total_sell(self):
        return self.quantity * self.sell_price

    def compute_amount(self, active_modifiers=None):
        """Uniform atom interface: total billable amount for this material.

        Materials have no modifier concept; the parameter is accepted to match
        the BillableAtom interface shared with TaskCharge/PlanCharge.
        """
        return self.quantity * self.sell_price
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_atom_compute_amount -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/models.py tests/test_atom_compute_amount.py
git commit -m "feat(atoms): add compute_amount() to MaterialBase"
```

---

### Task 4: Add `compute_amount()` to `TaskCharge` and `PlanCharge`

**Files:**
- Modify: `apps/jobs/models.py` — `TaskCharge` (around line 397) and `PlanCharge` (around line 425)
- Test: extend `tests/test_atom_compute_amount.py`

- [ ] **Step 1: Write the failing test (extend existing file)**

Append to `tests/test_atom_compute_amount.py`:

```python
from apps.jobs.models import (
    Blep, PlanCharge, PlanTask, RateScheme, Task, TaskCharge,
)
from django.utils import timezone
from datetime import timedelta


class TaskChargeComputeAmountTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001')
        self.scheme_time = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.scheme_qty = RateScheme.objects.create(
            name='PerItem', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50'), unit_label='item', accounting_category=self.cat,
        )
        self.scheme_flat = RateScheme.objects.create(
            name='FlatFee', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('250'), unit_label='each', accounting_category=self.cat,
        )

    def test_task_charge_elapsed_time(self):
        task = Task.objects.create(job=self.job, name='t', units='hours')
        TaskCharge.objects.create(task=task, rate_scheme=self.scheme_time)
        now = timezone.now()
        Blep.objects.create(task=task, start_time=now - timedelta(hours=2), end_time=now)
        # 2 hours × $100 = $200
        self.assertEqual(task.charge.compute_amount(), Decimal('200.00'))

    def test_task_charge_entered_qty(self):
        task = Task.objects.create(job=self.job, name='t', units='item')
        TaskCharge.objects.create(
            task=task, rate_scheme=self.scheme_qty, actuals={'qty': '3'},
        )
        # 3 × $50 = $150
        self.assertEqual(task.charge.compute_amount(), Decimal('150.00'))

    def test_task_charge_flat_fee(self):
        task = Task.objects.create(job=self.job, name='t', units='each')
        TaskCharge.objects.create(task=task, rate_scheme=self.scheme_flat)
        self.assertEqual(task.charge.compute_amount(), Decimal('250.00'))


class PlanChargeComputeAmountTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )

    def test_plan_charge_uses_estimated_qty(self):
        pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='setup', units='hours',
            est_qty=Decimal('2'), accounting_category=self.cat,
        )
        PlanCharge.objects.create(
            plan_task=pt, rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('2'),
        )
        # 2 hours × $100 = $200
        self.assertEqual(pt.charge.compute_amount(), Decimal('200.00'))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_atom_compute_amount -v 2`
Expected: FAIL on the four new tests with `AttributeError: ... no attribute 'compute_amount'`.

- [ ] **Step 3: Add `compute_amount()` to both charge models**

Modify `apps/jobs/models.py` — in `TaskCharge` (around line 397):

```python
class TaskCharge(models.Model):
    """The filled-in billing form for a Task. One per Task (OneToOne)."""
    # ... existing fields ...

    def compute(self):
        """Compute charge using scheme's algorithm and this charge's specifics."""
        qty = self.rate_scheme.get_actual_qty(self.task)
        return self.rate_scheme.compute_charge(qty, self.active_modifiers)

    def compute_amount(self, active_modifiers=None):
        """Uniform atom interface: total billable amount for this charge.

        Ignores the active_modifiers argument (uses self.active_modifiers).
        Parameter is accepted to match the BillableAtom interface shared with
        Material/PlanMaterial.
        """
        return self.compute()

    def effective_rate(self):
        return self.rate_scheme.effective_rate(self.active_modifiers)

    def has_actuals(self):
        if self.rate_scheme.algorithm == RateScheme.ENTERED_QTY:
            return bool(self.actuals.get('qty'))
        return True
```

And in `PlanCharge` (around line 425):

```python
class PlanCharge(models.Model):
    """Same shape as TaskCharge but for PlanTask. No actuals."""
    # ... existing fields ...

    def compute(self):
        return self.rate_scheme.compute_charge(self.estimated_billable_qty, self.active_modifiers)

    def compute_amount(self, active_modifiers=None):
        """Uniform atom interface: total billable amount for this charge.

        Ignores the active_modifiers argument (uses self.active_modifiers).
        Parameter is accepted to match the BillableAtom interface.
        """
        return self.compute()

    def effective_rate(self):
        return self.rate_scheme.effective_rate(self.active_modifiers)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_atom_compute_amount -v 2`
Expected: PASS (7 tests total — 3 from Task 3 + 4 from this task).

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/models.py tests/test_atom_compute_amount.py
git commit -m "feat(atoms): add compute_amount() to TaskCharge and PlanCharge"
```

---

## Phase 3 — `EstimateWizardService`

This phase mirrors `apps/invoicing/services.py:169-541` (`InvoiceWizardService`). Each task implements one operation.

### Task 5: Scaffold `EstimateWizardService` and `EstimateClaimConflict` exception

**Files:**
- Modify: `apps/estimates/services.py` — append new class at end of file
- Test: `tests/test_estimate_wizard_service.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_estimate_wizard_service.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import Estimate, EstWorksheet
from apps.estimates.services import EstimateWizardService, EstimateClaimConflict
from apps.jobs.models import Job


class OpenForWorksheetTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)

    def test_creates_draft_estimate_when_none_exists(self):
        est = EstimateWizardService.open_for_worksheet(self.ws)
        self.assertEqual(est.status, Estimate.STATUS_DRAFT)
        self.assertEqual(est.job, self.job)
        self.ws.refresh_from_db()
        self.assertEqual(self.ws.estimate, est)

    def test_returns_existing_draft(self):
        first = EstimateWizardService.open_for_worksheet(self.ws)
        second = EstimateWizardService.open_for_worksheet(self.ws)
        self.assertEqual(first.pk, second.pk)

    def test_refuses_finalized_worksheet(self):
        self.ws.status = EstWorksheet.STATUS_FINAL
        self.ws.save()
        with self.assertRaises(ValidationError):
            EstimateWizardService.open_for_worksheet(self.ws)


class ClaimConflictExceptionTest(TestCase):
    def test_exception_carries_atom_ids(self):
        exc = EstimateClaimConflict(atom_ids=[{'type': 'plan_charge', 'id': 1}])
        self.assertEqual(exc.atom_ids, [{'type': 'plan_charge', 'id': 1}])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_estimate_wizard_service -v 2`
Expected: FAIL — `ImportError: cannot import name 'EstimateWizardService'`.

- [ ] **Step 3: Add the exception and service skeleton**

Append to `apps/estimates/services.py`:

```python
class EstimateClaimConflict(Exception):
    """Raised when the estimate wizard tries to claim an atom already claimed elsewhere."""

    def __init__(self, atom_ids):
        self.atom_ids = atom_ids
        super().__init__(f'Atoms already claimed: {atom_ids}')


class EstimateWizardService:
    """Orchestration layer for the estimate wizard.

    Mirrors InvoiceWizardService shape. Composes on top of EstimateService rather
    than replacing it; manual line-item CRUD continues to use EstimateService.
    """

    @staticmethod
    def _validate_draft_worksheet(worksheet):
        from apps.estimates.models import EstWorksheet
        if worksheet.status != EstWorksheet.STATUS_DRAFT:
            raise ValidationError(
                f'Cannot run wizard on worksheet in status "{worksheet.status}". '
                f'Worksheet must be in draft.'
            )

    @staticmethod
    def _validate_draft_estimate(estimate):
        from apps.estimates.models import Estimate
        if estimate.status != Estimate.STATUS_DRAFT:
            raise ValidationError(
                f'Cannot modify line items on estimate in status "{estimate.status}".'
            )

    @staticmethod
    def open_for_worksheet(worksheet):
        """Return the worksheet's draft Estimate, creating one if none exists.

        Raises ValidationError if the worksheet is not in draft.
        """
        from apps.estimates.models import Estimate
        EstimateWizardService._validate_draft_worksheet(worksheet)

        if worksheet.estimate and worksheet.estimate.status == Estimate.STATUS_DRAFT:
            return worksheet.estimate

        estimate = Estimate.objects.create(job=worksheet.job, status=Estimate.STATUS_DRAFT)
        worksheet.estimate = estimate
        worksheet.save()
        return estimate
```

Add `from django.core.exceptions import ValidationError` at the top of `apps/estimates/services.py` if not already present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_estimate_wizard_service -v 2`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/services.py tests/test_estimate_wizard_service.py
git commit -m "feat(estimates): scaffold EstimateWizardService with open_for_worksheet"
```

---

### Task 6: Add `get_source_pool()` and atom helper methods

**Files:**
- Modify: `apps/estimates/services.py` — extend `EstimateWizardService`
- Test: extend `tests/test_estimate_wizard_service.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_estimate_wizard_service.py`:

```python
from apps.estimates.models import EstimateLineItem, EstimateLineItemSource
from apps.inventory.models import PlanMaterial
from apps.jobs.models import PlanCharge, PlanTask, RateScheme


class GetSourcePoolTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )

        # PlanCharge atom
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Setup', units='hours',
            est_qty=Decimal('2'), accounting_category=self.cat,
        )
        self.pc = PlanCharge.objects.create(
            plan_task=self.pt, rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('2'),
        )

        # PlanMaterial atom (task-less)
        self.pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )

        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)

    def test_pool_has_charge_and_material_atoms(self):
        pool = EstimateWizardService.get_source_pool(self.ws)
        atom_ids = [(a['type'], a['id']) for a in pool['atoms']]
        self.assertIn(('plan_charge', self.pc.pk), atom_ids)
        self.assertIn(('plan_material', self.pm.pk), atom_ids)

    def test_atom_amount_uses_compute_amount(self):
        pool = EstimateWizardService.get_source_pool(self.ws)
        amounts = {(a['type'], a['id']): a['amount'] for a in pool['atoms']}
        self.assertEqual(amounts[('plan_charge', self.pc.pk)], Decimal('200.00'))
        self.assertEqual(amounts[('plan_material', self.pm.pk)], Decimal('15.00'))

    def test_unclaimed_atom_state(self):
        pool = EstimateWizardService.get_source_pool(self.ws)
        for a in pool['atoms']:
            self.assertEqual(a['state'], 'available')

    def test_claimed_atom_state(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('200'), description='', accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_PLAN_CHARGE,
            source_pk=self.pc.pk,
        )
        pool = EstimateWizardService.get_source_pool(self.ws)
        states = {(a['type'], a['id']): a['state'] for a in pool['atoms']}
        self.assertEqual(states[('plan_charge', self.pc.pk)], 'claimed_by_current')
        self.assertEqual(states[('plan_material', self.pm.pk)], 'available')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_estimate_wizard_service.GetSourcePoolTest -v 2`
Expected: FAIL — `AttributeError: ... no attribute 'get_source_pool'`.

- [ ] **Step 3: Implement `get_source_pool` and helpers**

Append to `EstimateWizardService` in `apps/estimates/services.py`:

```python
    @staticmethod
    def _resolve_atom(atom_ref):
        """Convert {'type': 'plan_charge'|'plan_material', 'id': N} to a model instance."""
        from apps.jobs.models import PlanCharge
        from apps.inventory.models import PlanMaterial
        atom_type = atom_ref.get('type')
        atom_id = atom_ref.get('id')
        if atom_type == 'plan_charge':
            try:
                return PlanCharge.objects.get(pk=atom_id)
            except PlanCharge.DoesNotExist:
                raise ValidationError(f'PlanCharge {atom_id} not found')
        if atom_type == 'plan_material':
            try:
                return PlanMaterial.objects.get(pk=atom_id)
            except PlanMaterial.DoesNotExist:
                raise ValidationError(f'PlanMaterial {atom_id} not found')
        raise ValidationError(f'Unknown atom type: {atom_type}')

    @staticmethod
    def _atom_source_type(atom_instance):
        from apps.jobs.models import PlanCharge
        from apps.inventory.models import PlanMaterial
        from apps.estimates.models import EstimateLineItemSource
        if isinstance(atom_instance, PlanCharge):
            return EstimateLineItemSource.SOURCE_PLAN_CHARGE
        if isinstance(atom_instance, PlanMaterial):
            return EstimateLineItemSource.SOURCE_PLAN_MATERIAL
        raise ValueError(f'Unknown atom instance type: {type(atom_instance)}')

    @staticmethod
    def _atom_category(atom_instance):
        from apps.jobs.models import PlanCharge
        from apps.inventory.models import PlanMaterial
        if isinstance(atom_instance, PlanCharge):
            return atom_instance.plan_task.accounting_category
        if isinstance(atom_instance, PlanMaterial):
            return atom_instance.accounting_category
        return None

    @staticmethod
    def _atom_description(atom_instance):
        from apps.jobs.models import PlanCharge
        from apps.inventory.models import PlanMaterial
        if isinstance(atom_instance, PlanCharge):
            return atom_instance.plan_task.name
        if isinstance(atom_instance, PlanMaterial):
            return atom_instance.description
        return ''

    @staticmethod
    def _atom_units(atom_instance):
        from apps.jobs.models import PlanCharge
        from apps.inventory.models import PlanMaterial
        if isinstance(atom_instance, PlanCharge):
            return atom_instance.plan_task.units
        if isinstance(atom_instance, PlanMaterial):
            return 'each'
        return 'each'

    @staticmethod
    def get_source_pool(worksheet):
        """Walk the worksheet's atoms and return a flat pool with claim state.

        Returns: {'atoms': [
            {'type': 'plan_charge'|'plan_material', 'id': N, 'description': str,
             'amount': Decimal, 'state': 'available'|'claimed_by_current'|'claimed_by_other',
             'category_id': N or None, 'units': str}
        ]}
        """
        from apps.estimates.models import EstimateLineItemSource, Estimate
        from apps.jobs.models import PlanCharge
        from apps.inventory.models import PlanMaterial

        # Build the claim lookup: (source_type, source_pk) -> state info
        # Plan-side does NOT release on supersede, so we don't filter by status.
        claimed_sources = (
            EstimateLineItemSource.objects
            .filter(estimate_line_item__estimate__job=worksheet.job)
            .select_related('estimate_line_item', 'estimate_line_item__estimate')
        )
        current_estimate_pk = worksheet.estimate_id
        claims = {}
        for src in claimed_sources:
            li = src.estimate_line_item
            est = li.estimate
            key = (src.source_type, src.source_pk)
            if est.pk == current_estimate_pk:
                claims[key] = {
                    'state': 'claimed_by_current',
                    'claiming_line_item_id': li.pk,
                    'claiming_estimate_id': None,
                    'claiming_estimate_number': None,
                }
            else:
                claims[key] = {
                    'state': 'claimed_by_other',
                    'claiming_line_item_id': None,
                    'claiming_estimate_id': est.pk,
                    'claiming_estimate_number': est.estimate_number,
                }

        default_state = {
            'state': 'available',
            'claiming_line_item_id': None,
            'claiming_estimate_id': None,
            'claiming_estimate_number': None,
        }

        atoms = []

        for pc in PlanCharge.objects.filter(plan_task__est_worksheet=worksheet).select_related('plan_task', 'plan_task__accounting_category', 'rate_scheme'):
            key = (EstimateLineItemSource.SOURCE_PLAN_CHARGE, pc.pk)
            state_info = claims.get(key, default_state)
            atoms.append({
                'type': 'plan_charge',
                'id': pc.pk,
                'description': pc.plan_task.name,
                'amount': pc.compute_amount(),
                'units': pc.plan_task.units,
                'category_id': pc.plan_task.accounting_category_id,
                **state_info,
            })

        for pm in PlanMaterial.objects.filter(est_worksheet=worksheet).select_related('accounting_category'):
            key = (EstimateLineItemSource.SOURCE_PLAN_MATERIAL, pm.pk)
            state_info = claims.get(key, default_state)
            atoms.append({
                'type': 'plan_material',
                'id': pm.pk,
                'description': pm.description,
                'amount': pm.compute_amount(),
                'units': 'each',
                'category_id': pm.accounting_category_id,
                **state_info,
            })

        return {'atoms': atoms}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_estimate_wizard_service.GetSourcePoolTest -v 2`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/services.py tests/test_estimate_wizard_service.py
git commit -m "feat(estimates): add EstimateWizardService.get_source_pool"
```

---

### Task 7: Add `add_atoms_to_new_line_item()`

**Files:**
- Modify: `apps/estimates/services.py` — extend `EstimateWizardService`
- Test: extend `tests/test_estimate_wizard_service.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_estimate_wizard_service.py`:

```python
class AddAtomsToNewLineItemTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.cat2 = AccountingCategory.objects.create(name='Materials', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Setup', units='hours',
            est_qty=Decimal('2'), accounting_category=self.cat,
        )
        self.pc = PlanCharge.objects.create(
            plan_task=self.pt, rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('2'),
        )
        self.pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('5'), accounting_category=self.cat2,
        )
        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)

    def test_creates_line_item_with_summed_price(self):
        atoms = [
            {'type': 'plan_charge', 'id': self.pc.pk},
            {'type': 'plan_material', 'id': self.pm.pk},
        ]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        # 200 + 15 = 215
        self.assertEqual(li.price, Decimal('215.00'))

    def test_creates_source_rows(self):
        atoms = [{'type': 'plan_charge', 'id': self.pc.pk}]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.sources.count(), 1)
        self.assertEqual(li.sources.first().source_pk, self.pc.pk)

    def test_uniform_category_kept(self):
        # Both atoms in same category
        pm_same_cat = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='m', quantity=Decimal('1'),
            sell_price=Decimal('1'), accounting_category=self.cat,
        )
        atoms = [
            {'type': 'plan_charge', 'id': self.pc.pk},
            {'type': 'plan_material', 'id': pm_same_cat.pk},
        ]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertEqual(li.accounting_category, self.cat)

    def test_mixed_category_left_null(self):
        atoms = [
            {'type': 'plan_charge', 'id': self.pc.pk},
            {'type': 'plan_material', 'id': self.pm.pk},
        ]
        li = EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        self.assertIsNone(li.accounting_category)

    def test_double_claim_raises(self):
        atoms = [{'type': 'plan_charge', 'id': self.pc.pk}]
        EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
        with self.assertRaises(EstimateClaimConflict):
            EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)

    def test_refuses_non_draft_estimate(self):
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        atoms = [{'type': 'plan_charge', 'id': self.pc.pk}]
        with self.assertRaises(ValidationError):
            EstimateWizardService.add_atoms_to_new_line_item(self.estimate, atoms)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_estimate_wizard_service.AddAtomsToNewLineItemTest -v 2`
Expected: FAIL — `AttributeError: ... no attribute 'add_atoms_to_new_line_item'`.

- [ ] **Step 3: Implement `add_atoms_to_new_line_item`**

Append to `EstimateWizardService` in `apps/estimates/services.py`:

```python
    @staticmethod
    def add_atoms_to_new_line_item(estimate, atoms):
        """Create a new EstimateLineItem on `estimate` with the given atoms as sources.

        atoms: list of {'type': 'plan_charge'|'plan_material', 'id': N} dicts.
        """
        from django.db import transaction, IntegrityError
        from apps.estimates.models import EstimateLineItem, EstimateLineItemSource

        EstimateWizardService._validate_draft_estimate(estimate)

        instances = [EstimateWizardService._resolve_atom(a) for a in atoms]

        total_price = sum(
            (i.compute_amount() for i in instances),
            Decimal('0.00'),
        )
        categories = {EstimateWizardService._atom_category(i) for i in instances}
        category = categories.pop() if len(categories) == 1 else None

        try:
            with transaction.atomic():
                line_item = EstimateLineItem.objects.create(
                    estimate=estimate,
                    description='',
                    qty=Decimal('1'),
                    units='each',
                    price=total_price,
                    accounting_category=category,
                )
                for instance in instances:
                    EstimateLineItemSource.objects.create(
                        estimate_line_item=line_item,
                        source_type=EstimateWizardService._atom_source_type(instance),
                        source_pk=instance.pk,
                    )
        except IntegrityError:
            existing = set(
                EstimateLineItemSource.objects
                .filter(source_type__in=[a['type'] for a in atoms])
                .values_list('source_type', 'source_pk')
            )
            conflicts = [a for a in atoms if (a['type'], a['id']) in existing]
            raise EstimateClaimConflict(atom_ids=conflicts)

        return line_item
```

Add `from decimal import Decimal` at the top of `apps/estimates/services.py` if not already imported.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_estimate_wizard_service.AddAtomsToNewLineItemTest -v 2`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/services.py tests/test_estimate_wizard_service.py
git commit -m "feat(estimates): add add_atoms_to_new_line_item to wizard"
```

---

### Task 8: Add `add_atoms_to_line_item()` (with in-sync price recompute)

**Files:**
- Modify: `apps/estimates/services.py`
- Test: extend `tests/test_estimate_wizard_service.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_estimate_wizard_service.py`:

```python
class AddAtomsToExistingLineItemTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt1 = PlanTask.objects.create(
            est_worksheet=self.ws, name='A', units='hours',
            est_qty=Decimal('1'), accounting_category=self.cat,
        )
        self.pc1 = PlanCharge.objects.create(
            plan_task=self.pt1, rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('1'),
        )
        self.pt2 = PlanTask.objects.create(
            est_worksheet=self.ws, name='B', units='hours',
            est_qty=Decimal('1'), accounting_category=self.cat,
        )
        self.pc2 = PlanCharge.objects.create(
            plan_task=self.pt2, rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('1'),
        )
        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)
        self.li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'plan_charge', 'id': self.pc1.pk}],
        )

    def test_appends_source(self):
        EstimateWizardService.add_atoms_to_line_item(
            self.li, [{'type': 'plan_charge', 'id': self.pc2.pk}],
        )
        self.assertEqual(self.li.sources.count(), 2)

    def test_recomputes_price_when_in_sync(self):
        # Initial price = $100 (1 atom). After adding 2nd atom, expect $200 (2 × $100 / 1 qty).
        EstimateWizardService.add_atoms_to_line_item(
            self.li, [{'type': 'plan_charge', 'id': self.pc2.pk}],
        )
        self.li.refresh_from_db()
        self.assertEqual(self.li.price, Decimal('200.00'))

    def test_preserves_overridden_price(self):
        # Override the price away from in-sync value
        self.li.price = Decimal('500.00')
        self.li.save()
        EstimateWizardService.add_atoms_to_line_item(
            self.li, [{'type': 'plan_charge', 'id': self.pc2.pk}],
        )
        self.li.refresh_from_db()
        self.assertEqual(self.li.price, Decimal('500.00'))

    def test_double_claim_raises(self):
        with self.assertRaises(EstimateClaimConflict):
            EstimateWizardService.add_atoms_to_line_item(
                self.li, [{'type': 'plan_charge', 'id': self.pc1.pk}],
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_estimate_wizard_service.AddAtomsToExistingLineItemTest -v 2`
Expected: FAIL — `AttributeError: ... no attribute 'add_atoms_to_line_item'`.

- [ ] **Step 3: Implement helpers and `add_atoms_to_line_item`**

Append to `EstimateWizardService` in `apps/estimates/services.py`:

```python
    @staticmethod
    def _sum_sources(line_item):
        """Sum the computed amounts of all source atoms on a line item."""
        total = Decimal('0.00')
        for src in line_item.sources.all():
            instance = src.resolve()
            total += instance.compute_amount()
        return total

    @staticmethod
    def _expected_per_unit(sum_value, qty):
        """The per-unit price the wizard would compute right now: round(sum/qty, 2)."""
        if not qty:
            return Decimal('0.00')
        return (sum_value / qty).quantize(Decimal('0.01'))

    @staticmethod
    def _is_in_sync(line_item, sum_value):
        """In sync iff price == round(sum / qty, 2)."""
        if not line_item.qty:
            return False
        return line_item.price == EstimateWizardService._expected_per_unit(sum_value, line_item.qty)

    @staticmethod
    def add_atoms_to_line_item(line_item, atoms):
        """Append N atoms as sources to an existing line item.

        Recomputes the line item's price if it was in sync before the operation;
        preserves an overridden price otherwise.
        """
        from django.db import transaction, IntegrityError
        from apps.estimates.models import EstimateLineItemSource

        EstimateWizardService._validate_draft_estimate(line_item.estimate)

        old_sum = EstimateWizardService._sum_sources(line_item)
        was_in_sync = EstimateWizardService._is_in_sync(line_item, old_sum)

        instances = [EstimateWizardService._resolve_atom(a) for a in atoms]

        try:
            with transaction.atomic():
                for instance in instances:
                    EstimateLineItemSource.objects.create(
                        estimate_line_item=line_item,
                        source_type=EstimateWizardService._atom_source_type(instance),
                        source_pk=instance.pk,
                    )
                if was_in_sync:
                    new_sum = EstimateWizardService._sum_sources(line_item)
                    line_item.price = EstimateWizardService._expected_per_unit(new_sum, line_item.qty)
                    line_item.save()
        except IntegrityError:
            existing = set(
                EstimateLineItemSource.objects
                .filter(source_type__in=[a['type'] for a in atoms])
                .values_list('source_type', 'source_pk')
            )
            conflicts = [a for a in atoms if (a['type'], a['id']) in existing]
            raise EstimateClaimConflict(atom_ids=conflicts)

        return line_item
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_estimate_wizard_service.AddAtomsToExistingLineItemTest -v 2`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/services.py tests/test_estimate_wizard_service.py
git commit -m "feat(estimates): add add_atoms_to_line_item with in-sync recompute"
```

---

### Task 9: Add `remove_atoms_from_line_item()`

**Files:**
- Modify: `apps/estimates/services.py`
- Test: extend `tests/test_estimate_wizard_service.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_estimate_wizard_service.py`:

```python
class RemoveAtomsFromLineItemTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt1 = PlanTask.objects.create(
            est_worksheet=self.ws, name='A', units='hours',
            est_qty=Decimal('1'), accounting_category=self.cat,
        )
        self.pc1 = PlanCharge.objects.create(
            plan_task=self.pt1, rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('1'),
        )
        self.pt2 = PlanTask.objects.create(
            est_worksheet=self.ws, name='B', units='hours',
            est_qty=Decimal('1'), accounting_category=self.cat,
        )
        self.pc2 = PlanCharge.objects.create(
            plan_task=self.pt2, rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('1'),
        )
        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)
        self.li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate,
            [
                {'type': 'plan_charge', 'id': self.pc1.pk},
                {'type': 'plan_charge', 'id': self.pc2.pk},
            ],
        )

    def test_removes_subset(self):
        src_to_remove = self.li.sources.filter(source_pk=self.pc1.pk).first()
        result = EstimateWizardService.remove_atoms_from_line_item(
            self.li, [src_to_remove.source_id],
        )
        self.assertFalse(result['line_item_deleted'])
        self.assertEqual(self.li.sources.count(), 1)

    def test_recomputes_price_when_in_sync(self):
        # initial $200 / 1 qty. Remove pc1 -> remaining sum = $100, expected price = $100.
        src_to_remove = self.li.sources.filter(source_pk=self.pc1.pk).first()
        EstimateWizardService.remove_atoms_from_line_item(
            self.li, [src_to_remove.source_id],
        )
        self.li.refresh_from_db()
        self.assertEqual(self.li.price, Decimal('100.00'))

    def test_preserves_overridden_price(self):
        self.li.price = Decimal('999.00')
        self.li.save()
        src_to_remove = self.li.sources.filter(source_pk=self.pc1.pk).first()
        EstimateWizardService.remove_atoms_from_line_item(
            self.li, [src_to_remove.source_id],
        )
        self.li.refresh_from_db()
        self.assertEqual(self.li.price, Decimal('999.00'))

    def test_deletes_line_item_when_all_sources_removed(self):
        all_ids = list(self.li.sources.values_list('source_id', flat=True))
        result = EstimateWizardService.remove_atoms_from_line_item(self.li, all_ids)
        self.assertTrue(result['line_item_deleted'])
        from apps.estimates.models import EstimateLineItem
        self.assertFalse(EstimateLineItem.objects.filter(pk=self.li.pk).exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_estimate_wizard_service.RemoveAtomsFromLineItemTest -v 2`
Expected: FAIL — `AttributeError: ... no attribute 'remove_atoms_from_line_item'`.

- [ ] **Step 3: Implement `remove_atoms_from_line_item`**

Append to `EstimateWizardService` in `apps/estimates/services.py`:

```python
    @staticmethod
    def remove_atoms_from_line_item(line_item, source_ids):
        """Remove a subset of source rows from a line item.

        - Recomputes price if the line item was in sync before.
        - Preserves price if it was overridden.
        - Deletes the line item if all sources are removed.

        Returns: {'line_item_deleted': bool}
        """
        from django.db import transaction

        EstimateWizardService._validate_draft_estimate(line_item.estimate)

        old_sum = EstimateWizardService._sum_sources(line_item)
        was_in_sync = EstimateWizardService._is_in_sync(line_item, old_sum)

        with transaction.atomic():
            line_item.sources.filter(source_id__in=source_ids).delete()
            remaining = line_item.sources.count()

            if remaining == 0:
                line_item.delete()
                return {'line_item_deleted': True}

            if was_in_sync:
                new_sum = EstimateWizardService._sum_sources(line_item)
                line_item.price = EstimateWizardService._expected_per_unit(new_sum, line_item.qty)
                line_item.save()

        return {'line_item_deleted': False}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_estimate_wizard_service.RemoveAtomsFromLineItemTest -v 2`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/services.py tests/test_estimate_wizard_service.py
git commit -m "feat(estimates): add remove_atoms_from_line_item to wizard"
```

---

### Task 10: Add `send_all_atoms_to_estimate()` (bulk 1:1 conversion)

**Files:**
- Modify: `apps/estimates/services.py`
- Test: extend `tests/test_estimate_wizard_service.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_estimate_wizard_service.py`:

```python
class SendAllAtomsTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='A', units='hours',
            est_qty=Decimal('2'), accounting_category=self.cat,
        )
        self.pc = PlanCharge.objects.create(
            plan_task=self.pt, rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('2'),
        )
        self.pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )

    def test_creates_one_line_item_per_unclaimed_atom(self):
        result = EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        self.assertEqual(result['created_count'], 2)
        from apps.estimates.models import EstimateLineItem
        line_items = EstimateLineItem.objects.filter(estimate=result['estimate'])
        self.assertEqual(line_items.count(), 2)

    def test_each_line_item_has_one_source(self):
        result = EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        from apps.estimates.models import EstimateLineItem
        for li in EstimateLineItem.objects.filter(estimate=result['estimate']):
            self.assertEqual(li.sources.count(), 1)

    def test_skips_already_claimed_atoms(self):
        # Pre-claim the PlanCharge via an existing line item
        estimate = EstimateWizardService.open_for_worksheet(self.ws)
        EstimateWizardService.add_atoms_to_new_line_item(
            estimate, [{'type': 'plan_charge', 'id': self.pc.pk}],
        )
        result = EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        # Only the PlanMaterial gets a new line item
        self.assertEqual(result['created_count'], 1)

    def test_amount_matches_compute_amount(self):
        result = EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        from apps.estimates.models import EstimateLineItem
        prices = sorted(
            EstimateLineItem.objects.filter(estimate=result['estimate']).values_list('price', flat=True)
        )
        # PlanCharge: 2 × $100 = $200; PlanMaterial: 3 × $5 = $15
        self.assertEqual(prices, [Decimal('15.00'), Decimal('200.00')])

    def test_returns_estimate(self):
        result = EstimateWizardService.send_all_atoms_to_estimate(self.ws)
        self.assertEqual(result['estimate'].job, self.job)
        self.assertEqual(result['estimate'].status, Estimate.STATUS_DRAFT)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_estimate_wizard_service.SendAllAtomsTest -v 2`
Expected: FAIL — `AttributeError: ... no attribute 'send_all_atoms_to_estimate'`.

- [ ] **Step 3: Implement `send_all_atoms_to_estimate`**

Append to `EstimateWizardService` in `apps/estimates/services.py`:

```python
    @staticmethod
    def send_all_atoms_to_estimate(worksheet):
        """Bulk 1:1 conversion of unclaimed atoms on the worksheet to EstimateLineItems.

        Iterates all PlanCharges and PlanMaterials on the worksheet that aren't yet
        claimed by any EstimateLineItemSource, and creates one EstimateLineItem per
        atom (with one source row pointing at the atom).

        Returns: {'estimate': Estimate, 'created_count': int}
        """
        from apps.estimates.models import EstimateLineItem, EstimateLineItemSource
        from apps.jobs.models import PlanCharge
        from apps.inventory.models import PlanMaterial

        estimate = EstimateWizardService.open_for_worksheet(worksheet)

        # Build set of currently-claimed (type, pk) pairs
        claimed = set(
            EstimateLineItemSource.objects.values_list('source_type', 'source_pk')
        )

        created_count = 0

        # PlanCharges
        for pc in PlanCharge.objects.filter(plan_task__est_worksheet=worksheet).select_related('plan_task', 'plan_task__accounting_category'):
            if (EstimateLineItemSource.SOURCE_PLAN_CHARGE, pc.pk) in claimed:
                continue
            li = EstimateLineItem.objects.create(
                estimate=estimate,
                description=pc.plan_task.name,
                qty=Decimal('1'),
                units=pc.plan_task.units,
                price=pc.compute_amount(),
                accounting_category=pc.plan_task.accounting_category,
            )
            EstimateLineItemSource.objects.create(
                estimate_line_item=li,
                source_type=EstimateLineItemSource.SOURCE_PLAN_CHARGE,
                source_pk=pc.pk,
            )
            created_count += 1

        # PlanMaterials
        for pm in PlanMaterial.objects.filter(est_worksheet=worksheet).select_related('accounting_category'):
            if (EstimateLineItemSource.SOURCE_PLAN_MATERIAL, pm.pk) in claimed:
                continue
            li = EstimateLineItem.objects.create(
                estimate=estimate,
                description=pm.description,
                qty=Decimal('1'),
                units='each',
                price=pm.compute_amount(),
                accounting_category=pm.accounting_category,
            )
            EstimateLineItemSource.objects.create(
                estimate_line_item=li,
                source_type=EstimateLineItemSource.SOURCE_PLAN_MATERIAL,
                source_pk=pm.pk,
            )
            created_count += 1

        return {'estimate': estimate, 'created_count': created_count}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_estimate_wizard_service.SendAllAtomsTest -v 2`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/services.py tests/test_estimate_wizard_service.py
git commit -m "feat(estimates): add send_all_atoms_to_estimate bulk action"
```

---

## Phase 4 — REST API

### Task 11: Wire wizard endpoints onto `EstimateViewSet`

**Files:**
- Modify: `apps/api/estimates/views.py` — `EstimateViewSet` (around line 10)
- Test: `tests/test_estimate_wizard_api.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_estimate_wizard_api.py`:

```python
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, User
from apps.estimates.models import Estimate, EstWorksheet, EstimateLineItem
from apps.estimates.services import EstimateWizardService
from apps.inventory.models import PlanMaterial
from apps.jobs.models import Job, PlanCharge, PlanTask, RateScheme


class EstimateWizardAPITest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.user = User.objects.create_user(
            username='u', password='p', can_manage_jobs=True,
        )
        self.client = APIClient()
        self.client.login(username='u', password='p')

        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Setup', units='hours',
            est_qty=Decimal('2'), accounting_category=self.cat,
        )
        self.pc = PlanCharge.objects.create(
            plan_task=self.pt, rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('2'),
        )
        self.pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )
        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)

    def test_source_pool_endpoint(self):
        url = f'/api/estimates/{self.estimate.pk}/source-pool/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('atoms', data)
        types = [a['type'] for a in data['atoms']]
        self.assertIn('plan_charge', types)
        self.assertIn('plan_material', types)

    def test_line_items_from_atoms_endpoint(self):
        url = f'/api/estimates/{self.estimate.pk}/line-items-from-atoms/'
        payload = {'atoms': [{'type': 'plan_charge', 'id': self.pc.pk}]}
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(EstimateLineItem.objects.filter(estimate=self.estimate).count(), 1)

    def test_line_items_from_atoms_conflict_returns_409(self):
        # First claim
        url = f'/api/estimates/{self.estimate.pk}/line-items-from-atoms/'
        payload = {'atoms': [{'type': 'plan_charge', 'id': self.pc.pk}]}
        self.client.post(url, payload, format='json')
        # Second claim attempt
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['error'], 'atoms_already_claimed')

    def test_add_atoms_to_existing_line_item(self):
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'plan_charge', 'id': self.pc.pk}],
        )
        url = f'/api/estimates/{self.estimate.pk}/line-items/{li.pk}/add-atoms/'
        payload = {'atoms': [{'type': 'plan_material', 'id': self.pm.pk}]}
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 200)
        li.refresh_from_db()
        self.assertEqual(li.sources.count(), 2)

    def test_remove_atoms_endpoint(self):
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate,
            [
                {'type': 'plan_charge', 'id': self.pc.pk},
                {'type': 'plan_material', 'id': self.pm.pk},
            ],
        )
        src_id = li.sources.first().source_id
        url = f'/api/estimates/{self.estimate.pk}/line-items/{li.pk}/remove-atoms/'
        resp = self.client.post(url, {'source_ids': [src_id]}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['line_item_deleted'])

    def test_remove_all_atoms_deletes_line_item(self):
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'plan_charge', 'id': self.pc.pk}],
        )
        all_ids = list(li.sources.values_list('source_id', flat=True))
        url = f'/api/estimates/{self.estimate.pk}/line-items/{li.pk}/remove-atoms/'
        resp = self.client.post(url, {'source_ids': all_ids}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['line_item_deleted'])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_estimate_wizard_api -v 2`
Expected: FAIL — endpoints return 404 (URLs don't exist yet).

- [ ] **Step 3: Add the endpoints to `EstimateViewSet`**

Modify `apps/api/estimates/views.py` — locate `EstimateViewSet` and add these `@action` methods inside the class. Use the same Decimal serialization pattern as `apps/api/invoicing/views.py:46-136`.

```python
from rest_framework.decorators import action
from rest_framework.response import Response


# Inside EstimateViewSet:

@action(detail=True, methods=['get'], url_path='source-pool')
def source_pool(self, request, pk=None):
    """Return the source pool for the wizard, drawn from this estimate's worksheet."""
    from apps.estimates.services import EstimateWizardService
    estimate = self.get_object()
    worksheet = estimate.worksheets.first()
    if not worksheet:
        return Response({'atoms': []})
    pool = EstimateWizardService.get_source_pool(worksheet)
    return Response(_serialize_pool(pool))

@action(detail=True, methods=['post'], url_path='line-items-from-atoms')
def line_items_from_atoms(self, request, pk=None):
    """Create a new estimate line item from a list of atoms."""
    from django.core.exceptions import ValidationError
    from apps.estimates.services import EstimateWizardService, EstimateClaimConflict
    from .serializers import EstimateLineItemSerializer

    estimate = self.get_object()
    atoms = request.data.get('atoms', [])
    try:
        line_item = EstimateWizardService.add_atoms_to_new_line_item(estimate, atoms)
    except EstimateClaimConflict as e:
        return Response(
            {'error': 'atoms_already_claimed', 'atom_ids': e.atom_ids},
            status=409,
        )
    except ValidationError as e:
        return Response({'error': str(e)}, status=400)
    serializer = EstimateLineItemSerializer(line_item)
    return Response(serializer.data, status=201)

@action(
    detail=True, methods=['post'],
    url_path=r'line-items/(?P<line_item_pk>[^/.]+)/add-atoms',
)
def add_atoms(self, request, pk=None, line_item_pk=None):
    """Append atoms to an existing line item."""
    from django.core.exceptions import ValidationError
    from apps.estimates.models import EstimateLineItem
    from apps.estimates.services import EstimateWizardService, EstimateClaimConflict
    from .serializers import EstimateLineItemSerializer

    estimate = self.get_object()
    try:
        line_item = EstimateLineItem.objects.get(pk=line_item_pk, estimate=estimate)
    except EstimateLineItem.DoesNotExist:
        return Response({'error': 'Line item not found'}, status=404)

    atoms = request.data.get('atoms', [])
    try:
        EstimateWizardService.add_atoms_to_line_item(line_item, atoms)
    except EstimateClaimConflict as e:
        return Response(
            {'error': 'atoms_already_claimed', 'atom_ids': e.atom_ids},
            status=409,
        )
    except ValidationError as e:
        return Response({'error': str(e)}, status=400)

    line_item.refresh_from_db()
    serializer = EstimateLineItemSerializer(line_item)
    return Response(serializer.data, status=200)

@action(
    detail=True, methods=['post'],
    url_path=r'line-items/(?P<line_item_pk>[^/.]+)/remove-atoms',
)
def remove_atoms(self, request, pk=None, line_item_pk=None):
    """Remove atoms from an existing line item."""
    from django.core.exceptions import ValidationError
    from apps.estimates.models import EstimateLineItem
    from apps.estimates.services import EstimateWizardService
    from .serializers import EstimateLineItemSerializer

    estimate = self.get_object()
    try:
        line_item = EstimateLineItem.objects.get(pk=line_item_pk, estimate=estimate)
    except EstimateLineItem.DoesNotExist:
        return Response({'error': 'Line item not found'}, status=404)

    source_ids = request.data.get('source_ids', [])
    try:
        result = EstimateWizardService.remove_atoms_from_line_item(line_item, source_ids)
    except ValidationError as e:
        return Response({'error': str(e)}, status=400)

    if result['line_item_deleted']:
        return Response({'line_item_deleted': True, 'line_item': None})

    line_item.refresh_from_db()
    return Response({
        'line_item_deleted': False,
        'line_item': EstimateLineItemSerializer(line_item).data,
    })
```

Then add the `_serialize_pool` helper at module level in `apps/api/estimates/views.py`. Copy from `apps/api/invoicing/views.py` (look for the `_serialize_pool` function — typically around line 200+) and adapt for the estimate atom shape (`atoms` is a flat list, not nested in `tasks`):

```python
def _serialize_pool(pool):
    """Convert Decimals to strings for JSON serialization."""
    out = {'atoms': []}
    for a in pool['atoms']:
        out['atoms'].append({
            **a,
            'amount': str(a['amount']),
        })
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_estimate_wizard_api -v 2`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/api/estimates/views.py tests/test_estimate_wizard_api.py
git commit -m "feat(api): wire estimate wizard endpoints"
```

---

### Task 12: Add `send-all-atoms-to-estimate` endpoint to `EstWorksheetViewSet`

**Files:**
- Modify: `apps/api/worksheets/views.py` — `EstWorksheetViewSet` (around line 14)
- Test: extend `tests/test_estimate_wizard_api.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_estimate_wizard_api.py`:

```python
class SendAllAtomsAPITest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.user = User.objects.create_user(
            username='u', password='p', can_manage_jobs=True,
        )
        self.client = APIClient()
        self.client.login(username='u', password='p')
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Setup', units='hours',
            est_qty=Decimal('1'), accounting_category=self.cat,
        )
        self.pc = PlanCharge.objects.create(
            plan_task=self.pt, rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('1'),
        )

    def test_send_all_creates_estimate_and_line_items(self):
        url = f'/api/est-worksheets/{self.ws.pk}/send-all-atoms-to-estimate/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('estimate_id', data)
        self.assertEqual(data['created_count'], 1)
        self.assertEqual(EstimateLineItem.objects.filter(estimate_id=data['estimate_id']).count(), 1)

    def test_send_all_idempotent_for_already_claimed(self):
        url = f'/api/est-worksheets/{self.ws.pk}/send-all-atoms-to-estimate/'
        self.client.post(url)
        # Second call: nothing new should be created
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['created_count'], 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_estimate_wizard_api.SendAllAtomsAPITest -v 2`
Expected: FAIL with 404.

- [ ] **Step 3: Add the endpoint**

Modify `apps/api/worksheets/views.py` — inside `EstWorksheetViewSet` (around line 14, alongside the existing `@action` methods):

```python
@action(detail=True, methods=['post'], url_path='send-all-atoms-to-estimate')
def send_all_atoms_to_estimate(self, request, pk=None):
    """Bulk 1:1 conversion of unclaimed atoms to EstimateLineItems."""
    from django.core.exceptions import ValidationError
    from apps.estimates.services import EstimateWizardService

    worksheet = self.get_object()
    try:
        result = EstimateWizardService.send_all_atoms_to_estimate(worksheet)
    except ValidationError as e:
        return Response({'error': str(e)}, status=400)
    return Response({
        'estimate_id': result['estimate'].pk,
        'estimate_number': result['estimate'].estimate_number,
        'created_count': result['created_count'],
    })
```

Add `from rest_framework.decorators import action` and `from rest_framework.response import Response` at the top of the file if not already imported.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_estimate_wizard_api.SendAllAtomsAPITest -v 2`
Expected: PASS (2 tests).

- [ ] **Step 5: Run full test suite to confirm nothing regressed**

Run: `python manage.py test tests -v 1`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/api/worksheets/views.py tests/test_estimate_wizard_api.py
git commit -m "feat(api): add send-all-atoms-to-estimate endpoint on worksheet"
```

---

## Phase 5 — Verification

### Task 13: End-to-end verification

- [ ] **Step 1: Run the full test suite**

Run: `python manage.py test -v 1`
Expected: All tests pass. Note any pre-existing failures unrelated to this plan.

- [ ] **Step 2: Manual API smoke test (optional)**

Start the dev server: `python manage.py runserver`

Using curl or a REST client, exercise:
- `GET /api/estimates/<id>/source-pool/`
- `POST /api/estimates/<id>/line-items-from-atoms/` with `{"atoms": [{"type":"plan_charge","id":N}]}`
- `POST /api/est-worksheets/<id>/send-all-atoms-to-estimate/`

Verify each returns the expected payloads.

- [ ] **Step 3: Confirm old machinery still works**

This plan adds the new wizard alongside the existing `EstimateGenerationService` / `mapping_strategy` flow. Confirm the old "generate-estimate" UI/API still works:
- `POST /api/est-worksheets/<id>/generate-estimate/`

Expected: still functions as before. Plan B and Plan C handle removal.

---

## Self-review

**Spec coverage:** This plan covers the design's "Atom model," "Containers and parallel structure," "Line items and source rows," and "Worksheet → Estimate operations" sections, plus the new `EstimateLineItem.source_template` field. It does NOT cover catalog picker (Plan B), atom carry-over service (Plan C), Job state machine changes (Plan C), or migration/removal of old machinery (Plan C).

**Placeholder scan:** No "TBD" or vague "implement later." Every step has either a code block or an exact command + expected output.

**Type consistency:** `compute_amount(active_modifiers=None) -> Decimal` is the uniform interface used in tests and implementations. `EstimateLineItemSource.SOURCE_PLAN_CHARGE` and `SOURCE_PLAN_MATERIAL` constants are used consistently. Service method signatures match between definition and test usage. `add_atoms_to_new_line_item(estimate, atoms)` and `add_atoms_to_line_item(line_item, atoms)` match the invoice wizard naming.

**Open follow-ups (Plan B/C):**
- Catalog picker Svelte component
- `Job.STATUS_IN_PROGRESS` state and transition handling
- Atom carry-over service (Worksheet → Job on Estimate accepted)
- Direct-line-item carry-over (template-ref EstimateLineItems → atoms)
- Migration: back-fill `EstimateLineItemSource` rows from existing `EstimateLineItem.task` / `material` FKs
- Removal: `PlanBundle`, `mapping_strategy`, `TemplateBundle`, `EstimateGenerationService`, old `EstimateLineItem.task`/`material` FKs

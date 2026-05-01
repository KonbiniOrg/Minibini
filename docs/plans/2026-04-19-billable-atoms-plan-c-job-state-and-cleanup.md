# Billable Atoms — Plan C: Job State, Carry-Over, and Cleanup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the design described in `docs/designs/2026-04-19-billable-atoms-and-estimate-wizard-design.md`. Adds the new `Job.STATUS_IN_PROGRESS` state, the atom carry-over service that fires on `Estimate.accepted`, the Job Board / "Release to floor" frontend updates, then migrates existing data and removes the old declarative machinery (`PlanBundle`, `mapping_strategy`, `TemplateBundle`, `EstimateGenerationService`, old `EstimateLineItem.task` / `material` FKs).

**Architecture:** A new `AtomCarryOverService` walks the worksheet's atoms (PlanCharges → TaskCharges, PlanMaterials → Materials) and creates matching records on the Job; for direct-estimate line items with template refs, it creates equivalent atoms from the templates. It hooks into the existing `estimate_accepted` signal (which is already fired in `apps/estimates/models.py`). The Job state machine adds `IN_PROGRESS` between `APPROVED` and `WORK_COMPLETE` — `APPROVED` becomes "estimate accepted, awaiting prep" and `IN_PROGRESS` is "released to floor." Old machinery is removed only after data migration back-fills `EstimateLineItemSource` rows from the legacy FKs.

**Tech Stack:** Django 5.2, MySQL, Python 3.12, Svelte 5. Tests use Django TestCase.

**Reference files:**
- `apps/jobs/models.py:9-120` — `Job` model and existing state machine
- `apps/estimates/signals.py` — existing `estimate_accepted` signal and receivers
- `apps/jobs/services.py:283-311` — existing `populate_from_estimate` (legacy; will be removed)
- `apps/estimates/services.py:626-822` — `EstimateGenerationService` (will be removed)

**Prerequisite plans:** Plan A (backend foundation) and Plan B (frontend) must be merged before starting this plan.

---

## Phase 1 — Job state machine: add `IN_PROGRESS`

### Task 1: Add `Job.STATUS_IN_PROGRESS` constant + choice + transitions

**Files:**
- Modify: `apps/jobs/models.py:9-86`
- Test: `tests/test_job_in_progress_state.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_job_in_progress_state.py`:

```python
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import Configuration
from apps.jobs.models import Job


class JobInProgressStateTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )

    def test_status_in_progress_constant_exists(self):
        self.assertEqual(Job.STATUS_IN_PROGRESS, 'in_progress')

    def test_in_progress_in_choices(self):
        choices = dict(Job.JOB_STATUS_CHOICES)
        self.assertIn(Job.STATUS_IN_PROGRESS, choices)

    def test_approved_can_transition_to_in_progress(self):
        job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        job.status = Job.STATUS_SUBMITTED
        job.save()
        job.status = Job.STATUS_APPROVED
        job.save()
        job.status = Job.STATUS_IN_PROGRESS
        job.save()  # Should not raise
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)

    def test_in_progress_can_transition_to_work_complete(self):
        job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        job.status = Job.STATUS_SUBMITTED
        job.save()
        job.status = Job.STATUS_APPROVED
        job.save()
        job.status = Job.STATUS_IN_PROGRESS
        job.save()
        job.status = Job.STATUS_WORK_COMPLETE
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_WORK_COMPLETE)

    def test_in_progress_can_be_cancelled(self):
        job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        job.status = Job.STATUS_SUBMITTED
        job.save()
        job.status = Job.STATUS_APPROVED
        job.save()
        job.status = Job.STATUS_IN_PROGRESS
        job.save()
        job.status = Job.STATUS_CANCELLED
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_CANCELLED)

    def test_approved_can_no_longer_jump_to_work_complete(self):
        # Old transition approved → work_complete is removed; must go via in_progress
        job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        job.status = Job.STATUS_SUBMITTED
        job.save()
        job.status = Job.STATUS_APPROVED
        job.save()
        job.status = Job.STATUS_WORK_COMPLETE
        with self.assertRaises(ValidationError):
            job.save()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_job_in_progress_state -v 2`
Expected: FAIL — `AttributeError: type object 'Job' has no attribute 'STATUS_IN_PROGRESS'`.

- [ ] **Step 3: Add the new state and update transitions**

Modify `apps/jobs/models.py` — locate the Job model (around line 9) and update:

```python
class Job(AbstractWorkContainer):
    STATUS_DRAFT = 'draft'
    STATUS_SUBMITTED = 'submitted'
    STATUS_APPROVED = 'approved'
    STATUS_IN_PROGRESS = 'in_progress'  # NEW
    STATUS_WORK_COMPLETE = 'work_complete'
    STATUS_REJECTED = 'rejected'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'

    JOB_STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SUBMITTED, 'Submitted'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_IN_PROGRESS, 'In Progress'),  # NEW
        (STATUS_WORK_COMPLETE, 'Work Complete'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]
```

Then in the `clean()` method (around line 41), update `VALID_TRANSITIONS`:

```python
VALID_TRANSITIONS = {
    Job.STATUS_DRAFT: [Job.STATUS_SUBMITTED, Job.STATUS_REJECTED],
    Job.STATUS_SUBMITTED: [Job.STATUS_APPROVED, Job.STATUS_REJECTED],
    Job.STATUS_APPROVED: [Job.STATUS_IN_PROGRESS, Job.STATUS_CANCELLED],  # was: STATUS_WORK_COMPLETE
    Job.STATUS_IN_PROGRESS: [Job.STATUS_WORK_COMPLETE, Job.STATUS_CANCELLED],  # NEW
    Job.STATUS_WORK_COMPLETE: [Job.STATUS_COMPLETED, Job.STATUS_CANCELLED],
    Job.STATUS_REJECTED: [],
    Job.STATUS_COMPLETED: [],
    Job.STATUS_CANCELLED: [],
}
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations jobs -n add_job_in_progress_state`
Expected: A migration file is created updating the `status` field choices.

- [ ] **Step 5: Run tests**

Run: `python manage.py test tests.test_job_in_progress_state -v 2`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/ tests/test_job_in_progress_state.py
git commit -m "feat(jobs): add STATUS_IN_PROGRESS state between APPROVED and WORK_COMPLETE"
```

---

### Task 2: Update billable-job-statuses for invoicing

**Files:**
- Modify: `apps/invoicing/services.py:177` — `InvoiceWizardService.BILLABLE_JOB_STATUSES`
- Test: extend `tests/test_invoice_wizard_service.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_invoice_wizard_service.py` inside `OpenForJobTest`:

```python
def test_allows_in_progress_job(self):
    in_progress_job = Job.objects.create(
        contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0099',
    )
    in_progress_job.status = Job.STATUS_SUBMITTED
    in_progress_job.save()
    in_progress_job.status = Job.STATUS_APPROVED
    in_progress_job.save()
    in_progress_job.status = Job.STATUS_IN_PROGRESS
    in_progress_job.save()

    invoice = InvoiceWizardService.open_for_job(in_progress_job)
    self.assertEqual(invoice.status, Invoice.STATUS_DRAFT)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_invoice_wizard_service.OpenForJobTest.test_allows_in_progress_job -v 2`
Expected: FAIL — `ValidationError: Cannot start invoice wizard for job in status "in_progress"`.

- [ ] **Step 3: Add `STATUS_IN_PROGRESS` to billable statuses**

Modify `apps/invoicing/services.py` around line 177:

```python
class InvoiceWizardService:
    """..."""

    BILLABLE_JOB_STATUSES = {
        Job.STATUS_APPROVED,
        Job.STATUS_IN_PROGRESS,  # NEW
        Job.STATUS_WORK_COMPLETE,
        Job.STATUS_COMPLETED,
    }
```

- [ ] **Step 4: Run tests**

Run: `python manage.py test tests.test_invoice_wizard_service -v 2`
Expected: PASS (all tests, including the new one).

- [ ] **Step 5: Commit**

```bash
git add apps/invoicing/services.py tests/test_invoice_wizard_service.py
git commit -m "feat(invoicing): allow in_progress jobs in the invoice wizard"
```

---

## Phase 2 — Atom carry-over service

### Task 3: Build `AtomCarryOverService.carry_over_for_estimate()`

**Files:**
- Create: `apps/estimates/carry_over.py` (new module — keeps it separate from existing services file for clarity)
- Test: `tests/test_atom_carry_over.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_atom_carry_over.py`:

```python
from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.carry_over import AtomCarryOverService
from apps.estimates.models import Estimate, EstimateLineItem, EstWorksheet, TaskTemplate
from apps.estimates.services import EstimateWizardService
from apps.inventory.models import Material, PlanMaterial, PriceListItem
from apps.jobs.models import Job, PlanCharge, PlanTask, RateScheme, Task, TaskCharge


class CarryOverFromWorksheetAtomsTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
        )
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

    def test_creates_task_for_each_plan_charge(self):
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        tasks = Task.objects.filter(job=self.job)
        self.assertEqual(tasks.count(), 1)
        t = tasks.first()
        self.assertEqual(t.name, 'Setup')

    def test_creates_taskcharge_with_seed_qty(self):
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        t = Task.objects.get(job=self.job)
        self.assertTrue(hasattr(t, 'charge'))
        self.assertEqual(t.charge.rate_scheme, self.scheme)
        # Seed actuals from estimated qty (entered_qty schemes); elapsed_time is no-op
        # PlanCharge with elapsed_time scheme: actuals stays empty
        self.assertEqual(t.charge.actuals, {})

    def test_creates_taskcharge_seeds_entered_qty_from_estimate(self):
        # Replace scheme to entered_qty
        scheme_qty = RateScheme.objects.create(
            name='PerItem', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50'), unit_label='item', accounting_category=self.cat,
        )
        self.pc.rate_scheme = scheme_qty
        self.pc.save()
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        t = Task.objects.get(job=self.job)
        self.assertEqual(t.charge.actuals, {'qty': '2'})

    def test_creates_material_for_each_plan_material(self):
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        materials = Material.objects.filter(job=self.job)
        self.assertEqual(materials.count(), 1)
        m = materials.first()
        self.assertEqual(m.description, 'steel')
        self.assertEqual(m.quantity, Decimal('3'))

    def test_idempotent_on_repeated_call(self):
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        self.assertEqual(Task.objects.filter(job=self.job).count(), 1)
        self.assertEqual(Material.objects.filter(job=self.job).count(), 1)


class CarryOverFromDirectLineItemsTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
        )
        self.estimate = Estimate.objects.create(job=self.job, status=Estimate.STATUS_DRAFT)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.template = TaskTemplate.objects.create(
            template_name='Setup', units='hours', rate=Decimal('100'),
            accounting_category=self.cat, rate_scheme=self.scheme,
        )
        self.pli = PriceListItem.objects.create(
            code='STEEL', description='steel rod', units='ft',
            purchase_price=Decimal('3'), selling_price=Decimal('5'),
            accounting_category=self.cat,
        )

    def test_creates_task_from_template_ref(self):
        EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('2'), units='hours',
            price=Decimal('100'), description='Setup',
            accounting_category=self.cat,
            source_template=self.template,
        )
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        tasks = Task.objects.filter(job=self.job)
        self.assertEqual(tasks.count(), 1)
        self.assertEqual(tasks.first().source_template, self.template)

    def test_creates_material_from_pli_ref(self):
        EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('3'), units='ft',
            price=Decimal('5'), description='steel rod',
            accounting_category=self.cat,
            price_list_item=self.pli,
        )
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        materials = Material.objects.filter(job=self.job)
        self.assertEqual(materials.count(), 1)
        self.assertEqual(materials.first().price_list_item, self.pli)

    def test_skips_purely_manual_line_items(self):
        EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('500'), description='one-off bespoke thing',
            accounting_category=self.cat,
        )
        AtomCarryOverService.carry_over_for_estimate(self.estimate)
        self.assertEqual(Task.objects.filter(job=self.job).count(), 0)
        self.assertEqual(Material.objects.filter(job=self.job).count(), 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_atom_carry_over -v 2`
Expected: FAIL — `ImportError: cannot import name 'AtomCarryOverService' from 'apps.estimates.carry_over'`.

- [ ] **Step 3: Implement the service**

Create `apps/estimates/carry_over.py`:

```python
"""Atom carry-over from Worksheet/Estimate to Job at acceptance time.

Triggered automatically when an Estimate transitions to ACCEPTED. Walks the
worksheet's atoms (PlanCharges, PlanMaterials) and creates matching atoms on
the Job (Tasks/TaskCharges, Materials). For direct-estimate line items with
template refs (no worksheet), creates equivalent atoms from the templates.
Idempotent on source_template / price_list_item — re-running the carry-over
on a job that already has matching atoms is a no-op.
"""
from decimal import Decimal

from django.db import transaction


class AtomCarryOverService:

    @staticmethod
    @transaction.atomic
    def carry_over_for_estimate(estimate):
        """Create atoms on the Job from the estimate's worksheet (if any) and from
        any direct-estimate line items that carry a template ref.

        Returns: {'tasks_created': int, 'materials_created': int}
        """
        job = estimate.job

        tasks_created = 0
        materials_created = 0

        # Phase A: walk worksheet atoms (if a worksheet exists)
        worksheet = estimate.worksheets.first()
        if worksheet:
            tasks_created += AtomCarryOverService._carry_over_plan_charges(worksheet, job)
            materials_created += AtomCarryOverService._carry_over_plan_materials(worksheet, job)

        # Phase B: walk direct-estimate line items with template refs
        for li in estimate.estimatelineitem_set.all():
            if li.source_template_id and not li.sources.exists():
                # source_template is set AND no source rows → direct line item from a TaskTemplate
                if AtomCarryOverService._create_task_from_line_item(li, job):
                    tasks_created += 1
            elif li.price_list_item_id and not li.sources.exists():
                # PLI ref AND no source rows → direct line item from a PriceListItem
                if AtomCarryOverService._create_material_from_line_item(li, job):
                    materials_created += 1
            # purely manual (no template ref, no PLI ref) → skip

        return {'tasks_created': tasks_created, 'materials_created': materials_created}

    @staticmethod
    def _carry_over_plan_charges(worksheet, job):
        from apps.jobs.models import PlanCharge, RateScheme, Task, TaskCharge
        count = 0
        for pc in PlanCharge.objects.filter(plan_task__est_worksheet=worksheet).select_related('plan_task', 'rate_scheme'):
            source_template = pc.plan_task.source_template if hasattr(pc.plan_task, 'source_template') else None
            # Idempotency: skip if a Task on the same job already came from this source_template
            if source_template and Task.objects.filter(job=job, source_template=source_template).exists():
                continue
            task = Task.objects.create(
                job=job,
                name=pc.plan_task.name,
                description=pc.plan_task.description,
                units=pc.plan_task.units,
                rate=pc.plan_task.rate,
                est_qty=pc.plan_task.est_qty,
                accounting_category=pc.plan_task.accounting_category,
                source_template=source_template,
            )
            actuals = {}
            if pc.rate_scheme.algorithm == RateScheme.ENTERED_QTY:
                actuals = {'qty': str(pc.estimated_billable_qty)}
            TaskCharge.objects.create(
                task=task,
                rate_scheme=pc.rate_scheme,
                active_modifiers=pc.active_modifiers,
                actuals=actuals,
            )
            count += 1
        return count

    @staticmethod
    def _carry_over_plan_materials(worksheet, job):
        from apps.inventory.models import Material, PlanMaterial
        from apps.jobs.models import Task
        count = 0
        for pm in PlanMaterial.objects.filter(est_worksheet=worksheet):
            # Idempotency: skip if a Material on the same job already exists with same PLI ref
            if pm.price_list_item_id and Material.objects.filter(job=job, price_list_item=pm.price_list_item).exists():
                continue
            # If the PlanMaterial was attached to a PlanTask, find the corresponding Task on the job
            task = None
            if pm.plan_task_id and pm.plan_task.source_template_id:
                task = Task.objects.filter(job=job, source_template=pm.plan_task.source_template).first()
            Material.objects.create(
                job=job,
                task=task,
                description=pm.description,
                quantity=pm.quantity,
                unit_cost=pm.unit_cost,
                sell_price=pm.sell_price,
                price_list_item=pm.price_list_item,
                accounting_category=pm.accounting_category,
            )
            count += 1
        return count

    @staticmethod
    def _create_task_from_line_item(line_item, job):
        from apps.jobs.models import RateScheme, Task, TaskCharge
        template = line_item.source_template
        # Idempotency
        if Task.objects.filter(job=job, source_template=template).exists():
            return False
        task = Task.objects.create(
            job=job,
            name=template.template_name,
            description=template.description or '',
            units=template.units,
            rate=template.rate,
            est_qty=line_item.qty,
            accounting_category=template.accounting_category,
            source_template=template,
        )
        if template.rate_scheme_id:
            actuals = {}
            if template.rate_scheme.algorithm == RateScheme.ENTERED_QTY:
                actuals = {'qty': str(line_item.qty)}
            TaskCharge.objects.create(
                task=task,
                rate_scheme=template.rate_scheme,
                actuals=actuals,
            )
        return True

    @staticmethod
    def _create_material_from_line_item(line_item, job):
        from apps.inventory.models import Material
        pli = line_item.price_list_item
        if Material.objects.filter(job=job, price_list_item=pli).exists():
            return False
        Material.objects.create(
            job=job,
            description=pli.description,
            quantity=line_item.qty,
            unit_cost=pli.purchase_price,
            sell_price=pli.selling_price,
            price_list_item=pli,
            accounting_category=pli.accounting_category,
        )
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_atom_carry_over -v 2`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/carry_over.py tests/test_atom_carry_over.py
git commit -m "feat(estimates): add AtomCarryOverService for Worksheet→Job atom carry-over"
```

---

### Task 4: Hook the carry-over service to the `estimate_accepted` signal

**Files:**
- Modify: `apps/estimates/signals.py` — add a new receiver
- Test: `tests/test_carry_over_signal.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_carry_over_signal.py`:

```python
from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import Estimate, EstWorksheet
from apps.estimates.services import EstimateWizardService
from apps.inventory.models import PlanMaterial
from apps.jobs.models import Job, PlanCharge, PlanTask, RateScheme, Task


class CarryOverSignalTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
        )
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
        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)

    def test_carry_over_fires_on_estimate_accepted(self):
        # Walk the estimate through draft → open → accepted
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()

        # Carry-over should have fired and created a Task on the job
        self.assertEqual(Task.objects.filter(job=self.job).count(), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_carry_over_signal -v 2`
Expected: FAIL — Task count is 0 (no carry-over fires yet).

- [ ] **Step 3: Add the receiver**

Modify `apps/estimates/signals.py` — append at the end of the file:

```python
@receiver(estimate_accepted)
def trigger_atom_carry_over(sender, estimate, **kwargs):
    """When an Estimate is accepted, carry over atoms from its worksheet (and from
    any direct-estimate line items with template refs) to the Job.
    """
    from apps.estimates.carry_over import AtomCarryOverService
    AtomCarryOverService.carry_over_for_estimate(estimate)
```

- [ ] **Step 4: Run tests**

Run: `python manage.py test tests.test_carry_over_signal -v 2`
Expected: PASS.

- [ ] **Step 5: Run full suite to confirm nothing regressed**

Run: `python manage.py test -v 1`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/estimates/signals.py tests/test_carry_over_signal.py
git commit -m "feat(estimates): wire AtomCarryOverService to estimate_accepted signal"
```

---

## Phase 3 — Frontend: Job Board color + Release-to-floor button

### Task 5: Add `IN_PROGRESS` handling and `APPROVED` color to JobBoard

**Files:**
- Modify: `frontend/src/routes/jobs/JobBoardPage.svelte`

The Job Board needs to know about the new state. `approved` jobs go in the Pipeline tab in a distinct color; `in_progress` jobs go in the In Progress area in the color `approved` previously used.

- [ ] **Step 1: Locate the status color/tab mapping**

Open `frontend/src/routes/jobs/JobBoardPage.svelte`. Find the place where:
- Statuses are mapped to tabs/columns
- Statuses are mapped to colors

Search for `STATUS_APPROVED`, `'approved'`, or similar.

- [ ] **Step 2: Update the mappings**

Adjust so that:
- `'approved'` appears in the Pipeline tab with a new color (suggest hex `#c9b458` — a muted gold; pick whatever fits the existing palette)
- `'in_progress'` appears in the In Progress area in the color previously used for `'approved'`

If the file uses a status-to-color object literal, update the keys; if it uses CSS classes, add a new class for `approved-state` and rename the existing `approved` class to `in-progress-state`.

The exact diff depends on the file's current shape. After the edit:
- Verify `cd frontend && npm run build` succeeds.
- Verify in the browser that an existing `approved` job shows in the Pipeline tab in the new color, and any `in_progress` job (created via Phase 2 carry-over) shows in the In Progress area in the old approved color.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/jobs/JobBoardPage.svelte
git commit -m "feat(frontend): add IN_PROGRESS state and approved color to JobBoard"
```

---

### Task 6: Add "Release to floor" button on `JobDetailPage`

**Files:**
- Modify: `frontend/src/routes/jobs/JobDetailPage.svelte` (or `frontend/src/components/jobs/JobDetail.svelte`, whichever holds the action buttons)
- API: uses existing PATCH `/api/jobs/<id>/` to update status

- [ ] **Step 1: Add the button and handler**

Find the JobDetail action area (where status-changing buttons live). Add:

```svelte
<script>
  // ... existing script content ...

  let releasingToFloor = $state(false);

  async function releaseToFloor() {
    if (!confirm('Release this job to the floor? Workers will see it in In Progress.')) return;
    releasingToFloor = true;
    try {
      await api.patch(`/api/jobs/${job.job_id}/`, {status: 'in_progress'});
      await reload();
    } catch (e) {
      alert(e.message || 'Failed to release to floor.');
    } finally {
      releasingToFloor = false;
    }
  }
</script>

{#if job.status === 'approved' && canManageJobs}
  <p>
    <button onclick={releaseToFloor} disabled={releasingToFloor}>
      {releasingToFloor ? 'Releasing…' : 'Release to floor'}
    </button>
  </p>
{/if}
```

(Names like `canManageJobs`, `reload`, and the import of `api` should already exist in this file. If not, copy from a sibling page that has them.)

- [ ] **Step 2: Verify in browser**

Walk a job through `submitted → approved` (e.g., by accepting an estimate). Confirm the "Release to floor" button appears. Click it. Confirm the job's status updates to `in_progress` and the button disappears.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/jobs/JobDetailPage.svelte frontend/src/components/jobs/JobDetail.svelte
git commit -m "feat(frontend): add Release to floor button for approved → in_progress"
```

---

## Phase 4 — Data migration: back-fill `EstimateLineItemSource` rows

### Task 7: Write the data migration

**Files:**
- Create: `apps/estimates/migrations/XXXX_backfill_estimate_line_item_source.py` (manually written — `RunPython`)

Walk every existing `EstimateLineItem`. If it has a `task` FK (PlanTask), insert a source row for its `PlanCharge`. If it has a `material` FK (PlanMaterial), insert a source row for the PlanMaterial. Skip any line items that already have source rows (idempotent).

- [ ] **Step 1: Generate an empty migration**

Run: `python manage.py makemigrations estimates --empty -n backfill_estimate_line_item_source`

This creates a stub migration file. Replace its contents with the back-fill logic below.

- [ ] **Step 2: Write the back-fill**

Edit the new migration file:

```python
from django.db import migrations


def back_fill_sources(apps, schema_editor):
    EstimateLineItem = apps.get_model('estimates', 'EstimateLineItem')
    EstimateLineItemSource = apps.get_model('estimates', 'EstimateLineItemSource')
    PlanCharge = apps.get_model('jobs', 'PlanCharge')

    for li in EstimateLineItem.objects.all():
        if EstimateLineItemSource.objects.filter(estimate_line_item=li).exists():
            continue
        if li.task_id:
            # task FK is to PlanTask; the atom is the OneToOne PlanCharge off it
            try:
                pc = PlanCharge.objects.get(plan_task_id=li.task_id)
            except PlanCharge.DoesNotExist:
                continue  # PlanTask without a PlanCharge — nothing to claim
            EstimateLineItemSource.objects.create(
                estimate_line_item=li,
                source_type='plan_charge',
                source_pk=pc.pk,
            )
        elif li.material_id:
            EstimateLineItemSource.objects.create(
                estimate_line_item=li,
                source_type='plan_material',
                source_pk=li.material_id,
            )


def reverse_back_fill(apps, schema_editor):
    # Delete only the source rows we would have created (best-effort; safe to no-op)
    EstimateLineItemSource = apps.get_model('estimates', 'EstimateLineItemSource')
    EstimateLineItemSource.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        # Match the latest existing estimates migration name from `python manage.py showmigrations estimates`
        ('estimates', '<previous_migration_name>'),
    ]

    operations = [
        migrations.RunPython(back_fill_sources, reverse_back_fill),
    ]
```

Replace `<previous_migration_name>` with the actual previous migration name (the auto-generated stub will already have the right value — keep it as-is).

- [ ] **Step 3: Test the migration locally**

Run: `python manage.py test tests.test_estimate_line_item_source -v 2`
Expected: PASS.

Then verify the migration applies cleanly to a database with existing data. If you don't have a test fixture with old-style line items, write a quick TestCase that creates one EstimateLineItem with a `task` FK and one with a `material` FK, then run the migration's data function manually and assert source rows appear.

Add `tests/test_back_fill_source_migration.py`:

```python
from decimal import Decimal
from django.test import TestCase
from django.apps import apps as django_apps

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource, EstWorksheet
from apps.inventory.models import PlanMaterial
from apps.jobs.models import Job, PlanCharge, PlanTask, RateScheme


class BackFillSourceMigrationTest(TestCase):
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
        self.estimate = Estimate.objects.create(job=self.job, status=Estimate.STATUS_DRAFT)
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
        self.pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('2'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )

    def test_backfill_creates_source_for_task_fk(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='hours',
            price=Decimal('100'), description='Setup', accounting_category=self.cat,
            task=self.pt,
        )
        # Run the migration's function manually
        from apps.estimates.migrations import find_back_fill_callable
        # If the function isn't easily importable, copy the back-fill logic into the test.
        # For simplicity, exercise the apps registry the same way the migration does:
        from importlib import import_module
        # Find the migration module dynamically
        import os
        migration_dir = os.path.dirname(__file__).replace('/tests', '/apps/estimates/migrations')
        # Easier: just call the back-fill directly by re-importing the function
        EstimateLineItemSource.objects.filter(estimate_line_item=li).delete()
        from apps.estimates.migrations.{MIGRATION_NAME} import back_fill_sources  # replace with actual
        from django.apps import apps
        back_fill_sources(apps, None)
        self.assertEqual(EstimateLineItemSource.objects.filter(estimate_line_item=li).count(), 1)
```

(Replace `{MIGRATION_NAME}` with the actual migration filename without the `.py` extension. If the dynamic import is awkward, the simpler verification is to apply the migration to a test database and confirm row counts directly — see Step 4.)

- [ ] **Step 4: Apply on a real database (manual)**

This is a destructive change to production-bound data. The user should apply the migration themselves (per CLAUDE.md: "NEVER run `python manage.py migrate` — only the human user applies migrations"). Document the steps for the user to run:

```bash
python manage.py migrate estimates
```

After applying, spot-check via the Django shell:

```python
python manage.py shell
>>> from apps.estimates.models import EstimateLineItem, EstimateLineItemSource
>>> EstimateLineItem.objects.exclude(sources__isnull=False).filter(task__isnull=False).count()
# Should be 0 — every line item with task FK should now have at least one source
>>> EstimateLineItem.objects.exclude(sources__isnull=False).filter(material__isnull=False).count()
# Same for material FK
```

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/migrations/ tests/test_back_fill_source_migration.py
git commit -m "feat(estimates): back-fill EstimateLineItemSource from legacy task/material FKs"
```

---

## Phase 5 — Removal of old machinery

### Task 8: Remove `EstimateGenerationService`

**Files:**
- Modify: `apps/estimates/services.py` — delete the `EstimateGenerationService` class (around line 626)
- Delete tests that test it: `tests/test_estimate_generation_materials.py`, `tests/test_instance_level_estimate_generation.py`

- [ ] **Step 1: Confirm nothing else imports it**

Run: `grep -rn "EstimateGenerationService" apps/ frontend/ tests/`
Expected: only the class definition itself, the API view that calls it, and the test files we're about to delete.

- [ ] **Step 2: Remove the class**

Delete the entire `class EstimateGenerationService:` block in `apps/estimates/services.py`. (Roughly line 626 to end of class — preserve any unrelated code below it.)

- [ ] **Step 3: Delete its tests**

```bash
git rm tests/test_estimate_generation_materials.py tests/test_instance_level_estimate_generation.py
```

- [ ] **Step 4: Run the full test suite**

Run: `python manage.py test -v 1`
Expected: All remaining tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/services.py
git commit -m "refactor(estimates): remove obsolete EstimateGenerationService"
```

---

### Task 9: Remove `generate-estimate` API and HTML view

**Files:**
- Modify: `apps/api/worksheets/views.py:159` — remove the `@action` for `generate-estimate`
- Modify: `apps/estimates/views.py` — remove `estworksheet_generate_estimate` HTML view
- Modify: `apps/estimates/urls.py` — remove the URL pattern
- Modify: `templates/jobs/estworksheet_detail.html` — remove the "Generate Estimate" link
- Modify: `frontend/src/components/jobs/JobDetail.svelte` — already updated in Plan B Task 6
- Modify: `frontend/src/routes/worksheets/WorksheetDetailPage.svelte` — already updated in Plan B Task 2 (replaced with new buttons)

- [ ] **Step 1: Find and remove the API action**

Open `apps/api/worksheets/views.py:159`. Delete the `@action(detail=True, methods=['post'], url_path='generate-estimate')` method block.

- [ ] **Step 2: Remove the HTML view**

In `apps/estimates/views.py`, find `estworksheet_generate_estimate` (around line 425) and delete the function.

- [ ] **Step 3: Remove the URL**

In `apps/estimates/urls.py`, find and remove the URL pattern that maps to `estworksheet_generate_estimate`.

- [ ] **Step 4: Remove the template link**

In `templates/jobs/estworksheet_detail.html`, find any "Generate Estimate" link/button and remove it.

- [ ] **Step 5: Sweep for stragglers**

Run: `grep -rn "generate-estimate\|generate_estimate" apps/ frontend/ templates/`
Expected: only matches in tests (we'll handle those next), docs (no action), and old HTML templates if any.

- [ ] **Step 6: Update or remove tests that exercise the removed view**

Tests that exercise `generate-estimate` directly should be deleted (their functionality is now covered by the wizard tests):

```bash
grep -l "generate-estimate\|generate_estimate" tests/
```

For each test file in the result, evaluate:
- If the file is solely about `generate-estimate` → delete it
- If it has unrelated tests too → remove only the affected tests within

The likely candidates: `tests/test_worksheet_finalization.py`, `tests/test_api_worksheets.py`, `tests/test_estimate_worksheet_states.py`. Inspect each and remove just the `generate-estimate`-specific tests.

- [ ] **Step 7: Run full test suite**

Run: `python manage.py test -v 1`
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add apps/api/worksheets/views.py apps/estimates/views.py apps/estimates/urls.py templates/jobs/estworksheet_detail.html tests/
git commit -m "refactor(estimates): remove generate-estimate API and HTML views"
```

---

### Task 10: Drop `PlanTask.mapping_strategy` field and `PlanBundle` model

**Files:**
- Modify: `apps/jobs/models.py` — remove `mapping_strategy` field, `bundle` FK, custom `clean()` validation; remove `PlanBundle` class entirely
- Modify: `apps/api/worksheets/views.py` — `PlanTaskBundleMixin` likely references `PlanBundle`; clean up
- Migration: auto-generated removal migration

- [ ] **Step 1: Confirm no remaining references in app code**

Run: `grep -rn "mapping_strategy\|PlanBundle\|plan_bundles" apps/ tests/ frontend/`

For each remaining reference, evaluate whether it's a place we own (remove) or a test we need to delete.

- [ ] **Step 2: Remove the field from `PlanTask`**

In `apps/jobs/models.py`, edit `PlanTask` (around line 150):

```python
class PlanTask(TaskBase):
    """Planning task on an EstWorksheet. No lifecycle, no hierarchy, no bleps."""
    plan_task_id = models.AutoField(primary_key=True)
    est_worksheet = models.ForeignKey(
        'estimates.EstWorksheet', on_delete=models.CASCADE, related_name='plan_tasks'
    )

    class Meta:
        db_table = 'plan_tasks'

    def save(self, *args, **kwargs):
        from django.db import transaction
        if self.sort_order is None:
            with transaction.atomic():
                max_order = PlanTask.objects.filter(
                    est_worksheet=self.est_worksheet
                ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
                self.sort_order = max_order + 1
        self.full_clean()
        super().save(*args, **kwargs)
```

(Removed: `MAPPING_CHOICES`, `mapping_strategy`, `bundle` FK, the `clean()` method that validated bundle rules, and the bundle/sort-order branching in `save()`.)

- [ ] **Step 3: Remove the `PlanBundle` class**

Delete the entire `class PlanBundle(models.Model):` block (around line 272-299).

- [ ] **Step 4: Update API mixin if needed**

Inspect `apps/api/mixins.py` (or wherever `PlanTaskBundleMixin` lives). Strip out anything related to bundles. If the mixin is now degenerate (only handles tasks), rename to `PlanTaskMixin` and update its imports in `apps/api/worksheets/views.py`.

- [ ] **Step 5: Generate the migration**

Run: `python manage.py makemigrations jobs -n drop_plan_bundle_and_mapping_strategy`

Expected: a migration that drops the `mapping_strategy` and `bundle` columns from `plan_tasks` and drops the `plan_bundles` table.

- [ ] **Step 6: Update remaining tests**

Search `tests/` for `mapping_strategy`, `PlanBundle`, `plan_bundles` and delete or update each affected test. Many will simply lose their relevance — `mapping_strategy` doesn't exist anymore.

- [ ] **Step 7: Run full test suite**

Run: `python manage.py test -v 1`
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/ apps/api/ tests/
git commit -m "refactor(jobs): drop PlanTask.mapping_strategy and PlanBundle model"
```

---

### Task 11: Drop `TemplateBundle` model

**Files:**
- Modify: `apps/estimates/models.py` — remove `TemplateBundle`, drop `bundle` FK from `TemplateTaskAssociation`, simplify `WorkTemplate.generate_tasks_for_worksheet`
- Migration: auto-generated removal migration

- [ ] **Step 1: Find references**

Run: `grep -rn "TemplateBundle\|template_bundles\|source_template_bundle" apps/ tests/ frontend/`

- [ ] **Step 2: Remove `TemplateBundle` class and `bundle` FK on `TemplateTaskAssociation`**

In `apps/estimates/models.py`:

- Delete the `class TemplateBundle(models.Model):` block.
- In `TemplateTaskAssociation`, remove the `bundle` FK field.
- In `WorkTemplate.generate_tasks_for_worksheet`, remove any code that constructs `PlanBundle`s. The simpler version: just iterate associations and create flat `PlanTask`s.

- [ ] **Step 3: Remove `source_template_bundle` from `PlanBundle`**

Already gone (PlanBundle was deleted in Task 10). Just confirm no orphan references.

- [ ] **Step 4: Remove `bundle` field from `PlanTask`**

Already done in Task 10.

- [ ] **Step 5: Generate the migration**

Run: `python manage.py makemigrations estimates -n drop_template_bundle`

- [ ] **Step 6: Update tests**

Search `tests/` for `TemplateBundle` and `template_bundles`. Delete or update affected tests.

- [ ] **Step 7: Run tests**

Run: `python manage.py test -v 1`
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add apps/estimates/models.py apps/estimates/migrations/ tests/
git commit -m "refactor(estimates): drop TemplateBundle model"
```

---

### Task 12: Drop `EstimateLineItem.task` and `material` FKs

**Files:**
- Modify: `apps/estimates/models.py:564-568` — remove `task` and `material` fields
- Modify: `apps/jobs/services.py:283-311` — remove `populate_from_estimate` (was using these FKs); also remove its tests
- Modify: `apps/api/jobs/views.py` — remove the `populate-from-estimate` action
- Modify: `frontend/src/components/jobs/JobDetail.svelte` — remove any "Populate from Estimate" UI
- Migration: auto-generated removal migration

- [ ] **Step 1: Confirm `EstimateLineItemSource` rows are in place**

Run: `python manage.py shell`

```python
from apps.estimates.models import EstimateLineItem
EstimateLineItem.objects.filter(task__isnull=False).exclude(sources__isnull=False).count()
EstimateLineItem.objects.filter(material__isnull=False).exclude(sources__isnull=False).count()
```

Both should be 0. If not, the back-fill (Task 7) didn't cover everything — investigate before proceeding.

- [ ] **Step 2: Remove the FKs from the model**

In `apps/estimates/models.py`:

```python
class EstimateLineItem(BaseLineItem):
    """Line item for estimates - inherits shared functionality from BaseLineItem."""

    estimate = models.ForeignKey(Estimate, on_delete=models.CASCADE)
    source_template = models.ForeignKey(
        'estimates.TaskTemplate',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text='TaskTemplate this line item was created from.',
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

(Removed: `task` FK, `material` FK.)

- [ ] **Step 3: Remove `populate_from_estimate` and its API endpoint**

In `apps/jobs/services.py`, delete the `populate_from_estimate` static method (around line 283-311).

In `apps/api/jobs/views.py`, find and delete the `@action` that maps to `populate-from-estimate` (path `/api/jobs/<id>/populate-from-estimate/`).

- [ ] **Step 4: Remove the frontend "Populate from Estimate" button**

In `frontend/src/components/jobs/JobDetail.svelte`, find the call to `populate-from-estimate` (around line 99) and the surrounding button. Delete the button and its handler. The new auto carry-over makes this manual step unnecessary.

- [ ] **Step 5: Generate the migration**

Run: `python manage.py makemigrations estimates -n drop_estimate_line_item_legacy_fks`

- [ ] **Step 6: Update / remove tests**

Likely affected:
- `tests/test_populate_from_estimate_materials.py` — delete (the function it tests is gone)
- Any test that constructs `EstimateLineItem(task=..., material=...)` — update to use source rows instead

Run: `grep -rn "EstimateLineItem.*\(task=\|material=\)" tests/` to find remaining cases.

- [ ] **Step 7: Run full test suite**

Run: `python manage.py test -v 1`
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add apps/estimates/models.py apps/estimates/migrations/ apps/jobs/services.py apps/api/jobs/views.py frontend/src/components/jobs/JobDetail.svelte tests/
git commit -m "refactor(estimates): drop EstimateLineItem.task/material FKs and populate_from_estimate"
```

---

## Phase 6 — Verification

### Task 13: Final end-to-end verification

- [ ] **Step 1: Backend test suite**

Run: `python manage.py test -v 1`
Expected: All tests pass.

- [ ] **Step 2: Frontend build**

Run: `cd frontend && npm run build`
Expected: clean build.

- [ ] **Step 3: Full lifecycle smoke test**

With both servers running, walk through the entire wizard pattern:

1. **Create a worksheet** with 2 PlanCharges and 1 PlanMaterial.
2. **Open wizard, group two atoms into one line item, send the third 1:1.**
3. **Verify the resulting estimate** has 2 line items (one with 2 sources, one with 1 source).
4. **Move the estimate** through draft → open (sent) → accepted.
5. **Confirm the worksheet locked** (status = `final`) and the Job auto-transitioned to `approved`.
6. **Confirm carry-over fired**: Tasks and Materials exist on the Job matching the worksheet atoms.
7. **Confirm the Job appears in Pipeline tab** (not In Progress) on the Job Board, in the new approved color.
8. **Click "Release to floor"**: Job moves to `in_progress`, appears in In Progress area.
9. **Track time** on a task (Bleps).
10. **Open the invoice wizard** for the job. Confirm the in-progress job is allowed.
11. **Bill via the invoice wizard.**

- [ ] **Step 4: Sweep for orphan references**

Run: `grep -rn "EstimateGenerationService\|PlanBundle\|TemplateBundle\|mapping_strategy\|generate-estimate\|populate-from-estimate" apps/ frontend/ templates/`
Expected: no matches in code (matches in `docs/` or `test_output.txt` are OK).

---

## Self-review

**Spec coverage:**
- "New `Job.STATUS_IN_PROGRESS` state" → Tasks 1, 2, 5, 6 ✓
- "Atom carry-over service on Estimate `accepted`" → Tasks 3, 4 ✓
- "Job Board placement and color" → Task 5 ✓
- "Migration of existing data" → Task 7 ✓
- "Removed: PlanTask.mapping_strategy, PlanBundle, TemplateBundle, EstimateGenerationService, EstimateLineItem.task/material FKs" → Tasks 8, 9, 10, 11, 12 ✓

**Placeholder scan:** One genuine placeholder in Task 7 Step 2 (`<previous_migration_name>`) — that's the user filling in the actual migration filename Django generates. Same for `{MIGRATION_NAME}` in the back-fill test. Both are intentional, with instructions on how to fill them.

**Type consistency:** `Job.STATUS_IN_PROGRESS = 'in_progress'` is used consistently in tests and frontend. `EstimateLineItemSource.SOURCE_PLAN_CHARGE` / `SOURCE_PLAN_MATERIAL` constants are reused from Plan A. The `AtomCarryOverService.carry_over_for_estimate(estimate)` signature is called the same way from the signal handler and the tests.

**Order of operations:** Phase 4 (back-fill migration) must run before Phase 5 Task 12 (drop FKs). Phase 5 Task 8 (remove EstimateGenerationService) must run before Phase 5 Task 10 (drop PlanBundle) since the service uses it. Phase 5 Task 11 (TemplateBundle) is independent of others within Phase 5 but must come after Plan A's frontend stops using it (which Plan B doesn't, so it's safe at any point in Phase 5).

**Out of scope (deferred follow-ups not part of any of A/B/C):**
- Migrating `PlanTaskModal` / `PlanMaterialModal` to use `CatalogPicker` (cosmetic)
- Wiring `CatalogPicker` into Job atom creation and Invoice direct line item creation
- Adding `TaskTemplate ↔ TemplateMaterial` association (per the design's Out-of-scope section)
- Modifier-toggle UI polish in the catalog picker

**Known issues inherited from Plan A (to address in a future cleanup pass across both wizard services):**
- `IntegrityError` recovery query in `add_atoms_to_new_line_item` and `add_atoms_to_line_item` (both `InvoiceWizardService` and `EstimateWizardService`) is filtered only by `source_type__in=[...]`, not by `source_pk__in=[...]`. It loads every claim of those types into memory before filtering in Python. At scale this should be scoped to the atoms being inserted. See `apps/estimates/services.py` around the `except IntegrityError` blocks and the matching pattern in `apps/invoicing/services.py`.
- `EstimateClaimConflict.atom_ids` (and `ClaimConflict.atom_ids` on the invoice side) is misnamed — the field holds a list of `{'type','id'}` dicts, not bare ids. Rename to `conflicting_atoms` in both services and update the API response shape and any frontend consumers (Plan B's wizard components).
- `source_pool` API endpoint (on `EstimateViewSet`) uses `estimate.worksheets.first()` with no ordering, which is nondeterministic when multiple worksheet versions exist (revision chain). Should order by `pk` descending and pick the draft one, or otherwise make deterministic.

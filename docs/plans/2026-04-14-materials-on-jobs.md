# Materials-on-Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow `Material` / `PlanMaterial` to attach directly to a `Job` / `EstWorksheet` without a `Task` / `PlanTask`; add a new `TemplateMaterial` model; route all earmark mutations through a single service helper; add Consume / Restock / Draw-more ops with a new `consumption_state`; unify expense-born materials into the earmark pipeline.

**Architecture:** Add required `Material.job` and `PlanMaterial.est_worksheet` FKs; make `Material.task` / `PlanMaterial.plan_task` nullable. Introduce `MaterialService` in `apps/inventory/services.py` (`create_on_job`, `consume`, `restock`, `draw_more`) and one private `InventoryService._mutate_earmark` helper that becomes the sole `Earmark` writer. No Django signals — explicit service calls only. Add `TemplateMaterial` on `WorkTemplate` plus `generate_materials_for_worksheet` / `generate_materials_for_job`. Rewire `ExpenseService.submit` / `reject`, `JobService.copy_from_worksheet` / `populate_from_*`, `EstimateGenerationService.generate_estimate_from_worksheet`, and `InvoiceWizardService.get_source_pool`. Two-phase migration (additive + constraint-tighten) with a RunPython backfill that also cleans up placeholder "Materials" tasks.

**Tech Stack:** Django 5.2+, Django REST Framework, MySQL.

**Design spec:** `docs/designs/2026-04-14-materials-on-jobs-design.md`

**Prerequisites:**
- Existing `Material`, `PlanMaterial`, `Earmark`, `WorkTemplate`, `Job`, `EstWorksheet`, `Expense` models (see design doc "Current state").
- `InventoryService.create_earmarks_for_job`, `consume_material`, `receive_po_line_item` (`apps/inventory/services.py:251`, `:60`, `:38`).
- `ExpenseService.find_or_create_materials_task` (`apps/expenses/services.py:145`) — target for removal.
- `Expense.material` FK (`apps/expenses/models.py:48-52`, `on_delete=SET_NULL`, reverse `Material.expenses`).
- `JobService.copy_from_worksheet`, `populate_from_estimate`, `populate_from_template` (`apps/jobs/services.py:261-349`).
- `InvoiceWizardService.get_source_pool`, `_atom_computed_amount` (`apps/invoicing/services.py:200`, `:320`).
- `EstimateGenerationService.generate_estimate_from_worksheet`, `_create_material_line_item` (`apps/estimates/services.py:641`, `:755`).
- Permission classes `CanManageConfig` (`apps/api/permissions.py`).

---

## Testing discipline

- **TDD throughout.** Every code task follows: write failing test → run & verify the failure reason → write minimal implementation → run & verify pass → commit.
- **Never run `python manage.py migrate`** — only the human applies migrations. Use `makemigrations`; the Django test runner creates its own test DB.
- **Never run `python manage.py test` from multiple subagents in parallel.** Shared MySQL test DB will deadlock.
- **Test data:** use fixtures via `tests.base.FixtureTestCase`, or construct rows inline in a `BaseTestCase` subclass when a narrower setup reads more clearly.
- **No Django signals** are introduced by this work. Tests should read like linear service calls.

---

## File structure

```
apps/inventory/
├── models.py                    # MODIFY: Material, PlanMaterial; ADD TemplateMaterial
├── services.py                  # MODIFY: add MaterialService, _mutate_earmark,
│                                #         receive_ad_hoc_purchase, reverse_ad_hoc_purchase
└── migrations/
    ├── 00XX_material_job_plan_worksheet_additive.py    # NEW
    └── 00XY_material_constraints_tighten.py            # NEW

apps/expenses/services.py        # MODIFY: ExpenseService.submit, .reject

apps/estimates/
├── models.py                    # MODIFY: WorkTemplate — add generate_materials_for_worksheet
│                                #                        and generate_materials_for_job
└── services.py                  # MODIFY: generate_estimate_from_worksheet (task-less PMs)

apps/jobs/
├── services.py                  # MODIFY: JobService.copy_from_worksheet,
│                                #         populate_from_estimate, populate_from_template,
│                                #         work_complete gate
└── models.py                    # MODIFY: Job (only if gate lives on the model; see Task 19)

apps/invoicing/services.py       # MODIFY: InvoiceWizardService.get_source_pool,
                                 #         _atom_computed_amount

apps/api/
├── inventory/
│   ├── views.py                 # MODIFY: add MaterialViewSet (actions), register
│   ├── serializers.py           # MODIFY: add MaterialSerializer, MaterialOpSerializer
│   └── urls.py                  # (if separate) — or register in apps/api/urls.py
├── jobs/
│   └── views.py                 # MODIFY: JobViewSet — add materials action
├── estimates/
│   └── views.py                 # MODIFY: EstWorksheetViewSet — plan-materials accepts
│                                #         optional plan_task
├── worktemplates/ (or estimates/)
│   └── views.py                 # MODIFY: add TemplateMaterial CRUD
└── urls.py                      # MODIFY: register material routes

tests/                           # NEW + MODIFIED test files (see "Testing strategy")
```

---

## Phase 0 — Orientation

### Task 0: Read the design doc end-to-end

**Files:** (read-only) `docs/designs/2026-04-14-materials-on-jobs-design.md`

- [ ] **Step 1: Read the full design.** Pay attention to the state-machine table, the `_mutate_earmark` caller table, the migration plan, and the "What's gone compared to earlier drafts" section. No code changes in this task.

---

## Phase 1 — Schema additions (additive migration)

Goal: add the new fields / model without yet breaking existing code. Old code keeps working because `Material.task` and `PlanMaterial.plan_task` remain required for now.

### Task 1: Add `Material.job` (nullable), `consumption_state`, `restocked_qty`

**Files:**
- Modify: `apps/inventory/models.py` (Material class, ~line 152)
- Test: `tests/test_material_fields.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_material_fields.py
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import Job, Task
from apps.inventory.models import Material, PriceListItem
from apps.core.models import AccountingCategory


class MaterialFieldsTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='labor')
        self.job = Job.objects.create(job_number='JOB-TEST-1')
        self.task = Task.objects.create(job=self.job, name='t')

    def test_material_has_job_consumption_state_restocked_qty(self):
        m = Material.objects.create(
            task=self.task, job=self.job,
            description='x', quantity=Decimal('2.00'),
        )
        self.assertEqual(m.job_id, self.job.pk)
        self.assertEqual(m.consumption_state, 'na')
        self.assertEqual(m.restocked_qty, Decimal('0.00'))

    def test_material_effective_qty(self):
        m = Material.objects.create(
            task=self.task, job=self.job,
            description='x', quantity=Decimal('5.00'),
        )
        m.restocked_qty = Decimal('2.00')
        m.save()
        self.assertEqual(m.effective_qty, Decimal('3.00'))
```

- [ ] **Step 2: Run test, verify failure**

Run: `python manage.py test tests.test_material_fields -v 2`
Expected: FAIL — `Material() got unexpected keyword 'job'` (or missing field / attribute).

- [ ] **Step 3: Add the fields on `Material`**

In `apps/inventory/models.py`, edit the `Material` class:

```python
class Material(MaterialBase):
    """Actual material on a Job; optionally attached to a Task. Participates in earmark/QOH flows."""
    CONSUMPTION_STATE_NA = 'na'
    CONSUMPTION_STATE_PENDING = 'pending'
    CONSUMPTION_STATE_CONSUMED = 'consumed'
    CONSUMPTION_STATE_CHOICES = [
        (CONSUMPTION_STATE_NA, 'N/A'),
        (CONSUMPTION_STATE_PENDING, 'Pending'),
        (CONSUMPTION_STATE_CONSUMED, 'Consumed'),
    ]

    material_id = models.AutoField(primary_key=True)
    task = models.ForeignKey(
        'jobs.Task', on_delete=models.CASCADE, related_name='materials'
    )
    job = models.ForeignKey(
        'jobs.Job', on_delete=models.CASCADE, related_name='materials',
        null=True, blank=True,  # nullable during additive phase; tightened in Task 22
    )
    consumption_state = models.CharField(
        max_length=20, choices=CONSUMPTION_STATE_CHOICES,
        default=CONSUMPTION_STATE_NA,
    )
    restocked_qty = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
    )

    class Meta:
        db_table = 'materials'

    @property
    def effective_qty(self):
        return self.quantity - self.restocked_qty

    @property
    def is_expense_bound(self):
        return self.expenses.exists()

    def clean(self):
        super().clean()
        if self.task_id and self.job_id and self.task.job_id != self.job_id:
            from django.core.exceptions import ValidationError
            raise ValidationError('Material.task.job must match Material.job')
        if self.restocked_qty < Decimal('0.00') or self.restocked_qty > self.quantity:
            from django.core.exceptions import ValidationError
            raise ValidationError('restocked_qty must be between 0 and quantity')

    def save(self, *args, **kwargs):
        self._populate_from_pli()
        if not self.pk and self.price_list_item and self.price_list_item.is_inventoried:
            if self.consumption_state == self.CONSUMPTION_STATE_NA:
                self.consumption_state = self.CONSUMPTION_STATE_PENDING
        self.full_clean()
        super().save(*args, **kwargs)
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations inventory --name material_job_plan_worksheet_additive`

Do **not** run `migrate`.

- [ ] **Step 5: Run the test, verify pass**

Run: `python manage.py test tests.test_material_fields -v 2`
Expected: PASS (test DB is built fresh from migrations).

- [ ] **Step 6: Commit**

```bash
git add apps/inventory/models.py apps/inventory/migrations tests/test_material_fields.py
git commit -m "feat(inventory): add Material.job, consumption_state, restocked_qty (nullable phase)"
```

---

### Task 2: Add `PlanMaterial.est_worksheet` (nullable)

**Files:**
- Modify: `apps/inventory/models.py` (PlanMaterial class)
- Test: `tests/test_material_fields.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_material_fields.py`:

```python
from apps.estimates.models import EstWorksheet
from apps.jobs.models import PlanTask
from apps.inventory.models import PlanMaterial


class PlanMaterialFieldsTest(TestCase):
    def setUp(self):
        self.job = Job.objects.create(job_number='JOB-PM-1')
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.pt = PlanTask.objects.create(est_worksheet=self.ws, name='pt')

    def test_plan_material_has_est_worksheet(self):
        pm = PlanMaterial.objects.create(
            plan_task=self.pt, est_worksheet=self.ws,
            description='x', quantity=Decimal('1.00'),
        )
        self.assertEqual(pm.est_worksheet_id, self.ws.pk)

    def test_plan_material_invariant_rejects_mismatched_ws(self):
        from django.core.exceptions import ValidationError
        other_job = Job.objects.create(job_number='JOB-PM-2')
        other_ws = EstWorksheet.objects.create(job=other_job)
        with self.assertRaises(ValidationError):
            PlanMaterial.objects.create(
                plan_task=self.pt, est_worksheet=other_ws,
                description='x', quantity=Decimal('1.00'),
            )
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_material_fields.PlanMaterialFieldsTest -v 2`
Expected: FAIL — unexpected kwarg `est_worksheet`.

- [ ] **Step 3: Edit `PlanMaterial`**

```python
class PlanMaterial(MaterialBase):
    """Planning material on a Worksheet; optionally attached to a PlanTask. No inventory side effects."""
    plan_material_id = models.AutoField(primary_key=True)
    plan_task = models.ForeignKey(
        'jobs.PlanTask', on_delete=models.CASCADE, related_name='plan_materials'
    )
    est_worksheet = models.ForeignKey(
        'estimates.EstWorksheet', on_delete=models.CASCADE, related_name='plan_materials',
        null=True, blank=True,  # nullable during additive phase; tightened in Task 22
    )

    class Meta:
        db_table = 'plan_materials'

    def clean(self):
        super().clean()
        if self.plan_task_id and self.est_worksheet_id and (
            self.plan_task.est_worksheet_id != self.est_worksheet_id
        ):
            from django.core.exceptions import ValidationError
            raise ValidationError('plan_task.est_worksheet must match est_worksheet')

    def save(self, *args, **kwargs):
        self._populate_from_pli()
        self.full_clean()
        super().save(*args, **kwargs)
```

- [ ] **Step 4: Regenerate migration**

Run: `python manage.py makemigrations inventory`
Expected: a follow-up migration, **or** (preferred) squash into the Task 1 migration by deleting that migration first (since it hasn't been applied) and re-running `makemigrations --name material_job_plan_worksheet_additive`.

Squash approach (preferred — migrations not yet applied):
```bash
rm apps/inventory/migrations/00XX_material_job_plan_worksheet_additive.py
python manage.py makemigrations inventory --name material_job_plan_worksheet_additive
```

- [ ] **Step 5: Run the test, verify pass**

Run: `python manage.py test tests.test_material_fields -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/inventory/models.py apps/inventory/migrations tests/test_material_fields.py
git commit -m "feat(inventory): add PlanMaterial.est_worksheet (nullable phase) + invariant"
```

---

### Task 3: Add `TemplateMaterial` model

**Files:**
- Modify: `apps/inventory/models.py`
- Test: `tests/test_template_materials.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_template_materials.py
from decimal import Decimal
from django.test import TestCase
from apps.estimates.models import WorkTemplate
from apps.inventory.models import TemplateMaterial


class TemplateMaterialTest(TestCase):
    def test_create_template_material(self):
        wt = WorkTemplate.objects.create(
            template_name='widget', base_price=Decimal('0.00'), is_active=True,
        )
        tm = TemplateMaterial.objects.create(
            work_template=wt, description='screws', quantity=Decimal('10.00'),
        )
        self.assertEqual(list(wt.materials.all()), [tm])
        self.assertEqual(tm.sort_order, 0)

    def test_template_material_all_material_fields_optional(self):
        wt = WorkTemplate.objects.create(
            template_name='blank', base_price=Decimal('0.00'), is_active=True,
        )
        tm = TemplateMaterial.objects.create(work_template=wt)  # totally freeform
        self.assertEqual(tm.quantity, Decimal('0.00'))
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_template_materials -v 2`
Expected: FAIL — `TemplateMaterial` not defined.

- [ ] **Step 3: Add the model**

At the end of `apps/inventory/models.py`:

```python
class TemplateMaterial(MaterialBase):
    """Template-level material on a WorkTemplate. Populated as task-less PlanMaterial
    (on EstWorksheet) or task-less Material (on Job)."""
    template_material_id = models.AutoField(primary_key=True)
    work_template = models.ForeignKey(
        'estimates.WorkTemplate', on_delete=models.CASCADE,
        related_name='materials',
    )
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'template_materials'
        ordering = ['sort_order']

    def save(self, *args, **kwargs):
        self._populate_from_pli()
        self.full_clean()
        super().save(*args, **kwargs)
```

- [ ] **Step 4: Migration**

Run: `python manage.py makemigrations inventory`
Squash into the additive migration the same way as Task 2 (delete + re-run) so we end up with exactly one "additive" migration file.

- [ ] **Step 5: Run the test, verify pass**

Run: `python manage.py test tests.test_template_materials -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/inventory/models.py apps/inventory/migrations tests/test_template_materials.py
git commit -m "feat(inventory): add TemplateMaterial model on WorkTemplate"
```

---

## Phase 2 — `InventoryService._mutate_earmark` and `MaterialService.create_on_job`

Goal: single Earmark-writer helper, plus the sole Material-creation entry point. Nothing is rewired to use them yet — existing call sites still work.

### Task 4: `InventoryService._mutate_earmark`

**Files:**
- Modify: `apps/inventory/services.py`
- Test: `tests/test_mutate_earmark.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_mutate_earmark.py
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import Job
from apps.inventory.models import Earmark, PriceListItem
from apps.inventory.services import InventoryService
from apps.core.models import AccountingCategory


class MutateEarmarkTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c')
        self.job = Job.objects.create(job_number='JOB-E-1')
        self.pli = PriceListItem.objects.create(
            code='A', accounting_category=self.cat, is_inventoried=True,
        )
        self.noninv = PriceListItem.objects.create(
            code='B', accounting_category=self.cat, is_inventoried=False,
        )

    def test_positive_delta_creates_earmark(self):
        InventoryService._mutate_earmark(self.pli, self.job, Decimal('3'))
        e = Earmark.objects.get(price_list_item=self.pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('3'))

    def test_positive_delta_increments_existing(self):
        Earmark.objects.create(price_list_item=self.pli, job=self.job, quantity=Decimal('2'))
        InventoryService._mutate_earmark(self.pli, self.job, Decimal('3'))
        e = Earmark.objects.get(price_list_item=self.pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('5'))

    def test_negative_delta_shrinks(self):
        Earmark.objects.create(price_list_item=self.pli, job=self.job, quantity=Decimal('5'))
        InventoryService._mutate_earmark(self.pli, self.job, Decimal('-2'))
        e = Earmark.objects.get(price_list_item=self.pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('3'))

    def test_negative_delta_to_zero_deletes(self):
        Earmark.objects.create(price_list_item=self.pli, job=self.job, quantity=Decimal('2'))
        InventoryService._mutate_earmark(self.pli, self.job, Decimal('-2'))
        self.assertFalse(
            Earmark.objects.filter(price_list_item=self.pli, job=self.job).exists()
        )

    def test_noop_for_noninventoried_pli(self):
        InventoryService._mutate_earmark(self.noninv, self.job, Decimal('3'))
        self.assertFalse(Earmark.objects.exists())

    def test_noop_for_none_pli(self):
        InventoryService._mutate_earmark(None, self.job, Decimal('3'))
        self.assertFalse(Earmark.objects.exists())
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_mutate_earmark -v 2`
Expected: FAIL — `_mutate_earmark` does not exist.

- [ ] **Step 3: Implement `_mutate_earmark`**

In `apps/inventory/services.py` inside `InventoryService`:

```python
    @staticmethod
    def _mutate_earmark(pli, job, delta):
        """Apply `delta` to the (pli, job) Earmark. Upsert if positive net, delete if zero.
        No-op if pli is None or not inventoried. Sole writer of Earmark rows."""
        if pli is None or not pli.is_inventoried:
            return
        try:
            earmark = Earmark.objects.get(price_list_item=pli, job=job)
        except Earmark.DoesNotExist:
            if delta > Decimal('0.00'):
                Earmark.objects.create(price_list_item=pli, job=job, quantity=delta)
            return
        new_qty = earmark.quantity + delta
        if new_qty <= Decimal('0.00'):
            earmark.delete()
        else:
            earmark.quantity = new_qty
            earmark.save(update_fields=['quantity'])
```

- [ ] **Step 4: Run, verify pass**

Run: `python manage.py test tests.test_mutate_earmark -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/services.py tests/test_mutate_earmark.py
git commit -m "feat(inventory): add InventoryService._mutate_earmark (sole Earmark writer)"
```

---

### Task 5: `MaterialService.create_on_job`

**Files:**
- Modify: `apps/inventory/services.py` (new `MaterialService` class)
- Test: `tests/test_material_service_create.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_material_service_create.py
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import Job, Task
from apps.inventory.models import Material, Earmark, PriceListItem
from apps.inventory.services import MaterialService
from apps.core.models import AccountingCategory


class MaterialServiceCreateOnJobTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c')
        self.job = Job.objects.create(job_number='JOB-MS-1')
        self.pli_inv = PriceListItem.objects.create(
            code='I', accounting_category=self.cat, is_inventoried=True,
        )
        self.pli_noninv = PriceListItem.objects.create(
            code='N', accounting_category=self.cat, is_inventoried=False,
        )

    def test_create_taskless_inventoried_upserts_earmark(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('4.00'),
            price_list_item=self.pli_inv,
        )
        self.assertIsNone(m.task_id)
        self.assertEqual(m.job_id, self.job.pk)
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        e = Earmark.objects.get(price_list_item=self.pli_inv, job=self.job)
        self.assertEqual(e.quantity, Decimal('4.00'))

    def test_create_taskless_noninventoried_no_earmark(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('4.00'),
            price_list_item=self.pli_noninv,
        )
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_NA)
        self.assertFalse(Earmark.objects.exists())

    def test_create_task_attached_invariant_enforced(self):
        other = Job.objects.create(job_number='JOB-MS-2')
        t = Task.objects.create(job=other, name='t')
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            MaterialService.create_on_job(
                job=self.job, task=t,
                description='x', quantity=Decimal('1.00'),
            )

    def test_create_task_attached_inventoried_upserts_earmark(self):
        t = Task.objects.create(job=self.job, name='t')
        MaterialService.create_on_job(
            job=self.job, task=t, description='x', quantity=Decimal('2.00'),
            price_list_item=self.pli_inv,
        )
        e = Earmark.objects.get(price_list_item=self.pli_inv, job=self.job)
        self.assertEqual(e.quantity, Decimal('2.00'))
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_material_service_create -v 2`
Expected: FAIL — `MaterialService` not defined.

- [ ] **Step 3: Implement `MaterialService.create_on_job`**

At the bottom of `apps/inventory/services.py`:

```python
class MaterialService:
    """Sole entry point for Material row creation and lifecycle ops.
    All earmark mutations go through InventoryService._mutate_earmark."""

    @staticmethod
    def create_on_job(*, job, task=None, description='', quantity=Decimal('0.00'),
                      unit_cost=Decimal('0.00'), sell_price=Decimal('0.00'),
                      price_list_item=None, accounting_category=None):
        from django.db import transaction
        with transaction.atomic():
            m = Material(
                job=job, task=task,
                description=description, quantity=quantity,
                unit_cost=unit_cost, sell_price=sell_price,
                price_list_item=price_list_item,
                accounting_category=accounting_category,
            )
            m.save()  # full_clean() runs here; enforces task/job invariant
            InventoryService._mutate_earmark(price_list_item, job, quantity)
        return m
```

- [ ] **Step 4: Run, verify pass**

Run: `python manage.py test tests.test_material_service_create -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/services.py tests/test_material_service_create.py
git commit -m "feat(inventory): add MaterialService.create_on_job"
```

---

### Task 6: Fold `InventoryService.receive_po_line_item` onto `_mutate_earmark`

**Files:**
- Modify: `apps/inventory/services.py` (lines ~38–57)
- Test: existing `tests/test_earmark_flow.py` + a new assertion

- [ ] **Step 1: Write a failing focused test**

Create `tests/test_receive_po_uses_mutate_earmark.py`:

```python
from unittest.mock import patch
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import Job
from apps.inventory.models import PriceListItem, Earmark
from apps.inventory.services import InventoryService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory


class ReceivePoLineItemUsesMutateEarmarkTest(TestCase):
    def test_receive_po_line_item_routes_through_mutate_earmark(self):
        cat = AccountingCategory.objects.create(name='c')
        pli = PriceListItem.objects.create(
            code='P', accounting_category=cat, is_inventoried=True,
        )
        biz = Business.objects.create(business_name='Acme')
        vend = Contact.objects.create(first_name='V', last_name='Ndr', business=biz)
        job = Job.objects.create(job_number='JOB-RP-1')
        po = PurchaseOrder.objects.create(vendor=vend, po_number='PO-1')
        pli_line = PurchaseOrderLineItem.objects.create(
            purchase_order=po, price_list_item=pli, qty=Decimal('5'),
            job=job, description='x',
        )
        with patch.object(InventoryService, '_mutate_earmark') as m:
            InventoryService.receive_po_line_item(pli_line)
            m.assert_called_once_with(pli, job, Decimal('5'))
```

(If `PurchaseOrderLineItem` field names differ, adapt to real fields — line numbers in design doc reference the existing implementation.)

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_receive_po_uses_mutate_earmark -v 2`
Expected: FAIL — `_mutate_earmark` not called.

- [ ] **Step 3: Edit `receive_po_line_item`**

Replace the `Earmark.objects.get_or_create` / `F('quantity') + qty` block with:

```python
        if po_line_item.job:
            InventoryService._mutate_earmark(pli, po_line_item.job, po_line_item.qty)
```

- [ ] **Step 4: Run, verify pass**

Run:
```
python manage.py test tests.test_receive_po_uses_mutate_earmark tests.test_earmark_flow tests.test_earmark tests.test_auto_earmark -v 2
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/services.py tests/test_receive_po_uses_mutate_earmark.py
git commit -m "refactor(inventory): receive_po_line_item routes earmark write through _mutate_earmark"
```

---

## Phase 3 — Material ops (Consume / Restock / Draw more)

### Task 7: `MaterialService.consume`

**Files:**
- Modify: `apps/inventory/services.py`
- Test: `tests/test_material_ops.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_material_ops.py
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.jobs.models import Job
from apps.inventory.models import Material, Earmark, PriceListItem
from apps.inventory.services import InventoryService, MaterialService
from apps.core.models import AccountingCategory


class ConsumeTest(TestCase):
    def setUp(self):
        cat = AccountingCategory.objects.create(name='c')
        self.job = Job.objects.create(job_number='JOB-C-1')
        self.pli = PriceListItem.objects.create(
            code='I', accounting_category=cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )

    def test_consume_inventoried_updates_qoh_sold_earmark_state(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('4'),
            price_list_item=self.pli,
        )
        MaterialService.consume(m)
        m.refresh_from_db()
        self.pli.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)
        self.assertEqual(self.pli.qty_on_hand, Decimal('6'))
        self.assertEqual(self.pli.qty_sold, Decimal('4'))
        self.assertFalse(
            Earmark.objects.filter(price_list_item=self.pli, job=self.job).exists()
        )

    def test_consume_requires_pending(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('2'),
            price_list_item=self.pli,
        )
        MaterialService.consume(m)
        with self.assertRaises(ValidationError):
            MaterialService.consume(m)  # already consumed

    def test_consume_uses_effective_qty(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('5'),
            price_list_item=self.pli,
        )
        MaterialService.restock(m, Decimal('2'))
        MaterialService.consume(m)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_sold, Decimal('3'))
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_material_ops.ConsumeTest -v 2`
Expected: FAIL — `consume` / `restock` not defined.

- [ ] **Step 3: Implement `consume` (and a stub `restock` good enough for the effective_qty test)**

Add to `MaterialService`:

```python
    @staticmethod
    def consume(material):
        from django.db import transaction
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError(
                f'consume requires pending state; got {material.consumption_state}'
            )
        eff = material.effective_qty
        if eff <= Decimal('0.00'):
            return material  # nothing left to consume
        with transaction.atomic():
            pli = material.price_list_item
            if pli and pli.is_inventoried:
                from django.db.models import F
                pli.qty_on_hand = F('qty_on_hand') - eff
                pli.qty_sold = F('qty_sold') + eff
                pli.save(update_fields=['qty_on_hand', 'qty_sold'])
                pli.refresh_from_db()
                InventoryService._mutate_earmark(pli, material.job, -eff)
            material.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
            material.save(update_fields=['consumption_state'])
        return material
```

(Stub `restock` implemented in Task 8.)

- [ ] **Step 4: Run, verify pass (after Task 8's restock is done)**

Keep the `test_consume_uses_effective_qty` test marked as expected-pass — it depends on Task 8. For now run:
```
python manage.py test tests.test_material_ops.ConsumeTest.test_consume_inventoried_updates_qoh_sold_earmark_state tests.test_material_ops.ConsumeTest.test_consume_requires_pending -v 2
```
Expected: PASS on these two.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/services.py tests/test_material_ops.py
git commit -m "feat(inventory): MaterialService.consume"
```

---

### Task 8: `MaterialService.restock`

**Files:**
- Modify: `apps/inventory/services.py`
- Test: `tests/test_material_ops.py` (extend)

- [ ] **Step 1: Write failing tests**

Append:

```python
class RestockTest(TestCase):
    def setUp(self):
        cat = AccountingCategory.objects.create(name='c')
        self.job = Job.objects.create(job_number='JOB-R-1')
        self.pli = PriceListItem.objects.create(
            code='I', accounting_category=cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )

    def test_partial_restock_shrinks_earmark_and_bumps_restocked_qty(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('5'), price_list_item=self.pli,
        )
        MaterialService.restock(m, Decimal('2'))
        m.refresh_from_db()
        self.assertEqual(m.restocked_qty, Decimal('2'))
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        e = Earmark.objects.get(price_list_item=self.pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('3'))

    def test_full_restock_manual_add_deletes_material(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('5'), price_list_item=self.pli,
        )
        mid = m.pk
        MaterialService.restock(m, Decimal('5'))
        self.assertFalse(Material.objects.filter(pk=mid).exists())
        self.assertFalse(Earmark.objects.filter(
            price_list_item=self.pli, job=self.job).exists())

    def test_restock_validates_positive_and_leq_effective(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        with self.assertRaises(ValidationError):
            MaterialService.restock(m, Decimal('0'))
        with self.assertRaises(ValidationError):
            MaterialService.restock(m, Decimal('3'))
```

(The "expense-bound fully restocked survives" case is covered in the expense tests, Task 12.)

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_material_ops.RestockTest -v 2`
Expected: FAIL.

- [ ] **Step 3: Implement `restock`**

```python
    @staticmethod
    def restock(material, qty):
        from django.db import transaction
        if qty <= Decimal('0.00') or qty > material.effective_qty:
            raise ValidationError('restock qty must be > 0 and <= effective_qty')
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('restock requires pending state')
        with transaction.atomic():
            InventoryService._mutate_earmark(material.price_list_item, material.job, -qty)
            material.restocked_qty = material.restocked_qty + qty
            material.save(update_fields=['restocked_qty'])
            if material.effective_qty == Decimal('0.00') and not material.is_expense_bound:
                material.delete()
        return material
```

- [ ] **Step 4: Run all material ops tests, verify pass**

Run: `python manage.py test tests.test_material_ops -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/services.py tests/test_material_ops.py
git commit -m "feat(inventory): MaterialService.restock (partial / full, manual-add deletes)"
```

---

### Task 9: `MaterialService.draw_more`

**Files:**
- Modify: `apps/inventory/services.py`
- Test: `tests/test_material_ops.py` (extend)

- [ ] **Step 1: Write failing tests**

Append:

```python
class DrawMoreTest(TestCase):
    def setUp(self):
        cat = AccountingCategory.objects.create(name='c')
        self.job = Job.objects.create(job_number='JOB-D-1')
        self.pli = PriceListItem.objects.create(
            code='I', accounting_category=cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )

    def test_draw_more_increases_quantity_and_earmark(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        MaterialService.draw_more(m, Decimal('3'))
        m.refresh_from_db()
        self.assertEqual(m.quantity, Decimal('5'))
        e = Earmark.objects.get(price_list_item=self.pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('5'))

    def test_draw_more_rejects_non_positive(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('1'), price_list_item=self.pli,
        )
        with self.assertRaises(ValidationError):
            MaterialService.draw_more(m, Decimal('0'))

    def test_draw_more_forbidden_on_expense_bound(self):
        # Create an expense linked to the material to make it expense-bound.
        from apps.expenses.models import Expense
        from apps.core.models import AccountingCategory, User
        user = User.objects.create(username='u')
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('1'), price_list_item=self.pli,
        )
        Expense.objects.create(
            entered_by=user, amount=Decimal('10'),
            purchased_on='2026-04-14',
            accounting_category=m.accounting_category or AccountingCategory.objects.first(),
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            material=m,
        )
        with self.assertRaises(ValidationError):
            MaterialService.draw_more(m, Decimal('1'))
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_material_ops.DrawMoreTest -v 2`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
    @staticmethod
    def draw_more(material, qty):
        from django.db import transaction
        if qty <= Decimal('0.00'):
            raise ValidationError('draw_more qty must be > 0')
        if material.is_expense_bound:
            raise ValidationError('draw_more not allowed on expense-bound materials')
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('draw_more requires pending state')
        with transaction.atomic():
            material.quantity = material.quantity + qty
            material.save(update_fields=['quantity'])
            InventoryService._mutate_earmark(material.price_list_item, material.job, qty)
        return material
```

- [ ] **Step 4: Run, verify pass**

Run: `python manage.py test tests.test_material_ops -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/services.py tests/test_material_ops.py
git commit -m "feat(inventory): MaterialService.draw_more (forbidden on expense-bound)"
```

---

## Phase 4 — Expense path unification

### Task 10: `InventoryService.receive_ad_hoc_purchase` / `reverse_ad_hoc_purchase`

**Files:**
- Modify: `apps/inventory/services.py`
- Test: `tests/test_expense_material_inventory.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_expense_material_inventory.py
from decimal import Decimal
from django.test import TestCase
from apps.inventory.models import PriceListItem
from apps.inventory.services import InventoryService, MaterialService
from apps.core.models import AccountingCategory
from apps.jobs.models import Job


class AdHocPurchaseTest(TestCase):
    def setUp(self):
        cat = AccountingCategory.objects.create(name='c')
        self.job = Job.objects.create(job_number='JOB-AH-1')
        self.pli = PriceListItem.objects.create(
            code='I', accounting_category=cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )

    def test_receive_ad_hoc_purchase_bumps_qoh_only(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        InventoryService.receive_ad_hoc_purchase(m)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('12'))

    def test_reverse_ad_hoc_purchase_drops_qoh(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        InventoryService.receive_ad_hoc_purchase(m)
        InventoryService.reverse_ad_hoc_purchase(m)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('10'))
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_expense_material_inventory.AdHocPurchaseTest -v 2`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
    @staticmethod
    def receive_ad_hoc_purchase(material):
        from django.db.models import F
        pli = material.price_list_item
        if not pli or not pli.is_inventoried:
            return
        pli.qty_on_hand = F('qty_on_hand') + material.quantity
        pli.save(update_fields=['qty_on_hand'])
        pli.refresh_from_db()

    @staticmethod
    def reverse_ad_hoc_purchase(material):
        from django.db.models import F
        pli = material.price_list_item
        if not pli or not pli.is_inventoried:
            return
        pli.qty_on_hand = F('qty_on_hand') - material.quantity
        pli.save(update_fields=['qty_on_hand'])
        pli.refresh_from_db()
```

- [ ] **Step 4: Run, verify pass**

Run: `python manage.py test tests.test_expense_material_inventory -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/services.py tests/test_expense_material_inventory.py
git commit -m "feat(inventory): receive_ad_hoc_purchase / reverse_ad_hoc_purchase (QOH only)"
```

---

### Task 11: Rewire `ExpenseService.submit` to route through `MaterialService.create_on_job`

**Files:**
- Modify: `apps/expenses/services.py` (lines ~15–56, delete `find_or_create_materials_task` at line 145)
- Test: `tests/test_expense_material_inventory.py` (extend), `tests/test_expense_service.py` (existing — update)

- [ ] **Step 1: Write failing test**

Append to `tests/test_expense_material_inventory.py`:

```python
from apps.core.models import User
from apps.expenses.models import Expense
from apps.expenses.services import ExpenseService
from apps.inventory.models import Material, Earmark


class ExpenseSubmitPathTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c')
        self.user = User.objects.create(username='u')
        self.job = Job.objects.create(job_number='JOB-EX-1')
        self.pli = PriceListItem.objects.create(
            code='I', accounting_category=self.cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )

    def test_submit_inventoried_creates_taskless_material_and_bumps_qoh(self):
        exp = ExpenseService.submit(
            entered_by=self.user, payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            amount=Decimal('25'), purchased_on='2026-04-14',
            accounting_category=self.cat,
            new_material={
                'job_id': self.job.pk,
                'description': 'bolts',
                'quantity': Decimal('5'),
                'price': Decimal('5'),
                'price_list_item_id': self.pli.pk,
            },
        )
        self.assertEqual(exp.material.job_id, self.job.pk)
        self.assertIsNone(exp.material.task_id)  # task-less!
        self.assertEqual(exp.material.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('15'))
        e = Earmark.objects.get(price_list_item=self.pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('5'))

    def test_submit_does_not_create_placeholder_task(self):
        from apps.jobs.models import Task
        ExpenseService.submit(
            entered_by=self.user, payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            amount=Decimal('25'), purchased_on='2026-04-14',
            accounting_category=self.cat,
            new_material={
                'job_id': self.job.pk, 'description': 'x',
                'quantity': Decimal('1'), 'price': Decimal('25'),
            },
        )
        self.assertFalse(Task.objects.filter(job=self.job, name='Materials').exists())
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_expense_material_inventory.ExpenseSubmitPathTest -v 2`
Expected: FAIL — placeholder task still created, no earmark.

- [ ] **Step 3: Edit `ExpenseService.submit`**

Replace the `if new_material and not material:` block in `apps/expenses/services.py`:

```python
            if new_material and not material:
                from apps.jobs.models import Job
                from apps.inventory.models import PriceListItem
                from apps.inventory.services import InventoryService, MaterialService
                job = Job.objects.get(pk=new_material['job_id'])
                pli = None
                if new_material.get('price_list_item_id'):
                    pli = PriceListItem.objects.get(pk=new_material['price_list_item_id'])
                qty = new_material.get('quantity') or Decimal('1')
                price = new_material.get('price')
                if price is None:
                    price = amount
                material = MaterialService.create_on_job(
                    job=job, task=None,
                    description=new_material.get('description', description),
                    quantity=qty,
                    unit_cost=price,
                    price_list_item=pli,
                )
                if pli and pli.is_inventoried:
                    InventoryService.receive_ad_hoc_purchase(material)
```

Delete `ExpenseService.find_or_create_materials_task` (lines 144–155) — no more callers.

- [ ] **Step 4: Run, verify pass**

Run:
```
python manage.py test tests.test_expense_material_inventory tests.test_expense_service tests.test_api_expenses tests.test_qbo_expense_push -v 2
```
Expected: PASS. Fix any test that relied on the old "Materials" placeholder task by updating it to assert task-less Material creation.

- [ ] **Step 5: Commit**

```bash
git add apps/expenses/services.py tests/test_expense_material_inventory.py tests/test_expense_service.py tests/test_api_expenses.py tests/test_qbo_expense_push.py
git commit -m "refactor(expenses): route submit's new_material through MaterialService.create_on_job; drop Materials placeholder task"
```

---

### Task 12: `ExpenseService.reject` cascade

**Files:**
- Modify: `apps/expenses/services.py` (reject, line ~123)
- Test: `tests/test_expense_material_inventory.py` (extend)

- [ ] **Step 1: Write failing tests**

Append:

```python
class ExpenseRejectCascadeTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c')
        self.user = User.objects.create(username='u')
        self.job = Job.objects.create(job_number='JOB-RJ-1')
        self.pli = PriceListItem.objects.create(
            code='I', accounting_category=self.cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )

    def _submit(self, qty=Decimal('3')):
        return ExpenseService.submit(
            entered_by=self.user, payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            amount=Decimal('10'), purchased_on='2026-04-14',
            accounting_category=self.cat,
            new_material={
                'job_id': self.job.pk, 'description': 'x',
                'quantity': qty, 'price': Decimal('10'),
                'price_list_item_id': self.pli.pk,
            },
        )

    def test_reject_pending_reverses_earmark_qoh_and_deletes_material(self):
        exp = self._submit()
        mid = exp.material.pk
        ExpenseService.reject(expense=exp, actor=self.user)
        self.assertFalse(Material.objects.filter(pk=mid).exists())
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('10'))
        self.assertFalse(Earmark.objects.filter(
            price_list_item=self.pli, job=self.job).exists())

    def test_reject_forbidden_when_material_consumed(self):
        from django.core.exceptions import ValidationError
        exp = self._submit()
        MaterialService.consume(exp.material)
        with self.assertRaises(ValidationError):
            ExpenseService.reject(expense=exp, actor=self.user)

    def test_reject_after_full_restock_expense_bound_survives_until_reject(self):
        exp = self._submit(qty=Decimal('2'))
        MaterialService.restock(exp.material, Decimal('2'))
        exp.material.refresh_from_db()
        self.assertTrue(Material.objects.filter(pk=exp.material.pk).exists())  # survives
        self.assertEqual(exp.material.effective_qty, Decimal('0'))
        ExpenseService.reject(expense=exp, actor=self.user)
        self.assertFalse(Material.objects.filter(pk=exp.material.pk).exists())
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('10'))
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_expense_material_inventory.ExpenseRejectCascadeTest -v 2`
Expected: FAIL.

- [ ] **Step 3: Rewrite `ExpenseService.reject`**

Replace the existing `reject` method:

```python
    @staticmethod
    def reject(*, expense, actor):
        from apps.inventory.models import Material
        from apps.inventory.services import InventoryService
        if expense.payment_method != Expense.PAYMENT_METHOD_PERSONAL:
            raise ValidationError('Only personal expenses can be rejected.')
        if expense.status not in (Expense.STATUS_SUBMITTED,):
            raise ValidationError(
                f'Cannot reject an expense in status {expense.status!r}.'
            )
        materials = list(Material.objects.filter(expenses=expense))
        for m in materials:
            if m.consumption_state == Material.CONSUMPTION_STATE_CONSUMED:
                raise ValidationError(
                    'Cannot reject expense with consumed materials; adjust inventory manually.'
                )
        with transaction.atomic():
            for m in materials:
                # Release remaining earmark contribution.
                InventoryService._mutate_earmark(
                    m.price_list_item, m.job, -m.effective_qty,
                )
                # Reverse the QOH bump done at submit (full purchase quantity).
                InventoryService.reverse_ad_hoc_purchase(m)
                m.delete()
            expense.status = Expense.STATUS_REJECTED
            expense.save(update_fields=['status'])
        return expense
```

- [ ] **Step 4: Run, verify pass**

Run: `python manage.py test tests.test_expense_material_inventory -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/expenses/services.py tests/test_expense_material_inventory.py
git commit -m "feat(expenses): reject cascades to Materials (release earmark, reverse QOH, delete)"
```

---

## Phase 5 — Template population

### Task 13: `WorkTemplate.generate_materials_for_worksheet`

**Files:**
- Modify: `apps/estimates/models.py` (WorkTemplate, ~line 317)
- Test: `tests/test_template_materials.py` (extend)

- [ ] **Step 1: Write failing test**

Append:

```python
from apps.jobs.models import Job
from apps.estimates.models import EstWorksheet
from apps.inventory.models import PlanMaterial, TemplateMaterial


class GenerateMaterialsForWorksheetTest(TestCase):
    def test_generates_taskless_plan_materials(self):
        wt = WorkTemplate.objects.create(
            template_name='t', base_price=Decimal('0'), is_active=True,
        )
        TemplateMaterial.objects.create(
            work_template=wt, description='screws', quantity=Decimal('10'),
        )
        TemplateMaterial.objects.create(
            work_template=wt, description='nails', quantity=Decimal('5'),
        )
        job = Job.objects.create(job_number='JOB-GM-1')
        ws = EstWorksheet.objects.create(job=job)
        wt.generate_materials_for_worksheet(ws, quantity=1)
        pms = list(PlanMaterial.objects.filter(est_worksheet=ws, plan_task__isnull=True))
        self.assertEqual(len(pms), 2)
        self.assertEqual({p.description for p in pms}, {'screws', 'nails'})

    def test_quantity_multiplies_generation(self):
        wt = WorkTemplate.objects.create(
            template_name='t2', base_price=Decimal('0'), is_active=True,
        )
        TemplateMaterial.objects.create(
            work_template=wt, description='screws', quantity=Decimal('10'),
        )
        job = Job.objects.create(job_number='JOB-GM-2')
        ws = EstWorksheet.objects.create(job=job)
        wt.generate_materials_for_worksheet(ws, quantity=3)
        self.assertEqual(
            PlanMaterial.objects.filter(est_worksheet=ws, plan_task__isnull=True).count(),
            3,
        )
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_template_materials.GenerateMaterialsForWorksheetTest -v 2`
Expected: FAIL — method not defined.

- [ ] **Step 3: Implement on `WorkTemplate`**

Add a method to the `WorkTemplate` model:

```python
    def generate_materials_for_worksheet(self, worksheet, quantity=1):
        from apps.inventory.models import PlanMaterial
        for tm in self.materials.all():
            for _ in range(quantity):
                PlanMaterial.objects.create(
                    est_worksheet=worksheet,
                    plan_task=None,
                    description=tm.description,
                    quantity=tm.quantity,
                    unit_cost=tm.unit_cost,
                    sell_price=tm.sell_price,
                    price_list_item=tm.price_list_item,
                    accounting_category=tm.accounting_category,
                )
```

- [ ] **Step 4: Run, verify pass**

Run: `python manage.py test tests.test_template_materials -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/models.py tests/test_template_materials.py
git commit -m "feat(estimates): WorkTemplate.generate_materials_for_worksheet"
```

---

### Task 14: `WorkTemplate.generate_materials_for_job` + wire into `populate_from_template`

**Files:**
- Modify: `apps/estimates/models.py`
- Modify: `apps/jobs/services.py` (populate_from_template, ~line 279)
- Test: `tests/test_template_materials.py` (extend)

- [ ] **Step 1: Write failing test**

```python
class GenerateMaterialsForJobTest(TestCase):
    def test_populate_from_template_creates_taskless_materials_with_earmarks(self):
        from apps.jobs.services import JobService
        from apps.inventory.models import Material, Earmark, PriceListItem
        from apps.core.models import AccountingCategory
        cat = AccountingCategory.objects.create(name='c')
        pli = PriceListItem.objects.create(
            code='I', accounting_category=cat, is_inventoried=True,
        )
        wt = WorkTemplate.objects.create(
            template_name='t', base_price=Decimal('0'), is_active=True,
        )
        TemplateMaterial.objects.create(
            work_template=wt, description='x',
            quantity=Decimal('4'), price_list_item=pli,
        )
        job = Job.objects.create(job_number='JOB-GJ-1')
        JobService.populate_from_template(job, wt)
        mats = Material.objects.filter(job=job, task__isnull=True)
        self.assertEqual(mats.count(), 1)
        e = Earmark.objects.get(price_list_item=pli, job=job)
        self.assertEqual(e.quantity, Decimal('4'))
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_template_materials.GenerateMaterialsForJobTest -v 2`
Expected: FAIL.

- [ ] **Step 3: Add the generator method**

On `WorkTemplate`:

```python
    def generate_materials_for_job(self, job, quantity=1):
        from apps.inventory.services import MaterialService
        for tm in self.materials.all():
            for _ in range(quantity):
                MaterialService.create_on_job(
                    job=job, task=None,
                    description=tm.description,
                    quantity=tm.quantity,
                    unit_cost=tm.unit_cost,
                    sell_price=tm.sell_price,
                    price_list_item=tm.price_list_item,
                    accounting_category=tm.accounting_category,
                )
```

- [ ] **Step 4: Wire into `JobService.populate_from_template`**

In `apps/jobs/services.py`, after the `for association in associations: ...` loop (around line 294) and before `InventoryService.create_earmarks_for_job`:

```python
        template.generate_materials_for_job(job, quantity=1)
```

- [ ] **Step 5: Run, verify pass**

Run: `python manage.py test tests.test_template_materials -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/estimates/models.py apps/jobs/services.py tests/test_template_materials.py
git commit -m "feat(jobs): populate_from_template generates task-less Materials from TemplateMaterial"
```

---

## Phase 6 — Copy paths

### Task 15: `JobService.copy_from_worksheet` — task-attached loop uses `MaterialService.create_on_job`

**Files:**
- Modify: `apps/jobs/services.py` (copy_from_worksheet, lines 301–348)
- Test: `tests/test_earmark_flow.py` (existing) — plus new `tests/test_copy_from_worksheet_materials.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_copy_from_worksheet_materials.py
from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, PlanTask
from apps.estimates.models import EstWorksheet
from apps.inventory.models import PriceListItem, PlanMaterial, Material, Earmark
from apps.jobs.services import JobService


class CopyFromWorksheetMaterialsTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c')
        self.pli = PriceListItem.objects.create(
            code='I', accounting_category=self.cat, is_inventoried=True,
        )
        self.src_job = Job.objects.create(job_number='JOB-SRC-1')
        self.ws = EstWorksheet.objects.create(job=self.src_job)
        self.pt = PlanTask.objects.create(est_worksheet=self.ws, name='pt')
        PlanMaterial.objects.create(
            plan_task=self.pt, est_worksheet=self.ws,
            description='x', quantity=Decimal('3'), price_list_item=self.pli,
        )

    def test_task_attached_materials_copy_with_earmark_upsert(self):
        dst = Job.objects.create(job_number='JOB-DST-1')
        JobService.copy_from_worksheet(dst.pk, self.ws.pk)
        mats = Material.objects.filter(job=dst, task__isnull=False)
        self.assertEqual(mats.count(), 1)
        e = Earmark.objects.get(price_list_item=self.pli, job=dst)
        self.assertEqual(e.quantity, Decimal('3'))

    def test_taskless_plan_materials_copy_to_taskless_materials(self):
        PlanMaterial.objects.create(
            plan_task=None, est_worksheet=self.ws,
            description='loose', quantity=Decimal('2'), price_list_item=self.pli,
        )
        dst = Job.objects.create(job_number='JOB-DST-2')
        JobService.copy_from_worksheet(dst.pk, self.ws.pk)
        loose = Material.objects.filter(job=dst, task__isnull=True)
        self.assertEqual(loose.count(), 1)
        self.assertEqual(loose.first().description, 'loose')
        e = Earmark.objects.get(price_list_item=self.pli, job=dst)
        self.assertEqual(e.quantity, Decimal('5'))  # 3 task-attached + 2 task-less
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_copy_from_worksheet_materials -v 2`
Expected: FAIL — task-less PlanMaterial not copied; earmark only covers 3.

- [ ] **Step 3: Edit `copy_from_worksheet`**

Replace the body of the method's material-creation logic:

```python
        from apps.inventory.services import MaterialService

        for plan_task in PlanTask.objects.filter(
            est_worksheet=ws
        ).prefetch_related('plan_materials'):
            new_task = Task.objects.create(
                job=job,
                name=plan_task.name,
                description=plan_task.description,
                units=plan_task.units,
                rate=plan_task.rate,
                est_qty=plan_task.est_qty,
                accounting_category=plan_task.accounting_category,
                sort_order=plan_task.sort_order,
            )
            for pm in plan_task.plan_materials.all():
                MaterialService.create_on_job(
                    job=job, task=new_task,
                    description=pm.description,
                    quantity=pm.quantity,
                    unit_cost=pm.unit_cost,
                    sell_price=pm.sell_price,
                    price_list_item=pm.price_list_item,
                    accounting_category=pm.accounting_category,
                )

        # Task-less PlanMaterials → task-less Materials on the job.
        for pm in ws.plan_materials.filter(plan_task__isnull=True):
            MaterialService.create_on_job(
                job=job, task=None,
                description=pm.description,
                quantity=pm.quantity,
                unit_cost=pm.unit_cost,
                sell_price=pm.sell_price,
                price_list_item=pm.price_list_item,
                accounting_category=pm.accounting_category,
            )

        from apps.inventory.services import InventoryService
        InventoryService.create_earmarks_for_job(job)
```

- [ ] **Step 4: Run, verify pass**

Run:
```
python manage.py test tests.test_copy_from_worksheet_materials tests.test_earmark_flow -v 2
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services.py tests/test_copy_from_worksheet_materials.py
git commit -m "feat(jobs): copy_from_worksheet routes materials through MaterialService; carries task-less PlanMaterials"
```

---

### Task 16: `JobService.populate_from_estimate` covers task-less plan materials

**Files:**
- Modify: `apps/jobs/services.py` (populate_from_estimate, line 261)
- Test: `tests/test_populate_from_estimate_materials.py` (new)

- [ ] **Step 1: Write failing test**

```python
# tests/test_populate_from_estimate_materials.py
from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory
from apps.jobs.models import Job
from apps.estimates.models import EstWorksheet, Estimate
from apps.estimates.services import EstimateGenerationService
from apps.inventory.models import PriceListItem, PlanMaterial, Material
from apps.jobs.services import JobService


class PopulateFromEstimateLooseMaterialTest(TestCase):
    def test_taskless_plan_material_lands_as_taskless_material(self):
        cat = AccountingCategory.objects.create(name='c')
        pli = PriceListItem.objects.create(
            code='I', accounting_category=cat, is_inventoried=True,
        )
        ws_job = Job.objects.create(job_number='JOB-PE-SRC-1')
        ws = EstWorksheet.objects.create(job=ws_job)
        PlanMaterial.objects.create(
            plan_task=None, est_worksheet=ws,
            description='loose', quantity=Decimal('2'),
            price_list_item=pli,
        )
        est = EstimateGenerationService().generate_estimate_from_worksheet(ws)
        est.status = Estimate.STATUS_ACCEPTED
        est.save(update_fields=['status'])

        dst = Job.objects.create(job_number='JOB-PE-DST-1')
        JobService.populate_from_estimate(dst, est)

        loose = Material.objects.filter(job=dst, task__isnull=True)
        self.assertEqual(loose.count(), 1)
        self.assertEqual(loose.first().description, 'loose')
```

(Depends on Task 17 for estimate generation; the test will fail at either stage until both are done.)

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_populate_from_estimate_materials -v 2`
Expected: FAIL.

- [ ] **Step 3: Implement — see Task 17 for estimate generation.** Then wire up `populate_from_estimate` to detect materials attached directly to the estimate (via `EstimateLineItem` backed by task-less PlanMaterial).

Simplest approach: after `for line_item in estimate.estimatelineitem_set.all()`, look for line items whose `source_plan_material` (or equivalent) has `plan_task__isnull=True` and create task-less Materials. Concrete field-tie depends on what `_create_material_line_item` stores on the line item today — verify in Task 17 first and wire consistently.

Pseudo-implementation (concrete fields confirmed via Task 17):

```python
    @staticmethod
    def populate_from_estimate(job, estimate):
        if estimate.status not in [Estimate.STATUS_OPEN, Estimate.STATUS_ACCEPTED]:
            raise ValidationError(...)
        for line_item in estimate.estimatelineitem_set.all():
            if line_item.plan_material_id and line_item.plan_material.plan_task_id is None:
                # task-less plan material → task-less Material on job
                pm = line_item.plan_material
                from apps.inventory.services import MaterialService
                MaterialService.create_on_job(
                    job=job, task=None,
                    description=pm.description,
                    quantity=pm.quantity,
                    unit_cost=pm.unit_cost,
                    sell_price=pm.sell_price,
                    price_list_item=pm.price_list_item,
                    accounting_category=pm.accounting_category,
                )
            else:
                TaskService.create_from_line_item(line_item, job)
        from apps.inventory.services import InventoryService
        InventoryService.create_earmarks_for_job(job)
        return job
```

If `EstimateLineItem` doesn't carry a direct `plan_material` FK today, add one in Task 17 (or follow whatever convention `_create_material_line_item` already uses to associate line items with their source PlanMaterial).

- [ ] **Step 4: Run, verify pass (after Task 17 lands)**

Run: `python manage.py test tests.test_populate_from_estimate_materials tests.test_estimate_generation_materials -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services.py tests/test_populate_from_estimate_materials.py
git commit -m "feat(jobs): populate_from_estimate carries task-less plan materials"
```

---

## Phase 7 — Estimate generation

### Task 17: Task-less `PlanMaterial` becomes its own `EstimateLineItem`

**Files:**
- Modify: `apps/estimates/services.py` (`generate_estimate_from_worksheet` at line 641)
- Test: `tests/test_estimate_generation_materials.py` (existing — extend)

- [ ] **Step 1: Write failing test**

Append to `tests/test_estimate_generation_materials.py`:

```python
class TasklessPlanMaterialLineItemTest(TestCase):
    def test_taskless_plan_material_becomes_own_line_item(self):
        from decimal import Decimal
        from apps.core.models import AccountingCategory
        from apps.jobs.models import Job
        from apps.estimates.models import EstWorksheet
        from apps.inventory.models import PlanMaterial, PriceListItem
        from apps.estimates.services import EstimateGenerationService
        cat = AccountingCategory.objects.create(name='c')
        pli = PriceListItem.objects.create(
            code='P', accounting_category=cat, is_inventoried=False,
        )
        job = Job.objects.create(job_number='JOB-EG-1')
        ws = EstWorksheet.objects.create(job=job)
        PlanMaterial.objects.create(
            plan_task=None, est_worksheet=ws,
            description='loose', quantity=Decimal('2'),
            unit_cost=Decimal('1'), sell_price=Decimal('3'),
            price_list_item=pli,
        )
        est = EstimateGenerationService().generate_estimate_from_worksheet(ws)
        loose = est.estimatelineitem_set.filter(description='loose')
        self.assertEqual(loose.count(), 1)
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_estimate_generation_materials.TasklessPlanMaterialLineItemTest -v 2`
Expected: FAIL.

- [ ] **Step 3: Edit `generate_estimate_from_worksheet`**

After the existing direct/bundled task loop (near the end of `generate_estimate_from_worksheet`), add:

```python
        # Task-less plan materials → own line items
        for pm in worksheet.plan_materials.filter(plan_task__isnull=True):
            self._create_material_line_item(pm, estimate)
```

Verify `_create_material_line_item` tolerates the input unchanged (the method at `apps/estimates/services.py:755` already works from a `PlanMaterial`). If it reaches through `pm.plan_task` for any field (e.g. sort order, task line number), guard for `None`:

```python
    def _create_material_line_item(self, material, estimate):
        # ... existing body ...
        task_line_number = material.plan_task.line_number if material.plan_task_id else None
        # use task_line_number only when present
```

(Audit `_create_material_line_item` at line 755 and adapt the guard to whatever fields it currently reaches. Keep the change minimal.)

- [ ] **Step 4: Run, verify pass**

Run: `python manage.py test tests.test_estimate_generation_materials -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/services.py tests/test_estimate_generation_materials.py
git commit -m "feat(estimates): task-less plan materials produce their own EstimateLineItem"
```

---

## Phase 8 — Invoice wizard

### Task 18: "Materials (no task)" group in source pool

**Files:**
- Modify: `apps/invoicing/services.py` (`get_source_pool` line 200, `_atom_computed_amount` line 320)
- Test: `tests/test_invoice_wizard_service.py` (existing — extend), `tests/test_invoice_wizard_api.py` (extend)

- [ ] **Step 1: Write failing tests**

Append a new test class to `tests/test_invoice_wizard_service.py`:

```python
class SourcePoolLooseMaterialsTest(TestCase):
    def test_taskless_materials_group_appears_with_effective_qty_filter(self):
        from decimal import Decimal
        from apps.core.models import AccountingCategory
        from apps.jobs.models import Job
        from apps.invoicing.models import Invoice
        from apps.invoicing.services import InvoiceWizardService
        from apps.inventory.models import PriceListItem
        from apps.inventory.services import MaterialService
        cat = AccountingCategory.objects.create(name='c')
        pli = PriceListItem.objects.create(
            code='I', accounting_category=cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )
        job = Job.objects.create(job_number='JOB-IW-1')
        m1 = MaterialService.create_on_job(
            job=job, task=None, description='m1',
            quantity=Decimal('3'), sell_price=Decimal('2'),
            price_list_item=pli,
        )
        m2 = MaterialService.create_on_job(
            job=job, task=None, description='fully restocked',
            quantity=Decimal('2'), sell_price=Decimal('2'),
            price_list_item=pli,
        )
        # Simulate expense-bound, restock fully: effective_qty=0, still exists
        from apps.expenses.models import Expense
        from apps.core.models import User
        user = User.objects.create(username='u')
        Expense.objects.create(
            entered_by=user, amount=Decimal('4'),
            purchased_on='2026-04-14',
            accounting_category=cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            material=m2,
        )
        MaterialService.restock(m2, Decimal('2'))
        inv = Invoice.objects.create(job=job, status=Invoice.STATUS_DRAFT)
        pool = InvoiceWizardService.get_source_pool(inv)

        loose = [g for g in pool['tasks'] if g['task_id'] is None]
        self.assertEqual(len(loose), 1)
        atoms = loose[0]['atoms']
        # Only m1 appears; m2 excluded by effective_qty == 0
        self.assertEqual([a['atom_id'] for a in atoms], [m1.pk])
        self.assertEqual(atoms[0]['computed_amount'], Decimal('6.00'))  # 3 * 2
```

Add a partial-restock test for `_atom_computed_amount`:

```python
    def test_partial_restock_bills_effective_qty(self):
        from decimal import Decimal
        from apps.core.models import AccountingCategory
        from apps.jobs.models import Job
        from apps.invoicing.services import InvoiceWizardService
        from apps.inventory.models import PriceListItem
        from apps.inventory.services import MaterialService
        cat = AccountingCategory.objects.create(name='c')
        pli = PriceListItem.objects.create(
            code='I', accounting_category=cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )
        job = Job.objects.create(job_number='JOB-IW-2')
        m = MaterialService.create_on_job(
            job=job, task=None, description='m',
            quantity=Decimal('5'), sell_price=Decimal('2'),
            price_list_item=pli,
        )
        MaterialService.restock(m, Decimal('2'))
        amount = InvoiceWizardService._atom_computed_amount(m)
        self.assertEqual(amount, Decimal('6.00'))  # effective 3 * 2
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_invoice_wizard_service.SourcePoolLooseMaterialsTest -v 2`
Expected: FAIL.

- [ ] **Step 3: Edit `get_source_pool` and `_atom_computed_amount`**

Append a "Materials (no task)" group after the task loop, before `return`:

```python
        from django.db.models import F
        loose = (
            Material.objects.filter(job=job, task__isnull=True)
            .annotate(eff=F('quantity') - F('restocked_qty'))
            .filter(eff__gt=0)
            .order_by('pk')
        )
        loose_atoms = []
        for mat in loose:
            amount = (mat.effective_qty * mat.sell_price).quantize(Decimal('0.01'))
            key = (InvoiceLineItemSource.SOURCE_MATERIAL, mat.pk)
            state_info = claims.get(key, default_state)
            loose_atoms.append({
                'atom_type': 'material',
                'atom_id': mat.pk,
                'description': mat.description,
                'sub_info': '',
                'computed_amount': amount,
                **state_info,
            })
        task_list.append({
            'task_id': None,
            'name': 'Materials (no task)',
            'has_billable_atoms': len(loose_atoms) > 0,
            'atoms': loose_atoms,
        })
        return {'tasks': task_list}
```

And in `_atom_computed_amount` replace the Material branch to use `effective_qty`:

```python
        if isinstance(atom_instance, Material):
            return (atom_instance.effective_qty * atom_instance.sell_price).quantize(Decimal('0.01'))
```

Also: the task loop's Material atoms should use `effective_qty` consistently — update lines ~280–292 to use `mat.effective_qty` instead of `mat.quantity` for the amount, and filter `Material.objects.filter(task=task).annotate(eff=F('quantity') - F('restocked_qty')).filter(eff__gt=0)`.

- [ ] **Step 4: Run, verify pass**

Run:
```
python manage.py test tests.test_invoice_wizard_service tests.test_invoice_wizard_api tests.test_invoice_line_item_source -v 2
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/invoicing/services.py tests/test_invoice_wizard_service.py tests/test_invoice_wizard_api.py
git commit -m "feat(invoicing): wizard source pool adds 'Materials (no task)' group; uses effective_qty"
```

---

## Phase 9 — `work_complete` gate

### Task 19: Block `Job` → `work_complete` when task-less inventoried materials are pending

**Files:**
- Locate existing work_complete transition logic (`apps/jobs/services.py` — search for `STATUS_WORK_COMPLETE`; likely `JobService.mark_work_complete` or the API view action on JobViewSet)
- Modify: wherever the gate lives
- Test: `tests/test_loose_material_work_complete.py` (new)

- [ ] **Step 1: Locate the transition**

Grep: `grep -rn "work_complete\|WORK_COMPLETE" apps/ | head -40` — identify the gate / transition entry point (`JobService` method or signal on Task completion). Note file:line.

- [ ] **Step 2: Write failing tests**

```python
# tests/test_loose_material_work_complete.py
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, Task
from apps.inventory.models import PriceListItem, Material
from apps.inventory.services import MaterialService
from apps.jobs.services import JobService  # or wherever mark_work_complete lives


class LooseMaterialWorkCompleteGateTest(TestCase):
    def setUp(self):
        cat = AccountingCategory.objects.create(name='c')
        self.pli = PriceListItem.objects.create(
            code='I', accounting_category=cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )
        self.job = Job.objects.create(
            job_number='JOB-WC-1', status=Job.STATUS_APPROVED,
        )

    def test_taskless_pending_inventoried_material_blocks_transition(self):
        MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        with self.assertRaises(ValidationError):
            JobService.mark_work_complete(self.job)

    def test_fully_restocked_expense_bound_does_not_block(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        # Make expense-bound
        from apps.expenses.models import Expense
        from apps.core.models import User
        user = User.objects.create(username='u')
        Expense.objects.create(
            entered_by=user, amount=Decimal('10'),
            purchased_on='2026-04-14',
            accounting_category=m.accounting_category or AccountingCategory.objects.first(),
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            material=m,
        )
        MaterialService.restock(m, Decimal('2'))
        JobService.mark_work_complete(self.job)  # should succeed
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_WORK_COMPLETE)

    def test_consuming_pending_unblocks(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        MaterialService.consume(m)
        JobService.mark_work_complete(self.job)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_WORK_COMPLETE)
```

Also add an auto-advance coverage test to match the design's "last-task-completion path":

```python
    def test_last_task_completion_autoadvance_blocked_by_loose_material(self):
        MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        t = Task.objects.create(job=self.job, name='only')
        # Drive whatever API/service causes the Task to complete and trigger auto-advance.
        # Expected: the job does NOT advance to work_complete.
        from apps.jobs.services import TaskService  # or whatever completes tasks
        TaskService.mark_complete(t)  # adapt method name to codebase
        self.job.refresh_from_db()
        self.assertNotEqual(self.job.status, Job.STATUS_WORK_COMPLETE)
```

- [ ] **Step 3: Run, verify failure**

Run: `python manage.py test tests.test_loose_material_work_complete -v 2`
Expected: FAIL.

- [ ] **Step 4: Implement the gate**

Add a helper near the top of `apps/jobs/services.py`:

```python
    @staticmethod
    def _loose_pending_inventoried_materials(job):
        from django.db.models import F
        from apps.inventory.models import Material
        return (
            Material.objects.filter(
                job=job, task__isnull=True,
                price_list_item__is_inventoried=True,
                consumption_state=Material.CONSUMPTION_STATE_PENDING,
            )
            .annotate(eff=F('quantity') - F('restocked_qty'))
            .filter(eff__gt=0)
        )
```

At the top of `JobService.mark_work_complete` (and in the last-task auto-advance path — likely the same entry point, or a shared `_advance_to_work_complete`):

```python
        offenders = JobService._loose_pending_inventoried_materials(job)
        if offenders.exists():
            names = ', '.join(m.description or str(m.pk) for m in offenders)
            raise ValidationError(
                f'Cannot advance to work_complete: unresolved task-less materials: {names}'
            )
```

If the auto-advance path is in a signal (e.g. `apps/jobs/signals.py`) and invokes `mark_work_complete`, the gate is inherited automatically. If it bypasses the service and calls `job.save()` directly, refactor it to route through `mark_work_complete`, **swallowing the ValidationError so the task can still complete even when the auto-advance is blocked** (the user will transition the job manually later):

```python
# signal handler
try:
    JobService.mark_work_complete(job)
except ValidationError:
    pass  # gate blocked; user must resolve loose materials
```

- [ ] **Step 5: Run, verify pass**

Run: `python manage.py test tests.test_loose_material_work_complete -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/services.py apps/jobs/signals.py tests/test_loose_material_work_complete.py
git commit -m "feat(jobs): work_complete gate blocks on pending task-less inventoried materials"
```

---

## Phase 10 — API surface

### Task 20: Material endpoints (job-create + ops)

**Files:**
- Modify: `apps/api/inventory/views.py`, `apps/api/inventory/serializers.py`
- Modify: `apps/api/jobs/views.py` (Job materials sub-route) or `apps/api/urls.py` for top-level `/api/materials/`
- Modify: `apps/api/urls.py` (router registration)
- Test: `tests/test_api_materials.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_api_materials.py
from decimal import Decimal
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from apps.core.models import AccountingCategory
from apps.jobs.models import Job
from apps.inventory.models import PriceListItem, Material, Earmark

User = get_user_model()


class MaterialApiTest(APITestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c')
        self.user = User.objects.create_user('u', password='p')
        self.client.force_login(self.user)
        self.job = Job.objects.create(job_number='JOB-API-1')
        self.pli = PriceListItem.objects.create(
            code='I', accounting_category=self.cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )

    def test_post_jobs_id_materials_creates_taskless_material(self):
        url = f'/api/jobs/{self.job.pk}/materials/'
        resp = self.client.post(url, {
            'description': 'x', 'quantity': '3',
            'price_list_item': self.pli.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(Material.objects.filter(job=self.job, task__isnull=True).exists())

    def test_patch_material_description_only(self):
        from apps.inventory.services import MaterialService
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        r1 = self.client.patch(f'/api/materials/{m.pk}/', {'description': 'y'}, format='json')
        self.assertEqual(r1.status_code, 200)
        r2 = self.client.patch(f'/api/materials/{m.pk}/', {'quantity': '99'}, format='json')
        self.assertEqual(r2.status_code, 400)

    def test_consume_restock_draw_more_actions(self):
        from apps.inventory.services import MaterialService
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('5'), price_list_item=self.pli,
        )
        r = self.client.post(f'/api/materials/{m.pk}/draw-more/', {'quantity': '2'}, format='json')
        self.assertEqual(r.status_code, 200)
        r = self.client.post(f'/api/materials/{m.pk}/restock/', {'quantity': '1'}, format='json')
        self.assertEqual(r.status_code, 200)
        r = self.client.post(f'/api/materials/{m.pk}/consume/', format='json')
        self.assertEqual(r.status_code, 200)
        m.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)

    def test_draw_more_forbidden_on_expense_bound(self):
        from apps.inventory.services import MaterialService
        from apps.expenses.models import Expense
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('1'), price_list_item=self.pli,
        )
        Expense.objects.create(
            entered_by=self.user, amount=Decimal('10'),
            purchased_on='2026-04-14', accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            material=m,
        )
        r = self.client.post(f'/api/materials/{m.pk}/draw-more/', {'quantity': '1'}, format='json')
        self.assertEqual(r.status_code, 400)
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_api_materials -v 2`
Expected: FAIL — routes don't exist.

- [ ] **Step 3: Add serializer**

In `apps/api/inventory/serializers.py`:

```python
from rest_framework import serializers
from apps.inventory.models import Material


class MaterialSerializer(serializers.ModelSerializer):
    effective_qty = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True,
    )
    is_expense_bound = serializers.BooleanField(read_only=True)

    class Meta:
        model = Material
        fields = [
            'material_id', 'job', 'task',
            'description', 'quantity', 'unit_cost', 'sell_price',
            'price_list_item', 'accounting_category',
            'consumption_state', 'restocked_qty', 'effective_qty',
            'is_expense_bound',
        ]
        read_only_fields = [
            'material_id', 'job', 'task',
            'consumption_state', 'restocked_qty', 'effective_qty', 'is_expense_bound',
        ]

    def update(self, instance, validated_data):
        # PATCH restricted to description only; other fields 400.
        allowed = {'description'}
        disallowed = set(validated_data.keys()) - allowed
        if disallowed:
            raise serializers.ValidationError({
                k: 'read-only; use Restock/Draw-more for quantity, etc.'
                for k in disallowed
            })
        return super().update(instance, validated_data)


class MaterialOpSerializer(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
```

- [ ] **Step 4: Add viewset**

In `apps/api/inventory/views.py`:

```python
from decimal import Decimal
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.inventory.models import Material
from apps.inventory.services import MaterialService
from apps.api.inventory.serializers import MaterialSerializer, MaterialOpSerializer


class MaterialViewSet(viewsets.ModelViewSet):
    queryset = Material.objects.all()
    serializer_class = MaterialSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch', 'post', 'head', 'options']

    def destroy(self, request, *args, **kwargs):
        return Response({'error': 'Delete via Restock (manual-add) or expense rejection.'},
                        status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @action(detail=True, methods=['post'])
    def consume(self, request, pk=None):
        m = self.get_object()
        MaterialService.consume(m)
        m.refresh_from_db()
        return Response(MaterialSerializer(m).data)

    @action(detail=True, methods=['post'])
    def restock(self, request, pk=None):
        s = MaterialOpSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        m = self.get_object()
        MaterialService.restock(m, s.validated_data['quantity'])
        # Material may be deleted; refresh safely
        try:
            m.refresh_from_db()
            return Response(MaterialSerializer(m).data)
        except Material.DoesNotExist:
            return Response({'deleted': True})

    @action(detail=True, methods=['post'], url_path='draw-more')
    def draw_more(self, request, pk=None):
        s = MaterialOpSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        m = self.get_object()
        MaterialService.draw_more(m, s.validated_data['quantity'])
        m.refresh_from_db()
        return Response(MaterialSerializer(m).data)
```

- [ ] **Step 5: Register routes**

In `apps/api/urls.py`:

```python
from apps.api.inventory.views import PriceListItemViewSet, MaterialViewSet
router.register(r'materials', MaterialViewSet, basename='material')
```

- [ ] **Step 6: Add Job materials sub-route**

In `apps/api/jobs/views.py`, add a `materials` action on `JobViewSet`:

```python
    @action(detail=True, methods=['post'], url_path='materials',
            permission_classes=[IsAuthenticated])
    def create_material(self, request, pk=None):
        from apps.inventory.services import MaterialService
        from apps.api.inventory.serializers import MaterialSerializer
        job = self.get_object()
        data = request.data
        m = MaterialService.create_on_job(
            job=job, task=None,
            description=data.get('description', ''),
            quantity=data.get('quantity', 0),
            unit_cost=data.get('unit_cost', 0),
            sell_price=data.get('sell_price', 0),
            price_list_item_id=data.get('price_list_item'),
            accounting_category_id=data.get('accounting_category'),
        )
        return Response(MaterialSerializer(m).data, status=status.HTTP_201_CREATED)
```

(Adapt to the real `create_on_job` signature — it takes `price_list_item=` instance, not `_id`. Resolve in the action with `PriceListItem.objects.get(pk=...)`.)

- [ ] **Step 7: Run, verify pass**

Run: `python manage.py test tests.test_api_materials -v 2`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/api tests/test_api_materials.py
git commit -m "feat(api): /api/materials/ endpoints + /api/jobs/{id}/materials/ create"
```

---

### Task 21: Worksheet plan-materials endpoint accepts optional `plan_task`; TemplateMaterial CRUD

**Files:**
- Modify: `apps/api/estimates/views.py` (EstWorksheetViewSet plan-materials action — verify existence first)
- Modify: `apps/api/estimates/views.py` or new `apps/api/worktemplates/views.py` (TemplateMaterial CRUD)
- Modify: `apps/api/urls.py`
- Test: `tests/test_api_plan_materials.py` (new), `tests/test_api_template_materials.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_api_plan_materials.py — task-less plan-material creation
class PlanMaterialTasklessCreateTest(APITestCase):
    def test_post_without_plan_task_creates_worksheet_level(self):
        # ...setup EstWorksheet, POST with no plan_task field, assert plan_task=None
```

```python
# tests/test_api_template_materials.py — TemplateMaterial CRUD
class TemplateMaterialApiTest(APITestCase):
    def test_crud_requires_can_manage_config(self):
        # worker cannot POST, owner can
    def test_list_create_retrieve_update_delete(self):
        # standard DRF CRUD
```

(Fill in concrete assertions mirroring Task 20's style.)

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_api_plan_materials tests.test_api_template_materials -v 2`
Expected: FAIL.

- [ ] **Step 3: Implement**

- On `EstWorksheetViewSet.plan-materials` action: when the POST body omits `plan_task`, construct `PlanMaterial` with `plan_task=None` and `est_worksheet=worksheet`. The existing `InventoryService.create_plan_material(plan_task_pk, **kwargs)` needs a sibling `create_plan_material_on_worksheet(ws, **kwargs)`. Add it in `apps/inventory/services.py`.

- For template materials: register a router for `TemplateMaterialViewSet` with `permission_classes = [IsAuthenticated, CanManageConfig]`.

- [ ] **Step 4: Run, verify pass**

Run: `python manage.py test tests.test_api_plan_materials tests.test_api_template_materials -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api apps/inventory/services.py tests/test_api_plan_materials.py tests/test_api_template_materials.py
git commit -m "feat(api): worksheet plan-materials accepts optional plan_task; TemplateMaterial CRUD"
```

---

## Phase 11 — Data migration (backfill + tighten)

### Task 22: Backfill migration + constraint-tighten migration

**Files:**
- Create: `apps/inventory/migrations/00XY_material_backfill_and_cleanup.py`
- Create: `apps/inventory/migrations/00XZ_material_constraints_tighten.py`
- Test: `tests/test_material_migration.py` (new — uses Django's migration test harness)

- [ ] **Step 1: Write failing migration test**

```python
# tests/test_material_migration.py
from decimal import Decimal
from django.test import TransactionTestCase
from django.db.migrations.executor import MigrationExecutor
from django.db import connection


class MaterialBackfillMigrationTest(TransactionTestCase):
    migrate_from = [('inventory', '00XX_material_job_plan_worksheet_additive')]
    migrate_to = [('inventory', '00XY_material_backfill_and_cleanup')]

    def test_backfill_populates_job_and_est_worksheet(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        Job = old_apps.get_model('jobs', 'Job')
        Task = old_apps.get_model('jobs', 'Task')
        Material = old_apps.get_model('inventory', 'Material')
        # ... create rows with task set, job null, etc.
        executor.loader.build_graph()
        executor.migrate(self.migrate_to)
        new_apps = executor.loader.project_state(self.migrate_to).apps
        Material = new_apps.get_model('inventory', 'Material')
        # assert job_id backfilled from task.job_id, etc.
```

(Full migration test pattern — see existing examples in `tests/` if any; otherwise a simpler "run the data migration function directly" unit test is acceptable.)

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_material_migration -v 2`
Expected: FAIL.

- [ ] **Step 3: Implement backfill migration**

`apps/inventory/migrations/00XY_material_backfill_and_cleanup.py`:

```python
from django.db import migrations


def backfill(apps, schema_editor):
    Material = apps.get_model('inventory', 'Material')
    PlanMaterial = apps.get_model('inventory', 'PlanMaterial')
    Task = apps.get_model('jobs', 'Task')

    for m in Material.objects.all():
        if m.job_id is None and m.task_id:
            m.job_id = m.task.job_id
        # Inventoried materials need a starting consumption_state
        if m.price_list_item_id:
            pli = m.price_list_item
            if pli.is_inventoried and m.consumption_state == 'na':
                # if task is completed, mark consumed; else pending
                if m.task_id and m.task.status == 'complete':
                    m.consumption_state = 'consumed'
                else:
                    m.consumption_state = 'pending'
        m.save()

    for pm in PlanMaterial.objects.all():
        if pm.est_worksheet_id is None and pm.plan_task_id:
            pm.est_worksheet_id = pm.plan_task.est_worksheet_id
            pm.save()

    # Placeholder "Materials" task cleanup
    for t in Task.objects.filter(name='Materials'):
        has_bleps = t.blep_set.exists()
        mats = list(t.materials.all())
        all_expense_bound = mats and all(m.expenses.exists() for m in mats)
        if not has_bleps and all_expense_bound:
            for m in mats:
                m.task = None
                m.save()
            t.delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '00XX_material_job_plan_worksheet_additive'),
    ]
    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
```

- [ ] **Step 4: Implement constraint-tighten migration**

In `apps/inventory/models.py`, remove `null=True, blank=True` from `Material.job` and `PlanMaterial.est_worksheet`; change `Material.task` to `on_delete=SET_NULL, null=True, blank=True, related_name='materials'`; change `PlanMaterial.plan_task` to nullable.

Then run: `python manage.py makemigrations inventory --name material_constraints_tighten`

- [ ] **Step 5: Run, verify pass**

Run: `python manage.py test tests.test_material_migration -v 2`
Expected: PASS.

Then run the full test suite to catch any regression from the tightened constraints:

Run: `python manage.py test -v 2`
Expected: PASS.

- [ ] **Step 6: Fixture updates**

For each fixture listed in design "Fixtures" section, regenerate or hand-edit so each `materials` row has `job` populated and each `plan_materials` row has `est_worksheet` populated. Remove any remaining placeholder `task` named `"Materials"` and null out the corresponding material's `task` FK.

```bash
grep -l '"model": "inventory.material"' fixtures/ -r
# edit each affected fixture
python manage.py test -v 2  # verify fixtures still load cleanly
```

- [ ] **Step 7: Commit**

```bash
git add apps/inventory/models.py apps/inventory/migrations fixtures/ tests/test_material_migration.py
git commit -m "feat(inventory): backfill migration + tighten Material.job/PlanMaterial.est_worksheet NOT NULL"
```

---

## Phase 12 — Cleanup

### Task 23: Remove legacy `InventoryService.create_wo_material` / `update_wo_material` / `delete_wo_material` callers

**Files:**
- Grep: `InventoryService.create_wo_material|update_wo_material|delete_wo_material`
- Modify: each call site to use `MaterialService.create_on_job` or the new API endpoints
- Delete: those methods from `apps/inventory/services.py` once no callers remain

- [ ] **Step 1: Enumerate call sites**

Run:
```
grep -rn "create_wo_material\|update_wo_material\|delete_wo_material" apps/ tests/
```

- [ ] **Step 2: Rewrite each call site**

For each caller, replace with the equivalent `MaterialService` or API call. Likely: legacy Django HTML views (`apps/*/views.py`) or forms.

- [ ] **Step 3: Delete dead methods**

Once no callers remain, remove `create_wo_material`, `update_wo_material`, `delete_wo_material` from `apps/inventory/services.py`.

- [ ] **Step 4: Run full suite, verify pass**

Run: `python manage.py test -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/services.py apps/
git commit -m "refactor(inventory): drop legacy wo_material wrappers; all callers use MaterialService"
```

---

### Task 24: Assert `create_earmarks_for_job` is now a defensive no-op

**Files:**
- Test: `tests/test_earmark_flow.py` (extend)

- [ ] **Step 1: Write test**

```python
class CreateEarmarksForJobIsNoopTest(TestCase):
    def test_no_new_earmarks_when_materials_already_upserted(self):
        # Build a job via JobService.copy_from_worksheet; capture earmark state;
        # call InventoryService.create_earmarks_for_job(job) a second time;
        # assert earmark rows identical (same count, same quantities).
```

- [ ] **Step 2: Run, verify pass**

Run: `python manage.py test tests.test_earmark_flow.CreateEarmarksForJobIsNoopTest -v 2`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_earmark_flow.py
git commit -m "test(inventory): confirm create_earmarks_for_job is a defensive no-op under new regime"
```

---

## Manual browser testing

After all automated tests pass, work through the design doc's "Manual browser testing" checklist against `./dev.sh`. Report any UI gaps; the design doc's "Deferred" section flags surfacing work that's explicitly out of scope.

---

## Self-review checklist

- Every design section ("Schema changes", "Earmark & consumption semantics", "Expense flow", "Template population", "Invoice wizard & estimate generation", "Copy paths", "API surface", "Data migration", "Testing strategy") maps to at least one task above.
- `_mutate_earmark` is the sole Earmark writer after Task 6 (PO receive) and Task 11 (expense submit).
- Material deletion endpoints: none; only Restock-to-full (manual-add) or `ExpenseService.reject` (expense-bound) delete rows.
- Every new API endpoint has a test in `tests/test_api_materials.py`, `tests/test_api_plan_materials.py`, or `tests/test_api_template_materials.py`.
- Migrations are split into additive (Phase 1) and constraint-tighten (Task 22) with a RunPython backfill between them.
- No Django signals introduced (matches design).

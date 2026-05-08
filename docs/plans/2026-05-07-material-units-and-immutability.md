# Material `units` field + PLI-linked immutability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `units` field to `MaterialBase` (propagating to `Material`, `PlanMaterial`, `TemplateMaterial`); enforce that PLI-linked rows are immutable except for `unit_cost`/`sell_price`; add an optional `propagate_to_pli` flag on pricing PATCHes; and refactor `WorkTemplate.generate_materials_for_*` so PLI-linked TemplateMaterials pull pricing fresh from the current PLI instead of carrying stale snapshots.

**Architecture:** Schema change is one additive migration on the three `materials*` tables. The immutability rule is enforced at the API serializer layer (no model `clean()` defence-in-depth — keep it simple). The pricing carve-out lives in a dedicated `MaterialService.update_pricing` service method that handles the `propagate_to_pli` flag in a single atomic transaction. TemplateMaterial generation branches on `tm.price_list_item_id` so PLI-linked rows let `_populate_from_pli` pull current PLI values.

**Tech Stack:** Django 5.2, DRF, MySQL, Python 3.12, Svelte 5 (Vite SPA).

**Reference design:** `docs/designs/2026-05-07-material-units-field-design.md`. Read it before starting any task — it captures the why for every rule below.

---

## Conventions used throughout this plan

- **Never run `python manage.py migrate`.** Per `CLAUDE.md`, only the human user applies migrations to the dev DB. `makemigrations` is fine.
- **Tests:** `python manage.py test tests.test_<name>`. Test classes inherit from `tests.base.BaseTestCase` or `FixtureTestCase`. Run sequentially — do not parallelize across subagents (MySQL test-DB deadlock).
- **Commits:** one per task. Use `feat:` for new behavior, `refactor:` for internal restructuring, `test:` for test-only commits, `fix:` for bug fixes.
- **Service-mediated saves:** all Material/PlanMaterial mutations go through service methods, not direct ORM writes from views (per `docs/designs/2026-03-07-service-mediated-saves.md`).
- **Line-item deletion:** if any task touches `EstimateLineItem` deletion, route through `LineItemService.delete_line_item_with_renumber` — never call `.delete()` directly. Not expected to apply in this plan, but flag if it comes up.

---

## Phase 1 — Schema and `_populate_from_pli`

Add the `units` field to `MaterialBase` and wire `_populate_from_pli` to copy it from the linked PLI. Replace the existing `SerializerMethodField` hacks (which read through `obj.price_list_item.units`) with direct model fields. Pure additive — no behavior changes downstream yet.

### Task 1: Failing test — `units` field exists with default `'none'` on all three concrete models

**Files:**
- Test: `tests/test_material_units_field.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_material_units_field.py
from decimal import Decimal
from django.test import TestCase
from apps.inventory.models import Material, PlanMaterial, TemplateMaterial


class MaterialUnitsFieldTests(TestCase):
    """Phase 1: units field added to MaterialBase."""

    def test_material_has_units_field(self):
        f = Material._meta.get_field('units')
        self.assertEqual(f.max_length, 50)
        self.assertEqual(f.default, 'none')

    def test_plan_material_has_units_field(self):
        f = PlanMaterial._meta.get_field('units')
        self.assertEqual(f.max_length, 50)
        self.assertEqual(f.default, 'none')

    def test_template_material_has_units_field(self):
        f = TemplateMaterial._meta.get_field('units')
        self.assertEqual(f.max_length, 50)
        self.assertEqual(f.default, 'none')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_material_units_field -v 2`

Expected: 3 FAILs, all with `FieldDoesNotExist: Material has no field named 'units'` (or similar for the other two models).

- [ ] **Step 3: Add the `units` field to `MaterialBase`**

Edit `apps/inventory/models.py`. In `class MaterialBase(models.Model):`, add `units` between `quantity` and `unit_cost` to mirror `BaseLineItem`:

```python
class MaterialBase(models.Model):
    """Abstract base for PlanMaterial (planning) and Material (actual)."""
    description = models.CharField(max_length=255, blank=True, default='')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    units = models.CharField(max_length=50, default='none')
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    sell_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    price_list_item = models.ForeignKey(
        'PriceListItem', on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    accounting_category = models.ForeignKey(
        'core.AccountingCategory', on_delete=models.SET_NULL,
        null=True, blank=True,
    )
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations inventory`

Expected output: a new migration file in `apps/inventory/migrations/` with three `AddField` operations (one per concrete model — `materials`, `plan_materials`, `template_materials`). Verify by reading the generated file.

**Do not run `migrate`.** Per `CLAUDE.md`, only the user applies migrations.

- [ ] **Step 5: Run the test (still fails — DB schema not applied)**

Run: `python manage.py test tests.test_material_units_field -v 2`

Expected: PASS. Django's test runner creates a fresh test DB from migrations, so the new column exists in the test DB even though dev DB hasn't been migrated.

- [ ] **Step 6: Commit**

```bash
git add apps/inventory/models.py apps/inventory/migrations/ tests/test_material_units_field.py
git commit -m "feat: add units field to MaterialBase

Adds units CharField(max_length=50, default='none') to MaterialBase,
propagating to Material, PlanMaterial, and TemplateMaterial. Mirrors
the BaseLineItem.units field. No behavior change yet — population
from PLI and validation come in subsequent commits.

Refs: docs/designs/2026-05-07-material-units-field-design.md"
```

### Task 2: `_populate_from_pli` copies `units`

**Files:**
- Modify: `apps/inventory/models.py` (`MaterialBase._populate_from_pli`)
- Test: `tests/test_material_units_field.py` (extend)

- [ ] **Step 1: Write failing tests for PLI-fill behavior**

Append to `tests/test_material_units_field.py`:

```python
from apps.core.models import AccountingCategory, Configuration
from apps.inventory.models import PriceListItem
from apps.estimates.models import EstWorksheet, WorkTemplate
from apps.jobs.models import Job


class PopulateFromPliCopiesUnitsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","ea","sheets","lbs","hours"]')
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.pli = PriceListItem.objects.create(
            code='PLI-1', units='sheets', description='Steel Sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(name='J', job_number='J-1', status=Job.STATUS_DRAFT)

    def test_material_pulls_units_from_pli(self):
        m = Material(
            job=self.job, price_list_item=self.pli,
            quantity=Decimal('1'),
        )
        m.save()
        self.assertEqual(m.units, 'sheets')

    def test_material_keeps_explicit_units_when_set(self):
        # Override case: caller supplies a non-default 'units'; PLI does not overwrite.
        m = Material(
            job=self.job, price_list_item=self.pli,
            quantity=Decimal('1'), units='lbs',
        )
        m.save()
        self.assertEqual(m.units, 'lbs')

    def test_freeform_material_keeps_default_units(self):
        m = Material(
            job=self.job, price_list_item=None,
            quantity=Decimal('1'),
        )
        m.save()
        self.assertEqual(m.units, 'none')

    def test_plan_material_pulls_units_from_pli(self):
        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        pm = PlanMaterial(
            est_worksheet=ws, price_list_item=self.pli, quantity=Decimal('1'),
        )
        pm.save()
        self.assertEqual(pm.units, 'sheets')

    def test_template_material_pulls_units_from_pli(self):
        wt = WorkTemplate.objects.create(template_name='T')
        tm = TemplateMaterial(
            work_template=wt, price_list_item=self.pli, quantity=Decimal('1'),
        )
        tm.save()
        self.assertEqual(tm.units, 'sheets')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_material_units_field.PopulateFromPliCopiesUnitsTests -v 2`

Expected: 5 FAILs, all asserting `'none' != 'sheets'` (or similar), because `_populate_from_pli` doesn't copy `units` yet.

- [ ] **Step 3: Update `MaterialBase._populate_from_pli`**

In `apps/inventory/models.py`, modify the method:

```python
def _populate_from_pli(self):
    """Copy description/units/unit_cost/sell_price/accounting_category from linked PriceListItem if not already set."""
    if self.price_list_item:
        if not self.description:
            self.description = self.price_list_item.description[:255]
        if self.units == 'none' or not self.units:
            self.units = self.price_list_item.units
        if self.unit_cost == Decimal('0.00'):
            self.unit_cost = self.price_list_item.purchase_price
        if self.sell_price == Decimal('0.00'):
            self.sell_price = self.price_list_item.selling_price
        if not self.accounting_category:
            self.accounting_category = self.price_list_item.accounting_category
```

The `'none' or not self.units` guard mirrors `BaseLineItem._populate_from_pli` at `apps/core/models.py:264`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_material_units_field -v 2`

Expected: all 8 tests PASS (3 from Task 1 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/models.py tests/test_material_units_field.py
git commit -m "feat: _populate_from_pli copies units from linked PriceListItem

Materials linked to a PriceListItem inherit the PLI's units when the
material has the default value. Explicit overrides are preserved
(matches BaseLineItem._populate_from_pli precedent). Freeform
materials with no PLI keep the 'none' default."
```

### Task 3: API read serializers expose `units` as a real model field

The current code uses `SerializerMethodField` hacks that read through `obj.price_list_item.units`. With the field on the model, those become real fields. This task covers all three read serializers:

- `MaterialSerializer` — `apps/api/inventory/serializers.py:33,77-78`
- `PlanMaterialSerializer` — `apps/api/worksheets/serializers.py:9,20-21`
- (TemplateMaterial serializer doesn't have a units SerializerMethodField yet — it just lacks the field; we'll add it directly.)

**Files:**
- Modify: `apps/api/inventory/serializers.py`
- Modify: `apps/api/worksheets/serializers.py`
- Modify: `apps/api/templates_config/serializers.py`
- Modify: `apps/api/tasks/serializers.py` (also has `MaterialSerializer` and `MaterialWriteSerializer`)
- Test: `tests/test_material_units_field.py` (extend)

- [ ] **Step 1: Write failing test for serializer behavior**

Append to `tests/test_material_units_field.py`:

```python
from rest_framework.test import APITestCase
from apps.core.models import User


class MaterialSerializerUnitsTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","ea","sheets","lbs"]')
        cls.user = User.objects.create_user(username='u', password='p')
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.pli = PriceListItem.objects.create(
            code='PLI-1', units='sheets', description='Steel Sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(name='J', job_number='J-1', status=Job.STATUS_DRAFT)

    def setUp(self):
        self.client.force_login(self.user)

    def test_material_get_returns_units_from_field(self):
        m = Material.objects.create(
            job=self.job, price_list_item=self.pli, quantity=Decimal('1'),
        )
        # Override the units to something different from the PLI; verify the GET
        # returns the field value (override) rather than the PLI's value.
        Material.objects.filter(pk=m.pk).update(units='lbs')
        resp = self.client.get(f'/api/materials/{m.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['units'], 'lbs')

    def test_freeform_material_get_returns_units_field(self):
        m = Material.objects.create(
            job=self.job, price_list_item=None,
            description='custom', quantity=Decimal('1'), units='ea',
        )
        resp = self.client.get(f'/api/materials/{m.pk}/')
        self.assertEqual(resp.json()['units'], 'ea')
```

- [ ] **Step 2: Run test to verify failure**

Run: `python manage.py test tests.test_material_units_field.MaterialSerializerUnitsTests -v 2`

Expected: `test_material_get_returns_units_from_field` FAILS — current serializer returns `'sheets'` (PLI's value) not `'lbs'` (the override). `test_freeform_material_get_returns_units_field` may pass coincidentally because both freeform and the field default to `'none'`/`'ea'` consistently.

- [ ] **Step 3: Replace SerializerMethodField with direct field — `MaterialSerializer` (inventory)**

Edit `apps/api/inventory/serializers.py`:

```python
from apps.core.units import UnitsField

class MaterialSerializer(serializers.ModelSerializer):
    is_expense_bound = serializers.BooleanField(read_only=True)
    price_list_item_is_inventoried = serializers.SerializerMethodField()
    po_line_item_id = serializers.SerializerMethodField()
    po_id = serializers.SerializerMethodField()
    po_number = serializers.SerializerMethodField()
    po_status = serializers.SerializerMethodField()
    units = UnitsField()
    qty_on_order = serializers.SerializerMethodField()
    qty_on_hand = serializers.SerializerMethodField()
    # ...rest unchanged...
```

Remove the `get_units` method (lines 77-78). The `units` field list entry stays unchanged. **Remove `'units'` from the `read_only_fields` list** — units is now writable in some paths (covered in Phase 3).

- [ ] **Step 4: Replace SerializerMethodField — `PlanMaterialSerializer`**

Edit `apps/api/worksheets/serializers.py`:

```python
from apps.core.units import UnitsField

class PlanMaterialSerializer(serializers.ModelSerializer):
    units = UnitsField()

    class Meta:
        model = PlanMaterial
        fields = [
            'plan_material_id', 'description', 'quantity',
            'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category', 'units',
        ]
        read_only_fields = [
            'plan_material_id', 'description', 'quantity',
            'unit_cost', 'sell_price', 'price_list_item', 'accounting_category',
        ]
```

(`PlanMaterialSerializer` was entirely read-only before; keep that. The write path uses `PlanMaterialWriteSerializer`.)

Remove the `get_units` method.

- [ ] **Step 5: Add `units` to `PlanMaterialWriteSerializer`**

Same file:

```python
class PlanMaterialWriteSerializer(serializers.ModelSerializer):
    units = UnitsField(required=False)

    class Meta:
        model = PlanMaterial
        fields = [
            'plan_material_id', 'plan_task', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'price_list_item', 'accounting_category',
        ]
        read_only_fields = ['plan_material_id']
```

- [ ] **Step 6: Add `units` to `TemplateMaterialSerializer`**

Edit `apps/api/templates_config/serializers.py`:

```python
from apps.core.units import UnitsField

class TemplateMaterialSerializer(serializers.ModelSerializer):
    units = UnitsField(required=False)

    class Meta:
        model = TemplateMaterial
        fields = [
            'template_material_id', 'work_template', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'price_list_item', 'accounting_category',
            'sort_order',
        ]
        read_only_fields = ['template_material_id', 'work_template']
```

- [ ] **Step 7: Add `units` to `MaterialWriteSerializer` (apps/api/tasks/serializers.py)**

Edit `apps/api/tasks/serializers.py`:

```python
from apps.core.units import UnitsField

class MaterialWriteSerializer(serializers.ModelSerializer):
    units = UnitsField(required=False)

    class Meta:
        model = Material
        fields = [
            'material_id', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category',
        ]
        read_only_fields = ['material_id']
```

There's also a `MaterialSerializer` (read) at the top of this file used by the task-scoped materials endpoint. Add `units` to its fields list:

```python
class MaterialSerializer(serializers.ModelSerializer):
    is_expense_bound = serializers.BooleanField(read_only=True)
    price_list_item_is_inventoried = serializers.SerializerMethodField()

    class Meta:
        model = Material
        fields = [
            'material_id', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category',
            'consumption_state', 'restocked_qty',
            'is_expense_bound', 'price_list_item_is_inventoried',
        ]
        read_only_fields = fields
```

- [ ] **Step 8: Run the units-field tests; expect all to pass**

Run: `python manage.py test tests.test_material_units_field -v 2`

Expected: all PASS.

- [ ] **Step 9: Run the broader test suites that touch material serializers — confirm no regressions**

Run: `python manage.py test tests.test_api_materials tests.test_api_job_tasklist tests.test_material -v 2`

Expected: all PASS. If anything fails, the `units` addition has shifted serializer output in a way the existing test asserts on — fix the test (the new field is genuinely new output) before continuing.

- [ ] **Step 10: Commit**

```bash
git add apps/api/inventory/serializers.py apps/api/worksheets/serializers.py apps/api/templates_config/serializers.py apps/api/tasks/serializers.py tests/test_material_units_field.py
git commit -m "feat: expose units as a direct serializer field on Material/PlanMaterial/TemplateMaterial

Replaces SerializerMethodField hacks that read through
obj.price_list_item.units with a real UnitsField bound to the new
model field. Reads now respect explicit overrides on the material
row rather than always re-deriving from the PLI."
```

---

## Phase 2 — Carry-over paths copy `units`

Every code path that creates one Material-flavoured row from another now needs to copy `units` alongside the other `MaterialBase` fields. These are mechanical additions; no design decisions.

### Task 4: `JobService.copy_from_worksheet` carries `units`

**Files:**
- Modify: `apps/jobs/services.py` (`JobService.copy_from_worksheet`)
- Test: `tests/test_jobs_services.py` (extend) — or add `tests/test_material_units_carry_over.py` if you prefer a focused file

- [ ] **Step 1: Write the failing test**

Add to `tests/test_jobs_services.py` (or create the new file):

```python
def test_copy_from_worksheet_carries_units_on_plan_materials(self):
    # Setup: a worksheet with a freeform PlanMaterial whose units differ from default.
    ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
    pt = PlanTask.objects.create(
        est_worksheet=ws, name='T', sort_order=1, est_qty=Decimal('1'),
    )
    PlanMaterial.objects.create(
        est_worksheet=ws, plan_task=pt,
        description='custom', quantity=Decimal('5'), units='lbs',
        unit_cost=Decimal('2.00'), sell_price=Decimal('3.00'),
    )
    PlanMaterial.objects.create(
        est_worksheet=ws, plan_task=None,
        description='loose', quantity=Decimal('2'), units='ea',
        unit_cost=Decimal('1.00'), sell_price=Decimal('2.00'),
    )
    new_job = Job.objects.create(name='J2', job_number='J-2', status=Job.STATUS_DRAFT)

    JobService.copy_from_worksheet(new_job.pk, ws.pk)

    task_mat = Material.objects.get(job=new_job, task__isnull=False)
    self.assertEqual(task_mat.units, 'lbs')
    loose_mat = Material.objects.get(job=new_job, task__isnull=True)
    self.assertEqual(loose_mat.units, 'ea')
```

- [ ] **Step 2: Run test, verify failure**

Run: `python manage.py test tests.test_jobs_services.<TestClass>.test_copy_from_worksheet_carries_units_on_plan_materials -v 2`

Expected: FAIL — `'none' != 'lbs'`. The current `copy_from_worksheet` doesn't pass `units` to `MaterialService.create_on_job`, so the new Material gets the field default.

- [ ] **Step 3: Update `JobService.copy_from_worksheet`**

In `apps/jobs/services.py` around lines 343-352 and 354-363, add `units=pm.units` to both `MaterialService.create_on_job` calls:

```python
for pm in plan_task.plan_materials.all():
    MaterialService.create_on_job(
        job=job, task=new_task,
        description=pm.description,
        quantity=pm.quantity,
        units=pm.units,
        unit_cost=pm.unit_cost,
        sell_price=pm.sell_price,
        price_list_item=pm.price_list_item,
        accounting_category=pm.accounting_category,
    )

for pm in ws.plan_materials.filter(plan_task__isnull=True):
    MaterialService.create_on_job(
        job=job, task=None,
        description=pm.description,
        quantity=pm.quantity,
        units=pm.units,
        unit_cost=pm.unit_cost,
        sell_price=pm.sell_price,
        price_list_item=pm.price_list_item,
        accounting_category=pm.accounting_category,
    )
```

- [ ] **Step 4: Update `MaterialService.create_on_job` to accept `units`**

In `apps/inventory/services.py:292-307`:

```python
@staticmethod
def create_on_job(*, job, task=None, description='', quantity=Decimal('0.00'),
                  units='none',
                  unit_cost=Decimal('0.00'), sell_price=Decimal('0.00'),
                  price_list_item=None, accounting_category=None):
    from django.db import transaction
    with transaction.atomic():
        m = Material(
            job=job, task=task,
            description=description, quantity=quantity,
            units=units,
            unit_cost=unit_cost, sell_price=sell_price,
            price_list_item=price_list_item,
            accounting_category=accounting_category,
        )
        m.save()  # full_clean() runs here; enforces task/job invariant
        InventoryService._mutate_earmark(price_list_item, job, quantity)
    return m
```

- [ ] **Step 5: Run test, verify pass**

Run: `python manage.py test tests.test_jobs_services -v 2`

Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/services.py apps/inventory/services.py tests/test_jobs_services.py
git commit -m "feat: copy_from_worksheet carries units onto generated Materials

MaterialService.create_on_job now accepts a units kwarg with default
'none'. JobService.copy_from_worksheet passes pm.units through both
the task-attached and task-less Material creation loops."
```

### Task 5: `EstimateWizardService._atom_units` reads from `pm.units`

PlanMaterial → EstimateLineItem conversion lives in `EstimateWizardService.send_all_atoms_to_estimate` (`apps/estimates/services.py:872-940`) and the multi-atom claim flow around line 749. Both paths already use `EstimateWizardService._atom_units(pm)` to compute the `units` value passed into `EstimateLineItem.objects.create`. The only code change required is to make `_atom_units` read from the PlanMaterial's own `units` field instead of `pm.price_list_item.units`. Once that flips, all line-item paths inherit the new behavior automatically.

**Files:**
- Modify: `apps/estimates/services.py` — `_atom_units` (lines 599-613)
- Test: `tests/test_estimate_units_from_plan_material.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_estimate_units_from_plan_material.py
from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory, Configuration
from apps.inventory.models import PriceListItem, PlanMaterial
from apps.estimates.models import EstWorksheet, EstimateLineItem
from apps.estimates.services import EstimateWizardService
from apps.jobs.models import Job


class AtomUnitsFromPlanMaterialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","ea","sheets","lbs","hours"]')
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.pli = PriceListItem.objects.create(
            code='PLI-1', units='sheets', description='Steel Sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(name='J', job_number='J-1', status=Job.STATUS_DRAFT)

    def test_atom_units_returns_plan_material_field_freeform(self):
        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        pm = PlanMaterial.objects.create(
            est_worksheet=ws, plan_task=None,
            description='loose', quantity=Decimal('5'), units='lbs',
            unit_cost=Decimal('1.00'), sell_price=Decimal('2.00'),
        )
        self.assertEqual(EstimateWizardService._atom_units(pm), 'lbs')

    def test_atom_units_returns_plan_material_field_pli_linked(self):
        # PlanMaterial linked to a PLI with units='sheets' inherits that on save.
        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        pm = PlanMaterial.objects.create(
            est_worksheet=ws, plan_task=None,
            quantity=Decimal('1'), price_list_item=self.pli,
        )
        # _populate_from_pli should have set pm.units = 'sheets'.
        self.assertEqual(pm.units, 'sheets')
        self.assertEqual(EstimateWizardService._atom_units(pm), 'sheets')

    def test_send_all_atoms_to_estimate_carries_pm_units(self):
        # End-to-end: a freeform PlanMaterial on a worksheet → bulk-converted
        # to an EstimateLineItem; the line item's units mirrors the PM's.
        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        PlanMaterial.objects.create(
            est_worksheet=ws, plan_task=None,
            description='loose', quantity=Decimal('5'), units='lbs',
            unit_cost=Decimal('1.00'), sell_price=Decimal('2.00'),
        )
        result = EstimateWizardService.send_all_atoms_to_estimate(ws)
        self.assertEqual(result['created_count'], 1)
        li = EstimateLineItem.objects.get(estimate=result['estimate'])
        self.assertEqual(li.units, 'lbs')
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_estimate_units_from_plan_material -v 2`

Expected: `test_atom_units_returns_plan_material_field_freeform` FAILS with `'none' != 'lbs'` — current `_atom_units` returns `'none'` for freeform PMs (no PLI to read from). The other two might pass coincidentally because the PLI's units happen to match.

- [ ] **Step 3: Update `_atom_units`**

Replace the current body at `apps/estimates/services.py:599-613` with:

```python
@staticmethod
def _atom_units(atom_instance):
    """Return the units label for an atom.

    PlanTask: from rate_scheme.unit_label (or 'none' if no scheme).
    PlanMaterial: from the atom's own units field (which is populated
                  from the linked PLI at create time via _populate_from_pli,
                  so PLI-linked PMs reflect the PLI's units; freeform PMs
                  carry whatever units the user set).
    """
    from apps.jobs.models import PlanTask
    from apps.inventory.models import PlanMaterial
    if isinstance(atom_instance, PlanTask):
        if atom_instance.rate_scheme_id:
            return atom_instance.rate_scheme.unit_label
        return 'none'
    if isinstance(atom_instance, PlanMaterial):
        return atom_instance.units or 'none'
    return 'none'
```

- [ ] **Step 4: Run, verify pass**

Run: `python manage.py test tests.test_estimate_units_from_plan_material tests.test_estimates_services tests.test_estimate_wizard_service tests.test_estimate_wizard_api -v 2`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/services.py tests/test_estimate_units_from_plan_material.py
git commit -m "feat: _atom_units reads from PlanMaterial.units field

EstimateWizardService._atom_units now reads atom_instance.units for
PlanMaterial atoms instead of reaching through to
atom_instance.price_list_item.units. This carries user-set units on
freeform PlanMaterials through to generated EstimateLineItems and
respects PLI-derived units (via _populate_from_pli) on linked PMs."
```

---

## Phase 3 — PLI-linked rows are immutable (except for pricing)

The core behavior change. PATCH on a PLI-linked Material/PlanMaterial accepts only `unit_cost`, `sell_price`, and the `propagate_to_pli` flag. Anything else returns 400. Freeform rows accept the labelling/pricing fields.

There are **three Material PATCH paths** in the codebase (the immutability rule must apply to all):

1. `PATCH /api/materials/{id}/` — `MaterialViewSet` in `apps/api/inventory/views.py`, uses `MaterialSerializer.update()` (which currently restricts to `{'description'}`).
2. `PATCH /api/tasks/{id}/materials/{mid}/` — `TaskViewSet.material_detail` in `apps/api/tasks/views.py:74-118`, uses `MaterialWriteSerializer`.
3. `PATCH /api/est-worksheets/{id}/plan-materials/{mid}/` — for PlanMaterial in `apps/api/worksheets/views.py:168`.
4. `PATCH /api/plan-tasks/{id}/materials/{mid}/` — task-scoped PlanMaterial in `apps/api/plan_tasks/views.py:71`.
5. `PATCH /api/work-templates/{id}/materials/{mid}/` — TemplateMaterial in `apps/api/templates_config/views.py:59`.

Strategy: centralize the immutability check in a small helper on each write serializer. Each affected serializer's `update()` method calls it.

### Task 6: Failing tests — PATCH rejects locked-field edits on PLI-linked rows

**Files:**
- Test: `tests/test_material_immutability.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_material_immutability.py
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APITestCase
from apps.core.models import AccountingCategory, Configuration, User
from apps.inventory.models import (
    Material, PlanMaterial, TemplateMaterial, PriceListItem,
)
from apps.estimates.models import EstWorksheet, WorkTemplate
from apps.jobs.models import Job, Task, PlanTask


class _Setup(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","ea","sheets","lbs","hours"]')
        cls.user = User.objects.create_user(username='u', password='p')
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.pli = PriceListItem.objects.create(
            code='PLI-1', units='sheets', description='Steel Sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(name='J', job_number='J-1', status=Job.STATUS_DRAFT)

    def setUp(self):
        self.client.force_login(self.user)


class MaterialImmutabilityTests(_Setup):
    def test_patch_pli_linked_material_description_rejected(self):
        m = Material.objects.create(
            job=self.job, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'description': 'NEW'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('immutable', resp.json().get('detail', '').lower())

    def test_patch_pli_linked_material_units_rejected(self):
        m = Material.objects.create(
            job=self.job, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'units': 'lbs'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_pli_linked_material_unit_cost_allowed(self):
        m = Material.objects.create(
            job=self.job, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'unit_cost': '52.00'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertEqual(m.unit_cost, Decimal('52.00'))

    def test_patch_freeform_material_description_allowed(self):
        m = Material.objects.create(
            job=self.job, price_list_item=None,
            description='start', quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'description': 'NEW'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)

    def test_patch_freeform_material_units_allowed(self):
        m = Material.objects.create(
            job=self.job, price_list_item=None,
            description='x', quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'units': 'lbs'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertEqual(m.units, 'lbs')


class PlanMaterialImmutabilityTests(_Setup):
    def test_patch_pli_linked_plan_material_description_rejected(self):
        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        pm = PlanMaterial.objects.create(
            est_worksheet=ws, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/est-worksheets/{ws.pk}/plan-materials/{pm.pk}/',
            {'description': 'NEW'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_pli_linked_plan_material_unit_cost_allowed(self):
        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        pm = PlanMaterial.objects.create(
            est_worksheet=ws, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/est-worksheets/{ws.pk}/plan-materials/{pm.pk}/',
            {'unit_cost': '52.00'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)


class TemplateMaterialImmutabilityTests(_Setup):
    def test_patch_pli_linked_template_material_description_rejected(self):
        wt = WorkTemplate.objects.create(template_name='T')
        tm = TemplateMaterial.objects.create(
            work_template=wt, price_list_item=self.pli, quantity=Decimal('1'),
        )
        # User needs can_manage_config to PATCH templates; grant it.
        from django.contrib.auth.models import Permission
        self.user.user_permissions.add(Permission.objects.get(codename='can_manage_config'))
        resp = self.client.patch(
            f'/api/work-templates/{wt.pk}/materials/{tm.pk}/',
            {'description': 'NEW'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_pli_linked_template_material_unit_cost_rejected(self):
        # TemplateMaterial does NOT get the pricing carve-out.
        wt = WorkTemplate.objects.create(template_name='T')
        tm = TemplateMaterial.objects.create(
            work_template=wt, price_list_item=self.pli, quantity=Decimal('1'),
        )
        from django.contrib.auth.models import Permission
        self.user.user_permissions.add(Permission.objects.get(codename='can_manage_config'))
        resp = self.client.patch(
            f'/api/work-templates/{wt.pk}/materials/{tm.pk}/',
            {'unit_cost': '52.00'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_pli_linked_template_material_quantity_allowed(self):
        wt = WorkTemplate.objects.create(template_name='T')
        tm = TemplateMaterial.objects.create(
            work_template=wt, price_list_item=self.pli, quantity=Decimal('1'),
        )
        from django.contrib.auth.models import Permission
        self.user.user_permissions.add(Permission.objects.get(codename='can_manage_config'))
        resp = self.client.patch(
            f'/api/work-templates/{wt.pk}/materials/{tm.pk}/',
            {'quantity': '5.00'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_material_immutability -v 2`

Expected: most fail. The `freeform` tests may pass since current code allows description edits on freeform; the locked-field tests will fail because today's code doesn't check the PLI.

- [ ] **Step 3: Add a shared immutability helper**

Create `apps/inventory/serializer_helpers.py`:

```python
from rest_framework import serializers


# Fields editable on PLI-linked Material / PlanMaterial. TemplateMaterial
# has no pricing carve-out and uses an empty allowlist instead.
PLI_LINKED_PRICING_ALLOWED = {'unit_cost', 'sell_price', 'propagate_to_pli'}

# Fields editable on freeform (no PLI) Material / PlanMaterial.
FREEFORM_ALLOWED = {
    'description', 'units', 'unit_cost', 'sell_price', 'accounting_category',
}


def enforce_pli_linked_allowlist(instance, validated_data, allowed):
    """Raise serializers.ValidationError if validated_data has any field
    outside `allowed` while the instance is PLI-linked.

    `allowed` is a set of field names. Use PLI_LINKED_PRICING_ALLOWED for
    Material/PlanMaterial; pass set() for TemplateMaterial.
    """
    if instance.price_list_item_id is None:
        return
    disallowed = set(validated_data.keys()) - allowed
    if disallowed:
        raise serializers.ValidationError({
            'detail': (
                'PLI-linked materials are immutable except for pricing; '
                'delete and re-add as freeform to change other fields. '
                f'Disallowed fields: {sorted(disallowed)}'
            )
        })
```

- [ ] **Step 4: Update `MaterialSerializer.update()` (apps/api/inventory/serializers.py)**

Replace the existing `update` method:

```python
def update(self, instance, validated_data):
    from apps.inventory.serializer_helpers import (
        enforce_pli_linked_allowlist, PLI_LINKED_PRICING_ALLOWED, FREEFORM_ALLOWED,
    )
    if instance.price_list_item_id is not None:
        enforce_pli_linked_allowlist(
            instance, validated_data, PLI_LINKED_PRICING_ALLOWED,
        )
    else:
        disallowed = set(validated_data.keys()) - FREEFORM_ALLOWED
        if disallowed:
            raise serializers.ValidationError({
                'detail': f'Disallowed fields on freeform Material: {sorted(disallowed)}',
            })
    # propagate_to_pli is handled separately by the view; strip before saving.
    validated_data.pop('propagate_to_pli', None)
    return super().update(instance, validated_data)
```

Add `propagate_to_pli` as a write-only boolean on the serializer:

```python
class MaterialSerializer(serializers.ModelSerializer):
    # ... existing fields ...
    propagate_to_pli = serializers.BooleanField(
        write_only=True, required=False, default=False,
    )

    class Meta:
        model = Material
        fields = [
            # ...existing list, add:
            'propagate_to_pli',
        ]
```

(Don't add `propagate_to_pli` to `read_only_fields`. The `propagate_to_pli` flag is for Phase 4 — at this phase, we accept it but ignore it; tests in this phase don't exercise it.)

- [ ] **Step 5: Update `MaterialWriteSerializer` (apps/api/tasks/serializers.py)**

Add a `update()` method using the same helper:

```python
class MaterialWriteSerializer(serializers.ModelSerializer):
    units = UnitsField(required=False)
    propagate_to_pli = serializers.BooleanField(
        write_only=True, required=False, default=False,
    )

    class Meta:
        model = Material
        fields = [
            'material_id', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category', 'propagate_to_pli',
        ]
        read_only_fields = ['material_id']

    def update(self, instance, validated_data):
        from apps.inventory.serializer_helpers import (
            enforce_pli_linked_allowlist, PLI_LINKED_PRICING_ALLOWED, FREEFORM_ALLOWED,
        )
        if instance.price_list_item_id is not None:
            enforce_pli_linked_allowlist(
                instance, validated_data, PLI_LINKED_PRICING_ALLOWED,
            )
        else:
            disallowed = set(validated_data.keys()) - FREEFORM_ALLOWED
            if disallowed:
                raise serializers.ValidationError({
                    'detail': f'Disallowed fields on freeform Material: {sorted(disallowed)}',
                })
        validated_data.pop('propagate_to_pli', None)
        return super().update(instance, validated_data)
```

- [ ] **Step 6: Update `PlanMaterialWriteSerializer` (apps/api/worksheets/serializers.py)**

Same pattern:

```python
class PlanMaterialWriteSerializer(serializers.ModelSerializer):
    units = UnitsField(required=False)
    propagate_to_pli = serializers.BooleanField(
        write_only=True, required=False, default=False,
    )

    class Meta:
        model = PlanMaterial
        fields = [
            'plan_material_id', 'plan_task', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category', 'propagate_to_pli',
        ]
        read_only_fields = ['plan_material_id']

    def update(self, instance, validated_data):
        from apps.inventory.serializer_helpers import (
            enforce_pli_linked_allowlist, PLI_LINKED_PRICING_ALLOWED, FREEFORM_ALLOWED,
        )
        # plan_task is reassignable on both freeform and PLI-linked rows;
        # it's not a MaterialBase field and is allowed independently.
        scratch = dict(validated_data)
        scratch.pop('plan_task', None)
        if instance.price_list_item_id is not None:
            enforce_pli_linked_allowlist(
                instance, scratch, PLI_LINKED_PRICING_ALLOWED,
            )
        else:
            disallowed = set(scratch.keys()) - FREEFORM_ALLOWED
            if disallowed:
                raise serializers.ValidationError({
                    'detail': f'Disallowed fields on freeform PlanMaterial: {sorted(disallowed)}',
                })
        validated_data.pop('propagate_to_pli', None)
        return super().update(instance, validated_data)
```

- [ ] **Step 7: Update `TemplateMaterialSerializer` (apps/api/templates_config/serializers.py)**

TemplateMaterial allowlists are stricter:

```python
TEMPLATE_PLI_LINKED_ALLOWED = {'quantity', 'sort_order'}
TEMPLATE_FREEFORM_ALLOWED = {
    'description', 'units', 'quantity', 'unit_cost', 'sell_price',
    'accounting_category', 'sort_order',
}


class TemplateMaterialSerializer(serializers.ModelSerializer):
    units = UnitsField(required=False)

    class Meta:
        model = TemplateMaterial
        fields = [
            'template_material_id', 'work_template', 'description', 'quantity',
            'units', 'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category', 'sort_order',
        ]
        read_only_fields = ['template_material_id', 'work_template']

    def update(self, instance, validated_data):
        if instance.price_list_item_id is not None:
            disallowed = set(validated_data.keys()) - TEMPLATE_PLI_LINKED_ALLOWED
            if disallowed:
                raise serializers.ValidationError({
                    'detail': (
                        'PLI-linked TemplateMaterials are immutable except for quantity and sort_order; '
                        f'disallowed fields: {sorted(disallowed)}'
                    )
                })
        else:
            disallowed = set(validated_data.keys()) - TEMPLATE_FREEFORM_ALLOWED
            if disallowed:
                raise serializers.ValidationError({
                    'detail': f'Disallowed fields on freeform TemplateMaterial: {sorted(disallowed)}',
                })
        return super().update(instance, validated_data)
```

- [ ] **Step 8: Update `TaskViewSet.material_detail` PATCH path**

The task-scoped PATCH at `apps/api/tasks/views.py:74-118` currently has its own quantity-field check. The new `MaterialWriteSerializer.update()` handles the immutability rule, so the manual `QUANTITY_FIELDS` check can stay (defense-in-depth) but the field setting loop is fine:

Verify the existing code at lines 113-118 still works:

```python
serializer = MaterialWriteSerializer(material, data=request.data, partial=True)
serializer.is_valid(raise_exception=True)
serializer.save()  # was: setattr loop + material.save()
return Response(MaterialSerializer(material).data)
```

Change the setattr loop to `serializer.save()` so the serializer's `update()` method runs and the immutability check fires. The current code bypasses `update()` by setting fields manually.

- [ ] **Step 9: Run the immutability tests**

Run: `python manage.py test tests.test_material_immutability -v 2`

Expected: PASS for all tests.

- [ ] **Step 10: Run regression suites**

Run: `python manage.py test tests.test_api_materials tests.test_api_job_tasklist tests.test_material tests.test_estimates_services tests.test_jobs_services -v 2`

Expected: PASS. If anything fails, an existing test was relying on a now-blocked PATCH (e.g., editing `description` on a PLI-linked Material). Update that test to either work with a freeform Material or to assert the new 400.

- [ ] **Step 11: Commit**

```bash
git add apps/inventory/serializer_helpers.py apps/api/inventory/serializers.py apps/api/tasks/serializers.py apps/api/worksheets/serializers.py apps/api/templates_config/serializers.py apps/api/tasks/views.py tests/test_material_immutability.py
git commit -m "feat: enforce immutability on PLI-linked Material/PlanMaterial/TemplateMaterial

PATCH on a PLI-linked Material or PlanMaterial accepts only unit_cost,
sell_price, and the propagate_to_pli flag. PLI-linked TemplateMaterial
accepts only quantity and sort_order. Anything else returns 400 with
'PLI-linked materials are immutable...' and a list of the disallowed
fields. Freeform rows (no PLI link) accept the labelling and pricing
field set on PATCH as before.

The propagate_to_pli flag is accepted but ignored at this layer;
Phase 4 wires it through MaterialService for atomic catalog updates."
```

---

## Phase 4 — `propagate_to_pli` flag wires PLI catalog updates

When `propagate_to_pli=true` is sent with a pricing PATCH on a PLI-linked Material or PlanMaterial, the linked PLI's `purchase_price` / `selling_price` updates atomically alongside the row update. No permission check — open to any authenticated user (deliberate carve-out from `can_manage_financials`).

### Task 7: `MaterialService.update_pricing` and `PlanMaterialService.update_pricing` propagate to PLI

**Files:**
- Modify: `apps/inventory/services.py` — add `MaterialService.update_pricing` and a parallel for PlanMaterial
- Modify: `apps/api/inventory/views.py`, `apps/api/tasks/views.py`, `apps/api/worksheets/views.py`, `apps/api/plan_tasks/views.py` — call the new service methods on PATCH
- Test: `tests/test_material_propagate_to_pli.py` (create)

- [ ] **Step 1: Failing test for `propagate_to_pli=true` updating PLI**

```python
# tests/test_material_propagate_to_pli.py
from decimal import Decimal
from rest_framework.test import APITestCase
from apps.core.models import AccountingCategory, Configuration, User
from apps.inventory.models import Material, PlanMaterial, PriceListItem
from apps.estimates.models import EstWorksheet
from apps.jobs.models import Job


class _Setup(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","sheets","ea"]')
        cls.user = User.objects.create_user(username='u', password='p')
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.pli = PriceListItem.objects.create(
            code='PLI-1', units='sheets', description='Steel Sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(name='J', job_number='J-1', status=Job.STATUS_DRAFT)

    def setUp(self):
        self.client.force_login(self.user)


class MaterialPropagateTests(_Setup):
    def test_propagate_true_updates_pli(self):
        m = Material.objects.create(
            job=self.job, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'unit_cost': '52.00', 'sell_price': '78.00', 'propagate_to_pli': True},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.pli.refresh_from_db()
        self.assertEqual(m.unit_cost, Decimal('52.00'))
        self.assertEqual(m.sell_price, Decimal('78.00'))
        self.assertEqual(self.pli.purchase_price, Decimal('52.00'))
        self.assertEqual(self.pli.selling_price, Decimal('78.00'))

    def test_propagate_false_leaves_pli_alone(self):
        m = Material.objects.create(
            job=self.job, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'unit_cost': '52.00', 'propagate_to_pli': False},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.pli.refresh_from_db()
        self.assertEqual(m.unit_cost, Decimal('52.00'))
        self.assertEqual(self.pli.purchase_price, Decimal('40.00'))  # unchanged

    def test_propagate_only_changed_field(self):
        # User edits only unit_cost; sell_price stays the same as the PLI.
        m = Material.objects.create(
            job=self.job, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'unit_cost': '52.00', 'propagate_to_pli': True},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.purchase_price, Decimal('52.00'))
        self.assertEqual(self.pli.selling_price, Decimal('60.00'))  # unchanged

    def test_propagate_works_for_user_without_can_manage_financials(self):
        # Permission carve-out: any authenticated user can propagate.
        # self.user has no can_manage_financials by default.
        self.assertFalse(self.user.has_perm('core.can_manage_financials'))
        m = Material.objects.create(
            job=self.job, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/materials/{m.pk}/',
            {'unit_cost': '52.00', 'propagate_to_pli': True},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.purchase_price, Decimal('52.00'))


class PlanMaterialPropagateTests(_Setup):
    def test_propagate_via_plan_material_updates_pli(self):
        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        pm = PlanMaterial.objects.create(
            est_worksheet=ws, price_list_item=self.pli, quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/est-worksheets/{ws.pk}/plan-materials/{pm.pk}/',
            {'unit_cost': '52.00', 'sell_price': '78.00', 'propagate_to_pli': True},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.purchase_price, Decimal('52.00'))
        self.assertEqual(self.pli.selling_price, Decimal('78.00'))
```

- [ ] **Step 2: Run tests, verify failures**

Run: `python manage.py test tests.test_material_propagate_to_pli -v 2`

Expected: all FAIL — the flag is currently stripped and ignored.

- [ ] **Step 3: Add `MaterialService.update_pricing`**

In `apps/inventory/services.py`, add:

```python
@staticmethod
def update_pricing(material, *, unit_cost=None, sell_price=None, propagate_to_pli=False):
    """Update unit_cost and/or sell_price on a Material. If propagate_to_pli is
    True and the Material is PLI-linked, also update the PLI's purchase_price /
    selling_price to match — but only for fields that actually changed.

    No permission check: open to any authenticated user (deliberate carve-out
    from can_manage_financials per design).
    """
    from django.db import transaction
    with transaction.atomic():
        update_fields = []
        cost_changed = False
        price_changed = False
        if unit_cost is not None and unit_cost != material.unit_cost:
            material.unit_cost = unit_cost
            update_fields.append('unit_cost')
            cost_changed = True
        if sell_price is not None and sell_price != material.sell_price:
            material.sell_price = sell_price
            update_fields.append('sell_price')
            price_changed = True
        if update_fields:
            material.save(update_fields=update_fields)

        if propagate_to_pli and material.price_list_item_id is not None:
            pli = material.price_list_item
            pli_fields = []
            if cost_changed and pli.purchase_price != material.unit_cost:
                pli.purchase_price = material.unit_cost
                pli_fields.append('purchase_price')
            if price_changed and pli.selling_price != material.sell_price:
                pli.selling_price = material.sell_price
                pli_fields.append('selling_price')
            if pli_fields:
                pli.save(update_fields=pli_fields)
    return material
```

Add a parallel for PlanMaterial in `InventoryService` (since PlanMaterial CRUD lives there):

```python
@staticmethod
def update_plan_material_pricing(plan_material, *, unit_cost=None, sell_price=None, propagate_to_pli=False):
    """Same as MaterialService.update_pricing but for PlanMaterial."""
    from django.db import transaction
    with transaction.atomic():
        update_fields = []
        cost_changed = False
        price_changed = False
        if unit_cost is not None and unit_cost != plan_material.unit_cost:
            plan_material.unit_cost = unit_cost
            update_fields.append('unit_cost')
            cost_changed = True
        if sell_price is not None and sell_price != plan_material.sell_price:
            plan_material.sell_price = sell_price
            update_fields.append('sell_price')
            price_changed = True
        if update_fields:
            plan_material.save(update_fields=update_fields)

        if propagate_to_pli and plan_material.price_list_item_id is not None:
            pli = plan_material.price_list_item
            pli_fields = []
            if cost_changed and pli.purchase_price != plan_material.unit_cost:
                pli.purchase_price = plan_material.unit_cost
                pli_fields.append('purchase_price')
            if price_changed and pli.selling_price != plan_material.sell_price:
                pli.selling_price = plan_material.sell_price
                pli_fields.append('selling_price')
            if pli_fields:
                pli.save(update_fields=pli_fields)
    return plan_material
```

- [ ] **Step 4: Wire the views to the service for PLI-linked Material PATCH**

Edit `apps/api/inventory/views.py` `MaterialViewSet`. The default DRF `partial_update` calls `serializer.save()`, which calls `update()`. The serializer strips `propagate_to_pli` before `super().update()`. We need the propagation to happen — easiest is to override `partial_update`:

```python
def partial_update(self, request, *args, **kwargs):
    instance = self.get_object()
    serializer = self.get_serializer(instance, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    propagate = serializer.validated_data.get('propagate_to_pli', False)
    if instance.price_list_item_id is not None and (
        'unit_cost' in serializer.validated_data
        or 'sell_price' in serializer.validated_data
    ):
        # Pricing-only path on a PLI-linked instance: route through the service.
        unit_cost = serializer.validated_data.get('unit_cost')
        sell_price = serializer.validated_data.get('sell_price')
        MaterialService.update_pricing(
            instance,
            unit_cost=unit_cost, sell_price=sell_price,
            propagate_to_pli=propagate,
        )
        instance.refresh_from_db()
        return Response(MaterialSerializer(instance).data)
    # Freeform path or non-pricing fields: fall through to default save.
    serializer.save()
    return Response(MaterialSerializer(instance).data)
```

- [ ] **Step 5: Wire the task-scoped PATCH the same way**

`apps/api/tasks/views.py:74-118` (`material_detail`) — replace the `serializer.save()` call with the same branching:

```python
serializer = MaterialWriteSerializer(material, data=request.data, partial=True)
serializer.is_valid(raise_exception=True)
propagate = serializer.validated_data.get('propagate_to_pli', False)
if material.price_list_item_id is not None and (
    'unit_cost' in serializer.validated_data
    or 'sell_price' in serializer.validated_data
):
    MaterialService.update_pricing(
        material,
        unit_cost=serializer.validated_data.get('unit_cost'),
        sell_price=serializer.validated_data.get('sell_price'),
        propagate_to_pli=propagate,
    )
    material.refresh_from_db()
    return Response(MaterialSerializer(material).data)
serializer.save()
return Response(MaterialSerializer(material).data)
```

(Add `from apps.inventory.services import MaterialService` to the imports if not already.)

- [ ] **Step 6: Wire the worksheet plan-materials PATCH**

Edit `apps/api/worksheets/views.py` `plan_material_detail` action (around line 168). Same pattern with `InventoryService.update_plan_material_pricing`:

```python
# After serializer.is_valid:
propagate = serializer.validated_data.get('propagate_to_pli', False)
if pm.price_list_item_id is not None and (
    'unit_cost' in serializer.validated_data
    or 'sell_price' in serializer.validated_data
):
    InventoryService.update_plan_material_pricing(
        pm,
        unit_cost=serializer.validated_data.get('unit_cost'),
        sell_price=serializer.validated_data.get('sell_price'),
        propagate_to_pli=propagate,
    )
    pm.refresh_from_db()
    return Response(PlanMaterialSerializer(pm).data)
serializer.save()
return Response(PlanMaterialSerializer(pm).data)
```

- [ ] **Step 7: Wire the plan_tasks materials PATCH**

`apps/api/plan_tasks/views.py:71` — same pattern.

- [ ] **Step 8: Run the propagate tests**

Run: `python manage.py test tests.test_material_propagate_to_pli -v 2`

Expected: PASS.

- [ ] **Step 9: Regression run**

Run: `python manage.py test tests.test_api_materials tests.test_material_immutability tests.test_api_inventory tests.test_inventory_services tests.test_estimates_services -v 2`

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add apps/inventory/services.py apps/api/inventory/views.py apps/api/tasks/views.py apps/api/worksheets/views.py apps/api/plan_tasks/views.py tests/test_material_propagate_to_pli.py
git commit -m "feat: propagate_to_pli flag updates linked PLI on price PATCH

When a price PATCH on a PLI-linked Material or PlanMaterial includes
'propagate_to_pli': true, the linked PriceListItem's purchase_price /
selling_price are updated atomically — only the fields that actually
changed propagate. No permission check (carve-out from
can_manage_financials per design rationale)."
```

---

## Phase 5 — TemplateMaterial generation refactor

`WorkTemplate.generate_materials_for_worksheet` and `generate_materials_for_job` currently copy `unit_cost` and `sell_price` verbatim from the TemplateMaterial. After this refactor, PLI-linked TemplateMaterials carry only `quantity` and `price_list_item` to the generated row; `_populate_from_pli` pulls fresh values from the current PLI.

### Task 8: PLI-linked TemplateMaterial generation pulls current PLI pricing

**Files:**
- Modify: `apps/estimates/models.py` (`WorkTemplate.generate_materials_for_worksheet`, `generate_materials_for_job`)
- Test: `tests/test_template_materials.py` (or extend if exists; create otherwise)

- [ ] **Step 1: Failing test**

```python
# tests/test_template_materials_generation.py
from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory, Configuration
from apps.inventory.models import (
    Material, PlanMaterial, TemplateMaterial, PriceListItem,
)
from apps.estimates.models import EstWorksheet, WorkTemplate
from apps.jobs.models import Job


class TemplateMaterialGenerationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","sheets","ea"]')
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.pli = PriceListItem.objects.create(
            code='PLI-1', units='sheets', description='Steel Sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(name='J', job_number='J-1', status=Job.STATUS_DRAFT)

    def test_pli_linked_template_material_pulls_current_pli_pricing(self):
        # TemplateMaterial was set up with stale prices (40/60).
        wt = WorkTemplate.objects.create(template_name='T')
        tm = TemplateMaterial.objects.create(
            work_template=wt, price_list_item=self.pli, quantity=Decimal('5'),
        )
        # PLI's prices are bumped after the TemplateMaterial was created.
        self.pli.purchase_price = Decimal('52.00')
        self.pli.selling_price = Decimal('78.00')
        self.pli.save()

        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        wt.generate_materials_for_worksheet(ws, quantity=1)

        pm = PlanMaterial.objects.get(est_worksheet=ws, plan_task__isnull=True)
        self.assertEqual(pm.unit_cost, Decimal('52.00'))   # current PLI value
        self.assertEqual(pm.sell_price, Decimal('78.00'))  # current PLI value
        self.assertEqual(pm.units, 'sheets')               # from PLI
        self.assertEqual(pm.description, 'Steel Sheet')    # from PLI

    def test_freeform_template_material_carries_explicit_values(self):
        wt = WorkTemplate.objects.create(template_name='T')
        TemplateMaterial.objects.create(
            work_template=wt, price_list_item=None,
            description='custom thing', quantity=Decimal('3'),
            units='ea', unit_cost=Decimal('1.00'), sell_price=Decimal('2.00'),
        )
        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        wt.generate_materials_for_worksheet(ws, quantity=1)

        pm = PlanMaterial.objects.get(est_worksheet=ws, plan_task__isnull=True)
        self.assertEqual(pm.units, 'ea')
        self.assertEqual(pm.unit_cost, Decimal('1.00'))
        self.assertEqual(pm.sell_price, Decimal('2.00'))
        self.assertEqual(pm.description, 'custom thing')

    def test_generate_for_job_pli_linked_pulls_current(self):
        wt = WorkTemplate.objects.create(template_name='T')
        TemplateMaterial.objects.create(
            work_template=wt, price_list_item=self.pli, quantity=Decimal('5'),
        )
        self.pli.purchase_price = Decimal('52.00')
        self.pli.save()
        wt.generate_materials_for_job(self.job, quantity=1)
        m = Material.objects.get(job=self.job, task__isnull=True)
        self.assertEqual(m.unit_cost, Decimal('52.00'))
```

- [ ] **Step 2: Run tests, verify failure**

Run: `python manage.py test tests.test_template_materials_generation -v 2`

Expected: FAIL — `40.00 != 52.00`. Current generation copies the stale TemplateMaterial pricing.

- [ ] **Step 3: Refactor `generate_materials_for_worksheet`**

In `apps/estimates/models.py:344-357`:

```python
def generate_materials_for_worksheet(self, worksheet, quantity=1):
    from apps.inventory.models import PlanMaterial
    for tm in self.materials.all():
        for _ in range(quantity):
            if tm.price_list_item_id:
                # PLI-linked: only carry quantity + PLI link; _populate_from_pli
                # pulls description, units, pricing, and category fresh from
                # the current PLI.
                PlanMaterial.objects.create(
                    est_worksheet=worksheet,
                    plan_task=None,
                    quantity=tm.quantity,
                    price_list_item=tm.price_list_item,
                )
            else:
                # Freeform: template carries the explicit values.
                PlanMaterial.objects.create(
                    est_worksheet=worksheet,
                    plan_task=None,
                    description=tm.description,
                    quantity=tm.quantity,
                    units=tm.units,
                    unit_cost=tm.unit_cost,
                    sell_price=tm.sell_price,
                    accounting_category=tm.accounting_category,
                )
```

- [ ] **Step 4: Refactor `generate_materials_for_job`**

In `apps/estimates/models.py:359-371`:

```python
def generate_materials_for_job(self, job, quantity=1):
    from apps.inventory.services import MaterialService
    for tm in self.materials.all():
        for _ in range(quantity):
            if tm.price_list_item_id:
                MaterialService.create_on_job(
                    job=job, task=None,
                    quantity=tm.quantity,
                    price_list_item=tm.price_list_item,
                )
            else:
                MaterialService.create_on_job(
                    job=job, task=None,
                    description=tm.description,
                    quantity=tm.quantity,
                    units=tm.units,
                    unit_cost=tm.unit_cost,
                    sell_price=tm.sell_price,
                    accounting_category=tm.accounting_category,
                )
```

- [ ] **Step 5: Run tests, verify pass**

Run: `python manage.py test tests.test_template_materials_generation tests.test_template_workflows tests.test_new_templating -v 2`

Expected: PASS. If any existing template-workflow test was relying on the stale-snapshot behaviour, fix the test: it should set up a TemplateMaterial whose stored values match the PLI's, OR test the freeform path explicitly.

- [ ] **Step 6: Commit**

```bash
git add apps/estimates/models.py tests/test_template_materials_generation.py
git commit -m "feat: PLI-linked TemplateMaterial pulls fresh prices at generation

WorkTemplate.generate_materials_for_worksheet and generate_materials_for_job
now branch on tm.price_list_item_id. PLI-linked rows pass only quantity
and price_list_item to the new PlanMaterial/Material; _populate_from_pli
fills description, units, pricing, and accounting_category from the
*current* PLI. Freeform rows still copy explicit template values.

Resolves the stale-snapshot bug where a TemplateMaterial created months
ago kept injecting its frozen price into every new generation even after
the PLI's catalog price was updated."
```

---

## Phase 6 — Frontend (Svelte) updates

Update `MaterialModal.svelte`, `PlanMaterialModal.svelte`, and the TemplateMaterial editor (likely embedded in a WorkTemplate detail page) to:

1. Show a units `<select>` on freeform create, populated from the existing units store.
2. Disable description / units / accounting_category on PLI-linked edit; keep `unit_cost` and `sell_price` enabled.
3. Show a banner when PLI-linked: *"Linked to {pli.code} — {pli.description} ({pli.units}). Delete and re-add as freeform to change other fields."*
4. On save, if any pricing field changed AND the material is PLI-linked AND the new value differs from the PLI's current price, prompt *"Update PLI with the new values?"* — Yes triggers `propagate_to_pli: true` on the PATCH; No sends `propagate_to_pli: false`.
5. Display surfaces (`TaskTree.svelte`, `WorksheetTaskTable.svelte`, etc.) render `qty: 5 sheets` (suppressing the label when units == `'none'`).

### Task 9: `MaterialModal` accepts `units` and gates fields by PLI link

**Files:**
- Modify: `frontend/src/components/MaterialModal.svelte`

- [ ] **Step 1: Read the existing UnitsSelect component**

Run: `cat frontend/src/components/UnitsSelect.svelte`

Confirm its API. It likely takes a `value` prop and emits `bind:value` updates. If absent, check `frontend/src/stores/` for a units store.

- [ ] **Step 2: Add a `units` state and the units select to the modal**

In `frontend/src/components/MaterialModal.svelte`, in the `<script>` block, add:

```svelte
let units = $state('none');
let pliUnitCost = $state(null);  // for prompt comparison
let pliSellPrice = $state(null);  // for prompt comparison
let originalUnitCost = $state(null);  // pre-edit baseline
let originalSellPrice = $state(null);

let showPropagatePrompt = $state(false);
```

Update `$effect`:

```svelte
$effect(() => {
  if (open) {
    if (mode === 'edit' && material) {
      description = material.description || '';
      quantity = material.quantity ?? '';
      units = material.units || 'none';
      unitCost = material.unit_cost ?? '';
      sellPrice = material.sell_price ?? '';
      pliId = material.price_list_item || null;
      pliLocked = !!material.price_list_item;
      accountingCategory = material.accounting_category ?? '';
      originalUnitCost = unitCost;
      originalSellPrice = sellPrice;
    } else {
      description = '';
      quantity = '';
      units = 'none';
      unitCost = '';
      sellPrice = '';
      pliId = null;
      pliLocked = false;
      accountingCategory = '';
      originalUnitCost = null;
      originalSellPrice = null;
    }
    error = '';
    showPropagatePrompt = false;
  }
});
```

Update `handlePliSelect` to capture the PLI's units and price:

```svelte
function handlePliSelect(pli) {
  if (pli) {
    pliId = pli.price_list_item_id;
    description = pli.description || '';
    units = pli.units || 'none';
    unitCost = pli.purchase_price ?? '';
    sellPrice = pli.selling_price ?? '';
    pliUnitCost = pli.purchase_price ?? null;
    pliSellPrice = pli.selling_price ?? null;
    if (pli.accounting_category) accountingCategory = pli.accounting_category;
    pliLocked = true;
  } else {
    pliId = null;
    description = '';
    units = 'none';
    unitCost = '';
    sellPrice = '';
    pliUnitCost = null;
    pliSellPrice = null;
    pliLocked = false;
  }
}
```

- [ ] **Step 3: Add the units `<select>` and gate field disables**

Replace the existing form blocks. Use `UnitsSelect`:

```svelte
<p>
  <label><strong>Description</strong><br>
    <input type="text" bind:value={description} disabled={pliLocked} style="width:100%;box-sizing:border-box;">
  </label>
</p>

<p>
  <label><strong>Quantity</strong><br>
    <input type="number" step="0.01" bind:value={quantity}>
  </label>
</p>

<p>
  <label><strong>Units</strong><br>
    <UnitsSelect bind:value={units} disabled={pliLocked} />
  </label>
</p>

<p>
  <label><strong>Unit Cost</strong><br>
    <input type="number" step="0.01" bind:value={unitCost}>
  </label>
</p>

<p>
  <label><strong>Sell Price</strong><br>
    <input type="number" step="0.01" bind:value={sellPrice}>
  </label>
</p>

<p>
  <label><strong>Accounting Category</strong><br>
    <select bind:value={accountingCategory} disabled={pliLocked}>
      <option value="">-- None --</option>
      {#each categories as cat}
        <option value={cat.id}>{cat.code} - {cat.name}</option>
      {/each}
    </select>
  </label>
</p>
```

(Note: unit_cost and sell_price are no longer disabled when `pliLocked`; they're the carve-out.)

- [ ] **Step 4: Add the banner when PLI-linked**

Just below the PriceListItem picker:

```svelte
{#if pliLocked}
  <p style="background:#fff7e6;border:1px solid #ffc53d;padding:8px;">
    Linked to a price list item. Delete and re-add as freeform to change description, units, or category.
  </p>
{/if}
```

- [ ] **Step 5: Add the propagate-to-PLI prompt logic**

Replace `save()` with a two-step flow:

```svelte
async function save() {
  if (
    mode === 'edit' && pliLocked &&
    pliUnitCost !== null &&
    (Number(unitCost) !== Number(pliUnitCost) || Number(sellPrice) !== Number(pliSellPrice))
  ) {
    showPropagatePrompt = true;
    return;
  }
  await actuallySave(false);
}

async function actuallySave(propagate) {
  busy = true;
  error = '';
  showPropagatePrompt = false;
  const payload = {
    description,
    quantity: quantity || '0',
    units,
    unit_cost: unitCost || '0',
    sell_price: sellPrice || '0',
    price_list_item: pliId,
    accounting_category: accountingCategory || null,
  };
  try {
    if (mode === 'edit' && material) {
      // PATCH — send only the fields that should be editable on this row.
      const patch = pliLocked
        ? { unit_cost: payload.unit_cost, sell_price: payload.sell_price, propagate_to_pli: propagate }
        : { description, units, unit_cost: payload.unit_cost, sell_price: payload.sell_price, accounting_category: payload.accounting_category };
      await api.patch(`/api/materials/${material.material_id}/`, patch);
    } else if (taskId) {
      await api.post(`/api/tasks/${taskId}/materials/`, payload);
    } else {
      await api.post(`/api/jobs/${jobId}/materials/`, payload);
    }
    onSaved();
  } catch (e) {
    if (e.data && typeof e.data === 'object' && !e.data.detail) {
      error = Object.entries(e.data)
        .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
        .join('; ');
    } else {
      error = e.message || e.data?.detail || 'Could not save material.';
    }
  } finally {
    busy = false;
  }
}
```

- [ ] **Step 6: Render the prompt UI**

At the bottom of the modal `<div class="modal">`:

```svelte
{#if showPropagatePrompt}
  <div class="propagate-prompt">
    <p><strong>Update PLI with the new values?</strong></p>
    <div class="buttons">
      <button type="button" onclick={() => actuallySave(true)} disabled={busy}>Yes, update PLI</button>
      <button type="button" onclick={() => actuallySave(false)} disabled={busy}>No, just this material</button>
      <button type="button" onclick={() => (showPropagatePrompt = false)} disabled={busy}>Cancel</button>
    </div>
  </div>
{/if}
```

Add a style block entry:

```svelte
.propagate-prompt { margin-top: 12px; padding: 12px; background: #f0f9ff; border: 1px solid #91d5ff; }
```

- [ ] **Step 7: Manual smoke test**

Start backend and frontend:

```bash
python manage.py runserver
# in another shell
cd frontend && npm run dev
```

Open `http://localhost:9000/?autologin#/jobs/<some-job-id>` in a browser and:
- Open Add Material modal, leave PLI empty, set units to `lbs`, save → verify Material saved with units=lbs.
- Open Add Material, pick a PLI, save → verify Material has the PLI's units, all fields auto-filled.
- Open Edit Material on a PLI-linked row → verify description/units/category disabled, unit_cost/sell_price enabled, banner shown.
- Edit the unit_cost on a PLI-linked Material to a different value → verify the propagate prompt appears.
- Click Yes → verify both the Material and the PLI updated. Click No → verify only the Material updated.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/MaterialModal.svelte
git commit -m "feat(frontend): MaterialModal supports units field and PLI-linked carve-out

PLI-linked Materials show a banner and disable description/units/
category but keep unit_cost and sell_price editable. Editing a price
on a PLI-linked Material triggers an 'Update PLI?' prompt; the user's
choice maps to the propagate_to_pli flag on the PATCH.

Freeform Materials accept a units dropdown via the existing
UnitsSelect component."
```

### Task 10: `PlanMaterialModal` mirrors the same pattern

**Files:**
- Modify: `frontend/src/components/PlanMaterialModal.svelte`

- [ ] **Step 1: Apply the same logic as MaterialModal to PlanMaterialModal**

Read the existing component:

```bash
cat frontend/src/components/PlanMaterialModal.svelte
```

Apply parallel changes: add `units` state, switch to UnitsSelect, gate field disables on `pliLocked`, add the banner, add the propagate-to-PLI prompt. The save endpoints are different — likely `/api/est-worksheets/{id}/plan-materials/` for create and `/api/est-worksheets/{id}/plan-materials/{mid}/` for PATCH (or the plan_tasks variant when task-scoped).

- [ ] **Step 2: Manual smoke test**

Open the worksheet view; create a freeform PlanMaterial with units=lbs and a PLI-linked one. Verify edits behave the same as MaterialModal's.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/PlanMaterialModal.svelte
git commit -m "feat(frontend): PlanMaterialModal supports units and PLI carve-out

Mirrors the MaterialModal pattern: units dropdown, PLI-linked banner,
propagate_to_pli prompt for price edits."
```

### Task 11: Display surfaces render units alongside quantity

> **Note:** There is no TemplateMaterial editor in the SPA today (TemplateMaterial CRUD is API-only via `/api/work-templates/{id}/materials/`). The serializer rules added in Phase 3 already enforce the immutability + no-pricing-carve-out rule for TemplateMaterial. When a TemplateMaterial editor is built later, it will need to follow the same pattern as `MaterialModal.svelte` minus the pricing carve-out — but that's a separate piece of work, out of scope here.

**Files:**
- Modify: `frontend/src/components/TaskTree.svelte`, `frontend/src/components/WorksheetTaskTable.svelte`, and any other place that renders `material.quantity`.

- [ ] **Step 1: Find all material qty render sites**

```bash
grep -rn "material.quantity\|mat.quantity\|{m.quantity}" frontend/src/components/*.svelte frontend/src/routes/*.svelte
```

- [ ] **Step 2: Add a small formatter**

In `frontend/src/lib/format.js` (create if absent):

```js
export function formatQtyUnits(quantity, units) {
  if (!units || units === 'none') return String(quantity);
  return `${quantity} ${units}`;
}
```

- [ ] **Step 3: Use the formatter at each render site**

For each match found in step 1, replace `{mat.quantity}` (or similar) with `{formatQtyUnits(mat.quantity, mat.units)}`. Add the import at the top of each affected file:

```svelte
import { formatQtyUnits } from '../lib/format.js';
```

- [ ] **Step 4: Manual smoke test**

Open a job/worksheet with mixed materials. Verify rows show `5 sheets`, `2 ea`, `10` (when units == 'none'), etc.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/format.js frontend/src/components/TaskTree.svelte frontend/src/components/WorksheetTaskTable.svelte
git commit -m "feat(frontend): show units alongside material quantities

Adds a formatQtyUnits helper that renders 'qty units' (suppressing
the label when units == 'none', matching BaseLineItem precedent)
and applies it to material rows in TaskTree and WorksheetTaskTable."
```

---

## Phase 7 — Display formatting on the model

Backend `__str__` methods include units (suppressing the label when `'none'`).

### Task 12: `Material.__str__` and `PlanMaterial.__str__` include units

**Files:**
- Modify: `apps/inventory/models.py` (`Material.__str__`, `PlanMaterial.__str__`)
- Test: `tests/test_material_units_field.py` (extend)

- [ ] **Step 1: Failing tests**

```python
class MaterialStrTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","sheets","ea"]')
        cls.job = Job.objects.create(name='J', job_number='J-1', status=Job.STATUS_DRAFT)

    def test_material_str_includes_units_when_not_none(self):
        m = Material.objects.create(
            job=cls.job, description='Steel', quantity=Decimal('5'), units='sheets',
        )
        self.assertEqual(str(m), 'Steel (qty: 5.00 sheets)')

    def test_material_str_omits_units_when_none(self):
        m = Material.objects.create(
            job=cls.job, description='Misc', quantity=Decimal('1'),
        )
        self.assertEqual(str(m), 'Misc (qty: 1.00)')
```

- [ ] **Step 2: Run, verify failure**

Run: `python manage.py test tests.test_material_units_field.MaterialStrTests -v 2`

Expected: FAIL — current __str__ formats `{description} (qty: {quantity})` without units.

- [ ] **Step 3: Update `Material.__str__`**

In `apps/inventory/models.py:251-252`:

```python
def __str__(self):
    if self.units and self.units != 'none':
        return f"{self.description} (qty: {self.quantity} {self.units})"
    return f"{self.description} (qty: {self.quantity})"
```

- [ ] **Step 4: Update `PlanMaterial.__str__`**

In `apps/inventory/models.py:168-169`:

```python
def __str__(self):
    if self.units and self.units != 'none':
        return f"{self.description} (qty: {self.quantity} {self.units})"
    return f"{self.description} (qty: {self.quantity})"
```

- [ ] **Step 5: Run, verify pass**

Run: `python manage.py test tests.test_material_units_field -v 2`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/inventory/models.py tests/test_material_units_field.py
git commit -m "feat: Material/PlanMaterial __str__ include units when not 'none'

Suppresses the label when units == 'none' (no unit context),
matching the BaseLineItem display precedent."
```

---

## Phase 8 — Final regression and end-to-end smoke test

### Task 13: Full test-suite regression

- [ ] **Step 1: Run the entire suite**

Run: `python manage.py test -v 2`

Expected: PASS.

If a test fails:
- Read the failure message.
- If the failure is "this test was depending on the old behavior" (e.g., editing description on a PLI-linked Material), update the test to either use a freeform Material or assert the new 400.
- Do not weaken the new immutability rules to make a test pass — fix the test instead.

- [ ] **Step 2: Update fixtures if any test failure points there**

If any fixture-loaded test fails because materials in the fixture have units that no longer make sense (e.g., a PLI-linked Material whose `units` doesn't match the linked PLI), update the fixture row. Do this only for genuine mismatches; don't touch unrelated fields.

- [ ] **Step 3: Commit (only if fixture or test changes were needed)**

```bash
git add tests/ fixtures/
git commit -m "test: align tests and fixtures with PLI-linked immutability rules"
```

### Task 14: End-to-end manual browser smoke

Run the dev stack: `./dev.sh` (or `python manage.py runserver` + `cd frontend && npm run dev` in two shells). Open `http://localhost:9000/?autologin`.

- [ ] **Material creation paths**
  - On a job detail page, open Add Material → leave PLI empty, set units to `lbs`, save → row appears with `5 lbs` (or whatever).
  - Add Material → pick a PLI with `units='sheets'` → form auto-fills units / description / pricing → save → row appears with the PLI's units.
  - Add task-scoped Material from inside a task → verify same behavior.

- [ ] **PATCH on a PLI-linked Material**
  - Edit a PLI-linked Material → verify description/units/category are disabled, unit_cost/sell_price are not, banner is visible.
  - Change unit_cost only → click Save → "Update PLI?" prompt appears → click Yes → verify Material's `unit_cost` and the PLI's `purchase_price` both updated; PLI's `selling_price` unchanged.
  - Edit again, change unit_cost → click No → verify only Material updated.
  - Edit a freeform Material's description and units → save → verify both fields updated.

- [ ] **Delete-and-re-add to customize a PLI-linked Material**
  - On a PLI-linked Material with an inventoried PLI, delete it → verify earmark released.
  - Re-add as freeform with different units → verify the new Material has no earmark (no PLI link).

- [ ] **TemplateMaterial generation**
  - Edit a WorkTemplate, add a PLI-linked TemplateMaterial → verify pricing fields are hidden in the editor.
  - Update the linked PLI's `purchase_price` separately (via the PLI editor in settings).
  - Generate a worksheet from the template → verify the resulting PlanMaterial has the *current* PLI price, not the stale template value.

- [ ] **Estimate flow**
  - Create a worksheet with a freeform PlanMaterial whose units=`lbs`.
  - Generate an estimate from it → verify the EstimateLineItem has `units='lbs'`.

- [ ] **Permission carve-out**
  - Log in as a non-financials user (worker) → edit a PLI-linked Material's price → verify the propagate prompt still appears and the PLI update succeeds.

- [ ] **Commit final docs/notes (if any)**

If anything in `docs/designs/2026-05-07-material-units-field-design.md` proved wrong during implementation, update the design doc to match what landed:

```bash
git add docs/designs/2026-05-07-material-units-field-design.md
git commit -m "docs: update material units design with implementation refinements"
```

If everything matched the design, no commit needed.

---

## Done criteria

- [ ] All Django tests pass
- [ ] All Phase 5 manual browser tests pass
- [ ] No new permission warnings
- [ ] `docs/designs/2026-05-07-material-units-field-design.md` is accurate
- [ ] Branch ready for review / merge to main

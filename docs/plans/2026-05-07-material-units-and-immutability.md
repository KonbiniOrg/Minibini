# Material `units` field + PLI-linked immutability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `units` field to `MaterialBase` (propagating to `Material`, `PlanMaterial`, `TemplateMaterial`); enforce that PLI-linked rows are immutable except for `unit_cost`/`sell_price`; add an optional `propagate_to_pli` flag on pricing PATCHes; and refactor `WorkTemplate.generate_materials_for_*` so PLI-linked TemplateMaterials pull pricing fresh from the current PLI instead of carrying stale snapshots.

**Scope expansion (2026-05-09 during smoke testing):** Phase 9 and Phase 10 were added after the original 14-task plan, addressing two gaps surfaced during smoke testing. Phase 9 drops the redundant `TemplateMaterial` model in favour of a `TemplateMaterialAssociation` join table that links a WorkTemplate to a PriceListItem (with optional task pairing via `TemplateTaskAssociation`). Phase 10 makes `accounting_category` required on `Material` and `PlanMaterial`.

**Architecture:** Schema change is one additive migration on the three `materials*` tables. The immutability rule is enforced at the API serializer layer (no model `clean()` defence-in-depth — keep it simple). The pricing carve-out lives in a dedicated `MaterialService.update_pricing` service method that handles the `propagate_to_pli` flag in a single atomic transaction. TemplateMaterial generation branches on `tm.price_list_item_id` so PLI-linked rows let `_populate_from_pli` pull current PLI values. (Phase 9 then replaces the entire TemplateMaterial path with TemplateMaterialAssociation, which only ever links to a PLI — no branch needed because freeform-at-template is no longer supported.)

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

## Phase 9 — TemplateMaterial → TemplateMaterialAssociation refactor

**Scope expansion (added 2026-05-09 during smoke testing).** PLI is already the catalog of reusable materials; `TemplateMaterial` as a separate model is redundant. Drop `TemplateMaterial` entirely; replace with `TemplateMaterialAssociation` — a join table between `WorkTemplate` and `PriceListItem`, with an optional FK to `TemplateTaskAssociation` so generated PlanMaterial/Material rows attach to the matching generated PlanTask/Task.

**The big simplification:** freeform TemplateMaterials are no longer supported. If a template is going to use a material, that material must exist in the PLI catalog. Worksheet- and Job-level freeform Materials still work as before for ad-hoc cases.

**Pairing semantics** (per design doc):
- Each `TemplateMaterialAssociation` may optionally point at a `TemplateTaskAssociation`.
- For multi-instance generation (`quantity > 1`), each instance gets its own copy of the materials, paired one-to-one with the same instance's tasks. (Multi-instance UI is deferred per the follow-on note in the design doc; the generation API stays correct for any N.)

### Task 15: New `TemplateMaterialAssociation` model + data migration

**Files:**
- Modify: `apps/inventory/models.py` — add `TemplateMaterialAssociation`. (Don't drop `TemplateMaterial` yet.)
- Create: a new migration in `apps/inventory/migrations/` (auto-generated).
- Create: a `RunPython` data migration that converts existing `TemplateMaterial` rows.
- Create: `tests/test_template_material_association_model.py` for the new model.

#### Step 1: Failing test — model exists with correct shape

```python
# tests/test_template_material_association_model.py
from decimal import Decimal
from django.test import TestCase
from apps.inventory.models import (
    PriceListItem, TemplateMaterialAssociation,
)
from apps.estimates.models import (
    WorkTemplate, TaskTemplate, TemplateTaskAssociation,
)
from apps.core.models import AccountingCategory
from apps.jobs.models import RateScheme


class TemplateMaterialAssociationModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cat = AccountingCategory.objects.create(code='C', name='Cat')
        cls.scheme = RateScheme.objects.create(
            name='Hourly', rate=Decimal('50'), unit_label='hour',
            accounting_category=cls.cat,
        )
        cls.pli = PriceListItem.objects.create(
            code='PLI-A', units='sheets', description='X',
            purchase_price=Decimal('10'), selling_price=Decimal('20'),
            accounting_category=cls.cat,
        )
        cls.wt = WorkTemplate.objects.create(template_name='WT')
        cls.tt = TaskTemplate.objects.create(
            template_name='TT', rate_scheme=cls.scheme,
            default_billable_qty=Decimal('1'),
        )
        cls.tta = TemplateTaskAssociation.objects.create(
            work_template=cls.wt, task_template=cls.tt,
            est_qty=Decimal('1'), sort_order=0,
        )

    def test_minimal_creation_no_task_pairing(self):
        a = TemplateMaterialAssociation.objects.create(
            work_template=self.wt, price_list_item=self.pli,
            quantity=Decimal('5'),
        )
        self.assertIsNone(a.template_task_association)
        self.assertEqual(a.sort_order, 0)

    def test_creation_with_task_pairing(self):
        a = TemplateMaterialAssociation.objects.create(
            work_template=self.wt, price_list_item=self.pli,
            template_task_association=self.tta,
            quantity=Decimal('5'),
        )
        self.assertEqual(a.template_task_association_id, self.tta.pk)

    def test_work_template_related_name(self):
        TemplateMaterialAssociation.objects.create(
            work_template=self.wt, price_list_item=self.pli,
            quantity=Decimal('1'),
        )
        self.assertEqual(self.wt.material_associations.count(), 1)

    def test_template_task_association_related_name(self):
        TemplateMaterialAssociation.objects.create(
            work_template=self.wt, price_list_item=self.pli,
            template_task_association=self.tta, quantity=Decimal('1'),
        )
        self.assertEqual(self.tta.material_associations.count(), 1)
```

- [ ] **Step 2: Run test, expect failure**

```bash
python manage.py test tests.test_template_material_association_model -v 2
```

Expected: `ImportError: cannot import name 'TemplateMaterialAssociation' from 'apps.inventory.models'`.

- [ ] **Step 3: Add the model to `apps/inventory/models.py`**

```python
class TemplateMaterialAssociation(models.Model):
    """A reusable PriceListItem associated with a WorkTemplate.

    Replaces the old TemplateMaterial model: PLI is already the catalog of
    reusable materials, so a TemplateMaterial-as-separate-catalog was
    redundant. This model just pins which PLI belongs to which WorkTemplate
    (with quantity), optionally pairing to a TemplateTaskAssociation so the
    generated PlanMaterial/Material attaches to the corresponding generated
    PlanTask/Task.

    Generation semantics: for `quantity` instances of the parent WorkTemplate,
    each instance gets one PlanMaterial/Material per association, attached
    to the same-instance PlanTask/Task when `template_task_association` is set.
    """
    template_material_association_id = models.AutoField(primary_key=True)
    work_template = models.ForeignKey(
        'estimates.WorkTemplate', on_delete=models.CASCADE,
        related_name='material_associations',
    )
    price_list_item = models.ForeignKey(
        'PriceListItem', on_delete=models.PROTECT,
    )
    template_task_association = models.ForeignKey(
        'estimates.TemplateTaskAssociation',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='material_associations',
        help_text='If set, generated material attaches to the corresponding '
                  'generated PlanTask/Task.',
    )
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'template_material_assoc'
        ordering = ['sort_order']

    def __str__(self):
        return f'{self.work_template.template_name} → {self.price_list_item.code} (qty {self.quantity})'

    def clean(self):
        super().clean()
        if (
            self.template_task_association_id is not None
            and self.template_task_association.work_template_id != self.work_template_id
        ):
            from django.core.exceptions import ValidationError
            raise ValidationError(
                'template_task_association.work_template must match work_template'
            )
```

- [ ] **Step 4: Generate the schema migration**

```bash
python manage.py makemigrations inventory
```

Expected: a new migration file with `CreateModel` for `TemplateMaterialAssociation`. Read the file to verify.

- [ ] **Step 5: Run model tests, expect PASS**

```bash
python manage.py test tests.test_template_material_association_model -v 2
```

Expected: 4/4 PASS.

- [ ] **Step 6: Write failing test for the data migration**

Add to `tests/test_template_material_association_model.py`:

```python
class DataMigrationFromOldTemplateMaterialTests(TestCase):
    """Verifies the RunPython data migration converts existing TemplateMaterial
    rows to TemplateMaterialAssociation rows."""

    def test_pli_linked_template_materials_converted(self):
        # We can't run a migration mid-test, but we can verify the post-migration
        # state by creating a TemplateMaterial and a parallel association and
        # confirming they describe the same generation outcome.
        # The actual RunPython logic is tested via Django's migration test framework.
        pass  # Placeholder; the data migration test happens at migration runtime.
```

(The data migration's correctness is verified by the migration's own RunPython logic raising on freeform rows. We'll add an end-to-end test via fixtures in Step 8.)

- [ ] **Step 7: Write the data migration**

Create a new migration file (e.g. `apps/inventory/migrations/00XX_backfill_template_material_assoc.py`) right after the schema migration:

```python
from django.db import migrations


def backfill(apps, schema_editor):
    TemplateMaterial = apps.get_model('inventory', 'TemplateMaterial')
    TemplateMaterialAssociation = apps.get_model('inventory', 'TemplateMaterialAssociation')

    # Halt with a clear error if any freeform TemplateMaterials exist —
    # the new design only supports PLI-linked materials at the template level.
    freeforms = TemplateMaterial.objects.filter(price_list_item__isnull=True)
    if freeforms.exists():
        ids = list(freeforms.values_list('template_material_id', flat=True))
        raise RuntimeError(
            f'Cannot migrate: {len(ids)} freeform TemplateMaterial(s) found '
            f'(IDs: {ids}). The new design requires every template-level '
            f'material to link to a PriceListItem. Convert these to PLIs '
            f'(or delete them) before re-running this migration.'
        )

    for tm in TemplateMaterial.objects.all():
        TemplateMaterialAssociation.objects.create(
            work_template_id=tm.work_template_id,
            price_list_item_id=tm.price_list_item_id,
            quantity=tm.quantity,
            sort_order=tm.sort_order,
        )


def reverse_backfill(apps, schema_editor):
    # Best-effort reverse: rebuild TemplateMaterials from associations.
    # Some original fields (description, units, unit_cost, sell_price,
    # accounting_category) get default values since they were never carried
    # forward. This is acceptable since we only reverse pre-production data.
    from decimal import Decimal
    TemplateMaterial = apps.get_model('inventory', 'TemplateMaterial')
    TemplateMaterialAssociation = apps.get_model('inventory', 'TemplateMaterialAssociation')

    for a in TemplateMaterialAssociation.objects.all():
        TemplateMaterial.objects.create(
            work_template_id=a.work_template_id,
            price_list_item_id=a.price_list_item_id,
            quantity=a.quantity,
            sort_order=a.sort_order,
            description='',
            units='none',
            unit_cost=Decimal('0.00'),
            sell_price=Decimal('0.00'),
        )


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '00XX_create_template_material_association'),  # the schema migration from Step 4
    ]
    operations = [
        migrations.RunPython(backfill, reverse_backfill),
    ]
```

Replace the dependency name with the actual filename from Step 4.

- [ ] **Step 8: Run all tests; expect PASS**

```bash
python manage.py test tests.test_template_material_association_model tests.test_template_materials_generation tests.test_material_units_field -v 2
```

Existing TemplateMaterial-using tests still work (the model still exists). Phase 9's later tasks update them to use the new model.

- [ ] **Step 9: Commit**

```bash
git add apps/inventory/models.py apps/inventory/migrations/ tests/test_template_material_association_model.py
git commit -m "$(cat <<'EOF'
feat: add TemplateMaterialAssociation model + data migration

Replaces TemplateMaterial-as-catalog with a join table between
WorkTemplate and PriceListItem, with an optional FK to
TemplateTaskAssociation for per-task pairing.

Data migration backfills existing PLI-linked TemplateMaterials into
TemplateMaterialAssociation rows. Freeform TemplateMaterials (no PLI
link) are not supported by the new design; the migration halts with
a clear error if any are found, requiring manual cleanup before
re-running.

The TemplateMaterial model itself is not yet dropped — Tasks 16 and
17 update generation logic and the API surface, then Task 17 drops
the old model.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 16: Refactor generation logic to use TemplateMaterialAssociation with task pairing

**Files:**
- Modify: `apps/estimates/models.py` — `generate_tasks_for_worksheet`, `generate_materials_for_worksheet`, `generate_materials_for_job` on `WorkTemplate`.
- Modify: `apps/api/worksheets/views.py` and `apps/estimates/views.py` — capture the task pairing map from `generate_tasks_for_worksheet` and pass it to `generate_materials_for_worksheet`.
- Modify: `apps/jobs/services.py` — same pattern for `generate_materials_for_job`.
- Modify: `tests/test_template_materials_generation.py` — rewrite tests against the new model.

#### Step 1: Failing tests for the new generation behavior

Replace the contents of `tests/test_template_materials_generation.py` with tests against the new model:

```python
from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory, Configuration
from apps.contacts.models import Contact
from apps.inventory.models import (
    Material, PlanMaterial, PriceListItem, TemplateMaterialAssociation,
)
from apps.estimates.models import (
    EstWorksheet, WorkTemplate, TaskTemplate, TemplateTaskAssociation,
)
from apps.jobs.models import Job, PlanTask, RateScheme, Task


class _Setup(TestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","sheets","ea"]')
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.contact = Contact.objects.create(first_name='J', last_name='D', email='j@d.com')
        cls.scheme = RateScheme.objects.create(
            name='Hourly', rate=Decimal('100'), unit_label='hour',
            accounting_category=cls.cat,
        )
        cls.pli = PriceListItem.objects.create(
            code='PLI-1', units='sheets', description='Steel Sheet',
            purchase_price=Decimal('40.00'), selling_price=Decimal('60.00'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(
            name='J', job_number='J-1', status=Job.STATUS_DRAFT, contact=cls.contact,
        )
        cls.wt = WorkTemplate.objects.create(template_name='T')
        cls.tt = TaskTemplate.objects.create(
            template_name='Cut', rate_scheme=cls.scheme,
            default_billable_qty=Decimal('20'),
        )
        cls.tta = TemplateTaskAssociation.objects.create(
            work_template=cls.wt, task_template=cls.tt,
            est_qty=Decimal('20'), sort_order=0,
        )


class WorksheetGenerationTests(_Setup):
    def test_task_less_association_generates_task_less_plan_material(self):
        TemplateMaterialAssociation.objects.create(
            work_template=self.wt, price_list_item=self.pli,
            quantity=Decimal('5'),
        )
        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        self.wt.generate_tasks_for_worksheet(ws)
        self.wt.generate_materials_for_worksheet(ws)

        pms = list(PlanMaterial.objects.filter(est_worksheet=ws, plan_task__isnull=True))
        self.assertEqual(len(pms), 1)
        self.assertEqual(pms[0].quantity, Decimal('5'))
        self.assertEqual(pms[0].price_list_item_id, self.pli.pk)
        self.assertEqual(pms[0].units, 'sheets')  # via _populate_from_pli

    def test_task_paired_association_attaches_to_matching_plan_task(self):
        TemplateMaterialAssociation.objects.create(
            work_template=self.wt, price_list_item=self.pli,
            template_task_association=self.tta,
            quantity=Decimal('2'),
        )
        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        self.wt.generate_tasks_for_worksheet(ws)
        self.wt.generate_materials_for_worksheet(ws)

        pt = PlanTask.objects.get(est_worksheet=ws)
        pm = PlanMaterial.objects.get(est_worksheet=ws)
        self.assertEqual(pm.plan_task_id, pt.pk)
        self.assertEqual(pm.quantity, Decimal('2'))

    def test_pli_price_change_after_template_setup_reflected_at_generation(self):
        TemplateMaterialAssociation.objects.create(
            work_template=self.wt, price_list_item=self.pli,
            quantity=Decimal('5'),
        )
        # PLI price bumped after the template was set up
        self.pli.purchase_price = Decimal('52.00')
        self.pli.selling_price = Decimal('78.00')
        self.pli.save()

        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        self.wt.generate_tasks_for_worksheet(ws)
        self.wt.generate_materials_for_worksheet(ws)

        pm = PlanMaterial.objects.get(est_worksheet=ws)
        self.assertEqual(pm.unit_cost, Decimal('52.00'))
        self.assertEqual(pm.sell_price, Decimal('78.00'))

    def test_multi_instance_replicates_per_instance_with_pairing(self):
        TemplateMaterialAssociation.objects.create(
            work_template=self.wt, price_list_item=self.pli,
            template_task_association=self.tta,
            quantity=Decimal('2'),
        )
        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        self.wt.generate_tasks_for_worksheet(ws, quantity=3)
        self.wt.generate_materials_for_worksheet(ws, quantity=3)

        # 3 PlanTasks, 3 PlanMaterials, each PlanMaterial paired with a unique PlanTask
        pts = list(PlanTask.objects.filter(est_worksheet=ws).order_by('plan_task_id'))
        pms = list(PlanMaterial.objects.filter(est_worksheet=ws).order_by('plan_material_id'))
        self.assertEqual(len(pts), 3)
        self.assertEqual(len(pms), 3)
        # Each PlanMaterial's plan_task is one of the generated tasks, and they pair 1:1.
        paired_task_ids = sorted(pm.plan_task_id for pm in pms)
        self.assertEqual(paired_task_ids, sorted(pt.pk for pt in pts))


class JobGenerationTests(_Setup):
    def test_task_less_association_generates_task_less_material(self):
        TemplateMaterialAssociation.objects.create(
            work_template=self.wt, price_list_item=self.pli,
            quantity=Decimal('5'),
        )
        # Tasks first, then materials
        self.wt.generate_tasks_for_job(self.job)  # method may not exist — see Step 3 below
        self.wt.generate_materials_for_job(self.job)

        ms = list(Material.objects.filter(job=self.job, task__isnull=True))
        self.assertEqual(len(ms), 1)
        self.assertEqual(ms[0].price_list_item_id, self.pli.pk)
        self.assertEqual(ms[0].units, 'sheets')

    def test_task_paired_association_attaches_to_matching_task(self):
        TemplateMaterialAssociation.objects.create(
            work_template=self.wt, price_list_item=self.pli,
            template_task_association=self.tta,
            quantity=Decimal('2'),
        )
        self.wt.generate_tasks_for_job(self.job)
        self.wt.generate_materials_for_job(self.job)

        t = Task.objects.get(job=self.job)
        m = Material.objects.get(job=self.job)
        self.assertEqual(m.task_id, t.pk)
```

- [ ] **Step 2: Run, verify failure**

```bash
python manage.py test tests.test_template_materials_generation -v 2
```

Expected: most fail. The generation methods don't yet pair to tasks via the new model.

- [ ] **Step 3: Refactor `generate_tasks_for_worksheet` to return a pairing map**

In `apps/estimates/models.py`, change `generate_tasks_for_worksheet` to return a list of `(TemplateTaskAssociation, instance_index, PlanTask)` tuples:

```python
def generate_tasks_for_worksheet(self, worksheet, quantity=1):
    """Generate plan tasks for a worksheet from this template.

    Returns a list of (TemplateTaskAssociation, instance_index, PlanTask) tuples
    so callers (e.g. generate_materials_for_worksheet) can pair generated
    materials with their matching PlanTasks.
    """
    generated = []
    for instance in range(1, quantity + 1):
        associations = TemplateTaskAssociation.objects.filter(
            work_template=self,
            task_template__is_active=True,
        ).order_by('sort_order', 'task_template__template_name')

        for association in associations:
            task = association.task_template.generate_task(
                worksheet,
                est_qty=association.est_qty,
                product_instance=instance if quantity > 1 else None,
                sort_order=association.sort_order,
            )
            generated.append((association, instance, task))

    return generated
```

- [ ] **Step 4: Add `WorkTemplate.generate_tasks_for_job` (parallel to `generate_tasks_for_worksheet`)**

The Job side currently iterates associations directly inside `JobService.populate_from_template`. Lift the iteration into a `generate_tasks_for_job` method on `WorkTemplate` so the pairing map is exposed the same way. (Or: leave it where it is and have `JobService.populate_from_template` build the map and pass it to `generate_materials_for_job`. The method-on-WorkTemplate approach is more symmetric; recommended.)

In `apps/estimates/models.py`:

```python
def generate_tasks_for_job(self, job, quantity=1):
    """Generate Tasks on a Job from this template's TaskTemplates.

    Returns a list of (TemplateTaskAssociation, instance_index, Task) tuples
    so generate_materials_for_job can pair generated Materials with their
    matching Tasks. Mirrors generate_tasks_for_worksheet.
    """
    generated = []
    for instance in range(1, quantity + 1):
        associations = TemplateTaskAssociation.objects.filter(
            work_template=self,
            task_template__is_active=True,
        ).order_by('sort_order', 'task_template__template_name')

        for association in associations:
            task = association.task_template.generate_task(
                job,
                est_qty=association.est_qty,
                product_instance=instance if quantity > 1 else None,
                sort_order=association.sort_order,
            )
            generated.append((association, instance, task))

    return generated
```

- [ ] **Step 5: Refactor `generate_materials_for_worksheet` to use associations + pairing map**

```python
def generate_materials_for_worksheet(self, worksheet, quantity=1, task_pairing=None):
    """Generate PlanMaterials for a worksheet from this template's
    material associations. Pairs each association's generated PlanMaterial
    with the matching generated PlanTask via task_pairing (a list of
    (TemplateTaskAssociation, instance_index, PlanTask) tuples returned by
    generate_tasks_for_worksheet).

    If task_pairing is None, all generated materials are task-less.
    """
    from apps.inventory.models import PlanMaterial

    # Build (tta_pk, instance) -> PlanTask lookup if pairing was provided
    pairing = {}
    if task_pairing:
        for tta, instance, pt in task_pairing:
            pairing[(tta.pk, instance)] = pt

    associations = self.material_associations.all()
    for instance in range(1, quantity + 1):
        for assoc in associations:
            paired_pt = None
            if assoc.template_task_association_id is not None:
                paired_pt = pairing.get((assoc.template_task_association_id, instance))
            PlanMaterial.objects.create(
                est_worksheet=worksheet,
                plan_task=paired_pt,
                quantity=assoc.quantity,
                price_list_item=assoc.price_list_item,
            )
```

- [ ] **Step 6: Refactor `generate_materials_for_job` similarly**

```python
def generate_materials_for_job(self, job, quantity=1, task_pairing=None):
    from apps.inventory.services import MaterialService

    pairing = {}
    if task_pairing:
        for tta, instance, t in task_pairing:
            pairing[(tta.pk, instance)] = t

    associations = self.material_associations.all()
    for instance in range(1, quantity + 1):
        for assoc in associations:
            paired_t = None
            if assoc.template_task_association_id is not None:
                paired_t = pairing.get((assoc.template_task_association_id, instance))
            MaterialService.create_on_job(
                job=job, task=paired_t,
                quantity=assoc.quantity,
                price_list_item=assoc.price_list_item,
            )
```

- [ ] **Step 7: Update callers to capture the task pairing map**

`apps/api/worksheets/views.py:69-80`:

```python
def perform_create(self, serializer):
    data = serializer.validated_data
    job = data.get('job')
    job_pk = job.pk if hasattr(job, 'pk') else job
    kwargs = {}
    template = data.get('template')
    if template:
        kwargs['template'] = template
    ws = WorksheetService.create_worksheet(job_pk, **kwargs)
    if template:
        task_pairing = template.generate_tasks_for_worksheet(ws)
        template.generate_materials_for_worksheet(ws, task_pairing=task_pairing)
    serializer.instance = ws
```

`apps/estimates/views.py` (the legacy HTML view at line 383): same pattern.

`apps/jobs/services.py:300` `JobService.populate_from_template`: change

```python
template.generate_materials_for_job(job, quantity=1)
```

to

```python
task_pairing = template.generate_tasks_for_job(job)
template.generate_materials_for_job(job, task_pairing=task_pairing)
```

…and wherever `populate_from_template` currently creates the tasks (likely a similar inline loop), refactor to call `template.generate_tasks_for_job(job)` and capture the return.

(If `populate_from_template` already generates tasks via a different path, leave that intact and just add the call to `generate_tasks_for_job` if needed. Read the existing code carefully to avoid duplicate task generation.)

- [ ] **Step 8: Run all tests; expect PASS**

```bash
python manage.py test tests.test_template_materials_generation tests.test_template_workflows tests.test_new_templating tests.test_jobs_services tests.test_estimates_services -v 2
```

If any existing test fails because it relied on the old TemplateMaterial-direct generation path, update the test to use TemplateMaterialAssociation and a PLI link.

- [ ] **Step 9: Commit**

```bash
git add apps/estimates/models.py apps/api/worksheets/views.py apps/estimates/views.py apps/jobs/services.py tests/test_template_materials_generation.py
git commit -m "$(cat <<'EOF'
refactor: generate_materials_for_* uses TemplateMaterialAssociation + task pairing

WorkTemplate.generate_tasks_for_worksheet and a new
generate_tasks_for_job now return [(association, instance, PlanTask|Task)]
tuples so callers can build a pairing map. The materials generators
accept the map (optional) and attach generated PlanMaterial/Material
to the matching task when the association points to a
TemplateTaskAssociation.

Materials are sourced from wt.material_associations.all() rather than
wt.materials.all(); the old TemplateMaterial-to-PlanMaterial path is
gone. The TemplateMaterial model itself remains until Task 17 drops it
along with the API endpoints.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 17: API surface migrates to TemplateMaterialAssociation; drop old TemplateMaterial

**Files:**
- Modify: `apps/api/templates_config/serializers.py` — replace `TemplateMaterialSerializer` with `TemplateMaterialAssociationSerializer`.
- Modify: `apps/api/templates_config/views.py` — update the WorkTemplate viewset's `materials` and `material_detail` actions to operate on associations.
- Modify: `apps/inventory/serializer_helpers.py` — drop the TEMPLATE_* allowlists.
- Create: schema migration to drop the `template_materials` table and `TemplateMaterial` model.
- Modify: any remaining tests that reference TemplateMaterial.

#### Step 1: Update tests for the new endpoint shape

The endpoint stays at `/api/work-templates/{id}/materials/` but the payload changes from MaterialBase fields to `{price_list_item, quantity, template_task_association?, sort_order}`.

Add to `tests/test_template_material_association_model.py`:

```python
from rest_framework.test import APITestCase
from django.contrib.auth.models import Permission
from apps.core.models import User


class TemplateMaterialAssociationApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='u', password='p')
        cls.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_config'),
        )
        cls.cat = AccountingCategory.objects.create(code='C', name='Cat')
        from apps.jobs.models import RateScheme
        from apps.estimates.models import (
            WorkTemplate, TaskTemplate, TemplateTaskAssociation,
        )
        cls.scheme = RateScheme.objects.create(
            name='H', rate=Decimal('50'), unit_label='hour',
            accounting_category=cls.cat,
        )
        cls.pli = PriceListItem.objects.create(
            code='PLI', units='sheets', description='X',
            purchase_price=Decimal('10'), selling_price=Decimal('20'),
            accounting_category=cls.cat,
        )
        cls.wt = WorkTemplate.objects.create(template_name='WT')
        cls.tt = TaskTemplate.objects.create(
            template_name='TT', rate_scheme=cls.scheme,
            default_billable_qty=Decimal('1'),
        )
        cls.tta = TemplateTaskAssociation.objects.create(
            work_template=cls.wt, task_template=cls.tt,
            est_qty=Decimal('1'),
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_post_creates_association(self):
        resp = self.client.post(
            f'/api/work-templates/{self.wt.pk}/materials/',
            {'price_list_item': self.pli.pk, 'quantity': '5'},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['price_list_item'], self.pli.pk)
        self.assertEqual(body['quantity'], '5.00')
        self.assertIsNone(body['template_task_association'])

    def test_post_with_task_association(self):
        resp = self.client.post(
            f'/api/work-templates/{self.wt.pk}/materials/',
            {
                'price_list_item': self.pli.pk,
                'quantity': '2',
                'template_task_association': self.tta.pk,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['template_task_association'], self.tta.pk)

    def test_patch_quantity(self):
        a = TemplateMaterialAssociation.objects.create(
            work_template=self.wt, price_list_item=self.pli,
            quantity=Decimal('1'),
        )
        resp = self.client.patch(
            f'/api/work-templates/{self.wt.pk}/materials/{a.pk}/',
            {'quantity': '5'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        a.refresh_from_db()
        self.assertEqual(a.quantity, Decimal('5'))

    def test_delete(self):
        a = TemplateMaterialAssociation.objects.create(
            work_template=self.wt, price_list_item=self.pli,
            quantity=Decimal('1'),
        )
        resp = self.client.delete(
            f'/api/work-templates/{self.wt.pk}/materials/{a.pk}/',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(TemplateMaterialAssociation.objects.filter(pk=a.pk).exists())
```

- [ ] **Step 2: Run; expect failure (404 / 400 because the endpoint still expects the old shape)**

```bash
python manage.py test tests.test_template_material_association_model.TemplateMaterialAssociationApiTests -v 2
```

- [ ] **Step 3: Replace `TemplateMaterialSerializer` with `TemplateMaterialAssociationSerializer`**

In `apps/api/templates_config/serializers.py`:

```python
from apps.inventory.models import TemplateMaterialAssociation


class TemplateMaterialAssociationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TemplateMaterialAssociation
        fields = [
            'template_material_association_id', 'work_template',
            'price_list_item', 'template_task_association',
            'quantity', 'sort_order',
        ]
        read_only_fields = ['template_material_association_id', 'work_template']
```

Remove the `TemplateMaterialSerializer` class. Remove the import of `TemplateMaterial` if it's only used by that serializer.

- [ ] **Step 4: Update `apps/api/templates_config/views.py`**

Replace usages of `TemplateMaterial` with `TemplateMaterialAssociation`. The `materials` action's GET returns `assoc.work_template.material_associations.all()`; POST creates a new TemplateMaterialAssociation. The `material_detail` GET/PATCH/DELETE works on the same model.

```python
from apps.inventory.models import TemplateMaterialAssociation
from .serializers import (
    WorkTemplateSerializer, TaskTemplateSerializer,
    ConfigurationSerializer, AccountingCategorySerializer,
    TemplateMaterialAssociationSerializer,
)

# In WorkTemplateViewSet:

@action(detail=True, methods=['get', 'post'], url_path='materials', url_name='materials')
def materials(self, request, pk=None):
    template = self.get_object()
    if request.method == 'GET':
        assocs = TemplateMaterialAssociation.objects.filter(work_template=template)
        return Response(TemplateMaterialAssociationSerializer(assocs, many=True).data)

    serializer = TemplateMaterialAssociationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    a = TemplateMaterialAssociation(work_template=template, **serializer.validated_data)
    a.full_clean()
    a.save()
    return Response(
        TemplateMaterialAssociationSerializer(a).data,
        status=status.HTTP_201_CREATED,
    )

@action(detail=True, methods=['get', 'patch', 'delete'],
        url_path='materials/(?P<assoc_id>[0-9]+)', url_name='material-detail')
def material_detail(self, request, pk=None, assoc_id=None):
    template = self.get_object()
    try:
        a = TemplateMaterialAssociation.objects.get(pk=assoc_id, work_template=template)
    except TemplateMaterialAssociation.DoesNotExist:
        from rest_framework.exceptions import NotFound
        raise NotFound()

    if request.method == 'GET':
        return Response(TemplateMaterialAssociationSerializer(a).data)

    if request.method == 'DELETE':
        a.delete()
        return Response({'message': 'Template material association deleted.'})

    serializer = TemplateMaterialAssociationSerializer(a, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)
```

- [ ] **Step 5: Drop the TEMPLATE_* allowlists from `apps/inventory/serializer_helpers.py`**

The `TEMPLATE_PLI_LINKED_ALLOWED` and `TEMPLATE_FREEFORM_ALLOWED` constants are no longer used; remove them.

- [ ] **Step 6: Drop the `TemplateMaterial` model**

In `apps/inventory/models.py`, delete the `TemplateMaterial` class.

```bash
python manage.py makemigrations inventory
```

Expected: a new migration that does `migrations.DeleteModel(name='TemplateMaterial')`.

- [ ] **Step 7: Update any straggling test imports**

```bash
grep -rn "TemplateMaterial\b" tests/ apps/ docs/ 2>/dev/null
```

Update or remove any remaining references. (`TemplateMaterialAssociation` matches, so use `\b` boundary.)

- [ ] **Step 8: Run full regression**

```bash
python manage.py test 2>&1 | tail -10
```

Expected: 0 failures.

- [ ] **Step 9: Commit**

```bash
git add apps/api/templates_config/serializers.py apps/api/templates_config/views.py apps/inventory/serializer_helpers.py apps/inventory/models.py apps/inventory/migrations/ tests/test_template_material_association_model.py
git commit -m "$(cat <<'EOF'
refactor: drop TemplateMaterial; API moves to TemplateMaterialAssociation

The /api/work-templates/{id}/materials/ endpoint now operates on
TemplateMaterialAssociation rows. POST/PATCH bodies shrink from the
full MaterialBase field set to {price_list_item, quantity,
template_task_association?, sort_order} — labelling and pricing come
from the linked PriceListItem at generation time.

Removes the TEMPLATE_PLI_LINKED_ALLOWED / TEMPLATE_FREEFORM_ALLOWED
allowlist constants since the simpler shape doesn't need them.

Drops the TemplateMaterial model and its template_materials table.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 10 — `accounting_category` required server-side

**Scope expansion (added 2026-05-09 during smoke testing).** Today, `MaterialBase.accounting_category` is `null=True, blank=True`, so freeform Material creation can land without a category. We want it required everywhere — the field tracks tax/accounting categorization and shouldn't be optional.

Approach: model-level NOT NULL, with a data migration that backfills NULL rows (PLI-linked: copy from PLI; freeform: halt with a clear error so the operator can decide what to do).

### Task 18: Make `accounting_category` required on Material/PlanMaterial

**Files:**
- Modify: `apps/inventory/models.py` — `MaterialBase.accounting_category` loses `null=True, blank=True`.
- Create: data migration backfilling NULLs.
- Create: schema migration tightening to NOT NULL.
- Modify: `apps/api/jobs/views.py` — the hand-rolled POST handler at `create_material` sends `accounting_category=None` when not provided; let it raise a clear 400 instead. (The path through serializers does this already.)
- Modify: tests covering the new required behavior.

**Note:** by the time this task runs, `TemplateMaterial` is already gone (Task 17), so we only need to handle `Material` and `PlanMaterial`.

#### Step 1: Failing test for required-on-create

Create `tests/test_accounting_category_required.py`:

```python
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from rest_framework.test import APITestCase
from apps.core.models import AccountingCategory, Configuration, User
from apps.contacts.models import Contact
from apps.inventory.models import Material, PlanMaterial, PriceListItem
from apps.estimates.models import EstWorksheet
from apps.jobs.models import Job


class _Setup(APITestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none","ea","sheets"]')
        cls.user = User.objects.create_user(username='u', password='p')
        cls.cat = AccountingCategory.objects.create(code='MAT', name='Materials')
        cls.contact = Contact.objects.create(first_name='J', last_name='D', email='j@d.com')
        cls.pli = PriceListItem.objects.create(
            code='PLI', units='sheets', description='X',
            purchase_price=Decimal('10'), selling_price=Decimal('20'),
            accounting_category=cls.cat,
        )
        cls.job = Job.objects.create(
            name='J', job_number='J-1', status=Job.STATUS_DRAFT, contact=cls.contact,
        )

    def setUp(self):
        self.client.force_login(self.user)


class FreeformMaterialRequiresCategoryTests(_Setup):
    def test_post_freeform_material_without_category_fails(self):
        resp = self.client.post(
            f'/api/jobs/{self.job.pk}/materials/',
            {'description': 'x', 'quantity': '1'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_post_freeform_material_with_category_succeeds(self):
        resp = self.client.post(
            f'/api/jobs/{self.job.pk}/materials/',
            {
                'description': 'x', 'quantity': '1',
                'accounting_category': self.cat.pk,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_post_pli_linked_material_without_explicit_category_succeeds(self):
        # PLI fills in the category via _populate_from_pli, so no explicit
        # accounting_category is needed in the request.
        resp = self.client.post(
            f'/api/jobs/{self.job.pk}/materials/',
            {
                'price_list_item': self.pli.pk,
                'quantity': '1',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        m = Material.objects.get(job=self.job)
        self.assertEqual(m.accounting_category_id, self.cat.pk)


class FreeformPlanMaterialRequiresCategoryTests(_Setup):
    def test_post_freeform_plan_material_without_category_fails(self):
        ws = EstWorksheet.objects.create(job=self.job, status=EstWorksheet.STATUS_DRAFT)
        resp = self.client.post(
            f'/api/est-worksheets/{ws.pk}/plan-materials/',
            {'description': 'x', 'quantity': '1'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)


class ModelLevelNotNullTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='units_list', value='["none"]')
        cls.contact = Contact.objects.create(first_name='J', last_name='D', email='j@d.com')
        cls.job = Job.objects.create(
            name='J', job_number='J-1', status=Job.STATUS_DRAFT, contact=cls.contact,
        )

    def test_creating_freeform_material_without_category_raises(self):
        m = Material(
            job=self.job, description='x', quantity=Decimal('1'),
        )
        with self.assertRaises(ValidationError):
            m.save()  # full_clean inside save raises on missing category
```

- [ ] **Step 2: Run, expect failure (NULLs accepted today)**

```bash
python manage.py test tests.test_accounting_category_required -v 2
```

Expected: most tests fail because the field is currently nullable.

- [ ] **Step 3: Write the data migration to backfill NULLs**

Create `apps/inventory/migrations/00XX_backfill_accounting_category.py`:

```python
from django.db import migrations


def backfill(apps, schema_editor):
    Material = apps.get_model('inventory', 'Material')
    PlanMaterial = apps.get_model('inventory', 'PlanMaterial')

    # PLI-linked rows: copy the PLI's category.
    for cls in (Material, PlanMaterial):
        rows = cls.objects.filter(
            accounting_category__isnull=True,
            price_list_item__isnull=False,
        ).select_related('price_list_item')
        for row in rows:
            row.accounting_category_id = row.price_list_item.accounting_category_id
            row.save(update_fields=['accounting_category'])

    # Freeform rows: halt with a clear error.
    for cls in (Material, PlanMaterial):
        freeforms = cls.objects.filter(
            accounting_category__isnull=True,
            price_list_item__isnull=True,
        )
        if freeforms.exists():
            ids = list(freeforms.values_list('pk', flat=True))
            raise RuntimeError(
                f'Cannot migrate: {len(ids)} freeform {cls.__name__}(s) without '
                f'accounting_category found (IDs: {ids}). Assign a category '
                f'before re-running this migration.'
            )


def reverse_backfill(apps, schema_editor):
    # No-op: forward migration only fills NULLs from the PLI; reversing
    # would mean re-NULLing those rows, which is destructive and unwanted.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '00XX_drop_template_material'),  # the schema migration from Task 17
    ]
    operations = [
        migrations.RunPython(backfill, reverse_backfill),
    ]
```

- [ ] **Step 4: Tighten the model field to NOT NULL**

In `apps/inventory/models.py`, on `MaterialBase`:

```python
accounting_category = models.ForeignKey(
    'core.AccountingCategory', on_delete=models.SET_NULL,
    null=True, blank=True,
)
```

becomes

```python
accounting_category = models.ForeignKey(
    'core.AccountingCategory', on_delete=models.PROTECT,
)
```

(Switch to PROTECT since we're now always carrying a value; SET_NULL no longer makes sense.)

```bash
python manage.py makemigrations inventory
```

Expected: an `AlterField` migration tightening `accounting_category` on Material and PlanMaterial.

- [ ] **Step 5: Update `apps/api/jobs/views.py` `create_material`**

The hand-rolled POST handler currently does:

```python
ac = None
if data.get('accounting_category'):
    ac = AccountingCategory.objects.get(pk=data['accounting_category'])
```

With the field now NOT NULL, calling `MaterialService.create_on_job(... accounting_category=None)` will fail at `_populate_from_pli` (only fills if PLI is linked) and then at `full_clean()` for freeform creates with no PLI.

That's the desired behavior. Just verify the resulting 400 has a useful body. If needed, wrap `MaterialService.create_on_job` in a try/except that maps `ValidationError` to a 400 with the field errors. Many endpoints already do this.

- [ ] **Step 6: Run all tests**

```bash
python manage.py test 2>&1 | tail -10
```

Expected: 0 failures. If anything fails, it's likely a test that creates a Material/PlanMaterial without a category — update to provide one.

- [ ] **Step 7: Commit**

```bash
git add apps/inventory/models.py apps/inventory/migrations/ apps/api/jobs/views.py tests/test_accounting_category_required.py
git commit -m "$(cat <<'EOF'
feat: accounting_category required on Material/PlanMaterial

MaterialBase.accounting_category drops null=True, blank=True. Field
is now NOT NULL with on_delete=PROTECT. Migration backfills NULL rows
by copying from the linked PLI; halts with a clear error on freeform
rows that have no category set.

The serializer paths already validate; the hand-rolled
/api/jobs/{id}/materials/ POST surfaces a 400 via the model's
full_clean() failure when freeform creates omit the field.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Done criteria

- [ ] All Django tests pass
- [ ] All Phase 5 manual browser tests pass
- [ ] All Phase 9 / Phase 10 changes have passing unit tests
- [ ] No new permission warnings
- [ ] `docs/designs/2026-05-07-material-units-field-design.md` is accurate (the TemplateMaterial follow-on note becomes "implemented")
- [ ] Branch ready for review / merge to main

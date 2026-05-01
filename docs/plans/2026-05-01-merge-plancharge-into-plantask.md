# Merge PlanCharge into PlanTask Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge `PlanCharge` (per-task billing config) into `PlanTask` so the worksheet wizard's source pool can iterate `PlanTask` directly, fixing the bug where plan tasks created without an explicit charge POST never appear as wizard atoms.

**Architecture:** `PlanTask` gains the three fields currently on `PlanCharge` (`rate_scheme`, `active_modifiers`, `estimated_billable_qty`) and a `compute_amount()` method that delegates to `RateScheme.compute_charge`. `RateScheme` is unchanged — it remains the shared, append-only billing recipe. The `Task` / `TaskCharge` split on the real side is intentionally NOT touched (TaskCharge holds runtime `actuals` that don't exist on the plan side). Legacy `units` / `rate` / `est_qty` fields are removed from `PlanTask` (they're not referenced by anything that survives). The estimate-wizard atom interface stays the same shape; only the source-pool query and atom `type` string change (`plan_charge` → `plan_task`).

**Tech Stack:** Django 5.2+, DRF, MySQL, Svelte 5 SPA.

**Pre-requisites:** Read `docs/designs/2026-04-19-billable-atoms-and-estimate-wizard-design.md` and `docs/designs/2026-04-16-task-labor-ratescheme-refactor.md` for atom-system context. Read `apps/jobs/models.py:288-411` (RateScheme, TaskCharge, PlanCharge) to internalize how `compute_charge` flows. Read `apps/estimates/services.py:443-770` for the existing wizard service.

**Reminder:** Per CLAUDE.md, `python manage.py migrate` is the human's job. Use `makemigrations` only. Tests build their own database.

**Reminder:** Never run `python manage.py test` from multiple parallel agents — the MySQL test DB is shared and they will deadlock.

---

## File Structure

**Modify (backend):**
- `apps/jobs/models.py` — add atom fields and `compute_amount()` to `PlanTask`; rename `Task.source_plan_charge` → `Task.source_plan_task`; eventually drop `PlanCharge`; move legacy `units`/`rate`/`est_qty` from `TaskBase` to `Task` only.
- `apps/api/worksheets/serializers.py` — `PlanTaskSerializer` exposes the new fields, drops legacy ones.
- `apps/api/plan_tasks/views.py` — drop `plan_charge_view` and `PlanChargeSerializer`.
- `apps/api/urls.py` — drop `/charge/` URL pattern.
- `apps/estimates/services.py` — `EstimateWizardService` works with `PlanTask` atoms.
- `apps/estimates/models.py` — `EstimateLineItemSource.SOURCE_PLAN_CHARGE` → `SOURCE_PLAN_TASK`; update `EstWorksheet.create_new_version` to copy new fields.
- `apps/estimates/carry_over.py` — walk `PlanTask` instead of `PlanCharge`; idempotency keyed on `Task.source_plan_task`.
- `apps/api/estimates/views.py` and `apps/api/estimates/serializers.py` — atom-type rename in source-pool serialization and `EstimateLineItemSource` resolution.
- `apps/core/management/commands/validate_data.py` — update `PlanCharge` references.
- `apps/jobs/services.py` — any references to `PlanCharge` (none expected; verify).
- `apps/inventory/models.py` — comment refs to `PlanCharge` (cosmetic).
- New migrations under `apps/jobs/migrations/` and `apps/estimates/migrations/`.

**Modify (frontend):**
- `frontend/src/components/PlanTaskModal.svelte` — single save path; rate-scheme picker required for billing; replace `est_qty`/`rate`/`units` inputs with `estimated_billable_qty` + scheme-driven display.
- `frontend/src/components/WorksheetTaskTable.svelte` — display from new fields; drop the units / rate columns.
- `frontend/src/components/estimates/WizardSourcePool.svelte` — atom type `plan_charge` → `plan_task`.
- `frontend/src/routes/worksheets/WorksheetDetailPage.svelte` — verify task list still renders (consumes `WorksheetTaskTable`).

**Modify (tests):**
- `tests/test_atom_compute_amount.py`, `tests/test_atom_carry_over.py`, `tests/test_carry_over_signal.py`, `tests/test_estimate_line_item_source.py`, `tests/test_estimate_wizard_api.py`, `tests/test_estimate_wizard_service.py`, `tests/test_estimate_charge.py` — rename atom usage; create billing fields on `PlanTask` directly instead of via `PlanCharge`.
- Keep `tests/test_task_charge.py` and `tests/test_task_charge_api.py` — these test the real-side `TaskCharge`, which is unchanged.

**Modify (fixtures):**
- `fixtures/large_datasets/nealseed.json` — back-fill billing fields on `jobs.plantask` records (use a sensible default `RateScheme`).
- `fixtures/unit_test_data.json` — same.

---

## Phase 1 — Add atom fields to PlanTask (additive)

### Task 1: Add nullable atom fields and `compute_amount()` to `PlanTask`

**Files:**
- Modify: `apps/jobs/models.py:153-173` (the `PlanTask` class)
- Test: `tests/test_atom_compute_amount.py` (existing — extend)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_atom_compute_amount.py`:

```python
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import PlanTask, RateScheme
from apps.estimates.models import EstWorksheet
from tests.base import FixtureTestCase


class PlanTaskComputeAmountTests(FixtureTestCase):
    def test_compute_amount_with_scheme(self):
        scheme = RateScheme.objects.create(
            name='Test Hourly', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('60.00'), unit_label='hour',
        )
        ws = EstWorksheet.objects.first()
        pt = PlanTask.objects.create(
            est_worksheet=ws, name='Test',
            rate_scheme=scheme,
            active_modifiers=[],
            estimated_billable_qty=Decimal('2.5'),
        )
        self.assertEqual(pt.compute_amount(), Decimal('150.00'))

    def test_compute_amount_without_scheme_returns_zero(self):
        ws = EstWorksheet.objects.first()
        pt = PlanTask.objects.create(est_worksheet=ws, name='Bare')
        self.assertEqual(pt.compute_amount(), Decimal('0.00'))
```

- [ ] **Step 2: Run test to verify it fails**

`python manage.py test tests.test_atom_compute_amount.PlanTaskComputeAmountTests -v 2`

Expected: FAIL — `PlanTask` has no field `rate_scheme`.

- [ ] **Step 3: Add fields and method to PlanTask**

In `apps/jobs/models.py`:

```python
class PlanTask(TaskBase):
    """Planning task on an EstWorksheet. No lifecycle, no hierarchy, no bleps."""
    plan_task_id = models.AutoField(primary_key=True)
    est_worksheet = models.ForeignKey(
        'estimates.EstWorksheet', on_delete=models.CASCADE, related_name='plan_tasks'
    )
    rate_scheme = models.ForeignKey(
        'jobs.RateScheme', on_delete=models.PROTECT, null=True, blank=True,
    )
    active_modifiers = models.JSONField(default=list, blank=True)
    estimated_billable_qty = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
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

    def compute_amount(self, active_modifiers=None):
        from decimal import Decimal
        if not self.rate_scheme_id or self.estimated_billable_qty is None:
            return Decimal('0.00')
        return self.rate_scheme.compute_charge(
            self.estimated_billable_qty, self.active_modifiers,
        )

    def effective_rate(self):
        if not self.rate_scheme_id:
            return None
        return self.rate_scheme.effective_rate(self.active_modifiers)
```

- [ ] **Step 4: Generate the migration**

`python manage.py makemigrations jobs`

Expected: a new migration file adding `rate_scheme`, `active_modifiers`, `estimated_billable_qty` to `plantask`. Inspect it; it should ONLY touch `PlanTask`, not `Task`.

- [ ] **Step 5: Run the test**

`python manage.py test tests.test_atom_compute_amount.PlanTaskComputeAmountTests -v 2`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/ tests/test_atom_compute_amount.py
git commit -m "feat: add atom billing fields and compute_amount to PlanTask"
```

---

### Task 2: Data migration — copy `PlanCharge` rows onto `PlanTask`

**Files:**
- Create: `apps/jobs/migrations/NNNN_copy_plan_charge_to_plan_task.py` (NNNN = next number)
- Test: `tests/test_plan_charge_data_migration.py` (new)

- [ ] **Step 1: Write the failing test**

`tests/test_plan_charge_data_migration.py`:

```python
from decimal import Decimal
from django.test import TransactionTestCase
from django_test_migrations.migrator import Migrator


class PlanChargeDataMigrationTests(TransactionTestCase):
    """Verify the data migration copies PlanCharge fields onto PlanTask."""

    def test_data_is_copied(self):
        # If django_test_migrations isn't installed, fall back to a
        # plain pre/post-state assertion against current models.
        from apps.jobs.models import PlanTask, PlanCharge, RateScheme
        from apps.estimates.models import EstWorksheet
        # Sanity: every PlanCharge in fixtures should be reflected in PlanTask
        for pc in PlanCharge.objects.all():
            pt = pc.plan_task
            self.assertEqual(pt.rate_scheme_id, pc.rate_scheme_id)
            self.assertEqual(pt.active_modifiers, pc.active_modifiers)
            self.assertEqual(pt.estimated_billable_qty, pc.estimated_billable_qty)
```

(`django_test_migrations` is not currently a dependency; if absent, the simpler assertion against current models is fine — it verifies the post-migration state.)

- [ ] **Step 2: Run test to verify it fails**

`python manage.py test tests.test_plan_charge_data_migration -v 2`

Expected: FAIL — fields on `PlanTask` are still NULL for any seed data with `PlanCharge` rows.

- [ ] **Step 3: Write the data migration**

`apps/jobs/migrations/NNNN_copy_plan_charge_to_plan_task.py`:

```python
from django.db import migrations


def copy_forward(apps, schema_editor):
    PlanCharge = apps.get_model('jobs', 'PlanCharge')
    for pc in PlanCharge.objects.all():
        pt = pc.plan_task
        pt.rate_scheme_id = pc.rate_scheme_id
        pt.active_modifiers = pc.active_modifiers
        pt.estimated_billable_qty = pc.estimated_billable_qty
        pt.save(update_fields=['rate_scheme', 'active_modifiers', 'estimated_billable_qty'])


def copy_back(apps, schema_editor):
    # Reverse: clear fields on PlanTask. PlanCharge rows are untouched.
    PlanTask = apps.get_model('jobs', 'PlanTask')
    PlanTask.objects.update(
        rate_scheme=None, active_modifiers=[], estimated_billable_qty=None,
    )


class Migration(migrations.Migration):
    dependencies = [('jobs', '<previous-migration-from-task-1>')]
    operations = [migrations.RunPython(copy_forward, copy_back)]
```

Replace `<previous-migration-from-task-1>` with the actual filename stem from Task 1.

- [ ] **Step 4: Run the test**

`python manage.py test tests.test_plan_charge_data_migration -v 2`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/migrations/ tests/test_plan_charge_data_migration.py
git commit -m "feat: copy PlanCharge fields onto PlanTask"
```

---

## Phase 2 — Wire wizard service to `PlanTask` atoms

### Task 3: Rename source type — `SOURCE_PLAN_CHARGE` → `SOURCE_PLAN_TASK`

**Files:**
- Modify: `apps/estimates/models.py:495-540` (`EstimateLineItemSource`)
- Modify: `apps/api/estimates/serializers.py` (resolution helper)
- Create: data migration to rewrite existing source rows
- Test: `tests/test_estimate_line_item_source.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_estimate_line_item_source.py`:

```python
def test_source_resolves_to_plan_task(self):
    from apps.estimates.models import EstimateLineItemSource
    from apps.jobs.models import PlanTask
    pt = PlanTask.objects.first()
    src = EstimateLineItemSource.objects.create(
        estimate_line_item=self.make_line_item(),
        source_type=EstimateLineItemSource.SOURCE_PLAN_TASK,
        source_pk=pt.pk,
    )
    self.assertEqual(src.resolve(), pt)
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `SOURCE_PLAN_TASK` does not exist.

- [ ] **Step 3: Update model and resolution**

In `apps/estimates/models.py`:

```python
class EstimateLineItemSource(models.Model):
    SOURCE_PLAN_TASK = 'plan_task'
    SOURCE_PLAN_MATERIAL = 'plan_material'
    SOURCE_TYPE_CHOICES = [
        (SOURCE_PLAN_TASK, 'PlanTask'),
        (SOURCE_PLAN_MATERIAL, 'PlanMaterial'),
    ]

    # ... existing fields unchanged ...

    def resolve(self):
        if self.source_type == self.SOURCE_PLAN_TASK:
            from apps.jobs.models import PlanTask
            return PlanTask.objects.get(pk=self.source_pk)
        if self.source_type == self.SOURCE_PLAN_MATERIAL:
            from apps.inventory.models import PlanMaterial
            return PlanMaterial.objects.get(pk=self.source_pk)
        raise ValueError(f'Unknown source_type: {self.source_type}')
```

Drop `SOURCE_PLAN_CHARGE`; do not keep an alias.

- [ ] **Step 4: Generate schema migration**

`python manage.py makemigrations estimates`

Expected: an `AlterField` updating `source_type` choices.

- [ ] **Step 5: Add a data migration to rewrite existing rows**

`apps/estimates/migrations/NNNN_rewrite_source_type_to_plan_task.py`:

```python
from django.db import migrations


def rewrite_forward(apps, schema_editor):
    Source = apps.get_model('estimates', 'EstimateLineItemSource')
    PlanCharge = apps.get_model('jobs', 'PlanCharge')
    for src in Source.objects.filter(source_type='plan_charge'):
        try:
            pc = PlanCharge.objects.get(pk=src.source_pk)
        except PlanCharge.DoesNotExist:
            continue
        src.source_type = 'plan_task'
        src.source_pk = pc.plan_task_id
        src.save(update_fields=['source_type', 'source_pk'])


def rewrite_back(apps, schema_editor):
    Source = apps.get_model('estimates', 'EstimateLineItemSource')
    PlanCharge = apps.get_model('jobs', 'PlanCharge')
    for src in Source.objects.filter(source_type='plan_task'):
        pc = PlanCharge.objects.filter(plan_task_id=src.source_pk).first()
        if pc:
            src.source_type = 'plan_charge'
            src.source_pk = pc.pk
            src.save(update_fields=['source_type', 'source_pk'])


class Migration(migrations.Migration):
    dependencies = [
        ('estimates', '<schema-migration-from-step-4>'),
        ('jobs', '<task-2-migration>'),
    ]
    operations = [migrations.RunPython(rewrite_forward, rewrite_back)]
```

- [ ] **Step 6: Run the test**

`python manage.py test tests.test_estimate_line_item_source -v 2`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/estimates/models.py apps/estimates/migrations/ apps/api/estimates/serializers.py tests/test_estimate_line_item_source.py
git commit -m "refactor: rename EstimateLineItemSource type plan_charge -> plan_task"
```

---

### Task 4: Update `EstimateWizardService` to iterate `PlanTask`

**Files:**
- Modify: `apps/estimates/services.py:443-770` (`EstimateWizardService`)
- Test: `tests/test_estimate_wizard_service.py`, `tests/test_estimate_wizard_api.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_estimate_wizard_service.py`:

```python
def test_source_pool_includes_plan_tasks_without_explicit_charge_creation(self):
    """Bug regression: PlanTasks should appear in the source pool even when
    no separate PlanCharge POST has fired — the billing fields are on the
    PlanTask itself now."""
    from apps.estimates.services import EstimateWizardService
    from apps.jobs.models import PlanTask, RateScheme

    scheme = RateScheme.objects.create(
        name='Hourly Test', algorithm=RateScheme.ENTERED_QTY,
        rate=Decimal('50.00'), unit_label='hour',
    )
    pt = PlanTask.objects.create(
        est_worksheet=self.worksheet, name='Inline Task',
        rate_scheme=scheme, estimated_billable_qty=Decimal('3.0'),
    )

    pool = EstimateWizardService.get_source_pool(self.worksheet)

    plan_task_ids = [a['id'] for a in pool['atoms'] if a['type'] == 'plan_task']
    self.assertIn(pt.pk, plan_task_ids)
    pt_atom = next(a for a in pool['atoms'] if a['type'] == 'plan_task' and a['id'] == pt.pk)
    self.assertEqual(pt_atom['amount'], Decimal('150.00'))
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — atom `type` is currently `plan_charge` and the query joins through it.

- [ ] **Step 3: Rewrite the service helpers and `get_source_pool`**

In `apps/estimates/services.py`, replace `EstimateWizardService._resolve_atom`, `_atom_source_type`, `_atom_category`, `_atom_description`, `_atom_units`, and `get_source_pool`. New implementations:

```python
@staticmethod
def _resolve_atom(atom_ref):
    """Convert {'type': 'plan_task'|'plan_material', 'id': N} to a model instance."""
    from apps.jobs.models import PlanTask
    from apps.inventory.models import PlanMaterial
    atom_type = atom_ref.get('type')
    atom_id = atom_ref.get('id')
    if atom_type == 'plan_task':
        try:
            return PlanTask.objects.get(pk=atom_id)
        except PlanTask.DoesNotExist:
            raise ValidationError(f'PlanTask {atom_id} not found')
    if atom_type == 'plan_material':
        try:
            return PlanMaterial.objects.get(pk=atom_id)
        except PlanMaterial.DoesNotExist:
            raise ValidationError(f'PlanMaterial {atom_id} not found')
    raise ValidationError(f'Unknown atom type: {atom_type}')

@staticmethod
def _atom_source_type(atom_instance):
    from apps.jobs.models import PlanTask
    from apps.inventory.models import PlanMaterial
    from apps.estimates.models import EstimateLineItemSource
    if isinstance(atom_instance, PlanTask):
        return EstimateLineItemSource.SOURCE_PLAN_TASK
    if isinstance(atom_instance, PlanMaterial):
        return EstimateLineItemSource.SOURCE_PLAN_MATERIAL
    raise ValueError(f'Unknown atom instance type: {type(atom_instance)}')

@staticmethod
def _atom_category(atom_instance):
    from apps.jobs.models import PlanTask
    from apps.inventory.models import PlanMaterial
    if isinstance(atom_instance, PlanTask):
        return atom_instance.accounting_category
    if isinstance(atom_instance, PlanMaterial):
        return atom_instance.accounting_category
    return None

@staticmethod
def _atom_description(atom_instance):
    from apps.jobs.models import PlanTask
    from apps.inventory.models import PlanMaterial
    if isinstance(atom_instance, PlanTask):
        return atom_instance.name
    if isinstance(atom_instance, PlanMaterial):
        return atom_instance.description
    return ''

@staticmethod
def _atom_units(atom_instance):
    from apps.jobs.models import PlanTask
    from apps.inventory.models import PlanMaterial
    if isinstance(atom_instance, PlanTask):
        if atom_instance.rate_scheme_id:
            return atom_instance.rate_scheme.unit_label
        return 'each'
    if isinstance(atom_instance, PlanMaterial):
        return 'each'
    return 'each'

@staticmethod
def get_source_pool(worksheet):
    from apps.estimates.models import EstimateLineItemSource
    from apps.jobs.models import PlanTask
    from apps.inventory.models import PlanMaterial

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

    for pt in PlanTask.objects.filter(est_worksheet=worksheet).select_related(
        'accounting_category', 'rate_scheme',
    ):
        key = (EstimateLineItemSource.SOURCE_PLAN_TASK, pt.pk)
        state_info = claims.get(key, default_state)
        atoms.append({
            'type': 'plan_task',
            'id': pt.pk,
            'description': pt.name,
            'amount': pt.compute_amount().quantize(Decimal('0.01')),
            'units': pt.rate_scheme.unit_label if pt.rate_scheme_id else 'each',
            'category_id': pt.accounting_category_id,
            **state_info,
        })

    for pm in PlanMaterial.objects.filter(est_worksheet=worksheet).select_related('accounting_category'):
        key = (EstimateLineItemSource.SOURCE_PLAN_MATERIAL, pm.pk)
        state_info = claims.get(key, default_state)
        atoms.append({
            'type': 'plan_material',
            'id': pm.pk,
            'description': pm.description,
            'amount': pm.compute_amount().quantize(Decimal('0.01')),
            'units': 'each',
            'category_id': pm.accounting_category_id,
            **state_info,
        })

    return {'atoms': atoms}
```

- [ ] **Step 4: Update the bulk `send_all_atoms_to_estimate` helper**

In the same service (around line 770-820, find the iteration over `PlanCharge.objects.filter(plan_task__est_worksheet=worksheet)`), change to `PlanTask.objects.filter(est_worksheet=worksheet)` and read `name`/`accounting_category` directly off the PlanTask. Skip PlanTasks where `compute_amount() == 0` so we don't generate $0 line items by default — or include them; pick whichever the existing test suite expects. Update the test if needed.

- [ ] **Step 5: Update other test files**

Search and replace in:
- `tests/test_estimate_wizard_service.py`
- `tests/test_estimate_wizard_api.py`
- `tests/test_estimate_charge.py`

Replace any test setup that creates a `PlanTask` then a `PlanCharge` with a single `PlanTask.objects.create(..., rate_scheme=..., estimated_billable_qty=...)`. Replace `'plan_charge'` literal atom-type strings with `'plan_task'`.

- [ ] **Step 6: Run the targeted tests**

```bash
python manage.py test tests.test_estimate_wizard_service tests.test_estimate_wizard_api tests.test_estimate_charge -v 2
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/estimates/services.py tests/test_estimate_wizard_service.py tests/test_estimate_wizard_api.py tests/test_estimate_charge.py
git commit -m "refactor: estimate wizard iterates PlanTask atoms directly"
```

---

### Task 5: Rename `Task.source_plan_charge` → `Task.source_plan_task`

**Files:**
- Modify: `apps/jobs/models.py:211-217` (`Task.source_plan_charge`)
- Create: schema + data migration
- Modify: `apps/estimates/carry_over.py` (Task 6)
- Test: `tests/test_atom_carry_over.py`, `tests/test_carry_over_signal.py`

- [ ] **Step 1: Add the new field, keep the old one**

In `apps/jobs/models.py:211-217` add `source_plan_task` alongside the existing `source_plan_charge` (both nullable):

```python
source_plan_charge = models.OneToOneField(
    'jobs.PlanCharge',
    on_delete=models.SET_NULL,
    null=True, blank=True,
    related_name='carried_task',
)
source_plan_task = models.OneToOneField(
    'jobs.PlanTask',
    on_delete=models.SET_NULL,
    null=True, blank=True,
    related_name='carried_task_new',  # temporary; renamed back after old field is dropped
)
```

- [ ] **Step 2: Generate the schema migration**

`python manage.py makemigrations jobs`

Expected: `AddField` for `source_plan_task` only.

- [ ] **Step 3: Add a data migration to back-fill `source_plan_task`**

`apps/jobs/migrations/NNNN_backfill_task_source_plan_task.py`:

```python
from django.db import migrations


def backfill_forward(apps, schema_editor):
    Task = apps.get_model('jobs', 'Task')
    for task in Task.objects.exclude(source_plan_charge_id=None).select_related('source_plan_charge'):
        task.source_plan_task_id = task.source_plan_charge.plan_task_id
        task.save(update_fields=['source_plan_task'])


def backfill_back(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('jobs', '<schema-migration-from-step-2>')]
    operations = [migrations.RunPython(backfill_forward, backfill_back)]
```

- [ ] **Step 4: Update test setup**

In `tests/test_atom_carry_over.py` and `tests/test_carry_over_signal.py`, anywhere a test asserts on or sets `source_plan_charge`, also exercise `source_plan_task`. Don't drop the old assertions yet; the old field is still around.

- [ ] **Step 5: Run the tests**

`python manage.py test tests.test_atom_carry_over tests.test_carry_over_signal -v 2`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/ tests/
git commit -m "feat: add Task.source_plan_task and back-fill from source_plan_charge"
```

---

### Task 6: Update `AtomCarryOverService` to walk `PlanTask`

**Files:**
- Modify: `apps/estimates/carry_over.py:46-103`
- Test: `tests/test_atom_carry_over.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_atom_carry_over.py`:

```python
def test_carry_over_uses_plan_task_directly(self):
    from apps.jobs.models import PlanTask, RateScheme, Task
    from apps.estimates.carry_over import AtomCarryOverService

    scheme = RateScheme.objects.create(
        name='Carry Hourly', algorithm=RateScheme.ENTERED_QTY,
        rate=Decimal('40.00'), unit_label='hour',
    )
    pt = PlanTask.objects.create(
        est_worksheet=self.worksheet, name='Inline atom',
        rate_scheme=scheme, estimated_billable_qty=Decimal('2.0'),
    )

    AtomCarryOverService.carry_over_for_estimate(self.estimate)

    task = Task.objects.get(source_plan_task=pt)
    self.assertEqual(task.charge.rate_scheme_id, scheme.pk)
    self.assertEqual(task.charge.actuals.get('qty'), '2.0')
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — current carry-over walks PlanCharge.

- [ ] **Step 3: Rewrite `_carry_over_plan_charges` (rename to `_carry_over_plan_tasks`)**

Replace `apps/estimates/carry_over.py:47-76`:

```python
@staticmethod
def _carry_over_plan_tasks(worksheet, job):
    from apps.jobs.models import PlanTask, RateScheme, Task, TaskCharge
    count = 0
    for pt in PlanTask.objects.filter(
        est_worksheet=worksheet,
    ).select_related('rate_scheme', 'accounting_category'):
        if Task.objects.filter(job=job, source_plan_task=pt).exists():
            continue
        if not pt.rate_scheme_id:
            # Plan task with no billing config — carry as a Task without a TaskCharge.
            Task.objects.create(
                job=job, name=pt.name, description=pt.description,
                accounting_category=pt.accounting_category,
                source_plan_task=pt,
            )
            count += 1
            continue
        task = Task.objects.create(
            job=job, name=pt.name, description=pt.description,
            accounting_category=pt.accounting_category,
            source_plan_task=pt,
        )
        actuals = {}
        if pt.rate_scheme.algorithm == RateScheme.ENTERED_QTY and pt.estimated_billable_qty is not None:
            actuals = {'qty': str(pt.estimated_billable_qty.normalize())}
        TaskCharge.objects.create(
            task=task,
            rate_scheme=pt.rate_scheme,
            active_modifiers=pt.active_modifiers,
            actuals=actuals,
        )
        count += 1
    return count
```

Update the caller at line 32: `tasks_created += AtomCarryOverService._carry_over_plan_tasks(worksheet, job)`.

Also update `_carry_over_plan_materials` line 90 — change the lookup `source_plan_charge__plan_task=pm.plan_task` to `source_plan_task=pm.plan_task`.

Note: this carry-over creates `Task` rows that no longer carry the legacy `units`/`rate`/`est_qty` from the plan task — those fields are about to be moved off of `PlanTask` anyway. On the real side, billing flows entirely through `TaskCharge`. If existing tests assert on `task.units` or similar after carry-over, update them to assert on `task.charge.rate_scheme` instead.

- [ ] **Step 4: Run carry-over tests**

`python manage.py test tests.test_atom_carry_over tests.test_carry_over_signal -v 2`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/carry_over.py tests/
git commit -m "refactor: carry-over walks PlanTask atoms directly"
```

---

## Phase 3 — Frontend rewire

### Task 7: Update `PlanTaskSerializer` to expose new atom fields

**Files:**
- Modify: `apps/api/worksheets/serializers.py:30-41`
- Test: `tests/test_estimate_wizard_api.py` or a new `tests/test_plan_task_api.py`

- [ ] **Step 1: Write the failing test**

```python
def test_plan_task_create_via_api_includes_billing(self):
    from apps.jobs.models import RateScheme
    scheme = RateScheme.objects.create(
        name='Test', algorithm=RateScheme.ENTERED_QTY,
        rate=Decimal('30.00'), unit_label='hour',
    )
    self.client.force_login(self.user)
    resp = self.client.post(
        f'/api/est-worksheets/{self.worksheet.pk}/tasks/',
        {
            'name': 'Test Task',
            'description': '',
            'accounting_category': None,
            'rate_scheme': scheme.pk,
            'active_modifiers': [],
            'estimated_billable_qty': '4.5',
        },
        content_type='application/json',
    )
    self.assertEqual(resp.status_code, 201)
    self.assertEqual(resp.json()['estimated_billable_qty'], '4.50')
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — serializer doesn't accept `rate_scheme` etc.

- [ ] **Step 3: Update the serializer**

`apps/api/worksheets/serializers.py:30-41`:

```python
class PlanTaskSerializer(serializers.ModelSerializer):
    plan_materials = PlanMaterialSerializer(many=True, read_only=True)
    amount = serializers.SerializerMethodField()

    class Meta:
        model = PlanTask
        fields = [
            'plan_task_id', 'name', 'description', 'sort_order',
            'accounting_category',
            'rate_scheme', 'active_modifiers', 'estimated_billable_qty',
            'amount', 'plan_materials',
        ]
        read_only_fields = ['plan_task_id', 'sort_order', 'amount']

    def get_amount(self, obj):
        return str(obj.compute_amount().quantize(Decimal('0.01')))
```

(Drop the `units = UnitsField()` line and the `units`, `rate`, `est_qty` strings from `fields`. Drop the `UnitsField` import if no longer used.)

- [ ] **Step 4: Run the test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/worksheets/serializers.py tests/
git commit -m "feat: PlanTaskSerializer exposes atom billing fields"
```

---

### Task 8: Frontend — `WizardSourcePool.svelte` atom-type rename

**Files:**
- Modify: `frontend/src/components/estimates/WizardSourcePool.svelte:32`

- [ ] **Step 1: Update the type check**

```svelte
<small>[{atom.type === 'plan_task' ? 'task' : 'material'}]</small>
```

(Single string change. No tests to write — this is a label rendering and is exercised indirectly when running the dev server.)

- [ ] **Step 2: Manual verification**

Start backend (`python manage.py runserver`) and frontend (`cd frontend && npm run dev`). Open a worksheet wizard. Confirm task atoms render with the `[task]` tag and material atoms with the `[material]` tag. (CLAUDE.md requires manual UI verification for frontend changes.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/estimates/WizardSourcePool.svelte
git commit -m "fix: wizard source pool labels plan_task atoms correctly"
```

---

### Task 9: Frontend — `PlanTaskModal.svelte` single-save with billing

**Files:**
- Modify: `frontend/src/components/PlanTaskModal.svelte`

- [ ] **Step 1: Strip the legacy fields and the second POST**

Goals for the new modal:
- Inputs: `name`, `description`, `accounting_category`, `rate_scheme`, `active_modifiers` (driven by selected scheme), `estimated_billable_qty`.
- Removed inputs: `units`, `rate`, `est_qty` (legacy fields), and the separate `/charge/` POST.
- Both create-modes (freeform, from-template) save through the same endpoint with all billing fields included in one request.

Replace the script block roughly as follows (full file rewrite is fine — keep the styles unchanged):

```svelte
<script>
  import { api } from '../lib/api.js';

  let {
    open = false,
    mode = 'create-freeform',
    task = null,
    worksheetId = null,
    templates = [],
    categories = [],
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let createMode = $state('freeform');
  let name = $state('');
  let description = $state('');
  let accountingCategory = $state('');
  let templateId = $state('');
  let rateSchemeId = $state('');
  let estimatedBillableQty = $state('');
  let activeModifiers = $state([]);
  let schemes = $state([]);
  let busy = $state(false);
  let error = $state('');

  $effect(() => {
    if (open) {
      if (mode === 'edit' && task) {
        createMode = 'freeform';
        name = task.name || '';
        description = task.description || '';
        accountingCategory = task.accounting_category ?? '';
        rateSchemeId = task.rate_scheme ?? '';
        activeModifiers = [...(task.active_modifiers || [])];
        estimatedBillableQty = task.estimated_billable_qty ?? '';
        templateId = '';
      } else if (mode === 'create-template') {
        createMode = 'template';
        resetFields();
      } else {
        createMode = 'freeform';
        resetFields();
      }
      error = '';
      loadSchemes();
    }
  });

  function resetFields() {
    name = ''; description = ''; accountingCategory = '';
    rateSchemeId = ''; estimatedBillableQty = '';
    activeModifiers = []; templateId = '';
  }

  async function loadSchemes() {
    try {
      const data = await api.get('/api/rate-schemes/');
      schemes = data.results ?? data;
    } catch (e) {
      // non-fatal
    }
  }

  const isEdit = $derived(mode === 'edit');
  const title = $derived(isEdit ? 'Edit Task' : 'Add Task');

  const selectedTemplate = $derived(
    templates.find(t => String(t.template_id) === String(templateId)) || null
  );

  const selectedScheme = $derived.by(() => {
    if (createMode === 'template' && selectedTemplate?.rate_scheme) {
      return schemes.find(s => s.rate_scheme_id === selectedTemplate.rate_scheme) || null;
    }
    if (rateSchemeId) {
      return schemes.find(s => s.rate_scheme_id === Number(rateSchemeId)) || null;
    }
    return null;
  });

  $effect(() => {
    if (selectedTemplate) {
      activeModifiers = [...(selectedTemplate.default_active_modifiers || [])];
      if (selectedTemplate.default_billable_qty && !estimatedBillableQty) {
        estimatedBillableQty = selectedTemplate.default_billable_qty;
      }
      if (selectedTemplate.rate_scheme && !rateSchemeId) {
        rateSchemeId = selectedTemplate.rate_scheme;
      }
    }
  });

  const chargePreview = $derived.by(() => {
    if (!selectedScheme || !estimatedBillableQty) return null;
    const baseRate = Number(selectedScheme.rate);
    const modPct = (selectedScheme.modifiers || [])
      .filter(m => activeModifiers.includes(m.key))
      .reduce((sum, m) => sum + m.percent, 0);
    return (Number(estimatedBillableQty) * baseRate * (1 + modPct / 100)).toFixed(2);
  });

  function toggleModifier(key) {
    activeModifiers = activeModifiers.includes(key)
      ? activeModifiers.filter(k => k !== key)
      : [...activeModifiers, key];
  }

  async function save() {
    busy = true;
    error = '';
    try {
      const payload = {
        name,
        description,
        accounting_category: accountingCategory || null,
        rate_scheme: rateSchemeId || null,
        active_modifiers: activeModifiers,
        estimated_billable_qty: estimatedBillableQty || null,
      };
      if (isEdit && task) {
        await api.patch(
          `/api/est-worksheets/${worksheetId}/tasks/${task.plan_task_id}/`,
          payload,
        );
      } else if (createMode === 'template') {
        if (!templateId) { error = 'Please select a template.'; busy = false; return; }
        await api.post(`/api/est-worksheets/${worksheetId}/add-from-template/`, {
          task_template_id: Number(templateId),
          estimated_billable_qty: estimatedBillableQty || null,
          rate_scheme: rateSchemeId || null,
          active_modifiers: activeModifiers,
        });
      } else {
        await api.post(`/api/est-worksheets/${worksheetId}/tasks/`, payload);
      }
      onSaved();
    } catch (e) {
      if (e.data && typeof e.data === 'object' && !e.data.detail) {
        error = Object.entries(e.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        error = e.message || 'Could not save task.';
      }
    } finally {
      busy = false;
    }
  }
</script>
```

Update the markup block to drop the `Units` / `Rate` / `Estimated Quantity` inputs and add a single `Estimated billable qty` input plus the always-visible rate-scheme picker:

```svelte
{#if open}
  <div class="overlay">
    <div class="modal">
      <h3>{title}</h3>

      {#if !isEdit}
        <div class="mode-toggle">
          <label><input type="radio" bind:group={createMode} value="freeform"> Freeform</label>
          <label><input type="radio" bind:group={createMode} value="template"> From Template</label>
        </div>
      {/if}

      {#if createMode === 'template' && !isEdit}
        <p>
          <label><strong>Template *</strong><br>
            <select bind:value={templateId}>
              <option value="">-- Select template --</option>
              {#each templates as tmpl}
                <option value={tmpl.template_id}>{tmpl.template_name}</option>
              {/each}
            </select>
          </label>
        </p>
      {:else}
        <p>
          <label><strong>Name *</strong><br>
            <input type="text" bind:value={name} style="width:100%;box-sizing:border-box;">
          </label>
        </p>
        <p>
          <label><strong>Description</strong><br>
            <input type="text" bind:value={description} style="width:100%;box-sizing:border-box;">
          </label>
        </p>
        <p>
          <label><strong>Accounting Category</strong><br>
            <select bind:value={accountingCategory}>
              <option value="">-- None --</option>
              {#each categories as cat}
                <option value={cat.id}>{cat.code} — {cat.name}</option>
              {/each}
            </select>
          </label>
        </p>
      {/if}

      <p>
        <label><strong>Rate scheme</strong><br>
          <select bind:value={rateSchemeId}>
            <option value="">-- None (no billing) --</option>
            {#each schemes as scheme}
              <option value={scheme.rate_scheme_id}>{scheme.name}</option>
            {/each}
          </select>
        </label>
      </p>

      {#if selectedScheme}
        <p><strong>{selectedScheme.name}</strong> — ${selectedScheme.rate}/{selectedScheme.unit_label}</p>
        {#if (selectedScheme.modifiers || []).length > 0}
          <fieldset>
            <legend><strong>Modifiers</strong></legend>
            {#each selectedScheme.modifiers as mod}
              <label>
                <input type="checkbox"
                  checked={activeModifiers.includes(mod.key)}
                  onchange={() => toggleModifier(mod.key)}>
                {mod.label} (+{mod.percent}%)
              </label><br>
            {/each}
          </fieldset>
        {/if}
        <p>
          <label><strong>Estimated billable qty</strong><br>
            <input type="number" step="0.01" bind:value={estimatedBillableQty}>
          </label>
        </p>
        {#if chargePreview !== null}
          <p><strong>Estimated charge:</strong> ${chargePreview}</p>
        {/if}
      {/if}

      <div class="buttons">
        <button type="button" onclick={save} disabled={busy}>Save</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
    </div>
  </div>
{/if}
```

(The `<style>` block at the bottom of the file is unchanged.)

- [ ] **Step 2: Manual verification**

Run the dev servers. Open a worksheet, add a task in freeform mode with a rate scheme picked, save, confirm it appears in the wizard's source pool with a non-zero amount. Add a task in template mode, save, confirm same. Edit an existing task and confirm fields round-trip.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/PlanTaskModal.svelte
git commit -m "refactor: PlanTaskModal saves billing in one request"
```

---

### Task 10: Frontend — `WorksheetTaskTable.svelte` displays new fields

**Files:**
- Modify: `frontend/src/components/WorksheetTaskTable.svelte`

- [ ] **Step 1: Replace task-total computation and column layout**

Drop the `units`/`rate` columns; show `Qty` (the `estimated_billable_qty`) and a derived `Total` from the serializer's `amount` field. Keep the materials sub-row layout untouched.

```svelte
<script>
  let {
    worksheet = null,
    readonly = false,
    onEditTask = () => {},
    onDeleteTask = () => {},
    onReorder = () => {},
    onAddMaterial = () => {},
    onEditMaterial = () => {},
    onDeleteMaterial = () => {},
  } = $props();

  const tasks = $derived(
    [...(worksheet?.tasks || [])].sort(
      (a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)
    )
  );

  function taskTotal(task) {
    return Number(task.amount) || 0;
  }

  function materialTotal(mat) {
    const qty = Number(mat.quantity) || 0;
    const price = Number(mat.sell_price) || 0;
    return qty * price;
  }

  const grandTotal = $derived.by(() => {
    let total = 0;
    for (const t of tasks) {
      total += taskTotal(t);
      for (const m of (t.plan_materials || [])) {
        total += materialTotal(m);
      }
    }
    return total;
  });

  function fmt(n) {
    return n ? `$${Number(n).toFixed(2)}` : '-';
  }
</script>

<table border="1" class="ws-task-table">
  <thead>
    <tr>
      <th>Name / Description</th>
      <th class="text-right">Qty</th>
      <th class="text-right">Total</th>
      {#if !readonly}<th>Actions</th>{/if}
    </tr>
  </thead>
  <tbody>
    {#each tasks as task, i}
      <tr class="task-row">
        <td>{task.name}{#if task.description}<br><span class="dim">{task.description}</span>{/if}</td>
        <td class="text-right">{task.estimated_billable_qty ?? '-'}</td>
        <td class="text-right">{fmt(taskTotal(task))}</td>
        {#if !readonly}
          <td class="actions-cell">
            <button type="button" onclick={() => onEditTask(task)}>edit</button>
            <button type="button" onclick={() => onDeleteTask(task)}>del</button>
            <button type="button" onclick={() => onAddMaterial(task)}>+mat</button>
            <button type="button" onclick={() => onReorder(task.plan_task_id, 'up')} disabled={i === 0}>&#9650;</button>
            <button type="button" onclick={() => onReorder(task.plan_task_id, 'down')} disabled={i === tasks.length - 1}>&#9660;</button>
          </td>
        {/if}
      </tr>
      {#each (task.plan_materials || []) as mat}
        <tr class="material-row">
          <td class="indent"><span class="material-marker">&#9679;</span> {mat.description || '(no description)'}</td>
          <td class="text-right">{mat.quantity ?? '-'}</td>
          <td class="text-right">{fmt(materialTotal(mat))}</td>
          {#if !readonly}
            <td class="actions-cell">
              <button type="button" onclick={() => onEditMaterial(mat, task)}>edit</button>
              <button type="button" onclick={() => onDeleteMaterial(mat, task)}>del</button>
            </td>
          {/if}
        </tr>
      {/each}
    {/each}
  </tbody>
  <tfoot>
    <tr class="grand-total-row">
      <td colspan="2" class="text-right"><strong>Grand Total</strong></td>
      <td class="text-right"><strong>{fmt(grandTotal)}</strong></td>
      {#if !readonly}<td></td>{/if}
    </tr>
  </tfoot>
</table>
```

(The `<style>` block at the bottom of the file is unchanged.)

- [ ] **Step 2: Manual verification**

Open a worksheet with at least one task that has a rate scheme set. Confirm the table shows Qty and Total correctly. Confirm grand total matches sum of task amounts plus material amounts.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/WorksheetTaskTable.svelte
git commit -m "refactor: worksheet task table reads from atom amount field"
```

---

## Phase 4 — Drop `PlanCharge` and the `/charge/` endpoint

### Task 11: Drop `PlanChargeSerializer`, `plan_charge_view`, and the URL

**Files:**
- Modify: `apps/api/plan_tasks/views.py:18-68` (remove `PlanChargeSerializer` and `plan_charge_view`)
- Modify: `apps/api/urls.py:14, 102` (remove import and URL pattern)

- [ ] **Step 1: Delete `plan_charge_view` and its URL**

In `apps/api/urls.py`:
- Remove `plan_charge_view` from the import on line 14.
- Delete the `path('est-worksheets/<int:ws_pk>/plan-tasks/<int:pt_pk>/charge/', plan_charge_view, ...)` line.

In `apps/api/plan_tasks/views.py`:
- Delete `PlanChargeSerializer` (lines 18-25).
- Delete the `plan_charge_view` function (lines 28-68).
- Remove the `from apps.jobs.models import PlanTask, PlanCharge` import: leave only `PlanTask`.

- [ ] **Step 2: Run all tests touching the wizard / carry-over**

```bash
python manage.py test tests.test_atom_compute_amount tests.test_atom_carry_over tests.test_carry_over_signal tests.test_estimate_wizard_service tests.test_estimate_wizard_api tests.test_estimate_line_item_source tests.test_estimate_charge -v 2
```

Expected: PASS (no test should be calling the dropped endpoint anymore — if one is, update the test to use the unified `tasks/` endpoint).

- [ ] **Step 3: Commit**

```bash
git add apps/api/plan_tasks/views.py apps/api/urls.py
git commit -m "remove: /plan-tasks/<id>/charge/ endpoint (billing on PlanTask now)"
```

---

### Task 12: Drop the `PlanCharge` model and `Task.source_plan_charge`

**Files:**
- Modify: `apps/jobs/models.py` — delete `PlanCharge` class (lines 385-411); delete `Task.source_plan_charge` field; rename `source_plan_task`'s `related_name` to `carried_task`.
- Modify: `apps/estimates/models.py:271-292` — remove the `EstWorksheet.create_new_version` PlanCharge handling (none today, but the plantask copy needs the new fields):
  - Update the `PlanTask.objects.create(...)` block to also copy `rate_scheme`, `active_modifiers`, `estimated_billable_qty`.
- Modify: `apps/core/management/commands/validate_data.py` — replace `PlanCharge` references with `PlanTask`.
- Modify: `apps/inventory/models.py:121-130` (cosmetic comment update).
- Test: existing tests should still pass.

- [ ] **Step 1: Update `EstWorksheet.create_new_version`**

In `apps/estimates/models.py`, the `create_new_version` loop creating new `PlanTask` rows must copy the new fields:

```python
for plan_task in self.plan_tasks.all():
    new_plan_task = PlanTask.objects.create(
        est_worksheet=new_worksheet,
        name=plan_task.name,
        description=plan_task.description,
        accounting_category=plan_task.accounting_category,
        rate_scheme=plan_task.rate_scheme,
        active_modifiers=list(plan_task.active_modifiers or []),
        estimated_billable_qty=plan_task.estimated_billable_qty,
    )

    for plan_material in plan_task.plan_materials.all():
        # unchanged
        ...
```

(Drop the `units`, `rate`, `est_qty` fields from this `create()` call — they no longer exist on `PlanTask`.)

- [ ] **Step 2: Drop `PlanCharge` and `Task.source_plan_charge`**

In `apps/jobs/models.py`:
- Delete the entire `PlanCharge` class (lines 385-411 in the current file).
- Delete the `source_plan_charge` field from `Task`.
- Rename `source_plan_task`'s `related_name='carried_task_new'` to `related_name='carried_task'`.

- [ ] **Step 3: Update `validate_data.py`**

In `apps/core/management/commands/validate_data.py`, replace the section validating `EstimateLineItemSource` rows pointing at `PlanCharge` (lines 631-654 in the current file). Use `PlanTask` lookup with the new `SOURCE_PLAN_TASK` constant. Update the help-text comment block at line 72 too.

- [ ] **Step 4: Update inventory comment**

In `apps/inventory/models.py:121-130`, replace the docstring mention of `PlanCharge` with `PlanTask` so the BillableAtom interface comment matches reality.

- [ ] **Step 5: Generate the migration**

`python manage.py makemigrations jobs`

Expected output: a `RemoveField` for `Task.source_plan_charge`, an `AlterField` renaming `Task.source_plan_task.related_name`, and a `DeleteModel` for `PlanCharge`. Inspect; reorder operations if Django generates them in a hostile order (the data migration in Task 5 ran earlier, so `source_plan_charge` is unused by now).

- [ ] **Step 6: Run the full estimate suite**

```bash
python manage.py test tests.test_atom_compute_amount tests.test_atom_carry_over tests.test_carry_over_signal tests.test_estimate_wizard_service tests.test_estimate_wizard_api tests.test_estimate_line_item_source tests.test_estimate_charge -v 2
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/ apps/estimates/models.py apps/core/management/commands/validate_data.py apps/inventory/models.py
git commit -m "remove: PlanCharge model; Task.source_plan_charge"
```

---

## Phase 5 — Drop legacy fields from `PlanTask`

### Task 13: Move `units`, `rate`, `est_qty` from `TaskBase` to `Task` only

**Files:**
- Modify: `apps/jobs/models.py:126-150` (`TaskBase`) — remove `units`, `rate`, `est_qty`
- Modify: `apps/jobs/models.py:176-249` (`Task`) — add `units`, `rate`, `est_qty` directly
- Modify: `apps/api/jobs/serializers.py` if any task serializer relies on inheriting these fields (verify; the change should be transparent because the field names are identical).

- [ ] **Step 1: Move the fields**

In `apps/jobs/models.py`, edit `TaskBase`:

```python
class TaskBase(models.Model):
    """Abstract base for PlanTask (worksheet) and Task (work order)."""
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    sort_order = models.PositiveIntegerField(blank=True, null=True)
    est_worker_time = models.DurationField(null=True, blank=True)
    accounting_category = models.ForeignKey(
        'core.AccountingCategory',
        on_delete=models.PROTECT,
        null=True, blank=True,
    )

    class Meta:
        abstract = True

    def __str__(self):
        return self.name
```

In `Task`:

```python
class Task(TaskBase):
    # ... existing constants and choices ...

    task_id = models.AutoField(primary_key=True)
    parent_task = models.ForeignKey('self', ...)
    assignee = models.ForeignKey('core.User', ...)
    source_template = models.ForeignKey('estimates.TaskTemplate', ...)
    source_plan_task = models.OneToOneField(
        'jobs.PlanTask',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='carried_task',
    )
    job = models.ForeignKey('jobs.Job', on_delete=models.CASCADE, related_name='tasks')
    status = models.CharField(...)
    blocked_reason = models.TextField(blank=True, default='')
    worker_queue = models.PositiveIntegerField(null=True, blank=True)

    # Legacy fields — kept on the real side for now; cleanup tracked separately.
    units = models.CharField(max_length=50, default='none')
    rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    est_qty = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = 'tasks'
```

- [ ] **Step 2: Generate the migration**

`python manage.py makemigrations jobs`

Expected: `RemoveField` for `units`, `rate`, `est_qty` on `PlanTask`; nothing on `Task` (the columns already exist; field origin moved from abstract to concrete is invisible at the schema level).

If Django auto-generates spurious `AlterField` operations on `Task`, that's fine — they're no-ops.

- [ ] **Step 3: Update fixtures**

Edit `fixtures/large_datasets/nealseed.json` and `fixtures/unit_test_data.json`. For each `jobs.plantask` record:
- Remove the `units`, `rate`, `est_qty` keys from `fields`.
- Add a default `rate_scheme` (use a known PK, e.g., the first hourly scheme), `active_modifiers: []`, and `estimated_billable_qty` derived from the old `est_qty`.

A scripted approach (run once, manually, against a checked-out copy of the fixtures):

```python
# scratch script — not committed
import json
DEFAULT_SCHEME_PK = 1   # adjust to a real RateScheme PK in the fixtures
for path in ['fixtures/large_datasets/nealseed.json', 'fixtures/unit_test_data.json']:
    data = json.load(open(path))
    for row in data:
        if row.get('model') == 'jobs.plantask':
            f = row['fields']
            qty = f.pop('est_qty', None)
            f.pop('rate', None)
            f.pop('units', None)
            f.setdefault('rate_scheme', DEFAULT_SCHEME_PK)
            f.setdefault('active_modifiers', [])
            f.setdefault('estimated_billable_qty', qty)
    json.dump(data, open(path, 'w'), indent=2)
```

- [ ] **Step 4: Run the full test suite**

`python manage.py test -v 1`

Expected: PASS. If anything fails on a missing legacy attribute on `PlanTask`, fix the call site to use the new fields.

- [ ] **Step 5: Manual verification**

Restart the dev servers. Load a worksheet from seed data. Confirm:
- The task table shows correct totals derived from `amount`.
- The wizard source pool shows all tasks with their amounts.
- Adding a new freeform task with a rate scheme works end to end.
- Editing an existing task round-trips correctly.

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/ fixtures/
git commit -m "remove: units/rate/est_qty from PlanTask (moved to Task only)"
```

---

## Phase 6 — Documentation

### Task 14: Update design doc and CLAUDE.md

**Files:**
- Modify: `docs/designs/2026-04-19-billable-atoms-and-estimate-wizard-design.md`
- Modify: `CLAUDE.md` (Key Models section)

- [ ] **Step 1: Note the merge in the design doc**

Append a short post-implementation note to `docs/designs/2026-04-19-billable-atoms-and-estimate-wizard-design.md` (under "Open questions" or as a new "Implementation deltas" section):

```markdown
## Implementation delta — 2026-05-01

`PlanCharge` was merged into `PlanTask`. The OneToOne split was gratuitous on the
plan side (no `actuals` analog, no per-charge lifecycle), and the dual-create
pattern was the proximate cause of plan tasks being invisible to the wizard
source pool. `Task` / `TaskCharge` remain split on the real side because
`TaskCharge.actuals` legitimately needs its own home.
```

- [ ] **Step 2: Update CLAUDE.md**

In `CLAUDE.md`, the Jobs section currently lists `PlanTask`, `PlanBundle`, `Blep` and so on. Update it to reflect:
- `PlanTask` carries billing fields directly (`rate_scheme`, `active_modifiers`, `estimated_billable_qty`).
- `PlanCharge` is gone.
- `TaskCharge` remains on the real side.

(Keep the surrounding bullets unchanged; one-line edit.)

- [ ] **Step 3: Commit**

```bash
git add docs/designs/2026-04-19-billable-atoms-and-estimate-wizard-design.md CLAUDE.md
git commit -m "docs: note PlanCharge merge into PlanTask"
```

- [ ] **Step 4: Delete this plan**

`docs/plans/` is for disposable plans. Once the work is in main and the implementation delta lives in the design doc, delete this file:

```bash
git rm docs/plans/2026-05-01-merge-plancharge-into-plantask.md
git commit -m "chore: remove completed plan"
```

---

## Self-review notes

Spec coverage:
- "Merge plan side" — Tasks 1–6, 11–13.
- "Remove rate/est_qty/units that aren't used" — Task 13.
- "Way to capture new atom-style info in Svelte" — Tasks 9 (modal), 10 (table).
- "Reuse the wizard code" — Task 4 (service), Task 8 (atom-type rename); the wizard atom dict shape is preserved, only `type` value changes.

Type consistency check:
- Source-type constant: `SOURCE_PLAN_TASK` (Tasks 3, 4, 6).
- Atom dict `type` value: `'plan_task'` (Tasks 4, 8).
- Task field rename: `source_plan_task` (Tasks 5, 6, 12, 13).
- Serializer field name on PlanTask: `estimated_billable_qty` (Tasks 1, 7, 9, 10).
- All model methods named `compute_amount` (Tasks 1, 4).

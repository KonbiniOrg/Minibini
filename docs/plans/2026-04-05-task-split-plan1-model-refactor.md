# Plan 1: Task/Bundle/Material Model Split — Foundation Refactor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dual-FK `Task`, `TaskBundle`, and `Material` models with type-enforced splits: `PlanTask`/`Task`, `PlanBundle` (only), `PlanMaterial`/`Material`. Mechanical refactor only — preserve all existing behavior, keep all existing tests green.

**Architecture:** Django abstract-model inheritance. `TaskBase` and `MaterialBase` are abstract (`Meta: abstract = True`); no base table. Each subclass gets its own table with fields copied in. Worksheet-side tasks move to `PlanTask` (new table `plan_tasks`), work-order-side tasks stay in the `tasks` table but shed their `est_worksheet` FK. Parallel split for Materials. `TaskBundle` becomes `PlanBundle` (worksheet-only). Migration is a single atomic data-move: split existing rows across the new/retained tables based on which container FK was populated.

**Tech Stack:** Django 5.2, MySQL, Python 3.12, DRF.

**Spec:** `docs/designs/2026-04-05-task-split-and-worksheet-to-workorder.md`

**Scope:** Model/schema refactor + mechanical updates to all call sites. **Out of scope in this plan:** workflow routing warnings, new `/api/plan-tasks/` resource, earmark relocation (signal stays on `estimate_accepted`, just points at `PlanMaterial`). Those are Plans 2 and 3.

**Refactor discipline note:** This is a preserve-behavior refactor, not a feature. The TDD cycle is inverted: the existing test suite is the spec, and the refactor is correct when all existing tests pass against the new models. New tests are added only for the handful of methods with changed signatures (notably `copy_from_worksheet`). Every phase ends with a "run the test suite" checkpoint.

---

## File Structure

**Files to modify:**

- `apps/jobs/models.py` — redefine `Task`, add `PlanTask`, replace `TaskBundle` with `PlanBundle`, add `TaskBase` abstract
- `apps/inventory/models.py` — redefine `Material`, add `PlanMaterial`, add `MaterialBase` abstract
- `apps/estimates/models.py` — remove `TaskTemplate.parent_template`, update `TaskTemplate.generate_task` to create `PlanTask` or `Task` based on container type; update `EstimateLineItem.task` FK target; update `EstWorksheet.create_new_version` to copy PlanTasks/PlanMaterials
- `apps/estimates/services.py` — update `EstimateGenerationService` to read `PlanTask`/`PlanMaterial`
- `apps/estimates/signals.py` — update earmark query path to walk PlanMaterial instead of Material
- `apps/jobs/services/__init__.py` — update `WorkOrderService.copy_from_worksheet`, `create_from_estimate`, `create_from_template`, `TaskService` methods
- `apps/jobs/services/blep_service.py` — simplify worksheet-task defensive check (Task now always has `work_order`)
- `apps/jobs/views.py` — update material and task views to use `PlanTask`/`PlanMaterial` for worksheet paths
- `apps/jobs/forms.py` — update `MaterialForm` to work against `PlanMaterial` (for the current HTML material views that live on worksheet tasks)
- `apps/inventory/services.py` — update `InventoryService.create_material`, `update_material`, `delete_material` to target appropriate model; update `get_earmark_preview` and `consume_material` query paths
- `apps/api/mixins.py` — split `TaskBundleMixin` into a worksheet version (with bundles) and a work-order version (tasks only, no bundles)
- `apps/api/tasks/serializers.py` — drop dual-container fields; `TaskDetailSerializer.get_work_order` becomes trivial
- `apps/api/tasks/views.py` — filter to `work_order__isnull=False` equivalents removed (no longer needed)
- `apps/api/estimates/views.py` and `apps/api/workorders/views.py` — update nested task/bundle actions to reference the right models
- `fixtures/*.json` — regenerate or hand-edit to split tasks/bundles/materials across new tables
- `tests/base.py` and individual test files — update setup helpers and any test that constructs a Task with `est_worksheet=...` (becomes `PlanTask`) or Material on a worksheet task (becomes `PlanMaterial`)

**Files to create:**

- `apps/jobs/migrations/NNNN_task_split.py` — atomic schema + data migration
- `apps/inventory/migrations/NNNN_material_split.py` — atomic schema + data migration for materials (may be combined with the above if FK ordering requires)
- `apps/estimates/migrations/NNNN_task_template_parent_removal.py` — drop `TaskTemplate.parent_template`, update `EstimateLineItem.task` FK target

---

## Phase 0: Baseline

### Task 0.1: Verify green baseline

**Files:** none

- [ ] **Step 1: Run the full test suite on main**

```bash
python manage.py test 2>&1 | tail -30
```

Expected: all tests pass. Note the total count.

- [ ] **Step 2: Capture test count to a throwaway file**

```bash
python manage.py test 2>&1 | tail -1 > /tmp/baseline_test_count.txt
cat /tmp/baseline_test_count.txt
```

This gives you a reference point for later — you should not lose tests during the refactor. Any test that becomes unrunnable or gets deleted needs an explicit justification.

- [ ] **Step 3: Confirm branch is `feature/worksheet-to-workorder`**

```bash
git branch --show-current
```

Expected: `feature/worksheet-to-workorder`

---

## Phase 1: Models

This phase rewrites the model classes. Nothing else is touched yet, so tests will fail after this phase — that is expected and will be repaired in Phase 2 onward.

### Task 1.1: Add `TaskBase` abstract class and rewrite `Task` / add `PlanTask`

**Files:**
- Modify: `apps/jobs/models.py:165-303` (current `Task`), `306-352` (current `TaskBundle`)

- [ ] **Step 1: Rewrite the Task/TaskBundle block in `apps/jobs/models.py`**

Replace the current `Task` class and `TaskBundle` class (lines 165-352) with the following. Leave the `WorkOrder` class above and the `Blep` class below untouched for now — `Blep.task` will be updated in a later task.

```python
class TaskBase(models.Model):
    """Abstract base for PlanTask (worksheet) and Task (work order)."""
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    sort_order = models.PositiveIntegerField(blank=True, null=True)
    units = models.CharField(max_length=50, default='none')
    rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    est_qty = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    accounting_category = models.ForeignKey(
        'core.AccountingCategory',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Type of line item this task produces when mapped directly"
    )

    class Meta:
        abstract = True

    def __str__(self):
        return self.name


class PlanTask(TaskBase):
    """Planning task on an EstWorksheet. No lifecycle, no hierarchy, no bleps."""
    plan_task_id = models.AutoField(primary_key=True)
    est_worksheet = models.ForeignKey(
        'estimates.EstWorksheet', on_delete=models.CASCADE, related_name='plan_tasks'
    )

    MAPPING_CHOICES = [
        ('direct', 'Direct'),
        ('bundle', 'Bundle'),
        ('exclude', 'Exclude'),
    ]
    mapping_strategy = models.CharField(max_length=20, choices=MAPPING_CHOICES, default='direct')
    bundle = models.ForeignKey(
        'PlanBundle',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='plan_tasks'
    )

    class Meta:
        db_table = 'plan_tasks'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.mapping_strategy == 'bundle' and not self.bundle:
            raise ValidationError("Bundled plan tasks must have a bundle assigned")
        if self.bundle and self.mapping_strategy != 'bundle':
            raise ValidationError("Plan tasks with a bundle must use 'bundle' mapping strategy")

    def save(self, *args, **kwargs):
        """Auto-assign sort_order at the worksheet level (tasks + bundles share the ordering space)."""
        from django.db import transaction
        if self.sort_order is None:
            with transaction.atomic():
                if self.bundle:
                    max_order = PlanTask.objects.filter(bundle=self.bundle).aggregate(
                        models.Max('sort_order')
                    )['sort_order__max'] or 0
                else:
                    max_task = PlanTask.objects.filter(
                        bundle__isnull=True, est_worksheet=self.est_worksheet
                    ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
                    max_bundle = PlanBundle.objects.filter(
                        est_worksheet=self.est_worksheet
                    ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
                    max_order = max(max_task, max_bundle)
                self.sort_order = max_order + 1
        self.full_clean()
        super().save(*args, **kwargs)


class Task(TaskBase):
    """Work task on a WorkOrder. Has lifecycle, hierarchy, bleps."""
    STATUS_PENDING = 'pending'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_BLOCKED = 'blocked'
    STATUS_COMPLETE = 'complete'
    STATUS_CANCELLED = 'cancelled'

    TASK_STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_BLOCKED, 'Blocked'),
        (STATUS_COMPLETE, 'Complete'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    VALID_TRANSITIONS = {
        STATUS_PENDING: [STATUS_IN_PROGRESS, STATUS_BLOCKED, STATUS_COMPLETE, STATUS_CANCELLED],
        STATUS_IN_PROGRESS: [STATUS_BLOCKED, STATUS_COMPLETE, STATUS_CANCELLED],
        STATUS_BLOCKED: [STATUS_IN_PROGRESS, STATUS_COMPLETE, STATUS_CANCELLED],
        STATUS_COMPLETE: [],
        STATUS_CANCELLED: [],
    }

    task_id = models.AutoField(primary_key=True)
    parent_task = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True, related_name='subtasks'
    )
    assignee = models.ForeignKey('core.User', on_delete=models.SET_NULL, null=True, blank=True)
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name='tasks')
    status = models.CharField(max_length=20, choices=TASK_STATUS_CHOICES, default=STATUS_PENDING)
    worker_queue = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Position in assignee's work queue on the board"
    )

    class Meta:
        db_table = 'tasks'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.pk:
            old_status = Task.objects.get(pk=self.pk).status
            if old_status != self.status:
                allowed = self.VALID_TRANSITIONS.get(old_status, [])
                if self.status not in allowed:
                    raise ValidationError(
                        {'status': f"Cannot transition from '{old_status}' to '{self.status}'."}
                    )

    def save(self, *args, **kwargs):
        from django.db import transaction
        if self.sort_order is None:
            with transaction.atomic():
                max_order = Task.objects.filter(
                    work_order=self.work_order
                ).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
                self.sort_order = max_order + 1
        self.full_clean()
        super().save(*args, **kwargs)


class PlanBundle(models.Model):
    """Instance-level grouping of PlanTasks within a worksheet.

    Parallel to TemplateBundle, but lives on the worksheet instance.
    PlanTasks with mapping_strategy='bundle' point to a PlanBundle, and
    the bundle becomes a single line item on the estimate.
    """
    plan_bundle_id = models.AutoField(primary_key=True)
    est_worksheet = models.ForeignKey(
        'estimates.EstWorksheet', on_delete=models.CASCADE, related_name='plan_bundles'
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    accounting_category = models.ForeignKey(
        'core.AccountingCategory',
        on_delete=models.PROTECT
    )
    sort_order = models.IntegerField(default=0)
    source_template_bundle = models.ForeignKey(
        'estimates.TemplateBundle', on_delete=models.SET_NULL,
        null=True, blank=True
    )

    class Meta:
        db_table = 'plan_bundles'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return f"{self.est_worksheet} - {self.name}"
```

- [ ] **Step 2: Update `Blep.task` target (still in `apps/jobs/models.py`)**

`Blep.task` already references `Task` by class object. After the rewrite above, `Task` means the new work-order-only Task, which is correct. Verify the line reads:

```python
task = models.ForeignKey(Task, on_delete=models.PROTECT)
```

If it reads differently, update to the above. No logic change needed — `Blep` is work-side only by runtime enforcement today and that enforcement becomes type-level after this change.

- [ ] **Step 3: Sanity-check by running `makemigrations --dry-run`**

```bash
python manage.py makemigrations --dry-run apps.jobs
```

Expected: Django detects "Create model PlanTask, Create model PlanBundle, Remove field est_worksheet on Task, Remove field mapping_strategy on Task, Remove field bundle on Task, Delete model TaskBundle" (or similar). Do not create the migration yet — that happens in Task 1.4 after all model files are updated.

### Task 1.2: Add `MaterialBase` abstract and split `Material`

**Files:**
- Modify: `apps/inventory/models.py:96-139` (current `Material`)

- [ ] **Step 1: Rewrite the Material class in `apps/inventory/models.py`**

Replace the existing `Material` class (lines 96-139) with:

```python
class MaterialBase(models.Model):
    """Abstract base for PlanMaterial (planning) and Material (actual)."""
    description = models.TextField(blank=True, default='')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    sell_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    price_list_item = models.ForeignKey(
        'PriceListItem', on_delete=models.PROTECT,
        null=True, blank=True,
    )
    accounting_category = models.ForeignKey(
        'core.AccountingCategory', on_delete=models.PROTECT,
        null=True, blank=True,
    )
    line_item_type = models.ForeignKey(
        'core.LineItemType', on_delete=models.PROTECT,
        null=True, blank=True,  # nullable at the DB level for migration; runtime enforces
    )

    class Meta:
        abstract = True

    @property
    def total_cost(self):
        return self.quantity * self.unit_cost

    @property
    def total_sell(self):
        return self.quantity * self.sell_price

    def _populate_from_pli(self):
        """Copy description/unit_cost/sell_price from linked PriceListItem if not already set."""
        if self.price_list_item:
            if not self.description:
                self.description = self.price_list_item.description
            if self.unit_cost == Decimal('0.00'):
                self.unit_cost = self.price_list_item.purchase_price
            if self.sell_price == Decimal('0.00'):
                self.sell_price = self.price_list_item.selling_price


class PlanMaterial(MaterialBase):
    """Planning material on a PlanTask. No inventory side effects."""
    plan_material_id = models.AutoField(primary_key=True)
    plan_task = models.ForeignKey(
        'jobs.PlanTask', on_delete=models.CASCADE, related_name='plan_materials'
    )

    class Meta:
        db_table = 'plan_materials'

    def save(self, *args, **kwargs):
        self._populate_from_pli()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.description} ({self.quantity})"


class Material(MaterialBase):
    """Actual material on a Task (work order). Participates in earmark/QOH flows."""
    material_id = models.AutoField(primary_key=True)
    task = models.ForeignKey(
        'jobs.Task', on_delete=models.CASCADE, related_name='materials'
    )

    class Meta:
        db_table = 'materials'

    def save(self, *args, **kwargs):
        self._populate_from_pli()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.description} ({self.quantity})"
```

**Note on `line_item_type`:** the spec puts `line_item_type` on `MaterialBase`. The current `Material` model already has this field (added per the 2026-03-06 lifecycle doc Phase 1). If the field doesn't exist yet on the current `Material` model, add it to `MaterialBase` above and the migration in Task 1.4 will add the column. If it does exist, `MaterialBase` subsumes it. Verify by grepping `apps/inventory/models.py` for `line_item_type` before running the migration.

- [ ] **Step 2: If `LineItemType` import is missing at the top of the file, add it**

Check the top of `apps/inventory/models.py`. If `LineItemType` is referenced only as a string FK target (`'core.LineItemType'`), no import is needed. If the current Material class imports it, leave that import in place.

### Task 1.3: Remove `TaskTemplate.parent_template` and update `generate_task`

**Files:**
- Modify: `apps/estimates/models.py:474` (parent_template field), `486-518` (generate_task method), `521+` (EstimateLineItem.task)

- [ ] **Step 1: Remove `parent_template` field**

In `apps/estimates/models.py`, delete this line (currently line 474):

```python
parent_template = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='child_templates')
```

- [ ] **Step 2: Rewrite `TaskTemplate.generate_task`**

Replace the method (currently lines 486-518) with:

```python
def generate_task(self, container, est_qty, bundle_identifier=None, product_instance=None,
                   assignee=None, mapping_strategy='direct', bundle=None, sort_order=None):
    """Generate a PlanTask or Task from this template with specified quantity and mapping config.

    The return type depends on the container: EstWorksheet → PlanTask, WorkOrder → Task.
    """
    from apps.jobs.models import WorkOrder, Task, PlanTask

    if isinstance(container, WorkOrder):
        return Task.objects.create(
            work_order=container,
            name=self.template_name,
            description=self.description,
            units=self.units,
            rate=self.rate,
            est_qty=est_qty,
            accounting_category=self.accounting_category,
            assignee=assignee,
            sort_order=sort_order,
        )
    else:  # EstWorksheet
        return PlanTask.objects.create(
            est_worksheet=container,
            name=self.template_name,
            description=self.description,
            units=self.units,
            rate=self.rate,
            est_qty=est_qty,
            accounting_category=self.accounting_category,
            mapping_strategy=mapping_strategy,
            bundle=bundle,
            sort_order=sort_order,
        )
```

Notes:
- The recursive `child_templates` loop is deleted. Templates no longer have hierarchy.
- `assignee`, `bundle_identifier`, `product_instance` are accepted for signature compatibility but `bundle_identifier` and `product_instance` are now unused (they were only meaningful for bundled-recursive template generation). The parameters are kept in the signature to avoid breaking callers; they simply have no effect.

- [ ] **Step 3: Update `EstimateLineItem.task` FK target**

Find the `EstimateLineItem` class (around line 521). In `BaseLineItem` (likely `apps/core/models.py`, but verify), the `task` field targets `'jobs.Task'`. Change it to `'jobs.PlanTask'`.

```bash
grep -rn "task = models.ForeignKey" apps/core/models.py apps/estimates/models.py apps/invoicing/models.py apps/purchasing/models.py
```

For each line item model, determine whether `task` should retarget:
- `EstimateLineItem`: **retarget to `'jobs.PlanTask'`** (estimate line items are generated from worksheets).
- `InvoiceLineItem`: retarget to `'jobs.Task'` (invoices are generated from work orders). If the current code points at `Task` and means the WO-side, it already correctly targets the new `Task` after Phase 1, but verify the FK is not nullable or shared.
- `PurchaseOrderLineItem`, `BillLineItem`: these target `Task` for "which task is this material for." Retarget to `'jobs.Task'` (WO-side) since POs are issued against work that's happening.

Update each FK target accordingly. If the `task` FK lives on `BaseLineItem` (abstract parent) rather than each subclass, the FK cannot target two different models — in that case, pull `task` out of `BaseLineItem` and into each concrete subclass with its correct target. Check this before editing.

### Task 1.4: Generate and hand-author the migrations

**Files:**
- Create: `apps/jobs/migrations/NNNN_task_split.py`
- Create: `apps/inventory/migrations/NNNN_material_split.py`
- Create: `apps/estimates/migrations/NNNN_task_template_and_lineitem_fk.py`

- [ ] **Step 1: Generate migrations via makemigrations**

```bash
python manage.py makemigrations apps.jobs apps.inventory apps.estimates
```

Django will generate schema-level migrations for all three apps. Inspect each one. They will contain the auto-detected operations (create tables, remove fields, alter FKs) but **not** the data-move logic. That has to be hand-authored.

- [ ] **Step 2: Hand-author the jobs data migration**

Open the newly generated `apps/jobs/migrations/NNNN_....py`. After the auto-generated `CreateModel` operations for `PlanTask` and `PlanBundle`, and before the `RemoveField`/`DeleteModel` operations that drop the old `est_worksheet` FK on Task and delete the old `TaskBundle`, insert a `RunPython` operation that copies data.

Add at the top of the file:

```python
def split_tasks_and_bundles(apps, schema_editor):
    Task = apps.get_model('jobs', 'Task')
    PlanTask = apps.get_model('jobs', 'PlanTask')
    TaskBundle = apps.get_model('jobs', 'TaskBundle')
    PlanBundle = apps.get_model('jobs', 'PlanBundle')

    # Step 1: copy worksheet-side TaskBundles into PlanBundle, keep id mapping
    bundle_id_map = {}
    for tb in TaskBundle.objects.filter(est_worksheet__isnull=False):
        pb = PlanBundle.objects.create(
            est_worksheet_id=tb.est_worksheet_id,
            name=tb.name,
            description=tb.description,
            accounting_category_id=tb.accounting_category_id,
            sort_order=tb.sort_order,
            source_template_bundle_id=tb.source_template_bundle_id,
        )
        bundle_id_map[tb.pk] = pb.pk

    # Step 2: copy worksheet-side Tasks into PlanTask
    for t in Task.objects.filter(est_worksheet__isnull=False):
        PlanTask.objects.create(
            est_worksheet_id=t.est_worksheet_id,
            name=t.name,
            description=t.description,
            sort_order=t.sort_order,
            units=t.units,
            rate=t.rate,
            est_qty=t.est_qty,
            accounting_category_id=t.accounting_category_id,
            mapping_strategy=t.mapping_strategy,
            bundle_id=bundle_id_map.get(t.bundle_id) if t.bundle_id else None,
        )

    # Step 3: delete worksheet-side Task rows (they are now in plan_tasks)
    Task.objects.filter(est_worksheet__isnull=False).delete()

    # Step 4: delete work-order-side TaskBundle rows (RealBundle does not exist)
    TaskBundle.objects.filter(work_order__isnull=False).delete()


def reverse_split_tasks_and_bundles(apps, schema_editor):
    # Reversing this migration is not supported — data is destructured.
    raise RuntimeError("Task/Bundle split cannot be reversed automatically.")
```

Then, in the `operations` list, insert the `RunPython` call **after** the `CreateModel` ops for `PlanTask` and `PlanBundle`, and **before** any `RemoveField` or `DeleteModel` that drops the old columns/tables:

```python
operations = [
    # ... auto-generated CreateModel for PlanBundle
    # ... auto-generated CreateModel for PlanTask
    migrations.RunPython(split_tasks_and_bundles, reverse_split_tasks_and_bundles),
    # ... auto-generated RemoveField(Task, 'est_worksheet')
    # ... auto-generated RemoveField(Task, 'mapping_strategy')
    # ... auto-generated RemoveField(Task, 'bundle')
    # ... auto-generated DeleteModel(TaskBundle)
]
```

**Critical:** Django's autodetector may emit the operations in a different order than this. If `DeleteModel(TaskBundle)` comes before the `RunPython`, the data migration will fail because `TaskBundle` will no longer exist. Reorder operations manually if needed — the ordering constraint is "create new tables → RunPython data move → drop old columns/tables."

- [ ] **Step 3: Hand-author the inventory data migration**

Open `apps/inventory/migrations/NNNN_material_split.py`. Add the data-move function:

```python
def split_materials(apps, schema_editor):
    Material = apps.get_model('inventory', 'Material')
    PlanMaterial = apps.get_model('inventory', 'PlanMaterial')
    Task = apps.get_model('jobs', 'Task')  # still the old shape at this point
    PlanTask = apps.get_model('jobs', 'PlanTask')

    # At the point this migration runs, jobs' task split has already moved worksheet tasks
    # into PlanTask. But existing Material.task rows still point at the old Task.task_id
    # values that are now in plan_tasks. We need to find the matching PlanTask by the
    # original task_id that was used as the source during the jobs split.
    #
    # Strategy: we cannot reliably match after the fact. This migration must run within
    # the SAME migration cycle, relying on the dependency on the jobs migration, AND
    # we must seed a mapping table or inspect which Materials pointed at now-deleted Task rows.
    #
    # Simpler approach: make the jobs migration emit a mapping as it runs, stored in a
    # temporary table or settings dict. See Step 4 below for the combined approach.
    pass
```

**This is non-trivial.** Splitting Materials across two tables requires knowing which original `Task` each `Material` referenced, and whether that Task is now in `plan_tasks` or `tasks`. The cleanest solution is to combine the data moves into a single migration or to have the jobs migration expose an id mapping.

- [ ] **Step 4: Combine into a single atomic migration**

Rather than fight with cross-app migration state, put all the data moves into one migration in `apps/jobs` (the topologically first app in the dependency chain after estimates). This migration depends on all three apps' latest prior migrations and does the full split atomically.

Create `apps/jobs/migrations/NNNN_task_bundle_material_split.py` by hand (or generate a blank one with `python manage.py makemigrations --empty apps.jobs`). Its `operations` list:

```python
from django.db import migrations, models


def split_all(apps, schema_editor):
    Task = apps.get_model('jobs', 'Task')
    PlanTask = apps.get_model('jobs', 'PlanTask')
    TaskBundle = apps.get_model('jobs', 'TaskBundle')
    PlanBundle = apps.get_model('jobs', 'PlanBundle')
    Material = apps.get_model('inventory', 'Material')
    PlanMaterial = apps.get_model('inventory', 'PlanMaterial')

    # --- Bundles ---
    bundle_id_map = {}
    for tb in TaskBundle.objects.filter(est_worksheet__isnull=False):
        pb = PlanBundle.objects.create(
            est_worksheet_id=tb.est_worksheet_id,
            name=tb.name,
            description=tb.description,
            accounting_category_id=tb.accounting_category_id,
            sort_order=tb.sort_order,
            source_template_bundle_id=tb.source_template_bundle_id,
        )
        bundle_id_map[tb.pk] = pb.pk

    # --- Tasks ---
    task_id_map = {}  # old Task.task_id (worksheet-side) -> new PlanTask.plan_task_id
    for t in Task.objects.filter(est_worksheet__isnull=False):
        pt = PlanTask.objects.create(
            est_worksheet_id=t.est_worksheet_id,
            name=t.name,
            description=t.description,
            sort_order=t.sort_order,
            units=t.units,
            rate=t.rate,
            est_qty=t.est_qty,
            accounting_category_id=t.accounting_category_id,
            mapping_strategy=t.mapping_strategy,
            bundle_id=bundle_id_map.get(t.bundle_id) if t.bundle_id else None,
        )
        task_id_map[t.pk] = pt.pk

    # --- Materials ---
    for m in Material.objects.all():
        if m.task_id in task_id_map:
            # Material on a worksheet-side task → becomes PlanMaterial
            PlanMaterial.objects.create(
                plan_task_id=task_id_map[m.task_id],
                description=m.description,
                quantity=m.quantity,
                unit_cost=m.unit_cost,
                sell_price=m.sell_price,
                price_list_item_id=m.price_list_item_id,
                accounting_category_id=m.accounting_category_id,
                line_item_type_id=getattr(m, 'line_item_type_id', None),
            )
            m.delete()
        # Else: Material stays in place (already targets a WO-side Task which is
        # retained by the FK-drop phase below).

    # --- EstimateLineItem.task retarget ---
    # The task FK on EstimateLineItem currently points at old Task rows. After this
    # migration, those rows are gone for worksheet-side, so we need to rewrite the FKs.
    EstimateLineItem = apps.get_model('estimates', 'EstimateLineItem')
    for li in EstimateLineItem.objects.filter(task__isnull=False):
        if li.task_id in task_id_map:
            # Retarget to PlanTask. The FK column name doesn't change — we just update the value.
            li.task_id = task_id_map[li.task_id]
            li.save(update_fields=['task_id'])
        # Else: already points at a WO-side task; leave alone, but note this is unusual.

    # --- Cleanup: delete worksheet-side Task and work-order-side TaskBundle rows ---
    Task.objects.filter(est_worksheet__isnull=False).delete()
    TaskBundle.objects.filter(work_order__isnull=False).delete()


def reverse_split_all(apps, schema_editor):
    raise RuntimeError("Task/Bundle/Material split cannot be reversed automatically.")


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', 'PREVIOUS_JOBS_MIGRATION'),
        ('inventory', 'PREVIOUS_INVENTORY_MIGRATION'),
        ('estimates', 'PREVIOUS_ESTIMATES_MIGRATION'),
    ]

    operations = [
        # CreateModel for PlanTask
        # CreateModel for PlanBundle
        # CreateModel for PlanMaterial
        # RunPython(split_all, reverse_split_all)
        # AlterField for EstimateLineItem.task target (jobs.Task -> jobs.PlanTask)
        # RemoveField Task.est_worksheet
        # RemoveField Task.mapping_strategy
        # RemoveField Task.bundle
        # DeleteModel TaskBundle
        # AlterField on EstimateLineItem.task FK target
    ]
```

Fill in the `dependencies` with the actual latest migration names from each app (check via `ls apps/*/migrations/`). Fill in the `operations` by copying the auto-generated operations from the per-app migrations Django generated in Step 1, in the order commented above. **Delete the per-app migrations generated in Step 1** — we are using this single atomic migration instead.

- [ ] **Step 5: The user will apply the migration**

Per CLAUDE.md: never run `python manage.py migrate`. Stop here and ask the user to apply the migration manually. Before they do, run:

```bash
python manage.py makemigrations --check --dry-run
```

Expected: no pending migrations (meaning the combined one matches the model state). If Django reports pending changes, something is missing from the atomic migration's operations list.

### Task 1.5: Phase 1 checkpoint

- [ ] **Step 1: Verify models import cleanly**

```bash
python -c "from apps.jobs.models import PlanTask, Task, PlanBundle; from apps.inventory.models import PlanMaterial, Material; print('ok')"
```

Expected: `ok`. Any ImportError means a model refactor step was missed.

- [ ] **Step 2: Commit the model + migration changes**

```bash
git add apps/jobs/models.py apps/inventory/models.py apps/estimates/models.py apps/jobs/migrations/ apps/inventory/migrations/ apps/estimates/migrations/
git commit -m "$(cat <<'EOF'
refactor: split Task/Bundle/Material models (models + migration)

Replace dual-FK Task/TaskBundle/Material with type-enforced splits:
- TaskBase (abstract) + PlanTask (worksheet) + Task (work order)
- PlanBundle only (RealBundle dropped)
- MaterialBase (abstract) + PlanMaterial (on PlanTask) + Material (on Task)

Includes a single atomic data migration that moves worksheet-side rows
into the new plan_* tables, drops work-order-side TaskBundle rows, and
retargets EstimateLineItem.task to PlanTask.

Code call sites will be updated in subsequent commits; tests are
expected to fail until that work lands.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

Tests are expected to fail at this point. Proceed to Phase 2.

---

## Phase 2: Service layer

Every service that references the old `Task.est_worksheet`, `TaskBundle.work_order`, or `Material` on a worksheet task needs updating. Work outward from the core models.

### Task 2.1: Update `WorkOrderService.copy_from_worksheet`

**Files:**
- Modify: `apps/jobs/services/__init__.py:124-177`

- [ ] **Step 1: Replace the method body with the new PlanTask/PlanMaterial-aware version**

```python
@staticmethod
def copy_from_worksheet(work_order_pk, worksheet_pk):
    """Copy a worksheet's PlanTasks (with their PlanMaterials) to a work order.

    Per spec 2026-04-05-task-split-and-worksheet-to-workorder.md:
    - No bundle copy (RealBundle does not exist).
    - No parent_task copy (hierarchy emerges during work).
    - No mapping_strategy copy (irrelevant on work order).
    - PlanMaterials become Materials with price_list_item preserved.
    """
    from apps.estimates.models import EstWorksheet
    from apps.jobs.models import PlanTask, Task
    from apps.inventory.models import Material

    try:
        wo = WorkOrder.objects.get(pk=work_order_pk)
    except WorkOrder.DoesNotExist:
        raise NotFoundError(f'WorkOrder {work_order_pk} not found')
    try:
        ws = EstWorksheet.objects.get(pk=worksheet_pk)
    except EstWorksheet.DoesNotExist:
        raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')

    for plan_task in PlanTask.objects.filter(
        est_worksheet=ws
    ).prefetch_related('plan_materials'):
        new_task = Task.objects.create(
            work_order=wo,
            name=plan_task.name,
            description=plan_task.description,
            units=plan_task.units,
            rate=plan_task.rate,
            est_qty=plan_task.est_qty,
            accounting_category=plan_task.accounting_category,
            sort_order=plan_task.sort_order,
        )
        for pm in plan_task.plan_materials.all():
            Material.objects.create(
                task=new_task,
                description=pm.description,
                quantity=pm.quantity,
                unit_cost=pm.unit_cost,
                sell_price=pm.sell_price,
                price_list_item=pm.price_list_item,
                accounting_category=pm.accounting_category,
                line_item_type=pm.line_item_type,
            )
```

### Task 2.2: Update `TaskService._copy_worksheet_tasks`

**Files:**
- Modify: `apps/jobs/services/__init__.py:203-235`

- [ ] **Step 1: Rewrite `_copy_worksheet_tasks` to copy a PlanTask (from an EstimateLineItem) into a Task**

```python
@staticmethod
def _copy_worksheet_tasks(line_item, work_order):
    """Copy the PlanTask that contributed to this EstimateLineItem into a Task on the WO.

    Note: after the spec 2026-04-05 model split, this function copies exactly one
    PlanTask to one Task. The prior "multi-task with parent relationships" logic was
    dead code (the source list was always a single element) and is removed.
    """
    plan_task = line_item.task  # now a PlanTask FK
    new_task = Task.objects.create(
        work_order=work_order,
        name=plan_task.name,
        description=plan_task.description,
        units=plan_task.units,
        rate=plan_task.rate,
        est_qty=plan_task.est_qty,
        accounting_category=plan_task.accounting_category,
        # assignee and status use defaults; parent_task is None
    )
    return [new_task]
```

### Task 2.3: Audit remaining `TaskService` / `WorkOrderService` methods

**Files:**
- Modify: `apps/jobs/services/__init__.py` (remainder)

- [ ] **Step 1: Find every remaining reference to `est_worksheet` in the file**

```bash
grep -n "est_worksheet\|TaskBundle" apps/jobs/services/__init__.py
```

- [ ] **Step 2: Update each reference**

For each line returned:
- `Task.objects.filter(est_worksheet=...)` → `PlanTask.objects.filter(est_worksheet=...)` (if the intent was worksheet tasks) or delete the branch (if the intent was "handle both containers")
- `TaskBundle` references → `PlanBundle` if the context is a worksheet; delete the branch if the context is a work order
- Any conditional that switches on `if task.work_order` / `if task.est_worksheet` collapses because PlanTask and Task are now distinct types — whichever branch is unreachable for the given type should be removed.

Common sites: `TaskService.reorder_tasks` has a container branch that can simplify since the caller knows the type. Also check `TaskLifecycleService` if it lives in this file or a sibling.

### Task 2.4: Update `TaskLifecycleService`

**Files:**
- Modify: `apps/jobs/services/__init__.py` (look for `class TaskLifecycleService`)

- [ ] **Step 1: Simplify the `if not task.work_order` defensive checks**

After the split, anywhere `TaskLifecycleService` receives a task argument, that task is a `Task` (work-order side) by type. The `if not task.work_order` checks at lines ~363, ~403, ~452-454 are unreachable and should be removed. Replace each with a comment if you want a paper trail:

```python
# Post-split: task is always a Task (work-order side); no container check needed.
```

Or just delete the check and the associated error raise.

### Task 2.5: Update `BlepService`

**Files:**
- Modify: `apps/jobs/services/blep_service.py:101`

- [ ] **Step 1: Remove the runtime worksheet-task check**

Find the check that raises "Cannot create blep: task must belong to a WorkOrder, not a worksheet." It becomes unreachable after the split (PlanTasks cannot be passed in because `Blep.task` now FKs specifically to `Task`). Delete the check.

### Task 2.6: Update `InventoryService`

**Files:**
- Modify: `apps/inventory/services.py`

- [ ] **Step 1: Simplify `consume_material`'s container branching**

Lines 73-75 currently read:

```python
job = material.task.est_worksheet.job if material.task.est_worksheet else (
    material.task.work_order.job if material.task.work_order else None
)
```

After the split, `material.task` is always a `Task` with a `work_order`. Replace with:

```python
job = material.task.work_order.job
```

- [ ] **Step 2: Update `get_earmark_preview` query path**

Line ~175 reads `task__est_worksheet__job=job`. Since this plan keeps the `estimate_accepted` signal firing and still earmarks from the worksheet side, the query needs to walk through `PlanMaterial` instead. Replace:

```python
materials = Material.objects.filter(
    task__est_worksheet__job=job,
    price_list_item__is_inventoried=True,
).values('price_list_item').annotate(
    total_qty=Sum('quantity'),
)
```

with:

```python
from apps.inventory.models import PlanMaterial
materials = PlanMaterial.objects.filter(
    plan_task__est_worksheet__job=job,
    price_list_item__is_inventoried=True,
).values('price_list_item').annotate(
    total_qty=Sum('quantity'),
)
```

Note: Plan 3 will rewrite this entirely to query the WO side. This plan just keeps the existing behavior working.

- [ ] **Step 3: Update `create_material`/`update_material`/`delete_material`**

Lines 128-162. These currently take a `task_pk` and look up a `Task`. They are called from the HTML material views, which today operate on worksheet tasks. After the split, these should target `PlanMaterial` and `PlanTask` (because that's where the HTML views live — on worksheet tasks).

Rename the methods for clarity:

```python
@staticmethod
def create_plan_material(plan_task_pk, **kwargs):
    """Create a new PlanMaterial on a PlanTask."""
    from apps.core.services import NotFoundError
    from apps.jobs.models import PlanTask
    try:
        plan_task = PlanTask.objects.get(pk=plan_task_pk)
    except PlanTask.DoesNotExist:
        raise NotFoundError(f'PlanTask {plan_task_pk} not found')
    mat = PlanMaterial(plan_task=plan_task, **kwargs)
    mat.save()
    return mat

@staticmethod
def update_plan_material(pk, **kwargs):
    from apps.core.services import NotFoundError
    try:
        mat = PlanMaterial.objects.get(pk=pk)
    except PlanMaterial.DoesNotExist:
        raise NotFoundError(f'PlanMaterial {pk} not found')
    for field, value in kwargs.items():
        setattr(mat, field, value)
    mat.save()
    return mat

@staticmethod
def delete_plan_material(pk):
    from apps.core.services import NotFoundError
    try:
        mat = PlanMaterial.objects.get(pk=pk)
    except PlanMaterial.DoesNotExist:
        raise NotFoundError(f'PlanMaterial {pk} not found')
    mat.delete()
```

Add a corresponding import: `from apps.inventory.models import PlanMaterial` at the top of the file.

Leave the old `create_material`/`update_material`/`delete_material` names as thin wrappers that call the new methods, **only if** call sites still use the old names. Otherwise delete them. After updating views in Phase 3, remove the wrappers.

### Task 2.7: Update `EstimateGenerationService`

**Files:**
- Modify: `apps/estimates/services.py:610-671` (generate_estimate_from_worksheet)

- [ ] **Step 1: Replace `worksheet.task_set` with `worksheet.plan_tasks`**

Line 619 currently reads:

```python
tasks = worksheet.task_set.select_related('bundle').prefetch_related('materials').all()
```

Replace with:

```python
tasks = worksheet.plan_tasks.select_related('bundle').prefetch_related('plan_materials').all()
```

- [ ] **Step 2: Rename the local variable for clarity**

Rename `tasks` → `plan_tasks` throughout the method. Anywhere the method accesses `task.materials`, change to `task.plan_materials`. Anywhere it accesses `task.bundle`, the access stays the same (PlanTask also has a `bundle` attribute pointing at `PlanBundle`).

- [ ] **Step 3: Grep for other references to `.task_set` on EstWorksheet**

```bash
grep -rn "worksheet.task_set\|est_worksheet.task_set\|\.task_set" apps/estimates/ apps/jobs/ apps/api/
```

Replace every hit. The new related_name is `plan_tasks`.

### Task 2.8: Update `EstWorksheet.create_new_version`

**Files:**
- Modify: `apps/estimates/models.py` (around the `create_new_version` method)

- [ ] **Step 1: Find the method**

```bash
grep -n "def create_new_version" apps/estimates/models.py
```

- [ ] **Step 2: Update material copy to use PlanMaterial**

The method currently iterates tasks and copies materials. After the split, iterate `plan_tasks` and copy `plan_materials`. The task copies become `PlanTask` copies (because both the source and destination are worksheets). Bundles copy as `PlanBundle`.

### Task 2.9: Phase 2 checkpoint

- [ ] **Step 1: Run the test suite**

```bash
python manage.py test 2>&1 | tail -50
```

Expected: many failures, but the failures should be concentrated in views, API layers, and tests that directly construct old-style Tasks. Model and service layer import errors should be gone. If you see `AttributeError: 'Task' object has no attribute 'est_worksheet'`, that's a call site not yet updated — proceed to Phase 3.

- [ ] **Step 2: Commit service layer updates**

```bash
git add apps/jobs/services/ apps/inventory/services.py apps/estimates/services.py apps/estimates/models.py
git commit -m "$(cat <<'EOF'
refactor: update services for Task/Bundle/Material split

Mechanical updates to WorkOrderService, TaskService, TaskLifecycleService,
BlepService, InventoryService, EstimateGenerationService, and
EstWorksheet.create_new_version to reference PlanTask/PlanBundle/PlanMaterial
where the worksheet side is meant, and retain Task/Material for work-order
side. copy_from_worksheet rewritten to match the spec.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3: API layer

### Task 3.1: Update `TaskBundleMixin`

**Files:**
- Modify: `apps/api/mixins.py:184-290`

- [ ] **Step 1: Read the current mixin**

```bash
sed -n '184,290p' apps/api/mixins.py
```

- [ ] **Step 2: Split into two mixins**

The current `TaskBundleMixin` is parameterized by `container_field`. Split into:

- `PlanTaskBundleMixin` — used by `EstWorksheetViewSet`. Handles `plan_tasks` and `plan_bundles` nested endpoints. Works against `PlanTask` and `PlanBundle` models.
- `WorkOrderTaskMixin` — used by `WorkOrderViewSet`. Handles `tasks` nested endpoint only (no bundles). Works against `Task` model.

Write both mixins from scratch based on the current mixin's behavior. Each mixin is simpler than the original because the container type is fixed.

Keep the old `TaskBundleMixin` name as an alias to `PlanTaskBundleMixin` if there's any risk of stale imports; better, grep for uses and update all call sites:

```bash
grep -rn "TaskBundleMixin" apps/api/
```

### Task 3.2: Update worksheet viewset to use `PlanTaskBundleMixin`

**Files:**
- Modify: `apps/api/estimates/views.py` (EstWorksheetViewSet)

- [ ] **Step 1: Swap the mixin**

Change `TaskBundleMixin` to `PlanTaskBundleMixin` in the class bases of `EstWorksheetViewSet`. Update any `container_field = 'est_worksheet'` class attribute — the new mixin doesn't need it.

### Task 3.3: Update work order viewset to use `WorkOrderTaskMixin`

**Files:**
- Modify: `apps/api/workorders/views.py` (or wherever `WorkOrderViewSet` lives)

- [ ] **Step 1: Swap the mixin**

Change `TaskBundleMixin` to `WorkOrderTaskMixin`. Remove any references to bundles on the WO side (since `RealBundle` is deleted).

### Task 3.4: Update `TaskSerializer` and `TaskDetailSerializer`

**Files:**
- Modify: `apps/api/tasks/serializers.py:7-40`

- [ ] **Step 1: Read the current serializers**

```bash
cat apps/api/tasks/serializers.py
```

- [ ] **Step 2: Remove polymorphic `get_work_order`**

The current `TaskDetailSerializer.get_work_order` (lines 27-40) returns None when the task is worksheet-side. After the split, `Task` always has a `work_order`. The method becomes a simple attribute access — either use `WorkOrderSerializer(source='work_order')` or remove the method and expose `work_order` directly as a nested serializer.

- [ ] **Step 3: Remove any `est_worksheet`-related fields from `TaskSerializer`/`TaskDetailSerializer`**

These now belong on a new `PlanTaskSerializer` (created in Plan 2). For Plan 1, just strip the worksheet-side fields — no new serializer needed yet because no new API endpoint exists.

### Task 3.5: Update `TaskViewSet` queryset

**Files:**
- Modify: `apps/api/tasks/views.py`

- [ ] **Step 1: Remove any `est_worksheet` filters**

The current viewset may filter on `work_order__isnull=False` or similar. After the split, `TaskViewSet`'s queryset is just `Task.objects.all()` (filtered by permissions and pagination as appropriate).

### Task 3.6: Phase 3 checkpoint

- [ ] **Step 1: Run the test suite**

```bash
python manage.py test 2>&1 | tail -50
```

Most API-layer failures should be resolved. Remaining failures should be in HTML views, signals, tests, and fixtures.

- [ ] **Step 2: Commit**

```bash
git add apps/api/
git commit -m "$(cat <<'EOF'
refactor: update API mixins/serializers/views for model split

Split TaskBundleMixin into PlanTaskBundleMixin (worksheets) and
WorkOrderTaskMixin (work orders, tasks only). Simplify
TaskDetailSerializer now that Task always has a work_order.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4: HTML views, forms, signals

### Task 4.1: Update HTML material views

**Files:**
- Modify: `apps/jobs/views.py:402-470`

- [ ] **Step 1: Update `material_add`, `material_edit`, `material_delete`**

These views currently operate on `Task` + `Material` where the task is worksheet-side. After the split, they operate on `PlanTask` + `PlanMaterial`.

For `material_add`:

```python
@login_required
@permission_required('core.can_manage_jobs', raise_exception=True)
def material_add(request, task_id):
    """Add a PlanMaterial to a PlanTask. Only allowed on draft worksheets."""
    plan_task = get_object_or_404(PlanTask, plan_task_id=task_id)
    worksheet = plan_task.est_worksheet
    if worksheet.status != EstWorksheet.STATUS_DRAFT:
        messages.error(request, 'Cannot add materials to tasks on a non-draft worksheet.')
        return redirect('jobs:task_detail', task_id=task_id)

    if request.method == 'POST':
        pm_instance = PlanMaterial(plan_task=plan_task)
        form = MaterialForm(request.POST, instance=pm_instance)
        if form.is_valid():
            mat = InventoryService.create_plan_material(plan_task.pk, **form.cleaned_data)
            messages.success(request, f'Material "{mat.description}" added.')
            return redirect('jobs:task_detail', task_id=task_id)
    else:
        form = MaterialForm()

    return render(request, 'jobs/material_add.html', {
        'form': form,
        'task': plan_task,
    })
```

Apply the same pattern to `material_edit` and `material_delete`. Update the import at the top of `views.py`:

```python
from apps.jobs.models import PlanTask, Task  # add PlanTask
from apps.inventory.models import PlanMaterial  # if referenced directly
```

- [ ] **Step 2: Update the `task_detail` view**

If `task_detail` currently looks up a `Task` by `task_id`, it needs to handle both `Task` and `PlanTask`. Look at how it's routed. Options:

- Split into two URLs/views: `plan_task_detail` and `task_detail`.
- Or, because the HTML side is legacy and being replaced by the SPA, keep a single `task_detail` that tries `PlanTask` first then falls back to `Task`.

The minimal-change choice is the fallback. Add near the top of `task_detail`:

```python
def task_detail(request, task_id):
    try:
        task = PlanTask.objects.get(pk=task_id)
        is_plan = True
    except PlanTask.DoesNotExist:
        task = get_object_or_404(Task, pk=task_id)
        is_plan = False
    # ... rest of view, branching where needed
```

This preserves existing URL behavior without URL churn. The SPA work in future plans will supersede these HTML views anyway.

### Task 4.2: Update `MaterialForm`

**Files:**
- Modify: `apps/jobs/forms.py:203-214`

- [ ] **Step 1: Update the Meta model**

```python
class MaterialForm(forms.ModelForm):
    class Meta:
        model = PlanMaterial  # was Material
        fields = [
            'price_list_item', 'description', 'quantity',
            'unit_cost', 'sell_price', 'line_item_type',
            'accounting_category',
        ]
```

Update the import at the top:

```python
from apps.inventory.models import PlanMaterial  # was Material
```

Note: this form is only used for worksheet-side materials (per the current HTML views). WO-side materials will get their own form in a future plan.

### Task 4.3: Update `apps/estimates/signals.py`

**Files:**
- Modify: `apps/estimates/signals.py:117-135`

- [ ] **Step 1: Update the earmark signal query path**

The signal calls `InventoryService.get_earmark_preview(job)`. That service method was updated in Task 2.6 Step 2 to query `PlanMaterial`. No changes needed in the signal file itself — verify by reading the signal and confirming it still works end-to-end.

- [ ] **Step 2: Grep for any other worksheet-task references in signals**

```bash
grep -rn "task_set\|est_worksheet\|TaskBundle" apps/estimates/signals.py apps/jobs/signals.py
```

Update each hit: worksheet task access becomes `PlanTask` access; worksheet bundle access becomes `PlanBundle` access.

### Task 4.4: Update `apps/jobs/signals.py`

**Files:**
- Modify: `apps/jobs/signals.py` (if it exists and references Task)

- [ ] **Step 1: Find and update any references**

```bash
grep -n "Task\|TaskBundle\|Material\|est_worksheet" apps/jobs/signals.py
```

Update references: worksheet-side becomes `PlanTask`/`PlanBundle`/`PlanMaterial`, work-order-side stays `Task`/`Material`. Note that `Task` status-change signals should only apply to work-order-side tasks (PlanTask has no status), so any signal hooked to `post_save` on the old `Task` model should now be hooked to the new `Task` model specifically — which happens automatically since `Task` is now WO-only.

### Task 4.5: Phase 4 checkpoint

- [ ] **Step 1: Run the test suite**

```bash
python manage.py test 2>&1 | tail -50
```

Expected: remaining failures are concentrated in test files and fixtures.

- [ ] **Step 2: Commit**

```bash
git add apps/jobs/views.py apps/jobs/forms.py apps/estimates/signals.py apps/jobs/signals.py
git commit -m "$(cat <<'EOF'
refactor: update HTML views, forms, signals for model split

HTML material views and MaterialForm now target PlanTask/PlanMaterial.
task_detail HTML view falls back across both models to avoid URL churn.
Signals use PlanMaterial/PlanTask for worksheet-side queries.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5: Tests and fixtures

### Task 5.1: Inventory the remaining test failures

**Files:** none

- [ ] **Step 1: Run the test suite and capture failures**

```bash
python manage.py test 2>&1 | grep -E "^(ERROR|FAIL):" > /tmp/test_failures.txt
wc -l /tmp/test_failures.txt
cat /tmp/test_failures.txt
```

- [ ] **Step 2: Categorize failures**

Each failing test is in one of these buckets:
1. Constructs a `Task` with `est_worksheet=...` in setup → rewrite to construct `PlanTask`.
2. Constructs a `TaskBundle` with `est_worksheet=...` → rewrite to construct `PlanBundle`.
3. Constructs a `TaskBundle` with `work_order=...` → delete the test or rewrite (RealBundle doesn't exist).
4. Constructs a `Material` on a worksheet task → rewrite to construct `PlanMaterial`.
5. Asserts on `task.est_worksheet` → update to access via `PlanTask`.
6. Uses fixtures that reference the old Task structure → update the fixture file.
7. Legitimate behavior regression → investigate and fix the refactor.

Only bucket 7 indicates a bug in the refactor. The rest are mechanical test updates.

### Task 5.2: Update test fixtures

**Files:**
- Modify: `fixtures/unit_test_data.json` and any other fixture files under `fixtures/`

- [ ] **Step 1: List fixture files**

```bash
ls fixtures/*.json
```

- [ ] **Step 2: For each fixture that contains `jobs.task` entries, split**

Open each fixture. Find entries with `"model": "jobs.task"`. For each:
- If `"est_worksheet"` is non-null in the fields, change the model to `"jobs.plantask"` and remove the `work_order`, `assignee`, `status`, `parent_task`, `worker_queue` fields. The pk field may need to change from `task_id` to `plan_task_id` (check Django's fixture conventions for custom PKs).
- If `"work_order"` is non-null, change the model name stays `"jobs.task"` and remove `est_worksheet`, `mapping_strategy`, `bundle`.

Similarly for `jobs.taskbundle` entries:
- If `"est_worksheet"` is non-null, change to `"jobs.planbundle"`.
- If `"work_order"` is non-null, delete the entry entirely.

And for `inventory.material` entries:
- Look up the referenced task. If it's now a PlanTask, change the model to `"inventory.planmaterial"` and rename the `task` field to `plan_task`.
- Otherwise keep as `"inventory.material"`.

- [ ] **Step 3: Reload and verify**

```bash
python manage.py loaddata unit_test_data.json --verbosity=2
```

If loaddata errors, fix the fixture file until it loads.

### Task 5.3: Update `tests/base.py`

**Files:**
- Modify: `tests/base.py`

- [ ] **Step 1: Find task/bundle/material construction helpers**

```bash
grep -n "Task\|TaskBundle\|Material" tests/base.py
```

- [ ] **Step 2: Update helpers**

Any helper that creates worksheet-side entities should construct `PlanTask`/`PlanBundle`/`PlanMaterial`. Any helper for work-order-side should construct `Task`/`Material`. If helpers were unified (e.g., `make_task(container=...)`), split into `make_plan_task(worksheet=...)` and `make_task(work_order=...)`.

### Task 5.4: Fix failing tests file-by-file

**Files:**
- Modify: various test files under `tests/`

- [ ] **Step 1: Start with model tests**

```bash
python manage.py test tests.test_jobs_models -v 2 2>&1 | tail -30
```

Fix each failure per the bucketing in Task 5.1 Step 2. Run just the failing module after each fix to iterate quickly.

- [ ] **Step 2: Move to service tests**

```bash
python manage.py test tests.test_workorder_from_estimate tests.test_task_lifecycle tests.test_earmark_flow tests.test_auto_earmark -v 2
```

Fix failures. Note: `test_workorder_from_estimate` and related tests may exercise the `copy_from_worksheet` rewrite — they should still pass because the rewrite preserves observable behavior. If they fail for semantic reasons, verify the refactor is correct by re-reading Task 2.1.

- [ ] **Step 3: API tests**

```bash
python manage.py test tests.test_api_tasks tests.test_api_workorders tests.test_api_estimates -v 2
```

Fix failures.

- [ ] **Step 4: Everything else**

```bash
python manage.py test 2>&1 | grep -E "^(ERROR|FAIL):"
```

Fix the remaining failures iteratively.

### Task 5.5: Add new tests for `copy_from_worksheet`

**Files:**
- Create or modify: `tests/test_worksheet_to_workorder_copy.py`

- [ ] **Step 1: Write a test that exercises the new `copy_from_worksheet`**

```python
from django.test import TestCase
from decimal import Decimal
from apps.jobs.models import PlanTask, Task, WorkOrder
from apps.jobs.services import WorkOrderService
from apps.inventory.models import PlanMaterial, Material
# ... fixture setup imports


class CopyFromWorksheetTests(TestCase):
    fixtures = ['unit_test_data.json']

    def test_copy_creates_task_for_each_plan_task(self):
        # Given a worksheet with N plan tasks and a fresh work order on the same job
        worksheet = self._make_worksheet_with_plan_tasks(count=3)
        wo = WorkOrder.objects.create(job=worksheet.job)
        # When we copy
        WorkOrderService.copy_from_worksheet(wo.pk, worksheet.pk)
        # Then the WO has one Task per PlanTask
        self.assertEqual(wo.tasks.count(), 3)

    def test_copy_preserves_plan_material_pli_linkage(self):
        # Given a plan task with a PLI-linked plan material
        worksheet, plan_task = self._make_worksheet_with_plan_task_and_pli_material()
        wo = WorkOrder.objects.create(job=worksheet.job)
        # When we copy
        WorkOrderService.copy_from_worksheet(wo.pk, worksheet.pk)
        # Then the corresponding Task has a Material with the same PLI
        task = wo.tasks.get()
        material = task.materials.get()
        self.assertEqual(material.price_list_item, plan_task.plan_materials.get().price_list_item)

    def test_copy_drops_bundle_information(self):
        # Given plan tasks grouped in a PlanBundle
        worksheet = self._make_worksheet_with_bundled_plan_tasks(count=2)
        wo = WorkOrder.objects.create(job=worksheet.job)
        # When we copy
        WorkOrderService.copy_from_worksheet(wo.pk, worksheet.pk)
        # Then the Tasks on the WO have no bundle attribute
        for task in wo.tasks.all():
            self.assertFalse(hasattr(task, 'bundle'))  # or assertRaises(AttributeError)

    def test_copy_flat_no_parent_task(self):
        # Given a worksheet (no hierarchy is possible on PlanTasks)
        worksheet = self._make_worksheet_with_plan_tasks(count=2)
        wo = WorkOrder.objects.create(job=worksheet.job)
        WorkOrderService.copy_from_worksheet(wo.pk, worksheet.pk)
        for task in wo.tasks.all():
            self.assertIsNone(task.parent_task)

    # Helper methods _make_worksheet_with_plan_tasks etc. construct test fixtures
    # inline using PlanTask/PlanMaterial/PlanBundle. Fill in based on existing
    # test patterns in tests/test_worksheet_*.py.
```

Fill in the helper methods using patterns from existing tests. If similar tests already exist (likely in `tests/test_workorder_from_estimate.py` or `tests/test_worksheet_finalization.py`), extend them rather than creating a new file.

- [ ] **Step 2: Run the new test**

```bash
python manage.py test tests.test_worksheet_to_workorder_copy -v 2
```

Expected: pass.

### Task 5.6: Phase 5 checkpoint

- [ ] **Step 1: Run the full suite**

```bash
python manage.py test 2>&1 | tail -10
```

Expected: all green. Test count should be equal to or greater than the baseline captured in Task 0.1. If the count is lower, identify the missing tests and restore or justify their removal.

- [ ] **Step 2: Commit**

```bash
git add tests/ fixtures/
git commit -m "$(cat <<'EOF'
refactor: update tests and fixtures for model split

Rewrite test setup to construct PlanTask/PlanBundle/PlanMaterial on the
worksheet side and Task/Material on the work-order side. Update
fixtures to split entries across the new tables. Add new tests
covering copy_from_worksheet's rewrite.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 6: Final cleanup and documentation

### Task 6.1: Amend the 2026-03-06 lifecycle doc

**Files:**
- Modify: `docs/designs/2026-03-06-material-pli-lifecycle.md`

- [ ] **Step 1: Add amendment section**

Append to the end of the file (after the existing "Related" section):

```markdown

---

## Amendment (2026-04-05)

Phases 4 and 5 of this document are superseded by the task/bundle/material
split refactor. See `docs/designs/2026-04-05-task-split-and-worksheet-to-workorder.md`.

Specifically:

- **Phase 4 ("WorkOrder firm up") is deleted.** `price_list_item` on a
  material is set at creation time or never. There is no firming-up
  phase. The reasoning: a freeform material and a PLI-linked material
  are factually different records, and retroactive linking would
  quietly rewrite inventory history.
- **Phase 5's invoice PLI gate is deleted.** A Material with a
  `line_item_type` can become an `InvoiceLineItem` regardless of PLI
  status. The original gate existed because `line_item_type` wasn't
  yet a field on Material; once it was added (Phase 1 of this doc's
  own implementation plan), the gate became redundant.

The original phase descriptions above are preserved for decision-history
purposes but do not reflect current behavior.
```

- [ ] **Step 2: Commit the amendment**

```bash
git add docs/designs/2026-03-06-material-pli-lifecycle.md
git commit -m "docs: amend 2026-03-06 lifecycle doc for task split

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### Task 6.2: Remove any dead code flagged during the refactor

**Files:** various

- [ ] **Step 1: Search for leftover dead code**

```bash
grep -rn "get_container\b" apps/
grep -rn "container_field" apps/api/
grep -rn "TaskBundle\b" apps/
```

- [ ] **Step 2: Delete any dead references**

`get_container` was only useful when one model served two roles. After the split it should be gone. If any stragglers remain, delete them. If anything still imports `TaskBundle` from `apps.jobs.models`, update to `PlanBundle` or delete.

### Task 6.3: Verify migration still clean

**Files:** none

- [ ] **Step 1: Check for unmigrated changes**

```bash
python manage.py makemigrations --check --dry-run
```

Expected: "No changes detected". If Django proposes a new migration, it means a model edit happened during Phase 2-5 that wasn't captured in the Phase 1 migration. Decide whether to fold it in (if the change is to the split-introduced models) or add as a follow-up migration.

### Task 6.4: Full-suite final run and commit

- [ ] **Step 1: Run the full suite one more time**

```bash
python manage.py test 2>&1 | tail -10
```

Expected: all green, count >= baseline.

- [ ] **Step 2: Run makemigrations check one more time**

```bash
python manage.py makemigrations --check --dry-run
```

Expected: no changes.

- [ ] **Step 3: Commit anything uncommitted**

```bash
git status
```

If clean, Plan 1 is done. If there are stragglers, commit them with a descriptive message.

- [ ] **Step 4: Review commit log**

```bash
git log --oneline main..HEAD
```

The commit history for this plan should be roughly:
1. `refactor: split Task/Bundle/Material models (models + migration)`
2. `refactor: update services for Task/Bundle/Material split`
3. `refactor: update API mixins/serializers/views for model split`
4. `refactor: update HTML views, forms, signals for model split`
5. `refactor: update tests and fixtures for model split`
6. `docs: amend 2026-03-06 lifecycle doc for task split`

Plus any follow-up cleanup commits.

---

## Completion Criteria

Plan 1 is complete when:

1. All existing tests pass (`python manage.py test`).
2. Test count is equal to or greater than the baseline from Task 0.1.
3. `python manage.py makemigrations --check --dry-run` reports no changes.
4. `PlanTask`, `Task`, `PlanBundle`, `PlanMaterial`, `Material` exist as separate models with the shapes defined in the spec.
5. `TaskBundle` and the dual-FK `Task` no longer exist.
6. `TaskTemplate.parent_template` no longer exists.
7. `EstimateLineItem.task` targets `PlanTask`.
8. The 2026-03-06 lifecycle doc has an amendment section pointing at the new spec.
9. No code references `task.est_worksheet` or `task.get_container()`.

## What's Explicitly NOT in Plan 1

These remain for Plans 2 and 3:

- New `/api/plan-tasks/` API resource (Plan 2).
- Workflow routing: hard prereq gates beyond existing checks, soft warnings for workflow mismatch (Plan 2).
- SPA `#/worksheets/[ws_id]/plan-tasks/[pt_id]` routes (Plan 2, if wanted before materials project).
- Deleting `auto_earmark_inventory` signal (Plan 3).
- WO-creation-time earmark hook (Plan 3).
- WO-lifecycle earmark release (Plan 3).
- `InventoryService.get_earmark_preview` rewrite to query WO-side materials (Plan 3).

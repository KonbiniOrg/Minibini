# Task-as-Labor + RateScheme Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor Task to pure labor, introduce RateScheme as a first-class billing pattern, and add TaskCharge/PlanCharge as per-instance billing configuration.

**Architecture:** New RateScheme model in `apps/jobs/` (alongside Task/Blep). TaskCharge and PlanCharge are OneToOne companions to Task and PlanTask. TaskBase loses `units`, `rate`, `est_qty`; gains `est_worker_time`. Billing data moves to Charge objects that reference RateSchemes. Settings UI for RateScheme and TaskTemplate management. Worksheet PlanTaskModal and TaskDetailPage updated to work with charges.

**Tech Stack:** Django 5.2, DRF, MySQL, Svelte 5 (Vite), Python 3.12

**Spec:** `docs/designs/2026-04-16-task-labor-ratescheme-refactor.md`

---

## File Structure

### New files

| File | Responsibility |
|---|---|
| `apps/jobs/models.py` (modify) | Add RateScheme, TaskCharge, PlanCharge models |
| `apps/jobs/services.py` (create) | RateSchemeService, TaskChargeService |
| `apps/jobs/migrations/0013_ratescheme_taskcharge_plancharge.py` | New tables + est_worker_time on TaskBase |
| `apps/jobs/migrations/0014_remove_taskbase_billing_fields.py` | Drop units, rate, est_qty from TaskBase |
| `apps/api/rate_schemes/__init__.py` | API module |
| `apps/api/rate_schemes/serializers.py` | RateScheme serializers |
| `apps/api/rate_schemes/views.py` | RateScheme viewset |
| `tests/test_rate_scheme.py` | RateScheme model + service tests |
| `tests/test_rate_scheme_api.py` | RateScheme API tests |
| `tests/test_task_charge.py` | TaskCharge + PlanCharge model tests |
| `tests/test_task_charge_api.py` | TaskCharge API tests |
| `frontend/src/components/RateSchemeManager.svelte` | Settings UI for RateScheme CRUD |
| `frontend/src/components/TaskTemplateManager.svelte` | Settings UI for TaskTemplate CRUD |

### Modified files

| File | Changes |
|---|---|
| `apps/jobs/models.py` | TaskBase: remove units/rate/est_qty, add est_worker_time |
| `apps/estimates/models.py` | TaskTemplate: add rate_scheme FK, default_active_modifiers, default_billable_qty; remove units/rate |
| `apps/estimates/services.py` | EstimateGenerationService: read billing from PlanCharge |
| `apps/api/tasks/serializers.py` | Remove units/rate/est_qty; add nested charge |
| `apps/api/plan_tasks/serializers.py` | Remove units/rate/est_qty; add nested charge |
| `apps/api/templates_config/serializers.py` | Add rate_scheme, default_active_modifiers, default_billable_qty |
| `apps/api/templates_config/views.py` | Update TaskTemplateViewSet for new fields |
| `apps/api/urls.py` | Register rate-schemes router |
| `frontend/src/routes/SettingsPage.svelte` | Add RateSchemeManager + TaskTemplateManager |
| `frontend/src/components/PlanTaskModal.svelte` | Modifier checkboxes, charge creation |
| `frontend/src/routes/jobs/TaskDetailPage.svelte` | Charge display, actual qty entry |
| `fixtures/unit_test_data.json` | Add RateScheme fixtures; update Task/TaskTemplate fixtures |

---

## Phase 1: Models + API + Settings UI

### Task 1: RateScheme model + compute methods

**Files:**
- Modify: `apps/jobs/models.py:1-10` (imports) and append after line 325 (after Blep class)
- Test: `tests/test_rate_scheme.py` (create)

- [ ] **Step 1: Write the failing test for RateScheme creation**

```python
# tests/test_rate_scheme.py
from decimal import Decimal
from tests.base import BaseTestCase
from apps.jobs.models import RateScheme


class RateSchemeModelTest(BaseTestCase):

    def test_create_elapsed_time_scheme(self):
        scheme = RateScheme.objects.create(
            name='Hourly Labor',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45.00'),
            unit_label='hour',
        )
        self.assertEqual(scheme.name, 'Hourly Labor')
        self.assertEqual(scheme.algorithm, 'elapsed_time')
        self.assertEqual(scheme.rate, Decimal('45.00'))
        self.assertEqual(scheme.unit_label, 'hour')
        self.assertIsNone(scheme.minimum_charge)
        self.assertEqual(scheme.modifiers, [])

    def test_create_entered_qty_scheme_with_modifiers(self):
        scheme = RateScheme.objects.create(
            name='CNC Router',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='minute',
            modifiers=[
                {'key': 'messy', 'label': 'Messy materials', 'percent': 10},
                {'key': 'doublestick', 'label': 'Doublestick tape', 'percent': 5},
            ],
        )
        self.assertEqual(len(scheme.modifiers), 2)
        self.assertEqual(scheme.modifiers[0]['key'], 'messy')

    def test_create_flat_fee_scheme(self):
        scheme = RateScheme.objects.create(
            name='CNC Setup',
            algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('50.00'),
            unit_label='job',
        )
        self.assertEqual(scheme.algorithm, 'flat_fee')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_rate_scheme -v 2`
Expected: FAIL — `ImportError: cannot import name 'RateScheme'`

- [ ] **Step 3: Write RateScheme model**

Add to `apps/jobs/models.py` after the Blep class (after line 325):

```python
class RateScheme(models.Model):
    """Billing pattern — defines how a type of work is priced."""
    ELAPSED_TIME = 'elapsed_time'
    ENTERED_QTY = 'entered_qty'
    FLAT_FEE = 'flat_fee'

    ALGORITHM_CHOICES = [
        (ELAPSED_TIME, 'Based on time worked'),
        (ENTERED_QTY, 'Worker enters quantity'),
        (FLAT_FEE, 'Fixed charge'),
    ]

    rate_scheme_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default='')
    algorithm = models.CharField(max_length=20, choices=ALGORITHM_CHOICES)
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    unit_label = models.CharField(max_length=50)
    minimum_charge = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    modifiers = models.JSONField(default=list, blank=True)
    accounting_category = models.ForeignKey(
        'core.AccountingCategory',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    class Meta:
        db_table = 'rate_schemes'

    def __str__(self):
        return self.name

    def effective_rate(self, active_modifiers=None):
        """Rate with additive modifier surcharges applied."""
        modifier_percent = sum(
            m['percent'] for m in self.modifiers
            if m['key'] in (active_modifiers or [])
        )
        return self.rate * (1 + Decimal(modifier_percent) / 100)

    def compute_charge(self, qty, active_modifiers=None):
        """Compute total charge for a given quantity and active modifiers."""
        total = qty * self.effective_rate(active_modifiers)
        if self.minimum_charge:
            total = max(total, self.minimum_charge)
        return total

    def get_actual_qty(self, task):
        """Resolve actual quantity based on algorithm type.

        Args:
            task: a Task instance (reads task.bleps and task.charge.actuals)
        Returns:
            Decimal quantity
        """
        if self.algorithm == self.ELAPSED_TIME:
            total_seconds = sum(
                (b.elapsed.total_seconds() for b in task.bleps.all() if b.elapsed),
                0,
            )
            return Decimal(str(total_seconds)) / 3600
        elif self.algorithm == self.ENTERED_QTY:
            return Decimal(str(task.charge.actuals.get('qty', 0)))
        elif self.algorithm == self.FLAT_FEE:
            return Decimal('1')
        return Decimal('0')

    def get_modifier_inputs(self):
        """Return list of modifier definitions for UI rendering."""
        return list(self.modifiers)
```

- [ ] **Step 4: Create migration**

Run: `python manage.py makemigrations jobs --name ratescheme`

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_rate_scheme -v 2`
Expected: All 3 tests PASS

- [ ] **Step 6: Write tests for compute methods**

Add to `tests/test_rate_scheme.py`:

```python
class RateSchemeComputeTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.scheme = RateScheme.objects.create(
            name='CNC Router',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='minute',
            minimum_charge=Decimal('20.00'),
            modifiers=[
                {'key': 'messy', 'label': 'Messy materials', 'percent': 10},
                {'key': 'doublestick', 'label': 'Doublestick tape', 'percent': 5},
                {'key': 'fumes', 'label': 'Poisonous fumes', 'percent': 8},
            ],
        )

    def test_effective_rate_no_modifiers(self):
        self.assertEqual(self.scheme.effective_rate(), Decimal('4.00'))

    def test_effective_rate_one_modifier(self):
        rate = self.scheme.effective_rate(['messy'])
        self.assertEqual(rate, Decimal('4.40'))

    def test_effective_rate_stacking_modifiers(self):
        rate = self.scheme.effective_rate(['messy', 'doublestick'])
        # 4.00 * (1 + 15/100) = 4.60
        self.assertEqual(rate, Decimal('4.60'))

    def test_compute_charge_basic(self):
        charge = self.scheme.compute_charge(Decimal('30'), [])
        self.assertEqual(charge, Decimal('120.00'))

    def test_compute_charge_with_modifiers(self):
        charge = self.scheme.compute_charge(Decimal('30'), ['messy', 'doublestick'])
        # 30 * 4.60 = 138.00
        self.assertEqual(charge, Decimal('138.00'))

    def test_compute_charge_minimum_applies(self):
        charge = self.scheme.compute_charge(Decimal('1'), [])
        # 1 * 4.00 = 4.00, but minimum is 20.00
        self.assertEqual(charge, Decimal('20.00'))

    def test_compute_charge_minimum_not_applied_when_exceeded(self):
        charge = self.scheme.compute_charge(Decimal('10'), [])
        # 10 * 4.00 = 40.00, exceeds minimum of 20.00
        self.assertEqual(charge, Decimal('40.00'))

    def test_flat_fee_effective_rate(self):
        flat = RateScheme.objects.create(
            name='Setup', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('50.00'), unit_label='job',
        )
        self.assertEqual(flat.effective_rate(), Decimal('50.00'))

    def test_flat_fee_compute(self):
        flat = RateScheme.objects.create(
            name='Setup Fee', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('50.00'), unit_label='job',
        )
        self.assertEqual(flat.compute_charge(Decimal('1'), []), Decimal('50.00'))
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python manage.py test tests.test_rate_scheme -v 2`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/ tests/test_rate_scheme.py
git commit -m "feat: add RateScheme model with compute methods"
```

---

### Task 2: TaskCharge and PlanCharge models

**Files:**
- Modify: `apps/jobs/models.py` (append after RateScheme)
- Test: `tests/test_task_charge.py` (create)

- [ ] **Step 1: Write the failing test for TaskCharge**

```python
# tests/test_task_charge.py
from decimal import Decimal
from django.utils import timezone
from tests.base import BaseTestCase
from apps.jobs.models import Task, Blep, RateScheme, TaskCharge, PlanCharge, PlanTask
from apps.jobs.models import Job
from apps.estimates.models import EstWorksheet


class TaskChargeModelTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.scheme = RateScheme.objects.create(
            name='CNC Router',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='minute',
            modifiers=[
                {'key': 'messy', 'label': 'Messy materials', 'percent': 10},
                {'key': 'doublestick', 'label': 'Doublestick tape', 'percent': 5},
            ],
        )
        self.job = Job.objects.get(pk=1)
        self.task = Task.objects.get(pk=1)

    def test_create_task_charge(self):
        charge = TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            active_modifiers=['messy', 'doublestick'],
            actuals={'qty': 30},
        )
        self.assertEqual(charge.task, self.task)
        self.assertEqual(charge.rate_scheme, self.scheme)
        self.assertEqual(charge.active_modifiers, ['messy', 'doublestick'])
        self.assertEqual(charge.actuals, {'qty': 30})

    def test_task_charge_compute(self):
        charge = TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            active_modifiers=['messy', 'doublestick'],
            actuals={'qty': 30},
        )
        # 30 * 4.00 * (1 + 15/100) = 30 * 4.60 = 138.00
        self.assertEqual(charge.compute(), Decimal('138.00'))

    def test_task_charge_effective_rate(self):
        charge = TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            active_modifiers=['messy'],
        )
        self.assertEqual(charge.effective_rate(), Decimal('4.40'))

    def test_task_charge_has_actuals_false(self):
        charge = TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
        )
        self.assertFalse(charge.has_actuals())

    def test_task_charge_has_actuals_true(self):
        charge = TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            actuals={'qty': 30},
        )
        self.assertTrue(charge.has_actuals())

    def test_task_charge_one_to_one(self):
        TaskCharge.objects.create(task=self.task, rate_scheme=self.scheme)
        with self.assertRaises(Exception):
            TaskCharge.objects.create(task=self.task, rate_scheme=self.scheme)

    def test_task_charge_reverse_access(self):
        TaskCharge.objects.create(
            task=self.task, rate_scheme=self.scheme, actuals={'qty': 10},
        )
        self.assertEqual(self.task.charge.actuals, {'qty': 10})


class TaskChargeElapsedTimeTest(BaseTestCase):
    """Test compute() for elapsed_time scheme via bleps."""

    def setUp(self):
        super().setUp()
        self.scheme = RateScheme.objects.create(
            name='Hourly Labor',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45.00'),
            unit_label='hour',
        )
        self.task = Task.objects.get(pk=1)
        self.charge = TaskCharge.objects.create(
            task=self.task, rate_scheme=self.scheme,
        )
        # Create bleps: 2 hours total
        now = timezone.now()
        Blep.objects.create(
            task=self.task,
            user=self.task.assignee,
            start_time=now - timezone.timedelta(hours=2),
            end_time=now - timezone.timedelta(hours=1),
        )
        Blep.objects.create(
            task=self.task,
            user=self.task.assignee,
            start_time=now - timezone.timedelta(hours=1),
            end_time=now,
        )

    def test_compute_from_bleps(self):
        # 2 hours * $45/hr = $90
        charge = self.charge.compute()
        self.assertAlmostEqual(charge, Decimal('90.00'), places=1)


class TaskChargeFlatFeeTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.scheme = RateScheme.objects.create(
            name='Setup Fee',
            algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('50.00'),
            unit_label='job',
        )
        self.task = Task.objects.get(pk=1)

    def test_flat_fee_compute(self):
        charge = TaskCharge.objects.create(
            task=self.task, rate_scheme=self.scheme,
        )
        self.assertEqual(charge.compute(), Decimal('50.00'))


class PlanChargeModelTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.scheme = RateScheme.objects.create(
            name='CNC Router',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='minute',
            modifiers=[
                {'key': 'messy', 'label': 'Messy materials', 'percent': 10},
            ],
        )
        # Get a worksheet + plan task from fixtures
        self.worksheet = EstWorksheet.objects.first()
        if self.worksheet is None:
            self.skipTest('No EstWorksheet in fixtures')
        self.plan_task = PlanTask.objects.filter(
            est_worksheet=self.worksheet
        ).first()
        if self.plan_task is None:
            self.skipTest('No PlanTask in fixtures')

    def test_create_plan_charge(self):
        charge = PlanCharge.objects.create(
            plan_task=self.plan_task,
            rate_scheme=self.scheme,
            active_modifiers=['messy'],
            estimated_billable_qty=Decimal('30.00'),
        )
        self.assertEqual(charge.plan_task, self.plan_task)
        self.assertEqual(charge.estimated_billable_qty, Decimal('30.00'))

    def test_plan_charge_compute(self):
        charge = PlanCharge.objects.create(
            plan_task=self.plan_task,
            rate_scheme=self.scheme,
            active_modifiers=['messy'],
            estimated_billable_qty=Decimal('30.00'),
        )
        # 30 * 4.00 * 1.10 = 132.00
        self.assertEqual(charge.compute(), Decimal('132.00'))

    def test_plan_charge_effective_rate(self):
        charge = PlanCharge.objects.create(
            plan_task=self.plan_task,
            rate_scheme=self.scheme,
            active_modifiers=['messy'],
            estimated_billable_qty=Decimal('30.00'),
        )
        self.assertEqual(charge.effective_rate(), Decimal('4.40'))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_task_charge -v 2`
Expected: FAIL — `ImportError: cannot import name 'TaskCharge'`

- [ ] **Step 3: Write TaskCharge and PlanCharge models**

Add to `apps/jobs/models.py` after RateScheme:

```python
class TaskCharge(models.Model):
    """Filled-in billing form for a Task — stores which modifiers are active
    and what values the worker entered."""
    task_charge_id = models.AutoField(primary_key=True)
    task = models.OneToOneField(Task, on_delete=models.CASCADE, related_name='charge')
    rate_scheme = models.ForeignKey(RateScheme, on_delete=models.PROTECT)
    active_modifiers = models.JSONField(default=list, blank=True)
    actuals = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'task_charges'

    def __str__(self):
        return f"Charge for {self.task}"

    def compute(self):
        """Compute charge using scheme's algorithm and this charge's specifics."""
        qty = self.rate_scheme.get_actual_qty(self.task)
        return self.rate_scheme.compute_charge(qty, self.active_modifiers)

    def effective_rate(self):
        """Effective rate with active modifiers applied."""
        return self.rate_scheme.effective_rate(self.active_modifiers)

    def has_actuals(self):
        """Whether worker has entered required values for the scheme's algorithm."""
        if self.rate_scheme.algorithm == RateScheme.ENTERED_QTY:
            return bool(self.actuals.get('qty'))
        return True  # elapsed_time and flat_fee don't need manual entry


class PlanCharge(models.Model):
    """Filled-in billing form for a PlanTask (worksheet/estimate stage).
    No actuals — used for quoting only."""
    plan_charge_id = models.AutoField(primary_key=True)
    plan_task = models.OneToOneField(PlanTask, on_delete=models.CASCADE, related_name='charge')
    rate_scheme = models.ForeignKey(RateScheme, on_delete=models.PROTECT)
    active_modifiers = models.JSONField(default=list, blank=True)
    estimated_billable_qty = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'plan_charges'

    def __str__(self):
        return f"Charge for {self.plan_task}"

    def compute(self):
        """Compute estimated charge from qty and scheme."""
        return self.rate_scheme.compute_charge(
            self.estimated_billable_qty, self.active_modifiers
        )

    def effective_rate(self):
        """Effective rate with active modifiers applied."""
        return self.rate_scheme.effective_rate(self.active_modifiers)
```

- [ ] **Step 4: Update migration**

Run: `python manage.py makemigrations jobs --name taskcharge_plancharge`

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_task_charge -v 2`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/ tests/test_task_charge.py
git commit -m "feat: add TaskCharge and PlanCharge models"
```

---

### Task 3: Add est_worker_time to TaskBase

**Files:**
- Modify: `apps/jobs/models.py:123-143` (TaskBase class)
- Test: `tests/test_task_charge.py` (add to existing)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_task_charge.py`:

```python
from datetime import timedelta


class EstWorkerTimeTest(BaseTestCase):

    def test_task_has_est_worker_time(self):
        task = Task.objects.get(pk=1)
        self.assertIsNone(task.est_worker_time)

    def test_task_set_est_worker_time(self):
        task = Task.objects.get(pk=1)
        task.est_worker_time = timedelta(hours=2, minutes=30)
        task.save()
        task.refresh_from_db()
        self.assertEqual(task.est_worker_time, timedelta(hours=2, minutes=30))

    def test_plan_task_has_est_worker_time(self):
        pt = PlanTask.objects.first()
        if pt is None:
            self.skipTest('No PlanTask in fixtures')
        self.assertIsNone(pt.est_worker_time)

    def test_task_has_source_template(self):
        task = Task.objects.get(pk=1)
        self.assertIsNone(task.source_template)

    def test_task_set_source_template(self):
        from apps.estimates.models import TaskTemplate
        tmpl = TaskTemplate.objects.first()
        task = Task.objects.get(pk=1)
        task.source_template = tmpl
        task.save()
        task.refresh_from_db()
        self.assertEqual(task.source_template, tmpl)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_task_charge.EstWorkerTimeTest -v 2`
Expected: FAIL — field does not exist

- [ ] **Step 3: Add field to TaskBase and source_template to Task**

In `apps/jobs/models.py`, add to `TaskBase` class (around line 128, after `sort_order`):

```python
    est_worker_time = models.DurationField(
        null=True, blank=True,
        help_text="Estimated worker time for scheduling"
    )
```

In the `Task` class (around line 228, after `assignee`), add:

```python
    source_template = models.ForeignKey(
        'estimates.TaskTemplate',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text="TaskTemplate this task was created from"
    )
```

- [ ] **Step 4: Create migration**

Run: `python manage.py makemigrations jobs --name est_worker_time`

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_task_charge.EstWorkerTimeTest -v 2`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/ tests/test_task_charge.py
git commit -m "feat: add est_worker_time DurationField to TaskBase"
```

---

### Task 4: RateScheme API (CRUD)

**Files:**
- Create: `apps/api/rate_schemes/__init__.py`
- Create: `apps/api/rate_schemes/serializers.py`
- Create: `apps/api/rate_schemes/views.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_rate_scheme_api.py` (create)

- [ ] **Step 1: Write the failing test for RateScheme list**

```python
# tests/test_rate_scheme_api.py
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.jobs.models import RateScheme

User = get_user_model()


class RateSchemeAPITest(TestCase):

    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin', password='testpass',
            is_staff=True,
        )
        # Grant can_manage_config permission
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(codename='can_manage_config')
        self.admin.user_permissions.add(perm)

        self.worker = User.objects.create_user(
            username='worker', password='testpass',
        )

        self.scheme = RateScheme.objects.create(
            name='Hourly Labor',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45.00'),
            unit_label='hour',
        )

    def test_list_requires_auth(self):
        resp = self.client.get('/api/rate-schemes/')
        self.assertEqual(resp.status_code, 403)

    def test_list_authenticated(self):
        self.client.login(username='worker', password='testpass')
        resp = self.client.get('/api/rate-schemes/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['results']), 1)

    def test_create_requires_config_perm(self):
        self.client.login(username='worker', password='testpass')
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'New Scheme',
            'algorithm': 'flat_fee',
            'rate': '50.00',
            'unit_label': 'job',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_create_with_config_perm(self):
        self.client.login(username='admin', password='testpass')
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'CNC Setup',
            'algorithm': 'flat_fee',
            'rate': '50.00',
            'unit_label': 'job',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['name'], 'CNC Setup')

    def test_create_with_modifiers(self):
        self.client.login(username='admin', password='testpass')
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'CNC Router',
            'algorithm': 'entered_qty',
            'rate': '4.00',
            'unit_label': 'minute',
            'modifiers': [
                {'key': 'messy', 'label': 'Messy', 'percent': 10},
            ],
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(resp.json()['modifiers']), 1)

    def test_update(self):
        self.client.login(username='admin', password='testpass')
        resp = self.client.patch(
            f'/api/rate-schemes/{self.scheme.pk}/',
            {'rate': '50.00'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['rate'], '50.00')

    def test_delete(self):
        self.client.login(username='admin', password='testpass')
        resp = self.client.delete(f'/api/rate-schemes/{self.scheme.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(RateScheme.objects.filter(pk=self.scheme.pk).exists())

    def test_retrieve(self):
        self.client.login(username='worker', password='testpass')
        resp = self.client.get(f'/api/rate-schemes/{self.scheme.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['name'], 'Hourly Labor')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_rate_scheme_api -v 2`
Expected: FAIL — 404 (no URL route)

- [ ] **Step 3: Create serializer**

```python
# apps/api/rate_schemes/__init__.py
# (empty)
```

```python
# apps/api/rate_schemes/serializers.py
from rest_framework import serializers
from apps.jobs.models import RateScheme


class RateSchemeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RateScheme
        fields = [
            'rate_scheme_id', 'name', 'description', 'algorithm',
            'rate', 'unit_label', 'minimum_charge',
            'modifiers', 'accounting_category',
        ]
        read_only_fields = ['rate_scheme_id']
```

- [ ] **Step 4: Create viewset**

```python
# apps/api/rate_schemes/views.py
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.api.permissions import CanManageConfig
from apps.jobs.models import RateScheme
from .serializers import RateSchemeSerializer


class RateSchemeViewSet(viewsets.ModelViewSet):
    queryset = RateScheme.objects.all().order_by('name')
    serializer_class = RateSchemeSerializer
    lookup_field = 'pk'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageConfig()]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response({'message': f'Rate scheme "{instance.name}" deleted.'})
```

- [ ] **Step 5: Register URL**

In `apps/api/urls.py`, add import:

```python
from apps.api.rate_schemes.views import RateSchemeViewSet
```

Add to router registrations (around line 75):

```python
router.register(r'rate-schemes', RateSchemeViewSet, basename='rate-scheme')
```

Add to `api_root` response dict:

```python
'rate-schemes': '/api/rate-schemes/',
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python manage.py test tests.test_rate_scheme_api -v 2`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add apps/api/rate_schemes/ apps/api/urls.py tests/test_rate_scheme_api.py
git commit -m "feat: add RateScheme API endpoints"
```

---

### Task 5: TaskCharge API (nested under task)

**Files:**
- Modify: `apps/api/tasks/serializers.py`
- Modify: `apps/api/tasks/views.py` (or create charge endpoint)
- Test: `tests/test_task_charge_api.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_task_charge_api.py
from decimal import Decimal
from tests.base import BaseTestCase
from apps.jobs.models import RateScheme, TaskCharge, Task


class TaskChargeAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.scheme = RateScheme.objects.create(
            name='CNC Router',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='minute',
            modifiers=[
                {'key': 'messy', 'label': 'Messy', 'percent': 10},
            ],
        )
        self.task = Task.objects.get(pk=1)
        # Login as admin user from fixtures (pk=1 is typically admin)
        self.client.login(username='admin_user', password='admin_password')

    def test_task_serializer_includes_charge_null(self):
        """Task without a charge shows charge: null."""
        resp = self.client.get(f'/api/tasks/{self.task.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()['charge'])

    def test_task_serializer_includes_charge(self):
        """Task with a charge shows nested charge data."""
        TaskCharge.objects.create(
            task=self.task,
            rate_scheme=self.scheme,
            active_modifiers=['messy'],
            actuals={'qty': 30},
        )
        resp = self.client.get(f'/api/tasks/{self.task.pk}/')
        self.assertEqual(resp.status_code, 200)
        charge = resp.json()['charge']
        self.assertIsNotNone(charge)
        self.assertEqual(charge['rate_scheme'], self.scheme.pk)
        self.assertEqual(charge['active_modifiers'], ['messy'])
        self.assertEqual(charge['actuals'], {'qty': 30})

    def test_create_charge_on_task(self):
        job_id = self.task.job_id
        resp = self.client.post(
            f'/api/jobs/{job_id}/tasks/{self.task.pk}/charge/',
            {
                'rate_scheme': self.scheme.pk,
                'active_modifiers': ['messy'],
                'actuals': {'qty': 30},
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(TaskCharge.objects.filter(task=self.task).exists())

    def test_update_charge_actuals(self):
        charge = TaskCharge.objects.create(
            task=self.task, rate_scheme=self.scheme,
        )
        job_id = self.task.job_id
        resp = self.client.patch(
            f'/api/jobs/{job_id}/tasks/{self.task.pk}/charge/',
            {'actuals': {'qty': 35}},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        charge.refresh_from_db()
        self.assertEqual(charge.actuals, {'qty': 35})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_task_charge_api -v 2`
Expected: FAIL — `charge` field not in serializer / URL not found

- [ ] **Step 3: Add TaskCharge serializer**

Add to `apps/api/tasks/serializers.py`:

```python
from apps.jobs.models import TaskCharge


class TaskChargeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskCharge
        fields = [
            'task_charge_id', 'rate_scheme', 'active_modifiers', 'actuals',
        ]
        read_only_fields = ['task_charge_id']


class TaskChargeReadSerializer(serializers.ModelSerializer):
    """Nested read-only representation for task detail."""
    scheme_name = serializers.CharField(source='rate_scheme.name', read_only=True)
    scheme_algorithm = serializers.CharField(source='rate_scheme.algorithm', read_only=True)
    scheme_unit_label = serializers.CharField(source='rate_scheme.unit_label', read_only=True)
    effective_rate = serializers.SerializerMethodField()
    computed_charge = serializers.SerializerMethodField()

    class Meta:
        model = TaskCharge
        fields = [
            'task_charge_id', 'rate_scheme', 'active_modifiers', 'actuals',
            'scheme_name', 'scheme_algorithm', 'scheme_unit_label',
            'effective_rate', 'computed_charge',
        ]
        read_only_fields = fields

    def get_effective_rate(self, obj):
        return str(obj.effective_rate())

    def get_computed_charge(self, obj):
        try:
            return str(obj.compute())
        except Exception:
            return None
```

- [ ] **Step 4: Add charge field to TaskDetailSerializer**

In `apps/api/tasks/serializers.py`, modify `TaskDetailSerializer`:

```python
class TaskDetailSerializer(serializers.ModelSerializer):
    assignee_name = serializers.SerializerMethodField()
    units = UnitsField()
    job = serializers.SerializerMethodField()
    charge = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'status',
            'blocked_reason', 'units', 'rate', 'est_qty', 'accounting_category',
            'parent_task', 'assignee', 'assignee_name',
            'worker_queue', 'job', 'charge',
        ]
        read_only_fields = fields

    # ... existing get_assignee_name, get_job methods unchanged ...

    def get_charge(self, obj):
        try:
            charge = obj.charge
        except TaskCharge.DoesNotExist:
            return None
        return TaskChargeReadSerializer(charge).data
```

- [ ] **Step 5: Add charge endpoint to job tasks**

Read the current task views to find the job-nested task pattern, then add a charge action. In `apps/api/tasks/views.py` (or as a separate view), add the charge CRUD endpoint.

First, check how job-nested task URLs work. The JobViewSet likely has nested task routes. Add a charge action:

Create or modify the appropriate view file. If tasks are nested under jobs via `JobViewSet`, add to `apps/api/jobs/views.py`:

```python
# Add to the appropriate viewset or as a standalone view
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
from apps.jobs.models import Task, TaskCharge
from apps.api.permissions import CanManageJobs
from apps.api.tasks.serializers import TaskChargeSerializer, TaskChargeReadSerializer


@api_view(['GET', 'POST', 'PATCH'])
@permission_classes([IsAuthenticated])
def task_charge_view(request, job_pk, task_pk):
    """GET/POST/PATCH charge for a specific task."""
    try:
        task = Task.objects.get(pk=task_pk, job_id=job_pk)
    except Task.DoesNotExist:
        return Response({'detail': 'Task not found.'}, status=404)

    if request.method == 'GET':
        try:
            charge = task.charge
        except TaskCharge.DoesNotExist:
            return Response(None)
        return Response(TaskChargeReadSerializer(charge).data)

    # POST/PATCH require CanManageJobs
    if not request.user.has_perm('core.can_manage_jobs'):
        return Response(status=403)

    if request.method == 'POST':
        if hasattr(task, 'charge'):
            try:
                task.charge
                return Response(
                    {'detail': 'Charge already exists. Use PATCH to update.'},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )
            except TaskCharge.DoesNotExist:
                pass
        serializer = TaskChargeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(task=task)
        return Response(
            TaskChargeReadSerializer(serializer.instance).data,
            status=http_status.HTTP_201_CREATED,
        )

    # PATCH
    try:
        charge = task.charge
    except TaskCharge.DoesNotExist:
        return Response({'detail': 'No charge to update.'}, status=404)
    serializer = TaskChargeSerializer(charge, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(TaskChargeReadSerializer(charge).data)
```

Register the URL in `apps/api/urls.py`:

```python
path('jobs/<int:job_pk>/tasks/<int:task_pk>/charge/',
     task_charge_view, name='task-charge'),
```

(Add the import for `task_charge_view` from wherever it lives.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python manage.py test tests.test_task_charge_api -v 2`
Expected: All tests PASS

Note: The test setUp uses `admin_user` / `admin_password` — check the fixture to confirm the correct username/password for the admin user. Adjust if needed.

- [ ] **Step 7: Commit**

```bash
git add apps/api/tasks/serializers.py apps/api/urls.py tests/test_task_charge_api.py
git commit -m "feat: add TaskCharge API and nested serializer on task detail"
```

---

### Task 6: Update TaskTemplate model + serializer

**Files:**
- Modify: `apps/estimates/models.py:480-509` (TaskTemplate class)
- Modify: `apps/api/templates_config/serializers.py:10-19`
- Test: `tests/test_rate_scheme.py` (add TaskTemplate tests)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_rate_scheme.py`:

```python
from apps.estimates.models import TaskTemplate


class TaskTemplateRateSchemeTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.scheme = RateScheme.objects.create(
            name='Hourly Labor',
            algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45.00'),
            unit_label='hour',
            modifiers=[
                {'key': 'messy', 'label': 'Messy', 'percent': 10},
            ],
        )

    def test_task_template_with_rate_scheme(self):
        tmpl = TaskTemplate.objects.create(
            template_name='Assembly',
            rate_scheme=self.scheme,
            default_active_modifiers=['messy'],
            default_billable_qty=Decimal('4.00'),
        )
        self.assertEqual(tmpl.rate_scheme, self.scheme)
        self.assertEqual(tmpl.default_active_modifiers, ['messy'])
        self.assertEqual(tmpl.default_billable_qty, Decimal('4.00'))

    def test_task_template_without_rate_scheme(self):
        tmpl = TaskTemplate.objects.create(
            template_name='Legacy Template',
        )
        self.assertIsNone(tmpl.rate_scheme)
        self.assertEqual(tmpl.default_active_modifiers, [])
        self.assertIsNone(tmpl.default_billable_qty)

    def test_task_template_api_includes_rate_scheme(self):
        tmpl = TaskTemplate.objects.create(
            template_name='Assembly',
            rate_scheme=self.scheme,
            default_active_modifiers=['messy'],
            default_billable_qty=Decimal('4.00'),
        )
        self.client.login(username='admin_user', password='admin_password')
        resp = self.client.get(f'/api/task-templates/{tmpl.pk}/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['rate_scheme'], self.scheme.pk)
        self.assertEqual(data['default_active_modifiers'], ['messy'])
        self.assertEqual(data['default_billable_qty'], '4.00')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_rate_scheme.TaskTemplateRateSchemeTest -v 2`
Expected: FAIL — field does not exist on TaskTemplate

- [ ] **Step 3: Add fields to TaskTemplate model**

In `apps/estimates/models.py`, modify the TaskTemplate class (around line 480). Add after `rate`:

```python
    rate_scheme = models.ForeignKey(
        'jobs.RateScheme',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text="Default billing scheme for tasks from this template"
    )
    default_active_modifiers = models.JSONField(
        default=list, blank=True,
        help_text="Pre-checked modifier keys from the scheme"
    )
    default_billable_qty = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Typical estimated billable quantity"
    )
```

- [ ] **Step 4: Create migration**

Run: `python manage.py makemigrations estimates --name tasktemplate_rate_scheme`

- [ ] **Step 5: Update serializer**

In `apps/api/templates_config/serializers.py`, update `TaskTemplateSerializer`:

```python
class TaskTemplateSerializer(serializers.ModelSerializer):
    units = UnitsField()

    class Meta:
        model = TaskTemplate
        fields = [
            'template_id', 'template_name', 'description',
            'units', 'rate', 'accounting_category', 'is_active',
            'rate_scheme', 'default_active_modifiers', 'default_billable_qty',
        ]
        read_only_fields = ['template_id']
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python manage.py test tests.test_rate_scheme.TaskTemplateRateSchemeTest -v 2`
Expected: All tests PASS

Note: Check fixture credentials — `admin_user` and `admin_password` must match the fixture data. Adjust if fixtures use `dev_user` / `dev_password` or similar.

- [ ] **Step 7: Commit**

```bash
git add apps/estimates/models.py apps/estimates/migrations/ apps/api/templates_config/serializers.py tests/test_rate_scheme.py
git commit -m "feat: add rate_scheme fields to TaskTemplate"
```

---

### Task 7: Update fixtures

**Files:**
- Modify: `fixtures/unit_test_data.json`

- [ ] **Step 1: Add RateScheme entries to fixtures**

Add the following entries to `fixtures/unit_test_data.json`. Insert them before the `estimates.tasktemplate` entries (since templates will reference them):

```json
{
    "model": "jobs.ratescheme",
    "pk": 1,
    "fields": {
        "name": "Hourly Labor",
        "description": "Standard hourly rate for bench work",
        "algorithm": "elapsed_time",
        "rate": "45.00",
        "unit_label": "hour",
        "minimum_charge": null,
        "modifiers": [],
        "accounting_category": null
    }
},
{
    "model": "jobs.ratescheme",
    "pk": 2,
    "fields": {
        "name": "CNC Router",
        "description": "Per-minute CNC charge with optional modifiers",
        "algorithm": "entered_qty",
        "rate": "4.00",
        "unit_label": "minute",
        "minimum_charge": "20.00",
        "modifiers": [
            {"key": "messy", "label": "Messy materials", "percent": 10},
            {"key": "doublestick", "label": "Doublestick tape", "percent": 5}
        ],
        "accounting_category": null
    }
},
{
    "model": "jobs.ratescheme",
    "pk": 3,
    "fields": {
        "name": "Setup Fee",
        "description": "Flat setup charge",
        "algorithm": "flat_fee",
        "rate": "50.00",
        "unit_label": "job",
        "minimum_charge": null,
        "modifiers": [],
        "accounting_category": null
    }
}
```

- [ ] **Step 2: Run the full test suite to confirm fixtures load**

Run: `python manage.py test -v 2`
Expected: All existing tests still PASS (new fixture entries don't break anything)

- [ ] **Step 3: Commit**

```bash
git add fixtures/unit_test_data.json
git commit -m "feat: add RateScheme entries to test fixtures"
```

---

### Task 8: RateScheme Settings UI (Svelte)

**Files:**
- Create: `frontend/src/components/RateSchemeManager.svelte`
- Modify: `frontend/src/routes/SettingsPage.svelte`

- [ ] **Step 1: Create RateSchemeManager component**

```svelte
<!-- frontend/src/components/RateSchemeManager.svelte -->
<script>
  import { api } from '../lib/api.js';

  let schemes = $state([]);
  let loading = $state(true);
  let error = $state('');
  let editingId = $state(null);
  let form = $state(emptyForm());
  let saving = $state(false);
  let saveError = $state('');

  const ALGORITHM_LABELS = {
    elapsed_time: 'Based on time worked',
    entered_qty: 'Worker enters quantity',
    flat_fee: 'Fixed charge',
  };

  function emptyForm() {
    return {
      name: '', description: '', algorithm: 'elapsed_time',
      rate: '', unit_label: 'hour', minimum_charge: '',
      modifiers: [], accounting_category: '',
    };
  }

  async function load() {
    loading = true;
    error = '';
    try {
      const resp = await api.get('/api/rate-schemes/');
      schemes = resp.results || resp;
    } catch (e) {
      error = e.message || 'Could not load rate schemes.';
    } finally {
      loading = false;
    }
  }

  function startCreate() {
    form = emptyForm();
    editingId = 'new';
    saveError = '';
  }

  function startEdit(scheme) {
    form = {
      name: scheme.name,
      description: scheme.description || '',
      algorithm: scheme.algorithm,
      rate: scheme.rate,
      unit_label: scheme.unit_label,
      minimum_charge: scheme.minimum_charge || '',
      modifiers: [...(scheme.modifiers || [])],
      accounting_category: scheme.accounting_category || '',
    };
    editingId = scheme.rate_scheme_id;
    saveError = '';
  }

  function cancelEdit() {
    editingId = null;
    saveError = '';
  }

  function addModifier() {
    form.modifiers = [...form.modifiers, { key: '', label: '', percent: '' }];
  }

  function removeModifier(index) {
    form.modifiers = form.modifiers.filter((_, i) => i !== index);
  }

  function slugify(str) {
    return str.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
  }

  async function save() {
    saving = true;
    saveError = '';
    try {
      const payload = {
        name: form.name,
        description: form.description,
        algorithm: form.algorithm,
        rate: form.rate,
        unit_label: form.unit_label,
        minimum_charge: form.minimum_charge || null,
        modifiers: form.modifiers.map(m => ({
          key: m.key || slugify(m.label),
          label: m.label,
          percent: Number(m.percent),
        })),
        accounting_category: form.accounting_category || null,
      };

      if (editingId === 'new') {
        await api.post('/api/rate-schemes/', payload);
      } else {
        await api.patch(`/api/rate-schemes/${editingId}/`, payload);
      }
      editingId = null;
      await load();
    } catch (e) {
      if (e.data && typeof e.data === 'object') {
        saveError = Object.entries(e.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        saveError = e.message || 'Could not save.';
      }
    } finally {
      saving = false;
    }
  }

  async function remove(scheme) {
    if (!confirm(`Delete rate scheme "${scheme.name}"?`)) return;
    try {
      await api.delete(`/api/rate-schemes/${scheme.rate_scheme_id}/`);
      await load();
    } catch (e) {
      error = e.message || 'Could not delete.';
    }
  }

  const previewTotal = $derived.by(() => {
    if (!form.rate) return null;
    const rate = Number(form.rate);
    const modPct = form.modifiers.reduce((sum, m) => sum + (Number(m.percent) || 0), 0);
    const effRate = rate * (1 + modPct / 100);
    const qty = 10;
    return { qty, effRate: effRate.toFixed(2), total: (qty * effRate).toFixed(2) };
  });

  load();
</script>

<h3>Rate Schemes</h3>

{#if error}<p><em>{error}</em></p>{/if}
{#if loading}<p>Loading...</p>{/if}

{#if !loading && editingId === null}
  <table border="1">
    <thead>
      <tr>
        <th>Name</th><th>Type</th><th>Rate</th><th>Unit</th>
        <th>Modifiers</th><th></th>
      </tr>
    </thead>
    <tbody>
      {#each schemes as s (s.rate_scheme_id)}
        <tr>
          <td>{s.name}</td>
          <td>{ALGORITHM_LABELS[s.algorithm] || s.algorithm}</td>
          <td>${s.rate}/{s.unit_label}</td>
          <td>{s.unit_label}</td>
          <td>{(s.modifiers || []).length}</td>
          <td>
            <button type="button" onclick={() => startEdit(s)}>Edit</button>
            <button type="button" onclick={() => remove(s)}>Delete</button>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
  <p><button type="button" onclick={startCreate}>Add Rate Scheme</button></p>
{/if}

{#if editingId !== null}
  <fieldset>
    <legend><strong>{editingId === 'new' ? 'New Rate Scheme' : 'Edit Rate Scheme'}</strong></legend>
    <p><label><strong>Name *</strong><br>
      <input type="text" bind:value={form.name} style="width:100%;box-sizing:border-box;">
    </label></p>
    <p><label><strong>Description</strong><br>
      <textarea bind:value={form.description} style="width:100%;box-sizing:border-box;"></textarea>
    </label></p>
    <p><label><strong>Algorithm *</strong><br>
      <select bind:value={form.algorithm}>
        <option value="elapsed_time">Based on time worked</option>
        <option value="entered_qty">Worker enters quantity</option>
        <option value="flat_fee">Fixed charge</option>
      </select>
    </label></p>
    <p><label><strong>Rate *</strong><br>
      <input type="number" step="0.01" bind:value={form.rate}>
    </label>
    <label><strong>Unit label *</strong><br>
      <input type="text" bind:value={form.unit_label} placeholder="hour, minute, piece, job">
    </label></p>
    <p><label><strong>Minimum charge</strong><br>
      <input type="number" step="0.01" bind:value={form.minimum_charge}>
    </label></p>

    <fieldset>
      <legend><strong>Modifiers</strong></legend>
      {#each form.modifiers as mod, i}
        <p>
          <input type="text" bind:value={mod.label} placeholder="Label">
          <input type="number" step="0.1" bind:value={mod.percent} placeholder="%" style="width:60px;">%
          <button type="button" onclick={() => removeModifier(i)}>Remove</button>
        </p>
      {/each}
      <p><button type="button" onclick={addModifier}>Add modifier</button></p>
    </fieldset>

    {#if previewTotal}
      <p><strong>Preview:</strong>
        {previewTotal.qty} {form.unit_label}s @ ${previewTotal.effRate}/{form.unit_label} = ${previewTotal.total}
      </p>
    {/if}

    <p>
      <button type="button" onclick={save} disabled={saving}>
        {saving ? 'Saving...' : 'Save'}
      </button>
      <button type="button" onclick={cancelEdit} disabled={saving}>Cancel</button>
    </p>
    {#if saveError}<p><em style="color:#a8071a">{saveError}</em></p>{/if}
  </fieldset>
{/if}
```

- [ ] **Step 2: Add to SettingsPage**

In `frontend/src/routes/SettingsPage.svelte`, add import and component:

```svelte
<script>
  import RateSchemeManager from '../components/RateSchemeManager.svelte';
  // ... existing imports ...
</script>

<!-- Add after UnitsManager -->
<RateSchemeManager />
```

- [ ] **Step 3: Test in browser**

Run: `cd frontend && npm run dev`
Open: `http://localhost:9000/#/settings`

Verify:
- Rate Schemes section appears
- Can create a new scheme with modifiers
- Can edit an existing scheme
- Can delete a scheme
- Live preview updates as rate/modifiers change

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/RateSchemeManager.svelte frontend/src/routes/SettingsPage.svelte
git commit -m "feat: add RateScheme settings UI"
```

---

### Task 9: TaskTemplate Settings UI (Svelte)

**Files:**
- Create: `frontend/src/components/TaskTemplateManager.svelte`
- Modify: `frontend/src/routes/SettingsPage.svelte`

- [ ] **Step 1: Create TaskTemplateManager component**

```svelte
<!-- frontend/src/components/TaskTemplateManager.svelte -->
<script>
  import { api } from '../lib/api.js';

  let templates = $state([]);
  let schemes = $state([]);
  let categories = $state([]);
  let loading = $state(true);
  let error = $state('');
  let editingId = $state(null);
  let form = $state(emptyForm());
  let saving = $state(false);
  let saveError = $state('');

  function emptyForm() {
    return {
      template_name: '', description: '', rate_scheme: '',
      default_active_modifiers: [], default_billable_qty: '',
      accounting_category: '', is_active: true,
    };
  }

  async function load() {
    loading = true;
    error = '';
    try {
      const [tmplResp, schemeResp, catResp] = await Promise.all([
        api.get('/api/task-templates/'),
        api.get('/api/rate-schemes/'),
        api.get('/api/accounting-categories/'),
      ]);
      templates = tmplResp.results || tmplResp;
      schemes = schemeResp.results || schemeResp;
      categories = catResp.results || catResp;
    } catch (e) {
      error = e.message || 'Could not load.';
    } finally {
      loading = false;
    }
  }

  const selectedScheme = $derived(
    schemes.find(s => s.rate_scheme_id === Number(form.rate_scheme)) || null
  );

  function startCreate() {
    form = emptyForm();
    editingId = 'new';
    saveError = '';
  }

  function startEdit(tmpl) {
    form = {
      template_name: tmpl.template_name,
      description: tmpl.description || '',
      rate_scheme: tmpl.rate_scheme || '',
      default_active_modifiers: [...(tmpl.default_active_modifiers || [])],
      default_billable_qty: tmpl.default_billable_qty || '',
      accounting_category: tmpl.accounting_category || '',
      is_active: tmpl.is_active,
    };
    editingId = tmpl.template_id;
    saveError = '';
  }

  function cancelEdit() { editingId = null; saveError = ''; }

  function toggleModifier(key) {
    if (form.default_active_modifiers.includes(key)) {
      form.default_active_modifiers = form.default_active_modifiers.filter(k => k !== key);
    } else {
      form.default_active_modifiers = [...form.default_active_modifiers, key];
    }
  }

  async function save() {
    saving = true;
    saveError = '';
    try {
      const payload = {
        template_name: form.template_name,
        description: form.description,
        rate_scheme: form.rate_scheme || null,
        default_active_modifiers: form.default_active_modifiers,
        default_billable_qty: form.default_billable_qty || null,
        accounting_category: form.accounting_category || null,
        is_active: form.is_active,
      };
      if (editingId === 'new') {
        await api.post('/api/task-templates/', payload);
      } else {
        await api.patch(`/api/task-templates/${editingId}/`, payload);
      }
      editingId = null;
      await load();
    } catch (e) {
      if (e.data && typeof e.data === 'object') {
        saveError = Object.entries(e.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        saveError = e.message || 'Could not save.';
      }
    } finally {
      saving = false;
    }
  }

  async function remove(tmpl) {
    if (!confirm(`Delete template "${tmpl.template_name}"?`)) return;
    try {
      await api.delete(`/api/task-templates/${tmpl.template_id}/`);
      await load();
    } catch (e) {
      error = e.message || 'Could not delete.';
    }
  }

  load();
</script>

<h3>Task Templates</h3>

{#if error}<p><em>{error}</em></p>{/if}
{#if loading}<p>Loading...</p>{/if}

{#if !loading && editingId === null}
  <table border="1">
    <thead>
      <tr><th>Name</th><th>Rate Scheme</th><th>Default Qty</th><th>Active</th><th></th></tr>
    </thead>
    <tbody>
      {#each templates as t (t.template_id)}
        {@const scheme = schemes.find(s => s.rate_scheme_id === t.rate_scheme)}
        <tr>
          <td>{t.template_name}</td>
          <td>{scheme ? scheme.name : '—'}</td>
          <td>{t.default_billable_qty || '—'}</td>
          <td>{t.is_active ? 'Yes' : 'No'}</td>
          <td>
            <button type="button" onclick={() => startEdit(t)}>Edit</button>
            <button type="button" onclick={() => remove(t)}>Delete</button>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
  <p><button type="button" onclick={startCreate}>Add Template</button></p>
{/if}

{#if editingId !== null}
  <fieldset>
    <legend><strong>{editingId === 'new' ? 'New Task Template' : 'Edit Task Template'}</strong></legend>
    <p><label><strong>Name *</strong><br>
      <input type="text" bind:value={form.template_name} style="width:100%;box-sizing:border-box;">
    </label></p>
    <p><label><strong>Description</strong><br>
      <textarea bind:value={form.description} style="width:100%;box-sizing:border-box;"></textarea>
    </label></p>
    <p><label><strong>Rate Scheme</strong><br>
      <select bind:value={form.rate_scheme}>
        <option value="">-- None --</option>
        {#each schemes as s (s.rate_scheme_id)}
          <option value={s.rate_scheme_id}>{s.name} ({s.algorithm})</option>
        {/each}
      </select>
    </label></p>

    {#if selectedScheme && selectedScheme.modifiers.length > 0}
      <fieldset>
        <legend><strong>Default Modifiers</strong></legend>
        {#each selectedScheme.modifiers as mod}
          <label>
            <input type="checkbox"
              checked={form.default_active_modifiers.includes(mod.key)}
              onchange={() => toggleModifier(mod.key)}>
            {mod.label} (+{mod.percent}%)
          </label><br>
        {/each}
      </fieldset>
    {/if}

    {#if selectedScheme}
      <p><label><strong>Default estimated qty ({selectedScheme.unit_label}s)</strong><br>
        <input type="number" step="0.01" bind:value={form.default_billable_qty}>
      </label></p>
    {/if}

    <p><label><strong>Accounting Category</strong><br>
      <select bind:value={form.accounting_category}>
        <option value="">-- None --</option>
        {#each categories as cat (cat.id)}
          <option value={cat.id}>{cat.code} — {cat.name}</option>
        {/each}
      </select>
    </label></p>

    <p><label>
      <input type="checkbox" bind:checked={form.is_active}> Active
    </label></p>

    <p>
      <button type="button" onclick={save} disabled={saving}>
        {saving ? 'Saving...' : 'Save'}
      </button>
      <button type="button" onclick={cancelEdit} disabled={saving}>Cancel</button>
    </p>
    {#if saveError}<p><em style="color:#a8071a">{saveError}</em></p>{/if}
  </fieldset>
{/if}
```

- [ ] **Step 2: Add to SettingsPage**

In `frontend/src/routes/SettingsPage.svelte`, add:

```svelte
<script>
  import TaskTemplateManager from '../components/TaskTemplateManager.svelte';
  // ... existing imports ...
</script>

<!-- Add after RateSchemeManager -->
<TaskTemplateManager />
```

- [ ] **Step 3: Test in browser**

Open: `http://localhost:9000/#/settings`

Verify:
- Task Templates section appears below Rate Schemes
- Can create template with rate scheme selection
- Modifier checkboxes appear when a scheme with modifiers is selected
- Checkboxes refresh when scheme selection changes
- Can edit and delete templates

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/TaskTemplateManager.svelte frontend/src/routes/SettingsPage.svelte
git commit -m "feat: add TaskTemplate settings UI with scheme-driven modifiers"
```

---

## Phase 2: Worksheet + Task UI

### Task 10: Update PlanTaskModal for charge creation

**Files:**
- Modify: `frontend/src/components/PlanTaskModal.svelte`

- [ ] **Step 1: Update PlanTaskModal**

Replace the content of `frontend/src/components/PlanTaskModal.svelte` with the updated version that creates PlanCharges when a template with a RateScheme is selected. Key changes:

- When `createMode === 'template'` and a template is selected, fetch the template's rate scheme and show modifier checkboxes + estimated qty + live charge preview
- On save in template mode: create PlanTask, then create PlanCharge via API
- Freeform mode: add optional RateScheme dropdown; if selected, show modifiers + qty

The full component code follows the same modal pattern as the existing version. The key additions to the template section:

After the template `<select>`, add scheme info and modifier checkboxes:

```svelte
{#if selectedTemplate?.rate_scheme}
  {@const scheme = selectedScheme}
  {#if scheme}
    <p><strong>{scheme.name}</strong> — ${scheme.rate}/{scheme.unit_label}
      ({scheme.algorithm === 'elapsed_time' ? 'Based on time worked' :
        scheme.algorithm === 'entered_qty' ? 'Worker enters quantity' : 'Fixed charge'})
    </p>
    {#if scheme.modifiers.length > 0}
      <fieldset>
        <legend><strong>Modifiers</strong></legend>
        {#each scheme.modifiers as mod}
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
      <label><strong>Estimated {scheme.unit_label}s</strong><br>
        <input type="number" step="0.01" bind:value={estQty}>
      </label>
    </p>
    {#if chargePreview !== null}
      <p><strong>Estimated charge:</strong> ${chargePreview}</p>
    {/if}
  {/if}
{/if}
```

Add state variables:

```javascript
let schemes = $state([]);
let activeModifiers = $state([]);

const selectedTemplate = $derived(
  templates.find(t => String(t.template_id) === String(templateId)) || null
);
const selectedScheme = $derived(
  selectedTemplate?.rate_scheme
    ? schemes.find(s => s.rate_scheme_id === selectedTemplate.rate_scheme)
    : null
);
const chargePreview = $derived.by(() => {
  if (!selectedScheme || !estQty) return null;
  const rate = Number(selectedScheme.rate);
  const modPct = selectedScheme.modifiers
    .filter(m => activeModifiers.includes(m.key))
    .reduce((sum, m) => sum + m.percent, 0);
  const effRate = rate * (1 + modPct / 100);
  return (Number(estQty) * effRate).toFixed(2);
});

function toggleModifier(key) {
  if (activeModifiers.includes(key)) {
    activeModifiers = activeModifiers.filter(k => k !== key);
  } else {
    activeModifiers = [...activeModifiers, key];
  }
}
```

Load schemes on mount:

```javascript
$effect(() => {
  if (open) {
    api.get('/api/rate-schemes/').then(resp => {
      schemes = resp.results || resp;
    });
  }
});
```

When template is selected, pre-fill modifiers from template defaults:

```javascript
$effect(() => {
  if (selectedTemplate) {
    activeModifiers = [...(selectedTemplate.default_active_modifiers || [])];
    if (selectedTemplate.default_billable_qty && !estQty) {
      estQty = selectedTemplate.default_billable_qty;
    }
  }
});
```

Update the save function's template mode to create PlanCharge after PlanTask:

```javascript
// In the template branch of save():
const taskResp = await api.post(`/api/est-worksheets/${worksheetId}/add-from-template/`, {
  task_template_id: Number(templateId),
  est_qty: estQty || null,
});

// If scheme exists, create PlanCharge
if (selectedScheme && taskResp?.plan_task_id) {
  await api.post(`/api/est-worksheets/${worksheetId}/plan-tasks/${taskResp.plan_task_id}/charge/`, {
    rate_scheme: selectedScheme.rate_scheme_id,
    active_modifiers: activeModifiers,
    estimated_billable_qty: estQty || '0',
  });
}
```

Note: The PlanCharge API endpoint needs to be implemented — add a view similar to `task_charge_view` for plan tasks. Register it in `apps/api/urls.py`:

```python
path('est-worksheets/<int:ws_pk>/plan-tasks/<int:pt_pk>/charge/',
     plan_charge_view, name='plan-charge'),
```

- [ ] **Step 2: Create PlanCharge API view**

Add to the appropriate views file (e.g., `apps/api/plan_tasks/views.py` or a new file):

```python
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status
from apps.jobs.models import PlanTask, PlanCharge
from apps.api.permissions import CanManageJobs


class PlanChargeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanCharge
        fields = [
            'plan_charge_id', 'rate_scheme', 'active_modifiers',
            'estimated_billable_qty',
        ]
        read_only_fields = ['plan_charge_id']


@api_view(['GET', 'POST', 'PATCH'])
@permission_classes([IsAuthenticated])
def plan_charge_view(request, ws_pk, pt_pk):
    try:
        plan_task = PlanTask.objects.get(pk=pt_pk, est_worksheet_id=ws_pk)
    except PlanTask.DoesNotExist:
        return Response({'detail': 'Plan task not found.'}, status=404)

    if request.method == 'GET':
        try:
            charge = plan_task.charge
        except PlanCharge.DoesNotExist:
            return Response(None)
        return Response(PlanChargeSerializer(charge).data)

    if not request.user.has_perm('core.can_manage_jobs'):
        return Response(status=403)

    if request.method == 'POST':
        try:
            plan_task.charge
            return Response(
                {'detail': 'Charge already exists. Use PATCH to update.'},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        except PlanCharge.DoesNotExist:
            pass
        serializer = PlanChargeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(plan_task=plan_task)
        return Response(serializer.data, status=http_status.HTTP_201_CREATED)

    # PATCH
    try:
        charge = plan_task.charge
    except PlanCharge.DoesNotExist:
        return Response({'detail': 'No charge to update.'}, status=404)
    serializer = PlanChargeSerializer(charge, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)
```

- [ ] **Step 3: Test in browser**

Start both servers. Open a worksheet. Add a task from template. Verify:
- Modifier checkboxes appear if template has a scheme with modifiers
- Estimated charge previews live
- PlanCharge is created (check via API: `GET /api/est-worksheets/{id}/plan-tasks/{id}/charge/`)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/PlanTaskModal.svelte apps/api/plan_tasks/ apps/api/urls.py
git commit -m "feat: PlanTaskModal creates PlanCharge with scheme modifiers"
```

---

### Task 11: Update TaskDetailPage for charge display + actual qty entry

**Files:**
- Modify: `frontend/src/routes/jobs/TaskDetailPage.svelte`

- [ ] **Step 1: Add charge section to TaskDetailPage**

In the `<script>` section, add charge state and loading:

```javascript
let charge = $state(null);

async function loadCharge() {
  if (!task) return;
  try {
    const resp = await api.get(`/api/jobs/${task.job.id}/tasks/${task.task_id}/charge/`);
    charge = resp;
  } catch (e) {
    charge = null;
  }
}

async function saveActualQty(qty) {
  if (!charge || !task) return;
  try {
    await api.patch(`/api/jobs/${task.job.id}/tasks/${task.task_id}/charge/`, {
      actuals: { qty: Number(qty) },
    });
    await loadCharge();
  } catch (e) {
    // handle error
  }
}
```

Call `loadCharge()` after `loadTask()` in the initialization.

In the template, add a charge section after the task info table:

```svelte
{#if charge}
  <h3>Charge</h3>
  <table border="1">
    <tr><td><strong>Scheme</strong></td><td>{charge.scheme_name}</td></tr>
    <tr><td><strong>Rate</strong></td><td>${charge.effective_rate}/{charge.scheme_unit_label}</td></tr>
    {#if charge.active_modifiers.length > 0}
      <tr><td><strong>Modifiers</strong></td>
        <td>{charge.active_modifiers.join(', ')}</td></tr>
    {/if}
    {#if charge.scheme_algorithm === 'entered_qty'}
      <tr><td><strong>Actual {charge.scheme_unit_label}s</strong></td>
        <td>
          <input type="number" step="0.01"
            value={charge.actuals?.qty || ''}
            onchange={(e) => saveActualQty(e.target.value)}>
        </td></tr>
    {/if}
    {#if charge.computed_charge}
      <tr><td><strong>Charge</strong></td><td>${charge.computed_charge}</td></tr>
    {/if}
  </table>
{/if}
```

- [ ] **Step 2: Test in browser**

Navigate to a task detail page for a task that has a TaskCharge. Verify:
- Charge section appears with scheme name, rate, modifiers
- For entered_qty tasks: actual qty input is present and saves
- Computed charge updates after saving

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/jobs/TaskDetailPage.svelte
git commit -m "feat: show charge info and actual qty entry on task detail page"
```

---

### Task 12: Update estimate line item generation to use PlanCharge

**Files:**
- Modify: `apps/estimates/services.py:734-807`
- Test: existing estimate generation tests (add cases)

- [ ] **Step 1: Write the failing test**

Add to the appropriate test file (e.g., `tests/test_rate_scheme.py` or create `tests/test_estimate_charge.py`):

```python
# tests/test_estimate_charge.py
from decimal import Decimal
from tests.base import BaseTestCase
from apps.jobs.models import RateScheme, PlanCharge, PlanTask
from apps.estimates.models import EstWorksheet, Estimate
from apps.estimates.services import EstimateGenerationService


class EstimateFromPlanChargeTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.scheme = RateScheme.objects.create(
            name='CNC Router',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='minute',
            modifiers=[
                {'key': 'messy', 'label': 'Messy', 'percent': 10},
            ],
        )
        # Get a worksheet with plan tasks
        self.worksheet = EstWorksheet.objects.first()
        if self.worksheet is None:
            self.skipTest('No worksheet in fixtures')

    def test_line_item_uses_plan_charge_when_present(self):
        plan_task = self.worksheet.plan_tasks.filter(
            mapping_strategy='direct'
        ).first()
        if plan_task is None:
            self.skipTest('No direct plan task')

        PlanCharge.objects.create(
            plan_task=plan_task,
            rate_scheme=self.scheme,
            active_modifiers=['messy'],
            estimated_billable_qty=Decimal('30.00'),
        )

        service = EstimateGenerationService(self.worksheet)
        line_item = service._create_direct_line_item(plan_task, None)

        # Should use PlanCharge: qty=30, price=4.40 (4.00 * 1.10)
        self.assertEqual(line_item.qty, Decimal('30.00'))
        self.assertEqual(line_item.price, Decimal('4.40'))
        self.assertEqual(line_item.units, 'minute')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_estimate_charge -v 2`
Expected: FAIL — line item uses PlanTask's old fields instead of PlanCharge

- [ ] **Step 3: Update _create_direct_line_item**

In `apps/estimates/services.py`, modify `_create_direct_line_item` (line 734):

```python
    def _create_direct_line_item(self, task, estimate) -> 'EstimateLineItem':
        """Create a line item for a direct-mapped task.
        Uses PlanCharge if available; falls back to task fields."""
        try:
            charge = task.charge
            qty = charge.estimated_billable_qty
            rate = charge.effective_rate()
            units = charge.rate_scheme.unit_label
        except (PlanCharge.DoesNotExist, AttributeError):
            qty = task.est_qty or Decimal('1.00')
            rate = task.rate or Decimal('0.00')
            units = task.units or 'none'

        accounting_category = task.accounting_category
        if accounting_category is None:
            accounting_category = self._get_default_accounting_category()

        line_item = EstimateLineItem(
            estimate=estimate,
            task=task,
            line_number=self.line_number,
            description=task.name,
            qty=qty,
            units=units,
            price=rate,
            accounting_category=accounting_category
        )

        self.line_number += 1
        return line_item
```

Add the import at top of file:

```python
from apps.jobs.models import PlanCharge
```

- [ ] **Step 4: Update _create_bundle_line_item similarly**

In `_create_bundle_line_item` (line 784):

```python
    def _create_bundle_line_item(self, tasks, bundle, estimate) -> 'EstimateLineItem':
        """Create a single line item for bundled tasks, including material costs."""
        total_price = Decimal('0.00')

        for task in tasks:
            try:
                charge = task.charge
                qty = charge.estimated_billable_qty
                rate = charge.effective_rate()
            except (PlanCharge.DoesNotExist, AttributeError):
                qty = task.est_qty or Decimal('1.00')
                rate = task.rate or Decimal('0.00')
            total_price += qty * rate
            for material in task.plan_materials.all():
                total_price += material.total_sell

        line_item = EstimateLineItem(
            estimate=estimate,
            line_number=self.line_number,
            description=bundle.name,
            qty=Decimal('1.00'),
            units='none',
            price=total_price,
            accounting_category=bundle.accounting_category
        )

        self.line_number += 1
        return line_item
```

- [ ] **Step 5: Run tests**

Run: `python manage.py test tests.test_estimate_charge -v 2`
Expected: PASS

Then run full test suite to check for regressions:

Run: `python manage.py test -v 2`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add apps/estimates/services.py tests/test_estimate_charge.py
git commit -m "feat: estimate generation reads billing from PlanCharge when available"
```

---

### Task 13: Remove billing fields from TaskBase (Phase 1 cleanup)

**Deferred.** Do NOT execute this task until Phase 1 and Phase 2 are stable and verified in the browser. Removing `units`, `rate`, `est_qty` from TaskBase is a breaking change that requires:

1. All serializers updated to not reference these fields
2. All services using fallback to old fields verified
3. All frontend components updated to not read these fields
4. Data migration confirmed (all tasks with billing data have Charge objects)

When ready:

- [ ] **Step 1: Grep for remaining references**

```bash
grep -rn 'est_qty\|\.rate\|\.units' apps/ --include='*.py' | grep -v migrations | grep -v '__pycache__'
```

Fix every reference.

- [ ] **Step 2: Remove fields from TaskBase**

In `apps/jobs/models.py`, remove from TaskBase:
- `units = models.CharField(max_length=50, default='none')`
- `rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)`
- `est_qty = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)`

- [ ] **Step 3: Remove from TaskTemplate**

In `apps/estimates/models.py`, remove from TaskTemplate:
- `units = models.CharField(max_length=50, default='none')`
- `rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)`

- [ ] **Step 4: Create migrations**

```bash
python manage.py makemigrations jobs --name remove_taskbase_billing_fields
python manage.py makemigrations estimates --name remove_tasktemplate_billing_fields
```

- [ ] **Step 5: Update all serializers**

Remove `units`, `rate`, `est_qty` from:
- `apps/api/tasks/serializers.py` (TaskSerializer, TaskDetailSerializer)
- `apps/api/plan_tasks/serializers.py` (PlanTaskDetailSerializer)
- `apps/api/templates_config/serializers.py` (TaskTemplateSerializer)

Remove the `UnitsField` import from each.

- [ ] **Step 6: Update frontend components**

Remove references to `units`, `rate`, `est_qty` from:
- `frontend/src/components/PlanTaskModal.svelte`
- Any other components that read these fields

- [ ] **Step 7: Run full test suite**

```bash
python manage.py test -v 2
```

Fix any failures.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: remove billing fields from TaskBase and TaskTemplate"
```

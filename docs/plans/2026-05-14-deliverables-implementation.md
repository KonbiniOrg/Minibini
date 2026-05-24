# Deliverables and Shipments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Deliverables (customer-facing finished-goods list, no prices, on Job) and Shipments (fulfillment events with picked_up/prepared status) as a new `apps/deliverables/` app, with full backend + SPA UI. Change orders are deferred per the spec.

**Architecture:** A new Django app houses three models (`Deliverable`, `Shipment`, `ShipmentItem`) with services for all writes. A new `apps/api/deliverables/` app exposes the REST surface. The SPA adds an always-visible Deliverables column to the Job detail's flex row, a read-only Shipments pillar, and a click-through Job Shipments page with the matrix-table editor. One cross-app change: `EstimateService.mark_open` rejects when the Job has no Deliverables.

**Tech Stack:** Django 5.2, Django REST Framework, MySQL, Python 3.12, Svelte 5 (runes), Vite. Reference design: `docs/plans/2026-05-14-deliverables-design.md`.

**Permissions guarantees the plan relies on**

- `CanManageJobs` for Deliverable writes; `IsAuthenticated` for Deliverable reads.
- `IsAuthenticated` for all Shipment + ShipmentItem operations (reads and writes).
- DELETE responses return HTTP 200 with a JSON body (project-wide convention; SPA `lib/api.js` rejects non-JSON responses).

**Notes for the implementer**

- The dev DB is off-limits. Never run `python manage.py migrate`, never run `loaddata`, never run `shell`/`shell_plus`, never run a script that mutates the DB. `makemigrations` is fine. Test runs are fine — they create and tear down their own DB.
- Never run tests from multiple agents in parallel — MySQL shares one test database; concurrent runs deadlock.
- Use the existing service-layer pattern: viewsets call services; services raise `ValidationError` / `NotFoundError` / `ServiceError`; viewsets translate to HTTP.
- Never call `.delete()` directly on a line-item-style model; use the service path.
- Use model constants (`Estimate.STATUS_DRAFT` etc.), not string literals.
- Wrap multi-row writes in `transaction.atomic()`.

---

## File map

**New backend files:**

```
apps/deliverables/__init__.py                     (empty)
apps/deliverables/apps.py                         (AppConfig)
apps/deliverables/models.py                       (Deliverable, Shipment, ShipmentItem)
apps/deliverables/services.py                     (DeliverableService, ShipmentService)
apps/deliverables/admin.py                        (empty placeholder)
apps/deliverables/migrations/__init__.py          (empty)
apps/deliverables/migrations/0001_initial.py      (generated)

apps/api/deliverables/__init__.py                 (empty)
apps/api/deliverables/serializers.py              (DeliverableSerializer, ShipmentSerializer, ShipmentItemSerializer)
apps/api/deliverables/views.py                    (DeliverableViewSet, ShipmentViewSet, ShipmentItemViewSet)
apps/api/deliverables/urls.py                     (URL wiring for nested routes)
```

**Modified backend files:**

```
minibini/settings.py                              (add apps.deliverables to INSTALLED_APPS)
apps/api/urls.py                                  (register new viewsets and nested routes)
apps/estimates/services.py                        (EstimateService.mark_open: deliverables non-empty guard)
```

**New test files:**

```
tests/test_deliverable_models.py
tests/test_deliverable_service.py
tests/test_shipment_models.py
tests/test_shipment_service.py
tests/test_deliverables_api.py
tests/test_shipments_api.py
tests/test_estimate_mark_open_deliverables_guard.py
```

**New frontend files:**

```
frontend/src/components/jobs/DeliverablesSection.svelte
frontend/src/components/jobs/DeliverablesEditModal.svelte
frontend/src/components/jobs/ShipmentsPillar.svelte
frontend/src/routes/jobs/JobShipmentsPage.svelte
frontend/src/routes/shipments/PackingListPrint.svelte
```

**Modified frontend files:**

```
frontend/src/App.svelte                                            (register two new routes)
frontend/src/components/jobs/JobDetail.svelte                      (three-column flex row, Shipments pillar slot)
```

---

## Phase 0 — App skeleton

### Task 0.1: Create the `apps/deliverables/` package

**Files:**
- Create: `apps/deliverables/__init__.py` (empty)
- Create: `apps/deliverables/apps.py`
- Create: `apps/deliverables/admin.py` (empty placeholder)
- Create: `apps/deliverables/migrations/__init__.py` (empty)

- [ ] **Step 1: Create the empty package files**

Create `apps/deliverables/__init__.py`:

```python
```

(File should be empty — just an empty file.)

Create `apps/deliverables/migrations/__init__.py`:

```python
```

Create `apps/deliverables/admin.py`:

```python
```

- [ ] **Step 2: Create the AppConfig**

Create `apps/deliverables/apps.py`:

```python
from django.apps import AppConfig


class DeliverablesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.deliverables'
    verbose_name = 'Deliverables'
```

- [ ] **Step 3: Register the app in INSTALLED_APPS**

Modify `minibini/settings.py`, INSTALLED_APPS section. Add `'apps.deliverables',` in alphabetical order, placed after `'apps.contacts',` and before `'apps.expenses',`:

```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'apps.core',
    'apps.jobs',
    'apps.estimates',
    'apps.contacts',
    'apps.deliverables',
    'apps.expenses',
    'apps.invoicing',
    'apps.purchasing',
    'apps.search',
    'apps.inventory',
    'apps.qbo',
    'rest_framework',
    'apps.api',
]
```

- [ ] **Step 4: Verify Django can load the app**

Run: `python manage.py check`

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 5: Commit**

```bash
git add apps/deliverables/ minibini/settings.py
git commit -m "feat(deliverables): scaffold apps.deliverables Django app"
```

---

## Phase 1 — Deliverable model

### Task 1.1: Write Deliverable model tests

**Files:**
- Create: `tests/test_deliverable_models.py`

- [ ] **Step 1: Write failing tests for Deliverable**

Create `tests/test_deliverable_models.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable
from apps.jobs.models import Job


class DeliverableModelTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.assertIsNotNone(self.job, 'Fixture must include at least one Job.')

    def test_create_basic_deliverable(self):
        d = Deliverable.objects.create(
            job=self.job,
            description='Walnut stool',
            qty_ordered=Decimal('15'),
            units='ea',
        )
        self.assertEqual(d.job, self.job)
        self.assertEqual(d.description, 'Walnut stool')
        self.assertEqual(d.qty_ordered, Decimal('15'))
        self.assertEqual(d.units, 'ea')
        self.assertIsNotNone(d.sort_order)

    def test_sort_order_auto_assigns_on_save(self):
        a = Deliverable.objects.create(
            job=self.job, description='A', qty_ordered=Decimal('1'), units='ea',
        )
        b = Deliverable.objects.create(
            job=self.job, description='B', qty_ordered=Decimal('1'), units='ea',
        )
        c = Deliverable.objects.create(
            job=self.job, description='C', qty_ordered=Decimal('1'), units='ea',
        )
        self.assertLess(a.sort_order, b.sort_order)
        self.assertLess(b.sort_order, c.sort_order)

    def test_default_ordering_is_sort_order(self):
        a = Deliverable.objects.create(
            job=self.job, description='A', qty_ordered=Decimal('1'), units='ea',
            sort_order=20,
        )
        b = Deliverable.objects.create(
            job=self.job, description='B', qty_ordered=Decimal('1'), units='ea',
            sort_order=10,
        )
        retrieved = list(Deliverable.objects.filter(job=self.job))
        self.assertEqual(retrieved[0].pk, b.pk)
        self.assertEqual(retrieved[1].pk, a.pk)

    def test_db_table_name(self):
        self.assertEqual(Deliverable._meta.db_table, 'deliverables')

    def test_qty_ordered_supports_decimals(self):
        d = Deliverable.objects.create(
            job=self.job, description='Plywood sheet', qty_ordered=Decimal('2.5'),
            units='sheet',
        )
        d.refresh_from_db()
        self.assertEqual(d.qty_ordered, Decimal('2.50'))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_deliverable_models -v 2`

Expected: ImportError on `from apps.deliverables.models import Deliverable` — `Deliverable` doesn't exist yet.

- [ ] **Step 3: Implement the Deliverable model**

Create `apps/deliverables/models.py`:

```python
from django.db import models


class Deliverable(models.Model):
    """A finished item the customer is buying on a Job. No price; quantity + units only."""

    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.CASCADE,
        related_name='deliverables',
    )
    description = models.TextField()
    qty_ordered = models.DecimalField(max_digits=10, decimal_places=2)
    units = models.CharField(max_length=50)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'deliverables'
        ordering = ['sort_order']

    def save(self, *args, **kwargs):
        # Auto-assign next sort_order if unset (mirrors Task.save pattern).
        if not self.pk and not self.sort_order:
            last = Deliverable.objects.filter(job=self.job).order_by('-sort_order').first()
            self.sort_order = (last.sort_order + 10) if last else 10
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.description} (qty {self.qty_ordered} {self.units})'
```

- [ ] **Step 4: Run `makemigrations`**

Run: `python manage.py makemigrations deliverables`

Expected: `Migrations for 'deliverables': apps/deliverables/migrations/0001_initial.py - Create model Deliverable`

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_deliverable_models -v 2`

Expected: All 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/deliverables/models.py apps/deliverables/migrations/ tests/test_deliverable_models.py
git commit -m "feat(deliverables): add Deliverable model"
```

---

## Phase 2 — Shipment and ShipmentItem models

### Task 2.1: Write tests for Shipment and ShipmentItem

**Files:**
- Create: `tests/test_shipment_models.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_shipment_models.py`:

```python
from decimal import Decimal
from django.db import IntegrityError
from django.db import transaction
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable, Shipment, ShipmentItem
from apps.jobs.models import Job


class ShipmentModelTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.deliverable = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )

    def test_default_status_is_prepared(self):
        s = Shipment.objects.create(job=self.job, sequence=1)
        self.assertEqual(s.status, 'prepared')
        self.assertIsNotNone(s.prepared_date)
        self.assertIsNone(s.picked_up_date)

    def test_unique_sequence_per_job(self):
        Shipment.objects.create(job=self.job, sequence=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Shipment.objects.create(job=self.job, sequence=1)

    def test_db_table_name(self):
        self.assertEqual(Shipment._meta.db_table, 'shipments')

    def test_default_ordering_is_sequence(self):
        b = Shipment.objects.create(job=self.job, sequence=20)
        a = Shipment.objects.create(job=self.job, sequence=10)
        retrieved = list(Shipment.objects.filter(job=self.job))
        self.assertEqual(retrieved[0].pk, a.pk)
        self.assertEqual(retrieved[1].pk, b.pk)


class ShipmentItemModelTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.deliverable = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        self.shipment = Shipment.objects.create(job=self.job, sequence=1)

    def test_create_item(self):
        item = ShipmentItem.objects.create(
            shipment=self.shipment, deliverable=self.deliverable, qty=Decimal('5'),
        )
        self.assertEqual(item.shipment, self.shipment)
        self.assertEqual(item.deliverable, self.deliverable)
        self.assertEqual(item.qty, Decimal('5'))

    def test_unique_shipment_deliverable_pair(self):
        ShipmentItem.objects.create(
            shipment=self.shipment, deliverable=self.deliverable, qty=Decimal('5'),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ShipmentItem.objects.create(
                    shipment=self.shipment, deliverable=self.deliverable, qty=Decimal('3'),
                )

    def test_db_table_name(self):
        self.assertEqual(ShipmentItem._meta.db_table, 'shipment_items')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_shipment_models -v 2`

Expected: ImportError on Shipment / ShipmentItem.

- [ ] **Step 3: Add Shipment and ShipmentItem to the models module**

Edit `apps/deliverables/models.py` — append to the file:

```python
from django.utils import timezone


class Shipment(models.Model):
    """A single fulfillment event for a Job. Multiple Shipments per Job for phased delivery."""

    STATUS_PREPARED = 'prepared'
    STATUS_PICKED_UP = 'picked_up'
    STATUS_CHOICES = [
        (STATUS_PREPARED, 'Prepared'),
        (STATUS_PICKED_UP, 'Picked up'),
    ]

    job = models.ForeignKey(
        'jobs.Job',
        on_delete=models.CASCADE,
        related_name='shipments',
    )
    sequence = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PREPARED,
    )
    prepared_date = models.DateTimeField(default=timezone.now)
    picked_up_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'shipments'
        ordering = ['sequence']
        unique_together = [('job', 'sequence')]

    def __str__(self):
        return f'Shipment #{self.sequence} on Job {self.job_id}'


class ShipmentItem(models.Model):
    """A single Deliverable contribution to a Shipment. One row per (shipment, deliverable) pair."""

    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='items',
    )
    deliverable = models.ForeignKey(
        Deliverable,
        on_delete=models.PROTECT,
        related_name='shipment_items',
    )
    qty = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'shipment_items'
        unique_together = [('shipment', 'deliverable')]
        ordering = ['deliverable__sort_order']

    def __str__(self):
        return f'{self.qty} {self.deliverable.units} of {self.deliverable.description}'
```

- [ ] **Step 4: Run `makemigrations`**

Run: `python manage.py makemigrations deliverables`

Expected: A new migration file (`0002_*.py`) is generated, OR `0001_initial.py` updates to include all three models if migrations haven't been applied. Either is fine.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_shipment_models -v 2`

Expected: All 7 tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/deliverables/models.py apps/deliverables/migrations/ tests/test_shipment_models.py
git commit -m "feat(deliverables): add Shipment and ShipmentItem models"
```

---

## Phase 3 — DeliverableService

### Task 3.1: Write tests for editability and basic CRUD

**Files:**
- Create: `tests/test_deliverable_service.py`

- [ ] **Step 1: Write failing tests for editability**

Create `tests/test_deliverable_service.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable
from apps.deliverables.services import DeliverableService
from apps.estimates.models import Estimate
from apps.jobs.models import Job


class DeliverableEditabilityTests(FixtureTestCase):
    """is_editable / editability_reason across estimate states."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        # Wipe any pre-existing estimates from the fixture for this job.
        Estimate.objects.filter(job=self.job).delete()

    def test_editable_when_no_estimate(self):
        self.assertTrue(DeliverableService.is_editable(self.job))
        self.assertIsNone(DeliverableService.editability_reason(self.job))

    def test_editable_when_estimate_is_draft(self):
        Estimate.objects.create(
            job=self.job,
            estimate_number='EST-X-1',
            version=1,
            status=Estimate.STATUS_DRAFT,
        )
        self.assertTrue(DeliverableService.is_editable(self.job))
        self.assertIsNone(DeliverableService.editability_reason(self.job))

    def test_not_editable_when_estimate_is_open(self):
        Estimate.objects.create(
            job=self.job,
            estimate_number='EST-X-2',
            version=1,
            status=Estimate.STATUS_OPEN,
        )
        self.assertFalse(DeliverableService.is_editable(self.job))
        self.assertEqual(DeliverableService.editability_reason(self.job), 'estimate_sent')

    def test_not_editable_when_estimate_is_accepted(self):
        Estimate.objects.create(
            job=self.job,
            estimate_number='EST-X-3',
            version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.assertFalse(DeliverableService.is_editable(self.job))
        self.assertEqual(DeliverableService.editability_reason(self.job), 'estimate_accepted')

    def test_editable_again_after_rejected_estimate(self):
        Estimate.objects.create(
            job=self.job,
            estimate_number='EST-X-4',
            version=1,
            status=Estimate.STATUS_REJECTED,
        )
        # Rejected isn't "active"; D list is editable again.
        self.assertTrue(DeliverableService.is_editable(self.job))


class DeliverableCRUDTests(FixtureTestCase):
    """create / update / delete / reorder, all gated by editability."""

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()

    def test_create_when_editable(self):
        d = DeliverableService.create(
            job_id=self.job.pk,
            description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        self.assertEqual(d.job, self.job)
        self.assertEqual(d.description, 'Stool')

    def test_create_blocked_when_estimate_open(self):
        Estimate.objects.create(
            job=self.job, estimate_number='EST-Y-1', version=1,
            status=Estimate.STATUS_OPEN,
        )
        with self.assertRaises(ValidationError):
            DeliverableService.create(
                job_id=self.job.pk,
                description='Stool', qty_ordered=Decimal('15'), units='ea',
            )

    def test_create_blocked_when_estimate_accepted(self):
        Estimate.objects.create(
            job=self.job, estimate_number='EST-Y-2', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        with self.assertRaises(ValidationError):
            DeliverableService.create(
                job_id=self.job.pk,
                description='Stool', qty_ordered=Decimal('15'), units='ea',
            )

    def test_update_when_editable(self):
        d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        updated = DeliverableService.update(deliverable=d, description='Walnut stool')
        self.assertEqual(updated.description, 'Walnut stool')

    def test_update_blocked_when_estimate_accepted(self):
        d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        Estimate.objects.create(
            job=self.job, estimate_number='EST-Y-3', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        with self.assertRaises(ValidationError):
            DeliverableService.update(deliverable=d, qty_ordered=Decimal('20'))

    def test_delete_when_editable_renumbers_siblings(self):
        a = Deliverable.objects.create(job=self.job, description='A', qty_ordered=Decimal('1'), units='ea', sort_order=10)
        b = Deliverable.objects.create(job=self.job, description='B', qty_ordered=Decimal('1'), units='ea', sort_order=20)
        c = Deliverable.objects.create(job=self.job, description='C', qty_ordered=Decimal('1'), units='ea', sort_order=30)

        DeliverableService.delete(deliverable=b)

        remaining = list(Deliverable.objects.filter(job=self.job).order_by('sort_order'))
        self.assertEqual([r.pk for r in remaining], [a.pk, c.pk])
        self.assertEqual(remaining[0].sort_order, 10)
        self.assertEqual(remaining[1].sort_order, 20)

    def test_reorder_assigns_sequential_sort_orders(self):
        a = Deliverable.objects.create(job=self.job, description='A', qty_ordered=Decimal('1'), units='ea', sort_order=10)
        b = Deliverable.objects.create(job=self.job, description='B', qty_ordered=Decimal('1'), units='ea', sort_order=20)
        c = Deliverable.objects.create(job=self.job, description='C', qty_ordered=Decimal('1'), units='ea', sort_order=30)

        DeliverableService.reorder(job=self.job, ordered_ids=[c.pk, a.pk, b.pk])

        retrieved = list(Deliverable.objects.filter(job=self.job).order_by('sort_order'))
        self.assertEqual([r.pk for r in retrieved], [c.pk, a.pk, b.pk])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_deliverable_service -v 2`

Expected: ImportError on `from apps.deliverables.services import DeliverableService`.

- [ ] **Step 3: Implement DeliverableService**

Create `apps/deliverables/services.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from apps.deliverables.models import Deliverable
from apps.estimates.models import Estimate


# Estimate statuses that are terminal/inactive — these don't count when
# computing "latest active estimate".
_INACTIVE_ESTIMATE_STATUSES = {
    Estimate.STATUS_SUPERSEDED,
    Estimate.STATUS_REJECTED,
}


def _latest_active_estimate(job):
    return (
        Estimate.objects.filter(job=job)
        .exclude(status__in=_INACTIVE_ESTIMATE_STATUSES)
        .order_by('-version', '-pk')
        .first()
    )


def _any_accepted_estimate(job):
    return Estimate.objects.filter(
        job=job, status=Estimate.STATUS_ACCEPTED,
    ).exists()


class DeliverableService:
    """Business-logic façade for the Deliverable model."""

    @staticmethod
    def is_editable(job):
        if _any_accepted_estimate(job):
            return False
        latest = _latest_active_estimate(job)
        if latest is None:
            return True
        return latest.status == Estimate.STATUS_DRAFT

    @staticmethod
    def editability_reason(job):
        if _any_accepted_estimate(job):
            return 'estimate_accepted'
        latest = _latest_active_estimate(job)
        if latest is None or latest.status == Estimate.STATUS_DRAFT:
            return None
        if latest.status == Estimate.STATUS_OPEN:
            return 'estimate_sent'
        return None

    @staticmethod
    def _assert_editable(job):
        if not DeliverableService.is_editable(job):
            raise ValidationError('Deliverables list is not editable in the current state.')

    @staticmethod
    @transaction.atomic
    def create(*, job_id, description, qty_ordered, units, sort_order=None):
        from apps.jobs.models import Job
        job = Job.objects.get(pk=job_id)
        DeliverableService._assert_editable(job)
        d = Deliverable(
            job=job,
            description=description,
            qty_ordered=qty_ordered,
            units=units,
        )
        if sort_order is not None:
            d.sort_order = sort_order
        d.full_clean()
        d.save()
        return d

    @staticmethod
    @transaction.atomic
    def update(*, deliverable, **fields):
        DeliverableService._assert_editable(deliverable.job)
        allowed = {'description', 'qty_ordered', 'units', 'sort_order'}
        for field, value in fields.items():
            if field not in allowed:
                raise ValidationError(f'Field {field!r} is not updatable.')
            setattr(deliverable, field, value)
        deliverable.full_clean()
        deliverable.save()
        return deliverable

    @staticmethod
    @transaction.atomic
    def delete(*, deliverable):
        DeliverableService._assert_editable(deliverable.job)
        job = deliverable.job
        deliverable.delete()
        # Renumber surviving siblings, preserving relative order.
        remaining = list(
            Deliverable.objects.filter(job=job).order_by('sort_order', 'pk')
        )
        for idx, item in enumerate(remaining, start=1):
            new_sort = idx * 10
            if item.sort_order != new_sort:
                item.sort_order = new_sort
                item.save(update_fields=['sort_order', 'updated_at'])

    @staticmethod
    @transaction.atomic
    def reorder(*, job, ordered_ids):
        DeliverableService._assert_editable(job)
        for idx, pk in enumerate(ordered_ids, start=1):
            Deliverable.objects.filter(pk=pk, job=job).update(sort_order=idx * 10)
        return list(
            Deliverable.objects.filter(job=job).order_by('sort_order')
        )

    @staticmethod
    def compute_fulfillment(deliverable):
        from apps.deliverables.models import ShipmentItem, Shipment
        items = ShipmentItem.objects.filter(deliverable=deliverable).select_related('shipment')
        picked_up = Decimal('0')
        prepped = Decimal('0')
        for item in items:
            if item.shipment.status == Shipment.STATUS_PICKED_UP:
                picked_up += item.qty
            elif item.shipment.status == Shipment.STATUS_PREPARED:
                prepped += item.qty
        return {
            'qty_ordered': deliverable.qty_ordered,
            'qty_picked_up': picked_up,
            'qty_prepped': prepped,
            'qty_remaining': deliverable.qty_ordered - picked_up - prepped,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_deliverable_service -v 2`

Expected: All 13 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/deliverables/services.py tests/test_deliverable_service.py
git commit -m "feat(deliverables): add DeliverableService with editability and CRUD"
```

### Task 3.2: Add compute_fulfillment tests

**Files:**
- Modify: `tests/test_deliverable_service.py` (append)

- [ ] **Step 1: Append fulfillment tests**

Append to `tests/test_deliverable_service.py`:

```python
from apps.deliverables.models import Shipment, ShipmentItem


class ComputeFulfillmentTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        Estimate.objects.create(
            job=self.job, estimate_number='EST-CF-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )

    def test_no_shipments_remaining_equals_ordered(self):
        f = DeliverableService.compute_fulfillment(self.d)
        self.assertEqual(f['qty_ordered'], Decimal('15'))
        self.assertEqual(f['qty_picked_up'], Decimal('0'))
        self.assertEqual(f['qty_prepped'], Decimal('0'))
        self.assertEqual(f['qty_remaining'], Decimal('15'))

    def test_picked_up_reduces_remaining(self):
        s = Shipment.objects.create(job=self.job, sequence=1, status=Shipment.STATUS_PICKED_UP)
        ShipmentItem.objects.create(shipment=s, deliverable=self.d, qty=Decimal('10'))
        f = DeliverableService.compute_fulfillment(self.d)
        self.assertEqual(f['qty_picked_up'], Decimal('10'))
        self.assertEqual(f['qty_remaining'], Decimal('5'))

    def test_prepared_counts_separately(self):
        s_done = Shipment.objects.create(job=self.job, sequence=1, status=Shipment.STATUS_PICKED_UP)
        ShipmentItem.objects.create(shipment=s_done, deliverable=self.d, qty=Decimal('7'))
        s_prep = Shipment.objects.create(job=self.job, sequence=2, status=Shipment.STATUS_PREPARED)
        ShipmentItem.objects.create(shipment=s_prep, deliverable=self.d, qty=Decimal('3'))

        f = DeliverableService.compute_fulfillment(self.d)
        self.assertEqual(f['qty_picked_up'], Decimal('7'))
        self.assertEqual(f['qty_prepped'], Decimal('3'))
        self.assertEqual(f['qty_remaining'], Decimal('5'))
```

- [ ] **Step 2: Run tests**

Run: `python manage.py test tests.test_deliverable_service.ComputeFulfillmentTests -v 2`

Expected: All 3 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_deliverable_service.py
git commit -m "test(deliverables): cover compute_fulfillment scenarios"
```

---

## Phase 4 — ShipmentService

### Task 4.1: Write tests for shipment lifecycle and gating

**Files:**
- Create: `tests/test_shipment_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_shipment_service.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable, Shipment, ShipmentItem
from apps.deliverables.services import ShipmentService
from apps.estimates.models import Estimate
from apps.jobs.models import Job


def _job_with_accepted_estimate():
    job = Job.objects.first()
    Estimate.objects.filter(job=job).delete()
    Estimate.objects.create(
        job=job, estimate_number='EST-S-1', version=1,
        status=Estimate.STATUS_ACCEPTED,
    )
    return job


class ShipmentCreateGatingTests(FixtureTestCase):

    def test_create_blocked_when_no_estimate(self):
        job = Job.objects.first()
        Estimate.objects.filter(job=job).delete()
        with self.assertRaises(ValidationError):
            ShipmentService.create(job_id=job.pk)

    def test_create_blocked_when_estimate_draft(self):
        job = Job.objects.first()
        Estimate.objects.filter(job=job).delete()
        Estimate.objects.create(
            job=job, estimate_number='EST-S-2', version=1,
            status=Estimate.STATUS_DRAFT,
        )
        with self.assertRaises(ValidationError):
            ShipmentService.create(job_id=job.pk)

    def test_create_blocked_when_estimate_open(self):
        job = Job.objects.first()
        Estimate.objects.filter(job=job).delete()
        Estimate.objects.create(
            job=job, estimate_number='EST-S-3', version=1,
            status=Estimate.STATUS_OPEN,
        )
        with self.assertRaises(ValidationError):
            ShipmentService.create(job_id=job.pk)

    def test_create_succeeds_when_estimate_accepted(self):
        job = _job_with_accepted_estimate()
        s = ShipmentService.create(job_id=job.pk)
        self.assertEqual(s.status, Shipment.STATUS_PREPARED)
        self.assertEqual(s.sequence, 1)

    def test_create_assigns_next_sequence(self):
        job = _job_with_accepted_estimate()
        ShipmentService.create(job_id=job.pk)
        ShipmentService.create(job_id=job.pk)
        third = ShipmentService.create(job_id=job.pk)
        self.assertEqual(third.sequence, 3)


class ShipmentItemTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = _job_with_accepted_estimate()
        self.d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        self.s = ShipmentService.create(job_id=self.job.pk)

    def test_add_item_within_remaining(self):
        item = ShipmentService.add_item(
            shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('10'),
        )
        self.assertEqual(item.qty, Decimal('10'))

    def test_add_item_zero_qty_rejected(self):
        with self.assertRaises(ValidationError):
            ShipmentService.add_item(
                shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('0'),
            )

    def test_add_item_negative_qty_rejected(self):
        with self.assertRaises(ValidationError):
            ShipmentService.add_item(
                shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('-1'),
            )

    def test_add_item_exceeding_remaining_rejected(self):
        with self.assertRaises(ValidationError):
            ShipmentService.add_item(
                shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('16'),
            )

    def test_add_item_accounts_for_other_shipments(self):
        # First shipment claims 10.
        ShipmentService.add_item(
            shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('10'),
        )
        # Second shipment can claim up to 5 more.
        s2 = ShipmentService.create(job_id=self.job.pk)
        ShipmentService.add_item(shipment=s2, deliverable_id=self.d.pk, qty=Decimal('5'))
        # Third shipment can't add any more.
        s3 = ShipmentService.create(job_id=self.job.pk)
        with self.assertRaises(ValidationError):
            ShipmentService.add_item(shipment=s3, deliverable_id=self.d.pk, qty=Decimal('1'))

    def test_add_item_to_picked_up_shipment_rejected(self):
        self.s.status = Shipment.STATUS_PICKED_UP
        self.s.save()
        with self.assertRaises(ValidationError):
            ShipmentService.add_item(
                shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('1'),
            )

    def test_update_item_within_bounds(self):
        item = ShipmentService.add_item(
            shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('5'),
        )
        updated = ShipmentService.update_item(item=item, qty=Decimal('7'))
        self.assertEqual(updated.qty, Decimal('7'))

    def test_update_item_to_exceed_remaining_rejected(self):
        # Self contributes 5; deliverable has 15 ordered. Max settable here = 15.
        item = ShipmentService.add_item(
            shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('5'),
        )
        with self.assertRaises(ValidationError):
            ShipmentService.update_item(item=item, qty=Decimal('16'))

    def test_remove_item_from_prepared(self):
        item = ShipmentService.add_item(
            shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('5'),
        )
        ShipmentService.remove_item(item=item)
        self.assertFalse(ShipmentItem.objects.filter(pk=item.pk).exists())

    def test_remove_item_from_picked_up_rejected(self):
        item = ShipmentService.add_item(
            shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('5'),
        )
        self.s.status = Shipment.STATUS_PICKED_UP
        self.s.save()
        with self.assertRaises(ValidationError):
            ShipmentService.remove_item(item=item)


class ShipmentTransitionTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = _job_with_accepted_estimate()
        self.s = ShipmentService.create(job_id=self.job.pk)

    def test_mark_picked_up_transitions(self):
        result = ShipmentService.mark_picked_up(self.s.pk)
        self.assertEqual(result.status, Shipment.STATUS_PICKED_UP)
        self.assertIsNotNone(result.picked_up_date)

    def test_mark_picked_up_idempotent_rejection(self):
        ShipmentService.mark_picked_up(self.s.pk)
        with self.assertRaises(ValidationError):
            ShipmentService.mark_picked_up(self.s.pk)

    def test_delete_prepared_empty(self):
        ShipmentService.delete(shipment=self.s)
        self.assertFalse(Shipment.objects.filter(pk=self.s.pk).exists())

    def test_delete_prepared_with_items_rejected(self):
        d = Deliverable.objects.create(
            job=self.job, description='X', qty_ordered=Decimal('1'), units='ea',
        )
        ShipmentService.add_item(shipment=self.s, deliverable_id=d.pk, qty=Decimal('1'))
        with self.assertRaises(ValidationError):
            ShipmentService.delete(shipment=self.s)

    def test_delete_picked_up_rejected(self):
        ShipmentService.mark_picked_up(self.s.pk)
        self.s.refresh_from_db()
        with self.assertRaises(ValidationError):
            ShipmentService.delete(shipment=self.s)


class PackingListPayloadTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = _job_with_accepted_estimate()
        self.d1 = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea', sort_order=10,
        )
        self.d2 = Deliverable.objects.create(
            job=self.job, description='Hardware kit', qty_ordered=Decimal('15'), units='kit', sort_order=20,
        )

    def test_payload_includes_all_deliverables_in_sort_order(self):
        s = ShipmentService.create(job_id=self.job.pk)
        ShipmentService.add_item(shipment=s, deliverable_id=self.d1.pk, qty=Decimal('10'))
        payload = ShipmentService.packing_list_payload(s)

        rows = payload['rows']
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['deliverable_id'], self.d1.pk)
        self.assertEqual(rows[1]['deliverable_id'], self.d2.pk)
        self.assertEqual(rows[0]['qty_this_shipment'], Decimal('10'))
        self.assertEqual(rows[1]['qty_this_shipment'], Decimal('0'))

    def test_previously_picked_up_only_counts_other_picked_up_shipments(self):
        # First shipment, picked up, 10 stools.
        s1 = ShipmentService.create(job_id=self.job.pk)
        ShipmentService.add_item(shipment=s1, deliverable_id=self.d1.pk, qty=Decimal('10'))
        ShipmentService.mark_picked_up(s1.pk)

        # Second shipment, prepared, 5 stools — payload subject.
        s2 = ShipmentService.create(job_id=self.job.pk)
        ShipmentService.add_item(shipment=s2, deliverable_id=self.d1.pk, qty=Decimal('5'))

        payload = ShipmentService.packing_list_payload(s2)
        row = next(r for r in payload['rows'] if r['deliverable_id'] == self.d1.pk)
        self.assertEqual(row['qty_previously_picked_up'], Decimal('10'))
        self.assertEqual(row['qty_this_shipment'], Decimal('5'))
        self.assertEqual(row['qty_remaining_after_this_shipment'], Decimal('0'))

    def test_previously_does_not_include_other_prepared_shipments(self):
        s1 = ShipmentService.create(job_id=self.job.pk)
        ShipmentService.add_item(shipment=s1, deliverable_id=self.d1.pk, qty=Decimal('7'))
        # s1 remains prepared.

        s2 = ShipmentService.create(job_id=self.job.pk)
        ShipmentService.add_item(shipment=s2, deliverable_id=self.d1.pk, qty=Decimal('5'))

        payload = ShipmentService.packing_list_payload(s2)
        row = next(r for r in payload['rows'] if r['deliverable_id'] == self.d1.pk)
        self.assertEqual(row['qty_previously_picked_up'], Decimal('0'))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_shipment_service -v 2`

Expected: ImportError on `ShipmentService`.

- [ ] **Step 3: Implement ShipmentService**

Append to `apps/deliverables/services.py`:

```python
from django.utils import timezone
from apps.core.services import NotFoundError, ServiceError


class ShipmentService:
    """Business-logic façade for the Shipment + ShipmentItem models."""

    @staticmethod
    def _assert_d_list_locked(job):
        if not _any_accepted_estimate(job):
            raise ValidationError(
                'Cannot create a shipment until the deliverables list is locked '
                '(estimate accepted).'
            )

    @staticmethod
    @transaction.atomic
    def create(*, job_id):
        from apps.jobs.models import Job
        from apps.deliverables.models import Shipment
        job = Job.objects.select_for_update().get(pk=job_id)
        ShipmentService._assert_d_list_locked(job)
        last = (
            Shipment.objects.filter(job=job).order_by('-sequence').first()
        )
        next_seq = (last.sequence + 1) if last else 1
        s = Shipment.objects.create(
            job=job,
            sequence=next_seq,
            status=Shipment.STATUS_PREPARED,
            prepared_date=timezone.now(),
        )
        return s

    @staticmethod
    @transaction.atomic
    def update(*, shipment, **fields):
        from apps.deliverables.models import Shipment
        if shipment.status != Shipment.STATUS_PREPARED:
            raise ValidationError('Only prepared shipments can be edited.')
        allowed = {'notes'}
        for field, value in fields.items():
            if field not in allowed:
                raise ValidationError(f'Field {field!r} is not updatable.')
            setattr(shipment, field, value)
        shipment.full_clean()
        shipment.save()
        return shipment

    @staticmethod
    @transaction.atomic
    def delete(*, shipment):
        from apps.deliverables.models import Shipment
        if shipment.status != Shipment.STATUS_PREPARED:
            raise ValidationError('Only prepared shipments can be deleted.')
        if shipment.items.exists():
            raise ValidationError('Remove items before deleting the shipment.')
        shipment.delete()

    @staticmethod
    @transaction.atomic
    def mark_picked_up(pk):
        """Transition prepared -> picked_up. Signature shape suits StatusTransitionMixin."""
        from apps.deliverables.models import Shipment
        try:
            shipment = Shipment.objects.select_for_update().get(pk=pk)
        except Shipment.DoesNotExist:
            raise NotFoundError(f'Shipment {pk} not found')
        if shipment.status != Shipment.STATUS_PREPARED:
            raise ValidationError('Only prepared shipments can be marked picked up.')
        shipment.status = Shipment.STATUS_PICKED_UP
        shipment.picked_up_date = timezone.now()
        shipment.save()
        return shipment

    @staticmethod
    def _validate_qty_bounds(deliverable, *, requested_qty, exclude_item_id=None):
        if requested_qty is None or requested_qty <= 0:
            raise ValidationError('Quantity must be greater than zero.')
        from apps.deliverables.models import ShipmentItem
        # Sum of qtys on other ShipmentItems for this deliverable (across all shipments).
        existing = ShipmentItem.objects.filter(deliverable=deliverable)
        if exclude_item_id is not None:
            existing = existing.exclude(pk=exclude_item_id)
        already_committed = sum(
            (item.qty for item in existing.select_related('shipment')),
            Decimal('0'),
        )
        if already_committed + requested_qty > deliverable.qty_ordered:
            raise ValidationError(
                f'Quantity exceeds remaining ({deliverable.qty_ordered - already_committed}).'
            )

    @staticmethod
    @transaction.atomic
    def add_item(*, shipment, deliverable_id, qty):
        from apps.deliverables.models import Deliverable, Shipment, ShipmentItem
        if shipment.status != Shipment.STATUS_PREPARED:
            raise ValidationError('Items can only be added to prepared shipments.')
        try:
            deliverable = Deliverable.objects.select_for_update().get(
                pk=deliverable_id, job=shipment.job,
            )
        except Deliverable.DoesNotExist:
            raise NotFoundError(f'Deliverable {deliverable_id} not found for this Job')
        ShipmentService._validate_qty_bounds(deliverable, requested_qty=qty)
        item = ShipmentItem(shipment=shipment, deliverable=deliverable, qty=qty)
        item.full_clean()
        item.save()
        return item

    @staticmethod
    @transaction.atomic
    def update_item(*, item, qty):
        from apps.deliverables.models import Shipment, Deliverable
        if item.shipment.status != Shipment.STATUS_PREPARED:
            raise ValidationError('Items can only be edited on prepared shipments.')
        deliverable = Deliverable.objects.select_for_update().get(pk=item.deliverable_id)
        ShipmentService._validate_qty_bounds(
            deliverable, requested_qty=qty, exclude_item_id=item.pk,
        )
        item.qty = qty
        item.full_clean()
        item.save()
        return item

    @staticmethod
    @transaction.atomic
    def remove_item(*, item):
        from apps.deliverables.models import Shipment
        if item.shipment.status != Shipment.STATUS_PREPARED:
            raise ValidationError('Items can only be removed from prepared shipments.')
        item.delete()

    @staticmethod
    def packing_list_payload(shipment):
        """Return JSON-serializable payload for the printable packing list view."""
        from apps.deliverables.models import Deliverable, Shipment, ShipmentItem
        deliverables = list(
            Deliverable.objects.filter(job=shipment.job).order_by('sort_order', 'pk')
        )
        # Pre-fetch items for the entire job in one query.
        items_for_job = list(
            ShipmentItem.objects
            .filter(shipment__job=shipment.job)
            .select_related('shipment')
        )

        rows = []
        for d in deliverables:
            qty_this = Decimal('0')
            qty_prev = Decimal('0')
            for item in items_for_job:
                if item.deliverable_id != d.pk:
                    continue
                if item.shipment_id == shipment.pk:
                    qty_this = item.qty
                elif item.shipment.status == Shipment.STATUS_PICKED_UP:
                    qty_prev += item.qty
            qty_remaining_after = d.qty_ordered - qty_prev - qty_this
            rows.append({
                'deliverable_id': d.pk,
                'description': d.description,
                'units': d.units,
                'qty_ordered': d.qty_ordered,
                'qty_this_shipment': qty_this,
                'qty_previously_picked_up': qty_prev,
                'qty_remaining_after_this_shipment': qty_remaining_after,
            })
        return {
            'shipment': {
                'id': shipment.pk,
                'sequence': shipment.sequence,
                'status': shipment.status,
                'prepared_date': shipment.prepared_date,
                'picked_up_date': shipment.picked_up_date,
                'notes': shipment.notes,
            },
            'job': {
                'id': shipment.job.pk,
                'job_number': shipment.job.job_number,
                'name': shipment.job.name,
            },
            'rows': rows,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_shipment_service -v 2`

Expected: All 20 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/deliverables/services.py tests/test_shipment_service.py
git commit -m "feat(deliverables): add ShipmentService"
```

---

## Phase 5 — Estimate.mark_open guard

### Task 5.1: Add the empty-deliverables guard test

**Files:**
- Create: `tests/test_estimate_mark_open_deliverables_guard.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_estimate_mark_open_deliverables_guard.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateService
from apps.jobs.models import Job


class EstimateMarkOpenDeliverablesGuardTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        Deliverable.objects.filter(job=self.job).delete()
        self.estimate = Estimate.objects.create(
            job=self.job,
            estimate_number='EST-G-1',
            version=1,
            status=Estimate.STATUS_DRAFT,
        )

    def test_mark_open_blocked_without_deliverables(self):
        with self.assertRaises(ValidationError):
            EstimateService.mark_open(self.estimate.pk)
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, Estimate.STATUS_DRAFT)

    def test_mark_open_succeeds_with_deliverables(self):
        Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        EstimateService.mark_open(self.estimate.pk)
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, Estimate.STATUS_OPEN)
```

- [ ] **Step 2: Run tests to verify the first one fails**

Run: `python manage.py test tests.test_estimate_mark_open_deliverables_guard -v 2`

Expected: `test_mark_open_blocked_without_deliverables` fails (estimate opens even with no deliverables); `test_mark_open_succeeds_with_deliverables` may pass or fail depending on which assertion the test hits first.

- [ ] **Step 3: Add the guard to EstimateService.mark_open**

Modify `apps/estimates/services.py`, the `mark_open` method (around line 66). Insert the guard before the line `estimate.status = Estimate.STATUS_OPEN`. The full updated method becomes:

```python
    @staticmethod
    def mark_open(pk):
        """Mark a draft estimate as open and finalize associated worksheet."""
        try:
            estimate = Estimate.objects.get(pk=pk)
        except Estimate.DoesNotExist:
            raise NotFoundError(f'Estimate {pk} not found')
        if estimate.status != Estimate.STATUS_DRAFT:
            raise ValidationError('Only draft estimates can be marked as open.')

        # Guard: estimate cannot be sent without a non-empty Deliverables list.
        from apps.deliverables.models import Deliverable
        if not Deliverable.objects.filter(job=estimate.job).exists():
            raise ValidationError('Cannot send estimate: job has no deliverables.')

        estimate.status = Estimate.STATUS_OPEN
        estimate.save()

        # Finalize associated worksheet if draft
        worksheet = EstWorksheet.objects.filter(estimate=estimate).first()
        if worksheet and worksheet.status == EstWorksheet.STATUS_DRAFT:
            worksheet.status = EstWorksheet.STATUS_FINAL
            worksheet.save()

        return estimate
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_estimate_mark_open_deliverables_guard -v 2`

Expected: Both tests pass.

- [ ] **Step 5: Run the broader estimate test suite to verify nothing else broke**

Run: `python manage.py test tests.test_estimate_job_status_sync tests.test_estimate_mark_open_deliverables_guard -v 2`

Expected: All pass. If existing tests that call `mark_open` start failing, they likely create estimates with no Deliverables and need Deliverable creation added.

If any existing tests fail because they relied on `mark_open` without deliverables, the fix in each failing test is to add a `Deliverable.objects.create(job=..., description='...', qty_ordered=1, units='ea')` line before the `mark_open` call. Capture them in the same commit.

- [ ] **Step 6: Commit**

```bash
git add apps/estimates/services.py tests/test_estimate_mark_open_deliverables_guard.py
# plus any existing-test fixups touched above
git commit -m "feat(estimates): block mark_open when job has no deliverables"
```

---

## Phase 6 — API serializers

### Task 6.1: Create serializers

**Files:**
- Create: `apps/api/deliverables/__init__.py` (empty)
- Create: `apps/api/deliverables/serializers.py`

- [ ] **Step 1: Create the API app package**

Create `apps/api/deliverables/__init__.py` (empty).

- [ ] **Step 2: Implement the serializers**

Create `apps/api/deliverables/serializers.py`:

```python
from rest_framework import serializers
from apps.deliverables.models import Deliverable, Shipment, ShipmentItem
from apps.deliverables.services import DeliverableService


class DeliverableSerializer(serializers.ModelSerializer):
    qty_picked_up = serializers.SerializerMethodField()
    qty_prepped = serializers.SerializerMethodField()
    qty_remaining = serializers.SerializerMethodField()

    class Meta:
        model = Deliverable
        fields = [
            'id', 'job', 'description', 'qty_ordered', 'units', 'sort_order',
            'qty_picked_up', 'qty_prepped', 'qty_remaining',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'job', 'created_at', 'updated_at',
                            'qty_picked_up', 'qty_prepped', 'qty_remaining']

    def _fulfillment(self, obj):
        if not hasattr(obj, '_cached_fulfillment'):
            obj._cached_fulfillment = DeliverableService.compute_fulfillment(obj)
        return obj._cached_fulfillment

    def get_qty_picked_up(self, obj):
        return self._fulfillment(obj)['qty_picked_up']

    def get_qty_prepped(self, obj):
        return self._fulfillment(obj)['qty_prepped']

    def get_qty_remaining(self, obj):
        return self._fulfillment(obj)['qty_remaining']


class ShipmentItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShipmentItem
        fields = ['id', 'shipment', 'deliverable', 'qty']
        read_only_fields = ['id', 'shipment']


class ShipmentSerializer(serializers.ModelSerializer):
    items = ShipmentItemSerializer(many=True, read_only=True)

    class Meta:
        model = Shipment
        fields = [
            'id', 'job', 'sequence', 'status', 'prepared_date', 'picked_up_date',
            'notes', 'items', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'job', 'sequence', 'status', 'prepared_date',
                            'picked_up_date', 'items', 'created_at', 'updated_at']
```

- [ ] **Step 3: Verify Django can load the new module**

Run: `python manage.py check`

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 4: Commit**

```bash
git add apps/api/deliverables/__init__.py apps/api/deliverables/serializers.py
git commit -m "feat(api/deliverables): add serializers for Deliverable, Shipment, ShipmentItem"
```

---

## Phase 7 — Deliverable API viewset

### Task 7.1: Implement DeliverableViewSet and tests

**Files:**
- Create: `apps/api/deliverables/views.py`
- Create: `apps/api/deliverables/urls.py`
- Create: `tests/test_deliverables_api.py`
- Modify: `apps/api/urls.py`

- [ ] **Step 1: Write failing API tests for Deliverables**

Create `tests/test_deliverables_api.py`:

```python
from decimal import Decimal
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable
from apps.estimates.models import Estimate
from apps.jobs.models import Job


User = get_user_model()


def _job_clean():
    job = Job.objects.first()
    Estimate.objects.filter(job=job).delete()
    Deliverable.objects.filter(job=job).delete()
    return job


def _manager():
    # First active user with can_manage_jobs perm in the fixture.
    user = User.objects.filter(user_permissions__codename='can_manage_jobs', is_active=True).first()
    if user:
        return user
    # Fall back to creating one.
    from django.contrib.auth.models import Permission
    perm = Permission.objects.get(codename='can_manage_jobs')
    user = User.objects.create_user(username='mgr', password='x', email='m@x.com')
    user.user_permissions.add(perm)
    return user


def _plain_user():
    user = User.objects.filter(is_active=True).exclude(
        user_permissions__codename='can_manage_jobs',
    ).first()
    if user:
        return user
    user = User.objects.create_user(username='plain', password='x', email='p@x.com')
    return user


class DeliverableAPIPermissionTests(FixtureTestCase):

    def test_list_requires_auth(self):
        client = APIClient()
        job = _job_clean()
        r = client.get(f'/api/jobs/{job.pk}/deliverables/')
        self.assertIn(r.status_code, (401, 403))

    def test_list_works_with_any_authenticated_user(self):
        client = APIClient()
        client.force_authenticate(user=_plain_user())
        job = _job_clean()
        r = client.get(f'/api/jobs/{job.pk}/deliverables/')
        self.assertEqual(r.status_code, 200)

    def test_create_requires_can_manage_jobs(self):
        client = APIClient()
        client.force_authenticate(user=_plain_user())
        job = _job_clean()
        r = client.post(
            f'/api/jobs/{job.pk}/deliverables/',
            {'description': 'Stool', 'qty_ordered': '15', 'units': 'ea'},
            format='json',
        )
        self.assertEqual(r.status_code, 403)

    def test_create_allowed_for_manager(self):
        client = APIClient()
        client.force_authenticate(user=_manager())
        job = _job_clean()
        r = client.post(
            f'/api/jobs/{job.pk}/deliverables/',
            {'description': 'Stool', 'qty_ordered': '15', 'units': 'ea'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)


class DeliverableAPICRUDTests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.job = _job_clean()
        self.client = APIClient()
        self.client.force_authenticate(user=_manager())

    def test_create_returns_serializer_fields(self):
        r = self.client.post(
            f'/api/jobs/{self.job.pk}/deliverables/',
            {'description': 'Stool', 'qty_ordered': '15', 'units': 'ea'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['description'], 'Stool')
        self.assertEqual(r.json()['qty_remaining'], '15.00')

    def test_create_rejected_when_estimate_open(self):
        Estimate.objects.create(
            job=self.job, estimate_number='EST-Q-1', version=1,
            status=Estimate.STATUS_OPEN,
        )
        r = self.client.post(
            f'/api/jobs/{self.job.pk}/deliverables/',
            {'description': 'Stool', 'qty_ordered': '15', 'units': 'ea'},
            format='json',
        )
        self.assertEqual(r.status_code, 400)

    def test_patch_updates_fields(self):
        d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        r = self.client.patch(
            f'/api/jobs/{self.job.pk}/deliverables/{d.pk}/',
            {'description': 'Walnut stool'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        d.refresh_from_db()
        self.assertEqual(d.description, 'Walnut stool')

    def test_delete_returns_200_json(self):
        d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        r = self.client.delete(f'/api/jobs/{self.job.pk}/deliverables/{d.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'].split(';')[0], 'application/json')
        self.assertIn('message', r.json())

    def test_reorder_endpoint(self):
        a = Deliverable.objects.create(job=self.job, description='A', qty_ordered=Decimal('1'), units='ea', sort_order=10)
        b = Deliverable.objects.create(job=self.job, description='B', qty_ordered=Decimal('1'), units='ea', sort_order=20)
        c = Deliverable.objects.create(job=self.job, description='C', qty_ordered=Decimal('1'), units='ea', sort_order=30)

        r = self.client.post(
            f'/api/jobs/{self.job.pk}/deliverables/reorder/',
            {'ordered_ids': [c.pk, a.pk, b.pk]},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        ids = list(
            Deliverable.objects.filter(job=self.job).order_by('sort_order').values_list('pk', flat=True)
        )
        self.assertEqual(ids, [c.pk, a.pk, b.pk])

    def test_editability_endpoint(self):
        r = self.client.get(f'/api/jobs/{self.job.pk}/deliverables/editability/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body['editable'])
        self.assertIsNone(body['reason'])

        Estimate.objects.create(
            job=self.job, estimate_number='EST-E-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        r = self.client.get(f'/api/jobs/{self.job.pk}/deliverables/editability/')
        body = r.json()
        self.assertFalse(body['editable'])
        self.assertEqual(body['reason'], 'estimate_accepted')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_deliverables_api -v 2`

Expected: All tests fail with 404 (no route registered).

- [ ] **Step 3: Implement the viewset and urls**

Create `apps/api/deliverables/views.py`:

```python
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.api.permissions import CanManageJobs
from apps.deliverables.models import Deliverable, Shipment, ShipmentItem
from apps.deliverables.services import DeliverableService, ShipmentService
from apps.core.services import NotFoundError, ServiceError
from .serializers import (
    DeliverableSerializer, ShipmentSerializer, ShipmentItemSerializer,
)


def _validation_error_response(exc):
    detail = exc.message_dict if hasattr(exc, 'message_dict') else (
        exc.messages if hasattr(exc, 'messages') else [str(exc)]
    )
    return Response({'detail': detail}, status=status.HTTP_400_BAD_REQUEST)


class JobDeliverablesView(APIView):
    """List + create deliverables for a Job."""

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), CanManageJobs()]
        return [IsAuthenticated()]

    def get(self, request, job_id):
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_id)
        except Job.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        qs = Deliverable.objects.filter(job=job).order_by('sort_order')
        serializer = DeliverableSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request, job_id):
        data = request.data or {}
        try:
            d = DeliverableService.create(
                job_id=job_id,
                description=data.get('description', ''),
                qty_ordered=data.get('qty_ordered'),
                units=data.get('units', ''),
                sort_order=data.get('sort_order'),
            )
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(DeliverableSerializer(d).data, status=status.HTTP_201_CREATED)


class JobDeliverableDetailView(APIView):
    """Retrieve, update, delete a single deliverable."""

    def get_permissions(self):
        if self.request.method in ('GET',):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobs()]

    def _get(self, job_id, deliverable_id):
        try:
            return Deliverable.objects.get(pk=deliverable_id, job_id=job_id)
        except Deliverable.DoesNotExist:
            return None

    def get(self, request, job_id, deliverable_id):
        d = self._get(job_id, deliverable_id)
        if d is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(DeliverableSerializer(d).data)

    def patch(self, request, job_id, deliverable_id):
        d = self._get(job_id, deliverable_id)
        if d is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            d = DeliverableService.update(deliverable=d, **(request.data or {}))
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(DeliverableSerializer(d).data)

    def delete(self, request, job_id, deliverable_id):
        d = self._get(job_id, deliverable_id)
        if d is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            DeliverableService.delete(deliverable=d)
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response({'message': 'Deliverable deleted.'})


class JobDeliverablesReorderView(APIView):
    permission_classes = [IsAuthenticated, CanManageJobs]

    def post(self, request, job_id):
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_id)
        except Job.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        ordered_ids = (request.data or {}).get('ordered_ids', [])
        if not isinstance(ordered_ids, list) or not ordered_ids:
            return Response(
                {'ordered_ids': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = DeliverableService.reorder(job=job, ordered_ids=ordered_ids)
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(DeliverableSerializer(result, many=True).data)


class JobDeliverablesEditabilityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, job_id):
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_id)
        except Job.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'editable': DeliverableService.is_editable(job),
            'reason': DeliverableService.editability_reason(job),
        })
```

Create `apps/api/deliverables/urls.py`:

```python
from django.urls import path
from .views import (
    JobDeliverablesView, JobDeliverableDetailView,
    JobDeliverablesReorderView, JobDeliverablesEditabilityView,
)


urlpatterns = [
    path(
        'jobs/<int:job_id>/deliverables/',
        JobDeliverablesView.as_view(),
        name='job-deliverables-list',
    ),
    path(
        'jobs/<int:job_id>/deliverables/reorder/',
        JobDeliverablesReorderView.as_view(),
        name='job-deliverables-reorder',
    ),
    path(
        'jobs/<int:job_id>/deliverables/editability/',
        JobDeliverablesEditabilityView.as_view(),
        name='job-deliverables-editability',
    ),
    path(
        'jobs/<int:job_id>/deliverables/<int:deliverable_id>/',
        JobDeliverableDetailView.as_view(),
        name='job-deliverable-detail',
    ),
]
```

- [ ] **Step 4: Wire into the API URL tree**

Modify `apps/api/urls.py`. In the `urlpatterns` list, add the include before the `router.urls`:

```python
urlpatterns = [
    path('', api_root, name='api-root'),
    path('auth/', include('apps.api.auth.urls')),
    path('emails/', include('apps.api.email.urls')),
    path('search/', search_view, name='api-search'),
    path('settings/units/', units_view, name='api-settings-units'),
    path('settings/', settings_view, name='api-settings'),
    path('shifts/', include('apps.api.time_tracking.urls')),
    path('expenses/', include('apps.api.expenses.urls')),
    path('reimbursements/', include('apps.api.reimbursements.urls')),
    path('qbo/', include('apps.qbo.urls')),
    path('users/', include('apps.api.users.urls')),
    path('', include('apps.api.deliverables.urls')),  # NEW
    path('jobs/board/pipeline/', pipeline_view, name='board-pipeline'),
    ...
]
```

(The `path('', include(...))` mounts the new urls.py's patterns at `/api/`, so its paths like `jobs/<id>/deliverables/` resolve to `/api/jobs/<id>/deliverables/`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_deliverables_api -v 2`

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/api/deliverables/views.py apps/api/deliverables/urls.py apps/api/urls.py tests/test_deliverables_api.py
git commit -m "feat(api/deliverables): wire DeliverableViewSet endpoints"
```

---

## Phase 8 — Shipment API endpoints

### Task 8.1: Add Shipment / ShipmentItem views and tests

**Files:**
- Modify: `apps/api/deliverables/views.py`
- Modify: `apps/api/deliverables/urls.py`
- Create: `tests/test_shipments_api.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_shipments_api.py`:

```python
from decimal import Decimal
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from tests.base import FixtureTestCase
from apps.deliverables.models import Deliverable, Shipment, ShipmentItem
from apps.deliverables.services import ShipmentService
from apps.estimates.models import Estimate
from apps.jobs.models import Job


User = get_user_model()


def _job_with_accept():
    job = Job.objects.first()
    Estimate.objects.filter(job=job).delete()
    Deliverable.objects.filter(job=job).delete()
    Shipment.objects.filter(job=job).delete()
    Estimate.objects.create(
        job=job, estimate_number='EST-SH-1', version=1, status=Estimate.STATUS_ACCEPTED,
    )
    return job


def _plain_user():
    user = User.objects.filter(is_active=True).first()
    if not user:
        user = User.objects.create_user(username='u', password='x', email='u@x.com')
    return user


class ShipmentCreateAPITests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_plain_user())

    def test_create_requires_accepted_estimate(self):
        job = Job.objects.first()
        Estimate.objects.filter(job=job).delete()
        r = self.client.post(f'/api/jobs/{job.pk}/shipments/', {}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_create_succeeds_when_d_list_locked(self):
        job = _job_with_accept()
        r = self.client.post(f'/api/jobs/{job.pk}/shipments/', {}, format='json')
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual(body['status'], 'prepared')
        self.assertEqual(body['sequence'], 1)


class ShipmentListAndDetailAPITests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_plain_user())
        self.job = _job_with_accept()
        self.s = ShipmentService.create(job_id=self.job.pk)

    def test_list_filterable_by_job(self):
        r = self.client.get(f'/api/shipments/?job={self.job.pk}')
        self.assertEqual(r.status_code, 200)
        ids = [item['id'] for item in r.json()['results']] if 'results' in r.json() else [
            item['id'] for item in r.json()
        ]
        self.assertIn(self.s.pk, ids)

    def test_patch_notes(self):
        r = self.client.patch(
            f'/api/shipments/{self.s.pk}/',
            {'notes': 'Wrapped in newspaper'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        self.s.refresh_from_db()
        self.assertEqual(self.s.notes, 'Wrapped in newspaper')

    def test_delete_prepared_empty(self):
        r = self.client.delete(f'/api/shipments/{self.s.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'].split(';')[0], 'application/json')
        self.assertFalse(Shipment.objects.filter(pk=self.s.pk).exists())

    def test_pick_up_action(self):
        r = self.client.post(f'/api/shipments/{self.s.pk}/pick-up/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        self.s.refresh_from_db()
        self.assertEqual(self.s.status, 'picked_up')
        self.assertIsNotNone(self.s.picked_up_date)


class ShipmentItemAPITests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_plain_user())
        self.job = _job_with_accept()
        self.d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        self.s = ShipmentService.create(job_id=self.job.pk)

    def test_add_item(self):
        r = self.client.post(
            f'/api/shipments/{self.s.pk}/items/',
            {'deliverable': self.d.pk, 'qty': '10'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)

    def test_add_item_exceeding_remaining_rejected(self):
        r = self.client.post(
            f'/api/shipments/{self.s.pk}/items/',
            {'deliverable': self.d.pk, 'qty': '20'},
            format='json',
        )
        self.assertEqual(r.status_code, 400)

    def test_patch_item(self):
        item = ShipmentService.add_item(shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('5'))
        r = self.client.patch(
            f'/api/shipments/{self.s.pk}/items/{item.pk}/',
            {'qty': '7'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.qty, Decimal('7'))

    def test_delete_item(self):
        item = ShipmentService.add_item(shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('5'))
        r = self.client.delete(f'/api/shipments/{self.s.pk}/items/{item.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(ShipmentItem.objects.filter(pk=item.pk).exists())


class PackingListAPITests(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=_plain_user())
        self.job = _job_with_accept()
        self.d = Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('15'), units='ea',
        )
        self.s = ShipmentService.create(job_id=self.job.pk)
        ShipmentService.add_item(shipment=self.s, deliverable_id=self.d.pk, qty=Decimal('10'))

    def test_packing_list_endpoint(self):
        r = self.client.get(f'/api/shipments/{self.s.pk}/packing-list/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['shipment']['sequence'], 1)
        self.assertEqual(body['job']['id'], self.job.pk)
        self.assertEqual(len(body['rows']), 1)
        self.assertEqual(body['rows'][0]['qty_this_shipment'], '10.00')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_shipments_api -v 2`

Expected: All tests fail with 404.

- [ ] **Step 3: Add Shipment views**

Append to `apps/api/deliverables/views.py`:

```python
class JobShipmentsCreateView(APIView):
    """POST /api/jobs/<id>/shipments/ — create a new shipment."""

    permission_classes = [IsAuthenticated]

    def post(self, request, job_id):
        try:
            shipment = ShipmentService.create(job_id=job_id)
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(ShipmentSerializer(shipment).data, status=status.HTTP_201_CREATED)


class ShipmentsListView(APIView):
    """GET /api/shipments/?job=<id>"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Shipment.objects.all().select_related('job').prefetch_related('items')
        job_id = request.query_params.get('job')
        if job_id:
            qs = qs.filter(job_id=job_id)
        serializer = ShipmentSerializer(qs, many=True)
        return Response({'results': serializer.data})


class ShipmentDetailView(APIView):
    """GET / PATCH / DELETE /api/shipments/<id>/"""

    permission_classes = [IsAuthenticated]

    def _get(self, shipment_id):
        try:
            return Shipment.objects.get(pk=shipment_id)
        except Shipment.DoesNotExist:
            return None

    def get(self, request, shipment_id):
        s = self._get(shipment_id)
        if s is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(ShipmentSerializer(s).data)

    def patch(self, request, shipment_id):
        s = self._get(shipment_id)
        if s is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            s = ShipmentService.update(shipment=s, **(request.data or {}))
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(ShipmentSerializer(s).data)

    def delete(self, request, shipment_id):
        s = self._get(shipment_id)
        if s is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            ShipmentService.delete(shipment=s)
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response({'message': 'Shipment deleted.'})


class ShipmentPickUpView(APIView):
    """POST /api/shipments/<id>/pick-up/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, shipment_id):
        try:
            s = ShipmentService.mark_picked_up(shipment_id)
        except NotFoundError:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(ShipmentSerializer(s).data)


class ShipmentItemsView(APIView):
    """GET / POST /api/shipments/<id>/items/"""

    permission_classes = [IsAuthenticated]

    def _get_shipment(self, shipment_id):
        try:
            return Shipment.objects.get(pk=shipment_id)
        except Shipment.DoesNotExist:
            return None

    def get(self, request, shipment_id):
        s = self._get_shipment(shipment_id)
        if s is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        qs = s.items.all().select_related('deliverable').order_by('deliverable__sort_order')
        return Response(ShipmentItemSerializer(qs, many=True).data)

    def post(self, request, shipment_id):
        s = self._get_shipment(shipment_id)
        if s is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        data = request.data or {}
        try:
            item = ShipmentService.add_item(
                shipment=s,
                deliverable_id=data.get('deliverable'),
                qty=data.get('qty'),
            )
        except NotFoundError:
            return Response({'detail': 'Deliverable not found.'}, status=status.HTTP_400_BAD_REQUEST)
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(ShipmentItemSerializer(item).data, status=status.HTTP_201_CREATED)


class ShipmentItemDetailView(APIView):
    """PATCH / DELETE /api/shipments/<id>/items/<iid>/"""

    permission_classes = [IsAuthenticated]

    def _get(self, shipment_id, item_id):
        try:
            return ShipmentItem.objects.get(pk=item_id, shipment_id=shipment_id)
        except ShipmentItem.DoesNotExist:
            return None

    def patch(self, request, shipment_id, item_id):
        item = self._get(shipment_id, item_id)
        if item is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            item = ShipmentService.update_item(item=item, qty=(request.data or {}).get('qty'))
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response(ShipmentItemSerializer(item).data)

    def delete(self, request, shipment_id, item_id):
        item = self._get(shipment_id, item_id)
        if item is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            ShipmentService.remove_item(item=item)
        except DjangoValidationError as e:
            return _validation_error_response(e)
        return Response({'message': 'Item deleted.'})


class ShipmentPackingListView(APIView):
    """GET /api/shipments/<id>/packing-list/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, shipment_id):
        try:
            s = Shipment.objects.select_related('job').get(pk=shipment_id)
        except Shipment.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        payload = ShipmentService.packing_list_payload(s)
        return Response(payload)
```

- [ ] **Step 4: Add the new URL patterns**

Modify `apps/api/deliverables/urls.py`. Append the new routes:

```python
from django.urls import path
from .views import (
    JobDeliverablesView, JobDeliverableDetailView,
    JobDeliverablesReorderView, JobDeliverablesEditabilityView,
    JobShipmentsCreateView, ShipmentsListView, ShipmentDetailView,
    ShipmentPickUpView, ShipmentItemsView, ShipmentItemDetailView,
    ShipmentPackingListView,
)


urlpatterns = [
    # Deliverables
    path(
        'jobs/<int:job_id>/deliverables/',
        JobDeliverablesView.as_view(),
        name='job-deliverables-list',
    ),
    path(
        'jobs/<int:job_id>/deliverables/reorder/',
        JobDeliverablesReorderView.as_view(),
        name='job-deliverables-reorder',
    ),
    path(
        'jobs/<int:job_id>/deliverables/editability/',
        JobDeliverablesEditabilityView.as_view(),
        name='job-deliverables-editability',
    ),
    path(
        'jobs/<int:job_id>/deliverables/<int:deliverable_id>/',
        JobDeliverableDetailView.as_view(),
        name='job-deliverable-detail',
    ),

    # Shipments
    path(
        'jobs/<int:job_id>/shipments/',
        JobShipmentsCreateView.as_view(),
        name='job-shipments-create',
    ),
    path(
        'shipments/',
        ShipmentsListView.as_view(),
        name='shipments-list',
    ),
    path(
        'shipments/<int:shipment_id>/',
        ShipmentDetailView.as_view(),
        name='shipment-detail',
    ),
    path(
        'shipments/<int:shipment_id>/pick-up/',
        ShipmentPickUpView.as_view(),
        name='shipment-pick-up',
    ),
    path(
        'shipments/<int:shipment_id>/items/',
        ShipmentItemsView.as_view(),
        name='shipment-items',
    ),
    path(
        'shipments/<int:shipment_id>/items/<int:item_id>/',
        ShipmentItemDetailView.as_view(),
        name='shipment-item-detail',
    ),
    path(
        'shipments/<int:shipment_id>/packing-list/',
        ShipmentPackingListView.as_view(),
        name='shipment-packing-list',
    ),
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_shipments_api -v 2`

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/api/deliverables/views.py apps/api/deliverables/urls.py tests/test_shipments_api.py
git commit -m "feat(api/deliverables): wire Shipment + ShipmentItem endpoints"
```

---

## Phase 9 — Frontend: DeliverablesSection

### Task 9.1: Implement DeliverablesSection component

**Files:**
- Create: `frontend/src/components/jobs/DeliverablesSection.svelte`

- [ ] **Step 1: Implement the component**

Create `frontend/src/components/jobs/DeliverablesSection.svelte`:

```svelte
<script>
  import { api } from '../../lib/api.js';
  import DeliverablesEditModal from './DeliverablesEditModal.svelte';

  let { jobId } = $props();

  let deliverables = $state([]);
  let editability = $state({ editable: false, reason: null });
  let loading = $state(true);
  let modalOpen = $state(false);

  async function load() {
    loading = true;
    const [items, ed] = await Promise.all([
      api.get(`/api/jobs/${jobId}/deliverables/`),
      api.get(`/api/jobs/${jobId}/deliverables/editability/`),
    ]);
    deliverables = items;
    editability = ed;
    loading = false;
  }

  $effect(() => {
    if (jobId) load();
  });

  function openEdit() {
    modalOpen = true;
  }

  function onModalClose(changed) {
    modalOpen = false;
    if (changed) load();
  }

  function reasonLabel(r) {
    if (r === 'estimate_sent') return 'estimate sent';
    if (r === 'estimate_accepted') return 'estimate accepted';
    return '';
  }
</script>

<section class="deliverables">
  <header>
    <strong>Deliverables</strong>
    {#if !editability.editable && editability.reason}
      <span class="state">({reasonLabel(editability.reason)})</span>
    {/if}
    {#if editability.editable}
      <a href={null} onclick={openEdit}>Edit</a>
    {/if}
  </header>

  {#if loading}
    <p>Loading...</p>
  {:else if deliverables.length === 0}
    <p>
      No deliverables yet.
      {#if editability.editable}
        <a href={null} onclick={openEdit}>Add deliverables</a>
      {/if}
    </p>
  {:else}
    <div class="scroll">
      <table border="1">
        <thead>
          <tr><th>#</th><th>Description</th><th>Qty</th><th>Units</th><th>Picked up</th><th>Remaining</th></tr>
        </thead>
        <tbody>
          {#each deliverables as d, i}
            <tr>
              <td>{i + 1}</td>
              <td>{d.description}</td>
              <td>{d.qty_ordered}</td>
              <td>{d.units}</td>
              <td>{d.qty_picked_up}</td>
              <td>{d.qty_remaining}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

{#if modalOpen}
  <DeliverablesEditModal {jobId} onClose={onModalClose} />
{/if}

<style>
  .deliverables {
    min-width: 0;
  }
  .deliverables header {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
  }
  .state {
    font-style: italic;
    color: #555;
  }
  .scroll {
    max-height: 240px;
    overflow-y: auto;
  }
</style>
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && npm run build`

Expected: Build completes without errors. (`DeliverablesEditModal` import will resolve in Task 9.2; until then, this build will fail — defer the build check until 9.2.)

- [ ] **Step 3: Commit (incomplete; modal next)**

```bash
git add frontend/src/components/jobs/DeliverablesSection.svelte
git commit -m "feat(frontend): add DeliverablesSection skeleton"
```

### Task 9.2: Implement DeliverablesEditModal

**Files:**
- Create: `frontend/src/components/jobs/DeliverablesEditModal.svelte`

- [ ] **Step 1: Implement the modal**

Create `frontend/src/components/jobs/DeliverablesEditModal.svelte`:

```svelte
<script>
  import { api } from '../../lib/api.js';

  let { jobId, onClose } = $props();

  let rows = $state([]);
  let loading = $state(true);
  let saving = $state(false);
  let dirty = $state(false);
  let errorMsg = $state('');

  async function load() {
    loading = true;
    rows = await api.get(`/api/jobs/${jobId}/deliverables/`);
    rows = rows.map(r => ({ ...r, _new: false, _deleted: false }));
    loading = false;
  }

  function addRow() {
    rows = [...rows, {
      id: null,
      description: '',
      qty_ordered: '1',
      units: 'ea',
      sort_order: (rows.length + 1) * 10,
      _new: true,
      _deleted: false,
    }];
    dirty = true;
  }

  function deleteRow(idx) {
    const r = rows[idx];
    if (r._new) {
      rows = rows.filter((_, i) => i !== idx);
    } else {
      rows[idx]._deleted = true;
      rows = [...rows];
    }
    dirty = true;
  }

  function moveUp(idx) {
    if (idx === 0) return;
    const arr = [...rows];
    [arr[idx - 1], arr[idx]] = [arr[idx], arr[idx - 1]];
    rows = arr;
    dirty = true;
  }

  function moveDown(idx) {
    if (idx === rows.length - 1) return;
    const arr = [...rows];
    [arr[idx], arr[idx + 1]] = [arr[idx + 1], arr[idx]];
    rows = arr;
    dirty = true;
  }

  async function save() {
    saving = true;
    errorMsg = '';
    try {
      // Apply deletes first.
      for (const r of rows.filter(x => x._deleted && x.id)) {
        await api.delete(`/api/jobs/${jobId}/deliverables/${r.id}/`);
      }
      // Create new rows.
      const surviving = rows.filter(r => !r._deleted);
      for (const r of surviving.filter(x => x._new)) {
        const created = await api.post(`/api/jobs/${jobId}/deliverables/`, {
          description: r.description,
          qty_ordered: r.qty_ordered,
          units: r.units,
        });
        r.id = created.id;
        r._new = false;
      }
      // Patch updates to existing rows.
      for (const r of surviving.filter(x => !x._new)) {
        await api.patch(`/api/jobs/${jobId}/deliverables/${r.id}/`, {
          description: r.description,
          qty_ordered: r.qty_ordered,
          units: r.units,
        });
      }
      // Persist new sort order.
      const ordered_ids = surviving.map(r => r.id);
      if (ordered_ids.length > 0) {
        await api.post(`/api/jobs/${jobId}/deliverables/reorder/`, { ordered_ids });
      }
      onClose(true);
    } catch (err) {
      errorMsg = err.message || 'Save failed.';
    } finally {
      saving = false;
    }
  }

  function cancel() {
    onClose(false);
  }

  $effect(() => { if (jobId) load(); });
</script>

<div class="backdrop" onclick={cancel}>
  <div class="modal" onclick={(e) => e.stopPropagation()}>
    <h3>Edit deliverables</h3>
    {#if loading}
      <p>Loading...</p>
    {:else}
      <table border="1">
        <thead>
          <tr><th>#</th><th>Description</th><th>Qty</th><th>Units</th><th></th></tr>
        </thead>
        <tbody>
          {#each rows.filter(r => !r._deleted) as r, i (r.id || `new-${i}`)}
            <tr>
              <td>
                <button type="button" onclick={() => moveUp(i)}>↑</button>
                <button type="button" onclick={() => moveDown(i)}>↓</button>
              </td>
              <td><input bind:value={r.description} oninput={() => dirty = true} /></td>
              <td><input bind:value={r.qty_ordered} oninput={() => dirty = true} /></td>
              <td><input bind:value={r.units} oninput={() => dirty = true} /></td>
              <td><button type="button" onclick={() => deleteRow(rows.indexOf(r))}>Delete</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
      <p><button type="button" onclick={addRow}>+ Add row</button></p>
      {#if errorMsg}<p class="err">{errorMsg}</p>{/if}
      <p>
        <button type="button" onclick={save} disabled={saving || !dirty}>Save</button>
        <button type="button" onclick={cancel} disabled={saving}>Cancel</button>
      </p>
    {/if}
  </div>
</div>

<style>
  .backdrop {
    position: fixed; inset: 0; background: rgba(0,0,0,0.5);
    display: flex; align-items: center; justify-content: center;
    z-index: 1000;
  }
  .modal {
    background: white; padding: 1rem; min-width: 480px; max-width: 80vw;
    max-height: 80vh; overflow-y: auto;
  }
  .err { color: #c00; }
</style>
```

- [ ] **Step 2: Run build to verify both components compile**

Run: `cd frontend && npm run build`

Expected: Build completes without errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/jobs/DeliverablesEditModal.svelte
git commit -m "feat(frontend): add DeliverablesEditModal"
```

---

## Phase 10 — Frontend: JobDetail layout (three-column flex row + Shipments pillar slot)

### Task 10.1: Wire DeliverablesSection into JobDetail.svelte

**Files:**
- Modify: `frontend/src/components/jobs/JobDetail.svelte`

- [ ] **Step 1: Open JobDetail.svelte and locate the Description / History flex row**

Run: `grep -n "HistoryPanel\|description\|<div class=\"job-details\"\|flex" /Users/drshiny/Documents/konbini/Minibini/frontend/src/components/jobs/JobDetail.svelte | head -40`

Expected: lines around the Description + History flex row become visible.

- [ ] **Step 2: Add DeliverablesSection import**

In the `<script>` block of `JobDetail.svelte`, add (next to other component imports):

```javascript
  import DeliverablesSection from './DeliverablesSection.svelte';
```

- [ ] **Step 3: Insert DeliverablesSection between Description and History**

Locate the flex container that holds Description and HistoryPanel (search for `HistoryPanel`). The existing structure looks like:

```svelte
<div class="job-details-row">
  <div class="description-col">...</div>
  <HistoryPanel ... />
</div>
```

Modify it to a three-column layout:

```svelte
<div class="job-details-row">
  <div class="description-col">...</div>
  <DeliverablesSection jobId={job.id} />
  <HistoryPanel ... />
</div>
```

Update the surrounding CSS so the three columns share the row evenly. If the existing CSS uses `display: flex` with two columns, add a flex-basis tweak so the middle column gets reasonable width:

```css
.job-details-row {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
}
.job-details-row > * {
  flex: 1 1 0;
  min-width: 0;
}
```

(Adapt the exact class names to whatever is already in the file.)

- [ ] **Step 4: Run build to verify**

Run: `cd frontend && npm run build`

Expected: Build completes.

- [ ] **Step 5: Manual smoke test via dev server**

Run (in one terminal): `python manage.py runserver`
Run (in another): `cd frontend && npm run dev`

Open `http://localhost:9000/#/jobs/<some-job-id>` and confirm:
- Three-column layout renders with Description, Deliverables, History
- Empty state shows when no deliverables exist
- Click "Edit" opens the modal; add a row and save reloads the list

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/jobs/JobDetail.svelte
git commit -m "feat(frontend): three-column job detail row with Deliverables"
```

---

## Phase 11 — Frontend: ShipmentsPillar and JobShipmentsPage

### Task 11.1: Implement ShipmentsPillar (read-only matrix)

**Files:**
- Create: `frontend/src/components/jobs/ShipmentsPillar.svelte`

- [ ] **Step 1: Implement the component**

Create `frontend/src/components/jobs/ShipmentsPillar.svelte`:

```svelte
<script>
  import { api } from '../../lib/api.js';
  import { link } from 'svelte-spa-router';

  let { jobId } = $props();
  let deliverables = $state([]);
  let shipments = $state([]);
  let loading = $state(true);

  async function load() {
    loading = true;
    const [d, s] = await Promise.all([
      api.get(`/api/jobs/${jobId}/deliverables/`),
      api.get(`/api/shipments/?job=${jobId}`),
    ]);
    deliverables = d;
    shipments = (s.results || s).sort((a, b) => a.sequence - b.sequence);
    loading = false;
  }

  $effect(() => { if (jobId) load(); });

  function qtyAt(deliverableId, shipmentId) {
    const sh = shipments.find(x => x.id === shipmentId);
    if (!sh) return '';
    const item = (sh.items || []).find(it => it.deliverable === deliverableId);
    return item ? item.qty : '';
  }
</script>

<section class="shipments-pillar">
  <header>
    <strong>Shipments</strong>
    <a use:link href={`/jobs/${jobId}/shipments`}>Manage shipments</a>
  </header>

  {#if loading}
    <p>Loading...</p>
  {:else if deliverables.length === 0}
    <p>No deliverables; cannot ship.</p>
  {:else if shipments.length === 0}
    <p>No shipments yet.</p>
  {:else}
    <table border="1">
      <thead>
        <tr>
          <th>Deliverable</th>
          <th>Qty ordered</th>
          <th>Units</th>
          {#each shipments as sh}
            <th>
              Shipment #{sh.sequence}<br>
              <em>{sh.status === 'picked_up' ? 'picked up' : 'prepared'}</em><br>
              {new Date(sh.status === 'picked_up' ? sh.picked_up_date : sh.prepared_date).toLocaleDateString()}
            </th>
          {/each}
          <th>Remaining</th>
        </tr>
      </thead>
      <tbody>
        {#each deliverables as d}
          <tr>
            <td>{d.description}</td>
            <td>{d.qty_ordered}</td>
            <td>{d.units}</td>
            {#each shipments as sh}
              <td>{qtyAt(d.id, sh.id)}</td>
            {/each}
            <td>{d.qty_remaining}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  .shipments-pillar header {
    display: flex;
    align-items: baseline;
    gap: 1rem;
  }
</style>
```

- [ ] **Step 2: Wire into the accordion pillar list in JobDetail.svelte**

Open `frontend/src/components/jobs/JobDetail.svelte` and locate the accordion pillar list. Find the pillar order (`Worksheet | Estimate | Tasks | Invoice | Purchase Orders`). Add a Shipments pillar between Invoice and Purchase Orders.

The exact insertion depends on the existing pattern. Typical change shape:

```svelte
<script>
  // ... existing imports
  import ShipmentsPillar from './ShipmentsPillar.svelte';
</script>

{#each pillars as p}
  ...
{/each}
```

Add Shipments to the pillars array:

```javascript
const pillars = [
  { key: 'worksheet', label: 'Worksheet', ... },
  { key: 'estimate',  label: 'Estimate',  ... },
  { key: 'tasks',     label: 'Tasks',     ... },
  { key: 'invoice',   label: 'Invoice',   ... },
  { key: 'shipments', label: 'Shipments', component: ShipmentsPillar, props: { jobId: job.id } },
  { key: 'po',        label: 'Purchase Orders', ... },
];
```

Mirror the existing pattern from how Invoice or Tasks are wired (they're already in this file).

- [ ] **Step 3: Build**

Run: `cd frontend && npm run build`

Expected: Build completes.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/jobs/ShipmentsPillar.svelte frontend/src/components/jobs/JobDetail.svelte
git commit -m "feat(frontend): read-only Shipments pillar on Job detail"
```

### Task 11.2: Implement JobShipmentsPage (editable matrix)

**Files:**
- Create: `frontend/src/routes/jobs/JobShipmentsPage.svelte`
- Modify: `frontend/src/App.svelte`

- [ ] **Step 1: Implement the page**

Create `frontend/src/routes/jobs/JobShipmentsPage.svelte`:

```svelte
<script>
  import { api } from '../../lib/api.js';
  import { link } from 'svelte-spa-router';

  let { params } = $props();
  const jobId = $derived(parseInt(params.jobId, 10));

  let deliverables = $state([]);
  let shipments = $state([]);
  let job = $state(null);
  let loading = $state(true);
  let errorMsg = $state('');

  async function load() {
    loading = true;
    const [j, d, s] = await Promise.all([
      api.get(`/api/jobs/${jobId}/`),
      api.get(`/api/jobs/${jobId}/deliverables/`),
      api.get(`/api/shipments/?job=${jobId}`),
    ]);
    job = j;
    deliverables = d;
    shipments = (s.results || s).sort((a, b) => a.sequence - b.sequence);
    loading = false;
  }

  $effect(() => { if (jobId) load(); });

  function getItem(sh, deliverableId) {
    return (sh.items || []).find(it => it.deliverable === deliverableId);
  }

  async function addShipment() {
    try {
      await api.post(`/api/jobs/${jobId}/shipments/`, {});
      await load();
    } catch (e) { errorMsg = e.message; }
  }

  async function pickUp(sh) {
    try {
      await api.post(`/api/shipments/${sh.id}/pick-up/`, {});
      await load();
    } catch (e) { errorMsg = e.message; }
  }

  async function deleteShipment(sh) {
    if (!confirm(`Delete Shipment #${sh.sequence}?`)) return;
    try {
      await api.delete(`/api/shipments/${sh.id}/`);
      await load();
    } catch (e) { errorMsg = e.message; }
  }

  async function setQty(sh, deliverableId, value) {
    if (sh.status !== 'prepared') return;
    const trimmed = String(value || '').trim();
    const existing = getItem(sh, deliverableId);
    try {
      if (trimmed === '' || Number(trimmed) === 0) {
        if (existing) {
          await api.delete(`/api/shipments/${sh.id}/items/${existing.id}/`);
        }
      } else if (existing) {
        await api.patch(`/api/shipments/${sh.id}/items/${existing.id}/`, { qty: trimmed });
      } else {
        await api.post(`/api/shipments/${sh.id}/items/`, {
          deliverable: deliverableId,
          qty: trimmed,
        });
      }
      await load();
    } catch (e) { errorMsg = e.message; }
  }

  function printPackingList(sh) {
    window.open(`#/shipments/${sh.id}/print`, '_blank');
  }
</script>

{#if loading}
  <p>Loading...</p>
{:else}
  <header>
    <h2>Shipments for {job.job_number}: {job.name}</h2>
    <p><a use:link href={`/jobs/${jobId}`}>← Back to job</a></p>
    <p><button type="button" onclick={addShipment}>+ Add shipment</button></p>
    {#if errorMsg}<p style="color:#c00;">{errorMsg}</p>{/if}
  </header>

  {#if deliverables.length === 0}
    <p>This job has no deliverables yet.</p>
  {:else if shipments.length === 0}
    <p>No shipments yet. Click "Add shipment" to create one.</p>
  {:else}
    <table border="1">
      <thead>
        <tr>
          <th>Deliverable</th>
          <th>Qty ordered</th>
          <th>Units</th>
          {#each shipments as sh}
            <th>
              Shipment #{sh.sequence}<br>
              <em>{sh.status === 'picked_up' ? 'picked up' : 'prepared'}</em><br>
              {new Date(sh.status === 'picked_up' ? sh.picked_up_date : sh.prepared_date).toLocaleDateString()}<br>
              {#if sh.status === 'prepared'}
                <button type="button" onclick={() => pickUp(sh)}>Mark picked up</button>
              {/if}
              <button type="button" onclick={() => printPackingList(sh)}>Print packing list</button>
              {#if sh.status === 'prepared' && (sh.items || []).length === 0}
                <button type="button" onclick={() => deleteShipment(sh)}>Delete</button>
              {/if}
            </th>
          {/each}
          <th>Remaining</th>
        </tr>
      </thead>
      <tbody>
        {#each deliverables as d}
          <tr>
            <td>{d.description}</td>
            <td>{d.qty_ordered}</td>
            <td>{d.units}</td>
            {#each shipments as sh}
              <td>
                {#if sh.status === 'picked_up'}
                  {getItem(sh, d.id)?.qty ?? ''}
                {:else}
                  <input
                    style="width: 4em"
                    value={getItem(sh, d.id)?.qty ?? ''}
                    onblur={(e) => setQty(sh, d.id, e.target.value)}
                  />
                {/if}
              </td>
            {/each}
            <td>{d.qty_remaining}</td>
          </tr>
        {/each}
        <tr>
          <td colspan="3"><strong>Shipment total</strong></td>
          {#each shipments as sh}
            <td>{(sh.items || []).reduce((sum, it) => sum + Number(it.qty), 0)}</td>
          {/each}
          <td></td>
        </tr>
      </tbody>
    </table>
  {/if}
{/if}
```

- [ ] **Step 2: Register the route in App.svelte**

Modify `frontend/src/App.svelte`. Add the import next to other route imports:

```javascript
import JobShipmentsPage from './routes/jobs/JobShipmentsPage.svelte';
```

In the `routes` object, add a line near the existing job routes:

```javascript
'/jobs/:jobId/shipments': JobShipmentsPage,
```

- [ ] **Step 3: Build**

Run: `cd frontend && npm run build`

Expected: Build completes.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/jobs/JobShipmentsPage.svelte frontend/src/App.svelte
git commit -m "feat(frontend): add Job Shipments editable matrix page"
```

---

## Phase 12 — Frontend: PackingListPrint route

### Task 12.1: Implement the print view

**Files:**
- Create: `frontend/src/routes/shipments/PackingListPrint.svelte`
- Modify: `frontend/src/App.svelte`

- [ ] **Step 1: Implement the print view**

Create `frontend/src/routes/shipments/PackingListPrint.svelte`:

```svelte
<script>
  import { api } from '../../lib/api.js';

  let { params } = $props();
  const shipmentId = $derived(parseInt(params.sid, 10));

  let payload = $state(null);
  let loading = $state(true);

  async function load() {
    loading = true;
    payload = await api.get(`/api/shipments/${shipmentId}/packing-list/`);
    loading = false;
  }

  $effect(() => { if (shipmentId) load(); });
</script>

{#if loading}
  <p>Loading packing list...</p>
{:else if payload}
  <article class="packing-list">
    <h1>Packing list</h1>
    <p><strong>Job:</strong> {payload.job.job_number} — {payload.job.name}</p>
    <p><strong>Shipment #:</strong> {payload.shipment.sequence}</p>
    <p><strong>Status:</strong> {payload.shipment.status === 'picked_up' ? 'Picked up' : 'Prepared'}</p>
    <p><strong>Prepared:</strong> {new Date(payload.shipment.prepared_date).toLocaleString()}</p>
    {#if payload.shipment.picked_up_date}
      <p><strong>Picked up:</strong> {new Date(payload.shipment.picked_up_date).toLocaleString()}</p>
    {/if}

    <table border="1">
      <thead>
        <tr>
          <th>Description</th>
          <th>Units</th>
          <th>Qty ordered</th>
          <th>Previously delivered</th>
          <th>This shipment</th>
          <th>Remaining after this shipment</th>
        </tr>
      </thead>
      <tbody>
        {#each payload.rows as r}
          <tr>
            <td>{r.description}</td>
            <td>{r.units}</td>
            <td>{r.qty_ordered}</td>
            <td>{r.qty_previously_picked_up}</td>
            <td>{r.qty_this_shipment}</td>
            <td>{r.qty_remaining_after_this_shipment}</td>
          </tr>
        {/each}
      </tbody>
    </table>

    {#if payload.shipment.notes}
      <p><strong>Notes:</strong> {payload.shipment.notes}</p>
    {/if}
  </article>
{/if}

<style>
  .packing-list {
    max-width: 8.5in;
    margin: 0 auto;
    padding: 0.5in;
  }
  @media print {
    /* Hide app chrome when printing. */
    :global(.sidebar), :global(.current-blep-band) { display: none !important; }
  }
</style>
```

- [ ] **Step 2: Register the route in App.svelte**

In `frontend/src/App.svelte`:

```javascript
import PackingListPrint from './routes/shipments/PackingListPrint.svelte';
```

And in `routes`:

```javascript
'/shipments/:sid/print': PackingListPrint,
```

- [ ] **Step 3: Build**

Run: `cd frontend && npm run build`

Expected: Build completes.

- [ ] **Step 4: Manual smoke test**

Open the SPA, navigate to `#/shipments/<some-shipment-id>/print` directly (or via the Print packing list button on the JobShipmentsPage). Verify the print preview renders clean (no sidebar, no current-blep band).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/shipments/PackingListPrint.svelte frontend/src/App.svelte
git commit -m "feat(frontend): add printable packing list view"
```

---

## Phase 13 — Final integration check

### Task 13.1: Run the full test suite

- [ ] **Step 1: Run all backend tests**

Run: `python manage.py test -v 2`

Expected: All tests pass. Watch for any pre-existing tests that fail due to the `mark_open` deliverables guard — fix each by adding a Deliverable to the test setup.

- [ ] **Step 2: Run frontend build**

Run: `cd frontend && npm run build`

Expected: Build completes with no errors.

- [ ] **Step 3: Smoke test the full flow manually**

Start dev servers:
```bash
python manage.py runserver
# in another terminal:
cd frontend && npm run dev
```

Walk through:
1. Open a Job with no estimate. Verify Deliverables section shows "No deliverables yet. [Add deliverables]" with an edit link.
2. Add deliverables. Confirm they appear in the section.
3. Generate an estimate on the Job. Confirm the Deliverables section still shows "Edit" while the estimate is in draft.
4. Try to send the estimate (mark open) on a Job with no deliverables — confirm it's blocked with an error.
5. With deliverables present, send the estimate. Confirm Deliverables section now shows "(estimate sent)" and the Edit link is gone.
6. Revise the estimate (back to draft). Confirm Deliverables section is editable again.
7. Accept the estimate. Confirm Deliverables shows "(estimate accepted)" and is locked.
8. Open the Shipments pillar on the Job detail; confirm the read-only matrix appears with the deliverables and an empty shipment list.
9. Click Manage shipments. On the Job Shipments page, add a Shipment, then click cells to add items.
10. Try to add qty exceeding remaining; confirm rejection.
11. Mark the shipment picked up. Confirm cells become read-only.
12. Print the packing list. Confirm the print page renders.
13. Try to delete a picked-up shipment via API — confirm rejection.

- [ ] **Step 4: Commit any incidental fixes from smoke test**

```bash
git add ...
git commit -m "fix: smoke-test fallout"
```

Skip this step if no fixes were needed.

---

## Self-review checklist

Before marking the plan done, scan once more:

- [ ] No "TODO" / "TBD" / "fill in" placeholders
- [ ] Every test has actual code in the plan, not just a description
- [ ] Every model field name in tests matches the model definition (qty_ordered everywhere, not qty_ordered vs quantity)
- [ ] Every URL in tests matches the URL conf
- [ ] Every service method called in tests is defined in services.py
- [ ] Every Svelte component referenced is in the file map
- [ ] All DELETE responses return 200 + JSON
- [ ] No direct DB mutations outside services
- [ ] No `python manage.py migrate` step anywhere — only `makemigrations`

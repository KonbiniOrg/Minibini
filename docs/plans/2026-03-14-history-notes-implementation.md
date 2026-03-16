# History & Notes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an immutable audit trail and user notes system to the Minibini job shop application.

**Architecture:** A `@history` decorator marks models for tracking. Django signals (`post_init`, `pre_save`) capture field diffs. A middleware uses `contextvars` to collect pending changes per request and creates `HistoryEntry` records after the view completes. Signal handlers create their own action entries directly for system-initiated side effects. Notes are added via dedicated API endpoints.

**Tech Stack:** Django 5.2, Django REST Framework, MySQL, Svelte 5 frontend

**Design doc:** `docs/plans/2026-03-14-history-notes-design.md`

---

### Task 1: HistoryEntry Model

**Files:**
- Create: `apps/core/history.py`
- Modify: `apps/core/models.py`
- Test: `tests/test_history_model.py`

**Step 1: Write the failing test**

```python
# tests/test_history_model.py
from django.test import TestCase
from apps.core.models import HistoryEntry, User


class HistoryEntryModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')

    def test_create_audit_entry(self):
        entry = HistoryEntry.objects.create(
            entry_type='audit',
            object_type='estimate',
            object_id=1,
            user=self.user,
            changes={'status': {'old': 'draft', 'new': 'open'}},
        )
        self.assertEqual(entry.entry_type, 'audit')
        self.assertEqual(entry.object_type, 'estimate')
        self.assertEqual(entry.object_id, 1)
        self.assertEqual(entry.user, self.user)
        self.assertIsNotNone(entry.timestamp)
        self.assertEqual(entry.changes['status']['old'], 'draft')
        self.assertEqual(entry.text, '')

    def test_create_action_entry_with_reason(self):
        entry = HistoryEntry.objects.create(
            entry_type='action',
            object_type='job',
            object_id=1,
            user=None,
            changes={'status': {'old': 'submitted', 'new': 'approved'}},
            text='Estimate EST-2025-0001 accepted',
        )
        self.assertEqual(entry.entry_type, 'action')
        self.assertEqual(entry.text, 'Estimate EST-2025-0001 accepted')
        self.assertIsNone(entry.user)

    def test_create_note_entry(self):
        entry = HistoryEntry.objects.create(
            entry_type='note',
            object_type='job',
            object_id=1,
            user=self.user,
            text='Customer called to confirm delivery date.',
        )
        self.assertEqual(entry.entry_type, 'note')
        self.assertIsNone(entry.changes)
        self.assertEqual(entry.text, 'Customer called to confirm delivery date.')

    def test_ordering_newest_first(self):
        e1 = HistoryEntry.objects.create(
            entry_type='audit', object_type='job', object_id=1,
            changes={'name': {'old': 'A', 'new': 'B'}},
        )
        e2 = HistoryEntry.objects.create(
            entry_type='note', object_type='job', object_id=1,
            text='A note',
        )
        entries = list(HistoryEntry.objects.all())
        self.assertEqual(entries[0].pk, e2.pk)
        self.assertEqual(entries[1].pk, e1.pk)

    def test_entry_type_choices(self):
        valid_types = ['audit', 'action', 'note']
        for t in valid_types:
            entry = HistoryEntry(entry_type=t, object_type='job', object_id=1)
            entry.full_clean()  # should not raise
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_history_model -v2`
Expected: FAIL — `HistoryEntry` does not exist

**Step 3: Write minimal implementation**

Add to `apps/core/models.py`:

```python
class HistoryEntry(models.Model):
    ENTRY_TYPES = [
        ('audit', 'Audit'),
        ('action', 'Action'),
        ('note', 'Note'),
    ]

    entry_type = models.CharField(max_length=10, choices=ENTRY_TYPES)
    object_type = models.CharField(max_length=50)
    object_id = models.IntegerField()
    user = models.ForeignKey(
        'core.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='history_entries',
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    changes = models.JSONField(null=True, blank=True)
    text = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'history'
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.entry_type}: {self.object_type} #{self.object_id}"
```

**Step 4: Create migration**

Run: `python manage.py makemigrations core`

**Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_history_model -v2`
Expected: PASS — all 5 tests pass

**Step 6: Commit**

```bash
git add apps/core/models.py apps/core/migrations/ tests/test_history_model.py
git commit -m "add HistoryEntry model"
```

---

### Task 2: System User Fixture

**Files:**
- Modify: `fixtures/unit_test_data.json`
- Test: `tests/test_history_model.py` (add test)

**Step 1: Write the failing test**

Add to `tests/test_history_model.py`:

```python
from tests.base import BaseTestCase

class SystemUserTest(BaseTestCase):
    def test_system_user_exists(self):
        system = User.objects.get(username='system')
        self.assertTrue(system.is_active)
        self.assertFalse(system.is_superuser)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_history_model.SystemUserTest -v2`
Expected: FAIL — User matching query does not exist

**Step 3: Add System user to fixture**

Add a new User entry to `fixtures/unit_test_data.json` with username='system'. Use the next available pk (check existing fixture for current max pk). Set `is_active=true`, `is_superuser=false`, `is_staff=false`.

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_history_model.SystemUserTest -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add fixtures/unit_test_data.json tests/test_history_model.py
git commit -m "add System user to test fixtures"
```

---

### Task 3: @history Decorator with post_init Snapshot

**Files:**
- Create: `apps/core/history.py`
- Test: `tests/test_history_decorator.py`

**Step 1: Write the failing test**

```python
# tests/test_history_decorator.py
from django.test import TestCase
from tests.base import BaseTestCase
from apps.contacts.models import Contact


class HistoryDecoratorTest(BaseTestCase):
    def test_model_is_marked_as_tracked(self):
        """Tracked models have _history_tracked = True."""
        self.assertTrue(getattr(Contact, '_history_tracked', False))

    def test_model_has_exclude_set(self):
        """Tracked models have _history_exclude set."""
        self.assertIsInstance(Contact._history_exclude, set)

    def test_post_init_creates_snapshot(self):
        """Loading a tracked model from DB creates _history_original snapshot."""
        contact = Contact.objects.first()
        self.assertTrue(hasattr(contact, '_history_original'))
        self.assertIn('first_name', contact._history_original)
        self.assertEqual(contact._history_original['first_name'], contact.first_name)

    def test_snapshot_excludes_excluded_fields(self):
        """Excluded fields are not in the snapshot."""
        contact = Contact.objects.first()
        for field in Contact._history_exclude:
            self.assertNotIn(field, contact._history_original)

    def test_new_instance_has_empty_snapshot(self):
        """A brand new (unsaved) instance has _history_original = None."""
        contact = Contact(first_name='New', last_name='Person')
        self.assertIsNone(getattr(contact, '_history_original', 'missing'))
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_history_decorator -v2`
Expected: FAIL — `_history_tracked` not found on Contact

**Step 3: Write implementation**

```python
# apps/core/history.py
from django.db.models.signals import post_init


def _snapshot_fields(instance):
    """Capture current field values for later diffing."""
    if not instance.pk:
        instance._history_original = None
        return
    exclude = instance.__class__._history_exclude
    instance._history_original = {
        f.attname: getattr(instance, f.attname)
        for f in instance.__class__._meta.concrete_fields
        if f.attname not in exclude
    }


def _on_post_init(sender, instance, **kwargs):
    """Signal handler: snapshot field values when instance loads from DB."""
    _snapshot_fields(instance)


def history(exclude=None):
    """Decorator to mark a model for automatic history tracking."""
    def decorator(cls):
        cls._history_tracked = True
        cls._history_exclude = set(exclude or [])
        post_init.connect(_on_post_init, sender=cls, weak=False)
        return cls
    return decorator
```

Then apply the decorator to the Contact model (as one example to make the test pass). The decorator will be applied to all 9 models in Task 5.

In `apps/contacts/models.py`, add:

```python
from apps.core.history import history

@history(exclude=[])
class Contact(models.Model):
    ...
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_history_decorator -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/core/history.py apps/contacts/models.py tests/test_history_decorator.py
git commit -m "add @history decorator with post_init field snapshot"
```

---

### Task 4: History Middleware with Change Detection

**Files:**
- Modify: `apps/core/history.py` (add diff logic, contextvars, pre_save handler)
- Create: `apps/core/history_middleware.py`
- Modify: `minibini/settings.py` (add middleware)
- Test: `tests/test_history_middleware.py`

**Step 1: Write the failing tests**

```python
# tests/test_history_middleware.py
from django.test import TestCase, RequestFactory
from tests.base import BaseTestCase
from apps.core.models import HistoryEntry, User
from apps.contacts.models import Contact


class HistoryMiddlewareTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.get(username='admin')
        self.client.force_login(self.user)

    def test_field_change_creates_audit_entry(self):
        """Changing a tracked field via a request creates a history entry."""
        contact = Contact.objects.first()
        old_name = contact.first_name
        contact.first_name = 'Changed'
        contact.save()

        # History entry should exist after the request middleware processes
        entries = HistoryEntry.objects.filter(
            object_type='contact', object_id=contact.pk
        )
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertEqual(entry.entry_type, 'audit')
        self.assertEqual(entry.changes['first_name']['old'], old_name)
        self.assertEqual(entry.changes['first_name']['new'], 'Changed')

    def test_no_change_no_entry(self):
        """Saving without changes creates no history entry."""
        contact = Contact.objects.first()
        contact.save()
        entries = HistoryEntry.objects.filter(
            object_type='contact', object_id=contact.pk
        )
        self.assertEqual(entries.count(), 0)

    def test_excluded_field_only_no_entry(self):
        """Changing only excluded fields creates no history entry."""
        # This test depends on having an excluded field on the model.
        # If Contact has no excluded fields, apply @history(exclude=['some_field'])
        # and test accordingly. Skip if no excluded fields.
        pass

    def test_multiple_field_changes_single_entry(self):
        """Changing multiple fields creates one entry with all changes."""
        contact = Contact.objects.first()
        contact.first_name = 'NewFirst'
        contact.last_name = 'NewLast'
        contact.save()

        entries = HistoryEntry.objects.filter(
            object_type='contact', object_id=contact.pk
        )
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertIn('first_name', entry.changes)
        self.assertIn('last_name', entry.changes)

    def test_new_object_creation_creates_entry(self):
        """Creating a new tracked object creates an audit entry."""
        contact = Contact.objects.create(
            first_name='Brand', last_name='New', email='new@test.com'
        )
        entries = HistoryEntry.objects.filter(
            object_type='contact', object_id=contact.pk
        )
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertEqual(entry.entry_type, 'audit')
        # For new objects, changes should indicate creation
        self.assertIn('first_name', entry.changes)
        self.assertEqual(entry.changes['first_name']['old'], None)
        self.assertEqual(entry.changes['first_name']['new'], 'Brand')

    def test_entry_records_user_from_request(self):
        """History entries created during a request have the request user."""
        # Use the Django test client to make a real request
        contact = Contact.objects.first()
        response = self.client.patch(
            f'/api/contacts/{contact.pk}/',
            {'first_name': 'ViaAPI'},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        entry = HistoryEntry.objects.filter(
            object_type='contact', object_id=contact.pk
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.user, self.user)
```

Note: The `test_field_change_creates_audit_entry` and similar tests that call `.save()` directly (not through the API) will need the middleware active. In tests, the middleware runs when using `self.client` (Django test client). For direct `.save()` calls outside a request, entries will be created immediately by the pre_save handler with user=None. Adjust tests accordingly — the middleware batches entries for requests; outside requests, entries are created immediately.

**Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_history_middleware -v2`
Expected: FAIL — middleware not implemented

**Step 3: Write implementation**

Add to `apps/core/history.py` — the diff logic and pre_save handler:

```python
import contextvars
from django.db.models.signals import pre_save

# Request-scoped context
_history_context = contextvars.ContextVar('history_context', default=None)


class HistoryContext:
    """Holds pending changes and the request user for one request."""
    def __init__(self, user=None):
        self.user = user
        self.pending = []


def get_history_context():
    return _history_context.get(None)


def set_history_context(ctx):
    _history_context.set(ctx)


def _compute_diff(instance):
    """Compare current field values to snapshot, return changes dict."""
    original = getattr(instance, '_history_original', None)
    exclude = instance.__class__._history_exclude
    fields = {
        f.attname: f
        for f in instance.__class__._meta.concrete_fields
        if f.attname not in exclude
    }

    changes = {}
    if original is None:
        # New object — record all fields as old=None → new=value
        for attname in fields:
            new_val = getattr(instance, attname)
            if new_val is not None and new_val != '':
                changes[attname] = {'old': None, 'new': _serialize_value(new_val)}
    else:
        for attname, old_val in original.items():
            if attname not in fields:
                continue
            new_val = getattr(instance, attname)
            if old_val != new_val:
                changes[attname] = {
                    'old': _serialize_value(old_val),
                    'new': _serialize_value(new_val),
                }
    return changes


def _serialize_value(val):
    """Convert value to JSON-safe representation."""
    if val is None:
        return None
    if isinstance(val, (int, float, bool, str)):
        return val
    return str(val)


def _get_object_type(model_class):
    """Get the object_type string for a model class."""
    return model_class.__name__.lower()


def _on_pre_save(sender, instance, **kwargs):
    """Compute diff and either queue it (in request) or save immediately."""
    if not getattr(sender, '_history_tracked', False):
        return

    changes = _compute_diff(instance)
    if not changes:
        return

    from apps.core.models import HistoryEntry

    ctx = get_history_context()
    entry_data = {
        'entry_type': 'audit',
        'object_type': _get_object_type(sender),
        'object_id': instance.pk,
        'changes': changes,
    }

    if ctx is not None:
        # Inside a request — queue for batch creation with user
        entry_data['_instance'] = instance  # for getting pk after save
        ctx.pending.append(entry_data)
    else:
        # Outside a request — create immediately with no user
        if instance.pk:  # only if updating; new objects handled in post_save
            HistoryEntry.objects.create(**entry_data)
```

Note: For new objects, the `object_id` isn't known at `pre_save` time. The middleware needs to use a `post_save` handler to get the pk for new objects. Add a `_on_post_save` handler that fills in the pk for pending entries where `object_id` is None.

Create `apps/core/history_middleware.py`:

```python
from apps.core.history import HistoryContext, set_history_context, get_history_context


class HistoryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user if hasattr(request, 'user') and request.user.is_authenticated else None
        ctx = HistoryContext(user=user)
        set_history_context(ctx)

        try:
            response = self.get_response(request)
            # Create all pending history entries
            self._flush_pending(ctx)
            return response
        except Exception:
            # On error, discard pending entries (transaction will roll back)
            raise
        finally:
            set_history_context(None)

    def _flush_pending(self, ctx):
        from apps.core.models import HistoryEntry
        for entry_data in ctx.pending:
            instance = entry_data.pop('_instance', None)
            if instance and not entry_data.get('object_id'):
                entry_data['object_id'] = instance.pk
            entry_data['user'] = ctx.user
            HistoryEntry.objects.create(**entry_data)
```

Add to `minibini/settings.py` MIDDLEWARE list, after `AutoLoginMiddleware`:

```python
'apps.core.history_middleware.HistoryMiddleware',
```

**Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_history_middleware -v2`
Expected: PASS

Also run full suite to check for regressions:
Run: `python manage.py test`

**Step 5: Commit**

```bash
git add apps/core/history.py apps/core/history_middleware.py minibini/settings.py tests/test_history_middleware.py
git commit -m "add history middleware with change detection via contextvars"
```

---

### Task 5: Apply @history Decorator to All Tracked Models

**Files:**
- Modify: `apps/jobs/models.py` (Job, WorkOrder)
- Modify: `apps/estimates/models.py` (Estimate, EstWorksheet)
- Modify: `apps/invoicing/models.py` (Invoice)
- Modify: `apps/purchasing/models.py` (PurchaseOrder, Bill)
- Modify: `apps/contacts/models.py` (Contact already done in Task 3, add Business)
- Test: `tests/test_history_all_models.py`

**Step 1: Write the failing test**

```python
# tests/test_history_all_models.py
from django.test import TestCase
from apps.jobs.models import Job, WorkOrder
from apps.estimates.models import Estimate, EstWorksheet
from apps.invoicing.models import Invoice
from apps.purchasing.models import PurchaseOrder, Bill
from apps.contacts.models import Contact, Business


class AllTrackedModelsTest(TestCase):
    """Verify all intended models are decorated with @history."""

    TRACKED_MODELS = [
        Job, Estimate, EstWorksheet, WorkOrder,
        Invoice, PurchaseOrder, Bill, Contact, Business,
    ]

    def test_all_models_are_tracked(self):
        for model in self.TRACKED_MODELS:
            with self.subTest(model=model.__name__):
                self.assertTrue(
                    getattr(model, '_history_tracked', False),
                    f'{model.__name__} is not decorated with @history'
                )

    def test_all_models_have_exclude_set(self):
        for model in self.TRACKED_MODELS:
            with self.subTest(model=model.__name__):
                self.assertIsInstance(
                    getattr(model, '_history_exclude', None),
                    set,
                    f'{model.__name__} missing _history_exclude'
                )
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_history_all_models -v2`
Expected: FAIL — most models not yet decorated

**Step 3: Apply decorator to each model**

Add `from apps.core.history import history` and `@history(exclude=[...])` to each model class. Choose exclude lists per model — generally exclude auto-updated timestamp fields. Review each model file to identify which fields to exclude.

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_history_all_models -v2`
Expected: PASS

Run full suite: `python manage.py test`

**Step 5: Commit**

```bash
git add apps/jobs/models.py apps/estimates/models.py apps/invoicing/models.py apps/purchasing/models.py apps/contacts/models.py tests/test_history_all_models.py
git commit -m "apply @history decorator to all tracked models"
```

---

### Task 6: Signal Handlers Create Action Entries

**Files:**
- Modify: `apps/estimates/signals.py`
- Test: `tests/test_history_signals.py`

The `update_job_status` signal handler should create an action-type HistoryEntry with user=System and a reason when it changes the job's status as a side effect.

**Step 1: Write the failing test**

```python
# tests/test_history_signals.py
from tests.base import BaseTestCase
from apps.core.models import HistoryEntry, User
from apps.estimates.models import Estimate
from apps.estimates.signals import estimate_status_changed_for_job


class SignalHistoryTest(BaseTestCase):
    def test_job_status_change_from_signal_creates_action_entry(self):
        """When a signal changes job status, an action entry is created with System user and reason."""
        system_user = User.objects.get(username='system')
        estimate = Estimate.objects.first()
        job = estimate.job

        # Trigger the signal
        estimate_status_changed_for_job.send(
            sender=Estimate,
            estimate=estimate,
            new_job_status='approved',
        )

        entries = HistoryEntry.objects.filter(
            object_type='job',
            object_id=job.pk,
            entry_type='action',
        )
        self.assertTrue(entries.exists())
        entry = entries.first()
        self.assertEqual(entry.user, system_user)
        self.assertIn(estimate.estimate_number, entry.text)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_history_signals -v2`
Expected: FAIL — no action entry created

**Step 3: Modify signal handler**

In `apps/estimates/signals.py`, update `update_job_status` to create a HistoryEntry after changing the job status:

```python
@receiver(estimate_status_changed_for_job)
def update_job_status(sender, estimate, new_job_status, **kwargs):
    from apps.jobs.models import Job
    from apps.core.models import HistoryEntry, User

    job = estimate.job
    if job.status in ['completed', 'cancelled']:
        return 0

    if job.status != new_job_status:
        old_status = job.status
        system_user = User.objects.get(username='system')
        reason = f'Estimate {estimate.estimate_number} accepted'

        # ... existing transition logic ...

        # Create action entry
        HistoryEntry.objects.create(
            entry_type='action',
            object_type='job',
            object_id=job.pk,
            user=system_user,
            changes={'status': {'old': old_status, 'new': new_job_status}},
            text=reason,
        )
    return 0
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_history_signals -v2`
Expected: PASS

Run full suite: `python manage.py test`

**Step 5: Commit**

```bash
git add apps/estimates/signals.py tests/test_history_signals.py
git commit -m "add action history entries from signal-driven status changes"
```

---

### Task 7: History API Endpoints

**Files:**
- Create: `apps/api/history/serializers.py`
- Create: `apps/api/history/views.py`
- Create: `apps/api/history/__init__.py`
- Modify: `apps/api/urls.py`
- Modify: `apps/api/jobs/views.py` (add history action)
- Modify: `apps/api/contacts/views.py` (add history action to ContactViewSet)
- Modify: `apps/api/purchasing/views.py` (add history action to BusinessViewSet — check actual location)
- Test: `tests/test_api_history.py`

**Step 1: Write the failing tests**

```python
# tests/test_api_history.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import HistoryEntry, User


class JobHistoryAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_job_history_returns_entries(self):
        """GET /api/jobs/{id}/history/ returns history entries."""
        from apps.jobs.models import Job
        job = Job.objects.first()

        # Create some history entries
        HistoryEntry.objects.create(
            entry_type='audit', object_type='job', object_id=job.pk,
            user=self.user, changes={'name': {'old': 'A', 'new': 'B'}},
        )
        HistoryEntry.objects.create(
            entry_type='note', object_type='job', object_id=job.pk,
            user=self.user, text='A note on the job',
        )

        response = self.client.get(f'/api/jobs/{job.pk}/history/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)

    def test_job_history_aggregates_related_objects(self):
        """Job history includes entries from related estimates, work orders, etc."""
        from apps.jobs.models import Job
        from apps.estimates.models import Estimate
        job = Job.objects.first()
        estimate = Estimate.objects.filter(job=job).first()
        if not estimate:
            self.skipTest('No estimate in fixtures for this job')

        HistoryEntry.objects.create(
            entry_type='audit', object_type='job', object_id=job.pk,
            changes={'status': {'old': 'draft', 'new': 'submitted'}},
        )
        HistoryEntry.objects.create(
            entry_type='audit', object_type='estimate', object_id=estimate.pk,
            changes={'status': {'old': 'draft', 'new': 'open'}},
        )

        response = self.client.get(f'/api/jobs/{job.pk}/history/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)

    def test_job_history_ordered_newest_first(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        e1 = HistoryEntry.objects.create(
            entry_type='audit', object_type='job', object_id=job.pk,
            changes={'name': {'old': 'A', 'new': 'B'}},
        )
        e2 = HistoryEntry.objects.create(
            entry_type='note', object_type='job', object_id=job.pk,
            text='Later note',
        )
        response = self.client.get(f'/api/jobs/{job.pk}/history/')
        results = response.data['results']
        self.assertEqual(results[0]['id'], e2.pk)


class ContactHistoryAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_contact_history(self):
        from apps.contacts.models import Contact
        contact = Contact.objects.first()
        HistoryEntry.objects.create(
            entry_type='audit', object_type='contact', object_id=contact.pk,
            changes={'first_name': {'old': 'A', 'new': 'B'}},
        )
        response = self.client.get(f'/api/contacts/{contact.pk}/history/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)


class BusinessHistoryAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_business_history_aggregates_contacts(self):
        """Business history includes entries from its contacts."""
        from apps.contacts.models import Contact, Business
        business = Business.objects.first()
        contact = Contact.objects.filter(business=business).first()
        if not contact:
            self.skipTest('No contact for this business in fixtures')

        HistoryEntry.objects.create(
            entry_type='audit', object_type='business', object_id=business.pk,
            changes={'business_name': {'old': 'A', 'new': 'B'}},
        )
        HistoryEntry.objects.create(
            entry_type='audit', object_type='contact', object_id=contact.pk,
            changes={'first_name': {'old': 'X', 'new': 'Y'}},
        )

        response = self.client.get(f'/api/businesses/{business.pk}/history/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)
```

**Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_api_history -v2`
Expected: FAIL — endpoints don't exist

**Step 3: Write implementation**

Create serializer:

```python
# apps/api/history/serializers.py
from rest_framework import serializers
from apps.core.models import HistoryEntry


class HistoryEntrySerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True, default=None)

    class Meta:
        model = HistoryEntry
        fields = ['id', 'entry_type', 'object_type', 'object_id',
                  'user', 'username', 'timestamp', 'changes', 'text']
        read_only_fields = fields
```

Add `@action` endpoints to the relevant viewsets. For JobViewSet, the history action needs to aggregate entries from the job and all related objects. Query pattern:

```python
from django.db.models import Q

# Get IDs of all related objects
estimate_ids = Estimate.objects.filter(job=job).values_list('pk', flat=True)
worksheet_ids = EstWorksheet.objects.filter(job=job).values_list('pk', flat=True)
wo_ids = WorkOrder.objects.filter(job=job).values_list('pk', flat=True)
invoice_ids = Invoice.objects.filter(job=job).values_list('pk', flat=True)
po_ids = PurchaseOrder.objects.filter(job=job).values_list('pk', flat=True)
bill_ids = Bill.objects.filter(purchase_order__job=job).values_list('pk', flat=True)

entries = HistoryEntry.objects.filter(
    Q(object_type='job', object_id=job.pk) |
    Q(object_type='estimate', object_id__in=estimate_ids) |
    Q(object_type='estworksheet', object_id__in=worksheet_ids) |
    Q(object_type='workorder', object_id__in=wo_ids) |
    Q(object_type='invoice', object_id__in=invoice_ids) |
    Q(object_type='purchaseorder', object_id__in=po_ids) |
    Q(object_type='bill', object_id__in=bill_ids)
)
```

For BusinessViewSet, aggregate business + its contacts:

```python
contact_ids = Contact.objects.filter(business=business).values_list('pk', flat=True)
entries = HistoryEntry.objects.filter(
    Q(object_type='business', object_id=business.pk) |
    Q(object_type='contact', object_id__in=contact_ids)
)
```

For ContactViewSet, just the contact:

```python
entries = HistoryEntry.objects.filter(object_type='contact', object_id=contact.pk)
```

All endpoints are paginated and ordered newest first (model default ordering handles this).

**Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_api_history -v2`
Expected: PASS

Run full suite: `python manage.py test`

**Step 5: Commit**

```bash
git add apps/api/history/ apps/api/urls.py apps/api/jobs/views.py apps/api/contacts/views.py tests/test_api_history.py
git commit -m "add history API endpoints with aggregation"
```

---

### Task 8: Notes API Endpoints

**Files:**
- Modify: `apps/api/jobs/views.py`
- Modify: `apps/api/contacts/views.py`
- Modify: relevant business viewset file
- Test: `tests/test_api_notes.py`

**Step 1: Write the failing tests**

```python
# tests/test_api_notes.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import HistoryEntry, User


class JobNotesAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_add_note_to_job(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        response = self.client.post(
            f'/api/jobs/{job.pk}/notes/',
            {'text': 'Customer called about delivery.'},
        )
        self.assertEqual(response.status_code, 201)
        entry = HistoryEntry.objects.get(pk=response.data['id'])
        self.assertEqual(entry.entry_type, 'note')
        self.assertEqual(entry.object_type, 'job')
        self.assertEqual(entry.object_id, job.pk)
        self.assertEqual(entry.user, self.user)
        self.assertEqual(entry.text, 'Customer called about delivery.')
        self.assertIsNone(entry.changes)

    def test_add_note_requires_text(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        response = self.client.post(f'/api/jobs/{job.pk}/notes/', {})
        self.assertEqual(response.status_code, 400)

    def test_add_empty_note_rejected(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        response = self.client.post(f'/api/jobs/{job.pk}/notes/', {'text': ''})
        self.assertEqual(response.status_code, 400)

    def test_notes_are_immutable_no_patch(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        entry = HistoryEntry.objects.create(
            entry_type='note', object_type='job', object_id=job.pk,
            user=self.user, text='Original note',
        )
        response = self.client.patch(
            f'/api/jobs/{job.pk}/notes/{entry.pk}/',
            {'text': 'Modified'},
        )
        self.assertEqual(response.status_code, 405)

    def test_notes_are_immutable_no_delete(self):
        from apps.jobs.models import Job
        job = Job.objects.first()
        entry = HistoryEntry.objects.create(
            entry_type='note', object_type='job', object_id=job.pk,
            user=self.user, text='Original note',
        )
        response = self.client.delete(f'/api/jobs/{job.pk}/notes/{entry.pk}/')
        self.assertEqual(response.status_code, 405)


class ContactNotesAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_add_note_to_contact(self):
        from apps.contacts.models import Contact
        contact = Contact.objects.first()
        response = self.client.post(
            f'/api/contacts/{contact.pk}/notes/',
            {'text': 'Preferred morning calls.'},
        )
        self.assertEqual(response.status_code, 201)
        entry = HistoryEntry.objects.get(pk=response.data['id'])
        self.assertEqual(entry.object_type, 'contact')
        self.assertEqual(entry.object_id, contact.pk)


class BusinessNotesAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_add_note_to_business(self):
        from apps.contacts.models import Business
        business = Business.objects.first()
        response = self.client.post(
            f'/api/businesses/{business.pk}/notes/',
            {'text': 'Net 30 terms confirmed.'},
        )
        self.assertEqual(response.status_code, 201)
        entry = HistoryEntry.objects.get(pk=response.data['id'])
        self.assertEqual(entry.object_type, 'business')
        self.assertEqual(entry.object_id, business.pk)
```

**Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_api_notes -v2`
Expected: FAIL — endpoints don't exist

**Step 3: Write implementation**

Add `@action` to each viewset. The note action is simple — create a HistoryEntry with entry_type='note'. Example for JobViewSet:

```python
@action(detail=True, methods=['post'], url_path='notes', url_name='notes')
def notes(self, request, pk=None):
    job = self.get_object()
    text = request.data.get('text', '').strip()
    if not text:
        return Response(
            {'text': ['This field is required.']},
            status=status.HTTP_400_BAD_REQUEST,
        )
    entry = HistoryEntry.objects.create(
        entry_type='note',
        object_type='job',
        object_id=job.pk,
        user=request.user,
        text=text,
    )
    serializer = HistoryEntrySerializer(entry)
    return Response(serializer.data, status=status.HTTP_201_CREATED)
```

Same pattern for ContactViewSet and BusinessViewSet with appropriate object_type.

**Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_api_notes -v2`
Expected: PASS

Run full suite: `python manage.py test`

**Step 5: Commit**

```bash
git add apps/api/jobs/views.py apps/api/contacts/views.py tests/test_api_notes.py
git commit -m "add notes API endpoints for job, contact, business"
```

---

### Task 9: Frontend — History Section on Job Detail

**Files:**
- Modify: `frontend/src/routes/jobs/JobDetailPage.svelte`
- Modify: `frontend/src/components/jobs/JobDetail.svelte`

**Step 1: Update JobDetailPage to load history**

Add history loading to the data fetch in `JobDetailPage.svelte`:

```javascript
// In the loadJob function, add to Promise.all:
api.get(`/api/jobs/${params.id}/history/`)
```

Pass `history` data down to `JobDetail` component.

**Step 2: Update JobDetail component**

Add History section to `JobDetail.svelte`:

- Note input at top: `<textarea>` + submit button, calls `POST /api/jobs/{id}/notes/` via an `onAddNote` callback
- History feed below, newest first (API returns this order)
- Each entry shows: timestamp, username (or "System"), entry type, object type, changes or text
- Non-note entries in smaller font: wrap audit/action entries in `<small>`
- View mode: use `$derived` to filter — lite shows only notes, full shows all
- Show "No history" when empty

**Step 3: Verify build passes**

Run: `cd frontend && npx vite build`

**Step 4: Commit**

```bash
git add frontend/src/routes/jobs/JobDetailPage.svelte frontend/src/components/jobs/JobDetail.svelte
git commit -m "add history section to job detail frontend"
```

---

### Task 10: Frontend — History Section on Contact and Business Detail

**Files:**
- Modify: `frontend/src/routes/contacts/ContactDetailPage.svelte`
- Modify: `frontend/src/components/contacts/ContactDetail.svelte`
- Modify: `frontend/src/routes/contacts/BusinessDetailPage.svelte`
- Modify: `frontend/src/components/contacts/BusinessDetail.svelte`

**Step 1: Update detail pages to load history**

Add history loading to both `ContactDetailPage.svelte` and `BusinessDetailPage.svelte`, same pattern as Job.

**Step 2: Update detail components**

Add History section to both `ContactDetail.svelte` and `BusinessDetail.svelte`:

- Same pattern as JobDetail: note input at top, history feed below
- Lite view shows notes only, full shows all
- Non-note entries in smaller font
- Contact notes endpoint: `POST /api/contacts/{id}/notes/`
- Business notes endpoint: `POST /api/businesses/{id}/notes/`

**Step 3: Verify build passes**

Run: `cd frontend && npx vite build`

**Step 4: Commit**

```bash
git add frontend/src/routes/contacts/ frontend/src/components/contacts/
git commit -m "add history section to contact and business detail frontend"
```

---

## Discipline Reminder

**Never use `QuerySet.update()` on tracked models.** Always load the instance and call `.save()` so that `post_init`/`pre_save` fire and history is captured. This extends the existing codebase convention around custom `delete()` methods.

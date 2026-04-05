# Task View and Blep Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flesh out the Svelte task detail page, add blep editing (own-within-24h vs. manager via `can_manage_time`), and add a Recent Time list to the home page. Extract all blep writes into a new `BlepService` ahead of the feature work.

**Architecture:** Backend gains a `BlepService` that owns all `Blep` CRUD; `TaskLifecycleService` is refactored to delegate to it (no behavior change). A new top-level `BlepViewSet` exposes list/retrieve/create/update/delete via `/api/bleps/`, replacing the removed `/api/tasks/{id}/bleps/` nested action. Frontend adds `TaskDetailPage`, `TaskActions`, `BlepList`, `BlepEditModal`, `StartWorkConflictModal`, and `RecentTimeList` components.

**Tech Stack:** Django 5.2, DRF, Svelte 5 runes, Vite. Tests: Django TestCase.

**Reference doc:** `docs/designs/2026-04-04-task-view-and-blep-editing-design.md`

---

## File structure

**Backend — new files:**
- `apps/jobs/services/blep_service.py` — `BlepService` (primitives + public methods)
- `apps/api/bleps/__init__.py`
- `apps/api/bleps/serializers.py` — `BlepSerializer` (moved from `work_orders/serializers.py`)
- `apps/api/bleps/views.py` — `BlepViewSet`
- `apps/api/tasks/serializers.py` — `TaskDetailSerializer` (richer nested serializer for retrieve)
- `tests/test_blep_service.py`
- `tests/test_api_bleps.py`

**Backend — modified:**
- `apps/jobs/services/__init__.py` — delegate blep writes in `TaskLifecycleService`
- `apps/api/work_orders/serializers.py` — drop `BlepSerializer`
- `apps/api/tasks/views.py` — add retrieve, drop `bleps` action
- `apps/api/urls.py` — register `BlepViewSet`
- `tests/test_task_lifecycle_api.py` — drop `test_bleps_list`
- `tests/test_atom_api_permissions.py` — add blep endpoints

**Frontend — new files:**
- `frontend/src/components/tasks/TaskActions.svelte`
- `frontend/src/components/tasks/BlepList.svelte`
- `frontend/src/components/tasks/BlepEditModal.svelte`
- `frontend/src/components/tasks/StartWorkConflictModal.svelte`
- `frontend/src/components/home/RecentTimeList.svelte`

**Frontend — modified:**
- `frontend/src/routes/jobs/TaskDetailPage.svelte` — currently a stub; full rewrite
- `frontend/src/routes/Home.svelte` — mount `RecentTimeList` above Expenses

---

## Chunk 1 — Backend refactor (no behavior change)

### Task 1: Create `BlepService` with primitives

**Files:**
- Create: `apps/jobs/services/blep_service.py`
- Test: `tests/test_blep_service.py`

- [ ] **Step 1: Write failing tests for primitives**

Create `tests/test_blep_service.py`:

```python
from django.utils import timezone
from datetime import timedelta

from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job, WorkOrder, Task, Blep
from apps.jobs.services.blep_service import BlepService


class BlepServicePrimitivesTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='Task', work_order=self.wo)
        self.other_task = Task.objects.create(name='Other', work_order=self.wo)
        self.user = User.objects.get(username='admin')
        self.other_user = User.objects.create_user(username='worker2', password='x')

    def test_create_returns_open_blep(self):
        blep = BlepService._create(self.task, self.user)
        self.assertIsNotNone(blep.start_time)
        self.assertIsNone(blep.end_time)
        self.assertEqual(blep.user, self.user)
        self.assertEqual(blep.task, self.task)

    def test_create_with_explicit_times(self):
        start = timezone.now() - timedelta(hours=2)
        end = timezone.now() - timedelta(hours=1)
        blep = BlepService._create(self.task, self.user, start_time=start, end_time=end)
        self.assertEqual(blep.start_time, start)
        self.assertEqual(blep.end_time, end)

    def test_close_open_by_user_closes_all_user_bleps(self):
        b1 = Blep.objects.create(task=self.task, user=self.user, start_time=timezone.now())
        b2 = Blep.objects.create(task=self.other_task, user=self.user, start_time=timezone.now())
        # Another user's blep should NOT be closed.
        other = Blep.objects.create(task=self.task, user=self.other_user, start_time=timezone.now())
        BlepService._close_open(user=self.user)
        b1.refresh_from_db(); b2.refresh_from_db(); other.refresh_from_db()
        self.assertIsNotNone(b1.end_time)
        self.assertIsNotNone(b2.end_time)
        self.assertIsNone(other.end_time)

    def test_close_open_by_user_and_task_scoped(self):
        on_task = Blep.objects.create(task=self.task, user=self.user, start_time=timezone.now())
        other_task_blep = Blep.objects.create(task=self.other_task, user=self.user, start_time=timezone.now())
        BlepService._close_open(user=self.user, task=self.task)
        on_task.refresh_from_db(); other_task_blep.refresh_from_db()
        self.assertIsNotNone(on_task.end_time)
        self.assertIsNone(other_task_blep.end_time)

    def test_close_open_by_task_closes_all_workers(self):
        mine = Blep.objects.create(task=self.task, user=self.user, start_time=timezone.now())
        theirs = Blep.objects.create(task=self.task, user=self.other_user, start_time=timezone.now())
        BlepService._close_open(task=self.task)
        mine.refresh_from_db(); theirs.refresh_from_db()
        self.assertIsNotNone(mine.end_time)
        self.assertIsNotNone(theirs.end_time)

    def test_close_open_requires_filter(self):
        with self.assertRaises(ValueError):
            BlepService._close_open()
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_blep_service --noinput -v 2`
Expected: ImportError — `apps.jobs.services.blep_service` does not exist.

- [ ] **Step 3: Implement the service**

Create `apps/jobs/services/blep_service.py`:

```python
from django.utils import timezone

from apps.jobs.models import Blep


class BlepService:
    """All Blep (time entry) writes flow through this service.

    Primitives (leading underscore) skip validation — for trusted internal
    callers like TaskLifecycleService. Public methods enforce ownership,
    time windows, and overlap rules for user-initiated edits.
    """

    # ─────────────────────────── primitives ───────────────────────────

    @staticmethod
    def _create(task, user, start_time=None, end_time=None):
        """Create a Blep. `start_time` defaults to now."""
        if start_time is None:
            start_time = timezone.now()
        return Blep.objects.create(
            task=task, user=user,
            start_time=start_time, end_time=end_time,
        )

    @staticmethod
    def _close_open(user=None, task=None, now=None):
        """Close all open Bleps matching the given filter.

        At least one of `user` or `task` must be provided.
        """
        if user is None and task is None:
            raise ValueError("_close_open requires user or task filter")
        if now is None:
            now = timezone.now()
        qs = Blep.objects.filter(end_time__isnull=True)
        if user is not None:
            qs = qs.filter(user=user)
        if task is not None:
            qs = qs.filter(task=task)
        qs.update(end_time=now)
```

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_blep_service --noinput -v 2`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services/blep_service.py tests/test_blep_service.py
git commit -m "add BlepService with primitives for internal callers"
```

---

### Task 2: Refactor `TaskLifecycleService` to delegate blep writes

**Files:**
- Modify: `apps/jobs/services/__init__.py` (TaskLifecycleService methods)
- Validate against: `tests/test_task_lifecycle.py` (must still pass unchanged)

- [ ] **Step 1: Verify current tests pass**

Run: `python manage.py test tests.test_task_lifecycle tests.test_task_lifecycle_api --noinput`
Expected: PASS. This locks in the baseline — the refactor must not change behavior.

- [ ] **Step 2: Replace inline Blep writes with BlepService calls**

Edit `apps/jobs/services/__init__.py`. Add import at top of file:

```python
from apps.jobs.services.blep_service import BlepService
```

Replace in `TaskLifecycleService.complete_task`:

```python
# OLD:
now = timezone.now()
Blep.objects.filter(task=task, end_time__isnull=True).update(end_time=now)
# NEW:
BlepService._close_open(task=task)
```

Replace the same pattern in `cancel_task`:

```python
# OLD:
now = timezone.now()
Blep.objects.filter(task=task, end_time__isnull=True).update(end_time=now)
# NEW:
BlepService._close_open(task=task)
```

Replace in `start_work` (the pending-branch AND the in_progress-branch). The pending branch currently reads:

```python
# OLD in pending branch:
Blep.objects.filter(user=user, end_time__isnull=True).update(end_time=now)
Task.objects.filter(pk=task.pk).update(status=Task.STATUS_IN_PROGRESS)
task.status = Task.STATUS_IN_PROGRESS
from apps.inventory.services import InventoryService
for material in task.materials.all():
    InventoryService.consume_material(material)
blep = Blep.objects.create(task=task, user=user, start_time=now)
```

Replace with:

```python
# NEW in pending branch:
BlepService._close_open(user=user, now=now)
Task.objects.filter(pk=task.pk).update(status=Task.STATUS_IN_PROGRESS)
task.status = Task.STATUS_IN_PROGRESS
from apps.inventory.services import InventoryService
for material in task.materials.all():
    InventoryService.consume_material(material)
blep = BlepService._create(task, user, start_time=now)
```

And the in_progress branch tail:

```python
# OLD:
Blep.objects.filter(user=user, end_time__isnull=True).update(end_time=now)
if action == 'takeover':
    other_bleps.update(end_time=now)
blep = Blep.objects.create(task=task, user=user, start_time=now)
# NEW:
BlepService._close_open(user=user, now=now)
if action == 'takeover':
    other_bleps.update(end_time=now)
blep = BlepService._create(task, user, start_time=now)
```

Replace `stop_work` body:

```python
# OLD:
@staticmethod
def stop_work(task_pk, user):
    """Close user's open Blep on this task."""
    with transaction.atomic():
        updated = Blep.objects.filter(
            task_id=task_pk, user=user, end_time__isnull=True
        ).update(end_time=timezone.now())
        if not updated:
            raise ValidationError(
                "No open time entry found for this user on this task."
            )
# NEW:
@staticmethod
def stop_work(task_pk, user):
    """Close user's open Blep on this task."""
    from apps.jobs.models import Task
    with transaction.atomic():
        task = Task.objects.get(pk=task_pk)
        if not Blep.objects.filter(
            task=task, user=user, end_time__isnull=True
        ).exists():
            raise ValidationError(
                "No open time entry found for this user on this task."
            )
        BlepService._close_open(user=user, task=task)
```

Leave `block_task` alone — it only checks for open bleps, it doesn't close them (it rejects the transition if any exist).

- [ ] **Step 3: Run tests to verify no regression**

Run: `python manage.py test tests.test_task_lifecycle tests.test_task_lifecycle_api tests.test_blep_service --noinput`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/jobs/services/__init__.py
git commit -m "refactor TaskLifecycleService to use BlepService primitives"
```

---

### Task 3: Move `BlepSerializer` into new bleps module

**Files:**
- Create: `apps/api/bleps/__init__.py` (empty)
- Create: `apps/api/bleps/serializers.py`
- Modify: `apps/api/work_orders/serializers.py` (remove `BlepSerializer`)
- Modify: `apps/api/mixins.py` (update import in the removed-but-not-yet-deleted `task_bleps` path — actually this was removed earlier on this branch, verify)

- [ ] **Step 1: Create the new module and serializer**

Create `apps/api/bleps/__init__.py` with no content.

Create `apps/api/bleps/serializers.py`:

```python
from rest_framework import serializers
from apps.jobs.models import Blep


class BlepSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    task_name = serializers.CharField(source='task.name', read_only=True)
    job_id = serializers.IntegerField(source='task.work_order.job_id', read_only=True)
    job_number = serializers.CharField(source='task.work_order.job.job_number', read_only=True)
    job_name = serializers.CharField(source='task.work_order.job.name', read_only=True)

    class Meta:
        model = Blep
        fields = [
            'blep_id', 'user', 'user_name',
            'task', 'task_name',
            'job_id', 'job_number', 'job_name',
            'start_time', 'end_time',
        ]
        read_only_fields = ['blep_id', 'user_name', 'task_name',
                             'job_id', 'job_number', 'job_name']

    def get_user_name(self, obj):
        if obj.user is None:
            return None
        return obj.user.get_full_name() or obj.user.username
```

- [ ] **Step 2: Remove old BlepSerializer from work_orders**

Edit `apps/api/work_orders/serializers.py`:

- Remove the `BlepSerializer` class (lines 39–43).
- Update the top import line from `from apps.jobs.models import WorkOrder, Blep, Task, TaskBundle` to `from apps.jobs.models import WorkOrder, Task, TaskBundle` (drop `Blep` since nothing in this file still references it).

- [ ] **Step 3: Search for other imports of BlepSerializer**

Run: `grep -rn "BlepSerializer" apps/ tests/`
Expected: only the new `apps/api/bleps/serializers.py` and no stale references. If any other file imports it, update the import path to `from apps.api.bleps.serializers import BlepSerializer`.

- [ ] **Step 4: Run tests to confirm nothing broke**

Run: `python manage.py test tests.test_api_work_orders tests.test_task_lifecycle_api --noinput`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/bleps/__init__.py apps/api/bleps/serializers.py apps/api/work_orders/serializers.py
git commit -m "move BlepSerializer into apps/api/bleps module"
```

---

## Chunk 2 — Top-level BlepViewSet (read-only first)

### Task 4: Create `BlepViewSet` with list + retrieve, remove nested list

**Files:**
- Create: `apps/api/bleps/views.py`
- Modify: `apps/api/urls.py`
- Modify: `apps/api/tasks/views.py` (remove `bleps` action)
- Modify: `tests/test_task_lifecycle_api.py` (remove `test_bleps_list`)
- Test: `tests/test_api_bleps.py`

- [ ] **Step 1: Write failing tests for list and retrieve**

Create `tests/test_api_bleps.py`:

```python
from django.utils import timezone
from rest_framework.test import APIClient

from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job, WorkOrder, Task, Blep


class BlepListAndRetrieveTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='T', work_order=self.wo)
        self.blep = Blep.objects.create(
            task=self.task, user=self.user, start_time=timezone.now(),
        )

    def test_list_bleps(self):
        resp = self.client.get('/api/bleps/')
        self.assertEqual(resp.status_code, 200)
        ids = [b['blep_id'] for b in resp.data['results']]
        self.assertIn(self.blep.blep_id, ids)

    def test_retrieve_blep(self):
        resp = self.client.get(f'/api/bleps/{self.blep.blep_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['blep_id'], self.blep.blep_id)
        self.assertEqual(resp.data['task'], self.task.pk)

    def test_list_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get('/api/bleps/')
        self.assertIn(resp.status_code, [401, 403])
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_api_bleps.BlepListAndRetrieveTest --noinput`
Expected: FAIL — `/api/bleps/` returns 404.

- [ ] **Step 3: Create the viewset**

Create `apps/api/bleps/views.py`:

```python
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.jobs.models import Blep
from apps.api.bleps.serializers import BlepSerializer


class BlepViewSet(viewsets.ModelViewSet):
    """Top-level Blep (time entry) endpoints.

    List supports filters ?user=me|<id>, ?task=<id>, ?since=<iso>.
    Create/update/delete enforce ownership + 24h window or can_manage_time
    in the service layer (added in later tasks).
    """
    queryset = Blep.objects.all().order_by('-start_time')
    serializer_class = BlepSerializer
    permission_classes = [IsAuthenticated]
```

- [ ] **Step 4: Register the viewset**

Edit `apps/api/urls.py`:

```python
# Add to imports:
from apps.api.bleps.views import BlepViewSet

# Add to router registrations (order doesn't matter):
router.register(r'bleps', BlepViewSet, basename='blep')
```

- [ ] **Step 5: Remove the nested bleps action from TaskViewSet**

Edit `apps/api/tasks/views.py`. Delete the `bleps` action method entirely:

```python
# DELETE THIS BLOCK:
@action(detail=True, methods=['get'])
def bleps(self, request, pk=None):
    from apps.jobs.models import Blep
    from apps.api.work_orders.serializers import BlepSerializer
    task = self._get_task_or_404(pk)
    bleps = Blep.objects.filter(task=task)
    serializer = BlepSerializer(bleps, many=True)
    return Response(serializer.data)
```

- [ ] **Step 6: Remove the stale test_bleps_list test**

Edit `tests/test_task_lifecycle_api.py`. Delete `test_bleps_list` method:

```python
# DELETE THIS METHOD:
def test_bleps_list(self):
    Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
    Blep.objects.create(task=self.task, user=self.user, start_time=timezone.now())
    url = f'/api/tasks/{self.task.pk}/bleps/'
    resp = self.client.get(url)
    self.assertEqual(resp.status_code, 200)
    self.assertEqual(len(resp.data), 1)
```

- [ ] **Step 7: Run tests**

Run: `python manage.py test tests.test_api_bleps tests.test_task_lifecycle_api --noinput`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/api/bleps/views.py apps/api/urls.py apps/api/tasks/views.py tests/test_api_bleps.py tests/test_task_lifecycle_api.py
git commit -m "add /api/bleps/ list and retrieve; remove nested /api/tasks/{id}/bleps/"
```

---

### Task 5: Add list filters (`?user`, `?task`, `?since`)

**Files:**
- Modify: `apps/api/bleps/views.py`
- Test: `tests/test_api_bleps.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_api_bleps.py`:

```python
from datetime import timedelta


class BlepListFiltersTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.admin = User.objects.get(username='admin')
        self.worker = User.objects.create_user(username='worker', password='x')
        self.client.force_authenticate(user=self.admin)
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task_a = Task.objects.create(name='A', work_order=self.wo)
        self.task_b = Task.objects.create(name='B', work_order=self.wo)
        now = timezone.now()
        self.old = Blep.objects.create(
            task=self.task_a, user=self.admin,
            start_time=now - timedelta(days=10), end_time=now - timedelta(days=10, hours=-1),
        )
        self.recent_admin = Blep.objects.create(
            task=self.task_a, user=self.admin, start_time=now - timedelta(hours=2),
        )
        self.recent_worker = Blep.objects.create(
            task=self.task_b, user=self.worker, start_time=now - timedelta(hours=1),
        )

    def _ids(self, resp):
        return {b['blep_id'] for b in resp.data['results']}

    def test_filter_user_me(self):
        resp = self.client.get('/api/bleps/?user=me')
        self.assertEqual(resp.status_code, 200)
        ids = self._ids(resp)
        self.assertEqual(ids, {self.old.blep_id, self.recent_admin.blep_id})

    def test_filter_user_by_id(self):
        resp = self.client.get(f'/api/bleps/?user={self.worker.pk}')
        self.assertEqual(self._ids(resp), {self.recent_worker.blep_id})

    def test_filter_task(self):
        resp = self.client.get(f'/api/bleps/?task={self.task_b.pk}')
        self.assertEqual(self._ids(resp), {self.recent_worker.blep_id})

    def test_filter_since(self):
        cutoff = (timezone.now() - timedelta(days=1)).isoformat()
        resp = self.client.get(f'/api/bleps/?since={cutoff}')
        self.assertEqual(
            self._ids(resp),
            {self.recent_admin.blep_id, self.recent_worker.blep_id},
        )

    def test_filters_combine(self):
        cutoff = (timezone.now() - timedelta(days=1)).isoformat()
        resp = self.client.get(f'/api/bleps/?user=me&since={cutoff}')
        self.assertEqual(self._ids(resp), {self.recent_admin.blep_id})
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_api_bleps.BlepListFiltersTest --noinput`
Expected: FAIL — filters are ignored, all bleps returned.

- [ ] **Step 3: Add `get_queryset` filter logic**

Edit `apps/api/bleps/views.py`:

```python
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.jobs.models import Blep
from apps.api.bleps.serializers import BlepSerializer


class BlepViewSet(viewsets.ModelViewSet):
    serializer_class = BlepSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Blep.objects.all().order_by('-start_time')
        user_param = self.request.query_params.get('user')
        task_param = self.request.query_params.get('task')
        since_param = self.request.query_params.get('since')
        if user_param:
            if user_param == 'me':
                qs = qs.filter(user=self.request.user)
            else:
                qs = qs.filter(user_id=user_param)
        if task_param:
            qs = qs.filter(task_id=task_param)
        if since_param:
            qs = qs.filter(start_time__gte=since_param)
        return qs
```

- [ ] **Step 4: Run tests**

Run: `python manage.py test tests.test_api_bleps --noinput`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/bleps/views.py tests/test_api_bleps.py
git commit -m "add user/task/since filters to /api/bleps/"
```

---

## Chunk 3 — Blep writes: create, update, delete

### Task 6: Add `BlepService.create_historical` with validation

**Files:**
- Modify: `apps/jobs/services/blep_service.py`
- Test: `tests/test_blep_service.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_blep_service.py`:

```python
from django.core.exceptions import ValidationError
from apps.jobs.services.blep_service import BlepService, BlepPermissionError


class CreateHistoricalTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='T', work_order=self.wo)
        self.user = User.objects.get(username='admin')
        self.manager = User.objects.create_user(username='m', password='x')
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(codename='can_manage_time', content_type__app_label='core')
        self.manager.user_permissions.add(perm)
        self.manager = User.objects.get(pk=self.manager.pk)
        self.other_user = User.objects.create_user(username='worker2', password='x')

    def _times(self, hours_ago_start, hours_ago_end):
        from datetime import timedelta
        now = timezone.now()
        return (now - timedelta(hours=hours_ago_start),
                now - timedelta(hours=hours_ago_end))

    def test_create_for_self_within_24h(self):
        start, end = self._times(2, 1)
        blep = BlepService.create_historical(self.user, self.task, start, end)
        self.assertEqual(blep.user, self.user)
        self.assertEqual(blep.start_time, start)
        self.assertEqual(blep.end_time, end)

    def test_create_for_self_older_than_24h_requires_manage_time(self):
        start, end = self._times(48, 47)
        with self.assertRaises(BlepPermissionError):
            BlepService.create_historical(self.user, self.task, start, end)

    def test_create_for_self_older_than_24h_manager_allowed(self):
        start, end = self._times(48, 47)
        blep = BlepService.create_historical(self.manager, self.task, start, end)
        self.assertEqual(blep.user, self.manager)

    def test_create_for_other_user_requires_manage_time(self):
        start, end = self._times(2, 1)
        with self.assertRaises(BlepPermissionError):
            BlepService.create_historical(
                self.user, self.task, start, end, target_user=self.other_user,
            )

    def test_create_for_other_user_as_manager(self):
        start, end = self._times(2, 1)
        blep = BlepService.create_historical(
            self.manager, self.task, start, end, target_user=self.other_user,
        )
        self.assertEqual(blep.user, self.other_user)

    def test_create_rejects_worksheet_task(self):
        from apps.estimates.models import EstWorksheet
        ws = EstWorksheet.objects.create(job=self.job)
        ws_task = Task.objects.create(name='WS', est_worksheet=ws)
        start, end = self._times(2, 1)
        with self.assertRaises(ValidationError):
            BlepService.create_historical(self.user, ws_task, start, end)

    def test_create_rejects_end_before_start(self):
        start, end = self._times(1, 2)  # end < start
        with self.assertRaises(ValidationError):
            BlepService.create_historical(self.user, self.task, start, end)

    def test_create_rejects_overlap_with_existing_user_blep(self):
        from datetime import timedelta
        now = timezone.now()
        Blep.objects.create(
            task=self.task, user=self.user,
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(hours=1),
        )
        # New blep overlaps the existing one (3h ago to 1h ago).
        overlap_start = now - timedelta(hours=2)
        overlap_end = now - timedelta(minutes=30)
        with self.assertRaises(ValidationError):
            BlepService.create_historical(
                self.user, self.task, overlap_start, overlap_end,
            )

    def test_create_allows_overlap_across_different_users(self):
        from datetime import timedelta
        now = timezone.now()
        Blep.objects.create(
            task=self.task, user=self.other_user,
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(hours=1),
        )
        # Same time range, different user — allowed.
        start = now - timedelta(hours=2)
        end = now - timedelta(minutes=30)
        blep = BlepService.create_historical(self.user, self.task, start, end)
        self.assertIsNotNone(blep)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_blep_service.CreateHistoricalTest --noinput`
Expected: FAIL — `BlepService.create_historical` and `BlepPermissionError` don't exist.

- [ ] **Step 3: Implement `create_historical` and helpers**

Append to `apps/jobs/services/blep_service.py`:

```python
from datetime import timedelta
from django.core.exceptions import ValidationError


class BlepPermissionError(Exception):
    """Raised when a caller is not permitted to perform a blep operation."""
    pass


_EDIT_WINDOW = timedelta(hours=24)


def _has_manage_time(user):
    return user.has_perm('core.can_manage_time')


def _within_edit_window(start_time, now=None):
    if now is None:
        now = timezone.now()
    return (now - start_time) < _EDIT_WINDOW


# Extend the BlepService class defined above.
def _existing_overlaps(user, start_time, end_time, exclude_blep_id=None):
    """Does `user` already have a blep whose interval intersects
    [start_time, end_time)? Open bleps are treated as [start, now)."""
    now = timezone.now()
    # A blep's effective interval is [start, end or now).
    # Overlap: existing.start < new.end AND (existing.end or now) > new.start
    qs = Blep.objects.filter(user=user, start_time__lt=end_time)
    qs = qs.exclude(
        end_time__isnull=False, end_time__lte=start_time,
    ).exclude(
        end_time__isnull=True, start_time__gte=end_time,
    )
    # Open bleps whose start < end_time but who might end after start_time:
    # already handled since we only excluded those starting at/after end_time.
    # Still need to exclude open bleps whose start >= end_time:
    # done above.
    if exclude_blep_id is not None:
        qs = qs.exclude(blep_id=exclude_blep_id)
    return qs.exists()


# Attach methods to BlepService by reopening the class.
def create_historical(actor, task, start_time, end_time, target_user=None):
    if target_user is None:
        target_user = actor
    if target_user != actor and not _has_manage_time(actor):
        raise BlepPermissionError(
            "Creating a time entry for another user requires can_manage_time."
        )
    if not task.work_order_id:
        raise ValidationError(
            "Cannot create blep: task must belong to a WorkOrder, not a worksheet."
        )
    if end_time < start_time:
        raise ValidationError("end_time must be >= start_time.")
    if not _within_edit_window(start_time) and not _has_manage_time(actor):
        raise BlepPermissionError(
            "Creating a time entry older than 24 hours requires can_manage_time."
        )
    if _existing_overlaps(target_user, start_time, end_time):
        raise ValidationError(
            "This time entry overlaps an existing entry for the user."
        )
    return BlepService._create(task, target_user, start_time=start_time, end_time=end_time)


BlepService.create_historical = staticmethod(create_historical)
```

Refactoring note: the `_existing_overlaps` helper is placed at module scope but is called by the service method. Keeping it private (leading underscore). The "reopen class" pattern is used because the primitives were defined in Task 1 — this keeps the diff local. Alternatively, fold everything into the class definition by editing the file holistically; pick whichever is cleaner for your diff.

- [ ] **Step 4: Run tests**

Run: `python manage.py test tests.test_blep_service.CreateHistoricalTest --noinput`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services/blep_service.py tests/test_blep_service.py
git commit -m "add BlepService.create_historical with validation"
```

---

### Task 7: Add `POST /api/bleps/` endpoint

**Files:**
- Modify: `apps/api/bleps/views.py`
- Test: `tests/test_api_bleps.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_api_bleps.py`:

```python
from datetime import timedelta


class BlepCreateAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.other = User.objects.create_user(username='worker2', password='x')
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='T', work_order=self.wo)

    def _payload(self, hours_ago=2, duration_hours=1, user=None, task=None):
        now = timezone.now()
        start = now - timedelta(hours=hours_ago)
        end = start + timedelta(hours=duration_hours)
        data = {
            'task': (task or self.task).pk,
            'start_time': start.isoformat(),
            'end_time': end.isoformat(),
        }
        if user is not None:
            data['user'] = user.pk
        return data

    def test_create_historical_for_self(self):
        resp = self.client.post('/api/bleps/', self._payload(), format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['user'], self.user.pk)

    def test_create_defaults_user_to_self_when_omitted(self):
        payload = self._payload()
        payload.pop('user', None)
        resp = self.client.post('/api/bleps/', payload, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['user'], self.user.pk)

    def test_create_for_other_user_without_manage_time_denied(self):
        resp = self.client.post('/api/bleps/',
                                 self._payload(user=self.other), format='json')
        self.assertEqual(resp.status_code, 403)

    def test_create_older_than_24h_without_manage_time_denied(self):
        resp = self.client.post('/api/bleps/',
                                 self._payload(hours_ago=48, duration_hours=1),
                                 format='json')
        self.assertEqual(resp.status_code, 403)

    def test_create_overlap_returns_400(self):
        # First create one, then try to overlap.
        first = self.client.post('/api/bleps/', self._payload(hours_ago=3, duration_hours=2),
                                  format='json')
        self.assertEqual(first.status_code, 201)
        resp = self.client.post('/api/bleps/',
                                 self._payload(hours_ago=2, duration_hours=1),
                                 format='json')
        self.assertEqual(resp.status_code, 400)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_api_bleps.BlepCreateAPITest --noinput`
Expected: mostly FAIL — DRF will create the blep via `ModelViewSet.create` without running our validation.

- [ ] **Step 3: Override `create` to call the service**

Edit `apps/api/bleps/views.py`:

```python
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.jobs.models import Blep, Task
from apps.jobs.services.blep_service import BlepService, BlepPermissionError
from apps.api.bleps.serializers import BlepSerializer


class BlepViewSet(viewsets.ModelViewSet):
    serializer_class = BlepSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Blep.objects.all().order_by('-start_time')
        user_param = self.request.query_params.get('user')
        task_param = self.request.query_params.get('task')
        since_param = self.request.query_params.get('since')
        if user_param:
            if user_param == 'me':
                qs = qs.filter(user=self.request.user)
            else:
                qs = qs.filter(user_id=user_param)
        if task_param:
            qs = qs.filter(task_id=task_param)
        if since_param:
            qs = qs.filter(start_time__gte=since_param)
        return qs

    def create(self, request, *args, **kwargs):
        data = request.data
        task_id = data.get('task')
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        target_user_id = data.get('user')
        if not (task_id and start_time and end_time):
            return Response(
                {'detail': 'task, start_time, and end_time are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            task = Task.objects.get(pk=task_id)
        except Task.DoesNotExist:
            return Response({'task': ['Task not found.']},
                             status=status.HTTP_400_BAD_REQUEST)
        target_user = None
        if target_user_id is not None:
            from apps.core.models import User
            try:
                target_user = User.objects.get(pk=target_user_id)
            except User.DoesNotExist:
                return Response({'user': ['User not found.']},
                                 status=status.HTTP_400_BAD_REQUEST)
        try:
            blep = BlepService.create_historical(
                actor=request.user, task=task,
                start_time=start_time, end_time=end_time,
                target_user=target_user,
            )
        except BlepPermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except DjangoValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(BlepSerializer(blep).data, status=status.HTTP_201_CREATED)
```

- [ ] **Step 4: Run tests**

Run: `python manage.py test tests.test_api_bleps --noinput`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/bleps/views.py tests/test_api_bleps.py
git commit -m "add POST /api/bleps/ for historical blep creation"
```

---

### Task 8: Add `BlepService.update`

**Files:**
- Modify: `apps/jobs/services/blep_service.py`
- Test: `tests/test_blep_service.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_blep_service.py`:

```python
class UpdateBlepTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='T', work_order=self.wo)
        self.user = User.objects.get(username='admin')
        from django.contrib.auth.models import Permission
        self.manager = User.objects.create_user(username='m', password='x')
        perm = Permission.objects.get(codename='can_manage_time', content_type__app_label='core')
        self.manager.user_permissions.add(perm)
        self.manager = User.objects.get(pk=self.manager.pk)
        self.other = User.objects.create_user(username='w2', password='x')

    def _blep(self, user, hours_ago_start=2, hours_ago_end=1):
        from datetime import timedelta
        now = timezone.now()
        return Blep.objects.create(
            task=self.task, user=user,
            start_time=now - timedelta(hours=hours_ago_start),
            end_time=now - timedelta(hours=hours_ago_end),
        )

    def test_update_own_recent_blep(self):
        from datetime import timedelta
        blep = self._blep(self.user)
        new_end = blep.end_time + timedelta(minutes=15)
        updated = BlepService.update(blep, self.user, end_time=new_end)
        self.assertEqual(updated.end_time, new_end)

    def test_update_own_old_blep_requires_manage_time(self):
        blep = self._blep(self.user, hours_ago_start=48, hours_ago_end=47)
        from datetime import timedelta
        with self.assertRaises(BlepPermissionError):
            BlepService.update(
                blep, self.user,
                end_time=blep.end_time + timedelta(minutes=5),
            )

    def test_update_own_old_blep_as_manager_ok(self):
        blep = self._blep(self.user, hours_ago_start=48, hours_ago_end=47)
        from datetime import timedelta
        new_end = blep.end_time + timedelta(minutes=5)
        updated = BlepService.update(blep, self.manager, end_time=new_end)
        self.assertEqual(updated.end_time, new_end)

    def test_update_other_users_blep_requires_manage_time(self):
        blep = self._blep(self.other)
        from datetime import timedelta
        with self.assertRaises(BlepPermissionError):
            BlepService.update(
                blep, self.user,
                end_time=blep.end_time + timedelta(minutes=5),
            )

    def test_update_rejects_overlap(self):
        from datetime import timedelta
        now = timezone.now()
        existing = Blep.objects.create(
            task=self.task, user=self.user,
            start_time=now - timedelta(hours=5),
            end_time=now - timedelta(hours=4),
        )
        target = self._blep(self.user, hours_ago_start=3, hours_ago_end=2)
        # Extend `target` backwards to overlap `existing`.
        with self.assertRaises(ValidationError):
            BlepService.update(
                target, self.user,
                start_time=now - timedelta(hours=4, minutes=30),
            )
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_blep_service.UpdateBlepTest --noinput`
Expected: FAIL — `BlepService.update` doesn't exist.

- [ ] **Step 3: Implement `update`**

Append to `apps/jobs/services/blep_service.py`:

```python
def update(blep, actor, **fields):
    """Update a blep. Only `start_time` and `end_time` are editable here."""
    is_own = blep.user_id == actor.pk
    # Ownership + time-window gate
    if is_own:
        if not _within_edit_window(blep.start_time) and not _has_manage_time(actor):
            raise BlepPermissionError(
                "Editing a time entry older than 24 hours requires can_manage_time."
            )
    else:
        if not _has_manage_time(actor):
            raise BlepPermissionError(
                "Editing another user's time entry requires can_manage_time."
            )

    allowed_fields = {'start_time', 'end_time'}
    unknown = set(fields) - allowed_fields
    if unknown:
        raise ValidationError(f"Cannot update fields: {', '.join(sorted(unknown))}")

    new_start = fields.get('start_time', blep.start_time)
    new_end = fields.get('end_time', blep.end_time)
    if new_end is not None and new_start is not None and new_end < new_start:
        raise ValidationError("end_time must be >= start_time.")

    # Overlap check (use effective end = now for open bleps)
    effective_end = new_end if new_end is not None else timezone.now()
    if _existing_overlaps(blep.user, new_start, effective_end,
                           exclude_blep_id=blep.blep_id):
        raise ValidationError(
            "This time entry would overlap an existing entry for the user."
        )

    for k, v in fields.items():
        setattr(blep, k, v)
    blep.save()
    return blep


BlepService.update = staticmethod(update)
```

- [ ] **Step 4: Run tests**

Run: `python manage.py test tests.test_blep_service.UpdateBlepTest --noinput`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services/blep_service.py tests/test_blep_service.py
git commit -m "add BlepService.update with window and overlap validation"
```

---

### Task 9: Add `PATCH /api/bleps/{id}/` endpoint

**Files:**
- Modify: `apps/api/bleps/views.py`
- Test: `tests/test_api_bleps.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_api_bleps.py`:

```python
from django.contrib.auth.models import Permission


class BlepUpdateAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.manager = User.objects.create_user(username='m', password='x')
        perm = Permission.objects.get(codename='can_manage_time', content_type__app_label='core')
        self.manager.user_permissions.add(perm)
        self.manager = User.objects.get(pk=self.manager.pk)
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='T', work_order=self.wo)

    def _blep(self, user, hours_ago_start=2, hours_ago_end=1):
        from datetime import timedelta
        now = timezone.now()
        return Blep.objects.create(
            task=self.task, user=user,
            start_time=now - timedelta(hours=hours_ago_start),
            end_time=now - timedelta(hours=hours_ago_end),
        )

    def test_patch_own_recent_blep(self):
        from datetime import timedelta
        blep = self._blep(self.user)
        self.client.force_authenticate(user=self.user)
        new_end = (blep.end_time + timedelta(minutes=10)).isoformat()
        resp = self.client.patch(
            f'/api/bleps/{blep.blep_id}/',
            {'end_time': new_end}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        blep.refresh_from_db()

    def test_patch_old_blep_as_non_manager_denied(self):
        from datetime import timedelta
        blep = self._blep(self.user, 48, 47)
        self.client.force_authenticate(user=self.user)
        resp = self.client.patch(
            f'/api/bleps/{blep.blep_id}/',
            {'end_time': (blep.end_time + timedelta(minutes=5)).isoformat()},
            format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_patch_old_blep_as_manager(self):
        from datetime import timedelta
        blep = self._blep(self.user, 48, 47)
        self.client.force_authenticate(user=self.manager)
        resp = self.client.patch(
            f'/api/bleps/{blep.blep_id}/',
            {'end_time': (blep.end_time + timedelta(minutes=5)).isoformat()},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_api_bleps.BlepUpdateAPITest --noinput`
Expected: FAIL — default `ModelViewSet.update` bypasses our service.

- [ ] **Step 3: Override `partial_update` (and `update`)**

Edit `apps/api/bleps/views.py` — add these methods on `BlepViewSet`:

```python
    def update(self, request, *args, **kwargs):
        # Treat PUT the same as PATCH; we never do full-replacement updates.
        return self.partial_update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        blep = self.get_object()
        allowed = {'start_time', 'end_time'}
        fields = {k: v for k, v in request.data.items() if k in allowed}
        try:
            BlepService.update(blep, request.user, **fields)
        except BlepPermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except DjangoValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        blep.refresh_from_db()
        return Response(BlepSerializer(blep).data)
```

- [ ] **Step 4: Run tests**

Run: `python manage.py test tests.test_api_bleps --noinput`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/bleps/views.py tests/test_api_bleps.py
git commit -m "add PATCH /api/bleps/{id}/"
```

---

### Task 10: Add `BlepService.delete` and `DELETE /api/bleps/{id}/`

**Files:**
- Modify: `apps/jobs/services/blep_service.py`, `apps/api/bleps/views.py`
- Test: `tests/test_blep_service.py`, `tests/test_api_bleps.py`

- [ ] **Step 1: Write failing tests (service + api)**

Append to `tests/test_blep_service.py`:

```python
class DeleteBlepTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='T', work_order=self.wo)
        self.user = User.objects.get(username='admin')
        from django.contrib.auth.models import Permission
        self.manager = User.objects.create_user(username='m', password='x')
        perm = Permission.objects.get(codename='can_manage_time', content_type__app_label='core')
        self.manager.user_permissions.add(perm)
        self.manager = User.objects.get(pk=self.manager.pk)
        self.other = User.objects.create_user(username='w2', password='x')

    def _blep(self, user, hours_ago_start=2):
        from datetime import timedelta
        now = timezone.now()
        return Blep.objects.create(
            task=self.task, user=user,
            start_time=now - timedelta(hours=hours_ago_start),
            end_time=now - timedelta(hours=hours_ago_start - 0.5),
        )

    def test_delete_own_recent(self):
        blep = self._blep(self.user)
        BlepService.delete(blep, self.user)
        self.assertFalse(Blep.objects.filter(pk=blep.blep_id).exists())

    def test_delete_own_old_without_manage_time_denied(self):
        blep = self._blep(self.user, hours_ago_start=48)
        with self.assertRaises(BlepPermissionError):
            BlepService.delete(blep, self.user)

    def test_delete_other_without_manage_time_denied(self):
        blep = self._blep(self.other)
        with self.assertRaises(BlepPermissionError):
            BlepService.delete(blep, self.user)

    def test_delete_other_as_manager(self):
        blep = self._blep(self.other)
        BlepService.delete(blep, self.manager)
        self.assertFalse(Blep.objects.filter(pk=blep.blep_id).exists())
```

Append to `tests/test_api_bleps.py`:

```python
class BlepDeleteAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(name='T', work_order=self.wo)

    def test_delete_own_recent_blep(self):
        from datetime import timedelta
        now = timezone.now()
        blep = Blep.objects.create(
            task=self.task, user=self.user,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )
        self.client.force_authenticate(user=self.user)
        resp = self.client.delete(f'/api/bleps/{blep.blep_id}/')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Blep.objects.filter(pk=blep.blep_id).exists())

    def test_delete_old_blep_non_manager_denied(self):
        from datetime import timedelta
        now = timezone.now()
        blep = Blep.objects.create(
            task=self.task, user=self.user,
            start_time=now - timedelta(hours=48),
            end_time=now - timedelta(hours=47),
        )
        self.client.force_authenticate(user=self.user)
        resp = self.client.delete(f'/api/bleps/{blep.blep_id}/')
        self.assertEqual(resp.status_code, 403)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_blep_service.DeleteBlepTest tests.test_api_bleps.BlepDeleteAPITest --noinput`
Expected: FAIL.

- [ ] **Step 3: Implement delete in service and view**

Append to `apps/jobs/services/blep_service.py`:

```python
def delete(blep, actor):
    is_own = blep.user_id == actor.pk
    if is_own:
        if not _within_edit_window(blep.start_time) and not _has_manage_time(actor):
            raise BlepPermissionError(
                "Deleting a time entry older than 24 hours requires can_manage_time."
            )
    else:
        if not _has_manage_time(actor):
            raise BlepPermissionError(
                "Deleting another user's time entry requires can_manage_time."
            )
    blep.delete()


BlepService.delete = staticmethod(delete)
```

Add `destroy` override to `apps/api/bleps/views.py` on `BlepViewSet`:

```python
    def destroy(self, request, *args, **kwargs):
        blep = self.get_object()
        try:
            BlepService.delete(blep, request.user)
        except BlepPermissionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)
        return Response(status=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Run tests**

Run: `python manage.py test tests.test_blep_service tests.test_api_bleps --noinput`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services/blep_service.py apps/api/bleps/views.py tests/test_blep_service.py tests/test_api_bleps.py
git commit -m "add DELETE /api/bleps/{id}/"
```

---

## Chunk 4 — Task retrieve endpoint

### Task 11: Add retrieve to `TaskViewSet`

The task detail page needs to GET a task by id with enough data to render (task fields, containing work_order, job info).

**Files:**
- Create: `apps/api/tasks/serializers.py`
- Modify: `apps/api/tasks/views.py`
- Test: `tests/test_api_bleps.py` (add one small test for task retrieve — or a new file; we'll piggyback)

- [ ] **Step 1: Write failing test**

Append to `tests/test_api_bleps.py` (topical mismatch is fine; alternative is `tests/test_api_tasks.py`):

```python
class TaskRetrieveAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        self.wo = WorkOrder.objects.create(job=self.job, status=WorkOrder.STATUS_INCOMPLETE)
        self.task = Task.objects.create(
            name='T', description='desc', work_order=self.wo,
            units='hours', rate='10.00', est_qty='1',
        )

    def test_retrieve_task(self):
        resp = self.client.get(f'/api/tasks/{self.task.pk}/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['task_id'], self.task.pk)
        self.assertEqual(resp.data['name'], 'T')
        self.assertIn('work_order', resp.data)
        self.assertEqual(resp.data['work_order']['id'], self.wo.pk)
        self.assertEqual(resp.data['work_order']['job']['id'], self.job.pk)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_api_bleps.TaskRetrieveAPITest --noinput`
Expected: FAIL — `/api/tasks/{id}/` returns 404 because TaskViewSet is a GenericViewSet with no retrieve.

- [ ] **Step 3: Create `TaskDetailSerializer` and wire retrieve**

Create `apps/api/tasks/serializers.py`:

```python
from rest_framework import serializers

from apps.jobs.models import Task
from apps.core.units import UnitsField


class TaskDetailSerializer(serializers.ModelSerializer):
    assignee_name = serializers.SerializerMethodField()
    units = UnitsField()
    work_order = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'status',
            'units', 'rate', 'est_qty', 'accounting_category',
            'parent_task', 'assignee', 'assignee_name',
            'worker_queue', 'work_order',
        ]
        read_only_fields = fields

    def get_assignee_name(self, obj):
        if obj.assignee:
            return obj.assignee.get_full_name() or obj.assignee.username
        return None

    def get_work_order(self, obj):
        if not obj.work_order:
            return None
        wo = obj.work_order
        job = wo.job
        return {
            'id': wo.pk,
            'status': wo.status,
            'job': {
                'id': job.pk,
                'job_number': job.job_number,
                'name': job.name,
            },
        }
```

Edit `apps/api/tasks/views.py`:

Change the class inheritance and add retrieve support:

```python
from rest_framework.mixins import RetrieveModelMixin
# ...

class TaskViewSet(RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Task.objects.all()
    lookup_field = 'pk'
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        from apps.api.tasks.serializers import TaskDetailSerializer
        return TaskDetailSerializer

    # ... existing action methods unchanged ...
```

- [ ] **Step 4: Run tests**

Run: `python manage.py test tests.test_api_bleps.TaskRetrieveAPITest --noinput`
Expected: PASS.

- [ ] **Step 5: Run full affected suite**

Run: `python manage.py test tests.test_task_lifecycle_api tests.test_api_bleps tests.test_blep_service --noinput`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/tasks/serializers.py apps/api/tasks/views.py tests/test_api_bleps.py
git commit -m "add GET /api/tasks/{id}/ retrieve endpoint"
```

---

## Chunk 5 — Frontend: task detail page

### Task 12: Replace `TaskDetailPage.svelte` stub — header + core info

**Files:**
- Modify: `frontend/src/routes/jobs/TaskDetailPage.svelte`

- [ ] **Step 1: Rewrite the page**

Replace the contents of `frontend/src/routes/jobs/TaskDetailPage.svelte`:

```svelte
<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';

  let { params = {} } = $props();

  let task = $state(null);
  let loading = $state(true);
  let error = $state('');

  async function load() {
    loading = true;
    error = '';
    try {
      task = await api.get(`/api/tasks/${params.taskId}/`);
    } catch (e) {
      error = e.message || 'Could not load task.';
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (params.taskId) load();
  });
</script>

{#if loading}
  <p>Loading…</p>
{:else if error}
  <p class="error">{error}</p>
{:else if task}
  <h2>Task: {task.name}</h2>
  {#if task.work_order}
    <p>
      <a href={`/jobs/${task.work_order.job.id}`} use:link>
        &laquo; {task.work_order.job.job_number} {task.work_order.job.name}
      </a>
    </p>
  {/if}

  <table border="1">
    <tbody>
      <tr><td>Status</td><td>{task.status}</td></tr>
      <tr><td>Description</td><td>{task.description || '-'}</td></tr>
      <tr><td>Assignee</td><td>{task.assignee_name || 'Unassigned'}</td></tr>
      <tr><td>Est. quantity</td><td>{task.est_qty || '-'} {task.units || ''}</td></tr>
      <tr><td>Rate</td><td>{task.rate ? `$${task.rate}` : '-'}</td></tr>
      <tr><td>Accounting category</td><td>{task.accounting_category || '-'}</td></tr>
    </tbody>
  </table>
{/if}

<style>
  .error { color: #a8071a; }
</style>
```

- [ ] **Step 2: Manually verify in browser**

Start the dev stack (`python manage.py runserver` and `cd frontend && npm run dev`), navigate to `#/jobs/<jobId>/tasks/<taskId>` for a real task, confirm the page loads and shows the task info. Rebuild dist with `npm run build` if `npm run dev` is not in use.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/jobs/TaskDetailPage.svelte
git commit -m "scaffold TaskDetailPage with task header and core info"
```

---

### Task 13: Add `TaskActions.svelte` component

**Files:**
- Create: `frontend/src/components/tasks/TaskActions.svelte`
- Modify: `frontend/src/routes/jobs/TaskDetailPage.svelte`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/tasks/TaskActions.svelte`:

```svelte
<script>
  import { api } from '../../lib/api.js';

  let {
    task,
    user,
    userPermissions = [],
    activeBlepOnThisTask = null,
    onChanged = () => {},
    onConflict = () => {},
  } = $props();

  let busy = $state(false);
  let error = $state('');

  const isManager = $derived(userPermissions.includes('can_manage_jobs'));

  // Visibility per status (see design doc § Action visibility)
  const show = $derived.by(() => {
    const status = task?.status;
    const isActiveHere = activeBlepOnThisTask !== null;
    const base = {
      startWork: false, stopWork: false, complete: false,
      block: false, unblock: false, cancel: false,
    };
    if (status === 'pending' || status === 'in_progress') {
      base.startWork = !isActiveHere;
      base.stopWork = isActiveHere;
      base.complete = true;
      base.block = true;
      base.cancel = isManager;
    } else if (status === 'blocked') {
      base.unblock = true;
      base.cancel = isManager;
    }
    return base;
  });

  async function call(url, body = {}) {
    busy = true;
    error = '';
    try {
      const resp = await api.post(url, body);
      if (resp && resp.conflict) {
        onConflict(resp);
      } else {
        onChanged();
      }
    } catch (e) {
      error = e.message || 'Action failed.';
    } finally {
      busy = false;
    }
  }

  const startWork = () => call(`/api/tasks/${task.task_id}/start-work/`);
  const stopWork = () => call(`/api/tasks/${task.task_id}/stop-work/`);
  const complete = () => call(`/api/tasks/${task.task_id}/complete/`);
  const block = () => {
    const reason = prompt('Reason for blocking?');
    if (reason) call(`/api/tasks/${task.task_id}/block/`, { reason });
  };
  const unblock = () => call(`/api/tasks/${task.task_id}/unblock/`);
  const cancel = () => {
    if (confirm('Cancel this task?')) call(`/api/tasks/${task.task_id}/cancel/`);
  };
</script>

<div class="actions">
  {#if show.startWork}<button type="button" onclick={startWork} disabled={busy}>Start Work</button>{/if}
  {#if show.stopWork}<button type="button" onclick={stopWork} disabled={busy}>Stop Work</button>{/if}
  {#if show.complete}<button type="button" onclick={complete} disabled={busy}>Complete</button>{/if}
  {#if show.block}<button type="button" onclick={block} disabled={busy}>Block</button>{/if}
  {#if show.unblock}<button type="button" onclick={unblock} disabled={busy}>Unblock</button>{/if}
  {#if show.cancel}<button type="button" onclick={cancel} disabled={busy}>Cancel</button>{/if}
</div>
{#if error}<p class="error">{error}</p>{/if}

<style>
  .actions { display: flex; gap: 8px; margin: 8px 0; flex-wrap: wrap; }
  .error { color: #a8071a; }
</style>
```

- [ ] **Step 2: Wire into TaskDetailPage**

Edit `frontend/src/routes/jobs/TaskDetailPage.svelte`. Add imports and state for the current user, blep list, and render `<TaskActions>`:

```svelte
<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import { currentBlep } from '../../stores/currentBlep.js';
  import TaskActions from '../../components/tasks/TaskActions.svelte';

  let { params = {} } = $props();

  let task = $state(null);
  let loading = $state(true);
  let error = $state('');

  const activeBlepOnThisTask = $derived.by(() => {
    const cb = $currentBlep;
    if (!cb || !task) return null;
    return cb.task && cb.task.id === task.task_id ? cb : null;
  });

  const userPermissions = $derived($userStore?.permissions || []);

  async function loadTask() {
    loading = true;
    error = '';
    try {
      task = await api.get(`/api/tasks/${params.taskId}/`);
    } catch (e) {
      error = e.message || 'Could not load task.';
    } finally {
      loading = false;
    }
  }

  async function refresh() {
    await loadTask();
  }

  $effect(() => {
    if (params.taskId) loadTask();
  });
</script>

{#if loading}
  <p>Loading…</p>
{:else if error}
  <p class="error">{error}</p>
{:else if task}
  <h2>Task: {task.name}</h2>
  {#if task.work_order}
    <p>
      <a href={`/jobs/${task.work_order.job.id}`} use:link>
        &laquo; {task.work_order.job.job_number} {task.work_order.job.name}
      </a>
    </p>
  {/if}

  <TaskActions
    {task}
    user={$userStore}
    {userPermissions}
    {activeBlepOnThisTask}
    onChanged={refresh}
    onConflict={() => { /* wired in Task 14 */ }}
  />

  <table border="1">
    <tbody>
      <tr><td>Status</td><td>{task.status}</td></tr>
      <tr><td>Description</td><td>{task.description || '-'}</td></tr>
      <tr><td>Assignee</td><td>{task.assignee_name || 'Unassigned'}</td></tr>
      <tr><td>Est. quantity</td><td>{task.est_qty || '-'} {task.units || ''}</td></tr>
      <tr><td>Rate</td><td>{task.rate ? `$${task.rate}` : '-'}</td></tr>
      <tr><td>Accounting category</td><td>{task.accounting_category || '-'}</td></tr>
    </tbody>
  </table>
{/if}

<style>
  .error { color: #a8071a; }
</style>
```

- [ ] **Step 3: Manual verification**

Navigate to a pending task detail page, click Start Work, verify the task status changes and the global blep band lights up with this task.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/tasks/TaskActions.svelte frontend/src/routes/jobs/TaskDetailPage.svelte
git commit -m "add TaskActions component for lifecycle operations on task view"
```

---

### Task 14: Add `StartWorkConflictModal.svelte`

**Files:**
- Create: `frontend/src/components/tasks/StartWorkConflictModal.svelte`
- Modify: `frontend/src/routes/jobs/TaskDetailPage.svelte`

- [ ] **Step 1: Create the modal**

Create `frontend/src/components/tasks/StartWorkConflictModal.svelte`:

```svelte
<script>
  import { api } from '../../lib/api.js';

  let {
    conflict = null,
    taskId,
    onResolved = () => {},
    onCancel = () => {},
  } = $props();

  let busy = $state(false);
  let error = $state('');

  async function resolve(action) {
    busy = true;
    error = '';
    try {
      await api.post(`/api/tasks/${taskId}/start-work/`, { action });
      onResolved();
    } catch (e) {
      error = e.message || 'Could not resolve conflict.';
    } finally {
      busy = false;
    }
  }
</script>

{#if conflict}
  <div class="overlay">
    <div class="modal">
      <h3>Someone is already working on this task</h3>
      <p>
        <strong>{conflict.worker?.name}</strong> is currently working on this
        task (started at {new Date(conflict.started_at).toLocaleString()}).
      </p>
      <p>What do you want to do?</p>
      <div class="buttons">
        <button type="button" onclick={() => resolve('join')} disabled={busy}>
          Join (we work together)
        </button>
        <button type="button" onclick={() => resolve('takeover')} disabled={busy}>
          Take over (stop their timer)
        </button>
        <button type="button" onclick={onCancel} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.4);
    display: flex; align-items: center; justify-content: center; z-index: 200;
  }
  .modal {
    background: white; padding: 16px; max-width: 440px;
    border: 1px solid #ccc;
  }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
```

- [ ] **Step 2: Wire into TaskDetailPage**

Edit `frontend/src/routes/jobs/TaskDetailPage.svelte`. Add state for `conflict`, import the modal, pass to TaskActions:

```svelte
<script>
  // ... existing imports ...
  import StartWorkConflictModal from '../../components/tasks/StartWorkConflictModal.svelte';

  // ... existing state ...
  let conflict = $state(null);

  function handleConflict(c) { conflict = c; }
  function handleResolved() {
    conflict = null;
    refresh();
  }
  function handleCancel() { conflict = null; }
  // ... existing functions ...
</script>

<!-- In the TaskActions invocation, replace onConflict={() => {}} with: -->
<TaskActions
  {task}
  user={$userStore}
  {userPermissions}
  {activeBlepOnThisTask}
  onChanged={refresh}
  onConflict={handleConflict}
/>

<StartWorkConflictModal
  {conflict}
  taskId={task?.task_id}
  onResolved={handleResolved}
  onCancel={handleCancel}
/>
```

- [ ] **Step 3: Manual verification**

Create a second user, log in as them, start-work a task. Log in as the original user, navigate to the same task, click Start Work. Confirm the modal appears with Join and Take Over.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/tasks/StartWorkConflictModal.svelte frontend/src/routes/jobs/TaskDetailPage.svelte
git commit -m "add start-work conflict resolution modal"
```

---

### Task 15: Add `BlepList.svelte` — read-only work sessions table

**Files:**
- Create: `frontend/src/components/tasks/BlepList.svelte`
- Modify: `frontend/src/routes/jobs/TaskDetailPage.svelte`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/tasks/BlepList.svelte`:

```svelte
<script>
  let {
    bleps = [],
    currentUser,
    userPermissions = [],
    onEdit = () => {},
    onDelete = () => {},
    onAdd = () => {},
  } = $props();

  const canManageTime = $derived(userPermissions.includes('can_manage_time'));

  function within24h(iso) {
    if (!iso) return false;
    return Date.now() - new Date(iso).getTime() < 24 * 60 * 60 * 1000;
  }

  function isEditable(blep) {
    if (canManageTime) return true;
    if (blep.user !== currentUser?.id) return false;
    return within24h(blep.start_time);
  }

  function fmt(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString();
  }

  function elapsed(b) {
    if (!b.start_time) return '—';
    const endMs = b.end_time ? new Date(b.end_time).getTime() : Date.now();
    const s = Math.max(0, Math.floor((endMs - new Date(b.start_time).getTime()) / 1000));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }
</script>

<section>
  <h3>Work Sessions</h3>
  {#if bleps.length === 0}
    <p>No work sessions recorded.</p>
  {:else}
    <table border="1">
      <thead>
        <tr>
          <th>Worker</th><th>Start</th><th>End</th><th>Elapsed</th><th></th>
        </tr>
      </thead>
      <tbody>
        {#each bleps as blep (blep.blep_id)}
          <tr>
            <td>{blep.user_name || '—'}</td>
            <td>{fmt(blep.start_time)}</td>
            <td>{blep.end_time ? fmt(blep.end_time) : 'Active'}</td>
            <td>{elapsed(blep)}</td>
            <td>
              {#if isEditable(blep)}
                <button type="button" onclick={() => onEdit(blep)}>Edit</button>
                <button type="button" onclick={() => onDelete(blep)}>Delete</button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
  <p><button type="button" onclick={onAdd}>Add Entry</button></p>
</section>
```

- [ ] **Step 2: Load bleps and mount in TaskDetailPage**

Edit `frontend/src/routes/jobs/TaskDetailPage.svelte`. Add bleps state, fetch in `load`, render `<BlepList>`:

```svelte
<script>
  // ... existing imports ...
  import BlepList from '../../components/tasks/BlepList.svelte';

  // ... existing state ...
  let bleps = $state([]);

  async function loadBleps() {
    try {
      const resp = await api.get(`/api/bleps/?task=${params.taskId}`);
      bleps = resp.results || resp;
    } catch (e) {
      // ignore; surfaced via task error if any
    }
  }

  async function refresh() {
    await loadTask();
    await loadBleps();
  }

  // Add loadBleps() to the mount effect alongside loadTask()
  $effect(() => {
    if (params.taskId) {
      loadTask();
      loadBleps();
    }
  });
</script>

<!-- Below the core info table, before StartWorkConflictModal: -->
<BlepList
  {bleps}
  currentUser={$userStore}
  {userPermissions}
  onEdit={() => { /* Task 16 */ }}
  onDelete={() => { /* Task 17 */ }}
  onAdd={() => { /* Task 17 */ }}
/>
```

- [ ] **Step 3: Manual verification**

Load a task page that has bleps — the list should appear with Edit/Delete buttons shown only on recent own-bleps (or all rows if logged in as a user with `can_manage_time`).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/tasks/BlepList.svelte frontend/src/routes/jobs/TaskDetailPage.svelte
git commit -m "add BlepList component to task detail page"
```

---

### Task 16: Add `BlepEditModal.svelte` and wire Edit button

**Files:**
- Create: `frontend/src/components/tasks/BlepEditModal.svelte`
- Modify: `frontend/src/routes/jobs/TaskDetailPage.svelte`

- [ ] **Step 1: Create the modal**

Create `frontend/src/components/tasks/BlepEditModal.svelte`:

```svelte
<script>
  import { api } from '../../lib/api.js';

  let {
    open = false,
    mode = 'edit', // 'edit' | 'create'
    blep = null,   // when mode='edit'
    taskId = null, // when mode='create'
    currentUser,
    userPermissions = [],
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  const canManageTime = $derived(userPermissions.includes('can_manage_time'));

  let startTime = $state('');
  let endTime = $state('');
  let targetUserId = $state('');
  let busy = $state(false);
  let error = $state('');

  function isoToLocal(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    // datetime-local needs YYYY-MM-DDTHH:mm in local time
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
      + `T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function localToIso(local) {
    if (!local) return null;
    return new Date(local).toISOString();
  }

  $effect(() => {
    if (open) {
      if (mode === 'edit' && blep) {
        startTime = isoToLocal(blep.start_time);
        endTime = isoToLocal(blep.end_time);
        targetUserId = String(blep.user ?? '');
      } else {
        startTime = '';
        endTime = '';
        targetUserId = String(currentUser?.id ?? '');
      }
      error = '';
    }
  });

  async function save() {
    busy = true;
    error = '';
    try {
      if (mode === 'edit') {
        await api.patch(`/api/bleps/${blep.blep_id}/`, {
          start_time: localToIso(startTime),
          end_time: localToIso(endTime),
        });
      } else {
        const payload = {
          task: taskId,
          start_time: localToIso(startTime),
          end_time: localToIso(endTime),
        };
        if (canManageTime && targetUserId) payload.user = Number(targetUserId);
        await api.post('/api/bleps/', payload);
      }
      onSaved();
    } catch (e) {
      error = e.message || 'Could not save.';
    } finally {
      busy = false;
    }
  }

  async function remove() {
    if (!blep) return;
    if (!confirm('Delete this time entry?')) return;
    busy = true;
    error = '';
    try {
      await api.delete(`/api/bleps/${blep.blep_id}/`);
      onSaved();
    } catch (e) {
      error = e.message || 'Could not delete.';
    } finally {
      busy = false;
    }
  }
</script>

{#if open}
  <div class="overlay">
    <div class="modal">
      <h3>{mode === 'edit' ? 'Edit time entry' : 'Add time entry'}</h3>
      <p>
        <label><strong>Start</strong><br>
          <input type="datetime-local" bind:value={startTime}>
        </label>
      </p>
      <p>
        <label><strong>End</strong><br>
          <input type="datetime-local" bind:value={endTime}>
        </label>
      </p>
      {#if canManageTime}
        <p>
          <label><strong>User (manager only)</strong><br>
            <input type="number" bind:value={targetUserId}>
          </label>
        </p>
      {/if}
      <div class="buttons">
        <button type="button" onclick={save} disabled={busy}>Save</button>
        {#if mode === 'edit'}
          <button type="button" onclick={remove} disabled={busy}>Delete</button>
        {/if}
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.4);
    display: flex; align-items: center; justify-content: center; z-index: 200;
  }
  .modal { background: white; padding: 16px; max-width: 440px; border: 1px solid #ccc; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
```

- [ ] **Step 2: Wire Edit button into TaskDetailPage**

Edit `frontend/src/routes/jobs/TaskDetailPage.svelte` — add state for edit modal, handlers, and mount:

```svelte
<script>
  // ... existing imports ...
  import BlepEditModal from '../../components/tasks/BlepEditModal.svelte';

  // ... existing state ...
  let editingBlep = $state(null);
  let modalMode = $state('edit'); // 'edit' | 'create'
  const modalOpen = $derived(editingBlep !== null || modalMode === 'create-open');

  function openEdit(blep) { editingBlep = blep; modalMode = 'edit'; }
  function openCreate() { editingBlep = null; modalMode = 'create-open'; }
  function closeModal() { editingBlep = null; modalMode = 'edit'; }
  async function handleSaved() { closeModal(); await loadBleps(); }
</script>

<!-- Update the BlepList usage: -->
<BlepList
  {bleps}
  currentUser={$userStore}
  {userPermissions}
  onEdit={openEdit}
  onDelete={(b) => { editingBlep = b; modalMode = 'edit'; }}
  onAdd={openCreate}
/>

<BlepEditModal
  open={modalOpen}
  mode={modalMode === 'create-open' ? 'create' : 'edit'}
  blep={editingBlep}
  taskId={task?.task_id}
  currentUser={$userStore}
  {userPermissions}
  onSaved={handleSaved}
  onClose={closeModal}
/>
```

- [ ] **Step 3: Manual verification**

Click Edit on a recent own blep. Modify the end time. Save. Verify the list refreshes with the new value. Click Delete, confirm, verify the blep disappears. Click Add Entry, fill in start/end, save, verify it appears.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/tasks/BlepEditModal.svelte frontend/src/routes/jobs/TaskDetailPage.svelte
git commit -m "add BlepEditModal with edit, delete, and create modes"
```

---

## Chunk 6 — Home page Recent Time

### Task 17: Add `RecentTimeList.svelte`

**Files:**
- Create: `frontend/src/components/home/RecentTimeList.svelte`
- Modify: `frontend/src/routes/Home.svelte`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/home/RecentTimeList.svelte`:

```svelte
<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import BlepEditModal from '../tasks/BlepEditModal.svelte';

  let bleps = $state([]);
  let loading = $state(true);
  let editingBlep = $state(null);
  let modalOpen = $state(false);

  const userPermissions = $derived($userStore?.permissions || []);
  const canManageTime = $derived(userPermissions.includes('can_manage_time'));

  function within24h(iso) {
    if (!iso) return false;
    return Date.now() - new Date(iso).getTime() < 24 * 60 * 60 * 1000;
  }

  function isEditable(blep) {
    if (canManageTime) return true;
    return blep.user === $userStore?.id && within24h(blep.start_time);
  }

  async function load() {
    loading = true;
    try {
      const since = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
      const resp = await api.get(`/api/bleps/?user=me&since=${encodeURIComponent(since)}`);
      bleps = resp.results || resp;
    } finally {
      loading = false;
    }
  }

  function openEdit(blep) {
    editingBlep = blep;
    modalOpen = true;
  }

  function requestEdit() {
    alert('Request Edit: not yet implemented.');
  }

  async function handleSaved() {
    modalOpen = false;
    editingBlep = null;
    await load();
  }

  function closeModal() {
    modalOpen = false;
    editingBlep = null;
  }

  function fmt(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString();
  }

  $effect(() => { load(); });
</script>

<section>
  <h3>Recent Time</h3>
  {#if loading}
    <p>Loading…</p>
  {:else if bleps.length === 0}
    <p>No recent time entries.</p>
  {:else}
    <table border="1">
      <thead>
        <tr>
          <th>Task</th><th>Job</th><th>Start</th><th>End</th><th></th>
        </tr>
      </thead>
      <tbody>
        {#each bleps as blep (blep.blep_id)}
          <tr>
            <td>
              {#if blep.job_id}
                <a href={`/jobs/${blep.job_id}/tasks/${blep.task}`} use:link>
                  {blep.task_name}
                </a>
              {:else}
                {blep.task_name}
              {/if}
            </td>
            <td>
              {#if blep.job_id}
                <a href={`/jobs/${blep.job_id}`} use:link>
                  {blep.job_number} {blep.job_name}
                </a>
              {/if}
            </td>
            <td>{fmt(blep.start_time)}</td>
            <td>{blep.end_time ? fmt(blep.end_time) : 'Active'}</td>
            <td>
              {#if isEditable(blep)}
                <button type="button" onclick={() => openEdit(blep)}>Edit</button>
              {:else}
                <button type="button" onclick={requestEdit}>Request Edit</button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<BlepEditModal
  open={modalOpen}
  mode="edit"
  blep={editingBlep}
  currentUser={$userStore}
  {userPermissions}
  onSaved={handleSaved}
  onClose={closeModal}
/>
```

- [ ] **Step 2: Mount in Home.svelte above Expenses**

Edit `frontend/src/routes/Home.svelte`. Import `RecentTimeList` and insert the component *above* the existing Expenses section. Find the Expenses section in the markup and insert the import at the top of the `<script>` block and the component immediately before the Expenses section.

```svelte
<script>
  // ... existing imports ...
  import RecentTimeList from '../components/home/RecentTimeList.svelte';
</script>

<!-- In the markup, just before the Expenses section: -->
<RecentTimeList />
```

- [ ] **Step 3: Manual verification**

Log in as a user with recent bleps. Confirm Recent Time appears above Expenses on the home page. Confirm Edit works for recent bleps and Request Edit shows the alert for older ones. If you have no older bleps, create one with a manager user via the API (or temporarily tweak a blep's `start_time` in a Django shell) to exercise the Request Edit path.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/home/RecentTimeList.svelte frontend/src/routes/Home.svelte
git commit -m "add Recent Time section to home page"
```

---

## Chunk 7 — Final verification

### Task 18: Add blep endpoints to atom permission test fixtures

The blep endpoints are all `IsAuthenticated`, so bare users must be able to
reach them. Add them to the existing atom-permission test lists so any
future accidental atom gate gets caught.

**Files:**
- Modify: `tests/test_atom_api_permissions.py`

- [ ] **Step 1: Add bleps to the authenticated-access lists**

Edit `tests/test_atom_api_permissions.py`. Near the top where fixture
lists are defined, add `/api/bleps/` to the list-endpoint set and
`/api/bleps/1/` to the detail endpoint set. Find the
`DETAIL_ENDPOINTS` list (around line 103) and add:

```python
        '/api/bleps/1/',
```

Find the list-endpoint list (around line 86 — look for the list of
`/api/<collection>/` URLs that bare users can GET) and add
`/api/bleps/` there as well. If there isn't a separate list, add the
list URL to wherever list endpoints are covered for bare users.

- [ ] **Step 2: Run the permission tests**

Run: `python manage.py test tests.test_atom_api_permissions --noinput`
Expected: PASS. If a test fails because `/api/bleps/1/` does not exist in
the fixture data, adjust the ID to a blep that the `BaseTestCase` fixture
provides, or skip the specific detail entry.

- [ ] **Step 3: Commit**

```bash
git add tests/test_atom_api_permissions.py
git commit -m "cover /api/bleps/ in atom permission tests"
```

---

### Task 19: Rebuild frontend and run full test suite

**Files:**
- Modify: `frontend/dist/` (rebuild)

- [ ] **Step 1: Rebuild the frontend**

Run: `cd frontend && npm run build`
Expected: build succeeds with no new errors. Warnings about a11y on existing drag handlers are pre-existing and can be ignored.

- [ ] **Step 2: Run full backend test suite**

Run: `python manage.py test --noinput`
Expected: all tests pass.

- [ ] **Step 3: Manual smoke test**

1. Log in as admin. Navigate to a task. Click Start Work. Confirm the blep band appears and task status is `in_progress`.
2. Click Stop Work on the task page. Confirm the band disappears.
3. Click Add Entry in Work Sessions. Create a historical blep for the last hour. Verify it appears in the list.
4. Click Edit on the new blep. Change end time. Save. Verify updated.
5. Click Delete. Verify it is removed.
6. Navigate to Home. Confirm Recent Time shows the bleps you just created.
7. Log in as a user with `can_manage_time` and edit a blep older than 24 h (create one via Django shell first if needed). Verify it works.
8. Log in as bare user. Try to edit another user's blep via direct URL/API: should get 403.

- [ ] **Step 4: Commit (if frontend dist changed)**

```bash
git add frontend/dist/
git commit -m "rebuild frontend for task view and blep editing"
```

---

## Out of scope (intentionally not in this plan)

- Global "My Time" page.
- Blep reassignment across tasks or users.
- Real "Request Edit" workflow (stub only).
- Pay-period-aware editable window.
- Real-time updates to blep lists without refresh.
- Svelte component tests.

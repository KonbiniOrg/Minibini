# Project-Manager Job Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Job's `project_manager` perform `can_manage_jobs`-equivalent writes on **that** job and its contained objects (tasks, worksheets, plan-tasks, estimates, change orders, deliverables, line items) — without the global atom — using one shared predicate consumed by both backend enforcement and the SPA's edit affordances.

**Architecture:** A single predicate `JobService.user_can_manage(user, job)` (atom OR is-PM). Backend: a `CanManageJobOrPM` DRF permission class + a `JobScopedPermissionMixin` that resolves each viewset's target Job; both replace the bare `CanManageJobs` on job-scoped write paths. Frontend: a `can_manage` boolean on the job-scoped serializers (via `JobScopedCanManageMixin`) that the SPA gates on instead of the global `$canManageJobs`. Tasks need no backend change (already `IsAuthenticated`).

**Tech Stack:** Django 5.2 + DRF (MySQL test DB), Svelte 5 SPA (Vitest + @testing-library/svelte).

**Conventions to respect:**
- **Never write to the dev DB.** `makemigrations` is fine; `migrate` is the human's job. Tests use a separate auto-created test DB. **Subagents must not spin up a shell to "verify" models — that writes data. Use tests.**
- TDD: failing test first, watch it fail, minimal code, watch it pass, commit.
- Run backend tests with `python manage.py test tests.<module>` from the repo root. **Never** run the full suite from parallel agents (shared MySQL test DB deadlocks).
- Run frontend tests with `npm run test:run` from `frontend/` (never watch mode).
- Status/permission constants: use model/atom names, never string literals where a constant exists.

**Design reference:** `docs/plans/2026-06-10-pm-job-access-design.md`.

---

## File Structure

**Backend (modify):**
- `apps/jobs/services.py` — add `JobService.user_can_manage(user, job)`.
- `apps/api/permissions.py` — add `CanManageJobOrPM`.
- `apps/api/mixins.py` — add `JobScopedPermissionMixin` and `JobScopedCanManageMixin`.
- `apps/api/jobs/views.py` — `JobViewSet`: mix in, configure, swap permission class.
- `apps/api/jobs/serializers.py` — `JobSerializer`: add `can_manage`.
- `apps/api/worksheets/views.py` + `serializers.py`.
- `apps/api/estimates/views.py` + `serializers.py`.
- `apps/api/plan_tasks/views.py` + `serializers.py`.
- `apps/api/change_orders/views.py` + `serializers.py`.
- `apps/api/deliverables/views.py` + `serializers.py`.
- `apps/api/tasks/serializers.py` — `TaskSerializer`: add `can_manage` (for TaskDetailPage).

**Backend (create tests):**
- `tests/test_pm_job_access.py` — predicate + per-viewset allow/deny matrix + negatives.

**Frontend (modify):**
- `components/jobs/JobHeader.svelte`, `components/jobs/JobDetail.svelte`,
  `routes/jobs/JobEditPage.svelte`, `components/TaskTree.svelte`,
  `routes/jobs/TaskDetailPage.svelte`, `routes/worksheets/WorksheetDetailPage.svelte`,
  `routes/worksheets/PlanTaskDetailPage.svelte`, `routes/estimates/EstimateDetailPage.svelte`,
  `routes/change-orders/ChangeOrderDetailPage.svelte`.

**Frontend (create/extend tests):** the matching `frontend/tests/...` files.

**Docs (Task 14):** `users-and-permissions.md`, `architecture-and-conventions.md`,
`jobs-tasks-and-worksheets.md`.

---

## Task 1: The shared predicate `JobService.user_can_manage`

**Files:**
- Modify: `apps/jobs/services.py` (add a static method to `JobService`)
- Create: `tests/test_pm_job_access.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pm_job_access.py`:

```python
from tests.base import BaseTestCase
from django.contrib.auth.models import Permission
from apps.core.models import User
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.jobs.services import JobService


def grant_manage_jobs(user):
    perm = Permission.objects.get(
        codename='can_manage_jobs', content_type__app_label='core'
    )
    user.user_permissions.add(perm)
    return User.objects.get(pk=user.pk)  # re-fetch to clear perm cache


class UserCanManagePredicateTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(username='pm_p', password='x')
        self.other = User.objects.create_user(username='other_p', password='x')
        self.atom = grant_manage_jobs(
            User.objects.create_user(username='atom_p', password='x')
        )
        self.job = Job.objects.create(
            job_number='JOB-CAN-0001', name='Pred', status=Job.STATUS_DRAFT,
            contact=self.contact, project_manager=self.pm,
        )

    def test_atom_holder_can_manage_any_job(self):
        self.assertTrue(JobService.user_can_manage(self.atom, self.job))

    def test_pm_can_manage_own_job(self):
        self.assertTrue(JobService.user_can_manage(self.pm, self.job))

    def test_non_pm_non_atom_cannot(self):
        self.assertFalse(JobService.user_can_manage(self.other, self.job))

    def test_pm_cannot_manage_unmanaged_job(self):
        other_job = Job.objects.create(
            job_number='JOB-CAN-0002', name='NotMine', status=Job.STATUS_DRAFT,
            contact=self.contact,
        )
        self.assertFalse(JobService.user_can_manage(self.pm, other_job))

    def test_tolerates_none_job(self):
        self.assertFalse(JobService.user_can_manage(self.pm, None))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_pm_job_access.UserCanManagePredicateTest -v 2`
Expected: FAIL — `AttributeError: type object 'JobService' has no attribute 'user_can_manage'`.

- [ ] **Step 3: Add the predicate**

In `apps/jobs/services.py`, add to the `JobService` class:

```python
    @staticmethod
    def user_can_manage(user, job):
        """Single source of truth for 'may this user manage this job and its
        contained objects': the can_manage_jobs atom OR being the job's
        project_manager. Tolerates AnonymousUser / job=None. has_perm returns
        True for superusers, so they pass without a special case."""
        if user is None or not user.is_authenticated:
            return False
        if user.has_perm('core.can_manage_jobs'):
            return True
        return job is not None and job.project_manager_id == user.id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_pm_job_access.UserCanManagePredicateTest -v 2`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services.py tests/test_pm_job_access.py
git commit -m "feat: add JobService.user_can_manage predicate (atom or PM)"
```

---

## Task 2: `CanManageJobOrPM` permission class + `JobScopedPermissionMixin`

**Files:**
- Modify: `apps/api/permissions.py`
- Modify: `apps/api/mixins.py`
- Test: `tests/test_pm_job_access.py` (add a class that unit-tests the mixin resolution + class via a throwaway viewset is overkill; we'll cover behavior end-to-end in Task 3+). This task adds the building blocks and a light import-smoke test.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pm_job_access.py`:

```python
class PermissionBuildingBlocksTest(BaseTestCase):
    def test_imports_exist(self):
        from apps.api.permissions import CanManageJobOrPM
        from apps.api.mixins import JobScopedPermissionMixin
        self.assertTrue(hasattr(JobScopedPermissionMixin, 'get_object_job'))
        self.assertTrue(hasattr(JobScopedPermissionMixin, 'get_permission_target_job'))
        # default object-path resolution maps obj.job -> Job
        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        job = Job.objects.create(
            job_number='JOB-MIX-0001', name='Mix', status=Job.STATUS_DRAFT,
            contact=Contact.objects.first(),
        )
        mixin = JobScopedPermissionMixin()
        mixin.job_object_path = 'self'
        self.assertEqual(mixin.get_object_job(job), job)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_pm_job_access.PermissionBuildingBlocksTest -v 2`
Expected: FAIL — `ImportError: cannot import name 'CanManageJobOrPM'`.

- [ ] **Step 3: Add the permission class**

In `apps/api/permissions.py`, append:

```python
class CanManageJobOrPM(BasePermission):
    """can_manage_jobs atom OR being the target job's project_manager.

    Authoritative at the view level: for a non-atom user we resolve the
    request's target Job (looked-up instance, job-nested URL kwarg, or the
    create body's parent-Job field) and PM-check it. We do NOT rely on
    has_object_permission firing, because custom @actions don't all call
    get_object(); has_object_permission stays as defense-in-depth for the
    standard update/destroy path.
    """
    def has_permission(self, request, view):
        from apps.jobs.services import JobService
        if request.user.has_perm('core.can_manage_jobs'):
            return True
        job = view.get_permission_target_job(request)
        return job is not None and JobService.user_can_manage(request.user, job)

    def has_object_permission(self, request, view, obj):
        from apps.jobs.services import JobService
        if request.user.has_perm('core.can_manage_jobs'):
            return True
        job = view.get_object_job(obj)
        return JobService.user_can_manage(request.user, job)
```

- [ ] **Step 4: Add the view mixin**

In `apps/api/mixins.py`, append:

```python
class JobScopedPermissionMixin:
    """Resolve a viewset's target Job for CanManageJobOrPM.

    Configure per viewset:
      - job_object_path: attribute chain instance -> Job ('self' for JobViewSet,
        'job', 'est_worksheet.job', 'estimate.job', 'change_order.job', ...).
      - job_create_field: request.data key naming the parent Job on create.
      - job_url_kwarg: URL kwarg holding the job id (job-nested routes).
    """
    job_object_path = 'job'
    job_create_field = None
    job_url_kwarg = None

    def get_object_job(self, obj):
        if self.job_object_path == 'self':
            return obj
        target = obj
        for part in self.job_object_path.split('.'):
            target = getattr(target, part, None)
            if target is None:
                return None
        return target

    def get_permission_target_job(self, request):
        from apps.jobs.models import Job
        if self.job_url_kwarg and self.kwargs.get(self.job_url_kwarg):
            return Job.objects.filter(pk=self.kwargs[self.job_url_kwarg]).first()
        lookup = self.lookup_url_kwarg or self.lookup_field
        if self.kwargs.get(lookup) is not None:
            model = self.get_queryset().model
            obj = model._default_manager.filter(pk=self.kwargs[lookup]).first()
            if obj is not None:
                return self.get_object_job(obj)
        if self.job_create_field:
            jid = request.data.get(self.job_create_field)
            if jid:
                return Job.objects.filter(pk=jid).first()
        return None
```

- [ ] **Step 5: Add the serializer mixin** (used from Task 3 on)

In `apps/api/mixins.py`, add near the top imports `from rest_framework import serializers` if not present, then append:

```python
class JobScopedCanManageMixin(serializers.Serializer):
    """Adds read-only `can_manage` = JobService.user_can_manage(request.user,
    <job>). Set `can_manage_job_path` to the chain instance -> Job ('self',
    'job', 'estimate.job', ...). Returns False when there's no request in
    context (e.g. nested serialization without context)."""
    can_manage = serializers.SerializerMethodField()
    can_manage_job_path = 'job'

    def get_can_manage(self, obj):
        from apps.jobs.services import JobService
        request = self.context.get('request')
        if request is None:
            return False
        job = obj
        if self.can_manage_job_path != 'self':
            for part in self.can_manage_job_path.split('.'):
                job = getattr(job, part, None)
                if job is None:
                    return False
        return JobService.user_can_manage(request.user, job)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python manage.py test tests.test_pm_job_access.PermissionBuildingBlocksTest -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/permissions.py apps/api/mixins.py tests/test_pm_job_access.py
git commit -m "feat: add CanManageJobOrPM + JobScoped permission/serializer mixins"
```

---

## Task 3: Wire `JobViewSet` (job edit + `can_manage` on JobSerializer)

**Files:**
- Modify: `apps/api/jobs/views.py` (`JobViewSet`)
- Modify: `apps/api/jobs/serializers.py` (`JobSerializer`)
- Test: `tests/test_pm_job_access.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pm_job_access.py`:

```python
from rest_framework.test import APIClient


class JobViewSetPMAccessTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(username='pm_v', password='x')
        self.other = User.objects.create_user(username='other_v', password='x')
        self.job = Job.objects.create(
            job_number='JOB-VS-0001', name='VS', status=Job.STATUS_DRAFT,
            contact=self.contact, project_manager=self.pm,
        )
        self.unmanaged = Job.objects.create(
            job_number='JOB-VS-0002', name='VS2', status=Job.STATUS_DRAFT,
            contact=self.contact,
        )

    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_pm_can_patch_own_job(self):
        resp = self._client(self.pm).patch(
            f'/api/jobs/{self.job.pk}/', {'name': 'Renamed by PM'}, format='json'
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.job.refresh_from_db()
        self.assertEqual(self.job.name, 'Renamed by PM')

    def test_pm_cannot_patch_unmanaged_job(self):
        resp = self._client(self.pm).patch(
            f'/api/jobs/{self.unmanaged.pk}/', {'name': 'Nope'}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_non_pm_non_atom_cannot_patch(self):
        resp = self._client(self.other).patch(
            f'/api/jobs/{self.job.pk}/', {'name': 'Nope'}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_non_atom_cannot_create_job(self):
        resp = self._client(self.pm).post(
            '/api/jobs/', {'name': 'New', 'contact': self.contact.pk}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_serializer_can_manage_true_for_pm(self):
        resp = self._client(self.pm).get(f'/api/jobs/{self.job.pk}/')
        self.assertTrue(resp.data['can_manage'])

    def test_serializer_can_manage_false_for_other(self):
        resp = self._client(self.other).get(f'/api/jobs/{self.job.pk}/')
        self.assertFalse(resp.data['can_manage'])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_pm_job_access.JobViewSetPMAccessTest -v 2`
Expected: FAIL — `test_pm_can_patch_own_job` gets 403 (still `CanManageJobs`); `can_manage` KeyError.

- [ ] **Step 3: Wire the viewset**

In `apps/api/jobs/views.py`:

Update the import (line 16):
```python
from apps.api.permissions import CanManageJobs, CanManageJobOrPM
```
Add `JobScopedPermissionMixin` to the mixins import (line 15):
```python
from apps.api.mixins import StatusTransitionMixin, JobTaskMixin, JSONDestroyMixin, JobScopedPermissionMixin
```
Add the mixin to the class bases and the resolution attr (line 22):
```python
class JobViewSet(JobScopedPermissionMixin, JSONDestroyMixin, StatusTransitionMixin, JobTaskMixin, viewsets.ModelViewSet):
    job_object_path = 'self'
```
In `get_permissions()` (lines 44-58), replace the two write branches that return
`CanManageJobs()` with `CanManageJobOrPM()`. The `tasks`-POST branch (line 54) and the
final `return` (line 58) become:
```python
            return [IsAuthenticated(), CanManageJobOrPM()]
```
**Leave** `start_invoice_wizard` (line 57) as `(CanManageJobs | CanManageFinancials)()`.

> Note: `JobViewSet.get_queryset` filters by query params. `get_permission_target_job`
> uses `model._default_manager`, bypassing that filter — correct, so a PATCH with a
> stray `?contact=` can't hide the job from the permission check.

- [ ] **Step 4: Add `can_manage` to JobSerializer**

In `apps/api/jobs/serializers.py`:

Import the mixin (after line 1):
```python
from apps.api.mixins import JobScopedCanManageMixin
```
Make `JobSerializer` inherit it and set the path (line 23):
```python
class JobSerializer(JobScopedCanManageMixin, serializers.ModelSerializer):
    can_manage_job_path = 'self'
```
Add `'can_manage'` to `Meta.fields` (after `'project_manager_name'`, line 34):
```python
            'contact', 'contact_name', 'project_manager', 'project_manager_name',
            'can_manage',
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_pm_job_access.JobViewSetPMAccessTest -v 2`
Expected: PASS (6 tests).

- [ ] **Step 6: Regression check the jobs API**

Run: `python manage.py test tests.test_api_jobs -v 2`
Expected: PASS (no regressions).

- [ ] **Step 7: Commit**

```bash
git add apps/api/jobs/views.py apps/api/jobs/serializers.py tests/test_pm_job_access.py
git commit -m "feat: PM object access on JobViewSet + can_manage on JobSerializer"
```

---

## Task 4: Wire `EstWorksheetViewSet` + serializer

**Files:**
- Modify: `apps/api/worksheets/views.py`, `apps/api/worksheets/serializers.py`
- Test: `tests/test_pm_job_access.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pm_job_access.py`:

```python
from apps.estimates.models import EstWorksheet


class WorksheetPMAccessTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(username='pm_ws', password='x')
        self.other = User.objects.create_user(username='other_ws', password='x')
        self.job = Job.objects.create(
            job_number='JOB-WS-0001', name='WS', status=Job.STATUS_DRAFT,
            contact=self.contact, project_manager=self.pm,
        )
        self.ws = EstWorksheet.objects.create(job=self.job)

    def _client(self, user):
        c = APIClient(); c.force_authenticate(user=user); return c

    def test_pm_can_patch_worksheet(self):
        resp = self._client(self.pm).patch(
            f'/api/est-worksheets/{self.ws.pk}/', {}, format='json'
        )
        self.assertIn(resp.status_code, (200, 400))  # not 403 = permission passed
        self.assertNotEqual(resp.status_code, 403)

    def test_other_cannot_patch_worksheet(self):
        resp = self._client(self.other).patch(
            f'/api/est-worksheets/{self.ws.pk}/', {}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_pm_can_create_worksheet_on_own_job(self):
        resp = self._client(self.pm).post(
            '/api/est-worksheets/', {'job': self.job.pk}, format='json'
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_other_cannot_create_worksheet(self):
        resp = self._client(self.other).post(
            '/api/est-worksheets/', {'job': self.job.pk}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_serializer_can_manage(self):
        resp = self._client(self.pm).get(f'/api/est-worksheets/{self.ws.pk}/')
        self.assertTrue(resp.data['can_manage'])
        resp2 = self._client(self.other).get(f'/api/est-worksheets/{self.ws.pk}/')
        self.assertFalse(resp2.data['can_manage'])
```

> If `EstWorksheet.objects.create(job=...)` needs more required fields in this codebase,
> mirror the construction used in `tests/test_api_worksheets.py` setUp rather than guessing.

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_pm_job_access.WorksheetPMAccessTest -v 2`
Expected: FAIL — PM patch/create return 403; `can_manage` KeyError.

- [ ] **Step 3: Wire the viewset**

In `apps/api/worksheets/views.py`:
- Import: `from apps.api.permissions import CanManageJobs, CanManageJobOrPM` (extend the existing import) and add `JobScopedPermissionMixin` from `apps.api.mixins`.
- Class bases: add `JobScopedPermissionMixin` first; set attrs:
```python
class EstWorksheetViewSet(JobScopedPermissionMixin, StatusTransitionMixin, PlanTaskMixin, viewsets.ModelViewSet):
    job_object_path = 'job'
    job_create_field = 'job'
```
- In `get_permissions()`, replace the final `return [IsAuthenticated(), CanManageJobs()]` (line 29) and the write branch of `mixed_actions` with `CanManageJobOrPM()`.

- [ ] **Step 4: Add `can_manage` to the serializer**

In `apps/api/worksheets/serializers.py`, find `EstWorksheetSerializer`, add the mixin:
```python
from apps.api.mixins import JobScopedCanManageMixin
...
class EstWorksheetSerializer(JobScopedCanManageMixin, serializers.ModelSerializer):
    can_manage_job_path = 'job'
```
Add `'can_manage'` to its `Meta.fields`.

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_pm_job_access.WorksheetPMAccessTest -v 2`
Expected: PASS.

- [ ] **Step 6: Regression**

Run: `python manage.py test tests.test_api_worksheets -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/worksheets/ tests/test_pm_job_access.py
git commit -m "feat: PM object access on worksheets + can_manage field"
```

---

## Task 5: Wire `EstimateViewSet` + serializer (incl. line items)

**Files:**
- Modify: `apps/api/estimates/views.py`, `apps/api/estimates/serializers.py`
- Test: `tests/test_pm_job_access.py`

- [ ] **Step 1: Write the failing test**

Append (mirror the worksheet test shape):

```python
from apps.estimates.models import Estimate


class EstimatePMAccessTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(username='pm_est', password='x')
        self.other = User.objects.create_user(username='other_est', password='x')
        self.job = Job.objects.create(
            job_number='JOB-EST-0001', name='EST', status=Job.STATUS_DRAFT,
            contact=self.contact, project_manager=self.pm,
        )
        self.est = Estimate.objects.create(job=self.job, status=Estimate.STATUS_DRAFT)

    def _client(self, user):
        c = APIClient(); c.force_authenticate(user=user); return c

    def test_pm_patch_estimate_not_forbidden(self):
        resp = self._client(self.pm).patch(
            f'/api/estimates/{self.est.pk}/', {}, format='json'
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_other_patch_estimate_forbidden(self):
        resp = self._client(self.other).patch(
            f'/api/estimates/{self.est.pk}/', {}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_pm_add_line_item_not_forbidden(self):
        resp = self._client(self.pm).post(
            f'/api/estimates/{self.est.pk}/line-items/', {}, format='json'
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_other_add_line_item_forbidden(self):
        resp = self._client(self.other).post(
            f'/api/estimates/{self.est.pk}/line-items/', {}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_serializer_can_manage(self):
        resp = self._client(self.pm).get(f'/api/estimates/{self.est.pk}/')
        self.assertTrue(resp.data['can_manage'])
```

> Match `Estimate.objects.create(...)` to the required fields used in
> `tests/test_api_estimates.py` if the minimal form errors.

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_pm_job_access.EstimatePMAccessTest -v 2`
Expected: FAIL — PM gets 403; `can_manage` missing.

- [ ] **Step 3: Wire the viewset**

In `apps/api/estimates/views.py`: add `JobScopedPermissionMixin` base, set
`job_object_path = 'job'` and `job_create_field = 'job'`, import `CanManageJobOrPM`, and
replace `CanManageJobs()` with `CanManageJobOrPM()` in the write branches of
`get_permissions()` (the `mixed_actions` write branch and the final `return`). The
`line_items`/`add_atoms`/`remove_atoms`/`revise`/`send` actions are all detail routes
resolved via the looked-up Estimate → `estimate.job`.

- [ ] **Step 4: Add `can_manage` to the serializer**

In `apps/api/estimates/serializers.py`, on the main `EstimateSerializer`: add
`JobScopedCanManageMixin`, set `can_manage_job_path = 'job'`, add `'can_manage'` to fields.

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_pm_job_access.EstimatePMAccessTest -v 2`
Expected: PASS.

- [ ] **Step 6: Regression**

Run: `python manage.py test tests.test_api_estimates -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/estimates/ tests/test_pm_job_access.py
git commit -m "feat: PM object access on estimates + can_manage field"
```

---

## Task 6: Wire `PlanTaskViewSet` + serializer

**Files:**
- Modify: `apps/api/plan_tasks/views.py`, `apps/api/plan_tasks/serializers.py`
- Test: `tests/test_pm_job_access.py`

PlanTask only gates its `materials`/`material_detail` @actions (all detail routes;
mapping `plan_task.est_worksheet.job`). Creation of plan tasks is nested under the
worksheet viewset (covered in Task 4), so no `job_create_field` here.

- [ ] **Step 1: Write the failing test**

Append:

```python
from apps.jobs.models import PlanTask


class PlanTaskPMAccessTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(username='pm_pt', password='x')
        self.other = User.objects.create_user(username='other_pt', password='x')
        self.job = Job.objects.create(
            job_number='JOB-PT-0001', name='PT', status=Job.STATUS_DRAFT,
            contact=self.contact, project_manager=self.pm,
        )
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.pt = PlanTask.objects.create(est_worksheet=self.ws, name='Cut')

    def _client(self, user):
        c = APIClient(); c.force_authenticate(user=user); return c

    def test_pm_add_material_not_forbidden(self):
        resp = self._client(self.pm).post(
            f'/api/plan-tasks/{self.pt.pk}/materials/', {}, format='json'
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_other_add_material_forbidden(self):
        resp = self._client(self.other).post(
            f'/api/plan-tasks/{self.pt.pk}/materials/', {}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_serializer_can_manage(self):
        resp = self._client(self.pm).get(f'/api/plan-tasks/{self.pt.pk}/')
        self.assertTrue(resp.data['can_manage'])
```

> Match `PlanTask.objects.create(...)` required fields to `tests/test_api_plan_tasks.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_pm_job_access.PlanTaskPMAccessTest -v 2`
Expected: FAIL — 403 + missing `can_manage`.

- [ ] **Step 3: Wire the viewset**

In `apps/api/plan_tasks/views.py`: add `JobScopedPermissionMixin`, set
`job_object_path = 'est_worksheet.job'`, import `CanManageJobOrPM`, and in
`get_permissions()` replace the `materials`/`material_detail` write branch's
`CanManageJobs()` with `CanManageJobOrPM()`.

- [ ] **Step 4: Add `can_manage` to the serializer**

In `apps/api/plan_tasks/serializers.py`, on `PlanTaskSerializer`: add
`JobScopedCanManageMixin`, set `can_manage_job_path = 'est_worksheet.job'`, add
`'can_manage'` to fields.

- [ ] **Step 5: Run / Step 6: Regression / Step 7: Commit**

Run: `python manage.py test tests.test_pm_job_access.PlanTaskPMAccessTest -v 2` → PASS
Run: `python manage.py test tests.test_api_plan_tasks -v 2` → PASS
```bash
git add apps/api/plan_tasks/ tests/test_pm_job_access.py
git commit -m "feat: PM object access on plan-tasks + can_manage field"
```

---

## Task 7: Wire `ChangeOrderViewSet` + serializer (incl. line items)

**Files:**
- Modify: `apps/api/change_orders/views.py`, `apps/api/change_orders/serializers.py`
- Test: `tests/test_pm_job_access.py`

- [ ] **Step 1: Write the failing test**

Append (mirror the estimate test; ChangeOrder maps via `change_order.job`, create uses
`request.data['job']`):

```python
from apps.estimates.models import ChangeOrder


class ChangeOrderPMAccessTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(username='pm_co', password='x')
        self.other = User.objects.create_user(username='other_co', password='x')
        self.job = Job.objects.create(
            job_number='JOB-CO-0001', name='CO', status=Job.STATUS_DRAFT,
            contact=self.contact, project_manager=self.pm,
        )
        self.co = ChangeOrder.objects.create(job=self.job, status=ChangeOrder.STATUS_DRAFT)

    def _client(self, user):
        c = APIClient(); c.force_authenticate(user=user); return c

    def test_pm_patch_co_not_forbidden(self):
        resp = self._client(self.pm).patch(
            f'/api/change-orders/{self.co.pk}/', {}, format='json'
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_other_patch_co_forbidden(self):
        resp = self._client(self.other).patch(
            f'/api/change-orders/{self.co.pk}/', {}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_pm_add_co_line_item_not_forbidden(self):
        resp = self._client(self.pm).post(
            f'/api/change-orders/{self.co.pk}/line-items/', {}, format='json'
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_serializer_can_manage(self):
        resp = self._client(self.pm).get(f'/api/change-orders/{self.co.pk}/')
        self.assertTrue(resp.data['can_manage'])
```

> Match the `ChangeOrder.objects.create(...)` and the `line-items` route name to
> `tests/test_api_change_orders.py` (or the change-orders test module that exists).

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_pm_job_access.ChangeOrderPMAccessTest -v 2`
Expected: FAIL.

- [ ] **Step 3: Wire the viewset**

In `apps/api/change_orders/views.py`: add `JobScopedPermissionMixin`, set
`job_object_path = 'job'` and `job_create_field = 'job'`, import `CanManageJobOrPM`,
replace `CanManageJobs()` with `CanManageJobOrPM()` in the final write `return` of
`get_permissions()`. `seed_new`/`send`/`line_items`/`line_item_detail` are detail routes
resolved via the looked-up ChangeOrder.

- [ ] **Step 4: Add `can_manage` to the serializer**

In `apps/api/change_orders/serializers.py`, on the main change-order serializer: add
`JobScopedCanManageMixin`, `can_manage_job_path = 'job'`, add `'can_manage'` to fields.

- [ ] **Step 5 / 6 / 7:**

Run: `python manage.py test tests.test_pm_job_access.ChangeOrderPMAccessTest -v 2` → PASS
Run: the change-orders API test module → PASS
```bash
git add apps/api/change_orders/ tests/test_pm_job_access.py
git commit -m "feat: PM object access on change-orders + can_manage field"
```

---

## Task 8: Wire `DeliverableViewSet` (job-nested) + serializer

**Files:**
- Modify: `apps/api/deliverables/views.py`, `apps/api/deliverables/serializers.py`
- Test: `tests/test_pm_job_access.py`

Deliverables live at `/api/jobs/{job_id}/deliverables/` — resolve via `job_url_kwarg = 'job_id'`.

- [ ] **Step 1: Write the failing test**

Append:

```python
from apps.deliverables.models import Deliverable


class DeliverablePMAccessTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(username='pm_dl', password='x')
        self.other = User.objects.create_user(username='other_dl', password='x')
        self.job = Job.objects.create(
            job_number='JOB-DL-0001', name='DL', status=Job.STATUS_DRAFT,
            contact=self.contact, project_manager=self.pm,
        )

    def _client(self, user):
        c = APIClient(); c.force_authenticate(user=user); return c

    def test_pm_create_deliverable_not_forbidden(self):
        resp = self._client(self.pm).post(
            f'/api/jobs/{self.job.pk}/deliverables/', {}, format='json'
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_other_create_deliverable_forbidden(self):
        resp = self._client(self.other).post(
            f'/api/jobs/{self.job.pk}/deliverables/', {}, format='json'
        )
        self.assertEqual(resp.status_code, 403)
```

> Confirm the nested URL kwarg name is `job_id` in the deliverables route registration;
> if it differs, set `job_url_kwarg` to match.

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_pm_job_access.DeliverablePMAccessTest -v 2`
Expected: FAIL — PM create 403.

- [ ] **Step 3: Wire the viewset**

In `apps/api/deliverables/views.py`: add `JobScopedPermissionMixin`, set
`job_object_path = 'job'` and `job_url_kwarg = 'job_id'`, import `CanManageJobOrPM`,
replace `CanManageJobs()` with `CanManageJobOrPM()` in the write `return`.

- [ ] **Step 4: Add `can_manage` to the serializer**

In `apps/api/deliverables/serializers.py`: add `JobScopedCanManageMixin`,
`can_manage_job_path = 'job'`, add `'can_manage'` to fields.

- [ ] **Step 5 / 6 / 7:**

Run: `python manage.py test tests.test_pm_job_access.DeliverablePMAccessTest -v 2` → PASS
Run: the deliverables API test module → PASS
```bash
git add apps/api/deliverables/ tests/test_pm_job_access.py
git commit -m "feat: PM object access on deliverables + can_manage field"
```

---

## Task 9: `can_manage` on `TaskSerializer` + contacts-untouched guard

**Files:**
- Modify: `apps/api/tasks/serializers.py` (`TaskSerializer`)
- Test: `tests/test_pm_job_access.py`

Tasks need no backend permission change (writes are already `IsAuthenticated`). We add
`can_manage` so `TaskDetailPage` can gate its edit/assign affordances. We also pin down
that contacts/businesses stay atom-only (negative guard).

- [ ] **Step 1: Write the failing test**

Append:

```python
from apps.jobs.models import Task


class TaskAndContactGuardTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(username='pm_tk', password='x')
        self.other = User.objects.create_user(username='other_tk', password='x')
        self.job = Job.objects.create(
            job_number='JOB-TK-0001', name='TK', status=Job.STATUS_DRAFT,
            contact=self.contact, project_manager=self.pm,
        )
        self.task = Task.objects.create(job=self.job, name='Mill', sort_order=1)

    def _client(self, user):
        c = APIClient(); c.force_authenticate(user=user); return c

    def test_task_serializer_can_manage_for_pm(self):
        resp = self._client(self.pm).get(f'/api/tasks/{self.task.pk}/')
        self.assertTrue(resp.data['can_manage'])

    def test_task_serializer_can_manage_false_for_other(self):
        resp = self._client(self.other).get(f'/api/tasks/{self.task.pk}/')
        self.assertFalse(resp.data['can_manage'])

    def test_pm_cannot_edit_contacts(self):
        # PM has no can_manage_jobs atom -> contacts stay forbidden.
        resp = self._client(self.pm).patch(
            f'/api/contacts/{self.contact.pk}/', {'first_name': 'X'}, format='json'
        )
        self.assertEqual(resp.status_code, 403)
```

> Match `Task.objects.create(...)` to required fields used in `tests/test_api_tasks.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_pm_job_access.TaskAndContactGuardTest -v 2`
Expected: FAIL on the `can_manage` asserts (KeyError); the contacts guard should already PASS.

- [ ] **Step 3: Add `can_manage` to TaskSerializer**

In `apps/api/tasks/serializers.py`, on `TaskSerializer`: add `JobScopedCanManageMixin`,
set `can_manage_job_path = 'job'`, add `'can_manage'` to fields. (The mixin returns
`False` when there's no request in context, so the nested use inside
`JobSerializer.get_tasks` stays safe.)

- [ ] **Step 4: Run / Step 5: Regression / Step 6: Commit**

Run: `python manage.py test tests.test_pm_job_access.TaskAndContactGuardTest -v 2` → PASS
Run: `python manage.py test tests.test_api_tasks -v 2` → PASS
```bash
git add apps/api/tasks/serializers.py tests/test_pm_job_access.py
git commit -m "feat: expose can_manage on TaskSerializer; lock contacts to atom-only"
```

---

## Task 10: Frontend — job header / detail / edit gate on `job.can_manage`

**Files:**
- Modify: `frontend/src/components/jobs/JobHeader.svelte`,
  `frontend/src/components/jobs/JobDetail.svelte`,
  `frontend/src/routes/jobs/JobEditPage.svelte`
- Test: extend `frontend/tests/components/jobs/JobHeader.test.js`,
  `frontend/tests/components/jobs/JobEditPage.test.js`

The pattern: replace `$canManageJobs` reads (for **job-scoped** affordances) with the
per-object `job.can_manage`. Keep imports of the store only where still needed.

- [ ] **Step 1: Write the failing test (JobHeader)**

Append to `frontend/tests/components/jobs/JobHeader.test.js`:

```javascript
describe('JobHeader per-job can_manage gating', () => {
  it('shows the Edit link when job.can_manage is true (even without the global atom)', () => {
    canManageJobs.set(false); // global atom off
    const job = { job_id: 1, job_number: 'JOB-1', name: 'A', status: 'draft', can_manage: true };
    const { getByText } = render(JobHeader, { props: { job } });
    expect(getByText(/Edit/i)).toBeInTheDocument();
  });

  it('hides the Edit link when job.can_manage is false', () => {
    canManageJobs.set(true); // global atom on, but this job not manageable...
    const job = { job_id: 1, job_number: 'JOB-1', name: 'A', status: 'draft', can_manage: false };
    const { queryByText } = render(JobHeader, { props: { job } });
    expect(queryByText(/^Edit$/i)).toBeNull();
  });
});
```

> Ensure the test file imports `canManageJobs` from `@/stores/permissions.js` (add the
> import if absent). The second test encodes that the **per-object** flag wins over the
> global atom — the server already ANDs the atom into `can_manage`, so a `false` here is
> authoritative.

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test:run -- JobHeader`
Expected: FAIL — Edit still tied to `$canManageJobs`.

- [ ] **Step 3: Update JobHeader**

In `frontend/src/components/jobs/JobHeader.svelte`, replace each job-scoped
`$canManageJobs` guard (edit link, duplicate link, status dropdown, release button) with
`job.can_manage`. Remove the now-unused `canManageJobs` import **only if** no other use
remains.

- [ ] **Step 4: Update JobDetail**

In `frontend/src/components/jobs/JobDetail.svelte`, change the derived guards
(`canCreateEstimate`, `canCreateInvoice`, copy-from-worksheet, create-change-order, and
the line-548/667/825 blocks) from `canManageJobs` to `job.can_manage`. Pass the flag into
the task tree: `<TaskTree ... canManage={job.can_manage} />` (consumed in Task 11).
Keep `canManageFinancials` as-is.

- [ ] **Step 5: Update JobEditPage**

In `frontend/src/routes/jobs/JobEditPage.svelte`: the page already loads `job`. Replace
the `canManageJobs` form guard and the "fetch users only if can-manage" condition with
`job.can_manage`. (A PM may reassign the PM field within their own job — that's an
intended, reversible edit.)

- [ ] **Step 6: Write/extend JobEditPage test**

Add a test asserting the form renders and PATCHes when the loaded job has
`can_manage: true` and the global atom is `false`:

```javascript
it('renders the edit form for a PM (job.can_manage) without the global atom', async () => {
  canManageJobs.set(false);
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/jobs/')) return Promise.resolve({ ...JOB, can_manage: true });
    if (url === '/api/auth/users/') return Promise.resolve([]);
    return Promise.resolve({});
  });
  const { getByLabelText } = render(JobEditPage, { props: { params: { id: '7' } } });
  expect(await waitFor(() => getByLabelText(/Name/i))).toBeInTheDocument();
});
```

- [ ] **Step 7: Run tests to verify they pass**

Run (from `frontend/`): `npm run test:run -- JobHeader JobEditPage JobDetail`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/jobs/JobHeader.svelte frontend/src/components/jobs/JobDetail.svelte frontend/src/routes/jobs/JobEditPage.svelte frontend/tests/components/jobs/
git commit -m "feat: gate job header/detail/edit on per-job can_manage"
```

---

## Task 11: Frontend — TaskTree (prop) + TaskDetailPage

**Files:**
- Modify: `frontend/src/components/TaskTree.svelte`, `frontend/src/routes/jobs/TaskDetailPage.svelte`
- Test: extend `frontend/tests/components/TaskTree.test.js` (create if absent),
  `frontend/tests/components/jobs/TaskDetailPage.test.js` (create if absent)

- [ ] **Step 1: Write the failing test (TaskTree)**

```javascript
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import TaskTree from '@/components/TaskTree.svelte';

const tasks = [{ task_id: 1, name: 'Mill', status: 'not_started', sort_order: 1, subtasks: [] }];

describe('TaskTree canManage prop', () => {
  it('shows management buttons when canManage is true', () => {
    const { getByText } = render(TaskTree, { props: { tasks, canManage: true, onAssignTask: () => {} } });
    expect(getByText(/assign/i)).toBeInTheDocument();
  });
  it('hides them when canManage is false', () => {
    const { queryByText } = render(TaskTree, { props: { tasks, canManage: false, onAssignTask: () => {} } });
    expect(queryByText(/assign/i)).toBeNull();
  });
});
```

> Adjust props to match `TaskTree`'s actual required props (it takes `tasks`,
> `onAssignTask`, `readonly`, `showAssignee`, etc.). The point is `canManage` replaces
> the internal `$canManageJobs` read.

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test:run -- TaskTree`
Expected: FAIL — buttons still tied to `$canManageJobs` (true by default in the store).

- [ ] **Step 3: Convert TaskTree to a prop**

In `frontend/src/components/TaskTree.svelte`:
- Add `canManage` to the component props (`let { ..., canManage = false } = $props();`).
- Remove the `import { canManageJobs } from '../stores/permissions.js'` and replace every
  `$canManageJobs` in the template (lines ~168, 180, 187, 190, 242, 254, 260) with
  `canManage`.

- [ ] **Step 4: Pass the prop from every TaskTree caller**

Grep callers: `grep -rn "TaskTree" frontend/src`. For each (`JobDetail.svelte` — already
done in Task 10 — and any others), pass `canManage={job.can_manage}` (or the relevant
object's `can_manage`).

- [ ] **Step 5: Update TaskDetailPage**

In `frontend/src/routes/jobs/TaskDetailPage.svelte`: replace the `$canManageJobs` guards
(edit at ~314, assign at ~341) with the fetched task's `task.can_manage`. Drop the store
import if unused.

- [ ] **Step 6: Write/extend TaskDetailPage test**

Assert the assign/edit affordance appears when `task.can_manage` is true with the global
atom off, and hides when false (mock `api.get` to return the task with the flag).

- [ ] **Step 7: Run tests**

Run (from `frontend/`): `npm run test:run -- TaskTree TaskDetailPage`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/TaskTree.svelte frontend/src/routes/jobs/TaskDetailPage.svelte frontend/tests/
git commit -m "feat: gate task tree/detail on per-job can_manage (prop + task flag)"
```

---

## Task 12: Frontend — worksheet pages

**Files:**
- Modify: `frontend/src/routes/worksheets/WorksheetDetailPage.svelte`,
  `frontend/src/routes/worksheets/PlanTaskDetailPage.svelte`
- Test: extend the matching test files (create if absent)

- [ ] **Step 1: Write the failing test (WorksheetDetailPage)**

Assert that with `worksheet.can_manage = true`, `worksheet.editable = true`, and the
global atom **off**, the "Add task" affordance renders; and that with
`worksheet.can_manage = false` it does not (mock `api.get`).

- [ ] **Step 2: Run to verify it fails**

Run (from `frontend/`): `npm run test:run -- WorksheetDetailPage`
Expected: FAIL.

- [ ] **Step 3: Update the pages**

In `WorksheetDetailPage.svelte`, change:
```javascript
const canEdit = $derived(canManageJobs && (worksheet?.editable ?? false));
```
to:
```javascript
const canEdit = $derived((worksheet?.can_manage ?? false) && (worksheet?.editable ?? false));
```
and the delete guard `canManageJobs && editable && deletable` similarly to
`worksheet?.can_manage && ...`. Drop the `canManageJobs` import if unused.

In `PlanTaskDetailPage.svelte`, change `canManageJobs && worksheet.editable` to
`planTask?.can_manage && worksheet?.editable` (the page fetches the plan task, which now
carries `can_manage`).

- [ ] **Step 4: Run / Step 5: Commit**

Run (from `frontend/`): `npm run test:run -- WorksheetDetailPage PlanTaskDetailPage` → PASS
```bash
git add frontend/src/routes/worksheets/ frontend/tests/
git commit -m "feat: gate worksheet/plan-task pages on per-object can_manage"
```

---

## Task 13: Frontend — estimate + change-order pages

**Files:**
- Modify: `frontend/src/routes/estimates/EstimateDetailPage.svelte`,
  `frontend/src/routes/change-orders/ChangeOrderDetailPage.svelte`
- Test: extend the matching test files

- [ ] **Step 1: Write the failing tests**

For each page: with the object's `can_manage = true`, `isDraft = true`, global atom
**off**, the add-line-item affordance renders; with `can_manage = false` it does not.

- [ ] **Step 2: Run to verify they fail**

Run (from `frontend/`): `npm run test:run -- EstimateDetailPage ChangeOrderDetailPage`
Expected: FAIL.

- [ ] **Step 3: Update the pages**

In `EstimateDetailPage.svelte`: replace `canManageJobs` in the `canEdit` derive and the
revise-button guard with `estimate?.can_manage`.

In `ChangeOrderDetailPage.svelte`: replace the many `canManageJobs && isDraft` (and
plain `canManageJobs`) guards with `changeOrder?.can_manage && isDraft` /
`changeOrder?.can_manage`. The component derives `canManageJobs` from the store at line
50 — repoint that derive to the object, e.g.:
```javascript
const canManage = $derived(changeOrder?.can_manage ?? false);
```
and replace `canManageJobs` usages in the template with `canManage`. Drop the store
import if unused.

- [ ] **Step 4: Run / Step 5: Commit**

Run (from `frontend/`): `npm run test:run -- EstimateDetailPage ChangeOrderDetailPage` → PASS
```bash
git add frontend/src/routes/estimates/ frontend/src/routes/change-orders/ frontend/tests/
git commit -m "feat: gate estimate/change-order pages on per-object can_manage"
```

---

## Task 14: Full-suite verification + docs

**Files:**
- Modify: `docs/designs/users-and-permissions.md`, `docs/designs/architecture-and-conventions.md`,
  `docs/designs/jobs-tasks-and-worksheets.md`

- [ ] **Step 1: Run the backend tests touched by this work** (one agent only)

```bash
python manage.py test tests.test_pm_job_access tests.test_api_jobs tests.test_api_worksheets tests.test_api_estimates tests.test_api_plan_tasks tests.test_api_tasks -v 2
```
Plus the change-orders and deliverables API modules. Expected: all PASS. Fix any
regression before continuing.

- [ ] **Step 2: Run the full frontend suite**

Run (from `frontend/`): `npm run test:run`
Expected: all PASS.

- [ ] **Step 3: Update durable docs**

- `users-and-permissions.md`: add a "Project-manager object access" subsection — the
  `JobService.user_can_manage` predicate, `CanManageJobOrPM` + `JobScopedPermissionMixin`
  + `JobScopedCanManageMixin`, the `can_manage` serializer field, and a note on each
  job-scoped write row that PM access is layered on top of the atom. Explicitly record
  that **contacts/businesses are excluded** and **job create stays atom-only**.
- `architecture-and-conventions.md` §3.5: add `CanManageJobOrPM` to the permission
  classes list and the two mixins to the mixin catalog.
- `jobs-tasks-and-worksheets.md`: note that a Job's `project_manager` can write the job
  and its contained objects (tasks, worksheets, plan-tasks, estimates, change orders,
  deliverables, line items).

- [ ] **Step 4: Commit**

```bash
git add docs/designs/
git commit -m "docs: document project-manager object access"
```

---

## Self-Review Notes

- **Spec coverage:** predicate (T1); permission class + view/serializer mixins (T2);
  per-viewset wiring + `can_manage` for Job (T3), worksheets (T4), estimates+line-items
  (T5), plan-tasks (T6), change-orders+line-items (T7), deliverables (T8); task flag +
  contacts-untouched guard (T9); frontend gating for header/detail/edit (T10), task
  tree/detail (T11), worksheets (T12), estimates/COs (T13); verification + docs (T14).
  Out-of-scope items (contacts/businesses, job create, board reorder, invoice-wizard
  OR-gate, new atom) are intentionally absent and negatively asserted (T3, T9).
- **Naming consistency:** predicate `JobService.user_can_manage(user, job)`; permission
  class `CanManageJobOrPM`; view mixin `JobScopedPermissionMixin` with
  `job_object_path` / `job_create_field` / `job_url_kwarg` and methods
  `get_object_job` / `get_permission_target_job`; serializer mixin
  `JobScopedCanManageMixin` with `can_manage_job_path` and field `can_manage`; frontend
  prop `canManage`. These are used identically across all tasks.
- **Security:** `has_permission` is authoritative (resolves the Job for every non-atom
  write); `has_object_permission` is belt-and-suspenders. Create-with-no-job denies
  non-atom users (job create stays atom-only). Each viewset task asserts PM-allow,
  non-PM-deny, and (where applicable) wrong-job-deny.
- **Type/context safety:** `JobScopedCanManageMixin.get_can_manage` returns `False` when
  no request is in serializer context, so nested `TaskSerializer` use inside
  `JobSerializer.get_tasks` never raises and never leaks a wrong value.

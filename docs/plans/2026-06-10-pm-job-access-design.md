# Project-Manager Job Access — Design

**Date:** 2026-06-10
**Status:** Approved, pending implementation plan
**Builds on:** `2026-06-10-job-project-manager-design.md` (the informational `Job.project_manager` FK already shipped on `feature/pm`).

## Summary

Grant a Job's `project_manager` the equivalent of `can_manage_jobs` **for that one
job and its contained objects** — without granting the global atom. A PM can edit
their job, its tasks, worksheets, plan-tasks, estimates, change orders, deliverables,
and line items, exactly as an atom-holder can — but only on jobs they manage, and
gaining nothing on jobs they don't.

The rule is expressed **once**, server-side, and consumed by both ends so the SPA's
"offer the edit button" decision and the API's "accept the edit" decision can never
drift:

> **`can_manage_job(user, job)` = `user.has_perm('core.can_manage_jobs')` OR `job.project_manager_id == user.id`.**

This is the unification we *thought* already existed but didn't: today permissions are
**global per-atom** on both ends (backend `CanManageJobs` view-level class; frontend
`$canManageJobs` derived store). Neither knows *which* job. This design introduces the
per-object test and threads it through.

## Precedent we're modelling on

The codebase already has the exact *shape* — a single service predicate exposed to the
frontend as a serializer boolean **and** enforced on the backend:

- `WorksheetService.is_editable(worksheet)` → serialized as `EstWorksheetSerializer.editable`
  (frontend gate) **and** asserted in the service. Same for
  `DeliverableService.is_editable`.

Those gate on **estimate/CO state**, not on a permission atom. We add the missing
sibling: a predicate that bundles the **atom + object ownership (PM)**.

## Scope

### In
- A single shared predicate `can_manage_job(user, job)`.
- Backend enforcement of that predicate on every **write** path currently gated by
  `CanManageJobs`, for the job and its contained objects.
- A `can_manage` boolean exposed on the job-scoped serializers so the SPA gates edit
  affordances on the per-object value instead of the global atom.

### Contained objects (PM gains write access)
Job, Task, Material, EstWorksheet, PlanTask, PlanMaterial, Estimate, EstimateLineItem,
ChangeOrder, ChangeOrderLineItem, Deliverable. FK chains to Job:

| Model | Path to Job |
|---|---|
| Job | *(self)* |
| Task | `task.job` |
| Material | `material.job` |
| EstWorksheet | `worksheet.job` |
| PlanTask | `plan_task.est_worksheet.job` |
| PlanMaterial | `plan_material.est_worksheet.job` |
| Estimate | `estimate.job` |
| EstimateLineItem | `line_item.estimate.job` |
| ChangeOrder | `change_order.job` |
| ChangeOrderLineItem | `line_item.change_order.job` |
| Deliverable | `deliverable.job` |

### Out (explicitly)
- **Contacts and businesses.** They share the `can_manage_jobs` atom at the view layer
  but are **not** owned by a job. A PM gets **no** contact/business write access. Their
  viewsets and SPA surfaces are untouched.
- **Job creation.** A PM-to-be can't create a new job (there's no PM relationship until
  the job exists). `POST /api/jobs/` stays atom-only.
- **Cross-job board operations.** The board-level reorder endpoint
  (`/api/jobs/board/*` bulk reorder) spans many jobs and stays on the global atom. The
  *per-job* `reorder_tasks` action (inside a single job) is in scope.
- **The financial OR-gate.** `POST /api/jobs/{id}/start-invoice-wizard/` already accepts
  `can_manage_jobs OR can_manage_financials`. We leave it as-is; a PM-without-atom does
  **not** gain invoice-wizard kickoff through this change (kept conservative; can be
  revisited if desired).
- **No new permission atom**, no Django Groups, no change to `/api/auth/me/` payload.
- **`is_superuser`** continues to bypass everything (it satisfies `has_perm`).

## The shared predicate

```python
# apps/jobs/services.py  (inside JobService)
@staticmethod
def user_can_manage(user, job):
    """Single source of truth for 'may this user manage this job and its
    contained objects'. True if the user holds the can_manage_jobs atom OR
    is the job's project_manager. Tolerates AnonymousUser / job=None."""
    if user is None or not user.is_authenticated:
        return False
    if user.has_perm('core.can_manage_jobs'):
        return True
    return job is not None and job.project_manager_id == user.id
```

`has_perm` returns `True` for superusers, so they pass without a special case (matches
the project's "atoms-only, superuser folds in" convention).

## Backend enforcement

### Permission class
A new DRF class replaces the bare `CanManageJobs` on job-scoped write paths:

```python
# apps/api/permissions.py
class CanManageJobOrPM(BasePermission):
    """can_manage_jobs atom OR being the target job's project_manager.

    Authoritative at the view level: for any non-atom user we resolve the
    request's target Job (from the looked-up instance, a job-nested URL
    kwarg, or the create body's parent-Job field) and PM-check it. We do NOT
    rely on has_object_permission firing — custom @actions don't all call
    get_object(), and silently trusting that would let a non-PM through.
    has_object_permission is kept as defense-in-depth for the standard
    update/destroy path.
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

### View mixin (job resolution, configured per viewset)
```python
# apps/api/mixins.py
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
        # 1. Job-nested route, e.g. /api/jobs/{job_id}/deliverables/.
        if self.job_url_kwarg and self.kwargs.get(self.job_url_kwarg):
            return Job.objects.filter(pk=self.kwargs[self.job_url_kwarg]).first()
        # 2. Detail route: resolve the looked-up instance, then map to its Job.
        lookup = self.lookup_url_kwarg or self.lookup_field
        if self.kwargs.get(lookup) is not None:
            model = self.get_queryset().model
            obj = model._default_manager.filter(pk=self.kwargs[lookup]).first()
            if obj is not None:
                return self.get_object_job(obj)
        # 3. Create with an explicit parent-Job field in the body.
        if self.job_create_field:
            jid = request.data.get(self.job_create_field)
            if jid:
                return Job.objects.filter(pk=jid).first()
        return None
```

Why resolve the Job in `has_permission` (and not lean on `has_object_permission`): DRF
only runs object permissions when an action calls `get_object()`. Several custom
`@action`s mutate without that call. If `has_permission` returned `True` for "some
detail action" trusting object-perms to follow, a non-PM could slip through an action
that never fetches the object. Resolving the Job up front makes the view layer
authoritative for every write.

### Per-viewset wiring
Each viewset (a) mixes in `JobScopedPermissionMixin`, (b) sets the resolution attrs,
(c) swaps `CanManageJobs()` → `CanManageJobOrPM()` in `get_permissions()`. Read actions
(`IsAuthenticated`) are untouched.

| Viewset | `job_object_path` | create/route resolution |
|---|---|---|
| `JobViewSet` | `'self'` | (no PM-create; `create` stays atom-only — see note) |
| `EstWorksheetViewSet` | `'job'` | `job_create_field = 'job'` |
| `EstimateViewSet` | `'job'` | `job_create_field = 'job'` |
| `PlanTaskViewSet` | `'est_worksheet.job'` | *(only material @actions are gated; all detail)* |
| `ChangeOrderViewSet` | `'job'` | `job_create_field = 'job'` |
| `DeliverableViewSet` | `'job'` | `job_url_kwarg = 'job_id'` (nested route) |

**`JobViewSet.create` note:** `create` is not a detail route and has no parent-Job
field, so `get_permission_target_job` returns `None` and a non-atom user is denied —
exactly right (no job exists to be PM of). PM-reachable Job actions
(`partial_update`, `complete`/`work_complete`, `cancel`, `reopen`, `duplicate`,
`reorder_tasks`, `populate_from_template`, `copy_from_worksheet`, the worksheet/estimate
sub-creates, `POST tasks`) are all detail routes resolved via the looked-up Job.

**`start_invoice_wizard`** keeps its own `(CanManageJobs | CanManageFinancials)` gate
(out of scope, see above) — do not convert it.

### Tasks viewset — no backend change needed
`TaskViewSet` already gates **all** writes (lifecycle actions, materials, subtasks) on
`IsAuthenticated`, not the atom — workers self-serve their task lifecycle. So a PM
already passes the backend for tasks. The task work for PMs is **frontend-only**
(the SPA hides task-management affordances behind `$canManageJobs`).

### Service-layer asserts
The viewset gate is the enforcement point. The existing service predicates
(`is_editable`, etc.) are orthogonal state checks and stay. No new service assert is
required for PM, because the permission class denies the request before the service runs.

## Frontend

A `can_manage` boolean is added to the job-scoped serializers; the SPA gates job-scoped
edit affordances on **that per-object value** instead of the global `$canManageJobs`.

### Serializer field (shared mixin)
```python
# apps/api/mixins.py (serializer side)
from rest_framework import serializers

class JobScopedCanManageMixin(serializers.Serializer):
    """Adds a read-only `can_manage` boolean = can_manage_job(request.user, <job>).
    Set `can_manage_job_path` to the attribute chain from the serialized
    instance to its Job ('self', 'job', 'estimate.job', ...). Safe when there
    is no request in context (nested serialization) — returns False."""
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

Applied to: `JobSerializer` (`'self'`), `EstWorksheetSerializer` (`'job'`),
`EstimateSerializer` (`'job'`), `PlanTaskSerializer` (`'est_worksheet.job'`),
`ChangeOrderSerializer` (`'job'`), `DeliverableSerializer` (`'job'`).

**Nested-context caveat:** `JobSerializer.get_tasks` instantiates `TaskSerializer`
without context, so any `can_manage` there would be `False`. That's fine — we don't add
`can_manage` to `TaskSerializer`; the task tree reads the **parent job's** `can_manage`
(threaded as a prop). The detail-task page is handled in its task; see below.

### SPA changes (gate on per-object `can_manage`)
| File | Today gates on | Change to |
|---|---|---|
| `components/jobs/JobHeader.svelte` | `$canManageJobs` (edit/duplicate links, status dropdown, release button) | `job.can_manage` |
| `components/jobs/JobDetail.svelte` | `$canManageJobs` (create estimate / CO / copy-from-worksheet) | `job.can_manage` |
| `routes/jobs/JobEditPage.svelte` | `$canManageJobs` (whole form + PM picker user fetch) | `job.can_manage` |
| `components/TaskTree.svelte` | `$canManageJobs` (edit/delete/assign/reorder) | new `canManage` **prop** |
| `routes/jobs/TaskDetailPage.svelte` | `$canManageJobs` (edit, assign) | task payload's job `can_manage` |
| `routes/worksheets/WorksheetDetailPage.svelte` | `canManageJobs && worksheet.editable` | `worksheet.can_manage && worksheet.editable` |
| `routes/worksheets/PlanTaskDetailPage.svelte` | `canManageJobs && worksheet.editable` | `planTask.can_manage && worksheet.editable` |
| `routes/estimates/EstimateDetailPage.svelte` | `canManageJobs && isDraft` | `estimate.can_manage && isDraft` |
| `routes/change-orders/ChangeOrderDetailPage.svelte` | `canManageJobs && isDraft` | `changeOrder.can_manage && isDraft` |

`JobDetail` passes `canManage={job.can_manage}` into `TaskTree`. `JobEditPage` fetches
the user dropdown when `job.can_manage` (PMs can reassign within their job — note this
lets a PM hand the job to someone else; acceptable, it's a reversible field edit).

`TaskDetailPage`: the SPA fetches `/api/tasks/{id}/`; we add a `can_manage` to that
payload via `TaskSerializer` (path `'job'`), guarded so nested use returns `False`.

The global `$canManageJobs` store stays — it still drives **non-job-scoped** surfaces
(nav links, contacts/businesses, email-to-job actions) and is the fast atom signal.

## Security review checklist (called out for the implementer)
- A non-atom, non-PM user gets **403** on every contained-object write (job, task add,
  worksheet, plan-task, estimate, CO, deliverable, all line items).
- A PM gets **200** on those for **their** job and **403** for a job they don't manage.
- `POST /api/jobs/` (create) is **403** for a non-atom user even if they manage other jobs.
- Contacts/businesses writes are **unchanged** (still atom-only); a PM gets no access.
- Read endpoints are unchanged (`IsAuthenticated`).

## Testing strategy
- Backend: a focused `tests/test_pm_job_access.py` exercising the predicate and, per
  viewset, the PM-allow / non-PM-deny / wrong-job-deny matrix. Plus the create-denied and
  contacts-untouched negatives. TDD; separate test DB.
- Frontend (Vitest): each gated component shows its affordance when the object's
  `can_manage` is `true` and hides it when `false`, independent of the global atom store.

## Docs to update on completion
- `docs/designs/users-and-permissions.md` — new "Project-manager object access" section:
  the `can_manage_job` predicate, the `CanManageJobOrPM` class + `JobScopedPermissionMixin`,
  the `can_manage` serializer field, and the endpoint-table notes (PM ⊂ each job-scoped
  write row; contacts/businesses explicitly excluded).
- `docs/designs/architecture-and-conventions.md` §3.5 — add `CanManageJobOrPM` and the two
  mixins to the permissions plumbing + mixin catalog.
- `docs/designs/jobs-tasks-and-worksheets.md` — note PM write access to a job and its
  contained objects.

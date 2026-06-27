"""
Service classes for handling complex creation workflows between Jobs and Tasks.
"""

from datetime import timedelta
from apps.core.history import record_history
from decimal import Decimal
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q, Prefetch
from django.utils import timezone

from apps.jobs.models import Job, Task, Blep, RateScheme, copy_active_modifiers
from apps.estimates.models import (
    Estimate, WorkTemplate, TaskTemplate,
    EstWorksheet, EstimateLineItem,
)
from apps.inventory.models import InventoryItem
from apps.core.models import Configuration
from apps.core.services import NumberGenerationService, NotFoundError, SELF_EDIT_WINDOW_HOURS


# ═══════════════════════════════════════════════════════════════════
# BlepService (formerly apps.jobs.services.blep_service)
# ═══════════════════════════════════════════════════════════════════

class BlepPermissionError(Exception):
    """Raised when a caller is not permitted to perform a blep operation."""
    pass


class TaskActualQtyRequired(Exception):
    """Raised when completing an ENTERED_QTY task that has no worker-entered
    quantity. Carries the rate scheme's unit label so the caller can prompt
    for the value."""
    def __init__(self, unit_label=''):
        self.unit_label = unit_label
        super().__init__(
            'A quantity must be entered before this task can be completed.'
        )


class TaskTimeRequired(Exception):
    """Raised when completing an ELAPSED_TIME task that has no recorded time
    (no bleps, or zero total). The caller should prompt for a historical
    time entry."""
    pass


class TaskWorkerTimeRequired(Exception):
    """Raised when assigning a task to a worker while it has no estimated
    worker time. Assigned work has to be schedulable, and it can't be
    scheduled without a duration — the caller should prompt for an estimate."""
    pass


_EDIT_WINDOW = timedelta(hours=SELF_EDIT_WINDOW_HOURS)  # matches ShiftService.SELF_EDIT_WINDOW_HOURS

# Below this elapsed duration (whole minutes), a worker's Stop becomes Cancel
# (delete + undo). Lazy default written into Configuration on first read
# (mirrors the schedule keys). Times are minute-granular, so this is in minutes.
_BLEP_MINIMUM_MINUTES_DEFAULT = '1'


def blep_minimum_minutes():
    """The Stop→Cancel threshold (whole minutes). Single source of truth, also
    read by the API to expose it to the client. Lazy default written on first
    read."""
    try:
        return int(Configuration.objects.get(key='blep_minimum_minutes').value)
    except Configuration.DoesNotExist:
        Configuration.objects.create(
            key='blep_minimum_minutes', value=_BLEP_MINIMUM_MINUTES_DEFAULT,
        )
        return int(_BLEP_MINIMUM_MINUTES_DEFAULT)
    except (TypeError, ValueError):
        return int(_BLEP_MINIMUM_MINUTES_DEFAULT)


def _has_manage_time(user):
    return user.has_perm('core.can_manage_time')


def _within_edit_window(start_time, now=None):
    if now is None:
        now = timezone.now()
    return (now - start_time) < _EDIT_WINDOW


def _existing_overlaps(user, start_time, end_time, exclude_blep_id=None):
    """Does `user` already have a blep whose interval intersects
    [start_time, end_time)? Open bleps are treated as [start, now)."""
    # A blep's effective interval is [start, end or now).
    # Overlap: existing.start < new.end AND (existing.end or now) > new.start
    qs = Blep.objects.filter(user=user, start_time__lt=end_time)
    qs = qs.exclude(
        end_time__isnull=False, end_time__lte=start_time,
    ).exclude(
        end_time__isnull=True, start_time__gte=end_time,
    )
    if exclude_blep_id is not None:
        qs = qs.exclude(blep_id=exclude_blep_id)
    return qs.exists()


def _assert_job_allows_blep(job, allowed_statuses, action):
    """Reject Blep creation when the Task's Job is in a status where work
    should not be recorded against it."""
    if job.status not in allowed_statuses:
        labels = ', '.join(f"'{s}'" for s in allowed_statuses)
        raise ValidationError(
            f"Cannot {action}: job status is '{job.status}', "
            f"must be one of {labels}."
        )


def _assert_job_not_on_hold(job, action):
    """Reject task/material mutations while the job is paused on_hold.

    Resolve the open change order (accept/reject/discard) or take the job
    off hold before making changes.
    """
    if job.status == Job.STATUS_ON_HOLD:
        raise ValidationError(
            f"Cannot {action} while the job is on hold. Resolve the open "
            f"change order (or take the job off hold) first."
        )


class BlepService:
    """All Blep (time entry) writes flow through this service.

    Primitives (leading underscore) skip validation — for trusted internal
    callers like TaskLifecycleService. Public methods enforce ownership,
    time windows, and overlap rules for user-initiated edits.
    """

    # Tolerance for mismatched device clocks when rejecting future end times.
    _CLOCK_SKEW_BUFFER = timedelta(seconds=30)

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
    def _under_minimum(blep, close_time):
        """True when closing `blep` at `close_time` yields fewer whole minutes
        than the configured minimum. start_time is already minute-floored on
        save, so this compares whole minutes."""
        if blep.start_time is None:
            return False
        whole_minutes = int((close_time - blep.start_time).total_seconds() // 60)
        return whole_minutes < blep_minimum_minutes()

    @staticmethod
    def _cancel_blep(blep):
        """Delete an open blep with full cancel_work semantics.

        Locks the blep's task, computes whether this blep is the first/only
        activity (task is in_progress AND this is the only blep on it), deletes
        the blep, and — if first/only — reverts the task to pending and
        un-consumes its materials. This is exactly what cancel_work does after
        its guard; callers that hand an instance here must NOT re-query for the
        open blep nor re-apply the "too long" guard.
        """
        task = Task.objects.select_for_update().get(pk=blep.task_id)
        first_activity = (
            task.status == Task.STATUS_IN_PROGRESS
            and Blep.objects.filter(task=task).count() == 1
        )
        blep.delete()
        if first_activity:
            reverted = Task.objects.filter(
                pk=task.pk, status=Task.STATUS_IN_PROGRESS,
            ).update(status=Task.STATUS_PENDING)
            if reverted:
                from apps.inventory.services import MaterialService
                for material in task.materials.all():
                    if material.consumption_state == \
                            material.CONSUMPTION_STATE_CONSUMED:
                        MaterialService.unconsume(material)

    @staticmethod
    def _resolve_open_blep(blep, now):
        """Close an open blep, or cancel it (full undo) if it's under the
        minimum — the shared resolution used by every close path."""
        if BlepService._under_minimum(blep, now):
            BlepService._cancel_blep(blep)
        else:
            blep.end_time = now
            blep.save()

    @staticmethod
    def _close_open(user=None, task=None, now=None):
        """Resolve all open Bleps matching the given filter.

        At least one of `user` or `task` must be provided. Each open blep is
        resolved individually: a sub-minimum blep is an accidental start and is
        cancelled with full undo (delete + first/only-activity revert); an
        at-or-over-minimum blep is closed (end_time floored to the minute on
        save). Returns the number of bleps that were resolved.
        """
        # Programming-error guard: no DB needed, keep outside the atomic.
        if user is None and task is None:
            raise ValueError("_close_open requires user or task filter")
        if now is None:
            now = timezone.now()
        # Self-atomic: _cancel_blep uses select_for_update(), which requires an
        # enclosing transaction. Callers under autocommit (logout, deactivate)
        # would otherwise 500. Nested inside an existing atomic block this is
        # just a savepoint, which is fine.
        with transaction.atomic():
            qs = Blep.objects.filter(end_time__isnull=True)
            if user is not None:
                qs = qs.filter(user=user)
            if task is not None:
                qs = qs.filter(task=task)
            bleps = list(qs)
            for blep in bleps:
                BlepService._resolve_open_blep(blep, now)
            return len(bleps)

    @staticmethod
    def close_user_open_bleps(user, now=None):
        """Close all open bleps for the given user.

        Public wrapper around _close_open — used by UserAdminService when
        deactivating a user. Returns the number of bleps that were closed.
        """
        return BlepService._close_open(user=user, now=now)

    # ─────────────────────────── public API ───────────────────────────

    @staticmethod
    def create_historical(actor, task, start_time, end_time, target_user=None):
        """Create a historical blep with validation.

        - actor: the user performing the action
        - target_user: user the blep belongs to (defaults to actor)
        - Creating for another user requires can_manage_time
        - Creating older than 30h requires can_manage_time
        - Task must belong to a Job
        - end_time must be >= start_time
        - Must not overlap another blep for target_user
        """
        if target_user is None:
            target_user = actor
        if target_user != actor and not _has_manage_time(actor):
            raise BlepPermissionError(
                "Creating a time entry for another user requires can_manage_time."
            )
        # Post-split: task is always a Task (work-order side); no container check needed.
        # STATUS_CANCELLED is allowed for backfill — forgotten time can still be
        # logged against a stopped job for billing purposes.
        _assert_job_allows_blep(
            task.job,
            (Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS,
             Job.STATUS_WORK_COMPLETE, Job.STATUS_CANCELLED),
            'log time',
        )
        if task.status == Task.STATUS_COMPLETE:
            raise ValidationError(
                "Cannot log time on a complete task. Create a new task for "
                "additional work."
            )
        if end_time < start_time:
            raise ValidationError("end_time must be >= start_time.")
        if end_time > timezone.now() + BlepService._CLOCK_SKEW_BUFFER:
            raise ValidationError("End time cannot be in the future.")
        if not _within_edit_window(start_time) and not _has_manage_time(actor):
            raise BlepPermissionError(
                "Creating a time entry older than 30 hours requires can_manage_time."
            )
        if _existing_overlaps(target_user, start_time, end_time):
            raise ValidationError(
                "This time entry overlaps an existing entry for the user."
            )
        if target_user is not None:
            from apps.core.time_integrity import enclosing_shift_for_blep
            if enclosing_shift_for_blep(target_user, start_time, end_time) is None:
                raise ValidationError(
                    "No shift encloses this time — clock in / add a shift covering it first."
                )
        with transaction.atomic():
            blep = BlepService._create(
                task, target_user, start_time=start_time, end_time=end_time,
            )
            TaskLifecycleService._promote_pending_task(task)
            JobService.mark_work_started(task.job)
        return blep

    @staticmethod
    def update(blep, actor, **fields):
        """Update a blep. Only `start_time` and `end_time` are editable here."""
        is_own = blep.user_id == actor.pk
        if is_own:
            if not _within_edit_window(blep.start_time) and not _has_manage_time(actor):
                raise BlepPermissionError(
                    "Editing a time entry older than 30 hours requires can_manage_time."
                )
        else:
            if not _has_manage_time(actor):
                raise BlepPermissionError(
                    "Editing another user's time entry requires can_manage_time."
                )

        allowed_fields = {'start_time', 'end_time'}
        # Reassigning a blep to a different user requires can_manage_time
        if 'user' in fields:
            if not _has_manage_time(actor):
                raise ValidationError(
                    "Reassigning a time entry to another user requires can_manage_time."
                )
            allowed_fields.add('user')

        unknown = set(fields) - allowed_fields
        if unknown:
            raise ValidationError(
                f"Cannot update fields: {', '.join(sorted(unknown))}"
            )

        new_start = fields.get('start_time', blep.start_time)
        new_end = fields.get('end_time', blep.end_time)
        if new_end is not None and new_start is not None and new_end < new_start:
            raise ValidationError("end_time must be >= start_time.")
        if new_end is not None and new_end > timezone.now() + BlepService._CLOCK_SKEW_BUFFER:
            raise ValidationError("End time cannot be in the future.")

        # Use the target user for overlap check (new user if reassigning, else current)
        check_user = fields.get('user', blep.user)
        effective_end = new_end if new_end is not None else timezone.now()
        if _existing_overlaps(
            check_user, new_start, effective_end, exclude_blep_id=blep.blep_id,
        ):
            raise ValidationError(
                "This time entry would overlap an existing entry for the user."
            )

        # Enclosure guard: a closed blep must sit inside one of its user's
        # shifts. Skip orphan (user-less) bleps and still-open bleps (no end).
        if check_user is not None and new_end is not None:
            from apps.core.time_integrity import enclosing_shift_for_blep
            if enclosing_shift_for_blep(check_user, new_start, new_end) is None:
                raise ValidationError(
                    "No shift encloses the edited time — widen the enclosing shift first."
                )

        for k, v in fields.items():
            setattr(blep, k, v)
        blep.save()
        return blep

    @staticmethod
    def delete(blep, actor):
        is_own = blep.user_id == actor.pk
        if is_own:
            if not _within_edit_window(blep.start_time) and not _has_manage_time(actor):
                raise BlepPermissionError(
                    "Deleting a time entry older than 30 hours requires can_manage_time."
                )
        else:
            if not _has_manage_time(actor):
                raise BlepPermissionError(
                    "Deleting another user's time entry requires can_manage_time."
                )
        blep.delete()


# ═══════════════════════════════════════════════════════════════════
# JobService, TaskService, TaskLifecycleService
# ═══════════════════════════════════════════════════════════════════

class JobService:
    """Service for Job CRUD operations and workflows."""

    @staticmethod
    def user_holds_manage_jobs_atom(user):
        """True if the user holds (or bypasses) the can_manage_jobs atom.

        Resolves the atom with a single direct query against user_permissions
        rather than ``has_perm`` so callers that need it once per request
        (e.g. list serialization of can_manage) don't depend on Django's
        per-user-instance permission cache — that cache crosses requests for a
        reused user object and makes per-request query counts non-constant.
        Superusers bypass. Inactive users hold nothing, matching ``has_perm``
        (which returns False for inactive users, superuser or not) so this
        stays a faithful stand-in."""
        if user is None or not user.is_authenticated or not user.is_active:
            return False
        if user.is_superuser:
            return True
        return user.user_permissions.filter(
            codename='can_manage_jobs',
            content_type__app_label='core',
        ).exists()

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

    @staticmethod
    def create_job(**kwargs):
        """Create a new Job with auto-generated number."""
        job_number = NumberGenerationService.generate_next_number('job')
        job = Job(job_number=job_number, **kwargs)
        job.full_clean()
        job.save()
        return job

    # Job statuses whose entry releases the job's earmarks (work is done or
    # the job is dead — any reservation against inventory is freed).
    _EARMARK_RELEASING_STATUSES = (
        Job.STATUS_WORK_COMPLETE, Job.STATUS_CANCELLED, Job.STATUS_REJECTED,
    )

    @staticmethod
    def update_job(pk, **kwargs):
        """Base Job update. Applies field changes and dispatches
        status-transition side effects (loose-materials gate, earmark
        release). update_status() is a thin wrapper over this — every Job
        status change should flow through here."""
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {pk} not found')
        old_status = job.status
        for field, value in kwargs.items():
            setattr(job, field, value)
        status_changed = job.status != old_status

        if status_changed and job.status in (Job.STATUS_ON_HOLD, Job.STATUS_CANCELLED):
            if Blep.objects.filter(task__job=job, end_time__isnull=True).exists():
                raise ValidationError(
                    'Cannot pause or cancel the job while a worker has an open time entry — '
                    'have them stop first.'
                )

        if status_changed and old_status == Job.STATUS_ON_HOLD:
            from apps.estimates.models import ChangeOrder
            if ChangeOrder.objects.filter(
                job=job, status__in=[ChangeOrder.STATUS_DRAFT, ChangeOrder.STATUS_OPEN]
            ).exists():
                raise ValidationError(
                    'Resolve the open change order (accept, reject, or discard it) '
                    'before taking the job off hold.'
                )

        if status_changed and job.status == Job.STATUS_WORK_COMPLETE:
            offenders = JobService._loose_pending_materials(job)
            if offenders.exists():
                names = ', '.join(m.description or str(m.pk) for m in offenders)
                raise ValidationError(
                    f'Cannot advance to work_complete: unresolved task-less materials: {names}'
                )

        if status_changed and job.status == Job.STATUS_COMPLETED:
            from apps.deliverables.services import DeliverableService
            if not DeliverableService.all_deliverables_shipped(job):
                raise ValidationError(
                    'All deliverables must be shipped before completing the job.'
                )

        job.full_clean()
        job.save()

        if status_changed and job.status in JobService._EARMARK_RELEASING_STATUSES:
            from apps.inventory.services import InventoryService
            InventoryService.release_earmarks_for_job(job)

        return job

    @staticmethod
    def _loose_pending_materials(job):
        """Return task-less Materials on this job that still have a positive
        outstanding quantity committed to the job and are in the PENDING
        consumption state."""
        from apps.inventory.models import Material
        return Material.objects.filter(
            job=job,
            task__isnull=True,
            consumption_state=Material.CONSUMPTION_STATE_PENDING,
            quantity__gt=0,
        )

    @staticmethod
    def release_loose_materials(job):
        """Restock (release) any task-less PENDING materials still committed
        to the job. Returns a list of {'description', 'quantity'} captured
        before restock removes the rows — used for an audit record."""
        from apps.inventory.services import MaterialService
        released = []
        for material in list(JobService._loose_pending_materials(job)):
            released.append({
                'description': material.description or f'Material {material.pk}',
                'quantity': str(material.quantity),
            })
            MaterialService.restock(material, material.quantity)
        return released

    @staticmethod
    def update_status(pk, new_status):
        """Thin wrapper over update_job for a status-only change."""
        return JobService.update_job(pk, status=new_status)

    @staticmethod
    def maybe_complete_if_resolved(job):
        """Complete the job if all its invoices are resolved AND all its
        deliverables are fully picked up.

        This is the canonical completion check.  It is called from two paths:
          * ``Invoice._maybe_complete_job`` — fires when the last invoice is paid.
          * ``ShipmentService.mark_picked_up`` — fires when the last shipment is
            picked up.
        Whichever arrives last triggers the actual completion.

        Behaviour:
          - Refreshes the job from the DB (callers may hold a stale instance).
          - No-ops if the job is already completed or cancelled.
          - No-ops if any invoice is still unresolved (not paid/cancelled).
          - No-ops if any deliverable is not yet fully picked up.
          - Releases loose (task-less, pending) materials, records a system
            HistoryEntry for the release, then walks the job to ``completed``.
        """
        from apps.core.models import User
        from apps.deliverables.services import DeliverableService
        from apps.invoicing.models import Invoice

        job.refresh_from_db()
        if job.status in (Job.STATUS_COMPLETED, Job.STATUS_CANCELLED):
            return

        # All invoices must be resolved (paid or cancelled).
        unresolved = Invoice.objects.filter(job=job).exclude(
            status__in=(Invoice.STATUS_PAID, Invoice.STATUS_CANCELLED)
        ).exists()
        if unresolved:
            return

        # All deliverables must be fully picked up.
        if not DeliverableService.all_deliverables_shipped(job):
            return

        old_status = job.status
        system_user, _ = User.objects.get_or_create(
            username='system',
            defaults={'first_name': 'System', 'is_active': False},
        )

        # Invoice-paid / shipment completion is unattended — release loose
        # materials rather than letting the work_complete gate strand the job.
        released = JobService.release_loose_materials(job)
        if released:
            record_history(
                entry_type='action',
                object_type='job',
                object_id=job.pk,
                user=system_user,
                changes={
                    '_action': (
                        'Loose materials released on invoice-completion: '
                        + ', '.join(
                            f"{m['description']} (qty {m['quantity']})"
                            for m in released
                        )
                    ),
                },
            )

        # Walk through intermediate statuses when coming from early states.
        if job.status == Job.STATUS_APPROVED:
            job = JobService.update_job(job.pk, status=Job.STATUS_IN_PROGRESS)
        if job.status == Job.STATUS_IN_PROGRESS:
            job = JobService.update_job(job.pk, status=Job.STATUS_WORK_COMPLETE)
        job = JobService.update_job(job.pk, status=Job.STATUS_COMPLETED)

        record_history(
            entry_type='action',
            object_type='job',
            object_id=job.pk,
            user=system_user,
            changes={
                'status': {'old': old_status, 'new': Job.STATUS_COMPLETED},
                '_action': 'All invoices paid — job completed',
            },
        )

    @staticmethod
    def mark_work_started(job):
        """Advance an APPROVED Job to IN_PROGRESS when work begins on it
        (a Blep is created, or a Task is completed). No-op for any other
        status — pre-APPROVED jobs are left alone, and the state machine
        forbids a direct jump from DRAFT/SUBMITTED to IN_PROGRESS."""
        if job.status == Job.STATUS_APPROVED:
            JobService.update_status(job.pk, Job.STATUS_IN_PROGRESS)

    @staticmethod
    def populate_from_template(job, template):
        """Populate a Job's tasks and materials from a WorkTemplate. The
        template itself is not stored on the Job; only its generated children
        land here."""
        task_pairing = template.generate_tasks_for_job(job)
        template.generate_materials_for_job(job, task_pairing=task_pairing)

        from apps.inventory.services import InventoryService
        InventoryService.create_earmarks_for_job(job)
        return job

    @staticmethod
    def materialize_worksheet_onto_job(job, worksheet):
        """Create execution Tasks/Materials on ``job`` from ``worksheet``'s
        PlanTasks/PlanMaterials. The single shared core behind both the
        estimate-acceptance carry-over (#2) and the manual copy-from-worksheet
        button (#3).

        Idempotent on provenance (``source_plan_task`` / ``source_plan_material``):
        re-running skips atoms already carried, so it is safe to call twice and
        safe when both entry points run for the same worksheet (manual copy then
        acceptance won't duplicate). Tasks clone faithfully even when their rate
        scheme has since been superseded. Ends with the aggregate earmark sweep.

        Returns ``{'tasks_created': int, 'materials_created': int}``.
        """
        from apps.jobs.models import PlanTask, Task
        from apps.inventory.models import PlanMaterial, Material
        from apps.inventory.services import InventoryService, MaterialService

        tasks_created = 0
        materials_created = 0

        for pt in PlanTask.objects.filter(
            est_worksheet=worksheet
        ).order_by('sort_order', 'pk'):
            if Task.objects.filter(job=job, source_plan_task=pt).exists():
                continue
            TaskService.create_direct(
                job=job, source_plan_task=pt, actual_qty=None,
                allow_superseded_scheme=True, **pt.copy_fields(),
            )
            tasks_created += 1

        for pm in PlanMaterial.objects.filter(est_worksheet=worksheet):
            if Material.objects.filter(job=job, source_plan_material=pm).exists():
                continue
            task = None
            if pm.plan_task_id:
                task = Task.objects.filter(
                    job=job, source_plan_task=pm.plan_task).first()
            MaterialService.create_on_job(
                job=job, task=task, source_plan_material=pm, **pm.copy_fields(),
            )
            materials_created += 1

        InventoryService.create_earmarks_for_job(job)
        return {'tasks_created': tasks_created, 'materials_created': materials_created}

    @staticmethod
    def copy_from_worksheet(job_pk, worksheet_pk):
        """Manually copy a worksheet's PlanTasks/PlanMaterials onto a job.

        The pre-acceptance counterpart to estimate carry-over; both delegate to
        the shared ``materialize_worksheet_onto_job`` core, so the field set,
        provenance, idempotency, and earmarking stay identical between them.
        """
        from apps.estimates.models import EstWorksheet

        try:
            job = Job.objects.get(pk=job_pk)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {job_pk} not found')
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')

        JobService.materialize_worksheet_onto_job(job, ws)

    @staticmethod
    def duplicate_job(source_job, *, contact, path):
        """Copy `source_job` into a new Job. `path` is 'approved' or 'estimate'.
        Work is always sourced from the source Job's execution Tasks/Materials.
        Returns the new (refreshed) Job."""
        if path not in ('approved', 'estimate'):
            raise ValidationError(
                f"Invalid path '{path}'; expected 'approved' or 'estimate'.")
        with transaction.atomic():
            new_job = JobService.create_job(
                name=source_job.name,
                description=source_job.description,
                contact=contact,
            )
            JobService._copy_deliverables(source_job, new_job)
            if path == 'approved':
                JobService._copy_work_to_job(source_job, new_job)
                from apps.inventory.services import InventoryService
                InventoryService.create_earmarks_for_job(new_job)
                JobService._advance_to_approved(new_job, source_job)
            else:
                JobService._copy_work_to_worksheet(source_job, new_job)
            new_job.refresh_from_db()
            return new_job

    @staticmethod
    def _copy_deliverables(source_job, new_job):
        from apps.deliverables.services import DeliverableService
        from apps.deliverables.models import Deliverable
        for d in Deliverable.objects.filter(job=source_job).order_by('sort_order', 'pk'):
            DeliverableService.create(
                job_id=new_job.pk,
                description=d.description,
                qty_ordered=d.qty_ordered,
                units=d.units,
                sort_order=d.sort_order,
            )

    @staticmethod
    def _copy_work_to_job(source_job, new_job):
        """Outcome A: copy execution Tasks (reset, hierarchy preserved) + Materials."""
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        from apps.inventory.services import MaterialService

        source_tasks = list(
            Task.objects.filter(job=source_job).order_by('sort_order', 'pk'))
        task_map = {}  # source task_id -> new Task
        for task in source_tasks:
            new_task = Task.objects.create(
                job=new_job,
                status=Task.STATUS_PENDING,
                **task.copy_fields(),
            )
            task_map[task.pk] = new_task
        # Second pass: wire parent_task hierarchy onto the new tasks.
        for task in source_tasks:
            if task.parent_task_id and task.parent_task_id in task_map:
                new_task = task_map[task.pk]
                new_task.parent_task = task_map[task.parent_task_id]
                new_task.save()
        # Materials (task-attached follow their remapped task; task-less stay loose).
        for material in Material.objects.filter(job=source_job).order_by('pk'):
            MaterialService.create_on_job(
                job=new_job,
                task=task_map.get(material.task_id),
                **material.copy_fields(),
            )

    @staticmethod
    def _advance_to_approved(new_job, source_job):
        """Walk draft -> submitted -> approved through the service, recording a
        HistoryEntry per hop. Mirrors apps/estimates/signals.py:96-116."""
        from apps.core.models import User
        system_user, _ = User.objects.get_or_create(
            username='system',
            defaults={'first_name': 'System', 'is_active': False},
        )
        action_desc = f"Duplicated from {source_job.job_number}"
        JobService.update_status(new_job.pk, Job.STATUS_SUBMITTED)
        record_history(
            entry_type='action', object_type='job', object_id=new_job.pk,
            user=system_user,
            changes={'status': {'old': Job.STATUS_DRAFT, 'new': Job.STATUS_SUBMITTED},
                     '_action': action_desc},
        )
        JobService.update_status(new_job.pk, Job.STATUS_APPROVED)
        record_history(
            entry_type='action', object_type='job', object_id=new_job.pk,
            user=system_user,
            changes={'status': {'old': Job.STATUS_SUBMITTED, 'new': Job.STATUS_APPROVED},
                     '_action': action_desc},
        )

    @staticmethod
    def _copy_work_to_worksheet(source_job, new_job):
        """Outcome B: map execution Tasks/Materials into a fresh draft worksheet
        as PlanTasks/PlanMaterials. PlanTask requires a non-null est_qty, so fall
        back to actual_qty then 0.00 when the source Task has none. (PlanTask has
        no hierarchy, so subtask nesting is flattened; sort_order is preserved.)"""
        from decimal import Decimal
        from apps.estimates.models import EstWorksheet
        from apps.jobs.models import Task, PlanTask
        from apps.inventory.models import Material, PlanMaterial

        ws = EstWorksheet.objects.create(job=new_job)
        task_map = {}  # source task_id -> new PlanTask
        for task in Task.objects.filter(job=source_job).order_by('sort_order', 'pk'):
            if task.est_qty is not None:
                est_qty = task.est_qty
            elif task.actual_qty is not None:
                est_qty = task.actual_qty
            else:
                est_qty = Decimal('0.00')
            plan_task = PlanTask.objects.create(
                est_worksheet=ws,
                **{**task.copy_fields(), 'est_qty': est_qty},
            )
            task_map[task.pk] = plan_task
        for material in Material.objects.filter(job=source_job).order_by('pk'):
            PlanMaterial.objects.create(
                est_worksheet=ws,
                plan_task=task_map.get(material.task_id),
                **material.copy_fields(),
            )
        return ws


class TaskService:
    """Service class for Task creation workflows."""

    @staticmethod
    def create_from_template(template, job, assignee=None, est_qty=None):
        """
        Create Task from TaskTemplate. Writes billing fields directly on Task.
        """
        from apps.core.services import SchemeSupersededError

        _assert_job_not_on_hold(job, 'add a task to this job')
        if not template.is_active:
            raise ValidationError(f"Template {template.template_name} is not active.")
        if template.rate_scheme_id and template.rate_scheme.replaced_by_id is not None:
            raise SchemeSupersededError(
                f'Template "{template.template_name}" references a superseded RateScheme.'
            )
        if not template.rate_scheme_id:
            raise ValidationError(
                f'Template "{template.template_name}" has no rate_scheme.'
            )
        with transaction.atomic():
            task = Task.objects.create(
                job=job,
                name=template.template_name,
                assignee=assignee,
                rate_scheme=template.rate_scheme,
                active_modifiers=copy_active_modifiers(template.default_active_modifiers),
                est_qty=est_qty if est_qty is not None else template.default_billable_qty,
            )
        return task

    @staticmethod
    def create_direct(job, name, rate_scheme_id=None, active_modifiers=None,
                      est_qty=None, est_worker_time=None, actual_qty=None,
                      allow_superseded_scheme=False, **task_fields):
        """Create Task directly. Requires rate_scheme_id.

        ``allow_superseded_scheme`` bypasses the superseded-scheme rejection.
        The only intended caller is the worksheet→job copy/carry-over core,
        which must clone a worksheet faithfully even when its rate scheme has
        since been superseded.
        """
        _assert_job_not_on_hold(job, 'add a task to this job')
        if not rate_scheme_id:
            raise ValidationError({'rate_scheme': 'Required.'})
        scheme = RateScheme.objects.get(pk=rate_scheme_id)
        if scheme.replaced_by_id is not None and not allow_superseded_scheme:
            raise ValidationError(
                {'rate_scheme': 'Selected RateScheme is superseded.'}
            )
        if scheme.algorithm == RateScheme.PERCENTAGE:
            raise ValidationError(
                {'rate_scheme': 'Percentage services are document adjustments and cannot bill a task.'}
            )
        with transaction.atomic():
            task = Task.objects.create(
                job=job, name=name,
                rate_scheme=scheme,
                active_modifiers=copy_active_modifiers(active_modifiers),
                est_qty=est_qty,
                est_worker_time=est_worker_time,
                actual_qty=actual_qty,
                **task_fields,
            )
        return task

    @staticmethod
    def update_task(pk, **kwargs):
        """Update an existing Task by PK."""
        try:
            task = Task.objects.get(pk=pk)
        except Task.DoesNotExist:
            raise NotFoundError(f'Task {pk} not found')
        _assert_job_not_on_hold(task.job, 'edit this task')
        # A complete task is terminal and frozen: its work and billing inputs are
        # settled. sort_order is cosmetic (list position) and stays editable so a
        # list containing a complete task can still be reordered.
        if task.status == Task.STATUS_COMPLETE and set(kwargs) - {'sort_order'}:
            raise ValidationError(
                'Cannot edit a complete task. Its work and billing are settled; '
                'corrections belong on the invoice.'
            )
        for field, value in kwargs.items():
            setattr(task, field, value)
        task.full_clean()
        task.save()
        return task

    @staticmethod
    def delete_task(task_pk):
        """Delete a task if allowed.

        Rules:
        - In-progress and complete tasks cannot be deleted (cancel instead).
        - Tasks with bleps (time entries) cannot be deleted (cancel instead).
        """
        try:
            task = Task.objects.get(pk=task_pk)
        except Task.DoesNotExist:
            raise NotFoundError(f'Task {task_pk} not found')
        _assert_job_not_on_hold(task.job, 'delete this task')

        non_deletable = (Task.STATUS_IN_PROGRESS, Task.STATUS_COMPLETE)
        if task.status in non_deletable:
            raise ValidationError(
                f"Cannot delete a {task.status} task. Cancel it instead."
            )
        if Blep.objects.filter(task=task).exists():
            raise ValidationError(
                "Cannot delete a task that has time entries. Cancel it instead."
            )

        task.delete()

    @staticmethod
    def reorder_tasks(task_id, direction):
        """Reorder a task within its container — delegates to BundlingService."""
        from apps.core.services import BundlingService

        try:
            task = Task.objects.get(pk=task_id)
        except Task.DoesNotExist:
            raise NotFoundError(f'Task {task_id} not found')
        _assert_job_not_on_hold(task.job, 'reorder tasks on this job')

        items_qs = Task.objects.filter(job=task.job)

        BundlingService.reorder_container_items(
            items_qs, 'task', task_id, direction,
        )
        task.refresh_from_db()
        return task

    @staticmethod
    def assign(task, assignee_id, worker_queue=None, est_worker_time=None):
        """Assign (or unassign) a task to a worker.

        Assigned work has to be schedulable, so a task being given an
        assignee must carry an estimated worker time. When it has none and
        the caller did not supply one, raise `TaskWorkerTimeRequired` up
        front so the endpoint can answer with a prompt signal rather than a
        generic validation error. The save still runs `Task.clean()`, which
        is the actual enforcer of the invariant. Unassigning (`assignee_id`
        falsy) has no such requirement.
        """
        _assert_job_not_on_hold(task.job, "change this task's assignment")
        if assignee_id and est_worker_time is None and not task.est_worker_time:
            raise TaskWorkerTimeRequired()
        task.assignee_id = assignee_id or None
        task.worker_queue = worker_queue
        if est_worker_time is not None:
            task.est_worker_time = est_worker_time
        task.save()
        return task


class TaskLifecycleService:
    """Service for managing Task status transitions and Blep (time tracking) lifecycle."""

    @staticmethod
    def _promote_pending_task(task):
        """A Blep means work has begun on the task: promote a `pending` task
        to `in_progress` and consume its materials. No-op for any other
        status (an `in_progress` task is already there; a backdated Blep
        must not reopen a terminal or blocked task). The promotion is a
        conditional UPDATE on the DB row, so a stale in-memory `task` cannot
        cause a wrong promotion. Mutates `task` in place when it promotes.

        Material consumption is a side effect of the pending -> in_progress
        promotion, not of every clock-in — so it fires here, for both the
        live (start_work) and historical (create_historical) paths."""
        promoted = Task.objects.filter(
            pk=task.pk, status=Task.STATUS_PENDING,
        ).update(status=Task.STATUS_IN_PROGRESS)
        if promoted:
            task.status = Task.STATUS_IN_PROGRESS
            from apps.inventory.services import MaterialService
            for material in task.materials.all():
                MaterialService.consume(material)

    @staticmethod
    def complete_task(task_pk, actual_qty=None):
        """Transition task from pending/in_progress/blocked -> complete.

        `actual_qty` (optional Decimal): the worker-entered quantity. An
        ENTERED_QTY task cannot be completed without a positive quantity —
        either passed here or already on the task. If it's missing, raises
        `TaskActualQtyRequired` so the caller can prompt for it.
        """
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            _assert_job_not_on_hold(task.job, 'complete this task')
            if task.status not in (Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS, Task.STATUS_BLOCKED):
                raise ValidationError(
                    f"Cannot complete task: status is '{task.status}', "
                    f"must be 'pending', 'in_progress', or 'blocked'."
                )
            if actual_qty is not None:
                if actual_qty <= 0:
                    raise ValidationError('Quantity must be greater than 0.')
                task.actual_qty = actual_qty
            if (task.rate_scheme.algorithm == RateScheme.ENTERED_QTY
                    and (task.actual_qty is None or task.actual_qty <= 0)):
                raise TaskActualQtyRequired(task.rate_scheme.unit_label)
            if (task.rate_scheme.algorithm == RateScheme.ELAPSED_TIME
                    and task.rate_scheme.get_actual_qty(task) <= 0):
                raise TaskTimeRequired()
            update_fields = {'status': Task.STATUS_COMPLETE, 'blocked_reason': ''}
            if actual_qty is not None:
                update_fields['actual_qty'] = actual_qty
            BlepService._close_open(task=task)
            Task.objects.filter(pk=task.pk).update(**update_fields)
            task.status = Task.STATUS_COMPLETE
            task.blocked_reason = ''
            JobService.mark_work_started(task.job)
            TaskLifecycleService._check_job_work_complete(task)
            return task

    @staticmethod
    def _check_job_work_complete(task):
        """Auto-advance Job to work_complete if all its tasks are terminal.

        Fires when the Job is currently in APPROVED or IN_PROGRESS status.
        When the job is APPROVED, it walks approved → in_progress → work_complete
        so that the state machine is respected.
        """
        job = task.job
        if job.status not in (Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS):
            return
        terminal = {Task.STATUS_COMPLETE, Task.STATUS_CANCELLED}
        all_terminal = not Task.objects.filter(
            job=job
        ).exclude(status__in=terminal).exists()
        if all_terminal:
            try:
                if job.status == Job.STATUS_APPROVED:
                    JobService.update_status(job.pk, Job.STATUS_IN_PROGRESS)
                JobService.update_status(job.pk, Job.STATUS_WORK_COMPLETE)
            except ValidationError:
                pass  # Pending task-less materials block auto-advance; task completion itself succeeds.

    @staticmethod
    def block_task(task_pk, reason=''):
        """Transition task from pending/in_progress -> blocked.
        Returns conflict dict if open Bleps exist."""
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            _assert_job_not_on_hold(task.job, 'block this task')
            if task.status not in (Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS):
                raise ValidationError(
                    f"Cannot block task: status is '{task.status}', "
                    f"must be 'pending' or 'in_progress'."
                )
            open_bleps = Blep.objects.filter(task=task, end_time__isnull=True)
            if open_bleps.exists():
                workers = []
                for b in open_bleps:
                    workers.append({
                        'user_id': b.user_id,
                        'name': b.user.get_full_name() or b.user.username,
                        'blep_id': b.blep_id,
                        'started_at': b.start_time,
                    })
                return {'conflict': 'active_workers', 'workers': workers}
            Task.objects.filter(pk=task.pk).update(
                status=Task.STATUS_BLOCKED, blocked_reason=reason,
            )
            task.status = Task.STATUS_BLOCKED
            task.blocked_reason = reason
            return task

    @staticmethod
    def unblock_task(task_pk):
        """Transition task from blocked -> in_progress."""
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            _assert_job_not_on_hold(task.job, 'unblock this task')
            if task.status != Task.STATUS_BLOCKED:
                raise ValidationError(
                    f"Cannot unblock task: status is '{task.status}', must be 'blocked'."
                )
            Task.objects.filter(pk=task.pk).update(
                status=Task.STATUS_IN_PROGRESS, blocked_reason='',
            )
            task.status = Task.STATUS_IN_PROGRESS
            task.blocked_reason = ''
            return task

    @staticmethod
    def cancel_task(task_pk):
        """Transition task from pending/in_progress/blocked -> cancelled."""
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            _assert_job_not_on_hold(task.job, 'cancel this task')
            allowed = (Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS, Task.STATUS_BLOCKED)
            if task.status not in allowed:
                raise ValidationError(
                    f"Cannot cancel task: status is '{task.status}', "
                    f"must be 'pending', 'in_progress', or 'blocked'."
                )
            BlepService._close_open(task=task)
            Task.objects.filter(pk=task.pk).update(
                status=Task.STATUS_CANCELLED, blocked_reason='',
            )
            task.status = Task.STATUS_CANCELLED
            task.blocked_reason = ''
            TaskLifecycleService._check_job_work_complete(task)
            return task

    @staticmethod
    def _promote_to_front_of_worker_queue(task):
        """Move `task` to position 1 in its assignee's queue, shifting the
        other open tasks down by one. Reflects reality: a task being
        actively worked on is the next thing to think about — not some
        later position in the queue."""
        if task.assignee_id is None:
            return
        others = list(Task.objects.filter(
            assignee_id=task.assignee_id,
        ).exclude(
            pk=task.pk,
        ).exclude(
            status__in=[Task.STATUS_COMPLETE, Task.STATUS_CANCELLED],
        ).order_by('worker_queue', 'pk').values_list('pk', flat=True))
        if task.worker_queue != 1:
            Task.objects.filter(pk=task.pk).update(worker_queue=1)
            task.worker_queue = 1
        for i, other_pk in enumerate(others, start=2):
            Task.objects.filter(pk=other_pk).exclude(worker_queue=i).update(worker_queue=i)

    @staticmethod
    def start_work(task_pk, user, action=None, on_behalf_of=None):
        """Create a Blep on the given task.

        - The blep is attributed to `target` = `on_behalf_of or user`. When
          `on_behalf_of` differs from `user`, the actor (`user`) must hold
          can_manage_time — a manager starting a worker's timer as a
          convenience.
        - If the task is pending, promotes it to in_progress and consumes
          materials (first worker to start the task), assigning the target.
        - If already in_progress, handles multi-worker conflicts via
          `action='join'` or `action='takeover'` (evaluated against workers
          other than the target).
        - Promotes the task to position 1 in the assignee's worker_queue
          so the schedule view stays consistent with reality.
        - Rejects worksheet tasks and terminal statuses.
        """
        target = on_behalf_of or user
        if target != user and not _has_manage_time(user):
            raise BlepPermissionError(
                "Starting work for another user requires can_manage_time."
            )
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            # Post-split: task is always a Task (work-order side); no container check needed.
            _assert_job_allows_blep(
                task.job,
                (Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS),
                'start work',
            )
            if task.status not in (Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS):
                raise ValidationError(
                    f"Cannot start work: task status is '{task.status}', "
                    f"must be 'pending' or 'in_progress'."
                )
            now = timezone.now()

            # Auto-clock-in: a worker starting a live blep must have an open
            # shift. Open one for the target if they have none.
            from apps.core.services import ShiftService
            ShiftService.ensure_open_shift(target, start_time=now)

            if task.status == Task.STATUS_PENDING:
                # First worker on a pending task: promote (which consumes the
                # task's materials) and assign. No conflict possible — nobody
                # has touched it yet.
                BlepService._close_open(user=target, now=now)
                TaskLifecycleService._promote_pending_task(task)
                if not task.assignee_id:
                    Task.objects.filter(pk=task.pk).update(assignee=target)
                    task.assignee = target
                blep = BlepService._create(task, target, start_time=now)
                JobService.mark_work_started(task.job)
                # Promote only when the blepper IS the assignee — a
                # non-assignee is helping and must not reorder the owner's queue.
                if task.assignee_id == target.pk:
                    TaskLifecycleService._promote_to_front_of_worker_queue(task)
                return {'task': task, 'blep': blep}

            # Task is in_progress: check for active workers other than target.
            other_bleps = Blep.objects.filter(
                task=task, end_time__isnull=True
            ).exclude(user=target)
            if other_bleps.exists() and action is None:
                b = other_bleps.first()
                return {
                    'conflict': 'active_worker',
                    'worker': {
                        'user_id': b.user_id,
                        'name': b.user.get_full_name() or b.user.username,
                    },
                    'blep_id': b.blep_id,
                    'started_at': b.start_time,
                    'options': ['join', 'takeover'],
                }
            if action == 'takeover':
                # Resolve the displaced worker(s)' blep(s): a sub-minute one is an
                # accidental start → cancelled (full undo; may revert the task to
                # pending and un-consume materials), a real one → closed. Then start
                # fresh via the normal tested path — if the cancel reverted the task
                # to pending, that path re-promotes/re-consumes/reassigns; otherwise
                # it just adds the blep. No takeover-specific state handling.
                for b in list(other_bleps):
                    BlepService._resolve_open_blep(b, now)
                return TaskLifecycleService.start_work(task_pk, target)
            # Close target's open Blep on ANY task
            BlepService._close_open(user=target, now=now)
            blep = BlepService._create(task, target, start_time=now)
            JobService.mark_work_started(task.job)
            # Promote only when the blepper IS the assignee (see above).
            if task.assignee_id == target.pk:
                TaskLifecycleService._promote_to_front_of_worker_queue(task)
            return {'task': task, 'blep': blep}

    @staticmethod
    def stop_work(task_pk, user, on_behalf_of=None):
        """Close the target's open Blep on this task.

        `target` = `on_behalf_of or user`. Stopping another user's timer
        (e.g. a worker who left and forgot to clock out) requires the actor
        (`user`) to hold can_manage_time.
        """
        target = on_behalf_of or user
        if target != user and not _has_manage_time(user):
            raise BlepPermissionError(
                "Stopping another user's timer requires can_manage_time."
            )
        with transaction.atomic():
            task = Task.objects.get(pk=task_pk)
            closed = BlepService._close_open(user=target, task=task)
            if not closed:
                raise ValidationError(
                    "No open time entry found for this user on this task."
                )

    @staticmethod
    def cancel_work(task_pk, user):
        """Cancel the user's open blep on this task — the under-the-minimum
        'oops, didn't mean to start that' path.

        Deletes the blep. When that blep was the *first/only* activity on the
        task (the sole reason it is in_progress), also undoes exactly what the
        Start set in motion: reverts the task to pending and un-consumes its
        materials. Job status and assignment are deliberately left untouched
        (see the spec). A 'join' on an already-active task, or a task with
        prior sessions, only loses the blep.

        Only allowed while the session is under `blep_minimum_minutes`; over
        that the caller should Stop instead (enforced defensively here).
        """
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            blep = (
                Blep.objects
                .filter(task=task, user=user, end_time__isnull=True)
                .order_by('-start_time')
                .first()
            )
            if blep is None:
                raise ValidationError(
                    "No open time entry to cancel for this user on this task."
                )
            if not BlepService._under_minimum(blep, timezone.now()):
                raise ValidationError(
                    "Session is too long to cancel; stop it instead."
                )
            BlepService._cancel_blep(blep)


# ═══════════════════════════════════════════════════════════════════
# BoardService (formerly apps.jobs.services.board_service)
# ═══════════════════════════════════════════════════════════════════

class BoardService:
    """Computes board data including sub-statuses for jobs."""

    ACCENT_COLORS = [
        '#f97066', '#f59e0b', '#14b8a6', '#8b5cf6',
        '#38bdf8', '#fb7185', '#84cc16', '#f97316',
    ]

    @staticmethod
    def get_board_data():
        """Assemble all data for the job board view."""
        from apps.jobs.models import Job, Task
        from django.contrib.auth import get_user_model
        User = get_user_model()

        retention_days = 14
        try:
            config = Configuration.objects.get(key='board_closed_retention_days')
            retention_days = int(config.value)
        except (Configuration.DoesNotExist, ValueError):
            pass

        cutoff = timezone.now() - timedelta(days=retention_days)

        # Pipeline: draft + submitted + approved (estimate accepted, awaiting prep)
        #           + on_hold (reverted-to-planning / paused)
        pipeline_jobs = Job.objects.filter(
            status__in=['draft', 'submitted', 'approved', 'on_hold']
        ).select_related('contact', 'project_manager').order_by('due_date')
        pipeline = [BoardService._serialize_job(job) for job in pipeline_jobs]

        # In Progress (board column key kept as 'approved' for URL stability)
        approved_jobs = Job.objects.filter(
            status='in_progress'
        ).select_related('contact', 'project_manager').order_by('due_date')
        approved_list = []
        for i, job in enumerate(approved_jobs):
            job_data = BoardService._serialize_job(job)
            job_data['accent_color'] = job.accent_color or BoardService.ACCENT_COLORS[
                i % len(BoardService.ACCENT_COLORS)
            ]
            approved_list.append(job_data)

        # Build job_id -> accent_color map for tasks
        color_map = {j['job_id']: j['accent_color'] for j in approved_list}

        # Get all active tasks on approved jobs
        approved_job_ids = [j['job_id'] for j in approved_list]
        tasks = Task.objects.filter(
            job_id__in=approved_job_ids,
        ).exclude(
            status__in=[Task.STATUS_COMPLETE, Task.STATUS_CANCELLED]
        ).select_related(
            'job', 'assignee'
        ).prefetch_related('blep_set').order_by('worker_queue', 'pk')

        # Group by assignee
        worker_map = {}
        unassigned = []
        for task in tasks:
            task_data = BoardService._serialize_task(task, color_map)
            if task.assignee_id:
                if task.assignee_id not in worker_map:
                    worker_map[task.assignee_id] = {
                        'user': BoardService._serialize_user(task.assignee),
                        'tasks': [],
                    }
                worker_map[task.assignee_id]['tasks'].append(task_data)
            else:
                unassigned.append(task_data)

        # Sort unassigned by job due_date
        unassigned.sort(key=lambda t: t.get('job_due_date') or '9999-12-31')

        # Closed: terminal states within retention
        closed_jobs = Job.objects.filter(
            status__in=['completed', 'rejected', 'cancelled'],
            completed_date__gte=cutoff,
        ).select_related('contact', 'project_manager').order_by('-completed_date')
        closed = [BoardService._serialize_closed_job(job) for job in closed_jobs]

        # Available workers: active users not already shown in worker columns
        existing_worker_ids = set(worker_map.keys())
        available_users = User.objects.filter(
            is_active=True
        ).exclude(pk__in=existing_worker_ids).order_by('first_name', 'last_name')
        available_workers = [BoardService._serialize_user(u) for u in available_users]

        return {
            'pipeline': pipeline,
            'approved': {
                'jobs': approved_list,
                'workers': list(worker_map.values()),
                'unassigned': unassigned,
                'available_workers': available_workers,
            },
            'closed': closed,
        }

    @staticmethod
    def get_pipeline_data():
        """Return pipeline jobs (draft + submitted + approved + on_hold) with worksheet/estimate info."""
        from apps.jobs.models import Job
        pipeline_jobs = Job.objects.filter(
            status__in=['draft', 'submitted', 'approved', 'on_hold']
        ).select_related('contact', 'project_manager').order_by('due_date')
        return {
            'jobs': [BoardService._serialize_pipeline_job(job) for job in pipeline_jobs],
        }

    @staticmethod
    def in_progress_column_jobs():
        """Job instances in the board's In Progress column, in display order:
        `in_progress` jobs ordered by `due_date`, minus any whose sub-status
        routes them to the Unpaid column.

        This is the single definition of "the In Progress column job set",
        shared by the board column (`get_approved_data`) and the schedule chip
        strip (`ScheduleService.get_schedule`) so the two never drift. No
        `status=in_progress` job currently lands in `UNPAID_SUB_STATUSES`
        (those arise on `work_complete`), so the exclusion is a structural
        guard rather than a live filter. `select_related` covers the related
        fields both callers serialize.
        """
        from apps.jobs.models import Job
        jobs = Job.objects.filter(
            status=Job.STATUS_IN_PROGRESS,
        ).select_related('contact', 'project_manager').order_by('due_date')
        return [
            job for job in jobs
            if BoardService.compute_sub_status(job)
            not in BoardService.UNPAID_SUB_STATUSES
        ]

    @staticmethod
    def get_approved_data():
        """Return in_progress jobs where work is still active (not unpaid).

        Method name kept for URL/view stability. Conceptually this is now the
        "In Progress" column — jobs that have been released to the floor.
        Follow-up: rename to get_in_progress_data.
        """
        from apps.jobs.models import Job, Task
        from django.contrib.auth import get_user_model
        User = get_user_model()

        approved_jobs = BoardService.in_progress_column_jobs()

        approved_list = []
        for i, job in enumerate(approved_jobs):
            job_data = BoardService._serialize_job(job)
            job_data['accent_color'] = job.accent_color or BoardService.ACCENT_COLORS[
                i % len(BoardService.ACCENT_COLORS)
            ]
            approved_list.append(job_data)

        color_map = {j['job_id']: j['accent_color'] for j in approved_list}

        approved_job_ids = [j['job_id'] for j in approved_list]

        # Task counts per job (for progress bar in popup)
        from django.db.models import Count, Q as DjQ
        stats = Task.objects.filter(
            job_id__in=approved_job_ids
        ).exclude(status=Task.STATUS_CANCELLED).values(
            'job_id'
        ).annotate(
            total=Count('task_id'),
            completed=Count('task_id', filter=DjQ(status=Task.STATUS_COMPLETE)),
        )
        stats_by_job = {s['job_id']: s for s in stats}
        for j in approved_list:
            s = stats_by_job.get(j['job_id'], {'total': 0, 'completed': 0})
            j['task_total'] = s['total']
            j['task_completed'] = s['completed']

        tasks = Task.objects.filter(
            job_id__in=approved_job_ids,
        ).exclude(
            status__in=[Task.STATUS_COMPLETE, Task.STATUS_CANCELLED]
        ).select_related(
            'job', 'assignee'
        ).prefetch_related('blep_set').order_by('worker_queue', 'pk')

        worker_map = {}
        unassigned = []
        for task in tasks:
            task_data = BoardService._serialize_task(task, color_map)
            if task.assignee_id:
                if task.assignee_id not in worker_map:
                    worker_map[task.assignee_id] = {
                        'user': BoardService._serialize_user(task.assignee),
                        'tasks': [],
                    }
                worker_map[task.assignee_id]['tasks'].append(task_data)
            else:
                unassigned.append(task_data)

        unassigned.sort(key=lambda t: t.get('job_due_date') or '9999-12-31')

        existing_worker_ids = set(worker_map.keys())
        available_users = User.objects.filter(
            is_active=True
        ).exclude(pk__in=existing_worker_ids).order_by('first_name', 'last_name')
        available_workers = [BoardService._serialize_user(u) for u in available_users]

        return {
            'jobs': approved_list,
            'workers': list(worker_map.values()),
            'unassigned': unassigned,
            'available_workers': available_workers,
        }

    # Invoice statuses that represent a settled/voided receivable — excluded from
    # the "outstanding" predicate used to populate the Unpaid board lane.
    INVOICE_SETTLED_STATUSES = ['cancelled', 'superseded', 'paid']

    @staticmethod
    def get_unpaid_data():
        """Return jobs in the Unpaid lane: a UNION of two predicates.

        (a) All work_complete jobs — these are "work done, awaiting first invoice"
            (sub_status needs-invoice) as well as those already invoiced.
        (b) Any-status jobs with at least one outstanding (non-settled) invoice —
            so that a billable-cancelled job's receivable stays visible and is
            not lost after cancellation.

        The two predicates overlap for work_complete jobs that also carry an
        outstanding invoice; .distinct() ensures each job appears only once.
        """
        from apps.jobs.models import Job
        unpaid_jobs = Job.objects.filter(
            Q(status=Job.STATUS_WORK_COMPLETE) |
            Q(invoice__status__in=['draft', 'open', 'partly-paid', 'defaulted'])
        ).distinct().select_related('contact', 'project_manager').order_by('due_date')

        unpaid_list = [
            BoardService._serialize_unpaid_job(job) for job in unpaid_jobs
        ]
        return {'jobs': unpaid_list}

    @staticmethod
    def get_closed_data():
        """Return terminal-status jobs within retention window."""
        from apps.jobs.models import Job

        retention_days = 14
        try:
            config = Configuration.objects.get(key='board_closed_retention_days')
            retention_days = int(config.value)
        except (Configuration.DoesNotExist, ValueError):
            pass

        cutoff = timezone.now() - timedelta(days=retention_days)

        closed_jobs = Job.objects.filter(
            status__in=['completed', 'rejected', 'cancelled'],
            completed_date__gte=cutoff,
        ).select_related('contact', 'project_manager').order_by('-completed_date')
        return {'jobs': [BoardService._serialize_closed_job(job) for job in closed_jobs]}

    @staticmethod
    def _serialize_job(job):
        return {
            'job_id': job.job_id,
            'job_number': job.job_number,
            'name': job.name,
            'status': job.status,
            'sub_status': BoardService.compute_sub_status(job),
            'contact_id': job.contact_id,
            'contact_name': str(job.contact) if job.contact else None,
            'project_manager_name': (
                (job.project_manager.get_full_name() or job.project_manager.username)
                if job.project_manager_id else None
            ),
            'due_date': job.due_date.isoformat() if job.due_date else None,
            'completed_date': job.completed_date.isoformat() if job.completed_date else None,
        }

    @staticmethod
    def _serialize_closed_job(job):
        """Serialize a closed job with dates and profitability."""
        data = BoardService._serialize_job(job)
        data['start_date'] = job.start_date.isoformat() if job.start_date else None
        profitability = BoardService._compute_profitability(job)
        data.update(profitability)
        return data

    @staticmethod
    def _serialize_pipeline_job(job):
        """Serialize a pipeline job with worksheet and estimate info."""
        from apps.estimates.models import EstimateLineItem
        data = BoardService._serialize_job(job)

        worksheets = []
        for ws in job.estworksheet_set.order_by('-pk'):
            worksheets.append({
                'est_worksheet_id': ws.est_worksheet_id,
                'created_date': ws.created_date.isoformat() if ws.created_date else None,
            })
        data['worksheets'] = worksheets

        from apps.estimates.models import ChangeOrder
        estimates = []
        for est in job.estimate_set.order_by('-pk'):
            total = EstimateLineItem.objects.filter(estimate=est).aggregate(
                total=models.Sum(models.F('qty') * models.F('price'))
            )['total'] or Decimal('0.00')
            # Derived "amended" flag: accepted estimate with ≥1 accepted CO.
            # The stored status stays accepted; the UI renders "amended".
            is_amended = (
                est.status == Estimate.STATUS_ACCEPTED
                and ChangeOrder.objects.filter(
                    estimate=est, status=ChangeOrder.STATUS_ACCEPTED,
                ).exists()
            )
            estimates.append({
                'estimate_id': est.estimate_id,
                'estimate_number': est.estimate_number,
                'status': est.status,
                'is_amended': is_amended,
                'created_date': est.created_date.isoformat() if est.created_date else None,
                'total': total,
            })
        data['estimates'] = estimates
        data['is_revision'] = BoardService.is_revision(job)
        return data

    @staticmethod
    def _compute_profitability(job):
        """Billed/spent/profit for a board card.

        Thin adapter over the single source of truth in apps.jobs.financials so
        the board and the job-detail header can never drift. The card's "billed"
        is the shared "invoiced" figure (drafts/cancelled/superseded excluded);
        spent includes the average_labor_cost-based labor term; profit is
        invoiced − spent. Values are already quantized to cents.
        """
        from apps.jobs.financials import compute_job_financials

        fin = compute_job_financials(job)
        return {
            'billed': fin['invoiced'],
            'spent': fin['spent'],
            'profit': fin['profit'],
        }

    @staticmethod
    def _serialize_unpaid_job(job):
        """Serialize an unpaid job with invoice details and profitability."""
        data = BoardService._serialize_job(job)
        invoices = []
        for inv in job.invoice_set.exclude(status__in=['cancelled', 'superseded']).order_by('created_date'):
            total = inv.invoicelineitem_set.aggregate(
                total=models.Sum(models.F('qty') * models.F('price'))
            )['total'] or Decimal('0.00')
            invoices.append({
                'invoice_id': inv.invoice_id,
                'invoice_number': inv.invoice_number,
                'status': inv.status,
                'total': total,
                'created_date': inv.created_date.isoformat() if inv.created_date else None,
                'sent_date': inv.sent_date.isoformat() if inv.sent_date else None,
                'closed_date': inv.closed_date.isoformat() if inv.closed_date else None,
                'amount_paid': inv.qbo_amount_paid,
            })
        data['invoices'] = invoices
        profitability = BoardService._compute_profitability(job)
        data.update(profitability)
        return data

    @staticmethod
    def _serialize_task(task, color_map):
        job = task.job
        bleps = list(task.blep_set.all())
        open_user_ids = {b.user_id for b in bleps if b.end_time is None}
        return {
            'task_id': task.task_id,
            'name': task.name,
            'status': task.status,
            'job_id': job.job_id,
            'job_name': job.name,
            'job_due_date': job.due_date.isoformat() if job.due_date else None,
            'accent_color': color_map.get(job.job_id, '#94a3b8'),
            'blocked_reason': task.blocked_reason,
            'assignee_id': task.assignee_id,
            'worker_queue': task.worker_queue,
            'est_worker_time': (
                str(task.est_worker_time) if task.est_worker_time else None
            ),
            'has_active_blep': bool(open_user_ids),
            'active_worker_count': len(open_user_ids),
            'has_bleps': bool(bleps),
        }

    @staticmethod
    def _serialize_user(user):
        first = user.first_name or ''
        last = user.last_name or ''
        initials = (first[:1] + last[:1]).upper() or user.username[:2].upper()
        short_name = f"{first} {last[:1]}." if last else first or user.username
        return {
            'id': user.pk,
            'username': user.username,
            'initials': initials,
            'name': short_name,
        }

    @staticmethod
    def is_revision(job):
        """True when the job's live (non-superseded) estimate is a draft revision
        (version > 1) — a re-quote in progress, e.g. after a customer change
        request. Drives the 'Revision' board badge."""
        from apps.estimates.models import Estimate
        live = (job.estimate_set
                .exclude(status=Estimate.STATUS_SUPERSEDED)
                .order_by('-version', '-pk')
                .first())
        return bool(live and live.status == Estimate.STATUS_DRAFT and live.version > 1)

    @staticmethod
    def compute_sub_status(job):
        """Derive the sub-status of a job based on related object states."""
        if job.status == Job.STATUS_ON_HOLD:
            return 'on-hold'
        if job.status in ('draft', 'submitted'):
            return BoardService._pipeline_sub_status(job)
        elif job.status == Job.STATUS_APPROVED:
            # approved = estimate accepted, awaiting prep / release to floor
            return 'awaiting-prep'
        elif job.status == Job.STATUS_IN_PROGRESS:
            return BoardService._in_progress_sub_status(job)
        elif job.status == Job.STATUS_WORK_COMPLETE:
            return BoardService._work_complete_sub_status(job)
        return None

    @staticmethod
    def _pipeline_sub_status(job):
        """Sub-status for Draft/Submitted jobs."""
        estimates = job.estimate_set.all()

        if estimates.filter(status='open').exists():
            return 'awaiting-response'

        if estimates.filter(status='draft').exists():
            return 'estimating'

        if not estimates.exists() and job.estworksheet_set.exists():
            return 'estimating'

        return 'needs-scoping'

    UNPAID_SUB_STATUSES = {'invoice-sent', 'invoice-prepped', 'needs-invoice'}

    @staticmethod
    def _in_progress_sub_status(job):
        """Sub-status for In Progress jobs (status='in_progress').

        Tasks live directly on the job. Jobs with all tasks terminal are
        auto-advanced to work_complete, so invoice-related sub-statuses
        live on _work_complete_sub_status.

        Renamed from _approved_sub_status — follow-up: remove the old name.
        """
        all_tasks = job.tasks.all()
        if not all_tasks.exists():
            return 'needs-tasks'

        tasks = all_tasks.exclude(
            status__in=[Task.STATUS_COMPLETE, Task.STATUS_CANCELLED]
        )
        if tasks.filter(status=Task.STATUS_BLOCKED).exists():
            return 'blocked'
        if tasks.filter(status=Task.STATUS_IN_PROGRESS).exists():
            return 'in-progress'

        return 'work-ready'

    @staticmethod
    def _work_complete_sub_status(job):
        """Sub-status for work_complete jobs: invoice lifecycle."""
        from apps.invoicing.models import Invoice
        invoices = job.invoice_set.exclude(
            status__in=[Invoice.STATUS_CANCELLED, Invoice.STATUS_SUPERSEDED]
        )
        if invoices.filter(status=Invoice.STATUS_OPEN).exists():
            return 'invoice-sent'
        if invoices.filter(status=Invoice.STATUS_DRAFT).exists():
            return 'invoice-prepped'
        return 'needs-invoice'

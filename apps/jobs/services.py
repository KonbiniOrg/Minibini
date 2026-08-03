"""
Service classes for handling complex creation workflows between Jobs and Tasks.
"""

from datetime import timedelta
from apps.core.history import record_history
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q, Prefetch
from django.utils import timezone
from django.utils.dateparse import parse_duration

from apps.jobs.models import Job, Task, Blep, Fee, RateScheme
from apps.estimates.models import (
    Estimate, WorkTemplate, ServiceItem,
    EstimateLineItem,
)
from apps.inventory.models import InventoryItem
from apps.core.models import Configuration
from apps.core.services import NumberGenerationService, NotFoundError, SELF_EDIT_WINDOW_HOURS
from apps.core.timeutils import timedelta_to_hours
from apps.core.units import HOUR_UNIT


def _coerce_duration(value):
    """DurationField inputs arrive as timedelta (DRF) or ISO/HH:MM:SS string
    (internal callers). Return a timedelta or None — any other type (e.g. a
    raw JSON int from a direct POST) is not a duration we can coerce, so it
    passes through as None rather than reaching timedelta_to_hours() and
    raising AttributeError."""
    if isinstance(value, timedelta):
        return value
    if isinstance(value, str):
        return parse_duration(value)
    return None


def hours_pair_fill(unit_label, est_qty, est_worker_time):
    """For hour-denominated units, est_qty (billable hours) and
    est_worker_time (schedulable duration) are one number in two encodings.
    When exactly one is provided, derive the other. Convenience, not an
    invariant — both-provided passes through untouched.

    Takes a bare ``unit_label`` string (not a RateScheme) — task-owned
    money (Phase 1) means the unit of record lives on the Task itself, not
    on a scheme lookup."""
    if unit_label != HOUR_UNIT:
        return est_qty, est_worker_time
    if est_qty is not None and not est_worker_time:
        try:
            return est_qty, timedelta(hours=float(est_qty))
        except (TypeError, ValueError, OverflowError, InvalidOperation):
            # Unconvertible/out-of-range input passes through unchanged so
            # Task.full_clean() renders the contract-shaped 400 — this
            # helper is a convenience, not a validator.
            return est_qty, est_worker_time
    if est_worker_time and est_qty is None:
        td = _coerce_duration(est_worker_time)
        if td is not None:
            return timedelta_to_hours(td).quantize(Decimal('0.01')), est_worker_time
    return est_qty, est_worker_time


# ═══════════════════════════════════════════════════════════════════
# BlepService (formerly apps.jobs.services.blep_service)
# ═══════════════════════════════════════════════════════════════════

class TaskPermissionError(Exception):
    """The acting user may not perform this task operation (→ HTTP 403)."""
    pass


class BlepPermissionError(Exception):
    """Raised when a caller is not permitted to perform a blep operation."""
    pass


class TaskActualQtyRequired(Exception):
    """Raised when completing an ENTERED_QTY task without an explicit
    `add_qty` — completion always settles up through the prompt, even when
    a running total is already on record. Carries the rate scheme's unit
    label and the accumulated total so the caller can render the prompt."""
    def __init__(self, unit_label='', current_qty=None):
        self.unit_label = unit_label
        self.current_qty = current_qty
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
    """Reject Blep creation when the Task's Job is held or in a status where
    work should not be recorded against it. The hold check is explicit — the
    allow-lists describe pipeline position, and a held job keeps its true
    status underneath, so omission can't cover it."""
    if job.on_hold:
        raise ValidationError(f"Cannot {action}: the job is on hold.")
    if job.status not in allowed_statuses:
        labels = ', '.join(f"'{s}'" for s in allowed_statuses)
        raise ValidationError(
            f"Cannot {action}: job status is '{job.status}', "
            f"must be one of {labels}."
        )


def _assert_job_not_on_hold(job, action):
    """Reject task/material mutations while the job is paused (on_hold flag).

    Resolve the open change order (accept/reject/discard) or take the job
    off hold before making changes.
    """
    if job.on_hold:
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
            # Deliberate update(): in_progress -> pending is NOT a legal
            # forward transition (and stays out of VALID_TRANSITIONS — a
            # save() would raise). It exists only as the undo of an
            # accidental start. The explicit action row below keeps the
            # history trail truthful — the promotion is an audit diff, so
            # its undo must be visible too.
            reverted = Task.objects.filter(
                pk=task.pk, status=Task.STATUS_IN_PROGRESS,
            ).update(status=Task.STATUS_PENDING)
            if reverted:
                from apps.core.history import record_action
                record_action(
                    'task', task.pk,
                    'Accidental start cancelled — reverted to pending',
                )
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
            (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED,
             Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS,
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
            # Lock the task row (like start_work) so the promotion's
            # check-then-save can't race a concurrent historical create.
            task = Task.objects.select_for_update().get(pk=task.pk)
            blep = BlepService._create(
                task, target_user, start_time=start_time, end_time=end_time,
            )
            # Mirror start_work: the first worker whose blep promotes the
            # task becomes its assignee. A blep on an already-started task
            # is "helping" and doesn't claim it.
            promoted = TaskLifecycleService._promote_pending_task(
                task, assignee_if_unassigned=target_user)
            if not promoted and task.status == Task.STATUS_IN_PROGRESS:
                # A hand-added blep on a started task is still work happening:
                # consume arrived stock, refuse while a material is missing.
                # (The promotion above already swept a pending task's list.)
                TaskLifecycleService._consume_pending_materials(task)
            JobService.mark_work_started(task.job)
        return blep

    @staticmethod
    def update(blep, actor, **fields):
        """Update a blep. Only `start_time` and `end_time` are editable here."""
        from apps.invoicing.claims import InvoiceClaimService
        from apps.invoicing.models import InvoiceLineItemSource
        # Billed actuals are frozen for everyone — the same rule `delete`
        # enforces, for the same reason: moving a blep's times under an
        # invoiced task silently changes the basis of a number already
        # charged. Editing is not a lesser act than deleting here.
        # Keyed on INVOICED, not on task-complete: a finished but unbilled
        # task's time stays correctable.
        if InvoiceClaimService.is_invoiced(
                InvoiceLineItemSource.SOURCE_TASK, blep.task_id):
            raise ValidationError(
                "This time entry's task is on an invoice; its actuals are "
                "frozen. Remove the task from the invoice first."
            )
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
        from apps.invoicing.claims import InvoiceClaimService
        from apps.invoicing.models import InvoiceLineItemSource
        # Billed actuals are frozen for everyone: deleting a blep under an
        # invoiced task would silently change the basis of a number already
        # charged. (Estimate claims never block — estimates bill est_qty.)
        if InvoiceClaimService.is_invoiced(
                InvoiceLineItemSource.SOURCE_TASK, blep.task_id):
            raise ValidationError(
                "This time entry's task is on an invoice; its actuals are "
                "frozen. Remove the task from the invoice first."
            )
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
    def update_job(pk, system_transition=False, **kwargs):
        """Base Job update. Applies field changes and dispatches
        status-transition side effects (loose-materials gate, earmark
        release). update_status() is a thin wrapper over this — every Job
        status change should flow through here.

        `system_transition=True` marks a status walk driven by the system
        (estimate acceptance, duplicate-as-approved) rather than a user's
        direct status edit; only those may enter `approved` on a job that
        has estimates."""
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {pk} not found')
        old_status = job.status
        for field, value in kwargs.items():
            setattr(job, field, value)
        status_changed = job.status != old_status

        # Approval flows from estimate acceptance: a direct edit to approved
        # would bypass acceptance crystallization and leave the estimate's
        # customer-response clock ticking. Only a job with NO estimates at all
        # (any status counts — dead ones too) can be hand-approved.
        if (status_changed and job.status == Job.STATUS_APPROVED
                and not system_transition
                and job.estimate_set.exists()):
            raise ValidationError(
                'This job has an estimate — approve it by accepting the '
                'estimate (there or via the customer link), not by setting '
                'the job status directly.'
            )

        # A held job is parked: no status changes except cancellation, which
        # (like release) requires any live change order to be resolved first
        # and drops the flag as part of the transition.
        if status_changed and job.on_hold:
            if job.status != Job.STATUS_CANCELLED:
                raise ValidationError(
                    'Job is on hold — release it before changing its status.'
                )
            JobService._assert_no_live_change_order(job)
            job.on_hold = False

        if status_changed and job.status == Job.STATUS_CANCELLED:
            if Blep.objects.filter(task__job=job, end_time__isnull=True).exists():
                raise ValidationError(
                    'Cannot cancel the job while a worker has an open time entry — '
                    'have them stop first.'
                )

        if status_changed and job.status == Job.STATUS_WORK_COMPLETE:
            # work_complete means every task is terminal and every material
            # resolved — enforced here so EVERY path into the status (the
            # pill PATCH, the work-complete endpoint, internal walks) hits
            # the same gate. The endpoint pre-checks work_complete_blockers
            # to answer with a structured list instead of this error.
            blockers = JobService.work_complete_blockers(job)
            if blockers:
                parts = []
                if blockers['tasks']:
                    parts.append('unfinished tasks: ' + ', '.join(
                        t['name'] for t in blockers['tasks']))
                if blockers['materials']:
                    parts.append('pending materials: ' + ', '.join(
                        m['description'] or str(m['material_id'])
                        for m in blockers['materials']))
                raise ValidationError(
                    'Cannot advance to work_complete: ' + '; '.join(parts)
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
    def work_complete_blockers(job):
        """Everything standing between this job and work_complete (B4).

        Returns None when the job is ready, else
        {'tasks': [{task_id, name, status}...],
         'materials': [{material_id, description, task_id}...]} —
        non-terminal tasks plus PENDING materials (task-attached or loose)
        with quantity still committed. The work-complete endpoint returns
        this shape so the SPA can render the "resolve these first" list;
        update_job enforces the same predicate as a hard gate.
        """
        from apps.inventory.models import Material
        tasks = list(
            Task.objects.filter(job=job)
            .exclude(status__in=[Task.STATUS_COMPLETE, Task.STATUS_CANCELLED])
            .order_by('sort_order', 'pk')
            .values('task_id', 'name', 'status')
        )
        materials = list(
            Material.objects.filter(
                job=job,
                consumption_state=Material.CONSUMPTION_STATE_PENDING,
                quantity__gt=0,
            ).order_by('pk').values('material_id', 'description', 'task_id')
        )
        if not tasks and not materials:
            return None
        return {'tasks': tasks, 'materials': materials}

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
    def update_status(pk, new_status, system_transition=False):
        """Thin wrapper over update_job for a status-only change."""
        return JobService.update_job(pk, status=new_status,
                                     system_transition=system_transition)

    @staticmethod
    def _assert_no_live_change_order(job):
        """A job with a draft or open change order stays parked on hold —
        the CO must be resolved (accepted, rejected, or discarded) first."""
        from apps.estimates.models import ChangeOrder
        if ChangeOrder.objects.filter(
            job=job, status__in=[ChangeOrder.STATUS_DRAFT, ChangeOrder.STATUS_OPEN]
        ).exists():
            raise ValidationError(
                'Resolve the open change order (accept, reject, or discard it) '
                'before taking the job off hold.'
            )

    @staticmethod
    def hold_job(pk, reason):
        """Pause the job: set the on_hold flag. The job keeps its true status
        underneath — holding never moves it through the state machine."""
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {pk} not found')
        if job.on_hold:
            raise ValidationError('Job is already on hold.')
        if job.status not in (Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS):
            raise ValidationError(
                'Only an approved or in-progress job can be put on hold.'
            )
        if not (reason or '').strip():
            raise ValidationError({'reason': ['A hold reason is required.']})
        if Blep.objects.filter(task__job=job, end_time__isnull=True).exists():
            raise ValidationError(
                'Cannot pause the job while a worker has an open time entry — '
                'have them stop first.'
            )
        job.on_hold = True
        job.hold_reason = reason.strip()
        job.save()
        return job

    @staticmethod
    def release_job(pk):
        """Release the hold. Blocked while a draft/open change order exists;
        Job.save() clears hold_reason when the flag drops."""
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            raise NotFoundError(f'Job {pk} not found')
        if not job.on_hold:
            raise ValidationError('Job is not on hold.')
        JobService._assert_no_live_change_order(job)
        job.on_hold = False
        job.save()
        return job

    @staticmethod
    def assert_job_deletable(job):
        """Hard delete is for unworked jobs only (Rule 1 at job scale).

        A job with bleps, invoices, or any sent (non-draft) estimate or change
        order has history the cascade would destroy — bleps wholesale, which
        are absolute records of work that happened. Those jobs are cancelled,
        not deleted; a draft quote that never went anywhere still deletes.
        """
        from apps.estimates.models import ChangeOrder, Estimate
        from apps.invoicing.models import Invoice
        if Blep.objects.filter(task__job=job).exists():
            raise ValidationError(
                'This job has recorded time and cannot be deleted. '
                'Cancel it instead.'
            )
        if Invoice.objects.filter(job=job).exists():
            raise ValidationError(
                'This job has invoices and cannot be deleted. Cancel it instead.'
            )
        if Estimate.objects.filter(job=job).exclude(
                status=Estimate.STATUS_DRAFT).exists():
            raise ValidationError(
                'This job has a sent estimate and cannot be deleted. '
                'Cancel it instead.'
            )
        if ChangeOrder.objects.filter(job=job).exclude(
                status=ChangeOrder.STATUS_DRAFT).exists():
            raise ValidationError(
                'This job has a sent change order and cannot be deleted. '
                'Cancel it instead.'
            )

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
          - No-ops unless the job's WORK is finished: ``work_complete``, or
            ``approved``/``in_progress`` with at least one task and every task
            terminal (the loose-material-stranded case — see below).
          - No-ops if any invoice is still unresolved (not paid/cancelled).
          - No-ops if any deliverable is not yet fully picked up.
          - Releases loose (task-less, pending) materials, records a system
            HistoryEntry for the release, then walks the job to ``completed``.
        """
        from apps.core.models import User
        from apps.deliverables.services import DeliverableService
        from apps.invoicing.models import Invoice

        job.refresh_from_db()

        # Auto-complete requires the WORK to be finished — not merely the
        # money resolved. That means ``work_complete``, or an ``approved``/
        # ``in_progress`` job whose tasks exist and are ALL terminal: the one
        # legitimate way such a job is stranded short of ``work_complete`` is
        # a loose pending material blocking the transition, and this
        # unattended path releases exactly those below. Everything else is a
        # no-op: an ``in_progress`` job with open tasks (a follow-up to send
        # plans/photos, a post-job meeting), a deposit invoice paid before
        # any work starts (task-less job), and ``draft``/``submitted``/
        # ``on_hold`` jobs, which have no finished work at all. (This also
        # avoids forcing a transition the state machine forbids, e.g.
        # on_hold -> completed.)
        if job.status not in (Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS,
                              Job.STATUS_WORK_COMPLETE):
            return
        if job.status != Job.STATUS_WORK_COMPLETE:
            terminal = (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED)
            tasks = Task.objects.filter(job=job)
            if not tasks.exists() or tasks.exclude(status__in=terminal).exists():
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

        # Walk any intermediate statuses (the work-finished guard above means
        # only the loose-material-stranded approved/in_progress cases arrive
        # here short of work_complete; their materials were just released).
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
    def mark_work_reopened(job):
        """Pull a WORK_COMPLETE Job back to IN_PROGRESS when a new incomplete
        Task lands on it — work_complete means every task is terminal, and a
        fresh open task contradicts that. No-op for any other status."""
        if job.status == Job.STATUS_WORK_COMPLETE:
            JobService.update_status(job.pk, Job.STATUS_IN_PROGRESS)
            job.refresh_from_db()

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
                JobService._advance_to_approved(new_job, source_job)
                # Earmark AFTER the status walk: create_earmarks_for_job
                # no-ops on pre-approval jobs (the committed-jobs-only
                # invariant), and the new job is draft until just above.
                from apps.inventory.services import InventoryService
                new_job.refresh_from_db()
                InventoryService.create_earmarks_for_job(new_job)
            else:
                # Estimate path: copy work onto the new (draft) job. Estimates
                # project from the Job's atoms, so no worksheet is created and the
                # job is left in DRAFT for re-estimation.
                JobService._copy_work_to_job(source_job, new_job)
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
        # Materials (task-attached follow their remapped task; task-less stay
        # loose). Released materials are the SOURCE job's "planned it, didn't
        # use it" history — copying them would mint empty qty-0 rows.
        for material in Material.objects.filter(job=source_job).exclude(
            consumption_state=Material.CONSUMPTION_STATE_RELEASED,
        ).order_by('pk'):
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
        JobService.update_status(new_job.pk, Job.STATUS_SUBMITTED,
                                 system_transition=True)
        record_history(
            entry_type='action', object_type='job', object_id=new_job.pk,
            user=system_user,
            changes={'status': {'old': Job.STATUS_DRAFT, 'new': Job.STATUS_SUBMITTED},
                     '_action': action_desc},
        )
        JobService.update_status(new_job.pk, Job.STATUS_APPROVED,
                                 system_transition=True)
        record_history(
            entry_type='action', object_type='job', object_id=new_job.pk,
            user=system_user,
            changes={'status': {'old': Job.STATUS_SUBMITTED, 'new': Job.STATUS_APPROVED},
                     '_action': action_desc},
        )


class TaskService:
    """Service class for Task creation workflows."""

    @staticmethod
    def create_from_template(template, job, assignee=None, est_qty=None):
        """
        Create Task from ServiceItem. Stamps billing fields from the
        template's RateScheme onto the Task (task-owned money Phase 1) via
        ``Task.stamp_from_scheme`` before first save.
        """
        from apps.jobs.models import SchemeInactiveError

        _assert_job_not_on_hold(job, 'add a task to this job')
        if not template.is_active:
            raise ValidationError(f"Template {template.template_name} is not active.")
        if not template.rate_scheme_id:
            raise ValidationError(
                f'Template "{template.template_name}" has no rate_scheme.'
            )
        scheme = template.rate_scheme
        if not scheme.is_active:
            raise SchemeInactiveError(
                f'Template "{template.template_name}" references an inactive RateScheme.'
            )
        with transaction.atomic():
            task = Task(
                job=job,
                name=template.template_name,
                assignee=assignee,
                service_item=template,
                est_qty=est_qty if est_qty is not None else Decimal('1'),
            )
            task.stamp_from_scheme(scheme, modifier_keys=template.default_active_modifiers)
            task.save()
            JobService.mark_work_reopened(job)
        return task

    @staticmethod
    def create_direct(job, name, rate_scheme_id=None, active_modifiers=None,
                      est_qty=None, est_worker_time=None, actual_qty=None,
                      allow_inactive_scheme=False, parent_task_id=None,
                      **task_fields):
        """Create Task directly. Requires rate_scheme_id — stamps its billing
        fields onto the Task (task-owned money Phase 1) via
        ``Task.stamp_from_scheme`` before first save.

        ``allow_inactive_scheme`` bypasses the inactive-preset rejection.
        The only intended caller is the worksheet→job copy/carry-over core,
        which must clone a worksheet faithfully even when its rate scheme has
        since been retired.

        This is the single creation gate for direct tasks AND subtasks (the
        /api/tasks/{id}/subtasks/ endpoint routes here too) — the on-hold,
        inactive-scheme, depth, and assignee guards can't be skipped by
        picking a different endpoint.
        """
        from apps.jobs.models import SchemeInactiveError

        _assert_job_not_on_hold(job, 'add a task to this job')
        if not rate_scheme_id:
            raise ValidationError({'rate_scheme': 'Required.'})
        scheme = RateScheme.objects.get(pk=rate_scheme_id)
        if not scheme.is_active and not allow_inactive_scheme:
            raise SchemeInactiveError(
                'Selected RateScheme is inactive.'
            )
        if scheme.algorithm == RateScheme.PERCENTAGE:
            raise ValidationError(
                {'rate_scheme': 'Percentage services are document adjustments and cannot bill a task.'}
            )
        if parent_task_id:
            try:
                parent = Task.objects.get(pk=parent_task_id)
            except Task.DoesNotExist:
                raise ValidationError({'parent_task': ['Parent task not found.']})
            if parent.job_id != job.pk:
                raise ValidationError(
                    {'parent_task': ['Parent task belongs to a different job.']})
            if parent.parent_task_id is not None:
                raise ValidationError({'parent_task': [
                    'Subtasks cannot have their own subtasks — '
                    'one level of subtasks only.']})
        est_qty, est_worker_time = hours_pair_fill(scheme.unit_label, est_qty, est_worker_time)
        # A type _coerce_duration can't parse (e.g. a raw JSON int from this
        # endpoint's unserialized POST) would otherwise reach Task.save()'s
        # full_clean() and hit DurationField.to_python(), which only catches
        # ValueError — a non-str/timedelta input raises an uncaught
        # TypeError there (a 500), not the ValidationError (400) the error
        # contract requires. Reject it here instead, where a real
        # ValidationError renders correctly.
        if est_worker_time is not None and not isinstance(est_worker_time, (timedelta, str)):
            raise ValidationError({'est_worker_time': [
                'Must be a duration string (e.g. "01:30:00") or ISO 8601 duration.']})
        # Explicit assignment at create must be schedulable (the invariant
        # lives on the assign gestures, not Task.clean — see the model).
        if task_fields.get('assignee_id') and not est_worker_time:
            raise ValidationError({'est_worker_time': [
                'An assigned task must have an estimated worker time.']})
        with transaction.atomic():
            task = Task(
                job=job, name=name,
                est_qty=est_qty,
                est_worker_time=est_worker_time,
                actual_qty=actual_qty,
                parent_task_id=parent_task_id,
                **task_fields,
            )
            task.stamp_from_scheme(scheme, modifier_keys=active_modifiers)
            task.save()
            if task.status not in (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED):
                JobService.mark_work_reopened(job)
        return task

    @staticmethod
    def update_task(pk, user=None, **kwargs):
        """Update an existing Task by PK.

        Editability matrix (C1): pending is open to any authenticated user;
        in_progress/blocked require the manager atom, the job's PM, or the
        task's ASSIGNEE (checked when `user` is passed — the API always
        passes it; internal callers may omit it); terminal is frozen.
        """
        try:
            task = Task.objects.get(pk=pk)
        except Task.DoesNotExist:
            raise NotFoundError(f'Task {pk} not found')
        _assert_job_not_on_hold(task.job, 'edit this task')
        # A terminal task is frozen: its work and billing inputs are settled.
        # sort_order is cosmetic (list position) and stays editable so a
        # list containing a terminal task can still be reordered.
        if (task.status in (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED)
                and set(kwargs) - {'sort_order'}):
            raise ValidationError(
                f'Cannot edit a {task.status} task. Its work and billing are '
                f'settled; corrections belong on the invoice.'
            )
        if (user is not None
                and task.status in (Task.STATUS_IN_PROGRESS, Task.STATUS_BLOCKED)
                and not JobService.user_can_manage(user, task.job)
                and task.assignee_id != user.pk):
            raise TaskPermissionError(
                'Only a manager, the project manager, or the assignee may '
                'edit a task that is in progress or blocked.'
            )
        # Task-owned money (Phase 1): the unit of record is the task's own
        # unit_label, not a RateScheme lookup — an in-flight unit_label
        # edit (money-permission-gated at the serializer layer) wins over
        # the task's current value for this same-request qty/time sync.
        effective_unit_label = kwargs.get('unit_label', task.unit_label)
        if effective_unit_label == HOUR_UNIT:
            if ('est_qty' in kwargs and 'est_worker_time' not in kwargs
                    and kwargs['est_qty'] is not None):
                _, kwargs['est_worker_time'] = hours_pair_fill(
                    effective_unit_label, kwargs['est_qty'], None)
            elif ('est_worker_time' in kwargs and 'est_qty' not in kwargs
                    and kwargs['est_worker_time']):
                kwargs['est_qty'], _ = hours_pair_fill(
                    effective_unit_label, None, kwargs['est_worker_time'])
        # Explicit assignment must be schedulable (invariant lives here and
        # on assign/create_direct, not Task.clean — auto-assign is exempt).
        if kwargs.get('assignee'):
            est = kwargs.get('est_worker_time', task.est_worker_time)
            if not est:
                raise ValidationError({'est_worker_time': [
                    'An assigned task must have an estimated worker time.']})
        for field, value in kwargs.items():
            setattr(task, field, value)
        task.full_clean()
        task.save()
        return task

    @staticmethod
    def delete_task(task_pk):
        """Delete a task if allowed.

        Rules (B5 — open to any authenticated user; the guards decide):
        - The job must not be terminal (completed/cancelled/rejected) or held.
        - In-progress and complete tasks cannot be deleted (cancel instead).
        - Tasks with bleps (time entries) cannot be deleted (cancel instead).
        - Tasks with a CONSUMED material cannot be deleted — consumption is
          inventory history that must keep its anchor. Pending materials
          detach to the job as loose rows (Material.task is SET_NULL).
        - Tasks claimed by a non-draft document or on an invoice cannot be
          deleted (cancel instead) — Rule 1: once the claiming document has
          been sent, the task is part of a promise. Draft claims stay
          deletable (release them by removing the line/atoms first).
        """
        from apps.estimates.claims import atom_claimed_by_non_draft_document
        from apps.inventory.models import Material
        from apps.invoicing.claims import InvoiceClaimService
        from apps.invoicing.models import InvoiceLineItemSource
        try:
            task = Task.objects.get(pk=task_pk)
        except Task.DoesNotExist:
            raise NotFoundError(f'Task {task_pk} not found')
        _assert_job_not_on_hold(task.job, 'delete this task')
        if task.job.status in (Job.STATUS_COMPLETED, Job.STATUS_CANCELLED,
                               Job.STATUS_REJECTED):
            raise ValidationError(
                'Cannot delete a task on a closed job.'
            )

        non_deletable = (Task.STATUS_IN_PROGRESS, Task.STATUS_COMPLETE)
        if task.status in non_deletable:
            raise ValidationError(
                f"Cannot delete a {task.status} task. Cancel it instead."
            )
        if Blep.objects.filter(task=task).exists():
            raise ValidationError(
                "Cannot delete a task that has time entries. Cancel it instead."
            )
        if task.materials.filter(
                consumption_state=Material.CONSUMPTION_STATE_CONSUMED).exists():
            raise ValidationError(
                "Cannot delete a task with consumed materials. Cancel it instead."
            )
        if (atom_claimed_by_non_draft_document('task', task.pk)
                or InvoiceClaimService.is_invoiced(
                    InvoiceLineItemSource.SOURCE_TASK, task.pk)):
            raise ValidationError(
                "Cannot delete a task on a sent estimate, change order, or "
                "invoice. Cancel it instead."
            )

        task.delete()

    @staticmethod
    def reorder_tasks(task_id, direction):
        """Reorder a task among its PEERS — delegates to BundlingService.

        Peer-scoped (B3): a top-level task swaps only with other top-level
        tasks, a subtask only with its siblings. The peer group falls out of
        the task itself (parent_task=None ⇒ top level), so both the job
        task list (top-level arrows) and the parent task's detail page
        (sibling arrows) use this same entry point.
        """
        from apps.core.services import BundlingService

        try:
            task = Task.objects.get(pk=task_id)
        except Task.DoesNotExist:
            raise NotFoundError(f'Task {task_id} not found')
        _assert_job_not_on_hold(task.job, 'reorder tasks on this job')

        items_qs = Task.objects.filter(
            job=task.job, parent_task=task.parent_task)

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
            # Task-owned money (Phase 1): sync from the task's own
            # unit_label, not a RateScheme lookup (hours_pair_fill no-ops
            # when the unit isn't hours).
            if task.est_qty is None:
                task.est_qty, _ = hours_pair_fill(
                    task.unit_label, None, est_worker_time)
        task.save()
        return task


class FeeService:
    """Service for Fee (job-owned billable atom) writes.

    A Fee is a fixed charge owned by the Job — a pure pricing decision, not a
    record of work. Mirrors the create/update/delete shape of TaskService and
    respects the on-hold guard like the other job atoms.
    """

    @staticmethod
    def _next_sort_order(job):
        from django.db.models import Max
        current_max = Fee.objects.filter(job=job).aggregate(m=Max('sort_order'))['m']
        return (current_max or 0) + 1

    @staticmethod
    def create_on_job(job, *, description='', quantity=Decimal('1.00'),
                      unit_rate=None, accounting_category=None, task=None,
                      sort_order=None):
        """Create a Fee on `job`. `accounting_category` and `unit_rate` are
        required by the model — a missing one surfaces as a ValidationError
        (→ 400) via full_clean, never a 500."""
        _assert_job_not_on_hold(job, 'add a fee to this job')
        with transaction.atomic():
            if sort_order is None:
                sort_order = FeeService._next_sort_order(job)
            fee = Fee(
                job=job, task=task,
                description=description or '',
                quantity=quantity if quantity is not None else Decimal('1.00'),
                unit_rate=unit_rate,
                accounting_category=accounting_category,
                sort_order=sort_order,
            )
            fee.full_clean()
            fee.save()
        return fee

    @staticmethod
    def update(fee_pk, **kwargs):
        try:
            fee = Fee.objects.get(pk=fee_pk)
        except Fee.DoesNotExist:
            raise NotFoundError(f'Fee {fee_pk} not found')
        _assert_job_not_on_hold(fee.job, 'edit this fee')
        for field, value in kwargs.items():
            setattr(fee, field, value)
        fee.full_clean()
        fee.save()
        return fee

    @staticmethod
    def delete(fee_pk):
        """Delete a fee — but only while nothing references it (Rule 1).

        A claimed fee is part of an agreement's story: removing an agreed
        charge is a change order, not a delete. An invoiced fee is billed
        money. Unreferenced fees (setup scratch, mistakes) delete freely.
        """
        from apps.estimates.claims import atom_is_claimed
        from apps.invoicing.claims import InvoiceClaimService
        from apps.invoicing.models import InvoiceLineItemSource
        try:
            fee = Fee.objects.get(pk=fee_pk)
        except Fee.DoesNotExist:
            raise NotFoundError(f'Fee {fee_pk} not found')
        _assert_job_not_on_hold(fee.job, 'delete this fee')
        if atom_is_claimed('fee', fee.pk):
            raise ValidationError(
                'This fee backs an estimate or change-order line. To stop '
                'charging it, remove the line (draft) or issue a change order.'
            )
        if InvoiceClaimService.is_invoiced(
                InvoiceLineItemSource.SOURCE_FEE, fee.pk):
            raise ValidationError(
                'This fee is on an invoice; remove it from the invoice first.'
            )
        fee.delete()


class TaskLifecycleService:
    """Service for managing Task status transitions and Blep (time tracking) lifecycle."""

    @staticmethod
    def _promote_pending_task(task, assignee_if_unassigned=None):
        """A Blep means work has begun on the task: promote a `pending` task
        to `in_progress` (claiming it for the first worker when unassigned)
        and consume its materials. No-op for any other status (an
        `in_progress` task is already there; a backdated Blep must not
        reopen a terminal or blocked task). Returns True when it promoted.

        Callers MUST hold the row lock (`select_for_update()` on the task),
        which makes the check-then-save race-safe; the `save()` (rather than
        a bulk update) is what makes the promotion history-visible. Folding
        the auto-assign into the same save yields one audit row for the
        whole "first worker started this" event.

        Material consumption is a side effect of the pending -> in_progress
        promotion, not of every clock-in — so it fires here, for both the
        live (start_work) and historical (create_historical) paths."""
        if task.status != Task.STATUS_PENDING:
            return False
        task.status = Task.STATUS_IN_PROGRESS
        if assignee_if_unassigned is not None and not task.assignee_id:
            task.assignee = assignee_if_unassigned
        task.save()
        from apps.inventory.services import MaterialService
        for material in task.materials.all():
            MaterialService.consume(material)
        return True

    @staticmethod
    def _consume_pending_materials(task):
        """Blep-start sweep: a blep means work is happening NOW, so every
        pending material on the task must consume. consume() raising on
        insufficient stock IS the guard — no blep can be recorded while a
        required material is physically missing (same coaching error as the
        first-blep promotion path). This is also what catches the
        arrival-later case: a late-added material left pending because its
        stock hadn't arrived (consume-on-add skips understocked adds) is
        consumed by the next blep once the stock is in."""
        from apps.inventory.models import Material
        from apps.inventory.services import MaterialService
        for material in task.materials.filter(
                consumption_state=Material.CONSUMPTION_STATE_PENDING):
            MaterialService.consume(material)

    @staticmethod
    def add_actual_qty(task_pk, qty):
        """Apply a signed increment to an ENTERED_QTY task's actual_qty.

        Every mid-work write is an add — there is no replace path. A
        negative increment is the correction gesture (fat-fingered 50
        instead of 5 → add -45), bounded so the total never drops below
        zero. Locked so concurrent adds (two workers stopping a joined
        task together) can't lose an entry."""
        from decimal import Decimal, InvalidOperation
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            if task.status in (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED):
                raise ValidationError('Task is already settled.')
            if task.qty_source != Task.QTY_ENTERED:
                raise ValidationError(
                    'Task is not billed by entered quantity.')
            try:
                qty = Decimal(str(qty))
            except (InvalidOperation, TypeError, ValueError):
                raise ValidationError({'actual_qty': ['Invalid decimal.']})
            if qty == 0:
                raise ValidationError({'actual_qty': ['Must not be zero.']})
            new_total = (task.actual_qty or Decimal('0')) + qty
            if new_total < 0:
                raise ValidationError({'actual_qty': [
                    'Cannot reduce the total below zero.']})
            task.actual_qty = new_total
            task.save(update_fields=['actual_qty'])
            return task

    @staticmethod
    def complete_task(task_pk, add_qty=None):
        """Transition task from pending/in_progress/blocked -> complete.

        `add_qty` (optional signed Decimal): the settle-up increment for an
        ENTERED_QTY task. Completion ALWAYS round-trips through the prompt
        for these tasks — when `add_qty` is absent, raises
        `TaskActualQtyRequired` (carrying the running total) so the caller
        can ask "any more to add?". Zero means "nothing more"; negative is
        a last-moment correction; the resulting total must be positive.
        The increment is applied under the row lock, so a teammate's
        concurrent add is simply included in the final total.
        """
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            _assert_job_not_on_hold(task.job, 'complete this task')
            if task.status not in (Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS, Task.STATUS_BLOCKED):
                raise ValidationError(
                    f"Cannot complete task: status is '{task.status}', "
                    f"must be 'pending', 'in_progress', or 'blocked'."
                )
            if task.qty_source == Task.QTY_ENTERED:
                if add_qty is None:
                    raise TaskActualQtyRequired(
                        task.unit_label, task.actual_qty)
                final = (task.actual_qty or Decimal('0')) + add_qty
                if final <= 0:
                    raise ValidationError({'add_qty': [
                        'Final quantity must be greater than 0.']})
                task.actual_qty = final
            if (task.qty_source == Task.QTY_ELAPSED
                    and task.get_actual_qty() <= 0):
                raise TaskTimeRequired()
            # A complete task can never blep again, so nothing would ever
            # consume a leftover pending material — it would sit unbillable
            # forever. Completion stops until the human decides.
            from apps.inventory.models import Material
            pending = list(task.materials.filter(
                consumption_state=Material.CONSUMPTION_STATE_PENDING))
            if pending:
                # Stock check FIRST: "consume it by hand" is a dead end for a
                # material that CAN'T be consumed — provisional (no lot yet)
                # or lot short of stock — so those report their real blocker.
                short = []
                for m in pending:
                    name = m.description or f'material {m.pk}'
                    if m.inventory_item_id is None:
                        short.append(f'{name} (not yet priced/received)')
                    elif (m.quantity > 0
                          and m.inventory_item.qty_on_hand < m.quantity):
                        short.append(
                            f'{name} (needs {m.quantity}, '
                            f'{m.inventory_item.qty_on_hand} on hand)')
                if short:
                    raise ValidationError(
                        f'Cannot complete: material(s) not in stock — '
                        f'{", ".join(short[:3])}. Receive the stock first, or '
                        f'release the material if it will not be used.'
                    )
                names = ', '.join(
                    m.description or f'material {m.pk}' for m in pending[:3])
                raise ValidationError(
                    f'Cannot complete: this task has unconsumed materials '
                    f'({names}). If a material was used, consume it by hand; '
                    f'otherwise release it (restock its full quantity).'
                )
            BlepService._close_open(task=task)
            # save() (not a bulk update) so the transition lands in history.
            task.status = Task.STATUS_COMPLETE
            task.blocked_reason = ''
            task.save()
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
    def block_task(task_pk, reason='', user=None, prior_qty_handled=False):
        """Transition task from pending/in_progress -> blocked.

        Blocking is usually discovered mid-session, so the requester's OWN
        open blep never vetoes the block: it resolves settle-first (a
        `prior_session_qty` conflict on an ENTERED_QTY task, mutating
        nothing until the flagged re-post) and then closes via the shared
        `_close_open` (sub-minimum ⇒ cancel with undo). Only OTHER
        workers' open sessions refuse the block (`active_workers` — no
        override; coordinate before retrying). Callers passing no `user`
        can't claim any session as their own, so any open blep refuses.
        """
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            _assert_job_not_on_hold(task.job, 'block this task')
            if task.status not in (Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS):
                raise ValidationError(
                    f"Cannot block task: status is '{task.status}', "
                    f"must be 'pending' or 'in_progress'."
                )
            open_bleps = Blep.objects.filter(task=task, end_time__isnull=True)
            others = open_bleps if user is None else open_bleps.exclude(user=user)
            if others.exists():
                workers = []
                for b in others:
                    workers.append({
                        'user_id': b.user_id,
                        'name': b.user.get_full_name() or b.user.username,
                        'blep_id': b.blep_id,
                        'started_at': b.start_time,
                    })
                return {'conflict': 'active_workers', 'workers': workers}
            if (user is not None and not prior_qty_handled
                    and task.qty_source == Task.QTY_ENTERED
                    and open_bleps.filter(user=user).exists()):
                return {
                    'conflict': 'prior_session_qty',
                    'prior_task': {'task_id': task.pk, 'name': task.name},
                    'unit_label': task.unit_label,
                    'current_qty': (
                        str(task.actual_qty)
                        if task.actual_qty is not None else None
                    ),
                }
            if user is not None:
                BlepService._close_open(user=user, task=task)
            # save() (not a bulk update) so the transition lands in history.
            task.status = Task.STATUS_BLOCKED
            task.blocked_reason = reason
            task.save()
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
            # save() (not a bulk update) so the transition lands in history.
            task.status = Task.STATUS_IN_PROGRESS
            task.blocked_reason = ''
            task.save()
            return task

    @staticmethod
    def cancel_task(task_pk, user=None, prior_qty_handled=False):
        """Transition task from pending/in_progress/blocked -> cancelled.

        Settle-first (same family as start_work / clock-out): cancelling
        retains recorded quantities just as it retains closed bleps, so
        when the *canceller's own* open blep on an ENTERED_QTY task would
        be closed by this cancel, return a `prior_session_qty` conflict
        (mutating nothing) so the SPA can offer — skippably — to record
        the session's count first. Internal callers (change-order
        acceptance) pass no `user` and never prompt; other workers'
        sessions close silently, as with complete.
        """
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            _assert_job_not_on_hold(task.job, 'cancel this task')
            allowed = (Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS, Task.STATUS_BLOCKED)
            if task.status not in allowed:
                raise ValidationError(
                    f"Cannot cancel task: status is '{task.status}', "
                    f"must be 'pending', 'in_progress', or 'blocked'."
                )
            if (user is not None and not prior_qty_handled
                    and task.qty_source == Task.QTY_ENTERED
                    and Blep.objects.filter(
                        task=task, user=user, end_time__isnull=True,
                    ).exists()):
                return {
                    'conflict': 'prior_session_qty',
                    'prior_task': {'task_id': task.pk, 'name': task.name},
                    'unit_label': task.unit_label,
                    'current_qty': (
                        str(task.actual_qty)
                        if task.actual_qty is not None else None
                    ),
                }
            BlepService._close_open(task=task)
            # Pending materials ride back to the job as loose rows (task=NULL)
            # instead of staying "needed" on a dead task; the user releases
            # them by hand if the stock is truly unwanted. Consumed/released
            # rows stay attached — they are history of work actually done.
            from apps.inventory.models import Material
            from apps.inventory.services import MaterialService
            for material in task.materials.filter(
                    consumption_state=Material.CONSUMPTION_STATE_PENDING):
                MaterialService.assign_task(material, None)
            # save() (not a bulk update) so the transition lands in history.
            # (_close_open above may have reverted a first-blep task to
            # pending on the DB row; pending -> cancelled is legal, so the
            # save still passes clean().)
            task.status = Task.STATUS_CANCELLED
            task.blocked_reason = ''
            task.save()
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
    def prior_session_prompt(user, exclude_task_pk=None):
        """Return a `prior_session_qty` conflict dict when `user` holds an
        open blep on an ENTERED_QTY task (optionally excluding one task),
        else None. Shared by start_work and the clock-out endpoint: an own
        explicit gesture that would silently close such a session prompts
        the SPA to settle it first."""
        qs = Blep.objects.filter(
            user=user, end_time__isnull=True,
            task__qty_source=Task.QTY_ENTERED,
        ).select_related('task')
        if exclude_task_pk is not None:
            qs = qs.exclude(task_id=exclude_task_pk)
        prior = qs.first()
        if prior is None:
            return None
        prior_task = prior.task
        return {
            'conflict': 'prior_session_qty',
            'prior_task': {
                'task_id': prior_task.pk,
                'name': prior_task.name,
            },
            'unit_label': prior_task.unit_label,
            'current_qty': (
                str(prior_task.actual_qty)
                if prior_task.actual_qty is not None else None
            ),
        }

    @staticmethod
    def start_work(task_pk, user, action=None, on_behalf_of=None,
                   prior_qty_handled=False):
        """Create a Blep on the given task.

        - The blep is attributed to `target` = `on_behalf_of or user`. When
          `on_behalf_of` differs from `user`, the actor (`user`) must hold
          can_manage_time — a manager starting a worker's timer as a
          convenience.
        - Own starts settle first: without `prior_qty_handled`, an open blep
          on a different ENTERED_QTY task returns a `prior_session_qty`
          conflict (mutating nothing) so the SPA can prompt for that
          session's count. On-behalf starts never prompt.
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
                (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED,
                 Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS),
                'start work',
            )
            if task.status not in (Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS):
                raise ValidationError(
                    f"Cannot start work: task status is '{task.status}', "
                    f"must be 'pending' or 'in_progress'."
                )
            # Evaluated before the active_worker conflict below: the old
            # session gets settled before join/takeover on the new task.
            if not prior_qty_handled and on_behalf_of is None:
                prompt = TaskLifecycleService.prior_session_prompt(
                    target, exclude_task_pk=task.pk)
                if prompt is not None:
                    return prompt
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
                TaskLifecycleService._promote_pending_task(
                    task, assignee_if_unassigned=target)
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
                # The prior-session prompt already ran (or was flagged) on
                # the way in — don't re-prompt on the internal restart.
                return TaskLifecycleService.start_work(
                    task_pk, target, prior_qty_handled=True)
            # A blep on an in-progress task must consume any materials that
            # arrived (or refuse while one is still missing) — see the sweep.
            TaskLifecycleService._consume_pending_materials(task)
            # Close target's open Blep on ANY task
            BlepService._close_open(user=target, now=now)
            blep = BlepService._create(task, target, start_time=now)
            JobService.mark_work_started(task.job)
            # Promote only when the blepper IS the assignee (see above).
            if task.assignee_id == target.pk:
                TaskLifecycleService._promote_to_front_of_worker_queue(task)
            return {'task': task, 'blep': blep}

    @staticmethod
    def stop_work(task_pk, user, on_behalf_of=None, prior_qty_handled=False,
                  add_qty=None):
        """Close the target's open Blep on this task.

        `target` = `on_behalf_of or user`. Stopping another user's timer
        (e.g. a worker who left and forgot to clock out) requires the actor
        (`user`) to hold can_manage_time.

        Settle-first for own stops on ENTERED_QTY tasks: without
        `prior_qty_handled`, returns a `prior_session_qty` conflict dict
        and mutates NOTHING — the session keeps running until the SPA's
        prompt resolves (recording the count is part of the work, and the
        band stays honest because nothing has happened yet). The flagged
        re-post may carry `add_qty` (the session count, > 0): the increment
        applies and the blep closes in one transaction, so a failed entry
        can never half-run. On-behalf stops never conflict — the actor
        doesn't know the count.
        """
        target = on_behalf_of or user
        if target != user and not _has_manage_time(user):
            raise BlepPermissionError(
                "Stopping another user's timer requires can_manage_time."
            )
        with transaction.atomic():
            task = Task.objects.select_for_update().get(pk=task_pk)
            if (on_behalf_of is None and not prior_qty_handled
                    and task.qty_source == Task.QTY_ENTERED
                    and Blep.objects.filter(
                        task=task, user=target, end_time__isnull=True,
                    ).exists()):
                return {
                    'conflict': 'prior_session_qty',
                    'prior_task': {'task_id': task.pk, 'name': task.name},
                    'unit_label': task.unit_label,
                    'current_qty': (
                        str(task.actual_qty)
                        if task.actual_qty is not None else None
                    ),
                }
            if add_qty is not None:
                if task.qty_source != Task.QTY_ENTERED:
                    raise ValidationError(
                        'Task is not billed by entered quantity.')
                if add_qty <= 0:
                    raise ValidationError({'add_qty': [
                        'Must be greater than 0.']})
                task.actual_qty = (task.actual_qty or Decimal('0')) + add_qty
                task.save(update_fields=['actual_qty'])
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

        Only allowed while the session is under `blep_minimum_minutes` plus one
        grace minute; over that the caller should Stop instead (enforced
        defensively here). The grace minute exists because Blep.save() floors
        start_time to the whole minute, so the books can show up to ~59s more
        session than the user experienced — without it, a Start clicked just
        before a minute boundary can't be "oops"-cancelled inside the user's
        real first minute. The clock-out/stop auto-cancel path deliberately
        keeps the plain minimum (it decides cancel-vs-close bookkeeping, not a
        human's cancel request).
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
            whole_minutes = int(
                (timezone.now() - blep.start_time).total_seconds() // 60)
            if whole_minutes >= blep_minimum_minutes() + 1:
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

        # Pipeline: draft + submitted + approved (estimate accepted, awaiting
        # prep). A held job keeps its true status, so held-from-approved jobs
        # land here automatically with the 'on-hold' sub-status.
        pipeline_jobs = list(Job.objects.filter(
            status__in=[Job.STATUS_DRAFT, Job.STATUS_SUBMITTED,
                        Job.STATUS_APPROVED]
        ).select_related('contact', 'project_manager').order_by('due_date'))
        pipeline_deposit_states = BoardService._deposit_states(
            [j.job_id for j in pipeline_jobs])
        pipeline = [
            BoardService._serialize_job(job, pipeline_deposit_states)
            for job in pipeline_jobs
        ]

        # In Progress (board column key kept as 'approved' for URL stability)
        approved_jobs = list(Job.objects.filter(
            status='in_progress'
        ).select_related('contact', 'project_manager').order_by('due_date'))
        approved_deposit_states = BoardService._deposit_states(
            [j.job_id for j in approved_jobs])
        approved_list = []
        for i, job in enumerate(approved_jobs):
            job_data = BoardService._serialize_job(job, approved_deposit_states)
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
        closed_jobs = list(Job.objects.filter(
            status__in=[Job.STATUS_COMPLETED, Job.STATUS_REJECTED,
                        Job.STATUS_CANCELLED],
            completed_date__gte=cutoff,
        ).select_related('contact', 'project_manager').order_by('-completed_date'))
        closed_deposit_states = BoardService._deposit_states(
            [j.job_id for j in closed_jobs])
        closed = [
            BoardService._serialize_closed_job(job, closed_deposit_states)
            for job in closed_jobs
        ]

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
        """Return pipeline jobs (draft + submitted + approved, held or not)
        with worksheet/estimate info."""
        from apps.jobs.models import Job
        pipeline_jobs = list(Job.objects.filter(
            status__in=[Job.STATUS_DRAFT, Job.STATUS_SUBMITTED,
                        Job.STATUS_APPROVED]
        ).select_related('contact', 'project_manager').order_by('due_date'))
        deposit_states = BoardService._deposit_states(
            [j.job_id for j in pipeline_jobs])
        return {
            'jobs': [
                BoardService._serialize_pipeline_job(job, deposit_states)
                for job in pipeline_jobs
            ],
        }

    @staticmethod
    def in_progress_column_jobs():
        """Job instances in the board's In Progress column, in display order.

        The set is work-driven: every `in_progress` job (held or not), plus
        unheld pre-approval (`draft`/`submitted`) jobs that have at least one
        task that is assigned AND still planned (pending/in_progress) —
        deliberate work-ahead someone chose to assign. The pre-approval trigger
        is self-limiting: the job drops back off both surfaces the moment its
        assigned tasks complete (its history bars remain in the schedule
        lanes). `approved` stays excluded — release-to-floor is the gate.
        Ordered by `due_date`, minus any whose sub-status routes them to the
        Unpaid column.

        This is the single definition of "the In Progress column job set",
        shared by the board column (`get_approved_data`) and the schedule chip
        strip (`ScheduleService.get_schedule`) so the two never drift. No
        `status=in_progress` job currently lands in `UNPAID_SUB_STATUSES`
        (those arise on `work_complete`), so the exclusion is a structural
        guard rather than a live filter. `select_related` covers the related
        fields both callers serialize.
        """
        from django.db.models import Q
        from apps.jobs.models import Job, Task
        jobs = Job.objects.filter(
            Q(status=Job.STATUS_IN_PROGRESS)
            | Q(status__in=[Job.STATUS_DRAFT, Job.STATUS_SUBMITTED],
                on_hold=False,
                tasks__assignee__isnull=False,
                tasks__status__in=[Task.STATUS_PENDING, Task.STATUS_IN_PROGRESS])
        ).distinct().select_related('contact', 'project_manager').order_by('due_date')
        return [
            job for job in jobs
            if BoardService.compute_sub_status(job)
            not in BoardService.UNPAID_SUB_STATUSES
        ]

    @staticmethod
    def strip_jobs_payload():
        """The chip/card payload for the shared In Progress surface — the
        single serialization of `in_progress_column_jobs()`, consumed
        verbatim by BOTH the board column (`get_approved_data`) and the
        schedule chip strip (`ScheduleService.get_schedule`). One dict shape
        so the two surfaces can't drift: `_serialize_job` fields (incl.
        sub_status and the pre_approval/on_hold flags), an accent-color
        fallback, and the task_total/task_completed counts the hover
        popup's progress bar reads (cancelled tasks excluded)."""
        from django.db.models import Count, Q as DjQ
        from apps.jobs.models import Task

        jobs = BoardService.in_progress_column_jobs()
        deposit_states = BoardService._deposit_states([j.pk for j in jobs])
        stats_by_job = {
            s['job_id']: s
            for s in Task.objects.filter(job_id__in=[j.pk for j in jobs])
            .exclude(status=Task.STATUS_CANCELLED)
            .values('job_id')
            .annotate(
                total=Count('task_id'),
                completed=Count('task_id', filter=DjQ(status=Task.STATUS_COMPLETE)),
            )
        }
        payload = []
        for i, job in enumerate(jobs):
            job_data = BoardService._serialize_job(job, deposit_states)
            job_data['accent_color'] = job.accent_color or BoardService.ACCENT_COLORS[
                i % len(BoardService.ACCENT_COLORS)
            ]
            s = stats_by_job.get(job.pk, {'total': 0, 'completed': 0})
            job_data['task_total'] = s['total']
            job_data['task_completed'] = s['completed']
            payload.append(job_data)
        return payload

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

        approved_list = BoardService.strip_jobs_payload()
        color_map = {j['job_id']: j['accent_color'] for j in approved_list}
        approved_job_ids = [j['job_id'] for j in approved_list]

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
        from apps.invoicing.models import Invoice
        unpaid_jobs = list(Job.objects.filter(
            Q(status=Job.STATUS_WORK_COMPLETE) |
            Q(invoice__status__in=[Invoice.STATUS_DRAFT, Invoice.STATUS_OPEN,
                                   Invoice.STATUS_PARTLY_PAID, Invoice.STATUS_DEFAULTED])
        ).distinct().select_related('contact', 'project_manager').order_by('due_date'))

        deposit_states = BoardService._deposit_states(
            [j.job_id for j in unpaid_jobs])
        unpaid_list = [
            BoardService._serialize_unpaid_job(job, deposit_states)
            for job in unpaid_jobs
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

        closed_jobs = list(Job.objects.filter(
            status__in=[Job.STATUS_COMPLETED, Job.STATUS_REJECTED,
                        Job.STATUS_CANCELLED],
            completed_date__gte=cutoff,
        ).select_related('contact', 'project_manager').order_by('-completed_date'))
        deposit_states = BoardService._deposit_states(
            [j.job_id for j in closed_jobs])
        return {
            'jobs': [
                BoardService._serialize_closed_job(job, deposit_states)
                for job in closed_jobs
            ],
        }

    @staticmethod
    def _deposit_states(job_ids):
        """job_id -> 'requested' | 'paid' for jobs with live deposit
        signals; jobs absent from the dict have none."""
        from apps.invoicing.models import (
            Invoice, InvoiceLineItem, InvoiceLineItemSource,
        )
        rows = list(
            InvoiceLineItem.objects
            .filter(invoice__job_id__in=job_ids,
                    accounting_category__is_deposit=True,
                    invoice__status__in=[
                        Invoice.STATUS_OPEN, Invoice.STATUS_PARTLY_PAID,
                        Invoice.STATUS_PAID])
            .exclude(
                sources__source_type=InvoiceLineItemSource.SOURCE_DEPOSIT)
            .values_list('pk', 'invoice__job_id', 'invoice__status')
        )
        claimed = set(
            InvoiceLineItemSource.objects
            .filter(source_type=InvoiceLineItemSource.SOURCE_DEPOSIT,
                    source_pk__in=[pk for pk, _, _ in rows])
            .exclude(invoice_line_item__invoice__status=
                     Invoice.STATUS_CANCELLED)
            .values_list('source_pk', flat=True)
        )
        states = {}
        for pk, job_id, status in rows:
            if status in (Invoice.STATUS_OPEN, Invoice.STATUS_PARTLY_PAID):
                states[job_id] = 'requested'
            elif pk not in claimed and states.get(job_id) != 'requested':
                states[job_id] = 'paid'
        return states

    @staticmethod
    def _serialize_job(job, deposit_states=None):
        return {
            'job_id': job.job_id,
            'job_number': job.job_number,
            'name': job.name,
            'status': job.status,
            # A quote-stage job appearing on a work surface is exceptional —
            # the flag drives its distinct card/chip treatment.
            'pre_approval': job.status in (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED),
            'on_hold': job.on_hold,
            'hold_reason': job.hold_reason,
            'sub_status': BoardService.compute_sub_status(job),
            'contact_id': job.contact_id,
            'contact_name': str(job.contact) if job.contact else None,
            'project_manager_name': (
                (job.project_manager.get_full_name() or job.project_manager.username)
                if job.project_manager_id else None
            ),
            'due_date': job.due_date.isoformat() if job.due_date else None,
            'completed_date': job.completed_date.isoformat() if job.completed_date else None,
            'deposit_state': (deposit_states or {}).get(job.job_id),
        }

    @staticmethod
    def _serialize_closed_job(job, deposit_states=None):
        """Serialize a closed job with dates and profitability."""
        data = BoardService._serialize_job(job, deposit_states)
        data['start_date'] = job.start_date.isoformat() if job.start_date else None
        profitability = BoardService._compute_profitability(job)
        data.update(profitability)
        return data

    @staticmethod
    def _serialize_pipeline_job(job, deposit_states=None):
        """Serialize a pipeline job with worksheet and estimate info."""
        from apps.estimates.models import EstimateLineItem
        data = BoardService._serialize_job(job, deposit_states)

        # The plan/worksheet layer has been removed; work lives directly on the
        # Job. The key is kept (empty) for API-contract stability until the
        # frontend drops it (Phase 7).
        data['worksheets'] = []

        estimates = []
        from apps.estimates.models import Estimate as _Estimate
        for est in _Estimate.with_amended_flag(job.estimate_set.order_by('-pk')):
            total = EstimateLineItem.objects.filter(estimate=est).aggregate(
                total=models.Sum(models.F('qty') * models.F('price'))
            )['total'] or Decimal('0.00')
            estimates.append({
                'estimate_id': est.estimate_id,
                'estimate_number': est.estimate_number,
                'status': est.status,
                # Derived "amended" flag — see Estimate.is_amended() (the single
                # source of truth shared with the EstimateSerializer).
                'is_amended': est.is_amended(),
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
    def _serialize_unpaid_job(job, deposit_states=None):
        """Serialize an unpaid job with invoice details and profitability."""
        from apps.invoicing.models import Invoice
        data = BoardService._serialize_job(job, deposit_states)
        invoices = []
        for inv in job.invoice_set.select_related('job').exclude(
                status__in=[Invoice.STATUS_CANCELLED, Invoice.STATUS_SUPERSEDED]).order_by('created_date'):
            total = inv.invoicelineitem_set.aggregate(
                total=models.Sum(models.F('qty') * models.F('price'))
            )['total'] or Decimal('0.00')
            invoices.append({
                'invoice_id': inv.invoice_id,
                'invoice_number': inv.invoice_number,
                'display_number': inv.display_number,
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
        """Derive the sub-status of a job based on related object states.
        The hold flag wins over everything — a held job reads 'on-hold'
        whatever its underlying status."""
        if job.on_hold:
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

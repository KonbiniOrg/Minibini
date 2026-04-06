from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.jobs.models import Blep


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

        At least one of `user` or `task` must be provided. Returns the
        number of bleps that were closed.
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
        return qs.update(end_time=now)

    # ─────────────────────────── public API ───────────────────────────

    @staticmethod
    def create_historical(actor, task, start_time, end_time, target_user=None):
        """Create a historical blep with validation.

        - actor: the user performing the action
        - target_user: user the blep belongs to (defaults to actor)
        - Creating for another user requires can_manage_time
        - Creating older than 24h requires can_manage_time
        - Task must belong to a WorkOrder
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
        return BlepService._create(
            task, target_user, start_time=start_time, end_time=end_time,
        )

    @staticmethod
    def update(blep, actor, **fields):
        """Update a blep. Only `start_time` and `end_time` are editable here."""
        is_own = blep.user_id == actor.pk
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
            raise ValidationError(
                f"Cannot update fields: {', '.join(sorted(unknown))}"
            )

        new_start = fields.get('start_time', blep.start_time)
        new_end = fields.get('end_time', blep.end_time)
        if new_end is not None and new_start is not None and new_end < new_start:
            raise ValidationError("end_time must be >= start_time.")

        effective_end = new_end if new_end is not None else timezone.now()
        if _existing_overlaps(
            blep.user, new_start, effective_end, exclude_blep_id=blep.blep_id,
        ):
            raise ValidationError(
                "This time entry would overlap an existing entry for the user."
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
                    "Deleting a time entry older than 24 hours requires can_manage_time."
                )
        else:
            if not _has_manage_time(actor):
                raise BlepPermissionError(
                    "Deleting another user's time entry requires can_manage_time."
                )
        blep.delete()

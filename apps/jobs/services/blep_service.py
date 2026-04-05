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

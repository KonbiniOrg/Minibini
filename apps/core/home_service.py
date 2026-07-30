"""Service for building the user home page data payload."""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.activity.services import load_recent_days
from apps.jobs.models import Task


class HomeService:
    """Assembles the data the Svelte home page needs in one call."""

    RECENT_TASKS_LIMIT = 10
    HIDDEN_TASK_STATUSES = (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED)

    @classmethod
    def get_home_data(cls, user):
        # Look-back window (days) for the home page's recent lists —
        # shared with the Activity page via activity_recent_days.
        recent_days = load_recent_days()
        return {
            'current_tasks': cls._current_tasks(user, recent_days),
            'recent_tasks': cls._recent_tasks(user, recent_days),
            'recent_logins': cls._recent_logins(user, recent_days),
            'recent_days': recent_days,
        }

    @classmethod
    def _current_tasks(cls, user, recent_days):
        """The user's live work: tasks assigned to them, plus any task they
        have an open or recently-worked blep on (even if assigned to someone
        else). Completed/cancelled tasks are excluded (they surface in
        recent_tasks). Own tasks sort first in worker-queue order; tasks that
        only appear because of a blep sort to the bottom, most-recent first."""
        cutoff = timezone.now() - timedelta(days=recent_days)
        tasks = (
            Task.objects
            .exclude(status__in=cls.HIDDEN_TASK_STATUSES)
            .filter(
                Q(assignee=user)
                | Q(blep__user=user, blep__end_time__isnull=True)
                | Q(blep__user=user, blep__start_time__gte=cutoff)
            )
            .select_related('job')
            .prefetch_related('blep_set')
            .distinct()
        )

        mine, others = [], []
        for task in tasks:
            if task.assignee_id == user.pk:
                mine.append(task)
            else:
                others.append(task)

        mine.sort(key=lambda t: (t.worker_queue if t.worker_queue is not None else 0, t.task_id))
        others.sort(key=lambda t: cls._last_worked_at(t, user), reverse=True)

        result = []
        for task in mine:
            row = cls._serialize_task(task)
            row['assigned_to_me'] = True
            result.append(row)
        for task in others:
            row = cls._serialize_task(task)
            row['assigned_to_me'] = False
            result.append(row)
        return result

    @classmethod
    def _recent_tasks(cls, user, recent_days):
        """Tasks the user completed recently — status complete with a blep by
        the user inside the look-back window — most-recently-worked first.
        (Task has no completion timestamp of its own, so the user's latest
        blep on the task is the recency signal, as the old recent-jobs list
        used.)"""
        cutoff = timezone.now() - timedelta(days=recent_days)
        tasks = (
            Task.objects
            .filter(status=Task.STATUS_COMPLETE,
                    blep__user=user, blep__start_time__gte=cutoff)
            .select_related('job')
            .prefetch_related('blep_set')
            .distinct()
        )
        rows = sorted(
            tasks, key=lambda t: cls._last_worked_at(t, user), reverse=True
        )[:cls.RECENT_TASKS_LIMIT]

        result = []
        for task in rows:
            row = cls._serialize_task(task)
            last = cls._last_worked_at(task, user)
            row['last_worked_at'] = last.isoformat() if last else None
            result.append(row)
        return result

    @staticmethod
    def _last_worked_at(task, user):
        """Latest start_time among the user's bleps on the task (from the
        prefetched blep_set), or None."""
        stamps = [b.start_time for b in task.blep_set.all() if b.user_id == user.pk]
        return max(stamps) if stamps else None

    @classmethod
    def _serialize_task(cls, task):
        job = task.job
        bleps = list(task.blep_set.all())
        open_user_ids = {b.user_id for b in bleps if b.end_time is None}
        return {
            'id': task.pk,
            'name': task.name,
            'description': task.description,
            'status': task.status,
            'worker_queue': task.worker_queue,
            'has_active_blep': bool(open_user_ids),
            'active_worker_count': len(open_user_ids),
            'has_bleps': bool(bleps),
            'job': {
                'id': job.pk,
                'job_number': job.job_number,
                'name': job.name,
            } if job else None,
        }

    @classmethod
    def _recent_logins(cls, user, recent_days):
        # user_agent is kept in the DB for support investigation but omitted
        # from the payload — long, uninformative, privacy-adjacent.
        from apps.core.models import LoginEvent

        cutoff = timezone.now() - timedelta(days=recent_days)
        events = (
            LoginEvent.objects
            .filter(user=user, timestamp__gte=cutoff)
            .order_by('-timestamp')
        )
        return [
            {
                'timestamp': e.timestamp.isoformat(),
                'ip_address': e.ip_address,
            }
            for e in events
        ]

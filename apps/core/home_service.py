"""Service for building the user home page data payload."""

from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

from apps.activity.services import load_recent_days
from apps.jobs.models import Blep, Job, Task


class HomeService:
    """Assembles the data the Svelte home page needs in one call."""

    RECENT_JOBS_LIMIT = 10
    HIDDEN_TASK_STATUSES = (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED)

    @classmethod
    def get_home_data(cls, user):
        # Look-back window (days) for the home page's recent lists —
        # shared with the Activity page via activity_recent_days.
        recent_days = load_recent_days()
        return {
            'assigned_tasks': cls._assigned_tasks(user),
            'recent_jobs': cls._recent_jobs(user, recent_days),
            'recent_logins': cls._recent_logins(user, recent_days),
            'recent_days': recent_days,
        }

    @classmethod
    def _assigned_tasks(cls, user):
        tasks = (
            Task.objects
            .filter(assignee=user)
            .exclude(status__in=cls.HIDDEN_TASK_STATUSES)
            .select_related('job')
            .prefetch_related('blep_set')
            .order_by('worker_queue', 'task_id')
        )
        return [cls._serialize_task(t) for t in tasks]

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
    def _recent_jobs(cls, user, recent_days):
        # Find distinct jobs the user has a Blep on within the look-back
        # window, ordered by the user's most recent Blep start_time on that
        # job, limited. Both conditions in ONE filter() call so they share
        # the join — the Max annotation then ranges over exactly the
        # user's in-window bleps.
        cutoff = timezone.now() - timedelta(days=recent_days)
        job_rows = (
            Job.objects
            .filter(tasks__blep__user=user,
                    tasks__blep__start_time__gte=cutoff)
            .annotate(last_worked_at=Max('tasks__blep__start_time'))
            .order_by('-last_worked_at')
            .distinct()
        )[:cls.RECENT_JOBS_LIMIT]

        return [
            {
                'id': j.pk,
                'job_number': j.job_number,
                'name': j.name,
                'last_worked_at': j.last_worked_at.isoformat() if j.last_worked_at else None,
            }
            for j in job_rows
        ]

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

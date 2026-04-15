"""Service for building the user home page data payload."""

from django.db.models import Max

from apps.jobs.models import Blep, Job, Task


class HomeService:
    """Assembles the data the Svelte home page needs in one call."""

    RECENT_JOBS_LIMIT = 10
    HIDDEN_TASK_STATUSES = (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED)

    @classmethod
    def get_home_data(cls, user):
        return {
            'assigned_tasks': cls._assigned_tasks(user),
            'recent_jobs': cls._recent_jobs(user),
        }

    @classmethod
    def _assigned_tasks(cls, user):
        tasks = (
            Task.objects
            .filter(assignee=user)
            .exclude(status__in=cls.HIDDEN_TASK_STATUSES)
            .select_related('job')
            .order_by('worker_queue', 'task_id')
        )
        return [cls._serialize_task(t) for t in tasks]

    @classmethod
    def _serialize_task(cls, task):
        job = task.job
        return {
            'id': task.pk,
            'name': task.name,
            'description': task.description,
            'status': task.status,
            'worker_queue': task.worker_queue,
            'job': {
                'id': job.pk,
                'job_number': job.job_number,
                'name': job.name,
            } if job else None,
        }

    @classmethod
    def _recent_jobs(cls, user):
        # Find distinct jobs the user has any Blep on, ordered by the user's
        # most recent Blep start_time on that job, limited.
        job_rows = (
            Job.objects
            .filter(tasks__blep__user=user)
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

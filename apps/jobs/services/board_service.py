from django.utils import timezone
from datetime import timedelta

from apps.core.models import Configuration
from apps.jobs.models import Task


class BoardService:
    """Computes board data including sub-statuses for jobs."""

    ACCENT_COLORS = [
        '#f97066', '#f59e0b', '#14b8a6', '#8b5cf6',
        '#38bdf8', '#fb7185', '#84cc16', '#f97316',
    ]

    @staticmethod
    def get_board_data():
        """Assemble all data for the job board view."""
        from apps.jobs.models import Job, WorkOrder, Task
        from django.contrib.auth import get_user_model
        User = get_user_model()

        retention_days = 14
        try:
            config = Configuration.objects.get(key='board_closed_retention_days')
            retention_days = int(config.value)
        except (Configuration.DoesNotExist, ValueError):
            pass

        cutoff = timezone.now() - timedelta(days=retention_days)

        # Pipeline: draft + submitted
        pipeline_jobs = Job.objects.filter(
            status__in=['draft', 'submitted']
        ).select_related('contact').order_by('due_date')
        pipeline = [BoardService._serialize_job(job) for job in pipeline_jobs]

        # Approved
        approved_jobs = Job.objects.filter(
            status='approved'
        ).select_related('contact').order_by('due_date')
        approved_list = []
        for i, job in enumerate(approved_jobs):
            job_data = BoardService._serialize_job(job)
            job_data['accent_color'] = BoardService.ACCENT_COLORS[
                i % len(BoardService.ACCENT_COLORS)
            ]
            approved_list.append(job_data)

        # Build job_id -> accent_color map for tasks
        color_map = {j['job_id']: j['accent_color'] for j in approved_list}

        # Get all incomplete tasks from approved jobs' open work orders
        approved_job_ids = [j['job_id'] for j in approved_list]
        tasks = Task.objects.filter(
            work_order__job_id__in=approved_job_ids,
            work_order__status='incomplete',
        ).exclude(
            status__in=[Task.STATUS_COMPLETE, Task.STATUS_CANCELLED]
        ).select_related(
            'work_order__job', 'assignee'
        ).order_by('worker_queue', 'pk')

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
        ).select_related('contact').order_by('-completed_date')
        closed = [BoardService._serialize_job(job) for job in closed_jobs]

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
    def _serialize_job(job):
        return {
            'job_id': job.job_id,
            'job_number': job.job_number,
            'name': job.name,
            'status': job.status,
            'sub_status': BoardService.compute_sub_status(job),
            'contact_id': job.contact_id,
            'contact_name': str(job.contact) if job.contact else None,
            'due_date': job.due_date.isoformat() if job.due_date else None,
            'completed_date': job.completed_date.isoformat() if job.completed_date else None,
        }

    @staticmethod
    def _serialize_task(task, color_map):
        job = task.work_order.job
        return {
            'task_id': task.task_id,
            'name': task.name,
            'status': task.status,
            'job_id': job.job_id,
            'job_name': job.name,
            'job_due_date': job.due_date.isoformat() if job.due_date else None,
            'accent_color': color_map.get(job.job_id, '#94a3b8'),
            'assignee_id': task.assignee_id,
            'worker_queue': task.worker_queue,
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
    def compute_sub_status(job):
        """Derive the sub-status of a job based on related object states."""
        if job.status in ('draft', 'submitted'):
            return BoardService._pipeline_sub_status(job)
        elif job.status == 'approved':
            return BoardService._approved_sub_status(job)
        return None

    @staticmethod
    def _pipeline_sub_status(job):
        """Sub-status for Draft/Submitted jobs."""
        estimates = job.estimate_set.all()
        open_estimate = estimates.filter(status='open').first()
        if open_estimate:
            return 'awaiting-response'

        worksheets = job.estworksheet_set.all()
        if not worksheets.exists():
            return 'needs-scoping'

        latest_ws = worksheets.order_by('-pk').first()
        if latest_ws.status == 'draft':
            return 'estimating'

        if latest_ws.status == 'final':
            draft_estimate = estimates.filter(status='draft').first()
            if draft_estimate:
                return 'estimate-ready'

        return 'needs-scoping'

    @staticmethod
    def _approved_sub_status(job):
        """Sub-status for Approved jobs."""
        invoices = job.invoice_set.all()
        sent_invoice = invoices.filter(status='open').first()
        if sent_invoice:
            return 'invoice-sent'

        work_orders = job.workorder_set.all()
        if not work_orders.exists():
            return 'needs-work-order'

        active_wo = work_orders.filter(status='incomplete').order_by('-pk').first()
        if not active_wo:
            active_wo = work_orders.order_by('-pk').first()

        if active_wo.status == 'complete':
            return 'invoice-prepped'

        tasks = active_wo.task_set.exclude(
            status__in=[Task.STATUS_COMPLETE, Task.STATUS_CANCELLED]
        )
        if tasks.filter(status=Task.STATUS_BLOCKED).exists():
            return 'blocked'
        if tasks.filter(status=Task.STATUS_IN_PROGRESS).exists():
            return 'in-progress'

        return 'work-ready'

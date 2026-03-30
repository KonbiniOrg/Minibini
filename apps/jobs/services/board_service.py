from django.utils import timezone
from datetime import timedelta

from apps.core.models import Configuration
from apps.jobs.models import Task


class BoardService:
    """Computes board data including sub-statuses for jobs."""

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

"""ActivityService — computes the /activity dashboard payload.

Model-less service app (mirrors apps/schedule). Reads existing models plus the
`activity_recent_days` Configuration key, which defines a single look-back
window governing the whole page. Everything is read-only.
"""
from datetime import timedelta

from django.utils import timezone

from apps.core.models import Configuration, Shift
from apps.jobs.models import Blep, Job
from apps.estimates.models import Estimate
from apps.purchasing.models import PurchaseOrder
from apps.invoicing.models import Invoice
from apps.api.bleps.serializers import BlepSerializer


DEFAULT_RECENT_DAYS = 5


def load_recent_days():
    """Read `activity_recent_days` from Configuration.

    Returns an int clamped to a minimum of 1. Falls back to
    DEFAULT_RECENT_DAYS (5) when the key is missing or unparseable.

    Does NOT write a default back into Configuration (read-only).
    """
    try:
        n = int(Configuration.objects.get(key='activity_recent_days').value)
    except (Configuration.DoesNotExist, ValueError, TypeError):
        return DEFAULT_RECENT_DAYS
    return max(1, n)


def _iso(dt):
    return dt.isoformat() if dt is not None else None


def _date(dt):
    """Day-granularity display date (ISO date string) or None."""
    return dt.date().isoformat() if dt is not None else None


def _user_name(user):
    if user is None:
        return None
    return user.get_full_name() or user.username


class ActivityService:

    @staticmethod
    def get_activity(now=None):
        if now is None:
            now = timezone.now()
        recent_days = load_recent_days()
        cutoff = now - timedelta(days=recent_days)

        return {
            'recent_days': recent_days,
            'on_shift': ActivityService._on_shift(),
            'completed_bleps': ActivityService._completed_bleps(cutoff),
            'job_events': ActivityService._job_events(cutoff),
            'po_events': ActivityService._po_events(cutoff),
            'invoice_events': ActivityService._invoice_events(cutoff),
        }

    # ---- on shift ----------------------------------------------------

    @staticmethod
    def _on_shift():
        shifts = (
            Shift.objects.filter(end_time__isnull=True)
            .select_related('user')
            .order_by('start_time')
        )
        # One open Blep per clocked-in user (if any). A user generally has at
        # most one open blep; pick the most recent if somehow more than one.
        open_bleps = (
            Blep.objects.filter(end_time__isnull=True)
            .select_related('task', 'task__job', 'user')
            .order_by('-start_time')
        )
        blep_by_user = {}
        for blep in open_bleps:
            blep_by_user.setdefault(blep.user_id, blep)

        cards = []
        for shift in shifts:
            blep = blep_by_user.get(shift.user_id)
            current_blep = None
            if blep is not None:
                task = blep.task
                job = task.job
                current_blep = {
                    'task_id': task.pk,
                    'task_name': task.name,
                    'job_id': job.pk,
                    'job_number': job.job_number,
                    'job_name': job.name,
                    'blep_start': _iso(blep.start_time),
                }
            cards.append({
                'user_id': shift.user_id,
                'user_name': _user_name(shift.user),
                'shift_start': _iso(shift.start_time),
                'current_blep': current_blep,
            })
        return cards

    # ---- completed bleps ---------------------------------------------

    @staticmethod
    def _completed_bleps(cutoff):
        bleps = (
            Blep.objects.filter(
                end_time__isnull=False, end_time__gte=cutoff,
            )
            .select_related('task', 'task__job', 'user')
            .order_by('-end_time')
        )
        # Reuse BlepSerializer so the payload shape stays identical to the
        # /api/bleps/ endpoint by construction.
        return BlepSerializer(bleps, many=True).data

    # ---- job events (estimate sent + job approved) -------------------

    @staticmethod
    def _job_events(cutoff):
        events = []

        estimates = (
            Estimate.objects.filter(sent_date__gte=cutoff)
            .select_related('job')
        )
        for est in estimates:
            job = est.job
            events.append({
                'kind': 'estimate_sent',
                'job_id': job.pk,
                'job_number': job.job_number,
                'job_name': job.name,
                'estimate_id': est.pk,
                'date': _date(est.sent_date),
                '_sort': est.sent_date,
            })

        jobs = Job.objects.filter(start_date__gte=cutoff)
        for job in jobs:
            events.append({
                'kind': 'job_approved',
                'job_id': job.pk,
                'job_number': job.job_number,
                'job_name': job.name,
                'date': _date(job.start_date),
                '_sort': job.start_date,
            })

        return ActivityService._sorted(events)

    # ---- PO events ---------------------------------------------------

    @staticmethod
    def _po_events(cutoff):
        events = []
        for po in PurchaseOrder.objects.filter(issued_date__gte=cutoff):
            events.append({
                'kind': 'sent',
                'po_id': po.pk,
                'po_number': po.po_number,
                'date': _date(po.issued_date),
                '_sort': po.issued_date,
            })
        for po in PurchaseOrder.objects.filter(received_date__gte=cutoff):
            events.append({
                'kind': 'received',
                'po_id': po.pk,
                'po_number': po.po_number,
                'date': _date(po.received_date),
                '_sort': po.received_date,
            })
        return ActivityService._sorted(events)

    # ---- invoice events ----------------------------------------------

    @staticmethod
    def _invoice_events(cutoff):
        events = []
        for inv in Invoice.objects.filter(sent_date__gte=cutoff).select_related('job'):
            events.append({
                'kind': 'sent',
                'invoice_id': inv.pk,
                'invoice_number': inv.invoice_number,
                'display_number': inv.display_number,
                'date': _date(inv.sent_date),
                '_sort': inv.sent_date,
            })
        paid = Invoice.objects.filter(
            closed_date__gte=cutoff, status=Invoice.STATUS_PAID,
        ).select_related('job')
        for inv in paid:
            events.append({
                'kind': 'paid',
                'invoice_id': inv.pk,
                'invoice_number': inv.invoice_number,
                'display_number': inv.display_number,
                'date': _date(inv.closed_date),
                '_sort': inv.closed_date,
            })
        return ActivityService._sorted(events)

    # ---- helpers -----------------------------------------------------

    @staticmethod
    def _sorted(events):
        """Newest-first by the event's underlying timestamp, then strip it."""
        events.sort(key=lambda e: e['_sort'], reverse=True)
        for e in events:
            e.pop('_sort', None)
        return events

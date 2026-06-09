from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.models import HistoryEntry, User
from apps.jobs.models import Job, Task
from apps.estimates.models import Estimate, ChangeOrder
from apps.invoicing.models import Invoice
from apps.deliverables.models import Deliverable, Shipment
from apps.inventory.models import Material


class Command(BaseCommand):
    """Synthesize realistic HistoryEntry rows for ONE job so the Job History
    page can be evaluated against data that reads like genuine history.

    Each related record contributes:
      - a `_created` audit entry, anchored to the record's REAL creation date
        (Task/Material have no stored creation date, so they're anchored to the
        Job's start_date — falling back to created_date — which guarantees a
        child never appears to predate its Job);
      - lifecycle `action` entries driven by the record's real date fields
        (sent_date -> "sent to the customer", closed_date -> accepted/paid, the
        Job's own status path stamped at created_date/start_date/completed_date);
      - one illustrative field-diff `audit` entry (e.g. Job name, Material
        quantity) — the prior value is fabricated, since no real history exists.

    Every row is marked `changes["_backfill"] = True` so `--clear` can remove
    exactly them. NOT idempotent — run with --clear before re-running, or
    entries stack. NEVER run against data you care about.
    """

    help = (
        'Synthesize realistic, date-anchored HistoryEntry rows for ONE job so '
        'the Job History page can be evaluated. Marked changes["_backfill"]=True '
        'so --clear removes them. NOT idempotent — --clear before re-running. '
        'NEVER run against data you care about.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--job', required=True, help='Job pk')
        parser.add_argument('--clear', action='store_true',
                            help='Delete previously backfilled entries for this job instead of creating.')

    def handle(self, *args, **opts):
        try:
            job = Job.objects.get(pk=opts['job'])
        except Job.DoesNotExist:
            raise CommandError(f'Job {opts["job"]} not found')

        if opts['clear']:
            n = self._clear(job)
            self.stdout.write(self.style.SUCCESS(f'Cleared {n} backfilled entries for job {job.pk}'))
            return

        user = User.objects.order_by('pk').first()
        if user is None:
            raise CommandError('No users in database — load fixtures first.')
        created = self._backfill(job, user)
        self.stdout.write(self.style.SUCCESS(f'Created {created} backfilled entries for job {job.pk}'))

    # ------------------------------------------------------------------
    # Related records (one source of truth for both backfill and clear)
    # ------------------------------------------------------------------
    def _related(self, job):
        return [
            ('job', [job]),
            ('estimate', list(Estimate.objects.filter(job=job))),
            ('changeorder', list(ChangeOrder.objects.filter(job=job))),
            ('invoice', list(Invoice.objects.filter(job=job))),
            ('task', list(Task.objects.filter(job=job))),
            ('deliverable', list(Deliverable.objects.filter(job=job))),
            ('shipment', list(Shipment.objects.filter(job=job))),
            ('material', list(Material.objects.filter(job=job))),
        ]

    def _clear(self, job):
        total = 0
        for object_type, objs in self._related(job):
            ids = [o.pk for o in objs]
            if not ids:
                continue
            qs = HistoryEntry.objects.filter(
                object_type=object_type, object_id__in=ids, changes___backfill=True,
            )
            total += qs.count()
            qs.delete()
        return total

    def _backfill(self, job, user):
        builders = {
            'job': self._job_events,
            'estimate': self._document_events,
            'changeorder': self._document_events,
            'invoice': self._document_events,
            'task': self._task_events,
            'deliverable': self._deliverable_events,
            'shipment': self._shipment_events,
            'material': self._material_events,
        }
        # Gather every event across all records, then order them globally.
        events = []  # (when, object_type, obj_id, entry_type, changes)
        for object_type, objs in self._related(job):
            builder = builders[object_type]
            for obj in objs:
                for when, entry_type, changes in builder(obj, job):
                    events.append((when, object_type, obj.pk, entry_type, changes))

        # Chronological order; ties break by the _related() group order (job
        # before its estimates before tasks ...), which is a plausible sequence.
        events.sort(key=lambda e: e[0])

        # Force at least a minute between consecutive entries so nothing lands on
        # an identical timestamp (which sorts unpredictably and reads as noise).
        created = 0
        prev = None
        for when, object_type, obj_id, entry_type, changes in events:
            if prev is not None and when < prev + timedelta(minutes=1):
                when = prev + timedelta(minutes=1)
            prev = when
            created += self._entry(
                object_type, obj_id, user, when, entry_type=entry_type,
                changes={**changes, '_backfill': True},
            )
        return created

    # ------------------------------------------------------------------
    # Per-type event builders -> list of (when, entry_type, changes)
    # ------------------------------------------------------------------
    def _job_events(self, job, _):
        base = job.created_date
        start = job.start_date
        done = job.completed_date
        evs = [(base, 'audit', {'_created': True})]
        if job.name:
            evs.append((self._shift(base, hours=6), 'audit',
                        {'name': {'old': '(untitled)', 'new': job.name}}))
        if job.status != Job.STATUS_DRAFT:
            evs.append((self._mid(base, start) or self._shift(base, days=1), 'action',
                        {'status': {'old': 'draft', 'new': 'submitted'},
                         '_action': 'Submitted for approval'}))
        if start:
            evs.append((start, 'action',
                        {'status': {'old': 'submitted', 'new': 'approved'},
                         '_action': 'Approved — released to the floor'}))
            evs.append((self._shift(start, hours=2), 'action',
                        {'status': {'old': 'approved', 'new': 'in_progress'},
                         '_action': 'Work started on the floor'}))
        if job.status == Job.STATUS_COMPLETED and done:
            evs.append((self._shift(done, hours=-2), 'action',
                        {'status': {'old': 'in_progress', 'new': 'work_complete'},
                         '_action': 'Work completed'}))
            evs.append((done, 'action',
                        {'status': {'old': 'work_complete', 'new': 'completed'},
                         '_action': 'Job closed out'}))
        return self._clamp_sorted(evs, base)

    def _document_events(self, doc, job):
        noun = {'Estimate': 'Estimate', 'ChangeOrder': 'Change order',
                'Invoice': 'Invoice'}[type(doc).__name__]
        base = doc.created_date
        evs = [(base, 'audit', {'_created': True})]
        sent = getattr(doc, 'sent_date', None)
        if sent:
            evs.append((sent, 'action',
                        {'status': {'old': 'draft', 'new': 'open'},
                         '_action': f'{noun} sent to the customer'}))
        closed = getattr(doc, 'closed_date', None)
        if closed:
            evs.append((closed, 'action',
                        {'status': {'old': 'open', 'new': doc.status},
                         '_action': self._closure_label(noun, doc.status)}))
        return self._clamp_sorted(evs, base)

    def _closure_label(self, noun, status):
        return {
            'accepted': f'{noun} accepted by the customer',
            'rejected': f'{noun} rejected by the customer',
            'paid': f'{noun} paid in full',
            'paid_in_full': f'{noun} paid in full',
            'expired': f'{noun} expired',
            'superseded': f'{noun} superseded by a revision',
            'cancelled': f'{noun} cancelled',
        }.get(status, f'{noun} closed ({status})')

    def _task_events(self, task, job):
        anchor = job.start_date or job.created_date
        evs = [(anchor, 'audit', {'_created': True})]
        if task.status and task.status != Task.STATUS_PENDING:
            when = job.completed_date or self._shift(anchor, days=5)
            evs.append((when, 'audit',
                        {'status': {'old': Task.STATUS_PENDING, 'new': task.status}}))
        return self._clamp_sorted(evs, anchor)

    def _material_events(self, mat, job):
        anchor = job.start_date or job.created_date
        evs = [
            (anchor, 'audit', {'_created': True}),
            (self._shift(anchor, days=1), 'audit',
             {'quantity': {'old': str(mat.quantity + 1), 'new': str(mat.quantity)}}),
        ]
        if mat.consumption_state == Material.CONSUMPTION_STATE_CONSUMED:
            when = job.completed_date or self._shift(anchor, days=4)
            evs.append((when, 'audit',
                        {'consumption_state': {'old': 'pending', 'new': 'consumed'}}))
        return self._clamp_sorted(evs, anchor)

    def _deliverable_events(self, d, job):
        base = d.created_at
        evs = [
            (base, 'audit', {'_created': True}),
            (self._shift(base, days=1), 'audit',
             {'qty_ordered': {'old': str(d.qty_ordered + 1), 'new': str(d.qty_ordered)}}),
        ]
        return self._clamp_sorted(evs, base)

    def _shipment_events(self, s, job):
        base = s.created_at or s.prepared_date
        evs = [(base, 'audit', {'_created': True})]
        if getattr(s, 'picked_up_date', None):
            evs.append((s.picked_up_date, 'action',
                        {'status': {'old': 'prepared', 'new': 'picked_up'},
                         '_action': 'Shipment picked up'}))
        return self._clamp_sorted(evs, base)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _shift(self, when, days=0, hours=0):
        if when is None:
            return None
        return when + timedelta(days=days, hours=hours)

    def _mid(self, a, b):
        if a is None or b is None:
            return None
        return a + (b - a) / 2

    def _clamp_sorted(self, events, floor):
        out = []
        for when, entry_type, changes in events:
            if when is None:
                continue
            if floor is not None and when < floor:
                when = floor
            out.append((when, entry_type, changes))
        out.sort(key=lambda e: e[0])
        return out

    def _entry(self, object_type, obj_id, user, when, entry_type='audit', changes=None):
        entry = HistoryEntry.objects.create(
            entry_type=entry_type, object_type=object_type, object_id=obj_id,
            user=user, changes=changes or {},
        )
        # timestamp is auto_now_add — backdate via update() (HistoryEntry is not
        # @history-tracked and has no custom save, so update() is safe here).
        HistoryEntry.objects.filter(pk=entry.pk).update(timestamp=when)
        return 1

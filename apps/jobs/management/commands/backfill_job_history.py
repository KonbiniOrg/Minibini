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
    help = (
        'Synthesize representative HistoryEntry rows for ONE job so the Job '
        'History page can be evaluated. Marked with changes["_backfill"]=True '
        'so --clear can remove them. NOT idempotent — run with --clear before '
        're-running, or entries will stack. NEVER run against data you care about.'
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

    def _object_ids(self, job):
        return [
            ('job', [job.pk]),
            ('estimate', list(Estimate.objects.filter(job=job).values_list('pk', flat=True))),
            ('changeorder', list(ChangeOrder.objects.filter(job=job).values_list('pk', flat=True))),
            ('invoice', list(Invoice.objects.filter(job=job).values_list('pk', flat=True))),
            ('task', list(Task.objects.filter(job=job).values_list('pk', flat=True))),
            ('deliverable', list(Deliverable.objects.filter(job=job).values_list('pk', flat=True))),
            ('shipment', list(Shipment.objects.filter(job=job).values_list('pk', flat=True))),
            ('material', list(Material.objects.filter(job=job).values_list('pk', flat=True))),
        ]

    def _clear(self, job):
        total = 0
        for object_type, ids in self._object_ids(job):
            if not ids:
                continue
            qs = HistoryEntry.objects.filter(
                object_type=object_type, object_id__in=ids, changes___backfill=True,
            )
            total += qs.count()
            qs.delete()
        return total

    def _backfill(self, job, user):
        now = timezone.now()
        created = 0
        day = 0
        for object_type, ids in self._object_ids(job):
            for obj_id in ids:
                created += self._entry(object_type, obj_id, user, now - timedelta(days=day + 30),
                                       changes={'_created': True, '_backfill': True})
                created += self._entry(object_type, obj_id, user, now - timedelta(days=day + 15),
                                       entry_type='action',
                                       changes={'_action': f'Backfilled activity on {object_type}',
                                                '_backfill': True})
                day += 1
        return created

    def _entry(self, object_type, obj_id, user, when, entry_type='audit', changes=None):
        entry = HistoryEntry.objects.create(
            entry_type=entry_type, object_type=object_type, object_id=obj_id,
            user=user, changes=changes or {},
        )
        HistoryEntry.objects.filter(pk=entry.pk).update(timestamp=when)
        return 1

from datetime import timedelta

from django.utils import timezone

from apps.core.models import User, Configuration, Shift
from apps.jobs.models import Blep, Job, Task
from apps.estimates.models import Estimate
from apps.purchasing.models import PurchaseOrder
from apps.invoicing.models import Invoice
from apps.contacts.models import Business
from apps.activity.services import ActivityService
from tests.base import BaseTestCase


class ActivityServiceTest(BaseTestCase):
    """Service-level tests for the Activity dashboard payload.

    Fixture provides: Job 1 (JOB-2024-0001), Tasks 1 & 2 on Job 1,
    Business 1 (ABC Corporation), Contact 2 (has business), users
    admin/manager1/johnq.
    """

    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.user = User.objects.get(username='johnq')
        self.job = Job.objects.get(pk=1)
        self.task = Task.objects.get(pk=1)
        self.business = Business.objects.get(pk=1)
        # Default window of 5 days comes from the unit_test_data fixture
        # (core.configuration activity_recent_days=5); tests override it
        # explicitly where they need a different window.

    # ---- on_shift / current blep -------------------------------------

    def test_open_shift_with_open_blep_populates_current_blep(self):
        Shift.objects.create(
            user=self.user, start_time=self.now - timedelta(hours=2),
        )
        Blep.objects.create(
            user=self.user, task=self.task,
            start_time=self.now - timedelta(minutes=30), end_time=None,
        )
        data = ActivityService.get_activity()
        self.assertEqual(len(data['on_shift']), 1)
        card = data['on_shift'][0]
        self.assertEqual(card['user_id'], self.user.pk)
        self.assertIsNotNone(card['shift_start'])
        cb = card['current_blep']
        self.assertIsNotNone(cb)
        self.assertEqual(cb['task_id'], self.task.pk)
        self.assertEqual(cb['task_name'], self.task.name)
        self.assertEqual(cb['job_id'], self.job.pk)
        self.assertEqual(cb['job_number'], self.job.job_number)

    def test_open_shift_without_open_blep_is_idle(self):
        Shift.objects.create(
            user=self.user, start_time=self.now - timedelta(hours=2),
        )
        data = ActivityService.get_activity()
        self.assertEqual(len(data['on_shift']), 1)
        self.assertIsNone(data['on_shift'][0]['current_blep'])

    def test_multiple_open_bleps_surfaces_most_recent(self):
        # A user with two open bleps: current_blep must be the most recently
        # started one (locks the -start_time dedup in _on_shift).
        Shift.objects.create(
            user=self.user, start_time=self.now - timedelta(hours=4),
        )
        task2 = Task.objects.get(pk=2)
        Blep.objects.create(
            user=self.user, task=self.task,
            start_time=self.now - timedelta(hours=3), end_time=None,
        )
        newer = Blep.objects.create(
            user=self.user, task=task2,
            start_time=self.now - timedelta(minutes=10), end_time=None,
        )
        data = ActivityService.get_activity()
        self.assertEqual(len(data['on_shift']), 1)
        cb = data['on_shift'][0]['current_blep']
        self.assertIsNotNone(cb)
        self.assertEqual(cb['task_id'], newer.task_id)
        self.assertEqual(cb['blep_start'], newer.start_time.isoformat())

    def test_closed_shift_does_not_appear_on_shift(self):
        Shift.objects.create(
            user=self.user, start_time=self.now - timedelta(hours=3),
            end_time=self.now - timedelta(hours=1),
        )
        data = ActivityService.get_activity()
        self.assertEqual(data['on_shift'], [])

    # ---- completed bleps ---------------------------------------------

    def test_closed_blep_inside_cutoff_appears(self):
        Blep.objects.create(
            user=self.user, task=self.task,
            start_time=self.now - timedelta(days=1, hours=1),
            end_time=self.now - timedelta(days=1),
        )
        data = ActivityService.get_activity()
        self.assertEqual(len(data['completed_bleps']), 1)
        # completed_bleps reuse the BlepSerializer field shape (task FK pk).
        self.assertEqual(data['completed_bleps'][0]['task'], self.task.pk)

    def test_closed_blep_outside_cutoff_excluded(self):
        Blep.objects.create(
            user=self.user, task=self.task,
            start_time=self.now - timedelta(days=10),
            end_time=self.now - timedelta(days=9),
        )
        data = ActivityService.get_activity()
        self.assertEqual(data['completed_bleps'], [])

    def test_open_blep_never_in_completed(self):
        Blep.objects.create(
            user=self.user, task=self.task,
            start_time=self.now - timedelta(minutes=20), end_time=None,
        )
        data = ActivityService.get_activity()
        self.assertEqual(data['completed_bleps'], [])

    def test_completed_bleps_newest_first(self):
        older = Blep.objects.create(
            user=self.user, task=self.task,
            start_time=self.now - timedelta(days=3, hours=1),
            end_time=self.now - timedelta(days=3),
        )
        newer = Blep.objects.create(
            user=self.user, task=self.task,
            start_time=self.now - timedelta(days=1, hours=1),
            end_time=self.now - timedelta(days=1),
        )
        data = ActivityService.get_activity()
        ids = [b['blep_id'] for b in data['completed_bleps']]
        self.assertEqual(ids, [newer.pk, older.pk])

    # ---- estimate / job events ---------------------------------------

    def test_estimate_sent_inside_window_appears(self):
        est = Estimate.objects.create(
            job=self.job, estimate_number='EST-X', version=1,
            status=Estimate.STATUS_OPEN,
            sent_date=self.now - timedelta(days=2),
        )
        data = ActivityService.get_activity()
        kinds = [(e['kind'], e.get('estimate_id')) for e in data['job_events']]
        self.assertIn(('estimate_sent', est.pk), kinds)

    def test_estimate_sent_outside_window_excluded(self):
        Estimate.objects.create(
            job=self.job, estimate_number='EST-Y', version=1,
            status=Estimate.STATUS_OPEN,
            sent_date=self.now - timedelta(days=20),
        )
        data = ActivityService.get_activity()
        self.assertEqual(
            [e for e in data['job_events'] if e['kind'] == 'estimate_sent'],
            [],
        )

    def test_job_approved_inside_window_appears(self):
        self.job.start_date = self.now - timedelta(days=1)
        self.job.save()
        data = ActivityService.get_activity()
        approved = [e for e in data['job_events'] if e['kind'] == 'job_approved']
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]['job_id'], self.job.pk)
        self.assertEqual(approved[0]['job_number'], self.job.job_number)

    def test_job_approved_outside_window_excluded(self):
        self.job.start_date = self.now - timedelta(days=30)
        self.job.save()
        data = ActivityService.get_activity()
        self.assertEqual(
            [e for e in data['job_events'] if e['kind'] == 'job_approved'],
            [],
        )

    def test_job_events_newest_first(self):
        # estimate sent 4 days ago, job approved 1 day ago -> approved first.
        Estimate.objects.create(
            job=self.job, estimate_number='EST-Z', version=1,
            status=Estimate.STATUS_OPEN,
            sent_date=self.now - timedelta(days=4),
        )
        self.job.start_date = self.now - timedelta(days=1)
        self.job.save()
        data = ActivityService.get_activity()
        kinds = [e['kind'] for e in data['job_events']]
        self.assertEqual(kinds[0], 'job_approved')
        self.assertEqual(kinds[1], 'estimate_sent')

    # ---- PO events ----------------------------------------------------

    def test_po_sent_and_received_events(self):
        po = PurchaseOrder.objects.create(
            business=self.business, po_number='PO-A',
            status=PurchaseOrder.STATUS_RECEIVED_IN_FULL,
            issued_date=self.now - timedelta(days=3),
            received_date=self.now - timedelta(days=1),
        )
        data = ActivityService.get_activity()
        kinds = {(e['kind'], e['po_id']) for e in data['po_events']}
        self.assertIn(('sent', po.pk), kinds)
        self.assertIn(('received', po.pk), kinds)

    def test_po_events_outside_window_excluded(self):
        PurchaseOrder.objects.create(
            business=self.business, po_number='PO-B',
            status=PurchaseOrder.STATUS_ISSUED,
            issued_date=self.now - timedelta(days=40),
        )
        data = ActivityService.get_activity()
        self.assertEqual(data['po_events'], [])

    # ---- invoice events ----------------------------------------------

    def test_invoice_sent_event(self):
        inv = Invoice.objects.create(
            job=self.job, invoice_number='INV-A',
            status=Invoice.STATUS_OPEN,
            sent_date=self.now - timedelta(days=2),
        )
        data = ActivityService.get_activity()
        kinds = {(e['kind'], e['invoice_id']) for e in data['invoice_events']}
        self.assertIn(('sent', inv.pk), kinds)

    def test_invoice_paid_in_full_event(self):
        inv = Invoice.objects.create(
            job=self.job, invoice_number='INV-B',
            status=Invoice.STATUS_PAID,
            sent_date=self.now - timedelta(days=3),
            closed_date=self.now - timedelta(days=1),
        )
        data = ActivityService.get_activity()
        paid = [e for e in data['invoice_events'] if e['kind'] == 'paid']
        self.assertEqual(len(paid), 1)
        self.assertEqual(paid[0]['invoice_id'], inv.pk)

    def test_partly_paid_invoice_not_paid_event(self):
        # partly-paid: closed_date is null, status not PAID -> no paid event.
        Invoice.objects.create(
            job=self.job, invoice_number='INV-C',
            status=Invoice.STATUS_PARTLY_PAID,
            sent_date=self.now - timedelta(days=2),
            closed_date=None,
        )
        data = ActivityService.get_activity()
        self.assertEqual(
            [e for e in data['invoice_events'] if e['kind'] == 'paid'], [],
        )

    # ---- cutoff / config ---------------------------------------------

    def test_cutoff_honors_config_value(self):
        Configuration.objects.update_or_create(
            key='activity_recent_days', defaults={'value': '2'},
        )
        # Blep closed 3 days ago: outside a 2-day window.
        Blep.objects.create(
            user=self.user, task=self.task,
            start_time=self.now - timedelta(days=3, hours=1),
            end_time=self.now - timedelta(days=3),
        )
        data = ActivityService.get_activity()
        self.assertEqual(data['recent_days'], 2)
        self.assertEqual(data['completed_bleps'], [])

    def test_default_recent_days_when_key_absent(self):
        Configuration.objects.filter(key='activity_recent_days').delete()
        data = ActivityService.get_activity()
        self.assertEqual(data['recent_days'], 5)

    def test_invalid_config_falls_back_to_default(self):
        Configuration.objects.update_or_create(
            key='activity_recent_days', defaults={'value': 'garbage'},
        )
        data = ActivityService.get_activity()
        self.assertEqual(data['recent_days'], 5)

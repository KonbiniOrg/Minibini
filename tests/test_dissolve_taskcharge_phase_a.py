from decimal import Decimal
from django.test import TestCase
from django.db import connection

from apps.jobs.models import Task, TaskCharge, RateScheme, Job
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory


class PhaseABackfillTest(TestCase):
    """After Phase A, every Task must have rate_scheme/active_modifiers/actual_qty
    backfilled from its TaskCharge."""

    def setUp(self):
        ac = AccountingCategory.objects.create(name='Labor')
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50.00'), unit_label='hour',
            accounting_category=ac,
        )
        # Business requires a default_contact; create Contact first without biz,
        # then create Business with default_contact, then link contact to biz.
        contact = Contact.objects.create(first_name='A', last_name='B')
        biz = Business.objects.create(business_name='Acme', default_contact=contact)
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(
            job_number='JOB-2026-0001', contact=contact, status=Job.STATUS_DRAFT,
        )

    def test_backfill_copies_rate_scheme_from_taskcharge(self):
        # Create Task without going through Phase B paths — set fields manually
        # to simulate Phase A starting state (TaskCharge has values, Task does not).
        task = Task.objects.create(job=self.job, name='Bench work')
        TaskCharge.objects.create(
            task=task, rate_scheme=self.scheme,
            active_modifiers=['messy'],
            actuals={'qty': '5.5'},
        )
        # Pre-condition: Task has no billing fields populated.
        task.refresh_from_db()
        self.assertIsNone(task.rate_scheme_id)
        self.assertEqual(task.active_modifiers, [])
        self.assertIsNone(task.actual_qty)

        # Run the backfill (idempotent — call same logic the migration uses).
        from apps.jobs.migrations import _phase_a_backfill_helper
        _phase_a_backfill_helper.run(Task, TaskCharge)

        task.refresh_from_db()
        self.assertEqual(task.rate_scheme_id, self.scheme.pk)
        self.assertEqual(task.active_modifiers, ['messy'])
        self.assertEqual(task.actual_qty, Decimal('5.5'))

    def test_backfill_handles_missing_actuals_qty(self):
        task = Task.objects.create(job=self.job, name='Flat fee')
        scheme_flat = RateScheme.objects.create(
            name='Setup', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('100.00'), unit_label='job',
            accounting_category=self.scheme.accounting_category,
        )
        TaskCharge.objects.create(
            task=task, rate_scheme=scheme_flat,
            active_modifiers=[], actuals={},
        )

        from apps.jobs.migrations import _phase_a_backfill_helper
        _phase_a_backfill_helper.run(Task, TaskCharge)

        task.refresh_from_db()
        self.assertEqual(task.rate_scheme_id, scheme_flat.pk)
        self.assertIsNone(task.actual_qty)

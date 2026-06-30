from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.jobs.models import PlanTask, RateScheme, Job, Task
from apps.estimates.models import EstWorksheet
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory


class PlanTaskEstQtyRequiredTest(TestCase):
    """PlanTask.clean() rejects null est_qty at the application layer.
    Task.clean() accepts null est_qty (asymmetric enforcement).
    """

    def setUp(self):
        ac = AccountingCategory.objects.create(name='Labor')
        self.scheme = RateScheme.objects.create(
            name='Setup', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('100.00'), unit_label='job',
            accounting_category=ac,
        )
        # Business/Contact circular FK pattern
        contact = Contact.objects.create(first_name='A', last_name='B')
        biz = Business.objects.create(business_name='X', default_contact=contact)
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(
            job_number='JOB-PT1', contact=contact, status=Job.STATUS_DRAFT,
        )
        self.ws = EstWorksheet.objects.create(job=self.job)

    def test_plantask_rejects_null_est_qty(self):
        with self.assertRaises(ValidationError) as cm:
            PlanTask.objects.create(
                est_worksheet=self.ws, name='Bad',
                rate_scheme=self.scheme, est_qty=None,
            )
        self.assertIn('est_qty', cm.exception.message_dict)

    def test_plantask_accepts_non_null_est_qty(self):
        pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Good',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        self.assertEqual(pt.est_qty, Decimal('1'))

    def test_task_accepts_null_est_qty(self):
        # Task is the asymmetric side — null is fine.
        # B4 removed the hasattr(self, 'charge') guard, so no TaskCharge needed.
        t = Task.objects.create(
            job=self.job, name='Looser',
            rate_scheme=self.scheme,
            est_qty=None,
        )
        self.assertIsNone(t.est_qty)

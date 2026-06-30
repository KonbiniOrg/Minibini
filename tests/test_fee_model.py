from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import Fee, Job
from apps.core.models import AccountingCategory
from apps.contacts.models import Contact


class FeeModelTest(TestCase):
    def setUp(self):
        # Contact is required (non-nullable FK on Job)
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Customer', email='test@example.com'
        )
        self.ac = AccountingCategory.objects.create(name='Services', code='SVC')
        self.job = Job.objects.create(
            job_number='JOB-T-1', status=Job.STATUS_DRAFT, contact=self.contact
        )

    def test_compute_amount_is_quantity_times_unit_rate(self):
        fee = Fee.objects.create(job=self.job, description='Delivery',
                                 quantity=Decimal('3'), unit_rate=Decimal('50.00'),
                                 accounting_category=self.ac)
        self.assertEqual(fee.compute_amount(), Decimal('150.00'))

    def test_units_is_none_and_category_passthrough(self):
        fee = Fee.objects.create(job=self.job, description='Setup',
                                 quantity=Decimal('1'), unit_rate=Decimal('120.00'),
                                 accounting_category=self.ac)
        self.assertEqual(fee.units, 'none')
        self.assertEqual(fee.effective_accounting_category, self.ac)

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.jobs.models import Fee, Job
from apps.jobs.services import FeeService
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

    def test_fee_has_no_task_field(self):
        self.assertFalse(hasattr(Fee, 'task'))

    def test_negative_unit_rate_computes_negative_amount(self):
        """A credit is a negative Fee: negative unit_rate is allowed and
        compute_amount() reflects the sign."""
        fee = Fee.objects.create(job=self.job, description='Discount',
                                 quantity=Decimal('2'), unit_rate=Decimal('-25.00'),
                                 accounting_category=self.ac)
        self.assertEqual(fee.compute_amount(), Decimal('-50.00'))


class FeeServiceSignedAmountTest(TestCase):
    """FeeService.create_on_job/update accept negative unit_rate but reject
    zero (a Fee that charges nothing is meaningless)."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Customer', email='test2@example.com'
        )
        self.ac = AccountingCategory.objects.create(name='Services2', code='SVC2')
        self.job = Job.objects.create(
            job_number='JOB-T-2', status=Job.STATUS_DRAFT, contact=self.contact
        )

    def test_create_on_job_accepts_negative_unit_rate(self):
        fee = FeeService.create_on_job(
            self.job, description='Credit', quantity=Decimal('1'),
            unit_rate=Decimal('-10.00'), accounting_category=self.ac,
        )
        self.assertEqual(fee.unit_rate, Decimal('-10.00'))
        self.assertEqual(fee.compute_amount(), Decimal('-10.00'))

    def test_create_on_job_rejects_zero_unit_rate(self):
        with self.assertRaises(ValidationError) as ctx:
            FeeService.create_on_job(
                self.job, description='Zero', quantity=Decimal('1'),
                unit_rate=Decimal('0.00'), accounting_category=self.ac,
            )
        self.assertIn('unit_rate', ctx.exception.message_dict)

    def test_update_rejects_zero_unit_rate(self):
        fee = FeeService.create_on_job(
            self.job, description='Starts fine', quantity=Decimal('1'),
            unit_rate=Decimal('10.00'), accounting_category=self.ac,
        )
        with self.assertRaises(ValidationError):
            FeeService.update(fee.pk, unit_rate=Decimal('0.00'))

    def test_update_accepts_negative_unit_rate(self):
        fee = FeeService.create_on_job(
            self.job, description='Starts fine', quantity=Decimal('1'),
            unit_rate=Decimal('10.00'), accounting_category=self.ac,
        )
        updated = FeeService.update(fee.pk, unit_rate=Decimal('-5.00'))
        self.assertEqual(updated.unit_rate, Decimal('-5.00'))


class FeeServiceQuantityValidationTest(TestCase):
    """FeeService.create_on_job/update reject quantity <= 0 (Phase 3 Task 6):
    zero always zeroes compute_amount() regardless of unit_rate, and
    negative quantity would silently flip a charge/credit's sign instead of
    the caller using unit_rate's own sign for that (the credit convention
    already covers negative amounts)."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Customer', email='test3@example.com'
        )
        self.ac = AccountingCategory.objects.create(name='Services3', code='SVC3')
        self.job = Job.objects.create(
            job_number='JOB-T-3', status=Job.STATUS_DRAFT, contact=self.contact
        )

    def test_create_on_job_rejects_zero_quantity(self):
        with self.assertRaises(ValidationError) as ctx:
            FeeService.create_on_job(
                self.job, description='Zero qty', quantity=Decimal('0'),
                unit_rate=Decimal('10.00'), accounting_category=self.ac,
            )
        self.assertIn('quantity', ctx.exception.message_dict)

    def test_create_on_job_rejects_negative_quantity(self):
        with self.assertRaises(ValidationError) as ctx:
            FeeService.create_on_job(
                self.job, description='Negative qty', quantity=Decimal('-2'),
                unit_rate=Decimal('10.00'), accounting_category=self.ac,
            )
        self.assertIn('quantity', ctx.exception.message_dict)

    def test_create_on_job_accepts_positive_quantity(self):
        fee = FeeService.create_on_job(
            self.job, description='Fine', quantity=Decimal('3'),
            unit_rate=Decimal('10.00'), accounting_category=self.ac,
        )
        self.assertEqual(fee.quantity, Decimal('3'))

    def test_update_rejects_zero_quantity(self):
        fee = FeeService.create_on_job(
            self.job, description='Starts fine', quantity=Decimal('1'),
            unit_rate=Decimal('10.00'), accounting_category=self.ac,
        )
        with self.assertRaises(ValidationError) as ctx:
            FeeService.update(fee.pk, quantity=Decimal('0'))
        self.assertIn('quantity', ctx.exception.message_dict)

    def test_update_rejects_negative_quantity(self):
        fee = FeeService.create_on_job(
            self.job, description='Starts fine', quantity=Decimal('1'),
            unit_rate=Decimal('10.00'), accounting_category=self.ac,
        )
        with self.assertRaises(ValidationError) as ctx:
            FeeService.update(fee.pk, quantity=Decimal('-1'))
        self.assertIn('quantity', ctx.exception.message_dict)

    def test_update_accepts_positive_quantity(self):
        fee = FeeService.create_on_job(
            self.job, description='Starts fine', quantity=Decimal('1'),
            unit_rate=Decimal('10.00'), accounting_category=self.ac,
        )
        updated = FeeService.update(fee.pk, quantity=Decimal('4'))
        self.assertEqual(updated.quantity, Decimal('4'))

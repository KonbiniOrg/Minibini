from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import RateScheme, PlanTask, Job, TaskCharge
from apps.jobs.services import JobService
from apps.estimates.models import EstWorksheet
from apps.core.models import AccountingCategory
from apps.contacts.models import Contact


class CopyFromWorksheetChargeTest(TestCase):

    def setUp(self):
        self.category = AccountingCategory.objects.create(
            code='LAB', name='Labor', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='test@test.com',
        )
        self.job = Job.objects.create(
            name='Test Job', job_number='TEST-001', status='approved',
            contact=self.contact,
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status='final',
        )
        self.scheme = RateScheme.objects.create(
            name='CNC Router Copy Test',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='minute',
            modifiers=[
                {'key': 'messy', 'label': 'Messy', 'percent': 10},
            ],
        )

    def test_copy_creates_task_charge_from_plan_task_billing(self):
        plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='CNC cut panels',
            accounting_category=self.category,
            rate_scheme=self.scheme,
            active_modifiers=['messy'],
            estimated_billable_qty=Decimal('30.00'),
        )

        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)

        task = self.job.tasks.get(name='CNC cut panels')
        self.assertTrue(hasattr(task, 'charge'))
        charge = task.charge
        self.assertEqual(charge.rate_scheme, self.scheme)
        self.assertEqual(charge.active_modifiers, ['messy'])
        self.assertEqual(charge.actuals, {})

    def test_copy_without_billing_creates_no_task_charge(self):
        PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Manual task',
            accounting_category=self.category,
        )

        JobService.copy_from_worksheet(self.job.pk, self.worksheet.pk)

        task = self.job.tasks.get(name='Manual task')
        self.assertFalse(TaskCharge.objects.filter(task=task).exists())

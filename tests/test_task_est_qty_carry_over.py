from decimal import Decimal
from django.test import TestCase

from apps.jobs.models import Task, PlanTask, RateScheme, Job
from apps.jobs.services import JobService
from apps.estimates.models import EstWorksheet, ServiceItem
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory


class TaskEstQtyCarryOverTest(TestCase):
    """ServiceItem.generate_task persists est_qty and honors name/description overrides."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Labor')
        c = Contact.objects.create(first_name='A', last_name='B')
        biz = Business.objects.create(business_name='Y', default_contact=c)
        c.business = biz
        c.save()
        self.job = Job.objects.create(
            job_number='JOB-CO1', contact=c, status=Job.STATUS_APPROVED,
        )
        self.ws = EstWorksheet.objects.create(job=self.job)

    def test_template_generate_task_for_job_persists_est_qty(self):
        scheme = RateScheme.objects.create(
            name='T', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('100'), unit_label='job',
            accounting_category=self.ac,
        )
        template = ServiceItem.objects.create(
            template_name='Setup',
            rate_scheme=scheme,
        )
        task = template.generate_task(self.job, est_qty=Decimal('3'))
        self.assertEqual(task.est_qty, Decimal('3'))
        self.assertEqual(task.rate_scheme_id, scheme.pk)

    def test_template_generate_task_honors_name_and_description_overrides(self):
        """User-entered name and description must survive the template-add path."""
        scheme = RateScheme.objects.create(
            name='Hourly-O', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('75'), unit_label='hour',
            accounting_category=self.ac,
        )
        template = ServiceItem.objects.create(
            template_name='Default Template Name',
            rate_scheme=scheme,
        )
        template.description = 'Default template description'
        template.save()

        # Override both name and description
        task = template.generate_task(
            self.job,
            est_qty=Decimal('1'),
            name='Custom Name',
            description='Custom Desc',
        )
        self.assertEqual(task.name, 'Custom Name')
        self.assertEqual(task.description, 'Custom Desc')

        # Empty name falls back to template default
        task2 = template.generate_task(
            self.job,
            est_qty=Decimal('1'),
            name='',
            description='Another desc',
        )
        self.assertEqual(task2.name, 'Default Template Name')
        self.assertEqual(task2.description, 'Another desc')

        # description=None falls back to template default
        task3 = template.generate_task(
            self.job,
            est_qty=Decimal('1'),
            name='Override Name',
            description=None,
        )
        self.assertEqual(task3.name, 'Override Name')
        self.assertEqual(task3.description, 'Default template description')

        # Empty description is preserved (deliberate blank override)
        task4 = template.generate_task(
            self.job,
            est_qty=Decimal('1'),
            name='Name4',
            description='',
        )
        self.assertEqual(task4.name, 'Name4')
        self.assertEqual(task4.description, '')

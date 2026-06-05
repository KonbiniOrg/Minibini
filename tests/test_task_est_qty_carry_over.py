from decimal import Decimal
from django.test import TestCase

from apps.jobs.models import Task, PlanTask, RateScheme, Job
from apps.jobs.services import JobService
from apps.estimates.models import EstWorksheet, TaskTemplate
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory


class TaskEstQtyCarryOverTest(TestCase):
    """Phase B carry-over: PlanTask.est_qty lands on Task.est_qty for ALL algorithms."""

    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Labor')
        c = Contact.objects.create(first_name='A', last_name='B')
        biz = Business.objects.create(business_name='Y', default_contact=c)
        c.business = biz
        c.save()
        self.job = Job.objects.create(
            job_number='JOB-CO1', contact=c, status=Job.STATUS_DRAFT,
        )
        self.ws = EstWorksheet.objects.create(job=self.job)

    def _create_pt(self, scheme, est_qty):
        return PlanTask.objects.create(
            est_worksheet=self.ws, name='X',
            rate_scheme=scheme, active_modifiers=[],
            est_qty=est_qty,
        )

    def test_carry_over_elapsed_time_sets_task_est_qty(self):
        scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50'), unit_label='hour',
            accounting_category=self.ac,
        )
        pt = self._create_pt(scheme, Decimal('5'))
        JobService.materialize_worksheet_onto_job(self.job, self.ws)
        task = Task.objects.get(source_plan_task=pt)
        self.assertEqual(task.est_qty, Decimal('5'))
        self.assertIsNone(task.actual_qty)  # estimate, not actual

    def test_carry_over_entered_qty_sets_task_est_qty(self):
        scheme = RateScheme.objects.create(
            name='Pieces', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('5'), unit_label='piece',
            accounting_category=self.ac,
        )
        pt = self._create_pt(scheme, Decimal('12'))
        JobService.materialize_worksheet_onto_job(self.job, self.ws)
        task = Task.objects.get(source_plan_task=pt)
        self.assertEqual(task.est_qty, Decimal('12'))
        # actual_qty is null at carry-over — worker enters it later
        self.assertIsNone(task.actual_qty)

    def test_template_generate_task_for_job_persists_est_qty(self):
        scheme = RateScheme.objects.create(
            name='T', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('100'), unit_label='job',
            accounting_category=self.ac,
        )
        template = TaskTemplate.objects.create(
            template_name='Setup',
            rate_scheme=scheme,
            default_billable_qty=Decimal('1'),
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
        template = TaskTemplate.objects.create(
            template_name='Default Template Name',
            rate_scheme=scheme,
            default_billable_qty=Decimal('1'),
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

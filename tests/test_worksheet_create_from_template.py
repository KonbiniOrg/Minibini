"""Tests that creating a worksheet from a template via the view carries bundles through."""
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from apps.jobs.models import (
    Task, TaskBundle, EstWorksheet, Job,
    WorkOrderTemplate, TaskTemplate, TemplateTaskAssociation, TemplateBundle,
)
from apps.contacts.models import Contact, Business
from apps.core.models import User, LineItemType


class WorksheetCreateFromTemplateTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', email='test@test.com', password='testpass123'
        )
        self.client.force_login(self.user)

        self.default_contact = Contact.objects.create(
            first_name='Default', last_name='Contact', email='dc@test.com'
        )
        self.business = Business.objects.create(
            business_name='Test Co', business_phone='123-456',
            default_contact=self.default_contact
        )
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User', email='tu@test.com',
            business=self.business
        )
        self.job = Job.objects.create(
            job_number='JOB-001', name='Test Job',
            contact=self.contact, status='draft'
        )
        self.lit_labor, _ = LineItemType.objects.get_or_create(
            code='LBR', defaults={'name': 'Labor'}
        )

        # Set up a template with a bundle
        self.wot = WorkOrderTemplate.objects.create(template_name='Floor Refinish')
        self.template_bundle = TemplateBundle.objects.create(
            work_order_template=self.wot, name='Prep Work',
            line_item_type=self.lit_labor, sort_order=1
        )
        self.tt_sand = TaskTemplate.objects.create(
            template_name='Sand Floor', rate=Decimal('50'),
            units='hours', line_item_type=self.lit_labor
        )
        self.tt_clean = TaskTemplate.objects.create(
            template_name='Clean Floor', rate=Decimal('25'),
            units='hours', line_item_type=self.lit_labor
        )
        self.tt_finish = TaskTemplate.objects.create(
            template_name='Apply Finish', rate=Decimal('100'),
            units='hours', line_item_type=self.lit_labor
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=self.wot, task_template=self.tt_sand,
            est_qty=Decimal('1'), mapping_strategy='bundle',
            bundle=self.template_bundle, sort_order=1
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=self.wot, task_template=self.tt_clean,
            est_qty=Decimal('1'), mapping_strategy='bundle',
            bundle=self.template_bundle, sort_order=2
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=self.wot, task_template=self.tt_finish,
            est_qty=Decimal('2'), mapping_strategy='direct', sort_order=3
        )

    def test_bundles_created_when_worksheet_created_from_template(self):
        """Creating a worksheet from a template via the view should create TaskBundles."""
        url = reverse('jobs:estworksheet_create_for_job', args=[self.job.job_id])
        response = self.client.post(url, {
            'job': self.job.job_id,
            'template': self.wot.template_id,
        })
        self.assertEqual(response.status_code, 302)

        worksheet = EstWorksheet.objects.get(job=self.job)

        # TaskBundle should have been created
        bundles = list(worksheet.bundles.all())
        self.assertEqual(len(bundles), 1)
        self.assertEqual(bundles[0].name, 'Prep Work')
        self.assertEqual(bundles[0].line_item_type, self.lit_labor)
        self.assertEqual(bundles[0].source_template_bundle, self.template_bundle)

    def test_task_mapping_set_when_worksheet_created_from_template(self):
        """Tasks created from template via the view should have correct mapping_strategy and bundle."""
        url = reverse('jobs:estworksheet_create_for_job', args=[self.job.job_id])
        self.client.post(url, {
            'job': self.job.job_id,
            'template': self.wot.template_id,
        })

        worksheet = EstWorksheet.objects.get(job=self.job)
        tasks = {t.name: t for t in Task.objects.filter(est_worksheet=worksheet)}

        self.assertEqual(tasks['Sand Floor'].mapping_strategy, 'bundle')
        self.assertIsNotNone(tasks['Sand Floor'].bundle)
        self.assertEqual(tasks['Clean Floor'].mapping_strategy, 'bundle')
        self.assertIsNotNone(tasks['Clean Floor'].bundle)
        self.assertEqual(tasks['Apply Finish'].mapping_strategy, 'direct')
        self.assertIsNone(tasks['Apply Finish'].bundle)

    def test_three_tasks_created_from_template(self):
        """All three tasks from the template should be created."""
        url = reverse('jobs:estworksheet_create_for_job', args=[self.job.job_id])
        self.client.post(url, {
            'job': self.job.job_id,
            'template': self.wot.template_id,
        })

        worksheet = EstWorksheet.objects.get(job=self.job)
        tasks = Task.objects.filter(est_worksheet=worksheet)
        self.assertEqual(tasks.count(), 3)

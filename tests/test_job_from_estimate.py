"""API-side tests for populating a Job from an Estimate/Worksheet.

Formerly tests/test_workorder_from_estimate.py, which targeted Django
HTML views for the old WorkOrder-creation flow. The HTML views will be
rewritten in Phase F; this file now covers the new API contract via
/api/jobs/{id}/populate-from-estimate/ and copy-from-worksheet/.

Comprehensive coverage of those endpoints lives in test_api_jobs.py;
this file adds the end-to-end "populate from estimate with associated
worksheet" scenario.
"""

from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient
from apps.core.models import User
from apps.contacts.models import Contact
from apps.jobs.models import Job, Task, PlanTask
from apps.estimates.models import Estimate, EstWorksheet, WorkTemplate
from apps.inventory.models import PlanMaterial


class JobPopulateFromEstimateEndToEndTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='e2e_admin', password='pass')
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.user.user_permissions.add(perm)
        self.user = User.objects.get(pk=self.user.pk)
        self.client.force_authenticate(user=self.user)

        self.contact = Contact.objects.create(first_name='E2E', last_name='Test')
        self.job = Job.objects.create(
            job_number='E2E-001', name='E2E Job', contact=self.contact,
        )
        self.template = WorkTemplate.objects.create(
            template_name='Kitchen Job Template', is_active=True,
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, template=self.template,
        )
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Assembly',
            units='each',
            rate=Decimal('150'),
            est_qty=Decimal('1'),
        )
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.plan_task,
            description='Bracket',
            quantity=Decimal('4'),
            unit_cost=Decimal('5'),
            sell_price=Decimal('10'),
        )

    def test_copy_from_worksheet_links_template(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/copy-from-worksheet/',
            {'worksheet_id': self.worksheet.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.job.refresh_from_db()
        self.assertEqual(self.job.template_id, self.template.pk)
        tasks = Task.objects.filter(job=self.job)
        self.assertEqual(tasks.count(), 1)
        self.assertEqual(tasks.first().name, 'Assembly')
        self.assertEqual(tasks.first().materials.count(), 1)

    def test_populate_from_accepted_estimate(self):
        estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-E2E-001',
            status=Estimate.STATUS_ACCEPTED,
        )
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/populate-from-estimate/',
            {'estimate_id': estimate.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_populate_from_draft_estimate_rejected(self):
        estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-E2E-002',
            status=Estimate.STATUS_DRAFT,
        )
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/populate-from-estimate/',
            {'estimate_id': estimate.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

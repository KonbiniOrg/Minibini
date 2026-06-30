"""API-side tests for populating a Job from a Worksheet.

Formerly tests/test_workorder_from_estimate.py, which targeted Django
HTML views for the old WorkOrder-creation flow. The HTML views will be
rewritten in Phase F; this file now covers the copy-from-worksheet API
contract.

Comprehensive coverage of that endpoint lives in test_api_jobs.py;
this file adds the end-to-end "copy from worksheet with template" scenario.
"""

from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient
from apps.core.models import User
from apps.contacts.models import Contact
from apps.jobs.models import Job, Task, PlanTask, RateScheme
from apps.core.models import AccountingCategory
from apps.estimates.models import EstWorksheet, WorkTemplate
from apps.inventory.models import PlanMaterial


class JobCopyFromWorksheetEndToEndTest(TestCase):

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
            status=Job.STATUS_APPROVED,
        )
        self.template = WorkTemplate.objects.create(
            template_name='Kitchen Job Template',
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        ac = AccountingCategory.objects.create(code='E2E-AC', name='e2e')
        self.scheme = RateScheme.objects.create(
            name='S-e2e', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('1'), unit_label='ea', accounting_category=ac,
        )
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Assembly',
            rate_scheme=self.scheme,
            est_qty=Decimal('1'),
        )
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.plan_task,
            description='Bracket',
            quantity=Decimal('4'),
            unit_cost=Decimal('5'),
            sell_price=Decimal('10'),
            accounting_category=ac,
        )

    def test_copy_from_worksheet_copies_tasks_and_materials(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/copy-from-worksheet/',
            {'worksheet_id': self.worksheet.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        tasks = Task.objects.filter(job=self.job)
        self.assertEqual(tasks.count(), 1)
        self.assertEqual(tasks.first().name, 'Assembly')
        self.assertEqual(tasks.first().materials.count(), 1)

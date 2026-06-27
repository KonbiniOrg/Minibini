from datetime import timedelta
from decimal import Decimal
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient
from django.test import TestCase
from apps.core.models import AccountingCategory, User
from apps.jobs.models import Job, PlanTask, RateScheme
from apps.contacts.models import Contact
from apps.estimates.models import EstWorksheet


class PlanTaskAPITest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser', password='testpass',
        )
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
        )
        self.job = Job.objects.create(
            job_number='TEST-001', name='Test Job', contact=self.contact,
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.cat = AccountingCategory.objects.create(code='LAB-pt', name='Labor PT')
        self.scheme = RateScheme.objects.create(
            name='Hourly PT', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50.00'), unit_label='hour',
            accounting_category=self.cat,
        )
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Install shelves',
            description='Wall-mount 3 shelves',
            rate_scheme=self.scheme,
            est_qty=Decimal('1'),
        )

    def test_retrieve_plan_task(self):
        response = self.client.get(f'/api/plan-tasks/{self.plan_task.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Install shelves')
        self.assertIn('plan_task_id', response.data)
        self.assertIn('est_worksheet', response.data)

    def test_retrieve_includes_materials(self):
        from apps.inventory.models import PlanMaterial
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.plan_task,
            description='Shelf bracket',
            quantity=6,
            unit_cost=5,
            sell_price=10,
            accounting_category=self.cat,
        )
        response = self.client.get(f'/api/plan-tasks/{self.plan_task.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['plan_materials']), 1)
        self.assertEqual(response.data['plan_materials'][0]['description'], 'Shelf bracket')

    def test_retrieve_includes_worksheet_and_job_context(self):
        response = self.client.get(f'/api/plan-tasks/{self.plan_task.pk}/')
        self.assertEqual(response.status_code, 200)
        ws = response.data['est_worksheet']
        self.assertEqual(ws['est_worksheet_id'], self.worksheet.pk)
        self.assertEqual(ws['job']['job_number'], 'TEST-001')

    def test_list_not_allowed(self):
        """PlanTasks are accessed via worksheet nested endpoint, not flat list."""
        response = self.client.get('/api/plan-tasks/')
        self.assertEqual(response.status_code, 405)

    def test_create_not_allowed(self):
        response = self.client.post('/api/plan-tasks/', {
            'name': 'New task',
        }, format='json')
        self.assertEqual(response.status_code, 405)

    def test_unauthenticated_returns_403(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(f'/api/plan-tasks/{self.plan_task.pk}/')
        self.assertEqual(response.status_code, 403)


class WorksheetNestedPlanTaskTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser2', password='testpass',
        )
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact2',
        )
        self.job = Job.objects.create(
            job_number='TEST-002', name='Test Job 2', contact=self.contact,
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.cat = AccountingCategory.objects.create(code='LAB-pt2', name='Labor PT2')
        self.scheme = RateScheme.objects.create(
            name='Hourly PT2', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50.00'), unit_label='hour',
            accounting_category=self.cat,
        )
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Sand floor',
            rate_scheme=self.scheme,
            est_qty=Decimal('1'),
        )

    def test_nested_task_list_includes_materials(self):
        from apps.inventory.models import PlanMaterial
        PlanMaterial.objects.create(
            est_worksheet=self.worksheet,
            plan_task=self.plan_task,
            description='Sandpaper 120 grit',
            quantity=10,
            unit_cost=3,
            sell_price=5,
            accounting_category=self.cat,
        )
        response = self.client.get(
            f'/api/est-worksheets/{self.worksheet.pk}/tasks/'
        )
        self.assertEqual(response.status_code, 200)
        task_data = response.data[0]
        self.assertIn('plan_materials', task_data)
        self.assertEqual(len(task_data['plan_materials']), 1)


class WorksheetPlanTaskEstWorkerTimeTest(TestCase):
    """B7 compliance: worksheet task endpoints accept and persist est_worker_time."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser_ewt', password='testpass',
        )
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.user.user_permissions.add(perm)
        self.user = User.objects.get(pk=self.user.pk)  # reload to clear perm cache
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(
            first_name='Worker', last_name='Time',
        )
        self.job = Job.objects.create(
            job_number='EWT-001', name='Worker Time Job', contact=self.contact,
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.cat = AccountingCategory.objects.create(code='LAB-ewt', name='Labor EWT')
        self.scheme = RateScheme.objects.create(
            name='Hourly EWT', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('75.00'), unit_label='hour',
            accounting_category=self.cat,
        )

    def test_add_task_via_tasks_endpoint_with_est_worker_time(self):
        """POST /api/est-worksheets/{id}/tasks/ accepts est_worker_time and persists it."""
        response = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/tasks/',
            {
                'name': 'Fit panels',
                'rate_scheme': self.scheme.pk,
                'est_qty': '3.00',
                'est_worker_time': 'PT2H30M',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('est_worker_time', response.data)
        plan_task = PlanTask.objects.get(pk=response.data['plan_task_id'])
        self.assertEqual(plan_task.est_worker_time, timedelta(hours=2, minutes=30))

    def test_serializer_includes_est_worker_time_in_response(self):
        """est_worker_time is returned in the task list response."""
        PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Polish surface',
            rate_scheme=self.scheme,
            est_qty=Decimal('1'),
            est_worker_time=timedelta(hours=1),
        )
        response = self.client.get(f'/api/est-worksheets/{self.worksheet.pk}/tasks/')
        self.assertEqual(response.status_code, 200)
        task_data = response.data[0]
        self.assertIn('est_worker_time', task_data)
        # DRF serializes DurationField as a string in ISO 8601 / HH:MM:SS form
        self.assertIsNotNone(task_data['est_worker_time'])

    def test_plan_task_detail_serializer_includes_est_worker_time(self):
        """GET /api/plan-tasks/{id}/ includes est_worker_time in the response."""
        plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Detail task',
            rate_scheme=self.scheme,
            est_qty=Decimal('2'),
            est_worker_time=timedelta(minutes=45),
        )
        response = self.client.get(f'/api/plan-tasks/{plan_task.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('est_worker_time', response.data)
        self.assertIsNotNone(response.data['est_worker_time'])

    def test_add_from_template_accepts_est_worker_time(self):
        """POST /api/est-worksheets/{id}/add-from-template/ accepts est_worker_time."""
        from apps.estimates.models import TaskTemplate
        tt = TaskTemplate.objects.create(
            template_name='Cut pieces',
            rate_scheme=self.scheme,
            default_billable_qty=Decimal('4'),
        )
        response = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/add-from-template/',
            {
                'task_template_id': tt.pk,
                'est_worker_time': 'PT1H',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        plan_task = PlanTask.objects.get(pk=response.data['plan_task_id'])
        self.assertEqual(plan_task.est_worker_time, timedelta(hours=1))


class PercentageServicePlanTaskRejectionTest(TestCase):
    """A RateScheme with algorithm=PERCENTAGE must be rejected when assigning
    to a PlanTask via the worksheet tasks endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='pct_ws_mgr', password='testpass',
        )
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.user.user_permissions.add(perm)
        self.user = User.objects.get(pk=self.user.pk)
        self.client.force_authenticate(user=self.user)
        contact = Contact.objects.create(first_name='Pct', last_name='Ws')
        self.job = Job.objects.create(
            job_number='PCT-WS-001', name='Pct Ws Job', contact=contact,
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        ac = AccountingCategory.objects.create(code='LAB-pws', name='Labor PWS')
        self.rush = RateScheme.objects.create(
            name='Rush WS', algorithm=RateScheme.PERCENTAGE, rate=Decimal('15'),
            unit_label='%', accounting_category=ac,
        )

    def test_cannot_assign_percentage_service_to_plan_task(self):
        resp = self.client.post(
            f'/api/est-worksheets/{self.worksheet.pk}/tasks/',
            {'name': 'y', 'rate_scheme': self.rush.pk, 'est_qty': '1'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.data)

from rest_framework.test import APIClient
from django.test import TestCase
from apps.core.models import User
from apps.jobs.models import Job, PlanTask
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
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Install shelves',
            description='Wall-mount 3 shelves',



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
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Sand floor',



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
        )
        response = self.client.get(
            f'/api/est-worksheets/{self.worksheet.pk}/tasks/'
        )
        self.assertEqual(response.status_code, 200)
        task_data = response.data[0]
        self.assertIn('plan_materials', task_data)
        self.assertEqual(len(task_data['plan_materials']), 1)

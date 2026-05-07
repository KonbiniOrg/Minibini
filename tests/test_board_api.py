from django.contrib.auth import get_user_model

from tests.base import FixtureTestCase
from apps.jobs.models import Task, Job
from apps.contacts.models import Contact
from apps.core.models import Configuration

User = get_user_model()


class TaskWorkerQueueTest(FixtureTestCase):
    def setUp(self):
        super().setUp()
        from apps.core.models import Configuration
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'}
        )
        self.contact = Contact.objects.first()
        self.job = Job.objects.create(
            job_number='JOB-TEST-0001',
            name='Test Job',
            status='approved',
            contact=self.contact,
        )
    def test_task_worker_queue_field_exists(self):
        task = Task(
            name='Test task',
            job=self.job,
            worker_queue=5,
            rate_scheme_id=1,
        )
        task.save()
        task.refresh_from_db()
        self.assertEqual(task.worker_queue, 5)

    def test_task_worker_queue_nullable(self):
        task = Task(
            name='Test task',
            job=self.job,
            worker_queue=None,
            rate_scheme_id=1,
        )
        task.save()
        task.refresh_from_db()
        self.assertIsNone(task.worker_queue)


class BoardEndpointTest(FixtureTestCase):
    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'}
        )
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.client.login(username='testuser', password='testpass')
        self.contact = Contact.objects.first()

    def test_board_endpoint_returns_200(self):
        response = self.client.get('/api/jobs/board/')
        self.assertEqual(response.status_code, 200)

    def test_board_endpoint_returns_all_sections(self):
        response = self.client.get('/api/jobs/board/')
        data = response.json()
        self.assertIn('pipeline', data)
        self.assertIn('approved', data)
        self.assertIn('closed', data)

    def test_board_endpoint_requires_authentication(self):
        self.client.logout()
        response = self.client.get('/api/jobs/board/')
        self.assertEqual(response.status_code, 403)


class TaskReorderEndpointTest(FixtureTestCase):
    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'}
        )
        self.contact = Contact.objects.first()
        self.user = User.objects.create_user(username='manager', password='testpass')
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.user.user_permissions.add(perm)
        self.client.login(username='manager', password='testpass')

        self.job = Job.objects.create(
            job_number='JOB-TEST-0001', name='Test Job',
            status='approved', contact=self.contact,
        )
        self.task1 = Task.objects.create(
            name='Task 1', job=self.job, assignee=self.user, worker_queue=1, rate_scheme_id=1,
        )
        self.task2 = Task.objects.create(
            name='Task 2', job=self.job, assignee=self.user, worker_queue=2, rate_scheme_id=1,
        )
        self.task3 = Task.objects.create(
            name='Task 3', job=self.job, assignee=self.user, worker_queue=3, rate_scheme_id=1,
        )

    def test_reorder_updates_worker_queue(self):
        response = self.client.post(
            '/api/tasks/reorder/',
            data={'task_ids': [self.task3.pk, self.task1.pk, self.task2.pk]},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.task1.refresh_from_db()
        self.task2.refresh_from_db()
        self.task3.refresh_from_db()
        self.assertEqual(self.task3.worker_queue, 1)
        self.assertEqual(self.task1.worker_queue, 2)
        self.assertEqual(self.task2.worker_queue, 3)

    def test_reorder_allowed_for_any_authenticated_user(self):
        viewer = User.objects.create_user(username='viewer', password='testpass')
        self.client.login(username='viewer', password='testpass')
        response = self.client.post(
            '/api/tasks/reorder/',
            data={'task_ids': [self.task3.pk, self.task1.pk, self.task2.pk]},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.task1.refresh_from_db()
        self.task2.refresh_from_db()
        self.task3.refresh_from_db()
        self.assertEqual(self.task3.worker_queue, 1)
        self.assertEqual(self.task1.worker_queue, 2)
        self.assertEqual(self.task2.worker_queue, 3)

    def test_reorder_requires_authentication(self):
        self.client.logout()
        response = self.client.post(
            '/api/tasks/reorder/',
            data={'task_ids': [self.task1.pk]},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_assign_task_via_patch(self):
        unassigned_task = Task.objects.create(
            name='Unassigned', job=self.job, rate_scheme_id=1,
        )
        response = self.client.post(
            f'/api/tasks/{unassigned_task.pk}/assign/',
            data={'assignee': self.user.pk, 'worker_queue': 4},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        unassigned_task.refresh_from_db()
        self.assertEqual(unassigned_task.assignee_id, self.user.pk)
        self.assertEqual(unassigned_task.worker_queue, 4)

    def test_unassign_task_clears_worker_queue(self):
        response = self.client.post(
            f'/api/tasks/{self.task1.pk}/assign/',
            data={'assignee': None, 'worker_queue': None},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.task1.refresh_from_db()
        self.assertIsNone(self.task1.assignee_id)
        self.assertIsNone(self.task1.worker_queue)


class TaskAssignEndpointTest(FixtureTestCase):
    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'}
        )
        self.contact = Contact.objects.first()
        self.user = User.objects.create_user(username='manager', password='testpass')
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.user.user_permissions.add(perm)
        self.client.login(username='manager', password='testpass')

        self.job = Job.objects.create(
            job_number='JOB-TEST-0001', name='Test Job',
            status='approved', contact=self.contact,
        )
    def test_assign_task_to_worker(self):
        task = Task.objects.create(name='Unassigned', job=self.job, rate_scheme_id=1)
        response = self.client.post(
            f'/api/tasks/{task.pk}/assign/',
            data={'assignee': self.user.pk, 'worker_queue': 1},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.assignee_id, self.user.pk)
        self.assertEqual(task.worker_queue, 1)

    def test_unassign_task(self):
        task = Task.objects.create(
            name='Assigned', job=self.job,
            assignee=self.user, worker_queue=1, rate_scheme_id=1,
        )
        response = self.client.post(
            f'/api/tasks/{task.pk}/assign/',
            data={'assignee': None, 'worker_queue': None},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertIsNone(task.assignee_id)
        self.assertIsNone(task.worker_queue)

    def test_assign_requires_permission(self):
        viewer = User.objects.create_user(username='viewer', password='testpass')
        self.client.login(username='viewer', password='testpass')
        task = Task.objects.create(name='Task', job=self.job, rate_scheme_id=1)
        response = self.client.post(
            f'/api/tasks/{task.pk}/assign/',
            data={'assignee': self.user.pk, 'worker_queue': 1},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)


class LazyBoardEndpointTest(FixtureTestCase):
    def setUp(self):
        super().setUp()
        Configuration.objects.get_or_create(
            key='board_closed_retention_days',
            defaults={'value': '14'}
        )
        self.user = User.objects.create_user(username='boarduser', password='testpass')
        self.client.login(username='boarduser', password='testpass')

    def test_pipeline_endpoint_returns_200(self):
        response = self.client.get('/api/jobs/board/pipeline/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('jobs', response.json())

    def test_approved_endpoint_returns_200(self):
        response = self.client.get('/api/jobs/board/approved/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('jobs', response.json())

    def test_unpaid_endpoint_returns_200(self):
        response = self.client.get('/api/jobs/board/unpaid/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('jobs', response.json())

    def test_closed_endpoint_returns_200(self):
        response = self.client.get('/api/jobs/board/closed/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('jobs', response.json())

    def test_endpoints_require_auth(self):
        self.client.logout()
        for path in ['/api/jobs/board/pipeline/', '/api/jobs/board/approved/',
                     '/api/jobs/board/unpaid/', '/api/jobs/board/closed/']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403, f'{path} should require auth')

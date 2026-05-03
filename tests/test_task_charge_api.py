from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from tests.base import BaseTestCase
from apps.jobs.models import RateScheme, TaskCharge, Task

User = get_user_model()


class TaskChargeAPITest(TestCase):
    def setUp(self):
        # Create a user with can_manage_jobs permission
        self.manager = User.objects.create_user(username='manager', password='testpass')
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.manager.user_permissions.add(perm)

        # Create a read-only worker user
        self.worker = User.objects.create_user(username='worker', password='testpass')

        # Create a rate scheme with a modifier
        self.scheme = RateScheme.objects.create(
            name='CNC Router',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='minute',
            modifiers=[{'key': 'messy', 'label': 'Messy', 'percent': 10}],
        )

        # Create a job and task
        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        contact = Contact.objects.create(first_name='Test', last_name='Contact')
        self.job = Job.objects.create(name='Test Job', contact=contact, job_number='JOB-TEST-001')
        self.task = Task.objects.create(name='Test Task', job=self.job)

        # Log in as manager by default
        self.client.login(username='manager', password='testpass')

    def test_task_serializer_includes_charge_null(self):
        """GET /api/tasks/{id}/ shows charge: null when no charge exists."""
        resp = self.client.get(f'/api/tasks/{self.task.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()['charge'])

    def test_task_serializer_includes_charge(self):
        """GET /api/tasks/{id}/ shows nested charge data."""
        TaskCharge.objects.create(
            task=self.task, rate_scheme=self.scheme,
            active_modifiers=['messy'], actuals={'qty': 30},
        )
        resp = self.client.get(f'/api/tasks/{self.task.pk}/')
        self.assertEqual(resp.status_code, 200)
        charge = resp.json()['charge']
        self.assertIsNotNone(charge)
        self.assertEqual(charge['rate_scheme'], self.scheme.pk)
        self.assertEqual(charge['active_modifiers'], ['messy'])

    def test_create_charge_on_task(self):
        resp = self.client.post(
            f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/charge/',
            {'rate_scheme': self.scheme.pk, 'active_modifiers': ['messy'], 'actuals': {'qty': 30}},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(TaskCharge.objects.filter(task=self.task).exists())

    def test_update_charge_actuals(self):
        TaskCharge.objects.create(task=self.task, rate_scheme=self.scheme)
        resp = self.client.patch(
            f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/charge/',
            {'actuals': {'qty': 35}},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.task.charge.refresh_from_db()
        self.assertEqual(self.task.charge.actuals, {'qty': 35})

    def test_get_charge(self):
        TaskCharge.objects.create(
            task=self.task, rate_scheme=self.scheme,
            active_modifiers=['messy'], actuals={'qty': 30},
        )
        resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/charge/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['scheme_name'], 'CNC Router')

    def test_get_charge_null(self):
        resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/charge/')
        self.assertEqual(resp.status_code, 200)

    def test_duplicate_create_returns_400(self):
        TaskCharge.objects.create(task=self.task, rate_scheme=self.scheme)
        resp = self.client.post(
            f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/charge/',
            {'rate_scheme': self.scheme.pk},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_requires_manage_jobs_perm(self):
        """Unauthenticated/unauthorized users cannot POST."""
        self.client.logout()
        self.client.login(username='worker', password='testpass')
        resp = self.client.post(
            f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/charge/',
            {'rate_scheme': self.scheme.pk},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_patch_requires_manage_jobs_perm(self):
        """Workers without can_manage_jobs cannot PATCH."""
        TaskCharge.objects.create(task=self.task, rate_scheme=self.scheme)
        self.client.logout()
        self.client.login(username='worker', password='testpass')
        resp = self.client.patch(
            f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/charge/',
            {'actuals': {'qty': 5}},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_get_charge_worker_can_read(self):
        """Workers without can_manage_jobs can GET."""
        TaskCharge.objects.create(task=self.task, rate_scheme=self.scheme, actuals={'qty': 10})
        self.client.logout()
        self.client.login(username='worker', password='testpass')
        resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/charge/')
        self.assertEqual(resp.status_code, 200)

    def test_charge_computed_fields(self):
        """Response includes scheme_name, effective_rate, computed_charge."""
        TaskCharge.objects.create(
            task=self.task, rate_scheme=self.scheme,
            active_modifiers=['messy'], actuals={'qty': 10},
        )
        resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/charge/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['scheme_name'], 'CNC Router')
        self.assertEqual(data['scheme_unit_label'], 'minute')
        self.assertIn('effective_rate', data)
        self.assertIn('computed_charge', data)

    def test_task_not_found_returns_404(self):
        resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/99999/charge/')
        self.assertEqual(resp.status_code, 404)


class TaskSerializerNoLegacyFieldsTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory, User
        from django.contrib.auth.models import Permission
        from apps.jobs.models import RateScheme, Job, Task, TaskCharge
        from apps.contacts.models import Business, Contact
        self.user = User.objects.create_user('u-tnf', 'u-tnf@x.test', 'pw')
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.user.user_permissions.add(perm)
        self.client.force_login(self.user)
        ac = AccountingCategory.objects.create(code='X-tnf', name='X-tnf')
        self.scheme = RateScheme.objects.create(
            name='S-tnf', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-tnf@l.test',
        )
        biz = Business.objects.create(
            business_name='B-tnf', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(job_number='J-tnf', contact=contact)
        self.task = Task.objects.create(job=self.job, name='T-tnf')
        TaskCharge.objects.create(task=self.task, rate_scheme=self.scheme)

    def test_task_list_omits_legacy_fields(self):
        resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/')
        body = resp.json()
        # The list endpoint may be paginated or unpaginated; handle both.
        items = body.get('results', body) if isinstance(body, dict) else body
        first = items[0]
        for legacy in ('units', 'rate', 'est_qty', 'accounting_category'):
            self.assertNotIn(legacy, first)
        self.assertIn('charge', first)

    def test_task_detail_omits_legacy_fields(self):
        resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/')
        body = resp.json()
        for legacy in ('units', 'rate', 'est_qty', 'accounting_category'):
            self.assertNotIn(legacy, body)
        self.assertIn('charge', body)

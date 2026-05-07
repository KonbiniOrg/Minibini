from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from tests.base import BaseTestCase
from apps.jobs.models import RateScheme, Task

User = get_user_model()


class TaskBillingFieldsAPITest(TestCase):
    """Phase B: Task billing fields are top-level on the Task serializer.
    The /charge/ endpoint has been removed; billing is set directly on Task.
    """
    def setUp(self):
        self.manager = User.objects.create_user(username='manager', password='testpass')
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.manager.user_permissions.add(perm)

        self.worker = User.objects.create_user(username='worker', password='testpass')

        from apps.core.models import AccountingCategory
        self.ac = AccountingCategory.objects.create(code='LAB', name='Labor')
        self.scheme = RateScheme.objects.create(
            name='CNC Router',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='minute',
            modifiers=[{'key': 'messy', 'label': 'Messy', 'percent': 10}],
            accounting_category=self.ac,
        )

        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        contact = Contact.objects.create(first_name='Test', last_name='Contact')
        self.job = Job.objects.create(name='Test Job', contact=contact, job_number='JOB-TEST-001')
        self.task = Task.objects.create(name='Test Task', job=self.job, rate_scheme=self.scheme)

        self.client.login(username='manager', password='testpass')

    def test_task_serializer_has_no_charge_key(self):
        """GET /api/tasks/{id}/ Phase B: 'charge' is no longer nested; billing fields are top-level."""
        resp = self.client.get(f'/api/tasks/{self.task.pk}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertNotIn('charge', body)
        # rate_scheme and active_modifiers are now top-level
        self.assertIn('rate_scheme', body)
        self.assertIn('active_modifiers', body)

    def test_task_serializer_includes_billing_top_level(self):
        """GET /api/tasks/{id}/ Phase B: billing fields from Task are exposed top-level."""
        self.task.rate_scheme = self.scheme
        self.task.active_modifiers = ['messy']
        self.task.save()
        resp = self.client.get(f'/api/tasks/{self.task.pk}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertNotIn('charge', body)
        self.assertEqual(body['rate_scheme'], self.scheme.pk)
        self.assertEqual(body['active_modifiers'], ['messy'])


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
        self.task = Task.objects.create(job=self.job, name='T-tnf', rate_scheme=self.scheme)
        TaskCharge.objects.create(task=self.task, rate_scheme=self.scheme)

    def test_task_list_omits_legacy_fields(self):
        resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/')
        body = resp.json()
        # The list endpoint may be paginated or unpaginated; handle both.
        items = body.get('results', body) if isinstance(body, dict) else body
        first = items[0]
        # Phase A legacy fields (removed in the flatten refactor)
        for legacy in ('units', 'rate', 'accounting_category'):
            self.assertNotIn(legacy, first)
        # Phase B: charge nest is gone; billing fields are now top-level
        self.assertNotIn('charge', first)
        self.assertIn('rate_scheme', first)
        self.assertIn('est_qty', first)

    def test_task_detail_omits_legacy_fields(self):
        resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/')
        body = resp.json()
        # Phase A legacy fields (removed in the flatten refactor)
        for legacy in ('units', 'rate', 'accounting_category'):
            self.assertNotIn(legacy, body)
        # Phase B: charge nest is gone; billing fields are now top-level
        self.assertNotIn('charge', body)
        self.assertIn('rate_scheme', body)
        self.assertIn('est_qty', body)


class TaskTimeFieldsTest(BaseTestCase):
    """Verify actual_hours and estimated_hours on TaskSerializer."""
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory, User
        from django.contrib.auth.models import Permission
        from apps.jobs.models import RateScheme, Job, Task, TaskCharge, PlanTask, Blep
        from apps.estimates.models import EstWorksheet
        from apps.contacts.models import Contact
        from datetime import timedelta
        from django.utils import timezone

        self.user = User.objects.create_user('u-time', 'u-time@x.test', 'pw')
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.user.user_permissions.add(perm)
        self.client.force_login(self.user)

        ac = AccountingCategory.objects.create(code='X-time', name='X-time')
        self.elapsed_scheme = RateScheme.objects.create(
            name='Hourly-time', algorithm='elapsed_time', rate=Decimal('60'),
            unit_label='hr', accounting_category=ac,
        )
        self.flat_scheme = RateScheme.objects.create(
            name='Flat-time', algorithm='flat_fee', rate=Decimal('100'),
            unit_label='ea', accounting_category=ac,
        )
        contact = Contact.objects.create(first_name='T', last_name='Time')
        self.job = Job.objects.create(job_number='J-time', contact=contact)
        self.worksheet = EstWorksheet.objects.create(job=self.job)

        # Time-based task carried over from a plan task with est_qty=4 hours.
        # Phase B: est_qty is set directly on the Task (not read via source_plan_task).
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Cut',
            rate_scheme=self.elapsed_scheme, est_qty=Decimal('4.0'),
        )
        self.elapsed_task = Task.objects.create(
            job=self.job, name='Cut', source_plan_task=self.plan_task,
            est_qty=Decimal('4.0'), rate_scheme=self.elapsed_scheme,
        )
        TaskCharge.objects.create(task=self.elapsed_task, rate_scheme=self.elapsed_scheme)

        # 1 hour 30 minutes of work logged (1.5h)
        now = timezone.now()
        Blep.objects.create(
            task=self.elapsed_task, user=self.user,
            start_time=now - timedelta(hours=1, minutes=30),
            end_time=now,
        )

        # Flat-fee task with no plan source
        self.flat_task = Task.objects.create(job=self.job, name='Setup', rate_scheme=self.flat_scheme)
        TaskCharge.objects.create(task=self.flat_task, rate_scheme=self.flat_scheme)
        Blep.objects.create(
            task=self.flat_task, user=self.user,
            start_time=now - timedelta(minutes=30),
            end_time=now,
        )

    def test_actual_hours_sums_bleps(self):
        # Phase B: both list and detail endpoints include actual_hours.
        resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/')
        items = resp.json()
        items = items.get('results', items) if isinstance(items, dict) else items
        elapsed = next(t for t in items if t['task_id'] == self.elapsed_task.pk)
        self.assertAlmostEqual(elapsed['actual_hours'], 1.5, places=1)
        # Phase B: estimated_hours removed; est_qty is now the top-level field.
        self.assertNotIn('estimated_hours', elapsed)
        self.assertEqual(float(elapsed['est_qty']), 4.0)

    def test_flat_fee_task_has_no_estimated_hours(self):
        resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/')
        items = resp.json()
        items = items.get('results', items) if isinstance(items, dict) else items
        flat = next(t for t in items if t['task_id'] == self.flat_task.pk)
        self.assertAlmostEqual(flat['actual_hours'], 0.5, places=1)
        # Phase B: estimated_hours is removed; flat tasks have no est_qty by default.
        self.assertNotIn('estimated_hours', flat)
        self.assertIsNone(flat['est_qty'])


class TaskTemplateSerializerNoACTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory, User
        from apps.jobs.models import RateScheme
        from apps.estimates.models import TaskTemplate
        self.user = User.objects.create_user('u-tts', 'u-tts@x.test', 'pw')
        self.client.force_login(self.user)
        ac = AccountingCategory.objects.create(code='X-tts', name='X-tts')
        scheme = RateScheme.objects.create(
            name='S-tts', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        self.template = TaskTemplate.objects.create(
            template_name='T-tts', rate_scheme=scheme,
            default_billable_qty=Decimal('1'),
        )

    def test_template_payload_omits_accounting_category(self):
        resp = self.client.get(f'/api/task-templates/{self.template.pk}/')
        body = resp.json()
        self.assertNotIn('accounting_category', body)
        self.assertIn('rate_scheme', body)

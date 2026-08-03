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
        self.task = Task(name='Test Task', job=self.job)
        self.task.stamp_from_scheme(self.scheme, modifier_keys=['messy'])
        self.task.save()

        self.client.login(username='manager', password='testpass')

    def test_task_serializer_has_no_charge_key(self):
        """GET /api/tasks/{id}/: 'charge' is no longer nested; billing
        fields are top-level task-owned-money fields (task-owned-money
        Phase 1). `rate_scheme` is a write-only create-time stamp trigger —
        never in a GET response; `source_scheme` is the read-only
        provenance pointer stamping actually leaves behind."""
        resp = self.client.get(f'/api/tasks/{self.task.pk}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertNotIn('charge', body)
        self.assertNotIn('rate_scheme', body)
        self.assertIn('source_scheme', body)
        self.assertIn('active_modifiers', body)

    def test_task_serializer_includes_billing_top_level(self):
        """GET /api/tasks/{id}/: billing fields stamped from the preset are
        exposed top-level, owned by the Task itself."""
        resp = self.client.get(f'/api/tasks/{self.task.pk}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertNotIn('charge', body)
        self.assertEqual(body['source_scheme'], self.scheme.pk)
        self.assertEqual(body['qty_source'], self.scheme.algorithm)
        self.assertEqual(Decimal(body['rate']), self.scheme.rate)
        self.assertEqual(body['unit_label'], self.scheme.unit_label)
        self.assertEqual(body['accounting_category'], self.ac.pk)
        self.assertEqual([m['key'] for m in body['active_modifiers']], ['messy'])


class TaskSerializerNoLegacyFieldsTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory, User
        from django.contrib.auth.models import Permission
        from apps.jobs.models import RateScheme, Job, Task
        from apps.contacts.models import Business, Contact
        self.user = User.objects.create_user('u-tnf', 'u-tnf@x.test', 'pw')
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.user.user_permissions.add(perm)
        self.client.force_login(self.user)
        ac = AccountingCategory.objects.create(code='X-tnf', name='X-tnf')
        self.scheme = RateScheme.objects.create(
            name='S-tnf', algorithm='entered_qty', rate=Decimal('1'),
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
        self.task = Task(job=self.job, name='T-tnf')
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()

    def test_task_list_omits_legacy_fields(self):
        resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/')
        body = resp.json()
        # The list endpoint may be paginated or unpaginated; handle both.
        items = body.get('results', body) if isinstance(body, dict) else body
        first = items[0]
        # 'units' (old field name, renamed to unit_label) and the old
        # scheme_name/scheme_algorithm/scheme_unit_label read-only echoes
        # are gone. 'rate_scheme' is now write-only (a create-time stamp
        # trigger) — never in a GET response.
        for legacy in ('units', 'scheme_name', 'scheme_algorithm', 'scheme_unit_label'):
            self.assertNotIn(legacy, first)
        self.assertNotIn('rate_scheme', first)
        self.assertNotIn('charge', first)
        # rate/accounting_category are now genuine task-owned-money fields.
        self.assertIn('rate', first)
        self.assertIn('accounting_category', first)
        self.assertIn('source_scheme', first)
        self.assertIn('est_qty', first)

    def test_task_detail_omits_legacy_fields(self):
        resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/')
        body = resp.json()
        for legacy in ('units', 'scheme_name', 'scheme_algorithm', 'scheme_unit_label'):
            self.assertNotIn(legacy, body)
        self.assertNotIn('rate_scheme', body)
        self.assertNotIn('charge', body)
        self.assertIn('rate', body)
        self.assertIn('accounting_category', body)
        self.assertIn('source_scheme', body)
        self.assertIn('est_qty', body)


class TaskTimeFieldsTest(BaseTestCase):
    """Verify actual_hours and estimated_hours on TaskSerializer."""
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory, User
        from django.contrib.auth.models import Permission
        from apps.jobs.models import RateScheme, Job, Task, Blep
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
            unit_label='hour', accounting_category=ac,
        )
        self.flat_scheme = RateScheme.objects.create(
            name='Flat-time', algorithm='entered_qty', rate=Decimal('100'),
            unit_label='ea', accounting_category=ac,
        )
        contact = Contact.objects.create(first_name='T', last_name='Time')
        self.job = Job.objects.create(job_number='J-time', contact=contact)

        # Time-based task with est_qty=4 hours set directly on the Task.
        self.elapsed_task = Task(
            job=self.job, name='Cut', est_qty=Decimal('4.0'),
        )
        self.elapsed_task.stamp_from_scheme(self.elapsed_scheme)
        self.elapsed_task.save()

        # 1 hour 30 minutes of work logged (1.5h)
        now = timezone.now()
        Blep.objects.create(
            task=self.elapsed_task, user=self.user,
            start_time=now - timedelta(hours=1, minutes=30),
            end_time=now,
        )

        # Flat-fee task with no plan source
        self.flat_task = Task(job=self.job, name='Setup')
        self.flat_task.stamp_from_scheme(self.flat_scheme)
        self.flat_task.save()
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

    def test_actual_hours_matches_billing_qty(self):
        # 50 min of bleps: serializer hours must equal get_actual_qty exactly
        # (they were two independent conversions before; now one).
        from apps.jobs.models import Blep
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now().replace(second=0, microsecond=0)
        task = Task(job=self.job, name='Drift')
        task.stamp_from_scheme(self.elapsed_scheme)
        task.save()
        Blep.objects.create(
            task=task, user=self.user,
            start_time=now - timedelta(minutes=50),
            end_time=now,
        )
        from apps.api.tasks.serializers import TaskSerializer
        ser_val = Decimal(str(TaskSerializer(task).data['actual_hours']))
        # Task-owned money (Phase 1): actual qty resolves from the task's
        # own qty_source — no RateScheme lookup.
        self.assertEqual(ser_val, task.get_actual_qty())


class ServiceItemSerializerNoACTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory, User
        from apps.jobs.models import RateScheme
        from apps.estimates.models import ServiceItem
        self.user = User.objects.create_user('u-tts', 'u-tts@x.test', 'pw')
        self.client.force_login(self.user)
        ac = AccountingCategory.objects.create(code='X-tts', name='X-tts')
        scheme = RateScheme.objects.create(
            name='S-tts', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        self.template = ServiceItem.objects.create(
            template_name='T-tts', rate_scheme=scheme,
        )

    def test_template_payload_omits_accounting_category(self):
        resp = self.client.get(f'/api/service-items/{self.template.pk}/')
        body = resp.json()
        self.assertNotIn('accounting_category', body)
        self.assertIn('rate_scheme', body)

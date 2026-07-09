"""Tests for /api/tasks/ endpoints — permissions and worker-accessible actions."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from apps.contacts.models import Contact
from apps.jobs.models import Job, RateScheme, Task

User = get_user_model()


class ActualQtyAddActionTest(TestCase):
    """POST /api/tasks/{id}/actual-qty/add/ applies a signed increment to
    the running total. IsAuthenticated only — any worker on the task can
    contribute. The old replace-style PATCH endpoint is gone."""

    def setUp(self):
        from apps.core.models import AccountingCategory

        ac = AccountingCategory.objects.create(code='LAB2', name='Labor2')
        self.scheme = RateScheme.objects.create(
            name='Press',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'),
            unit_label='piece',
            accounting_category=ac,
        )

        contact = Contact.objects.create(first_name='Acme', last_name='Corp')
        self.job = Job.objects.create(
            name='Widget Run', contact=contact, job_number='JOB-TEST-002'
        )
        self.task = Task.objects.create(
            name='Press parts', job=self.job, rate_scheme=self.scheme
        )

        # A plain worker — no can_manage_jobs permission.
        self.worker = User.objects.create_user(
            username='plain_worker', password='testpass'
        )

    def _url(self):
        return f'/api/tasks/{self.task.pk}/actual-qty/add/'

    def _post(self, payload):
        return self.client.post(
            self._url(), data=payload, content_type='application/json'
        )

    def test_worker_without_manage_jobs_can_add(self):
        self.client.login(username='plain_worker', password='testpass')
        resp = self._post({'actual_qty': '7.50'})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.actual_qty, Decimal('7.50'))

    def test_adds_accumulate(self):
        self.client.login(username='plain_worker', password='testpass')
        self._post({'actual_qty': '9'})
        resp = self._post({'actual_qty': '5'})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.actual_qty, Decimal('14'))

    def test_negative_add_subtracts(self):
        self.client.login(username='plain_worker', password='testpass')
        self._post({'actual_qty': '50'})
        resp = self._post({'actual_qty': '-45'})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.actual_qty, Decimal('5'))

    def test_add_below_zero_total_rejected(self):
        self.client.login(username='plain_worker', password='testpass')
        self._post({'actual_qty': '3'})
        resp = self._post({'actual_qty': '-4'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('actual_qty', resp.json())

    def test_zero_add_rejected(self):
        self.client.login(username='plain_worker', password='testpass')
        resp = self._post({'actual_qty': '0'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('actual_qty', resp.json())

    def test_missing_actual_qty_returns_400(self):
        self.client.login(username='plain_worker', password='testpass')
        resp = self._post({})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('actual_qty', resp.json())

    def test_invalid_decimal_returns_400(self):
        self.client.login(username='plain_worker', password='testpass')
        resp = self._post({'actual_qty': 'not-a-number'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('actual_qty', resp.json())

    def test_unauthenticated_request_is_rejected(self):
        resp = self._post({'actual_qty': '5'})
        self.assertIn(resp.status_code, (401, 403))

    def test_response_returns_new_total(self):
        self.client.login(username='plain_worker', password='testpass')
        self._post({'actual_qty': '9'})
        resp = self._post({'actual_qty': '3.5'})
        body = resp.json()
        self.assertIn('actual_qty', body)
        self.assertEqual(Decimal(body['actual_qty']), Decimal('12.5'))

    def test_add_on_complete_task_rejected(self):
        self.client.login(username='plain_worker', password='testpass')
        Task.objects.filter(pk=self.task.pk).update(
            status=Task.STATUS_COMPLETE, actual_qty=Decimal('5'))
        resp = self._post({'actual_qty': '1'})
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_replace_patch_endpoint_is_gone(self):
        """The old PATCH /actual-qty/ replace endpoint must no longer route."""
        self.client.login(username='plain_worker', password='testpass')
        resp = self.client.patch(
            f'/api/tasks/{self.task.pk}/actual-qty/',
            data={'actual_qty': '5'}, content_type='application/json',
        )
        self.assertIn(resp.status_code, (404, 405), resp.content)


class CancelTaskPermissionTest(TestCase):
    """POST /api/tasks/{id}/cancel/ requires CanManageJobOrPM (atom-holder OR
    the task's job's project_manager). A plain worker is denied (403)."""

    def setUp(self):
        from apps.core.models import AccountingCategory

        ac = AccountingCategory.objects.create(code='LABC', name='LaborC')
        self.scheme = RateScheme.objects.create(
            name='CancelScheme',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'),
            unit_label='piece',
            accounting_category=ac,
        )
        contact = Contact.objects.create(first_name='Cancel', last_name='Co')
        self.job = Job.objects.create(
            name='Cancel Job', contact=contact, job_number='JOB-CANCEL-001'
        )
        self.task = Task.objects.create(
            name='Cancellable', job=self.job, rate_scheme=self.scheme
        )

        # A plain worker — no atom, not the job's PM.
        self.worker = User.objects.create_user(
            username='cancel_worker', password='testpass'
        )
        # An atom-holder.
        self.manager = User.objects.create_user(
            username='cancel_mgr', password='testpass'
        )
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.manager.user_permissions.add(perm)
        self.manager = User.objects.get(pk=self.manager.pk)
        # The job's project manager (no atom, but is PM).
        self.pm = User.objects.create_user(
            username='cancel_pm', password='testpass'
        )
        self.job.project_manager = self.pm
        self.job.save(update_fields=['project_manager'])

    def _url(self):
        return f'/api/tasks/{self.task.pk}/cancel/'

    def test_cancel_denied_for_worker(self):
        self.client.force_login(self.worker)
        resp = self.client.post(self._url(), data={}, content_type='application/json')
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_cancel_allowed_for_atom_holder(self):
        # Resolves the target job via JobScopedPermissionMixin — must not 403.
        self.client.force_login(self.manager)
        resp = self.client.post(self._url(), data={}, content_type='application/json')
        self.assertNotEqual(resp.status_code, 403, resp.content)

    def test_cancel_allowed_for_project_manager(self):
        self.client.force_login(self.pm)
        resp = self.client.post(self._url(), data={}, content_type='application/json')
        self.assertNotEqual(resp.status_code, 403, resp.content)


class PercentageServiceTaskRejectionTest(TestCase):
    """A RateScheme with algorithm=PERCENTAGE must be rejected when assigning
    to a Task — percentage services are document-level adjustments only."""

    def setUp(self):
        from apps.core.models import AccountingCategory
        from django.contrib.auth.models import Permission

        ac = AccountingCategory.objects.create(code='LABD', name='LaborD')
        self.contact = Contact.objects.create(first_name='Pct', last_name='Co')
        self.job = Job.objects.create(
            name='Pct Job', contact=self.contact, job_number='JOB-PCT-001'
        )
        self.rush = RateScheme.objects.create(
            name='Rush', algorithm=RateScheme.PERCENTAGE, rate=Decimal('15'),
            unit_label='%', accounting_category=ac,
        )
        self.manager = User.objects.create_user(
            username='pct_mgr', password='testpass'
        )
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.manager.user_permissions.add(perm)

    def test_cannot_assign_percentage_service_to_task(self):
        self.client.force_login(self.manager)
        resp = self.client.post(f'/api/jobs/{self.job.pk}/tasks/', {
            'name': 'x', 'rate_scheme': self.rush.pk, 'est_qty': '1',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 400)

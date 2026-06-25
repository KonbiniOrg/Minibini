"""Tests for /api/tasks/ endpoints — permissions and worker-accessible actions."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from apps.contacts.models import Contact
from apps.jobs.models import Job, ServiceItem, Task

User = get_user_model()


class ActualQtyActionTest(TestCase):
    """The /api/tasks/{id}/actual-qty/ PATCH endpoint requires only IsAuthenticated,
    so workers without can_manage_jobs can record their own actual qty."""

    def setUp(self):
        from apps.core.models import AccountingCategory

        ac = AccountingCategory.objects.create(code='LAB2', name='Labor2')
        self.scheme = ServiceItem.objects.create(
            name='Press',
            algorithm=ServiceItem.ENTERED_QTY,
            rate=Decimal('10.00'),
            unit_label='piece',
            accounting_category=ac,
        )

        contact = Contact.objects.create(first_name='Acme', last_name='Corp')
        self.job = Job.objects.create(
            name='Widget Run', contact=contact, job_number='JOB-TEST-002'
        )
        self.task = Task.objects.create(
            name='Press parts', job=self.job, service_item=self.scheme
        )

        # A plain worker — no can_manage_jobs permission.
        self.worker = User.objects.create_user(
            username='plain_worker', password='testpass'
        )

        # A manager with can_manage_jobs — for contrast.
        self.manager = User.objects.create_user(
            username='mgr', password='testpass'
        )
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.manager.user_permissions.add(perm)

    def _url(self):
        return f'/api/tasks/{self.task.pk}/actual-qty/'

    def test_worker_without_manage_jobs_can_set_actual_qty(self):
        """A worker who cannot manage jobs must still be able to record qty."""
        self.client.login(username='plain_worker', password='testpass')
        resp = self.client.patch(
            self._url(), data={'actual_qty': '7.50'}, content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.actual_qty, Decimal('7.50'))

    def test_manager_can_also_set_actual_qty(self):
        """Managers retain the ability to set actual_qty through this endpoint too."""
        self.client.login(username='mgr', password='testpass')
        resp = self.client.patch(
            self._url(), data={'actual_qty': '3'}, content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.actual_qty, Decimal('3'))

    def test_unauthenticated_request_is_rejected(self):
        """Unauthenticated requests must be denied (401 or 403)."""
        resp = self.client.patch(
            self._url(), data={'actual_qty': '5'}, content_type='application/json'
        )
        self.assertIn(resp.status_code, (401, 403))

    def test_missing_actual_qty_returns_400(self):
        """Omitting actual_qty from the payload returns a 400 error."""
        self.client.login(username='plain_worker', password='testpass')
        resp = self.client.patch(
            self._url(), data={}, content_type='application/json'
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('actual_qty', resp.json())

    def test_invalid_decimal_returns_400(self):
        """Non-numeric values return a 400 error."""
        self.client.login(username='plain_worker', password='testpass')
        resp = self.client.patch(
            self._url(), data={'actual_qty': 'not-a-number'}, content_type='application/json'
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('actual_qty', resp.json())

    def test_response_echoes_saved_value(self):
        """The response body includes the saved actual_qty as a string."""
        self.client.login(username='plain_worker', password='testpass')
        resp = self.client.patch(
            self._url(), data={'actual_qty': '12.5'}, content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertIn('actual_qty', body)
        self.assertEqual(Decimal(body['actual_qty']), Decimal('12.5'))


class CancelTaskPermissionTest(TestCase):
    """POST /api/tasks/{id}/cancel/ requires CanManageJobOrPM (atom-holder OR
    the task's job's project_manager). A plain worker is denied (403)."""

    def setUp(self):
        from apps.core.models import AccountingCategory

        ac = AccountingCategory.objects.create(code='LABC', name='LaborC')
        self.scheme = ServiceItem.objects.create(
            name='CancelScheme',
            algorithm=ServiceItem.ENTERED_QTY,
            rate=Decimal('10.00'),
            unit_label='piece',
            accounting_category=ac,
        )
        contact = Contact.objects.create(first_name='Cancel', last_name='Co')
        self.job = Job.objects.create(
            name='Cancel Job', contact=contact, job_number='JOB-CANCEL-001'
        )
        self.task = Task.objects.create(
            name='Cancellable', job=self.job, service_item=self.scheme
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
    """A ServiceItem with algorithm=PERCENTAGE must be rejected when assigning
    to a Task — percentage services are document-level adjustments only."""

    def setUp(self):
        from apps.core.models import AccountingCategory
        from django.contrib.auth.models import Permission

        ac = AccountingCategory.objects.create(code='LABD', name='LaborD')
        self.contact = Contact.objects.create(first_name='Pct', last_name='Co')
        self.job = Job.objects.create(
            name='Pct Job', contact=self.contact, job_number='JOB-PCT-001'
        )
        self.rush = ServiceItem.objects.create(
            name='Rush', algorithm=ServiceItem.PERCENTAGE, rate=Decimal('15'),
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
            'name': 'x', 'service_item': self.rush.pk, 'est_qty': '1',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 400)

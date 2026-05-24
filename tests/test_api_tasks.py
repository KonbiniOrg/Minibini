"""Tests for /api/tasks/ endpoints — permissions and worker-accessible actions."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from apps.contacts.models import Contact
from apps.jobs.models import Job, RateScheme, Task

User = get_user_model()


class ActualQtyActionTest(TestCase):
    """The /api/tasks/{id}/actual-qty/ PATCH endpoint requires only IsAuthenticated,
    so workers without can_manage_jobs can record their own actual qty."""

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

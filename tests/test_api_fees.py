from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APITestCase
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, Fee
from apps.contacts.models import Contact, Business

User = get_user_model()


def _make_manager(username):
    user = User.objects.create_user(username, password='p')
    user.user_permissions.add(Permission.objects.get(codename='can_manage_jobs'))
    # Re-fetch to drop Django's per-instance permission cache.
    return User.objects.get(pk=user.pk)


class FeeApiTest(APITestCase):
    """POST/PATCH/DELETE for Fee atoms nested under a job."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='Services', code='FEEAPI1')
        self.manager = _make_manager('fee_mgr')
        self.client.force_login(self.manager)
        contact = Contact.objects.create(first_name='C', last_name='T')
        biz = Business.objects.create(business_name='B', default_contact=contact)
        contact.business = biz
        contact.save()
        self.job = Job.objects.create(job_number='JOB-FEE-1', contact=contact)

    def test_create_fee(self):
        url = f'/api/jobs/{self.job.pk}/fees/'
        resp = self.client.post(url, {
            'description': 'Rush charge',
            'quantity': '2',
            'unit_rate': '75.00',
            'accounting_category': self.cat.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        fee = Fee.objects.get(job=self.job)
        self.assertEqual(fee.unit_rate, Decimal('75.00'))
        self.assertEqual(fee.quantity, Decimal('2'))
        self.assertEqual(fee.accounting_category_id, self.cat.pk)
        self.assertEqual(fee.description, 'Rush charge')

    def test_create_assigns_incrementing_sort_order(self):
        url = f'/api/jobs/{self.job.pk}/fees/'
        self.client.post(url, {'unit_rate': '1', 'accounting_category': self.cat.pk}, format='json')
        self.client.post(url, {'unit_rate': '2', 'accounting_category': self.cat.pk}, format='json')
        orders = sorted(Fee.objects.filter(job=self.job).values_list('sort_order', flat=True))
        self.assertEqual(orders, [1, 2])

    def test_create_missing_accounting_category_is_400(self):
        url = f'/api/jobs/{self.job.pk}/fees/'
        resp = self.client.post(url, {
            'description': 'no cat', 'quantity': '1', 'unit_rate': '50.00',
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_patch_edits_fee(self):
        fee = Fee.objects.create(job=self.job, description='x', quantity=Decimal('1'),
                                 unit_rate=Decimal('10.00'), accounting_category=self.cat)
        url = f'/api/jobs/{self.job.pk}/fees/{fee.pk}/'
        resp = self.client.patch(url, {'unit_rate': '99.00'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        fee.refresh_from_db()
        self.assertEqual(fee.unit_rate, Decimal('99.00'))

    def test_delete_returns_200_with_json_body(self):
        fee = Fee.objects.create(job=self.job, description='x', quantity=Decimal('1'),
                                 unit_rate=Decimal('10.00'), accounting_category=self.cat)
        url = f'/api/jobs/{self.job.pk}/fees/{fee.pk}/'
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn('message', resp.data)
        self.assertFalse(Fee.objects.filter(pk=fee.pk).exists())

    def test_patch_fee_not_on_job_is_404(self):
        other = Job.objects.create(job_number='JOB-FEE-OTHER', contact=self.job.contact)
        fee = Fee.objects.create(job=other, description='x', quantity=Decimal('1'),
                                 unit_rate=Decimal('10.00'), accounting_category=self.cat)
        url = f'/api/jobs/{self.job.pk}/fees/{fee.pk}/'
        resp = self.client.patch(url, {'unit_rate': '5'}, format='json')
        self.assertEqual(resp.status_code, 404, resp.content)


class FeeApiPermissionTest(APITestCase):
    """Fees fall on the jobs-viewset default gate (CanManageJobOrPM), unlike
    tasks/materials which are carved out as worker self-service."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='Services', code='FEEPERM1')
        contact = Contact.objects.create(first_name='P', last_name='T')
        biz = Business.objects.create(business_name='PBiz', default_contact=contact)
        contact.business = biz
        contact.save()
        self.contact = contact
        self.job = Job.objects.create(job_number='JOB-FEEPERM-1', contact=contact)

    def test_worker_without_atoms_is_forbidden(self):
        worker = User.objects.create_user('fee_worker', password='p')
        worker.user_permissions.clear()
        self.client.force_login(worker)
        url = f'/api/jobs/{self.job.pk}/fees/'
        resp = self.client.post(url, {
            'unit_rate': '10', 'accounting_category': self.cat.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_project_manager_can_create_fee(self):
        pm = User.objects.create_user('fee_pm', password='p')
        self.job.project_manager = pm
        self.job.save()
        self.client.force_login(pm)
        url = f'/api/jobs/{self.job.pk}/fees/'
        resp = self.client.post(url, {
            'unit_rate': '10', 'accounting_category': self.cat.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_unauthenticated_is_rejected(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        url = f'/api/jobs/{self.job.pk}/fees/'
        resp = anon.post(url, {'unit_rate': '10'}, format='json')
        self.assertIn(resp.status_code, [401, 403])

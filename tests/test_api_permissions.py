from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient
from tests.base import BaseTestCase

User = get_user_model()


def _assign_group_permissions():
    """Assign permission atoms to groups (fixture loads groups without permissions)."""
    ct = ContentType.objects.get(app_label='core', model='user')

    def get_perms(*codenames):
        return Permission.objects.filter(codename__in=codenames, content_type=ct)

    groups_config = {
        'Admin': [
            'can_manage_jobs', 'can_view_jobs', 'can_manage_invoicing',
            'can_manage_purchasing', 'can_manage_time',
            'can_approve_expenses', 'can_manage_config',
        ],
        'Manager': ['can_view_jobs', 'can_manage_jobs', 'can_manage_time', 'can_approve_expenses'],
        'Worker': ['can_view_jobs'],
        'Bookkeeper': ['can_view_jobs', 'can_manage_invoicing', 'can_manage_purchasing', 'can_approve_expenses'],
    }

    for group_name, perm_codenames in groups_config.items():
        group = Group.objects.get(name=group_name)
        group.permissions.set(get_perms(*perm_codenames))


class APIPermissionTestBase(BaseTestCase):
    """Base class for API permission tests."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

        # Fixture loads groups without permissions — wire them up
        _assign_group_permissions()

        # Worker: can_view_jobs only
        self.worker = User.objects.get(username='johnq')
        self.worker.set_password('testpass')
        self.worker.save()

        # Manager: can_view_jobs, can_manage_jobs, can_manage_time, can_approve_expenses
        self.manager = User.objects.get(username='manager1')
        self.manager.set_password('testpass')
        self.manager.save()

        # Superuser: everything
        self.admin = User.objects.get(username='admin')
        self.admin.set_password('testpass')
        self.admin.save()


class JobViewSetPermissionTest(APIPermissionTestBase):

    def test_worker_can_list_jobs(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/jobs/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_create_job(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post('/api/jobs/', {'customer': 1})
        self.assertEqual(response.status_code, 403)

    def test_manager_can_create_job(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.post('/api/jobs/', {'customer': 1})
        self.assertNotEqual(response.status_code, 403)

    def test_unauthenticated_denied(self):
        response = self.client.get('/api/jobs/')
        self.assertIn(response.status_code, [401, 403])


class ContactViewSetPermissionTest(APIPermissionTestBase):

    def test_worker_can_list_contacts(self):
        """Contacts read is IsAuthenticated only — worker can view."""
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/contacts/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_create_contact(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post('/api/contacts/', {'first_name': 'Test', 'last_name': 'User'})
        self.assertEqual(response.status_code, 403)

    def test_manager_can_create_contact(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.post('/api/contacts/', {'first_name': 'Test', 'last_name': 'User'})
        self.assertNotEqual(response.status_code, 403)


class InvoiceViewSetPermissionTest(APIPermissionTestBase):

    def test_worker_can_view_invoices(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/invoices/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_create_invoice(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post('/api/invoices/', {})
        self.assertEqual(response.status_code, 403)

    def test_manager_cannot_create_invoice(self):
        """Manager doesn't have can_manage_invoicing."""
        self.client.force_authenticate(user=self.manager)
        response = self.client.post('/api/invoices/', {})
        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_invoice(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post('/api/invoices/', {})
        self.assertNotEqual(response.status_code, 403)


class PurchaseOrderPermissionTest(APIPermissionTestBase):

    def test_worker_can_view_purchase_orders(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/purchase-orders/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_create_po(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post('/api/purchase-orders/', {})
        self.assertEqual(response.status_code, 403)

    def test_manager_cannot_create_po(self):
        """Manager doesn't have can_manage_purchasing."""
        self.client.force_authenticate(user=self.manager)
        response = self.client.post('/api/purchase-orders/', {})
        self.assertEqual(response.status_code, 403)


class SettingsPermissionTest(APIPermissionTestBase):

    def test_worker_cannot_access_settings(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/settings/')
        self.assertEqual(response.status_code, 403)

    def test_manager_cannot_access_settings(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.get('/api/settings/')
        self.assertEqual(response.status_code, 403)

    def test_admin_can_access_settings(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/settings/')
        self.assertEqual(response.status_code, 200)


class TemplateConfigPermissionTest(APIPermissionTestBase):

    def test_worker_can_list_templates(self):
        """Templates read is IsAuthenticated — worker can view."""
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/work-order-templates/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_create_template(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post('/api/work-order-templates/', {'template_name': 'Test'})
        self.assertEqual(response.status_code, 403)

    def test_worker_can_list_line_item_types(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/line-item-types/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_create_line_item_type(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post('/api/line-item-types/', {'name': 'Test'})
        self.assertEqual(response.status_code, 403)


class PriceListItemPermissionTest(APIPermissionTestBase):

    def test_worker_can_list_price_list_items(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/price-list-items/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_create_price_list_item(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post('/api/price-list-items/', {'code': 'TST', 'description': 'Test'})
        self.assertEqual(response.status_code, 403)


class EstimatePermissionTest(APIPermissionTestBase):

    def test_worker_can_list_estimates(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/estimates/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_create_estimate(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post('/api/estimates/', {'job': 1})
        self.assertEqual(response.status_code, 403)


class WorksheetPermissionTest(APIPermissionTestBase):

    def test_worker_can_list_worksheets(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/est-worksheets/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_create_worksheet(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post('/api/est-worksheets/', {'job': 1})
        self.assertEqual(response.status_code, 403)


class WorkOrderPermissionTest(APIPermissionTestBase):

    def test_worker_can_list_work_orders(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/work-orders/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_create_work_order(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post('/api/work-orders/', {'job': 1})
        self.assertEqual(response.status_code, 403)


class SearchPermissionTest(APIPermissionTestBase):

    def test_worker_can_search(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/search/?q=test')
        self.assertEqual(response.status_code, 200)

    def test_unauthenticated_cannot_search(self):
        response = self.client.get('/api/search/?q=test')
        self.assertIn(response.status_code, [401, 403])


class EmailPermissionTest(APIPermissionTestBase):

    def test_worker_can_list_emails(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/emails/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_link_email_to_job(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post('/api/emails/1/link-to-job/', {'job_id': 1})
        # 403 (permission denied) — not 200/201
        self.assertEqual(response.status_code, 403)

    def test_worker_cannot_create_job_from_email(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post('/api/emails/1/create-job/', {'contact': 1})
        self.assertEqual(response.status_code, 403)

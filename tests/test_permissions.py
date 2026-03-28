from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from tests.base import BaseTestCase

User = get_user_model()


class PermissionAtomsTest(BaseTestCase):
    """Verify custom permission atoms exist after migration."""

    EXPECTED_ATOMS = [
        'can_view_financials',
        'can_manage_jobs',
        'can_manage_financials',
        'can_manage_time',
        'can_approve_expenses',
        'can_manage_config',
    ]

    def test_all_permission_atoms_exist(self):
        """All 6 permission atoms should exist in auth_permission table."""
        for codename in self.EXPECTED_ATOMS:
            with self.subTest(codename=codename):
                self.assertTrue(
                    Permission.objects.filter(
                        codename=codename,
                        content_type__app_label='core',
                    ).exists(),
                    f"Permission '{codename}' not found"
                )

    def test_user_can_be_assigned_permission(self):
        """A permission atom can be assigned to a user and checked via has_perm."""
        user = User.objects.create_user(username='testuser', password='testpass')
        perm = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
        user.user_permissions.add(perm)
        user = User.objects.get(pk=user.pk)
        self.assertTrue(user.has_perm('core.can_manage_jobs'))
        self.assertFalse(user.has_perm('core.can_manage_financials'))


from apps.api.permissions import (
    atom_permission, CanManageJobs, CanViewFinancials,
    CanManageFinancials, CanManageTime, CanApproveExpenses, CanManageConfig,
)


class AtomPermissionFactoryTest(BaseTestCase):
    """Test the DRF permission class factory."""

    def _make_request(self, user):
        """Create a fake request object with the given user."""
        from rest_framework.test import APIRequestFactory
        factory = APIRequestFactory()
        request = factory.get('/')
        request.user = user
        return request

    def test_factory_creates_permission_class(self):
        """atom_permission returns a class with has_permission method."""
        PermClass = atom_permission('can_manage_jobs')
        self.assertTrue(hasattr(PermClass, 'has_permission'))

    def test_permission_denied_without_perm(self):
        """User without the permission is denied."""
        user = User.objects.create_user(username='testuser', password='testpass')
        request = self._make_request(user)
        perm = CanManageJobs()
        self.assertFalse(perm.has_permission(request, None))

    def test_permission_granted_with_direct_perm(self):
        """User with direct permission is allowed."""
        user = User.objects.create_user(username='testuser', password='testpass')
        perm_obj = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
        user.user_permissions.add(perm_obj)
        user = User.objects.get(pk=user.pk)
        request = self._make_request(user)
        perm = CanManageJobs()
        self.assertTrue(perm.has_permission(request, None))

    def test_superuser_has_all_permissions(self):
        """Superuser passes all permission checks."""
        user = User.objects.create_superuser(username='supertest', password='testpass')
        request = self._make_request(user)
        self.assertTrue(CanManageJobs().has_permission(request, None))
        self.assertTrue(CanManageFinancials().has_permission(request, None))
        self.assertTrue(CanManageConfig().has_permission(request, None))

    def test_all_constants_are_defined(self):
        """All 6 permission class constants are importable and functional."""
        classes = [
            CanManageJobs, CanViewFinancials, CanManageFinancials,
            CanManageTime, CanApproveExpenses, CanManageConfig,
        ]
        self.assertEqual(len(classes), 6)
        for cls in classes:
            self.assertTrue(hasattr(cls, 'has_permission'))


from django.test import Client


class HTMLViewPermissionTest(BaseTestCase):
    """Test that HTML views require login and correct permissions."""

    def setUp(self):
        super().setUp()
        self.client = Client()

        # Worker-equivalent: no atoms, just authenticated
        self.worker = User.objects.create_user(username='worker', password='testpass')

        # Manager-equivalent: can_manage_jobs
        self.manager = User.objects.create_user(username='manager', password='testpass')
        perm = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
        self.manager.user_permissions.add(perm)
        self.manager = User.objects.get(pk=self.manager.pk)  # clear cache

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.get('/jobs/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_unauthenticated_redirects_from_contacts(self):
        response = self.client.get('/contacts/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_unauthenticated_redirects_from_invoicing(self):
        response = self.client.get('/invoicing/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_unauthenticated_redirects_from_purchasing(self):
        response = self.client.get('/purchasing/purchase-orders/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_unauthenticated_redirects_from_settings(self):
        response = self.client.get('/settings/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_worker_can_view_job_list(self):
        self.client.login(username='worker', password='testpass')
        response = self.client.get('/jobs/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_access_settings(self):
        self.client.login(username='worker', password='testpass')
        response = self.client.get('/settings/')
        self.assertEqual(response.status_code, 403)

    def test_worker_can_view_invoice_list(self):
        self.client.login(username='worker', password='testpass')
        response = self.client.get('/invoicing/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_reorder_invoice_line_items(self):
        """Worker without can_manage_financials cannot reorder invoice line items."""
        self.client.login(username='worker', password='testpass')
        # Use a non-existent ID; permission check happens before object lookup
        response = self.client.post('/invoicing/999/reorder-line-item/999/up/')
        self.assertEqual(response.status_code, 403)

    def test_worker_can_view_purchase_order_list(self):
        self.client.login(username='worker', password='testpass')
        response = self.client.get('/purchasing/purchase-orders/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_create_purchase_order(self):
        """Worker without can_manage_financials cannot create POs."""
        self.client.login(username='worker', password='testpass')
        response = self.client.get('/purchasing/purchase-orders/create/')
        self.assertEqual(response.status_code, 403)

    def test_worker_cannot_create_job(self):
        """Worker without can_manage_jobs cannot create jobs."""
        self.client.login(username='worker', password='testpass')
        response = self.client.get('/jobs/create/')
        self.assertEqual(response.status_code, 403)

    def test_manager_can_create_job(self):
        """Manager with can_manage_jobs can create jobs."""
        self.client.login(username='manager', password='testpass')
        response = self.client.get('/jobs/create/')
        self.assertEqual(response.status_code, 200)

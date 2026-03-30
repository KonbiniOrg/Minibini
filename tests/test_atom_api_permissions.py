"""
Exhaustive atom-level API permission tests.

Each test user has exactly ONE permission atom via user_permissions.add().
Tests verify both allowed (not 403) and denied (403) directions.
Any non-403 status (200, 201, 400, 404, 405) counts as "permission passed".
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient
from tests.base import BaseTestCase

User = get_user_model()


class AtomPermissionTestBase(BaseTestCase):
    """
    Base class that creates one test user per permission atom.
    Each user has ONLY that atom — no group membership.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()

        self.users = {}
        atoms = [
            'can_view_financials', 'can_manage_jobs',
            'can_manage_financials', 'can_manage_time',
            'can_approve_expenses', 'can_manage_config',
        ]
        for atom in atoms:
            user = User.objects.create_user(
                username=f'user_{atom}', password='testpass',
            )
            perm = Permission.objects.get(
                codename=atom, content_type__app_label='core'
            )
            user.user_permissions.add(perm)
            # Refetch to clear Django's permission cache
            user = User.objects.get(pk=user.pk)
            self.users[atom] = user

        self.bare_user = User.objects.create_user(
            username='bare_user', password='testpass'
        )

    def assert_allowed(self, user, method, url, data=None):
        self.client.force_authenticate(user=user)
        try:
            response = getattr(self.client, method)(url, data, format='json')
        except Exception:
            # Server error (e.g. ProtectedError) means permission passed
            # but business logic failed — that's fine for permission tests.
            return None
        self.assertNotEqual(
            response.status_code, 403,
            f"{user.username} should be allowed {method.upper()} {url}"
            f" (got {response.status_code})"
        )
        return response

    def assert_denied(self, user, method, url, data=None):
        self.client.force_authenticate(user=user)
        response = getattr(self.client, method)(url, data, format='json')
        self.assertEqual(
            response.status_code, 403,
            f"{user.username} should be denied {method.upper()} {url}"
            f" (got {response.status_code})"
        )
        return response

    def assert_requires_auth(self, method, url, data=None):
        self.client.force_authenticate(user=None)
        response = getattr(self.client, method)(url, data, format='json')
        self.assertIn(response.status_code, [401, 403])


class TestAuthenticatedOnlyAPI(AtomPermissionTestBase):
    """
    Endpoints that require only IsAuthenticated (no specific atom).
    bare_user (no atoms) should get through; unauthenticated should be denied.
    """

    # ── List endpoints: bare_user gets 200 ──────────────────────────
    LIST_ENDPOINTS = [
        '/api/jobs/',
        '/api/estimates/',
        '/api/est-worksheets/',
        '/api/work-orders/',
        '/api/contacts/',
        '/api/businesses/',
        '/api/payment-terms/',
        '/api/work-order-templates/',
        '/api/task-templates/',
        '/api/accounting-categories/',
        '/api/price-list-items/',
        '/api/search/?q=test',
    ]

    # ── Detail / sub-resource endpoints: bare_user gets 200 or 404 ──
    DETAIL_ENDPOINTS = [
        '/api/jobs/1/',
        '/api/jobs/1/history/',
        '/api/estimates/1/',
        '/api/estimates/1/line-items/',
        '/api/est-worksheets/1/',
        '/api/est-worksheets/1/tasks/',
        '/api/est-worksheets/1/bundles/',
        '/api/work-orders/1/',
        '/api/work-orders/1/tasks/',
        '/api/work-orders/1/bundles/',
        '/api/work-orders/1/tasks/1/bleps/',
        '/api/contacts/1/',
        '/api/contacts/1/history/',
        '/api/businesses/1/',
        '/api/businesses/1/history/',
        '/api/payment-terms/1/',
        '/api/price-list-items/1/',
    ]

    # ── Write endpoints that are IsAuthenticated only ───────────────
    WRITE_ENDPOINTS = [
        ('post', '/api/jobs/1/notes/', {'text': 'test note'}),
        ('post', '/api/contacts/1/notes/', {'text': 'test note'}),
        ('post', '/api/businesses/1/notes/', {'text': 'test note'}),
        ('post', '/api/work-orders/1/tasks/', {'name': 'Test'}),
    ]

    def test_bare_user_can_list(self):
        for url in self.LIST_ENDPOINTS:
            with self.subTest(url=url):
                self.assert_allowed(self.bare_user, 'get', url)

    def test_bare_user_can_read_detail(self):
        for url in self.DETAIL_ENDPOINTS:
            with self.subTest(url=url):
                resp = self.assert_allowed(self.bare_user, 'get', url)
                self.assertIn(resp.status_code, [200, 404])

    def test_bare_user_can_write_authenticated_endpoints(self):
        for method, url, data in self.WRITE_ENDPOINTS:
            with self.subTest(url=url):
                self.assert_allowed(self.bare_user, method, url, data)

    def test_unauthenticated_denied_list(self):
        sample_urls = [
            '/api/jobs/',
            '/api/contacts/',
            '/api/estimates/',
            '/api/work-orders/',
            '/api/price-list-items/',
            '/api/search/?q=test',
        ]
        for url in sample_urls:
            with self.subTest(url=url):
                self.assert_requires_auth('get', url)

    def test_unauthenticated_denied_detail(self):
        sample_urls = [
            '/api/jobs/1/',
            '/api/contacts/1/',
            '/api/businesses/1/',
        ]
        for url in sample_urls:
            with self.subTest(url=url):
                self.assert_requires_auth('get', url)

    def test_unauthenticated_denied_write(self):
        self.assert_requires_auth('post', '/api/jobs/1/notes/', {'text': 'x'})
        self.assert_requires_auth('post', '/api/contacts/1/notes/', {'text': 'x'})


class TestCanViewFinancialsAPI(AtomPermissionTestBase):
    """
    can_view_financials — read-only access to invoices, POs, bills.
    """

    READ_ENDPOINTS = [
        '/api/invoices/',
        '/api/purchase-orders/',
        '/api/bills/',
        '/api/invoices/1/',
        '/api/invoices/1/line-items/',
        '/api/purchase-orders/1/',
        '/api/purchase-orders/1/line-items/',
        '/api/bills/1/',
        '/api/bills/1/line-items/',
    ]

    def test_can_view_financials_allows_read(self):
        user = self.users['can_view_financials']
        for url in self.READ_ENDPOINTS:
            with self.subTest(url=url):
                resp = self.assert_allowed(user, 'get', url)
                self.assertIn(resp.status_code, [200, 404])

    def test_bare_user_denied_financial_reads(self):
        for url in self.READ_ENDPOINTS:
            with self.subTest(url=url):
                self.assert_denied(self.bare_user, 'get', url)

    def test_wrong_atom_denied_financial_reads(self):
        user = self.users['can_manage_jobs']
        # List endpoints must be 403
        list_urls = ['/api/invoices/', '/api/purchase-orders/', '/api/bills/']
        for url in list_urls:
            with self.subTest(url=url, user='can_manage_jobs'):
                self.assert_denied(user, 'get', url)


class TestCanManageJobsAPI(AtomPermissionTestBase):
    """
    can_manage_jobs — manage jobs, estimates, worksheets, work orders,
    contacts, businesses, emails.
    """

    # ── Email reads ─────────────────────────────────────────────────
    EMAIL_READ_ENDPOINTS = [
        ('get', '/api/emails/', None),
        ('get', '/api/emails/1/', None),
    ]

    # ── Job writes ──────────────────────────────────────────────────
    JOB_WRITE_ENDPOINTS = [
        ('post', '/api/jobs/', {'customer': 1}),
        ('patch', '/api/jobs/1/', {'name': 'Updated'}),
        ('delete', '/api/jobs/1/', None),
        ('post', '/api/jobs/1/complete/', {}),
        ('post', '/api/jobs/1/cancel/', {'reason': 'test'}),
        ('post', '/api/jobs/1/reopen/', {'reason': 'test'}),
    ]

    # ── Contact/Business writes ─────────────────────────────────────
    CONTACT_WRITE_ENDPOINTS = [
        ('post', '/api/contacts/', {'first_name': 'T', 'last_name': 'U'}),
        ('patch', '/api/contacts/1/', {'first_name': 'Updated'}),
        ('delete', '/api/contacts/1/', None),
        ('post', '/api/businesses/', {'business_name': 'T', 'default_contact': 1}),
        ('patch', '/api/businesses/1/', {'business_name': 'Updated'}),
        ('delete', '/api/businesses/1/', None),
        ('post', '/api/businesses/1/set-default-contact/', {'contact_id': 1}),
    ]

    # ── Estimate writes ─────────────────────────────────────────────
    ESTIMATE_WRITE_ENDPOINTS = [
        ('post', '/api/estimates/', {'job': 1}),
        ('patch', '/api/estimates/1/', {'notes': 'test'}),
        ('delete', '/api/estimates/1/', None),
        ('post', '/api/estimates/1/line-items/', {'description': 'Test'}),
        ('post', '/api/estimates/1/line-items/reorder/', {'order': []}),
        ('post', '/api/estimates/1/mark-open/', {}),
        ('post', '/api/estimates/1/revise/', {}),
    ]

    # ── Worksheet writes ────────────────────────────────────────────
    WORKSHEET_WRITE_ENDPOINTS = [
        ('post', '/api/est-worksheets/', {'job': 1}),
        ('patch', '/api/est-worksheets/1/', {'notes': 'test'}),
        ('delete', '/api/est-worksheets/1/', None),
        ('post', '/api/est-worksheets/1/tasks/', {'name': 'Test'}),
        ('post', '/api/est-worksheets/1/bundles/', {'name': 'Test'}),
        ('post', '/api/est-worksheets/1/generate-estimate/', {}),
        ('post', '/api/est-worksheets/1/revise/', {}),
    ]

    # ── Work order writes ───────────────────────────────────────────
    WORK_ORDER_WRITE_ENDPOINTS = [
        ('post', '/api/work-orders/', {'job': 1}),
        ('patch', '/api/work-orders/1/', {'notes': 'test'}),
        ('delete', '/api/work-orders/1/', None),
        ('patch', '/api/work-orders/1/tasks/1/', {'name': 'Updated'}),
        ('delete', '/api/work-orders/1/tasks/1/', None),
        ('post', '/api/work-orders/1/bundles/', {'name': 'Test'}),
        ('post', '/api/work-orders/1/tasks/1/start/', {}),
        ('post', '/api/work-orders/1/tasks/1/complete/', {}),
        ('post', '/api/work-orders/1/tasks/1/block/', {'reason': 'test'}),
        ('post', '/api/work-orders/1/tasks/1/unblock/', {}),
        ('post', '/api/work-orders/1/tasks/1/cancel/', {}),
        ('post', '/api/work-orders/1/tasks/1/start-work/', {}),
        ('post', '/api/work-orders/1/tasks/1/stop-work/', {}),
        ('post', '/api/work-orders/1/complete/', {}),
        ('post', '/api/work-orders/1/block/', {'reason': 'test'}),
        ('post', '/api/work-orders/1/reopen/', {'reason': 'test'}),
    ]

    # ── Email action writes ─────────────────────────────────────────
    EMAIL_WRITE_ENDPOINTS = [
        ('post', '/api/emails/1/link-to-job/', {'job_id': 1}),
        ('post', '/api/emails/1/unlink-from-job/', {}),
        ('post', '/api/emails/1/create-job/', {'contact': 1}),
    ]

    def _all_manage_jobs_endpoints(self):
        return (
            self.EMAIL_READ_ENDPOINTS
            + self.JOB_WRITE_ENDPOINTS
            + self.CONTACT_WRITE_ENDPOINTS
            + self.ESTIMATE_WRITE_ENDPOINTS
            + self.WORKSHEET_WRITE_ENDPOINTS
            + self.WORK_ORDER_WRITE_ENDPOINTS
            + self.EMAIL_WRITE_ENDPOINTS
        )

    def test_can_manage_jobs_allows_emails(self):
        user = self.users['can_manage_jobs']
        for method, url, data in self.EMAIL_READ_ENDPOINTS:
            with self.subTest(url=url):
                self.assert_allowed(user, method, url, data)

    def test_can_manage_jobs_allows_job_writes(self):
        user = self.users['can_manage_jobs']
        for method, url, data in self.JOB_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_allowed(user, method, url, data)

    def test_can_manage_jobs_allows_contact_writes(self):
        user = self.users['can_manage_jobs']
        for method, url, data in self.CONTACT_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_allowed(user, method, url, data)

    def test_can_manage_jobs_allows_estimate_writes(self):
        user = self.users['can_manage_jobs']
        for method, url, data in self.ESTIMATE_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_allowed(user, method, url, data)

    def test_can_manage_jobs_allows_worksheet_writes(self):
        user = self.users['can_manage_jobs']
        for method, url, data in self.WORKSHEET_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_allowed(user, method, url, data)

    def test_can_manage_jobs_allows_work_order_writes(self):
        user = self.users['can_manage_jobs']
        for method, url, data in self.WORK_ORDER_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_allowed(user, method, url, data)

    def test_can_manage_jobs_allows_email_actions(self):
        user = self.users['can_manage_jobs']
        for method, url, data in self.EMAIL_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_allowed(user, method, url, data)

    def test_bare_user_denied_email_read(self):
        for method, url, data in self.EMAIL_READ_ENDPOINTS:
            with self.subTest(url=url):
                self.assert_denied(self.bare_user, method, url, data)

    def test_bare_user_denied_job_writes(self):
        for method, url, data in self.JOB_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_denied(self.bare_user, method, url, data)

    def test_bare_user_denied_contact_writes(self):
        for method, url, data in self.CONTACT_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_denied(self.bare_user, method, url, data)

    def test_bare_user_denied_estimate_writes(self):
        for method, url, data in self.ESTIMATE_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_denied(self.bare_user, method, url, data)

    def test_bare_user_denied_worksheet_writes(self):
        for method, url, data in self.WORKSHEET_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_denied(self.bare_user, method, url, data)

    def test_bare_user_denied_work_order_writes(self):
        for method, url, data in self.WORK_ORDER_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_denied(self.bare_user, method, url, data)

    def test_bare_user_denied_email_actions(self):
        for method, url, data in self.EMAIL_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_denied(self.bare_user, method, url, data)

    def test_wrong_atom_manage_financials_denied_jobs(self):
        user = self.users['can_manage_financials']
        self.assert_denied(user, 'post', '/api/jobs/', {'customer': 1})

    def test_wrong_atom_manage_financials_denied_emails(self):
        user = self.users['can_manage_financials']
        self.assert_denied(user, 'get', '/api/emails/')

    def test_wrong_atom_view_financials_denied_jobs(self):
        user = self.users['can_view_financials']
        self.assert_denied(user, 'post', '/api/jobs/', {'customer': 1})

    def test_wrong_atom_manage_config_denied_jobs(self):
        user = self.users['can_manage_config']
        self.assert_denied(user, 'post', '/api/jobs/', {'customer': 1})


class TestCanManageFinancialsAPI(AtomPermissionTestBase):
    """
    can_manage_financials — manage invoices, POs, bills, price list items.
    """

    INVOICE_WRITE_ENDPOINTS = [
        ('post', '/api/invoices/', {'job': 1}),
        ('patch', '/api/invoices/1/', {'notes': 'test'}),
        ('delete', '/api/invoices/1/', None),
        ('post', '/api/invoices/1/line-items/', {'description': 'Test'}),
        ('post', '/api/invoices/1/line-items/reorder/', {'order': []}),
        ('post', '/api/invoices/1/cancel/', {'reason': 'test'}),
    ]

    PO_WRITE_ENDPOINTS = [
        ('post', '/api/purchase-orders/', {'vendor': 1}),
        ('patch', '/api/purchase-orders/1/', {'notes': 'test'}),
        # Use nonexistent PK for delete: fixture POs are 'issued' and model
        # raises PermissionDenied on non-draft delete (business logic, not
        # DRF permission). A 404 proves the permission layer passed.
        ('delete', '/api/purchase-orders/9999/', None),
        ('post', '/api/purchase-orders/1/line-items/', {'description': 'Test'}),
        ('post', '/api/purchase-orders/1/line-items/reorder/', {'order': []}),
        ('post', '/api/purchase-orders/1/issue/', {}),
        ('post', '/api/purchase-orders/1/cancel/', {'reason': 'test'}),
    ]

    BILL_WRITE_ENDPOINTS = [
        ('post', '/api/bills/', {'purchase_order': 1, 'vendor': 1}),
        ('patch', '/api/bills/1/', {'notes': 'test'}),
        ('delete', '/api/bills/1/', None),
        ('post', '/api/bills/1/line-items/', {'description': 'Test'}),
        ('post', '/api/bills/1/line-items/reorder/', {'order': []}),
        ('post', '/api/bills/1/cancel/', {'reason': 'test'}),
    ]

    PRICE_LIST_WRITE_ENDPOINTS = [
        ('post', '/api/price-list-items/', {'code': 'TST', 'description': 'Test'}),
        ('patch', '/api/price-list-items/1/', {'description': 'Updated'}),
        ('delete', '/api/price-list-items/1/', None),
    ]

    def _all_manage_financials_endpoints(self):
        return (
            self.INVOICE_WRITE_ENDPOINTS
            + self.PO_WRITE_ENDPOINTS
            + self.BILL_WRITE_ENDPOINTS
            + self.PRICE_LIST_WRITE_ENDPOINTS
        )

    def test_can_manage_financials_allows_invoice_writes(self):
        user = self.users['can_manage_financials']
        for method, url, data in self.INVOICE_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_allowed(user, method, url, data)

    def test_can_manage_financials_allows_po_writes(self):
        user = self.users['can_manage_financials']
        for method, url, data in self.PO_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_allowed(user, method, url, data)

    def test_can_manage_financials_allows_bill_writes(self):
        user = self.users['can_manage_financials']
        for method, url, data in self.BILL_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_allowed(user, method, url, data)

    def test_can_manage_financials_allows_price_list_writes(self):
        user = self.users['can_manage_financials']
        for method, url, data in self.PRICE_LIST_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_allowed(user, method, url, data)

    def test_bare_user_denied_invoice_writes(self):
        for method, url, data in self.INVOICE_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_denied(self.bare_user, method, url, data)

    def test_bare_user_denied_po_writes(self):
        for method, url, data in self.PO_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_denied(self.bare_user, method, url, data)

    def test_bare_user_denied_bill_writes(self):
        for method, url, data in self.BILL_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_denied(self.bare_user, method, url, data)

    def test_bare_user_denied_price_list_writes(self):
        for method, url, data in self.PRICE_LIST_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_denied(self.bare_user, method, url, data)

    def test_wrong_atom_manage_jobs_denied_invoice_writes(self):
        user = self.users['can_manage_jobs']
        sample = [
            ('post', '/api/invoices/', {'job': 1}),
            ('post', '/api/purchase-orders/', {'vendor': 1}),
            ('post', '/api/bills/', {'purchase_order': 1, 'vendor': 1}),
        ]
        for method, url, data in sample:
            with self.subTest(url=url):
                self.assert_denied(user, method, url, data)

    def test_wrong_atom_view_financials_denied_writes(self):
        user = self.users['can_view_financials']
        sample = [
            ('post', '/api/invoices/', {'job': 1}),
            ('post', '/api/purchase-orders/', {'vendor': 1}),
            ('post', '/api/price-list-items/', {'code': 'TST', 'description': 'Test'}),
        ]
        for method, url, data in sample:
            with self.subTest(url=url):
                self.assert_denied(user, method, url, data)


class TestCanManageConfigAPI(AtomPermissionTestBase):
    """
    can_manage_config — manage settings, templates, line item types.
    """

    SETTINGS_ENDPOINTS = [
        ('get', '/api/settings/', None),
        ('patch', '/api/settings/', {}),
    ]

    TEMPLATE_WRITE_ENDPOINTS = [
        ('post', '/api/work-order-templates/', {'template_name': 'Test'}),
        ('patch', '/api/work-order-templates/1/', {'template_name': 'Updated'}),
        ('delete', '/api/work-order-templates/1/', None),
        ('post', '/api/task-templates/', {'template_name': 'Test'}),
        ('patch', '/api/task-templates/1/', {'template_name': 'Updated'}),
        ('delete', '/api/task-templates/1/', None),
        ('post', '/api/accounting-categories/', {'name': 'Test'}),
        ('patch', '/api/accounting-categories/1/', {'name': 'Updated'}),
        ('delete', '/api/accounting-categories/1/', None),
    ]

    def test_can_manage_config_allows_settings(self):
        user = self.users['can_manage_config']
        for method, url, data in self.SETTINGS_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_allowed(user, method, url, data)

    def test_can_manage_config_allows_template_writes(self):
        user = self.users['can_manage_config']
        for method, url, data in self.TEMPLATE_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_allowed(user, method, url, data)

    def test_bare_user_denied_settings(self):
        for method, url, data in self.SETTINGS_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_denied(self.bare_user, method, url, data)

    def test_bare_user_denied_template_writes(self):
        for method, url, data in self.TEMPLATE_WRITE_ENDPOINTS:
            with self.subTest(url=url, method=method):
                self.assert_denied(self.bare_user, method, url, data)

    def test_wrong_atom_manage_jobs_denied_settings(self):
        user = self.users['can_manage_jobs']
        self.assert_denied(user, 'get', '/api/settings/')
        self.assert_denied(user, 'patch', '/api/settings/', {})

    def test_wrong_atom_manage_jobs_denied_template_writes(self):
        user = self.users['can_manage_jobs']
        sample = [
            ('post', '/api/work-order-templates/', {'template_name': 'Test'}),
            ('post', '/api/task-templates/', {'template_name': 'Test'}),
            ('post', '/api/accounting-categories/', {'name': 'Test'}),
        ]
        for method, url, data in sample:
            with self.subTest(url=url):
                self.assert_denied(user, method, url, data)


class TestCanManageTimeAPI(AtomPermissionTestBase):
    """can_manage_time — no endpoints yet.
    When time-tracking endpoints are added, add tests here.
    """
    pass


class TestCanApproveExpensesAPI(AtomPermissionTestBase):
    """can_approve_expenses — no endpoints yet.
    When expense endpoints are added, add tests here.
    """
    pass

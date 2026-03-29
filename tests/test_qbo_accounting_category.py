from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from apps.core.models import AccountingCategory

User = get_user_model()


class AccountingCategoryMappingAPITest(TestCase):
    """Test updating QBO account mappings via API."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(codename='can_manage_config', content_type__app_label='core')
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)

        self.category = AccountingCategory.objects.create(
            code='SVC', name='Service', taxable=False
        )

    def test_patch_qbo_income_account(self):
        """Can set QBO income account via PATCH."""
        self.client.login(username='admin', password='testpass')
        response = self.client.patch(
            f'/api/accounting-categories/{self.category.pk}/',
            data='{"qbo_item_id": "42"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.category.refresh_from_db()
        self.assertEqual(self.category.qbo_item_id, '42')

    def test_patch_qbo_expense_account(self):
        """Can set QBO expense account via PATCH."""
        self.client.login(username='admin', password='testpass')
        response = self.client.patch(
            f'/api/accounting-categories/{self.category.pk}/',
            data='{"qbo_expense_account_id": "99"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.category.refresh_from_db()
        self.assertEqual(self.category.qbo_expense_account_id, '99')

    def test_get_includes_qbo_fields(self):
        """GET response includes QBO mapping fields."""
        self.client.login(username='admin', password='testpass')
        response = self.client.get(f'/api/accounting-categories/{self.category.pk}/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('qbo_item_id', data)
        self.assertIn('qbo_expense_account_id', data)


class AccountingCategoryQBOFieldsTest(TestCase):
    """Test QBO account mapping fields on AccountingCategory."""

    def test_qbo_item_id_default_blank(self):
        lit = AccountingCategory.objects.create(code='TST', name='Test')
        self.assertEqual(lit.qbo_item_id, '')

    def test_qbo_expense_account_id_default_blank(self):
        lit = AccountingCategory.objects.create(code='TST', name='Test')
        self.assertEqual(lit.qbo_expense_account_id, '')

    def test_can_set_both_account_ids(self):
        """A category can map to both income and expense accounts."""
        lit = AccountingCategory.objects.create(
            code='MAT', name='Materials',
            qbo_item_id='42',
            qbo_expense_account_id='99',
        )
        lit.refresh_from_db()
        self.assertEqual(lit.qbo_item_id, '42')
        self.assertEqual(lit.qbo_expense_account_id, '99')

    def test_can_set_income_only(self):
        """A service category maps to income only."""
        lit = AccountingCategory.objects.create(
            code='SVC', name='Service',
            qbo_item_id='42',
        )
        self.assertEqual(lit.qbo_item_id, '42')
        self.assertEqual(lit.qbo_expense_account_id, '')

from django.test import TestCase
from apps.core.models import AccountingCategory


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

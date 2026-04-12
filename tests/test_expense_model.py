from decimal import Decimal
from datetime import date
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from apps.core.models import AccountingCategory
from apps.expenses.models import Expense

User = get_user_model()


class ExpenseModelTest(TestCase):
    """Test the Expense model — basic creation and fields."""

    def setUp(self):
        self.user = User.objects.create_user(username='worker', password='testpass')
        self.category = AccountingCategory.objects.create(
            code='SUP', name='Shop Supplies', taxable=True,
        )

    def test_create_personal_expense_defaults_submitted(self):
        exp = Expense.objects.create(
            entered_by=self.user,
            purchased_by=self.user,
            amount=Decimal('47.50'),
            purchased_on=date(2026, 4, 5),
            accounting_category=self.category,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
        )
        self.assertEqual(exp.status, Expense.STATUS_SUBMITTED)
        self.assertIsNotNone(exp.created_at)

    def test_create_company_paid_expense_defaults_submitted(self):
        # Company-paid also starts as 'submitted'; the service flips it to
        # 'synced' after the QBO push. The model itself doesn't push.
        exp = Expense.objects.create(
            entered_by=self.user,
            amount=Decimal('218.45'),
            purchased_on=date(2026, 4, 9),
            accounting_category=self.category,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='42',
            description='Sherwin-Williams paint',
        )
        self.assertEqual(exp.status, Expense.STATUS_SUBMITTED)

    def test_purchased_by_can_be_null_for_company_paid(self):
        exp = Expense.objects.create(
            entered_by=self.user,
            amount=Decimal('15.00'),
            purchased_on=date(2026, 4, 9),
            accounting_category=self.category,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            payment_account_id='42',
        )
        self.assertIsNone(exp.purchased_by)

    def test_payment_method_choices_enumerated(self):
        methods = [m for m, _ in Expense.PAYMENT_METHOD_CHOICES]
        self.assertEqual(set(methods), {'company', 'personal'})

    def test_status_choices_enumerated(self):
        statuses = [s for s, _ in Expense.STATUS_CHOICES]
        self.assertEqual(
            set(statuses),
            {'submitted', 'reimbursed', 'rejected', 'synced', 'sync_failed'},
        )

    def test_ordering_is_newest_first_by_purchase_date(self):
        older = Expense.objects.create(
            entered_by=self.user, purchased_by=self.user,
            amount=Decimal('10.00'), purchased_on=date(2026, 3, 1),
            accounting_category=self.category,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
        )
        newer = Expense.objects.create(
            entered_by=self.user, purchased_by=self.user,
            amount=Decimal('20.00'), purchased_on=date(2026, 4, 1),
            accounting_category=self.category,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
        )
        ordered = list(Expense.objects.all())
        self.assertEqual(ordered[0], newer)
        self.assertEqual(ordered[1], older)

    def test_table_name(self):
        self.assertEqual(Expense._meta.db_table, 'expenses')


class ExpenseCleanTest(TestCase):
    """Validation rules in Expense.clean()."""

    def setUp(self):
        self.user = User.objects.create_user(username='worker', password='testpass')
        self.category = AccountingCategory.objects.create(
            code='SUP', name='Shop Supplies',
        )

    def _build(self, **overrides):
        defaults = dict(
            entered_by=self.user,
            amount=Decimal('10.00'),
            purchased_on=date(2026, 4, 1),
            accounting_category=self.category,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
            purchased_by=self.user,
        )
        defaults.update(overrides)
        return Expense(**defaults)

    def test_personal_without_purchased_by_raises(self):
        exp = self._build(purchased_by=None)
        with self.assertRaises(ValidationError) as ctx:
            exp.full_clean()
        self.assertIn('purchased_by', ctx.exception.message_dict)

    def test_personal_with_payment_account_id_raises(self):
        exp = self._build(payment_account_id='42')
        with self.assertRaises(ValidationError) as ctx:
            exp.full_clean()
        self.assertIn('payment_account_id', ctx.exception.message_dict)

    def test_company_without_payment_account_id_raises(self):
        exp = self._build(
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            purchased_by=None,
            payment_account_id='',
        )
        with self.assertRaises(ValidationError) as ctx:
            exp.full_clean()
        self.assertIn('payment_account_id', ctx.exception.message_dict)

    def test_company_with_payment_account_id_passes(self):
        exp = self._build(
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
            purchased_by=None,
            payment_account_id='42',
        )
        exp.full_clean()  # should not raise

    def test_personal_without_payment_account_id_passes(self):
        exp = self._build(payment_account_id='')
        exp.full_clean()  # should not raise

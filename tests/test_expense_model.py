from decimal import Decimal
from datetime import date
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from apps.core.models import AccountingCategory
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.inventory.models import Material
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


class ExpenseJobTest(TestCase):
    """Job is the cost anchor for Expenses; consistency with linked material."""

    def setUp(self):
        self.user = User.objects.create_user(username='worker', password='testpass')
        self.category = AccountingCategory.objects.create(
            code='SUP', name='Shop Supplies',
        )
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com',
        )
        self.job = Job.objects.create(job_number='JOB-EXP-1', contact=self.contact)
        self.other_job = Job.objects.create(job_number='JOB-EXP-2', contact=self.contact)
        self.material = Material.objects.create(
            job=self.job, accounting_category=self.category,
            description='Steel', quantity=Decimal('1.00'),
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

    def test_job_optional(self):
        # job=None (overhead) is allowed
        overhead = self._build(job=None)
        overhead.full_clean()  # should not raise

        # job set (no material) is allowed
        on_job = self._build(job=self.job)
        on_job.full_clean()  # should not raise

    def test_material_job_must_match_expense_job(self):
        exp = self._build(material=self.material, job=self.other_job)
        with self.assertRaises(ValidationError) as ctx:
            exp.full_clean()
        self.assertIn('job', ctx.exception.message_dict)

    def test_material_without_explicit_job_ok(self):
        exp = self._build(material=self.material, job=self.job)
        exp.full_clean()  # should not raise


class ExpenseStockReceiptModelTest(TestCase):
    """Stock-receipt mode validation (inventoried PLI + qty; not mixed with material)."""

    def setUp(self):
        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        from apps.inventory.models import PriceListItem, Material
        self.user = User.objects.create_user(username='sr', password='x')
        self.cat = AccountingCategory.objects.create(code='SR', name='sr')
        self.contact = Contact.objects.create(first_name='T', last_name='C', email='s@t.com')
        self.job = Job.objects.create(job_number='JOB-SR-1', contact=self.contact)
        self.inv_pli = PriceListItem.objects.create(
            code='INV', description='inv', accounting_category=self.cat, is_inventoried=True)
        self.noninv_pli = PriceListItem.objects.create(
            code='NONINV', description='n', accounting_category=self.cat, is_inventoried=False)

    def _build(self, **overrides):
        defaults = dict(
            entered_by=self.user, purchased_by=self.user,
            amount=Decimal('40.00'), purchased_on=date(2026, 4, 1),
            accounting_category=self.cat,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL, job=self.job,
        )
        defaults.update(overrides)
        return Expense(**defaults)

    def test_valid_stock_receipt(self):
        exp = self._build(stock_pli=self.inv_pli, stock_qty=Decimal('3.00'))
        exp.full_clean()  # should not raise

    def test_stock_requires_positive_qty(self):
        exp = self._build(stock_pli=self.inv_pli, stock_qty=None)
        with self.assertRaises(ValidationError):
            exp.full_clean()

    def test_stock_pli_must_be_inventoried(self):
        exp = self._build(stock_pli=self.noninv_pli, stock_qty=Decimal('3.00'))
        with self.assertRaises(ValidationError):
            exp.full_clean()

    def test_cannot_mix_stock_and_material(self):
        from apps.inventory.models import Material
        mat = Material.objects.create(
            job=self.job, accounting_category=self.cat, description='m',
            quantity=Decimal('1.00'))
        exp = self._build(stock_pli=self.inv_pli, stock_qty=Decimal('3.00'), material=mat)
        with self.assertRaises(ValidationError):
            exp.full_clean()

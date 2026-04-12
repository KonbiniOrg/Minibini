from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.core.models import AccountingCategory
from apps.expenses.models import Expense, Reimbursement

User = get_user_model()


class ReimbursementModelTest(TestCase):
    def setUp(self):
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')

    def test_create_reimbursement_defaults_pending(self):
        r = Reimbursement.objects.create(
            purchased_by=self.worker,
            paid_on=date(2026, 4, 11),
            payment_account_id='42',
            created_by=self.admin,
        )
        self.assertEqual(r.status, Reimbursement.STATUS_PENDING)
        self.assertEqual(r.reference_number, '')
        self.assertEqual(r.notes, '')
        self.assertEqual(r.qbo_id, '')

    def test_status_choices_enumerated(self):
        statuses = [s for s, _ in Reimbursement.STATUS_CHOICES]
        self.assertEqual(set(statuses), {'pending', 'synced', 'sync_failed'})

    def test_table_name(self):
        self.assertEqual(Reimbursement._meta.db_table, 'reimbursements')


class ReimbursementTotalTest(TestCase):
    def setUp(self):
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.admin = User.objects.create_user(username='admin', password='testpass')
        self.category = AccountingCategory.objects.create(code='SUP', name='Shop Supplies')

    def _expense(self, amount):
        return Expense.objects.create(
            entered_by=self.worker,
            purchased_by=self.worker,
            amount=Decimal(amount),
            purchased_on=date(2026, 4, 1),
            accounting_category=self.category,
            payment_method=Expense.PAYMENT_METHOD_PERSONAL,
        )

    def test_total_sums_linked_expense_amounts(self):
        batch = Reimbursement.objects.create(
            purchased_by=self.worker,
            paid_on=date(2026, 4, 11),
            payment_account_id='42',
            created_by=self.admin,
        )
        for amt in ('47.50', '62.00', '28.75'):
            e = self._expense(amt)
            e.reimbursement = batch
            e.status = Expense.STATUS_REIMBURSED
            e.save(update_fields=['reimbursement', 'status'])
        self.assertEqual(batch.total, Decimal('138.25'))

    def test_total_is_zero_for_empty_batch(self):
        batch = Reimbursement.objects.create(
            purchased_by=self.worker,
            paid_on=date(2026, 4, 11),
            payment_account_id='42',
            created_by=self.admin,
        )
        self.assertEqual(batch.total, Decimal('0'))

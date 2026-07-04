"""Tests for Expense @history audit tracking (ExpensesHistory partition).

TDD: write failing tests first, then implement.
"""
from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model

from apps.core.models import AccountingCategory, Configuration
from apps.core.history import history_model_for, set_history_context, HistoryContext
from apps.expenses.models import Expense

User = get_user_model()


def _seed_config():
    Configuration.objects.get_or_create(
        key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'},
    )
    Configuration.objects.get_or_create(
        key='job_counter', defaults={'value': '0'},
    )
    Configuration.objects.get_or_create(
        key='qbo_payment_accounts',
        defaults={'value': '[{"id": "1", "name": "Checking"}]'},
    )


def _make_expense(user, cat, amount=Decimal('50.00')):
    """Create a minimal personal expense for testing."""
    return Expense.objects.create(
        entered_by=user,
        purchased_by=user,
        amount=amount,
        purchased_on=date(2026, 6, 1),
        accounting_category=cat,
        payment_method=Expense.PAYMENT_METHOD_PERSONAL,
    )


class ExpensesHistoryModelRoutingTest(TestCase):
    """history_model_for routes 'expense' and 'reimbursement' to ExpensesHistory."""

    def test_history_model_for_expense_returns_expenses_history(self):
        from apps.core.models import ExpensesHistory
        self.assertIs(history_model_for('expense'), ExpensesHistory)

    def test_history_model_for_reimbursement_returns_expenses_history(self):
        from apps.core.models import ExpensesHistory
        self.assertIs(history_model_for('reimbursement'), ExpensesHistory)


class ExpenseAuditTrailTest(TestCase):
    """Editing an expense writes an ExpensesHistory audit row."""

    def setUp(self):
        _seed_config()
        self.user = User.objects.create_user(username='tester', password='pass')
        self.cat = AccountingCategory.objects.create(
            code='SUP', name='Supplies', qbo_expense_account_id='500',
        )
        set_history_context(None)

    def tearDown(self):
        set_history_context(None)

    def test_amount_edit_writes_history_row(self):
        from apps.core.models import ExpensesHistory
        ctx = HistoryContext(user=self.user)
        set_history_context(ctx)

        expense = _make_expense(self.user, self.cat, amount=Decimal('50.00'))
        # Flush the pending create entry
        for entry in ctx.pending:
            from apps.core.history import record_history
            record_history(
                object_type=entry['object_type'],
                entry_type=entry['entry_type'],
                object_id=entry['_instance'].pk,
                changes=entry['changes'],
                user=self.user,
            )
        ctx.pending.clear()

        before_count = ExpensesHistory.objects.filter(
            object_type='expense', object_id=expense.pk,
        ).count()

        expense.amount = Decimal('75.00')
        expense.save()

        # Flush pending entries from the update
        for entry in ctx.pending:
            from apps.core.history import record_history
            record_history(
                object_type=entry['object_type'],
                entry_type=entry['entry_type'],
                object_id=entry['_instance'].pk,
                changes=entry['changes'],
                user=self.user,
            )
        ctx.pending.clear()

        after_count = ExpensesHistory.objects.filter(
            object_type='expense', object_id=expense.pk,
        ).count()
        self.assertGreater(after_count, before_count)

        # The most recent entry should contain the amount change
        latest = ExpensesHistory.objects.filter(
            object_type='expense', object_id=expense.pk,
        ).order_by('-timestamp').first()
        self.assertIsNotNone(latest)
        self.assertIn('amount', latest.changes)
        self.assertEqual(latest.changes['amount']['new'], '75.00')

    def test_status_flip_writes_history_row(self):
        from apps.core.models import ExpensesHistory
        ctx = HistoryContext(user=self.user)
        set_history_context(ctx)

        expense = _make_expense(self.user, self.cat)
        # Flush create entry
        ctx.pending.clear()

        # Snapshot the count before the flip
        before_count = ExpensesHistory.objects.filter(
            object_type='expense', object_id=expense.pk,
        ).count()

        expense.status = Expense.STATUS_REIMBURSED
        expense.save()

        # Flush pending update entries
        for entry in ctx.pending:
            from apps.core.history import record_history
            record_history(
                object_type=entry['object_type'],
                entry_type=entry['entry_type'],
                object_id=entry['_instance'].pk,
                changes=entry['changes'],
                user=self.user,
            )
        ctx.pending.clear()

        after_count = ExpensesHistory.objects.filter(
            object_type='expense', object_id=expense.pk,
        ).count()
        self.assertGreater(after_count, before_count)

        latest = ExpensesHistory.objects.filter(
            object_type='expense', object_id=expense.pk,
        ).order_by('-timestamp').first()
        self.assertIsNotNone(latest)
        self.assertIn('status', latest.changes)
        self.assertEqual(latest.changes['status']['new'], Expense.STATUS_REIMBURSED)


class ExpenseQBOSeamTest(TestCase):
    """qbo_* saves must NOT write any ExpensesHistory rows (seam test)."""

    def setUp(self):
        _seed_config()
        self.user = User.objects.create_user(username='seam_tester', password='pass')
        self.cat = AccountingCategory.objects.create(
            code='SMP', name='Sample', qbo_expense_account_id='501',
        )
        set_history_context(None)

    def tearDown(self):
        set_history_context(None)

    def test_mark_failed_writes_no_history_row(self):
        from apps.core.models import ExpensesHistory
        # Create expense outside context so we start clean
        expense = _make_expense(self.user, self.cat)

        before = ExpensesHistory.objects.filter(
            object_type='expense', object_id=expense.pk,
        ).count()

        # mark_failed only touches qbo_* fields — all excluded
        expense.mark_failed('boom', Expense.OP_DELETE)

        after = ExpensesHistory.objects.filter(
            object_type='expense', object_id=expense.pk,
        ).count()
        self.assertEqual(before, after, (
            'mark_failed (qbo-only save) must not write an ExpensesHistory row'
        ))

    def test_mark_synced_writes_no_history_row(self):
        from apps.core.models import ExpensesHistory
        expense = _make_expense(self.user, self.cat)

        before = ExpensesHistory.objects.filter(
            object_type='expense', object_id=expense.pk,
        ).count()

        # mark_synced only touches qbo_* fields — all excluded
        expense.mark_synced('qbo-id-123')

        after = ExpensesHistory.objects.filter(
            object_type='expense', object_id=expense.pk,
        ).count()
        self.assertEqual(before, after, (
            'mark_synced (qbo-only save) must not write an ExpensesHistory row'
        ))

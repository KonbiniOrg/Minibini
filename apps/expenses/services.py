from django.db import transaction
from django.core.exceptions import ValidationError

from apps.expenses.models import Expense
from apps.jobs.models import Task


class ExpenseService:
    """Business-logic façade for the Expense model."""

    @staticmethod
    def submit(*, entered_by, payment_method, amount, purchased_on, accounting_category,
               description='', payment_account_id='', reference_number='',
               purchased_by=None, material=None):
        with transaction.atomic():
            expense = Expense(
                entered_by=entered_by,
                purchased_by=purchased_by,
                amount=amount,
                purchased_on=purchased_on,
                accounting_category=accounting_category,
                description=description,
                payment_method=payment_method,
                payment_account_id=payment_account_id,
                reference_number=reference_number,
                material=material,
            )
            expense.full_clean()
            expense.save()

        if payment_method == Expense.PAYMENT_METHOD_COMPANY:
            ExpenseService._push_and_set_status(expense)

        return expense

    @staticmethod
    def _push_and_set_status(expense):
        from apps.qbo.services import QBOExpenseSyncService
        try:
            QBOExpenseSyncService.push_expense(expense)
            expense.status = Expense.STATUS_SYNCED
            expense.qbo_sync_error = ''
            expense.save(update_fields=['status', 'qbo_sync_error'])
        except Exception as e:
            expense.status = Expense.STATUS_SYNC_FAILED
            expense.qbo_sync_error = str(e)
            expense.save(update_fields=['status', 'qbo_sync_error'])

    @staticmethod
    def update(*, expense, actor, **fields):
        allowed = {
            'amount', 'purchased_on', 'description', 'accounting_category',
            'payment_method', 'payment_account_id', 'reference_number',
            'purchased_by', 'material',
        }
        with transaction.atomic():
            for key, value in fields.items():
                if key in allowed:
                    setattr(expense, key, value)
            expense.full_clean()
            expense.save()

        if expense.qbo_id:
            ExpenseService._resync(expense)
        return expense

    @staticmethod
    def _resync(expense):
        from apps.qbo.services import QBOExpenseSyncService
        try:
            if expense.reimbursement_id:
                QBOExpenseSyncService.update_reimbursement(expense.reimbursement)
            else:
                QBOExpenseSyncService.update_expense(expense)
            if expense.status == Expense.STATUS_SYNC_FAILED:
                expense.status = Expense.STATUS_SYNCED
                expense.qbo_sync_error = ''
                expense.save(update_fields=['status', 'qbo_sync_error'])
        except Exception as e:
            if expense.reimbursement_id:
                batch = expense.reimbursement
                from apps.expenses.models import Reimbursement
                batch.status = Reimbursement.STATUS_SYNC_FAILED
                batch.qbo_sync_error = str(e)
                batch.save(update_fields=['status', 'qbo_sync_error'])
            else:
                expense.status = Expense.STATUS_SYNC_FAILED
                expense.qbo_sync_error = str(e)
                expense.save(update_fields=['status', 'qbo_sync_error'])

    @staticmethod
    def delete(*, expense, actor):
        from apps.qbo.services import QBOExpenseSyncService
        if expense.qbo_id and not expense.reimbursement_id:
            QBOExpenseSyncService.void_expense(expense)
        expense.delete()

    @staticmethod
    def reject(*, expense, actor):
        if expense.payment_method != Expense.PAYMENT_METHOD_PERSONAL:
            raise ValidationError('Only personal expenses can be rejected.')
        if expense.status not in (Expense.STATUS_SUBMITTED,):
            raise ValidationError(
                f'Cannot reject an expense in status {expense.status!r}.'
            )
        expense.status = Expense.STATUS_REJECTED
        expense.save(update_fields=['status'])
        return expense

    @staticmethod
    def retry_sync(*, expense, actor):
        if expense.status != Expense.STATUS_SYNC_FAILED:
            raise ValidationError(
                'Can only retry sync on expenses in sync_failed status.'
            )
        ExpenseService._push_and_set_status(expense)
        expense.refresh_from_db()
        return expense

    @staticmethod
    def find_or_create_materials_task(*, work_order):
        existing = Task.objects.filter(
            work_order=work_order, name='Materials',
        ).first()
        if existing:
            return existing
        return Task.objects.create(
            work_order=work_order,
            name='Materials',
            status=Task.STATUS_COMPLETE,
        )

import logging

from django.db import transaction
from django.core.exceptions import ValidationError

from apps.expenses.models import Expense
from apps.jobs.models import Task

logger = logging.getLogger(__name__)


class ExpenseService:
    """Business-logic façade for the Expense model."""

    @staticmethod
    def submit(*, entered_by, payment_method, amount, purchased_on, accounting_category,
               description='', payment_account_id='', reference_number='',
               purchased_by=None, material=None, new_material=None):
        with transaction.atomic():
            # If new_material info is provided, create the material atomically
            if new_material and not material:
                from apps.jobs.models import Job
                from apps.inventory.models import Material
                # Accept either 'job_id' (new) or 'work_order_id' (legacy key
                # from callers that haven't been updated yet — e.g., the
                # frontend expense form). Post-WorkOrder-removal, both point
                # at the Job.
                job_id = new_material.get('job_id') or new_material.get('work_order_id')
                job = Job.objects.get(pk=job_id)
                task = ExpenseService.find_or_create_materials_task(job=job)
                qty = new_material.get('quantity') or 1
                price = new_material.get('price')
                if price is None:
                    price = amount
                material = Material.objects.create(
                    task=task,
                    description=new_material.get('description', description),
                    quantity=qty,
                    unit_cost=price,
                )

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
            logger.exception('QBO expense push failed for expense %s', expense.pk)
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
            logger.exception('QBO resync failed for expense %s', expense.pk)
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
    def find_or_create_materials_task(*, job):
        existing = Task.objects.filter(
            job=job, name='Materials',
        ).first()
        if existing:
            return existing
        return Task.objects.create(
            job=job,
            name='Materials',
            status=Task.STATUS_COMPLETE,
        )


class ReimbursementService:
    """Business logic for creating, retrying, and unwinding reimbursement batches."""

    @staticmethod
    def create_batch(*, purchased_by, expense_ids, paid_on, payment_account_id,
                      reference_number, notes, created_by):
        """Validate + create the batch + flip expenses (one transaction), then push
        to QBO. Batch is left in sync_failed if QBO push fails; the DB commit stands."""
        from apps.expenses.models import Reimbursement

        if not expense_ids:
            raise ValidationError({'expense_ids': 'At least one expense is required.'})

        with transaction.atomic():
            expenses = list(
                Expense.objects.select_for_update().filter(pk__in=expense_ids)
            )
            if len(expenses) != len(set(expense_ids)):
                raise ValidationError({'expense_ids': 'One or more expenses not found.'})

            for e in expenses:
                if e.purchased_by_id != purchased_by.pk:
                    raise ValidationError({
                        'expense_ids':
                        f'Expense #{e.pk} belongs to a different user.',
                    })
                if e.payment_method != Expense.PAYMENT_METHOD_PERSONAL:
                    raise ValidationError({
                        'expense_ids':
                        f'Expense #{e.pk} is not a personal expense.',
                    })
                if e.status != Expense.STATUS_SUBMITTED:
                    raise ValidationError({
                        'expense_ids':
                        f'Expense #{e.pk} is not in submitted status.',
                    })

            batch = Reimbursement.objects.create(
                purchased_by=purchased_by,
                paid_on=paid_on,
                payment_account_id=payment_account_id,
                reference_number=reference_number,
                notes=notes,
                created_by=created_by,
                status=Reimbursement.STATUS_PENDING,
            )
            for e in expenses:
                e.reimbursement = batch
                e.status = Expense.STATUS_REIMBURSED
                e.save(update_fields=['reimbursement', 'status'])

        # After commit: attempt QBO push.
        from apps.qbo.services import QBOExpenseSyncService
        try:
            QBOExpenseSyncService.push_reimbursement(batch)
            batch.status = Reimbursement.STATUS_SYNCED
            batch.qbo_sync_error = ''
            batch.save(update_fields=['status', 'qbo_sync_error'])
        except Exception as e:
            logger.exception('QBO reimbursement push failed for batch %s', batch.pk)
            batch.status = Reimbursement.STATUS_SYNC_FAILED
            batch.qbo_sync_error = str(e)
            batch.save(update_fields=['status', 'qbo_sync_error'])

        return batch

    @staticmethod
    def retry_sync(*, batch, actor):
        from apps.expenses.models import Reimbursement
        if batch.status != Reimbursement.STATUS_SYNC_FAILED:
            raise ValidationError(
                'Can only retry sync on batches in sync_failed status.'
            )
        from apps.qbo.services import QBOExpenseSyncService
        try:
            QBOExpenseSyncService.push_reimbursement(batch)
            batch.status = Reimbursement.STATUS_SYNCED
            batch.qbo_sync_error = ''
            batch.save(update_fields=['status', 'qbo_sync_error'])
        except Exception as e:
            logger.exception('QBO reimbursement retry failed for batch %s', batch.pk)
            batch.qbo_sync_error = str(e)
            batch.save(update_fields=['qbo_sync_error'])
        return batch

    @staticmethod
    def delete(*, batch, actor):
        """Unwind: void QBO, flip expenses back to submitted, delete the batch row."""
        from apps.qbo.services import QBOExpenseSyncService
        if batch.qbo_id:
            QBOExpenseSyncService.void_reimbursement(batch)

        with transaction.atomic():
            for e in batch.expenses.all():
                e.reimbursement = None
                e.status = Expense.STATUS_SUBMITTED
                e.save(update_fields=['reimbursement', 'status'])
            batch.delete()

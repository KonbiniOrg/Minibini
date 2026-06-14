import logging
from decimal import Decimal

from django.db import transaction
from django.core.exceptions import ValidationError

from apps.expenses.models import Expense

logger = logging.getLogger(__name__)


class ExpenseService:
    """Business-logic façade for the Expense model."""

    @staticmethod
    def submit(*, entered_by, payment_method, amount, purchased_on, accounting_category,
               description='', payment_account_id='', reference_number='',
               purchased_by=None, material=None, new_material=None, job=None):
        created_new_material = False
        with transaction.atomic():
            # If new_material info is provided, create the material atomically
            if new_material and not material:
                created_new_material = True
                from apps.jobs.models import Job
                from apps.inventory.models import PriceListItem
                from apps.inventory.services import InventoryService, MaterialService
                job = Job.objects.get(pk=new_material['job_id'])
                pli = None
                if new_material.get('price_list_item_id'):
                    pli = PriceListItem.objects.get(pk=new_material['price_list_item_id'])
                qty = new_material.get('quantity') or Decimal('1')
                price = new_material.get('price')
                if price is None:
                    price = amount
                # For PLI-linked materials, _populate_from_pli fills the category.
                # For freeform (no PLI), inherit the expense's accounting_category.
                mat_category = None if pli else accounting_category
                material = MaterialService.create_on_job(
                    job=job, task=None,
                    description=new_material.get('description', description),
                    quantity=qty,
                    unit_cost=price,
                    price_list_item=pli,
                    accounting_category=mat_category,
                )
                if pli and pli.is_inventoried:
                    InventoryService.receive_ad_hoc_purchase(material)

            # A linked material implies the job (cost anchor). Derive it when the
            # caller didn't pass one explicitly.
            if material and job is None:
                job = material.job

            # Linking an EXISTING material at submit must not silently clobber a
            # cost that came from another source (PLI/PO/another expense).
            if material and not created_new_material:
                ExpenseService._assert_no_cost_clobber(material)

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
                job=job,
                material=material,
            )
            expense.full_clean()
            expense.save()

            # Cost lives on the material: actualize it from the linked expense(s).
            # (A freshly created new_material already carries its intended cost.)
            if material and not created_new_material:
                ExpenseService._recost_material_from_expenses(material)

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
            'purchased_by', 'material', 'job',
        }
        # Frozen while it (or its material) is on an invoice.
        ExpenseService._assert_not_invoiced(expense)
        # Once reimbursed, the money fields are settled (the person was paid).
        ExpenseService._assert_reimbursed_money_unchanged(expense, fields)
        old_material_id = expense.material_id
        with transaction.atomic():
            for key, value in fields.items():
                if key in allowed:
                    setattr(expense, key, value)

            new_material = expense.material
            # A linked material implies the job; derive it if the expense has none.
            if new_material and not expense.job_id:
                expense.job = new_material.job
            # Moving the expense to another job moves its linked material too, so
            # the material.job == expense.job consistency rule holds.
            if new_material and expense.job_id and new_material.job_id != expense.job_id:
                ExpenseService._move_material_to_job(new_material, expense.job)

            is_new_link = new_material and new_material.pk != old_material_id
            if is_new_link:
                ExpenseService._assert_no_cost_clobber(new_material)

            expense.full_clean()
            expense.save()

            # Recost: actualize the (now-)linked material's cost; clear/recompute
            # the material we just unlinked from.
            if old_material_id and old_material_id != expense.material_id:
                from apps.inventory.models import Material
                try:
                    ExpenseService._recost_after_unlink(
                        Material.objects.get(pk=old_material_id)
                    )
                except Material.DoesNotExist:
                    pass
            if expense.material_id:
                ExpenseService._recost_material_from_expenses(expense.material)

        if expense.qbo_id:
            ExpenseService._resync(expense)
        return expense

    # ----- job/material cost & freeze helpers -------------------------------

    @staticmethod
    def _assert_not_invoiced(expense):
        """Raise if the expense — or its linked material — is on a non-cancelled
        invoice. An expense is immutable while billed (remove it from the invoice
        first)."""
        from django.db.models import Q
        from apps.invoicing.models import InvoiceLineItemSource, Invoice
        live = InvoiceLineItemSource.objects.exclude(
            invoice_line_item__invoice__status=Invoice.STATUS_CANCELLED
        )
        cond = Q(
            source_type=InvoiceLineItemSource.SOURCE_EXPENSE, source_pk=expense.pk,
        )
        if expense.material_id:
            cond |= Q(
                source_type=InvoiceLineItemSource.SOURCE_MATERIAL,
                source_pk=expense.material_id,
            )
        if live.filter(cond).exists():
            raise ValidationError(
                'Cannot edit an expense that is on an invoice; '
                'remove it from the invoice first.'
            )

    @staticmethod
    def _assert_reimbursed_money_unchanged(expense, fields):
        """Once an expense is reimbursed (the person has been paid), its money
        fields are settled. Block changes to amount / payment_method /
        payment_account_id / purchased_by. Cost-attribution (job, material) and
        clerical fields (description, reference) stay editable. Unwind the
        reimbursement batch first to change a paid amount."""
        if not (expense.reimbursement_id
                or expense.status == Expense.STATUS_REIMBURSED):
            return
        for f in ('amount', 'payment_method', 'payment_account_id'):
            if f in fields and fields[f] != getattr(expense, f):
                raise ValidationError(
                    'Cannot change the money fields of a reimbursed expense; '
                    'unwind the reimbursement first.'
                )
        if 'purchased_by' in fields:
            new_pb = fields['purchased_by']
            new_pb_id = getattr(new_pb, 'pk', new_pb)
            if new_pb_id != expense.purchased_by_id:
                raise ValidationError(
                    'Cannot change who is reimbursed on a reimbursed expense; '
                    'unwind the reimbursement first.'
                )

    @staticmethod
    def _assert_no_cost_clobber(material):
        """Linking an expense actualizes the material's cost from what was actually
        paid. A PLI catalog price is only an *estimate*, so it's fine to overwrite.
        The one cost we must not silently clobber is a **PO-received** one — the
        purchase order is the authoritative cost source there."""
        if material.po_line_item_id and not material.expenses.exists():
            raise ValidationError({
                'material': 'This material’s cost comes from a purchase order; '
                            'link the expense to a different material or leave it '
                            'job-only.'
            })

    @staticmethod
    def _recost_material_from_expenses(material):
        """Set the material's unit_cost to (sum of linked expense amounts) / qty.
        Cost lives on the material; this is the document-sourced cost path."""
        from apps.inventory.services import MaterialService
        if not material.quantity or material.quantity == Decimal('0.00'):
            return
        total = sum((e.amount for e in material.expenses.all()), Decimal('0.00'))
        new_cost = (total / material.quantity).quantize(Decimal('0.01'))
        MaterialService.update_pricing(
            material, unit_cost=new_cost, cost_source='document',
        )

    @staticmethod
    def _recost_after_unlink(material):
        """After an expense detaches: recompute from remaining expenses; if none
        remain and nothing else backs the cost (no PO line), reset to 0."""
        from apps.inventory.services import MaterialService
        if material.expenses.exists():
            ExpenseService._recost_material_from_expenses(material)
        elif not material.po_line_item_id:
            MaterialService.update_pricing(
                material, unit_cost=Decimal('0.00'), cost_source='document',
            )
        # else: PO-backed — leave the cost as-is.

    @staticmethod
    def _move_material_to_job(material, new_job):
        """Move a linked material to a new job. A pending, inventoried material's
        earmark follows it; a consumed material's inventory is already settled
        (QOH/qty_sold are global), so only its job changes."""
        from apps.inventory.models import Material
        from apps.inventory.services import InventoryService
        if material.job_id == new_job.pk:
            return
        pli = material.price_list_item
        move_earmark = (
            material.consumption_state == Material.CONSUMPTION_STATE_PENDING
            and pli and pli.is_inventoried
            and material.quantity > Decimal('0.00')
        )
        old_job = material.job
        if move_earmark:
            InventoryService._mutate_earmark(pli, old_job, -material.quantity)
        material.job = new_job
        material.save()
        if move_earmark:
            InventoryService._mutate_earmark(pli, new_job, material.quantity)

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
        ExpenseService._assert_not_invoiced(expense)
        if expense.reimbursement_id:
            raise ValidationError(
                'Cannot delete a reimbursed expense; unwind the reimbursement first.'
            )
        from apps.qbo.services import QBOExpenseSyncService
        if expense.qbo_id and not expense.reimbursement_id:
            QBOExpenseSyncService.void_expense(expense)
        expense.delete()

    @staticmethod
    def reject(*, expense, actor):
        from apps.inventory.models import Material
        from apps.inventory.services import InventoryService
        if expense.payment_method != Expense.PAYMENT_METHOD_PERSONAL:
            raise ValidationError('Only personal expenses can be rejected.')
        if expense.status not in (Expense.STATUS_SUBMITTED,):
            raise ValidationError(
                f'Cannot reject an expense in status {expense.status!r}.'
            )
        materials = list(Material.objects.filter(expenses=expense))
        for m in materials:
            if m.consumption_state == Material.CONSUMPTION_STATE_CONSUMED:
                raise ValidationError(
                    'Cannot reject expense with consumed materials; adjust inventory manually.'
                )
        with transaction.atomic():
            for m in materials:
                InventoryService._mutate_earmark(
                    m.price_list_item, m.job, -m.quantity,
                )
                InventoryService.reverse_ad_hoc_purchase(m)
                m.delete()
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

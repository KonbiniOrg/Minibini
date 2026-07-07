from decimal import Decimal

from django.db import transaction
from django.core.exceptions import ValidationError

from apps.core.history import record_action
from apps.expenses.models import Expense


class ExpenseService:
    """Business-logic façade for the Expense model."""

    @staticmethod
    def submit(*, entered_by, payment_method, amount, purchased_on, accounting_category,
               description='', payment_account_id='', reference_number='',
               purchased_by=None, new_material=None, job=None,
               stock_pli=None, stock_qty=None, material_id=None, attach_qty=None):
        """Create an expense in one of three modes:
        - **cost**: optionally creates ONE consumable material from `new_material`
          (freeform or non-inventoried PLI); `amount` is the job cost.
        - **stock receipt**: an inventoried PLI (passed directly as
          `stock_pli`/`stock_qty`, or detected from an inventoried `new_material`)
          bumps QOH; `amount` is NOT job-costed (cost flows at consumption).
        - **attach** (`material_id`): attach to a PENDING, non-customer material —
          the cost AND the stock. Prices the target (establishing a provisional
          one), stamps EXPENSE provenance, and receives `attach_qty` (default: the
          material's quantity) into its lot. attach == receipt. Mutually exclusive
          with `new_material`; `amount` flows through the material (as in the
          new_material cost mode), not double-counted as job cost."""
        from apps.inventory.services import InventoryService
        material = None
        if material_id and new_material:
            raise ValidationError(
                'Attach to an existing material or create a new one, not both.')
        with transaction.atomic():
            if material_id:
                from apps.inventory.models import Material
                from apps.inventory.services import MaterialService
                material = Material.objects.get(pk=material_id)
                if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
                    raise ValidationError('Can only attach to a pending material.')
                if material.is_customer_supplied:
                    raise ValidationError(
                        'A customer-supplied material has no purchase to attach.')
                if job is None:
                    job = material.job
                qty = attach_qty if attach_qty is not None else material.quantity
                if qty <= Decimal('0.00'):
                    raise ValidationError({'attach_qty': ['Quantity must be positive.']})
                unit_cost = (amount / qty).quantize(Decimal('0.01'))
                if material.inventory_item_id is None:
                    # Provisional target: one move prices AND backs it.
                    MaterialService.establish(
                        material, unit_cost=unit_cost,
                        cost_source=Material.COST_SOURCE_EXPENSE)
                else:
                    MaterialService.update_pricing(material, unit_cost=unit_cost)
                    material.cost_source = Material.COST_SOURCE_EXPENSE
                    material.save(update_fields=['cost_source'])
                material.refresh_from_db()
                # attach == receipt: bump the lot QOH (even atop a partial PO
                # receipt — don't block). `stock_qty` records the received qty so
                # reject can back it off (stock bookkeeping, no new field).
                InventoryService.receive_ad_hoc_purchase(material, qty=qty)
                stock_qty = qty

            if new_material:
                from apps.jobs.models import Job
                from apps.inventory.models import InventoryItem, Material
                from apps.inventory.services import MaterialService
                nm_job = Job.objects.get(pk=new_material['job_id'])
                if job is None:
                    job = nm_job
                pli = None
                if new_material.get('inventory_item_id'):
                    pli = InventoryItem.objects.get(pk=new_material['inventory_item_id'])
                qty = new_material.get('quantity') or Decimal('1')
                if pli:
                    # Inventoried → stock receipt (no consumable material).
                    stock_pli, stock_qty = pli, qty
                else:
                    price = new_material.get('price')
                    if price is None:
                        price = amount
                    material = MaterialService.create_on_job(
                        job=nm_job, task=None,
                        description=new_material.get('description', description),
                        quantity=qty, unit_cost=price,
                        inventory_item=pli,
                        accounting_category=(None if pli else accounting_category),
                        cost_source=Material.COST_SOURCE_EXPENSE,
                    )

            if material and job is None:
                job = material.job

            expense = Expense(
                entered_by=entered_by, purchased_by=purchased_by, amount=amount,
                purchased_on=purchased_on, accounting_category=accounting_category,
                description=description, payment_method=payment_method,
                payment_account_id=payment_account_id, reference_number=reference_number,
                job=job, material=material, stock_pli=stock_pli, stock_qty=stock_qty,
            )
            expense.full_clean()
            expense.save()

            if stock_pli is not None:
                InventoryService.receive_stock(
                    stock_pli, stock_qty,
                    reason=f'Stock receipt (expense {expense.pk})')

        if payment_method == Expense.PAYMENT_METHOD_COMPANY:
            ExpenseService._push_create(expense)

        return expense

    @staticmethod
    def _push_create(expense):
        from apps.qbo.services import QBOExpenseSyncService, QBOSyncService
        QBOSyncService.run_create(
            expense, lambda: QBOExpenseSyncService.push_expense(expense))

    @staticmethod
    def update(*, expense, actor, **fields):
        # `material` is not editable post-create (expenses never link/relink an
        # existing material). `stock_qty` adjusts the receipt's QOH by the delta.
        allowed = {
            'amount', 'purchased_on', 'description', 'accounting_category',
            'payment_method', 'payment_account_id', 'reference_number',
            'purchased_by', 'job', 'stock_qty',
        }
        # Frozen while it (or its material) is on an invoice.
        ExpenseService._assert_not_invoiced(expense)
        # Once reimbursed, the money fields are settled (the person was paid).
        ExpenseService._assert_reimbursed_money_unchanged(expense, fields)
        old_stock_qty = expense.stock_qty
        with transaction.atomic():
            for key, value in fields.items():
                if key in allowed:
                    setattr(expense, key, value)

            # A linked consumable material follows a job change so the
            # material.job == expense.job consistency rule holds (no cost effect).
            if (expense.material_id and expense.job_id
                    and expense.material.job_id != expense.job_id):
                ExpenseService._move_material_to_job(expense.material, expense.job)

            expense.full_clean()
            expense.save()

            # Stock-receipt qty change → adjust QOH by the delta.
            if expense.stock_pli_id and 'stock_qty' in fields:
                from apps.inventory.services import InventoryService
                delta = (expense.stock_qty or Decimal('0.00')) - (old_stock_qty or Decimal('0.00'))
                if delta != Decimal('0.00'):
                    InventoryService.receive_stock(
                        expense.stock_pli, delta,
                        reason=f'Stock receipt adj (expense {expense.pk})')

        if expense.qbo_id:
            ExpenseService._push_update(expense)
        return expense

    # ----- job/material cost & freeze helpers -------------------------------

    @staticmethod
    def _assert_not_invoiced(expense):
        """Raise if the expense — or its linked material — is on a non-cancelled
        invoice. An expense is immutable while billed (remove it from the invoice
        first)."""
        from apps.invoicing.claims import InvoiceClaimService
        from apps.invoicing.models import InvoiceLineItemSource
        if InvoiceClaimService.is_invoiced(
            InvoiceLineItemSource.SOURCE_EXPENSE, expense.pk,
        ) or (
            expense.material_id and InvoiceClaimService.is_invoiced(
                InvoiceLineItemSource.SOURCE_MATERIAL, expense.material_id,
            )
        ):
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
    def _move_material_to_job(material, new_job):
        """Move a linked material to a new job. A pending, inventoried material's
        earmark follows it; a consumed material's inventory is already settled
        (QOH/qty_sold are global), so only its job changes."""
        from apps.inventory.models import Material
        from apps.inventory.services import InventoryService
        if material.job_id == new_job.pk:
            return
        pli = material.inventory_item
        move_earmark = (
            material.consumption_state == Material.CONSUMPTION_STATE_PENDING
            and pli is not None
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
    def _push_update(expense):
        from apps.qbo.services import QBOExpenseSyncService, QBOSyncService
        if expense.reimbursement_id:
            QBOSyncService.run_update(expense.reimbursement, lambda: QBOExpenseSyncService.update_reimbursement(expense.reimbursement))
        else:
            QBOSyncService.run_update(expense, lambda: QBOExpenseSyncService.update_expense(expense))

    @staticmethod
    def _is_attach(expense):
        """Attach mode's discriminator: material set + stock_qty recorded, no
        stock_pli (stock-receipt mode). new_material consumables have no
        stock_qty; stock receipts have no material."""
        return bool(expense.material_id and expense.stock_qty
                    and not expense.stock_pli_id)

    @staticmethod
    def _unwind_attach(expense, *, reason):
        """Faithful inverse of an attach receipt — shared by reject and delete.

        1. Reverse the receipt: back stock_qty off the material's lot (with an
           inventory-history entry).
        2. Restore invariant-consistent state — never leave a lot-backed
           material with NULL cost_source, never let the QOH bump outlive its
           expense:
           - If the attach minted the lot (code LOT-{material_pk}) and, after
             the reversal, it is empty and referenced by nothing but this
             material (no document line items, no other materials, no foreign
             earmarks, no expense stock links — adapted from
             InventoryService.assert_item_deletable), the whole establishment
             was this expense's doing: demote the material back to provisional
             (inventory_item None, unit_cost 0, cost_source None, earmark
             backed out) and hard-delete the lot. This is mistake-correction
             deletion of a never-really-referenced row — the deletion doctrine
             bans auto-deleting rows with history, not unwinding a mistake.
           - Otherwise (shared/catalog lot, residual stock, or outside
             references) the material stays established and provenance falls
             back to ENTERED: the pre-attach source isn't stored, and ENTERED
             ("a human vouched for this cost") is the honest approximation.
             Limitation: unit_cost keeps the expense-derived value — the
             pre-attach cost is likewise unrecoverable.
        """
        from apps.inventory.models import Earmark, Material
        from apps.inventory.services import InventoryService
        material = expense.material
        lot = material.inventory_item
        if lot is None:
            return  # nothing received (defensive; attach always leaves a lot)
        InventoryService.receive_stock(lot, -expense.stock_qty, reason=reason)
        lot.refresh_from_db()
        minted_and_unreferenced = (
            lot.code == f'LOT-{material.pk}'
            and lot.qty_on_hand == Decimal('0.00')
            and not lot.has_document_line_refs
            and not Material.objects.filter(inventory_item=lot)
                                    .exclude(pk=material.pk).exists()
            and not Earmark.objects.filter(inventory_item=lot)
                                   .exclude(job=material.job).exists()
            and not Expense.objects.filter(stock_pli=lot).exists()
        )
        if minted_and_unreferenced:
            InventoryService._mutate_earmark(lot, material.job, -material.quantity)
            material.inventory_item = None
            material.unit_cost = Decimal('0.00')
            material.cost_source = None
            material.save(update_fields=['inventory_item', 'unit_cost', 'cost_source'])
            lot.delete()
        else:
            material.cost_source = Material.COST_SOURCE_ENTERED
            material.save(update_fields=['cost_source'])

    @staticmethod
    def delete(*, expense, actor):
        from apps.inventory.models import Material
        ExpenseService._assert_not_invoiced(expense)
        if expense.reimbursement_id:
            raise ValidationError(
                'Cannot delete a reimbursed expense; unwind the reimbursement first.'
            )
        # A rejected attach expense was already unwound at reject — deleting the
        # row must not reverse the receipt a second time.
        unwind_attach = (ExpenseService._is_attach(expense)
                         and expense.status != Expense.STATUS_REJECTED)
        if unwind_attach:
            expense.material.refresh_from_db()  # guard on current state, not a cache
            if (expense.material.consumption_state
                    == Material.CONSUMPTION_STATE_CONSUMED):
                raise ValidationError(
                    'Cannot delete this expense: its attached material has been '
                    'consumed — the received stock was already drawn down. '
                    'Adjust inventory manually.'
                )
        # QBO void runs OUTSIDE the transaction so that on failure mark_failed→expense.save()
        # commits (row retained as sync_failed) while the stock reversal + delete are never reached.
        if expense.qbo_id:
            from apps.qbo.services import QBOExpenseSyncService, QBOSyncService
            try:
                QBOSyncService.run_delete(expense, lambda: QBOExpenseSyncService.void_expense(expense))
            except Exception:
                raise ValidationError(
                    'Could not delete this expense — its QuickBooks sync failed, so the expense '
                    'was kept (marked sync-failed). Retry once QuickBooks is reachable.'
                )
        with transaction.atomic():
            if expense.stock_pli_id and expense.stock_qty:
                from apps.inventory.services import InventoryService
                InventoryService.receive_stock(
                    expense.stock_pli, -expense.stock_qty,
                    reason=f'Stock receipt void (expense {expense.pk})')
            if unwind_attach:
                ExpenseService._unwind_attach(
                    expense,
                    reason=f'Attach receipt void (expense {expense.pk})')
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
        mat = expense.material
        if mat and mat.consumption_state == Material.CONSUMPTION_STATE_CONSUMED:
            raise ValidationError(
                'Cannot reject expense with consumed materials; adjust inventory manually.'
            )
        # Attach mode: the material predates the expense, so reject must NOT
        # delete it — _unwind_attach reverses the receipt and restores an
        # invariant-consistent material instead.
        is_attach = ExpenseService._is_attach(expense)
        # Rule 1: for a new_material expense, reject DELETES the created material,
        # so it must not be claimed by a document. Attach leaves the material in
        # place, so a claim there is no obstacle — only guard the delete path.
        if mat and not is_attach:
            from apps.estimates.claims import atom_is_claimed
            if atom_is_claimed('material', mat.pk):
                raise ValidationError(
                    'Cannot reject: this expense’s material backs an estimate or '
                    'change-order line. Remove the line first.'
                )
        with transaction.atomic():
            if is_attach:
                ExpenseService._unwind_attach(
                    expense,
                    reason=f'Attach receipt void on reject (expense {expense.pk})')
            elif mat:
                # Release the earmark and delete the material. The cost-material
                # path earmarks but never bumps QOH (it's a job cost, not a stock
                # receipt), so there is no ad-hoc receipt to reverse here — stock
                # receipts are handled separately below.
                InventoryService._mutate_earmark(
                    mat.inventory_item, mat.job, -mat.quantity,
                )
                mat.delete()
                expense.material = None  # drop the now-deleted FK before save
            # Reverse a stock-receipt's QOH bump.
            if expense.stock_pli_id and expense.stock_qty:
                InventoryService.receive_stock(
                    expense.stock_pli, -expense.stock_qty,
                    reason=f'Stock receipt void on reject (expense {expense.pk})')
            expense.status = Expense.STATUS_REJECTED
            expense.save(update_fields=['status'])
        return expense

    @staticmethod
    def retry(*, expense, actor):
        if expense.qbo_sync_status != Expense.SYNC_FAILED:
            raise ValidationError('Can only retry a sync that failed.')
        op = expense.qbo_pending_op
        if op == Expense.OP_DELETE:
            ExpenseService.delete(expense=expense, actor=actor)  # re-void + remove
            return None
        if op == Expense.OP_UPDATE:
            ExpenseService._push_update(expense)
        else:  # create (or blank → treat as create)
            ExpenseService._push_create(expense)
        expense.refresh_from_db()
        return expense

    @staticmethod
    def retry_sync(*, expense, actor):
        return ExpenseService.retry(expense=expense, actor=actor)


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
            )
            for e in expenses:
                e.reimbursement = batch
                e.status = Expense.STATUS_REIMBURSED
                e.save(update_fields=['reimbursement', 'status'])
                record_action(
                    object_type='expense',
                    object_id=e.pk,
                    action=f'Reimbursed in batch #{batch.pk} (paid to {purchased_by.username})',
                )

        # After commit: attempt QBO push.
        ReimbursementService._push_create(batch)

        return batch

    @staticmethod
    def _push_create(batch):
        from apps.qbo.services import QBOExpenseSyncService, QBOSyncService
        QBOSyncService.run_create(batch, lambda: QBOExpenseSyncService.push_reimbursement(batch))

    @staticmethod
    def _push_update(batch):
        from apps.qbo.services import QBOExpenseSyncService, QBOSyncService
        QBOSyncService.run_update(batch, lambda: QBOExpenseSyncService.update_reimbursement(batch))

    @staticmethod
    def retry(*, batch, actor):
        from apps.expenses.models import Reimbursement
        if batch.qbo_sync_status != Reimbursement.SYNC_FAILED:
            raise ValidationError('Can only retry a sync that failed.')
        op = batch.qbo_pending_op
        if op == Reimbursement.OP_DELETE:
            ReimbursementService.delete(batch=batch, actor=actor)
            return None
        if op == Reimbursement.OP_UPDATE:
            ReimbursementService._push_update(batch)
        else:  # create (or blank → treat as create)
            ReimbursementService._push_create(batch)
        batch.refresh_from_db()
        return batch

    @staticmethod
    def retry_sync(*, batch, actor):
        return ReimbursementService.retry(batch=batch, actor=actor)

    @staticmethod
    def delete(*, batch, actor):
        """Unwind: void QBO, flip expenses back to submitted, delete the batch row."""
        from apps.qbo.services import QBOExpenseSyncService, QBOSyncService
        if batch.qbo_id:
            try:
                QBOSyncService.run_delete(batch, lambda: QBOExpenseSyncService.void_reimbursement(batch))
            except Exception:
                raise ValidationError(
                    'Could not delete this reimbursement — its QuickBooks sync failed, so the batch '
                    'was kept (marked sync-failed). Retry once QuickBooks is reachable.'
                )

        with transaction.atomic():
            batch_pk = batch.pk
            for e in batch.expenses.all():
                e.reimbursement = None
                e.status = Expense.STATUS_SUBMITTED
                e.save(update_fields=['reimbursement', 'status'])
                record_action(
                    object_type='expense',
                    object_id=e.pk,
                    action=f'Reimbursement unwound (batch #{batch_pk})',
                )
            batch.delete()

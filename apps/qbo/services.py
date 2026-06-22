import datetime
import logging
from apps.core.history import record_history
import json
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.core.models import Configuration
from apps.qbo.models import QBOConnection, QBOSyncLog

logger = logging.getLogger(__name__)


class QBOService:
    """
    Thin wrapper around python-quickbooks API calls.
    This class is the mock boundary — tests mock methods on this class
    rather than mocking python-quickbooks internals.
    """

    @staticmethod
    def get_active_connection():
        """Return the active QBO connection, or None."""
        return QBOConnection.objects.filter(is_active=True).first()

    @staticmethod
    def get_client():
        """
        Build and return an authenticated QuickBooks client.
        Refreshes the access token if expired.
        Returns None if no active connection.
        """
        conn = QBOService.get_active_connection()
        if not conn:
            return None

        from quickbooks import QuickBooks
        from intuitlib.client import AuthClient

        auth_client = AuthClient(
            client_id=settings.QBO_CLIENT_ID,
            client_secret=settings.QBO_CLIENT_SECRET,
            redirect_uri=settings.QBO_REDIRECT_URI,
            environment=settings.QBO_ENVIRONMENT,
            access_token=conn.access_token,
            refresh_token=conn.refresh_token,
        )

        if conn.is_access_token_expired:
            auth_client.refresh()
            now = timezone.now()
            conn.access_token = auth_client.access_token
            conn.refresh_token = auth_client.refresh_token
            conn.access_token_expires_at = now + datetime.timedelta(hours=1)
            conn.refresh_token_expires_at = now + datetime.timedelta(days=100)
            conn.save()

        return QuickBooks(
            auth_client=auth_client,
            refresh_token=conn.refresh_token,
            company_id=conn.realm_id,
        )

    @staticmethod
    def log_sync(entity_type, entity_id, qbo_entity_type, qbo_entity_id,
                 action, status, error_message=''):
        """Create a sync log entry."""
        return QBOSyncLog.objects.create(
            entity_type=entity_type,
            entity_id=entity_id,
            qbo_entity_type=qbo_entity_type,
            qbo_entity_id=qbo_entity_id,
            action=action,
            status=status,
            error_message=error_message,
        )

    @staticmethod
    def save_and_log(qbo_obj, client, *, entity_type, qbo_entity_type, entity_id, action='create'):
        """Save a QBO SDK object, write a QBOSyncLog row, return str(qbo_obj.Id).
        On exception: log a failed row (qbo_entity_id='') and re-raise."""
        try:
            qbo_obj.save(qb=client)
            qbo_id = str(qbo_obj.Id)
            QBOService.log_sync(entity_type=entity_type, entity_id=entity_id,
                                qbo_entity_type=qbo_entity_type, qbo_entity_id=qbo_id,
                                action=action, status='success')
            return qbo_id
        except Exception as e:
            QBOService.log_sync(entity_type=entity_type, entity_id=entity_id,
                                qbo_entity_type=qbo_entity_type, qbo_entity_id='',
                                action=action, status='failed', error_message=str(e))
            raise

    @staticmethod
    def delete_and_log(sdk_class, qbo_id, client, *, entity_type, qbo_entity_type, entity_id):
        """Fetch and delete a QBO SDK object; write a QBOSyncLog row with action='delete'.

        Idempotent: if QBO reports the object is already gone (ObjectNotFoundException /
        error_code 610), treat it as a successful delete — log success and return normally.

        On a real failure: log a failed row (qbo_entity_id='') and re-raise so the caller
        can refuse the local delete.
        """
        from quickbooks.exceptions import ObjectNotFoundException
        try:
            obj = sdk_class.get(qbo_id, qb=client)
            obj.delete(qb=client)
            QBOService.log_sync(
                entity_type=entity_type, entity_id=entity_id,
                qbo_entity_type=qbo_entity_type, qbo_entity_id=qbo_id,
                action='delete', status='success',
            )
        except ObjectNotFoundException:
            # Already gone in QBO — treat as a successful delete.
            QBOService.log_sync(
                entity_type=entity_type, entity_id=entity_id,
                qbo_entity_type=qbo_entity_type, qbo_entity_id=qbo_id,
                action='delete', status='success',
            )
        except Exception as e:
            QBOService.log_sync(
                entity_type=entity_type, entity_id=entity_id,
                qbo_entity_type=qbo_entity_type, qbo_entity_id='',
                action='delete', status='failed', error_message=str(e),
            )
            raise


class QBODisplayNameService:
    """Generates QBO-compliant DisplayNames for customer/vendor records."""

    QBO_DISPLAY_NAME_MAX = 500

    @staticmethod
    def generate_display_name(business, role):
        """
        Generate a QBO DisplayName for a Business.

        Rules:
        - First QBO record for this business uses the plain business_name.
        - Second record gets a suffix: (Customer) or (Vendor).
        - role: 'customer' or 'vendor'
        """
        name = business.business_name
        other_role_field = (
            'qbo_vendor_id' if role == 'customer' else 'qbo_customer_id'
        )

        other_exists = bool(getattr(business, other_role_field, ''))

        if other_exists:
            suffix = f' ({role.capitalize()})'
            max_base = QBODisplayNameService.QBO_DISPLAY_NAME_MAX - len(suffix)
            name = name[:max_base] + suffix

        return name


class QBOCustomerSyncService:
    """Syncs Minibini Business records to QBO as Customers."""

    @staticmethod
    def push_customer(business):
        """
        Push a Business to QBO as a Customer.
        Returns the QBO Customer ID.
        Skips if already synced (qbo_customer_id is set).
        """
        if business.qbo_customer_id:
            return business.qbo_customer_id

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        customer = QBOCustomerSyncService._build_customer(business)

        qbo_id = QBOService.save_and_log(
            customer, client,
            entity_type='customer',
            qbo_entity_type='Customer',
            entity_id=business.pk,
        )
        with transaction.atomic():
            business.qbo_customer_id = qbo_id
            business.save(update_fields=['qbo_customer_id'])
        return qbo_id

    @staticmethod
    def _build_customer(business):
        """Build a QBO Customer object from a Business."""
        from quickbooks.objects.customer import Customer

        customer = Customer()
        customer.CompanyName = business.business_name
        customer.DisplayName = QBODisplayNameService.generate_display_name(
            business, role='customer'
        )

        if business.business_phone:
            from quickbooks.objects.base import PhoneNumber
            customer.PrimaryPhone = PhoneNumber()
            customer.PrimaryPhone.FreeFormNumber = business.business_phone

        # Use default contact's email if available
        default_contact = business.default_contact
        if default_contact and default_contact.email:
            from quickbooks.objects.base import EmailAddress
            customer.PrimaryEmailAddr = EmailAddress()
            customer.PrimaryEmailAddr.Address = default_contact.email

        return customer


    @staticmethod
    def push_contact_as_customer(contact):
        """
        Push an individual Contact (no business) to QBO as a Customer.
        Returns the QBO Customer ID.
        Skips if already synced (qbo_customer_id is set).
        """
        if contact.qbo_customer_id:
            return contact.qbo_customer_id

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        customer = QBOCustomerSyncService._build_contact_customer(contact)

        qbo_id = QBOService.save_and_log(
            customer, client,
            entity_type='contact_customer',
            qbo_entity_type='Customer',
            entity_id=contact.pk,
        )
        with transaction.atomic():
            contact.qbo_customer_id = qbo_id
            contact.save(update_fields=['qbo_customer_id'])
        return qbo_id

    @staticmethod
    def _build_contact_customer(contact):
        """Build a QBO Customer object from an individual Contact."""
        from quickbooks.objects.customer import Customer

        customer = Customer()
        customer.DisplayName = contact.name
        customer.GivenName = contact.first_name
        customer.FamilyName = contact.last_name

        if contact.email:
            from quickbooks.objects.base import EmailAddress
            customer.PrimaryEmailAddr = EmailAddress()
            customer.PrimaryEmailAddr.Address = contact.email

        phone = contact.phone()
        if phone:
            from quickbooks.objects.base import PhoneNumber
            customer.PrimaryPhone = PhoneNumber()
            customer.PrimaryPhone.FreeFormNumber = phone

        return customer


class QBOVendorSyncService:
    """Syncs Minibini Business records to QBO as Vendors."""

    @staticmethod
    def push_vendor(business):
        """
        Push a Business to QBO as a Vendor.
        Returns the QBO Vendor ID.
        Skips if already synced (qbo_vendor_id is set).
        """
        if business.qbo_vendor_id:
            return business.qbo_vendor_id

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        vendor = QBOVendorSyncService._build_vendor(business)

        qbo_id = QBOService.save_and_log(
            vendor, client,
            entity_type='vendor',
            qbo_entity_type='Vendor',
            entity_id=business.pk,
        )
        with transaction.atomic():
            business.qbo_vendor_id = qbo_id
            business.save(update_fields=['qbo_vendor_id'])
        return qbo_id

    @staticmethod
    def _build_vendor(business):
        """Build a QBO Vendor object from a Business."""
        from quickbooks.objects.vendor import Vendor

        vendor = Vendor()
        vendor.CompanyName = business.business_name
        vendor.DisplayName = QBODisplayNameService.generate_display_name(
            business, role='vendor'
        )

        if business.business_phone:
            from quickbooks.objects.base import PhoneNumber
            vendor.PrimaryPhone = PhoneNumber()
            vendor.PrimaryPhone.FreeFormNumber = business.business_phone

        default_contact = business.default_contact
        if default_contact and default_contact.email:
            from quickbooks.objects.base import EmailAddress
            vendor.PrimaryEmailAddr = EmailAddress()
            vendor.PrimaryEmailAddr.Address = default_contact.email

        return vendor


class QBOInvoiceSyncService:
    """Helpers used by InvoiceEmailService.send_invoice to push an Invoice
    to QBO and fetch the rendered PDF. The full send orchestration lives
    in apps/invoicing/services.py:InvoiceEmailService — including the
    qbo_id short-circuit that fixes the duplicate-push-on-retry bug the
    earlier push_invoice path had."""

    @staticmethod
    def _build_qbo_invoice(invoice, qbo_customer_id, grouped_lines):
        from quickbooks.objects.invoice import Invoice as QBOInvoice
        from quickbooks.objects.detailline import SalesItemLine, SalesItemLineDetail
        from quickbooks.objects.base import Ref

        qbo_inv = QBOInvoice()
        qbo_inv.CustomerRef = Ref()
        qbo_inv.CustomerRef.value = qbo_customer_id

        qbo_inv.Line = []
        for group in grouped_lines:
            line = SalesItemLine()
            line.Amount = float(group['amount'])
            line.Description = group['description']

            detail = SalesItemLineDetail()
            if group['qbo_item_id']:
                detail.ItemRef = Ref()
                detail.ItemRef.value = group['qbo_item_id']

            detail.TaxCodeRef = Ref()
            detail.TaxCodeRef.value = 'TAX' if group['taxable'] else 'NON'

            line.SalesItemLineDetail = detail
            qbo_inv.Line.append(line)

        return qbo_inv

    @staticmethod
    def _mark_as_sent(client, qbo_id):
        """Mark a QBO invoice as sent without triggering QBO's email."""
        from quickbooks.objects.invoice import Invoice as QBOInvoice
        fresh_inv = QBOInvoice.get(qbo_id, qb=client)
        fresh_inv.EmailStatus = 'EmailSent'
        fresh_inv.save(qb=client)

    @staticmethod
    def _download_qbo_pdf(client, qbo_id):
        """Download the QBO invoice as PDF bytes."""
        from quickbooks.objects.invoice import Invoice as QBOInvoice
        qbo_invoice = QBOInvoice.get(qbo_id, qb=client)
        return qbo_invoice.download_pdf(qb=client)

class QBOBillSyncService:
    """Pushes Minibini bills to QBO."""

    @staticmethod
    def push_bill(bill):
        if bill.qbo_id:
            return bill.qbo_id

        business = bill.business
        if not business:
            raise ValueError('Bill must have a vendor business')

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        # Auto-sync vendor to QBO if not already synced
        if not business.qbo_vendor_id:
            QBOVendorSyncService.push_vendor(business)

        qbo_bill = QBOBillSyncService._build_qbo_bill(bill)

        qbo_id = QBOService.save_and_log(
            qbo_bill, client,
            entity_type='bill',
            qbo_entity_type='Bill',
            entity_id=bill.pk,
        )
        bill.qbo_id = qbo_id
        bill.save(update_fields=['qbo_id'])
        return qbo_id

    @staticmethod
    def push_bill_payment(payment):
        """Create a QBO BillPayment for a recorded Minibini BillPayment.
        Idempotent on payment.qbo_id. Never raises — records sync state on the
        payment via QBOSyncService."""
        if payment.qbo_id:
            return payment.qbo_id
        return QBOSyncService.run_create(
            payment,
            lambda: QBOBillSyncService._build_qbo_bill_payment(payment),
        )

    @staticmethod
    def _build_qbo_bill_payment(payment):
        from quickbooks.objects.billpayment import (
            BillPayment as QBOBillPayment, BillPaymentLine,
            CheckPayment, BillPaymentCreditCard,
        )
        from quickbooks.objects.base import Ref, LinkedTxn

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')
        if not payment.payment_account_id:
            raise ValueError('No payment account selected for this bill payment')

        bill = payment.bill
        if not bill.qbo_id:
            QBOBillSyncService.push_bill(bill)

        account = QBOPaymentAccountService.lookup(payment.payment_account_id)

        qbp = QBOBillPayment()
        qbp.TotalAmt = float(payment.amount)
        if payment.reference:
            qbp.DocNumber = payment.reference

        vendor_ref = Ref()
        vendor_ref.value = bill.business.qbo_vendor_id
        qbp.VendorRef = vendor_ref

        acct_ref = Ref()
        acct_ref.value = account['qbo_account_id']
        if account['account_type'] == 'Credit Card':
            qbp.PayType = 'CreditCard'
            cc = BillPaymentCreditCard()
            cc.CCAccountRef = acct_ref
            qbp.CreditCardPayment = cc
        else:
            qbp.PayType = 'Check'
            chk = CheckPayment()
            chk.BankAccountRef = acct_ref
            qbp.CheckPayment = chk

        line = BillPaymentLine()
        line.Amount = float(payment.amount)
        linked = LinkedTxn()
        linked.TxnId = bill.qbo_id
        linked.TxnType = 'Bill'
        line.LinkedTxn = [linked]
        qbp.Line = [line]

        return QBOService.save_and_log(
            qbp, client,
            entity_type='bill_payment',
            qbo_entity_type='BillPayment',
            entity_id=payment.pk,
        )

    @staticmethod
    def update_bill_payment(payment):
        """Re-fetch and update the QBO BillPayment with the current local values.
        Raises ValueError if the payment has no qbo_id or there is no active connection."""
        from quickbooks.objects.billpayment import BillPayment as QBOBillPayment
        if not payment.qbo_id:
            raise ValueError('BillPayment has no qbo_id — use push_bill_payment')
        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')
        existing = QBOBillPayment.get(payment.qbo_id, qb=client)
        existing.TotalAmt = float(payment.amount)
        if payment.reference:
            existing.DocNumber = payment.reference
        if existing.Line:
            existing.Line[0].Amount = float(payment.amount)
        QBOService.save_and_log(
            existing, client,
            entity_type='bill_payment',
            qbo_entity_type='BillPayment',
            entity_id=payment.pk,
            action='update',
        )
        return payment.qbo_id

    @staticmethod
    def void_bill_payment(payment):
        """Delete the QBO BillPayment. Raises on failure so the caller refuses the local delete."""
        from quickbooks.objects.billpayment import BillPayment as QBOBillPayment
        if not payment.qbo_id:
            return
        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')
        QBOService.delete_and_log(
            QBOBillPayment, payment.qbo_id, client,
            entity_type='bill_payment', qbo_entity_type='BillPayment', entity_id=payment.pk,
        )

    @staticmethod
    def _build_qbo_bill(bill):
        from quickbooks.objects.bill import Bill as QBOBill
        from quickbooks.objects.detailline import AccountBasedExpenseLine, AccountBasedExpenseLineDetail
        from quickbooks.objects.base import Ref

        qbo_bill = QBOBill()
        qbo_bill.VendorRef = Ref()
        qbo_bill.VendorRef.value = bill.business.qbo_vendor_id

        if bill.vendor_invoice_number:
            qbo_bill.DocNumber = bill.vendor_invoice_number

        qbo_bill.Line = []
        for item in bill.billlineitem_set.select_related('accounting_category').all():
            line = AccountBasedExpenseLine()
            line.Amount = float(item.total_amount)
            line.Description = item.description

            detail = AccountBasedExpenseLineDetail()
            if item.accounting_category and item.accounting_category.qbo_expense_account_id:
                detail.AccountRef = Ref()
                detail.AccountRef.value = item.accounting_category.qbo_expense_account_id

            line.AccountBasedExpenseLineDetail = detail
            qbo_bill.Line.append(line)

        return qbo_bill


class QBOAccountsService:
    """Pulls Items and chart of accounts from QBO for category mapping."""

    @staticmethod
    def get_income_items():
        """Return Service and NonInventory Items from QBO."""
        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        from quickbooks.objects.item import Item
        items = Item.filter(Active=True, qb=client)
        return [
            {
                'id': str(i.Id),
                'name': i.Name,
                'type': getattr(i, 'Type', ''),
            }
            for i in items
            if getattr(i, 'Type', '') in ('Service', 'NonInventory')
        ]

    @staticmethod
    def get_expense_accounts():
        """Return expense + COGS accounts from QBO."""
        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        from quickbooks.objects.account import Account
        expense = Account.filter(AccountType='Expense', Active=True, qb=client)
        cogs = Account.filter(AccountType='Cost of Goods Sold', Active=True, qb=client)
        seen = set()
        results = []
        for a in list(expense) + list(cogs):
            aid = str(a.Id)
            if aid not in seen:
                seen.add(aid)
                results.append({
                    'id': aid,
                    'name': a.Name,
                    'type': a.AccountType,
                    'sub_type': getattr(a, 'AccountSubType', ''),
                })
        return results


class QBOPaymentAccountService:
    """Owns the `qbo_payment_accounts` Configuration lookup. Shared by the
    expense/reimbursement Purchase push and the bill-payment push."""

    @staticmethod
    def load_accounts():
        """Parsed payment-account config JSON; [] if unset/blank."""
        try:
            raw = Configuration.objects.get(key='qbo_payment_accounts').value
        except Configuration.DoesNotExist:
            return []
        if not raw:
            return []
        return json.loads(raw)

    @staticmethod
    def lookup(payment_account_id):
        """Return the dict for a given qbo_account_id, or raise ValueError."""
        for a in QBOPaymentAccountService.load_accounts():
            if a['qbo_account_id'] == payment_account_id:
                return a
        raise ValueError(
            f"payment_account_id={payment_account_id!r} not in configured payment accounts"
        )


class QBOExpenseSyncService:
    """Pushes Minibini expenses and reimbursement batches to QBO.
    Follows the pattern of QBOBillSyncService."""

    @staticmethod
    def get_payment_accounts():
        """
        Return Bank, Credit Card, and Other Current Asset accounts from QBO.
        Used by the Settings page to populate the payment-account config JSON.
        """
        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        from quickbooks.objects.account import Account
        results = []
        for account_type in ('Bank', 'Credit Card', 'Other Current Asset'):
            for a in Account.filter(AccountType=account_type, Active=True, qb=client):
                results.append({
                    'qbo_account_id': str(a.Id),
                    'display_name': a.Name,
                    'account_type': account_type,
                })
        return results

    # ---- config helpers ----

    @staticmethod
    def _load_payment_accounts():
        return QBOPaymentAccountService.load_accounts()

    @staticmethod
    def _lookup_account(payment_account_id):
        return QBOPaymentAccountService.lookup(payment_account_id)

    @staticmethod
    def _derive_payment_type(account_type, reference_number):
        """Map an account type + reference number to a QBO PaymentType (or None)."""
        if account_type == 'Credit Card':
            return 'CreditCard'
        if account_type == 'Bank' and reference_number:
            return 'Check'
        return None

    # ---- line builder ----

    @staticmethod
    def _build_expense_line(expense):
        from quickbooks.objects.detailline import (
            AccountBasedExpenseLine, AccountBasedExpenseLineDetail,
        )
        from quickbooks.objects.base import Ref

        line = AccountBasedExpenseLine()
        line.Amount = float(expense.amount)
        line.Description = expense.description or f"Expense #{expense.pk}"

        detail = AccountBasedExpenseLineDetail()
        if expense.accounting_category and expense.accounting_category.qbo_expense_account_id:
            detail.AccountRef = Ref()
            detail.AccountRef.value = expense.accounting_category.qbo_expense_account_id
        line.AccountBasedExpenseLineDetail = detail
        return line

    # ---- purchase builder ----

    @staticmethod
    def _build_qbo_purchase_for_expense(expense):
        from quickbooks.objects.purchase import Purchase
        from quickbooks.objects.base import Ref

        account = QBOExpenseSyncService._lookup_account(expense.payment_account_id)

        purchase = Purchase()
        purchase.AccountRef = Ref()
        purchase.AccountRef.value = account['qbo_account_id']

        payment_type = QBOExpenseSyncService._derive_payment_type(
            account['account_type'], expense.reference_number,
        )
        if payment_type:
            purchase.PaymentType = payment_type
        if expense.reference_number:
            purchase.DocNumber = expense.reference_number

        purchase.TxnDate = expense.purchased_on.isoformat()
        purchase.PrivateNote = (
            f"Minibini expense #{expense.pk} — entered by {expense.entered_by.username}"
        )

        purchase.Line = [QBOExpenseSyncService._build_expense_line(expense)]
        return purchase

    # ---- push / update / void ----

    @staticmethod
    def push_expense(expense):
        """Create a QBO Purchase for a company-paid expense. Returns qbo_id."""
        if expense.qbo_id:
            return expense.qbo_id

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        qbo_purchase = QBOExpenseSyncService._build_qbo_purchase_for_expense(expense)

        qbo_id = QBOService.save_and_log(
            qbo_purchase, client,
            entity_type='expense',
            qbo_entity_type='Purchase',
            entity_id=expense.pk,
        )
        expense.qbo_id = qbo_id
        expense.save(update_fields=['qbo_id'])
        return qbo_id

    @staticmethod
    def update_expense(expense):
        """Re-sync a modified company-paid expense to its existing QBO Purchase."""
        if not expense.qbo_id:
            raise ValueError('Expense has no qbo_id — use push_expense instead')

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        from quickbooks.objects.purchase import Purchase
        from quickbooks.objects.base import Ref

        existing = Purchase.get(expense.qbo_id, qb=client)

        account = QBOExpenseSyncService._lookup_account(expense.payment_account_id)
        existing.AccountRef = Ref()
        existing.AccountRef.value = account['qbo_account_id']

        payment_type = QBOExpenseSyncService._derive_payment_type(
            account['account_type'], expense.reference_number,
        )
        if payment_type:
            existing.PaymentType = payment_type
        existing.DocNumber = expense.reference_number or ''
        existing.TxnDate = expense.purchased_on.isoformat()
        existing.Line = [QBOExpenseSyncService._build_expense_line(expense)]

        QBOService.save_and_log(
            existing, client,
            entity_type='expense',
            qbo_entity_type='Purchase',
            entity_id=expense.pk,
            action='update',
        )

    @staticmethod
    def void_expense(expense):
        """Delete the QBO Purchase for this expense. Raises on failure so the caller refuses the local delete."""
        from quickbooks.objects.purchase import Purchase
        if not expense.qbo_id:
            return
        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')
        QBOService.delete_and_log(
            Purchase, expense.qbo_id, client,
            entity_type='expense', qbo_entity_type='Purchase', entity_id=expense.pk,
        )

    # ---- reimbursement batch push / update / void ----

    @staticmethod
    def _build_qbo_purchase_for_reimbursement(batch):
        from quickbooks.objects.purchase import Purchase
        from quickbooks.objects.base import Ref

        account = QBOExpenseSyncService._lookup_account(batch.payment_account_id)

        purchase = Purchase()
        purchase.AccountRef = Ref()
        purchase.AccountRef.value = account['qbo_account_id']

        payment_type = QBOExpenseSyncService._derive_payment_type(
            account['account_type'], batch.reference_number,
        )
        if payment_type:
            purchase.PaymentType = payment_type
        if batch.reference_number:
            purchase.DocNumber = batch.reference_number

        purchase.TxnDate = batch.paid_on.isoformat()
        purchase.PrivateNote = (
            f"Reimbursement to {batch.purchased_by.username} — Minibini batch #{batch.pk}"
        )

        purchase.Line = [
            QBOExpenseSyncService._build_expense_line(e)
            for e in batch.expenses.all().order_by('pk')
        ]
        return purchase

    @staticmethod
    def push_reimbursement(batch):
        """Create a QBO Purchase for a reimbursement batch. Returns qbo_id."""
        if batch.qbo_id:
            return batch.qbo_id

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        qbo_purchase = QBOExpenseSyncService._build_qbo_purchase_for_reimbursement(batch)

        qbo_id = QBOService.save_and_log(
            qbo_purchase, client,
            entity_type='reimbursement',
            qbo_entity_type='Purchase',
            entity_id=batch.pk,
        )
        batch.qbo_id = qbo_id
        batch.save(update_fields=['qbo_id'])
        return qbo_id

    @staticmethod
    def update_reimbursement(batch):
        """Re-sync a batch's QBO Purchase (after an expense edit or batch note change)."""
        if not batch.qbo_id:
            raise ValueError('Reimbursement has no qbo_id — use push_reimbursement instead')

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        from quickbooks.objects.purchase import Purchase
        from quickbooks.objects.base import Ref

        existing = Purchase.get(batch.qbo_id, qb=client)

        account = QBOExpenseSyncService._lookup_account(batch.payment_account_id)
        existing.AccountRef = Ref()
        existing.AccountRef.value = account['qbo_account_id']

        payment_type = QBOExpenseSyncService._derive_payment_type(
            account['account_type'], batch.reference_number,
        )
        if payment_type:
            existing.PaymentType = payment_type
        existing.DocNumber = batch.reference_number or ''
        existing.TxnDate = batch.paid_on.isoformat()
        existing.Line = [
            QBOExpenseSyncService._build_expense_line(e)
            for e in batch.expenses.all().order_by('pk')
        ]

        QBOService.save_and_log(
            existing, client,
            entity_type='reimbursement',
            qbo_entity_type='Purchase',
            entity_id=batch.pk,
            action='update',
        )

    @staticmethod
    def void_reimbursement(batch):
        """Delete the QBO Purchase for this batch. Logs but doesn't raise on failure."""
        if not batch.qbo_id:
            return

        client = QBOService.get_client()
        if not client:
            QBOService.log_sync(
                entity_type='reimbursement',
                entity_id=batch.pk,
                qbo_entity_type='Purchase',
                qbo_entity_id=batch.qbo_id,
                action='delete',
                status='failed',
                error_message='No active QBO connection',
            )
            return

        from quickbooks.objects.purchase import Purchase
        try:
            existing = Purchase.get(batch.qbo_id, qb=client)
            existing.delete(qb=client)
            QBOService.log_sync(
                entity_type='reimbursement',
                entity_id=batch.pk,
                qbo_entity_type='Purchase',
                qbo_entity_id=batch.qbo_id,
                action='delete',
                status='success',
            )
        except Exception as e:
            QBOService.log_sync(
                entity_type='reimbursement',
                entity_id=batch.pk,
                qbo_entity_type='Purchase',
                qbo_entity_id=batch.qbo_id,
                action='delete',
                status='failed',
                error_message=str(e),
            )
            # Intentionally do NOT raise — caller still deletes locally.


class QBOPaymentPollingService:
    """Polls QBO for payment status updates on synced invoices."""

    @staticmethod
    def poll_all():
        from django.db import transaction
        from apps.invoicing.models import Invoice
        from apps.core.models import User

        stats = {'checked': 0, 'transitioned': 0, 'cache_updated': 0, 'errors': []}

        client = QBOService.get_client()
        if not client:
            stats['error'] = 'No active QBO connection'
            return stats

        system_user, _ = User.objects.get_or_create(
            username='system', defaults={'first_name': 'System', 'is_active': False},
        )
        invoices = Invoice.objects.filter(
            qbo_id__isnull=False,
            status__in=[Invoice.STATUS_OPEN, Invoice.STATUS_PARTLY_PAID],
        )
        for invoice in invoices:
            stats['checked'] += 1
            try:
                qbo_inv = QBOPaymentPollingService._fetch_qbo_invoice(client, invoice.qbo_id)
                if qbo_inv is None:
                    stats['errors'].append(f'Invoice {invoice.pk}: not found in QBO')
                    continue

                total = Decimal(str(qbo_inv.TotalAmt))
                balance = Decimal(str(qbo_inv.Balance))
                amount_paid = total - balance

                if balance == 0:
                    cache_status, target_status = 'Paid', Invoice.STATUS_PAID
                elif amount_paid > 0:
                    cache_status, target_status = 'Partial', Invoice.STATUS_PARTLY_PAID
                else:
                    cache_status, target_status = 'Unpaid', None

                cache_changed = (invoice.qbo_payment_status != cache_status
                                 or invoice.qbo_amount_paid != amount_paid)
                status_changed = target_status is not None and invoice.status != target_status

                if not (cache_changed or status_changed):
                    continue

                old_status = invoice.status
                with transaction.atomic():
                    invoice.qbo_payment_status = cache_status
                    invoice.qbo_amount_paid = amount_paid
                    if status_changed:
                        invoice.status = target_status
                    invoice.save()  # full save → fires _maybe_complete_job + closed_date
                    if status_changed:
                        record_history(
                            entry_type='action', object_type='invoice', object_id=invoice.pk,
                            user=system_user,
                            changes={
                                'status': {'old': old_status, 'new': target_status},
                                '_action': f'Payment synced from QBO — marked {target_status}',
                            },
                        )

                if cache_changed:
                    stats['cache_updated'] += 1
                if status_changed:
                    stats['transitioned'] += 1
            except Exception as e:  # noqa: BLE001 - record per-invoice failures, keep polling
                stats['errors'].append(f'Invoice {invoice.pk}: {str(e)}')

        return stats

    @staticmethod
    def _fetch_qbo_invoice(client, qbo_id):
        from quickbooks.objects.invoice import Invoice as QBOInvoice
        return QBOInvoice.get(qbo_id, qb=client)


class QBOBillPaymentPollingService:
    """Polls QBO for payment status updates on synced bills."""

    @staticmethod
    def poll_all():
        """Clear per-BillPayment from QBO reconciliation. STUBBED: all QBO ->
        Minibini polling is deferred to a dedicated later session. The
        bill-payment push is live and writes `qbo_id`, so rows can match the
        filter below; the inner loop just doesn't fetch/confirm clearance yet."""
        from apps.purchasing.models import BillPayment
        stats = {'checked': 0, 'cleared': 0, 'errors': []}
        client = QBOService.get_client()
        if not client:
            stats['error'] = 'No active QBO connection'
            return stats
        pending = BillPayment.objects.filter(
            cleared_date__isnull=True).exclude(qbo_id='')
        for payment in pending:
            stats['checked'] += 1
            # QBO reconciliation fetch + cleared_date set lands in the QBO session.
        return stats


class QBOInboundPollingService:
    """Single entry point for all QBO -> Minibini polling. Sweeps every inbound
    type (invoice payments, bill clearance; future: Job-P&L actuals, CDC)."""

    @staticmethod
    def poll_all():
        return {
            'invoices': QBOPaymentPollingService.poll_all(),
            'bills': QBOBillPaymentPollingService.poll_all(),
        }


class QBOSyncService:
    """Wraps the push/resync try-except so every adopter records its sync
    outcome the same way. Never raises — a QBO hiccup must not block the local
    write that already committed."""

    @staticmethod
    def run_create(record, push_callable):
        """push_callable() does the QBO create and returns the new qbo_id."""
        try:
            qbo_id = push_callable()
            if qbo_id:
                record.mark_synced(qbo_id)
            return qbo_id
        except Exception as e:  # noqa: BLE001
            logger.exception('QBO create sync failed for %r', record)
            record.mark_failed(e)
            return None

    @staticmethod
    def run_resync(record, resync_callable):
        """resync_callable() updates the existing QBO object (qbo_id unchanged)."""
        try:
            resync_callable()
            record.mark_synced(record.qbo_id)
        except Exception as e:  # noqa: BLE001
            logger.exception('QBO resync failed for %r', record)
            record.mark_failed(e)

    @staticmethod
    def run_delete(record, delete_callable):
        """delete_callable() performs the QBO delete.

        On success: returns None.
        On failure: marks the record sync_failed AND re-raises — the re-raise is
        deliberate so the caller can abort the local delete and retain the row.
        This is the key difference from run_create/run_resync, which swallow.
        """
        try:
            delete_callable()
        except Exception as e:
            record.mark_failed(e)
            raise

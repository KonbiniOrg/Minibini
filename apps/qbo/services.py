import datetime
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.qbo.models import QBOConnection, QBOSyncLog


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

        try:
            customer.save(qb=client)
            with transaction.atomic():
                business.qbo_customer_id = str(customer.Id)
                business.save(update_fields=['qbo_customer_id'])

                QBOService.log_sync(
                    entity_type='customer',
                    entity_id=business.pk,
                    qbo_entity_type='Customer',
                    qbo_entity_id=str(customer.Id),
                    action='create',
                    status='success',
                )
            return str(customer.Id)

        except Exception as e:
            QBOService.log_sync(
                entity_type='customer',
                entity_id=business.pk,
                qbo_entity_type='Customer',
                qbo_entity_id='',
                action='create',
                status='failed',
                error_message=str(e),
            )
            raise

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

        try:
            customer.save(qb=client)
            with transaction.atomic():
                contact.qbo_customer_id = str(customer.Id)
                contact.save(update_fields=['qbo_customer_id'])

                QBOService.log_sync(
                    entity_type='contact_customer',
                    entity_id=contact.pk,
                    qbo_entity_type='Customer',
                    qbo_entity_id=str(customer.Id),
                    action='create',
                    status='success',
                )
            return str(customer.Id)

        except Exception as e:
            QBOService.log_sync(
                entity_type='contact_customer',
                entity_id=contact.pk,
                qbo_entity_type='Customer',
                qbo_entity_id='',
                action='create',
                status='failed',
                error_message=str(e),
            )
            raise

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

        try:
            vendor.save(qb=client)
            with transaction.atomic():
                business.qbo_vendor_id = str(vendor.Id)
                business.save(update_fields=['qbo_vendor_id'])

                QBOService.log_sync(
                    entity_type='vendor',
                    entity_id=business.pk,
                    qbo_entity_type='Vendor',
                    qbo_entity_id=str(vendor.Id),
                    action='create',
                    status='success',
                )
            return str(vendor.Id)

        except Exception as e:
            QBOService.log_sync(
                entity_type='vendor',
                entity_id=business.pk,
                qbo_entity_type='Vendor',
                qbo_entity_id='',
                action='create',
                status='failed',
                error_message=str(e),
            )
            raise

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
    """Pushes Minibini invoices to QBO."""

    @staticmethod
    def push_invoice(invoice, send_to, cc=None, bcc=None):
        if invoice.qbo_id:
            return invoice.qbo_id

        contact = invoice.job.contact
        business = contact.business

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        # Resolve QBO customer ID: business path or individual contact path
        if business:
            if not business.qbo_customer_id:
                QBOCustomerSyncService.push_customer(business)
            qbo_customer_id = business.qbo_customer_id
        else:
            if not contact.qbo_customer_id:
                QBOCustomerSyncService.push_contact_as_customer(contact)
                contact.refresh_from_db()
            qbo_customer_id = contact.qbo_customer_id

        from apps.invoicing.services import InvoiceGroupingService
        grouped_lines = InvoiceGroupingService.group_for_qbo(invoice)
        qbo_invoice = QBOInvoiceSyncService._build_qbo_invoice(
            invoice, qbo_customer_id, grouped_lines
        )

        try:
            qbo_invoice.save(qb=client)
            qbo_id = str(qbo_invoice.Id)

            # Save qbo_id immediately so retries don't create duplicates
            invoice.qbo_id = qbo_id
            invoice.save(update_fields=['qbo_id'])

            # Attach job statement PDF
            from apps.invoicing.pdf import generate_job_statement_pdf
            statement_pdf = generate_job_statement_pdf(invoice)
            QBOInvoiceSyncService._attach_pdf(client, qbo_id, statement_pdf, invoice)

            # Mark as sent in QBO (so it doesn't show "needs to be sent")
            QBOInvoiceSyncService._mark_as_sent(client, qbo_id)

            # Download QBO invoice PDF (includes tax calc and Pay Now link)
            qbo_invoice_pdf = QBOInvoiceSyncService._download_qbo_pdf(client, qbo_id)

            # Send both PDFs via Minibini's email
            QBOInvoiceSyncService._send_email(
                invoice, send_to, cc, bcc,
                qbo_invoice_pdf, statement_pdf,
            )

            QBOService.log_sync(
                entity_type='invoice',
                entity_id=invoice.pk,
                qbo_entity_type='Invoice',
                qbo_entity_id=qbo_id,
                action='create',
                status='success',
            )
            return qbo_id

        except Exception as e:
            QBOService.log_sync(
                entity_type='invoice',
                entity_id=invoice.pk,
                qbo_entity_type='Invoice',
                qbo_entity_id='',
                action='create',
                status='failed',
                error_message=str(e),
            )
            raise

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
    def _attach_pdf(client, qbo_invoice_id, pdf_bytes, invoice):
        from quickbooks.objects.attachable import Attachable, AttachableRef
        import tempfile
        import os

        filename = f"job_statement_{invoice.invoice_number}.pdf"
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(pdf_bytes)
            temp_path = f.name

        try:
            attachable = Attachable()
            attachable_ref = AttachableRef()
            attachable_ref.EntityRef = {'type': 'Invoice', 'value': qbo_invoice_id}
            attachable.AttachableRef = [attachable_ref]
            attachable.FileName = filename
            attachable.ContentType = 'application/pdf'
            attachable._FilePath = temp_path
            attachable.save(qb=client)
        finally:
            os.unlink(temp_path)

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

    @staticmethod
    def _send_email(invoice, send_to, cc, bcc, qbo_invoice_pdf, statement_pdf):
        """Send invoice email via Minibini with both PDFs attached."""
        from apps.core.services import OutboundEmailService

        job = invoice.job
        subject = f'Invoice {invoice.invoice_number} — {job.job_number}'
        body = (
            f'Please find attached your invoice and job statement '
            f'for {job.job_number}.\n\n'
            f'The invoice includes a link to view and pay online.'
        )

        attachments = [
            (f'Invoice_{invoice.invoice_number}.pdf',
             qbo_invoice_pdf, 'application/pdf'),
            (f'Job_Statement_{invoice.invoice_number}.pdf',
             statement_pdf, 'application/pdf'),
        ]

        to_list = [send_to] if isinstance(send_to, str) else send_to
        cc_list = [e.strip() for e in cc.split(',') if e.strip()] if cc else []
        bcc_list = [e.strip() for e in bcc.split(',') if e.strip()] if bcc else []

        OutboundEmailService.send_email(
            to=to_list, subject=subject, body=body,
            cc=cc_list, bcc=bcc_list, attachments=attachments,
        )


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

        try:
            qbo_bill.save(qb=client)
            qbo_id = str(qbo_bill.Id)

            bill.qbo_id = qbo_id
            bill.save(update_fields=['qbo_id'])

            QBOService.log_sync(
                entity_type='bill',
                entity_id=bill.pk,
                qbo_entity_type='Bill',
                qbo_entity_id=qbo_id,
                action='create',
                status='success',
            )
            return qbo_id

        except Exception as e:
            QBOService.log_sync(
                entity_type='bill',
                entity_id=bill.pk,
                qbo_entity_type='Bill',
                qbo_entity_id='',
                action='create',
                status='failed',
                error_message=str(e),
            )
            raise

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


class QBOPaymentPollingService:
    """Polls QBO for payment status updates on synced invoices."""

    @staticmethod
    def poll_all():
        from apps.invoicing.models import Invoice

        stats = {'checked': 0, 'updated': 0, 'errors': []}

        client = QBOService.get_client()
        if not client:
            stats['error'] = 'No active QBO connection'
            return stats

        invoices = Invoice.objects.filter(
            qbo_id__isnull=False,
        ).exclude(
            qbo_payment_status='Paid',
        )

        for invoice in invoices:
            stats['checked'] += 1
            try:
                qbo_inv = QBOPaymentPollingService._fetch_qbo_invoice(
                    client, invoice.qbo_id
                )
                if qbo_inv is None:
                    stats['errors'].append(f'Invoice {invoice.pk}: not found in QBO')
                    continue

                total = Decimal(str(qbo_inv.TotalAmt))
                balance = Decimal(str(qbo_inv.Balance))
                amount_paid = total - balance

                if balance == 0:
                    payment_status = 'Paid'
                elif amount_paid > 0:
                    payment_status = 'Partial'
                else:
                    payment_status = 'Unpaid'

                if (invoice.qbo_payment_status != payment_status or
                        invoice.qbo_amount_paid != amount_paid):
                    invoice.qbo_payment_status = payment_status
                    invoice.qbo_amount_paid = amount_paid
                    invoice.save(update_fields=[
                        'qbo_payment_status', 'qbo_amount_paid'
                    ])
                    stats['updated'] += 1

            except Exception as e:
                stats['errors'].append(f'Invoice {invoice.pk}: {str(e)}')

        return stats

    @staticmethod
    def _fetch_qbo_invoice(client, qbo_id):
        from quickbooks.objects.invoice import Invoice as QBOInvoice
        return QBOInvoice.get(qbo_id, qb=client)

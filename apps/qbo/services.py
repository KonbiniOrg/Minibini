import datetime
import logging
from apps.core.history import record_history
import json
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
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
                 action, status, error_message='', triggered_by=None):
        """Create a sync log entry.

        triggered_by defaults to the authenticated user from the active request
        context (apps.core.history.current_request_user).  Pass an explicit User
        instance to override, or pass triggered_by=None to use the context (the
        default — None means "fall back to context", not "force null").
        """
        from apps.core.history import current_request_user
        if triggered_by is None:
            triggered_by = current_request_user()
        return QBOSyncLog.objects.create(
            entity_type=entity_type,
            entity_id=entity_id,
            qbo_entity_type=qbo_entity_type,
            qbo_entity_id=qbo_entity_id,
            action=action,
            status=status,
            error_message=error_message,
            triggered_by=triggered_by,
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

        try:
            qbo_id = QBOService.save_and_log(
                customer, client,
                entity_type='customer',
                qbo_entity_type='Customer',
                entity_id=business.pk,
            )
        except Exception as e:
            # Duplicate DisplayName → the Customer already exists in QBO;
            # adopt it (same pattern as QBOItemMintService). save_and_log
            # already recorded the failed create attempt.
            if not _is_duplicate_name_error(e):
                raise
            from quickbooks.objects.customer import Customer
            qbo_id = _adopt_id_by_name(
                Customer, client, DisplayName=customer.DisplayName)
            if not qbo_id:
                raise
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

        try:
            qbo_id = QBOService.save_and_log(
                customer, client,
                entity_type='contact_customer',
                qbo_entity_type='Customer',
                entity_id=contact.pk,
            )
        except Exception as e:
            if not _is_duplicate_name_error(e):
                raise
            from quickbooks.objects.customer import Customer
            qbo_id = _adopt_id_by_name(
                Customer, client, DisplayName=customer.DisplayName)
            if not qbo_id:
                raise
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


class QBOInvoiceSyncService:
    """Helpers used by InvoiceEmailService.send_invoice to push an Invoice
    to QBO and fetch the rendered PDF. The full send orchestration lives
    in apps/invoicing/services.py:InvoiceEmailService — including the
    qbo_id short-circuit that fixes the duplicate-push-on-retry bug the
    earlier push_invoice path had."""

    @staticmethod
    def _build_qbo_invoice(invoice, qbo_customer_id, client):
        """Build the QBO Invoice with one SalesItemLine per konbini line.

        Description is the konbini line's text verbatim; ItemRef comes from
        _resolve_item_ref (minting catalog Items lazily via the client);
        TaxCodeRef is the line's category `taxable` flag. The job reference
        rides in CustomerMemo; online-payment flags are enabled so the
        hosted invoice carries the Pay button when QBO Payments is active.
        """
        from quickbooks.objects.invoice import Invoice as QBOInvoice
        from quickbooks.objects.detailline import SalesItemLine, SalesItemLineDetail
        from quickbooks.objects.base import Ref, EmailAddress, CustomerMemo

        qbo_inv = QBOInvoice()
        qbo_inv.CustomerRef = Ref()
        qbo_inv.CustomerRef.value = qbo_customer_id
        qbo_inv.AllowOnlineCreditCardPayment = True
        qbo_inv.AllowOnlineACHPayment = True

        job = invoice.job
        memo = CustomerMemo()
        memo.value = f"Job {job.job_number} — {job.name}"
        qbo_inv.CustomerMemo = memo

        contact = job.contact
        if contact and contact.email:
            qbo_inv.BillEmail = EmailAddress()
            qbo_inv.BillEmail.Address = contact.email

        qbo_inv.Line = []
        line_items = (invoice.invoicelineitem_set
                      .select_related('accounting_category', 'inventory_item')
                      .order_by('line_number'))
        for li in line_items:
            QBOInvoiceSyncService._require_line_category(li)

            line = SalesItemLine()
            line.Amount = float(li.total_amount)
            line.Description = li.description

            detail = SalesItemLineDetail()
            # Qty/UnitPrice make QBO render the qty and rate columns
            # instead of a bare total.
            detail.Qty = float(li.qty)
            detail.UnitPrice = float(li.price)
            item_id = QBOInvoiceSyncService._resolve_item_ref(li, client)
            if item_id:
                detail.ItemRef = Ref()
                detail.ItemRef.value = item_id
            detail.TaxCodeRef = Ref()
            detail.TaxCodeRef.value = 'TAX' if li.accounting_category.taxable else 'NON'

            line.SalesItemLineDetail = detail
            qbo_inv.Line.append(line)

        return qbo_inv

    @staticmethod
    def _require_line_category(line_item):
        """Raise ValidationError naming the offending line when it has no
        accounting category.

        Defensive guard: invoice authoring stamps the configured fallback
        AccountingCategory onto any line whose deriving atom carries none
        (Phase 3 Task 5), so a null-AC line should be unreachable via
        normal authoring flows. Hand lines can still be created with a
        null AC deliberately, though — InvoiceEmailService's send-gate
        (`_assert_all_lines_categorized`) is the primary catch for those;
        this is the second line of defense for any push path that reaches
        QBO line-building without going through that gate (e.g. a retry
        or a future direct-push caller). Without this, the line would hit
        a bare AttributeError on `.taxable` / `.qbo_item_id` further down.
        """
        if line_item.accounting_category_id is None:
            raise ValidationError(
                f"Invoice line {line_item.line_number} "
                f"('{line_item.description}') has no accounting category. "
                f"Categorize the line, or configure the "
                f"fallback_accounting_category setting, before sending to "
                f"QBO."
            )

    @staticmethod
    def _catalog_entity_for_line(line_item):
        """The single catalog entity (InventoryItem or ServiceItem) this line
        sells, or None when there isn't exactly one."""
        if line_item.inventory_item_id:
            return line_item.inventory_item
        if line_item.adjustment_service_id:
            return None
        entities = set()
        sources = list(line_item.sources.all())
        if not sources:
            return None
        for source in sources:
            if source.source_type == source.SOURCE_TASK:
                task = source.resolve()
                if not task.service_item_id:
                    return None
                entities.add(('service', task.service_item_id))
            elif source.source_type == source.SOURCE_MATERIAL:
                material = source.resolve()
                if not material.inventory_item_id:
                    return None
                entities.add(('inventory', material.inventory_item_id))
            else:  # expense — no catalog identity
                return None
        if len(entities) != 1:
            return None
        kind, pk = entities.pop()
        if kind == 'service':
            from apps.estimates.models import ServiceItem
            return ServiceItem.objects.get(pk=pk)
        from apps.inventory.models import InventoryItem
        return InventoryItem.objects.get(pk=pk)

    @staticmethod
    def _resolve_item_ref(line_item, client):
        """QBO Item id for this line, or None to omit ItemRef.

        Raises ValidationError (via `_require_line_category`) if the line
        carries no catalog entity to mint/adopt an Item from *and* has no
        accounting_category of its own to fall back to — see
        `_require_line_category` for why this line should be unreachable
        via normal authoring flows and why the guard exists anyway.
        """
        entity = QBOInvoiceSyncService._catalog_entity_for_line(line_item)
        if entity is not None:
            qbo_id = QBOItemMintService.ensure_item(entity, client)
            if qbo_id:
                return qbo_id
        QBOInvoiceSyncService._require_line_category(line_item)
        category = line_item.accounting_category
        if category.qbo_item_id:
            return category.qbo_item_id
        return None

    @staticmethod
    def _fetch_invoice_link(client, qbo_id):
        """Shareable hosted-invoice URL (carries the Pay button when QBO
        Payments is active). '' when QBO returns none.

        The installed python-quickbooks get()/get_single_object() can't pass
        query params, so this builds the request directly on the client.
        """
        url = "{0}/company/{1}/invoice/{2}/".format(
            client.api_url, client.company_id, qbo_id)
        # minorversion >= 36 is required or QBO silently omits invoiceLink
        # from the response (no error — the field just isn't there).
        result = client.get(url, {}, params={
            'include': 'invoiceLink', 'minorversion': '75',
        })
        inv = result.get('Invoice') or {}
        # QBO's raw JSON returns 'InvoiceLink' (capital I) even though the
        # docs and SDK say 'invoiceLink' — accept both.
        return inv.get('InvoiceLink') or inv.get('invoiceLink') or ''

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

def _is_duplicate_name_error(exc):
    """QBO's 6240 Duplicate Name Exists Error, in any of its phrasings."""
    text = str(exc)
    return 'Duplicate Name Exists' in text or '6240' in text


def _adopt_id_by_name(sdk_class, client, **name_filter):
    """Adopt an existing QBO record after a duplicate-name refusal.

    QBO companies routinely predate konbini (future tenants; reseeded dev
    DBs against a lived-in sandbox), so a name collision usually means
    "this record already exists over there" — query it by its name field
    and return str(Id). Returns None when no match (e.g. the collision is
    with an inactive record the default query can't see) — caller
    re-raises. Accepted trade-off: a same-named-but-genuinely-different
    record binds silently.
    """
    existing = sdk_class.filter(qb=client, **name_filter)
    if not existing:
        return None
    return str(existing[0].Id)


class QBOItemMintService:
    """Lazily mirrors konbini catalog entities (InventoryItem, ServiceItem)
    into QBO Items at invoice-push time.

    The income account for a minted Item is copied from the entity's
    AccountingCategory's generic fallback Item — income-account
    configuration lives in QBO: the bookkeeper sets it once, on the
    per-category Items, and konbini never stores income accounts.
    """

    @staticmethod
    def ensure_item(entity, client):
        """Return the QBO Item id for entity, minting/adopting if needed.

        Returns '' when the entity's category has no qbo_item_id mapped
        (no income account to copy) — the caller falls back to the
        category Item / no ItemRef. On QBO's duplicate-name error the
        existing Item is adopted by name.
        """
        if entity.qbo_id:
            return entity.qbo_id

        from apps.inventory.models import InventoryItem
        if isinstance(entity, InventoryItem):
            category = entity.accounting_category
            name = entity.code
            qbo_type = 'NonInventory'
        else:  # ServiceItem
            category = entity.effective_accounting_category
            name = entity.template_name
            qbo_type = 'Service'

        if not category or not category.qbo_item_id:
            return ''

        from quickbooks.objects.item import Item
        generic = Item.get(category.qbo_item_id, qb=client)

        item = Item()
        item.Name = name
        item.Type = qbo_type
        item.IncomeAccountRef = generic.IncomeAccountRef
        try:
            item.save(qb=client)
            qbo_id = str(item.Id)
        except Exception as e:
            if not _is_duplicate_name_error(e):
                raise
            qbo_id = _adopt_id_by_name(Item, client, Name=name)
            if not qbo_id:
                raise

        entity.qbo_id = qbo_id
        entity.save(update_fields=['qbo_id'])
        return qbo_id


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
    """Owns the `qbo_payment_accounts` Configuration lookup, used by the
    expense/reimbursement Purchase push."""

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
    """Pushes Minibini expenses and reimbursement batches to QBO."""

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
        """Delete the QBO Purchase for this batch. Raises on failure so the caller refuses the local delete."""
        from quickbooks.objects.purchase import Purchase
        if not batch.qbo_id:
            return
        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')
        QBOService.delete_and_log(
            Purchase, batch.qbo_id, client,
            entity_type='reimbursement', qbo_entity_type='Purchase', entity_id=batch.pk,
        )


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


class QBOInboundPollingService:
    """Single entry point for all QBO -> Minibini polling. Sweeps every inbound
    type (invoice payments; future: Job-P&L actuals, CDC)."""

    @staticmethod
    def poll_all():
        return {
            'invoices': QBOPaymentPollingService.poll_all(),
        }


class QBOSyncFailureService:
    """Returns a unified list of all sync-failed records across the three
    money-push entity types: company Expense and Reimbursement."""

    @staticmethod
    def list_failures():
        """Return a list of dicts, one per sync_failed record.

        Each dict: {entity_type, id, label, amount, qbo_pending_op, qbo_sync_error}.

        Only company-paid Expenses are included (personal ones never carry their
        own QBO failure — their Reimbursement batch does).
        """
        from apps.expenses.models import Expense, Reimbursement

        results = []

        for e in Expense.objects.filter(
            qbo_sync_status=Expense.SYNC_FAILED,
            payment_method=Expense.PAYMENT_METHOD_COMPANY,
        ).select_related('entered_by'):
            results.append({
                'entity_type': 'expense',
                'id': e.pk,
                'label': f"Expense #{e.pk}: {e.description or '—'}",
                'amount': str(e.amount),
                'qbo_pending_op': e.qbo_pending_op,
                'qbo_sync_error': e.qbo_sync_error,
                'retry_url': f'/api/expenses/{e.pk}/retry-sync/',
            })

        for b in Reimbursement.objects.filter(
            qbo_sync_status=Reimbursement.SYNC_FAILED,
        ).select_related('purchased_by'):
            results.append({
                'entity_type': 'reimbursement',
                'id': b.pk,
                'label': f"Reimbursement batch #{b.pk}: {b.purchased_by.username}",
                'amount': str(b.total),
                'qbo_pending_op': b.qbo_pending_op,
                'qbo_sync_error': b.qbo_sync_error,
                'retry_url': f'/api/reimbursements/{b.pk}/retry-sync/',
            })

        return results


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
            record.mark_failed(e, record.OP_CREATE)
            return None

    @staticmethod
    def run_update(record, update_callable):
        """update_callable() updates the existing QBO object (qbo_id unchanged)."""
        try:
            update_callable()
            record.mark_synced(record.qbo_id)
        except Exception as e:  # noqa: BLE001
            logger.exception('QBO update sync failed for %r', record)
            record.mark_failed(e, record.OP_UPDATE)

    @staticmethod
    def run_delete(record, delete_callable):
        """delete_callable() performs the QBO delete.

        On success: returns None.
        On failure: marks the record sync_failed AND re-raises — the re-raise is
        deliberate so the caller can abort the local delete and retain the row.
        This is the key difference from run_create/run_update, which swallow.
        """
        try:
            delete_callable()
        except Exception as e:
            record.mark_failed(e, record.OP_DELETE)
            raise

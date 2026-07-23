"""QBO setup-time data import: snapshot pull, suggestion diffs, commits.

Spec: docs/plans/qbo-setup-import-spec.md Parts 4–5. The snapshot is one
JSON blob in Configuration; suggestion panels diff it live against the
database; per-area dismissal flags short-circuit that work entirely.
"""
import json

from django.db import transaction
from django.utils import timezone

from apps.core.models import Configuration

_PAGE = 1000


def _all(sdk_class, client, **kwargs):
    """Fetch every active record of an SDK type, paginating until a short
    page. python-quickbooks caps result pages; start_position is 1-based."""
    results = []
    position = 1
    while True:
        page = sdk_class.filter(
            start_position=str(position), max_results=str(_PAGE),
            qb=client, **kwargs)
        results.extend(page)
        if len(page) < _PAGE:
            return results
        position += _PAGE


def _ref_value(ref):
    return str(ref.value) if ref is not None and getattr(ref, 'value', None) else ''


def _ref_name(ref):
    return str(ref.name) if ref is not None and getattr(ref, 'name', None) else ''


class QBOSnapshotService:
    KEY = 'qbo_import_snapshot'

    @staticmethod
    def pull(client):
        """Fetch items, accounts, customers, vendors, and terms in one
        sweep; store as the shared snapshot; return it."""
        from quickbooks.objects.account import Account
        from quickbooks.objects.customer import Customer
        from quickbooks.objects.item import Item
        from quickbooks.objects.term import Term
        from quickbooks.objects.vendor import Vendor

        items = []
        for i in _all(Item, client, Active=True):
            if getattr(i, 'Type', '') not in ('Service', 'NonInventory',
                                              'Inventory'):
                continue  # Category grouping nodes etc. — not sellable
            items.append({
                'qbo_id': str(i.Id),
                'name': str(i.Name or ''),
                'type': str(i.Type),
                'unit_price': str(i.UnitPrice or '0'),
                'description': str(getattr(i, 'Description', '') or ''),
                'income_account_id': _ref_value(i.IncomeAccountRef),
                'income_account_name': _ref_name(i.IncomeAccountRef),
                'expense_account_id': _ref_value(
                    getattr(i, 'ExpenseAccountRef', None)),
                'purchase_cost': str(getattr(i, 'PurchaseCost', 0) or '0'),
                'taxable': bool(getattr(i, 'Taxable', False)),
            })

        def account_rows(accounts):
            return [{'qbo_id': str(a.Id), 'name': str(a.Name),
                     'type': str(a.AccountType)} for a in accounts]

        income_accounts = account_rows(
            Account.filter(AccountType='Income', Active=True, qb=client))
        expense_accounts = account_rows(
            list(Account.filter(AccountType='Expense', Active=True, qb=client))
            + list(Account.filter(AccountType='Cost of Goods Sold',
                                  Active=True, qb=client)))

        customers = []
        for c in _all(Customer, client, Active=True):
            customers.append({
                'qbo_id': str(c.Id),
                'display_name': str(getattr(c, 'DisplayName', '') or ''),
                'company_name': str(getattr(c, 'CompanyName', '') or ''),
                'given_name': str(getattr(c, 'GivenName', '') or ''),
                'family_name': str(getattr(c, 'FamilyName', '') or ''),
                'email': str(getattr(getattr(c, 'PrimaryEmailAddr', None),
                                     'Address', '') or ''),
                'phone': str(getattr(getattr(c, 'PrimaryPhone', None),
                                     'FreeFormNumber', '') or ''),
                'term_qbo_id': _ref_value(getattr(c, 'SalesTermRef', None)),
            })

        vendors = []
        for v in _all(Vendor, client, Active=True):
            vendors.append({
                'qbo_id': str(v.Id),
                'display_name': str(getattr(v, 'DisplayName', '') or ''),
                'company_name': str(getattr(v, 'CompanyName', '') or ''),
                'email': str(getattr(getattr(v, 'PrimaryEmailAddr', None),
                                     'Address', '') or ''),
                'phone': str(getattr(getattr(v, 'PrimaryPhone', None),
                                     'FreeFormNumber', '') or ''),
            })

        terms = [{'qbo_id': str(t.Id), 'name': str(t.Name or ''),
                  'due_days': int(getattr(t, 'DueDays', 0) or 0)}
                 for t in _all(Term, client, Active=True)]

        snapshot = {
            'version': 1,
            'fetched_at': timezone.now().isoformat(),
            'items': items,
            'income_accounts': income_accounts,
            'expense_accounts': expense_accounts,
            'customers': customers,
            'vendors': vendors,
            'terms': terms,
        }
        Configuration.objects.update_or_create(
            key=QBOSnapshotService.KEY,
            defaults={'value': json.dumps(snapshot)})
        return snapshot

    @staticmethod
    def load():
        """Parsed snapshot, or None when never pulled / unparsable."""
        try:
            raw = Configuration.objects.get(key=QBOSnapshotService.KEY).value
            return json.loads(raw)
        except Configuration.DoesNotExist:
            return None
        except (TypeError, ValueError):
            return None


class QBOImportState:
    """Sticky per-area dismissal flags for the suggestion panels.

    Dismissal is total for its area (panel gone; only the pull button
    remains) and survives pulls made from OTHER areas — only the area's
    own pull clears its flag. Spec Part 4."""

    DISMISS_KEY = 'qbo_import_dismissed'
    AREAS = ('categories', 'schemes', 'catalog', 'contacts')

    @staticmethod
    def dismissed():
        try:
            raw = Configuration.objects.get(
                key=QBOImportState.DISMISS_KEY).value
            return json.loads(raw) or {}
        except Configuration.DoesNotExist:
            return {}
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _write(flags):
        Configuration.objects.update_or_create(
            key=QBOImportState.DISMISS_KEY,
            defaults={'value': json.dumps(flags)})

    @staticmethod
    def _check(area):
        if area not in QBOImportState.AREAS:
            raise ValueError(f'Unknown import area: {area!r}')

    @staticmethod
    def dismiss(area):
        QBOImportState._check(area)
        flags = QBOImportState.dismissed()
        flags[area] = True
        QBOImportState._write(flags)

    @staticmethod
    def undismiss(area):
        QBOImportState._check(area)
        flags = QBOImportState.dismissed()
        flags.pop(area, None)
        QBOImportState._write(flags)


class QBOImportSummary:
    """Post-pull diff counts per kind (already-imported matched by the
    qbo_id-family fields)."""

    @staticmethod
    def diff_summary():
        from apps.contacts.models import Business, Contact, PaymentTerms
        from apps.estimates.models import ServiceItem
        from apps.inventory.models import InventoryItem

        snapshot = QBOSnapshotService.load()
        if snapshot is None:
            return {}

        def count(rows, imported_ids):
            imported = sum(1 for r in rows if r['qbo_id'] in imported_ids)
            return {'total': len(rows), 'imported': imported,
                    'new': len(rows) - imported}

        item_ids = (set(InventoryItem.objects.exclude(qbo_id='')
                        .values_list('qbo_id', flat=True))
                    | set(ServiceItem.objects.exclude(qbo_id='')
                          .values_list('qbo_id', flat=True)))
        customer_ids = (set(Business.objects.exclude(qbo_customer_id=None)
                            .values_list('qbo_customer_id', flat=True))
                        | set(Contact.objects.exclude(qbo_customer_id=None)
                              .values_list('qbo_customer_id', flat=True)))
        vendor_ids = set(Business.objects.exclude(qbo_vendor_id=None)
                         .values_list('qbo_vendor_id', flat=True))
        term_ids = set(PaymentTerms.objects.exclude(qbo_id='')
                       .values_list('qbo_id', flat=True))

        return {
            'items': count(snapshot['items'], item_ids),
            'customers': count(snapshot['customers'], customer_ids),
            'vendors': count(snapshot['vendors'], vendor_ids),
            'terms': count(snapshot['terms'], term_ids),
        }

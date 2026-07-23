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


def _slug_code(name, taken):
    """Short uppercase code from a name ('Service Income' → 'SI'), padded
    from the name when too short, uniquified against `taken`."""
    initials = ''.join(w[0] for w in name.split() if w and w[0].isalnum())
    base = (initials or name[:3]).upper()[:10] or 'CAT'
    if len(base) < 2:
        base = (name.replace(' ', '')[:3].upper() or 'CAT')
    code = base
    n = 2
    while code in taken:
        code = f'{base}{n}'
        n += 1
    return code


def _category_by_income_account(snapshot):
    """{income_account_id: AccountingCategory pk} via each committed kAC's
    fallback Item (the item's income account identifies the cluster)."""
    from apps.core.models import AccountingCategory
    item_income = {i['qbo_id']: i['income_account_id']
                   for i in snapshot['items']}
    mapping = {}
    for pk, item_id in AccountingCategory.objects.exclude(
            qbo_item_id='').values_list('pk', 'qbo_item_id'):
        account = item_income.get(item_id)
        if account:
            mapping[account] = pk
    return mapping


def _load_scheme_map():
    """{qbo_item_id: RateScheme pk} persisted at scheme commit — the durable
    record of which QBO service items have already been imported as schemes."""
    try:
        return json.loads(Configuration.objects.get(
            key='qbo_import_scheme_map').value)
    except Configuration.DoesNotExist:
        return {}
    except (TypeError, ValueError):
        return {}


class QBOSuggestionService:
    """Live diffs of the snapshot against the database, per panel area.

    Short-circuits BEFORE any snapshot parse when the area is dismissed."""

    @staticmethod
    def suggestions(area):
        QBOImportState._check(area)
        if QBOImportState.dismissed().get(area):
            return {'dismissed': True, 'fetched_at': None, 'rows': []}
        snapshot = QBOSnapshotService.load()
        if snapshot is None:
            return {'dismissed': False, 'fetched_at': None, 'rows': []}
        rows = getattr(QBOSuggestionService, f'_{area}')(snapshot)
        out = {'dismissed': False, 'fetched_at': snapshot['fetched_at'],
               'rows': rows}
        if area == 'categories':
            out['expense_accounts'] = snapshot['expense_accounts']
        elif area in ('schemes', 'catalog'):
            from apps.core.models import AccountingCategory
            from apps.jobs.models import RateScheme
            out['category_options'] = list(
                AccountingCategory.objects.filter(is_active=True)
                .values('pk', 'name'))
            if area == 'catalog':
                out['scheme_options'] = list(
                    RateScheme.objects.filter(replaced_by__isnull=True)
                    .values('pk', 'name'))
        return out

    # ---- categories ----

    @staticmethod
    def _categories(snapshot):
        from apps.core.models import AccountingCategory
        existing_codes = set(
            AccountingCategory.objects.values_list('code', flat=True))
        existing_item_ids = set(
            AccountingCategory.objects.exclude(qbo_item_id='')
            .values_list('qbo_item_id', flat=True))

        clusters = {}
        for item in snapshot['items']:
            account = item['income_account_id']
            if not account:
                continue
            clusters.setdefault(account, []).append(item)

        account_names = {a['qbo_id']: a['name']
                         for a in snapshot['income_accounts']}
        rows = []
        taken = set(existing_codes)
        all_accounts = list(dict.fromkeys(
            list(clusters.keys())
            + [a['qbo_id'] for a in snapshot['income_accounts']]))
        for account in all_accounts:
            members = clusters.get(account, [])
            name = account_names.get(
                account,
                members[0]['income_account_name'] if members else account)
            code = _slug_code(name, taken)
            taken.add(code)
            taxable_votes = [m['taxable'] for m in members]
            expense_votes = [m['expense_account_id'] for m in members
                             if m['expense_account_id']]
            imported = any(m['qbo_id'] in existing_item_ids for m in members)
            rows.append({
                'income_account': {'qbo_id': account, 'name': name},
                'member_count': len(members),
                'suggested': {
                    'name': name,
                    'code': code,
                    'taxable': (sum(taxable_votes) * 2 >= len(taxable_votes))
                               if taxable_votes else True,
                },
                'fallback_item_options': [
                    {'qbo_id': m['qbo_id'], 'name': m['name']}
                    for m in members],
                'fallback_item_default': members[0]['qbo_id'] if members else '',
                'expense_account_default': (
                    max(set(expense_votes), key=expense_votes.count)
                    if expense_votes else ''),
                'state': 'imported' if imported else 'new',
            })
        return rows

    # ---- schemes ----

    @staticmethod
    def _schemes(snapshot):
        from apps.estimates.models import ServiceItem
        from apps.jobs.models import RateScheme
        imported_ids = set(ServiceItem.objects.exclude(qbo_id='')
                           .values_list('qbo_id', flat=True))
        # A mapped item whose scheme still exists (even superseded) was
        # imported by a scheme commit — ServiceItems only appear later, at
        # the catalog commit, so the map is the authoritative marker here.
        scheme_pks = set(RateScheme.objects.values_list('pk', flat=True))
        imported_ids |= {qid for qid, pk in _load_scheme_map().items()
                         if pk in scheme_pks}
        category_map = _category_by_income_account(snapshot)
        rows = []
        for item in snapshot['items']:
            if item['type'] != 'Service':
                continue
            rows.append({
                'qbo_item_id': item['qbo_id'],
                'name': item['name'],
                'rate': item['unit_price'],
                'algorithm_default': 'entered_qty',
                'unit_default': 'ea',
                'category': category_map.get(item['income_account_id']),
                'price_group': item['unit_price'],
                'state': ('imported' if item['qbo_id'] in imported_ids
                          else 'new'),
            })
        return rows

    # ---- catalog ----

    @staticmethod
    def _catalog(snapshot):
        from decimal import Decimal, InvalidOperation

        from apps.estimates.models import ServiceItem
        from apps.inventory.models import InventoryItem

        def dec(value):
            try:
                return Decimal(str(value))
            except (InvalidOperation, TypeError):
                return Decimal('0')

        from apps.jobs.models import RateScheme
        scheme_by_name = dict(
            RateScheme.objects.filter(replaced_by__isnull=True)
            .values_list('name', 'pk'))
        scheme_map = _load_scheme_map()
        live = set(RateScheme.objects.filter(replaced_by__isnull=True)
                   .values_list('pk', flat=True))
        category_map = _category_by_income_account(snapshot)
        inv_by_qbo = {i.qbo_id: i for i in
                      InventoryItem.objects.exclude(qbo_id='')}
        svc_by_qbo = {s.qbo_id: s for s in
                      ServiceItem.objects.exclude(qbo_id='')
                      .select_related('rate_scheme')}
        taken_codes = set(
            InventoryItem.objects.values_list('code', flat=True))

        rows = []
        for item in snapshot['items']:
            if item['type'] == 'Service':
                existing = svc_by_qbo.get(item['qbo_id'])
                if existing is None:
                    state = 'new'
                elif (dec(existing.rate_scheme.rate) != dec(item['unit_price'])
                        or existing.template_name != item['name']):
                    state = 'changed'
                else:
                    state = 'imported'
                rows.append({
                    'kind': 'service',
                    'qbo_id': item['qbo_id'],
                    'name': item['name'],
                    'description': item['description'],
                    'rate': item['unit_price'],
                    'rate_scheme_default': (
                        scheme_map.get(item['qbo_id'])
                        if scheme_map.get(item['qbo_id']) in live
                        else scheme_by_name.get(item['name'])),
                    'state': state,
                })
            else:  # NonInventory + Inventory → konbini inventory items
                existing = inv_by_qbo.get(item['qbo_id'])
                if existing is None:
                    state = 'new'
                    code = item['name']
                    n = 2
                    while code in taken_codes:
                        code = f"{item['name']}-{n}"
                        n += 1
                    taken_codes.add(code)
                elif (dec(existing.selling_price) != dec(item['unit_price'])
                        or (existing.description or '') != item['description']):
                    state = 'changed'
                    code = existing.code
                else:
                    state = 'imported'
                    code = existing.code
                rows.append({
                    'kind': 'inventory',
                    'qbo_id': item['qbo_id'],
                    'code_suggestion': code,
                    'description': item['description'] or item['name'],
                    'selling_price': item['unit_price'],
                    'purchase_price': item['purchase_cost'],
                    'category': category_map.get(item['income_account_id']),
                    'state': state,
                })
        return rows

    # ---- contacts (customers / vendors / terms) ----

    @staticmethod
    def _contacts(snapshot):
        from apps.contacts.models import Business, Contact, PaymentTerms

        biz_by_customer = {b.qbo_customer_id: b for b in
                           Business.objects.exclude(qbo_customer_id=None)}
        contact_by_customer = {c.qbo_customer_id: c for c in
                               Contact.objects.exclude(qbo_customer_id=None)}
        biz_by_vendor = {b.qbo_vendor_id: b for b in
                         Business.objects.exclude(qbo_vendor_id=None)}
        term_by_qbo = {t.qbo_id: t for t in
                       PaymentTerms.objects.exclude(qbo_id='')}
        customer_names = {c['display_name'] for c in snapshot['customers']}

        rows = []
        for c in snapshot['customers']:
            business = biz_by_customer.get(c['qbo_id'])
            contact = contact_by_customer.get(c['qbo_id'])
            if business is None and contact is None:
                state = 'new'
            else:
                mirrored_email = (business.default_contact.email
                                  if business and business.default_contact
                                  else contact.email if contact else '')
                changed = (
                    (business and business.business_name != c['company_name']
                     and c['company_name'])
                    or (mirrored_email or '') != c['email'])
                state = 'changed' if changed else 'imported'
            rows.append({'kind': 'customer', 'state': state, **c})
        for v in snapshot['vendors']:
            existing = biz_by_vendor.get(v['qbo_id'])
            if existing is None:
                state = 'new'
            else:
                state = ('changed'
                         if existing.business_name != v['display_name']
                         and v['company_name'] else 'imported')
            rows.append({'kind': 'vendor', 'state': state,
                         'merge_hint': v['display_name'] in customer_names,
                         **v})
        for t in snapshot['terms']:
            existing = term_by_qbo.get(t['qbo_id'])
            if existing is None:
                state = 'new'
            elif (existing.name != t['name']
                  or (existing.days or 0) != t['due_days']):
                state = 'changed'
            else:
                state = 'imported'
            rows.append({'kind': 'term', 'state': state, **t})
        return rows


class QBOImportCommitService:
    """Applies user-confirmed suggestion rows. Each commit is atomic for
    its kind; after a commit, if the area's diff is empty the area is
    auto-dismissed (finished == dismissed)."""

    @staticmethod
    def _auto_dismiss(area):
        if not QBOSuggestionService.suggestions(area)['rows']:
            QBOImportState.dismiss(area)
        else:
            remaining = QBOSuggestionService.suggestions(area)['rows']
            if all(r.get('state') == 'imported' for r in remaining):
                QBOImportState.dismiss(area)

    @staticmethod
    def commit_categories(rows):
        from django.core.exceptions import ValidationError

        from apps.core.models import AccountingCategory
        created = []
        with transaction.atomic():
            for row in rows:
                category = AccountingCategory(
                    name=row['name'],
                    code=row['code'],
                    taxable=bool(row.get('taxable', True)),
                    qbo_item_id=row.get('qbo_item_id', '') or '',
                    qbo_expense_account_id=(
                        row.get('qbo_expense_account_id', '') or ''),
                )
                try:
                    category.validate_unique()
                except ValidationError:
                    raise ValidationError(
                        {'code': [f"Duplicate category code: {row['code']}"]})
                category.save()
                created.append(category)
        QBOImportCommitService._auto_dismiss('categories')
        return created

    @staticmethod
    def commit_schemes(rows):
        """One RateScheme per row, except rows sharing a collapse_group,
        which share ONE scheme (first row wins the name/rate/etc.).
        Returns {qbo_item_id: scheme_pk} for the catalog panel handoff."""
        from decimal import Decimal

        from apps.jobs.models import RateScheme

        from django.core.exceptions import ValidationError

        missing = [row.get('name') or row.get('qbo_item_id')
                   for row in rows if not row.get('accounting_category')]
        if missing:
            raise ValidationError({'accounting_category': [
                'Every scheme needs a category. Missing on: '
                + ', '.join(str(m) for m in missing)
                + '. Commit your accounting categories first if the '
                  'pulldowns are empty.']})

        from apps.core.models import AccountingCategory
        from apps.core.services import ConfigurationService
        from apps.estimates.models import ServiceItem

        stored_map = _load_scheme_map()

        def current(pk):
            """The live end of pk's supersession chain, or None if gone."""
            try:
                scheme = RateScheme.objects.get(pk=pk)
            except RateScheme.DoesNotExist:
                return None
            while scheme.replaced_by_id:
                scheme = scheme.replaced_by
            return scheme

        # Rows whose item was committed before update their existing scheme;
        # only genuinely new rows insert — so a stale panel or a re-apply
        # can never duplicate.
        targets = {row['qbo_item_id']: current(stored_map[row['qbo_item_id']])
                   if row['qbo_item_id'] in stored_map else None
                   for row in rows}
        target_pks = {s.pk for s in targets.values() if s is not None}
        taken_names = set(RateScheme.objects.exclude(pk__in=target_pks)
                          .values_list('name', flat=True))
        collisions = []
        for row in rows:
            if targets[row['qbo_item_id']] is not None:
                continue
            if row.get('collapse_group'):     # group members share one row
                continue
            if row['name'] in taken_names:
                collisions.append(row['name'])
            taken_names.add(row['name'])
        if collisions:
            raise ValidationError({'name': [
                'A rate scheme with this name already exists: '
                + ', '.join(collisions)
                + '. Edit it in the scheme manager below, or pick a '
                  'different name.']})

        mapping = {}
        group_schemes = {}
        handled = {}                # original pk → scheme updated this call
        with transaction.atomic():
            for row in rows:
                group = row.get('collapse_group') or None
                target = targets[row['qbo_item_id']]
                if target is not None:
                    if target.pk in handled:
                        target = handled[target.pk]
                    else:
                        original_pk = target.pk
                        fields = {
                            'name': row['name'],
                            'algorithm': row['algorithm'],
                            'rate': Decimal(str(row['rate'] or '0')),
                            'unit_label': row['unit_label'],
                            'accounting_category_id': row['accounting_category'],
                        }
                        changed = any(getattr(target, f) != v
                                      for f, v in fields.items())
                        if changed and target.is_referenced():
                            # Frozen once referenced: new pricing is a new
                            # version. supersede() does NOT repoint catalog
                            # users, so repoint ServiceItems explicitly.
                            new = ConfigurationService.supersede_rate_scheme(
                                target,
                                name=row['name'],
                                algorithm=row['algorithm'],
                                rate=fields['rate'],
                                unit_label=row['unit_label'],
                                accounting_category=AccountingCategory.objects
                                    .get(pk=row['accounting_category']),
                            )
                            for svc in ServiceItem.objects.filter(
                                    rate_scheme=target):
                                svc.rate_scheme = new
                                svc.save()
                            target = new
                        elif changed:
                            ConfigurationService.update_rate_scheme(
                                target, **fields)
                        handled[original_pk] = target
                    mapping[row['qbo_item_id']] = target.pk
                    if group and group not in group_schemes:
                        group_schemes[group] = target
                    continue
                if group and group in group_schemes:
                    mapping[row['qbo_item_id']] = group_schemes[group].pk
                    continue
                scheme = RateScheme.objects.create(
                    name=row['name'],
                    algorithm=row['algorithm'],
                    rate=Decimal(str(row['rate'] or '0')),
                    unit_label=row['unit_label'],
                    accounting_category_id=row['accounting_category'],
                )
                if group:
                    group_schemes[group] = scheme
                mapping[row['qbo_item_id']] = scheme.pk
            # Persist the linkage so the catalog panel can bind services to
            # their schemes reliably (name-matching breaks for collapsed
            # groups and renames), and so re-applies update instead of
            # duplicating.
            stored_map.update(mapping)
            Configuration.objects.update_or_create(
                key='qbo_import_scheme_map',
                defaults={'value': json.dumps(stored_map)})
        QBOImportCommitService._auto_dismiss('schemes')
        return mapping


def _catalog_commit_rows(rows):
    """Apply catalog rows; returns (created, updated)."""
    from decimal import Decimal

    from apps.estimates.models import ServiceItem
    from apps.inventory.models import InventoryItem

    from django.core.exceptions import ValidationError

    bad_inventory = [row.get('code') or row['qbo_id'] for row in rows
                     if row['kind'] == 'inventory'
                     and row['action'] == 'create'
                     and not row.get('accounting_category')]
    bad_service = [row.get('name') or row['qbo_id'] for row in rows
                   if row['kind'] == 'service'
                   and row['action'] == 'create'
                   and not row.get('rate_scheme')]
    errors = {}
    if bad_inventory:
        errors['accounting_category'] = [
            'Every inventory item needs a category. Missing on: '
            + ', '.join(str(m) for m in bad_inventory)]
    if bad_service:
        errors['rate_scheme'] = [
            'Every service needs a rate scheme. Missing on: '
            + ', '.join(str(m) for m in bad_service)]
    if errors:
        raise ValidationError(errors)

    created = updated = 0
    for row in rows:
        if row['kind'] == 'inventory':
            if row['action'] == 'create':
                InventoryItem.objects.create(
                    code=row['code'],
                    description=row.get('description', ''),
                    selling_price=Decimal(str(row.get('selling_price') or '0')),
                    purchase_price=Decimal(str(row.get('purchase_price') or '0')),
                    units=row.get('units') or 'none',
                    accounting_category_id=row['accounting_category'],
                    qbo_id=row['qbo_id'],
                )
                created += 1
            else:
                item = InventoryItem.objects.get(qbo_id=row['qbo_id'])
                item.description = row.get('description', item.description)
                item.selling_price = Decimal(
                    str(row.get('selling_price') or item.selling_price))
                item.purchase_price = Decimal(
                    str(row.get('purchase_price') or item.purchase_price))
                item.save()
                updated += 1
        else:  # service
            if row['action'] == 'create':
                ServiceItem.objects.create(
                    template_name=row['name'],
                    description=row.get('description', ''),
                    rate_scheme_id=row['rate_scheme'],
                    qbo_id=row['qbo_id'],
                )
                created += 1
            else:
                from apps.core.services import ConfigurationService
                svc = (ServiceItem.objects
                       .select_related('rate_scheme')
                       .get(qbo_id=row['qbo_id']))
                new_rate = Decimal(str(row.get('rate') or '0'))
                if (row.get('rate') is not None
                        and svc.rate_scheme.rate != new_rate):
                    # Pricing integrity: price changes supersede, never a
                    # bare rate edit. supersede() does NOT repoint catalog
                    # users, so repoint the ServiceItem explicitly.
                    new_scheme = ConfigurationService.supersede_rate_scheme(
                        svc.rate_scheme, rate=new_rate)
                    svc.rate_scheme = new_scheme
                if row.get('name'):
                    svc.template_name = row['name']
                svc.save()
                updated += 1
    return created, updated


# QBOImportCommitService extensions (catalog + contacts) — attached here to
# keep the class definition above focused; staticmethods assigned below.

def _commit_catalog(rows):
    with transaction.atomic():
        created, updated = _catalog_commit_rows(rows)
    QBOImportCommitService._auto_dismiss('catalog')
    return {'created': created, 'updated': updated}


def _commit_contacts(payload):
    """Terms first, then customers, then vendors (merge-by-name)."""
    from apps.contacts.models import Business, Contact, PaymentTerms

    counts = {'terms': {'created': 0, 'updated': 0},
              'customers': {'created': 0, 'updated': 0},
              'vendors': {'created': 0, 'updated': 0}}
    with transaction.atomic():
        for row in payload.get('terms') or []:
            if row['action'] == 'create':
                PaymentTerms.objects.create(
                    name=row['name'], days=row.get('due_days'),
                    qbo_id=row['qbo_id'])
                counts['terms']['created'] += 1
            else:
                term = PaymentTerms.objects.get(qbo_id=row['qbo_id'])
                term.name = row['name']
                term.days = row.get('due_days')
                term.save()
                counts['terms']['updated'] += 1

        term_by_qbo = {t.qbo_id: t for t in
                       PaymentTerms.objects.exclude(qbo_id='')}

        for row in payload.get('customers') or []:
            term = term_by_qbo.get(row.get('term_qbo_id') or '')
            if row['action'] == 'create':
                if row.get('company_name'):
                    contact = Contact.objects.create(
                        first_name=row.get('given_name') or row['display_name'],
                        last_name=row.get('family_name') or '',
                        email=row.get('email') or '',
                        mobile_number=row.get('phone') or '',
                    )
                    business = Business.objects.create(
                        business_name=row['company_name'],
                        business_phone=row.get('phone') or '',
                        default_contact=contact,
                        qbo_customer_id=row['qbo_id'],
                        terms=term,
                    )
                    Contact.objects.filter(pk=contact.pk).update(
                        business=business)
                else:
                    Contact.objects.create(
                        first_name=row.get('given_name') or row['display_name'],
                        last_name=row.get('family_name') or '',
                        email=row.get('email') or '',
                        mobile_number=row.get('phone') or '',
                        qbo_customer_id=row['qbo_id'],
                    )
                counts['customers']['created'] += 1
            else:
                business = Business.objects.filter(
                    qbo_customer_id=row['qbo_id']).first()
                if business is not None:
                    if row.get('company_name'):
                        business.business_name = row['company_name']
                    if term is not None:
                        business.terms = term
                    business.save()
                    contact = business.default_contact
                else:
                    contact = Contact.objects.get(
                        qbo_customer_id=row['qbo_id'])
                if contact is not None:
                    contact.first_name = (row.get('given_name')
                                          or contact.first_name)
                    contact.last_name = (row.get('family_name')
                                         or contact.last_name)
                    contact.email = row.get('email') or ''
                    if row.get('phone'):
                        contact.mobile_number = row['phone']
                    contact.save()
                counts['customers']['updated'] += 1

        for row in payload.get('vendors') or []:
            name = row.get('company_name') or row['display_name']
            if row['action'] == 'create':
                existing = Business.objects.filter(
                    business_name__iexact=name).first()
                if existing is not None:
                    # Same-named business (usually a customer) — one
                    # Business plays both roles; adopt, don't duplicate.
                    existing.qbo_vendor_id = row['qbo_id']
                    existing.save(update_fields=['qbo_vendor_id'])
                else:
                    contact = Contact.objects.create(
                        first_name=name, last_name='',
                        email=row.get('email') or '',
                        mobile_number=row.get('phone') or '',
                    )
                    business = Business.objects.create(
                        business_name=name,
                        business_phone=row.get('phone') or '',
                        default_contact=contact,
                        qbo_vendor_id=row['qbo_id'],
                    )
                    Contact.objects.filter(pk=contact.pk).update(
                        business=business)
                counts['vendors']['created'] += 1
            else:
                business = Business.objects.get(qbo_vendor_id=row['qbo_id'])
                if row.get('company_name'):
                    business.business_name = row['company_name']
                business.save()
                counts['vendors']['updated'] += 1
    QBOImportCommitService._auto_dismiss('contacts')
    return counts


QBOImportCommitService.commit_catalog = staticmethod(_commit_catalog)
QBOImportCommitService.commit_contacts = staticmethod(_commit_contacts)

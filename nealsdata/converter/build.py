"""Base fixture builders for the Neal's data converter.

Each builder function takes a NealsDataConverter instance as its first
argument and appends fixture records to c.fixture_data via c.add_fixture().
"""
import json

from nealsdata.converter import parsing as P


def build_users(c):
    """Emit core.user fixtures: a system user and staff users.

    Sets c.default_user_pk to the pk of the lowest-permission staff user.
    """
    # System user — inactive, no usable password
    system_pk = c.next_pk('core.user')
    c.add_fixture('core.user', system_pk, {
        'username': 'system',
        'password': '!',
        'first_name': '',
        'last_name': '',
        'email': '',
        'is_active': False,
        'is_staff': False,
        'is_superuser': False,
    })

    # Primary staff user (admin)
    admin_pk = c.next_pk('core.user')
    c.add_fixture('core.user', admin_pk, {
        'username': 'neal',
        'password': '!',
        'first_name': 'Neal',
        'last_name': '',
        'email': '',
        'is_active': True,
        'is_staff': True,
        'is_superuser': True,
    })

    # Default (lowest-permission) staff user — used as the fallback creator
    # for converted records that have no more specific user assignment.
    default_pk = c.next_pk('core.user')
    c.add_fixture('core.user', default_pk, {
        'username': 'staff',
        'password': '!',
        'first_name': 'Staff',
        'last_name': 'User',
        'email': '',
        'is_active': True,
        'is_staff': False,
        'is_superuser': False,
    })

    c.default_user_pk = default_pk


def build_configuration(c):
    """Emit core.configuration fixtures for document numbering and app settings.

    Configuration uses the key field as primary key, so pk is the key string.
    """
    entries = [
        ('job_number_sequence',      'J{year}-{counter:04d}'),
        ('job_counter',              '0'),
        ('estimate_number_sequence', 'E{year}-{counter:04d}'),
        ('estimate_counter',         '0'),
        ('invoice_number_sequence',  'INV-{year}-{counter:04d}'),
        ('invoice_counter',          '0'),
        ('po_number_sequence',       'PO-{year}-{counter:04d}'),
        ('po_counter',               '0'),
        ('est_expire_days',          '30'),
        ('email_retention_days',     '30'),
        ('units_list',               json.dumps(['none', 'hours', 'days', 'each', 'ea', 'min', 'sheets', 'sq ft', 'ft', 'yd', 'm', 'lbs', 'kg', 'gal', 'qt', 'L', 'bd ft', 'ln ft'])),
    ]
    for key, value in entries:
        c.add_fixture('core.configuration', key, {'value': value})


def build_accounting_categories(c):
    """Emit core.accountingcategory fixtures for SVC and MAT.

    Sets c.ac_svc_pk and c.ac_mat_pk for use by downstream builders.
    """
    svc_pk = c.next_pk('core.accountingcategory')
    c.add_fixture('core.accountingcategory', svc_pk, {
        'code': 'SVC',
        'name': 'Service',
        'taxable': True,
        'default_description': '',
        'is_active': True,
        'qbo_item_id': '',
        'qbo_expense_account_id': '',
    })
    c.ac_svc_pk = svc_pk

    mat_pk = c.next_pk('core.accountingcategory')
    c.add_fixture('core.accountingcategory', mat_pk, {
        'code': 'MAT',
        'name': 'Materials',
        'taxable': True,
        'default_description': '',
        'is_active': True,
        'qbo_item_id': '',
        'qbo_expense_account_id': '',
    })
    c.ac_mat_pk = mat_pk


def build_contacts_and_businesses(c):
    """Emit contacts.contact and contacts.business fixtures for orgs referenced
    by the spine's estimate rows and bills.

    Only builds one Contact + one Business per referenced org (non-interactive;
    name mismatches between sources are ignored — the Contacts-sheet record is
    used as-is).

    Sets c.org_map (org_name -> {'business': pk, 'contact': pk}) for use by
    downstream builders.
    """
    # --- 1. Collect referenced org names -----------------------------------
    # Index Projects sheet by base_ref of the project Name
    projects_by_base = {}
    for row in c.loader.sheets_data.get('Projects', []):
        name = (row.get('Name') or '').strip()
        if name:
            base = P.base_reference(name)
            projects_by_base[base] = row

    # Index Bills sheet by base_ref of the bill's Project column
    bill_orgs_by_base = {}
    for row in c.loader.sheets_data.get('Bills', []):
        proj = (row.get('Project') or '').strip()
        org = (row.get('Contact Organisation') or '').strip()
        if proj and org:
            base = P.base_reference(proj)
            bill_orgs_by_base.setdefault(base, set()).add(org)

    # Gather referenced org names for each spine entry.
    # Priority: Projects sheet -> Bills -> card name parsed with parse_kanban_name
    referenced_orgs = set()
    for entry in c.spine:
        base = entry['base_ref']

        # From Projects sheet
        proj_row = projects_by_base.get(base)
        if proj_row:
            org = (proj_row.get('Client Organisation') or '').strip()
            if org:
                referenced_orgs.add(org)
                continue  # found it

        # From Bills sheet
        bill_org_set = bill_orgs_by_base.get(base, set())
        if bill_org_set:
            referenced_orgs.update(bill_org_set)
            continue

        # Fall back to card name
        card_name = entry['card'].get('Name', '')
        biz, _person = P.parse_kanban_name(card_name)
        if biz:
            referenced_orgs.add(biz)

    # --- 2. Index Contacts sheet by Organisation ---------------------------
    contacts_by_org = {}
    for row in c.loader.sheets_data.get('Contacts', []):
        org = (row.get('Organisation') or '').strip()
        if org and org not in contacts_by_org:
            contacts_by_org[org] = row

    # --- 3. Emit one Contact + one Business per referenced org -------------
    c.org_map = {}

    for org in sorted(referenced_orgs):  # deterministic order
        contact_row = contacts_by_org.get(org)

        # Determine Contact field values
        if contact_row:
            first_name = str(contact_row.get('First Name') or '').strip()
            last_name = str(contact_row.get('Last Name') or '').strip()
            email = str(contact_row.get('Email') or '').strip()
            work_number = str(contact_row.get('Phone Number') or '').strip()
            mobile_number = str(contact_row.get('Mobile Phone Number') or '').strip()
        else:
            # Synthesize from org name
            first_name, last_name = P.split_name(org)
            email = ''
            work_number = ''
            mobile_number = ''

        # Enforce non-empty first_name / last_name
        if not first_name:
            first_name = '(unknown)'
        if not last_name:
            last_name = '(unknown)'

        # Allocate PKs
        contact_pk = c.next_pk('contacts.contact')
        business_pk = c.next_pk('contacts.business')

        # Apply fallbacks for email and phone
        if not email:
            email = f'noreply+{contact_pk}@example.com'
        if not work_number and not mobile_number:
            work_number = '000-000-0000'

        # Emit Contact fixture
        c.add_fixture('contacts.contact', contact_pk, {
            'first_name': first_name,
            'middle_initial': '',
            'last_name': last_name,
            'email': email,
            'addr1': '',
            'addr2': '',
            'addr3': '',
            'city': '',
            'municipality': '',
            'postal_code': '',
            'country_code': '',
            'mobile_number': mobile_number,
            'work_number': work_number,
            'home_number': '',
            'business': business_pk,
            'qbo_customer_id': None,
        })

        # Emit Business fixture
        c.add_fixture('contacts.business', business_pk, {
            'business_name': org,
            'our_reference_code': f'BUS-{business_pk:04d}',
            'default_contact': contact_pk,
            'business_address': '',
            'business_phone': '',
            'tax_exemption_number': '',
            'website': '',
            'terms': None,
            'tax_multiplier': None,
            'qbo_customer_id': None,
            'qbo_vendor_id': None,
        })

        c.org_map[org] = {'business': business_pk, 'contact': contact_pk}


def build_price_list_items(c):
    """Emit inventory.pricelistitem fixtures from the 'Price List Items' sheet.

    Skips rows with no Code value and deduplicates by code.
    Sets c.pli_map (code -> pk) for use by downstream builders.

    Sheet column headers (positional reference from spec):
      [0] Code, [1] Quantity, [2] Type, [3] Price, [4] Description
    The loader returns header-keyed dicts, so we access by header name.
    """
    rows = c.loader.sheets_data.get('Price List Items', [])
    seen_codes = set()
    c.pli_map = {}

    for row in rows:
        # The sheet uses header names; try both the spec names and common
        # alternatives in case the actual header differs slightly.
        code = (row.get('Code') or row.get('Item Code') or '').strip()
        if not code:
            continue
        if code in seen_codes:
            continue
        seen_codes.add(code)

        description = str(row.get('Description') or '').strip()
        price_raw = row.get('Price') or row.get('Sales Price') or 0
        selling_price = f'{P.parse_decimal(price_raw):.2f}'

        pk = c.next_pk('inventory.pricelistitem')
        c.add_fixture('inventory.pricelistitem', pk, {
            'code': code,
            'description': description,
            'units': 'none',
            'selling_price': selling_price,
            'purchase_price': '0.00',
            'qty_on_hand': '0.00',
            'qty_sold': '0.00',
            'qty_wasted': '0.00',
            'is_active': True,
            'is_inventoried': False,
            'accounting_category': c.ac_mat_pk,
        })
        c.pli_map[code] = pk

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

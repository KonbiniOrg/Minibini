"""Base fixture builders for the Neal's data converter.

Each builder function takes a NealsDataConverter instance as its first
argument and appends fixture records to c.fixture_data via c.add_fixture().
"""
import json
from datetime import datetime

from nealsdata.converter import parsing as P

# Fallback year when no date can be parsed from the source data.
_FALLBACK_YEAR = 2025

# Maps FreeAgent estimate Status values to Minibini job status constants.
_EST_STATUS_TO_JOB_STATUS = {
    'Draft':    'draft',
    'Sent':     'submitted',
    'Approved': 'approved',
    'Rejected': 'rejected',
}


def _revision_index(row):
    """Return the numeric revision index for a container row.

    Used as a key function when selecting the highest-revision estimate row.
    Among rows with equal indices, ``max`` returns the last one seen, which
    preserves the "later sheet row wins on ties" behaviour.
    """
    ref = (row.get('Reference') or '').strip()
    return P.revision_parts(ref)[1]


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


def build_jobs(c):
    """Emit jobs.job fixtures — one per spine entry.

    Sources:
    - Client org: parsed from card['Name'] via parse_kanban_name, resolved
      through c.org_map (built by build_contacts_and_businesses).
    - Primary estimate: highest-revision container row from estimate_rows.
    - Status: mapped from FreeAgent estimate Status field.
    - Job number: J{year}-{counter:04d}, counter resets per year.

    Sets:
    - c.job_map  : base_ref -> job_pk
    - c.jobs     : base_ref -> {'job_pk', 'card', 'estimate_rows', 'primary_ref'}
    - c.discarded_cards : list of notes about skipped spine entries
    """
    # Per-year job counters (keys are int years)
    year_counters = {}

    for entry in c.spine:
        card = entry['card']
        base_ref = entry['base_ref']
        estimate_rows = entry['estimate_rows']

        # --- 1. Resolve contact from card name ----------------------------
        org, _person = P.parse_kanban_name(card.get('Name', ''))
        if not org or org not in c.org_map:
            c.discarded_cards.append(
                f'{base_ref}: org "{org}" not in org_map — skipped'
            )
            continue
        contact_pk = c.org_map[org]['contact']

        # --- 2. Select the primary estimate container row -----------------
        # Container rows have a non-empty Reference value.
        container_rows = [
            r for r in estimate_rows
            if (r.get('Reference') or '').strip()
        ]
        if not container_rows:
            # Fallback: treat all estimate rows as candidates
            container_rows = estimate_rows

        # Pick highest revision index; ties broken by sheet order (last wins).
        # max() returns the last element on ties, preserving sheet order.
        primary_row = max(container_rows, key=_revision_index)

        primary_ref = (primary_row.get('Reference') or '').strip()

        # --- 3. Derive year and job_number --------------------------------
        raw_date = primary_row.get('Date')
        dt = P.to_datetime(raw_date)
        year = dt.year if dt else _FALLBACK_YEAR

        year_counters[year] = year_counters.get(year, 0) + 1
        job_number = f'J{year}-{year_counters[year]:04d}'

        # --- 4. Map estimate status → job status --------------------------
        est_status = (primary_row.get('Status') or '').strip()
        job_status = _EST_STATUS_TO_JOB_STATUS.get(est_status, 'draft')

        # --- 5. Build description from card fields ------------------------
        parts = []
        desc = (card.get('Description') or '').strip()
        notes = (card.get('Notes') or '').strip()
        if desc:
            parts.append(desc)
        if notes:
            parts.append(notes)
        description = '\n'.join(parts)

        # --- 6. Emit fixture ----------------------------------------------
        job_pk = c.next_pk('jobs.job')
        c.add_fixture('jobs.job', job_pk, {
            'job_number':         job_number,
            'name':               (card.get('Name') or '')[:50],
            'contact':            contact_pk,
            'status':             job_status,
            'created_date':       P.format_date(raw_date) or f'{_FALLBACK_YEAR}-01-01',
            'start_date':         None,
            'due_date':           P.format_date(card.get('Due date')),
            'completed_date':     None,
            'customer_po_number': '',
            'description':        description,
        })

        # --- 7. Record maps -----------------------------------------------
        c.job_map[base_ref] = job_pk
        c.jobs[base_ref] = {
            'job_pk':        job_pk,
            'card':          card,
            'estimate_rows': estimate_rows,
            'primary_ref':   primary_ref,
        }


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


# Maps FreeAgent estimate Status values to Minibini estimate status constants.
_EST_STATUS_MAP = {
    'Draft':    'draft',
    'Sent':     'open',
    'Approved': 'accepted',
    'Rejected': 'rejected',
}

# Sentinel: datetime that sorts after all real dates (for unparseable dates).
_DATE_SORT_MAX = datetime.max


def build_estimates(c):
    """Emit estimates.estimate and estimates.estimatelineitem fixtures.

    Scans the full Estimates sheet to recover the container + line-item
    structure (container rows have a non-empty Reference; line-item rows
    immediately follow their container and have an empty Reference).

    Only emits estimates whose base_reference is present in c.job_map.

    For Task 10: populates
        c.line_items  — {est_pk: [{'classification', 'item_type', 'qty',
                                    'units', 'description', 'price',
                                    'line_item_pk'}, ...]}
        c.estimates   — {base_ref: [{'est_pk', 'status', 'created_date',
                                     'version'}, ...]}
    """
    # ------------------------------------------------------------------
    # 1. Walk the Estimates sheet: collect (container_row, [li_rows]) pairs
    # ------------------------------------------------------------------
    all_pairs = []          # list of (container_row_dict, [li_row_dict, ...])
    current_container = None
    current_lis = []

    for row in c.loader.sheets_data.get('Estimates', []):
        ref = (row.get('Reference') or '').strip()

        if ref:
            # Skip repeated-header rows
            if ref == 'Reference':
                continue
            # Save the previous container (if any) before starting a new one
            if current_container is not None:
                all_pairs.append((current_container, current_lis))
            current_container = row
            current_lis = []
        else:
            # Line-item row — belongs to the current container
            if current_container is None:
                # No container seen yet; skip orphaned rows
                continue
            item_type = (row.get('Item Type') or '').strip()
            # Skip repeated column-header rows inside line items
            if item_type == 'Item Type':
                continue
            current_lis.append(row)

    # Flush the last container
    if current_container is not None:
        all_pairs.append((current_container, current_lis))

    # ------------------------------------------------------------------
    # 2. Group pairs by base_reference; keep only those in c.job_map
    # ------------------------------------------------------------------
    groups = {}   # base_ref -> [(sheet_index, container_row, li_rows), ...]
    for idx, (container, lis) in enumerate(all_pairs):
        ref = (container.get('Reference') or '').strip()
        base = P.base_reference(ref)
        if base not in c.job_map:
            continue
        groups.setdefault(base, []).append((idx, container, lis))

    # ------------------------------------------------------------------
    # 3. For each group: sort by Date then sheet order; assign version 1..N
    # ------------------------------------------------------------------
    for base, entries in groups.items():
        job_pk = c.job_map[base]

        # Sort: primary key = parsed date (unparseable → datetime.max),
        #       secondary = original sheet index (preserves order on ties).
        def _sort_key(entry):
            idx, container, _lis = entry
            dt = P.to_datetime(container.get('Date'))
            return (dt if dt is not None else _DATE_SORT_MAX, idx)

        entries.sort(key=_sort_key)

        base_estimates = []   # accumulate for c.estimates[base]

        # Version by chronological order (not suffix index) so versions advance with time.
        for version, (idx, container, lis) in enumerate(entries, start=1):
            raw_date = container.get('Date')
            est_status_raw = (container.get('Status') or '').strip()
            est_status = _EST_STATUS_MAP.get(est_status_raw, 'draft')
            created_date = P.format_date(raw_date) or f'{_FALLBACK_YEAR}-01-01'

            est_pk = c.next_pk('estimates.estimate')
            c.add_fixture('estimates.estimate', est_pk, {
                'job':             job_pk,
                'estimate_number': base,
                'version':         version,
                'parent':          None,
                'status':          est_status,
                'created_date':    created_date,
                'sent_date':       None,
                'expiration_date': None,
                'closed_date':     None,
            })

            base_estimates.append({
                'est_pk':       est_pk,
                'status':       est_status,
                'created_date': created_date,
                'version':      version,
                'base_ref':     base,
            })

            # --------------------------------------------------------------
            # 4. Emit line items; stash classification info for Task 10
            # --------------------------------------------------------------
            c.line_items[est_pk] = []
            line_number = 0

            for li_row in lis:
                item_type = (li_row.get('Item Type') or '').strip()
                description = (li_row.get('Description') or '').strip()
                classification = P.classify_line_item(item_type, description)

                if classification == 'skip':
                    # Comment rows: do not emit a line item, do not stash
                    continue

                line_number += 1
                qty = P.parse_decimal(li_row.get('Quantity'))
                price = P.parse_decimal(li_row.get('Price'))

                # Determine units value
                it_lower = item_type.lower()
                if it_lower == 'hours':
                    units = 'hours'
                elif it_lower == 'days':
                    units = 'days'
                else:
                    units = 'none'

                li_pk = c.next_pk('estimates.estimatelineitem')
                c.add_fixture('estimates.estimatelineitem', li_pk, {
                    'estimate':          est_pk,
                    'source_template':   None,
                    'price_list_item':   None,
                    'line_number':       line_number,
                    'qty':               f'{qty:.2f}',
                    'units':             units,
                    'description':       description,
                    'price':             f'{price:.2f}',
                    'accounting_category': None,
                    'taxable_override':  None,
                    'tax_rate_override': None,
                })

                c.line_items[est_pk].append({
                    'classification': classification,
                    'item_type':      item_type,
                    'qty':            qty,
                    'units':          units,
                    'description':    description,
                    'price':          price,
                    'line_item_pk':   li_pk,
                })

        c.estimates[base] = base_estimates

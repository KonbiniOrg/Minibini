"""Base fixture builders for the Neal's data converter.

Each builder function takes a NealsDataConverter instance as its first
argument and appends fixture records to c.fixture_data via c.add_fixture().
"""
import json
from datetime import datetime
from decimal import Decimal

from nealsdata.converter import parsing as P

# Fallback year when no date can be parsed from the source data.
_FALLBACK_YEAR = 2025

# Maps Kanban 'Stage' values to Minibini job status constants.
_STAGE_TO_JOB_STATUS = {
    'estimate':         'submitted',
    'in progress':      'in_progress',
    'invoice':          'work_complete',
    'done or rejected': 'completed',
}


def _revision_index(row):
    """Return the numeric revision index for a container row.

    Used as a key function when selecting the highest-revision estimate row.
    Among rows with equal indices, ``max`` returns the last one seen, which
    preserves the "later sheet row wins on ties" behaviour.
    """
    ref = (row.get('Reference') or '').strip()
    return P.revision_parts(ref)[1]


def build_seed(c):
    """Emit core.user, core.accountingcategory and jobs.ratescheme records
    verbatim from the nealseed fixture.

    The records are appended to c.fixture_data exactly as they appear in
    nealseed (user records there are written without explicit pks; Django
    assigns them on load). Indexes the seed data for downstream builders:
      - c.ac_by_code / c.ac_svc_pk / c.ac_mat_pk
      - c.scheme_by_name
    Also advances the jobs.ratescheme pk counter past the seeded schemes so
    any derived (cloned) scheme gets a fresh pk.
    """
    from nealsdata.converter.loaders import load_seed_records

    records = load_seed_records(c.seed_path)
    max_rs_pk = 0
    for rec in records:
        c.fixture_data.append(rec)   # verbatim — preserve pk-less records
        model = rec['model']
        fields = rec['fields']
        if model == 'core.accountingcategory':
            c.ac_by_code[fields['code']] = rec.get('pk')
        elif model == 'jobs.ratescheme':
            c.scheme_by_name[fields['name']] = rec.get('pk')
            if isinstance(rec.get('pk'), int):
                max_rs_pk = max(max_rs_pk, rec['pk'])

    c.ac_svc_pk = c.ac_by_code.get('SVC')
    c.ac_mat_pk = c.ac_by_code.get('MTL')
    if max_rs_pk:
        c._pk_counters['jobs.ratescheme'] = max(
            c._pk_counters['jobs.ratescheme'], max_rs_pk)

    # One shared flat-fee ("Fixed charge") RateScheme for converter-derived
    # tasks that don't fit a nealseed scheme. Per the flat-fee pricing design,
    # the per-task price rides on the task's active_modifiers as
    # {'flat_fee_price': <str>}; this scheme's own rate is only a fallback.
    ff_pk = c.next_pk('jobs.ratescheme')
    c.add_fixture('jobs.ratescheme', ff_pk, {
        'name':                'Flat Fee',
        'description':         'Shared fixed-charge scheme; price set per task.',
        'algorithm':           'flat_fee',
        'rate':                '0.00',
        'unit_label':          'ea',
        'modifiers':           [],
        'accounting_category': c.ac_svc_pk,
        'replaced_by':         None,
        'replaced_at':         None,
    })
    c.flat_fee_scheme_pk = ff_pk
    c.scheme_by_name['Flat Fee'] = ff_pk


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

        # Clamp phone numbers to the model field length (max_length=20).
        # FreeAgent exports sometimes carry extension text / multiple numbers.
        work_number = work_number[:20]
        mobile_number = mobile_number[:20]

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
    - Name: the Kanban card Description (FreeAgent has no job names).
    - Status: mapped from the Kanban card 'Stage' column.
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

        # --- 4. Map Kanban Stage → job status -----------------------------
        stage = (card.get('Stage') or '').strip().lower()
        job_status = _STAGE_TO_JOB_STATUS.get(stage, 'draft')

        # --- 5. Build name and description from card fields ---------------
        desc = (card.get('Description') or '').strip()
        notes = (card.get('Notes') or '').strip()
        # Job name: the card Description (the FreeAgent data has no job
        # names); fall back to the card Name when Description is blank.
        job_name = (desc or card.get('Name') or '')[:50]
        # Job description duplicates the full Description plus Notes.
        parts = [p for p in (desc, notes) if p]
        description = '\n'.join(parts)

        # --- 6. Emit fixture ----------------------------------------------
        job_pk = c.next_pk('jobs.job')
        c.add_fixture('jobs.job', job_pk, {
            'job_number':         job_number,
            'name':               job_name,
            'contact':            contact_pk,
            'status':             job_status,
            'created_date':       P.format_datetime(raw_date) or f'{_FALLBACK_YEAR}-01-01T00:00:00+00:00',
            'start_date':         None,
            'due_date':           P.format_datetime(card.get('Due date')),
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
            # created_date_bare: bare 'YYYY-MM-DD' used internally by reconcile
            # for date arithmetic (_add_days, P.to_datetime).
            created_date_bare = P.format_date(raw_date) or f'{_FALLBACK_YEAR}-01-01'
            # created_date_tz: tz-aware value for the DateTimeField fixture.
            created_date_tz = f'{created_date_bare}T00:00:00+00:00'

            est_pk = c.next_pk('estimates.estimate')
            c.add_fixture('estimates.estimate', est_pk, {
                'job':             job_pk,
                'estimate_number': base,
                'version':         version,
                'parent':          None,
                'status':          est_status,
                'created_date':    created_date_tz,
                'sent_date':       None,
                'expiration_date': None,
                'closed_date':     None,
            })

            base_estimates.append({
                'est_pk':       est_pk,
                'status':       est_status,
                'created_date': created_date_bare,   # bare date; used by reconcile
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


# Default RateScheme for tasks with no more specific keyword match.
_CHECKLIST_DEFAULT_SCHEME = 'Shop labor'


def _scheme_pk(c, scheme_name):
    """Resolve a seed RateScheme name to its pk, falling back to Shop labor."""
    return (c.scheme_by_name.get(scheme_name)
            or c.scheme_by_name.get(_CHECKLIST_DEFAULT_SCHEME))


def _match_seed_scheme(c, algorithm, rate):
    """Match a line's (algorithm, rate) to a seed RateScheme.

    Returns (scheme_pk, active_modifiers). Time/qty lines match the nearest
    seed scheme of that algorithm when within ~10% of its rate. Anything
    that doesn't fit — and every flat-fee line, since the only flat-fee
    seed scheme (Delivery1) is delivery-specific — goes to the shared
    'Flat Fee' scheme with the price carried on the task's active_modifiers.
    """
    if algorithm != 'flat_fee':
        candidates = [
            f for f in c.fixture_data
            if f['model'] == 'jobs.ratescheme'
            and f['fields'].get('algorithm') == algorithm
            and f.get('pk') != c.flat_fee_scheme_pk
        ]
        if candidates:
            nearest = min(
                candidates,
                key=lambda f: abs(Decimal(f['fields']['rate']) - rate))
            near_rate = Decimal(nearest['fields']['rate'])
            tolerance = max(near_rate, Decimal('1')) / 10   # within ~10%
            if abs(near_rate - rate) <= tolerance:
                return nearest['pk'], []
    # Doesn't fit a seed scheme: shared Flat Fee scheme, price per task.
    return c.flat_fee_scheme_pk, {'flat_fee_price': f'{rate:.2f}'}


def _fallback_scheme(c, li):
    """RateScheme pk + active_modifiers for an estimate-line-item-derived task.

    Keyword rule first; otherwise match a seed scheme by rate, or fall back
    to the shared Flat Fee scheme. Returns (scheme_pk, active_modifiers).
    """
    keyword_name = P.checklist_scheme_name(li['description'])
    if keyword_name != _CHECKLIST_DEFAULT_SCHEME:
        return _scheme_pk(c, keyword_name), []
    algorithm = P.infer_algorithm(li['item_type'], li['units'])
    return _match_seed_scheme(c, algorithm, li['price'])


def _build_checklist_tasks(c, base_ref, job_pk, items):
    """Emit jobs.task fixtures from parsed Kanban checklist items.

    Indented checklist lines become subtasks of the most recent
    non-indented line ([X] -> complete, [ ] -> pending).
    """
    sort_order = 0
    last_toplevel_pk = None
    for item in items:
        sort_order += 1
        name = (item['text'] or 'Task')[:255] or 'Task'
        scheme_pk = _scheme_pk(c, P.checklist_scheme_name(name))
        parent_pk = last_toplevel_pk if item['is_subtask'] else None
        task_pk = c.next_pk('jobs.task')
        c.add_fixture('jobs.task', task_pk, {
            'job':              job_pk,
            'rate_scheme':      scheme_pk,
            'name':             name,
            'description':      item['text'] or '',
            'est_qty':          None,
            'est_worker_time':  None,
            'actual_qty':       None,
            'active_modifiers': [],
            'status':           'complete' if item['completed'] else 'pending',
            'blocked_reason':   '',
            'worker_queue':     None,
            'assignee':         None,
            'parent_task':      parent_pk,
            'source_template':  None,
            'source_plan_task': None,
            'sort_order':       sort_order,
        })
        if not item['is_subtask']:
            last_toplevel_pk = task_pk
        if base_ref not in c.cut_task and 'cut' in name.lower():
            c.cut_task[base_ref] = task_pk


def _build_line_item_tasks(c, base_ref, job_pk, task_lines):
    """Emit jobs.task fixtures from task-classified estimate line items.

    Used only for jobs whose Kanban card has no checklist.
    """
    sort_order = 0
    for li in task_lines:
        sort_order += 1
        name = (li['description'] or 'Task')[:255] or 'Task'
        scheme_pk, active_modifiers = _fallback_scheme(c, li)
        task_pk = c.next_pk('jobs.task')
        c.add_fixture('jobs.task', task_pk, {
            'job':              job_pk,
            'rate_scheme':      scheme_pk,
            'name':             name,
            'description':      li['description'] or '',
            'est_qty':          f"{li['qty']:.2f}",
            'est_worker_time':  None,
            'actual_qty':       None,
            'active_modifiers': active_modifiers,
            'status':           'pending',
            'blocked_reason':   '',
            'worker_queue':     None,
            'assignee':         None,
            'parent_task':      None,
            'source_template':  None,
            'source_plan_task': None,
            'sort_order':       sort_order,
        })
        if base_ref not in c.cut_task and 'cut' in name.lower():
            c.cut_task[base_ref] = task_pk


def _apply_worker_times(c, job_pk, card):
    """Apply the Kanban card's est cut/assembly times to matching tasks."""
    def _find_task_fixture(predicate):
        for f in c.fixture_data:
            if f['model'] == 'jobs.task' and f['fields']['job'] == job_pk:
                if predicate(f['fields']['name']):
                    return f
        return None

    def _set(fixture, raw_val):
        duration = P.hours_to_duration(raw_val)
        if duration is not None:
            fixture['fields']['est_worker_time'] = duration

    raw_cut = card.get('est *cut* time')
    if raw_cut not in (None, ''):
        f = _find_task_fixture(lambda n: 'cut' in n.lower())
        if f is not None:
            _set(f, raw_cut)
        else:
            c.time_match_misses += 1

    raw_ass = card.get('est ASS time')
    if raw_ass not in (None, ''):
        f = _find_task_fixture(lambda n: 'assemb' in n.lower())
        if f is not None:
            _set(f, raw_ass)
        else:
            c.time_match_misses += 1


def _build_deliverables(c, job_pk, material_lines):
    """Emit deliverables.deliverable fixtures — one per material line, or a
    synthetic 'Fake Deliverable' when the job has no material lines.
    """
    # created_at/updated_at are auto fields; loaddata won't populate them, so
    # the fixture must supply a value. Reuse the job's tz-aware created_date.
    job_fixture = next(
        (f for f in c.fixture_data
         if f['model'] == 'jobs.job' and f['pk'] == job_pk),
        None,
    )
    deliv_ts = (
        job_fixture['fields']['created_date'] if job_fixture
        else f'{_FALLBACK_YEAR}-01-01T00:00:00+00:00'
    )

    if material_lines:
        d_sort = 0
        for li in material_lines:
            d_sort += 10
            d_pk = c.next_pk('deliverables.deliverable')
            c.add_fixture('deliverables.deliverable', d_pk, {
                'job':         job_pk,
                'description': (li['description'] or '')[:255],
                'qty_ordered': f"{li['qty']:.2f}",
                'units':       li['units'] or 'each',
                'sort_order':  d_sort,
                'created_at':  deliv_ts,
                'updated_at':  deliv_ts,
            })
    else:
        d_pk = c.next_pk('deliverables.deliverable')
        c.add_fixture('deliverables.deliverable', d_pk, {
            'job':         job_pk,
            'description': 'Fake Deliverable',
            'qty_ordered': '1.00',
            'units':       'each',
            'sort_order':  10,
            'created_at':  deliv_ts,
            'updated_at':  deliv_ts,
        })
        c.fake_deliverable_count += 1


def derive_atoms(c):
    """Derive Task, Material and Deliverable fixtures for each job.

    Tasks come from the Kanban card's Checklist when it has any items
    (each line -> a Task; indented lines -> subtasks; [X] -> complete).
    Only when a job has no checklist do task-classified estimate line items
    become Tasks instead. Materials and Deliverables always come from the
    latest estimate's material-classified line items.

    RateSchemes are the canonical seed schemes (build_seed); checklist tasks
    are assigned by keyword, fallback tasks by keyword then rate-match/clone.

    Mutates c.fixture_data, c.cut_task, c.time_match_misses,
    c.fake_deliverable_count.
    """
    for base_ref, job_info in c.jobs.items():
        job_pk = job_info['job_pk']
        card = job_info['card']

        # Use only the latest estimate version for materials / fallback tasks.
        est_list = c.estimates.get(base_ref, [])
        latest = (max(est_list, key=lambda e: e['version'])
                  if est_list else None)
        lines = c.line_items.get(latest['est_pk'], []) if latest else []
        task_lines = [li for li in lines if li['classification'] == 'task']
        material_lines = [li for li in lines
                          if li['classification'] == 'material']

        # --- 1. Tasks: checklist first, estimate line items as fallback ----
        checklist_items = P.parse_checklist(card.get('Checklist'))
        if checklist_items:
            _build_checklist_tasks(c, base_ref, job_pk, checklist_items)
        else:
            _build_line_item_tasks(c, base_ref, job_pk, task_lines)

        # --- 2. Materials (after tasks so cut_task is populated) -----------
        for li in material_lines:
            mat_pk = c.next_pk('inventory.material')
            c.add_fixture('inventory.material', mat_pk, {
                'job':                 job_pk,
                'task':                c.cut_task.get(base_ref),
                'description':         (li['description'] or '')[:255],
                'quantity':            f"{li['qty']:.2f}",
                'units':               li['units'] or 'none',
                'unit_cost':           '0.00',
                'sell_price':          f"{li['price']:.2f}",
                'accounting_category': c.ac_mat_pk,
                'price_list_item':     None,
                'consumption_state':   'pending',
                'restocked_qty':       '0.00',
                'po_line_item':        None,
                'source_plan_material': None,
            })

        # --- 3. CSV worker-time assignments --------------------------------
        _apply_worker_times(c, job_pk, card)

        # --- 4. Deliverables -----------------------------------------------
        _build_deliverables(c, job_pk, material_lines)


# Maps FreeAgent Invoice Status values to Minibini invoice status constants.
# 'Sent' with a paid date is handled specially in build_invoices (→ 'paid').
_INV_STATUS_MAP = {
    'Draft':      'draft',
    'Cancelled':  'cancelled',
    'Open':       'open',
    'Paid':       'paid',
}


def _map_invoice_status(fa_status, paid_date):
    """Map a FreeAgent invoice status string to a Minibini status constant.

    FreeAgent marks all sent invoices (paid or unpaid) as 'Sent'. We detect
    paid invoices by the presence of a Paid Date value.
    """
    s = (fa_status or '').strip()
    if s == 'Sent':
        # If a paid date is present, the invoice was paid in full.
        return 'paid' if paid_date else 'open'
    return _INV_STATUS_MAP.get(s, 'open')


def build_invoices(c):
    """Emit invoicing.invoice and invoicing.invoicelineitem fixtures.

    Linkage strategy (plan amendment):
      For each spine job, collect the set of Invoice Reference values from
      that job's Estimate container rows. An Invoice whose Reference matches
      one of those values belongs to that job.

    Invoices not referenced by any spine job's estimates are skipped.

    Populates:
        c.invoice_totals — {base_ref: Decimal sum of qty*price for that job's
                            invoice line items}
    """
    # ------------------------------------------------------------------
    # 1. Build invoice_ref -> (job_pk, base_ref) from estimate rows
    # ------------------------------------------------------------------
    inv_ref_to_job = {}   # str(invoice_ref) -> job_pk
    inv_ref_to_base = {}  # str(invoice_ref) -> base_ref

    for base_ref, job_info in c.jobs.items():
        job_pk = job_info['job_pk']
        for est_row in job_info['estimate_rows']:
            inv_ref = (est_row.get('Invoice Reference') or '')
            inv_ref_str = str(inv_ref).strip()
            if inv_ref_str:
                inv_ref_to_job[inv_ref_str] = job_pk
                inv_ref_to_base[inv_ref_str] = base_ref

    # ------------------------------------------------------------------
    # 2. Walk Invoices sheet: collect (container_row, [li_rows]) pairs
    # ------------------------------------------------------------------
    all_pairs = []
    current_container = None
    current_lis = []

    for row in c.loader.sheets_data.get('Invoices', []):
        ref = (row.get('Reference') or '').strip()

        if ref:
            # Skip repeated-header rows
            if ref == 'Reference':
                continue
            # Save the previous container before starting a new one
            if current_container is not None:
                all_pairs.append((current_container, current_lis))
            current_container = row
            current_lis = []
        else:
            # Line-item row
            if current_container is None:
                continue
            item_type = (row.get('Item Type') or '').strip()
            if item_type == 'Item Type':
                continue
            current_lis.append(row)

    # Flush the last container
    if current_container is not None:
        all_pairs.append((current_container, current_lis))

    # ------------------------------------------------------------------
    # 3. Emit matched invoices and their line items
    # ------------------------------------------------------------------
    for container, lis in all_pairs:
        ref_str = str(container.get('Reference') or '').strip()
        if ref_str not in inv_ref_to_job:
            continue

        job_pk = inv_ref_to_job[ref_str]
        base_ref = inv_ref_to_base[ref_str]

        fa_status = (container.get('Status') or '').strip()
        paid_date = container.get('Paid Date')
        status = _map_invoice_status(fa_status, paid_date)

        raw_date = container.get('Date')
        created_date = P.format_datetime(raw_date) or f'{_FALLBACK_YEAR}-01-01T00:00:00+00:00'
        closed_date = P.format_datetime(paid_date) if status == 'paid' else None

        inv_pk = c.next_pk('invoicing.invoice')
        c.add_fixture('invoicing.invoice', inv_pk, {
            'job':                  job_pk,
            'invoice_number':       ref_str,
            'status':               status,
            'created_date':         created_date,
            'sent_date':            None,
            'closed_date':          closed_date,
            'qbo_id':               None,
            'qbo_payment_status':   '',
            'qbo_amount_paid':      None,
        })

        # Emit line items
        line_number = 0
        job_li_total = c.invoice_totals.get(base_ref, Decimal('0'))

        for li_row in lis:
            item_type = (li_row.get('Item Type') or '').strip()
            description = str(li_row.get('Description') or '').strip()
            classification = P.classify_line_item(item_type, description)
            if classification == 'skip':
                continue

            line_number += 1
            qty = P.parse_decimal(li_row.get('Quantity'))
            price = P.parse_decimal(li_row.get('Price'))

            li_pk = c.next_pk('invoicing.invoicelineitem')
            c.add_fixture('invoicing.invoicelineitem', li_pk, {
                'invoice':             inv_pk,
                'price_list_item':     None,
                'line_number':         line_number,
                'qty':                 f'{qty:.2f}',
                'units':               'none',  # intentional: FreeAgent invoice line items carry no unit signal
                'description':         description,
                'price':               f'{price:.2f}',
                'accounting_category': None,
                'taxable_override':    None,
                'tax_rate_override':   None,
            })

            job_li_total += qty * price

        c.invoice_totals[base_ref] = job_li_total

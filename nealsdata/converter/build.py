"""Base fixture builders for the Neal's data converter.

Each builder function takes a NealsDataConverter instance as its first
argument and appends fixture records to c.fixture_data via c.add_fixture().
"""
import json
import re
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from nealsdata.converter import parsing as P

# Fallback year when no date can be parsed from the source data.
_FALLBACK_YEAR = 2025

# Palette for Job.accent_color round-robin. Mirrors
# apps.jobs.models.JOB_ACCENT_COLOR_PALETTE; kept in sync manually so the
# converter doesn't need a configured Django settings module at import time.
_ACCENT_COLOR_PALETTE = (
    '#f97066', '#f59e0b', '#14b8a6', '#8b5cf6',
    '#38bdf8', '#fb7185', '#84cc16', '#f97316',
)

# Maps Kanban 'Stage' values to Minibini job status constants.
# 'estimate' is handled separately in build_jobs (it depends on Swimlane).
_STAGE_TO_JOB_STATUS = {
    'in progress':      'in_progress',
    'invoice':          'work_complete',
    'done or rejected': 'completed',
}


def _is_neals_swimlane(card):
    """True when a Kanban card sits in the 'Neal's do' swimlane.

    'Neal's do' means work still on Neal's side: an estimate not yet sent,
    or an invoice not yet sent. 'Other do' means it has gone to the customer.
    """
    return (card.get('Swimlane') or '').strip().lower().startswith('neal')


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
    """Emit document-numbering + app-settings state.

    Both Configuration and AppState use the key field as primary key, so pk is
    the key string. Document-number *patterns* are user-settable Configuration;
    the *counters* are machine state in AppState (core migration 0018). Estimate
    numbering no longer uses this service, so it gets no sequence/counter keys.
    """
    config = [
        ('job_number_sequence',      'J{year}-{counter:04d}'),
        ('invoice_number_sequence',  'INV-{year}-{counter:04d}'),
        ('po_number_sequence',       'PO-{year}-{counter:04d}'),
        ('est_expire_days',          '30'),
        ('email_retention_days',     '30'),
        # Mirror apps.core.units.DEFAULT_UNITS so every emitted line-item /
        # material / deliverable row validates against the running app's
        # canonical list. ('Days' inputs convert to 'hours' × 8 at emit time;
        # see parsing.resolve_li_units_and_qty.)
        ('units_list',               json.dumps(['none', 'ea', 'hours', 'min', 'sheets', 'sq ft', 'ft', 'yd', 'm', 'lbs', 'kg', 'gal', 'qt', 'L', 'bd ft', 'ln ft'])),
    ]
    for key, value in config:
        c.add_fixture('core.configuration', key, {'value': value})

    # Machine-managed counters live in AppState (a separate table the Settings
    # editor can't touch). Without these, document creation (e.g. a new PO)
    # raises "AppState key '..._counter' not found".
    for key in ('job_counter', 'invoice_counter', 'po_counter'):
        c.add_fixture('core.appstate', key, {'value': '0'})


def _anonymize_email(value):
    """Replace an email address's domain with example.com, keeping the
    local part. A value with no '@' is treated as the local part."""
    local = (value or '').split('@', 1)[0].strip()
    return f'{local}@example.com' if local else (value or '')


def _anonymize_phone(value):
    """Anonymize a phone number: keep the area code and the last four
    digits, replace the 3-digit prefix (exchange) with 555."""
    digits = re.sub(r'\D', '', value or '')
    if len(digits) < 4:
        return '555-555-5555'
    last4 = digits[-4:]
    area = digits[:-7] if len(digits) >= 7 else ''
    return f'{area}-555-{last4}' if area else f'555-{last4}'


# Free-text scrubbing: email addresses, and phone numbers in the classic
# 10-digit separated form (a deliberately conservative phone pattern to
# avoid scrubbing part numbers / dimensions).
_EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
_PHONE_RE = re.compile(r'\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}')


def _scrub_text(text):
    """Anonymize email addresses and phone numbers found in free text."""
    text = _EMAIL_RE.sub(lambda m: _anonymize_email(m.group(0)), text)
    text = _PHONE_RE.sub(lambda m: _anonymize_phone(m.group(0)), text)
    return text


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

        # Anonymize contact details: real email domains -> example.com,
        # phone-number prefixes -> 555.
        email = (_anonymize_email(email) if email
                 else f'noreply+{contact_pk}@example.com')
        work_number = _anonymize_phone(work_number) if work_number else ''
        mobile_number = _anonymize_phone(mobile_number) if mobile_number else ''
        if not work_number and not mobile_number:
            work_number = '555-555-5555'

        # Clamp phone numbers to the model field length (max_length=20).
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
    - Job number: the FreeAgent estimate base reference (the leading digit
      run of the estimate's Reference column, e.g. "07754"). The base ref is
      also the join key with the Kanban card's External ID, so this gives
      the Job the same identifier the source data ties everything to.

    Sets:
    - c.job_map  : base_ref -> job_pk
    - c.jobs     : base_ref -> {'job_pk', 'card', 'estimate_rows', 'primary_ref'}
    - c.discarded_cards : list of notes about skipped spine entries
    """
    for idx, entry in enumerate(c.spine):
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

        # --- 3. Job number is the base ref itself -------------------------
        raw_date = primary_row.get('Date')
        job_number = base_ref

        # --- 4. Map Kanban Stage (+ Swimlane) → job status ----------------
        stage = (card.get('Stage') or '').strip().lower()
        if stage == 'estimate':
            # Estimate stage: 'Neal's do' = estimate not yet sent (job
            # draft); 'Other do' = estimate sent to customer (job submitted).
            job_status = 'draft' if _is_neals_swimlane(card) else 'submitted'
        else:
            job_status = _STAGE_TO_JOB_STATUS.get(stage, 'draft')

        # --- 5. Build name and description from card fields ---------------
        # Scrub emails / phone numbers that may appear in the free text.
        desc = _scrub_text((card.get('Description') or '').strip())
        notes = _scrub_text((card.get('Notes') or '').strip())
        # Job name: the card Description (the FreeAgent data has no job
        # names); fall back to the card Name when Description is blank.
        job_name = (desc or card.get('Name') or '')[:50]
        # Job description duplicates the full Description plus Notes.
        parts = [p for p in (desc, notes) if p]
        description = '\n'.join(parts)

        # --- 6. Emit fixture ----------------------------------------------
        job_pk = c.next_pk('jobs.job')
        accent_color = _ACCENT_COLOR_PALETTE[idx % len(_ACCENT_COLOR_PALETTE)]
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
            'accent_color':       accent_color,
            'hold_reason':        '',
        })

        # --- 7. Record maps -----------------------------------------------
        c.job_map[base_ref] = job_pk
        c.jobs[base_ref] = {
            'job_pk':        job_pk,
            'card':          card,
            'estimate_rows': estimate_rows,
            'primary_ref':   primary_ref,
            'status':        job_status,
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
        sell = P.parse_decimal(price_raw).quantize(Decimal('0.01'))
        selling_price = f'{sell:.2f}'
        # Purchase price modelled as 83.33% of the listed sell price.
        purchase_price = f'{sell * Decimal("0.8333"):.2f}'

        pk = c.next_pk('inventory.pricelistitem')
        c.add_fixture('inventory.pricelistitem', pk, {
            'code': code,
            'description': description,
            'units': 'none',
            'selling_price': selling_price,
            'purchase_price': purchase_price,
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

        # Estimate-stage jobs: the Kanban swimlane drives the latest
        # estimate's status — 'Neal's do' = draft (not sent), 'Other do' =
        # open (sent). Older versions are superseded by reconcile as usual.
        card = c.jobs.get(base, {}).get('card', {})
        est_stage = (card.get('Stage') or '').strip().lower() == 'estimate'
        swimlane_status = 'draft' if _is_neals_swimlane(card) else 'open'

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
            # Estimate-stage job: the latest version's status comes from the
            # swimlane, not the FreeAgent Status column.
            if est_stage and version == len(entries):
                est_status = swimlane_status
            # created_date_bare: bare 'YYYY-MM-DD' used internally by reconcile
            # for date arithmetic (_add_days, P.to_datetime).
            created_date_bare = P.format_date(raw_date) or f'{_FALLBACK_YEAR}-01-01'
            # created_date_tz: tz-aware value for the DateTimeField fixture.
            created_date_tz = f'{created_date_bare}T00:00:00+00:00'

            est_pk = c.next_pk('estimates.estimate')
            c.add_fixture('estimates.estimate', est_pk, {
                'job':             job_pk,
                'estimate_number': f'{base}-{version}',
                'version':         version,
                'parent':          None,
                'status':          est_status,
                'created_date':    created_date_tz,
                'sent_date':       None,
                'expiration_date': None,
                'closed_date':     None,
                'public_token':    secrets.token_urlsafe(32),
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

                # Map Item Type → canonical (units, qty). 'Days' lines convert
                # to 'hours' by multiplying qty by 8 (one workday).
                units, qty = P.resolve_li_units_and_qty(item_type, qty)

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


# Leading verbs that mark a material-keyword line as labour/prep (a Task)
# rather than raw stock or a finished deliverable.
_LABOR_VERB_PREFIXES = ('prepare', 'apply', 'glue', 'engrave')


def _material_line_kind(description):
    """Classify a material-classified estimate line into one of:

      'material'    — raw stock (sheets, board feet, a materials-cost line)
      'task'        — labour/prep that merely names a material
      'deliverable' — a finished good or named part

    Each material-classified line becomes exactly one of these.
    """
    t = (description or '').strip().lower()
    if ('sheet' in t or 'board feet' in t or 'bf of' in t
            or t.startswith('materials') or t.startswith('estimated material')):
        return 'material'
    if t.startswith(_LABOR_VERB_PREFIXES):
        return 'task'
    return 'deliverable'


# Checklist lines that are board status-markers, not real work. A line
# starting with one of these is dropped (no Task emitted) — the underlying
# fact is tracked more accurately elsewhere (FreeAgent invoice/payment data)
# or is just a recurring reminder. A line carrying a '(track time)' marker is
# never dropped: that marker explicitly flags a real, time-tracked task.
_DROPPED_CHECKLIST_PREFIXES = (
    'invoice sent',
    'payment received',
    'jan take photos',
    'packing slip',
)


def _is_dropped_checklist_line(text):
    """True when a checklist line is a board status-marker to skip."""
    t = (text or '').strip().lower()
    if '(track time)' in t:
        return False
    return t.startswith(_DROPPED_CHECKLIST_PREFIXES)


def _build_checklist_tasks(c, base_ref, job_pk, items, start_sort=0):
    """Emit jobs.task fixtures from parsed Kanban checklist items.

    Indented checklist lines become subtasks of the most recent
    non-indented line ([X] -> complete, [ ] -> pending). Returns the final
    per-job sort_order so later task builders can continue the sequence.

    Pickup markers (Shipments) and board status-markers
    (_is_dropped_checklist_line) do not become Tasks.
    """
    sort_order = start_sort
    last_toplevel_pk = None
    for item in items:
        # The 'Picked up/Delivered' marker drives Shipments, not Tasks.
        if _is_pickup_marker(item['text']):
            continue
        # Board status-markers (Invoice Sent, Payment Received, …) are noise.
        if _is_dropped_checklist_line(item['text']):
            continue
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
    return sort_order


def _build_line_item_tasks(c, base_ref, job_pk, task_lines, start_sort=0):
    """Emit jobs.task fixtures from estimate line items.

    Used for the no-checklist fallback (task-classified lines) and for
    material-keyword lines reclassified as labour. Returns the final
    per-job sort_order.
    """
    sort_order = start_sort
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
    return sort_order


# Default est_worker_time for any task not matched to a Kanban time column.
# The checklists carry no per-task time data, so this is an invented flat
# 1-hour estimate (see _apply_worker_times).
_DEFAULT_WORKER_TIME = '01:00:00'

# Task-name keywords matched to the Kanban card's est ASS time column.
_ASSEMBLY_KEYWORDS = ('assemb', 'build', 'make')

# Job statuses for which atoms live on the plan side (EstWorksheet +
# PlanTask + PlanMaterial) rather than the real side (Task + Material).
# These are statuses where no estimate has been accepted yet: an accepted
# estimate is the trigger that copies plan atoms onto the Job per §2.3.
_PLAN_STATUSES = ('draft', 'submitted')


def _apply_worker_times(c, job_pk, card, *, task_model='jobs.task',
                        container_field='job', container_pk=None):
    """Apply the Kanban card's est cut/assembly times to matching tasks.

    Works on both jobs.task (real side, scoped by ``job`` FK) and
    jobs.plantask (plan side, scoped by ``est_worksheet`` FK). The Kanban
    card carries two job-level time columns (est *cut* time, est ASS time);
    each lands on at most one task — the first whose name names a cut
    ('cut') or an assembly (_ASSEMBLY_KEYWORDS). The two never share a
    task. The checklists hold no per-task time data, so every other task is
    given a flat 1-hour estimate.
    """
    container_pk = container_pk if container_pk is not None else job_pk

    def _find_task_fixture(predicate, exclude=None):
        for f in c.fixture_data:
            if f is exclude:
                continue
            if f['model'] == task_model and f['fields'][container_field] == container_pk:
                if predicate(f['fields']['name']):
                    return f
        return None

    def _set(fixture, raw_val):
        duration = P.hours_to_duration(raw_val)
        if duration is not None:
            fixture['fields']['est_worker_time'] = duration

    cut_fixture = None
    raw_cut = card.get('est *cut* time')
    if raw_cut not in (None, ''):
        cut_fixture = _find_task_fixture(lambda n: 'cut' in n.lower())
        if cut_fixture is not None:
            _set(cut_fixture, raw_cut)
        else:
            c.time_match_misses += 1

    raw_ass = card.get('est ASS time')
    if raw_ass not in (None, ''):
        f = _find_task_fixture(
            lambda n: any(k in n.lower() for k in _ASSEMBLY_KEYWORDS),
            exclude=cut_fixture,
        )
        if f is not None:
            _set(f, raw_ass)
        else:
            c.time_match_misses += 1

    # Every task left without a card-derived time gets the default estimate.
    for f in c.fixture_data:
        if (f['model'] == task_model
                and f['fields'][container_field] == container_pk
                and f['fields'].get('est_worker_time') is None):
            f['fields']['est_worker_time'] = _DEFAULT_WORKER_TIME


def _build_estworksheet(c, job_pk, created_date):
    """Emit one estimates.estworksheet per Job. Returns the new pk."""
    ws_pk = c.next_pk('estimates.estworksheet')
    c.add_fixture('estimates.estworksheet', ws_pk, {
        'job':          job_pk,
        'created_date': created_date,
    })
    return ws_pk


def _emit_estimate_line_item_source(c, li_pk, source_type, source_pk):
    """Emit an estimates.estimatelineitemsource row claiming a plan atom.

    Each plan atom can be claimed by at most one line item (model enforces
    unique_together on (source_type, source_pk)); the converter emits at
    most one source row per plan atom by construction (each plan atom is
    derived from exactly one LI).
    """
    src_pk = c.next_pk('estimates.estimatelineitemsource')
    c.add_fixture('estimates.estimatelineitemsource', src_pk, {
        'estimate_line_item': li_pk,
        'source_type':        source_type,
        'source_pk':          source_pk,
    })


def _build_plan_checklist_tasks(c, base_ref, ws_pk, items, start_sort=0):
    """Emit jobs.plantask fixtures from parsed Kanban checklist items.

    PlanTask is flat — the checklist's subtask hierarchy is lost. Pickup
    markers (Shipments) and board status-markers (_is_dropped_checklist_line)
    do not become PlanTasks. Returns the final per-worksheet sort_order.
    Checklist-derived plan tasks have no source LI, so no
    EstimateLineItemSource row is emitted.

    est_qty is set to Decimal('1') — PlanTask.clean() requires non-null
    est_qty, and the checklist carries no quantity signal.
    """
    sort_order = start_sort
    for item in items:
        if _is_pickup_marker(item['text']):
            continue
        if _is_dropped_checklist_line(item['text']):
            continue
        sort_order += 1
        name = (item['text'] or 'Task')[:255] or 'Task'
        scheme_pk = _scheme_pk(c, P.checklist_scheme_name(name))
        pt_pk = c.next_pk('jobs.plantask')
        c.add_fixture('jobs.plantask', pt_pk, {
            'est_worksheet':    ws_pk,
            'rate_scheme':      scheme_pk,
            'name':             name,
            'description':      item['text'] or '',
            'est_qty':          '1.00',
            'est_worker_time':  None,
            'active_modifiers': [],
            'sort_order':       sort_order,
        })
        if base_ref not in c.cut_plan_task and 'cut' in name.lower():
            c.cut_plan_task[base_ref] = pt_pk
    return sort_order


def _build_plan_line_item_tasks(c, base_ref, ws_pk, task_lines, start_sort=0):
    """Emit jobs.plantask fixtures from estimate line items, plus the
    EstimateLineItemSource row linking each to its source LI."""
    sort_order = start_sort
    for li in task_lines:
        sort_order += 1
        name = (li['description'] or 'Task')[:255] or 'Task'
        scheme_pk, active_modifiers = _fallback_scheme(c, li)
        pt_pk = c.next_pk('jobs.plantask')
        c.add_fixture('jobs.plantask', pt_pk, {
            'est_worksheet':    ws_pk,
            'rate_scheme':      scheme_pk,
            'name':             name,
            'description':      li['description'] or '',
            'est_qty':          f"{li['qty']:.2f}",
            'est_worker_time':  None,
            'active_modifiers': active_modifiers,
            'sort_order':       sort_order,
        })
        _emit_estimate_line_item_source(
            c, li['line_item_pk'], 'plan_task', pt_pk)
        if base_ref not in c.cut_plan_task and 'cut' in name.lower():
            c.cut_plan_task[base_ref] = pt_pk
    return sort_order


def _build_plan_raw_materials(c, base_ref, ws_pk, raw_lines):
    """Emit inventory.planmaterial fixtures + EstimateLineItemSource rows."""
    for li in raw_lines:
        pm_pk = c.next_pk('inventory.planmaterial')
        c.add_fixture('inventory.planmaterial', pm_pk, {
            'est_worksheet':       ws_pk,
            'plan_task':           c.cut_plan_task.get(base_ref),
            'description':         (li['description'] or '')[:255],
            'quantity':            f"{li['qty']:.2f}",
            'units':               li['units'] or 'none',
            'unit_cost':           '0.00',
            'sell_price':          f"{li['price']:.2f}",
            'accounting_category': c.ac_mat_pk,
            'price_list_item':     None,
        })
        _emit_estimate_line_item_source(
            c, li['line_item_pk'], 'plan_material', pm_pk)


def _build_deliverables(c, job_pk, deliverable_lines):
    """Emit deliverables.deliverable fixtures — one per deliverable line, or
    a synthetic 'Fake Deliverable' when the job has no deliverable lines.
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

    if deliverable_lines:
        d_sort = 0
        for li in deliverable_lines:
            d_sort += 10
            d_pk = c.next_pk('deliverables.deliverable')
            c.add_fixture('deliverables.deliverable', d_pk, {
                'job':         job_pk,
                'description': (li['description'] or '')[:255],
                'qty_ordered': f"{li['qty']:.2f}",
                'units':       li['units'] or 'ea',
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
            'units':       'ea',
            'sort_order':  10,
            'created_at':  deliv_ts,
            'updated_at':  deliv_ts,
        })
        c.fake_deliverable_count += 1


def derive_atoms(c):
    """Derive Task / PlanTask, Material / PlanMaterial, and Deliverable
    fixtures for each job.

    Branches on the Job's as-built status:

    - **Plan-side** (draft, submitted) — no accepted estimate yet, so the
      atoms live on the plan side. Emit one EstWorksheet per Job, then
      PlanTasks and PlanMaterials on that worksheet. PlanTask is flat (no
      hierarchy) and est_qty is required (Decimal('1') for checklist-derived,
      qty from LI otherwise). LI-derived plan atoms also get an
      EstimateLineItemSource row linking back to the LI.
    - **Real-side** (everything else) — Tasks on Job, Materials on Job.
      Checklist tasks keep their subtask hierarchy and [X]/[ ] status.

    In both modes, Deliverables go on the Job (deliverables are job-scoped,
    not plan-scoped).

    Tasks come from the Kanban card's Checklist when it has any items
    (each line -> a Task; indented lines -> subtasks; [X] -> complete);
    otherwise task-classified estimate line items become Tasks.

    Material-classified estimate line items are split (see
    _material_line_kind): raw stock -> Material/PlanMaterial, labour/prep
    lines -> Task/PlanTask, finished goods -> Deliverable. Each line
    becomes exactly one of those. A job with no deliverable line gets a
    synthetic 'Fake Deliverable'.

    Mutates c.fixture_data, c.cut_task, c.cut_plan_task,
    c.time_match_misses, c.fake_deliverable_count.
    """
    for base_ref, job_info in c.jobs.items():
        job_pk = job_info['job_pk']
        card = job_info['card']
        job_status = job_info.get('status')
        plan_mode = job_status in _PLAN_STATUSES

        # Use only the latest estimate version for materials / fallback tasks.
        est_list = c.estimates.get(base_ref, [])
        latest = (max(est_list, key=lambda e: e['version'])
                  if est_list else None)
        lines = c.line_items.get(latest['est_pk'], []) if latest else []
        task_lines = [li for li in lines if li['classification'] == 'task']

        # Split material-classified lines into raw stock / labour / deliverable.
        raw_lines, labor_lines, deliverable_lines = [], [], []
        for li in lines:
            if li['classification'] != 'material':
                continue
            kind = _material_line_kind(li['description'])
            if kind == 'material':
                raw_lines.append(li)
            elif kind == 'task':
                labor_lines.append(li)
            else:
                deliverable_lines.append(li)

        checklist_items = P.parse_checklist(card.get('Checklist'))

        if plan_mode:
            # --- Plan side: EstWorksheet + PlanTask + PlanMaterial -------
            job_fixture = next(
                (f for f in c.fixture_data
                 if f['model'] == 'jobs.job' and f['pk'] == job_pk),
                None,
            )
            created = (job_fixture['fields']['created_date'] if job_fixture
                       else f'{_FALLBACK_YEAR}-01-01T00:00:00+00:00')
            ws_pk = _build_estworksheet(c, job_pk, created)

            # --- 1. PlanTasks (checklist or LI fallback) + labour lines ---
            if checklist_items:
                sort_order = _build_plan_checklist_tasks(
                    c, base_ref, ws_pk, checklist_items)
            else:
                sort_order = _build_plan_line_item_tasks(
                    c, base_ref, ws_pk, task_lines)
            _build_plan_line_item_tasks(
                c, base_ref, ws_pk, labor_lines, sort_order)

            # --- 2. PlanMaterials: raw stock (after plan tasks so cut is set)
            _build_plan_raw_materials(c, base_ref, ws_pk, raw_lines)

            # --- 3. Worker times on PlanTask fixtures ----------------------
            _apply_worker_times(
                c, job_pk, card,
                task_model='jobs.plantask',
                container_field='est_worksheet',
                container_pk=ws_pk,
            )

            # --- 4. Deliverables: on the Job regardless of plan mode -------
            _build_deliverables(c, job_pk, deliverable_lines)
            continue

        # --- Real side (existing behaviour) ------------------------------

        # --- 1. Tasks: checklist (or fallback line items), plus labour lines.
        if checklist_items:
            sort_order = _build_checklist_tasks(
                c, base_ref, job_pk, checklist_items)
        else:
            sort_order = _build_line_item_tasks(
                c, base_ref, job_pk, task_lines)
        # Material-keyword lines that are really labour become Tasks too.
        _build_line_item_tasks(c, base_ref, job_pk, labor_lines, sort_order)

        # --- 2. Materials: raw stock only (after tasks so cut_task is set) --
        for li in raw_lines:
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

        # --- 4. Deliverables: finished-good lines (or a Fake Deliverable) --
        _build_deliverables(c, job_pk, deliverable_lines)


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

        # Invoice-stage 'Neal's do' jobs: an invoice may exist but has not
        # been sent to the customer — force it to draft.
        card = c.jobs.get(base_ref, {}).get('card', {})
        if ((card.get('Stage') or '').strip().lower() == 'invoice'
                and _is_neals_swimlane(card)):
            status = 'draft'

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
            # Stash classification for the source-link builder; the LI model
            # itself has no item_type field, so this is the only place to
            # hold the FreeAgent Item Type information.
            c.invoice_line_kinds[li_pk] = classification

            job_li_total += qty * price

        c.invoice_totals[base_ref] = job_li_total


def build_invoice_line_item_sources(c):
    """Emit invoicing.invoicelineitemsource rows linking InvoiceLineItems to
    Tasks / Materials on the Job.

    Schema permits freeform invoice lines (no source); the wiring is purely
    cosmetic — it makes Tasks/Materials show as 'billed' on a paid Job in
    the UI instead of orphaned. Heuristic, deterministic claim:

      - For each Invoice on each Job (invoice pk asc → invoice line_number asc)
      - Classify the line via P.classify_line_item.
      - If classification is 'task': claim the next unclaimed Task on the Job;
        fall through to materials if exhausted.
      - If classification is 'material': claim the next unclaimed Material;
        fall through to tasks if exhausted.
      - 'lineitem' / 'skip' classifications never claim (discounts / comments
        are inherently freeform).
      - Leftover lines stay freeform.

    The model's global ``unique_together(source_type, source_pk)`` prevents
    double-claim, so once an atom is claimed by one Invoice it stays claimed
    across the whole fixture.
    """
    invoices_by_job = {}
    for f in c.fixture_data:
        if f['model'] == 'invoicing.invoice':
            invoices_by_job.setdefault(
                f['fields']['job'], []).append(f)
    lines_by_invoice = {}
    for f in c.fixture_data:
        if f['model'] == 'invoicing.invoicelineitem':
            lines_by_invoice.setdefault(
                f['fields']['invoice'], []).append(f)
    tasks_by_job = {}
    for f in c.fixture_data:
        if f['model'] == 'jobs.task':
            tasks_by_job.setdefault(f['fields']['job'], []).append(f['pk'])
    materials_by_job = {}
    for f in c.fixture_data:
        if f['model'] == 'inventory.material':
            materials_by_job.setdefault(f['fields']['job'], []).append(f['pk'])

    claimed_tasks = set()
    claimed_materials = set()

    def _claim(pool, claimed):
        for pk in pool:
            if pk not in claimed:
                claimed.add(pk)
                return pk
        return None

    # Deterministic iteration: jobs by pk, invoices by pk, lines by line_number.
    for job_pk in sorted(invoices_by_job):
        task_pool = sorted(tasks_by_job.get(job_pk, []))
        material_pool = sorted(materials_by_job.get(job_pk, []))
        invs = sorted(invoices_by_job[job_pk], key=lambda f: f['pk'])
        for inv in invs:
            lines = sorted(
                lines_by_invoice.get(inv['pk'], []),
                key=lambda f: f['fields'].get('line_number') or 0,
            )
            for li in lines:
                kind = c.invoice_line_kinds.get(li['pk'])
                if kind == 'task':
                    src_pk = _claim(task_pool, claimed_tasks)
                    src_type = 'task'
                    if src_pk is None:
                        src_pk = _claim(material_pool, claimed_materials)
                        src_type = 'material'
                elif kind == 'material':
                    src_pk = _claim(material_pool, claimed_materials)
                    src_type = 'material'
                    if src_pk is None:
                        src_pk = _claim(task_pool, claimed_tasks)
                        src_type = 'task'
                else:
                    src_pk = None
                if src_pk is None:
                    continue
                row_pk = c.next_pk('invoicing.invoicelineitemsource')
                c.add_fixture(
                    'invoicing.invoicelineitemsource', row_pk, {
                        'invoice_line_item': li['pk'],
                        'source_type':       src_type,
                        'source_pk':         src_pk,
                    })


def _is_pickup_marker(text):
    """True when a checklist line is the 'Picked up/Delivered' marker.

    Matches with or without a trailing recipient name; ordinary
    'pick up ...' notes fail the 'picked up/delivered' prefix test.
    """
    return text.strip().lower().replace(' ', '').startswith('pickedup/delivered')


def _has_pickup_done(card):
    """True when the card's checklist has a checked 'Picked up/Delivered' item."""
    return any(it['completed'] and _is_pickup_marker(it['text'])
               for it in P.parse_checklist(card.get('Checklist')))


def build_shipments(c):
    """Emit deliverables.shipment + deliverables.shipmentitem fixtures.

    Two trigger paths, both producing one picked-up Shipment covering every
    Deliverable on the Job:

    1. The Kanban checklist has a checked 'Picked up/Delivered' item — the
       canonical source signal. Notes left blank.
    2. The Job is in 'completed' status (per §2.5 the Job is impossible
       without all-shipped) but no pickup marker is present. Synthesise a
       Shipment anyway so the all-shipped gate validates. Notes set to
       '(Fake shipment)' when at least one of the Deliverables is real
       (i.e. not a synthesised 'Fake Deliverable'); otherwise the Fake
       Deliverable's own name already signals the fakeness and notes stay
       blank.

    The shipment's picked-up date is taken near the end of the Job's
    lifetime (completed_date, else the latest invoice date, else the Job's
    created_date). Runs AFTER reconcile so job status / completed_date are
    final.
    """
    job_fixtures = {f['pk']: f['fields']
                    for f in c.fixture_data if f['model'] == 'jobs.job'}

    deliverables_by_job = {}
    for f in c.fixture_data:
        if f['model'] == 'deliverables.deliverable':
            deliverables_by_job.setdefault(
                f['fields']['job'], []).append(f)

    latest_invoice_date = {}
    for f in c.fixture_data:
        if f['model'] == 'invoicing.invoice':
            jp = f['fields']['job']
            d = f['fields'].get('created_date')
            if d and d > latest_invoice_date.get(jp, ''):
                latest_invoice_date[jp] = d

    for base_ref, job_info in c.jobs.items():
        job_pk = job_info['job_pk']
        card = job_info['card']
        job_fields = job_fixtures.get(job_pk)
        if job_fields is None:
            continue

        marker_present = _has_pickup_done(card)
        is_completed = job_fields.get('status') == 'completed'
        # Two trigger paths: checked pickup marker, or completed status
        # without one (synthetic). Anything else: no Shipment.
        if not (marker_present or is_completed):
            continue

        delivs = deliverables_by_job.get(job_pk, [])
        if not delivs:
            continue

        picked_ts = (job_fields.get('completed_date')
                     or latest_invoice_date.get(job_pk)
                     or job_fields.get('created_date')
                     or f'{_FALLBACK_YEAR}-01-01T00:00:00+00:00')

        # Note flag: only on synthetic Shipments that cover at least one
        # real (non-Fake) Deliverable. A purely-Fake-Deliverable shipment
        # already telegraphs its fakeness via the Deliverable name.
        notes = ''
        if not marker_present and any(
                d['fields']['description'] != 'Fake Deliverable' for d in delivs):
            notes = '(Fake shipment)'

        ship_pk = c.next_pk('deliverables.shipment')
        c.add_fixture('deliverables.shipment', ship_pk, {
            'job':            job_pk,
            'sequence':       1,
            'status':         'picked_up',
            'prepared_date':  picked_ts,
            'picked_up_date': picked_ts,
            'notes':          notes,
            'created_at':     picked_ts,
            'updated_at':     picked_ts,
        })
        for d in delivs:
            si_pk = c.next_pk('deliverables.shipmentitem')
            c.add_fixture('deliverables.shipmentitem', si_pk, {
                'shipment':    ship_pk,
                'deliverable': d['pk'],
                'qty':         d['fields']['qty_ordered'],
            })


# Models the @history decorator tracks AND that this converter emits. The value
# is the object_type stored on a HistoryEntry — the model class name lowercased
# (see apps/core/history.py _get_object_type). EstWorksheet is intentionally
# absent: it is no longer history-tracked.
_HISTORY_TRACKED_MODELS = {
    'contacts.contact': 'contact',
    'contacts.business': 'business',
    'jobs.job': 'job',
    'jobs.task': 'task',
    'estimates.estimate': 'estimate',
    'inventory.material': 'material',
    'invoicing.invoice': 'invoice',
    'deliverables.deliverable': 'deliverable',
    'deliverables.shipment': 'shipment',
}

# Fallback for objects with no Job and no creation date (Contact, Business).
_HISTORY_FALLBACK_DATE = '2024-01-01T00:00:00+00:00'

# Estimate statuses meaning "was sent" (reached open) and the terminal labels.
_EST_OPENED = {'open', 'accepted', 'rejected', 'expired', 'superseded'}
_EST_TERMINAL = {'accepted', 'rejected', 'expired', 'superseded'}
_EST_ACTION = {
    'accepted': 'Accepted by the customer',
    'rejected': 'Rejected by the customer',
    'expired': 'Expired',
    'superseded': 'Superseded by a revision',
}
# Invoice statuses meaning "was sent" (reached open).
_INV_SENT = {'open', 'paid', 'partly-paid', 'defaulted'}


def _parse_dt(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None


def _job_timeline(job_pk, job_fields, related):
    """Return [(ordinal, object_type, object_id, entry_type, changes)] for one
    Job and its tracked children, in causal order.

    The ordinal encodes the lifecycle phase (see the sequence below); the actual
    timestamps are derived from it so the order is what matters, not the clock.
    """
    ev = []

    def add(ordinal, otype, oid, etype, changes):
        ev.append((ordinal, otype, oid, etype, changes))

    st = job_fields.get('status')
    estimates = related.get('estimates.estimate', [])
    deliverables = related.get('deliverables.deliverable', [])
    tasks = related.get('jobs.task', [])
    materials = related.get('inventory.material', [])
    shipments = related.get('deliverables.shipment', [])
    invoices = related.get('invoicing.invoice', [])

    reached_submitted = st in ('submitted', 'in_progress', 'work_complete', 'completed', 'rejected')
    reached_approved = st in ('in_progress', 'work_complete', 'completed')
    reached_work_complete = st in ('work_complete', 'completed')

    # 0  Job created
    add(0, 'job', job_pk, 'audit', {'_created': True})
    # 1  Estimates created
    for e in estimates:
        add(1, 'estimate', e['pk'], 'audit', {'_created': True})
    # 2  Deliverables created (incl. any fake)
    for d in deliverables:
        add(2, 'deliverable', d['pk'], 'audit', {'_created': True})
    # 3  PlanTasks / PlanMaterials created — not history-tracked, no entries

    # 4  Estimate marked Open (sent) + Job submitted
    for e in estimates:
        if e['fields'].get('status') in _EST_OPENED:
            add(4, 'estimate', e['pk'], 'action',
                {'status': {'old': 'draft', 'new': 'open'}, '_action': 'Sent to the customer'})
    if reached_submitted:
        add(4, 'job', job_pk, 'action',
            {'status': {'old': 'draft', 'new': 'submitted'}, '_action': 'Submitted for approval'})

    # 5  Estimate terminal (accepted/superseded/expired/rejected) + Job approved
    for e in estimates:
        es = e['fields'].get('status')
        if es in _EST_TERMINAL:
            add(5, 'estimate', e['pk'], 'action',
                {'status': {'old': 'open', 'new': es}, '_action': _EST_ACTION[es]})
    if reached_approved:
        add(5, 'job', job_pk, 'action',
            {'status': {'old': 'submitted', 'new': 'approved'}, '_action': 'Approved — released to the floor'})

    # 5.5  Job rejected — after the estimate lapsed, when no tasks exist
    if st == 'rejected':
        add(5.5, 'job', job_pk, 'action',
            {'status': {'old': 'submitted', 'new': 'rejected'}, '_action': 'Rejected'})

    # 6  Tasks and Materials created
    for t in tasks:
        add(6, 'task', t['pk'], 'audit', {'_created': True})
    for m in materials:
        add(6, 'material', m['pk'], 'audit', {'_created': True})

    # 6.5  Job cancelled — after tasks exist (dormant on current data)
    if st == 'cancelled':
        add(6.5, 'job', job_pk, 'action',
            {'status': {'old': 'in_progress', 'new': 'cancelled'}, '_action': 'Cancelled'})

    # 7  Job in progress
    if reached_approved:
        add(7, 'job', job_pk, 'action',
            {'status': {'old': 'approved', 'new': 'in_progress'}, '_action': 'Work started on the floor'})

    # 8  Shipments and Invoices created
    for s in shipments:
        add(8, 'shipment', s['pk'], 'audit', {'_created': True})
    for inv in invoices:
        add(8, 'invoice', inv['pk'], 'audit', {'_created': True})

    # 9  Tasks completed / Materials consumed (work happening)
    for t in tasks:
        if t['fields'].get('status') == 'complete':
            add(9, 'task', t['pk'], 'audit', {'status': {'old': 'pending', 'new': 'complete'}})
    for m in materials:
        if m['fields'].get('consumption_state') == 'consumed':
            add(9, 'material', m['pk'], 'audit', {'consumption_state': {'old': 'pending', 'new': 'consumed'}})

    # 10  Job work complete + Shipments picked up
    if reached_work_complete:
        add(10, 'job', job_pk, 'action',
            {'status': {'old': 'in_progress', 'new': 'work_complete'}, '_action': 'Work completed'})
    for s in shipments:
        if s['fields'].get('status') == 'picked_up':
            add(10, 'shipment', s['pk'], 'action',
                {'status': {'old': 'prepared', 'new': 'picked_up'}, '_action': 'Picked up'})

    # 11  Invoices marked Sent
    for inv in invoices:
        if inv['fields'].get('status') in _INV_SENT:
            add(11, 'invoice', inv['pk'], 'action',
                {'status': {'old': 'draft', 'new': 'open'}, '_action': 'Sent to the customer'})
    # 12  Invoices marked Paid
    for inv in invoices:
        if inv['fields'].get('status') == 'paid':
            add(12, 'invoice', inv['pk'], 'action',
                {'status': {'old': 'open', 'new': 'paid'}, '_action': 'Paid in full'})

    # 13  Job completed
    if st == 'completed':
        add(13, 'job', job_pk, 'action',
            {'status': {'old': 'work_complete', 'new': 'completed'}, '_action': 'Job closed out'})

    return ev


def build_history(c):
    """Emit HistoryEntry rows for every history-tracked object, ordered to match
    the real job lifecycle.

    Mirrors apps/core/history.py: a ``_created`` audit entry when an object is
    first saved, plus the status transitions implied by its final status —
    ``action`` entries with an ``_action`` label for Job/Estimate/Invoice/
    Shipment moves, bare ``audit`` field diffs for Task/Material.

    Per Job, entries are laid out in causal order (job created -> estimate
    created -> deliverables -> estimate sent -> accepted/approved -> tasks &
    materials -> in progress -> shipments/invoices -> work complete -> invoice
    sent/paid -> completed; rejection lands after the estimate lapses, after any
    tasks). Timestamps are derived from the Job's ``created_date`` plus the phase
    ordinal — the order is what matters; the converter carries no per-transition
    dates. Objects with no Job (Contact, Business) get a single creation entry.

    Runs last, after every object has been built, so it can see them all.
    """
    from collections import defaultdict

    def emit(object_type, object_id, timestamp, entry_type, changes):
        c.add_fixture('core.historyentry', c.next_pk('core.historyentry'), {
            'entry_type': entry_type,
            'object_type': object_type,
            'object_id': object_id,
            'user': None,
            'timestamp': timestamp,
            'changes': changes,
            'text': '',
        })

    # Group tracked objects by Job; Contact/Business have no Job.
    jobs = {}
    by_job = defaultdict(lambda: defaultdict(list))
    no_job = []
    for f in c.fixture_data:
        model = f['model']
        if model not in _HISTORY_TRACKED_MODELS:
            continue
        if model == 'jobs.job':
            jobs[f['pk']] = f
        elif f['fields'].get('job') is not None:
            by_job[f['fields']['job']][model].append(f)
        else:
            no_job.append(f)

    # Job-less objects: a single creation entry.
    for f in no_job:
        emit(_HISTORY_TRACKED_MODELS[f['model']], f['pk'], _HISTORY_FALLBACK_DATE,
             'audit', {'_created': True})

    # Per-job causal timeline.
    for job_pk, job_f in jobs.items():
        base_str = job_f['fields'].get('created_date') or _HISTORY_FALLBACK_DATE
        base_dt = _parse_dt(base_str)
        events = sorted(_job_timeline(job_pk, job_f['fields'], by_job.get(job_pk, {})),
                        key=lambda e: e[0])
        prev_ord, intra = None, 0
        for ordinal, otype, oid, etype, changes in events:
            if ordinal != prev_ord:
                prev_ord, intra = ordinal, 0
            if base_dt is not None:
                ts = (base_dt + timedelta(days=ordinal, minutes=intra)).isoformat()
            else:
                ts = base_str
            emit(otype, oid, ts, etype, changes)
            intra += 1

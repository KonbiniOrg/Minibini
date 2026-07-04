"""Base fixture builders for the Neal's data converter.

Each builder function takes a NealsDataConverter instance as its first
argument and appends fixture records to c.fixture_data via c.add_fixture().
"""
import difflib
import json
import random
import re
import secrets
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from nealsdata.converter import parsing as P

# Material unit cost as a fraction of sell price, for materials not linked to a
# PriceListItem. Mirrors the PriceListItem purchase_price factor so linked and
# unlinked materials cost consistently.
_COST_RATIO = Decimal('0.8333')

# Usernames excluded from the blep-rotation pool.
_NON_ROTATION_USERNAMES = {'system'}

# Synthetic workday for blep/shift placement (UTC). Bleps are packed inside it.
_WORKDAY_START = time(8, 0)
_WORKDAY_END = time(16, 0)

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
        model = rec['model']
        fields = rec['fields']
        if model == 'core.user':
            # Seed users are written pk-less; assign explicit pks so Bleps/Shifts
            # (the first user FKs) and minted users reference them deterministically.
            pk = c.next_pk('core.user')
            rec['pk'] = pk
            username = fields.get('username')
            c.user_by_username[username] = pk
            if username not in _NON_ROTATION_USERNAMES and fields.get('is_active'):
                c.rotation_user_pks.append(pk)
            # Keep a worker record to clone (password hash + permissions) when
            # minting extra users for blep placement.
            if c._mint_template is None and username and username.startswith('worker'):
                c._mint_template = fields
        c.fixture_data.append(rec)
        if model == 'core.accountingcategory':
            c.ac_by_code[fields['code']] = rec.get('pk')
        elif model == 'jobs.ratescheme':
            c.scheme_by_name[fields['name']] = rec.get('pk')
            c.scheme_algorithm_by_pk[rec.get('pk')] = fields.get('algorithm')
            if isinstance(rec.get('pk'), int):
                max_rs_pk = max(max_rs_pk, rec['pk'])

    c.ac_svc_pk = c.ac_by_code.get('SVC')
    c.ac_mat_pk = c.ac_by_code.get('MTL')
    if max_rs_pk:
        c._pk_counters['jobs.ratescheme'] = max(
            c._pk_counters['jobs.ratescheme'], max_rs_pk)


def build_configuration(c):
    """Emit document-numbering + app-settings state.

    Both Configuration and AppState use the key field as primary key, so pk is
    the key string. Document-number *patterns* are user-settable Configuration;
    the *counters* are machine state in AppState (core migration 0018). Estimate
    numbering no longer uses this service, so it gets no sequence/counter keys.
    """
    config = [
        ('job_number_sequence',         'J{counter:04d}'),
        ('invoice_number_sequence',     'INV{counter:04d}'),
        ('po_number_sequence',          'PO{counter:04d}'),
        ('est_expire_days',             '30'),
        ('email_retention_days',        '30'),
        ('board_closed_retention_days', '5'),
        ('average_labor_cost',          '50'),
        # Default material markup: InventoryService.create_item derives an
        # item's selling_price from purchase_price × (1 + this/100). 20 => a
        # 20% markup over cost.
        ('default_material_markup_percent', '20'),
        # Default AC for a material line that supplies none — bare is_material
        # estimate lines and freeform materials. Read by
        # EstimateService._apply_material_ac_default (which RAISES if this key is
        # absent) and the SPA material forms. Points at MTL (the materials AC);
        # build_seed runs before this, so c.ac_mat_pk is set.
        ('default_material_accounting_category', str(c.ac_mat_pk)),
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


# Normalized source keys that must NOT fuzzy-merge onto a FreeAgent org. The
# one confirmed false positive in the near-miss survey: 'BWC Architects' is a
# distinct firm from 'HMC Architects' (0.86 similar). Extend as more surface.
_FORCE_DISTINCT = {P.normalize_name('BWC Architects')}

# Org fuzzy-match acceptance threshold. The near-miss survey confirmed every
# org pair at/above this is a real match (the only exception is force-distinct
# above); below it, names are treated as absent.
_ORG_FUZZY_THRESHOLD = 0.82


def _build_fa_indexes(c):
    """Index the FreeAgent Contacts sheet for resolve_contact.

    Businesses key off the `Organisation` column; individuals are Contacts-sheet
    rows with a *blank* Organisation (a person with no business — e.g. James
    Sandersfeld). Sets c.fa_org_by_norm / c.fa_org_display / c.fa_org_norms and
    c.fa_person_by_norm (all keyed by normalize_name; first row wins per key).
    """
    c.fa_org_by_norm = {}
    c.fa_org_display = {}
    c.fa_person_by_norm = {}
    for row in c.loader.sheets_data.get('Contacts', []):
        org = str(row.get('Organisation') or '').strip()
        if org:
            key = P.normalize_name(org)
            if key and key not in c.fa_org_by_norm:
                c.fa_org_by_norm[key] = row
                c.fa_org_display[key] = org
        else:
            full = (f"{str(row.get('First Name') or '').strip()} "
                    f"{str(row.get('Last Name') or '').strip()}").strip()
            key = P.normalize_name(full)
            if key and key not in c.fa_person_by_norm:
                c.fa_person_by_norm[key] = row
    c.fa_org_norms = sorted(c.fa_org_by_norm)


def resolve_contact(c, raw_name):
    """Resolve a noisy kanban/Bills org-or-person name to a canonical entity.

    Returns {'kind', 'key', 'display', 'fa_row'} or None for an empty name:
      kind    'business' | 'individual'
      key     dedup key — normalized canonical org, or 'person:<norm>'
      display business_name (org) or person full name
      fa_row  the matching Contacts-sheet row (real details) or None

    Order: exact/normalized org -> fuzzy org (>=threshold, unless force-distinct)
    -> exact/normalized person -> heuristic (person-shape => individual, else a
    new business). Persons match exactly only (no fuzzy) so two different people
    never merge.
    """
    name = str(raw_name or '').strip()
    nkey = P.normalize_name(name)
    if not nkey:
        return None

    # 1. org exact / normalized
    if nkey in c.fa_org_by_norm:
        return {'kind': 'business', 'key': nkey,
                'display': P.clean_display_name(c.fa_org_display[nkey]),
                'fa_row': c.fa_org_by_norm[nkey]}

    # 2. org fuzzy (skip confirmed false-positive sources)
    if nkey not in _FORCE_DISTINCT and c.fa_org_norms:
        best = max(c.fa_org_norms,
                   key=lambda k: difflib.SequenceMatcher(None, nkey, k).ratio())
        if (difflib.SequenceMatcher(None, nkey, best).ratio()
                >= _ORG_FUZZY_THRESHOLD):
            return {'kind': 'business', 'key': best,
                    'display': P.clean_display_name(c.fa_org_display[best]),
                    'fa_row': c.fa_org_by_norm[best]}

    # 3. person exact / normalized (blank-org FreeAgent individuals)
    if nkey in c.fa_person_by_norm:
        return {'kind': 'individual', 'key': f'person:{nkey}',
                'display': name, 'fa_row': c.fa_person_by_norm[nkey]}

    # 4. absent -> heuristic
    if P.looks_like_person(name):
        return {'kind': 'individual', 'key': f'person:{nkey}',
                'display': name, 'fa_row': None}
    return {'kind': 'business', 'key': nkey,
            'display': P.clean_display_name(name), 'fa_row': None}


def _emit_contact(c, business_pk, fa_row=None, fallback_name=None):
    """Emit one contacts.contact (business_pk may be None for an individual) and
    return its pk. Details come from a Contacts-sheet row when given, else the
    person name is synthesized from fallback_name. Emails/phones are anonymized."""
    if fa_row is not None:
        first = str(fa_row.get('First Name') or '').strip()
        last = str(fa_row.get('Last Name') or '').strip()
        email = str(fa_row.get('Email') or '').strip()
        work = str(fa_row.get('Phone Number') or '').strip()
        mobile = str(fa_row.get('Mobile Phone Number') or '').strip()
    else:
        first, last = P.split_name(fallback_name or '')
        email = work = mobile = ''
    if not first:
        first = '(unknown)'
    if not last:
        last = '(unknown)'

    contact_pk = c.next_pk('contacts.contact')
    email = (_anonymize_email(email) if email
             else f'noreply+{contact_pk}@example.com')
    work = _anonymize_phone(work) if work else ''
    mobile = _anonymize_phone(mobile) if mobile else ''
    if not work and not mobile:
        work = '555-555-5555'

    c.add_fixture('contacts.contact', contact_pk, {
        'first_name': first,
        'middle_initial': '',
        'last_name': last,
        'email': email,
        'addr1': '', 'addr2': '', 'addr3': '',
        'city': '', 'municipality': '', 'postal_code': '', 'country_code': '',
        'mobile_number': mobile[:20],
        'work_number': work[:20],
        'home_number': '',
        'business': business_pk,
        'qbo_customer_id': None,
    })
    return contact_pk


def _emit_individual(c, key, info):
    """Emit a standalone Contact (business=None) for an individual and register
    it in c.entity_map."""
    contact_pk = _emit_contact(c, None, fa_row=info['fa_row'],
                               fallback_name=info['display'])
    c.entity_map[key] = {'kind': 'individual', 'business': None,
                         'contact': contact_pk}
    return contact_pk


def _emit_business(c, key, info):
    """Emit a Business plus its Contacts and register it in c.entity_map.

    `info['persons']` maps normalized person name -> display name (the distinct
    kanban/Bills contact people named for this business). FreeAgent allows one
    contact per business but Minibini allows many, so every distinct person is
    attached as a Contact. default_contact is the FreeAgent representative when
    matched, else the first person, else synthesized from the business name.
    """
    business_pk = c.next_pk('contacts.business')
    contacts = {}            # normalized person name -> contact pk
    default_pk = None

    fa_row = info['fa_row']
    if fa_row is not None:
        default_pk = _emit_contact(c, business_pk, fa_row=fa_row)
        fa_full = (f"{str(fa_row.get('First Name') or '').strip()} "
                   f"{str(fa_row.get('Last Name') or '').strip()}").strip()
        fk = P.normalize_name(fa_full)
        if fk:
            contacts[fk] = default_pk

    for pnorm in sorted(info['persons']):
        if pnorm in contacts:
            continue
        pk = _emit_contact(c, business_pk, fallback_name=info['persons'][pnorm])
        contacts[pnorm] = pk
        if default_pk is None:
            default_pk = pk

    if default_pk is None:
        # No FreeAgent row and no named person — synthesize from the org name.
        default_pk = _emit_contact(c, business_pk, fallback_name=info['display'])

    c.add_fixture('contacts.business', business_pk, {
        'business_name': info['display'],
        'our_reference_code': f'BUS-{business_pk:04d}',
        'default_contact': default_pk,
        'business_address': '',
        'business_phone': '',
        'tax_exemption_number': '',
        'website': '',
        'terms': None,
        'tax_multiplier': None,
        'qbo_customer_id': None,
        'qbo_vendor_id': None,
    })
    c.entity_map[key] = {'kind': 'business', 'business': business_pk,
                         'default_contact': default_pk, 'contacts': contacts}
    return business_pk


def _customer_ref_for_entry(c, entry, projects_by_base, bill_orgs_by_base):
    """Return (org_name, person) for a spine entry: the customer org via
    Projects ('Client Organisation') -> Bills ('Contact Organisation') -> the
    parsed card Name, and the contact person from the card Name's parenthetical
    ('Business (Person)')."""
    base = entry['base_ref']
    card_name = entry['card'].get('Name', '')
    _biz, person = P.parse_kanban_name(card_name)

    proj_row = projects_by_base.get(base)
    if proj_row:
        org = (proj_row.get('Client Organisation') or '').strip()
        if org:
            return org, person
    bset = bill_orgs_by_base.get(base)
    if bset:
        return sorted(bset)[0], person          # deterministic pick
    biz, _ = P.parse_kanban_name(card_name)
    return (biz or '').strip(), person


def build_contacts_and_businesses(c):
    """Emit contacts.contact / contacts.business for the customers referenced by
    spine cards, matched against the canonical FreeAgent Contacts sheet.

    Each spine entry's customer org (Projects -> Bills -> card name) is resolved
    via resolve_contact, which folds noisy kanban spellings onto one canonical
    FreeAgent record (normalization + fuzzy) and tells individuals (blank-org
    persons) from businesses. Multiple kanban spellings of one org collapse to a
    single Business (Class B merge); the distinct contact-persons named across
    those cards all attach to it (Q1). Individuals become a Contact with no
    Business. Sets c.entity_map (key -> entity) and c.entry_contact (base_ref ->
    (key, person_norm)) so build_jobs links each Job to the right Contact.
    """
    _build_fa_indexes(c)

    projects_by_base = {}
    for row in c.loader.sheets_data.get('Projects', []):
        name = (row.get('Name') or '').strip()
        if name:
            projects_by_base[P.base_reference(name)] = row
    bill_orgs_by_base = {}
    for row in c.loader.sheets_data.get('Bills', []):
        proj = (row.get('Project') or '').strip()
        org = (row.get('Contact Organisation') or '').strip()
        if proj and org:
            bill_orgs_by_base.setdefault(P.base_reference(proj), set()).add(org)

    businesses = {}      # key -> {'display','fa_row','persons': {pnorm: display}}
    individuals = {}     # key -> {'display','fa_row'}
    c.entry_contact = {}

    for entry in c.spine:
        base = entry['base_ref']
        org_name, person = _customer_ref_for_entry(
            c, entry, projects_by_base, bill_orgs_by_base)
        res = resolve_contact(c, org_name)
        if res is None:
            c.entry_contact[base] = None
            continue
        pnorm = P.normalize_name(person) if person else None
        c.entry_contact[base] = (res['key'], pnorm)
        if res['kind'] == 'individual':
            individuals.setdefault(res['key'],
                                   {'display': res['display'],
                                    'fa_row': res['fa_row']})
        else:
            b = businesses.setdefault(
                res['key'], {'display': res['display'],
                             'fa_row': res['fa_row'], 'persons': {}})
            if person and pnorm:
                b['persons'].setdefault(pnorm, person.strip())

    c.entity_map = {}
    for key in sorted(individuals):
        _emit_individual(c, key, individuals[key])
    for key in sorted(businesses):
        _emit_business(c, key, businesses[key])


def build_vendors(c):
    """Emit Businesses/Contacts for the most recent vendors in the FreeAgent
    Bills sheet, capped at c.limit, reusing existing entities on canonical match.

    Vendors come *wholly* from the FreeAgent Bills sheet — the Kanban source has
    no concept of bills or vendors. Bill container rows carry a non-empty
    'Contact Organisation'; line-item rows (org blank) and name-only one-offs
    (Contact Name but no org) are skipped (count on c.vendor_skipped_name_only).
    Vendors rank by most recent bill 'Date' (newest first; undated last, ties by
    name); the first c.limit distinct orgs are selected (c.vendor_selected_orgs).

    Each selected org is resolved through resolve_contact (same canonicalization
    as customers). A vendor that resolves to an existing entity is reused; for an
    existing Business the bill's Contact Name is attached as another Contact if
    new. Runs after build_jobs so a vendor org can't be taken for a job's client.
    """
    latest_by_org = {}      # org -> most recent bill datetime (or None if undated)
    name_by_org = {}        # org -> first-seen bill Contact Name
    skipped_name_only = set()

    for row in c.loader.sheets_data.get('Bills', []):
        org = (row.get('Contact Organisation') or '').strip()
        if not org:
            name = (row.get('Contact Name') or '').strip()
            if name:
                skipped_name_only.add(name)
            continue
        dt = P.to_datetime(row.get('Date'))
        if org not in latest_by_org:
            latest_by_org[org] = dt
        elif dt is not None and (latest_by_org[org] is None
                                 or dt > latest_by_org[org]):
            latest_by_org[org] = dt
        if org not in name_by_org:
            cn = (row.get('Contact Name') or '').strip()
            if cn:
                name_by_org[org] = cn

    orgs = sorted(
        latest_by_org,
        key=lambda o: (latest_by_org[o] is None,
                       -latest_by_org[o].timestamp() if latest_by_org[o] else 0.0,
                       o))
    selected = orgs[:c.limit]
    c.vendor_selected_orgs = selected
    c.vendor_skipped_name_only = len(skipped_name_only)

    created = reused = 0
    for org in selected:
        res = resolve_contact(c, org)
        if res is None:
            continue
        key = res['key']
        person = name_by_org.get(org)
        ent = c.entity_map.get(key)
        if ent is None:
            if res['kind'] == 'individual':
                _emit_individual(c, key, {'display': res['display'],
                                          'fa_row': res['fa_row']})
            else:
                persons = {}
                if person:
                    persons[P.normalize_name(person)] = person.strip()
                _emit_business(c, key, {'display': res['display'],
                                        'fa_row': res['fa_row'],
                                        'persons': persons})
            created += 1
        else:
            reused += 1
            if ent['kind'] == 'business' and person:
                pnorm = P.normalize_name(person)
                if pnorm and pnorm not in ent['contacts']:
                    pk = _emit_contact(c, ent['business'],
                                       fallback_name=person.strip())
                    ent['contacts'][pnorm] = pk

    if c.verbose:
        print(f'  vendors: {len(selected)} selected (cap {c.limit}), '
              f'{created} new, {reused} reused; '
              f'{len(skipped_name_only)} name-only bill orgs skipped')


def build_jobs(c):
    """Emit jobs.job fixtures — one per spine entry.

    Sources:
    - Contact: the per-entry resolution recorded on c.entry_contact by
      build_contacts_and_businesses (canonical entity + named person). A Job for
      a business links to the Contact matching its card's named person, falling
      back to the business default_contact; an individual links to its Contact.
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

        # --- 1. Resolve contact from the per-entry resolution -------------
        resolved = c.entry_contact.get(base_ref)
        if not resolved:
            c.discarded_cards.append(
                f'{base_ref}: no resolvable customer org — skipped')
            continue
        key, person_norm = resolved
        ent = c.entity_map.get(key)
        if ent is None:
            c.discarded_cards.append(
                f'{base_ref}: entity {key!r} missing — skipped')
            continue
        if ent['kind'] == 'individual':
            contact_pk = ent['contact']
        else:
            contact_pk = ent['contacts'].get(person_norm) or ent['default_contact']

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

        # created_date: the job object exists a day before the earliest estimate
        # (the job is created, then its first estimate is drawn up). start_date
        # (set in reconcile) is the *latest* estimate's date, so created < start.
        container_dts = [P.to_datetime(r.get('Date'))
                         for r in container_rows]
        container_dts = [d for d in container_dts if d is not None]
        earliest_dt = min(container_dts) if container_dts else P.to_datetime(raw_date)
        if earliest_dt is not None:
            created_date = (earliest_dt - timedelta(days=1)).strftime(
                '%Y-%m-%dT00:00:00+00:00')
        else:
            created_date = f'{_FALLBACK_YEAR}-01-01T00:00:00+00:00'

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
            'created_date':       created_date,
            'start_date':         None,
            'due_date':           P.format_datetime(card.get('Due date')),
            'completed_date':     None,
            'customer_po_number': '',
            'description':        description,
            'accent_color':       accent_color,
            'hold_reason':        '',
            'project_manager':    None,   # set by assign_project_managers (non-draft)
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


# Description-word → canonical unit (must be a value in units_list). Checked
# most-specific first; whole-word / phrase match, case-insensitive. Single-letter
# units ('m', 'L') are intentionally omitted — too error-prone to detect in prose.
_UNIT_PATTERNS = [
    (r'\bsq(?:uare)?\.?\s*(?:ft|ft\.|feet|foot)\b|\bsqft\b', 'sq ft'),
    (r'\b(?:b(?:oar)?d)\.?\s*(?:ft|feet|foot)\b', 'bd ft'),
    (r'\b(?:lin(?:ear)?|ln)\.?\s*(?:ft|feet|foot)\b', 'ln ft'),
    (r'\bsheets?\b', 'sheets'),
    (r'\b(?:ft|feet|foot)\b', 'ft'),
    (r'\b(?:yards?|yds?)\b', 'yd'),
    (r'\b(?:gallons?|gal)\b', 'gal'),
    (r'\b(?:quarts?|qt)\b', 'qt'),
    (r'\b(?:pounds?|lbs?)\b', 'lbs'),
    (r'\b(?:kg|kilograms?)\b', 'kg'),
    (r'\b(?:hours?|hrs?)\b', 'hours'),
    (r'\bmin(?:ute)?s?\b', 'min'),
]


def _unit_from_description(description):
    """Pick a unit by scanning the description for a unit word; default 'ea'."""
    d = description.lower()
    for pattern, unit in _UNIT_PATTERNS:
        if re.search(pattern, d):
            return unit
    return 'ea'


def build_inventory_items(c):
    """Emit inventory.inventoryitem fixtures from the 'Price List Items' sheet.

    Skips rows with no Code value, deduplicates by code, and **excludes service
    items** — those whose code starts with a digit are dropped (a heuristic;
    other service items in the source can't be identified programmatically and
    still come through). Sets c.pli_map (code -> pk) for downstream builders.

    Units are inferred from the description (e.g. "sheets"), defaulting to 'ea'.
    All items use the Materials accounting category. A random ~10% are seeded
    with on-hand stock (1–10) and a separate ~10% with qty_sold (1–20); the
    per-code RNG keeps this deterministic across re-conversions.

    Sheet column headers (positional reference from spec):
      [0] Code, [1] Quantity, [2] Type, [3] Price, [4] Description
    """
    rows = c.loader.sheets_data.get('Price List Items', [])
    seen_codes = set()
    c.pli_map = {}
    c.pli_index = []                 # [{'code', 'description'}] for fuzzy matching
    c.pli_purchase_by_code = {}      # code -> purchase_price string
    c.pli_units_by_code = {}         # code -> units (description-inferred)

    for row in rows:
        # The sheet uses header names; try both the spec names and common
        # alternatives in case the actual header differs slightly.
        code = (row.get('Code') or row.get('Item Code') or '').strip()
        if not code:
            continue
        if code in seen_codes:
            continue
        # Service items: codes starting with a digit are not stock. (Others
        # exist but have no reliable programmatic signal — left as a known gap.)
        if code[0].isdigit():
            continue
        seen_codes.add(code)

        description = str(row.get('Description') or '').strip()
        price_raw = row.get('Price') or row.get('Sales Price') or 0
        sell = P.parse_decimal(price_raw).quantize(Decimal('0.01'))
        selling_price = f'{sell:.2f}'
        # Purchase price modelled as 83.33% of the listed sell price.
        purchase_price = f'{sell * Decimal("0.8333"):.2f}'

        # Deterministic-per-code seeding so re-conversions are stable.
        rng = random.Random(code)
        qty_on_hand = f'{rng.randint(1, 10)}.00' if rng.random() < 0.10 else '0.00'
        qty_sold = f'{rng.randint(1, 20)}.00' if rng.random() < 0.10 else '0.00'

        pk = c.next_pk('inventory.inventoryitem')
        c.add_fixture('inventory.inventoryitem', pk, {
            'code': code,
            'description': description,
            'units': _unit_from_description(description),
            'selling_price': selling_price,
            'purchase_price': purchase_price,
            'qty_on_hand': qty_on_hand,
            'qty_sold': qty_sold,
            'qty_wasted': '0.00',
            'is_active': True,
            'is_catalog': True,
            'accounting_category': c.ac_mat_pk,
        })
        c.pli_map[code] = pk
        c.pli_index.append({'code': code, 'description': description})
        c.pli_purchase_by_code[code] = purchase_price
        c.pli_units_by_code[code] = _unit_from_description(description)


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
                    'inventory_item':   None,
                    'line_number':       line_number,
                    'qty':               f'{qty:.2f}',
                    'units':             units,
                    'description':       description,
                    'price':             f'{price:.2f}',
                    # Every line needs an AC: source-backed lines (task/material/
                    # fee) carry it on their atom, but bare discount/credit
                    # ('lineitem') and deliverable lines never get a source, so
                    # emit a classification-matched default here (matches the AC
                    # the eventual atom would carry) — current code forbids a
                    # null-AC line item.
                    'accounting_category': (
                        c.ac_mat_pk if classification == 'material'
                        else c.ac_svc_pk
                    ),
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
    """Match a time/qty line's (algorithm, rate) to a seed RateScheme.

    Returns (scheme_pk, active_modifiers). Picks the nearest seed scheme of the
    given algorithm; when it is within ~10% of the line's rate that scheme wins,
    otherwise (or when no seed scheme of that algorithm exists) the default Shop
    labor scheme stands in. active_modifiers is always an empty list.

    Fixed charges no longer reach this function — they become jobs.Fee atoms
    (see _line_billing); only 'elapsed_time' / 'entered_qty' lines are matched.
    """
    candidates = [
        f for f in c.fixture_data
        if f['model'] == 'jobs.ratescheme'
        and f['fields'].get('algorithm') == algorithm
    ]
    if candidates:
        nearest = min(
            candidates,
            key=lambda f: abs(Decimal(f['fields']['rate']) - rate))
        near_rate = Decimal(nearest['fields']['rate'])
        tolerance = max(near_rate, Decimal('1')) / 10   # within ~10%
        if abs(near_rate - rate) <= tolerance:
            return nearest['pk'], []
    return _scheme_pk(c, _CHECKLIST_DEFAULT_SCHEME), []


def _line_billing(c, li):
    """Decide how a task-classified estimate line should bill.

    Returns one of:
      ('fee', None, None)              — a fixed charge → emit a jobs.Fee atom
      ('task', scheme_pk, modifiers)   — work → emit a Task with this RateScheme

    Keyword rule first (a 'cut'/'laser'/'cad' line is always work); otherwise the
    inferred billing shape decides. A line with no time/quantity signal is a fee.
    """
    keyword_name = P.checklist_scheme_name(li['description'])
    if keyword_name != _CHECKLIST_DEFAULT_SCHEME:
        return 'task', _scheme_pk(c, keyword_name), []
    algorithm = P.infer_algorithm(li['item_type'], li['units'])
    if algorithm == 'fee':
        return 'fee', None, None
    scheme_pk, modifiers = _match_seed_scheme(c, algorithm, li['price'])
    return 'task', scheme_pk, modifiers


# Leading verbs that mark a material-keyword line as labour/prep (a Task)
# rather than raw stock or a finished deliverable.
_LABOR_VERB_PREFIXES = ('prepare', 'apply', 'glue', 'engrave')


def _material_cost_and_pli(c, description, sell_price):
    """Resolve (unit_cost_str, inventory_item_pk, units) for a material line.

    Fuzzy-match the description to a PriceListItem (keyword + thickness). On a
    match, link the FK, take the PLI's purchase_price as unit_cost, and carry
    the PLI's units (fixtures bypass Material.save(), so _populate_from_pli
    never runs — the converter must copy the units itself). On a miss, leave
    the FK null, derive unit_cost from the sell price via _COST_RATIO, and
    return units=None for the caller to infer.
    """
    code = P.match_pli(description, getattr(c, 'pli_index', []))
    if code:
        pli_pk = c.pli_map.get(code)
        purchase = c.pli_purchase_by_code.get(code)
        if pli_pk is not None and purchase is not None:
            return purchase, pli_pk, c.pli_units_by_code.get(code)
    unit_cost = (sell_price * _COST_RATIO).quantize(Decimal('0.01'))
    return f'{unit_cost:.2f}', None, None


# Mirrors the converter's default_material_markup_percent config (20%): a minted
# transient lot's selling_price = purchase_price × this factor.
_MATERIAL_MARKUP_FACTOR = Decimal('1.20')


def _mint_transient_lot(c, description, units, purchase_cost):
    """Create a transient-lot InventoryItem (is_catalog=False) to back a Material
    that matched no catalog item, and return its pk. Selling price derives from
    the purchase cost via the configured material markup. QOH starts at 0 and is
    reconciled later by build_purchasing."""
    pk = c.next_pk('inventory.inventoryitem')
    purchase = Decimal(purchase_cost)
    selling = (purchase * _MATERIAL_MARKUP_FACTOR).quantize(Decimal('0.01'))
    c.add_fixture('inventory.inventoryitem', pk, {
        'code': f'LOT-{pk:05d}',
        'description': (description or 'Material')[:255],
        'units': units or 'none',
        'selling_price': f'{selling:.2f}',
        'purchase_price': f'{purchase:.2f}',
        'qty_on_hand': '0.00',
        'qty_sold': '0.00',
        'qty_wasted': '0.00',
        'is_active': True,
        'is_catalog': False,
        'accounting_category': c.ac_mat_pk,
    })
    return pk


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
            'sort_order':       sort_order,
        })
        if not item['is_subtask']:
            last_toplevel_pk = task_pk
        if base_ref not in c.cut_task and 'cut' in name.lower():
            c.cut_task[base_ref] = task_pk
    return sort_order


def _emit_fee(c, base_ref, job_pk, li, sort_order, task_pk=None):
    """Emit a jobs.fee atom for a fixed-charge estimate line, plus the
    EstimateLineItemSource claiming it (source_type='fee'). Returns the fee pk.

    quantity comes from the line qty (>0) or defaults to 1; unit_rate is the
    line price; the fee carries the services AccountingCategory.

    A non-positive price emits nothing (returns None): validate_data requires
    Fee.unit_rate > 0, and a $0 fixed charge carries no billing information —
    the estimate line itself is kept, just unclaimed.
    """
    if not li['price'] or li['price'] <= 0:
        print(f"  fee skipped (non-positive price {li['price']}): "
              f"{(li['description'] or '')[:60]!r}")
        return None
    qty = li['qty'] if (li['qty'] and li['qty'] > 0) else Decimal('1')
    fee_pk = c.next_pk('jobs.fee')
    c.add_fixture('jobs.fee', fee_pk, {
        'job':                 job_pk,
        'task':                task_pk,
        'description':         (li['description'] or '')[:255],
        'quantity':            f'{qty:.2f}',
        'unit_rate':           f"{li['price']:.2f}",
        'accounting_category': c.ac_svc_pk,
        'sort_order':          sort_order,
    })
    _emit_estimate_line_item_source(c, li['line_item_pk'], 'fee', fee_pk)
    return fee_pk


def _build_line_item_tasks(c, base_ref, job_pk, task_lines, start_sort=0):
    """Emit jobs.task / jobs.fee fixtures from estimate line items.

    Used for the no-checklist fallback (task-classified lines) and for
    material-keyword lines reclassified as labour. A line that bills as a fixed
    charge becomes a jobs.Fee (claimed via an EstimateLineItemSource); every
    other line becomes a Task. Returns the final per-job sort_order.
    """
    sort_order = start_sort
    for li in task_lines:
        sort_order += 1
        kind, scheme_pk, active_modifiers = _line_billing(c, li)
        if kind == 'fee':
            _emit_fee(c, base_ref, job_pk, li, sort_order)
            continue
        name = (li['description'] or 'Task')[:255] or 'Task'
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
            'sort_order':       sort_order,
        })
        if base_ref not in c.cut_task and 'cut' in name.lower():
            c.cut_task[base_ref] = task_pk
    return sort_order


def assign_worker_times(c):
    """Give every Task an invented per-task estimated worker time.

    The Kanban data carries no trustworthy per-task time signal (the old
    est *cut*/ASS columns were rare, whole-job estimates wrongly stamped onto a
    single task), so each task gets an independent random estimate uniform in
    [0.5, 4.0] hours, rounded to 2 significant figures and stored at minute
    granularity. Iterates in pk order with the seeded RNG so output is
    deterministic.
    """
    tasks = sorted(
        (f for f in c.fixture_data if f['model'] == 'jobs.task'),
        key=lambda f: f['pk'],
    )
    for f in tasks:
        hours = P.round_2sig(random.uniform(0.5, 4.0))
        f['fields']['est_worker_time'] = P.hours_to_duration(hours)


def assign_project_managers(c):
    """Assign a random project_manager to every Job beyond draft state.

    Runs after reconcile so the *final* job status decides eligibility (a draft
    job can become rejected via the expiry pass). The PM is drawn from the seed
    rotation pool (`c.rotation_user_pks`, excludes `system` and minted workers);
    draft jobs keep a null PM. Iterates in pk order with the seeded RNG.
    """
    pool = list(c.rotation_user_pks)
    if not pool:
        return
    jobs = sorted((f for f in c.fixture_data if f['model'] == 'jobs.job'),
                  key=lambda f: f['pk'])
    for f in jobs:
        if f['fields'].get('status') == 'draft':
            continue
        f['fields']['project_manager'] = random.choice(pool)


def _duration_hours(duration_str):
    """Whole hours (Decimal, 2dp) of a 'HH:MM:SS' duration. Minute-floored
    durations divide cleanly. Defaults to 1.0 when unparseable."""
    td = P.parse_duration(duration_str)
    if td is None:
        return Decimal('1.00')
    return (Decimal(int(td.total_seconds())) / Decimal(3600)).quantize(Decimal('0.01'))


def assign_est_quantities(c):
    """Fill est_qty on real Tasks via a per-rate-scheme heuristic.

    Runs after assign_worker_times (it reads est_worker_time). est_qty is
    optional on Task at the DB + app layer, but the dataset wants it populated:

    - elapsed_time (hourly): est_qty == the worker-time estimate in hours, so
      estimated billable hours match the estimated worker time. Set always
      (overrides any source-line qty).
    - entered_qty: a piece count tied to the worker time (longer task → more
      pieces, 2–6 pieces/hour), unless a source line already set one.

    Fixed charges are now jobs.Fee atoms (not Tasks), so no flat-fee case
    remains here.
    """
    for f in c.fixture_data:
        if f['model'] != 'jobs.task':
            continue
        fields = f['fields']
        algo = c.scheme_algorithm_by_pk.get(fields.get('rate_scheme'))
        if algo == 'elapsed_time':
            fields['est_qty'] = f'{_duration_hours(fields.get("est_worker_time")):.2f}'
        elif algo == 'entered_qty':
            if fields.get('est_qty') in (None, ''):
                hours = _duration_hours(fields.get('est_worker_time'))
                pieces = max(1, round(float(hours) * random.randint(2, 6)))
                fields['est_qty'] = f'{Decimal(pieces):.2f}'


def _emit_estimate_line_item_source(c, li_pk, source_type, source_pk):
    """Emit an estimates.estimatelineitemsource row claiming a job atom.

    source_type is one of 'task' / 'material' / 'fee'. Each atom can be claimed
    by at most one line item (model enforces unique_together on
    (source_type, source_pk)); the converter never double-claims an atom.
    """
    src_pk = c.next_pk('estimates.estimatelineitemsource')
    c.add_fixture('estimates.estimatelineitemsource', src_pk, {
        'estimate_line_item': li_pk,
        'source_type':        source_type,
        'source_pk':          source_pk,
    })


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
    """Derive Task, Material, Fee, and Deliverable fixtures for each job.

    Atoms now live directly on the Job for **every** status (draft included) —
    there is no plan layer. Per job:

    - **Tasks** come from the Kanban card's Checklist when it has any items
      (each line -> a Task; indented lines -> subtasks; [X] -> complete);
      otherwise task-classified estimate line items become Tasks (or Fees, see
      below). Checklist tasks keep their subtask hierarchy and [X]/[ ] status.
    - **Fees**: a task-classified estimate line that bills as a fixed charge
      (no time/quantity signal) becomes a jobs.Fee instead of a Task, claimed by
      its source line via an EstimateLineItemSource (source_type='fee').
    - **Materials** come from material-classified lines split by
      _material_line_kind: raw stock -> Material, labour/prep -> Task, finished
      goods -> Deliverable. Each line becomes exactly one of those.
    - **Deliverables** go on the Job; a job with no deliverable line gets a
      synthetic 'Fake Deliverable'.

    Mutates c.fixture_data, c.cut_task, c.fake_deliverable_count.
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

        # --- 1. Tasks/Fees: checklist (or fallback line items), plus labour.
        if checklist_items:
            sort_order = _build_checklist_tasks(
                c, base_ref, job_pk, checklist_items)
        else:
            sort_order = _build_line_item_tasks(
                c, base_ref, job_pk, task_lines)
        # Material-keyword lines that are really labour become Tasks too.
        _build_line_item_tasks(c, base_ref, job_pk, labor_lines, sort_order)

        # Worker times are assigned in a separate pass (assign_worker_times)
        # after every task exists.

        # --- 2. Materials: raw stock only (after tasks so cut_task is set) --
        for li in raw_lines:
            mat_pk = c.next_pk('inventory.material')
            unit_cost, pli_pk, pli_units = _material_cost_and_pli(
                c, li['description'] or '', li['price'])
            # FreeAgent line items carry no unit signal for material lines
            # (resolve_li_units_and_qty only ever yields hours/none), so
            # resolve real units here: the matched catalog item's, else the
            # same description inference catalog items get. The minted lot
            # gets the SAME units so material↔item unit checks (consume,
            # merge) hold.
            units = li['units'] if li['units'] not in (None, '', 'none') else None
            if units is None:
                units = pli_units or _unit_from_description(li['description'] or '')
            if pli_pk is None:
                # No catalog match — mint a transient lot so every Material is
                # item-backed (uniform earmark/QOH/consumption handling).
                pli_pk = _mint_transient_lot(
                    c, li['description'] or '', units, unit_cost)
            c.add_fixture('inventory.material', mat_pk, {
                'job':                 job_pk,
                'task':                c.cut_task.get(base_ref),
                'description':         (li['description'] or '')[:255],
                'quantity':            f"{li['qty']:.2f}",
                'units':               units,
                'unit_cost':           unit_cost,
                'sell_price':          f"{li['price']:.2f}",
                'accounting_category': c.ac_mat_pk,
                'inventory_item':     pli_pk,
                'consumption_state':   'pending',
                'released_qty':       '0.00',
                'po_line_item':        None,
            })

        # --- 3. Deliverables: finished-good lines (or a Fake Deliverable) --
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
        # A sent (open) or paid invoice has been sent to the customer; stamp the
        # send date with the FreeAgent invoice Date. Draft invoices must stay
        # null-dated (model invariant). Paid invoices also record the amount paid
        # (no QBO here, so the invoice's own line-item total stands in).
        sent_date = created_date if status in ('open', 'paid') else None

        inv_pk = c.next_pk('invoicing.invoice')
        inv_fields = {
            'job':                  job_pk,
            'invoice_number':       ref_str,
            'status':               status,
            'created_date':         created_date,
            'sent_date':            sent_date,
            'closed_date':          closed_date,
            'qbo_id':               None,
            'qbo_payment_status':   '',
            'qbo_amount_paid':      None,
        }
        c.add_fixture('invoicing.invoice', inv_pk, inv_fields)

        # Emit line items
        line_number = 0
        job_li_total = c.invoice_totals.get(base_ref, Decimal('0'))
        inv_total = Decimal('0')   # this invoice's own line total (for paid amount)

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
                'inventory_item':     None,
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
            inv_total += qty * price

        c.invoice_totals[base_ref] = job_li_total
        if status == 'paid':
            inv_fields['qbo_amount_paid'] = f'{inv_total.quantize(Decimal("0.01")):.2f}'


def build_synthetic_estimate_sources(c):
    """Test-data synthesis: round-robin assign each job's unclaimed Tasks as
    sources of that job's (non-adjustment) estimate line items, so the Client
    View projects atoms even though the kanban work and FreeAgent charge lines
    don't really correspond. Each Task claims at most one estimate line (model
    unique_together); extra Tasks group onto lines, surplus/adjustment lines
    stay sourceless.

    Fee atoms are already claimed by their own source lines in derive_atoms
    (source_type='fee'); this pass only places Tasks, and it skips Tasks already
    claimed and estimate lines that already carry a source (so a line that owns
    a Fee isn't double-sourced with a Task).
    """
    claimed_tasks = {
        f['fields']['source_pk']
        for f in c.fixture_data
        if f['model'] == 'estimates.estimatelineitemsource'
        and f['fields'].get('source_type') == 'task'
    }
    sourced_lines = {
        f['fields']['estimate_line_item']
        for f in c.fixture_data
        if f['model'] == 'estimates.estimatelineitemsource'
    }
    tasks_by_job = {}
    for f in c.fixture_data:
        if f['model'] == 'jobs.task' and f['pk'] not in claimed_tasks:
            tasks_by_job.setdefault(f['fields']['job'], []).append(f)

    est_to_job = {
        f['pk']: f['fields']['job']
        for f in c.fixture_data if f['model'] == 'estimates.estimate'
    }
    lines_by_job = {}
    for f in c.fixture_data:
        if f['model'] != 'estimates.estimatelineitem':
            continue
        if f['pk'] in sourced_lines:
            continue  # already owns an atom (e.g. a Fee) — don't double-source
        job_pk = est_to_job.get(f['fields']['estimate'])
        if job_pk is not None:
            lines_by_job.setdefault(job_pk, []).append(f)

    for job_pk, tasks in tasks_by_job.items():
        lines = lines_by_job.get(job_pk)
        if not lines:
            continue
        lines = sorted(lines, key=lambda f: (
            f['fields'].get('estimate'), f['fields'].get('line_number') or 0))
        for i, t in enumerate(sorted(tasks, key=lambda f: f['pk'])):
            li = lines[i % len(lines)]
            _emit_estimate_line_item_source(c, li['pk'], 'task', t['pk'])


def build_invoice_line_item_sources(c):
    """Emit invoicing.invoicelineitemsource rows linking InvoiceLineItems to
    Tasks / Fees / Materials on the Job.

    Schema permits freeform invoice lines (no source); the wiring is purely
    cosmetic — it makes Tasks/Fees/Materials show as 'billed' on a paid Job in
    the UI instead of orphaned. Heuristic, deterministic claim:

      - For each Invoice on each Job (invoice pk asc → invoice line_number asc)
      - Classify the line via P.classify_line_item.
      - If classification is 'task': claim the next unclaimed Task on the Job;
        fall through to Fees, then Materials, if exhausted.
      - If classification is 'material': claim the next unclaimed Material;
        fall through to Tasks, then Fees, if exhausted.
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
    fees_by_job = {}
    for f in c.fixture_data:
        if f['model'] == 'jobs.fee':
            fees_by_job.setdefault(f['fields']['job'], []).append(f['pk'])

    claimed_tasks = set()
    claimed_materials = set()
    claimed_fees = set()

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
        fee_pool = sorted(fees_by_job.get(job_pk, []))
        invs = sorted(invoices_by_job[job_pk], key=lambda f: f['pk'])
        for inv in invs:
            # Draft invoices are seeded empty in the app (the user picks
            # "Apply everything" / "Copy from estimate"); don't pre-claim atoms
            # onto a draft's lines.
            if inv['fields'].get('status') == 'draft':
                continue
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
                        src_pk = _claim(fee_pool, claimed_fees)
                        src_type = 'fee'
                    if src_pk is None:
                        src_pk = _claim(material_pool, claimed_materials)
                        src_type = 'material'
                elif kind == 'material':
                    src_pk = _claim(material_pool, claimed_materials)
                    src_type = 'material'
                    if src_pk is None:
                        src_pk = _claim(task_pool, claimed_tasks)
                        src_type = 'task'
                    if src_pk is None:
                        src_pk = _claim(fee_pool, claimed_fees)
                        src_type = 'fee'
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


# --- Bleps, Shifts, and entered_qty actuals ---------------------------------

# Reused password hash + permission natural keys for minted workers (filled from
# a seed worker in build_seed; a safe fallback keeps the builder importable).
_MINT_FALLBACK_PASSWORD = (
    'pbkdf2_sha256$1000000$mintplaceholderxxxxxxx$'
    'mintplaceholderhashbase64valuexxxxxxxxxxxxxx=')


def _aware(dt_str):
    """Parse a fixture datetime string into an aware UTC datetime, or None."""
    if not isinstance(dt_str, str) or not dt_str:
        return None
    try:
        d = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def _dataset_now(c):
    """Newest real datetime in the dataset — the upper clamp for blep times.

    Max over job created/start/completed dates and invoice created dates, so an
    in_progress / work_complete job (no completed_date) never gets a future blep.
    """
    newest = None
    for f in c.fixture_data:
        fields = f['fields']
        if f['model'] == 'jobs.job':
            cands = (fields.get('created_date'), fields.get('start_date'),
                     fields.get('completed_date'))
        elif f['model'] == 'invoicing.invoice':
            cands = (fields.get('created_date'),)
        else:
            continue
        for s in cands:
            d = _aware(s)
            if d is not None and (newest is None or d > newest):
                newest = d
    return newest or datetime(_FALLBACK_YEAR, 12, 31, tzinfo=timezone.utc)


def _mint_user(c):
    """Create a new worker user for blep overflow; return its pk.

    Modeled on the seed workers: active, non-staff, can_manage_time. Username is
    the next free worker{N}. The password hash + permissions are cloned from a
    seed worker so the row is a valid, loadable User.
    """
    template = c._mint_template or {}
    password = template.get('password') or _MINT_FALLBACK_PASSWORD
    perms = template.get('user_permissions') or [['can_manage_time', 'core', 'user']]

    n = getattr(c, '_mint_seq', 1)
    while True:
        n += 1
        username = f'worker{n}'
        if username not in c.user_by_username:
            break
    c._mint_seq = n

    pk = c.next_pk('core.user')
    c.add_fixture('core.user', pk, {
        'password':       password,
        'last_login':     None,
        'is_superuser':   False,
        'username':       username,
        'first_name':     username.capitalize(),
        'last_name':      'Worker',
        'email':          f'{username}@example.com',
        'is_staff':       False,
        'is_active':      True,
        'date_joined':    f'{_FALLBACK_YEAR}-01-01T00:00:00+00:00',
        'contact':        None,
        'groups':         [],
        'user_permissions': [list(p) for p in perms],
    })
    c.user_by_username[username] = pk
    return pk


def _earliest_slot(intervals, lower, eff_upper, length):
    """Earliest (start, end) for a blep of ``length`` inside [lower, eff_upper].

    Searches calendar days from lower forward; on each day the usable window is
    the 08:00–16:00 workday intersected with [lower, eff_upper]. Returns the
    earliest gap (vs the user's existing ``intervals``) that fits, or None.
    """
    day = lower.date()
    last = eff_upper.date()
    while day <= last:
        ws = max(datetime.combine(day, _WORKDAY_START, tzinfo=timezone.utc), lower)
        we = min(datetime.combine(day, _WORKDAY_END, tzinfo=timezone.utc), eff_upper)
        if we - ws >= length:
            day_ivs = sorted((iv for iv in intervals if iv[1] > ws and iv[0] < we),
                             key=lambda iv: iv[0])
            cursor = ws
            for s, e in day_ivs:
                if s - cursor >= length:
                    return (cursor, cursor + length)
                if e > cursor:
                    cursor = e
            if we - cursor >= length:
                return (cursor, cursor + length)
        day += timedelta(days=1)
    return None


def _place_blep(c, rotation, rot_idx, schedules, lower, eff_upper, length):
    """Pick a user and slot for one blep, satisfying job-window + no-overlap.

    Tries rotation users starting at the pointer; the first with a free slot in
    the window takes it. If none is free, mints a new user (who, with an empty
    schedule, always fits on the window's first workday). Records the interval on
    the chosen user's schedule and advances the pointer. Returns (user_pk, start,
    end).
    """
    n = len(rotation)
    for k in range(n):
        user_pk = rotation[(rot_idx[0] + k) % n]
        slot = _earliest_slot(schedules[user_pk], lower, eff_upper, length)
        if slot is not None:
            schedules[user_pk].append(slot)
            rot_idx[0] = (rot_idx[0] + k + 1) % n
            return user_pk, slot[0], slot[1]

    # Everyone booked across the window: mint a fresh worker.
    user_pk = _mint_user(c)
    rotation.append(user_pk)
    slot = _earliest_slot(schedules[user_pk], lower, eff_upper, length)
    if slot is None:
        # Defensive: an empty schedule on the window's first workday always fits,
        # but guard anyway so a degenerate window can't crash the build.
        start = max(datetime.combine(lower.date(), _WORKDAY_START,
                                     tzinfo=timezone.utc), lower)
        slot = (start, start + length)
    schedules[user_pk].append(slot)
    rot_idx[0] = 0
    return user_pk, slot[0], slot[1]


def build_bleps_and_shifts(c):
    """Emit a Blep for every complete Task, the Shifts that enclose them, and
    actual_qty for complete entered_qty tasks.

    Placement satisfies two invariants at once: each blep falls inside its job's
    active window, and no user's bleps overlap. Each (user, day) with bleps gets
    one Shift tightly enclosing that day's bleps (so the shift↔blep enclosure
    invariant holds). Runs after reconcile (final task statuses + job dates).
    """
    now = _dataset_now(c)
    job_by_pk = {f['pk']: f['fields']
                 for f in c.fixture_data if f['model'] == 'jobs.job'}

    complete = [f for f in c.fixture_data
                if f['model'] == 'jobs.task'
                and f['fields'].get('status') == 'complete']
    complete.sort(key=lambda f: (f['fields']['job'],
                                 f['fields'].get('sort_order') or 0, f['pk']))

    rotation = list(c.rotation_user_pks)
    if not rotation:                       # no seed users (degenerate) → mint one
        rotation.append(_mint_user(c))
    rot_idx = [0]
    schedules = defaultdict(list)          # user_pk -> [(start, end), ...]

    def _window(tf):
        """A complete task's blep window [lower, eff_upper], clamped to `now`.

        A finished job (has a completed_date) ends when it completed. An
        unfinished/current job (no completed_date — in_progress, work_complete,
        on_hold) has ongoing work, so its window runs to `now`. That keeps
        eff_upper >= horizon, so a complete Task on a current job is never skipped
        by the horizon below — it always gets a supporting blep."""
        job = job_by_pk.get(tf['fields']['job'], {})
        lower = (_aware(job.get('start_date'))
                 or _aware(job.get('created_date'))
                 or now - timedelta(days=1))
        completed = _aware(job.get('completed_date'))
        upper = completed if completed is not None else now
        lower = min(lower, now)
        # Window must allow at least one workday; expand a collapsed window to the
        # lower day's workday end, then clamp to now.
        day_end = datetime.combine(lower.date(), _WORKDAY_END, tzinfo=timezone.utc)
        return lower, min(now, max(upper, day_end))

    # Three-week horizon: keep the dataset's time-tracking recent, anchored to the
    # dataset's "now". Finished work older than this is dropped (those jobs are out
    # of scope). Unfinished jobs always fall inside the window because their window
    # upper is `now` (see _window) — so their complete Tasks are never orphaned.
    horizon = now - timedelta(weeks=3)

    for counter, tf in enumerate(complete):
        fields = tf['fields']

        # entered_qty complete tasks bill on actual_qty (no bleps drive it), so
        # invent one with the thirds rule vs est_qty (fallback base 1). Set for
        # EVERY complete task — even an old finished one too old to get a blep
        # (the horizon skip below) — so nothing can invoice at zero.
        if c.scheme_algorithm_by_pk.get(fields.get('rate_scheme')) == 'entered_qty':
            base = (Decimal(fields['est_qty'])
                    if fields.get('est_qty') not in (None, '') else Decimal('1'))
            actual = (base * P.thirds_factor(counter)).quantize(Decimal('0.01'))
            fields['actual_qty'] = f'{actual:.2f}'

        lower, eff_upper = _window(tf)

        # A FINISHED job whose work ended more than three weeks ago gets no blep
        # (out of scope). Unfinished jobs never hit this (eff_upper == now). A
        # survivor that *started* before the horizon is clamped into the window.
        if eff_upper < horizon:
            continue
        lower = max(lower, horizon)

        # Blep length: est_worker_time × thirds factor, floored to whole minutes
        # (≥ 1 minute).
        ewt = P.parse_duration(fields.get('est_worker_time')) or timedelta(hours=1)
        raw = ewt * float(P.thirds_factor(counter))
        minutes = max(1, int(raw.total_seconds() // 60))
        length = timedelta(minutes=minutes)

        user_pk, start, end = _place_blep(
            c, rotation, rot_idx, schedules, lower, eff_upper, length)

        # The worker who logged time on the task is its assignee.
        fields['assignee'] = user_pk

        blep_pk = c.next_pk('jobs.blep')
        c.add_fixture('jobs.blep', blep_pk, {
            'user':       user_pk,
            'task':       tf['pk'],
            'start_time': start.strftime('%Y-%m-%dT%H:%M:00+00:00'),
            'end_time':   end.strftime('%Y-%m-%dT%H:%M:00+00:00'),
        })

    # One Shift per (user, calendar day), tightly enclosing that day's bleps.
    for user_pk, intervals in schedules.items():
        by_day = defaultdict(list)
        for s, e in intervals:
            by_day[s.date()].append((s, e))
        for day in sorted(by_day):
            ivs = by_day[day]
            shift_pk = c.next_pk('core.shift')
            c.add_fixture('core.shift', shift_pk, {
                'user':       user_pk,
                'start_time': min(s for s, _ in ivs).strftime('%Y-%m-%dT%H:%M:00+00:00'),
                'end_time':   max(e for _, e in ivs).strftime('%Y-%m-%dT%H:%M:00+00:00'),
            })


# Up to this many assigned-but-unstarted Tasks per worker (assign_current_work).
_MAX_QUEUED_TASKS_PER_WORKER = 3


def assign_current_work(c):
    """Give each worker a few assigned-but-unstarted Tasks so the job board and
    schedule show current work.

    build_bleps_and_shifts only assigns the worker who logged time on a
    *complete* Task, so pending work carries no assignee and never reaches a
    worker's queue. This pass hands each rotation worker up to
    `_MAX_QUEUED_TASKS_PER_WORKER` random **pending** Tasks drawn from
    **in_progress** Jobs (the current work), setting `assignee` and a per-worker
    `worker_queue` position. Tasks stay pending — assigned, not yet started — so
    they render as forecast bars on the schedule (ScheduleService includes
    pending assigned tasks) and as queued cards on the board.

    Only Tasks with an `est_worker_time` are eligible (Task.clean() requires it
    on an assigned Task). Workers come from `c.rotation_user_pks` (excludes
    `system` and minted blep-overflow users). Deterministic given the seeded RNG;
    runs after reconcile (needs final job/task status) and after
    build_bleps_and_shifts (so completed work is already assigned).
    """
    pool = list(c.rotation_user_pks)
    if not pool:
        return

    in_progress_jobs = {
        f['pk'] for f in c.fixture_data
        if f['model'] == 'jobs.job' and f['fields'].get('status') == 'in_progress'
    }
    candidates = sorted(
        (f for f in c.fixture_data
         if f['model'] == 'jobs.task'
         and f['fields'].get('job') in in_progress_jobs
         and f['fields'].get('status') == 'pending'
         and f['fields'].get('assignee') is None
         and f['fields'].get('est_worker_time')),
        key=lambda f: f['pk'],
    )
    random.shuffle(candidates)

    # Round-robin so the queue spreads across workers before any one fills up.
    idx = 0
    for position in range(_MAX_QUEUED_TASKS_PER_WORKER):
        for worker_pk in pool:
            if idx >= len(candidates):
                return
            fields = candidates[idx]['fields']
            fields['assignee'] = worker_pk
            fields['worker_queue'] = position
            idx += 1


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

# History is partitioned by domain (see apps/core/history.record_history): the
# object_type picks the table. The converter only emits job-domain and CRM rows.
_HISTORY_TABLE = {
    'job': 'core.jobhistory', 'task': 'core.jobhistory', 'estimate': 'core.jobhistory',
    'changeorder': 'core.jobhistory', 'invoice': 'core.jobhistory',
    'material': 'core.jobhistory', 'deliverable': 'core.jobhistory',
    'shipment': 'core.jobhistory',
    'contact': 'core.crmhistory', 'business': 'core.crmhistory',
    'purchaseorder': 'core.purchasinghistory', 'bill': 'core.purchasinghistory',
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


# Job statuses that hold no inventory reservation (earmarks released) and,
# for task-less materials, imply the work happened (consumed).
_TERMINAL_JOB_STATUSES = {'work_complete', 'completed', 'cancelled', 'rejected'}
_WORKED_JOB_STATUSES = {'in_progress', 'work_complete', 'completed'}


def build_purchasing(c):
    """Reconcile material consumption + inventory state and synthesize POs/Bills.

    Runs after reconcile (needs FINAL job/task statuses) and before build_history
    (which narrates consumption from each Material's consumption_state). Three
    coordinated effects on the real (Material) side — PlanMaterials are untouched:

    1. **Consumption** (task-driven, universal): a Material is consumed iff its
       work happened — a task-attached Material when its Task is complete, a
       task-less Material when its Job reached in_progress/work_complete/completed.
       Consumed Materials are assumed acquired: net-zero QOH, qty_sold += qty,
       whether or not a Bill is found.
    2. **Earmarks + QOH**: a pending Material holds an Earmark (per item+job) while
       the Job is active (none on terminal jobs / on consume). A pending Material
       on a bill-matched Job is treated as received (qty_on_hand += qty).
    3. **PO/Bill synthesis**: a Job whose estimate base appears in a Bill's
       Comments (precision-biased: Comments only, job must exist and have
       Materials) gets a received_in_full PO to that Bill's vendor carrying all
       the Job's Materials (Material.po_line_item set) plus the linked Bill.
       First matched bill/vendor wins per Job; the vendor business is created if
       it wasn't among the imported vendors.
    """
    job_status = {f['pk']: f['fields']['status']
                  for f in c.fixture_data if f['model'] == 'jobs.job'}
    job_created = {f['pk']: f['fields'].get('created_date')
                   for f in c.fixture_data if f['model'] == 'jobs.job'}
    task_status = {f['pk']: f['fields']['status']
                   for f in c.fixture_data if f['model'] == 'jobs.task'}
    items = {f['pk']: f['fields']
             for f in c.fixture_data if f['model'] == 'inventory.inventoryitem'}

    materials_by_job = defaultdict(list)
    for f in c.fixture_data:
        if f['model'] == 'inventory.material':
            materials_by_job[f['fields']['job']].append(f['fields'])

    base_by_jobpk = {jp: base for base, jp in c.job_map.items()}

    # --- bill matching (Comments only, precision-biased) -------------------
    bases_with_materials = {base_by_jobpk[jp] for jp in materials_by_job
                            if jp in base_by_jobpk}
    bill_for_base = {}        # base -> {'org','date','ref'}; first match wins
    for row in c.loader.sheets_data.get('Bills', []):
        org = (row.get('Contact Organisation') or '').strip()
        if not org:
            continue
        cands = set()
        for m in re.findall(r'\d{4,5}', str(row.get('Comments') or '')):
            cands |= {m, m.zfill(5), m.lstrip('0')}
        hit = cands & bases_with_materials
        if not hit:
            continue
        base = sorted(hit)[0]
        if base not in bill_for_base:
            bill_for_base[base] = {
                'org': org,
                'date': P.to_datetime(row.get('Date')),
                'ref': str(row.get('Reference') or '').strip(),
            }

    # --- consumption + earmark/QOH accumulation ----------------------------
    def _consumed(mf):
        tpk = mf.get('task')
        if tpk is not None:
            return task_status.get(tpk) == 'complete'
        return job_status.get(mf['job']) in _WORKED_JOB_STATUSES

    qoh_delta = defaultdict(lambda: Decimal('0'))
    sold_delta = defaultdict(lambda: Decimal('0'))
    earmarks = defaultdict(lambda: Decimal('0'))   # (item_pk, job_pk) -> qty

    for job_pk, mats in materials_by_job.items():
        base = base_by_jobpk.get(job_pk)
        received_job = base in bill_for_base
        active = job_status.get(job_pk) not in _TERMINAL_JOB_STATUSES
        for mf in mats:
            item_pk = mf['inventory_item']
            qty = Decimal(mf['quantity'])
            if _consumed(mf):
                mf['consumption_state'] = 'consumed'
                sold_delta[item_pk] += qty          # assumed acquired: net-0 QOH
            else:
                mf['consumption_state'] = 'pending'
                if received_job:
                    qoh_delta[item_pk] += qty        # received into stock
                if active:
                    earmarks[(item_pk, job_pk)] += qty

    for item_pk, d in qoh_delta.items():
        items[item_pk]['qty_on_hand'] = f"{Decimal(items[item_pk]['qty_on_hand']) + d:.2f}"
    for item_pk, d in sold_delta.items():
        items[item_pk]['qty_sold'] = f"{Decimal(items[item_pk]['qty_sold']) + d:.2f}"

    for (item_pk, job_pk), qty in earmarks.items():
        if qty <= 0:
            continue
        c.add_fixture('inventory.earmark', c.next_pk('inventory.earmark'), {
            'inventory_item': item_pk,
            'job': job_pk,
            'quantity': f'{qty:.2f}',
            'created_date': job_created.get(job_pk) or _HISTORY_FALLBACK_DATE,
        })

    # --- PO + Bill synthesis ----------------------------------------------
    po_count = 0
    for base, bill in sorted(bill_for_base.items()):
        job_pk = c.job_map[base]
        mats = materials_by_job.get(job_pk, [])
        if not mats:
            continue
        res = resolve_contact(c, bill['org'])
        if res is None:
            continue
        ent = c.entity_map.get(res['key'])
        if ent is None:                       # vendor not imported — create it now
            if res['kind'] == 'individual':
                _emit_individual(c, res['key'],
                                 {'display': res['display'], 'fa_row': res['fa_row']})
            else:
                _emit_business(c, res['key'],
                               {'display': res['display'], 'fa_row': res['fa_row'],
                                'persons': {}})
            ent = c.entity_map[res['key']]
        if ent['kind'] != 'business':         # a PO needs a Business vendor
            continue

        dt = bill['date']
        dstr = (dt.strftime('%Y-%m-%dT00:00:00+00:00') if dt
                else _HISTORY_FALLBACK_DATE)
        po_count += 1
        po_pk = c.next_pk('purchasing.purchaseorder')
        c.add_fixture('purchasing.purchaseorder', po_pk, {
            'po_number': f'PO{po_count:04d}',
            'business': ent['business'],
            'contact': ent.get('default_contact'),
            'status': 'received_in_full',
            'created_date': dstr,
            'requested_date': None,
            'issued_date': dstr,
            'received_date': dstr,
            'cancel_date': None,
        })
        bill_pk = c.next_pk('purchasing.bill')
        line_no = 0
        for mf in mats:
            line_no += 1
            poli_pk = c.next_pk('purchasing.purchaseorderlineitem')
            c.add_fixture('purchasing.purchaseorderlineitem', poli_pk, {
                'purchase_order': po_pk,
                'task': None,
                'inventory_item': mf['inventory_item'],
                'line_number': line_no,
                'qty': mf['quantity'],
                'units': mf['units'],
                'description': mf['description'],
                'price': mf['unit_cost'],
                'accounting_category': mf['accounting_category'],
                'taxable_override': None,
                'tax_rate_override': None,
                'qty_received': mf['quantity'],
                'received_by': None,
                'received_date': dstr,
                'receipt_note': '',
                'qty_cancelled': '0.00',
            })
            mf['po_line_item'] = poli_pk
            c.add_fixture('purchasing.billlineitem',
                          c.next_pk('purchasing.billlineitem'), {
                'bill': bill_pk,
                'task': None,
                'inventory_item': mf['inventory_item'],
                'line_number': line_no,
                'qty': mf['quantity'],
                'units': mf['units'],
                'description': mf['description'],
                'price': mf['unit_cost'],
                'accounting_category': mf['accounting_category'],
                'taxable_override': None,
                'tax_rate_override': None,
            })
        c.add_fixture('purchasing.bill', bill_pk, {
            'purchase_order': po_pk,
            'business': ent['business'],
            'contact': ent.get('default_contact'),
            'vendor_invoice_number': (bill['ref'] or f'BILL-{bill_pk:04d}')[:50],
            'status': 'received',
            'created_date': dstr,
            'due_date': None,
            'received_date': dstr,
            'paid_date': None,
            'cancelled_date': None,
            'qbo_id': None,
            'qbo_payment_status': '',
        })

    # Advance the po_counter AppState past the generated POs.
    for f in c.fixture_data:
        if f['model'] == 'core.appstate' and f['pk'] == 'po_counter':
            f['fields']['value'] = str(po_count)
            break

    if c.verbose:
        consumed = sum(1 for mats in materials_by_job.values()
                       for mf in mats if mf['consumption_state'] == 'consumed')
        print(f'  purchasing: {po_count} POs+Bills from matched bills; '
              f'{consumed} materials consumed; {len(earmarks)} earmarks')


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
        model = _HISTORY_TABLE[object_type]
        c.add_fixture(model, c.next_pk(model), {
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

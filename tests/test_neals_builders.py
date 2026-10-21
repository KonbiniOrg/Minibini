# tests/test_neals_builders.py
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from nealsdata.converter import build
from nealsdata.converter import parsing as P
from nealsdata.converter import reconcile
from nealsdata.converter.loaders import discover_datasets
from nealsdata.converter.orchestrator import NealsDataConverter

try:
    XLSX, CSV = discover_datasets('nealsdata/datasets')
except (ValueError, FileNotFoundError):
    XLSX = 'nealsdata/datasets/__missing__.xlsx'
    CSV = 'nealsdata/datasets/__missing__.csv'


class SpineTest(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                         'datasets not present')
    def test_spine_selects_limited_recent_matched_cards(self):
        c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=20)
        c.loader.load()
        c.csv_cards = c.csv_loader.load()
        spine = c.select_spine()
        # Active-stage cards are always included, so the spine may exceed a
        # small limit; the fill portion is still capped.
        self.assertGreater(len(spine), 0)
        for entry in spine:
            self.assertIn('card', entry)
            self.assertIn('estimate_rows', entry)
            self.assertTrue(entry['estimate_rows'])

    @unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                         'datasets not present')
    def test_active_board_cards_survive_the_limit(self):
        # Regression (2026-07-13): the two Barbara Freeman jobs — in-progress
        # cards created in 2025 — silently aged out of the newest-100 window
        # even though their FreeAgent estimates matched.
        c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=100)
        c.loader.load()
        c.csv_cards = c.csv_loader.load()
        bases = {e['base_ref'] for e in c.select_spine()}
        self.assertIn('07724', bases)
        self.assertIn('07725', bases)


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class BaseBuildersTest(unittest.TestCase):
    def setUp(self):
        self.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=5)
        self.c.loader.load()

    def _models(self, model):
        return [f for f in self.c.fixture_data if f['model'] == model]

    def test_build_seed_emits_users_acs_schemes(self):
        build.build_seed(self.c)
        users = self._models('core.user')
        self.assertTrue(any(u['fields']['username'] == 'system' for u in users))
        codes = {f['fields']['code']
                 for f in self._models('core.accountingcategory')}
        self.assertIn('SVC', codes)
        self.assertIn('MTL', codes)
        self.assertGreater(len(self._models('jobs.ratescheme')), 0)
        # build_seed indexes the seed data for downstream builders
        self.assertEqual(self.c.ac_by_code.get('SVC'), self.c.ac_svc_pk)
        self.assertIn('Shop labor', self.c.scheme_by_name)

    def test_build_configuration_numbering_keys(self):
        build.build_configuration(self.c)
        config = {f['pk'] for f in self._models('core.configuration')}
        appstate = {f['pk'] for f in self._models('core.appstate')}
        # Patterns are user-settable Configuration ...
        for k in ('job_number_sequence', 'invoice_number_sequence', 'po_number_sequence'):
            self.assertIn(k, config)
        # ... counters are machine state in AppState (migration 0018).
        for k in ('job_counter', 'invoice_counter', 'po_counter'):
            self.assertIn(k, appstate)
            self.assertNotIn(k, config)
        # Dead keys deleted by 0018 are not emitted.
        self.assertNotIn('estimate_counter', config)
        self.assertNotIn('estimate_number_sequence', config)

    def test_units_list_matches_canon(self):
        # The converter installs Configuration['units_list']; it must match
        # apps.core.units.DEFAULT_UNITS so BaseLineItem rows we emit validate
        # against the running app's canonical list.
        build.build_configuration(self.c)
        cfg = next(f for f in self._models('core.configuration')
                   if f['pk'] == 'units_list')
        value = json.loads(cfg['fields']['value'])
        canon = ['none', 'ea', 'hour', 'min', 'sheet', 'sq ft', 'ft', 'yd',
                 'm', 'lb', 'kg', 'gal', 'qt', 'L', 'bd ft', 'ln ft']
        self.assertEqual(value, canon)

    def test_service_items_and_extra_categories_come_from_internal_tables(self):
        """RM 2026-08-18: the converter preserves RM's dev-authored catalog —
        ServiceItems and the extra (DEP/UNC) AccountingCategories are emitted
        from converter-internal tables so a regen never wipes them."""
        build.build_seed(self.c)
        items = {f['pk']: f['fields'] for f in self._models('estimates.serviceitem')}
        table = {pk: fields for pk, fields in build.CONVERTER_SERVICE_ITEMS}
        self.assertEqual(set(items), set(table))
        for pk, fields in table.items():
            for k, v in fields.items():
                self.assertEqual(items[pk][k], v, f'serviceitem {pk} field {k}')
            self.assertIn('created_date', items[pk])
            # Every item's scheme FK resolves to an emitted scheme.
            self.assertIn(fields['rate_scheme'], self.c.scheme_fields_by_pk)
        # Flat-fee items carry a one-entry amount config (the scheme owns the
        # interpretation; this pins the emitted shape).
        flat_pks = {pk for pk, f in build.CONVERTER_SCHEMES
                    if f['algorithm'] == 'flat_fee'}
        for pk, fields in table.items():
            if fields['rate_scheme'] in flat_pks:
                cfg = fields['default_active_modifiers']
                self.assertEqual(len(cfg), 1)
                self.assertIn('amount', cfg[0])
        # Extra categories emitted with their codes indexed.
        acs = {f['pk']: f['fields'] for f in self._models('core.accountingcategory')}
        for pk, fields in build.CONVERTER_EXTRA_CATEGORIES:
            self.assertEqual(acs[pk]['code'], fields['code'])
            self.assertEqual(self.c.ac_by_code[fields['code']], pk)
        self.assertTrue(acs[5]['is_deposit'])

    def test_configuration_carries_rm_settings(self):
        """The defaults/email/Business-tab keys RM tunes in dev are emitted so
        a regen'd DB comes up configured (RM 2026-08-18)."""
        build.build_seed(self.c)
        build.build_configuration(self.c)
        config = {f['pk']: f['fields']['value']
                  for f in self._models('core.configuration')}
        self.assertEqual(config['default_rate_scheme'], '7')
        self.assertEqual(config['default_deposit_accounting_category'], '5')
        self.assertEqual(config['fallback_accounting_category'], '6')
        for key in ('email_address', 'email_imap_server', 'email_password',
                    'email_smtp_host', 'email_smtp_port',
                    'business_email', 'our_public_url', 'our_domain'):
            self.assertTrue(config.get(key), f'missing config key {key}')

    def test_schemes_come_from_the_internal_table_not_nealseed(self):
        """RM 2026-08-16 (flat-fee Task 4): the converter sources its
        RateSchemes from build.CONVERTER_SCHEMES — nealseed's ratescheme
        records are ignored, so a new algorithm never requires touching the
        RM-managed seed files. The 8 legacy schemes keep their pks/fields;
        one flat_fee scheme is added."""
        build.build_seed(self.c)
        emitted = {f['pk']: f['fields'] for f in self._models('jobs.ratescheme')}
        table = {pk: dict(fields) for pk, fields in build.CONVERTER_SCHEMES}
        self.assertEqual(emitted, table)
        # The internal table includes exactly one flat_fee scheme.
        flat = [f for f in emitted.values() if f['algorithm'] == 'flat_fee']
        self.assertEqual(len(flat), 1)
        self.assertEqual(flat[0]['rate'], '0.00')
        self.assertEqual(flat[0]['modifiers'], [])
        # Legacy names survive with their original pks (downstream builders
        # key on scheme_by_name / scheme_fields_by_pk).
        self.assertEqual(self.c.scheme_by_name.get('Shop labor'), 7)
        self.assertEqual(self.c.scheme_by_name.get('CNC routing'), 1)

    def test_ratescheme_unit_labels_within_canon(self):
        # Every emitted RateScheme.unit_label must be a value in the
        # converter's units_list. DEFAULT_UNITS uses singular 'hour', and the
        # seed's RateScheme unit_label matches — this guards that pairing.
        build.build_seed(self.c)
        build.build_configuration(self.c)
        cfg = next(f for f in self._models('core.configuration')
                   if f['pk'] == 'units_list')
        units = set(json.loads(cfg['fields']['value']))
        for f in self._models('jobs.ratescheme'):
            label = f['fields']['unit_label']
            self.assertIn(
                label, units,
                f"RateScheme {f['fields']['name']!r} unit_label {label!r} "
                f"is not in units_list {sorted(units)}")

    def test_build_inventory_items(self):
        build.build_seed(self.c)
        build.build_inventory_items(self.c)
        items = self._models('inventory.inventoryitem')
        self.assertGreater(len(items), 100)
        # purchase_price is 83.33% of selling_price.
        for f in items:
            sell = Decimal(f['fields']['selling_price'])
            expected = (sell * Decimal('0.8333')).quantize(Decimal('0.01'))
            self.assertEqual(Decimal(f['fields']['purchase_price']), expected)


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class CanonUnitLabelTest(unittest.TestCase):
    """RM 2026-08-12: seed rate-scheme unit labels self-heal 'hours' -> 'hour'
    (plural drift breaks the SPA's hour-unit single-field collapse)."""

    def test_hours_drops_the_s(self):
        self.assertEqual(build._canon_unit_label('hours'), 'hour')
        self.assertEqual(build._canon_unit_label('Hours'), 'hour')
        self.assertEqual(build._canon_unit_label(' HOURS '), 'hour')

    def test_everything_else_passes_through(self):
        for label in ('hour', 'min', 'ea', 'none', 'sq ft', '', None):
            self.assertEqual(build._canon_unit_label(label), label)


class UniqueEmailTest(unittest.TestCase):
    def test_first_occurrence_keeps_the_original(self):
        seen = set()
        self.assertEqual(build._unique_email('test+info@robot-six.com', seen),
                         'test+info@robot-six.com')

    def test_collisions_number_the_local_part(self):
        seen = set()
        build._unique_email('test+info@robot-six.com', seen)
        self.assertEqual(build._unique_email('test+info@robot-six.com', seen),
                         'test+info1@robot-six.com')
        self.assertEqual(build._unique_email('test+info@robot-six.com', seen),
                         'test+info2@robot-six.com')

    def test_numbering_skips_addresses_already_taken(self):
        seen = {'test+info@robot-six.com', 'test+info1@robot-six.com'}
        self.assertEqual(build._unique_email('test+info@robot-six.com', seen),
                         'test+info2@robot-six.com')

    def test_collisions_are_case_insensitive(self):
        # MySQL's default *_ci collation makes Contact.email's unique index
        # case-insensitive, so test+Brian@ and test+brian@ collide on load.
        seen = set()
        self.assertEqual(build._unique_email('test+Brian@robot-six.com', seen),
                         'test+Brian@robot-six.com')
        self.assertEqual(build._unique_email('test+brian@robot-six.com', seen),
                         'test+brian1@robot-six.com')
        self.assertEqual(build._unique_email('TEST+BRIAN@robot-six.com', seen),
                         'TEST+BRIAN2@robot-six.com')

    def test_numbering_skips_case_variants_already_taken(self):
        # The registry holds lowercased keys (only _unique_email writes it).
        seen = set()
        build._unique_email('test+brian@robot-six.com', seen)
        build._unique_email('test+Brian@robot-six.com', seen)   # -> Brian1
        self.assertEqual(build._unique_email('test+BRIAN@robot-six.com', seen),
                         'test+BRIAN2@robot-six.com')


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class ContactBuildersTest(unittest.TestCase):
    def setUp(self):
        self.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=10)
        self.c.loader.load()
        self.c.csv_cards = self.c.csv_loader.load()
        self.c.spine = self.c.select_spine()

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def test_contact_emails_are_unique(self):
        # Contact.email is DB-unique (contacts migration 0008). Distinct source
        # contacts can share a local part (info@a.com, info@b.com — both
        # anonymize to test+info@robot-six.com); the builder must number the
        # collisions: test+info@, test+info1@, test+info2@ ...
        build.build_contacts_and_businesses(self.c)
        build.build_vendors(self.c)
        emails = [f['fields']['email'] for f in self._models('contacts.contact')
                  if f['fields']['email']]
        self.assertEqual(len(emails), len(set(emails)),
                         [e for e in emails if emails.count(e) > 1])

    def test_builds_referenced_contacts_and_businesses(self):
        build.build_contacts_and_businesses(self.c)
        contacts = self._models('contacts.contact')
        businesses = self._models('contacts.business')
        self.assertGreater(len(contacts), 0)
        contact_pks = {f['pk'] for f in contacts}
        # Every Business.default_contact resolves to a real Contact.
        for b in businesses:
            self.assertIn(b['fields']['default_contact'], contact_pks)
        # Every contact has an email and a well-formed phones list with at
        # least one entry (the converter synthesizes 555-555-5555 when the
        # export has none), plus the active flag.
        for ct in contacts:
            self.assertTrue(ct['fields']['email'])
            phones = ct['fields']['phones']
            self.assertIsInstance(phones, list)
            self.assertGreaterEqual(len(phones), 1)
            for p in phones:
                self.assertEqual(set(p), {'number', 'label'})
                self.assertTrue(p['number'])
            self.assertTrue(ct['fields']['is_active'])
            self.assertNotIn('work_number', ct['fields'])
        for b in businesses:
            self.assertEqual(b['fields']['phones'], [])
            self.assertTrue(b['fields']['is_active'])
        # Each entity in the map is consistent: individuals carry a null-business
        # Contact; businesses carry a Business whose contacts all FK to it.
        by_pk = {ct['pk']: ct['fields'] for ct in contacts}
        biz_pks = {b['pk'] for b in businesses}
        for ent in self.c.entity_map.values():
            if ent['kind'] == 'individual':
                self.assertIsNone(by_pk[ent['contact']]['business'])
            else:
                self.assertIn(ent['business'], biz_pks)
                for cpk in ent['contacts'].values():
                    self.assertEqual(by_pk[cpk]['business'], ent['business'])


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class VendorBuildersTest(unittest.TestCase):
    """Vendors are imported wholly from the FreeAgent Bills sheet (the Kanban
    source has no concept of bills/vendors), capped at --limit, newest first,
    reusing existing businesses on exact org-name match."""

    def setUp(self):
        self.limit = 10
        self.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json',
                                    limit=self.limit)
        self.c.loader.load()
        self.c.csv_cards = self.c.csv_loader.load()
        self.c.spine = self.c.select_spine()
        # Full prefix so entity_map holds the customer entities before vendors.
        build.build_contacts_and_businesses(self.c)
        build.build_jobs(self.c)

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def _bills_latest_by_org(self):
        from nealsdata.converter import parsing as P
        latest = {}
        for row in self.c.loader.sheets_data.get('Bills', []):
            org = (row.get('Contact Organisation') or '').strip()
            if not org:
                continue
            dt = P.to_datetime(row.get('Date'))
            prev = latest.get(org, ('absent',))
            if prev == ('absent',) or (dt is not None and
                                       (prev is None or dt > prev)):
                latest[org] = dt
        return latest

    def test_vendors_built_from_bills(self):
        before = len(self._models('contacts.business'))
        build.build_vendors(self.c)
        after = len(self._models('contacts.business'))
        self.assertGreater(after, before)
        # Every selected vendor org comes from the Bills sheet and resolves to
        # a registered entity (a new vendor business or a reused customer).
        bill_orgs = set(self._bills_latest_by_org())
        for org in self.c.vendor_selected_orgs:
            self.assertIn(org, bill_orgs)
            res = build.resolve_contact(self.c, org)
            self.assertIsNotNone(res)
            self.assertIn(res['key'], self.c.entity_map)

    def test_vendor_selection_capped_at_limit(self):
        build.build_vendors(self.c)
        self.assertLessEqual(len(self.c.vendor_selected_orgs), self.limit)

    def test_vendors_selected_most_recent_first(self):
        build.build_vendors(self.c)
        latest = self._bills_latest_by_org()
        selected = self.c.vendor_selected_orgs
        # Selected dates are non-increasing (newest first).
        sel_dts = [latest[o] for o in selected if latest[o] is not None]
        self.assertEqual(sel_dts, sorted(sel_dts, reverse=True))
        # Nothing excluded is strictly newer than anything included: every
        # non-selected dated org is no newer than the oldest selected one. (Tie
        # ordering at the boundary is deterministic but not asserted here.)
        if len(selected) == self.limit and sel_dts:
            boundary = min(sel_dts)
            excluded = set(latest) - set(selected)
            for org in excluded:
                if latest[org] is not None:
                    self.assertLessEqual(latest[org], boundary)

    def test_vendor_reuses_existing_business_on_exact_match(self):
        # No duplicate business_name anywhere: a vendor org that already exists
        # as a customer is reused, never re-created.
        build.build_vendors(self.c)
        names = [b['fields']['business_name']
                 for b in self._models('contacts.business')]
        self.assertEqual(len(names), len(set(names)))

    def test_vendor_rows_with_no_org_are_skipped(self):
        build.build_vendors(self.c)
        # Name-only bill rows (blank Contact Organisation) are not imported and
        # never produce an empty-named business.
        self.assertGreater(self.c.vendor_skipped_name_only, 0)
        for b in self._models('contacts.business'):
            self.assertTrue(b['fields']['business_name'].strip())


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class JobBuilderTest(unittest.TestCase):
    def setUp(self):
        self.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=10)
        self.c.loader.load()
        self.c.csv_cards = self.c.csv_loader.load()
        self.c.spine = self.c.select_spine()
        build.build_contacts_and_businesses(self.c)

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def test_builds_one_job_per_spine_entry(self):
        build.build_jobs(self.c)
        jobs = self._models('jobs.job')
        self.assertEqual(len(jobs) + len(self.c.discarded_cards), len(self.c.spine))
        self.assertGreater(len(jobs), 0)
        for j in jobs:
            self.assertTrue(j['fields']['job_number'])
            self.assertIsNotNone(j['fields']['contact'])
            self.assertIn(j['fields']['status'],
                          ('draft', 'submitted', 'approved', 'in_progress',
                           'work_complete', 'completed', 'cancelled', 'rejected'))

    def test_job_number_is_freeagent_base_ref(self):
        # Job numbers come verbatim from the FreeAgent estimate ref's base
        # (the digit run), not from a synthesised J{year}-counter scheme.
        build.build_jobs(self.c)
        for base_ref, job_pk in self.c.job_map.items():
            job = next(f for f in self._models('jobs.job') if f['pk'] == job_pk)
            self.assertEqual(job['fields']['job_number'], base_ref)

    def test_jobs_cycle_through_accent_color_palette(self):
        # Job.save() auto-assigns accent_color from the palette, but loaddata
        # bypasses save(). The converter round-robins through the palette so
        # the SPA board renders with colored bars instead of bare jobs.
        import re
        build.build_jobs(self.c)
        jobs = self._models('jobs.job')
        self.assertGreater(len(jobs), 0)
        colors = [j['fields']['accent_color'] for j in jobs]
        # Every job has a hex color from the palette
        for c in colors:
            self.assertIsNotNone(c)
            self.assertRegex(c, r'^#[0-9a-fA-F]{6}$')
        # Round-robin: with > 1 job there's more than one distinct color
        if len(jobs) >= 2:
            self.assertGreater(len(set(colors)), 1)


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class EstimateBuilderTest(unittest.TestCase):
    def setUp(self):
        self.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=10)
        self.c.loader.load()
        self.c.csv_cards = self.c.csv_loader.load()
        self.c.spine = self.c.select_spine()
        # build_seed sets c.ac_svc_pk / c.ac_mat_pk (the default ACs) — the
        # orchestrator runs it before build_jobs/build_estimates, so the test
        # context must too, or emitted atoms/lines get a None accounting category.
        build.build_seed(self.c)
        build.build_contacts_and_businesses(self.c)
        build.build_jobs(self.c)

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def test_estimates_and_line_items_built(self):
        build.build_estimates(self.c)
        ests = self._models('estimates.estimate')
        self.assertGreater(len(ests), 0)
        for e in ests:
            self.assertIn(e['fields']['status'],
                          ('draft', 'open', 'accepted', 'rejected',
                           'superseded', 'expired'))
        lines = self._models('estimates.estimatelineitem')
        by_est = {}
        for li in lines:
            by_est.setdefault(li['fields']['estimate'], []).append(
                li['fields']['line_number'])
        for nums in by_est.values():
            self.assertEqual(sorted(nums), list(range(1, len(nums) + 1)))

    def test_emitted_units_are_within_canon(self):
        # No emitted line-item / material / deliverable row may carry units
        # like 'days' or 'each' — those are off-canon. Materials/Deliverables
        # default to 'ea'; Days lines convert to hour via resolve helper.
        build.build_estimates(self.c)
        canon = {'none', 'ea', 'hour', 'min', 'sheet', 'sq ft', 'ft', 'yd',
                 'm', 'lb', 'kg', 'gal', 'qt', 'L', 'bd ft', 'ln ft'}
        for li in self._models('estimates.estimatelineitem'):
            self.assertIn(li['fields']['units'], canon,
                          f"line item {li['pk']} has off-canon units "
                          f"{li['fields']['units']!r}")

    def test_every_estimate_line_item_has_an_accounting_category(self):
        # Current code (the AC-required rule) forbids an estimate line item
        # without an accounting category, and the send-gate only exempts
        # source-backed and adjustment lines. Discount/credit ('lineitem') and
        # deliverable lines never get a source-linked atom to carry the AC, so
        # the converter must emit one on every line or regen reproduces bare
        # null-AC lines.
        build.build_estimates(self.c)
        for li in self._models('estimates.estimatelineitem'):
            self.assertIsNotNone(
                li['fields']['accounting_category'],
                f"line item {li['pk']} "
                f"({li['fields'].get('description')!r}) has no "
                f"accounting_category — bare null-AC lines are invalid",
            )

    def test_every_estimate_has_a_unique_public_token(self):
        # Estimate.save() mints public_token via secrets.token_urlsafe(32);
        # loaddata bypasses save(), so the converter mints one per estimate.
        # The portal URL (/portal/?token=…) needs it.
        build.build_estimates(self.c)
        ests = self._models('estimates.estimate')
        tokens = [e['fields']['public_token'] for e in ests]
        for t in tokens:
            self.assertIsInstance(t, str)
            self.assertGreaterEqual(len(t), 32)
        self.assertEqual(len(tokens), len(set(tokens)),
                         'public_token must be unique across estimates')

    def test_estimate_number_is_the_bare_job_number(self):
        # App convention (RM 2026-08-17): estimate_number == job_number with
        # NO version suffix — `version` is its own field and the SPA renders
        # "{estimate_number}-{version}". (The old "{base}-{version}" emission
        # double-suffixed converted estimates in the UI: "07998-1-1".)
        build.build_estimates(self.c)
        for base_ref, est_list in self.c.estimates.items():
            for entry in est_list:
                est = next(f for f in self._models('estimates.estimate')
                           if f['pk'] == entry['est_pk'])
                self.assertEqual(est['fields']['estimate_number'], base_ref)
                self.assertEqual(est['fields']['version'], entry['version'])

    def test_comment_lines_excluded_and_estimates_link_to_jobs(self):
        build.build_estimates(self.c)
        job_pks = set(self.c.job_map.values())
        for e in self._models('estimates.estimate'):
            self.assertIn(e['fields']['job'], job_pks)
        # estimates were built for at least one job
        self.assertGreater(len(self._models('estimates.estimate')), 0)
        for li_list in self.c.line_items.values():
            self.assertFalse(
                any(li['classification'] == 'skip' for li in li_list),
                'Comment/skip lines must not be stashed in c.line_items')


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class AtomDerivationTest(unittest.TestCase):
    def setUp(self):
        self.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=15)
        self.c.loader.load()
        self.c.csv_cards = self.c.csv_loader.load()
        self.c.spine = self.c.select_spine()
        build.build_seed(self.c)
        build.build_contacts_and_businesses(self.c)
        build.build_jobs(self.c)
        build.build_estimates(self.c)

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def test_derives_ratescheme_task_material_deliverable(self):
        build.derive_atoms(self.c)
        self.assertGreater(len(self._models('jobs.ratescheme')), 0)
        self.assertGreater(len(self._models('jobs.task')), 0)
        schemes_by_pk = {f['pk']: f['fields'] for f in self._models('jobs.ratescheme')}
        for t in self._models('jobs.task'):
            fields = t['fields']
            self.assertIn(fields['source_scheme'], schemes_by_pk)
            # Task-owned money (task-owned-money Phase 1): the task carries its
            # own permanent copy of the resolved scheme's money fields, mirroring
            # Task.stamp_from_scheme.
            scheme = schemes_by_pk[fields['source_scheme']]
            self.assertEqual(fields['qty_source'], scheme['algorithm'])
            self.assertEqual(fields['rate'], scheme['rate'])
            self.assertEqual(fields['unit_label'], scheme['unit_label'])
            self.assertEqual(fields['accounting_category'], scheme['accounting_category'])

    def test_atoms_emit_canon_units_only(self):
        # Materials and Deliverables must use canonical units (no 'each' /
        # 'days') so they validate against the running app's units_list.
        build.derive_atoms(self.c)
        canon = {'none', 'ea', 'hour', 'min', 'sheet', 'sq ft', 'ft', 'yd',
                 'm', 'lb', 'kg', 'gal', 'qt', 'L', 'bd ft', 'ln ft'}
        for m in self._models('inventory.material'):
            self.assertIn(m['fields']['units'], canon,
                          f"material {m['pk']} units={m['fields']['units']!r}")
        for d in self._models('deliverables.deliverable'):
            self.assertIn(d['fields']['units'], canon,
                          f"deliverable {d['pk']} units={d['fields']['units']!r}")
        job_pks = {f['pk'] for f in self._models('jobs.job')}
        deliv_jobs = {d['fields']['job'] for d in self._models('deliverables.deliverable')}
        self.assertEqual(job_pks, deliv_jobs)
        # Every task must have a list active_modifiers with no flat_fee_price.
        for t in self._models('jobs.task'):
            mods = t['fields']['active_modifiers']
            self.assertIsInstance(mods, list,
                                  f"task {t['pk']} active_modifiers should be a list, got {type(mods)}")
            self.assertNotIn('flat_fee_price', mods if isinstance(mods, dict) else {},
                             f"task {t['pk']} active_modifiers must not contain flat_fee_price")

    def test_flat_fee_tasks_carry_their_own_rate(self):
        # REWRITTEN 2026-08-16 (flat-fee redesign): the old "Phase 1 reframe"
        # contract (per-price flat_fee schemes, no shared catch-all) is
        # superseded — the new design is ONE shared zero-rate flat_fee scheme
        # whose ServiceItems carry item-side amounts, resolved into Task.rate
        # at stamp time. The converter emits exactly that shared scheme; any
        # flat-fee TASK still carries its own nonzero rate (money on the
        # task, never on the scheme) and empty list active_modifiers.
        build.derive_atoms(self.c)
        ff_schemes = [f for f in self._models('jobs.ratescheme')
                      if f['fields'].get('algorithm') == 'flat_fee']
        self.assertEqual(len(ff_schemes), 1)
        self.assertEqual(ff_schemes[0]['fields']['rate'], '0.00')
        self.assertEqual(ff_schemes[0]['fields']['modifiers'], [])
        ff_pks = {f['pk'] for f in ff_schemes}
        for t in self._models('jobs.task'):
            sp = t['fields']['source_scheme']
            mods = t['fields']['active_modifiers']
            self.assertIsInstance(mods, list,
                                  f"task {t['pk']} active_modifiers should be list")
            if sp in ff_pks:
                self.assertNotEqual(
                    t['fields']['rate'], '0.00',
                    f"task {t['pk']} stamped from the flat_fee scheme must "
                    f"carry its own nonzero rate (item-side amount)")
                self.assertEqual(mods, [])

    def test_fixed_charge_lines_stay_plain_no_atom_no_source(self):
        # better-fees spec §4 (Fee model deleted): a task-classified line with
        # no time/quantity signal is 'plain' — the estimate line item keeps its
        # price, but NO atom and NO source row crystallize from it. The
        # jobs.Fee model string must not appear in output at all, and no
        # source row may carry source_type='fee'.
        build.derive_atoms(self.c)
        self.assertEqual(
            [f for f in self.c.fixture_data if f['model'] == 'jobs.fee'], [])
        self.assertEqual(
            [s for s in self._models('estimates.estimatelineitemsource')
             if s['fields']['source_type'] == 'fee'], [])
        # Find the plain-classified task lines on each job's latest estimate
        # (the lines _build_line_item_tasks saw) and pin: line emitted with
        # its price, unclaimed by any source, and no Task made from it.
        line_by_pk = {f['pk']: f
                      for f in self._models('estimates.estimatelineitem')}
        sourced = {s['fields']['estimate_line_item']
                   for s in self._models('estimates.estimatelineitemsource')}
        tasks_by_job = {}
        for t in self._models('jobs.task'):
            tasks_by_job.setdefault(
                t['fields']['job'], set()).add(t['fields']['name'])
        plain_lines = []  # (li, job_pk, fallback_path_ran)
        for base_ref, job_info in self.c.jobs.items():
            est_list = self.c.estimates.get(base_ref, [])
            if not est_list:
                continue
            latest = max(est_list, key=lambda e: e['version'])
            has_checklist = bool(
                P.parse_checklist(job_info['card'].get('Checklist')))
            for li in self.c.line_items.get(latest['est_pk'], []):
                if li['classification'] != 'task':
                    continue
                kind, _, _ = build._line_billing(self.c, li)
                if kind == 'plain':
                    plain_lines.append(
                        (li, job_info['job_pk'], not has_checklist))
        self.assertGreater(len(plain_lines), 0,
                           'dataset slice has no plain fixed-charge lines')
        for li, job_pk, fallback_ran in plain_lines:
            fixture = line_by_pk[li['line_item_pk']]
            self.assertEqual(fixture['fields']['price'], f"{li['price']:.2f}",
                             'plain line must keep its price')
            self.assertNotIn(li['line_item_pk'], sourced,
                             'plain line must not be claimed by any atom')
            if fallback_ran:
                name = (li['description'] or 'Task')[:255] or 'Task'
                self.assertNotIn(
                    name, tasks_by_job.get(job_pk, set()),
                    'plain line must not crystallize into a Task')

    def test_assign_worker_times_random_per_task_in_range(self):
        # Every task/plantask gets an invented per-task estimate in [0.5, 4.0]h
        # (2 sig figs); cut/ass card columns are no longer consumed.
        import random as _random
        build.derive_atoms(self.c)
        # Before the pass, tasks carry no worker time.
        self.assertTrue(all(t['fields']['est_worker_time'] is None
                            for t in self._models('jobs.task')))
        _random.seed(123)
        build.assign_worker_times(self.c)

        def hrs(s):
            h, m, sec = map(int, s.split(':'))
            return h + m / 60 + sec / 3600

        tasks = self._models('jobs.task') + self._models('jobs.plantask')
        self.assertGreater(len(tasks), 0)
        for t in tasks:
            ewt = t['fields']['est_worker_time']
            self.assertIsNotNone(ewt, f"task {t['pk']} has no est_worker_time")
            self.assertGreaterEqual(hrs(ewt), 0.5)
            self.assertLessEqual(hrs(ewt), 4.0)

    def test_assign_worker_times_is_deterministic_for_fixed_seed(self):
        import random as _random
        build.derive_atoms(self.c)
        _random.seed(999)
        build.assign_worker_times(self.c)
        first = {t['pk']: t['fields']['est_worker_time']
                 for t in self._models('jobs.task')}
        _random.seed(999)
        build.assign_worker_times(self.c)
        second = {t['pk']: t['fields']['est_worker_time']
                  for t in self._models('jobs.task')}
        self.assertEqual(first, second)

    def test_materials_link_to_cut_task_when_present(self):
        build.derive_atoms(self.c)
        tasks = self._models('jobs.task')
        cut_task_pks = {t['pk'] for t in tasks if 'cut' in t['fields']['name'].lower()}
        for m in self._models('inventory.material'):
            if m['fields']['task'] is not None:
                self.assertIn(m['fields']['task'], cut_task_pks)

    def test_every_derived_material_is_claimed_by_its_source_line(self):
        # A Material derived from a material-classified estimate line is that
        # line's crystallized atom — the converter must record the claim
        # (EstimateLineItemSource, source_type='material'). Without it the
        # line looks unsourced, and accepting a still-open estimate in-app
        # re-crystallizes it → duplicate atoms (job 08008).
        build.derive_atoms(self.c)
        materials = self._models('inventory.material')
        self.assertGreater(len(materials), 0)
        claims = {}
        for s in self._models('estimates.estimatelineitemsource'):
            if s['fields']['source_type'] != 'material':
                continue
            claims.setdefault(s['fields']['source_pk'], []).append(s)
        line_by_pk = {li['line_item_pk']: li
                      for lis in self.c.line_items.values() for li in lis}
        for m in materials:
            claimed_by = claims.get(m['pk'], [])
            self.assertEqual(
                len(claimed_by), 1,
                f"material {m['pk']} ({m['fields']['description'][:40]!r}) "
                f"must be claimed by exactly one estimate line, "
                f"got {len(claimed_by)}",
            )
            # The claiming line is a real material-classified line.
            li = line_by_pk.get(claimed_by[0]['fields']['estimate_line_item'])
            self.assertIsNotNone(li)
            self.assertEqual(li['classification'], 'material')


class InvoiceLineCategoryPickTest(unittest.TestCase):
    """AC assignment for invoice line items is deterministic and plausible:
    delivery-ish descriptions → DLV, FreeAgent 'Products' → PRD, the
    material classification → MTL, everything else (labour, discounts,
    credits) → SVC. No randomness — regen must be reproducible."""

    def test_delivery_keywords_win_over_everything(self):
        self.assertEqual(
            P.pick_invoice_line_ac('Products', 'Delivery of finished panels',
                                   'material'), 'DLV')
        self.assertEqual(
            P.pick_invoice_line_ac('Hours', 'shipping & handling', 'task'),
            'DLV')

    def test_products_item_type_maps_to_prd(self):
        self.assertEqual(
            P.pick_invoice_line_ac('Products', 'baltic birch ply',
                                   'material'), 'PRD')

    def test_material_classification_maps_to_mtl(self):
        self.assertEqual(
            P.pick_invoice_line_ac('-No Unit-', '3/4" MDF sheet',
                                   'material'), 'MTL')

    def test_labour_and_adjustments_map_to_svc(self):
        self.assertEqual(
            P.pick_invoice_line_ac('Hours', 'Cut panels', 'task'), 'SVC')
        self.assertEqual(
            P.pick_invoice_line_ac('Discount', 'loyalty discount',
                                   'lineitem'), 'SVC')


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class InvoiceBuilderTest(unittest.TestCase):
    def setUp(self):
        # limit=40, not 15: the 15 most recent spine jobs carry no invoices
        # at all, which made every line-item assertion in this class
        # vacuously true. 40 yields real invoice lines.
        self.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=40)
        self.c.loader.load()
        self.c.csv_cards = self.c.csv_loader.load()
        self.c.spine = self.c.select_spine()
        # build_seed populates c.ac_by_code (the seeded ACs) — the
        # orchestrator runs it before the other builders, so the test
        # context must too, or emitted lines get a None accounting category.
        build.build_seed(self.c)
        build.build_contacts_and_businesses(self.c)
        build.build_jobs(self.c)
        build.build_estimates(self.c)

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def test_every_invoice_line_item_has_a_seeded_accounting_category(self):
        # Invoice lines have no source-linked atom to inherit an AC from at
        # load time, so the converter must emit one on every line (mirrors
        # the estimate-line rule above). The value must be one of the four
        # seeded categories.
        build.build_invoices(self.c)
        seeded = {self.c.ac_by_code[code] for code in ('SVC', 'MTL', 'PRD', 'DLV')}
        lis = self._models('invoicing.invoicelineitem')
        self.assertTrue(lis, 'expected invoice line items in the fixture')
        for li in lis:
            self.assertIn(
                li['fields']['accounting_category'], seeded,
                f"invoice line {li['pk']} "
                f"({li['fields'].get('description')!r}) has AC "
                f"{li['fields']['accounting_category']!r} — every line "
                f"needs one of the seeded categories",
            )

    def test_invoices_attach_to_jobs_with_contiguous_line_numbers(self):
        build.build_invoices(self.c)
        job_pks = set(self.c.job_map.values())
        for inv in self._models('invoicing.invoice'):
            self.assertIn(inv['fields']['job'], job_pks)
        by_inv = {}
        for li in self._models('invoicing.invoicelineitem'):
            by_inv.setdefault(li['fields']['invoice'], []).append(
                li['fields']['line_number'])
        for nums in by_inv.values():
            self.assertEqual(sorted(nums), list(range(1, len(nums) + 1)))
        if self._models('invoicing.invoicelineitem'):
            self.assertTrue(self.c.invoice_totals)
            self.assertTrue(all(isinstance(v, Decimal) for v in self.c.invoice_totals.values()))


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class InvoiceAgreementRefsTest(unittest.TestCase):
    """RM 2026-08-12: converted invoice lines carry agreement_estimate_line
    refs (description-matched to the job's latest ACCEPTED estimate) so
    the one-live-invoice-per-agreement-line invariant holds on converted
    jobs — without them, Start Invoice re-seeds the full agreement next to
    an open legacy invoice."""

    @classmethod
    def setUpClass(cls):
        cls.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=20)
        cls.c.loader.load()
        cls.c.csv_cards = cls.c.csv_loader.load()
        cls.c.spine = cls.c.select_spine()
        build.build_seed(cls.c)
        build.build_contacts_and_businesses(cls.c)
        build.build_jobs(cls.c)
        build.build_estimates(cls.c)
        build.derive_atoms(cls.c)
        build.build_invoices(cls.c)
        reconcile.reconcile(cls.c)
        build.build_invoice_agreement_refs(cls.c)

    def _m(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def test_refs_point_at_the_same_jobs_latest_accepted_estimate(self):
        est_by_pk = {f['pk']: f['fields'] for f in self._m('estimates.estimate')}
        est_line_by_pk = {f['pk']: f['fields']
                          for f in self._m('estimates.estimatelineitem')}
        inv_by_pk = {f['pk']: f['fields'] for f in self._m('invoicing.invoice')}
        latest_by_job = {}
        for pk, fields in est_by_pk.items():
            cur = latest_by_job.get(fields['job'])
            if cur is None or fields['version'] > est_by_pk[cur]['version']:
                latest_by_job[fields['job']] = pk

        refs = 0
        for f in self._m('invoicing.invoicelineitem'):
            ref = f['fields'].get('agreement_estimate_line')
            if ref is None:
                continue
            refs += 1
            inv = inv_by_pk[f['fields']['invoice']]
            est_line = est_line_by_pk[ref]
            est = est_by_pk[est_line['estimate']]
            self.assertEqual(est['job'], inv['job'],
                             f"line {f['pk']} refs another job's estimate line")
            self.assertEqual(est_line['estimate'], latest_by_job[inv['job']])
            self.assertEqual(est['status'], 'accepted')
            self.assertNotEqual(inv.get('status'), 'cancelled')
            self.assertIsNone(est_line.get('adjustment_service'))
        # Sanity: the heuristic actually fires on the real dataset.
        self.assertGreater(refs, 0)

    def test_one_live_invoice_per_agreement_line(self):
        seen = {}
        for f in self._m('invoicing.invoicelineitem'):
            ref = f['fields'].get('agreement_estimate_line')
            if ref is None:
                continue
            inv_pk = f['fields']['invoice']
            self.assertNotIn(
                ref, seen,
                f'estimate line {ref} referenced by invoices {seen.get(ref)} and {inv_pk}')
            seen[ref] = inv_pk


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class ReconcileTest(unittest.TestCase):
    def setUp(self):
        self.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=20)
        self.c.loader.load()
        self.c.csv_cards = self.c.csv_loader.load()
        self.c.spine = self.c.select_spine()
        build.build_seed(self.c)
        build.build_contacts_and_businesses(self.c)
        build.build_jobs(self.c)
        build.build_estimates(self.c)
        build.derive_atoms(self.c)
        build.build_invoices(self.c)

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def test_estimate_statuses_and_versioning(self):
        reconcile.reconcile(self.c)
        for e in self._models('estimates.estimate'):
            self.assertIn(e['fields']['status'],
                          ('draft', 'open', 'accepted', 'rejected',
                           'superseded', 'expired'))
            if e['fields']['status'] in ('accepted', 'rejected', 'expired', 'superseded'):
                self.assertIsNotNone(e['fields']['closed_date'])

    def test_job_dates_consistent_with_status(self):
        reconcile.reconcile(self.c)
        for j in self._models('jobs.job'):
            st = j['fields']['status']
            if st in ('draft', 'submitted', 'rejected'):
                self.assertIsNone(j['fields']['start_date'])
            if st in ('approved', 'in_progress', 'work_complete', 'completed'):
                self.assertIsNotNone(j['fields']['start_date'])
            if st in ('draft', 'submitted', 'approved', 'in_progress',
                      'work_complete'):
                self.assertIsNone(j['fields']['completed_date'])
            if st in ('completed', 'cancelled', 'rejected'):
                self.assertIsNotNone(j['fields']['completed_date'])

    def test_started_jobs_have_an_accepted_latest_estimate(self):
        reconcile.reconcile(self.c)
        jobs = {j['pk']: j['fields']['status']
                for j in self._models('jobs.job')}
        ests_by_job = {}
        for e in self._models('estimates.estimate'):
            ests_by_job.setdefault(e['fields']['job'], []).append(e['fields'])
        for jp, status in jobs.items():
            if status not in ('in_progress', 'work_complete', 'completed'):
                continue
            ests = ests_by_job.get(jp, [])
            if not ests:
                continue
            latest = max(ests, key=lambda e: e['version'])
            self.assertEqual(latest['status'], 'accepted',
                             f'job {jp} ({status}) latest estimate not accepted')


    def test_task_statuses_are_valid_and_preserved(self):
        # Task status comes from the checklist ([X]/[ ]); reconcile only
        # cancels tasks on cancelled/rejected jobs and must not clobber
        # the rest. Verify every task carries a valid status.
        reconcile.reconcile(self.c)
        valid = ('pending', 'in_progress', 'blocked', 'complete', 'cancelled')
        for t in self._models('jobs.task'):
            self.assertIn(t['fields']['status'], valid)


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class SyntheticEstimateSourcesTest(unittest.TestCase):
    def setUp(self):
        self.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=20)
        self.c.loader.load()
        self.c.csv_cards = self.c.csv_loader.load()
        self.c.spine = self.c.select_spine()
        build.build_seed(self.c)
        build.build_contacts_and_businesses(self.c)
        build.build_jobs(self.c)
        build.build_estimates(self.c)
        build.derive_atoms(self.c)
        build.build_invoices(self.c)
        reconcile.reconcile(self.c)
        build.build_synthetic_estimate_sources(self.c)

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def test_no_source_claims_a_line_on_a_superseded_estimate(self):
        # In-app invariant: revising an estimate MOVES every source row onto
        # the revision's copied lines, so a superseded estimate keeps its line
        # items as a frozen snapshot but holds zero claims. The synthetic pass
        # must respect that — a claim stranded on an old revision surfaces in
        # the estimate/CO wizard pools as a bogus "Claimed by estimate
        # <superseded rev>" blocked row.
        est_status = {f['pk']: f['fields']['status']
                      for f in self._models('estimates.estimate')}
        line_estimate = {f['pk']: f['fields']['estimate']
                         for f in self._models('estimates.estimatelineitem')}
        for s in self._models('estimates.estimatelineitemsource'):
            est_pk = line_estimate[s['fields']['estimate_line_item']]
            self.assertNotIn(
                est_status[est_pk], ('superseded', 'rejected'),
                f"source {s['pk']} claims {s['fields']['source_type']} "
                f"{s['fields']['source_pk']} on a line of "
                f"{est_status[est_pk]} estimate {est_pk} — superseded moved "
                f"its claims to the revision; rejected released them. "
                f"(Expired estimates legitimately KEEP claims, RM 2026-08-13.)")


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class ShipmentBuilderTest(unittest.TestCase):
    def setUp(self):
        self.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json',
                                    limit=100)
        self.c.loader.load()
        self.c.csv_cards = self.c.csv_loader.load()
        self.c.spine = self.c.select_spine()
        build.build_seed(self.c)
        build.build_contacts_and_businesses(self.c)
        build.build_jobs(self.c)
        build.build_estimates(self.c)
        build.derive_atoms(self.c)
        build.build_invoices(self.c)
        reconcile.reconcile(self.c)

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def test_shipments_are_picked_up_with_their_jobs_deliverables(self):
        build.build_shipments(self.c)
        shipments = self._models('deliverables.shipment')
        self.assertGreater(len(shipments), 0)
        deliv_job = {d['pk']: d['fields']['job']
                     for d in self._models('deliverables.deliverable')}
        ship_job = {}
        for s in shipments:
            self.assertEqual(s['fields']['status'], 'picked_up')
            self.assertIsNotNone(s['fields']['picked_up_date'])
            ship_job[s['pk']] = s['fields']['job']
        items = self._models('deliverables.shipmentitem')
        self.assertGreater(len(items), 0)
        for it in items:
            self.assertIn(it['fields']['shipment'], ship_job)
            # the item's deliverable belongs to the shipment's job
            self.assertEqual(deliv_job[it['fields']['deliverable']],
                             ship_job[it['fields']['shipment']])


class DroppedChecklistLineTest(unittest.TestCase):
    def test_board_status_markers_are_dropped(self):
        for line in ('Invoice Sent',
                     'Invoice Sent Toni Morrison',
                     'Payment Received',
                     'Payment Received MLK',
                     'Jan take photos!',
                     'Packing Slip'):
            self.assertTrue(build._is_dropped_checklist_line(line), line)

    def test_real_work_lines_are_kept(self):
        for line in ('code for cutting',
                     'wait for deposit payment',
                     'wrap w/ packing slip',
                     'add invoice for sheet of black laminate',
                     'assemble piece'):
            self.assertFalse(build._is_dropped_checklist_line(line), line)

    def test_track_time_marker_is_never_dropped(self):
        # A '(track time)' marker overrides the drop-list.
        self.assertFalse(
            build._is_dropped_checklist_line('Invoice Sent (track time)'))


class MaterialLineKindTest(unittest.TestCase):
    def test_raw_stock_is_material(self):
        for d in ('4\'x8\' x 3/4" sheet(s) of Baltic Birch plywood',
                  'BF of solid maple lumber',
                  'board feet of ash, maple, white oak',
                  'Materials: plywood, lumber, acrylic',
                  'Estimated materials cost for both pedestals'):
            self.assertEqual(build._material_line_kind(d), 'material', d)

    def test_labour_verbs_are_tasks(self):
        for d in ('Apply epoxy to engraved redwood bench',
                  'Glue up MDF to similar proportions',
                  'Engrave decorative pattern into lead',
                  'Prepare stock for M58 floors'):
            self.assertEqual(build._material_line_kind(d), 'task', d)

    def test_finished_goods_are_deliverables(self):
        for d in ("Cat's Cradle sign from wood and brass",
                  'CNC cut B_Bottom Shelf from 3/4" Walnut Plywood',
                  'Construct Pedestal "A"',
                  'Large acrylic/wood backdrop with crate'):
            self.assertEqual(build._material_line_kind(d), 'deliverable', d)


class AnonymizeTest(unittest.TestCase):
    def test_email_domain_replaced(self):
        self.assertEqual(build._anonymize_email('oomung@abinari.it'),
                         'test+oomung@robot-six.com')
        self.assertEqual(build._anonymize_email('noreply+5@example.com'),
                         'test+noreply+5@robot-six.com')

    def test_phone_prefix_replaced(self):
        self.assertEqual(build._anonymize_phone('408-323-3393'), '408-555-3393')
        self.assertEqual(build._anonymize_phone('805 433 4154'), '805-555-4154')
        self.assertEqual(build._anonymize_phone('(650) 593-6997'), '650-555-6997')
        self.assertEqual(build._anonymize_phone(''), '555-555-5555')

    def test_scrub_text(self):
        self.assertEqual(
            build._scrub_text('email john@neals.com or call 415-867-5309'),
            'email test+john@robot-six.com or call 415-555-5309')
        # part-number-like sequences without the phone shape are untouched
        self.assertEqual(build._scrub_text('cut part A-109180-00 x10'),
                         'cut part A-109180-00 x10')


class DowngradeCompletedJobsWithUnpaidInvoicesTest(unittest.TestCase):
    """Focused unit test for the new reconcile pass — synthetic fixture data
    so we control the exact scenario."""

    def _make_converter(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        c.jobs = {}
        c.job_map = {}
        c.estimates = {}
        return c

    def _add_job(self, c, base_ref, status, completed_date='2026-05-01T00:00:00+00:00'):
        pk = c.next_pk('jobs.job')
        c.add_fixture('jobs.job', pk, {
            'job_number': base_ref, 'name': 'j', 'contact': 1, 'status': status,
            'created_date': '2026-01-01T00:00:00+00:00',
            'start_date': '2026-01-01T00:00:00+00:00',
            'due_date': None,
            'completed_date': completed_date if status == 'completed' else None,
            'customer_po_number': '', 'description': '', 'accent_color': '#f97066',
        })
        c.job_map[base_ref] = pk
        c.jobs[base_ref] = {'job_pk': pk, 'card': {}, 'estimate_rows': [], 'primary_ref': base_ref}
        return pk

    def _add_invoice(self, c, job_pk, status):
        pk = c.next_pk('invoicing.invoice')
        c.add_fixture('invoicing.invoice', pk, {
            'job': job_pk, 'invoice_number': f'INV-{pk}', 'status': status,
            'created_date': '2026-02-01T00:00:00+00:00',
            'sent_date': None, 'closed_date': None,
            'qbo_id': None, 'qbo_payment_status': '', 'qbo_amount_paid': None,
        })
        return pk

    def test_completed_with_open_invoice_downgrades_to_work_complete(self):
        c = self._make_converter()
        jp = self._add_job(c, '00001', 'completed')
        self._add_invoice(c, jp, 'open')
        reconcile.reconcile(c)
        job_fields = next(f['fields'] for f in c.fixture_data
                          if f['model'] == 'jobs.job' and f['pk'] == jp)
        self.assertEqual(job_fields['status'], 'work_complete')
        self.assertIsNone(job_fields['completed_date'])

    def test_completed_with_only_paid_and_cancelled_invoices_stays_completed(self):
        c = self._make_converter()
        jp = self._add_job(c, '00002', 'completed')
        self._add_invoice(c, jp, 'paid')
        self._add_invoice(c, jp, 'cancelled')
        reconcile.reconcile(c)
        job_fields = next(f['fields'] for f in c.fixture_data
                          if f['model'] == 'jobs.job' and f['pk'] == jp)
        self.assertEqual(job_fields['status'], 'completed')
        self.assertIsNotNone(job_fields['completed_date'])

    def test_completed_with_no_invoices_stays_completed(self):
        # Vacuously satisfies the gate — no Invoice means no unpaid Invoice.
        c = self._make_converter()
        jp = self._add_job(c, '00003', 'completed')
        reconcile.reconcile(c)
        job_fields = next(f['fields'] for f in c.fixture_data
                          if f['model'] == 'jobs.job' and f['pk'] == jp)
        self.assertEqual(job_fields['status'], 'completed')

    def test_non_completed_jobs_are_untouched(self):
        c = self._make_converter()
        jp = self._add_job(c, '00004', 'in_progress', completed_date=None)
        self._add_invoice(c, jp, 'draft')
        reconcile.reconcile(c)
        job_fields = next(f['fields'] for f in c.fixture_data
                          if f['model'] == 'jobs.job' and f['pk'] == jp)
        self.assertEqual(job_fields['status'], 'in_progress')


class PromoteWorkCompleteJobsTheGateWouldCloseTest(unittest.TestCase):
    """Reconcile pass 6.5: a work_complete Job that the app's completion gate
    (JobService.maybe_complete_if_resolved) would have walked to `completed`
    — every invoice resolved, deliverables all picked up — is promoted, with
    a completed_date as if the walk had happened on the last payment
    (RM 2026-10-14). Synthetic fixture data so we control the scenario."""

    PICKED = {'Checklist': '[X] cut it\n[X] Picked up/Delivered'}
    NOT_PICKED = {'Checklist': '[X] cut it\n[ ] Picked up/Delivered'}

    def _make_converter(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        c.jobs = {}
        c.job_map = {}
        c.estimates = {}
        return c

    def _add_job(self, c, base_ref, status='work_complete', card=None, on_hold=False):
        pk = c.next_pk('jobs.job')
        c.add_fixture('jobs.job', pk, {
            'job_number': base_ref, 'name': 'j', 'contact': 1, 'status': status,
            'created_date': '2026-01-01T00:00:00+00:00',
            'start_date': '2026-01-01T00:00:00+00:00',
            'due_date': None, 'completed_date': None,
            'customer_po_number': '', 'description': '', 'accent_color': '#f97066',
            'on_hold': on_hold, 'hold_reason': 'x' if on_hold else '',
        })
        c.job_map[base_ref] = pk
        c.jobs[base_ref] = {'job_pk': pk, 'card': card if card is not None else self.PICKED,
                            'estimate_rows': [], 'primary_ref': base_ref}
        return pk

    def _add_invoice(self, c, job_pk, status, created='2026-02-01T00:00:00+00:00',
                     closed=None):
        pk = c.next_pk('invoicing.invoice')
        c.add_fixture('invoicing.invoice', pk, {
            'job': job_pk, 'invoice_number': f'INV-{pk}', 'status': status,
            'created_date': created,
            'sent_date': created if status in ('open', 'paid') else None,
            'closed_date': closed,
            'qbo_id': None, 'qbo_payment_status': '', 'qbo_amount_paid': None,
        })
        return pk

    def _job(self, c, pk):
        return next(f['fields'] for f in c.fixture_data
                    if f['model'] == 'jobs.job' and f['pk'] == pk)

    def test_paid_and_picked_up_promotes_to_completed_on_the_payment_date(self):
        c = self._make_converter()
        jp = self._add_job(c, '00001')
        self._add_invoice(c, jp, 'paid', closed='2026-04-14T00:00:00+00:00')
        reconcile.reconcile(c)
        self.assertEqual(self._job(c, jp)['status'], 'completed')
        self.assertEqual(self._job(c, jp)['completed_date'], '2026-04-14T00:00:00+00:00')

    def test_latest_payment_wins_with_several_paid_invoices(self):
        c = self._make_converter()
        jp = self._add_job(c, '00002')
        self._add_invoice(c, jp, 'paid', closed='2026-03-01T00:00:00+00:00')
        self._add_invoice(c, jp, 'paid', closed='2026-05-09T00:00:00+00:00')
        self._add_invoice(c, jp, 'cancelled')
        reconcile.reconcile(c)
        self.assertEqual(self._job(c, jp)['status'], 'completed')
        self.assertEqual(self._job(c, jp)['completed_date'], '2026-05-09T00:00:00+00:00')

    def test_missing_closed_date_falls_back_to_latest_invoice_date(self):
        c = self._make_converter()
        jp = self._add_job(c, '00003')
        self._add_invoice(c, jp, 'paid', created='2026-02-20T00:00:00+00:00', closed=None)
        reconcile.reconcile(c)
        self.assertEqual(self._job(c, jp)['status'], 'completed')
        self.assertEqual(self._job(c, jp)['completed_date'], '2026-02-20T00:00:00+00:00')

    def test_not_picked_up_stays_work_complete(self):
        # The gate requires all deliverables shipped; without the marker a
        # work_complete job gets no shipment, so it stays — the board files
        # it under Needs Pickup.
        c = self._make_converter()
        jp = self._add_job(c, '00004', card=self.NOT_PICKED)
        self._add_invoice(c, jp, 'paid', closed='2026-04-14T00:00:00+00:00')
        reconcile.reconcile(c)
        self.assertEqual(self._job(c, jp)['status'], 'work_complete')
        self.assertIsNone(self._job(c, jp)['completed_date'])

    def test_unresolved_invoice_stays_work_complete(self):
        c = self._make_converter()
        jp = self._add_job(c, '00005')
        self._add_invoice(c, jp, 'paid', closed='2026-04-14T00:00:00+00:00')
        self._add_invoice(c, jp, 'open')
        reconcile.reconcile(c)
        self.assertEqual(self._job(c, jp)['status'], 'work_complete')

    def test_no_invoices_stays_work_complete(self):
        # Deliberate departure from the gate's vacuous "all invoices resolved":
        # the Kanban Invoice stage means billing is still pending, so a
        # picked-up but never-invoiced job must stay visible as Needs Invoice.
        c = self._make_converter()
        jp = self._add_job(c, '00006')
        reconcile.reconcile(c)
        self.assertEqual(self._job(c, jp)['status'], 'work_complete')

    def test_only_cancelled_invoices_stays_work_complete(self):
        # Resolved but nothing was ever paid: the bill still has to go out.
        c = self._make_converter()
        jp = self._add_job(c, '00007')
        self._add_invoice(c, jp, 'cancelled')
        reconcile.reconcile(c)
        self.assertEqual(self._job(c, jp)['status'], 'work_complete')

    def test_held_job_is_not_promoted(self):
        # The gate never fires on a held job (status changes are blocked).
        c = self._make_converter()
        jp = self._add_job(c, '00008', on_hold=True)
        self._add_invoice(c, jp, 'paid', closed='2026-04-14T00:00:00+00:00')
        reconcile.reconcile(c)
        self.assertEqual(self._job(c, jp)['status'], 'work_complete')

    def test_other_statuses_are_untouched(self):
        c = self._make_converter()
        jp = self._add_job(c, '00009', status='in_progress')
        self._add_invoice(c, jp, 'paid', closed='2026-04-14T00:00:00+00:00')
        reconcile.reconcile(c)
        self.assertEqual(self._job(c, jp)['status'], 'in_progress')

    def test_promoted_job_gets_a_shipment_and_closed_out_history(self):
        c = self._make_converter()
        jp = self._add_job(c, '00010')
        self._add_invoice(c, jp, 'paid', closed='2026-04-14T00:00:00+00:00')
        c.add_fixture('deliverables.deliverable', c.next_pk('deliverables.deliverable'), {
            'job': jp, 'description': 'Sign', 'qty_ordered': '1.00', 'units': 'ea',
            'sort_order': 10, 'created_at': '2026-01-01T00:00:00+00:00',
            'updated_at': '2026-01-01T00:00:00+00:00', 'source_line': None,
        })
        reconcile.reconcile(c)
        build.build_shipments(c)
        ships = [f for f in c.fixture_data if f['model'] == 'deliverables.shipment'
                 and f['fields']['job'] == jp]
        self.assertEqual(len(ships), 1)
        self.assertEqual(ships[0]['fields']['status'], 'picked_up')
        self.assertEqual(ships[0]['fields']['notes'], '')  # marker path, not synthetic
        events = build._job_timeline(jp, self._job(c, jp), {
            'invoicing.invoice': [f for f in c.fixture_data if f['model'] == 'invoicing.invoice'],
            'deliverables.shipment': ships,
        })
        self.assertTrue(any(ch.get('_action') == 'Job closed out' for *_, ch in events))


class BlepHorizonTest(unittest.TestCase):
    """build_bleps_and_shifts only emits bleps within three weeks of the
    dataset's "now". A FINISHED job (has completed_date) older than that is
    dropped; an UNFINISHED/current job always bleps its complete Tasks because its
    window runs to `now`. Synthetic fixture data for exact scenarios."""

    def _make_converter(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        c.rotation_user_pks = [self._user(c), self._user(c)]
        return c

    def _user(self, c):
        pk = c.next_pk('core.user')
        c.add_fixture('core.user', pk, {'username': f'w{pk}', 'is_active': True})
        return pk

    def _job(self, c, status, start, completed=None):
        pk = c.next_pk('jobs.job')
        c.add_fixture('jobs.job', pk, {
            'job_number': f'J{pk}', 'status': status,
            'created_date': start, 'start_date': start,
            'due_date': None, 'completed_date': completed,
        })
        return pk

    def _task(self, c, job_pk, status='complete', ewt='02:00:00'):
        pk = c.next_pk('jobs.task')
        c.add_fixture('jobs.task', pk, {
            'job': job_pk, 'name': f't{pk}', 'status': status,
            'est_worker_time': ewt, 'est_qty': None, 'rate_scheme': None,
            'assignee': None, 'worker_queue': None, 'sort_order': pk,
        })
        return pk

    def _bleps(self, c):
        return [f for f in c.fixture_data if f['model'] == 'jobs.blep']

    def test_old_finished_job_gets_no_blep_recent_one_does(self):
        c = self._make_converter()
        # now = 2026-06-10 → horizon = 2026-05-20.
        recent = self._job(c, 'completed', '2026-06-01T00:00:00+00:00',
                           '2026-06-10T00:00:00+00:00')
        rt = self._task(c, recent)
        old = self._job(c, 'completed', '2026-03-01T00:00:00+00:00',
                        '2026-03-15T00:00:00+00:00')
        ot = self._task(c, old)
        build.build_bleps_and_shifts(c)
        task_pks = {b['fields']['task'] for b in self._bleps(c)}
        self.assertIn(rt, task_pks)
        self.assertNotIn(ot, task_pks)

    def test_no_blep_starts_before_the_horizon(self):
        c = self._make_converter()
        # now = 2026-06-10 (horizon 2026-05-20). A job that started long ago but
        # completed inside the window is clamped, not skipped.
        recent = self._job(c, 'completed', '2026-06-09T00:00:00+00:00',
                           '2026-06-10T00:00:00+00:00')
        self._task(c, recent)
        straddle = self._job(c, 'completed', '2026-01-01T00:00:00+00:00',
                             '2026-06-05T00:00:00+00:00')
        self._task(c, straddle)
        build.build_bleps_and_shifts(c)
        bleps = self._bleps(c)
        self.assertTrue(bleps)
        for b in bleps:
            self.assertGreaterEqual(b['fields']['start_time'][:10], '2026-05-20')

    def test_unfinished_job_started_long_ago_still_bleps(self):
        # The core fix: a long-running in_progress job (started well before the
        # horizon, no completed_date) must still blep its complete Tasks — its
        # window runs to `now`, so the horizon never skips it.
        c = self._make_converter()
        anchor = self._job(c, 'completed', '2026-06-01T00:00:00+00:00',
                           '2026-06-10T00:00:00+00:00')  # now = 2026-06-10
        self._task(c, anchor)
        ip = self._job(c, 'in_progress', '2026-01-01T00:00:00+00:00')  # >3wk before
        t = self._task(c, ip)
        build.build_bleps_and_shifts(c)
        self.assertIn(t, {b['fields']['task'] for b in self._bleps(c)})

    def test_in_scope_complete_tasks_always_blepped(self):
        # Every complete Task on a current (unfinished) job or a job finished
        # within the horizon gets a blep; only an old finished job may be skipped.
        c = self._make_converter()
        ip = self._job(c, 'in_progress', '2026-01-01T00:00:00+00:00')
        wc = self._job(c, 'work_complete', '2026-02-01T00:00:00+00:00')
        recent = self._job(c, 'completed', '2026-06-01T00:00:00+00:00',
                           '2026-06-08T00:00:00+00:00')  # now = 2026-06-08
        old = self._job(c, 'completed', '2026-03-01T00:00:00+00:00',
                        '2026-03-15T00:00:00+00:00')
        in_scope = [self._task(c, ip), self._task(c, wc), self._task(c, recent)]
        old_task = self._task(c, old)
        build.build_bleps_and_shifts(c)
        task_pks = {b['fields']['task'] for b in self._bleps(c)}
        for t in in_scope:
            self.assertIn(t, task_pks)
        self.assertNotIn(old_task, task_pks)  # out of scope: finished long ago


class AssignCurrentWorkTest(unittest.TestCase):
    """assign_current_work hands rotation workers up to three random pending
    Tasks drawn from in_progress Jobs, leaving status pending."""

    def _make_converter(self):
        return NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')

    def _user(self, c):
        pk = c.next_pk('core.user')
        c.add_fixture('core.user', pk, {'username': f'w{pk}', 'is_active': True})
        return pk

    def _job(self, c, status):
        pk = c.next_pk('jobs.job')
        c.add_fixture('jobs.job', pk, {'job_number': f'J{pk}', 'status': status})
        return pk

    def _task(self, c, job_pk, status='pending', ewt='01:00:00'):
        pk = c.next_pk('jobs.task')
        c.add_fixture('jobs.task', pk, {
            'job': job_pk, 'name': f't{pk}', 'status': status,
            'est_worker_time': ewt, 'assignee': None, 'worker_queue': None,
        })
        return pk

    def _task_fields(self, c, pk):
        return next(f['fields'] for f in c.fixture_data
                    if f['model'] == 'jobs.task' and f['pk'] == pk)

    def test_assigns_pending_in_progress_tasks_only(self):
        import random as _random
        c = self._make_converter()
        c.rotation_user_pks = [self._user(c), self._user(c)]
        ip = self._job(c, 'in_progress')
        pend = [self._task(c, ip, 'pending') for _ in range(5)]
        comp = self._task(c, ip, 'complete')
        no_ewt = self._task(c, ip, 'pending', ewt=None)
        other = self._task(c, self._job(c, 'work_complete'), 'pending')

        _random.seed(1)
        build.assign_current_work(c)

        # Pending in_progress tasks get assignees from the rotation pool.
        assigned = [p for p in pend
                    if self._task_fields(c, p)['assignee'] in c.rotation_user_pks]
        self.assertEqual(len(assigned), 5)
        # Complete task, estimate-less task, and other-job task are untouched.
        self.assertIsNone(self._task_fields(c, comp)['assignee'])
        self.assertIsNone(self._task_fields(c, no_ewt)['assignee'])
        self.assertIsNone(self._task_fields(c, other)['assignee'])
        # Tasks stay pending (assigned, not started) and get a worker_queue.
        for p in assigned:
            self.assertEqual(self._task_fields(c, p)['status'], 'pending')
            self.assertIsNotNone(self._task_fields(c, p)['worker_queue'])

    def test_at_most_three_tasks_per_worker(self):
        import random as _random
        c = self._make_converter()
        c.rotation_user_pks = [self._user(c)]
        ip = self._job(c, 'in_progress')
        pend = [self._task(c, ip, 'pending') for _ in range(10)]

        _random.seed(2)
        build.assign_current_work(c)

        worker = c.rotation_user_pks[0]
        mine = [p for p in pend if self._task_fields(c, p)['assignee'] == worker]
        self.assertEqual(len(mine), 3)
        self.assertEqual(
            sorted(self._task_fields(c, p)['worker_queue'] for p in mine),
            [0, 1, 2],
        )

    def test_deterministic_for_fixed_seed(self):
        import random as _random

        def run():
            c = self._make_converter()
            c.rotation_user_pks = [self._user(c), self._user(c)]
            ip = self._job(c, 'in_progress')
            tasks = [self._task(c, ip, 'pending') for _ in range(6)]
            _random.seed(42)
            build.assign_current_work(c)
            return {p: self._task_fields(c, p)['assignee'] for p in tasks}

        self.assertEqual(run(), run())


class FakeShipmentSynthesisTest(unittest.TestCase):
    """Focused tests for the build_shipments synthesis branch — for completed
    Jobs whose Kanban card has no checked Picked up/Delivered marker, emit a
    Shipment covering every Deliverable on the Job."""

    def _make_converter(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        c.jobs = {}
        return c

    def _add_job(self, c, status, card_checklist=''):
        pk = c.next_pk('jobs.job')
        c.add_fixture('jobs.job', pk, {
            'job_number': f'JOB{pk}', 'name': 'j', 'contact': 1, 'status': status,
            'created_date': '2026-01-01T00:00:00+00:00',
            'start_date': '2026-01-01T00:00:00+00:00',
            'due_date': None,
            'completed_date': '2026-05-01T00:00:00+00:00' if status == 'completed' else None,
            'customer_po_number': '', 'description': '', 'accent_color': '#f97066',
        })
        c.jobs[f'BASE{pk}'] = {
            'job_pk': pk, 'card': {'Checklist': card_checklist},
            'estimate_rows': [], 'primary_ref': f'BASE{pk}',
        }
        return pk

    def _add_deliverable(self, c, job_pk, description='Widget'):
        pk = c.next_pk('deliverables.deliverable')
        c.add_fixture('deliverables.deliverable', pk, {
            'job': job_pk, 'description': description, 'qty_ordered': '1.00',
            'units': 'ea', 'sort_order': 10,
            'created_at': '2026-01-01T00:00:00+00:00',
            'updated_at': '2026-01-01T00:00:00+00:00',
        })
        return pk

    def _shipments(self, c):
        return [f for f in c.fixture_data if f['model'] == 'deliverables.shipment']

    def _shipment_items(self, c):
        return [f for f in c.fixture_data
                if f['model'] == 'deliverables.shipmentitem']

    def test_completed_without_pickup_marker_gets_synthesised_shipment(self):
        c = self._make_converter()
        jp = self._add_job(c, 'completed', card_checklist='[X] cut\n[ ] sand')
        dp = self._add_deliverable(c, jp, 'Real Widget')
        build.build_shipments(c)
        ships = self._shipments(c)
        self.assertEqual(len(ships), 1)
        self.assertEqual(ships[0]['fields']['job'], jp)
        self.assertEqual(ships[0]['fields']['status'], 'picked_up')
        # Notes flagged because the shipment references a real (non-Fake)
        # Deliverable.
        self.assertEqual(ships[0]['fields']['notes'], '(Fake shipment)')
        items = self._shipment_items(c)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['fields']['deliverable'], dp)

    def test_only_fake_deliverables_get_no_fake_shipment_note(self):
        c = self._make_converter()
        jp = self._add_job(c, 'completed', card_checklist='')
        self._add_deliverable(c, jp, 'Fake Deliverable')
        build.build_shipments(c)
        ships = self._shipments(c)
        self.assertEqual(len(ships), 1)
        # The Fake Deliverable already signals the fakeness — no note needed.
        self.assertEqual(ships[0]['fields']['notes'], '')

    def test_work_complete_job_gets_no_synthesised_shipment(self):
        c = self._make_converter()
        jp = self._add_job(c, 'work_complete', card_checklist='')
        self._add_deliverable(c, jp, 'Widget')
        build.build_shipments(c)
        self.assertEqual(self._shipments(c), [])

    def test_completed_with_pickup_marker_uses_existing_marker_path(self):
        # When the Kanban card already has a checked Picked up/Delivered
        # marker, the existing pre-synthesis path emits the Shipment and the
        # synthesis branch must not run for this job (no duplicate).
        c = self._make_converter()
        jp = self._add_job(c, 'completed',
                           card_checklist='[X] Picked up/Delivered\n[X] cut')
        self._add_deliverable(c, jp, 'Widget')
        build.build_shipments(c)
        ships = self._shipments(c)
        self.assertEqual(len(ships), 1)
        # Marker-driven shipment carries no Fake-shipment note.
        self.assertEqual(ships[0]['fields']['notes'], '')


class InvoiceLineItemSourceWiringTest(unittest.TestCase):
    """Focused tests for the heuristic source-link builder — claim Tasks /
    Materials on the Job against the invoice's line items in deterministic
    order. Leftover lines stay freeform."""

    def _make_converter(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        return c

    def _add_job(self, c):
        pk = c.next_pk('jobs.job')
        c.add_fixture('jobs.job', pk, {'job_number': '00001', 'status': 'completed'})
        return pk

    def _add_task(self, c, job_pk, name='cut sheet', status='complete'):
        # Runs post-reconcile in the pipeline, so tasks carry final statuses;
        # 'complete' is the billable default the claimer accepts.
        pk = c.next_pk('jobs.task')
        c.add_fixture('jobs.task', pk, {
            'job': job_pk, 'name': name, 'status': status})
        return pk

    def _add_material(self, c, job_pk, desc='plywood sheet',
                      consumption_state='consumed'):
        # Runs post-purchasing in the pipeline, so materials carry final
        # consumption states; only 'consumed' is billable.
        pk = c.next_pk('inventory.material')
        c.add_fixture('inventory.material', pk, {
            'job': job_pk, 'description': desc,
            'consumption_state': consumption_state})
        return pk

    def _add_invoice(self, c, job_pk):
        pk = c.next_pk('invoicing.invoice')
        c.add_fixture('invoicing.invoice', pk, {'job': job_pk})
        return pk

    def _add_line(self, c, invoice_pk, line_number, kind, description=''):
        pk = c.next_pk('invoicing.invoicelineitem')
        c.add_fixture('invoicing.invoicelineitem', pk, {
            'invoice': invoice_pk,
            'line_number': line_number,
            'description': description,
        })
        # Classification is stashed in a parallel dict (build_invoices populates
        # it at emit time; the model itself has no item_type field).
        c.invoice_line_kinds[pk] = kind
        return pk

    def _sources(self, c):
        return [f for f in c.fixture_data
                if f['model'] == 'invoicing.invoicelineitemsource']

    def test_task_classified_line_claims_a_task(self):
        c = self._make_converter()
        jp = self._add_job(c)
        task_pk = self._add_task(c, jp)
        inv_pk = self._add_invoice(c, jp)
        li_pk = self._add_line(c, inv_pk, 1, 'task', 'cut and assemble')
        build.build_invoice_line_item_sources(c)
        srcs = self._sources(c)
        self.assertEqual(len(srcs), 1)
        self.assertEqual(srcs[0]['fields']['invoice_line_item'], li_pk)
        self.assertEqual(srcs[0]['fields']['source_type'], 'task')
        self.assertEqual(srcs[0]['fields']['source_pk'], task_pk)

    def test_material_classified_line_claims_a_material(self):
        c = self._make_converter()
        jp = self._add_job(c)
        mat_pk = self._add_material(c, jp, 'maple plywood sheet')
        inv_pk = self._add_invoice(c, jp)
        li_pk = self._add_line(c, inv_pk, 1, 'material', 'maple plywood sheet')
        build.build_invoice_line_item_sources(c)
        srcs = self._sources(c)
        self.assertEqual(len(srcs), 1)
        self.assertEqual(srcs[0]['fields']['source_type'], 'material')
        self.assertEqual(srcs[0]['fields']['source_pk'], mat_pk)

    def test_global_unique_no_double_claim_across_invoices(self):
        c = self._make_converter()
        jp = self._add_job(c)
        only_task = self._add_task(c, jp)
        inv1 = self._add_invoice(c, jp)
        inv2 = self._add_invoice(c, jp)
        self._add_line(c, inv1, 1, 'task', 'cut')
        li2 = self._add_line(c, inv2, 1, 'task', 'cut')
        build.build_invoice_line_item_sources(c)
        srcs = self._sources(c)
        # First invoice's line claims it; second has nothing to claim.
        self.assertEqual(len(srcs), 1)
        self.assertEqual(srcs[0]['fields']['source_pk'], only_task)
        self.assertNotEqual(srcs[0]['fields']['invoice_line_item'], li2)

    def test_no_unclaimed_atom_leaves_line_freeform(self):
        c = self._make_converter()
        jp = self._add_job(c)
        # Job has no Tasks or Materials at all.
        inv_pk = self._add_invoice(c, jp)
        self._add_line(c, inv_pk, 1, 'task', 'cut')
        build.build_invoice_line_item_sources(c)
        self.assertEqual(self._sources(c), [])

    def test_skip_and_discount_lines_never_claim(self):
        c = self._make_converter()
        jp = self._add_job(c)
        self._add_task(c, jp)
        self._add_material(c, jp)
        inv_pk = self._add_invoice(c, jp)
        # Comment lines are 'skip'; discount lines are 'lineitem' freeform.
        self._add_line(c, inv_pk, 1, 'skip', 'note for customer')
        self._add_line(c, inv_pk, 2, 'lineitem', 'volume discount')
        build.build_invoice_line_item_sources(c)
        self.assertEqual(self._sources(c), [])

    # --- billability filters (only settled work links to an invoice) ------

    def test_pending_task_is_never_claimed(self):
        c = self._make_converter()
        jp = self._add_job(c)
        self._add_task(c, jp, status='pending')
        inv_pk = self._add_invoice(c, jp)
        self._add_line(c, inv_pk, 1, 'task', 'cut and assemble')
        build.build_invoice_line_item_sources(c)
        self.assertEqual(self._sources(c), [])

    def test_cancelled_task_is_never_claimed(self):
        # The app's billability line is terminal (complete OR cancelled), but
        # converter-cancelled tasks never carry actuals (bleps only attach to
        # complete tasks), so claiming one would put a zero-work task on a
        # paid invoice. Only 'complete' claims.
        c = self._make_converter()
        jp = self._add_job(c)
        self._add_task(c, jp, status='cancelled')
        inv_pk = self._add_invoice(c, jp)
        self._add_line(c, inv_pk, 1, 'task', 'cut and assemble')
        build.build_invoice_line_item_sources(c)
        self.assertEqual(self._sources(c), [])

    def test_pending_material_is_never_claimed(self):
        c = self._make_converter()
        jp = self._add_job(c)
        self._add_material(c, jp, consumption_state='pending')
        inv_pk = self._add_invoice(c, jp)
        self._add_line(c, inv_pk, 1, 'material', 'maple plywood sheet')
        build.build_invoice_line_item_sources(c)
        self.assertEqual(self._sources(c), [])

    def test_fallthrough_skips_non_final_atoms(self):
        # A task-classified line whose job has only a pending task falls
        # through to a consumed material — never to the pending task.
        c = self._make_converter()
        jp = self._add_job(c)
        self._add_task(c, jp, status='pending')
        mat_pk = self._add_material(c, jp)
        inv_pk = self._add_invoice(c, jp)
        self._add_line(c, inv_pk, 1, 'task', 'cut and assemble')
        build.build_invoice_line_item_sources(c)
        srcs = self._sources(c)
        self.assertEqual(len(srcs), 1)
        self.assertEqual(srcs[0]['fields']['source_type'], 'material')
        self.assertEqual(srcs[0]['fields']['source_pk'], mat_pk)


class ConvertEndToEndTest(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                         'datasets not present')
    def test_convert_writes_a_fixture_file(self):
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        self.addCleanup(os.unlink, path)
        # limit=40, not 10: the newest cards can be all-fresh draft jobs with
        # unchecked checklists (zero complete tasks → zero bleps/shifts, as in
        # the 2026-07-12 re-export). 40 reaches far enough back for real
        # completed work — same reasoning as InvoiceBuilderTest's limit.
        c = NealsDataConverter(XLSX, CSV, output_path=path, limit=40)
        c.convert()
        with open(path) as f:
            raw = f.read()
        data = json.loads(raw)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        models = {row['model'] for row in data}
        self.assertIn('jobs.job', models)
        self.assertIn('estimates.estimate', models)
        self.assertIn('core.jobhistory', models)
        self.assertIn('jobs.blep', models)
        self.assertIn('core.shift', models)
        self.assertNotIn('jobs.workorder', models)
        # Fee model deleted (better-fees spec §4): the literal model string
        # and the fee source_type must never appear anywhere in output —
        # loaddata would crash on jobs.fee rows.
        self.assertNotIn('"jobs.fee"', raw)
        self.assertNotIn('"source_type": "fee"', raw)

    @unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                         'datasets not present')
    def test_archive_rule_holds_end_to_end(self):
        from datetime import datetime, timezone as tz
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        self.addCleanup(os.unlink, path)
        now = datetime(2030, 1, 1, tzinfo=tz.utc)   # far future: every closed job is old
        c = NealsDataConverter(XLSX, CSV, output_path=path, limit=40, now=now)
        c.convert()
        cutoff = build.archive_cutoff(now)
        jobs = [f for f in c.fixture_data if f['model'] == 'jobs.job']
        archived = {f['pk'] for f in jobs if f['fields']['status'] == 'archived'}
        self.assertEqual(archived, c.archived_job_pks)
        self.assertGreater(len(archived), 0)
        closed = ('completed', 'rejected', 'cancelled')
        for f in jobs:
            st = f['fields']['status']
            cd = build._aware(f['fields'].get('completed_date'))
            if st == 'archived':
                # archived => it was an old closed job
                self.assertIn(c.archived_outcome[f['pk']], closed)
                self.assertIsNotNone(cd)
                self.assertLessEqual(cd, cutoff)
            elif st in closed:
                # a closed job left live => it is younger than the cutoff
                self.assertTrue(cd is None or cd > cutoff, f['fields']['job_number'])
        # nothing invented survives on an archive
        for f in c.fixture_data:
            if f['model'] in ('deliverables.deliverable', 'deliverables.shipment', 'jobs.blep',
                              'inventory.earmark', 'purchasing.purchaseorderlineitem'):
                self.assertNotIn(f['fields'].get('job'), archived, f['model'])


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class ConvertedStateInvariantsTest(unittest.TestCase):
    """Full-pipeline invariants the running app enforces and the converted
    fixture must therefore satisfy (2026-07-12 tasks refinements):

    - only settled work links to an invoice (complete tasks / consumed
      materials — the app's billability line is terminal, and converter
      cancelled tasks carry no actuals);
    - work_complete/completed means every task terminal and no pending
      material (the B4 work-complete gate in JobService.update_job);
    - a cancelled task keeps no pending materials attached (the app's
      cancel_task detaches them to the job as loose rows).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        # limit=100 (the CLI default): a wide-enough slice that the
        # invariants sweep old finished jobs too, not just the recent
        # all-draft tail. (Tests exercise the conversion itself, against
        # datasets/ inputs — never any shipped fixture artifact.)
        c = NealsDataConverter(XLSX, CSV, output_path=path, limit=100)
        c.convert()
        os.unlink(path)
        cls.data = c.fixture_data
        cls.tasks = {f['pk']: f['fields'] for f in cls.data
                     if f['model'] == 'jobs.task'}
        cls.materials = {f['pk']: f['fields'] for f in cls.data
                         if f['model'] == 'inventory.material'}
        cls.jobs = {f['pk']: f['fields'] for f in cls.data
                    if f['model'] == 'jobs.job'}
        cls.sources = [f['fields'] for f in cls.data
                       if f['model'] == 'invoicing.invoicelineitemsource']

    def test_invoice_sources_only_link_complete_tasks(self):
        offenders = [
            (s['source_pk'], self.tasks[s['source_pk']].get('status'))
            for s in self.sources if s['source_type'] == 'task'
            and self.tasks[s['source_pk']].get('status') != 'complete'
        ]
        self.assertEqual(offenders, [],
                         f'non-complete tasks linked to invoices: {offenders}')

    def test_invoice_sources_only_link_consumed_materials(self):
        offenders = [
            (s['source_pk'],
             self.materials[s['source_pk']].get('consumption_state'))
            for s in self.sources if s['source_type'] == 'material'
            and self.materials[s['source_pk']].get('consumption_state')
            != 'consumed'
        ]
        self.assertEqual(offenders, [],
                         f'unconsumed materials linked to invoices: {offenders}')

    def test_work_complete_jobs_have_only_terminal_tasks(self):
        closed = {pk for pk, jf in self.jobs.items()
                  if jf.get('status') in ('work_complete', 'completed')}
        offenders = [
            (pk, tf.get('status'), tf.get('job'))
            for pk, tf in self.tasks.items()
            if tf.get('job') in closed
            and tf.get('status') not in ('complete', 'cancelled')
        ]
        self.assertEqual(offenders, [],
                         f'open tasks on closed jobs: {offenders}')

    def test_work_complete_jobs_have_no_pending_materials(self):
        closed = {pk for pk, jf in self.jobs.items()
                  if jf.get('status') in ('work_complete', 'completed')}
        offenders = [
            (pk, mf.get('job'))
            for pk, mf in self.materials.items()
            if mf.get('job') in closed
            and mf.get('consumption_state') == 'pending'
            and Decimal(mf.get('quantity') or '0') > 0
        ]
        self.assertEqual(offenders, [],
                         f'pending materials on closed jobs: {offenders}')

    def test_cancelled_tasks_keep_no_pending_materials_attached(self):
        cancelled = {pk for pk, tf in self.tasks.items()
                     if tf.get('status') == 'cancelled'}
        offenders = [
            (pk, mf.get('task'))
            for pk, mf in self.materials.items()
            if mf.get('task') in cancelled
            and mf.get('consumption_state') == 'pending'
        ]
        self.assertEqual(offenders, [],
                         f'pending materials still on cancelled tasks: {offenders}')

    def test_no_invoice_on_pre_approval_job(self):
        pre = {pk for pk, jf in self.jobs.items()
               if jf.get('status') in ('draft', 'submitted', 'rejected')}
        offenders = [
            (f['pk'], f['fields']['job'])
            for f in self.data if f['model'] == 'invoicing.invoice'
            and f['fields']['job'] in pre
        ]
        self.assertEqual(offenders, [],
                         f'invoices on pre-approval jobs: {offenders}')

    def test_no_unanswered_lines_on_accepted_estimates_of_approved_plus_jobs(self):
        # Task 5's answeredness rule (EstimateService.unanswered_lines): on
        # an ACCEPTED estimate, a line is UNANSWERED iff non-adjustment,
        # non-deposit, carries no EstimateLineItemSource, and
        # work_declined=False. A converted job sitting at approved-or-beyond
        # must never surface a phantom checklist item — build_checklist_declines
        # (ES Task 9) marks every such line work_declined=True during
        # conversion so JobService.maybe_auto_release's invariant holds
        # without a data-repair pass.
        approved_or_beyond = {'approved', 'in_progress', 'work_complete',
                              'completed', 'cancelled'}
        deposit_acs = {f['pk'] for f in self.data
                       if f['model'] == 'core.accountingcategory'
                       and f['fields'].get('is_deposit')}
        sourced = {f['fields']['estimate_line_item'] for f in self.data
                  if f['model'] == 'estimates.estimatelineitemsource'}
        estimates = {f['pk']: f['fields'] for f in self.data
                    if f['model'] == 'estimates.estimate'}
        offenders = []
        for f in self.data:
            if f['model'] != 'estimates.estimatelineitem':
                continue
            fields = f['fields']
            est = estimates.get(fields['estimate'])
            if est is None or est.get('status') != 'accepted':
                continue
            if self.jobs.get(est['job'], {}).get('status') not in approved_or_beyond:
                continue
            if fields.get('adjustment_service') is not None:
                continue
            if fields.get('accounting_category') in deposit_acs:
                continue
            if f['pk'] in sourced:
                continue
            if fields.get('work_declined'):
                continue
            offenders.append((f['pk'], fields['estimate']))
        self.assertEqual(
            offenders, [],
            f'unanswered lines on accepted estimates of approved+ jobs: {offenders}')

    def test_earmarks_covered_by_qty_on_hand(self):
        items = {f['pk']: f['fields'] for f in self.data
                 if f['model'] == 'inventory.inventoryitem'}
        earmarked = {}
        for f in self.data:
            if f['model'] == 'inventory.earmark':
                item = f['fields']['inventory_item']
                earmarked[item] = (earmarked.get(item, Decimal('0'))
                                   + Decimal(f['fields']['quantity']))
        offenders = [
            (item, str(total), items[item].get('qty_on_hand'))
            for item, total in earmarked.items()
            if total > Decimal(items[item].get('qty_on_hand') or '0')
        ]
        self.assertEqual(offenders, [],
                         f'earmarks exceed QOH: {offenders}')


class DocumentCounterReconcileTest(unittest.TestCase):
    """Dataset-independent: _pass_document_counters writes emitted record
    counts onto the core.APPSTATE counter rows — migration 0018 moved the
    machine counters out of Configuration, and the pass silently no-opped
    while it still looked them up under core.configuration."""

    def test_counters_land_on_appstate(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        for key in ('job_counter', 'invoice_counter', 'po_counter'):
            c.add_fixture('core.appstate', key, {'value': '0'})
        for _ in range(3):
            c.add_fixture('jobs.job', c.next_pk('jobs.job'), {'status': 'draft'})
        c.add_fixture('invoicing.invoice', c.next_pk('invoicing.invoice'), {})
        index = {(f['model'], f.get('pk')): f for f in c.fixture_data}
        reconcile._pass_document_counters(c, index)
        appstate = {f['pk']: f['fields']['value'] for f in c.fixture_data
                    if f['model'] == 'core.appstate'}
        self.assertEqual(appstate['job_counter'], '3')
        self.assertEqual(appstate['invoice_counter'], '1')
        # No POs emitted at reconcile time (build_purchasing runs later and
        # advances po_counter itself) — the pass writes the honest zero.
        self.assertEqual(appstate['po_counter'], '0')


class ArchivedJobHistoryTest(unittest.TestCase):
    """build_history gives archived jobs exactly what ArchiveImportService leaves."""

    NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    NOW_S = NOW.isoformat()

    def _converter(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json',
                               now=self.NOW)
        return c

    def _rows(self, c, job_objs):
        models = ('core.jobhistory', 'core.crmhistory', 'core.purchasinghistory')
        out = []
        for r in c.fixture_data:
            if r['model'] not in models:
                continue
            f = r['fields']
            if (f['object_type'], f['object_id']) in job_objs:
                self.assertIsNone(f['user'])
                out.append((f['entry_type'], f['object_type'], f['object_id'],
                            f['changes'], f['text'], f['timestamp']))
        return sorted(out, key=lambda t: (t[5], t[0], t[1], t[2], t[4]))

    def _build(self, c, start_date, completed_date, status, checklist, outcome):
        c.add_fixture('jobs.job', 1, {
            'created_date': '2020-01-01T00:00:00+00:00', 'start_date': start_date,
            'completed_date': completed_date, 'status': 'archived'})
        c.add_fixture('jobs.task', 2, {'job': 1})
        c.add_fixture('estimates.estimate', 3, {'job': 1, 'created_date': '2020-01-02T00:00:00+00:00'})
        c.add_fixture('inventory.material', 4, {'job': 1})
        c.add_fixture('invoicing.invoice', 7, {'job': 1, 'created_date': '2020-02-01T00:00:00+00:00'})
        c.archived_job_pks = {1}
        c.archived_outcome = {1: outcome}
        c.jobs['K1'] = {'job_pk': 1, 'card': {'Checklist': checklist}}
        build.build_history(c)

    def _audits(self):
        return [('audit', t, i, {'_created': True}, '', self.NOW_S)
                for t, i in (('job', 1), ('task', 2), ('material', 4),
                             ('estimate', 3), ('invoice', 7))]

    def test_completed_archive_rows(self):
        c = self._converter()
        self._build(c, '2020-01-05T00:00:00+00:00', '2020-03-01T00:00:00+00:00',
                    'archived', '[X] Picked up/Delivered', 'completed')
        objs = {('job', 1), ('task', 2), ('material', 4), ('estimate', 3), ('invoice', 7)}
        expected = self._audits() + [
            ('action', 'job', 1, {'_action': 'Created'}, '', '2020-01-01T00:00:00+00:00'),
            ('action', 'job', 1, {'_action': 'Started'}, '', '2020-01-05T00:00:00+00:00'),
            ('action', 'job', 1, {'_action': 'Completed'}, '', '2020-03-01T00:00:00+00:00'),
            # changes None, not {}: record_history's default for a note row
            ('note', 'job', 1, None, 'Picked up/Delivered (Kanban checklist)',
             '2020-03-01T00:00:00+00:00'),
            ('action', 'job', 1, {'_action': 'Imported from Kanban'}, '', self.NOW_S),
        ]
        key = lambda t: (t[5], t[0], t[1], t[2], t[4])
        self.assertEqual(self._rows(c, objs), sorted(expected, key=key))

    def test_rejected_archive_rows(self):
        c = self._converter()
        self._build(c, None, '2020-03-01T00:00:00+00:00', 'archived',
                    '[ ] Picked up/Delivered', 'rejected')
        objs = {('job', 1), ('task', 2), ('material', 4), ('estimate', 3), ('invoice', 7)}
        expected = self._audits() + [
            ('action', 'job', 1, {'_action': 'Created'}, '', '2020-01-01T00:00:00+00:00'),
            ('action', 'job', 1, {'_action': 'Rejected'}, '', '2020-03-01T00:00:00+00:00'),
            ('action', 'job', 1, {'_action': 'Imported from Kanban'}, '', self.NOW_S),
        ]
        key = lambda t: (t[5], t[0], t[1], t[2], t[4])
        self.assertEqual(self._rows(c, objs), sorted(expected, key=key))

    def test_live_jobs_unchanged(self):
        c = self._converter()
        c.add_fixture('jobs.job', 1, {'created_date': '2025-03-01T00:00:00+00:00', 'status': 'rejected'})
        c.add_fixture('estimates.estimate', 10, {'job': 1, 'status': 'expired'})
        c.archived_job_pks = {99}
        c.archived_outcome = {}
        build.build_history(c)
        labels = [r['fields']['changes'].get('_action') for r in c.fixture_data
                  if r['model'] == 'core.jobhistory' and r['fields']['object_type'] == 'estimate']
        self.assertIn('Expired', labels)
        self.assertNotIn(self.NOW_S, [r['fields']['timestamp'] for r in c.fixture_data
                                      if r['model'] == 'core.jobhistory'])


class BuildHistoryUnitTest(unittest.TestCase):
    """Dataset-independent: drives build_history off a hand-built fixture list."""

    def _converter(self):
        # Loader __init__ is lazy (stores the path), so dummy paths are fine —
        # we never call load(); we only use fixture_data / next_pk / add_fixture.
        return NealsDataConverter('x.xlsx', 'x.csv', output_path='/tmp/x.json')

    def _history(self, c):
        models = ('core.jobhistory', 'core.crmhistory', 'core.purchasinghistory')
        return [f for f in c.fixture_data if f['model'] in models]

    def test_created_entry_for_tracked_objects_only(self):
        c = self._converter()
        c.add_fixture('jobs.job', 1, {'created_date': '2025-03-01T00:00:00+00:00'})
        c.add_fixture('jobs.task', 2, {'job': 1})
        c.add_fixture('estimates.estimate', 3, {'job': 1, 'created_date': '2025-03-02T00:00:00+00:00'})
        c.add_fixture('inventory.material', 4, {'job': 1})
        c.add_fixture('deliverables.deliverable', 5, {'job': 1, 'created_at': '2025-03-03T00:00:00+00:00'})
        c.add_fixture('deliverables.shipment', 6, {'job': 1, 'created_at': '2025-03-04T00:00:00+00:00'})
        c.add_fixture('invoicing.invoice', 7, {'job': 1, 'created_date': '2025-03-05T00:00:00+00:00'})
        c.add_fixture('contacts.contact', 8, {})
        c.add_fixture('contacts.business', 9, {})
        # untracked — must NOT get history
        c.add_fixture('inventory.inventoryitem', 12, {})

        build.build_history(c)

        got = {(r['fields']['object_type'], r['fields']['object_id']) for r in self._history(c)}
        self.assertEqual(got, {
            ('job', 1), ('task', 2), ('estimate', 3), ('material', 4),
            ('deliverable', 5), ('shipment', 6), ('invoice', 7),
            ('contact', 8), ('business', 9),
        })
        for r in self._history(c):
            self.assertEqual(r['fields']['entry_type'], 'audit')
            self.assertEqual(r['fields']['changes'], {'_created': True})
            self.assertIsNone(r['fields']['user'])

    def test_job_created_anchored_children_ordered_after(self):
        c = self._converter()
        c.add_fixture('jobs.job', 1, {'created_date': '2025-03-01T00:00:00+00:00', 'status': 'completed'})
        c.add_fixture('estimates.estimate', 2, {'job': 1, 'status': 'accepted'})
        c.add_fixture('jobs.task', 3, {'job': 1, 'status': 'complete'})
        c.add_fixture('contacts.contact', 4, {})  # no Job -> fallback constant

        build.build_history(c)

        created = {}
        for r in self._history(c):
            f = r['fields']
            if f['changes'].get('_created'):
                created[(f['object_type'], f['object_id'])] = f['timestamp']
        # Job creation keeps the real job created_date; children sort after it.
        self.assertEqual(created[('job', 1)], '2025-03-01T00:00:00+00:00')
        self.assertGreater(created[('estimate', 2)], created[('job', 1)])
        self.assertGreater(created[('task', 3)], created[('estimate', 2)])
        # Job-less object falls back to the constant.
        self.assertEqual(created[('contact', 4)], '2024-01-01T00:00:00+00:00')

    def _for(self, c, otype, oid):
        return [r['fields'] for r in self._history(c)
                if r['fields']['object_type'] == otype and r['fields']['object_id'] == oid]

    @staticmethod
    def _sorted_fields(history_rows):
        return [r['fields'] for r in sorted(history_rows, key=lambda r: r['fields']['timestamp'])]

    def test_full_lifecycle_causal_order(self):
        c = self._converter()
        c.add_fixture('jobs.job', 1, {'created_date': '2025-03-01T00:00:00+00:00', 'status': 'completed'})
        c.add_fixture('estimates.estimate', 10, {'job': 1, 'status': 'accepted'})
        c.add_fixture('deliverables.deliverable', 20, {'job': 1})
        c.add_fixture('jobs.task', 30, {'job': 1, 'status': 'complete'})
        c.add_fixture('inventory.material', 40, {'job': 1, 'consumption_state': 'consumed'})
        c.add_fixture('deliverables.shipment', 50, {'job': 1, 'status': 'picked_up'})
        c.add_fixture('invoicing.invoice', 60, {'job': 1, 'status': 'paid'})

        build.build_history(c)
        fields = self._sorted_fields(self._history(c))

        def idx(otype, pred):
            return next(i for i, f in enumerate(fields)
                        if f['object_type'] == otype and pred(f['changes']))

        seq = [
            idx('job', lambda ch: ch.get('_created')),
            idx('estimate', lambda ch: ch.get('_created')),
            idx('deliverable', lambda ch: ch.get('_created')),
            idx('estimate', lambda ch: ch.get('_action') == 'Sent to the customer'),
            idx('estimate', lambda ch: ch.get('_action') == 'Accepted by the customer'),
            idx('job', lambda ch: str(ch.get('_action', '')).startswith('Approved')),
            idx('task', lambda ch: ch.get('_created')),
            idx('job', lambda ch: ch.get('_action') == 'Work started on the floor'),
            idx('invoice', lambda ch: ch.get('_created')),
            idx('task', lambda ch: ch.get('status', {}).get('new') == 'complete'),
            idx('job', lambda ch: ch.get('_action') == 'Work completed'),
            idx('invoice', lambda ch: ch.get('_action') == 'Sent to the customer'),
            idx('invoice', lambda ch: ch.get('_action') == 'Paid in full'),
            idx('job', lambda ch: ch.get('_action') == 'Job closed out'),
        ]
        self.assertEqual(seq, sorted(seq), 'lifecycle entries are not in causal order')

        # Task completion is a bare audit diff (no _action label).
        task_done = fields[idx('task', lambda ch: ch.get('status', {}).get('new') == 'complete')]
        self.assertNotIn('_action', task_done['changes'])
        # Estimate accepted and job approved fall in the same phase (same day).
        acc = fields[idx('estimate', lambda ch: ch.get('_action') == 'Accepted by the customer')]['timestamp']
        app = fields[idx('job', lambda ch: str(ch.get('_action', '')).startswith('Approved'))]['timestamp']
        self.assertEqual(acc[:10], app[:10])

    def test_rejected_job_lands_after_estimate_lapses(self):
        c = self._converter()
        c.add_fixture('jobs.job', 1, {'created_date': '2025-03-01T00:00:00+00:00', 'status': 'rejected'})
        c.add_fixture('estimates.estimate', 10, {'job': 1, 'status': 'expired'})

        build.build_history(c)
        fields = self._sorted_fields(self._history(c))

        def idx(otype, pred):
            return next(i for i, f in enumerate(fields)
                        if f['object_type'] == otype and pred(f['changes']))

        seq = [
            idx('job', lambda ch: ch.get('_created')),
            idx('estimate', lambda ch: ch.get('_created')),
            idx('estimate', lambda ch: ch.get('_action') == 'Sent to the customer'),
            idx('estimate', lambda ch: ch.get('_action') == 'Expired'),
            idx('job', lambda ch: ch.get('_action') == 'Rejected'),
        ]
        self.assertEqual(seq, sorted(seq))
        # The job rejection is the final entry, and the job was never approved.
        self.assertEqual(fields[-1]['object_type'], 'job')
        self.assertEqual(fields[-1]['changes']['_action'], 'Rejected')
        self.assertFalse(any('Approved' in str(f['changes'].get('_action', '')) for f in fields))

    def test_initial_status_emits_no_transition(self):
        c = self._converter()
        c.add_fixture('jobs.job', 1, {'created_date': '2025-03-01T00:00:00+00:00', 'status': 'draft'})
        c.add_fixture('jobs.task', 2, {'job': 1, 'status': 'pending'})
        build.build_history(c)
        # only the _created entry for each — no status diffs
        self.assertEqual(len(self._for(c, 'job', 1)), 1)
        self.assertEqual(len(self._for(c, 'task', 2)), 1)


class BlepShiftSynthesisTest(unittest.TestCase):
    """Bleps + Shifts for complete tasks: window placement, enclosure, no
    per-user overlap, entered_qty actuals. Synthetic state for control."""

    # scheme pk -> algorithm, for _add_task's qty_source (task-owned money:
    # build_bleps_and_shifts now reads the task's own qty_source directly,
    # not a rate_scheme indirection).
    _SCHEME_ALGO = {10: 'elapsed_time', 11: 'entered_qty'}

    def _converter(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        # Two seed-style users in the rotation pool.
        c.user_by_username = {'u1': 1, 'u2': 2}
        c.rotation_user_pks = [1, 2]
        c._pk_counters['core.user'] = 2
        return c

    def _add_job(self, c, pk, status='completed',
                 start='2026-01-05T00:00:00+00:00',
                 completed='2026-02-05T00:00:00+00:00'):
        c.add_fixture('jobs.job', pk, {
            'job_number': f'J{pk}', 'name': 'j', 'contact': 1, 'status': status,
            'created_date': '2026-01-04T00:00:00+00:00', 'start_date': start,
            'due_date': None,
            'completed_date': completed if status == 'completed' else None,
            'customer_po_number': '', 'description': '', 'accent_color': '#f97066',
        })

    def _add_task(self, c, pk, job, status='complete', scheme=10,
                  ewt='02:00:00', est_qty=None, sort_order=1):
        c.add_fixture('jobs.task', pk, {
            'job': job, 'source_scheme': scheme,
            'qty_source': self._SCHEME_ALGO[scheme], 'rate': None,
            'unit_label': 'none', 'accounting_category': None,
            'name': f't{pk}', 'description': '',
            'est_qty': est_qty, 'est_worker_time': ewt, 'actual_qty': None,
            'active_modifiers': [], 'status': status, 'blocked_reason': '',
            'worker_queue': None, 'assignee': None, 'parent_task': None,
            'sort_order': sort_order,
        })

    def _m(self, c, model):
        return [f for f in c.fixture_data if f['model'] == model]

    def test_one_blep_per_complete_task_only(self):
        c = self._converter()
        self._add_job(c, 1)
        self._add_task(c, 10, 1, status='complete', sort_order=1)
        self._add_task(c, 11, 1, status='pending', sort_order=2)
        build.build_bleps_and_shifts(c)
        bleps = self._m(c, 'jobs.blep')
        self.assertEqual(len(bleps), 1)
        self.assertEqual(bleps[0]['fields']['task'], 10)

    def test_bleps_inside_job_window_and_enclosed_no_overlap(self):
        from datetime import datetime
        c = self._converter()
        # Several jobs, many complete tasks, to exercise placement.
        for j in range(1, 4):
            self._add_job(c, j)
            for t in range(5):
                self._add_task(c, 100 * j + t, j, sort_order=t)
        build.build_bleps_and_shifts(c)
        bleps = self._m(c, 'jobs.blep')
        shifts = self._m(c, 'core.shift')
        self.assertEqual(len(bleps), 15)
        self.assertTrue(shifts)

        def dt(s):
            return datetime.fromisoformat(s.replace('Z', '+00:00'))

        # All blep times are whole-minute and end >= start.
        for b in bleps:
            s, e = dt(b['fields']['start_time']), dt(b['fields']['end_time'])
            self.assertEqual(s.second, 0)
            self.assertEqual(e.second, 0)
            self.assertGreaterEqual(e, s)

        # Enclosure + no per-user overlap.
        from collections import defaultdict
        sh = defaultdict(list)
        for s in shifts:
            f = s['fields']
            sh[f['user']].append((dt(f['start_time']), dt(f['end_time'])))
        bl = defaultdict(list)
        for b in bleps:
            f = b['fields']
            bl[f['user']].append((dt(f['start_time']), dt(f['end_time'])))
        for u, items in bl.items():
            for s, e in items:
                self.assertTrue(any(ss <= s and e <= ee for ss, ee in sh[u]),
                                f'blep {s}-{e} not enclosed for user {u}')
            ordered = sorted(items)
            for (s1, e1), (s2, e2) in zip(ordered, ordered[1:]):
                self.assertGreaterEqual(s2, e1, f'overlap for user {u}')

    def test_minting_when_pool_saturated(self):
        # One user, a one-day window, more tasks than fit in a single 8h day →
        # extra users get minted.
        c = self._converter()
        c.user_by_username = {'u1': 1}
        c.rotation_user_pks = [1]
        c._pk_counters['core.user'] = 1
        self._add_job(c, 1, start='2026-03-02T00:00:00+00:00',
                      completed='2026-03-02T00:00:00+00:00')
        for t in range(6):  # 6 × ~2h = 12h > one 8h day
            self._add_task(c, 50 + t, 1, ewt='02:00:00', sort_order=t)
        build.build_bleps_and_shifts(c)
        users = self._m(c, 'core.user')
        self.assertGreater(len(users), 0)  # minted at least one extra worker
        minted = [u for u in users if u['fields']['username'].startswith('worker')]
        self.assertTrue(minted)
        # Still no per-user overlap.
        from collections import defaultdict
        from datetime import datetime
        bl = defaultdict(list)
        for b in self._m(c, 'jobs.blep'):
            f = b['fields']
            bl[f['user']].append((datetime.fromisoformat(f['start_time'].replace('Z', '+00:00')),
                                  datetime.fromisoformat(f['end_time'].replace('Z', '+00:00'))))
        for u, items in bl.items():
            ordered = sorted(items)
            for (s1, e1), (s2, e2) in zip(ordered, ordered[1:]):
                self.assertGreaterEqual(s2, e1)

    def test_blepped_task_gets_assignee_of_its_blep_user(self):
        c = self._converter()
        self._add_job(c, 1)
        self._add_task(c, 10, 1, status='complete')
        self._add_task(c, 11, 1, status='pending')
        build.build_bleps_and_shifts(c)
        blep = self._m(c, 'jobs.blep')[0]
        by_pk = {f['pk']: f['fields'] for f in self._m(c, 'jobs.task')}
        self.assertEqual(blep['fields']['task'], 10)
        self.assertEqual(by_pk[10]['assignee'], blep['fields']['user'])
        self.assertIsNone(by_pk[11]['assignee'])  # no blep, no assignee

    def test_entered_qty_complete_tasks_get_actual_qty(self):
        c = self._converter()
        self._add_job(c, 1)
        # entered_qty scheme (11): est_qty present and absent.
        self._add_task(c, 20, 1, scheme=11, est_qty='4.00', sort_order=1)
        self._add_task(c, 21, 1, scheme=11, est_qty=None, sort_order=2)
        # elapsed_time scheme (10): actual_qty stays None (bleps drive it).
        self._add_task(c, 22, 1, scheme=10, sort_order=3)
        build.build_bleps_and_shifts(c)
        by_pk = {f['pk']: f['fields'] for f in self._m(c, 'jobs.task')}
        self.assertIsNotNone(by_pk[20]['actual_qty'])
        self.assertIsNotNone(by_pk[21]['actual_qty'])
        self.assertIsNone(by_pk[22]['actual_qty'])


class EstQuantityHeuristicTest(unittest.TestCase):
    """assign_est_quantities fills est_qty on real Tasks by scheme algorithm."""

    # scheme pk -> algorithm, for _add_task's qty_source. 'flat_fee' isn't a
    # real Task.qty_source choice (fixed charges stay plain document lines,
    # never Tasks) — kept as a value assign_est_quantities' branches don't
    # match, to exercise the "leaves est_qty untouched" fallthrough.
    _SCHEME_ALGO = {1: 'elapsed_time', 2: 'entered_qty', 3: 'flat_fee'}

    def _converter(self):
        return NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')

    def _add_task(self, c, pk, scheme, ewt='02:30:00', est_qty=None):
        c.add_fixture('jobs.task', pk, {
            'job': 1, 'source_scheme': scheme,
            'qty_source': self._SCHEME_ALGO[scheme], 'rate': None,
            'unit_label': 'none', 'accounting_category': None,
            'name': 't', 'description': '',
            'est_qty': est_qty, 'est_worker_time': ewt, 'actual_qty': None,
            'active_modifiers': [], 'status': 'complete', 'blocked_reason': '',
            'worker_queue': None, 'assignee': None, 'parent_task': None,
            'sort_order': 1,
        })

    def _qty(self, c, pk):
        return next(f['fields']['est_qty'] for f in c.fixture_data if f['pk'] == pk)

    def test_elapsed_time_est_qty_equals_worker_hours(self):
        c = self._converter()
        self._add_task(c, 10, 1, ewt='02:30:00')
        build.assign_est_quantities(c)
        self.assertEqual(self._qty(c, 10), '2.50')

    def test_elapsed_time_overrides_source_qty(self):
        c = self._converter()
        self._add_task(c, 10, 1, ewt='01:00:00', est_qty='5.00')
        build.assign_est_quantities(c)
        self.assertEqual(self._qty(c, 10), '1.00')

    def test_non_work_algorithm_leaves_est_qty_untouched(self):
        # Fixed charges stay plain document lines (no est_qty), never Tasks,
        # so assign_est_quantities only fills elapsed_time / entered_qty Tasks
        # and leaves any other scheme's est_qty exactly as the source set it.
        c = self._converter()
        self._add_task(c, 10, 3, est_qty=None)
        self._add_task(c, 11, 3, est_qty='3.00')
        build.assign_est_quantities(c)
        self.assertIsNone(self._qty(c, 10))
        self.assertEqual(self._qty(c, 11), '3.00')

    def test_entered_qty_generated_when_missing_kept_when_present(self):
        import random as _random
        _random.seed(7)
        c = self._converter()
        self._add_task(c, 10, 2, ewt='02:00:00', est_qty=None)
        self._add_task(c, 11, 2, est_qty='7.00')
        build.assign_est_quantities(c)
        self.assertGreaterEqual(Decimal(self._qty(c, 10)), Decimal('1'))
        self.assertEqual(self._qty(c, 11), '7.00')


class ProjectManagerAssignmentTest(unittest.TestCase):
    """assign_project_managers gives a rotation-pool PM to every non-draft Job."""

    def _converter(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        c.rotation_user_pks = [1, 2, 3]
        return c

    def _add_job(self, c, pk, status):
        c.add_fixture('jobs.job', pk, {
            'job_number': f'J{pk}', 'name': 'j', 'contact': 1, 'status': status,
            'created_date': '2026-01-01T00:00:00+00:00', 'start_date': None,
            'due_date': None, 'completed_date': None, 'customer_po_number': '',
            'description': '', 'accent_color': '#f97066', 'on_hold': False,
            'hold_reason': '', 'project_manager': None,
        })

    def test_non_draft_jobs_get_pm_draft_does_not(self):
        import random as _random
        _random.seed(3)
        c = self._converter()
        self._add_job(c, 1, 'draft')
        for pk, st in ((2, 'submitted'), (3, 'in_progress'), (4, 'completed'),
                       (5, 'rejected'), (6, 'cancelled')):
            self._add_job(c, pk, st)
        build.assign_project_managers(c)
        by_pk = {f['pk']: f['fields'] for f in c.fixture_data if f['model'] == 'jobs.job'}
        self.assertIsNone(by_pk[1]['project_manager'])
        for pk in (2, 3, 4, 5, 6):
            self.assertIn(by_pk[pk]['project_manager'], (1, 2, 3),
                          f'job {pk} PM not from rotation pool')

    def test_no_pool_is_a_noop(self):
        c = self._converter()
        c.rotation_user_pks = []
        self._add_job(c, 1, 'in_progress')
        build.assign_project_managers(c)
        f = next(x['fields'] for x in c.fixture_data if x['pk'] == 1)
        self.assertIsNone(f['project_manager'])


class JobDateSwapTest(unittest.TestCase):
    """created_date = earliest estimate − 1 day; start_date = latest estimate."""

    def _converter(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        c.jobs = {}
        c.job_map = {}
        c.estimates = {}
        return c

    def test_started_job_created_before_start(self):
        c = self._converter()
        pk = c.next_pk('jobs.job')
        c.add_fixture('jobs.job', pk, {
            'job_number': '00001', 'name': 'j', 'contact': 1, 'status': 'in_progress',
            'created_date': '2026-01-09T00:00:00+00:00',  # earliest(01-10) − 1 day
            'start_date': None, 'due_date': None, 'completed_date': None,
            'customer_po_number': '', 'description': '', 'accent_color': '#f97066',
        })
        c.job_map['00001'] = pk
        c.jobs['00001'] = {'job_pk': pk, 'card': {}, 'estimate_rows': [], 'primary_ref': '00001'}
        c.estimates['00001'] = [
            {'est_pk': 1, 'status': 'accepted', 'created_date': '2026-01-10', 'version': 1, 'base_ref': '00001'},
            {'est_pk': 2, 'status': 'accepted', 'created_date': '2026-01-20', 'version': 2, 'base_ref': '00001'},
        ]
        reconcile.reconcile(c)
        f = next(x['fields'] for x in c.fixture_data
                 if x['model'] == 'jobs.job' and x['pk'] == pk)
        # start_date = latest estimate (v2, 01-20); created_date < start_date.
        self.assertEqual(f['start_date'], '2026-01-20T00:00:00+00:00')
        self.assertLess(f['created_date'], f['start_date'])


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class InvoiceDatesAndPaidAmountTest(unittest.TestCase):
    """sent_date for open/paid; qbo_amount_paid (per-invoice line total) for paid."""

    def _setup(self, limit=15):
        c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=limit)
        c.loader.load()
        c.csv_cards = c.csv_loader.load()
        c.spine = c.select_spine()
        build.build_seed(c)
        build.build_contacts_and_businesses(c)
        build.build_jobs(c)
        build.build_estimates(c)
        build.derive_atoms(c)
        build.build_invoices(c)
        return c

    def test_sent_date_and_paid_amount(self):
        c = self._setup()
        invs = [f for f in c.fixture_data if f['model'] == 'invoicing.invoice']
        lines = [f for f in c.fixture_data if f['model'] == 'invoicing.invoicelineitem']
        from collections import defaultdict
        from decimal import Decimal as D
        tot = defaultdict(lambda: D('0'))
        for li in lines:
            tot[li['fields']['invoice']] += D(li['fields']['qty']) * D(li['fields']['price'])
        for inv in invs:
            f = inv['fields']
            if f['status'] in ('open', 'paid'):
                self.assertEqual(f['sent_date'], f['created_date'])
            else:
                self.assertIsNone(f['sent_date'])
            if f['status'] == 'paid':
                self.assertEqual(
                    D(f['qbo_amount_paid']),
                    tot[inv['pk']].quantize(D('0.01')))
            else:
                self.assertIsNone(f['qbo_amount_paid'])


class ContactResolutionTest(unittest.TestCase):
    """Synthetic (dataset-free) tests for the name-resolution rewrite:
    canonicalization against the FreeAgent Contacts sheet, the
    individual-vs-business split, multi-contact businesses, and force-distinct."""

    class _Stub:
        def __init__(self, contacts_rows, spine):
            from types import SimpleNamespace
            self.loader = SimpleNamespace(sheets_data={
                'Contacts': contacts_rows, 'Projects': [], 'Bills': []})
            self.spine = spine
            self.fixture_data = []
            self._pk = {}
            self.entity_map = {}
            self.entry_contact = {}

        def next_pk(self, model):
            self._pk[model] = self._pk.get(model, 0) + 1
            return self._pk[model]

        def add_fixture(self, model, pk, fields):
            self.fixture_data.append(
                {'model': model, 'pk': pk, 'fields': fields})

    @staticmethod
    def _card(name):
        return {'card': {'Name': name}, 'base_ref': name, 'estimate_rows': []}

    def setUp(self):
        contacts = [
            {'Organisation': 'Acme Inc.', 'First Name': 'Jane',
             'Last Name': 'Doe', 'Email': 'jane@acme.example'},
            {'Organisation': 'HMC Architects', 'First Name': 'Hank',
             'Last Name': 'M', 'Email': 'h@hmc.example'},
            {'Organisation': 'Waveworks', 'First Name': 'Wendy',
             'Last Name': 'W', 'Email': 'w@wave.example'},
            {'Organisation': '', 'First Name': 'James',
             'Last Name': 'Sandersfeld', 'Email': 'js@x.example'},
        ]
        spine = [
            self._card('Acme (Bob Smith)'),     # business + person
            self._card('acme (Carol King)'),    # same business (norm) + person
            self._card('James Sandersfeld'),    # individual (blank-org person)
            self._card('Wave Works'),           # fuzzy -> Waveworks
        ]
        self.c = self._Stub(contacts, spine)
        build.build_contacts_and_businesses(self.c)

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def test_canonical_merge_and_multicontact(self):
        biz = self._models('contacts.business')
        names = [b['fields']['business_name'] for b in biz]
        # 'Acme (Bob Smith)' and 'acme (Carol King)' collapse to one Business
        # with the canonical FreeAgent display name.
        self.assertIn('Acme Inc.', names)
        acme = next(b for b in biz if b['fields']['business_name'] == 'Acme Inc.')
        contacts = [ct for ct in self._models('contacts.contact')
                    if ct['fields']['business'] == acme['pk']]
        firsts = {ct['fields']['first_name'] for ct in contacts}
        # FreeAgent default (Jane) + both kanban people (Bob, Carol)
        self.assertEqual(firsts, {'Jane', 'Bob', 'Carol'})

    def test_individual_has_no_business(self):
        js = next(ct for ct in self._models('contacts.contact')
                  if ct['fields']['last_name'] == 'Sandersfeld')
        self.assertIsNone(js['fields']['business'])
        key = next(k for k, e in self.c.entity_map.items()
                   if e['kind'] == 'individual')
        self.assertTrue(key.startswith('person:'))

    def test_fuzzy_folds_onto_canonical(self):
        res = build.resolve_contact(self.c, 'Wave Works')
        self.assertEqual(res['kind'], 'business')
        self.assertEqual(res['display'], 'Waveworks')

    def test_force_distinct_blocks_false_positive(self):
        # BWC must not fuzzy-merge onto HMC Architects.
        res = build.resolve_contact(self.c, 'BWC Architects')
        self.assertEqual(res['kind'], 'business')
        self.assertIsNone(res['fa_row'])
        self.assertNotEqual(res['key'],
                            P.normalize_name('HMC Architects'))



def _bill_for_base(c):
    """Mirror build_purchasing's bill matching: base -> the first Bills row
    (non-empty Contact Organisation) whose Comments digits hit a job base that
    has Materials. Lets tests assert PO provenance from the source sheet."""
    import re as _re
    job_number = {f['pk']: f['fields']['job_number']
                  for f in c.fixture_data if f['model'] == 'jobs.job'}
    bases_with_materials = {job_number[f['fields']['job']]
                            for f in c.fixture_data
                            if f['model'] == 'inventory.material'}
    out = {}
    for row in c.loader.sheets_data.get('Bills', []):
        org = (row.get('Contact Organisation') or '').strip()
        if not org:
            continue
        cands = set()
        for m in _re.findall(r'\d{4,5}', str(row.get('Comments') or '')):
            cands |= {m, m.zfill(5), m.lstrip('0')}
        hit = cands & bases_with_materials
        if hit:
            out.setdefault(sorted(hit)[0], row)
    return out


def _assert_po_contacts_come_from_bills(test, c):
    """Every PO's contact is the Contact Name on its source Bill (a Contact of
    the PO's business), never silently the business default."""
    f = c.fixture_data
    jobs = {j['pk']: j['fields'] for j in f if j['model'] == 'jobs.job'}
    contacts = {x['pk']: x['fields'] for x in f if x['model'] == 'contacts.contact'}
    bills = _bill_for_base(c)
    pos = [x for x in f if x['model'] == 'purchasing.purchaseorder']
    test.assertGreater(len(pos), 0)
    checked = 0
    for po in pos:
        fields = po['fields']
        # The PO's job is the one whose materials its lines carry.
        poli_pk = next(l['pk'] for l in f
                       if l['model'] == 'purchasing.purchaseorderlineitem'
                       and l['fields']['purchase_order'] == po['pk'])
        mat = next(m['fields'] for m in f if m['model'] == 'inventory.material'
                   and m['fields']['po_line_item'] == poli_pk)
        base = jobs[mat['job']]['job_number']
        name = (bills[base].get('Contact Name') or '').strip()
        contact = contacts[fields['contact']]
        test.assertEqual(contact['business'], fields['business'])
        if not name:
            continue
        first, last = P.split_name(name)
        test.assertEqual((contact['first_name'], contact['last_name']),
                         (first, last), f'PO {fields["po_number"]} for {base}')
        checked += 1
    test.assertGreater(checked, 0)


def _businesses_without_job_or_po(c):
    f = c.fixture_data
    contacts = {x['pk']: x['fields'] for x in f if x['model'] == 'contacts.contact'}
    used = set()
    for x in f:
        if x['model'] == 'jobs.job':
            used.add(contacts[x['fields']['contact']]['business'])
        elif x['model'] == 'purchasing.purchaseorder':
            used.add(x['fields']['business'])
    return [b for b in f if b['model'] == 'contacts.business'
            and b['pk'] not in used]


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class PurchasingBuilderTest(unittest.TestCase):
    """build_purchasing: transient lots, consumption-by-task, earmarks/QOH, and
    PO/Bill synthesis. Runs the whole pipeline once via convert()."""

    @classmethod
    def setUpClass(cls):
        cls.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/po_test.json',
                                   limit=80)
        cls.c.convert()
        cls.f = cls.c.fixture_data

    def _m(self, model):
        return [r for r in self.f if r['model'] == model]

    def test_every_material_is_item_backed(self):
        for m in self._m('inventory.material'):
            self.assertIsNotNone(m['fields']['inventory_item'])

    def test_every_material_has_entered_cost_source(self):
        # Invariant: a material with an inventory_item carries a non-null
        # cost_source (and every converter material is item-backed — see
        # test above). Imported pricing is human-vouched-for historical
        # data, so it is 'entered', never null/'po'/'estimated'.
        for m in self._m('inventory.material'):
            self.assertEqual(m['fields']['cost_source'], 'entered')

    def test_unmatched_materials_get_markup_priced_transient_lots(self):
        lots = [i for i in self._m('inventory.inventoryitem')
                if i['fields']['code'].startswith('LOT-')]
        self.assertGreater(len(lots), 0)
        for lot in lots:
            p = Decimal(lot['fields']['purchase_price'])
            s = Decimal(lot['fields']['selling_price'])
            self.assertEqual(s, (p * Decimal('1.20')).quantize(Decimal('0.01')))

    def test_no_negative_qoh(self):
        for i in self._m('inventory.inventoryitem'):
            self.assertGreaterEqual(Decimal(i['fields']['qty_on_hand']),
                                    Decimal('0'))

    def test_consumption_follows_task_then_job_state(self):
        tstat = {t['pk']: t['fields']['status'] for t in self._m('jobs.task')}
        jstat = {j['pk']: j['fields']['status'] for j in self._m('jobs.job')}
        worked = {'in_progress', 'work_complete', 'completed'}
        for m in self._m('inventory.material'):
            f = m['fields']
            tpk = f['task']
            expect = (tstat.get(tpk) == 'complete' if tpk is not None
                      else jstat.get(f['job']) in worked)
            self.assertEqual(f['consumption_state'] == 'consumed', expect)

    def test_earmarks_are_pending_materials_on_active_jobs(self):
        jstat = {j['pk']: j['fields']['status'] for j in self._m('jobs.job')}
        terminal = {'work_complete', 'completed', 'cancelled', 'rejected'}
        pending_pairs = set()
        for m in self._m('inventory.material'):
            f = m['fields']
            if f['consumption_state'] == 'pending':
                pending_pairs.add((f['inventory_item'], f['job']))
        for e in self._m('inventory.earmark'):
            ef = e['fields']
            self.assertNotIn(jstat.get(ef['job']), terminal)
            self.assertIn((ef['inventory_item'], ef['job']), pending_pairs)
            self.assertGreater(Decimal(ef['quantity']), Decimal('0'))

    def test_pos_received_in_full_and_link_materials(self):
        pos = self._m('purchasing.purchaseorder')
        self.assertGreater(len(pos), 0)
        for p in pos:
            self.assertEqual(p['fields']['status'], 'received_in_full')
        poli = {l['pk']: l['fields']
                for l in self._m('purchasing.purchaseorderlineitem')}
        linked = 0
        for m in self._m('inventory.material'):
            lp = m['fields']['po_line_item']
            if lp is not None:
                linked += 1
                self.assertIn(lp, poli)
                self.assertEqual(poli[lp]['qty_received'], m['fields']['quantity'])
        self.assertGreater(linked, 0)

    def test_no_bill_records_emitted(self):
        """Bills are retired (they live in QBO) — the converter builds POs
        from the FreeAgent Bills sheet but emits no konbini Bill rows."""
        self.assertEqual(self._m('purchasing.bill'), [])
        self.assertEqual(self._m('purchasing.billlineitem'), [])
        self.assertGreater(len(self._m('purchasing.purchaseorder')), 0)

    def test_no_vendor_without_po_by_default(self):
        # Without all_vendors, a vendor Business exists only because a Bill
        # produced a PO to it — the bulk Bills-sheet vendor import is off.
        self.assertFalse(self.c.all_vendors)
        self.assertEqual(self.c.vendor_selected_orgs, [])
        orphans = _businesses_without_job_or_po(self.c)
        self.assertEqual([b['fields']['business_name'] for b in orphans], [])

    def test_po_contact_is_the_bill_contact(self):
        _assert_po_contacts_come_from_bills(self, self.c)


    def test_markup_config_emitted(self):
        cfg = {r['pk']: r['fields']['value']
               for r in self._m('core.configuration')}
        self.assertEqual(cfg.get('default_material_markup_percent'), '20')
        # The default material AC must be emitted and point at a real
        # AccountingCategory — EstimateService._derive_is_material matches a
        # hand line's AC against this key (RM 2026-08-11), so a regen without
        # it means no freeform line can ever be a material in the running app.
        ac_pk = cfg.get('default_material_accounting_category')
        self.assertIsNotNone(ac_pk)
        self.assertNotEqual(ac_pk, 'None')
        ac_pks = {str(r['pk']) for r in self._m('core.accountingcategory')}
        self.assertIn(ac_pk, ac_pks)


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class AllVendorsConvertTest(unittest.TestCase):
    """all_vendors=True restores the capped Bills-sheet vendor import: the
    newest --limit vendor orgs land in the output even when no Bill of theirs
    yields a PO. POs still name the Bill's contact, adding it to a
    pre-imported business when that business lacks the person."""

    @classmethod
    def setUpClass(cls):
        cls.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/po_av_test.json',
                                   limit=30, all_vendors=True)
        cls.c.convert()

    def test_vendors_imported_up_to_limit(self):
        self.assertTrue(self.c.all_vendors)
        self.assertEqual(len(self.c.vendor_selected_orgs), 30)
        self.assertGreater(len(_businesses_without_job_or_po(self.c)), 0)

    def test_po_contact_is_the_bill_contact(self):
        _assert_po_contacts_come_from_bills(self, self.c)


class PurchaseOrderContactTest(unittest.TestCase):
    """Dataset-independent: a synthesized PO names the Contact Name on its
    source Bill — attached to the vendor business as another Contact when the
    business doesn't already have that person — never silently the business's
    default contact. A Bill with no Contact Name falls back to the default."""

    _BASE = '00042'

    def _converter(self, bills):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        class FakeLoader:
            sheets_data = {'Contacts': [], 'Bills': bills}
        c.loader = FakeLoader()
        build._build_fa_indexes(c)
        job_pk = c.next_pk('jobs.job')
        c.add_fixture('jobs.job', job_pk, {
            'job_number': self._BASE, 'status': 'in_progress',
            'created_date': '2026-01-01T00:00:00+00:00'})
        c.job_map = {self._BASE: job_pk}
        item_pk = c.next_pk('inventory.inventoryitem')
        c.add_fixture('inventory.inventoryitem', item_pk,
                      {'qty_on_hand': '0.00', 'qty_sold': '0.00'})
        c.add_fixture('inventory.material', c.next_pk('inventory.material'), {
            'job': job_pk, 'task': None, 'inventory_item': item_pk,
            'quantity': '2.00', 'units': 'ea', 'description': 'ply',
            'unit_cost': '10.00', 'accounting_category': None})
        return c

    def _bill(self, name, org='Acme Plywood Supply Co'):
        return {'Contact Organisation': org, 'Contact Name': name,
                'Comments': f'for job {self._BASE}', 'Date': '2026-01-05',
                'Reference': 'B1'}

    def _rows(self, c, model):
        return [f for f in c.fixture_data if f['model'] == model]

    def _po_and_contact(self, c):
        po = self._rows(c, 'purchasing.purchaseorder')
        self.assertEqual(len(po), 1)
        po = po[0]['fields']
        contact = next(f['fields'] for f in self._rows(c, 'contacts.contact')
                       if f['pk'] == po['contact'])
        return po, contact

    def _preimport_vendor(self, c, person):
        key = P.normalize_name('Acme Plywood Supply Co')
        build._emit_business(c, key, {
            'display': 'Acme Plywood Supply Co', 'fa_row': None,
            'persons': {P.normalize_name(person): person}})
        return c.entity_map[key]

    def test_preimported_vendor_gets_bill_contact_added_and_used(self):
        c = self._converter([self._bill('Bill Person')])
        ent = self._preimport_vendor(c, 'Default Person')
        build.build_purchasing(c)
        po, contact = self._po_and_contact(c)
        self.assertEqual(po['business'], ent['business'])
        self.assertNotEqual(po['contact'], ent['default_contact'])
        self.assertEqual((contact['first_name'], contact['last_name']),
                         ('Bill', 'Person'))
        self.assertEqual(contact['business'], ent['business'])
        self.assertEqual(len([f for f in self._rows(c, 'contacts.contact')
                              if f['fields']['business'] == ent['business']]), 2)

    def test_preimported_vendor_reuses_matching_contact(self):
        c = self._converter([self._bill('Bill Person')])
        ent = self._preimport_vendor(c, 'Bill Person')
        build.build_purchasing(c)
        po, contact = self._po_and_contact(c)
        self.assertEqual(po['contact'], ent['default_contact'])
        self.assertEqual(len(self._rows(c, 'contacts.contact')), 1)

    def test_vendor_created_on_the_spot_uses_bill_contact(self):
        c = self._converter([self._bill('Bill Person')])
        build.build_purchasing(c)
        po, contact = self._po_and_contact(c)
        biz = next(f for f in self._rows(c, 'contacts.business')
                   if f['pk'] == po['business'])
        self.assertEqual(biz['fields']['business_name'], 'Acme Plywood Supply Co')
        self.assertEqual((contact['first_name'], contact['last_name']),
                         ('Bill', 'Person'))
        self.assertEqual(contact['business'], po['business'])

    def test_blank_bill_contact_falls_back_to_default(self):
        c = self._converter([self._bill('')])
        ent = self._preimport_vendor(c, 'Default Person')
        build.build_purchasing(c)
        po, _contact = self._po_and_contact(c)
        self.assertEqual(po['contact'], ent['default_contact'])
        self.assertEqual(len(self._rows(c, 'contacts.contact')), 1)


class CliParserTest(unittest.TestCase):
    def _parse(self, argv):
        from nealsdata.convert_neals_data import build_parser
        return build_parser().parse_args(argv)

    def test_all_vendors_off_by_default(self):
        self.assertFalse(self._parse([]).all_vendors)

    def test_all_vendors_flag(self):
        self.assertTrue(self._parse(['--all-vendors']).all_vendors)


class InvoicedJobStatusReconcileTest(unittest.TestCase):
    """Dataset-independent: a draft/submitted job carrying any invoice is an
    app-unreachable state (BILLABLE_JOB_STATUSES guards every invoice path),
    so reconcile bumps it to 'approved' — the minimal billable status (a
    deposit invoice on an approved job is legal)."""

    def _converter(self):
        return NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')

    def _job(self, c, status):
        pk = c.next_pk('jobs.job')
        c.add_fixture('jobs.job', pk, {'job_number': f'RJ{pk}', 'status': status})
        return pk

    def _invoice(self, c, job_pk, status='paid'):
        pk = c.next_pk('invoicing.invoice')
        c.add_fixture('invoicing.invoice', pk, {'job': job_pk, 'status': status})
        return pk

    def _run_pass(self, c):
        index = {(f['model'], f.get('pk')): f for f in c.fixture_data}
        reconcile._pass_invoiced_jobs_are_started(c, index)

    def _status(self, c, job_pk):
        return next(f['fields']['status'] for f in c.fixture_data
                    if f['model'] == 'jobs.job' and f['pk'] == job_pk)

    def test_draft_job_with_invoice_bumps_to_approved(self):
        c = self._converter()
        jp = self._job(c, 'draft')
        self._invoice(c, jp)
        self._run_pass(c)
        self.assertEqual(self._status(c, jp), 'approved')

    def test_submitted_job_with_draft_invoice_bumps_to_approved(self):
        # Even a draft invoice can't exist on a pre-approval job in the app.
        c = self._converter()
        jp = self._job(c, 'submitted')
        self._invoice(c, jp, status='draft')
        self._run_pass(c)
        self.assertEqual(self._status(c, jp), 'approved')

    def test_started_job_with_invoice_untouched(self):
        c = self._converter()
        jp = self._job(c, 'in_progress')
        self._invoice(c, jp)
        self._run_pass(c)
        self.assertEqual(self._status(c, jp), 'in_progress')

    def test_draft_job_without_invoice_untouched(self):
        c = self._converter()
        jp = self._job(c, 'draft')
        self._run_pass(c)
        self.assertEqual(self._status(c, jp), 'draft')


class SpineActiveCardPolicyTest(unittest.TestCase):
    """Dataset-independent: non-archived cards in an ACTIVE stage (in
    progress / invoice) are always selected, whatever their age — live
    board work must never silently age out of the dataset. Remaining
    slots fill newest-first as before."""

    def _converter(self, cards, refs, limit):
        c = NealsDataConverter('/dev/null', '/dev/null',
                               output_path='/tmp/x.json', limit=limit)
        class FakeLoader:
            sheets_data = {'Estimates': [{'Reference': r} for r in refs]}
        c.loader = FakeLoader()
        c.csv_cards = cards
        return c

    def _card(self, ext, created, stage='estimate', archived=''):
        return {'External ID': ext, 'Created at': created,
                'Stage': stage, 'Archived at': archived}

    def test_old_active_card_survives_the_limit(self):
        cards = [
            self._card('00001', '2026-07-01'),
            self._card('00002', '2026-07-02'),
            self._card('00003', '2026-07-03'),
            self._card('00009', '2025-01-01', stage='In Progress'),
        ]
        c = self._converter(cards, ['00001', '00002', '00003', '00009'], limit=3)
        bases = {e['base_ref'] for e in c.select_spine()}
        self.assertIn('00009', bases)
        self.assertEqual(len(bases), 3)  # active + the 2 newest others
        self.assertNotIn('00001', bases)  # oldest non-active aged out

    def test_archived_active_stage_card_ages_out_normally(self):
        cards = [
            self._card('00001', '2026-07-01'),
            self._card('00002', '2026-07-02'),
            self._card('00009', '2025-01-01', stage='In Progress',
                       archived='2025-06-01'),
        ]
        c = self._converter(cards, ['00001', '00002', '00009'], limit=2)
        bases = {e['base_ref'] for e in c.select_spine()}
        self.assertNotIn('00009', bases)

    def test_old_done_card_ages_out_normally(self):
        cards = [
            self._card('00001', '2026-07-01'),
            self._card('00002', '2026-07-02'),
            self._card('00009', '2025-01-01', stage='Done or Rejected'),
        ]
        c = self._converter(cards, ['00001', '00002', '00009'], limit=2)
        bases = {e['base_ref'] for e in c.select_spine()}
        self.assertNotIn('00009', bases)

    def test_spine_stays_newest_first_overall(self):
        # Actives consume limit slots (total = max(limit, actives)): with
        # limit=2, the active card plus ONE newest fill — ordered newest
        # first overall.
        cards = [
            self._card('00001', '2026-07-01'),
            self._card('00009', '2025-01-01', stage='Invoice'),
            self._card('00002', '2026-07-02'),
        ]
        c = self._converter(cards, ['00001', '00002', '00009'], limit=2)
        spine = c.select_spine()
        self.assertEqual([e['base_ref'] for e in spine],
                         ['00002', '00009'])

    def test_limit_never_cuts_active_cards(self):
        cards = [self._card('0000%d' % i, '2025-01-0%d' % i,
                            stage='In Progress') for i in range(1, 5)]
        c = self._converter(cards, [f['External ID'] for f in cards], limit=2)
        self.assertEqual(len(c.select_spine()), 4)


class RunClockTest(unittest.TestCase):
    def test_now_defaults_to_aware_utc_and_is_injectable(self):
        from datetime import datetime, timezone as tz
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        self.assertIsNotNone(c.now.tzinfo)
        fixed = datetime(2030, 1, 15, tzinfo=tz.utc)
        self.assertEqual(NealsDataConverter('/dev/null', '/dev/null',
                                            output_path='/tmp/x.json', now=fixed).now, fixed)

    def _expiry_status(self, now):
        c = NealsDataConverter('/dev/null', '/dev/null',
                               output_path='/tmp/x.json', now=now)
        c.add_fixture('estimates.estimate', 1, {
            'status': 'open', 'created_date': '2029-12-01T00:00:00Z',
            'closed_date': None})
        c.estimates = {'EST-1': [{'est_pk': 1, 'version': 1, 'status': 'open',
                                  'created_date': '2029-12-01'}]}
        index = {(f['model'], f.get('pk')): f for f in c.fixture_data}
        reconcile._pass_estimate_expiry(c, index)
        return index[('estimates.estimate', 1)]['fields']['status']

    def test_expiry_uses_run_clock(self):
        from datetime import datetime, timezone as tz
        self.assertEqual(self._expiry_status(datetime(2030, 1, 15, tzinfo=tz.utc)),
                         'expired')
        self.assertEqual(self._expiry_status(datetime(2029, 12, 20, tzinfo=tz.utc)),
                         'open')


class EstQtyProvenanceTest(unittest.TestCase):
    def test_records_invented_est_qty(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        c.add_fixture('jobs.task', 1, {'qty_source': 'elapsed_time', 'est_qty': None,
                                       'est_worker_time': '02:00:00'})
        c.add_fixture('jobs.task', 2, {'qty_source': 'entered_qty', 'est_qty': '4.00',
                                       'est_worker_time': '02:00:00'})
        c.add_fixture('jobs.task', 3, {'qty_source': 'entered_qty', 'est_qty': None,
                                       'est_worker_time': '02:00:00'})
        build.assign_est_quantities(c)
        self.assertEqual(c.invented_est_qty, {1, 3})


class ArchiveOldJobsTest(unittest.TestCase):
    """archive_old_jobs reshapes old completed/rejected jobs into archived jobs."""

    CUTOFF = datetime(2026, 4, 21, tzinfo=timezone.utc)

    def _c(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json',
                               now=datetime(2026, 10, 21, tzinfo=timezone.utc))
        c.jobs = {}
        return c

    def _add_job(self, c, status, completed_date, checklist=''):
        pk = c.next_pk('jobs.job')
        c.add_fixture('jobs.job', pk, {
            'job_number': f'JOB{pk}', 'name': 'j', 'contact': 1, 'status': status,
            'created_date': '2025-01-01T00:00:00+00:00',
            'start_date': '2025-01-01T00:00:00+00:00', 'due_date': None,
            'completed_date': completed_date, 'project_manager': 7,
            'customer_po_number': '', 'description': '', 'accent_color': '#f97066',
        })
        c.jobs[f'BASE{pk}'] = {'job_pk': pk, 'card': {'Checklist': checklist}}
        return pk

    def _add_task(self, c, job_pk, **over):
        pk = c.next_pk('jobs.task')
        fields = {
            'job': job_pk, 'name': 't', 'description': '', 'est_qty': '2.00',
            'est_worker_time': '01:00:00', 'actual_qty': '1.00',
            'status': 'complete', 'blocked_reason': '', 'worker_queue': 3,
            'assignee': 4, 'parent_task': None, 'sort_order': 1,
            'source_scheme': 5, 'qty_source': 'elapsed_time', 'rate': '90.00',
            'unit_label': 'hr', 'accounting_category': 2,
            'active_modifiers': [{'key': 'rush', 'label': 'Rush', 'percent': '10'}],
        }
        fields.update(over)
        c.add_fixture('jobs.task', pk, fields)
        return pk

    def _add_lot(self, c):
        pk = c.next_pk('inventory.inventoryitem')
        c.add_fixture('inventory.inventoryitem', pk, {'code': 'LOT-x', 'name': 'lot'})
        return pk

    def _add_pli(self, c):
        pk = c.next_pk('inventory.inventoryitem')
        c.add_fixture('inventory.inventoryitem', pk, {'code': 'MDF.75', 'name': 'MDF'})
        return pk

    def _add_material(self, c, job_pk, inventory_item, **over):
        pk = c.next_pk('inventory.material')
        fields = {
            'job': job_pk, 'task': None, 'description': 'm', 'quantity': '3.00',
            'units': 'ea', 'unit_cost': '10.00', 'sell_price': '20.00',
            'accounting_category': 1, 'inventory_item': inventory_item,
            'cost_source': 'entered', 'consumption_state': 'pending',
            'released_qty': '1.00', 'po_line_item': 9,
        }
        fields.update(over)
        c.add_fixture('inventory.material', pk, fields)
        return pk

    def _add_deliverable(self, c, job_pk, description='Widget'):
        pk = c.next_pk('deliverables.deliverable')
        c.add_fixture('deliverables.deliverable', pk, {
            'job': job_pk, 'description': description, 'qty_ordered': '1.00',
            'units': 'ea', 'sort_order': 10})
        return pk

    def _add_source(self, c, li_pk, source_type, source_pk):
        pk = c.next_pk('estimates.estimatelineitemsource')
        c.add_fixture('estimates.estimatelineitemsource', pk, {
            'estimate_line_item': li_pk, 'source_type': source_type,
            'source_pk': source_pk})
        return pk

    def _add_invoice(self, c, job_pk, status, qbo_amount_paid):
        pk = c.next_pk('invoicing.invoice')
        c.add_fixture('invoicing.invoice', pk, {
            'job': job_pk, 'invoice_number': f'I{pk}', 'status': status,
            'created_date': '2025-02-01T00:00:00+00:00',
            'sent_date': '2025-02-02T00:00:00+00:00',
            'closed_date': '2025-03-01T00:00:00+00:00',
            'qbo_id': '55', 'qbo_payment_status': 'paid',
            'qbo_amount_paid': qbo_amount_paid})
        return pk

    def _row(self, c, model, pk):
        for f in c.fixture_data:
            if f['model'] == model and f['pk'] == pk:
                return f['fields']
        return None

    def _job(self, c, pk):
        return self._row(c, 'jobs.job', pk)

    def test_archives_completed_and_rejected_at_or_before_cutoff(self):
        c = self._c()
        old_completed = self._add_job(c, 'completed', '2026-04-21T00:00:00+00:00')
        old_rejected = self._add_job(c, 'rejected', '2025-12-01T00:00:00+00:00')
        recent = self._add_job(c, 'completed', '2026-04-22T00:00:00+00:00')
        wc = self._add_job(c, 'work_complete', None)
        ip = self._add_job(c, 'in_progress', None)
        build.archive_old_jobs(c, self.CUTOFF)
        self.assertEqual(c.archived_job_pks, {old_completed, old_rejected})
        self.assertEqual(c.archived_outcome,
                         {old_completed: 'completed', old_rejected: 'rejected'})
        self.assertEqual(self._job(c, old_completed)['status'], 'archived')
        self.assertEqual(self._job(c, old_completed)['project_manager'], None)
        self.assertEqual(self._job(c, old_completed)['completed_date'],
                         '2026-04-21T00:00:00+00:00')
        self.assertEqual(self._job(c, recent)['status'], 'completed')
        self.assertEqual(self._job(c, recent)['project_manager'], 7)
        self.assertEqual(self._job(c, wc)['status'], 'work_complete')
        self.assertEqual(self._job(c, ip)['status'], 'in_progress')

    def test_archives_on_reconciled_completed_date_whatever_its_source(self):
        c = self._c()
        no_card = self._add_job(c, 'completed', '2025-06-01T00:00:00+00:00')
        stale_card = self._add_job(c, 'work_complete', None)
        c.jobs[f'BASE{stale_card}']['card']['Archived at'] = '2024-01-01'
        build.archive_old_jobs(c, self.CUTOFF)
        self.assertEqual(c.archived_job_pks, {no_card})
        self.assertEqual(self._job(c, stale_card)['status'], 'work_complete')

    def test_task_quantities(self):
        c = self._c()
        jp = self._add_job(c, 'completed', '2025-06-01T00:00:00+00:00')
        invented = self._add_task(c, jp)
        c.invented_est_qty.add(invented)
        entered = self._add_task(c, jp, qty_source='entered_qty', est_qty='4.00')
        other = self._add_task(c, jp, status='pending')
        build.archive_old_jobs(c, self.CUTOFF)
        self.assertIsNone(self._row(c, 'jobs.task', invented)['est_qty'])
        self.assertEqual(self._row(c, 'jobs.task', entered)['est_qty'], '4.00')
        for pk, status in ((invented, 'complete'), (entered, 'complete'),
                           (other, 'pending')):
            t = self._row(c, 'jobs.task', pk)
            self.assertEqual(t['qty_source'], 'entered_qty')
            for k in ('est_worker_time', 'actual_qty', 'assignee',
                      'worker_queue', 'source_scheme', 'service_item'):
                self.assertIsNone(t[k], k)
            self.assertEqual(t['active_modifiers'], [])
            self.assertEqual(t['rate'], '90.00')
            self.assertEqual(t['unit_label'], 'hr')
            self.assertEqual(t['accounting_category'], 2)
            self.assertEqual(t['status'], status)

    def test_materials_and_lots(self):
        c = self._c()
        jp = self._add_job(c, 'completed', '2025-06-01T00:00:00+00:00')
        task = self._add_task(c, jp)
        pli = self._add_pli(c)
        lot = self._add_lot(c)
        a = self._add_material(c, jp, pli, task=task)
        b = self._add_material(c, jp, lot)
        build.archive_old_jobs(c, self.CUTOFF)
        ma = self._row(c, 'inventory.material', a)
        self.assertEqual(ma['inventory_item'], pli)
        self.assertEqual(ma['consumption_state'], 'consumed')
        self.assertEqual(ma['cost_source'], 'imported')
        self.assertEqual(ma['released_qty'], '0.00')
        self.assertIsNone(ma['po_line_item'])
        self.assertEqual((ma['unit_cost'], ma['quantity'], ma['units'], ma['task']),
                         ('10.00', '3.00', 'ea', task))
        self.assertIsNone(self._row(c, 'inventory.material', b)['inventory_item'])
        self.assertIsNone(self._row(c, 'inventory.inventoryitem', lot))
        self.assertIsNotNone(self._row(c, 'inventory.inventoryitem', pli))

    def test_shared_transient_lot_survives(self):
        c = self._c()
        old = self._add_job(c, 'completed', '2025-06-01T00:00:00+00:00')
        live = self._add_job(c, 'in_progress', None)
        lot = self._add_lot(c)
        a = self._add_material(c, old, lot)
        b = self._add_material(c, live, lot)
        build.archive_old_jobs(c, self.CUTOFF)
        self.assertIsNone(self._row(c, 'inventory.material', a)['inventory_item'])
        self.assertEqual(self._row(c, 'inventory.material', b)['inventory_item'], lot)
        self.assertIsNotNone(self._row(c, 'inventory.inventoryitem', lot))
        self.assertEqual(self._row(c, 'inventory.material', b)['consumption_state'],
                         'pending')

    def test_deliverables_sources_and_invoices(self):
        c = self._c()
        old = self._add_job(c, 'completed', '2025-06-01T00:00:00+00:00')
        live = self._add_job(c, 'in_progress', None)
        c.fake_deliverable_count = 2
        d1 = self._add_deliverable(c, old, 'Fake Deliverable')
        d2 = self._add_deliverable(c, old, 'Real')
        d3 = self._add_deliverable(c, live, 'Fake Deliverable')
        t_old = self._add_task(c, old)
        m_old = self._add_material(c, old, None)
        t_live = self._add_task(c, live)
        s1 = self._add_source(c, 1, 'task', t_old)
        s2 = self._add_source(c, 2, 'material', m_old)
        s3 = self._add_source(c, 3, 'task', t_live)
        # a material source whose pk is not one of the archived job's materials
        s4 = self._add_source(c, 4, 'material', m_old + 1000)
        i_old = self._add_invoice(c, old, 'paid', '100.00')
        i_live = self._add_invoice(c, live, 'open', '5.00')
        build.archive_old_jobs(c, self.CUTOFF)
        self.assertIsNone(self._row(c, 'deliverables.deliverable', d1))
        self.assertIsNone(self._row(c, 'deliverables.deliverable', d2))
        self.assertIsNotNone(self._row(c, 'deliverables.deliverable', d3))
        self.assertEqual(c.fake_deliverable_count, 1)
        M = 'estimates.estimatelineitemsource'
        self.assertIsNone(self._row(c, M, s1))
        self.assertIsNone(self._row(c, M, s2))
        self.assertIsNotNone(self._row(c, M, s3))
        self.assertIsNotNone(self._row(c, M, s4))
        inv = self._row(c, 'invoicing.invoice', i_old)
        self.assertIsNone(inv['qbo_amount_paid'])
        self.assertIsNone(inv['qbo_id'])
        self.assertEqual(inv['qbo_payment_status'], '')
        self.assertEqual(inv['status'], 'paid')
        self.assertEqual(inv['closed_date'], '2025-03-01T00:00:00+00:00')
        live_inv = self._row(c, 'invoicing.invoice', i_live)
        self.assertEqual((live_inv['qbo_amount_paid'], live_inv['qbo_id']),
                         ('5.00', '55'))

    def test_cutoff_helper(self):
        self.assertEqual(
            build.archive_cutoff(datetime(2026, 10, 21, 12, tzinfo=timezone.utc)),
            datetime(2026, 4, 21, 12, tzinfo=timezone.utc))


class ArchivedJobsDownstreamSkipTest(unittest.TestCase):
    """Every builder that runs after archive_old_jobs leaves archived jobs
    alone (spec §6) while a twin live job in the same converter is handled
    as before. Dataset-free synthetic state."""

    def _c(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        c.jobs = {}
        c.job_map = {}
        c.rotation_user_pks = [1, 2, 3]
        c.user_by_username = {'u1': 1, 'u2': 2, 'u3': 3}
        c._pk_counters['core.user'] = 3
        return c

    def _job(self, c, status, archived=False, checklist='', completed=None):
        pk = c.next_pk('jobs.job')
        c.add_fixture('jobs.job', pk, {
            'job_number': f'JOB{pk}', 'name': 'j', 'contact': 1,
            'status': 'archived' if archived else status,
            'created_date': '2026-01-01T00:00:00+00:00',
            'start_date': '2026-01-01T00:00:00+00:00', 'due_date': None,
            'completed_date': completed, 'project_manager': None,
            'customer_po_number': '', 'description': '', 'accent_color': '#f97066',
        })
        c.jobs[f'BASE{pk}'] = {'job_pk': pk, 'card': {'Checklist': checklist},
                               'estimate_rows': [], 'primary_ref': f'BASE{pk}'}
        c.job_map[f'BASE{pk}'] = pk
        if archived:
            c.archived_job_pks.add(pk)
        return pk

    def _task(self, c, job, status='complete', **over):
        pk = c.next_pk('jobs.task')
        fields = {
            'job': job, 'name': f't{pk}', 'status': status,
            'qty_source': 'entered_qty', 'est_qty': '2.00',
            'est_worker_time': '01:00:00', 'actual_qty': None,
            'assignee': None, 'worker_queue': None, 'sort_order': 1,
        }
        fields.update(over)
        c.add_fixture('jobs.task', pk, fields)
        return pk

    def _m(self, c, model):
        return [f for f in c.fixture_data if f['model'] == model]

    def _fields(self, c, model, pk):
        return next(f['fields'] for f in c.fixture_data
                    if f['model'] == model and f['pk'] == pk)

    def test_project_manager_skips_archived(self):
        import random as _random
        _random.seed(1)
        c = self._c()
        arch = self._job(c, 'completed', archived=True)
        live = self._job(c, 'in_progress')
        build.assign_project_managers(c)
        self.assertIsNone(self._fields(c, 'jobs.job', arch)['project_manager'])
        self.assertIn(self._fields(c, 'jobs.job', live)['project_manager'], (1, 2, 3))

    def test_shipments_skip_archived(self):
        c = self._c()
        arch = self._job(c, 'completed', archived=True,
                         checklist='[X] Picked up/Delivered')
        live = self._job(c, 'completed', checklist='[X] Picked up/Delivered',
                         completed='2026-05-01T00:00:00+00:00')
        for jp in (arch, live):
            dp = c.next_pk('deliverables.deliverable')
            c.add_fixture('deliverables.deliverable', dp, {
                'job': jp, 'description': 'Widget', 'qty_ordered': '1.00'})
        build.build_shipments(c)
        ships = self._m(c, 'deliverables.shipment')
        self.assertEqual([s['fields']['job'] for s in ships], [live])

    def test_bleps_skip_archived(self):
        c = self._c()
        arch = self._job(c, 'completed', archived=True,
                         completed='2026-02-05T00:00:00+00:00')
        live = self._job(c, 'in_progress')
        at = self._task(c, arch)
        lt = self._task(c, live)
        build.build_bleps_and_shifts(c)
        self.assertEqual([b['fields']['task'] for b in self._m(c, 'jobs.blep')],
                         [lt])
        self.assertIsNone(self._fields(c, 'jobs.task', at)['actual_qty'])
        self.assertIsNone(self._fields(c, 'jobs.task', at)['assignee'])
        self.assertIsNotNone(self._fields(c, 'jobs.task', lt)['actual_qty'])

    def test_current_work_skips_archived(self):
        import random as _random
        _random.seed(1)
        c = self._c()
        arch = self._job(c, 'in_progress', archived=True)
        # Restore the live status so only the archived guard can exclude it.
        self._fields(c, 'jobs.job', arch)['status'] = 'in_progress'
        live = self._job(c, 'in_progress')
        at = self._task(c, arch, 'pending')
        lt = self._task(c, live, 'pending')
        build.assign_current_work(c)
        self.assertIsNone(self._fields(c, 'jobs.task', at)['assignee'])
        self.assertIn(self._fields(c, 'jobs.task', lt)['assignee'], (1, 2, 3))

    def test_purchasing_skips_archived(self):
        c = self._c()
        arch = self._job(c, 'in_progress', archived=True)
        live = self._job(c, 'in_progress')
        ip = c.next_pk('inventory.inventoryitem')
        c.add_fixture('inventory.inventoryitem', ip, {
            'code': 'X', 'qty_on_hand': '0.00', 'qty_sold': '0.00'})
        for jp in (arch, live):
            # Task-linked to a complete task: the live one counts as sold; the
            # archived one would too, were it not skipped.
            tp = self._task(c, jp)
            mp = c.next_pk('inventory.material')
            c.add_fixture('inventory.material', mp, {
                'job': jp, 'task': tp, 'inventory_item': ip,
                'quantity': '3.00', 'consumption_state': 'consumed',
                'po_line_item': None})
        build.build_purchasing(c)
        # Only the live twin's material moves qty_sold.
        self.assertEqual(self._fields(c, 'inventory.inventoryitem', ip)['qty_sold'],
                         '3.00')
        self.assertEqual(self._fields(c, 'inventory.inventoryitem', ip)['qty_on_hand'],
                         '0.00')
        self.assertEqual(self._m(c, 'inventory.earmark'), [])

    def test_purchasing_skips_archived_pending_material(self):
        # A pending archived material on an earmark-eligible job must not
        # earmark or raise QOH; the live twin earmarks.
        c = self._c()
        arch = self._job(c, 'approved', archived=True)
        # Restore the live status so only the archived guard can exclude it.
        self._fields(c, 'jobs.job', arch)['status'] = 'approved'
        live = self._job(c, 'approved')
        ip = c.next_pk('inventory.inventoryitem')
        c.add_fixture('inventory.inventoryitem', ip, {
            'code': 'X', 'qty_on_hand': '0.00', 'qty_sold': '0.00'})
        for jp in (arch, live):
            mp = c.next_pk('inventory.material')
            c.add_fixture('inventory.material', mp, {
                'job': jp, 'task': None, 'inventory_item': ip,
                'quantity': '3.00', 'consumption_state': 'pending',
                'po_line_item': None})
        build.build_purchasing(c)
        self.assertEqual([e['fields']['job'] for e in self._m(c, 'inventory.earmark')],
                         [live])
        self.assertEqual(self._fields(c, 'inventory.inventoryitem', ip)['qty_on_hand'],
                         '3.00')

    def _invoice_with_line(self, c, job, kind='task', desc='cut'):
        ip = c.next_pk('invoicing.invoice')
        c.add_fixture('invoicing.invoice', ip, {'job': job, 'status': 'paid'})
        lp = c.next_pk('invoicing.invoicelineitem')
        c.add_fixture('invoicing.invoicelineitem', lp, {
            'invoice': ip, 'line_number': 1, 'description': desc})
        c.invoice_line_kinds[lp] = kind
        return ip, lp

    def test_invoice_sources_skip_archived(self):
        c = self._c()
        arch = self._job(c, 'completed', archived=True)
        live = self._job(c, 'completed')
        self._task(c, arch)
        lt = self._task(c, live)
        self._invoice_with_line(c, arch)
        _, live_line = self._invoice_with_line(c, live)
        build.build_invoice_line_item_sources(c)
        srcs = self._m(c, 'invoicing.invoicelineitemsource')
        self.assertEqual(len(srcs), 1)
        self.assertEqual(srcs[0]['fields']['invoice_line_item'], live_line)
        self.assertEqual(srcs[0]['fields']['source_pk'], lt)

    def _agreement_state(self, c, job):
        base = f'BASE{job}'
        ep = c.next_pk('estimates.estimate')
        c.add_fixture('estimates.estimate', ep, {
            'job': job, 'status': 'accepted', 'version': 1})
        c.estimates[base] = [{'est_pk': ep, 'version': 1}]
        lp = c.next_pk('estimates.estimatelineitem')
        c.add_fixture('estimates.estimatelineitem', lp, {
            'estimate': ep, 'line_number': 1, 'description': 'cut'})
        c.line_items[ep] = [{'line_item_pk': lp, 'description': 'cut'}]
        return lp

    def test_agreement_refs_skip_archived(self):
        c = self._c()
        arch = self._job(c, 'completed', archived=True)
        live = self._job(c, 'completed')
        self._agreement_state(c, arch)
        live_est_line = self._agreement_state(c, live)
        _, arch_line = self._invoice_with_line(c, arch)
        _, live_line = self._invoice_with_line(c, live)
        build.build_invoice_agreement_refs(c)
        self.assertIsNone(
            self._fields(c, 'invoicing.invoicelineitem', arch_line)
            .get('agreement_estimate_line'))
        self.assertEqual(
            self._fields(c, 'invoicing.invoicelineitem', live_line)
            .get('agreement_estimate_line'), live_est_line)

    def _est_with_line(self, c, job, status='accepted'):
        ep = c.next_pk('estimates.estimate')
        c.add_fixture('estimates.estimate', ep, {
            'job': job, 'status': status, 'version': 1})
        lp = c.next_pk('estimates.estimatelineitem')
        c.add_fixture('estimates.estimatelineitem', lp, {
            'estimate': ep, 'line_number': 1, 'description': 'cut',
            'adjustment_service': None, 'accounting_category': None,
            'service_item': None, 'inventory_item': None, 'is_material': False})
        return lp

    def test_synthetic_sources_skip_archived(self):
        c = self._c()
        arch = self._job(c, 'archived', archived=True)
        live = self._job(c, 'in_progress')
        self._est_with_line(c, arch)
        live_line = self._est_with_line(c, live)
        self._task(c, arch)
        lt = self._task(c, live)
        build.build_synthetic_estimate_sources(c)
        rows = self._m(c, 'estimates.estimatelineitemsource')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['fields']['estimate_line_item'], live_line)
        self.assertEqual(rows[0]['fields']['source_pk'], lt)

    def test_checklist_declines_skip_archived(self):
        c = self._c()
        # An archived job whose (unreset) status would otherwise qualify.
        arch = self._job(c, 'completed', archived=True)
        live = self._job(c, 'completed')
        arch_line = self._est_with_line(c, arch)
        live_line = self._est_with_line(c, live)
        # Status literal is 'archived' on the job row; declines must still
        # skip it explicitly, so also check against a qualifying status.
        self._fields(c, 'jobs.job', arch)['status'] = 'completed'
        build.build_checklist_declines(c)
        self.assertFalse(
            self._fields(c, 'estimates.estimatelineitem', arch_line)
            .get('work_declined', False))
        self.assertTrue(
            self._fields(c, 'estimates.estimatelineitem', live_line)
            .get('work_declined'))

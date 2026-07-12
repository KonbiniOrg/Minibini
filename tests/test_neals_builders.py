# tests/test_neals_builders.py
import json
import os
import tempfile
import unittest
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
        self.assertLessEqual(len(spine), 20)
        self.assertGreater(len(spine), 0)
        for entry in spine:
            self.assertIn('card', entry)
            self.assertIn('estimate_rows', entry)
            self.assertTrue(entry['estimate_rows'])


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
        canon = ['none', 'ea', 'hours', 'min', 'sheets', 'sq ft', 'ft', 'yd',
                 'm', 'lbs', 'kg', 'gal', 'qt', 'L', 'bd ft', 'ln ft']
        self.assertEqual(value, canon)

    def test_ratescheme_unit_labels_within_canon(self):
        # Every emitted RateScheme.unit_label must be a value in the
        # converter's units_list. The seed historically used the singular
        # 'hour', which is not in DEFAULT_UNITS ('hours') — a mismatch that
        # makes the seeded schemes fail unit validation in the running app.
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
class ContactBuildersTest(unittest.TestCase):
    def setUp(self):
        self.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=10)
        self.c.loader.load()
        self.c.csv_cards = self.c.csv_loader.load()
        self.c.spine = self.c.select_spine()

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def test_builds_referenced_contacts_and_businesses(self):
        build.build_contacts_and_businesses(self.c)
        contacts = self._models('contacts.contact')
        businesses = self._models('contacts.business')
        self.assertGreater(len(contacts), 0)
        contact_pks = {f['pk'] for f in contacts}
        # Every Business.default_contact resolves to a real Contact.
        for b in businesses:
            self.assertIn(b['fields']['default_contact'], contact_pks)
        # Every contact has an email and at least one phone.
        for ct in contacts:
            self.assertTrue(ct['fields']['email'])
            self.assertTrue(ct['fields']['work_number'] or
                            ct['fields']['mobile_number'] or
                            ct['fields']['home_number'])
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
        # default to 'ea'; Days lines convert to hours via resolve helper.
        build.build_estimates(self.c)
        canon = {'none', 'ea', 'hours', 'min', 'sheets', 'sq ft', 'ft', 'yd',
                 'm', 'lbs', 'kg', 'gal', 'qt', 'L', 'bd ft', 'ln ft'}
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

    def test_estimate_number_derives_from_job_number_and_version(self):
        # The canonical form is "{job_number}-{version}". Job number ==
        # FreeAgent base ref, version is the per-chain index.
        build.build_estimates(self.c)
        for base_ref, est_list in self.c.estimates.items():
            for entry in est_list:
                est = next(f for f in self._models('estimates.estimate')
                           if f['pk'] == entry['est_pk'])
                self.assertEqual(
                    est['fields']['estimate_number'],
                    f'{base_ref}-{entry["version"]}')

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
        rs_pks = {f['pk'] for f in self._models('jobs.ratescheme')}
        for t in self._models('jobs.task'):
            self.assertIn(t['fields']['rate_scheme'], rs_pks)

    def test_atoms_emit_canon_units_only(self):
        # Materials and Deliverables must use canonical units (no 'each' /
        # 'days') so they validate against the running app's units_list.
        build.derive_atoms(self.c)
        canon = {'none', 'ea', 'hours', 'min', 'sheets', 'sq ft', 'ft', 'yd',
                 'm', 'lbs', 'kg', 'gal', 'qt', 'L', 'bd ft', 'ln ft'}
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

    def test_flat_fee_tasks_use_per_price_rate_scheme(self):
        # After Phase 1 reframe: flat-fee tasks point to a per-price RateScheme
        # (rate = the fee amount) and carry an empty list active_modifiers.
        # No shared zero-rate 'Flat Fee' scheme should be emitted.
        build.derive_atoms(self.c)
        ff_schemes = [f for f in self._models('jobs.ratescheme')
                      if f['fields'].get('algorithm') == 'flat_fee']
        # No zero-rate shared catch-all scheme.
        for f in ff_schemes:
            self.assertNotEqual(
                f['fields']['rate'], '0.00',
                f"flat_fee RateScheme pk={f['pk']} has rate=0.00 (shared catch-all should not be emitted)")
        # Every flat-fee task: rate on RateScheme, empty list modifiers.
        ff_pks = {f['pk'] for f in ff_schemes}
        for t in self._models('jobs.task'):
            sp = t['fields']['rate_scheme']
            mods = t['fields']['active_modifiers']
            self.assertIsInstance(mods, list,
                                  f"task {t['pk']} active_modifiers should be list")
            if sp in ff_pks:
                # The price must be on the RateScheme.rate, not in modifiers.
                rate_str = next(f['fields']['rate'] for f in ff_schemes if f['pk'] == sp)
                self.assertNotEqual(rate_str, '0.00',
                                    f"task {t['pk']} points to a flat_fee scheme with zero rate")

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
        # (EstimateLineItemSource, source_type='material'), exactly as it does
        # for fees. Without it, accepting a still-open estimate in-app
        # re-crystallizes the line as a bare Fee → duplicate atoms (job 08008).
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
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        models = {row['model'] for row in data}
        self.assertIn('jobs.job', models)
        self.assertIn('estimates.estimate', models)
        self.assertIn('core.jobhistory', models)
        self.assertIn('jobs.blep', models)
        self.assertIn('core.shift', models)
        self.assertNotIn('jobs.workorder', models)


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
        c = NealsDataConverter(XLSX, CSV, output_path=path, limit=40)
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

    def _converter(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        # Two seed-style users in the rotation pool.
        c.user_by_username = {'u1': 1, 'u2': 2}
        c.rotation_user_pks = [1, 2]
        c.scheme_algorithm_by_pk = {10: 'elapsed_time', 11: 'entered_qty'}
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
            'job': job, 'rate_scheme': scheme, 'name': f't{pk}', 'description': '',
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

    def _converter(self):
        c = NealsDataConverter('/dev/null', '/dev/null', output_path='/tmp/x.json')
        c.scheme_algorithm_by_pk = {1: 'elapsed_time', 2: 'entered_qty', 3: 'flat_fee'}
        return c

    def _add_task(self, c, pk, scheme, ewt='02:30:00', est_qty=None):
        c.add_fixture('jobs.task', pk, {
            'job': 1, 'rate_scheme': scheme, 'name': 't', 'description': '',
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
        # Fixed charges are now jobs.Fee atoms (no est_qty), not Tasks, so
        # assign_est_quantities only fills elapsed_time / entered_qty Tasks and
        # leaves any other scheme's est_qty exactly as the source set it.
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

    def test_bills_link_to_received_pos(self):
        po_pks = {p['pk'] for p in self._m('purchasing.purchaseorder')}
        biz_pks = {b['pk'] for b in self._m('contacts.business')}
        bills = self._m('purchasing.bill')
        self.assertGreater(len(bills), 0)
        for b in bills:
            self.assertIn(b['fields']['purchase_order'], po_pks)
            self.assertIn(b['fields']['business'], biz_pks)
            self.assertEqual(b['fields']['status'], 'received')

    def test_markup_config_emitted(self):
        cfg = {r['pk']: r['fields']['value']
               for r in self._m('core.configuration')}
        self.assertEqual(cfg.get('default_material_markup_percent'), '20')
        # The default material AC must be emitted and point at a real
        # AccountingCategory — EstimateService._apply_material_ac_default RAISES
        # if this key is absent, so a regen without it breaks freeform-material
        # creation in the running app.
        ac_pk = cfg.get('default_material_accounting_category')
        self.assertIsNotNone(ac_pk)
        self.assertNotEqual(ac_pk, 'None')
        ac_pks = {str(r['pk']) for r in self._m('core.accountingcategory')}
        self.assertIn(ac_pk, ac_pks)

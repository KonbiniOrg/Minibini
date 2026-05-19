# tests/test_neals_builders.py
import json
import os
import tempfile
import unittest
from decimal import Decimal
from nealsdata.converter import build
from nealsdata.converter import reconcile
from nealsdata.converter.orchestrator import NealsDataConverter

XLSX = 'nealsdata/datasets/company-export-220382-2026-05-18-02-19.xlsx'
CSV = 'nealsdata/datasets/neals kanban.csv'


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

    def test_build_configuration_has_numbering_keys(self):
        build.build_configuration(self.c)
        keys = {f['pk'] for f in self._models('core.configuration')}
        for k in ('job_counter', 'estimate_counter', 'invoice_counter',
                  'po_counter'):
            self.assertIn(k, keys)

    def test_build_price_list_items(self):
        build.build_seed(self.c)
        build.build_price_list_items(self.c)
        self.assertGreater(len(self._models('inventory.pricelistitem')), 100)


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
        for b in businesses:
            self.assertIn(b['fields']['default_contact'], contact_pks)
        for ct in contacts:
            self.assertTrue(ct['fields']['email'])
            self.assertTrue(ct['fields']['work_number'] or
                            ct['fields']['mobile_number'] or
                            ct['fields']['home_number'])


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


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class EstimateBuilderTest(unittest.TestCase):
    def setUp(self):
        self.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=10)
        self.c.loader.load()
        self.c.csv_cards = self.c.csv_loader.load()
        self.c.spine = self.c.select_spine()
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
        job_pks = {f['pk'] for f in self._models('jobs.job')}
        deliv_jobs = {d['fields']['job'] for d in self._models('deliverables.deliverable')}
        self.assertEqual(job_pks, deliv_jobs)
        # Tasks on the shared Flat Fee scheme carry a per-task price in
        # active_modifiers ({'flat_fee_price': ...}); no per-rate clones exist.
        ff_pks = {f['pk'] for f in self._models('jobs.ratescheme')
                  if f['fields']['name'] == 'Flat Fee'}
        for t in self._models('jobs.task'):
            if t['fields']['rate_scheme'] in ff_pks:
                mods = t['fields']['active_modifiers']
                self.assertIsInstance(mods, dict)
                self.assertIn('flat_fee_price', mods)

    def test_materials_link_to_cut_task_when_present(self):
        build.derive_atoms(self.c)
        tasks = self._models('jobs.task')
        cut_task_pks = {t['pk'] for t in tasks if 'cut' in t['fields']['name'].lower()}
        for m in self._models('inventory.material'):
            if m['fields']['task'] is not None:
                self.assertIn(m['fields']['task'], cut_task_pks)


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class InvoiceBuilderTest(unittest.TestCase):
    def setUp(self):
        self.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=15)
        self.c.loader.load()
        self.c.csv_cards = self.c.csv_loader.load()
        self.c.spine = self.c.select_spine()
        build.build_contacts_and_businesses(self.c)
        build.build_jobs(self.c)
        build.build_estimates(self.c)

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

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
                         'oomung@example.com')
        self.assertEqual(build._anonymize_email('noreply+5@example.com'),
                         'noreply+5@example.com')

    def test_phone_prefix_replaced(self):
        self.assertEqual(build._anonymize_phone('408-323-3393'), '408-555-3393')
        self.assertEqual(build._anonymize_phone('805 433 4154'), '805-555-4154')
        self.assertEqual(build._anonymize_phone('(650) 593-6997'), '650-555-6997')
        self.assertEqual(build._anonymize_phone(''), '555-555-5555')

    def test_scrub_text(self):
        self.assertEqual(
            build._scrub_text('email john@neals.com or call 415-867-5309'),
            'email john@example.com or call 415-555-5309')
        # part-number-like sequences without the phone shape are untouched
        self.assertEqual(build._scrub_text('cut part A-109180-00 x10'),
                         'cut part A-109180-00 x10')


class ConvertEndToEndTest(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                         'datasets not present')
    def test_convert_writes_a_fixture_file(self):
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        self.addCleanup(os.unlink, path)
        c = NealsDataConverter(XLSX, CSV, output_path=path, limit=10)
        c.convert()
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        models = {row['model'] for row in data}
        self.assertIn('jobs.job', models)
        self.assertIn('estimates.estimate', models)
        self.assertNotIn('jobs.workorder', models)
        self.assertNotIn('jobs.blep', models)

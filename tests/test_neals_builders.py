# tests/test_neals_builders.py
import json
import os
import tempfile
import unittest
from decimal import Decimal
from nealsdata.converter import build
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

    def test_build_configuration_has_numbering_keys(self):
        build.build_configuration(self.c)
        keys = {f['pk'] for f in self._models('core.configuration')}
        for k in ('job_counter', 'estimate_counter', 'invoice_counter',
                  'po_counter'):
            self.assertIn(k, keys)

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
        # Tasks on the shared Flat Fee scheme carry a per-task price in
        # active_modifiers ({'flat_fee_price': ...}); no per-rate clones exist.
        ff_pks = {f['pk'] for f in self._models('jobs.ratescheme')
                  if f['fields']['name'] == 'Flat Fee'}
        for t in self._models('jobs.task'):
            if t['fields']['rate_scheme'] in ff_pks:
                mods = t['fields']['active_modifiers']
                self.assertIsInstance(mods, dict)
                self.assertIn('flat_fee_price', mods)

    def test_every_task_has_an_est_worker_time(self):
        # Cut/assembly tasks get the Kanban card's time columns; every other
        # task gets the invented flat 1-hour default.
        build.derive_atoms(self.c)
        tasks = self._models('jobs.task')
        self.assertGreater(len(tasks), 0)
        for t in tasks:
            self.assertIsNotNone(t['fields']['est_worker_time'],
                                 f"task {t['pk']} has no est_worker_time")

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


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class PlanSideAtomsTest(unittest.TestCase):
    """Jobs whose status at build time is draft or submitted don't yet have
    an accepted estimate, so their atoms must live on the plan side
    (EstWorksheet + PlanTask + PlanMaterial) rather than the real side
    (Task + Material). Deliverables stay on the Job either way."""

    def setUp(self):
        # limit=100 to guarantee both draft and submitted jobs in the slice.
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

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def _jobs_by_status(self):
        out = {}
        for j in self._models('jobs.job'):
            out.setdefault(j['fields']['status'], []).append(j['pk'])
        return out

    def test_draft_and_submitted_jobs_have_no_real_tasks_or_materials(self):
        plan_jobs = set()
        by_status = self._jobs_by_status()
        for s in ('draft', 'submitted'):
            plan_jobs.update(by_status.get(s, []))
        self.assertGreater(len(plan_jobs), 0,
                           'dataset should contain draft/submitted jobs')
        for t in self._models('jobs.task'):
            self.assertNotIn(t['fields']['job'], plan_jobs,
                             f'task {t["pk"]} on plan-side job {t["fields"]["job"]}')
        for m in self._models('inventory.material'):
            self.assertNotIn(m['fields']['job'], plan_jobs,
                             f'material {m["pk"]} on plan-side job {m["fields"]["job"]}')

    def test_draft_and_submitted_jobs_have_exactly_one_est_worksheet(self):
        by_status = self._jobs_by_status()
        plan_jobs = set(by_status.get('draft', []) + by_status.get('submitted', []))
        ws_by_job = {}
        for ws in self._models('estimates.estworksheet'):
            ws_by_job.setdefault(ws['fields']['job'], []).append(ws['pk'])
        for jp in plan_jobs:
            self.assertEqual(len(ws_by_job.get(jp, [])), 1,
                             f'plan-side job {jp} has {len(ws_by_job.get(jp, []))} worksheets')

    def test_started_and_terminal_jobs_have_no_est_worksheet(self):
        # Real-side jobs (approved+, completed, rejected, cancelled) don't get
        # an EstWorksheet — their atoms are real-side.
        by_status = self._jobs_by_status()
        real_jobs = set()
        for s in ('approved', 'in_progress', 'work_complete', 'completed',
                  'rejected', 'cancelled'):
            real_jobs.update(by_status.get(s, []))
        ws_jobs = {ws['fields']['job'] for ws in self._models('estimates.estworksheet')}
        self.assertEqual(real_jobs & ws_jobs, set(),
                         'real-side jobs should not have EstWorksheets')

    def test_every_plantask_has_required_fields(self):
        # PlanTask.clean() raises if est_qty is null; rate_scheme is NOT NULL
        # at the DB level. Every emitted PlanTask must satisfy both.
        plantasks = self._models('jobs.plantask')
        self.assertGreater(len(plantasks), 0)
        rs_pks = {f['pk'] for f in self._models('jobs.ratescheme')}
        ws_pks = {f['pk'] for f in self._models('estimates.estworksheet')}
        for pt in plantasks:
            self.assertIsNotNone(pt['fields'].get('est_qty'),
                                 f'plantask {pt["pk"]} has null est_qty')
            self.assertIn(pt['fields']['rate_scheme'], rs_pks)
            self.assertIn(pt['fields']['est_worksheet'], ws_pks)
            # PlanTask has no parent_task / status / actual_qty fields.
            for f in ('parent_task', 'status', 'actual_qty', 'blocked_reason',
                      'worker_queue', 'assignee', 'source_template',
                      'source_plan_task'):
                self.assertNotIn(f, pt['fields'],
                                 f'plantask {pt["pk"]} has unexpected field {f!r}')

    def test_planmaterials_link_to_worksheet(self):
        planmats = self._models('inventory.planmaterial')
        ws_pks = {f['pk'] for f in self._models('estimates.estworksheet')}
        for pm in planmats:
            self.assertIn(pm['fields']['est_worksheet'], ws_pks)
            # PlanMaterial swaps job/task for est_worksheet/plan_task.
            self.assertNotIn('job', pm['fields'])
            self.assertNotIn('task', pm['fields'])

    def test_deliverables_exist_for_all_jobs_regardless_of_plan_status(self):
        by_status = self._jobs_by_status()
        all_job_pks = set()
        for v in by_status.values():
            all_job_pks.update(v)
        deliv_jobs = {d['fields']['job']
                      for d in self._models('deliverables.deliverable')}
        self.assertEqual(deliv_jobs, all_job_pks,
                         'every Job (plan or real) should have a Deliverable')


@unittest.skipUnless(os.path.exists(XLSX) and os.path.exists(CSV),
                     'datasets not present')
class EstimateLineItemSourceWiringTest(unittest.TestCase):
    """Plan atoms derived from estimate line items get an
    EstimateLineItemSource row linking back. Checklist-derived plan tasks
    don't (no source LI)."""

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

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def test_source_rows_have_valid_types_and_unique_atoms(self):
        srcs = self._models('estimates.estimatelineitemsource')
        self.assertGreater(len(srcs), 0, 'expected some plan source links')
        plan_task_pks = {f['pk'] for f in self._models('jobs.plantask')}
        plan_mat_pks = {f['pk'] for f in self._models('inventory.planmaterial')}
        li_pks = {f['pk'] for f in self._models('estimates.estimatelineitem')}
        seen = set()
        for s in srcs:
            t = s['fields']['source_type']
            pk = s['fields']['source_pk']
            self.assertIn(t, ('plan_task', 'plan_material'))
            self.assertIn(s['fields']['estimate_line_item'], li_pks)
            if t == 'plan_task':
                self.assertIn(pk, plan_task_pks)
            else:
                self.assertIn(pk, plan_mat_pks)
            key = (t, pk)
            self.assertNotIn(key, seen,
                             f'duplicate claim on {key}: violates unique_together')
            seen.add(key)


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

    def _add_task(self, c, job_pk, name='cut sheet'):
        pk = c.next_pk('jobs.task')
        c.add_fixture('jobs.task', pk, {'job': job_pk, 'name': name})
        return pk

    def _add_material(self, c, job_pk, desc='plywood sheet'):
        pk = c.next_pk('inventory.material')
        c.add_fixture('inventory.material', pk, {'job': job_pk, 'description': desc})
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
        self.assertIn('core.historyentry', models)
        self.assertNotIn('jobs.workorder', models)
        self.assertNotIn('jobs.blep', models)


class BuildHistoryUnitTest(unittest.TestCase):
    """Dataset-independent: drives build_history off a hand-built fixture list."""

    def _converter(self):
        # Loader __init__ is lazy (stores the path), so dummy paths are fine —
        # we never call load(); we only use fixture_data / next_pk / add_fixture.
        return NealsDataConverter('x.xlsx', 'x.csv', output_path='/tmp/x.json')

    def _history(self, c):
        return [f for f in c.fixture_data if f['model'] == 'core.historyentry']

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
        c.add_fixture('estimates.estworksheet', 10, {'job': 1})
        c.add_fixture('jobs.plantask', 11, {})
        c.add_fixture('inventory.pricelistitem', 12, {})

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

    def test_timestamp_anchors_to_creation_dates(self):
        c = self._converter()
        c.add_fixture('jobs.job', 1, {'created_date': '2025-03-01T00:00:00+00:00'})
        c.add_fixture('jobs.task', 2, {'job': 1})                  # -> job's date
        c.add_fixture('inventory.material', 3, {'job': 1})         # -> job's date
        c.add_fixture('deliverables.deliverable', 4, {'job': 1, 'created_at': '2025-03-09T00:00:00+00:00'})
        c.add_fixture('contacts.contact', 5, {})                   # -> fallback constant

        build.build_history(c)

        ts = {(r['fields']['object_type'], r['fields']['object_id']): r['fields']['timestamp']
              for r in self._history(c)}
        self.assertEqual(ts[('job', 1)], '2025-03-01T00:00:00+00:00')
        self.assertEqual(ts[('task', 2)], '2025-03-01T00:00:00+00:00')
        self.assertEqual(ts[('material', 3)], '2025-03-01T00:00:00+00:00')
        self.assertEqual(ts[('deliverable', 4)], '2025-03-09T00:00:00+00:00')
        self.assertEqual(ts[('contact', 5)], '2024-01-01T00:00:00+00:00')

    def _for(self, c, otype, oid):
        return [r['fields'] for r in self._history(c)
                if r['fields']['object_type'] == otype and r['fields']['object_id'] == oid]

    def test_status_transitions_synthesised_from_final_status(self):
        c = self._converter()
        c.add_fixture('jobs.job', 1, {'created_date': '2025-03-01T00:00:00+00:00', 'status': 'completed'})
        c.add_fixture('jobs.task', 2, {'job': 1, 'status': 'complete'})
        c.add_fixture('inventory.material', 3, {'job': 1, 'consumption_state': 'consumed'})
        c.add_fixture('deliverables.shipment', 4, {'job': 1, 'created_at': '2025-03-02T00:00:00+00:00', 'status': 'picked_up'})
        c.add_fixture('estimates.estimate', 5, {'job': 1, 'created_date': '2025-03-01T00:00:00+00:00', 'status': 'accepted'})

        build.build_history(c)

        # Job: created + the full draft->...->completed path as action entries
        job = self._for(c, 'job', 1)
        self.assertEqual(len([e for e in job if e['changes'].get('_created')]), 1)
        actions = [e for e in job if e['entry_type'] == 'action']
        self.assertEqual([e['changes']['status']['new'] for e in actions],
                         ['submitted', 'approved', 'in_progress', 'work_complete', 'completed'])
        self.assertTrue(all('_action' in e['changes'] for e in actions))
        created_ts = next(e['timestamp'] for e in job if e['changes'].get('_created'))
        self.assertTrue(all(e['timestamp'] > created_ts for e in actions))

        # Task / Material: bare audit field diffs (no _action)
        task_audits = [e for e in self._for(c, 'task', 2) if 'status' in e['changes']]
        self.assertEqual(task_audits[-1]['changes']['status']['new'], 'complete')
        self.assertNotIn('_action', task_audits[-1]['changes'])
        mat = self._for(c, 'material', 3)
        self.assertTrue(any(e['changes'].get('consumption_state', {}).get('new') == 'consumed' for e in mat))

        # Shipment: picked_up action; Estimate: sent(open) + accepted
        ship = self._for(c, 'shipment', 4)
        self.assertTrue(any(e['entry_type'] == 'action'
                            and e['changes'].get('status', {}).get('new') == 'picked_up' for e in ship))
        est_new = [e['changes']['status']['new'] for e in self._for(c, 'estimate', 5)
                   if e['entry_type'] == 'action']
        self.assertEqual(est_new, ['open', 'accepted'])

    def test_initial_status_emits_no_transition(self):
        c = self._converter()
        c.add_fixture('jobs.job', 1, {'created_date': '2025-03-01T00:00:00+00:00', 'status': 'draft'})
        c.add_fixture('jobs.task', 2, {'job': 1, 'status': 'pending'})
        build.build_history(c)
        # only the _created entry for each — no status diffs
        self.assertEqual(len(self._for(c, 'job', 1)), 1)
        self.assertEqual(len(self._for(c, 'task', 2)), 1)

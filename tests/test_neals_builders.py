# tests/test_neals_builders.py
import os
import unittest
from nealsdata.converter import build
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

    def test_build_users_includes_system_user(self):
        build.build_users(self.c)
        users = self._models('core.user')
        self.assertTrue(any(u['fields']['username'] == 'system' for u in users))

    def test_build_configuration_has_numbering_keys(self):
        build.build_configuration(self.c)
        keys = {f['pk'] for f in self._models('core.configuration')}
        for k in ('job_counter', 'estimate_counter', 'invoice_counter',
                  'po_counter'):
            self.assertIn(k, keys)

    def test_build_accounting_categories(self):
        build.build_accounting_categories(self.c)
        codes = {f['fields']['code'] for f in self._models('core.accountingcategory')}
        self.assertIn('SVC', codes)
        self.assertIn('MAT', codes)

    def test_build_price_list_items(self):
        build.build_accounting_categories(self.c)
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

import os
import tempfile
import unittest
from nealsdata.converter.loaders import ExcelDataLoader, KanbanCsvLoader

XLSX = 'nealsdata/datasets/company-export-220382-2026-05-18-02-19.xlsx'


class ExcelDataLoaderTest(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(XLSX), 'workbook dataset not present')
    def test_loads_expected_sheets(self):
        loader = ExcelDataLoader(XLSX)
        loader.load()
        self.assertIn('Estimates', loader.sheets_data)
        self.assertGreater(len(loader.sheets_data['Estimates']), 100)
        # header keys are present on rows
        self.assertIn('Reference', loader.sheets_data['Estimates'][0])


class KanbanCsvLoaderTest(unittest.TestCase):
    def _write(self, body):
        fd, path = tempfile.mkstemp(suffix='.csv')
        with os.fdopen(fd, 'w', newline='') as f:
            f.write(body)
        self.addCleanup(os.unlink, path)
        return path

    def test_skips_sep_line_and_parses_tab_columns(self):
        path = self._write(
            'sep=\t\n'
            'Name\tCard type\tCard color\tDescription\tDue date\tExternal ID\t'
            'Notes\test *cut* time\test ASS time\test $\tCreated at\t'
            'Archived at\tBlock reason\n'
            'Acme (Jo Roe)\tCut job\tyellow\tdesc\t\t07754\tnote\t4\t2\t$10\t'
            '2026-02-03 04:56\t\t\n'
        )
        cards = KanbanCsvLoader(path).load()
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['External ID'], '07754')
        self.assertEqual(cards[0]['est *cut* time'], '4')
        self.assertEqual(cards[0]['Name'], 'Acme (Jo Roe)')

    @unittest.skipUnless(os.path.exists('nealsdata/datasets/neals kanban.csv'), 'kanban csv not present')
    def test_loads_real_file(self):
        cards = KanbanCsvLoader('nealsdata/datasets/neals kanban.csv').load()
        self.assertGreater(len(cards), 2000)
        self.assertTrue(any(c['External ID'] for c in cards))

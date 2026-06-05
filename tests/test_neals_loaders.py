import os
import shutil
import tempfile
import unittest
from nealsdata.converter.loaders import (
    ExcelDataLoader, KanbanCsvLoader, discover_datasets,
)

try:
    XLSX, _CSV = discover_datasets('nealsdata/datasets')
except (ValueError, FileNotFoundError):
    XLSX = 'nealsdata/datasets/__missing__.xlsx'


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

    def test_parses_comma_delimited_export(self):
        path = self._write(
            'Swimlane,Stage,Name,Description,Due date,External ID,Notes,'
            'est *cut* time,est ASS time,est $,Created at,Archived at,'
            'Checklist,Block reason\n'
            "Neal's do,estimate,Acme (Jo Roe),"
            '"desc, with commas",,07754,note,4,2,$10,2026-02-03 04:56,,,\n'
        )
        cards = KanbanCsvLoader(path).load()
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['External ID'], '07754')
        self.assertEqual(cards[0]['Description'], 'desc, with commas')
        self.assertEqual(cards[0]['Name'], 'Acme (Jo Roe)')

    @unittest.skipUnless(os.path.exists('nealsdata/datasets/neals kanban.csv'), 'kanban csv not present')
    def test_loads_real_file(self):
        cards = KanbanCsvLoader('nealsdata/datasets/neals kanban.csv').load()
        self.assertGreater(len(cards), 50)
        self.assertTrue(any(c['External ID'] for c in cards))
        self.assertIn('Checklist', cards[0])


class DiscoverDatasetsTest(unittest.TestCase):
    def _tmpdir(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        return d

    @staticmethod
    def _touch(directory, name):
        open(os.path.join(directory, name), 'w').close()

    def test_finds_single_excel_and_csv(self):
        d = self._tmpdir()
        self._touch(d, 'company-export.xlsx')
        self._touch(d, 'neals kanban.csv')
        self._touch(d, 'converted.json')  # ignored — not .xlsx/.csv
        excel, csv_path = discover_datasets(d)
        self.assertTrue(excel.endswith('company-export.xlsx'))
        self.assertTrue(csv_path.endswith('neals kanban.csv'))

    def test_errors_on_multiple_excel(self):
        d = self._tmpdir()
        self._touch(d, 'a.xlsx')
        self._touch(d, 'b.xlsx')
        self._touch(d, 'k.csv')
        with self.assertRaises(ValueError) as ctx:
            discover_datasets(d)
        self.assertIn('Excel', str(ctx.exception))

    def test_errors_on_multiple_csv(self):
        d = self._tmpdir()
        self._touch(d, 'a.xlsx')
        self._touch(d, 'one.csv')
        self._touch(d, 'two.csv')
        with self.assertRaises(ValueError) as ctx:
            discover_datasets(d)
        self.assertIn('CSV', str(ctx.exception))

    def test_errors_on_missing_excel(self):
        d = self._tmpdir()
        self._touch(d, 'k.csv')
        with self.assertRaises(ValueError):
            discover_datasets(d)

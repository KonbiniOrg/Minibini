import os
import unittest
from nealsdata.converter.loaders import ExcelDataLoader

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

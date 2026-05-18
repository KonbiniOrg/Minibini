"""Data loaders for the Neal's CNC converter."""

import csv
from pathlib import Path
from typing import Dict, List

try:
    import openpyxl
except ImportError:
    raise ImportError("openpyxl is required. Install with: pip install openpyxl")


def _single_dataset_file(matches, label, datasets_dir):
    """Return the sole file in `matches`, or raise ValueError if 0 or >1."""
    if not matches:
        raise ValueError(f'No {label} file found in {datasets_dir}')
    if len(matches) > 1:
        names = ', '.join(sorted(m.name for m in matches))
        raise ValueError(
            f'Expected exactly one {label} file in {datasets_dir}, '
            f'found {len(matches)}: {names}'
        )
    return matches[0]


def discover_datasets(datasets_dir):
    """Locate the single Excel file and single CSV file in `datasets_dir`.

    Returns (excel_path, csv_path) as strings. Raises ValueError with a
    clear message if either is missing or ambiguous (more than one).
    """
    datasets_dir = Path(datasets_dir)
    excels = sorted(datasets_dir.glob('*.xlsx')) + sorted(datasets_dir.glob('*.xls'))
    csvs = sorted(datasets_dir.glob('*.csv'))
    excel = _single_dataset_file(excels, 'Excel (.xlsx/.xls)', datasets_dir)
    csv_file = _single_dataset_file(csvs, 'CSV (.csv)', datasets_dir)
    return str(excel), str(csv_file)


class ExcelDataLoader:
    """Loads and parses Excel sheets into structured data."""

    def __init__(self, excel_path: str, verbose: bool = False):
        self.excel_path = excel_path
        self.verbose = verbose
        self.wb = None
        self.sheets_data = {}

    def load(self):
        """Load all required sheets into memory."""
        if self.verbose:
            print(f"Loading Excel file: {self.excel_path}")

        self.wb = openpyxl.load_workbook(self.excel_path, data_only=True)

        sheets_to_load = [
            'Contacts', 'Projects', 'Invoices', 'Estimates',
            'Bills', 'Price List Items'
        ]

        for sheet_name in sheets_to_load:
            if sheet_name in self.wb.sheetnames:
                self.sheets_data[sheet_name] = self._load_sheet(sheet_name)
                if self.verbose:
                    print(f"  Loaded {sheet_name}: {len(self.sheets_data[sheet_name])} rows")
            else:
                print(f"Warning: Sheet '{sheet_name}' not found in workbook")
                self.sheets_data[sheet_name] = []

        self.wb.close()

    def _load_sheet(self, sheet_name: str) -> List[Dict]:
        """Load sheet into list of dictionaries."""
        ws = self.wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))

        if not rows:
            return []

        headers = rows[0]
        data = []

        for row_idx, row_values in enumerate(rows[1:], start=2):
            row_dict = {
                '_row': row_idx,
                '_sheet': sheet_name
            }
            for idx, header in enumerate(headers):
                if header and idx < len(row_values):
                    row_dict[header] = row_values[idx]
            data.append(row_dict)

        return data


class KanbanCsvLoader:
    """Loads the tab-delimited Kanban board export into a list of dicts."""

    def __init__(self, csv_path):
        self.csv_path = csv_path

    def load(self):
        with open(self.csv_path, newline='', encoding='utf-8-sig') as f:
            first = f.readline()
            if not first.lower().startswith('sep='):
                f.seek(0)  # no sep= directive; rewind
            reader = csv.DictReader(f, delimiter='\t')
            return [dict(row) for row in reader]

"""Excel data loader for the FreeAgent export."""

from typing import Dict, List

try:
    import openpyxl
except ImportError:
    raise ImportError("openpyxl is required. Install with: pip install openpyxl")


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

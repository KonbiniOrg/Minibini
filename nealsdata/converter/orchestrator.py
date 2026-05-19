"""Orchestrates the Neal's data conversion phases."""
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from nealsdata.converter.loaders import ExcelDataLoader, KanbanCsvLoader
from nealsdata.converter import parsing as P

# nealseed fixture supplying canonical users, accounting categories and
# rate schemes (resolved relative to the repo root).
_DEFAULT_SEED_PATH = (Path(__file__).resolve().parents[2]
                      / 'fixtures' / 'large_datasets' / 'nealseed.json')


class NealsDataConverter:
    def __init__(self, excel_path, csv_path, output_path,
                 limit=100, verbose=False, seed_path=None):
        self.loader = ExcelDataLoader(excel_path, verbose=verbose)
        self.csv_loader = KanbanCsvLoader(csv_path)
        self.output_path = output_path
        self.limit = limit
        self.verbose = verbose
        self.seed_path = str(seed_path) if seed_path else str(_DEFAULT_SEED_PATH)
        self.fixture_data = []
        self._pk_counters = defaultdict(int)
        self.csv_cards = []
        self.ac_by_code = {}        # AccountingCategory code -> pk (from seed)
        self.scheme_by_name = {}    # RateScheme name -> pk (from seed)
        self.ac_svc_pk = None
        self.ac_mat_pk = None
        self.pli_map = {}
        self.org_map = {}
        self.job_map = {}
        self.jobs = {}
        self.discarded_cards = []
        self.line_items = {}
        self.estimates = {}
        self.flat_fee_scheme_pk = None  # shared flat-fee scheme (build_seed)
        self.cut_task = {}          # base_ref -> task_pk (first task whose name has 'cut')
        self.time_match_misses = 0  # count of CSV worker-time values with no matching task
        self.invoice_totals = {}    # base_ref -> Decimal total of qty*price across job's invoice lines
        self.fake_deliverable_count = 0  # jobs that got a synthetic 'Fake Deliverable'

    # --- fixture plumbing -------------------------------------------------
    def next_pk(self, model):
        self._pk_counters[model] += 1
        return self._pk_counters[model]

    def add_fixture(self, model, pk, fields):
        self.fixture_data.append({'model': model, 'pk': pk, 'fields': fields})

    # --- spine ------------------------------------------------------------
    def select_spine(self):
        """Match recent Kanban cards to Estimate Reference groups.

        Returns a list of {'card', 'base_ref', 'estimate_rows'} dicts,
        newest card first, capped at self.limit successful matches.
        """
        est_by_base = defaultdict(list)
        for row in self.loader.sheets_data.get('Estimates', []):
            ref = row.get('Reference')
            if ref:
                est_by_base[P.base_reference(ref)].append(row)

        cards = [c for c in self.csv_cards if (c.get('External ID') or '').strip()]
        cards.sort(key=lambda c: P.to_datetime(c.get('Created at')) or datetime.min,
                   reverse=True)

        spine, seen = [], set()
        for card in cards:
            base = P.base_reference(card['External ID'])
            if base in seen or base not in est_by_base:
                continue
            seen.add(base)
            spine.append({'card': card, 'base_ref': base,
                          'estimate_rows': est_by_base[base]})
            if len(spine) >= self.limit:
                break
        return spine

    def convert(self):
        from nealsdata.converter import build, reconcile
        self.loader.load()
        self.csv_cards = self.csv_loader.load()
        self.spine = self.select_spine()
        build.build_seed(self)
        build.build_configuration(self)
        build.build_price_list_items(self)
        build.build_contacts_and_businesses(self)
        build.build_jobs(self)
        build.build_estimates(self)
        build.derive_atoms(self)
        build.build_invoices(self)
        reconcile.reconcile(self)
        self._write_json()
        if self.verbose:
            self._print_summary()

    def _write_json(self):
        with open(self.output_path, 'w') as f:
            json.dump(self.fixture_data, f, indent=2, default=str)

    def _print_summary(self):
        from collections import Counter
        c = self
        counts = Counter(row['model'] for row in self.fixture_data)
        for model, n in sorted(counts.items()):
            print(f'  {n:6} {model}')
        print(f'  {c.fake_deliverable_count} jobs got a synthetic \'Fake Deliverable\' (review these)')

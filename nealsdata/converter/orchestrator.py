"""Orchestrates the Neal's data conversion phases."""
import json
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from nealsdata.converter.loaders import ExcelDataLoader, KanbanCsvLoader
from nealsdata.converter import parsing as P

# nealseed fixture supplying canonical users, accounting categories and
# rate schemes (resolved relative to the repo root).
_DEFAULT_SEED_PATH = (Path(__file__).resolve().parents[2]
                      / 'fixtures' / 'large_datasets' / 'nealseed.json')

# Fixed RNG seed so regeneration is byte-stable unless the inputs change
# (invented worker times and blep lengths/placement draw from random).
_RNG_SEED = 20260612


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
        self.pli_index = []             # [{'code','description'}] for material matching
        self.pli_purchase_by_code = {}  # code -> purchase_price string
        self.org_map = {}
        self.job_map = {}
        self.jobs = {}
        self.discarded_cards = []
        self.line_items = {}
        self.estimates = {}
        self.flat_fee_scheme_pk = None  # shared flat-fee scheme (build_seed)
        self.scheme_algorithm_by_pk = {}  # ratescheme pk -> algorithm (for actuals)
        self.user_by_username = {}      # username -> pk (build_seed assigns user pks)
        self.rotation_user_pks = []     # ordered blep-rotation pool (excludes system)
        self._mint_template = None      # a seed worker's fields, cloned when minting
        self._mint_seq = 1              # worker{N} mint counter
        self.cut_task = {}          # base_ref -> task_pk (first task whose name has 'cut')
        self.cut_plan_task = {}     # base_ref -> plan_task_pk (plan-side analogue)
        self.invoice_totals = {}    # base_ref -> Decimal total of qty*price across job's invoice lines
        self.fake_deliverable_count = 0  # jobs that got a synthetic 'Fake Deliverable'
        self.invoice_line_kinds = {}  # invoicelineitem pk -> 'task' | 'material' | 'lineitem' | 'skip'

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
        # Seed the RNG before any random-driven phase so output is deterministic.
        random.seed(_RNG_SEED)
        self.loader.load()
        self.csv_cards = self.csv_loader.load()
        self.spine = self.select_spine()
        build.build_seed(self)
        build.build_configuration(self)
        build.build_inventory_items(self)
        build.build_contacts_and_businesses(self)
        build.build_jobs(self)
        build.build_estimates(self)
        build.derive_atoms(self)
        build.assign_worker_times(self)  # per-task random est_worker_time
        build.assign_est_quantities(self)  # real-task est_qty heuristic (needs worker times)
        build.build_invoices(self)
        build.build_invoice_line_item_sources(self)
        reconcile.reconcile(self)
        build.assign_project_managers(self)  # after reconcile: needs final job status
        build.build_shipments(self)   # after reconcile: needs final job dates
        build.build_bleps_and_shifts(self)  # after reconcile: needs final task status/dates
        build.build_history(self)     # last: emit a created entry per tracked object
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

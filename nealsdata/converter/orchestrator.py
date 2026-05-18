"""Orchestrates the Neal's data conversion phases."""
import json
from collections import defaultdict
from datetime import datetime

from nealsdata.converter.loaders import ExcelDataLoader, KanbanCsvLoader
from nealsdata.converter import parsing as P


class NealsDataConverter:
    def __init__(self, excel_path, csv_path, output_path,
                 limit=100, verbose=False):
        self.loader = ExcelDataLoader(excel_path, verbose=verbose)
        self.csv_loader = KanbanCsvLoader(csv_path)
        self.output_path = output_path
        self.limit = limit
        self.verbose = verbose
        self.fixture_data = []
        self._pk_counters = defaultdict(int)
        self.csv_cards = []
        self.default_user_pk = None
        self.ac_svc_pk = None
        self.ac_mat_pk = None
        self.pli_map = {}
        self.org_map = {}
        self.job_map = {}
        self.jobs = {}
        self.discarded_cards = []
        self.line_items = {}
        self.estimates = {}

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
        raise NotImplementedError('phases wired in Task 14')

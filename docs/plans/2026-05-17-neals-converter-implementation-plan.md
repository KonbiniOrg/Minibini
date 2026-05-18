# Neal's Data Converter — Schema Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-target `nealsdata/convert_neals_data.py` to the current Minibini schema and make the Kanban CSV the spine that defines which Jobs exist.

**Architecture:** Targeted rewrite (Approach C). Keep the data-shape-tuned Excel parsing; rewrite the model-building and reconciliation layer; add a Kanban CSV loader. Output stays Django `loaddata` fixture JSON. Design spec: `docs/plans/2026-05-17-neals-converter-schema-update-design.md`.

**Tech Stack:** Python 3.12, `openpyxl`, Python stdlib `csv`, Django 5.2 test runner (`python manage.py test`).

**Inputs:** `nealsdata/datasets/company-export-220382-2026-05-18-02-19.xlsx`, `nealsdata/datasets/neals kanban.csv`.

**Conventions:**
- Tests live in `tests/` and run with `python manage.py test tests.<module>`. **Never run the test suite from multiple agents in parallel** (shared MySQL test DB — see CLAUDE.md).
- **Never write to the dev DB.** `call_command('loaddata', ...)` inside a Django `TestCase` runs against the auto-created test DB and is safe; nothing in this plan runs `loaddata` against the dev DB.
- Commit after every task.

---

## Reference: data facts (verified against the workbook)

Sheet columns (0-indexed) the converter consumes:

- **Estimates:** `[0]Project [1]Reference [2]Date [3]Status [5]Notes [9]Total Value [10]Contact` then per-line-item `[41]Item Type [42]Quantity [43]Price [44]Description [50]Category Name`.
- **Invoices:** `[2]Projects [3]Reference [4]Date [6]Status [9]Paid Amount [10]Paid Date [14]Total Value` then `[54]Item Type [55]Quantity [56]Price [57]Description [61]Project`.
- **Bills:** `[0]Contact Organisation [1]Contact Name [2]Date [3]Due Date [4]Reference [9]Gross Value [14]Project` then `[20]Item Type [21]Quantity [23]Description [26]Subtotal`.
- **Projects:** `[0]Name [1]Client Organisation [2]Client Name [8]Status [13]Created Date [14]Updated Date`.
- **Contacts:** `[0]Organisation [1]First Name [2]Last Name [3]Email [5]Phone Number [13]Mobile Phone Number`.
- **Price List Items:** `[0]Code [1]Quantity [2]Type [3]Price [4]Description`.
- **Kanban CSV** (tab-delimited, first line is `sep=\t`): `[0]Name [1]Card type [2]Card color [3]Description [4]Due date [5]External ID [6]Notes [7]est *cut* time [8]est ASS time [9]est $ [10]Created at [11]Archived at [12]Block reason`.

Matching: CSV `External ID` (e.g. `07754`) → Estimate `Reference`. Revisions are letter-suffixed (`03024`, `03024b`, `03024c`); the **base reference** is the digits, the suffix marks the version chain. Project `Name` embeds the estimate prefix (`"03024 - Round Desks"`); Estimates link to a Project via `[0]Project`.

`Item Type` values on estimate line items: `-no unit-` (bulk), `Hours`, `Days`, `Comment`, `Products`, `Services`, `Expenses`, `Discount`, `Credit`.

---

## File structure

```
nealsdata/
  __init__.py              # NEW — empty; makes nealsdata importable in tests
  convert_neals_data.py    # REWRITE — thin CLI entry
  converter/
    __init__.py            # NEW — empty
    loaders.py             # NEW — ExcelDataLoader (ported) + KanbanCsvLoader
    parsing.py             # NEW — pure helpers: dates, decimals, names,
                            #   revision suffix, line-item classification,
                            #   RateScheme algorithm inference
    build.py               # NEW — model builders
    reconcile.py           # NEW — cross-model status/date reconciliation
    orchestrator.py        # NEW — NealsDataConverter; wires phases
tests/
  test_neals_parsing.py        # NEW — unit tests for parsing.py
  test_neals_loaders.py        # NEW — unit tests for KanbanCsvLoader
  test_neals_builders.py       # NEW — unit tests for build.py / reconcile.py
  test_neals_fixture.py        # NEW — loaddata integration test
```

The old `nealsdata/convert_neals_data.py` (3033 lines) is fully replaced. Keep a copy at `nealsdata/convert_neals_data.py.bak` until Task 15 confirms the new pipeline works, then delete the backup.

---

### Task 1: Package scaffold + Excel loader

**Files:**
- Create: `nealsdata/__init__.py` (empty), `nealsdata/converter/__init__.py` (empty)
- Create: `nealsdata/converter/loaders.py`
- Backup then rewrite: `nealsdata/convert_neals_data.py`
- Test: `tests/test_neals_loaders.py`

- [ ] **Step 1: Back up the old script**

```bash
cp nealsdata/convert_neals_data.py nealsdata/convert_neals_data.py.bak
```

- [ ] **Step 2: Create the empty package files**

```bash
touch nealsdata/__init__.py nealsdata/converter/__init__.py
```

- [ ] **Step 3: Write `loaders.py` with `ExcelDataLoader`**

Port `ExcelDataLoader` verbatim from `convert_neals_data.py.bak` (lines 101-154) into `nealsdata/converter/loaders.py`. It already loads sheets into lists of dicts keyed by header, tagging each row with `_row` and `_sheet`. Change the `sheets_to_load` list to: `['Contacts', 'Projects', 'Invoices', 'Estimates', 'Bills', 'Price List Items']` (drop `Tasks` and `Timeslips` — no longer used).

- [ ] **Step 4: Write the failing test**

```python
# tests/test_neals_loaders.py
import unittest
from nealsdata.converter.loaders import ExcelDataLoader

XLSX = 'nealsdata/datasets/company-export-220382-2026-05-18-02-19.xlsx'

class ExcelDataLoaderTest(unittest.TestCase):
    def test_loads_expected_sheets(self):
        loader = ExcelDataLoader(XLSX)
        loader.load()
        self.assertIn('Estimates', loader.sheets_data)
        self.assertGreater(len(loader.sheets_data['Estimates']), 100)
        # header keys are present on rows
        self.assertIn('Reference', loader.sheets_data['Estimates'][0])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_neals_loaders -v 2`
Expected: PASS.

- [ ] **Step 6: Stub the CLI entry**

Rewrite `nealsdata/convert_neals_data.py` as a thin entry that parses args and calls the orchestrator (orchestrator written in Task 5; until then, import lazily inside `main()`):

```python
#!/usr/bin/env python3
"""Convert Neal's CNC FreeAgent export + Kanban CSV to a Django fixture JSON."""
import argparse


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('excel', help='Path to the FreeAgent .xlsx export')
    p.add_argument('--csv', default='nealsdata/datasets/neals kanban.csv',
                   help='Path to the Kanban board CSV export')
    p.add_argument('--output', default='nealsdata/datasets/converted.json')
    p.add_argument('--limit', type=int, default=100,
                   help='Approx. number of Jobs to build from recent cards')
    p.add_argument('--verbose', action='store_true')
    args = p.parse_args()

    from nealsdata.converter.orchestrator import NealsDataConverter
    NealsDataConverter(
        excel_path=args.excel, csv_path=args.csv, output_path=args.output,
        limit=args.limit, verbose=args.verbose,
    ).convert()


if __name__ == '__main__':
    main()
```

- [ ] **Step 7: Commit**

```bash
git add nealsdata/ tests/test_neals_loaders.py
git commit -m "refactor(nealsdata): scaffold converter package + Excel loader"
```

---

### Task 2: Kanban CSV loader

**Files:**
- Modify: `nealsdata/converter/loaders.py`
- Test: `tests/test_neals_loaders.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_neals_loaders.py
import csv, os, tempfile
from nealsdata.converter.loaders import KanbanCsvLoader

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_neals_loaders.KanbanCsvLoaderTest -v 2`
Expected: FAIL — `cannot import name 'KanbanCsvLoader'`.

- [ ] **Step 3: Implement `KanbanCsvLoader`**

Add to `nealsdata/converter/loaders.py`:

```python
import csv


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_neals_loaders.KanbanCsvLoaderTest -v 2`
Expected: PASS.

- [ ] **Step 5: Add a real-file smoke test**

```python
# add to KanbanCsvLoaderTest
    def test_loads_real_file(self):
        cards = KanbanCsvLoader('nealsdata/datasets/neals kanban.csv').load()
        self.assertGreater(len(cards), 2000)
        self.assertTrue(any(c['External ID'] for c in cards))
```

Run: `python manage.py test tests.test_neals_loaders -v 2` → PASS.

- [ ] **Step 6: Commit**

```bash
git add nealsdata/converter/loaders.py tests/test_neals_loaders.py
git commit -m "feat(nealsdata): add Kanban CSV loader"
```

---

### Task 3: Parsing helpers

**Files:**
- Create: `nealsdata/converter/parsing.py`
- Test: `tests/test_neals_parsing.py`

Pure functions, no I/O. Each gets its own failing test first.

- [ ] **Step 1: Write failing tests for all helpers**

```python
# tests/test_neals_parsing.py
import unittest
from datetime import datetime
from decimal import Decimal
from nealsdata.converter import parsing as P


class ParsingTest(unittest.TestCase):
    def test_parse_decimal(self):
        self.assertEqual(P.parse_decimal('$1,234.50'), Decimal('1234.50'))
        self.assertEqual(P.parse_decimal(None), Decimal('0'))
        self.assertEqual(P.parse_decimal(12), Decimal('12'))

    def test_format_date(self):
        self.assertEqual(P.format_date(datetime(2026, 2, 3, 4, 56)), '2026-02-03')
        self.assertEqual(P.format_date('2026-02-03 04:56'), '2026-02-03')
        self.assertIsNone(P.format_date(None))

    def test_split_name(self):
        self.assertEqual(P.split_name('Jo Roe'), ('Jo', 'Roe'))
        self.assertEqual(P.split_name(''), ('(unknown)', '(unknown)'))
        self.assertEqual(P.split_name('Cher'), ('Cher', '(unknown)'))

    def test_revision_base_and_suffix(self):
        self.assertEqual(P.revision_parts('03024'), ('03024', 0))
        self.assertEqual(P.revision_parts('03024b'), ('03024', 1))
        self.assertEqual(P.revision_parts('03024c'), ('03024', 2))

    def test_hours_to_duration(self):
        self.assertEqual(P.hours_to_duration('4'), '04:00:00')
        self.assertEqual(P.hours_to_duration('1.5'), '01:30:00')
        self.assertIsNone(P.hours_to_duration(''))

    def test_parse_kanban_name(self):
        self.assertEqual(P.parse_kanban_name('Acme (Jo Roe)'), ('Acme', 'Jo Roe'))
        self.assertEqual(P.parse_kanban_name('Acme'), ('Acme', None))
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_neals_parsing -v 2`
Expected: FAIL — `No module named 'nealsdata.converter.parsing'`.

- [ ] **Step 3: Implement `parsing.py` helpers**

```python
"""Pure parsing/normalisation helpers for the Neal's data converter."""
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation


def parse_decimal(value):
    if value is None or value == '':
        return Decimal('0')
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    cleaned = re.sub(r'[^0-9.\-]', '', str(value))
    try:
        return Decimal(cleaned) if cleaned else Decimal('0')
    except InvalidOperation:
        return Decimal('0')


def format_date(value):
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d')
    text = str(value).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(text, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None


def to_datetime(value):
    """Parse a cell into a datetime, or None."""
    if isinstance(value, datetime):
        return value
    if value in (None, ''):
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    return None


def split_name(full_name):
    if not full_name or not str(full_name).strip():
        return ('(unknown)', '(unknown)')
    parts = str(full_name).strip().split()
    if len(parts) == 1:
        return (parts[0], '(unknown)')
    return (parts[0], ' '.join(parts[1:]))


def revision_parts(reference):
    """('03024b') -> ('03024', 1). Suffix letters a/b/c... -> version index."""
    m = re.match(r'^(\d+)([a-zA-Z]*)$', str(reference).strip())
    if not m:
        return (str(reference).strip(), 0)
    digits, suffix = m.group(1), m.group(2).lower()
    if not suffix:
        return (digits, 0)
    return (digits, ord(suffix[-1]) - ord('a') + 1)


def hours_to_duration(value):
    """'1.5' hours -> Django DurationField string '01:30:00'. '' -> None."""
    if value in (None, ''):
        return None
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return None
    total = timedelta(hours=hours)
    s = int(total.total_seconds())
    return f'{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}'


def parse_kanban_name(name):
    """'Business (Contact)' -> ('Business', 'Contact'); 'Business' -> ('Business', None)."""
    m = re.match(r'^(.*?)\s*\(([^)]+)\)\s*$', str(name).strip())
    if m:
        return (m.group(1).strip(), m.group(2).strip())
    return (str(name).strip(), None)
```

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_neals_parsing -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/parsing.py tests/test_neals_parsing.py
git commit -m "feat(nealsdata): add pure parsing helpers"
```

---

### Task 4: Line-item classification + RateScheme inference

**Files:**
- Modify: `nealsdata/converter/parsing.py`
- Test: `tests/test_neals_parsing.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_neals_parsing.py
class ClassifyTest(unittest.TestCase):
    def test_comment_is_skipped(self):
        self.assertEqual(P.classify_line_item('Comment', 'anything'), 'skip')

    def test_item_type_drives_classification(self):
        self.assertEqual(P.classify_line_item('Hours', 'cut parts'), 'task')
        self.assertEqual(P.classify_line_item('Days', 'design'), 'task')
        self.assertEqual(P.classify_line_item('Services', 'consult'), 'task')
        self.assertEqual(P.classify_line_item('Products', 'plywood'), 'material')
        self.assertEqual(P.classify_line_item('Expenses', 'shipping'), 'material')
        self.assertEqual(P.classify_line_item('Discount', 'x'), 'lineitem')
        self.assertEqual(P.classify_line_item('Credit', 'x'), 'lineitem')

    def test_no_unit_uses_keyword_heuristic(self):
        self.assertEqual(
            P.classify_line_item('-no unit-', '3 sheets of 3/4" plywood'), 'material')
        self.assertEqual(
            P.classify_line_item('-no unit-', 'CNC cutting of wall parts'), 'task')

    def test_algorithm_inference(self):
        self.assertEqual(P.infer_algorithm('Hours', 'hours'), 'elapsed_time')
        self.assertEqual(P.infer_algorithm('Days', 'days'), 'elapsed_time')
        self.assertEqual(P.infer_algorithm('Services', ''), 'flat_fee')
        self.assertEqual(P.infer_algorithm('-no unit-', 'each'), 'entered_qty')
        self.assertEqual(P.infer_algorithm('-no unit-', ''), 'flat_fee')
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_neals_parsing.ClassifyTest -v 2`
Expected: FAIL — `module 'parsing' has no attribute 'classify_line_item'`.

- [ ] **Step 3: Implement classification + inference**

Add to `nealsdata/converter/parsing.py`:

```python
MATERIAL_KEYWORDS = (
    'plywood', 'acrylic', 'mdf', 'sheet', 'hardwood', 'melamine', 'sintra',
    'aluminum', 'aluminium', 'board feet', 'lumber', 'plastic', 'steel',
    'wood', 'foam', 'gator', 'laminate', 'trupan', 'chipboard', 'baltic birch',
)
COUNT_UNITS = ('each', 'ea', 'pcs', 'pieces', 'unit', 'units')


def classify_line_item(item_type, description):
    """Return one of: 'skip', 'task', 'material', 'lineitem'."""
    it = (item_type or '').strip().lower()
    if it == 'comment':
        return 'skip'
    if it in ('hours', 'days', 'services'):
        return 'task'
    if it in ('products', 'expenses'):
        return 'material'
    if it in ('discount', 'credit'):
        return 'lineitem'
    # '-no unit-' and anything unrecognised: keyword heuristic
    desc = (description or '').lower()
    if any(kw in desc for kw in MATERIAL_KEYWORDS):
        return 'material'
    return 'task'


def infer_algorithm(item_type, units):
    """RateScheme.algorithm for a Task-classified line item."""
    it = (item_type or '').strip().lower()
    u = (units or '').strip().lower()
    if it in ('hours', 'days') or u in ('hour', 'hours', 'day', 'days'):
        return 'elapsed_time'
    if u in COUNT_UNITS:
        return 'entered_qty'
    return 'flat_fee'
```

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_neals_parsing -v 2`
Expected: PASS (all parsing tests).

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/parsing.py tests/test_neals_parsing.py
git commit -m "feat(nealsdata): line-item classification + RateScheme inference"
```

---

### Task 5: Orchestrator skeleton + spine selection

**Files:**
- Create: `nealsdata/converter/orchestrator.py`
- Test: `tests/test_neals_builders.py`

The orchestrator owns: PK allocation, the `fixture_data` list, an `add_fixture` helper, and the phase sequence. Spine selection matches CSV cards to Estimates and picks ~`limit` recent ones.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_neals_builders.py
import unittest
from nealsdata.converter.orchestrator import NealsDataConverter

XLSX = 'nealsdata/datasets/company-export-220382-2026-05-18-02-19.xlsx'
CSV = 'nealsdata/datasets/neals kanban.csv'


class SpineTest(unittest.TestCase):
    def test_spine_selects_limited_recent_matched_cards(self):
        c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=20)
        c.loader.load()
        c.csv_cards = c.csv_loader.load()
        spine = c.select_spine()
        self.assertLessEqual(len(spine), 20)
        self.assertGreater(len(spine), 0)
        for entry in spine:
            # each spine entry pairs a card with a matched estimate group
            self.assertIn('card', entry)
            self.assertIn('estimate_rows', entry)
            self.assertTrue(entry['estimate_rows'])
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_neals_builders.SpineTest -v 2`
Expected: FAIL — `No module named 'nealsdata.converter.orchestrator'`.

- [ ] **Step 3: Implement the orchestrator skeleton + `select_spine`**

```python
"""Orchestrates the Neal's data conversion phases."""
import json
from collections import defaultdict

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
        # group Estimate rows by base reference (digits, suffix stripped)
        est_by_base = defaultdict(list)
        for row in self.loader.sheets_data.get('Estimates', []):
            ref = row.get('Reference')
            if ref:
                base, _ = P.revision_parts(ref)
                est_by_base[base].append(row)

        cards = [c for c in self.csv_cards if (c.get('External ID') or '').strip()]
        cards.sort(key=lambda c: P.to_datetime(c.get('Created at')) or
                   __import__('datetime').datetime.min, reverse=True)

        spine, seen = [], set()
        for card in cards:
            ext = card['External ID'].strip()
            base, _ = P.revision_parts(ext)
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
```

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_neals_builders.SpineTest -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/orchestrator.py tests/test_neals_builders.py
git commit -m "feat(nealsdata): orchestrator skeleton + spine selection"
```

---

### Task 6: Base builders (users, configuration, accounting categories, price list items)

**Files:**
- Create: `nealsdata/converter/build.py`
- Test: `tests/test_neals_builders.py`

`build.py` holds free functions taking the converter as first arg, so they can call `next_pk`/`add_fixture`. Build order and field shapes follow `docs/designs/data-constraints.md` §1.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_neals_builders.py
from nealsdata.converter import build


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
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_neals_builders.BaseBuildersTest -v 2`
Expected: FAIL — `No module named 'nealsdata.converter.build'`.

- [ ] **Step 3: Implement the base builders**

Create `nealsdata/converter/build.py`. Implementation notes:

- `build_users(c)` — emit a `system` user (`username='system'`, `is_active=False`, unusable password `'!'`) and 2-3 ordinary staff users. Store the lowest-permission user pk on `c.default_user_pk`. `core.user` fields: `username`, `password` (`'!'`), `is_active`, `is_staff=False`, `is_superuser=False`, `first_name`, `last_name`, `email`.
- `build_configuration(c)` — emit `core.configuration` rows (pk = the key). Keys and values: `job_number_sequence`=`J{year}-{counter:04d}`, `job_counter`=`0`, `estimate_number_sequence`=`E{year}-{counter:04d}`, `estimate_counter`=`0`, `invoice_number_sequence`=`INV-{year}-{counter:04d}`, `invoice_counter`=`0`, `po_number_sequence`=`PO-{year}-{counter:04d}`, `po_counter`=`0`, `est_expire_days`=`30`, `email_retention_days`=`30`, `units_list`=`hours,each,sheet`.
- `build_accounting_categories(c)` — emit `core.accountingcategory` rows for at least `SVC` (Service, taxable) and `MAT` (Materials, taxable); store their pks on `c.ac_svc_pk` and `c.ac_mat_pk`. Fields: `code`, `name`, `taxable=True`, `is_active=True`, `qbo_item_id=None`, `qbo_expense_account_id=None`.
- `build_price_list_items(c)` — one `inventory.pricelistitem` per row of the `Price List Items` sheet. Fields: `code` (sheet `[0]Code`, deduped — skip duplicates), `description` (`[4]`), `purchase_price`=`0`, `selling_price`=`parse_decimal([3]Price)`, `accounting_category`=`c.ac_mat_pk`, `is_inventoried=False`, `qty_on_hand=0`, `qty_sold=0`, `qty_wasted=0`, `is_active=True`. Store a `code -> pk` map on `c.pli_map`.

Each builder appends via `c.add_fixture(...)` using `c.next_pk(model)`.

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_neals_builders.BaseBuildersTest -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/build.py tests/test_neals_builders.py
git commit -m "feat(nealsdata): base builders (users, config, AC, PLI)"
```

---

### Task 7: Contact + Business builders

**Files:**
- Modify: `nealsdata/converter/build.py`
- Test: `tests/test_neals_builders.py`

Build Contacts/Businesses only for organisations referenced by the spine's projects and the spine's bills. Handle the Business↔Contact circular dependency per data-constraints §1.5: emit the Contact first (`business=None`), then the Business (`default_contact`=that contact), then a second Contact fixture is **not** needed — instead emit the Contact with its final `business` set, and emit the Business referencing it; `loaddata` resolves forward references within one file.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_neals_builders.py
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
        # every business points at a contact that exists
        contact_pks = {f['pk'] for f in contacts}
        for b in businesses:
            self.assertIn(b['fields']['default_contact'], contact_pks)
        # every contact has an email and a phone (data-constraints §1.5)
        for ct in contacts:
            self.assertTrue(ct['fields']['email'])
            self.assertTrue(ct['fields']['work_number'] or
                            ct['fields']['mobile_number'] or
                            ct['fields']['home_number'])
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_neals_builders.ContactBuildersTest -v 2`
Expected: FAIL — `build` has no `build_contacts_and_businesses`.

- [ ] **Step 3: Implement `build_contacts_and_businesses`**

Logic:
1. Collect referenced org names: from each spine entry's Project rows (`Client Organisation`) and from Bills linked to those projects (`Contact Organisation`).
2. Index the `Contacts` sheet by `Organisation`.
3. For each referenced org with a Contacts-sheet row: allocate a Contact pk and a Business pk.
   - `contacts.contact` fields: `first_name`/`last_name` (`split_name` of `First Name`+`Last Name`, falling back to `(unknown)`), `email` (sheet `Email`; if blank synthesize `noreply+{pk}@example.com`), `work_number` (sheet `Phone Number`; if blank and no mobile use `'000-000-0000'`), `mobile_number` (sheet `Mobile Phone Number` or `''`), `home_number=''`, `business`=the Business pk, `qbo_customer_id=None`, plus blank address fields as the model requires.
   - `contacts.business` fields: `business_name`=org, `our_reference_code`=`f'BUS-{pk:04d}'`, `default_contact`=the Contact pk, `tax_multiplier=None`, `qbo_customer_id=None`, `qbo_vendor_id=None`.
4. Store `org -> {'business': pk, 'contact': pk}` on `c.org_map`.
5. For orgs with no Contacts-sheet match, synthesize a minimal Contact+Business the same way using `(unknown)` names.

Reuse `ContactMismatchHandler` from the old script only if a referenced name disagrees with the sheet — otherwise non-interactive default (`map`). Port `ContactMismatchHandler` into `parsing.py` if needed; for `--non-interactive` runs it always maps.

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_neals_builders.ContactBuildersTest -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/build.py tests/test_neals_builders.py
git commit -m "feat(nealsdata): contact + business builders (referenced only)"
```

---

### Task 8: Job builder

**Files:**
- Modify: `nealsdata/converter/build.py`
- Test: `tests/test_neals_builders.py`

One `jobs.job` per spine entry. The Job's `contact` is resolved from the spine entry's Project `Client Organisation`/`Client Name` via `c.org_map`. CSV fields are applied here (status-dependent fields are finalised in reconcile, Task 13).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_neals_builders.py
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
        self.assertEqual(len(jobs), len(self.c.spine))
        for j in jobs:
            self.assertTrue(j['fields']['job_number'])
            self.assertIsNotNone(j['fields']['contact'])
            self.assertIn(j['fields']['status'],
                          ('draft', 'submitted', 'approved', 'in_progress',
                           'work_complete', 'completed', 'cancelled', 'rejected'))
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_neals_builders.JobBuilderTest -v 2`
Expected: FAIL — `build` has no `build_jobs`.

- [ ] **Step 3: Implement `build_jobs`**

For each spine entry:
1. Pick the representative Project row: the first of the entry's `estimate_rows` has a `Project` value → find that Project in the `Projects` sheet; if absent, derive client from the CSV card's `Name` via `parse_kanban_name`.
2. Resolve `contact` pk from `c.org_map` using the project's `Client Organisation`. If the org/name disagree with the CSV `Name` (`parse_kanban_name`), discard the spine entry and record it (validation failure per design §5 step 3). Track discards on `c.discarded_cards`.
3. Allocate job pk; `job_number` = `f'J{year}-{counter:04d}'` where `year` comes from the matched estimate `Date` and counter increments per year.
4. `jobs.job` fields: `name` = project name or card name (≤50 chars), `job_number`, `contact`, `status` = mapped from Project `Status` (`Completed→completed`, `Active→approved`, `Cancelled→cancelled`; default `approved`), `created_date` = `format_date` of the matched estimate `Date`, `start_date=None` (set in reconcile), `due_date` = `format_date(card['Due date'])`, `completed_date=None` (set in reconcile), `customer_po_number=''`, `description` = CSV `Description` + `'\n'` + CSV `Notes` (joined, stripped).
5. Store `c.job_map[base_ref] = job_pk`; keep the card and matched estimate rows on a per-job record `c.jobs[base_ref]` for later phases.

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_neals_builders.JobBuilderTest -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/build.py tests/test_neals_builders.py
git commit -m "feat(nealsdata): job builder from Kanban spine"
```

---

### Task 9: Estimate + EstimateLineItem builder

**Files:**
- Modify: `nealsdata/converter/build.py`
- Test: `tests/test_neals_builders.py`

Port the line-item header-row detection from the old script (`_collect_all_estimates`, lines 450-467, plus the row-shape switch described in `convert.md`): in the Estimates sheet the container rows carry `Project`/`Reference`/`Status`; the following rows carry only `Item Type`/`Quantity`/`Price`/`Description`. Group line-item rows under the preceding container.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_neals_builders.py
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
        # line numbers restart per estimate and are contiguous from 1
        by_est = {}
        for li in lines:
            by_est.setdefault(li['fields']['estimate'], []).append(
                li['fields']['line_number'])
        for nums in by_est.values():
            self.assertEqual(sorted(nums), list(range(1, len(nums) + 1)))

    def test_comment_lines_excluded(self):
        build.build_estimates(self.c)
        # Comment rows must never become line items
        for li in self._models('estimates.estimatelineitem'):
            self.assertNotEqual(li['fields'].get('_item_type'), 'Comment')
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_neals_builders.EstimateBuilderTest -v 2`
Expected: FAIL — `build` has no `build_estimates`.

- [ ] **Step 3: Implement `build_estimates`**

For each job's matched estimate group (`c.jobs[base_ref]['estimate_rows']`):
1. Sort the group's rows into (container, [line-item rows]) pairs preserving sheet order. A container row has a non-empty `Reference`; subsequent rows until the next `Reference` are its line items.
2. For each container (one per estimate version), allocate an `estimates.estimate` pk. Fields: `job` = `c.job_map[base_ref]`, `estimate_number` = the `Reference` digits, `version` = `revision_parts(Reference)[1] + 1`, `parent=None` (linked in reconcile), `status` = mapped (`Draft→draft, Sent→open, Approved→accepted, Rejected→rejected`; default `draft`), `created_date` = `format_date(Date)`, `sent_date=None`, `expiration_date=None`, `closed_date=None` (dates finalised in reconcile).
3. For each line-item row under the container, call `classify_line_item(Item Type, Description)`:
   - `'skip'` → ignore (Comment).
   - else → emit an `estimates.estimatelineitem`. Fields: `estimate` = est pk, `price_list_item=None`, `source_template=None`, `line_number` = sequential from 1 per estimate, `qty` = `parse_decimal(Quantity)`, `units` = derived from `Item Type` (`Hours→hours, Days→days`, else `none`), `description` = `Description`, `price` = `parse_decimal(Price)`, `accounting_category=None`, `taxable_override=None`, `tax_rate_override=None`. Stash the classification + `Item Type` + raw row on a parallel structure `c.line_items[est_pk]` for Task 10.
4. Store `c.estimates[base_ref]` = list of `{est_pk, status, created_date, version, base_ref}` for reconcile.

(The `_item_type` key in the test refers to a debug field — only stash classification data off-fixture in `c.line_items`; do not add `_item_type` to emitted fixture fields. Adjust the test to read `c.line_items` instead if you added no debug field.)

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_neals_builders.EstimateBuilderTest -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/build.py tests/test_neals_builders.py
git commit -m "feat(nealsdata): estimate + line-item builder (Comment-filtered)"
```

---

### Task 10: RateScheme + Task + Material + Deliverable derivation

**Files:**
- Modify: `nealsdata/converter/build.py`
- Test: `tests/test_neals_builders.py`

Derive Job-side atoms from the estimate line items stashed in `c.line_items`. The estimate keeps its line items (built in Task 9) — these are **copies**.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_neals_builders.py
class AtomDerivationTest(unittest.TestCase):
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

    def test_derives_ratescheme_task_material_deliverable(self):
        build.derive_atoms(self.c)
        self.assertGreater(len(self._models('jobs.ratescheme')), 0)
        self.assertGreater(len(self._models('jobs.task')), 0)
        # every Task points at a RateScheme that exists
        rs_pks = {f['pk'] for f in self._models('jobs.ratescheme')}
        for t in self._models('jobs.task'):
            self.assertIn(t['fields']['rate_scheme'], rs_pks)
        # every Job has at least one Deliverable
        job_pks = {f['pk'] for f in self._models('jobs.job')}
        deliv_jobs = {d['fields']['job'] for d in self._models('deliverables.deliverable')}
        self.assertEqual(job_pks, deliv_jobs)

    def test_materials_link_to_cut_task_when_present(self):
        build.derive_atoms(self.c)
        tasks = self._models('jobs.task')
        cut_task_pks = {t['pk'] for t in tasks if 'cut' in t['fields']['name'].lower()}
        for m in self._models('inventory.material'):
            if m['fields']['task'] is not None:
                self.assertIn(m['fields']['task'], cut_task_pks)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_neals_builders.AtomDerivationTest -v 2`
Expected: FAIL — `build` has no `derive_atoms`.

- [ ] **Step 3: Implement `derive_atoms`**

For each job (`base_ref`):
1. **RateSchemes** — for each Task-classified line item, compute `algorithm = infer_algorithm(item_type, units)`, `rate = price`, `unit_label = units or 'hours'`, `ac = c.ac_svc_pk`. Dedupe on `(algorithm, rate, unit_label, ac)` in a converter-wide `c.rate_scheme_map`; on miss, emit a `jobs.ratescheme` (fields: `name` = `f'{algorithm} ${rate}/{unit_label}'` made unique with a counter suffix on collision, `description=''`, `algorithm`, `rate` (string), `unit_label`, `modifiers=[]`, `accounting_category=ac`, `replaced_by=None`, `replaced_at=None`).
2. **Tasks** — for each Task-classified line item emit a `jobs.task` (fields: `job` = job pk, `rate_scheme` = scheme pk, `name` = description truncated to 255, `description` = full description, `est_qty` = qty (string), `est_worker_time=None`, `actual_qty=None`, `active_modifiers=[]`, `status='pending'` (finalised in reconcile), `blocked_reason=''`, `worker_queue=None`, `assignee=None`, `parent_task=None`, `source_template=None`, `source_plan_task=None`, `sort_order` sequential per job). Record the first task whose name lower-cases-contains `cut` as `c.cut_task[base_ref]`.
3. **Materials** — for each material-classified line item emit an `inventory.material` (fields: `job` = job pk, `task` = `c.cut_task.get(base_ref)` or `None`, `description`, `quantity` = qty (string), `units`, `unit_cost='0'`, `sell_price` = price (string), `accounting_category=c.ac_mat_pk`, `price_list_item=None`, `consumption_state='pending'`, `restocked_qty='0'`, `po_line_item=None`, `source_plan_material=None`).
4. **CSV times** — apply `est *cut* time` to the `est_worker_time` of the job's cut task (if any), and `est ASS time` to the first task whose name contains `assemb` or `ass`. Use `hours_to_duration`. Count misses on `c.time_match_misses`.
5. **Deliverables** — second pass over the job's non-Comment line items: a line is a deliverable candidate if its classification is `task` or `material` is **not** required — instead pick lines whose `qty > 1` and which are not pure raw material keywords. Emit `deliverables.deliverable` (fields: `job`, `description`, `qty_ordered` = qty (string), `units`, `sort_order` 10/20/30…). If the job produced zero deliverables, emit one `{description: 'Fake Deliverable', qty_ordered: '1', units: 'each', sort_order: 10}`.

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_neals_builders.AtomDerivationTest -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/build.py tests/test_neals_builders.py
git commit -m "feat(nealsdata): derive RateSchemes, Tasks, Materials, Deliverables"
```

---

### Task 11: Invoice + InvoiceLineItem builder

**Files:**
- Modify: `nealsdata/converter/build.py`
- Test: `tests/test_neals_builders.py`

Invoices link to a Job via the `Projects`/`Project` column. Same container/line-item row-shape switch as estimates (container row has `Reference`; following rows carry `Item Type`/`Quantity`/`Price`/`Description`). Invoices are **not** used for atom derivation — only their own line items are emitted.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_neals_builders.py
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

    def test_invoices_attach_to_jobs(self):
        build.build_invoices(self.c)
        job_pks = {f['pk'] for f in self._models('jobs.job')}
        for inv in self._models('invoicing.invoice'):
            self.assertIn(inv['fields']['job'], job_pks)
        # line numbers contiguous per invoice
        by_inv = {}
        for li in self._models('invoicing.invoicelineitem'):
            by_inv.setdefault(li['fields']['invoice'], []).append(
                li['fields']['line_number'])
        for nums in by_inv.values():
            self.assertEqual(sorted(nums), list(range(1, len(nums) + 1)))
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_neals_builders.InvoiceBuilderTest -v 2`
Expected: FAIL — `build` has no `build_invoices`.

- [ ] **Step 3: Implement `build_invoices`**

1. Index Invoice container rows by their `Projects`/`Project` column; keep only invoices whose project resolves to a job in `c.job_map` (match via the project name's estimate-number prefix → `base_ref`).
2. For each kept invoice container emit `invoicing.invoice` (fields: `job`, `invoice_number` = `Reference` or generated `INV-{year}-{counter:04d}`, `status` = mapped from `Status` to one of `draft/open/cancelled/superseded/partly-paid/paid/defaulted` (`Paid→paid, Sent/Open→open, Draft→draft`, default `open`), `created_date` = `format_date(Date)`, `sent_date=None`, `closed_date` = `format_date(Paid Date)` if paid else `None`, `qbo_id=None`, `qbo_payment_status=None`, `qbo_amount_paid=None`).
3. For each line-item row (skip `Comment`) emit `invoicing.invoicelineitem` (fields: `invoice`, `price_list_item=None`, `line_number` sequential per invoice from 1, `qty` = `parse_decimal(Quantity)`, `units='none'`, `description` = `Description`, `price` = `parse_decimal(Price)`, `accounting_category=None`, `taxable_override=None`, `tax_rate_override=None`).
4. Stash invoice totals (Σ qty×price) per job on `c.invoice_totals[base_ref]` for the reconcile invoiced-work rule.

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_neals_builders.InvoiceBuilderTest -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/build.py tests/test_neals_builders.py
git commit -m "feat(nealsdata): invoice + invoice line-item builder"
```

---

### Task 12: Bill + PurchaseOrder builder

**Files:**
- Modify: `nealsdata/converter/build.py`
- Test: `tests/test_neals_builders.py`

Each Bill produces a `Bill` **and** a `PurchaseOrder` (FreeAgent has no PO concept), with the Bill's `purchase_order` FK pointing at it. Bills link to a Job via the `[14]Project` column and to a vendor Business via `[0]Contact Organisation`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_neals_builders.py
class BillBuilderTest(unittest.TestCase):
    def setUp(self):
        self.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=20)
        self.c.loader.load()
        self.c.csv_cards = self.c.csv_loader.load()
        self.c.spine = self.c.select_spine()
        build.build_contacts_and_businesses(self.c)
        build.build_jobs(self.c)

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def test_each_bill_has_a_purchase_order(self):
        build.build_bills_and_pos(self.c)
        bills = self._models('purchasing.bill')
        po_pks = {f['pk'] for f in self._models('purchasing.purchaseorder')}
        for b in bills:
            self.assertIn(b['fields']['purchase_order'], po_pks)
            self.assertTrue(b['fields']['vendor_invoice_number'])
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_neals_builders.BillBuilderTest -v 2`
Expected: FAIL — `build` has no `build_bills_and_pos`.

- [ ] **Step 3: Implement `build_bills_and_pos`**

1. Index Bill container rows; keep only bills whose `[14]Project` resolves to a job in `c.job_map`.
2. Resolve the vendor `business` pk from `c.org_map` using `Contact Organisation`; if the org has no business yet, build one on demand (reuse the Task 7 synthesize path — extract it into a helper `ensure_business(c, org, name)`).
3. For each kept bill: emit a `purchasing.purchaseorder` first (fields: `business` = vendor business pk, `contact=None`, `po_number` generated `PO-{year}-{counter:04d}`, `status='received_in_full'`, `created_date` = `format_date(Date)`, `issued_date` = same, `received_date` = same, `cancel_date=None`), then a `purchasing.bill` (fields: `business` = vendor business pk, `contact=None`, `vendor_invoice_number` = `Reference` or `f'VINV-{pk}'`, `purchase_order` = the PO pk, `status` = `paid_in_full` if the bill is fully paid else `received`, `created_date`, `received_date` = `format_date(Date)`, `paid_date` = `format_date(Date)` if paid else `None`, `cancelled_date=None`, `due_date` = `format_date(Due Date)`, `qbo_id=None`, `qbo_payment_status=None`).
4. For each line-item row (skip `Comment`) emit a `purchasing.purchaseorderlineitem` and a matching `purchasing.billlineitem` (fields for both: `task=None`, `price_list_item=None`, `line_number` sequential from 1, `qty` = `parse_decimal(Quantity)`, `units='none'`, `description` = `Description`, `price` = `parse_decimal(Subtotal)`, `accounting_category=None`, `taxable_override=None`, `tax_rate_override=None`; PO line also `qty_received` = qty, `qty_cancelled='0'`, `received_by=None`, `received_date=None`, `receipt_note=''`; bill line also `bill` = bill pk; PO line also `purchase_order` = PO pk).

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_neals_builders.BillBuilderTest -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/build.py tests/test_neals_builders.py
git commit -m "feat(nealsdata): bill + purchase order builder"
```

---

### Task 13: Reconciliation

**Files:**
- Create: `nealsdata/converter/reconcile.py`
- Test: `tests/test_neals_builders.py`

Reconcile mutates already-emitted fixtures (look them up in `c.fixture_data` by model+pk). Applies status/date rules from design §10.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_neals_builders.py
from nealsdata.converter import reconcile


class ReconcileTest(unittest.TestCase):
    def setUp(self):
        self.c = NealsDataConverter(XLSX, CSV, output_path='/tmp/x.json', limit=20)
        self.c.loader.load()
        self.c.csv_cards = self.c.csv_loader.load()
        self.c.spine = self.c.select_spine()
        build.build_contacts_and_businesses(self.c)
        build.build_jobs(self.c)
        build.build_estimates(self.c)
        build.derive_atoms(self.c)
        build.build_invoices(self.c)
        build.build_bills_and_pos(self.c)

    def _models(self, m):
        return [f for f in self.c.fixture_data if f['model'] == m]

    def test_expired_estimates_and_versioning(self):
        reconcile.reconcile(self.c)
        ests = self._models('estimates.estimate')
        # no estimate is left 'open' with a created_date older than 30 days
        # (those become 'expired')
        for e in ests:
            self.assertIn(e['fields']['status'],
                          ('draft', 'open', 'accepted', 'rejected',
                           'superseded', 'expired'))
        # superseded estimates have a closed_date
        for e in ests:
            if e['fields']['status'] == 'superseded':
                self.assertIsNotNone(e['fields']['closed_date'])

    def test_completed_jobs_have_completed_date_and_complete_tasks(self):
        reconcile.reconcile(self.c)
        jobs = {j['pk']: j for j in self._models('jobs.job')}
        for j in jobs.values():
            if j['fields']['status'] == 'completed':
                self.assertIsNotNone(j['fields']['completed_date'])
        for t in self._models('jobs.task'):
            job = jobs[t['fields']['job']]
            if job['fields']['status'] == 'completed':
                self.assertEqual(t['fields']['status'], 'complete')
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_neals_builders.ReconcileTest -v 2`
Expected: FAIL — `No module named 'nealsdata.converter.reconcile'`.

- [ ] **Step 3: Implement `reconcile.reconcile(c)`**

Implement these passes in order, each iterating `c.fixture_data`:

1. **Estimate version chains** — for each `base_ref` with multiple estimate versions: sort by `version`; mark all but the highest `superseded` and set their `closed_date` to their `created_date`; set each non-first version's `parent` to the previous version's pk.
2. **Estimate expiry** — any estimate `open` with `created_date` more than 30 days before today → `expired`, `closed_date` = `created_date` + 30 days. If that estimate is the latest version on its job, set the job `status` to `rejected`.
3. **Estimate dates** — `open`/`accepted`/`rejected`/`expired`/`superseded` estimates get `sent_date` = `created_date`; `accepted`/`rejected`/`expired`/`superseded` get `closed_date` (if not already set) = `created_date`; `open`/later get `expiration_date` = `created_date` + 30 days.
4. **Job dates** — `start_date`: explicit Project `Starts On` if present, else the v1 estimate `created_date` for `approved` jobs, else `created_date` for `completed` jobs with no estimates. `completed_date`: from the CSV `Archived at` if the job is terminal (`completed`/`cancelled`/`rejected`); else for `completed` jobs fall back to the Project `Updated Date`.
5. **Task status** — tasks on a `completed` job → `complete`; tasks on `cancelled`/`rejected` jobs → `cancelled`; otherwise `pending`.
6. **Invoiced-work rule** — for any job with an estimate and a non-draft invoice whose totals are within 10% (`abs(est_total - inv_total) <= 0.10 * max(est_total, inv_total)`), set every task on that job to `complete`.
7. **Document-number counters** — bump the `core.configuration` counters (`job_counter` etc.) to the number of objects generated, so post-import numbering continues cleanly.

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_neals_builders.ReconcileTest -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/reconcile.py tests/test_neals_builders.py
git commit -m "feat(nealsdata): cross-model reconciliation pass"
```

---

### Task 14: Wire `convert()` + JSON output

**Files:**
- Modify: `nealsdata/converter/orchestrator.py`
- Test: `tests/test_neals_builders.py`

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_neals_builders.py
import json, os, tempfile


class ConvertEndToEndTest(unittest.TestCase):
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
        # no obsolete models
        self.assertNotIn('jobs.workorder', models)
        self.assertNotIn('jobs.blep', models)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_neals_builders.ConvertEndToEndTest -v 2`
Expected: FAIL — `convert()` raises `NotImplementedError`.

- [ ] **Step 3: Implement `convert()`**

Replace the `NotImplementedError` stub with the full phase sequence:

```python
def convert(self):
    from nealsdata.converter import build, reconcile
    self.loader.load()
    self.csv_cards = self.csv_loader.load()
    self.spine = self.select_spine()
    build.build_users(self)
    build.build_configuration(self)
    build.build_accounting_categories(self)
    build.build_price_list_items(self)
    build.build_contacts_and_businesses(self)
    build.build_jobs(self)
    build.build_estimates(self)
    build.derive_atoms(self)
    build.build_invoices(self)
    build.build_bills_and_pos(self)
    reconcile.reconcile(self)
    self._write_json()
    if self.verbose:
        self._print_summary()

def _write_json(self):
    with open(self.output_path, 'w') as f:
        json.dump(self.fixture_data, f, indent=2, default=str)

def _print_summary(self):
    from collections import Counter
    counts = Counter(row['model'] for row in self.fixture_data)
    for model, n in sorted(counts.items()):
        print(f'  {n:6} {model}')
```

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_neals_builders.ConvertEndToEndTest -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/orchestrator.py tests/test_neals_builders.py
git commit -m "feat(nealsdata): wire conversion phases + JSON output"
```

---

### Task 15: Loadability integration test + full run

**Files:**
- Create: `tests/test_neals_fixture.py`
- Delete: `nealsdata/convert_neals_data.py.bak`

This is the verification that the fixture is actually loadable. `call_command('loaddata', ...)` inside a Django `TestCase` runs against the **test** database — never the dev DB.

- [ ] **Step 1: Generate the fixture from the real data**

Run: `python nealsdata/convert_neals_data.py nealsdata/datasets/company-export-220382-2026-05-18-02-19.xlsx --verbose`
Expected: writes `nealsdata/datasets/converted.json` and prints a per-model summary with `jobs.job` ≈ 100.

- [ ] **Step 2: Write the loadability test**

```python
# tests/test_neals_fixture.py
from django.test import TestCase
from django.core.management import call_command
from apps.jobs.models import Job, Task, RateScheme
from apps.estimates.models import Estimate
from apps.deliverables.models import Deliverable

FIXTURE = 'nealsdata/datasets/converted.json'


class NealsFixtureLoadTest(TestCase):
    def test_fixture_loads_into_test_db(self):
        # Loads into the test DB created by the test runner; raises on any
        # FK / validation / schema mismatch.
        call_command('loaddata', FIXTURE, verbosity=0)
        self.assertGreater(Job.objects.count(), 0)
        # every Task has a rate_scheme (NOT NULL FK)
        self.assertEqual(Task.objects.filter(rate_scheme__isnull=True).count(), 0)
        # every Job with a non-draft estimate has a deliverable
        for est in Estimate.objects.exclude(status='draft'):
            self.assertTrue(
                Deliverable.objects.filter(job=est.job).exists(),
                f'Job {est.job_id} has a non-draft estimate but no Deliverable',
            )
```

- [ ] **Step 3: Run the loadability test**

Run: `python manage.py test tests.test_neals_fixture -v 2`
Expected: PASS. If `loaddata` fails, the error names the offending model/field — fix the relevant builder, regenerate the fixture (Step 1), and re-run.

- [ ] **Step 4: Run the whole converter test suite**

Run: `python manage.py test tests.test_neals_parsing tests.test_neals_loaders tests.test_neals_builders tests.test_neals_fixture -v 2`
Expected: all PASS.

- [ ] **Step 5: Remove the backup and commit**

```bash
rm nealsdata/convert_neals_data.py.bak
git add nealsdata/ tests/test_neals_fixture.py
git commit -m "test(nealsdata): fixture loadability test; drop old script backup"
```

---

## Self-review notes

- **Spec coverage:** §3 file structure → Task 1; §5 CSV spine → Tasks 2,5,8; §6 Comment filter → Task 9; §7 atom derivation → Task 10; §8 RateScheme → Tasks 4,10; §9 filtering/trimming → Tasks 5,7,11,12; §10 reconciliation → Task 13; §11 output+testing → Tasks 14,15. All covered.
- **Out-of-scope items** (EstWorksheet, PlanTask, Earmark, Shipment, HistoryEntry, Blep, Expenses sheet) are intentionally absent from every task.
- **Heuristic refinement:** the material keyword list (Task 4) and the deliverable-candidate rule (Task 10) are expected to need tuning once the user reviews the loaded data — design §13. Treat post-load review feedback as a follow-up pass, not a plan failure.
- **Dev-DB safety:** no task runs `migrate`, `loaddata`, or `shell` against the dev DB. The only `loaddata` (Task 15) runs inside a `TestCase` against the test DB.

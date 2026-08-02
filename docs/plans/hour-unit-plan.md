# Hour as a First-Class Unit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `hour` a privileged, undeletable, singular unit; pin `elapsed_time` rate schemes to it; unify the task estimate UI around one hours input; fix the invoice wizard's solo-elapsed line shape; consolidate duplicated time conversions.

**Architecture:** Sentinel string `HOUR_UNIT = 'hour'` in `apps/core/units.py` (no structured-units rework). Enforcement layering: model `clean()` holds the elapsed⇒hour invariant, serializers/import paths auto-set it, the SPA hides the choice. A core data migration singularizes all stored unit strings. Spec: `docs/plans/hour-unit-spec.md`.

**Tech Stack:** Django 5.2 + DRF, MySQL, Svelte 5 (runes) + Vitest, Playwright e2e.

## Global Constraints

- **Branch:** RM creates the working branch before implementation starts. If no branch is set up, STOP and ask RM — never create or choose one (global CLAUDE.md rule). Commit to that branch only; never merge/push/PR.
- **NEVER write to the dev database.** No `migrate`, no `shell` ORM writes, no `loaddata`. Tests only (`manage.py test` builds its own DB). Read-only SQL diagnostics are OK.
- **Test commands:** always `python manage.py test <module> --noinput`. Never run two Django test runs concurrently (hook-enforced). Never judge pass/fail via a piped exit code — read the `OK` / `FAILED` summary line.
- Targeted test modules per task; ONE full-suite run at final verification, **without `--keepdb`** (migrations change in this plan).
- **`fixtures/large_datasets/nealsmall.json` is RM-managed — never edit or regenerate it.**
- Converter changes MUST be verified with `python manage.py test tests.test_neals_builders --noinput`.
- Error responses follow the two-shape contract (`{'detail': ...}` / `{field: [...]}`); frontend errors route through `triageError`.
- All user-visible text says "timeslip", never "blep"; unit strings are singular everywhere after this plan.
- Commit after each task; end commit messages with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

**Files-at-a-glance (who owns what):**
- `apps/core/units.py` — canon list + `HOUR_UNIT` (Task 1)
- `apps/core/timeutils.py` — `timedelta_to_hours` (Task 2)
- new core data migration — singularize + pin (Task 4)
- `apps/jobs/models.py` — clean() invariant, `get_actual_qty` via helper (Tasks 2, 5)
- `apps/api/rate_schemes/serializers.py`, `apps/qbo/import_services.py` — auto-set (Task 5)
- `apps/api/templates_config/views.py`, `UnitsManager.svelte` — undeletable hour (Task 6)
- `apps/invoicing/services.py` — solo-elapsed line shape (Task 7)
- `apps/jobs/services.py`, `apps/estimates/models.py` — pair-fill (Task 8)
- `frontend/src/lib/format.js`, `taskTotals.js`, `WorkItemForm.svelte` — parser consolidation + single input (Tasks 9, 10)
- `RateSchemeManager.svelte`, `SchemesImportPanel.svelte`, `TaskDetailPage.svelte`, `TaskRow.svelte` — display/lock (Task 11)
- fixtures + tests sweep (Task 3), converter (Task 12), e2e (Task 13), docs (Task 14), verification (Task 15)

---

### Task 1: Singular canon + `HOUR_UNIT` constant

**Files:**
- Modify: `apps/core/units.py`
- Test: `tests/test_units_api.py`

**Interfaces:**
- Produces: `apps.core.units.HOUR_UNIT == 'hour'`; `DEFAULT_UNITS` singular. Every later task imports `HOUR_UNIT` instead of writing `'hour'` literals (backend).

- [ ] **Step 1: Write the failing test** — append to `tests/test_units_api.py`:

```python
class UnitsCanonTest(BaseTestCase):
    def test_default_units_are_singular_and_contain_hour(self):
        from apps.core.units import DEFAULT_UNITS, HOUR_UNIT
        self.assertEqual(HOUR_UNIT, 'hour')
        self.assertIn(HOUR_UNIT, DEFAULT_UNITS)
        for legacy in ('hours', 'sheets', 'lbs'):
            self.assertNotIn(legacy, DEFAULT_UNITS)
```

- [ ] **Step 2: Run it** — `python manage.py test tests.test_units_api --noinput` — expect FAIL (`ImportError: HOUR_UNIT` / `'hours' in DEFAULT_UNITS`).

- [ ] **Step 3: Implement** in `apps/core/units.py`:

```python
DEFAULT_UNITS = [
    "none", "ea", "hour", "min", "sheet", "sq ft", "ft", "yd", "m",
    "lb", "kg", "gal", "qt", "L", "bd ft", "ln ft",
]

# The unit time-based billing and scheduling are denominated in. Present in
# every units_list (the settings endpoint refuses to remove it); elapsed_time
# RateSchemes are pinned to it.
HOUR_UNIT = "hour"
```

Also delete the dead `UnitsFieldMixin` class (zero importers) and the now-unused `from django import forms` import; `units_choices()` stays (still used by `UnitsField`).

- [ ] **Step 4: Fix the plural literals inside `tests/test_units_api.py` itself** — `['none', 'hours', 'ea', 'custom_unit']` etc. become `['none', 'hour', 'ea', 'custom_unit']`, `['hour', 'ea']`, `['none', 'hour', 'hour']`, `['none', 'hour']`. (The hour-required rule is Task 6 — these lists must already contain `hour` so Task 6 doesn't have to re-touch them.)

- [ ] **Step 5: Run** `python manage.py test tests.test_units_api --noinput` — expect OK.
  (Other modules still reference `'hours'`; they get swept in Task 3 — do not run the full suite here.)

- [ ] **Step 6: Commit** — `feat: singular units canon + HOUR_UNIT constant`

---

### Task 2: One backend seconds→hours conversion

**Files:**
- Modify: `apps/core/timeutils.py`, `apps/jobs/models.py:536-551`, `apps/jobs/financials.py:69-87`, `apps/jobs/overview.py:34-35`, `apps/api/tasks/serializers.py:167-172`
- Test: `tests/test_timeutils.py` (create), plus a drift test in `tests/test_api_tasks.py` (or the module that already tests `TaskSerializer` — grep `get_actual_hours`/`actual_hours` under `tests/` and put it beside its neighbors)

**Interfaces:**
- Produces: `apps.core.timeutils.timedelta_to_hours(td) -> Decimal | None` — unquantized; callers quantize.

- [ ] **Step 1: Write failing tests** — `tests/test_timeutils.py`:

```python
from datetime import timedelta
from decimal import Decimal
from django.test import SimpleTestCase
from apps.core.timeutils import timedelta_to_hours

class TimedeltaToHoursTest(SimpleTestCase):
    def test_converts_and_is_none_safe(self):
        self.assertIsNone(timedelta_to_hours(None))
        self.assertEqual(timedelta_to_hours(timedelta(hours=1, minutes=30)),
                         Decimal('1.5'))
        self.assertEqual(
            timedelta_to_hours(timedelta(minutes=50)).quantize(Decimal('0.01')),
            Decimal('0.83'))
```

- [ ] **Step 2: Run** `python manage.py test tests.test_timeutils --noinput` — FAIL (no such function).

- [ ] **Step 3: Implement** in `apps/core/timeutils.py`:

```python
from decimal import Decimal

SECONDS_PER_HOUR = Decimal('3600')


def timedelta_to_hours(td):
    """timedelta → Decimal hours, unquantized (callers pick their rounding).

    None-safe: None → None. The single seconds/3600 conversion — billing
    (RateScheme.get_actual_qty), cost (financials), progress (overview) and
    the task serializer all route here so they can't drift.
    """
    if td is None:
        return None
    return Decimal(str(td.total_seconds())) / SECONDS_PER_HOUR
```

- [ ] **Step 4: Convert the four call sites** (each keeps its own quantization):

`apps/jobs/models.py` `get_actual_qty` ELAPSED_TIME branch:

```python
        if self.algorithm == self.ELAPSED_TIME:
            from datetime import timedelta
            from apps.core.timeutils import timedelta_to_hours
            total = sum(
                (b.elapsed for b in task.blep_set.all() if b.elapsed is not None),
                timedelta(),
            )
            # Quantize to 2 places: a raw seconds/3600 division is
            # non-terminating (~28 digits) and overflows the line item qty
            # field (max_digits=10) when carried into the invoice wizard.
            return timedelta_to_hours(total).quantize(Decimal('0.01'))
```

`apps/jobs/financials.py` — delete the local `SECONDS_PER_HOUR` (line 19), `from apps.core.timeutils import timedelta_to_hours`, and in `_blep_hours` replace the division line with `total_hours += timedelta_to_hours(elapsed)`.

`apps/jobs/overview.py` — delete local `SECONDS_PER_HOUR` (line 21; keep `HOURS_QUANT`), import the helper, and `_duration_hours` becomes `return timedelta_to_hours(total)`.

`apps/api/tasks/serializers.py` `get_actual_hours` (this is the float drift risk — it must produce exactly `get_actual_qty`'s number):

```python
    def get_actual_hours(self, obj):
        from datetime import timedelta
        from decimal import Decimal
        from apps.core.timeutils import timedelta_to_hours
        total = sum(
            (b.elapsed for b in obj.blep_set.all() if b.elapsed is not None),
            timedelta(),
        )
        # float at the JSON boundary; the arithmetic is the shared Decimal path
        return float(timedelta_to_hours(total).quantize(Decimal('0.01')))
```

- [ ] **Step 5: Add the drift test** next to the existing TaskSerializer tests:

```python
    def test_actual_hours_matches_billing_qty(self):
        # 50 min of bleps: serializer hours must equal get_actual_qty exactly
        # (they were two independent conversions before; now one).
        ...seed one task on an elapsed_time scheme + one 50-minute blep...
        ser_val = Decimal(str(TaskSerializer(task).data['actual_hours']))
        self.assertEqual(ser_val, task.rate_scheme.get_actual_qty(task))
```

(Adopt the module's existing setUp seeding idiom for the task/blep; bleps floor to the minute, so use whole-minute times.)

- [ ] **Step 6: Run** `python manage.py test tests.test_timeutils tests.<serializer module> tests.test_invoice_wizard_service --noinput` — expect OK (conversion is value-identical).

- [ ] **Step 7: Commit** — `refactor: single timedelta_to_hours conversion`

---

### Task 3: Fixture + test-literal singularization sweep

**Files:**
- Modify: `fixtures/core_base_data.json`, `fixtures/unit_test_data.json`, `fixtures/contacts_base_data.json`, `fixtures/purchasing_data.json`, `fixtures/invoicing_data.json`, `fixtures/jobs_basic_data.json`, `fixtures/contact_data/01_base_contacts.json`, `fixtures/large_datasets/nealseed.json`, `fixtures/staging/seed.json`, `fixtures/playwright/seed.json`, `fixtures/playwright/rebased.json`
- Modify: every test module asserting `'hours'` (`tests/test_invoice_wizard_service.py`, `tests/test_invoice_line_from_service.py`, plus whatever grep finds)
- **Do NOT touch `fixtures/large_datasets/nealsmall.json`.**

- [ ] **Step 1: Write the sweep script** to the session scratchpad (NOT the repo), e.g. `<scratchpad>/singularize_fixtures.py`:

```python
import json, pathlib, re

RENAMES = {'hours': 'hour', 'sheets': 'sheet', 'lbs': 'lb', 'pcs': 'pc'}
FILES = [
    'fixtures/core_base_data.json', 'fixtures/unit_test_data.json',
    'fixtures/contacts_base_data.json', 'fixtures/purchasing_data.json',
    'fixtures/invoicing_data.json', 'fixtures/jobs_basic_data.json',
    'fixtures/contact_data/01_base_contacts.json',
    'fixtures/large_datasets/nealseed.json', 'fixtures/staging/seed.json',
    'fixtures/playwright/seed.json', 'fixtures/playwright/rebased.json',
]

for f in FILES:
    p = pathlib.Path(f)
    raw = p.read_text()
    # preserve each file's existing indent (2 vs 4 spaces)
    m = re.search(r'\n( +)"', raw)
    indent = len(m.group(1)) if m else 2
    data = json.loads(raw)
    for rec in data:
        fields = rec.get('fields', {})
        if (rec.get('model') == 'core.configuration'
                and rec.get('pk') == 'units_list'):
            units = json.loads(fields['value'])
            fields['value'] = json.dumps([RENAMES.get(u, u) for u in units])
        for key in ('units', 'unit_label'):
            if fields.get(key) in RENAMES:
                fields[key] = RENAMES[fields[key]]
    p.write_text(json.dumps(data, indent=indent) + '\n')
    print('done', f)
```

- [ ] **Step 2: Run it** from the repo root: `python <scratchpad>/singularize_fixtures.py`. Then verify: `grep -rn '"units": "hours"\|"unit_label": "hours"\|\\\\"hours\\\\"' fixtures/ | grep -v nealsmall` → no output. Also eyeball `git diff --stat` — only the listed files, and the diff should be unit strings only (if the whole file reflowed, the indent detection guessed wrong — fix and re-run).

- [ ] **Step 3: Sweep test literals**: `grep -rln "'hours'" tests/` → in each hit, `'hours'` → `'hour'` where it's a unit value (`unit_label=`, `units=`, assertions on those fields). Update the `tests/test_invoice_wizard_service.py` comment at ~L591 too.

- [ ] **Step 4: Run the touched modules**: `python manage.py test tests.test_invoice_wizard_service tests.test_invoice_line_from_service tests.test_units_api --noinput` — expect OK.

- [ ] **Step 5: Commit** — `chore: singularize unit strings in fixtures and tests`

---

### Task 4: Data migration — singularize + pin elapsed schemes

**Files:**
- Create: `apps/core/migrations/00XX_singular_units.py` (via `python manage.py makemigrations core --empty --name singular_units`; creating migrations is allowed, running `migrate` is NOT — RM applies it)

- [ ] **Step 1: Author the migration**:

```python
import json
from django.db import migrations

UNIT_RENAMES = {'hours': 'hour', 'sheets': 'sheet', 'lbs': 'lb', 'pcs': 'pc'}

# (app_label, model, field) for every stored unit string.
UNIT_FIELDS = [
    ('estimates', 'EstimateLineItem', 'units'),
    ('estimates', 'ChangeOrderLineItem', 'units'),
    ('purchasing', 'PurchaseOrderLineItem', 'units'),
    ('purchasing', 'BillLineItem', 'units'),      # schema stub; rows may exist
    ('invoicing', 'InvoiceLineItem', 'units'),
    ('inventory', 'InventoryItem', 'units'),
    ('inventory', 'Material', 'units'),
    ('deliverables', 'Deliverable', 'units'),
    ('deliverables', 'DeliverableSnapshot', 'units'),
    ('jobs', 'RateScheme', 'unit_label'),
]


def forwards(apps, schema_editor):
    Configuration = apps.get_model('core', 'Configuration')
    try:
        cfg = Configuration.objects.get(key='units_list')
    except Configuration.DoesNotExist:
        cfg = None
    if cfg is not None:
        try:
            units = json.loads(cfg.value)
        except ValueError:
            units = None
        if isinstance(units, list):
            units = [UNIT_RENAMES.get(u, u) for u in units]
            if 'hour' not in units:
                units.append('hour')
            cfg.value = json.dumps(units)
            cfg.save(update_fields=['value'])

    # QuerySet.update() is correct here despite the house rule: historical
    # models carry no custom save(), and none of these fields are
    # save-normalized.
    for app_label, model_name, field in UNIT_FIELDS:
        Model = apps.get_model(app_label, model_name)
        for old, new in UNIT_RENAMES.items():
            Model.objects.filter(**{field: old}).update(**{field: new})

    # elapsed_time schemes were always billed in hours whatever their label
    # said; correct the label (fixes a lie, not a price).
    RateScheme = apps.get_model('jobs', 'RateScheme')
    RateScheme.objects.filter(algorithm='elapsed_time') \
        .exclude(unit_label='hour').update(unit_label='hour')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '00XX_<previous>'),
        # + the CURRENT latest migration of each app in UNIT_FIELDS —
        # check with:  ls apps/{estimates,purchasing,invoicing,inventory,deliverables,jobs}/migrations | sort | tail
        ('estimates', '00XX_...'), ('purchasing', '00XX_...'),
        ('invoicing', '00XX_...'), ('inventory', '00XX_...'),
        ('deliverables', '00XX_...'), ('jobs', '00XX_...'),
    ]
    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
```

- [ ] **Step 2: Prove the migration chain builds a DB from scratch** (this also exercises the seed path, which now emits the singular list): `python manage.py test tests.test_units_api --noinput` (no `--keepdb` — a fresh test DB runs every migration). Expect OK.

- [ ] **Step 3: Commit** — `feat: migration singularizing stored units, pinning elapsed schemes to hour`

---

### Task 5: elapsed_time ⇒ unit_label 'hour' (model + serializer + QBO import)

**Files:**
- Modify: `apps/jobs/models.py` (`RateScheme.clean`, ~L479), `apps/api/rate_schemes/serializers.py:35-59`, `apps/qbo/import_services.py` (`commit_schemes`, ~L688)
- Test: `tests/test_rate_schemes.py` or wherever RateScheme clean/serializer tests live (grep `unit_label` under `tests/`); QBO import tests module (grep `commit_schemes` under `tests/`)

**Interfaces:**
- Consumes: `HOUR_UNIT` (Task 1).
- Produces: the invariant later tasks rely on — an elapsed scheme's `unit_label` is always `'hour'`.

- [ ] **Step 1: Write failing tests** (in the module that already tests RateScheme validation):

```python
    def test_elapsed_scheme_rejects_non_hour_unit(self):
        scheme = ...existing factory/setup for a saved, unreferenced elapsed scheme...
        scheme.unit_label = 'ea'
        with self.assertRaises(ValidationError) as ctx:
            scheme.full_clean()
        self.assertIn('unit_label', ctx.exception.message_dict)

    def test_serializer_forces_hour_on_elapsed(self):
        data = {'name': 'Shop time', 'algorithm': 'elapsed_time',
                'rate': '90.00', 'unit_label': 'gal',
                'accounting_category': self.category.pk}
        ser = RateSchemeSerializer(data=data)
        self.assertTrue(ser.is_valid(), ser.errors)
        self.assertEqual(ser.validated_data['unit_label'], 'hour')
```

And in the QBO import tests: a `commit_schemes` row with `algorithm='elapsed_time', unit_label='ea'` creates a scheme with `unit_label == 'hour'`.

- [ ] **Step 2: Run them** — expect FAIL.

- [ ] **Step 3: Implement.**

`apps/jobs/models.py` — add to `RateScheme.clean()` after the negative-rate check (import `HOUR_UNIT` at module top: `from apps.core.units import HOUR_UNIT`):

```python
        if self.algorithm == self.ELAPSED_TIME and self.unit_label != HOUR_UNIT:
            raise ValidationError({
                'unit_label': 'Time-based schemes are billed in hours; '
                              f'unit must be "{HOUR_UNIT}".',
            })
```

(Note: `RateScheme.save()` only runs `full_clean()` on updates, by design — creates are guarded by the write surfaces below, same as today's other clean() rules.)

`apps/api/rate_schemes/serializers.py` `validate()` — insert an elapsed branch above the percentage branch (import `HOUR_UNIT` alongside `get_units_list`):

```python
        if algorithm == RateScheme.ELAPSED_TIME:
            # Time-based schemes are always denominated in hours; the UI
            # hides the picker and any submitted value is overridden.
            attrs['unit_label'] = HOUR_UNIT
        elif algorithm == RateScheme.PERCENTAGE:
            ...existing...
```

`apps/qbo/import_services.py` `commit_schemes` — at the top of the `for row in rows:` loop inside the transaction (~L689), before `fields` is built:

```python
                if row['algorithm'] == RateScheme.ELAPSED_TIME:
                    row['unit_label'] = HOUR_UNIT
```

(import `HOUR_UNIT` at module top; this covers both the update/supersede path and the `RateScheme.objects.create` path).

- [ ] **Step 4: Run** the touched test modules `--noinput` — expect OK.

- [ ] **Step 5: Commit** — `feat: pin elapsed_time rate schemes to unit 'hour'`

---

### Task 6: 'hour' is undeletable in the units config

**Files:**
- Modify: `apps/api/templates_config/views.py:308-321`, `frontend/src/components/UnitsManager.svelte`
- Test: `tests/test_units_api.py`, `frontend/tests/components/UnitsManager.test.js`

- [ ] **Step 1: Backend failing test** (`tests/test_units_api.py`, `UnitsUpdateEndpointTest`):

```python
    def test_patch_requires_hour_present(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.patch('/api/settings/units/', ['none', 'ea'], format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('hour', response.data['detail'])
```

- [ ] **Step 2: Run** `python manage.py test tests.test_units_api --noinput` — FAIL (200).

- [ ] **Step 3: Implement** in `units_view` after the duplicates check (import `HOUR_UNIT` from `apps.core.units`):

```python
    if HOUR_UNIT not in units:
        return Response(
            {'detail': f'"{HOUR_UNIT}" must be included — time-based '
                       'billing and scheduling depend on it.'},
            status=400)
```

- [ ] **Step 4: Run** — OK. Then frontend, `UnitsManager.svelte`:

```js
  const SPECIAL_UNITS = ['none', 'hour'];  // undeletable; mirror of backend rule

  function removeUnit(index) {
    if (SPECIAL_UNITS.includes(units[index])) return;
    units = units.filter((_, i) => i !== index);
    saveUnits();
  }
```

Template: `{#if unit !== 'none'}` around the Remove button becomes `{#if !SPECIAL_UNITS.includes(unit)}`. Intro `<p>` gains: `"none" and "hour" are built-in and can't be removed — "hour" is the unit time-based billing and scheduling use.` While in `saveUnits()`, fix the retired-shape error read: `e.data?.error || e.message` → `e.data?.detail || e.message`.

- [ ] **Step 5: Vitest** — extend `frontend/tests/components/UnitsManager.test.js` following its existing render/mocking pattern:

```js
  it('offers no Remove button for none or hour', async () => {
    // mock GET /api/settings/units/ → ['none', 'ea', 'hour']
    // render, wait for rows
    // rows for 'none' and 'hour' have no Remove button; 'ea' has one
  });
```

(Write it as real code against the file's established mock helpers — read the existing tests in that file first.)

- [ ] **Step 6: Run** `cd frontend && npm run test:run` — expect OK.

- [ ] **Step 7: Commit** — `feat: hour is undeletable in units settings`

---

### Task 7: Invoice wizard — solo elapsed line copies over hours × rate

**Files:**
- Modify: `apps/invoicing/services.py:1137-1146`
- Test: `tests/test_invoice_wizard_service.py`

- [ ] **Step 1: Flip the existing assertions first (TDD via changed expectations).** In `tests/test_invoice_wizard_service.py`, the solo-elapsed tests (~L397, 428, 591, 616 pre-sweep) assert `qty=1, price=total`. Rewrite them to the new shape — e.g. where a task has 2h of bleps at rate 25.00:

```python
        self.assertEqual(line_item.qty, Decimal('2.00'))
        self.assertEqual(line_item.price, Decimal('25.00'))
        self.assertEqual(line_item.units, 'hour')
```

Add one new test: solo elapsed line equals the shape the same task produces via a same-scheme two-task bundle (create two tasks on one scheme, bundle them, compare units/price; qty = sum).

- [ ] **Step 2: Run** `python manage.py test tests.test_invoice_wizard_service --noinput` — FAIL (qty is 1).

- [ ] **Step 3: Implement** — replace `InvoiceWizardService._task_qty_and_price`:

```python
    @classmethod
    def _task_qty_and_price(cls, task, total_price):
        # Both algorithms carry a real per-unit qty × rate: entered_qty from
        # the worker-entered quantity, elapsed_time from blep hours. Either
        # way qty × effective_rate == the computed amount exactly, and it
        # matches what _uniform_scheme_bundle produces for the same task.
        if task.rate_scheme_id:
            scheme = task.rate_scheme
            return scheme.get_actual_qty(task), task.effective_rate()
        return Decimal('1'), total_price
```

- [ ] **Step 4: Run** the module `--noinput` — OK. Also run `python manage.py test tests.test_invoice_line_from_service --noinput` (it builds solo lines too).

- [ ] **Step 5: Commit** — `fix: solo elapsed-time invoice lines carry hours × rate`

---

### Task 8: Backend pair-fill — est_qty ⟷ est_worker_time for hour-unit schemes

**Files:**
- Modify: `apps/jobs/services.py` (`create_direct` ~L1011, `update_task` ~L1072, `assign` ~L1198), `apps/estimates/models.py` (`generate_task` ~L481)
- Test: `tests/test_task_service.py` (or the module holding create_direct/update_task tests — grep), acceptance tests module (grep `on_accept` under `tests/`)

**Interfaces:**
- Produces: `hours_pair_fill(scheme, est_qty, est_worker_time) -> (est_qty, est_worker_time)` module-level in `apps/jobs/services.py`.

- [ ] **Step 1: Write failing tests**:

```python
    def test_hour_scheme_create_derives_worker_time_from_qty(self):
        task = TaskService.create_direct(
            self.job, 'Cutting', rate_scheme_id=self.hour_scheme.pk,
            est_qty=Decimal('2.5'))
        self.assertEqual(task.est_worker_time, timedelta(hours=2.5))

    def test_hour_scheme_create_derives_qty_from_worker_time(self):
        task = TaskService.create_direct(
            self.job, 'Cutting', rate_scheme_id=self.hour_scheme.pk,
            est_worker_time=timedelta(minutes=90))
        self.assertEqual(task.est_qty, Decimal('1.50'))

    def test_non_hour_scheme_never_pair_fills(self):
        task = TaskService.create_direct(
            self.job, 'Sheets', rate_scheme_id=self.ea_scheme.pk,
            est_qty=Decimal('4'))
        self.assertIsNone(task.est_worker_time)

    def test_hour_scheme_both_provided_passes_through(self):
        task = TaskService.create_direct(
            self.job, 'Cutting', rate_scheme_id=self.hour_scheme.pk,
            est_qty=Decimal('10'), est_worker_time=timedelta(hours=12))
        self.assertEqual(task.est_qty, Decimal('10'))
        self.assertEqual(task.est_worker_time, timedelta(hours=12))

    def test_update_qty_alone_resyncs_worker_time(self):
        task = ...hour-scheme task with est 2h...
        TaskService.update_task(task.pk, est_qty=Decimal('3'))
        task.refresh_from_db()
        self.assertEqual(task.est_worker_time, timedelta(hours=3))
```

Acceptance side (in the estimate-acceptance test module): accept an estimate whose hand-line uses a ServiceItem on an hour scheme with `qty=3` → created task has `est_worker_time == timedelta(hours=3)`; and the equivalent CO-acceptance case.

- [ ] **Step 2: Run them** — FAIL (worker time is None).

- [ ] **Step 3: Implement.** In `apps/jobs/services.py`, module level (near the other helpers; imports: `from datetime import timedelta`, `from django.utils.dateparse import parse_duration`, `from apps.core.timeutils import timedelta_to_hours`, `from apps.core.units import HOUR_UNIT`):

```python
def _coerce_duration(value):
    """DurationField inputs arrive as timedelta (DRF) or ISO/HH:MM:SS string
    (internal callers). Return a timedelta or None."""
    if isinstance(value, str):
        return parse_duration(value)
    return value


def hours_pair_fill(scheme, est_qty, est_worker_time):
    """For hour-denominated schemes, est_qty (billable hours) and
    est_worker_time (schedulable duration) are one number in two encodings.
    When exactly one is provided, derive the other. Convenience, not an
    invariant — both-provided passes through untouched."""
    if scheme is None or scheme.unit_label != HOUR_UNIT:
        return est_qty, est_worker_time
    if est_qty is not None and not est_worker_time:
        return est_qty, timedelta(hours=float(est_qty))
    if est_worker_time and est_qty is None:
        td = _coerce_duration(est_worker_time)
        if td is not None:
            return timedelta_to_hours(td).quantize(Decimal('0.01')), est_worker_time
    return est_qty, est_worker_time
```

`create_direct` — after the scheme guards, before the assignee guard (so a derived worker time satisfies "assigned needs worker time"):

```python
        est_qty, est_worker_time = hours_pair_fill(scheme, est_qty, est_worker_time)
```

`update_task` — before the assignee guard (~L1104), same reasoning:

```python
        scheme = kwargs.get('rate_scheme') or task.rate_scheme
        if scheme is not None and scheme.unit_label == HOUR_UNIT:
            if ('est_qty' in kwargs and 'est_worker_time' not in kwargs
                    and kwargs['est_qty'] is not None):
                _, kwargs['est_worker_time'] = hours_pair_fill(
                    scheme, kwargs['est_qty'], None)
            elif ('est_worker_time' in kwargs and 'est_qty' not in kwargs
                    and kwargs['est_worker_time']):
                kwargs['est_qty'], _ = hours_pair_fill(
                    scheme, None, kwargs['est_worker_time'])
```

`assign` — where `est_worker_time` is applied (~L1214):

```python
        if est_worker_time is not None:
            task.est_worker_time = est_worker_time
            if task.rate_scheme_id and task.est_qty is None:
                task.est_qty, _ = hours_pair_fill(
                    task.rate_scheme, None, est_worker_time)
```

`apps/estimates/models.py` `generate_task` — before the `Task.objects.create` (crystallization + template-add both land here, resolving the estimates-and-prices open item):

```python
        if est_worker_time is None and est_qty is not None and self.rate_scheme_id:
            from apps.jobs.services import hours_pair_fill
            est_qty, est_worker_time = hours_pair_fill(
                self.rate_scheme, est_qty, None)
```

- [ ] **Step 4: Run** the touched modules `--noinput`; also `tests.test_api_schedule` is NOT needed here (schedule only reads `est_worker_time`) — skip. Expect OK.

- [ ] **Step 5: Commit** — `feat: hour-unit tasks pair-fill est_qty and est_worker_time`

---

### Task 9: Frontend duration-parser consolidation

**Files:**
- Modify: `frontend/src/lib/format.js`, `frontend/src/lib/taskTotals.js`, `frontend/src/components/WorkItemForm.svelte`
- Test: `frontend/tests/lib/format.test.js` (create or extend — check `frontend/tests/lib/`)

**Interfaces:**
- Produces (in `lib/format.js`): existing `parseDurationToISO`, `formatDuration`; new `parseDurationToHours(input) -> number|null|false` and `durationToHours(raw) -> number|null` (DRF/ISO duration string → decimal hours). Task 10 and 11 consume these.

- [ ] **Step 1: Failing tests** (Vitest, plain unit tests):

```js
import { parseDurationToHours, durationToHours } from '../../src/lib/format.js';

describe('parseDurationToHours', () => {
  it('parses decimal hours and HH:MM to 2dp hours', () => {
    expect(parseDurationToHours('1.5')).toBe(1.5);
    expect(parseDurationToHours('1:30')).toBe(1.5);
    expect(parseDurationToHours('0:50')).toBe(0.83);
  });
  it('passes through null/false sentinels', () => {
    expect(parseDurationToHours('')).toBeNull();
    expect(parseDurationToHours('abc')).toBe(false);
  });
});

describe('durationToHours', () => {
  it('handles DRF HH:MM:SS, D HH:MM:SS and ISO', () => {
    expect(durationToHours('01:30:00')).toBe(1.5);
    expect(durationToHours('1 02:00:00')).toBe(26);
    expect(durationToHours('PT1H30M')).toBe(1.5);
    expect(durationToHours(null)).toBeNull();
  });
});
```

- [ ] **Step 2: Run** `cd frontend && npm run test:run` — FAIL (no exports).

- [ ] **Step 3: Implement** in `lib/format.js`:

```js
// Parse duration input ("HH:MM" or decimal hours) to decimal hours (2dp).
// Same sentinels as parseDurationToISO: null for empty, false for unparseable.
export function parseDurationToHours(input) {
  const iso = parseDurationToISO(input);
  if (iso === null || iso === false) return iso;
  const m = iso.match(/^PT(\d+)H(\d+)M$/);
  return Math.round(((parseInt(m[1], 10) * 60) + parseInt(m[2], 10)) / 60 * 100) / 100;
}

// Server duration string ("H:MM:SS", "D H:MM:SS", or ISO "PT1H30M") → decimal
// hours (2dp), or null. The one server→hours conversion for display math.
export function durationToHours(raw) {
  if (!raw) return null;
  const str = String(raw);
  const iso = str.match(/^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/);
  let h = null, m = 0, d = 0, s = 0;
  if (iso) {
    d = parseInt(iso[1] || '0', 10); h = parseInt(iso[2] || '0', 10);
    m = parseInt(iso[3] || '0', 10); s = parseInt(iso[4] || '0', 10);
  } else {
    const hms = str.match(/^(?:(\d+) )?(\d+):(\d+):(\d+)/);
    if (!hms) return null;
    d = parseInt(hms[1] || '0', 10); h = parseInt(hms[2], 10);
    m = parseInt(hms[3], 10); s = parseInt(hms[4], 10);
  }
  return Math.round(((d * 24 + h) + m / 60 + s / 3600) * 100) / 100;
}
```

- [ ] **Step 4: Kill the duplicates.**
  - `WorkItemForm.svelte`: delete the local `durationToISO` (L145-169); `import { parseDurationToISO } from '../lib/format.js';` and call it in `save()`.
  - `lib/taskTotals.js` `fmtWorkerTime`: keep the export (many row callers) but reimplement via format.js primitives — parse with the same two regexes? No: replace its body with `durationToHours`-based rendering:

```js
import { durationToHours } from './format.js';

export function fmtWorkerTime(value) {
  const hours = durationToHours(value);
  if (hours === null) return '-';
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (h && m) return `${h}h ${m}m`;
  if (h) return `${h}h`;
  if (m) return `${m}m`;
  return '-';
}
```

  - Leave the six standalone h/m formatters (BlepList, BlepLogTable, ShiftLogTable, ShiftBand, CurrentBlepBand, PayrollReport) alone in this task unless one is a literal drop-in for `formatDuration`; note any conversions or survivors in the commit message. Do not force-fit.

- [ ] **Step 5: Run** `npm run test:run` (full frontend suite — taskTotals/TaskRow/TaskTree tests exercise `fmtWorkerTime`). Expect OK.

- [ ] **Step 6: Commit** — `refactor: one duration parser/converter set in lib/format.js`

---

### Task 10: WorkItemForm — single "Estimated hours" input for hour-unit schemes

**Files:**
- Modify: `frontend/src/components/WorkItemForm.svelte`
- Test: `frontend/tests/components/WorkItemForm.test.js`

**Interfaces:**
- Consumes: `parseDurationToISO`, `parseDurationToHours` (Task 9); scheme objects with `unit_label` (now `'hour'` on elapsed schemes, Task 5).

- [ ] **Step 1: Failing Vitest** — extend `WorkItemForm.test.js` using its existing mount/mock idiom (read the file first; it already mocks `/api/rate-schemes/`):

```js
  it('shows one Estimated hours input for an hour-unit scheme and submits both fields', async () => {
    // scheme fixture: { rate_scheme_id: 7, unit_label: 'hour', algorithm: 'elapsed_time', ... }
    // pick the scheme, type "1:30" into Estimated hours, submit
    // assert POST payload: est_qty === 1.5 AND est_worker_time === 'PT1H30M'
    // assert there is no separate "Estimated qty" spinbutton
  });

  it('keeps two inputs for a non-hour scheme', async () => {
    // scheme fixture with unit_label 'ea': both "Estimated qty" and
    // "Estimated worker time" inputs render; payload passes them separately
  });
```

(Write these as real code against the file's helpers — the sketch names the behavior contract.)

- [ ] **Step 2: Run** `npm run test:run` — FAIL.

- [ ] **Step 3: Implement** in `WorkItemForm.svelte`:

```js
  import { parseDurationToISO, parseDurationToHours } from '../lib/format.js';

  const isHourUnit = $derived(selectedScheme?.unit_label === 'hour');
```

Edit-prefill in the `$effect` (hour-unit rows converge on the worker time; fall back to est_qty for legacy rows that only have a qty):

```js
      estQty = item.est_qty ?? '';
      estWorkerTime = item.est_worker_time
        ? formatDuration(item.est_worker_time)
        : (item.est_qty ?? '');
```

(the existing local `formatDuration` HH:MM renderer stays — it renders the input value).

In `save()`:

```js
    const estWorkerTimeISO = parseDurationToISO(estWorkerTime);
    if (estWorkerTimeISO === false) { ...existing error... }
    const estQtyValue = isHourUnit
      ? parseDurationToHours(estWorkerTime)   // null when input empty
      : (estQty || null);
```

and use `est_qty: estQtyValue` in both the task payload and the add-from-template payload.

Template markup — the "Estimated qty" block (L353-359) renders only `{#if selectedScheme && !isHourUnit}`; the worker-time block (L362-368) becomes, when `isHourUnit`, labelled **Estimated hours** with hint `HH:MM or decimal hours — also the billable quantity ({selectedScheme.unit_label})`; unchanged label otherwise:

```svelte
        <p>
          <label><strong>{isHourUnit ? 'Estimated hours' : 'Estimated worker time'}</strong><br>
            <input type="text" placeholder="e.g. 1:30 or 1.5" bind:value={estWorkerTime}>
            <small>{isHourUnit
              ? 'HH:MM or decimal hours — used for both billing and scheduling'
              : 'HH:MM or decimal hours (1.5 = 1h30m)'}</small>
          </label>
          <FieldError errors={fieldErrs} field="est_worker_time" />
          {#if isHourUnit}<FieldError errors={fieldErrs} field="est_qty" />{/if}
        </p>
```

Template-pick effect: the `estQty = '1'` default (L119) must not apply to hour-unit templates — guard it: `estQty = '1'` only when the picked template's scheme isn't hour-unit; for hour-unit leave `estWorkerTime` for the user (no default).

- [ ] **Step 4: Run** `npm run test:run` — OK (fix any pre-existing WorkItemForm tests that assumed two inputs for hour schemes).

- [ ] **Step 5: Commit** — `feat: single Estimated-hours input for hour-unit tasks`

---

### Task 11: Scheme editor lock, import panel, preview, and task displays

**Files:**
- Modify: `frontend/src/components/RateSchemeManager.svelte`, `frontend/src/components/qboimport/SchemesImportPanel.svelte`, `frontend/src/routes/jobs/TaskDetailPage.svelte`, `frontend/src/components/tasks/TaskRow.svelte`
- Test: `frontend/tests/components/RateSchemeManager.test.js`, `frontend/tests/components/qboimport/*`, tasks component tests

- [ ] **Step 1: Failing Vitests** (each in its component's existing test file, real code per that file's idiom):
  - RateSchemeManager: with algorithm `elapsed_time`, the unit control is a disabled input showing `hour` (no `<select>`); switching to `entered_qty` restores the select. Preview text contains `3 hour @` (no trailing `s`).
  - SchemesImportPanel: changing a row's algorithm to `elapsed time (hourly)` sets and disables that row's unit select to `hour`.

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement.**

`RateSchemeManager.svelte` — unit block (L311-319):

```svelte
      <label><strong>Unit label *</strong><br>
        {#if form.algorithm === 'elapsed_time'}
          <input type="text" value="hour" disabled>
          <small>Time-based schemes are billed in hours.</small>
        {:else}
          <select bind:value={form.unit_label} required>
            <option value="">-- select --</option>
            {#each unitsList as u}
              <option value={u}>{u}</option>
            {/each}
          </select>
        {/if}
      </label>
```

In `save()` (before building the payload): `if (form.algorithm === 'elapsed_time') form.unit_label = 'hour';` — the backend forces it anyway (Task 5); this keeps the form state honest. Preview (L349) drops the naive pluralization:

```svelte
        {previewTotal.qty} {form.unit_label} @ ${previewTotal.effRate}/{form.unit_label} = ${previewTotal.total}
```

`SchemesImportPanel.svelte` — algorithm `onchange` (L85) also pins the unit, and the unit select disables for elapsed rows:

```svelte
            <select value={edit(row).algorithm}
                    onchange={(e) => {
                      set(row, 'algorithm', e.target.value);
                      if (e.target.value === 'elapsed_time') set(row, 'unit_label', 'hour');
                    }}>
```

```svelte
            <select class="unit" value={edit(row).unit_label}
                    disabled={edit(row).algorithm === 'elapsed_time'}
                    onchange={(e) => set(row, 'unit_label', e.target.value)}>
```

`TaskDetailPage.svelte` — the Actual chip (L437): `{task.scheme_unit_label || 'hour'}` → `{task.scheme_unit_label}` (the fallback literal dies; every elapsed task's scheme now says `hour`). Est chips (L403-414): suppress the duplicate Est Qty chip when it restates the worker time:

```js
  import { durationToHours } from '../../lib/format.js';
  const estQtyIsDuplicate = $derived(
    task?.scheme_unit_label === 'hour'
    && task?.est_worker_time
    && Number(task?.est_qty) === durationToHours(task.est_worker_time)
  );
```

and the Est Qty chip condition becomes `{#if task.scheme_name && task.est_qty && !estQtyIsDuplicate}`. (Legacy divergent rows: both chips still show, as today.)

`TaskRow.svelte` — same duplicate-suppression for the Est Qty cell (L76): render `-` when the row's est_qty duplicates its worker time (same `durationToHours` comparison; the Est Time column already shows the number).

- [ ] **Step 4: Run** `npm run test:run` — OK.

- [ ] **Step 5: Commit** — `feat: lock elapsed schemes to hour in UI; dedupe task estimate display`

---

### Task 12: nealsdata converter emits singular units

**Files:**
- Modify: `nealsdata/converter/parsing.py` (`resolve_li_units_and_qty` L157-171), `nealsdata/converter/build.py` (units_list literal ~L164, `_UNIT_PATTERNS` ~L737-758), `nealsdata/convert.md` (§ units mapping ~L505)
- Regenerate: `nealsdata/datasets/converted.json`
- **Never touch `nealsmall.json`.**

- [ ] **Step 1: Update the emitters.**
  - `parsing.resolve_li_units_and_qty`: returns `('hour', qty * 8)` for days, `('hour', qty)` for hours; update its docstring ("canon list has 'hour'…"). The *input* matching (`it == 'hours'` etc.) is FreeAgent Item Type text — unchanged. `infer_algorithm`'s `u in ('hour', 'hours', ...)` check (L302) already accepts both — leave.
  - `build.py` L164: the `units_list` literal becomes exactly Task 1's `DEFAULT_UNITS` (singular). `_UNIT_PATTERNS` targets: `'sheets'` → `'sheet'`, `'lbs'` → `'lb'`, `'hours'` → `'hour'` (the regexes still match plural prose; only the emitted canon changes). Update the `Days`/comment lines mentioning `'hours'`.
  - `convert.md`: `Hours` → `units='hour'`; `Days` → `units='hour'`, qty × 8.

- [ ] **Step 2: Regenerate `nealsdata/datasets/converted.json`** using the converter's documented build invocation (see the top of `nealsdata/convert.md` for the exact command; it reads RM's raw exports from the paths named there). If the raw inputs aren't present on this machine, STOP and ask RM rather than hand-editing the dataset.

- [ ] **Step 3: Verify** — `python manage.py test tests.test_neals_builders --noinput` — read the summary line; expect OK. Then `grep -c '"hours"' nealsdata/datasets/converted.json` → 0.

- [ ] **Step 4: Commit** — `feat: converter emits singular units`

---

### Task 13: E2E — the hour-unit arc

**Files:**
- Modify: `e2e/specs/settings/rate-scheme-modal.spec.js` (unit-lock assertions)
- Create: `e2e/specs/add-line-and-work-authoring/hour-unit-task.spec.js`

Read `docs/designs/e2e-testing.md` and the two exemplar specs (`rate-scheme-modal.spec.js`, `estimate-gate-and-live-picker.spec.js`) first; reuse their login/persona helpers and data-setup idioms verbatim. The seed was singularized in Task 3, so the e2e DB (rebuilt from it every run) is already singular.

- [ ] **Step 1: Extend `rate-scheme-modal.spec.js`:** in the create-modal flow, select algorithm "Based on time worked" → assert the unit control is disabled and reads `hour`; switch to "Worker enters quantity" → assert the unit `<select>` returns. Assert the settings Units tab shows no Remove button beside `hour` (and still none beside `none`).

- [ ] **Step 2: New spec `hour-unit-task.spec.js`** covering the user arc:
  1. As the manager persona, create (or reuse from seed) an elapsed-time scheme — unit shows `hour`.
  2. On a job, add a manual task with that scheme: the form shows a single "Estimated hours" input (no "Estimated qty" spinner); enter `2:00`, save.
  3. Task list/detail shows a 2h estimate once, not twice.
  4. Assign the task to a worker: **no worker-time prompt appears** (est_worker_time was pair-filled).
  Follow the suite's convention of creating its own job (see the `deposit-creation` LATER note — don't hunt the seed for a clean job).

- [ ] **Step 3: Run** `cd e2e && npx playwright test specs/settings/rate-scheme-modal.spec.js specs/add-line-and-work-authoring/hour-unit-task.spec.js` — expect pass.

- [ ] **Step 4: Commit** — `test: e2e coverage for hour-unit scheme + task flow`

---

### Task 14: Documentation updates

**Files:**
- Modify: `docs/designs/estimates-and-prices.md`, `docs/designs/data-constraints.md`, `docs/designs/materials-inventory-and-purchasing.md`, `docs/designs/jobs-and-tasks.md`

- [ ] **Step 1:** `estimates-and-prices.md`: `unit_label` description (~L82) — no free "hour/minute" examples; state the elapsed⇒`hour` rule and that the serializer auto-sets it. Algorithm table (~L95, 389) — elapsed = blep sum in hours, unit always `hour`. `est_qty` note (~L463): describe the pair-fill (hour-unit schemes keep est_qty and est_worker_time in step; the SPA shows one input). Mark the "Auto-fill est_worker_time…" open item (~L2090) **resolved** with a pointer to `hours_pair_fill`. Note the invoice-wizard change: solo elapsed lines now carry hours × rate (matching bundles).

- [ ] **Step 2:** `data-constraints.md` §1.1: `units_list` canon is singular; two special units — `none` (first, undeletable) and `hour` (required present, undeletable); elapsed schemes pinned. §1.5-adjacent field notes if unit fields are described there — spot-check with grep for `'hours'`.

- [ ] **Step 3:** `materials-inventory-and-purchasing.md` ~L684: fix the stale claim that Task/ServiceItem carry a units field (they derive from `rate_scheme.unit_label`).

- [ ] **Step 4:** `jobs-and-tasks.md`: task form's single-input behavior for hour-unit schemes; assign no longer prompts for worker time on crystallized hour-unit tasks.

- [ ] **Step 5:** `grep -rn "'hours'" docs/designs/ | grep -v LATER` — fix remaining stale references in the four touched docs (don't sweep unrelated docs).

- [ ] **Step 6: Commit** — `docs: hour-unit rules across design docs`

---

### Task 15: Final verification

- [ ] **Step 1:** Full backend suite, fresh DB (migrations changed — house rule): `python manage.py test --noinput 2>&1 | tee <scratchpad>/full-suite.log` then **read the summary**: `grep -E "^(OK|FAILED|Ran )" <scratchpad>/full-suite.log`. Gate on the `OK` line, never the exit code of the pipe. Known midnight/date-sensitive flakes in `tests.test_api_schedule` are pre-existing (LATER.md) — re-run that module solo if it's the only failure and note it.
- [ ] **Step 2:** `cd frontend && npm run test:run` — expect clean.
- [ ] **Step 3:** `cd e2e && npx playwright test` — full run. Pre-existing known flakes: `contacts/import-skip-report.spec.js` (fails every full-suite run currently — LATER.md), `deposits/deposit-creation.spec.js` (order-dependent). Report results honestly against that baseline; anything else failing is ours.
- [ ] **Step 4:** Sweep for stragglers: `grep -rn "'hours'\|\"hours\"" apps/ frontend/src/ tests/ e2e/specs/ fixtures/ --include='*.py' --include='*.js' --include='*.svelte' --include='*.json' | grep -v nealsmall | grep -v node_modules` — every remaining hit must be justifiable (FreeAgent input matching in the converter, prose like "24 hours", `blep_minimum`-style duration copy — not unit values).
- [ ] **Step 5:** Confirm all work is committed on RM's branch (`git status` clean, `git log --oneline`), then STOP: report done and ready for RM's review. **No merge, no push, no PR, no options menu** (global CLAUDE.md).

---

## Self-review notes (spec → plan)

- Spec §1 (canon/constant/migration) → Tasks 1, 3, 4. §2 (undeletable) → Task 6. §3 (pinning incl. QBO + converter) → Tasks 5, 12. §4 (pair-fill + single input + displays) → Tasks 8, 10, 11. §5 (wizard solo-elapsed) → Task 7. §6 (conversions) → Tasks 2, 9. §7 (fixtures) → Task 3. §8 (tests) → embedded per task + Task 13 e2e. §9 (docs) → Task 14. §10 sequencing preserved (rename lands atomically across Tasks 1+3 before enforcement in 5/6).
- `hour` fallback removal on TaskDetailPage: Task 11 (spec left it discretionary; removing it is coherent post-pinning).
- Deliberately absent (spec Out-of-scope): blended-rate consolidation, in-use deletion guard for other units, structured units, labor-cost/schedule changes, the two LATER config-robustness bugs.

# Phase 1 — ServicePrice Reframe (flat-fee price onto `rate`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ServicePrice.rate` the price authority for **all** algorithms — relocate flat-fee price off the per-atom `active_modifiers` dict and onto `rate`, let flat-fee entries proliferate (one priced service per item), restore `active_modifiers` to a pure list everywhere, and decouple `TaskTemplate` from pricing.

**Architecture:** A small set of model-method changes (`effective_rate`, `copy_active_modifiers`, removal of `_flat_fee_price`, `TaskTemplate.clean`), a **best-effort** data migration that mints per-price flat-fee services from existing atoms, and consequential updates to fixtures, the `validate_data` command, the `nealsdata` converter, the SPA "Services" labels, and the durable docs. **Depends on Phase 0** (the `RateScheme`→`ServicePrice` rename) being merged.

**Tech Stack:** Django 5.2 / DRF / MySQL; Svelte 5 + Vitest; Django `TestCase` suite.

## Global Constraints

- **NEVER write to the dev DB.** No `migrate` / `loaddata` / `shell` / ORM writes against dev. Migrations are verified via the **test DB only** + `makemigrations --check --dry-run`. (`CLAUDE.md`)
- **Data migration is best-effort.** Mint services for confidently-resolvable `(price, unit_label, accounting_category)` tuples; **log** (do not raise on) ambiguous cases for the user to hand-fix. Pre-production: drop/recreate is acceptable.
- **One agent runs the Django suite at a time** (shared MySQL test DB).
- **macOS `sed`** uses `sed -i ''`.
- Assumes Phase 0 is merged: the model is `ServicePrice`, FK `service_price`, PK `service_price_id`, `db_table='service_prices'`, API `/api/service-prices/`.

---

## File Structure

- `apps/jobs/models.py` — `ServicePrice.effective_rate` (flat-fee → `rate`), remove `ServicePrice._flat_fee_price`, simplify `copy_active_modifiers`.
- `apps/estimates/models.py` — remove the flat-fee-price validation in `TaskTemplate.clean()`.
- `apps/jobs/flat_fee_reframe.py` — **create**: the best-effort relocation helper (callable from the migration and unit-testable).
- `apps/jobs/migrations/0045_reframe_flat_fee_prices.py` — **create**: `RunPython` calling the helper.
- `fixtures/unit_test_data.json`, `fixtures/jobs_basic_data.json`, `fixtures/large_datasets/nealsmall.json`, `fixtures/large_datasets/nealseed.json` — flat-fee services get a real `rate`; flat-fee atoms get empty `active_modifiers`.
- `apps/core/management/commands/validate_data.py` — `check_service_prices`: assert no dict-shaped `active_modifiers`, flat-fee services carry positive `rate`.
- `nealsdata/converter/build.py` (+ `loaders.py` as needed) — generate one flat-fee service per priced item, pure-list `active_modifiers`.
- `frontend/src/components/ServicePriceManager.svelte`, `TaskTemplateManager.svelte`, `WorkItemForm.svelte` — drop the flat-fee-price input from the template/atom forms (price now lives on the service); relabel UI to "Services".
- `docs/designs/estimates-and-prices.md`, `docs/designs/data-constraints.md` — reframe prose.
- Tests: `tests/test_flat_fee_pricing.py`, `tests/test_atom_compute_amount.py`, `tests/test_task_compute_amount.py`, `tests/test_estimate_charge.py`, and any other test constructing flat-fee atoms with a `flat_fee_price` dict.

---

## Task 1: Branch

- [ ] **Step 1: Branch off the merged Phase 0**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git checkout main && git pull --ff-only
git checkout -b feature/serviceprice-reframe
```

Confirm `ServicePrice` exists (Phase 0 merged):

```bash
grep -n "class ServicePrice" apps/jobs/models.py
```
Expected: one match. If absent, Phase 0 is not merged — stop.

---

## Task 2: `effective_rate` returns `rate` for flat-fee

**Files:**
- Modify: `apps/jobs/models.py` (`ServicePrice.effective_rate`)
- Test: `tests/test_flat_fee_pricing.py`

**Interfaces:**
- Produces: `ServicePrice.effective_rate(active_modifiers=None)` returns `self.rate` for `flat_fee`, ignoring `active_modifiers`. Later tasks rely on flat-fee price living on `rate`.

- [ ] **Step 1: Write the failing test**

Replace the body of `tests/test_flat_fee_pricing.py` with tests asserting price-on-rate (drop all `flat_fee_price`-dict assumptions). Core case:

```python
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import ServicePrice
from apps.core.models import AccountingCategory


class FlatFeePricingTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Svc', code='SVC')

    def test_flat_fee_effective_rate_is_rate(self):
        svc = ServicePrice.objects.create(
            name='Tap a hole', algorithm=ServicePrice.FLAT_FEE,
            rate=Decimal('1.00'), unit_label='hole', accounting_category=self.ac,
        )
        # active_modifiers is ignored for flat_fee; price comes from rate.
        self.assertEqual(svc.effective_rate([]), Decimal('1.00'))
        self.assertEqual(svc.effective_rate(['anything']), Decimal('1.00'))

    def test_flat_fee_compute_charge(self):
        svc = ServicePrice.objects.create(
            name='Coat plywood', algorithm=ServicePrice.FLAT_FEE,
            rate=Decimal('30.00'), unit_label='sheet', accounting_category=self.ac,
        )
        self.assertEqual(svc.compute_charge(Decimal('3'), []), Decimal('90.00'))
```

- [ ] **Step 2: Run it; expect failure**

Run: `python manage.py test tests.test_flat_fee_pricing -v 2`
Expected: FAIL (current `effective_rate` reads `_flat_fee_price` from `active_modifiers`, which is now empty/absent).

- [ ] **Step 3: Edit `ServicePrice.effective_rate`**

Replace the flat-fee branch so it returns `rate` directly:

```python
    def effective_rate(self, active_modifiers=None):
        """Compute the per-unit rate.

        Flat-fee price lives on self.rate (one priced service per item).
        For time/qty schemes, apply additive modifier surcharges.
        """
        if self.algorithm == self.FLAT_FEE:
            return self.rate
        modifier_percent = sum(
            m['percent'] for m in self.modifiers if m['key'] in (active_modifiers or [])
        )
        rate = self.rate * (1 + Decimal(modifier_percent) / 100)
        return rate.quantize(Decimal('0.01'))
```

- [ ] **Step 4: Run; expect pass**

Run: `python manage.py test tests.test_flat_fee_pricing -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/models.py tests/test_flat_fee_pricing.py
git commit -m "feat: flat-fee effective_rate reads ServicePrice.rate, not active_modifiers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Decouple `TaskTemplate` from pricing

**Files:**
- Modify: `apps/estimates/models.py` (`TaskTemplate.clean`)
- Test: `tests/test_new_templating.py` (or `tests/test_template_workflows.py` — whichever covers TaskTemplate validation)

**Interfaces:**
- Produces: a `flat_fee` `TaskTemplate` no longer requires a `flat_fee_price` in `default_active_modifiers`; its price is read from `service_price.rate`.

- [ ] **Step 1: Write the failing test**

Add to the TaskTemplate test module:

```python
def test_flat_fee_template_needs_no_price_in_modifiers(self):
    from apps.estimates.models import TaskTemplate
    from apps.jobs.models import ServicePrice
    svc = ServicePrice.objects.create(
        name='Setup fee', algorithm=ServicePrice.FLAT_FEE,
        rate=Decimal('100.00'), unit_label='job',
        accounting_category=self.ac,
    )
    tt = TaskTemplate(
        template_name='Setup', service_price=svc,
        default_active_modifiers=[], default_billable_qty=Decimal('1'),
    )
    tt.full_clean()  # must not raise
```

- [ ] **Step 2: Run; expect failure**

Run: `python manage.py test tests.test_new_templating -v 2`
Expected: FAIL — current `TaskTemplate.clean()` raises "must carry a positive flat_fee_price".

- [ ] **Step 3: Remove the flat-fee-price validation block from `TaskTemplate.clean()`**

Delete the entire `if self.service_price_id and self.service_price.algorithm == ServicePrice.FLAT_FEE:` block (the one raising on `flat_fee_price`). `clean()` keeps only `super().clean()` and any non-pricing validation.

- [ ] **Step 4: Run; expect pass**

Run: `python manage.py test tests.test_new_templating -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/models.py tests/test_new_templating.py
git commit -m "feat: TaskTemplate no longer holds flat-fee price (reads from service)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Remove dead `_flat_fee_price`; simplify `copy_active_modifiers`

**Files:**
- Modify: `apps/jobs/models.py`
- Test: `tests/test_copy_fields.py`

**Interfaces:**
- Produces: `copy_active_modifiers(value)` always returns a list. `ServicePrice._flat_fee_price` no longer exists. Callers must already be off it (Tasks 2–3).

- [ ] **Step 1: Confirm no remaining callers of `_flat_fee_price`**

```bash
grep -rn "_flat_fee_price" apps/ --include="*.py" | grep -v migrations
```
Expected: only the definition in `apps/jobs/models.py`. If any caller remains, fix it before proceeding.

- [ ] **Step 2: Write the failing test**

In `tests/test_copy_fields.py`:

```python
def test_copy_active_modifiers_always_returns_list(self):
    from apps.jobs.models import copy_active_modifiers
    self.assertEqual(copy_active_modifiers(['a', 'b']), ['a', 'b'])
    self.assertEqual(copy_active_modifiers(None), [])
    # legacy dict shape collapses to empty list (price now lives on the service)
    self.assertEqual(copy_active_modifiers({'flat_fee_price': '5'}), [])
```

- [ ] **Step 3: Run; expect failure**

Run: `python manage.py test tests.test_copy_fields -v 2`
Expected: FAIL — current `copy_active_modifiers` returns `dict(value)` for a dict.

- [ ] **Step 4: Simplify `copy_active_modifiers` and delete `_flat_fee_price`**

```python
def copy_active_modifiers(value):
    """Return a copy of an atom's active_modifiers list (modifier keys)."""
    return list(value or [])
```

Note: `list({'flat_fee_price': '5'})` yields `['flat_fee_price']`, not `[]`. To satisfy the legacy-dict test, special-case the dict to an empty list:

```python
def copy_active_modifiers(value):
    """Return a copy of an atom's active_modifiers list (modifier keys).

    Legacy flat-fee dicts ({'flat_fee_price': ...}) collapse to [] — the price
    now lives on ServicePrice.rate, not on the atom.
    """
    if isinstance(value, dict):
        return []
    return list(value or [])
```

Then delete the entire `@staticmethod def _flat_fee_price(...)` method from `ServicePrice`.

- [ ] **Step 5: Run; expect pass**

Run: `python manage.py test tests.test_copy_fields -v 2`
Expected: PASS.

- [ ] **Step 6: Run the full suite to catch flat-fee-dict assumptions elsewhere**

Run: `python manage.py test`
Expected: failures only in tests that still construct flat-fee atoms with a `flat_fee_price` dict. For each, update the test to set the **service's `rate`** instead of an `active_modifiers` price, and use `active_modifiers=[]`. Re-run until green.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: drop _flat_fee_price; active_modifiers is always a list

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Best-effort data migration helper

**Files:**
- Create: `apps/jobs/flat_fee_reframe.py`
- Test: `tests/test_flat_fee_reframe.py` (create)

**Interfaces:**
- Produces: `reframe_flat_fee_prices(ServicePrice, Task, PlanTask, TaskTemplate, *, log=print) -> list[tuple[str,int,str]]` — mints per-price flat-fee services, repoints atoms/templates, empties their `active_modifiers`, and returns a worklist of `(model_name, pk, reason)` for unresolved rows.

- [ ] **Step 1: Write the failing test**

```python
from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory
from apps.jobs.models import ServicePrice, Task, PlanTask
from apps.estimates.models import TaskTemplate
from apps.jobs.flat_fee_reframe import reframe_flat_fee_prices


class FlatFeeReframeTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Svc', code='SVC')
        self.shared = ServicePrice.objects.create(
            name='Flat Fee', algorithm=ServicePrice.FLAT_FEE,
            rate=Decimal('0.00'), unit_label='each', accounting_category=self.ac,
        )

    def _template(self, price):
        return TaskTemplate.objects.create(
            template_name='t', service_price=self.shared,
            default_active_modifiers={'flat_fee_price': str(price)},
            default_billable_qty=Decimal('1'),
        )

    def test_mints_per_price_service_and_repoints(self):
        t1 = self._template('1.00')
        t2 = self._template('30.00')
        t3 = self._template('1.00')  # same price as t1 -> shares minted service
        worklist = reframe_flat_fee_prices(ServicePrice, Task, PlanTask, TaskTemplate)
        t1.refresh_from_db(); t2.refresh_from_db(); t3.refresh_from_db()
        self.assertEqual(t1.service_price.rate, Decimal('1.00'))
        self.assertEqual(t2.service_price.rate, Decimal('30.00'))
        self.assertEqual(t1.service_price_id, t3.service_price_id)
        self.assertNotEqual(t1.service_price_id, t2.service_price_id)
        self.assertEqual(t1.default_active_modifiers, [])
        self.assertEqual(worklist, [])

    def test_logs_unresolved_zero_price(self):
        bad = self._template('0')
        worklist = reframe_flat_fee_prices(ServicePrice, Task, PlanTask, TaskTemplate)
        self.assertTrue(any(r[0] == 'TaskTemplate' and r[1] == bad.pk for r in worklist))
```

- [ ] **Step 2: Run; expect failure**

Run: `python manage.py test tests.test_flat_fee_reframe -v 2`
Expected: FAIL with `ModuleNotFoundError: apps.jobs.flat_fee_reframe`.

- [ ] **Step 3: Implement the helper**

```python
# apps/jobs/flat_fee_reframe.py
from decimal import Decimal

FLAT_FEE = 'flat_fee'


def _price_of(active_modifiers):
    if isinstance(active_modifiers, dict):
        raw = active_modifiers.get('flat_fee_price')
        if raw not in (None, ''):
            return Decimal(str(raw))
    return None


def reframe_flat_fee_prices(ServicePrice, Task, PlanTask, TaskTemplate, *, log=print):
    """Best-effort: relocate per-atom flat_fee_price onto dedicated ServicePrice rows.

    Works with both real and historical (migration) model classes — uses the
    literal 'flat_fee', never model constants. Returns a worklist of
    (model_name, pk, reason) for rows that couldn't be resolved.
    """
    worklist = []
    minted = {}  # (orig_service_id, price_str) -> ServicePrice

    def mint(orig, price):
        key = (orig.pk, str(price))
        if key in minted:
            return minted[key]
        name = f'{orig.name} — {price}'
        try:
            new = ServicePrice.objects.create(
                name=name, description=orig.description, algorithm=FLAT_FEE,
                rate=price, unit_label=orig.unit_label, modifiers=[],
                accounting_category=orig.accounting_category,
            )
        except Exception:  # unique-name collision or similar — log, skip
            return None
        minted[key] = new
        return new

    for model, attr in ((Task, 'active_modifiers'),
                        (PlanTask, 'active_modifiers'),
                        (TaskTemplate, 'default_active_modifiers')):
        for obj in model.objects.select_related('service_price').all():
            svc = obj.service_price
            if not svc or svc.algorithm != FLAT_FEE:
                continue
            am = getattr(obj, attr)
            price = _price_of(am)
            if price is None or price <= 0:
                if isinstance(am, dict):
                    worklist.append((model.__name__, obj.pk, 'no/zero flat_fee_price'))
                continue
            new_svc = mint(svc, price)
            if new_svc is None:
                worklist.append((model.__name__, obj.pk, 'could not mint service'))
                continue
            obj.service_price = new_svc
            setattr(obj, attr, [])
            obj.save()
    return worklist
```

- [ ] **Step 4: Run; expect pass**

Run: `python manage.py test tests.test_flat_fee_reframe -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/flat_fee_reframe.py tests/test_flat_fee_reframe.py
git commit -m "feat: best-effort flat-fee price relocation helper

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: The data migration

**Files:**
- Create: `apps/jobs/migrations/0045_reframe_flat_fee_prices.py`

- [ ] **Step 1: Write the migration**

```python
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.jobs.flat_fee_reframe import reframe_flat_fee_prices
    ServicePrice = apps.get_model('jobs', 'ServicePrice')
    Task = apps.get_model('jobs', 'Task')
    PlanTask = apps.get_model('jobs', 'PlanTask')
    TaskTemplate = apps.get_model('estimates', 'TaskTemplate')
    worklist = reframe_flat_fee_prices(ServicePrice, Task, PlanTask, TaskTemplate)
    for kind, pk, reason in worklist:
        print(f'[flat_fee_reframe] UNRESOLVED {kind} pk={pk}: {reason}')


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0044_rename_ratescheme_to_serviceprice'),
        ('estimates', '0026_rename_tasktemplate_rate_scheme'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
```

- [ ] **Step 2: Verify migration state is consistent (read-only)**

Run: `python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`. **Do not** run `migrate`.

- [ ] **Step 3: Run the suite (the migration runs against the empty test DB as a no-op; logic is covered by Task 5)**

Run: `python manage.py test`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/jobs/migrations/0045_reframe_flat_fee_prices.py
git commit -m "feat: data migration to relocate flat-fee prices (best-effort)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Update fixtures to the reframed shape

**Files:**
- Modify: `fixtures/unit_test_data.json`, `fixtures/jobs_basic_data.json`, `fixtures/large_datasets/nealsmall.json`, `fixtures/large_datasets/nealseed.json`

- [ ] **Step 1: Find flat-fee services and their dependent atoms in each fixture**

```bash
grep -n '"algorithm": "flat_fee"' fixtures/unit_test_data.json fixtures/jobs_basic_data.json fixtures/large_datasets/*.json
grep -n 'flat_fee_price' fixtures/unit_test_data.json fixtures/jobs_basic_data.json fixtures/large_datasets/*.json
```

- [ ] **Step 2: For each flat-fee service, set `rate` to the price its atoms carried; for each atom/template, set `active_modifiers` (or `default_active_modifiers`) to `[]`.**

Edit by hand (fixtures are small/structured): give each previously-shared flat-fee service its own row per distinct price (split if one service backed multiple prices), set `"rate"` to that price, and replace every `{"flat_fee_price": "..."}` with `[]`. This mirrors what the migration does for dev data, since the migration does not touch fixture data loaded into the test DB.

- [ ] **Step 3: Verify fixtures load (read-only — into the test DB via a throwaway test)**

Run: `python manage.py test tests.test_jobs_models_with_fixtures -v 2`
(or any `FixtureTestCase`-based module that loads these fixtures)
Expected: PASS — fixtures deserialize and atoms compute amounts from `rate`.

- [ ] **Step 4: Commit**

```bash
git add fixtures/
git commit -m "chore: reframe flat-fee fixtures (price on rate, empty active_modifiers)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Update `validate_data` command

**Files:**
- Modify: `apps/core/management/commands/validate_data.py` (`check_service_prices`, formerly `check_rate_schemes`)
- Test: `tests/test_api_templates_config.py` or a dedicated `tests/test_validate_data.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_validate_data.py`:

```python
from decimal import Decimal
from io import StringIO
from django.test import TestCase
from django.core.management import call_command
from apps.core.models import AccountingCategory
from apps.jobs.models import ServicePrice


class ValidateDataServicePriceTest(TestCase):
    def test_flags_zero_rate_flat_fee(self):
        ac = AccountingCategory.objects.create(name='Svc', code='SVC')
        ServicePrice.objects.create(
            name='Bad flat', algorithm=ServicePrice.FLAT_FEE,
            rate=Decimal('0.00'), unit_label='each', accounting_category=ac,
        )
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        self.assertIn('flat-fee', out.getvalue().lower())
```

- [ ] **Step 2: Run; expect failure**

Run: `python manage.py test tests.test_validate_data -v 2`
Expected: FAIL (no such check yet).

- [ ] **Step 3: Update the check**

Rename `check_rate_schemes` → `check_service_prices` (and its call site at the top of the command). Add, inside the per-row loop:

```python
            if rs.algorithm == ServicePrice.FLAT_FEE and (rs.rate is None or rs.rate <= 0):
                self.errors.append(
                    f'ServicePrice {rs.pk} ({rs.name}): flat-fee service must have a positive rate'
                )
            for obj_label, am in self._active_modifiers_for(rs):
                if isinstance(am, dict):
                    self.errors.append(
                        f'{obj_label}: active_modifiers is a dict; must be a list of keys'
                    )
```

(Implement `_active_modifiers_for` to walk the service's referencing `Task`/`PlanTask`/`TaskTemplate` rows, or fold the dict-shape check into the existing per-model validators — whichever fits the command's structure. The header comment block listing checks updates from `RateScheme` to `ServicePrice`.)

- [ ] **Step 4: Run; expect pass**

Run: `python manage.py test tests.test_validate_data -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/core/management/commands/validate_data.py tests/test_validate_data.py
git commit -m "feat: validate_data checks flat-fee rate and pure-list active_modifiers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Update the `nealsdata` converter

**Files:**
- Modify: `nealsdata/converter/build.py` (and `loaders.py` if it emits `flat_fee_price`)
- Test: `tests/test_neals_builders.py`

- [ ] **Step 1: Locate flat-fee emission**

```bash
grep -rn "flat_fee\|flat_fee_price\|active_modifiers\|service_price\|rate_scheme" nealsdata/
```

- [ ] **Step 2: Write/adjust the failing test**

In `tests/test_neals_builders.py`, assert that a built flat-fee service carries its price on `rate` and that built atoms have a list `active_modifiers` with no `flat_fee_price` key. (Follow the module's existing builder-assertion style.)

- [ ] **Step 3: Run; expect failure**

Run: `python manage.py test tests.test_neals_builders -v 2`
Expected: FAIL.

- [ ] **Step 4: Update the converter**

Emit one flat-fee `ServicePrice` per distinct priced item with `rate` = the price; emit atoms/templates with `active_modifiers = []` (no `flat_fee_price`).

- [ ] **Step 5: Run; expect pass**

Run: `python manage.py test tests.test_neals_builders -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nealsdata/ tests/test_neals_builders.py
git commit -m "feat: nealsdata emits per-item flat-fee services, list active_modifiers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Frontend — drop the flat-fee-price input; relabel "Services"

**Files:**
- Modify: `frontend/src/components/ServicePriceManager.svelte`, `frontend/src/components/TaskTemplateManager.svelte`, `frontend/src/components/WorkItemForm.svelte`, `frontend/src/routes/SettingsPage.svelte`
- Test: `frontend/tests/components/ServicePriceManager.test.js`, `frontend/tests/components/TaskTemplateManager.test.js`, `frontend/tests/components/WorkItemForm.test.js`

- [ ] **Step 1: Write/adjust the failing component test**

In `TaskTemplateManager.test.js` and `WorkItemForm.test.js`, assert that **no** flat-fee-price input is rendered when a flat-fee service is selected (the price comes from the service now), and that the flat-fee service's own `rate` is shown read-only. In `ServicePriceManager.test.js`, assert a flat-fee service is created/edited with a `rate` field (not a per-atom price) and that the section heading reads "Services".

- [ ] **Step 2: Run; expect failure**

Run: `cd frontend && npm run test:run`
Expected: FAIL on the updated specs.

- [ ] **Step 3: Update components**

- `TaskTemplateManager.svelte` / `WorkItemForm.svelte`: remove the conditional `flat_fee_price` input and the dict-shaped `active_modifiers` handling; `active_modifiers` is always a list of modifier keys. Show the selected service's `rate`/`unit_label` read-only.
- `ServicePriceManager.svelte`: ensure the create/edit form's price field maps to `rate` for all algorithms including flat-fee; update headings/labels to "Services".
- `SettingsPage.svelte`: relabel the section/menu entry to "Services".

- [ ] **Step 4: Run; expect pass + build**

Run: `cd frontend && npm run test:run && npm run build`
Expected: PASS and successful build.

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat: SPA reads flat-fee price from the service; label as Services

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Docs

**Files:**
- Modify: `docs/designs/estimates-and-prices.md`, `docs/designs/data-constraints.md`

- [ ] **Step 1: Rewrite the pricing prose**

In `estimates-and-prices.md`: replace the §2 pointer note (from Phase 0) and the flat-fee subsections with the reframed model — `ServicePrice` is the service price list; `rate` is the price for all algorithms; flat-fee services proliferate (one per priced item); `active_modifiers` is a pure list; `TaskTemplate` holds no price. Remove the `flat_fee_price`/`_flat_fee_price` descriptions. In `data-constraints.md`: note flat-fee services require positive `rate` and `active_modifiers` is always a list.

- [ ] **Step 2: Commit**

```bash
git add docs/
git commit -m "docs: ServicePrice reframe — price on rate, pure-list modifiers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Final gate

- [ ] **Step 1: Full backend + frontend suites**

```bash
cd /Users/drshiny/Documents/konbini/Minibini && python manage.py test
cd frontend && npm run test:run
```
Expected: both PASS.

- [ ] **Step 2: Straggler sweep for flat-fee-price assumptions**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
grep -rn "flat_fee_price\|_flat_fee_price" apps/ frontend/src tests/ --include="*.py" --include="*.svelte" --include="*.js" | grep -v "/migrations/"
```
Expected: **no output** (only the migration `0045` references the legacy key via the helper, and that's by design).

---

## Self-Review

**Spec coverage (parent §3.1, §5.1–5.3, §8, §8.1, §12 Phase 1):**
- flat-fee price → `rate` (Task 2), `effective_rate` (Task 2). ✓
- proliferation / drop shared convention (migration mints per-price, Task 5/6; fixtures Task 7; nealsdata Task 9). ✓
- `active_modifiers` pure list (Task 4). ✓
- remove `_flat_fee_price` (Task 4). ✓
- `TaskTemplate` price decoupling (Task 3, Task 10). ✓
- best-effort migration with worklist (Task 5/6). ✓
- validate_data update (Task 8). ✓
- nealsdata update (Task 9). ✓
- UI "Services" (Task 10). ✓
- docs (Task 11). ✓

**Placeholder scan:** Task 8 Step 3 and Task 9/10 lean on "follow the module's structure" where the existing code shape isn't reproduced here, but each gives the exact assertion/behavior and file. No TBDs in backend-core logic.

**Type/name consistency:** `ServicePrice`, `service_price`, `effective_rate`, `compute_charge`, `copy_active_modifiers`, `reframe_flat_fee_prices`, `check_service_prices` used consistently.

---

## Execution Handoff

Plan saved to `docs/plans/2026-06-23-phase1-serviceprice-reframe.md`. Phase 2 (percentage adjustments) builds on this. Execution options: subagent-driven (recommended) or inline.
</content>

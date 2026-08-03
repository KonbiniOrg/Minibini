# Task-Owned Money — Implementation Plan (Roadmap + Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `docs/plans/2026-08-02-task-owned-money.md` — tasks own their money block, RateScheme becomes an editable stamp/preset, and the downstream re-scopes (Fee, entry vocabulary, subtask quantities, outsourced POs, nullable AC) follow in later phases.

**Architecture:** Phase 1 moves the price of record from `RateScheme` onto `Task` (snapshot-at-stamp), deletes the supersession apparatus, snapshots adjustment percents onto document lines, and adds preset retirement + a default-preset Configuration key. Every compute path that reads `task.rate_scheme.*` moves to task-own fields. Later phases build on that foundation and are planned separately when commissioned.

**Tech Stack:** Django 5.2 / DRF / MySQL backend; Svelte 5 SPA (Vitest); Playwright e2e.

## Global Constraints

- **Branch:** RM designates the working branch before execution (do not create or rename branches; currently the spec lives on `feature/fees`).
- **NEVER write the dev DB** — no `migrate`, no `shell` ORM writes, no `loaddata`. Verify model behavior only via `python manage.py test` (own test DB).
- **Every test command carries `--noinput`**; one Django test run at a time (both hook-enforced).
- **Never judge tests by a piped exit code** — read the `OK` / `FAILED` summary line and `Ran N tests` count.
- **After any migration change, the verification suite runs on a fresh DB — no `--keepdb`.**
- Status values via model constants, never string literals.
- Line-item deletes only via `LineItemService.delete_line_item_with_renumber`.
- No `QuerySet.update()`/bulk writes on fields `save()` normalizes (Blep/Shift floor times; RateScheme normalizes modifiers).
- API error contract: `{'detail': ...}` operation errors / `{'<field>': [...]}` validation; DELETE returns 200 + JSON; don't catch service `ValidationError` just to re-render it.
- Frontend errors through `triageError(e)` venues; `<tr>` always inside `<tbody>`; Vitest test per component change (`cd frontend && npm run test:run`).
- Converter changes must run `python manage.py test tests.test_neals_builders --noinput`; never regenerate or test against `nealsdata/nealsmall.json`.
- Subagents run **targeted** test modules per task; the full backend suite runs once at final verification (Task 13).
- E2E is DoD for changed user-reachable flows (Task 14); backend-only tasks are exempt individually.
- Docs in `docs/designs/` update in the same phase as the behavior change (Task 15).

---

## Phase roadmap

| Phase | Spec §§ | Delivers | Plan |
|---|---|---|---|
| **1 (this doc)** | §1 §2 §5 §6 | Task money block, presets-as-stamps, supersession deleted, `is_active` retirement, default-preset config, adjustment-percent snapshot, money-field permissions | below |
| 2 | §3 §8 | Fee re-scope (signed amounts, drop `task` OneToOne), three-value freeform line kind, Work/Fee-Credit entry forms, acceptance discriminator rewrite | write at phase start |
| 3 | §4 | Nullable Task AC end-to-end, fallback AC Configuration + invoice-compose stamping + wizard flag, QBO push untouched-but-null-proof | write at phase start |
| 4 | §9 | Non-startable parents, per-unit subtasks, `qty_scales_with_parent`, derivation helper, parent completion billing qty, deliverables bridge | write at phase start |
| 5 | §7 | Service-PO link UI, PO-level reconciliation, awaiting-reconciliation nudge, task-rate prompt | write at phase start |

Phases must land in order (2–5 all assume the Phase 1 field layout). Each phase ends with its own fresh-DB full suite + e2e + docs update.

---

## Phase 1 — file structure

| File | Responsibility in this phase |
|---|---|
| `apps/jobs/models.py` | Task money fields + compute paths; RateScheme slimming; `copy_active_modifiers` new shape |
| `apps/jobs/migrations/00XX_*` | Schema + data migrations (numbers assigned by `makemigrations`) |
| `apps/jobs/services.py` | `TaskService` stamp wiring; `hours_pair_fill` unchanged consumers |
| `apps/estimates/models.py` | `ServiceItem.generate_task` stamping; `adjustment_percent` on EstimateLineItem (+ CO twin) |
| `apps/invoicing/models.py` | `adjustment_percent` on InvoiceLineItem |
| `apps/core/adjustments.py` | Read percent from the line, not the scheme |
| `apps/core/wizard.py` | `_uniform_scheme_bundle` → (rate, unit, modifiers) equality; `_atom_category` via task field |
| `apps/estimates/services.py`, `apps/invoicing/services.py` | qty/price branch points read task fields |
| `apps/core/services.py` | `ConfigurationService` scheme methods: drop supersede, add retire; `default_rate_scheme` key |
| `apps/api/rate_schemes/*` | Retire endpoint, `is_active` filter, no 409/supersede flow |
| `apps/api/tasks/serializers.py`, `apps/api/mixins.py` | Task money fields exposed; permission-gated writes; stamp-on-create |
| `apps/core/management/commands/validate_data.py` | New modifier shape, task-field checks, scheme checks minus frozen |
| `nealsdata/converter/build.py` | Emit task money fields |
| `frontend/src/components/RateSchemeManager.svelte` (+test) | No supersession UI; Active toggle; default-preset picker |
| `frontend/src/components/WorkItemForm.svelte`, `routes/.../TaskDetailPage.svelte` (+tests) | Preset-stamp form, editable money fields (permission-gated), provenance chip |
| `e2e/specs/...` | Preset retire/default + stamped task creation |
| `docs/designs/*.md` | estimates-and-prices, jobs-and-tasks, architecture-and-conventions, data-constraints, users-and-permissions |

**Canonical interfaces (used by every task below and by Phases 2–5):**

```python
# apps/jobs/models.py
class Task(TaskBase):
    QTY_ELAPSED = 'elapsed_time'      # same strings as RateScheme.ELAPSED_TIME /
    QTY_ENTERED = 'entered_qty'       # ENTERED_QTY so the data migration is a copy
    QTY_SOURCE_CHOICES = [(QTY_ELAPSED, 'Timeslips'), (QTY_ENTERED, 'Entered quantity')]

    qty_source = models.CharField(max_length=20, choices=QTY_SOURCE_CHOICES,
                                  default=QTY_ENTERED)
    rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    unit_label = models.CharField(max_length=50, default='none')
    accounting_category = models.ForeignKey('core.AccountingCategory',
        on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    source_scheme = models.ForeignKey('jobs.RateScheme', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='stamped_tasks')   # provenance ONLY
    # active_modifiers: list of {'key','label','percent'} snapshots (was list of keys)

    def stamp_from_scheme(self, scheme, modifier_keys=None) -> None: ...
    def effective_rate(self) -> Decimal: ...        # 0 when rate is None
    def get_actual_qty(self) -> Decimal: ...        # moved off RateScheme
    def compute_amount(self, active_modifiers=None) -> Decimal
    def compute_estimate_amount(self, active_modifiers=None) -> Decimal
    @property
    def effective_accounting_category(self)         # → self.accounting_category

class SchemeInactiveError(Exception): ...           # replaces SchemeSupersededError
```

In Phase 1, `Task.accounting_category` is nullable at the DB but **required by serializers/services** (stamps always carry it; presets require AC) — Phase 3 relaxes that, not this one.

---

### Task 1: Task money fields — schema + data migration

**Files:**
- Modify: `apps/jobs/models.py` (Task field block, ~`:294-320`)
- Create: two migrations via `makemigrations` (schema add + RunPython data copy) and a rename/alter migration for `rate_scheme` → `source_scheme`
- Test: `tests/test_task_money_migration.py` (new)

**Interfaces:**
- Consumes: existing `Task.rate_scheme` (NOT NULL, PROTECT), `RateScheme.modifiers` (`[{key,label,percent}]`), `Task.active_modifiers` (list of keys)
- Produces: the canonical Task fields above, populated for every existing row; `source_scheme` nullable SET_NULL

- [ ] **Step 1: Write the failing migration test** (uses the historical-state pattern — see `tests/test_flat_fee_reframe.py` for the house style of testing a RunPython helper directly):

```python
# tests/test_task_money_migration.py
from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, RateScheme, Task
from apps.jobs.task_money_backfill import backfill_task_money  # helper the data migration calls

class TaskMoneyBackfillTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Shop', code='SHOP')
        self.scheme = RateScheme.objects.create(
            name='Shop rate', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('95.00'), unit_label='hour',
            modifiers=[{'key': 'rush', 'label': 'Rush', 'percent': 50}],
            accounting_category=self.ac)
        self.job = Job.objects.create(name='J', contact=None)
        self.task = Task.objects.create(
            job=self.job, name='Cut', source_scheme=self.scheme,
            active_modifiers=['rush'])

    def test_backfill_copies_scheme_values_and_resolves_modifiers(self):
        # Simulate pre-backfill state: money fields empty, modifiers still keys.
        Task.objects.filter(pk=self.task.pk).update(
            rate=None, unit_label='none', accounting_category=None,
            qty_source=Task.QTY_ENTERED, active_modifiers=['rush'])
        backfill_task_money(Task, RateScheme)
        t = Task.objects.get(pk=self.task.pk)
        self.assertEqual(t.rate, Decimal('95.00'))
        self.assertEqual(t.unit_label, 'hour')
        self.assertEqual(t.qty_source, Task.QTY_ELAPSED)
        self.assertEqual(t.accounting_category_id, self.ac.pk)
        self.assertEqual(t.active_modifiers,
                         [{'key': 'rush', 'label': 'Rush', 'percent': 50}])
```

- [ ] **Step 2: Run it — must fail** (`ImportError: task_money_backfill`):
  `python manage.py test tests.test_task_money_migration --noinput`
- [ ] **Step 3: Implement.** Add the canonical fields to `Task` (Step 1's shapes). Order of migrations: (a) `AddField` × 4 (`qty_source`, `rate`, `unit_label`, `accounting_category`); (b) `RenameField rate_scheme → source_scheme` + `AlterField` to `null=True, on_delete=SET_NULL, related_name='stamped_tasks'`; (c) RunPython calling the helper below (mirror the `apps/jobs/flat_fee_reframe.py` historical-helper pattern, including its DO-NOT-SWEEP header):

```python
# apps/jobs/task_money_backfill.py
def backfill_task_money(Task, RateScheme):
    """One-shot copy of scheme values onto tasks + key→snapshot modifier resolution.
    Iterates and saves via update() per-row on the historical model (no custom save
    side effects exist for these fields)."""
    for task in Task.objects.select_related('source_scheme').iterator():
        scheme = task.source_scheme
        if scheme is None:
            continue
        keys = task.active_modifiers if isinstance(task.active_modifiers, list) else []
        resolved = [m for m in (scheme.modifiers or []) if m.get('key') in keys]
        Task.objects.filter(pk=task.pk).update(
            qty_source=scheme.algorithm, rate=scheme.rate,
            unit_label=scheme.unit_label,
            accounting_category_id=scheme.accounting_category_id,
            active_modifiers=resolved)
```

(`update()` is safe here: none of these fields are normalized by `Task.save()`.) Grep check before committing (field-rename pitfall): `grep -rn "rate_scheme" apps/ nealsdata/ frontend/src/ | grep -v migrations` — every hit is a later task's job; record the list in the commit message body.
- [ ] **Step 4: Run test — must pass**, then the neighbouring model suites:
  `python manage.py test tests.test_task_money_migration tests.test_copy_fields --noinput`
  (`test_copy_fields` will fail on `copy_active_modifiers` — expected; it's fixed in Task 2. Note it in the commit.)
- [ ] **Step 5: Commit** `feat(jobs): task money fields + backfill; rate_scheme becomes source_scheme provenance`

### Task 2: Task compute paths from own fields

**Files:**
- Modify: `apps/jobs/models.py` — `copy_active_modifiers` (~`:39-47`), `Task.compute_amount`/`compute_estimate_amount` (~`:364-386`), `Task.effective_rate` (~`:389`), `Task.effective_accounting_category` (~`:360`); move `get_actual_qty` body from `RateScheme` (~`:541-559`) onto `Task`
- Test: `tests/test_task_money_compute.py` (new); update `tests/test_copy_fields.py`

**Interfaces:**
- Consumes: Task fields from Task 1
- Produces: `Task.effective_rate()`, `Task.get_actual_qty()`, `Task.compute_amount()`, `Task.compute_estimate_amount()` reading ONLY task fields; `copy_active_modifiers` deep-copies dict lists (legacy key-lists and `{'flat_fee_price':…}` dicts still collapse to `[]` — they can't be resolved without a scheme)

- [ ] **Step 1: Failing tests:**

```python
# tests/test_task_money_compute.py
class TaskMoneyComputeTest(TestCase):
    # setUp: AC + Job as in TaskMoneyBackfillTest; no RateScheme needed — that's the point.
    def test_effective_rate_from_task_fields(self):
        t = Task.objects.create(job=self.job, name='X', qty_source=Task.QTY_ENTERED,
            rate=Decimal('100.00'), unit_label='ea', accounting_category=self.ac,
            active_modifiers=[{'key': 'rush', 'label': 'Rush', 'percent': 50}])
        self.assertEqual(t.effective_rate(), Decimal('150.00'))

    def test_effective_rate_none_rate_is_zero(self):
        t = Task.objects.create(job=self.job, name='X', rate=None,
                                accounting_category=self.ac)
        self.assertEqual(t.effective_rate(), Decimal('0.00'))

    def test_entered_qty_amounts(self):
        t = Task.objects.create(job=self.job, name='X', qty_source=Task.QTY_ENTERED,
            rate=Decimal('10.00'), unit_label='ea', accounting_category=self.ac,
            est_qty=Decimal('5'), actual_qty=Decimal('4'))
        self.assertEqual(t.compute_estimate_amount(), Decimal('50.00'))
        self.assertEqual(t.compute_amount(), Decimal('40.00'))

    def test_elapsed_actual_qty_sums_bleps(self):
        # create task qty_source=QTY_ELAPSED, one closed blep of 90 minutes
        # assert t.get_actual_qty() == Decimal('1.50')
        ...  # mirror blep setup from tests/test_atom_compute_amount.py
```

(Write the elapsed test fully by copying the blep fixture lines from `tests/test_atom_compute_amount.py` — it already builds closed bleps.)
- [ ] **Step 2: Run — fail** (`effective_rate` still reads `self.rate_scheme`, now gone): `python manage.py test tests.test_task_money_compute --noinput`
- [ ] **Step 3: Implement:**

```python
def effective_rate(self):
    if self.rate is None:
        return Decimal('0.00')
    pct = sum(Decimal(str(m.get('percent', 0))) for m in (self.active_modifiers or []))
    return (self.rate * (1 + pct / 100)).quantize(Decimal('0.01'))

def get_actual_qty(self):
    if self.qty_source == self.QTY_ELAPSED:
        total = sum((b.elapsed for b in self.blep_set.all() if b.elapsed is not None),
                    timedelta())
        return timedelta_to_hours(total).quantize(Decimal('0.01'))
    return self.actual_qty or Decimal('0')

def compute_amount(self, active_modifiers=None):
    return (self.get_actual_qty() * self.effective_rate()).quantize(Decimal('0.01'))

def compute_estimate_amount(self, active_modifiers=None):
    return ((self.est_qty or Decimal('0')) * self.effective_rate()).quantize(Decimal('0.01'))
```

`copy_active_modifiers`: dict-list → `[dict(m) for m in value]`; list-of-strings (legacy keys) or bare dict → `[]`. Update `RateScheme.get_actual_qty`/`effective_rate`/`compute_charge` to remain for **preset preview only** (RateSchemeManager preview, serializer detail) — mark with a comment: *never called with a task*.
- [ ] **Step 4: Run new + updated suites:** `python manage.py test tests.test_task_money_compute tests.test_copy_fields tests.test_atom_compute_amount --noinput` — `test_atom_compute_amount` failures at this point must be only assertions still constructing schemes for tasks; update those fixtures to task-field construction in this task.
- [ ] **Step 5: Commit** `feat(jobs): task computes price from its own money block`

### Task 3: Stamping — `stamp_from_scheme`, creation gates, `SchemeInactiveError`

**Files:**
- Modify: `apps/jobs/models.py` (add `stamp_from_scheme`, add `SchemeInactiveError`, delete `SchemeSupersededError`), `apps/jobs/services.py` (`TaskService.create_direct` ~`:1051`, `create_from_template` ~`:1019`), `apps/estimates/models.py` (`ServiceItem.generate_task` ~`:481-538`)
- Test: `tests/test_task_stamping.py` (new); update `tests/test_service_item*.py`

**Interfaces:**
- Consumes: Task 1–2 fields/methods
- Produces: `task.stamp_from_scheme(scheme, modifier_keys=None)` — sets `qty_source=scheme.algorithm`, `rate`, `unit_label`, `accounting_category`, resolved modifier snapshots (default: all of `ServiceItem.default_active_modifiers` when routed via a ServiceItem, else `modifier_keys`), `source_scheme=scheme`; raises `ValueError` on percentage schemes; creation services raise `SchemeInactiveError` for `is_active=False` presets unless `allow_inactive_scheme=True` (rename of the existing `allow_superseded_scheme` kwarg — grep callers)

- [ ] **Step 1: Failing tests** — stamp copies all five aspects; stamping from an inactive preset via `create_direct` raises `SchemeInactiveError`; stamped task then prices independently (mutate `scheme.rate`, assert task unchanged):

```python
def test_stamp_then_edit_preset_does_not_reprice(self):
    task = Task.objects.create(job=self.job, name='X', accounting_category=self.ac)
    task.stamp_from_scheme(self.scheme, modifier_keys=['rush'])
    task.save()
    self.scheme.rate = Decimal('500.00'); self.scheme.save()
    task.refresh_from_db()
    self.assertEqual(task.rate, Decimal('95.00'))
```

(`is_active` doesn't exist until Task 4 — write the inactive-preset test now with `@skipUnless(hasattr(RateScheme, 'is_active'), 'Task 4')`, and remove the skip in Task 4.)
- [ ] **Step 2: Run — fail:** `python manage.py test tests.test_task_stamping --noinput`
- [ ] **Step 3: Implement** stamp + rewire the three creation paths (each currently assigns `rate_scheme=`/copies keys — they now call `stamp_from_scheme` before first save; `hours_pair_fill` keeps keying on `unit_label == 'hour'`, now the task's field).
- [ ] **Step 4: Run:** `python manage.py test tests.test_task_stamping tests.test_service_item_generate_task tests.test_deferred_service_crystallization --noinput` (fix constructor fallout inside this task).
- [ ] **Step 5: Commit** `feat(jobs): preset stamping via stamp_from_scheme; SchemeInactiveError`

### Task 4: RateScheme slimming — supersession out, `is_active` in

**Files:**
- Modify: `apps/jobs/models.py` (RateScheme ~`:433-633`: delete `replaced_by`, `replaced_at`, `FROZEN_FIELDS`, `supersede()`, the frozen-field guard in `clean()`; keep `_normalize_modifiers`, AC-required, negative-rate-only-percentage, hour-pin; add `is_active = models.BooleanField(default=True)`; `is_referenced`/`reference_counts` now count `stamped_tasks` + `serviceitem_set` for display only), `apps/core/services.py` (~`:1207-1244`: `update_rate_scheme` loses the `code='referenced'` refusal; `supersede_rate_scheme` deleted; add `retire_rate_scheme(pk)` / `reactivate_rate_scheme(pk)`; `delete_rate_scheme` unchanged — ServiceItem FK PROTECT still guards)
- Create: migration (RemoveField ×2, AddField `is_active`)
- Test: update `tests/test_rate_scheme_modifiers.py`; replace the supersession test module with `tests/test_rate_scheme_retire.py`

**Interfaces:**
- Produces: freely editable presets; `RateScheme.is_active`; `ConfigurationService.retire_rate_scheme(pk)`; supersede gone everywhere server-side

- [ ] **Step 1: Failing tests** — editing a referenced preset succeeds and does not touch stamped tasks; retiring hides from `task_applicable` (assert in Task 7's view test — here assert the flag flips); deleting a preset with stamped tasks succeeds and nulls `source_scheme` (SET_NULL); deleting one referenced by a ServiceItem raises `ProtectedError`.
- [ ] **Step 2: Run — fail:** `python manage.py test tests.test_rate_scheme_retire --noinput`
- [ ] **Step 3: Implement** (delete `supersede()` and both timestamp fields in the same migration; grep `replaced_by\|supersede` across `apps/ frontend/src/ tests/` and list the frontend hits for Task 11).
- [ ] **Step 4: Run:** `python manage.py test tests.test_rate_scheme_retire tests.test_rate_scheme_modifiers --noinput`
- [ ] **Step 5: Commit** `feat(jobs): rate schemes are freely editable presets; supersession removed; is_active retirement`

### Task 5: Adjustment percent snapshots onto lines

**Files:**
- Modify: `apps/estimates/models.py` (`EstimateLineItem` + `ChangeOrderLineItem`: add `adjustment_percent = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)`), `apps/invoicing/models.py` (InvoiceLineItem: same), `apps/core/adjustments.py` (`compute_adjustment_amount` ~`:23-55` reads `line.adjustment_percent`, not `line.adjustment_service.rate`), `apps/estimates/services.py` ~`:546` and `apps/invoicing/services.py` ~`:312` (populate the field at adjustment-line creation), `copy_from_estimate` (~`apps/invoicing/services.py:221-290`: carry the field)
- Create: schema migration + RunPython backfill (`line.adjustment_percent = line.adjustment_service.rate` where FK set)
- Test: update `tests/test_adjustment_lines.py`

**Interfaces:**
- Produces: `adjustment_percent` on all three line models; `adjustment_service` FK demoted to provenance (never read for math — same invariant as `source_scheme`)

- [ ] **Step 1: Failing test** — create a percentage adjustment line, then change the scheme's `rate`; recompute; the adjustment amount must NOT move:

```python
def test_editing_percentage_preset_does_not_move_existing_adjustments(self):
    line = EstimateService.add_adjustment_line(self.estimate, self.pct_scheme.pk, target_ids=[])
    before = line.total_amount
    self.pct_scheme.rate = Decimal('99.00'); self.pct_scheme.save()
    recompute_adjustments(self.estimate)
    line.refresh_from_db()
    self.assertEqual(line.total_amount, before)
```

(Adapt the creation call to the actual service method name in `apps/estimates/services.py:546` context — copy its existing test's invocation from `tests/test_adjustment_lines.py`.)
- [ ] **Step 2: Run — fail** (amount moves today): `python manage.py test tests.test_adjustment_lines --noinput`
- [ ] **Step 3–4: Implement, run same suite.**
- [ ] **Step 5: Commit** `feat(estimates,invoicing): adjustment lines snapshot their percent; scheme FK is provenance`

### Task 6: Wizard + document-service branch points

**Files:**
- Modify: `apps/core/wizard.py` (`_uniform_scheme_bundle` ~`:149-175` → uniform iff all tasks share `(rate, unit_label, modifier-snapshot-set)`; `_atom_category` ~`:88-92` → `task.effective_accounting_category` (unchanged name, new source)), `apps/estimates/services.py` (~`:1045-1077`, `:1234-1242`: est qty/price/units from task fields), `apps/invoicing/services.py` (~`:551-562` `qty_source_label` branches on `task.qty_source`, delete the dead `'flat fee'` fallback; `:1137-1150` actual qty/price from task)
- Test: update `tests/test_wizard_bundle_summary.py`, `tests/test_api_invoicing.py` (targeted classes only)

**Interfaces:**
- Consumes: Task 2 compute methods
- Produces: wizard pool/lines fully scheme-free; `sub_info` labels driven by `qty_source`

- [ ] **Step 1: Failing test** — two tasks with identical `(rate, unit_label, modifiers)` but different `source_scheme` values bundle uniformly (today they would not):

```python
def test_bundle_uniform_on_money_not_provenance(self):
    # two tasks, same rate/unit/modifiers, source_scheme=None on one
    units, qty, price = EstimateWizardService._uniform_scheme_bundle([t1, t2])
    self.assertEqual((units, qty, price), ('hour', Decimal('5.00'), Decimal('95.00')))
```

- [ ] **Step 2–4: Fail → implement → pass:** `python manage.py test tests.test_wizard_bundle_summary tests.test_api_invoicing --noinput`
- [ ] **Step 5: Commit** `refactor(wizard): bundle uniformity and labels read task money, not schemes`

### Task 7: Rate-scheme API — retire/filters/default, supersede flow removed

**Files:**
- Modify: `apps/api/rate_schemes/views.py` (delete `supersede` action + the 409 `supersede_url` shaping ~`:44-57`; add `POST {id}/retire/` and `POST {id}/reactivate/` (200 + `{'message': ...}`); list filters: `include_inactive`, `task_applicable=true` → `exclude(algorithm=PERCENTAGE).filter(is_active=True)`), `apps/api/rate_schemes/serializers.py` (expose `is_active`; drop `replaced_by`/`replaced_at`), `apps/api/settings` surface for `default_rate_scheme` Configuration key (follow the existing settings-endpoint pattern for keys in `docs/designs/data-constraints.md` §1.1)
- Test: update `tests/test_api_rate_schemes.py`

**Interfaces:**
- Produces: `POST /api/rate-schemes/{id}/retire/`; `GET /api/rate-schemes/?include_inactive=true`; `default_rate_scheme` readable/writable via `/api/settings/` (CanManageConfig); PATCH on a referenced scheme returns 200 (no more 409)

- [ ] **Steps 1–4 (TDD):** tests: retire flips flag + drops the scheme from default list and `task_applicable`; PATCH on a stamped-referenced scheme succeeds; `default_rate_scheme` round-trips through settings; retiring the default clears the key (assert `Configuration.objects.get(key='default_rate_scheme').value == ''`). Run: `python manage.py test tests.test_api_rate_schemes tests.test_api_settings --noinput`
- [ ] **Step 5: Commit** `feat(api): rate-scheme retire/reactivate + default preset; supersede endpoint removed`

### Task 8: Task API — money fields, stamping on create, permission gating

**Files:**
- Modify: `apps/api/tasks/serializers.py` (expose `qty_source`, `rate`, `unit_label`, `accounting_category`, `source_scheme`, `source_scheme_name`; keep `effective_rate`, `computed_charge`, `actual_hours` working from task fields; delete `scheme_algorithm`/`scheme_unit_label` in favor of the task fields — grep `frontend/src` for both names and fix consumers in Task 12), `apps/api/mixins.py` ~`:331`, `apps/api/tasks/views.py` (create accepts `rate_scheme` (preset id) → server-side `stamp_from_scheme`; money-field writes require `CanManageJobOrPM` or `can_manage_financials` — everyone else gets stamp-only)
- Test: update `tests/test_api_tasks.py` (add a `TaskMoneyPermissionTest` class)

**Interfaces:**
- Produces: worker POST with `{'rate_scheme': id}` → stamped task, 201; worker POST/PATCH containing `rate`/`accounting_category`/`active_modifiers`/`qty_source`/`unit_label` → 403; PM/financials PATCH of the same → 200. AC remains **required** at creation (serializer `required=True` against the nullable column — Phase 3 relaxes).

- [ ] **Steps 1–4 (TDD):** permission matrix test (worker stamp ok / worker money 403 / PM money ok / financials money ok / unauthenticated 401), stamp-on-create fields assertion. Run: `python manage.py test tests.test_api_tasks --noinput`
- [ ] **Step 5: Commit** `feat(api): task money block exposed; workers stamp presets only`

### Task 9: validate_data for the new shapes

**Files:**
- Modify: `apps/core/management/commands/validate_data.py` — modifier-shape check (~`:319-338`) now requires list-of-dicts with `key`/`percent` on tasks and key-lists on nothing; scheme checks (~`:436-452`) drop frozen/supersession assertions, keep AC/negative-rate/hour-pin; new task checks: `qty_source` in choices; `rate` non-negative when set; task with `source_scheme` whose scheme was deleted is fine (SET_NULL) — no check
- Test: update `tests/test_validate_data.py` (task/scheme classes only)

- [ ] **Steps 1–4 (TDD)**, run `python manage.py test tests.test_validate_data --noinput`
- [ ] **Step 5: Commit** `refactor(validate_data): task money-block checks; supersession checks removed`

### Task 10: Converter emits task money

**Files:**
- Modify: `nealsdata/converter/build.py` — every emitted `jobs.task` fixture gains `qty_source`/`rate`/`unit_label`/`accounting_category`/`source_scheme` (values from the scheme the converter already resolves; modifiers resolved to snapshots)
- Test: `tests/test_neals_builders.py` (update fixture-shape assertions)

- [ ] **Steps 1–4 (TDD):** update the builder tests' expected task dicts first, watch them fail, implement. **Never** regenerate or run against `nealsmall.json`; use `datasets/converted.json` flows only. Run: `python manage.py test tests.test_neals_builders tests.test_neals_parsing --noinput`
- [ ] **Step 5: Commit** `feat(converter): tasks carry their money block`

### Task 11: Frontend — RateSchemeManager

**Files:**
- Modify: `frontend/src/components/RateSchemeManager.svelte` (delete `startSupersede`/409 affordance/`include_superseded` ~`:102-114,159-178,383-385`; add Active column + Retire/Reactivate buttons (buttons act — no confirm, it's reversible); Edit/Delete no longer hidden when referenced (delete may still 409 via ServiceItem PROTECT → surface through `triageError`); add "Default preset" picker bound to `/api/settings/` `default_rate_scheme`)
- Test: `frontend/tests/components/RateSchemeManager.test.js` (replace supersession cases with retire/default cases; delete the stale `algorithm: 'flat_fee'` fixtures noted in the exploration — also in `WorkItemForm.test.js`)

- [ ] **Steps 1–4 (TDD):** `cd frontend && npm run test:run -- RateSchemeManager` red → implement → green.
- [ ] **Step 5: Commit** `feat(frontend): preset manager — retire/reactivate + default picker, supersession UI removed`

### Task 12: Frontend — WorkItemForm + TaskDetailPage

**Files:**
- Modify: `frontend/src/components/WorkItemForm.svelte` (preset dropdown prefilled from `default_rate_scheme`; picking stamps rate/units/AC into visible fields; fields disabled unless `can_manage` — consume the serializer's `can_manage` flag per `JobScopedCanManageMixin`; modifier checkboxes read the **selected preset's** definitions and submit snapshots), `frontend/src/routes/**/TaskDetailPage.svelte` (~`:282-288, :429, :448`: display task money fields; `Scheme:` line becomes a `source_scheme_name` provenance chip; stat chips branch on `qty_source`), `frontend/src/lib/taskTotals.js` (~`:40-51`: branch on `task.qty_source`)
- Test: `frontend/tests/components/WorkItemForm.test.js` + a `TaskDetailPage` display test

- [ ] **Steps 1–4 (TDD):** `cd frontend && npm run test:run` for the two files red → implement → green. Grep `frontend/src` for `scheme_algorithm|scheme_unit_label|rate_scheme_detail` and migrate every consumer found.
- [ ] **Step 5: Commit** `feat(frontend): task forms stamp presets; task detail shows the money block`

### Task 13: Full verification — fresh DB

- [ ] **Step 1:** `python manage.py test --noinput` (NO `--keepdb` — migrations changed) with output to a file; gate on the `OK`/`FAILED` summary line and `Ran N tests`, never the pipe exit code. Fix all fallout (expected clusters: acceptance/CO tests still constructing scheme-priced tasks, serializer snapshot tests).
- [ ] **Step 2:** `cd frontend && npm run test:run` — full Vitest suite green.
- [ ] **Step 3: Commit** `test: suite green on task-owned money phase 1`

### Task 14: E2E

**Files:**
- Create: `e2e/specs/settings/rate-scheme-presets.spec.js` (manager: edit a referenced preset succeeds; retire hides it from the task-create dropdown; set default → new-task form opens with it preselected), extend the existing job/task spec with: worker creates a stamped task and sees no money inputs; PM edits the rate and the task detail shows the new rate with the provenance chip

- [ ] **Steps 1–3:** write specs, run `cd e2e && npx playwright test rate-scheme-presets` (own DB/ports; dev servers may stay up), fix, commit `test(e2e): preset retire/default + stamped task creation`

### Task 15: Docs

**Files:**
- Modify: `docs/designs/estimates-and-prices.md` (§2 RateScheme → preset semantics; delete supersession §; rewrite §10 AC pass-through table rows for Task; note adjustment_percent), `docs/designs/jobs-and-tasks.md` (Task field table + money block), `docs/designs/architecture-and-conventions.md` (mixin/serializer notes for money-field gating), `docs/designs/data-constraints.md` (Task constraints; RateScheme constraints minus frozen; `default_rate_scheme` key in §1.1), `docs/designs/users-and-permissions.md` (money-field permission rows)

- [ ] **Step 1:** Update all five docs in one pass; each section states current behavior only (no changelog prose beyond the docs' existing dating conventions).
- [ ] **Step 2: Commit** `docs(designs): task-owned money phase 1 reference updates`

---

## Self-review notes (done at write time)

- Spec §1 → Tasks 1–3, 8; §2 → Tasks 4, 7, 11; §5 → Task 5; §6 → Task 8, 12; §3/§4/§7/§8/§9 deliberately out of phase (roadmap).
- Later-phase dependency check: Phase 2's crystallization writes task money directly (Task 2's constructors allow scheme-less tasks — verified by `test_task_money_compute`); Phase 3 needs only serializer `required=False` flips (Task 8 keeps the column nullable); Phase 4 rides `rate=None` tasks (Task 2's zero-rate rule).
- Known intentional gap: `est_worker_time`/`hours_pair_fill` behavior unchanged (keyed on `unit_label == 'hour'`, now a task field — Task 3 wires it, no semantic change).

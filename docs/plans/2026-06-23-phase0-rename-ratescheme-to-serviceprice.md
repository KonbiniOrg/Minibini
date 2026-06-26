# Phase 0 — Rename `RateScheme` → `ServicePrice` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the `RateScheme` model to `ServicePrice` across the entire stack (model, `db_table`, PK, FK fields, API, frontend, tests, fixtures) as a pure mechanical refactor with **zero behavior change**.

**Architecture:** A rename cannot be committed half-done — a partially renamed backend fails to import and the test suite goes red. So the backend is renamed in one coordinated task that ends with the full suite green; the frontend is a second task; a verification sweep is the third. This is Phase 0 of the larger spec (`docs/plans/2026-06-23-service-price-list-and-percentage-adjustments.md`); doing the rename first means Phases 1–2 are authored natively against `ServicePrice` and never re-touched by a late rename.

**Tech Stack:** Django 5.2 / DRF / MySQL backend; Svelte 5 + Vitest frontend; pytest-style Django `TestCase` suite.

## Global Constraints

- **NEVER write to the dev DB.** Do not run `python manage.py migrate`, `loaddata`, `shell`, or any ORM/SQL write. Migrations are verified via the **test DB only** (tests apply migrations automatically) and `makemigrations --check --dry-run` (read-only). (`CLAUDE.md`)
- **Migrations are hand-written**, not generated — interactive `makemigrations` rename prompts (`y/N`) are not supported in this environment.
- **No behavior change.** This phase only renames symbols. Existing tests are the regression net; they should pass unchanged except for the renamed identifiers.
- **Do not run the Django test suite from multiple agents in parallel** — shared MySQL test DB will deadlock. One agent runs tests at a time. (`CLAUDE.md`)
- **macOS `sed`** requires an explicit backup-suffix arg: `sed -i ''`. All `sed` commands below use that form.
- **Final name:** model `ServicePrice`, FK field `service_price`, PK `service_price_id`, `db_table='service_prices'`, related_name on the self-FK unchanged (`replaces`), API route `/api/service-prices/`, package `apps/api/service_prices/`, UI label "Services". Bare-`scheme` symbols that are NOT `rate_scheme`/`RateScheme` (`SchemeSupersededError`, `allow_superseded_scheme`) are intentionally **left as-is** — they're out of scope for this FK/model rename.

---

## File Structure

Renamed/touched units:

- `apps/jobs/models.py` — `RateScheme` class → `ServicePrice`; PK + Meta; FK fields on `Task`, `PlanTask`.
- `apps/jobs/migrations/0044_rename_ratescheme_to_serviceprice.py` — **create**.
- `apps/estimates/migrations/0026_rename_tasktemplate_rate_scheme.py` — **create**.
- `apps/estimates/models.py` — `TaskTemplate.rate_scheme` FK + `to=` string.
- Backend reference modules (sed): `apps/jobs/services.py`, `apps/jobs/financials.py`, `apps/core/services.py`, `apps/core/wizard.py`, `apps/core/management/commands/validate_data.py`, `apps/estimates/services.py`, `apps/estimates/carry_over.py`, `apps/invoicing/services.py`, `apps/api/mixins.py`, `apps/api/jobs/views.py`, `apps/api/plan_tasks/serializers.py`, `apps/api/tasks/serializers.py`, `apps/api/templates_config/serializers.py`, `apps/api/worksheets/serializers.py`, `apps/api/worksheets/views.py`.
- API package: `apps/api/rate_schemes/` → `apps/api/service_prices/` (dir rename); `apps/api/urls.py` (import, route, basename, api-root listing).
- `tests/` — 107 files (bulk sed).
- Fixtures: `fixtures/unit_test_data.json`, `fixtures/jobs_basic_data.json`, `fixtures/large_datasets/nealsmall.json`, `fixtures/large_datasets/nealseed.json`.
- Frontend: `frontend/src/components/RateSchemeManager.svelte` → `ServicePriceManager.svelte` (+ test), `frontend/src/components/TaskTemplateManager.svelte`, `frontend/src/components/WorkItemForm.svelte`, `frontend/src/routes/SettingsPage.svelte`, and their tests.

---

## Task 1: Branch

- [ ] **Step 1: Create the feature branch**

The current branch is `feature/qbo-stuff`. Start the rename on its own branch off `main`.

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git checkout main
git pull --ff-only
git checkout -b feature/serviceprice-rename
```

Expected: on a clean new branch `feature/serviceprice-rename`.

---

## Task 2: Backend rename (model + migrations + all Python + fixtures)

**Files:** all backend modules and fixtures listed in File Structure; two new migration files.

**Interfaces:**
- Produces: model `apps.jobs.models.ServicePrice` with PK `service_price_id`, `db_table='service_prices'`; FK `service_price` on `Task`, `PlanTask`, `TaskTemplate`; API `ServicePriceViewSet` / `ServicePriceSerializer` at `/api/service-prices/`. All later phases consume these names.

- [ ] **Step 1: Rename the model class, PK, Meta, and FK fields in `apps/jobs/models.py`**

Apply these exact edits:

- `class RateScheme(models.Model):` → `class ServicePrice(models.Model):`
- `rate_scheme_id = models.AutoField(primary_key=True)` → `service_price_id = models.AutoField(primary_key=True)`
- In `Meta`: `db_table = 'rate_schemes'` → `db_table = 'service_prices'`
- On `Task`: the FK currently
  ```python
  rate_scheme = models.ForeignKey(
      'jobs.RateScheme',
      on_delete=models.PROTECT,
      related_name='task_set',
  )
  ```
  becomes
  ```python
  service_price = models.ForeignKey(
      'jobs.ServicePrice',
      on_delete=models.PROTECT,
      related_name='task_set',
  )
  ```
- On `PlanTask`: `rate_scheme = models.ForeignKey('jobs.RateScheme', on_delete=models.PROTECT,)` → `service_price = models.ForeignKey('jobs.ServicePrice', on_delete=models.PROTECT,)`

- [ ] **Step 2: Update the remaining `rate_scheme*` / `RateScheme` references inside `apps/jobs/models.py`**

These are attribute accesses, docstrings, and the `copy_fields`/`compute_amount`/`effective_rate`/`effective_accounting_category` bodies, plus `is_referenced`/`reference_counts`/`supersede` docstrings. Bulk-replace within the file:

```bash
cd /Users/drshiny/Documents/konbini/Minibini
sed -i '' 's/rate_scheme_id/service_price_id/g; s/rate_scheme/service_price/g; s/RateScheme/ServicePrice/g' apps/jobs/models.py
```

Note: this also rewrites `copy_fields()`'s `rate_scheme_id=self.rate_scheme_id` → `service_price_id=self.service_price_id` and `PlanTask.compute_amount`'s `self.rate_scheme_id` guard → `self.service_price_id`. Verify `self.service_price.accounting_category` etc. read correctly afterward.

- [ ] **Step 3: Update `apps/estimates/models.py` `TaskTemplate` FK**

```bash
sed -i '' "s/'jobs.RateScheme'/'jobs.ServicePrice'/g; s/rate_scheme/service_price/g; s/RateScheme/ServicePrice/g" apps/estimates/models.py
```

This renames the `rate_scheme` FK → `service_price`, its `to='jobs.ServicePrice'`, and the `RateScheme._flat_fee_price(...)` call in `TaskTemplate.clean()` → `ServicePrice._flat_fee_price(...)`. (The flat-fee validation logic itself is removed in Phase 1, not here.)

- [ ] **Step 4: Create `apps/jobs/migrations/0044_rename_ratescheme_to_serviceprice.py`**

```python
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0043_job_project_manager'),
    ]

    operations = [
        migrations.RenameModel(old_name='RateScheme', new_name='ServicePrice'),
        migrations.AlterModelTable(name='serviceprice', table='service_prices'),
        migrations.RenameField(
            model_name='serviceprice',
            old_name='rate_scheme_id',
            new_name='service_price_id',
        ),
        migrations.RenameField(
            model_name='task', old_name='rate_scheme', new_name='service_price',
        ),
        migrations.RenameField(
            model_name='plantask', old_name='rate_scheme', new_name='service_price',
        ),
    ]
```

- [ ] **Step 5: Create `apps/estimates/migrations/0026_rename_tasktemplate_rate_scheme.py`**

```python
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('estimates', '0025_rename_price_list_item_changeorderlineitem_inventory_item_and_more'),
        ('jobs', '0044_rename_ratescheme_to_serviceprice'),
    ]

    operations = [
        migrations.RenameField(
            model_name='tasktemplate',
            old_name='rate_scheme',
            new_name='service_price',
        ),
    ]
```

- [ ] **Step 6: Bulk-rename all backend reference modules (non-migration, non-test)**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
grep -rl "RateScheme\|rate_scheme" apps/ --include="*.py" \
  | grep -v "/migrations/" \
  | grep -v "apps/jobs/models.py" \
  | grep -v "apps/estimates/models.py" \
  | while read f; do
      sed -i '' 's/rate_scheme_id/service_price_id/g; s/rate_scheme/service_price/g; s/RateScheme/ServicePrice/g' "$f"
    done
```

This covers `apps/jobs/services.py`, `apps/jobs/financials.py`, `apps/core/services.py`, `apps/core/wizard.py`, `apps/core/management/commands/validate_data.py`, `apps/estimates/services.py`, `apps/estimates/carry_over.py`, `apps/invoicing/services.py`, `apps/api/mixins.py`, and the API serializers/views that reference the FK. Note `TaskService.create_direct`'s `rate_scheme_id=` parameter and callers are renamed together, so the keyword stays consistent.

- [ ] **Step 7: Rename the API package directory and its contents**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git mv apps/api/rate_schemes apps/api/service_prices
sed -i '' 's/RateSchemeViewSet/ServicePriceViewSet/g; s/RateSchemeSerializer/ServicePriceSerializer/g; s/RateScheme/ServicePrice/g; s/rate_scheme_id/service_price_id/g; s/rate_scheme/service_price/g' apps/api/service_prices/views.py apps/api/service_prices/serializers.py
```

Then in `apps/api/service_prices/views.py`, update the hard-coded supersede URL string `/api/rate-schemes/{instance.pk}/supersede/` → `/api/service-prices/{instance.pk}/supersede/`:

```bash
sed -i '' 's#/api/rate-schemes/#/api/service-prices/#g' apps/api/service_prices/views.py
```

- [ ] **Step 8: Update `apps/api/urls.py` (import, route, basename, api-root listing)**

```bash
sed -i '' \
  -e 's#from apps.api.rate_schemes.views import RateSchemeViewSet#from apps.api.service_prices.views import ServicePriceViewSet#' \
  -e "s/RateSchemeViewSet/ServicePriceViewSet/g" \
  -e "s#'rate-schemes': '/api/rate-schemes/'#'service-prices': '/api/service-prices/'#" \
  -e "s#r'rate-schemes'#r'service-prices'#" \
  -e "s/basename='rate-scheme'/basename='service-price'/" \
  apps/api/urls.py
```

Verify the three lines (import, api-root dict entry, `router.register`) now read `service-prices` / `ServicePriceViewSet` / `basename='service-price'`.

- [ ] **Step 9: Bulk-rename the test suite**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
grep -rl "RateScheme\|rate_scheme\|rate-schemes" tests/ apps/schedule/tests/ \
  | while read f; do
      sed -i '' 's#/api/rate-schemes/#/api/service-prices/#g; s/rate_scheme_id/service_price_id/g; s/rate_scheme/service_price/g; s/RateScheme/ServicePrice/g' "$f"
    done
```

- [ ] **Step 10: Rename the test modules whose filenames carry the old name**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git mv tests/test_rate_scheme.py tests/test_service_price.py
git mv tests/test_rate_scheme_api.py tests/test_service_price_api.py
```

- [ ] **Step 11: Bulk-rename fixtures**

Django fixtures reference the model by lowercased label (`jobs.ratescheme`) and the FK by field name. Replace both, plus the API-less data:

```bash
cd /Users/drshiny/Documents/konbini/Minibini
for f in fixtures/unit_test_data.json fixtures/jobs_basic_data.json \
         fixtures/large_datasets/nealsmall.json fixtures/large_datasets/nealseed.json; do
  sed -i '' 's/jobs\.ratescheme/jobs.serviceprice/g; s/"rate_scheme"/"service_price"/g; s/"rate_scheme_id"/"service_price_id"/g' "$f"
done
```

Note: `RateScheme.pk` in fixtures lives under `"pk"`, not a named field, so the model-label and FK-field replacements above are sufficient. The `service_price`'s own `fields` block does not contain `rate_scheme_id`.

- [ ] **Step 12: Verify no backend stragglers remain**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
grep -rn "RateScheme\|rate_scheme\|rate-schemes\|jobs.ratescheme" apps/ tests/ fixtures/ --include="*.py" --include="*.json" | grep -v "/migrations/0"
```

Expected: **no output** (the only allowed remaining `RateScheme`/`rate_scheme` references are inside *historical* migration files `apps/*/migrations/0...`, which must NOT be edited). If anything else prints, hand-fix it.

- [ ] **Step 13: Verify migration state is consistent (read-only)**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
python manage.py makemigrations --check --dry-run
```

Expected: `No changes detected` (the hand-written 0044/0026 fully describe the rename). If it reports changes, the model edits and migration operations disagree — reconcile before continuing. **Do not** run `migrate`.

- [ ] **Step 14: Run the full backend test suite**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
python manage.py test
```

Expected: PASS (same pass/fail counts as before the rename — no behavior changed). Investigate any failure as a missed reference, not a logic change.

- [ ] **Step 15: Commit**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git add -A
git commit -m "refactor: rename RateScheme to ServicePrice (model, FK, API, tests, fixtures)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Frontend rename

**Files:** `frontend/src/components/RateSchemeManager.svelte` (→ `ServicePriceManager.svelte`), `TaskTemplateManager.svelte`, `WorkItemForm.svelte`, `frontend/src/routes/SettingsPage.svelte`, and the matching `frontend/tests/components/*.test.js`.

**Interfaces:**
- Consumes: the renamed API route `/api/service-prices/` produced in Task 2.

- [ ] **Step 1: Rename the component and its test file**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git mv frontend/src/components/RateSchemeManager.svelte frontend/src/components/ServicePriceManager.svelte
git mv frontend/tests/components/RateSchemeManager.test.js frontend/tests/components/ServicePriceManager.test.js
```

- [ ] **Step 2: Bulk-rename identifiers and API paths across the frontend**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
grep -rl "RateScheme\|rate_scheme\|rateScheme\|rate-schemes" frontend/src frontend/tests \
  | while read f; do
      sed -i '' 's#/api/rate-schemes/#/api/service-prices/#g; s/RateScheme/ServicePrice/g; s/rateScheme/servicePrice/g; s/rate_scheme/service_price/g' "$f"
    done
```

This rewrites the component import in `SettingsPage.svelte`, the `<ServicePriceManager />` usage, and the `rate_scheme` / `rateScheme` field bindings and fetch URLs in `TaskTemplateManager.svelte` and `WorkItemForm.svelte`.

- [ ] **Step 3: Verify no frontend stragglers**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
grep -rn "RateScheme\|rate_scheme\|rateScheme\|rate-schemes" frontend/src frontend/tests
```

Expected: **no output**. Hand-fix anything that prints (e.g. a user-visible "Rate Scheme" heading string → "Service" — update copy as appropriate).

- [ ] **Step 4: Run the frontend test suite**

```bash
cd /Users/drshiny/Documents/konbini/Minibini/frontend
npm run test:run
```

Expected: PASS (no watch mode). Fix any failure as a missed reference.

- [ ] **Step 5: Build check**

```bash
cd /Users/drshiny/Documents/konbini/Minibini/frontend
npm run build
```

Expected: build succeeds (Svelte 5 strict mode catches any dangling identifier).

- [ ] **Step 6: Commit**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git add -A
git commit -m "refactor: rename RateScheme to ServicePrice in Svelte SPA

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Verification sweep + doc pointer

**Files:** `docs/designs/estimates-and-prices.md` (pointer note only).

- [ ] **Step 1: Whole-repo straggler sweep (excluding historical migrations and node_modules)**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
grep -rn "RateScheme\|rate_scheme\|rateScheme\|rate-schemes\|jobs.ratescheme" . \
  --include="*.py" --include="*.js" --include="*.svelte" --include="*.json" \
  | grep -v "/migrations/0" | grep -v "node_modules" | grep -v "/venv/"
```

Expected: **no output**. Historical migration files (`/migrations/0*.py`) legitimately retain the old name and are excluded — do not edit them.

- [ ] **Step 2: Add a pointer note to the durable doc**

The full rewrite of `docs/designs/estimates-and-prices.md` (RateScheme→ServicePrice prose, the reframe, percentage adjustments) happens in Phase 1/2 per the spec's §11. For now, add a single note at the top of §2 so the doc isn't silently wrong:

In `docs/designs/estimates-and-prices.md`, immediately under the `## 2. RateScheme` heading, insert:

```markdown
> **Rename (2026-06):** the model is now `ServicePrice` (`db_table='service_prices'`,
> FK field `service_price`, API `/api/service-prices/`). This section still uses the
> old name `RateScheme` pending the Phase 1 reframe rewrite
> (`docs/plans/2026-06-23-service-price-list-and-percentage-adjustments.md`).
```

- [ ] **Step 3: Re-run both suites as a final gate**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
python manage.py test
cd frontend && npm run test:run
```

Expected: both PASS.

- [ ] **Step 4: Commit**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git add -A
git commit -m "docs: note ServicePrice rename in estimates-and-prices reference

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage (Phase 0 scope = §2 item 0 + §12 Phase 0 of the parent spec):**
- Model class rename → Task 2 Step 1. ✓
- `db_table` rename → Task 2 Step 1 + migration Step 4 (`AlterModelTable`). ✓
- PK rename → Task 2 Step 1 + migration Step 4 (`RenameField` on `service_price_id`). ✓
- FK field renames (`Task`, `PlanTask`, `TaskTemplate`) → Steps 1, 3 + migrations 4, 5. ✓
- API route + package + classes → Task 2 Steps 7, 8. ✓
- Tests + fixtures → Task 2 Steps 9–11. ✓
- Frontend → Task 3. ✓
- No-behavior-change guarantee → suites green at Steps 14 / Task 3.4 / Task 4.3. ✓

**Placeholder scan:** every step has a concrete command or exact edit. No TBDs.

**Type/name consistency:** `ServicePrice`, `service_price`, `service_price_id`, `service_prices`, `/api/service-prices/`, `ServicePriceViewSet`, `ServicePriceSerializer`, `ServicePriceManager.svelte` used consistently across tasks. Self-FK `replaces`/`replaced_by` deliberately unchanged. Bare-`scheme` symbols (`SchemeSupersededError`, `allow_superseded_scheme`) deliberately unchanged (Global Constraints).

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-06-23-phase0-rename-ratescheme-to-serviceprice.md`. After this lands green, the Phase 1 (service-price reframe) and Phase 2 (percentage adjustments) plans should be generated against the new `ServicePrice` names.
</content>

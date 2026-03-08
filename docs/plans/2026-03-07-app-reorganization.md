# App Reorganization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reorganize models across apps per the model inventory, add short db_table names, create new estimates app, reset all migrations, and update fixtures. No new models or business logic.

**Architecture:** Move models between existing apps and into a new estimates app. Mechanical moves, import updates, and migration reset. The existing development database will need to be recreated from scratch after this.

**Tech Stack:** Django 5.2+, MySQL, Python 3.12

**Reference:** `docs/plans/2026-03-07-model-inventory.md` — the authoritative source for where each model lands.

---

## Prerequisites

- Working on branch: `feature/model-reorg` (already created)

---

## Task 1: Create the estimates app

**Files:**
- Create: `apps/estimates/__init__.py`
- Create: `apps/estimates/apps.py`
- Create: `apps/estimates/models.py`
- Create: `apps/estimates/admin.py`
- Create: `apps/estimates/views.py`
- Create: `apps/estimates/forms.py`
- Create: `apps/estimates/services.py`
- Create: `apps/estimates/urls.py`
- Create: `apps/estimates/migrations/__init__.py`
- Modify: `minibini/settings.py` — add `'apps.estimates'` to INSTALLED_APPS

**Step 1: Create the app directory and boilerplate files**

```bash
mkdir -p apps/estimates/migrations
touch apps/estimates/__init__.py
touch apps/estimates/migrations/__init__.py
touch apps/estimates/admin.py
touch apps/estimates/views.py
touch apps/estimates/forms.py
touch apps/estimates/services.py
touch apps/estimates/urls.py
```

**Step 2: Create apps/estimates/apps.py**

```python
from django.apps import AppConfig


class EstimatesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.estimates'
```

**Step 3: Create apps/estimates/models.py (empty for now)**

```python
from django.db import models
```

**Step 4: Add to INSTALLED_APPS in minibini/settings.py**

Add `'apps.estimates'` after `'apps.jobs'` in the INSTALLED_APPS list.

**Step 5: Commit**

```
feat: create empty estimates app
```

---

## Task 2: Move models to target apps

This is the largest task. All model moves happen together because cross-references make incremental moves impractical. The app will not run until all imports are also updated (Task 3).

**Models moving:**

| Model | From | To |
|---|---|---|
| AbstractWorkContainer | jobs | core |
| Estimate | jobs | estimates |
| EstWorksheet | jobs | estimates |
| EstimateLineItem | jobs | estimates |
| WorkOrderTemplate | jobs | estimates |
| TaskTemplate | jobs | estimates |
| TemplateBundle | jobs | estimates |
| TemplateTaskAssociation | jobs | estimates |
| Material | jobs | inventory |
| PriceListItem | invoicing | inventory |

**Files:**
- Modify: `apps/jobs/models.py` — remove moved models
- Modify: `apps/estimates/models.py` — add models from jobs
- Modify: `apps/core/models.py` — add AbstractWorkContainer
- Modify: `apps/inventory/models.py` — add Material, PriceListItem
- Modify: `apps/invoicing/models.py` — remove PriceListItem

**Step 1: Move AbstractWorkContainer to core/models.py**

Cut the `AbstractWorkContainer` class from `apps/jobs/models.py` and add it to `apps/core/models.py`. It's an abstract model — no db_table needed.

**Step 2: Move estimates models to estimates/models.py**

Cut from `apps/jobs/models.py` and paste into `apps/estimates/models.py`:
- `Estimate`
- `EstWorksheet`
- `EstimateLineItem`
- `WorkOrderTemplate`
- `TaskTemplate`
- `TemplateBundle`
- `TemplateTaskAssociation`

Add the necessary imports at the top of estimates/models.py:
```python
from django.db import models
from apps.core.models import BaseLineItem, AbstractWorkContainer
```

Update any ForeignKey string references within these models that pointed to `'jobs.Xyz'` for models that are now in estimates — change to direct model references or update the string to `'estimates.Xyz'`.

**Step 3: Move PriceListItem and Material to inventory/models.py**

Cut `PriceListItem` from `apps/invoicing/models.py` and `Material` from `apps/jobs/models.py`. Add both to `apps/inventory/models.py`.

Update imports at the top of inventory/models.py as needed.

**Step 4: Update ForeignKey string references in all models**

Any ForeignKey that used a string reference to a model that has moved needs updating. Key changes:

- `'jobs.Estimate'` → `'estimates.Estimate'`
- `'jobs.EstWorksheet'` → `'estimates.EstWorksheet'`
- `'jobs.EstimateLineItem'` → `'estimates.EstimateLineItem'`
- `'jobs.WorkOrderTemplate'` → `'estimates.WorkOrderTemplate'`
- `'jobs.TaskTemplate'` → `'estimates.TaskTemplate'`
- `'jobs.TemplateBundle'` → `'estimates.TemplateBundle'`
- `'jobs.TemplateTaskAssociation'` → `'estimates.TemplateTaskAssociation'`
- `'invoicing.PriceListItem'` → `'inventory.PriceListItem'`
- `'jobs.Material'` → `'inventory.Material'`

Search all models.py files for these string references. Also check for `related_name` conflicts.

**Step 5: Commit**

```
refactor: move models to target apps per reorganization plan
```

---

## Task 3: Update all imports across the codebase

Every file that imports a moved model needs updating. This task covers views, services, forms, signals, admin, and URL files.

**Files to update (based on cross-app import mapping):**

### For models moved to estimates:

- `apps/jobs/views.py` — update imports of Estimate, EstWorksheet, EstimateLineItem, WorkOrderTemplate, TaskTemplate, TemplateBundle, TemplateTaskAssociation
- `apps/jobs/services.py` — update imports of Estimate, EstWorksheet, EstimateLineItem, WorkOrderTemplate, TaskTemplate
- `apps/jobs/forms.py` — update any imports of moved models
- `apps/jobs/signals.py` — update import of EstWorksheet (line 21)
- `apps/search/services.py` — update imports of Estimate, EstWorksheet, EstimateLineItem
- `apps/core/views.py` — check for any estimate-related imports

### For PriceListItem moved to inventory:

- `apps/invoicing/models.py` — remove PriceListItem, update any internal references
- `apps/invoicing/forms.py` — update PriceListItem import
- `apps/invoicing/views.py` — update PriceListItem import if present
- `apps/purchasing/forms.py` — update PriceListItem import (line 5)
- `apps/jobs/services.py` — update PriceListItem import (line 18)
- `apps/inventory/services.py` — update PriceListItem import (line 4)
- `apps/inventory/forms.py` — update PriceListItem import (line 2)
- `apps/inventory/views.py` — update PriceListItem import (line 3)
- `apps/search/services.py` — update PriceListItem import

### For Material moved to inventory:

- `apps/jobs/models.py` — remove Material, check for internal references
- Any views/forms that reference Material

### For AbstractWorkContainer moved to core:

- `apps/jobs/models.py` — import from core instead of defining locally
- `apps/estimates/models.py` — already importing from core (set up in Task 2)

**Step 1: Update each file listed above**

Use grep to find any remaining references:
```bash
grep -rn "from apps.jobs.models import" apps/ tests/ --include="*.py"
grep -rn "from apps.invoicing.models import" apps/ tests/ --include="*.py"
grep -rn "from apps.jobs import" apps/ tests/ --include="*.py"
```

Verify every import of a moved model now points to the correct app.

**Step 2: Update test imports**

```bash
grep -rn "from apps.jobs.models import" tests/ --include="*.py"
grep -rn "from apps.invoicing.models import" tests/ --include="*.py"
```

Update all test files that import moved models.

**Step 3: Commit**

```
refactor: update all imports for moved models
```

---

## Task 4: Move views, forms, services, and URL routes for estimates

The HTML views, forms, services, and URL patterns that deal with estimates, worksheets, and templates need to move from jobs to estimates.

**Step 1: Identify which views to move**

Grep `apps/jobs/views.py` for functions that operate on Estimate, EstWorksheet, EstimateLineItem, WorkOrderTemplate, TaskTemplate, TemplateBundle, or TemplateTaskAssociation. Move those functions to `apps/estimates/views.py`.

**Step 2: Move corresponding forms**

Move estimate/worksheet/template-related forms from `apps/jobs/forms.py` to `apps/estimates/forms.py`.

**Step 3: Move corresponding services**

Move `EstimateGenerationService` and any other estimate/template-related service classes from `apps/jobs/services.py` to `apps/estimates/services.py`.

**Step 4: Move URL patterns**

Move estimate/worksheet/template URL patterns from `apps/jobs/urls.py` to `apps/estimates/urls.py`. Add `path('estimates/', include('apps.estimates.urls'))` to `minibini/urls.py`.

**Step 5: Move signals**

The signals `estimate_status_changed_for_worksheet` and `estimate_status_changed_for_job` should move to `apps/estimates/signals.py`. The `estimate_accepted` signal (which triggers earmarking) should also move. Update `apps/estimates/apps.py` with a `ready()` method to import the signals. Remove signal registration from `apps/jobs/apps.py` if no signals remain there.

**Step 6: Update all internal imports**

After moving, update any imports within the moved files that still reference `apps.jobs`.

**Step 7: Verify with grep**

```bash
grep -rn "from apps.jobs" apps/estimates/ --include="*.py"
```

Estimates will legitimately import from jobs (EstWorksheet references Task/TaskBundle, Estimate references Job). This check verifies no imports of *moved* models from their old locations — e.g., no `from apps.jobs.models import Estimate`.

**Step 8: Commit**

```
refactor: move estimate views, forms, services, and URLs to estimates app
```

---

## Task 5: Move PriceListItem views/forms to inventory

**Step 1: Move PriceListItem views from invoicing to inventory**

Move price list item view functions from `apps/invoicing/views.py` to `apps/inventory/views.py`.

**Step 2: Move PriceListItem forms**

Move related forms from `apps/invoicing/forms.py` to `apps/inventory/forms.py`.

**Step 3: Move URL patterns**

Move price list item URL patterns from `apps/invoicing/urls.py` to `apps/inventory/urls.py`.

**Step 4: Update imports and commit**

```
refactor: move price list item views and forms to inventory app
```

---

## Task 6: Add db_table to all models

Add `db_table` in the `Meta` class of every concrete model.

**apps/core:**

| Model | db_table |
|---|---|
| User | `auth_user` (already set) |
| Configuration | `config` |
| EmailRecord | `email_record` (already set) |
| TempEmail | `temp_email` (already set) |
| LineItemType | `li_types` |

**apps/jobs:**

| Model | db_table |
|---|---|
| Job | `jobs` |
| WorkOrder | `workorders` |
| Task | `tasks` |
| TaskBundle | `task_bundles` |
| Blep | `bleps` |

**apps/estimates:**

| Model | db_table |
|---|---|
| Estimate | `estimates` |
| EstWorksheet | `worksheets` |
| EstimateLineItem | `est_li` |
| WorkOrderTemplate | `wo_templates` |
| TaskTemplate | `task_templates` |
| TemplateBundle | `template_bundles` |
| TemplateTaskAssociation | `template_task_assoc` |

**apps/contacts:**

| Model | db_table |
|---|---|
| Contact | `contacts` |
| Business | `businesses` |
| PaymentTerms | `terms` |

**apps/invoicing:**

| Model | db_table |
|---|---|
| Invoice | `invoices` |
| InvoiceLineItem | `invoice_li` |

**apps/purchasing:**

| Model | db_table |
|---|---|
| PurchaseOrder | `pos` |
| Bill | `bills` |
| PurchaseOrderLineItem | `po_li` |
| BillLineItem | `bill_li` |

**apps/inventory:**

| Model | db_table |
|---|---|
| Earmark | `earmarks` |
| InventoryAdjustment | `inv_adjustments` |
| PriceListItem | `price_list` |
| Material | `materials` |

**Step 1: Add Meta.db_table to each model**

For models that don't have a Meta class, add one:
```python
class Meta:
    db_table = 'short_name'
```

For models that already have a Meta class, add the `db_table` line.

**Step 2: Commit**

```
refactor: add short db_table names to all models
```

---

## Task 7: Delete all migrations and regenerate

**Step 1: Delete all migration files (keep __init__.py)**

```bash
find apps/*/migrations/ -name "*.py" ! -name "__init__.py" -delete
```

**Step 2: Generate fresh migrations**

```bash
python manage.py makemigrations
```

This creates a single 0001_initial.py per app based on the current model definitions. Verify that each app with models gets a migration.

Expected migrations created:
- `apps/core/migrations/0001_initial.py`
- `apps/jobs/migrations/0001_initial.py`
- `apps/estimates/migrations/0001_initial.py`
- `apps/contacts/migrations/0001_initial.py`
- `apps/invoicing/migrations/0001_initial.py`
- `apps/purchasing/migrations/0001_initial.py`
- `apps/inventory/migrations/0001_initial.py`

**Step 3: Verify migrations are complete**

```bash
python manage.py showmigrations
```

All apps should show a single unapplied `0001_initial` migration.

**Step 4: Commit**

```
refactor: delete all migrations and regenerate from current models
```

---

## Task 8: Update all fixture files

Fixtures use `"model": "appname.modelname"` format. Every reference to a moved model needs updating.

**Files:** All 18 fixture files in `fixtures/` directory.

**Replacements:**

| Old reference | New reference |
|---|---|
| `"jobs.estimate"` | `"estimates.estimate"` |
| `"jobs.estworksheet"` | `"estimates.estworksheet"` |
| `"jobs.estimatelineitem"` | `"estimates.estimatelineitem"` |
| `"jobs.workordertemplate"` | `"estimates.workordertemplate"` |
| `"jobs.tasktemplate"` | `"estimates.tasktemplate"` |
| `"jobs.templatebundle"` | `"estimates.templatebundle"` |
| `"jobs.templatetaskassociation"` | `"estimates.templatetaskassociation"` |
| `"invoicing.pricelistitem"` | `"inventory.pricelistitem"` |

**Step 1: Run sed replacements across all fixture files**

```bash
find fixtures/ -name "*.json" -exec sed -i '' \
    -e 's/"jobs\.estimate"/"estimates.estimate"/g' \
    -e 's/"jobs\.estworksheet"/"estimates.estworksheet"/g' \
    -e 's/"jobs\.estimatelineitem"/"estimates.estimatelineitem"/g' \
    -e 's/"jobs\.workordertemplate"/"estimates.workordertemplate"/g' \
    -e 's/"jobs\.tasktemplate"/"estimates.tasktemplate"/g' \
    -e 's/"jobs\.templatebundle"/"estimates.templatebundle"/g' \
    -e 's/"jobs\.templatetaskassociation"/"estimates.templatetaskassociation"/g' \
    -e 's/"invoicing\.pricelistitem"/"inventory.pricelistitem"/g' \
    {} +
```

**Step 2: Verify no stale references remain**

```bash
grep -rn '"jobs\.estimate' fixtures/
grep -rn '"jobs\.estworksheet' fixtures/
grep -rn '"jobs\.estimatelineitem' fixtures/
grep -rn '"jobs\.workordertemplate' fixtures/
grep -rn '"jobs\.tasktemplate' fixtures/
grep -rn '"jobs\.templatebundle' fixtures/
grep -rn '"jobs\.templatetaskassociation' fixtures/
grep -rn '"invoicing\.pricelistitem' fixtures/
```

All should return no results. Also verify Material is not in any fixtures (it uses `jobs.material` — check and update if present).

**Step 3: Verify fixtures load**

```bash
python manage.py loaddata unit_test_data.json
```

Note: This requires a migrated test database. If the dev database hasn't been migrated yet, this will be verified via tests in Task 9.

**Step 4: Commit**

```
refactor: update fixture model references for app reorganization
```

---

## Task 9: Run tests and fix

**Step 1: Run the full test suite**

```bash
python manage.py test
```

Tests create their own database, so migration state doesn't matter for the dev DB.

**Step 2: Fix any failures**

Common issues to expect:
- **Import errors** — missed an import update somewhere. Grep for the old import path and fix.
- **Fixture load errors** — missed a model reference in a fixture. Check the error message for the fixture file and model name.
- **URL resolution errors** — URL names may have changed if views moved. Update `reverse()` calls and template `{% url %}` tags.
- **Signal registration** — if signals didn't get re-registered in the new app's `ready()` method.

**Step 3: Iterate until all tests pass**

Fix one category of failure at a time. After each fix, re-run the full suite.

**Step 4: Final commit**

```
fix: resolve test failures from app reorganization
```

---

## Task 10: Final verification and cleanup

**Step 1: Verify no stale imports**

```bash
grep -rn "from apps.jobs.models import.*Estimate" apps/ tests/ --include="*.py"
grep -rn "from apps.jobs.models import.*WorkOrderTemplate" apps/ tests/ --include="*.py"
grep -rn "from apps.jobs.models import.*TaskTemplate" apps/ tests/ --include="*.py"
grep -rn "from apps.jobs.models import.*Material" apps/ tests/ --include="*.py"
grep -rn "from apps.invoicing.models import.*PriceListItem" apps/ tests/ --include="*.py"
```

All should return no results.

**Step 2: Verify no model reference strings pointing to old locations**

```bash
grep -rn "'jobs\.Estimate'" apps/ --include="*.py"
grep -rn "'jobs\.EstWorksheet'" apps/ --include="*.py"
grep -rn "'invoicing\.PriceListItem'" apps/ --include="*.py"
```

All should return no results.

**Step 3: Run tests one final time**

```bash
python manage.py test
```

All green.

**Step 4: Final commit**

```
chore: cleanup stale references after app reorganization
```

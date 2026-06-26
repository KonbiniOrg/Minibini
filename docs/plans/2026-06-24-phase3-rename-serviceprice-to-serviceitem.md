# Phase 3 — Rename `ServicePrice` → `ServiceItem` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Rename the `ServicePrice` model to `ServiceItem` across the whole stack (model, `db_table`, PK, FK fields, API, frontend, tests, fixtures, durable docs) as a pure mechanical refactor with **zero behavior change**.

**Architecture:** Identical method to Phase 0 (`docs/plans/2026-06-23-phase0-rename-ratescheme-to-serviceprice.md`) — a partial rename won't import, so the backend is renamed in one coordinated commit that ends with the full suite green; the frontend is a second commit; a sweep + docs/memory is the third. This runs on the **same branch** (`feature/serviceprice-rename`); Phases 0–2 are already on it. The source name is now `ServicePrice` (Phase 0's target).

## Global Constraints

- **NEVER write the dev DB.** No `migrate`/`loaddata`/`shell`. Verify via the test DB + `makemigrations --check --dry-run`.
- **Hand-write the rename migrations** (interactive rename prompts unsupported).
- **No behavior change.** Existing tests are the regression net.
- **macOS `sed`** uses `sed -i ''`.
- **Never edit historical migrations** (`apps/*/migrations/0*.py`). `jobs/0044`, `jobs/0045`, `estimates/0026` legitimately hardcode `ServicePrice`/`service_price` and refer to the name valid *at their point in the chain* (the rename happens later, in `jobs/0047`). `jobs/0045`'s `apps.get_model('jobs', 'ServicePrice')` MUST stay.
- **`adjustment_service` stays.** The FK field `adjustment_service` (on `EstimateLineItem`/`InvoiceLineItem`) and `adjustment_service_detail` do NOT contain `service_price`, so the `sed`s below won't touch them — correct, the field keeps its name and just points at the renamed model.
- **Final names:** model `ServiceItem`, FK field `service_item`, PK `service_item_id`, `db_table='service_items'`, API `/api/service-items/`, package `apps/api/service_items/`, basename `service-item`, component `ServiceItemManager.svelte`. UI label text ("Services", "Add Service") is unchanged — it doesn't contain the model name. Bare-`scheme` symbols (`SchemeSupersededError`) remain.

## Surface (from recon, 2026-06-24)

- Backend non-migration (26 files): `apps/jobs/models.py`, `apps/estimates/models.py`, `apps/invoicing/models.py`, `apps/jobs/{services,financials,flat_fee_reframe}.py`, `apps/core/{adjustments,services,wizard}.py`, `apps/core/management/commands/validate_data.py`, `apps/estimates/{services,carry_over}.py`, `apps/invoicing/services.py`, `apps/api/service_prices/{views,serializers}.py`, `apps/api/{mixins,urls}.py`, `apps/api/{estimates,invoicing,jobs,tasks,plan_tasks,templates_config,worksheets}/*.py`, `apps/schedule/tests/test_schedule_service.py`.
- Tests: 111 files under `tests/` (+ the schedule test above).
- Fixtures: `fixtures/unit_test_data.json`, `fixtures/jobs_basic_data.json`, `fixtures/large_datasets/nealsmall.json`, `fixtures/large_datasets/nealseed.json`.
- Frontend (11): `ServicePriceManager.svelte`(→rename), `AdjustmentModal.svelte`, `TaskTemplateManager.svelte`, `WorkItemForm.svelte`, `SettingsPage.svelte`, + 6 test files.
- Docs: `docs/designs/{estimates-and-prices,invoicing-and-expenses,data-constraints,LATER}.md`, `docs/ui-flows/Services-and-Adjustments.md`, the 4 `docs/plans/2026-06-2*` files. Memory: `MEMORY.md` + `project_serviceprice_rename_branch.md`.

---

## Task 1: Backend rename (one coordinated commit)

**Steps**

- [ ] **1. Model edits.** In `apps/jobs/models.py`: `class ServicePrice` → `class ServiceItem`; PK `service_price_id` → `service_item_id`; `Meta.db_table='service_prices'` → `'service_items'`; on `Task` and `PlanTask` the FK `service_price = models.ForeignKey('jobs.ServicePrice', …)` → `service_item = models.ForeignKey('jobs.ServiceItem', …)`. In `apps/estimates/models.py`: `TaskTemplate.service_price` → `service_item`, `to='jobs.ServicePrice'`→`'jobs.ServiceItem'`. In `apps/invoicing/models.py` and `apps/estimates/models.py`: the `adjustment_service` FK `to='jobs.ServicePrice'`→`'jobs.ServiceItem'` (field name stays).

- [ ] **2. Create `apps/jobs/migrations/0047_rename_serviceprice_to_serviceitem.py`:**

```python
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0046_alter_serviceprice_algorithm'),
    ]

    operations = [
        migrations.RenameModel(old_name='ServicePrice', new_name='ServiceItem'),
        migrations.AlterModelTable(name='serviceitem', table='service_items'),
        migrations.RenameField(model_name='serviceitem', old_name='service_price_id', new_name='service_item_id'),
        migrations.RenameField(model_name='task', old_name='service_price', new_name='service_item'),
        migrations.RenameField(model_name='plantask', old_name='service_price', new_name='service_item'),
    ]
```

- [ ] **3. Create `apps/estimates/migrations/0028_rename_tasktemplate_service_item.py`:**

```python
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('estimates', '0027_estimatelineitem_adjustment_service_and_more'),
        ('jobs', '0047_rename_serviceprice_to_serviceitem'),
    ]

    operations = [
        migrations.RenameField(model_name='tasktemplate', old_name='service_price', new_name='service_item'),
    ]
```

- [ ] **4. Bulk-rename backend modules (non-migration, non-test):**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
grep -rIl "ServicePrice\|service_price" apps/ --include='*.py' | grep -v '/migrations/' \
  | grep -v 'apps/jobs/models.py' | grep -v 'apps/estimates/models.py' | grep -v 'apps/invoicing/models.py' \
  | while read f; do
      sed -i '' 's/service_price_id/service_item_id/g; s/service_price/service_item/g; s/ServicePrice/ServiceItem/g' "$f"
    done
# models.py files already hand-edited in step 1; apply the same sed to catch
# internal refs (compute methods, docstrings) without disturbing step-1 edits:
for f in apps/jobs/models.py apps/estimates/models.py apps/invoicing/models.py; do
  sed -i '' 's/service_price_id/service_item_id/g; s/service_price/service_item/g; s/ServicePrice/ServiceItem/g' "$f"
done
```

- [ ] **5. Rename the API package + route/basename/supersede-URL:**

```bash
git mv apps/api/service_prices apps/api/service_items
sed -i '' 's/ServicePriceViewSet/ServiceItemViewSet/g; s/ServicePriceSerializer/ServiceItemSerializer/g; s/ServicePrice/ServiceItem/g; s/service_price_id/service_item_id/g; s/service_price/service_item/g; s#/api/service-prices/#/api/service-items/#g' apps/api/service_items/views.py apps/api/service_items/serializers.py
sed -i '' \
  -e 's#from apps.api.service_prices.views import ServicePriceViewSet#from apps.api.service_items.views import ServiceItemViewSet#' \
  -e 's/ServicePriceViewSet/ServiceItemViewSet/g' \
  -e "s#'service-prices': '/api/service-prices/'#'service-items': '/api/service-items/'#" \
  -e "s#r'service-prices'#r'service-items'#" \
  -e "s/basename='service-price'/basename='service-item'/" \
  apps/api/urls.py
```

- [ ] **6. Bulk-rename tests:**

```bash
grep -rIl "ServicePrice\|service_price\|service-prices" tests/ apps/schedule/tests/ \
  | while read f; do
      sed -i '' 's#/api/service-prices/#/api/service-items/#g; s/service_price_id/service_item_id/g; s/service_price/service_item/g; s/ServicePrice/ServiceItem/g' "$f"
    done
git mv tests/test_service_price.py tests/test_service_item.py
git mv tests/test_service_price_api.py tests/test_service_item_api.py
```

- [ ] **7. Bulk-rename fixtures:**

```bash
for f in fixtures/unit_test_data.json fixtures/jobs_basic_data.json fixtures/large_datasets/nealsmall.json fixtures/large_datasets/nealseed.json; do
  sed -i '' 's/jobs\.serviceprice/jobs.serviceitem/g; s/"service_price"/"service_item"/g; s/"service_price_id"/"service_item_id"/g' "$f"
done
```

- [ ] **8. Straggler sweep (backend) — expect empty:**

```bash
grep -rn "ServicePrice\|service_price\|service-prices\|jobs.serviceprice" apps/ tests/ fixtures/ --include='*.py' --include='*.json' | grep -v '/migrations/0'
```
Only allowed remaining refs live inside the historical migrations `apps/*/migrations/0*.py` — do NOT touch them.

- [ ] **9. `makemigrations --check --dry-run`** → expect **No changes detected**. If it reports an `AlterField` on `estimatelineitem.adjustment_service` / `invoicelineitem.adjustment_service` (RenameModel didn't propagate the FK `to`), generate those with `python manage.py makemigrations estimates invoicing` (additive AlterField, non-interactive) and re-check. **Do not** run `migrate`.

- [ ] **10. Full backend suite** (`python manage.py test`, `--keepdb` ok) → same pass/skip counts as before. Fix any failure as a missed reference, never a logic change.

- [ ] **11. Commit** `refactor: rename ServicePrice to ServiceItem (model, FK, API, tests, fixtures)`.

## Task 2: Frontend rename

- [ ] **1. Rename component + test:** `git mv frontend/src/components/ServicePriceManager.svelte frontend/src/components/ServiceItemManager.svelte` and `git mv frontend/tests/components/ServicePriceManager.test.js frontend/tests/components/ServiceItemManager.test.js`.
- [ ] **2. Sed the frontend:**

```bash
grep -rIl "ServicePrice\|service_price\|servicePrice\|service-prices" frontend/src frontend/tests \
  | while read f; do
      sed -i '' 's#/api/service-prices/#/api/service-items/#g; s/ServicePrice/ServiceItem/g; s/servicePrice/serviceItem/g; s/service_price/service_item/g' "$f"
    done
```
Also update the `import ServicePriceManager` / `<ServicePriceManager />` in `SettingsPage.svelte` → `ServiceItemManager` (the `ServicePrice`→`ServiceItem` sed handles it).

- [ ] **3. Straggler grep** (`grep -rn "ServicePrice\|service_price\|servicePrice\|service-prices" frontend/src frontend/tests`) → empty.
- [ ] **4. Frontend gate:** `cd frontend && npm run test:run && npm run build` → both green.
- [ ] **5. Commit** `refactor: rename ServicePrice to ServiceItem in Svelte SPA`.

## Task 3: Docs, memory, verification sweep

- [ ] **1. Sed durable docs:** `docs/designs/*.md`, `docs/ui-flows/Services-and-Adjustments.md` — `s/ServicePrice/ServiceItem/g; s/service_price/service_item/g; s#/api/service-prices/#/api/service-items/#g; s/service-prices/service-items/g`. (The `docs/plans/*` files are disposable history; optionally sed them too for consistency, but they may reference the old migration names — prefer leaving the plan files as the historical record, or add a one-line note. Decide per file.)
- [ ] **2. Update memory:** `MEMORY.md` pointer line + `project_serviceprice_rename_branch.md` body to say `ServiceItem` (note the branch still implements the same work; main unchanged).
- [ ] **3. Whole-repo straggler sweep** (excluding historical migrations + node_modules): `grep -rn "ServicePrice\|service_price\|service-prices\|jobs.serviceprice" . --include='*.py' --include='*.js' --include='*.svelte' --include='*.json' --include='*.md' | grep -v '/migrations/0' | grep -v node_modules | grep -v '/venv/' | grep -v 'docs/plans/2026-06-2'` → empty (or only intentional historical-doc mentions).
- [ ] **4. Final gate:** `python manage.py test` + `cd frontend && npm run test:run` → both green.
- [ ] **5. Commit** `docs: ServiceItem rename in durable docs + memory`.

---

## Self-Review

- Model/db_table/PK/FK renamed (Task 1.1–1.4); migrations `jobs/0047` + `estimates/0028` mirror Phase 0's `0044`/`0026`. ✓
- `adjustment_service` field name preserved; only its `to=` target updated (RenameModel + model-code edit). ✓
- API package/route/basename, tests, fixtures, frontend, docs, memory all covered. ✓
- Historical migrations excluded. ✓
- No-behavior-change guaranteed by suite-green gates. ✓
</content>

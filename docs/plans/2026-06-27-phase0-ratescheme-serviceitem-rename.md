# Phase 0 — the RateScheme / ServiceItem rename (pure mechanical, no behavior change)

> REQUIRED SUB-SKILL when executing: superpowers:subagent-driven-development.
> Same shape as the prior rename passes (RateScheme→ServicePrice→ServiceItem). **No
> behavior change — the existing tests are the regression net.**

**Goal:** put the right names on the right objects, so all later work reads cleanly.
- **Rate card:** model `ServiceItem` → **`RateScheme`** (revert).
- **Saved work item (salable concept):** model `TaskTemplate` → **`ServiceItem`**.

**The collision (why this is sequenced).** The names `ServiceItem` / `service_item` /
`service_items` (db_table) / `/api/service-items/` / `apps/api/service_items/` /
`ServiceItemManager` are **vacated by the rate card** and then **reclaimed by the
template**. Do it as **two ordered passes**: **Pass A** renames the rate card away
from those names first; **Pass B** then renames the template *into* them. Never both
at once.

## Name mapping

| Thing | Now | Pass A → | Pass B → |
|---|---|---|---|
| Rate-card model | `ServiceItem` | **`RateScheme`** | — |
| Rate-card db_table | `service_items` | **`rate_schemes`** | — |
| Rate-card PK | `service_item_id` | **`rate_scheme_id`** | — |
| FK to rate card (Task/PlanTask/the template) | `service_item` | **`rate_scheme`** | — |
| Rate-card route / pkg / serializer / FE manager | `service-items` / `apps/api/service_items/` / `ServiceItemSerializer` / `ServiceItemManager.svelte` | **`rate-schemes` / `apps/api/rate_schemes/` / `RateSchemeSerializer` / `RateSchemeManager.svelte`** | — |
| Saved-work model | `TaskTemplate` | (untouched in A) | **`ServiceItem`** |
| Saved-work db_table | `task_templates` | — | **`service_items`** (now free) |
| Saved-work route / serializer / FE manager | `task-templates` / `TaskTemplateSerializer` / `TaskTemplateManager.svelte` | — | **`service-items` / `ServiceItemSerializer` / `ServiceItemManager.svelte`** (now free) |

**Keep (don't churn):** `adjustment_service` FK keeps its name (just retargets to
`RateScheme`); `EstimateLineItem.source_template` keeps its name (retargets to the new
`ServiceItem`; it's removed in Phase 7 anyway). The bare-`scheme` symbols
(`SchemeSupersededError`, `allow_superseded_scheme`, `replaced_by`/`replaces`) were
left as-is across earlier renames and now re-align with `RateScheme` — leave them.
`TemplateTaskAssociation.task_template` FK → rename to **`service_item`** (it points
at the new ServiceItem); `WorkTemplate` and `TemplateTaskAssociation` model names stay.

## Global constraints
- **No behavior change.** Don't alter logic; rename only. Existing tests are the net.
- **Hand-write migrations** (interactive rename prompts aren't supported here):
  `RenameModel` + `AlterModelTable` + `RenameField` (PK + FKs). **Never edit historical
  migrations.** Pass B's migration **depends on** Pass A's (so `service_items` is free
  before B claims it).
- **Never write the dev DB.** Tests use the test DB. After migrations, run the suite at
  least once **fresh (no `--keepdb`)** — `feedback_fresh_db_after_migrations` — to catch
  ordering/historical-helper breakage (we hit exactly that on a prior rename). One test
  process at a time.
- macOS `sed -i ''`. After each pass, **grep the whole repo** for the old name
  (excluding historical migrations + the intentional bare-`scheme` symbols).
- Don't forget `fixtures/*.json`, `fixtures/large_datasets/*`, and `nealsdata/`
  (converter/build + datasets) — a prior rename's biggest miss was nealsdata.

## Reference (current)
- Rate card: `apps/jobs/models.py` `class ServiceItem` (~L469), db_table `service_items`,
  PK `service_item_id`; FK `service_item` on Task/PlanTask + `TaskTemplate.service_item`;
  `adjustment_service` FK on `EstimateLineItem`/`InvoiceLineItem`. API:
  `apps/api/service_items/`, route `service-items` (basename `service-item`), `ServiceItemViewSet`/`ServiceItemSerializer`.
  FE: `frontend/src/components/ServiceItemManager.svelte`; identifiers `service_item`/`serviceItem`.
- Template: `apps/estimates/models.py` `class TaskTemplate` (~L461), db_table `task_templates`;
  fields `template_name`, `service_item` (→rate card), `default_active_modifiers`,
  `default_billable_qty`. Referenced by `WorkTemplate`/`TemplateTaskAssociation` (db_table
  `template_task_assoc`, FK `task_template`) and `EstimateLineItem.source_template`. API:
  `apps/api/templates_config/`, route `task-templates` (basename `task-template`),
  `TaskTemplateViewSet`/`TaskTemplateSerializer`. FE: `TaskTemplateManager.svelte`.

## Tasks (TDD-ish; renames are verified by the *existing* suite staying green)

### Pass A — `ServiceItem` (rate card) → `RateScheme`
- [ ] **A1 — Backend.** Rename model `ServiceItem`→`RateScheme`; hand-write migration
  (`RenameModel` ServiceItem→RateScheme, `AlterModelTable`→`rate_schemes`, `RenameField`
  PK `service_item_id`→`rate_scheme_id`, `RenameField` `service_item`→`rate_scheme` on
  Task/PlanTask/TaskTemplate; retarget `adjustment_service` FK `to=`). Sweep Python
  (`service_item`→`rate_scheme`, `ServiceItem`→`RateScheme`), rename `apps/api/service_items/`→
  `apps/api/rate_schemes/`, route `service-items`→`rate-schemes` (basename `rate-scheme`),
  `ServiceItemSerializer/ViewSet`→`RateScheme…`. Fix fixtures + nealsdata. `makemigrations
  --check` clean; **fresh** full backend suite green.
- [ ] **A2 — Frontend.** `ServiceItemManager.svelte`→`RateSchemeManager.svelte` (git mv);
  `/api/service-items/`→`/api/rate-schemes/` in fetches; identifiers `service_item`/
  `serviceItem`→`rate_scheme`/`rateScheme`. (Leave user-visible "Service"/"Rate" *display*
  copy decisions to the UI vocab work — this is identifiers/routes.) Frontend suite + build green.
- [ ] **A3 — Sweep + gate.** Repo grep for stray `ServiceItem`/`service_item`/`service-items`
  (excluding historical migrations + bare-`scheme` symbols). Backend (fresh) + frontend green.

### Pass B — `TaskTemplate` → `ServiceItem` (depends on Pass A)
- [ ] **B1 — Backend.** Rename model `TaskTemplate`→`ServiceItem`; migration **depends on
  A's** (`RenameModel` TaskTemplate→ServiceItem, `AlterModelTable` `task_templates`→
  `service_items`, `RenameField` `TemplateTaskAssociation.task_template`→`service_item`;
  `EstimateLineItem.source_template` keeps its name, retargets via the model rename).
  Sweep Python (`TaskTemplate`→`ServiceItem`), route `task-templates`→`service-items`
  (basename `service-item`), `TaskTemplateSerializer/ViewSet`→`ServiceItem…` (now free),
  and move/rename the template endpoints into `apps/api/service_items/` (now free) — or
  keep them in `templates_config` with renamed classes/route (decision below). Fixtures +
  nealsdata. `makemigrations --check` clean; **fresh** backend suite green.
- [ ] **B2 — Frontend.** `TaskTemplateManager.svelte`→`ServiceItemManager.svelte` (now
  free; git mv); `/api/task-templates/`→`/api/service-items/`; identifiers
  `task_template`/`taskTemplate`→`service_item`/`serviceItem` where they mean the template.
  Frontend + build green.
- [ ] **B3 — Final sweep + gate.** Repo grep for stray `TaskTemplate`/`task-templates`
  (excluding historical migrations). makemigrations clean; **fresh** full backend + frontend + build green.

## Done-when
- Rate card is `RateScheme` everywhere (model/table/PK/FK/route/pkg/serializer/FE),
  saved-work item is `ServiceItem` everywhere; `makemigrations --check` clean; a
  **fresh-build** full backend suite + frontend suite + build are green; repo grep for
  the old names is clean except historical migrations and the intentional bare-`scheme`
  symbols.

## Decisions to confirm
- **Template API package:** move the (now) `ServiceItem` endpoints into a fresh
  `apps/api/service_items/` (clean), or keep them in `apps/api/templates_config/` with
  renamed classes/route (less churn). Lean: keep in `templates_config` for now (route is
  what matters); revisit when the catalog leaves the config area.
- **`adjustment_service` / `source_template` field names** kept (retargeted) to limit
  churn; rename later if desired.

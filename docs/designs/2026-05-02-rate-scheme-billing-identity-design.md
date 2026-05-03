# RateScheme as Billing Identity

## Summary

Promote `RateScheme` to the unit of billing identity for labor. The scheme owns the math (rate, algorithm, modifiers, minimum_charge), the `AccountingCategory` (and therefore taxability + QBO mapping), and its own version lineage. Work items (`PlanTask`, `Task`, `TaskTemplate`) stop carrying their own AC, rate, units, or est_qty — they reference a scheme and inherit its billing identity. Schemes become append-only once referenced. The invoice wizard finally migrates onto `TaskCharge` and switches to per-task atoms.

This consolidates four threads from `docs/plans/charge-thinking.md` (now obsolete and removable after this design lands): AC placement, scheme immutability, real-side `TaskCharge` adoption, and required-scheme cleanup. It builds on `docs/designs/2026-04-16-task-labor-ratescheme-refactor.md` — much of that doc is partially stale (`PlanCharge` was since merged into `PlanTask`); treat the prior doc as historical context, this doc as current.

## Motivation

Configuring a billable concept today requires touching three objects: an `AccountingCategory`, a `RateScheme`, and a `TaskTemplate` that wires them together. When creating a `PlanTask` the estimator picks both an AC and a RateScheme separately, even though the scheme implies a category for any sane setup. Editing a `RateScheme` retroactively rewrites the totals on accepted estimates and posted invoices — a known bug whose fix was specified ("append-only convention") but never enforced. The real-side invoice wizard ignores `TaskCharge` entirely and prices each blep as `task.rate × hours`, losing scheme modifiers and `minimum_charge`. `Task.rate` does double duty as customer billing rate and labor cost proxy. And `TaskTemplate.rate_scheme` allows null, leaving a "no billing" pattern that conflicts with the architectural direction.

The connective fix is to give `RateScheme` more authority and remove the duplicated billing fields from work items. Once the scheme is the source of truth, AC pass-through is automatic, immutability is enforceable, and the wizard rewrite has a clean target.

## Architectural Claim

`RateScheme` is the unit of billing identity for labor:

- It owns the **math** (rate, algorithm, modifiers, minimum_charge) — already true.
- It owns the **AccountingCategory** — therefore taxability and QBO income mapping. New.
- It owns its own **version lineage** via a self-FK — new.
- It is **immutable once referenced** by any work item — new (was a convention, becomes enforced).

Work items (`PlanTask`, `Task`, `TaskTemplate`) reference exactly one scheme and inherit everything else. They don't store AC, rate, units, or est_qty.

Materials use `PriceListItem` as their parallel "billing identity" object — same shape, different concrete model because materials' pricing is per-item rather than patterned. Expenses stay direct (per-instance dollar amounts; AC set on the expense).

## Model Changes

| Model | Add | Remove | Change |
|---|---|---|---|
| `RateScheme` | `replaced_by: FK(self, null=True, blank=True, on_delete=PROTECT)`, `replaced_at: DateTimeField(null=True, blank=True)` | — | `accounting_category` becomes `NOT NULL` |
| `PlanTask` | — | `accounting_category` | `rate_scheme` becomes `NOT NULL`; `estimated_billable_qty` renamed to `est_qty` and becomes `NOT NULL` |
| `Task` | — | `accounting_category`, `rate`, `units`, `est_qty` | `charge` (reverse OneToOne to `TaskCharge`) becomes a required relationship — see "Required TaskCharge" below |
| `TaskCharge` | — | — | no schema change; finally becomes authoritative for real-side billing |
| `TaskTemplate` | — | `accounting_category` | `rate_scheme` and `default_billable_qty` become `NOT NULL` |
| `Material`, `PlanMaterial`, `TemplateMaterial` | — | — | unchanged; AC derived from `price_list_item.accounting_category` when PLI is set, else direct on the material (today's `MaterialBase.save()` copy logic becomes pure derivation when PLI is present) |
| `Expense` | — | — | unchanged; AC stays direct (default pre-fill from linked Material's PLI when present) |
| `BillLineItem` | — | — | out of scope |

### Required `TaskCharge`

Every `Task` must have a `TaskCharge`. This is enforced in two layers:

1. **Service layer**: every Task creation path creates the `TaskCharge` in the same `transaction.atomic()` block. Paths include estimate carry-over (PlanTask → Task), `add-from-template`, ad-hoc add via `TaskModal`, and subtask creation via `SubtaskModal`.
2. **Defensive validation**: `Task.clean()` requires `hasattr(self, 'charge')` after first save. A code path that forgets fails loudly rather than silently shipping a chargeless task.

Django's `OneToOneField` has no native "must exist on the parent side" constraint — these two layers together provide it.

## AC Pass-Through

After the change, AC is read from the scheme everywhere a work item needs it:

- `plan_task.accounting_category` → `plan_task.rate_scheme.accounting_category`
- `task.accounting_category` → `task.charge.rate_scheme.accounting_category`
- `template.accounting_category` → `template.rate_scheme.accounting_category`

Editing a scheme's AC propagates to every work item linked to it — but per immutability rules, this only happens during the typo-fix window (before any references exist). After supersession, an old scheme keeps its AC frozen and existing references stay on the old AC.

For materials and expenses the existing arrangement holds: `Material` AC comes from its `PriceListItem` when one is linked, otherwise is set directly on the material; `Expense` AC is set directly with a sensible pre-fill from a linked Material's PLI when present.

## Append-Only Versioning

### Edit Rules

- A `RateScheme` is **freely editable** while no `PlanTask`, `TaskCharge`, or `TaskTemplate` references it (typo-fix window after creation).
- Once any reference exists, the scheme is **fully frozen** — `save()` and `clean()` reject changes to all fields except `replaced_by` / `replaced_at`. Splitting "math vs metadata" was considered and rejected: shops will catch typos quickly, full freeze keeps the rule simple.
- The only mutation allowed on a frozen scheme is the supersession transition (`replaced_by` and `replaced_at` get set together).

### Versioning Flow

- The "Edit" action in the Settings UI becomes **"Create new version"** once a scheme is frozen. The new-version form is pre-filled with the old scheme's values; the user changes what they want and saves.
- On save: a new `RateScheme` row is created; the old scheme's `replaced_by` is set to the new one and `replaced_at` is set to `now()`.
- The chain is preserved without auto-rewrite. `A.replaced_by → B.replaced_by → C` remains navigable; supersession does not collapse the chain to point everyone at the latest head.
- **Existing `PlanTask` and `TaskCharge` rows always keep their FK to the scheme they were created with.** No migration of historical references on supersession, ever. This is how billing history is preserved.
- **`TaskTemplate` rows are NOT auto-bumped.** A template pointing at a superseded scheme keeps its FK. The system surfaces this and forces resolution before the template can be used again — see below.

### Template Guard on Superseded Schemes

When `TaskTemplate.generate_task` (or any code path that creates a `Task` / `PlanTask` from a template) runs, it validates that `template.rate_scheme.replaced_by IS NULL`. If superseded:

- Service raises a `ValidationError` (or the project's equivalent service-layer exception).
- API responds **HTTP 409 Conflict** with a structured payload identifying the template, the superseded scheme, and the current head of the supersession chain.
- The frontend modal surfaces the message ("This template uses a superseded RateScheme. Update the template before adding tasks from it.") and offers a link to the template's edit screen.

The shop owner is forced to deliberately decide whether the template should adopt the new version or pick a different scheme. Silent retroactive change to template behavior is never acceptable.

### Picker Filtering

All scheme pickers (PlanTaskModal, TaskModal, SubtaskModal, TaskTemplate edit form) filter to `RateScheme.objects.filter(replaced_by__isnull=True)`. Superseded schemes are not pickable for new work.

### Outdated-Schemes UI

In Settings → RateSchemes:

- Default list shows active schemes (`replaced_by IS NULL`).
- A toggle or tab reveals **"Superseded schemes"** — list rows showing scheme name, the scheme it was replaced by (link to the next link in the chain), `replaced_at`, and reference counts (`N PlanTasks, M TaskCharges, K TaskTemplates`).
- Detail view of a superseded scheme is read-only. It shows the original values, the full forward chain (`replaced_by → replaced_by → …`) with each `replaced_at`, and back-links from the most recent ancestor.
- A small "Templates referencing superseded schemes" widget on the active-schemes view surfaces the count and links to the affected templates so owners can update them deliberately rather than discovering the conflict on next use.

### `PROTECT` Cascade Behavior

`replaced_by` uses `on_delete=PROTECT`. Combined with `PROTECT` on `TaskCharge.rate_scheme`, `PlanTask.rate_scheme`, and `TaskTemplate.rate_scheme`, schemes that have entered the lineage are effectively un-deletable. That is the intended behavior — you cannot orphan a `TaskCharge` or break the supersession chain.

## Edit-In-Use Block

Attempts to `PUT` / `PATCH` a scheme that has any reference (`PlanTask`, `TaskCharge`, or `TaskTemplate`) return **HTTP 409 Conflict** with a payload directing the client to `POST /api/rate-schemes/{id}/supersede/` instead. The response includes the reference counts so the UI can explain *why* the edit is blocked.

## Invoice Wizard Refactor

### Bug Being Fixed

The current wizard exposes per-blep atoms priced as `task.rate × hours`. This (a) bypasses `TaskCharge` entirely, (b) loses scheme modifiers, (c) loses `minimum_charge` (a per-task floor that can't be applied per-blep), and (d) reads `Task.rate` which this design removes.

### New Wizard Behavior

- **Atoms are tasks, one per task.** Each atom shows: task name, scheme name, qty source label ("3.5 hrs from bleps" / "12 pieces entered" / "flat fee"), active modifiers, and the computed total from `task.charge.compute()`.
- Bleps remain **visible as read-only detail** under their task atom (so the user can see what work the charge represents), but are not selectable as atoms themselves.
- The user includes or excludes whole tasks. Adjustments (rate negotiation, knocked-off hours, comp'd work) are made on the resulting `InvoiceLineItem` rows after generation. Non-billable bleps are handled either by editing the line item or by excluding the task from the wizard altogether.
- The wizard never sees a chargeless task (every Task has a TaskCharge per "Required TaskCharge" above).

### Code Path Removed

The per-blep iteration in the invoice wizard service and any helpers that read `task.rate` / `task.units` / `task.est_qty` are deleted in the same change that drops those columns from `TaskBase`.

## Required-RateScheme Cleanup

The plan-side and template-side null-rate-scheme path is removed:

- `PlanTask.rate_scheme` and `PlanTask.est_qty` become `NOT NULL`.
- `TaskTemplate.rate_scheme` and `TaskTemplate.default_billable_qty` become `NOT NULL`.
- `TaskTemplate.generate_task` (the `EstWorksheet` branch) propagates `rate_scheme` to the generated `PlanTask`. (Currently a known gap.)
- `PlanTaskModal` removes the "-- None (no billing) --" option; scheme selection is required.
- The "$0 Non-billable" scheme pattern is documented but **not shipped as a default**. Shops create one (or more) themselves with whatever AC fits their setup. This avoids architectural dependence on fixture data.

## API Changes

### `RateScheme` Viewset

- **New**: `POST /api/rate-schemes/{id}/supersede/` — body is the new scheme's fields. Server creates the new `RateScheme`, sets the old scheme's `replaced_by` and `replaced_at` in the same transaction, returns the new scheme. Permission: `CanManageConfig`.
- **List default filter**: `replaced_by__isnull=True`. Query param `?include_superseded=true` returns the full set; `?only_superseded=true` returns just retired schemes.
- **Edit (PUT/PATCH) on a referenced scheme**: returns **HTTP 409** with a payload directing the client to the supersede endpoint and including reference counts.
- **Serializer additions**: `replaced_by`, `replaced_at`, `superseded` (computed bool: `replaced_by is not None`), and reference counts (`plan_task_count`, `task_charge_count`, `task_template_count`) for the outdated-schemes UI.
- **`unit_label` validation**: `RateScheme` serializer (and the underlying model `clean()`) validates `unit_label` against the configured units list via the shared `validate_units` validator from `apps.core`. Same controlled vocabulary as `BaseLineItem.units` etc.

### `PlanTask`, `Task`, `TaskTemplate` Serializers

- Drop `accounting_category` field from the serializer payload (no longer stored).
- The frontend reads AC, when needed, from the nested `rate_scheme.accounting_category`.
- `TaskTemplate` serializer no longer includes any AC field at all — the rate_scheme nested representation is sufficient.

### Task Creation Endpoints

Every server-side Task creation path accepts `rate_scheme` (required), modifier keys, and `est_qty` (or whatever the algorithm requires) and creates the `TaskCharge` server-side in the same transaction. This covers ad-hoc creation via `POST /api/jobs/{job_id}/tasks/` (used by both `TaskModal` and `SubtaskModal`, the latter setting `parent_task`), template-driven creation (`add-from-template`, `populate-from-template`), estimate carry-over (`populate-from-estimate`), and worksheet copy (`copy-from-worksheet`). The implementation plan enumerates each path; the architectural guarantee is that no Task can be created without its TaskCharge.

The "use of a template whose scheme is superseded" guard described above applies to template-driven endpoints.

### Errors

- **409 Conflict** for both "edit-in-use scheme" and "use-template-with-superseded-scheme". Both are state conflicts (request well-formed, server state blocks the action) — not malformed input.
- **400 Bad Request** for the usual: missing `rate_scheme`, invalid modifier key (not in scheme's modifier list), invalid actuals shape, etc.

## UI Changes

### Settings → RateSchemes

- List of active schemes; per-row "Create new version" button (replaces "Edit" once references exist).
- "Superseded" tab/toggle exposing the outdated-schemes view described above.
- "Templates referencing superseded schemes" widget surfacing the count + links.
- The create/edit form's `unit_label` field is a `<select>` dropdown populated from the configured units list (`GET /api/settings/units/`), not a free-text input. This brings RateScheme into line with the controlled-vocabulary convention from `docs/designs/2026-03-30-configurable-units.md` already used by line items, templates, and inventory.

### Settings → TaskTemplates

- AC field removed from the form. The currently-selected scheme's AC may be shown as read-only context if useful.
- `rate_scheme` selection required; default modifier checkboxes populate from the chosen scheme.

### Settings → AccountingCategories

- Unchanged. Still configured separately because materials and expenses point at categories directly.

### `PlanTaskModal` (worksheet)

- "-- None (no billing) --" option removed.
- AC field removed.
- `rate_scheme` picker filters to active schemes.

### `TaskModal` and `SubtaskModal` (job task list)

- Both gain a required `rate_scheme` picker, modifier checkboxes, and `est_qty` input — same shape as `PlanTaskModal`.
- Factor the shared rate-scheme-input UI into a single `RateSchemeFieldset.svelte` subcomponent embedded by all three modals (PlanTaskModal, TaskModal, SubtaskModal).

### `TaskDetailPage`

- AC display is **removed entirely** from this page. Workers do not need to see accounting categories; AC stays an estimating / invoicing / QBO concept.
- The TaskCharge section continues to show scheme name, effective rate, modifiers, and (for `entered_qty`) the editable actual qty input.

### Invoice Wizard

- Atoms render per-task with the computed total from `task.charge.compute()`.
- Bleps appear as read-only detail under each task atom.
- The legacy per-blep atom UI is removed.

## Permissions

| Action | Permission |
|---|---|
| View RateSchemes (active or superseded) | `IsAuthenticated` |
| Create RateScheme | `CanManageConfig` |
| Edit RateScheme (typo-fix window) | `CanManageConfig` |
| Supersede RateScheme | `CanManageConfig` |
| Edit TaskTemplate | `CanManageConfig` |
| Create Task on a Job (any modal/endpoint) | `IsAuthenticated` (today's behavior preserved; future worker-friendly default-scheme work is deferred — see "Known Future Need") |

## Known Future Need

A worker without management permissions may discover that an additional task is needed mid-job and want to create it quickly — possibly starting a blep against it as part of the same flow. Forcing such a worker through a full RateScheme picker is friction. The likely future shape is a `default_worker_rate_scheme` Configuration key (or similar) that lets the `TaskModal` skip the picker for unprivileged users.

This is **explicitly deferred**. The architecture in this design does not preclude any solution — once the workflow is decided, it's a Configuration key plus a permissions-aware modal flow, with no model changes required.

## Out of Scope

- `User.pay_rate`, labor cost computation, profitability reporting. Profitability remains broken until a separate design addresses it.
- `BillLineItem` cleanup.
- Per-task rate override mechanism. All rate adjustments happen on `InvoiceLineItem` after wizard generation.
- Material / Expense restructuring beyond the AC-derivation clarification noted above.
- A shipped "Non-billable" RateScheme. Shops create their own.
- Worker-friendly quick-add task flow (see "Known Future Need").

## Migration Philosophy

The architecture does not depend on data munging, but the **implementation plan must sequence the work to leave a manual-fix window** for the dev database.

- Schema migrations drop columns (`Task.rate`, `Task.units`, `Task.est_qty`, `accounting_category` on `PlanTask` / `Task` / `TaskTemplate`) and tighten constraints (`NOT NULL` on `RateScheme.accounting_category`, `PlanTask.rate_scheme`, `PlanTask.est_qty`, `TaskTemplate.rate_scheme`, `TaskTemplate.default_billable_qty`).
- `PlanTask.estimated_billable_qty` is renamed to `PlanTask.est_qty`.
- No one-off backfill code is part of this design.
- Pre-production: legacy data may be hand-fixed or wiped without any architectural accommodation.

### Required implementation sequencing

The implementation plan must split the work into at least two phases with a deliberate pause between them:

**Phase A — additive only, no constraint tightening:**
- Add `RateScheme.replaced_by` and `RateScheme.replaced_at` columns (nullable).
- Add new code paths (TaskCharge-required service code, AC-pass-through readers, supersede endpoint, scheme-locked validation, template-superseded guard, per-task wizard atoms, `RateSchemeFieldset` component, `unit_label` controlled vocabulary).
- Add the new UI surfaces (Settings → RateSchemes outdated view, modal updates).
- Do **not** drop columns. Do **not** tighten `NOT NULL` constraints. Do **not** rename `estimated_billable_qty`.
- At the end of this phase the system runs with both old and new shapes coexisting; new code prefers the new shape and tolerates old shape for the duration of the pause.

**Pause — manual data fix window:**
- The developer reviews and corrects dev-DB rows: every `RateScheme` gets an `AccountingCategory`; every `PlanTask` gets a `rate_scheme` and `est_qty`; every `TaskTemplate` gets a `rate_scheme` and `default_billable_qty`; every `Task` gets a `TaskCharge`; any `accounting_category` set on a work item that disagrees with its scheme's AC is reconciled (typically by leaving the scheme's AC as authoritative).
- This pause is a single explicit step in the plan, not a hand-wave. The plan should provide a checklist or a read-only diagnostic management command (`check_billing_data`, no writes) the developer runs to confirm the dataset is ready for Phase B.

**Phase B — constraint tightening and column drops:**
- Tighten `NOT NULL`s on the new FKs and AC.
- Rename `PlanTask.estimated_billable_qty` → `est_qty`.
- Drop `Task.rate`, `Task.units`, `Task.est_qty`.
- Drop `accounting_category` from `PlanTask`, `Task`, `TaskTemplate`.
- Remove the legacy code branches that tolerated old shape during Phase A.
- Enforce immutability on referenced schemes (the edit-blocking `clean()` rule).

If the manual fix window proves too painful in practice, the fallback is to re-seed from the (already updated) JSON fixture rather than work through the dataset row by row — but the phased plan keeps that as a fallback rather than a forced step.

## Tests

Following the project's TDD convention, the implementation plan will introduce or update at minimum:

- `test_rate_scheme.py` / `test_rate_scheme_api.py` — supersession transition, edit-in-use block (HTTP 409), picker filtering, replaced_at timestamp behavior, AC-required validation.
- `test_task_charge.py` / `test_task_charge_api.py` — Task creation always produces a TaskCharge (every endpoint path), `Task.clean()` defensive check.
- `test_estimate_charge.py` — PlanTask AC derived through scheme; renamed `est_qty` field.
- New: `test_invoice_wizard_per_task_atoms.py` (or extension of an existing wizard test) — wizard exposes per-task atoms, prices through `task.charge.compute()`, includes modifiers and `minimum_charge`, line item generation snapshots the right fields.
- New: `test_template_superseded_scheme_guard.py` — using a template whose scheme is superseded raises 409 with the right payload structure.

Detailed test enumeration is the implementation plan's job, not this design's.

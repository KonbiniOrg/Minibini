# Billable Atoms and Estimate Wizard

**Date:** 2026-04-19
**Status:** Draft

## Problem

The codebase has two parallel systems for turning work objects (Tasks, Materials) into LineItems:

- **Plan side (Worksheet → Estimate):** declarative. `PlanTask.mapping_strategy` (`direct`/`bundle`/`exclude`) plus `PlanBundle` group atoms; `EstimateGenerationService` does a one-shot generation when the user clicks "Generate Estimate."
- **Real side (Job → Invoice):** interactive. `InvoiceWizardService` exposes Bleps and Materials as polymorphic atoms; users group them into `InvoiceLineItem`s via a wizard, with `InvoiceLineItemSource` rows tracking claims.

The plan-side system has problems:

1. The `mapping_strategy` field forces an up-front commitment to a grouping decision per atom, instead of letting the user group ad-hoc.
2. The data model is awkward: bundling lives partly on the PlanTask, partly in PlanBundle, partly in mapping_strategy logic.
3. The "exclude" strategy doesn't model anything real — items are kept on the worksheet but hidden from the estimate.
4. It's a separate codepath from the wizard for the same conceptual operation.

There's also a **gap**: estimates created without a worksheet (the "direct estimate" path) can only add line items by manual entry or by picking from `PriceListItem`. There's no way to pick a `TaskTemplate` for an estimate line item, and no template object that represents a pre-built line item.

The wizard is the better pattern. The goal is to bring the plan side into parallel with the real side, fill the direct-estimate gap by extending catalog pickers to cover both `TaskTemplate` and `PriceListItem`, and add a Job state to handle the gap between "estimate accepted" and "ready for the floor."

## Design

### The atom model

Both sides use the same abstraction. An **atom** is anything implementing a uniform interface:

- `compute_amount(modifiers) -> Money`
- `accounting_category`
- `units`
- `description`
- a source-pointer identity (model + pk)

Atoms come in two families on each side:

| Plan side | Real side | Notes |
|---|---|---|
| `PlanCharge` | `TaskCharge` | Wraps a `RateScheme`. `compute_amount` rolls up Bleps for `elapsed_time`, uses entered actuals for `entered_qty`, returns the fixed price for `flat_fee`. Modifiers and minimum charges apply uniformly. |
| `PlanMaterial` | `Material` | `compute_amount = qty × sell_price`. |

Bleps are detail inside an `elapsed_time` `TaskCharge`. They are never claimed as atoms themselves. There is no business reason to split bleps from one Task across multiple line items; if such a need arises, the Task itself gets split first.

`PlanCharge` and `PlanTask` (and the corresponding `TaskCharge` / `Task`) remain as separate models, OneToOne. The work-item model carries identity (description, accounting_category, source_template) and on the real side, lifecycle and Bleps. The charge model carries billing config (RateScheme, modifiers, qty). Keeping them separate makes it easier to evolve billing logic without touching the work model.

### Containers and parallel structure

The new structure is:

```
PLAN SIDE                                  REAL SIDE
---------                                  ---------

Worksheet  ----[wizard]---->  Estimate     Job  ----[wizard]---->  Invoice
   |                            |            |                       |
PlanCharge          EstimateLineItem    TaskCharge           InvoiceLineItem
PlanMaterial             ^               Material                   ^
   |                     |                  |                       |
   +----[source rows]----+                  +-----[source rows]-----+

atoms                line items          atoms                  line items
(optional)                               (optional)
```

The Worksheet : Estimate relationship is exactly parallel to Job : Invoice. The wizard pattern is the same machinery on either side.

### Line items and source rows

`EstimateLineItem` and `InvoiceLineItem` both have a polymorphic source table (parallel to today's `InvoiceLineItemSource`).

- **0 sources** — manually authored line item, or pre-filled from a catalog without going through atoms (the simple-estimate path).
- **1 source** — came from one atom (bulk "send all" or single-atom wizard pick). Looks like a 1:1 conversion.
- **N sources** — wizard-grouped from multiple atoms.

Price behavior: a line item is "in sync" if its price equals the rolled-up `compute_amount` of its sources. In-sync line items recompute when sources change. Manual price overrides stick. Identical rule on both sides.

### Catalog flow and the picker

A single shared form pattern is used in three places:

| Context | Output |
|---|---|
| Worksheet | `PlanCharge` / `PlanMaterial` atom |
| Estimate (direct, no atom) | `EstimateLineItem` with 0 source rows |
| Job | `TaskCharge` / `Material` atom on a Task |

The form (the **catalog picker**) defaults to **unified search** — one search box, results from `TaskTemplate` and `PriceListItem` mixed, tagged by source. A "Manual" option lets the user type a fully custom row. For task-template picks with entry-requiring schemes, an **Estimated qty** input appears (required), seeded from the template default if any. Modifier toggles appear inline, driven by the scheme's available modifiers.

`WorkTemplate` is **not** in the catalog picker. WorkTemplates serve a different purpose — they're a pre-built bundle of TaskTemplates and TemplateMaterials representing a common job type, used at worksheet creation time to seed atoms in bulk. That existing UX path is unchanged by this design.

Unified search is "try it and see." If mixing the two catalogs proves confusing in practice, fall back to a tabbed picker (Tasks / Materials / Manual). Out of scope for this design; revisit only if needed.

### Worksheet → Estimate operations

A Worksheet exposes two top-level operations:

1. **"Send all atoms to estimate"** — bulk 1:1 conversion. Iterates unclaimed atoms; creates one `EstimateLineItem` per atom with one source row pointing at the atom. Default fast path. No per-atom UI.
2. **"Group atoms"** — opens the wizard. User picks atoms, combines into one or more line items, optionally overrides description/price. Each resulting line item has one or more source rows.

These are separate UIs, not interleaved per-atom. A user can run them sequentially across sessions (e.g., wizard-group some atoms, bulk-send the rest later). Inside the wizard, even a single-atom-to-single-line-item operation happens via the wizard UI; there is no per-atom button on the worksheet itself.

Atoms already claimed by a source row are shown as "already on estimate" and cannot be double-claimed — same rule as today's invoice wizard.

### Direct estimate line items (no worksheet, no atoms)

The simple path stays simple:

- User clicks "Add line item" on an Estimate.
- Same shared form (unified picker / manual entry) opens.
- Result is an `EstimateLineItem` with **zero source rows**. No atom backs it.

This is the existing direct-estimate path. The only new thing is that the picker now includes `TaskTemplate`s alongside `PriceListItem`s — closing the gap the user originally described.

### Worksheet status

Worksheet status flow is preserved: `draft` → `final` → `superseded`.

- `draft`: user is still editing atoms. Atoms can be added, edited, claimed by line items.
- `final`: locked. No more atom editing. Triggered automatically when the associated Estimate transitions out of `draft` (i.e., to `open`/sent). Atoms not claimed by any line item remain as historical artifacts on the worksheet — the user is allowed to send an Estimate without including every atom.
- `superseded`: a new revision has replaced this worksheet. New revisions are full copies (existing `EstWorksheet.create_new_version()` pattern), so the new worksheet has its own atom instances.

Source rows on the plan side are **permanent within their estimate's lifetime**. Superseding/rejecting/expiring an Estimate does NOT release source-row claims on its atoms. This is asymmetric with the invoice side (where cancelled invoices release claims), but it doesn't matter in practice: revision flow always copies the worksheet, so new estimates use new atom instances. The complexity of release-on-supersede has no payoff on the plan side and adds a rule to learn.

### Job state machine — new `in_progress` state

The current Job state machine:

```
draft → submitted → approved → work_complete → completed
                       ^
                       |
            "estimate accepted AND shows in In Progress"
```

The auto carry-over of atoms from Worksheet to Job at estimate acceptance creates a problem: the Job lands in `approved` and immediately appears on the Job Board's In Progress area, even when the shop still needs to set up tasks/materials (especially for direct-estimate line items that didn't come with atoms).

The new state machine:

```
draft → submitted → approved → in_progress → work_complete → completed
                       |             |
                       |             |
           "estimate accepted;   "released to floor;
            in Pipeline tab"     in In Progress area"
```

Transitions:

- **submitted → approved**: automatic when the associated Estimate moves to `accepted`. **Atom carry-over fires here**: PlanCharges become TaskCharges on new Tasks; PlanMaterials become Materials. Direct-estimate line items with a template ref also generate matching atoms (see "Atom carry-over from Worksheet to Job" below). Manual line items with no template ref do not.
- **approved → in_progress**: explicit user action ("Release to floor"). User reviews carried-over atoms, fills in setup for any manual line items, then promotes when ready.
- Jobs without an estimate use the same flow but the user manually promotes through states.

Job Board placement:

- `approved`: appears in the existing **Pipeline tab**, in its own new color (distinct from `submitted` and any other Pipeline states).
- `in_progress`: appears in the existing **In Progress area**, using whatever color `approved` uses today (since `in_progress` takes over that semantic role).

### Atom carry-over from Worksheet to Job

When a Job auto-transitions `submitted → approved` on Estimate acceptance:

- For each `PlanCharge` on the worksheet: create a `Task` on the Job and a `TaskCharge` on that Task. Estimated qty seeds the actuals/expected.
- For each `PlanMaterial` on the worksheet: create a `Material` on the Job (linked to the corresponding Task if the PlanMaterial was task-scoped on the worksheet).
- Idempotent on `source_template` — if Tasks/Materials with the same source_template already exist on the Job, skip.

For **direct-estimate line items** (no worksheet involved):

- If the line item was created from a `TaskTemplate` (template ref preserved on the line item): create a matching `Task` + `TaskCharge` on the Job.
- If the line item was created from a `PriceListItem`: create a matching `Material` on the Job.
- If the line item was purely manual (no template ref): no automatic atom. The user adds tasks/materials manually as the work shapes up.

### Permissions

No new permission atoms. All operations stay within `can_manage_jobs` (atom CRUD on Worksheet/Job, line item operations, wizard, state transitions including `approved → in_progress`).

## Removed

- `PlanTask.mapping_strategy` field. Obsolete; grouping is wizard-driven, not declarative.
- `PlanBundle` model. Replaced by source rows on `EstimateLineItem`s.
- `TemplateBundle` model. Same reasoning at the template level. `TemplateTaskAssociation`s previously inside a bundle become normal flat template task entries.
- `EstimateGenerationService`. Replaced by the wizard service (mirroring `InvoiceWizardService`) plus the "send all" bulk action. Both produce source-backed line items.
- `EstimateLineItem.task` FK (to PlanTask) and `EstimateLineItem.material` FK (to PlanMaterial). Replaced by `EstimateLineItemSource` rows.

## Added

- **`EstimateLineItemSource`** model. Polymorphic claim table mirroring `InvoiceLineItemSource`. Sources point to PlanCharge or PlanMaterial via `source_type` + `source_pk`. Unique constraint on `(source_type, source_pk)` enforces one-claim-per-atom across all non-cancelled estimates. CASCADE on EstimateLineItem deletion (so deleting a line item releases its claims; only superseding/rejecting/expiring an Estimate does not). No release on supersede on the plan side.
- **`EstimateLineItem.source_template`** FK (to `TaskTemplate`, nullable). Preserves the catalog reference for direct-estimate line items so the Job carry-over service can create matching atoms at Estimate acceptance. Existing `price_list_item` FK serves the same purpose for material-style line items.
- **Uniform `compute_amount(modifiers) -> Money` interface** on `TaskCharge`, `PlanCharge`, `Material`, `PlanMaterial`. Existing scheme logic stays where it is; this just gives both sides the same callable shape.
- **Estimate wizard service** (e.g., `EstimateWizardService`) mirroring `InvoiceWizardService`. Same source-pool / line-items-from-atoms / add-atoms / remove-atoms operations.
- **Estimate wizard REST endpoints** under `/api/estimates/<id>/`: `source-pool/`, `line-items-from-atoms/`, `line-items/<li_id>/add-atoms/`, `line-items/<li_id>/remove-atoms/`. Exact shapes mirror the invoice wizard endpoints; details for the implementation plan.
- **Bulk "send all atoms" endpoint** on Worksheet (e.g., `POST /api/est-worksheets/<id>/send-all-atoms-to-estimate/`).
- **Catalog picker** (Svelte component). Unified search over `TaskTemplate` + `PriceListItem` + Manual. Used by Worksheet/Job (creates atoms) and Estimate/Invoice (creates line items).
- **`Job.STATUS_IN_PROGRESS`** constant and state machine entry. Transition `approved → in_progress` is explicit user action.
- **Job Board "approved" color** distinct from other Pipeline-tab states.
- **Carry-over service** that fires on Estimate `accepted`: creates Tasks/TaskCharges/Materials on the Job from worksheet atoms and direct-estimate line items with template refs.

## Migration

CLAUDE.md indicates pre-production state, so correctness over preservation is acceptable. For any existing data:

- **Existing `EstimateLineItem`s with FK to `PlanTask`**: back-fill `EstimateLineItemSource` rows pointing to the corresponding `PlanCharge` (the OneToOne off the PlanTask).
- **Existing `EstimateLineItem`s with FK to `PlanMaterial`**: back-fill `EstimateLineItemSource` rows pointing to the PlanMaterial.
- **`PlanBundle`s**: for each bundle, the corresponding bundled `EstimateLineItem` already exists (one per bundle); back-fill source rows for all PlanCharges in the bundle. Then drop `PlanBundle`.
- **`PlanTask.mapping_strategy = 'exclude'`**: leave those PlanCharge atoms on the worksheet without a source row — they were already not represented in the estimate. Same effect as before.
- **`TemplateBundle`s**: the `TemplateTaskAssociation`s inside become normal flat template task entries; drop `TemplateBundle`.
- After back-fill: drop the old FK fields from `EstimateLineItem` (`task`, `material`) and the `PlanBundle` / `TemplateBundle` tables.

Existing Jobs in `approved` status remain in `approved` (no automatic move to `in_progress`) — preserves existing state for in-flight jobs. Users can promote them as they review.

## Open questions deferred to implementation plan

- Exact REST endpoint shapes for the estimate wizard (mirror invoice wizard; final details when writing the implementation plan).
- UI polish for the modifier toggles in the catalog picker form.
- Tabbed catalog picker fallback — only build if unified search proves confusing in practice.
- Whether to show "atoms not yet sent to estimate" prominently on the worksheet UI as a nudge to the user.

## Out of scope

- Splitting a single Task's Bleps across multiple invoice line items. No business reason.
- Replacing `PlanTask` / `Task` with a single unified model. Considered and rejected — separation of work-item identity from billing config is cleaner.
- Eliminating the Worksheet model in favor of "atoms on the Estimate." Considered and rejected — the Worksheet : Estimate :: Job : Invoice parallel is the right shape.
- A separate "LineItem catalog." Not needed — the existing two catalogs (TaskTemplate, PriceListItem) feed both atoms and line items via the shared catalog picker.
- **Adding a `TaskTemplate ↔ TemplateMaterial` association** so a TaskTemplate can carry default attached materials. Future capability; deferred. When added, the picker behavior in line-item context will be: produce one combined `EstimateLineItem` (description aggregates task + material; price = task amount + material amount; `source_template` preserved). Carry-over to Job at acceptance reconstructs the proper Task + Material atoms with their association intact via the source_template.
- Including `WorkTemplate` in the catalog picker. WorkTemplates remain a separate worksheet-creation tool; that UX path is unchanged.

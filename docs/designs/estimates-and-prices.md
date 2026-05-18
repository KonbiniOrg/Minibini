# Estimates and Billing

Reference for the estimating side of Minibini: `RateScheme` as the
unit of billing identity, supersession, the billable-atom abstraction,
the estimate wizard, atom carry-over from worksheet to job, and AC
pass-through. Read alongside:

- `docs/designs/architecture-and-conventions.md` — service-layer
  pattern, `LineItemMixin`, exception hierarchy
  (`ServiceError` / `NotFoundError` / `SchemeSupersededError`).
- `docs/designs/jobs-tasks-and-worksheets.md` — `Task`, `PlanTask`,
  `Job`/`EstWorksheet` containers, populate paths, signal receivers
  (`estimate_accepted`, `estimate_status_changed_for_job`,
  `estimate_status_changed_for_worksheet`).
- `docs/designs/materials-inventory-and-purchasing.md` — `Material`
  and `PlanMaterial` (the other atom family), `PriceListItem`.
- `docs/designs/invoicing-and-expenses.md` — the parallel invoice
  wizard built on the same source-row pattern.
- `CLAUDE.md` — status constants, document-numbering service,
  `AccountingCategory` shape, line-item delete rule.

---

## 1. What this doc owns

This doc owns:

- `RateScheme` model, modifier algebra, supersession lineage.
- Billing identity on `Task` / `PlanTask` / `TaskTemplate` (the FK to
  `RateScheme` and the `active_modifiers` / `est_qty` / `actual_qty`
  semantics).
- `Estimate`, `EstimateLineItem`, `EstimateLineItemSource`.
- The atom abstraction (atoms are Tasks and Materials; whole-task
  billing).
- `EstimateWizardService`, the wizard endpoints, and the wizard UI.
- `AtomCarryOverService` — what fires when an Estimate is accepted.
- AC pass-through rules from RateScheme → Task / line item.

It does **not** own:

- The Job/Task/Worksheet shape or status machines (jobs-tasks doc).
- The Material/PlanMaterial side of the atom family beyond the pieces
  the wizard touches (materials doc).
- Invoice-side wizard or `InvoiceLineItemSource` (invoicing doc).
- Service-layer mechanics, mixin catalog, permission atoms (architecture
  doc).

---

## 2. RateScheme

`RateScheme` (`apps/jobs/models.py`, `db_table = 'rate_schemes'`) is
the unit of billing identity for labor. It owns the math (rate,
algorithm, modifiers), the `AccountingCategory` (and therefore
taxability / QBO income mapping), and its own version lineage. Every
`PlanTask`, `Task`, and `TaskTemplate` references exactly one
`RateScheme` and inherits the rest.

### 2.1 Identity fields

| Field | Type | Notes |
|---|---|---|
| `rate_scheme_id` | AutoField PK | |
| `name` | CharField(100), unique | display name; e.g. "CNC Router", "Hourly Labor" |
| `description` | TextField, blank | longer admin explanation |
| `algorithm` | CharField(20), choices | one of `elapsed_time`, `entered_qty`, `flat_fee` |
| `rate` | Decimal(10,2) | per-unit base price |
| `unit_label` | CharField(50) | the customer-facing unit (e.g. `hour`, `minute`, `piece`, `job`); validated against the configured units list (`apps/core/units.py`) |
| `modifiers` | JSONField | list of `{key, label, percent}` dicts |
| `accounting_category` | FK → `AccountingCategory` (PROTECT) | required, NOT NULL |
| `replaced_by` | FK self (PROTECT, nullable) | supersession pointer |
| `replaced_at` | DateTimeField, nullable | when supersession happened |

`accounting_category_id` is enforced at the application layer in
`RateScheme.clean()` (raises `ValidationError`).

### 2.2 Algorithms

| Algorithm | Constant | Quantity source | Typical use |
|---|---|---|---|
| `elapsed_time` | `RateScheme.ELAPSED_TIME` | sum of `Blep` durations on the task in hours | hourly labor (assembly, bench work) |
| `entered_qty` | `RateScheme.ENTERED_QTY` | `Task.actual_qty` | machine-minutes, piece work; worker enters the count |
| `flat_fee` | `RateScheme.FLAT_FEE` | implicit `Decimal(1)` | setup fees, delivery |

`RateScheme.get_actual_qty(task)` resolves the right quantity per
algorithm:

```python
ELAPSED_TIME → (Decimal(sum(blep.elapsed.total_seconds())) / 3600).quantize(0.01)
ENTERED_QTY  → task.actual_qty or Decimal('0')
FLAT_FEE     → Decimal('1')
```

The `ELAPSED_TIME` result is quantized to 2 decimal places: a raw
seconds/3600 division is non-terminating (~28 digits) and would overflow
the line item `qty` field (`max_digits=10`) when carried into the invoice
wizard.

### 2.3 Modifiers

Each modifier in the scheme's `modifiers` JSON list is a dict:

```json
{"key": "messy", "label": "Messy materials", "percent": 10}
```

- `key`: stable identifier; recorded in `Task.active_modifiers` (and
  `PlanTask.active_modifiers`, `TaskTemplate.default_active_modifiers`).
- `label`: display string shown in checkboxes and on the line item.
- `percent`: additive percent surcharge over the base rate.

Active modifiers stack additively: messy (+10%) + doublestick (+5%)
= +15% on `rate`. Validation that `active_modifiers` keys are a subset
of the scheme's modifier keys is up to the form/serializer layer.

### 2.4 Effective rate and compute

```python
RateScheme.effective_rate(active_modifiers)
    → rate * (1 + sum(m.percent for m in modifiers if m.key in active_modifiers) / 100)

RateScheme.compute_charge(qty, active_modifiers)
    → qty * effective_rate(active_modifiers)
```

There is no minimum-charge floor on RateScheme — that field was
removed.

### 2.5 Reference checks

`RateScheme.is_referenced()` returns `True` if any `PlanTask`, `Task`,
or `TaskTemplate` points at this scheme.

`RateScheme.reference_counts()` returns:

```python
{
    'plan_task_count':     PlanTask.objects.filter(rate_scheme=self).count(),
    'task_count':          Task.objects.filter(rate_scheme=self).count(),
    'task_template_count': TaskTemplate.objects.filter(rate_scheme=self).count(),
}
```

Used by both the edit-in-use guard and the outdated-schemes UI.

---

## 3. Supersession

Once any work item references a `RateScheme`, the scheme is **frozen**
in place. To change rate / modifiers / AC after that, the user
**supersedes** the scheme — creates a new row, leaves the old one
intact, and links them via `replaced_by` / `replaced_at`. Existing
work items keep pointing at the old scheme; future picks pull from
active (non-superseded) schemes.

### 3.1 Frozen fields

`RateScheme.FROZEN_FIELDS`:

```python
('name', 'description', 'algorithm', 'rate', 'unit_label',
 'modifiers', 'accounting_category')
```

`RateScheme.clean()` rejects any change to these fields when
`is_referenced()` is true. The only allowed mutations on a frozen
scheme are `replaced_by` and `replaced_at` (and the `name` rename
that `supersede()` itself performs — see below).

The freeze is full, not split into "math vs metadata". Shops catch
typos quickly, and a single rule is easier to reason about.

### 3.2 supersede()

```python
RateScheme.supersede(**overrides) → new RateScheme
```

In one transaction:

1. Renames `self` in place to `<orig_name> (vN)` where `N` counts
   predecessors in the chain. This frees the unique-name slot for the
   new row without needing a partial-unique index.
2. Creates a new `RateScheme` row with all of `self`'s field values,
   then applies `**overrides`.
3. Sets `self.replaced_by = new` and `self.replaced_at = now()`.

The chain is preserved without auto-collapse:
`A.replaced_by → B.replaced_by → C` stays navigable. Existing
`PlanTask` / `Task` / `TaskTemplate` rows always keep their FK to the
scheme they were created with — no migration of historical references
on supersede, ever. That's how billing history is preserved.

`supersede()` raises `ValueError` if the scheme is already
superseded.

### 3.3 API

| Verb + path | Behavior |
|---|---|
| `GET /api/rate-schemes/` | List active schemes (`replaced_by IS NULL`) |
| `GET /api/rate-schemes/?include_superseded=true` | List all schemes |
| `GET /api/rate-schemes/?only_superseded=true` | List just superseded |
| `GET /api/rate-schemes/{id}/` | Retrieve any scheme (active or superseded) |
| `POST /api/rate-schemes/` | Create — `CanManageConfig` |
| `PUT/PATCH /api/rate-schemes/{id}/` | Edit — **HTTP 409** if referenced (see below) |
| `POST /api/rate-schemes/{id}/supersede/` | Create new version, set `replaced_by`/`replaced_at` on the old row — `CanManageConfig` |
| `DELETE /api/rate-schemes/{id}/` | Delete — possible only for never-referenced schemes (PROTECT cascade) |

Permissions: read is `IsAuthenticated`; all write actions require
`CanManageConfig`.

The serializer (`RateSchemeSerializer`,
`apps/api/rate_schemes/serializers.py`) exposes `superseded` (computed
bool: `replaced_by_id is not None`) and `reference_counts` for the
outdated-schemes UI. `unit_label` is validated against the configured
units list (`apps/core/units.get_units_list`).

### 3.4 Edit-in-use block

`PUT/PATCH` against a referenced scheme returns **HTTP 409 Conflict**:

```json
{
    "detail": "Scheme is referenced; create a new version instead of editing.",
    "supersede_url": "https://.../api/rate-schemes/{id}/supersede/",
    "reference_counts": {
        "plan_task_count":     5,
        "task_count":          12,
        "task_template_count": 1
    }
}
```

The frontend uses this to surface "Create new version" affordances
and explain *why* an edit was blocked.

### 3.5 Template guard

When `TaskTemplate.generate_task(container, est_qty, ...)` runs, it
checks `template.rate_scheme.replaced_by_id is None`. If the template
points at a superseded scheme, it raises `SchemeSupersededError`
(`apps/core/services.py`), which the API translates to **HTTP 409
Conflict** with a message identifying the template:

> Template "Hourly Labor — assembly" references a superseded
> RateScheme. Update the template before adding tasks from it.

Same guard fires on `WorksheetService.add_task_from_template` if no
explicit `rate_scheme_id` override is supplied.

The shop owner is forced to deliberately decide whether the template
should adopt a new scheme or pick a different one. Silent retroactive
change to template behavior is never acceptable.

### 3.6 Picker filtering

All scheme pickers
(`WorkItemForm.svelte`, `TaskTemplateManager.svelte`,
`RateSchemeManager.svelte`) default to active schemes only. The
frontend gets this for free from the `GET /api/rate-schemes/`
default filter; passing `?include_superseded=true` reveals the full
set for the outdated-schemes view.

### 3.7 PROTECT cascade

`replaced_by`, `Task.rate_scheme`, `PlanTask.rate_scheme`, and
`TaskTemplate.rate_scheme` all use `on_delete=PROTECT`. A scheme that
has entered the lineage is effectively un-deletable — orphaning a
work item or breaking the supersession chain is structurally
impossible.

---

## 4. Task / PlanTask billing

Both `Task` and `PlanTask` carry billing identity directly via
`TaskBase` (the abstract base in `apps/jobs/models.py`). The full
field shape lives in `docs/designs/jobs-tasks-and-worksheets.md`.
Recap of the billing fields:

| Field | On TaskBase / Task / PlanTask | Notes |
|---|---|---|
| `rate_scheme` | declared on Task and PlanTask | FK to `RateScheme` (PROTECT). NOT NULL on both. |
| `active_modifiers` | declared on Task and PlanTask | JSON list of modifier keys |
| `est_qty` | inherited from `TaskBase` | nullable on Task; `PlanTask.clean()` rejects null |
| `est_worker_time` | inherited from `TaskBase` | DurationField for scheduling |
| `actual_qty` | declared on Task only | Decimal nullable; worker-entered for `entered_qty` schemes |

### 4.1 compute_amount and effective_rate

Both models implement the uniform atom interface
`compute_amount(active_modifiers=None) → Decimal`:

```python
class Task:
    def compute_amount(self, active_modifiers=None):
        qty = self.rate_scheme.get_actual_qty(self)  # algorithm-aware
        charge = self.rate_scheme.compute_charge(qty, self.active_modifiers)
        return charge.quantize(Decimal('0.01'))

class PlanTask:
    def compute_amount(self, active_modifiers=None):
        if not self.rate_scheme_id or self.est_qty is None:
            return Decimal('0.00')
        charge = self.rate_scheme.compute_charge(self.est_qty, self.active_modifiers)
        return charge.quantize(Decimal('0.01'))
```

Both `compute_amount` results are quantized to 2 decimal places (cents):
`compute_charge` is `qty * effective_rate`, and a modifier-adjusted rate
can carry more than 2 decimals, so the unrounded product would surface
extra digits on the task detail page and in worksheet totals.

The `active_modifiers` parameter is accepted to match the atom
interface but is ignored — both use `self.active_modifiers`. PlanTask
has no actuals, so it always uses `est_qty`. Task uses the algorithm
to resolve qty:

| Algorithm | Task.compute_amount qty source |
|---|---|
| `elapsed_time` | sum of Blep durations in hours |
| `entered_qty` | `task.actual_qty or 0` |
| `flat_fee` | `1` |

`effective_rate()` on both returns
`rate_scheme.effective_rate(self.active_modifiers)`.

### 4.2 actual_qty semantics

| Algorithm | `Task.actual_qty` meaning |
|---|---|
| `elapsed_time` | unused; should stay `None` (qty derived from Bleps) |
| `entered_qty` | what the worker entered; `None` until entered |
| `flat_fee` | unused; should stay `None` |

The "Actual qty" input on `TaskDetailPage` writes `actual_qty`; only
visible for `entered_qty` schemes.

### 4.3 est_qty semantics

| Algorithm | `est_qty` meaning |
|---|---|
| `elapsed_time` | estimated billable hours (often equals `est_worker_time` but doesn't have to) |
| `entered_qty` | estimated piece / minute count |
| `flat_fee` | implicitly 1 if used; usually left null |

`est_qty` is **never** modified by work activity. It stays as the
estimate. `actual_qty` and Bleps capture what happened. This
separation enables estimate-vs-actuals reporting (not yet built;
see §14).

---

## 5. Estimate

`Estimate` (`apps/estimates/models.py`, `db_table = 'estimates'`,
decorated with `@history`) is the customer-facing quote. One Job may
have multiple Estimates over time (revisions); only one may be
`accepted`.

### 5.1 Status machine

| Status | Constant | Meaning |
|---|---|---|
| `draft` | `STATUS_DRAFT` | Editable; line items can be added/removed |
| `open` | `STATUS_OPEN` | Sent to customer; awaiting response |
| `accepted` | `STATUS_ACCEPTED` | Terminal. Customer accepted; one per Job |
| `rejected` | `STATUS_REJECTED` | Terminal |
| `expired` | `STATUS_EXPIRED` | Terminal; auto on `expiration_date` (manual today) |
| `superseded` | `STATUS_SUPERSEDED` | Terminal; replaced by a new revision |

Valid transitions (`Estimate.clean()`):

```
draft       → open, rejected
open        → accepted, superseded, rejected, expired
accepted, rejected, expired, superseded → (terminal)
```

`Estimate.clean()` also enforces:

- At least one `EstimateLineItem` must exist before transitioning out
  of `draft`.
- Only one `accepted` Estimate per Job.

### 5.2 Auto-set dates

`Estimate.save()`:

- On entry to `open`: sets `sent_date = now()` if unset; sets
  `expiration_date = now() + est_expire_days` (Configuration key,
  default 30 days) if unset.
- On entry to a terminal: sets `closed_date = now()` if unset.
- `created_date`, `sent_date`, `closed_date` are immutable once set.

### 5.3 Versioning (revision)

`EstimateService.revise_estimate(pk)`
(`apps/estimates/services.py`):

1. Validates parent is **not** in `draft` (drafts edit in place).
2. Creates a new `Estimate` with `parent=self`,
   `version=self.version+1`, status `draft`, same `estimate_number`.
3. Copies line items field-by-field. Source rows are **not** carried
   forward — the new revision starts with no atom claims, so a fresh
   worksheet revision (or manual adds) can wire it up.
4. Marks the parent `superseded`.

The `unique_together = ['estimate_number', 'version']` constraint
keeps revisions distinct.

### 5.4 Document numbering

Pointer: `CLAUDE.md` "Document Numbering". `EstimateService.create_for_job`
calls `NumberGenerationService.generate_next_number('estimate')`,
which uses Configuration keys `estimate_number_sequence` and
`estimate_counter`.

---

## 6. EstimateLineItem and EstimateLineItemSource

### 6.1 EstimateLineItem

Inherits `BaseLineItem` (description, qty, units, price, line_number,
accounting_category, taxable_override, tax_rate_override; see
`apps/core/models.py`). Declared in `apps/estimates/models.py`,
`db_table = 'est_li'`. Adds:

- `estimate` — FK to `Estimate` (CASCADE).
- `source_template` — nullable FK to `TaskTemplate`. Preserves the
  catalog reference for direct-estimate line items so the carry-over
  service can spawn matching atoms when the estimate is accepted.

Line item deletion goes through
`LineItemService.delete_line_item_with_renumber` per the rule in
CLAUDE.md.

### 6.2 EstimateLineItemSource

The polymorphic claim table that links a line item to its source
atom(s).

```python
EstimateLineItemSource:
    source_id           AutoField PK
    estimate_line_item  FK → EstimateLineItem (CASCADE, related_name='sources')
    source_type         CharField — 'plan_task' | 'plan_material'
    source_pk           PositiveIntegerField

    Meta:
        db_table = 'estimate_line_item_sources'
        unique_together = [('source_type', 'source_pk')]
```

Atoms are `PlanTask` and `PlanMaterial` (the worksheet-side atoms;
the real-side equivalents — `Task` and `Material` — feed the invoice
wizard, owned by the invoicing doc). The unique constraint on
`(source_type, source_pk)` enforces **whole-atom claim at the database
level**: an atom can be referenced by at most one estimate line item.

`source.resolve()` returns the concrete atom instance.

Unlike `InvoiceLineItemSource`, this constraint is **not** scoped by
Estimate status. Worksheet revisions copy atoms (creating new
PlanTask / PlanMaterial instances), so the constraint never needs to
fire across revisions in practice.

CASCADE on `EstimateLineItem` deletion: deleting a line item releases
its claims. Superseding / rejecting / expiring an Estimate does **not**
release claims on the plan side.

### 6.3 Atom-to-line-item shapes

| Source rows on a line item | What it represents |
|---|---|
| 0 | Manually authored, or pre-filled from a `PriceListItem` (no atom backs it) |
| 1 | Single-atom conversion (bulk send-all or a wizard pick of one atom) |
| N | Wizard-grouped from multiple atoms |

A single-atom line item copies the atom's description, units, qty,
and price across. Multi-atom line items: when every atom is a task
(`PlanTask` / `Task`) sharing one `RateScheme` and identical
`active_modifiers`, the line is **summarized** — `units` from the
scheme, `qty` = summed quantities (`est_qty` on the estimate side,
actuals on the invoice side), `price` = the common effective rate.
Any other multi-atom bundle (a material atom present, mixed schemes,
or mixed modifiers) falls back to blank description, `units = 'none'`,
`qty = 1`, `price = sum(compute_amount)`.

---

## 7. Billable atoms

An **atom** is a billable unit on the plan side or real side. Atoms
implement a uniform interface:

- `compute_amount(active_modifiers=None) → Decimal`
- a description (`atom.description` or `atom.name` for tasks)
- units (from the rate scheme on tasks; from the atom for materials)
- an `accounting_category` (derived for tasks; direct on materials)
- a source-pointer identity (model + pk)

Atom families:

| Plan side | Real side | Owner doc |
|---|---|---|
| `PlanTask` | `Task` | this doc / jobs-tasks |
| `PlanMaterial` | `Material` | materials doc |

Bleps are read-only detail under their task's atom; they are never
claimed as atoms themselves. **Whole-task billing**: there is no
business reason to split bleps from one Task across multiple line
items; if such a need arises, the Task itself gets split first.

Atom claim semantics:

- An atom is **available** if no source row points at it.
- An atom is **claimed** if a source row exists pointing at it.
- The DB-level unique on `(source_type, source_pk)` makes
  double-claim impossible.

A worksheet exposes two top-level operations on its atoms:

1. **Send all atoms to estimate** — bulk 1:1 conversion of every
   unclaimed atom to its own line item with one source row.
2. **Open wizard to group atoms** — interactive grouping of atoms
   into one or more line items.

Both produce source-backed line items. They can be run in any order
or sequence (e.g. wizard-group some, bulk-send the rest later).

Out of scope: partial-atom billing (per-hour or per-unit slicing of a
single atom across line items), and flat-rate task billing without
atoms. See §14.

---

## 8. EstimateWizardService

`EstimateWizardService` (`apps/estimates/services.py`) is the
orchestration layer for the wizard. The line-items-from-atoms logic
(`add_atoms_to_new_line_item`, `add_atoms_to_line_item`,
`remove_atoms_from_line_item`, the in-sync / bundle-summary helpers) is
shared with `InvoiceWizardService` via `BaseWizardService`
(`apps/core/wizard.py`); `EstimateWizardService` subclasses it, supplies
a small config block plus model hooks, and keeps the estimate-specific
methods (`open_for_worksheet`, `get_source_pool`,
`send_all_atoms_to_estimate`).

### 8.1 Methods

| Method | Purpose |
|---|---|
| `open_for_worksheet(worksheet)` | Returns the worksheet's draft Estimate, creating one if none exists. Refuses if the worksheet's estimate is non-draft (the `final` worksheet should have prevented this). |
| `get_source_pool(worksheet)` | Walks PlanTasks and PlanMaterials on the worksheet, returns a flat pool of atoms. Each atom carries `type`/`id`/`description`, the `qty`/`rate`/`units`/`amount` breakdown (from the shared `BaseWizardService._atom_detail`), and claim state: `available`, `claimed_by_current` (this estimate), `claimed_by_other` (a different estimate on the same job). |
| `add_atoms_to_new_line_item(estimate, atoms)` | Creates a new `EstimateLineItem` with a source row per atom. Single-atom case copies atom's description/units/qty/price; multi-atom case summarizes a uniform same-scheme task bundle, else falls back to blanks (see §6.3). |
| `add_atoms_to_line_item(line_item, atoms)` | Appends source rows to an existing line item. If the line item was **in sync** before (`price == round(sum(sources)/qty, 2)`), it is re-derived: a uniform same-scheme task bundle is re-summarized (units/qty/price), otherwise qty is kept and the per-unit price recomputed. An overridden line item is left untouched. |
| `remove_atoms_from_line_item(line_item, source_ids)` | Deletes source rows. Same re-derive-if-in-sync rule as `add_atoms_to_line_item`. Deletes the line item if no sources remain. |
| `send_all_atoms_to_estimate(worksheet)` | Bulk 1:1 conversion of every unclaimed atom on the worksheet to its own line item. Not transactionally wrapped — partial success is acceptable; caller can re-run. |

Conflict handling: `add_atoms_to_*` raise `EstimateClaimConflict` when
the unique-constraint trips (e.g. concurrent claim from another
session); the API turns that into HTTP 409.

### 8.2 In-sync rule

A line item is "in sync" if its per-unit price equals
`round(sum(source.compute_amount()) / qty, 2)`. In-sync line items
recompute when sources change. Manual price overrides stick across
add/remove. Identical rule on the invoice side.

### 8.3 API endpoints

Estimate wizard endpoints live on `EstimateViewSet`
(`apps/api/estimates/views.py`):

| Verb + path | Action method | Calls |
|---|---|---|
| `GET /api/estimates/{id}/source-pool/` | `source_pool` | `EstimateWizardService.get_source_pool(worksheet)`; returns `{atoms: []}` if no worksheet |
| `POST /api/estimates/{id}/line-items-from-atoms/` | `line_items_from_atoms` | `add_atoms_to_new_line_item(estimate, atoms)` |
| `POST /api/estimates/{id}/line-items/{lid}/add-atoms/` | `add_atoms` | `add_atoms_to_line_item(line_item, atoms)` |
| `POST /api/estimates/{id}/line-items/{lid}/remove-atoms/` | `remove_atoms` | `remove_atoms_from_line_item(line_item, source_ids)` |

Worksheet-side wizard helpers live on `EstWorksheetViewSet`
(`apps/api/worksheets/views.py`):

| Verb + path | Action method | Calls |
|---|---|---|
| `POST /api/est-worksheets/{id}/send-all-atoms-to-estimate/` | `send_all_atoms_to_estimate` | `EstimateWizardService.send_all_atoms_to_estimate(worksheet)` — returns `{estimate_id, estimate_number, created_count}` |
| `POST /api/est-worksheets/{id}/open-estimate/` | `open_estimate` | `EstimateWizardService.open_for_worksheet(worksheet)` — returns `{estimate_id, estimate_number}` without auto-claiming any atoms |

Request body shape for atoms: `{atoms: [{type: 'plan_task'|'plan_material', id: N}, ...]}`.

Permissions: read is `IsAuthenticated`; write actions require
`CanManageJobs`.

### 8.4 Frontend components

| Component | Path | Role |
|---|---|---|
| `EstimateWizardPage.svelte` | `frontend/src/routes/estimates/` | Page shell. Two-column layout (source pool left, line items right). Loads estimate + line-items + source-pool on mount; `reloadAfterAction` refreshes line items and reconciles atom states locally |
| `WizardSourcePool.svelte` | `frontend/src/components/estimates/` | Renders the flat atom list; binds `selectedAtoms` to the page. Each atom is a `WizardAtomRow`. The invoice wizard has its own task-grouped `WizardSourcePool.svelte` that reuses the same row. |
| `WizardAtomRow.svelte` | `frontend/src/components/wizards/` | One source-pool atom row, shared by both wizards: checkbox + `description — qty units × $rate = $total` + claim state |
| `WizardLineItemCard.svelte` | `frontend/src/components/wizards/` | One line-item card with its source rows; surfaces "Add Here" and per-source remove |
| `WizardActions.svelte` | `frontend/src/components/wizards/` | Bottom action bar (Discard draft, Return to estimate detail) |
| `CatalogPicker.svelte` | `frontend/src/components/` | Unified search over `TaskTemplate` + `PriceListItem` + Manual; shared by worksheet/job atom-add and direct-estimate line-item add |
| `EstimateLineItemModal.svelte` | `frontend/src/components/` | Modal for direct (no-atom) line item create/edit on the Estimate detail page |

The invoice-side wizard is structurally parallel — same source pool,
add-atoms, remove-atoms, in-sync rule. Components are partially
shared (e.g. `WizardLineItemCard`, `WizardActions`); the invoice
WizardSourcePool is its own component
(`frontend/src/components/invoices/WizardSourcePool.svelte`) because
the atom shape differs (Tasks + Materials, not PlanTasks +
PlanMaterials). Pointer: invoicing doc.

---

## 9. Atom carry-over (Worksheet → Job)

When an `Estimate` transitions to `accepted`, the
`estimate_accepted` signal fires
(`apps/estimates/signals.py:trigger_atom_carry_over` receiver), which
calls `AtomCarryOverService.carry_over_for_estimate(estimate)`.

### 9.1 What carries

`AtomCarryOverService` (`apps/estimates/carry_over.py`) does its work
in one `transaction.atomic()` block:

**Phase A — worksheet atoms** (only if a worksheet exists on the
estimate):

- Each `PlanTask` becomes a `Task` on the Job, with:
  - `name`, `description` copied
  - `source_plan_task = pt` (the carry-over idempotency hook)
  - `rate_scheme`, `active_modifiers`, `est_qty`, `est_worker_time` copied
  - `actual_qty = None`
  - `parent_task = None` (always; hierarchy emerges later in execution)
- Each `PlanMaterial` becomes a `Material` on the Job, paired to a
  `Task` if the PlanMaterial was attached to a `PlanTask` on the
  worksheet (via `Material.source_plan_material` and a lookup through
  `Task.source_plan_task`).

**Phase B — direct-estimate line items** (carry-over for line items
without worksheet sources):

- Line items with `source_template` set → spawn a `Task` from the
  template, copying `template.rate_scheme`, `default_active_modifiers`,
  `description`; `est_qty = line_item.qty`.
- Line items with `price_list_item` set (and no `source_template`) →
  spawn a `Material` on the Job from the PLI.

Manual line items with no template / PLI ref do not auto-create
atoms; the user adds tasks/materials manually as the work shapes up.

### 9.2 Idempotency

Each kind of carry-over has a different idempotency key:

| Carry-over | Idempotency key |
|---|---|
| Worksheet PlanTask → Task | `Task.source_plan_task` (OneToOne; same PlanTask cannot carry over twice) |
| Worksheet PlanMaterial → Material | `Material.source_plan_material` |
| Line-item with source_template → Task | `Task.source_template` already exists on the Job |
| Line-item with PLI → Material | `Material.price_list_item` already exists on the Job |

Re-firing the signal (e.g. by saving the estimate again) is safe —
each `_carry_over_*` and `_create_*_from_line_item` checks the
appropriate filter and skips.

### 9.3 Job status side effects

Separate from carry-over, `estimate_status_changed_for_job` walks the
Job through `submitted → approved` when its estimate is accepted, via
the receiver in `apps/estimates/signals.py`. Pointer:
`docs/designs/jobs-tasks-and-worksheets.md` §12 for the full
receiver-by-receiver behavior.

---

## 10. AccountingCategory pass-through

`AccountingCategory` (`apps/core/models.py`) is required on
`RateScheme` (NOT NULL). Every billable concept either references a
RateScheme (and inherits AC) or carries AC directly (Materials with
no PLI; Expenses).

### 10.1 Where AC comes from

| Object | AC source |
|---|---|
| `RateScheme` | own field, required |
| `Task` | `task.rate_scheme.accounting_category` (via `Task.effective_accounting_category`) |
| `PlanTask` | `plan_task.rate_scheme.accounting_category` (via `PlanTask.effective_accounting_category`) |
| `TaskTemplate` | `template.rate_scheme.accounting_category` (via `TaskTemplate.effective_accounting_category`) |
| `Material` (PLI-linked) | `material.price_list_item.accounting_category` (copy/derivation; materials doc owns this) |
| `Material` (freeform) | direct on the material |
| `EstimateLineItem` from atom | derived from the atom's effective AC at line-item creation; snapshot |
| `EstimateLineItem` from PLI | from `pli.accounting_category`; snapshot |
| `EstimateLineItem` manual | user-entered |

Each model that has an `effective_accounting_category` property
exposes it for serializers and the wizard's pool building. Wizard
single-atom line-item creation pulls `category` from the atom's
effective AC; multi-atom creation only sets `category` if all atoms
share one.

### 10.2 What changes when AC moves

`RateScheme.accounting_category` is in `FROZEN_FIELDS`. Once the
scheme is referenced, AC change requires supersession. Existing tasks
that referenced the old scheme keep the old AC; future tasks pick the
new scheme and get the new AC.

For line items, AC is **snapshotted** at line-item creation time —
it's a field on `BaseLineItem`, not derived live. Once the estimate
is sent (out of draft), the snapshot is permanent.

---

## 11. UI: Estimate Detail page

Route: `#/estimates/:id` → `EstimateDetailPage.svelte`
(`frontend/src/routes/estimates/`).

### 11.1 Layout

Top-down:

1. **JobHeader** — same component used on the Job detail page.
2. **Toolbar** — back link, page title (with `superseded` styling
   when applicable), status pill (interactive `<select>` for users
   with `can_manage_jobs` when transitions are allowed), action
   buttons.
3. **Field table** — estimate number, job link, worksheet link
   (if any), version, status, dates.
4. **Line items table** (`LineItemTable.svelte`) — line items with
   per-row Edit / move-up / move-down / Delete affordances when the
   estimate is editable (`isDraft` and `can_manage_jobs`).
5. **EstimateLineItemModal** — direct (no-atom) line item create/edit.

### 11.2 Action buttons

| Status | Button | Handler |
|---|---|---|
| `draft` | "Send Estimate" | disabled stub (PDF + email not implemented) |
| `draft` | "Mark as Sent" | `POST /api/estimates/{id}/mark-open/` |
| `draft` | "Add Line Item" | opens `EstimateLineItemModal` |
| `draft` (with worksheet) | "Open atoms wizard" | navigates to `#/estimates/{id}/wizard` |
| `open` | "Revise Estimate" | `POST /api/estimates/{id}/revise/` → opens new draft revision |
| any | status `<select>` | `PATCH /api/estimates/{id}/` with `{status}` (when transitions are valid) |

Editing rules: `canEdit = canManageJobs && status === 'draft'`.

The legacy HTML view at `/estimates/` still exists in
`apps/estimates/views.py` but is deprecated.

---

## 12. UI: Estimate Wizard page

Route: `#/estimates/:id/wizard` → `EstimateWizardPage.svelte`
(`frontend/src/routes/estimates/`).

### 12.1 Flow

Two columns:

- **Source pool** (left) — `WizardSourcePool` shows every PlanTask
  and PlanMaterial on the worksheet. Each atom is clickable
  (checkbox-style) when `available`; locked-out otherwise with a
  "claimed by …" indicator. The component binds `selectedAtoms`.
- **Line items** (right) — list of `WizardLineItemCard`s for the
  current estimate, each with its source rows expanded. Each card
  has an "Add Here" button (enabled when atoms are selected) that
  appends the selected atoms via `add-atoms`. A trailing "New line
  item" placeholder card has its own "Add Here" that calls
  `line-items-from-atoms`. A "+ Manual" button drops a blank line
  item via the standard line-items POST.

After every action, `reloadAfterAction` re-fetches estimate + line
items, then **reconciles** atom states client-side from the new
claims map without re-fetching the source pool. `claimed_by_other`
atoms (snapshotted at mount) are left alone.

### 12.2 Bottom actions

`WizardActions` provides:

- **Discard draft** — `DELETE /api/estimates/{id}/?confirm=true` (sends
  the confirm token to the discard-draft path on `EstimateService.discard_draft`).
- **Return** — navigate to `/estimates/{id}` (the detail page).

### 12.3 Wizard entry from worksheet

The Worksheet detail page (`WorksheetDetailPage.svelte`) has:

- "Send all atoms to estimate" — `POST /api/est-worksheets/{id}/send-all-atoms-to-estimate/`,
  then navigate to the estimate detail page.
- "Open wizard to group atoms" — `POST /api/est-worksheets/{id}/open-estimate/`
  (creates the draft estimate without claiming atoms), then navigate
  to `/estimates/{eid}/wizard`.

---

## 13. Signals

Three signals, all defined in `apps/estimates/signals.py` and fired
by `Estimate.save()`. Brief recap; the receiver-by-receiver
behavior lives in `docs/designs/jobs-tasks-and-worksheets.md` §12.

| Signal | Fires when | Receiver | Effect |
|---|---|---|---|
| `estimate_status_changed_for_worksheet` | worksheet-status mapping changes | `update_estworksheet_status` | bulk-updates linked EstWorksheets to draft/final/superseded |
| `estimate_status_changed_for_job` | draft→open or any→accepted | `update_job_status` | walks the Job through submitted/approved with HistoryEntry rows |
| `estimate_accepted` | any→accepted | `trigger_atom_carry_over` | calls `AtomCarryOverService.carry_over_for_estimate(estimate)` |

The `estimate_accepted` signal is the one this doc owns. The other
two are summarized here only so the carry-over fits into the
estimate-acceptance picture; their full behavior is in jobs-tasks.

---

## 14. Unfinished work

- **Default rate scheme for worker quick-add** — the worker-side
  `WorkItemForm` flow currently still requires the worker to pick a
  rate scheme. The 2026-05-02 doc designed (but did not ship) a
  `default_worker_rate_scheme` Configuration key that the form would
  silently default to when the user lacks `can_manage_jobs`. Pairs
  with the broader worker-friendly mid-job task creation work.

- **Estimate-vs-actuals reporting** — once `est_qty` and
  `actual_qty` (or Bleps) coexist on Task, a per-job and per-template
  variance report becomes trivial. "We're at 7 of 12 estimated" or
  "How accurate are estimates for this template?" are both unblocked
  by data but not yet built.

- **Auto-fill `est_worker_time` when scheme units are hours** —
  when the chosen scheme's `unit_label` represents hours, `est_qty`
  and `est_worker_time` are typically the same number. The form
  could pre-fill, with override. Needs a way to mark which configured
  unit means "hour".

- **`@history` decorator on `Task`** — billing-config changes on a Task
  (rate-scheme reassignment, modifier toggles) are a normal
  estimating-related event but don't surface in the Job HistoryPanel.
  Tracked in `jobs-tasks-and-worksheets.md`.

- **`accounting_category` required on `EstimateLineItem`** — part of the
  project-wide line-item AC-NOT-NULL migration tracked in
  `architecture-and-conventions.md`.

- **Review `AtomCarryOverService.carry_over_for_estimate` in detail.**
  The current behaviour is documented in §9 — Phase A worksheet atom
  copy (PlanTask → Task, PlanMaterial → Material), Phase B
  direct-estimate line-item spawn (Tasks from `source_template`,
  Materials from `price_list_item`), with idempotency keyed by
  `source_plan_task` / `source_plan_material` / `source_template` /
  `price_list_item`. Not confident this matches the intended
  customer-acceptance workflow; review against real estimate-accept
  scenarios and revise.

- **Worksheet lock-on-generate vs lock-on-send (open question).** When
  an Estimate is generated from a worksheet, the current code keeps the
  worksheet in `draft` until the Estimate transitions out of `draft`
  (mapped by `Estimate._get_worksheet_status`: `draft → draft`,
  `open/accepted/rejected → final`, `superseded → superseded`). This
  allows both surfaces to be refined together until "Send Estimate"
  flips both to locked. The alternative — lock the worksheet on
  generation regardless of estimate status — is stricter and matches
  the older mental model. Either policy is defensible; revisit if the
  edit-both-in-draft mode causes confusion.

- **Estimate send (PDF + email).** The "Send Estimate" button on
  `EstimateDetailPage` is a disabled stub. When built, follow the PO
  pattern in `PurchaseOrderEmailService.send_po`: rely on the
  `@history` decorator on `Estimate` to capture the status change
  (`draft → open` via `mark_open`), then hand-write an `action`
  HistoryEntry to record the email-send event with the recipient
  list (the recipients aren't model fields, so the decorator has
  nothing to capture for them). Pair with PDF generation (parallel
  to `apps/purchasing/pdf.py`) and reuse `OutboundEmailService.send_email`.

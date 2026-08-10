# Estimates and Billing

Reference for the estimating side of Minibini: `RateScheme` as an
editable service-price preset, task-owned money (a `Task` stamps a
permanent copy of a preset's pricing at creation time), the
billable-atom abstraction, the estimate wizard, the job-atom projection
(documents-as-lenses), acceptance crystallizing hand-lines into atoms
(Tasks or Materials — a plain, no-descriptor line stays a document
line), and AC pass-through.
Read alongside:

- `docs/designs/architecture-and-conventions.md` — service-layer
  pattern, `LineItemMixin`, exception hierarchy
  (`ServiceError` / `NotFoundError` / `SchemeInactiveError`).
- `docs/designs/jobs-and-tasks.md` — `Task`, `Material`
  (the Job's work atoms), the Work surface, populate paths, signal
  receivers (`estimate_accepted`, `estimate_status_changed_for_job`).
- `docs/designs/materials-inventory-and-purchasing.md` — `Material`
  (the other atom family), `InventoryItem`.
- `docs/designs/invoicing-and-expenses.md` — the parallel invoice
  wizard built on the same source-row pattern.
- `CLAUDE.md` — status constants, document-numbering service,
  `AccountingCategory` shape, line-item delete rule.

> **Job-owns-atoms model.** Work atoms (`Task`, `Material`) live
> directly on the **Job**, created at any status (including `draft`). The
> former planning layer — `EstWorksheet`, `PlanTask`, `PlanMaterial`, the
> worksheet API, and worksheet→job carry-over — has been **removed**.
> An `Estimate` is now a **lens** over the job's atoms: each line item
> optionally links to one atom via `EstimateLineItemSource`; a line with no
> source is a **hand-line**. See §7 and §9.

---

## 1. What this doc owns

This doc owns:

- `RateScheme` model, modifier algebra, `is_active` retirement.
- Task-owned money: the task's own `qty_source` / `rate` / `unit_label` /
  `accounting_category` / `active_modifiers` block, `stamp_from_scheme`,
  and `source_scheme` provenance. Billing identity on `ServiceItem` (the
  live FK to `RateScheme`) and the `est_qty` / `actual_qty` semantics.
- `Estimate`, `EstimateLineItem`, `EstimateLineItemSource`.
- `ChangeOrder`, `ChangeOrderLineItem`, the agreement-of-record
  composition over (Estimate + accepted COs).
- The atom abstraction (atoms are Tasks and Materials; whole-atom
  billing).
- `EstimateWizardService`, the wizard endpoints, and the wizard UI.
- `EstimateAcceptanceService` — what fires when an Estimate is accepted
  (hand-line → Task/Material crystallization, or nothing for a plain
  line; earmarks).
- AC pass-through rules from RateScheme → Task / line item.

It does **not** own:

- The Job/Task shape or status machines (jobs-tasks doc).
- The Material side of the atom family beyond the pieces the wizard
  touches (materials doc).
- Invoice-side wizard or `InvoiceLineItemSource` (invoicing doc).
- Service-layer mechanics, mixin catalog, permission atoms (architecture
  doc).

---

## 2. RateScheme

`RateScheme` (`apps/jobs/models.py`, `db_table = 'rate_schemes'`,
FK field `rate_scheme`, API `/api/rate-schemes/`) is the **service
price list** — the catalog of named, priced services the shop performs.
It owns the math (rate, algorithm, modifiers) and the `AccountingCategory`
(and therefore taxability / QBO income mapping). A `RateScheme` is a
**freely editable preset** (task-owned-money Phase 1): a `Task` copies
its pricing fields onto itself at creation time
(`Task.stamp_from_scheme`, §3) and that copy — not a live FK — is the
task's price of record from then on, so editing a preset never reprices
an already-stamped task. `ServiceItem` still holds a **live** FK to
exactly one `RateScheme` and reads its rate directly (no stamping) until
it in turn generates a Task. (Fixed one-off charges are authored as a
plain hand-line — see §4.5 — not a RateScheme; a plain hand-line has no
job atom backing it and stays a document line forever.)

### 2.1 Identity fields

| Field | Type | Notes |
|---|---|---|
| `rate_scheme_id` | AutoField PK | |
| `name` | CharField(100), unique | display name; e.g. "CNC Router", "Hourly Labor", "Tap a hole" |
| `description` | TextField, blank | longer admin explanation |
| `algorithm` | CharField(20), choices | one of `elapsed_time`, `entered_qty`, `percentage` |
| `rate` | Decimal(10,2) | the per-unit price for `elapsed_time`/`entered_qty`; holds the percent value for `percentage` (negative = discount) |
| `unit_label` | CharField(50) | the customer-facing unit; validated against the configured units list (`apps/core/units.py`). `elapsed_time` schemes are pinned to `'hour'` — `RateScheme.clean()` raises a `unit_label` `ValidationError` for any other value, and the rate-scheme serializer force-sets `unit_label='hour'` for `elapsed_time` (so the field is redundant, not user-chosen, once that algorithm is picked). `percentage` still defaults `unit_label='none'`. |
| `modifiers` | JSONField | list of `{key, label, percent}` dicts |
| `accounting_category` | FK → `AccountingCategory` (PROTECT) | required, NOT NULL |
| `is_active` | BooleanField, default `True` | retirement flag — hides the preset from *new* task stampings only (§3.1); does not affect tasks already stamped from it |

`accounting_category_id` is enforced at the application layer in
`RateScheme.clean()` (raises `ValidationError`).

### 2.2 Algorithms

| Algorithm | Constant | Quantity source | Typical use |
|---|---|---|---|
| `elapsed_time` | `RateScheme.ELAPSED_TIME` | sum of `Blep` durations on the task in hours | hourly labor (assembly, bench work); unit is always `'hour'` (pinned — see §2.1) |
| `entered_qty` | `RateScheme.ENTERED_QTY` | `Task.actual_qty` | machine-minutes, piece work; worker enters the count |
| `percentage` | `RateScheme.PERCENTAGE` | n/a — document-layer computation only | surcharges and discounts (rush fee, volume discount) |

> **`flat_fee` removed.** RateScheme no longer has a `flat_fee` algorithm.
> A fixed one-off or per-unit charge (tap a hole, plywood coating, setup
> fee) is authored as a **plain hand-line** on the Estimate/CO — it has
> no job atom backing it and stays a document line forever (see §4.5;
> the `jobs.Fee` atom that briefly replaced this algorithm was itself
> retired 2026-08-09). `copy_active_modifiers()` collapses any legacy
> `{'flat_fee_price': …}` dict to `[]`.

#### The `percentage` algorithm

`percentage` is a **document-level adjustment** — it never backs a `Task`
or `ServiceItem`. Calling `RateScheme.effective_rate()` or
`get_actual_qty()` on a percentage service raises `ValueError`; the estimate
and invoice serializers reject it; `TaskService.create_direct` rejects it;
and `GET /api/rate-schemes/?task_applicable=true` excludes it. The
`ServiceItemManager` (Catalog area, `/catalog/service-items` — moved out of
Settings; `materials-inventory-and-purchasing.md` §17) still displays
percentage types so they can be managed; the task-creation pickers never
show them.

`rate` holds the **percent value**: `10` means 10%, `-5` means a 5% discount.
Negative rates are allowed only for `percentage` services (all other
algorithms must have `rate >= 0`, enforced by `RateScheme.clean()` and
`validate_data.py`).

**`compute_adjustment_amount`** (`apps/core/adjustments.py`) is the helper
that resolves a percentage line's dollar amount at the document layer:

```python
compute_adjustment_amount(adjustment_line, sibling_lines) → Decimal
```

1. Reads the line's own `adjustment_percent` snapshot (§10.3) — **never**
   the live `adjustment_service.rate`, which is provenance only — and the
   line's `adjustment_target_categories` M2M set.
2. Sums `total_amount` (`qty × price`) of every **non-adjustment** sibling
   line whose `accounting_category_id` is in the target set. An **empty**
   target set matches **all** non-adjustment siblings.
3. Adjustment lines are explicitly skipped — no stacking: an adjustment
   never sums other adjustments.
4. Result: `(adjustment_percent / 100) × base_total`, quantized to
   `Decimal('0.01')` (nearest cent).

`RateScheme.get_actual_qty(task)` resolves the right quantity per
algorithm:

```python
ELAPSED_TIME → (Decimal(sum(blep.elapsed.total_seconds())) / 3600).quantize(0.01)
ENTERED_QTY  → task.actual_qty or Decimal('0')
```

`get_actual_qty()` raises `ValueError` for a `percentage` scheme
(percentage services are document adjustments, not task billing).

The `ELAPSED_TIME` result is quantized to 2 decimal places: a raw
seconds/3600 division is non-terminating (~28 digits) and would overflow
the line item `qty` field (`max_digits=10`) when carried into the invoice
wizard.

### 2.3 Modifiers

Each modifier in the scheme's `modifiers` JSON list is a dict:

```json
{"key": "messy", "label": "Messy materials", "percent": 10}
```

- `key`: stable identifier. Selected on `ServiceItem.default_active_modifiers`
  (a list of keys) and, at task-stamping time, resolved by
  `Task.stamp_from_scheme` into full `{key, label, percent}` snapshot
  dicts on `Task.active_modifiers` (§3) — not live keys.
- `label`: display string shown in checkboxes and on the line item.
- `percent`: additive percent surcharge over the base rate.

Active modifiers stack additively: messy (+10%) + doublestick (+5%)
= +15% on `rate`. Validation that a `modifier_keys` argument to
`stamp_from_scheme` is a subset of the scheme's modifier keys is up to
the form/serializer layer — unknown keys are silently dropped (`dict(m)
for m in scheme.modifiers if m.get('key') in keys`).

**`active_modifiers` shape differs by model.**
`ServiceItem.default_active_modifiers` is a **list of modifier-key
strings**. `Task.active_modifiers` is a **list of `{key, label,
percent}` snapshot dicts** — the resolved modifiers as they stood at
stamp time, not scheme-relative keys, so a later edit to the scheme's
`modifiers` list never reaches an already-stamped task. The
`copy_active_modifiers()` helper (`apps/jobs/models.py`, used by
`Task.copy_fields()` when cloning a task) deep-copies each snapshot
dict; legacy shapes it can't resolve without a scheme — a bare dict (the
old `{'flat_fee_price': …}` encoding) or a list of bare modifier-key
strings (the pre-Phase-1 snapshot shape) — collapse to `[]`.

### 2.4 Effective rate and compute (preset preview)

```python
RateScheme.effective_rate(active_modifiers)
    elapsed_time / entered_qty
        → rate * (1 + sum(m.percent for m in modifiers if m.key in active_modifiers) / 100)
    percentage
        → raises ValueError (computes at the document layer, not per-unit)

RateScheme.compute_charge(qty, active_modifiers)
    → qty * effective_rate(active_modifiers)
```

**Preset preview only.** `RateScheme.effective_rate()` /
`compute_charge()` / `get_actual_qty(task)` are never called against a
stamped Task's own money math — `Task.effective_rate()` /
`compute_amount()` / `compute_estimate_amount()` (§4.1) read the task's
own fields instead. These RateScheme methods back the
`RateSchemeManager` preview and the rate-scheme serializer's detail
view, and are still what `ServiceItem`'s deferred service line uses
(§6.4) before a Task exists.

There is no minimum-charge floor on RateScheme — that field was
removed.

### 2.5 Reference checks

`RateScheme.is_referenced()` returns `True` if any `Task` has ever
stamped from this preset (`self.stamped_tasks.exists()`), or any
`ServiceItem` points at it. **Display only** (the outdated-schemes UI,
reference counts) — it no longer gates edits or deletes; a stamped task
owns a permanent copy of its money fields, so editing or deleting a
referenced preset can't reprice or orphan anything (§3).

`RateScheme.reference_counts()` returns:

```python
{
    'task_count':          self.stamped_tasks.count(),
    'service_item_count': ServiceItem.objects.filter(rate_scheme=self).count(),
}
```

Display only — the outdated-schemes UI and the serializer's
`reference_counts` field.

---

## 3. Task-owned money: stamping and preset retirement

**Supersession is gone (task-owned-money Phase 1).** A `RateScheme` is
no longer frozen once referenced, and there is no `replaced_by` /
`replaced_at` / `FROZEN_FIELDS` / `supersede()` machinery — all
retired. In its place: a `Task` copies a preset's pricing fields onto
itself at creation time and that copy becomes the price of record, so
the preset itself stays a plain, freely editable row.

### 3.1 stamp_from_scheme

`Task.stamp_from_scheme(scheme, modifier_keys=None)`
(`apps/jobs/models.py`) runs before a task's first save, on **every**
creation path (`TaskService.create_direct`, `TaskService.create_from_template`,
`ServiceItem.generate_task`). It sets, on the task itself:

- `qty_source` — copied from `scheme.algorithm` (`elapsed_time` /
  `entered_qty`; a `percentage` scheme raises `ValueError` — percentage
  services are document adjustments and can never stamp a task).
- `rate`, `unit_label`, `accounting_category` — copied straight from
  the scheme.
- `active_modifiers` — `modifier_keys` (a list of `scheme.modifiers`
  `key` strings; `None` activates none) resolved into full `{key,
  label, percent}` snapshot dicts (§2.3).
- `source_scheme` — the scheme FK itself, kept **only as provenance**.
  It is never read by any compute path (`Task.effective_rate()` /
  `get_actual_qty()` / `compute_amount()` / `compute_estimate_amount()`
  all read the task's own fields, §4.1) — deleting the scheme later
  (`on_delete=SET_NULL`) can never disturb an already-stamped task's
  billing.

Because the copy is permanent, editing (or even deleting) a `RateScheme`
after tasks have stamped from it never reprices or orphans them — the
frozen-fields rule this section used to describe no longer applies to
anything.

### 3.2 is_active retirement

`RateScheme.is_active` (default `True`) replaces the old
`replaced_by`/`replaced_at` pair. Retiring a preset only hides it from
*new* stampings:

- The creation-time guard lives in the calling service, not
  `stamp_from_scheme` itself: `TaskService.create_direct`,
  `TaskService.create_from_template`, and `ServiceItem.generate_task`
  each check `scheme.is_active` and raise `SchemeInactiveError`
  (`apps/jobs/models.py`) when it's `False` and the caller didn't pass
  `allow_inactive_scheme=True`. The API translates `SchemeInactiveError`
  to **HTTP 409 Conflict**, e.g.:

  > Template "Hourly Labor — assembly" references an inactive
  > RateScheme. Update the template before adding tasks from it.

- `allow_inactive_scheme=True` bypasses the rejection. The intended
  callers are acceptance-time crystallization
  (`generate_task(allow_inactive_scheme=True)`, §9.1/§14.11) — a hand-line
  whose scheme was retired after the estimate was authored can still
  crystallize into a Task — and any path that must faithfully replay a
  historical stamping.
- Retiring (or reactivating) a preset never touches tasks that already
  stamped from it — `is_active` is read only at stamp time.

### 3.3 API

| Verb + path | Behavior |
|---|---|
| `GET /api/rate-schemes/` | List active entries by default (`is_active=True`) |
| `GET /api/rate-schemes/?include_inactive=true` | List all entries |
| `GET /api/rate-schemes/?task_applicable=true` | Active, non-percentage entries — the task-creation picker's feed (always active regardless of `include_inactive`) |
| `GET /api/rate-schemes/{id}/` | Retrieve any entry |
| `POST /api/rate-schemes/` | Create — `CanManageConfig` |
| `PUT/PATCH /api/rate-schemes/{id}/` | Edit any field directly — `CanManageConfig`. No 409, no frozen-fields rejection, referenced or not. |
| `POST /api/rate-schemes/{id}/retire/` | Flip `is_active` to `False` — `CanManageConfig`. Rejected (400) if this scheme is the current `default_rate_scheme` (§3.4). |
| `POST /api/rate-schemes/{id}/reactivate/` | Flip `is_active` back to `True` — `CanManageConfig` |
| `DELETE /api/rate-schemes/{id}/` | Delete — allowed even with stamped tasks (`Task.source_scheme` is `SET_NULL`); blocked (409 via `ProtectedError`) while a `ServiceItem` still references it (`ServiceItem.rate_scheme` is `PROTECT`), and rejected (400) if this scheme is the current `default_rate_scheme` (§3.4) |

Permissions: read is `IsAuthenticated`; all write actions require
`CanManageConfig`.

Create/update/delete/retire/reactivate route through
`ConfigurationService.{create,update,delete,retire,reactivate}_rate_scheme`
(`apps/core/services.py`). The serializer exposes `reference_counts`
(display only, §2.5) and `is_default` (§3.4, computed) and validates
`unit_label` against the configured units list (`apps/core/units.get_units_list`).

### 3.4 Default preset

The `default_rate_scheme` Configuration key (string-encoded `RateScheme`
pk, or `''` — see `data-constraints.md` §1.1) preselects the CREATE
dropdown on the manual task-creation form (`WorkItemForm`) for every
user, manager or worker alike. Set via the RateSchemeManager's default
preset picker (`PATCH /api/settings/` with `default_rate_scheme`,
explicit Save — not auto-committed on change) — that endpoint stays
`CanManageConfig`-gated.

Everywhere else, the default's *identity* is read from `is_default`, a
computed field on `RateSchemeSerializer` (`True` iff the row's pk equals
the configured `default_rate_scheme`, one Configuration read per
response via serializer-context caching, never per row). The list/
retrieve endpoints are `IsAuthenticated`-only, so this is how a
permissionless worker's create-task form preselects the default — it
never calls `/api/settings/` for it. (RM browser-testing note 3: it used
to, and a worker's fetch there 403'd silently, so the dropdown never
preselected and submitting without picking one hit the
required-`rate_scheme` validation error.)

- `PATCH /api/settings/` rejects a value that isn't blank or an
  **active** RateScheme id.
- Retiring or deleting the current default preset is **rejected outright**
  (`ValidationError`, "This Rate Scheme is the default for new tasks —
  change the default first."), not silently cleared — an RM browser-testing
  finding: the old auto-clear-on-retire behavior gave no warning that the
  scheme being retired was the default. `ConfigurationService.
  _raise_if_default_rate_scheme` is the single gate, called from
  `retire_rate_scheme`, `delete_rate_scheme`, and the general
  `update_rate_scheme` path whenever `is_active` transitions
  `True → False` (a plain field-level `PATCH {"is_active": false}` goes
  through the same guard, not just `retire()`). The caller must change
  `default_rate_scheme` to something else (or blank) first.
- RateSchemeManager (the Settings → Pricing UI) doesn't wait for the
  server rejection: the row matching the current default renders a
  greyed-out "default" note in place of the Retire/Delete buttons
  entirely, so the guard is mostly unreachable from the SPA — it's a
  backstop for any other caller.

### 3.5 Picker filtering

Task-creation pickers request `?task_applicable=true` (active,
non-percentage only). The RateSchemeManager (outdated-schemes /
retirement UI) defaults to active-only and reveals the full set via
`?include_inactive=true`.

### 3.6 Post-stamp rate changes

Once stamped, a task's `rate` is an ordinary money-gated field — a
manager/PM or `can_manage_financials` user can edit it directly at any
time (`PATCH .../tasks/{id}/ {rate: ...}`), same as any other
`MONEY_FIELDS` entry. `source_scheme` provenance stays put on an
ordinary field-level edit like that one — it only moves via the
edit-task Rate Scheme **dropdown**, a separate, deliberate re-pick
described next (§3.6a).

### 3.6a Edit-task restamp (RM browser-testing note 5)

The edit-task form (`WorkItemForm.svelte`, edit mode) offers a **Rate
Scheme** dropdown fed by the same `?task_applicable=true` list the
create-mode dropdown uses (active, non-percentage presets), preselected
to the task's current `source_scheme`:

- A currently-**retired** `source_scheme` (absent from the
  task-applicable list) renders as a disabled placeholder option labeled
  with its name + "(retired)".
- A **null** `source_scheme` renders as a disabled "—" placeholder.
- Neither placeholder is a selectable **target** — real options are only
  active, non-percentage, task-applicable schemes, same as create mode.

Picking a **different** scheme (a genuine `change` event — re-selecting
the current value is naturally a no-op, nothing to build a same-value
reset path for) triggers a **client-side restamp**: the form prefills
`rate`/`unit_label`/`accounting_category` from the newly-picked scheme's
already-fetched list data, and replaces the modifier checkboxes
**wholesale** with the new scheme's definitions, none checked — the
user re-ticks before saving. Nothing persists until Save (explicit-save
doctrine); the reset path back to the original scheme's values is
A → B → A, each hop a real change that restamps — landing back on A
restamps to A's *own current* list data, not a memory of the task's
pre-edit values (a fresh pick of A means exactly A's current data, even
if A's preset has since been edited).

On Save, the PATCH carries the same full money block edit mode always
sends (`rate`/`unit_label`/`accounting_category`/`active_modifiers`,
money-gated as ever) **plus** `source_scheme` — but only when the
selection actually differs from the task's original provenance; an
unchanged re-select never adds the key.

**Backend:** `TaskSerializer.source_scheme` is writable on **UPDATE
only** — create keeps its `rate_scheme` server-stamp contract untouched
(`validate_source_scheme` rejects the field outright when there's no
instance yet, i.e. on create). `source_scheme` joined `MONEY_FIELDS`
(§10.1 in `jobs-and-tasks.md`), so the key's mere presence in a PATCH
gates on `CanManageJobOrPM`/`can_manage_financials` like every other
money field. Validation on write mirrors create's `rate_scheme` rules —
must exist, `is_active=True`, non-percentage — as field-shaped 400s
(no `allow_inactive_scheme` escape hatch here; a restamp is always a
deliberate pick from the CURRENTLY-offered target list). The server
does **not** re-derive the money block from the new `source_scheme` —
it just records the pointer; the client's `rate`/`unit_label`/
`accounting_category`/`active_modifiers` values in the same request
ARE the restamp (same precedent as the estimate Work-form's
client-computed stamp). A write where the money fields don't actually
match the new scheme's current data isn't rejected — it shows up as
drift on the task, which is the provenance pointer doing its job as an
audit trail, not a bug for the serializer to guard against.

A restamp PATCH reaches a **parent** task the same as any other
money-field edit: if the parent's own `rate` was `None` (deriving its
price from children, §4.1a), the restamp sets an explicit `rate` that
overrides the derivation — the existing rule, not new behavior.

**Outsourced work (task-owned-money Phase 5)** is the one *suggested*
path to that same edit: a flat task linked to a PO line
(`materials-inventory-and-purchasing.md` §10a) can be the target of a
**task-rate prompt** once that PO is reconciled with a per-line final
cost that differs from what was ordered — "update the selling rate to
final × markup?" A human must explicitly accept it; accepting issues
the exact same `PATCH .../tasks/{id}/ {rate: ...}` call described
above, so nothing here is a second money-writing code path. Declining
leaves the quoted rate untouched, and nothing about the decline is
persisted. Full mechanics — qualifying-line rule, the markup config,
accept/decline — live in `materials-inventory-and-purchasing.md` §10a.

### 3.6b Edit-task money-field gating uses `can_write_money`, not `can_manage` (RM browser-testing note 6)

`WorkItemForm.svelte`'s edit-mode money-field gating (the Rate Scheme
dropdown, Rate/Unit, Accounting Category, and modifier checkboxes — every
`{#if effectiveCanWriteMoney}`/`disabled={!effectiveCanWriteMoney}` site)
reads `item.can_write_money`, **not** `item.can_manage`. The two look
similar but test different things: `can_manage`
(`JobScopedCanManageMixin`, §3 of `users-and-permissions.md`) is the
`can_manage_jobs`-atom-or-PM test only, while the server's actual
money-write gate (`TaskSerializer._can_write_money`, §"Task money-field
writes" in `users-and-permissions.md`) additionally accepts the
`can_manage_financials` atom. A financials-only caller (no
`can_manage_jobs`, not the job's PM) therefore has `can_manage=False` but
`can_write_money=True` — gating the UI on `can_manage` disabled/greyed
fields the server would happily accept the write for.

`can_write_money` is a read-only `SerializerMethodField` on
`TaskSerializer` that calls `_can_write_money()` directly, so it is
*literally* the same predicate the server enforces on write — not a
second, independently-maintained approximation of it. `_can_write_money`
takes an optional `job` argument: the `validate()` write path calls it
with no argument (resolves via `self.instance`/context, correct for a
single-instance POST/PATCH); `get_can_write_money` passes `obj.job`
explicitly, because DRF's `ListSerializer` never sets `self.instance`
per-row on a shared child serializer — reading `self.instance` there
would silently misreport for every row in a task list (e.g.
`GET /api/jobs/{id}/tasks/`), not just the detail view. Same pattern
`JobScopedCanManageMixin.get_can_manage` already uses for `can_manage`.

Create mode has no `item` yet, so it keeps reading the `canManage` prop
(a caller override, default `true`) — there's no server-computed
create-time equivalent to fetch ahead of the POST; the server's own
create-time `MONEY_FIELDS` gate is enforced independently by
`TaskSerializer.validate()` regardless of what the create form renders.

`can_manage` on the Task serializer keeps its original job-management
meaning unchanged (non-money task affordances, e.g. the manager-only
actions in `users-and-permissions.md` §3) — this was purely a matter of
routing the *money-field* gate to the field that actually matches the
server's money-write test.

---

## 4. Task billing

**Task-owned money (Phase 1).** `Task` carries its own permanent money
block directly — not a live FK to `RateScheme` — stamped once at
creation by `Task.stamp_from_scheme` (§3.1). The full field shape lives
in `docs/designs/jobs-and-tasks.md` §4.4. Recap of the billing fields:

| Field | On Task | Notes |
|---|---|---|
| `qty_source` | own field | `'elapsed_time'` / `'entered_qty'` (`Task.QTY_ELAPSED` / `QTY_ENTERED`); copied from `scheme.algorithm` at stamp time. Never `'percentage'` — percentage schemes can't stamp a task. |
| `rate` | own field | Decimal, nullable. `effective_rate()` returns `0.00` when `None` (e.g. a task cloned or built without a scheme). |
| `unit_label` | own field | CharField, default `'none'` |
| `accounting_category` | own field | FK → `AccountingCategory` (PROTECT), nullable at the DB level but required by the API serializer (§10) |
| `active_modifiers` | own field | JSON list of `{key, label, percent}` **snapshot** dicts — resolved at stamp time, not live scheme keys (§2.3) |
| `source_scheme` | own field | FK → `RateScheme` (`SET_NULL`, `related_name='stamped_tasks'`) — **provenance only**, never read for money math |
| `est_qty` | inherited from `TaskBase` | nullable on Task |
| `est_worker_time` | inherited from `TaskBase` | DurationField for scheduling |
| `actual_qty` | declared on Task only | Decimal nullable; worker-entered for `entered_qty` schemes |

### 4.1 compute_amount, compute_estimate_amount, effective_rate

`Task` implements the uniform atom interface
`compute_amount(active_modifiers=None) → Decimal` (the **invoice** view —
bills actuals) plus a parallel `compute_estimate_amount()` (the
**estimate** view — bills `est_qty`). Both compute entirely from the
task's own fields — **no RateScheme lookup**:

```python
class Task:
    def effective_rate(self):
        # Own rate + own active_modifiers surcharges.
        if self.rate is None:
            return Decimal('0.00')
        pct = sum(Decimal(str(m.get('percent', 0))) for m in (self.active_modifiers or []))
        return (self.rate * (1 + pct / 100)).quantize(Decimal('0.01'))

    def get_actual_qty(self):
        # Own qty_source — no RateScheme lookup.
        if self.qty_source == self.QTY_ELAPSED:
            return timedelta_to_hours(sum(blep elapsed)).quantize(Decimal('0.01'))
        return self.actual_qty or Decimal('0')

    def compute_amount(self, active_modifiers=None):
        # Invoice side: qty from actuals (bleps / actual_qty).
        return (self.get_actual_qty() * self.effective_rate()).quantize(Decimal('0.01'))

    def compute_estimate_amount(self, active_modifiers=None):
        # Estimate side: qty is est_qty (what the job is *expected* to cost).
        return ((self.est_qty or Decimal('0')) * self.effective_rate()).quantize(Decimal('0.01'))
```

This is the crux of **documents-as-lenses** (§7): the *estimate* projects
`est_qty` via `compute_estimate_amount`; the *invoice* bills the locked
`actual_qty` of a complete task via `compute_amount`. Both are quantized
to cents — a modifier-adjusted rate can carry more than 2 decimals.

The `active_modifiers` parameter on both methods is accepted only to
match the shared `BillableAtom` interface (the same signature `Material`
uses) — both **ignore** it and read `self.active_modifiers`.
`get_actual_qty()` resolves the qty source:

| `qty_source` | `Task.get_actual_qty()` source |
|---|---|
| `elapsed_time` | sum of Blep durations in hours |
| `entered_qty` | `task.actual_qty or 0` |

An `elapsed_time` task's `unit_label` is always `'hour'` (copied from
the `elapsed_time`-pinned scheme it stamped from — §2.1) — so this qty
is always a count of hours.

`effective_rate()` quantizes to 2 decimal places (cents): a percentage
modifier divides by 100, so `rate × (1 + percent/100)` can carry more
than 2 places (e.g. `99.99 × 1.05 = 104.9895`). The per-unit rate is a
money value that is copied straight onto a line item's `price` field (a
2-decimal `DecimalField`), so it must be trimmed at the source — every
caller that uses it as a price (the estimate wizard's single-atom and
"send all atoms" paths, the bundle summary, the source-pool detail) is
then safe without having to remember its own `.quantize()`.

### 4.2 actual_qty semantics

| Algorithm | `Task.actual_qty` meaning |
|---|---|
| `elapsed_time` | unused; should stay `None` (qty derived from Bleps) |
| `entered_qty` | running total of worker-entered increments; `None` until first entry |

For `entered_qty`, **every write is an add — there is no replace path**
(`TaskLifecycleService.add_actual_qty`, locked with `select_for_update`;
signed increments, total floored at zero; negative = correction). Entry
surfaces, all showing the scheme's `unit_label`:

- **Settle-first stop** — an own stop on an `entered_qty` task returns a
  `prior_session_qty` conflict and mutates NOTHING: the session keeps
  running (the band stays honest) while the SPA asks "how many did this
  session produce?" (leading with "Entered so far: N unit" when a total
  exists). The flagged re-post `{prior_qty_handled: true, add_qty?: N}`
  applies the increment and closes the blep in ONE transaction — a failed
  entry can never half-run. Empty submit = skip (stop without an entry);
  modal Cancel aborts the stop (session keeps running). The "This
  completes the task" checkbox turns the submit into one atomic
  `complete` with `add_qty` instead (which also closes the blep).
  Recording the count is part of the work — that's why stop waits.
- **Prior-session settle on task-switch, clock-out, task-cancel, and
  task-block** — `start-work`, `/api/shifts/clock-out`,
  `POST /api/tasks/{id}/cancel/`, and `POST /api/tasks/{id}/block/`
  return the same `prior_session_qty` conflict (mutating nothing) when
  the user's own gesture would close an open `entered_qty` session; the
  SPA prompts (naming the task), settles (add / complete / skip), and
  re-posts with `prior_qty_handled: true` (block re-carries the reason).
  Cancel-the-task keeps the count for the same reason cancelled
  elapsed-time tasks keep their bleps — actuals are history even on dead
  tasks (no completes-checkbox on cancel or block: completing while
  cancelling is contradictory, and a blocked task isn't done). Own
  gestures only — on-behalf starts, stops, and clock-outs, and internal
  bulk cancels (CO acceptance) never prompt. Cancelling the prompt
  aborts the gesture.
- **TaskDetailPage add field** — the header's **Actual** stat chip
  shows the running total ("N {unit}") with a signed delta input and
  explicit Add button beside it (never blur-commit: adds are not
  idempotent). Hidden on terminal and blocked tasks. Success briefly
  swaps the chip's header label to "added ✓".
- **Completion settle-up** — completing an `entered_qty` task ALWAYS
  round-trips through the prompt: the bare `complete` answers
  `needs_actual_qty` + `current_qty`, the modal shows "Entered so far: N
  — any more to add?", and the re-post carries the final increment as
  `add_qty` (zero = nothing more; negative = correction; resulting
  total must be > 0, applied under the row lock).

Every own explicit gesture is now **settle-first** — nothing mutates
until the prompt resolves, so no prompt modal ever has to survive a
refresh of the page under it (jobs-and-tasks.md §10.1a).
Paths that close bleps without a prompt (on-behalf gestures, takeover,
admin closes, `complete_task` closing teammates' bleps, historical
entry) just leave the running total short; the completion settle-up is
the backstop, so the billed number is always one a human confirmed.

### 4.3 est_qty semantics

| Algorithm | `est_qty` meaning |
|---|---|
| `elapsed_time` | estimated billable hours — kept in step with `est_worker_time` by pair-fill (below) |
| `entered_qty` | estimated piece / minute count |

`est_qty` is **never** modified by work activity. It stays as the
estimate (and drives `compute_estimate_amount`). `actual_qty` and Bleps
capture what happened (and drive `compute_amount`). This separation
enables estimate-vs-actuals reporting (not yet built; see §16).

**Hour-unit pair-fill (`hours_pair_fill`, `apps/jobs/services.py`).** For
any Task whose rate scheme has `unit_label == 'hour'` — keyed on the
scheme's *unit*, not on the `elapsed_time` algorithm, so an `entered_qty`
scheme labeled in hours gets the same treatment — `est_qty` (billable
hours) and `est_worker_time` (schedulable duration) are one number in two
encodings. `TaskService.create_direct`, `update_task`, and `assign` all
call `hours_pair_fill(scheme, est_qty, est_worker_time)`: when exactly one
of the pair is supplied, it derives the other; when both are supplied it
passes them through untouched. This is a **convenience, not an
invariant** — an unconvertible or out-of-range `est_qty` passes through
unchanged rather than being rejected here, so `Task.full_clean()` still
renders the normal contract-shaped 400. Separately,
`ServiceItem.generate_task` fills `est_worker_time` from `est_qty` when
the caller doesn't supply one, so estimate acceptance, change-order
acceptance, and add-from-template all produce schedulable tasks without an
assign-time worker-time prompt for hour-unit schemes. The SPA's
`WorkItemForm` shows a single "Estimated hours" input for hour-unit
schemes and writes both fields (jobs-and-tasks.md §9.5).

### 4.4 Material as a billable atom

`Material` (`apps/inventory/models.py`) is the second billable atom on
the Job. It implements `compute_amount() → quantity × sell_price`,
exposes `effective_accounting_category`, and is claimed by a line item
exactly like a Task. Full model shape is in
`materials-inventory-and-purchasing.md`.

### 4.5 Fee — retired

**Fee retired 2026-08-09** — the `jobs.Fee` model (`apps/jobs/models.py`,
`db_table = 'fees'`) was deleted
(`apps/jobs/migrations/0062_delete_fee.py`, alongside
`apps/estimates/migrations/0045_alter_changeorderlineitem_is_material_and_more.py`
and `apps/invoicing/migrations/0024_alter_invoicelineitemsource_source_type.py`).
There is no longer a pure-money job atom. A **plain hand-line** — no
`service_item`, no `inventory_item`, `is_material=False` — never
crystallizes into a job atom on acceptance (§9.1); it stays a document
line on the Estimate/CO forever, and it is **always billable** in the
sense that it needs no lifecycle gate (there's no atom readiness state
to check — it's just text, qty, and a price on the document). It
transits to an Invoice later via an **agreement-line reference**
(`InvoiceLineItem.agreement_estimate_line` / `agreement_co_line`, the
`compose_agreement` / `seed_from_agreement` / `restore_agreement_line`
machinery in `apps/invoicing/services.py`), not via a Fee atom + claim.
See `invoicing-and-expenses.md` for the invoice-side mechanics.

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
| `expired` | `STATUS_EXPIRED` | Terminal; auto-set by the `mark_estimates_expired` scheduled command once `expiration_date` has passed (also settable manually) |
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

`expiration_date` is **frozen** at the moment of send — it's a stamped
datetime, not derived live from `est_expire_days`. Changing the
Configuration key later does **not** retroactively re-date already-open
estimates; it only affects estimates sent after the change.

### 5.2a Automatic expiry — `mark_estimates_expired`

The `mark_estimates_expired` scheduled command
(`apps/estimates/management/commands/mark_estimates_expired.py`) is the
mechanism that actually flips estimates to `expired`. Each run:

1. Selects every `open` estimate whose (non-null) `expiration_date` is at
   or before `now()`.
2. For each, transitions it to `expired` via
   `EstimateService.update_status(pk, STATUS_EXPIRED)` (under
   `select_for_update`, re-checking it's still `open`), and writes a
   `system`-attributed `action` HistoryEntry ("Auto-expired …").
3. Counts `open` estimates with a **NULL** `expiration_date` separately and
   skips them (`skipped_no_expiry` in the run summary) — they never auto-expire.

Because the transition is `open → expired`, it fires the §9.3 invariant:
the parent Job is driven to `rejected`. The command is part of the
scheduled-process machinery (`ScheduledProcessCommand` + cron) documented
in `architecture-and-conventions.md` §9; it runs daily.

### 5.3 Versioning (revision)

`EstimateService.revise_estimate(pk)`
(`apps/estimates/services.py`):

1. Validates parent is **not** in `draft` (drafts edit in place).
2. Creates a new `Estimate` with `parent=self`,
   `version=self.version+1`, status `draft`, and the same `estimate_number`
   as the parent (the job number — the revision is the `version`, see §5.4).
3. Copies line items field-by-field and **moves** each line's
   `EstimateLineItemSource` rows onto the revision (reassigns the FK, not a
   copy — the source `unique_together` forbids two claims on one atom). So a
   revision stays atom-backed and the job atom remains claimed exactly once;
   a source is lost only when the user deletes that line. (The superseded
   estimate keeps its frozen line items but no longer references the atoms —
   the new revision is the live lens over them.)
4. Marks the parent `superseded`.
5. Snapshots the live deliverables onto the now-superseded parent
   (`DeliverableService.snapshot_document(estimate=parent)`), freezing the
   scope the customer saw. The customer portal renders that snapshot for
   the out-of-date estimate; the new draft keeps using the live list. See
   `jobs-and-tasks.md` §12.9 (trigger 1 + portal read rule).

The `unique_together = ['estimate_number', 'version']` constraint
keeps revisions distinct.

### 5.3a Adjustment lines and `revise_estimate`

`revise_estimate` preserves adjustment lines exactly like normal lines:
`adjustment_service_id`, `adjustment_percent` (the price-of-record
snapshot — §10.3), and the `adjustment_target_categories` M2M set are
all copied onto the new revision's line items. The revision's adjustment line
amounts are frozen at the inherited values until a line-item change triggers
auto-recompute (see §5.3b). Source atom rows (`EstimateLineItemSource`) are
moved onto the new line items as usual (see §5.3).

### 5.3b Adjustment line services and endpoints

**Auto-recompute:** Adjustment lines recompute automatically on every line-item
mutation — `add_line_item`, `add_line_item_from_pli`, `update_line_item`,
`delete_line_item`, `add_adjustment_line`, and all three wizard atom-mutation
methods. (Direct authoring `add_line_item` / `add_line_item_from_pli` were
removed in the 2026-06 consolidation, then **restored** — the estimate detail
page authors hand-lines again alongside atom-backed lines; hand-lines
crystallize into atoms at acceptance — catalog and bare-material lines
into Materials, deferred-service lines into Tasks, and plain lines stay
document-only forever.) There is no manual recalculate step. Freeze is implicit:
all mutations are draft-gated, so once an estimate leaves `draft` the stored
price is frozen automatically.

`EstimateService` (`apps/estimates/services.py`) provides:

| Method | Behavior |
|---|---|
| `add_adjustment_line(estimate, *, adjustment_service_id, target_category_ids=[])` | Creates a new `EstimateLineItem` backed by a PERCENTAGE `RateScheme` at the end of the estimate's line list, calls `_recompute_adjustments`, and returns the saved line. Raises `ValidationError` if the estimate is not `draft` or the service is not `PERCENTAGE`. |
| `_recompute_adjustments(estimate)` | Internal helper. Calls `recompute_adjustments()` over all `EstimateLineItem` rows for the estimate. Called after every line-item mutation. |

**API endpoints:**

| Verb + path | Behavior |
|---|---|
| `POST /api/estimates/{id}/adjustment-lines/` | Body: `{adjustment_service: <PK>, target_category_ids: [<AC PKs>]}`. Returns 201 with the serialized line item (price already computed). Returns 400 if not draft or service is not PERCENTAGE. Permission: `CanManageJobs` (or the job's PM). |

**`compose_agreement` surfacing.** `compose_agreement(job)` line dicts carry
`is_adjustment` (bool), `adjustment_service_id`, `percent` (the line's own
`adjustment_percent` snapshot — never the live `adjustment_service.rate`,
which is provenance only — or `None` for non-adjustment lines), and
`target_category_ids` for
estimate-origin lines. CO-origin lines always have falsey adjustment fields
(adjustments are estimate-only).

### 5.4 Document numbering

One estimate tree per job — enforced at the service layer:
`EstimateService.create_for_job` refuses a second non-superseded estimate
(2026-07-04; previously only the API viewset checked). New *versions* come
only from `revise_estimate`, which creates the revision directly and then
supersedes the parent. It also refuses a job past the quoting phase
(2026-07-19): estimates start only on `draft`/`submitted` jobs — a
hand-approved or duplicated-as-approved estimate-less job skipped the
negotiation and doesn't get one retroactively. The estimate panel hides
Start Estimate with a hint on such jobs. The estimate's identity *is* the job's: the
`estimate_number` **is just the job number** (e.g. `JOB-2026-0001`), the same
across every revision. The revision lives in the separate `version` field — it
is **not** baked into the number. It is set by `EstimateService.create_for_job`
/ `create_direct` at creation and
by `revise_estimate` on each revision (which sets the same number, bumps
`version`). The `unique_together = ['estimate_number', 'version']` constraint
keeps revisions distinct. The customer tracks one number across the
conversation; the UI shows the revision by displaying `{estimate_number}-{version}`
(e.g. `JOB-2026-0001-2`) — that dash-joined form is a *display* concatenation,
not the stored value. (The old `estimate_number_sequence` / `estimate_counter`
Configuration keys are no longer used for estimates.)

### 5.5 Serializer: computed `total`

`EstimateSerializer` (`apps/api/estimates/serializers.py`) exposes a
read-only `total` `SerializerMethodField` — `Σ line.qty × line.price`
across the estimate's line items, quantized to cents. It is the
authoritative document total the job-overview Scope block consumes
(`frontend/src/lib/jobOverview.js`) rather than recomputing client-side
(adjustment/percentage lines make a client-side `qty*price` walk
fragile). `ChangeOrderSerializer` (`apps/api/change_orders/serializers.py`)
exposes the same-named field but a different figure — see §14.2. Both
are per-object `SerializerMethodField`s with no queryset annotation, so
an unfiltered list view (e.g. the global estimates list) pays one extra
query per row; see `docs/designs/LATER.md` for the N+1 note.

---

## 6. EstimateLineItem and EstimateLineItemSource

### 6.1 EstimateLineItem

Inherits `BaseLineItem` (description, qty, units, price, line_number,
accounting_category; see `apps/core/models.py`; the per-line
`taxable_override`/`tax_rate_override` fields were removed 2026-07-21 —
taxability reads `accounting_category.taxable` directly). Declared in
`apps/estimates/models.py`,
`db_table = 'est_li'`. Adds:

- `estimate` — FK to `Estimate` (CASCADE).
- `adjustment_service` — nullable FK to `RateScheme` (PROTECT). Set
  when this line is a percentage adjustment. A line with
  `adjustment_service_id` set is an **adjustment line**; one without is
  a normal line. **Provenance/identity only** since task-owned-money
  Phase 1 — still what *selects* a line as an adjustment, but never read
  for the dollar computation (see `adjustment_percent` below).
- `adjustment_percent` — nullable Decimal(6,2). Snapshot of
  `adjustment_service.rate` taken at line-creation time; the **price of
  record** — `compute_adjustment_amount` (§2.2) reads this field, never
  the live scheme (§10.3).
- `adjustment_target_categories` — M2M to `AccountingCategory`. The
  categories whose lines this adjustment applies to. Empty = all
  non-adjustment lines.
- `is_material` — BooleanField, default `False`. Marks a bare
  (no `inventory_item`, non-adjustment) freeform line as a
  **material**: at acceptance it crystallizes into a `Material`
  (established with a reverse-markup placeholder cost — §9.1)
  instead of staying a plain, uncrystallized hand-line. Invalid on a line that already has an
  `inventory_item` (already a catalog material) or that has an
  `adjustment_service` (document-only adjustments can't be materials) —
  enforced by `EstimateService._assert_is_material_only_on_bare_line`.
- `service_item` — nullable FK to `estimates.ServiceItem` (PROTECT,
  `related_name='+'`). Deferred service descriptor: the line carries the
  `ServiceItem`'s snapshotted price at authoring time, and the FK is the
  crystallization target that `on_accept` resolves to a `Task` (§9.1).

The serializer exposes a read-only `adjustment_service_detail` dict
`{name, rate, algorithm}` for display purposes when `adjustment_service`
is set. It also exposes `service_item` (writable FK PK, nullable) and a
read-only `service_item_detail` dict `{template_id, name}` (or `null`).

**`backing` / `backing_total` (2026-08, skeleton phase — never stored,
derived on every read).** `EstimateLineItemSerializer` exposes read-only
`backing` — one of `'adjustment'` / `'from_catalog'` / `'planned_work'` /
`'planned_materials'` / `'edited'` / `'hand'`, via the module-level
`derive_estimate_backing(line)` function
(`apps/api/estimates/serializers.py`) — and `backing_total` (the summed
source `compute_estimate_amount`/`compute_amount`, `null` when the line
has no sources; the "work totals $X" reference figure, independent of
`backing` itself). See §12.2 for the derivation order and the
chip vocabulary; `derive_estimate_backing`'s own docstring is the
authoritative source for the two post-acceptance quirks noted there.
The list/retrieve queryset prefetches `sources` (and the atoms they
resolve to) to keep this derivation N+1-free.

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
    source_type         CharField — 'task' | 'material'
    source_pk           PositiveIntegerField

    Meta:
        db_table = 'estimate_line_item_sources'
        unique_together = [('source_type', 'source_pk')]
```

Atoms are the Job's `Task` and `Material` (`SOURCE_TASK`,
`SOURCE_MATERIAL`). These are the **same** job atoms the
invoice lens claims (via `InvoiceLineItemSource`, owned by the invoicing
doc) — both documents are lenses over one set of atoms on the Job. The
unique constraint on `(source_type, source_pk)` enforces **whole-atom
claim at the database level**: an atom can be referenced by at most one
estimate line item at a time.

Because that constraint is *global* and `rejected`/`expired` are terminal,
a dead document holding claims would lock its atoms out of every future
estimate on the job — forever. So **entering `rejected` or `expired`
releases the claims**: `Estimate.save()` deletes the document's source rows
via `claims.release_estimate_claims` (2026-07-28), and `ChangeOrder.save()`
does the same through `release_change_order_claims`. `accepted` keeps its
rows — they are the agreement record — and `superseded` already holds none,
since `revise_estimate` re-points them. The release lives in `save()`
rather than a service so every writer is covered: the portal decline
endpoints, the expiry sweep, the status-transition actions, and the admin.
The line items themselves are untouched, so a rejected estimate stays a
readable frozen snapshot of what was offered — the same shape a superseded
one takes. This mirrors `InvoiceService.cancel` on the billing lens.

`source.resolve()` returns the concrete atom instance (`Task` or
`Material`).

CASCADE on `EstimateLineItem` deletion: deleting a line item releases
its claims. On revision, `revise_estimate` **moves** the source rows onto
the new line items (§5.3), so the live estimate is always the one lens
over the atoms; superseding/rejecting/expiring otherwise does not touch
claims.

**No source row outlives its atom.** `Material.delete()` and
`Task.delete()` call `purge_source_rows_for_atom`
(`apps/estimates/claims.py`), which drops the estimate-, CO-, and
invoice-lens source rows pointing at the deleted atom. This holds on
*every* deletion path — restock-to-zero (incl. the job-completion
loose-material release), PO sever, task/material delete, CO retirement — so
`resolve()` consumers never hit a dangling pk. The source serializers
additionally render a dangling row (pre-purge data) as `null` rather
than 500ing. Paths that must not delete a billed atom guard *before*
deleting (`_assert_not_invoiced`, the CO retirement skips); the purge is
the consistency backstop, not the guard.

### 6.3 Atom-to-line-item shapes

| Source rows on a line item | What it represents |
|---|---|
| 0 | A **hand-line** — manually authored, no atom backs it. Crystallizes at acceptance via the four-way discriminator (§9.1): `service_item` → Task, `inventory_item` → Material, `is_material` bare → established Material (reverse-markup cost), else → nothing (a plain line stays a document-only line forever). |
| 1 | Single-atom conversion (bulk send-all or a wizard pick of one atom) |
| N | Wizard-grouped from multiple atoms |

A single-atom line item copies the atom's description, units, qty,
and price across. For a solo Task atom this is `est_qty` × effective
rate on the estimate side, and actual qty (§2.2 `get_actual_qty`) ×
effective rate on the invoice side — including `elapsed_time` tasks,
which carry hours × rate rather than collapsing to `qty=1`/price=total.
This makes a solo elapsed-time line's shape match what a same-scheme
multi-task bundle produces for the identical work
(`InvoiceWizardService._task_qty_and_price`). Multi-atom line items: when every atom is a task
sharing one `RateScheme` and identical `active_modifiers`, the line is
**summarized** — `units` from the service price, `qty` = summed
quantities (`est_qty` on the estimate side, actuals on the invoice side),
`price` = the common effective rate. Any other multi-atom bundle (a
material atom present, mixed service prices, or mixed modifiers)
falls back to blank description, `units = 'none'`, `qty = 1`,
`price = sum(compute_amount)`.

### 6.4 Service-line authoring and the unified picker

`EstimateService.add_line_item_from_service(estimate_pk, service_item_pk, qty)` creates a **deferred service line** on a draft estimate — it snapshots the `ServiceItem`'s current values and stores the FK without minting a Task:

| Line field | Snapshot source |
|---|---|
| `description` | `service_item.template_name` (user-editable after creation) |
| `qty` | caller-supplied |
| `units` | `service_item.rate_scheme.unit_label` (or `'none'`) |
| `price` | `service_item.rate_scheme.effective_rate(service_item.default_active_modifiers)` |
| `accounting_category` | `service_item.effective_accounting_category` (from the rate scheme) |
| `service_item` | FK pointer; crystallizes to a `Task` at acceptance |

No `Task` is created at authoring time. The Task is created at acceptance by `on_accept` (§9.1, discriminator step 1), with `description=li.description` (the edited line description) and `allow_inactive_scheme=True` so a line whose scheme was retired after authoring can still crystallize.

**`_apply_material_ac_default`.** `is_material=True` bare lines with no explicit AC default to the `Configuration['default_material_accounting_category']` key (stored as a string `AccountingCategory` PK). `_apply_material_ac_default` resolves the key and raises `ValidationError` if the key is absent or the PK is stale. Plain (non-`is_material`) hand-lines still require an explicit AC. The key is editable via a "Default material category" picker (`DefaultMaterialCategorySetting.svelte`, extracted out of `AccountingCategories.svelte`), rendered in both Settings' Accounting and Pricing tabs; `PATCH /api/settings/` validates it as blank-or-active-category-id (`data-constraints.md` §1.1).

**API endpoint:**

| Verb + path | Behavior |
|---|---|
| `POST /api/estimates/{id}/line-items-from-service/` | Body: `{service_item: <PK>, qty: <N>}`. Returns 201 with the serialized line. Permission: `CanManageJobs`. |

**`PriceListPicker.svelte` — the unified picker.** Both the estimate detail page and the job task-list page use `PriceListPicker` as the single "Add line / Add Work" entry point. The component is a pure `onChoose` emitter — zero surface-specific logic. It searches service items and catalog inventory items in parallel via their respective `?search=` endpoints and emits one of:

| `onChoose` payload | Meaning |
|---|---|
| `{type: 'service', serviceItem}` | User picked a `ServiceItem` from the catalog |
| `{type: 'inventory', inventoryItem}` | User picked a catalog `InventoryItem` |
| `{type: 'freeform', typed, isMaterial}` | User typed a description; `isMaterial` checkbox sets the `is_material` flag |

On the **estimate detail page** (`EstimatePanel.svelte`, hosted at `#/jobs/:jobId/estimate/:docId`), the picker is followed by `EstimateAddLineForm.svelte`, which handles the post-selection form (qty, units, AC) and dispatches to the correct endpoint: `line-items-from-service/` for service picks, the standard `line-items/` POST for inventory or freeform picks.

On the **job task-list page** (`JobTaskListPage.svelte` → `TasksPanel.svelte`), the picker opens with `taskSurface={true}`: it offers only explicit **Add Task** / **Add Material** buttons (plus the service/inventory search) — there is no plain-freeform option on this surface, since a job-owned atomless charge doesn't exist (that's an Estimate/CO-only concept, §11.3). `handleChoose` routes a service pick or "Add Task" to `WorkItemForm` (service pick → Task via `/add-from-template/`; "Add Task" → manual mode, rate scheme picked in the form), and an inventory pick or "Add Material" to `MaterialModal` (`presetPli`, `presetDescription`, `defaultMaterialCategoryId`). See `docs/designs/jobs-and-tasks.md` §9.5.

---

## 7. Billable atoms (documents as lenses)

An **atom** is a billable unit owned by the **Job**: a `Task` or
`Material`. Atoms implement a uniform interface:

- `compute_amount(active_modifiers=None) → Decimal` (Task also has
  `compute_estimate_amount()` — the estimate-side projection of `est_qty`)
- a description (`atom.description` or `atom.name` for tasks)
- units (from the rate scheme on tasks; from the atom for materials)
- an `accounting_category` (derived for tasks via the rate scheme; direct on materials)
- a source-pointer identity (`source_type` + pk)

An `Estimate` and an `Invoice` are **lenses** over these job atoms: each
document's line items optionally link to an atom via its source table
(`EstimateLineItemSource` / `InvoiceLineItemSource`). The **estimate**
projects `est_qty` (`Task.compute_estimate_amount`); the **invoice** bills
the locked `actual_qty` of complete tasks (`Task.compute_amount`). A
line item with no source is a **hand-line** — a plain (no-descriptor)
hand-line never becomes an atom; it stays a document line and transits
to invoices via an agreement-line reference instead (§4.5,
`invoicing-and-expenses.md`).

| Atom | Owner doc | Estimate amount | Invoice amount |
|---|---|---|---|
| `Task` | this doc / jobs-tasks | `compute_estimate_amount` (est_qty) | `compute_amount` (actuals; task must be complete) |
| `Material` | materials doc | `compute_amount` (qty × sell_price) | same (must be consumed) |
| `Expense` (material-less) | invoicing doc | _(invoice-only)_ | `compute_amount` |

Bleps are read-only detail under their task's atom; they are never
claimed as atoms themselves. **Whole-task billing**: there is no
business reason to split bleps from one Task across multiple line
items; if such a need arises, the Task itself gets split first.

Atom claim semantics (per document):

- An atom is **available** if no source row of that document points at it.
- An atom is **claimed** if a source row exists pointing at it.
- The DB-level unique on `(source_type, source_pk)` makes
  double-claim impossible within one document table.
- **Claim state on the job detail page.** Each Task/Material
  serializer exposes a `claimed` boolean — true iff the atom is referenced
  by the job's **live (non-superseded) estimate**. Unclaimed atoms are
  pre-approval / released work that no current estimate lens covers.

### Wizard-pool billability gates (invoice side)

The invoice wizard's source pool (`InvoiceWizardService.get_source_pool`)
distinguishes between atoms that are available to bill and those that are not
yet ready:

| Atom type | Billable when |
|---|---|
| `Task` | `status == complete` |
| `Material` | `consumption_state == consumed` |
| `Expense` (material-less) | always (submitted is sufficient; no readiness gate) |

Non-billable atoms appear in the pool with `state='not_billable'` and a
`not_billable_reason` (`'task_incomplete'` or `'material_unconsumed'`).
`InvoiceEditView`'s `UncoveredWorkSection` (§12.1's invoice-side
counterpart; see `invoicing-and-expenses.md`) renders them dimmed and
non-selectable (`unselectableNote`) so the invoicer can see what is
pending without being able to add it yet.

`InvoiceWizardService._assert_atom_billable` is the service-side enforcement
point: it re-checks readiness when atoms are actually submitted to the wizard
(i.e. when `add_atoms_to_new_line_item` / `add_atoms_to_line_item` resolve
each atom), raising `ValidationError` if the readiness condition is not met.
(The estimate side has no readiness gate — it projects `est_qty`, which exists
the moment a Task is created.)

Out of scope: partial-atom billing (per-hour or per-unit slicing of a
single atom across line items). See §16.

---

## 8. EstimateWizardService

`EstimateWizardService` (`apps/estimates/services.py`) is the
orchestration layer for the wizard. It subclasses `BaseWizardService`
(`apps/core/wizard.py`), which owns the shared line-items-from-atoms logic
(`add_atoms_to_new_line_item`, `add_atoms_to_line_item`,
`remove_atoms_from_line_item`, the in-sync / bundle-summary helpers) with
`InvoiceWizardService`. The estimate subclass supplies a config block
(`container_attr='estimate'`, `source_fk='estimate_line_item'`,
`claim_conflict_exc=EstimateClaimConflict`) plus model hooks
(`_resolve_atom`, `_atom_source_type`, `_atom_computed_amount`,
`_atom_units`) that wire it to the Job's atoms, and `get_source_pool`.

The wizard projects the **Job's own atoms** (Tasks + Materials) — there is
no longer a worksheet source. (A plain hand-line never becomes an atom,
so it's never picked in the wizard either — it's authored directly on
the document, §6.4/§11.3.)

### 8.1 Methods

| Method | Purpose |
|---|---|
| `get_source_pool(estimate)` | Walks the estimate's **Job's** Tasks and Materials, returns a flat pool of atoms. Each atom carries `type` (`'task'`/`'material'`), `id`, `description`, the `qty`/`rate`/`units`/`amount` breakdown, `category_id`, and claim state: `available`, `claimed_by_current` (this estimate), `claimed_by_other` (a different estimate on the same job). Task amounts use `compute_estimate_amount` (`est_qty`). **Cancelled tasks are excluded** — estimates project planned work, and a cancelled task is not planned work (the *invoice* pool is the opposite: recorded actuals on a cancelled task stay billable — see `invoicing-and-expenses.md`). |
| `add_atoms_to_new_line_item(estimate, atoms)` | Creates a new `EstimateLineItem` with a source row per atom. Single-atom case copies atom's description/units/qty/price; multi-atom case summarizes a uniform same-scheme task bundle, else falls back to blanks (see §6.3). |
| `send_all_atoms(estimate)` | One-click "send all": one new line item per `available` atom in the pool. Claimed atoms are skipped, so it composes with existing lines. `POST /api/estimates/{id}/send-all-atoms/` → `{'created': N}`; the wizard's "Send all to Estimate" button. |
| `add_atoms_to_line_item(line_item, atoms)` | Appends source rows to an existing line item. If the line item was **in sync** before (`price == round(sum(sources)/qty, 2)`), it is re-derived: a uniform same-scheme task bundle is re-summarized (units/qty/price), otherwise qty is kept and the per-unit price recomputed. An overridden line item is left untouched. |
| `remove_atoms_from_line_item(line_item, source_ids)` | Deletes source rows. Same re-derive-if-in-sync rule as `add_atoms_to_line_item`. Deletes the line item if no sources remain. |

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
| `GET /api/estimates/{id}/source-pool/` | `source_pool` | `EstimateWizardService.get_source_pool(estimate)` — drawn from the job's Tasks/Materials |
| `POST /api/estimates/{id}/line-items-from-atoms/` | `line_items_from_atoms` | `add_atoms_to_new_line_item(estimate, atoms)` |
| `POST /api/estimates/{id}/line-items/{lid}/add-atoms/` | `add_atoms` | `add_atoms_to_line_item(line_item, atoms)` |
| `POST /api/estimates/{id}/line-items/{lid}/remove-atoms/` | `remove_atoms` | `remove_atoms_from_line_item(line_item, source_ids)` |

Request body shape for atoms: `{atoms: [{type: 'task'|'material', id: N}, ...]}`.

The estimate itself is created directly on the job — `POST /api/estimates/`
with `{job}` (→ `EstimateService.create_for_job`), surfaced in the SPA as
the Job overview's **"Start Estimate"** button. There is no longer a
worksheet `open-estimate` / `send-all-atoms` endpoint.

Permissions: read is `IsAuthenticated`; write actions require
`CanManageJobs`.

### 8.4 Frontend components

**Retired 2026-08 (skeleton + three-mode surface, Task 13 of the
2026-08-08 plan):** `ReconcileMode.svelte`, `WizardActions.svelte`,
`WizardLineItemCard.svelte`, `WizardAtomRow.svelte`, and both
`WizardSourcePool.svelte` files (estimate and invoice) are **deleted**.
The two-column "reconcile mode" presentation they built is gone; the
service methods this section documents (§8.1–§8.3) are **unchanged** —
only the surface that calls them moved. See §12 for what replaced it
(`EstimateEditView.svelte` + the shared `docsurface` component kit) and
`architecture-and-conventions.md` §5.5b for the kit's cross-cutting
conventions.

| Component | Path | Role |
|---|---|---|
| `EstimateEditView.svelte` | `frontend/src/components/estimates/` | The estimate's **Edit** mode — one merged surface: the line-items table (each row's atom claims nested via `AtomChildRow`) plus an `UncoveredWorkSection` pool below it. Presentation + gestures only; `EstimatePanel` owns data loading. See §12. |
| `docsurface/*` kit | `frontend/src/components/docsurface/` | Seven shared components (`DocModeBar`, `BackingChip`, `AtomChildRow`, `UncoveredWorkSection`, `NewLineFromSelectedRow`, `DocCustomerView`, `DocReorderView`) consumed by both the estimate and invoice edit surfaces (and the planned CO surface). Not estimate- or invoice-specific — every prop is content/config, never `docType`-branched. |
| `LineItemModal.svelte` | `frontend/src/components/` | Shared modal for direct (no-atom) line item create/edit. Used by **both** the Invoice and Estimate detail pages (manual/catalog toggle on add; field-edit on edit). The estimate detail page authors hand-lines via **Add line** + per-line **Edit**. |

The invoice side is structurally parallel — same source pool, add-atoms,
remove-atoms, in-sync rule, and the same `docsurface` kit consumed by its
own `InvoiceEditView.svelte`. Both surfaces now read the **same** Job
atoms (Tasks + Materials) through the identical component family;
invoice-only concerns (agreement `backing`, seeded lines, deposit
credits) live in `InvoiceEditView` itself, not the shared kit. Pointer:
invoicing doc.

---

## 9. Acceptance — crystallizing hand-lines into atoms

When an `Estimate` transitions to `accepted`, the `estimate_accepted`
signal fires (`apps/estimates/signals.py` receiver), which calls
`EstimateAcceptanceService.on_accept(estimate)`
(`apps/estimates/acceptance.py`).

In the job-owns-atoms model the work already lives on the Job
(Tasks/Materials were created directly), so there is **nothing to copy
from a worksheet** — the old `AtomCarryOverService` /
`materialize_worksheet_onto_job` carry-over is gone. Acceptance instead
**crystallizes the estimate's descriptor-bearing hand-lines into job
atoms** so the agreed price of a service-item, catalog, or bare-material
hand-line becomes a real, billable job atom. A **plain** hand-line (no
descriptor) is the exception: it never crystallizes into anything — it
stays a document line forever, and transits to invoices later via an
agreement-line reference, not an atom (§4.5). Each sourceless hand-line
(no `EstimateLineItemSource`, not a percentage adjustment) goes through a
**four-way discriminator** in order: `service_item` → Task,
`inventory_item` → Material, `is_material` bare → established Material
(reverse-markup cost), else → nothing.

### 9.1 What `on_accept` does

In one `transaction.atomic()` block:

1. For each `EstimateLineItem` on the accepted estimate that has **no
   source row** (a hand-line) and is **not** a percentage adjustment
   (`adjustment_service_id is None`), crystallize it via the following
   discriminator (tested in order; first match wins):

   - **Service-item line** (`service_item_id is not None`) →
     call `service_item.generate_task(job, est_qty=li.qty or 1,
     description=li.description or '', allow_inactive_scheme=True)`.
     `Task.name` comes from the `ServiceItem.template_name`; `Task.description`
     comes from the estimate line's (user-edited) `description`. Record an
     `EstimateLineItemSource` with `source_type='task'`.

   - **Catalog material** (`inventory_item_id is not None`) →
     create a `Material` via `MaterialService.create_on_job` carrying
     `description`, `quantity = li.qty or 1`, `sell_price = li.price or 0`
     (the estimate's quoted price; the PLI supplies `unit_cost` via
     `_populate_from_pli`), the `inventory_item`, and `accounting_category`.
     Record an `EstimateLineItemSource` with `source_type='material'`.

   - **Bare material line** (`is_material=True`) →
     create a `Material` via `MaterialService.create_on_job`
     (`inventory_item=None`, `sell_price = li.price`), then **establish it**
     via `MaterialService.establish` with a **reverse-markup provisional cost**:
     `unit_cost = sell ÷ (1 + default_material_markup_percent/100)`, minting a
     QOH-0 `LOT-{pk}` lot and stamping `cost_source='estimated'`. The accepted
     **sell price is locked**; the cost is a placeholder flagged "cost
     unconfirmed" (⚠ in the UI) until a real document arrives. Record an
     `EstimateLineItemSource` with `source_type='material'`.

     > **Why established, not provisional.** Crystallizing established (with the
     > reverse-markup cost) means the material rides the procurement rails from
     > acceptance — it can be Ordered, consume-gates on arrival, and carries
     > COGS/margin — while the ⚠ marks the cost as not-yet-real. When a **PO**
     > line (or an attached expense) supplies the true cost, `cost_source` flips
     > to `po`/`expense` and **sell stays put**, so margin trues up against real
     > cost. CO acceptance establishes identically (shared
     > `MaterialService.establish_reverse_markup`; parity 2026-07-05).

   - **Plain line (default, no crystallization)** → the line has no
     `service_item`, no `inventory_item`, and `is_material=False`. Nothing
     is created and no `EstimateLineItemSource` is recorded — the line
     stays a document-only line for the rest of its life. It reaches an
     invoice later, if at all, via an agreement-line reference
     (`InvoiceLineItem.agreement_estimate_line`, §4.5), never through an
     atom claim.

   A descriptor-bearing line becomes atom-backed (the first three
   branches above), which is what lets the invoice wizard's source pool
   (§7) offer it for billing. A plain line never does — there is nothing
   for a source row to point at.

2. Atom-backed lines (those that already have an `EstimateLineItemSource`
   for a Task / Material) are skipped — their atoms are already on the
   job. Adjustment lines stay document-only (they recompute against the
   live lines and never crystallize).
3. Call `InventoryService.create_earmarks_for_job(job)`, so accepting an
   estimate earmarks the job's inventoried materials (including any just
   crystallized from catalog hand-lines or bare material lines).

`on_accept` returns `{'materials_created': int, 'tasks_created': int}`.

### 9.2 Idempotency

Because each crystallized hand-line gets a source row (material or
task), re-firing acceptance would find those lines already source-backed
and skip them — the same guard that protects atom-backed lines. A plain
hand-line never gets a source row in the first place, so it is
inherently a no-op on re-run — there's nothing to guard. The earmark
step is an absolute aggregate sweep, so it is idempotent on re-run too.

### 9.3 Job status side effects

Separate from acceptance crystallization, `estimate_status_changed_for_job`
walks the Job's status when its estimate moves, via the receiver in
`apps/estimates/signals.py`. Two symmetric invariants:

- **Estimate accepted ⇒ Job approved.** An estimate reaching `accepted`
  drives its Job to `approved` (after the `submitted` step on send).
- **Open estimate dies ⇒ Job rejected.** An **open** estimate
  transitioning to **expired** or **rejected** (a customer decline, or the
  `mark_estimates_expired` sweep) drives its Job to `rejected`, with a
  `system`-attributed `action` HistoryEntry ("Estimate … expired" /
  "Estimate … declined"). `rejected` is terminal. This closed a prior gap
  where declining an open estimate left the Job stranded at `submitted`.

`draft → rejected` on an estimate is intentionally **not** handled — a
never-sent draft dying does not reject the Job (out of scope). Only the
`open → {expired, rejected}` edge fires the rejection.

Pointer: `docs/designs/jobs-and-tasks.md` §13 for the full
receiver-by-receiver behavior.

---

## 10. AccountingCategory pass-through

`AccountingCategory` (`apps/core/models.py`) is required on
`RateScheme` (NOT NULL). `Task` carries its **own** `accounting_category`
(stamped from the preset at creation, then permanent — nullable at the
DB level, but required by the API serializer, §4). `ServiceItem` still
reads AC live off its `RateScheme` FK. Every other billable concept
carries AC directly (Materials with no PLI; Expenses).

### 10.1 Where AC comes from

| Object | AC source |
|---|---|
| `RateScheme` | own field, required |
| `Task` | own field — stamped from `scheme.accounting_category` by `Task.stamp_from_scheme` at creation (§3.1); `Task.effective_accounting_category` returns it directly, no FK traversal. Nullable at the DB level; the API's `TaskSerializer` makes it `required=True`, pre-filled from the picked preset for stamp-only creation. |
| `ServiceItem` | `template.rate_scheme.accounting_category` (via `ServiceItem.effective_accounting_category`) — still a live FK read; ServiceItem doesn't stamp |
| `Material` (PLI-linked) | `material.inventory_item.accounting_category` (copy/derivation; materials doc owns this) |
| `Material` (freeform) | direct on the material |
| `EstimateLineItem` from atom | derived from the atom's effective AC at line-item creation; snapshot |
| `EstimateLineItem` service-line | snapshotted from `service_item.effective_accounting_category` at `add_line_item_from_service` |
| `EstimateLineItem` `is_material` hand-line | `Configuration['default_material_accounting_category']` if no explicit AC supplied (see §6.4); required if the key is absent |
| `EstimateLineItem` plain hand-line (no descriptor) | user-entered; required before send (§15); the line never crystallizes into an atom, so the AC just stays on the document line and rides along into any invoice agreement-line reference |

`ServiceItem.effective_accounting_category` exposes AC for serializers
and the wizard's pool building. Wizard single-atom line-item creation
pulls `category` from the atom's effective AC (for a Task, its own
field); multi-atom creation only sets `category` if all atoms share one.

### 10.2 What changes when AC moves

Editing `RateScheme.accounting_category` is unrestricted — presets are
freely editable (§3) — but it only affects *future* stampings: a task's
own `accounting_category` was copied at creation time and never
re-reads the preset, so editing (or retiring) the preset never changes
an already-stamped task's AC.

For line items, AC is **snapshotted** at line-item creation time —
it's a field on `BaseLineItem`, not derived live. Once the estimate
is sent (out of draft), the snapshot is permanent.

### 10.3 Adjustment-line percent snapshot

Percentage adjustment lines (rush/discount) snapshot the same way:
`EstimateLineItem.adjustment_percent` / `InvoiceLineItem.adjustment_percent`
(Decimal(6,2), nullable) copy `adjustment_service.rate` (the percent
value) at line-creation time. `compute_adjustment_amount` (§2.2) reads
`adjustment_percent`, never the live scheme — so editing an adjustment
`RateScheme`'s percent after a line was created never moves an
already-created line's charge. `adjustment_service` itself is kept as
**provenance/identity only** — it's still what *selects* a line as an
adjustment (`adjustment_service_id is not None`), but the dollar amount
never reads its live `rate`. `ChangeOrderLineItem` has no adjustment
fields at all — CO deltas don't carry percentage-adjustment lines.

---

## 11. UI: Estimate Detail page

Route: `#/jobs/:jobId/estimate[/:docId]` → `JobEstimatePage.svelte`
(`frontend/src/routes/jobs/`), which hosts `EstimatePanel.svelte`
(`frontend/src/components/estimates/`) inside the job workspace shell
(`JobShell` — header + nav rail + collapsible context band; see
`jobs-and-tasks.md` §9.6). The bare section route
(`#/jobs/:jobId/estimate`) restores whichever version/CO the user last
viewed for this job (or the latest); picking a different version via
the panel's subnav (`DocSubnav.svelte`) updates the URL to
`/:docId` in place — no remount, no job refetch. The old
`#/estimates/:id` route still works: `EstimateDetailPage.svelte` is now
a small redirect shim into the job-scoped URL (old bookmarks, emitted
`source_link`s, and search results all keep working).

### 11.1 Layout

Top-down (settled 2026-08-08 wireframe session; design authority
`docs/plans/2026-08-06-better-fees.md` §9 and the wireframe artifact
linked there):

1. **JobHeader + JobNavRail + JobContextBand** — the job workspace
   shell (`JobShell`), shared by every job section page.
2. **DocSubnav** — one pill per estimate version (oldest→newest,
   labeled with the full code `{estimate_number}-{version}`, each with a
   status badge) plus this job's change orders, appended in
   `change_order_number` order. Change-order pills link to the
   job-scoped `#/jobs/:jobId/change-order/:coId` route, hosted by
   `JobChangeOrderPage` → `ChangeOrderPanel` since the 2026-07-19
   extraction (see `jobs-and-tasks.md` §9.6).
3. **Toolbar** — back link, page title (with `superseded` styling
   when applicable), status pill (interactive `<select>` for users
   with `can_manage_jobs` when transitions are allowed), and document
   action buttons (Send/Resend/Revise/Create Change Order — §11.2).
   There is no mode toggle here anymore — that moved to its own row
   (item 5).
4. **Field table** — estimate number, job link, version, status, dates.
5. **`DocModeBar`** (`docsurface/DocModeBar.svelte`) — three buttons,
   **Edit** / **Customer** / **Reorder**, `aria-pressed` on the active
   one. Flips the panel's local `mode` in place at the same URL — never
   a navigation, never a modal (§12).
6. **Mode content** — `EstimateEditView` in Edit mode (line items +
   uncovered-work pool, §12.1); `DocCustomerView`/`DocReorderView` in
   Customer/Reorder mode (§12.3).

### 11.2 Action buttons

| Status | Button | Handler |
|---|---|---|
| `draft` | "Send Email" (navigation link) | navigates to `#/estimates/{id}/send` — the send-form page that calls `EstimateEmailService.send_estimate` on submit |
| `open` | "Resend Email" (navigation link) | navigates to `#/estimates/{id}/send` |
| `open`, no CO yet, job on hold | "Create Change Order" | `POST /api/change-orders/` `{job}` → navigates to the new CO's page |
| `open` | "Revise Estimate" | `POST /api/estimates/{id}/revise/` → opens new draft revision |
| any | status `<select>` | `PATCH /api/estimates/{id}/` with `{status}` (when transitions are valid) |

Editing rules: `canEdit = canManageJobs && status === 'draft'`. **Add
line** and **Add Adjustment** are no longer toolbar buttons — they live
inside `EstimateEditView` itself, above its line-items table (§12.1),
since Edit mode is now the only place authoring happens.

### 11.3 Line item authoring — estimate vs invoice

**Estimate.** `EstimateEditView` (Edit mode, §12.1) authors line items
via the unified **"Add line"** button. A single `PriceListPicker` →
`EstimateAddLineForm` flow covers service picks, inventory picks, and
freeform (plain or material) lines — the estimate detail doesn't create a
Task immediately on a service pick; the Task is deferred to acceptance.
Per-line **Edit** / **Remove** remain (never "Delete" — §12.1); a line's
current backing renders as a `BackingChip` with its atom claims nested
underneath (`AtomChildRow`) rather than an "out of sync" marker — an
`edited` chip (with a "work totals $X" caption) is what used to be the
⚠ marker. `POST /api/estimates/{id}/line-items/` (hand-lines) and
`POST /api/estimates/{id}/line-items-from-service/` (service lines) are
the two create endpoints; GET list, per-line `PATCH`/`DELETE`, reorder
(now driven from Reorder mode, §12.3), and `POST .../adjustment-lines/`
are unchanged.

**Invoice.** `LineItemModal.svelte` is still used by the **invoice**
edit view for direct (no-atom) line authoring and for field-editing any
line (`InvoiceEditView`, `invoicing-and-expenses.md`) — a toggle between
**manual entry** and **"From Price List"** (catalog mode: pick an
`InventoryItem`; the server copies `description`, `units`,
`selling_price`, `accounting_category`) when adding, field-only when
editing. The invoice surface additionally carries agreement-seeded lines
and backing controls (**Use estimate** / **Use actuals**) the estimate
side has no equivalent for — see `invoicing-and-expenses.md`.

### 11.4 Starting an estimate — Create/View model

**Superseded by the 2026-07-08 job-workspace restructure and the
2026-07-09 overview redesign** (the "job detail, estimate pillar" this
section used to describe no longer exists — the job overview has no
authoring affordances at all; see `jobs-and-tasks.md` §9).
The Create/View model now lives entirely on `EstimatePanel.svelte`
(the Estimates section page, `#/jobs/:jobId/estimate`):

- **"Start Estimate"** — shown only when the job has no non-superseded
  estimate yet (job status is not itself gated in the panel — the
  backend's `EstimateService.create_for_job` is the enforcement point).
  POSTs `{job}` to `/api/estimates/` and reloads the panel onto the new
  draft. The UI enforces one active estimate tree per job; the backend
  permits multiple estimates, but the button disappears once any live
  estimate exists.
- **Viewing** — once an estimate exists, the panel simply renders it
  (no separate "View" affordance needed — the Estimates section route
  *is* the view). The overview's Scope block (§ jobs-and-tasks.md
  §9) shows a stat summary only, with no link into the panel (the rail
  is the navigation).

---

## 12. UI: The three-mode surface (Edit / Customer / Reorder)

**Retired 2026-08 — the old two-mode ("lines"/"reconcile") panel and the
two-column `ReconcileMode` wizard presentation are gone.** In their
place: one merged editing surface (`EstimateEditView`) plus two
read-only projections (`DocCustomerView`, `DocReorderView`), all three
switched in place by `DocModeBar` (§11.1) at the same
`#/jobs/:jobId/estimate/:docId` URL — never a navigation, never a
remount, never a modal. This is the estimate side of a shared
`docsurface` component kit also consumed by the invoice
(`InvoiceEditView`, `invoicing-and-expenses.md`) and, per the design
doc's sequencing, a future change-order surface. Design authority:
`docs/plans/2026-08-06-better-fees.md` §9 (the settled surface) and the
wireframe artifact it links — build-to-the-artifact was the standing
instruction; this section records the shape as built.
`architecture-and-conventions.md` §5.5b documents the kit's own
cross-cutting conventions (the seven components, shared `app.css`
classes, the flip-in-place pattern, the no-dead-buttons rule).

The former standalone `EstimateWizardPage.svelte` is gone; the old route
`#/estimates/:id/wizard` is still a redirect shim
(`EstimateWizardRedirect.svelte`), but it now remembers **`'edit'`**
mode for that document (`rememberMode`, `stores/jobWorkspace.js`) before
bouncing to the job-scoped URL — old wizard bookmarks land on the
merged Edit view, not a resurrected reconcile pane.

**Mode persistence and normalization.** Which mode a document was left
in is remembered per document id (`stores/jobWorkspace.js`, keyed by
`est:{estimateId}` — not by section, so leaving invoice #22 in Reorder
can't leak into invoice #23). The store itself keeps whatever was
written, **unmigrated** — normalization happens at the read site
(`EstimatePanel`, and identically in `InvoicePanel`): a remembered
`'lines'` or `'reconcile'` (both pre-dating this surface) folds to
`'edit'`; a remembered `'reorder'` additionally falls back to `'edit'`
if the document is no longer editable (`canEdit` false — e.g. the
estimate was sent/accepted since the mode was last remembered).

### 12.1 Edit mode — `EstimateEditView`

One `.data-table` of the estimate's line items, an uncovered-work pool
below it. `EstimatePanel` owns data loading (estimate, source pool,
categories) and passes it down; `EstimateEditView` is presentation +
gestures only, calling back (`onChanged`) after every mutation so the
panel can refresh both silently (`loadEstimate({silent: true})` — a
non-silent refresh would blank the surface and lose in-flight state
such as an open edit modal or the current pool selection; see
`architecture-and-conventions.md` §5.5b for this idiom generalized).

- **Authoring buttons** above the table: **"Add line"** (opens
  `PriceListPicker` → `EstimateAddLineForm`, §6.4/§11.3) and **"Add
  Adjustment"** (opens `AdjustmentModal`).
- **Table columns:** `#`, Description (+ a small provenance caption —
  `+N% {scheme name}` for an adjustment line, `Catalog: {name}` for a
  catalog-sourced line, and a **`needs category`** amber marker when
  `accounting_category` is null on an editable line — the same send-gate
  precondition the old ⚠ marker used to carry), Qty, Price, Amount,
  **Backing** (a `BackingChip`, §9.2 vocabulary below), and — while
  `canEdit` or a caller has wired `onMakeDeliverable` (currently no
  caller does; see below) — Actions.
- **Backing chip + reference.** Every line renders its derived
  `backing` (`derive_estimate_backing`, §6.1); when `backing ===
  'edited'` the chip is followed by a `work totals {backing_total}`
  caption — the reference figure "today's ⚠ out-of-sync made a
  first-class chip" per the design doc.
- **Atom nest.** Each line's `sources` render as indented
  `AtomChildRow`s directly beneath it — kind tag (task/material),
  description, qty/rate/amount, and (while `canEdit`) a per-atom
  **Remove** button that calls `remove-atoms`.
- **Per-line actions (while `canEdit`):** **Edit** (opens
  `LineItemModal` in field-edit mode — editing price flips `backing` to
  `'edited'`), **Remove** (`DELETE .../line-items/{id}/`, single-phase —
  the estimate has no two-phase confirm gate here since a removed line
  is freely re-addable via the uncovered-work pool below), and — only
  while the ticked-selection is non-empty — **"Add selected here"**
  (`POST .../line-items/{id}/add-atoms/`). **The word "delete" does not
  appear anywhere on this surface** — Remove releases the line's
  backing work untouched, it does not destroy the atoms.
- **"→ Deliverable" — ships dark.** The view accepts an
  `onMakeDeliverable` prop and renders a per-line **"→ Deliverable"**
  button only when a caller supplies it (the A3 no-dead-buttons rule,
  `architecture-and-conventions.md` §5.5b); `EstimatePanel` does not
  wire it yet, so the button is currently unrendered everywhere. It is
  reserved for the §6 make-a-deliverable endpoint, a later phase.
- **Uncovered-work pool** (`UncoveredWorkSection`, title "Uncovered
  work") — fed from `GET .../source-pool/`, filtered to atoms this
  estimate hasn't already claimed (`claimed_by_current` excluded — those
  already show as `AtomChildRow`s above). A row is selectable when
  `available`; a `claimed_by_other` row is dimmed with a "Claimed by
  estimate …" note instead of a checkbox. `directLabel="Add as its own
  line"` bills one atom directly (`onDirect` → `billDirect`, one POST to
  `line-items-from-atoms`, then opens the new line's Edit modal).
- **Object-first composition.** Ticking any pool row makes **every**
  line's Actions cell offer "Add selected here" and reveals the table's
  dashed footer placeholder, `NewLineFromSelectedRow` ("＋ New line from
  selected", labeled with the next line number). Its **Create line**
  button (`createLineFromSelected`) POSTs `line-items-from-atoms` with
  the ticked atoms, then — after awaiting the panel's silent refresh so
  the modal opens against the server's authoritative copy — opens
  `LineItemModal` on the new line immediately, same as the single-atom
  "Add as its own line" path.
- **409 handling.** A claim conflict (another session claimed an atom
  between pool load and POST) clears the selection, awaits a refresh,
  and shows a specific "…refreshed" message via the global overlay
  rather than the generic error text (`handleMutationError`,
  `architecture-and-conventions.md` §5.5b's 409-refresh idiom).

### 12.2 Backing chips (design doc §9.2 vocabulary)

The estimate has no actuals yet, so its `backing` enum and chip labels
(`docsurface/BackingChip.svelte`) are domain-specific — see §6.1 for the
derivation, and `docs/plans/2026-08-06-better-fees.md` §9.2 for the full
cross-document chip vocabulary (both estimate and invoice). On the
estimate: `planned_work` → **"planned work"** (any task
among the line's sources), `planned_materials` → **"planned materials"**
(materials only), `from_catalog` → **"from catalog"** (a `service_item`
or `inventory_item` ref — the two deferred-crystallization catalog
kinds), `hand` → **"hand line"**, `edited` → **"edited"** (with the
"work totals $X" reference caption), `adjustment` → **"adjustment"**.
`derive_estimate_backing`'s docstring documents this as **draft-surface
semantics**: the enum is designed for the estimate wizard's chip labels,
not as a general-purpose lifecycle indicator — a catalog-sourced line
keeps reading `from_catalog` for its whole life even after acceptance
crystallizes it into a live Task/Material source on that same line (rule
2 fires before rule 3, deliberately). A **plain** hand-line never
crystallizes into anything, so it keeps reading `hand` for its whole
life too, even after acceptance — there's no source row to promote it to
`planned_work`/`planned_materials`.

### 12.3 Customer and Reorder modes

**Customer mode** renders `DocCustomerView` — the collapsed, read-only
document exactly as it will read to the customer: `#`, description,
qty, price, amount, and a grand-total footer row, for **every** line
including adjustments, numbered by the document's own stored
`line_number`. No backing column, no atom rows, no struck rows, no
buttons of any kind — the settled rule is that a mode is never a modal
and Customer mode carries zero interactive affordances.

**Reorder mode** renders `DocReorderView` — **the identical rows as
Customer mode plus a trailing arrows column** (↑/↓, boundary arrows
disabled), so reordering never carries sub-line ambiguity. Clicking an
arrow (`handleReorderDoc`) swaps the line's `line_number` with its
neighbor in the full ordered id list and POSTs the existing
`.../line-items/reorder/` endpoint with the full `item_ids` order, then
reloads the estimate. Reorder is only offered in the mode bar
(`modes`, §11.1) while `canEdit` is true; a document that stops being
editable while remembered in `'reorder'` falls back to `'edit'` on next
load (§12 intro).

### 12.4 Entry

The estimate is reached from the rail's Estimates link (§11): "Start
Estimate" creates the draft estimate directly on the job
(`POST /api/estimates/` with `{job}`), landing on
`#/jobs/:jobId/estimate/:newId` in Edit mode (the panel's default). The
mode bar (§11.1) is present unconditionally once the estimate is loaded
— no separate reconcile entry point or worksheet page exists.

---

## 13. Signals

Two signals, defined in `apps/estimates/signals.py` and fired by
`Estimate.save()`. Brief recap; the receiver-by-receiver behavior lives
in `docs/designs/jobs-and-tasks.md` §13. (The former
`estimate_status_changed_for_worksheet` signal was removed with the
worksheet layer.)

| Signal | Fires when | Receiver | Effect |
|---|---|---|---|
| `estimate_status_changed_for_job` | draft→open, any→accepted, or open→{rejected, expired} | `update_job_status` | walks the Job through submitted/approved/rejected with HistoryEntry rows (see §9.3) |
| `estimate_accepted` | any→accepted | acceptance receiver | calls `EstimateAcceptanceService.on_accept(estimate)` — crystallizes descriptor-bearing hand-lines into Tasks/Materials via the four-way discriminator (a plain hand-line stays document-only) and earmarks the job (§9) |

The `estimate_accepted` signal is the one this doc owns. The other is
summarized here only so acceptance fits into the picture; its full
behavior is in jobs-tasks.

---

## 14. Change Orders

`ChangeOrder` (`apps/estimates/models.py`, `db_table = 'change_orders'`,
decorated with `@history`) is the amendment instrument that lets the
agreement change after an Estimate has been `accepted`. Once an
Estimate is accepted it is terminal — its line items are the frozen
record of what was sold. A change order is the **only** sanctioned way
to alter that record. The agreement-of-record for a job is therefore
not a single document; it's the accepted Estimate combined with each
accepted ChangeOrder's line-item deltas, composed by §14.6 below.

### 14.1 What a CO is (and isn't)

A CO carries **less than a job's worth of change**. Significant
restructurings (a wholesale re-scope, a re-run of the estimate wizard)
are not COs — they're "cancel and start a new job" territory
(`cancelled-with-invoice` for closing the current job early; see
`invoicing-and-expenses.md`). Consequences baked into the model:

- While being authored, a CO is a **document**: direct line-item
  composition (manual entry, or pulls from `ServiceItem` /
  `InventoryItem`). It does not project or mutate the Job's atoms while
  draft/open, and it never runs the estimate wizard.
- **Acceptance crystallizes the deltas onto the Job's atoms** (§14.11),
  exactly parallel to estimate acceptance (§9): a descriptor-bearing
  `add` line becomes a Task or Material (a plain `add` line stays
  document-only), a `remove` retires the target line's atom, a
  `replace` retires the old atom and crystallizes its replacement. The
  amended work becomes real — schedulable, blep-trackable, earmarked —
  the moment the customer says yes. (The living Job can still be edited
  by hand afterwards; crystallization sets the starting point, it
  doesn't lock anything.)

### 14.2 Model

| Field | Type / FK | Notes |
|---|---|---|
| `change_order_id` | AutoField PK | |
| `job` | FK → Job (CASCADE) | Parent job |
| `estimate` | FK → Estimate (PROTECT) | The accepted Estimate the CO amends |
| `change_order_number` | CharField (max 80, unique) | Auto-generated `{estimate_number}-CO{N}` where N is the count of COs against this Estimate at creation time |
| `version`, `parent` | int, self-FK | Reserved for future CO revisions; not currently exercised |
| `status` | CharField (choices) | See §14.3 |
| `created_date`, `sent_date`, `closed_date` | DateTimes | Auto-set on entry to `open` / terminal states; immutable once set |
| `expiration_date` | DateTime | Frozen at the moment of send; see §14.7 |

A CO can only be created while the job is held (`job.on_hold` flag) —
`ChangeOrderService.create` enforces this (see §14.5). The CO's
`estimate` FK pins it to the accepted Estimate that was in force when
the CO was opened; this is what `compose_agreement` walks.

`ChangeOrderSerializer` also exposes a read-only `total`
`SerializerMethodField` — **not** `Σ qty×price` of the CO's own
add/remove/replace lines (a `remove` subtracts, a `replace` swaps), but
the authoritative delta from `compose_change_order_diff(obj)['diff_total']`
(the same figure the CO PDF and customer-portal diff use). The
job-overview Scope block adds this delta onto the frozen estimate total
when a draft/open CO re-activates the block. `change_order_id`,
`change_order_number`, `version`, `estimate`, `created_date`,
`sent_date`, `closed_date` are all in the serializer's
`read_only_fields` — a bare PATCH cannot flip identity/timestamp fields
(regression-tested; a prior pass had accidentally dropped this list,
leaving them client-writable).

### 14.3 Status machine

| Status | Constant | Meaning |
|---|---|---|
| `draft` | `STATUS_DRAFT` | Editable; line items can be added/removed; not yet sent |
| `open` | `STATUS_OPEN` | Sent to customer; awaiting response |
| `accepted` | `STATUS_ACCEPTED` | Terminal. Customer accepted; deltas are now part of the agreement-of-record |
| `rejected` | `STATUS_REJECTED` | Terminal |
| `expired` | `STATUS_EXPIRED` | Terminal; auto-set by `mark_change_orders_expired` once `expiration_date` has passed |
| `superseded` | `STATUS_SUPERSEDED` | Terminal; replaced by a CO revision |

Valid transitions (`ChangeOrder.clean()`, identical shape to
`Estimate.clean()`):

```
draft       → open, rejected
open        → accepted, rejected, superseded, expired
accepted, rejected, expired, superseded → (terminal)
```

`clean()` also blocks `draft → open` if the CO has no
`ChangeOrderLineItem` rows. `save()` auto-sets `sent_date` and
`expiration_date` on entry to `open` (using the same `est_expire_days`
Configuration key Estimates use), and `closed_date` on entry to a
terminal.

### 14.4 ChangeOrderLineItem — delta semantics

`ChangeOrderLineItem` (`db_table = 'co_li'`) inherits from
`BaseLineItem` and adds:

| Field | Notes |
|---|---|
| `change_order` | FK → ChangeOrder (CASCADE) |
| `action` | One of `add`, `remove`, `replace` |
| `target_line_item` | FK → EstimateLineItem (PROTECT). Required for `remove` / `replace`; must be null for `add`. Enforced in `clean()`. |
| `inventory_item` | Optional catalog pointer, parallel to `EstimateLineItem` provenance. At acceptance the line crystallizes into a `Material` on this item. |
| `service_item` | Nullable FK → `ServiceItem` (PROTECT). Deferred service descriptor, identical to `EstimateLineItem.service_item` (§6.1): the line snapshots the service's price at authoring and crystallizes to a `Task` at CO acceptance. |
| `is_material` | Marks a bare (no descriptor) line as a material: crystallizes into an **established Material** (reverse-markup placeholder cost, `cost_source='estimated'`) instead of staying a plain, uncrystallized document line, same as `EstimateLineItem.is_material`. Authoring applies the `default_material_accounting_category` config default and rejects the marker on lines that already carry an `inventory_item`/`service_item`. |

`clean()` also rejects `service_item` / `is_material` on a `remove` line
(its own fields are display-only; it never crystallizes anything).

The `action` field is the heart of CO semantics:

- **`add`** — a brand-new line. The line's qty/price/description live
  on the CO row; there's no `target_line_item`. Composed at the **end**
  of the agreement (after all estimate lines), in line-number order
  within the CO.
- **`remove`** — strikes the `target_line_item` from the agreement.
  The CO row's own qty/price/description are display-only (what the
  customer agreed to remove). The line vanishes from the composed
  output.
- **`replace`** — overrides the `target_line_item`'s qty / price /
  description with the CO row's values, in place. The original line
  number is preserved in the composed output.

The estimate's line items are never mutated. The agreement is always
the composition (Estimate + accepted COs); the underlying
`EstimateLineItem` rows stay frozen as the historical record of what
was first sold.

**Send guard (AC).** `ChangeOrder.clean()` blocks `draft → open` while
any bare `add` line (no `service_item`, no `inventory_item`) lacks an
`accounting_category` — the CO parallel of
`assert_all_hand_lines_have_ac` (§5.1/§15). Such a line either
crystallizes into a Material (`is_material=True`) at acceptance, where
the category must be pinned *before* the customer can say yes so
acceptance can never fail on it, or — if not marked as a material —
stays a plain document line forever, where the category is still
required up front (§15's send-time AC guard applies regardless of
whether the line will ever back an atom). The check is `ChangeOrderService.assert_all_bare_add_lines_have_ac`
(2026-07-20), shared by the model's `clean()` — so the guard holds on every
send path (mark-open action, status PATCH, `send_change_order`) — and by
`ChangeOrderEmailService._validate_send` as a pre-email copy, so a refusal
lands *before* the customer is mailed a link (previously the clean()-only
placement meant the email went out and then the draft→open transition
failed, leaving the customer a dead draft link — the estimate side never
had that gap).

**Content gate (2026-07-20):** leaving `draft` requires the CO to carry
line-item changes **or** a deliverables diff against its baseline —
`ChangeOrderService.has_sendable_changes(co)`, shared by
`ChangeOrder.clean()`'s draft-exit guard (the invariant home) and
`ChangeOrderEmailService._validate_send` (the pre-email copy, so an
unsendable CO fails before the email goes out). A **deliverables-only
CO** (spec/quantity correction with no price impact — typically a
fix-the-mistake amendment) is sendable; only a CO empty on both halves
is refused ("Cannot send an empty change order…"). Previously a CO with
no line items was refused outright.

**`ChangeOrderLineItemSource`** (`db_table = 'co_li_sources'`) is the CO
analog of `EstimateLineItemSource` (§6.2): a polymorphic join
(`source_type ∈ {task, material}` + `source_pk`, unique together)
from a CO line to the atom it **crystallized** at acceptance. It is the
provenance record and the idempotency marker (a line with a source row
is already crystallized). `resolve()` returns the concrete atom. Unlike
the estimate table, rows exist only for add/replace lines of
**accepted** COs — authoring never creates one. (Billing no longer
traces through this table at all — see §14.6's note on the retired
`source_fee_id` channel; the invoice side now claims agreement value via
`agreement_estimate_line`/`agreement_co_line` references instead,
invoicing doc.)

### 14.5 Job on_hold gate

COs are authored only while the parent Job is **held** — the `on_hold`
flag, an orthogonal pause that leaves the job's true status untouched
(see `jobs-and-tasks.md`). The flow:

1. User pauses the Job (`JobService.hold_job` — the flag goes up; the
   status stays `approved`/`in_progress` underneath). The pause
   requires a `hold_reason`; no open Bleps may exist.
2. While held, the user can `ChangeOrderService.create(job_id=…)`.
   `create` raises unless `job.on_hold` is set.
3. The user edits the CO (line items), sends it (`draft → open`),
   and waits for customer response.
4. **Accept:** `ChangeOrderService.update_status(pk, accepted)`
   **clears the hold** — the job resumes its true underlying status
   directly (a job held from `in_progress` goes straight back to
   `in_progress`; the old `on_hold → approved` detour and its second
   release step are gone) — writes a system-attributed HistoryEntry,
   and **crystallizes the CO's deltas onto the Job's atoms**
   (`ChangeOrderAcceptanceService.on_accept` — §14.11), all in one
   transaction. The CO's deltas are now part of the agreement and the
   amended work is real on the Job.
5. **Reject / Expire / Request changes:** the Job stays held. The CO
   snapshots its proposal (so the rejected/expired version is
   preserved verbatim even if the Estimate or its line items later
   change).
6. **Release guard** (was the "exit guard"): `JobService.release_job`
   refuses to drop the flag while any `draft` or `open` CO exists —
   the job stays parked on hold until open COs are resolved
   (accept / reject / discard).

The on_hold gate is the entire point of the flag — it's the room
where CO work happens, isolated from the live work side of the Job.
The Schedule never forecasts a held job since its agreement is in
flux (its history bars still render — `apps/schedule/services.py`).

### 14.6 `compose_agreement` — the agreement-of-record

`compose_agreement(job)` in `apps/estimates/agreement.py` is the
function that produces the agreement-of-record:

```python
{
  'lines': [
    {'description', 'qty', 'units', 'price', 'amount', 'origin'},
    …
  ],
  'grand_total': Decimal,
}
```

where `origin` is `'estimate'` or `'change_order'`. Empty dict (lines
`[]`, total `0`) when the Job has no accepted Estimate.

**Line identity (2026-08, skeleton phase).** Every line dict also
carries `estimate_line_id` and `co_line_id` (int or `None`) — exactly
one is non-null per line: an estimate-origin line carries its
`EstimateLineItem.pk` (and `co_line_id: None`); a CO-origin line (add or
replace) carries its `ChangeOrderLineItem.pk` (and `estimate_line_id:
None`) — a CO *replacement* line dict is CO-origin, since the CO's own
line is the row of record once accepted. This identity is what
`InvoiceService` (`invoicing-and-expenses.md` §"Agreement-line
references and seeding") matches against to decide which agreement
lines are "remaining" (not yet on a live invoice) and to enforce the
one-live-invoice-per-agreement-line invariant.

The composition rules:

1. Start with the accepted Estimate's `EstimateLineItem` rows in
   `line_number` order, each turned into a line dict.
2. Walk the Job's `accepted` ChangeOrders in **acceptance order**:
   `closed_date` asc, with `change_order_id` asc as a deterministic
   tie-break.
3. For each CO, apply its line items in `line_number` order:
   - `replace` → overwrite the matching line dict in place.
   - `remove` → null out the matching line dict (it drops out of the
     output).
   - `add` → append to a deferred "added lines" list.
4. Final output is the surviving estimate-keyed lines (still in their
   original line-number order) followed by the appended `add` lines
   in the order they were accepted.

`amount = qty * price` on each line, matching `BaseLineItem.total_amount`.
The grand total is the sum of all surviving line amounts.

Line dicts carry **no** `source_fee_id` key (the fee-provenance channel
was removed 2026-08, fee-removal Task 3 — `copy_from_estimate` no longer
creates fee claims from agreement lines; legacy `SOURCE_FEE` rows on
estimate/CO lines are simply ignored by the composition). Line identity
is `estimate_line_id` / `co_line_id` only.

This function is the single source of truth for what the customer owes.
The Invoice wizard reads it; PDF rendering of the agreement reads it;
the Estimate-detail page surfaces the composed view alongside the
underlying Estimate.

**`compose_amended_agreement(co)`** (same module, CO amend-in-place
2026-08-09) is the sibling composer that answers "what will the
agreement read if `co` is accepted" — the baseline (the estimate plus
whichever accepted COs precede `co` in acceptance order) with `co`'s
own draft add/remove/replace lines applied on top. It shares `_fold`
(the add/remove/replace walk) with `compose_agreement` so the two can
never diverge. Returns `{'rows', 'original_total', 'co_delta',
'revised_total'}`; each row is kind-tagged —
`agreement` (untouched baseline line; carries `billed_on` and, for a
stale adjustment line, `adjustment_expected_amount`), `replaced` (the
CO's replacement line dict + the struck `original`), `removed` (struck
`original` only), `added` (the CO's new line dict) — with `replaced`/
`added` rows numbered `co_index` (1… in line_number order). This is the
engine behind `COEditView` (§14.9) and its `GET .../amended-agreement/`
endpoint (§14.8); `apps/api/change_orders/serializers.py`'s
`serialize_amended_agreement` adds the per-row display extras (backing
classification, resolvable `sources`, JSON stringification) the same
way `EstimateLineItemSerializer` does for the estimate side.

### 14.7 Auto-expiry — `mark_change_orders_expired`

`mark_change_orders_expired`
(`apps/estimates/management/commands/mark_change_orders_expired.py`)
is the sibling of `mark_estimates_expired` (§5.2a). Each run:

1. Selects every `open` CO whose (non-null) `expiration_date` is at or
   before `now()`.
2. For each, transitions it to `expired` via
   `ChangeOrderService.update_status(pk, STATUS_EXPIRED)` (under
   `select_for_update`, re-checking it's still `open`), and writes a
   `system`-attributed `action` HistoryEntry.
3. Counts `open` COs with a **NULL** `expiration_date` separately and
   skips them — they never auto-expire.

Like estimates, the parent Job stays held after expiry (the expiry
doesn't release the hold; the user releases the job once all open COs
are resolved).

### 14.8 API endpoints

- `GET /api/jobs/{id}/change-orders/` — list of the job's COs
- `POST /api/change-orders/` — create (body: `{job_id}`). UI-wise, the
  estimate panel's **Create Change Order** button (accepted estimate)
  shows only while the job has **no** change orders (2026-07-19): the
  first CO branches from the accepted estimate, and every further CO is
  seeded from the previous one via the CO page's "Start new change
  order" (`seed-new`) flow, so COs chain rather than branching fresh.
- `GET / PATCH / DELETE /api/change-orders/{id}/`
- `POST /api/change-orders/{id}/mark-open/` — `draft → open`
- `POST /api/change-orders/{id}/update-status/` — accept / reject /
  discard transitions; routes through `ChangeOrderService.update_status`
- `POST /api/change-orders/{id}/line-items/` — add line item
- `POST /api/change-orders/{id}/line-items/from-pli/` — add from
  InventoryItem
- `POST /api/change-orders/{id}/line-items-from-service/` — add a
  deferred service line (body `{service_item, qty}`; snapshots price,
  mints no Task — mirrors the estimate action, §6.4)
- `PATCH /api/change-orders/{id}/line-items/{liid}/` — update
- `POST /api/change-orders/{id}/line-items/reorder/`
- `DELETE /api/change-orders/{id}/line-items/{liid}/`
- `GET /api/change-orders/{id}/deliverables-baseline/` — the snapshot
  of deliverables-at-CO-creation used to render the CO-edit view's
  baseline (see `jobs-and-tasks.md` §12 for snapshot
  mechanics)
- `GET /api/change-orders/{id}/amended-agreement/` — the
  `compose_amended_agreement(co)` result (§14.6), serialized —
  `COEditView`'s (§14.9) one-table data source
- `GET /api/change-orders/{id}/source-pool/` — the CO wizard's source
  pool (`ChangeOrderWizardService.get_source_pool`), same atom shape as
  the estimate's `source-pool` (§8), with claims unioned across both
  the estimate and CO lenses (uncovered-work rows in `COEditView`)
- `POST /api/change-orders/{id}/line-items-from-atoms/` — create a new
  `add` line from a set of atoms (mirrors §8's estimate action)
- `POST /api/change-orders/{id}/line-items/{lid}/add-atoms/` /
  `POST /api/change-orders/{id}/line-items/{lid}/remove-atoms/` —
  append/detach atoms on an existing CO line (409 `atoms_already_claimed`
  on a claim conflict, same contract as the estimate side)
- `GET /api/change-orders/{id}/send-defaults/` — pre-populated
  send-to-customer form fields (to / subject / body with the portal
  link; `attachments_preview` lists the auto-attached CO PDF)
- `POST /api/change-orders/{id}/send/` — email the customer the portal
  link plus the change-order PDF, and transition `draft → open`
  (`ChangeOrderEmailService.send_change_order`)
- `GET /api/jobs/{id}/agreement/` — the `compose_agreement` result for
  a job

All write endpoints (including `send`/`send-defaults`) require
`can_manage_jobs`. The endpoint→atom table in `users-and-permissions.md`
is authoritative.

### 14.9 SPA

`ChangeOrderPanel.svelte` (`components/changeorders/`, hosted at
`#/jobs/:jobId/change-order/:coId` by `routes/jobs/JobChangeOrderPage.svelte`
inside `JobShell` — extracted 2026-07-19 from the old
`ChangeOrderDetailPage` route) is the CO edit view. It owns CO-scoped
loading (the CO, its `amended-agreement`, its `source-pool`, sibling
COs for display-status relabelling, and the deliverables live/baseline
pair) plus the toolbar and status actions; `CODeliverablesSection.svelte`
owns the deliverables grid + inline drafting forms
(`lib/changeOrderDiff.js`'s `buildDeliverableRows`, unit-tested), and
`COEditView.svelte` owns the line-item surface.

**`COEditView.svelte`** (CO amend-in-place, 2026-08-09 — replaced the
old flat `COLineItemsSection` line-diff table) renders **one**
`.data-table doc-edit-table` of the CO's `amended-agreement` (§14.6,
§14.8): "the agreement as it will read if this CO is accepted", with
gesture buttons rather than a diff. It follows the same structural
contract as `EstimateEditView`/`InvoiceEditView` (§12, the `docsurface`
kit) — presentation + gestures only, the panel owns loading and a
silent (`{silent:true}`) refresh after every mutation so an
in-progress edit modal or atom selection survives the round trip.
Row kinds, per `compose_amended_agreement`'s row `kind`:

- `agreement` — an untouched baseline line: `BackingChip` + **Remove
  via CO** / **Replace…** (POST a `remove`/`replace` CO line targeting
  it). Both buttons disable with `title="Billed on {billed_on}"` (and a
  caption) once a live invoice references the line; a stale adjustment
  line shows a muted "recomputes to {amount} if replaced" caption.
  Replace on an adjustment line (`line.is_adjustment`) opens the
  modal's `adjustment` variant instead of `replace-prefill`.
- `replaced` — CO-tinted (`.co-authored`), tagged `CO {co_index}`, the
  replacement line above its struck `original` (excluded from totals)
  and the inherited-preview `AtomChildRow`s (each labelled "inherited
  from line {n}" — the claims that backed the original line, per
  `derive_co_line_backing`); actions **Edit** / **Undo** (DELETE the CO
  line, reverting to the `agreement` row).
- `removed` — the struck original alone; action **Undo**.
- `added` — CO-tinted, tagged `CO {co_index}`, its own `AtomChildRow`s
  (detachable via `remove-atoms`) and `BackingChip`; actions **Edit** /
  **Remove**, plus **Add selected here** while the uncovered-work
  selection is non-empty (`add-atoms`).

The table foot is `NewLineFromSelectedRow` (`line-items-from-atoms`,
then opens the Edit modal on the fresh line) and the
original/this-CO/revised totals from the payload. Below the table:
**"Add line"** opens the unified `PriceListPicker` (§6.4) — the same
service / inventory / freeform (+ is-material checkbox) entry point as
the estimate detail page — followed by `COAddLineForm.svelte`
(`components/changeorders/`, unchanged), which posts a service pick to
`line-items-from-service/`, an inventory pick to `line-items/` (the
from-pli path), and a freeform line manually with AC + `is_material`;
then `UncoveredWorkSection` (title "Uncovered work") over the CO's
`source-pool`.

**`COLineItemModal.svelte`** was reworked the same day from a single
action/target-select form into a gesture-driven modal with **no**
action or target selects — the calling gesture presets everything via
props, and create-vs-PATCH is derived from whether `lineItemId` (a
PATCH target) is set. Three variants: `edit-fields`
(description/qty/units/price; an Accounting Category select only when
editing an `add` line — replace lines inherit AC from their target),
`replace-prefill` (same fields, prefilled from the `agreement` line
being replaced; POSTs `{action:'replace', target_line_item, …}`), and
`adjustment` (description + percent only — the server recomputes
`price` against the amended-agreement basis,
`ChangeOrderService.recompute_adjustment_replaces` — the modal shows
that computed amount as a readback with an explicit **Done** button
before closing, never auto-closing on save). The Estimate detail page
shows accepted COs as pills/badges in the deliverables and line-items
sections.

**The "amended" status label.** An accepted estimate that an accepted
change order amends keeps its stored `status = accepted` — it is still
the base of the agreement-of-record — but the UI relabels it **amended**
so the human sees that the agreement has moved. This is derived, never
stored: the rule lives once on the model as `Estimate.is_amended()` —
true when the estimate is `accepted` and at least one **accepted** CO
references it (a non-accepted estimate short-circuits to `False`). Both
read paths call it: `EstimateSerializer.get_is_amended` and the board
pipeline payload's per-estimate `is_amended` (`BoardService.
_serialize_pipeline_job`). The frontend renders
`is_amended ? 'amended' : status` (`JobDetail`, `EstimatePanel`, the
board `PipelineColumn`); there is no client-side re-derivation. Only
accepted COs flip it — a draft/open CO does not, matching
`compose_agreement`, which only applies accepted COs. (The CO detail/job
views use the same word, "amended", for an accepted CO that a later
accepted CO has itself amended — a separate client-side computation
ordered by `change_order_id`.) See `LATER.md` for the decision record on
keeping `status = accepted` rather than introducing a stored state.

The draft toolbar's **Send to customer** link routes to
`ChangeOrderSendPage.svelte` (`/change-orders/:id/send`), which reuses
`DocumentSendForm` to email the portal link + PDF and flip the CO to
`open` (the bare `mark-open` endpoint remains for back-compat). On an
`open` CO the toolbar shows **Resend to customer** (same send page —
`send_change_order` only transitions on the first send, so a resend just
re-emails), alongside the shop's internal **Record Accepted / Record
Rejected** buttons for decisions relayed out-of-band. This mirrors the
estimate detail page's Send / Resend Email affordance.

### 14.10 Customer portal

The CO customer portal mirrors the Estimate portal (§15.1) so a customer
can review and respond to a change order through a token link, without a
login.

- **Token.** `ChangeOrder.public_token` (`CharField(64, unique)`) is
  minted once in `ChangeOrder.save()` at creation, per row — a
  `seed_new` revision gets its own. Identical to `Estimate.public_token`.
- **Link.** `build_object_url('change_order', id)` →
  `<base>/portal/?token=<token>&doc=change_order`. The single `/portal/`
  static entry dispatches on the `doc` query param
  (`PortalApp.svelte` → `EstimatePortal` or `ChangeOrderPortal`; both
  pages are thin content snippets around the shared
  `components/PortalDocument.svelte` shell, which owns the token load,
  the confirm/submit state machine, and the confirmation fieldsets —
  each page supplies its API path, copy, and body tables). `doc` is
  **required and explicit** for both document types — estimate links are
  `&doc=estimate` (see `build_object_url('estimate', …)` and the in-app
  superseded forward links); a portal URL with a missing or unknown `doc`
  renders a "could not be found" message and makes no API call, rather than
  silently assuming a document type.
- **API** (`apps/api/portal/change_order_views.py`, all `AllowAny`,
  `authentication_classes([])`; the helpers both portal modules share —
  `money`, `not_available`, `actor_for`, the draft-visibility gate, and
  the lock-by-token `decide` skeleton — live in
  `apps/api/portal/common.py`, with each side keeping its own
  `_is_actionable` rule and payload builder):
  - `GET /api/portal/change-orders/<token>/` →
    `build_change_order_payload` (a before/after diff: `line_rows` with
    `kind ∈ {unchanged, changed, changed-orig, removed, added}` from
    `compose_change_order_diff`, a `deliverables` diff, `prior_total` /
    `proposed_total` / `diff_total`, `actions`, `actionable`,
    `closed_message`, and `current_token` when superseded). A `draft`
    CO or unknown token 404s.
  - `POST …/accept/` → `update_status(ACCEPTED)` (clears the job's
    hold; the job resumes its true status directly).
  - `POST …/reject/` (body `{reason}`) → `update_status(REJECTED)` (job
    stays held).
  - `POST …/request-changes/` (body `{reason}`) →
    `ChangeOrderService.request_changes`: supersede the open CO and
    `seed_new` a fresh draft, job stays held.
- **Actionability.** A CO is actionable only when `status == open` and
  its job is held (`co.job.on_hold` — the CO analog of an estimate
  being `open` with its job `submitted`). A click that races a shop
  action is a silent no-op. Each decision runs under `select_for_update`.
- **History + notification.** The portal records a *customer*-attributed
  `HistoryEntry` for every decision (the service's `update_status` writes
  only a system entry for accept and none for reject), and fires
  best-effort `ChangeOrderEmailService.notify_shop_of_decision` after
  commit for accept / decline / request-changes.
- **Baseline asymmetry (faithful to the shop edit page):** the line-item
  diff baselines off the flat accepted estimate (`co.estimate`), while
  the deliverables diff baselines off
  `ChangeOrderService.baseline_document(co=co)` (the latest accepted CO
  before this one, else the estimate). Single-CO is the validated path;
  with multiple accepted COs the line baseline can understate the true
  current agreement (see `LATER.md`).
- **Diff composers (shared, not portal-only):** line-item diff is
  `compose_change_order_diff(co)` in `agreement.py`; the deliverable diff
  is `ChangeOrderService.compose_deliverable_diff(co)` (rows
  `{kind, description, qty, units}`, same kind vocabulary). Both feed the
  portal payload **and** the CO PDF, so the emailed document and the
  online view show the same line-item and deliverable changes.
- **PDF.** `generate_change_order_pdf(co)` (`apps/estimates/pdf.py` +
  `templates/estimates/change_order_pdf.html`, WeasyPrint, styled like the
  estimate PDF; both generators resolve the header's contact/business
  names through the shared `_pdf_party_context(job)` helper, while the
  two templates stay deliberately separate — PDF templates are
  self-contained by convention, no extends/include) renders both diffs — a "What you'll receive" deliverables
  section and the line-item table with prior/new/change totals — using
  print-safe change labels (Added/Removed/Changed/was). It is attached to
  the CO send email.

### 14.11 Acceptance — crystallizing CO deltas onto Job atoms

`ChangeOrderAcceptanceService.on_accept(co)`
(`apps/estimates/co_acceptance.py`) is the CO parallel of §9's
`EstimateAcceptanceService`. `ChangeOrderService._handle_accepted`
invokes it after the Job's hold is cleared (the job resumes its
underlying status directly — a job held from `in_progress` resumes
work with no second release step), inside `update_status`'s
transaction — atom writes are blocked while the job is held, and a
failed crystallization rolls the whole acceptance back.

Lines are processed **adds → replaces → removes** (each group in
`line_number` order) so a CO that swaps out the job's only task never
transiently empties the live work set and trips the auto-advance to
`work_complete`.

- **add** — crystallize via the same four-way discriminator as estimate
  acceptance (§9.1): `service_item` → Task
  (`generate_task(allow_inactive_scheme=True)`; name from the
  ServiceItem, description from the line), `inventory_item` → Material
  (line price = sell price), `is_material` bare → established Material
  via `MaterialService.establish_reverse_markup` (parity with §9.1 —
  cost backed out of the locked sell, `cost_source='estimated'`; a bare
  replace whose mirrored atom was provisional is likewise established),
  else → nothing — a **plain** add line crystallizes no atom and gets no
  `ChangeOrderLineItemSource` row; it stays a document-only delta,
  exactly like a plain estimate hand-line (§9.1). Descriptor-bearing
  branches write a `ChangeOrderLineItemSource` row.
- **remove** — resolve the target estimate line to its **current** atom
  and retire it:
  - *Task*: `TaskLifecycleService.cancel_task` — **bleps are
    preserved**; already complete/cancelled tasks are left alone.
  - *Material*: **released** (`MaterialService.release` — earmark backed
    out, quantity moved to `released_qty`, state → `released`, claims
    kept as job history), but **only if** pending, not expense-bound,
    not PO-linked, and not on a live invoice — physical or billed
    reality is never unwound by a document; those are left for the
    human to reconcile.
  - A document-only target (adjustment line, a plain line that never
    crystallized, or an atom already retired) is a no-op — the delta
    stays document-only, matching `compose_agreement`.

  **Surfacing the skips (decided 2026-07-20):** the skip itself stays
  silent at acceptance, but the invoice wizard pool badges every
  struck-but-still-live atom **"struck from agreement"** (amber, like
  the cancelled-task badge; suppressed when the task is also cancelled)
  so the biller decides consciously at the money moment. The set is
  derived, never stored — `ChangeOrderService.struck_atom_keys(job)`
  walks the persisted chain (accepted CO remove/replace line → target
  estimate line → claim rows → atom); "still live in the pool" is the
  whole skip test, so the skip-reason logic is not replicated.
  **Considered and declined for now:** keeping the job held after CO
  acceptance (making release-hold the worker's reconciliation act,
  parallel to release-to-floor) plus a SCOPE reconciliation banner. RM
  2026-07-20: don't change a working system — acceptance keeps
  auto-clearing the hold, no second hold layer, no job-status changes.
  Revisit if the badge alone proves insufficient in practice; the
  banner would reuse `struck_atom_keys` (built shared-ready). Note the
  inherent limit either way: work added outside the estimate has no
  claim chain, so no mechanism can identify it — that reconciliation is
  always the human's.
  When an atom is hard-deleted, source rows pointing at it are purged so
  no lens dangles; release never purges.
- **replace** — crystallize the replacement **first**, then retire the
  old atom (as above). A CO line carrying its own descriptor
  (service/inventory/is_material) crystallizes per that descriptor; a
  **bare** replace line mirrors the retired atom's type (Task or
  Material — the only two mirrorable atom kinds; `_mirror_of` raises if
  it's ever handed anything else) — a Task target yields a new pending
  Task with the same name / rate scheme / modifiers / sort order /
  assignee (`TaskBase.copy_fields`) at the CO line's qty and
  description; a Material target a new Material on the same inventory
  item (AC/units inherited when the line omits them). A bare replace
  whose target never crystallized (a plain line) has no atom to mirror,
  so it stays document-only, same as a bare add with no descriptor.

**Current-atom resolution (multi-CO chain).** The target of a
remove/replace is always an `EstimateLineItem`, but after an earlier
accepted CO replaced that line, the live atom is the *earlier CO line's*
crystallized atom, not the estimate's. Resolution therefore picks the
sources of the latest accepted-CO replace line targeting the same
estimate line (acceptance order: `closed_date`, then id), falling back
to the estimate line's own sources. This is how consecutive COs against
one line chain correctly. (The `compose_change_order_diff` display
baseline still has the documented single-CO limitation — see LATER.md;
crystallization does not share it.)

After the walk, `InventoryService.create_earmarks_for_job(job)` re-runs
the absolute earmark sweep — same as estimate acceptance — so
crystallized and retired materials net out to correct reservations.

**Idempotency** mirrors §9.2: crystallized lines carry a source row and
are skipped on re-run; retirement re-checks atom state (a cancelled
task, a deleted material) before acting.

**Billing stays with the agreement.** Crystallization never creates
billing lines. (The former `source_fee_id` plumbing in §14.6 — the
channel that fed crystallized Fees into `copy_from_estimate` claims —
was removed 2026-08, fee-removal Task 3.) Bleps on a
task cancelled by a remove/replace stay on record under the cancelled
task (the invoice wizard's complete-task gate applies as usual — the
cancelled work's time is reconciled by the human at invoicing).

Returns `{'tasks_created', 'materials_created',
'tasks_cancelled', 'materials_removed'}`. Tests:
`tests/test_change_order_acceptance.py`.

---

## 15. Sending an Estimate

`EstimateEmailService.send_estimate` (`apps/estimates/services.py`)
is the entry point. `EstimateEmailService` and its CO sibling
`ChangeOrderEmailService` subclass a shared `DocumentEmailService`
base (same module) that owns `get_email_defaults`,
`notify_shop_of_decision`, and the send skeleton; each subclass
declares its default subject/body, Configuration keys, labels, PDF
generator, and send validation. The SPA route `/estimates/:id/send` mounts
`DocumentSendForm.svelte`, populated by
`GET /api/estimates/{id}/send-defaults/`; submit POSTs
multipart to `/api/estimates/{id}/send/`.

**Send preconditions.** Before an estimate goes out — enforced in **both**
`EstimateEmailService.send_estimate` and the bare `EstimateService.mark_open`
(the draft→open shortcut) — every hand-line must have an accounting category.
`EstimateService.assert_all_hand_lines_have_ac` raises `ValidationError` (400)
listing the offending lines if any hand-line (no atom source, not a percentage
adjustment — atom-backed and adjustment lines are exempt) lacks one. This hoists
the AC-required rule from acceptance (§9) to send-time, so the omission is caught
before the estimate reaches the customer. (`mark_open` also still requires the job
to have at least one Deliverable.)

What happens on send (the cross-doc framing is in
`architecture-and-conventions.md` §7.10):

1. Generate the Estimate PDF via `apps/estimates/pdf.py:generate_estimate_pdf`
   (weasyprint over `templates/estimates/estimate_pdf.html`).
2. Call `OutboundEmailService.send_tracked` with
   `associate_with={'job': estimate.job}` — that persists an outbound
   `EmailRecord` linked to the parent Job (so the new email appears in
   the Job overview Email panel and participates in reply correlation).
3. On send success, transition `draft → open` (using `Estimate.save()`,
   so all the normal side effects from §5.1 still fire — `sent_date`
   gets stamped, `expiration_date` gets computed, the Job goes to
   `submitted`).
4. On SMTP failure, the exception re-raises so the API view returns
   502; the outbound EmailRecord persists with `last_send_error`
   populated, the Estimate stays `draft`.

Configuration keys:

- `estimate_email_subject_template` — default
  `Estimate {document_number}`.
- `estimate_email_body_template` — default starts with
  `Hi {contact_fname},…` and ends with `Thanks,\n{my_user_name}`.

The common template variable set is in
`architecture-and-conventions.md` §7.10. `{estimate_number}` is
available as an alias of `{document_number}`.

**Removed UI:** the previous Estimate detail page's "Mark as Sent"
button and the disabled "Send Estimate" placeholder are gone. The
underlying `POST /api/estimates/{id}/mark-open/` endpoint still
exists (workers triggering the status change without sending is
preserved as a back-door), but the normal flow is now Send Email,
which transitions status as part of the send-success path.

### 15.1 Customer approval (portal)

A customer can accept or reject a sent Estimate by clicking the
link in the send email — no Minibini account required.

**`Estimate.public_token`** (`CharField(max_length=64, null=True,
blank=True, unique=True)`) is minted in `Estimate.save()` at
creation (`if not self.pk and not self.public_token`), so the token
exists from the first write — well before any send. Each revision
row mints its own token. The token never hard-expires; live estimate
`status` determines what actions are available.

**URL shape.** `build_object_url('estimate', id)` now returns
`<our_public_url>/portal/?token=<public_token>` instead of the
previous stub internal URL. This is the value that lands in
`{object_url}` when composing the send email.

**Portal API (`apps/api/portal/`, all `AllowAny`,
`authentication_classes=[]`; shared helpers + the `decide` skeleton live
in `apps/api/portal/common.py` — see §14.10):**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/portal/estimates/<token>/` | Customer-safe payload: deliverables, line items, total, status |
| `POST` | `/api/portal/estimates/<token>/accept/` | Accept the estimate |
| `POST` | `/api/portal/estimates/<token>/request-changes/` | Ask for changes (optional `reason`); auto-revises, keeps the job alive |
| `POST` | `/api/portal/estimates/<token>/reject/` | Reject with optional `reason` |

The payload (`build_estimate_payload`) returns deliverables, line
items, and status; no internal IDs or operator data. The `actions`
list is `['accept', 'request_changes', 'reject']` while `open`, else `[]`.

**Customer-requested revision (`request-changes`).** Distinct from reject:
the customer wants the job but needs changes. Reject declines the *job*
(terminal); request-changes keeps it alive. The endpoint only acts from
`open` (a click racing the shop is a no-op), and calls
`EstimateService.request_changes(pk, actor)`, which:

1. Writes the customer's comment as an `action` HistoryEntry on the estimate
   (`_action='Changes requested via customer link'`, `user=None`, `text=`
   the comment) — the same plumbing as accept/reject.
2. Calls `revise_estimate` (§5.3): a fresh `draft` revision, sources moved,
   parent `superseded`.
3. Reverts the Job `submitted → draft` (a transition added for this; see
   `jobs-and-tasks.md`), so a draft job + draft estimate keep it
   in the pipeline. Reverting to `draft` fires no job-status side effects.
4. Emails the shop via `notify_shop_of_decision(estimate, 'requested changes',
   reason=...)`.

The shop sees the auto-staged revision two ways: a derived **"Revision"**
badge on the board card (`BoardService.is_revision` — the live estimate is a
`draft` with `version > 1`), and a banner on the Job detail page echoing the
latest comment (`JobSerializer.latest_change_request`, detail-only). The shop
edits the draft and re-sends; the customer can't request again until then
(the draft isn't portal-visible).

An **unknown/unmatched token** or a **draft estimate** both return the generic `Not available.` 404 — an unsent token leaks nothing, the same as an unknown token. A valid token for a **non-draft** estimate returns the full payload regardless of status; terminal, superseded, or expired states render a read-only status message with no action buttons.

**Actionability respects job status (`_is_actionable`).** The estimate is
customer-actionable only when **`estimate.status == open` AND
`job.status == submitted`**. The shop can move the job independently — cancel,
reject, manually approve, or reopen it — without touching the estimate (an open
estimate on a moved job is a legitimate real-world state). The portal **never
mutates the estimate from the job side**; it just respects job status. When an
estimate is `open` but its job is no longer `submitted`, the payload carries
`actionable=false`, an empty `actions` list, and `closed_message` = *"This
estimate is not open for response.  Please contact us for further
information."*, and the page renders that read-only message instead of buttons.
The three POST handlers (`accept`/`reject`/`request-changes`) apply the same
`_is_actionable` guard, so a stale browser tab can't act once the job has moved.

**Superseded → current revision link.** For a `superseded` estimate the payload
includes `current_token` — the token of the **latest non-draft version** for
the job (`_current_token`). Drafts are excluded (they aren't portal-viewable),
so a customer is never linked to an unsent revision; if the only newer version
is an unsent draft, `current_token` is `null` and no forward link is shown.

**Customer attribution.** Operator-side
`EstimateService.update_status(pk, new_status, actor=customer_dict)`
writes a `HistoryEntry` (entry_type `'action'`, `user=None`) with
the customer's name/contact from the `actor` dict, so the action
appears in the Job history feed with proper attribution without
requiring a User record.

**Shop notification.** On accept or reject,
`EstimateEmailService.notify_shop_of_decision(estimate, decision,
reason='')` sends a best-effort email to the `business_email`
Configuration key (see `data-constraints.md` §1.1). If `business_email`
is unset the notification is silently skipped; the accept/reject still
completes.

**Customer page.** `frontend/portal/` is a second Vite entry (built
by the same `npm run build`, served at `/portal/`). It is login-not-required,
has no operator nav, and reads the token from the query string.
`EstimatePortal.svelte` supplies the estimate copy and body tables to
the shared `components/PortalDocument.svelte` shell (§14.10). It
shows deliverables (top), line items + total, and a status banner.
**Actionable** estimates (open + submitted job) show Accept, Request changes,
and Decline buttons, each opening a confirmation panel with plain-language
consequences (Request changes and Decline take an optional comment). After a
successful Request changes the page shows a "we'll send a revised estimate"
message rather than the generic superseded notice. An `open` estimate whose
job has moved on renders `closed_message` read-only (no buttons). A
`superseded` estimate links to the latest non-draft revision's portal URL (or
no link if the only newer version is an unsent draft). All other terminal
statuses show a read-only status message.

Change-order customer approval mirrors this flow — see §14.10. A CO send
emails the portal link plus an auto-generated change-order PDF
(`generate_change_order_pdf`, which renders the before/after diff) and
transitions the CO `draft → open`.

---

## 16. Unfinished work

> **Default service price for worker quick-add — RESOLVED (task-owned-money
> Phase 1, §3.4).** The `default_rate_scheme` Configuration key now
> preselects the CREATE dropdown on `WorkItemForm` for every user
> (worker or manager), set via the RateSchemeManager's default-preset
> picker.

- **Per-blep entered-qty provenance (deferred extension)** — per-session
  quantities are BUILT (see §4.2) as a single accumulator on Task; if
  per-session provenance (reviewing/editing who produced what) is ever
  needed, the extension is a nullable `entered_qty` Decimal on `Blep` —
  *not* JSON in `Task.actual_qty`. A Blep is the record of a work
  session, so "what the session produced" is session-shaped data; the
  column gets lifecycle for free (delete a blep, its entry goes; the
  blep edit modal is the natural editing surface; user/time provenance
  already on the row) and avoids the JSON blob's problems (no
  referential key to bleps, read-modify-write lost updates on a shared
  blob, summing decimals-as-strings instead of `Sum()`). Shape: running
  total = `Sum(blep.entered_qty)`; `get_actual_qty` returns
  `task.actual_qty` when set (the settled value written at completion)
  else the blep sum. Safe because a complete task can never blep again,
  so the settled value can't be stranded by later entries. The no-blep
  entry path (ENTERED_QTY tasks can complete without any time logged)
  is why the task-level field must survive in this design.
  - **Interaction to guard:** if the job-level `work-complete` action
    ever grows bulk task completion (an open issue considers blocking
    it on in-progress tasks instead), it must refuse on unsettled
    `ENTERED_QTY` tasks rather than invent quantities — the settle-up
    prompt (§4.2) assumes a human is looking at the specific task.

- **Estimate-vs-actuals reporting** — once `est_qty` and
  `actual_qty` (or Bleps) coexist on Task, a per-job and per-template
  variance report becomes trivial. "We're at 7 of 12 estimated" or
  "How accurate are estimates for this template?" are both unblocked
  by data but not yet built.

- **Auto-fill `est_worker_time` when scheme units are hours —
  RESOLVED.** `apps/core/units.py` defines a canonical `HOUR_UNIT`
  ("hour"); `hours_pair_fill` (§4.3) derives whichever of
  `est_qty` / `est_worker_time` is missing for any hour-unit scheme, and
  `WorkItemForm` presents one "Estimated hours" input.

- **`@history` decorator on `Task`** — billing-config changes on a Task
  (service-price reassignment, modifier toggles) are a normal
  estimating-related event but don't surface in the Job HistoryPanel.
  Tracked in `jobs-and-tasks.md`.

- **`accounting_category` required on `EstimateLineItem`** — part of the
  project-wide line-item AC-NOT-NULL migration tracked in
  `architecture-and-conventions.md`.

- **`EstimateAcceptanceService.on_accept` review — RESOLVED (superseded
  by the 2026-08-09 Fee retirement).** The item used to ask for a review
  of a design where every hand-line crystallized into a `Fee`. That
  design is gone: the current behaviour (§9) crystallizes only
  descriptor-bearing hand-lines into Tasks/Materials; a plain hand-line
  crystallizes nothing and stays a document line, transiting to invoices
  via an agreement-line reference instead (§4.5). This is the settled
  shape, not an open review item.

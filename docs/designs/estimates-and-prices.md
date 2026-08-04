# Estimates and Billing

Reference for the estimating side of Minibini: `RateScheme` as an
editable service-price preset, task-owned money (a `Task` stamps a
permanent copy of a preset's pricing at creation time), the
billable-atom abstraction, the estimate wizard, the job-atom projection
(documents-as-lenses), acceptance crystallizing hand-lines into atoms
(Materials or Fees), and AC pass-through.
Read alongside:

- `docs/designs/architecture-and-conventions.md` — service-layer
  pattern, `LineItemMixin`, exception hierarchy
  (`ServiceError` / `NotFoundError` / `SchemeInactiveError`).
- `docs/designs/jobs-and-tasks.md` — `Task`, `Material`,
  `Fee` (the Job's work atoms), the Work surface, populate paths, signal
  receivers (`estimate_accepted`, `estimate_status_changed_for_job`).
- `docs/designs/materials-inventory-and-purchasing.md` — `Material`
  (the other atom family), `InventoryItem`.
- `docs/designs/invoicing-and-expenses.md` — the parallel invoice
  wizard built on the same source-row pattern.
- `CLAUDE.md` — status constants, document-numbering service,
  `AccountingCategory` shape, line-item delete rule.

> **Job-owns-atoms model.** Work atoms (`Task`, `Material`, `Fee`) live
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
- The atom abstraction (atoms are Tasks, Materials, and Fees; whole-atom
  billing).
- `EstimateWizardService`, the wizard endpoints, and the wizard UI.
- `EstimateAcceptanceService` — what fires when an Estimate is accepted
  (hand-line → Material/Fee crystallization, earmarks).
- AC pass-through rules from RateScheme → Task / line item.

It does **not** own:

- The Job/Task shape or status machines (jobs-tasks doc).
- The Material side of the atom family beyond the pieces the wizard
  touches (materials doc).
- The `Fee` atom model shape (jobs-tasks doc) beyond its role as a
  billable atom and acceptance crystallization target.
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
it in turn generates a Task. (Fixed one-off charges are the `Fee`
atom — see §4.5 — not a RateScheme.)

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
> fee) is now the **`Fee` atom** on the Job — `quantity × unit_rate` with
> its own `accounting_category` (see §4.5). `copy_active_modifiers()`
> collapses any legacy `{'flat_fee_price': …}` dict to `[]`.

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
| `POST /api/rate-schemes/{id}/retire/` | Flip `is_active` to `False` — `CanManageConfig`. Clears the `default_rate_scheme` Configuration key if this was it (§3.4). |
| `POST /api/rate-schemes/{id}/reactivate/` | Flip `is_active` back to `True` — `CanManageConfig` |
| `DELETE /api/rate-schemes/{id}/` | Delete — allowed even with stamped tasks (`Task.source_scheme` is `SET_NULL`); blocked (409 via `ProtectedError`) only while a `ServiceItem` still references it (`ServiceItem.rate_scheme` is `PROTECT`) |

Permissions: read is `IsAuthenticated`; all write actions require
`CanManageConfig`.

Create/update/delete/retire/reactivate route through
`ConfigurationService.{create,update,delete,retire,reactivate}_rate_scheme`
(`apps/core/services.py`). The serializer exposes `reference_counts`
(display only, §2.5) and validates `unit_label` against the configured
units list (`apps/core/units.get_units_list`).

### 3.4 Default preset

The `default_rate_scheme` Configuration key (string-encoded `RateScheme`
pk, or `''` — see `data-constraints.md` §1.1) preselects the CREATE
dropdown on the manual task-creation form (`WorkItemForm`) for every
user, manager or worker alike. Set via the RateSchemeManager's default
preset picker (`PATCH /api/settings/` with `default_rate_scheme`,
explicit Save — not auto-committed on change).

- `PATCH /api/settings/` rejects a value that isn't blank or an
  **active** RateScheme id.
- `ConfigurationService._clear_default_rate_scheme_if_matches` is the
  single gate that clears the key to `''` whenever the current default
  preset transitions `is_active: True → False` — called from both
  `retire_rate_scheme` and the general `update_rate_scheme` path (a
  plain field-level `PATCH {"is_active": false}` can't strand the
  default pointing at an inactive preset either).

### 3.5 Picker filtering

Task-creation pickers request `?task_applicable=true` (active,
non-percentage only). The RateSchemeManager (outdated-schemes /
retirement UI) defaults to active-only and reveals the full set via
`?include_inactive=true`.

---

## 4. Task billing (and the Fee atom)

**Task-owned money (Phase 1).** `Task` carries its own permanent money
block directly — not a live FK to `RateScheme` — stamped once at
creation by `Task.stamp_from_scheme` (§3.1). The full field shape lives
in `docs/designs/jobs-and-tasks.md` §4.4. Recap of the billing fields:

| Field | On Task | Notes |
|---|---|---|
| `qty_source` | own field | `'elapsed_time'` / `'entered_qty'` (`Task.QTY_ELAPSED` / `QTY_ENTERED`); copied from `scheme.algorithm` at stamp time. Never `'percentage'` — percentage schemes can't stamp a task. |
| `rate` | own field | Decimal, nullable. `effective_rate()` returns `0.00` when `None` (e.g. a task cloned or built without a scheme). |
| `unit_label` | own field | CharField, default `'none'` |
| `accounting_category` | own field | FK → `AccountingCategory` (PROTECT), **nullable end-to-end** (DB and API — task-owned-money Phase 3): a stamp-only create still fills it from the preset (`RateScheme.accounting_category` is itself required), but a manual/flat task may be created or edited with none — "categorize at invoicing" (§10). Writing or clearing it is gated by `MONEY_FIELDS` (§10.1). |
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
        # Own rate + own active_modifiers surcharges. When rate is None
        # AND this task is a parent (task-owned-money Phase 4, §4.1a),
        # the rate derives from its children instead of defaulting to
        # zero. An explicit rate on a parent always overrides derivation.
        if self.rate is None:
            if self.is_parent:
                return self.derived_unit_price()
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

### 4.1a Parent/subtask billing aggregation (task-owned-money Phase 4)

A **parent task** — one with ≥1 subtask, `Task.is_parent` — is priced
by aggregating its children rather than carrying its own `rate`. Full
non-billing mechanics (non-startable enforcement, the
`qty_scales_with_parent` flag, the `expected_qty`/`expected_worker_time`
derivation helper, Template N, the Deliverables bridge) are the
**definitive reference** in `jobs-and-tasks.md` §4a; this section
covers only the billing/aggregation math and how it flows through the
estimate/invoice wizards.

**`Task.derived_unit_price()`** — the parent's per-unit price:

```python
per_unit_total = Σ(flag-True child.est_qty × child.effective_rate())   # already per-unit
batch_total    = Σ(flag-False child.est_qty × child.effective_rate())  # a per-batch total
derived_unit_price = (per_unit_total + batch_total / (parent.est_qty or 1)).quantize('0.01')
```

`None` when the task is not a parent. Quantized once, at the end — the
per-child amounts are not individually rounded first. When the
flag-`False` sum is non-zero but the parent's own `est_qty` is falsy,
the divisor is treated as `1` (the raw batch total stands) rather than
raising.

**Both money entry points bill the parent through the one rate.**
Neither `compute_estimate_amount()` (`est_qty × effective_rate()`) nor
`compute_amount()` (`get_actual_qty() × effective_rate()`) needed a
parent-specific branch — `effective_rate()`'s own fallback (§4.1)
already routes there. Concretely: the **estimate** side bills the
parent's own `est_qty` (the structure quantity — "10 units of this
assembly"); the **invoice** side bills `get_actual_qty()`, which for
an entered-qty parent is the parent's own `actual_qty` — the
completion-time "quantity actually made," settled through the same
entered-qty prompt a leaf task uses (`jobs-and-tasks.md` §4a.1).

**Wizard composition.** `_task_qty_and_price` (both
`EstimateWizardService` and `InvoiceWizardService`) gates a single-atom
line-item copy on `task.rate is not None or task.is_parent`, so a
derived-price parent composes correctly solo (qty = the parent's own
qty field, price = `effective_rate()`). A parent mixed into a
multi-atom bundle with a differently-rated sibling still falls back to
the pre-existing non-uniform summary (`_uniform_money_bundle` already
treats any `rate is None` atom as non-uniform) rather than crashing —
a parent can't currently be summarized into a *uniform* bundle
alongside siblings, same as any other `rate=None` atom.

**Pool exclusion and direct-claim rejection** — see §7 "Wizard-pool
billability gates" below; the short version is that a subtask never
appears in a source pool and is rejected if claimed directly, on both
the estimate and invoice sides, so the parent is always the sole
billing surface for its structure.

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

### 4.5 Fee — the fixed-charge atom

`Fee` (`apps/jobs/models.py`, `db_table = 'fees'`) is the third billable
atom and the **crystallized form of an accepted hand-line** (§9). It is a
pure pricing decision, not a record of work:

| Field | Type | Notes |
|---|---|---|
| `fee_id` | AutoField PK | |
| `job` | FK → Job (CASCADE, `related_name='fees'`) | owning job |
| `description` | CharField(255), blank | |
| `quantity` | Decimal(10,2), default `1.00` | |
| `unit_rate` | Decimal(10,2) | **required, signed, never zero** — negative is a valid credit |
| `accounting_category` | FK → AccountingCategory (PROTECT) | **required, NOT NULL** |
| `sort_order` | PositiveInteger, default 0 | |

Fee had a `task` OneToOne (SET_NULL, nullable) through 2026-08-03; it was
dormant (nothing in the UI ever populated it) and was dropped in the same
migration that made `unit_rate` signed (task-owned-money Phase 2, Task 1)
— Fee no longer references Task at all, and a Fee is otherwise unchanged
(job-owned, `quantity × unit_rate`, its own required AC, claims via
`fee` source rows, always-billable).

`Fee.compute_amount() → (quantity × unit_rate).quantize('0.01')`;
`effective_accounting_category` returns its own `accounting_category`;
`units` is `'none'`. A Fee has no lifecycle and no actuals — it is
**always billable** (unlike a Task, which must be `complete`, or a
Material, which must be `consumed`). A **negative `unit_rate` is a
credit** — `unit_rate == 0` is rejected (400) by
`FeeService._reject_zero_unit_rate` (a zero-rate Fee charges nothing;
the model itself has no validator for this, so it's enforced in the
service per house pattern). Writes go through `FeeService`
(`apps/jobs/services.py`) — `create_on_job` / `update` / `delete`, all
respecting the job's on-hold guard — and the API at
`POST /api/jobs/{id}/fees/`. The task-list page's create form
(`FeeModal.svelte`) is labeled "Fee / Credit" and shows an inline "This
will appear as a credit." note when the entered amount is negative.

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
crystallize into atoms at acceptance — catalog lines into Materials, the rest
into Fees.) There is no manual recalculate step. Freeze is implicit:
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
- `freeform_kind` — nullable CharField, choices `work` | `material` |
  `fee` (task-owned-money Phase 2 Task 2; replaced the retired
  `is_material` boolean). Set **iff** the line is bare (no
  `inventory_item`, `service_item`, or `adjustment_service`) —
  `EstimateService._reject_freeform_kind_on_non_bare_line` rejects a
  direct write on any other line shape. At acceptance it discriminates
  the crystallization target (§9.1): `material` → an established
  `Material` (reverse-markup placeholder cost), `work` → a flat `Task`
  (entered-qty, no `RateScheme`), `fee` (or `NULL`, for pre-migration
  rows) → a `Fee`. **Required at entry on a bare `add_line_item` call**
  (Task 4) — the old silent bare-line default of `Fee` no longer applies
  to new writes; only legacy rows may carry `NULL`. **Immutable after
  creation** — `update_line_item` rejects any attempt to change an
  already-set kind (`ValidationError` on `freeform_kind`); re-sending the
  same value is a no-op.
  The `is_material` boolean is **fully retired, not just SPA-free** — the
  compatibility alias that used to translate it into `freeform_kind` at
  the service boundary was itself removed (task-owned-money Phase 3,
  Task 6): `EstimateService._reject_is_material_field` (shared by
  `ChangeOrderService`) now 400s any `add_line_item`/`update_line_item`
  payload that still carries an `is_material` key at all —
  `{'is_material': ['Retired field — send freeform_kind directly
  ("work", "material", or "fee").']}` — rather than translating it or
  silently ignoring it. There is no longer any live path (SPA or API)
  that accepts `is_material`; every caller must send `freeform_kind`
  directly.
  A hand-line's **sign/zero rules** (Task 4, enforced by
  `EstimateService._validate_price`, shared with `ChangeOrderService`):
  negative `price` is allowed only when `freeform_kind='fee'` (a
  credit) — `work`/`material` lines (and catalog/service lines, which
  never carry `freeform_kind`) reject a negative price; a `fee` line's
  `price` must not be `0` (it maps straight onto `Fee.unit_rate` at
  acceptance, and a zero-rate `Fee` is forbidden). Percentage adjustment
  lines are exempt from both rules.
- `service_item` — nullable FK to `estimates.ServiceItem` (PROTECT,
  `related_name='+'`). Deferred service descriptor: the line carries the
  `ServiceItem`'s snapshotted price at authoring time, and the FK is the
  crystallization target that `on_accept` resolves to a `Task` (§9.1).

The serializer exposes a read-only `adjustment_service_detail` dict
`{name, rate, algorithm}` for display purposes when `adjustment_service`
is set. It also exposes `service_item` (writable FK PK, nullable) and a
read-only `service_item_detail` dict `{template_id, name}` (or `null`).

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
    source_type         CharField — 'task' | 'material' | 'fee'
    source_pk           PositiveIntegerField

    Meta:
        db_table = 'estimate_line_item_sources'
        unique_together = [('source_type', 'source_pk')]
```

Atoms are the Job's `Task`, `Material`, and `Fee` (`SOURCE_TASK`,
`SOURCE_MATERIAL`, `SOURCE_FEE`). These are the **same** job atoms the
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

`source.resolve()` returns the concrete atom instance (`Task`,
`Material`, or `Fee`).

CASCADE on `EstimateLineItem` deletion: deleting a line item releases
its claims. On revision, `revise_estimate` **moves** the source rows onto
the new line items (§5.3), so the live estimate is always the one lens
over the atoms; superseding/rejecting/expiring otherwise does not touch
claims.

**No source row outlives its atom.** `Material.delete()`, `Fee.delete()`,
and `Task.delete()` call `purge_source_rows_for_atom`
(`apps/estimates/claims.py`), which drops the estimate-, CO-, and
invoice-lens source rows pointing at the deleted atom. This holds on
*every* deletion path — restock-to-zero (incl. the job-completion
loose-material release), PO sever, fee/task delete, CO retirement — so
`resolve()` consumers never hit a dangling pk. The source serializers
additionally render a dangling row (pre-purge data) as `null` rather
than 500ing. Paths that must not delete a billed atom guard *before*
deleting (`_assert_not_invoiced`, the CO retirement skips); the purge is
the consistency backstop, not the guard.

### 6.3 Atom-to-line-item shapes

| Source rows on a line item | What it represents |
|---|---|
| 0 | A **hand-line** — manually authored, no atom backs it. Crystallizes at acceptance via the four-way discriminator (§9.1): `service_item` → Task, `inventory_item` → Material, bare `freeform_kind='material'` → established Material (reverse-markup cost), bare `freeform_kind='work'` → flat Task, bare `freeform_kind='fee'`/`NULL` → Fee. |
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
material or fee atom present, mixed service prices, or mixed modifiers)
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

**`_apply_material_ac_default`.** Bare `freeform_kind='material'` lines with no explicit AC default to the `Configuration['default_material_accounting_category']` key (stored as a string `AccountingCategory` PK). `_apply_material_ac_default` resolves the key and raises `ValidationError` if the key is absent or the PK is stale. `work` and `fee` hand-lines get no default — both still require an explicit AC at entry (the generic hand-line AC-required check, unconditional on kind — no atom source and not an adjustment means an AC is mandatory). The key is editable via a "Default material category" picker (`DefaultMaterialCategorySetting.svelte`, extracted out of `AccountingCategories.svelte`), rendered in both Settings' Accounting and Pricing tabs; `PATCH /api/settings/` validates it as blank-or-active-category-id (`data-constraints.md` §1.1).

**Kind required at entry (Task 4).** A bare `add_line_item` payload (Estimate, or a CO line with `action='add'` — REPLACE/REMOVE carry no kind requirement of their own, since REPLACE mirrors the target's current atom type) must carry a direct `freeform_kind` or the call 400s with `{'freeform_kind': [...]}` (Task 6 removed the `is_material` alias entirely — an `is_material` key in the payload now 400s on its own, above, rather than resolving a kind). `update_line_item` never re-requires a kind (an untouched line keeps its persisted one); it only rejects an attempt to *change* an already-set kind.

**API endpoint:**

| Verb + path | Behavior |
|---|---|
| `POST /api/estimates/{id}/line-items-from-service/` | Body: `{service_item: <PK>, qty: <N>}`. Returns 201 with the serialized line. Permission: `CanManageJobs`. |

**`PriceListPicker.svelte` — the unified picker.** Both the estimate detail page and the job task-list page use `PriceListPicker` as the single "Add line / Add Work" entry point. The component is a pure `onChoose` emitter — zero surface-specific logic. It searches service items and catalog inventory items in parallel via their respective `?search=` endpoints and emits one of:

| `onChoose` payload | Meaning |
|---|---|
| `{type: 'service', serviceItem}` | User picked a `ServiceItem` from the catalog |
| `{type: 'inventory', inventoryItem}` | User picked a catalog `InventoryItem` |
| `{type: 'freeform', typed, kind}` | **Estimate/CO footer** (non-`taskSurface`): three explicit buttons — Add Work / Add Material / Add Fee-Credit — emit `kind: 'work' \| 'material' \| 'fee'` directly (matches `EstimateLineItem`/`ChangeOrderLineItem.freeform_kind`; the retired `is_material` alias is never sent from this footer) |
| `{type: 'freeform', typed, isMaterial}` | **Task-list footer** (`taskSurface`): Task / Material / Fee buttons — unchanged, still `is_material`-shaped (that surface creates a `Task`/`Material`/`Fee` atom directly, not a line item) |
| `{type: 'freeform-task', typed}` | Task-list footer only — a manual Task (rate scheme picked in the follow-up `WorkItemForm`) |

On the **estimate detail page** (`EstimatePanel.svelte`, hosted at `#/jobs/:jobId/estimate/:docId`) and the **change-order panel** (`ChangeOrderPanel.svelte`), the picker is followed by `EstimateAddLineForm.svelte` / `COAddLineForm.svelte` respectively — twin components that dispatch to the correct endpoint (`line-items-from-service/` for service picks, the standard `line-items/` POST — CO adds `action: 'add'` — for inventory or freeform picks) and render a kind-specific freeform subform once a bare line is chosen:

| `kind` | Subform |
|---|---|
| `work` | An optional **preset dropdown** (`GET /api/rate-schemes/?task_applicable=true`, same active/non-percentage list as `WorkItemForm`'s manual-mode dropdown; `default_rate_scheme` from `/api/settings/` preselects it when present in the list) — picking a preset only **stamps** its `rate`/`unit_label`/`accounting_category` into the editable local fields client-side; no scheme id is ever sent. Plus description/qty/units/rate/AC (AC required). Payload: `freeform_kind: 'work'` + plain description/qty/units/price/accounting_category. |
| `material` | The pre-existing form: description/qty/units/price/AC (AC prefills from `default_material_accounting_category`, overridable, and is optional — the backend fills it if blank). Payload: `freeform_kind: 'material'`. |
| `fee` | description/qty (default 1)/signed amount/AC (required) — a negative amount shows an in-form "This will appear as a credit" note. Payload: `freeform_kind: 'fee'`. |

A negative amount on the Work or Material subform is rejected client-side with a field error ("Negative price is only allowed on a Fee/Credit line.") before it ever reaches the server-side `_validate_price` check (§6.4 above). Line tables (`LineItemTable.svelte`, shared by the estimate/CO/invoice surfaces) render a `.kind-badge` (Work / Material / "Fee/Credit") next to the description on any line carrying `freeform_kind`; adjustment lines keep their separate `.adj-badge` and never also get a kind badge (a bare line and an adjustment line are mutually exclusive). `LineItemTable.svelte`'s money formatting is `formatMoney()` from `lib/format.js` (the house-wide currency formatter — `toLocaleString` currency style, not raw `$` string-concatenation), so a negative fee/credit line's price and total render `-$80.00` rather than the mangled `$-80.00`. `formatMoney(n, { decimals })` is the one shared implementation — `WizardAtomRow.svelte`, `COLineItemsSection.svelte`, `lib/taskTotals.js`, and `lib/jobOverview.js` (whole-dollar `{ decimals: 0 }` mode) all delegate to it rather than each hand-rolling their own `$`-concatenation (a prior round of this fix touched three of those sites independently before a review caught the other two still mangling negatives — see git history on `feature/fees`).

On the **job task-list page** (`JobTaskListPage.svelte`), the same picker opens `WorkItemForm` (service pick → Task via `/add-from-template/`), `MaterialModal` (inventory pick — `presetPli`, `presetDescription`, `defaultMaterialCategoryId`), or `FeeModal` (freeform non-material — `presetDescription`). See `docs/designs/jobs-and-tasks.md` §9.5.

`LineItemModal.svelte` (generic edit-only modal, also shared by Invoice) and `COLineItemModal.svelte` (CO replace/edit) display an existing bare line's `freeform_kind` **read-only** (`freeform_kind` is immutable after creation — no editor) rather than the retired `is_material` checkbox/flag.

---

## 7. Billable atoms (documents as lenses)

An **atom** is a billable unit owned by the **Job**: a `Task`,
`Material`, or `Fee`. Atoms implement a uniform interface:

- `compute_amount(active_modifiers=None) → Decimal` (Task also has
  `compute_estimate_amount()` — the estimate-side projection of `est_qty`)
- a description (`atom.description` or `atom.name` for tasks)
- units (from the rate scheme on tasks; from the atom for materials; `'none'` for fees)
- an `accounting_category` (derived for tasks via the rate scheme; direct on materials and fees)
- a source-pointer identity (`source_type` + pk)

An `Estimate` and an `Invoice` are **lenses** over these job atoms: each
document's line items optionally link to an atom via its source table
(`EstimateLineItemSource` / `InvoiceLineItemSource`). The **estimate**
projects `est_qty` (`Task.compute_estimate_amount`); the **invoice** bills
the locked `actual_qty` of complete tasks (`Task.compute_amount`); Fees
are always billable on either side. A line item with no source is a
**hand-line**.

| Atom | Owner doc | Estimate amount | Invoice amount |
|---|---|---|---|
| `Task` | this doc / jobs-tasks | `compute_estimate_amount` (est_qty) | `compute_amount` (actuals; task must be complete) |
| `Material` | materials doc | `compute_amount` (qty × sell_price) | same (must be consumed) |
| `Fee` | jobs-tasks (§4.5 here) | `compute_amount` (qty × unit_rate) | same (always billable) |
| `Expense` (material-less) | invoicing doc | _(invoice-only)_ | `compute_amount` |

Bleps are read-only detail under their task's atom; they are never
claimed as atoms themselves. **Whole-task billing**: there is no
business reason to split bleps from one Task across multiple line
items; if such a need arises, the Task itself gets split first.

**A subtask is never an atom on its own** (task-owned-money Phase 4):
when a Task has a `parent_task`, its parent is the sole billing surface
for the whole structure — see §4.1a and the pool-exclusion rule below.
The `Task` row in the table above describes a top-level task; a parent
task's amount is the same `compute_estimate_amount`/`compute_amount`
call, just backed by `derived_unit_price()` instead of an own `rate`.

Atom claim semantics (per document):

- An atom is **available** if no source row of that document points at it.
- An atom is **claimed** if a source row exists pointing at it.
- The DB-level unique on `(source_type, source_pk)` makes
  double-claim impossible within one document table.
- **Claim state on the job detail page.** Each Task/Material/Fee
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
`not_billable_reason` (`'task_incomplete'` or `'material_unconsumed'`). They
are rendered greyed-out and non-selectable in `WizardSourcePool.svelte` so
the invoicer can see what is pending without being able to add it yet.

`InvoiceWizardService._assert_atom_billable` is the service-side enforcement
point: it re-checks readiness when atoms are actually submitted to the wizard
(i.e. when `add_atoms_to_new_line_item` / `add_atoms_to_line_item` resolve
each atom), raising `ValidationError` if the readiness condition is not met.
(The estimate side has no readiness gate — it projects `est_qty`, which exists
the moment a Task is created.)

**Subtask exclusion (task-owned-money Phase 4, §4.1a)** applies on
**both** sides and at **two** layers, not just the pool listing:

- **Pool listing** — `get_source_pool` filters `parent_task__isnull=True`
  on its task queryset (`EstimateWizardService` and
  `InvoiceWizardService` both), so a subtask never appears as a row to
  pick, claimed or otherwise.
- **Direct claim** — `BaseWizardService._assert_atom_billable`'s base
  implementation (not a subclass override) rejects any atom that is a
  `Task` with `parent_task_id is not None`, before either wizard's own
  lifecycle-readiness check runs. This closes the path a client could
  otherwise use to route around the pool by POSTing a child's
  `{type, id}` straight at `add_atoms_to_new_line_item` /
  `add_atoms_to_line_item` — `InvoiceWizardService`'s override calls
  `super()._assert_atom_billable(instance)` first, so the base
  rejection isn't bypassed by the subclass chain.

The parent itself is never excluded — it's the one billable surface
for the whole structure, priced via `derived_unit_price()` (§4.1a).

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
no longer a worksheet source. (Fees are created by acceptance, not picked
in the wizard.)

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

| Component | Path | Role |
|---|---|---|
| `ReconcileMode.svelte` | `frontend/src/components/wizards/` | Reconcile-mode view, rendered in place by `EstimatePanel`/`InvoicePanel` (§12; `jobs-and-tasks.md` §9.6) — not a route. Two-column layout (source pool left, line items right), parameterized per `docType` via a config block. Loads doc + line-items + source-pool on mount; re-fetches line items after every action and reconciles atom states locally |
| `WizardSourcePool.svelte` | `frontend/src/components/estimates/` | Renders the flat atom list; binds `selectedAtoms` to `ReconcileMode`. Each atom is a `WizardAtomRow`. The invoice wizard has its own task-grouped `WizardSourcePool.svelte` that reuses the same row. |
| `WizardAtomRow.svelte` | `frontend/src/components/wizards/` | One source-pool atom row, shared by both wizards: checkbox + `description — qty units × $rate = $total` + claim state. The `[type]` tag reads `[fee / credit]` for a fee atom (`unit_rate` is signed — a fee atom's row can be a credit); the qty×rate=amount detail is formatted with `lib/format.js`'s shared `formatMoney()` (not raw `$` string-concatenation) so a negative amount renders `-$80.00`, never the mangled `$-80.00`. |
| `WizardLineItemCard.svelte` | `frontend/src/components/wizards/` | One line-item card with its source rows; surfaces "Add Here" and per-source remove |
| `WizardActions.svelte` | `frontend/src/components/wizards/` | Bottom action bar (Discard draft, Done — flips the panel back to lines mode in place) |
| `LineItemModal.svelte` | `frontend/src/components/` | Shared modal for direct (no-atom) line item create/edit. Used by **both** the Invoice and Estimate detail pages (manual/catalog toggle on add; field-edit on edit). The estimate detail page authors hand-lines again via **Add Line Item** + per-line **Edit** (Phase 6's atoms-only projection was reversed). |

The invoice-side wizard is structurally parallel — same source pool,
add-atoms, remove-atoms, in-sync rule. Both wizards now read the **same**
Job atoms (Tasks + Materials). Components are partially shared (e.g.
`WizardLineItemCard`, `WizardActions`); the invoice WizardSourcePool is
its own component (`frontend/src/components/invoices/WizardSourcePool.svelte`)
because the invoice pool also surfaces billability gates (task complete /
material consumed) and Expenses. Pointer: invoicing doc.

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
**crystallizes the estimate's hand-lines into job atoms** so the agreed
price of a hand-authored line becomes a real, billable job atom. Each
sourceless hand-line (no `EstimateLineItemSource`, not a percentage
adjustment) goes through a **discriminator** in order: `service_item` →
Task, `inventory_item` → Material, bare `freeform_kind='material'` →
established Material (reverse-markup cost), bare `freeform_kind='work'` →
flat Task, bare `freeform_kind='fee'`/`NULL` → Fee.

A **work** hand-line mints a **flat Task** (task-owned-money Phase 2,
Task 3) — entered-qty, no `RateScheme`, claimed via a `source_type='task'`
row exactly like a service-generated Task (see §9.1's full field list and
§14.11 for why the CO-retire discriminator can't tell a flat task apart
from any other by looking at the atom alone).

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

   - **Bare material line** (`freeform_kind='material'`) →
     create a `Material` via `MaterialService.create_on_job`
     (`inventory_item=None`, `sell_price = li.price`), then **establish it**
     via `MaterialService.establish_reverse_markup` with a **reverse-markup
     provisional cost**:
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

   - **Bare work line** (`freeform_kind='work'`) → create a **flat `Task`**
     (task-owned-money Phase 2, Task 3), not a service-generated one:
     `Task(job=job, name=(li.description or 'Work')[:100],
     description=li.description or '', qty_source=Task.QTY_ENTERED,
     est_qty=li.qty, rate=li.price, unit_label=li.units,
     accounting_category=li.accounting_category, source_scheme=None)` — no
     `RateScheme` behind it; the estimate line's own typed qty/rate/units/AC
     become the task's permanent stamp, exactly as a manually-added
     `WorkItemForm` (manual mode) task would carry them. A defensive guard
     raises `ValidationError` on a negative `price` here (entry-time
     validation, Task 4, should already have caught it).
     `JobService.mark_work_reopened(job)` runs alongside — the same call a
     manually-added task triggers — so a `work_complete` job correctly
     reopens. Record an `EstimateLineItemSource` with `source_type='task'`
     (a flat work Task claims exactly like a service-generated one; nothing
     on the `Task` row itself flags it as flat — see §14.11's CO-retire
     discriminator for why that distinction has to live on the *claiming
     line*, not the atom).

   - **Fee (default)** — bare `freeform_kind='fee'`, or `NULL` on
     pre-migration rows — → create a `Fee`: `description`, `quantity = li.qty or
     1`, `unit_rate = li.price or 0`, `accounting_category`, `sort_order =
     li.line_number or 0`. A defensive guard raises `ValidationError` if the
     line has no `accounting_category` (the fee atom requires it NOT NULL;
     the error gives a useful message instead of an opaque IntegrityError).
     Record an `EstimateLineItemSource` with `source_type='fee'`.

   Either way the line becomes atom-backed, so `copy_from_estimate`
   (invoice side) can trace which hand-line maps to which atom and claim it.

2. Atom-backed lines (those that already have an `EstimateLineItemSource`
   for a Task / Material / Fee) are skipped — their atoms are already on the
   job. Adjustment lines stay document-only (they recompute against the
   live lines and never become atoms).
3. Call `InventoryService.create_earmarks_for_job(job)`, so accepting an
   estimate earmarks the job's inventoried materials (including any just
   crystallized from catalog hand-lines or bare material lines).

`on_accept` returns `{'fees_created': int, 'materials_created': int,
'tasks_created': int, 'work_tasks_created': int}` — `tasks_created`
counts service-line Tasks, `work_tasks_created` counts flat work-line
Tasks, tallied separately since they crystallize through different
branches of the discriminator above.

### 9.2 Idempotency

Because each crystallized hand-line gets a source row (fee, material, or
task), re-firing acceptance would find those lines already source-backed
and skip them — the same guard that protects atom-backed lines. The
earmark step is an absolute aggregate sweep, so it is idempotent on
re-run too.

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
`RateScheme` (NOT NULL) and on `Fee` (NOT NULL). `Task` carries its
**own** `accounting_category` — stamped from the preset at creation,
then a permanent field the task owns — and, since **task-owned-money
Phase 3**, it is **nullable end-to-end**: nullable at the DB level *and*
optional in the API (`TaskSerializer.accounting_category` is
`required=False, allow_null=True`). A stamp-only creation (picking a
`RateScheme` via `rate_scheme`) still fills it from the preset, because
`RateScheme.accounting_category` is itself required — a task only ends
up with no AC when someone deliberately leaves it blank (a manual/flat
task with no preset) or a manager/financials write clears an
already-stamped one. `ServiceItem` still reads AC live off its
`RateScheme` FK. Every other billable concept carries AC directly
(Materials with no PLI; Expenses; Fees — required).

A null-AC Task is not an error state — it's **"categorize at
invoicing"**: composing it onto an invoice line stamps the configured
**fallback accounting category** onto the *line* (never the Task
itself) — see §10.1a and `invoicing-and-expenses.md`'s "Fallback
accounting category" section for the full mechanic, and
`data-constraints.md` §1.1 for the `fallback_accounting_category`
Configuration key.

### 10.1 Where AC comes from

| Object | AC source |
|---|---|
| `RateScheme` | own field, required |
| `Task` | own field — stamped from `scheme.accounting_category` by `Task.stamp_from_scheme` at creation (§3.1) when a preset is picked; `Task.effective_accounting_category` returns it directly, no FK traversal. **Nullable end-to-end** (task-owned-money Phase 3) — a manual/flat task may be created or edited with no AC ("categorize at invoicing", above). Writing it — including *clearing* an existing value to null — is gated by `TaskSerializer.MONEY_FIELDS`: only `CanManageJobOrPM` or `can_manage_financials` may set/clear it; everyone else's stamp-only creates get the preset's AC with no override (`users-and-permissions.md` "Task money-field writes"). |
| `ServiceItem` | `template.rate_scheme.accounting_category` (via `ServiceItem.effective_accounting_category`) — still a live FK read; ServiceItem doesn't stamp |
| `Material` (PLI-linked) | `material.inventory_item.accounting_category` (copy/derivation; materials doc owns this) |
| `Material` (freeform) | direct on the material |
| `Fee` | own field, required (NOT NULL) |
| `EstimateLineItem` from atom | derived from the atom's effective AC at line-item creation; snapshot. **May be null** if the source Task itself has none — the estimate side never stamps a fallback (§10.1a); the line stays null until a human sets one. |
| `EstimateLineItem` service-line | snapshotted from `service_item.effective_accounting_category` at `add_line_item_from_service` |
| `EstimateLineItem` bare `freeform_kind='material'` hand-line | `Configuration['default_material_accounting_category']` if no explicit AC supplied (see §6.4); required if the key is absent |
| `EstimateLineItem` bare `freeform_kind='work'` hand-line | user-entered; **required at entry** (no config default) — `EstimateService.add_line_item`/`update_line_item` 400 a bare hand-line with no AC and no `adjustment_service`; carried onto the crystallized flat Task's own `accounting_category` at acceptance |
| `EstimateLineItem` bare `freeform_kind='fee'`/`NULL` hand-line | user-entered; **required at entry**, same guard as above; carried onto the crystallized `Fee` at acceptance |
| `InvoiceLineItem` from atom | derived from the atom's effective AC at compose time, **or the configured fallback** if the atom's own AC is null (§10.1a) |
| `InvoiceLineItem` via `copy_from_estimate` | copied from the estimate line's AC, **or the fallback** if the estimate line's AC is null (§10.1a) |
| `InvoiceLineItem` freeform (Add Line Item) | user-entered; **not required at entry** by `InvoiceService.add_line_item` itself (unlike the estimate side — see `docs/designs/LATER.md`); the SPA validates it client-side and the send-time gate (§10.2) blocks an uncategorized line from reaching a customer regardless |

Note the asymmetry: **hand-lines require an AC at entry only on the
estimate/CO side.** A `work`/`fee` hand-line with no explicit category
and no atom source 400s immediately; this is unchanged by task-owned-money
Phase 3 and gets no config default the way `material` hand-lines do. The
invoice side never had this entry-time requirement — it's covered by
compose-time fallback stamping and the send-time gate instead.

`ServiceItem.effective_accounting_category` exposes AC for serializers
and the wizard's pool building. Wizard single-atom line-item creation
pulls `category` from the atom's effective AC (for a Task, its own
field); multi-atom creation only sets `category` if all atoms share
one — two DIFFERENT real categories (no null atom involved) still land
on a null line-item category, untouched by the fallback (§10.1a's
fallback path only fires when the mismatch traces back to a null atom).

### 10.1a Fallback stamping at invoice compose (task-owned-money Phase 3)

The **estimate side never stamps a fallback.** A null-AC Task composed
onto an estimate line (or reached via `revise_estimate`) stays null — a
human has to set one, and the only automatic backstop on that side is
the send-time hand-line gate (§10.2), which doesn't apply to atom-backed
lines at all. So an atom-backed estimate line whose Task has no AC can
legally go out to a customer uncategorized.

The **invoice side stamps.** `InvoiceWizardService`/`InvoiceService`
override the shared wizard's `_resolve_fallback_category` hook
(`BaseWizardService`, `apps/core/wizard.py`) to read the
`fallback_accounting_category` Configuration key and apply it —
**line-local only**, never written back to the Task/Material atom —
whenever composing a line whose shared category resolves to null
*because* a contributing atom has no AC of its own.
`InvoiceService.copy_from_estimate` applies the identical fallback to
any copied line whose source estimate line has a null AC (adjustment
lines are exempt — their AC provenance is the adjustment `RateScheme`,
not a billable atom). If no fallback is configured, either path raises
a `ValidationError` naming the `fallback_accounting_category` setting
rather than silently leaving the line uncategorized.

The stamped-or-not state is exposed read-time as `used_fallback_ac` on
`InvoiceLineItem` (true iff the line's current AC equals the
*currently* configured fallback — a computed comparison, not a stored
flag) and surfaced in the wizard as an "Uncategorized → `<name>` ·
`<taxability>`" badge, correctable via the line edit modal. See
`invoicing-and-expenses.md`'s "Fallback accounting category" section
for the badge/correction/warning-banner mechanics, and
`quickbooks-integration.md` for the QBO push-time guard that backstops
this (defense-in-depth — normal operation never reaches it, since
compose-time stamping and the send-time gate both run first).

### 10.2 What changes when AC moves / send-time AC gates

Editing `RateScheme.accounting_category` is unrestricted — presets are
freely editable (§3) — but it only affects *future* stampings: a task's
own `accounting_category` was copied at creation time and never
re-reads the preset, so editing (or retiring) the preset never changes
an already-stamped task's AC.

For line items, AC is **snapshotted** at line-item creation time —
it's a field on `BaseLineItem`, not derived live. Once the estimate
is sent (out of draft), the snapshot is permanent.

**Send-time AC gates (hand-lines only).**
`EstimateService.assert_all_hand_lines_have_ac` blocks `draft → open`
while any hand-line (no atom source, not an adjustment) lacks an AC;
`ChangeOrderService.assert_all_bare_add_lines_have_ac` is the CO
parallel, gating a bare `add` line at send. Neither gate touches
atom-backed lines — see the asymmetry note in §10.1. The
`validate_data` management command mirrors the estimate-side gate as a
data-integrity check (`check_estimate_hand_line_categorization`): a
hand-line with no AC on a `draft` estimate is a WARNING (legitimately
reachable pre-send); on anything past draft it's an ERROR (the gate
should already have caught it). It has the parallel invoice-side check
(`check_invoice_line_categorization`) too, same WARN/ERROR split keyed
on `Invoice.status == draft`. It does **not** yet have an analogous
check for `ChangeOrderLineItem` bare-add lines — a pre-existing
coverage gap, tracked in `docs/designs/LATER.md`. See
`data-constraints.md` §1.13/§1.13a/§1.16 for field-level detail.

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

Top-down:

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
   with `can_manage_jobs` when transitions are allowed), action
   buttons, and a **Reconcile** / **Back to lines** toggle (§12).
4. **Field table** — estimate number, job link, version, status, dates.
5. **Line Items area** — heading, then (when `canEdit` = `canManageJobs && isDraft`)
   an actions row with a single **"Add line"** button, an **"Add Adjustment"**
   button, and a **"Show Tasks & Materials"** button that flips the panel into
   reconcile mode (§12) in place — no navigation. "Add line" opens
   `PriceListPicker` (§6.4) — one entry point for service picks, inventory
   picks, and freeform fee/material lines.
6. **Line items table** (`LineItemTable.svelte`) — line items with per-line
   **Edit** / **Delete** and reorder (move-up / move-down) when editable, plus an
   "⚠ out of sync with atoms" marker on any line whose stored price no longer
   matches its atoms' computed total. (Atom-backed lines are still pulled/edited
   via reconcile mode; hand-lines are authored directly.)

### 11.2 Action buttons

| Status | Button | Handler |
|---|---|---|
| `draft` | "Send Email" (navigation link) | navigates to `#/estimates/{id}/send` — the send-form page that calls `EstimateEmailService.send_estimate` on submit |
| `open` | "Resend Email" (navigation link) | navigates to `#/estimates/{id}/send` |
| `draft` | "Add line" | opens `PriceListPicker` → `EstimateAddLineForm` (§6.4) — unified entry for service, inventory, and freeform (fee or material) lines |
| `draft` | "Add Adjustment" | opens `AdjustmentModal` (percentage `RateScheme`) |
| `draft` | "Show Tasks & Materials" / "Reconcile" | flips `EstimatePanel`'s local `mode` to `'reconcile'` — same route, same panel, no navigation (pulls the job's atoms into atom-backed lines; §12) |
| `open` | "Revise Estimate" | `POST /api/estimates/{id}/revise/` → opens new draft revision |
| any | status `<select>` | `PATCH /api/estimates/{id}/` with `{status}` (when transitions are valid) |

Editing rules: `canEdit = canManageJobs && status === 'draft'`.

### 11.3 Line item authoring — estimate vs invoice

**Estimate.** The estimate detail page authors line items via the unified
**"Add line"** button (§6.4, §11.2). A single `PriceListPicker` → `EstimateAddLineForm`
flow replaces the former separate "Add Line Item" and "Add from Service" buttons.
`AddServiceItemModal.svelte` has been deleted; the estimate detail no longer
creates a Task immediately on service pick — the Task is deferred to acceptance.
Per-line **Edit** / **Delete** and reorder remain; atom-backed lines still show an
"⚠ out of sync with atoms" marker and are pulled/edited via the wizard.
`POST /api/estimates/{id}/line-items/` (hand-lines) and
`POST /api/estimates/{id}/line-items-from-service/` (service lines) are the two
create endpoints; GET list, per-line `PATCH`/`DELETE`, reorder, and
`POST .../adjustment-lines/` are unchanged.

**Invoice.** `LineItemModal.svelte` is still used by the **invoice** detail
page for direct (no-atom) line authoring — a toggle between **manual entry**
and **"From Price List"** (catalog mode: pick an `InventoryItem`; the server
copies `description`, `units`, `selling_price`, `accounting_category`). Editing
an existing line shows fields only. Bringing the invoice onto the same
atoms-only projection is a deferred consolidation pass.

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

## 12. UI: Estimate Wizard (reconcile mode)

The "wizard" is no longer a separate route — it's **reconcile mode**,
one of two view modes (`'lines'` | `'reconcile'`) that `EstimatePanel`
(§11) toggles in place, both rendered at the same
`#/jobs/:jobId/estimate/:docId` URL, same job load, no remount. In
reconcile mode the panel renders the shared
`ReconcileMode.svelte` (`frontend/src/components/wizards/`) —
parameterized per `docType` (`'estimate'` | `'invoice'`; the invoice
side is structurally identical, see `invoicing-and-expenses.md`) — in
place of the line-items view. The former standalone
`EstimateWizardPage.svelte` is gone; the old route
`#/estimates/:id/wizard` is now a redirect shim
(`EstimateWizardRedirect.svelte`) that remembers `'reconcile'` mode for
that document (`rememberMode`, `stores/jobWorkspace.js`) and bounces to
the job-scoped URL, so old bookmarks land back in reconcile mode.

**Mode persistence and validation.** Which mode a document was left in
is remembered per document id (`stores/jobWorkspace.js`, keyed by
`docId` — not by section, so leaving invoice #22 in reconcile can't
leak into invoice #23). Restoring a remembered `'reconcile'` mode is
**validated against the estimate's live status**: reconcile is only
offered while the document is still an editable `draft`, so an estimate
sent/accepted/superseded since the mode was last remembered falls back
to `'lines'` instead of resurrecting an edit surface on a closed
document.

### 12.1 Flow

Two columns, unchanged from the former wizard page's behavior:

- **Source pool** (left) — `WizardSourcePool` shows every Task and
  Material on the **Job**. Each atom is clickable (checkbox-style) when
  `available`; locked-out otherwise with a "claimed by …" indicator. The
  component binds `selectedAtoms`.
- **Line items** (right) — list of `WizardLineItemCard`s for the
  current estimate, each with its source rows expanded. Each card
  has an "Add Here" button (enabled when atoms are selected) that
  appends the selected atoms via `add-atoms`. A trailing "New line
  item" placeholder card has its own "Add Here" that calls
  `line-items-from-atoms`. Estimates don't offer a manual-line button
  here (`hasManualLine: false` in `ReconcileMode`'s per-doc-type
  config) — hand lines are added from the lines view's "Add line".

After every action, `ReconcileMode` re-fetches the estimate + line
items, then **reconciles** atom states client-side from the new
claims map without re-fetching the source pool. `claimed_by_other`
atoms (snapshotted at mount) are left alone.

### 12.2 Bottom actions

`WizardActions` provides:

- **Discard draft** — `DELETE /api/estimates/{id}/?confirm=true` (sends
  the confirm token to the discard-draft path on `EstimateService.discard_draft`).
- **Done** — flips the panel back to `'lines'` mode at the same URL
  (`onExit`, no navigation); flushed pending edits first
  (`flushRegistry.flushAll()`).

### 12.3 Reconcile-mode entry

The estimate is reached from the rail's Estimates link (§11): "Start
Estimate" creates the draft estimate directly on the job
(`POST /api/estimates/` with `{job}`), landing on
`#/jobs/:jobId/estimate/:newId`. "Show Tasks & Materials" / "Reconcile"
(on the estimate panel, §11.2) flips that same page into reconcile
mode. There is no longer a worksheet page, a worksheet-side wizard
entry, or a separate wizard route.

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
| `estimate_accepted` | any→accepted | acceptance receiver | calls `EstimateAcceptanceService.on_accept(estimate)` — crystallizes hand-lines into Tasks/Materials/Fees via the four-way discriminator and earmarks the job (§9) |

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
  exactly parallel to estimate acceptance (§9): an `add` line becomes a
  Task / Material / Fee, a `remove` retires the target line's atom, a
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
| `freeform_kind` | Nullable CharField, choices `work` \| `material` \| `fee` — mirrors `EstimateLineItem.freeform_kind` (§6.1). Set **iff** the line is bare (no `inventory_item`/`service_item`); required on an `action='add'` line at entry (not on `replace`/`remove`, which mirror the target atom or retire it). At CO acceptance: `material` → established Material (reverse-markup placeholder cost, `cost_source='estimated'`, `default_material_accounting_category` config default applied at authoring); `work` → a flat Task; `fee`/`NULL` → a Fee. Immutable after creation, same rule as the estimate side. |

`clean()` also rejects `service_item` or `freeform_kind='material'` on a
`remove` line (its own fields are display-only; it never crystallizes
anything — `freeform_kind='work'`/`'fee'` aren't separately blocked
there, but a remove line's descriptor fields are never read regardless,
so this is inert either way).

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
`assert_all_hand_lines_have_ac` (§5.1/§15). Such a line crystallizes
into a Task, Material, or Fee at acceptance (per `freeform_kind`), and
the category must be pinned *before* the customer can say yes, so
acceptance can never fail on it. The check is
`ChangeOrderService.assert_all_bare_add_lines_have_ac`
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
(`source_type ∈ {task, material, fee}` + `source_pk`, unique together)
from a CO line to the atom it **crystallized** at acceptance. It is the
provenance record (compose_agreement traces crystallized CO fees so the
invoice claims them exactly once — §14.6) and the idempotency marker (a
line with a source row is already crystallized). `resolve()` returns the
concrete atom. Unlike the estimate table, rows exist only for
add/replace lines of **accepted** COs — authoring never creates one.

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

Every line also carries `source_fee_id` — the pk of the Fee the line
crystallized into, when it did: for estimate-origin lines that's the
hand-line fee provenance (`EstimateLineItemSource`, §9.1), and for
CO-origin add/replace lines the `ChangeOrderLineItemSource` fee row
written at CO acceptance (§14.11). Both are bulk-prefetched.
`InvoiceService.copy_from_estimate` claims each `source_fee_id` with an
`InvoiceLineItemSource` so the wizard pool marks the Fee as billed and
double-billing is impossible — the agreement stays the **billing**
source of truth; the crystallized atoms are the *work* mirror, and the
source rows are what keep the two views counting each Fee once.

This function is the single source of truth for what the customer owes.
The Invoice wizard reads it; PDF rendering of the agreement reads it;
the Estimate-detail page surfaces the composed view alongside the
underlying Estimate.

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
`ChangeOrderDetailPage` route) is the CO edit view. It renders a merged
baseline-vs-proposal diff using the CO's line items and the
`deliverables-baseline` endpoint: `lib/changeOrderDiff.js` derives the
rows (unit-tested), `CODeliverablesSection.svelte` owns the deliverables
grid + inline drafting forms, and `COLineItemsSection.svelte` renders the
line diff with actions as callbacks to the panel.
**"+ New line"** opens the unified `PriceListPicker` (§6.4) — the same
service / inventory / freeform (Work / Material / Fee-Credit buttons)
entry point as the estimate detail page — followed by
`COAddLineForm.svelte` (`components/changeorders/`), which posts a
service pick to `line-items-from-service/`, an inventory pick to
`line-items/` (the from-pli path, `action: 'add'`), and a freeform line
with `action: 'add'` + AC + `freeform_kind` (never the retired
`is_material`; see §6.4 for the kind-specific subforms).
`COLineItemModal.svelte` remains the editor for existing lines and the
Change/replace flow; on `add`-action lines it carries an Accounting
Category select (required unless the line's immutable `freeform_kind`
is `'material'`, config-defaulted there — the send guard's authoring
face) and displays that `freeform_kind` read-only (no editor — kind is
immutable after creation). The Estimate detail page shows accepted COs
as pills/badges in the deliverables and line-items sections.

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

- **add** — crystallize via the same discriminator as estimate acceptance
  (§9.1): `service_item` → Task
  (`generate_task(allow_inactive_scheme=True)`; name from the
  ServiceItem, description from the line), `inventory_item` → Material
  (line price = sell price), `freeform_kind='material'` bare →
  established Material via `MaterialService.establish_reverse_markup`
  (parity with §9.1 — cost backed out of the locked sell,
  `cost_source='estimated'`; a bare replace whose mirrored atom was
  provisional is likewise established), `freeform_kind='work'` bare →
  a **flat Task** (`work_tasks_created`; same shape as §9.1's — entered
  qty, `source_scheme=None`, defensive negative-price guard, and
  `JobService.mark_work_reopened(job)`), else → Fee (defensive
  ValidationError if no AC — normally unreachable past the send guard).
  Write a `ChangeOrderLineItemSource` row.
- **remove** — resolve the target estimate line to its **current** atom
  and retire it. The discriminator for a Task target is the **claiming
  line's own `freeform_kind`** (`_current_atoms`' `claiming_kind` — the
  `EstimateLineItem`/`ChangeOrderLineItem` whose source row currently
  resolves to this atom), not any field on the Task itself: neither
  `service_item_id` nor `source_scheme` reliably marks a flat work task
  apart from an ad-hoc or bare-CO-mirrored one (see below), so retire
  can't discriminate on the atom.
  - *Task, claiming line's `freeform_kind='work'`* (a flat work task,
    crystallized straight from a bare work hand-line): **deleted**, not
    cancelled — re-applying `TaskService.delete_task`'s guards (no
    bleps, not in-progress/complete, no consumed materials) as
    `ValidationError`s that tell the caller to cancel instead; a live
    invoice claim is left alone (skip, like the Fee branch). This
    mirrors retiring a Fee (delete) rather than a normal Task (cancel)
    — a flat work task never carried a catalog/scheduling promise.
    Counted in `work_tasks_removed`.
  - *Task, any other claiming kind* (service-generated, ad-hoc, or a
    bare-CO-replace's mirrored task — see the replace note below):
    `TaskLifecycleService.cancel_task` — **bleps are preserved**;
    already complete/cancelled tasks are left alone. Counted in
    `tasks_cancelled`.
  - *Material*: **released** (`MaterialService.release` — earmark backed
    out, quantity moved to `released_qty`, state → `released`, claims
    kept as job history), but **only if** pending, not expense-bound,
    not PO-linked, and not on a live invoice — physical or billed
    reality is never unwound by a document; those are left for the
    human to reconcile. Counted in `materials_removed`.
  - *Fee*: deleted unless on a live invoice (its estimate-line claim is
    purged; the CO line remains the record of the removal — a Fee
    `retired` state is deferred to a future fixed-price pass; Fee no
    longer has a `task` link at all as of 2026-08-03). Counted in
    `fees_removed`.
  - A document-only target (adjustment line, or an atom already
    retired) is a no-op — the delta stays document-only, matching
    `compose_agreement`.

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
  (service/inventory/`freeform_kind`) crystallizes per that descriptor
  — including `freeform_kind='work'`, which mints a fresh flat Task
  exactly like an `add` line does; a **bare** replace line (no
  descriptor at all) instead mirrors the retired atom's type — a Task
  target yields a new pending Task with the same name / rate scheme /
  modifiers / sort order / assignee (`TaskBase.copy_fields`) at the CO
  line's qty and description; a Material target a new Material on the
  same inventory item (AC/units inherited when the line omits them); a
  Fee target a new Fee (AC inherited from the old fee if absent on the
  line).

  **A bare replace mirroring a derived-price parent snapshots its
  rate** (final-review finding I2). When the mirrored Task is a **parent**
  (`is_parent`) with its own `rate` `None` — priced via
  `derived_unit_price()`, `jobs-and-tasks.md` §4a.3 — `copy_fields()`
  alone would carry that `None` verbatim, and the replacement (a fresh,
  childless Task) has no children to derive from: it would silently
  price at `0.00`. `_mirror_of` snapshots the LIVE `derived_unit_price()`
  into the copied `rate` at mirror-build time (before the old parent is
  retired), so the replacement bills at the same effective rate the
  retiring structure was actually charging.

  **A bare replace mirroring a flat work Task "promotes" it.** The new
  Task is claimed by the *bare* replace line, whose own `freeform_kind`
  is `NULL` — so a later remove/replace targeting *this* replacement
  atom sees `claiming_kind=None` and cancels it (§ above), even though
  its shape (entered qty, `source_scheme=None`) still looks exactly
  like a flat work task. `TaskBase.copy_fields()` deliberately excludes
  `source_scheme` as pure provenance, so this isn't visible on the atom
  either way — only the claiming line's `freeform_kind`, which the bare
  replace never carries, decides it. This is intentional: a bare
  replace is a generic "keep what's there, change the numbers" edit,
  not a re-authored work hand-line.

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

`on_accept` returns `{'tasks_created', 'materials_created', 'fees_created',
'work_tasks_created', 'tasks_cancelled', 'materials_removed',
'fees_removed', 'work_tasks_removed'}` — the created/cancelled/removed
split for work tasks is separate from the ordinary Task counters for the
same reason as §9's `work_tasks_created`: they crystallize/retire
through different branches.

**Idempotency** mirrors §9.2: crystallized lines carry a source row and
are skipped on re-run; retirement re-checks atom state (a cancelled
task, a deleted material) before acting.

**Billing stays with the agreement.** Crystallization never creates
billing lines; §14.6's `source_fee_id` plumbing is what keeps the
document and atom views counting each crystallized Fee once. Bleps on a
task cancelled by a remove/replace stay on record under the cancelled
task (the invoice wizard's complete-task gate applies as usual — the
cancelled work's time is reconciled by the human at invoicing).

Returns `{'tasks_created', 'materials_created', 'fees_created',
'tasks_cancelled', 'materials_removed', 'fees_removed'}`. Tests:
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

- **Review `EstimateAcceptanceService.on_accept` in detail.** The current
  behaviour is documented in §9 — crystallize each hand-line into a `Fee`
  (recording a `fee` source link), then earmark the job. Review against
  real estimate-accept scenarios and revise if needed.

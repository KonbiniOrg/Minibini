# Estimates and Billing

Reference for the estimating side of Minibini: `RateScheme` as the
unit of billing identity, supersession, the billable-atom abstraction,
the estimate wizard, the job-atom projection (documents-as-lenses),
acceptance crystallizing hand-lines into atoms (Materials or Fees), and AC pass-through.
Read alongside:

- `docs/designs/architecture-and-conventions.md` — service-layer
  pattern, `LineItemMixin`, exception hierarchy
  (`ServiceError` / `NotFoundError` / `SchemeSupersededError`).
- `docs/designs/jobs-tasks-and-worksheets.md` — `Task`, `Material`,
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

- `RateScheme` model, modifier algebra, supersession lineage.
- Billing identity on `Task` / `ServiceItem` (the FK to `RateScheme` and
  the `active_modifiers` / `est_qty` / `actual_qty` semantics).
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
It owns the math (rate, algorithm, modifiers), the `AccountingCategory`
(and therefore taxability / QBO income mapping), and its own version
lineage. Every `Task` and `ServiceItem` references exactly one
`RateScheme` and inherits the rest. (Fixed one-off charges are the `Fee`
atom — see §4.5 — not a RateScheme.)

### 2.1 Identity fields

| Field | Type | Notes |
|---|---|---|
| `rate_scheme_id` | AutoField PK | |
| `name` | CharField(100), unique | display name; e.g. "CNC Router", "Hourly Labor", "Tap a hole" |
| `description` | TextField, blank | longer admin explanation |
| `algorithm` | CharField(20), choices | one of `elapsed_time`, `entered_qty`, `percentage` |
| `rate` | Decimal(10,2) | the per-unit price for `elapsed_time`/`entered_qty`; holds the percent value for `percentage` (negative = discount) |
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
`Services` manager in the settings UI still displays percentage types so they
can be managed; the task-creation pickers never show them.

`rate` holds the **percent value**: `10` means 10%, `-5` means a 5% discount.
Negative rates are allowed only for `percentage` services (all other
algorithms must have `rate >= 0`, enforced by `RateScheme.clean()` and
`validate_data.py`).

**`compute_adjustment_amount`** (`apps/core/adjustments.py`) is the helper
that resolves a percentage line's dollar amount at the document layer:

```python
compute_adjustment_amount(adjustment_line, sibling_lines) → Decimal
```

1. Reads `service.rate` (the percent) and the line's
   `adjustment_target_categories` M2M set.
2. Sums `total_amount` (`qty × price`) of every **non-adjustment** sibling
   line whose `accounting_category_id` is in the target set. An **empty**
   target set matches **all** non-adjustment siblings.
3. Adjustment lines are explicitly skipped — no stacking: an adjustment
   never sums other adjustments.
4. Result: `(rate / 100) × base_total`, quantized to `Decimal('0.01')`
   (nearest cent).

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

- `key`: stable identifier; recorded in `Task.active_modifiers` (and
  `ServiceItem.default_active_modifiers`).
- `label`: display string shown in checkboxes and on the line item.
- `percent`: additive percent surcharge over the base rate.

Active modifiers stack additively: messy (+10%) + doublestick (+5%)
= +15% on `rate`. Validation that `active_modifiers` keys are a subset
of the scheme's modifier keys is up to the form/serializer layer.

**`active_modifiers` is always a list.** `active_modifiers` on `Task`,
and `default_active_modifiers` on `ServiceItem`, are always a **list** of
modifier keys — never a dict. The `copy_active_modifiers()` helper
(`apps/jobs/models.py`) returns a list copy; legacy dict values (e.g. an
old `{'flat_fee_price': …}` encoding) collapse to `[]`.

### 2.4 Effective rate and compute

```python
RateScheme.effective_rate(active_modifiers)
    elapsed_time / entered_qty
        → rate * (1 + sum(m.percent for m in modifiers if m.key in active_modifiers) / 100)
    percentage
        → raises ValueError (computes at the document layer, not per-unit)

RateScheme.compute_charge(qty, active_modifiers)
    → qty * effective_rate(active_modifiers)
```

There is no minimum-charge floor on RateScheme — that field was
removed.

### 2.5 Reference checks

`RateScheme.is_referenced()` returns `True` if any `Task` or
`ServiceItem` points at this service price.

`RateScheme.reference_counts()` returns:

```python
{
    'task_count':          Task.objects.filter(rate_scheme=self).count(),
    'service_item_count': ServiceItem.objects.filter(rate_scheme=self).count(),
}
```

Used by both the edit-in-use guard and the outdated-schemes UI.

---

## 3. Supersession

Once any work item references a `RateScheme`, the service price is
**frozen** in place. To change rate / modifiers / AC after that, the user
**supersedes** the entry — creates a new row, leaves the old one
intact, and links them via `replaced_by` / `replaced_at`. Existing
work items keep pointing at the old entry; future picks pull from
active (non-superseded) entries.

### 3.1 Frozen fields

`RateScheme.FROZEN_FIELDS`:

```python
('name', 'description', 'algorithm', 'rate', 'unit_label',
 'modifiers', 'accounting_category')
```

`RateScheme.clean()` rejects any change to these fields when
`is_referenced()` is true. The only allowed mutations on a frozen
entry are `replaced_by` and `replaced_at` (and the `name` rename
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
`Task` / `ServiceItem` rows always keep their FK to the entry they were
created with — no migration of historical references on supersede, ever.
That's how billing history is preserved.

`supersede()` raises `ValueError` if the entry is already superseded.

### 3.3 API

| Verb + path | Behavior |
|---|---|
| `GET /api/rate-schemes/` | List active entries (`replaced_by IS NULL`) |
| `GET /api/rate-schemes/?include_superseded=true` | List all entries |
| `GET /api/rate-schemes/?only_superseded=true` | List just superseded |
| `GET /api/rate-schemes/{id}/` | Retrieve any entry (active or superseded) |
| `POST /api/rate-schemes/` | Create — `CanManageConfig` |
| `PUT/PATCH /api/rate-schemes/{id}/` | Edit — **HTTP 409** if referenced (see below) |
| `POST /api/rate-schemes/{id}/supersede/` | Create new version, set `replaced_by`/`replaced_at` on the old row — `CanManageConfig` |
| `DELETE /api/rate-schemes/{id}/` | Delete — possible only for never-referenced entries (PROTECT cascade) |

Permissions: read is `IsAuthenticated`; all write actions require
`CanManageConfig`.

The serializer exposes `superseded` (computed bool:
`replaced_by_id is not None`) and `reference_counts` for the
outdated-schemes UI. `unit_label` is validated against the configured
units list (`apps/core/units.get_units_list`).

### 3.4 Edit-in-use block

`PUT/PATCH` against a referenced entry returns **HTTP 409 Conflict**:

```json
{
    "detail": "Scheme is referenced; create a new version instead of editing.",
    "supersede_url": "https://.../api/rate-schemes/{id}/supersede/",
    "reference_counts": {
        "task_count":          12,
        "service_item_count": 1
    }
}
```

The frontend uses this to surface "Create new version" affordances
and explain *why* an edit was blocked.

### 3.5 Template guard

When `ServiceItem.generate_task(container, est_qty, ...)` runs, it
checks `template.rate_scheme.replaced_by_id is None`. If the template
points at a superseded entry, it raises `SchemeSupersededError`
(`apps/core/services.py`), which the API translates to **HTTP 409
Conflict** with a message identifying the template:

> Template "Hourly Labor — assembly" references a superseded
> RateScheme. Update the template before adding tasks from it.

The same guard fires on `TaskService.create_from_template`.

The shop owner is forced to deliberately decide whether the template
should adopt a new entry or pick a different one. Silent retroactive
change to template behavior is never acceptable.

### 3.6 Picker filtering

All service-price pickers default to active entries only. The
frontend gets this for free from the `GET /api/rate-schemes/`
default filter; passing `?include_superseded=true` reveals the full
set for the outdated-schemes view.

### 3.7 PROTECT cascade

`replaced_by`, `Task.rate_scheme`, and `ServiceItem.rate_scheme` all use
`on_delete=PROTECT`. An entry that
has entered the lineage is effectively un-deletable — orphaning a
work item or breaking the supersession chain is structurally
impossible.

---

## 4. Task billing (and the Fee atom)

`Task` carries billing identity directly via `TaskBase` (the abstract
base in `apps/jobs/models.py`). The full field shape lives in
`docs/designs/jobs-tasks-and-worksheets.md`. Recap of the billing fields:

| Field | On TaskBase / Task | Notes |
|---|---|---|
| `rate_scheme` | declared on Task | FK to `RateScheme` (PROTECT). NOT NULL at the DB level. |
| `active_modifiers` | declared on Task | JSON list of modifier keys (always a list, never a dict — see §2.3) |
| `est_qty` | inherited from `TaskBase` | nullable on Task |
| `est_worker_time` | inherited from `TaskBase` | DurationField for scheduling |
| `actual_qty` | declared on Task only | Decimal nullable; worker-entered for `entered_qty` schemes |

### 4.1 compute_amount, compute_estimate_amount, effective_rate

`Task` implements the uniform atom interface
`compute_amount(active_modifiers=None) → Decimal` (the **invoice** view —
bills actuals) plus a parallel `compute_estimate_amount()` (the
**estimate** view — bills `est_qty`):

```python
class Task:
    def compute_amount(self, active_modifiers=None):
        # Invoice side: qty from actuals (bleps / actual_qty).
        qty = self.rate_scheme.get_actual_qty(self)  # algorithm-aware
        charge = self.rate_scheme.compute_charge(qty, self.active_modifiers)
        return charge.quantize(Decimal('0.01'))

    def compute_estimate_amount(self, active_modifiers=None):
        # Estimate side: qty is est_qty (what the job is *expected* to cost).
        charge = self.rate_scheme.compute_charge(
            self.est_qty or Decimal('0'), self.active_modifiers,
        )
        return charge.quantize(Decimal('0.01'))
```

This is the crux of **documents-as-lenses** (§7): the *estimate* projects
`est_qty` via `compute_estimate_amount`; the *invoice* bills the locked
`actual_qty` of a complete task via `compute_amount`. Both are quantized
to cents: `compute_charge` is `qty * effective_rate`, and a
modifier-adjusted rate can carry more than 2 decimals.

The `active_modifiers` parameter is accepted to match the atom interface
but is ignored — both use `self.active_modifiers`. `compute_amount` uses
the algorithm to resolve qty:

| Algorithm | Task.compute_amount qty source |
|---|---|
| `elapsed_time` | sum of Blep durations in hours |
| `entered_qty` | `task.actual_qty or 0` |

`effective_rate()` returns `rate_scheme.effective_rate(self.active_modifiers)`.

`RateScheme.effective_rate()` for `elapsed_time` / `entered_qty`
quantizes to 2 decimal places (cents): a percentage modifier divides by
100, so `rate × (1 + percent/100)` can carry more than 2 places (e.g.
`99.99 × 1.05 = 104.9895`). The per-unit rate is a money value that is
copied straight onto a line item's `price` field (a 2-decimal
`DecimalField`), so it must be trimmed at the source — every caller that
uses it as a price (the estimate wizard's single-atom and "send all
atoms" paths, the bundle summary, the source-pool detail) is then safe
without having to remember its own `.quantize()`.

### 4.2 actual_qty semantics

| Algorithm | `Task.actual_qty` meaning |
|---|---|
| `elapsed_time` | unused; should stay `None` (qty derived from Bleps) |
| `entered_qty` | what the worker entered; `None` until entered |

The "Actual qty" input on `TaskDetailPage` writes `actual_qty`; only
visible for `entered_qty` schemes.

### 4.3 est_qty semantics

| Algorithm | `est_qty` meaning |
|---|---|
| `elapsed_time` | estimated billable hours (often equals `est_worker_time` but doesn't have to) |
| `entered_qty` | estimated piece / minute count |

`est_qty` is **never** modified by work activity. It stays as the
estimate (and drives `compute_estimate_amount`). `actual_qty` and Bleps
capture what happened (and drive `compute_amount`). This separation
enables estimate-vs-actuals reporting (not yet built; see §16).

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
| `task` | OneToOne → Task (SET_NULL, nullable) | optional link to the work behind the charge |
| `description` | CharField(255), blank | |
| `quantity` | Decimal(10,2), default `1.00` | |
| `unit_rate` | Decimal(10,2) | **required** |
| `accounting_category` | FK → AccountingCategory (PROTECT) | **required, NOT NULL** |
| `sort_order` | PositiveInteger, default 0 | |

`Fee.compute_amount() → (quantity × unit_rate).quantize('0.01')`;
`effective_accounting_category` returns its own `accounting_category`;
`units` is `'none'`. A Fee has no lifecycle and no actuals — it is
**always billable** (unlike a Task, which must be `complete`, or a
Material, which must be `consumed`). Writes go through `FeeService`
(`apps/jobs/services.py`) — `create_on_job` / `update` / `delete`, all
respecting the job's on-hold guard — and the API at
`POST /api/jobs/{id}/fees/`.

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
   `jobs-tasks-and-worksheets.md` §12.9 (trigger 1 + portal read rule).

The `unique_together = ['estimate_number', 'version']` constraint
keeps revisions distinct.

### 5.3a Adjustment lines and `revise_estimate`

`revise_estimate` preserves adjustment lines exactly like normal lines:
`adjustment_service_id` and the `adjustment_target_categories` M2M set are
both copied onto the new revision's line items. The revision's adjustment line
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
`is_adjustment` (bool), `adjustment_service_id`, `percent` (the rate, or
`None` for non-adjustment lines), and `target_category_ids` for
estimate-origin lines. CO-origin lines always have falsey adjustment fields
(adjustments are estimate-only).

### 5.4 Document numbering

One estimate tree per job, so the estimate's identity *is* the job's: the
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

---

## 6. EstimateLineItem and EstimateLineItemSource

### 6.1 EstimateLineItem

Inherits `BaseLineItem` (description, qty, units, price, line_number,
accounting_category, taxable_override, tax_rate_override; see
`apps/core/models.py`). Declared in `apps/estimates/models.py`,
`db_table = 'est_li'`. Adds:

- `estimate` — FK to `Estimate` (CASCADE).
- `adjustment_service` — nullable FK to `RateScheme` (PROTECT). Set
  when this line is a percentage adjustment. A line with
  `adjustment_service_id` set is an **adjustment line**; one without is
  a normal line.
- `adjustment_target_categories` — M2M to `AccountingCategory`. The
  categories whose lines this adjustment applies to. Empty = all
  non-adjustment lines.

The serializer exposes a read-only `adjustment_service_detail` dict
`{name, rate, algorithm}` for display purposes when `adjustment_service`
is set.

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
estimate line item.

`source.resolve()` returns the concrete atom instance (`Task`,
`Material`, or `Fee`).

CASCADE on `EstimateLineItem` deletion: deleting a line item releases
its claims. On revision, `revise_estimate` **moves** the source rows onto
the new line items (§5.3), so the live estimate is always the one lens
over the atoms; superseding/rejecting/expiring otherwise does not touch
claims.

### 6.3 Atom-to-line-item shapes

| Source rows on a line item | What it represents |
|---|---|
| 0 | A **hand-line** — manually authored, no atom backs it (crystallizes on acceptance into a `Material` if it has an `inventory_item`, else a `Fee` — §9) |
| 1 | Single-atom conversion (bulk send-all or a wizard pick of one atom) |
| N | Wizard-grouped from multiple atoms |

A single-atom line item copies the atom's description, units, qty,
and price across. Multi-atom line items: when every atom is a task
sharing one `RateScheme` and identical `active_modifiers`, the line is
**summarized** — `units` from the service price, `qty` = summed
quantities (`est_qty` on the estimate side, actuals on the invoice side),
`price` = the common effective rate. Any other multi-atom bundle (a
material or fee atom present, mixed service prices, or mixed modifiers)
falls back to blank description, `units = 'none'`, `qty = 1`,
`price = sum(compute_amount)`.

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
| `get_source_pool(estimate)` | Walks the estimate's **Job's** Tasks and Materials, returns a flat pool of atoms. Each atom carries `type` (`'task'`/`'material'`), `id`, `description`, the `qty`/`rate`/`units`/`amount` breakdown, `category_id`, and claim state: `available`, `claimed_by_current` (this estimate), `claimed_by_other` (a different estimate on the same job). Task amounts use `compute_estimate_amount` (`est_qty`). |
| `add_atoms_to_new_line_item(estimate, atoms)` | Creates a new `EstimateLineItem` with a source row per atom. Single-atom case copies atom's description/units/qty/price; multi-atom case summarizes a uniform same-scheme task bundle, else falls back to blanks (see §6.3). |
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
| `EstimateWizardPage.svelte` | `frontend/src/routes/estimates/` | Page shell. Two-column layout (source pool left, line items right). Loads estimate + line-items + source-pool on mount; `reloadAfterAction` refreshes line items and reconciles atom states locally |
| `WizardSourcePool.svelte` | `frontend/src/components/estimates/` | Renders the flat atom list; binds `selectedAtoms` to the page. Each atom is a `WizardAtomRow`. The invoice wizard has its own task-grouped `WizardSourcePool.svelte` that reuses the same row. |
| `WizardAtomRow.svelte` | `frontend/src/components/wizards/` | One source-pool atom row, shared by both wizards: checkbox + `description — qty units × $rate = $total` + claim state |
| `WizardLineItemCard.svelte` | `frontend/src/components/wizards/` | One line-item card with its source rows; surfaces "Add Here" and per-source remove |
| `WizardActions.svelte` | `frontend/src/components/wizards/` | Bottom action bar (Discard draft, Return to estimate detail) |
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
price of a hand-authored line becomes a real, billable job atom.

### 9.1 What `on_accept` does

In one `transaction.atomic()` block:

1. For each `EstimateLineItem` on the accepted estimate that has **no
   source row** (a hand-line) and is **not** a percentage adjustment
   (`adjustment_service_id is None`), crystallize it by type:
   - **Catalog material** (`inventory_item_id is not None`, i.e. added via
     "From Inventory") → create a `Material` via
     `MaterialService.create_on_job` carrying `description`, `quantity =
     li.qty`, `sell_price = li.price` (the estimate's quoted price; the
     PLI supplies `unit_cost` via `_populate_from_pli`), the
     `inventory_item`, and `accounting_category`. Record an
     `EstimateLineItemSource` with `source_type='material'`.
   - **Otherwise** → create a `Fee`: `description`, `quantity = li.qty or
     1`, `unit_rate = li.price or 0`, `accounting_category`, `sort_order =
     li.line_number or 0`. Record an `EstimateLineItemSource` with
     `source_type='fee'`.
   Either way the line becomes atom-backed, so `copy_from_estimate`
   (invoice side) can trace which hand-line maps to which atom and claim
   it. (A hand-*typed* material with no `inventory_item` has no signal and
   still becomes a Fee — see `docs/designs/LATER.md`.)
2. Atom-backed lines (those that already have an `EstimateLineItemSource`
   for a Task / Material) are skipped — their atoms are already on the
   job. Adjustment lines stay document-only (they recompute against the
   live lines and never become Fees).
3. Call `InventoryService.create_earmarks_for_job(job)`, so accepting an
   estimate earmarks the job's inventoried materials (including any just
   crystallized from catalog hand-lines).

`on_accept` returns `{'fees_created': int, 'materials_created': int}`.

### 9.2 Idempotency

Because each crystallized hand-line gets a `fee` source row, re-firing
acceptance would find those lines already source-backed and skip them —
the same guard that protects atom-backed lines. The earmark step is an
absolute aggregate sweep, so it is idempotent on re-run too.

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

Pointer: `docs/designs/jobs-tasks-and-worksheets.md` §13 for the full
receiver-by-receiver behavior.

---

## 10. AccountingCategory pass-through

`AccountingCategory` (`apps/core/models.py`) is required on
`RateScheme` (NOT NULL). Every billable concept either references a
`RateScheme` (and inherits AC) or carries AC directly (Materials with
no PLI; Expenses).

### 10.1 Where AC comes from

| Object | AC source |
|---|---|
| `RateScheme` | own field, required |
| `Task` | `task.rate_scheme.accounting_category` (via `Task.effective_accounting_category`) |
| `ServiceItem` | `template.rate_scheme.accounting_category` (via `ServiceItem.effective_accounting_category`) |
| `Material` (PLI-linked) | `material.inventory_item.accounting_category` (copy/derivation; materials doc owns this) |
| `Material` (freeform) | direct on the material |
| `Fee` | own field, required (NOT NULL) |
| `EstimateLineItem` from atom | derived from the atom's effective AC at line-item creation; snapshot |
| `EstimateLineItem` hand-line | user-entered (carried onto the crystallized `Fee` on acceptance) |

Each model that has an `effective_accounting_category` property
exposes it for serializers and the wizard's pool building. Wizard
single-atom line-item creation pulls `category` from the atom's
effective AC; multi-atom creation only sets `category` if all atoms
share one.

### 10.2 What changes when AC moves

`RateScheme.accounting_category` is in `FROZEN_FIELDS`. Once the
entry is referenced, AC change requires supersession. Existing tasks
that referenced the old entry keep the old AC; future tasks pick the
new entry and get the new AC.

For line items, AC is **snapshotted** at line-item creation time —
it's a field on `BaseLineItem`, not derived live. Once the estimate
is sent (out of draft), the snapshot is permanent.

---

## 11. UI: Estimate Detail page

Route: `#/estimates/:id` → `EstimateDetailPage.svelte`
(`frontend/src/routes/estimates/`).

### 11.1 Layout

Top-down:

1. **JobHeader** — same component used on the Job detail page, and
   shared with the atom-pull (wizard) page.
2. **Toolbar** — back link, page title (with `superseded` styling
   when applicable), status pill (interactive `<select>` for users
   with `can_manage_jobs` when transitions are allowed), action
   buttons.
3. **Field table** — estimate number, job link, version, status, dates.
4. **Line Items area** — heading, then (when `canEdit` = `canManageJobs && isDraft`)
   an actions row with **"Add Line Item"**, **"Add from Service"**, and
   **"Add Adjustment"** buttons plus a **"Show Tasks & Materials"** link to the
   wizard at `#/estimates/{id}/wizard`. Direct authoring is back (the Phase-6
   projection-only stance was reversed): lines can be hand-authored/edited on the
   detail page, or atom-backed (pulled from the job's atoms via the wizard, or
   created by "Add from Service").
5. **Line items table** (`LineItemTable.svelte`) — line items with per-line
   **Edit** / **Delete** and reorder (move-up / move-down) when editable, plus an
   "⚠ out of sync with atoms" marker on any line whose stored price no longer
   matches its atoms' computed total. (Atom-backed lines are still pulled/edited
   via the wizard; hand-lines are authored directly.)

### 11.2 Action buttons

| Status | Button | Handler |
|---|---|---|
| `draft` | "Send Email" (navigation link) | navigates to `#/estimates/{id}/send` — the send-form page that calls `EstimateEmailService.send_estimate` on submit |
| `open` | "Resend Email" (navigation link) | navigates to `#/estimates/{id}/send` |
| `draft` | "Add Line Item" | opens `LineItemModal` (manual or catalog) — direct hand-line/PLI authoring |
| `draft` | "Add from Service" | opens `AddServiceItemModal` — pick a `ServiceItem` → creates a Task on the Job + an atom-backed line |
| `draft` | "Add Adjustment" | opens `AdjustmentModal` (percentage `RateScheme`) |
| `draft` | "Show Tasks & Materials" (navigation link) | navigates to the wizard at `#/estimates/{id}/wizard` (pulls the job's atoms into atom-backed lines) |
| `open` | "Revise Estimate" | `POST /api/estimates/{id}/revise/` → opens new draft revision |
| any | status `<select>` | `PATCH /api/estimates/{id}/` with `{status}` (when transitions are valid) |

Editing rules: `canEdit = canManageJobs && status === 'draft'`.

### 11.3 Line item authoring — estimate vs invoice

**Estimate.** The estimate detail page authors line items directly again
(Phase 6's atoms-only projection was reversed). It uses `LineItemModal.svelte`
for **Add Line Item** (manual or catalog) and per-line **Edit**, plus per-line
**Delete** and reorder, and surfaces the "out of sync with atoms" marker on
atom-backed lines. Atom-backed lines are still pulled via the wizard
("Show Tasks & Materials"); hand-lines crystallize into Fees at acceptance.
`POST /api/estimates/{id}/line-items/` creates again (draft-only; a hand-line
requires an accounting category), served by `LineItemMixin.line_items` — the
Phase-6 405 override was removed. GET list, per-line `PATCH`/`DELETE`, reorder,
and `POST .../adjustment-lines/` are unchanged.

**Add from Service** (`AddServiceItemModal.svelte`, estimate detail only) is the
service counterpart to the inventory catalog pick. It creates a real Task on the
Job *immediately* — `POST /api/jobs/{jobId}/add-from-template/`
(`ServiceItem.generate_task`) — then links that Task as an atom-backed line via
`POST /api/estimates/{id}/line-items-from-atoms/` (`{atoms:[{type:'task', id}]}`).
So the line is atom-backed from the start (no acceptance crystallization needed),
and the Task persists on the Job even if the line is later removed. It is
estimate-only: an invoice bills actuals, so a freshly-created zero-actual Task
there makes no sense. **Note the asymmetry with the inventory pick** (which is
deferred — hand-line now, Material at acceptance); reconciling the two
crystallization models is tracked in `docs/designs/LATER.md`.

**Invoice.** `LineItemModal.svelte` is still used by the **invoice** detail
page for direct (no-atom) line authoring — a toggle between **manual entry**
and **"From Price List"** (catalog mode: pick an `InventoryItem`; the server
copies `description`, `units`, `selling_price`, `accounting_category`). Editing
an existing line shows fields only. Bringing the invoice onto the same
atoms-only projection is a deferred consolidation pass.

### 11.4 Job overview — Create/View model

The Job overview page (job detail, estimate pillar) follows a
Create/View model:

- **"Create Estimate"** — shown only when the job's status is `draft`
  or `submitted` **and** no non-superseded estimate exists yet. POSTs
  `{job}` to `/api/estimates/` (→ `EstimateService.create_for_job`,
  always a new draft) and navigates to the new estimate detail page.
  The UI enforces one active estimate tree per job; the backend permits
  multiple estimates, but the button disappears once any live estimate
  exists.
- **"View Full Estimate"** (or equivalent) — shown whenever a
  non-superseded estimate exists, regardless of job status. Can appear
  alongside "Create Estimate" if the button hasn't been suppressed by
  the rules above, but in practice only one state is active at a time:
  once an estimate exists, the Create button no longer renders.

---

## 12. UI: Estimate Wizard page

Route: `#/estimates/:id/wizard` → `EstimateWizardPage.svelte`
(`frontend/src/routes/estimates/`).

### 12.1 Flow

Two columns:

- **Source pool** (left) — `WizardSourcePool` shows every Task and
  Material on the **Job**. Each atom is clickable (checkbox-style) when
  `available`; locked-out otherwise with a "claimed by …" indicator. The
  component binds `selectedAtoms`.
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

### 12.3 Wizard entry

The estimate (and its wizard) is reached from the Job overview's
**Estimate** pillar: "Start Estimate" creates the draft estimate directly
on the job (`POST /api/estimates/` with `{job}`), and "Show Tasks &
Materials" (on the estimate detail) opens the wizard at
`#/estimates/{id}/wizard`. There is no longer a worksheet page or
worksheet-side wizard entry.

---

## 13. Signals

Two signals, defined in `apps/estimates/signals.py` and fired by
`Estimate.save()`. Brief recap; the receiver-by-receiver behavior lives
in `docs/designs/jobs-tasks-and-worksheets.md` §13. (The former
`estimate_status_changed_for_worksheet` signal was removed with the
worksheet layer.)

| Signal | Fires when | Receiver | Effect |
|---|---|---|---|
| `estimate_status_changed_for_job` | draft→open, any→accepted, or open→{rejected, expired} | `update_job_status` | walks the Job through submitted/approved/rejected with HistoryEntry rows (see §9.3) |
| `estimate_accepted` | any→accepted | acceptance receiver | calls `EstimateAcceptanceService.on_accept(estimate)` — crystallizes hand-lines into Fees and earmarks the job (§9) |

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

- A CO is **document-only**: direct line-item composition (manual entry,
  or pulls from `ServiceItem` / `InventoryItem`). It does not project or
  mutate the Job's atoms, and it never runs the estimate wizard.
- **No automated Task/Material changes.** Accepting a CO does not
  spawn, mutate, or cancel any Task or Material. Accepting it advances
  the parent Job and updates the agreement-of-record, full stop. The
  living Job is then edited by hand — Tasks are mutable records of
  what actually happened, and editing them is the normal motion.

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

A CO can only be created while `job.status == on_hold` —
`ChangeOrderService.create` enforces this (see §14.5). The CO's
`estimate` FK pins it to the accepted Estimate that was in force when
the CO was opened; this is what `compose_agreement` walks.

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
| `inventory_item` | Optional catalog pointer, parallel to `EstimateLineItem` provenance |

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

### 14.5 Job on_hold gate

COs are authored only while the parent Job is `on_hold` — a
work-paused state (see `jobs-tasks-and-worksheets.md`). The flow:

1. User pauses the Job (`active → on_hold`). The pause requires a
   `hold_reason`; no open Bleps may exist.
2. While on_hold, the user can `ChangeOrderService.create(job_id=…)`.
   `create` raises if `job.status != on_hold`.
3. The user edits the CO (line items), sends it (`draft → open`),
   and waits for customer response.
4. **Accept:** `ChangeOrderService.update_status(pk, accepted)`
   advances the Job `on_hold → approved` and writes a system-attributed
   HistoryEntry. The CO's deltas are now part of the agreement.
5. **Reject / Expire:** the Job stays `on_hold`. The CO snapshots its
   proposal (so the rejected/expired version is preserved verbatim
   even if the Estimate or its line items later change).
6. Taking the Job off-hold to `approved` requires that no `draft` or
   `open` CO exists — `JobService.update_job` enforces this. Resolve
   open COs (accept / reject / discard) first.

The on_hold gate is the entire point of the state — it's the room
where CO work happens, isolated from the live work side of the Job.
The Schedule excludes `on_hold` jobs from forecasts since their
agreement is in flux (`apps/schedule/services.py`).

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

Like estimates, the parent Job stays `on_hold` after expiry (the
expiry doesn't release the Job; the user has to take it off-hold once
all open COs are resolved).

### 14.8 API endpoints

- `GET /api/jobs/{id}/change-orders/` — list of the job's COs
- `POST /api/change-orders/` — create (body: `{job_id}`)
- `GET / PATCH / DELETE /api/change-orders/{id}/`
- `POST /api/change-orders/{id}/mark-open/` — `draft → open`
- `POST /api/change-orders/{id}/update-status/` — accept / reject /
  discard transitions; routes through `ChangeOrderService.update_status`
- `POST /api/change-orders/{id}/line-items/` — add line item
- `POST /api/change-orders/{id}/line-items/from-pli/` — add from
  InventoryItem
- `PATCH /api/change-orders/{id}/line-items/{liid}/` — update
- `POST /api/change-orders/{id}/line-items/reorder/`
- `DELETE /api/change-orders/{id}/line-items/{liid}/`
- `GET /api/change-orders/{id}/deliverables-baseline/` — the snapshot
  of deliverables-at-CO-creation used to render the CO-edit view's
  baseline (see `jobs-tasks-and-worksheets.md` §12 for snapshot
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

`frontend/src/routes/change-orders/ChangeOrderDetailPage.svelte` is the
CO edit view. It renders a merged baseline-vs-proposal diff using the
CO's line items and the `deliverables-baseline` endpoint;
`COLineItemModal.svelte` is the line-item editor. The Estimate detail
page shows accepted COs as pills/badges in the deliverables and
line-items sections.

**The "amended" status label.** An accepted estimate that an accepted
change order amends keeps its stored `status = accepted` — it is still
the base of the agreement-of-record — but the UI relabels it **amended**
so the human sees that the agreement has moved. This is derived, never
stored: `EstimateSerializer.is_amended` (and the board pipeline payload's
per-estimate `is_amended`) returns true when the estimate is `accepted`
and at least one **accepted** CO references it. The frontend renders
`is_amended ? 'amended' : status` (`JobDetail`, `EstimateDetailPage`, the
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
  (`PortalApp.svelte` → `EstimatePortal` or `ChangeOrderPortal`). `doc` is
  **required and explicit** for both document types — estimate links are
  `&doc=estimate` (see `build_object_url('estimate', …)` and the in-app
  superseded forward links); a portal URL with a missing or unknown `doc`
  renders a "could not be found" message and makes no API call, rather than
  silently assuming a document type.
- **API** (`apps/api/portal/change_order_views.py`, all `AllowAny`,
  `authentication_classes([])`):
  - `GET /api/portal/change-orders/<token>/` →
    `build_change_order_payload` (a before/after diff: `line_rows` with
    `kind ∈ {unchanged, changed, changed-orig, removed, added}` from
    `compose_change_order_diff`, a `deliverables` diff, `prior_total` /
    `proposed_total` / `diff_total`, `actions`, `actionable`,
    `closed_message`, and `current_token` when superseded). A `draft`
    CO or unknown token 404s.
  - `POST …/accept/` → `update_status(ACCEPTED)` (job `on_hold →
    approved`).
  - `POST …/reject/` (body `{reason}`) → `update_status(REJECTED)` (job
    stays `on_hold`).
  - `POST …/request-changes/` (body `{reason}`) →
    `ChangeOrderService.request_changes`: supersede the open CO and
    `seed_new` a fresh draft, job stays `on_hold`.
- **Actionability.** A CO is actionable only when `status == open` and
  its job is `on_hold` (the CO analog of an estimate being `open` with
  its job `submitted`). A click that races a shop action is a silent
  no-op. Each decision runs under `select_for_update`.
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
  estimate PDF) renders both diffs — a "What you'll receive" deliverables
  section and the line-item table with prior/new/change totals — using
  print-safe change labels (Added/Removed/Changed/was). It is attached to
  the CO send email.

---

## 15. Sending an Estimate

`EstimateEmailService.send_estimate` (`apps/estimates/services.py`)
is the entry point. The SPA route `/estimates/:id/send` mounts
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
`authentication_classes=[]`):**

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
   `jobs-tasks-and-worksheets.md`), so a draft job + draft estimate keep it
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
has no operator nav, and reads the token from the query string. It
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

- **Default service price for worker quick-add** — the worker-side
  `WorkItemForm` flow currently still requires the worker to pick a
  service price. A `default_worker_rate_scheme` Configuration key
  that the form would silently default to when the user lacks
  `can_manage_jobs` has been designed but not shipped. Pairs with the
  broader worker-friendly mid-job task creation work.

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
  (service-price reassignment, modifier toggles) are a normal
  estimating-related event but don't surface in the Job HistoryPanel.
  Tracked in `jobs-tasks-and-worksheets.md`.

- **`accounting_category` required on `EstimateLineItem`** — part of the
  project-wide line-item AC-NOT-NULL migration tracked in
  `architecture-and-conventions.md`.

- **Review `EstimateAcceptanceService.on_accept` in detail.** The current
  behaviour is documented in §9 — crystallize each hand-line into a `Fee`
  (recording a `fee` source link), then earmark the job. Review against
  real estimate-accept scenarios and revise if needed.

# Hour as a first-class unit — design spec

_Status: draft for RM review. 2026-08-01._

## Problem

Three related defects in how time interacts with the configurable-units system:

1. **`elapsed_time` schemes lie about their unit.** `RateScheme.get_actual_qty()`
   (`apps/jobs/models.py:540-547`) sums blep durations and divides by 3600 —
   the quantity is always *hours*, but `unit_label` is a free pick from the
   units list. A "based on time worked" scheme with unit `gal` bills hours at
   the per-`unit_label` rate and prints "N gal from timeslips" in the invoice
   wizard (`apps/invoicing/services.py:552-562`).
2. **Tasks carry two disconnected estimates of the same number.** For
   time-based work, `est_qty` (billable, in scheme units) and
   `est_worker_time` (a duration, for scheduling) are the same quantity in two
   encodings, entered in two separate inputs (`WorkItemForm.svelte`) with no
   cross-fill. Estimate acceptance sets `est_qty` but never `est_worker_time`
   (`apps/estimates/acceptance.py:58-70`), which is why the board prompts for
   worker time at assign.
3. **Nothing marks which configured unit means "hour".** The units list is
   bare strings; `hours` is deletable like anything else. (Acknowledged open
   item at `docs/designs/estimates-and-prices.md` §"Auto-fill est_worker_time
   when scheme units are hours".)

## Decisions (agreed with RM, 2026-08-01)

- **All unit names become singular** — `hours` → `hour`, `sheets` → `sheet`,
  `lbs` → `lb` (and `pcs` → `pc` where fixtures carry it). Code, config,
  fixtures, datasets, docs.
- **`hour` is a special unit**: seeded, required to be present, undeletable in
  the units config — same treatment as `none`. It stays in the general list
  (an `entered_qty` scheme or a hand line may legitimately use `hour`).
  Represented as a sentinel string + code constant, **not** a structured-units
  rework (that waits for the divisibility-flag work, which wants the same
  structured home).
- **`elapsed_time` ⇒ `unit_label == 'hour'`**, enforced at the model and
  auto-set at every write surface. Existing offenders corrected by data
  migration (the frozen-fields rule protects referenced documents from
  *meaning* changes; these labels always displayed next to hour quantities, so
  correcting them fixes a lie, not a price).
- **One estimate input for hour-unit work.** When a task's scheme unit is
  `hour`, the UI shows a single "Estimated hours" input that writes both
  `est_qty` and `est_worker_time`. Both DB fields survive (billing vs
  scheduling consumers; non-hour tasks still need both independently). The
  "billable hours ≠ scheduled hours" distinction is deliberately dropped —
  RM: if we bill fewer hours than worked, that's an invoice edit.
- **Consolidate the duplicated time-conversion helpers** (three JS
  decimal-hours parsers, two independent Python seconds→hours conversions).

## Out of scope (deliberate)

- **Blended-rate consolidation.** When a wizard line bundles tasks whose rate
  schemes (or modifiers) do NOT match, the fallback stays exactly as today:
  `qty=1, units='none', price=total`. No computed blended per-hour rate —
  RM explicitly does not want that. (Matching-scheme bundles already
  consolidate via `_uniform_scheme_bundle`; §5 extends that honesty to the
  single-atom case only.)
- An in-use guard for deleting *other* units — RM: they're mere labels; drift
  against old data doesn't matter.
- Structured units (`{label, kind, divisible}`) — future, with the
  divisibility flag.
- Labor-cost math (`apps/jobs/financials.py`) and the schedule
  (`apps/schedule/`) — both are correctly hour/minute-native already and never
  read `unit_label`. No changes.
- The two config-robustness bugs found during research (generic settings PATCH
  bypassing units validation; `get_units_list()` not catching
  `JSONDecodeError`) — logged in `docs/designs/LATER.md` 2026-08-01, not part
  of this branch.

---

## 1. Canonical list, constant, and the singular sweep

**`apps/core/units.py`:**

```python
DEFAULT_UNITS = [
    "none", "ea", "hour", "min", "sheet", "sq ft", "ft", "yd", "m",
    "lb", "kg", "gal", "qt", "L", "bd ft", "ln ft",
]
HOUR_UNIT = "hour"
```

Every special case introduced by this spec references `HOUR_UNIT` (backend)
or a mirrored frontend constant (see §5) — no new string literals.

Also delete the dead `UnitsFieldMixin` (zero importers) while touching the
file.

**Data migration** (one migration, `apps/core`), in order:

1. Rewrite the `units_list` Configuration row: map each entry through a
   plural→singular dict (`hours→hour`, `sheets→sheet`, `lbs→lb`, `pcs→pc`);
   append `hour` if absent. Preserve existing order otherwise.
2. Singularize every stored unit string through the same dict:
   `EstimateLineItem.units`, `ChangeOrderLineItem.units`,
   `PurchaseOrderLineItem.units`, `BillLineItem.units` (schema stub, rows may
   exist), `InvoiceLineItem.units`, `InventoryItem.units`, `Material.units`,
   `Deliverable.units`, `DeliverableSnapshot.units`, `RateScheme.unit_label`.
3. Set `unit_label = 'hour'` on every `RateScheme` with
   `algorithm='elapsed_time'`, whatever it said before.

`QuerySet.update()` is correct here despite the house rule: data migrations
operate on historical models, which carry no custom `save()` in any case, and
none of these fields are save-normalized. (The `_seed_setup_defaults` helper
keeps reading `DEFAULT_UNITS`, so fresh installs get the singular list; its
`get_or_create` never overwrites, hence the migration for existing DBs.)

**House rule reminder:** migrations changed ⇒ the final full-suite run is
WITHOUT `--keepdb`.

## 2. `hour` is undeletable

- `units_view` PATCH (`apps/api/templates_config/views.py`): alongside the
  existing checks (non-empty, `none` first, no duplicates) add: the list must
  contain `hour` (any position).
- `UnitsManager.svelte`: the remove button refuses `hour` exactly as it
  refuses `none`; extend the helper text to name both specials and why
  (`none` = "no unit", `hour` = the unit time-based billing and scheduling
  are denominated in).
- Tests: extend `tests/test_units_api.py` (reject a list missing `hour`);
  Vitest for the manager's disabled state.

## 3. `elapsed_time` schemes are pinned to `hour`

**Model (the invariant's true home):** `RateScheme.clean()` raises
`ValidationError({'unit_label': [...]})` when `algorithm == ELAPSED_TIME` and
`unit_label != HOUR_UNIT`. (`RateScheme.save()` already runs `full_clean()` on
update; confirm the create path validates too.)

**Serializer:** `apps/api/rate_schemes/serializers.py` — follow the existing
`percentage → 'none'` precedent (lines 46-48): when `algorithm ==
elapsed_time`, force `unit_label = HOUR_UNIT` regardless of input, skipping
the membership check. Users never see the model error.

**Frontend `RateSchemeManager.svelte`:** when the algorithm select reads
`elapsed_time`, replace the unit `<select>` with a fixed, disabled "hour"
display (mirror however the `percentage` case is handled today). Also fix the
preview's naive pluralization (line ~349, `{unit_label}s` → renders "hourss"):
display the unit verbatim, no auto-`s`, e.g. `3 hour @ $50.00/hour`. Singular
units make this read fine.

**QBO scheme import:** `SchemesImportPanel.svelte` — choosing
"elapsed time (hourly)" for a row forces that row's unit to `hour` (picker
disabled), resolving the current contradiction where the unit default stays
`ea` (`apps/qbo/import_services.py:410`). Backend
`apps/qbo/import_services.py` applies the same rule on commit — defense in
depth with the model clean().

**nealsdata converter:** `nealsdata/converter/` emits `'hours'` today
(`build.py` canon list at ~L164, `_UNIT_PATTERNS` at ~L748, `parsing.py`
`'Days'→hours×8` handling, `convert.md` §units) — switch all to `'hour'`,
elapsed schemes included. Regenerate `nealsdata/datasets/converted.json` and
**run `tests.test_neals_builders`** (house rule). **`nealsmall.json` is
RM-managed — do not touch or regenerate it**; it will carry plural strings
until RM refreshes it, which is acceptable (labels only).

## 4. One estimate input; auto-fill of `est_worker_time`

The pairing rule keys on **scheme unit == `hour`** (covers every
`elapsed_time` scheme and any `entered_qty`-in-hours scheme), not on the
algorithm.

**Service layer (`apps/jobs/services.py`, task create/update paths):** when
the task's scheme unit is `hour` and exactly one of `est_qty` /
`est_worker_time` is provided, derive the other (`est_qty` decimal hours ↔
duration). If both are provided, accept both as given (the API stays
permissive; the SPA is what keeps them equal). This is deliberately a
convenience fill, **not** a hard invariant — legacy rows may diverge and
that's harmless.

**Crystallization auto-fill** (resolves the open item in
estimates-and-prices):

- `apps/estimates/acceptance.py` and `apps/estimates/co_acceptance.py`: when
  the line's scheme unit is `hour`, set
  `est_worker_time = timedelta(hours=float(est_qty))` on the created Task.
- `ServiceItem.generate_task` (`apps/estimates/models.py`): same fill when
  `est_worker_time` isn't passed and the scheme unit is `hour`.

Consequence worth an explicit test: an accepted hour-denominated line lands on
the board already schedulable — the assign-time `WorkerTimePromptModal` no
longer fires for it.

**`WorkItemForm.svelte`:** when the selected scheme's unit is `hour`, render
one input — "Estimated hours" (accepts `HH:MM` or decimal hours, the existing
hint) — and submit both fields from it. For other units keep today's two
inputs. Prefill when editing an existing hour-unit task: `est_worker_time` if
set, else `est_qty`; saving overwrites both (this is how legacy divergent rows
converge).

**Display:** `TaskDetailPage.svelte` and `TaskRow.svelte` — for hour-unit
tasks show a single estimate value (they're now kept equal; if a legacy row
diverges, show both as today). The literal `|| 'hour'` fallback at
`TaskDetailPage.svelte:437` becomes consistent with the configured list;
keep or drop at implementer's discretion — it's no longer a lie either way.

## 5. Invoice wizard: single-atom elapsed lines copy over `hours × rate`

Multi-atom same-scheme bundles already consolidate correctly
(`_uniform_scheme_bundle`, `apps/core/wizard.py:150-175`: units from the
scheme, qty = summed actuals, price = common effective rate). But
`add_atoms_to_new_line_item` branches on `len(instances) == 1` before the
summarizer runs, and the invoice-side `_task_qty_and_price`
(`apps/invoicing/services.py:1138-1146`) special-cases elapsed-time to
`qty=1, price=total` — so one task alone prints `1 hour × $total` while the
same task inside a bundle prints `N.NN hour × $rate`. The comment justifying
it ("no single qty/price is meaningful") is stale: `get_actual_qty` × 
`effective_rate` equals the computed amount exactly, same arithmetic the
bundle path uses. It's also inconsistent with `_resync_in_sync_line_item`,
which runs the summarizer even on a single-source line and would rewrite the
solo line to `hours × rate` on any source-set change.

**Change:** delete the elapsed special-case in
`InvoiceWizardService._task_qty_and_price` — with a scheme present, return
`(scheme.get_actual_qty(task), task.effective_rate())` for both algorithms.
Single-atom elapsed lines then carry real hours, the rate, and (post-§3)
units `hour`; `qty_source_label`'s "N.NN hour from timeslips" finally matches
the line it sits under. The estimate-side wizard needs no change (it already
prices `est_qty × rate` uniformly). Existing assertions pinning `qty=1` /
`units='hours'` for solo elapsed lines in `tests/test_invoice_wizard_service.py`
(~L397, 428, 591, 616) update to the new shape.

The mismatched-scheme fallback is untouched (see Out of scope).

## 6. Conversion/parser consolidation

**Backend — one seconds→hours conversion.** Add
`timedelta_to_hours(td) -> Decimal` to `apps/core/timeutils.py` (unquantized;
call sites keep their own rounding). Convert:

- `RateScheme.get_actual_qty` (`apps/jobs/models.py:547`) — quantizes 0.01.
- `apps/jobs/financials.py:86` (`_blep_hours`).
- `apps/jobs/overview.py:34-35` (`_duration_hours`).
- `apps/api/tasks/serializers.py:167-172` (`get_actual_hours`) — currently an
  independent *float* implementation that can drift from `get_actual_qty`;
  route through the shared helper, keep the JSON output numeric
  (`float(...)` at the boundary) so the API shape doesn't change.

**Frontend — one duration module.** `lib/format.js` is the canonical home
(`parseDurationToISO` — bare decimals are hours — and `formatDuration`).
Remove the duplicates:

- `WorkItemForm.svelte:145-168` `durationToISO` (third copy of the parser).
- `lib/taskTotals.js` `fmtWorkerTime`'s private ISO/HH:MM:SS parser —
  re-express via the `format.js` primitives.

The six-odd standalone `h/m` formatters (BlepList, BlepLogTable,
ShiftLogTable, ShiftBand, CurrentBlepBand, PayrollReport) migrate to
`formatDuration` **only where it's a drop-in**; don't force-fit ones with
genuinely different display needs. Note any survivors in the PR description.

## 7. Fixture and dataset sweep (singularization)

Apply the same plural→singular dict to every committed JSON that carries unit
strings or a `units_list` config row. Known carriers (grep before finishing —
`"hours"|"sheets"|"lbs"|"pcs"`):

- `fixtures/unit_test_data.json`, `fixtures/invoicing_data.json`,
  `fixtures/core_base_data.json`, `fixtures/contact_data/01_base_contacts.json`
  (these three have drifted lists containing `pcs` — singularize in place,
  don't reorder or otherwise re-canonize).
- `fixtures/playwright/seed.json`, `fixtures/playwright/rebased.json`,
  `fixtures/staging/seed.json`, `fixtures/large_datasets/nealseed.json` —
  regenerate via the converter pipeline if practical, otherwise scripted JSON
  edit; verify the e2e suite still boots its DB from the seed.
- `nealsdata/datasets/converted.json` — regenerate from the converter (§3).
- **NOT `fixtures/large_datasets/nealsmall.json`** — RM-managed, leave as-is.
- Test modules asserting `'hours'` (`tests/test_invoice_wizard_service.py`,
  `tests/test_invoice_line_from_service.py`, plus whatever the sweep finds)
  update to `'hour'`.

## 8. Tests

Backend (TDD; targeted modules per task, full suite once at the end, fresh DB):

- Units API: list must contain `hour`; existing four negatives still pass.
- `RateScheme.clean()` rejects elapsed+non-hour; serializer force-sets;
  QBO import commit force-sets.
- Task service pair-fill: hour-unit task created with only `est_qty` gets
  `est_worker_time` (and vice versa); non-hour task untouched; both-provided
  passes through.
- Acceptance + CO acceptance + `generate_task` auto-fill, including "no
  worker-time prompt needed" (task arrives with `est_worker_time` set).
- `get_actual_hours` equals `get_actual_qty` for elapsed tasks (drift test).
- Invoice wizard: a solo elapsed-time atom copies over
  `(actual hours, effective rate, 'hour')` and matches what the same task
  produces inside a same-scheme bundle; mismatched-scheme bundles still fall
  back to `qty=1 / units='none' / price=total`.

Vitest (`frontend/tests/`):

- `WorkItemForm`: single input for hour-unit scheme, writes both fields;
  two inputs otherwise; prefill rules.
- `RateSchemeManager`: unit control locked to `hour` under `elapsed_time`;
  preview shows verbatim unit.
- `UnitsManager`: `hour` not removable.

E2E (Definition of Done): one spec covering the user-reachable arc — create an
elapsed-time rate scheme (unit locked to hour), estimate + accept an
hour-denominated line, observe the task is assignable without the worker-time
prompt and the task form shows the single hours input. Runs against the
rebuilt (singularized) seed.

## 9. Docs to update in the same session

- `docs/designs/estimates-and-prices.md` — `unit_label` description (no more
  "e.g. hour, minute" free-for-all), the elapsed⇒hour rule, `est_qty`/
  `est_worker_time` pairing, and mark the §"Auto-fill est_worker_time" open
  item resolved.
- `docs/designs/data-constraints.md` §1.1 — singular `units_list` canon, the
  two special units (`none` first, `hour` required), elapsed⇒hour constraint.
- `docs/designs/materials-inventory-and-purchasing.md` — fix the stale claim
  (~L684) that Task/ServiceItem carry a units field.
- `docs/designs/jobs-and-tasks.md` — task form's single-input behavior.
- `nealsdata/convert.md` — `Hours`/`Days` mapping now emits `hour`.

## 10. Sequencing sketch

1. `units.py` (list, constant, dead-code removal) + data migration + fixture
   sweep — the rename must land atomically so serializer validation never
   sees a mixed state.
2. Model/serializer/import pinning of elapsed⇒hour (§3).
3. Service pair-fill + acceptance auto-fill (§4 backend).
4. Frontend: WorkItemForm merge, RateSchemeManager lock, UnitsManager guard,
   displays (§4 frontend, §2).
5. Invoice-wizard solo-elapsed copy-over (§5) — small, rides with step 2's
   test updates.
6. Conversion consolidation (§6) — independent, can interleave.
7. Converter + datasets + `tests.test_neals_builders` (§3, §7).
8. Docs (§9), full suite without `--keepdb`, Vitest suite, e2e.

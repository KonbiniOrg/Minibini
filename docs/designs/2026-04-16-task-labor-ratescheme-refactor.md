# Task-as-Labor + RateScheme Refactor

## Summary

Refactor Task to be a pure labor entity. Introduce RateScheme as a first-class billing pattern, and TaskCharge/PlanCharge as the per-instance billing configuration. Remove billing fields from TaskBase. Establish TaskTemplate as the labor catalog (parallel to PriceListItem for materials).

## Motivation

Tasks originally served double duty — labor and materials. Materials have since moved to their own model. Tasks still carry generic billing fields (`units`, `rate`, `est_qty`) that don't express the shop's actual billing patterns: hourly labor, machine-minute charges with percentage modifiers, flat fees. This refactor makes billing explicit, auditable, and configurable.

## New Models

### RateScheme

The billing pattern. Admin-configured in Settings. Defines how a type of work is priced.

```
RateScheme:
  rate_scheme_id: AutoField (PK)
  name: CharField(max_length=100)            # "CNC Router", "Hourly Labor"
  description: TextField(blank=True)         # longer explanation for admins
  algorithm: CharField(choices)              # elapsed_time | entered_qty | flat_fee
  rate: DecimalField(max_digits=10, dp=2)    # per-unit price
  unit_label: CharField(max_length=50)       # "hour", "minute", "piece", "job"
  minimum_charge: DecimalField(null=True)    # optional floor
  modifiers: JSONField(default=list)         # [{key, label, percent}, ...]
  accounting_category: FK(AccountingCategory, nullable)

  class Meta:
      db_table = 'rate_schemes'
```

**Algorithm types:**

| Algorithm | qty source | Use case |
|---|---|---|
| `elapsed_time` | Sum of Blep durations on the task | Hourly labor (assembly, bench work) |
| `entered_qty` | Worker-entered value in TaskCharge.actuals | Machine minutes, piece work |
| `flat_fee` | Hardcoded 1 | Setup fees, delivery |

**Modifier format** (each entry in the `modifiers` JSON array):

```json
{
  "key": "messy",
  "label": "Messy materials",
  "percent": 10
}
```

- `key`: stable identifier, used as key in TaskCharge.active_modifiers
- `label`: display text shown in checkboxes and on estimates/invoices
- `percent`: additive percent-of-base surcharge

Multiple modifiers stack additively: messy (+10%) + doublestick (+5%) = +15% on base rate.

**Methods:**

- `compute_charge(qty, active_modifiers) -> Decimal` — core calculation:
  ```
  modifier_percent = sum(m.percent for m in self.modifiers if m.key in active_modifiers)
  effective_rate = self.rate * (1 + modifier_percent / 100)
  return max(qty * effective_rate, self.minimum_charge or 0)
  ```
- `get_actual_qty(task) -> Decimal` — resolves qty based on algorithm. Accepts a Task instance (deliberate coupling — RateScheme reads task.bleps and task.charge.actuals):
  - `elapsed_time`: sum of task's blep durations in hours (`total_seconds / 3600`)
  - `entered_qty`: `task.charge.actuals.get('qty', 0)`
  - `flat_fee`: `Decimal(1)`
- `effective_rate(active_modifiers) -> Decimal` — rate with modifier surcharges applied
- `get_modifier_inputs()` — returns list of modifier definitions for UI rendering

**Append-only convention:** RateSchemes should not be edited once referenced by tasks. To change rates, create a new RateScheme and update TaskTemplates to point to it. Old tasks retain their original scheme FK. This preserves billing history without a versioning table.

### TaskCharge

The filled-in billing form for a Task. One per Task (OneToOne). Stores which modifiers are active and what values the worker entered.

```
TaskCharge:
  task_charge_id: AutoField (PK)
  task: OneToOneField(Task, related_name='charge')
  rate_scheme: FK(RateScheme, on_delete=PROTECT)
  active_modifiers: JSONField(default=list)  # ["messy", "doublestick"]
  actuals: JSONField(default=dict)           # {"qty": 35}

  class Meta:
      db_table = 'task_charges'
```

- `active_modifiers`: list of modifier keys from the scheme that apply to this task
- `actuals`: worker-entered values. For `entered_qty` algorithm: `{"qty": <value>}`. For `elapsed_time` and `flat_fee`: `{}` (empty — qty is derived).

**Methods:**

- `compute() -> Decimal` — convenience: calls `self.rate_scheme.compute_charge(self.rate_scheme.get_actual_qty(self.task), self.active_modifiers)`
- `effective_rate() -> Decimal` — calls `self.rate_scheme.effective_rate(self.active_modifiers)`
- `has_actuals() -> bool` — whether worker has entered required values

**Validation:** `active_modifiers` keys must be a subset of the scheme's modifier keys. `actuals` keys must match what the algorithm expects.

### PlanCharge

Same shape for PlanTask (worksheet/estimate stage). No actuals — used for quoting only.

```
PlanCharge:
  plan_charge_id: AutoField (PK)
  plan_task: OneToOneField(PlanTask, related_name='charge')
  rate_scheme: FK(RateScheme, on_delete=PROTECT)
  active_modifiers: JSONField(default=list)
  estimated_billable_qty: DecimalField(max_digits=10, dp=2)

  class Meta:
      db_table = 'plan_charges'
```

**Methods:**

- `compute() -> Decimal` — `self.rate_scheme.compute_charge(self.estimated_billable_qty, self.active_modifiers)`
- `effective_rate() -> Decimal`

## Changes to Existing Models

### TaskBase (abstract)

**Remove** the following fields (billing moves to Charge objects):
- `units` — replaced by `RateScheme.unit_label`
- `rate` — replaced by `RateScheme.rate`
- `est_qty` — replaced by `PlanCharge.estimated_billable_qty` / `TaskCharge.actuals`

**Add:**
- `est_worker_time: DurationField(null=True, blank=True)` — estimated worker time for scheduling. Used by Task for calendar projection; PlanTask may leave null. Lives on TaskBase so no separate migration is needed when scheduling work begins.

**Keep:**
- `name`, `description`, `sort_order`, `accounting_category`

### Task

**No new fields on Task itself.** Billing lives on TaskCharge (OneToOne).

**Add:**
- `source_template: FK(TaskTemplate, null=True, blank=True, on_delete=SET_NULL)` — which template spawned this task

**Keep unchanged:**
- `task_id`, `parent_task`, `assignee`, `job`, `status`, `blocked_reason`, `worker_queue`

**Remove (via TaskBase change):**
- `units`, `rate`, `est_qty`

### PlanTask

**Remove (via TaskBase change):**
- `units`, `rate`, `est_qty`

Billing lives on PlanCharge (OneToOne).

### TaskTemplate

Becomes the labor catalog. Currently has fields inherited from its own model definition.

**Changes:**
- **Add** `rate_scheme: FK(RateScheme, null=True, blank=True, on_delete=SET_NULL)` — default scheme for tasks from this template
- **Add** `default_active_modifiers: JSONField(default=list)` — pre-checked modifier keys
- **Add** `default_billable_qty: DecimalField(null=True, blank=True)` — typical estimated qty
- **Remove** `units`, `rate` (if present — these move to RateScheme)
- **Keep** `name`, `description`, `accounting_category`, `is_active` (and any other existing fields)

### BaseLineItem

No changes. InvoiceLineItem and EstimateLineItem continue to store frozen qty, price, description. The Charge objects compute values; line items snapshot them.

## API Changes

### New Endpoints

**RateScheme CRUD:**
- `GET/POST /api/rate-schemes/` — list/create
- `GET/PUT/PATCH/DELETE /api/rate-schemes/{id}/` — retrieve/update/delete
- Permission: `CanManageConfig` for write, `IsAuthenticated` for read

**TaskCharge (nested under task):**
- `GET/PUT/PATCH /api/jobs/{job_id}/tasks/{task_id}/charge/` — get or update the task's charge
- `POST /api/jobs/{job_id}/tasks/{task_id}/charge/` — create charge for a task that doesn't have one
- Permission: `CanManageJobs` for create/update, `IsAuthenticated` for read

**PlanCharge (nested under plan task):**
- `GET/PUT/PATCH /api/est-worksheets/{ws_id}/plan-tasks/{pt_id}/charge/` — get or update
- `POST /api/est-worksheets/{ws_id}/plan-tasks/{pt_id}/charge/` — create
- Permission: `CanManageJobs` for write, `IsAuthenticated` for read

### Modified Endpoints

**TaskTemplate serializer:**
- Add `rate_scheme`, `default_active_modifiers`, `default_billable_qty` fields
- Remove `units`, `rate` (once migration complete)

**PlanTask serializer:**
- Remove `units`, `rate`, `est_qty` — billing data now on nested PlanCharge
- Include `charge` as nested read representation (scheme name, effective rate, modifiers, estimated charge)

**Task serializer:**
- Remove `units`, `rate`, `est_qty`
- Add `source_template` (read-only)
- Include `charge` as nested read representation

**Estimate line item generation** (`apps/estimates/services.py`):
- When creating EstimateLineItems from PlanTasks, read billing data from PlanCharge instead of PlanTask fields
- `qty = plan_charge.estimated_billable_qty`
- `price = plan_charge.effective_rate()`
- `units` on line item = `plan_charge.rate_scheme.unit_label`

## UI Requirements

### Settings: RateScheme Management (NEW)

New section in SettingsPage. Permission: `CanManageConfig`.

**List view:** Cards or table rows showing each RateScheme: name, algorithm (friendly label), rate, unit_label, modifier count.

**Create/Edit form** (modal or inline expansion):
- Name (text input)
- Description (textarea)
- Algorithm (dropdown: "Based on time worked" / "Worker enters quantity" / "Fixed charge")
- Rate (decimal input) + Unit label (text input, e.g., "hour", "minute")
- Minimum charge (optional decimal input)
- Accounting category (dropdown)
- **Modifiers section:**
  - List of modifier rows, each with: Label (text), Percent (number)
  - Add/remove modifier buttons
  - Key auto-generated from label (slugified, stable after creation)

**Live preview:** As admin configures, show example calculation: "10 [unit_label] @ $[rate]/[unit_label] + [active modifiers] = $[total]"

**Validation:**
- Name required, unique
- Rate required, > 0 (except flat_fee allows rate = 0 for "free" tasks)
- Unit label required
- Modifier labels unique within a scheme
- Modifier percents > 0

### Settings: TaskTemplate Management (NEW)

New section in SettingsPage. Permission: `CanManageConfig`.

**List view:** Cards or table rows showing each TaskTemplate: name, linked RateScheme name, default modifiers, default qty.

**Create/Edit form:**
- Name (text input)
- Description (textarea)
- RateScheme (dropdown — shows scheme name + algorithm type)
- **Default modifier checkboxes** — dynamically populated from selected scheme's modifiers. Estimator defaults. Pre-checked ones apply unless estimator unchecks.
- Default estimated qty (decimal input, optional) + unit label shown read-only from scheme
- Accounting category (dropdown, overrides scheme default if set)
- Is active (toggle)

**Behavior:** When RateScheme selection changes, modifier checkboxes refresh to show the new scheme's modifiers (all unchecked by default).

### Worksheet Builder: PlanTaskModal (MODIFY)

Modify the existing PlanTaskModal in the worksheet detail page.

**From-template mode:**
- After selecting a TaskTemplate, show:
  - Scheme info (read-only): name, rate, unit label
  - **Modifier checkboxes**: populated from scheme, pre-checked per template's `default_active_modifiers`. Estimator can toggle.
  - **Estimated qty input**: pre-filled from template's `default_billable_qty` if set
  - **Estimated charge display**: live-computed as `qty * effective_rate`. Updates as modifiers toggle or qty changes.
- On save: creates PlanTask + PlanCharge (scheme, active_modifiers, estimated_billable_qty)

**Freeform mode:**
- Add optional RateScheme dropdown. If a scheme is selected, show modifier checkboxes + qty input (same as template mode).
- If no scheme selected, create PlanTask without a PlanCharge (unpriced planning task).

### Task Detail Page (MODIFY)

Modify the existing TaskDetailPage.

**Charge info section** (visible when TaskCharge exists):
- Read-only display: scheme name, effective rate, active modifier badges
- For `entered_qty` tasks: **editable input** for actual qty, labeled with scheme's unit_label ("Actual minutes:", "Actual pieces:")
- For `elapsed_time` tasks: show computed qty from bleps (read-only)
- For `flat_fee` tasks: show rate (read-only)
- Show computed charge total

**Permissions:**
- Worker (`IsAuthenticated`): can enter actual qty on their assigned tasks
- Manager (`CanManageJobs`): can also toggle active modifiers, change scheme

### Invoice Wizard (DEFERRED)

The invoice wizard changes are deferred until the above is functional in the browser. The current wizard behavior is preserved unchanged. Invoice wizard redesign will be a separate spec after hands-on evaluation of the new billing model.

## Migration Strategy

### Data Migration

1. Create new tables: `rate_schemes`, `task_charges`, `plan_charges`
2. Group existing Tasks by distinct (`units`, `rate`) combinations. For each combination, create a RateScheme:
   - `algorithm`: `elapsed_time` if units is 'hours' or 'none', `entered_qty` otherwise
   - `rate`: the task's rate value
   - `unit_label`: the task's units value (normalize 'none' to 'hour')
   - `name`: auto-generated, e.g., "Migrated — $45/hour"
3. For each existing Task:
   - Create a TaskCharge pointing to the matching RateScheme
   - For `entered_qty` schemes: store `est_qty` in `TaskCharge.actuals` as `{"qty": est_qty}`
   - `active_modifiers`: empty (no modifiers existed before)
4. Same for PlanTasks → PlanCharges (using `estimated_billable_qty` = `est_qty`)
5. Tasks/PlanTasks with no `rate` and no `est_qty`: no TaskCharge/PlanCharge created (unpriced tasks)
6. Drop `units`, `rate`, `est_qty` from TaskBase after migration confirmed and Phase 1 is stable

### Phased Rollout

**Phase 1 — Models + API + Settings UI:**
- New models + migrations
- API endpoints for RateScheme CRUD
- Settings UI for RateScheme and TaskTemplate management
- Data migration for existing tasks

**Phase 2 — Worksheet + Task UI:**
- PlanTaskModal changes (modifier checkboxes, PlanCharge creation)
- Task detail page changes (actual qty entry, charge display)
- Estimate line item generation reads from PlanCharge

**Phase 3 — Invoice Wizard (separate spec):**
- Redesign wizard to work with TaskCharge
- Handle tasks with and without charges
- Deferred until Phase 2 is usable in browser

## Permissions

| Action | Permission |
|---|---|
| View RateSchemes | IsAuthenticated |
| Create/Edit/Delete RateSchemes | CanManageConfig |
| View TaskTemplates | IsAuthenticated |
| Create/Edit/Delete TaskTemplates | CanManageConfig |
| View TaskCharge/PlanCharge | IsAuthenticated |
| Create/Edit PlanCharge (worksheet) | CanManageJobs |
| Enter actual qty on own tasks | IsAuthenticated |
| Toggle modifiers / change scheme on TaskCharge | CanManageJobs |

## Not in Scope

- **Scheduling / calendar view** — separate design, depends on this refactor
- **Tiered/volume algorithm** — add when volume pricing graduates from ad-hoc estimates
- **Rate versioning** — append-only convention is sufficient for now
- **Invoice wizard changes** — deferred to Phase 3
- **Compound modifiers** (percent-of-total, multiplicative stacking) — additive percent-of-base covers current needs

# Dissolve TaskCharge; Restore Work Measurement on Task

## Summary

Dissolve `TaskCharge` into `Task`. Restore `est_qty` (the billable-units estimate) as a first-class field on Task, alongside `est_worker_time` (already on `TaskBase`) and a new typed `actual_qty` (replacing `TaskCharge.actuals.qty`). Expose `est_worker_time` and `est_qty` in the Task-add UI for the first time, and converge the three near-duplicate Task-add modals (TaskModal, SubtaskModal, PlanTaskModal) onto a shared form fronted by a two-button entry: **Add Task From Template** vs **Add Manual Task**.

The motivating insight is that the 2026-05-02 "billing identity" refactor focused entirely on the billing axis and inadvertently erased the **work-measurement axis** — quantity and time, estimated and actual, which scheduling, mid-job progress reporting, and estimate-vs-actuals refinement all depend on. This design re-introduces work measurement as a structural concern on `Task` (and keeps it on `PlanTask`), without giving up any of the billing-identity claim.

## Prior Design Summaries (relevant context)

These four documents shape the current state. The summaries here are scoped to what bears on this design — see the originals for full reasoning.

### `2026-04-05-task-split-and-worksheet-to-workorder.md`

Established the `PlanTask` (worksheet-side) vs `Task` (job-side) split with `TaskBase` abstract. Hierarchy (`parent_task`) lives only on `Task`. Bleps live only on `Task`. `TaskBase` carried `units`, `rate`, `est_qty`, `accounting_category` at the time of that doc — fields later removed.

### `2026-04-16-task-labor-ratescheme-refactor.md`

Introduced `RateScheme`, `TaskCharge`, `PlanCharge` (later merged into `PlanTask`). Removed `units` / `rate` / `est_qty` from `TaskBase` on the basis that billing identity moves to `RateScheme`. **Added `est_worker_time: DurationField(null=True, blank=True)` to `TaskBase`** — explicitly noted as "for scheduling. Used by Task for calendar projection; PlanTask may leave null. Lives on TaskBase so no separate migration is needed when scheduling work begins." Scheduling/calendar UI was deferred. Stated rationale for keeping `Task` and `TaskCharge` split: "Keeping them separate makes it easier to evolve billing logic without touching the work model."

### `2026-04-19-billable-atoms-and-estimate-wizard-design.md`

Established the atom abstraction (`compute_amount(modifiers) -> Money`, `accounting_category`, `units`, `description`, source-pointer identity) shared by `TaskCharge` / `PlanCharge` (now `PlanTask`) and `Material` / `PlanMaterial`. Bleps are read-only detail under their task's atom; never claimed as atoms themselves. Estimate wizard mirrors the invoice wizard. Carry-over fires on Estimate-accepted: `PlanCharge → TaskCharge`, `PlanMaterial → Material`. Includes the **2026-05-01 implementation delta**: `PlanCharge` was merged into `PlanTask`. The justification given for keeping `Task` / `TaskCharge` split on the real side after that change was "TaskCharge.actuals legitimately needs its own home."

### `2026-05-02-rate-scheme-billing-identity-design.md`

Promoted `RateScheme` to the unit of billing identity for labor: it owns rate, algorithm, modifiers, AC, and version lineage. Made schemes append-only once referenced (supersession via `replaced_by` / `replaced_at`). **Removed `accounting_category`, `rate`, `units`, `est_qty` from `Task`.** Made `TaskCharge` a required relationship for every `Task` (enforced via service paths and `Task.clean()`). Made `PlanTask.rate_scheme` and `PlanTask.est_qty` `NOT NULL`. Made `TaskTemplate.rate_scheme` and `TaskTemplate.default_billable_qty` `NOT NULL`. Refactored the invoice wizard to per-task atoms priced through `task.charge.compute()`. Introduced `RateSchemeFieldset.svelte` shared by PlanTaskModal, TaskModal, and SubtaskModal.

This is the doc whose work measurement gap this design addresses.

## The Work-Measurement Axis

The 2026-05-02 refactor cleanly resolved the **billing axis**. What it didn't name is the **work-measurement axis**: quantity and time, estimated and actual, used for scheduling, progress reporting, and estimate refinement. Currently those fields are scattered:

| Concern | Plan side | Real side |
|---|---|---|
| Estimated billable qty | `PlanTask.est_qty` (NOT NULL) | **missing** |
| Estimated worker time | `PlanTask.est_worker_time` | `Task.est_worker_time` |
| Actual billable qty | n/a (no actuals on plan) | `TaskCharge.actuals['qty']` (JSON, ENTERED_QTY only) |
| Actual elapsed time | n/a | Bleps (reverse FK) |

The real-side gap is the bug. Without `est_qty` on `Task`:

1. **Scheduling has no qty estimate to work from.** `apps/api/tasks/serializers.py:90` already has a workaround that reaches across `task.source_plan_task.est_qty` — but it only fires for ELAPSED_TIME schemes that came from a worksheet carry-over. Ad-hoc tasks (TaskModal, SubtaskModal, add-from-template) get nothing.
2. **`TaskTemplate.generate_task(job, est_qty)` accepts an est_qty argument and silently drops it** (`apps/estimates/models.py:445-459`). The qty is only stored when generating to a Worksheet (where it lands on PlanTask.est_qty).
3. **TaskModal and SubtaskModal stuff `est_qty` into `actuals`** (`TaskModal.svelte:80`, `SubtaskModal.svelte:40`: `actuals: estQty ? { qty: estQty } : {}`). Consequences:
    - For ELAPSED_TIME schemes, the value lands in a field that `RateScheme.get_actual_qty` ignores (it reads bleps). The user's estimate is silently lost.
    - For ENTERED_QTY schemes, `actuals.qty` at creation time is indistinguishable from "the worker entered this." The invoice wizard would happily generate a line item against an unworked task.
    - For FLAT_FEE, harmless.
4. **No estimate-vs-actuals reporting is possible.** "We're at 7 of 12 estimated" requires both numbers. Today the estimate is unrecoverable on the real side.
5. **Not every job has a worksheet.** Some jobs go straight to work; some have only a direct estimate. The `source_plan_task` workaround can't help those.

## The Bigger Restructure

Two questions sat in front of the field-restoration:

**Q1: Where should `est_qty` live on the real side — Task, TaskCharge, or TaskBase?**
**Q2: Why does TaskCharge still exist?**

The reasoning preserved in the docs for keeping TaskCharge separate boils down to two thin claims: "easier to evolve billing logic without touching the work model" (2026-04-19) and "actuals legitimately needs its own home" (2026-05-01). After 2026-05-02, most billing logic lives on `RateScheme`; `TaskCharge.compute()` is a 2-line wrapper. And `actuals` is a JSON dict that holds at most one `qty` value, only for ENTERED_QTY schemes. A typed `actual_qty: Decimal(null=True)` field captures the same data more cleanly.

The plan side already proved this argument when `PlanCharge` was merged into `PlanTask` on 2026-05-01: "no actuals analog, no per-charge lifecycle." The real side has actuals and Bleps, but Bleps are a separate model regardless of whether the parent is `Task` or `TaskCharge`. Once `actuals.qty` becomes a typed field, there's no remaining structural justification for the 1:1 split.

**Decision:** Dissolve TaskCharge. Move billing-config fields (`rate_scheme`, `active_modifiers`) onto Task. Replace `actuals` JSON with a typed `actual_qty` Decimal field. Add `est_qty` as a typed Decimal field. Plan/real symmetry is restored. PlanTask and Task share the same shape minus Task's lifecycle/hierarchy/Bleps.

## Architectural Claim

Work measurement and billing identity are distinct concerns that share a model. Every Task and PlanTask carries:

- **Billing config** — `rate_scheme` (FK), `active_modifiers` (JSON list)
- **Work measurement (estimate)** — `est_qty`, `est_worker_time`
- **Work measurement (actual)** — `actual_qty` (Task only); Bleps (Task only, reverse FK); the plan side has no actuals

`RateScheme` remains the unit of billing identity, exactly as 2026-05-02 specifies. This design does not weaken or alter that claim. It only changes which model the FK lives on (Task instead of TaskCharge) and adds the work-measurement fields that 2026-05-02 didn't account for.

## Model Changes

| Model | Add | Remove | Change |
|---|---|---|---|
| `TaskBase` | `est_qty: Decimal(null=True, blank=True)` | — | est_qty promoted from PlanTask onto the abstract base (nullable at DB level so Task can leave it unset; see "est_qty placement" below) |
| `Task` | `rate_scheme: FK(RateScheme, on_delete=PROTECT)`, `active_modifiers: JSONField(default=list, blank=True)`, `actual_qty: Decimal(null=True, blank=True)` | reverse `charge` relationship (drops with TaskCharge) | `rate_scheme` is `NOT NULL` (replaces "Task must have a TaskCharge" rule); `est_qty` inherited from TaskBase, left nullable |
| `PlanTask` | — | the model's own `est_qty` field declaration (now inherited from TaskBase) | `clean()` enforces `est_qty is not None` at the application layer; see "est_qty placement" |
| `TaskCharge` | — | **dropped entirely** | the `task_charges` table goes away |
| `RateScheme` | — | — | reference checks update from `TaskCharge` to `Task` (see RateScheme Effects); model fields unchanged |
| `TaskTemplate` | — | — | unchanged |

### `est_qty` placement

`est_qty` lives on `TaskBase` (abstract) so PlanTask and Task share one declaration. The DB column is nullable on both subclasses — but **only because Task needs it to be**. PlanTask requires `est_qty` to be set; the requirement is enforced in code, not in the schema:

```python
class PlanTask(TaskBase):
    def clean(self):
        super().clean()
        if self.est_qty is None:
            raise ValidationError({
                'est_qty': 'Required: every PlanTask must have an estimated quantity.',
            })
```

This is the same two-layer pattern Task uses today for "every Task must have a TaskCharge" (DB allows the missing relationship; `Task.clean()` rejects it). Service-layer paths that create PlanTasks (worksheet add-task, add-from-template, copy-from-worksheet, supersede-worksheet) must supply `est_qty`. Defensive `clean()` catches any code path that forgets.

`Task.est_qty` is genuinely optional. A Task created mid-job ("make a phone call to the customer") may have no meaningful estimate; it stays `None` and contributes 0 to atom totals.

`PlanTask.rate_scheme` stays DB-level `NOT NULL`. `Task.rate_scheme` is DB-level `NOT NULL`. Every work item must reference a scheme — that part of 2026-05-02 stands. Only `est_qty` shifts from schema-enforced to code-enforced on the plan side, and only because the Task side needs the column nullable.

### Why not declare `est_qty` separately on each subclass

Considered. The alternative is keeping the field declaration off TaskBase and writing it twice — `NOT NULL` on PlanTask, nullable on Task. That preserves the database-level constraint on PlanTask but duplicates the field declaration and breaks the principle that TaskBase carries the shared work-item shape (which is why `est_worker_time` lives there too). The two-layer (schema + clean()) pattern is already in use on Task today; using it consistently keeps TaskBase cohesive.

### `actual_qty` semantics

| Algorithm | `actual_qty` meaning |
|---|---|
| ELAPSED_TIME | unused (qty derived from Bleps); should stay null |
| ENTERED_QTY | what the worker entered; null until entered |
| FLAT_FEE | unused (qty is implicit 1); should stay null |

The compute logic in `RateScheme.get_actual_qty(task)` updates from `task.charge.actuals.get('qty', 0)` to `task.actual_qty or 0` for ENTERED_QTY. ELAPSED_TIME / FLAT_FEE branches are unchanged.

### `est_qty` semantics

| Algorithm | `est_qty` meaning |
|---|---|
| ELAPSED_TIME | estimated billable hours (often equals est_worker_time but doesn't have to) |
| ENTERED_QTY | estimated piece/minute count (laser case: estimated billable laser-minutes, distinct from operator est_worker_time) |
| FLAT_FEE | implicitly 1 if used; usually left null |

`est_qty` is **never** modified by work activity. It stays as the estimate. `actual_qty` (and Bleps) capture what happened. This separation is what enables estimate-vs-actuals reporting.

## RateScheme Effects

Minor — mostly simplifying. No model schema change.

| Concern | Today | After |
|---|---|---|
| `is_referenced()` | checks PlanTask, **TaskCharge**, TaskTemplate | checks PlanTask, **Task**, TaskTemplate |
| `reference_counts()` | exposes `task_charge_count` | exposes `task_count` |
| `get_actual_qty(task)` for ENTERED_QTY | `task.charge.actuals.get('qty', 0)` plus Decimal-coercion comment | `task.actual_qty or Decimal('0')` (typed) |
| Compute / effective_rate / modifiers / supersede / append-only / PROTECT cascade | unchanged | unchanged |
| Outdated-schemes UI | shows TaskCharge count | shows Task count |

The supersede flow, frozen-once-referenced rules, AC pass-through, scheme picker filtering, and template-superseded guard from 2026-05-02 all remain in force.

## Atom Interface Migration

`TaskCharge.compute_amount` moves to `Task`. `PlanTask.compute_amount` already exists. Both atoms become first-class on the work-item model — symmetric with `Material` / `PlanMaterial`.

The invoice wizard's per-task atom (designed in 2026-05-02 and shipped) already keys `InvoiceLineItemSource` rows on Task PKs (`SOURCE_TASK` with `source_pk = task.pk`) — confirmed in `apps/invoicing/models.py:191`. **No migration of source rows is needed.** Only the compute path changes: `task.charge.compute()` becomes `task.compute_amount()`. Same for the per-task atom assembly in `InvoiceWizardService.get_source_pool` and the `_atom_*` helpers — they switch from `task.charge.<x>` to `task.<x>` directly.

The estimate wizard's per-PlanTask atom (designed in 2026-04-19) is unchanged.

## Carry-Over and Template-Add Behavior

### Worksheet → Job carry-over (`AtomCarryOverService._carry_over_plan_tasks`)

For each PlanTask:

```
Task.objects.create(
    job=job, name=pt.name, description=pt.description,
    source_plan_task=pt,
    rate_scheme=pt.rate_scheme,
    active_modifiers=list(pt.active_modifiers or []),
    est_qty=pt.est_qty,                       # ← carries forward
    est_worker_time=pt.est_worker_time,       # ← carries forward
    actual_qty=None,                          # explicitly empty
)
```

The current code stuffs `pt.est_qty` into `TaskCharge.actuals['qty']` for ENTERED_QTY schemes. After this design, it carries to `Task.est_qty` for **all** schemes, and `actual_qty` is left null until the worker enters it.

### Direct-estimate line-item carry-over (`_create_task_from_line_item`)

For a line item with a `source_template`:

```
Task.objects.create(
    job=job, name=template.template_name, description=template.description,
    source_template=template,
    rate_scheme=template.rate_scheme,
    active_modifiers=list(template.default_active_modifiers or []),
    est_qty=line_item.qty,                    # use the LI's qty as the estimate
    est_worker_time=None,                     # template doesn't carry one yet
    actual_qty=None,
)
```

Today this path also stuffs `line_item.qty` into `actuals` for ENTERED_QTY only. After this design, est_qty is set for all algorithms.

### `TaskTemplate.generate_task(job, est_qty, ...)`

The currently-discarded `est_qty` argument becomes load-bearing:

```
Task.objects.create(
    job=container,
    name=self.template_name, description=self.description,
    rate_scheme=self.rate_scheme,
    active_modifiers=list(self.default_active_modifiers or []),
    est_qty=est_qty,                          # ← was silently dropped
    ...
)
```

For the EstWorksheet branch, behavior is unchanged (PlanTask already takes est_qty).

## UI: Task-Add Modal Convergence

### Current state (problems)

Three modals — TaskModal, SubtaskModal, PlanTaskModal — each ~150 lines, ~90% the same logic. SubtaskModal lacks the freeform/template toggle. The "Freeform vs From Template" radio toggle hides name/description in template mode. `RateSchemeFieldset` (shared) hard-requires `est_qty`. `est_worker_time` has no UI input anywhere.

### New shape

Two entry buttons replace the radio toggle:

- **[Add Task From Template]** → opens the modal in template mode; primary input is a template dropdown.
- **[Add Manual Task]** → opens the modal in manual mode; primary input is a rate-scheme dropdown.

This removes the toggle and makes each path's "first thing you do" obvious. The modal beneath both buttons is a single shared component: **`WorkItemForm.svelte`**.

#### `WorkItemForm.svelte` shape

The primary picker — Template in one mode, RateScheme in the other — sits at the top in both modes. The modes are structurally parallel: the top picker drives downstream defaults, name/description follow, modifiers (which depend on the chosen scheme) sit below, then qty and worker-time at the bottom.

```
TEMPLATE MODE
─────────────
Template *           [ Hourly Labor — assembly  ▼ ]
Name *               [pre-filled from template, editable]
Description          [pre-filled from template, editable]
Rate scheme:         Hourly Labor — $50/hour    (locked, from template)
Modifiers            ☐ messy  ☐ rush             (defaults from template)
Estimated qty        [12]                        (pre-filled from template default; editable; OPTIONAL)
Estimated worker time   [__h __m]                (NEW input; OPTIONAL)

[Save] [Cancel]


MANUAL MODE
───────────
Rate scheme *        [ Hourly Labor  ▼ ]
Name *               [____________________________]
Description          [____________________________]
Modifiers            ☐ messy  ☐ rush
Estimated qty        [____]                      (in scheme units; OPTIONAL)
Estimated worker time   [__h __m]                (OPTIONAL)

[Save] [Cancel]
```

Both flat dropdowns. Templates and rate schemes are not categorized in the picker — until the count grows enough to warrant it, the flat list is faster to use.

The Template picker (template mode) and the Rate scheme picker (manual mode) occupy the same top slot — they are the equivalent "primary pick that drives downstream defaults" in their respective modes. Putting them in the same position avoids the user feeling like they're filling out two structurally different forms.

#### Field requirements

- `name`: required (always).
- `rate_scheme`: required (always; in template mode, locked to the template's scheme).
- `est_qty`: **required on the worksheet (plan) side, optional on the job (real) side.** The form enforces this client-side based on context. Server-side, `PlanTask.clean()` rejects null and `Task` accepts it. Today's `RateSchemeFieldset` hard-requires the field everywhere; that gets relaxed for the Task context.
- `est_worker_time`: optional (new field, no current UI).
- `active_modifiers`: optional, defaults from template in template mode.

#### Where the form is used

| Context | Mounted by | Submits to |
|---|---|---|
| Worksheet (PlanTask) | the worksheet view's "Add Task" buttons | `POST /api/est-worksheets/<id>/tasks/` (manual) or `add-from-template/` (template) |
| Job (Task) | the job view's "Add Task" buttons | `POST /api/jobs/<id>/tasks/` (manual) or `add-from-template/` (template) |
| Subtask of a Job Task | the task detail view's "Add Subtask" button | `POST /api/tasks/<parent_id>/subtasks/` (manual) — template flow not currently supported for subtasks; preserve current behavior |
| Edit existing Task / PlanTask | the row's edit affordance | `PATCH` to the resource — locked to manual-mode editing of the existing fields |

PlanTaskModal, TaskModal, and SubtaskModal are deleted; `WorkItemForm.svelte` replaces them. `RateSchemeFieldset.svelte` is folded into `WorkItemForm` (or kept as a small subcomponent, depending on how clean the extraction is — implementation detail).

The two-button entry pattern makes manual vs template a directly-clickable choice rather than a hidden modal toggle. It also removes the awkward "name/description hidden in template mode" behavior — both fields are always shown, just pre-filled in template mode.

#### What this fixes

- `actuals: { qty: estQty }` hack is **gone** from the modals. They send `est_qty` as `est_qty`. Task creation paths set `est_qty` cleanly; `actual_qty` stays null until the worker enters it on TaskDetailPage.
- `est_worker_time` finally has a UI input.
- One form to maintain, not three.
- The template / manual choice is visible up front instead of buried in a radio toggle.

### Updated TaskDetailPage charge section

The "Actual qty" input on TaskDetailPage (which today reads/writes `task.charge.actuals.qty`) reads/writes `task.actual_qty` after the migration. Visible only for ENTERED_QTY schemes. UI shape unchanged.

## API Changes

### Endpoints removed

- Any TaskCharge-specific endpoints. Today's code does not appear to expose `/charge/` REST resources directly (TaskCharge is created server-side as part of Task creation), so this is mostly internal cleanup.

### Endpoints modified

- `POST /api/jobs/<id>/tasks/` (and the SubtaskModal equivalent) accept `rate_scheme`, `active_modifiers`, `est_qty`, `est_worker_time`, `actual_qty` as direct fields on the Task. No longer accept `actuals: { qty: ... }` (the field is gone).
- `POST /api/jobs/<id>/add-from-template/` already accepts `est_qty`; now it actually stores the value rather than discarding it. Also accepts `active_modifiers` and `est_worker_time` overrides.
- `POST /api/est-worksheets/<id>/tasks/` and `add-from-template/` continue to accept `est_qty`, gain `est_worker_time` acceptance.
- `GET` payloads on Task/PlanTask flatten: `rate_scheme`, `active_modifiers`, `est_qty`, `est_worker_time`, `actual_qty` are top-level fields, not nested under `charge`.

### Serializer cleanup

- `TaskSerializer.charge` nested representation is removed. The fields it surfaced (`rate_scheme`, `active_modifiers`, computed charge, etc.) move to top-level on the Task serializer.
- `TaskSerializer.estimated_hours` workaround (`apps/api/tasks/serializers.py:90`) reading through `task.source_plan_task.est_qty` is **removed**. Replace with direct `task.est_qty`. The "ELAPSED_TIME only" gating goes away too — the field is meaningful for any scheme; consumers interpret it via the scheme's `unit_label`.

## Migration Philosophy

Pre-production: correctness over preservation. The existing dev DB can be hand-fixed or reseeded. Phased to leave a manual-fix window, following the 2026-05-02 pattern.

### Phase A — additive

- Add columns: `Task.rate_scheme` (nullable), `Task.active_modifiers`, `Task.est_qty`, `Task.actual_qty`.
- Backfill from TaskCharge: copy `rate_scheme`, `active_modifiers`, `actuals['qty']` (if present) to the new Task fields.
- Existing `task.charge` reverse-OneToOne keeps working; new code reads from Task fields.
- Modal redesign **does not ship in Phase A**. PlanTaskModal/TaskModal/SubtaskModal continue to function against the old shape.

### Pause — manual data fix window

- Confirm every Task has `rate_scheme` set (via the Phase A backfill).
- For any Tasks where `actuals` had unexpected keys (e.g. junk data), the developer reviews and reconciles.
- Optional read-only `check_task_data` management command can validate the dataset is ready for Phase B.

### Phase B — constraint tighten and cleanup

- Make `Task.rate_scheme` `NOT NULL`.
- Drop `Task.clean()`'s `hasattr(self, 'charge')` requirement.
- Drop the `TaskCharge` model and `task_charges` table.
- (`InvoiceLineItemSource` source rows already key on Task PKs via `SOURCE_TASK` — no migration needed.)
- Update `RateScheme.is_referenced()` and `reference_counts()` to query Task instead of TaskCharge.
- Update `RateScheme.get_actual_qty()` to read `task.actual_qty`.
- Move `compute_amount` from TaskCharge to Task. Update wizard atom callsites.
- Move `est_qty` field declaration from `PlanTask` to `TaskBase` (nullable). DB-level effect: `PlanTask.est_qty` constraint relaxes from `NOT NULL` to nullable. Existing PlanTask rows already have non-null values, so no data backfill needed. **Add `PlanTask.clean()` enforcement** rejecting null at the application layer — this preserves the worksheet-side requirement without depending on a DB constraint that Task can't honor.
- Ship the `WorkItemForm.svelte` modal redesign and delete TaskModal / SubtaskModal / PlanTaskModal.
- Update `TaskTemplate.generate_task` to actually store the `est_qty` argument when the container is a Job.
- Update `AtomCarryOverService` paths (`_carry_over_plan_tasks`, `_create_task_from_line_item`) to set `est_qty` on Task directly instead of stuffing into actuals.
- Remove the `_estimated_hours` workaround in `TaskSerializer`.
- Remove the carry-over's ENTERED_QTY-only special case in `_carry_over_plan_tasks`.

## Tests

Following the project's TDD convention. New / updated tests at minimum:

- `test_task_charge_dissolution.py` — Task creation paths persist `rate_scheme`, `active_modifiers`, `est_qty`, `actual_qty` on Task directly. No TaskCharge model exists.
- `test_atom_compute_amount.py` — `Task.compute_amount` returns the same numbers `TaskCharge.compute_amount` did. Existing PlanTask atom tests unchanged.
- `test_rate_scheme.py` — `is_referenced()` / `reference_counts()` updated to count Tasks. `get_actual_qty` reads typed field.
- `test_carry_over.py` — `est_qty` carries from PlanTask to Task for all algorithms (not just ENTERED_QTY). `actual_qty` left null on carry-over.
- `test_task_template_generate_task.py` — `generate_task(job, est_qty)` actually stores the est_qty.
- `test_invoice_wizard_per_task_atoms.py` — atom is the Task, not the TaskCharge. `InvoiceLineItemSource` points to Task.
- `test_plan_task_est_qty_required.py` — `PlanTask.clean()` rejects null `est_qty` (covers worksheet add-task, add-from-template, copy-from-worksheet, supersede). `Task.clean()` accepts null `est_qty`. Confirms the asymmetric application-layer enforcement holds across every PlanTask creation path.
- `test_work_item_form.svelte` (frontend) — template mode pre-fills name/scheme/qty/modifiers from template; manual mode allows free entry; on a Worksheet context `est_qty` is required (form refuses save), on a Job context it's optional; `est_worker_time` optional in both contexts; `rate_scheme` always required.
- Migration tests confirm Phase A backfill copies fields correctly and Phase B drops the table without orphaning data.

Detailed test enumeration is the implementation plan's job.

## Permissions

Unchanged. `IsAuthenticated` reads, `CanManageJobs` for Task structural changes, `CanManageJobs` for scheme/modifier edits, `IsAuthenticated` for actual_qty entry on a worker's own Task (matches today's "enter actuals" permission). The 2026-05-02 permissions table holds.

## Out of Scope

- Scheduling / calendar UI itself. This design only ensures the data exists. Calendar projection, capacity views, due-date promising — separate design.
- Per-task due dates. Currently only Job has `due_date`. Worth a future design but unrelated to work measurement structure.
- Task dependencies / precedence (X must finish before Y). Bigger feature.
- Resource (machine/station) assignment beyond person via `assignee`.
- Profitability and `User.pay_rate`. Explicitly deferred elsewhere.
- Worker-friendly default-scheme quick-add (the 2026-05-02 "Known Future Need").
- Setup-vs-production task split. Already handled by the convention of separate setup tasks.

## Later

Items adjacent to this design that aren't in scope but are likely to come up sooner rather than later. Captured here so future designs can reference them by name.

### Default rate scheme for quick worker-side task add

A `Configuration` key (e.g. `default_worker_rate_scheme_id`) lets `WorkItemForm` skip the rate-scheme picker entirely when the user lacks `can_manage_jobs`. The form would either default the scheme silently and hide the picker, or show it pre-selected and locked. Pairs with the 2026-05-02 "Known Future Need" for worker-friendly mid-job task creation.

### Estimate-vs-actuals reporting

Once `est_qty` and `actual_qty` (or Bleps) coexist on Task, a per-job and per-template variance report becomes trivial. "How accurate are our estimates for this kind of work?" feeds back into `TaskTemplate.default_billable_qty` tuning. A management command or admin view that surfaces the variance could ship without further model changes.

### Template tuning loop

`TaskTemplate.default_billable_qty` could auto-suggest updates based on rolling-average actuals from completed Tasks created from the template. A "suggested update" UI in the TaskTemplate manager, not an automatic write. Out of scope here, but the data is now in place.

### Per-task due date

Many real shops want milestone tasks ("polish must be done by Tuesday so packaging can start Wednesday"). Currently only Job has a `due_date`. Adding `Task.due_date` is a small change but interacts with scheduling design and dependencies; deserves its own thinking.

### Task dependencies (precedence)

"X must finish before Y" — currently only `sort_order` exists, which is a hint not a constraint. Real scheduling needs explicit precedence edges. Bigger feature; flagging as a future direction.

### Resource (non-person) assignment

`Task.assignee` is a User. A laser job is often "assigned to the laser" with a separate operator. A `Task.resource` FK to a future `Resource` model (machine/station) would parallel `assignee`. Out of scope; flagging.

### Categorized scheme/template pickers

Today's flat dropdowns are deliberate per this design. As shops accumulate schemes, grouping by AC or recently-used signal becomes worth the complexity. Revisit if real-world use shows the lists getting long.

### Auto-fill `est_worker_time` when scheme units are hours

When the chosen rate scheme's `unit_label` represents hours, `est_qty` and `est_worker_time` are typically the same number. The form could pre-fill `est_worker_time` from `est_qty` automatically in that case, with the user free to override. Tricky because `unit_label` is a configured value (per `2026-03-30-configurable-units.md`) rather than a hard-coded `"hour"` string — the form would need to know which configured unit, if any, represents hours-worth-of-work. Possible shapes: a dedicated config key (`hours_unit_label`) listing the unit label(s) that mean "hour"; or a flag on the unit definitions themselves marking which is the canonical hour unit. Worth a small design pass on its own when picked up.

### Multiple kinds of time

Beyond `est_worker_time` (operator attention) and billable qty, a third axis exists for jobs with unattended work: **wall-clock lead time** ("the laser runs for 90 min unattended"). Scheduling that uses both worker-attention capacity and wall-clock-lead-time for due-date promising would want a third estimate field. Not now.

### Setup-vs-production decomposition on a single Task

This design treats setup and production as separate Tasks (the existing convention works). If we ever want both as a structured pair on one Task — e.g. `setup_worker_time` + `production_worker_time` — that's a future field-set discussion. Flagging only because it came up.

## Open Questions for Implementation Plan

- Whether to keep `RateSchemeFieldset.svelte` as a sub-component of `WorkItemForm.svelte` or fold it in entirely. Implementation cleanliness call.
- Exact JSON shape for `est_worker_time` on the wire. Django's `DurationField` accepts ISO 8601 strings (`'PT45M'`) or `HH:MM:SS`. The frontend likely wants `{hours, minutes}` or total minutes — pick one convention and stick to it.
- Whether to deprecate the `actuals` JSON field gracefully or hard-cut. Pre-production says hard-cut.
- Whether the Phase A backfill should also populate `est_qty` from `actuals['qty']` for tasks created via the buggy modal path, or leave them null and let the user re-enter. Likely populate, with a note.
- Whether `add-from-template` for subtasks should be added at the same time. Currently `SubtaskModal` is manual-only; the WorkItemForm convergence makes adding template support to subtasks nearly free, but it's not strictly required by this design.

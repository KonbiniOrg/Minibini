# Job Duplication — Design Spec

_Spec date: 2026-06-01 · Branch: feature/portal (or a dedicated `feature/job-duplication`)_

## 1. Goal

One action that copies an existing Job into a **new** Job, sparing the user from
re-entering deliverables, tasks, and materials for repeat or similar work. The user
picks the new Job's customer and chooses one of two outcomes: an **immediately
approved** ready-to-work clone, or a **draft that requires a new estimate** (re-quote).

Invoices, POs, bills, estimates, shipments, change orders, and history from the source
Job are **never** copied.

## 2. Background — the two layers

This codebase has two parallel layers for the same conceptual work:

- **Planning layer** — `EstWorksheet` holds `PlanTask`s and `PlanMaterial`s ("what we quote").
- **Execution layer** — the `Job` holds `Task`s and `Material`s directly ("what we do").

Normal flow: Worksheet → Estimate → on accept, plan atoms **carry over** into execution
Tasks/Materials on the Job (`AtomCarryOverService`).

The duplicate feature always **sources work from the source Job's execution layer** (its
`Task`s / `Material`s) — never from its old worksheet. Rationale: the execution layer is
guaranteed to exist (not every job has a worksheet, and tasks can be added during
execution that never existed as plan atoms), and "what we actually built" is the truthful
basis for a repeat order. The two outcomes differ only in which layer the copy **lands in**.

## 3. User-facing flow

- **Entry point:** a **"Duplicate…"** link on the SPA Job detail page → a dedicated
  intermediate route `#/jobs/:id/duplicate`. SPA-only — the deprecated Django HTML job
  views are not touched.
- **Eligibility:** any Job may be duplicated regardless of status (draft, completed,
  cancelled, …).
- **Intermediate page** (`DuplicateJobPage.svelte`) asks two things:
  1. **Customer** — a contact picker pre-filled with the source Job's `contact`, freely
     editable to any contact.
  2. **Path** — a radio: **Immediately approved** vs **Requires a new estimate**.
- **Advisory** (always shown, static text near the path radio): _"Immediately-approved
  reuses the original's pricing as-is. If rates or material prices may have moved, choose
  'Requires a new estimate' to re-quote."_ No price-drift **detection** is built — this
  is a deliberate, permanent scope decision (not a deferred follow-up).
- A **Duplicate** button submits. On success the SPA redirects to the new Job
  (`#/jobs/:newId`).

## 4. What always copies (both outcomes)

**Job metadata onto the new Job:**

| Field | Behavior |
|---|---|
| `name` | Copied verbatim |
| `description` | Copied verbatim |
| `contact` | Set to the chosen contact (pre-filled = source's) |
| `job_number` | **Freshly generated** — handled by `JobService.create_job` (which calls `NumberGenerationService.generate_next_number('job')`) |
| `created_date` | Fresh (`timezone.now()`, the model default) |
| `accent_color` | **Regenerated** — left `None` so `Job.save()` auto-assigns a fresh one |
| `customer_po_number` | **Not** copied (customer issues a fresh PO) |
| `due_date` | **Not** copied (new schedule) |
| `hold_reason` | Not copied (empty) |
| `status` | Set per outcome (§5 / §6) |

**Deliverables:** each source `Deliverable` is recreated on the new Job via
`DeliverableService.create`, preserving `description`, `qty_ordered`, `units`, and relative
order (`sort_order`). No shipment/fulfillment state exists on a brand-new Job, so nothing
is anchored.

**Work atoms** are always sourced from the source Job's execution `Task`s / `Material`s.
**Tasks are reset** when copied: fresh `status=pending`, **no bleps, no logged time, no
assignee**, and the following execution-only fields cleared:

- `assignee = None`, `worker_queue = None`, `blocked_reason = ''`
- `actual_qty = None` (worker-entered actual)
- `status = pending`
- `source_template = None`, `source_plan_task = None`

Descriptive + billing fields that **do** carry: `name`, `description`, `sort_order`,
`est_worker_time`, `est_qty`, `rate_scheme`, and `active_modifiers` (copied through
`copy_active_modifiers()` from `apps.jobs.models` to preserve the dict-vs-list modifier
shape, matching `create_new_version` / `copy_from_worksheet`).

**Materials** carry `description`, `quantity`, `units`, `unit_cost`, `sell_price`,
`price_list_item`, `accounting_category`, and their **task attachment** (task-less
materials stay task-less). Execution/inventory state is **reset/dropped**:
`consumption_state = pending`, `restocked_qty = 0`, `po_line_item = None`,
`source_plan_material = None`.

**Never copied (either outcome):** estimates, worksheets-from-source, invoices, POs,
bills, shipments, `ShipmentItem`s, change orders, `DeliverableSnapshot`s, history entries,
bleps.

## 5. Outcome A — Immediately approved

The new Job reaches `approved` by **walking the legal transitions through the service**,
never by a direct write — so all current and future `update_job` side effects fire and we
match existing precedent (see below). Order of operations, all inside one
`transaction.atomic()`:

1. Create the Job at the default `status=DRAFT` via `JobService.create_job(...)` (this
   generates the job number and assigns the accent color).
2. Copy deliverables; copy Tasks **directly onto the Job** as execution `Task`s (reset per
   §4, hierarchy preserved per §7); copy Materials as execution `Material`s preserving task
   links.
3. Create **earmarks** for the copied materials via
   `InventoryService.create_earmarks_for_job(new_job)` (one call after all materials exist
   — mirrors `copy_from_worksheet`).
4. Advance the status: `JobService.update_status(job.pk, STATUS_SUBMITTED)` then
   `JobService.update_status(job.pk, STATUS_APPROVED)`. The `approved` hop sets `start_date`
   via `Job.save()`'s real side-effect path. Write a `HistoryEntry` per hop (action e.g.
   `"Duplicated from <source job_number>"`).

**Why walk through `submitted` rather than create directly at `approved`:**
`draft → approved` is not a legal transition (`VALID_TRANSITIONS`: `draft→submitted→approved`),
and creating directly at `approved` would **bypass** `Job.save()`'s transition logic and the
`start_date` side effect (those only run on update, when `self.pk` exists). Routing through
`update_job` keeps us inside every guard (open-blep, change-order, loose-materials,
earmark-release) and any future side effect added there. `SUBMITTED` itself carries **no**
side effect (no signal — `jobs/signals.py` is empty — and no gate); it is purely the
mandatory stepping-stone. This is **exactly** what the estimate-acceptance flow already does
in `apps/estimates/signals.py:96-116` (two-hop `update_job` + `HistoryEntry` per hop), so we
follow that precedent. The transient `submitted` state lives entirely inside the atomic
block and is never observable.

- **No estimate, no worksheet.** Deliverables remain **editable** (no estimate → editable
  in any status, per `DeliverableService.is_editable`) until they anchor on shipment.

Result: a ready-to-work job. The user tweaks quantities, then advances to `in_progress`.

## 6. Outcome B — Requires a new estimate

- New Job created at **`status=DRAFT`** (`start_date` stays null).
- A fresh `EstWorksheet` is created on the new Job: `version=1`, `status=DRAFT`,
  `parent=None`, `estimate=None`. (It is a new worksheet, **not** a revision of anything.)
- Source `Task`s are mapped to `PlanTask`s on that worksheet; source `Material`s are
  mapped to `PlanMaterial`s, preserving the task attachment
  (`PlanMaterial.plan_task` → the corresponding new `PlanTask`; task-less → `plan_task=None`).
- **No earmarks** (earmarks happen later, on carry-over). **No estimate copied** — the user
  runs the normal re-quote → send → accept → carry-over flow, which then creates the
  execution Tasks/Materials.

### 6.1 `est_qty` fallback (Task → PlanTask)

`PlanTask.clean()` **requires `est_qty` to be non-null**, but `Task.est_qty` is nullable.
When a source Task has no `est_qty`, fall back explicitly (note: `Decimal('0.00')` is
falsy, so use `is not None` checks, not `or`):

```
est_qty = task.est_qty   if task.est_qty   is not None
     else task.actual_qty if task.actual_qty is not None
     else Decimal('0.00')
```

A `0.00` placeholder is acceptable because Outcome B is a draft the user re-quotes; they
set real quantities during the estimate pass. Tasks that came from carry-over normally
already carry `est_qty`, so the fallback is the uncommon path.

### 6.2 Hierarchy note

`PlanTask` has **no `parent_task`** (planning layer is flat). Subtask hierarchy is
therefore **flattened** in Outcome B — `sort_order` is preserved so ordering survives, but
parent/child nesting does not. (Outcome A preserves hierarchy — see §7.)

## 7. Subtask hierarchy (Outcome A only)

`Task.parent_task` (self-FK) can nest tasks. Outcome A preserves it with a **two-pass
remap**: create every new Task first (building an old-`task_id` → new-`Task` map), then set
each new Task's `parent_task` from the map. Materials attach to their remapped Task.

## 8. Backend

- **Service:** `JobService.duplicate_job(source_job, *, contact, path)` in
  `apps/jobs/services.py`, wrapped in `transaction.atomic()`. `path` is `'approved'` or
  `'estimate'`. Returns the new `Job`.
  - Creates the Job at `draft` via `JobService.create_job` (number + accent handled there).
  - Delegates material creation to `MaterialService.create_on_job` (Outcome A) and creates
    `PlanMaterial`/`PlanTask` directly (Outcome B, as `create_new_version` does).
  - Outcome A then advances `submitted → approved` via `JobService.update_status` (two hops,
    `HistoryEntry` each); `start_date` falls out of the `approved` transition. Outcome B
    leaves the Job at `draft`. **No status is ever written directly** — all transitions go
    through the service.
- **API:** `POST /api/jobs/{id}/duplicate/` — a `@action` on `JobViewSet`.
  - Request body: `{ "contact_id": <int>, "path": "approved" | "estimate" }`.
  - Response: `{ "job_id": <new id> }` (so the SPA can redirect). DELETE-style 200-with-JSON
    convention is irrelevant here; this is a POST returning 200/201 with JSON.
  - **Permission:** `IsAuthenticated` + `CanManageJobs` (duplicating creates jobs,
    worksheets, tasks). `ValidationError` from the service → 400.
- **No new migration** — no schema changes. The feature is pure orchestration over
  existing models.

## 9. Frontend (SPA)

- `routes/jobs/DuplicateJobPage.svelte` mounted at `#/jobs/:id/duplicate`.
  - Loads the source Job (for the pre-filled contact + a "Duplicating: JOB-…" header).
  - Contact picker (reuse the existing contact-select component/endpoint), pre-selected to
    the source's contact.
  - Path radio (approved / estimate) + the static advisory text (§3).
  - **Duplicate** button → `POST …/duplicate/` → redirect to `#/jobs/:newId`.
  - Errors surface via the standard `lib/api.js` overlay.
- A **"Duplicate…"** link added to the Job detail page header/action area.

## 10. Testing (TDD)

Service-level (`tests/`):

- **Outcome A:** new Job is `approved` with a `start_date` set (proving the transition
  fired, not a hand-written value); a `HistoryEntry` exists for each of the submitted +
  approved hops; tasks copied with reset fields (pending, no assignee/bleps/actual_qty);
  materials copied with task links and reset inventory state; **earmarks created**; subtask
  hierarchy preserved; deliverables copied; **no** estimate/worksheet/PO/invoice on the new
  job. (The whole operation is atomic — a failure mid-copy leaves no partial job.)
- **Outcome B:** new Job is `draft`; a fresh `EstWorksheet` v1/draft/no-parent/no-estimate
  exists; PlanTasks/PlanMaterials mapped with task attachment preserved; **no earmarks**;
  `est_qty` fallback when source Task lacks one; hierarchy flattened but order preserved.
- **Both:** job number freshly generated and unique; `accent_color` regenerated;
  `customer_po_number`/`due_date`/`hold_reason` not copied; chosen contact applied;
  `active_modifiers` shape preserved; source Job left unmodified.
- **Edge:** source Job with zero tasks/materials/deliverables → empty-but-valid duplicate.

API-level: permission enforcement (`CanManageJobs` required; `IsAuthenticated`-only user
gets 403), happy-path payload returns `{job_id}`, bad `path`/`contact_id` → 400.

Per CLAUDE.md: write failing tests first; run via `python manage.py test` (separate test
DB). One test runner at a time.

## 11. Docs to update (same session as implementation)

- `docs/designs/jobs-tasks-and-worksheets.md` — add a "Job duplication" subsection
  (the two outcomes, execution-layer sourcing, reset rules, earmark behavior, endpoint).
- `docs/designs/users-and-permissions.md` §3 — add the `POST /api/jobs/{id}/duplicate/`
  row under `CanManageJobs`.
- Confirm nothing in `data-constraints.md` needs a new invariant (the feature introduces
  none; no-estimate-job deliverable editability is already documented in
  `jobs-tasks-and-worksheets.md` §12.2).

## 12. Out of scope / parked

- **Price-drift detection** — dropped permanently (advisory text only). Not a follow-up.
- **Harder deliverable freeze for no-estimate jobs** — accepted as-is for now (anchoring is
  the only freeze). Tracked in `docs/designs/LATER.md` ("Deliverable freeze under the
  no-estimate case", added 2026-06-01) for possible later revisit.

## 13. Key references

- `apps/jobs/models.py` — `Job` (transitions `99–108`, save side effects `150–181`),
  `TaskBase`/`PlanTask`/`Task` (`196–399`), `copy_active_modifiers`.
- `apps/inventory/models.py` — `MaterialBase`/`PlanMaterial`/`Material` (`101–297`).
- `apps/jobs/services.py` — `copy_from_worksheet` (`588–642`, earmark + material pattern),
  `create_job` (`382`), `update_job`/`update_status` (`396–483`, the status-transition
  side-effect dispatcher).
- `apps/estimates/signals.py` (`96–116`) — the **precedent** for the `draft→submitted→approved`
  two-hop walk with a `HistoryEntry` per hop that Outcome A mirrors.
- `apps/estimates/models.py` — `EstWorksheet.create_new_version` (`332–375`, the clone
  pattern this mirrors).
- `apps/inventory/services.py` — `MaterialService.create_on_job` (`376`),
  `InventoryService.create_earmarks_for_job` (`254`).
- `apps/deliverables/services.py` — `DeliverableService.is_editable` (`52`), `create`.

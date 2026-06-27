# Phase 5 — Combine the Tasks & Materials pillar

> REQUIRED SUB-SKILL when executing: superpowers:subagent-driven-development.
> Design draft §8 ("The Tasks & Materials pillar") + §14 step 4. Frontend-only,
> low-risk, separable from the estimate-pillar work.

**Goal:** Replace the job overview's *separate* **Tasks** and **Materials** (which
already includes Expenses) accordion sections with **one "Tasks & Materials"
pillar** that mirrors the main Task View — i.e. the job's live billable-atom family
(Tasks + Materials + Expenses), exactly what the Invoice projects from.

**Depends on:** nothing hard; can ship anytime. Touches JobDetail (coordinate with
the user's process rework). If the **Fee** atom is ever built (design §15.1), it
slots into this pillar beside Expenses.

## Global constraints
- Frontend-only. No model/endpoint changes. Svelte 5 runes. Never write the dev DB.
  Tests: `cd frontend && npm run test:run`.

## Reference (from exploration)
- `frontend/src/components/jobs/JobDetail.svelte`: `VALID_SECTIONS` (~L468) includes
  `'tasks'` and `'materials'`; **Tasks** pillar inline table (~L826–930, uses
  `jobTasks` ~L269, "View task list →" + "Copy tasks from worksheet"); **Materials**
  pillar inline tables (~L932–1043, `jobMaterials` ~L465, `looseExpenses` ~L30,
  `expenseByMaterial` ~L31). Expenses are already folded into the Materials pillar.
- `frontend/src/components/TaskTree.svelte` = the **reusable** Task View layout
  (used by `JobTaskListPage.svelte` and `TaskDetailPage.svelte`): nested tasks →
  materials (● marker) → subtasks, job-level materials, loose expenses, columns
  (Name, Assignee, Status, Units, Est Qty, Actual, Sell Price, Total) + grand total.
- `frontend/tests/components/jobs/JobDetail.test.js` (existing: header,
  material-less expense count) and `JobTaskListPage.test.js` (TaskTree usage).

## Tasks (TDD)

### Task 1 — One combined pillar
Replace the two pillars with a single **"Tasks & Materials"** pillar. In
`VALID_SECTIONS`, replace `'tasks'` and `'materials'` with one key (e.g.
`'tasks_materials'`); update the default-section logic (the current
tasks/materials/worksheets fallback chain) accordingly, and the session-stored
section reconciliation (map any old stored `'tasks'`/`'materials'` to the new key).

### Task 2 — Render via the Task View layout
Render the combined pillar's open panel by **reusing `TaskTree`** (or a compact
read-mostly variant of it) so it shows tasks + nested materials + subtasks +
job-level materials + loose expenses with the Task-View columns and grand total —
instead of the two bespoke inline tables. Keep the existing affordances that lived
in those pillars (the "View task list →" link; "Copy tasks from worksheet" when
applicable). Confirm `TaskTree` can render in the pillar context (it's already used
on two pages); pass the job's tasks/materials/expenses and the `can_manage` flag.

### Task 3 — Tests
Update `JobDetail.test.js`: assert the single "Tasks & Materials" pillar exists,
that the old separate "Tasks"/"Materials" pillars are gone, and that tasks +
materials + loose expenses all appear within it. Keep/port the material-less-expense
count assertion. Ensure the full suite is green.

## Out of scope
- Changing task/material/expense editing flows (still via the task list / detail
  pages and their modals).
- The Fee atom (deferred — but this pillar is its future home).

## Decisions to confirm
- Pillar label: keep **"Tasks & Materials"** (user already OK'd) even though Expenses
  ride inside it.
- Whether to embed the full interactive `TaskTree` or a read-mostly summary in the
  pillar (lean: reuse `TaskTree` for consistency, read-mostly in the collapsed
  overview, full interactions on the task-list page).

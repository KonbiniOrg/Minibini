# Task Detail Page redesign + status-pill consolidation

**Date:** 2026-07-07
**Status:** Spec — approved design, pre-implementation
**Mockup:** `.superpowers/brainstorm/82231-1783487107/content/full-page-pending-v2.html` (final approved render; `task-page-full-v5.html` and `status-left-of-title.html` show the in-progress and blocked states)

## Goal

Rework the top of `#/jobs/:jobId/tasks/:taskId` for its primary audience — workers doing the task. Actions and description become prominent; the scattered key-value tables collapse into a compact single-row header. Along the way, consolidate the app's copy-pasted status-pill styles into one shared system.

Out of scope: lite-view behavior (money chips will later hide in lite view; not built now), live repolling.

## Page layout (top to bottom)

1. **JobHeader** — unchanged.
2. **Crumbs line** — small: `« job overview · task list`, plus `· subtask of <parent>` (linked) when the task has a parent.
3. **Title row** — status pill **left of** the task name (`<h1>`); stat-chip strip right-aligned on the same row.
4. **Blocked line** — when blocked: full-width red line under the title row, `Blocked: {blocked_reason}`, untruncated.
5. **Action band** — full-width strip: task action buttons + `Edit Task` as a quieter peer button.
6. **Description** — its own section, full width, generous room (`LinkifiedText`, preserve breaks).
7. **Subtasks** — moved above Materials. TaskTree as today.
8. **Materials** — table as today.
9. **Work Sessions** — BlepList at the bottom, **including its existing "Add Entry" button** (it is the only way to log forgotten historical time from this page).

The old toolbar row, details table, and Charge table are removed.

## Status pill

- The pill is `TaskActivityIndicator` with a new `pill` variant prop — same live vocabulary (Working with pulsing dot / Ongoing / Unstarted / Blocked / Complete / Cancelled), wrapped in the shared pill styling below. No new component.
- When `task.invoice` is set, the INVOICED badge (linked to the invoice) renders in place of the pill, as the current status cell does.

## Stat chips (header strip)

Each chip: shaded header bar carrying an uppercase label (uniform height/type across the strip), body below sized to content. Chips render as separate small cards with gaps (job-board chip look). Money chips get a green-tinted header so the billing pair reads as a family.

| Chip | Body | Shown when |
|---|---|---|
| Assignee | Assignee name, or muted "Unassigned". The name itself is the interactive element (opens AssignModal); no separate "assign" link. Interactive only when `can_manage`; plain text otherwise. It's a `<button>` styled as link text (opens a modal = action, per Links-navigate/Buttons-act). | always |
| Est Time | `formatDuration(est_worker_time)` | `est_worker_time` present |
| Est Qty | `{est_qty} {scheme_unit_label}` | rate scheme + `est_qty` present |
| Actual | See below | rate scheme present |
| Rate (money) | `${effective_rate}/{scheme_unit_label}` | rate scheme present |
| Charge (money) | `${computed_charge}` | rate scheme present |

- Unit labels come from the DB (configurable) and render verbatim; chips widen to fit.
- **Actual chip, entered-qty tasks:** running total + the add-widget inline in the chip body (`+/−` input, Add button; Enter submits; add-only, never blur). Page-specific markup inside a plain chip — the chip system stays generic. Transient success feedback: the chip's header-bar label briefly swaps to "added ✓" (no layout shift). Errors: message line below the chip strip (field-error styling). Widget hidden when the task is terminal or blocked.
- **Actual chip, elapsed-time tasks:** `{actual_hours}` + unit, read-only.
- **Scheme name and active modifiers** (previously rows in the Charge table) move to a `title` tooltip on the Rate chip (`Scheme: X · Modifiers: A, B`). Revisit visibility in the lite-view pass.

## Action band

- `TaskActions` renders in the band. Its `hideStartStop` prop is replaced by `hideStop`: on this page Start Work renders normally **inside** TaskActions (the toolbar-relocation + `bind:this` ref hack is deleted), while Stop Work / the under-minimum blep-Cancel never render here — the global yellow band owns stop/cancel while a session runs.
- `TaskQuickCard` (schedule) keeps current behavior: no prop passed, Start and Stop both available there.
- `Edit Task` button joins the band after the TaskActions buttons, in a quieter style (white bg, lighter border); opens the existing WorkItemForm edit modal. Hidden when terminal, as today.
- Button visibility per status is unchanged (pending/in_progress → Start Work, Complete, Block, Cancel; blocked → Unblock, Cancel; `cancel` still gated on `can_manage`).

## Shared styles (`frontend/src/css/app.css`)

Written generically — **no references to the task page**:

- **`.status-badge` family** — one base pill class + per-status color modifier classes, merged from the six current private copies (JobHeader, JobDetail, PurchaseOrderDetail, EstimateDetailPage, InvoiceDetailPage, ChangeOrderDetailPage). Those components drop their local `.status-badge` CSS and use the shared classes; change orders drop their `status-co-*` names for plain status names. Where a status name is shared across domains (draft/approved/cancelled/…), keep the color currently used; where copies disagree, unify to the JobHeader palette (it is the most recently designed). Add modifiers for the task-activity keys (working/ongoing/unstarted/blocked/complete/cancelled) so the pill variant of TaskActivityIndicator draws from the same family. No visual redesign intended beyond unification.
- **Stat-chip family** — `.stat-chips` (strip), `.stat-chip` (card), header-bar and body elements, and a money-tinted header modifier. Generic names, reusable on other pages.
- **Action-band class** — the full-width action strip (background, padding, flex row) as a shared class.

## Component cleanups

- **`TaskActivityIndicator`** — new `pill` prop (default false → current dot+label rendering, unchanged everywhere it's used today).
- **`TaskCard` (board)** — delete the hand-copied `tsb-*` / `dot-*` color classes; read `activity.color` from the `taskActivity()` call it already makes (inline style/custom property). No visual change.

## Backend

- `TaskSerializer`: add read-only `parent_task_name` (from `parent_task.name`, null when no parent) so the crumb link renders without an extra fetch. TDD: serializer test first.

## Testing

TDD throughout (backend Django tests; frontend Vitest in `frontend/tests/`, run `npm run test:run`):

- Serializer test for `parent_task_name`.
- TaskDetailPage tests updated for the new structure (crumbs/parent link, pill, chips incl. conditional rendering, add-qty widget behavior, section order, Add Entry retained).
- TaskActions tests for `hideStop` semantics (start visible, stop/cancel-work hidden).
- TaskActivityIndicator `pill` variant test.
- TaskCard still renders activity colors after palette removal.
- Migrated status-badge pages: existing tests keep passing (no behavior change).

Only one agent runs the Django suite at a time. Never judge pass/fail by a piped exit code — read the `OK`/`FAILED` summary line.

## Docs to update (same session as implementation)

- `docs/designs/jobs-tasks-and-worksheets.md` — task detail page section.
- `docs/designs/architecture-and-conventions.md` — shared `.status-badge`, stat-chip, and action-band conventions.

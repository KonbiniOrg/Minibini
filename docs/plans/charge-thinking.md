# Charge thinking — prep for brainstorming

A bunch of related questions about how charges/billing work have surfaced. They feel like part of one larger architectural change that hasn't taken shape yet. This doc is a memory aid: re-read before the brainstorming session so the context is loaded back in. No decisions, no implementation details — just observations and questions.

## Snapshot of what's true in the code today

**Plan side (post-PlanCharge merge):**
- `PlanTask` carries billing fields directly: `rate_scheme`, `active_modifiers`, `estimated_billable_qty`.
- Estimate wizard iterates `PlanTask` directly; atom dict has `'type': 'plan_task'`.
- Carry-over from accepted estimate creates `Task` + `TaskCharge` on the Job.
- Tasks without a `rate_scheme` are visible in the wizard at $0 (graceful fallback).

**Real side:**
- `Task` still has the legacy `units`, `rate`, `est_qty` fields.
- `TaskCharge` exists and knows how to compute billing correctly (algorithm + modifiers + minimum_charge).
- Invoice wizard prices each Blep as `task.rate × hours`, bypassing `TaskCharge` entirely.
- Profitability uses `task.rate / 2` as a labor cost proxy with a TODO to switch to `User.pay_rate` (which doesn't exist yet).

**RateScheme:**
- Owns the math: `compute_charge(qty, active_modifiers)`.
- Has `accounting_category` field but it's null everywhere and zero readers in the codebase.
- Has no `save()` / `clean()` enforcement — editing a scheme retroactively changes every linked total.
- The Settings UI form has `accounting_category` in state but never renders an input for it.

**AccountingCategory:**
- Set on work items: `PlanTask.accounting_category`, `Material.accounting_category`, `BillLineItem.accounting_category`, `Expense.accounting_category`.
- QBO sync reads it from `BillLineItem` and `Expense`.
- Doesn't flow through `RateScheme` at all today.

## Observed bugs / gaps that prompted the questions

1. Editing a `RateScheme` retroactively changes every linked total — including on accepted estimates and sent invoices. Original design doc anticipated this with an "append-only convention" but the convention was never enforced in code.
2. Real-side invoice wizard ignores `TaskCharge` and reads `task.rate` directly, so scheme modifiers and `minimum_charge` don't apply at billing time. (Mirror of the plan-side bug we just fixed, on the real side.)
3. `RateScheme.accounting_category` is dead code — never read, no UI to set it.
4. `task.rate` does double duty (customer billing rate AND labor cost proxy). These are conceptually different and got conflated.
5. Plan side currently allows `null` `rate_scheme` on `PlanTask`. Decided already that this should be required going forward, with a $0 RateScheme as the "non-billable" pattern.

## Threads being pulled on

### A. Where should accounting_category live?

Currently on work items. RateScheme has the field but unused. The natural question of "should we require it on RateScheme" turned into a bigger question about whether AC belongs on the scheme, on the work item, or both with a fallback.

Things to trace before deciding:
- Where is AC actually set today? (Forms for tasks, templates, materials, expenses.)
- Where is it read? (Wizard atom dicts, line-item creation, QBO sync.)
- Where would a shop owner want per-task override vs. accept the scheme/template default?
- Is there a real workflow where two tasks on one job legitimately need different ACs while sharing a RateScheme? The answer to this probably determines the placement.

### B. Should RateSchemes be immutable once used?

Original design said yes ("append-only convention" — to change rates, create a new scheme). Not enforced. User has now hit the bug.

Questions still open:
- What counts as "in use"? Any TaskCharge/PlanTask reference, or only references on finalized work (sent invoices, accepted estimates)?
- Hard block edits, soft warning, or split (block math fields, allow metadata)?
- What does "create a new version" mean structurally? Pure copy with `parent_scheme` FK? Version integer? Just a new scheme with a new name?
- When a new version is created, do referencing `TaskTemplate`s auto-bump? Existing `TaskCharge`/`PlanTask` rows certainly stay on the old scheme (history preservation).
- UX for retired/superseded schemes — hidden from the new-task dropdown, visible read-only on existing tasks?

### C. Should real-side billing fully migrate to TaskCharge?

`TaskCharge` exists but the invoice wizard ignores it. Migrating would mean:
- Wizard prices through `task.charge.compute_amount()` (or the scheme's effective rate per blep).
- `task.rate` / `task.units` / `task.est_qty` get dropped.
- Labor cost moves to `User.pay_rate`.

Open architectural question inside this: per-blep atoms vs per-task atoms. The design doc says bleps are detail inside a TaskCharge and shouldn't be wizard atoms; the code disagrees and exposes per-blep atoms. Resolving this changes the wizard UX, not just the pricing math.

Q4 from the previous plan was important: are users manually overriding `Task.rate` to a value that disagrees with the rate-scheme? If yes, dropping `Task.rate` loses an unspoken workflow and we'd need a `manual_override_rate` mechanism on TaskCharge. Should be answered with a quick data audit before any code changes.

### D. Require RateScheme on plan side (and on TaskTemplate)

Already mostly scoped:
- `PlanTask.rate_scheme` and `estimated_billable_qty` should be NOT NULL.
- `TaskTemplate.rate_scheme` and `default_billable_qty` cascade to NOT NULL since templates produce PlanTasks.
- One creation-path gap: `TaskTemplate.generate_task` for the EstWorksheet branch doesn't currently propagate `rate_scheme`.
- Modal needs validation; the "-- None (no billing) --" option goes away.
- Re-seed of dev DB needed since fixtures back-filled all 74 PlanTasks to a single nominal scheme that almost certainly isn't right per-task.
- A `$0` "Non-billable" scheme replaces the "task with no billing" pattern.

## The connective thread

These four threads share a question: **what is the unit of "billing identity," and what authority should it have?**

Today, billing authority is fragmented:
- `RateScheme` owns the math.
- Work items (`PlanTask`, `Task`) own qty, AC, and (legacy) rate.
- `TaskCharge` owns active modifiers and actuals on the real side.
- `PlanTaskModal` and admin forms own the user-facing input.
- Nothing owns history/versioning.

If `RateScheme` grew up — owned more, was immutable, versioned itself, carried the AC, was the canonical "billing unit" — a lot of these questions resolve at once. If `RateScheme` stayed minimal and work items kept owning their own pricing, the answers look different. The four threads are probably one architectural decision in disguise.

## Possible entry points for the brainstorm

(Prompts, not answers.)

- What invariants should a finalized invoice or accepted estimate hold against scheme edits? Once that's clear, immutability falls out.
- What's the shop-owner mental model — "configure a scheme once, tasks inherit" or "configure each task with its own pricing"? That answer probably resolves both AC placement and how much per-task override is needed.
- Where does the customer-facing rate vs. internal labor cost split land? `User.pay_rate` is the obvious answer for cost; if customer rate stops being on `Task` entirely, the model gets cleaner.
- Is `RateScheme` just "billing pattern" (pure recipe) or "billing item with history" (versioned, owns its own lifecycle)? These are very different things and the codebase is currently confused about which.
- Should `TaskCharge` and `PlanTask` be thin billing wrappers around a scheme, or do they need state of their own (actuals, modifiers, qty) that justifies separate models? On the plan side we just collapsed `PlanCharge` into `PlanTask` because the answer was "no, no separate state." On the real side, `TaskCharge.actuals` is the state that justifies the split — but is per-instance modifier selection enough to keep that model around?


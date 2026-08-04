# Task-Owned Money — Phase 5 Plan (outsourced work / service POs, spec §7)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development, task-by-task.

**Goal:** Implement spec §7 of `docs/plans/2026-08-02-task-owned-money.md` — the outsourced-work flow: PO lines linked to flat sell-side tasks, PO-level-first reconciliation of vendor bills (which stay in QBO), the received-not-reconciled nudge, and the human-confirmed task-rate update prompt. Then the cross-phase close-out: RM's manual-test outline.

**Architecture:** Sell side is an ordinary flat task (Phase 2 machinery). Cost side lives on the PO: `PurchaseOrderLineItem.task` (the reserved FK) links a PO line to the task it purchases; reconciliation adds PO-level fields (bill total, vendor invoice ref, reconciled state) + optional per-line `final_price` + invoice-only appended lines; variance reporting is per-PO. No Bill resurrection; no PO→QBO push. All rules in spec §7's numbered flow + its Future/Rejected lists are binding.

**Global Constraints:** identical to prior phase plans (branch `feature/fees`; never write the dev DB; FOREGROUND-ONLY commands with explicit 600000 ms timeout — no backgrounding/monitors/waiting; `--noinput`, one Django run at a time, fresh DB after migrations, summary-line judgment; API contract; frontend conventions; converter rules; full suites at final verification AND after any behavior-changing fix wave; e2e for changed flows; docs in-phase).

## Binding rules (spec §7, all previously RM-approved)

1. **Ordering**: creating a PO line with `task` set links cost→sell. The linked task must be top-level (structures link at the parent; subtask link rejected) and belong to a job (PO lines may serve multiple jobs via different tasks). Task link is optional per line (material lines unaffected).
2. **Receive → nudge**: a PO fully received but not reconciled surfaces as **awaiting reconciliation** (purchasing-side; NOT tied to task completion). List/dashboard affordance per existing PO list patterns.
3. **Reconcile** (bill entered once in QBO by whoever does payables; Minibini captures only the delta):
   - PO-level, authoritative: `bill_total` (Decimal, nullable), `vendor_invoice_ref` (Char), `reconciled` state (part of PO status? NO — separate boolean + reconciled_date; PO status lifecycle unchanged) — always possible however the vendor billed.
   - Line-level, optional: `final_price` (nullable = as ordered); appended invoice-only lines (ordinary PO lines flagged `invoice_only=True`, excluded from receiving flows) with optional task attribution.
   - Unattributed variance stays at PO granularity; multi-job POs report per-PO. Variance = bill_total − ordered total (display; no proration).
4. **Task-rate prompt**: ONLY from a clean per-line `final_price` on a line whose linked task is not yet invoiced: offer "update selling price to final × markup?" (markup from the existing default-markup config if present — VERIFY what exists; if no markup config exists, the prompt offers final-cost-derived suggestion without markup and notes it). Accept = permissioned money-block edit (manage/financials); decline = quoted rate stands. Never silent, never live-read: the invoice wizard stays dumb.
5. **No hard blocks**: reconciliation never gates invoicing; task completion remains the only billability gate. Late variance = recorded margin; pass-through later is a deliberate new line/CO.
6. **Rejected (do NOT build)**: final price at task completion; Bill entry in Minibini with push; PO→QBO push; automatic rate updates; proration.
7. **Job costing surface**: PO variance visible per-PO (PO detail + a job-level rollup line where job financials show PO costs — check apps/jobs/financials.py for what exists; extend minimally to show ordered vs final where POs link to the job's tasks/materials).

## Tasks

### Task 1: Schema + reconciliation core
PO fields (`bill_total`, `vendor_invoice_ref`, `reconciled`, `reconciled_date`), line fields (`final_price`, `invoice_only`), migrations; `PurchaseOrderService.reconcile(po, bill_total, vendor_invoice_ref, line_finals: {line_id: Decimal}, appended_lines: [...])` — validates received state not required (bill can precede receiving? spec says nudge keys on received; reconcile itself allowed any time post-issue — decide: allowed once ISSUED, state it), invoice_only lines excluded from receiving completeness; task-link validation (top-level, job-bearing) on line create/update; `awaiting_reconciliation` queryset/property (received-in-full AND not reconciled). Un-reconcile allowed while... keep simple: reconcile is editable (re-reconcile overwrites; it's bookkeeping, not a lifecycle lock). TDD.

### Task 2: API
PO serializers/viewset: new fields, reconcile action (`POST /api/purchase-orders/{id}/reconcile/`, CanManageFinancials), task-link on line payloads (+validation errors), awaiting-reconciliation list filter, variance in PO detail payload. Task-rate prompt support: the reconcile response includes `rate_prompts` (per clean final-price line with uninvoiced linked task: task id/name, current rate, suggested rate) — the CLIENT then offers; accepting calls the normal task PATCH (existing money-gated path; no new endpoint). Permission matrix tests.

### Task 3: Frontend — PO reconciliation UI
POPanel/PurchaseOrderDetail: reconciliation section (bill total, vendor ref, per-line final prices, append invoice-only line, variance display); awaiting-reconciliation badge/filter in the PO list; after reconcile, the rate-prompt dialog (accept → task PATCH via existing api; decline dismisses; show only for manage/financials users); task-link picker on PO line forms (top-level tasks of a chosen job — follow existing PO line form patterns). Vitest.

### Task 4: Job costing + validate_data + converter
Job financials: per-PO ordered-vs-final variance where linked (minimal extension, per rule 7); validate_data: invoice_only lines with receiving data = ERROR; final_price on unreconciled PO = WARN (stale partial entry); task-link to subtask = ERROR (guard exists; check catches bypass); converter: verify no impact (it doesn't emit POs? VERIFY — if it does, conform). Tests.

### Task 5: Full verification (fresh DB) + e2e + docs
Full Django + Vitest; e2e spec (create PO linked to an outsourced flat task → receive → awaiting-reconciliation badge → reconcile with a higher final → rate prompt accept → task rate updated → invoice wizard offers new rate; decline path too); docs: materials-inventory-and-purchasing.md (reconciliation §), jobs-and-tasks/estimates-and-prices cross-refs, invoicing-and-expenses (no-hard-block note), data-constraints (§ fields/rules), quickbooks-integration (bills-stay-in-QBO + phase-2 pull-matcher future note), ui-flows + README.

### Task 6 (CLOSE-OUT): RM's manual-test outline
Write `docs/plans/2026-08-04-manual-test-outline.md`: a rough path checklist covering EVERY user-visible change across Phases 1-5 (presets/retire/default; stamped tasks + money permissions; hand-line kinds + crystallization; signed fees/credits end-to-end incl. PDFs; nullable AC + fallback flow incl. mapping the fallback AC's QBO Item; quantity structures (build, derived expectations incl. parent-qty-not-set state, completion qty-made, pool exclusion); deliverables bridge; template-N apply (flag via API PATCH — note it); PO reconciliation + rate prompt; plus the accumulated RM-judgment items from the phase ledgers). Low detail — paths, not scripts. Commit it.

## Self-review notes
- §7 numbered flow → Tasks 1-3; costing/validate → 4; verification/e2e/docs → 5; RM outline → 6.
- Rejected list enforced by omission; the phase-2 pull-matcher stays future.
- No dependencies on unbuilt work; Phase 4 structures interact only via the top-level task-link rule.

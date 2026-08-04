# Task-Owned Money — Phase 3 Plan (nullable AC + fallback, spec §4)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development, task-by-task.

**Goal:** Implement spec §4 of `docs/plans/2026-08-02-task-owned-money.md`: Task AC becomes genuinely nullable/late-bound; a Configuration-designated fallback "uncategorized" AC is stamped onto invoice lines at compose time and flagged in the wizard; QBO stays the classification authority. Plus the Phase-2 pickup list.

**Architecture:** Classification is a billing-time concern. Catalog work stamps AC invisibly (unchanged); manual/flat tasks may leave AC null; the invoice compose step resolves null → fallback ON THE LINE (line-local; atoms keep their honest null so the flag regenerates on release/recompose). Estimate/CO hand-lines KEEP their required AC (Phase 2 rule, unchanged). Tax must be right before send; income classification is fixable later in QBO.

**Global Constraints:** identical to the Phase 2 plan's (branch `feature/fees`; never write the dev DB; foreground-only test commands with explicit 600000 ms timeout — no backgrounding, no monitors; `--noinput`, one Django run at a time, fresh DB after migration changes, summary-line judgment only; converter rules; API error contract; frontend conventions; full suites once at final verification; e2e for changed flows; docs in-phase).

## End-of-work note (applies after Phase 5, recorded here so it survives)

RM wants a rough manual-test outline — a committed checklist of paths exercising every change across Phases 1–5, low detail — delivered when all phases complete.

## Canonical decisions

- Fallback AC: Configuration key `fallback_accounting_category` (string AC id; settings surface mirrors `default_rate_scheme`, CanManageConfig). The designated AC is EXCLUDED from normal AC pickers (API filter param mirroring how `include_inactive` works, or client-side exclusion — follow whichever the AC list endpoint supports today; prefer server-side). Recommended bootstrap: RM creates an "Uncategorized income" AC (taxable=True) and designates it; no auto-creation.
- Compose stamping: when a source atom's effective AC is null, the created invoice line gets the fallback AC stamped (line-local). If NO fallback is configured and a null-AC atom is composed → contract-shaped ValidationError naming the settings key.
- Wizard flag: line serializer exposes `used_fallback_ac` (computed: line AC == configured fallback id); wizard UI badges those lines "Uncategorized → <fallback name> · taxable/non-taxable" with the normal line AC editor as the correction path.
- Targeted percentage adjustments: a targeted (non-empty AC set) adjustment on a document containing fallback-stamped lines triggers a wizard warning (display-level; no computation change — the fallback AC can never be IN a targeted set since pickers exclude it).
- Estimate-side unchanged: hand-lines keep required AC; estimate wizard lines derive AC from atoms as today (a null-AC atom composed onto an ESTIMATE line keeps AC null there — estimates don't push to QBO; only invoice compose stamps).
- Task API: `accounting_category` no longer serializer-required (column already nullable); stamping from presets still fills it; task forms show AC as optional ("— none (categorize at invoicing) —").
- QBO push: unchanged code path; compose guarantees non-null line AC. Add a defensive assert-with-clear-error where `li.accounting_category` is read.

## Tasks

### Task 1: Fallback AC Configuration + settings surface + picker exclusion
Files: apps/core (Configuration key consts if any), apps/api settings surface (mirror `default_rate_scheme` incl. validation: must be an existing AC; deposit ACs disallowed — a deposit category must stay special), AC list endpoint exclusion param, tests (settings round-trip; exclusion; deposit rejection).
TDD; run settings + AC api modules foreground.

### Task 2: Task AC optional end-to-end (API + forms)
Files: apps/api/tasks/serializers.py (drop required; prefill-before-validate from Task 8/Phase 1 adjusts), WorkItemForm.svelte (+CO/estimate Work subform AC stays REQUIRED — only job-side task forms relax), TaskDetailPage (render "—"), validate_data (task AC-null now legal — adjust the Phase-1 check), tests + Vitest.
Watch: `effective_accounting_category` consumers (wizard `_atom_category` may return None — Phase 3's compose handles; estimate-side group/category display handles None as "uncategorized" text).

### Task 3: Invoice compose stamps fallback + `used_fallback_ac`
Files: apps/invoicing/services.py (`_atom_category` consumers / line-creation sites: null → fallback lookup once per compose; no-fallback-configured → ValidationError), invoice line serializer (`used_fallback_ac`), tests (single-atom, bundle-mixed-AC, fee, material, adjustment untouched; releases regenerate flag — delete line, re-add, still flagged).
copy_from_estimate: an estimate line with null AC copied to invoice → same stamping at copy time.

### Task 4: Wizard UI flag + correction + targeted-adjustment warning
Files: wizard components (badge on flagged lines incl. fallback name + taxability; AC editor as correction), warning banner when a targeted adjustment coexists with flagged lines; Vitest.

### Task 5: QBO defensive guard + send-gate reconciliation
Files: apps/qbo/services.py (clear error if a line AC is somehow null at push), apps/invoicing/services.py send/categorization gate — reconcile with fallback semantics (gate should now be unreachable for AC; keep as defense), tests.

### Task 6: Pickup list
- Backend: remove the `is_material` service-layer alias (+ its tests; grep proof zero remaining `is_material` outside migrations/backfill helper + genuinely historical docs).
- Backend: `FeeService` rejects negative `quantity` (and 0? qty=0 makes amount 0 — reject `quantity <= 0`), tests.
- Frontend: CO line tables get kind badges (match estimate tables); fee subforms client-reject zero amount (match FeeModal); Vitest.

### Task 7: validate_data + full verification (fresh DB)
Kind/AC checks consistent with Phase 3 rules (task AC null legal; invoice line AC null = error — compose always stamps; estimate line AC null legal only on non-hand-lines...verify existing checks and adjust); then ONE full fresh-DB Django run + full Vitest; triage per standing rules; batch commits.

### Task 8: E2E
Spec: manager creates a flat job task with no AC → invoice wizard shows the uncategorized badge with fallback name → corrects one line, sends another as-is (assert both outcomes); settings page designates the fallback key. Seed conformance fixes as needed. Full e2e pass.

### Task 9: Docs
estimates-and-prices (AC pass-through §10 rewrite for late binding), invoicing-and-expenses (compose/fallback/flag), data-constraints (§1.1 new key; task AC nullability; line rules), users-and-permissions (unchanged perms note), quickbooks-integration (fallback interaction note), ui-flows (+README map). Current behavior only; verify against code.

## Self-review notes
- §4 fully covered by Tasks 1–5; pickups → 6; verification/e2e/docs → 7–9.
- Phase 4 dependency: none of this blocks §9 (subtasks inherit nullable AC trivially).
- Deliberately NOT here: per-line taxable overrides (retired concept stays retired); auto-creating the fallback AC; estimate-side stamping.

# Phase 3 — Nullable Task AC + Fallback Stamping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Adopt feature/fees Phase 3 (better-fees spec §2): Task AC becomes genuinely optional end-to-end; a Configuration-designated fallback "uncategorized" AC is stamped onto **invoice** lines at authoring/seeding time — line-local, atoms keep their honest null — and flagged in the wizard UI; QBO push gains a defensive null-AC guard.

**Architecture:** Classification is a billing-time concern. Catalog/preset work stamps AC invisibly (unchanged); manual tasks may leave AC null; every invoice-line materialization site resolves null → fallback ON THE LINE. Estimate/CO documents are untouched: their hand-lines keep required AC, their wizard lines keep deriving AC from atoms (null allowed — those documents never push to QBO). The old Phase 3 commits (`c4e52ce6..cc640988` on feature/fees) are the reference, but the invoice side is re-implemented against the agreement-skeleton reality (seeding, `BaseWizardService`, no Fee model, AC-derived material-ness).

**Tech stack:** Django 5.2/DRF service layer, Svelte 5 runes SPA, Vitest, Playwright.

## Global Constraints

- Branch: `feature/better-fees`. Subagents are told this branch explicitly and commit to it.
- NEVER write the dev DB (no migrate/shell/loaddata/ORM writes outside `manage.py test`).
- Test runs: FOREGROUND only with an explicit timeout (never background + wait, never arm a Monitor), always `--noinput`, ONE Django run at a time, judge by the `Ran N tests` / `OK` / `FAILED` summary line never a piped exit code.
- No model/schema migrations expected (Task.accounting_category is already nullable). If one becomes necessary, full suite runs fresh-DB (no `--keepdb`).
- Error contract: `{'detail': ...}` for operation errors, `{'<field>': ['msg']}` for validation; services raise ValidationError, the central handler renders.
- User-facing text never says "wizard" or "blep"; document surfaces say "Remove" never "delete". The fallback flag's user-facing word is **"uncategorized"**.
- The designated fallback AC label/name is RM's data; code never auto-creates an AC.
- e2e is DoD for user-reachable flows; Vitest per changed component; docs updated in-phase.
- nealsdata fixtures (nealseed/nealsmall) are RM-managed — never regenerate.

## Canonical decisions

- **Config key** `fallback_accounting_category` (string AC pk, unset by default). Settings PATCH validation mirrors `default_material_accounting_category` (must be blank or an existing **active** AC id) **plus** rejects deposit-flagged ACs (a deposit category must stay special).
- **Picker exclusion:** the AC list endpoint (`/api/accounting-categories/`, `AccountingCategoryViewSet.get_queryset`) gains an opt-in `?exclude_fallback=true` param that filters out the designated fallback. Normal AC pickers (LineItemModal, add-line forms, AdjustmentModal, WorkItemForm, MaterialModal, expense forms — every consumer that populates a `categories` select) pass it; the Settings surfaces do NOT (they must still list it, and the fallback-designation picker must offer everything).
- **Task API:** `accounting_category` becomes `required=False, allow_null=True` on TaskSerializer; the stamp-prefill path is unchanged (a preset pick still fills it). Task forms show AC as optional with a "— none (categorize at invoicing) —" empty option; task detail renders a muted "uncategorized" for null.
- **Invoice stamping** happens at every invoice-line materialization site, via ONE helper `InvoiceWizardService.resolve_line_category(category)` (name final): returns `category` unchanged when non-null; when null, returns the configured fallback AC; when null and NO fallback is configured, raises `ValidationError({'accounting_category': ['... set the fallback_accounting_category setting ...']})` naming the key. Sites:
  - the shared wizard's line creation for the INVOICE subclass only — `BaseWizardService` gains a `_resolve_line_category(category)` classmethod hook (base = identity) applied where `add_atoms_to_new_line_item` assigns `accounting_category=category`; `InvoiceWizardService` overrides it with the fallback resolution. `add_atoms_to_line_item` re-derive paths that rewrite the line's AC (if any — verify) get the same treatment. Estimate/CO wizards inherit the identity hook: their lines keep null.
  - agreement seeding (`seed_from_agreement`) and the restore path — a skeleton line whose agreement line dict has `accounting_category_id=None` gets the fallback stamped.
  - deposit lines and hand lines are already guaranteed an AC (deposit default / required-AC rule) — no change, but the helper is still the single choke point if verification finds another null path.
- **`used_fallback_ac`:** computed field on `InvoiceLineItemSerializer` — true iff a fallback is configured AND `line.accounting_category_id` equals it. Line-local and self-healing: correcting the line's AC clears it; re-adding an uncategorized atom re-flags.
- **Wizard UI:** flagged lines show an amber chip in the Backing column area: `uncategorized → {fallback name} · {taxable|non-taxable}`. Correction path is the existing Edit modal's AC select (no new control). A **banner** above the line table warns when a *targeted* percentage adjustment (non-empty `adjustment_target_categories`) coexists with flagged lines: the fallback category can never be in a targeted set (pickers exclude it), so targeted math silently skips flagged lines — display-level warning only, no computation change.
- **QBO defensive guard:** `apps/qbo/services.py` line loop (`li.accounting_category.taxable` at ~:355 and the item mapping at `_line_item_qbo_item`/~:404) raises a clear contract-shaped error naming the invoice line when AC is null instead of `AttributeError`. The existing pre-send gate (`assert_all_lines_categorized`, `apps/invoicing/services.py` ~:768) STAYS as defense in depth — reword its message to point at the fallback setting.
- **validate_data:** task AC null = legal (relax the Phase 1-era check if present); INVOICE line AC null = error (stamping means it should never survive authoring); estimate/CO line AC null = legal only on non-hand lines (verify current checks match).

---

### Task 1: `fallback_accounting_category` — Configuration + settings API + picker-exclusion param

**Files:**
- Modify: `apps/api/templates_config/views.py` (settings GET/PATCH — mirror the `default_material_accounting_category` block at ~:254, adding the deposit-AC rejection; `AccountingCategoryViewSet.get_queryset` — `exclude_fallback` param)
- Test: `tests/test_fallback_ac_setting.py` (new)

**Steps:**
1. Failing tests: settings PATCH round-trips the key (blank clears); rejects a non-id, an unknown/inactive AC, and a deposit-flagged AC (verify the deposit flag's real field name on AccountingCategory first — the e2e fixtures read `is_deposit`); GET exposes it. AC list with `?exclude_fallback=true` omits the designated AC; without the param includes it; param with no key configured is a no-op.
2. Implement both view changes.
3. Module run green; commit `feat(api): fallback_accounting_category setting + AC picker exclusion (Phase 3 Task 1)`.

**Produces:** the Configuration key contract every later task reads; the `exclude_fallback` param name.

### Task 2: Settings SPA surface

**Files:**
- Create: `frontend/src/components/settings/FallbackCategorySetting.svelte` (mirror `DefaultMaterialCategorySetting.svelte` — explicit Save, error via triage)
- Modify: the settings page that hosts `DefaultMaterialCategorySetting` (render the new block beside it)
- Test: `frontend/tests/components/settings/FallbackCategorySetting.test.js` (mirror the sibling's tests)

**Steps:** copy the sibling component's shape exactly (load current value from `/api/settings/`, select over ALL categories — no exclusion here, Save PATCHes, success/error display); Vitest green; commit `feat(spa): fallback accounting category setting (Phase 3 Task 2)`.

### Task 3: AC pickers pass `exclude_fallback=true`

**Files:**
- Modify: every SPA fetch that populates an AC picker for *authoring* (grep `accounting-categories` in `frontend/src` — expected: the panels' `loadCategories` (estimate/CO/invoice), TasksPanel, expense/material forms, AdjustmentModal's source if it fetches). Settings surfaces keep the bare list.
- Test: extend one representative Vitest per surface asserting the fetch URL carries the param (behavior-level; no new components).

**Steps:** sweep + assert + commit `feat(spa): authoring AC pickers exclude the fallback category (Phase 3 Task 3)`.

### Task 4: Task AC optional end-to-end

**Files:**
- Modify: `apps/api/tasks/serializers.py` (`accounting_category` → `required=False, allow_null=True`; adjust the "API tightens to required" comment + any view prefill assumptions in `apps/api/jobs/views.py`/tasks views)
- Modify: `frontend/src/components/WorkItemForm.svelte` (task AC select gains an explicit "— none (categorize at invoicing) —" empty option in edit mode; create mode is stamp-driven and unchanged), task detail page (render muted "uncategorized" when null)
- Modify: `apps/core/management/commands/validate_data.py` (or wherever the task-AC check lives — make task AC null legal)
- Test: extend `tests/test_task_money_api.py`-family (create/PATCH a task clearing AC succeeds; stamp path still fills), Vitest for the form/detail rendering.

**Steps:** failing tests → implement → targeted modules + Vitest → commit `feat(jobs,api,spa): task accounting category optional end-to-end (Phase 3 Task 4)`.

**Watch:** `_atom_category` (`apps/core/wizard.py:95`) now returns None for such tasks — Task 5 owns the invoice side; estimate/CO side must simply tolerate a null-AC line (verify `derive_estimate_backing`/group displays don't crash — render "uncategorized" text where a name would show).

### Task 5: Invoice authoring stamps the fallback + `used_fallback_ac`

**Files:**
- Modify: `apps/core/wizard.py` (add the identity `_resolve_line_category` hook at the `accounting_category=category` assignment in `add_atoms_to_new_line_item`; audit `add_atoms_to_line_item`/`remove_atoms_from_line_item` re-derive paths for AC rewrites and route them through the hook too)
- Modify: `apps/invoicing/services.py` (`InvoiceWizardService._resolve_line_category` override + the `resolve_line_category` fallback lookup helper; `seed_from_agreement` + the restore-line path stamp when the agreement line dict's `accounting_category_id` is None)
- Modify: `apps/api/invoicing/serializers.py` (`used_fallback_ac` on `InvoiceLineItemSerializer` — one Configuration read per serialization, not per line: resolve in `to_representation` context or a cached property)
- Test: `tests/test_invoice_fallback_ac.py` (new): single null-AC task atom → line stamped + flag true; mixed-AC bundle → stamped; all-same-AC bundle → real AC, flag false; estimate wizard line from the same null-AC atom keeps AC **null** (no stamping outside invoices); seeding an agreement whose estimate line has null AC → stamped; restore path same; no fallback configured + null needed → ValidationError naming the key; correcting the line's AC via update → flag false.

**Steps:** failing tests → implement → run invoice + estimate + CO wizard suites (the hook touches the shared base) → commit `feat(invoicing): invoice lines stamp the fallback AC; used_fallback_ac flag (Phase 3 Task 5)`.

### Task 6: Wizard UI — uncategorized chip + targeted-adjustment warning

**Files:**
- Modify: `frontend/src/components/invoices/InvoiceEditView.svelte` (chip on flagged lines: `uncategorized → {name} · {taxable|non-taxable}` — fallback name/taxability read from the already-loaded `categories` list by the line's AC id; banner when any `used_fallback_ac` line coexists with a targeted adjustment line (`adjustment_target_categories.length > 0`))
- Test: `frontend/tests/components/invoices/InvoiceEditView.test.js` (chip renders with name + taxability; absent when flag false; banner appears only for the coexistence case)

**Steps:** failing Vitest → implement → full Vitest → commit `feat(spa): uncategorized-line chip + targeted-adjustment warning (Phase 3 Task 6)`.

### Task 7: QBO defensive guard + send-gate reconciliation

**Files:**
- Modify: `apps/qbo/services.py` (null-AC line → clear ValidationError naming the line, replacing the latent AttributeError at ~:355/:404)
- Modify: `apps/invoicing/services.py` (the ~:768 categorization gate message points at the fallback setting; confirm the gate is now unreachable via authoring but keep it)
- Test: extend the QBO push tests + invoice send-gate tests.

**Steps:** failing tests → implement → run qbo + invoicing modules → commit `fix(qbo,invoicing): defensive null-AC guards name the fallback setting (Phase 3 Task 7)`.

### Task 8: validate_data rules + converter conformance

**Files:**
- Modify: the validate_data checks (task AC null legal; invoice line AC null = error; estimate/CO hand-line AC rules verified unchanged)
- Test: the validate_data test module; `tests.test_neals_builders` run REQUIRED (converter conformance — no fixture regen, nealseed/nealsmall untouched).

**Steps:** adjust → run validate_data tests + full `tests.test_neals_builders` foreground → commit `feat(core): validate_data reflects Phase 3 AC nullability rules (Phase 3 Task 8)`.

### Task 9: E2E

**Files:**
- Create: `e2e/specs/invoice-seeding-and-send/uncategorized-fallback.spec.js`

**Flow:** (configtime persona) settings page designates the fallback AC → (finjobs) build job via API with a null-AC task (PATCH the AC away post-create), estimate from the atom, accept → start invoice → the seeded/added line shows the `uncategorized →` chip → correct ONE line's AC via the edit modal (chip clears) → a second uncategorized line is left as-is and send succeeds (QBO mocked/absent locally — assert the send gate does not trip). Follow the folder's build-it-fresh idiom.

**Steps:** spec passes solo + folder run → commit `test(e2e): uncategorized fallback-AC invoice flow (Phase 3 Task 9)`.

### Task 10: Docs + final verification

**Files:**
- Modify: `docs/designs/estimates-and-prices.md` (AC pass-through section — late binding), `docs/designs/invoicing-and-expenses.md` (stamping/flag/chip), `docs/designs/data-constraints.md` (§1.1 new key; task AC nullability; line-level rules), `docs/designs/quickbooks-integration.md` (fallback note), `docs/designs/jobs-and-tasks.md` (task AC optional), `docs/ui-flows/` map if a flow doc names AC requiredness.
- Final verification: ONE full fresh-DB Django run + full Vitest + the invoice-seeding-and-send and add-line-and-work-authoring e2e folders. Triage per standing rules.

**Steps:** docs → verification → commit `docs: Phase 3 nullable AC + fallback reference updates (Phase 3 Task 10)`.

## Self-review

- Spec §2 Phase 3 bullets all covered: optional task AC (T4), fallback key (T1-3), invoice stamping line-local + flag (T5-6), QBO guard (T7). Old plan's "pickup list" (Fee/is_material items) is moot on this branch — Fee deleted, is_material now AC-derived.
- The estimate/CO side deliberately unchanged beyond null-tolerance (T4 watch note).
- No migrations anticipated; if an implementer needs one, fresh-DB rule applies.
- Deferred/not here: per-line taxable overrides (retired), auto-created fallback AC, estimate-side stamping.

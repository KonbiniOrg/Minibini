# Fee Removal + Crystallization Narrowing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the `jobs.Fee` model and the fee atom type everywhere, and narrow
acceptance crystallization so plain hand-lines produce nothing (spec
`docs/plans/2026-08-06-better-fees.md` §4, §5, §10 phase 5: "There is no
pure-money atom. Pure money lives on documents.").

**Architecture:** Backend code references die first (acceptance → CO acceptance →
agreement channel → invoice wizard → service/API/validate_data), then the model +
three migrations (purge fee source rows, narrow source_type choices, DeleteModel)
+ fixture stripping, then the converter, then the frontend work surface and copy,
then e2e + docs. Each task leaves the targeted test modules green.

**Tech Stack:** Django 5.2 / DRF / MySQL backend; Svelte 5 + Vitest frontend;
Playwright e2e; nealsdata converter (plain Python).

## Global Constraints

- Branch: **`feature/better-fees`** — commit every task there. Never create or
  switch branches.
- **Never write to the dev database.** No `manage.py migrate`, no `manage.py
  shell`, no loaddata, no ORM writes outside `manage.py test`. (Tests use their
  own DB.) Read-only SELECT diagnostics are allowed.
- Django tests: always `--noinput`; never run two Django test processes at once
  (hook-enforced); **run tests in the FOREGROUND with a generous timeout — never
  background a test run and wait for a notification** (known stall pattern).
  Judge results by the `Ran N tests` / `OK` / `FAILED` summary lines, never by a
  piped exit code.
- Targeted backend modules per task; the **full backend suite runs fresh-DB
  (NO `--keepdb`) only in Task 6 and Task 12** (migration house rule).
- Frontend: Vitest via `npm run test:run` from `frontend/` (never watch mode).
- TDD: write/adjust the failing test first, watch it fail, then implement.
- Error contract: services raise `ValidationError` (field-keyed when the problem
  belongs to an input field); never emit an `'error'` key.
- User-facing text never says "blep" (say "timeslip") or "wizard".
- **Do NOT touch** the flat-fee RateScheme machinery: `apps/jobs/flat_fee_reframe.py`,
  `apps/jobs/task_money_backfill.py`, `apps/jobs/migrations/0013|0045|0046|0052`,
  `tests/test_flat_fee_reframe.py`, any `flat_fee` string, and fixture/test rows
  named "Late Fee"/"Rush Fee 15%"/"Std Setup Fee" (rate-scheme adjustments).
  Historical migration helpers carry explicit do-not-sweep warnings — obey them.
- The entry-time AC-required rules on hand lines **stay**
  (`EstimateService.assert_all_hand_lines_have_ac`,
  `ChangeOrderService.assert_all_bare_add_lines_have_ac`, and the frontend
  guards): spec §4 keeps them verbatim. Only their *justifying comments*
  ("crystallizes into a Fee") get reworded.
- `claiming_kind` (named in spec §4) **does not exist in code** — do not hunt it.

**Dev-DB data facts** (verified 2026-08-09, read-only): 42 Fee rows; 40 claimed
by estimate lines (2 of those also invoice-claimed), 2 claimed by CO lines,
**0 unclaimed, 0 task-linked** — the §10 "surface unclaimed fees to RM" step is
satisfied vacuously; the migration handles everything mechanically.

---

### Task 1: Acceptance narrowing — plain lines crystallize nothing

**Files:**
- Modify: `apps/estimates/acceptance.py` (fallthrough branch ~119-146, module docstring 7-20)
- Modify: `apps/estimates/signals.py:112-120` (docstring only)
- Modify: `apps/api/estimates/views.py:106` (comment only)
- Test: `tests/test_acceptance_fees.py` → rename `tests/test_acceptance_plain_lines.py`; update `tests/test_deferred_service_crystallization.py`, `tests/test_hand_line_ac_validation.py`, `tests/test_estimate_create_and_claim_state.py` as they fall out

**Interfaces:**
- Produces: `run_acceptance` (or the module's entry function) return dict **loses
  the `'fees_created'` key** — grep all consumers (API response payloads, tests,
  services) and update them in this task.
- The discriminator becomes: sources → skip; adjustment → skip; `service_item` →
  Task; `inventory_item` → Material; `is_material` → Material; **else → skip
  (no source row, no object; the line stays a document line)**.

- [ ] **Step 1: Write the failing tests.** In the renamed test module: (a) a bare
  non-material hand line with an AC on an accepted estimate creates **no Fee, no
  EstimateLineItemSource row**, and the line is still present on the document;
  (b) acceptance is idempotent for plain lines (re-running creates nothing);
  (c) service/inventory/bare-material crystallization is untouched (keep the
  existing passing assertions for those arms). Note `Fee` still exists at this
  point — assert `EstimateLineItemSource.objects.filter(source_type='fee').count() == 0`
  and no source row on the line, not model non-existence.
- [ ] **Step 2:** `python manage.py test tests.test_acceptance_plain_lines --noinput` — new assertions FAIL (a Fee/source row is created today).
- [ ] **Step 3: Implement.** Delete the Fee fallthrough block (the AC-guard
  `ValidationError` at 122-127 dies with it — the entry-time send guard already
  enforces AC), replace with `continue`. Drop `'fees_created'` from the counts
  dict and its consumers. Rewrite the module docstring's arm list.
- [ ] **Step 4:** Run `tests.test_acceptance_plain_lines`,
  `tests.test_deferred_service_crystallization`, `tests.test_hand_line_ac_validation`,
  `tests.test_estimate_create_and_claim_state`, `tests.test_estimates_services`
  (foreground, `--noinput`) — all green.
- [ ] **Step 5: Commit** `feat: acceptance skips plain hand-lines (no Fee crystallization)`.

### Task 2: CO acceptance narrowing

**Files:**
- Modify: `apps/estimates/co_acceptance.py` (docstring 10-36; counts 64-67; `_mirror_of` 144-169; `_crystallize` 175-283; `_retire` 298-335)
- Modify: `apps/estimates/change_order_service.py` (docstrings at 92, 121-123, 221 — reword, guards stay)
- Test: `tests/test_change_order_acceptance.py`, `tests/test_change_order_lifecycle.py`, `tests/test_change_order_model.py`

**Interfaces:**
- Consumes: Task 1's narrowed estimate-side discriminator (mirror it exactly).
- Produces: `on_accept` counts dict loses `'fees_created'`/`'fees_removed'`;
  `_mirror_of` becomes an **explicit** dispatch.

- [ ] **Step 1: Failing tests.** (a) a CO **add** of a bare non-material line
  with AC, accepted → no Fee, no `ChangeOrderLineItemSource` row, line stays a
  document line; (b) a CO **replace** of a plain line → document-level only, no
  atom churn; (c) task/material add/replace/retire behavior pinned unchanged.
- [ ] **Step 2:** Run `tests.test_change_order_acceptance` — new assertions FAIL.
- [ ] **Step 3: Implement.** In `_mirror_of`, make the material arm explicit and
  make the trailing default **raise**, never silently mistype:
```python
        if source_type == 'task':
            ...  # existing task mirror
        if source_type == 'material':
            ...  # existing material mirror
        raise ValueError(f'unknown source_type {source_type!r}')
```
  In `_crystallize`, the Fee default arm (263-283, incl. its AC ValidationError)
  becomes a skip (document-only line). In `_retire`, delete the `'fee'` arm.
  Drop the two counts keys and their consumers. Reword the three
  change_order_service docstrings (`assert_all_bare_add_lines_have_ac` now
  justifies AC on plain lines as a document/invoice-transit requirement — the
  guard itself is untouched).
- [ ] **Step 4:** Run `tests.test_change_order_acceptance`,
  `tests.test_change_order_lifecycle`, `tests.test_change_order_model` — green.
- [ ] **Step 5: Commit** `feat: CO acceptance skips plain lines; explicit mirror dispatch`.

### Task 3: Remove the `source_fee_id` agreement channel

**Files:**
- Modify: `apps/estimates/agreement.py` (`_line_dict_from_estimate_item` 20-49, `_line_dict_from_co_item` 52-80, `fee_source_map` ~115, `co_fee_source_map` ~142, call sites 126-128/164-169)
- Modify: `apps/invoicing/services.py:311-319` (the `source_fee_id` consumer in `copy_from_estimate`)
- Test: `tests/test_line_item_sources.py`, invoice seeding tests (`tests/test_invoice_includes_fees.py` → delete or fold its surviving assertions into the seeding suite), `tests/test_api_invoicing.py`

**Interfaces:**
- Produces: agreement line dicts **no longer carry `source_fee_id`** (contract
  change; `compose_agreement` consumers are `apps/invoicing/services.py` and
  tests — grep for the key).

- [ ] **Step 1: Failing test.** Assert `compose_agreement` line dicts have no
  `source_fee_id` key, and that seeding/copy-from-estimate of a job whose
  agreement contains a plain hand line creates the invoice line **without** any
  `InvoiceLineItemSource` fee row (agreement_ref only).
- [ ] **Step 2:** Watch it fail (key present today).
- [ ] **Step 3: Implement** — delete both maps, both parameters, both dict keys,
  and the invoicing consumer block. Delete `tests/test_invoice_includes_fees.py`
  if nothing in it survives (fee-transit is now agreement_ref transit, covered by
  the seeding suite).
- [ ] **Step 4:** Run `tests.test_line_item_sources`, `tests.test_api_invoicing`,
  and the invoice seeding module(s) touched — green.
- [ ] **Step 5: Commit** `feat: drop source_fee_id from the agreement contract`.

### Task 4: Invoice wizard fee removal

**Files:**
- Modify: `apps/invoicing/services.py` — "Fees" pseudo-group 1176-1203; `_resolve_atom` 1386-1405 fee arm; `_atom_source_type` 1407-1422 Fee isinstance; `_atom_category`/`_atom_description`/`_atom_qty_and_price`/`_atom_detail` fee arms 1448-1502; `_mirror_agreement_claims` docstring 443-447 ("Fee atoms … always pass")
- Test: `tests/test_fee_wizard.py` (delete), pool-shape tests in `tests/test_api_invoicing.py` / wizard tests

**Interfaces:**
- Produces: the source pool's group list is Loose/Expenses/Deposit credits +
  real tasks — **no `{'name': 'Fees'}` pseudo-group**; atom refs of
  `type: 'fee'` are rejected by `_resolve_atom` like any unknown type.

- [ ] **Step 1: Failing test.** Pool response for a job never contains a group
  named `'Fees'`; POSTing an atom ref `{'type': 'fee', 'id': N}` to
  line-items-from-atoms / add-atoms returns a 400 (not a 500).
- [ ] **Step 2:** Watch the pool-shape half fail (group exists when the job has fees).
- [ ] **Step 3: Implement** — delete the group block and every Fee arm; verify
  the unknown-type path of `_resolve_atom` raises `ValidationError`, not
  `KeyError`. Delete `tests/test_fee_wizard.py`.
- [ ] **Step 4:** Run `tests.test_api_invoicing` + the wizard/pool test modules — green.
- [ ] **Step 5: Commit** `feat: invoice pool loses the Fees group and fee atom type`.

### Task 5: FeeService, API endpoints, serializers, validate_data

**Files:**
- Modify: `apps/jobs/services.py` (drop `Fee` import line 17; delete `FeeService` 1275-1351)
- Modify: `apps/api/jobs/views.py` (imports 10/12; prefetch 49-52; `create_fee` 328-371; `fee_detail` 373-430)
- Modify: `apps/api/jobs/serializers.py` (import line 2; `FeeSerializer` 24-48; `fees` field 57/74; `get_fees` 219-223; `_atom_context` docstring 196)
- Modify: `apps/api/estimates/serializers.py` (Fee isinstance arms in `get_units` 150-159 / `get_rate` 161-170 + their imports; comment blocks 65-70 & 134-140 — the "Fee is transitional → planned_materials" caveat dies)
- Modify: `apps/core/management/commands/validate_data.py` (`check_fees` call at 120 + def 782-800; `SOURCE_FEE` members in the two source-consistency sets ~810/~842)
- Test: delete `tests/test_fee_model.py`, `tests/test_api_fees.py`; update `tests/test_validate_data.py`, `tests/test_deletion_guards.py`, `tests/test_source_row_purge_on_atom_delete.py`, `tests/test_service_item.py`, `tests/test_adjustment_lines.py`, `tests/test_estimate_job_status_sync.py`, `tests/test_acceptance_provisional_material.py`, `tests/test_api_invoicing.py` (whatever references Fee)

**Interfaces:**
- Produces: `GET /api/jobs/{id}/` payload **loses the `fees` key**; the
  `/api/jobs/{id}/fees/` routes 404 (they were `@action`-declared — deleting the
  actions removes the routes; no urls.py entry exists).
- The estimate-side derived backing (`derive_estimate_backing`) no longer has a
  fee-source input; keep its behavior pinned by existing tests.

- [ ] **Step 1: Failing tests.** Job detail payload has no `fees` key; POST to
  `/api/jobs/{id}/fees/` is 404. Adjust the update-list test modules' fixtures
  that construct Fees to construct the equivalent plain-line/material scenarios.
- [ ] **Step 2:** Watch fail. **Step 3: Implement** the deletions.
- [ ] **Step 4:** Run every test module named above (foreground, one process) — green.
- [ ] **Step 5: Commit** `feat: delete FeeService, fee endpoints, fee serializer surface`.

### Task 6: Model deletion, migrations, fixture stripping, fresh-DB suite

**Files:**
- Modify: `apps/jobs/models.py` (delete `Fee` 708-745)
- Modify: `apps/estimates/models.py` (`SOURCE_FEE` 606/610 + resolve arm 634-636; `SOURCE_FEE` 734/738 + resolve arm 762-764; prose at 574/599/674/725-726)
- Modify: `apps/invoicing/models.py` (`SOURCE_FEE` 256/262 + resolve arm 290-292)
- Modify: `apps/estimates/claims.py` docstring 55-58 (names `Fee.delete()`)
- Create: `apps/estimates/migrations/0045_*.py`, `apps/invoicing/migrations/0024_*.py`, `apps/jobs/migrations/0062_*.py`
- Modify: the five fee-carrying fixtures (strip via script): `fixtures/playwright/seed.json`, `fixtures/playwright/rebased.json`, `fixtures/staging/seed.json`, `fixtures/large_datasets/nealseed.json`, `fixtures/large_datasets/nealsmall.json`

**Interfaces:**
- Migration ordering: the two source-purge migrations run **before**
  `jobs/0062_delete_fee` (declare both as dependencies of 0062).

- [ ] **Step 1:** Edit the three models (constants, choices, resolve arms, Fee
  class). `python manage.py makemigrations` (allowed) — it will generate the
  AlterField(source_type choices) operations and the DeleteModel.
- [ ] **Step 2:** Prepend a `RunPython` purge to each source-app migration so
  data dies before choices narrow (historical models have no custom `delete()`,
  so QuerySet.delete is correct *inside migrations*):
```python
def drop_fee_sources(apps, schema_editor):
    for model_name in ('EstimateLineItemSource', 'ChangeOrderLineItemSource'):
        apps.get_model('estimates', model_name).objects.filter(source_type='fee').delete()
```
  (invoicing analog for `InvoiceLineItemSource`). Reverse = `migrations.RunPython.noop`
  with a comment: fee data is unrecoverable by design (spec §10 phase 5 —
  claimed lines already carry their stored values). Add
  `dependencies` entries in `jobs/0062` on the exact estimates/invoicing
  migration names. Comment each migration with the spec reference.
- [ ] **Step 3: Fixture strip.** Write a small script (scratch, not committed)
  that loads each of the five JSON fixtures and removes (a) every object with
  `"model": "jobs.fee"`, (b) every `*lineitemsource` object whose fields carry
  `"source_type": "fee"`, then rewrites the file with the original indent style.
  Verify counts removed match the survey (38/38 ×4 files; 41/43 for
  nealsmall.json — nealsmall has 2 extra source rows; confirm they are CO fee
  sources and are removed too).
- [ ] **Step 4: Fresh-DB full suite** (the migration house rule):
  `python manage.py test --noinput` with NO `--keepdb`, foreground, timeout
  generous (~600s+). Read the summary line. Also
  `cd e2e && node` the seed-load path if one exists — at minimum confirm
  `fixtures/playwright/seed.json` parses as JSON.
- [ ] **Step 5: Commit** `feat: delete the Fee model; purge fee source rows; strip fixtures`.

### Task 7: nealsdata converter — fee lines become plain document lines

**Files:**
- Modify: `nealsdata/converter/parsing.py` (`infer_algorithm` 296-306 — the `'fee'` terminal fallback)
- Modify: `nealsdata/converter/build.py` (`_emit_fee` 1242-1269 delete; `_line_billing` 1084-1102 sentinel; `_build_line_item_tasks` 1284-1285; comments 999/1065/1088/1092/1369/1389/1446/1453-1457/1551)
- Test: `tests/test_neals_builders.py`, `tests/test_neals_parsing.py`, `tests/test_neals_fixture.py`

**Interfaces:**
- Produces: a line `infer_algorithm` classifies as fee-like now emits **no atom
  and no source row** — the estimate line rides as a plain hand line. Keep the
  sentinel's *detection* (rename `'fee'` → `'plain'`) so `_line_billing` can
  skip explicitly; do NOT reroute those lines into Tasks or Materials.

- [ ] **Step 1: Failing tests.** In the builders/parsing tests, pin: fee-classified
  input lines produce zero `jobs.fee` fixtures (the model string must not appear
  in output at all) and zero `source_type='fee'` rows; the estimate line itself
  is still emitted with its price.
- [ ] **Step 2:** Watch fail. **Step 3: Implement**; delete `_emit_fee`, rename
  the sentinel, update comments.
- [ ] **Step 4:** Regenerate `nealsdata/datasets/converted.json`
  (`python nealsdata/convert_neals_data.py` — output is gitignored) and run
  `tests.test_neals_builders`, `tests.test_neals_parsing`, `tests.test_neals_fixture`
  (foreground) — green. **Do not regenerate or hand-edit `nealsmall.json` here**
  (RM-managed; Task 6 already stripped its fee rows mechanically).
- [ ] **Step 5: Commit** `feat: converter emits plain lines instead of Fee atoms`.

### Task 8: Frontend work surface — delete the fee UI

**Files:**
- Delete: `frontend/src/components/FeeModal.svelte`, `frontend/tests/components/FeeModal.test.js`
- Modify: `frontend/src/components/tasks/TasksPanel.svelte` (import :11; state 43-59; `handleChoose` else-branch 214-228; `openEditFee`/`handleFeeSaved` 302-313; props into TaskTree 398-399; comment 403; modal 437-446; `taskSurface` picker 448)
- Modify: `frontend/src/components/TaskTree.svelte` (import :5; props 41-42; total 79-82; Fees group 190-211; styles 231-238)
- Modify: `frontend/src/components/PriceListPicker.svelte` (footer 92-96 → two buttons Add Task / Add Material on the task surface; `emitFreeformFee` 56-58 dies; the estimate-surface "Is this a material?" checkbox + `emitFreeform` **stay** — `is_material` still drives crystallization)
- Modify: `frontend/src/lib/taskTotals.js` (delete `feeTotal` 61-63), `frontend/src/lib/format.js` (drop `fee: 'fee'` from `ATOM_KIND_TAGS` :20)
- Test: `frontend/tests/components/tasks/TasksPanel.test.js` (fee describes 83-186, 288-307, fixtures), `frontend/tests/components/TaskTree.test.js:25-40`, `frontend/tests/components/PriceListPicker.test.js:72-78,107-121`

**Interfaces:**
- `TasksPanel.handleChoose`: with Add Fee gone, a freeform non-material choice
  can no longer arrive from the task surface — the trailing `else` becomes the
  material branch's sibling; leave no silent fee path.

- [ ] **Step 1: Failing tests.** Task-surface picker offers exactly Add Task /
  Add Material (no `/add fee/i`); TaskTree renders no Fees group and its grand
  total is tasks+materials only; TasksPanel has no FeeModal path.
- [ ] **Step 2:** Watch fail. **Step 3: Implement** the deletions/restructures.
- [ ] **Step 4:** `npm run test:run` (full Vitest — cheap) — green.
- [ ] **Step 5: Commit** `feat(spa): remove the fee work-surface UI`.

### Task 9: Frontend copy + comment pass

**Files:**
- Modify: `frontend/src/components/invoices/InvoiceEditView.svelte:567` (subtitle → "Tasks, materials, and expenses from this job not yet on this invoice.")
- Modify: `frontend/src/components/home/HelpPanel.svelte:88-90,109,135,245` (drop the Fee atom bullet; reword crystallization + pool copy to tasks/materials/expenses)
- Modify: comment rewording only (guards stay): `frontend/src/components/estimates/EstimateAddLineForm.svelte:59-69`, `frontend/src/components/changeorders/COAddLineForm.svelte:62-73`, `frontend/src/components/LineItemModal.svelte:94-110`, `frontend/src/components/changeorders/COLineItemModal.svelte:45-48,91-100` — AC is required on plain lines because documents/invoicing need it, not because a Fee will be created
- Test: `frontend/tests/components/EstimateAddLineForm.test.js:36-48,97-105`, `frontend/tests/components/changeorders/COAddLineForm.test.js:36-51,80-89`, `frontend/tests/LineItemModal.test.js:54-67` — keep the AC-guard assertions, rename their fee-worded test titles

- [ ] **Step 1:** Update test titles/copy assertions first (subtitle text change
  will fail the InvoiceEditView copy test if one pins it — check).
- [ ] **Step 2-3:** Implement copy changes.
- [ ] **Step 4:** `npm run test:run` — green.
- [ ] **Step 5: Commit** `chore(spa): fee copy and comment pass (AC guards unchanged)`.

### Task 10: E2E — the fee-less surfaces

**Files:**
- Create: `e2e/specs/add-line-and-work-authoring/no-fee-surface.spec.js`
- Reference conventions: `docs/designs/e2e-testing.md`, existing specs in the same directory

**Interfaces:** e2e runs against its own DB (ports 8100/9100) rebuilt from
migrations + the stripped seed — Task 6 must be complete.

- [ ] **Step 1:** Write the spec: (a) on a manageable job's task surface, the
  Add Work picker footer offers Add Task and Add Material and **no Add Fee**;
  (b) build a draft estimate with one plain hand line (AC assigned), accept it
  via the API, and assert the job's task list shows no Fees section and the
  job's fresh invoice source pool shows no Fees group (drive the invoice edit
  view; the uncovered-work subtitle reads the Task 9 copy).
- [ ] **Step 2:** `cd e2e && npx playwright test specs/add-line-and-work-authoring/no-fee-surface.spec.js` — green.
- [ ] **Step 3:** Run the whole e2e suite once (`npx playwright test`) — the
  fixture strip (Task 6) changed the seed; watch
  `specs/settings/accounting-categories.spec.js` (its AC reference-count
  assertion was partly fed by 38 seeded fee rows) and the three known
  pre-existing flakes catalogued in `docs/designs/LATER.md`.
- [ ] **Step 4: Commit** `test(e2e): fee-less work surface + plain-line acceptance`.

### Task 11: Docs pass

**Files:**
- Modify: `docs/designs/estimates-and-prices.md` (75 fee mentions), `docs/designs/jobs-and-tasks.md` (34), `docs/designs/data-constraints.md` (27 — the Fee field table + fee source_type rows die), `docs/designs/invoicing-and-expenses.md` (22 — Fees pool group, always-billable carve-out), `docs/designs/architecture-and-conventions.md` (12), `docs/designs/tutorial.md` (5), `docs/designs/materials-inventory-and-purchasing.md` (3)
- Modify: `docs/ui-flows/Add-Line-and-Work-Authoring.md`, `docs/ui-flows/Change-Orders.md`, `docs/ui-flows/Deletion-and-Retirement.md` (§1 "Fees" section dies), `docs/ui-flows/Production-Lifecycle.md:199`, `docs/ui-flows/Invoice-Seeding-and-Send.md:13`, `docs/ui-flows/Services-and-Adjustments.md:21,92-93,128-129,330` (reword "the Fee atom" parentheticals; rush-fee *adjustment* language stays)
- Modify: `docs/plans/2026-08-06-better-fees.md` §10 item 5 — mark landed
- Modify: `CLAUDE.md` key-models table (`apps.jobs` row lists Fee)

- [ ] **Step 1:** Sweep each file for `fee` (case-insensitive), rewriting to the
  new taxonomy: plain lines don't crystallize; charges are document lines;
  fee-ness is not a model property. Leave flat-fee RateScheme and
  adjustment-example ("rush fee") language alone.
- [ ] **Step 2: Commit** `docs: fee removal pass across designs + ui-flows`.

### Task 12: Final verification

- [ ] **Step 1:** Full backend suite, fresh DB, foreground:
  `python manage.py test --noinput` (no `--keepdb`). Read the summary line.
- [ ] **Step 2:** `cd frontend && npm run test:run` — full Vitest.
- [ ] **Step 3:** `cd e2e && npx playwright test` — full e2e (if not already
  green in Task 10 after all later commits).
- [ ] **Step 4:** `grep -rn "\bFee\b" apps/ nealsdata/ frontend/src --include='*.py' --include='*.svelte' --include='*.js'`
  minus the allowed survivors (flat_fee helpers, better-fees spec references,
  `#fee2e2` hex, "feeds") — confirm nothing else remains.
- [ ] **Step 5: Commit** any stragglers; report done for RM review. **Do not
  merge, push, or open a PR.**

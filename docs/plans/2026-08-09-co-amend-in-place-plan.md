# CO Amend-in-Place Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the change-order surface as "amend the agreement in place" per
spec `docs/plans/2026-08-06-better-fees.md` §9.3 and the six RM decisions in
§11 (2026-08-09): server-composed amended-agreement view, acceptance-time
backing inheritance for replacements, stored descope provenance, CO
adjustment-line amendment, single-CO scope, docsurface-kit three-mode UI.

**Architecture:** Schema first (CO adjustment triple, `descoped_by` stamps),
then the acceptance semantic change (replace = claims move, remove = stamp +
retire), then the server-side amended-agreement composition + CO authoring
claims (a `BaseWizardService` subclass), then the frontend rebuild on the
docsurface kit, then invoice-side chips, e2e, docs. Each task leaves its
targeted test modules green.

**Tech Stack:** Django 5.2 / DRF / MySQL backend; Svelte 5 + Vitest frontend;
Playwright e2e.

## Global Constraints

- Branch: **`feature/better-fees`** — commit every task there. Never create or
  switch branches.
- **Never write to the dev database.** No `manage.py migrate`, no `manage.py
  shell`, no loaddata, no ORM writes outside `manage.py test`. Read-only SELECT
  diagnostics are allowed.
- Django tests: always `--noinput`; never run two Django test processes at once
  (hook-enforced); **run tests in the FOREGROUND with a generous timeout —
  never background a test run and wait for a notification.** Judge results by
  the `Ran N tests` / `OK` / `FAILED` summary lines, never by a piped exit code.
- Targeted backend modules per task; the **full backend suite runs fresh-DB
  (NO `--keepdb`) only in Task 4 and Task 12** (migration house rule).
- Frontend: Vitest via `npm run test:run` from `frontend/` (never watch mode);
  full Vitest run before committing any frontend task.
- TDD: write/adjust the failing test first, watch it fail, then implement.
- Error contract: services raise `ValidationError` (field-keyed when the
  problem belongs to an input field); never emit an `'error'` key.
- User-facing text never says "blep" (say "timeslip") or "wizard". Document
  surfaces say **Remove**, never "delete". CO gestures are labeled **"Remove
  via CO"** and **"Replace…"**; the invoice-block reason reads **"Billed on
  INV-NNNN"**.
- Reuse the docsurface kit (`frontend/src/components/docsurface/`) — do not
  invent parallel components; extend the kit only where a prop is genuinely
  missing, matching its existing style.
- **Single-CO scope** (RM decision #5): no chain view, no multi-CO surface
  work. Chain-aware helpers that already exist (`_current_atoms`) stay
  chain-aware; nothing new is built for chains.
- **compose_change_order_diff, the CO PDF, and the customer portal are NOT in
  scope** — they keep baselining on the flat accepted estimate (single-CO
  validated). Task 12 adds a LATER.md note to unify them with the new
  composition later.
- Confirmations only for irreversible actions; every CO-line gesture here is
  undoable (Undo / re-add), so no `confirm()` on them.

**Settled design decisions this plan implements** (spec §11, RM 2026-08-09,
plus resolutions taken in planning):

1. Replace lines become **purely commercial**: at acceptance the target's
   claims MOVE to the replacement (`revise_estimate` move-the-source-rows
   pattern per line); replace never crystallizes or retires atoms. New model
   rule: `ACTION_REPLACE` lines may not carry
   `service_item`/`inventory_item`/`is_material` (new work = remove + add, or
   post-acceptance job edits). Known consequence: after CO acceptance the
   original estimate line's backing chip degrades to hand-line (its claims
   genuinely moved) — the estimate is a historical record with the "amended"
   badge, acceptable.
2. Remove = stamp `descoped_by` on the line's current atoms, then retire
   exactly as today (cancel pending task / release pending material; billed or
   consumed reality untouched).
3. Descope provenance is stored (`Task.descoped_by`, `Material.descoped_by`
   FKs → ChangeOrder); `struck_atom_keys` dies; a data migration backfills
   legacy accepted-CO remove **and** replace targets (old replace semantics
   retired atoms, so legacy replace targets were struck).
4. CO add-lines can claim job atoms at authoring time
   (`ChangeOrderWizardService`, subclassing `EstimateWizardService`);
   `ChangeOrder.save()` already releases claims on dead statuses, so a
   discarded/rejected draft costs nothing. Acceptance already skips
   crystallization when `li.sources.exists()`.
5. Adjustment amendment: `ChangeOrderLineItem` gains the estimate's adjustment
   triple, valid only on a REPLACE targeting an adjustment line; price is
   `percent/100 × Σ` amended-agreement non-adjustment lines (respecting target
   categories), recomputed after every CO line mutation.

---

### Task 1: Schema + model rules

**Files:**
- Modify: `apps/estimates/models.py` (`ChangeOrderLineItem` ~638–714: new
  fields + `clean()` additions)
- Modify: `apps/jobs/models.py` (Task: `descoped_by`)
- Modify: `apps/inventory/models.py` (Material: `descoped_by`)
- Create: migrations in `estimates`, `jobs`, `inventory` (schema only — the
  backfill data migration is Task 4)
- Test: `tests/test_change_order_model.py` (new validation tests; update any
  existing tests that build descriptor-carrying replace lines)

**Interfaces (produces):**
- `ChangeOrderLineItem.adjustment_service` (FK `jobs.RateScheme`, SET_NULL,
  null/blank, provenance-only — mirror `EstimateLineItem.adjustment_service`'s
  on_delete/help_text exactly), `adjustment_percent`
  (Decimal, same max_digits/decimal_places/null as the estimate field),
  `adjustment_target_categories` (M2M `core.AccountingCategory`, blank).
- `Task.descoped_by` / `Material.descoped_by`: 
  `models.ForeignKey('estimates.ChangeOrder', null=True, blank=True,
  on_delete=models.SET_NULL, related_name='+')` — help_text: "Accepted change
  order whose remove struck the agreement line this atom backed. Stamped at CO
  acceptance; drives the billing pool's 'descoped' badge."
- New `clean()` rules on `ChangeOrderLineItem`:
  - `ACTION_REPLACE` may not carry `service_item` / `inventory_item` /
    `is_material` (message: `'action="replace" amends the commercial line only
    — it cannot carry a service item, inventory item, or material marker. Use
    remove + add to change the work.'`).
  - Adjustment fields (`adjustment_service`/`adjustment_percent`) are only
    valid on an `ACTION_REPLACE` whose `target_line_item` is itself an
    adjustment line (`target.adjustment_service_id is not None`); everywhere
    else raise.

- [ ] **Step 1: Failing tests** in `tests/test_change_order_model.py`:
  (a) replace line with `service_item` → ValidationError; with
  `inventory_item` → ValidationError; with `is_material=True` →
  ValidationError; (b) `adjustment_percent` on an add line → ValidationError;
  on a replace targeting a non-adjustment line → ValidationError; on a replace
  targeting an adjustment line → valid; (c) `Task.descoped_by` /
  `Material.descoped_by` settable and SET_NULL on CO delete.
- [ ] **Step 2:** Run `tests.test_change_order_model` — new tests FAIL.
- [ ] **Step 3: Implement** fields + clean rules; run `makemigrations`
  (never `migrate`). Grep existing tests for replace lines built with
  descriptors (`test_change_order_acceptance`, `test_change_order_lifecycle`,
  `test_change_order_api`) — rewrite those *setups* minimally so this task's
  modules pass; the acceptance-behavior assertions themselves are rewritten in
  Task 3, so where a test's whole premise is descriptor-replace
  crystallization, convert it to the remove+add shape or skip-mark it with a
  `# rewritten in Task 3` note and list it in the report.
- [ ] **Step 4:** Run `tests.test_change_order_model`,
  `tests.test_change_order_lifecycle`, `tests.test_change_order_api`,
  `tests.test_change_order_acceptance` — green (with any Task-3-pending skips
  explicitly reported).
- [ ] **Step 5: Commit** `feat: CO line adjustment fields, descoped_by stamps, replace-is-commercial model rules`.

### Task 2: Live-invoice guard on remove/replace targets

**Files:**
- Modify: `apps/estimates/change_order_service.py` (`add_line_item` :407,
  `update_line_item` :502)
- Test: `tests/test_change_order_lifecycle.py` (or a new
  `tests/test_co_live_invoice_guard.py`)

**Interfaces (produces):**
- `ChangeOrderService._assert_target_not_billed(target_line_item)` — raises
  `ValidationError({'target_line_item': ['Billed on INV-NNNN — remove it from
  that invoice before amending this line.']})` when a live (non-cancelled)
  invoice line references the target. Match the "live" definition used by
  `InvoiceService.remaining_agreement_lines` /
  `_assert_agreement_line_unclaimed` (`apps/invoicing/services.py` ~356–430)
  exactly:

```python
    @staticmethod
    def _assert_target_not_billed(target_line_item):
        from apps.invoicing.models import Invoice, InvoiceLineItem
        ref = (InvoiceLineItem.objects
               .filter(agreement_estimate_line=target_line_item)
               .exclude(invoice__status=Invoice.STATUS_CANCELLED)
               .select_related('invoice')
               .first())
        if ref is not None:
            raise ValidationError({'target_line_item': [
                f'Billed on {ref.invoice.display_number} — remove it from '
                f'that invoice before amending this line.']})
```

  Called from `add_line_item` and `update_line_item` whenever the (resulting)
  action is `remove`/`replace` and a `target_line_item` is set (including
  retargeting an existing line).

- [ ] **Step 1: Failing tests:** CO remove targeting an estimate line
  referenced by a draft invoice line → 400 with the field-keyed message; same
  for replace; a CANCELLED invoice's reference does not block; retargeting via
  `update_line_item` onto a billed line also blocks.
- [ ] **Step 2:** Run the module — FAIL.
- [ ] **Step 3: Implement**, verifying the exclusion set against
  `remaining_agreement_lines` (if that helper treats more statuses as dead,
  mirror it and say so in the report).
- [ ] **Step 4:** Module green; also run `tests.test_change_order_api`.
- [ ] **Step 5: Commit** `feat: block CO remove/replace on agreement lines with a live invoice reference`.

### Task 3: Acceptance rewrite — claims move, descope stamped, stored provenance consumed

**Files:**
- Modify: `apps/estimates/co_acceptance.py` (docstring; REPLACE path :78–95;
  `_mirror_of` :147–172 deleted; mirror arms of `_crystallize` :235–266
  deleted; remove path :97–99 stamps)
- Modify: `apps/estimates/change_order_service.py` (`struck_atom_keys` :91
  deleted)
- Modify: `apps/invoicing/services.py` (`get_source_pool` ~985–1130: struck
  set replaced by stored `descoped_by` reads)
- Test: `tests/test_change_order_acceptance.py` (major rewrite),
  `tests/test_co_struck_badge.py` (rewrite against stored provenance)

**Interfaces:**
- Consumes: Task 1's fields and model rules.
- Produces: REPLACE acceptance = **move claim rows**; new pool atom key
  `descoped_by_co_number` (change_order_number string or None);
  `struck_from_agreement` boolean retained (now
  `descoped_by_id is not None`, still suppressed on cancelled tasks).
  `on_accept` counts stay `{'tasks_created','materials_created',
  'tasks_cancelled','materials_removed'}` (replaces now contribute 0 to all
  four).

New REPLACE handler (replaces the crystallize+retire block):

```python
        for li in replaces:
            if li.sources.exists():          # already inherited (re-run)
                continue
            ChangeOrderAcceptanceService._move_claims_to(li)

    @staticmethod
    def _move_claims_to(replace_li):
        """Backing inheritance (spec §9.3 / §11 #1): the target line's current
        claim rows move to the replacement — same move-the-source-rows pattern
        as revise_estimate, applied to one line. Chain-aware: if a prior
        accepted CO already replaced this target, the rows live on that CO
        line's sources instead of the estimate line's."""
        from apps.estimates.models import (
            ChangeOrder, ChangeOrderLineItem, ChangeOrderLineItemSource)
        target = replace_li.target_line_item
        if target is None:
            return
        prior = (ChangeOrderLineItem.objects.filter(
                     target_line_item=target,
                     action=ChangeOrderLineItem.ACTION_REPLACE,
                     change_order__status=ChangeOrder.STATUS_ACCEPTED,
                     sources__isnull=False)
                 .exclude(pk=replace_li.pk)
                 .order_by('-change_order__closed_date',
                           '-change_order__change_order_id', '-line_number')
                 .distinct().first())
        rows = list(prior.sources.all()) if prior is not None else list(target.sources.all())
        for row in rows:
            ChangeOrderLineItemSource.objects.create(
                change_order_line_item=replace_li,
                source_type=row.source_type, source_pk=row.source_pk)
            row.delete()
```

New REMOVE handler (stamp before retire — the non-retirable atoms are exactly
the ones the pool badge exists for):

```python
        for li in removes:
            for source_type, atom in ChangeOrderAcceptanceService._current_atoms(li.target_line_item):
                atom.descoped_by = co
                atom.save()
                ChangeOrderAcceptanceService._retire(job, source_type, atom, counts)
```

Pool change in `get_source_pool`: delete the `struck = …struck_atom_keys(job)`
block; task/material queries gain `.select_related('descoped_by')`; each atom
dict emits:

```python
                'descoped_by_co_number': (
                    task.descoped_by.change_order_number
                    if task.descoped_by_id else None),
                'struck_from_agreement': (
                    task.descoped_by_id is not None
                    and task.status != Task.STATUS_CANCELLED),
```

(materials: same two keys, no cancelled-suppression clause).

- [ ] **Step 1: Failing tests** in `tests.test_change_order_acceptance`:
  (a) replace of a task-backed line → target's `EstimateLineItemSource` rows
  gone, identical `ChangeOrderLineItemSource` rows on the CO line, the Task
  itself untouched (same pk, same status, NOT cancelled), counts all zero for
  the replace; (b) replace of a plain/adjustment line → no-op beyond the
  document; (c) re-run idempotent (sources exist → skip); (d) remove →
  `descoped_by == co` stamped on the atom AND retire behavior unchanged
  (pending task cancelled, pending material released, consumed/invoiced
  material left alone but still stamped); (e) adds unchanged incl.
  authored-sources skip. In `tests.test_co_struck_badge`: pool rows carry
  `descoped_by_co_number` for stamped atoms; cancelled-task suppression holds;
  replace targets no longer flagged.
- [ ] **Step 2:** Run both modules — FAIL.
- [ ] **Step 3: Implement**; delete `_mirror_of` and the two mirror arms in
  `_crystallize`; delete `struck_atom_keys`; rewrite the module docstring's
  remove/replace paragraphs to the new semantics; grep for remaining
  `struck_atom_keys` references (none may survive).
- [ ] **Step 4:** Run `tests.test_change_order_acceptance`,
  `tests.test_co_struck_badge`, `tests.test_change_order_lifecycle`,
  `tests.test_change_order_model`, `tests.test_invoice_wizard` (pool shape),
  `tests.test_agreement_composition` — green; un-skip anything parked in
  Task 1.
- [ ] **Step 5: Commit** `feat: CO acceptance — replace moves claims, remove stamps stored descope provenance`.

### Task 4: Descope backfill migration + fresh-DB full suite

**Files:**
- Create: `apps/estimates/migrations/00XX_backfill_descoped_by.py` (RunPython;
  depends on Task 1's three schema migrations)
- Test: `tests/test_descope_backfill_migration.py` (direct-call pattern —
  copy the structure of `tests/test_fee_purge_migrations.py`, importlib for
  the digit-leading module name)

**Interfaces:** the migration function `stamp_descoped_atoms(apps,
schema_editor)` uses historical models only: for each ACCEPTED ChangeOrder,
its remove **and** replace lines' `target_line_item` → that line's
`EstimateLineItemSource` rows → stamp the referenced Task/Material's
`descoped_by = co` (skip rows whose atom no longer exists; later-accepted CO
wins if several target the same line). Replace targets are included because
LEGACY replace semantics retired the old atom (this is a one-time historical
stamp; new acceptances stamp removes only). Reverse = noop.

- [ ] **Step 1: Failing test:** plant an accepted CO with a remove line and a
  replace line targeting claimed estimate lines (claims via ORM), plus an
  unrelated claimed line; call the migration function with
  `django.apps.apps`; assert both targets' atoms stamped with the CO,
  unrelated atom untouched, dangling source row skipped without error.
- [ ] **Step 2:** Test FAILS (module doesn't exist).
- [ ] **Step 3:** Write the migration; test passes.
- [ ] **Step 4: Full backend suite, fresh DB:**
  `python manage.py test --noinput` (NO `--keepdb`), foreground, generous
  timeout; judge by the `Ran N tests` summary. Fix fallout.
- [ ] **Step 5: Commit** `feat: backfill descoped_by from legacy accepted-CO targets`.

### Task 5: compose_amended_agreement + the amended-agreement endpoint

**Files:**
- Modify: `apps/estimates/agreement.py` (`_line_dict_from_co_item` :43 —
  adjustment emission; new `compose_amended_agreement(co)`)
- Modify: `apps/api/change_orders/views.py` (new GET action),
  `apps/api/change_orders/serializers.py` (adjustment fields on the line
  serializer)
- Test: `tests/test_amended_agreement.py` (new),
  `tests/test_agreement_composition.py` (adjustment emission)

**Interfaces (produces):**
- `_line_dict_from_co_item` now reads the CO line's own adjustment triple
  (same shape `_line_dict_from_estimate_item` emits: `is_adjustment`,
  `adjustment_service_id`, `percent`, `target_category_ids`) instead of
  hardcoding falsey — so an accepted adjustment-replace flows into
  `compose_agreement` and the invoicing agreement-adjustments pass-through
  correctly.
- `compose_amended_agreement(co)` returns
  `{'rows': [...], 'original_total', 'co_delta', 'revised_total'}`.
  Baseline = the estimate + accepted COs that precede `co` in acceptance
  order (for a draft/open CO that is every accepted CO; for an accepted CO,
  those accepted before it — so the record view never double-applies).
  Reuse `compose_agreement`'s folding logic against that baseline (factor a
  private `_compose(estimate, cos)` helper both call rather than duplicating
  the fold). Then apply `co`'s lines. Row kinds:
  - `{'kind': 'agreement', 'line': <line dict>, 'billed_on': 'INV-0012'|None,
     'adjustment_expected_amount': '123.40'|None}` — an untouched baseline
    line. `billed_on` = the display_number of the live invoice referencing it
    (same liveness rule as Task 2; look up via `agreement_estimate_line` /
    `agreement_co_line` per the line's identity). For an untouched adjustment
    line, `adjustment_expected_amount` = what
    `compute_adjustment_amount`-style math yields against the amended
    non-adjustment rows — None when it equals the stored amount (the UI's
    "stale adjustment" hint).
  - `{'kind': 'replaced', 'line': <dict from CO line>, 'original': <baseline
     dict>, 'co_line_id', 'co_index': n}`
  - `{'kind': 'removed', 'original': <baseline dict>, 'co_line_id'}` — the
    strike is the row; no own line.
  - `{'kind': 'added', 'line': <dict from CO line>, 'co_line_id',
     'co_index': n}`
  - `co_index` numbers the CO's add+replace lines 1… in `line_number` order
    (the UI renders "CO 1", "CO 2"…). Removes get no index.
  - Totals: `original_total` = baseline grand total; `revised_total` = Σ of
    surviving rows (`agreement` + `replaced` + `added` amounts); `co_delta` =
    revised − original.
- `GET /api/change-orders/{id}/amended-agreement/` (read =
  `IsAuthenticated`, matching the viewset's read permissions): serializes the
  rows plus per-row display extras the edit view needs:
  - on `agreement` rows whose line is estimate-origin: `backing` +
    `backing_total` from `derive_estimate_backing` /
    `get_backing_total` against the resolved `EstimateLineItem` (chips render
    on every row in the wireframe); CO-origin baseline lines (accepted prior
    COs — rare under single-CO) may emit `backing: null`.
  - on `replaced`/`added` rows: `backing` + `backing_total` (see below) and
    `sources` (serialized like the estimate line serializer's `sources`
    block: source_id/source_type/description/qty/units/rate/
    computed_amount); on `replaced` rows the sources are the TARGET's
    still-unmoved claim rows presented as the inherited preview, each with
    `'inherited_from_line': <target line_number>`; on `added` rows the CO
    line's own authored claims.
  - Backing derivation: for `added` rows call
    `derive_estimate_backing(co_line)` (`apps/api/estimates/serializers.py`
    :28 — already duck-typed; CO lines have every attribute it reads). For
    `replaced` rows compute the same classification but summing the TARGET's
    resolvable sources against the CO line's qty/price (in-sync →
    planned_work/planned_materials; out-of-sync → `edited` with
    `backing_total`); package as a small
    `derive_co_line_backing(co_line)` helper in
    `apps/api/change_orders/serializers.py`.
- `ChangeOrderLineItemSerializer` gains `adjustment_service`,
  `adjustment_percent`, `adjustment_target_categories` (read via the default
  M2M pk list), all read-only here (writes go through the service in Task 6).

- [ ] **Step 1: Failing tests** (`tests.test_amended_agreement`): composition
  with an untouched line, a replace, a remove, an add → row kinds, co_index
  order, three totals; billed_on populated from a live draft invoice and
  absent for a cancelled one; accepted-CO record view doesn't double-apply;
  adjustment_expected_amount appears when a CO remove makes an estimate
  adjustment stale and is None when in sync; endpoint returns 200 with
  backing + inherited sources on a replace row. In
  `tests.test_agreement_composition`: an accepted adjustment-replace CO line
  emits is_adjustment/percent/targets.
- [ ] **Step 2:** Run both — FAIL.
- [ ] **Step 3: Implement** (factor the fold helper; don't fork the fold).
- [ ] **Step 4:** Run `tests.test_amended_agreement`,
  `tests.test_agreement_composition`, `tests.test_change_order_api`,
  `tests.test_invoice_seeding` (composition consumers) — green.
- [ ] **Step 5: Commit** `feat: server-composed amended agreement + endpoint`.

### Task 6: Adjustment-replace service path + recompute

**Files:**
- Modify: `apps/estimates/change_order_service.py` (`add_line_item`,
  `update_line_item`, `delete_line_item`, `reorder_line_items`)
- Modify: `apps/api/change_orders/views.py` (accept `adjustment_percent` in
  line-item create/update payloads — pass through to the service)
- Test: `tests/test_co_adjustment_amendment.py` (new)

**Interfaces (produces):**
- `add_line_item` path: when `action == 'replace'` and the target is an
  adjustment line, the caller supplies `adjustment_percent` (and nothing
  else beyond description); the service copies `adjustment_service` and
  `adjustment_target_categories` from the target, sets `qty=1`,
  `units=target.units`, `accounting_category=target.accounting_category`,
  `description = description or target.description`, and computes `price`
  (below). A replace of an adjustment line WITHOUT `adjustment_percent`
  keeps the target's percent (copied) — the author edited the description
  only.
- `ChangeOrderService.recompute_adjustment_replaces(co)` — for each CO line
  with `adjustment_service_id`, recompute
  `price = (adjustment_percent/100 × Σ amount of surviving amended
  non-adjustment rows whose accounting_category_id is in the target set
  (empty set = all))`, quantized to cents, save if changed. Basis rows come
  from `compose_amended_agreement(co)`'s surviving rows minus adjustment
  lines — no recursion (adjustments never stack). Called at the end of
  `add_line_item`, `update_line_item`, `delete_line_item`,
  `reorder_line_items` (reorder for completeness/cheapness), and by Task 7's
  atom mutations. It is fine that `LineItemService`'s internal
  `recompute_adjustments` runs first with sibling-basis math — this call runs
  after, in the same transaction, and overwrites with the amended-basis
  value.

- [ ] **Step 1: Failing tests:** (a) adjustment-replace of a 10% rush fee to
  5% → CO line has copied service/targets, price = 5% of the amended
  non-adjustment total; (b) targeted categories respected; (c) adding a CO
  add-line afterwards re-raises the adjustment-replace price; (d) removing an
  estimate line via CO lowers it; (e) percent-less replace copies the
  target's percent; (f) API create with `adjustment_percent` round-trips;
  (g) acceptance of the adjustment-replace changes no atoms and the composed
  agreement's adjustment line carries the new percent/price.
- [ ] **Step 2:** Run module — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `tests.test_co_adjustment_amendment`,
  `tests.test_change_order_api`, `tests.test_amended_agreement`,
  `tests.test_agreement_adjustments` (invoicing pass-through, if that module
  name differs, the agreement-adjustments tests wherever they live) — green.
- [ ] **Step 5: Commit** `feat: CO adjustment-line amendment with amended-basis recompute`.

### Task 7: CO authoring claims — wizard service + endpoints

**Files:**
- Modify: `apps/estimates/services.py` (new `ChangeOrderWizardService` at the
  bottom, subclassing `EstimateWizardService`; `EstimateWizardService
  .get_source_pool` gains CO-claim awareness)
- Modify: `apps/estimates/change_order_service.py`
  (`assert_all_bare_add_lines_have_ac` :120 — sources-exempt)
- Modify: `apps/api/change_orders/views.py` (four actions mirroring the
  estimate viewset's: `source-pool`, `line-items-from-atoms`,
  `line-items/{pk}/add-atoms`, `line-items/{pk}/remove-atoms` — copy the
  estimate versions at `apps/api/estimates/views.py` :122–210, permissions
  `IsAuthenticated` read / `CanManageJobOrPM` writes like the rest of the
  viewset)
- Test: `tests/test_co_authoring_claims.py` (new),
  `tests/test_estimates_services.py` (pool cross-lens)

**Interfaces (produces):**
- `ChangeOrderWizardService(EstimateWizardService)` overriding:
  `container_attr = 'change_order'`, `source_fk = 'change_order_line_item'`,
  `_line_item_model` → ChangeOrderLineItem, `_source_model` →
  ChangeOrderLineItemSource, `_validate_draft` → CO must be
  `STATUS_DRAFT`. The base's `add_atoms_to_new_line_item` constructs the
  line without `action` — override to inject `action='add'` (add a
  `_extra_line_kwargs()` hook returning `{'action': ChangeOrderLineItem
  .ACTION_ADD}` in `BaseWizardService` defaulting to `{}`, and splat it in
  the constructor — smallest seam, keeps the estimate/invoice paths
  byte-identical).
  `add_atoms_to_line_item` must refuse non-`add` CO lines
  (`ValidationError('Atoms attach to CO add lines only — a replacement
  inherits its backing at acceptance.')`).
  `get_source_pool(co)` — same atom walk as the estimate pool, but the claim
  lookup unions BOTH lenses: the job's `EstimateLineItemSource` rows
  (claimed_by_other: "Claimed by estimate EST-N" — covered work is not
  CO-addable) and the job's `ChangeOrderLineItemSource` rows
  (claimed_by_current when on THIS co, else claimed_by_other "Claimed by
  CO-N").
- `EstimateWizardService.get_source_pool` symmetric fix: its claim lookup
  additionally marks atoms claimed by any of the job's CO lines as
  `claimed_by_other` (note text "Claimed by change order <number>") — closes
  the new cross-lens double-claim hole.
- `assert_all_bare_add_lines_have_ac` adds `sources__isnull=True` to its
  filter (an authored-claimed add line is not a bare hand line; estimate-side
  guard already exempts sourced lines).
- Every atom mutation endpoint ends with
  `ChangeOrderService.recompute_adjustment_replaces(co)` (Task 6).

- [ ] **Step 1: Failing tests:** (a) CO source-pool marks estimate-claimed
  atoms claimed_by_other, this-CO claims claimed_by_current; (b)
  line-items-from-atoms creates an `action='add'` CO line with source rows +
  derived values (single-atom copy rule); (c) add-atoms onto an add line
  works, onto a replace line → 400; (d) remove-atoms deletes the line when
  the last source goes; (e) discarding the draft CO releases the claims
  (existing `release_change_order_claims` — pin it); (f) send guard no longer
  trips on a sourced AC-less add line; (g) estimate pool shows a CO-claimed
  atom as claimed_by_other; (h) accepting a CO with an authored-claimed add
  line crystallizes nothing for it (sources exist) and the claims survive.
- [ ] **Step 2:** Run modules — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `tests.test_co_authoring_claims`,
  `tests.test_estimates_services`, `tests.test_change_order_acceptance`,
  `tests.test_change_order_api`, `tests.test_dead_document_claims` (claim
  release) — green.
- [ ] **Step 5: Commit** `feat: CO authoring claims — wizard service, pool, atom endpoints`.

### Task 8: Frontend — COEditView + gesture-driven modal

**Files:**
- Create: `frontend/src/components/changeorders/COEditView.svelte`
- Rewrite: `frontend/src/components/changeorders/COLineItemModal.svelte`
- Modify: `frontend/src/components/changeorders/ChangeOrderPanel.svelte`
  (swap COLineItemsSection → COEditView; load `amended-agreement` +
  `source-pool`; keep toolbar/status/deliverables/send flows untouched)
- Delete: `frontend/src/components/changeorders/COLineItemsSection.svelte`
- Modify: `frontend/src/lib/changeOrderDiff.js` (drop `buildMergedRows`
  and `lineDiffTotals`; keep `buildDeliverableRows`)
- Test: `frontend/tests/` — new `COEditView.test.js`; rewrite
  `COLineItemModal.test.js`, `ChangeOrderPanel.test.js`; trim
  `changeOrderDiff.test.js`

**Interfaces:** COEditView is presentation + gestures only (EstimateEditView's
contract: panel owns loading, view calls `onChanged()`); props
`{co, canEdit, amended, sourcePool, categories, defaultMaterialCategoryId,
onChanged}`. Layout per spec §9.3 — one `.data-table doc-edit-table` of the
amended agreement:

- `agreement` rows: line fields + BackingChip (from the row's `backing` /
  `backing_total`; no chip when null) + actions
  **Remove via CO** / **Replace…** (Replace on an adjustment line opens the
  modal's adjustment variant). When `billed_on` is set, both buttons render
  `disabled` with `title="Billed on {billed_on}"` and a small caption
  "billed on {billed_on}". When `adjustment_expected_amount` is set, a small
  muted caption: `recomputes to {amount} if replaced`.
- `replaced` rows: CO-tinted (`.co-authored` row class, light tint consistent
  with app.css palette), numbered `CO {co_index}`, showing the replacement
  line; beneath it the struck original (`.struck` — parenthesized amount,
  excluded from totals) and the inherited-preview AtomChildRows (each with
  small text `inherited from line {inherited_from_line}`); actions **Edit** /
  **Undo** (Undo = DELETE the CO line).
- `removed` rows: the original struck in place, amount parenthesized;
  action **Undo**.
- `added` rows: CO-tinted, `CO {co_index}`, own AtomChildRows from `sources`,
  BackingChip; actions **Edit** / **Remove**; **Add selected here** appears on
  added rows while the pool selection is non-empty (add-atoms endpoint).
- Table foot: `NewLineFromSelectedRow` (creates via
  `line-items-from-atoms`, then opens the Edit modal on the fresh line — same
  await-refresh pattern as EstimateEditView's `openModalForCreatedLine`), and
  a totals block **original / this CO / revised** from the payload's three
  totals.
- Below the table: "Add line" button → existing PriceListPicker →
  COAddLineForm (unchanged), and `UncoveredWorkSection` (title "Uncovered
  work", subtitle "Tasks and materials from this job not covered by the
  agreement.", rows from the CO source-pool, same selectable/claimed mapping
  as EstimateEditView, directLabel "Add as its own line").
- COLineItemModal rewrite: gestures preset everything — no action or target
  selects remain. Three variants driven by props: **edit-fields**
  (description/qty/units/price; AC only for add lines),
  **replace-prefill** (same fields, prefilled from the original, POSTs
  `{action:'replace', target_line_item, …}`), **adjustment**
  (description + percent input, shows the computed amount readback after
  save; POSTs/PATCHes `adjustment_percent`). 409 claim conflicts route
  through the same refresh-and-toast pattern as EstimateEditView's
  `handleMutationError`.
- All mutations call the existing endpoints (`line-items` CRUD,
  Task 7 atom endpoints), then `onChanged()`.

- [ ] **Step 1: Failing Vitest** for COEditView: renders four row kinds with
  strikes/tints/CO numbering; billed_on disables both gesture buttons; Undo
  fires DELETE; new-line-from-selected fires the atoms POST; adjustment
  Replace opens percent variant. Modal tests per variant.
- [ ] **Step 2:** Run `npm run test:run` — new tests FAIL.
- [ ] **Step 3: Implement** (match EstimateEditView's structure/idioms —
  colspan constants, silent-refresh contract, `.preserve-breaks`,
  `<tbody>` wrapping).
- [ ] **Step 4:** Full `npm run test:run` green.
- [ ] **Step 5: Commit** `feat: CO edit surface — amended agreement in place`.

### Task 9: Frontend — CO panel modes, customer delta view, reorder, chips

**Files:**
- Modify: `frontend/src/components/changeorders/ChangeOrderPanel.svelte`
- Create: `frontend/src/components/changeorders/COCustomerView.svelte`
- Test: `frontend/tests/ChangeOrderPanel.test.js` (+ new
  `COCustomerView.test.js`)

**Interfaces:**
- DocModeBar exactly as EstimatePanel wires it (:122–138): modes
  `['edit','customer','reorder']` when `canManageJobs && isDraft`, else
  `['edit','customer']`; mode memory key `co:{coId}` via
  `getJobWs`/`rememberMode` (the store is key-generic — no store change);
  reorder falls back to edit when not editable.
- Toolbar gains the standard date stat-chips (Created / Sent / Expires /
  Closed), same markup/CSS as EstimatePanel :359–376, always rendered with
  muted `-` when empty.
- **Customer view** (COCustomerView): the conventional delta document —
  only the changed lines: replaced → the revised line with a delta-amount
  column (`new − old`), removed → the original with its amount negated,
  added → its amount; footer rows **Change total** (`co_delta`) and
  **Revised agreement total** (`revised_total`). Title
  `Change Order {change_order_number}`. Reuse DocCustomerView's CSS classes
  / visual grammar (it's a sibling, not a wrapper — DocCustomerView's props
  don't fit a delta table).
- **Reorder view**: DocReorderView over the CO's OWN add+replace rows
  (label each `CO {co_index} — {description}`); `onReorder` builds the
  reorder payload from the add+replace ids in their new order **with the
  CO's remove-line ids appended at the end in their existing order** (the
  reorder endpoint renumbers every listed line from 1; omitting removes
  would collide).
- Deliverables section renders in edit mode only.

- [ ] **Step 1: Failing Vitest:** mode bar renders and remembers `co:{id}`;
  customer view shows delta rows/negated removals/two totals; reorder payload
  appends remove ids; chips render with `-` placeholders.
- [ ] **Step 2:** `npm run test:run` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Full `npm run test:run` green.
- [ ] **Step 5: Commit** `feat: CO panel — Views modes, customer delta view, reorder, date chips`.

### Task 10: Invoice-side UI — descoped chip + CO provenance label

**Files:**
- Modify: `apps/api/invoicing/serializers.py` (agreement_ref block ~30–52:
  add CO provenance fields)
- Modify: `frontend/src/components/invoices/InvoiceEditView.svelte`
  (descoped chip stub :277–296; reference text)
- Modify: the lib holding `estReferenceText` (grep `estReferenceText` under
  `frontend/src/lib/`) + its tests
- Test: `tests/test_invoice_api.py` (or wherever agreement_ref is pinned),
  `frontend/tests/InvoiceEditView.test.js`

**Interfaces:**
- The serialized `agreement_ref` gains, for `kind == 'change_order'`:
  `'co_number': ref.change_order.change_order_number` and
  `'co_line_number': ref.line_number` (null/absent for estimate refs).
- New lib helper `coShortLabel(changeOrderNumber)` → `"CO-1"` from the
  trailing `-CO<n>` suffix, falling back to the full number when the suffix
  is absent. Reference text for CO-origin lines reads
  `{coShortLabel} line {co_line_number}` (spec §9.3 "CO-N line M");
  estimate-origin text unchanged.
- The pool atom rows (invoice wizard payload already carries
  `descoped_by_co_number` from Task 3): the stub chip at InvoiceEditView
  :277–296 renders `descoped by {coShortLabel(descoped_by_co_number)}`
  (amber/badge styling consistent with the existing cancelled-task badge);
  suppression on cancelled tasks comes from the server flag as today.

- [ ] **Step 1: Failing tests:** serializer emits co_number/co_line_number on
  a CO-origin seeded line and omits them on estimate-origin; Vitest —
  descoped chip renders from `descoped_by_co_number`; CO-origin reference
  text says "CO-1 line 2"; `coShortLabel` unit cases.
- [ ] **Step 2:** Run both sides — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Backend module + full `npm run test:run` green.
- [ ] **Step 5: Commit** `feat: descoped-by-CO chip and CO-line provenance on invoicing surfaces`.

### Task 11: E2E — amend-in-place flows

**Files:**
- Rewrite: `e2e/specs/change-orders/co-room-and-diff.spec.js` (the room is a
  new surface now)
- Create: `e2e/specs/change-orders/amend-in-place.spec.js`
- Possibly modify: the e2e seed (only if no seeded job offers an accepted
  estimate + held job + billable atoms; check first — the existing CO specs
  imply one exists). Follow `docs/designs/e2e-testing.md` conventions.

Coverage (both files together):
- Remove via CO strikes the row in place (parenthesized amount, revised total
  drops); Undo restores.
- Replace… prefilled modal → tinted CO row over struck original with
  "inherited from line N" child rows; footer original/this CO/revised totals.
- Add line from the uncovered pool via "New line from selected" → tinted CO
  add row carrying the atom.
- A line billed on a live invoice shows both gestures disabled with the
  "billed on" reason.
- Mode bar: Customer shows the delta document; Reorder moves a CO line.
- Accept the CO → job un-held, estimate badge "amended", invoice pool shows
  the descoped chip for a removed line's surviving atom (drive a task to
  complete first so it survives retire), and a new invoice seeds the
  replacement line with "CO-1 line N" provenance.

- [ ] **Step 1:** Write the specs; run `npx playwright test
  specs/change-orders/` from `e2e/` (own servers/DB; foreground).
- [ ] **Step 2:** Iterate to green; note any catalogued pre-existing flakes
  rather than chasing them.
- [ ] **Step 3: Commit** `test(e2e): CO amend-in-place coverage`.

### Task 12: Docs + final verification

**Files:**
- Modify: `docs/designs/estimates-and-prices.md` (CO surface §: amend-in-place
  view, claim-move at acceptance, adjustment amendment, authoring claims,
  live-invoice block, amended-agreement endpoint),
  `docs/designs/invoicing-and-expenses.md` (descoped chip, CO provenance
  label, pool payload keys), `docs/designs/jobs-and-tasks.md`
  (`Task.descoped_by`), `docs/designs/materials-inventory-and-purchasing.md`
  (`Material.descoped_by`), `docs/designs/data-constraints.md` (new fields,
  clean() rules, migrations, the moved-claims invariant),
  `docs/designs/LATER.md` (unify compose_change_order_diff/PDF/portal onto
  compose_amended_agreement)
- Update: `docs/plans/2026-08-06-better-fees.md` §10 — mark the CO phase
  LANDED with a summary line.

- [ ] **Step 1:** Docs pass (grep the docs for `struck_atom_keys`, the old
  CO-room description, and the "adjustments are estimate-only" claim — all
  must be updated).
- [ ] **Step 2: Final verification:** full backend suite fresh-DB
  (`python manage.py test --noinput`, foreground) — read the summary line;
  full `npm run test:run`; e2e already ran in Task 11 (re-run only the
  change-orders + invoices specs if later tasks touched those surfaces).
- [ ] **Step 3:** Residual grep: `struck_atom_keys`, `buildMergedRows`,
  `lineDiffTotals`, `COLineItemsSection` — zero hits outside frozen
  migrations/docs history.
- [ ] **Step 4: Commit** `docs: CO amend-in-place reference updates + spec close-out`.

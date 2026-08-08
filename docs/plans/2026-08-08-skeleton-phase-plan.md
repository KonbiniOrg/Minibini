# Skeleton + Three-Mode Surface — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Invoices auto-seed from the remaining agreement with whole-line
references and a backing model (actuals by default); estimates and invoices
both get the settled three-mode surface (Edit / Customer / Reorder) built
from one shared component kit.

**Architecture:** Backend first — agreement-line references on
`InvoiceLineItem` (one live invoice per agreement line), seeding in
`InvoiceService`, backing derived (never stored) in serializers on both
documents. Then a shared `docsurface` component kit consumed by the new
estimate and invoice edit views; the old two-column wizard presentation
(`ReconcileMode` and friends) is retired once both surfaces migrate. The
CO amend-in-place surface is a FOLLOW-ON plan that reuses this kit — every
shared component here must take its content via props/config, never assume
"estimate or invoice".

**Tech Stack:** Django 5.2 / DRF (services + serializers), Svelte 5 runes,
Vitest, Playwright.

**Design authority:** `docs/plans/2026-08-06-better-fees.md` §7 + §9, and
the wireframe artifact
(https://claude.ai/code/artifact/9e73a22a-b0e2-4cc4-bc9d-816653364fc9).
Build to the artifact; deviations go back through RM.

## Global Constraints

- **DRY (RM directive):** reuse is between the three new surface
  implementations (estimate, invoice, and the follow-on CO surface) and
  with existing CSS. Never build on components that are going away
  (`ReconcileMode.svelte`, `WizardActions.svelte`,
  `WizardLineItemCard.svelte`, `WizardAtomRow.svelte`, both
  `WizardSourcePool.svelte` files) — they are deleted in Task 13.
- **Existing CSS first:** `.data-table`, `.status-badge`, `.row-actions`,
  `.badge-invoiced`, `.small-btn`, `.link-btn` from
  `frontend/src/css/app.css`. New shared classes (backing chips, atom
  child rows, struck rows, placeholder row) go into app.css ONCE — never
  per-component copies.
- Word bans on document surfaces: never "delete" (use Remove / Remove
  from invoice); user-visible "timeslip" never "blep"; backing chip
  vocabulary exactly per spec §9.2.
- Money: format via `fmtMoney`/`formatMoney` from `lib/format.js` /
  `lib/taskTotals.js`; `tabular-nums` on money columns comes with
  `.data-table`.
- Explicit save only — no blur-commits; reversible actions get no
  confirm dialogs.
- Error contract: services raise `ValidationError` (field-shaped when
  field-bound); frontend routes every error through `triageError`.
- Line-item deletes ALWAYS via
  `LineItemService.delete_line_item_with_renumber`.
- Tests: `python manage.py test <module> --noinput`, never piped for
  pass/fail judgment; ONE Django test run at a time; Vitest via
  `npm run test:run` from `frontend/`; full fresh-DB suite + e2e at final
  verification only (this plan adds migrations).
- All commits on `feature/better-fees`. No push, no PR.

## File Structure

```
apps/estimates/agreement.py            # line dicts gain estimate_line_id / co_line_id
apps/invoicing/models.py               # InvoiceLineItem: agreement_estimate_line, agreement_co_line
apps/invoicing/migrations/0023_*.py    # the two FKs
apps/invoicing/services.py             # seeding, remaining/restore/release, invariant
apps/api/invoicing/serializers.py      # agreement_ref + backing (derived)
apps/api/invoicing/views.py            # perform_create seeds; restore endpoint; seed=false
apps/api/estimates/serializers.py      # backing (derived) on estimate lines
apps/core/management/commands/validate_data.py  # one-live-invoice-per-agreement-line check

frontend/src/components/docsurface/    # NEW shared kit (3 consumers: est, inv, CO-later)
  DocModeBar.svelte                    # Edit/Customer/Reorder switcher
  BackingChip.svelte                   # chip renderer, kind -> label/class
  AtomChildRow.svelte                  # nested backing row under a line
  UncoveredWorkSection.svelte          # checkbox list + per-row direct-add button
  NewLineFromSelectedRow.svelte        # dashed placeholder row
  DocCustomerView.svelte               # collapsed read-only document
  DocReorderView.svelte                # customer view + arrows column
frontend/src/components/estimates/EstimateEditView.svelte   # NEW merged editing view
frontend/src/components/invoices/InvoiceEditView.svelte     # NEW seeded editing view
frontend/src/components/estimates/EstimatePanel.svelte      # modes: edit/customer/reorder
frontend/src/components/invoices/InvoicePanel.svelte        # same
frontend/src/css/app.css               # shared surface classes, added once
```

Deleted at the end (Task 13): `frontend/src/components/wizards/` (all
four), `frontend/src/components/invoices/WizardSourcePool.svelte`,
`frontend/src/components/estimates/WizardSourcePool.svelte`.

---

### Task 1: Agreement line identity in `compose_agreement`

**Files:**
- Modify: `apps/estimates/agreement.py` (`_line_dict_from_estimate_item`, the CO-line dict builder, `compose_agreement` docstring)
- Test: `tests/test_agreement_compose.py` (existing module — add tests)

**Interfaces:**
- Produces: every line dict in `compose_agreement(job)['lines']` carries
  `estimate_line_id` (int|None) and `co_line_id` (int|None) — exactly one
  non-null per line. Consumed by Tasks 3 and 5.

- [ ] **Step 1: Write the failing tests** (extend the existing test class that builds an accepted estimate + CO):

```python
def test_lines_carry_estimate_line_identity(self):
    lines = compose_agreement(self.job)['lines']
    est_lines = [l for l in lines if l['origin'] == 'estimate']
    self.assertTrue(est_lines)
    for l in est_lines:
        self.assertIsNotNone(l['estimate_line_id'])
        self.assertIsNone(l['co_line_id'])

def test_co_added_lines_carry_co_line_identity(self):
    lines = compose_agreement(self.job)['lines']
    co_lines = [l for l in lines if l['origin'] == 'change_order']
    self.assertTrue(co_lines)
    for l in co_lines:
        self.assertIsNotNone(l['co_line_id'])
        self.assertIsNone(l['estimate_line_id'])
```

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test tests.test_agreement_compose --noinput`
Expected: FAIL with `KeyError: 'estimate_line_id'`

- [ ] **Step 3: Implement** — in `_line_dict_from_estimate_item` add
`'estimate_line_id': eli.pk, 'co_line_id': None`; in the CO-line dict
builder add `'estimate_line_id': None, 'co_line_id': co_li.pk`. A CO
*replacement* line dict is CO-origin (carries `co_line_id`). Update the
docstring's shape comment.

- [ ] **Step 4: Run the module — all green**

- [ ] **Step 5: Commit** `feat(agreement): line dicts carry their source line identity`

---

### Task 2: Agreement-reference fields on InvoiceLineItem

**Files:**
- Modify: `apps/invoicing/models.py` (InvoiceLineItem)
- Create: `apps/invoicing/migrations/0023_invoiceline_agreement_refs.py` (makemigrations)
- Test: `tests/test_invoicing_models.py` (add class)

**Interfaces:**
- Produces: `InvoiceLineItem.agreement_estimate_line`
  (FK `estimates.EstimateLineItem`, null=True, blank=True,
  on_delete=SET_NULL, related_name='invoice_lines') and
  `InvoiceLineItem.agreement_co_line` (FK `estimates.ChangeOrderLineItem`,
  same shape, related_name='invoice_lines'), plus property
  `agreement_line` returning whichever is set (or None). Consumed by
  Tasks 3, 5, 7.

- [ ] **Step 1: Failing test**

```python
class InvoiceLineAgreementRefTest(TestCase):
    def test_reference_fields_exist_and_default_null(self):
        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        li = InvoiceLineItem.objects.create(
            invoice=inv, description='x', qty=1, units='none', price=Decimal('1'))
        self.assertIsNone(li.agreement_estimate_line)
        self.assertIsNone(li.agreement_co_line)
        self.assertIsNone(li.agreement_line)

    def test_agreement_line_property_returns_the_set_ref(self):
        li = self._line_with(est_line=self.est_line)
        self.assertEqual(li.agreement_line, self.est_line)
```

- [ ] **Step 2: Run — fails (no field)**
- [ ] **Step 3: Add the two FKs + property; run `makemigrations invoicing`**
  (SET_NULL, never CASCADE: an invoice line must survive its agreement
  line vanishing; comment the fields as *reference/provenance for
  seeding + backing — release semantics live in the service, §7.1*)
- [ ] **Step 4: Run module — green. Then, house rule after a migration:**
  run the full suite fresh-DB ONCE at final verification, not here; for
  now run `tests.test_invoicing_models tests.test_api_invoicing --noinput`.
- [ ] **Step 5: Commit** `feat(invoicing): agreement-line reference fields (dormant until seeding)`

---

### Task 3: Seeding, remaining-lines, restore, release, and the invariant

**Files:**
- Modify: `apps/invoicing/services.py` (InvoiceService)
- Test: `tests/test_invoice_seeding.py` (create)

**Interfaces:**
- Consumes: Task 1's line-identity dicts; Task 2's FK fields.
- Produces (all on `InvoiceService`):
  - `seed_from_agreement(invoice) -> int` — creates one line per
    *remaining* agreement line; returns count.
  - `remaining_agreement_lines(job, exclude_invoice=None) -> list[dict]`
    — compose_agreement lines minus those referenced by a live invoice
    (live = not cancelled; `exclude_invoice` lets the restore picker
    exclude the current draft's own refs).
  - `restore_agreement_line(invoice, *, estimate_line_id=None, co_line_id=None) -> InvoiceLineItem`
  - `remove_line(invoice, line_item)` — routes through
    `LineItemService.delete_line_item_with_renumber`, releasing the
    reference and the line's source rows (claims) first.
  Seeded line values: description/qty/units/price straight from the
  agreement dict; AC from the source line's AC. **Claim mirroring:** for
  an estimate-origin line, copy the accepted estimate line's
  `EstimateLineItemSource` rows into `InvoiceLineItemSource` rows on the
  new invoice line — but ONLY atoms that pass the existing billability
  gate (`_assert_atom_billable` logic: task complete, material
  consumed); unbillable atoms are simply not claimed yet (the surface
  shows them via the pool).
  **Invariant:** inside `restore_agreement_line` and `seed_from_agreement`,
  re-check under `select_for_update` on the agreement line's pk that no
  live invoice already references it; raise
  `ValidationError('This agreement line is already on invoice INV-…')`.

- [ ] **Step 1: Failing tests** (fixture: accepted estimate with one
  task-backed line (task complete), one hand line, one adjustment line;
  a second job invoice scenario for the invariant):

```python
def test_seed_creates_one_line_per_remaining_agreement_line(self):
    inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
    n = InvoiceService.seed_from_agreement(inv)
    self.assertEqual(n, 3)
    li = inv.invoicelineitem_set.get(agreement_estimate_line=self.backed_line)
    self.assertEqual(li.qty, self.backed_line.qty)
    self.assertEqual(li.price, self.backed_line.price)

def test_backed_line_mirrors_claims_for_billable_atoms_only(self):
    inv = self._seeded()
    li = inv.invoicelineitem_set.get(agreement_estimate_line=self.backed_line)
    types = set(li.sources.values_list('source_type', flat=True))
    self.assertEqual(types, {'task'})          # complete task claimed
    # the unconsumed material was NOT claimed
    self.assertFalse(li.sources.filter(source_type='material').exists())

def test_hand_line_seeds_without_claims(self):
    inv = self._seeded()
    li = inv.invoicelineitem_set.get(agreement_estimate_line=self.hand_line)
    self.assertFalse(li.sources.exists())

def test_adjustment_line_seeds_with_snapshot_percent(self):
    inv = self._seeded()
    li = inv.invoicelineitem_set.get(agreement_estimate_line=self.adj_line)
    self.assertEqual(li.adjustment_percent, self.adj_line.adjustment_percent)

def test_remove_line_releases_reference_and_claims(self):
    inv = self._seeded()
    li = inv.invoicelineitem_set.get(agreement_estimate_line=self.backed_line)
    InvoiceService.remove_line(inv, li)
    self.assertIn(self.backed_line.pk,
                  [l['estimate_line_id'] for l in
                   InvoiceService.remaining_agreement_lines(self.job)])

def test_agreement_line_on_at_most_one_live_invoice(self):
    inv1 = self._seeded()          # references all three lines
    inv2 = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
    # (one-draft-per-job is DB-enforced; simulate by sending inv1 first)
    self._send(inv1)
    with self.assertRaises(ValidationError):
        InvoiceService.restore_agreement_line(
            inv2, estimate_line_id=self.backed_line.pk)

def test_cancelled_invoice_releases_references(self):
    inv1 = self._seeded(); self._send(inv1)
    InvoiceService.cancel(inv1)
    self.assertEqual(len(InvoiceService.remaining_agreement_lines(self.job)), 3)
```

- [ ] **Step 2: Run — all fail (methods missing)**
- [ ] **Step 3: Implement.** `remaining_agreement_lines` filters
  `compose_agreement` lines against
  `InvoiceLineItem.objects.filter(invoice__status__in=LIVE_STATUSES,
  agreement_estimate_line_id__in=…)` (LIVE = everything except
  `STATUS_CANCELLED`). `seed_from_agreement` loops remaining lines in
  order, `transaction.atomic()`, creating lines + refs + mirrored claims
  (reuse `InvoiceWizardService._assert_atom_billable`'s billability by
  catching its ValidationError per atom — an unbillable atom is skipped,
  not fatal). Adjustment lines copy `adjustment_service`,
  `adjustment_percent`, and target categories, then recompute via the
  existing `recompute_adjustments` path. `InvoiceService.cancel` already
  releases claims — extend it to also NULL the two ref FKs on its lines
  (grep its current body; same loop).
- [ ] **Step 4: Run module — green**
- [ ] **Step 5: Commit** `feat(invoicing): agreement seeding, remaining/restore/remove, one-live-invoice invariant`

---

### Task 4: Auto-seed on creation; deposit path opts out; restore endpoint

**Files:**
- Modify: `apps/invoicing/services.py` (`InvoiceWizardService.open_for_job` gains `seed=True` param)
- Modify: `apps/api/invoicing/views.py` (`perform_create`, new `restore-line` action)
- Modify: `frontend/src/components/invoices/DepositInvoiceModal.svelte` (pass `seed: false`)
- Test: `tests/test_api_invoicing.py` (add class), `frontend/tests/components/DepositInvoiceModal.test.js` (adjust)

**Interfaces:**
- Consumes: Task 3's `seed_from_agreement`, `restore_agreement_line`,
  `remaining_agreement_lines`.
- Produces: `POST /api/invoices/ {job}` → draft seeded automatically;
  `POST /api/invoices/ {job, seed: false}` → unseeded (the deposit
  modal's path, until the button-relabel phase);
  `GET /api/invoices/{id}/remaining-agreement-lines/` → list for the
  restore picker; `POST /api/invoices/{id}/restore-line/`
  `{estimate_line_id | co_line_id}` → 201 with the serialized line.

- [ ] **Step 1: Failing API tests**

```python
def test_create_invoice_auto_seeds_from_agreement(self):
    resp = self.client.post('/api/invoices/', {'job': self.job.pk}, format='json')
    self.assertEqual(resp.status_code, 201)
    inv = Invoice.objects.get(pk=resp.data['invoice_id'])
    self.assertEqual(inv.invoicelineitem_set.count(), 3)

def test_create_with_seed_false_stays_empty(self):
    resp = self.client.post('/api/invoices/', {'job': self.job.pk, 'seed': False}, format='json')
    inv = Invoice.objects.get(pk=resp.data['invoice_id'])
    self.assertEqual(inv.invoicelineitem_set.count(), 0)

def test_estimate_less_job_seeds_empty(self):
    resp = self.client.post('/api/invoices/', {'job': self.bare_job.pk}, format='json')
    inv = Invoice.objects.get(pk=resp.data['invoice_id'])
    self.assertEqual(inv.invoicelineitem_set.count(), 0)

def test_restore_line_endpoint(self):
    inv = self._seeded_via_api()
    li = inv.invoicelineitem_set.first()
    self.client.delete(f'/api/invoices/{inv.pk}/line-items/{li.pk}/?confirm=true')
    resp = self.client.post(f'/api/invoices/{inv.pk}/restore-line/',
                            {'estimate_line_id': li.agreement_estimate_line_id},
                            format='json')
    self.assertEqual(resp.status_code, 201)
```

- [ ] **Step 2: Run — fail**
- [ ] **Step 3: Implement.** `open_for_job(job, seed=True)`: after
  creating a NEW draft (not when returning an existing one), call
  `InvoiceService.seed_from_agreement`. `perform_create` reads
  `self.request.data.get('seed', True)`. New viewset actions delegate to
  Task 3's service methods; permissions `CanManageFinancials` matching
  the existing line-item actions; DELETE of a line-item routes through
  `InvoiceService.remove_line` (check the existing line-item destroy
  path — it must release refs now). DepositInvoiceModal: add
  `seed: false` to its create POST body.
- [ ] **Step 4: Run backend module; run
  `npx vitest run tests/components/DepositInvoiceModal.test.js` from
  `frontend/` — green**
- [ ] **Step 5: Commit** `feat(api): invoices auto-seed from the agreement; deposit modal opts out; restore endpoint`

---

### Task 5: Invoice line serializer — agreement_ref + derived backing

**Files:**
- Modify: `apps/api/invoicing/serializers.py` (InvoiceLineItemSerializer)
- Test: `tests/test_api_invoicing.py` (add class)

**Interfaces:**
- Consumes: Task 2 fields; existing `is_deposit_line` /
  `is_deposit_deduction` model properties; the wizard in-sync rule
  (`BaseWizardService._is_in_sync` semantics).
- Produces read-only serializer fields:
  - `agreement_ref`: `null` or `{kind: 'estimate'|'change_order',
    line_id, est_qty, est_price, est_amount}` (from the referenced line's
    stored values).
  - `backing`: one of `'deposit' | 'deposit_credit' | 'actuals' |
    'estimate' | 'edited' | null` derived, never stored:
    1. `is_deposit_line` → `deposit`; `is_deposit_deduction` → `deposit_credit`
    2. has source rows AND in-sync (price == round(Σ sources ÷ qty, 2)) → `actuals`
    3. has `agreement_ref` AND qty/price equal the ref's est values → `estimate`
    4. has `agreement_ref` or sources (but neither rule above) → `edited`
    5. else → `null` (plain hand line)
  - `actuals_total`: Σ `compute_amount()` over claimed atoms (null when
    no sources) — the reference figure for est-vs-actual display.

- [ ] **Step 1: Failing tests** — one per derivation branch:

```python
def test_backing_estimate_on_untouched_seeded_line(self): ...
    # seeded hand line: agreement_ref set, no sources, values match -> 'estimate'
def test_backing_actuals_on_in_sync_claimed_line(self): ...
def test_backing_edited_after_price_override(self): ...
def test_backing_deposit_and_credit(self): ...
def test_backing_null_on_plain_hand_line(self): ...
def test_actuals_total_sums_claimed_atoms_only(self): ...
```

(Each test builds the state via Task 3/4 services + direct edits, GETs
`/api/invoices/{id}/line-items/`, asserts the field.)

- [ ] **Step 2: Run — fail**
- [ ] **Step 3: Implement** as `SerializerMethodField`s; extract the
  derivation into a module-level `derive_backing(line)` function (the CO
  surface will reuse it). Guard the N+1: the list context prefetches
  `sources` and `select_related('agreement_estimate_line',
  'agreement_co_line', 'accounting_category')` — add to the viewset's
  line-items queryset.
- [ ] **Step 4: Run module — green (watch the existing query-count tests;
  update their pins if the prefetch changes counts, with a comment)**
- [ ] **Step 5: Commit** `feat(api): invoice lines expose agreement_ref + derived backing`

---

### Task 6: Estimate line serializer — derived backing

**Files:**
- Modify: `apps/api/estimates/serializers.py` (EstimateLineItemSerializer)
- Test: `tests/test_api_estimates.py` (add class)

**Interfaces:**
- Produces read-only `backing`: `'planned_work' | 'planned_materials' |
  'from_catalog' | 'hand' | 'edited' | 'adjustment'` per spec §9.2:
  1. `adjustment_service_id` → `adjustment`
  2. `service_item_id` OR `inventory_item_id` → `from_catalog`
  3. has source rows: any task among them → `planned_work`;
     materials only → `planned_materials`; overridden price
     (not in-sync) → `edited`
  4. else → `hand`
  Plus `backing_total`: Σ source `compute_estimate_amount`/
  `compute_amount` (the "work totals $X" reference; null when no
  sources). The chip labels ("planned work", "from catalog"…) are
  frontend copy — the API ships the enum.

- [ ] **Step 1: Failing tests** — one per branch (wizard-composed
  task line, materials-only line, mixed line, service line, inventory
  line, bare material line — `is_material=True` bare lines are
  `from_catalog`? NO: bare material = `hand` until crystallization
  narrowing decides otherwise; only `inventory_item` catalog lines are
  `from_catalog`. Assert exactly that.)
- [ ] **Step 2: Run — fail**
- [ ] **Step 3: Implement** — same `derive` style as Task 5, shared
  in-sync check; prefetch sources on the line-items queryset.
- [ ] **Step 4: Run module — green**
- [ ] **Step 5: Commit** `feat(api): estimate lines expose derived backing`

---

### Task 7: validate_data — one live invoice per agreement line

**Files:**
- Modify: `apps/core/management/commands/validate_data.py` (invoices section)
- Test: `tests/test_validate_data.py` (add tests)

**Interfaces:** consumes Task 2 fields.

- [ ] **Step 1: Failing tests**

```python
def test_agreement_line_on_two_live_invoices_is_an_error(self):
    # build two open invoices whose lines reference the same estimate line
    output = self._run()
    self.assertIn('[ERROR]', output)
    self.assertIn('referenced by more than one live invoice', output)

def test_reference_on_cancelled_invoice_not_flagged(self): ...
```

- [ ] **Step 2: Run — fail**
- [ ] **Step 3: Implement** — aggregate
  `InvoiceLineItem.objects.exclude(invoice__status=Invoice.STATUS_CANCELLED)`
  grouped by each ref FK, `Count > 1` → error naming the invoices.
- [ ] **Step 4: Run module — green**
- [ ] **Step 5: Commit** `feat(validate_data): one-live-invoice-per-agreement-line check`

---

### Task 8: Shared kit A — app.css classes, DocModeBar, BackingChip

**Files:**
- Modify: `frontend/src/css/app.css` (one new block)
- Create: `frontend/src/components/docsurface/DocModeBar.svelte`
- Create: `frontend/src/components/docsurface/BackingChip.svelte`
- Test: `frontend/tests/components/docsurface/DocModeBar.test.js`, `BackingChip.test.js`

**Interfaces:**
- Produces: `DocModeBar` props `{ mode, onMode, modes = ['edit','customer','reorder'], labels = {edit:'Edit', customer:'Customer', reorder:'Reorder'} }` —
  renders one button per mode, active gets `aria-pressed="true"`.
  `BackingChip` props `{ backing, syncedWithEstimate = false }` — maps the
  Task 5/6 enums to labels: estimate→"estimate", actuals→"actuals" (or
  "actuals = estimate ✓" when `syncedWithEstimate`), edited→"edited",
  deposit→"deposit", deposit_credit→"deposit credit",
  planned_work→"planned work", planned_materials→"planned materials",
  from_catalog→"from catalog", hand→"hand line", adjustment→"adjustment";
  null renders nothing.
- app.css additions (once, shared by all three surfaces):

```css
/* Document-surface kit (estimate / invoice / CO editing views, 2026-08) */
.backing-chip { display:inline-block; font-size:11px; font-weight:600;
  padding:1px 8px; border-radius:999px; white-space:nowrap;
  background:#eceae5; color:#6b6e71; }
.backing-chip.actuals, .backing-chip.planned, .backing-chip.catalog,
.backing-chip.deposit { background:#e3eeee; color:#2e6e73; }
.backing-chip.synced { background:#e4f0e6; color:#3e7c4f; }
.backing-chip.edited { background:#f7ebdc; color:#a8651f; }
.doc-atom-row td { font-size:12.5px; color:#6b6e71; padding:4px 10px;
  background:#f7f7f5; border-bottom:1px dotted #e8e6e1; }
.doc-atom-row td:first-child { padding-left: 34px; }
.doc-offdoc td { color:#6b6e71; border-bottom:1px dashed #d8d6d0;
  background:repeating-linear-gradient(-45deg, transparent 0 8px, #f0efec 8px 16px); }
.doc-newline td { border-top:2px dashed #d8d6d0; border-bottom:2px dashed #d8d6d0; }
.doc-newline .cta { color:#2e6e73; font-weight:600; }
.doc-mode-bar button[aria-pressed="true"] { background:#115e59; color:#fff;
  border-color:#115e59; }
```

- [ ] **Step 1: Write failing Vitest** — DocModeBar renders three
  buttons, clicking fires `onMode('customer')`, active button carries
  aria-pressed; BackingChip label table (one `it` per enum, including
  the ✓ variant and the null-renders-nothing case).
- [ ] **Step 2: Run — fail (component missing)**
- [ ] **Step 3: Implement both components** (BackingChip is a lookup
  table + `<span class="backing-chip {cls}">{label}</span>`; DocModeBar a
  flex row of `<button type="button">`).
- [ ] **Step 4: `npx vitest run tests/components/docsurface/` — green**
- [ ] **Step 5: Commit** `feat(spa): docsurface kit A — mode bar, backing chips, shared css`

---

### Task 9: Shared kit B — AtomChildRow, UncoveredWorkSection, NewLineFromSelectedRow

**Files:**
- Create: `frontend/src/components/docsurface/AtomChildRow.svelte`
- Create: `frontend/src/components/docsurface/UncoveredWorkSection.svelte`
- Create: `frontend/src/components/docsurface/NewLineFromSelectedRow.svelte`
- Test: `frontend/tests/components/docsurface/UncoveredWorkSection.test.js` (+ small tests for the other two)

**Interfaces:**
- `AtomChildRow` props `{ atom, colspanBefore = 0, onRemove = null, note = '' }` —
  one `<tr class="doc-atom-row">`: kind tag (task/mat), description
  (+ optional `note` small-text, e.g. "inherited from line 1"),
  qty/rate/amount right-aligned via existing `.text-right` conventions,
  trailing `remove` button only when `onRemove` wired (A3 rule: no dead
  buttons).
- `UncoveredWorkSection` props `{ title, subtitle, rows, selected = $bindable([]),
  directLabel = 'Bill as its own line', onDirect = null, emptyText }` —
  each row `{ id, kind, description, qty, rate, amount, selectable,
  unselectableNote }`; checkbox per selectable row bound into `selected`;
  per-row direct button when `onDirect` wired and row unselected;
  dim rows with `unselectableNote` ("billable when complete").
- `NewLineFromSelectedRow` props `{ visible, nextNumber, onCreate }` —
  the dashed placeholder `<tr class="doc-newline">`; renders only when
  `visible` (selection non-empty).
- All three are consumed by Tasks 10–12 and by the CO plan.

- [ ] **Step 1: Failing Vitest** — UncoveredWorkSection: renders rows,
  binds selection, hides direct button while its row is selected, shows
  `emptyText` when rows empty, never renders a button without its
  callback. NewLineFromSelectedRow: hidden when `visible=false`.
- [ ] **Step 2: Run — fail**
- [ ] **Step 3: Implement** (markup mirrors the artifact; classes from
  app.css only — zero component-local CSS beyond layout glue).
- [ ] **Step 4: Vitest green**
- [ ] **Step 5: Commit** `feat(spa): docsurface kit B — atom rows, uncovered-work section, placeholder row`

---

### Task 10: Shared kit C — DocCustomerView and DocReorderView

**Files:**
- Create: `frontend/src/components/docsurface/DocCustomerView.svelte`
- Create: `frontend/src/components/docsurface/DocReorderView.svelte`
- Test: `frontend/tests/components/docsurface/DocViews.test.js`

**Interfaces:**
- Both take `{ title, lines, grandTotal }` where each line is
  `{ line_number, description, qty_display, price, amount }` — the
  collapsed rendering: `#` column, description, qty, price, amount,
  `.grand` total row, `.data-table` styling. Excluded (struck/removed)
  lines are NOT in `lines` — callers filter.
- `DocReorderView` adds `{ onReorder(lineId, 'up'|'down') }` and an
  arrows column — **identical rows to customer view plus arrows** (the
  settled rule); first/last arrows disabled.
- Consumed by Tasks 11, 12, and the CO plan.

- [ ] **Step 1: Failing Vitest** — customer view renders lines +
  total and no buttons at all; reorder view fires `onReorder(id, 'down')`
  on click, disables the boundary arrows, and renders the same
  cell text as customer view for identical input (assert per-row text
  equality between the two renders).
- [ ] **Step 2: Run — fail**
- [ ] **Step 3: Implement** — DocReorderView composes the same row
  markup (either by iterating the same derived rows or by rendering
  DocCustomerView's row snippet — implement as one shared `{#snippet}`
  inside DocReorderView importing nothing heavy; do NOT duplicate the
  formatting logic: both use `fmtMoney` from `lib/taskTotals.js`).
- [ ] **Step 4: Vitest green**
- [ ] **Step 5: Commit** `feat(spa): docsurface kit C — customer + reorder views`

---

### Task 11: Estimate — merged edit view + three-mode panel

**Files:**
- Create: `frontend/src/components/estimates/EstimateEditView.svelte`
- Modify: `frontend/src/components/estimates/EstimatePanel.svelte`
- Modify: `frontend/src/stores/jobWorkspace.js` (mode value migration)
- Test: `frontend/tests/components/estimates/EstimateEditView.test.js`, update `EstimatePanel.test.js`

**Interfaces:**
- Consumes: kit A/B/C; existing endpoints only —
  `GET /api/estimates/{id}/line-items/` (now with `backing`,
  `backing_total` from Task 6), `GET /api/estimates/{id}/source-pool/`,
  `POST .../line-items-from-atoms/`, `POST .../line-items/{lid}/add-atoms/`,
  `POST .../line-items/{lid}/remove-atoms/`, the `line-items` CRUD +
  reorder, `line-items-from-service/`, `adjustment-lines/`.
- Produces: `EstimateEditView` props `{ estimate, canEdit, onChanged }`.
  Layout per the artifact: Add line / Add adjustment buttons (reusing
  the existing `PriceListPicker` → `EstimateAddLineForm` flow and
  `AdjustmentModal` unchanged); `.data-table` of lines — # column,
  description (+provenance small), qty, price, amount, BackingChip
  (+ "work totals $X" reference when `edited`), per-line actions
  **Edit** (existing `LineItemModal` in field-edit mode) / **Remove** /
  **→ Deliverable** (calls the §6 endpoint when it lands — render only
  when the callback prop is wired, so this task ships it dark);
  AtomChildRow nest per line from the line's `sources` detail;
  `NewLineFromSelectedRow` + per-line "Add selected here" while
  `selected` non-empty; `UncoveredWorkSection` fed from `source-pool`
  atoms with `claimed_by_current` filtered out.
- `EstimatePanel` mode state becomes `'edit' | 'customer' | 'reorder'`
  via `DocModeBar`; `jobWorkspace.rememberMode` values `'lines'` and
  `'reconcile'` read back as `'edit'` (one-line normalization in
  `getJobWs` consumers — grep for `rememberMode` readers). Customer
  mode renders `DocCustomerView` from the non-adjustment... no: ALL
  lines including adjustments, numbered as stored; reorder mode
  `DocReorderView` wired to the existing reorder endpoint.

- [ ] **Step 1: Failing Vitest** — EstimateEditView: renders a backed
  line with its atom nest and chip; ticking a pool row makes every line
  grow "Add selected here" and the placeholder row appear; clicking a
  line's "Add selected here" POSTs `add-atoms` with the ticked ids;
  "New line from selected" POSTs `line-items-from-atoms` then opens the
  edit modal (assert modal open state); Remove calls the DELETE
  endpoint (with `?confirm=true` if the two-phase pattern requires it —
  match the existing estimate line-item delete call in the old panel);
  no "delete" text anywhere (assert `queryByText(/delete/i)` null).
  EstimatePanel: mode bar switches views in place; remembered
  `'reconcile'` normalizes to `'edit'`.
- [ ] **Step 2: Run — fail**
- [ ] **Step 3: Implement.** EstimatePanel keeps ownership of data
  loading (its existing fetch flow) and passes down; EstimateEditView is
  presentation + gestures. Delete nothing yet — the old lines-view
  markup and "Show Tasks & Materials" toggle are *replaced* in
  EstimatePanel by the new mode bar + views (ReconcileMode import
  removed from the estimate side).
- [ ] **Step 4: Vitest: the two new/updated files green, then full
  `npm run test:run` (other estimate tests will need the same
  adjustments — fix them here, they are part of this task)**
- [ ] **Step 5: Commit** `feat(spa): estimate three-mode surface — merged edit view`

---

### Task 12: Invoice — seeded edit view + three-mode panel

**Files:**
- Create: `frontend/src/components/invoices/InvoiceEditView.svelte`
- Modify: `frontend/src/components/invoices/InvoicePanel.svelte`
- Test: `frontend/tests/components/invoices/InvoiceEditView.test.js`, update `InvoicePanel.test.js`

**Interfaces:**
- Consumes: kit A/B/C; Task 4/5 endpoints (`remaining-agreement-lines`,
  `restore-line`, line-items with `agreement_ref`/`backing`/
  `actuals_total`); existing invoice wizard endpoints for atom
  attach/remove (`line-items-from-atoms`, `add-atoms`, `remove-atoms`,
  `source-pool`) and `InvoiceAddLineForm`/`LineItemModal`/
  `AgreementAdjustmentsPanel` as today.
- Produces `InvoiceEditView` props `{ invoice, canEdit, onChanged }`:
  - Seeded lines render with # column, BackingChip, est-reference
    (`est was $X · +$Δ` from `agreement_ref` + `actuals_total`), and
    backing controls: **Use estimate** (PATCH the line back to
    `agreement_ref` est values), **Use actuals** (PATCH price to
    round(actuals_total ÷ qty, 2) — shown when backing is
    `estimate`/`edited` and sources exist), **Edit…** (modal).
  - **Remove from invoice** keeps a struck `.doc-offdoc` row in place
    (client-side list of removed refs for this draft session) with
    **Restore** → `restore-line`.
  - `UncoveredWorkSection` from `source-pool` (billable atoms not
    claimed by this invoice; INVOICED-elsewhere rows dim with their
    invoice ref; "descoped by CO-N" chips arrive with the CO plan — the
    section takes an optional per-row `chip` prop NOW so it needs no
    rework then).
  - "Add selected here" / placeholder row exactly as the estimate.
  - Deposit credits: the existing deposit-credit pull flow
    (`WizardSourcePool`'s deposit group logic) is re-homed as a
    `DepositCreditsSection` INSIDE this file (it is invoice-only; keep
    it a local section, not kit).
- InvoicePanel gains the mode bar; customer/reorder modes reuse
  `DocCustomerView`/`DocReorderView` (removed lines excluded from
  both).

- [ ] **Step 1: Failing Vitest** — seeded line shows `estimate` chip
  and no controls when nothing attached; attaching (mock POST) then
  refetch shows `actuals` chip and the est-reference; **Use estimate**
  PATCHes the est values; removing a line renders the struck row with
  Restore wired to `restore-line`; totals row excludes struck rows;
  no "delete" text anywhere; mode bar flips to customer view where NO
  buttons render.
- [ ] **Step 2: Run — fail**
- [ ] **Step 3: Implement** (same ownership split as Task 11).
- [ ] **Step 4: Vitest green incl. full run**
- [ ] **Step 5: Commit** `feat(spa): invoice three-mode surface — seeded edit view with backing controls`

---

### Task 13: Retire the old wizard presentation

**Files:**
- Delete: `frontend/src/components/wizards/ReconcileMode.svelte`, `WizardActions.svelte`, `WizardLineItemCard.svelte`, `WizardAtomRow.svelte`
- Delete: `frontend/src/components/invoices/WizardSourcePool.svelte`, `frontend/src/components/estimates/WizardSourcePool.svelte`
- Modify: `frontend/src/routes/estimates/EstimateWizardRedirect.svelte` (remember `'edit'` instead of `'reconcile'`)
- Modify/Delete: their Vitest files
- Test: `cd frontend && npm run build` + full Vitest

**Interfaces:** none — pure removal. Grep first:
`grep -rn "ReconcileMode\|WizardSourcePool\|WizardLineItemCard\|WizardAtomRow\|WizardActions" frontend/src/` must return only the files being deleted (the CO panel must NOT be an importer; if it is, STOP — the CO panel keeps its current non-wizard UI until the CO plan, so an import here means Task 11/12 missed a consumer).

- [ ] **Step 1: Grep for importers — expect none outside the delete list**
- [ ] **Step 2: Delete components + their tests; fix the redirect shim**
- [ ] **Step 3: `npm run build` — must succeed (Svelte catches dangling imports)**
- [ ] **Step 4: Full `npm run test:run` — green**
- [ ] **Step 5: Commit** `refactor(spa): retire the two-column wizard presentation`

---

### Task 14: E2E — seeding, backing, remove/restore, three modes

**Files:**
- Create: `e2e/specs/invoice-skeleton/seeded-invoice.spec.js`
- Create: `e2e/specs/invoice-skeleton/estimate-three-modes.spec.js`
- Modify: existing wizard-flow specs that drive the old UI (grep
  `e2e/specs/` for `reconcile`, `wizard`, `Show Tasks`, `source-pool`
  driving selectors; update to the new surface)
- Test: `cd e2e && npx playwright test`

**Interfaces:** consumes the full stack.

- [ ] **Step 1: Write the specs** —
  `seeded-invoice.spec.js`: manager creates an invoice on a seeded job
  with an accepted backed estimate → asserts lines pre-filled with est
  values and the complete task's line showing `actuals`; removes a line
  → struck row + Restore brings it back; customer mode shows no
  controls; sends.
  `estimate-three-modes.spec.js`: estimator on a draft estimate ticks
  two work rows → "New line from selected" → names the line in the edit
  modal → chip reads "planned work"; reorder mode moves it; customer
  mode renders the collapsed doc.
- [ ] **Step 2: Run the two specs — fix selectors until green**
- [ ] **Step 3: Run the FULL e2e suite; update the old-UI specs it
  breaks (they are part of this task's deliverable)**
- [ ] **Step 4: Commit** `test(e2e): skeleton + three-mode surface coverage`

---

### Task 15: Docs + full verification

**Files:**
- Modify: `docs/designs/estimates-and-prices.md` (§8 wizard → the new surface; §11/§12 rewritten around the three modes), `docs/designs/invoicing-and-expenses.md` (seeding, references, backing, remove/restore), `docs/designs/architecture-and-conventions.md` (docsurface kit entry), `docs/designs/data-constraints.md` (reference fields + invariant), `frontend/README.md` (docsurface conventions)
- Test: full verification battery

- [ ] **Step 1: Update the five docs** — behavior as built, pointing at
  the spec §9 and the artifact for rationale.
- [ ] **Step 2: Full fresh-DB backend suite (`--noinput`, NO --keepdb —
  this plan added migration invoicing/0023), read the OK line from the
  log file**
- [ ] **Step 3: Full Vitest + full e2e (may run concurrently with the
  backend suite per RM — separate DBs)**
- [ ] **Step 4: Commit** `docs: skeleton phase — durable docs current`

---

## Self-Review

- **Spec coverage:** §7.1 refs+invariant (T2/T3/T7), §7.2 seeding +
  seed-false + restore (T3/T4), §7.3 backing model + pool reframing
  (T5/T6/T11/T12), §9.1 modes/gestures/Remove/placeholder (T8–T12),
  §9.2 chips (T5/T6/T8), §9.4 checkpoints (T11/T12/T14 asserts), retire
  old wizard (T13), docs (T15). Deposit relabel + § "→ Deliverable"
  endpoint are LATER phases — the surface ships those affordances dark
  (render-when-wired), which is why UncoveredWorkSection takes a `chip`
  prop and the deliverable button renders only when its callback prop
  is provided.
- **Placeholder scan:** the two "ships dark" affordances are deliberate
  scope edges, not TBDs; all steps carry code or exact instructions.
- **Type consistency:** `backing` enum strings match between Task 5/6
  (API) and Task 8 (BackingChip lookup); `agreement_ref.kind` matches
  Task 4's restore-line body keys; `remaining_agreement_lines` name used
  consistently in T3/T4/T12.

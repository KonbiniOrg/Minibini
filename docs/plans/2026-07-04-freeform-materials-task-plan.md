# Freeform Materials on the Inventory Rails — Implementation Plan

> **Status: IMPLEMENTED on `feature/inventory_again` (2026-07-05).** All 17 tasks
> complete; backend (3927) + frontend (797) suites green, build clean. Durable
> behavior reconciled into `docs/designs/` (materials-inventory-and-purchasing,
> estimates-and-prices, data-constraints, jobs-tasks-and-worksheets). This file
> is retained as the execution record.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every acted-on Material is lot-backed (provisional → established via pricing), with four fulfillment paths (Order / Attach-Expense / Mark-on-hand / Customer-supplied), arrival-gated consumption, `is_catalog` dropped, and the settled UI state vocabulary.

**Spec:** `docs/plans/2026-06-30-freeform-material-procurement-inventory.md` (all majors [SETTLED] 2026-07-04). Read it before starting any task.

**Architecture:** Establishment = pricing mints/attaches an `InventoryItem` lot behind the Material; the existing QOH/earmark/receipt rails then do all the work. `Material.cost_source` is the single provenance enum. Display status is derived client-side in one pure function.

**Tech Stack:** Django 5.2 + DRF, MySQL, Svelte 5 SPA (Vitest for frontend tests).

## Global Constraints

- **Branch: `feature/inventory_again`.** Commit every task here. Never merge/push/PR (user's global rule).
- **NEVER write to the dev DB** — no `migrate`, no `manage.py shell` ORM writes, no loaddata, no SQL writes. `makemigrations` is fine; tests use their own DB.
- **Only one agent at a time may run `python manage.py test`** (shared MySQL).
- **Never judge tests by a piped exit code** — read the `OK` / `FAILED` summary line and `Ran N tests` count.
- After the migration tasks land, the final suite run must be **fresh, WITHOUT `--keepdb`**.
- Error contract: services raise `ValidationError({'field': ['msg']})` for field problems, `ValidationError('sentence')` otherwise; never catch just to re-render; frontend routes errors through `triageError(e)`.
- All DELETE responses return 200 + JSON body (no 204). No `QuerySet.update()`/`bulk_*` where `save()` has side effects. Status constants, never string literals. Multi-model ops in `transaction.atomic()`.
- UI: links navigate, buttons act; saves explicit (never blur-only); confirm only the irreversible; `<tr>` always inside `<tbody>`/`<thead>`.
- Frontend tests: Vitest in `frontend/tests/`, run `npm run test:run` from `frontend/`.
- Converter (`nealsdata/`) changes must run `python manage.py test tests.test_neals_builders`.
- TDD every task: write failing test → verify failure reason → minimal code → green → commit.

## File Structure (locked decisions)

- `apps/inventory/models.py` — `Material.cost_source` field + constants; `InventoryItem.is_catalog` and `is_finished_lot` removed.
- `apps/inventory/services.py` — `MaterialService.establish` / `mint_lot` / `_earmark_if_committed` / `order` / `mark_on_hand`; `consume` provisional refusal; merge guard change; `receive_ad_hoc_purchase(material, qty=None)`.
- `apps/estimates/acceptance.py` — is_material branch establishes with reverse-markup cost.
- `apps/expenses/services.py` — classification without `is_catalog`; attach-to-existing-material mode.
- `apps/purchasing/models.py` — `PurchaseOrder.business` nullable for drafts; issue-gate.
- `apps/api/inventory/views.py` + `serializers.py` — new actions `order`, `mark-on-hand`; `cost_source`/`customer_supplied` fields; hide-on-spend filter removed; picker ranking.
- `frontend/src/lib/materialStatus.js` (new) — the one status function. Tests: `frontend/tests/materialStatus.test.js`.
- `frontend/src/routes/jobs/JobTaskListPage.svelte`, `frontend/src/components/TaskTree.svelte`, `frontend/src/components/MaterialModal.svelte`, `frontend/src/routes/inventory/InventoryListPage.svelte`, `frontend/src/components/settings/AccountingCategories.svelte`.
- `nealsdata/converter/build.py` — drop `is_catalog`, set `cost_source`.

**Lot code convention [DEFAULT]:** minted lots get `code = f'LOT-{material.pk}'` (unique because material PKs are). **Picker ranking [DEFAULT]:** in-stock first, then newest (`-inventory_item_id` as recency proxy).

---

### Task 1: `Material.cost_source` provenance enum

**Files:**
- Modify: `apps/inventory/models.py` (Material class, ~line 251)
- Modify: `apps/api/inventory/serializers.py` (MaterialSerializer)
- Create: migration via `makemigrations inventory`
- Test: `tests/test_material_cost_source.py` (new)

**Interfaces — Produces:** `Material.COST_SOURCE_ESTIMATED/ENTERED/PO/EXPENSE/CUSTOMER` constants; nullable `cost_source` CharField; `cost_source` read-only in `MaterialSerializer`. Later tasks rely on exactly these names.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_material_cost_source.py
"""Material.cost_source — the single provenance enum (spec §cost_source)."""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.inventory.models import Material
from apps.jobs.models import Job


class CostSourceFieldTests(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MAT')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='5')
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-2026-0001')

    def test_defaults_null_and_accepts_choices(self):
        m = Material(job=self.job, description='x', quantity=Decimal('1'),
                     accounting_category=self.cat)
        m.save()
        self.assertIsNone(m.cost_source)
        for value in (Material.COST_SOURCE_ESTIMATED, Material.COST_SOURCE_ENTERED,
                      Material.COST_SOURCE_PO, Material.COST_SOURCE_EXPENSE,
                      Material.COST_SOURCE_CUSTOMER):
            m.cost_source = value
            m.save()
            m.refresh_from_db()
            self.assertEqual(m.cost_source, value)

    def test_is_customer_supplied_property(self):
        m = Material(job=self.job, description='x', quantity=Decimal('1'),
                     accounting_category=self.cat)
        m.save()
        self.assertFalse(m.is_customer_supplied)
        m.cost_source = Material.COST_SOURCE_CUSTOMER
        self.assertTrue(m.is_customer_supplied)
```

- [ ] **Step 2: Run it — must fail with `AttributeError: ... COST_SOURCE_ESTIMATED`**

Run: `python manage.py test tests.test_material_cost_source`

- [ ] **Step 3: Implement**

In `apps/inventory/models.py`, inside `class Material`, after the `CONSUMPTION_STATE_CHOICES` block:

```python
    # Provenance: where this material's cost/backing came from. NULL =
    # provisional (no lot, no meaningful pricing yet). One field answers both
    # "is this cost real?" and "who owns this thing?" (spec §cost_source).
    COST_SOURCE_ESTIMATED = 'estimated'          # reverse-markup placeholder — cost unconfirmed
    COST_SOURCE_ENTERED = 'entered'              # user-entered / catalog-attached pricing
    COST_SOURCE_PO = 'po'                        # real document cost from a PO line
    COST_SOURCE_EXPENSE = 'expense'              # real document cost from an attached expense
    COST_SOURCE_CUSTOMER = 'customer_supplied'   # $0, deliberate and locked
    COST_SOURCE_CHOICES = [
        (COST_SOURCE_ESTIMATED, 'Estimated'),
        (COST_SOURCE_ENTERED, 'Entered'),
        (COST_SOURCE_PO, 'PO'),
        (COST_SOURCE_EXPENSE, 'Expense'),
        (COST_SOURCE_CUSTOMER, 'Customer supplied'),
    ]
```

After the `released_qty` field:

```python
    cost_source = models.CharField(
        max_length=20, choices=COST_SOURCE_CHOICES, null=True, blank=True,
        help_text='Cost provenance; NULL means provisional (unpriced).',
    )
```

After `is_expense_bound`:

```python
    @property
    def is_customer_supplied(self):
        return self.cost_source == self.COST_SOURCE_CUSTOMER
```

In `apps/api/inventory/serializers.py` `MaterialSerializer.Meta`: add `'cost_source'` to `fields` and to `read_only_fields`.

Run: `python manage.py makemigrations inventory` (do NOT migrate the dev DB).

- [ ] **Step 4: Green** — `python manage.py test tests.test_material_cost_source tests.test_api_materials` → `OK`

- [ ] **Step 5: Commit** — `feat(inventory): Material.cost_source provenance enum`

---

### Task 2: Retire `is_catalog`'s behavioral forks (expense classification, merge guard, earmark-move guard)

**Files:**
- Modify: `apps/expenses/services.py:39` and `:184`
- Modify: `apps/expenses/models.py:109-112` (clean)
- Modify: `apps/inventory/services.py` merge (`if discard.is_catalog:` block, ~line 160)
- Test: extend `tests/test_expense_material_inventory.py`, `tests/test_inventory_merge.py`

**Interfaces — Produces:** classification rule "any inventory-item-backed purchase is a stock receipt"; merge accepts any discard item.

- [ ] **Step 1: Failing tests.** In `tests/test_expense_material_inventory.py` add (match the file's existing setUp fixtures/objects — reuse its PLI factory; create the item WITHOUT relying on catalog semantics):

```python
    def test_any_item_backed_purchase_is_stock_receipt(self):
        """Spec §Drop is_catalog: pli present → stock receipt, uniformly."""
        pli = InventoryItem.objects.create(
            code='LOT-X', accounting_category=self.cat, units='ea',
            qty_on_hand=Decimal('0'))
        expense = ExpenseService.create(
            entered_by=self.user, amount=Decimal('40.00'),
            description='sheet', new_material={
                'job_id': self.job.pk, 'inventory_item_id': pli.pk,
                'quantity': Decimal('2'),
            })
        pli.refresh_from_db()
        self.assertEqual(pli.qty_on_hand, Decimal('2'))
        self.assertEqual(expense.stock_pli, pli)
        self.assertIsNone(expense.material)
```

In `tests/test_inventory_merge.py`: find the test asserting "cannot discard a catalog item" and REPLACE it with:

```python
    def test_merge_discards_any_item(self):
        """The catalog discard-guard is retired; explicit confirm lives in the UI."""
        keep = InventoryItem.objects.create(
            code='K', accounting_category=self.cat, units='ea')
        discard = InventoryItem.objects.create(
            code='D', accounting_category=self.cat, units='ea',
            qty_on_hand=Decimal('3'))
        InventoryService.merge(keep.pk, discard.pk)
        keep.refresh_from_db()
        self.assertEqual(keep.qty_on_hand, Decimal('3'))
        self.assertFalse(InventoryItem.objects.filter(pk=discard.pk).exists())
```

(Adapt constructor kwargs to that file's existing helpers; drop any `is_catalog=` kwargs from the tests you touch.)

- [ ] **Step 2: Run both files — new tests fail** (`stock_pli` is None / ValidationError raised).

- [ ] **Step 3: Implement.**
  - `apps/expenses/services.py:39`: `if pli and pli.is_catalog:` → `if pli:`
  - `apps/expenses/services.py:184` (job-change earmark move): `and pli and pli.is_catalog` → `and pli is not None`
  - `apps/expenses/models.py`: delete the `if self.stock_pli and not self.stock_pli.is_catalog:` error block in `clean()`.
  - `apps/inventory/services.py` merge: delete the `if discard.is_catalog: raise ValidationError(...)` block.

- [ ] **Step 4: Green** — `python manage.py test tests.test_expense_material_inventory tests.test_inventory_merge tests.test_expense_service tests.test_expense_model` → read summary, `OK`. Fix any test in those files that asserted the old fork (delete assertions of the catalog refusal; keep unit-mismatch merge tests).

- [ ] **Step 5: Commit** — `refactor(inventory,expenses): retire is_catalog behavioral forks`

---

### Task 3: Drop `is_catalog` everywhere + remove hide-on-spend

**Files:**
- Modify: `apps/inventory/models.py` (remove field + `is_finished_lot`), `apps/inventory/services.py` (`MERGE_OVERRIDE_FIELDS`, `update_item` comment), `apps/api/inventory/views.py` (hide-on-spend exclude + `include_finished` + `?is_catalog` params), `apps/api/inventory/serializers.py` + `apps/api/tasks/serializers.py` (`is_catalog`, `inventory_item_is_catalog` fields)
- Modify: every test/fixture referencing `is_catalog`; frontend files; `nealsdata/converter/build.py` (~774, ~1064) + `nealsdata/convert.md`
- Create: migration via `makemigrations inventory`
- Test: delete `tests/test_inventory_hide_on_spend.py`; sweep the rest

**Interfaces — Produces:** `InventoryItem` has no `is_catalog`; list endpoint returns every item (only `?is_active` and `?search` filter).

- [ ] **Step 1:** Backend removals (order matters so each grep comes up empty):
  1. Serializers: remove `'is_catalog'` from `InventoryItemSerializer.fields`; remove `inventory_item_is_catalog` method-fields from `MaterialSerializer` and `apps/api/tasks/serializers.py`.
  2. Views: in `apps/api/inventory/views.py` `get_queryset`, delete the `include_finished` block (the `annotate(_em_count=...).exclude(...)`) and the `is_catalog_param` block.
  3. Services: remove `'is_catalog'` from `MERGE_OVERRIDE_FIELDS`; fix the stale `update_item` comment.
  4. Models: remove the `is_catalog` field, its comment, and the `is_finished_lot` property.
  5. `python manage.py makemigrations inventory` → RemoveField migration.

- [ ] **Step 2:** Test + fixture sweep:

```bash
grep -rln "is_catalog" tests/ fixtures/
```

For each hit: remove `is_catalog=...` constructor kwargs, delete assertions about catalog/lot visibility, delete `tests/test_inventory_hide_on_spend.py` entirely (`git rm`). In `fixtures/*.json` remove any `"is_catalog"` keys. Re-grep until empty.

- [ ] **Step 3:** Frontend sweep:

```bash
cd frontend && grep -rln "is_catalog\|inventory_item_is_catalog\|include_finished" src/ tests/
```

Known hits and the change in each:
- `InventoryItemForm.svelte` — remove the catalog checkbox + `isCatalog` state + payload key.
- `InventoryListPage.svelte` — `lotOptions` becomes all items (`$derived(items)`); type column `catalog|lot` → show `{it.is_active ? 'active' : 'inactive'}`; drop the `finished` row-class condition; drop any `include_finished` query param.
- `TaskTree.svelte`, `MaterialModal.svelte`, `PriceListPicker.svelte`, `LineItemModal.svelte`, `LineItemForm.svelte`, `ServiceItemManager.svelte`, `MaterialPicker.svelte` — remove the 📦 `inv-badge` markup and any `is_catalog` conditionals (materials are all lot-backed once established; the badge is meaningless).
Update any affected Vitest fixtures. Run `npm run test:run` and `npm run build` — both green.

- [ ] **Step 4:** Converter: in `nealsdata/converter/build.py` remove the `'is_catalog': True` dict key (~774) and the `is_catalog=False` in `_mint_transient_lot` (~1064); update `nealsdata/convert.md` (§ lines 117-118, 426) to say every item is just an item, retirement is manual `is_active`.

- [ ] **Step 5:** Full verification (fresh DB — a migration changed):

Run: `python manage.py test 2>&1 | tee /tmp/t3.log` then read the tail summary — must be `OK`. Then `python manage.py test tests.test_neals_builders` → `OK`.

- [ ] **Step 6: Commit** — `feat(inventory)!: drop is_catalog — one item kind, manual is_active retirement`

---

### Task 4: Vendor-less draft POs (`PurchaseOrder.business` nullable + issue gate)

**Files:**
- Modify: `apps/purchasing/models.py:27` + `clean()`, `apps/purchasing/services.py` (`update_status`)
- Create: migration via `makemigrations purchasing`
- Test: `tests/test_po_vendorless_draft.py` (new)

**Interfaces — Produces:** `PurchaseOrderService.create_po()` works with no `business`; transition to `STATUS_ISSUED` raises without one. (Task 8's Order action depends on this.)

- [ ] **Step 1: Failing tests**

```python
# tests/test_po_vendorless_draft.py
"""Order-from-material needs a draft PO before the vendor is known (spec Path 1)."""
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.core.models import AppState, Configuration
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import PurchaseOrderService


class VendorlessDraftTests(TestCase):
    def setUp(self):
        Configuration.objects.create(
            key='po_number_sequence', value='PO-{year}-{counter:04d}')
        AppState.objects.create(key='po_counter', value='0')

    def test_draft_po_without_business(self):
        po = PurchaseOrderService.create_po()
        self.assertIsNone(po.business_id)
        self.assertEqual(po.status, PurchaseOrder.STATUS_DRAFT)

    def test_issue_requires_business(self):
        po = PurchaseOrderService.create_po()
        with self.assertRaises(ValidationError):
            PurchaseOrderService.update_status(po.pk, PurchaseOrder.STATUS_ISSUED)
```

(Check the real Configuration/AppState keys used by existing PO tests — copy their setUp lines verbatim if they differ.)

- [ ] **Step 2: Run — fails** (IntegrityError/ValidationError on create).

- [ ] **Step 3: Implement.** Model: `business = models.ForeignKey('contacts.Business', on_delete=models.PROTECT, null=True, blank=True)`. In `PurchaseOrderService.update_status`, before saving:

```python
        if new_status == PurchaseOrder.STATUS_ISSUED and po.business_id is None:
            raise ValidationError(
                {'business': ['A purchase order needs a vendor before it can be issued.']})
```

Guard the model `clean()` blocks that dereference `self.business` with `self.business_id and ...`. `makemigrations purchasing`. Check the PO PDF/send path (`apps/purchasing/pdf.py`) tolerates it — send requires issued, and issued now implies a business, so no change should be needed; verify by reading, don't guess. Frontend `PurchaseOrderDetail.svelte`: render `—` when `business` is null.

- [ ] **Step 4: Green** — `python manage.py test tests.test_po_vendorless_draft tests.test_purchasing_services tests.test_api_purchasing tests.test_purchasing_models` → `OK`.

- [ ] **Step 5: Commit** — `feat(purchasing): vendor-less draft POs; vendor required at issue`

---

### Task 5: Establishment core — `establish()`, `mint_lot()`, `create_on_job` mints, PATCH routes

**Files:**
- Modify: `apps/inventory/services.py` (MaterialService), `apps/api/inventory/serializers.py` (drop freeform-cost refusal)
- Test: `tests/test_material_establish.py` (new)

**Interfaces — Produces:**
- `MaterialService.establish(material, *, inventory_item=None, unit_cost=None, sell_price=None, cost_source=Material.COST_SOURCE_ENTERED) -> Material`
- `MaterialService.mint_lot(material, *, unit_cost, sell_price=None) -> InventoryItem`
- `MaterialService._earmark_if_committed(material)` (extracted; also used by Tasks 7, 10)
- `create_on_job(..., cost_source=...)` now takes the Task-1 enum values; passing a nonzero `unit_cost` with no `inventory_item` **mints** (born established). The old `'manual'`/`'document'` values and the freeform-cost refusal are retired.

- [ ] **Step 1: Failing tests**

```python
# tests/test_material_establish.py
"""Establishment = pricing mints/attaches the lot (spec §core move)."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.inventory.models import Earmark, InventoryItem, Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Job


class EstablishBase(TestCase):
    def setUp(self):
        Configuration.objects.create(
            key='default_material_markup_percent', value='25')
        self.cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MAT')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='5')
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-2026-0001')

    def _provisional(self, **kw):
        kw.setdefault('quantity', Decimal('4'))
        return MaterialService.create_on_job(
            job=self.job, description='dragon skin',
            accounting_category=self.cat, units='ea', **kw)


class EstablishTests(EstablishBase):
    def test_provisional_birth_no_lot_null_source(self):
        m = self._provisional()
        self.assertIsNone(m.inventory_item_id)
        self.assertIsNone(m.cost_source)
        self.assertFalse(Earmark.objects.filter(job=self.job).exists())

    def test_establish_mints_lot_with_markup_sell_and_earmark(self):
        m = self._provisional()
        MaterialService.establish(m, unit_cost=Decimal('100.00'))
        m.refresh_from_db()
        lot = m.inventory_item
        self.assertIsNotNone(lot)
        self.assertEqual(lot.code, f'LOT-{m.pk}')
        self.assertEqual(lot.qty_on_hand, Decimal('0.00'))
        self.assertEqual(lot.purchase_price, Decimal('100.00'))
        self.assertEqual(lot.selling_price, Decimal('125.00'))  # 25% markup
        self.assertEqual(m.sell_price, Decimal('125.00'))
        self.assertEqual(m.cost_source, Material.COST_SOURCE_ENTERED)
        em = Earmark.objects.get(inventory_item=lot, job=self.job)
        self.assertEqual(em.quantity, Decimal('4'))

    def test_establish_keeps_estimate_locked_sell_price(self):
        m = self._provisional(sell_price=Decimal('400.00'))
        MaterialService.establish(m, unit_cost=Decimal('300.00'))
        m.refresh_from_db()
        self.assertEqual(m.sell_price, Decimal('400.00'))  # locked, not re-derived

    def test_establish_attaches_existing_item(self):
        item = InventoryItem.objects.create(
            code='ACR', accounting_category=self.cat, units='ea',
            purchase_price=Decimal('10.00'), selling_price=Decimal('15.00'))
        m = self._provisional()
        MaterialService.establish(m, inventory_item=item)
        m.refresh_from_db()
        self.assertEqual(m.inventory_item_id, item.pk)
        self.assertEqual(m.unit_cost, Decimal('10.00'))
        self.assertEqual(m.cost_source, Material.COST_SOURCE_ENTERED)

    def test_establish_refuses_established_and_nonpending(self):
        m = self._provisional()
        MaterialService.establish(m, unit_cost=Decimal('1.00'))
        with self.assertRaises(ValidationError):
            MaterialService.establish(m, unit_cost=Decimal('2.00'))

    def test_create_on_job_with_cost_is_born_established(self):
        m = MaterialService.create_on_job(
            job=self.job, description='ply', quantity=Decimal('2'),
            unit_cost=Decimal('50.00'), accounting_category=self.cat, units='ea')
        self.assertIsNotNone(m.inventory_item_id)
        self.assertEqual(m.cost_source, Material.COST_SOURCE_ENTERED)

    def test_no_earmark_on_preapproval_job(self):
        self.job.status = Job.STATUS_DRAFT
        self.job.save()
        m = self._provisional()
        MaterialService.establish(m, unit_cost=Decimal('10.00'))
        self.assertFalse(Earmark.objects.filter(job=self.job).exists())
```

- [ ] **Step 2: Run — fails** (`establish` undefined; freeform-cost refusal fires on `test_create_on_job_with_cost...`).

- [ ] **Step 3: Implement** in `apps/inventory/services.py` (MaterialService):

```python
    @staticmethod
    def _earmark_if_committed(material):
        """Reserve stock only for committed (approved+) jobs — pre-approval
        jobs earmark in bulk at acceptance (create_earmarks_for_job)."""
        from apps.jobs.models import Job as _Job
        _PRE_APPROVAL = (_Job.STATUS_DRAFT, _Job.STATUS_SUBMITTED)
        if material.job.status not in _PRE_APPROVAL:
            InventoryService._mutate_earmark(
                material.inventory_item, material.job, material.quantity)

    @staticmethod
    def mint_lot(material, *, unit_cost, sell_price=None):
        """Create the InventoryItem lot backing a one-off established material.
        QOH 0; sell defaults from the markup config when not supplied."""
        if not sell_price or sell_price == Decimal('0.00'):
            markup = InventoryService._default_markup_percent()
            sell_price = (unit_cost * (Decimal('1') + markup / Decimal('100'))
                          ).quantize(Decimal('0.01'))
        return InventoryService.create_item(
            code=f'LOT-{material.pk}',
            description=material.description,
            units=material.units,
            purchase_price=unit_cost,
            selling_price=sell_price,
            qty_on_hand=Decimal('0.00'),
            accounting_category=material.accounting_category,
        )

    @staticmethod
    def establish(material, *, inventory_item=None, unit_cost=None,
                  sell_price=None, cost_source=None):
        """provisional → established: supplying the price mints/attaches the lot.
        A sell_price already on the material (estimate-locked) is never re-derived."""
        from django.core.exceptions import ValidationError
        from django.db import transaction
        cost_source = cost_source or Material.COST_SOURCE_ENTERED
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('establish requires pending state')
        if material.inventory_item_id is not None:
            raise ValidationError('Material is already established.')
        if inventory_item is None and unit_cost is None:
            raise ValidationError(
                {'unit_cost': ['Establishing without an inventory item requires a cost.']})
        with transaction.atomic():
            locked_sell = material.sell_price
            if inventory_item is None:
                lot = MaterialService.mint_lot(
                    material, unit_cost=unit_cost, sell_price=locked_sell or sell_price)
                material.inventory_item = lot
                material.unit_cost = unit_cost
                if not locked_sell:
                    material.sell_price = lot.selling_price
            else:
                material.inventory_item = inventory_item
                if unit_cost is not None:
                    material.unit_cost = unit_cost
                elif not material.unit_cost:
                    material.unit_cost = inventory_item.purchase_price
                if not locked_sell:
                    material.sell_price = (
                        sell_price if sell_price else inventory_item.selling_price)
            material.cost_source = cost_source
            material.save()
            MaterialService._earmark_if_committed(material)
            MaterialService.consume_if_task_started(material)
        return material
```

In `create_on_job`: delete the freeform-manual-cost refusal block; change the signature's `cost_source='document'` to `cost_source=None`; after the existing save + earmark + consume-sweep logic, add:

```python
            if inventory_item is not None:
                m.cost_source = cost_source or Material.COST_SOURCE_ENTERED
                m.save(update_fields=['cost_source'])
            elif unit_cost and unit_cost != Decimal('0.00'):
                # Priced at authoring with no item pick → born established.
                m = MaterialService.establish(
                    m, unit_cost=unit_cost, cost_source=cost_source)
```

(Place the mint AFTER the create so `m.pk` exists for the lot code; pass `unit_cost=Decimal('0.00')` into the `Material(...)` constructor in that branch so `_populate_from_pli` doesn't fight — the establish call sets it.) Sweep old callers: `grep -rn "cost_source='manual'\|cost_source='document'" apps/` — replace with the new enum values (`COST_SOURCE_EXPENSE` in `ExpenseService`, `COST_SOURCE_PO` in the PO resolver) or drop the kwarg. In `update_pricing`, delete the `cost_source` parameter and its docstring paragraph (provenance is now set by callers on the Material).

In `apps/api/inventory/serializers.py` `MaterialSerializer.validate`: delete the freeform `unit_cost` refusal block. In `MaterialService.update_fields`: replace the PLI-null branch's behavior so a pricing write on a provisional material establishes:

```python
        if material.inventory_item_id is None:
            inv = fields.pop('inventory_item', None)
            uc = fields.pop('unit_cost', None)
            sp = fields.pop('sell_price', None)
            if inv is not None or (uc and uc != Decimal('0.00')):
                MaterialService.establish(
                    material, inventory_item=inv, unit_cost=uc, sell_price=sp)
            elif sp is not None:
                fields['sell_price'] = sp  # sell-only edit stays provisional
```

- [ ] **Step 4: Green** — `python manage.py test tests.test_material_establish tests.test_material_service_create tests.test_freeform_material_cost tests.test_api_materials tests.test_material_ops` → `OK`. `tests/test_freeform_material_cost.py` asserted the old refusal — rewrite those tests to assert the new minting behavior instead (the refusal is gone by design; cite spec §establishment).

- [ ] **Step 5: Commit** — `feat(inventory): establishment mints/attaches the lot; pricing = establishment`

---

### Task 6: `consume()` refuses provisional; late-add sweep stays pending

**Files:**
- Modify: `apps/inventory/services.py` (`consume`, `consume_if_task_started`)
- Test: extend `tests/test_consume_material_uniformity.py`

- [ ] **Step 1: Failing test** (add to `tests/test_consume_material_uniformity.py`; refit that file's existing freeform-silent-flip tests — they now assert the refusal):

```python
    def test_consume_provisional_raises(self):
        """Spec §consume gating: a null-lot material must refuse, never flip."""
        m = MaterialService.create_on_job(
            job=self.job, description='mystery', quantity=Decimal('1'),
            accounting_category=self.cat, units='ea')
        self.assertIsNone(m.inventory_item_id)
        with self.assertRaises(ValidationError):
            MaterialService.consume(m)
        m.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)

    def test_late_add_sweep_leaves_provisional_pending(self):
        """consume_if_task_started must not raise on provisional — in-flight
        pricing is a legitimate pending state (mirrors the understock rule)."""
        m = MaterialService.create_on_job(
            job=self.job, task=self.started_task, description='mystery',
            quantity=Decimal('1'), accounting_category=self.cat, units='ea')
        m.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
```

(Use that file's existing job/task fixtures for a started task; if it has none, borrow the pattern from `tests/test_late_material_consumption.py`.)

- [ ] **Step 2: Run — first test fails** (silent flip to consumed).

- [ ] **Step 3: Implement.** In `consume()`, after the pending-state check:

```python
        if material.inventory_item_id is None:
            raise ValidationError(
                'This material is provisional — set its pricing and receive it '
                'before work can consume it.'
            )
```

In `consume_if_task_started()`, replace the `pli is not None` stock check block's surroundings with an early return for provisional:

```python
        pli = material.inventory_item
        if pli is None:
            return material  # provisional: stays pending, never silently consumed
        if material.quantity > Decimal('0.00'):
            pli.refresh_from_db()
            if pli.qty_on_hand < material.quantity:
                return material
        return MaterialService.consume(material)
```

Also polish the shortfall message in `consume()` (spec §consume gating): append `' If it is on order or coming from the customer, wait for arrival.'` to the existing "Cannot consume…" error.

- [ ] **Step 4: Ripple sweep.** Run the full suite: `python manage.py test 2>&1 | tee /tmp/t6.log`; read the summary. Tests that created freeform materials and expected consumption now fail — fix each by making the material established (give it a `unit_cost` at create, which now mints, then `mark_on_hand`-style QOH… until Task 11 exists, bump the lot directly in the test: `m.inventory_item.qty_on_hand = m.quantity; m.inventory_item.save()`). Candidates: `test_late_material_consumption`, `test_blep_start_material_sweep`, `test_complete_task_material_guard`, `test_loose_material_work_complete`, `test_preapproval_work_materials`, `test_job_direct_materials`. Do NOT weaken the new refusal to spare test churn (CLAUDE.md engineering principles).

- [ ] **Step 5: Commit** — `feat(inventory): consume() refuses provisional materials`

---

### Task 7: Acceptance crystallization — reverse-markup establishment; PO link overrides cost

**Files:**
- Modify: `apps/estimates/acceptance.py:91-115` (is_material branch), `apps/inventory/services.py` (`resolve_or_create_for_line` + `_resolve_material_for_line` call sites in `apps/purchasing/services.py` — read them first)
- Test: extend `tests/test_acceptance_provisional_material.py`; new assertions in `tests/test_material_resolve_or_create.py`

- [ ] **Step 1: Failing tests.** In `tests/test_acceptance_provisional_material.py` (reuse its existing acceptance fixture; it currently asserts the bare-marked line yields a null-lot material — update those to the new behavior):

```python
    def test_marked_line_establishes_with_reverse_markup(self):
        """Spec §provisional cost: sell $400, 25% markup → cost $320, estimated."""
        # fixture: default_material_markup_percent = 25, line price 400, qty 1
        material = self._accept_and_get_material()
        self.assertIsNotNone(material.inventory_item_id)
        self.assertEqual(material.sell_price, Decimal('400.00'))
        self.assertEqual(material.unit_cost, Decimal('320.00'))
        self.assertEqual(material.cost_source, Material.COST_SOURCE_ESTIMATED)
        self.assertEqual(material.inventory_item.qty_on_hand, Decimal('0.00'))
```

In `tests/test_material_resolve_or_create.py`:

```python
    def test_po_link_overrides_estimated_cost(self):
        """Spec: the PO write overrides the placeholder; sell stays locked."""
        material = self._estimated_material(sell=Decimal('400.00'))  # cost_source='estimated'
        li = self._add_po_line(price=Decimal('345.00'), material_id=material.pk)
        material.refresh_from_db()
        self.assertEqual(material.unit_cost, Decimal('345.00'))
        self.assertEqual(material.cost_source, Material.COST_SOURCE_PO)
        self.assertEqual(material.sell_price, Decimal('400.00'))
```

(Build `_estimated_material` / `_add_po_line` helpers from that file's existing PO-line fixtures.)

- [ ] **Step 2: Run — fail** (material stays provisional; cost untouched).

- [ ] **Step 3: Implement.** `apps/estimates/acceptance.py` is_material branch — after `create_on_job(...)`, before the source-row create:

```python
                sell = li.price or Decimal('0')
                markup = InventoryService._default_markup_percent()
                unit_cost = (
                    sell / (Decimal('1') + markup / Decimal('100'))
                ).quantize(Decimal('0.01'))
                material = MaterialService.establish(
                    material, unit_cost=unit_cost,
                    cost_source=Material.COST_SOURCE_ESTIMATED,
                )
```

(Import `InventoryService` + `Material`; update the now-stale out-of-scope comment block above the branch.) In the PO↔material resolver (`MaterialService.resolve_or_create_for_line`): in the explicit-`material_id` and claim branches, after linking, when `li.price` is set and differs:

```python
            MaterialService.update_pricing(material, unit_cost=li.price)
            material.cost_source = Material.COST_SOURCE_PO
            material.save(update_fields=['cost_source'])
```

In the create-new branch, pass `cost_source=Material.COST_SOURCE_PO` to `create_on_job`. If the explicit-link path can receive a *provisional* material (it can — Order requires established, but a hand-built PO line may name one), route it through `establish(material, unit_cost=li.price, cost_source=Material.COST_SOURCE_PO)` instead of `update_pricing`.

- [ ] **Step 4: Green** — `python manage.py test tests.test_acceptance_provisional_material tests.test_material_resolve_or_create tests.test_api_po_job_material tests.test_po_receive_with_material tests.test_material_link_to_po_line` → `OK`.

- [ ] **Step 5: Commit** — `feat(estimates,purchasing): reverse-markup establishment at acceptance; PO cost override`

---

### Task 8: Order action — append-or-create draft PO from a material

**Files:**
- Modify: `apps/inventory/services.py` (`MaterialService.order`), `apps/api/inventory/views.py` (+action), `apps/api/inventory/serializers.py` (tiny request serializer)
- Modify: `frontend/src/routes/jobs/JobTaskListPage.svelte` (Order button + choice dialog — full UI wiring lands with Task 12's status chips; here add the API helper + a minimal button)
- Test: `tests/test_material_order_action.py` (new)

**Interfaces — Produces:** `MaterialService.order(material, po=None) -> (po, line_item)`; `POST /api/materials/{id}/order/` body `{"po_id": <int, optional>}` → `{material..., 'po_id', 'po_number'}`. Permission: `CanManageFinancials`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_material_order_action.py
"""Order-from-material: append to a chosen draft or start a vendor-less one (spec Path 1)."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.inventory.models import Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Job
from apps.purchasing.models import PurchaseOrder


class OrderFromMaterialTests(TestCase):
    def setUp(self):
        for key, value in (('po_number_sequence', 'PO-{year}-{counter:04d}'),
                           ('default_material_markup_percent', '25')):
            Configuration.objects.create(key=key, value=value)
        AppState.objects.create(key='po_counter', value='0')
        self.cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MAT')
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='5')
        self.job = Job.objects.create(
            contact=contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001')
        self.material = MaterialService.create_on_job(
            job=self.job, description='steel', quantity=Decimal('3'),
            unit_cost=Decimal('80.00'), accounting_category=self.cat, units='ea')

    def test_order_creates_vendorless_draft_and_links(self):
        po, li = MaterialService.order(self.material)
        self.assertEqual(po.status, PurchaseOrder.STATUS_DRAFT)
        self.assertIsNone(po.business_id)
        self.assertEqual(li.inventory_item_id, self.material.inventory_item_id)
        self.assertEqual(li.qty, Decimal('3'))
        self.material.refresh_from_db()
        self.assertEqual(self.material.po_line_item_id, li.pk)

    def test_order_appends_to_given_draft(self):
        po, _ = MaterialService.order(self.material)
        m2 = MaterialService.create_on_job(
            job=self.job, description='rod', quantity=Decimal('1'),
            unit_cost=Decimal('10.00'), accounting_category=self.cat, units='ea')
        po2, li2 = MaterialService.order(m2, po=po)
        self.assertEqual(po2.pk, po.pk)
        self.assertEqual(po.line_items.count(), 2)

    def test_order_refuses_provisional_linked_and_customer(self):
        prov = MaterialService.create_on_job(
            job=self.job, description='?', quantity=Decimal('1'),
            accounting_category=self.cat, units='ea')
        with self.assertRaises(ValidationError):
            MaterialService.order(prov)
        with self.assertRaises(ValidationError):
            MaterialService.order(self.material) and MaterialService.order(self.material)
```

(Confirm the PO line related name — `line_items` — against the model; adjust.)

- [ ] **Step 2: Run — fails** (`order` undefined).

- [ ] **Step 3: Implement** service:

```python
    @staticmethod
    def order(material, po=None):
        """Path 1: start (or append to) a draft PO with a line linked to this
        material. Vendor-less create is fine — vendor is required at issue."""
        from django.core.exceptions import ValidationError
        from django.db import transaction
        from apps.purchasing.models import PurchaseOrder
        from apps.purchasing.services import PurchaseOrderService
        if material.inventory_item_id is None:
            raise ValidationError('Set pricing on this material before ordering.')
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('Only a pending material can be ordered.')
        if material.is_customer_supplied:
            raise ValidationError(
                'A customer-supplied material is not ordered — the customer sends it.')
        if material.po_line_item_id is not None:
            raise ValidationError('Material is already on a purchase order.')
        if po is not None and po.status != PurchaseOrder.STATUS_DRAFT:
            raise ValidationError('Can only add lines to a draft purchase order.')
        with transaction.atomic():
            if po is None:
                po = PurchaseOrderService.create_po()
            li = PurchaseOrderService.add_line_item_from_pli(
                po.pk, material.inventory_item_id, material.quantity,
                job=material.job_id, material_id=material.pk)
        return po, li
```

API action in `MaterialViewSet`:

```python
    @action(detail=True, methods=['post'],
            permission_classes=[IsAuthenticated, CanManageFinancials])
    def order(self, request, pk=None):
        m = self.get_object()
        po = None
        po_id = request.data.get('po_id')
        if po_id:
            po = get_object_or_404(PurchaseOrder, pk=po_id)
        po, _li = MaterialService.order(m, po=po)
        m.refresh_from_db()
        data = MaterialSerializer(m).data
        data['po_id'], data['po_number'] = po.pk, po.po_number
        return Response(data)
```

(Imports: `CanManageFinancials` from `apps.api.permissions`, `PurchaseOrder`, `get_object_or_404`.) Frontend: add `orderMaterial(materialId, poId)` helper where JobTaskListPage's other material calls live — POST to `/api/materials/${id}/order/`; full button/dialog UI comes in Task 12.

- [ ] **Step 4: Green** — `python manage.py test tests.test_material_order_action tests.test_api_materials` → `OK`.

- [ ] **Step 5: Commit** — `feat(inventory,api): Order action — material to draft PO (append or create)`

---

### Task 9: Expense attach mode — attach-to-existing-material establishes + receives

**Files:**
- Modify: `apps/expenses/services.py` (`ExpenseService.create`), `apps/api/expenses/serializers.py` (`material_id` write field), `apps/inventory/services.py` (`receive_ad_hoc_purchase(material, qty=None)`)
- Test: `tests/test_expense_attach_material.py` (new)

**Interfaces — Produces:** `ExpenseService.create(..., material_id=<pk>, attach_qty=None)` — attach == receipt; establishes a provisional target.

- [ ] **Step 1: Failing tests**

```python
# tests/test_expense_attach_material.py
"""Path 2: attaching an expense prices AND receives (spec §Path 2)."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
# imports as in tests/test_expense_service.py — reuse its user/job fixture setup


class ExpenseAttachTests(TestCase):
    # setUp: copy the user/cat/job scaffold from tests/test_expense_service.py,
    # plus Configuration default_material_markup_percent=25.

    def test_attach_to_established_receives_and_reprices(self):
        m = MaterialService.create_on_job(
            job=self.job, description='ply', quantity=Decimal('4'),
            unit_cost=Decimal('50.00'), accounting_category=self.cat, units='ea')
        e = ExpenseService.create(
            entered_by=self.user, amount=Decimal('240.00'),
            description='bought at yard', material_id=m.pk)
        m.refresh_from_db()
        self.assertEqual(e.material_id, m.pk)
        self.assertEqual(m.unit_cost, Decimal('60.00'))          # 240/4
        self.assertEqual(m.cost_source, Material.COST_SOURCE_EXPENSE)
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('4'))  # attach == receipt

    def test_attach_to_provisional_establishes(self):
        m = MaterialService.create_on_job(
            job=self.job, description='mystery', quantity=Decimal('2'),
            accounting_category=self.cat, units='ea')
        ExpenseService.create(
            entered_by=self.user, amount=Decimal('30.00'),
            description='corner store', material_id=m.pk)
        m.refresh_from_db()
        self.assertIsNotNone(m.inventory_item_id)
        self.assertEqual(m.unit_cost, Decimal('15.00'))
        self.assertEqual(m.cost_source, Material.COST_SOURCE_EXPENSE)
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('2'))

    def test_attach_partial_qty_tops_up(self):
        m = MaterialService.create_on_job(
            job=self.job, description='ply', quantity=Decimal('12'),
            unit_cost=Decimal('10.00'), accounting_category=self.cat, units='ea')
        m.inventory_item.qty_on_hand = Decimal('8')   # partial PO receipt happened
        m.inventory_item.save()
        ExpenseService.create(
            entered_by=self.user, amount=Decimal('44.00'),
            description='last 4 locally', material_id=m.pk,
            attach_qty=Decimal('4'))
        m.refresh_from_db()
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('12'))
        self.assertEqual(m.unit_cost, Decimal('11.00'))          # 44/4

    def test_attach_refuses_customer_and_nonpending(self):
        m = MaterialService.create_on_job(
            job=self.job, description='theirs', quantity=Decimal('1'),
            accounting_category=self.cat, units='ea', customer_supplied=True)
        with self.assertRaises(ValidationError):
            ExpenseService.create(entered_by=self.user, amount=Decimal('5.00'),
                                  description='x', material_id=m.pk)
```

(`customer_supplied=True` lands in Task 10 — mark that one test `@skip('Task 10')` for now and unskip there.)

- [ ] **Step 2: Run — fails** (unexpected kwarg `material_id`).

- [ ] **Step 3: Implement.** Extend `receive_ad_hoc_purchase(material, qty=None)`: `qty = qty if qty is not None else material.quantity`, bump by `qty` (keep history action). In `ExpenseService.create`, add `material_id=None, attach_qty=None` params; before the `new_material` handling:

```python
            if material_id:
                from apps.inventory.models import Material
                from apps.inventory.services import InventoryService, MaterialService
                material = Material.objects.get(pk=material_id)
                if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
                    raise ValidationError('Can only attach to a pending material.')
                if material.is_customer_supplied:
                    raise ValidationError(
                        'A customer-supplied material has no purchase to attach.')
                if job is None:
                    job = material.job
                qty = attach_qty or material.quantity
                if qty <= Decimal('0.00'):
                    raise ValidationError({'attach_qty': ['Quantity must be positive.']})
                unit_cost = (amount / qty).quantize(Decimal('0.01'))
                if material.inventory_item_id is None:
                    MaterialService.establish(
                        material, unit_cost=unit_cost,
                        cost_source=Material.COST_SOURCE_EXPENSE)
                else:
                    MaterialService.update_pricing(material, unit_cost=unit_cost)
                    material.cost_source = Material.COST_SOURCE_EXPENSE
                    material.save(update_fields=['cost_source'])
                material.refresh_from_db()
                InventoryService.receive_ad_hoc_purchase(material, qty=qty)
```

then link `material` onto the Expense exactly as the `new_material` branch does (same field, same downstream). Mutual exclusion: `material_id` + `new_material` together → `ValidationError`. Serializer: `material_id = serializers.IntegerField(required=False, write_only=True)` + `attach_qty` Decimal write-only; thread through the viewset's `perform_create` → service.

- [ ] **Step 4: Green** — `python manage.py test tests.test_expense_attach_material tests.test_expense_service tests.test_api_expenses tests.test_expense_material_inventory` → `OK`.

- [ ] **Step 5: Commit** — `feat(expenses): attach-to-material mode — attach == receipt, establishes provisional`

---

### Task 10: Customer-supplied materials — creation toggle, $0 locked, suppressions

**Files:**
- Modify: `apps/inventory/services.py` (`create_on_job(customer_supplied=False)`, `update_fields` lock), `apps/api/inventory/serializers.py` + the job-materials create path (find it: `grep -rn "create_on_job" apps/api/`) to accept `customer_supplied`
- Test: `tests/test_material_customer_supplied.py` (new); unskip the Task-9 test

**Interfaces — Produces:** `create_on_job(..., customer_supplied=True)` → born established, lot at $0/$0, `cost_source='customer_supplied'`; pricing edits refused; `customer_supplied` accepted on the create API.

- [ ] **Step 1: Failing tests**

```python
# tests/test_material_customer_supplied.py
"""Path 4: customer-supplied = established at a deliberate, locked $0 (spec §Path 4)."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
# scaffold imports as in tests/test_material_establish.py


class CustomerSuppliedTests(TestCase):
    # setUp identical to EstablishBase (markup config, cat, contact, approved job)

    def _customer_material(self, qty=Decimal('12')):
        return MaterialService.create_on_job(
            job=self.job, description='museum panels', quantity=qty,
            accounting_category=self.cat, units='ea', customer_supplied=True)

    def test_born_established_at_locked_zero(self):
        m = self._customer_material()
        self.assertIsNotNone(m.inventory_item_id)
        self.assertEqual(m.unit_cost, Decimal('0.00'))
        self.assertEqual(m.sell_price, Decimal('0.00'))
        self.assertEqual(m.cost_source, Material.COST_SOURCE_CUSTOMER)
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('0.00'))
        self.assertEqual(m.inventory_item.selling_price, Decimal('0.00'))
        em = Earmark.objects.get(inventory_item=m.inventory_item, job=self.job)
        self.assertEqual(em.quantity, Decimal('12'))

    def test_pricing_is_locked(self):
        m = self._customer_material()
        with self.assertRaises(ValidationError):
            MaterialService.update_fields(m, unit_cost=Decimal('5.00'))
        with self.assertRaises(ValidationError):
            MaterialService.update_fields(m, sell_price=Decimal('5.00'))

    def test_consume_blocks_until_received(self):
        m = self._customer_material()
        with self.assertRaises(ValidationError):
            MaterialService.consume(m)
```

- [ ] **Step 2: Run — fails** (unexpected kwarg).

- [ ] **Step 3: Implement.** `create_on_job(..., customer_supplied=False)`; in the body, after the material row save, before other establishment branches:

```python
            if customer_supplied:
                if inventory_item is not None or (unit_cost and unit_cost != Decimal('0.00')):
                    raise ValidationError(
                        'A customer-supplied material carries no purchase pricing.')
                return MaterialService.establish(
                    m, unit_cost=Decimal('0.00'), sell_price=Decimal('0.00'),
                    cost_source=Material.COST_SOURCE_CUSTOMER)
```

`establish`/`mint_lot` already handle $0 (markup on 0 is 0) — but `mint_lot`'s `if not sell_price` guard derives from cost 0 → 0; verify the minted lot's `selling_price` is 0 (the `create_item` markup fallback only fires when `purchase_price` is truthy, so it stays 0 — the first test asserts this). Wait — `establish` with `locked_sell == 0` sets `material.sell_price = lot.selling_price` = 0. Correct. Lock in `update_fields` (both branches — the PLI-backed pricing carve-out and the establish route):

```python
        if material.is_customer_supplied and (
                'unit_cost' in fields or 'sell_price' in fields):
            raise ValidationError(
                'A customer-supplied material is not priced — it is the '
                'customer’s property, carried at zero.')
```

API: add `customer_supplied = serializers.BooleanField(required=False, write_only=True, default=False)` to `MaterialSerializer`; pass through wherever the job-materials create endpoint calls `create_on_job`. Unskip the Task-9 test.

- [ ] **Step 4: Green** — `python manage.py test tests.test_material_customer_supplied tests.test_expense_attach_material tests.test_api_materials tests.test_material_immutability` → `OK`.

- [ ] **Step 5: Commit** — `feat(inventory): customer-supplied materials — established at locked $0`

---

### Task 11: Mark on-hand / Mark received

**Files:**
- Modify: `apps/inventory/services.py` (`MaterialService.mark_on_hand`), `apps/api/inventory/views.py` (+action), reuse `MaterialOpSerializer`
- Test: `tests/test_material_mark_on_hand.py` (new)

**Interfaces — Produces:** `MaterialService.mark_on_hand(material, qty, user=None) -> Material`; `POST /api/materials/{id}/mark-on-hand/` body `{"quantity": n}` (IsAuthenticated — shop-floor arrival marking, like task ops). History action: `'Customer delivery'` for customer-supplied, `'Marked on-hand'` otherwise.

- [ ] **Step 1: Failing tests**

```python
# tests/test_material_mark_on_hand.py
"""Paths 3+4 receipt: an explicit, recorded QOH bump in job context (spec §Path 3/4)."""
# scaffold as in tests/test_material_establish.py
from apps.core.models import HistoryEntry


class MarkOnHandTests(TestCase):
    def test_mark_on_hand_bumps_lot_and_records_history(self):
        m = MaterialService.create_on_job(
            job=self.job, description='steel', quantity=Decimal('3'),
            unit_cost=Decimal('10.00'), accounting_category=self.cat, units='ea')
        MaterialService.mark_on_hand(m, Decimal('3'))
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('3'))
        entry = HistoryEntry.objects.filter(
            object_type='inventoryitem', object_id=m.inventory_item_id).latest('pk')
        self.assertEqual(entry.changes.get('_action'), 'Marked on-hand')
        MaterialService.consume(m)   # arrival satisfied the gate

    def test_customer_delivery_action_label_and_partial(self):
        m = MaterialService.create_on_job(
            job=self.job, description='panels', quantity=Decimal('12'),
            accounting_category=self.cat, units='ea', customer_supplied=True)
        MaterialService.mark_on_hand(m, Decimal('8'))
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('8'))
        entry = HistoryEntry.objects.filter(
            object_type='inventoryitem', object_id=m.inventory_item_id).latest('pk')
        self.assertEqual(entry.changes.get('_action'), 'Customer delivery')
        with self.assertRaises(ValidationError):
            MaterialService.consume(m)          # 8 < 12 still blocks

    def test_refuses_provisional_and_nonpositive(self):
        prov = MaterialService.create_on_job(
            job=self.job, description='?', quantity=Decimal('1'),
            accounting_category=self.cat, units='ea')
        with self.assertRaises(ValidationError):
            MaterialService.mark_on_hand(prov, Decimal('1'))
```

(Verify `HistoryEntry` model/lookup shape against `InventoryService._record_qoh_history` / an existing history test — copy its query idiom.)

- [ ] **Step 2: Run — fails** (`mark_on_hand` undefined).

- [ ] **Step 3: Implement**

```python
    @staticmethod
    def mark_on_hand(material, qty, *, user=None):
        """Deliberate no-document receipt (Path 3), and the customer-delivery
        receipt for customer-supplied materials (Path 4)."""
        from django.core.exceptions import ValidationError
        from django.db.models import F
        if material.inventory_item_id is None:
            raise ValidationError('Set pricing on this material first.')
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('Only a pending material can be received.')
        if qty <= Decimal('0.00'):
            raise ValidationError({'quantity': ['Quantity must be positive.']})
        pli = material.inventory_item
        pli.qty_on_hand = F('qty_on_hand') + qty
        pli.save(update_fields=['qty_on_hand'])
        pli.refresh_from_db()
        action = ('Customer delivery' if material.is_customer_supplied
                  else 'Marked on-hand')
        InventoryService._record_qoh_history(
            pli, qty, action=action,
            reason=f'{action} on job {material.job.job_number}',
            job=material.job, user=user)
        return material
```

API action:

```python
    @action(detail=True, methods=['post'], url_path='mark-on-hand')
    def mark_on_hand(self, request, pk=None):
        s = MaterialOpSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        m = self.get_object()
        MaterialService.mark_on_hand(
            m, s.validated_data['quantity'], user=request.user)
        m.refresh_from_db()
        return Response(MaterialSerializer(m).data)
```

- [ ] **Step 4: Green** — `python manage.py test tests.test_material_mark_on_hand tests.test_api_materials` → `OK`.

- [ ] **Step 5: Commit** — `feat(inventory,api): mark-on-hand / customer-delivery receipt`

---

### Task 12: Frontend — `materialStatus.js` + status chips, actions, consumed flag

**Files:**
- Create: `frontend/src/lib/materialStatus.js`; Test: `frontend/tests/materialStatus.test.js`
- Modify: `frontend/src/routes/jobs/JobTaskListPage.svelte` (chips + actions per state), `frontend/src/components/TaskTree.svelte` (passive chip), `frontend/src/css/app.css` (chip styles if a shared class fits better than component styles)

**Interfaces — Produces:** `materialStatus(m) -> {key, label}`; `costUnconfirmed(m) -> bool`. Keys: `needs-pricing | needed | ordered | awaiting-customer | on-hand | consumed | released`.

- [ ] **Step 1: Failing Vitest**

```js
// frontend/tests/materialStatus.test.js
import { describe, it, expect } from 'vitest';
import { materialStatus, costUnconfirmed } from '../src/lib/materialStatus.js';

const base = {
  inventory_item: 7, cost_source: 'entered', consumption_state: 'pending',
  quantity: '4.00', qty_on_hand: '0.00', po_line_item_id: null, po_number: null,
};

describe('materialStatus', () => {
  it('released and consumed win over everything', () => {
    expect(materialStatus({ ...base, consumption_state: 'released' }).key).toBe('released');
    expect(materialStatus({ ...base, consumption_state: 'consumed' }).key).toBe('consumed');
  });
  it('provisional → needs-pricing', () => {
    expect(materialStatus({ ...base, inventory_item: null, cost_source: null }).key)
      .toBe('needs-pricing');
  });
  it('customer short → awaiting-customer', () => {
    expect(materialStatus({ ...base, cost_source: 'customer_supplied' }).key)
      .toBe('awaiting-customer');
  });
  it('stock covers → on-hand (incl. customer)', () => {
    expect(materialStatus({ ...base, qty_on_hand: '4.00' }).key).toBe('on-hand');
    expect(materialStatus({ ...base, cost_source: 'customer_supplied', qty_on_hand: '5.00' }).key)
      .toBe('on-hand');
  });
  it('linked PO → ordered with number in label', () => {
    const s = materialStatus({ ...base, po_line_item_id: 3, po_number: 'PO-2026-0042' });
    expect(s.key).toBe('ordered');
    expect(s.label).toContain('PO-2026-0042');
  });
  it('established + short + unlinked → needed', () => {
    expect(materialStatus(base).key).toBe('needed');
  });
  it('costUnconfirmed only for estimated', () => {
    expect(costUnconfirmed({ ...base, cost_source: 'estimated' })).toBe(true);
    expect(costUnconfirmed(base)).toBe(false);
  });
});
```

- [ ] **Step 2:** `cd frontend && npm run test:run` — fails (module missing).

- [ ] **Step 3: Implement**

```js
// frontend/src/lib/materialStatus.js
// One derived display status per material row (spec §UI surface). Pure —
// computed from serializer fields; no new backend state machine.
const short = (m) => Number(m.qty_on_hand) < Number(m.quantity);

export function materialStatus(m) {
  if (m.consumption_state === 'released') return { key: 'released', label: 'Released' };
  if (m.consumption_state === 'consumed') return { key: 'consumed', label: 'Consumed' };
  if (!m.inventory_item) return { key: 'needs-pricing', label: 'Needs pricing' };
  if (!short(m)) return { key: 'on-hand', label: 'On Hand' };
  if (m.cost_source === 'customer_supplied')
    return { key: 'awaiting-customer', label: 'Awaiting customer' };
  if (m.po_line_item_id)
    return { key: 'ordered', label: `Ordered — ${m.po_number || 'PO'}` };
  return { key: 'needed', label: 'Needed' };
}

export function costUnconfirmed(m) {
  return m.cost_source === 'estimated';
}

// Default receipt quantity for Mark received / Mark on-hand prompts.
export function remainingShortfall(m) {
  return Math.max(Number(m.quantity) - Number(m.qty_on_hand), 0);
}
```

- [ ] **Step 4: Wire the venues.**
  - **TaskTree.svelte (pillar — passive):** render `<span class="mat-status mat-{status.key}">{status.label}</span>` on each material row; keep/extend the existing `consumed` row styling; add `released` styling (greyed + line-through via the existing pattern at line ~276). No buttons, no action links (venue rule).
  - **JobTaskListPage.svelte (actions venue):** per material row, the chip plus state-driven actions calling existing/new endpoints: `needs-pricing` → "Set pricing" button (opens MaterialModal in edit mode) ; `needed` → **Order** button + "Attach expense" link (`#/expenses/new?material={id}&job={id}`) + quiet `Mark on-hand` text link (class `quiet-link`, opens qty prompt defaulting to `remainingShortfall(m)`, POSTs `mark-on-hand`); `ordered` → PO number as `<a use:link href="#/purchase-orders/{m.po_id}">`; `awaiting-customer` → **Mark received** button (same qty prompt/endpoint); `consumed` → ✓ mark (`<span class="mat-consumed" title="Consumed">✓</span>`); `released` → tombstone styling. Cost-unconfirmed: `{#if costUnconfirmed(m)}<span class="cost-warn" title="Cost unconfirmed — placeholder from estimate markup">⚠</span>{/if}` beside the cost cell.
  - **Order flow:** on click, `GET /api/purchase-orders/?status=draft&page_size=100`; if zero drafts POST `order` directly; else open a small Modal (reuse the shared Modal shell) listing `PO-number — vendor-or-'no vendor'` options + "Start new PO", then POST with/without `po_id`. Success → `showSuccess` with the PO number; errors → `triageError`.
  - Gate Order behind the user's `can_manage_financials` (same store/flag pattern other financial buttons on this page use — check how PO/invoice buttons are gated and copy it).
  - Follow the modal/keyboard conventions from recent commits (`Modal` shell, native `<form>`).

- [ ] **Step 5: Green** — `cd frontend && npm run test:run && npm run build` → both green. Add/extend a JobTaskListPage or TaskTree Vitest only if one already exists for these components (behavior-vs-display triage per `docs/designs/frontend-testing.md`); the status lib test is the required one.

- [ ] **Step 6: Commit** — `feat(spa): material status vocabulary + fulfillment actions on task view`

---

### Task 13: MaterialModal — set-pricing establishes; customer-supplied toggle

**Files:**
- Modify: `frontend/src/components/MaterialModal.svelte`
- Test: extend the modal's existing Vitest if present; otherwise the API-level behavior is already covered (Tasks 5, 10)

- [ ] **Step 1:** Read the component. Changes:
  - **Create mode:** add a "Customer-supplied (no charge — customer sends it)" checkbox. Checked → zero + disable both pricing inputs and the item picker; submit sends `customer_supplied: true`.
  - **Freeform cost entry now allowed** (Task 5 removed the refusal): enable the unit-cost input for no-item materials in create and edit; helper text "Entering a cost sets this material up for ordering" on provisional rows.
  - **Edit mode on a provisional row:** title/action reads "Set pricing" when opened from the Needs-pricing action (pass a prop from JobTaskListPage).
  - **Customer-supplied rows in edit:** pricing inputs disabled with a "customer-supplied — carried at $0" note.
- [ ] **Step 2:** Manual check via `npm run build`; extend `frontend/tests/` component test if one exists for MaterialModal.
- [ ] **Step 3: Commit** — `feat(spa): MaterialModal — set-pricing establishment + customer-supplied toggle`

---

### Task 14: Inventory list + picker ranking

**Files:**
- Modify: `apps/api/inventory/views.py` (ordering), `frontend/src/routes/inventory/InventoryListPage.svelte` (merge dialog discard options already widened in Task 3 — verify), `frontend/src/components/PriceListPicker.svelte` / `InventoryItemPicker.svelte` (no client sort needed once server ranks)
- Test: extend `tests/test_api_inventory.py`

- [ ] **Step 1: Failing test** (in `tests/test_api_inventory.py`):

```python
    def test_list_ranks_in_stock_then_newest(self):
        """Spec §Drop is_catalog: ranking replaces hiding."""
        old_empty = InventoryItem.objects.create(
            code='OLD0', accounting_category=self.cat, units='ea')
        newer_empty = InventoryItem.objects.create(
            code='NEW0', accounting_category=self.cat, units='ea')
        stocked = InventoryItem.objects.create(
            code='STK', accounting_category=self.cat, units='ea',
            qty_on_hand=Decimal('5'))
        resp = self.client.get('/api/price-list-items/?page_size=100')
        codes = [r['code'] for r in resp.json()['results']]
        self.assertLess(codes.index('STK'), codes.index('NEW0'))
        self.assertLess(codes.index('NEW0'), codes.index('OLD0'))
```

(Match that file's auth/setup idioms.)

- [ ] **Step 2: Implement.** In `get_queryset`, after filters:

```python
        from django.db.models import Case, When, Value, IntegerField
        qs = qs.annotate(
            _in_stock=Case(
                When(qty_on_hand__gt=Decimal('0.00'), then=Value(0)),
                default=Value(1), output_field=IntegerField()),
        ).order_by('_in_stock', '-inventory_item_id')
```

(Newest-first is the recency proxy [DEFAULT]; refine to last-touched later if it disappoints.)

- [ ] **Step 3: Green** — `python manage.py test tests.test_api_inventory` → `OK`; `npm run build` green.
- [ ] **Step 4: Commit** — `feat(api): inventory pickers rank in-stock first, then newest`

---

### Task 15: Settings — default material accounting category picker

**Files:**
- Modify: `apps/api/templates_config/views.py` (`settings_view` PATCH validation), `frontend/src/components/settings/AccountingCategories.svelte`
- Test: extend the settings API test (`grep -rln "settings_view\|api-settings" tests/`)

- [ ] **Step 1: Failing test** (in the existing settings API test file):

```python
    def test_default_material_accounting_category_roundtrip(self):
        cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MAT')
        resp = self.client.patch('/api/settings/',
                                 {'default_material_accounting_category': str(cat.pk)},
                                 format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            Configuration.objects.get(
                key='default_material_accounting_category').value, str(cat.pk))

    def test_default_material_accounting_category_rejects_unknown(self):
        resp = self.client.patch('/api/settings/',
                                 {'default_material_accounting_category': '999999'},
                                 format='json')
        self.assertEqual(resp.status_code, 400)
```

- [ ] **Step 2: Implement.** In `settings_view` PATCH, alongside the other validation blocks:

```python
    if 'default_material_accounting_category' in request.data:
        raw = request.data['default_material_accounting_category']
        raw = '' if raw is None else str(raw).strip()
        if raw != '':
            from apps.core.models import AccountingCategory
            try:
                pk = int(raw)
            except (TypeError, ValueError):
                return Response(
                    {'default_material_accounting_category': 'must be a category id'},
                    status=400)
            if not AccountingCategory.objects.filter(pk=pk, is_active=True).exists():
                return Response(
                    {'default_material_accounting_category': 'unknown or inactive category'},
                    status=400)
```

Frontend `AccountingCategories.svelte`: a "Default material category" `<select>` of active categories (the component already loads them) + blank option, current value from `GET /api/settings/`, explicit Save button PATCHing `/api/settings/` (no blur-save), success/error via the component's existing venue pattern.

- [ ] **Step 3: Green** — settings tests `OK`; `npm run test:run && npm run build` green.
- [ ] **Step 4: Commit** — `feat(settings): default material accounting category picker`

---

### Task 16: Converter — `cost_source` + valid states; neals suite

**Files:**
- Modify: `nealsdata/converter/build.py`, `nealsdata/convert.md`
- Test: `python manage.py test tests.test_neals_builders` (mandatory — memory: JSON-scan alone missed a causal-ordering break)

- [ ] **Step 1:** In `build.py`: `_mint_transient_lot`-backed materials and catalog-matched materials get `cost_source='entered'`; any converter-produced provisional material (no cost) keeps `cost_source` null. Confirm Task 3 already stripped `is_catalog` here; update `convert.md` §materials accordingly.
- [ ] **Step 2:** `python manage.py test tests.test_neals_builders 2>&1 | tee /tmp/neals.log` — read summary: `OK`.
- [ ] **Step 3: Commit** — `feat(nealsdata): emit cost_source; drop is_catalog`

---

### Task 17: Full verification + docs

**Files:**
- Modify: `docs/designs/materials-inventory-and-purchasing.md` (§2 items/lots, §3 Material + consumption machine, §4 MaterialService ops, §11 PO↔Material, §15-17 UI), `docs/designs/estimates-and-prices.md` (acceptance crystallization), `docs/designs/data-constraints.md` (cost_source, PO.business nullability), `docs/designs/LATER.md` (drop items this work resolved), `frontend/README.md` (status vocabulary if UI conventions live there)

- [ ] **Step 1:** Full backend suite, FRESH (migrations landed): `python manage.py test 2>&1 | tee /tmp/final.log` — no `--keepdb`; read `Ran N tests ... OK`.
- [ ] **Step 2:** `cd frontend && npm run test:run && npm run build` — green.
- [ ] **Step 3:** Docs pass — every behavior this branch changed lands in the design docs the same session (project rule): establishment/provisional/cost_source, is_catalog removal + ranking, four paths incl. customer-supplied + mark-on-hand history actions, consume refusal, Order/vendor-less drafts + issue gate, UI status table (On Hand naming), settings key UI. Mark the spec doc's status line "implemented on feature/inventory_again".
- [ ] **Step 4: Commit** — `docs(designs): materials/inventory docs reflect the procurement build`

---

## Execution notes

- Tasks 1→11 are strictly ordered (each consumes the previous task's interfaces). Tasks 12-15 (frontend/UX) depend on 1-11 but not on each other. 16 depends on 3+5; 17 is last.
- Only ONE agent runs `manage.py test` at any time. Subagents must be told: branch `feature/inventory_again`, never touch the dev DB (no migrate/shell/loaddata), and repeat the piped-exit-code rule.
- If a step's stated expectation fails for a *different* reason than predicted, stop and investigate (systematic-debugging) — don't force the assertion.

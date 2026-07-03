# Impl plan — material/fee marker + provisional-Material crystallization

> **Status: TDD task plan — ready to execute.** First of three sequenced plans
> (**marker → deferred-crystallization → unified-picker**). Source of truth for
> *what* to build: `docs/plans/2026-06-30-freeform-material-procurement-inventory.md`
> ("proto-Material marker — built here", provisional/established framing). How this
> slice fits the whole: `docs/plans/2026-07-02-add-line-crystallization-and-unified-picker.md`.
> Branch: `feature/unification` (already checked out — do not create a branch or worktree).

## Goal

Give a **bare** freeform estimate line one bit — **"is this a material?"** — so that
at acceptance a checked line crystallizes into a **provisional `Material`** (sell price
only, `inventory_item = None`, cost unset) instead of a **`Fee`**. This retires the
standing LATER item *"Hand-typed estimate material lines can't crystallize into Materials."*

The whole feature is: one `BooleanField`, plumbed through the serializer + the two
line-authoring service methods (with a conflict guard), a new branch in
`EstimateAcceptanceService.on_accept`, and a checkbox on the freeform line-item form.

## Architecture

- **Discriminator (pinned, shared across all three plans).** `on_accept`, per bare
  hand-line (no source row, not a percentage adjustment), resolves the atom type:

  ```
  service_item  → Task              (Plan 2 — NOT built here; leave room ABOVE inventory_item)
  inventory_item → Material          (already exists — unchanged)
  bare + is_material → provisional Material   (THIS plan)
  else → Fee                         (already exists — unchanged)
  ```

  This plan **owns only the `is_material` branch**. It sits **after** the
  `inventory_item` block and **before** the `Fee` block, and is written so Plan 2 can
  insert a `service_item` branch above `inventory_item` without touching it.

- **A provisional Material here is deliberately minimal.** It reuses **today's** existing
  freeform-material behavior: `MaterialService.create_on_job(..., inventory_item=None)`
  produces a `Material` with a `sell_price`, `inventory_item = None`, and cost unset
  (`unit_cost` defaults to `0.00`, `cost_source='document'`). Because `inventory_item`
  is `None`, `MaterialService._mutate_earmark` is a no-op even on the just-approved job,
  so no lot and no earmark are created — correct for a provisional Material (nothing to
  reserve yet).

- **The `is_material` bit only makes sense on a bare line.** A line that already carries
  an `inventory_item` *is* a material (catalog-backed); a percentage-adjustment line is
  document-only. So the service methods **reject** `is_material=True` combined with either
  `inventory_item` or `adjustment_service`.

## Tech Stack

- Backend: Django 5.2, DRF. Model in `apps/estimates/models.py`; services in
  `apps/estimates/services.py` and `apps/estimates/acceptance.py`; serializer in
  `apps/api/estimates/serializers.py`.
- Frontend: Svelte 5 SPA, Vitest + `@testing-library/svelte`
  (`frontend/src/components/LineItemModal.svelte`, `frontend/tests/`).
- Tests: Django `TestCase` in `tests/`; run a module with
  `python manage.py test tests.test_foo` (**never** pipe to `tail`, **never** `--keepdb`).

## Global Constraints

- **TDD, strictly.** Each task = write failing test → run it and read the actual
  `FAILED …` / `Ran N tests` summary to confirm it fails **for the intended reason** →
  minimal impl → run again and read the `OK` summary → commit. Never judge pass/fail by a
  piped exit code.
- **Never write the dev DB.** `makemigrations` is fine; **never** `migrate`, `loaddata`,
  or ORM writes via shell. Tests create their own test DB and tear it down.
- Use model constants, never string literals (`EstimateLineItemSource.SOURCE_MATERIAL`,
  `Estimate.STATUS_*`, `Job.STATUS_*`).
- Line-item deletes go through `LineItemService.delete_line_item_with_renumber` (not
  exercised by this plan, but keep the rule in mind).
- Run each backend test module on its own; **only one agent runs tests at a time**
  (shared MySQL test DB).
- Commit after each green task. Do **not** merge/push/PR — RM reviews in the browser.

## Boundary — explicitly OUT of scope (belongs to later plans/batches)

Do **not** build any of these here:

- Reverse-markup **provisional cost** (`unit_cost = sell ÷ (1 + markup)`),
  `cost_provisional` / `cost_source='estimated'` flags. The provisional Material here has
  **cost unset**.
- **Transient-lot minting**, establishment, the **Order** affordance, PO-cost override.
- The `consume()` provisional-refusal change.
- Any **`service_item`** descriptor work (that is Plan 2). Only leave structural room for
  its future `on_accept` branch.

A provisional Material in this plan carries only a **sell price** and `inventory_item = None`
and uses today's existing freeform-material behavior — nothing more.

## File Structure

```
apps/estimates/
  models.py                         # + EstimateLineItem.is_material (BooleanField)
  migrations/003X_estimatelineitem_is_material.py   # makemigrations output (do NOT migrate)
  services.py                       # add_line_item / update_line_item: accept + validate is_material
  acceptance.py                     # on_accept: bare + is_material → provisional Material branch
apps/api/estimates/
  serializers.py                    # EstimateLineItemSerializer: + 'is_material'
frontend/src/components/
  LineItemModal.svelte              # "Is this a material?" checkbox on the manual form
tests/
  test_estimate_is_material_field.py        # Task 1
  test_estimate_is_material_serializer.py    # Task 2
  test_estimate_is_material_service.py       # Task 3
  test_acceptance_provisional_material.py     # Task 4
frontend/tests/
  LineItemModal.test.js             # Task 5
```

---

## Task 1 — Add `EstimateLineItem.is_material` + migration

Add the field with a `makemigrations`-generated migration. Default `False` so every
existing/omitted line is a Fee-candidate exactly as today.

**Files**
- `apps/estimates/models.py` (edit `EstimateLineItem`)
- `apps/estimates/migrations/003X_estimatelineitem_is_material.py` (generated)
- `tests/test_estimate_is_material_field.py` (new)

**Interfaces**
- Produces: `EstimateLineItem.is_material: bool` (default `False`, persisted).
- Consumes: nothing new.

**Steps**

- [ ] **Write the failing test.** `tests/test_estimate_is_material_field.py`:

  ```python
  from decimal import Decimal
  from django.test import TestCase

  from apps.contacts.models import Contact
  from apps.core.models import AccountingCategory
  from apps.estimates.models import Estimate, EstimateLineItem
  from apps.jobs.models import Job


  class EstimateLineItemIsMaterialFieldTest(TestCase):
      def setUp(self):
          self.cat = AccountingCategory.objects.create(name='Mat', is_active=True, code='MAT')
          self.contact = Contact.objects.create(
              first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
          )
          self.job = Job.objects.create(
              contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
          )
          self.estimate = Estimate.objects.create(
              job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_DRAFT,
          )

      def test_defaults_false(self):
          li = EstimateLineItem.objects.create(
              estimate=self.estimate, line_number=1, description='x',
              qty=Decimal('1'), price=Decimal('1'), accounting_category=self.cat,
          )
          li.refresh_from_db()
          self.assertFalse(li.is_material)

      def test_persists_true(self):
          li = EstimateLineItem.objects.create(
              estimate=self.estimate, line_number=1, description='ply',
              qty=Decimal('1'), price=Decimal('1'), accounting_category=self.cat,
              is_material=True,
          )
          li.refresh_from_db()
          self.assertTrue(li.is_material)
  ```

- [ ] **Run it, confirm the intended failure** (field does not exist → `TypeError`/`FieldError`):

  ```bash
  python manage.py test tests.test_estimate_is_material_field
  ```
  Read the summary line — expect `FAILED (errors=…)` mentioning `is_material`.

- [ ] **Implement.** In `apps/estimates/models.py`, add to `EstimateLineItem` (after the
  `adjustment_target_categories` field, before `class Meta`):

  ```python
      is_material = models.BooleanField(
          default=False,
          help_text=(
              'Marks a bare (no inventory_item, non-adjustment) freeform line as a '
              'material: at acceptance it crystallizes into a provisional Material '
              '(sell price only, no lot) instead of a Fee.'
          ),
      )
  ```

- [ ] **Generate the migration (do NOT migrate):**

  ```bash
  python manage.py makemigrations estimates
  ```
  Confirm a new `003X_estimatelineitem_is_material.py` with a single `AddField`
  (`field=models.BooleanField(default=False, help_text=...)`).

- [ ] **Run the test, confirm green:**

  ```bash
  python manage.py test tests.test_estimate_is_material_field
  ```
  Read `OK` and `Ran 2 tests`.

- [ ] **Commit:** `feat(estimates): add EstimateLineItem.is_material marker field`

---

## Task 2 — Expose `is_material` on the serializer

`EstimateLineItemSerializer` must round-trip the field so the SPA can read and write it.
Because the line-item POST/PATCH flow through `LineItemMixin` calls the **service** with
`**request.data` (not the serializer for writes), the serializer change is about **read**
exposure + keeping the field in the declared `fields` list; the write plumbing is Task 3.

**Files**
- `apps/api/estimates/serializers.py` (edit `EstimateLineItemSerializer.Meta.fields`)
- `tests/test_estimate_is_material_serializer.py` (new)

**Interfaces**
- Produces: `is_material` in serialized `EstimateLineItem` output.
- Consumes: `EstimateLineItem.is_material` (Task 1).

**Steps**

- [ ] **Write the failing test.** `tests/test_estimate_is_material_serializer.py`:

  ```python
  from decimal import Decimal
  from django.test import TestCase

  from apps.api.estimates.serializers import EstimateLineItemSerializer
  from apps.contacts.models import Contact
  from apps.core.models import AccountingCategory
  from apps.estimates.models import Estimate, EstimateLineItem
  from apps.jobs.models import Job


  class EstimateLineItemSerializerIsMaterialTest(TestCase):
      def setUp(self):
          self.cat = AccountingCategory.objects.create(name='Mat', is_active=True, code='MAT')
          self.contact = Contact.objects.create(
              first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
          )
          self.job = Job.objects.create(
              contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
          )
          self.estimate = Estimate.objects.create(
              job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_DRAFT,
          )

      def test_is_material_serialized(self):
          li = EstimateLineItem.objects.create(
              estimate=self.estimate, line_number=1, description='ply',
              qty=Decimal('1'), price=Decimal('1'), accounting_category=self.cat,
              is_material=True,
          )
          data = EstimateLineItemSerializer(li).data
          self.assertIn('is_material', data)
          self.assertIs(data['is_material'], True)
  ```

- [ ] **Run it, confirm the intended failure** (`is_material` not in `data` → `assertIn` fails):

  ```bash
  python manage.py test tests.test_estimate_is_material_serializer
  ```

- [ ] **Implement.** In `apps/api/estimates/serializers.py`, add `'is_material'` to
  `EstimateLineItemSerializer.Meta.fields` (next to `'inventory_item'`):

  ```python
          fields = [
              'line_item_id', 'line_number', 'inventory_item', 'is_material',
              'qty', 'units', 'description', 'price',
              'accounting_category', 'taxable_override', 'tax_rate_override',
              'adjustment_service', 'adjustment_target_categories',
              'adjustment_service_detail',
              'sources',
          ]
  ```

- [ ] **Run, confirm green:**

  ```bash
  python manage.py test tests.test_estimate_is_material_serializer
  ```

- [ ] **Commit:** `feat(api/estimates): expose is_material on EstimateLineItemSerializer`

---

## Task 3 — Persist + validate `is_material` in the line-authoring services

`EstimateService.add_line_item` and `update_line_item` already accept arbitrary field
kwargs and route them through `LineItemService.normalize_fk_kwargs` → the model. Because
`is_material` is a plain boolean (not an FK), it **already flows through** to the instance.
The real work is the **conflict guard**: reject `is_material=True` on a line that carries
an `inventory_item` or an `adjustment_service` (those lines are already material/adjustment;
the marker is only meaningful on a bare line).

**Files**
- `apps/estimates/services.py` (edit `add_line_item`, `update_line_item`)
- `tests/test_estimate_is_material_service.py` (new)

**Interfaces**
- Consumes: `EstimateService.add_line_item(estimate_pk, **kwargs)`,
  `EstimateService.update_line_item(line_item_id, **kwargs)` with an `is_material` kwarg.
- Produces: persisted `is_material`; `ValidationError` on `is_material=True` +
  `inventory_item`/`adjustment_service`.

**Steps**

- [ ] **Write the failing tests.** `tests/test_estimate_is_material_service.py`:

  ```python
  from decimal import Decimal
  from django.core.exceptions import ValidationError
  from django.test import TestCase

  from apps.contacts.models import Contact
  from apps.core.models import AccountingCategory
  from apps.estimates.models import Estimate, EstimateLineItem
  from apps.estimates.services import EstimateService
  from apps.inventory.models import InventoryItem
  from apps.jobs.models import Job, RateScheme


  class EstimateServiceIsMaterialTest(TestCase):
      def setUp(self):
          self.cat = AccountingCategory.objects.create(name='Mat', is_active=True, code='MAT')
          self.contact = Contact.objects.create(
              first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
          )
          self.job = Job.objects.create(
              contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
          )
          self.estimate = Estimate.objects.create(
              job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_DRAFT,
          )

      def test_add_bare_line_persists_is_material(self):
          li = EstimateService.add_line_item(
              self.estimate.pk, description='ABS sheet', qty=Decimal('1'),
              price=Decimal('400'), units='ea', accounting_category=self.cat.pk,
              is_material=True,
          )
          li.refresh_from_db()
          self.assertTrue(li.is_material)

      def test_add_defaults_is_material_false(self):
          li = EstimateService.add_line_item(
              self.estimate.pk, description='Rush', qty=Decimal('1'),
              price=Decimal('25'), accounting_category=self.cat.pk,
          )
          li.refresh_from_db()
          self.assertFalse(li.is_material)

      def test_add_rejects_is_material_with_inventory_item(self):
          pli = InventoryItem.objects.create(
              code='PLY', accounting_category=self.cat, is_catalog=True,
          )
          with self.assertRaises(ValidationError):
              EstimateService.add_line_item(
                  self.estimate.pk, description='ply', qty=Decimal('1'),
                  price=Decimal('1'), accounting_category=self.cat.pk,
                  inventory_item=pli.pk, is_material=True,
              )

      def test_add_rejects_is_material_with_adjustment_service(self):
          adj = RateScheme.objects.create(
              name='Rush 10%', algorithm=RateScheme.PERCENTAGE,
              rate=Decimal('10'), unit_label='%', accounting_category=self.cat,
          )
          with self.assertRaises(ValidationError):
              EstimateService.add_line_item(
                  self.estimate.pk, description='rush', qty=Decimal('1'),
                  price=Decimal('0'), accounting_category=self.cat.pk,
                  adjustment_service=adj.pk, is_material=True,
              )

      def test_update_toggles_is_material(self):
          li = EstimateService.add_line_item(
              self.estimate.pk, description='ABS', qty=Decimal('1'),
              price=Decimal('400'), accounting_category=self.cat.pk,
          )
          EstimateService.update_line_item(li.pk, is_material=True)
          li.refresh_from_db()
          self.assertTrue(li.is_material)

      def test_update_rejects_is_material_on_inventory_line(self):
          pli = InventoryItem.objects.create(
              code='PLY', accounting_category=self.cat, is_catalog=True,
          )
          li = EstimateService.add_line_item_from_pli(self.estimate.pk, pli.pk, Decimal('2'))
          with self.assertRaises(ValidationError):
              EstimateService.update_line_item(li.pk, is_material=True)
  ```

- [ ] **Run, confirm the intended failures** (the two "rejects" tests fail because no guard
  exists yet — the line saves instead of raising):

  ```bash
  python manage.py test tests.test_estimate_is_material_service
  ```
  Expect `FAILED` with the two `assertRaises` cases (persist/toggle tests may already pass
  since kwargs flow through — that is fine; the guard tests are the red ones).

- [ ] **Implement the guard.** Add a small helper and call it from both methods in
  `apps/estimates/services.py`. Place the helper as a `@staticmethod` on `EstimateService`
  (near `assert_all_hand_lines_have_ac`):

  ```python
      @staticmethod
      def _assert_is_material_only_on_bare_line(li):
          """`is_material` is meaningful only on a bare line. A line with an
          inventory_item is already a (catalog) material; an adjustment line is
          document-only — the marker must not conflict with either."""
          if not li.is_material:
              return
          if li.inventory_item_id is not None:
              raise ValidationError({'is_material': (
                  'A line with an inventory item is already a material; '
                  'the "is material" marker only applies to a bare line.'
              )})
          if li.adjustment_service_id is not None:
              raise ValidationError({'is_material': (
                  'An adjustment line cannot be marked as a material.'
              )})
  ```

  In `add_line_item`, after the AC check and before `li.full_clean()`:

  ```python
          EstimateService._assert_is_material_only_on_bare_line(li)
          li.full_clean()
  ```

  In `update_line_item`, after the AC check and before `li.full_clean()`:

  ```python
          EstimateService._assert_is_material_only_on_bare_line(li)
          li.full_clean()
  ```

  (`ValidationError` is already imported in `services.py`.)

- [ ] **Run, confirm green:**

  ```bash
  python manage.py test tests.test_estimate_is_material_service
  ```
  Read `OK` and `Ran 6 tests`.

- [ ] **Commit:** `feat(estimates): persist + guard is_material on line authoring`

---

## Task 4 — Crystallize a marked bare line into a provisional Material at acceptance

Add the `is_material` branch to `EstimateAcceptanceService.on_accept`, between the existing
`inventory_item → Material` block and the `Fee` block. A bare line with `is_material=True`
becomes a **provisional Material** (`inventory_item=None`, `sell_price=li.price`, cost
unset), source-linked `SOURCE_MATERIAL`. Unchecked lines still become Fees (unchanged).

**Files**
- `apps/estimates/acceptance.py` (edit `on_accept`)
- `tests/test_acceptance_provisional_material.py` (new)

**Interfaces**
- Consumes: `EstimateLineItem.is_material`; `MaterialService.create_on_job(...)`;
  `EstimateLineItemSource.SOURCE_MATERIAL`.
- Produces: a provisional `Material` (`inventory_item is None`, `unit_cost == 0`,
  `sell_price == li.price`) + its `SOURCE_MATERIAL` link; `materials_created` incremented.

**Steps**

- [ ] **Write the failing tests.** `tests/test_acceptance_provisional_material.py`:

  ```python
  from decimal import Decimal
  from django.test import TestCase

  from apps.contacts.models import Contact
  from apps.core.models import AccountingCategory, AppState, Configuration
  from apps.estimates.acceptance import EstimateAcceptanceService
  from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource
  from apps.inventory.models import Material
  from apps.jobs.models import Fee, Job


  class AcceptanceProvisionalMaterialTest(TestCase):
      """A bare line marked is_material=True crystallizes into a provisional
      Material (no inventory_item, sell price only, cost unset) — not a Fee.
      An unmarked bare line still becomes a Fee (unchanged)."""

      def setUp(self):
          Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
          Configuration.objects.create(key='estimate_counter', value='0')
          Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
          AppState.objects.create(key='job_counter', value='0')

          self.cat = AccountingCategory.objects.create(name='Mat', is_active=True, code='MAT')
          self.contact = Contact.objects.create(
              first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
          )
          self.job = Job.objects.create(
              contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001',
          )
          self.estimate = Estimate.objects.create(
              job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_OPEN,
          )

      def _add_line(self, **kw):
          defaults = dict(
              estimate=self.estimate, qty=Decimal('1'), units='ea',
              accounting_category=self.cat,
          )
          defaults.update(kw)
          return EstimateLineItem.objects.create(**defaults)

      def test_marked_bare_line_becomes_provisional_material(self):
          line = self._add_line(
              line_number=1, description='M77 ABS', qty=Decimal('2'),
              price=Decimal('400.00'), is_material=True,
          )

          result = EstimateAcceptanceService.on_accept(self.estimate)

          mat = Material.objects.get(job=self.job, description='M77 ABS')
          self.assertIsNone(mat.inventory_item)                 # provisional — no lot
          self.assertEqual(mat.quantity, Decimal('2'))
          self.assertEqual(mat.sell_price, Decimal('400.00'))    # quoted sell, locked
          self.assertEqual(mat.unit_cost, Decimal('0.00'))       # cost unset (out of scope: reverse-markup)
          self.assertEqual(mat.accounting_category, self.cat)
          self.assertEqual(result['materials_created'], 1)

          # It did NOT become a Fee.
          self.assertFalse(Fee.objects.filter(job=self.job, description='M77 ABS').exists())

          # Source-linked as a Material.
          src = EstimateLineItemSource.objects.get(estimate_line_item=line)
          self.assertEqual(src.source_type, EstimateLineItemSource.SOURCE_MATERIAL)
          self.assertEqual(src.source_pk, mat.pk)

      def test_unmarked_bare_line_still_becomes_a_fee(self):
          self._add_line(
              line_number=1, description='Rush handling', qty=Decimal('3'),
              price=Decimal('25.00'), is_material=False,
          )

          result = EstimateAcceptanceService.on_accept(self.estimate)

          self.assertEqual(result['fees_created'], 1)
          self.assertEqual(result['materials_created'], 0)
          self.assertTrue(Fee.objects.filter(job=self.job, description='Rush handling').exists())
          self.assertFalse(Material.objects.filter(job=self.job, description='Rush handling').exists())
  ```

- [ ] **Run, confirm the intended failure** (marked line becomes a Fee today →
  `Material.DoesNotExist` in the first test):

  ```bash
  python manage.py test tests.test_acceptance_provisional_material
  ```

- [ ] **Implement.** In `apps/estimates/acceptance.py` `on_accept`, insert the branch
  **after** the `if li.inventory_item_id is not None:` block's `continue` and **before**
  the `# Defensive guard: Fee.accounting_category …` block:

  ```python
              # Bare line marked as a material → provisional Material atom.
              # (No inventory_item, so no lot: it carries only a sell price; cost
              # stays unset. Reverse-markup provisional cost, transient-lot minting,
              # establishment, and the Order affordance are OUT of scope here — see
              # docs/plans/2026-06-30-freeform-material-procurement-inventory.md.)
              # NOTE (pinned discriminator): Plan 2 adds a `service_item → Task`
              # branch ABOVE the inventory_item block; this is_material branch stays
              # here, between inventory_item and Fee.
              if li.is_material:
                  material = MaterialService.create_on_job(
                      job=job,
                      task=None,
                      description=li.description or '',
                      quantity=li.qty or Decimal('1'),
                      sell_price=li.price or Decimal('0'),
                      inventory_item=None,
                      accounting_category=li.accounting_category,
                      units=li.units or 'none',
                  )
                  EstimateLineItemSource.objects.create(
                      estimate_line_item=li,
                      source_type=EstimateLineItemSource.SOURCE_MATERIAL,
                      source_pk=material.pk,
                  )
                  materials_created += 1
                  continue
  ```

  Also update the module docstring's parenthetical note (currently says hand-typed
  material lines "still become Fees … See docs/designs/LATER.md") to reflect that a bare
  line **marked `is_material`** now crystallizes into a provisional Material.

- [ ] **Run, confirm green:**

  ```bash
  python manage.py test tests.test_acceptance_provisional_material
  ```
  Read `OK` and `Ran 2 tests`.

- [ ] **Run the existing acceptance suite to confirm no regression** (unmarked bare lines,
  inventory lines, adjustments, earmarks unchanged):

  ```bash
  python manage.py test tests.test_acceptance_fees
  ```
  Read `OK`.

- [ ] **Remove the LATER item.** Delete the *"Hand-typed estimate material lines can't
  crystallize into Materials"* entry from `docs/designs/LATER.md` (grep for it first;
  it may be phrased slightly differently). If the whole feature isn't complete until the
  frontend lands, defer this deletion to Task 5's commit — but do it in this batch.

- [ ] **Commit:** `feat(estimates): crystallize is_material bare lines into provisional Materials`

---

## Task 5 — "Is this a material?" checkbox on the freeform line form

Add a checkbox to `LineItemModal.svelte`'s **manual** (non-PLI) branch and include
`is_material` in the create/edit payload. The checkbox is only shown on the manual form
(the "From Inventory" branch already produces an inventory-backed material).

> **Scope note:** `LineItemModal` is shared by the estimate **and invoice** line-item
> surfaces. The marker is only meaningful for estimates (invoices bill actuals and never
> crystallize). Gate the checkbox on a prop so it renders only where relevant — add a
> `showMaterialMarker = false` prop and have the estimate caller pass `true`. Grep the
> callers (`grep -rn "LineItemModal" frontend/src`) and set the prop on the estimate
> line-item page only. Do not send `is_material` from the invoice surface.

**Files**
- `frontend/src/components/LineItemModal.svelte` (edit)
- the estimate line-item caller component (pass `showMaterialMarker={true}`) — found via grep
- `frontend/tests/LineItemModal.test.js` (new)

**Interfaces**
- Consumes: `is_material` on the API line-item POST/PATCH (Task 3).
- Produces: a checkbox bound to local `isMaterial` state, sent as `is_material` in the
  manual payload when `showMaterialMarker` is true.

**Steps**

- [ ] **Write the failing test.** `frontend/tests/LineItemModal.test.js`:

  ```js
  import { render, fireEvent } from '@testing-library/svelte';
  import { describe, it, expect, vi, beforeEach } from 'vitest';
  import LineItemModal from '../src/components/LineItemModal.svelte';

  // Stub the API so save() does not hit the network.
  vi.mock('../src/lib/api.js', () => ({
    api: { post: vi.fn().mockResolvedValue({}), patch: vi.fn().mockResolvedValue({}) },
  }));
  import { api } from '../src/lib/api.js';

  const categories = [{ id: 7, name: 'Materials', code: 'MAT' }];

  describe('LineItemModal — is-material marker', () => {
    beforeEach(() => { api.post.mockClear(); });

    it('shows the checkbox when showMaterialMarker and posts is_material=true', async () => {
      const { getByLabelText, getByText } = render(LineItemModal, {
        props: {
          open: true, mode: 'create', apiBase: '/api/estimates/1',
          categories, showMaterialMarker: true,
        },
      });

      await fireEvent.input(getByLabelText(/Description/i), { target: { value: 'M77 ABS' } });
      await fireEvent.change(getByLabelText(/Accounting Category/i), { target: { value: '7' } });
      await fireEvent.click(getByLabelText(/Is this a material/i));
      await fireEvent.click(getByText('Save'));

      expect(api.post).toHaveBeenCalledTimes(1);
      const [, payload] = api.post.mock.calls[0];
      expect(payload.is_material).toBe(true);
    });

    it('hides the checkbox when showMaterialMarker is false', () => {
      const { queryByLabelText } = render(LineItemModal, {
        props: {
          open: true, mode: 'create', apiBase: '/api/invoices/1',
          categories, showMaterialMarker: false,
        },
      });
      expect(queryByLabelText(/Is this a material/i)).toBeNull();
    });
  });
  ```

- [ ] **Run, confirm the intended failure:**

  ```bash
  cd frontend && npm run test:run -- LineItemModal
  ```
  Expect the first test to fail (no checkbox / `is_material` absent from payload).

- [ ] **Implement.** In `LineItemModal.svelte`:

  1. Add the prop and state:
     ```js
     let {
       open = false,
       mode = 'create',
       apiBase = '',
       item = null,
       categories = [],
       showMaterialMarker = false,   // estimate surface only
       onSaved = () => {},
       onClose = () => {},
     } = $props();

     let isMaterial = $state(false);
     ```
  2. Reset/prefill it in the `$effect(...)` that runs on open — mirror the other fields:
     ```js
     // in the mode === 'edit' branch:
     isMaterial = item.is_material ?? false;
     // in the create/else branch:
     isMaterial = false;
     ```
  3. In `save()`, add `is_material` to the **manual** payload (the `else` branch), gated
     on the prop so the invoice surface never sends it:
     ```js
     const payload = {
       description,
       qty: qty || '0',
       units,
       price: price || '0',
       accounting_category: accountingCategory ? Number(accountingCategory) : null,
     };
     if (showMaterialMarker) {
       payload.is_material = isMaterial;
     }
     ```
  4. Render the checkbox inside the manual branch (after the Accounting Category `<p>`),
     gated on the prop:
     ```svelte
     {#if showMaterialMarker}
       <p>
         <label>
           <input type="checkbox" bind:checked={isMaterial}>
           Is this a material?
         </label>
       </p>
     {/if}
     ```

- [ ] **Wire the estimate caller.** `grep -rn "LineItemModal" frontend/src`, and on the
  **estimate** line-item page/component add `showMaterialMarker={true}` to its
  `<LineItemModal … />`. Leave the invoice caller unchanged (defaults to `false`).

- [ ] **Run, confirm green:**

  ```bash
  cd frontend && npm run test:run -- LineItemModal
  ```

- [ ] **If not already done in Task 4**, remove the retired LATER item from
  `docs/designs/LATER.md`.

- [ ] **Commit:** `feat(estimates/ui): "is this a material?" marker on the freeform line form`

---

## Done when

- `EstimateLineItem.is_material` exists (migration generated, **not** applied) and is
  serialized.
- The two line-authoring services persist it and reject the `inventory_item` /
  `adjustment_service` conflict.
- `on_accept` crystallizes a marked bare line into a **provisional Material**
  (`inventory_item=None`, sell price only, cost unset), source-linked `SOURCE_MATERIAL`;
  unmarked bare lines still become Fees; the inventory branch is untouched.
- The estimate freeform line form shows the checkbox and sends `is_material`; the invoice
  surface does not.
- The retired LATER item is removed.
- All new + existing acceptance tests are green; the shared discriminator branch is
  positioned so Plan 2's `service_item → Task` branch can slot in above `inventory_item`.

## Assumptions / decisions to flag for RM

- **`LineItemModal` is shared with invoices**, so the plan gates the checkbox behind a
  `showMaterialMarker` prop (estimate-only) rather than always showing it. Confirm this is
  the desired surfacing (vs. a separate estimate-only modal).
- The provisional Material is created via `MaterialService.create_on_job(inventory_item=None,
  cost_source='document')` (the existing freeform default). On the just-approved job this is
  earmark-safe because `_mutate_earmark` no-ops when `inventory_item is None`.
- No AC guard is added to the `is_material` branch (parallel to the existing `inventory_item`
  branch, which also relies on the send-gate `assert_all_hand_lines_have_ac`).

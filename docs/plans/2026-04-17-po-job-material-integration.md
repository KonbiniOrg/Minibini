# PO–Job–Material Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Link PO line items to Jobs through `Material.po_line_item`, so that creating a job-linked PO line creates or claims a Material on the Job, receipts move physical stock (QOH) without touching Materials, and lifecycle edges (cancel, reverse, reassign) stay coherent.

**Architecture:** `Material.po_line_item` becomes the sole source of truth for PO line → job attribution. `PurchaseOrderLineItem.job` is dropped. Materials are created at line-add time (not at receipt). `Material.quantity` is planned consumption and is never changed by a receipt. A new resolver (`MaterialService.resolve_or_create_for_line`) handles explicit link / claim-existing / create-new. Severance prompts the user "still needed on old job?" on cancel/reassign/unlink.

**Tech Stack:** Django 5.2, DRF, MySQL, Python 3.12, Svelte 5 (Vite).

**Design:** `docs/designs/2026-04-17-po-job-material-integration.md` is the authoritative spec. Read sections on linkage resolver, severance, and edge cases before diving in.

**Conventions:**
- TDD for every behavior change — write the failing test first, see it fail for the right reason, then implement.
- Never run `python manage.py migrate`. Only create migrations with `makemigrations`. The user applies them manually.
- Never run tests from parallel subagents (shared MySQL test DB deadlocks).
- All API DELETE responses return 200 with JSON (never 204); frontend `api.js` assumes JSON.
- Custom `db_table` names are set in models; check `Meta.db_table` before assuming Django defaults.
- Use service layer for all business logic (viewsets are thin wrappers).
- Prefer small atomic commits. One task = one commit.

---

## Task 1: Add `Material.po_line_item` FK (model + migration)

**Files:**
- Modify: `apps/inventory/models.py:193-210` (Material class)
- Create: `apps/inventory/migrations/XXXX_material_po_line_item.py` (generated)

- [ ] **Step 1: Write the failing test**

Create `tests/test_material_po_line_item_fk.py`:

```python
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Material, PriceListItem
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.core.models import AccountingCategory, Configuration


class MaterialPOLineItemFKTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.contact = Contact.objects.create(first_name='V', last_name='Vendor', work_number='555')
        self.business = Business.objects.create(business_name='Vendor Inc', default_contact=self.contact)
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(job_number='J-1', contact=self.contact, description='j')
        self.category = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='BOLT', description='bolt', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.category,
        )

    def test_material_has_nullable_po_line_item_fk(self):
        mat = Material.objects.create(job=self.job, quantity=Decimal('5.00'))
        self.assertIsNone(mat.po_line_item)

    def test_material_can_link_to_po_line(self):
        po = PurchaseOrder.objects.create(business=self.business)
        line = PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='x', qty=Decimal('5.00'), price=Decimal('1.00'),
        )
        mat = Material.objects.create(
            job=self.job, quantity=Decimal('5.00'), po_line_item=line,
        )
        mat.refresh_from_db()
        self.assertEqual(mat.po_line_item_id, line.pk)

    def test_po_line_item_linked_material_property_returns_material(self):
        po = PurchaseOrder.objects.create(business=self.business)
        line = PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='x', qty=Decimal('5.00'), price=Decimal('1.00'),
        )
        mat = Material.objects.create(
            job=self.job, quantity=Decimal('5.00'), po_line_item=line,
        )
        self.assertEqual(line.linked_material, mat)

    def test_po_line_item_linked_material_property_returns_none_when_absent(self):
        po = PurchaseOrder.objects.create(business=self.business)
        line = PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='x', qty=Decimal('5.00'), price=Decimal('1.00'),
        )
        self.assertIsNone(line.linked_material)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_material_po_line_item_fk -v 2`
Expected: FAIL — `Material` has no attribute `po_line_item` (and/or `PurchaseOrderLineItem` has no `linked_material`).

- [ ] **Step 3: Add the FK and helper property**

In `apps/inventory/models.py`, add to the `Material` class (near the other FKs, before `class Meta`):

```python
    po_line_item = models.ForeignKey(
        'purchasing.PurchaseOrderLineItem',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
    )
```

In `apps/purchasing/models.py`, add to the `PurchaseOrderLineItem` class (after the existing fields, before `class Meta`):

```python
    @property
    def linked_material(self):
        from apps.inventory.models import Material
        return Material.objects.filter(po_line_item=self).first()
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations inventory`
Expected: one new migration file under `apps/inventory/migrations/` adding the `po_line_item` field. Inspect it to confirm it's a nullable `AddField`.

- [ ] **Step 5: Apply migration and run test**

Ask the user to apply the migration (do NOT run `migrate` yourself). After they confirm, run:
`python manage.py test tests.test_material_po_line_item_fk -v 2`
Expected: 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/inventory/models.py apps/inventory/migrations/ apps/purchasing/models.py tests/test_material_po_line_item_fk.py
git commit -m "feat(materials): add Material.po_line_item FK and linked_material helper"
```

---

## Task 2: Add `MaterialService.link_to_po_line` and `unlink_from_po_line`

**Files:**
- Modify: `apps/inventory/services.py:289+` (MaterialService class)
- Test: `tests/test_material_link_to_po_line.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_material_link_to_po_line.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Material, PriceListItem
from apps.inventory.services import MaterialService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.core.models import AccountingCategory, Configuration


class MaterialLinkToPOLineTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=cat,
        )
        po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='x', qty=Decimal('5.00'), price=Decimal('1.00'),
        )

    def _make_material(self, **kwargs):
        defaults = dict(job=self.job, quantity=Decimal('5.00'))
        defaults.update(kwargs)
        return Material.objects.create(**defaults)

    def test_link_to_po_line_sets_fk(self):
        m = self._make_material()
        MaterialService.link_to_po_line(m, self.line)
        m.refresh_from_db()
        self.assertEqual(m.po_line_item_id, self.line.pk)

    def test_link_refuses_consumed_material(self):
        m = self._make_material(consumption_state=Material.CONSUMPTION_STATE_CONSUMED)
        with self.assertRaises(ValidationError):
            MaterialService.link_to_po_line(m, self.line)

    def test_link_refuses_already_linked_material(self):
        other_line = PurchaseOrderLineItem.objects.create(
            purchase_order=self.line.purchase_order,
            description='y', qty=Decimal('1.00'), price=Decimal('1.00'),
        )
        m = self._make_material(po_line_item=other_line)
        with self.assertRaises(ValidationError):
            MaterialService.link_to_po_line(m, self.line)

    def test_unlink_clears_fk(self):
        m = self._make_material(po_line_item=self.line)
        MaterialService.unlink_from_po_line(m)
        m.refresh_from_db()
        self.assertIsNone(m.po_line_item_id)

    def test_unlink_refuses_consumed_material(self):
        m = self._make_material(po_line_item=self.line, consumption_state=Material.CONSUMPTION_STATE_CONSUMED)
        with self.assertRaises(ValidationError):
            MaterialService.unlink_from_po_line(m)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_material_link_to_po_line -v 2`
Expected: FAIL — `MaterialService` has no `link_to_po_line` / `unlink_from_po_line`.

- [ ] **Step 3: Implement the methods**

In `apps/inventory/services.py`, inside `class MaterialService` (after `assign_task`):

```python
    @staticmethod
    def link_to_po_line(material, po_line):
        """Set material.po_line_item = po_line. Validates pending + unlinked invariants."""
        from django.core.exceptions import ValidationError
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('Cannot link; Material is not pending.')
        if material.po_line_item_id is not None and material.po_line_item_id != po_line.pk:
            raise ValidationError('Material is already linked to a different PO line.')
        material.po_line_item = po_line
        material.save(update_fields=['po_line_item'])

    @staticmethod
    def unlink_from_po_line(material):
        """Clear material.po_line_item. Validates pending state."""
        from django.core.exceptions import ValidationError
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('Cannot unlink; Material is not pending.')
        material.po_line_item = None
        material.save(update_fields=['po_line_item'])
```

- [ ] **Step 4: Run and verify pass**

Run: `python manage.py test tests.test_material_link_to_po_line -v 2`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/services.py tests/test_material_link_to_po_line.py
git commit -m "feat(materials): add link_to_po_line and unlink_from_po_line services"
```

---

## Task 3: Add `MaterialService.sever`

**Files:**
- Modify: `apps/inventory/services.py` (MaterialService)
- Test: `tests/test_material_sever.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_material_sever.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Earmark, Material, PriceListItem
from apps.inventory.services import MaterialService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.core.models import AccountingCategory, Configuration


class MaterialSeverTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=cat, is_inventoried=True,
        )
        po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='x', qty=Decimal('5.00'), price=Decimal('1.00'),
        )
        # Material created via MaterialService.create_on_job so earmark is set
        self.material = MaterialService.create_on_job(
            job=self.job, price_list_item=self.pli, quantity=Decimal('5.00'),
        )
        self.material.po_line_item = self.line
        self.material.save(update_fields=['po_line_item'])

    def test_sever_keep_clears_fk_and_preserves_material(self):
        MaterialService.sever(self.material, 'keep')
        self.material.refresh_from_db()
        self.assertIsNone(self.material.po_line_item_id)
        self.assertEqual(self.material.quantity, Decimal('5.00'))
        # Earmark preserved
        earmark = Earmark.objects.filter(price_list_item=self.pli, job=self.job).first()
        self.assertIsNotNone(earmark)
        self.assertEqual(earmark.quantity, Decimal('5.00'))

    def test_sever_delete_removes_material_and_backs_out_earmark(self):
        material_id = self.material.pk
        MaterialService.sever(self.material, 'delete')
        self.assertFalse(Material.objects.filter(pk=material_id).exists())
        self.assertFalse(Earmark.objects.filter(price_list_item=self.pli, job=self.job).exists())

    def test_sever_raises_on_consumed_material(self):
        self.material.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        self.material.save(update_fields=['consumption_state'])
        with self.assertRaises(ValidationError):
            MaterialService.sever(self.material, 'keep')

    def test_sever_raises_on_unknown_decision(self):
        with self.assertRaises(ValidationError):
            MaterialService.sever(self.material, 'something-else')
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_material_sever -v 2`
Expected: FAIL — `MaterialService` has no `sever`.

- [ ] **Step 3: Implement `sever`**

In `apps/inventory/services.py`, inside `class MaterialService`:

```python
    @staticmethod
    def sever(material, decision):
        """'keep' clears FK. 'delete' deletes the Material and backs out earmark.
        Raises if Material is consumed or decision is invalid."""
        from django.core.exceptions import ValidationError
        from django.db import transaction
        if material.consumption_state != Material.CONSUMPTION_STATE_PENDING:
            raise ValidationError('Cannot sever; Material is not pending.')
        if decision == 'keep':
            material.po_line_item = None
            material.save(update_fields=['po_line_item'])
            return
        if decision == 'delete':
            with transaction.atomic():
                InventoryService._mutate_earmark(
                    material.price_list_item, material.job, -material.quantity,
                )
                material.delete()
            return
        raise ValidationError(f'Unknown sever decision: {decision!r}')
```

- [ ] **Step 4: Run and verify pass**

Run: `python manage.py test tests.test_material_sever -v 2`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/services.py tests/test_material_sever.py
git commit -m "feat(materials): add MaterialService.sever"
```

---

## Task 4: Add `MaterialService.resolve_or_create_for_line`

**Files:**
- Modify: `apps/inventory/services.py` (MaterialService)
- Test: `tests/test_material_resolve_or_create.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_material_resolve_or_create.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Material, PriceListItem
from apps.inventory.services import MaterialService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.core.models import AccountingCategory, Configuration


class MaterialResolveOrCreateTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        self.cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.cat, is_inventoried=True,
        )
        self.po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='x', qty=Decimal('5.00'), price=Decimal('1.00'),
            price_list_item=self.pli,
        )

    def _args(self, **over):
        defaults = dict(
            job=self.job, price_list_item=self.pli, qty=Decimal('5.00'),
            unit_cost=Decimal('1.00'), description='x', accounting_category=self.cat,
        )
        defaults.update(over)
        return defaults

    def test_explicit_link_via_material_id(self):
        existing = MaterialService.create_on_job(
            job=self.job, price_list_item=self.pli, quantity=Decimal('3.00'),
        )
        result = MaterialService.resolve_or_create_for_line(
            self.line, material_id=existing.pk, **self._args(qty=Decimal('10.00')),
        )
        self.assertEqual(result.pk, existing.pk)
        result.refresh_from_db()
        self.assertEqual(result.po_line_item_id, self.line.pk)
        # Plan unchanged by resolver
        self.assertEqual(result.quantity, Decimal('3.00'))

    def test_explicit_link_raises_if_material_already_linked(self):
        other_line = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='y', qty=Decimal('1.00'), price=Decimal('1.00'),
        )
        existing = MaterialService.create_on_job(
            job=self.job, price_list_item=self.pli, quantity=Decimal('3.00'),
        )
        existing.po_line_item = other_line
        existing.save(update_fields=['po_line_item'])
        with self.assertRaises(ValidationError):
            MaterialService.resolve_or_create_for_line(
                self.line, material_id=existing.pk, **self._args(),
            )

    def test_claim_exactly_one_unlinked_pending_material(self):
        existing = MaterialService.create_on_job(
            job=self.job, price_list_item=self.pli, quantity=Decimal('3.00'),
        )
        result = MaterialService.resolve_or_create_for_line(self.line, **self._args())
        self.assertEqual(result.pk, existing.pk)
        result.refresh_from_db()
        self.assertEqual(result.po_line_item_id, self.line.pk)
        self.assertEqual(result.quantity, Decimal('3.00'))  # plan unchanged

    def test_no_claim_when_multiple_matches_creates_new(self):
        m1 = MaterialService.create_on_job(
            job=self.job, price_list_item=self.pli, quantity=Decimal('3.00'),
        )
        m2 = MaterialService.create_on_job(
            job=self.job, price_list_item=self.pli, quantity=Decimal('7.00'),
        )
        result = MaterialService.resolve_or_create_for_line(self.line, **self._args())
        self.assertNotIn(result.pk, (m1.pk, m2.pk))
        self.assertEqual(result.po_line_item_id, self.line.pk)
        self.assertEqual(result.quantity, Decimal('5.00'))

    def test_no_claim_when_match_is_consumed_creates_new(self):
        consumed = MaterialService.create_on_job(
            job=self.job, price_list_item=self.pli, quantity=Decimal('3.00'),
        )
        consumed.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        consumed.save(update_fields=['consumption_state'])
        result = MaterialService.resolve_or_create_for_line(self.line, **self._args())
        self.assertNotEqual(result.pk, consumed.pk)
        self.assertEqual(result.po_line_item_id, self.line.pk)

    def test_create_new_when_no_match(self):
        result = MaterialService.resolve_or_create_for_line(self.line, **self._args())
        self.assertEqual(result.quantity, Decimal('5.00'))
        self.assertEqual(result.po_line_item_id, self.line.pk)
        self.assertEqual(result.job_id, self.job.pk)
        self.assertEqual(result.price_list_item_id, self.pli.pk)
        self.assertEqual(result.unit_cost, Decimal('1.00'))

    def test_create_new_pli_less(self):
        result = MaterialService.resolve_or_create_for_line(
            self.line, **self._args(price_list_item=None),
        )
        self.assertIsNone(result.price_list_item_id)
        self.assertEqual(result.quantity, Decimal('5.00'))
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_material_resolve_or_create -v 2`
Expected: FAIL — `MaterialService` has no `resolve_or_create_for_line`.

- [ ] **Step 3: Implement resolver**

In `apps/inventory/services.py`, inside `class MaterialService`:

```python
    @staticmethod
    def resolve_or_create_for_line(po_line, *, job, price_list_item=None,
                                    qty, unit_cost, description,
                                    accounting_category=None, material_id=None):
        """Resolver precedence: explicit (material_id) -> claim exactly-one -> create new.
        Returns the linked Material. Raises ValidationError on explicit-link failures."""
        from django.core.exceptions import ValidationError
        from django.db import transaction

        with transaction.atomic():
            # Step 1: explicit link
            if material_id is not None:
                try:
                    mat = Material.objects.select_for_update().get(pk=material_id)
                except Material.DoesNotExist:
                    raise ValidationError(f'Material {material_id} not found')
                if mat.job_id != getattr(job, 'pk', job):
                    raise ValidationError('Material is not on the requested job')
                MaterialService.link_to_po_line(mat, po_line)
                return mat

            # Step 2: claim exactly-one unlinked pending match
            if price_list_item is not None:
                candidates = Material.objects.filter(
                    job=job,
                    price_list_item=price_list_item,
                    consumption_state=Material.CONSUMPTION_STATE_PENDING,
                    po_line_item__isnull=True,
                )
                matches = list(candidates[:2])
                if len(matches) == 1:
                    MaterialService.link_to_po_line(matches[0], po_line)
                    return matches[0]

            # Step 3: create new
            mat = MaterialService.create_on_job(
                job=job,
                price_list_item=price_list_item,
                description=description,
                quantity=qty,
                unit_cost=unit_cost,
                accounting_category=accounting_category,
            )
            MaterialService.link_to_po_line(mat, po_line)
            return mat
```

- [ ] **Step 4: Run and verify pass**

Run: `python manage.py test tests.test_material_resolve_or_create -v 2`
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/services.py tests/test_material_resolve_or_create.py
git commit -m "feat(materials): add resolve_or_create_for_line resolver"
```

---

## Task 5: Delete the orphaned `receive_po_line_item` helper and its tests

**Files:**
- Modify: `apps/inventory/services.py:38-50` (delete `receive_po_line_item`)
- Delete: `tests/test_receive_po_uses_mutate_earmark.py` (covered by new flow)

- [ ] **Step 1: Confirm the helper has no other callers**

Run: `grep -rn "receive_po_line_item" apps/ tests/`
Expected: matches only in `apps/inventory/services.py` (the definition) and `tests/test_receive_po_uses_mutate_earmark.py`.

If there are other callers, stop and flag. Do not proceed until this is confirmed.

- [ ] **Step 2: Delete the helper**

In `apps/inventory/services.py`, remove the `receive_po_line_item` static method (lines 37-50 area, the method that takes `po_line_item` and does `qty_on_hand += ... _mutate_earmark(...)`).

- [ ] **Step 3: Delete the obsolete test file**

```bash
git rm tests/test_receive_po_uses_mutate_earmark.py
```

- [ ] **Step 4: Run the full inventory test suite**

Run: `python manage.py test tests.test_inventory_qoh tests.test_inventory_qoh_services tests.test_material_sever tests.test_material_resolve_or_create -v 2`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/services.py
git commit -m "chore(inventory): remove orphaned receive_po_line_item helper"
```

---

## Task 6: Extend `PurchaseOrderService.add_line_item` to accept `job` and `material_id`

**Files:**
- Modify: `apps/purchasing/services.py:90-128` (add_line_item and add_line_item_from_pli)
- Test: `tests/test_po_add_line_item_with_job.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_po_add_line_item_with_job.py`:

```python
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Earmark, Material, PriceListItem
from apps.inventory.services import MaterialService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService
from apps.core.models import AccountingCategory, Configuration


class POAddLineItemWithJobTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        self.cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.cat, is_inventoried=True,
        )
        self.po = PurchaseOrder.objects.create(business=self.business)

    def test_add_line_item_with_job_creates_and_links_material(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk,
            description='x',
            qty=Decimal('5.00'),
            price=Decimal('1.00'),
            price_list_item=self.pli.pk,
            job=self.job.pk,
        )
        mat = line.linked_material
        self.assertIsNotNone(mat)
        self.assertEqual(mat.job_id, self.job.pk)
        self.assertEqual(mat.quantity, Decimal('5.00'))
        self.assertEqual(mat.price_list_item_id, self.pli.pk)
        earmark = Earmark.objects.filter(price_list_item=self.pli, job=self.job).first()
        self.assertEqual(earmark.quantity, Decimal('5.00'))

    def test_add_line_item_with_material_id_links_explicitly(self):
        existing = MaterialService.create_on_job(
            job=self.job, price_list_item=self.pli, quantity=Decimal('3.00'),
        )
        line = PurchaseOrderService.add_line_item(
            self.po.pk,
            description='x',
            qty=Decimal('5.00'),
            price=Decimal('1.00'),
            price_list_item=self.pli.pk,
            material_id=existing.pk,
        )
        self.assertEqual(line.linked_material.pk, existing.pk)

    def test_add_line_item_without_job_creates_no_material(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk,
            description='x',
            qty=Decimal('5.00'),
            price=Decimal('1.00'),
            price_list_item=self.pli.pk,
        )
        self.assertIsNone(line.linked_material)
        self.assertFalse(Material.objects.filter(po_line_item=line).exists())

    def test_add_line_item_pli_less_with_job_creates_pli_less_material(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk,
            description='Custom service',
            qty=Decimal('1.00'),
            price=Decimal('500.00'),
            accounting_category=self.cat.pk,
            job=self.job.pk,
        )
        mat = line.linked_material
        self.assertIsNotNone(mat)
        self.assertIsNone(mat.price_list_item_id)
        self.assertEqual(mat.description, 'Custom service')
        self.assertEqual(mat.quantity, Decimal('1.00'))
        self.assertEqual(mat.unit_cost, Decimal('500.00'))
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_po_add_line_item_with_job -v 2`
Expected: FAIL — `job` and `material_id` are unknown kwargs on PO line item.

- [ ] **Step 3: Modify `add_line_item`**

In `apps/purchasing/services.py`, replace `add_line_item` (currently around line 89-102) with:

```python
    @staticmethod
    def add_line_item(po_id, **kwargs):
        """Add a manual line item to a draft PO. Accepts optional transient job, material_id."""
        from apps.core.services import LineItemService
        from apps.inventory.services import MaterialService
        from django.db import transaction
        try:
            po = PurchaseOrder.objects.get(pk=po_id)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {po_id} not found')
        PurchaseOrderService._validate_draft(po)

        # Pop transient params before they hit the model constructor
        job_id = kwargs.pop('job', None)
        material_id = kwargs.pop('material_id', None)

        kwargs = LineItemService.normalize_fk_kwargs(PurchaseOrderLineItem, kwargs)
        with transaction.atomic():
            li = PurchaseOrderLineItem(purchase_order=po, **kwargs)
            li.full_clean()
            li.save()
            if job_id is not None or material_id is not None:
                from apps.jobs.models import Job
                job_obj = None
                if job_id is not None:
                    try:
                        job_obj = Job.objects.get(pk=job_id)
                    except Job.DoesNotExist:
                        from django.core.exceptions import ValidationError
                        raise ValidationError(f'Job {job_id} not found')
                MaterialService.resolve_or_create_for_line(
                    li,
                    job=job_obj,
                    price_list_item=li.price_list_item,
                    qty=li.qty,
                    unit_cost=li.price,
                    description=li.description,
                    accounting_category=li.accounting_category,
                    material_id=material_id,
                )
        return li
```

Also update `add_line_item_from_pli` (around line 104-128) to accept and honor `job` / `material_id`:

```python
    @staticmethod
    def add_line_item_from_pli(po_id, price_list_item_id, qty, job=None, material_id=None):
        """Add a line item from a PriceListItem to a draft PO. Accepts optional job, material_id."""
        from apps.inventory.models import PriceListItem
        from apps.inventory.services import MaterialService
        from django.db import transaction
        try:
            po = PurchaseOrder.objects.get(pk=po_id)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {po_id} not found')
        PurchaseOrderService._validate_draft(po)
        try:
            pli = PriceListItem.objects.get(pk=price_list_item_id)
        except PriceListItem.DoesNotExist:
            raise NotFoundError(f'PriceListItem {price_list_item_id} not found')
        with transaction.atomic():
            li = PurchaseOrderLineItem(
                purchase_order=po,
                price_list_item=pli,
                description=pli.description,
                qty=qty,
                units=pli.units,
                price=pli.purchase_price,
                accounting_category=pli.accounting_category,
            )
            li.full_clean()
            li.save()
            if job is not None or material_id is not None:
                from apps.jobs.models import Job
                job_obj = None
                if job is not None:
                    try:
                        job_obj = Job.objects.get(pk=job)
                    except Job.DoesNotExist:
                        from django.core.exceptions import ValidationError
                        raise ValidationError(f'Job {job} not found')
                MaterialService.resolve_or_create_for_line(
                    li,
                    job=job_obj,
                    price_list_item=pli,
                    qty=li.qty,
                    unit_cost=li.price,
                    description=li.description,
                    accounting_category=li.accounting_category,
                    material_id=material_id,
                )
        return li
```

- [ ] **Step 4: Run and verify pass**

Run: `python manage.py test tests.test_po_add_line_item_with_job -v 2`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/purchasing/services.py tests/test_po_add_line_item_with_job.py
git commit -m "feat(purchasing): add_line_item accepts job and material_id"
```

---

## Task 7: Add `PurchaseOrderService.change_line_job`

**Files:**
- Modify: `apps/purchasing/services.py` (PurchaseOrderService)
- Test: `tests/test_po_change_line_job.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_po_change_line_job.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Earmark, Material, PriceListItem
from apps.inventory.services import MaterialService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService
from apps.core.models import AccountingCategory, Configuration


class POChangeLineJobTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job_a = Job.objects.create(job_number='J-A', contact=c, description='a')
        self.job_b = Job.objects.create(job_number='J-B', contact=c, description='b')
        self.cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.cat, is_inventoried=True,
        )
        self.po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job_a.pk,
        )
        self.assertIsNotNone(self.line.linked_material)

    def test_change_job_with_delete_removes_old_material_and_creates_new(self):
        PurchaseOrderService.change_line_job(self.line.pk, self.job_b.pk, sever_decision='delete')
        self.line.refresh_from_db()
        # Old material gone
        self.assertFalse(Earmark.objects.filter(price_list_item=self.pli, job=self.job_a).exists())
        # New material linked on job_b
        new_mat = self.line.linked_material
        self.assertIsNotNone(new_mat)
        self.assertEqual(new_mat.job_id, self.job_b.pk)
        self.assertEqual(new_mat.quantity, Decimal('5.00'))
        ea = Earmark.objects.filter(price_list_item=self.pli, job=self.job_b).first()
        self.assertEqual(ea.quantity, Decimal('5.00'))

    def test_change_job_with_keep_preserves_old_material_unlinked(self):
        original_mat_id = self.line.linked_material.pk
        PurchaseOrderService.change_line_job(self.line.pk, self.job_b.pk, sever_decision='keep')
        # Old material still on job_a, unlinked
        old = Material.objects.get(pk=original_mat_id)
        self.assertEqual(old.job_id, self.job_a.pk)
        self.assertIsNone(old.po_line_item_id)
        self.assertEqual(Earmark.objects.get(price_list_item=self.pli, job=self.job_a).quantity, Decimal('5.00'))
        # New material on job_b
        self.line.refresh_from_db()
        new_mat = self.line.linked_material
        self.assertEqual(new_mat.job_id, self.job_b.pk)

    def test_change_job_missing_sever_decision_raises(self):
        with self.assertRaises(ValidationError):
            PurchaseOrderService.change_line_job(self.line.pk, self.job_b.pk)

    def test_change_job_with_consumed_material_raises(self):
        mat = self.line.linked_material
        mat.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        mat.save(update_fields=['consumption_state'])
        with self.assertRaises(ValidationError):
            PurchaseOrderService.change_line_job(self.line.pk, self.job_b.pk, sever_decision='delete')

    def test_change_job_to_none_unlinks(self):
        PurchaseOrderService.change_line_job(self.line.pk, None, sever_decision='delete')
        self.line.refresh_from_db()
        self.assertIsNone(self.line.linked_material)

    def test_change_job_on_issued_po_works_if_material_pending(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        PurchaseOrderService.change_line_job(self.line.pk, self.job_b.pk, sever_decision='delete')
        self.line.refresh_from_db()
        self.assertEqual(self.line.linked_material.job_id, self.job_b.pk)

    def test_change_job_raises_on_cancelled_po(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        self.po.status = PurchaseOrder.STATUS_CANCELLED
        self.po.save()
        with self.assertRaises(ValidationError):
            PurchaseOrderService.change_line_job(self.line.pk, self.job_b.pk, sever_decision='delete')
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_po_change_line_job -v 2`
Expected: FAIL — `PurchaseOrderService` has no `change_line_job`.

- [ ] **Step 3: Implement `change_line_job`**

In `apps/purchasing/services.py`, inside `class PurchaseOrderService` (near the other methods):

```python
    @staticmethod
    def change_line_job(line_item_id, new_job_id, sever_decision=None):
        """Change a PO line's job attribution. Allowed on any non-cancelled PO
        as long as the linked Material (if any) is pending."""
        from django.core.exceptions import ValidationError
        from django.db import transaction
        from apps.inventory.services import MaterialService
        from apps.jobs.models import Job

        try:
            li = PurchaseOrderLineItem.objects.get(pk=line_item_id)
        except PurchaseOrderLineItem.DoesNotExist:
            raise NotFoundError(f'PurchaseOrderLineItem {line_item_id} not found')
        if li.purchase_order.status == PurchaseOrder.STATUS_CANCELLED:
            raise ValidationError('Cannot change job on a cancelled PO.')

        new_job_obj = None
        if new_job_id is not None:
            try:
                new_job_obj = Job.objects.get(pk=new_job_id)
            except Job.DoesNotExist:
                raise ValidationError(f'Job {new_job_id} not found')

        with transaction.atomic():
            existing = li.linked_material
            if existing is not None:
                if sever_decision is None:
                    raise ValidationError(
                        'sever_decision is required when the line has a linked Material.'
                    )
                MaterialService.sever(existing, sever_decision)

            if new_job_obj is not None:
                MaterialService.resolve_or_create_for_line(
                    li,
                    job=new_job_obj,
                    price_list_item=li.price_list_item,
                    qty=li.qty,
                    unit_cost=li.price,
                    description=li.description,
                    accounting_category=li.accounting_category,
                )
```

- [ ] **Step 4: Run and verify pass**

Run: `python manage.py test tests.test_po_change_line_job -v 2`
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/purchasing/services.py tests/test_po_change_line_job.py
git commit -m "feat(purchasing): add change_line_job service"
```

---

## Task 8: Extend `cancel_line_item` / `cancel_po` / `delete_po` to accept sever decisions

**Files:**
- Modify: `apps/purchasing/services.py` (PurchaseOrderService.cancel_po, delete_po; PurchaseOrderReceivingService.cancel_line_item)
- Test: `tests/test_po_sever_on_cancel.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_po_sever_on_cancel.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Earmark, Material, PriceListItem
from apps.inventory.services import MaterialService
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService, PurchaseOrderReceivingService
from apps.core.models import AccountingCategory, Configuration, User


class POSeverOnCancelTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.user = User.objects.create_user(username='u', password='p')
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        self.cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.cat, is_inventoried=True,
        )
        self.po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )

    def test_cancel_line_item_with_linked_pending_requires_sever_decision(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        with self.assertRaises(ValidationError):
            PurchaseOrderReceivingService.cancel_line_item(
                self.po, self.line.pk, self.user, note='',
            )

    def test_cancel_line_item_delete_deletes_material(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        mat_id = self.line.linked_material.pk
        PurchaseOrderReceivingService.cancel_line_item(
            self.po, self.line.pk, self.user, note='', sever_decision='delete',
        )
        self.assertFalse(Material.objects.filter(pk=mat_id).exists())

    def test_cancel_line_item_keep_preserves_material_unlinked(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        mat_id = self.line.linked_material.pk
        PurchaseOrderReceivingService.cancel_line_item(
            self.po, self.line.pk, self.user, note='', sever_decision='keep',
        )
        mat = Material.objects.get(pk=mat_id)
        self.assertIsNone(mat.po_line_item_id)

    def test_cancel_po_requires_decisions_for_linked_lines(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        with self.assertRaises(ValidationError):
            PurchaseOrderService.cancel_po(self.po.pk)

    def test_cancel_po_with_decisions_applies_them(self):
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        mat_id = self.line.linked_material.pk
        PurchaseOrderService.cancel_po(
            self.po.pk, sever_decisions={self.line.pk: 'delete'},
        )
        self.assertFalse(Material.objects.filter(pk=mat_id).exists())
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.STATUS_CANCELLED)

    def test_delete_po_requires_decisions_for_linked_lines(self):
        with self.assertRaises(ValidationError):
            PurchaseOrderService.delete_po(self.po.pk)

    def test_delete_po_with_decisions_deletes_materials(self):
        mat_id = self.line.linked_material.pk
        PurchaseOrderService.delete_po(
            self.po.pk, sever_decisions={self.line.pk: 'delete'},
        )
        self.assertFalse(Material.objects.filter(pk=mat_id).exists())
        self.assertFalse(PurchaseOrder.objects.filter(pk=self.po.pk).exists())
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_po_sever_on_cancel -v 2`
Expected: FAIL — services don't accept these kwargs.

- [ ] **Step 3: Update the three services**

Replace `PurchaseOrderReceivingService.cancel_line_item` (in `apps/purchasing/services.py`, around line 298-335) — add `sever_decision=None` parameter. After the existing `qty_cancelled` math, before committing, if `li.linked_material` exists and is pending, require decision and apply:

```python
    @staticmethod
    def cancel_line_item(po, line_item_id, user, note='', sever_decision=None):
        """Cancel remaining quantity on a line item.
        If the line has a linked pending Material, sever_decision is required
        ('keep' or 'delete')."""
        from apps.core.models import HistoryEntry
        from apps.inventory.services import MaterialService
        from django.core.exceptions import ValidationError as DjangoValidationError

        if po.status not in (
            PurchaseOrder.STATUS_ISSUED,
            PurchaseOrder.STATUS_PARTLY_RECEIVED,
        ):
            raise ValidationError(
                f'Cannot cancel line items on a PO in status "{po.status}".'
            )

        with transaction.atomic():
            li = PurchaseOrderLineItem.objects.select_for_update().get(
                pk=line_item_id, purchase_order=po,
            )
            if li.qty_received + li.qty_cancelled >= li.qty:
                raise ValidationError(
                    f'Line item #{li.line_number} has no outstanding quantity to cancel.'
                )

            existing_mat = li.linked_material
            if existing_mat and existing_mat.consumption_state == existing_mat.CONSUMPTION_STATE_PENDING:
                if sever_decision is None:
                    raise DjangoValidationError(
                        'sever_decision is required; this line has a linked Material.'
                    )
                MaterialService.sever(existing_mat, sever_decision)

            qty_to_cancel = li.qty - li.qty_received - li.qty_cancelled
            li.qty_cancelled = li.qty - li.qty_received
            li.save(update_fields=['qty_cancelled'])

            HistoryEntry.objects.create(
                entry_type='action',
                object_type='purchaseorder',
                object_id=po.pk,
                user=user,
                changes={'_action': f'Line #{li.line_number} cancelled ({qty_to_cancel} remaining): {li.description}'},
                text=note,
            )

            PurchaseOrderReceivingService._update_po_status(po)

        return po
```

Replace `PurchaseOrderService.cancel_po` (around line 49-67) with:

```python
    @staticmethod
    def cancel_po(pk, sever_decisions=None):
        """Cancel an issued PO. sever_decisions: dict[line_item_id -> 'keep'|'delete'].
        Required for every line whose linked Material is pending."""
        from apps.inventory.services import MaterialService
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            po = PurchaseOrder.objects.get(pk=pk)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {pk} not found')
        if po.status != PurchaseOrder.STATUS_ISSUED:
            raise ValidationError(
                f'Cannot cancel PO {po.po_number}. Only issued POs can be cancelled.'
            )
        sever_decisions = sever_decisions or {}
        # Collect all lines needing a decision
        lines = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        needed = []
        for li in lines:
            mat = li.linked_material
            if mat and mat.consumption_state == mat.CONSUMPTION_STATE_PENDING:
                if li.pk not in sever_decisions:
                    needed.append(li.pk)
        if needed:
            raise DjangoValidationError(
                f'sever_decisions required for line(s): {needed}'
            )
        with transaction.atomic():
            for li in lines:
                mat = li.linked_material
                if mat and mat.consumption_state == mat.CONSUMPTION_STATE_PENDING:
                    MaterialService.sever(mat, sever_decisions[li.pk])
                li.qty_cancelled = li.qty - li.qty_received
                li.save(update_fields=['qty_cancelled'])
            po.status = PurchaseOrder.STATUS_CANCELLED
            po.full_clean()
            po.save()
        return po
```

Replace `PurchaseOrderService.delete_po` (around line 69-80) with:

```python
    @staticmethod
    def delete_po(pk, sever_decisions=None):
        """Delete a draft PO. sever_decisions: dict[line_item_id -> 'keep'|'delete']."""
        from apps.inventory.services import MaterialService
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            po = PurchaseOrder.objects.get(pk=pk)
        except PurchaseOrder.DoesNotExist:
            raise NotFoundError(f'PurchaseOrder {pk} not found')
        if po.status != PurchaseOrder.STATUS_DRAFT:
            raise ValidationError(
                f'Cannot delete PO {po.po_number}. Only draft POs can be deleted.'
            )
        sever_decisions = sever_decisions or {}
        lines = list(PurchaseOrderLineItem.objects.filter(purchase_order=po))
        needed = []
        for li in lines:
            mat = li.linked_material
            if mat and mat.consumption_state == mat.CONSUMPTION_STATE_PENDING:
                if li.pk not in sever_decisions:
                    needed.append(li.pk)
        if needed:
            raise DjangoValidationError(
                f'sever_decisions required for line(s): {needed}'
            )
        with transaction.atomic():
            for li in lines:
                mat = li.linked_material
                if mat and mat.consumption_state == mat.CONSUMPTION_STATE_PENDING:
                    MaterialService.sever(mat, sever_decisions[li.pk])
            po.delete()
```

- [ ] **Step 4: Run and verify pass**

Run: `python manage.py test tests.test_po_sever_on_cancel -v 2`
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/purchasing/services.py tests/test_po_sever_on_cancel.py
git commit -m "feat(purchasing): cancel/delete honor sever_decisions for linked Materials"
```

---

## Task 9: Rewrite `receive_items` — remove Material creation, loosen overage

**Files:**
- Modify: `apps/purchasing/services.py:193-296` (PurchaseOrderReceivingService.receive_items, _update_po_status)
- Test: `tests/test_po_receive_with_material.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_po_receive_with_material.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Earmark, Material, PriceListItem, InventoryAdjustment
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService, PurchaseOrderReceivingService
from apps.core.models import AccountingCategory, Configuration, User


class POReceiveWithMaterialTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.user = User.objects.create_user(username='u', password='p')
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        self.cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.cat, is_inventoried=True,
            qty_on_hand=Decimal('0.00'),
        )
        self.po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('10.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()

    def _receive(self, qty):
        return PurchaseOrderReceivingService.receive_items(
            self.po,
            [{'line_item_id': self.line.pk, 'qty_received': qty}],
            self.user,
        )

    def test_receipt_bumps_qoh_and_leaves_material_alone(self):
        mat = self.line.linked_material
        original_qty = mat.quantity
        self._receive(Decimal('3.00'))
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('3.00'))
        mat.refresh_from_db()
        self.assertEqual(mat.quantity, original_qty)
        self.assertEqual(
            Earmark.objects.get(price_list_item=self.pli, job=self.job).quantity,
            original_qty,
        )

    def test_partial_receipts_never_grow_material(self):
        mat = self.line.linked_material
        self._receive(Decimal('3.00'))
        self._receive(Decimal('5.00'))
        self._receive(Decimal('2.00'))
        self.pli.refresh_from_db()
        mat.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('10.00'))
        self.assertEqual(mat.quantity, Decimal('10.00'))  # plan

    def test_overage_receives_full_qty_but_material_unchanged(self):
        mat = self.line.linked_material
        self._receive(Decimal('12.00'))
        self.pli.refresh_from_db()
        mat.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('12.00'))
        self.assertEqual(mat.quantity, Decimal('10.00'))
        self.line.refresh_from_db()
        self.assertEqual(self.line.qty_received, Decimal('12.00'))
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.STATUS_RECEIVED_IN_FULL)

    def test_receipt_of_zero_is_skipped(self):
        self._receive(Decimal('0.00'))
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('0.00'))
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_po_receive_with_material -v 2`
Expected: FAIL — most cases fail because the current code either rejects overage or mutates the Material on receipt.

- [ ] **Step 3: Rewrite `receive_items` and `_update_po_status`**

In `apps/purchasing/services.py`, replace `PurchaseOrderReceivingService.receive_items` (around line 192-276) with:

```python
    @staticmethod
    def receive_items(po, items, user):
        """Record receipt of items on a PO.
        Material.quantity is unchanged — planned consumption is set at line-add time.
        QOH bumps by received qty for inventoried PLIs. Overage is accepted."""
        from apps.core.models import HistoryEntry
        from apps.inventory.models import InventoryAdjustment
        from django.utils import timezone

        if po.status not in (
            PurchaseOrder.STATUS_ISSUED,
            PurchaseOrder.STATUS_PARTLY_RECEIVED,
        ):
            raise ValidationError(
                f'Cannot receive items on a PO in status "{po.status}".'
            )

        now = timezone.now()
        history_lines = []
        inventory_updates = []

        with transaction.atomic():
            for item_data in items:
                li = PurchaseOrderLineItem.objects.select_for_update().get(
                    pk=item_data['line_item_id'],
                    purchase_order=po,
                )
                qty = Decimal(str(item_data['qty_received']))
                if qty <= 0:
                    continue

                li.qty_received = li.qty_received + qty
                li.received_by = user
                li.received_date = now
                if item_data.get('note'):
                    li.receipt_note = item_data['note']
                li.save()

                history_lines.append(
                    f'#{li.line_number} {li.description}: received {qty}'
                    + (f' — {item_data["note"]}' if item_data.get('note') else '')
                )

                # QOH for inventoried PLI-backed lines
                if li.price_list_item and li.price_list_item.is_inventoried:
                    li.price_list_item.qty_on_hand += qty
                    li.price_list_item.save(update_fields=['qty_on_hand'])
                    InventoryAdjustment.objects.create(
                        price_list_item=li.price_list_item,
                        quantity_change=qty,
                        reason=f'Received on {po.po_number}',
                    )
                    inventory_updates.append(li.price_list_item.code)

            PurchaseOrderReceivingService._update_po_status(po)

            if history_lines:
                action_text = f'Items received by {user.get_full_name() or user.username}'
                if inventory_updates:
                    action_text += f'. Inventory updated: {", ".join(inventory_updates)}'
                HistoryEntry.objects.create(
                    entry_type='action',
                    object_type='purchaseorder',
                    object_id=po.pk,
                    user=user,
                    changes={'_action': action_text},
                    text='\n'.join(history_lines),
                )
        return po
```

Update `_update_po_status` (around line 395-426) — change `==` to `>=` for the all-done check:

```python
        all_done = all(li.qty_received + li.qty_cancelled >= li.qty for li in all_items)
```

- [ ] **Step 4: Run and verify pass**

Run: `python manage.py test tests.test_po_receive_with_material -v 2`
Expected: 4 tests pass.

- [ ] **Step 5: Confirm existing receipt tests still pass**

Run: `python manage.py test tests.test_api_purchasing tests.test_po_receive_with_material -v 2`
Expected: all pass. If any existing test fails because it relied on the old "reject overage" behavior, update it to expect the new overage-accepted behavior.

- [ ] **Step 6: Commit**

```bash
git add apps/purchasing/services.py tests/test_po_receive_with_material.py
git commit -m "feat(purchasing): receive_items accepts overage and leaves Materials alone"
```

---

## Task 10: `reverse_receipt` — untouched Material; consumed raises

**Files:**
- Modify: `apps/purchasing/services.py` (PurchaseOrderReceivingService.reverse_receipt)
- Test: `tests/test_po_reverse_receipt_with_material.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_po_reverse_receipt_with_material.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Earmark, Material, PriceListItem
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService, PurchaseOrderReceivingService
from apps.core.models import AccountingCategory, Configuration, User


class POReverseReceiptWithMaterialTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.user = User.objects.create_user(username='u', password='p')
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=cat, is_inventoried=True,
            qty_on_hand=Decimal('0.00'),
        )
        self.po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        PurchaseOrderReceivingService.receive_items(
            self.po, [{'line_item_id': self.line.pk, 'qty_received': Decimal('5.00')}], self.user,
        )

    def test_reverse_receipt_with_pending_material_leaves_it_alone(self):
        mat = self.line.linked_material
        original_qty = mat.quantity
        original_earmark = Earmark.objects.get(price_list_item=self.pli, job=self.job).quantity
        PurchaseOrderReceivingService.reverse_receipt(self.po, self.line.pk, self.user, note='')
        mat.refresh_from_db()
        self.assertEqual(mat.quantity, original_qty)
        self.assertEqual(
            Earmark.objects.get(price_list_item=self.pli, job=self.job).quantity,
            original_earmark,
        )
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_on_hand, Decimal('0.00'))
        self.line.refresh_from_db()
        self.assertEqual(self.line.qty_received, Decimal('0.00'))

    def test_reverse_receipt_raises_if_material_consumed(self):
        mat = self.line.linked_material
        mat.consumption_state = Material.CONSUMPTION_STATE_CONSUMED
        mat.save(update_fields=['consumption_state'])
        with self.assertRaises(ValidationError):
            PurchaseOrderReceivingService.reverse_receipt(self.po, self.line.pk, self.user, note='')
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_po_reverse_receipt_with_material -v 2`
Expected: FAIL — either the reversal mutates Material or consumed-check is missing.

- [ ] **Step 3: Update `reverse_receipt`**

In `apps/purchasing/services.py`, in `PurchaseOrderReceivingService.reverse_receipt` (around line 337-393), after the initial status check and inside the `transaction.atomic()`, add the consumed-material guard before mutating QOH/line:

```python
    @staticmethod
    def reverse_receipt(po, line_item_id, user, note=''):
        """Reverse all received quantity on a line item. Raises if linked Material consumed."""
        from apps.core.models import HistoryEntry
        from apps.inventory.models import InventoryAdjustment

        if po.status not in (
            PurchaseOrder.STATUS_ISSUED,
            PurchaseOrder.STATUS_PARTLY_RECEIVED,
            PurchaseOrder.STATUS_RECEIVED_IN_FULL,
        ):
            raise ValidationError(
                f'Cannot reverse receipts on a PO in status "{po.status}".'
            )

        with transaction.atomic():
            li = PurchaseOrderLineItem.objects.select_for_update().get(
                pk=line_item_id, purchase_order=po,
            )
            if li.qty_received <= 0:
                raise ValidationError(
                    f'Line item #{li.line_number} has no received quantity to reverse.'
                )

            existing_mat = li.linked_material
            if existing_mat and existing_mat.consumption_state == existing_mat.CONSUMPTION_STATE_CONSUMED:
                raise ValidationError(
                    'Cannot reverse receipt; linked Material has been consumed. Restock first.'
                )

            reversed_qty = li.qty_received

            if li.price_list_item and li.price_list_item.is_inventoried:
                li.price_list_item.qty_on_hand -= reversed_qty
                li.price_list_item.save(update_fields=['qty_on_hand'])
                InventoryAdjustment.objects.create(
                    price_list_item=li.price_list_item,
                    quantity_change=-reversed_qty,
                    reason=f'Reversed receipt on {po.po_number}',
                )

            li.qty_received = Decimal('0.00')
            li.qty_cancelled = Decimal('0.00')
            li.received_by = None
            li.received_date = None
            li.receipt_note = ''
            li.save(update_fields=[
                'qty_received', 'qty_cancelled',
                'received_by', 'received_date', 'receipt_note',
            ])

            HistoryEntry.objects.create(
                entry_type='action',
                object_type='purchaseorder',
                object_id=po.pk,
                user=user,
                changes={'_action': f'Line #{li.line_number} receipt reversed ({reversed_qty}): {li.description}'},
                text=note,
            )

            PurchaseOrderReceivingService._update_po_status(po)

        return po
```

- [ ] **Step 4: Run and verify pass**

Run: `python manage.py test tests.test_po_reverse_receipt_with_material -v 2`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/purchasing/services.py tests/test_po_reverse_receipt_with_material.py
git commit -m "feat(purchasing): reverse_receipt preserves Material, blocks on consumed"
```

---

## Task 11: Wire services into API viewset — line-item POST/PATCH, cancel, destroy

**Files:**
- Modify: `apps/api/purchasing/views.py` (PurchaseOrderViewSet)
- Test: `tests/test_api_po_job_material.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_po_job_material.py`:

```python
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import Material, PriceListItem
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import PurchaseOrderService
from apps.core.models import AccountingCategory, Configuration, User
from django.contrib.auth.models import Permission


class APIPOJobMaterialTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.user = User.objects.create_user(username='u', password='p')
        perm = Permission.objects.get(codename='can_manage_financials')
        self.user.user_permissions.add(perm)
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        self.cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=self.cat, is_inventoried=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.po = PurchaseOrder.objects.create(business=self.business)

    def _post_line(self, **data):
        return self.client.post(
            f'/api/purchase-orders/{self.po.pk}/line-items/',
            data=data, format='json',
        )

    def test_post_line_with_job_creates_material(self):
        r = self._post_line(
            description='x', qty='5.00', price='1.00',
            price_list_item=self.pli.pk, job=self.job.pk,
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Material.objects.filter(job=self.job, po_line_item__isnull=False).count(), 1)

    def test_patch_line_change_job_requires_sever_decision(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        other_job = Job.objects.create(job_number='J-2', contact=self.job.contact, description='o')
        r = self.client.patch(
            f'/api/purchase-orders/{self.po.pk}/line-items/{line.pk}/',
            data={'job': other_job.pk}, format='json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn('sever_decision', r.json().get('detail', ''))

    def test_patch_line_change_job_with_delete_succeeds(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        other_job = Job.objects.create(job_number='J-2', contact=self.job.contact, description='o')
        r = self.client.patch(
            f'/api/purchase-orders/{self.po.pk}/line-items/{line.pk}/',
            data={'job': other_job.pk, 'sever_decision': 'delete'}, format='json',
        )
        self.assertEqual(r.status_code, 200)
        line.refresh_from_db()
        self.assertEqual(line.linked_material.job_id, other_job.pk)

    def test_cancel_line_item_requires_sever_decision(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        r = self.client.post(
            f'/api/purchase-orders/{self.po.pk}/cancel-line-item/',
            data={'line_item_id': line.pk}, format='json',
        )
        self.assertEqual(r.status_code, 400)

    def test_cancel_po_requires_sever_decisions(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        self.po.status = PurchaseOrder.STATUS_ISSUED
        self.po.save()
        r = self.client.post(
            f'/api/purchase-orders/{self.po.pk}/cancel/',
            data={'reason': 'oops'}, format='json',
        )
        self.assertEqual(r.status_code, 400)

    def test_delete_draft_po_requires_sever_decisions(self):
        PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        r = self.client.delete(f'/api/purchase-orders/{self.po.pk}/?confirm=true')
        self.assertEqual(r.status_code, 400)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_api_po_job_material -v 2`
Expected: FAIL — viewset doesn't accept `job`/`sever_decision` / doesn't dispatch `change_line_job`.

- [ ] **Step 3: Update the viewset**

In `apps/api/purchasing/views.py`, override `line_items` and `line_item_detail` on `PurchaseOrderViewSet` to dispatch correctly. Add these as override methods (they shadow the `LineItemMixin` defaults):

```python
    @action(detail=True, methods=['get', 'post'], url_path='line-items', url_name='line-items')
    def line_items(self, request, pk=None):
        """Line-item list (GET) / create (POST). POST accepts transient job, material_id."""
        from rest_framework.exceptions import ValidationError as DRFValidationError
        from django.core.exceptions import ValidationError as DjangoValidationError
        from apps.core.services import NotFoundError
        parent = self.get_object()
        if request.method == 'GET':
            items = self._get_line_items_qs(parent)
            serializer = self.line_item_serializer_class(items, many=True)
            return Response(serializer.data)

        service = self.line_item_service_class
        data = request.data.copy()
        pli_id = data.get('price_list_item')
        has_manual_fields = data.get('description') or data.get('price')
        job = data.pop('job', None)
        material_id = data.pop('material_id', None)
        # Strip `task` — reserved field; ignored by this feature
        data.pop('task', None)

        try:
            if pli_id and not has_manual_fields:
                qty = data.get('qty', 0)
                item = service.add_line_item_from_pli(
                    parent.pk, pli_id, qty, job=job, material_id=material_id,
                )
            else:
                if job is not None:
                    data['job'] = job
                if material_id is not None:
                    data['material_id'] = material_id
                item = service.add_line_item(parent.pk, **data)
        except (DjangoValidationError, NotFoundError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.line_item_serializer_class(item)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='line-items/(?P<item_id>[0-9]+)', url_name='line-item-detail')
    def line_item_detail(self, request, pk=None, item_id=None):
        """Line-item PATCH/DELETE. PATCH dispatches to change_line_job if payload
        has only 'job' (and optional 'sever_decision')."""
        from django.core.exceptions import ValidationError as DjangoValidationError
        from apps.core.services import NotFoundError
        parent = self.get_object()
        item = self._get_line_item_or_404(parent, item_id)
        service = self.line_item_service_class

        if request.method == 'DELETE':
            try:
                service.delete_line_item(item.pk)
            except (DjangoValidationError, Exception) as e:
                return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            return Response({'message': 'Line item deleted.'})

        data = request.data.copy()
        job_keys = {'job', 'sever_decision'}
        is_job_only = set(data.keys()).issubset(job_keys) and 'job' in data
        try:
            if is_job_only:
                service.change_line_job(
                    item.pk, data.get('job'), sever_decision=data.get('sever_decision'),
                )
                item.refresh_from_db()
            else:
                data.pop('job', None)
                data.pop('sever_decision', None)
                data.pop('material_id', None)
                item = service.update_line_item(item.pk, **data)
        except (DjangoValidationError, NotFoundError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.line_item_serializer_class(item)
        return Response(serializer.data)
```

Update the `cancel_line_item` action to pass `sever_decision`:

```python
    @action(detail=True, methods=['post'], url_path='cancel-line-item', url_name='cancel-line-item')
    def cancel_line_item(self, request, pk=None):
        po = self.get_object()
        line_item_id = request.data.get('line_item_id')
        note = request.data.get('note', '')
        sever_decision = request.data.get('sever_decision')
        if not line_item_id:
            return Response({'line_item_id': ['This field is required.']},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            po = PurchaseOrderReceivingService.cancel_line_item(
                po, line_item_id, request.user, note=note, sever_decision=sever_decision,
            )
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(po)
        return Response(serializer.data)
```

Update the `status_actions` dict for `cancel` to consume `sever_decisions`, and override `destroy` so DELETE accepts them. Replace the `status_actions` cancel entry:

```python
    status_actions = {
        'issue': {
            'service': lambda pk: PurchaseOrderService.update_status(pk, PurchaseOrder.STATUS_ISSUED),
        },
        'cancel': {
            'service': lambda pk, reason=None, sever_decisions=None: PurchaseOrderService.cancel_po(pk, sever_decisions=sever_decisions),
            'requires_reason': True,
            'extra_params': ['sever_decisions'],
        },
    }
```

Check `apps/api/mixins.py::StatusTransitionMixin` — if it doesn't already forward `extra_params`, adjust the mixin or implement a custom `cancel` action that reads `sever_decisions`. The simplest is: override cancel:

```python
    @action(detail=True, methods=['post'], url_path='cancel', url_name='cancel')
    def cancel(self, request, pk=None):
        from django.core.exceptions import ValidationError as DjangoValidationError
        sever_decisions = request.data.get('sever_decisions')
        try:
            po = PurchaseOrderService.cancel_po(pk, sever_decisions=sever_decisions)
        except (DjangoValidationError, Exception) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(po)
        return Response(serializer.data)
```

And override `destroy` to route through `delete_po` with sever decisions:

```python
    def destroy(self, request, *args, **kwargs):
        from django.core.exceptions import ValidationError as DjangoValidationError
        po = self.get_object()
        # DRF passes body on DELETE
        sever_decisions = request.data.get('sever_decisions') if request.data else None
        try:
            PurchaseOrderService.delete_po(po.pk, sever_decisions=sever_decisions)
        except (DjangoValidationError, Exception) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'message': f'PO {po.po_number} deleted.'})
```

- [ ] **Step 4: Run and verify pass**

Run: `python manage.py test tests.test_api_po_job_material -v 2`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/purchasing/views.py tests/test_api_po_job_material.py
git commit -m "feat(api): PO line-item endpoints accept job, material_id, sever decisions"
```

---

## Task 12: Update `POLineItemSerializer` — derive effective_job from Material; add material field

**Files:**
- Modify: `apps/api/purchasing/serializers.py:18-58` (POLineItemSerializer)
- Test: `tests/test_po_serializer_material.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_po_serializer_material.py`:

```python
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import PriceListItem
from apps.purchasing.services import PurchaseOrderService
from apps.purchasing.models import PurchaseOrder
from apps.api.purchasing.serializers import POLineItemSerializer
from apps.core.models import AccountingCategory, Configuration


class POSerializerMaterialTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=cat,
        )
        self.po = PurchaseOrder.objects.create(business=self.business)

    def test_linked_line_exposes_effective_job_and_material(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        data = POLineItemSerializer(line).data
        self.assertEqual(data['effective_job_id'], self.job.pk)
        self.assertEqual(data['effective_job_number'], self.job.job_number)
        self.assertIsNotNone(data['material'])
        self.assertEqual(data['material']['job_id'], self.job.pk)
        self.assertEqual(data['material']['quantity'], '5.00')

    def test_unlinked_line_has_null_material_and_null_effective_job(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk,
        )
        data = POLineItemSerializer(line).data
        self.assertIsNone(data['effective_job_id'])
        self.assertIsNone(data['material'])

    def test_serializer_does_not_expose_job_field(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk,
        )
        data = POLineItemSerializer(line).data
        self.assertNotIn('job', data)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_po_serializer_material -v 2`
Expected: FAIL — serializer still exposes `job`, no `material` field.

- [ ] **Step 3: Rewrite the serializer**

Replace `POLineItemSerializer` in `apps/api/purchasing/serializers.py`:

```python
class POLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    received_by_name = serializers.SerializerMethodField()
    effective_job_id = serializers.SerializerMethodField()
    effective_job_number = serializers.SerializerMethodField()
    material = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderLineItem
        fields = [
            'line_item_id', 'line_number', 'task', 'price_list_item',
            'qty', 'units', 'description', 'price',
            'effective_job_id', 'effective_job_number', 'material',
            'accounting_category', 'taxable_override', 'tax_rate_override',
            'qty_received', 'received_by', 'received_by_name',
            'received_date', 'receipt_note', 'qty_cancelled',
        ]
        read_only_fields = [
            'line_item_id', 'qty_received', 'received_by', 'received_by_name',
            'received_date', 'receipt_note', 'qty_cancelled',
            'effective_job_id', 'effective_job_number', 'material',
        ]

    def get_received_by_name(self, obj):
        if obj.received_by:
            return obj.received_by.get_full_name() or obj.received_by.username
        return None

    def _material(self, obj):
        return obj.linked_material

    def get_effective_job_id(self, obj):
        mat = self._material(obj)
        return mat.job_id if mat else None

    def get_effective_job_number(self, obj):
        mat = self._material(obj)
        return mat.job.job_number if mat else None

    def get_material(self, obj):
        mat = self._material(obj)
        if mat is None:
            return None
        return {
            'material_id': mat.pk,
            'description': mat.description,
            'quantity': str(mat.quantity),
            'consumption_state': mat.consumption_state,
            'job_id': mat.job_id,
            'job_number': mat.job.job_number,
        }
```

- [ ] **Step 4: Run and verify pass**

Run: `python manage.py test tests.test_po_serializer_material -v 2`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/purchasing/serializers.py tests/test_po_serializer_material.py
git commit -m "feat(api): POLineItemSerializer derives effective_job from Material"
```

---

## Task 13: Update PO list filter and prefetch (viewset)

**Files:**
- Modify: `apps/api/purchasing/views.py:22-53` (queryset/get_queryset)

- [ ] **Step 1: Add a regression test**

Append to `tests/test_api_po_job_material.py`:

```python
    def test_po_list_filtered_by_job_returns_pos_for_that_job(self):
        line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        other_job = Job.objects.create(job_number='J-2', contact=self.job.contact, description='o')
        r = self.client.get(f'/api/purchase-orders/?job={self.job.pk}')
        self.assertEqual(r.status_code, 200)
        ids = [po['po_id'] for po in r.json()['results']]
        self.assertIn(self.po.pk, ids)
        r2 = self.client.get(f'/api/purchase-orders/?job={other_job.pk}')
        ids2 = [po['po_id'] for po in r2.json()['results']]
        self.assertNotIn(self.po.pk, ids2)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_api_po_job_material.APIPOJobMaterialTest.test_po_list_filtered_by_job_returns_pos_for_that_job -v 2`
Expected: FAIL because the filter still uses `purchaseorderlineitem__job` which no longer matches any rows (since Line.job is still present but nothing writes to it — actually it'd find 0 results since Line.job is null).

- [ ] **Step 3: Update queryset/filter**

In `apps/api/purchasing/views.py`, replace the queryset and the `get_queryset` filter to go through Material:

```python
    queryset = PurchaseOrder.objects.all().prefetch_related(
        'purchaseorderlineitem_set__task__job',
        'purchaseorderlineitem_set__price_list_item',
    ).order_by('-created_date')
```

(Remove `purchaseorderlineitem_set__job` from prefetch since the field is going away.)

And the `job` filter:

```python
        job = self.request.query_params.get('job')
        if job:
            qs = qs.filter(purchaseorderlineitem__material__job=job).distinct()
```

Note: this works after Task 1 added `Material.po_line_item`, and `Material.materials` reverse on `PurchaseOrderLineItem` is accessible via `purchaseorderlineitem__material__job` (Django will find Materials pointing at the line via the FK even with `related_name='+'`).

Actually verify: `related_name='+'` disables the reverse accessor on Python, but the DB relation is still there. Django ORM `filter(purchaseorderlineitem__material__...)` uses the lowercased model name when no related_name is set. Since we set `related_name='+'`, we need to use the explicit FK name: `filter(purchaseorderlineitem__material_set__job=...)` won't work.

Use the explicit lookup via Materials:

```python
        job = self.request.query_params.get('job')
        if job:
            from apps.inventory.models import Material
            line_ids = Material.objects.filter(job=job, po_line_item__isnull=False).values_list('po_line_item_id', flat=True)
            qs = qs.filter(purchaseorderlineitem__in=line_ids).distinct()
```

- [ ] **Step 4: Run and verify pass**

Run: `python manage.py test tests.test_api_po_job_material -v 2`
Expected: all tests (including the new one) pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/purchasing/views.py tests/test_api_po_job_material.py
git commit -m "feat(api): PO list ?job filter traverses Material.po_line_item"
```

---

## Task 14: Update search service to traverse Material

**Files:**
- Modify: `apps/search/services.py:341` and line ~789 (within-search variant if present)

- [ ] **Step 1: Write the failing test**

Create `tests/test_search_po_by_job.py`:

```python
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import PriceListItem
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import PurchaseOrderService
from apps.search.services import SearchService
from apps.core.models import AccountingCategory, Configuration


class SearchPOByJobTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='UNIQUEJOBXYZ', contact=c, description='j')
        cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=cat,
        )
        self.po = PurchaseOrder.objects.create(business=self.business)
        PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )

    def test_po_search_finds_po_by_associated_job_number(self):
        results = SearchService.search('UNIQUEJOBXYZ')
        pos_category = results.get('purchase_orders')
        self.assertTrue(pos_category, 'purchase_orders category missing from results')
        po_ids = [po.pk for po in pos_category['items']]
        self.assertIn(self.po.pk, po_ids)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_search_po_by_job -v 2`
Expected: FAIL — the current search traverses `purchaseorderlineitem__job` which is empty.

- [ ] **Step 3: Update the search query**

In `apps/search/services.py`, search for `purchaseorderlineitem__job__job_number` — there's at least one occurrence around line 341 and possibly a within-search variant around line 789. Replace each with a query via Material. The cleanest pattern:

```python
# In the purchase order search method, replace:
#   Q(purchaseorderlineitem__job__job_number__icontains=query)
# with the equivalent via Material:
from apps.inventory.models import Material
material_line_ids = Material.objects.filter(
    job__job_number__icontains=query, po_line_item__isnull=False,
).values_list('po_line_item_id', flat=True)
# Then in the PurchaseOrder queryset Q:
# Q(po_number__icontains=query) | Q(business__business_name__icontains=query) |
# Q(purchaseorderlineitem__in=material_line_ids)
```

Adjust both the main search and the within-search variant. Keep the existing `Q(po_number__icontains=query)` and `Q(business__business_name__icontains=query)` branches.

- [ ] **Step 4: Run and verify pass**

Run: `python manage.py test tests.test_search_po_by_job -v 2`
Expected: pass.

Also run the full search test suite to catch regressions:
Run: `python manage.py test tests.test_api_home tests.test_search_po_by_job -v 2` (or similar — whichever test files exercise search).
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/search/services.py tests/test_search_po_by_job.py
git commit -m "feat(search): PO search traverses Material for job association"
```

---

## Task 15: Update legacy Django job-detail view to use Material traversal

**Files:**
- Modify: `apps/jobs/views.py:136-139`

- [ ] **Step 1: Inspect the current code and confirm the query**

Read `apps/jobs/views.py:125-155` to locate the PO fetch:

```python
from apps.purchasing.models import PurchaseOrderLineItem
po_ids = PurchaseOrderLineItem.objects.filter(job=job).values_list('purchase_order_id', flat=True).distinct()
purchase_orders = PurchaseOrder.objects.filter(po_id__in=po_ids).order_by('-po_id')
```

- [ ] **Step 2: Write a regression test**

Create `tests/test_legacy_job_view_po_list.py`:

```python
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import PriceListItem
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import PurchaseOrderService
from apps.core.models import AccountingCategory, Configuration, User


class LegacyJobViewPOListTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.user = User.objects.create_user(username='u', password='p')
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=cat,
        )
        self.po = PurchaseOrder.objects.create(business=self.business)
        PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )

    def test_legacy_job_detail_lists_pos_linked_via_material(self):
        self.client.force_login(self.user)
        resp = self.client.get(f'/jobs/{self.job.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.po.po_number.encode(), resp.content)
```

- [ ] **Step 3: Run to verify failure**

Run: `python manage.py test tests.test_legacy_job_view_po_list -v 2`
Expected: FAIL — PO not listed (query finds nothing via `line.job`).

- [ ] **Step 4: Update the query**

Replace the PO fetch block in `apps/jobs/views.py` (around line 136-139):

```python
    from apps.purchasing.models import PurchaseOrder
    from apps.inventory.models import Material
    line_ids = Material.objects.filter(job=job, po_line_item__isnull=False).values_list(
        'po_line_item_id', flat=True,
    )
    purchase_orders = PurchaseOrder.objects.filter(
        purchaseorderlineitem__in=line_ids,
    ).distinct().order_by('-po_id')
```

Remove the now-unused `from apps.purchasing.models import PurchaseOrderLineItem` import if it isn't used elsewhere in the file.

- [ ] **Step 5: Run and verify pass**

Run: `python manage.py test tests.test_legacy_job_view_po_list -v 2`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/views.py tests/test_legacy_job_view_po_list.py
git commit -m "fix(jobs): legacy job view lists POs via Material.po_line_item"
```

---

## Task 16: Drop `PurchaseOrderLineItem.job` field (model + migration)

**Files:**
- Modify: `apps/purchasing/models.py:358-363` (remove `job` field)
- Create: `apps/purchasing/migrations/XXXX_drop_line_item_job.py` (generated)
- Modify: `tests/test_po_line_item_job.py` (remove / rewrite)

- [ ] **Step 1: Confirm no remaining readers**

Run: `grep -rn "purchaseorderlineitem__job" apps/ tests/ frontend/src/`
Expected: zero hits (this was the only ORM traversal we had; now replaced by `__material__job`).

Run: `grep -rn "PurchaseOrderLineItem.objects.*job=" apps/ tests/`
Expected: zero hits. Any that remain are obsolete constructors writing to the about-to-be-removed field.

Run: `grep -rn "li\.job\b\|line\.job\b\|po_line\.job\b\|line_item\.job\b" apps/ tests/ frontend/src/`
Expected: no functional reads (comments OK).

If any remain, fix them first before dropping the column.

- [ ] **Step 2: Remove the field**

In `apps/purchasing/models.py`, in `class PurchaseOrderLineItem`, delete the `job` field (around lines 360-363):

```python
    # Remove:
    # job = models.ForeignKey(
    #     'jobs.Job', on_delete=models.SET_NULL,
    #     null=True, blank=True,
    # )
```

Keep the `task` FK unchanged.

- [ ] **Step 3: Remove/rewrite the obsolete test**

`tests/test_po_line_item_job.py` tested the FK directly. Delete the tests that only exercise the field; if any still exercise the new Material flow, migrate them to the equivalent `linked_material` assertions. Simplest: delete the file entirely — it's covered by the new test files in Tasks 6, 7, 10, 11.

```bash
git rm tests/test_po_line_item_job.py
```

- [ ] **Step 4: Generate migration**

Run: `python manage.py makemigrations purchasing`
Expected: a migration that removes the `job` field on `PurchaseOrderLineItem`. Inspect it.

- [ ] **Step 5: Ask the user to apply migration and run full test suite**

Ask the user to apply the migration. After they confirm:

Run: `python manage.py test -v 2`
Expected: full suite passes. If any tests break because they set `job=...` on a PO line item constructor, update them to use the new attribution path (`PurchaseOrderService.add_line_item(..., job=X)`).

Also update `tests/test_api_purchasing.py:58` if the test still writes `job=job` on a `PurchaseOrderLineItem.objects.create(...)`.

- [ ] **Step 6: Commit**

```bash
git add apps/purchasing/models.py apps/purchasing/migrations/ tests/
git commit -m "feat(purchasing): drop PurchaseOrderLineItem.job field"
```

---

## Task 17: Add Material serializer fields for PO badge on Job page

**Files:**
- Modify: `apps/api/jobs/serializers.py` (Material serializer, whatever serializer exposes Materials on a Job)

- [ ] **Step 1: Find the Material serializer used by the job detail payload**

Run: `grep -rn "class.*Material.*Serializer" apps/api/`

Open the Material serializer that the job payload uses (most likely in `apps/api/jobs/serializers.py` or similar). Note its current `fields`.

- [ ] **Step 2: Write a test**

Create `tests/test_job_material_serializer_po_fields.py`:

```python
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.jobs.models import Job
from apps.inventory.models import PriceListItem
from apps.purchasing.services import PurchaseOrderService
from apps.purchasing.models import PurchaseOrder
from apps.core.models import AccountingCategory, Configuration, User


class JobMaterialSerializerPOFieldsTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.user = User.objects.create_user(username='u', password='p')
        c = Contact.objects.create(first_name='V', last_name='V', work_number='5')
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business; c.save()
        self.job = Job.objects.create(job_number='J-1', contact=c, description='j')
        cat = AccountingCategory.objects.get_or_create(code='MAT', defaults={'name': 'Material'})[0]
        self.pli = PriceListItem.objects.create(
            code='P', description='p', purchase_price=Decimal('1.00'),
            selling_price=Decimal('2.00'), accounting_category=cat,
        )
        self.po = PurchaseOrder.objects.create(business=self.business)
        self.line = PurchaseOrderService.add_line_item(
            self.po.pk, description='x', qty=Decimal('5.00'),
            price=Decimal('1.00'), price_list_item=self.pli.pk, job=self.job.pk,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_material_payload_exposes_po_fields(self):
        r = self.client.get(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(r.status_code, 200)
        mats = r.json()['materials']
        linked = [m for m in mats if m.get('po_line_item_id')]
        self.assertEqual(len(linked), 1)
        mat = linked[0]
        self.assertEqual(mat['po_line_item_id'], self.line.pk)
        self.assertEqual(mat['po_number'], self.po.po_number)
        self.assertEqual(mat['po_status'], self.po.status)
```

Materials are nested inside the Job detail payload (see `apps/api/jobs/serializers.py:47`) so we read them from there.

- [ ] **Step 3: Run to verify failure**

Run: `python manage.py test tests.test_job_material_serializer_po_fields -v 2`
Expected: FAIL — fields not yet on serializer.

- [ ] **Step 4: Add fields to the Material serializer**

In the Material serializer file, add three SerializerMethodFields:

```python
    po_line_item_id = serializers.SerializerMethodField()
    po_number = serializers.SerializerMethodField()
    po_status = serializers.SerializerMethodField()

    # Add to Meta.fields:
    # 'po_line_item_id', 'po_number', 'po_status',

    def get_po_line_item_id(self, obj):
        return obj.po_line_item_id

    def get_po_number(self, obj):
        if obj.po_line_item_id and obj.po_line_item:
            return obj.po_line_item.purchase_order.po_number
        return None

    def get_po_status(self, obj):
        if obj.po_line_item_id and obj.po_line_item:
            return obj.po_line_item.purchase_order.status
        return None
```

- [ ] **Step 5: Run and verify pass**

Run: `python manage.py test tests.test_job_material_serializer_po_fields -v 2`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add apps/api/jobs/serializers.py tests/test_job_material_serializer_po_fields.py
git commit -m "feat(api): Material serializer exposes PO line info for badge"
```

---

## Task 18: Frontend — `JobDetail.svelte`: use `effective_job_id` instead of `li.job`

**Files:**
- Modify: `frontend/src/components/jobs/JobDetail.svelte:314-327`

- [ ] **Step 1: Read the current cross-job logic**

Open `frontend/src/components/jobs/JobDetail.svelte` at lines 305-340. Note the logic:

```svelte
{#if po.line_items?.some(li => li.job && li.job !== job.job_id)}
  {#each po.line_items as li}
    <tr class:other-job={li.job && li.job !== job.job_id}>
      <td colspan="2" style="padding-left: 32px; font-size: 13px;">
        {li.description}
        {#if li.job && li.job !== job.job_id}
          <span class="other-job-label">(other job)</span>
        {/if}
      </td>
      ...
```

- [ ] **Step 2: Switch to `effective_job_id`**

Replace `li.job` with `li.effective_job_id` in that block:

```svelte
{#if po.line_items?.some(li => li.effective_job_id && li.effective_job_id !== job.job_id)}
  {#each po.line_items as li}
    <tr class:other-job={li.effective_job_id && li.effective_job_id !== job.job_id}>
      <td colspan="2" style="padding-left: 32px; font-size: 13px;">
        {li.description}
        {#if li.effective_job_id && li.effective_job_id !== job.job_id}
          <span class="other-job-label">(other job)</span>
        {/if}
      </td>
      ...
```

- [ ] **Step 3: Manually verify in browser**

Start the dev server (`python manage.py runserver` in one terminal, `cd frontend && npm run dev` in another). Navigate to a Job with at least one linked PO (use the "Order this" flow to set one up). Verify the PO shows under the Purchase Orders accordion and cross-job lines render correctly.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/jobs/JobDetail.svelte
git commit -m "fix(frontend): JobDetail uses effective_job_id from serializer"
```

---

## Task 19: Frontend — add Job picker to `LineItemForm.svelte`

**Files:**
- Modify: `frontend/src/components/purchaseorders/LineItemForm.svelte`

- [ ] **Step 1: Add a Job picker prop and state**

At the top of the script in `LineItemForm.svelte`, add a `defaultJob` prop and form state:

```svelte
<script>
  import PriceListItemPicker from '../PriceListItemPicker.svelte';
  import UnitsSelect from '../UnitsSelect.svelte';
  import JobPicker from '../JobPicker.svelte';

  const {
    categories = [],
    onSubmit,
    onCancel,
    defaultJob = null,      // { job_id, job_number } or null
    materialId = null,      // if present, passed along on submit
  } = $props();

  let mode = $state('manual');
  let selectedPLI = $state(null);
  let selectedJob = $state(defaultJob);

  let form = $state({
    description: '',
    qty: '',
    units: 'none',
    price: '',
    accounting_category: '',
  });
  ...
```

- [ ] **Step 2: Add a JobPicker to the form UI**

In the form markup, add above the submit button:

```svelte
  <p>
    <label><strong>Job (optional)</strong></label><br>
    <JobPicker bind:value={selectedJob} />
  </p>
```

- [ ] **Step 3: Include `job` / `material_id` in submit payload**

Update `handleSubmit`:

```js
  function handleSubmit(e) {
    e.preventDefault();
    const data = {};
    if (mode === 'pli' && selectedPLI) {
      data.price_list_item = selectedPLI.price_list_item_id;
      data.qty = Number(form.qty);
    } else {
      data.description = form.description;
      data.qty = Number(form.qty);
      data.units = form.units;
      data.price = form.price;
      if (form.accounting_category) {
        data.accounting_category = Number(form.accounting_category);
      }
    }
    if (selectedJob?.job_id) {
      data.job = selectedJob.job_id;
    }
    if (materialId) {
      data.material_id = materialId;
    }
    onSubmit(data);
  }
```

- [ ] **Step 4: Create `JobPicker.svelte` if it doesn't exist**

Check: `ls frontend/src/components/JobPicker.svelte`. If missing:

```svelte
<script>
  import { api } from '../lib/api.js';
  let { value = null } = $props();
  let query = $state('');
  let results = $state([]);
  let showResults = $state(false);

  async function search() {
    if (!query.trim()) { results = []; return; }
    try {
      const data = await api.get(`/api/jobs/?search=${encodeURIComponent(query)}&page_size=10`);
      results = data.results || data;
      showResults = true;
    } catch (e) { console.error(e); }
  }
  function pick(job) {
    value = { job_id: job.job_id, job_number: job.job_number };
    query = job.job_number;
    showResults = false;
  }
  function clear() { value = null; query = ''; results = []; }
</script>

{#if value}
  <span>{value.job_number} <button type="button" onclick={clear}>Clear</button></span>
{:else}
  <input type="text" bind:value={query} oninput={search} placeholder="Search jobs…">
  {#if showResults && results.length}
    <ul>
      {#each results as job}
        <li><button type="button" onclick={() => pick(job)}>{job.job_number} — {job.description?.slice(0, 40)}</button></li>
      {/each}
    </ul>
  {/if}
{/if}
```

Test the picker in the browser: navigate to `#/purchase-orders/new`, add a line item, confirm the picker shows and filters.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/purchaseorders/LineItemForm.svelte frontend/src/components/JobPicker.svelte
git commit -m "feat(frontend): add Job picker to PO LineItemForm"
```

---

## Task 20: Frontend — create `MaterialSeverDialog.svelte`

**Files:**
- Create: `frontend/src/components/purchaseorders/MaterialSeverDialog.svelte`

- [ ] **Step 1: Build the component**

Create `frontend/src/components/purchaseorders/MaterialSeverDialog.svelte`:

```svelte
<script>
  /**
   * Modal that asks the user "still needed?" for one or more linked Materials
   * about to be severed. Emits a map of {material_id: "keep"|"delete"}.
   *
   * Props:
   *   items: [{ material_id, job_number, quantity, description, line_item_id }]
   *   onSubmit: (decisions) => void   // decisions keyed by line_item_id
   *   onCancel: () => void
   */
  const { items = [], onSubmit, onCancel } = $props();
  let decisions = $state({});

  // Default every row to 'delete'
  for (const it of items) {
    decisions[it.line_item_id] = 'delete';
  }

  function submit() {
    onSubmit({ ...decisions });
  }
</script>

<div class="overlay">
  <div class="dialog">
    <h3>Linked Materials — still needed?</h3>
    <p>Each of these Materials is currently linked to a PO line you're about to sever. Decide whether the plan on the Job should stay.</p>
    <table border="1">
      <thead>
        <tr><th>Job</th><th>Material</th><th>Qty</th><th>Decision</th></tr>
      </thead>
      <tbody>
        {#each items as it}
          <tr>
            <td>{it.job_number}</td>
            <td>{it.description}</td>
            <td>{it.quantity}</td>
            <td>
              <label>
                <input type="radio" name={`d-${it.line_item_id}`} value="keep"
                       checked={decisions[it.line_item_id] === 'keep'}
                       onchange={() => { decisions[it.line_item_id] = 'keep'; }}>
                Keep on {it.job_number}
              </label>
              <label>
                <input type="radio" name={`d-${it.line_item_id}`} value="delete"
                       checked={decisions[it.line_item_id] === 'delete'}
                       onchange={() => { decisions[it.line_item_id] = 'delete'; }}>
                Delete
              </label>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    <p>
      <button onclick={submit}>Confirm</button>
      <button onclick={onCancel}>Cancel</button>
    </p>
  </div>
</div>

<style>
  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
  .dialog { background: white; padding: 20px; max-width: 600px; border-radius: 6px; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/purchaseorders/MaterialSeverDialog.svelte
git commit -m "feat(frontend): add MaterialSeverDialog component"
```

---

## Task 21: Frontend — wire sever dialog into `PurchaseOrderDetailPage.svelte`

**Files:**
- Modify: `frontend/src/routes/purchaseorders/PurchaseOrderDetailPage.svelte`
- Modify: `frontend/src/components/purchaseorders/PurchaseOrderDetail.svelte`

- [ ] **Step 1: Import the dialog in the detail page**

In `PurchaseOrderDetailPage.svelte`, add `import MaterialSeverDialog from '../../components/purchaseorders/MaterialSeverDialog.svelte';` at the top.

Add state to control it:

```js
  let severPrompt = $state(null); // { items, onSubmit } when showing
```

- [ ] **Step 2: Build a helper that collects linked pending Materials from a line set**

```js
  function collectLinkedMaterials(lines) {
    return lines
      .filter(li => li.material && li.material.consumption_state === 'pending')
      .map(li => ({
        material_id: li.material.material_id,
        line_item_id: li.line_item_id,
        job_number: li.material.job_number,
        quantity: li.material.quantity,
        description: li.description,
      }));
  }
```

- [ ] **Step 3: Override `handleCancelLineItem`, `handleCancel`, `handleDelete` to prompt when needed**

Replace the `handleCancelLineItem`, `handleCancel`, `handleDelete` functions in `PurchaseOrderDetailPage.svelte`:

```js
  async function handleCancelLineItem(lineItemId, note) {
    const line = po.line_items.find(li => li.line_item_id === lineItemId);
    const items = collectLinkedMaterials([line]);
    const doCancel = async (sever_decisions) => {
      busy = true; error = null; success = null;
      try {
        const payload = { line_item_id: lineItemId, note };
        if (sever_decisions) {
          payload.sever_decision = sever_decisions[lineItemId];
        }
        await api.post(`/api/purchase-orders/${po.po_id}/cancel-line-item/`, payload);
        success = 'Line item cancelled.';
        await reload();
      } catch (e) {
        error = e.data?.detail || e.message;
      } finally {
        busy = false; severPrompt = null;
      }
    };
    if (items.length > 0) {
      severPrompt = { items, onSubmit: doCancel };
    } else {
      doCancel(null);
    }
  }

  async function handleCancel() {
    const reason = prompt('Reason for cancellation:');
    if (!reason) return;
    const items = collectLinkedMaterials(po.line_items || []);
    const doCancelPO = async (sever_decisions) => {
      busy = true; error = null; success = null;
      try {
        const payload = { reason };
        if (sever_decisions) payload.sever_decisions = sever_decisions;
        await api.post(`/api/purchase-orders/${po.po_id}/cancel/`, payload);
        success = 'Purchase order cancelled.';
        await reload();
      } catch (e) {
        error = e.data?.detail || e.message;
      } finally {
        busy = false; severPrompt = null;
      }
    };
    if (items.length > 0) {
      severPrompt = { items, onSubmit: doCancelPO };
    } else {
      doCancelPO(null);
    }
  }

  async function handleDelete() {
    if (!confirm('Delete this purchase order? This cannot be undone.')) return;
    const items = collectLinkedMaterials(po.line_items || []);
    const doDelete = async (sever_decisions) => {
      busy = true; error = null;
      try {
        const url = `/api/purchase-orders/${po.po_id}/?confirm=true`;
        const body = sever_decisions ? { sever_decisions } : undefined;
        await api.delete(url, body);
        push('/purchase-orders');
      } catch (e) {
        error = e.data?.detail || e.message; busy = false; severPrompt = null;
      }
    };
    if (items.length > 0) {
      severPrompt = { items, onSubmit: doDelete };
    } else {
      doDelete(null);
    }
  }
```

Note: `api.delete` may need an overload to accept a body; check `frontend/src/lib/api.js` and adjust. If not supported, use `fetch` directly with a body.

- [ ] **Step 4: Render the dialog**

Before the closing of the component template, add:

```svelte
{#if severPrompt}
  <MaterialSeverDialog
    items={severPrompt.items}
    onSubmit={severPrompt.onSubmit}
    onCancel={() => { severPrompt = null; }}
  />
{/if}
```

- [ ] **Step 5: Manual verification**

Run dev servers. Create a PO with a line linked to a Material (use Order this). Issue the PO. Cancel the PO — the dialog should appear with the Material listed. Submit with Delete → Material deleted, PO cancelled. Try again with Keep → Material stays on job, unlinked.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/purchaseorders/PurchaseOrderDetailPage.svelte frontend/src/components/purchaseorders/PurchaseOrderDetail.svelte
git commit -m "feat(frontend): PO cancel/delete paths prompt for Material sever decision"
```

---

## Task 22: Frontend — inline Job picker in `PurchaseOrderDetail.svelte` edit row

**Files:**
- Modify: `frontend/src/components/purchaseorders/PurchaseOrderDetail.svelte`

- [ ] **Step 1: Import JobPicker into the detail component**

Add `import JobPicker from '../JobPicker.svelte';` at the top of the script block in `PurchaseOrderDetail.svelte`.

Extend `editForm` state to carry the job:

```js
  let editForm = $state({});
  function startEdit(li) {
    editingId = li.line_item_id;
    editForm = {
      description: li.description,
      qty: li.qty,
      units: li.units || 'none',
      price: li.price,
      job: li.effective_job_id
        ? { job_id: li.effective_job_id, job_number: li.effective_job_number }
        : null,
      _hadLinkedMaterial: !!li.material,
      _linkedMaterial: li.material,
      _lineNumber: li.line_number,
      _description: li.description,
    };
  }
```

- [ ] **Step 2: Add a JobPicker cell to the edit row**

In the edit-row `<tr>` (the `{#if editingId === li.line_item_id}` branch, around line 177-196), add a new cell or tuck the picker under the existing cells (before the Save/Cancel buttons):

```svelte
<td>
  <JobPicker bind:value={editForm.job} />
</td>
```

Ensure the Save/Cancel cell is still present.

- [ ] **Step 3: On save, dispatch the job change separately**

Update the parent page's `onEditLineItem` handler signature (`PurchaseOrderDetailPage.svelte`) to also accept a job and sever_decision. But the simplest: expose a prop `onChangeLineJob(lineItemId, newJobId, severDecision?)` and call it from `saveEdit` in `PurchaseOrderDetail.svelte`:

In `PurchaseOrderDetail.svelte`, modify `saveEdit`:

```js
  function saveEdit() {
    const original = lineItems.find(li => li.line_item_id === editingId);
    const origJobId = original?.effective_job_id ?? null;
    const newJobId = editForm.job?.job_id ?? null;
    const jobChanged = origJobId !== newJobId;

    // Field edits (draft only — guard already at button level)
    if (onEditLineItem) {
      onEditLineItem(editingId, {
        description: editForm.description,
        qty: Number(editForm.qty),
        units: editForm.units,
        price: editForm.price,
      });
    }
    if (jobChanged && onChangeLineJob) {
      onChangeLineJob(editingId, newJobId, editForm._hadLinkedMaterial ? editForm._linkedMaterial : null);
    }
    editingId = null;
    editForm = {};
  }
```

And accept the new prop:

```js
  const {
    po,
    canManageFinancials = false,
    ...
    onChangeLineJob = null,
  } = $props();
```

- [ ] **Step 4: Implement `handleChangeLineJob` in the parent page**

In `PurchaseOrderDetailPage.svelte`:

```js
  async function handleChangeLineJob(lineItemId, newJobId, existingMaterial) {
    const runPatch = async (severDecision) => {
      busy = true; error = null;
      try {
        const payload = { job: newJobId };
        if (severDecision) payload.sever_decision = severDecision;
        await api.patch(
          `/api/purchase-orders/${po.po_id}/line-items/${lineItemId}/`,
          payload,
        );
        await reload();
      } catch (e) {
        error = e.data?.detail || e.message;
      } finally {
        busy = false; severPrompt = null;
      }
    };
    if (existingMaterial) {
      severPrompt = {
        items: [{
          material_id: existingMaterial.material_id,
          line_item_id: lineItemId,
          job_number: existingMaterial.job_number,
          quantity: existingMaterial.quantity,
          description: existingMaterial.description,
        }],
        onSubmit: (decisions) => runPatch(decisions[lineItemId]),
      };
    } else {
      await runPatch(null);
    }
  }
```

Pass it to the child: `onChangeLineJob={handleChangeLineJob}`.

- [ ] **Step 5: Manual verification**

Create a draft PO with a job-linked line. Edit the line and change the Job. Confirm the dialog appears and the change applies with keep/delete.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/purchaseorders/PurchaseOrderDetail.svelte frontend/src/routes/purchaseorders/PurchaseOrderDetailPage.svelte
git commit -m "feat(frontend): inline Job picker on PO line edit with sever dialog"
```

---

## Task 23: Frontend — "Change Job" action on non-draft POs

**Files:**
- Modify: `frontend/src/components/purchaseorders/PurchaseOrderDetail.svelte`

- [ ] **Step 1: Add a button per line on issued/partly_received/received_in_full**

In the non-edit `<tr>` row (the `{:else}` branch for each line), inside the Actions cell, add (after the existing "Cancel Line" and "Reverse Receipt" buttons):

```svelte
{#if canChangeJob(li)}
  <button onclick={() => openChangeJob(li)}>Change Job</button>
{/if}
```

And helper in the script:

```js
  function canChangeJob(li) {
    // Visible only when the linked Material is pending AND PO isn't cancelled
    if (po.status === 'cancelled') return false;
    if (!li.material) return po.status === 'draft';  // draft line without Material — still editable via inline row
    return li.material.consumption_state === 'pending';
  }
  function openChangeJob(li) {
    changeJobLine = li;
    changeJobPick = li.effective_job_id
      ? { job_id: li.effective_job_id, job_number: li.effective_job_number }
      : null;
  }
  let changeJobLine = $state(null);
  let changeJobPick = $state(null);
```

- [ ] **Step 2: Add a small modal for the Job picker**

At the bottom of the template, add:

```svelte
{#if changeJobLine}
  <div class="overlay">
    <div class="dialog">
      <h3>Change Job for Line #{changeJobLine.line_number}</h3>
      <JobPicker bind:value={changeJobPick} />
      <p>
        <button onclick={() => {
          if (onChangeLineJob) {
            onChangeLineJob(changeJobLine.line_item_id, changeJobPick?.job_id ?? null, changeJobLine.material);
          }
          changeJobLine = null;
        }}>Save</button>
        <button onclick={() => { changeJobLine = null; }}>Cancel</button>
      </p>
    </div>
  </div>
{/if}
```

Reuse the overlay CSS from the sever dialog or add inline.

- [ ] **Step 3: Manual verification**

Issue a PO with a job-linked line. On the issued PO detail, verify the "Change Job" button appears on the line. Click, pick a different job, then pick delete/keep in the sever dialog, confirm the change.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/purchaseorders/PurchaseOrderDetail.svelte
git commit -m "feat(frontend): add Change Job action on non-draft PO lines"
```

---

## Task 24: Frontend — "Create PO for this job" + "Order" on Job Materials

**Files:**
- Modify: `frontend/src/components/jobs/JobDetail.svelte` (action bar + Materials section)

- [ ] **Step 1: Add "Create PO for this job" button in action bar**

In `JobDetail.svelte`, locate where the action buttons for the job are rendered. Add (behind `canManageFinancials`):

```svelte
{#if canManageFinancials}
  <a href="#/purchase-orders/new?job={job.job_id}"><button>Create PO for this job</button></a>
{/if}
```

If the component doesn't currently have a `canManageFinancials` prop, accept it and thread it from the parent page (`JobDetailPage.svelte`).

- [ ] **Step 2: Add "Order" button and PO badge to Material rows**

Find where Material rows render on the job page. For each pending Material, add:

```svelte
{#if mat.po_line_item_id}
  <span class="po-badge">
    Ordered on <a href="#/purchase-orders/{mat.po_line_item.purchase_order_id || /* derived */ ''}">{mat.po_number}</a>
    · {mat.po_status}
  </span>
{:else if mat.consumption_state === 'pending' && canManageFinancials}
  <a href="#/purchase-orders/new?job={job.job_id}&material={mat.material_id}">
    <button>Order</button>
  </a>
{/if}
```

Note: the payload from Task 17 gave `po_line_item_id`, `po_number`, `po_status`. The PO href needs the PO id; either extend the serializer (Task 17) with `po_id` too, or fetch via `po_line_item_id`. Simplest: extend the serializer to include `po_id`. Go back to Task 17's serializer and add:

```python
    po_id = serializers.SerializerMethodField()
    ...
    def get_po_id(self, obj):
        if obj.po_line_item_id and obj.po_line_item:
            return obj.po_line_item.purchase_order_id
        return None
```

Add `'po_id'` to `fields`. Update the Svelte to use `mat.po_id`.

- [ ] **Step 3: Manual verification**

On a job with a pending Material linked to a PO, verify the badge shows. On a pending unlinked Material, the Order button shows. On a consumed Material, neither shows.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/jobs/JobDetail.svelte apps/api/jobs/serializers.py
git commit -m "feat(frontend): add Create PO and Order-this actions on Job page"
```

---

## Task 25: Frontend — PO create page handles `?job` and `?material` params

**Files:**
- Modify: `frontend/src/routes/purchaseorders/PurchaseOrderFormPage.svelte`
- Modify: `frontend/src/routes/purchaseorders/PurchaseOrderDetailPage.svelte` (if line-item form needs defaults)
- Modify: `frontend/src/components/purchaseorders/PurchaseOrderForm.svelte` (header)

- [ ] **Step 1: Read `?job` and `?material` on mount**

In `PurchaseOrderFormPage.svelte`, read query params:

```js
  import { querystring } from 'svelte-spa-router';
  const params = new URLSearchParams($querystring);
  const contextJobId = params.get('job');
  const contextMaterialId = params.get('material');
  let contextJob = $state(null);
  let contextMaterial = $state(null);

  $effect(async () => {
    if (contextJobId) {
      contextJob = await api.get(`/api/jobs/${contextJobId}/`);
    }
    if (contextMaterialId) {
      try {
        contextMaterial = await api.get(`/api/materials/${contextMaterialId}/`);
      } catch {
        contextMaterial = null;
      }
    }
  });
```

(Adjust the materials endpoint URL if different. If there's no direct GET for a single Material, fetch the job's materials and filter.)

- [ ] **Step 2: Show "For job JOB-XXXX" header on the form**

In `PurchaseOrderForm.svelte`, accept a `contextJob` prop and render the header when present:

```svelte
{#if contextJob}
  <p><strong>For job: <a href="#/jobs/{contextJob.job_id}">{contextJob.job_number}</a></strong></p>
{/if}
```

Thread from the form page.

- [ ] **Step 3: Pre-fill the first line item from the material**

After creating the draft PO (existing flow posts to `/api/purchase-orders/` and redirects to detail), the detail page handles line-item creation. Adjust so that when `contextMaterial` is set, the first line-item form opens pre-populated. Add a prop to `PurchaseOrderDetailPage.svelte` or pass through navigation state.

Simplest: after `PurchaseOrderForm.svelte` creates the PO, navigate to `#/purchase-orders/{id}?prefill_material={material_id}&default_job={job_id}`. Then `PurchaseOrderDetailPage.svelte` reads those params and opens the add-line form with defaults.

In `PurchaseOrderDetailPage.svelte`:

```js
  const params = new URLSearchParams($querystring);
  const prefillMaterialId = params.get('prefill_material');
  const defaultJobId = params.get('default_job');
  // After loading PO, if prefill_material set, fetch material and open LineItemForm with defaults:
  $effect(async () => {
    if (prefillMaterialId && po) {
      const mat = await api.get(`/api/materials/${prefillMaterialId}/`);
      showAddLineItem = true;
      prefilledLine = { /* description, qty, units, price, pli */ };
      prefilledMaterialId = mat.material_id;
    }
  });
```

And pass `defaultJob` and `materialId` to `LineItemForm.svelte` (already supports these props from Task 19).

- [ ] **Step 4: Manual verification**

From a job, click Order on a pending Material. Verify PO create form shows "For job JOB-XXXX". Submit → PO detail opens with first line form pre-populated from the Material. Add line → verify the line is linked to the Material (green badge on the Material row on the job page).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/purchaseorders/ frontend/src/components/purchaseorders/
git commit -m "feat(frontend): PO create handles ?job and ?material context"
```

---

## Task 26: Manual verification against the design's scenarios

**Files:** none (manual testing + fixups)

- [ ] **Step 1: Pull up the design's manual-verification scripts**

Open `docs/designs/2026-04-17-po-job-material-integration.md` and locate the "Manual verification script" section. It has scenarios 1 through 12.

- [ ] **Step 2: Run each scenario in order**

For each scenario (1, 2, 3, 4, 5, 6, 7, 8, 8b, 9, 10, 11, 12):

- Follow every step exactly.
- Use `python manage.py shell` for the shell verifications noted in steps.
- Record any deviation between observed and expected behavior.

- [ ] **Step 3: File bugs for deviations**

If any scenario fails:
- Capture the exact steps, observed output, and expected output.
- Stop and fix the underlying code (backend or frontend). Write a regression test before fixing.
- Re-run the scenario.

Do not declare the feature complete until all 12 scenarios pass in full.

- [ ] **Step 4: Run the full automated test suite**

Run: `python manage.py test -v 1`
Expected: all tests pass.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix(po-job-material): resolve issues found in manual verification"
```

Skip this commit if nothing needed fixing.

---

## Task 27: Documentation touch-ups

**Files:**
- Modify: `CLAUDE.md` (if PO/Inventory sections reference the old `Line.job` mechanism)
- Modify: `docs/designs/2026-04-06-purchasing-workflow-design.md` (add a note pointing to this design)

- [ ] **Step 1: Search CLAUDE.md for stale references**

Run: `grep -n "purchaseorderlineitem__job\|PurchaseOrderLineItem.*job" CLAUDE.md`
Expected: no or few hits. If any functional description mentions Line.job as the attribution mechanism, update it to reference `Material.po_line_item`.

Relevant sections to scan: Purchasing, Inventory, Business Workflows.

- [ ] **Step 2: Cross-reference older purchasing design**

In `docs/designs/2026-04-06-purchasing-workflow-design.md`, add a short note at the top:

```markdown
> **Superseded in part by `2026-04-17-po-job-material-integration.md`** — Job attribution on PO lines now flows through `Material.po_line_item` (created at line-add time), not `PurchaseOrderLineItem.job`. The rest of this document (receiving, cancellation, reversal) is still current.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/designs/2026-04-06-purchasing-workflow-design.md
git commit -m "docs: update CLAUDE.md and cross-reference older purchasing design"
```

---

## Completion checklist

Before declaring done:

- [ ] All automated tests pass: `python manage.py test -v 1`
- [ ] All 12 manual scenarios in the design pass
- [ ] `grep -rn "purchaseorderlineitem__job\|\.job\b" apps/ frontend/src/` turns up only unrelated matches (e.g., `Job.objects...job_id`, `task.job`, `material.job`, etc.)
- [ ] No orphaned helpers or dead code
- [ ] CLAUDE.md reflects the current model
- [ ] Frontend no longer reads `li.job` anywhere

When the whole sequence is green, share the branch diff and a brief writeup of which scenarios ran clean.

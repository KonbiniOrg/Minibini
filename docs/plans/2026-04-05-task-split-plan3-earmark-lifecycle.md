# Plan 3: Earmark Lifecycle Relocation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move earmark creation from the `estimate_accepted` signal to WorkOrder creation time, rewrite `get_earmark_preview` to query WO-side Materials, and add earmark release on WO completion.

**Architecture:** Three changes: (1) `InventoryService.get_earmark_preview` switches from querying `PlanMaterial` to querying `Material` on the WO. (2) A new `InventoryService.create_earmarks_for_work_order(wo)` method runs as a hook at the end of each `WorkOrderService` creation path. (3) The `auto_earmark_inventory` signal handler is deleted. (4) `WorkOrderService.update_status` releases remaining earmarks when a WO reaches COMPLETE. All three WO creation workflows now produce correct earmarks; previously only workflow 3 (via the estimate-acceptance signal) did.

**Tech Stack:** Django 5.2, DRF, Python 3.12, MySQL.

**Spec:** `docs/designs/2026-04-05-task-split-and-worksheet-to-workorder.md` — section "Earmark Lifecycle".

**Depends on:** Plan 1 + Plan 2 on branch `feature/worksheet-to-workorder`.

---

## File Structure

**Files to modify:**

- `apps/inventory/services.py` — rewrite `get_earmark_preview` to query Material (WO-side); add `create_earmarks_for_work_order(wo)` convenience method; add `release_earmarks_for_job(job)` method
- `apps/jobs/services/__init__.py` — add earmark hook call at the end of `create_from_estimate`, `create_from_template`, `copy_from_worksheet`; add earmark release in `update_status` when WO reaches COMPLETE
- `apps/estimates/signals.py` — delete `auto_earmark_inventory` handler
- `tests/test_earmark_flow.py` — rewrite `get_earmark_preview` tests to set up WO-side Materials instead of PlanMaterials
- `tests/test_auto_earmark.py` — rewrite: earmarks created on WO creation (not estimate acceptance)

**Files NOT modified:**

- `apps/inventory/models.py` — Earmark model unchanged
- `apps/estimates/models.py` — `estimate_accepted` signal dispatch stays (other listeners may use it); only the earmark handler is removed
- `apps/inventory/services.py` `consume_material` — already works correctly (queries `material.task.work_order.job` after Plan 1)
- `apps/inventory/services.py` `receive_po_line_item` — unchanged (PO receipt earmarks are a separate flow keyed on PO line items, not Materials)

---

## Phase 1: Rewrite `get_earmark_preview` to query WO-side Materials

### Task 1.1: Update `get_earmark_preview` and its tests

**Files:**
- Modify: `apps/inventory/services.py:182-206`
- Modify: `tests/test_earmark_flow.py:16-165`

- [ ] **Step 1: Rewrite the tests to use WO-side Materials**

The current `EarmarkPreviewTest` in `tests/test_earmark_flow.py` creates `PlanTask` + `PlanMaterial` on a worksheet. After this change, the preview queries `Material` on Tasks on WorkOrders. Rewrite the setUp and all test methods.

Replace the entire `EarmarkPreviewTest` class (lines 16-165) with:

```python
class EarmarkPreviewTest(TestCase):
    """Tests for InventoryService.get_earmark_preview() — queries WO-side Materials."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

        self.job = Job.objects.create(
            job_number='J-EMK-001', contact=self.contact, description='Earmark Job',
        )
        self.work_order = WorkOrder.objects.create(job=self.job)

        self.plywood = PriceListItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheets',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            is_inventoried=True,
        )
        self.screws = PriceListItem.objects.create(
            code='SCR.100',
            description='Wood Screws Box of 100',
            units='ea',
            qty_on_hand=Decimal('50.00'),
            purchase_price=Decimal('8.00'),
            selling_price=Decimal('12.00'),
            is_inventoried=True,
        )

        self.task_a = Task.objects.create(
            work_order=self.work_order,
            name='Build cabinets',
            sort_order=1,
        )
        self.task_b = Task.objects.create(
            work_order=self.work_order,
            name='Install trim',
            sort_order=2,
        )

    def test_preview_aggregates_by_item(self):
        """Preview aggregates material quantities by price list item across tasks."""
        Material.objects.create(
            task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        Material.objects.create(
            task=self.task_b, price_list_item=self.plywood,
            quantity=Decimal('3.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(len(preview), 1)
        self.assertEqual(preview[0]['price_list_item'], self.plywood)
        self.assertEqual(preview[0]['needed_qty'], Decimal('8.00'))

    def test_preview_shows_available_qty(self):
        Material.objects.create(
            task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(preview[0]['available_qty'], Decimal('20.00'))

    def test_preview_shows_shortfall(self):
        Material.objects.create(
            task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('25.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(preview[0]['shortfall'], Decimal('5.00'))

    def test_preview_no_shortfall_when_sufficient(self):
        Material.objects.create(
            task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(preview[0]['shortfall'], Decimal('0.00'))

    def test_preview_multiple_items(self):
        Material.objects.create(
            task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        Material.objects.create(
            task=self.task_a, price_list_item=self.screws,
            quantity=Decimal('2.00'), unit_cost=Decimal('8.00'), sell_price=Decimal('12.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(len(preview), 2)
        items = {p['price_list_item']: p for p in preview}
        self.assertEqual(items[self.plywood]['needed_qty'], Decimal('5.00'))
        self.assertEqual(items[self.screws]['needed_qty'], Decimal('2.00'))

    def test_preview_accounts_for_existing_earmarks(self):
        other_job = Job.objects.create(
            job_number='J-EMK-002', contact=self.contact, description='Other Job',
        )
        Earmark.objects.create(
            price_list_item=self.plywood, job=other_job, quantity=Decimal('15.00'),
        )
        Material.objects.create(
            task=self.task_a, price_list_item=self.plywood,
            quantity=Decimal('10.00'), unit_cost=Decimal('45.00'), sell_price=Decimal('90.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(preview[0]['available_qty'], Decimal('5.00'))
        self.assertEqual(preview[0]['shortfall'], Decimal('5.00'))

    def test_preview_empty_when_no_inventoried_materials(self):
        Material.objects.create(
            task=self.task_a,
            description='Custom brackets',
            quantity=Decimal('5.00'), unit_cost=Decimal('10.00'), sell_price=Decimal('20.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(len(preview), 0)

    def test_preview_ignores_non_inventoried_pli(self):
        non_inv = PriceListItem.objects.create(
            code='NONINV', description='Not tracked', is_inventoried=False,
        )
        Material.objects.create(
            task=self.task_a, price_list_item=non_inv,
            quantity=Decimal('5.00'), unit_cost=Decimal('10.00'), sell_price=Decimal('20.00'),
        )
        preview = InventoryService.get_earmark_preview(self.job)
        self.assertEqual(len(preview), 0)
```

Update the imports at the top of the file — add `WorkOrder`, `Task`, `Material` and remove `PlanTask`, `PlanMaterial`:

```python
from apps.jobs.models import Job, WorkOrder, Task
from apps.inventory.models import Material, PriceListItem, Earmark
from apps.inventory.services import InventoryService
```

Remove the `EstWorksheet` import if present.

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_earmark_flow.EarmarkPreviewTest -v 2 2>&1 | tail -20
```

Expected: failures because `get_earmark_preview` still queries PlanMaterial.

- [ ] **Step 3: Rewrite `get_earmark_preview` in `apps/inventory/services.py`**

Replace the method body (lines 182-206):

```python
    @staticmethod
    def get_earmark_preview(job):
        """Get preview of inventoried items needed for a job's work order materials.

        Aggregates by price_list_item across all Materials on all WorkOrders
        for this job. Returns list of dicts with price_list_item, needed_qty,
        available_qty, shortfall.
        """
        from apps.inventory.models import Material

        materials = Material.objects.filter(
            task__work_order__job=job,
            price_list_item__is_inventoried=True,
        ).values('price_list_item').annotate(
            total_qty=Sum('quantity'),
        )

        preview = []
        for entry in materials:
            item = PriceListItem.objects.get(pk=entry['price_list_item'])
            needed = entry['total_qty']
            available = item.qty_available
            shortfall = max(needed - available, Decimal('0.00'))
            preview.append({
                'price_list_item': item,
                'needed_qty': needed,
                'available_qty': available,
                'shortfall': shortfall,
            })
        return preview
```

Remove the `PlanMaterial` import from the top of `apps/inventory/services.py` if `get_earmark_preview` was the only consumer. Grep first:

```bash
grep -n "PlanMaterial" apps/inventory/services.py
```

If only used in `get_earmark_preview`, remove the import.

- [ ] **Step 4: Run tests**

```bash
python manage.py test tests.test_earmark_flow.EarmarkPreviewTest -v 2 2>&1 | tail -20
```

Expected: all 8 preview tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/services.py tests/test_earmark_flow.py
git commit -m "$(cat <<'EOF'
refactor: rewrite get_earmark_preview to query WO-side Materials

Switches from PlanMaterial (worksheet) to Material (work order).
Earmark preview now reflects actual materials on work orders,
not planning estimates. Part of earmark lifecycle relocation.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2: Earmark creation hook on WO creation

### Task 2.1: Add `create_earmarks_for_work_order` and hook it into WO creation

**Files:**
- Modify: `apps/inventory/services.py`
- Modify: `apps/jobs/services/__init__.py:54-169`
- Modify: `tests/test_auto_earmark.py`

- [ ] **Step 1: Rewrite `tests/test_auto_earmark.py` — earmarks on WO creation, not estimate acceptance**

Replace the entire file with:

```python
"""
Tests for automatic earmarking when a WorkOrder is created.

After Plan 3, earmarks are created at WO creation time (not on
estimate acceptance). The trigger is inside WorkOrderService's
creation methods, which call InventoryService.create_earmarks_for_work_order().
"""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, WorkOrder, Task, PlanTask
from apps.estimates.models import (
    Estimate, EstimateLineItem, EstWorksheet, WorkOrderTemplate,
    TaskTemplate, TemplateTaskAssociation,
)
from apps.inventory.models import Material, PlanMaterial, PriceListItem, Earmark
from apps.jobs.services import WorkOrderService


class EarmarkOnCopyFromWorksheetTest(TestCase):
    """Earmarks created when WO is created via copy_from_worksheet (workflow 3)."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='J-AEM-001', contact=self.contact,
        )
        self.plywood = PriceListItem.objects.create(
            code='PLY.75', description='Plywood',
            units='sheets', qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'), selling_price=Decimal('90.00'),
            is_inventoried=True,
        )
        self.screws = PriceListItem.objects.create(
            code='SCR.100', description='Screws',
            units='ea', qty_on_hand=Decimal('50.00'),
            purchase_price=Decimal('8.00'), selling_price=Decimal('12.00'),
            is_inventoried=True,
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Build cabinets', sort_order=1,
        )

    def test_earmarks_created_on_copy_from_worksheet(self):
        PlanMaterial.objects.create(
            plan_task=self.plan_task, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        PlanMaterial.objects.create(
            plan_task=self.plan_task, price_list_item=self.screws,
            quantity=Decimal('2.00'), unit_cost=Decimal('8.00'),
            sell_price=Decimal('12.00'),
        )

        wo = WorkOrderService.create_direct(self.job)
        WorkOrderService.copy_from_worksheet(wo.pk, self.worksheet.pk)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 2)
        self.assertEqual(
            Earmark.objects.get(price_list_item=self.plywood, job=self.job).quantity,
            Decimal('5.00'),
        )
        self.assertEqual(
            Earmark.objects.get(price_list_item=self.screws, job=self.job).quantity,
            Decimal('2.00'),
        )

    def test_aggregates_across_tasks(self):
        plan_task_b = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Install trim', sort_order=2,
        )
        PlanMaterial.objects.create(
            plan_task=self.plan_task, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        PlanMaterial.objects.create(
            plan_task=plan_task_b, price_list_item=self.plywood,
            quantity=Decimal('3.00'), unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )

        wo = WorkOrderService.create_direct(self.job)
        WorkOrderService.copy_from_worksheet(wo.pk, self.worksheet.pk)

        earmark = Earmark.objects.get(price_list_item=self.plywood, job=self.job)
        self.assertEqual(earmark.quantity, Decimal('8.00'))

    def test_no_earmarks_without_inventoried_materials(self):
        PlanMaterial.objects.create(
            plan_task=self.plan_task,
            description='Custom brackets',
            quantity=Decimal('5.00'), unit_cost=Decimal('10.00'),
            sell_price=Decimal('20.00'),
        )

        wo = WorkOrderService.create_direct(self.job)
        WorkOrderService.copy_from_worksheet(wo.pk, self.worksheet.pk)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)

    def test_no_earmarks_when_no_materials(self):
        wo = WorkOrderService.create_direct(self.job)
        WorkOrderService.copy_from_worksheet(wo.pk, self.worksheet.pk)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)


class EarmarkOnCreateFromTemplateTest(TestCase):
    """Earmarks created (if any materials exist) after create_from_template."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='J-AEM-002', contact=self.contact,
        )
        from apps.core.models import AccountingCategory
        cat = AccountingCategory.objects.create(name='Labor')
        self.template = WorkOrderTemplate.objects.create(
            template_name='Quick', is_active=True,
        )
        tt = TaskTemplate.objects.create(
            template_name='Countertop', is_active=True,
            units='each', rate=100, accounting_category=cat,
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=self.template,
            task_template=tt, est_qty=1, sort_order=1,
        )

    def test_no_earmarks_from_template_with_no_materials(self):
        """Template → WO has no materials, so no earmarks."""
        wo = WorkOrderService.create_from_template(self.template, self.job)
        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)


class EarmarkOnCreateFromEstimateTest(TestCase):
    """Earmarks created (if any materials copy over) after create_from_estimate."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='J-AEM-003', contact=self.contact,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-AEM-001', version=1,
        )

    def test_no_earmarks_from_estimate_with_no_materials(self):
        """Estimate → WO with no task materials produces no earmarks."""
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Manual item',
            price=Decimal('100.00'),
        )
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()

        wo = WorkOrderService.create_from_estimate(self.estimate)
        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)


class EstimateAcceptanceNoLongerCreatesEarmarksTest(TestCase):
    """Verify that the old estimate_accepted signal no longer creates earmarks."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='J-AEM-004', contact=self.contact,
        )
        self.plywood = PriceListItem.objects.create(
            code='PLY.99', description='Plywood',
            units='sheets', qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'), selling_price=Decimal('90.00'),
            is_inventoried=True,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-AEM-005', version=1,
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, estimate=self.estimate, version=1,
        )
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Build stuff', sort_order=1,
        )
        PlanMaterial.objects.create(
            plan_task=self.plan_task, price_list_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )

    def test_accepting_estimate_does_not_create_earmarks(self):
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Test item',
            price=Decimal('100.00'),
        )
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_auto_earmark -v 2 2>&1 | tail -20
```

Expected: `test_earmarks_created_on_copy_from_worksheet` fails (no earmark hook yet); `test_accepting_estimate_does_not_create_earmarks` fails (old signal still fires).

- [ ] **Step 3: Add `create_earmarks_for_work_order` to `InventoryService`**

In `apps/inventory/services.py`, add after the existing `create_earmarks_for_job` method:

```python
    @staticmethod
    def create_earmarks_for_work_order(work_order):
        """Create earmarks from a WorkOrder's Materials.

        Aggregates inventoried Materials by PLI across all Tasks on the WO,
        then upserts Earmark records for the job. Called as a hook after
        each WO creation path.
        """
        from apps.inventory.models import Material

        job = work_order.job
        materials = Material.objects.filter(
            task__work_order=work_order,
            price_list_item__is_inventoried=True,
        ).values('price_list_item').annotate(
            total_qty=Sum('quantity'),
        )

        if not materials:
            return

        earmark_data = [
            {
                'price_list_item_id': entry['price_list_item'],
                'quantity': entry['total_qty'],
            }
            for entry in materials
        ]
        InventoryService.create_earmarks_for_job(job, earmark_data)
```

- [ ] **Step 4: Hook into `WorkOrderService.copy_from_worksheet`**

In `apps/jobs/services/__init__.py`, at the end of `copy_from_worksheet` (after the `for pm in plan_task.plan_materials.all()` loop finishes), add:

```python
        from apps.inventory.services import InventoryService
        InventoryService.create_earmarks_for_work_order(wo)
```

The full method ending should look like:

```python
        for plan_task in PlanTask.objects.filter(
            est_worksheet=ws
        ).prefetch_related('plan_materials'):
            new_task = Task.objects.create(
                work_order=wo,
                name=plan_task.name,
                description=plan_task.description,
                units=plan_task.units,
                rate=plan_task.rate,
                est_qty=plan_task.est_qty,
                accounting_category=plan_task.accounting_category,
                sort_order=plan_task.sort_order,
            )
            for pm in plan_task.plan_materials.all():
                Material.objects.create(
                    task=new_task,
                    description=pm.description,
                    quantity=pm.quantity,
                    unit_cost=pm.unit_cost,
                    sell_price=pm.sell_price,
                    price_list_item=pm.price_list_item,
                    accounting_category=pm.accounting_category,
                )

        from apps.inventory.services import InventoryService
        InventoryService.create_earmarks_for_work_order(wo)
```

- [ ] **Step 5: Hook into `WorkOrderService.create_from_estimate`**

At the end of `create_from_estimate`, before `return work_order`:

```python
        from apps.inventory.services import InventoryService
        InventoryService.create_earmarks_for_work_order(work_order)

        return work_order
```

- [ ] **Step 6: Hook into `WorkOrderService.create_from_template`**

At the end of `create_from_template`, before `return work_order`:

```python
        from apps.inventory.services import InventoryService
        InventoryService.create_earmarks_for_work_order(work_order)

        return work_order
```

- [ ] **Step 7: Delete the `auto_earmark_inventory` signal handler**

In `apps/estimates/signals.py`, delete lines 117-135 (the `@receiver(estimate_accepted)` handler and the `auto_earmark_inventory` function). Keep the `estimate_accepted` signal definition on line 12 — it may be used by other listeners in the future and removing the signal itself would require changes to `Estimate.save()`.

- [ ] **Step 8: Run the new earmark tests**

```bash
python manage.py test tests.test_auto_earmark -v 2 2>&1 | tail -20
```

Expected: all 7 tests pass.

- [ ] **Step 9: Run the earmark flow tests**

```bash
python manage.py test tests.test_earmark_flow -v 2 2>&1 | tail -20
```

Expected: all tests pass (preview tests from Phase 1 + create tests unchanged).

- [ ] **Step 10: Commit**

```bash
git add apps/inventory/services.py apps/jobs/services/__init__.py apps/estimates/signals.py tests/test_auto_earmark.py
git commit -m "$(cat <<'EOF'
feat: move earmark creation from estimate_accepted to WO creation

All three WO creation paths (template, estimate, worksheet) now
call InventoryService.create_earmarks_for_work_order() after
creating tasks/materials. The auto_earmark_inventory signal
handler on estimate_accepted is deleted.

Fixes: workflows 1 (template) and 2 (estimate) previously
produced zero earmarks; now all three workflows earmark correctly.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3: Earmark release on WO completion

### Task 3.1: Add `release_earmarks_for_job` and hook into WO completion

**Files:**
- Modify: `apps/inventory/services.py`
- Modify: `apps/jobs/services/__init__.py`
- Create or modify: `tests/test_earmark_release.py`

- [ ] **Step 1: Write the tests**

Create `tests/test_earmark_release.py`:

```python
"""
Tests for earmark release when a WorkOrder is completed.
"""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.jobs.models import Job, WorkOrder, Task
from apps.jobs.services import WorkOrderService
from apps.inventory.models import Material, PriceListItem, Earmark


class EarmarkReleaseOnWOCompleteTest(TestCase):

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(
            job_number='J-REL-001', contact=self.contact,
        )
        self.plywood = PriceListItem.objects.create(
            code='PLY.REL', description='Plywood',
            units='sheets', qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'), selling_price=Decimal('90.00'),
            is_inventoried=True,
        )

    def test_earmarks_released_on_wo_complete(self):
        """Remaining earmarks for the job are deleted when WO is completed."""
        wo = WorkOrder.objects.create(job=self.job)
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job,
            quantity=Decimal('3.00'),
        )
        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 1)

        WorkOrderService.update_status(wo.pk, WorkOrder.STATUS_COMPLETE)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)

    def test_partial_earmark_released_on_complete(self):
        """Even partially consumed earmarks are cleaned up."""
        wo = WorkOrder.objects.create(job=self.job)
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job,
            quantity=Decimal('1.50'),
        )

        WorkOrderService.update_status(wo.pk, WorkOrder.STATUS_COMPLETE)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)

    def test_no_error_when_no_earmarks_on_complete(self):
        """Completing a WO with no earmarks doesn't error."""
        wo = WorkOrder.objects.create(job=self.job)

        WorkOrderService.update_status(wo.pk, WorkOrder.STATUS_COMPLETE)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)

    def test_other_job_earmarks_untouched(self):
        """Completing one job's WO doesn't affect another job's earmarks."""
        other_job = Job.objects.create(
            job_number='J-REL-002', contact=self.contact,
        )
        Earmark.objects.create(
            price_list_item=self.plywood, job=other_job,
            quantity=Decimal('5.00'),
        )
        wo = WorkOrder.objects.create(job=self.job)
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job,
            quantity=Decimal('3.00'),
        )

        WorkOrderService.update_status(wo.pk, WorkOrder.STATUS_COMPLETE)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 0)
        self.assertEqual(Earmark.objects.filter(job=other_job).count(), 1)

    def test_blocking_wo_does_not_release_earmarks(self):
        """Blocking a WO does NOT release earmarks — only completion does."""
        wo = WorkOrder.objects.create(job=self.job)
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job,
            quantity=Decimal('3.00'),
        )

        WorkOrderService.update_status(wo.pk, WorkOrder.STATUS_BLOCKED)

        self.assertEqual(Earmark.objects.filter(job=self.job).count(), 1)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_earmark_release -v 2 2>&1 | tail -20
```

Expected: `test_earmarks_released_on_wo_complete` fails (earmarks not deleted).

- [ ] **Step 3: Add `release_earmarks_for_job` to `InventoryService`**

In `apps/inventory/services.py`, add:

```python
    @staticmethod
    def release_earmarks_for_job(job):
        """Delete all remaining earmarks for a job.

        Called when a WorkOrder is completed — any un-consumed earmark
        balance is released back to general inventory availability.
        """
        Earmark.objects.filter(job=job).delete()
```

- [ ] **Step 4: Hook into `WorkOrderService.update_status`**

In `apps/jobs/services/__init__.py`, update the `update_status` method. After `wo.save()`, add the earmark release check:

```python
    @staticmethod
    def update_status(pk, new_status):
        """Update work order status."""
        try:
            wo = WorkOrder.objects.get(pk=pk)
        except WorkOrder.DoesNotExist:
            raise NotFoundError(f'WorkOrder {pk} not found')
        wo.status = new_status
        wo.full_clean()
        wo.save()

        # Release remaining earmarks when WO completes
        if new_status == WorkOrder.STATUS_COMPLETE:
            from apps.inventory.services import InventoryService
            InventoryService.release_earmarks_for_job(wo.job)

        return wo
```

- [ ] **Step 5: Run tests**

```bash
python manage.py test tests.test_earmark_release -v 2 2>&1 | tail -10
```

Expected: all 5 pass.

- [ ] **Step 6: Commit**

```bash
git add apps/inventory/services.py apps/jobs/services/__init__.py tests/test_earmark_release.py
git commit -m "$(cat <<'EOF'
feat: release earmarks on WorkOrder completion

When a WO reaches STATUS_COMPLETE, all remaining earmarks for the
job are deleted, freeing the reserved inventory. Blocking a WO
does not release earmarks — only completion does.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4: Final checkpoint

### Task 4.1: Full test suite run

**Files:** none

- [ ] **Step 1: Run the full test suite**

```bash
python manage.py test 2>&1 | tail -10
```

Expected: all tests pass. Count should be >= 2074 (Plan 2 baseline). Some old `test_auto_earmark` tests were replaced (6 old → 7 new), and new `test_earmark_release` tests add 5, so expect ~2080.

- [ ] **Step 2: Verify no migration changes**

```bash
python manage.py makemigrations --check --dry-run --skip-checks
```

Expected: "No changes detected" (no model changes in Plan 3).

- [ ] **Step 3: Review commit log**

```bash
git log --oneline main..HEAD
```

Plan 3 commits should include:
1. `refactor: rewrite get_earmark_preview to query WO-side Materials`
2. `feat: move earmark creation from estimate_accepted to WO creation`
3. `feat: release earmarks on WorkOrder completion`

---

## Completion Criteria

Plan 3 is complete when:

1. `InventoryService.get_earmark_preview(job)` queries `Material` (WO-side), not `PlanMaterial`.
2. All three WO creation paths (`create_from_template`, `create_from_estimate`, `copy_from_worksheet`) call `create_earmarks_for_work_order()` after creating tasks/materials.
3. The `auto_earmark_inventory` signal handler in `apps/estimates/signals.py` is deleted.
4. Accepting an estimate no longer creates earmarks.
5. Completing a WO releases remaining earmarks for the job.
6. PO-received earmarks (`receive_po_line_item`) are unchanged.
7. `consume_material` earmark drawdown is unchanged.
8. All existing tests pass; new test count >= 2074.

## What's Explicitly NOT in Plan 3

- Earmark release on **job** cancellation (Job.STATUS_CANCELLED). WO doesn't have a cancelled status; job cancellation is a broader lifecycle concern not scoped to this refactor.
- Earmark release on WO **deletion**. Django CASCADE on the Job FK handles Earmark cleanup if a Job is deleted; WO deletion is not a standard workflow.
- Per-WO earmarks (earmarks remain keyed by `(PLI, Job)`, not `(PLI, WorkOrder)`). A job with multiple WOs shares a single earmark pool.
- Prompted WO creation after estimate acceptance (UX improvement suggested in the spec's "timing trade-off" section).

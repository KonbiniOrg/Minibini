# PO Order Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three one-click "order" entry points with one Order modal that knows the item's vendor history, carries a vendor SKU on PO lines, lets the PO add-line form attach to a specific pending material, and opens PO creation and PO-level writes to the jobs atom and linked project managers.

**Architecture:** Backend first (schema, a read-only vendor-history endpoint, a new request contract on the two order actions and the email create-PO action, two resolver guards, three permission composites), each slice landing with its Django tests. Then the SPA: a `VendorPicker` (recent-vendors select that flips to the existing `BusinessPicker`), an `OrderModal` with three sources (`material`, `item`, `email`) that creates nothing until Submit, a material radio list on `LineItemForm`, Code/SKU columns on the PO table and PDF, and button gating moved to `can_manage` flags. One Playwright spec and the durable-doc updates close it out.

**Tech Stack:** Django 5.2 / DRF (services in `apps/*/services.py`, viewsets in `apps/api/*`), MySQL, Svelte 5 runes SPA (Vite, svelte-spa-router, Vitest + @testing-library/svelte), Playwright e2e, WeasyPrint PDF.

**Spec:** `docs/plans/2026-10-14-po-order-flow.md` — read it first; section numbers below (§3, §4.2, §5.1 …) refer to it.

## Global Constraints

- Branch: **`feature/po-flows`**. Every task commits on it. Never merge, push, or open a PR (RM reviews in the browser).
- **Never write to the dev database.** No `migrate`, no `shell` ORM writes, no `loaddata`. `makemigrations` is fine. Tests use Django's throwaway test DB.
- Django tests: `python manage.py test <module> --noinput`, **foreground**, one run at a time, never from parallel agents, never piped (read the `OK` / `FAILED` line yourself). Targeted modules per task; the full suite runs once in Task 13 **without `--keepdb`** (Task 1 adds a migration).
- Vitest: `cd frontend && npm run test:run [path]` (never watch mode). Whole suite must be green at the end of every frontend task.
- Error contract (architecture doc §3.9): services raise `ValidationError({'field': ['msg']})` for input-field problems, `ValidationError('sentence')` otherwise; views never re-render a caught `ValidationError`; the frontend routes every error through `triageError`.
- Never call `.delete()` on a line item outside `LineItemService.delete_line_item_with_renumber`; never `QuerySet.update()` on fields `save()` normalizes (test fixtures that flip PO `status` with `.update()` follow the existing precedent in `tests/test_stock_order.py` and are the only exception).
- Multi-model writes go in `transaction.atomic()`.
- Permissions (spec §6): `CanManageJobsOrFinancials` **excludes** config; `reconcile` stays `CanManageFinancials`; the PO list's "New Purchase Order" gates on atoms, everything on a PO page gates on `po.can_manage`.
- `vendor_sku` is `CharField(max_length=100, blank=True, default='')`, editable on draft lines only (spec §3).
- The order endpoints' body is exactly one of `po_id` / `po`; `line.inventory_item` is refused with `{'line': {'inventory_item': ['Cannot change the item here.']}}`; responses are `{po_id, po_number, line_item_id}` with HTTP 201 (spec §4.2).
- UI copy: "Create PO" / "Add to PO0131" buttons, "Search all businesses…" option, "Also needed: …" earmark line, "No unordered materials on this job — a new material will be created." (spec §5).
- Record forms are modals (`components/Modal.svelte`); a modal whose content is a native `<form>` omits `onSave`; nested prompts are in-modal sub-states; confirm only the irreversible.
- Update `docs/designs/*` in the same session as the behavior change (Task 13 lists them).

## Review Focus

1. **Order with `qty` 0 or blank** (material source with the field cleared, or item source): expected `{'line': {'qty': [...]}}` 400 and the message under the Qty input, never a 0-qty PO line. → Task 3 `test_order_api_rejects_zero_qty`.
2. **`?exclude_job=abc` on vendor-history**: expected a 400 `{'exclude_job': [...]}`, not a 500 from `int()`. → Task 2 `test_exclude_job_must_be_integer`.
3. **Email create-PO with a `contact_id` that belongs to a different business than the vendor**: expected `{'contact_id': ['Contact is not at this vendor.']}` 400, never a PO whose contact and business disagree. → Task 4 `test_create_po_rejects_contact_from_other_business`.
4. **History recommends a vendor whose Business was deactivated since**: `create_po` refuses with a top-level `{'business': [...]}` (the service's shape, not nested under `po`); the modal must still land it under the vendor field and leave the form usable. → Task 3 `test_order_api_inactive_vendor_lands_on_business_field`, Task 8 `shows a top-level business error under the vendor picker`.
5. **Job changed after a material was picked on the add-line form**: a stale `material_id` from the previous job would 400 as "Material is not on the requested job". Expected: the choice resets and Submit disables again. → Task 10 `resets the material choice when the job changes`.

## File structure

Backend
- `apps/purchasing/models.py` — `PurchaseOrderLineItem.vendor_sku`.
- `apps/purchasing/migrations/0002_purchaseorderlineitem_vendor_sku.py` — generated.
- `apps/purchasing/services.py` — `add_line_item` comment guard; `add_line_item_from_pli` overrides; `linked_job_ids` / `user_can_manage`.
- `apps/purchasing/pdf.py` + `templates/purchasing/purchase_order_pdf.html` — Code / SKU columns.
- `apps/inventory/services.py` — `InventoryService.vendor_history`, new `order_stock` / `MaterialService.order` signatures, resolver mismatch guard, `_apply_po_line_cost` fix.
- `apps/api/inventory/serializers.py` — `OrderPOSerializer`, `OrderLineSerializer`, `OrderRequestSerializer`, `StockOrderRequestSerializer`; `MaterialSerializer.can_manage`.
- `apps/api/inventory/views.py` — `vendor_history` action, rewritten `order` actions, permissions.
- `apps/api/tasks/serializers.py` / `views.py` — `can_manage` on the task-materials serializer (+ request in context).
- `apps/api/purchasing/serializers.py` / `views.py` — `vendor_sku`, `item_code`, `can_manage`; `get_permission_target_po`; permissions.
- `apps/api/email/serializers.py` / `views.py` — `EmailCreatePOSerializer`; grown create-po body; `sender_info` opened to jobs-or-financials.
- `apps/api/permissions.py` — `CanManageJobsOrFinancials`, `CanManageFinancialsOrJobOrPM`, `CanManageFinancialsOrJobsOrLinkedPM`.
- Tests: `tests/test_po_vendor_sku.py`, `tests/test_vendor_history.py`, `tests/test_material_order_action.py` (rewritten API class), `tests/test_stock_order.py` (rewritten), `tests/test_api_email.py` (extended), `tests/test_po_line_guards.py`, `tests/test_po_permissions.py`, `tests/test_permissions_combo.py` (extended); one-line signature updates in `tests/test_api_earmarks.py`, `tests/test_material_ops.py`, `tests/test_api_job_tasklist.py`.

Frontend (`frontend/src/`)
- `components/purchaseorders/VendorPicker.svelte` (new), `OrderModal.svelte` (new), `LineItemForm.svelte`, `PurchaseOrderDetail.svelte`, `PurchaseOrderForm.svelte`.
- `components/materials/MaterialFulfillmentModals.svelte`, `MaterialRow.svelte`.
- `components/inventory/StockOrderDialog.svelte` — **deleted**.
- `components/email/EmailActionPanel.svelte`; `routes/email/EmailDetailPage.svelte`; `routes/email/EmailCreatePOPage.svelte` — **deleted**; `App.svelte` route stub.
- `routes/catalog/CatalogInventoryPage.svelte`, `CatalogEarmarksPage.svelte`.
- `routes/purchaseorders/PurchaseOrderDetailPage.svelte`, `PurchaseOrderFormPage.svelte`, `PurchaseOrderListPage.svelte`; `components/contacts/CustomerActivity.svelte`.
- `lib/email.js`.
- Tests (`frontend/tests/components/`): `purchaseorders/VendorPicker.test.js`, `purchaseorders/OrderModal.test.js` (new); `purchaseorders/LineItemForm.test.js`, `purchaseorders/PurchaseOrderDetail.test.js`, `purchaseorders/PurchaseOrderDetailPage.test.js`, `purchaseorders/PurchaseOrderListPage.test.js`, `email/EmailActionPanel.test.js`, `tasks/TasksPanel.test.js`, `TaskTree.test.js` (updated); `inventory/StockOrderDialog.test.js` (deleted).

E2E / docs
- `e2e/specs/purchasing/po-order-flow.spec.js` (new); `docs/ui-flows/Purchasing.md` §11 (new section).
- `docs/designs/materials-inventory-and-purchasing.md`, `architecture-and-conventions.md`, `users-and-permissions.md`, `data-constraints.md`, `LATER.md`, `frontend/README.md`.

---

### Task 1: `vendor_sku` on PO lines, Code/SKU on the PDF

**Files:**
- Modify: `apps/purchasing/models.py` (class `PurchaseOrderLineItem`, after `invoice_only`)
- Create: `apps/purchasing/migrations/0002_purchaseorderlineitem_vendor_sku.py` (via `makemigrations`)
- Modify: `apps/api/purchasing/serializers.py:14-45` (`POLineItemSerializer`)
- Modify: `apps/purchasing/pdf.py`, `templates/purchasing/purchase_order_pdf.html:34-58`
- Test: `tests/test_po_vendor_sku.py`

**Interfaces:**
- Produces: `PurchaseOrderLineItem.vendor_sku: str` (default `''`); line serializer fields `vendor_sku` (writable) and `item_code` (read-only, `inventory_item.code`, `None` for freeform); `li.display_code` attribute set by `generate_purchase_order_pdf` (blank for freeform and for `LOT-*` lots).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_po_vendor_sku.py
"""vendor_sku on PO lines (spec 2026-10-14 §3): stored, editable on drafts
through the line PATCH, exposed with the item code on the line serializer,
and printed as Code / SKU columns on the PDF (blank for freeform lines and
for minted LOT-* lots, which are not vendor codes)."""
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.inventory.models import InventoryItem
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.pdf import generate_purchase_order_pdf


class VendorSkuTests(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='po_number_sequence', defaults={'value': 'PO-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Materials', code='MATSKU')
        c = Contact.objects.create(first_name='V', last_name='V',
                                   phones=[{'number': '5', 'label': 'work'}])
        self.business = Business.objects.create(business_name='Rugby', default_contact=c)
        c.business = self.business
        c.save()
        self.item = InventoryItem.objects.create(
            code='BB34P', description='3/4 Baltic Birch', accounting_category=self.cat,
            purchase_price=Decimal('62.40'), units='sheet')
        self.lot = InventoryItem.objects.create(
            code='LOT-77', description='minted', accounting_category=self.cat,
            purchase_price=Decimal('1.00'))
        self.po = PurchaseOrder.objects.create(business=self.business, contact=c)
        self.user = User.objects.create_user('sku_admin', password='p', is_superuser=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_default_is_blank(self):
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='x', qty=1, price=1)
        self.assertEqual(li.vendor_sku, '')

    def test_line_create_accepts_vendor_sku_and_serializes_item_code(self):
        r = self.client.post(f'/api/purchase-orders/{self.po.pk}/line-items/', {
            'description': 'ply', 'qty': 2, 'price': '62.40',
            'inventory_item': self.item.pk, 'vendor_sku': 'BB34P-48',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['vendor_sku'], 'BB34P-48')
        self.assertEqual(r.json()['item_code'], 'BB34P')

    def test_line_patch_edits_vendor_sku(self):
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='x', qty=1, price=1)
        r = self.client.patch(
            f'/api/purchase-orders/{self.po.pk}/line-items/{li.pk}/',
            {'vendor_sku': 'X-1'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        li.refresh_from_db()
        self.assertEqual(li.vendor_sku, 'X-1')

    def test_freeform_line_has_null_item_code(self):
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='x', qty=1, price=1)
        r = self.client.get(f'/api/purchase-orders/{self.po.pk}/line-items/')
        row = next(x for x in r.json() if x['line_item_id'] == li.pk)
        self.assertIsNone(row['item_code'])
        self.assertEqual(row['vendor_sku'], '')

    @patch('apps.purchasing.pdf.HTML')
    def test_pdf_prints_code_and_sku_columns(self, mock_html):
        mock_html.return_value.write_pdf.return_value = b'%PDF-x'
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, inventory_item=self.item, description='ply',
            qty=1, price=Decimal('62.40'), vendor_sku='BB34P-48')
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, description='freight', qty=1, price=Decimal('10.00'))
        PurchaseOrderLineItem.objects.create(
            purchase_order=self.po, inventory_item=self.lot, description='lot line',
            qty=1, price=Decimal('1.00'))
        generate_purchase_order_pdf(self.po)
        html = mock_html.call_args.kwargs['string']
        self.assertIn('<th>Code</th>', html)
        self.assertIn('<th>SKU</th>', html)
        self.assertIn('BB34P-48', html)
        self.assertIn('>BB34P<', html)
        self.assertNotIn('LOT-77', html)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python manage.py test tests.test_po_vendor_sku --noinput`
Expected: errors — `vendor_sku` is an invalid keyword for `PurchaseOrderLineItem`.

- [ ] **Step 3: Add the field and migration**

In `apps/purchasing/models.py`, inside `PurchaseOrderLineItem` after `invoice_only`:

```python
    # Vendor's part number for this line (PO order flow, 2026-10-14 §3).
    # Suggested from the item's vendor history when ordering; a quote's SKU
    # overrides it. Editable on drafts only, like the other ordering fields.
    vendor_sku = models.CharField(max_length=100, blank=True, default='')
```

Run: `python manage.py makemigrations purchasing -n purchaseorderlineitem_vendor_sku`
Expected: `apps/purchasing/migrations/0002_purchaseorderlineitem_vendor_sku.py` created. Do **not** run `migrate`.

- [ ] **Step 4: Serializer fields**

In `apps/api/purchasing/serializers.py`, `POLineItemSerializer`: add a declared field and list entries.

```python
    # Catalog code of the line's item (None for freeform). The PO table and
    # PDF print it beside the vendor SKU.
    item_code = serializers.CharField(
        source='inventory_item.code', read_only=True, default=None)
```

In `Meta.fields` insert `'vendor_sku', 'item_code',` after `'is_comment',`. In `read_only_fields` add `'item_code',` (keep `vendor_sku` writable).

- [ ] **Step 5: PDF**

In `apps/purchasing/pdf.py` replace the `line_items = ...` statement with:

```python
    line_items = list(po.purchaseorderlineitem_set.select_related(
        'accounting_category', 'inventory_item'
    ).order_by('line_number'))
    # Code column: the catalog code, blank for freeform lines and for minted
    # LOT-* lots (a lot id means nothing to the vendor).
    for li in line_items:
        code = li.inventory_item.code if li.inventory_item_id else ''
        li.display_code = '' if code.startswith('LOT-') else code
```

In `templates/purchasing/purchase_order_pdf.html`: header row becomes
`<th>#</th><th>Description</th><th>Code</th><th>SKU</th><th>Qty</th><th>Unit</th><th>Price</th><th>Total</th>`;
after the description cell add `<td>{{ item.display_code }}</td><td>{{ item.vendor_sku }}</td>`;
the footer `colspan="5"` becomes `colspan="7"`.

- [ ] **Step 6: Run the tests**

Run: `python manage.py test tests.test_po_vendor_sku tests.test_po_send tests.test_api_purchasing tests.test_api_line_item_mixin --noinput`
Expected: all `OK`.

- [ ] **Step 7: Commit**

```bash
git add apps/purchasing/models.py apps/purchasing/migrations/0002_purchaseorderlineitem_vendor_sku.py apps/api/purchasing/serializers.py apps/purchasing/pdf.py templates/purchasing/purchase_order_pdf.html tests/test_po_vendor_sku.py
git commit -m "feat(purchasing): vendor_sku on PO lines; Code/SKU columns on the PO PDF"
```

---

### Task 2: Vendor history endpoint

**Files:**
- Modify: `apps/inventory/services.py` (class `InventoryService`, after `order_stock`)
- Modify: `apps/api/inventory/views.py:48-57` (`get_permissions`) and add an action after `order` (line ~126)
- Test: `tests/test_vendor_history.py`

**Interfaces:**
- Produces: `InventoryService.vendor_history(item, *, exclude_job=None) -> {'vendors': [...], 'earmarks': [...], 'open_drafts': [...]}` exactly as spec §4.1 (`last_price`, `quantity` are strings; `last_ordered` is an ISO date; `times` counts distinct POs). `GET /api/inventory/{id}/vendor-history/?exclude_job=<id>` (`IsAuthenticated`) returns that dict.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_vendor_history.py
"""GET /api/inventory/{id}/vendor-history/ (spec 2026-10-14 §4.1): vendors
from non-draft, non-cancelled PO lines newest first; earmarks by job with
?exclude_job; every open draft (vendor-less included) for client-side
filtering."""
from datetime import timedelta
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.inventory.models import Earmark, InventoryItem
from apps.inventory.services import InventoryService
from apps.jobs.models import Job
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService


def _vendor(name):
    c = Contact.objects.create(first_name=name, last_name='Sales',
                               phones=[{'number': '5', 'label': 'work'}])
    b = Business.objects.create(business_name=name, default_contact=c)
    c.business = b
    c.save()
    return b, c


class _Base(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='po_number_sequence', defaults={'value': 'PO-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Materials', code='MATVH')
        self.item = InventoryItem.objects.create(
            code='BB34P', description='ply', accounting_category=self.cat,
            purchase_price=Decimal('60.00'), units='sheet')
        self.rugby, self.rugby_contact = _vendor('Rugby')
        self.royal, self.royal_contact = _vendor('Royal')
        self.now = timezone.now()

    def _po(self, business, contact=None, status=PurchaseOrder.STATUS_ISSUED, days_ago=0):
        po = PurchaseOrder.objects.create(business=business, contact=contact)
        if status != PurchaseOrder.STATUS_DRAFT:
            po.status = PurchaseOrder.STATUS_ISSUED
            po.save()
            PurchaseOrder.objects.filter(pk=po.pk).update(
                status=status, issued_date=self.now - timedelta(days=days_ago))
            po.refresh_from_db()
        return po

    def _line(self, po, price=Decimal('60.00'), sku=''):
        return PurchaseOrderLineItem.objects.create(
            purchase_order=po, inventory_item=self.item, description='ply',
            qty=1, price=price, vendor_sku=sku)


class VendorHistoryServiceTests(_Base):
    def test_vendors_newest_first_with_newest_line_details(self):
        old = self._po(self.rugby, self.rugby_contact, days_ago=10)
        self._line(old, Decimal('58.00'), 'R-OLD')
        mid = self._po(self.rugby, None, days_ago=5)
        self._line(mid, Decimal('60.00'), 'R-NEW')
        new = self._po(self.royal, self.royal_contact,
                       status=PurchaseOrder.STATUS_RECEIVED_IN_FULL, days_ago=2)
        self._line(new, Decimal('62.40'), 'BB34P-48')

        data = InventoryService.vendor_history(self.item)
        self.assertEqual([v['business_name'] for v in data['vendors']], ['Royal', 'Rugby'])
        royal, rugby = data['vendors']
        self.assertEqual(royal['contact_id'], self.royal_contact.pk)
        self.assertEqual(royal['last_price'], '62.40')
        self.assertEqual(royal['vendor_sku'], 'BB34P-48')
        self.assertEqual(royal['po_number'], new.po_number)
        self.assertEqual(royal['last_ordered'], (self.now - timedelta(days=2)).date().isoformat())
        self.assertEqual(royal['times'], 1)
        self.assertEqual(rugby['vendor_sku'], 'R-NEW')
        self.assertIsNone(rugby['contact_id'])
        self.assertEqual(rugby['po_number'], mid.po_number)
        self.assertEqual(rugby['times'], 2)

    def test_drafts_and_cancelled_excluded_from_vendors(self):
        self._line(self._po(self.rugby, status=PurchaseOrder.STATUS_DRAFT))
        self._line(self._po(self.royal, status=PurchaseOrder.STATUS_CANCELLED, days_ago=1))
        self.assertEqual(InventoryService.vendor_history(self.item)['vendors'], [])

    def test_lot_item_has_no_vendors_but_sees_open_drafts(self):
        lot = InventoryItem.objects.create(
            code='LOT-9', description='lot', accounting_category=self.cat)
        draft = self._po(self.rugby, status=PurchaseOrder.STATUS_DRAFT)
        data = InventoryService.vendor_history(lot)
        self.assertEqual(data['vendors'], [])
        self.assertEqual([d['po_id'] for d in data['open_drafts']], [draft.pk])

    def test_open_drafts_include_vendorless_with_line_count(self):
        vendored = self._po(self.rugby, status=PurchaseOrder.STATUS_DRAFT)
        self._line(vendored)
        self._line(vendored)
        bare = PurchaseOrderService.create_po()
        issued = self._po(self.royal, days_ago=1)
        self._line(issued)
        rows = {d['po_id']: d for d in InventoryService.vendor_history(self.item)['open_drafts']}
        self.assertEqual(set(rows), {vendored.pk, bare.pk})
        self.assertEqual(rows[vendored.pk]['line_count'], 2)
        self.assertEqual(rows[vendored.pk]['business_name'], 'Rugby')
        self.assertIsNone(rows[bare.pk]['business_id'])
        self.assertIsNone(rows[bare.pk]['business_name'])

    def test_earmarks_by_job_with_exclude_job(self):
        cust = Contact.objects.create(first_name='C', last_name='C',
                                      phones=[{'number': '1', 'label': 'work'}])
        job_a = Job.objects.create(job_number='08157', contact=cust, description='a')
        job_b = Job.objects.create(job_number='08149', contact=cust, description='b')
        Earmark.objects.create(inventory_item=self.item, job=job_a, quantity=Decimal('4'))
        Earmark.objects.create(inventory_item=self.item, job=job_b, quantity=Decimal('3'))
        all_rows = InventoryService.vendor_history(self.item)['earmarks']
        self.assertEqual({(e['job_number'], e['quantity']) for e in all_rows},
                         {('08157', '4.00'), ('08149', '3.00')})
        others = InventoryService.vendor_history(self.item, exclude_job=job_a.pk)['earmarks']
        self.assertEqual([e['job_id'] for e in others], [job_b.pk])


class VendorHistoryApiTests(_Base):
    def setUp(self):
        super().setUp()
        self.worker = User.objects.create_user('vh_worker', password='p')
        self.client = APIClient()

    def test_any_authenticated_user_can_read(self):
        self._line(self._po(self.rugby, days_ago=1), sku='R-1')
        self.client.force_authenticate(self.worker)
        r = self.client.get(f'/api/inventory/{self.item.pk}/vendor-history/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['vendors'][0]['vendor_sku'], 'R-1')
        self.assertEqual(set(r.json()), {'vendors', 'earmarks', 'open_drafts'})

    def test_anonymous_rejected(self):
        r = self.client.get(f'/api/inventory/{self.item.pk}/vendor-history/')
        self.assertIn(r.status_code, (401, 403))

    def test_exclude_job_must_be_integer(self):
        self.client.force_authenticate(self.worker)
        r = self.client.get(f'/api/inventory/{self.item.pk}/vendor-history/?exclude_job=abc')
        self.assertEqual(r.status_code, 400)
        self.assertIn('exclude_job', r.json())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python manage.py test tests.test_vendor_history --noinput`
Expected: `AttributeError: ... has no attribute 'vendor_history'` and 404s on the API class.

- [ ] **Step 3: Service**

In `apps/inventory/services.py`, in `InventoryService` directly after `order_stock`:

```python
    @staticmethod
    def vendor_history(item, *, exclude_job=None):
        """Who has this item been bought from (PO order flow §4.1). One row per
        business from lines on POs that are neither draft nor cancelled, newest
        first; `last_*` / `vendor_sku` / `contact_id` come from the newest
        line's PO. `earmarks` lists the item's committed earmarks by job
        (minus `exclude_job`, the calling material's own job). `open_drafts`
        is every draft PO — vendor-less ones included, flagged by
        business_id None — so the modal can filter by vendor client-side."""
        from django.db.models import Count
        from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
        lines = (
            PurchaseOrderLineItem.objects
            .filter(inventory_item=item, purchase_order__business__isnull=False)
            .exclude(purchase_order__status__in=[
                PurchaseOrder.STATUS_DRAFT, PurchaseOrder.STATUS_CANCELLED])
            .select_related('purchase_order__business')
            .order_by('-purchase_order__issued_date', '-purchase_order__created_date', '-pk')
        )
        vendors, by_business, pos_seen = [], {}, {}
        for li in lines:
            po = li.purchase_order
            row = by_business.get(po.business_id)
            if row is None:
                row = {
                    'business_id': po.business_id,
                    'business_name': po.business.business_name,
                    'contact_id': po.contact_id,
                    'last_ordered': (po.issued_date or po.created_date).date().isoformat(),
                    'last_price': str(li.price),
                    'vendor_sku': li.vendor_sku,
                    'po_number': po.po_number,
                    'times': 0,
                }
                by_business[po.business_id] = row
                pos_seen[po.business_id] = set()
                vendors.append(row)
            if po.pk not in pos_seen[po.business_id]:
                pos_seen[po.business_id].add(po.pk)
                row['times'] += 1

        earmark_qs = (Earmark.objects.filter(inventory_item=item, quantity__gt=0)
                      .select_related('job').order_by('job__job_number'))
        if exclude_job is not None:
            earmark_qs = earmark_qs.exclude(job_id=exclude_job)
        earmarks = [{'job_id': e.job_id, 'job_number': e.job.job_number,
                     'quantity': str(e.quantity)} for e in earmark_qs]

        drafts = (PurchaseOrder.objects.filter(status=PurchaseOrder.STATUS_DRAFT)
                  .select_related('business')
                  .annotate(line_count=Count('purchaseorderlineitem'))
                  .order_by('-created_date')[:100])
        open_drafts = [{
            'po_id': d.pk, 'po_number': d.po_number,
            'business_id': d.business_id,
            'business_name': d.business.business_name if d.business_id else None,
            'line_count': d.line_count,
        } for d in drafts]
        return {'vendors': vendors, 'earmarks': earmarks, 'open_drafts': open_drafts}
```

Confirm `Earmark` is already imported at the top of `apps/inventory/services.py` (it is used by `_mutate_earmark`); import it if not.

- [ ] **Step 4: View + permission**

In `apps/api/inventory/views.py`, `InventoryItemViewSet.get_permissions`, change the first branch to `if self.action in ('list', 'retrieve', 'vendor_history'):`. Add after the `order` action:

```python
    @action(detail=True, methods=['get'], url_path='vendor-history')
    def vendor_history(self, request, pk=None):
        """Who carries this item, its earmarks by job, and the open drafts —
        the Order modal's one read (PO order flow §4.1)."""
        item = self.get_object()
        raw = request.query_params.get('exclude_job')
        exclude_job = None
        if raw not in (None, ''):
            try:
                exclude_job = int(raw)
            except ValueError:
                return Response({'exclude_job': ['Must be an integer.']},
                                status=status.HTTP_400_BAD_REQUEST)
        return Response(InventoryService.vendor_history(item, exclude_job=exclude_job))
```

- [ ] **Step 5: Run the tests**

Run: `python manage.py test tests.test_vendor_history --noinput`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add apps/inventory/services.py apps/api/inventory/views.py tests/test_vendor_history.py
git commit -m "feat(inventory): vendor-history endpoint (vendors, earmarks, open drafts)"
```

---

### Task 3: Order endpoints take the whole PO

**Files:**
- Modify: `apps/api/inventory/serializers.py:140-142` (replace `StockOrderSerializer`)
- Modify: `apps/api/inventory/views.py:109-126` (inventory `order`), `:204-220` (material `order`)
- Modify: `apps/inventory/services.py:265-285` (`order_stock`), `:1140-1165` (`MaterialService.order`)
- Modify: `apps/purchasing/services.py:612-652` (`add_line_item_from_pli`), `apps/api/purchasing/views.py:148-153` (pass `vendor_sku` through on the PLI path)
- Modify tests: `tests/test_material_order_action.py`, `tests/test_stock_order.py`, `tests/test_api_earmarks.py:51`, `tests/test_material_ops.py:278`, `tests/test_api_job_tasklist.py:512`

**Interfaces:**
- Consumes: `vendor_sku` (Task 1).
- Produces:
  - `PurchaseOrderService.add_line_item_from_pli(po_id, inventory_item_id, qty, job=None, material_id=None, task=None, *, price=None, description=None, units=None, vendor_sku='', accounting_category=None)` — `None` means "the item's default".
  - `MaterialService.order(material, *, po=None, po_fields=None, line=None) -> (po, li)`; `InventoryService.order_stock(item, *, po=None, po_fields=None, line=None) -> (po, li)`. `line` is a dict with optional `qty` (required for stock) plus the overrides above; `po_fields` is passed to `create_po(**po_fields)` (may be empty — the service still allows a vendor-less draft, the API does not).
  - `OrderRequestSerializer` / `StockOrderRequestSerializer` (validated data: `po_id`, `po` {business, contact, requested_date — model instances}, `line`).
  - API: `POST /api/materials/{id}/order/`, `POST /api/inventory/{id}/order/` → 201 `{po_id, po_number, line_item_id}`.

- [ ] **Step 1: Rewrite the API test class and extend the service tests**

Replace `OrderFromMaterialApiTests` in `tests/test_material_order_action.py` with:

```python
class OrderFromMaterialApiTests(APITestCase):
    """POST /api/materials/{id}/order/ — spec §4.2: exactly one of po_id / po,
    po.business required, line overrides, item fixed by the URL."""

    def setUp(self):
        for key, value in (('po_number_sequence', 'PO-{year}-{counter:04d}'),
                           ('default_material_markup_percent', '25')):
            Configuration.objects.get_or_create(key=key, defaults={'value': value})
        AppState.objects.get_or_create(key='po_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MATAPI')
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='japi@d.com', phones=[{'number': '5', 'label': 'mobile'}])
        self.job = Job.objects.create(
            contact=contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0002')
        self.material = MaterialService.create_on_job(
            job=self.job, description='steel', quantity=Decimal('3'),
            unit_cost=Decimal('80.00'), accounting_category=self.cat, units='ea')
        vc = Contact.objects.create(
            first_name='V', last_name='V', phones=[{'number': '6', 'label': 'mobile'}])
        self.business = Business.objects.create(business_name='Vendor Co', default_contact=vc)
        vc.business = self.business
        vc.save()
        self.vendor_contact = vc
        self.user = User.objects.create_user('order_fin_user', password='p')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials'))
        self.client.force_login(self.user)
        self.url = f'/api/materials/{self.material.pk}/order/'

    def test_po_mode_creates_vendored_po_with_line_and_links_material(self):
        resp = self.client.post(self.url, {
            'po': {'business': self.business.pk, 'contact': self.vendor_contact.pk,
                   'requested_date': '2026-10-20'},
            'line': {'qty': '4', 'price': '62.40', 'vendor_sku': 'ST-4',
                     'description': 'steel bar', 'units': 'ea'},
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        data = resp.json()
        po = PurchaseOrder.objects.get(pk=data['po_id'])
        self.assertEqual(po.business_id, self.business.pk)
        self.assertEqual(po.contact_id, self.vendor_contact.pk)
        self.assertEqual(po.requested_date.date().isoformat(), '2026-10-20')
        li = po.purchaseorderlineitem_set.get(pk=data['line_item_id'])
        self.assertEqual((li.qty, li.price, li.vendor_sku, li.description),
                         (Decimal('4'), Decimal('62.40'), 'ST-4', 'steel bar'))
        self.material.refresh_from_db()
        self.assertEqual(self.material.po_line_item_id, li.pk)
        self.assertEqual(self.material.unit_cost, Decimal('62.40'))
        self.assertEqual(self.material.cost_source, Material.COST_SOURCE_PO)

    def test_line_defaults_come_from_the_material_and_item(self):
        resp = self.client.post(self.url, {'po': {'business': self.business.pk}}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        li = PurchaseOrder.objects.get(pk=resp.json()['po_id']).purchaseorderlineitem_set.get()
        self.assertEqual(li.qty, Decimal('3'))
        self.assertEqual(li.price, Decimal('80.00'))
        self.assertEqual(li.vendor_sku, '')

    def test_po_id_mode_appends_to_that_draft(self):
        po = PurchaseOrderService.create_po(business=self.business)
        resp = self.client.post(self.url, {'po_id': po.pk, 'line': {'qty': '2'}}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['po_id'], po.pk)
        self.assertEqual(po.purchaseorderlineitem_set.get().qty, Decimal('2'))

    def test_both_or_neither_is_a_non_field_error(self):
        for body in ({}, {'po_id': 1, 'po': {'business': self.business.pk}}):
            resp = self.client.post(self.url, body, format='json')
            self.assertEqual(resp.status_code, 400, resp.content)
            self.assertIn('non_field_errors', resp.json())

    def test_po_mode_requires_business(self):
        resp = self.client.post(self.url, {'po': {}}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('business', resp.json()['po'])

    def test_contact_must_belong_to_the_vendor(self):
        stranger = Contact.objects.create(
            first_name='S', last_name='S', phones=[{'number': '7', 'label': 'mobile'}])
        resp = self.client.post(self.url, {
            'po': {'business': self.business.pk, 'contact': stranger.pk}}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('contact', resp.json()['po'])

    def test_line_inventory_item_is_refused(self):
        resp = self.client.post(self.url, {
            'po': {'business': self.business.pk},
            'line': {'inventory_item': self.material.inventory_item_id}}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['line']['inventory_item'], ['Cannot change the item here.'])
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def test_order_api_rejects_zero_qty(self):
        resp = self.client.post(self.url, {
            'po': {'business': self.business.pk}, 'line': {'qty': '0'}}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('qty', resp.json()['line'])
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def test_order_api_inactive_vendor_lands_on_business_field(self):
        self.business.is_active = False
        self.business.save()
        resp = self.client.post(self.url, {'po': {'business': self.business.pk}}, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('business', resp.json())
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def test_non_draft_po_id_rejected(self):
        po = PurchaseOrderService.create_po(business=self.business)
        po.status = PurchaseOrder.STATUS_ISSUED
        po.save()
        resp = self.client.post(self.url, {'po_id': po.pk}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.json())

    def test_order_action_forbidden_without_financials_atom(self):
        worker = User.objects.create_user('order_worker', password='p')
        self.client.force_login(worker)
        resp = self.client.post(self.url, {'po': {'business': self.business.pk}}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_order_action_unauthenticated_rejected(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        resp = anon.post(self.url, {'po': {'business': self.business.pk}}, format='json')
        self.assertIn(resp.status_code, [401, 403])
```

Add `from apps.inventory.models import Material` is already imported at the top of that file; keep it. Add to `OrderFromMaterialTests` (service class):

```python
    def test_order_with_po_fields_and_line_overrides(self):
        vc = Contact.objects.create(
            first_name='V', last_name='V', phones=[{'number': '6', 'label': 'mobile'}])
        business = Business.objects.create(business_name='Vendor Co', default_contact=vc)
        po, li = MaterialService.order(
            self.material, po_fields={'business': business},
            line={'qty': Decimal('5'), 'vendor_sku': 'ST-5', 'price': Decimal('70.00')})
        self.assertEqual(po.business_id, business.pk)
        self.assertEqual((li.qty, li.vendor_sku, li.price), (Decimal('5'), 'ST-5', Decimal('70.00')))
        self.material.refresh_from_db()
        self.assertEqual(self.material.unit_cost, Decimal('70.00'))

    def test_order_rolls_back_the_po_when_the_line_fails(self):
        from unittest.mock import patch
        before = PurchaseOrder.objects.count()
        with patch.object(PurchaseOrderService, 'add_line_item_from_pli',
                          side_effect=ValidationError('boom')):
            with self.assertRaises(ValidationError):
                MaterialService.order(self.material, po_fields={})
        self.assertEqual(PurchaseOrder.objects.count(), before)
        self.material.refresh_from_db()
        self.assertIsNone(self.material.po_line_item_id)
```

Rewrite `tests/test_stock_order.py` so every `order_stock` call uses the new signature and add the API matrix:

```python
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.inventory.models import InventoryItem
from apps.inventory.services import InventoryService
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import PurchaseOrderService


class OrderStockTest(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(key='po_number_sequence', defaults={'value': 'PO-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})
        cat = AccountingCategory.objects.create(name='c')
        self.item = InventoryItem.objects.create(
            code='SHEET-3', accounting_category=cat,
            qty_on_hand=Decimal('1'), purchase_price=Decimal('10'),
        )

    def test_creates_draft_po_with_unlinked_line(self):
        po, li = InventoryService.order_stock(self.item, line={'qty': Decimal('5')})
        self.assertEqual(po.status, PurchaseOrder.STATUS_DRAFT)
        self.assertEqual(li.inventory_item_id, self.item.pk)
        self.assertEqual(li.qty, Decimal('5'))
        self.assertEqual(li.price, Decimal('10'))
        self.assertIsNone(li.task_id)
        self.assertIsNone(li.linked_material)

    def test_line_overrides_and_po_fields(self):
        c = Contact.objects.create(first_name='V', last_name='V', phones=[{'number': '5', 'label': 'work'}])
        b = Business.objects.create(business_name='B', default_contact=c)
        po, li = InventoryService.order_stock(
            self.item, po_fields={'business': b},
            line={'qty': Decimal('2'), 'price': Decimal('9.50'), 'vendor_sku': 'S-3', 'units': 'sheet'})
        self.assertEqual(po.business_id, b.pk)
        self.assertEqual((li.price, li.vendor_sku, li.units), (Decimal('9.50'), 'S-3', 'sheet'))

    def test_appends_to_given_draft(self):
        po, _ = InventoryService.order_stock(self.item, line={'qty': Decimal('2')})
        po2, li2 = InventoryService.order_stock(self.item, po=po, line={'qty': Decimal('3')})
        self.assertEqual(po2.pk, po.pk)
        self.assertEqual(po.purchaseorderlineitem_set.count(), 2)

    def test_refuses_non_draft_po(self):
        po, _ = InventoryService.order_stock(self.item, line={'qty': Decimal('2')})
        PurchaseOrder.objects.filter(pk=po.pk).update(status=PurchaseOrder.STATUS_ISSUED)
        po.refresh_from_db()
        with self.assertRaises(ValidationError):
            InventoryService.order_stock(self.item, po=po, line={'qty': Decimal('1')})

    def test_refuses_missing_or_non_positive_quantity(self):
        for line in (None, {}, {'qty': Decimal('0')}, {'qty': Decimal('-1')}):
            with self.assertRaises(ValidationError):
                InventoryService.order_stock(self.item, line=line)


class OrderStockApiTest(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(key='po_number_sequence', defaults={'value': 'PO-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})
        cat = AccountingCategory.objects.create(name='c2')
        self.item = InventoryItem.objects.create(code='SHEET-4', accounting_category=cat, purchase_price=Decimal('10'))
        c = Contact.objects.create(first_name='V', last_name='V', phones=[{'number': '5', 'label': 'work'}])
        self.business = Business.objects.create(business_name='B2', default_contact=c)
        self.user = User.objects.create_user('stock_fin', password='p')
        self.user.user_permissions.add(Permission.objects.get(codename='can_manage_financials'))
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = f'/api/inventory/{self.item.pk}/order/'

    def test_po_mode_creates_po_and_line(self):
        r = self.client.post(self.url, {'po': {'business': self.business.pk},
                                        'line': {'qty': '3', 'vendor_sku': 'S-4'}}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        po = PurchaseOrder.objects.get(pk=r.json()['po_id'])
        self.assertEqual(po.business_id, self.business.pk)
        self.assertEqual(po.purchaseorderlineitem_set.get().vendor_sku, 'S-4')

    def test_po_id_mode_appends(self):
        po = PurchaseOrderService.create_po(business=self.business)
        r = self.client.post(self.url, {'po_id': po.pk, 'line': {'qty': '1'}}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['po_id'], po.pk)

    def test_qty_is_required_for_stock(self):
        r = self.client.post(self.url, {'po': {'business': self.business.pk}}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('line', r.json())
        r = self.client.post(self.url, {'po': {'business': self.business.pk}, 'line': {}}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('qty', r.json()['line'])

    def test_line_inventory_item_refused(self):
        r = self.client.post(self.url, {'po': {'business': self.business.pk},
                                        'line': {'qty': '1', 'inventory_item': self.item.pk}}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('inventory_item', r.json()['line'])

    def test_worker_forbidden(self):
        self.client.force_authenticate(User.objects.create_user('stock_worker', password='p'))
        r = self.client.post(self.url, {'po': {'business': self.business.pk}, 'line': {'qty': '1'}}, format='json')
        self.assertEqual(r.status_code, 403)
```

Update the three other callers to the keyword form:
- `tests/test_api_earmarks.py:51` → `po, li = InventoryService.order_stock(self.item, line={'qty': Decimal('3')})`
- `tests/test_material_ops.py:278` and `tests/test_api_job_tasklist.py:512` — `MaterialService.order(m)` / `MaterialService.order(material)` stay valid (keyword-only extras, vendor-less draft still allowed at the service level); no change.

- [ ] **Step 2: Run to verify the new tests fail**

Run: `python manage.py test tests.test_material_order_action tests.test_stock_order --noinput`
Expected: failures on the new body shape (old view returns 200 / ignores `po`), `TypeError` on `order_stock(..., line=...)`.

- [ ] **Step 3: Serializers**

In `apps/api/inventory/serializers.py` replace `StockOrderSerializer` with (add `from decimal import Decimal`, `from apps.contacts.models import Business, Contact`, `from apps.core.models import AccountingCategory` to the imports; `UnitsField` is already imported there):

```python
class OrderPOSerializer(serializers.Serializer):
    """`po` block of an order request (spec §4.2). A vendor is required, so
    the one-click paths can no longer mint a vendor-less draft (path 3's
    form still may)."""
    business = serializers.PrimaryKeyRelatedField(queryset=Business.objects.all())
    contact = serializers.PrimaryKeyRelatedField(
        queryset=Contact.objects.all(), required=False, allow_null=True)
    requested_date = serializers.DateTimeField(required=False, allow_null=True)

    def validate(self, attrs):
        contact = attrs.get('contact')
        if contact is not None and contact.business_id != attrs['business'].pk:
            raise serializers.ValidationError({'contact': ['Contact is not at this vendor.']})
        return attrs


class OrderLineSerializer(serializers.Serializer):
    """`line` overrides for the ordered line. Every field is optional; an
    absent/None value means "the item's (or material's) default"."""
    qty = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, min_value=Decimal('0.01'))
    units = UnitsField(required=False, default=None)
    price = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True,
        min_value=Decimal('0'))
    description = serializers.CharField(required=False, allow_blank=True)
    vendor_sku = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default='')
    accounting_category = serializers.PrimaryKeyRelatedField(
        queryset=AccountingCategory.objects.all(), required=False, allow_null=True)


class OrderRequestSerializer(serializers.Serializer):
    """POST /api/materials/{id}/order/ body: exactly one of `po_id` (append
    to that draft) or `po` (create a PO), plus optional `line` overrides.
    `line.inventory_item` is refused — the item is fixed by the URL."""
    po_id = serializers.IntegerField(required=False, allow_null=True)
    po = OrderPOSerializer(required=False, allow_null=True)
    line = OrderLineSerializer(required=False, allow_null=True)

    def validate(self, attrs):
        raw_line = self.initial_data.get('line') if hasattr(self.initial_data, 'get') else None
        if isinstance(raw_line, dict) and 'inventory_item' in raw_line:
            raise serializers.ValidationError(
                {'line': {'inventory_item': ['Cannot change the item here.']}})
        has_id = attrs.get('po_id') is not None
        has_po = attrs.get('po') is not None
        if has_id == has_po:
            raise serializers.ValidationError(
                {'non_field_errors': ['Provide exactly one of po_id or po.']})
        return attrs


class StockOrderLineSerializer(OrderLineSerializer):
    """Order-to-stock has no material to default the quantity from."""
    qty = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))


class StockOrderRequestSerializer(OrderRequestSerializer):
    """POST /api/inventory/{id}/order/ body: same as OrderRequestSerializer
    with `line` (and `line.qty`) required."""
    line = StockOrderLineSerializer()
```

- [ ] **Step 4: Services**

`apps/purchasing/services.py`, `add_line_item_from_pli` — new signature and constructor:

```python
    @staticmethod
    def add_line_item_from_pli(po_id, inventory_item_id, qty, job=None, material_id=None,
                               task=None, *, price=None, description=None, units=None,
                               vendor_sku='', accounting_category=None):
        """Add a line item from an InventoryItem to a draft PO. Accepts optional
        job, material_id, task, and per-field overrides (PO order flow §4.2):
        None → the item's own value.
        ... (keep the existing docstring paragraph about `task`) ...
        """
```

and inside the `transaction.atomic()` block:

```python
            li = PurchaseOrderLineItem(
                purchase_order=po,
                inventory_item=pli,
                description=pli.description if description is None else description,
                qty=qty,
                units=pli.units if units is None else units,
                price=pli.purchase_price if price is None else price,
                accounting_category=(pli.accounting_category
                                     if accounting_category is None else accounting_category),
                vendor_sku=vendor_sku or '',
                task_id=task,
            )
```

`apps/api/purchasing/views.py` `line_items` POST, PLI branch — pass the SKU through:

```python
                item = service.add_line_item_from_pli(
                    parent.pk, pli_id, qty, job=job, material_id=material_id, task=task,
                    vendor_sku=data.get('vendor_sku', ''),
                )
```

`apps/inventory/services.py` — replace `order_stock`:

```python
    @staticmethod
    def _split_order_line(line):
        """Pop `qty` off a validated `line` block; the rest are
        add_line_item_from_pli overrides."""
        overrides = dict(line or {})
        return overrides.pop('qty', None), overrides

    @staticmethod
    def order_stock(item, *, po=None, po_fields=None, line=None):
        """Order an inventory item to stock: a plain PO line, no material link,
        no job (PO order flow §4.2). `po` appends to that draft; otherwise a
        PO is created from `po_fields` (the API requires a business; the
        service tolerates an empty dict) and the line added in the same
        transaction. `line['qty']` is required — stock has no material to
        default from."""
        from django.core.exceptions import ValidationError
        from django.db import transaction
        from apps.purchasing.models import PurchaseOrder
        from apps.purchasing.services import PurchaseOrderService
        qty, overrides = InventoryService._split_order_line(line)
        if qty is None or qty <= 0:
            raise ValidationError({'qty': ['Quantity must be greater than 0.']})
        if po is not None and po.status != PurchaseOrder.STATUS_DRAFT:
            raise ValidationError('Can only add lines to a draft purchase order.')
        with transaction.atomic():
            if po is None:
                po = PurchaseOrderService.create_po(**(po_fields or {}))
            li = PurchaseOrderService.add_line_item_from_pli(po.pk, item.pk, qty, **overrides)
        return po, li
```

and `MaterialService.order`:

```python
    @staticmethod
    def order(material, *, po=None, po_fields=None, line=None):
        """Path 1 (PO order flow §4.2): start a PO from `po_fields` or append
        to draft `po`, with one line linked to this material, in one
        transaction. `line` overrides default from the material (qty) and
        its item (the rest). The resolver's explicit path links the material;
        `_apply_po_line_cost` pushes the line price onto it."""
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
        qty, overrides = InventoryService._split_order_line(line)
        if qty is None:
            qty = material.quantity
        with transaction.atomic():
            if po is None:
                po = PurchaseOrderService.create_po(**(po_fields or {}))
            li = PurchaseOrderService.add_line_item_from_pli(
                po.pk, material.inventory_item_id, qty,
                job=material.job_id, material_id=material.pk, **overrides)
        return po, li
```

- [ ] **Step 5: Views**

`apps/api/inventory/views.py` — replace the inventory `order` body:

```python
    @action(detail=True, methods=['post'])
    def order(self, request, pk=None):
        """Order this item to stock (PO order flow §4.2): `{po_id}` appends to
        that draft, `{po: {business, contact?, requested_date?}}` creates; `line`
        overrides the item's defaults (qty required — nothing to default from)."""
        from django.shortcuts import get_object_or_404
        from apps.purchasing.models import PurchaseOrder
        s = StockOrderRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        item = self.get_object()
        po = get_object_or_404(PurchaseOrder, pk=v['po_id']) if v.get('po_id') is not None else None
        po, li = InventoryService.order_stock(
            item, po=po, po_fields=v.get('po'), line=v.get('line'))
        return Response({'po_id': po.pk, 'po_number': po.po_number, 'line_item_id': li.pk},
                        status=status.HTTP_201_CREATED)
```

and the material `order` body (same decorator and permission as today; Task 6 changes the permission):

```python
    def order(self, request, pk=None):
        """Start a PO (po) or append to a draft (po_id) with a line linked to
        this material — PO order flow §4.2. The item is the material's."""
        from django.shortcuts import get_object_or_404
        from apps.purchasing.models import PurchaseOrder
        s = OrderRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        m = self.get_object()
        po = get_object_or_404(PurchaseOrder, pk=v['po_id']) if v.get('po_id') is not None else None
        po, li = MaterialService.order(m, po=po, po_fields=v.get('po'), line=v.get('line'))
        return Response({'po_id': po.pk, 'po_number': po.po_number, 'line_item_id': li.pk},
                        status=status.HTTP_201_CREATED)
```

Update the serializer import line in the views to `OrderRequestSerializer, StockOrderRequestSerializer` (drop `StockOrderSerializer`).

- [ ] **Step 6: Run the tests**

Run: `python manage.py test tests.test_material_order_action tests.test_stock_order tests.test_api_earmarks tests.test_material_ops tests.test_api_job_tasklist tests.test_po_add_line_item_with_job tests.test_catalog_line_item_adds --noinput`
Expected: all `OK`.

- [ ] **Step 7: Commit**

```bash
git add apps/api/inventory/serializers.py apps/api/inventory/views.py apps/inventory/services.py apps/purchasing/services.py apps/api/purchasing/views.py tests/test_material_order_action.py tests/test_stock_order.py tests/test_api_earmarks.py
git commit -m "feat(api): order endpoints take the whole PO (po_id xor po) plus line overrides"
```

---

### Task 4: Email create-PO carries contact, date and an optional first line

**Files:**
- Modify: `apps/api/email/serializers.py` (append), `apps/api/email/views.py:140-181` (`create_po_from_email`)
- Test: `tests/test_api_email.py` (class `EmailPoAPITest`)

**Interfaces:**
- Consumes: `OrderLineSerializer` (Task 3), `add_line_item_from_pli` overrides (Task 3).
- Produces: `POST /api/emails/{id}/create-po/` body `{vendor_business_id, contact_id?, requested_date?, line?}` where `line` = `{inventory_item?, qty, units?, price?, description?, vendor_sku?, accounting_category?}`; response 201 `{po_id, po_number, line_item_id}` (`line_item_id` null without a line). The legacy `{vendor_business_id}` body is unchanged.

- [ ] **Step 1: Add failing tests to `EmailPoAPITest`**

```python
    def test_create_po_stores_contact_and_requested_date(self):
        response = self.client.post(
            f'/api/emails/{self.email.pk}/create-po/',
            {'vendor_business_id': self.business.pk, 'contact_id': self.contact.pk,
             'requested_date': '2026-10-20'}, format='json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        from apps.purchasing.models import PurchaseOrder
        po = PurchaseOrder.objects.get(pk=response.data['po_id'])
        self.assertEqual(po.contact_id, self.contact.pk)
        self.assertEqual(po.requested_date.date().isoformat(), '2026-10-20')
        self.assertIsNone(response.data['line_item_id'])

    def test_create_po_rejects_contact_from_other_business(self):
        from apps.contacts.models import Contact
        stranger = Contact.objects.create(
            first_name='S', last_name='S', phones=[{'number': '1', 'label': 'mobile'}])
        response = self.client.post(
            f'/api/emails/{self.email.pk}/create-po/',
            {'vendor_business_id': self.business.pk, 'contact_id': stranger.pk}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('contact_id', response.data)
        self.email.refresh_from_db()
        self.assertIsNone(self.email.purchase_order_id)

    def test_create_po_with_catalog_line(self):
        from decimal import Decimal
        from apps.core.models import AccountingCategory
        from apps.inventory.models import InventoryItem
        from apps.purchasing.models import PurchaseOrderLineItem
        cat = AccountingCategory.objects.first()
        item = InventoryItem.objects.create(
            code='EM-PLY', description='ply', accounting_category=cat,
            purchase_price=Decimal('50.00'), units='sheet')
        response = self.client.post(
            f'/api/emails/{self.email.pk}/create-po/',
            {'vendor_business_id': self.business.pk,
             'line': {'inventory_item': item.pk, 'qty': '3', 'vendor_sku': 'EM-1'}},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        li = PurchaseOrderLineItem.objects.get(pk=response.data['line_item_id'])
        self.assertEqual(li.purchase_order_id, response.data['po_id'])
        self.assertEqual((li.inventory_item_id, li.qty, li.price, li.vendor_sku),
                         (item.pk, Decimal('3'), Decimal('50.00'), 'EM-1'))

    def test_create_po_with_freeform_line(self):
        from decimal import Decimal
        from apps.purchasing.models import PurchaseOrderLineItem
        response = self.client.post(
            f'/api/emails/{self.email.pk}/create-po/',
            {'vendor_business_id': self.business.pk,
             'line': {'qty': '1', 'description': 'freight', 'price': '25.00'}},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        li = PurchaseOrderLineItem.objects.get(pk=response.data['line_item_id'])
        self.assertIsNone(li.inventory_item_id)
        self.assertEqual((li.description, li.price), ('freight', Decimal('25.00')))

    def test_create_po_freeform_line_needs_description(self):
        response = self.client.post(
            f'/api/emails/{self.email.pk}/create-po/',
            {'vendor_business_id': self.business.pk, 'line': {'qty': '1'}}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('description', response.data['line'])

    def test_create_po_is_atomic_when_the_line_fails(self):
        from unittest.mock import patch
        from django.core.exceptions import ValidationError
        from apps.purchasing.models import PurchaseOrder
        from apps.purchasing.services import PurchaseOrderService
        before = PurchaseOrder.objects.count()
        with patch.object(PurchaseOrderService, 'add_line_item',
                          side_effect=ValidationError({'price': ['bad']})):
            response = self.client.post(
                f'/api/emails/{self.email.pk}/create-po/',
                {'vendor_business_id': self.business.pk,
                 'line': {'qty': '1', 'description': 'x', 'price': '1.00'}},
                format='json',
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PurchaseOrder.objects.count(), before)
        self.email.refresh_from_db()
        self.assertIsNone(self.email.purchase_order_id)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test tests.test_api_email.EmailPoAPITest --noinput`
Expected: the new tests fail (contact not stored, `line_item_id` missing, 201 where 400 expected).

- [ ] **Step 3: Serializer**

Append to `apps/api/email/serializers.py`:

```python
from decimal import Decimal
from apps.api.inventory.serializers import OrderLineSerializer
from apps.inventory.models import InventoryItem


class EmailPOLineSerializer(OrderLineSerializer):
    """The email path has no fixed item, so `inventory_item` is allowed
    (null = freeform line, which then needs a description)."""
    inventory_item = serializers.PrimaryKeyRelatedField(
        queryset=InventoryItem.objects.all(), required=False, allow_null=True)
    qty = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))
    description = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        if attrs.get('inventory_item') is None and not attrs.get('description'):
            raise serializers.ValidationError(
                {'description': ['A freeform line needs a description.']})
        return attrs


class EmailCreatePOSerializer(serializers.Serializer):
    """POST /api/emails/{id}/create-po/ (PO order flow §4.3). The legacy
    `{vendor_business_id}` body is a valid subset."""
    vendor_business_id = serializers.IntegerField()
    contact_id = serializers.IntegerField(required=False, allow_null=True)
    requested_date = serializers.DateTimeField(required=False, allow_null=True)
    line = EmailPOLineSerializer(required=False, allow_null=True)
```

(`serializers` is already imported in that module as `from rest_framework import serializers`; check the top of the file and keep a single import.)

- [ ] **Step 4: View**

Replace `create_po_from_email` in `apps/api/email/views.py` (keep its decorators; Task 6 changes the permission class):

```python
def create_po_from_email(request, pk):
    """Create a Purchase Order from an email and link the email to it
    (PO order flow §4.3). Body: ``{vendor_business_id, contact_id?,
    requested_date?, line?}`` — the PO, the link and the optional first
    line land in one transaction. The old ``{vendor_business_id}`` body
    still works."""
    from django.db import transaction
    from apps.purchasing.services import PurchaseOrderService
    from .serializers import EmailCreatePOSerializer
    try:
        EmailRecord.objects.get(pk=pk)
    except EmailRecord.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    s = EmailCreatePOSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    v = s.validated_data
    try:
        business = Business.objects.get(pk=v['vendor_business_id'])
    except Business.DoesNotExist:
        return Response(
            {'vendor_business_id': [f'Business {v["vendor_business_id"]} not found.']},
            status=status.HTTP_404_NOT_FOUND,
        )
    contact = None
    if v.get('contact_id') is not None:
        contact = Contact.objects.filter(pk=v['contact_id']).first()
        if contact is None or contact.business_id != business.pk:
            return Response({'contact_id': ['Contact is not at this vendor.']},
                            status=status.HTTP_400_BAD_REQUEST)

    line = dict(v.get('line') or {})
    with transaction.atomic():
        po = PurchaseOrderService.create_po(
            business=business, contact=contact, requested_date=v.get('requested_date'))
        EmailService.associate_with(pk, 'purchase_order', po.pk)
        line_item_id = None
        if line:
            item = line.pop('inventory_item', None)
            qty = line.pop('qty')
            if item is not None:
                li = PurchaseOrderService.add_line_item_from_pli(po.pk, item.pk, qty, **line)
            else:
                manual = {k: val for k, val in line.items() if val is not None}
                li = PurchaseOrderService.add_line_item(po.pk, qty=qty, **manual)
            line_item_id = li.pk
    return Response(
        {'po_id': po.pk, 'po_number': po.po_number, 'line_item_id': line_item_id},
        status=status.HTTP_201_CREATED,
    )
```

`Business` and `Contact` are already imported at the top of the module.

- [ ] **Step 5: Run the tests**

Run: `python manage.py test tests.test_api_email --noinput`
Expected: `OK` (the legacy tests `test_create_po_from_email`, `test_create_po_missing_vendor`, `test_create_po_vendor_not_found` still pass).

- [ ] **Step 6: Commit**

```bash
git add apps/api/email/serializers.py apps/api/email/views.py tests/test_api_email.py
git commit -m "feat(email): create-po stores the contact and takes an optional first line, atomically"
```

---

### Task 5: Add-line guards and the provisional-material establish fix

**Files:**
- Modify: `apps/purchasing/services.py:569-610` (`add_line_item`)
- Modify: `apps/inventory/services.py:1167-1195` (`_apply_po_line_cost`), `:1197-1230` (`resolve_or_create_for_line`, explicit path)
- Test: `tests/test_po_line_guards.py`

**Interfaces:**
- Produces: `add_line_item` raises `ValidationError({'job': ['A comment line cannot be attributed to a job.']})` for `is_comment` + `job`/`material_id`; the resolver's explicit path raises `ValidationError({'material_id': ['This material needs <code>, not <code>.']})` on an item mismatch (both `add_line_item` and `add_line_item_from_pli` reach it — placed in the resolver rather than only in `add_line_item` because both entry points share the invariant); a provisional material named by `material_id` on a catalog line is established **onto the line's item**.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_po_line_guards.py
"""PO add-line guards (PO order flow §4.4): a comment line can't carry a
job; an explicit material_id must agree with the line's item; and a
provisional material on a catalog line is established onto that item
instead of minting a stray lot."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.inventory.models import InventoryItem, Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Job
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService


class _Base(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='po_number_sequence', defaults={'value': 'PO-{counter:04d}'})
        Configuration.objects.update_or_create(
            key='default_material_markup_percent', defaults={'value': '25'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})
        c = Contact.objects.create(first_name='V', last_name='V',
                                   phones=[{'number': '5', 'label': 'work'}])
        self.business = Business.objects.create(business_name='B', default_contact=c)
        c.business = self.business
        c.save()
        self.job = Job.objects.create(job_number='J-G', contact=c, description='j',
                                      status=Job.STATUS_APPROVED)
        self.cat = AccountingCategory.objects.get_or_create(
            code='MATG', defaults={'name': 'Material'})[0]
        self.ply = InventoryItem.objects.create(
            code='BBPLY.75', description='3/4 ply', purchase_price=Decimal('60.00'),
            selling_price=Decimal('80.00'), accounting_category=self.cat, units='sheet')
        self.mdf = InventoryItem.objects.create(
            code='MDF.75', description='3/4 mdf', purchase_price=Decimal('30.00'),
            selling_price=Decimal('40.00'), accounting_category=self.cat, units='sheet')
        self.po = PurchaseOrder.objects.create(business=self.business)


class CommentLineGuardTests(_Base):
    def test_comment_with_job_is_rejected_on_the_job_field(self):
        with self.assertRaises(ValidationError) as cm:
            PurchaseOrderService.add_line_item(
                self.po.pk, description='lead time 6 weeks', is_comment=True,
                qty=0, price=0, job=self.job.pk)
        self.assertIn('job', cm.exception.message_dict)
        self.assertEqual(Material.objects.filter(job=self.job).count(), 0)
        self.assertEqual(self.po.purchaseorderlineitem_set.count(), 0)

    def test_comment_with_material_id_is_rejected(self):
        mat = MaterialService.create_on_job(
            job=self.job, inventory_item=self.ply, quantity=Decimal('1'))
        with self.assertRaises(ValidationError) as cm:
            PurchaseOrderService.add_line_item(
                self.po.pk, description='note', is_comment=True, qty=0, price=0,
                material_id=mat.pk)
        self.assertIn('job', cm.exception.message_dict)

    def test_api_shape(self):
        user = User.objects.create_user('guard_admin', password='p', is_superuser=True)
        client = APIClient()
        client.force_authenticate(user)
        r = client.post(f'/api/purchase-orders/{self.po.pk}/line-items/', {
            'description': 'note', 'is_comment': True, 'qty': 0, 'price': 0,
            'units': 'none', 'job': self.job.pk}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('job', r.json())


class MaterialItemMismatchTests(_Base):
    def test_explicit_material_on_a_different_item_is_rejected(self):
        mat = MaterialService.create_on_job(
            job=self.job, inventory_item=self.ply, quantity=Decimal('2'))
        before = PurchaseOrderLineItem.objects.count()
        with self.assertRaises(ValidationError) as cm:
            PurchaseOrderService.add_line_item(
                self.po.pk, description='mdf', qty=Decimal('2'), price=Decimal('30.00'),
                inventory_item=self.mdf.pk, material_id=mat.pk)
        self.assertEqual(cm.exception.message_dict['material_id'],
                         ['This material needs BBPLY.75, not MDF.75.'])
        self.assertEqual(PurchaseOrderLineItem.objects.count(), before)
        mat.refresh_from_db()
        self.assertIsNone(mat.po_line_item_id)

    def test_pli_path_hits_the_same_guard(self):
        mat = MaterialService.create_on_job(
            job=self.job, inventory_item=self.ply, quantity=Decimal('2'))
        with self.assertRaises(ValidationError) as cm:
            PurchaseOrderService.add_line_item_from_pli(
                self.po.pk, self.mdf.pk, Decimal('2'), material_id=mat.pk)
        self.assertIn('material_id', cm.exception.message_dict)

    def test_matching_item_still_links(self):
        mat = MaterialService.create_on_job(
            job=self.job, inventory_item=self.ply, quantity=Decimal('2'))
        li = PurchaseOrderService.add_line_item_from_pli(
            self.po.pk, self.ply.pk, Decimal('2'), material_id=mat.pk)
        mat.refresh_from_db()
        self.assertEqual(mat.po_line_item_id, li.pk)


class ProvisionalEstablishTests(_Base):
    def test_catalog_line_establishes_provisional_material_onto_the_lines_item(self):
        prov = MaterialService.create_on_job(
            job=self.job, description='some ply', quantity=Decimal('2'),
            accounting_category=self.cat, units='sheet')
        self.assertIsNone(prov.inventory_item_id)
        lots_before = InventoryItem.objects.filter(code__startswith='LOT-').count()
        li = PurchaseOrderService.add_line_item(
            self.po.pk, description='3/4 ply', qty=Decimal('2'), price=Decimal('58.00'),
            inventory_item=self.ply.pk, material_id=prov.pk)
        prov.refresh_from_db()
        self.assertEqual(prov.inventory_item_id, self.ply.pk)
        self.assertEqual(prov.po_line_item_id, li.pk)
        self.assertEqual(prov.unit_cost, Decimal('58.00'))
        self.assertEqual(prov.cost_source, Material.COST_SOURCE_PO)
        self.assertEqual(InventoryItem.objects.filter(code__startswith='LOT-').count(), lots_before)
        li.refresh_from_db()
        self.assertEqual(li.inventory_item_id, self.ply.pk)

    def test_freeform_line_still_mints_a_lot_and_repoints_the_line(self):
        prov = MaterialService.create_on_job(
            job=self.job, description='custom bracket', quantity=Decimal('1'),
            accounting_category=self.cat, units='ea')
        li = PurchaseOrderService.add_line_item(
            self.po.pk, description='bracket', qty=Decimal('1'), price=Decimal('12.00'),
            material_id=prov.pk)
        prov.refresh_from_db()
        li.refresh_from_db()
        self.assertTrue(prov.inventory_item.code.startswith('LOT-'))
        self.assertEqual(li.inventory_item_id, prov.inventory_item_id)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test tests.test_po_line_guards --noinput`
Expected: comment/mismatch tests fail (no error raised); the establish test fails on `prov.inventory_item_id != self.ply.pk` (a `LOT-*` was minted).

- [ ] **Step 3: Guards**

`apps/purchasing/services.py`, `add_line_item`, right after the two `pop` lines:

```python
        if kwargs.get('is_comment') and (job_id is not None or material_id is not None):
            raise ValidationError({'job': ['A comment line cannot be attributed to a job.']})
```

`apps/inventory/services.py`, `resolve_or_create_for_line`, explicit path — after the `job` mismatch check and before `link_to_po_line`:

```python
                if (mat.inventory_item_id is not None and inventory_item is not None
                        and mat.inventory_item_id != inventory_item.pk):
                    raise ValidationError({'material_id': [
                        f'This material needs {mat.inventory_item.code}, '
                        f'not {inventory_item.code}.']})
```

`_apply_po_line_cost` — replace the provisional branch:

```python
        if material.inventory_item_id is None:
            # A catalog line establishes the material ONTO the line's item
            # (PO order flow §4.4) so receipt lands on the item the material
            # consumes from; only a freeform line mints a lot and repoints the
            # line at it.
            MaterialService.establish(
                material, inventory_item=po_line.inventory_item,
                unit_cost=price, cost_source=Material.COST_SOURCE_PO)
            if po_line.inventory_item_id is None:
                po_line.inventory_item = material.inventory_item
                po_line.save(update_fields=['inventory_item'])
```

Update the docstring's first bullet to say "establish it onto the line's item when the line has one, else mint a QOH-0 lot".

- [ ] **Step 4: Run the tests**

Run: `python manage.py test tests.test_po_line_guards tests.test_po_add_line_item_with_job tests.test_material_link_to_po_line tests.test_po_receive_with_material tests.test_po_change_line_job tests.test_comment_line_items tests.test_line_item_service_routing --noinput`
Expected: all `OK`.

- [ ] **Step 5: Commit**

```bash
git add apps/purchasing/services.py apps/inventory/services.py tests/test_po_line_guards.py
git commit -m "fix(purchasing): comment+job guard, material/item mismatch guard, establish onto the line's item"
```

---

### Task 6: Permissions — creation opens to jobs/PM, PO writes to jobs/linked PM

**Files:**
- Modify: `apps/api/permissions.py` (append three classes)
- Modify: `apps/purchasing/services.py` (`PurchaseOrderService`, after `create_po`: `linked_job_ids`, `user_can_manage`)
- Modify: `apps/api/purchasing/views.py:49-57` (`get_permissions`) + a `get_permission_target_po` method; `apps/api/purchasing/serializers.py:91-120` (`can_manage`)
- Modify: `apps/api/inventory/views.py` (`InventoryItemViewSet.get_permissions` order branch; `MaterialViewSet` gains `JobScopedPermissionMixin`; material `order` permission; action responses pass `context={'request': request}`)
- Modify: `apps/api/inventory/serializers.py:28-72`, `apps/api/tasks/serializers.py:13-41` (`JobScopedCanManageMixin`, `can_manage`); `apps/api/tasks/views.py:83-95` (request in context)
- Modify: `apps/api/email/views.py` (`create_po_from_email`, `sender_info` → `CanManageJobsOrFinancials`)
- Test: `tests/test_po_permissions.py`, `tests/test_permissions_combo.py` (extend), `tests/test_api_email.py` (`test_create_po_requires_can_manage_financials` → rename/extend)

**Interfaces:**
- Produces: `CanManageJobsOrFinancials`, `CanManageFinancialsOrJobOrPM`, `CanManageFinancialsOrJobsOrLinkedPM` in `apps/api/permissions.py`; `PurchaseOrderService.linked_job_ids(po) -> set[int]`, `PurchaseOrderService.user_can_manage(user, po) -> bool`; `PurchaseOrderViewSet.get_permission_target_po(request)`; `can_manage: bool` on `PurchaseOrderSerializer` and on both `MaterialSerializer`s.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_permissions_combo.py`:

```python
from apps.api.permissions import CanManageJobsOrFinancials


class JobsOrFinancialsPermTest(BaseTestCase):
    def _user(self, codename=None):
        u = User.objects.create_user(username=f'jof_{codename}', password='x')
        if codename:
            u.user_permissions.add(Permission.objects.get(
                codename=codename, content_type__app_label='core'))
            u = User.objects.get(pk=u.pk)
        return u

    def test_jobs_allowed(self):
        self.assertTrue(CanManageJobsOrFinancials().has_permission(
            _Req(self._user('can_manage_jobs')), None))

    def test_financials_allowed(self):
        self.assertTrue(CanManageJobsOrFinancials().has_permission(
            _Req(self._user('can_manage_financials')), None))

    def test_config_denied(self):
        # Purchasing is not an admin act (spec §6).
        self.assertFalse(CanManageJobsOrFinancials().has_permission(
            _Req(self._user('can_manage_config')), None))

    def test_neither_denied(self):
        self.assertFalse(CanManageJobsOrFinancials().has_permission(
            _Req(self._user()), None))
```

Create `tests/test_po_permissions.py`:

```python
"""PO order flow §6: creating a PO opens to the jobs atom (not a PM alone);
ordering a material opens to the PM of its job; every PO-level write opens
to the jobs atom and to the PM of any job linked to a line on that PO —
and that access drops as soon as the link does. reconcile stays
financials-only. `can_manage` on the PO and material serializers follows
the same rule."""
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration, EmailRecord, User
from apps.inventory.models import InventoryItem
from apps.inventory.services import MaterialService
from apps.jobs.models import Job, RateScheme, Task
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.services import PurchaseOrderService
from tests.base import grant_atoms


class _Base(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='po_number_sequence', defaults={'value': 'PO-{year}-{counter:04d}'})
        Configuration.objects.update_or_create(
            key='default_material_markup_percent', defaults={'value': '25'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Materials', code='MATPERM')
        vc = Contact.objects.create(first_name='V', last_name='V',
                                    phones=[{'number': '5', 'label': 'work'}])
        self.business = Business.objects.create(business_name='Vendor', default_contact=vc)
        vc.business = self.business
        vc.save()
        cust = Contact.objects.create(first_name='C', last_name='C',
                                      phones=[{'number': '1', 'label': 'work'}])
        self.pm = User.objects.create_user('pm_a', password='p')
        self.other_pm = User.objects.create_user('pm_b', password='p')
        self.fin = grant_atoms(User.objects.create_user('fin', password='p'), 'can_manage_financials')
        self.jobs = grant_atoms(User.objects.create_user('jobs', password='p'), 'can_manage_jobs')
        self.worker = User.objects.create_user('worker', password='p')
        self.job_a = Job.objects.create(job_number='J-A', contact=cust, description='a',
                                        status=Job.STATUS_APPROVED, project_manager=self.pm)
        self.job_b = Job.objects.create(job_number='J-B', contact=cust, description='b',
                                        status=Job.STATUS_APPROVED, project_manager=self.other_pm)
        self.item = InventoryItem.objects.create(
            code='PERM-1', description='x', accounting_category=self.cat,
            purchase_price=Decimal('5.00'), units='ea')
        self.material = MaterialService.create_on_job(
            job=self.job_a, inventory_item=self.item, description='x',
            quantity=Decimal('2'), unit_cost=Decimal('5.00'),
            accounting_category=self.cat, units='ea')
        self.client = APIClient()

    def _as(self, user):
        self.client.force_authenticate(user)

    def _po_body(self):
        return {'po': {'business': self.business.pk}}

    def _linked_po(self):
        """A draft PO whose one line is linked to job A's material (as fin)."""
        self._as(self.fin)
        r = self.client.post(f'/api/materials/{self.material.pk}/order/',
                             self._po_body(), format='json')
        assert r.status_code == 201, r.content
        return r.json()['po_id'], r.json()['line_item_id']


class PoCreatePermissionTests(_Base):
    def test_jobs_atom_can_create_po(self):
        self._as(self.jobs)
        r = self.client.post('/api/purchase-orders/', {'business': self.business.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_pm_alone_cannot_create_po(self):
        self._as(self.pm)
        r = self.client.post('/api/purchase-orders/', {'business': self.business.pk}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_worker_cannot_create_po(self):
        self._as(self.worker)
        r = self.client.post('/api/purchase-orders/', {'business': self.business.pk}, format='json')
        self.assertEqual(r.status_code, 403)


class OrderPermissionTests(_Base):
    def test_pm_of_the_materials_job_can_order_it(self):
        self._as(self.pm)
        r = self.client.post(f'/api/materials/{self.material.pk}/order/', self._po_body(), format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_pm_of_another_job_cannot_order_it(self):
        self._as(self.other_pm)
        r = self.client.post(f'/api/materials/{self.material.pk}/order/', self._po_body(), format='json')
        self.assertEqual(r.status_code, 403)

    def test_jobs_atom_can_order_stock_but_a_pm_cannot(self):
        body = {**self._po_body(), 'line': {'qty': '1'}}
        self._as(self.jobs)
        self.assertEqual(self.client.post(f'/api/inventory/{self.item.pk}/order/', body, format='json').status_code, 201)
        self._as(self.pm)
        self.assertEqual(self.client.post(f'/api/inventory/{self.item.pk}/order/', body, format='json').status_code, 403)

    def test_jobs_atom_can_create_po_from_email_and_read_sender_info(self):
        email = EmailRecord.objects.create(message_id='<perm-po@example.com>')
        self._as(self.jobs)
        r = self.client.post(f'/api/emails/{email.pk}/create-po/',
                             {'vendor_business_id': self.business.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self._as(self.fin)
        r = self.client.get(f'/api/emails/{email.pk}/sender-info/')
        self.assertNotEqual(r.status_code, 403)   # 503 (no cached content) is fine here


class PoWritePermissionTests(_Base):
    def test_pm_linked_via_material_can_write_the_po(self):
        po_id, _ = self._linked_po()
        self._as(self.pm)
        r = self.client.patch(f'/api/purchase-orders/{po_id}/', {'requested_date': '2026-11-01'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.post(f'/api/purchase-orders/{po_id}/line-items/',
                             {'description': 'extra', 'qty': 1, 'price': '1.00'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_pm_linked_via_task_can_write_the_po(self):
        scheme = RateScheme.objects.create(
            name='Perm Scheme', algorithm=RateScheme.ELAPSED_TIME, rate=Decimal('10.00'),
            unit_label='hour', accounting_category=self.cat)
        task = Task(job=self.job_a, name='Outsourced', sort_order=0)
        task.stamp_from_scheme(scheme)
        task.save()
        po = PurchaseOrderService.create_po(business=self.business)
        PurchaseOrderService.add_line_item(po.pk, description='outsourced', qty=1,
                                           price=Decimal('10.00'), task=task.pk)
        self._as(self.pm)
        r = self.client.patch(f'/api/purchase-orders/{po.pk}/', {'requested_date': '2026-11-01'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_unlinked_pm_and_worker_are_denied(self):
        po_id, _ = self._linked_po()
        for user in (self.other_pm, self.worker):
            self._as(user)
            r = self.client.patch(f'/api/purchase-orders/{po_id}/', {'requested_date': '2026-11-01'}, format='json')
            self.assertEqual(r.status_code, 403, user.username)

    def test_access_drops_after_the_linking_line_is_deleted(self):
        po_id, li = self._linked_po()
        self._as(self.pm)
        r = self.client.delete(f'/api/purchase-orders/{po_id}/line-items/{li}/')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.patch(f'/api/purchase-orders/{po_id}/', {'requested_date': '2026-11-01'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_access_drops_after_the_line_is_unjobbed(self):
        po_id, li = self._linked_po()
        self._as(self.pm)
        r = self.client.patch(f'/api/purchase-orders/{po_id}/line-items/{li}/',
                              {'job': None, 'sever_decision': 'keep'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.patch(f'/api/purchase-orders/{po_id}/', {'requested_date': '2026-11-01'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_jobs_atom_can_issue_and_delete(self):
        po_id, _ = self._linked_po()
        self._as(self.jobs)
        self.assertEqual(self.client.post(f'/api/purchase-orders/{po_id}/issue/', {}, format='json').status_code, 200)
        po2 = PurchaseOrderService.create_po(business=self.business)
        self.assertEqual(self.client.delete(f'/api/purchase-orders/{po2.pk}/?confirm=true').status_code, 200)

    def test_reconcile_stays_financials_only(self):
        po_id, _ = self._linked_po()
        for user in (self.jobs, self.pm):
            self._as(user)
            r = self.client.post(f'/api/purchase-orders/{po_id}/reconcile/', {}, format='json')
            self.assertEqual(r.status_code, 403, user.username)
        self._as(self.fin)
        r = self.client.post(f'/api/purchase-orders/{po_id}/reconcile/', {}, format='json')
        self.assertNotEqual(r.status_code, 403)


class CanManageFlagTests(_Base):
    def test_po_can_manage_follows_the_link(self):
        po_id, li = self._linked_po()
        expected = {self.pm: True, self.other_pm: False, self.worker: False,
                    self.jobs: True, self.fin: True}
        for user, flag in expected.items():
            self._as(user)
            self.assertEqual(self.client.get(f'/api/purchase-orders/{po_id}/').json()['can_manage'],
                             flag, user.username)
        self._as(self.fin)
        self.client.delete(f'/api/purchase-orders/{po_id}/line-items/{li}/')
        self._as(self.pm)
        self.assertFalse(self.client.get(f'/api/purchase-orders/{po_id}/').json()['can_manage'])

    def test_material_can_manage_for_the_jobs_pm(self):
        self._as(self.pm)
        self.assertTrue(self.client.get(f'/api/materials/{self.material.pk}/').json()['can_manage'])
        self.assertTrue(self.client.get(f'/api/jobs/{self.job_a.pk}/').json()['materials'][0]['can_manage'])
        self._as(self.other_pm)
        self.assertFalse(self.client.get(f'/api/materials/{self.material.pk}/').json()['can_manage'])
```

In `tests/test_api_email.py`, replace `test_create_po_requires_can_manage_financials` with:

```python
    def test_create_po_requires_jobs_or_financials(self):
        worker = User.objects.create_user(username='worker_create_po', password='pw')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/emails/{self.email.pk}/create-po/',
            {'vendor_business_id': self.business.pk}, format='json',
        )
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test tests.test_po_permissions tests.test_permissions_combo --noinput`
Expected: ImportError on `CanManageJobsOrFinancials`; 403s where 201/200 expected; `KeyError: 'can_manage'`.

- [ ] **Step 3: Permission classes**

Append to `apps/api/permissions.py`:

```python
class CanManageJobsOrFinancials(BasePermission):
    """Purchasing acts that start a PO (create, order a material or stock, PO
    from email) belong to the money role and the plan-builders alike — NOT
    config: purchasing is not an admin act (PO order flow §6)."""
    def has_permission(self, request, view):
        return (request.user.has_perm('core.can_manage_jobs')
                or request.user.has_perm('core.can_manage_financials'))


class CanManageFinancialsOrJobOrPM(BasePermission):
    """The financials atom, else CanManageJobOrPM (jobs atom, or PM of the
    request's target job via view.get_permission_target_job). Gates ordering
    a material: its job's PM may buy for that job."""
    def has_permission(self, request, view):
        if request.user.has_perm('core.can_manage_financials'):
            return True
        return CanManageJobOrPM().has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        if request.user.has_perm('core.can_manage_financials'):
            return True
        return CanManageJobOrPM().has_object_permission(request, view, obj)


class CanManageFinancialsOrJobsOrLinkedPM(BasePermission):
    """PO-level writes (RM 2026-10-15): the financials atom, the jobs atom, or
    the project_manager of ANY job linked to a line on the PO the URL names
    (a Material whose po_line_item is on it, or a task-attributed line whose
    task is on the job). Resolved per request from view.get_permission_target_po
    — no stored flag, so the access lasts exactly as long as the link."""
    def has_permission(self, request, view):
        from apps.purchasing.services import PurchaseOrderService
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if user.has_perm('core.can_manage_financials') or user.has_perm('core.can_manage_jobs'):
            return True
        po = view.get_permission_target_po(request)
        return po is not None and PurchaseOrderService.user_can_manage(user, po)
```

- [ ] **Step 4: Service helpers**

In `apps/purchasing/services.py`, `PurchaseOrderService`, after `create_po`:

```python
    @staticmethod
    def linked_job_ids(po):
        """Jobs tied to this PO through its lines: a Material whose
        po_line_item is on the PO, or a task-attributed line's task.job."""
        from apps.inventory.models import Material
        via_material = Material.objects.filter(
            po_line_item__purchase_order=po).values_list('job_id', flat=True)
        via_task = PurchaseOrderLineItem.objects.filter(
            purchase_order=po, task__isnull=False).values_list('task__job_id', flat=True)
        return set(via_material) | set(via_task)

    @staticmethod
    def user_can_manage(user, po):
        """May this user write to this PO (PO order flow §6)? financials or
        jobs atom, else PM of any linked job. Superusers pass via has_perm."""
        if user is None or not user.is_authenticated:
            return False
        if user.has_perm('core.can_manage_financials') or user.has_perm('core.can_manage_jobs'):
            return True
        if po is None:
            return False
        from apps.jobs.models import Job
        return Job.objects.filter(
            pk__in=PurchaseOrderService.linked_job_ids(po), project_manager_id=user.id).exists()
```

- [ ] **Step 5: PO viewset + serializer**

`apps/api/purchasing/views.py` — import the new classes and replace `get_permissions`:

```python
from apps.api.permissions import (
    CanManageFinancials, CanManageJobsOrFinancials, CanManageFinancialsOrJobsOrLinkedPM,
)
```

```python
    def get_permissions(self):
        if self.action in (
            'list', 'retrieve', 'history', 'notes', 'send_defaults',
            'receive', 'receive_all', 'receipts', 'cancel_line_item', 'reverse_receipt',
        ):
            return [IsAuthenticated()]
        if self.action == 'line_items' and self.request.method == 'GET':
            return [IsAuthenticated()]
        if self.action == 'create':
            # No PO to be linked to yet: atoms only (PO order flow §6).
            return [IsAuthenticated(), CanManageJobsOrFinancials()]
        if self.action == 'reconcile':
            # The bookkeeping half of the vendor bill stays with financials.
            return [IsAuthenticated(), CanManageFinancials()]
        return [IsAuthenticated(), CanManageFinancialsOrJobsOrLinkedPM()]

    def get_permission_target_po(self, request):
        """The PO the URL names, for CanManageFinancialsOrJobsOrLinkedPM."""
        pk = self.kwargs.get(self.lookup_url_kwarg or self.lookup_field)
        if pk is None:
            return None
        return PurchaseOrder.objects.filter(pk=pk).first()
```

`apps/api/purchasing/serializers.py`, `PurchaseOrderSerializer`: add `can_manage = serializers.SerializerMethodField()`, put `'can_manage'` at the end of `Meta.fields`, and:

```python
    def get_can_manage(self, obj):
        request = self.context.get('request')
        if request is None:
            return False
        from apps.purchasing.services import PurchaseOrderService
        return PurchaseOrderService.user_can_manage(request.user, obj)
```

- [ ] **Step 6: Inventory / material / task serializers and views**

`apps/api/inventory/serializers.py`: `from apps.api.mixins import JobScopedCanManageMixin`; `class MaterialSerializer(JobScopedCanManageMixin, InvoiceRefMixin, serializers.ModelSerializer):` with `can_manage_job_path = 'job'`; add `'can_manage'` to `Meta.fields` and `read_only_fields`.

`apps/api/tasks/serializers.py`: same three changes on its `MaterialSerializer` (`read_only_fields = fields` already covers it).

`apps/api/tasks/views.py`, `materials` GET: context becomes `{'request': request, 'invoice_claims': InvoiceClaimService.claims_for_job(task.job)}`.

`apps/api/inventory/views.py`:
- imports: `from apps.api.mixins import JobScopedPermissionMixin` and `CanManageJobsOrFinancials, CanManageFinancialsOrJobOrPM` from permissions.
- `InventoryItemViewSet.get_permissions` order branch → `return [IsAuthenticated(), CanManageJobsOrFinancials()]` (update the comment: "a purchasing act — financials or jobs, not config").
- `class MaterialViewSet(JobScopedPermissionMixin, viewsets.ModelViewSet):` with `job_object_path = 'job'`.
- material `order` decorator → `permission_classes=[IsAuthenticated, CanManageFinancialsOrJobOrPM]`.
- Every `MaterialSerializer(m).data` in `MaterialViewSet` actions (`partial_update`, `consume`, and the others at lines ~154-200) becomes `MaterialSerializer(m, context={'request': request}).data` so `can_manage` is populated on action responses.

`apps/api/email/views.py`: import `CanManageJobsOrFinancials`; `create_po_from_email` and `sender_info` decorators → `@permission_classes([IsAuthenticated, CanManageJobsOrFinancials])`. (`sender_info` feeds the Order modal's vendor tier for the email source; a financials-only user must be able to load it. **Deviation from the spec table — flag in the task report.**)

- [ ] **Step 7: Run the tests**

Run: `python manage.py test tests.test_po_permissions tests.test_permissions_combo tests.test_api_email tests.test_material_order_action tests.test_stock_order tests.test_atom_api_permissions tests.test_api_purchasing tests.test_material_qty_available tests.test_job_material_serializer_po_fields tests.test_po_serializer_material --noinput`
Expected: all `OK`. If `test_atom_api_permissions` pins the old financials-only expectation for PO create / inventory order, update that expectation to the new rule (jobs atom allowed, config denied) — the rule changed by decision, not by accident.

- [ ] **Step 8: Commit**

```bash
git add apps/api/permissions.py apps/purchasing/services.py apps/api/purchasing/views.py apps/api/purchasing/serializers.py apps/api/inventory/views.py apps/api/inventory/serializers.py apps/api/tasks/serializers.py apps/api/tasks/views.py apps/api/email/views.py tests/test_po_permissions.py tests/test_permissions_combo.py tests/test_api_email.py tests/test_atom_api_permissions.py
git commit -m "feat(permissions): PO creation opens to jobs/PM; PO writes open to jobs atom and linked PMs"
```

---

### Task 7: `VendorPicker.svelte`

**Files:**
- Create: `frontend/src/components/purchaseorders/VendorPicker.svelte`
- Test: `frontend/tests/components/purchaseorders/VendorPicker.test.js`

**Interfaces:**
- Consumes: `components/BusinessPicker.svelte` (`bind:value`, `onSelect(business|null)`, placeholder "Search business…"; its `SearchPicker` renders a selected chip with a "Clear" button).
- Produces: `<VendorPicker vendors={historyRows} bind:value onSelect={(row) => …} />`. `vendors` rows are the §4.1 `vendors` objects. `value` is the chosen business id or null. `onSelect` receives a history row (has `vendor_sku`), a business object from search (has `business_name`, `default_contact`), or `null`. On mount with non-empty `vendors`, the first row is preselected and `onSelect(vendors[0])` fires once.

- [ ] **Step 1: Write the failing tests**

```js
// frontend/tests/components/purchaseorders/VendorPicker.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import VendorPicker from '@/components/purchaseorders/VendorPicker.svelte';

const rows = [
  { business_id: 17, business_name: 'Rugby Architectural', contact_id: 88, last_ordered: '2026-08-02',
    last_price: '62.40', vendor_sku: 'BB34P-48', po_number: 'PO0120', times: 6 },
  { business_id: 59, business_name: 'Royal Plywood', contact_id: null, last_ordered: '2026-07-09',
    last_price: '73.33', vendor_sku: '', po_number: 'PO0012', times: 1 },
];

beforeEach(() => { api.get.mockReset(); api.get.mockResolvedValue({ results: [] }); });

describe('VendorPicker', () => {
  it('opens in recent mode, preselects the first vendor and reports it', () => {
    const onSelect = vi.fn();
    const { getByRole } = render(VendorPicker, { props: { vendors: rows, onSelect } });
    const select = getByRole('combobox');
    expect(select.value).toBe('17');
    expect(onSelect).toHaveBeenCalledWith(rows[0]);
    const labels = Array.from(select.options).map((o) => o.textContent);
    expect(labels[0]).toMatch(/Rugby Architectural/);
    expect(labels[0]).toMatch(/\$62\.40/);
    expect(labels[0]).toMatch(/SKU BB34P-48/);
    expect(labels[1]).not.toMatch(/SKU/);            // empty SKU segment omitted
    expect(labels.at(-1)).toMatch(/Search all businesses/);
  });

  it('choosing another recent vendor reports that row', async () => {
    const onSelect = vi.fn();
    const { getByRole } = render(VendorPicker, { props: { vendors: rows, onSelect } });
    await fireEvent.change(getByRole('combobox'), { target: { value: '59' } });
    expect(onSelect).toHaveBeenLastCalledWith(rows[1]);
  });

  it('"Search all businesses…" switches to the type-ahead with a back link; back restores recent', async () => {
    const onSelect = vi.fn();
    const { getByRole, getByPlaceholderText, queryByRole, getByText } = render(VendorPicker, { props: { vendors: rows, onSelect } });
    await fireEvent.change(getByRole('combobox'), { target: { value: '__search' } });
    expect(onSelect).toHaveBeenLastCalledWith(null);
    expect(getByPlaceholderText('Search business…')).toBeInTheDocument();
    expect(queryByRole('combobox')).toBeNull();
    await fireEvent.click(getByText('back to recent vendors'));
    expect(getByRole('combobox').value).toBe('17');
    expect(onSelect).toHaveBeenLastCalledWith(rows[0]);
  });

  it('a search pick reports the business; Clear returns to recent mode', async () => {
    api.get.mockResolvedValue({ results: [{ business_id: 5, business_name: 'Acme Steel', default_contact: 9 }] });
    const onSelect = vi.fn();
    const { getByRole, getByPlaceholderText, findByRole, queryByText } = render(VendorPicker, { props: { vendors: rows, onSelect } });
    await fireEvent.change(getByRole('combobox'), { target: { value: '__search' } });
    await fireEvent.input(getByPlaceholderText('Search business…'), { target: { value: 'ac' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole('button', { name: /Acme Steel/ }));
    expect(onSelect).toHaveBeenLastCalledWith(expect.objectContaining({ business_id: 5 }));
    expect(queryByText('back to recent vendors')).toBeNull();   // hidden once something is chosen
    await fireEvent.click(await findByRole('button', { name: 'Clear' }));
    expect(getByRole('combobox').value).toBe('17');
    expect(onSelect).toHaveBeenLastCalledWith(rows[0]);
  });

  it('with no history it opens in search mode with no back link', () => {
    const onSelect = vi.fn();
    const { getByPlaceholderText, queryByRole, queryByText } = render(VendorPicker, { props: { vendors: [], onSelect } });
    expect(getByPlaceholderText('Search business…')).toBeInTheDocument();
    expect(queryByRole('combobox')).toBeNull();
    expect(queryByText('back to recent vendors')).toBeNull();
    expect(onSelect).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npm run test:run tests/components/purchaseorders/VendorPicker.test.js`
Expected: FAIL — module not found.

- [ ] **Step 3: Component**

```svelte
<!-- frontend/src/components/purchaseorders/VendorPicker.svelte -->
<script>
  // Vendor tier of the Order modal (PO order flow §5.2). Two modes:
  //  - recent: a native <select> of the item's vendor-history rows (newest
  //    first, preselected to the first) plus a final "Search all
  //    businesses…" option;
  //  - search: the existing BusinessPicker type-ahead. While nothing is
  //    chosen and history exists, a "back to recent vendors" link returns;
  //    Clear on the picked chip returns to recent mode too.
  // Empty history opens straight in search mode with no back link.
  import BusinessPicker from '../BusinessPicker.svelte';

  let { vendors = [], value = $bindable(null), onSelect = () => {} } = $props();

  const SEARCH = '__search';
  // svelte-ignore state_referenced_locally -- mount-seed by design (history is loaded before this mounts)
  let mode = $state(vendors.length ? 'recent' : 'search');
  // svelte-ignore state_referenced_locally -- mount-seed by design
  let recentChoice = $state(vendors.length ? String(vendors[0].business_id) : '');
  let searchValue = $state(null);

  if (vendors.length && value == null) {
    value = vendors[0].business_id;
    onSelect(vendors[0]);
  }

  function money(n) { return `$${Number(n).toFixed(2)}`; }
  function optionLabel(v) {
    let s = `${v.business_name} — last ${v.last_ordered}`;
    if (v.last_price != null && v.last_price !== '') s += ` at ${money(v.last_price)}`;
    if (v.vendor_sku) s += ` · SKU ${v.vendor_sku}`;
    return s;
  }

  function onRecentChange(e) {
    const picked = e.target.value;
    if (picked === SEARCH) {
      mode = 'search';
      searchValue = null;
      value = null;
      onSelect(null);
      return;
    }
    recentChoice = picked;
    const row = vendors.find((v) => String(v.business_id) === picked);
    value = row.business_id;
    onSelect(row);
  }

  function backToRecent() {
    mode = 'recent';
    recentChoice = String(vendors[0].business_id);
    value = vendors[0].business_id;
    onSelect(vendors[0]);
  }

  function onSearchSelect(b) {
    if (b) { value = b.business_id; onSelect(b); return; }
    value = null;
    if (vendors.length) backToRecent(); else onSelect(null);
  }
</script>

{#if mode === 'recent'}
  <select id="vendor-recent" value={recentChoice} onchange={onRecentChange}>
    {#each vendors as v (v.business_id)}
      <option value={String(v.business_id)}>{optionLabel(v)}</option>
    {/each}
    <option value={SEARCH}>Search all businesses…</option>
  </select>
{:else}
  <BusinessPicker bind:value={searchValue} onSelect={onSearchSelect} />
  {#if searchValue == null && vendors.length}
    <p class="back"><button type="button" class="link-btn" onclick={backToRecent}>back to recent vendors</button></p>
  {/if}
{/if}

<style>
  select { max-width: 100%; }
  .back { margin: 4px 0 0; }
  .link-btn { background: none; border: 0; padding: 0; color: #2563eb; cursor: pointer; font-size: 13px; text-decoration: underline; }
</style>
```

(`BusinessPicker`'s input is auto-focused by the host modal's focus handling if any; no extra autofocus here — jsdom and the modal's drag grip both dislike it.)

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npm run test:run tests/components/purchaseorders/VendorPicker.test.js`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/purchaseorders/VendorPicker.svelte frontend/tests/components/purchaseorders/VendorPicker.test.js
git commit -m "feat(spa): VendorPicker — recent vendors select with a search escape hatch"
```

---

### Task 8: `OrderModal.svelte` (material + item sources) and its hosts

**Files:**
- Create: `frontend/src/components/purchaseorders/OrderModal.svelte`
- Modify: `frontend/src/components/materials/MaterialFulfillmentModals.svelte` (order half), `frontend/src/components/materials/MaterialRow.svelte:149`
- Modify: `frontend/src/routes/catalog/CatalogInventoryPage.svelte:3-6,36,220-223,266-267`, `frontend/src/routes/catalog/CatalogEarmarksPage.svelte:4-6,74,80-84`
- Delete: `frontend/src/components/inventory/StockOrderDialog.svelte`, `frontend/tests/components/inventory/StockOrderDialog.test.js`
- Test: `frontend/tests/components/purchaseorders/OrderModal.test.js` (new), `frontend/tests/components/tasks/TasksPanel.test.js:180-250`, `frontend/tests/components/TaskTree.test.js:330-350`

**Interfaces:**
- Consumes: `VendorPicker` (Task 7); `GET /api/inventory/{id}/` (item: `code, description, units, purchase_price, accounting_category`); `GET /api/inventory/{id}/vendor-history/?exclude_job=` (Task 2); `GET /api/accounting-categories/?page_size=100`; `GET /api/contacts/?business=<id>&page_size=100`; `GET /api/businesses/{id}/` (`default_contact`); `POST …/order/` (Task 3 body); `orderPrefillQty` (`lib/materials.js`); `stockShortfall` (`lib/stockShortfall.js`); `Modal`, `UnitsSelect`, `FieldError`, `FormMessage`, `triageError`, `showSuccess`, `push`.
- Produces: `<OrderModal source="material" material={m} onDone onCancel />` and `<OrderModal source="item" item={{inventory_item_id, code, description?}} prefillQty="3" onDone onCancel />`. Task 9 adds `source="email"`. Dialog `aria-label` is `"Order"`. Submit button text: `Create PO` or `Add to <po_number>`. On success: `showSuccess('Added to', {href, label})`, `onDone(resp)`, `push('/purchase-orders/<po_id>')`.

- [ ] **Step 1: Write the failing tests**

```js
// frontend/tests/components/purchaseorders/OrderModal.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => ({}) }));
vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e, f) => e?.message || f,
}));
vi.mock('@/stores/messages.js', () => ({ showSuccess: vi.fn(), showError: vi.fn() }));

import { push } from 'svelte-spa-router';
import { api } from '@/lib/api.js';
import { showSuccess } from '@/stores/messages.js';
import OrderModal from '@/components/purchaseorders/OrderModal.svelte';

const ITEM = { inventory_item_id: 7, code: 'BB34P', description: '3/4 Baltic Birch', units: 'sheet',
  purchase_price: '60.00', accounting_category: 3 };
const HISTORY = {
  vendors: [
    { business_id: 17, business_name: 'Rugby Architectural', contact_id: 88, last_ordered: '2026-08-02',
      last_price: '62.40', vendor_sku: 'BB34P-48', po_number: 'PO0120', times: 6 },
    { business_id: 59, business_name: 'Royal Plywood', contact_id: 98, last_ordered: '2026-07-09',
      last_price: '73.33', vendor_sku: 'RP-77', po_number: 'PO0012', times: 1 },
  ],
  earmarks: [{ job_id: 48, job_number: '08149', quantity: '3.00' }],
  open_drafts: [
    { po_id: 131, po_number: 'PO0131', business_id: 17, business_name: 'Rugby Architectural', line_count: 2 },
    { po_id: 132, po_number: 'PO0132', business_id: null, business_name: null, line_count: 0 },
  ],
};
const CONTACTS = {
  17: [{ contact_id: 88, first_name: 'Ann', last_name: 'Rugby' }, { contact_id: 89, first_name: 'Bob', last_name: 'Rugby' }],
  59: [{ contact_id: 98, first_name: 'Denis', last_name: 'Schneider' }],
};
const MATERIAL = { material_id: 55, job: 39, description: 'ply for cabinets', quantity: '4', units: 'sheet',
  unit_cost: '60.00', accounting_category: 3, inventory_item: 7, item_code: 'BB34P', qty_on_hand: '0',
  po_line_item_id: null, consumption_state: 'pending', cost_source: 'entered' };

function mockApi({ history = HISTORY } = {}) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/inventory/7/') return Promise.resolve(ITEM);
    if (url.startsWith('/api/inventory/7/vendor-history/')) return Promise.resolve(history);
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [{ id: 3, name: 'Materials' }] });
    if (url.startsWith('/api/contacts/?business=')) {
      const id = Number(new URL('http://x' + url).searchParams.get('business'));
      return Promise.resolve({ results: CONTACTS[id] || [] });
    }
    if (url.startsWith('/api/businesses/')) return Promise.resolve({ business_id: 5, business_name: 'Acme', default_contact: 9 });
    if (url.startsWith('/api/units')) return Promise.resolve(['none', 'sheet', 'ea']);
    return Promise.resolve([]);
  });
}

beforeEach(() => {
  mockApi();
  api.post.mockReset();
  api.post.mockResolvedValue({ po_id: 200, po_number: 'PO0200', line_item_id: 9 });
  showSuccess.mockReset();
  push.mockReset();
});

describe('OrderModal — material source', () => {
  it('seeds vendor, contact, SKU, price and qty from history and the material; item is read-only', async () => {
    const { findByRole, getByLabelText, getByText, queryByPlaceholderText } = render(OrderModal, {
      props: { source: 'material', material: MATERIAL, onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    expect((await findByRole('combobox', { name: /Vendor/ })).value).toBe('17');
    await waitFor(() => expect(getByLabelText(/Contact/).value).toBe('88'));
    expect(getByLabelText(/Vendor SKU/).value).toBe('BB34P-48');
    expect(getByLabelText(/^Price/).value).toBe('62.40');
    expect(getByLabelText(/^Qty/).value).toBe('4');
    expect(getByText(/BB34P/)).toBeInTheDocument();
    expect(queryByPlaceholderText('Search inventory items…')).toBeNull();
    expect(getByText(/Also needed: 08149 ×3/)).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/inventory/7/vendor-history/?exclude_job=39');
  });

  it('offers the vendor\'s open draft as an explicit choice; Submit is disabled until chosen', async () => {
    const { findByRole, getByRole, getByLabelText } = render(OrderModal, {
      props: { source: 'material', material: MATERIAL, onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    const addTo = await findByRole('radio', { name: /Add to PO0131 \(2 lines\)/ });
    expect(getByRole('radio', { name: /Start a new PO/ })).not.toBeChecked();
    expect(addTo).not.toBeChecked();
    expect(getByRole('button', { name: 'Create PO' })).toBeDisabled();
    await fireEvent.click(addTo);
    expect(getByRole('button', { name: 'Add to PO0131' })).toBeEnabled();
    // The draft already has a contact and date: those fields collapse.
    expect(() => getByLabelText(/Contact/)).toThrow();
    await fireEvent.click(getByRole('button', { name: 'Add to PO0131' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/materials/55/order/', {
      po_id: 131,
      line: { qty: '4', units: 'sheet', price: '62.40', description: 'ply for cabinets',
              vendor_sku: 'BB34P-48', accounting_category: 3 },
    }));
  });

  it('vendor-less drafts are never offered; Create PO posts the po block and navigates', async () => {
    const onDone = vi.fn();
    const { findByRole, getByRole, queryByRole, getByLabelText } = render(OrderModal, {
      props: { source: 'material', material: MATERIAL, onDone, onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    await findByRole('radio', { name: /Add to PO0131/ });
    expect(queryByRole('radio', { name: /PO0132/ })).toBeNull();
    await fireEvent.click(getByRole('radio', { name: /Start a new PO/ }));
    await fireEvent.input(getByLabelText(/Requested date/), { target: { value: '2026-10-20' } });
    await fireEvent.click(getByRole('button', { name: 'Create PO' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/materials/55/order/', {
      po: { business: 17, contact: 88, requested_date: '2026-10-20' },
      line: expect.objectContaining({ qty: '4', vendor_sku: 'BB34P-48' }),
    }));
    expect(showSuccess).toHaveBeenCalledWith('Added to', { href: '#/purchase-orders/200', label: 'PO0200' });
    expect(onDone).toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith('/purchase-orders/200');
  });

  it('switching vendor re-seeds SKU/price unless the SKU was hand-edited; no draft → no choice needed', async () => {
    const { findByRole, getByRole, getByLabelText, queryByRole } = render(OrderModal, {
      props: { source: 'material', material: MATERIAL, onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    const vendor = await findByRole('combobox', { name: /Vendor/ });
    await fireEvent.change(vendor, { target: { value: '59' } });
    await waitFor(() => expect(getByLabelText(/Vendor SKU/).value).toBe('RP-77'));
    expect(getByLabelText(/^Price/).value).toBe('73.33');
    await waitFor(() => expect(getByLabelText(/Contact/).value).toBe('98'));
    expect(queryByRole('radio')).toBeNull();                 // Royal has no open draft
    expect(getByRole('button', { name: 'Create PO' })).toBeEnabled();
    await fireEvent.input(getByLabelText(/Vendor SKU/), { target: { value: 'MINE-1' } });
    await fireEvent.change(vendor, { target: { value: '17' } });
    await waitFor(() => expect(getByLabelText(/^Price/).value).toBe('62.40'));
    expect(getByLabelText(/Vendor SKU/).value).toBe('MINE-1');
  });

  it('a contact_id from history that is no longer at the business falls back to the first contact', async () => {
    mockApi({ history: { ...HISTORY, vendors: [{ ...HISTORY.vendors[0], contact_id: 999 }] } });
    const { findByRole, getByLabelText } = render(OrderModal, {
      props: { source: 'material', material: MATERIAL, onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    await waitFor(() => expect(getByLabelText(/Contact/).value).toBe('88'));
  });

  it('shows a top-level business error under the vendor picker and keeps the form', async () => {
    mockApi({ history: { ...HISTORY, open_drafts: [] } });
    api.post.mockRejectedValue({ status: 400, data: { business: ['Rugby Architectural is inactive.'] } });
    const { findByRole, getByRole, findByText } = render(OrderModal, {
      props: { source: 'material', material: MATERIAL, onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    await fireEvent.click(getByRole('button', { name: 'Create PO' }));
    expect(await findByText('Rugby Architectural is inactive.')).toBeInTheDocument();
    expect(getByRole('button', { name: 'Create PO' })).toBeEnabled();
    expect(push).not.toHaveBeenCalled();
  });

  it('nested po.* and line.* errors land under their inputs; non_field_errors in the footer', async () => {
    mockApi({ history: { ...HISTORY, open_drafts: [] } });
    api.post.mockRejectedValue({ status: 400, data: {
      po: { contact: ['Contact is not at this vendor.'] }, line: { qty: ['Ensure this value is greater than or equal to 0.01.'] },
      non_field_errors: ['Provide exactly one of po_id or po.'] } });
    const { findByRole, getByRole, findByText } = render(OrderModal, {
      props: { source: 'material', material: MATERIAL, onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    await fireEvent.click(getByRole('button', { name: 'Create PO' }));
    expect(await findByText('Contact is not at this vendor.')).toBeInTheDocument();
    expect(await findByText(/greater than or equal to 0.01/)).toBeInTheDocument();
    expect(await findByText('Provide exactly one of po_id or po.')).toBeInTheDocument();
  });
});

describe('OrderModal — item source', () => {
  it('with no history opens in search mode, prefills qty from the host, and posts to the inventory endpoint', async () => {
    mockApi({ history: { vendors: [], earmarks: [], open_drafts: [] } });
    api.get.mockImplementation((url) => {
      if (url === '/api/inventory/7/') return Promise.resolve(ITEM);
      if (url.startsWith('/api/inventory/7/vendor-history/')) return Promise.resolve({ vendors: [], earmarks: [], open_drafts: [] });
      if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [{ id: 3, name: 'Materials' }] });
      if (url.startsWith('/api/businesses/?search=')) return Promise.resolve({ results: [{ business_id: 5, business_name: 'Acme Steel', default_contact: 9 }] });
      if (url === '/api/businesses/5/') return Promise.resolve({ business_id: 5, business_name: 'Acme Steel', default_contact: 9 });
      if (url.startsWith('/api/contacts/?business=5')) return Promise.resolve({ results: [{ contact_id: 9, first_name: 'Sam', last_name: 'Acme' }] });
      return Promise.resolve([]);
    });
    const { findByRole, findByPlaceholderText, getByLabelText, getByRole } = render(OrderModal, {
      props: { source: 'item', item: { inventory_item_id: 7, code: 'BB34P' }, prefillQty: '3', onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    const search = await findByPlaceholderText('Search business…');
    expect(getByLabelText(/^Qty/).value).toBe('3');
    expect(getByLabelText(/^Price/).value).toBe('60.00');       // item default
    expect(getByRole('button', { name: 'Create PO' })).toBeDisabled();   // no vendor yet
    await fireEvent.input(search, { target: { value: 'ac' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole('button', { name: /Acme Steel/ }));
    await waitFor(() => expect(getByLabelText(/Contact/).value).toBe('9'));
    await fireEvent.click(getByRole('button', { name: 'Create PO' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/inventory/7/order/', {
      po: { business: 5, contact: 9, requested_date: null },
      line: { qty: '3', units: 'sheet', price: '60.00', description: '3/4 Baltic Birch', vendor_sku: '', accounting_category: 3 },
    }));
  });

  it('a blank qty is reported under the field before any request', async () => {
    const { findByRole, getByLabelText, getByRole, findByText } = render(OrderModal, {
      props: { source: 'item', item: { inventory_item_id: 7, code: 'BB34P' }, prefillQty: '0', onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    await findByRole('combobox', { name: /Vendor/ });
    await fireEvent.input(getByLabelText(/^Qty/), { target: { value: '' } });
    await fireEvent.click(getByRole('button', { name: 'Create PO' }));
    expect(await findByText('Enter a quantity greater than 0.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('Cancel calls onCancel and nothing is posted', async () => {
    const onCancel = vi.fn();
    const { findByRole, getByRole } = render(OrderModal, {
      props: { source: 'item', item: { inventory_item_id: 7, code: 'BB34P' }, prefillQty: '1', onDone: vi.fn(), onCancel },
    });
    await findByRole('dialog', { name: 'Order' });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npm run test:run tests/components/purchaseorders/OrderModal.test.js`
Expected: FAIL — module not found.

- [ ] **Step 3: Component**

```svelte
<!-- frontend/src/components/purchaseorders/OrderModal.svelte -->
<script>
  // THE Order modal (PO order flow §5.1): a PO header plus one line, which
  // creates nothing until Submit. Three sources — `material` (MaterialRow
  // "Order"), `item` (catalog "order"), `email` (email action panel "Create
  // new" PO, Task 9). The item is fixed for material/item sources; vendor
  // comes from the item's history (VendorPicker) and, once known, the
  // vendor's open drafts are offered as an explicit append-or-new choice.
  import { push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError, showSuccess } from '../../stores/messages.js';
  import { orderPrefillQty } from '../../lib/materials.js';
  import Modal from '../Modal.svelte';
  import UnitsSelect from '../UnitsSelect.svelte';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';
  import VendorPicker from './VendorPicker.svelte';

  let {
    source,                 // 'material' | 'item' | 'email'
    material = null,        // source === 'material'
    item = null,            // source === 'item': { inventory_item_id, code, description? }
    prefillQty = '',        // source === 'item'
    emailRecordId = null,   // source === 'email' (Task 9)
    onDone = () => {},
    onCancel = () => {},
  } = $props();

  const itemId = $derived(source === 'material' ? material?.inventory_item : item?.inventory_item_id);

  let loading = $state(true);
  let itemDetail = $state(null);
  let history = $state(null);     // { vendors, earmarks, open_drafts }
  let categories = $state([]);

  let vendorId = $state(null);
  let vendorRow = $state(null);   // history row or business object
  let contacts = $state([]);
  let contactId = $state('');
  let requestedDate = $state('');
  let draftChoice = $state(null); // null | 'new' | po_id

  let form = $state({ qty: '', units: 'none', price: '', description: '', vendor_sku: '', accounting_category: '' });
  let skuTouched = $state(false);
  let qtyError = $state('');
  let busy = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});

  const draftsForVendor = $derived(
    vendorId == null ? [] : (history?.open_drafts || []).filter((d) => d.business_id === vendorId));
  const appendTarget = $derived(
    draftChoice && draftChoice !== 'new' ? draftsForVendor.find((d) => d.po_id === draftChoice) : null);
  const choiceNeeded = $derived(draftsForVendor.length > 0 && draftChoice == null);
  const canSubmit = $derived(!busy && !loading && vendorId != null && !choiceNeeded);

  async function load() {
    loading = true;
    try {
      const excl = source === 'material' && material?.job ? `?exclude_job=${material.job}` : '';
      const [it, hist, cats] = await Promise.all([
        api.get(`/api/inventory/${itemId}/`),
        api.get(`/api/inventory/${itemId}/vendor-history/${excl}`),
        api.get('/api/accounting-categories/?page_size=100'),
      ]);
      itemDetail = it;
      categories = cats.results || cats;
      // Line defaults: the item's, then (material source) the material's.
      form.description = it.description || '';
      form.units = it.units || 'none';
      form.price = it.purchase_price ?? '';
      form.accounting_category = it.accounting_category ?? '';
      if (source === 'material') {
        form.qty = orderPrefillQty(material);
        form.description = material.description || form.description;
        form.units = material.units || form.units;
        if (material.unit_cost != null) form.price = material.unit_cost;
        if (material.accounting_category) form.accounting_category = material.accounting_category;
      } else {
        form.qty = prefillQty;
      }
      history = hist;   // VendorPicker mounts now and preselects the first vendor
    } catch (e) {
      const t = triageError(e);
      showError(t.overlay || t.message || 'Could not load vendor history.');
      onCancel();
    } finally {
      loading = false;
    }
  }
  $effect(() => { void itemId; load(); });

  async function handleVendor(row) {
    vendorRow = row;
    draftChoice = null;
    fieldErrs = {};
    if (!row) { vendorId = null; contacts = []; contactId = ''; return; }
    vendorId = row.business_id;
    const isHistory = 'vendor_sku' in row;
    if (isHistory) {
      if (!skuTouched) form.vendor_sku = row.vendor_sku || '';
      if (row.last_price != null && row.last_price !== '') form.price = row.last_price;
    }
    const [contactData, biz] = await Promise.all([
      api.get(`/api/contacts/?business=${row.business_id}&page_size=100`),
      isHistory ? api.get(`/api/businesses/${row.business_id}/`) : Promise.resolve(row),
    ]);
    if (vendorId !== row.business_id) return;   // vendor changed while loading
    contacts = contactData.results || contactData;
    const preferred = [isHistory ? row.contact_id : null, biz?.default_contact, contacts[0]?.contact_id]
      .find((id) => id != null && contacts.some((c) => c.contact_id === id));
    contactId = preferred ?? '';
  }

  function linePayload() {
    return {
      qty: String(form.qty).trim(),
      units: form.units || 'none',
      price: form.price === '' || form.price == null ? null : String(form.price),
      description: form.description,
      vendor_sku: form.vendor_sku,
      accounting_category: form.accounting_category ? Number(form.accounting_category) : null,
    };
  }

  async function submit(e) {
    e.preventDefault();
    qtyError = ''; formError = ''; fieldErrs = {};
    if (!String(form.qty).trim() || Number(form.qty) <= 0) {
      qtyError = 'Enter a quantity greater than 0.';
      return;
    }
    if (!canSubmit) return;
    const line = linePayload();
    const body = appendTarget
      ? { po_id: appendTarget.po_id, line }
      : { po: { business: vendorId, contact: contactId === '' ? null : Number(contactId),
                requested_date: requestedDate || null }, line };
    const url = source === 'material'
      ? `/api/materials/${material.material_id}/order/`
      : `/api/inventory/${itemId}/order/`;
    busy = true;
    try {
      const resp = await api.post(url, body);
      showSuccess('Added to', { href: `#/purchase-orders/${resp.po_id}`, label: resp.po_number });
      onDone(resp);
      push(`/purchase-orders/${resp.po_id}`);
    } catch (err) {
      const t = triageError(err);
      if (t.overlay) { showError(t.overlay); return; }
      formError = t.message;
      // Nested po.* / line.* bags plus the service's top-level `business`
      // (an inactive vendor) all land under their inputs.
      fieldErrs = { ...(t.fields.po || {}), ...(t.fields.line || {}), ...t.fields };
    } finally {
      busy = false;
    }
  }

  const submitLabel = $derived(appendTarget ? `Add to ${appendTarget.po_number}` : 'Create PO');
  const itemCode = $derived(itemDetail?.code?.startsWith('LOT-') ? '' : itemDetail?.code);
</script>

<!-- Native <form> owns Enter; the shell wires Escape. -->
<Modal open={true} onCancel={onCancel} busy={busy} maxWidth="720px" label="Order">
  <h3 class="modal-title">Order — {itemCode || itemDetail?.description || material?.description || ''}</h3>
  {#if loading}
    <p>Loading…</p>
  {:else if history}
    <form onsubmit={submit}>
      <p>
        <label for="vendor-recent"><strong>Vendor *</strong></label><br>
        <VendorPicker vendors={history.vendors} onSelect={handleVendor} />
        <FieldError errors={fieldErrs} field="business" />
      </p>

      {#if !appendTarget}
        <p>
          <label for="order-contact"><strong>Contact</strong></label><br>
          <select id="order-contact" bind:value={contactId} disabled={vendorId == null}>
            <option value="">— none —</option>
            {#each contacts as c (c.contact_id)}
              <option value={c.contact_id}>{c.first_name} {c.last_name}</option>
            {/each}
          </select>
          <FieldError errors={fieldErrs} field="contact" />
        </p>
        <p>
          <label for="order-date"><strong>Requested date</strong></label><br>
          <input id="order-date" type="date" bind:value={requestedDate}>
          <FieldError errors={fieldErrs} field="requested_date" />
        </p>
      {/if}

      {#if draftsForVendor.length}
        <fieldset class="drafts">
          <legend>Open drafts for this vendor</legend>
          <label><input type="radio" bind:group={draftChoice} value="new"> Start a new PO</label>
          {#each draftsForVendor as d (d.po_id)}
            <label><input type="radio" bind:group={draftChoice} value={d.po_id}>
              Add to {d.po_number} ({d.line_count} {d.line_count === 1 ? 'line' : 'lines'})</label>
          {/each}
        </fieldset>
      {/if}

      <fieldset class="line">
        <legend>Line</legend>
        <p><strong>Item:</strong> {#if itemCode}<code class="mat-code">{itemCode}</code>{/if} {itemDetail.description}</p>
        <p>
          <label for="order-qty"><strong>Qty *</strong></label><br>
          <input id="order-qty" type="number" step="any" min="0" bind:value={form.qty} oninput={() => qtyError = ''}>
          {#if qtyError}<span class="field-error">{qtyError}</span>{/if}
          <FieldError errors={fieldErrs} field="qty" />
          {#if history.earmarks.length}
            <br><small class="earmarks">Also needed: {history.earmarks.map((e) => `${e.job_number} ×${String(Number(e.quantity))}`).join(', ')}</small>
          {/if}
        </p>
        <p>
          <label for="order-units"><strong>Units</strong></label><br>
          <UnitsSelect id="order-units" bind:value={form.units} />
          <FieldError errors={fieldErrs} field="units" />
        </p>
        <p>
          <label for="order-price"><strong>Price</strong></label><br>
          <input id="order-price" type="number" step="0.01" min="0" bind:value={form.price}>
          <FieldError errors={fieldErrs} field="price" />
        </p>
        <p>
          <label for="order-description"><strong>Description</strong></label><br>
          <input id="order-description" type="text" bind:value={form.description}>
          <FieldError errors={fieldErrs} field="description" />
        </p>
        <p>
          <label for="order-sku"><strong>Vendor SKU</strong></label><br>
          <input id="order-sku" type="text" maxlength="100" bind:value={form.vendor_sku} oninput={() => skuTouched = true}>
          <FieldError errors={fieldErrs} field="vendor_sku" />
        </p>
        <p>
          <label for="order-category"><strong>Category</strong></label><br>
          <select id="order-category" bind:value={form.accounting_category}>
            <option value="">-- None --</option>
            {#each categories.filter((c) => !c.is_fallback) as cat (cat.id)}
              <option value={cat.id}>{cat.name}</option>
            {/each}
          </select>
          <FieldError errors={fieldErrs} field="accounting_category" />
        </p>
      </fieldset>

      <p class="dialog-actions">
        <button type="submit" disabled={!canSubmit}>{submitLabel}</button>
        <button type="button" onclick={onCancel} disabled={busy}>Cancel</button>
      </p>
      <FormMessage error={formError} />
    </form>
  {/if}
</Modal>

<style>
  .modal-title { margin: 0 0 12px; font-size: 16px; }
  .drafts, .line { margin: 8px 0; }
  .drafts label { display: block; }
  .earmarks { color: #555; }
  .field-error { color: #c00; font-size: 0.9em; margin-left: 6px; }
  .mat-code { font-size: 11px; color: #374151; background: #f3f4f6; border: 1px solid #d1d5db; border-radius: 3px; padding: 0 4px; }
  .dialog-actions { display: flex; gap: 8px; margin-top: 12px; }
</style>
```

Notes for the implementer:
- `UnitsSelect` accepts an `id` prop (`frontend/src/components/UnitsSelect.svelte`), so `<label for="order-units">` names it.
- `VendorPicker` calls `onSelect(vendors[0])` during its own script init. That is a synchronous parent-state write from inside the parent's mount, which Svelte 5 permits. If the runtime nonetheless raises `state_unsafe_mutation`, move that seed into `$effect.pre(() => { if (!seeded && vendors.length && value == null) { seeded = true; value = vendors[0].business_id; onSelect(vendors[0]); } })` with `let seeded = false;` — the tests already `await` the resulting state.
- The `"Vendor *"` label's `for="vendor-recent"` matches the select's id in recent mode (the test queries `combobox` by `/Vendor/`). In search mode the `BusinessPicker` input is reached by placeholder.
- `history` is assigned last in `load()` so `VendorPicker` mounts with the final `vendors` and its mount-time preselect calls `handleVendor` once.

- [ ] **Step 4: Hosts — material rows**

`MaterialFulfillmentModals.svelte`: delete `orderDialogOpen`, `orderDrafts`, `orderBusy`, `submitOrder`, `closeOrderDialog`, the order `<Modal>` block and its styles; `startOrder` becomes:

```js
  import OrderModal from '../purchaseorders/OrderModal.svelte';
  let orderMaterial = $state(null);
  export function startOrder(material) { orderMaterial = material; }
```

and the markup:

```svelte
{#if orderMaterial}
  <OrderModal source="material" material={orderMaterial}
    onDone={async () => { orderMaterial = null; await onDone(); }}
    onCancel={() => { orderMaterial = null; }} />
{/if}
```

Remove the now-unused `api`/`showSuccess` imports if nothing else in the file uses them (the receipt flow still uses `api`, `showError`, `triageError`).

`MaterialRow.svelte:149`: `{#if onOrderMaterial && ($canManageFinancials || mat.can_manage) && mat.po_line_item_id == null}`.

- [ ] **Step 5: Hosts — catalog pages**

`CatalogInventoryPage.svelte`: import `OrderModal` instead of `StockOrderDialog`; import `canManageJobs` from the permissions store; the order button gate becomes `{#if $canManageFinancials || $canManageJobs}`; the modal block:

```svelte
{#if orderItem}
  <OrderModal source="item" item={orderItem} prefillQty={stockShortfall(orderItem)}
    onDone={() => { orderItem = null; load(); }}
    onCancel={() => orderItem = null} />
{/if}
```

`CatalogEarmarksPage.svelte`: same import swap; the actions column gate `($canManageFinancials || $canManageJobs)`; the modal:

```svelte
{#if orderRow}
  <OrderModal source="item"
    item={{ inventory_item_id: orderRow.inventory_item, code: orderRow.item_code, description: orderRow.item_description }}
    prefillQty={stockShortfall(orderRow)}
    onDone={() => { orderRow = null; load(); }}
    onCancel={() => orderRow = null} />
{/if}
```

Delete `frontend/src/components/inventory/StockOrderDialog.svelte` and `frontend/tests/components/inventory/StockOrderDialog.test.js` (`git rm`).

- [ ] **Step 6: Update the TasksPanel and TaskTree tests**

In `frontend/tests/components/tasks/TasksPanel.test.js` replace the three Order tests (`'Order with zero drafts POSTs immediately…'`, `'Order with drafts opens the chooser…'`, `'a draft with no vendor renders "no vendor"'`) with one that asserts the modal opens and is seeded; extend `mockApiWithMaterial` so `/api/inventory/7/`, `/api/inventory/7/vendor-history/…`, `/api/contacts/?business=`, `/api/businesses/` resolve (reuse the fixtures from `OrderModal.test.js`, inline — do not import across test files):

```js
  it('Order opens the Order modal seeded from the material and its vendor history', async () => {
    user.set({ id: 1, permissions: ['can_manage_financials'] });
    mockApiWithMaterial(neededMat);
    const { findByRole } = render(TasksPanel, { props: { job: jobWithMaterial() } });
    await fireEvent.click(await findByRole('button', { name: 'Order' }));
    const dialog = await findByRole('dialog', { name: 'Order' });
    expect(dialog).toBeInTheDocument();
    expect((await findByRole('combobox', { name: /Vendor/ })).value).toBe('17');
    expect(api.post).not.toHaveBeenCalled();     // nothing is created until Submit
  });
```

In `frontend/tests/components/TaskTree.test.js`, rename `'needed material gates the Order button behind can_manage_financials'` to `'needed material gates the Order button behind can_manage_financials or the material's can_manage'` and append after the `fin` assertion (the test's `mat`, `matTask`, `wired` locals are already in scope):

```js
    fin.unmount();
    // a PM of the material's job (no atom) sees it too — the row's own can_manage flag
    user.set({ id: 1, permissions: [] });
    const pm = render(TaskTree, { props: { tasks: [matTask({ ...mat, can_manage: true })], canManage: true, ...wired } });
    expect(pm.getByRole('button', { name: 'Order' })).toBeInTheDocument();
```

- [ ] **Step 7: Run the frontend suite**

Run: `cd frontend && npm run test:run`
Expected: all green; `StockOrderDialog.test.js` gone; `OrderModal.test.js` 10 tests pass.

- [ ] **Step 8: Commit**

```bash
git add -A frontend/src/components/purchaseorders/OrderModal.svelte frontend/src/components/materials frontend/src/routes/catalog frontend/src/components/inventory frontend/tests/components/purchaseorders/OrderModal.test.js frontend/tests/components/tasks/TasksPanel.test.js frontend/tests/components/TaskTree.test.js frontend/tests/components/inventory
git commit -m "feat(spa): OrderModal replaces the material and catalog one-click order dialogs"
```

---

### Task 9: `OrderModal` email source; the create-PO page becomes a route stub

**Files:**
- Modify: `frontend/src/components/purchaseorders/OrderModal.svelte` (email branch)
- Modify: `frontend/src/lib/email.js:15-16` (`createPo`)
- Modify: `frontend/src/components/email/EmailActionPanel.svelte:10-11,67-84`
- Modify: `frontend/src/routes/email/EmailDetailPage.svelte:85-90`
- Modify: `frontend/src/App.svelte:53,114`
- Delete: `frontend/src/routes/email/EmailCreatePOPage.svelte`
- Test: `frontend/tests/components/purchaseorders/OrderModal.test.js` (add an email `describe`), `frontend/tests/components/email/EmailActionPanel.test.js:48-62`

**Interfaces:**
- Consumes: `emailApi.senderInfo(id)`, `resolveSenderToContact(state)` (`lib/email.js`), `SenderResolutionForm` (`bind:state`), `DuplicateContactNotice` / `DuplicateBusinessNotice` (`components/contacts/`), `InventoryItemPicker`, `POST /api/emails/{id}/create-po/` (Task 4 body), `GET /api/contacts/{id}/` (`business` field).
- Produces: `emailApi.createPo(id, body)` passes the body through unchanged; `<OrderModal source="email" emailRecordId={id} onDone onCancel />`; `EmailActionPanel` emits `onAction('create-po')`; `/email/:id/create-po` redirects to `/email/:id`.

- [ ] **Step 1: Write the failing tests**

Append to `OrderModal.test.js` (add `vi.mock('@/lib/email.js', …)` next to the other mocks, and import `emailApi`, `resolveSenderToContact`):

```js
vi.mock('@/lib/email.js', () => ({
  emailApi: { senderInfo: vi.fn(), createPo: vi.fn() },
  resolveSenderToContact: vi.fn(),
}));
import { emailApi, resolveSenderToContact } from '@/lib/email.js';

describe('OrderModal — email source', () => {
  const SENDER = { sender_name: 'Jack Moore', sender_email: 'jack@mnh.com', subject: 'Invoice MNH-20441',
    matching_contacts: [{ id: 100, name: 'Jack Moore' }], matching_businesses: [] };

  beforeEach(() => {
    emailApi.senderInfo.mockReset(); emailApi.createPo.mockReset(); resolveSenderToContact.mockReset();
    emailApi.senderInfo.mockResolvedValue(SENDER);
    emailApi.createPo.mockResolvedValue({ po_id: 300, po_number: 'PO0300', line_item_id: null });
    api.get.mockImplementation((url) => {
      if (url === '/api/contacts/100/') return Promise.resolve({ contact_id: 100, business: 61 });
      if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [{ id: 3, name: 'Materials' }] });
      if (url.startsWith('/api/inventory/?')) return Promise.resolve({ results: [ITEM] });
      return Promise.resolve([]);
    });
  });

  it('shows the sender-resolution form, no vendor picker, and creates a header-only PO from the matched contact', async () => {
    resolveSenderToContact.mockResolvedValue({ contactId: 100, businessId: null });
    const onDone = vi.fn();
    const { findByRole, getByRole, queryByPlaceholderText, queryByLabelText } = render(OrderModal, {
      props: { source: 'email', emailRecordId: 10, onDone, onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    await findByRole('heading', { name: 'Sender' });
    expect(queryByPlaceholderText('Search business…')).toBeNull();
    expect(queryByLabelText(/^Qty/)).toBeNull();            // line is opt-in
    await fireEvent.click(getByRole('button', { name: 'Create PO' }));
    await waitFor(() => expect(emailApi.createPo).toHaveBeenCalledWith(10, {
      vendor_business_id: 61, contact_id: 100, requested_date: null,
    }));
    expect(onDone).toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith('/purchase-orders/300');
  });

  it('"Add a first line" reveals an item picker and the line fields; the line rides along', async () => {
    resolveSenderToContact.mockResolvedValue({ contactId: 100, businessId: 61 });
    const { findByRole, getByRole, getByLabelText, findByPlaceholderText, container } = render(OrderModal, {
      props: { source: 'email', emailRecordId: 10, onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    await findByRole('heading', { name: 'Sender' });
    await fireEvent.click(getByLabelText('Add a first line'));
    const picker = await findByPlaceholderText('Search inventory items…');
    await fireEvent.input(picker, { target: { value: 'bb' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole('button', { name: /BB34P/ }));
    await waitFor(() => expect(getByLabelText(/^Price/).value).toBe('60.00'));
    await fireEvent.input(getByLabelText(/^Qty/), { target: { value: '2' } });
    await fireEvent.input(getByLabelText(/Vendor SKU/), { target: { value: 'MNH-1' } });
    await fireEvent.click(getByRole('button', { name: 'Create PO' }));
    await waitFor(() => expect(emailApi.createPo).toHaveBeenCalledWith(10, expect.objectContaining({
      vendor_business_id: 61,
      line: { inventory_item: 7, qty: '2', units: 'sheet', price: '60.00', description: '3/4 Baltic Birch',
              vendor_sku: 'MNH-1', accounting_category: 3 },
    })));
  });

  it('a sender with no business is reported in the footer, not sent', async () => {
    resolveSenderToContact.mockResolvedValue({ contactId: 100, businessId: null });
    api.get.mockImplementation((url) => url === '/api/contacts/100/'
      ? Promise.resolve({ contact_id: 100, business: null })
      : Promise.resolve({ results: [] }));
    const { findByRole, getByRole, findByText } = render(OrderModal, {
      props: { source: 'email', emailRecordId: 10, onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    await findByRole('heading', { name: 'Sender' });
    await fireEvent.click(getByRole('button', { name: 'Create PO' }));
    expect(await findByText(/vendor business is required/i)).toBeInTheDocument();
    expect(emailApi.createPo).not.toHaveBeenCalled();
  });

  it('duplicate contact → in-modal notice; Go Back returns to the form', async () => {
    emailApi.senderInfo.mockResolvedValue({ ...SENDER, matching_contacts: [] });
    resolveSenderToContact.mockRejectedValue({ status: 409, data: { code: 'duplicate_email',
      existing_contact: { contact_id: 9, name: 'Jack Moore', email: 'jack@mnh.com' } } });
    const { findByRole, getByRole, findByText } = render(OrderModal, {
      props: { source: 'email', emailRecordId: 10, onDone: vi.fn(), onCancel: vi.fn() },
    });
    await findByRole('dialog', { name: 'Order' });
    await findByRole('heading', { name: 'Sender' });
    await fireEvent.click(getByRole('button', { name: 'Create PO' }));
    expect(await findByText('This contact may already exist')).toBeInTheDocument();
    expect(document.querySelectorAll('[role="dialog"]').length).toBe(1);
    await fireEvent.click(getByRole('button', { name: 'Go Back and Edit' }));
    expect(await findByRole('heading', { name: 'Sender' })).toBeInTheDocument();
  });
});
```

In `EmailActionPanel.test.js` replace lines 48-62 (`'Create new / Link existing are buttons that report their action'`) with:

```js
  it('Create new / Link existing are buttons that report their action (PO section included)', async () => {
    user.set({ permissions: ['can_manage_jobs', 'can_manage_financials'] });
    const onAction = vi.fn();
    const { getAllByRole, queryByRole } = render(EmailActionPanel, {
      props: { emailRecord: { email_record_id: 1 }, onAction },
    });
    const creates = getAllByRole('button', { name: 'Create new' });
    expect(creates).toHaveLength(2);
    await fireEvent.click(creates[0]);
    await fireEvent.click(creates[1]);
    expect(onAction).toHaveBeenNthCalledWith(1, 'create-job');
    expect(onAction).toHaveBeenNthCalledWith(2, 'create-po');
    expect(queryByRole('link', { name: 'Create new' })).toBeNull();
  });

  it('a jobs-only user sees the PO "Create new" but not "Link existing"', () => {
    user.set({ permissions: ['can_manage_jobs'] });
    const { getByRole, getAllByRole, queryByRole } = render(EmailActionPanel, {
      props: { emailRecord: { email_record_id: 1 }, onAction: vi.fn() },
    });
    expect(getByRole('heading', { name: 'Purchase Order' })).toBeInTheDocument();
    expect(getAllByRole('button', { name: 'Create new' })).toHaveLength(2);
    expect(getAllByRole('button', { name: 'Link existing' })).toHaveLength(1);   // the Job one only
    expect(queryByRole('link', { name: 'Create new' })).toBeNull();
  });
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npm run test:run tests/components/purchaseorders/OrderModal.test.js tests/components/email/EmailActionPanel.test.js`
Expected: the email cases fail (no sender form; `createPo` never called); the panel test fails on the link.

- [ ] **Step 3: `lib/email.js`**

```js
  createPo: (id, body) => api.post(`/api/emails/${id}/create-po/`, body),
```

- [ ] **Step 4: `OrderModal` email branch**

Add imports: `import { emailApi, resolveSenderToContact } from '../../lib/email.js'; import SenderResolutionForm from '../email/SenderResolutionForm.svelte'; import DuplicateContactNotice from '../contacts/DuplicateContactNotice.svelte'; import DuplicateBusinessNotice from '../contacts/DuplicateBusinessNotice.svelte'; import InventoryItemPicker from '../InventoryItemPicker.svelte';`

State: `let senderInfo = $state(null); let resolutionState = $state(null); let duplicateContact = $state(null); let duplicateBusiness = $state(null); let addLine = $state(false); let pickedItem = $state(null);` and `const noticeShowing = $derived(!!duplicateContact || !!duplicateBusiness);`.

`load()` branches at the top:

```js
    if (source === 'email') {
      try {
        const [info, cats] = await Promise.all([
          emailApi.senderInfo(emailRecordId),
          api.get('/api/accounting-categories/?page_size=100'),
        ]);
        senderInfo = info;
        categories = cats.results || cats;
      } catch (e) {
        const t = triageError(e);
        showError(t.overlay || t.message || 'Could not load email.');
        onCancel();
      } finally { loading = false; }
      return;
    }
```

(`$effect` keys on `itemId`, which is `undefined` for email; keep `void itemId; void emailRecordId;` in the effect.)

Item pick for the email line:

```js
  function handleItemPick(it) {
    pickedItem = it;
    if (!it) return;
    form.description = it.description || '';
    form.units = it.units || 'none';
    form.price = it.purchase_price ?? '';
    form.accounting_category = it.accounting_category ?? '';
  }
```

Email submit (branch at the top of `submit`, before the qty check — the qty check applies only when `addLine`):

```js
    if (source === 'email') {
      duplicateContact = null; duplicateBusiness = null;
      if (addLine && (!String(form.qty).trim() || Number(form.qty) <= 0)) {
        qtyError = 'Enter a quantity greater than 0.';
        return;
      }
      busy = true;
      try {
        const { contactId: cid, businessId } = await resolveSenderToContact(resolutionState);
        let vendorBusinessId = businessId;
        if (!vendorBusinessId) {
          const c = await api.get(`/api/contacts/${cid}/`);
          vendorBusinessId = c.business?.business_id ?? c.business ?? c.business_id ?? null;
        }
        if (!vendorBusinessId) {
          formError = 'A vendor business is required to create a PO. Pick or create one for this contact.';
          return;
        }
        const body = { vendor_business_id: vendorBusinessId, contact_id: cid, requested_date: requestedDate || null };
        if (addLine) body.line = { inventory_item: pickedItem?.inventory_item_id ?? null, ...linePayload() };
        const resp = await emailApi.createPo(emailRecordId, body);
        showSuccess('Added to', { href: `#/purchase-orders/${resp.po_id}`, label: resp.po_number });
        onDone(resp);
        push(`/purchase-orders/${resp.po_id}`);
      } catch (err) {
        if (err?.status === 409 && err.data?.code === 'duplicate_email') duplicateContact = err.data.existing_contact;
        else if (err?.status === 409 && err.data?.code === 'duplicate_business_name') duplicateBusiness = err.data.existing_business;
        else {
          const t = triageError(err);
          if (t.overlay) showError(t.overlay);
          else { formError = t.message; fieldErrs = { ...(t.fields.line || {}), ...t.fields }; }
        }
      } finally { busy = false; }
      return;
    }
```

`canSubmit` for email: `!busy && !loading && (source === 'email' ? !!resolutionState : vendorId != null && !choiceNeeded)`. `handleCancel` for the modal: `noticeShowing ? (duplicateContact = null, duplicateBusiness = null) : onCancel()` — pass `handleCancel` as `Modal`'s `onCancel`.

Markup for the email source (inside the `{:else if history}` chain add `{:else if source === 'email' && senderInfo}`):

```svelte
    {#if duplicateContact}
      <DuplicateContactNotice contact={duplicateContact}
        onViewExisting={() => { onCancel(); push(`/contacts/${duplicateContact.contact_id}`); }}
        onReactivate={async () => { await api.post(`/api/contacts/${duplicateContact.contact_id}/reactivate/`, {}); onCancel(); push(`/contacts/${duplicateContact.contact_id}`); }}
        onBack={() => { duplicateContact = null; }} />
    {:else if duplicateBusiness}
      <DuplicateBusinessNotice business={duplicateBusiness}
        onViewExisting={() => { onCancel(); push(`/businesses/${duplicateBusiness.business_id}`); }}
        onBack={() => { duplicateBusiness = null; }} />
    {/if}
    <div hidden={noticeShowing}>
      <form onsubmit={submit}>
        <SenderResolutionForm {senderInfo} bind:state={resolutionState} />
        <p>
          <label for="order-date"><strong>Requested date</strong></label><br>
          <input id="order-date" type="date" bind:value={requestedDate}>
        </p>
        <p><label><input type="checkbox" bind:checked={addLine}> Add a first line</label></p>
        {#if addLine}
          <fieldset class="line">
            <legend>Line</legend>
            <p>
              <label><strong>Item</strong></label><br>
              <InventoryItemPicker value={pickedItem?.inventory_item_id} selectedItem={pickedItem}
                onSelect={handleItemPick} params={{ is_active: true }} />
            </p>
            <!-- the same Qty / Units / Price / Description / Vendor SKU / Category block as the fixed-item sources -->
          </fieldset>
        {/if}
        <p class="dialog-actions">
          <button type="submit" disabled={!canSubmit}>Create PO</button>
          <button type="button" onclick={onCancel} disabled={busy}>Cancel</button>
        </p>
        <FormMessage error={formError} />
      </form>
    </div>
```

Extract the Qty…Category block into a `{#snippet lineFields()}` at the bottom of the component and `{@render lineFields()}` in both branches so the fields are declared once (the earmark line renders only when `history?.earmarks?.length`).

- [ ] **Step 5: Panel, detail page, route**

`EmailActionPanel.svelte`: the PO `<section>` gate becomes `{#if canManageJobs || canManageFinancials}`; inside it, "Create new" becomes `<button type="button" class="action-button" onclick={() => onAction('create-po')}>Create new</button>`; wrap the "Link existing" `<p>` and the "Disassociate" `<p>` in `{#if canManageFinancials}` (link/unlink stay financials-only on the server). Update the file-top comment (line 7) — the PO create is no longer a page link.

`EmailDetailPage.svelte`: `import OrderModal from '../../components/purchaseorders/OrderModal.svelte';` and after the `EmailLinkModal` lines:

```svelte
  {#if actionModal === 'create-po'}
    <OrderModal source="email" emailRecordId={email.email_record_id}
      onDone={() => { actionModal = null; }} onCancel={() => (actionModal = null)} />
  {/if}
```

`App.svelte`: delete the `EmailCreatePOPage` import; route `'/email/:id/create-po': wrap({ component: RedirectTo, props: { to: '/email/:id' } }),`. `git rm frontend/src/routes/email/EmailCreatePOPage.svelte`.

- [ ] **Step 6: Run the frontend suite**

Run: `cd frontend && npm run test:run`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add -A frontend/src/components/purchaseorders/OrderModal.svelte frontend/src/lib/email.js frontend/src/components/email/EmailActionPanel.svelte frontend/src/routes/email frontend/src/App.svelte frontend/tests/components/purchaseorders/OrderModal.test.js frontend/tests/components/email/EmailActionPanel.test.js
git commit -m "feat(spa): create PO from email inside OrderModal; /email/:id/create-po is a redirect stub"
```

---

### Task 10: Add-line form — explicit material picker; dead prefill plumbing removed

**Files:**
- Modify: `frontend/src/components/purchaseorders/LineItemForm.svelte`
- Modify: `frontend/src/routes/purchaseorders/PurchaseOrderDetailPage.svelte:7,41-51,86-123,208-220,483-488`
- Modify: `frontend/src/routes/purchaseorders/PurchaseOrderFormPage.svelte:17-25,34-48,67-77,106-120`, `frontend/src/components/purchaseorders/PurchaseOrderForm.svelte:13,102-104`
- Test: `frontend/tests/components/purchaseorders/LineItemForm.test.js`, `frontend/tests/components/purchaseorders/PurchaseOrderDetailPage.test.js:89-135`

**Interfaces:**
- Consumes: `GET /api/jobs/{id}/` → `materials[]` with `material_id, description, quantity, units, item_code, inventory_item, consumption_state, po_line_item_id, cost_source`; `GET /api/inventory/{id}/`.
- Produces: `LineItemForm` props are now `{ categories, onSubmit, onCancel }` only. Payload: `material_id` when a material is picked, `job` when "Create a new material" is picked, `task` when a task is picked (unchanged). Radio group name `material-choice`.

- [ ] **Step 1: Update the tests**

In `LineItemForm.test.js`: delete `'prefills from an inventory item — fetches it and submits a PLI line'` and `'prefills manual fields from a neutral prefill (no inventory item)'`. Change `'job-only (no task): payload unchanged, sends job as before'` to pick "Create a new material" before submitting (the job GET must resolve):

```js
  it('job-only with "Create a new material" sends job (no material_id)', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/?')) return Promise.resolve({ results: [{ job_id: 5, job_number: 'JOB-5', name: 'widget' }] });
      if (url === '/api/jobs/5/') return Promise.resolve({ job_id: 5, materials: [] });
      return Promise.resolve([]);
    });
    const onSubmit = vi.fn();
    const { getByLabelText, getByRole, getByPlaceholderText, container, findByText } = render(LineItemForm, {
      props: { onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Bolt' } });
    await fireEvent.input(getByLabelText(/Qty/), { target: { value: '3' } });
    await fireEvent.input(getByLabelText(/^Price/), { target: { value: '2.50' } });
    await fireEvent.input(getByPlaceholderText('Search jobs…'), { target: { value: 'wid' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole(container, 'button', { name: /JOB-5/ }));
    await findByText(/No unordered materials on this job/);
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith({
      description: 'Bolt', qty: 3, units: 'none', price: 2.5, job: 5,
    });
  });
```

Add:

```js
describe('LineItemForm — material picker', () => {
  const JOB = { job_id: 5, materials: [
    { material_id: 41, description: '3/4 Baltic Birch', quantity: '4.00', units: 'sheet', item_code: 'BBPLY.75',
      inventory_item: 7, consumption_state: 'pending', po_line_item_id: null, cost_source: 'entered' },
    { material_id: 42, description: 'already ordered', quantity: '1.00', units: 'ea', item_code: 'X',
      inventory_item: 8, consumption_state: 'pending', po_line_item_id: 99, cost_source: 'po' },
    { material_id: 43, description: 'customer sends it', quantity: '1.00', units: 'ea', item_code: null,
      inventory_item: null, consumption_state: 'pending', po_line_item_id: null, cost_source: 'customer_supplied' },
    { material_id: 44, description: 'consumed', quantity: '1.00', units: 'ea', item_code: 'Y',
      inventory_item: 9, consumption_state: 'consumed', po_line_item_id: null, cost_source: 'entered' },
  ] };
  function mockJobs(jobs = { 5: JOB }) {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/?')) return Promise.resolve({ results: [
        { job_id: 5, job_number: 'JOB-5', name: 'widget' }, { job_id: 6, job_number: 'JOB-6', name: 'gadget' }] });
      const m = url.match(/^\/api\/jobs\/(\d+)\/$/);
      if (m) return Promise.resolve(jobs[m[1]] || { job_id: Number(m[1]), materials: [] });
      if (url === '/api/inventory/7/') return Promise.resolve({ inventory_item_id: 7, code: 'BBPLY.75', description: '3/4 Baltic Birch', units: 'sheet', purchase_price: '60.00' });
      return Promise.resolve([]);
    });
  }
  async function pickJob(container, getByPlaceholderText, label = /JOB-5/) {
    await fireEvent.input(getByPlaceholderText('Search jobs…'), { target: { value: 'g' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole(container, 'button', { name: label }));
    await new Promise((r) => setTimeout(r));
  }

  it('lists only pending, unlinked, non-customer materials plus "Create a new material"; nothing preselected; Add disabled', async () => {
    mockJobs();
    const { container, getByPlaceholderText, findByRole, getAllByRole, getByRole, queryByText } = render(LineItemForm, {
      props: { onSubmit: vi.fn(), onCancel: vi.fn() },
    });
    await pickJob(container, getByPlaceholderText);
    await findByRole('radio', { name: /BBPLY.75 · 4 sheet · 3\/4 Baltic Birch/ });
    expect(getAllByRole('radio').map((r) => r.checked)).toEqual([false, false]);
    expect(queryByText(/already ordered/)).toBeNull();
    expect(queryByText(/customer sends it/)).toBeNull();
    expect(queryByText(/consumed/)).toBeNull();
    expect(getByRole('radio', { name: 'Create a new material for this line' })).toBeInTheDocument();
    expect(getByRole('button', { name: 'Add' })).toBeDisabled();
  });

  it('picking a material in From Inventory mode sets and locks the item and sends material_id (no job)', async () => {
    mockJobs();
    const onSubmit = vi.fn();
    const { container, getByPlaceholderText, getByLabelText, findByRole, getByRole, findByText } = render(LineItemForm, {
      props: { onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.click(getByLabelText('From Inventory'));
    await pickJob(container, getByPlaceholderText);
    await fireEvent.click(await findByRole('radio', { name: /BBPLY.75/ }));
    await findByText(/BBPLY.75 — 3\/4 Baltic Birch/);
    expect(container.querySelector('input[placeholder="Search inventory items…"]')).toBeNull();   // locked chip, no input
    await fireEvent.input(getByLabelText(/Qty/), { target: { value: '4' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith({ inventory_item: 7, qty: 4, material_id: 41 });
  });

  it('in Manual mode a picked material links without touching the line fields', async () => {
    mockJobs();
    const onSubmit = vi.fn();
    const { container, getByPlaceholderText, getByLabelText, findByRole, getByRole } = render(LineItemForm, {
      props: { onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'ply' } });
    await fireEvent.input(getByLabelText(/Qty/), { target: { value: '4' } });
    await fireEvent.input(getByLabelText(/^Price/), { target: { value: '58' } });
    await pickJob(container, getByPlaceholderText);
    await fireEvent.click(await findByRole('radio', { name: /BBPLY.75/ }));
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith({ description: 'ply', qty: 4, units: 'none', price: 58, material_id: 41 });
  });

  it('shows the no-materials line and sends job when the job has nothing to attach to', async () => {
    mockJobs({ 5: { job_id: 5, materials: [] } });
    const onSubmit = vi.fn();
    const { container, getByPlaceholderText, getByLabelText, findByText, getByRole, queryByRole } = render(LineItemForm, {
      props: { onSubmit, onCancel: vi.fn() },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'ply' } });
    await fireEvent.input(getByLabelText(/Qty/), { target: { value: '1' } });
    await fireEvent.input(getByLabelText(/^Price/), { target: { value: '1' } });
    await pickJob(container, getByPlaceholderText);
    await findByText('No unordered materials on this job — a new material will be created.');
    expect(queryByRole('radio')).toBeNull();
    expect(getByRole('button', { name: 'Add' })).toBeEnabled();
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ job: 5 }));
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty('material_id');
  });

  it('resets the material choice when the job changes', async () => {
    mockJobs();
    const { container, getByPlaceholderText, findByRole, getByRole, findByText } = render(LineItemForm, {
      props: { onSubmit: vi.fn(), onCancel: vi.fn() },
    });
    await pickJob(container, getByPlaceholderText);
    await fireEvent.click(await findByRole('radio', { name: /BBPLY.75/ }));
    // clear and pick the other job
    await fireEvent.click(getByRole('button', { name: 'Clear' }));
    await pickJob(container, getByPlaceholderText, /JOB-6/);
    await findByText(/No unordered materials on this job/);
    expect(container.querySelector('input[name="material-choice"]:checked')).toBeNull();
  });

  it('the comment checkbox disables the Job picker and clears any job', async () => {
    mockJobs();
    const { container, getByPlaceholderText, getByLabelText, queryByText } = render(LineItemForm, {
      props: { onSubmit: vi.fn(), onCancel: vi.fn() },
    });
    await pickJob(container, getByPlaceholderText);
    await fireEvent.click(getByLabelText(/Comment line/));
    expect(queryByText('Task Link (optional)')).toBeNull();
    expect(container.querySelector('input[placeholder="Search jobs…"]')).toBeDisabled();
  });
});
```

(`findByRole` imported from `@testing-library/svelte` is the standalone query bound to `container`, as the existing tests already use.)

In `PurchaseOrderDetailPage.test.js`, delete the `'PurchaseOrderDetailPage one-shot material prefill'` describe (lines 89-135) and the `qsRef`-based `querystring` mock if nothing else uses it.

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npm run test:run tests/components/purchaseorders/LineItemForm.test.js`
Expected: the new describe fails (no radios).

- [ ] **Step 3: `LineItemForm.svelte`**

Replace the props and add state:

```js
  const { categories = [], onSubmit, onCancel } = $props();

  let mode = $state('manual');
  let selectedPLI = $state(null);
  let jobId = $state(null);
  let jobRow = $state(null);
  let taskId = $state(null);
  // Explicit material picker (PO order flow §5.3): once a job is chosen and
  // no task is picked, list its pending unlinked materials and make the
  // attach-or-create choice explicit. Null = nothing chosen yet.
  let jobMaterials = $state(null);   // null = loading / no job
  let materialChoice = $state(null); // null | material_id | 'new'
  let itemLocked = $state(false);
```

Delete the whole `prefill` `$effect`. Add:

```js
  function isAttachable(m) {
    return m.consumption_state === 'pending' && m.po_line_item_id == null
      && m.cost_source !== 'customer_supplied';
  }

  $effect(() => {
    const id = jobId;
    materialChoice = null;
    itemLocked = false;
    jobMaterials = null;
    if (!id) return;
    api.get(`/api/jobs/${id}/`)
      .then((job) => { if (jobId === id) jobMaterials = (job.materials || []).filter(isAttachable); })
      .catch(() => { if (jobId === id) jobMaterials = []; });
  });

  async function chooseMaterial(value) {
    materialChoice = value;
    itemLocked = false;
    if (value === 'new' || mode !== 'pli') return;
    const m = jobMaterials.find((x) => x.material_id === value);
    if (!m?.inventory_item) return;   // provisional: the user still picks the item
    const item = await api.get(`/api/inventory/${m.inventory_item}/`);
    handlePLISelect(item);
    itemLocked = true;
  }

  const materialChoiceNeeded = $derived(
    !isComment && !!jobId && !taskId && (jobMaterials?.length ?? 0) > 0 && materialChoice == null);
```

Move `let isComment = $state(false);` above the `$derived`. In `handleSubmit` replace the tail:

```js
    if (taskId) {
      data.task = taskId;
    } else if (jobId && !isComment) {
      if (materialChoice && materialChoice !== 'new') data.material_id = materialChoice;
      else data.job = jobId;
    }
    onSubmit(data);
```

Markup: the Job picker gets `disabled={isComment}`; the comment checkbox keeps `bind:checked={isComment}` and adds `onchange={(e) => { if (e.target.checked) { jobId = null; jobRow = null; taskId = null; } }}` (read the event's own `checked`, not the bound state, so the order of bind-vs-handler never matters). The inventory picker gets `disabled={itemLocked}` (SearchPicker's selected chip then hides Clear; verify `BusinessPicker`/`SearchPicker` honor `disabled` on the chip — they do, `disabled={disabled}` on the Clear button). After the Task Link block, inside `{#if jobId}` and guarded by `{#if !taskId && !isComment}`:

```svelte
      {#if jobMaterials === null}
        <p><small>Loading materials…</small></p>
      {:else if jobMaterials.length === 0}
        <p><small>No unordered materials on this job — a new material will be created.</small></p>
      {:else}
        <fieldset class="material-choice">
          <legend><strong>Attach to a material</strong></legend>
          {#each jobMaterials as m (m.material_id)}
            <label>
              <input type="radio" name="material-choice" value={m.material_id}
                checked={materialChoice === m.material_id} onchange={() => chooseMaterial(m.material_id)}>
              {#if m.item_code && !m.item_code.startsWith('LOT-')}{m.item_code} · {/if}{String(Number(m.quantity))} {m.units} · {m.description}
            </label>
          {/each}
          <label>
            <input type="radio" name="material-choice" value="new"
              checked={materialChoice === 'new'} onchange={() => chooseMaterial('new')}>
            Create a new material for this line
          </label>
        </fieldset>
      {/if}
```

Submit button: `<button type="submit" disabled={materialChoiceNeeded}>Add</button>`. Add `.material-choice label { display: block; }` in a `<style>` block.

- [ ] **Step 4: Remove the dead prefill plumbing**

`PurchaseOrderDetailPage.svelte`: delete the `querystring` import usage (`initialQs`, `prefillMaterialId`, `prefillInventoryItemId`, `defaultJobId`, `prefilledJob`, `prefilledMaterialIdNum`, `prefilledLine`, `prefillLoaded`), the whole `loadPrefill()` and its call in `loadPO()`, the two `prefilled… = null` lines in `handleAddLineItem`, the `orderPrefillQty` import if now unused, and the three props on the `<LineItemForm>` mount (leave `{categories}`, `onSubmit`, `onCancel`).

`PurchaseOrderFormPage.svelte`: delete `contextJobId`, `contextMaterialId`, `contextInventoryItemId`, `contextJob`, `contextMaterial`, their loads, the `qs` forwarding in `handleSubmit` (just `push(`/purchase-orders/${created.po_id}`)`), and the `{contextJob}` prop. Keep `contextBusinessId` / `contextContactId`.

`PurchaseOrderForm.svelte`: drop the `contextJob` prop and the `{#if contextJob}` paragraph.

- [ ] **Step 5: Run the suite**

Run: `cd frontend && npm run test:run`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/purchaseorders/LineItemForm.svelte frontend/src/components/purchaseorders/PurchaseOrderForm.svelte frontend/src/routes/purchaseorders frontend/tests/components/purchaseorders/LineItemForm.test.js frontend/tests/components/purchaseorders/PurchaseOrderDetailPage.test.js frontend/tests/components/purchaseorders/PurchaseOrderForm.test.js
git commit -m "feat(spa): explicit material picker on the PO add-line form; drop dead prefill plumbing"
```

---

### Task 11: PO table Code/SKU columns, SKU edit, `can_manage` gating

**Files:**
- Modify: `frontend/src/components/purchaseorders/PurchaseOrderDetail.svelte` (props line 11, `startEdit`/`saveEdit` 101-150, toolbar 208-225, table 231-375)
- Modify: `frontend/src/routes/purchaseorders/PurchaseOrderDetailPage.svelte:6,65,433,480` ; `PurchaseOrderListPage.svelte:5,17,54`; `frontend/src/components/contacts/CustomerActivity.svelte:158`
- Test: `frontend/tests/components/purchaseorders/PurchaseOrderDetail.test.js`, `PurchaseOrderListPage.test.js`

**Interfaces:**
- Consumes: `po.can_manage`, line `item_code`, `vendor_sku` (Tasks 1, 6).
- Produces: `PurchaseOrderDetail` prop **`canManage`** (renamed from `canManageFinancials`; `ReconciliationSection` keeps its `canManageFinancials` prop). Line edit PATCH body includes `vendor_sku`.

- [ ] **Step 1: Update/extend the tests**

In `PurchaseOrderDetail.test.js`: rename every `canManageFinancials: true` prop to `canManage: true`; extend `po()`'s lines with `item_code: 'BB34P', vendor_sku: 'BB34P-48'` on line 1 and `item_code: null, vendor_sku: ''` on line 2; add:

```js
  it('prints Code and SKU columns, blank for freeform and LOT lines', () => {
    const data = po();
    data.line_items.push({ line_item_id: 3, line_number: 3, description: 'lot', qty: 1, price: '1.00', item_code: 'LOT-5', vendor_sku: '' });
    const { getByRole, getAllByRole } = render(PurchaseOrderDetail, { props: { po: data, canManage: false } });
    expect(getByRole('columnheader', { name: 'Code' })).toBeInTheDocument();
    expect(getByRole('columnheader', { name: 'SKU' })).toBeInTheDocument();
    const rows = getAllByRole('row');
    expect(rows[1].textContent).toMatch(/BB34P.*BB34P-48/);
    expect(rows[3].textContent).not.toMatch(/LOT-5/);
  });

  it('the draft edit row carries the SKU into the save payload', async () => {
    const onEditLineItem = vi.fn();
    const { getAllByRole, getByRole, getByDisplayValue } = render(PurchaseOrderDetail, {
      props: { po: po(), canManage: true, onEditLineItem },
    });
    await fireEvent.click(getAllByRole('button', { name: 'Edit' })[0]);
    await fireEvent.input(getByDisplayValue('BB34P-48'), { target: { value: 'NEW-1' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(onEditLineItem).toHaveBeenCalledWith(1, expect.objectContaining({ vendor_sku: 'NEW-1' }));
  });

  it('hides every write control when canManage is false', () => {
    const { queryByRole } = render(PurchaseOrderDetail, { props: { po: po(), canManage: false } });
    for (const name of ['Issue & Send', 'Mark as Issued', 'Delete', 'Edit']) {
      expect(queryByRole('button', { name })).toBeNull();
    }
  });
```

In `PurchaseOrderListPage.test.js` (it mocks `@/stores/permissions.js`): add a case where `canManageJobs` is true and `canManageFinancials` false and assert the "New Purchase Order" link renders; and one where both are false and it does not. Follow the file's existing mock shape for the stores.

- [ ] **Step 2: Run to verify failures**

Run: `cd frontend && npm run test:run tests/components/purchaseorders/PurchaseOrderDetail.test.js tests/components/purchaseorders/PurchaseOrderListPage.test.js`
Expected: FAIL (no Code header; prop name).

- [ ] **Step 3: `PurchaseOrderDetail.svelte`**

- Prop: `canManage = false,` replacing `canManageFinancials = false,`; replace every `canManageFinancials` in this file with `canManage` (toolbar, header `onChangeContact`, table gates, tfoot).
- `startEdit`: add `vendor_sku: li.vendor_sku || '',` to `editForm`. `saveEdit`: add `vendor_sku: editForm.vendor_sku,` to the `onEditLineItem` payload.
- Table head: after `<th>Description</th>` add `<th>Code</th><th>SKU</th>`.
- Edit row: after the description `<td>` add `<td>{li.item_code && !li.item_code.startsWith('LOT-') ? li.item_code : ''}</td><td><input type="text" maxlength="100" bind:value={editForm.vendor_sku} style="width:110px;"></td>`.
- Display row: after the description `<td>` add `<td>{#if li.item_code && !li.item_code.startsWith('LOT-')}<code class="mat-code">{li.item_code}</code>{/if}</td><td>{li.vendor_sku || ''}</td>`.
- tfoot: `colspan="5"` → `colspan="7"`.
- Style: add `.mat-code { font-size: 11px; color: #374151; background: #f3f4f6; border: 1px solid #d1d5db; border-radius: 3px; padding: 0 4px; }`.

- [ ] **Step 4: Pages**

`PurchaseOrderDetailPage.svelte`: keep `canManageFinancials` (it still gates `ReconciliationSection` and the rate-prompt handling at line 391); add `let canManage = $derived(!!po?.can_manage);`; pass `{canManage}` to `<PurchaseOrderDetail>` (replacing `{canManageFinancials}`); the Add Line Item gate at line 480 becomes `{#if canManage && po.status === 'draft'}`.

`PurchaseOrderListPage.svelte`: import `canManageJobs as canManageJobsStore` too; `let canCreate = $derived($canManageFinancialsStore || $canManageJobsStore);`; the link gate becomes `{#if canCreate}`.

`CustomerActivity.svelte:158`: `{#if ($canManageFinancials || $canManageJobs) && newPOHref}`.

- [ ] **Step 5: Run the suite**

Run: `cd frontend && npm run test:run`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/purchaseorders/PurchaseOrderDetail.svelte frontend/src/routes/purchaseorders frontend/src/components/contacts/CustomerActivity.svelte frontend/tests/components/purchaseorders
git commit -m "feat(spa): Code/SKU columns on the PO table, SKU edit; PO page gates on po.can_manage"
```

---

### Task 12: Playwright spec `po-order-flow.spec.js` + flow-doc section

**Files:**
- Create: `e2e/specs/purchasing/po-order-flow.spec.js`
- Modify: `docs/ui-flows/Purchasing.md` (new `## 11. Ordering through the Order modal` before `## Coverage matrix`; Personas section gains the jobs-atom note)

**Interfaces:**
- Consumes: seed facts (`fixtures/playwright/seed.json`, verified 2026-10-15): item **30 `BBPLY.5`** has history from businesses **61 Moore Newton Hardwoods** (POs 0001/0008/0009/0010, contact 100) and **59 Royal Plywood** (PO0012, 2026-07-09, newest, contact 98); material **6** on job **19 (08008, approved)**, task 523, uses item 30, qty 8, pending, unlinked; the seed has **no draft POs**; email **10** ("Invoice MNH-20441 — plywood order", from `test+ap@robot-six.com`) is unlinked and matches no contact. Personas: `finjobs` (financials + jobs), `worker` (none). `apiAs` from `e2e/fixtures/api.js`.

- [ ] **Step 1: Add the flow-doc section**

Append to `docs/ui-flows/Purchasing.md` before `## Coverage matrix`:

```markdown
## 11. Ordering through the Order modal (PO order flow, 2026-10-15)

Entry points: a material row's **Order** (job task list / task detail), the
catalog Inventory and Earmarks tabs' **order**, and the email action panel's
PO **Create new**. All three open the same `OrderModal`; nothing is created
until Submit.

- [ ] **Vendor from history:** ordering a material whose item has been
  bought before preselects the most recent vendor in a **Vendor** select;
  the option text shows the last date, price and SKU. Contact defaults to
  that PO's contact; Vendor SKU and Price are seeded from that history row.
- [ ] **Search escape hatch:** the select's last option **Search all
  businesses…** turns the field into the business type-ahead; **back to
  recent vendors** returns.
- [ ] **Create PO:** Submit creates the PO and its first line in one step and
  lands on the PO detail; the line shows the SKU in the **SKU** column and
  the item code in **Code**.
- [ ] **Append or new is explicit:** ordering again while that PO is still a
  draft shows **Open drafts for this vendor** with *Start a new PO* /
  *Add to PO… (n lines)* radios, nothing preselected, Submit disabled until
  one is picked; picking the draft appends the line.
- [ ] **No history:** a never-ordered item opens straight in search mode.
- [ ] **Email → PO:** the PO section's **Create new** opens the modal with
  the sender-resolution block; a matched sender creates a PO carrying that
  contact and lands on it.
- [ ] **Add Line Item → attach to a material:** on a draft PO, picking a Job
  lists that job's unordered materials as radios plus *Create a new material
  for this line*; nothing is preselected; attaching links the line to the
  chosen material and creates **no** duplicate material on the job.
- [ ] **Guard — permissions:** a Worker (no atom) sees no **Order** / order /
  Create new controls and `POST /api/materials/{id}/order/` answers 403.
- [ ] **Jobs atom:** a jobs-only user can create a PO (list page **New
  Purchase Order** visible) and order a material.
```

Also in the Personas section add a bullet: "**Jobs** — holds `can_manage_jobs`: may create POs and order materials/stock, and edit any PO (PO order flow §6); reconcile stays Financials-only."

- [ ] **Step 2: Write the spec**

```js
// e2e/specs/purchasing/po-order-flow.spec.js
// docs/ui-flows/Purchasing.md §11 — the Order modal (PO order flow spec
// docs/plans/2026-10-14-po-order-flow.md). Seed facts used: item 30
// BBPLY.5 has vendor history (newest: Royal Plywood, PO0012); material 6 on
// job 19 (08008) uses it and is pending/unlinked; the seed has no draft POs;
// email 10 is an unlinked vendor invoice with no matching contact.
import { expect, test } from '@playwright/test';
import { apiAs } from '../../fixtures/api.js';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.finjobs.storageState });

const stamp = `e2e-pof-${Date.now().toString(36)}`;

async function dismissOverlay(page) {
  const btn = page.getByRole('button', { name: 'Dismiss message' });
  if (await btn.count()) await btn.first().click();
}

test('§11 order a material with history → Create PO → order again → Add to the draft', async ({ page }) => {
  test.setTimeout(120_000);
  const api = await apiAs(personas.finjobs);
  const job = await api.get('/api/jobs/19/');
  const material = job.materials.find((m) => m.material_id === 6);
  test.skip(!material || material.po_line_item_id != null, 'seed gap: material 6 on job 19 is not pending/unlinked');
  const history = await api.get('/api/inventory/30/vendor-history/');
  test.skip(!history.vendors.length, 'seed gap: BBPLY.5 has no vendor history');
  const newest = history.vendors[0];

  await test.step('Vendor from history: Order on the material row preselects the newest vendor', async () => {
    await page.goto('/#/jobs/19/tasks');
    const row = page.locator('tr.material-row', { hasText: material.description }).first();
    await row.getByRole('button', { name: 'Order' }).click();
    const dialog = page.getByRole('dialog', { name: 'Order' });
    const vendor = dialog.getByRole('combobox', { name: /Vendor/ });
    await expect(vendor).toHaveValue(String(newest.business_id));
    await expect(vendor.locator('option').first()).toContainText(newest.business_name);
    await expect(dialog.getByLabel(/^Price/)).toHaveValue(Number(newest.last_price).toFixed(2));
    await expect(dialog.getByText(/Open drafts for this vendor/)).toHaveCount(0);   // seed has no drafts
  });

  let poUrl, poId, poNumber;
  await test.step('Create PO: lands on the PO with the line, Code and SKU columns', async () => {
    const dialog = page.getByRole('dialog', { name: 'Order' });
    await dialog.getByLabel(/Vendor SKU/).fill(`${stamp}-SKU`);
    await dialog.getByRole('button', { name: 'Create PO' }).click();
    await expect(page).toHaveURL(/#\/purchase-orders\/\d+$/);
    poUrl = page.url();
    poId = Number(poUrl.split('/').pop());
    poNumber = (await api.get(`/api/purchase-orders/${poId}/`)).po_number;
    await dismissOverlay(page);
    await expect(page.getByRole('heading', { name: /Purchase Order PO/ })).toBeVisible();
    await expect(page.getByText(`Vendor:`)).toContainText(newest.business_name);
    await expect(page.getByRole('columnheader', { name: 'SKU' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Code' })).toBeVisible();
    await expect(page.getByRole('cell', { name: `${stamp}-SKU` })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'BBPLY.5' })).toBeVisible();
  });

  await test.step('Append or new is explicit: a second order offers the draft, nothing preselected', async () => {
    // Backdrop: a second pending material on the same job and item (not the flow under test).
    const second = await api.post('/api/jobs/19/materials/', {
      description: `${stamp} second sheet`, quantity: '2', units: 'sheet', inventory_item: 30,
      unit_cost: '73.33', accounting_category: material.accounting_category,
    });
    await page.goto('/#/jobs/19/tasks');
    const row = page.locator('tr.material-row', { hasText: `${stamp} second sheet` });
    await row.getByRole('button', { name: 'Order' }).click();
    const dialog = page.getByRole('dialog', { name: 'Order' });
    const addTo = dialog.getByRole('radio', { name: new RegExp(`Add to ${poNumber}`) });
    await expect(addTo).toBeVisible();
    await expect(addTo).not.toBeChecked();
    await expect(dialog.getByRole('radio', { name: 'Start a new PO' })).not.toBeChecked();
    await expect(dialog.getByRole('button', { name: 'Create PO' })).toBeDisabled();
    await addTo.check();
    await dialog.getByRole('button', { name: `Add to ${poNumber}` }).click();
    await expect(page).toHaveURL(poUrl);
    await dismissOverlay(page);
    await expect(page.getByRole('cell', { name: `${stamp} second sheet` })).toBeVisible();
    const po = await api.get(`/api/purchase-orders/${poId}/`);
    expect(po.line_items).toHaveLength(2);
    expect((await api.get(`/api/materials/${second.material_id}/`)).po_line_item_id).not.toBeNull();
  });

  await test.step('Add Line Item → attach to an existing material creates no duplicate', async () => {
    const before = (await api.get('/api/jobs/19/')).materials.length;
    const third = await api.post('/api/jobs/19/materials/', {
      description: `${stamp} third sheet`, quantity: '1', units: 'sheet', inventory_item: 30,
      unit_cost: '73.33', accounting_category: material.accounting_category,
    });
    await page.goto(poUrl);
    await page.getByRole('button', { name: 'Add Line Item' }).click();
    await page.getByLabel('From Inventory').check();
    await page.getByPlaceholder('Search jobs…').fill('08008');
    await page.getByRole('button', { name: /08008/ }).first().click();
    const choice = page.getByRole('radio', { name: new RegExp(`${stamp} third sheet`) });
    await expect(choice).toBeVisible();
    await expect(choice).not.toBeChecked();
    await expect(page.getByRole('button', { name: 'Add' })).toBeDisabled();
    await choice.check();
    await expect(page.getByText(/BBPLY\.5 — /)).toBeVisible();     // item set and locked
    await page.getByLabel(/Qty/).fill('1');
    await page.getByRole('button', { name: 'Add' }).click();
    await expect(page.getByRole('cell', { name: `${stamp} third sheet` })).toBeVisible();
    expect((await api.get('/api/jobs/19/')).materials.length).toBe(before + 1);   // the one we made, no duplicate
    expect((await api.get(`/api/materials/${third.material_id}/`)).po_line_item_id).not.toBeNull();
  });

  await test.step('Cleanup: delete the draft PO (sever keep) so reruns start clean', async () => {
    const po = await api.get(`/api/purchase-orders/${poId}/`);
    // Draft delete with linked materials needs a sever decision per linked line
    // (PurchaseOrderDetailPage.runDelete sends the same body).
    const decisions = Object.fromEntries(
      po.line_items.filter((l) => l.material).map((l) => [l.line_item_id, 'keep']));
    await api.delWith(`/api/purchase-orders/${poId}/?confirm=true`, { sever_decisions: decisions });
    await api.dispose();
  });
});

test('§11 catalog order with no history opens in search mode', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const items = (await api.get('/api/inventory/?page_size=100&is_active=true')).results;
  let bare = null;
  for (const it of items) {
    const h = await api.get(`/api/inventory/${it.inventory_item_id}/vendor-history/`);
    if (!h.vendors.length && !it.code.startsWith('LOT-')) { bare = it; break; }
  }
  await api.dispose();
  test.skip(!bare, 'seed gap: every catalog item has vendor history');
  await page.goto('/#/catalog/inventory');
  const row = page.getByRole('row', { name: new RegExp(bare.code) }).first();
  await row.getByRole('button', { name: 'order' }).click();
  const dialog = page.getByRole('dialog', { name: 'Order' });
  await expect(dialog.getByPlaceholder('Search business…')).toBeVisible();
  await expect(dialog.getByRole('combobox', { name: /Vendor/ })).toHaveCount(0);
  await expect(dialog.getByText('back to recent vendors')).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Create PO' })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('§11 email → Create new (PO) with a matched sender carries the contact', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const list = await api.get('/api/emails/?page_size=50');
  const email = (list.results || list).find((e) => !e.purchase_order && !e.job);
  test.skip(!email, 'seed gap: no unlinked email');
  // Backdrop: make the sender a known vendor contact so resolution matches
  // (the seed's vendor-invoice sender has no contact). Business 61 is a
  // seed vendor (Moore Newton Hardwoods).
  const info = await api.get(`/api/emails/${email.email_record_id}/sender-info/`);
  let contact = info.matching_contacts[0];
  if (!contact) {
    const created = await api.post('/api/contacts/', {
      first_name: 'Vendor', last_name: stamp, email: info.sender_email,
      phones: [{ number: '555-0199', label: 'work' }], business_id: 61,
    });
    contact = { id: created.contact_id };
  }

  await page.goto(`/#/email/${email.email_record_id}`);
  const panel = page.getByRole('complementary');
  const poSection = panel.locator('section', { has: page.getByRole('heading', { name: 'Purchase Order' }) });
  await poSection.getByRole('button', { name: 'Create new' }).click();
  const dialog = page.getByRole('dialog', { name: 'Order' });
  await expect(dialog.getByRole('heading', { name: 'Sender' })).toBeVisible();
  await dialog.getByRole('button', { name: 'Create PO' }).click();
  await expect(page).toHaveURL(/#\/purchase-orders\/\d+$/);
  await dismissOverlay(page);
  const id = page.url().split('/').pop();
  const po = await api.get(`/api/purchase-orders/${id}/`);
  expect(po.contact).toBe(contact.id);
  expect(po.business).toBe(61);
  expect((await api.get(`/api/emails/${email.email_record_id}/`)).purchase_order).toBe(Number(id));

  await api.post(`/api/emails/${email.email_record_id}/unlink-from-po/`, {});
  await api.del(`/api/purchase-orders/${id}/?confirm=true`);
  await api.dispose();
});

test('§11 guard: a worker sees no Order control and the API answers 403', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: personas.worker.storageState });
  const page = await ctx.newPage();
  await page.goto('/#/jobs/19/tasks');
  await expect(page.locator('tr.material-row').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Order' })).toHaveCount(0);
  const api = await apiAs(personas.worker);
  const r = await api.postRaw('/api/materials/6/order/', { po: { business: 59 } });
  expect(r.status()).toBe(403);
  await api.dispose();
  await ctx.close();
});
```

Implementer notes:
- `api.delWith` does not exist yet. Add it to `e2e/fixtures/api.js` beside `del` (the PO draft delete takes `sever_decisions` in the DELETE body, exactly as `PurchaseOrderDetailPage.svelte`'s `runDelete` sends it):

```js
    delWith: async (url, data) =>
      asJson(await ctx.delete(url, { data, headers: { 'X-CSRFToken': csrf } })),
```

- `/api/jobs/19/materials/` POST fields are `description, quantity, units, unit_cost, sell_price, inventory_item, accounting_category` (`MaterialWriteSerializer`, `apps/api/tasks/serializers.py:94-101`); the spec sends the subset it needs.
- If the catalog Inventory tab's row/button names differ (`getByRole('row', { name })` depends on cell text), read `CatalogInventoryPage.svelte` and adjust the locator; do not add test ids.
- Run only this spec: `cd e2e && npx playwright test specs/purchasing/po-order-flow.spec.js`.

- [ ] **Step 3: Run the spec**

Run: `cd e2e && npx playwright test specs/purchasing/po-order-flow.spec.js`
Expected: 4 passed. Iterate on locators until green; never loosen an assertion to pass.

- [ ] **Step 4: Commit**

```bash
git add e2e/specs/purchasing/po-order-flow.spec.js e2e/fixtures/api.js docs/ui-flows/Purchasing.md
git commit -m "test(e2e): PO order flow — history vendor, append-or-new, email PO, attach-to-material, guard"
```

---

### Task 13: Durable docs, LATER cleanup, full verification

**Files:**
- Modify: `docs/designs/materials-inventory-and-purchasing.md` §9 (Fields: `vendor_sku`), §10 (`add_line_item_from_pli` overrides; `add_line_item` comment guard), §11 ("Order — generate a PO from a material", "Order to stock", resolver "Three-step resolver": mismatch guard + establish-onto-item; new "Vendor history" subsection; "Vendor-invoice emails link to the PO": create-po body), §15 (PO surfaces: Code/SKU columns, `po.can_manage` gating, Add Line material picker), §16 (MaterialRow Order gate), §17 (catalog order buttons → OrderModal)
- Modify: `docs/designs/architecture-and-conventions.md:1628` (the `/email/:id/create-po` line → RedirectTo stub; add `GET /api/inventory/{id}/vendor-history/` to the endpoint list near the inventory entries)
- Modify: `docs/designs/users-and-permissions.md:57,134-135,144` (atom table + endpoint rows: PO create / inventory order / email create-po / sender-info = jobs-or-financials; material order = financials-or-job-PM; PO writes = financials-or-jobs-or-linked-PM; reconcile financials; vendor-history IsAuthenticated; the self-lockout note)
- Modify: `docs/designs/data-constraints.md` (PO line item field list: `vendor_sku` CharField(100) blank default '')
- Modify: `docs/designs/LATER.md:843-852` (remove "Show a material's earmarks on the PO when ordering it"), `:1452` (rewrite the stale "ideally create-PO-from-email" fragment — it exists, via OrderModal), `:1608` (remove "PO line items should show the inventory item's code")
- Modify: `frontend/README.md` Modals list (add `OrderModal` — three sources; remove `StockOrderDialog`; note `EmailCreatePOPage` retired)
- Delete: `docs/plans/2026-10-14-po-order-flow.md`, `docs/plans/2026-10-15-po-order-flow-plan.md` (disposable once shipped — per project CLAUDE.md)

- [ ] **Step 1: Docs**

Write each change listed above. For §11 add:

```markdown
### Vendor history — `GET /api/inventory/{id}/vendor-history/`

`IsAuthenticated`. `InventoryService.vendor_history(item, *, exclude_job=None)`
returns `vendors` (one row per business from lines on non-draft,
non-cancelled POs, newest first: `business_id, business_name, contact_id,
last_ordered, last_price, vendor_sku, po_number, times`), `earmarks` (the
item's committed earmarks by job, minus `?exclude_job`), and `open_drafts`
(every draft PO, vendor-less ones flagged by `business_id: null`, capped at
100). This is the Order modal's one read; vendor knowledge is derived from
PO history, never curated (RM 2026-10-14).
```

and rewrite "Order — generate a PO from a material (Path 1)" / "Order to stock" to the §4.2 contract (body `po_id` xor `po`, `line` overrides, `line.inventory_item` refused, 201 `{po_id, po_number, line_item_id}`, services `MaterialService.order(material, *, po, po_fields, line)` / `InventoryService.order_stock(item, *, po, po_fields, line)`, one transaction).

- [ ] **Step 2: Full backend suite (fresh DB — a migration was added)**

Run: `python manage.py test --noinput`
Expected: `OK`. Read the summary line; do not pipe.

- [ ] **Step 3: Full frontend suite**

Run: `cd frontend && npm run test:run`
Expected: all green.

- [ ] **Step 4: Build check**

Run: `cd frontend && npm run build`
Expected: builds (Svelte strict mode: every `<tr>` inside `<tbody>`; no unused-prop warnings treated as errors).

- [ ] **Step 5: E2E — this feature's spec plus the neighbors it touches**

Run: `cd e2e && npx playwright test specs/purchasing specs/email specs/inventory specs/comment-lines`
Expected: passed (if `completion.spec` ordering flakiness appears elsewhere, it is pre-existing on main — see memory; re-run in isolation before calling it a regression).

- [ ] **Step 6: Commit and report**

```bash
git add docs/designs frontend/README.md
git rm docs/plans/2026-10-14-po-order-flow.md docs/plans/2026-10-15-po-order-flow-plan.md
git commit -m "docs: PO order flow — vendor history, Order modal, vendor_sku, permissions; remove shipped plan"
```

Then tell RM the branch is ready for review in the browser. Do not merge, push, or open a PR. Remind them: `nealseed.json` regeneration (from the 2026-10-14 matcher fix) is still theirs to run, and the dev DB needs `migrate` for `purchasing.0002`.

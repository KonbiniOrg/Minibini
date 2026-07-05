# Catalog Area UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Top-level Catalog area (`/catalog` + `/catalog/service-items` + `/catalog/earmarks`), stock ordering of inventory items, service-item permission widening, and the Settings Pricing-tab tidy-up — per `docs/plans/2026-07-05-catalog-area-ui.md` (the spec; read it for rationale).

**Architecture:** Backend first: one new permission class, `InventoryService.order_stock`, a `POST /api/inventory/{id}/order/` action, and a read-only `/api/earmarks/` viewset. Then frontend: per-tab routes with a shared `CatalogTabs` nav, a shared `StockOrderDialog`, the earmarks table, ServiceItemManager read-only mode, and the Settings reshuffle.

**Tech Stack:** Django 5.2 + DRF (backend), Svelte 5 SPA + Vitest (frontend).

## Global Constraints

- **Never write to the dev database.** No `migrate`, no `manage.py shell` ORM writes, no `loaddata`, no SQL writes. Tests only (`python manage.py test` uses its own DB). No model changes are planned, so no migrations should be created.
- **Only one `python manage.py test` invocation at a time** (shared MySQL). Never judge a test run by a piped exit code — read the `OK` / `FAILED (...)` / `Ran N tests` summary lines.
- Error contract: services raise `ValidationError({'field': ['msg']})` for field problems, `ValidationError('sentence')` otherwise; do NOT catch-and-rerender — the central handler shapes them. Frontend routes errors through `triageError(e)`; success overlay via `showSuccess(text, {href,label})`.
- All DELETE responses return 200 with JSON (existing `JSONDestroyMixin`); new viewsets must not return 204.
- **Links navigate; buttons act.** The Catalog tab strip is `<a use:link>`; Order/write-off/etc. are `<button>`.
- Frontend tests: Vitest in `frontend/tests/`, run `npm run test:run` from `frontend/` (never watch mode). `<tr>` must be wrapped in `<tbody>`/`<thead>` (Svelte 5 strict).
- Status/state values via model constants, never string literals.
- Commit after each task; never merge/push/PR.
- Shortfall formula (spec): `max(0, qty_earmarked_total − qty_on_hand − qty_on_order)`, **item-level** (total earmarked across all jobs), used for both the Earmarks column and the Order prompt pre-fill on both tabs.

---

### Task 1: `CanManageJobsOrFinancialsOrConfig` + ServiceItemViewSet widening

**Files:**
- Modify: `apps/api/permissions.py` (after `CanManageJobsOrConfig`, ~line 41)
- Modify: `apps/api/templates_config/views.py` (`ServiceItemViewSet.get_permissions`, ~line 106)
- Test: `tests/test_api_templates_config.py`

**Interfaces:**
- Produces: `apps.api.permissions.CanManageJobsOrFinancialsOrConfig` (BasePermission).
- ServiceItem writes (create/update/partial_update/destroy) become jobs|financials|config; list/retrieve stay `IsAuthenticated`.

- [ ] **Step 1: Write failing tests** — append to `tests/test_api_templates_config.py` inside `ServiceItemAPITest` (match the existing atom-user pattern at line 53):

```python
    def _atom_client(self, username, *codenames):
        from django.contrib.auth.models import Permission
        u = User.objects.create_user(username=username, password='x')
        for c in codenames:
            u.user_permissions.add(Permission.objects.get(codename=c))
        client = APIClient()
        client.force_authenticate(user=User.objects.get(pk=u.pk))
        return client

    def _make_item(self):
        from apps.estimates.models import ServiceItem
        return ServiceItem.objects.create(template_name='Perm Target')

    def test_financials_atom_can_create_update_delete(self):
        client = self._atom_client('fin_user', 'can_manage_financials')
        resp = client.post('/api/service-items/', {
            'template_name': 'Fin Created', 'description': '',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        item = self._make_item()
        resp = client.patch(f'/api/service-items/{item.pk}/',
                            {'description': 'x'}, format='json')
        self.assertEqual(resp.status_code, 200)
        resp = client.delete(f'/api/service-items/{item.pk}/')
        self.assertEqual(resp.status_code, 200)

    def test_jobs_atom_can_update_and_delete(self):
        # Was config-only; the catalog now belongs to plan-builders too.
        client = self._atom_client('jobs_user', 'can_manage_jobs')
        item = self._make_item()
        resp = client.patch(f'/api/service-items/{item.pk}/',
                            {'description': 'y'}, format='json')
        self.assertEqual(resp.status_code, 200)
        resp = client.delete(f'/api/service-items/{item.pk}/')
        self.assertEqual(resp.status_code, 200)

    def test_no_atom_user_reads_but_cannot_write(self):
        client = self._atom_client('plain_user')
        resp = client.get('/api/service-items/')
        self.assertEqual(resp.status_code, 200)
        resp = client.post('/api/service-items/', {
            'template_name': 'Nope',
        }, format='json')
        self.assertEqual(resp.status_code, 403)
        item = self._make_item()
        resp = client.patch(f'/api/service-items/{item.pk}/',
                            {'description': 'z'}, format='json')
        self.assertEqual(resp.status_code, 403)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_api_templates_config -v 1`
Expected: the two atom tests FAIL with 403 != 200/201 (update/delete are config-only today).

- [ ] **Step 3: Implement** — in `apps/api/permissions.py`, after `CanManageJobsOrConfig`:

```python
class CanManageJobsOrFinancialsOrConfig(BasePermission):
    """The catalog (ServiceItems) is shared workshop vocabulary: plan-builders
    (jobs), the money role (financials), and config admins may all manage it."""
    def has_permission(self, request, view):
        return (request.user.has_perm('core.can_manage_jobs')
                or request.user.has_perm('core.can_manage_financials')
                or request.user.has_perm('core.can_manage_config'))
```

In `apps/api/templates_config/views.py`, import it and replace `ServiceItemViewSet.get_permissions` with:

```python
    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        # Catalog management is shared: jobs | financials | config.
        return [IsAuthenticated(), CanManageJobsOrFinancialsOrConfig()]
```

(Remove the now-unused `CanManageJobsOrConfig` import **only if** nothing else in the module uses it — grep the file first.)

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_api_templates_config -v 1`
Expected: `OK`, no failures.

- [ ] **Step 5: Commit**

```bash
git add apps/api/permissions.py apps/api/templates_config/views.py tests/test_api_templates_config.py
git commit -m "feat(api): service-item management widened to jobs|financials|config"
```

---

### Task 2: `InventoryService.order_stock`

**Files:**
- Modify: `apps/inventory/services.py` (add a static method to `InventoryService`, near the other item-level ops)
- Test: `tests/test_stock_order.py` (create)

**Interfaces:**
- Produces: `InventoryService.order_stock(item, quantity, po=None) -> (PurchaseOrder, PurchaseOrderLineItem)`. Quantity is a `Decimal`; `po` (optional) must be a draft PO. Creates a PO via `PurchaseOrderService.create_po()` when none given; line added via `PurchaseOrderService.add_line_item_from_pli(po.pk, item.pk, quantity)` — **no `job`, no `material_id`** (plain stock line).

- [ ] **Step 1: Write failing tests** — create `tests/test_stock_order.py`:

```python
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.inventory.models import InventoryItem
from apps.inventory.services import InventoryService
from apps.purchasing.models import PurchaseOrder


class OrderStockTest(TestCase):
    def setUp(self):
        Configuration.objects.create(
            key='po_number_sequence', value='PO-{year}-{counter:04d}')
        AppState.objects.create(key='po_counter', value='0')
        cat = AccountingCategory.objects.create(name='c')
        self.item = InventoryItem.objects.create(
            code='SHEET-3', accounting_category=cat,
            qty_on_hand=Decimal('1'), purchase_price=Decimal('10'),
        )

    def test_creates_draft_po_with_unlinked_line(self):
        po, li = InventoryService.order_stock(self.item, Decimal('5'))
        self.assertEqual(po.status, PurchaseOrder.STATUS_DRAFT)
        self.assertEqual(li.inventory_item_id, self.item.pk)
        self.assertEqual(li.qty, Decimal('5'))
        self.assertIsNone(li.job_id)
        self.assertFalse(li.materials.exists())

    def test_appends_to_given_draft(self):
        po, _ = InventoryService.order_stock(self.item, Decimal('2'))
        po2, li2 = InventoryService.order_stock(self.item, Decimal('3'), po=po)
        self.assertEqual(po2.pk, po.pk)
        self.assertEqual(po.line_items.count(), 2)

    def test_refuses_non_draft_po(self):
        po, _ = InventoryService.order_stock(self.item, Decimal('2'))
        PurchaseOrder.objects.filter(pk=po.pk).update(
            status=PurchaseOrder.STATUS_ISSUED)
        po.refresh_from_db()
        with self.assertRaises(ValidationError):
            InventoryService.order_stock(self.item, Decimal('1'), po=po)

    def test_refuses_non_positive_quantity(self):
        with self.assertRaises(ValidationError):
            InventoryService.order_stock(self.item, Decimal('0'))
        with self.assertRaises(ValidationError):
            InventoryService.order_stock(self.item, Decimal('-1'))
```

Note: `li.materials` / `li.job_id` / `po.line_items` — verify the actual related
names on `PurchaseOrderLineItem` (check `apps/purchasing/models.py`; the material
link is `Material.po_line_item` so the reverse may be `material_set` or a
`related_name`; the PO line-items reverse may differ). Adjust the assertions to
the real names — the *intent* is: no job on the line, no material linked to it.
The status flip via `QuerySet.update()` is deliberate test scaffolding to skip
transition guards (PurchaseOrder.save has no minute-flooring side effects).

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_stock_order -v 1`
Expected: FAIL/ERROR — `InventoryService has no attribute 'order_stock'`.

- [ ] **Step 3: Implement** — in `apps/inventory/services.py`, inside `InventoryService`:

```python
    @staticmethod
    def order_stock(item, quantity, po=None):
        """Order an inventory item to stock: a plain PO line with no material
        link and no job — legit to buy just to have the inventory. Receipt
        lands in QOH via the normal PO receiving path. Mirrors
        MaterialService.order's draft-append-or-create contract."""
        from django.core.exceptions import ValidationError
        from django.db import transaction
        from apps.purchasing.models import PurchaseOrder
        from apps.purchasing.services import PurchaseOrderService
        if quantity is None or quantity <= 0:
            raise ValidationError({'quantity': ['Quantity must be greater than 0.']})
        if po is not None and po.status != PurchaseOrder.STATUS_DRAFT:
            raise ValidationError('Can only add lines to a draft purchase order.')
        with transaction.atomic():
            if po is None:
                po = PurchaseOrderService.create_po()
            li = PurchaseOrderService.add_line_item_from_pli(
                po.pk, item.pk, quantity)
        return po, li
```

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_stock_order -v 1`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/services.py tests/test_stock_order.py
git commit -m "feat(inventory): InventoryService.order_stock — order an item to stock, no material link"
```

---

### Task 3: `POST /api/inventory/{id}/order/`

**Files:**
- Modify: `apps/api/inventory/views.py` (`InventoryItemViewSet`)
- Modify: `apps/api/inventory/serializers.py` (add `StockOrderSerializer`)
- Test: `tests/test_api_inventory.py`

**Interfaces:**
- Produces: `POST /api/inventory/{id}/order/` body `{"quantity": "5.00", "po_id": <optional int>}`, permission `CanManageFinancials`. Response: the item's serialized data plus `po_id` and `po_number` keys (same convention as the material order action).

- [ ] **Step 1: Write failing tests** — append to `tests/test_api_inventory.py`:

```python
class InventoryStockOrderAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from apps.core.models import AppState, Configuration
        Configuration.objects.update_or_create(
            key='po_number_sequence',
            defaults={'value': 'PO-{year}-{counter:04d}'})
        AppState.objects.update_or_create(
            key='po_counter', defaults={'value': '0'})
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        cat = AccountingCategory.objects.get(pk=901)
        self.item = InventoryItem.objects.create(
            code='ORD-1', accounting_category=cat,
            purchase_price=Decimal('10'))

    def test_order_creates_po_and_returns_link_fields(self):
        resp = self.client.post(f'/api/inventory/{self.item.pk}/order/',
                                {'quantity': '4'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('po_id', resp.data)
        self.assertTrue(resp.data['po_number'])

    def test_order_appends_to_draft_when_po_id_given(self):
        first = self.client.post(f'/api/inventory/{self.item.pk}/order/',
                                 {'quantity': '1'}, format='json')
        po_id = first.data['po_id']
        resp = self.client.post(f'/api/inventory/{self.item.pk}/order/',
                                {'quantity': '2', 'po_id': po_id}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['po_id'], po_id)

    def test_order_requires_financials(self):
        plain = User.objects.create_user(username='noatom', password='x')
        client = APIClient()
        client.force_authenticate(user=plain)
        resp = client.post(f'/api/inventory/{self.item.pk}/order/',
                           {'quantity': '1'}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_order_rejects_missing_quantity(self):
        resp = self.client.post(f'/api/inventory/{self.item.pk}/order/',
                                {}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('quantity', resp.data)
```

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_api_inventory -v 1`
Expected: new tests FAIL (404 — no such action).

- [ ] **Step 3: Implement** — in `apps/api/inventory/serializers.py`:

```python
class StockOrderSerializer(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    po_id = serializers.IntegerField(required=False, allow_null=True)
```

In `apps/api/inventory/views.py`, import `StockOrderSerializer` and add to `InventoryItemViewSet`:

```python
    @action(detail=True, methods=['post'],
            permission_classes=[IsAuthenticated, CanManageFinancials])
    def order(self, request, pk=None):
        """Order this item to stock — plain PO line, no material link.
        Optional body po_id appends to that draft (same contract as the
        material order action)."""
        from django.shortcuts import get_object_or_404
        from apps.purchasing.models import PurchaseOrder
        s = StockOrderSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        item = self.get_object()
        po = None
        if s.validated_data.get('po_id'):
            po = get_object_or_404(PurchaseOrder, pk=s.validated_data['po_id'])
        po, _li = InventoryService.order_stock(
            item, s.validated_data['quantity'], po=po)
        data = self.get_serializer(item).data
        data['po_id'], data['po_number'] = po.pk, po.po_number
        return Response(data)
```

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_api_inventory -v 1`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add apps/api/inventory/views.py apps/api/inventory/serializers.py tests/test_api_inventory.py
git commit -m "feat(api): POST /api/inventory/{id}/order/ — stock-order action"
```

---

### Task 4: `GET /api/earmarks/` read-only list

**Files:**
- Modify: `apps/api/inventory/serializers.py` (add `EarmarkSerializer`)
- Modify: `apps/api/inventory/views.py` (add `EarmarkViewSet`)
- Modify: `apps/api/urls.py` (register router + api_root entry)
- Test: `tests/test_api_earmarks.py` (create)

**Interfaces:**
- Produces: `GET /api/earmarks/` — `IsAuthenticated`, **unpaginated** (`pagination_class = None`; response body is a plain JSON array). Row shape per the spec: `earmark_id, inventory_item, item_code, item_description, units, job, job_number, quantity, created_date, qty_on_hand, qty_on_order, qty_earmarked_total, pos:[{po_id,po_number}]`. `pos` lists distinct non-cancelled POs with an outstanding line for the item (`qty − qty_received − qty_cancelled > 0`). Read-only: POST/PATCH/DELETE are 405.

- [ ] **Step 1: Write failing tests** — create `tests/test_api_earmarks.py`:

```python
from decimal import Decimal
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, AccountingCategory, AppState, Configuration
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.inventory.models import Earmark, InventoryItem
from apps.inventory.services import InventoryService


class EarmarkAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        Configuration.objects.update_or_create(
            key='po_number_sequence',
            defaults={'value': 'PO-{year}-{counter:04d}'})
        AppState.objects.update_or_create(
            key='po_counter', defaults={'value': '0'})
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        cat = AccountingCategory.objects.get(pk=901)
        contact = Contact.objects.create(
            first_name='E', last_name='M', email='e@test.com')
        self.job = Job.objects.create(
            job_number='JOB-EM-1', contact=contact,
            status=Job.STATUS_APPROVED)
        self.item = InventoryItem.objects.create(
            code='EM-1', description='earmark item',
            accounting_category=cat, qty_on_hand=Decimal('1'))
        self.earmark = Earmark.objects.create(
            inventory_item=self.item, job=self.job, quantity=Decimal('4'))

    def _rows(self, resp):
        # Unpaginated: plain list, not {results: [...]}.
        self.assertIsInstance(resp.data, list)
        return resp.data

    def test_list_returns_item_and_job_fields(self):
        resp = self.client.get('/api/earmarks/')
        self.assertEqual(resp.status_code, 200)
        rows = self._rows(resp)
        row = next(r for r in rows if r['earmark_id'] == self.earmark.pk)
        self.assertEqual(row['item_code'], 'EM-1')
        self.assertEqual(row['job_number'], 'JOB-EM-1')
        self.assertEqual(Decimal(row['quantity']), Decimal('4'))
        self.assertEqual(Decimal(row['qty_on_hand']), Decimal('1'))
        self.assertEqual(Decimal(row['qty_earmarked_total']), Decimal('4'))
        self.assertEqual(row['pos'], [])

    def test_pos_lists_outstanding_pos_only(self):
        po, li = InventoryService.order_stock(self.item, Decimal('3'))
        resp = self.client.get('/api/earmarks/')
        row = next(r for r in self._rows(resp)
                   if r['earmark_id'] == self.earmark.pk)
        self.assertEqual(row['pos'], [{'po_id': po.pk, 'po_number': po.po_number}])
        self.assertEqual(Decimal(row['qty_on_order']), Decimal('3'))
        # Fully received → the PO is history, drops out of pos.
        li.qty_received = li.qty
        li.save()
        resp = self.client.get('/api/earmarks/')
        row = next(r for r in self._rows(resp)
                   if r['earmark_id'] == self.earmark.pk)
        self.assertEqual(row['pos'], [])

    def test_write_methods_rejected(self):
        resp = self.client.post('/api/earmarks/', {}, format='json')
        self.assertEqual(resp.status_code, 405)
        resp = self.client.delete(f'/api/earmarks/{self.earmark.pk}/')
        self.assertEqual(resp.status_code, 405)
```

(If `li.save()` on a PO line has receiving side effects, set `qty_received` via
the receiving service instead; check `PurchaseOrderLineItem` first. Direct
field-set + `save()` is expected to be fine — it has no minute-flooring.)

- [ ] **Step 2: Run to verify failure**

Run: `python manage.py test tests.test_api_earmarks -v 1`
Expected: FAIL with 404s (no route).

- [ ] **Step 3: Implement** — in `apps/api/inventory/serializers.py` (import `Earmark` from `apps.inventory.models`):

```python
class EarmarkSerializer(serializers.ModelSerializer):
    """Read-only commitment report row: the earmark plus the item-level
    figures the Catalog Earmarks tab needs (shortfall is computed
    client-side from the three quantities)."""
    item_code = serializers.CharField(source='inventory_item.code', read_only=True)
    item_description = serializers.CharField(
        source='inventory_item.description', read_only=True)
    units = serializers.CharField(source='inventory_item.units', read_only=True)
    job_number = serializers.CharField(source='job.job_number', read_only=True)
    qty_on_hand = serializers.DecimalField(
        source='inventory_item.qty_on_hand',
        max_digits=10, decimal_places=2, read_only=True)
    qty_on_order = serializers.DecimalField(
        source='inventory_item.qty_on_order',
        max_digits=10, decimal_places=2, read_only=True)
    qty_earmarked_total = serializers.DecimalField(
        source='inventory_item.qty_earmarked',
        max_digits=10, decimal_places=2, read_only=True)
    pos = serializers.SerializerMethodField()

    class Meta:
        model = Earmark
        fields = [
            'earmark_id', 'inventory_item', 'item_code', 'item_description',
            'units', 'job', 'job_number', 'quantity', 'created_date',
            'qty_on_hand', 'qty_on_order', 'qty_earmarked_total', 'pos',
        ]

    def get_pos(self, obj):
        """Distinct non-cancelled POs with an outstanding line for this item."""
        from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
        lines = PurchaseOrderLineItem.objects.filter(
            inventory_item=obj.inventory_item,
        ).exclude(
            purchase_order__status=PurchaseOrder.STATUS_CANCELLED,
        ).select_related('purchase_order')
        seen, out = set(), []
        for li in lines:
            if li.qty - li.qty_received - li.qty_cancelled <= 0:
                continue
            po = li.purchase_order
            if po.pk in seen:
                continue
            seen.add(po.pk)
            out.append({'po_id': po.pk, 'po_number': po.po_number})
        return out
```

In `apps/api/inventory/views.py` (import `Earmark`, `EarmarkSerializer`):

```python
class EarmarkViewSet(viewsets.ReadOnlyModelViewSet):
    """Earmarks are system-managed (created at establish/order, shrunk by
    restock, deleted by consume/release) — read-only over the API.
    Unpaginated: the whole table is small and the SPA sorts client-side."""
    queryset = (Earmark.objects
                .select_related('inventory_item', 'job')
                .order_by('inventory_item__code', 'job__job_number'))
    serializer_class = EarmarkSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None
```

In `apps/api/urls.py`: import `EarmarkViewSet` from `apps.api.inventory.views`, add
`router.register(r'earmarks', EarmarkViewSet, basename='earmark')` next to the
inventory registration, and add `'earmarks': '/api/earmarks/'` to the api_root dict.

- [ ] **Step 4: Run to verify pass**

Run: `python manage.py test tests.test_api_earmarks -v 1`
Expected: `OK`.

- [ ] **Step 5: Run the full backend suite** (no migrations were added, `--keepdb` not needed either way)

Run: `python manage.py test`
Expected: summary line `OK` (read it — do not trust a piped exit code).

- [ ] **Step 6: Commit**

```bash
git add apps/api/inventory/serializers.py apps/api/inventory/views.py apps/api/urls.py tests/test_api_earmarks.py
git commit -m "feat(api): read-only /api/earmarks/ — commitment report rows with item aggregates + outstanding POs"
```

---

### Task 5: Catalog routes, tabs, sidebar; move the inventory page

**Files:**
- Create: `frontend/src/components/CatalogTabs.svelte`
- Create: `frontend/src/routes/catalog/CatalogInventoryPage.svelte` (git mv of `frontend/src/routes/inventory/InventoryListPage.svelte`, then edit)
- Create: `frontend/src/routes/catalog/CatalogServiceItemsPage.svelte`
- Create: `frontend/src/routes/catalog/CatalogEarmarksPage.svelte` (skeleton; real table in Task 7)
- Modify: `frontend/src/App.svelte` (routes), `frontend/src/components/Sidebar.svelte` (link)
- Test: `frontend/tests/components/catalog/CatalogInventoryPage.test.js` (git mv of `frontend/tests/components/inventory/InventoryListPage.test.js`, update imports), `frontend/tests/components/catalog/CatalogTabs.test.js` (create)

**Interfaces:**
- Produces routes `/catalog`, `/catalog/service-items`, `/catalog/earmarks`; `CatalogTabs` renders the `<h2>Catalog</h2>` heading + the `<a use:link>` tab strip (each tab page renders `<CatalogTabs />` first, then its own content — pages no longer render their own `<h2>`).
- `/inventory` route and the sidebar "Inventory" entry are deleted; sidebar gains `<a href="/catalog" use:link>Catalog</a>` in the same position.

- [ ] **Step 1: Write failing test** — `frontend/tests/components/catalog/CatalogTabs.test.js`:

```js
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import CatalogTabs from '@/components/CatalogTabs.svelte';

describe('CatalogTabs', () => {
  it('renders the three tab links with their routes', () => {
    const { getByRole } = render(CatalogTabs);
    expect(getByRole('link', { name: 'Inventory' }).getAttribute('href'))
      .toContain('/catalog');
    expect(getByRole('link', { name: 'Service Items' }).getAttribute('href'))
      .toContain('/catalog/service-items');
    expect(getByRole('link', { name: 'Earmarks' }).getAttribute('href'))
      .toContain('/catalog/earmarks');
  });

  it('renders the area heading', () => {
    const { getByRole } = render(CatalogTabs);
    expect(getByRole('heading', { name: 'Catalog' })).toBeTruthy();
  });
});
```

(If existing page tests mock `svelte-spa-router`, follow the same mock pattern here — check `frontend/tests/components/inventory/InventoryListPage.test.js` before writing.)

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm run test:run -- tests/components/catalog/CatalogTabs.test.js`
Expected: FAIL — component doesn't exist.

- [ ] **Step 3: Implement `CatalogTabs.svelte`:**

```svelte
<script>
  import { link, location } from 'svelte-spa-router';

  const tabs = [
    { path: '/catalog', label: 'Inventory' },
    { path: '/catalog/service-items', label: 'Service Items' },
    { path: '/catalog/earmarks', label: 'Earmarks' },
  ];
</script>

<h2>Catalog</h2>

<nav class="catalog-tabs">
  {#each tabs as t (t.path)}
    <a href={t.path} use:link class:active={$location === t.path}>{t.label}</a>
  {/each}
</nav>

<style>
  /* Same visual vocabulary as .settings-tabs, but real links (per-tab routes). */
  .catalog-tabs {
    display: flex;
    gap: 0;
    border-bottom: 2px solid #ccc;
    margin-bottom: 1em;
  }
  .catalog-tabs a {
    padding: 0.4em 1.2em;
    border: 2px solid #ccc;
    border-bottom: none;
    background: #f5f5f5;
    color: inherit;
    text-decoration: none;
    margin-bottom: -2px;
  }
  .catalog-tabs a.active {
    background: white;
    border-bottom: 2px solid white;
    font-weight: bold;
  }
</style>
```

- [ ] **Step 4: Move + adapt the inventory page**

```bash
git mv frontend/src/routes/inventory/InventoryListPage.svelte frontend/src/routes/catalog/CatalogInventoryPage.svelte
git mv frontend/tests/components/inventory/InventoryListPage.test.js frontend/tests/components/catalog/CatalogInventoryPage.test.js
```

In `CatalogInventoryPage.svelte`: add `import CatalogTabs from '../../components/CatalogTabs.svelte';` and replace `<h2>Inventory</h2>` with `<CatalogTabs />`. (Relative import depth is unchanged — `routes/catalog/` is as deep as `routes/inventory/`.) Update the moved test file's import to `@/routes/catalog/CatalogInventoryPage.svelte` and any name references; if it asserted the `Inventory` heading, assert the `Catalog` heading instead. Delete the now-empty `frontend/src/routes/inventory/` and `frontend/tests/components/inventory/` dirs only if actually empty (`InventoryItemForm.svelte` lives in `components/inventory/` — untouched; `InventoryItemForm.test.js` stays in `tests/components/inventory/`).

- [ ] **Step 5: Create the two sibling pages**

`frontend/src/routes/catalog/CatalogServiceItemsPage.svelte`:

```svelte
<script>
  import CatalogTabs from '../../components/CatalogTabs.svelte';
  import ServiceItemManager from '../../components/ServiceItemManager.svelte';
</script>

<CatalogTabs />
<ServiceItemManager />
```

(Read-only gating lands in Task 8.)

`frontend/src/routes/catalog/CatalogEarmarksPage.svelte` (skeleton — Task 7 replaces the body):

```svelte
<script>
  import CatalogTabs from '../../components/CatalogTabs.svelte';
</script>

<CatalogTabs />
<p><em>Loading...</em></p>
```

- [ ] **Step 6: Rewire routes + sidebar**

`App.svelte`: replace the `InventoryListPage` import with the three catalog pages; in `routes`, delete `'/inventory': InventoryListPage,` and add (order matters — svelte-spa-router matches in insertion order, so the static children go in with the parent; there are no params so any order works):

```js
    '/catalog': CatalogInventoryPage,
    '/catalog/service-items': CatalogServiceItemsPage,
    '/catalog/earmarks': CatalogEarmarksPage,
```

`Sidebar.svelte` line 65: `<a href="/inventory" use:link>Inventory</a>` → `<a href="/catalog" use:link>Catalog</a>`.

- [ ] **Step 7: Run the full frontend suite + build**

Run: `cd frontend && npm run test:run && npm run build`
Expected: all tests pass (moved test included), build succeeds.

- [ ] **Step 8: Commit**

```bash
git add -A frontend/src frontend/tests
git commit -m "feat(spa): Catalog area — per-tab routes, tab strip, sidebar rename; inventory page moved under /catalog"
```

---

### Task 6: `StockOrderDialog` + Order button on the Inventory tab

**Files:**
- Create: `frontend/src/lib/stockShortfall.js`
- Create: `frontend/src/components/inventory/StockOrderDialog.svelte`
- Modify: `frontend/src/routes/catalog/CatalogInventoryPage.svelte` (replace the old order-button navigation)
- Test: `frontend/tests/lib/stockShortfall.test.js`, `frontend/tests/components/inventory/StockOrderDialog.test.js`, update `frontend/tests/components/catalog/CatalogInventoryPage.test.js`

**Interfaces:**
- `stockShortfall(row) -> string`: `max(0, earmarkedTotal − qty_on_hand − qty_on_order)` where earmarkedTotal is `row.qty_earmarked_total ?? row.qty_earmarked` (earmark rows vs. inventory rows).
- `StockOrderDialog` props: `{ item, prefillQty, onDone, onCancel }` — `item` needs `inventory_item_id` + `code`. Flow: qty input (pre-filled) → on Order: fetch `/api/purchase-orders/?status=draft&page_size=100`; zero drafts → POST immediately; else show the draft chooser (append buttons + "Start new PO"). POST `/api/inventory/{id}/order/` with `{quantity, po_id?}`; success → `showSuccess('Added to', {href, label: po_number})`, call `onDone()`.

- [ ] **Step 1: Write failing tests**

`frontend/tests/lib/stockShortfall.test.js`:

```js
import { describe, it, expect } from 'vitest';
import { stockShortfall } from '@/lib/stockShortfall.js';

describe('stockShortfall', () => {
  it('uses qty_earmarked on inventory rows', () => {
    expect(stockShortfall({ qty_earmarked: '6', qty_on_hand: '1', qty_on_order: '2' }))
      .toBe('3');
  });
  it('prefers qty_earmarked_total on earmark rows', () => {
    expect(stockShortfall({
      qty_earmarked_total: '6', qty_earmarked: '999',
      qty_on_hand: '1', qty_on_order: '2',
    })).toBe('3');
  });
  it('floors at zero when stock covers', () => {
    expect(stockShortfall({ qty_earmarked: '2', qty_on_hand: '5', qty_on_order: '0' }))
      .toBe('0');
  });
});
```

`frontend/tests/components/inventory/StockOrderDialog.test.js` (mock `@/lib/api.js` and `@/stores/messages.js` following the MessageOverlay / task-list test patterns):

```js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn() },
  errorMessage: (e, f) => e?.message || f,
}));
vi.mock('@/stores/messages.js', () => ({
  showSuccess: vi.fn(), showError: vi.fn(),
}));

import { api } from '@/lib/api.js';
import { showSuccess } from '@/stores/messages.js';
import StockOrderDialog from '@/components/inventory/StockOrderDialog.svelte';

const item = { inventory_item_id: 7, code: 'SHEET-3' };

beforeEach(() => {
  api.get.mockReset(); api.post.mockReset(); showSuccess.mockReset();
  api.post.mockResolvedValue({ po_id: 9, po_number: 'PO-2026-0001' });
});

describe('StockOrderDialog', () => {
  it('pre-fills the quantity and orders immediately when no drafts exist', async () => {
    api.get.mockResolvedValue({ results: [] });
    const onDone = vi.fn();
    const { getByLabelText, getByRole } = render(StockOrderDialog, {
      props: { item, prefillQty: '3', onDone, onCancel: () => {} },
    });
    expect(getByLabelText(/Quantity/).value).toBe('3');
    await fireEvent.click(getByRole('button', { name: 'Order' }));
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/api/inventory/7/order/', { quantity: '3' }));
    expect(showSuccess).toHaveBeenCalled();
    expect(onDone).toHaveBeenCalled();
  });

  it('offers the draft chooser when drafts exist and appends on pick', async () => {
    api.get.mockResolvedValue({ results: [
      { po_id: 4, po_number: 'PO-2026-0004', status: 'draft' },
    ] });
    const { getByRole, findByRole } = render(StockOrderDialog, {
      props: { item, prefillQty: '2', onDone: () => {}, onCancel: () => {} },
    });
    await fireEvent.click(getByRole('button', { name: 'Order' }));
    const appendBtn = await findByRole('button', { name: /PO-2026-0004/ });
    await fireEvent.click(appendBtn);
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/api/inventory/7/order/', { quantity: '2', po_id: 4 }));
  });

  it('can start a new PO from the chooser', async () => {
    api.get.mockResolvedValue({ results: [
      { po_id: 4, po_number: 'PO-2026-0004', status: 'draft' },
    ] });
    const { getByRole, findByRole } = render(StockOrderDialog, {
      props: { item, prefillQty: '2', onDone: () => {}, onCancel: () => {} },
    });
    await fireEvent.click(getByRole('button', { name: 'Order' }));
    await fireEvent.click(await findByRole('button', { name: 'Start new PO' }));
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/api/inventory/7/order/', { quantity: '2' }));
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm run test:run -- tests/lib/stockShortfall.test.js tests/components/inventory/StockOrderDialog.test.js`
Expected: FAIL — modules don't exist.

- [ ] **Step 3: Implement**

`frontend/src/lib/stockShortfall.js`:

```js
// Item-level shortfall (spec: catalog-area-ui): what you'd have to buy so
// every commitment on this item is covered. Item-level on purpose — per-row
// arithmetic understates when several jobs earmark the same item.
export function stockShortfall(row) {
  const earmarked = Number(row.qty_earmarked_total ?? row.qty_earmarked);
  const s = earmarked - Number(row.qty_on_hand) - Number(row.qty_on_order);
  return s > 0 ? String(s) : '0';
}
```

`frontend/src/components/inventory/StockOrderDialog.svelte`:

```svelte
<script>
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError, showSuccess } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';

  let { item, prefillQty = '', onDone = () => {}, onCancel = () => {} } = $props();

  let qty = $state(prefillQty);
  let drafts = $state(null);   // null = qty phase; [] handled inline
  let busy = $state(false);

  // Phase 1 → on Order: look for open drafts. Zero → order immediately
  // (silent create, same contract as the material order flow); some →
  // show the chooser.
  async function startOrder() {
    if (!String(qty).trim() || Number(qty) <= 0) return;
    busy = true;
    try {
      const resp = await api.get('/api/purchase-orders/?status=draft&page_size=100');
      const found = resp.results || resp;
      if (!found.length) {
        await submit(null);
        return;
      }
      drafts = found;
    } catch (e) {
      const t = triageError(e);
      showError(t.overlay || t.message || 'Could not load draft purchase orders.');
    } finally {
      busy = false;
    }
  }

  async function submit(poId) {
    busy = true;
    try {
      const body = poId
        ? { quantity: String(qty), po_id: poId }
        : { quantity: String(qty) };
      const resp = await api.post(
        `/api/inventory/${item.inventory_item_id}/order/`, body);
      showSuccess('Added to', {
        href: `#/purchase-orders/${resp.po_id}`, label: resp.po_number,
      });
      onDone();
    } catch (e) {
      const t = triageError(e);
      showError(t.overlay || t.message || 'Could not order.');
    } finally {
      busy = false;
    }
  }
</script>

<Modal open={true} onCancel={onCancel} maxWidth="480px">
  <h3>Order — {item.code}</h3>
  {#if drafts === null}
    <p><label for="stock-order-qty">Quantity</label><br>
      <input id="stock-order-qty" type="number" step="0.01" min="0"
        bind:value={qty}></p>
    <p>
      <button type="button" disabled={busy} onclick={startOrder}>Order</button>
      <button type="button" disabled={busy} onclick={onCancel}>Cancel</button>
    </p>
  {:else}
    <p>Add to an open draft PO, or start a new one:</p>
    <ul>
      {#each drafts as po (po.po_id)}
        <li><button type="button" disabled={busy} onclick={() => submit(po.po_id)}>
          {po.po_number}
        </button></li>
      {/each}
    </ul>
    <p>
      <button type="button" disabled={busy} onclick={() => submit(null)}>Start new PO</button>
      <button type="button" disabled={busy} onclick={onCancel}>Cancel</button>
    </p>
  {/if}
</Modal>
```

(Check `Modal.svelte`'s actual props before using — match how `CatalogInventoryPage` already invokes it. Draft PO id field: confirm the PO list serializer exposes `po_id` — adjust if it's `id`/`purchase_order_id`.)

- [ ] **Step 4: Wire into `CatalogInventoryPage.svelte`**

Remove the `push('/purchase-orders/new?...')` order button handler (and the now-unused `push` import if nothing else uses it). Add:

```js
  import StockOrderDialog from '../../components/inventory/StockOrderDialog.svelte';
  import { stockShortfall } from '../../lib/stockShortfall.js';

  let orderItem = $state(null);
```

Replace the order button markup with:

```svelte
              {#if $canManageFinancials}
                <button type="button" onclick={() => orderItem = it}>order</button>
              {/if}
```

And render, next to the other modals:

```svelte
  {#if orderItem}
    <StockOrderDialog item={orderItem} prefillQty={stockShortfall(orderItem)}
      onDone={() => { orderItem = null; load(); }}
      onCancel={() => orderItem = null} />
  {/if}
```

Update `CatalogInventoryPage.test.js` if it asserted the old navigation behavior.

- [ ] **Step 5: Run to verify pass**

Run: `cd frontend && npm run test:run`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/stockShortfall.js frontend/src/components/inventory/StockOrderDialog.svelte frontend/src/routes/catalog/CatalogInventoryPage.svelte frontend/tests
git commit -m "feat(spa): stock-order dialog — qty prompt with shortfall prefill, draft-append-or-create; wired into inventory tab"
```

---

### Task 7: Earmarks tab

**Files:**
- Modify: `frontend/src/routes/catalog/CatalogEarmarksPage.svelte` (replace skeleton)
- Test: `frontend/tests/components/catalog/CatalogEarmarksPage.test.js` (create)

**Interfaces:**
- Consumes: `GET /api/earmarks/` (plain array — Task 4 shape), `StockOrderDialog`, `stockShortfall`.
- Read-only table; client-side sortable columns; Order button (`canManageFinancials` only).

- [ ] **Step 1: Write failing tests** — `frontend/tests/components/catalog/CatalogEarmarksPage.test.js`. Follow the existing page-test mock pattern (check `CatalogInventoryPage.test.js` for the `svelte-spa-router` and permission-store mocks — permission stores are mocked as readable stores):

```js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { readable } from 'svelte/store';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('@/stores/permissions.js', () => ({
  canManageFinancials: readable(true),
  canManageJobs: readable(true),
  canManageConfig: readable(true),
}));

import { api } from '@/lib/api.js';
import CatalogEarmarksPage from '@/routes/catalog/CatalogEarmarksPage.svelte';

const rows = [
  {
    earmark_id: 1, inventory_item: 7, item_code: 'B-SHEET', item_description: 'acrylic',
    units: 'sheet', job: 3, job_number: 'JOB-2026-0011', quantity: '4.00',
    qty_on_hand: '1.00', qty_on_order: '2.00', qty_earmarked_total: '6.00',
    pos: [{ po_id: 9, po_number: 'PO-2026-0042' }],
  },
  {
    earmark_id: 2, inventory_item: 8, item_code: 'A-ROD', item_description: 'rod',
    units: 'ea', job: 4, job_number: 'JOB-2026-0012', quantity: '2.00',
    qty_on_hand: '5.00', qty_on_order: '0.00', qty_earmarked_total: '2.00',
    pos: [],
  },
];

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue(rows);
});

describe('CatalogEarmarksPage', () => {
  it('renders one row per earmark with job link, PO link and shortfall', async () => {
    const { findByText, getByRole } = render(CatalogEarmarksPage);
    await findByText('B-SHEET');
    expect(getByRole('link', { name: 'JOB-2026-0011' }).getAttribute('href'))
      .toContain('/jobs/3');
    expect(getByRole('link', { name: 'PO-2026-0042' }).getAttribute('href'))
      .toContain('/purchase-orders/9');
    // shortfall: 6 − 1 − 2 = 3
    await findByText('3');
  });

  it('sorts by a column on header click', async () => {
    const { findByText, getByRole, getAllByRole } = render(CatalogEarmarksPage);
    await findByText('B-SHEET');
    await fireEvent.click(getByRole('button', { name: /Code/ }));
    const cells = getAllByRole('row').slice(1).map(r => r.textContent);
    expect(cells[0]).toContain('A-ROD');   // ascending after click
  });

  it('shows an Order button per row for financials users', async () => {
    const { findAllByRole } = render(CatalogEarmarksPage);
    const buttons = await findAllByRole('button', { name: 'order' });
    expect(buttons.length).toBe(2);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm run test:run -- tests/components/catalog/CatalogEarmarksPage.test.js`
Expected: FAIL (skeleton renders nothing).

- [ ] **Step 3: Implement the page:**

```svelte
<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { canManageFinancials } from '../../stores/permissions.js';
  import CatalogTabs from '../../components/CatalogTabs.svelte';
  import StockOrderDialog from '../../components/inventory/StockOrderDialog.svelte';
  import { stockShortfall } from '../../lib/stockShortfall.js';

  let rows = $state([]);
  let loading = $state(true);
  let error = $state('');
  let orderRow = $state(null);

  // Client-side sort. Earmarks stay small (spec) — the API is unpaginated
  // and the browser owns ordering.
  let sortKey = $state('item_code');
  let sortDir = $state(1);
  const NUMERIC = new Set(['quantity', 'qty_on_hand', 'qty_on_order', 'shortfall']);

  function setSort(key) {
    if (sortKey === key) { sortDir = -sortDir; }
    else { sortKey = key; sortDir = 1; }
  }

  function sortValue(r, key) {
    if (key === 'shortfall') return Number(stockShortfall(r));
    if (NUMERIC.has(key)) return Number(r[key]);
    return String(r[key] ?? '').toLowerCase();
  }

  let sorted = $derived(
    [...rows].sort((a, b) => {
      const va = sortValue(a, sortKey), vb = sortValue(b, sortKey);
      return (va < vb ? -1 : va > vb ? 1 : 0) * sortDir;
    })
  );

  async function load() {
    loading = true;
    error = '';
    try {
      rows = await api.get('/api/earmarks/');
    } catch (e) {
      error = e.message || 'Could not load earmarks.';
    } finally {
      loading = false;
    }
  }

  load();
</script>

<CatalogTabs />

{#if loading}
  <p><em>Loading...</em></p>
{:else if error}
  <p><em>{error}</em></p>
{:else if rows.length === 0}
  <p><em>No earmarks — nothing is committed right now.</em></p>
{:else}
  <table class="data-table" style="width: 100%">
    <thead>
      <tr>
        <th><button type="button" class="sort" onclick={() => setSort('item_code')}>Code</button></th>
        <th><button type="button" class="sort" onclick={() => setSort('item_description')}>Description</button></th>
        <th><button type="button" class="sort" onclick={() => setSort('units')}>Units</button></th>
        <th><button type="button" class="sort" onclick={() => setSort('job_number')}>Job</button></th>
        <th style="text-align: right"><button type="button" class="sort" onclick={() => setSort('quantity')}>Earmarked</button></th>
        <th style="text-align: right"><button type="button" class="sort" onclick={() => setSort('qty_on_hand')}>On hand</button></th>
        <th style="text-align: right"><button type="button" class="sort" onclick={() => setSort('qty_on_order')}>On order</button></th>
        <th style="text-align: right"><button type="button" class="sort" onclick={() => setSort('shortfall')}>Shortfall</button></th>
        <th>POs</th>
        {#if $canManageFinancials}<th></th>{/if}
      </tr>
    </thead>
    <tbody>
      {#each sorted as r (r.earmark_id)}
        <tr class:short={Number(stockShortfall(r)) > 0}>
          <td>{r.item_code}</td>
          <td class="preserve-breaks">{r.item_description || '—'}</td>
          <td>{r.units}</td>
          <td><a href={`/jobs/${r.job}`} use:link>{r.job_number}</a></td>
          <td style="text-align: right">{r.quantity}</td>
          <td style="text-align: right">{r.qty_on_hand}</td>
          <td style="text-align: right">{r.qty_on_order}</td>
          <td style="text-align: right">{stockShortfall(r)}</td>
          <td>
            {#each r.pos as po, i (po.po_id)}
              {#if i > 0},&nbsp;{/if}
              <a href={`/purchase-orders/${po.po_id}`} use:link>{po.po_number}</a>
            {:else}
              —
            {/each}
          </td>
          {#if $canManageFinancials}
            <td><button type="button" onclick={() => orderRow = r}>order</button></td>
          {/if}
        </tr>
      {/each}
    </tbody>
  </table>
{/if}

{#if orderRow}
  <StockOrderDialog
    item={{ inventory_item_id: orderRow.inventory_item, code: orderRow.item_code }}
    prefillQty={stockShortfall(orderRow)}
    onDone={() => { orderRow = null; load(); }}
    onCancel={() => orderRow = null} />
{/if}

<style>
  .short td { background: #fff1f0; }
  th button.sort {
    background: none;
    border: none;
    padding: 0;
    font: inherit;
    font-weight: bold;
    cursor: pointer;
  }
</style>
```

(Svelte `{#each}...{:else}` inside the POs cell: verify this compiles in Svelte 5 — if not, use an explicit `{#if r.pos.length === 0}—{:else}...{/if}`.)

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npm run test:run`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/catalog/CatalogEarmarksPage.svelte frontend/tests/components/catalog/CatalogEarmarksPage.test.js
git commit -m "feat(spa): Earmarks tab — read-only commitment report with sortable columns, PO links, stock ordering"
```

---

### Task 8: ServiceItemManager read-only mode

**Files:**
- Modify: `frontend/src/components/ServiceItemManager.svelte`
- Modify: `frontend/src/routes/catalog/CatalogServiceItemsPage.svelte`
- Test: `frontend/tests/components/ServiceItemManager.test.js` (extend)

**Interfaces:**
- `ServiceItemManager` gains prop `canEdit = true`. When false: the Edit/Delete row buttons and the "Add Service Item" button don't render (the form is only reachable through them, so no further gating needed).
- `CatalogServiceItemsPage` passes `canEdit={$canManageJobs || $canManageFinancials || $canManageConfig}`.

- [ ] **Step 1: Write failing tests** — extend `ServiceItemManager.test.js` (reuse its existing api mocks/fixtures):

```js
  it('hides Add/Edit/Delete when canEdit is false', async () => {
    const { findByText, queryByRole } = render(ServiceItemManager, {
      props: { canEdit: false },
    });
    await findByText(/Service Items/);
    // Table still renders (read-only), but no mutating controls.
    expect(queryByRole('button', { name: 'Add Service Item' })).toBeNull();
    expect(queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(queryByRole('button', { name: 'Delete' })).toBeNull();
  });

  it('still shows the edit controls by default', async () => {
    const { findByRole } = render(ServiceItemManager);
    expect(await findByRole('button', { name: 'Add Service Item' })).toBeTruthy();
  });
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm run test:run -- tests/components/ServiceItemManager.test.js`
Expected: first new test FAILS (buttons render regardless).

- [ ] **Step 3: Implement** — in `ServiceItemManager.svelte`:

```js
  let { canEdit = true } = $props();
```

Wrap the row action cell contents (Edit/Delete buttons, lines ~180-181) in `{#if canEdit}...{/if}` and the "Add Service Item" paragraph (line ~187) in `{#if canEdit}...{/if}`.

In `CatalogServiceItemsPage.svelte`:

```svelte
<script>
  import CatalogTabs from '../../components/CatalogTabs.svelte';
  import ServiceItemManager from '../../components/ServiceItemManager.svelte';
  import { canManageJobs, canManageFinancials, canManageConfig }
    from '../../stores/permissions.js';

  let canEdit = $derived($canManageJobs || $canManageFinancials || $canManageConfig);
</script>

<CatalogTabs />
<ServiceItemManager {canEdit} />
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npm run test:run`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ServiceItemManager.svelte frontend/src/routes/catalog/CatalogServiceItemsPage.svelte frontend/tests/components/ServiceItemManager.test.js
git commit -m "feat(spa): ServiceItemManager read-only mode; Service Items tab gates edits to jobs|financials|config"
```

---

### Task 9: Settings — Pricing tab + shared default-material-category widget

**Files:**
- Create: `frontend/src/components/settings/DefaultMaterialCategorySetting.svelte`
- Modify: `frontend/src/components/settings/AccountingCategories.svelte` (remove the embedded Materials fieldset + its state/functions)
- Modify: `frontend/src/routes/SettingsPage.svelte`
- Test: `frontend/tests/components/settings/DefaultMaterialCategorySetting.test.js` (create), `frontend/tests/components/settings/AccountingCategories.test.js` (update — drop default-material assertions if present)

**Interfaces:**
- `DefaultMaterialCategorySetting` is self-contained: loads `/api/accounting-categories/` (active only, for the picker) and `/api/settings/`, saves `default_material_accounting_category` via `PATCH /api/settings/`. Rendered in BOTH the Accounting tab (after `<AccountingCategories />`) and the Pricing tab.
- SettingsPage: tab key `catalog` → `pricing`, button label `Pricing`; ServiceItemManager import + render removed; "Work templates" stub removed; Pricing tab renders `<MaterialMarkupSetting />`, `<DefaultMaterialCategorySetting />`, `<RateSchemeManager />`.

- [ ] **Step 1: Write failing tests** — `DefaultMaterialCategorySetting.test.js`:

```js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import DefaultMaterialCategorySetting
  from '@/components/settings/DefaultMaterialCategorySetting.svelte';

beforeEach(() => {
  api.get.mockReset(); api.patch.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/accounting-categories/')) {
      return Promise.resolve([
        { id: 1, name: 'Materials', is_active: true },
        { id: 2, name: 'Retired', is_active: false },
      ]);
    }
    return Promise.resolve({ default_material_accounting_category: '1' });
  });
  api.patch.mockResolvedValue({});
});

describe('DefaultMaterialCategorySetting', () => {
  it('loads categories (active only) and the current default', async () => {
    const { findByLabelText, queryByText } = render(DefaultMaterialCategorySetting);
    const select = await findByLabelText(/Default material category/);
    await vi.waitFor(() => expect(select.value).toBe('1'));
    expect(queryByText('Retired')).toBeNull();
  });

  it('saves via PATCH /api/settings/', async () => {
    const { findByLabelText, getByRole, findByText } = render(DefaultMaterialCategorySetting);
    await findByLabelText(/Default material category/);
    await fireEvent.click(getByRole('button', { name: /Save/ }));
    await vi.waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/api/settings/', { default_material_accounting_category: '1' }));
    await findByText('Default material category saved.');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm run test:run -- tests/components/settings/DefaultMaterialCategorySetting.test.js`
Expected: FAIL — component doesn't exist.

- [ ] **Step 3: Implement the component** (logic lifted verbatim from `AccountingCategories.svelte` lines 17-19, 55-62, 129-146, 230-250):

```svelte
<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';

  let categories = $state([]);
  let defaultMaterialCategoryId = $state('');
  let error = $state('');
  let success = $state('');
  let saving = $state(false);
  let loading = $state(true);

  let activeCategories = $derived(categories.filter(c => c.is_active));

  async function load() {
    loading = true;
    try {
      const [catData, settings] = await Promise.all([
        api.get('/api/accounting-categories/'),
        api.get('/api/settings/'),
      ]);
      categories = catData.results || catData;
      defaultMaterialCategoryId = settings.default_material_accounting_category || '';
    } catch (_) {
      // Best-effort: the picker just stays blank.
    } finally {
      loading = false;
    }
  }

  async function save() {
    saving = true;
    error = '';
    success = '';
    try {
      await api.patch('/api/settings/', {
        default_material_accounting_category: defaultMaterialCategoryId,
      });
      success = 'Default material category saved.';
      setTimeout(() => success = '', 3000);
    } catch (e) {
      const t = triageError(e);
      error = t.fields.default_material_accounting_category
        || t.message || t.overlay || 'Failed to save';
    } finally {
      saving = false;
    }
  }

  onMount(() => { load(); });
</script>

{#if !loading}
  <fieldset>
    <legend><strong>Materials</strong></legend>
    <p>
      <label for="default-material-category"><strong>Default material category</strong></label><br>
      <select id="default-material-category" bind:value={defaultMaterialCategoryId}>
        <option value="">-- None --</option>
        {#each activeCategories as cat (cat.id)}
          <option value={String(cat.id)}>{cat.name}</option>
        {/each}
      </select>
      {#if error}<strong>Error:</strong> {error}{/if}
      {#if success}<em>{success}</em>{/if}
    </p>
    <p><small>Accounting category applied by default to materials on estimate acceptance.</small></p>
    <p>
      <button type="button" onclick={save} disabled={saving}>
        {saving ? 'Saving...' : 'Save'}
      </button>
    </p>
  </fieldset>
{/if}
```

- [ ] **Step 4: Strip the embedded copy from `AccountingCategories.svelte`**

Remove: state `defaultMaterialCategoryId`/`materialCategoryError`/`savingMaterialCategory` (lines 17-19), `activeCategories` (line 21), `loadSettings` (lines 55-62, and its call in `loadData`), `saveDefaultMaterialCategory` (lines 129-146), and the whole `{#if !loadingCategories}` Materials fieldset (lines 230-250). Remove the `triageError` import if now unused. Update `AccountingCategories.test.js` if it asserted the Materials fieldset.

- [ ] **Step 5: Rewire `SettingsPage.svelte`**

- Delete the `ServiceItemManager` import; add `import DefaultMaterialCategorySetting from '../components/settings/DefaultMaterialCategorySetting.svelte';`
- Tab button: `catalog` → `pricing`, label `Pricing`.
- Accounting tab: after `<AccountingCategories />`, add `<DefaultMaterialCategorySetting />`.
- Pricing tab block becomes:

```svelte
{:else if tab === 'pricing'}
  <MaterialMarkupSetting />

  <DefaultMaterialCategorySetting />

  <RateSchemeManager />
```

(The `<h3>Work templates</h3>` stub is deleted — a future work-templates UI belongs in the Catalog area, not Settings.)

- [ ] **Step 6: Run the full frontend suite + build**

Run: `cd frontend && npm run test:run && npm run build`
Expected: all pass, build green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/settings frontend/src/routes/SettingsPage.svelte frontend/tests/components/settings
git commit -m "feat(spa): Settings Pricing tab — service items moved out, shared default-material-category widget in Accounting + Pricing"
```

---

### Task 10: Reconcile the durable docs

**Files:**
- Modify: `docs/designs/materials-inventory-and-purchasing.md` (Catalog area UI, `/api/earmarks/`, stock-order flow + `order_stock`)
- Modify: `docs/designs/users-and-permissions.md` (service-item writes → jobs|financials|config; new endpoints' gating: earmarks list IsAuthenticated, stock order financials)
- Modify: `docs/designs/architecture-and-conventions.md` (sidebar entry rename if the sidebar/nav is enumerated there; Catalog per-tab-route pattern worth one line)
- Modify: `docs/designs/estimates-and-prices.md` **only if** it names Settings as the ServiceItem venue (grep `ServiceItem` / `service item` first)
- Modify: `CLAUDE.md` (REST API list: add `/api/earmarks/`; SPA description: inventory → catalog)
- Modify: `docs/plans/2026-07-05-catalog-area-ui.md` (status header → implemented)

**Steps:**

- [ ] **Step 1:** Grep the four design docs (and `frontend/README.md`) for `Inventory` (as a nav/page name), `ServiceItem`, `Settings`, `earmark` and update every statement the branch changed: venue moves (ServiceItemManager Settings → `/catalog/service-items`), new endpoints, permission table rows, sidebar naming. Keep edits surgical — these are reference docs, not changelogs.
- [ ] **Step 2:** Run nothing (docs only). Re-read each edited section for drift against the code you just wrote.
- [ ] **Step 3: Commit**

```bash
git add docs CLAUDE.md
git commit -m "docs: reconcile design docs with the Catalog area (tabs, earmarks endpoint, stock ordering, Pricing tab)"
```

---

## Final verification (whole branch)

- [ ] Full backend suite: `python manage.py test` → read the `OK` summary line.
- [ ] Full frontend: `cd frontend && npm run test:run && npm run build`.
- [ ] Dispatch the final whole-branch code review (superpowers:requesting-code-review) over `merge-base` → `HEAD`.
- [ ] Do NOT merge/push/PR — leave `feature/inventory_again` for RM's browser review.

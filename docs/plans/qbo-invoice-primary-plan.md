# QBO Invoice as Primary Document — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push konbini invoices to QBO line-by-line (lazily minting QBO Items for catalog entities), adopt QBO's invoice numbering, and include QBO's hosted payment link in konbini's outbound invoice email.

**Architecture:** The QBO invoice becomes the primary document. Konbini composes the invoice (wizard) and sends the email; QBO owns number, tax, PDF, and the payment experience. `InvoiceGroupingService` is replaced by a per-line builder; catalog entities (`InventoryItem`, `ServiceItem`) mirror lazily into QBO Items at push time; `Task` gains ServiceItem provenance so task-sourced lines can find their catalog identity. Spec: `docs/plans/qbo-invoice-primary-spec.md`.

**Tech Stack:** Django 5.2, python-quickbooks SDK (mocked at the `QBOService` boundary in tests), Svelte 5 SPA, Vitest, Playwright.

## Global Constraints

- **Branch: `feature/qbo`.** All commits land here. Never merge/push/PR.
- **Never write to the dev DB.** No `migrate`, no `manage.py shell` ORM writes, no `loaddata`. `makemigrations` is fine; tests build their own DB.
- **Test commands:** always `python manage.py test <module> --noinput`. Never pipe the test command (exit code lies); read the `OK`/`FAILED` summary. Only ONE test run at a time.
- **After migration changes, the final full-suite run must NOT use `--keepdb`.**
- Status constants, not string literals. No `QuerySet.update()`/`bulk_*` where `save()` has side effects. Line-item deletes via `LineItemService.delete_line_item_with_renumber`.
- Error contract: services raise `ValidationError({'field': [...]})` or `ValidationError('sentence')`; don't catch-and-rerender.
- Mock QBO at the `QBOService` boundary (`QBOService.get_client`) plus `patch` of SDK classes at their import site, following `tests/test_qbo_invoice_push.py` patterns.
- TDD: failing test first, then code, then green, then commit.

---

### Task 1: `qbo_id` on catalog models + purge support

**Files:**
- Modify: `apps/inventory/models.py` (InventoryItem, ~line 23)
- Modify: `apps/estimates/models.py` (ServiceItem, ~line 428)
- Modify: `apps/qbo/management/commands/purge_qbo_data.py:35` (FIELD_RESETS)
- Create: migrations via `makemigrations`
- Test: `tests/test_purge_qbo_data.py` (extend)

**Interfaces:**
- Produces: `InventoryItem.qbo_id` and `ServiceItem.qbo_id` — `CharField(max_length=50, blank=True, default='')`. Empty string = not yet mirrored.

- [ ] **Step 1: Write failing test** — in `tests/test_purge_qbo_data.py`, add (adapting to the file's existing fixture/dump-building helpers — read the file first; there is an existing test that asserts `core.accountingcategory` resets, copy its shape):

```python
def test_purge_resets_catalog_qbo_ids(self):
    # Build a dump record for an inventory item and a service item with qbo_id set,
    # run the purge transform, assert qbo_id comes back ''.
    record = {'model': 'inventory.inventoryitem', 'pk': 1,
              'fields': {'code': 'X', 'qbo_id': '77'}}
    out = purge_record(record)  # use the module's actual transform entry point
    self.assertEqual(out['fields']['qbo_id'], '')
    record = {'model': 'estimates.serviceitem', 'pk': 1,
              'fields': {'template_name': 'X', 'qbo_id': '78'}}
    out = purge_record(record)
    self.assertEqual(out['fields']['qbo_id'], '')
```

- [ ] **Step 2: Run it, verify it fails** — `python manage.py test tests.test_purge_qbo_data --noinput` → FAILED (qbo_id survives untouched).

- [ ] **Step 3: Implement** — add to both models:

```python
    # QBO Item mirror (lazily created at first invoice push; '' = not mirrored)
    qbo_id = models.CharField(max_length=50, blank=True, default='')
```

Add to `FIELD_RESETS` in `purge_qbo_data.py`:

```python
    'inventory.inventoryitem': {'qbo_id': ''},
    'estimates.serviceitem': {'qbo_id': ''},
```

Run `python manage.py makemigrations inventory estimates`.

- [ ] **Step 4: Run tests** — `python manage.py test tests.test_purge_qbo_data --noinput` → OK.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "Add qbo_id mirror field to InventoryItem and ServiceItem"`

---

### Task 2: ServiceItem provenance on Task

**Files:**
- Modify: `apps/jobs/models.py` — `TaskBase` (~line 208, field block) and `copy_fields()` (~line 232)
- Modify: `apps/estimates/models.py` — `ServiceItem.generate_task` `Task.objects.create(...)` (~line 502)
- Modify: `apps/jobs/services.py` — template-task creation (~line 984)
- Create: migration via `makemigrations jobs`
- Test: `tests/test_task_service_item_provenance.py` (new)

**Interfaces:**
- Produces: `Task.service_item` (nullable FK to `estimates.ServiceItem`, `on_delete=SET_NULL`) — set whenever a task is generated from a ServiceItem; included in `TaskBase.copy_fields()` so clones keep their catalog identity.

- [ ] **Step 1: Write failing tests** — new file `tests/test_task_service_item_provenance.py`. Use `BaseTestCase` from `tests/base.py` and build the minimal Job/RateScheme/ServiceItem the way `tests/test_invoice_wizard_service.py` does (read its setUp for the factory idiom):

```python
from tests.base import BaseTestCase
# imports for Job, RateScheme, ServiceItem, Task, JobService as per existing tests

class TaskServiceItemProvenanceTests(BaseTestCase):
    def setUp(self):
        # create AccountingCategory, RateScheme, Job, ServiceItem per existing test idiom
        ...

    def test_generate_task_stamps_service_item(self):
        task = self.service_item.generate_task(self.job, est_qty=Decimal('1'))
        self.assertEqual(task.service_item_id, self.service_item.pk)

    def test_copy_fields_carries_service_item(self):
        task = self.service_item.generate_task(self.job, est_qty=Decimal('1'))
        self.assertEqual(task.copy_fields()['service_item_id'], self.service_item.pk)

    def test_jobservice_template_task_stamps_service_item(self):
        # exercise the JobService path at apps/jobs/services.py:~984
        # (find its public entry point — the API add-task-from-template action calls it)
        task = JobService.create_task_from_template(self.job, self.service_item)
        self.assertEqual(task.service_item_id, self.service_item.pk)
```

(Adjust the third test's call to the actual method name at `apps/jobs/services.py:984` — read the surrounding `def`.)

- [ ] **Step 2: Run, verify fail** — `python manage.py test tests.test_task_service_item_provenance --noinput` → FAILED (no field).

- [ ] **Step 3: Implement**

In `TaskBase` (so `copy_fields` works uniformly; PlanTask simply never sets it):

```python
    service_item = models.ForeignKey(
        'estimates.ServiceItem', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
        help_text='Catalog identity: the ServiceItem this task was generated from.',
    )
```

In `copy_fields()` add `service_item_id=self.service_item_id,`.
In `generate_task`'s `Task.objects.create(...)` add `service_item=self,`.
In `apps/jobs/services.py` (~984) add `service_item=template,` to the create call.
`python manage.py makemigrations jobs`.

- [ ] **Step 4: Run** the new module, plus regression: `python manage.py test tests.test_task_service_item_provenance tests.test_invoice_wizard_service --noinput` → OK. (Fresh DB, no `--keepdb`, since migrations changed.)

- [ ] **Step 5: Commit** — `"Task carries ServiceItem provenance from generate_task"`

---

### Task 3: `QBOItemMintService`

**Files:**
- Modify: `apps/qbo/services.py` (new service class, near `QBOAccountsService`)
- Test: `tests/test_qbo_item_mint.py` (new)

**Interfaces:**
- Consumes: `InventoryItem.qbo_id` / `ServiceItem.qbo_id` (Task 1).
- Produces: `QBOItemMintService.ensure_item(entity, client) -> str | ''` — returns the QBO Item id for an `InventoryItem` or `ServiceItem`, creating (or adopting by name) the QBO Item on first use and persisting `entity.qbo_id`. Returns `''` (mints nothing) when the entity's category has no `qbo_item_id` mapped — caller falls back.

- [ ] **Step 1: Write failing tests** (`tests/test_qbo_item_mint.py`) — mock the SDK `Item` class where it's imported (`quickbooks.objects.item.Item`), MagicMock client. Cover:

```python
class QBOItemMintTests(BaseTestCase):
    # setUp: AccountingCategory(code='MAT', taxable=True, qbo_item_id='55'),
    # InventoryItem(code='PLY', description='Plywood', accounting_category=cat),
    # RateScheme(accounting_category=cat) + ServiceItem(template_name='CNC Cutting', rate_scheme=rs)

    def test_short_circuits_on_existing_qbo_id(self):
        self.inv.qbo_id = '42'
        self.assertEqual(QBOItemMintService.ensure_item(self.inv, MagicMock()), '42')

    def test_mints_noninventory_item_for_inventory_item(self):
        # patch Item: Item.get(55) returns generic item with IncomeAccountRef;
        # constructed Item instance save() sets Id=901
        # assert: created with Type='NonInventory', Name='PLY',
        #   IncomeAccountRef copied from the generic item; entity.qbo_id == '901' persisted
        ...

    def test_mints_service_item_with_service_type_and_template_name(self):
        # ServiceItem → Type='Service', Name='CNC Cutting',
        #   category via rate_scheme.accounting_category
        ...

    def test_duplicate_name_adopts_existing(self):
        # save() raises QuickbooksException('Duplicate Name Exists Error', error_code=6240)
        # Item.filter(Name='PLY', qb=client) returns [existing with Id=333]
        # assert entity.qbo_id == '333', no raise
        ...

    def test_unmapped_category_returns_empty_and_mints_nothing(self):
        self.cat.qbo_item_id = ''
        self.cat.save()
        self.assertEqual(QBOItemMintService.ensure_item(self.inv, MagicMock()), '')
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.qbo_id, '')
```

Write these as real tests (the sketches above show intent; fill in the patch plumbing following `tests/test_qbo_accounts.py`).

- [ ] **Step 2: Run, verify fail** — module fails with `ImportError`/`AttributeError` (service missing).

- [ ] **Step 3: Implement** in `apps/qbo/services.py`:

```python
class QBOItemMintService:
    """Lazily mirrors konbini catalog entities (InventoryItem, ServiceItem)
    into QBO Items at invoice-push time.

    The income account for a minted Item is copied from the entity's
    AccountingCategory's generic fallback Item (Configuration lives in QBO:
    the bookkeeper sets income accounts once, on the per-category Items).
    """

    @staticmethod
    def ensure_item(entity, client):
        """Return the QBO Item id for entity, minting/adopting if needed.

        Returns '' when the entity's category has no qbo_item_id mapped
        (no income account to copy) — caller falls back to category/None.
        """
        if entity.qbo_id:
            return entity.qbo_id

        from apps.inventory.models import InventoryItem
        if isinstance(entity, InventoryItem):
            category = entity.accounting_category
            name = entity.code
            qbo_type = 'NonInventory'
        else:  # ServiceItem
            category = entity.effective_accounting_category
            name = entity.template_name
            qbo_type = 'Service'

        if not category or not category.qbo_item_id:
            return ''

        from quickbooks.objects.item import Item
        generic = Item.get(category.qbo_item_id, qb=client)

        item = Item()
        item.Name = name
        item.Type = qbo_type
        item.IncomeAccountRef = generic.IncomeAccountRef
        try:
            item.save(qb=client)
            qbo_id = str(item.Id)
        except Exception as e:
            if 'Duplicate Name Exists' not in str(e) and '6240' not in str(e):
                raise
            existing = Item.filter(Name=name, qb=client)
            if not existing:
                raise
            qbo_id = str(existing[0].Id)

        entity.qbo_id = qbo_id
        entity.save(update_fields=['qbo_id'])
        return qbo_id
```

- [ ] **Step 4: Run** — `python manage.py test tests.test_qbo_item_mint --noinput` → OK.

- [ ] **Step 5: Commit** — `"QBOItemMintService: lazy QBO Item minting with duplicate-name adopt"`

---

### Task 4: ItemRef resolution for invoice lines

**Files:**
- Modify: `apps/qbo/services.py` (`QBOInvoiceSyncService`)
- Test: `tests/test_qbo_item_ref_resolution.py` (new)

**Interfaces:**
- Consumes: `QBOItemMintService.ensure_item` (Task 3); `Task.service_item` (Task 2); `InvoiceLineItemSource` (`related_name='sources'`, `source_type` in task/material/expense/fee, `.resolve()`).
- Produces:
  - `QBOInvoiceSyncService._catalog_entity_for_line(line_item) -> InventoryItem | ServiceItem | None`
  - `QBOInvoiceSyncService._resolve_item_ref(line_item, client) -> str | None` — QBO Item id or None (omit ItemRef).

- [ ] **Step 1: Failing tests** (`tests/test_qbo_item_ref_resolution.py`) — DB-level tests; mock only `QBOItemMintService.ensure_item` where minting would fire. Cases:

1. Line with `inventory_item` FK → that entity.
2. Line with single task source whose task has `service_item` → that ServiceItem.
3. Line with two task sources sharing one `service_item` → that ServiceItem.
4. Line with two task sources with different `service_item`s → None (category fallback).
5. Line whose task source has `service_item=None` → None.
6. Line with single material source whose Material has `inventory_item` → that InventoryItem.
7. Line with material source whose Material has no `inventory_item` (provisional) → None.
8. Adjustment line (`adjustment_service` set) → None.
9. Expense/fee-sourced line → None.
10. `_resolve_item_ref`: entity found + mint returns id → id; entity found + mint returns `''` → falls to `category.qbo_item_id`; no entity + category mapped → `category.qbo_item_id`; no entity + category unmapped → None.

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** in `QBOInvoiceSyncService`:

```python
    @staticmethod
    def _catalog_entity_for_line(line_item):
        """The single catalog entity (InventoryItem or ServiceItem) this line
        sells, or None when there isn't exactly one."""
        if line_item.inventory_item_id:
            return line_item.inventory_item
        if line_item.adjustment_service_id:
            return None
        entities = set()
        for source in line_item.sources.all():
            if source.source_type == source.SOURCE_TASK:
                task = source.resolve()
                if not task.service_item_id:
                    return None
                entities.add(('service', task.service_item_id))
            elif source.source_type == source.SOURCE_MATERIAL:
                material = source.resolve()
                if not material.inventory_item_id:
                    return None
                entities.add(('inventory', material.inventory_item_id))
            else:  # expense / fee — no catalog identity
                return None
        if len(entities) != 1:
            return None
        kind, pk = entities.pop()
        if kind == 'service':
            from apps.estimates.models import ServiceItem
            return ServiceItem.objects.get(pk=pk)
        from apps.inventory.models import InventoryItem
        return InventoryItem.objects.get(pk=pk)

    @staticmethod
    def _resolve_item_ref(line_item, client):
        """QBO Item id for this line, or None to omit ItemRef."""
        entity = QBOInvoiceSyncService._catalog_entity_for_line(line_item)
        if entity is not None:
            qbo_id = QBOItemMintService.ensure_item(entity, client)
            if qbo_id:
                return qbo_id
        category = line_item.accounting_category
        if category and category.qbo_item_id:
            return category.qbo_item_id
        return None
```

- [ ] **Step 4: Run** → OK. **Step 5: Commit** — `"Per-line ItemRef resolution: catalog entity via line FK or source atoms"`

---

### Task 5: Per-line invoice builder; delete `InvoiceGroupingService`

**Files:**
- Modify: `apps/qbo/services.py` — rewrite `QBOInvoiceSyncService._build_qbo_invoice` (~line 341)
- Modify: `apps/invoicing/services.py` — `send_invoice` (~line 366): drop grouping call, pass client; delete `InvoiceGroupingService` (~line 445); drop now-unused `defaultdict`/`Decimal` imports if orphaned
- Delete: `tests/test_invoice_grouping.py`
- Rewrite: `tests/test_qbo_invoice_push.py`
- Test: also run `tests/test_invoice_send_category_gate.py`, `tests/test_api_invoicing.py`

**Interfaces:**
- Consumes: `_resolve_item_ref` (Task 4).
- Produces: `_build_qbo_invoice(invoice, qbo_customer_id, client)` — new signature (client needed for minting; grouped_lines gone). `send_invoice` updated to call it.

- [ ] **Step 1: Failing tests** — rewrite `tests/test_qbo_invoice_push.py` (keep its mock scaffolding: patch `QBOService.get_client`, SDK `Invoice`/`SalesItemLine` etc. at import sites; keep whatever send-flow tests still apply). New builder assertions:

1. Three konbini lines → three `SalesItemLine`s in line_number order, `Description` equal to each line's text verbatim, `Amount` = each `total_amount`.
2. `TaxCodeRef.value` == 'TAX' for a line whose category `taxable=True`, 'NON' otherwise.
3. Line with catalog identity → `ItemRef.value` from `_resolve_item_ref` (mock mint); uncategorized-catalog line with mapped category → category's `qbo_item_id`; unmapped → detail has no ItemRef set.
4. `CustomerMemo.value == f"Job {job.job_number} — {job.name}"`.
5. `BillEmail.Address` == the job contact's email (and not set when contact has no email).
6. `AllowOnlineCreditCardPayment is True` and `AllowOnlineACHPayment is True`.
7. `InvoiceGroupingService` no longer exists (`ImportError` guard test not needed — just ensure nothing imports it; grep).

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement.** New builder:

```python
    @staticmethod
    def _build_qbo_invoice(invoice, qbo_customer_id, client):
        from quickbooks.objects.invoice import Invoice as QBOInvoice
        from quickbooks.objects.detailline import SalesItemLine, SalesItemLineDetail
        from quickbooks.objects.base import Ref, EmailAddress, CustomerMemo

        qbo_inv = QBOInvoice()
        qbo_inv.CustomerRef = Ref()
        qbo_inv.CustomerRef.value = qbo_customer_id
        qbo_inv.AllowOnlineCreditCardPayment = True
        qbo_inv.AllowOnlineACHPayment = True

        job = invoice.job
        memo = CustomerMemo()
        memo.value = f"Job {job.job_number} — {job.name}"
        qbo_inv.CustomerMemo = memo

        contact = job.contact
        if contact and contact.email:
            qbo_inv.BillEmail = EmailAddress()
            qbo_inv.BillEmail.Address = contact.email

        qbo_inv.Line = []
        line_items = (invoice.invoicelineitem_set
                      .select_related('accounting_category', 'inventory_item')
                      .order_by('line_number'))
        for li in line_items:
            line = SalesItemLine()
            line.Amount = float(li.total_amount)
            line.Description = li.description

            detail = SalesItemLineDetail()
            item_id = QBOInvoiceSyncService._resolve_item_ref(li, client)
            if item_id:
                detail.ItemRef = Ref()
                detail.ItemRef.value = item_id
            detail.TaxCodeRef = Ref()
            detail.TaxCodeRef.value = 'TAX' if li.accounting_category.taxable else 'NON'
            line.SalesItemLineDetail = detail
            qbo_inv.Line.append(line)
        return qbo_inv
```

(Verify `CustomerMemo` import location in the installed python-quickbooks — `from quickbooks.objects.base import CustomerMemo`; if absent there, find it with `python -c "import quickbooks.objects.base as b; print([n for n in dir(b)])"`.)

In `send_invoice`, replace:

```python
            grouped_lines = InvoiceGroupingService.group_for_qbo(invoice)
            qbo_invoice = QBOInvoiceSyncService._build_qbo_invoice(
                invoice, qbo_customer_id, grouped_lines,
            )
```

with:

```python
            qbo_invoice = QBOInvoiceSyncService._build_qbo_invoice(
                invoice, qbo_customer_id, client,
            )
```

Delete the `InvoiceGroupingService` class and `tests/test_invoice_grouping.py`. Grep for stray imports: `grep -rn "InvoiceGroupingService\|group_for_qbo" apps/ tests/ frontend/src/`.

- [ ] **Step 4: Run** — `python manage.py test tests.test_qbo_invoice_push tests.test_invoice_send_category_gate tests.test_api_invoicing tests.test_qbo_item_ref_resolution --noinput` → OK.

- [ ] **Step 5: Commit** — `"Per-line QBO invoice push; delete InvoiceGroupingService"`

---

### Task 6: Payment link in konbini's email

**Files:**
- Modify: `apps/qbo/services.py` — add `QBOInvoiceSyncService._fetch_invoice_link(client, qbo_id)`
- Modify: `apps/invoicing/services.py` — `send_invoice` substitutes `{payment_link}`; `DEFAULT_BODY` gains the link line; `get_email_defaults` passes the placeholder through
- Modify: `frontend/src/components/settings/EmailTemplates.svelte` — document `{payment_link}` in the invoice-template placeholder help text (match how existing placeholders are listed)
- Test: extend `tests/test_qbo_invoice_push.py` (send-flow section)

**Interfaces:**
- Consumes: pushed invoice `qbo_id`.
- Produces: `_fetch_invoice_link(client, qbo_id) -> str` (empty string if QBO returns none); `send_invoice` renders `{payment_link}` in subject/body via `render_email_template` at send time.

- [ ] **Step 1: Failing tests:**

1. `_fetch_invoice_link` reads the invoice via the SDK with `include=invoiceLink` — python-quickbooks: `Invoice.get(qbo_id, qb=client, params={'include': 'invoiceLink'})`; if the installed version's `.get` lacks `params`, drop to `client.get_single_object('Invoice', pk=qbo_id, params={'include': 'invoiceLink'})` and read `['Invoice']['invoiceLink']`. Test asserts returned link string, and `''` when attribute missing.
2. `send_invoice` with body `'Pay here: {payment_link}'` → `send_tracked` called with body `'Pay here: https://…'` (mock `_fetch_invoice_link`).
3. Body without the placeholder → unchanged.
4. `DEFAULT_BODY` contains `{payment_link}`.

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement.**

```python
    @staticmethod
    def _fetch_invoice_link(client, qbo_id):
        """Shareable hosted-invoice URL (carries the Pay button when QBO
        Payments is active). '' when QBO returns none."""
        from quickbooks.objects.invoice import Invoice as QBOInvoice
        qbo_invoice = QBOInvoice.get(qbo_id, qb=client, params={'include': 'invoiceLink'})
        return getattr(qbo_invoice, 'InvoiceLink', '') or ''
```

In `send_invoice`, after the push block (always — retry path too):

```python
        from apps.core.email_templates import render_email_template
        payment_link = QBOInvoiceSyncService._fetch_invoice_link(client, invoice.qbo_id)
        subject = render_email_template(subject, payment_link=payment_link)
        body = render_email_template(body, payment_link=payment_link)
```

Update `DEFAULT_BODY` to:

```python
    DEFAULT_BODY = (
        'Hi {contact_fname},\n\n'
        'Please find attached your invoice {document_number} for {job_name}. '
        'You can view and pay it online here: {payment_link}\n\n'
        'Thanks,\n{my_user_name}'
    )
```

`get_email_defaults` needs no change (`render_email_template` passes unknown `{payment_link}` through literally, so it survives into the dialog and is substituted at send).

- [ ] **Step 4: Run the module** → OK. **Step 5: Commit** — `"Invoice email carries QBO hosted payment link via {payment_link}"`

---

### Task 7: QBO-assigned numbering

**Files:**
- Modify: `apps/invoicing/models.py` — `invoice_number` nullable; remove auto-generation in `save()` (~line 98); add `display_number` property; `__str__`s (~138, ~170)
- Create: migration via `makemigrations invoicing`
- Modify: `apps/invoicing/services.py` — `send_invoice` DocNumber writeback; attachment names; `get_email_defaults` values + `attachments_preview`
- Modify: `apps/api/invoicing/serializers.py` — add `display_number` to the three field lists (~104, 113, 199)
- Test: `tests/test_invoice_numbering.py` (new); update `tests/test_invoicing_models.py` and any test asserting generated `INV-…` numbers (`grep -rln "invoice_number" tests/`)

**Interfaces:**
- Produces: `Invoice.display_number` — `invoice_number` if set, else `f'Draft — {job.job_number}'` (job is required on Invoice). Serializers expose it read-only. `send_invoice` sets `invoice_number` from QBO `DocNumber` right after push (and backfills on retry sends via `Invoice.get`).

- [ ] **Step 1: Failing tests** (`tests/test_invoice_numbering.py`):

1. New draft invoice has `invoice_number is None`; `display_number == f'Draft — {job.job_number}'`.
2. Two drafts on two jobs coexist (no unique collision on NULL).
3. `str(invoice)` uses `display_number`.
4. Send flow: mocked QBO save sets `DocNumber='1042'` → after `send_invoice`, `invoice.invoice_number == '1042'` and attachment filenames use `Invoice-1042.pdf` (assert via `send_tracked` mock call args).
5. Retry path: invoice with `qbo_id` set but `invoice_number` None → `send_invoice` fetches the QBO invoice and backfills DocNumber.
6. `get_email_defaults` for a draft renders `{document_number}` as the draft placeholder.

- [ ] **Step 2: Run, verify fail** (unique constraint / auto-generation currently interfere).

- [ ] **Step 3: Implement.**

Model: `invoice_number = models.CharField(max_length=50, unique=True, null=True, blank=True)`; delete the auto-generate block in `save()` (and the now-unused `NumberGenerationService` import if orphaned); add:

```python
    @property
    def display_number(self):
        return self.invoice_number or f'Draft — {self.job.job_number}'
```

`__str__`: `return f"Invoice {self.display_number}"` (and the line-item `__str__` similarly). `makemigrations invoicing`.

In `send_invoice`, inside the push block after `invoice.qbo_id = qbo_id`:

```python
            doc_number = str(getattr(qbo_invoice, 'DocNumber', '') or '')
            if doc_number:
                invoice.invoice_number = doc_number
            invoice.save(update_fields=['qbo_id', 'invoice_number'])
```

And before the attachments block (retry-path backfill):

```python
        if not invoice.invoice_number:
            from quickbooks.objects.invoice import Invoice as SDKInvoice
            fetched = SDKInvoice.get(invoice.qbo_id, qb=client)
            doc_number = str(getattr(fetched, 'DocNumber', '') or '')
            if doc_number:
                invoice.invoice_number = doc_number
                invoice.save(update_fields=['invoice_number'])
```

Attachment names + `get_email_defaults`'s `document_number`/`invoice_number` values and `attachments_preview` filenames: use `invoice.display_number` (at actual send time the real number exists; defaults for a draft show the placeholder).

Serializers: add `'display_number'` (read-only — it's a property, DRF handles via `fields` + `read_only_fields` or `ReadOnlyField`).

- [ ] **Step 4: Run** — `python manage.py test tests.test_invoice_numbering tests.test_invoicing_models tests.test_api_invoicing tests.test_api_invoice_list tests.test_qbo_invoice_push --noinput`; fix every test that asserted generated numbers (give drafts explicit numbers only where the test needs a sent invoice). Fresh DB (no `--keepdb`).

- [ ] **Step 5: Commit** — `"QBO assigns invoice numbers; drafts display placeholder identity"`

---

### Task 8: Drop phantom tax overrides; delete `TaxCalculationService`

**Files:**
- Modify: `apps/core/models.py` — remove `taxable_override`, `tax_rate_override` from `BaseLineItem` (~lines 358-365)
- Modify: `apps/core/services.py` — delete `TaxCalculationService` (~line 1128)
- Modify: serializers — remove both fields: `apps/api/invoicing/serializers.py:65`, `apps/api/estimates/serializers.py:57`, `apps/api/purchasing/serializers.py:62,153`, `apps/api/change_orders/serializers.py:18`
- Modify: `apps/estimates/change_order_service.py:362-363` — drop both kwargs
- Modify: `apps/invoicing/services.py` — remove `TaxCalculationService` import (line 8)
- Create: migrations via `makemigrations` (estimates, invoicing, purchasing — wherever the concrete tables land)
- Test: `grep -rln "taxable_override\|tax_rate_override\|TaxCalculationService" tests/` and update

**Interfaces:** none new — pure removal. `Business.tax_exemption_number` / `tax_multiplier` untouched.

- [ ] **Step 1:** Grep first: `grep -rn "taxable_override\|tax_rate_override\|TaxCalculationService\|get_effective_taxability" apps/ tests/ frontend/src/`. Every hit is either a removal site listed above or a test to update. No new failing test to write (deletion task) — the failing state is the suite after removal.

- [ ] **Step 2: Implement removals**, run `makemigrations`.

- [ ] **Step 3: Run affected test modules** (from the grep list, e.g. `tests.test_invoicing_services`, `tests.test_qbo_accounting_category`, change-order modules) with `--noinput`, fresh DB → OK.

- [ ] **Step 4: Commit** — `"Remove phantom per-line tax overrides and TaxCalculationService"`

---

### Task 9: SPA — draft placeholder, payment-link hint, retire invoice-number pattern setting

**Files:**
- Modify: `frontend/src/routes/invoices/InvoiceListPage.svelte:97`, `frontend/src/components/invoices/InvoicePanel.svelte:193,251,286`, `frontend/src/lib/jobOverview.js:518`, plus every `invoice_number` render found by `grep -rn "invoice_number" frontend/src/` that displays an *invoice's* number (skip Bill/PO files) — switch to `display_number`
- Modify: `frontend/src/components/settings/GeneralSettings.svelte` — remove the invoice-number-pattern input (grep `invoice` in that file; leave other patterns)
- Test: `frontend/tests/` — update/add Vitest specs for the touched components (`npm run test:run` from `frontend/`)

**Interfaces:** Consumes serializer `display_number` (Task 7).

- [ ] **Step 1: Failing Vitest** — extend the existing invoice list/panel component specs (find them: `ls frontend/tests | grep -i invoice`): a draft invoice (`invoice_number: null, display_number: 'Draft — JOB-2025-0001'`) renders the placeholder; a sent one renders `'1042'`.

- [ ] **Step 2: Run** `npm run test:run` → FAIL.

- [ ] **Step 3: Implement** the component/lib changes (`inv.display_number` instead of `inv.invoice_number`; in `jobOverview.js` label likewise). Remove the pattern input from GeneralSettings. Add `{payment_link}` to the invoice-template placeholder list in `EmailTemplates.svelte` if Task 6 didn't already.

- [ ] **Step 4: Run** `npm run test:run` → OK.

- [ ] **Step 5: Commit** — `"SPA: invoice display_number, retire invoice number pattern setting"`

---

### Task 10: E2E + docs + LATER

**Files:**
- Modify: the invoice-flow e2e spec (`grep -rln "invoice" e2e/tests/` — likely `e2e/tests/invoices*.spec.js`): draft shows `Draft — JOB-…`; no generated `INV-` number appears. QBO push/send is not e2e-reachable (no QBO connection in the e2e env) — assert only the draft-side UI.
- Modify docs (same session, per repo rule):
  - `docs/designs/quickbooks-integration.md` — per-line push, `QBOItemMintService`, ItemRef resolution, invoiceLink fetch, DocNumber writeback
  - `docs/designs/invoicing-and-expenses.md` — numbering (QBO-assigned, `display_number`), send flow, `{payment_link}` placeholder
  - `docs/designs/jobs-tasks-and-worksheets.md` + `estimates-and-prices.md` — `Task.service_item` provenance; ServiceItem `qbo_id`
  - `docs/designs/materials-inventory-and-purchasing.md` — InventoryItem `qbo_id`
  - `docs/designs/data-constraints.md` — `invoice_number` now nullable/QBO-assigned; removed tax-override fields; retired `invoice` numbering pattern
  - `docs/designs/LATER.md` — add: catalog rename propagation to QBO Items; business-level tax exemption via QBO Customer
- Run: `cd e2e && npx playwright test <invoice spec>` (dev servers may stay up)

- [ ] **Step 1:** Update the e2e spec expectations; run that spec; fix until green.
- [ ] **Step 2:** Update all docs listed.
- [ ] **Step 3: Commit** — `"E2E + design docs for QBO-primary invoicing"`

---

### Task 11: Final verification

- [ ] **Step 1:** Full backend suite, fresh DB (migrations changed — NO `--keepdb`): `python manage.py test --noinput` writing output to a file; then grep the file for the `Ran N tests` + `OK`/`FAILED` summary. Fix anything red.
- [ ] **Step 2:** `cd frontend && npm run test:run` → all green.
- [ ] **Step 3:** Full e2e: `cd e2e && npx playwright test` → all green.
- [ ] **Step 4:** `grep -rn "InvoiceGroupingService\|taxable_override\|tax_rate_override\|TaxCalculationService" apps/ tests/ frontend/src/` → zero hits.
- [ ] **Step 5:** Final commit of any stragglers. Report done for RM review — do NOT merge/push/PR.

## Self-review notes

- Spec coverage: per-line push (T5), Item minting incl. duplicate-adopt + income-account copy (T3), ItemRef resolution incl. provenance gap fix (T2+T4), numbering (T7), payment link + send flow (T6), tax simplification + override removal (T8), AccountingCategory roles unchanged in code (no task needed), SPA (T9), e2e/docs/LATER (T10). Sandbox spike items are manual/RM-facing, not implementable here — listed in the spec.
- The `CustomerMemo` SDK import location and `Invoice.get(..., params=)` support must be verified against the installed python-quickbooks version at T5/T6 (fallback given).

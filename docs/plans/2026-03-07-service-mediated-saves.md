# Service-Mediated Saves Refactor

**Date:** 2026-03-07
**Status:** Approved
**Scope:** Refactor HTML views to route all writes through service methods
**Do before:** API implementation

---

## Overview

Currently, most HTML views update models inline:

```python
# Typical inline save in a view
estimate.status = Estimate.STATUS_ACCEPTED
estimate.save()
```

This works today but creates a problem: side effects (signals, related model updates, transaction wrapping) can be bypassed or duplicated. When the API layer is added, both the HTML view and the API view would need identical save logic — or one would miss a side effect.

**Solution:** Every model write goes through a service method. Views (HTML and API) call services, never save models directly.

---

## Current State (Post-Reorganization Audit)

### Existing Services

| File | Class | Methods |
|------|-------|---------|
| `core/services.py` | `NumberGenerationService` | `generate_next_number`, `reset_counter` |
| `core/services.py` | `EmailService` | `fetch_new_emails`, `link_email_to_job`, etc. |
| `core/services.py` | `LineItemService` | `delete_line_item_with_renumber`, `reorder_line_item`, `can_modify_line_items`, `calculate_total` |
| `core/services.py` | `TaxCalculationService` | `get_effective_taxability`, `calculate_line_item_tax`, `calculate_document_tax` |
| `estimates/services.py` | `EstimateService` | `create_from_work_order`, `create_direct` (will absorb `EstimateGenerationService`) |
| `estimates/services.py` | `EstimateGenerationService` | `generate_estimate_from_worksheet` (→ merge into `EstimateService`) |
| `jobs/services.py` | `LineItemTaskService` | `generate_tasks_for_work_order` |
| `jobs/services.py` | `WorkOrderService` | `create_from_estimate`, `create_from_template`, `create_direct` |
| `jobs/services.py` | `TaskService` | `create_from_line_item`, `create_from_template`, `create_direct`, `create_line_item_from_task` |
| `inventory/services.py` | `InventoryService` | `create_item`, `update_item`, `receive_po_line_item`, `consume_material`, `manual_adjustment`, `get_earmark_preview`, `create_earmarks_for_job` |

### Inline Saves by App (View Audit)

Total: ~74 inline database operations across all views. Only 2 currently go through services (PO/bill line item deletion via `LineItemService`).

---

## Target Pattern

### Key principles

1. **Services accept IDs and primitives, not model instances or forms.**
   Views (HTML or API) never load models for write operations — the service
   does all lookups internally. This keeps views thin and ensures the service
   owns the full operation including object resolution.

2. **Services raise domain exceptions, views map to HTTP responses.**
   `ServiceError` and `NotFoundError` (in `core/services.py`) are the base
   exceptions. Views catch these and translate to 404s, error messages, etc.

3. **No forms or serializers cross into the service layer.**
   Views extract `form.cleaned_data` or `serializer.validated_data` and pass
   the resulting primitives/IDs to the service.

### Create example

```python
# Service — takes primitives, does its own lookups
class JobService:
    @staticmethod
    def create_job(*, name, contact_id, description='', customer_po_number=''):
        contact = Contact.objects.get(pk=contact_id)  # service resolves
        job = Job(name=name, contact=contact, description=description,
                  customer_po_number=customer_po_number)
        job.full_clean()
        job.save()
        return job

# HTML view
def job_create(request):
    form = JobCreateForm(request.POST)
    if form.is_valid():
        job = JobService.create_job(**form.cleaned_data)
        messages.success(request, f'Job {job.job_number} created.')
        return redirect(...)

# API view
def create(self, request):
    serializer = JobSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    job = JobService.create_job(**serializer.validated_data)
    return Response(...)
```

### Update/action example

```python
# Service — takes PK, raises NotFoundError if missing
class EstimateService:
    @staticmethod
    def accept_estimate(estimate_id):
        try:
            estimate = Estimate.objects.select_related('job').get(pk=estimate_id)
        except Estimate.DoesNotExist:
            raise NotFoundError(f'Estimate {estimate_id} not found')
        with transaction.atomic():
            estimate.status = Estimate.STATUS_ACCEPTED
            estimate.full_clean()
            estimate.save()
            estimate.job.status = Job.STATUS_APPROVED
            estimate.job.full_clean()
            estimate.job.save()
        return estimate

# HTML view — catches domain exception, maps to user-facing response
try:
    EstimateService.accept_estimate(estimate_id)
    messages.success(request, 'Estimate accepted.')
except NotFoundError:
    raise Http404
```

### Exception hierarchy

```python
# In core/services.py
class ServiceError(Exception):
    """Base exception for service-layer errors."""
    pass

class NotFoundError(ServiceError):
    """Raised when a requested object does not exist."""
    pass
```

---

## View Audit Results

### jobs/views.py (11 inline operations)

| View | Operation | Model | What it does |
|------|-----------|-------|-------------|
| `job_create` | `form.save(commit=False)` + `.save()` | Job | Creates new job |
| `job_create` | `.save()` | EmailRecord | Links email to new job |
| `job_edit` | `form.save()` | Job | Updates job fields |
| `task_edit` | `form.save()` | Task | Updates task fields |
| `work_order_detail` | `.status = ...; .save()` | WorkOrder | Status transition |
| `task_reorder_work_order` | `.save()` x2 | Task | Swaps sort_order on two tasks |
| `material_add` | `form.save()` | Material | Creates material on task |
| `material_edit` | `form.save()` | Material | Updates material |
| `material_delete` | `.delete()` | Material | Deletes material |

### estimates/views.py (45+ inline operations)

| View | Operation | Model | What it does |
|------|-----------|-------|-------------|
| `_copy_worksheet_to_work_order` | `.create()` | TaskBundle, Task, Material | Copies worksheet contents to work order |
| `estimate_detail` | `.save()` | Estimate | Status transition |
| `add_work_order_template` | `form.save()` | WorkOrderTemplate | Creates template |
| `work_order_template_edit` | `form.save()` | WorkOrderTemplate | Updates template |
| `work_order_template_delete` | `.delete()` | WorkOrderTemplate | Deletes template |
| `work_order_template_detail` | `.save()`, `.delete()` (many) | TemplateTaskAssociation, TemplateBundle | Bundle/unbundle operations |
| `estworksheet_detail` | `.save()`, `.delete()` (many) | Task, TaskBundle | Bundle/unbundle operations |
| `estworksheet_generate_estimate` | `.save()` (loop) | Task | Assigns line_item_type pre-generation |
| `estworksheet_generate_estimate` | `.save()` | EstWorksheet | Sets status to 'final' |
| `estimate_mark_open` | `.save()` | Estimate | Sets status to 'open' |
| `estimate_mark_open` | `.save()` | EstWorksheet | Sets status to 'final' |
| `estworksheet_revise` | `.create()` | EstWorksheet | Creates new revision |
| `estworksheet_revise` | `.create()` (loop) | Task | Copies tasks to new revision |
| `estworksheet_revise` | `.save()` | EstWorksheet | Marks parent superseded |
| `add_task_template_standalone` | `form.save()` | TaskTemplate | Creates template |
| `task_template_edit` | `form.save()` | TaskTemplate | Updates template |
| `task_template_delete` | `.delete()` | TaskTemplate | Deletes template |
| `estworksheet_create_for_job` | `form.save(commit=False)` + `.save()` | EstWorksheet | Creates worksheet |
| `task_add_from_template` | `.create()` | Task | Creates task from template |
| `task_add_manual` | `form.save()` | Task | Creates task manually |
| `estimate_add_line_item` | `.save()` or `.create()` | EstimateLineItem | Adds line item (manual or from PLI) |
| `estimate_update_status` | `.save()` | Estimate | Status transition |
| `estimate_create_for_job` | `.create()` | Estimate | Creates blank estimate |
| `estimate_revise` | `.create()` | Estimate | Creates revision |
| `estimate_revise` | `.create()` (loop) | EstimateLineItem | Copies line items |
| `estimate_revise` | `.save()` | Estimate | Marks parent superseded |
| `task_reorder_worksheet` | `.save()` x2 | Task | Swaps sort_order |
| `template_reorder_item` | `.save()` x2 | TemplateTaskAssociation/TemplateBundle | Swaps sort_order |
| `template_reorder_in_bundle` | `.save()` x2 | TemplateTaskAssociation | Swaps sort_order in bundle |
| `worksheet_reorder_item` | `.save()` x2 | Task/TaskBundle | Swaps sort_order |
| `worksheet_reorder_in_bundle` | `.save()` x2 | Task | Swaps sort_order in bundle |
| `work_order_create_from_estimate` | `.create()` | WorkOrder | Creates work order |

### contacts/views.py (32 inline operations — most complex)

| View | Operation | Model | What it does |
|------|-----------|-------|-------------|
| `add_contact` | `.create()` | Contact | Creates contact |
| `confirm_create_business` | `.create()` | Business | Creates business for existing contact |
| `confirm_create_business` | `.save()` | Contact | Links contact to new business |
| `add_business_contact` | `.create()` | Contact | Creates contact for business |
| `add_business_contact` | `.save()` | Business | Sets default contact |
| `add_business` | `.create()` (multiple) | Contact, Business | Creates business with contacts |
| `edit_contact` | `.create()` | Business | Creates new business during edit |
| `edit_contact` | `.save()` | Contact | Updates contact fields |
| `set_default_contact` | `.save()` | Business | Sets default contact |
| `delete_contact` | `.save()`, `.delete()` | Business, Contact | Deletes contact, reassigns default |
| `_show_deletion_management_page` | `.delete()` | Business | Deletes unassociated business |
| `_process_business_deletion` | `.delete()`, `.update()` (many) | PO, Bill, Job, Contact, Business | Cascading business deletion with reassignment |
| `edit_business` | `.save()` | Business | Updates business fields |

### purchasing/views.py (19 inline operations, 2 via service)

| View | Operation | Model | What it does |
|------|-----------|-------|-------------|
| `purchase_order_detail` | `.save()` | PurchaseOrder | Status transition |
| `purchase_order_create` | `form.save()` | PurchaseOrder | Creates PO |
| `purchase_order_create_for_job` | `form.save()` | PurchaseOrder | Creates PO for job |
| `purchase_order_add_line_item` | `.save()` or `.create()` | POLineItem | Adds line item |
| `bill_detail` | `.save()` | Bill | Status transition |
| `purchase_order_edit` | `form.save()` | PurchaseOrder | Updates PO |
| `purchase_order_delete` | `.delete()` | PurchaseOrder | Deletes draft PO |
| `purchase_order_cancel` | `.save()` | PurchaseOrder | Cancels PO |
| `bill_create` | `form.save()` | Bill | Creates bill |
| `bill_create_for_po` | `form.save()` | Bill | Creates bill from PO |
| `bill_create_for_po` | `.create()` (loop) | BillLineItem | Copies PO line items to bill |
| `bill_add_line_item` | `.create()` | BillLineItem | Adds line item |
| `purchase_order_reorder_line_item` | `.save()` x2 | POLineItem | Swaps line_number |
| `bill_reorder_line_item` | `.save()` x2 | BillLineItem | Swaps line_number |
| `bill_delete` | `.delete()` | Bill | Deletes draft bill |
| `purchase_order_delete_line_item` | via service | — | **Already uses LineItemService** |
| `bill_delete_line_item` | via service | — | **Already uses LineItemService** |

### invoicing/views.py (2 inline operations)

| View | Operation | Model | What it does |
|------|-----------|-------|-------------|
| `invoice_reorder_line_item` | `.save()` x2 | InvoiceLineItem | Swaps line_number |

### inventory/views.py (4 inline operations)

| View | Operation | Model | What it does |
|------|-----------|-------|-------------|
| `inventory_item_add` | `form.save()` | PriceListItem | Creates inventoried item |
| `inventory_item_edit` | `form.save()` | PriceListItem | Updates inventoried item |
| `price_list_item_add` | `form.save()` | PriceListItem | Creates PLI |
| `price_list_item_edit` | `form.save()` | PriceListItem | Updates PLI |

### core/views.py (6 inline operations)

| View | Operation | Model | What it does |
|------|-----------|-------|-------------|
| `associate_email_with_job` | `.save()` | EmailRecord | Links email to job |
| `disassociate_email_from_job` | `.save()` | EmailRecord | Unlinks email from job |
| `line_item_type_create` | `form.save()` | LineItemType | Creates line item type |
| `line_item_type_edit` | `form.save()` | LineItemType | Updates line item type |
| `tax_config_edit` | `.update_or_create()` x2 | Configuration | Updates tax settings |

---

## Service Methods Needed

All service methods accept IDs and primitives — never model instances, forms, or serializers.
Services do their own lookups internally and raise domain exceptions (`NotFoundError`, etc.).
Views extract `form.cleaned_data` or `serializer.validated_data` before calling.

### Jobs App — `apps/jobs/services.py`

New class: **`JobService`**
- `create_job(**kwargs)` — create with number generation
- `update_job(pk, **kwargs)` — field updates
- `delete_job(pk)` — delete with cascading cleanup

Extend: **`WorkOrderService`** (already exists)
- `update_status(pk, new_status)` — status transition
- `bundle_tasks(work_order_id, task_ids, bundle_name)` — validates status, delegates to BundlingService
- `unbundle_task(work_order_id, task_id)` — validates status, delegates to BundlingService
- `reorder_items(work_order_id, item_id, direction)` — validates status, delegates to BundlingService
- `reorder_in_bundle(work_order_id, task_id, direction)` — validates status, delegates to BundlingService

Extend: **`TaskService`** (already exists)
- `update_task(pk, **kwargs)` — update task fields
- `reorder_tasks(pk, direction)` — swap sort_order

### Shared Service — `apps/core/services.py` (or `apps/estimates/services.py`)

New class: **`BundlingService`**

Low-level shared service for bundling, unbundling, and reorder operations.
Works with any item model that has `mapping_strategy`, `bundle` (FK), and `sort_order`
fields, and any bundle model with `sort_order`. Domain services (WorksheetService,
WorkOrderTemplateService, WorkOrderService) call BundlingService after handling
domain-specific validation (e.g. status checks).

- `bundle_items(items, bundle, ...)` — assign items to bundle with sequential sort_order
- `unbundle_item(item)` — remove from bundle, re-insert at container level, auto-dissolve empty bundles
- `reorder_container_item(container_items, item, direction)` — swap sort_order at container level
- `reorder_in_bundle(item, direction)` — swap sort_order within bundle

This follows the same pattern as `LineItemService` — a shared low-level service
that domain services delegate to after applying their own rules.

### Estimates App — `apps/estimates/services.py`

Extend: **`EstimateService`** (already exists — merge EstimateGenerationService into this)
- `update_status(pk, new_status)` — status transition (covers accept, reject, send, etc.)
- `mark_open(pk)` — set open + update worksheet
- `revise_estimate(pk)` — create revision, copy line items, supersede parent
- `add_line_item(estimate_id, **kwargs)` — add line item (manual or from PLI)
- `generate_from_worksheet(worksheet_id)` — convert worksheet to estimate (was `EstimateGenerationService`)
- `create_from_work_order(work_order_id)` — create estimate from work order (already exists)
- `create_direct(job_id, **kwargs)` — create blank estimate (already exists)

New class: **`WorksheetService`**
- `create_worksheet(job_id, **kwargs)` — create worksheet
- `revise_worksheet(pk)` — create revision, copy tasks, supersede parent
- `prepare_for_generation(pk, task_types)` — assign line_item_types, set status final
- `bundle_tasks(worksheet_id, task_ids, bundle_name)` — validates draft status, then delegates to BundlingService
- `unbundle_task(worksheet_id, task_id)` — validates draft status, then delegates to BundlingService
- `add_task_from_template(worksheet_id, template_id)` — add task from template
- `add_task_manual(worksheet_id, **kwargs)` — add task manually
- `reorder_items(worksheet_id, item_id, direction)` — validates draft status, then delegates to BundlingService
- `reorder_in_bundle(worksheet_id, task_id, direction)` — validates draft status, then delegates to BundlingService

New class: **`WorkOrderTemplateService`**
- `create_template(**kwargs)` — create template
- `update_template(pk, **kwargs)` — update template
- `delete_template(pk)` — delete template
- `bundle_associations(template_id, assoc_ids, bundle_name)` — delegates to BundlingService (no status check)
- `unbundle_association(template_id, assoc_id)` — delegates to BundlingService
- `reorder_items(template_id, item_id, direction)` — delegates to BundlingService
- `reorder_in_bundle(template_id, assoc_id, direction)` — delegates to BundlingService
- `create_task_template(**kwargs)` — create task template
- `update_task_template(pk, **kwargs)` — update template
- `delete_task_template(pk)` — delete (with usage check)

### Contacts App — `apps/contacts/services.py` (new file)

New class: **`ContactService`**
- `create_contact(**kwargs)` — create contact
- `update_contact(pk, **kwargs)` — update contact fields
- `delete_contact(pk)` — delete with default_contact reassignment
- `create_business(contacts_data, **kwargs)` — create business with contacts
- `create_business_for_contact(contact_id, **kwargs)` — create business and link contact
- `update_business(pk, **kwargs)` — update business fields
- `set_default_contact(business_id, contact_id)` — set default contact
- `delete_business(pk, reassignment_plan)` — complex cascading deletion

### Purchasing App — `apps/purchasing/services.py` (new file)

New class: **`PurchaseOrderService`**
- `create_po(**kwargs)` — create PO
- `create_po_for_job(job_id, **kwargs)` — create PO for job
- `update_po(pk, **kwargs)` — update PO
- `update_status(pk, new_status)` — status transition
- `cancel_po(pk)` — cancel PO
- `delete_po(pk)` — delete draft PO
- `add_line_item(po_id, **kwargs)` — add line item
- Reorder: use existing `LineItemService.reorder_line_item()` from core

New class: **`BillService`**
- `create_bill(**kwargs)` — create bill
- `create_bill_from_po(po_id, **kwargs)` — create bill with PO line items copied
- `update_status(pk, new_status)` — status transition
- `delete_bill(pk)` — delete draft bill
- `add_line_item(bill_id, **kwargs)` — add line item
- Reorder: use existing `LineItemService.reorder_line_item()` from core

### Invoicing App — `apps/invoicing/services.py` (new file)

New class: **`InvoiceService`**
- `reorder_line_item(line_item_id, direction)` — delegates to `LineItemService.reorder_line_item()`
- (Invoice CRUD views don't exist yet — create, update, status transitions, add/delete line items will be added here when built)

### Inventory App — `apps/inventory/services.py` — DONE (consolidated)

Extend: **`InventoryService`** (already exists — QOH ops + earmarks)
- `create_item(**kwargs)` — create PLI ✅
- `update_item(pk, **kwargs)` — update PLI ✅
- `get_earmark_preview(job)` — preview earmarks needed for job ✅ (was EarmarkService)
- `create_earmarks_for_job(job, earmark_data)` — create/update earmarks ✅ (was EarmarkService)
- `receive_po_line_item(po_line_item)` — QOH increase on PO receipt ✅
- `consume_material(material)` — QOH decrease on task start ✅
- `manual_adjustment(price_list_item, quantity_change, reason)` — manual QOH adjust ✅

### Core App — `apps/core/services.py` — DONE

Extend: **`EmailService`** (already exists)
- `associate_with_job(email_record_id, job_id)` — link email to job ✅
- `disassociate_from_job(email_record_id)` — unlink email ✅

Extend: **`ConfigurationService`** ✅ (absorbs LineItemTypeService — line item types are configuration)
- `update_tax_config(**kwargs)` — update tax configuration values
- `create_line_item_type(**kwargs)` — create line item type
- `update_line_item_type(pk, **kwargs)` — update line item type

---

## Implementation Order

Work app-by-app, from simplest to most complex:

1. **core** — ✅ DONE — services + views + tests
2. **inventory** — services consolidated (EarmarkService merged into InventoryService, PLI CRUD added); views not yet updated
3. **invoicing** — just reorder (use existing LineItemService)
4. **purchasing** — CRUD + status transitions (19 operations)
5. **jobs** — CRUD + status + reorder (11 operations)
6. **estimates** — largest, most complex: status, revisions, bundles, templates (45+ operations)
7. **contacts** — complex cascading deletion logic (32 operations)

For each app:
1. Create/extend service class with methods
2. Update views to call service methods
3. Run tests — behavior should not change
4. Verify full test suite passes

The refactor is behavior-preserving. Every service method does exactly what the inline view code did, but in one reusable place. New side effects or transaction boundaries can be added to the service method later and both HTML and API views benefit automatically.

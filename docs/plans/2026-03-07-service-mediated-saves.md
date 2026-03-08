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
| `estimates/services.py` | `EstimateService` | `create_from_work_order`, `create_direct` |
| `estimates/services.py` | `EstimateGenerationService` | `generate_estimate_from_worksheet` |
| `jobs/services.py` | `LineItemTaskService` | `generate_tasks_for_work_order` |
| `jobs/services.py` | `WorkOrderService` | `create_from_estimate`, `create_from_template`, `create_direct` |
| `jobs/services.py` | `TaskService` | `create_from_line_item`, `create_from_template`, `create_direct`, `create_line_item_from_task` |
| `inventory/services.py` | `InventoryService` | `receive_po_line_item`, `consume_material`, `manual_adjustment` |
| `inventory/services.py` | `EarmarkService` | `get_earmark_preview`, `create_earmarks_for_job` |

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

All service methods accept model instances and plain kwargs — never forms or serializers.
Views extract `form.cleaned_data` or `serializer.validated_data` before calling.

### Jobs App — `apps/jobs/services.py`

New class: **`JobService`**
- `create_job(**kwargs)` — create with number generation
- `update_job(job, **kwargs)` — field updates
- `delete_job(job)` — delete with cascading cleanup

Extend: **`WorkOrderService`** (already exists)
- `update_status(wo, new_status)` — status transition

New class: **`MaterialService`**
- `create_material(task, **kwargs)` — create material on task
- `update_material(material, **kwargs)` — update material
- `delete_material(material)` — delete material

Extend: **`TaskService`** (already exists)
- `update_task(task, **kwargs)` — update task fields
- `reorder_tasks(task, direction)` — swap sort_order

### Estimates App — `apps/estimates/services.py`

Extend: **`EstimateService`** (already exists)
- `update_status(estimate, new_status)` — status transition (covers accept, reject, send, etc.)
- `mark_open(estimate)` — set open + update worksheet
- `revise_estimate(estimate)` — create revision, copy line items, supersede parent
- `add_line_item(estimate, **kwargs)` — add line item (manual or from PLI)

New class: **`WorksheetService`**
- `create_worksheet(job, **kwargs)` — create worksheet
- `revise_worksheet(worksheet)` — create revision, copy tasks, supersede parent
- `prepare_for_generation(worksheet, task_types)` — assign line_item_types, set status final
- `bundle_tasks(worksheet, task_ids, bundle_name)` — bundle operations
- `unbundle_task(worksheet, task)` — unbundle operations
- `add_task_from_template(worksheet, template)` — add task from template
- `add_task_manual(worksheet, **kwargs)` — add task manually
- `reorder_items(container, item_id, direction)` — reorder tasks/bundles
- `reorder_in_bundle(bundle, task_id, direction)` — reorder within bundle

New class: **`WorkOrderTemplateService`**
- `create_template(**kwargs)` — create template
- `update_template(template, **kwargs)` — update template
- `delete_template(template)` — delete template
- `bundle_associations(template, assoc_ids, bundle)` — bundle operations
- `unbundle_association(assoc)` — unbundle operations
- `reorder_items(template, item_id, direction)` — reorder
- `reorder_in_bundle(bundle, assoc_id, direction)` — reorder within bundle

New class: **`TaskTemplateService`**
- `create_template(**kwargs)` — create task template
- `update_template(template, **kwargs)` — update template
- `delete_template(template)` — delete (with usage check)

### Contacts App — `apps/contacts/services.py` (new file)

New class: **`ContactService`**
- `create_contact(**kwargs)` — create contact
- `update_contact(contact, **kwargs)` — update contact fields
- `delete_contact(contact)` — delete with default_contact reassignment

New class: **`BusinessService`**
- `create_business(contacts_data, **kwargs)` — create business with contacts
- `create_business_for_contact(contact, **kwargs)` — create business and link contact
- `update_business(business, **kwargs)` — update business fields
- `set_default_contact(business, contact)` — set default contact
- `delete_business(business, reassignment_plan)` — complex cascading deletion

### Purchasing App — `apps/purchasing/services.py` (new file)

New class: **`PurchaseOrderService`**
- `create_po(**kwargs)` — create PO
- `create_po_for_job(job, **kwargs)` — create PO for job
- `update_po(po, **kwargs)` — update PO
- `update_status(po, new_status)` — status transition
- `cancel_po(po)` — cancel PO
- `delete_po(po)` — delete draft PO
- `add_line_item(po, **kwargs)` — add line item
- `reorder_line_items(line_item, direction)` — swap line_number

New class: **`BillService`**
- `create_bill(**kwargs)` — create bill
- `create_bill_from_po(po, **kwargs)` — create bill with PO line items copied
- `update_status(bill, new_status)` — status transition
- `delete_bill(bill)` — delete draft bill
- `add_line_item(bill, **kwargs)` — add line item
- `reorder_line_items(line_item, direction)` — swap line_number

### Invoicing App — `apps/invoicing/services.py` (new file)

New class: **`InvoiceService`**
- `reorder_line_items(line_item, direction)` — swap line_number

### Inventory App — `apps/inventory/services.py` (extend)

New class: **`PriceListItemService`**
- `create_item(**kwargs)` — create PLI
- `update_item(pli, **kwargs)` — update PLI

### Core App — `apps/core/services.py` (extend)

Extend: **`EmailService`** (already exists)
- `associate_with_job(email_record, job)` — link email to job (method exists but view doesn't use it)
- `disassociate_from_job(email_record)` — unlink email

New class: **`ConfigurationService`**
- `update_tax_config(**kwargs)` — update tax configuration values

New class: **`LineItemTypeService`**
- `create_type(**kwargs)` — create line item type
- `update_type(lit, **kwargs)` — update line item type

---

## Implementation Order

Work app-by-app, from simplest to most complex:

1. **core** — small, simple form saves + config updates (6 operations)
2. **inventory** — simple form saves (4 operations)
3. **invoicing** — just reorder (2 operations)
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

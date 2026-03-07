# Service-Mediated Saves Refactor

**Date:** 2026-03-07
**Status:** Approved
**Scope:** Refactor HTML views to route all writes through service methods
**Do before:** API implementation

---

## Overview

Currently, some HTML views update models inline:

```python
# Typical inline save in a view
estimate.status = Estimate.STATUS_ACCEPTED
estimate.save()
```

This works today but creates a problem: side effects (signals, related model updates, transaction wrapping) can be bypassed or duplicated. When the API layer is added, both the HTML view and the API view would need identical save logic — or one would miss a side effect.

**Solution:** Every model write goes through a service method. Views (HTML and API) call services, never save models directly.

---

## Current State

### Already Using Services

These operations are already service-mediated:

- `EstimateGenerationService.generate_estimate_from_worksheet()` — worksheet to estimate conversion
- `WorkOrderService.create_from_estimate()` — work order creation
- `LineItemService.delete_line_item_with_renumber()` — line item deletion
- `LineItemService.reorder_line_items()` — line item reordering
- `NumberGenerationService.generate_next_number()` — document numbering
- `TaxCalculationService` — tax computation
- `EmailService` — email operations
- `InventoryService` / `EarmarkService` — inventory tracking

### Doing Inline Saves (Need Refactoring)

These patterns in views need to be replaced with service calls:

- **Status transitions** — views set `model.status` and call `save()` directly
- **Simple field updates** — views update fields from form data and save
- **Object creation** — views create models directly from form data
- **Object deletion** — some views call `delete()` directly (others correctly iterate)

---

## Target Pattern

### Before (inline in view)

```python
def estimate_accept(request, estimate_id):
    estimate = get_object_or_404(Estimate, pk=estimate_id)
    estimate.status = Estimate.STATUS_ACCEPTED
    estimate.accepted_date = date.today()
    estimate.save()
    # Side effect: update job status
    estimate.job.status = Job.STATUS_APPROVED
    estimate.job.save()
    messages.success(request, "Estimate accepted.")
    return redirect(...)
```

### After (service-mediated)

```python
# In the view
def estimate_accept(request, estimate_id):
    estimate = get_object_or_404(Estimate, pk=estimate_id)
    EstimateService.accept_estimate(estimate)
    messages.success(request, "Estimate accepted.")
    return redirect(...)

# In the service
class EstimateService:
    @staticmethod
    def accept_estimate(estimate):
        with transaction.atomic():
            estimate.status = Estimate.STATUS_ACCEPTED
            estimate.accepted_date = date.today()
            estimate.full_clean()
            estimate.save()
            estimate.job.status = Job.STATUS_APPROVED
            estimate.job.full_clean()
            estimate.job.save()
```

The API view then calls the same service:

```python
# API viewset action
def accept(self, request, pk=None):
    estimate = self.get_object()
    EstimateService.accept_estimate(estimate)
    return Response(self.get_serializer(estimate).data)
```

---

## Service Methods Needed

This is a preliminary inventory. The exact list should be determined by auditing each view for inline saves.

### Jobs

- `JobService.create_job(data)` — create with number generation
- `JobService.update_job(job, data)` — field updates
- `JobService.complete_job(job)`
- `JobService.cancel_job(job, reason)`
- `JobService.reopen_job(job, reason)`
- `JobService.delete_job(job)`

### Estimates

- `EstimateService.create_estimate(data)`
- `EstimateService.update_estimate(estimate, data)`
- `EstimateService.send_estimate(estimate)`
- `EstimateService.accept_estimate(estimate)`
- `EstimateService.reject_estimate(estimate)`
- `EstimateService.revise_estimate(estimate)`
- `EstimateService.expire_estimate(estimate, reason)`
- `EstimateService.cancel_estimate(estimate, reason)`
- `EstimateService.delete_estimate(estimate)`

### EstWorksheets

- `WorksheetService.create_worksheet(data)`
- `WorksheetService.update_worksheet(worksheet, data)`
- `WorksheetService.revise_worksheet(worksheet)`
- `WorksheetService.delete_worksheet(worksheet)`
- Task and bundle operations (some already exist)

### Work Orders

- `WorkOrderService.update_work_order(wo, data)`
- `WorkOrderService.complete_work_order(wo)`
- `WorkOrderService.block_work_order(wo, reason)`
- `WorkOrderService.cancel_work_order(wo, reason)`
- `WorkOrderService.reopen_work_order(wo, reason)`
- `WorkOrderService.delete_work_order(wo)`

### Contacts & Businesses

- `ContactService.create_contact(data)`
- `ContactService.update_contact(contact, data)`
- `ContactService.delete_contact(contact)`
- `BusinessService.create_business(data)`
- `BusinessService.update_business(business, data)`
- `BusinessService.set_default_contact(business, contact)`
- `BusinessService.delete_business(business)`

### Invoicing

- `InvoiceService.create_invoice(data)`
- `InvoiceService.update_invoice(invoice, data)`
- `InvoiceService.send_invoice(invoice)`
- `InvoiceService.record_payment(invoice, amount, date)`
- `InvoiceService.cancel_invoice(invoice, reason)`
- `InvoiceService.supersede_invoice(invoice, reason)`
- `InvoiceService.delete_invoice(invoice)`

### Purchasing

- `PurchaseOrderService.create_po(data)`
- `PurchaseOrderService.update_po(po, data)`
- `PurchaseOrderService.issue_po(po)`
- `PurchaseOrderService.receive_po(po, line_quantities)`
- `PurchaseOrderService.cancel_po(po, reason)`
- `PurchaseOrderService.delete_po(po)`
- `BillService.create_bill(data)`
- `BillService.update_bill(bill, data)`
- `BillService.receive_bill(bill)`
- `BillService.record_payment(bill, amount, date)`
- `BillService.cancel_bill(bill, reason)`
- `BillService.refund_bill(bill, reason)`
- `BillService.delete_bill(bill)`

### Line Items (already partially exists)

- `LineItemService.add_line_item(parent, data)` — new
- `LineItemService.update_line_item(line_item, data)` — new
- `LineItemService.delete_line_item_with_renumber(line_item)` — exists
- `LineItemService.reorder_line_items(parent, ordered_ids)` — exists

### Templates & Configuration

- Service methods for template CRUD and configuration updates as needed

---

## Implementation Approach

1. **Audit views** — go through each view file, identify every inline save/create/delete
2. **Create service methods** — one app at a time, starting with the most critical (jobs/estimates)
3. **Update HTML views** — replace inline saves with service calls
4. **Test** — existing tests should continue to pass since behavior doesn't change
5. **Verify** — run full test suite after each app is refactored

The refactor is behavior-preserving. Every service method does exactly what the inline view code did, but in one reusable place. New side effects or transaction boundaries can be added to the service method later and both HTML and API views benefit automatically.

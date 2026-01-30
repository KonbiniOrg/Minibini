# Code Review Findings Report

**Date:** December 19, 2025
**Reviewed By:** Automated Code Review
**Scope:** Full codebase review of existing functionality

---

## Executive Summary

This document presents findings from a comprehensive code review of the Minibini Django application. The application is a job management and invoicing system with modules for contacts, jobs, estimates, worksheets, invoicing, and purchasing.

**Note:** This review focuses on bugs and issues in **existing functionality**. Authentication, authorization, and credential management are intentionally simplified for development and will be addressed later.

| Severity | Count | Fixed | Key Areas |
|----------|-------|-------|-----------|
| CRITICAL | 1 | 1 ✅ | Data Integrity |
| IMPORTANT | 13 | 10 ✅ | Logic Bugs, Validation, Performance, Data Integrity |
| MINOR | 6 | 0 | Code Style, Incomplete Features |

---

## CRITICAL Issues (Must Fix)

### 1. Contact Deletion Bypasses Model Validation

**Status:** ✅ FIXED

**Files:** `apps/contacts/views.py` (lines 659-666), `apps/contacts/models.py` (lines 66-92)

**Original Issue:** Using `QuerySet.delete()` bypassed the `Contact.delete()` override that validates business default contact logic.

**Fixes Applied:**

1. **View fix** - `delete_business` now uses individual `contact.delete()` calls:
```python
# Delete contacts individually to trigger model validation logic
for contact_id in contact_ids:
    try:
        contact = Contact.objects.get(contact_id=contact_id)
        contact.delete()
    except Contact.DoesNotExist:
        pass
```

2. **Model fix** - `Contact.delete()` now prevents deletion of sole contacts and auto-reassigns default_contact:
```python
def delete(self, *args, **kwargs):
    business = self.business
    if business and business.default_contact == self:
        other_contacts = business.contacts.exclude(pk=self.pk)
        if not other_contacts.exists():
            raise PermissionDenied(
                f'Cannot delete the only contact for business "{business}". '
                'Delete the business or add another contact as the default first.'
            )
        # Reassign default_contact to another contact before deleting
        business.default_contact = other_contacts.first()
        business.save(update_fields=['default_contact'])
    super().delete(*args, **kwargs)
    if business:
        business.validate_and_fix_default_contact()
```

---

## IMPORTANT Issues (Should Fix Before Production)

### 2. Invoice Default Status Mismatch

**Status:** ✅ FIXED

**File:** `apps/invoicing/models.py`, line 21

**Original Issue:** Default value `'active'` was not in `INVOICE_STATUS_CHOICES`.

**Fix Applied:** Changed default to `'draft'`:
```python
status = models.CharField(max_length=20, choices=INVOICE_STATUS_CHOICES, default='draft')
```

---

### 3. Race Condition in Business Reference Code Generation

**Status:** ✅ FIXED

**File:** `apps/contacts/models.py`, lines 129-165

**Original Issue:** Loop-based uniqueness check was not atomic, allowing race conditions.

**Fix Applied:** Added IntegrityError retry logic with transaction.atomic():
```python
def save(self, *args, **kwargs):
    from django.db import IntegrityError, transaction

    if self.our_reference_code:
        super().save(*args, **kwargs)
        return

    max_attempts = 10
    for attempt in range(max_attempts):
        # Generate code...
        try:
            with transaction.atomic():
                super().save(*args, **kwargs)
            return
        except IntegrityError as e:
            if 'our_reference_code' in str(e) and attempt < max_attempts - 1:
                continue
            raise
    raise ValueError("Could not generate unique reference code")
```

---

### 4. estimate_revise Sets Non-Existent Field

**Status:** ✅ FIXED

**File:** `apps/jobs/views.py`

**Original Issue:** Code referenced `superseded_date` field which was renamed to `closed_date`.

**Fix Applied:** Removed the manual date setting - the model's `save()` method auto-sets `closed_date`:
```python
parent_estimate.status = 'superseded'
# closed_date is automatically set by the model's save() method
parent_estimate.save()
```

---

### 5. PurchaseOrder Form Regenerates PO Number on Edit

**Status:** ✅ FIXED

**File:** `apps/purchasing/forms.py`, lines 62-72

**Original Issue:** Form regenerated PO number on every save, even when editing.

**Fix Applied:** Only generate PO number for new instances:
```python
def save(self, commit=True):
    instance = super().save(commit=False)
    if not instance.pk:  # Only generate for new instances
        instance.po_number = NumberGenerationService.generate_next_number('po')
    if commit:
        instance.save()
    return instance
```

---

### 6. Missing Transaction Wrapping on Multi-Model Operations

**Status:** ✅ FIXED

**File:** `apps/contacts/views.py`

**Original Issue:** Multi-model operations weren't wrapped in transactions, risking orphaned data.

**Fixes Applied:**
1. `add_contact`: Added `transaction.atomic()` wrapper, fixed order to create Contact first, then Business with `default_contact` set
2. `add_business`: Added `transaction.atomic()` wrapper around all contact/business creation

```python
with transaction.atomic():
    contact = Contact.objects.create(...)  # Create contact first
    business = Business.objects.create(..., default_contact=contact)
    contact.business = business
    contact.save()
```

---

### 7. Model clean() Method Not Called on ORM Create

**File:** `apps/contacts/views.py`, multiple locations

**Description:** `Contact.objects.create()` does not call `full_clean()` by default, so the model-level validation in `Contact.clean()` (requiring email and at least one phone number) is bypassed.

**Impact:** Contacts can be created without email or phone numbers through direct ORM usage, bypassing the validation that the view manually implements.

**Recommended Fix:** Override `Contact.save()` to call `full_clean()`:
```python
def save(self, *args, **kwargs):
    self.full_clean()  # Add this line
    # ... rest of save method
    super().save(*args, **kwargs)
```

---

### 8. N+1 Query Problem in delete_business View

**Status:** ✅ FIXED

**File:** `apps/contacts/views.py`, lines 592-626

**Original Issue:** For each contact, 2-4 database queries were made, causing performance issues.

**Fix Applied:** Replaced per-contact queries with bulk queries using `defaultdict`:
```python
contact_ids = list(contacts.values_list('contact_id', flat=True))

# Single query for jobs
jobs_by_contact = defaultdict(list)
for item in Job.objects.filter(contact_id__in=contact_ids).values('contact_id', 'job_number'):
    jobs_by_contact[item['contact_id']].append(item['job_number'])

# Single query for bills
bills_by_contact = defaultdict(list)
for item in Bill.objects.filter(contact_id__in=contact_ids).values('contact_id', 'bill_id'):
    bills_by_contact[item['contact_id']].append(str(item['bill_id']))

# Then check each contact using the dictionaries
```

---

### 9. State-Changing Operations on GET Requests

**Status:** ✅ FIXED

**Files:** `apps/jobs/views.py` (lines 886, 926, 961), `apps/invoicing/views.py` (line 72), `apps/purchasing/views.py` (lines 309, 349)

**Description:** Reordering operations modify database state but are triggered via GET requests:
```python
def task_reorder_worksheet(request, worksheet_id, task_id, direction):
    # No POST check, but modifies data
    current_task.save()
    swap_task.save()
```

**Impact:** GET requests should be idempotent. While CSRF middleware provides some protection, these could still be triggered unintentionally by browser prefetching, crawlers, or link previews.

**Recommended Fix:** This requires changes to both views AND templates.

**Step 1: Add POST requirement to views:**
```python
# apps/jobs/views.py
from django.views.decorators.http import require_POST

@require_POST
def task_reorder_worksheet(request, worksheet_id, task_id, direction):
    # ... existing logic unchanged ...

@require_POST
def task_reorder_work_order(request, work_order_id, task_id, direction):
    # ... existing logic unchanged ...

@require_POST
def estimate_reorder_line_item(request, estimate_id, line_item_id, direction):
    # ... existing logic unchanged ...

# apps/invoicing/views.py
@require_POST
def invoice_reorder_line_item(request, invoice_id, line_item_id, direction):
    # ... existing logic unchanged ...

# apps/purchasing/views.py
@require_POST
def purchase_order_reorder_line_item(request, po_id, line_item_id, direction):
    # ... existing logic unchanged ...

@require_POST
def bill_reorder_line_item(request, bill_id, line_item_id, direction):
    # ... existing logic unchanged ...
```

**Step 2: Update templates to use form submissions instead of links:**

Current (GET links):
```html
<!-- templates/includes/_line_items_table.html -->
<a href="{% url reorder_url_name parent_id item.line_item_id 'up' %}">↑</a>
<a href="{% url reorder_url_name parent_id item.line_item_id 'down' %}">↓</a>
```

Updated (POST forms):
```html
<!-- templates/includes/_line_items_table.html -->
<form method="post" action="{% url reorder_url_name parent_id item.line_item_id 'up' %}" style="display:inline;">
    {% csrf_token %}
    <button type="submit" class="btn btn-sm btn-link" title="Move up">↑</button>
</form>
<form method="post" action="{% url reorder_url_name parent_id item.line_item_id 'down' %}" style="display:inline;">
    {% csrf_token %}
    <button type="submit" class="btn btn-sm btn-link" title="Move down">↓</button>
</form>
```

Same pattern applies to `templates/jobs/_task_list.html`.

**Fixes Applied:**
1. Added `@require_POST` decorator to all 6 reorder views
2. Updated imports in `jobs/views.py`, `invoicing/views.py`, and `purchasing/views.py`
3. GET requests now return 405 Method Not Allowed
4. Updated `templates/includes/_line_items_table.html` to use POST forms
5. Updated `templates/jobs/_task_list.html` to use POST forms

---

### 10. Inconsistent Validation Between Forms and Models

**File:** `apps/jobs/forms.py`, lines 296-322 vs `apps/jobs/models.py`, lines 134-142

**Description:** `EstimateStatusForm.VALID_TRANSITIONS` duplicates the transition logic from `Estimate.clean()`. Same issue exists for `WorkOrderStatusForm`, `PurchaseOrderStatusForm`, and `BillStatusForm`.

**Impact:** If transition rules change in the model, the form may not be updated (or vice versa), leading to inconsistent behavior.

**Recommended Fix:** Single source of truth - define transitions on the model and reference from forms:
```python
# In models.py
class Estimate(models.Model):
    VALID_TRANSITIONS = {
        'draft': ['open', 'rejected'],
        'open': ['accepted', 'superseded', 'rejected', 'expired'],
        # ...
    }

# In forms.py
class EstimateStatusForm(forms.Form):
    def __init__(self, *args, **kwargs):
        current_status = kwargs.pop('current_status', 'draft')
        super().__init__(*args, **kwargs)
        valid_statuses = Estimate.VALID_TRANSITIONS.get(current_status, [])
        # ...
```

---

### 11. Line Number Stored as String Instead of Integer

**Status:** ✅ FIXED

**File:** `apps/jobs/services.py`

**Original Issue:** `str(self.line_number)` was converting integers to strings unnecessarily.

**Fix Applied:** Removed `str()` wrapper, passing integer directly:
```python
line_number=self.line_number,  # No string conversion
```

---

### 12. Views Duplicate Validation Logic Already in Models

**File:** `apps/contacts/views.py`, lines 43-52, 106-115, 183-192, 276-292

**Description:** Views manually validate email and phone requirements:
```python
# View validation
if not email or not email.strip():
    messages.error(request, 'Email address is required.')
    return render(request, 'contacts/add_contact.html')

if not any([work_number, mobile_number, home_number]):
    messages.error(request, 'At least one phone number...')
```

This duplicates `Contact.clean()` logic.

**Impact:** Validation logic must be maintained in two places. If model validation changes, views may not be updated.

**Recommended Fix:** Use Django ModelForms which automatically call model validation:
```python
class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ['first_name', 'last_name', 'email', ...]
```

---

### 13. Business Deletion Can Leave Default Contact Reference Invalid

**Status:** ✅ FIXED

**File:** `apps/contacts/views.py`, lines 643-648

**Original Issue:** `contacts.update(business=None)` used a bulk update that bypassed `Contact.save()`.

**Fix Applied:** Now uses individual `contact.save()` calls to trigger model validation:
```python
if contact_action == 'unlink':
    # Unlink contacts from business individually to trigger model validation
    for contact in contacts:
        contact.business = None
        contact.save()
    business.delete()
```

---

### 14. delete_contact Uses Wrong Status Values

**Status:** ✅ FIXED

**File:** `apps/contacts/views.py`

**Original Issue:** Used `'complete'` instead of `'completed'` in status filter.

**Fix Applied:** Corrected status values:
```python
).exclude(
    status__in=['completed', 'rejected', 'cancelled']
)
```

---

## MINOR Issues (Nice to Fix)

### 15. Inconsistent Error Message Formatting

**Files:** Various views

**Description:** Some error messages use f-strings with quotes around names, others don't. Some end with periods, others don't.

**Recommended Fix:** Establish a style guide for error messages and apply consistently.

---

### 16. Misplaced Import in jobs/models.py

**File:** `apps/jobs/models.py`, line 502

**Description:**
```python
from apps.core.models import BaseLineItem
```
This import appears mid-file instead of at the top with other imports.

**Recommended Fix:** Move import to top of file. This appears to be a circular import workaround - consider restructuring if possible.

---

### 17. PaymentTerms Model is Incomplete

**File:** `apps/contacts/models.py`, lines 181-186

**Description:**
```python
class PaymentTerms(models.Model):
    term_id = models.AutoField(primary_key=True)
    # Additional fields not visible in diagram
```

**Impact:** The model has no meaningful fields beyond the primary key. It's referenced by `Business.terms` but is currently unusable.

**Recommended Fix:** Either complete the model with necessary fields (days_until_due, discount_percentage, etc.) or remove the foreign key reference until needed.

---

### 18. Magic Strings for Status Values

**Files:** Various models and views

**Description:** Status values like `'draft'`, `'open'`, `'accepted'` are repeated as string literals throughout the codebase.

**Recommended Fix:** Use constants:
```python
class EstimateStatus:
    DRAFT = 'draft'
    OPEN = 'open'
    ACCEPTED = 'accepted'
    REJECTED = 'rejected'
    EXPIRED = 'expired'
    SUPERSEDED = 'superseded'
```

---

### 19. Decimal Field Precision for Financial Data

**File:** `apps/core/models.py`, line 60

**Description:**
```python
price_currency = models.DecimalField(max_digits=10, decimal_places=2)
```

**Impact:** 2 decimal places is standard for display but may cause rounding errors in intermediate calculations.

**Recommended Fix:** Consider 4 decimal places for storage, rounding on display:
```python
price_currency = models.DecimalField(max_digits=12, decimal_places=4)
```

---

### 20. Unused template Field in EstWorksheet

**File:** `apps/jobs/models.py`

**Description:** `EstWorksheet` inherits `template` from `AbstractWorkContainer` but the field is optional and the relationship to templates is managed through the workflow rather than direct assignment.

**Recommended Fix:** Review whether this field is needed or if the template relationship should be restructured.

---

## Priority Recommendations

### Immediate Priority (Blocks Testing)
1. **Fix Invoice default status** (`'active'` -> `'draft'`) - Will cause errors on invoice creation
2. **Fix estimate_revise `superseded_date` error** - Will crash when revising estimates
3. **Fix delete_contact status check** (`'complete'` -> `'completed'`) - Wrong filter logic

### Short-term Priority (Before Integration Testing)
1. ~~Fix Contact deletion bypassing model validation (Critical #1)~~ ✅ FIXED
2. Fix PurchaseOrder number regeneration on edit
3. Wrap multi-model operations in transactions
4. Fix line_number string/integer type mismatch

### Medium-term Priority (Before Production)
1. Consolidate validation between forms and models
2. Optimize N+1 queries
3. Require POST for state-changing operations (see Issue #9 for complete fix)
4. Add model-level validation enforcement in `save()`

---

## Appendix: Files Reviewed

| App | Files |
|-----|-------|
| contacts | `models.py`, `views.py` |
| core | `models.py`, `services.py`, `middleware.py` |
| jobs | `models.py`, `views.py`, `forms.py`, `services.py` |
| invoicing | `models.py`, `views.py` |
| purchasing | `models.py`, `views.py`, `forms.py` |
| search | `views.py` |
| minibini | `settings.py` |

---

## Notes

Items intentionally excluded from this review (to be addressed in future development phase):
- Authentication and authorization implementation
- Environment-based configuration management
- Secret key externalization
- AutoLoginMiddleware (intentional dev convenience)

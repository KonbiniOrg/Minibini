# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Minibini is a Django-based job shop management system for handling jobs, estimates, work orders, invoicing, and purchasing. Pre-production state, rapidly evolving.

**Tech Stack:** Django 5.2+, MySQL, Python 3.12, plain semantic HTML (no CSS frameworks/JS)

## Essential Commands

```bash
# Development
python manage.py runserver              # Start dev server (auto-logs in dev_user)

# Database
python manage.py makemigrations         # Create migrations (OK to run)
python manage.py loaddata unit_test_data.json  # Load test fixtures

# Testing
python manage.py test                   # Run all tests
python manage.py test tests.test_foo    # Run specific test module

# Docker
docker compose up                       # Full stack (app, mysql, nginx)
```

**CRITICAL:** NEVER run `python manage.py migrate` - only the human user applies migrations to the development database. Creating migrations with `makemigrations` is fine; tests create their own test database automatically.

## Architecture

```
Minibini/
├── apps/
│   ├── core/       # User model, Configuration, BaseLineItem, LineItemType, Email
│   ├── jobs/       # Job, Estimate, EstWorksheet, WorkOrder, Task, Templates (largest app)
│   ├── contacts/   # Contact, Business, PaymentTerms
│   ├── invoicing/  # Invoice, InvoiceLineItem, PriceListItem
│   └── purchasing/ # PurchaseOrder, Bill, line items
├── templates/      # HTML templates
├── fixtures/       # Test data fixtures (JSON)
├── tests/          # Test suite
├── minibini/       # Project configuration (settings, urls)
└── manage.py
```

**Key Patterns:**
- Function-based views only (no CBVs)
- Service classes in `apps/*/services.py` contain business logic
- Signals in `apps/jobs/signals.py` handle status change side effects
- Abstract `BaseLineItem` shared by all line item types
- Template system: `WorkOrderTemplate` → `TaskTemplate` → `TaskMapping` → `ProductBundlingRule`

**Workflow:** Job → EstWorksheet (from template) → Estimate → WorkOrder → Invoice

## Key Models

### Core (`apps.core`)
- **User** - Custom AbstractUser, links to Contact
- **Configuration** - Key-value store for system settings (document numbering sequences/counters, email settings). **Never add fields** - all settings are key-value pairs
- **EmailRecord** - Permanent record linking emails to jobs (message_id only, email server is source of truth)
- **TempEmail** - Temporary cache of email metadata from IMAP (OneToOne with EmailRecord, cleaned up after retention period)
- **BaseLineItem** (Abstract) - Shared fields for all line items: task, price_list_item, line_number, qty, units, description, price_currency. Validates items can't have both task AND price_list_item

### Jobs (`apps.jobs`)
- **Job** - Central entity. Status: draft → approved/rejected → needs_attention/blocked → complete
- **Estimate** - Quotes with versioning. Status: draft → open → accepted/rejected/superseded
- **EstWorksheet** - Working document for estimates. Status: draft → final → superseded
- **WorkOrder** - Actual work. Status: draft → incomplete/blocked → complete
- **Task** - Work items belonging to either EstWorksheet OR WorkOrder (not both). Hierarchical with parent_task
- **Blep** - Time tracking (start/end times for task work)
- **EstimateLineItem** - Line items for estimates (inherits BaseLineItem)
- **Template System** - WorkOrderTemplate, TaskTemplate, TaskMapping, TemplateTaskAssociation, ProductBundlingRule

### Contacts (`apps.contacts`)
- **Contact** - Individual person with multiple phone numbers, address, linked to Business
- **Business** - Company with tax info, payment terms, internal reference code
- **PaymentTerms** - Payment conditions

### Invoicing (`apps.invoicing`)
- **Invoice** - Bills for completed work, linked to Job. Status: active/cancelled
- **InvoiceLineItem** - Inherits BaseLineItem
- **PriceListItem** - Catalog items with purchase/selling prices, inventory tracking

### Purchasing (`apps.purchasing`)
- **PurchaseOrder** - Orders to vendors, optionally linked to Job
- **Bill** - Vendor invoices, linked to PurchaseOrder and Contact
- **PurchaseOrderLineItem & BillLineItem** - Inherit BaseLineItem

## Configuration Model

Key-value store accessed via:
```python
from apps.core.models import Configuration

# Read
config = Configuration.objects.get(key='email_retention_days')
value = config.value  # always a string

# Create/update
Configuration.objects.update_or_create(key='your_key', defaults={'value': 'val'})
```

**Current keys:** `job_number_sequence`, `job_counter`, `estimate_number_sequence`, `estimate_counter`, `invoice_number_sequence`, `invoice_counter`, `po_number_sequence`, `po_counter`, `email_retention_days`, `latest_email_date`, `email_display_limit`

When adding new keys, also add to test setUp() methods and fixture files.

## Document Numbering (NumberGenerationService)

```python
from apps.core.services import NumberGenerationService
job_number = NumberGenerationService.generate_next_number('job')  # "JOB-2025-0001"
```

Pattern placeholders: `{year}`, `{month:02d}`, `{day:02d}`, `{counter:04d}`. Uses `select_for_update()` for thread safety. Patterns and counters stored in Configuration.

## URL Structure

- `/` - Home | `/admin/` - Django admin | `/settings/` - Settings
- `/jobs/` - Jobs (list, create, detail, estimates, worksheets, templates, task-templates, work_orders)
- `/contacts/` - Contacts (add, confirm-create-business)
- `/core/` - Core (inbox, email detail, create-job-from-email)
- `/purchasing/` - Purchasing | `/invoicing/` - Invoicing

## Template/HTML Conventions

- **No CSS frameworks, no JavaScript** (except datetime-local inputs)
- **Semantic HTML only:** `<p>`, `<strong>`, `<fieldset>`, `<table border="1">`
- **Django messages:** Use `messages.success()`/`error()` in views; NEVER duplicate message display in templates (base.html handles it)
- **Form pattern:** `<p><label><strong>Label</strong></label><br><input></p>`
- **Buttons:** Plain `<button>`, simple `<a>` links (no styling)
- **No inline styles** except for critical readability (e.g., borders on email content)

**Correct template pattern:**
```html
{% extends 'base.html' %}
{% block content %}
<h2>Title</h2>
<form method="post">
    {% csrf_token %}
    <p><label for="name"><strong>Name *</strong></label><br>
        <input type="text" id="name" name="name" required></p>
    <fieldset>
        <legend><strong>Optional Group</strong></legend>
        <p><label for="field"><strong>Field</strong></label><br>
            <select id="field" name="field"><option value="">-- None --</option></select></p>
    </fieldset>
    <p><button type="submit">Save</button> <a href="{% url 'list' %}">Cancel</a></p>
</form>
{% endblock %}
```

**Anti-patterns:** Inline styled divs, styled buttons, links styled as buttons, duplicate message handling blocks.

## Code Conventions

**Status Constants:** Always use model constants, not string literals:
```python
Job.objects.exclude(status__in=[Job.STATUS_COMPLETED, Job.STATUS_REJECTED])
```

**Document Numbers:** Only generate for NEW instances:
```python
if not instance.pk:
    instance.po_number = generate_next_number('po')
```

**Deletion:** Custom `delete()` methods exist - iterate instead of `QuerySet.delete()`:
```python
for contact in Contact.objects.filter(...):
    contact.delete()
```

**Transactions:** Wrap multi-model operations:
```python
with transaction.atomic():
    business = Business.objects.create(...)
    contact = Contact.objects.create(business=business, ...)
```

**Types:** Pass correct types to model fields (don't wrap numbers in `str()`).

**Field renames:** After migration renames, grep entire codebase for old field name. Python silently allows setting arbitrary attributes on model instances.

## Business Workflows

### Job Creation Flow
Job → EstWorksheet (optionally from template) → Tasks → Estimate → WorkOrder → Time tracking (Bleps) → Invoice

### Email-to-Job Workflow
1. Fetch emails from IMAP → EmailRecord + TempEmail
2. Parse sender, extract company from signature
3. If contact exists → redirect to job creation with contact pre-selected
4. If not → session-based flow: create contact → optionally create/associate business (4 scenarios via dropdown) → create job → link EmailRecord to job

Key files: `apps/core/services.py` (EmailService), `apps/core/email_utils.py`, `apps/core/views.py`, `apps/contacts/views.py`, `apps/jobs/views.py`

### Revision Workflow
Estimates/worksheets support versioning via parent-child relationships. Old versions marked superseded.

## Testing

**Use Test-Driven Development (TDD) for all code work:**
1. Write failing tests first
2. Verify tests fail for the expected reason
3. Write minimal code to make tests pass
4. Refactor while keeping tests green

- Tests in `/tests/` directory using Django TestCase
- Fixtures in `/fixtures/` (JSON format)
- Base test classes: `BaseTestCase`, `FixtureTestCase` in `tests/base.py`

## Development Features

- **AutoLoginMiddleware** (`apps.core.middleware`) - Auto-logs in dev_user, remove for production
- **Management commands** - `populate_data.py` (base), `populate_contact_data.py`, `populate_job_data.py`

## Common Coding Pitfalls

1. **Old field names after renames** - Python silently sets arbitrary attributes; data never saved
2. **Status value typos** - Use model constants (`Job.STATUS_COMPLETED`), not strings
3. **Defaults not in choices** - Always use a value from the choices list
4. **Number regeneration on edit** - Guard with `if not instance.pk:`
5. **QuerySet.delete() bypasses Model.delete()** - Iterate and call delete() individually
6. **Missing transaction wrapping** - Multi-model ops need `transaction.atomic()`
7. **Type coercion** - Pass correct types to ORM fields

### Code Review Checklist
- [ ] Status values match model choice definitions
- [ ] Default values are in the choices list
- [ ] Document numbers only generated for new instances
- [ ] Field names match current model (no old renamed fields)
- [ ] Integer fields receive integers, not strings
- [ ] Custom delete() methods are respected (no QuerySet.delete())
- [ ] Multi-model operations are wrapped in transactions

## Key File Locations

- Models: `apps/*/models.py` | Views: `apps/*/views.py` | URLs: `apps/*/urls.py`
- Forms: `apps/*/forms.py` | Templates: `templates/` and `apps/*/templates/`
- Services: `apps/*/services.py` | Settings: `minibini/settings.py`
- `apps/jobs/models.py` - Core models (largest) | `apps/jobs/views.py` - Main views (largest)

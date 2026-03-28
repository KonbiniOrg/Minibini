# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Minibini is a Django-based job shop management system for handling jobs, estimates, work orders, invoicing, and purchasing. Pre-production state, rapidly evolving.

**Tech Stack:** Django 5.2+, Django REST Framework, MySQL, Python 3.12, Svelte 5 SPA (Vite)

## Essential Commands

```bash
# Backend development
python manage.py runserver              # Start Django dev server on :8000

# Frontend development
cd frontend && npm run dev              # Start Vite dev server on :9000 (proxies /api to :8000)
cd frontend && npm run build            # Build for production (outputs to dist/)

# Database
python manage.py makemigrations         # Create migrations (OK to run)
python manage.py loaddata unit_test_data.json  # Load test fixtures

# Testing
python manage.py test                   # Run all tests
python manage.py test tests.test_foo    # Run specific test module

# Docker
docker compose up                       # Full stack (app, mysql, nginx)

# Data seeding
./scripts/seed_data.sh                  # Seed realistic data via API (requires dev server running)
```

**CRITICAL:** NEVER run `python manage.py migrate` - only the human user applies migrations to the development database. Creating migrations with `makemigrations` is fine; tests create their own test database automatically.

## Architecture

```
Minibini/
├── apps/
│   ├── api/        # REST API (DRF viewsets, serializers, permissions, mixins)
│   ├── core/       # User, Configuration, BaseLineItem, LineItemType, HistoryEntry, Email
│   ├── jobs/       # Job, WorkOrder, Task, TaskBundle, Blep
│   ├── estimates/  # Estimate, EstWorksheet, EstimateLineItem, Templates
│   ├── contacts/   # Contact, Business, PaymentTerms
│   ├── invoicing/  # Invoice, InvoiceLineItem
│   ├── inventory/  # PriceListItem, Material, Earmark, InventoryAdjustment
│   ├── purchasing/ # PurchaseOrder, Bill, line items
│   └── search/     # Cross-entity search service
├── frontend/       # Svelte 5 SPA (Vite, svelte-spa-router)
├── templates/      # Django HTML templates (server-rendered views)
├── fixtures/       # Test data fixtures (JSON)
├── tests/          # Test suite
├── scripts/        # Utility scripts (seed_data.sh)
├── docs/plans/     # Design docs and implementation plans
├── minibini/       # Project configuration (settings, urls)
└── manage.py
```

**Key Patterns:**
- HTML views: function-based views only (no CBVs)
- API views: DRF ModelViewSets with reusable mixins (StatusTransitionMixin, LineItemMixin, TaskBundleMixin, TaskLifecycleMixin)
- Service classes in `apps/*/services.py` contain business logic — viewsets are thin wrappers
- Signals in `apps/jobs/signals.py` handle status change side effects
- Abstract `BaseLineItem` shared by all line item types
- Template system: `WorkOrderTemplate` → `TaskTemplate` → `TemplateTaskAssociation` → `TemplateBundle`

**Workflow:** Job → EstWorksheet (from template) → Estimate → WorkOrder → Invoice

## Key Models

### Core (`apps.core`)
- **User** - Custom AbstractUser, links to Contact. Has 6 custom permission atoms (see Permissions section)
- **Configuration** - Key-value store for system settings (document numbering sequences/counters, email settings). **Never add fields** - all settings are key-value pairs
- **HistoryEntry** - Audit log and notes linked to any entity (jobs, contacts, businesses)
- **LineItemType** - Categorizes line items (e.g., labor, materials)
- **AbstractWorkContainer** (Abstract) - Base for EstWorksheet and WorkOrder
- **BaseLineItem** (Abstract) - Shared fields for all line items: task, price_list_item, line_number, qty, units, description, price_currency. Validates items can't have both task AND price_list_item
- **EmailRecord** - Permanent record linking emails to jobs (message_id only, email server is source of truth)
- **TempEmail** - Temporary cache of email metadata from IMAP (OneToOne with EmailRecord, cleaned up after retention period)

### Jobs (`apps.jobs`)
- **Job** - Central entity. Status: draft → approved/rejected → needs_attention/blocked → complete
- **WorkOrder** - Actual work (extends AbstractWorkContainer). Status: draft → incomplete/blocked → complete
- **Task** - Work items belonging to either EstWorksheet OR WorkOrder (not both). Hierarchical with parent_task
- **TaskBundle** - Groups related tasks together
- **Blep** - Time tracking (start/end times for task work)

### Estimates (`apps.estimates`)
- **Estimate** - Quotes with versioning. Status: draft → open → accepted/rejected/superseded
- **EstWorksheet** - Working document for estimates (extends AbstractWorkContainer). Status: draft → final → superseded
- **EstimateLineItem** - Line items for estimates (inherits BaseLineItem)
- **Template System** - WorkOrderTemplate, TaskTemplate, TemplateTaskAssociation, TemplateBundle

### Contacts (`apps.contacts`)
- **Contact** - Individual person with multiple phone numbers, address, linked to Business
- **Business** - Company with tax info, payment terms, internal reference code
- **PaymentTerms** - Payment conditions

### Inventory (`apps.inventory`)
- **PriceListItem** - Catalog items with purchase/selling prices, inventory tracking
- **Material** - Materials used in jobs
- **Earmark** - Inventory earmarking for specific jobs/tasks
- **InventoryAdjustment** - Stock adjustments

### Invoicing (`apps.invoicing`)
- **Invoice** - Bills for completed work, linked to Job. Status: active/cancelled
- **InvoiceLineItem** - Inherits BaseLineItem

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

### Django HTML Views
- `/` - Home | `/admin/` - Django admin | `/settings/` - Settings
- `/jobs/` - Jobs (list, create, detail, work orders)
- `/estimates/` - Estimates, worksheets, templates, task-templates
- `/contacts/` - Contacts (add, confirm-create-business)
- `/core/` - Core (inbox, email detail, create-job-from-email)
- `/purchasing/` - Purchasing | `/invoicing/` - Invoicing
- `/search/` - Search | `/inventory/` - Inventory

### REST API (`/api/`)
- `/api/auth/` - Login, logout, me (session-based auth)
- `/api/jobs/`, `/api/contacts/`, `/api/businesses/`, `/api/payment-terms/`
- `/api/estimates/`, `/api/est-worksheets/`, `/api/work-orders/`
- `/api/invoices/`, `/api/purchase-orders/`, `/api/bills/`
- `/api/price-list-items/`, `/api/work-order-templates/`, `/api/task-templates/`, `/api/line-item-types/`
- `/api/emails/`, `/api/search/`, `/api/settings/`

### Svelte SPA (`frontend/`, served on `:9000` in dev)
Hash-based routing (`#/path`). Currently implements: home, contacts, businesses, jobs. Other entities still use Django HTML views.

## Frontend (Svelte SPA)

The primary UI is a Svelte 5 SPA at `frontend/`, built with Vite and using hash-based routing (`svelte-spa-router`).

- **Reactivity:** Svelte 5 runes (`$state`, `$derived`, `$effect`)
- **API client:** `src/lib/api.js` — handles CSRF tokens, session-based auth (no JWT)
- **Stores:** `src/stores/auth.js` (user state, login/logout), `src/stores/viewMode.js` (full/lite toggle)
- **Auth flow:** On mount, checks `/api/auth/me/`. Shows `LoginPage` if unauthenticated, otherwise renders nav + router
- **No CSS frameworks** — semantic HTML, same conventions as Django templates
- **Dev:** Vite on `:9000` proxies `/api/*` to Django on `:8000`
- **Prod:** `npm run build` → `dist/` served by nginx

## REST API (`apps/api/`)

DRF-based API serving the Svelte frontend. Session-based authentication (no tokens).

**Key patterns:**
- ViewSets use service classes for all business logic (`perform_create`/`perform_update` delegate to services)
- Reusable mixins: `StatusTransitionMixin` (status change actions), `LineItemMixin` (CRUD for line items), `TaskBundleMixin` (task/bundle CRUD), `TaskLifecycleMixin` (task state machine)
- Permission classes in `apps/api/permissions.py` — factory-generated from permission atoms
- `StandardPagination`: 25 items/page, max 100, via `?page_size=N`
- Delete confirmation pattern: first DELETE returns impact counts, second with `?confirm=true` executes

**Stubs (not yet implemented):** `/api/auth/refresh/`, `/api/emails/send/`, `/api/shifts/`, `/api/expenses/`, `/api/time-tracking/`

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

**Permissions:** Always check permissions in views:
- API viewsets: override `get_permissions()` returning `[IsAuthenticated(), CanXxx()]`
- API function views: `@permission_classes([IsAuthenticated, CanXxx])`
- HTML views: `@login_required` + `@permission_required('core.can_xxx', raise_exception=True)`
- Notes (HistoryEntry) and WO task creation are `IsAuthenticated` only
- Email viewing requires `CanManageJobs`

See `docs/plans/2026-03-24-permission-atom-redesign.md` for atoms, group mappings, and view-to-permission mapping.

## Permissions

### Permission Atoms (defined on User model)

| Permission | Covers |
|---|---|
| `can_view_financials` | Read-only access to invoices, POs, bills |
| `can_manage_jobs` | Full CRUD on jobs, estimates, worksheets, work orders, tasks, bundles, contacts, businesses; read+write emails |
| `can_manage_financials` | Full CRUD on invoices, POs, bills, price list items |
| `can_manage_time` | Edit/delete anyone's time entries (shifts + bleps) |
| `can_approve_expenses` | Approve/reject expenses over threshold |
| `can_manage_config` | Settings, templates, line item types, user admin |

**`IsAuthenticated` (no atom):** Read access to jobs, work orders, tasks, worksheets, estimates, contacts, businesses, payment terms, templates, line item types, search, price list items. Write access to notes on jobs/contacts/businesses and adding tasks to work orders.

**Implicit:** All authenticated users can track own time and submit own expenses.

### Default Groups

| Group | Permissions |
|---|---|
| Worker | *(none — IsAuthenticated covers read access)* |
| Admin | `can_manage_jobs`, `can_view_financials` |
| Bookkeeper | `can_view_financials`, `can_manage_financials`, `can_approve_expenses` |
| Manager | `can_manage_jobs`, `can_view_financials`, `can_manage_financials`, `can_manage_time`, `can_approve_expenses` |
| Owner | all atoms |

Groups are defined in fixture data, not migrations. Shops customize to suit their needs.

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

- **Dev autologin** — Frontend supports `?autologin` query param to log in as dev_user via the API (requires dev_user with password `dev_password`)
- **Seed script** — `scripts/seed_data.sh` seeds realistic data through API endpoints (requires dev server on :8000)
- **Management commands** — `populate_data.py` (base), `populate_contact_data.py`, `populate_job_data.py`

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
- API: `apps/api/*/views.py` (viewsets), `apps/api/*/serializers.py`, `apps/api/mixins.py`, `apps/api/permissions.py`
- Frontend: `frontend/src/` — `App.svelte`, `routes/`, `components/`, `stores/`, `lib/api.js`
- Design docs: `docs/plans/`

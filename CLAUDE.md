# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Minibini is a Django-based job shop management system for handling jobs, estimates, tasks, invoicing, and purchasing. Pre-production state, rapidly evolving.

**Tech Stack:** Django 5.2+, Django REST Framework, MySQL, Python 3.12, Svelte 5 SPA (Vite)

## Brainstorming / Design Discussion

**Never use the multiple-choice / AskUserQuestion framework when brainstorming with this user.** Conduct design discussions as unstructured, back-and-forth prose — one idea or question at a time, in conversational paragraphs. This overrides any skill or default that prefers multiple-choice questions.

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

# Scheduled jobs
# Management commands like `poll_qbo_payments` exist; a crontab/scheduler to
# run them is not yet wired in any deployed environment.

# Data seeding
./scripts/seed_data.sh                  # Seed realistic data via API (requires dev server running)
```

**CRITICAL — never write to the dev database.** Only the human user is allowed to mutate the dev DB. Specifically:

- Never run `python manage.py migrate`. Creating migrations with `makemigrations` is fine; tests create their own test database automatically.
- Never run `python manage.py shell` (or `shell_plus`) and execute ORM writes — `Model.objects.create(...)`, `.save()`, `.delete()`, etc. all commit to the dev DB.
- Never run `python -c "import django; django.setup(); ..."` followed by ORM writes for the same reason.
- Never run `python manage.py loaddata` against the dev DB.
- Never connect to the DB directly via `mysql` / `psql` / a Python DB driver and execute writes.
- Never run scripts in the repo (`scripts/seed_data.sh`, anything in `apps/core/management/commands/`) that mutate the DB.

If you need to verify model behavior, write a test and run `python manage.py test` (which uses a separate test DB and tears it down). If you need to see the current state of dev data, ask the user to run the query themselves and paste the result.

**Read-only dev DB access via SQL is OK** for diagnostics (e.g. `mysql ... -e "SELECT ..."`) but never write SQL.

Subagents inherit this rule. When dispatching a subagent, repeat the rule in the prompt if the task involves any DB-related work — subagents tend to "verify" model definitions by spinning up a shell, which writes data.

## Architecture

```
Minibini/
├── apps/
│   ├── api/        # REST API (DRF viewsets, serializers, permissions, mixins)
│   ├── core/       # User, Configuration, BaseLineItem, AccountingCategory, HistoryEntry, Email
│   ├── jobs/       # Job, Task, PlanTask, Blep
│   ├── estimates/  # Estimate, EstWorksheet, EstimateLineItem, Templates
│   ├── contacts/   # Contact, Business, PaymentTerms
│   ├── invoicing/  # Invoice, InvoiceLineItem
│   ├── inventory/  # PriceListItem, Material, Earmark, InventoryAdjustment
│   ├── purchasing/ # PurchaseOrder, Bill, line items
│   ├── deliverables/ # Deliverable, Shipment, ShipmentItem
│   ├── search/     # Cross-entity search service
│   └── schedule/   # ScheduleService — per-worker time-axis layout (model-less)
├── frontend/       # Svelte 5 SPA (Vite, svelte-spa-router)
├── templates/      # Django HTML templates (server-rendered views)
├── fixtures/       # Test data fixtures (JSON)
├── tests/          # Test suite
├── scripts/        # Utility scripts (seed_data.sh)
├── docs/designs/   # Topic reference docs (nine consolidated areas — see below)
├── docs/plans/     # Working directory for short-lived implementation plans (currently empty)
├── minibini/       # Project configuration (settings, urls)
└── manage.py
```

**Key Patterns:**
- HTML views: function-based views only (no CBVs); deprecated, being decommissioned opportunistically
- API views: DRF ModelViewSets with reusable mixins (`StatusTransitionMixin`, `LineItemMixin`, `JobTaskMixin`, `PlanTaskMixin`) — see `docs/designs/architecture-and-conventions.md`
- Service classes in `apps/*/services.py` contain business logic — viewsets are thin wrappers
- Job status side effects live in `apps/jobs/services.py` (`apps/jobs/signals.py` is empty). Estimate-driven cross-model side effects live in `apps/estimates/signals.py`
- Abstract `BaseLineItem` shared by all line item types
- Template system: `WorkTemplate` ↔ `TaskTemplate` via `TemplateTaskAssociation`, plus `TemplateMaterialAssociation` for materials

**Workflow:** Job → EstWorksheet (optionally from template) → Estimate → atoms carry over to Job on accept → Tasks worked → Invoice → QBO push

## Topic reference docs

`docs/designs/` holds nine consolidated docs. When working in a domain, start at its doc; cross-references link out where needed.

**Keep these current.** These are the durable record of how the system behaves. After every work session that changes behavior, models, endpoints, config keys, or UI conventions in a domain, update the corresponding `docs/designs/` doc(s) in the same session so they don't drift from the code. (Disposable specs/plans live in `docs/plans/`; the durable reference is `docs/designs/`.)

| Doc | Covers |
|---|---|
| `architecture-and-conventions.md` | Service layer, mixin catalog, permissions plumbing, line-item pattern, view-mode, history capture, sidebar |
| `jobs-tasks-and-worksheets.md` | Job, Task, Blep, EstWorksheet, PlanTask, Templates, Job Board, lifecycle service, Deliverables, Shipments |
| `estimates-and-prices.md` | RateScheme + supersession, billable atoms, Estimate + wizard, atom carry-over, AC pass-through |
| `materials-inventory-and-purchasing.md` | PriceListItem, Material, PlanMaterial, Earmarks, units, PurchaseOrder, Bill |
| `invoicing-and-expenses.md` | Invoice + wizard, send-to-customer flow, Expense + Reimbursement |
| `quickbooks-integration.md` | QBO models, OAuth, sync services, polling, developer setup appendix |
| `users-and-permissions.md` | User model, permission atoms, auth, user admin, self-service, login tracking (designed not built) |
| `data-constraints.md` | Cross-model invariants and field-by-field constraints (validator-consumable reference) |
| `schedule.md` | ScheduleService, the forecast cascade, bar kinds/layering, schedule Configuration, the `/schedule` page |

## Key Models

| App | Models | Authoritative doc |
|---|---|---|
| `apps.core` | User, Configuration, AccountingCategory, BaseLineItem (abstract), AbstractWorkContainer (abstract), HistoryEntry, EmailRecord, TempEmail | architecture, users-and-permissions, data-constraints |
| `apps.jobs` | Job, Task, PlanTask, Blep, RateScheme | jobs-tasks-and-worksheets (Job/Task/Blep/PlanTask) + estimates-and-prices (RateScheme) |
| `apps.estimates` | Estimate, EstimateLineItem, EstimateLineItemSource, EstWorksheet, WorkTemplate, TaskTemplate, TemplateTaskAssociation | estimates-and-prices + jobs-tasks-and-worksheets (worksheets, templates) |
| `apps.contacts` | Contact, Business, PaymentTerms | data-constraints §1.5, §1.4 |
| `apps.inventory` | PriceListItem, Material, PlanMaterial, Earmark, InventoryAdjustment, TemplateMaterialAssociation | materials-inventory-and-purchasing |
| `apps.purchasing` | PurchaseOrder, PurchaseOrderLineItem, Bill, BillLineItem | materials-inventory-and-purchasing |
| `apps.invoicing` | Invoice, InvoiceLineItem, InvoiceLineItemSource | invoicing-and-expenses |
| `apps.expenses` | Expense, Reimbursement | invoicing-and-expenses |
| `apps.deliverables` | Deliverable, Shipment, ShipmentItem | jobs-tasks-and-worksheets §12 |
| `apps.qbo` | QBOConnection, QBOSyncLog | quickbooks-integration |
| `apps.schedule` | _(no models)_ — `ScheduleService` produces the `/schedule` view's per-worker bars from Tasks + Bleps + `Job.accent_color` + Configuration | `docs/designs/schedule.md` |

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

For the full list of in-use keys (document numbering, units list, QBO payment accounts, board retention, email retention, PO email templates, etc.) see `docs/designs/data-constraints.md` §1.1.

When adding new keys, also add to test `setUp()` methods and fixture files.

## Document Numbering (NumberGenerationService)

```python
from apps.core.services import NumberGenerationService
job_number = NumberGenerationService.generate_next_number('job')  # "JOB-2025-0001"
```

Pattern placeholders: `{year}`, `{month:02d}`, `{day:02d}`, `{counter:04d}`. Uses `select_for_update()` for thread safety. Patterns and counters stored in Configuration.

## URL Structure

### Django HTML Views
- `/` - Home | `/admin/` - Django admin | `/settings/` - Settings
- `/jobs/` - Jobs (list, create, detail)
- `/estimates/` - Estimates, worksheets, templates, task-templates
- `/contacts/` - Contacts (add, confirm-create-business)
- `/core/` - Core (inbox, email detail, create-job-from-email)
- `/purchasing/` - Purchasing | `/invoicing/` - Invoicing
- `/search/` - Search | `/inventory/` - Inventory

### REST API (`/api/`)
- `/api/auth/` — login, logout, me, me/password, refresh stub, lightweight users dropdown
- `/api/jobs/`, `/api/contacts/`, `/api/businesses/`, `/api/payment-terms/`
- `/api/estimates/`, `/api/est-worksheets/`, `/api/plan-tasks/`, `/api/rate-schemes/`, `/api/tasks/`, `/api/bleps/`
- `/api/invoices/`, `/api/purchase-orders/`, `/api/bills/`
- `/api/price-list-items/`, `/api/materials/`, `/api/work-templates/`, `/api/task-templates/`, `/api/accounting-categories/`
- `/api/expenses/`, `/api/reimbursements/`
- `/api/jobs/{id}/deliverables/`, `/api/shipments/` (Shipments are flat; Deliverables are job-nested)
- `/api/users/` (admin), `/api/qbo/` (OAuth + accounts + payment-accounts)
- `/api/emails/`, `/api/search/`, `/api/schedule/`, `/api/settings/`, `/api/home/`

Per-viewset action endpoints (status transitions, line items, wizard, etc.) live in the topic docs.

### Svelte SPA (`frontend/`, served on `:9000` in dev)
Hash-based routing (`#/path`). The SPA is the primary UI; covers home, jobs (board + detail + task list + task detail), schedule, contacts, businesses, estimates, worksheets, invoices (incl. wizard), purchase orders, expenses, reimbursements, users, settings, profile, email, search. Some legacy Django HTML views still exist for opportunistic decommissioning.

## Frontend (Svelte SPA)

The primary UI is a Svelte 5 SPA at `frontend/`, built with Vite and using hash-based routing (`svelte-spa-router`).

- **Reactivity:** Svelte 5 runes (`$state`, `$derived`, `$effect`)
- **API client:** `src/lib/api.js` — handles CSRF tokens, session-based auth (no JWT)
- **Stores:** `src/stores/auth.js` (user state, login/logout), `src/stores/viewMode.js` (full/lite toggle)
- **Auth flow:** On mount, checks `/api/auth/me/`. Shows `LoginPage` if unauthenticated, otherwise renders nav + router
- **No CSS frameworks** — semantic HTML, same conventions as Django templates
- **Dev:** Vite on `:9000` proxies `/api/*` to Django on `:8000`
- **Prod:** `npm run build` → `dist/` served by nginx

## UI Decisions

Conventions to keep the SPA's interaction vocabulary consistent. New code follows these unless there's a specific reason not to.

- **Links navigate; buttons act.** Use `<a href="...">` (or `use:link`) for anything that takes the user to a different view. Use `<button>` for anything that mutates state, opens a modal, or triggers an API call without a navigation. Don't dress a `<button>` as a link to navigate, and don't wrap a `<a>` around an action handler.
- **Saves are explicit, never blur-only.** `onblur` (or any other implicit focus/navigation event) must never be the only trigger that commits a change to the server. Users move focus accidentally — losing or saving work as a side effect is hostile. Every mutation needs an explicit confirmation: a Save button, an Enter-on-form, an explicit modal "OK". `onblur` is fine as a secondary trigger (validating format, normalizing values into pending state) but the actual API call must wait for a deliberate action.
- **Confirmations are for the irreversible, not the reversible.** Only prompt (`confirm()` / a modal) when an action is irreversible or extremely arduous to undo — deleting a persisted record, sending a document to a customer. **Never** confirm an action that's exactly undoable by another local action (editing a field, toggling, reordering, adding/removing a draft line that can be re-added or removed). A reversible action just does the thing.

## REST API (`apps/api/`)

DRF-based API serving the Svelte frontend. Session-based authentication (no tokens).

**Key patterns:**
- ViewSets use service classes for all business logic (`perform_create`/`perform_update` delegate to services)
- Reusable mixins: `StatusTransitionMixin`, `LineItemMixin`, `JobTaskMixin`, `PlanTaskMixin` — full catalog in `docs/designs/architecture-and-conventions.md`
- Permission classes in `apps/api/permissions.py` — factory-generated from the four permission atoms
- `StandardPagination`: 25 items/page, max 100, via `?page_size=N`
- Delete confirmation pattern (two-phase): first DELETE returns impact counts, second with `?confirm=true` executes
- **All DELETE responses return 200 with a JSON body** (e.g. `{'message': '... deleted.'}`), never 204. The frontend `api.js` wrapper assumes every response has JSON. Override DRF's default `destroy()` on new viewsets

501 stub list and viewset compliance details are in `docs/designs/architecture-and-conventions.md` §3.6 and §3.8.

## Template/HTML Conventions

**Scope:** this section applies to the deprecated Django HTML view layer (`apps/*/views.py` + `templates/`), still present and edited opportunistically. The SPA uses its own conventions — semantic HTML, per-component `<style>` blocks, and an **error-overlay / success-overlay** pattern (red / green borders) for user feedback, owned by `frontend/src/lib/api.js`. SPA UI conventions are documented in `frontend/README.md`; the architecture doc covers the cross-cutting view-mode, sidebar, and history-panel patterns.

- **No CSS frameworks, no JavaScript** (except datetime-local inputs)
- **Semantic HTML only:** `<p>`, `<strong>`, `<fieldset>`, `<table border="1">`
- **Django messages:** Use `messages.success()`/`error()` in HTML views; NEVER duplicate message display in templates (base.html handles it). The SPA does NOT use Django messages — it uses `lib/api.js` overlays instead
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

**Table markup:** Always wrap `<tr>` rows in `<tbody>` (or `<thead>`/`<tfoot>`). Svelte 5 strict mode rejects `<tr>` as a direct child of `<table>` and the build will fail.

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

**Line item deletion:** NEVER call `.delete()` directly on a line item (`EstimateLineItem`, `InvoiceLineItem`, `PurchaseOrderLineItem`, `BillLineItem`). Always go through `LineItemService.delete_line_item_with_renumber(line_item)` — `BaseLineItem.delete()` does NOT renumber survivors, so a direct call leaves gaps in `line_number` (e.g. lines 2, 3, 5, 7). The only legitimate exception is the implementation of `delete_line_item_with_renumber` itself. Cascade deletes from the parent container (Estimate/Invoice/PO/Bill) are fine because Django uses bulk-delete and skips per-instance `.delete()` entirely. If you need to delete a line item from a new code path, route it through the service.

**QuerySet.update() / bulk writes:** NEVER use `QuerySet.update()`, `bulk_update`, or `bulk_create` for fields that `Model.save()` normalizes or that trigger side effects — these bypass `save()` entirely (same reasoning as the `QuerySet.delete()` rule above). `Shift.save()` and `Blep.save()` floor `start_time`/`end_time` to the whole minute, so a `Blep.objects.filter(...).update(end_time=now)` would persist an unfloored timestamp and break shift↔blep minute alignment. Iterate and call `.save()` per instance instead:
```python
bleps = list(qs)
for blep in bleps:
    blep.end_time = now
    blep.save()
```

**Transactions:** Wrap multi-model operations:
```python
with transaction.atomic():
    business = Business.objects.create(...)
    contact = Contact.objects.create(business=business, ...)
```

**Types:** Pass correct types to model fields (don't wrap numbers in `str()`).

**`__init__.py` files:** Keep `__init__.py` files empty (or limited to re-exports). Do not put service classes, models, or other substantial code in `__init__.py`. Use dedicated modules instead (e.g., `services.py`, not `services/__init__.py`).

**Field renames:** After migration renames, grep entire codebase for old field name. Python silently allows setting arbitrary attributes on model instances.

**Permissions:** Always check permissions in views:
- API viewsets: override `get_permissions()` returning `[IsAuthenticated(), CanXxx()]`
- API function views: `@permission_classes([IsAuthenticated, CanXxx])`
- HTML views: `@login_required` + `@permission_required('core.can_xxx', raise_exception=True)`
- Notes (HistoryEntry) and adding tasks to a Job are `IsAuthenticated` only
- Email *reads* (`/api/emails/`, detail) are `IsAuthenticated`; email-to-job actions (link, unlink, create-job-from-email) require `CanManageJobs`

See `docs/designs/users-and-permissions.md` for the full atom-to-endpoint mapping.

## Permissions

Four custom permission atoms on the `User` model:

| Atom | Covers |
|---|---|
| `can_manage_jobs` | Full CRUD on jobs, estimates, worksheets, tasks, contacts, businesses; email-to-job actions (link, unlink, create-job-from-email) |
| `can_manage_financials` | Full CRUD on invoices, POs, bills, price list items, expenses, reimbursements |
| `can_manage_time` | Edit/delete anyone's bleps (own bleps are `IsAuthenticated` within the 24h rolling window) |
| `can_manage_config` | Settings, templates, accounting categories, user admin, QBO connection |

**`IsAuthenticated` (no atom):** Read access to jobs, tasks, worksheets, estimates, contacts, businesses, payment terms, templates, accounting categories, search, price list items, invoices, purchase orders, bills, emails. Write access to notes on jobs/contacts/businesses, adding tasks to existing jobs, and submitting/tracking own time and expenses.

**`is_superuser` bypasses every atom check.**

Django Groups are not used; permissions are assigned per-atom on `user_permissions`. Full endpoint-to-atom table lives in `docs/designs/users-and-permissions.md` §3.

## Business Workflows

### Job Creation Flow
Job → EstWorksheet (optionally from template) → Estimate → Tasks on Job → Time tracking (Bleps) → Job advances to `work_complete` when all tasks complete → Invoice

### Email-to-Job Workflow
1. Fetch emails from IMAP → EmailRecord + TempEmail. `TempEmail.text_body` / `html_body` cache the message body and `TempEmail.attachments_metadata` caches per-attachment filename/content_type/size so list views, `sender_info`, and the email-detail page render without re-hitting IMAP. `EmailService.get_email_content` falls back to IMAP only when `temp_data` is missing or the cache is incomplete (no body cached, or `has_attachments=True` with empty `attachments_metadata` — e.g. pre-backfill rows). Attachment payloads themselves are never cached.
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
- **NEVER run `python manage.py test` from multiple subagents in parallel.** They all share one MySQL database and will deadlock fighting over test database creation/destruction. Only one agent at a time may run tests.
- **Front-end (Svelte SPA):** component/unit tests use Vitest, in `frontend/tests/`; run `npm run test:run` from `frontend/`. Extend TDD to the SPA — add/update a component's test in the same change. Patterns, conventions, and the behavior-vs-display triage live in `docs/designs/frontend-testing.md`.

## Development Features

- **Seed script** — `scripts/seed_data.sh` seeds realistic data through API endpoints (requires dev server on :8000)
- **Management commands** — `populate_data.py` (base), `populate_contact_data.py`, `populate_job_data.py`

### QuickBooks Online Integration

See `docs/designs/quickbooks-integration.md` for the full reference, including OAuth credentials, `.env` setup, and the first-connect walkthrough.

## Common Coding Pitfalls

1. **Old field names after renames** - Python silently sets arbitrary attributes; data never saved
2. **Status value typos** - Use model constants (`Job.STATUS_COMPLETED`), not strings
3. **Defaults not in choices** - Always use a value from the choices list
4. **Number regeneration on edit** - Guard with `if not instance.pk:`
5. **QuerySet.delete() bypasses Model.delete()** - Iterate and call delete() individually
6. **Missing transaction wrapping** - Multi-model ops need `transaction.atomic()`
7. **Type coercion** - Pass correct types to ORM fields
8. **Direct `.delete()` on a line item** - Leaves `line_number` gaps. Always go through `LineItemService.delete_line_item_with_renumber(line_item)`
9. **QuerySet.update() bypasses Model.save()** - Iterate and call `save()` individually when `save()` normalizes fields or has side effects (e.g. Shift/Blep floor times to the minute)

### Code Review Checklist
- [ ] Status values match model choice definitions
- [ ] Default values are in the choices list
- [ ] Document numbers only generated for new instances
- [ ] Field names match current model (no old renamed fields)
- [ ] Integer fields receive integers, not strings
- [ ] Custom delete() methods are respected (no QuerySet.delete())
- [ ] Line item deletes go through `LineItemService.delete_line_item_with_renumber`
- [ ] Multi-model operations are wrapped in transactions

## Key File Locations

- Models: `apps/*/models.py` | Views: `apps/*/views.py` | URLs: `apps/*/urls.py`
- Forms: `apps/*/forms.py` | Templates: `templates/` and `apps/*/templates/`
- Services: `apps/*/services.py` | Settings: `minibini/settings.py`
- API: `apps/api/*/views.py` (viewsets), `apps/api/*/serializers.py`, `apps/api/mixins.py`, `apps/api/permissions.py`
- Frontend: `frontend/src/` — `App.svelte`, `routes/`, `components/`, `stores/`, `lib/api.js`
- Topic reference docs: `docs/designs/` (nine files; see "Topic reference docs" above)
- Implementation plans (temporary working files): `docs/plans/` (currently empty)

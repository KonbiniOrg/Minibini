# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Minibini is a Django-based job shop management system for handling jobs, estimates, tasks, invoicing, and purchasing. Pre-production state, rapidly evolving.

**Tech Stack:** Django 5.2+, Django REST Framework, MySQL, Python 3.12, Svelte 5 SPA (Vite)

## Brainstorming / Design Discussion

**Never use the multiple-choice / AskUserQuestion framework when brainstorming with this user.** Conduct design discussions as unstructured, back-and-forth prose — one idea or question at a time, in conversational paragraphs. This overrides any skill or default that prefers multiple-choice questions.

## Engineering Principles

**Test-count is never an architecture argument.** How many tests would need updating — or how many a given placement "auto-fixes" — is *not* a valid reason to choose or reject where a guard, invariant, abstraction, or transition belongs. Decide placement on correctness alone: where the invariant is actually true and must hold. Then update whatever tests fall out. A large blast radius is *signal about the change's reach*, not a veto, and never a justification. Relocating or weakening a real invariant to spare test churn is exactly how real invariants get quietly lost. If you catch yourself citing test counts, broken tests, or "this avoids touching N files" as support for a design decision, stop — that reasoning is inadmissible; re-argue the decision on its merits, and if the correct placement is expensive, surface the trade-off explicitly instead of letting test cost silently pick the design.

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
cd e2e && npx playwright test           # E2E suite (own ports 8100/9100; dev servers can stay up)

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
- Never run scripts in the repo (anything in `apps/core/management/commands/`, data generators) that mutate the DB.

If you need to verify model behavior, write a test and run `python manage.py test` (which uses a separate test DB and tears it down). If you need to see the current state of dev data, ask the user to run the query themselves and paste the result.

**Read-only dev DB access via SQL is OK** for diagnostics (e.g. `mysql ... -e "SELECT ..."`) but never write SQL.

Subagents inherit this rule. When dispatching a subagent, repeat the rule in the prompt if the task involves any DB-related work — subagents tend to "verify" model definitions by spinning up a shell, which writes data.

## Architecture

```
Minibini/
├── apps/
│   ├── api/        # REST API (DRF viewsets, serializers, permissions, mixins)
│   ├── core/       # User, Configuration, BaseLineItem, AccountingCategory, HistoryEntry, Email
│   ├── jobs/       # Job, Task, Blep, RateScheme
│   ├── estimates/  # Estimate, ChangeOrder, EstimateLineItem, Templates
│   ├── contacts/   # Contact, Business, PaymentTerms
│   ├── invoicing/  # Invoice, InvoiceLineItem
│   ├── inventory/  # InventoryItem (catalog/lots), Material, Earmark
│   ├── purchasing/ # PurchaseOrder + line items (Bill models are retired schema-only stubs — bills live in QBO)
│   ├── deliverables/ # Deliverable, Shipment, ShipmentItem
│   ├── search/     # Cross-entity search service
│   └── schedule/   # ScheduleService — per-worker time-axis layout (model-less)
├── frontend/       # Svelte 5 SPA (Vite, svelte-spa-router)
├── templates/      # PDF templates only (estimate/change-order/PO/job-statement) rendered by the API via WeasyPrint
├── fixtures/       # Test data fixtures (JSON)
├── tests/          # Test suite
├── docs/designs/   # Topic reference docs (nine consolidated areas — see below)
├── docs/plans/     # Working directory for short-lived implementation plans (disposable; deleted once shipped)
├── minibini/       # Project configuration (settings, urls)
└── manage.py
```

**Key Patterns:**
- The Svelte SPA + REST API is the only UI. The deprecated Django HTML view layer (`apps/*/views.py` + `templates/*.html`) has been fully removed; the only server-rendered templates left are the three PDF templates (see Template/PDF section below)
- API views: DRF ModelViewSets with reusable mixins (`StatusTransitionMixin`, `LineItemMixin`, `JobTaskMixin`) — see `docs/designs/architecture-and-conventions.md`
- Service classes in `apps/*/services.py` contain business logic — viewsets are thin wrappers
- Job status side effects live in `apps/jobs/services.py` (`apps/jobs/signals.py` is empty). Estimate-driven cross-model side effects live in `apps/estimates/signals.py`
- Abstract `BaseLineItem` shared by all line item types
- Template system: `WorkTemplate` ↔ `ServiceItem` via `TemplateTaskAssociation`, plus `TemplateMaterialAssociation` for materials

**Workflow:** Job (tasks optionally generated from a WorkTemplate) → Estimate (wizard composes line items from the job's atoms) → accept crystallizes service hand-lines into Tasks → Tasks worked → Invoice → QBO push

## Topic reference docs

`docs/designs/` holds ten consolidated docs. When working in a domain, start at its doc; cross-references link out where needed.

**Keep these current.** These are the durable record of how the system behaves. After every work session that changes behavior, models, endpoints, config keys, or UI conventions in a domain, update the corresponding `docs/designs/` doc(s) in the same session so they don't drift from the code. (Disposable specs/plans live in `docs/plans/`; the durable reference is `docs/designs/`.)

| Doc | Covers |
|---|---|
| `architecture-and-conventions.md` | Service layer, mixin catalog, permissions plumbing, line-item pattern, view-mode, history capture, sidebar |
| `jobs-tasks-and-worksheets.md` | Job, Task, Blep, Templates, Job Board, lifecycle service, Deliverables, Shipments (filename is historical — the worksheet layer was removed) |
| `estimates-and-prices.md` | RateScheme + supersession, billable atoms, Estimate + wizard, atom carry-over, AC pass-through |
| `materials-inventory-and-purchasing.md` | InventoryItem (catalog/lots), Material, Earmarks, units, PurchaseOrder, the Bill retirement |
| `contacts-and-businesses.md` | Contact, Business, Tag, PaymentTerms, duplicate-email/name detection, financials rollup, the combined Contacts & Businesses frontend surface |
| `invoicing-and-expenses.md` | Invoice + wizard, send-to-customer flow, Expense + Reimbursement |
| `quickbooks-integration.md` | QBO models, OAuth, sync services, polling, developer setup appendix |
| `users-and-permissions.md` | User model, permission atoms, auth, user admin, self-service, login tracking (designed not built) |
| `data-constraints.md` | Cross-model invariants and field-by-field constraints (validator-consumable reference) |
| `schedule.md` | ScheduleService, the forecast cascade, bar kinds/layering, schedule Configuration, the `/schedule` page |

## Key Models

| App | Models | Authoritative doc |
|---|---|---|
| `apps.core` | User, Configuration, AccountingCategory, BaseLineItem (abstract), AbstractWorkContainer (abstract), HistoryEntry, EmailRecord, TempEmail | architecture, users-and-permissions, data-constraints |
| `apps.jobs` | Job, Task, Blep, RateScheme, Fee | jobs-tasks-and-worksheets (Job/Task/Blep) + estimates-and-prices (RateScheme) |
| `apps.estimates` | Estimate, ChangeOrder, EstimateLineItem, EstimateLineItemSource, WorkTemplate, ServiceItem, TemplateTaskAssociation | estimates-and-prices + jobs-tasks-and-worksheets (templates) |
| `apps.contacts` | Contact, Business, PaymentTerms, Tag | contacts-and-businesses + data-constraints §1.5, §1.4 |
| `apps.inventory` | InventoryItem (was PriceListItem; `is_catalog` flag), Material, Earmark, TemplateMaterialAssociation | materials-inventory-and-purchasing |
| `apps.purchasing` | PurchaseOrder, PurchaseOrderLineItem (Bill/BillLineItem/BillPayment are retired schema-only stubs, 2026-07-23 — bills live in QBO) | materials-inventory-and-purchasing |
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

Django serves only two URL prefixes now: `/admin/` (Django admin) and `/api/` (the REST API). The old server-rendered HTML routes (`/jobs/`, `/estimates/`, `/contacts/`, `/core/`, `/purchasing/`, `/invoicing/`, `/search/`, `/inventory/`, `/settings/`, and the `/` home page) have been removed — the SPA is the UI. QBO OAuth redirect views live under `/api/qbo/` (browser redirects, not the deleted HTML layer).

### REST API (`/api/`)
- `/api/auth/` — login, logout, me, me/password, refresh stub, lightweight users dropdown
- `/api/jobs/`, `/api/contacts/`, `/api/businesses/`, `/api/payment-terms/`
- `/api/estimates/`, `/api/change-orders/`, `/api/rate-schemes/`, `/api/tasks/`, `/api/bleps/`
- `/api/invoices/`, `/api/purchase-orders/`
- `/api/inventory/`, `/api/materials/`, `/api/earmarks/` (read-only), `/api/work-templates/`, `/api/service-items/`, `/api/accounting-categories/`
- `/api/expenses/`, `/api/reimbursements/`
- `/api/jobs/{id}/deliverables/`, `/api/shipments/` (Shipments are flat; Deliverables are job-nested)
- `/api/users/` (admin), `/api/qbo/` (OAuth + accounts + payment-accounts)
- `/api/emails/`, `/api/search/`, `/api/schedule/`, `/api/settings/`, `/api/home/`

Per-viewset action endpoints (status transitions, line items, wizard, etc.) live in the topic docs.

### Svelte SPA (`frontend/`, served on `:9000` in dev)
Hash-based routing (`#/path`). The SPA is the only UI; covers home, jobs (board + detail + task list + task detail), schedule, contacts, businesses, estimates, change orders, invoices (incl. wizard), purchase orders, catalog (inventory / service items / earmarks tabs), expenses, reimbursements, users, settings, profile, email, search. (The legacy Django HTML views have been removed.)

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
- Reusable mixins: `StatusTransitionMixin`, `LineItemMixin`, `JobTaskMixin` — full catalog in `docs/designs/architecture-and-conventions.md`
- Permission classes in `apps/api/permissions.py` — factory-generated from the four permission atoms
- `StandardPagination`: 25 items/page, max 100, via `?page_size=N`
- Delete confirmation pattern (two-phase): first DELETE returns impact counts, second with `?confirm=true` executes
- **All DELETE responses return 200 with a JSON body** (e.g. `{'message': '... deleted.'}`), never 204. The frontend `api.js` wrapper assumes every response has JSON. Override DRF's default `destroy()` on new viewsets

501 stub list and viewset compliance details are in `docs/designs/architecture-and-conventions.md` §3.6 and §3.8.

**Error responses — USE THIS STRUCTURE** (full contract:
`docs/designs/architecture-and-conventions.md` §3.9):

- Exactly two error shapes: `{'detail': '<sentence>'}` for operation errors,
  `{'<field>': ['msg', ...]}` (with `non_field_errors` for cross-field) for
  validation. `{'message': ...}` is success-only; the `'error'` key is
  retired — never emit it.
- Do NOT catch a service `ValidationError` just to re-render it as a 400 —
  the central handler (`apps/api/exceptions.py`, registered in settings)
  renders uncaught `ValidationError` (and `ProtectedError` → 409) in
  contract shape. Catch only to change the status code or add payload, and
  `raise` any variant the catch doesn't reshape.
- In services, raise `ValidationError({'field': ['msg']})` when the problem
  belongs to an input field, plain `ValidationError('sentence')` otherwise —
  that choice is what the SPA renders.
- Frontend: route every error through `triageError(e)`
  (`lib/errorTriage.js`) to its venue — `FieldError` slots under inputs,
  `FormMessage` under the form's buttons, or the global overlay
  (`stores/messages.js` `showError`/`showSuccess`) for form-less and
  infrastructure errors. Never `JSON.stringify(e.data)`, never display
  bare `e.message`, never `window.alert()` for API results; branch on
  `err.status` / `err.data?.code` for flow (e.g. 409). Exemplar:
  `RateSchemeManager.svelte`; rules: `frontend/README.md` → Error
  Handling.

## UI Conventions

The UI is the Svelte SPA. It uses semantic HTML, per-component `<style>` blocks, and an **error-overlay / success-overlay** pattern (red / green bordered boxes; CSS classes in `frontend/src/css/app.css`, markup per page) for user feedback. Error *text* always comes from `errorMessage()` / `fieldErrors()` — see the error-response contract above. SPA UI conventions are documented in `frontend/README.md`; the architecture doc covers the cross-cutting view-mode, sidebar, and history-panel patterns. (The Django HTML view layer and its template conventions were removed; only the PDF templates below remain.)

**Table markup:** Always wrap `<tr>` rows in `<tbody>` (or `<thead>`/`<tfoot>`). Svelte 5 strict mode rejects `<tr>` as a direct child of `<table>` and the build will fail.

## PDF Templates

The only server-rendered Django templates left live in `templates/` and are rendered by the API via WeasyPrint to produce PDF attachments for outbound email (the SPA "send" buttons hit the API, which generates the PDF in memory):

| Template | Generator | Endpoint |
|---|---|---|
| `templates/estimates/estimate_pdf.html` | `apps/estimates/pdf.py` | `POST /api/estimates/{id}/send` |
| `templates/estimates/change_order_pdf.html` | `apps/estimates/pdf.py` | `POST /api/change-orders/{id}/send` |
| `templates/purchasing/purchase_order_pdf.html` | `apps/purchasing/pdf.py` | `POST /api/purchase-orders/{id}/send` |

These are self-contained (no `{% extends %}`/`{% include %}`). The invoice send attaches QBO's rendered PDF instead of a local one (the old `job_statement.html` was deleted 2026-07-23). Email subject/body templates are NOT files — they live in `Configuration` rows and render via `apps/core/email_templates.py`.

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

**Line item deletion:** NEVER call `.delete()` directly on a line item (`EstimateLineItem`, `InvoiceLineItem`, `PurchaseOrderLineItem`). Always go through `LineItemService.delete_line_item_with_renumber(line_item)` — `BaseLineItem.delete()` does NOT renumber survivors, so a direct call leaves gaps in `line_number` (e.g. lines 2, 3, 5, 7). The only legitimate exception is the implementation of `delete_line_item_with_renumber` itself. Cascade deletes from the parent container (Estimate/Invoice/PO) are fine because Django uses bulk-delete and skips per-instance `.delete()` entirely. If you need to delete a line item from a new code path, route it through the service.

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
- Notes (HistoryEntry) and adding/editing/deleting/completing/**cancelling** tasks on a Job are `IsAuthenticated` only (cancel opened to all workers 2026-07-12 — it shares delete's principal set); reordering and marking all work complete use `CanManageJobOrPM` (atom or the job's PM)
- `CanManageJobOrPM` (`apps/api/permissions.py`) gates job-owned writes so a Job's `project_manager` gets atom-equivalent access to that one job; viewsets mix in `JobScopedPermissionMixin` and serializers expose a `can_manage` flag via `JobScopedCanManageMixin`
- Email *reads* (`/api/emails/`, detail) are `IsAuthenticated`; email-to-job actions (link, unlink, create-job-from-email) require `CanManageJobs`

See `docs/designs/users-and-permissions.md` for the full atom-to-endpoint mapping.

## Permissions

Four custom permission atoms on the `User` model:

| Atom | Covers |
|---|---|
| `can_manage_jobs` | Full CRUD on jobs, estimates, contacts, businesses; cancel/reorder tasks and mark all a job's work complete; email-to-job actions (link, unlink, create-job-from-email). (Add/edit/delete and complete *individual* tasks are open to any authenticated user — see below.) A Job's `project_manager` gets this atom's powers **scoped to that one job** (its tasks, estimates, change orders, deliverables, line items) via `CanManageJobOrPM` — but **not** contacts/businesses or job creation. |
| `can_manage_financials` | Full CRUD on invoices, POs, price list items, expenses, reimbursements (bill endpoints retired 2026-07-23 — bills live in QBO; the permission label string still says "bills", kept to avoid a migration) |
| `can_manage_time` | Edit/delete anyone's bleps (own bleps are `IsAuthenticated` within the 24h rolling window) |
| `can_manage_config` | Settings, templates, accounting categories, user admin, QBO connection |

**`IsAuthenticated` (no atom):** Read access to jobs, tasks, estimates, contacts, businesses, payment terms, templates, accounting categories, search, price list items, invoices, purchase orders, emails. Write access to notes on jobs/contacts/businesses, adding/editing/deleting (delete blocked when the task has Bleps or is in_progress/complete) and completing tasks on existing jobs, and submitting/tracking own time and expenses.

**`is_superuser` bypasses every atom check.**

Django Groups are not used; permissions are assigned per-atom on `user_permissions`. Full endpoint-to-atom table lives in `docs/designs/users-and-permissions.md` §3.

## Business Workflows

### Job Creation Flow
Job (tasks optionally generated from a WorkTemplate) → Estimate (wizard over the job's atoms) → accept crystallizes service hand-lines into Tasks → Time tracking (Bleps) → Job advances to `work_complete` when all tasks complete → Invoice

### Email-to-Job Workflow
1. Fetch emails from IMAP → EmailRecord + TempEmail. `TempEmail.text_body` / `html_body` cache the message body and `TempEmail.attachments_metadata` caches per-attachment filename/content_type/size so list views, `sender_info`, and the email-detail page render without re-hitting IMAP. `EmailService.get_email_content` falls back to IMAP only when `temp_data` is missing or the cache is incomplete (no body cached, or `has_attachments=True` with empty `attachments_metadata` — e.g. pre-backfill rows). Attachment payloads themselves are never cached.
2. Parse sender, extract company from signature
3. If contact exists → redirect to job creation with contact pre-selected
4. If not → session-based flow: create contact → optionally create/associate business (4 scenarios via dropdown) → create job → link EmailRecord to job

Key files: `apps/core/services.py` (EmailService), `apps/core/email_utils.py`, and the API viewsets/actions under `apps/api/` (emails, contacts, businesses, jobs). The email-to-job flow is now fully SPA + API driven — the SPA's `EmailCreateJobPage.svelte` calls `POST /api/emails/{id}/create-job/` plus `/api/contacts/` and `/api/businesses/`.

### Revision Workflow
Estimates support versioning via parent-child relationships (`POST /api/estimates/{id}/revise`). Old versions marked superseded.

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
- **Always pass `--noinput` to `manage.py test`.** A stale test database (left behind by any killed run) otherwise triggers an interactive delete prompt that hangs non-interactive shells forever. Both this rule and the no-parallel rule are **hook-enforced** (`.claude/hooks/check-django-test.sh`, wired in `.claude/settings.json`): a `manage.py test` command missing `--noinput`, or issued while another Django test run is alive, is denied before it executes — fix the command per the denial message and re-run.
- **NEVER judge test pass/fail by a piped command's exit code.** `python manage.py test ... | tail` (or any pipe) reports the *last* command's exit code (`tail`'s, always 0), NOT Django's — so a green-looking exit can hide real failures. To gate on results, read the actual `OK` / `FAILED (failures=…, errors=…)` summary line and the `Ran N tests` count from the output (e.g. write to a file and grep it, or run without a pipe so the exit code is Django's). This applies to background runs especially.
- **Front-end (Svelte SPA):** component/unit tests use Vitest, in `frontend/tests/`; run `npm run test:run` from `frontend/`. Extend TDD to the SPA — add/update a component's test in the same change. Patterns, conventions, and the behavior-vs-display triage live in `docs/designs/frontend-testing.md`.
- **E2E (Playwright):** full-stack browser tests in `e2e/`, driven from the `docs/ui-flows/` checklists, against a dedicated `minibini_e2e` DB rebuilt from migrations + the committed seed every run (never the dev DB). Run `npx playwright test` from `e2e/`; it starts its own servers on ports 8100/9100, so the dev stack can stay up. Setup, seed pipeline, personas, and spec conventions live in `docs/designs/e2e-testing.md`.
- **E2E is part of Definition of Done for new work and fixes** (RM, 2026-07-20): every change with a user-reachable flow ships an e2e spec in the same session, alongside (never instead of) its backend/Vitest tests. Do NOT backfill e2e for unchanged areas on your own initiative — RM commissions those explicitly. Pure-backend work with no browser-reachable surface is exempt; note the exemption rather than forcing a fake flow.

## Development Features

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

- Models: `apps/*/models.py` | Services: `apps/*/services.py` | Settings: `minibini/settings.py`
- API: `apps/api/*/views.py` (viewsets), `apps/api/*/serializers.py`, `apps/api/mixins.py`, `apps/api/permissions.py` | URLs: `apps/api/urls.py`, `apps/qbo/urls.py`
- PDF generation: `apps/{estimates,purchasing}/pdf.py` + the three `templates/**/*_pdf.html` (invoices attach QBO's rendered PDF)
- QBO OAuth (browser redirects, not the deleted HTML layer): `apps/qbo/views.py`
- Frontend: `frontend/src/` — `App.svelte`, `routes/`, `components/`, `stores/`, `lib/api.js`
- Topic reference docs: `docs/designs/` (nine files; see "Topic reference docs" above)
- Implementation plans (temporary working files): `docs/plans/` (disposable; deleted once shipped)

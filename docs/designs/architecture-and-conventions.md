# Architecture and Conventions

A reference for how Minibini is organized: backend service layer, REST API
shape and shared mixins, line item handling, the Svelte SPA, view-mode
toggle, history/notes, and sidebar nav. Read alongside `CLAUDE.md`, which
holds the prescriptive conventions (testing rules, status constants,
deletion rules, etc.) — this doc describes structure and patterns and
does not repeat that material.

---

## 1. Overview

Minibini is a Django 5 + DRF backend with a Svelte 5 SPA frontend. One
Django project, one HTTP origin, two consumers:

- The SPA at `frontend/` (Vite, served on `:9000` in dev, built to
  `dist/` for nginx in prod) is the primary UI for new work.
- A set of legacy server-rendered HTML views still live under `apps/*/views.py`
  and `templates/`. They are deprecated; new features are SPA-only.

Both call the same Django service layer through different transports:
HTML views call services directly; the SPA calls the REST API at `/api/`,
whose viewsets call the same services. No business logic lives in either
view layer.

---

## 2. Backend

### 2.1 App layout

See CLAUDE.md "Architecture" for the full app tree. The split is by
domain (jobs, estimates, contacts, invoicing, purchasing, inventory,
core) plus a single `apps/api/` app that owns the REST layer.

### 2.2 Service layer

Every model write goes through a service method in `apps/<app>/services.py`.
Views (HTML or API) never call `.save()` or `.delete()` on a tracked
model directly.

**Rules:**

- Services own business logic. Viewsets and HTML views are thin —
  parse input, call a service, render a response.
- Services accept primitives and IDs, return model instances
  ("primitives in, models out"). Views never load a model just to
  hand it to a service; the service does its own lookups.
- No forms or serializers cross the service boundary. Views extract
  `form.cleaned_data` or `serializer.validated_data` and pass plain
  kwargs.
- Services raise domain exceptions (`ServiceError`, `NotFoundError`,
  `SchemeSupersededError`). Views translate those into HTTP responses
  or Django messages.

The estimate and invoice wizards share their line-items-from-atoms logic
through `BaseWizardService` (`apps/core/wizard.py`):
`InvoiceWizardService` and `EstimateWizardService` subclass it, each
supplying a small config block (line-item/source models, atom types)
plus model hooks for the few genuine divergences.

**Exception hierarchy** (`apps/core/services.py`):

```python
class ServiceError(Exception):
    """Base exception for service-layer errors."""

class NotFoundError(ServiceError):
    """Raised when a requested object does not exist."""

class SchemeSupersededError(ServiceError):
    """Raised when a template referencing a superseded RateScheme is used."""
```

A typical create:

```python
class JobService:
    @staticmethod
    def create_job(*, name, contact_id, description='', customer_po_number=''):
        contact = Contact.objects.get(pk=contact_id)
        job = Job(name=name, contact=contact, description=description,
                  customer_po_number=customer_po_number)
        job.full_clean()
        job.save()
        return job
```

The viewset wires it up in `perform_create`:

```python
def perform_create(self, serializer):
    job = JobService.create_job(**serializer.validated_data)
    serializer.instance = job
```

**Job status changes — one chokepoint.** `JobService.update_job(pk, **kwargs)`
is the base update method: it applies the field changes *and* dispatches
status-transition side effects (the `work_complete` loose-materials gate,
earmark release on entry to `work_complete`/`cancelled`/`rejected`).
`JobService.update_status(pk, new_status)` is a thin wrapper over it. Every
Job status change is expected to flow through `update_job` — the status
pill's PATCH, the status-action endpoints, and the estimate- and
invoice-driven handlers all route through it, so side effects fire
regardless of caller.

### 2.3 Signals vs services

The codebase has not committed to a single pattern for cross-model side
effects. Two different conventions coexist:

- `apps/jobs/signals.py` — **0 lines**. Job status side effects are
  handled inside `apps/jobs/services.py`.
- `apps/estimates/signals.py` — three receivers
  (`estimate_status_changed_for_worksheet`, `estimate_status_changed_for_job`,
  `estimate_accepted`) that mutate worksheets and jobs when an estimate
  status changes. The job-status receiver routes its changes through
  `JobService.update_job` rather than mutating the Job directly.

This is undecided convention, not deliberate design. Either approach
works in isolation; mixing them makes it hard to reason about what
happens when a status changes. See "Unfinished work" below.

---

## 3. REST API

### 3.1 Directory structure

```
apps/api/
    urls.py                  # full URL tree, all includes in one place
    permissions.py           # atom-permission factory + the four atom classes
    pagination.py            # StandardPagination
    mixins.py                # StatusTransitionMixin, LineItemMixin,
                             # PlanTaskMixin, JobTaskMixin,
                             # JSONDestroyMixin, ConfirmDeleteMixin
    stubs.py                 # stub_501 factory
    auth/                    # session login/logout/me, password change, refresh stub
    bleps/                   # historical time entries
    contacts/                # Contact, Business, PaymentTerms
    email/                   # inbox, detail, link/unlink, create-job, send (stub)
    estimates/               # Estimate
    expenses/                # Expense (real, fully implemented)
    history/                 # HistoryEntrySerializer (no urls of its own;
                             #  feeds live on Job/Contact/Business viewsets)
    home/                    # home dashboard, current blep band
    inventory/               # PriceListItem, Material
    invoicing/               # Invoice
    jobs/                    # Job + board views
    plan_tasks/              # PlanTask (worksheet-side tasks)
    purchasing/              # PurchaseOrder, Bill
    rate_schemes/            # RateScheme
    reimbursements/          # expense reimbursement batches
    search/                  # SearchService dispatch
    tasks/                   # Task (job-side tasks)
    templates_config/        # WorkTemplate, TaskTemplate, AccountingCategory,
                             #  settings, units
    time_tracking/           # urls only — all routes return 501
    users/                   # User admin (CRUD, deactivate, reset password)
    worksheets/              # EstWorksheet
```

The `WorkOrder` model has been removed; Tasks live directly on `Job`.
See `docs/designs/jobs-tasks-and-worksheets.md` for the task-on-job
shape.

### 3.2 Authentication

Session auth only. Configured in `settings.py` with DRF's
`SessionAuthentication` as the sole backend. The dev autologin
middleware (which sets `request.user` on the session) works
transparently. The frontend never sees a JWT — see `frontend/src/lib/api.js`,
which only handles the CSRF cookie.

`apps/api/auth/views.py` implements:

- `POST /api/auth/login/` — credentials → session cookie + user JSON
- `POST /api/auth/logout/`
- `GET, PATCH /api/auth/me/` — current user; PATCH updates own profile
- `POST /api/auth/me/password/` — change own password
- `GET /api/auth/users/` — active users for assignee dropdowns
- `POST /api/auth/refresh/` — 501 stub (placeholder for JWT)

### 3.3 Pagination

`apps/api/pagination.py`:

```python
class StandardPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100
```

Page-number pagination, default 25, max 100, override per request via
`?page_size=N`. Set globally as `DEFAULT_PAGINATION_CLASS`. Some
viewsets disable it (e.g., `UserViewSet` sets `pagination_class = None`).

### 3.4 Mixin catalog

All in `apps/api/mixins.py`.

| Mixin | Used by | One-line description |
|---|---|---|
| `StatusTransitionMixin` | Every document viewset | Auto-registers `@action` POST endpoints from a `status_actions` dict, with optional `requires_reason` validation and HistoryEntry attachment. |
| `LineItemMixin` | EstimateViewSet, InvoiceViewSet, PurchaseOrderViewSet, BillViewSet | Adds `line-items/`, `line-items/{id}/`, `line-items/reorder/` actions; delegates all writes to `line_item_service_class`. |
| `PlanTaskMixin` | EstWorksheetViewSet | Adds `tasks/`, `tasks/{id}/` actions for `PlanTask` (worksheet-side). |
| `PlanTaskBundleMixin` | n/a | Backwards-compat alias for `PlanTaskMixin`; remove after callers update. |
| `JobTaskMixin` | JobViewSet | Adds `tasks/`, `tasks/{id}/` actions for `Task` (job-side); calls `TaskService.create_direct` / `delete_task`. |
| `JSONDestroyMixin` | JobViewSet, BillViewSet, PriceListItemViewSet, WorkTemplateViewSet, TaskTemplateViewSet, AccountingCategoryViewSet | Overrides DRF's default destroy() to return 200 with `{'message': ...}` instead of 204; subclasses set `destroy_response_message`. |
| `ConfirmDeleteMixin` | ContactViewSet, BusinessViewSet, ReimbursementViewSet | Two-phase delete; first DELETE returns `{'confirm_required': True, 'impact': {…}}`, DELETE with `?confirm=true` runs the delete. Subclasses implement `get_deletion_impact(obj)` and `perform_confirmed_destroy(obj)`. |

`StatusTransitionMixin.status_actions` shape:

```python
status_actions = {
    'mark-open': {'service': EstimateService.mark_open},
    'cancel':    {'service': BillService.cancel,
                  'requires_reason': True},
}
```

The mixin creates a POST action at `/{action_name}/` for each entry. If
`requires_reason` is true, the request body must include a non-empty
`reason`; the mixin attaches it to the most recent audit `HistoryEntry`
for the object (or creates a standalone audit entry if none was
generated by the service call).

### 3.5 Permissions

Four permission atoms on `User`, exposed as DRF permission classes via a
factory in `apps/api/permissions.py`:

```python
def atom_permission(perm_codename):
    class AtomPermission(BasePermission):
        def has_permission(self, request, view):
            return request.user.has_perm(f'core.{perm_codename}')
    AtomPermission.__name__ = perm_codename
    return AtomPermission

CanManageJobs       = atom_permission('can_manage_jobs')
CanManageFinancials = atom_permission('can_manage_financials')
CanManageTime       = atom_permission('can_manage_time')
CanManageConfig     = atom_permission('can_manage_config')
```

Default for everything else: `IsAuthenticated`. See CLAUDE.md
"Permissions" for the full atom-to-action mapping and the default
groups.

Viewsets check by overriding `get_permissions()`:

```python
def get_permissions(self):
    if self.action in ('list', 'retrieve'):
        return [IsAuthenticated()]
    return [IsAuthenticated(), CanManageJobs()]
```

A few endpoints split read/write within an action — the `tasks` action
on `JobViewSet` is `IsAuthenticated` for GET but requires `CanManageJobs`
for POST (see `apps/api/jobs/views.py`).

### 3.6 DELETE responses are 200 with JSON

Convention: every DELETE returns HTTP 200 with a JSON body (e.g.
`{'message': '... deleted.'}`), never 204. The frontend
`api.js` rejects any non-JSON response, so a default DRF 204 is
a runtime error in the SPA.

**Viewsets that comply** (override `destroy()` to return JSON, or use `JSONDestroyMixin`):

- `EstimateViewSet` — `apps/api/estimates/views.py`
- `InvoiceViewSet` — `apps/api/invoicing/views.py`
- `EstWorksheetViewSet` — `apps/api/worksheets/views.py`
- `PurchaseOrderViewSet` — `apps/api/purchasing/views.py`
- `ContactViewSet` — `apps/api/contacts/views.py`
- `BusinessViewSet` — `apps/api/contacts/views.py`
- `ReimbursementViewSet` — `apps/api/reimbursements/views.py`
- `BlepViewSet` — `apps/api/bleps/views.py`
- `RateSchemeViewSet` — `apps/api/rate_schemes/views.py`
- `ExpenseViewSet` — `apps/api/expenses/views.py`
- `JobViewSet` — `JSONDestroyMixin`
- `BillViewSet` — `JSONDestroyMixin`
- `PriceListItemViewSet` — `JSONDestroyMixin`
- `WorkTemplateViewSet` — `JSONDestroyMixin` (plus `perform_destroy` for service call)
- `TaskTemplateViewSet` — `JSONDestroyMixin` (plus `perform_destroy` for service call)
- `AccountingCategoryViewSet` — `JSONDestroyMixin`
- `MaterialViewSet` — returns 405 (top-level material delete is disallowed)
- `UserViewSet` — raises `MethodNotAllowed` (use deactivate)

### 3.7 Two-phase delete confirmation

For objects with cascading impact, the first DELETE returns an impact
summary instead of deleting; a second DELETE with `?confirm=true`
executes:

```
DELETE /api/contacts/5/
  → 200 {"confirm_required": true, "impact": {"jobs": 3}}

DELETE /api/contacts/5/?confirm=true
  → 200 {"message": "\"Jane Doe\" has been deleted."}
```

Implemented via `ConfirmDeleteMixin` in `apps/api/mixins.py`. Three
viewsets use it today:

- `ContactViewSet` — `apps/api/contacts/views.py`
- `BusinessViewSet` — `apps/api/contacts/views.py`
- `ReimbursementViewSet` — `apps/api/reimbursements/views.py`

Each one implements `get_deletion_impact(obj) -> dict` and
`perform_confirmed_destroy(obj) -> Response`; the mixin handles the
`?confirm=true` ceremony.

The contact/business impact queries currently live inline in the
viewset (`Job.objects.filter(contact=contact).count()` etc.) — those
queries should move to the service layer; viewsets shouldn't be poking
the ORM directly.

### 3.8 501 stub policy

Endpoints that have a planned URL but no implementation return 501 with
a JSON body: `{'detail': 'Not yet implemented.', 'endpoint': '<METHOD> <path>'}`.
The factory is `apps/api/stubs.py:stub_501`.

**Currently registered stubs:**

- `POST /api/auth/refresh/` — `apps/api/auth/views.py` (JWT placeholder)
- `POST /api/emails/send/` — `apps/api/email/urls.py`
- `POST /api/shifts/clock-in/` — `apps/api/time_tracking/urls.py`
- `POST /api/shifts/clock-out/` — `apps/api/time_tracking/urls.py`
- `GET /api/time-tracking/status/` — `apps/api/urls.py`
- `GET /api/time-tracking/active/` — `apps/api/urls.py`

`/api/expenses/` is fully implemented (`ExpenseViewSet` in
`apps/api/expenses/views.py`); it is not a stub.

---

## 4. Line item API pattern

Four entities have line items (Estimate, Invoice, PurchaseOrder, Bill).
All use `LineItemMixin` and route every write through a service class.

A viewset wires up the mixin with three attributes:

```python
class EstimateViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    line_item_serializer_class = EstimateLineItemSerializer
    line_item_parent_field = 'estimate'         # FK name on the line item
    line_item_service_class = EstimateService    # service that owns writes
```

The mixin then exposes:

| Verb + path | Mixin method | Calls |
|---|---|---|
| `GET /{id}/line-items/` | `line_items` | direct query, ordered by `line_number` |
| `POST /{id}/line-items/` | `line_items` | `service.add_line_item_from_pli` if `price_list_item` is supplied without manual fields, else `service.add_line_item` |
| `PATCH /{id}/line-items/{item_id}/` | `line_item_detail` | `service.update_line_item` |
| `DELETE /{id}/line-items/{item_id}/` | `line_item_detail` | `service.delete_line_item` |
| `POST /{id}/line-items/reorder/` | `reorder_line_items` | `service.reorder_line_items` |

Each service class must provide: `add_line_item`, `add_line_item_from_pli`,
`update_line_item`, `delete_line_item`, `reorder_line_items`. Each
enforces its own status guard (typically draft only); the mixin doesn't
know what statuses are editable.

`BaseLineItem.save()` has a `_populate_from_pli` safety net that fills
in description/units/price/category from a linked `PriceListItem` if
they're missing — the model's last line of defence in case some new
code path bypasses the service.

Line item deletion: never call `.delete()` on a line item directly.
Always go through `LineItemService.delete_line_item_with_renumber()`
(or the entity service's `delete_line_item`, which delegates to it),
because plain delete leaves gaps in `line_number`. See CLAUDE.md
"Code Conventions" for the rule.

---

## 5. Frontend (Svelte SPA)

### 5.1 Tech and runtime

- Svelte 5 with runes (`$state`, `$derived`, `$effect`, `$props`,
  `$bindable`).
- Vite dev server on `:9000` proxying `/api/*` to Django on `:8000`;
  prod build emits `dist/` served by nginx.
- Hash-based routing via `svelte-spa-router`.
- No CSS framework; semantic HTML and per-component `<style>` blocks.

### 5.2 API client

`frontend/src/lib/api.js` is the only thing that talks to Django.

- Reads CSRF token from the `csrftoken` cookie, sends it as
  `X-CSRFToken` on every mutating request.
- `credentials: 'same-origin'` carries the session cookie.
- Asserts every response has `Content-Type: application/json` — a
  non-JSON response throws `Server error (status)`. This is why every
  API endpoint must return JSON, including DELETE.
- Exposes `api.get/post/patch/put/delete`. DELETE may take a body
  (used by the PO destroy flow's `sever_decisions`).

### 5.3 Stores

`frontend/src/stores/`:

- `auth.js` — `user` + `authChecked` writables, `checkAuth()`,
  `login()`, `logout()`. `App.svelte` calls `checkAuth()` on mount and
  shows `LoginPage` if `$user` is null.
- `viewMode.js` — see §6.
- `currentBlep.js` — currently-running time entry, polled and shown in
  the `CurrentBlepBand`.

### 5.4 Routing

`App.svelte` declares the route table and mounts `<Router routes={routes} />`
inside the auth gate. Routes are page components under
`frontend/src/routes/<domain>/<PageName>.svelte`. Reusable pieces live
in `frontend/src/components/`.

### 5.5 Style scoping gotcha (and a small footgun)

Svelte scopes component `<style>` blocks per component. Class selectors
defined in one component's `<style>` are silently invisible to the DOM
rendered by another component, even when the class name matches.

Concrete example we hit: `JobDetail.svelte` defines `.panel`,
`.panel-head`, `.panel-scroll` for the Description / History card
chrome. When `DeliverablesSection.svelte` was added as a sibling card,
its outer element used `class="panel deliverables-panel"`, but the
panel chrome did not render — the white card, border, rounded corners,
and uppercase header treatment all came from JobDetail's scoped
classes, which don't reach a child component's elements. Result: a
borderless, unstyled list.

Workaround in place today: copy the relevant rules into the child
component's own `<style>` block (`DeliverablesSection.svelte` now owns
its own `.panel` / `.panel-head` / `.panel-scroll` rules). This works
but duplicates the styling, so the components can drift.

Better long-term fix (deferred): extract shared UI chrome (panel
shapes, common section heads, etc.) into a global stylesheet, or use
`:global(.panel) { ... }` once in a "host" component. We have not
audited which selectors deserve this treatment yet. When the styling
layer is reorganized, this is the first item on the list.

Rule of thumb when working on a new SPA component: if you reuse a
class name from another component and the styling vanishes, this is
the cause. Either copy the rule in, or promote it to global.

---

## 6. View mode (full / lite)

Two-axis design: **content density** (lite vs. full) is independent of
**layout/styling** (responsive CSS). The store handles density only;
layout is per-component CSS.

The bigger lite-mode design — what each page actually shows in lite,
how aggressively to hide things, the toggle's permanent home — is
deferred pending real user feedback. Today's behavior (sparse
`<FullOnly>` adoption, sidebar-mounted toggle, `localStorage`
persistence) is intentionally minimal until that feedback exists.

### 6.1 Store

`frontend/src/stores/viewMode.js` — Svelte writable, defaults to
`'lite'`, persisted to `localStorage` under `minibini_view_mode`.
`toggleViewMode()` flips between `'full'` and `'lite'`.

```javascript
const stored = localStorage.getItem(STORAGE_KEY) || 'lite';
export const viewMode = writable(stored);
viewMode.subscribe((value) => localStorage.setItem(STORAGE_KEY, value));
```

Persistence is client-side only. Future work: store as a user
preference fetched from the API on load.

### 6.2 The `<FullOnly>` wrapper

`frontend/src/components/FullOnly.svelte`:

```svelte
<script>
  import { viewMode } from '../stores/viewMode.js';
  const { children } = $props();
</script>

{#if $viewMode === 'full'}
  {@render children()}
{/if}
```

Convention: wrap full-mode-only sections in `<FullOnly>` rather than
checking `$viewMode` in business components.

Adoption is sparse — currently only two consumers
(`components/contacts/BusinessDetail.svelte`,
`components/contacts/ContactDetail.svelte`). Other components either
predate the convention or check `$viewMode` directly (e.g.,
`HistoryPanel.svelte` filters its timeline based on `$viewMode === 'lite'`).

### 6.3 Toggle location

The view-mode toggle currently lives at the bottom of the sidebar
(`components/Sidebar.svelte`), shown as `LITE | FULL` with the
active state in white. The original sidebar spec called for relocating
it to a user profile page — that move hasn't happened.

---

## 7. History and notes

### 7.1 Model

`apps/core/models.py` — `HistoryEntry` with three entry types:

- `audit` — automatic field-change tracking (decorated models)
- `action` — system-generated state changes from signals/services
- `note` — user-written free text

`object_type` (lowercased class name) + `object_id` link entries to any
model — no `GenericForeignKey`. `db_table = 'history'`. Ordered newest
first.

`changes` is a JSON field with field diffs (`{"status": {"old": "draft",
"new": "open"}}`) plus underscore-prefixed metadata keys: `_created`
(true on first save) and `_action` (system-generated description).
`text` is reserved for human-entered text only — never put a
system-generated description in `text`.

### 7.2 Tracked models

Models opt in with `@history(exclude=[...])` from `apps/core/history.py`:

- `Contact`, `Business` — `apps/contacts/models.py`
- `Job` — `apps/jobs/models.py`
- `Estimate`, `EstWorksheet` — `apps/estimates/models.py`
- `Invoice` — `apps/invoicing/models.py`
- `PurchaseOrder`, `Bill` — `apps/purchasing/models.py`

Excluded fields don't appear in `changes`; if they were the only fields
that changed, no entry is created.

### 7.3 Change capture

`apps/core/history.py` uses Django signals plus a `contextvars.ContextVar`:

- `post_init` (`_on_post_init`) — snapshots a tracked instance's field
  values to `instance._history_original` when it loads from the DB.
- `pre_save` (`_on_pre_save`) — diffs current values against the
  snapshot and either appends to the request-scoped pending list (if
  inside a request) or writes a `HistoryEntry` immediately (outside a
  request).
- `post_save` (`_on_post_save`) — for new objects saved outside a
  request, writes the deferred history entry now that `pk` exists; also
  re-snapshots so subsequent edits diff correctly.

Middleware (set up at request start) puts a `HistoryContext` into the
ContextVar with `request.user` and an empty pending list, then after the
view drains the list into `HistoryEntry` rows. If the request errored
or its transaction rolled back, the entries are dropped.

`get_history_context()` / `set_history_context(ctx)` are the public
hooks. `StatusTransitionMixin` uses them to attach a status-change
reason to the most recent pending audit entry
(`apps/api/mixins.py`).

**Important** (also in CLAUDE.md): never use `QuerySet.update()` on
tracked models — it bypasses signals. Always load and `.save()`.

### 7.4 Endpoints

History feeds (paginated, newest first):

- `GET /api/jobs/{id}/history/` — aggregates the job plus any related
  estimates, worksheets, and invoices (`apps/api/jobs/views.py`).
- `GET /api/contacts/{id}/history/` — single object.
- `GET /api/businesses/{id}/history/` — business plus its contacts.

Notes (write-only, immutable):

- `POST /api/jobs/{id}/notes/`
- `POST /api/contacts/{id}/notes/`
- `POST /api/businesses/{id}/notes/`

No PATCH or DELETE on notes — a new note may textually reference an old
one if needed.

### 7.5 Frontend

`frontend/src/components/HistoryPanel.svelte` renders a merged timeline
of `HistoryEntry` rows and `EmailRecord` rows for the same object. In
lite mode it filters to emails plus history entries that have free-text
content (`entry.data.text`); full mode shows everything.

---

## 8. Sidebar nav

`frontend/src/components/Sidebar.svelte` is the nav for every SPA page.
Always-visible 44x44 hamburger icon pinned top-left, dark
`#1a3344` background. Hover the hamburger or sidebar to open; ~300 ms
delay before close on mouseleave. 120 px wide, overlay behavior — the
sidebar is `position: fixed` / `z-index: 999` and slides in on top of the
page (0.25 s ease) without shifting content.

**Link list** (in order):

```
Home
Jobs               → /jobs/board
Contacts
Email
Purchasing         → /purchase-orders
─── Admin ───      (label only if user has any admin perm)
Expenses           (can_manage_financials)
Users              (can_manage_config)
Settings           (can_manage_config)
[spacer]
LITE | FULL        (view-mode toggle)
─────────────
<username>         → /profile
Logout
```

Django server-rendered pages (`templates/base.html`) keep their own nav
and are unchanged.

---

## 9. Unfinished work

Concrete items, smallest first:

- **Move impact queries into services.** `ContactViewSet.get_deletion_impact`
  and `BusinessViewSet.get_deletion_impact` currently run
  `Job.objects.filter(...)` directly to compute the impact dict. That
  belongs on the service.

- **Lite-mode rollout** (deferred pending user feedback). Once the
  shape of lite mode is decided, expect: server-side persistence of
  the per-user preference (currently `localStorage`-only), wider
  `<FullOnly>` adoption (only two components use it today), and a
  decision on the toggle's permanent home.

- **Pick a signals-vs-services convention.** `apps/jobs/signals.py` is
  empty; `apps/estimates/signals.py` is 123 lines. Decide on one
  pattern and document it in CLAUDE.md.

- **Negative-price sanity check on line items.** All four line-item
  subclasses (Estimate, Invoice, PO, Bill) accept any decimal price
  with no validation. Negative values are legitimate (discount lines,
  credits), but typos that flip a sign go through silently. A serializer-
  or service-level warning (not a hard reject) would catch obvious
  mistakes. Concern is shared across all four subclasses since it lives
  on `BaseLineItem`.

- **`accounting_category` required on all four line-item subclasses
  (`EstimateLineItem`, `InvoiceLineItem`, `PurchaseOrderLineItem`,
  `BillLineItem`).** Currently nullable (inherited from
  `BaseLineItem`); a null AC falls back to silently tax-exempt at QBO
  push time. Should become NOT NULL after existing rows are backfilled.
  One project-wide migration across all four subclasses — the change
  lives in `apps/core/models.py` (`BaseLineItem`) plus a backfill step
  per subclass.

- **Decommission deprecated HTML views opportunistically.** Full
  CRUD HTML views still live in `apps/contacts/views.py`,
  `apps/estimates/views.py`, `apps/jobs/views.py`, and
  `apps/invoicing/views.py`. They overlap with SPA routes that
  already cover the same entities and can drift from them.

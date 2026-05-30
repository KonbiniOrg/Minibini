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

### 5.6 Preserving line breaks in free-text fields

Large free-text fields (`TextField`s — descriptions, notes, reasons,
addresses) let users type paragraphs. Default HTML rendering collapses
their newlines, so paragraph formatting is lost on display.

Convention: wherever such a field is shown **in full**, apply the
global `.preserve-breaks` utility class. It is `white-space: pre-wrap`,
defined once per stack so both share the same mechanism:

- `frontend/src/css/app.css` — SPA (global, reaches every component;
  not subject to the §5.5 scoping gotcha).
- `templates/base.html` — Django HTML views.
- `templates/purchasing/purchase_order_pdf.html` — standalone PDF
  template with its own `<style>`, so it carries its own copy.

`pre-wrap` is preferred over swapping `\n` for `<br>` via `{@html}`:
the text stays auto-escaped (no XSS), long lines still wrap, and it's
one class instead of an escape-then-replace helper.

Two rules when applying it:

- `pre-wrap` also preserves whitespace from the **HTML source**. If the
  field hugs its element on one line (`<td>{x.description}</td>`), tag
  that element. If the field shares an element with other content (a
  label, badges, conditional spans on separate source lines), wrap
  **just the field** in a tight `<span class="preserve-breaks">{x}</span>`
  so source indentation isn't rendered.
- Skip it where the field is truncated/sliced or shown as a short
  inline suffix (pickers, breadcrumbs, `truncatewords`, `{name} —
  {description}` rows) — there's no paragraph to preserve and multi-line
  output would break compact layouts.

### 5.7 Modal keyboard shortcuts (Enter / Escape)

Editing and confirmation modals support **Enter = primary action (Save /
confirm)** and **Escape = cancel**, via the shared action
`frontend/src/lib/modalKeys.js`. Attach it to the modal's overlay /
backdrop element so the window-level key listener lives exactly as long
as the modal is on screen (the element only exists inside `{#if open}`,
so the listener auto-detaches on close and idle modals don't stomp each
other):

```svelte
<div class="overlay" use:modalKeys={{ onSave: save, onCancel: onClose }}>
```

`onSave` / `onCancel` are the caller's hooks — put any guards there, e.g.
`onSave: () => { if (!busy) save(); }` so Enter can't double-submit while
a request is in flight (Enter bypasses the `disabled` Save button).

Enter is intercepted only when focus is **not** in a `<textarea>` or
contenteditable region (so multi-line fields keep inserting newlines — see
§5.6), **not** on a `<button>` (so a focused Save/Cancel isn't double-fired),
and not mid-IME-composition.

Two modes:

- **Enter + Escape** (most modals): pass both `onSave` and `onCancel`.
- **Escape only**: omit `onSave`. Do this when a native `<form>` already
  submits on Enter (binding it here too would double-fire — the action
  won't even `preventDefault` Enter without an `onSave`, so the form's
  native submit survives), or when the primary action is ambiguous /
  irreversible (several action buttons, e.g. `StartWorkConflictModal`'s
  Join vs. Take over). `SendPODialog` is form-driven, so it's Escape-only.

For a confirm sub-step inside a modal (e.g. `MaterialModal`'s "update
PLI?" prompt), gate the hooks on that state: make `onSave` inert while the
sub-step shows, and have `onCancel` dismiss the sub-step first, falling
through to closing the whole modal only once it's gone.

### 5.8 Linkifying URLs in free-text fields

URLs pasted into descriptions / line items are turned into clickable links
by `<LinkifiedText>` (`frontend/src/components/LinkifiedText.svelte`), backed
by the pure tokenizer in `frontend/src/lib/linkify.js`. Drop it *inside* an
existing `.preserve-breaks` wrapper so it inherits newline preservation and
the long-token wrap (§5.6):

```svelte
<p class="preserve-breaks"><LinkifiedText text={job.description} /></p>
```

**Matching rule** (`linkify(text)` → text/url segments): a token links iff it
starts with `http://`/`https://` **and** its host contains a dot. So
`https://example.com/x` and `https://www.example.com` link, while
`http://intra/wiki` and `http://localhost:8000` stay plain (no dot in host),
as do scheme-less `example.com` and `drawing.pdf`. The required scheme keeps
false positives near zero, so there's no TLD allowlist to maintain. Trailing
sentence punctuation (`.,;:!?)]}'"`) is trimmed back out of the match.

**Display** (`truncateUrl(url)`, the segment's `display`): scheme dropped,
full host + up to 8 characters of the path/query, then `…` only if there's
more — e.g. `example.com/files/r…`, `example.com/x`, `example.com`. The full
URL stays in the anchor's `href` and `title` (hover). Links open in a new tab
with `rel="noopener noreferrer"`.

**Safety:** segments render as Svelte nodes (auto-escaped text, `<a>` for
URLs) — never `{@html}` — so it's XSS-safe by construction, same discipline
as §5.6.

**Applied at:** Job / Task / PlanTask descriptions and billing line-item
descriptions (`LineItemTable`, `JobDetail` invoice + PO lines,
`PurchaseOrderDetail`). Other free-text fields (notes, addresses, material
descriptions) get the §5.6 wrap but are not linkified.

**Layout note:** a long unbreakable token (URL) in a CSS grid/flex column
won't shrink the track unless the item has `min-width: 0`. The job-overview
midband sets `.midband > * { min-width: 0 }` for this; pair `overflow-wrap:
anywhere` (now part of `.preserve-breaks`) with `min-width: 0` anywhere a
free-text field sits in a grid/flex track.

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
`HistoryPanel.svelte` filters history entries based on `$viewMode === 'lite'`).

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

`frontend/src/components/HistoryPanel.svelte` renders a history-only
timeline of `HistoryEntry` rows for an object. In lite mode it filters
to entries with free-text content (`entry.data.text`); full mode shows
everything. The component is currently unmounted from the Job overview
pending a redesign — `EmailPanel.svelte` occupies that slot today (see
§7.6) — but the component itself is still wired and works for any
caller that passes it `{ history, onAddNote }`.

### 7.6 Email panel on the Job overview

`frontend/src/components/EmailPanel.svelte` renders the email list in
the bottom-right pane of the Job overview, mounted by `JobDetail.svelte`
where `HistoryPanel.svelte` used to live. Two-line cards: row 1 is
`<date> <direction-glyph> <display_address> <subject>`, row 2 is the
`snippet`. Outbound rows get a tinted background. The whole card is an
`<a>` to `#/email/<email_record_id>`.

The component consumes the same paginated `/api/emails/?job=<id>`
response the rest of the SPA uses. The serializer now exposes three
fields specifically for this view (`apps/api/email/serializers.py`):

- `direction` — `'inbound' | 'outbound'`. Hard-coded `'inbound'` today;
  outbound tracking is a deferred follow-up but the data shape is in
  place.
- `display_address` — sender for inbound, first recipient for outbound.
- `snippet` — 80-char preview derived from the cached body
  (`text_body`, or `html_body` with HTML tags stripped), passed through
  `strip_quoted_reply` and whitespace-collapsed. Empty string when
  `temp_data` has been purged.

### 7.7 IMAP cache on `TempEmail`

`TempEmail` caches the parts of an email that list and detail views
need so the SPA can render without re-hitting IMAP:

- `text_body` / `html_body` — message body (used by the Email panel
  snippet, `sender_info`, and the detail page).
- `attachments_metadata` — JSON list of
  `{filename, content_type, size}` per attachment (used by the detail
  page's attachment list).

`EmailService.fetch_emails_by_date_range` / `fetch_new_emails`
populate all three fields when they create the `TempEmail` row (helper
`_attachments_metadata` builds the list).
`EmailService.get_email_content` returns a cache-only dict when both
the body and the attachment list are available; it falls back to IMAP
when (a) `temp_data` is missing entirely or (b) the cache is
incomplete — either no body cached, or `has_attachments=True` with an
empty `attachments_metadata` (pre-backfill rows). Attachment payload
bytes are never cached and are not part of the JSON response; the
future per-attachment download endpoint re-fetches them by UID. Cached
bodies/metadata are purged alongside the rest of `TempEmail` per the
existing retention policy (`email_retention_days`).

### 7.8 Email detail action panel

`EmailRecord` has three independent association FKs — `job`,
`purchase_order`, and `bill`, all `on_delete=SET_NULL`. Any
combination is valid; the user chooses which apply per email.

`frontend/src/components/email/EmailActionPanel.svelte` is the
right-rail side panel on the email detail page (`EmailDetailPage.svelte`
lays out content + rail in a two-column flexbox). One section per
target (Job, Purchase Order, Bill). When the email is linked to that
target the section shows the linked entity as a navigation link plus a
Disassociate `<button>`; when unlinked it shows two `<a>`s styled like
buttons — *Create new* and *Link existing* — that route to the
respective Create-from-Email and Associate-with-Existing pages. Each
section is hidden when the viewer lacks the relevant permission atom
(`can_manage_jobs` for the Job section; `can_manage_financials` for
PO and Bill).

The Create-from-Email pages share `SenderResolutionForm.svelte`
(`frontend/src/components/email/`), the sender-info + contact-picker /
new-contact-form + business-mode sub-flow. The form owns the visual
block and the resolution state (bound via `$bindable`); the
`resolveSenderToContact(state)` helper in `lib/email.js` turns that
state into `{contactId, businessId}` by making the necessary
`/api/contacts/` and `/api/businesses/` POSTs on submit. The constraint
that drove this shape: `Business.default_contact` is a required FK, so
every Create flow that produces a vendor Business naturally produces
a Contact alongside it. The placeholder name "PO receiver" (or
similar) is acceptable when no real sales rep is involved.

SPA routes registered in `App.svelte`:

- `/email/:id/create-job` → `EmailCreateJobPage.svelte`
- `/email/:id/create-po` → `EmailCreatePOPage.svelte`
- `/email/:id/create-bill` → `EmailCreateBillPage.svelte` (resolves the
  Contact+Business, then navigates to `#/bills/new?email=&vendor=` —
  the actual Bill creation page is future work)
- `/email/:id/associate` → `EmailAssociatePage.svelte` (Job picker)
- `/email/:id/associate-po` → `EmailAssociatePOPage.svelte`
- `/email/:id/associate-bill` → `EmailAssociateBillPage.svelte`

`EmailRecordSerializer` exposes `job` + `job_number`,
`purchase_order` + `po_number`, and `bill` + `vendor_invoice_number`
read-only so the panel can render linked-entity labels without extra
fetches.

### 7.9 `EmailService` association helpers

`EmailService.associate_with(email_pk, target_field, target_pk)` and
`disassociate_from(email_pk, target_field)` are parameterized over the
three target fields (`'job'`, `'purchase_order'`, `'bill'`), validated
against an allowlist. The five Email-action API endpoints
(`link-to-job` / `unlink-from-job` / `link-to-po` / `unlink-from-po` /
`link-to-bill` / `unlink-from-bill`) route through these via a
`_link_email_to(target_field, body_key, …)` / `_unlink_email_from`
helper pair in `apps/api/email/views.py` so the six views are
one-liners. `EmailService.associate_with_job` and
`disassociate_from_job` remain as backwards-compatible shims that
delegate to the parameterized pair; callers that already used the
job-specific names keep working unchanged.

### 7.10 Outbound email tracking

Outbound documents (Estimate / PO / Invoice send) persist an
`EmailRecord` with `direction='outbound'` at send time. The flow is
owned by `OutboundEmailService.send_tracked` in `apps/core/services.py`:

1. Generate a Message-ID we control —
   `<minibini-<uuid4-hex>@<our_domain>>` — where `our_domain` is the
   eponymous Configuration key (default `example.com` until tenancy
   lands). Set as the outgoing message's `Message-ID` header so
   customer replies' `In-Reply-To` round-trips back to a row we own.
2. Persist the `EmailRecord` (direction=outbound, message_id, the
   association FK passed in `associate_with={'job'|'purchase_order'|
   'bill': obj}`) + a `TempEmail` row holding the composed
   subject/from/to/cc/bcc/body and the attachments_metadata. Both
   committed in a single transaction *before* SMTP runs.
3. Call `EmailMessage.send()`. On success, set `sent_at=now()`. On
   failure, save the exception's message into `last_send_error` and
   re-raise — the row persists for the user to retry.
4. Retry semantics: `send_tracked` finds the most recent
   `direction='outbound', sent_at=null` row for the same target and
   reuses it (same `message_id`, updated body/subject/etc from the
   current call). PDFs are regenerated on every attempt; user
   uploads come from the multipart POST. No drafts.

The per-document send services that wrap this:
- `EstimateEmailService` (`apps/estimates/services.py`) — generates
  the PDF, calls `send_tracked` with `associate_with={'job': …}`,
  transitions `draft → open` on send success.
- `PurchaseOrderEmailService.send_po` (`apps/purchasing/services.py`)
  — same shape but `associate_with={'purchase_order': …}` and
  `draft → issued`.
- `InvoiceEmailService.send_invoice` (`apps/invoicing/services.py`)
  — adds the QBO push step before SMTP (skipped if `invoice.qbo_id`
  is already set — fixes the duplicate-push-on-retry bug),
  auto-attaches both the QBO-rendered invoice PDF and the local Job
  Statement PDF, transitions `draft → open`.

Body / subject templates live as `Configuration` keys
(`estimate_email_subject_template`, `estimate_email_body_template`,
`po_email_*`, `invoice_email_*`). Rendering goes through
`apps.core.email_templates.render_email_template` — a safe
`str.format_map` wrapper that leaves unknown `{placeholders}`
literal so user-edited templates can't crash a send. Variables shared
across all three document types: `{contact_fname}`, `{contact_lname}`,
`{contact_business}`, `{our_user_name}`, `{our_business_name}`,
`{job_number}`, `{job_name}`, `{document_number}`. Per-document
aliases (`{estimate_number}`, `{po_number}`, `{invoice_number}`,
`{vendor_name}`) also work.

### 7.11 Reply correlation

`EmailService.correlate_reply(email_record)` runs at the tail of
`fetch_new_emails` and `fetch_emails_by_date_range`, after the
inbound `EmailRecord` + `TempEmail` are created. It walks
`TempEmail.in_reply_to` first, then the `references` chain
right-to-left, looking up each token against existing
`EmailRecord.message_id`. The first parent found wins; its non-null
`job` / `purchase_order` / `bill` FKs are copied onto the new reply
EmailRecord. Behavior is silent — no "auto-linked via reply" badge;
the action panel's existing Disassociate handles any mis-correlated
auto-links.

The `TempEmail` rows that drive this gain three columns:
`in_reply_to` (CharField, captures the immediate parent's
Message-ID), `references` (TextField, captures the full thread
chain), and `bcc_email` (TextField, populated only on outbound rows
since IMAP-fetched inbound can't see BCC).

### 7.12 SPA send pages

The send compose surface is a per-document route
(`/estimates/:id/send`, `/purchase-orders/:id/send`,
`/invoices/:id/send`). Each wraps the shared
`frontend/src/components/email/DocumentSendForm.svelte` (To / CC /
BCC / Subject / Body / Attachments-with-remove-checkboxes /
Add-attachment / Send button with native `confirm()`), fetches its
own `send-defaults` for prefill, and renders a focused read-only
document summary below the form. Submit POSTs as
`multipart/form-data` via `api.postMultipart()` in `lib/api.js` —
the new sibling of the JSON `api.post()`.

### 7.13 Reply composer

The reply composer is inline on the email detail page —
`EmailReplyComposer.svelte` mounted by `EmailDetailPage.svelte` above
the original `EmailContent` when the user clicks Reply or Reply All in
the right-rail `EmailActionPanel`. The page tracks a small
`replyMode = $state(null)` (one of `null | 'reply' | 'reply-all'`); the
action panel's Reply / Reply All buttons set it via an `onReply(mode)`
callback prop. The right rail uses `position: sticky` so the action
panel (Job / PO / Bill associations + Reply controls) stays visible
while the user scrolls between the compose form and the original
email below it.

`EmailReplyComposer` owns the form state (to / cc / bcc / subject /
body / extraFiles) directly and binds it into `DocumentSendForm`
via `$bindable` props. Mid-compose mode switching (clicking Reply
All while composing a Reply, or vice versa) preserves everything the
user has typed and only updates the CC field — driven by an
`$effect` that fires when `mode` changes after the initial load.
Cancel button calls `onClose` which clears `replyMode`. Submit calls
the reply endpoint and on success calls `onSent`, which clears the
composer and reloads the email (so any inherited associations and
the new outbound row in the linked Job's panel render
appropriately).

Backend endpoints:

- `GET /api/emails/{id}/reply-defaults/` — returns the prefilled
  form payload: `to` (parent's parsed from-email), `cc` (blank),
  `bcc` (blank), `reply_all_cc` (parent's to + cc minus
  `EMAIL_HOST_USER`, deduped, original order), `subject`
  (single-`Re: ` prefix via `build_reply_subject`), `body`
  (quoted-original block via `build_reply_body`), `in_reply_to`
  (parent's `message_id`), `references` (parent's references chain
  extended with the parent's own message_id), and
  `inherit_associations` (the parent's `job_id` /
  `purchase_order_id` / `bill_id`).
- `POST /api/emails/{id}/reply/` — accepts multipart form data,
  echoes the threading headers + first non-null inherited
  association FK back as `associate_with`, delegates to
  `OutboundEmailService.send_tracked`. Returns
  `{email_record_id}` on success, 400 on missing To, 502 on SMTP
  failure (the outbound row's `last_send_error` captures the
  reason).

Both endpoints are `IsAuthenticated` — no atom required (replying
is the email reader's own words; not a permission decision).

The reply correlation pass (§7.11) runs unchanged on the inbound
side: customer's reply to our outbound auto-links to the same Job
/ PO / Bill the outbound was associated with.

### 7.14 Outbound email — single entry point

`OutboundEmailService.send_tracked` is the sole way to send email
from this codebase. The earlier `send_email` SMTP-wrapper sibling
has been removed; its `EmailMessage` construction is inlined into
`send_tracked` where it's the only thing that did anything anyway.

Every outbound flow — document sends (Estimate / PO / Invoice) and
replies — routes through `send_tracked`, which guarantees an
`EmailRecord` row exists before SMTP fires, a Message-ID is
generated and persisted, and SMTP failures leave a "needs retry"
row that the user can re-submit from.

The `{object_url}` placeholder in document-send templates resolves
through `apps.core.email_templates.build_object_url(kind, obj_id)`
to `<our_public_url>/<entity-path>/<id>`, where `our_public_url` is
a Configuration key (default `https://example.com`). These URLs
don't currently serve unauthenticated customers — they're stub-
shaped so user-authored boilerplate has a sensible placeholder. The
real customer-facing public URL feature is a deferred follow-up;
the stub resolution flips to signed tokens when that work lands.

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

## 9. Scheduled processes

Some work has to happen on a clock rather than in response to a request —
expiring stale estimates, polling QBO for payments, pruning cached email.
These run as **Django management commands** and nothing else. There is no
HTTP route, no API endpoint, and no SPA affordance that triggers them; the
only entry points are a shell (`python manage.py <command>`) and the cron
daemon. This keeps the system-driven side effects (which attribute their
history to the `system` user) off the request path entirely.

### 9.1 `ScheduledProcessCommand` base class

`apps/core/management/base.py` defines `ScheduledProcessCommand`
(a `BaseCommand` subclass). A scheduled command:

- sets `process_name` (a stable string identifying the job), and
- implements `run()`, returning a JSON-serializable summary dict.

The base class's `handle()` wraps every invocation: it creates a
`ScheduledProcessRun` row at the start, calls `run()`, and on the way out
records the outcome and summary. Three outcomes:

- **`ok`** — `run()` returned; its dict is stored in `summary`.
- **`failed`** — `run()` raised. The traceback is stored in `error`, the
  run is saved, and the exception **re-raises** (so cron logs it / a human
  notices).
- **`skipped`** — `run()` raised `SkipRun(reason)`. The reason is stored in
  `summary` and no error is recorded. Used for "nothing to do, not a
  failure" cases — e.g. `poll_qbo_payments` when there's no active QBO
  connection.

Subclasses do **not** create the run row themselves; they just describe the
work and let the base class handle observability.

### 9.2 `ScheduledProcessRun` model

`apps/core/models.py` — one row per command invocation
(`db_table = 'scheduled_process_run'`, ordered newest first):

| Field | Notes |
|---|---|
| `process_name` | indexed; the command's `process_name` |
| `started_at` | set when the run begins |
| `finished_at` | set when it ends (null while running) |
| `outcome` | `ok` / `failed` / `skipped` (default `ok`) |
| `summary` | JSON — the command's return dict, or `{'reason': …}` for a skip |
| `error` | traceback text on `failed`, else empty |

Registered in the Django admin (`apps/core/admin.py`) **read-only** — add,
change, and delete are all disabled; every field is read-only. The admin is
the observability surface (filter by `process_name` / `outcome`); the rows
are written only by the base class.

### 9.3 The commands and their cadence

Four commands run on a schedule today:

| Command | `process_name` | What it does |
|---|---|---|
| `poll_qbo_payments` | `poll_qbo_payments` | Polls QBO for invoice payment and drives `Invoice.status` — see `quickbooks-integration.md` / `invoicing-and-expenses.md`. |
| `mark_estimates_expired` | `mark_estimates_expired` | Expires `open` estimates past their frozen `expiration_date` — see `estimates-and-prices.md`. |
| `mark_change_orders_expired` | `mark_change_orders_expired` | Expires `open` change orders past their frozen `expiration_date` — see `estimates-and-prices.md` (CO section). |
| `cleanup_temp_emails` | `cleanup_temp_emails` | Deletes cached `TempEmail` rows older than `email_retention_days` (preserves `EmailRecord`; no per-object history). |

### 9.4 The docker-compose `cron` service

A dedicated `cron` service in `docker-compose.yml` runs the scheduler. It
reuses the app image (`ashannonlee/minibini`) and runs
`deploy/cron/entrypoint.sh`, which exports the container environment to a
file the jobs source (cron strips the environment otherwise), installs
`deploy/cron/crontab`, and execs the cron daemon. Schedules
(container timezone, **UTC** by default):

| Cadence | Command |
|---|---|
| every 15 min | `poll_qbo_payments` |
| `01:30` daily | `mark_estimates_expired` |
| `02:00` daily | `cleanup_temp_emails` |

The cron container needs the same credentials the app does for these to
succeed (QBO OAuth + email/IMAP); see the operational note in
`quickbooks-integration.md`. Set `TZ` on the service to schedule in local
time instead of UTC.

---

## 10. Unfinished work

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

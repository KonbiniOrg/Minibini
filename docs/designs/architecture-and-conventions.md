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
Django project, one HTTP origin:

- The SPA at `frontend/` (Vite, served on `:9000` in dev, built to
  `dist/` for nginx in prod) is the UI.
- It calls the REST API at `/api/`, whose viewsets call the Django
  service layer. No business logic lives in the view layer.

Django itself serves only `/admin/` and `/api/`. The deprecated
server-rendered HTML view layer (`apps/*/views.py` + `templates/*.html`)
has been removed; the only non-API server endpoints left are the QBO
OAuth redirect views under `/api/qbo/` and WeasyPrint PDF rendering of
the four document templates in `templates/` for outbound email.

---

## 2. Backend

### 2.1 App layout

See CLAUDE.md "Architecture" for the full app tree. The split is by
domain (jobs, estimates, contacts, invoicing, purchasing, inventory,
core) plus a single `apps/api/` app that owns the REST layer.

### 2.2 Service layer

**All model CRUD goes through the service layer.** Every create, update, and
delete of a tracked model happens inside a service method in
`apps/<app>/services.py`. No other layer — viewsets, the wizard, management
commands, PDF/email code — calls `Model.save()`, `.delete()`, or
`.objects.create()` on a tracked model directly. The point isn't ceremony: it's
that a single write path lets cross-cutting side effects be **guaranteed instead
of remembered**. Example: every line-item write routes through `LineItemService`
(§4), whose `save_line_item` / `delete_line_item_with_renumber` recompute the
document's percentage-adjustment lines, so an adjustment can never go stale no
matter who edited a line (a viewset, the wizard, a future caller). Sanctioned
exceptions: migrations, fixtures/seed loaders, and test `setUp` may write models
directly; a bulk service method may batch its writes and recompute once at the
end (e.g. `InvoiceService.copy_from_estimate`).

**Rules:**

- Services own business logic. Viewsets are thin —
  parse input, call a service, render a response.
- Services accept primitives and IDs, return model instances
  ("primitives in, models out"). Viewsets never load a model just to
  hand it to a service; the service does its own lookups.
- No serializers cross the service boundary. Viewsets extract
  `serializer.validated_data` and pass plain kwargs.
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
- `apps/estimates/signals.py` — two receivers
  (`estimate_status_changed_for_job`, `estimate_accepted`) that mutate jobs
  (and, on accept, crystallize hand-lines into Fees) when an estimate
  status changes. The job-status receiver routes its changes through
  `JobService.update_job` rather than mutating the Job directly. (The former
  `estimate_status_changed_for_worksheet` receiver was removed with the
  planning layer.)

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
                             # JobTaskMixin,
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
    inventory/               # InventoryItem, Material
    invoicing/               # Invoice
    jobs/                    # Job + board views
    purchasing/              # PurchaseOrder
    rate_schemes/            # RateScheme
    reimbursements/          # expense reimbursement batches
    search/                  # SearchService dispatch
    shifts/                  # Shift + clock-in/out + change-requests + report
    tasks/                   # Task (job-side tasks)
    templates_config/        # WorkTemplate, ServiceItem, AccountingCategory,
                             #  settings, units
    time_tracking/           # urls only — re-exports apps.api.shifts.urls
                             #  (mounted at /api/shifts/); time-tracking/{status,active} still 501
    users/                   # User admin (CRUD, deactivate, reset password)
    portal/                  # Customer portal (AllowAny; estimate read/accept/reject)
```

The `WorkOrder` model has been removed; Tasks live directly on `Job`. The
planning layer (`EstWorksheet` / `PlanTask` / the `worksheets/` and
`plan_tasks/` API apps) has also been removed — the Job owns its work atoms
(`Task` / `Material` / `Fee`) directly. See
`docs/designs/jobs-and-tasks.md` for the job-owns-atoms shape.

**Shared change-request viewset.** `apps/api/shifts/views.py` defines a
`_ChangeRequestViewSet` base that `ShiftChangeRequestViewSet` and
`BlepChangeRequestViewSet` both subclass — common create / list-scoping /
`approve` / `deny` behaviour, differing only in `queryset_model` and
`serializer_class`. Both delegate to `TimeChangeRequestService`
(`apps/core/services.py`) and the model's `apply_requested()`. See
`docs/designs/data-constraints.md` §1.2a and
`docs/designs/users-and-permissions.md` for the shift/blep change-request
and clock-in/out endpoints and their atoms.

### 3.2 Authentication

Session auth only. Configured in `settings.py` with DRF's
`SessionAuthentication` as the sole backend. The dev autologin
middleware (which sets `request.user` on the session) works
transparently. The frontend never sees a JWT — see `frontend/src/lib/api.js`,
which only handles the CSRF cookie.

**Exception — portal endpoints.** `apps/api/portal/` (`/api/portal/`)
is the first `AllowAny` + `authentication_classes=[]` write surface.
It is token-authorized (each `Estimate` carries a `public_token`
column) rather than session-authorized. The customer is not a `User`;
their action is attributed via an explicit `HistoryEntry` with
`user=None`. See `estimates-and-prices.md` §15.1 and
`users-and-permissions.md` §Portal endpoints.

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

> **⚠️ The 100 cap is silent — this has bitten us repeatedly.** `max_page_size
> = 100` means **any** larger `?page_size` is silently clamped to 100. A request
> for `?page_size=9999` returns *at most* 100 rows with no error. A client that
> reads `data.results` and ignores `data.next` therefore **silently shows only
> the first 100** — the classic symptom is "a record I know exists doesn't appear
> in the list / isn't selectable in the picker" once a dataset crosses 100.
>
> Whenever a frontend (or any consumer) "just wants all the rows," do **not**
> assume a big `page_size` works. Notice the cap and pick a fix deliberately —
> there's no one right answer; it depends on the surface:
> - **Walk the pages** — loop following `next` (incrementing `page` locally to
>   stay proxy-relative) and accumulate. Good for a *browse + client-side search*
>   list where you genuinely want the whole set in memory (e.g.
>   `InventoryListPage`). Watch the total size.
> - **Server-side `?search=` / filtering** — for type-aheads and large datasets,
>   query the API as the user types instead of loading everything. The durable
>   choice for pickers.
> - **Disable pagination on the viewset** (`pagination_class = None`) — only when
>   the result set is *intrinsically bounded* and small (like `UserViewSet`).
> - **Real pagination UI** — page controls, when the user should page through.
>
> The anti-pattern to avoid: bumping `?page_size` to a big number and assuming
> it's complete. If you bound a result deliberately, say so in the UI; never let
> it look like "everything" when it's the first 100. Known instances fixed by
> page-walking: `InventoryListPage` (2026-06). Fixed by server-side-search
> rework (2026-06): `InventoryItemPicker` (formerly `InventoryItemPicker`),
> email-association pickers (jobs/POs, plus the since-retired bills picker).

#### Type-ahead pickers: `SearchPicker` + per-entity wrappers

All searchable entity pickers in the SPA are built on a shared behavior core,
`frontend/src/components/SearchPicker.svelte`, which owns: debounced search
(via a `search(query)` callback), focus/blur-managed results dropdown,
prefill-by-id label resolution with a race guard (via `resolveLabel(value,
selectedItem?)`), and selected/clear state. Callers supply row rendering and
interaction through named snippets (`row`, `selected`, `header`) and callbacks
(`onPick`, `onClear`). Props: `value` (bindable, opaque), `selectedItem`
(optional prefill object), `disabled`, `placeholder`, `rowLabel(row)`.

Per-entity pickers thin-wrap `SearchPicker` and own their API endpoint, search
params, and row/selected rendering:

| Component | Search endpoint | Notes |
|---|---|---|
| `BusinessPicker` | `/api/businesses/?search=` | |
| `JobPicker` | `/api/jobs/?search=` | |
| `ContactPicker` | `/api/contacts/?search=` | |
| `PurchaseOrderPicker` | `/api/purchase-orders/?search=` | Global (po_number, vendor name) |
| `InventoryItemPicker` | `/api/inventory/?search=` | Accepts `params` prop; "None (freeform)" via `header` snippet |
| `CustomerPicker` | dual-source contacts + businesses | Emits `{type, id}` (not a plain id) |

**Shared single-model picker contract:** `value` (bindable entity id), `onSelect(fullRow|null)`, optional `selectedItem` for id-based prefill. `CustomerPicker` deviates: its `value` is `{type, id}`.

**Backend `?search=`** is hand-rolled in `get_queryset` for purchase-orders (po_number, vendor name) and inventory items (code, description) — the same pattern as contacts/jobs. DRF `SearchFilter` is not used.

### 3.4 Mixin catalog

All in `apps/api/mixins.py`.

| Mixin | Used by | One-line description |
|---|---|---|
| `StatusTransitionMixin` | Every document viewset | Auto-registers `@action` POST endpoints from a `status_actions` dict, with optional `requires_reason` validation and HistoryEntry attachment. |
| `LineItemMixin` | EstimateViewSet, InvoiceViewSet, PurchaseOrderViewSet | Adds `line-items/`, `line-items/{id}/`, `line-items/reorder/` actions; delegates all writes to `line_item_service_class`. Its own `try`/`except` blocks catch only `NotFoundError` → 404; a service `ValidationError` is **not** caught here (2026-07-25 fix — it used to be re-rendered as `{'detail': str(e)}`, which stringified dict-keyed field errors into garbled text) and instead propagates to the central handler (§3.9), which renders both the plain-sentence and field-keyed shapes correctly. |
| `JobTaskMixin` | JobViewSet | Adds `tasks/`, `tasks/{id}/` actions for `Task` (job-side); calls `TaskService.create_direct` / `delete_task`. (The Job's `materials/` and `fees/` actions live on `JobViewSet` directly.) |
| `JSONDestroyMixin` | JobViewSet, InventoryItemViewSet, WorkTemplateViewSet, ServiceItemViewSet, AccountingCategoryViewSet | Overrides DRF's default destroy() to return 200 with `{'message': ...}` instead of 204; subclasses set `destroy_response_message`. |
| `ConfirmDeleteMixin` | ContactViewSet, BusinessViewSet, ReimbursementViewSet | Two-phase delete; first DELETE returns `{'confirm_required': True, 'impact': {…}}`, DELETE with `?confirm=true` runs the delete. Subclasses implement `get_deletion_impact(obj)` and `perform_confirmed_destroy(obj)`. |
| `JobScopedPermissionMixin` | JobViewSet, EstimateViewSet, ChangeOrderViewSet, DeliverableViewSet, TaskViewSet | Resolves a viewset's target Job for `CanManageJobOrPM` via `get_object_job(obj)` / `get_permission_target_job(request)`. Configured per viewset with `job_object_path` (attribute chain instance → Job, e.g. `'self'`, `'estimate.job'`), `job_create_field` (create-body key naming the parent Job), and `job_url_kwarg` (job-nested URL kwarg). |
| `JobScopedCanManageMixin` | Job/Estimate/ChangeOrder/Deliverable/Task serializers | Serializer mixin adding a server-computed read-only `can_manage` boolean (`JobService.user_can_manage(request.user, <job>)`, job reached via `can_manage_job_path`). Caches the atom check per-request to keep list serialization O(1) queries. The SPA gates job-scoped edit affordances on this per-object flag — same convention as the line-item `editable`/`deletable` booleans. |

(The former `PlanTaskMixin` / `PlanTaskBundleMixin` were removed with the
worksheet layer.)

`StatusTransitionMixin.status_actions` shape:

```python
status_actions = {
    'mark-open': {'service': EstimateService.mark_open},
    'cancel':    {'service': InvoiceService.cancel,
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

Two composite classes (hand-written, not factory-generated) live alongside the atoms:

- `CanManageTimeOrFinancials` — OR of `can_manage_time` and `can_manage_financials`; gates the payroll shift report.
- `CanManageJobOrPM` — `can_manage_jobs` OR being the target Job's `project_manager`. View-authoritative: short-circuits `SAFE_METHODS`, passes atom holders, and otherwise resolves the request's target Job (via `JobScopedPermissionMixin.get_permission_target_job`) and PM-checks it with `JobService.user_can_manage`. `has_object_permission` stays as defense-in-depth for update/destroy. Gates writes on the job-owned viewsets (Job, Estimate, ChangeOrder, Deliverable, Task) so a job's PM gets atom-equivalent access **scoped to that one job** — see `users-and-permissions.md` "Project-manager object access".

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

A few endpoints split read/write within an action. On `JobViewSet`, the
`tasks` action (GET list + POST add) and the `task_detail` action
(GET/PATCH/DELETE a task) are `IsAuthenticated` — any authenticated user
may add, edit, and delete a task (delete is still blocked by
`TaskService.delete_task` when the task is in_progress/complete or has
Bleps); the manager/PM-only job actions fall through to
`CanManageJobOrPM` (see `apps/api/jobs/views.py`). On `TaskViewSet`, the
flat `cancel` action requires `CanManageJobOrPM` while the other
lifecycle actions stay `IsAuthenticated`.

### 3.6 DELETE responses are 200 with JSON

Convention: every DELETE returns HTTP 200 with a JSON body (e.g.
`{'message': '... deleted.'}`), never 204. The frontend
`api.js` rejects any non-JSON response, so a default DRF 204 is
a runtime error in the SPA.

**Viewsets that comply** (override `destroy()` to return JSON, or use `JSONDestroyMixin`):

- `EstimateViewSet` — `apps/api/estimates/views.py`
- `InvoiceViewSet` — `apps/api/invoicing/views.py`
- `PurchaseOrderViewSet` — `apps/api/purchasing/views.py`
- `ContactViewSet` — `apps/api/contacts/views.py`
- `BusinessViewSet` — `apps/api/contacts/views.py`
- `ReimbursementViewSet` — `apps/api/reimbursements/views.py`
- `BlepViewSet` — `apps/api/bleps/views.py`
- `RateSchemeViewSet` — `apps/api/rate_schemes/views.py`
- `ExpenseViewSet` — `apps/api/expenses/views.py`
- `JobViewSet` — `JSONDestroyMixin`
- `InventoryItemViewSet` — `JSONDestroyMixin`
- `WorkTemplateViewSet` — `JSONDestroyMixin` (plus `perform_destroy` for service call)
- `ServiceItemViewSet` — `JSONDestroyMixin` (plus `perform_destroy` for service call)
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
- `GET /api/time-tracking/status/` — `apps/api/urls.py`
- `GET /api/time-tracking/active/` — `apps/api/urls.py`

`POST /api/shifts/clock-in/` and `POST /api/shifts/clock-out/` are no longer
stubs — they are live in `apps/api/shifts/views.py` (work-shifts feature).
`apps/api/time_tracking/urls.py` now re-exports the real shift URLs.

`/api/expenses/` is fully implemented (`ExpenseViewSet` in
`apps/api/expenses/views.py`); it is not a stub.

### 3.9 Error response contract

**Two error shapes, nothing else.** Every API error body is one of:

| Shape | Meaning | Example |
|---|---|---|
| `{'detail': '<sentence>'}` | Operation error — a guard, state-machine refusal, permission problem, missing record | `{'detail': 'Scheme is referenced; create a new version instead of editing.'}` |
| `{'<field>': ['msg', ...]}` | Field validation error (DRF serializer shape); cross-field problems use the `non_field_errors` key | `{'unit_label': ['"parsec" is not a configured unit.']}` |

Status codes carry the semantics: 400 validation/guard, 403 permission,
404 missing, 409 conflict (referenced/superseded/two-phase collisions).
`{'message': ...}` is **success-only** (the DELETE-returns-200 convention,
§3.6) and never appears in an error body. The `'error'` key is retired —
never emit it.

**The central handler owns rendering.** `apps/api/exceptions.py`
(`api_exception_handler`, registered in `settings.REST_FRAMEWORK`) renders
any *uncaught* exception into the contract:

- Django `ValidationError` with plain message(s) → 400
  `{'detail': 'msg1 msg2'}` (messages joined).
- Django `ValidationError` raised with a dict → 400 field-keyed
  pass-through, `'__all__'` renamed to `non_field_errors`.
- `ProtectedError` → 409 `{'detail': 'This record is referenced…'}`.
- Everything DRF already handles (serializer validation, `PermissionDenied`,
  `NotFound`, …) keeps its native contract shape.

**View rule: don't catch what you don't reshape.** A service
`ValidationError` that should be a plain 400 needs *no* try/except — let it
propagate to the handler. Catch it only to change the status code or add
payload (e.g. the rate-scheme referenced 409 with `supersede_url` +
`reference_counts`, or the wizard claim-conflict 409s carrying
`code: 'atoms_already_claimed'` + `atom_ids`). When a client needs to
branch on *which* conflict occurred, add a machine-readable `code` key
beside the human `detail` — never make `detail` itself a token. In any
kept catch, `raise` variants you don't handle rather than hand-rendering
them:

```python
try:
    ConfigurationService.update_rate_scheme(instance, **ser.validated_data)
except DjangoValidationError as e:
    if getattr(e, 'code', None) == 'referenced':
        return self._referenced_conflict(instance, request)
    raise  # plain validation errors render via the contract handler
```

Services should raise field-keyed `ValidationError({'field': ['msg']})`
when the problem belongs to a specific input field, and a plain
`ValidationError('sentence')` for operation errors — the handler preserves
whichever shape you choose, so the choice made in the service is what the
SPA renders.

**Frontend display.** `api.js` attaches `.status` and `.data` to every
thrown error (`.data` is `null` when the body wasn't JSON — nginx error
pages still carry `.status`). The display half of the contract routes
every message to one of three venues via `lib/errorTriage.js`
(`triageError(e)` → `{overlay, message, fields}`):

1. field validation → `<FieldError>` slots under each input;
2. operation errors + `non_field_errors` (+ in-form success acks) →
   `<FormMessage>` under the form's button row, which also hosts
   next-step affordances for coded conflicts (e.g. "Create new version"
   on the referenced-scheme 409);
3. everything form-less (row actions, 5xx, infrastructure, page-level
   success) → the single global red/green overlay
   (`stores/messages.js` `showError`/`showSuccess` +
   `MessageOverlay.svelte` mounted once in App.svelte).

`window.alert()` for API results is banned; `confirm()` for irreversible
deletes stays. Full frontend rules and the uniform catch-block snippet:
`frontend/README.md` → Error Handling. Exemplar:
`frontend/src/components/RateSchemeManager.svelte`.

---

## 4. Line item API pattern

Three entities have line items (Estimate, Invoice, PurchaseOrder).
All use `LineItemMixin` and route every write through a service class.
(`BillLineItem` survives only as retired schema — 2026-07-23, see
materials-inventory-and-purchasing.md §13.)

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
| `POST /{id}/line-items/` | `line_items` | `service.add_line_item_from_pli` if `inventory_item` is supplied without manual fields, else `service.add_line_item` |
| `PATCH /{id}/line-items/{item_id}/` | `line_item_detail` | `service.update_line_item` |
| `DELETE /{id}/line-items/{item_id}/` | `line_item_detail` | `service.delete_line_item` |
| `POST /{id}/line-items/reorder/` | `reorder_line_items` | `service.reorder_line_items` |

Each service class must provide: `add_line_item`, `add_line_item_from_pli`,
`update_line_item`, `delete_line_item`, `reorder_line_items`. Each
enforces its own status guard (typically draft only); the mixin doesn't
know what statuses are editable.

`BaseLineItem.save()` has a `_populate_from_pli` safety net that fills
in description/units/price/category from a linked `InventoryItem` if
they're missing — the model's last line of defence in case some new
code path bypasses the service.

Line item deletion: never call `.delete()` on a line item directly.
Always go through `LineItemService.delete_line_item_with_renumber()`
(or the entity service's `delete_line_item`, which delegates to it),
because plain delete leaves gaps in `line_number`. See CLAUDE.md
"Code Conventions" for the rule.

**Line item create/update: route through `LineItemService.save_line_item()`.**
Mirroring the delete rule, every line-item create and update — in the entity
services *and* in the wizard (`BaseWizardService`) — saves via
`LineItemService.save_line_item(line_item)` instead of calling
`line_item.save()` directly. That method saves the row, then recomputes any
percentage-adjustment lines on the parent document (container resolved via
`get_parent_container`), so adjustments stay correct after any line change with
no manual "recalculate" step. `recompute_adjustments` writes the adjustment
rows with a raw `.save()`, so there is no recursion. The wizard still owns
creating its `…LineItemSource` rows (those aren't line items); only the
line-item writes go through the chokepoint. The sanctioned bypass stays
correct: `revise_estimate` is a faithful copy of an existing revision
(adjustment prices carry over already correct).

---

## 5. Frontend (Svelte SPA)

### 5.1 Tech and runtime

- Svelte 5 with runes (`$state`, `$derived`, `$effect`, `$props`,
  `$bindable`).
- Vite dev server on `:9000` proxying `/api/*` to Django on `:8000`;
  prod build emits `dist/` served by nginx.
- Hash-based routing via `svelte-spa-router`.
- No CSS framework; semantic HTML and per-component `<style>` blocks.

**Second Vite entry — customer portal.** `frontend/portal/` is a
separate entry point (listed in `vite.config.js`
`build.rollupOptions.input`) that builds to `dist/portal/index.html`
and is served at `/portal/`. It is login-not-required: no auth gate,
no operator nav, no reference to `App.svelte` or the auth store. It is
the customer surface for accepting or rejecting a sent Estimate (see
`estimates-and-prices.md` §15.1). The same Vite dev server serves it;
the same `/api` proxy covers its requests.

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
- `shift.js` — the worker's open shift, shown in the permanent
  `ShiftBand` header strip (Clock In / Clock Out; the `CurrentBlepBand`
  slides in beneath it while a session runs — both in `App.svelte`'s
  sticky `.app-bands` wrapper).

### 5.4 Routing

`App.svelte` declares the route table and mounts `<Router routes={routes} />`
inside the auth gate. Routes are page components under
`frontend/src/routes/<domain>/<PageName>.svelte`. Reusable pieces live
in `frontend/src/components/`.

### 5.5 Style scoping gotcha (and a small footgun)

Svelte scopes component `<style>` blocks per component. Class selectors
defined in one component's `<style>` are silently invisible to the DOM
rendered by another component, even when the class name matches.

Concrete example we hit: `JobDetail.svelte` defined `.panel`,
`.panel-head`, `.panel-scroll` for the Description / History card
chrome. When `DeliverablesSection.svelte` was added as a sibling card,
its outer element used `class="panel deliverables-panel"`, but the
panel chrome did not render — the white card, border, rounded corners,
and uppercase header treatment all came from JobDetail's scoped
classes, which don't reach a child component's elements. Result: a
borderless, unstyled list. (For a while the fix was a copied rule
block in each component — which promptly drifted.)

**Resolved (2026-07-08):** the CSS reorg pass audited every component
`<style>` block and promoted all shared chrome — the `.panel` family
included — into `app.css` (§5.5a); the per-component copies are gone.

The gotcha itself is permanent Svelte behavior, so the rule of thumb
stands: if you reuse a class name from another component and the
styling vanishes, this is the cause. **Promote the rule to `app.css`**
— never copy it into your component; the copy is how the pre-reorg
drift started.

### 5.5a Shared UI families in `app.css`

`frontend/src/css/app.css` is the single global stylesheet (imported by
both the app and portal entries) and is organized in three sections:
BASE (tokens, element defaults, utilities, page frame), SHARED
(cross-page families), and PAGE KINDS (vocabulary keyed to the three
page categories of the `.page-body` rollout — fully-individualized,
banner pages, plain pages; `frontend/README.md` § CSS). The 2026-07
consolidation promoted every rule that existed as copies in two or more
components: `.toolbar` (+ buttons), `.back-link`, `.page-title`,
`.action-link`, `.edit-link`, `.panel`/`.panel-head`/`.panel-scroll`,
`.badge-invoiced`, `.row-actions button`, and `.page-tabs`, alongside
the families below. Rule of the road: page styles arrange and tune;
copying a rule between components means it should be promoted instead;
local overrides may resize a family for dense contexts but never
recolor it.

#### The page-styling pipeline

The three page categories of the `.page-body` rollout
(`frontend/README.md` § CSS) are not a fixed taxonomy — they are
**stations a page moves through**, on two independent axes:

1. **Kit consumer** (the starting state). Category III pages and
   not-yet-detailed Category II pages are the same thing in different
   clothes: their entire look comes from the shared vocabulary in
   `app.css`. Improving the kit (form kit, tab strips, tables,
   toolbars) improves every page at this station for free. Generic
   styling sweeps target exactly this pool.
2. **Banner promotion** (III → II). A page moves under a full-bleed
   area header when its *area's* header grouping is finalized — an
   area decision, not a page redesign. Groupings so far: **job**
   (gray-800 `#1f2937` — the 2026-07-08 job workspace restructure
   formalized this into a reusable shell, `JobShell.svelte`:
   `JobHeader` + `JobNavRail` + a collapsible `JobContextBand`, with one
   section panel hosted per page; see `jobs-and-tasks.md`
   §9.6) and **customer** (`CustomerHeader`, red-950 `#450a0a`, no rail
   yet). More areas are planned; as each lands, its pages move from III
   to II without other change. `JobShell`'s header+rail+band+panel
   shape is the pattern to reuse when a future area needs the same
   kind of always-present chrome around several document/list sections
   — the section pages themselves stay ordinary kit consumers (or get
   their own detail pass later); only the *shell* is shared.
3. **Detail pass** (the terminal station). A page graduates out of
   the sweep pool when it gets a deliberate, one-by-one design pass —
   a layout built *out of* the shared vocabulary but no longer
   *defined by* the generic defaults. A detailed page still consumes
   the kit (its pills, chips, action band track global changes), but
   generic kit-rollout work **skips it**; subsequent changes to it are
   page-specific decisions.

Category I (fully individualized: board, schedule) is a separate track —
those pages use only the BASE layer and get bespoke passes on their own
schedule. **The job overview is no longer purely Category I** (2026-07-09):
it mounts `JobShell` like every other job page (header + rail + context
band are the shared chrome, banner-promoted per the "job" area entry
above), but its `.page-body` content — the six `.summary-block` lifecycle
blocks — is still a fully individualized, bespoke layout, not a kit-consumer
body. So the page is a hybrid: shell chrome from the II/banner track, body
from the I/bespoke track.

**Job-page taxonomy (the seam test).** `JobShell` pages come in three
kinds, separated by asking *does any interaction cross the seam?* (from
the 2026-07-08 workspace-restructure design):

1. **Section page** — shell + one panel. The shipped norm.
2. **Combo page** (future, none built) — shell + two *independent*,
   read-mostly panels side by side; zero cross-pane coupling. First
   candidate when the time comes: **estimate|invoice** (RM compares
   these daily today via two browser windows); also plausible:
   invoice|shipments, tasks|POs.
3. **Reconciliation surface** — shell + one *composite* panel with an
   internal two-column layout and owned cross-column state
   (`ReconcileMode`). The wizard composed itself; it is never a pane in
   a combo, and it needs full width.

**Detailed pages** (the skip-list for generic sweeps — keep current as
passes complete):

| Page | Detail pass |
|---|---|
| Task Detail (`#/jobs/:jobId/tasks/:taskId`) | 2026-07-07 |

#### The founding families

The founding three families (promoted global per §5.5's "better
long-term fix"; 2026-07). They are generic on purpose — no
page-specific names or references:

- **`.status-badge` + `.status-{status}`** — THE status pill. One base
  pill class plus per-status color modifiers keyed by status name
  (document statuses *and* the task-activity keys from
  `lib/taskActivity.js`: working/ongoing/unstarted/blocked/complete/
  cancelled). The former per-component copies (JobHeader, JobDetail,
  PurchaseOrderDetail, EstimateDetailPage, InvoiceDetailPage,
  ChangeOrderDetailPage) are gone; change orders' `status-co-*` names
  were folded into the plain names. Components may locally override
  base *sizing* for dense contexts (JobHeader/JobDetail do) but never
  colors — a shared status name shares its color everywhere. The header
  status `<select>`s reuse the same color classes. Tasks join via
  `TaskActivityIndicator`'s `pill` prop; the board's `TaskCard` reads
  `activity.color` inline rather than keeping a parallel palette.
- **`.stat-chips` / `.stat-chip`** — a strip of small labeled value
  cards (the job-board chip look): each chip is a card whose shaded
  header bar (`.stat-chip-header`) carries an uppercase label, bodies
  (`.stat-chip-body`) size to content so header bars stay uniform
  across the strip. `money` on a chip tints its header green to group
  financial chips into a family. First consumer: the task detail
  header (jobs-and-tasks §10.2).
- **`.action-band`** — a full-width strip of the actions operating on
  the entity above it; buttons inside get consistent sizing, with
  `primary` (the one most-expected action) and `quiet` (housekeeping,
  e.g. an Edit button riding along) modifiers.
- **`.summary-block` + `.stat-spread`** — the lifecycle-summary family
  (2026-07-09, job overview redesign): tiles a subject's lifecycle into
  fixed-order blocks, each in one of three temperatures —
  `.summary-block.active` (white card, blue left edge, shadow, full
  `.stat-spread` of `.stat` groups top-aligned so label rows form one
  line), `.summary-block.frozen` (flat grey one-liner), `.summary-block.dormant`
  (dashed ghost one-liner). `.stat` holds `.stat-label` / `.stat-value`
  (with an optional `.unit` suffix and a `.status-badge` pill) /
  `.stat-sub` / an optional `.stat-progress` bar. `.clock-line` (+
  `.clock-good` / `.clock-warn` / `.clock-bad`) is a hairline-topped
  trailing status line inside an active block. First (and so far only)
  consumer: the job overview's six blocks (`jobs-and-tasks.md`
  §9) — generic on purpose, named for reuse by other lifecycle
  summaries.
  **`.summary-block` is an `<a>`** (2026-07-28): the whole card is the
  link, so the base rule resets `display`/`text-decoration`/`color`, and
  hover, `:focus-visible`, and the accent ring are styled on the anchor.
  A consumer must therefore render **no interactive descendants** inside
  a block — a nested link or button makes the markup invalid and forces
  a stretched-link overlay instead (which also kills text selection in
  the card). Keep controls outside the family.

### 5.6 Preserving line breaks in free-text fields

Large free-text fields (`TextField`s — descriptions, notes, reasons,
addresses) let users type paragraphs. Default HTML rendering collapses
their newlines, so paragraph formatting is lost on display.

Convention: wherever such a field is shown **in full**, apply the
global `.preserve-breaks` utility class. It is `white-space: pre-wrap`,
defined once per stack so both share the same mechanism:

- `frontend/src/css/app.css` — SPA (global, reaches every component;
  not subject to the §5.5 scoping gotcha).
- `templates/purchasing/purchase_order_pdf.html` — standalone PDF
  template with its own `<style>`, so it carries its own copy (the
  other three document PDF templates do likewise).

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

**Applied at:** Job / Task descriptions and billing line-item
descriptions (`LineItemTable`, `JobDetail` invoice + PO lines,
`PurchaseOrderDetail`). Other free-text fields (notes, addresses, material
descriptions) get the §5.6 wrap but are not linkified.

**Layout note:** a long unbreakable token (URL) in a CSS grid/flex column
won't shrink the track unless the item has `min-width: 0`. Pair
`overflow-wrap: anywhere` (now part of `.preserve-breaks`) with
`min-width: 0` anywhere a free-text field sits in a grid/flex track. (The
`.midband` class this note used to reference was retired with the
accordion-pillar overview — 2026-07-09; `app.css` currently has no
`min-width: 0` rule for the context band's `.context-band-grid`, which
replaced it. Verify before relying on this if a long-URL overflow bug
turns up in `JobContextBand`.)

### 5.9 Time-edit modal (shifts + bleps)

`frontend/src/components/time/TimeEditModal.svelte` is the single modal for all
time-record edits — generalized from the old `BlepEditModal` (which now just
wraps `TimeEditModal` with `recordType="blep"`). Props pick the variant:

- `recordType`: `'blep'` | `'shift'`
- `action`: `'edit'` | `'create'` | `'request'`

In `edit` mode it offers Delete; in all modes it runs **soft conflict
detection** against the enclosure invariant (shift↔blep) and shows a warning.
On `edit` / `create` a detected conflict **blocks Save** (the change would
break the invariant outright); on `request` it only **warns** (the request is
still submittable — a manager resolves it on approve, see
`docs/designs/data-constraints.md` §1.2a). Mutations notify the relevant store
(`stores/shift.js` / `stores/blepActivity.js`) so other views refresh. Used by
`home/MyShiftsList.svelte`, `home/RecentTimeList.svelte`, and the task-detail
blep wrapper.

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

History is **partitioned by domain into per-domain tables** (`apps/core/models.py`),
all sharing the abstract `HistoryEntryBase`:

- `JobHistory` (`job_history`) — Job + everything that hangs off it (task,
  estimate, change order, invoice, material, deliverable, shipment).
- `CrmHistory` (`crm_history`) — contacts and businesses.
- `PurchasingHistory` (`purchasing_history`) — purchase orders (plus legacy bill / bill-payment entries from before the 2026-07-23 bill retirement).
- `InventoryHistory` (`inventory_history`) — inventory items.
- `ExpensesHistory` (`expenses_history`) — expenses **and reimbursement batches** (a batch is an adjunct of its member expenses — see §7.4).

Three entry types (on the base): `audit` (automatic field-change tracking on
decorated models), `action` (system-generated state changes from
signals/services), `note` (user-written free text).

`object_type` (lowercased class name) + `object_id` link an entry to any model —
no `GenericForeignKey`. The **target table is chosen from `object_type`** by
`apps.core.history.record_history` (the single write entry point) and
`history_model_for`; every read site queries the table for its domain. Ordered
newest first.

`changes` is a JSON field with field diffs (`{"status": {"old": "draft",
"new": "open"}}`) plus underscore-prefixed metadata keys: `_created`
(true on first save) and `_action` (system-generated description).
`text` is reserved for human-entered text only — never put a
system-generated description in `text`.

### 7.2 Tracked models

Models opt in with `@history(exclude=[...])` from `apps/core/history.py`:

- `Contact`, `Business` — `apps/contacts/models.py`
- `Job`, `Task` — `apps/jobs/models.py`
- `Estimate`, `ChangeOrder` — `apps/estimates/models.py`
- `Invoice` — `apps/invoicing/models.py`
- `PurchaseOrder` — `apps/purchasing/models.py` (Bill's decorator was removed with the 2026-07-23 retirement; its old entries remain)
- `Material` — `apps/inventory/models.py`
- `Deliverable`, `Shipment` — `apps/deliverables/models.py`
- `Expense` — `apps/expenses/models.py`. Excludes the four `qbo_*` fields (`qbo_id`, `qbo_sync_status`, `qbo_sync_error`, `qbo_pending_op`) so QBO sync-state churn never enters the expense timeline — the domain↔QBO seam (QBO sync state lives in `QBOSyncLog`, not here).

`Reimbursement` is deliberately **not** decorated — it's an adjunct whose history is written imperatively onto its *primary* (§7.4), which the decorator (keyed to a model's own `object_type`) can't express. (`BillPayment` followed the same pattern until the bill retirement.)

Time/workforce models (`Shift`, `ShiftChangeRequest`, `BlepChangeRequest`)
are **not** tracked: their lifecycle is already first-class data
(`status`, `reviewer`, `reviewed_at`, …) and nothing read their history.

Excluded fields don't appear in `changes`; if they were the only fields
that changed, no entry is created.

### 7.3 Change capture

`apps/core/history.py` uses Django signals plus a `contextvars.ContextVar`:

- `post_init` (`_on_post_init`) — snapshots a tracked instance's field
  values to `instance._history_original` when it loads from the DB.
- `pre_save` (`_on_pre_save`) — diffs current values against the
  snapshot and either appends to the request-scoped pending list (if
  inside a request) or writes a history row immediately via
  `record_history` (outside a request).
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

### 7.4 `record_action`, imperative entries, and attribution

`audit` entries are automatic (the decorator). `action` and `note` entries are
**imperative** — a service calls into `apps/core/history.py`:

- `record_history(object_type, entry_type, object_id, user=None, changes=…)` — the
  single low-level write entry point.
- `record_action(object_type, object_id, action, user=None)` — the thin convenience
  wrapper for `entry_type='action'` (`changes={'_action': action}`). **Prefer this**
  for system/service action entries over hand-writing `record_history(entry_type='action', …)`.

**Attribution defaults to the request context.** `record_history` itself (and
therefore `record_action` and `QBOService.log_sync`) defaults its author to
`current_request_user()` — the authenticated user resolved from the active
`HistoryContext` — so a service does **not** thread a `user`/`actor` just for
attribution. Pass an explicit `user=` only for a *deliberate non-request author*:
a `system` user (signals, expiry commands), a customer (the portal puts the
customer in the `changes` payload; its anonymous requests resolve to `user=None`),
or a historical author + backdated `timestamp` (`backfill_job_history`). The old
redundant `request.user` threading was removed 2026-07-04 — the document-send
services, `cancel_line_item`, and the inventory `write_off`/`merge`/
`manual_adjustment` trio carry no `user` param anymore; params that carry real
data (`record_payment`'s `created_by`, `receive_items`' `received_by`, blep/shift
permission `actor`s) remain. Tests that invoke views via `APIRequestFactory`
(no middleware) must set a `HistoryContext` themselves.

**Adjunct → primary.** The `@history` decorator keys entries to a model's *own*
`object_type`, so a sub-resource can't auto-route its history to its parent. Adjuncts
therefore record imperatively on the **primary's** timeline:
`Reimbursement` lifecycle (reimbursed-in-batch / unwound) → `record_action(object_type='expense', …)`
on each member expense. (`BillPayment` → its Bill was the other adjunct
until the 2026-07-23 bill retirement.) Delete entries are written on the **success path only** (after
the QBO void succeeds and just before the local row is removed — capture the parent id +
amount first).

**Important** (also in CLAUDE.md): never use `QuerySet.update()` on
tracked models — it bypasses signals. Always load and `.save()`.

### 7.4 Endpoints

History feeds (paginated, newest first):

- `GET /api/jobs/{id}/history/` — aggregates the job plus its estimates,
  change orders, invoices, tasks, deliverables, shipments, and materials
  (built by `apps/api/jobs/history.py` → `build_job_history`). Each
  entry carries `source_label` (e.g. `"Task: Fabrication"`) and
  `source_link` (populated for job and task entries; `null` for others in
  this version). EstWorksheet is no longer collated.
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
everything. The panel is used on Contact, Business, and PO detail pages
(`{ history, onAddNote }`). It is not used on the Job overview — that
slot is occupied by `EmailPanel.svelte` (see §7.6).

A dedicated Job History page lives at `#/jobs/:id/history`
(`frontend/src/routes/jobs/JobHistoryPage.svelte`). It renders the full
collated feed returned by `GET /api/jobs/{id}/history/` — job events
alongside those from its tasks, estimates, change orders, invoices,
deliverables, shipments, and materials, each labelled with
`source_label`.

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
retention policy described in §7.7a.

### 7.7a Retention clock: finality-based purge

`EmailService.cleanup_old_temp_emails` (invoked by the
`cleanup_temp_emails` scheduled command) decides eligibility per
`TempEmail` row:

- **Unlinked** (the `EmailRecord` has no `job` / `purchase_order`):
  clock starts at `TempEmail.created_at`. Purged once
  `email_retention_days` have elapsed. This is the original behavior.
- **Linked to one or more of Job / PurchaseOrder**: the clock
  is the *finality date* of those records, not the email's own date.
  Each linked record contributes its own clock; the strictest one wins
  (the email is purged only when **every** linked record is past its
  retention window).
- A linked record's finality date is the timestamp of the most recent
  `HistoryEntry` recording a transition into a final status, scoped to
  that record. If no qualifying `HistoryEntry` exists for a final
  record (pre-history-tracking data, or created directly in a final
  state), we fall back to `TempEmail.created_at` for that link so
  emails aren't stuck unpurgeable.
- A linked record that is **not** currently in a final status keeps
  its emails indefinitely. The clock has not yet started.

Final-status sets ("practically done"):

| Model | Final statuses |
|---|---|
| `Job` | `completed`, `rejected`, `cancelled` |
| `PurchaseOrder` | `received_in_full`, `cancelled` |

(The Bill slice of the finality map was removed with the 2026-07-23 bill
retirement; a legacy `EmailRecord.bill` link no longer contributes a clock.)

`EmailRecord` rows are preserved permanently regardless of `TempEmail`
purge — the auditable record of an email having existed survives even
once its cached body and metadata are gone.

`email_retention_days` is editable in the Settings → Email tab
(gated on `can_manage_config`).

### 7.8 Email detail action panel

`EmailRecord` has two active association FKs — `job` and
`purchase_order`, both `on_delete=SET_NULL`. Any combination is valid;
the user chooses which apply per email. (The third FK, `bill`, is
retained-but-unused legacy schema since the 2026-07-23 bill retirement —
vendor-invoice emails link to the PO instead.)

`frontend/src/components/email/EmailActionPanel.svelte` is the
right-rail side panel on the email detail page (`EmailDetailPage.svelte`
lays out content + rail in a two-column flexbox). One section per
target (Job, Purchase Order). When the email is linked to that
target the section shows the linked entity as a navigation link plus a
Disassociate `<button>`; when unlinked it shows two `<a>`s styled like
buttons — *Create new* and *Link existing* — that route to the
respective Create-from-Email and Associate-with-Existing pages. Each
section is hidden when the viewer lacks the relevant permission atom
(`can_manage_jobs` for the Job section; `can_manage_financials` for
PO).

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
- `/email/:id/associate` → `EmailAssociatePage.svelte` (Job picker)
- `/email/:id/associate-po` → `EmailAssociatePOPage.svelte`

(The create-bill / associate-bill routes and pages were deleted with the
2026-07-23 bill retirement.)

`EmailRecordSerializer` exposes `job` + `job_number` and
`purchase_order` + `po_number`
read-only so the panel can render linked-entity labels without extra
fetches. (It no longer exposes `bill` / `vendor_invoice_number`.)

### 7.9 `EmailService` association helpers

`EmailService.associate_with(email_pk, target_field, target_pk)` and
`disassociate_from(email_pk, target_field)` are parameterized over the
two target fields (`'job'`, `'purchase_order'`), validated
against an allowlist (`'bill'` was removed from the allowlist with the
2026-07-23 retirement). The four Email-action API endpoints
(`link-to-job` / `unlink-from-job` / `link-to-po` / `unlink-from-po`)
route through these via a
`_link_email_to(target_field, body_key, …)` / `_unlink_email_from`
helper pair in `apps/api/email/views.py` so the views are
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
   association FK passed in `associate_with={'job'|'purchase_order':
   obj}`) + a `TempEmail` row holding the composed
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
- `EstimateEmailService` and `ChangeOrderEmailService`
  (`apps/estimates/services.py`) — both subclass the shared
  `DocumentEmailService` base (same module: class-level subject/body
  defaults, Configuration keys, labels, and hooks for the PDF
  generator and send validation). Each generates its PDF, calls
  `send_tracked` with `associate_with={'job': …}`, and transitions
  `draft → open` on send success.
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
`{contact_business}`, `{my_user_name}` (the requesting user's full
name, falling back to username — resolved via
`email_templates.user_display_name(request.user)`, wired through every
`get_email_defaults(doc, user=…)`; fixed 2026-07-22 after rendering
blank since inception), `{job_number}`, `{job_name}`,
`{document_number}`. Per-document aliases (`{estimate_number}`,
`{po_number}`, `{invoice_number}`, `{vendor_name}`) also work — and on
the Invoice template, `{document_number}`/`{invoice_number}` and
`{payment_link}` are **send-time** substitutions (see
invoicing-and-expenses.md). The shop's own business name isn't a
variable — users hard-code it into the boilerplate where they want it.

### 7.11 Reply correlation

`EmailService.correlate_reply(email_record)` runs at the tail of
`fetch_new_emails` and `fetch_emails_by_date_range`, after the
inbound `EmailRecord` + `TempEmail` are created. It walks
`TempEmail.in_reply_to` first, then the `references` chain
right-to-left, looking up each token against existing
`EmailRecord.message_id`. **The walk continues past parents that
exist but have no FKs to copy** — that lets a new reply inherit
context from a grandparent when the immediate parent happens to be
orphaned itself. The first parent that contributes at least one
non-null FK wins; its `job` / `purchase_order` values are
copied onto the new reply EmailRecord. Behavior is silent — no
"auto-linked via reply" badge; the action panel's existing
Disassociate handles any mis-correlated auto-links.

The `TempEmail` rows that drive this gain three columns:
`in_reply_to` (CharField, captures the immediate parent's
Message-ID), `references` (TextField, captures the full thread
chain), and `bcc_email` (TextField, populated only on outbound rows
since IMAP-fetched inbound can't see BCC).

### 7.11a Thread-wide association propagation

Every place that sets a `job` / `purchase_order` FK on an
EmailRecord — `EmailService.associate_with` (called by the
link-to-X endpoints and the create-X-from-email paths) and
`correlate_reply` (called at IMAP fetch time) — invokes
`EmailService.propagate_thread_association(email_record,
target_field)` afterwards. The propagation:

1. Reads the source EmailRecord's value for that field. No-op when
   it's null (nothing to propagate).
2. Calls `collect_thread_member_ids(email_record)` in
   `apps.core.email_utils` — a BFS over the RFC 5322 thread graph
   (Message-ID + In-Reply-To + References intersection) that
   returns every EmailRecord PK in the same thread. The BFS uses
   one DB round per expansion, capped at 8 rounds defensively;
   real threads converge in 1-2 rounds because each email's
   References field already encodes its full chain back to the
   root.
3. Bulk-updates every thread member where the target field is null
   to the source's value. **Doesn't overwrite a sibling already
   linked to a different target** — that's a deliberate human
   choice the propagation respects.

Bulk `.update()` skips `Model.save()` and the `@history` capture —
that's intentional. The user-initiated event on the source
EmailRecord IS the audited action; the propagated set is the
implicit consequence the design promises, and writing a per-row
history entry for each sibling would flood the activity feed.

Disassociate doesn't propagate. Per-email is the surgical tool the
user reaches for when a sibling really doesn't belong.

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
panel (Job / PO associations + Reply controls) stays visible
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
  `purchase_order_id`).
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
/ PO the outbound was associated with.

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



### Setup gating (gradual setup)

`GET /api/setup/status/` (`apps/core/setup_gates.gate_status`) returns
per-area `{available, message}` from **live predicates** (no stored flag;
spec: docs/plans/qbo-setup-import-spec.md Part 3). Consumers:
`stores/setupStatus.js` (refreshed on auth and after gate-flipping
actions), the Sidebar (unavailable entries render as greyed spans with a
`SetupCallout` floating hint on hover), an App-level route guard
(gated prefixes redirect Home), and the Home HelpPanel's
"Finish setting up" checklist. Areas/predicates live in the endpoint —
docs must not duplicate the table.

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
Schedule
Activity
Contacts
Email
Purchasing         → /purchase-orders
Catalog            → /catalog
─── Financials ─── (label only if user has can_manage_financials)
Invoices           (can_manage_financials) → /invoices
Expenses           (can_manage_financials)
─── Admin ───      (label only if user has can_manage_config)
Users              (can_manage_config)
Settings           (can_manage_config)
[spacer]
LITE | FULL        (view-mode toggle)
─────────────
<username>         → /profile
Logout
```

**Route-based tab areas.** Some sidebar destinations are themselves a strip
of tabs — e.g. Catalog (`/catalog`, `/catalog/service-items`,
`/catalog/earmarks`; `docs/designs/materials-inventory-and-purchasing.md`
§17). The convention there is **real routes, not local `$state` tabs**: each
tab is its own `App.svelte` route, the strip is `<a use:link>` (links
navigate; buttons act, per the UI Decisions in `CLAUDE.md`), and refresh /
back-button / bookmarks land on the right tab. Settings and JobHistory still
use local-state tabs (`$state('pricing')` + `{:else if}`) — converting those
to routes is noted as future work, not yet done.

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
| `cleanup_temp_emails` | `cleanup_temp_emails` | Deletes cached `TempEmail` rows whose retention clock has elapsed (preserves `EmailRecord`; no per-object history). See §7.7a for the finality-based clock rule. |

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

- **Negative-price sanity check on line items.** All the line-item
  subclasses (Estimate, Invoice, PO) accept any decimal price
  with no validation. Negative values are legitimate (discount lines,
  credits), but typos that flip a sign go through silently. A serializer-
  or service-level warning (not a hard reject) would catch obvious
  mistakes. Concern is shared across the subclasses since it lives
  on `BaseLineItem`.

- **`accounting_category` required on the line-item subclasses
  (`EstimateLineItem`, `InvoiceLineItem`, `PurchaseOrderLineItem`).**
  Currently nullable (inherited from
  `BaseLineItem`); a null AC falls back to silently tax-exempt at QBO
  push time. Should become NOT NULL after existing rows are backfilled.
  One project-wide migration across the subclasses — the change
  lives in `apps/core/models.py` (`BaseLineItem`) plus a backfill step
  per subclass.

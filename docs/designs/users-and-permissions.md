# Users and Permissions

Authoritative reference for the user model, permission atoms, authentication, owner-side user administration, and self-service profile. Login tracking is documented here as a preserved design (not implemented).

## Scope

This doc owns:

- The `User` model and its custom permission atoms
- The four permission atoms and the DRF permission classes derived from them
- Authentication endpoints (`/api/auth/`)
- Owner-side user admin (`/api/users/` and the SPA `/users` pages)
- Self-service profile (`/api/auth/me/` and the SPA `/profile` page)
- The login-tracking design (preserved verbatim-ish, not built)

Permissions are atom-only. Django Groups are not used by this project — `set_permissions` writes directly to `user_permissions`, and the admin UI uses per-atom checkboxes.

Sibling docs that cover the surrounding mechanics:

- `architecture-and-conventions.md` — session authentication, CSRF, DRF mixins, DELETE-200-JSON convention, two-phase delete pattern, `lib/api.js`
- The "Permissions" section of `CLAUDE.md` — short-form atom-to-action summary

## User model

`apps.core.models.User` is an `AbstractUser` subclass with two extra fields and the project's custom permission atoms.

| Field | Type | Notes |
|---|---|---|
| `contact` | `OneToOneField(contacts.Contact, on_delete=SET_NULL, null, blank)` | Optional link to the Contact record representing this user as a person. Nullable — many user accounts have no Contact yet. |
| `schedule_envelope` | `JSONField(null, blank)` | The user's personal weekly work envelope (canonical week-envelope shape, validated by `apps.schedule.calendar_arithmetic.validate_week_envelope`). Null = use the shop default (`schedule_week_envelope` Configuration key). Added in migration `core.0025`. See `schedule.md` §2. |
| (inherited) | `AbstractUser` fields | `username`, `email`, `first_name`, `last_name`, `password`, `is_active`, `is_staff`, `is_superuser`, `date_joined`, `last_login`, `user_permissions`, `groups`. |

`Meta`:

- `db_table = 'auth_user'`
- `permissions = [...]` — the four custom atoms (see next section)

`AUTH_USER_MODEL = 'core.User'` in `minibini/settings.py`.

### Flag semantics

| Flag | What it does | How the project uses it |
|---|---|---|
| `is_active` | Django blocks authentication entirely when `False`. | The primitive for "deactivate user". User-admin endpoints flip this; the assignee dropdown filters on it. |
| `is_staff` | Permits login at `/admin/`. | Set on dev seed data; never read by production code. Orthogonal to the atom system. |
| `is_superuser` | `user.has_perm(anything)` returns `True` unconditionally — Django built-in `ModelBackend` behaviour. | Bypasses every atom check. Set on `dev_user` and in some tests. Surfaced read-only in the user admin UI; never editable from the SPA. Create new superusers with `manage.py createsuperuser`. |

Inactive users never reach atom checks because authentication itself fails first. `is_superuser=True` and atom membership are independent paths to "full access" — removing an atom does nothing if the user is a superuser.

## Permission atoms

The project defines four custom permission atoms on `User.Meta.permissions`:

| Atom | Scope |
|---|---|
| `can_manage_jobs` | Full CRUD on jobs, estimates, worksheets, plan-tasks, contacts, businesses. Status transitions on each. Cancel/reorder tasks and mark all a job's work complete. Email-to-job actions: link, unlink, create-job-from-email. (Adding/editing/deleting and completing individual tasks is open to any authenticated user — see below.) A Job's `project_manager` gets this atom's powers **scoped to that one job** via `CanManageJobOrPM` — see "Project-manager object access". |
| `can_manage_financials` | Full CRUD on invoices, purchase orders, bills, price-list items, and their line items. Status transitions (issue, cancel). Expenses/reimbursements writes. Email-to-PO / email-to-bill actions: link, unlink, create-po-from-email. |
| `can_manage_time` | Edit or delete any user's bleps and shifts, clock another worker in/out, and approve/deny shift & blep change requests. (Tracking, clocking, or editing one's own recent time is `IsAuthenticated`.) |
| `can_manage_config` | Settings endpoint, work templates, accounting categories, user admin viewset, QBO connection management. Service-item (the saved-work catalog) writes are shared three ways — see the endpoint table. |

DRF permission classes in `apps/api/permissions.py`:

```python
CanManageJobs            = atom_permission('can_manage_jobs')
CanManageFinancials      = atom_permission('can_manage_financials')
CanManageTime            = atom_permission('can_manage_time')
CanManageConfig          = atom_permission('can_manage_config')
CanManageTimeOrFinancials  # OR of the two — gates the payroll shift report
```

`atom_permission(codename)` is a factory returning a `BasePermission` subclass whose `has_permission` calls `request.user.has_perm(f'core.{codename}')`.

### `IsAuthenticated` (no atom)

Any logged-in user gets read access to jobs, estimates, worksheets, tasks, bleps, contacts, businesses, payment terms, templates, accounting categories, search, price-list items, invoices, purchase orders, bills, and emails. They also get write access to notes on jobs/contacts/businesses, can add / edit / delete tasks on existing jobs (delete blocked when the task has Bleps or is in_progress/complete) and complete individual tasks, and can track their own time and submit their own expenses.

### `is_superuser` bypass

`is_superuser=True` short-circuits every permission check. A superuser does not need any atom. The owner-side admin UI surfaces this flag read-only with a note; it cannot be toggled through the API. Creating a new superuser is a developer task (`manage.py createsuperuser`).

### Implicit (any authenticated user)

- Track own time (clock in/out, start/stop bleps)
- Submit own expenses
- View own expenses and time entries

## Project-manager object access

A Job's `project_manager` (nullable FK to User, `related_name='managed_jobs'`) gets `can_manage_jobs`-equivalent access to **that one job and its contained objects** — without holding the global atom. This lets a job be delegated to someone who isn't a shop-wide manager.

**The predicate.** `JobService.user_can_manage(user, job)` (in `apps/jobs/services.py`) is the single source of truth:

```python
user.has_perm('core.can_manage_jobs')  # atom holders & superusers
    or job.project_manager_id == user.id  # the job's PM
```

It tolerates `AnonymousUser` / `job=None`. A companion, `JobService.user_holds_manage_jobs_atom(user)`, resolves *just* the atom (or superuser bypass, honouring `is_active`) with a single direct `user_permissions` query rather than `has_perm` — the serializer mixin caches its result per-request so list serialization of `can_manage` stays O(1) queries instead of N+1.

**The permission class.** `CanManageJobOrPM` (in `apps/api/permissions.py`) gates writes. It is **view-authoritative**: `has_permission` short-circuits `SAFE_METHODS`, passes atom holders, and otherwise resolves the request's target Job (looked-up instance, job-nested URL kwarg, or the create body's parent-Job field) via the view and PM-checks it — it does not rely on `has_object_permission` firing, because custom `@action`s don't all call `get_object()`. `has_object_permission` remains as defense-in-depth for the standard update/destroy path.

**The mixins** (in `apps/api/mixins.py`):
- `JobScopedPermissionMixin` — gives a viewset `get_object_job(obj)` and `get_permission_target_job(request)`. Configured per viewset with `job_object_path` (attribute chain instance → Job, e.g. `'self'`, `'job'`, `'est_worksheet.job'`, `'estimate.job'`, `'change_order.job'`), `job_create_field` (request-body key naming the parent Job on create), and `job_url_kwarg` (URL kwarg holding the job id on job-nested routes).
- `JobScopedCanManageMixin` — a serializer mixin adding a read-only `can_manage` boolean computed from `JobService.user_can_manage(request.user, <job>)`, where the job is reached via `can_manage_job_path`. The SPA gates per-object job-scoped edit affordances on this field instead of the global `$canManageJobs` store.

**Where `can_manage` is exposed / where PM writes are accepted.** The `can_manage` field is on the Job, EstWorksheet, Estimate, PlanTask(Detail), ChangeOrder, Deliverable, and Task serializers. `CanManageJobOrPM` gates writes on `JobViewSet`, `EstWorksheetViewSet`, `EstimateViewSet` (incl. its line items), `PlanTaskViewSet` (incl. material actions), `ChangeOrderViewSet` (incl. its line items), and the job-nested `DeliverableViewSet`. So a PM may manage the job's tasks, worksheets, plan-tasks, estimates, change orders, deliverables, and their line items.

**Explicitly NOT PM-scoped:**
- **Contacts and businesses** — they share the `can_manage_jobs` atom at the view layer but are not job-owned, so they stay **atom-only**. A PM gets no access to them through this mechanism.
- **Job create** — stays **atom-only** (there's no target job yet to be a PM of).
- The invoice-wizard OR-gate (`CanManageJobs | CanManageFinancials`) is unchanged.

### Endpoint-to-atom mapping

Default pattern: list/retrieve are `IsAuthenticated`; create / update / delete and most action endpoints require the resource's atom. Exceptions are called out in the "Special cases" subsection below. Several job-owned resources additionally accept the job's **project_manager** via `CanManageJobOrPM` — see "Project-manager object access" above and the per-row notes below.

| Resource | Read (list / retrieve) | Write (create / update / delete) | Notes |
|---|---|---|---|
| `/api/jobs/` | `IsAuthenticated` | `can_manage_jobs` **OR** the job's PM (`CanManageJobOrPM`) | create stays atom-only; several action exceptions — see below |
| `/api/contacts/` | `IsAuthenticated` | `can_manage_jobs` | atom-only — **not** PM-scoped |
| `/api/businesses/` | `IsAuthenticated` | `can_manage_jobs` | atom-only — **not** PM-scoped |
| `/api/payment-terms/` | `IsAuthenticated` | (read-only) | |
| `/api/estimates/` | `IsAuthenticated` | `can_manage_jobs` **OR** the job's PM (incl. line items) | also `send-defaults` (GET, IsAuth), `send` (POST, can_manage_jobs) |
| `/api/est-worksheets/` | `IsAuthenticated` | `can_manage_jobs` **OR** the job's PM | |
| `/api/tasks/` (flat lifecycle) | `IsAuthenticated` | `IsAuthenticated`; `cancel` requires `can_manage_jobs` **OR** the job's PM | service enforces ownership and lifecycle rules; on-behalf start/stop requires `can_manage_time` |
| `/api/plan-tasks/` (worksheet-side) | `IsAuthenticated` | `can_manage_jobs` **OR** the job's PM (incl. material actions) | retrieve open to all |
| `/api/bleps/` | `IsAuthenticated` | `IsAuthenticated` | service enforces 30h rolling rule + `can_manage_time` for editing others |
| `/api/shifts/` | `IsAuthenticated` | `IsAuthenticated` for `PATCH` (service enforces 30h self-edit window) | `DELETE` requires `can_manage_time` (200 + JSON body); `?user=me\|<id>`, `?since=` |
| `/api/shift-change-requests/` | `IsAuthenticated` (non-managers see only their own; `?mine=true`, `?status=`) | `IsAuthenticated` to create; `approve` / `deny` require `can_manage_time` | serializes a read-only `conflicts` list (the records the request collides with); a worker can't target another user's record (403 unless `can_manage_time`) |
| `/api/blep-change-requests/` | `IsAuthenticated` (non-managers see only their own; `?mine=true`, `?status=`) | `IsAuthenticated` to create; `approve` / `deny` require `can_manage_time` | a create-type (null `blep`) request requires `task`; same `conflicts` list + own-record rule as shifts |
| `/api/rate-schemes/` | `IsAuthenticated` | `can_manage_config` | `supersede` action also `can_manage_config` |
| `/api/work-templates/` | `IsAuthenticated` | `can_manage_config` | |
| `/api/service-items/` | `IsAuthenticated` | `can_manage_jobs` **or** `can_manage_financials` **or** `can_manage_config` (`CanManageJobsOrFinancialsOrConfig`) | Widened 2026-07 (was create: jobs-or-config, update/delete: config-only) so the Catalog area's Service Items tab lets any of the three atoms manage the shared catalog; list/retrieve stay `IsAuthenticated` (visible to every user in the Catalog UI) |
| `/api/accounting-categories/` | `IsAuthenticated` | `can_manage_config` | |
| `/api/invoices/` | `IsAuthenticated` | `can_manage_financials` | `send-defaults` (GET) IsAuth; `send` (POST) `can_manage_financials`. The legacy `send-to-qbo` was removed when the new send flow shipped. |
| `/api/purchase-orders/` | `IsAuthenticated` | `can_manage_financials` | |
| `/api/bills/` | `IsAuthenticated` | `can_manage_financials` | `send-to-qbo` also `can_manage_financials` |
| `/api/inventory/` (`InventoryItemViewSet`) | `IsAuthenticated` | `can_manage_financials` **or** `can_manage_config` | `order` action (`POST /api/inventory/{id}/order/` — order to stock, no material/job) is `can_manage_financials` only |
| `/api/earmarks/` (`EarmarkViewSet`) | `IsAuthenticated` | (read-only) | New — `ReadOnlyModelViewSet`, unpaginated, backs the Catalog Earmarks tab |
| `/api/materials/` | `IsAuthenticated` | `IsAuthenticated` | service enforces consumption-state and immutability rules |
| `/api/expenses/` | `IsAuthenticated` | `can_manage_financials` for update / destroy / reject / retry-sync | list / retrieve auto-scoped to `purchased_by=user` unless `can_manage_financials`; create open to authenticated |
| `/api/reimbursements/` | `can_manage_financials` | `can_manage_financials` | |
| `/api/users/` (admin) | `can_manage_config` | `can_manage_config` | DELETE returns 405 — use deactivate. Exception: the `schedule-envelope` action is `can_manage_time` **OR** `can_manage_config` — the one user-admin route open to time managers |
| `/api/auth/users/` (assignee dropdown) | `IsAuthenticated` | — | distinct from `/api/users/` |
| `/api/emails/` | `IsAuthenticated` | (no writes from this viewset) | reads only |
| `/api/emails/{id}/link-to-job/` etc. | — | `can_manage_jobs` | link-to-job, unlink-from-job, create-job |
| `/api/emails/{id}/link-to-po/` etc. | — | `can_manage_financials` | link-to-po, unlink-from-po, create-po |
| `/api/emails/{id}/link-to-bill/` etc. | — | `can_manage_financials` | link-to-bill, unlink-from-bill |
| `/api/emails/{id}/reply-defaults/` | `IsAuthenticated` | — | Pre-populated form payload for Reply / Reply All |
| `/api/emails/{id}/reply/` | — | `IsAuthenticated` | POST a reply (multipart); delegates to `send_tracked` |
| `/api/search/` | `IsAuthenticated` | — | |
| `/api/jobs/board/*` | `IsAuthenticated` | — | one bulk reorder endpoint requires `can_manage_jobs` |
| `/api/home/` | `IsAuthenticated` | — | |
| `/api/settings/` | `IsAuthenticated` | `can_manage_config` | including `/api/settings/units/` |
| `/api/qbo/*` | `can_manage_config` | `can_manage_config` | OAuth + connection state — see `quickbooks-integration.md` |

#### Special cases

- **Task add / edit / delete** — `POST /api/jobs/{id}/tasks/` (add a task) and `GET`/`PATCH`/`DELETE /api/jobs/{id}/tasks/{task_pk}/` (the `task_detail` action: read, edit, delete a task) are all `IsAuthenticated` — any authenticated user may add, edit, and delete a task. Delete is still blocked by `TaskService.delete_task` when the task is `in_progress`/`complete` or has Bleps (400) — that guard applies to everyone. (This revises the earlier policy where adding a task required `can_manage_jobs`.)
- **Cancelling a task** — `POST /api/tasks/{id}/cancel/` requires `can_manage_jobs` **OR** the task's job's PM (`CanManageJobOrPM`). The other flat task lifecycle actions (`complete`, `block`, `unblock`, `start-work`, `stop-work`, `cancel-work`, `actual-qty/add`) stay `IsAuthenticated` — they are worker operations.
- **Marking all the job's work complete** — `POST /api/jobs/{id}/work-complete/` and **`POST /api/jobs/{id}/reorder-tasks/`** require `can_manage_jobs` **OR** the job's PM (`CanManageJobOrPM`).
- **`POST /api/jobs/{id}/add-from-template/`** and **`POST /api/jobs/{id}/create_material/`** are `IsAuthenticated` only — workers can self-serve adding template-driven tasks and materials.
- **`POST /api/jobs/{id}/duplicate/`** requires `can_manage_jobs` **OR** the job's PM (`CanManageJobOrPM`). Duplicates the Job into a new one; body `{contact_id, path}`, returns `{job_id}` at 201.
- **`POST /api/jobs/{id}/start-invoice-wizard/`** accepts `can_manage_jobs` OR `can_manage_financials` — either side can spawn the draft so the other side can fill it.
- **`POST /api/jobs/{id}/notes/`**, **`POST /api/contacts/{id}/notes/`**, **`POST /api/businesses/{id}/notes/`** are `IsAuthenticated` — anyone can add a note.
- **`POST /api/shifts/clock-in/`**, **`POST /api/shifts/clock-out/`** are `IsAuthenticated` for self. Clocking another worker (via `?user=` / body `user`) requires `can_manage_time`; an unknown user id returns 404. Clock-out also closes the worker's open bleps.
- **`GET /api/shifts/active/`** is `IsAuthenticated` — the caller's own open shift (or `null`).
- **`GET /api/shifts/report/?start=&end=&user=`** (per-worker per-day payroll report) requires `can_manage_time` **OR** `can_manage_financials` (`CanManageTimeOrFinancials`). Financial staff can run payroll without the time-management atom.

#### Stub endpoints

501 stubs that need atom assignments when implemented:

- `POST /api/auth/refresh/` (placeholder for token refresh)
- `POST /api/emails/send/` (outbound email — `can_manage_jobs` is the natural fit)
- `GET /api/time-tracking/status/`, `GET /api/time-tracking/active/`

The previously-stubbed `POST /api/shifts/clock-in/` and
`POST /api/shifts/clock-out/` are now **live** (work-shifts feature) — see the
endpoint table and the special cases above.

## Portal endpoints

`/api/portal/` sits **outside the four-atom permission model entirely**.

- `AllowAny` permission class, `authentication_classes=[]` — no session required.
- Authorized by an opaque per-row `public_token` secret — `Estimate.public_token`
  for `/api/portal/estimates/<token>/…` and `ChangeOrder.public_token` for
  `/api/portal/change-orders/<token>/…` (GET + `accept` / `reject` /
  `request-changes`). The token is the bearer credential.
- The customer is **not a User**. There is no login, no session, and no
  `request.user`. Attribution for accept/reject actions is via an explicit
  `HistoryEntry` with `user=None` (entry_type `'action'`) — written by
  `EstimateService.update_status(actor=customer_dict)` for estimates, and by
  the CO portal view itself (`_record_customer_action`) for change orders.
- `is_superuser` bypass does not apply — there is no auth subject to bypass with.

The shop-side **send** endpoints that deliver these portal links are inside the
atom model: `GET/POST /api/estimates/{id}/send-defaults|send/` and
`GET/POST /api/change-orders/{id}/send-defaults|send/` require their owning atom
(`can_manage_jobs` for change orders).

See `estimates-and-prices.md` §14.10 (change orders) and §15.1 (estimates) for
the full endpoint tables and `architecture-and-conventions.md` §3.2 for the auth note.

## Authentication

Session authentication only — see `architecture-and-conventions.md` for the underlying DRF setup, CSRF handling, and `lib/api.js` client behaviour.

### Endpoints

All live under `/api/auth/` (`apps/api/auth/`):

| Method | Path | Permission | Purpose |
|---|---|---|---|
| `POST` | `/api/auth/login/` | `AllowAny` | Authenticate; sets session cookie; returns `UserSerializer` body. 400 on invalid credentials with `{"detail": "Invalid credentials."}`. |
| `POST` | `/api/auth/logout/` | `IsAuthenticated` | Clears session; returns `{"detail": "Logged out."}`. |
| `GET` | `/api/auth/me/` | `IsAuthenticated` | Returns the current user as `UserSerializer`. |
| `PATCH` | `/api/auth/me/` | `IsAuthenticated` | Updates own profile (`email`, `first_name`, `last_name`). Returns `UserSerializer` shape. |
| `POST` | `/api/auth/me/password/` | `IsAuthenticated` | Change own password. Returns `{"detail": "Password changed."}`. |
| `PUT` | `/api/auth/me/schedule-envelope/` | `IsAuthenticated` | Set (or reset) one's own weekly schedule envelope. Body `{"schedule_envelope": {...}}` (validated via `validate_week_envelope`) or `{"schedule_envelope": null}` to reset to the shop default. Returns the `UserSerializer` body. |
| `GET` | `/api/auth/users/` | `IsAuthenticated` | Lightweight assignee dropdown payload: `[{id, username, name}]` filtered to `is_active=True`, ordered by first name then username. Distinct from the admin `/api/users/` namespace. |
| `POST` | `/api/auth/refresh/` | `AllowAny` | 501 stub. Reserved for token refresh if/when the project moves off session auth. |

`UserSerializer` returns `{id, username, email, first_name, last_name, permissions, schedule_envelope}` where `permissions` is a sorted list of atom codenames the user effectively has (via `get_all_permissions()`, filtered to `core.can_*`) and `schedule_envelope` is read-only (writes go through the dedicated envelope endpoints). Superusers' `permissions` list reflects the framework view — Django reports all permissions for a superuser.

### Login flow (SPA)

1. `frontend/src/components/LoginPage.svelte` is shown when `$user` is `null` after the initial `checkAuth()` mount probe.
2. The form posts to `/api/auth/login/` via `frontend/src/stores/auth.js`'s `login(username, password)`. Success sets the `user` store; the SPA re-renders into the authenticated tree.
3. `checkAuth()` on subsequent loads calls `GET /api/auth/me/` to populate the store from the existing session.
4. After login the SPA lands on **Home** (`#/`), where the Clock In / Out band and the Time tab live — the worker's first action on arrival is typically to clock in.

## User admin

`apps/api/users/` — viewset, serializers, service, URL registration. Mounted at `/api/users/`. All actions require `[IsAuthenticated, CanManageConfig]`, with one exception: the `schedule-envelope` action is `CanManageTime | CanManageConfig` — schedule planning is a time-domain concern, so time managers get this single write without full user-admin power. Everything else on `/api/users/` stays `can_manage_config`-only.

### Endpoints

| Method | Path | Action | Body / Returns |
|---|---|---|---|
| `GET` | `/api/users/` | list | Plain JSON array (no pagination). `UserListSerializer`. Ordered `-is_active, username` so active users appear first. |
| `POST` | `/api/users/` | create | `UserCreateSerializer` in; `UserDetailSerializer` out at 201. |
| `GET` | `/api/users/:id/` | retrieve | `UserDetailSerializer`. |
| `PATCH` | `/api/users/:id/` | partial_update | `UserUpdateSerializer` in; `UserDetailSerializer` out. |
| `DELETE` | `/api/users/:id/` | destroy | **405 Method Not Allowed** — use deactivate instead. |
| `POST` | `/api/users/:id/activate/` | activate action | `UserDetailSerializer`. |
| `POST` | `/api/users/:id/deactivate/` | deactivate action | `UserDetailSerializer`. |
| `POST` | `/api/users/:id/reset-password/` | reset_password action | `PasswordResetSerializer` in; `{"detail": "Password reset."}` out. |
| `PUT` | `/api/users/:id/permissions/` | permissions action | `PermissionsUpdateSerializer` in; `UserDetailSerializer` out. |
| `PUT` | `/api/users/:id/schedule-envelope/` | schedule_envelope action | `{"schedule_envelope": {...}\|null}` in (`ScheduleEnvelopeSerializer`, shared with the self-service endpoint; null resets the user to the shop default); `UserDetailSerializer` out. **Permission: `can_manage_time` OR `can_manage_config`** — the one user-admin route open to time managers. |

`pagination_class = None` — small shops, small lists. Revisit if user counts grow beyond a few hundred.

### Serializers

- **`UserListSerializer`** — `id, username, first_name, last_name, email, is_active, is_superuser, permissions`. All read-only. `permissions` is the user's directly granted atom codenames (filtered to `core.can_*`), sorted.
- **`UserDetailSerializer`** — list fields plus `date_joined` and `schedule_envelope`. All read-only. The viewset writes via `UserUpdateSerializer` and the dedicated action serializers, then returns this for the response body.
- **`UserCreateSerializer`** — `username, email, first_name, last_name, password, password_confirm`. All required. `email` is `EmailField`. `first_name` and `last_name` override Django's default `blank=True` to required. Passwords are `write_only`, validated against `AUTH_PASSWORD_VALIDATORS`, must match. `create()` calls `User.objects.create_user(...)` (which hashes the password). New users default to `is_active=True` and have zero atoms — the admin grants atoms separately via the permissions endpoint.
- **`UserUpdateSerializer`** — `username, email, first_name, last_name`. All optional. Admins CAN change username here (unlike the self-service serializer). The fields allowlist is the privilege-escalation guard: `password`, `is_active`, `is_staff`, `is_superuser`, `user_permissions`, `groups` are not in the list and are ignored even if sent.
- **`PasswordResetSerializer`** — pure `Serializer` (not `ModelSerializer`). `password`, `password_confirm`, both write-only. Runs `validate_password`. `save()` calls `target.set_password(...); target.save(update_fields=['password'])`. Does NOT call `update_session_auth_hash` — that's only meaningful for the actor's own session. Target's existing sessions are invalidated on their next request (Django checks the session auth hash against the stored hash).
- **`PermissionsUpdateSerializer`** — pure `Serializer`. `permissions = ListField(child=CharField, allow_empty=True)`. Validates every codename is one of the four atoms by deriving the known set from `User._meta.permissions` at import time. Unknown codenames raise `'Unknown permission codename(s): ...'`.

### `UserAdminService`

`apps/api/users/services.py`. Owns all business logic. Viewset is a thin wrapper.

**Public methods:**

| Method | Purpose |
|---|---|
| `deactivate_user(actor, target)` | Self-lockout checks, then flip `is_active=False`, close open bleps, kill sessions. |
| `activate_user(actor, target)` | Flip `is_active=True`. No side effects. |
| `set_permissions(actor, target, atom_codenames)` | Lockout checks, then replace `target.user_permissions` M2M with the matching `Permission` rows. |
| `_kill_sessions_for_user(user)` | Iterate `Session` table, decode each, delete those matching the target's pk. |

`reset_password` is handled inside the serializer's `save()` (the service does not own it — by design the password reset is a one-line `set_password/save` call).

**Lockout checks:**

- **D1 (self-deactivate)**: `actor.pk == target.pk` blocks deactivation with `'You cannot deactivate yourself.'`
- **D2 (remove own admin atom)**: actor is target, the new atom set lacks `can_manage_config`, and the target currently has `can_manage_config` → `'You cannot remove your own can_manage_config permission.'`
- **D3 (last admin)**: target currently has `can_manage_config`, the operation would leave them without it, and they are the only active user with that atom → `'Cannot deactivate the last user who can manage config.'` or `'Cannot remove can_manage_config from the last user who has it.'`

Last-admin count query:

```python
User.objects.filter(
    is_active=True,
    user_permissions__codename='can_manage_config',
    user_permissions__content_type__app_label='core',
).distinct().count()
```

**Deactivation side effects:**

- `BlepService.close_user_open_bleps(target)` — public wrapper around the internal `BlepService._close_open(user=target)`. Closes any open time entries the deactivated user had running.
- `_kill_sessions_for_user(target)` — iterates `django.contrib.sessions.models.Session`, decodes each, deletes those whose `_auth_user_id` matches the target. Forces logout in any active browser. Iteration is fine for small shops; revisit if the session table grows large.
- Does NOT auto-unassign the user's tasks. Managers reassign manually.

### Activation

`activate_user` is intentionally minimal: flip the flag, no blep reopening, no session restoration, no permission mutation. There are no lockout checks — activating a user can never take anyone offline.

### Password reset

Admin enters a new password directly. The serializer:

1. Validates `password` against Django's configured `AUTH_PASSWORD_VALIDATORS`.
2. Validates `password == password_confirm`.
3. Calls `target.set_password(new); target.save(update_fields=['password'])`.

If `actor == target` (an admin resetting their own password through this endpoint), their own current session is also invalidated on next request. They must log in again with the new password. The graceful in-session change path is `POST /api/auth/me/password/`.

### Frontend

| Route | Component | Purpose |
|---|---|---|
| `/users` | `frontend/src/routes/users/UserListPage.svelte` | List all users with a compact permissions column (short labels). Active first, deactivated grouped below. "New user" link. |
| `/users/new` | `frontend/src/routes/users/UserCreatePage.svelte` | Create form. On success pushes to the new user's detail page. |
| `/users/:id` | `frontend/src/routes/users/UserDetailPage.svelte` | Independent sub-forms (Profile, Permissions, Reset password, Account status, Schedule — an `EnvelopeEditor` writing `PUT /api/users/:id/schedule-envelope/`) plus a `UserReimbursementPanel` for expenses. Self-lockout hints rendered client-side; D3 (last-admin) is server-only. |

The sidebar Users link gates on `hasPerm('can_manage_config')`. The atom labels and codename list are hardcoded in `UserDetailPage.svelte` (`ATOMS` array, four entries). The component uses `currentUser` from the auth store to compute `isSelf` and disable the deactivate button and the `can_manage_config` checkbox when applicable.

The list page renders permissions with a short-label dictionary: `can_manage_jobs → "jobs"`, `can_manage_financials → "financials"`, `can_manage_time → "time"`, `can_manage_config → "config"`.

## Self-service profile

`apps/api/auth/views.py` extends `me_view` to accept `PATCH` and adds `change_password_view` and `me_schedule_envelope_view`. All require `IsAuthenticated` only — every user manages their own account.

### `PATCH /api/auth/me/`

`MeUpdateSerializer` on `User` with `fields = ['email', 'first_name', 'last_name']`. Partial update. Fields not listed (`username`, `password`, `is_active`, `is_staff`, `is_superuser`, `user_permissions`, `groups`) are silently ignored — this is the privilege-escalation guard. Returns the `UserSerializer` body so the frontend can update its store.

### `POST /api/auth/me/password/`

`PasswordChangeSerializer` (pure `Serializer`):

- `current_password` — required, validated via `user.check_password(value)`. Wrong current → `400 {"current_password": ["Current password is incorrect."]}`.
- `new_password` — required, run through `django.contrib.auth.password_validation.validate_password(value, user)`. Validator messages re-raised as a DRF list under the `new_password` key.
- `new_password_confirm` — required. Mismatch raises `{"new_password_confirm": ["Passwords do not match."]}`.
- `save()` calls `user.set_password(new); user.save()`.

After `serializer.save()`, the view calls `update_session_auth_hash(request, user)` so the user's own session survives the change. Returns `{"detail": "Password changed."}`.

### `PUT /api/auth/me/schedule-envelope/`

`me_schedule_envelope_view` (`IsAuthenticated`, self only). Body `{"schedule_envelope": {...}}` or `{"schedule_envelope": null}` (null resets to the shop default). `ScheduleEnvelopeSerializer` validates the payload via `apps.schedule.calendar_arithmetic.validate_week_envelope` and the view writes `request.user.schedule_envelope`. The editing surface is the bottom of the Home → Time tab (`MyEnvelopeEditor`, wrapping the shared `EnvelopeEditor` component that Settings → Schedule and the user-admin profile page also use). See `schedule.md` §2.

### Frontend

`frontend/src/routes/ProfilePage.svelte` — two independent forms (account info, change password) plus the view-mode toggle. Initializes from the `$user` store on first render; updates the store after a successful profile PATCH so the sidebar username stays in sync.

- Account form fields: `email`, `first_name`, `last_name`. Username is shown read-only.
- Password form fields: `current_password` (autocomplete `current-password`), `new_password` and `new_password_confirm` (both `new-password`).
- Field-level errors rendered via `fieldErrors(errorsObject, fieldName)` from `frontend/src/lib/formErrors.js`.

## Login tracking — DESIGNED, NOT YET IMPLEMENTED

Preserved here so a future implementer can act on it. Nothing in this section is built. `frontend/src/components/home/RecentLoginsList.svelte` is a static placeholder ("Not yet implemented"). There is no `LoginEvent` model, no signal handler, no `recent_logins` field on the home payload, no prune command.

### Purpose

Record a history of successful logins per user so the home page (and a future security/account-review screen) can display "your recent logins over the last N days". Django's `User.last_login` is a single overwritable timestamp — insufficient.

### Non-goals

- Not an admin audit log. A broader audit trail is a separate concern.
- Not a session manager — no "log out this device" enforcement.
- Not rate limiting or brute-force protection.
- No tracking of failed login attempts (first pass).

### Model

New model in `apps/core/models.py`:

```python
class LoginEvent(models.Model):
    user = models.ForeignKey(
        'core.User', on_delete=models.CASCADE,
        related_name='login_events',
    )
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        db_table = 'login_events'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', '-timestamp']),
        ]
```

Rationale:

- `CASCADE` on user — personal history, not admin audit. Deleting a user takes their login history with them.
- `ip_address` and `user_agent` nullable/blank so unusual login paths (management commands, tests, proxy misconfigs) don't crash the handler.
- Compound `(user, -timestamp)` index supports "most recent N for this user".

### Recording logins

Signal handler on `django.contrib.auth.signals.user_logged_in`. Fires for every successful auth path — DRF session login, the Django admin, the `login()` view, any custom `django.contrib.auth.login()` call.

```python
# apps/core/signals.py
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from .models import LoginEvent


def _client_ip(request):
    if request is None:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR') or None


@receiver(user_logged_in)
def record_login_event(sender, request, user, **kwargs):
    LoginEvent.objects.create(
        user=user,
        ip_address=_client_ip(request),
        user_agent=(request.META.get('HTTP_USER_AGENT', '') if request else '')[:500],
    )
```

Connect the signal in `apps/core/apps.py`'s `ready()`.

Edge cases:

- `request` can be `None` when `login()` is called programmatically (tests, scripts). Handler must tolerate this.
- `HTTP_X_FORWARDED_FOR` may be spoofed. Trust only when running behind a known reverse proxy. Production needs a `TRUSTED_PROXIES` story; dev/tests are fine.
- User agent truncated to 500 chars to defend against pathological headers.

### Retention

First pass: query-time filter only. Consumers query with `timestamp__gte = now - timedelta(days=14)`. Rows accumulate indefinitely.

For a small-shop deployment this is negligible storage (tens of rows per user per week). If pruning becomes necessary, add a cron-driven management command:

```python
# apps/core/management/commands/prune_login_events.py
class Command(BaseCommand):
    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=90)
        LoginEvent.objects.filter(timestamp__lt=cutoff).delete()
```

Scheduling would live alongside the existing crontab config. Out of initial scope.

### API

Extend `HomeService.get_home_data(user)` to include a `recent_logins` key:

```json
{
  "assigned_tasks": [...],
  "recent_jobs": [...],
  "recent_logins": [
    {"timestamp": "2026-04-04T08:13:22Z", "ip_address": "192.0.2.10"}
  ]
}
```

Query:

```python
cutoff = timezone.now() - timedelta(days=14)
LoginEvent.objects.filter(
    user=user, timestamp__gte=cutoff,
).order_by('-timestamp')
```

No separate endpoint initially — the home widget is the only consumer. Add `GET /api/login-events/` later if a profile/security screen wants paginated access.

User agent is kept in the DB for future support investigation but omitted from the API payload by default — long, mostly uninformative to end users, privacy-adjacent.

### Frontend

Replace the placeholder `RecentLoginsList.svelte`:

- Takes a `logins` prop (the `recent_logins` array from the home payload).
- Plain list, one row per login: localised timestamp + IP address.
- Empty state: "No logins in the last 14 days" — though the current session itself should produce at least one row.

`Home.svelte` passes the prop through the same way it does for `recent_jobs`.

The component already exists at `frontend/src/components/home/RecentLoginsList.svelte` as a static stub; its contents need to be replaced with the design above.

### Testing

- `LoginEvent` model: field defaults; query uses the compound index.
- Signal handler: `self.client.login(...)` creates a row; logout does not; programmatic `login(request=None, ...)` does not crash.
- Home payload: includes `recent_logins` scoped to the requester; excludes events older than 14 days; ordered most-recent first.
- Failed login attempts do not create rows (sanity check).

### Migration

`python manage.py makemigrations core` — creates `login_events` and indexes. Per CLAUDE.md, only the human operator applies migrations.

### Open questions

- **Trusted proxy configuration for `X-Forwarded-For`.** The app runs behind nginx per `docker-compose`. Production should only trust `X-Forwarded-For` when the immediate upstream is a known proxy. Dev doesn't care. Could tie into a future `TRUSTED_PROXIES` setting.
- **Logout tracking?** Not in this design. Rarely interesting to users, and `user_logged_out` doesn't fire reliably for expired sessions or closed browsers.

## Unfinished work

| Item | Source | Notes |
|---|---|---|
| Implement login tracking end-to-end | `2026-04-04-login-tracking.md`, this doc | Model, signal, home-payload extension, retention command, frontend list. `RecentLoginsList.svelte` is the placeholder. |
| Deactivated-assignee visual indicator | `2026-04-10-user-admin-design.md` | Wherever a username/assignee renders (task cards, detail pages, task lists, history feed, search results) show "(deactivated)" or a greyed style when `is_active=False`. Requires an audit of all assignee-rendering components. |
| User-to-Contact association in user admin UI | `2026-04-10-user-admin-design.md` | `User.contact` is already nullable; the admin form does not yet let the owner link or create a Contact. |
| Admin-action history logging | `2026-04-10-user-admin-design.md` | `HistoryEntry` already supports it; create/deactivate/reset/re-permission events should be logged. |
| Forgot-password email flow | `2026-04-10-user-admin-design.md`, `2026-04-10-user-self-service-design.md` | Requires email-sending infra. |
| Atom assignments for the stub endpoints | `2026-03-24-permission-atom-redesign.md` | `/api/emails/send/`, `/api/auth/refresh/`, and `/api/time-tracking/{status,active}/` are 501 stubs needing permission gating when implemented. (`/api/shifts/...` is now live — see the endpoint table above.) |

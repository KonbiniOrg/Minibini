# User Self-Service Profile — Design

**Date:** 2026-04-10
**Scope:** Let a logged-in user view and update their own `User` record (profile fields + password). First half of this session's user-management work; owner-side user admin is a separate design.

## Goals

- A user can edit their `email`, `first_name`, and `last_name`.
- A user can change their own password (requires current password).
- The user stays logged in after a successful password change.
- No changes to `username` (admin-only, out of scope).
- No interaction with the linked `Contact` record — User fields only.

## Non-goals

- Creating or deleting users (owner-side feature, separate design).
- Password reset via email ("forgot password").
- 2FA, email-change confirmation, avatar, account deletion.
- History/audit logging of profile or password changes.
- Reusing Django's template-based `PasswordChangeView` / `UserChangeForm` (wrong shape for a DRF+SPA architecture).

## Reuse from Django

We deliberately do **not** use Django's built-in auth views or forms — they target server-rendered templates and don't fit the DRF+Svelte architecture. We **do** reuse four framework utilities:

- `user.check_password(raw)` — verify current password
- `user.set_password(raw)` — hash and store new password
- `django.contrib.auth.password_validation.validate_password(password, user)` — run the configured `AUTH_PASSWORD_VALIDATORS`
- `django.contrib.auth.update_session_auth_hash(request, user)` — keep the current session valid after a password change

## Django built-ins: what we use and what we don't

Context for future work on the `User` model and related features. Captured here because it came up while brainstorming this feature.

### Auth framework (`django.contrib.auth`) — heavily used

- `AbstractUser` as the base for our `User` model (`apps/core/models.py`), with `AUTH_USER_MODEL = 'core.User'`
- `authenticate()` / `login()` / `logout()` in `apps/api/auth/views.py`
- `@login_required` / `@permission_required` decorators in HTML views
- `Group` and `Permission` models — our atom permissions are rows in `auth_permission` with codenames `can_manage_jobs`, etc.; the default Worker/Admin/Bookkeeper/Manager/Owner groups in `auth_group`
- `ModelBackend` permission resolution — this is where the `is_superuser` → `has_perm() == True` bypass lives
- Password hashing (`set_password`, `check_password`), `AUTH_PASSWORD_VALIDATORS`
- Session-based authentication via `django.contrib.sessions`

### Django admin (`django.contrib.admin`) — stopgap use only

- Installed in `INSTALLED_APPS` and mounted at `/admin/` (`minibini/urls.py`)
- `LOGIN_URL = '/admin/login/'` in `settings.py` is a stale interim bridge — predates the SPA login page. Anyone who hits a Django-side `@login_required` view while logged out lands on the admin login form, not the SPA login. **Should be fixed separately** (not part of this feature).
- Registered ModelAdmins:
  - `apps/core/admin.py` — `AccountingCategory` only (not `User`, not `Configuration`, not `HistoryEntry`)
  - `apps/qbo/admin.py` — `QBOConnection` (with `access_token`/`refresh_token` readonly), `QBOSyncLog`
  - `apps/estimates/admin.py` — empty file (`startapp` leftover, harmless)
- None of the core business models (Job, WorkOrder, Estimate, Invoice, Contact, Business, etc.) are registered
- **The admin's role in this project is stopgap UI for low-frequency, developer-adjacent configuration** — not a user-facing interface. Workers, managers, and owners live in the SPA.
- **`User` is not registered with the admin.** The only ways to edit a user today are `./manage.py createsuperuser`, `./manage.py changepassword`, or direct shell/SQL. This feature is the first user-editing UI in the project.

### Django flags on `AbstractUser` and how they interact with our atoms

| Flag | Django behavior | Used in our code? | Interacts with atoms? |
|---|---|---|---|
| `is_active` | `False` → cannot authenticate at all | Read in `apps/api/auth/views.py:47` (assignee dropdown filter). Otherwise dormant. | Indirectly — inactive users never get as far as an atom check. Correct primitive for "deactivate user". |
| `is_staff` | `True` → can log into `/admin/` | Set in dev seed data and test fixtures; never read by production code. | No. Orthogonal. |
| `is_superuser` | `True` → `user.has_perm(anything)` returns `True` unconditionally (Django built-in, not our code) | Set in tests as a permission-bypass shortcut. Set for `dev_user` in seed data. Never read directly. | **Yes — silently bypasses every atom check.** This creates two independent paths to "full access": (1) membership in the Owner group (atom-based), or (2) `is_superuser=True` (framework bypass). Removing a user from the Owner group does nothing if they are also a superuser. |

### Implications for this feature and the owner-side feature

- **Self-service (this feature):** None of these flags should be editable via `/api/auth/me/`. The serializer excludes them by listing only `email`, `first_name`, `last_name`. Test #6 explicitly verifies that sending `is_staff`, `is_superuser`, or `is_active` in the PATCH body does not change those flags.
- **Owner-side user management (next session):** `is_active` is the right primitive for "deactivate user" and should be exposed. `is_staff` should probably stay dev-only — the business UI should cover everything a non-developer owner needs, so there's no reason to grant a user Django admin access. `is_superuser` should not be exposed through the UI at all; if a new superuser is needed, `createsuperuser` on the command line is the right tool. The owner UI should, at most, surface `is_superuser` read-only with a note that the atom system does not apply to that user.

### Other Django built-ins we use

- `django.contrib.sessions` — required for session auth; used by DRF's `SessionAuthentication`
- `django.contrib.messages` — used by HTML function-based views; not used by SPA paths
- `django.contrib.contenttypes` — required by `auth` for the permission system
- `django.contrib.staticfiles` — standard static file handling

## Backend

### Endpoints

**`GET /api/auth/me/`** — unchanged. Already returns `{id, username, email, first_name, last_name, permissions}`.

**`PATCH /api/auth/me/`** — new.
- Permission: `IsAuthenticated`
- Body: any subset of `{email, first_name, last_name}`
- Serializer: `MeUpdateSerializer(ModelSerializer)` on `User` with `fields = ['email', 'first_name', 'last_name']`, all optional. Partial update.
- Response: 200 with the same body shape as `GET /api/auth/me/` (reuse `UserSerializer`).
- Errors: 400 with DRF default field-level error shape.
- Fields not listed in the serializer (`username`, `is_staff`, `is_superuser`, `permissions`) are silently ignored — this is the privilege-escalation guard and is covered by tests.

**`POST /api/auth/me/password/`** — new.
- Permission: `IsAuthenticated`
- Body: `{current_password, new_password, new_password_confirm}` — all required.
- Serializer: `PasswordChangeSerializer(serializers.Serializer)`
  - `validate_current_password` → `user.check_password(value)`; raise `ValidationError("Current password is incorrect.")` if false.
  - `validate_new_password` → wrap `django.contrib.auth.password_validation.validate_password(value, user)`; catch `django.core.exceptions.ValidationError` and re-raise as `rest_framework.serializers.ValidationError(list(e.messages))` so DRF renders the validator messages as a list.
  - `validate()` → if `new_password != new_password_confirm`, raise `ValidationError({'new_password_confirm': ['Passwords do not match.']})` so the error lands on that specific field.
  - `save()` → `user.set_password(new_password); user.save()`.
- View: after `serializer.save()`, call `update_session_auth_hash(request, user)` so the active session isn't invalidated.
- Response: 200 with `{'detail': 'Password changed.'}` (never 204 — project convention is that all API responses have a JSON body).

### File layout

- `apps/api/auth/serializers.py` — add `MeUpdateSerializer`, `PasswordChangeSerializer`. Keep `UserSerializer` as-is.
- `apps/api/auth/views.py` — extend `me_view` to handle `PATCH` in addition to `GET` (`@api_view(['GET', 'PATCH'])`); add `change_password_view`.
- `apps/api/auth/urls.py` — add `path('me/password/', change_password_view, name='auth-password-change')`.

## Frontend

### Page

Rewrite `frontend/src/routes/ProfilePage.svelte`. It's already wired to `/profile` in `App.svelte` and linked from `Sidebar.svelte` via the username link.

### Layout

Semantic HTML, no CSS framework, following the project's template conventions:

```
<h2>Profile</h2>

<h3>Account info</h3>
<form>  <!-- profile form -->
  username (read-only text display)
  email
  first_name
  last_name
  [Save]
  inline success / error messages
</form>

<h3>Change password</h3>
<form>  <!-- password form -->
  current_password
  new_password
  new_password_confirm
  [Change password]
  inline success / error messages
</form>

<h3>Preferences</h3>
  View mode toggle (existing, unchanged)
```

Two independent `<form>` elements — each has its own submit button, state, and error display. No shared state between them.

### State (Svelte 5 runes)

```javascript
let profileForm = $state({ email: '', first_name: '', last_name: '' });
let profileErrors = $state({});
let profileMessage = $state('');
let profileSaving = $state(false);

let pwForm = $state({ current_password: '', new_password: '', new_password_confirm: '' });
let pwErrors = $state({});
let pwMessage = $state('');
let pwSaving = $state(false);
```

On mount, initialize `profileForm` from the `$user` store — no extra fetch needed. After a successful profile PATCH, update the `user` store with the response so the sidebar stays in sync.

### API calls

- Profile save: `api.patch('/auth/me/', profileForm)` — add a `patch` helper to `lib/api.js` if one doesn't exist (verify during implementation).
- Password change: `api.post('/auth/me/password/', pwForm)`.

### Password input autocomplete

- `current_password` → `autocomplete="current-password"`
- `new_password`, `new_password_confirm` → `autocomplete="new-password"`

This lets browsers offer to update saved passwords on success.

## Error handling

### Backend error shapes

| Case | Status | Body |
|---|---|---|
| Profile: invalid email | 400 | `{"email": ["Enter a valid email address."]}` |
| Profile: extra fields (`username`, `is_staff`, etc.) | 200 | ignored, not applied |
| Password: wrong current | 400 | `{"current_password": ["Current password is incorrect."]}` |
| Password: fails validators | 400 | `{"new_password": ["This password is too short...", "...too common."]}` |
| Password: confirm mismatch | 400 | `{"new_password_confirm": ["Passwords do not match."]}` |
| Unauthenticated | 401 | handled globally by SPA |

### Frontend handling

- 400 → read JSON, populate the relevant `*Errors` state object, render messages under each field.
- 401 → existing global handler in `api.js` redirects to login.
- Network / 500 → show a single non-field error ("Could not save. Please try again.").
- Clear errors and success messages on next submit.

### Security

- Never echo passwords in any response.
- `current_password` verification happens in `validate_current_password` so the wrong-password path fails before `set_password` is reached.
- `update_session_auth_hash` is the single line that prevents the user from being logged out of their own session after a password change. Covered by an explicit test.

## Testing

TDD. New file: `tests/test_api_auth_me.py`. Django `TestCase` + DRF `APIClient` with session login. No fixtures — create the user in `setUp`.

### Profile update — `PATCH /api/auth/me/`

1. Unauthenticated → 401
2. Update all three fields → 200, DB reflects changes, response body has new values
3. Partial update (only `first_name`) → 200, other fields unchanged
4. Invalid email → 400 with `email` error
5. `username` in body → 200, username unchanged (silently ignored)
6. Privilege-escalation guard: sending `is_staff=true`, `is_superuser=true`, and `is_active=false` in the PATCH body → 200; all three flags unchanged in the DB. Single test covering all three flags.

### Password change — `POST /api/auth/me/password/`

7. Unauthenticated → 401
8. Happy path: correct current + valid new + matching confirm → 200; `check_password(new)` true, `check_password(old)` false
9. Wrong current password → 400 with `current_password` error; DB password unchanged
10. New + confirm mismatch → 400 with `new_password_confirm` error; DB password unchanged
11. New password fails validators (too short, too common) → 400 with `new_password` error containing validator messages; DB password unchanged
12. Missing one of the three fields → 400 for that field
13. After a successful change, the same `APIClient` session can hit `GET /api/auth/me/` without re-logging-in → confirms `update_session_auth_hash`

### Frontend

No new test infra. Manual browser verification per the CLAUDE.md guidance: load the page, run the happy path for each form, exercise each error case.

## Out of scope (future work)

- Owner-side user management: list users, create users, assign groups/permissions, deactivate users. This is the next brainstorming session.
- Optional: link profile edits to the associated `Contact` record (currently ignored per scope decision).
- Optional: history logging of profile and password changes.

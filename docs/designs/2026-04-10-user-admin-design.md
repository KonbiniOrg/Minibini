# Owner-Side User Administration — Design

**Date:** 2026-04-10
**Scope:** Let users with `can_manage_config` create, view, edit, permission, activate, deactivate, and reset-password for any user, via a new `/users` area in the Svelte SPA backed by a new `/api/users/` DRF viewset. Second half of this session's user-management work; the first half (self-service profile) shipped as `docs/designs/2026-04-10-user-self-service-design.md`.

## Goals

- Owners can create new users (username, email, name, initial password).
- Owners can view the list of all users, including deactivated ones (visually flagged).
- Owners can view and edit a user's profile fields.
- Owners can set a user's permission atoms via individual checkboxes.
- Owners can deactivate and reactivate users.
- Deactivating a user:
  - Auto-closes any open bleps belonging to that user.
  - Kills the user's active Django sessions so an in-browser session is booted on next request.
  - Does NOT auto-unassign tasks (managers reassign manually via existing task UI).
- Owners can reset any user's password by entering a new password directly.
- Self-lockout prevention: owners cannot (a) deactivate themselves, (b) remove their own `can_manage_config`, (c) deactivate or demote the last active admin with `can_manage_config`.
- All protected by the `can_manage_config` atom.

## Non-goals

- Owner-side user-to-Contact association (deferred).
- Email-based "forgot password" flow (deferred — no email-sending infra wired for this).
- History/audit logging of admin actions (deferred).
- Hard-delete users — never. Deactivation is the only removal mechanism.
- Visual indicators for deactivated assignees in task/work-order/board views (separate follow-up plan; see "Known follow-ups" at the end).
- Pagination or search on the user list — small shops, small lists. Render the whole list in one call.
- Exposing or editing `is_superuser` from the UI (shown as a read-only badge only).
- Using Django's `Group` model. Permissions are assigned as individual atoms directly on the user.

## Related design decisions (from earlier context)

- The project uses a 5-atom permission system (`apps/core/models.py` User.Meta.permissions). `can_manage_config` is the atom that gates user admin.
- `is_superuser=True` bypasses the atom system entirely (Django built-in `ModelBackend.has_perm` behavior). The user admin UI surfaces the flag read-only but does not edit it.
- The existing `/api/auth/` namespace is for the current session's own user (login/logout/me/password). This feature gets its own `/api/users/` namespace to keep the "session-self" and "admin-of-users" surfaces distinct.
- The existing Django HTML user_list/user_detail pages (`apps/core/views.py:13-24`, `templates/core/user_list.html`, `templates/core/user_detail.html`) are ignored for this design. Treated as if they don't exist.
- The sidebar currently has a `Manage` placeholder link at `/manage` with no registered route or page. Replaced with the new `Users` link as part of this feature.

## Backend

### URL namespace

Register `apps.api.users.urls` under `/api/users/` in `apps/api/urls.py`. New Django app directory `apps/api/users/` containing:

- `views.py` — `UserViewSet(ModelViewSet)`
- `serializers.py` — list, detail, create, update, password-reset, permissions-update serializers
- `urls.py` — DefaultRouter registration for `UserViewSet`
- `services.py` — `UserAdminService` with all business logic (lockout checks, side effects)
- `__init__.py` — empty (project convention)

### Endpoint map

All endpoints require `[IsAuthenticated, CanManageConfig]` via `get_permissions()`.

| Method | URL | Purpose | Serializer |
|---|---|---|---|
| `GET` | `/api/users/` | List all users | `UserListSerializer` |
| `POST` | `/api/users/` | Create user | `UserCreateSerializer` |
| `GET` | `/api/users/:id/` | Retrieve user | `UserDetailSerializer` |
| `PATCH` | `/api/users/:id/` | Update profile fields | `UserUpdateSerializer` |
| `DELETE` | `/api/users/:id/` | **Returns 405.** Hard delete is not supported. | — |
| `POST` | `/api/users/:id/activate/` | Reactivate user | — |
| `POST` | `/api/users/:id/deactivate/` | Deactivate user | — |
| `POST` | `/api/users/:id/reset-password/` | Admin password reset | `PasswordResetSerializer` |
| `PUT` | `/api/users/:id/permissions/` | Replace user's permission atoms | `PermissionsUpdateSerializer` |

Custom actions (`activate`, `deactivate`, `reset-password`, `permissions`) all return the updated `UserDetailSerializer` body (or `{'detail': '...'}` where no body change is needed). This lets the frontend refresh state without a second fetch. The project convention of "all DELETE responses return JSON bodies" is moot here because `destroy()` is overridden to return 405.

### List endpoint: no pagination, no search

`GET /api/users/` returns the full user list as a plain JSON array (via DRF list renderer) with `pagination_class = None` set on the viewset. Small-shop assumption; revisit if user counts grow past a few hundred. Ordering: `.order_by('-is_active', 'username')` so active users appear first, inactive grouped at the bottom.

### Serializers

**`UserListSerializer`** (list rows)
```python
fields = ['id', 'username', 'first_name', 'last_name', 'email', 'is_active', 'is_superuser']
```
All read-only. `is_superuser` included so the UI can render a badge.

**`UserDetailSerializer`**
Same fields as list plus `permissions` (SerializerMethodField — list of atom codenames the user has) and `date_joined`. All read-only. No mutation via this serializer; the viewset's PATCH uses `UserUpdateSerializer`.

**`UserCreateSerializer`** (ModelSerializer on User)
```python
fields = ['username', 'email', 'first_name', 'last_name', 'password', 'password_confirm']
```
- `username` — required. Uniqueness enforced by Django's `AbstractUser` default.
- `email` — required (EmailField). **No uniqueness enforcement** — Django's default on `AbstractUser.email` has no unique constraint, and duplicate emails (shared household email, shared shop inbox) are legitimate for small operations.
- `first_name`, `last_name` — required (override Django's default `blank=True` in the serializer).
- `password`, `password_confirm` — both required, `write_only=True`. `validate_password` runs each through `django.contrib.auth.password_validation.validate_password` (same pattern as the self-service feature's `PasswordChangeSerializer`). Mismatch raises `{'password_confirm': ['Passwords do not match.']}`.
- `save()` calls `User.objects.create_user(username=..., email=..., first_name=..., last_name=...)` then `user.set_password(password); user.save()`. (Django's `create_user` already does this in one call; using it is cleaner. The serializer just unpacks `validated_data` and calls `create_user`.)
- New user gets `is_active=True` by default. No permission atoms assigned at creation — admin uses the Set Permissions endpoint as a follow-up.

**`UserUpdateSerializer`** (ModelSerializer on User, for PATCH)
```python
fields = ['username', 'email', 'first_name', 'last_name']
```
All optional (partial update). The same privilege-escalation-guard pattern as the self-service feature: `password`, `is_active`, `is_staff`, `is_superuser`, `permissions`, and `groups` are deliberately not in the allowlist. Those have dedicated endpoints.

Note: admin CAN edit `username` here (unlike self-service, which excluded it). Fixing a typo in a new hire's username is a reasonable admin operation.

**`PasswordResetSerializer`** (pure Serializer, not ModelSerializer)
```python
fields = ['password', 'password_confirm']
```
Both `write_only=True`, required. Same validators as `UserCreateSerializer`. Does not take a `current_password` — admin is resetting, not changing their own password. `save()` takes the target user (passed via context) and calls `target.set_password(new); target.save()`. Does NOT call `update_session_auth_hash` — that's only meaningful for the current session's own user.

**`PermissionsUpdateSerializer`** (pure Serializer)
```python
permissions = serializers.ListField(
    child=serializers.CharField(),
    allow_empty=True,
)
```
- `validate_permissions` checks every codename is one of the 5 known atoms. Unknown codenames raise a field-level error.
- Known atoms: `can_manage_jobs`, `can_manage_financials`, `can_manage_time`, `can_approve_expenses`, `can_manage_config`. Derived from `User._meta.permissions` at import time so there is exactly one source of truth. If a new atom is added to the User model, the serializer automatically accepts it.
- `save()` delegates to `UserAdminService.set_permissions(actor, target, atoms)` — the service is where lockout checks live.

### UserAdminService

Lives in `apps/api/users/services.py`. Owns all business logic and side effects; the viewset is a thin wrapper that calls into it. Matches the project pattern (see `apps/api/jobs/services.py` etc.).

**Public methods:**

```python
class UserAdminService:
    @staticmethod
    def deactivate_user(actor, target): ...
    @staticmethod
    def activate_user(actor, target): ...
    @staticmethod
    def reset_password(actor, target, new_password): ...
    @staticmethod
    def set_permissions(actor, target, atom_codenames): ...
    @staticmethod
    def _kill_sessions_for_user(user): ...  # testable helper
```

#### `deactivate_user(actor, target)`

1. **Lockout check D1:** if `target.pk == actor.pk` → raise `serializers.ValidationError('You cannot deactivate yourself.')`
2. **Lockout check D3 (last admin via deactivate):** if `target` currently has `can_manage_config` AND target is the only active user with that permission → raise `serializers.ValidationError('Cannot deactivate the last user who can manage config.')`. Query:
   ```python
   last_admin_count = User.objects.filter(
       is_active=True,
       user_permissions__codename='can_manage_config',
       user_permissions__content_type__app_label='core',
   ).distinct().count()
   ```
3. `target.is_active = False; target.save(update_fields=['is_active'])`
4. Call `BlepService.close_user_open_bleps(target)` — see "Small backend refactor" below.
5. `_kill_sessions_for_user(target)` — see implementation below.
6. Return `target`.

#### `activate_user(actor, target)`

1. No lockout checks (activating never takes anyone offline).
2. `target.is_active = True; target.save(update_fields=['is_active'])`
3. Return `target`.

No blep reopening, no session restoration, no permission mutation.

#### `reset_password(actor, target, new_password)`

1. No lockout checks. Admin resetting their own password via this endpoint is allowed (the owner who forgot their own password has no other recovery path).
2. `target.set_password(new_password); target.save(update_fields=['password'])`
3. Return `target`.

The call does NOT invoke `update_session_auth_hash`. Consequences:
- If `actor != target`: target's existing sessions will be invalidated on their next request (Django's `AuthenticationMiddleware` re-checks the session auth hash against the user's stored hash). This is desirable — the old password should not grant continued access.
- If `actor == target`: the owner's own current session is also invalidated on their next request. They're forced to log in again with the new password. Acceptable behavior for the "I forgot my own password" recovery path; if they wanted graceful in-session change, they could use the self-service `/api/auth/me/password/` flow.

#### `set_permissions(actor, target, atom_codenames)`

1. **Lockout check D2:** if `actor.pk == target.pk` AND `'can_manage_config' not in atom_codenames` AND target currently has `can_manage_config` → raise `serializers.ValidationError('You cannot remove your own can_manage_config permission.')`
2. **Lockout check D3 (last admin via permission removal):** if target currently has `can_manage_config` AND `'can_manage_config' not in atom_codenames` AND target is the last active user with `can_manage_config` → raise `serializers.ValidationError('Cannot remove can_manage_config from the last user who has it.')`
3. Look up `Permission` rows by codename:
   ```python
   perms = Permission.objects.filter(
       codename__in=atom_codenames,
       content_type__app_label='core',
   )
   ```
4. `target.user_permissions.set(perms)` — replaces the M2M entirely.
5. Return `target`.

Note: we do not touch `target.groups`. Groups remain empty for all users (per the atoms-only decision).

#### `_kill_sessions_for_user(user)`

```python
from django.contrib.sessions.models import Session

def _kill_sessions_for_user(user):
    target_pk = str(user.pk)
    for session in Session.objects.all():
        data = session.get_decoded()
        if data.get('_auth_user_id') == target_pk:
            session.delete()
```

Perf note: Django's default database session backend has no index on decoded user ID (session data is pickled/base64-encoded), so there's no way to query "sessions for user X" directly. Iterating all sessions is the standard pattern. For a shop with ~10-50 concurrent sessions this is fine. If the session table ever grows large enough to make this slow, we swap to a signed-cookie backend or add a denormalized `user_id` column to a custom session model — neither is a concern for this feature.

### Small backend refactor: `BlepService.close_user_open_bleps`

`apps/jobs/services.py` currently has `BlepService._close_open(user=None, task=None, now=None)` — a pseudo-private helper used internally by the service's own methods. The user admin service needs the same behavior but calling a pseudo-private from a different app is smelly.

Add a thin public wrapper:

```python
@staticmethod
def close_user_open_bleps(user, now=None):
    """Close all open bleps for the given user. Used when a user is deactivated."""
    return BlepService._close_open(user=user, now=now)
```

One-line public interface, same behavior. `UserAdminService.deactivate_user` calls the public wrapper. In-scope for this feature.

### Permission class

All viewset actions use:
```python
def get_permissions(self):
    return [IsAuthenticated(), CanManageConfig()]
```

No per-action differentiation. An owner can do anything; a non-admin cannot reach any endpoint in the namespace.

## Frontend

### Routing

New routes in `frontend/src/App.svelte`:
```javascript
'/users': UserListPage,
'/users/new': UserCreatePage,
'/users/:id': UserDetailPage,
```

### Sidebar change

File: `frontend/src/components/Sidebar.svelte`.

1. **Delete** the `showManage` derivation and the `<a href="/manage">Manage</a>` link block. The `/manage` route has no page component and the link goes nowhere; it's vestigial.
2. **Add** a new link under the "Admin" section label, visible only to users with `can_manage_config`:
   ```svelte
   {#if hasPerm('can_manage_config')}
     <a href="/users" use:link>Users</a>
   {/if}
   ```
3. **Update** `showAdminLabel` to depend on the new gate:
   ```javascript
   let showAdminLabel = $derived(hasPerm('can_manage_config'));
   ```
   (Since `showSettings` also gates on `can_manage_config`, these collapse into a single condition. Simplification: `showAdminLabel === showSettings === hasPerm('can_manage_config')`. Inline the check or keep one `$derived` for readability — I'd keep `showSettings` and `showAdminLabel` both equal to that single expression for symmetry with the existing pattern.)

### API client addition

`frontend/src/lib/api.js` currently exports `{ get, post, patch, delete }`. The permissions endpoint uses `PUT`. Add:

```javascript
put: (url, data) => request('PUT', url, data),
```

One line. The underlying `request` function already handles PUT via its existing method whitelist.

### Shared helper extraction: `formErrors.js`

The self-service `ProfilePage.svelte` has a local `fieldErrors(errors, field)` helper. The user admin pages (list, create, detail) will need the same helper at least 4 more times. To avoid copy-paste proliferation, extract to `frontend/src/lib/formErrors.js`:

```javascript
export function fieldErrors(errors, field) {
  const v = errors?.[field];
  if (!v) return [];
  return Array.isArray(v) ? v : [v];
}
```

As part of this feature, update `ProfilePage.svelte` to import the extracted helper. One-line refactor, removes the local definition. Small opportunistic cleanup within scope.

### UserListPage.svelte

```
<h2>Users</h2>
<p><a href="/users/new" use:link>New user</a></p>

{#if loading}
  <p>Loading...</p>
{:else if errors}
  <p>{errors}</p>
{:else}
  <table border="1">
    <thead>
      <tr>
        <th>Username</th>
        <th>Name</th>
        <th>Email</th>
        <th>Status</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>
      {#each users as user (user.id)}
        <tr>
          <td>{user.username}</td>
          <td>
            {user.first_name} {user.last_name}
            {#if user.is_superuser} <em>(superuser)</em>{/if}
          </td>
          <td>{user.email}</td>
          <td>
            {#if user.is_active}
              Active
            {:else}
              <em>Deactivated</em>
            {/if}
          </td>
          <td><a href="/users/{user.id}" use:link>View</a></td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
```

**State:**
```javascript
let users = $state([]);
let loading = $state(true);
let errors = $state(null);
```

**Behavior:**
- On mount: `api.get('/api/users/')` populates `users`. 403 → show an error message (shouldn't happen if the sidebar gating is correct, but handle defensively for direct URL access).
- Order: whatever the backend returns (active first, then inactive, each group by username).
- No search, no pagination, no filters. Whole list.

### UserCreatePage.svelte

Mirrors `ContactFormPage.svelte` in structure. Plain form with all six fields: username, email, first_name, last_name, password, password_confirm.

**State:**
```javascript
let form = $state({
  username: '', email: '', first_name: '', last_name: '',
  password: '', password_confirm: '',
});
let errors = $state({});
let saving = $state(false);
```

**Markup pattern** (per CLAUDE.md form conventions):
```svelte
<p>
  <label for="new-username"><strong>Username *</strong></label><br>
  <input type="text" id="new-username" bind:value={form.username} required>
</p>
{#each fieldErrors(errors, 'username') as msg}
  <p>{msg}</p>
{/each}
```

Password inputs use `autocomplete="new-password"`. All inputs have `for`/`id` pairing.

**On success:** `api.post('/api/users/', form)` returns the created user; call `push('/users/' + created.id)` to jump to the detail page. The admin sets permissions there.

**On failure:** populate `errors` from `err.data` (object) or fall back to `{non_field_errors: ['Could not create user. Please try again.']}`.

### UserDetailPage.svelte

The most complex page. Four independent sub-sections, each with its own form/state/handler, matching the pattern from `ProfilePage.svelte` (multiple independent forms on one page).

**Top-level layout:**

```
<h2>User: {user.username}</h2>
<p><a href="/users" use:link>← Back to users</a></p>

Status line:
  Active | Deactivated (em)
  Superuser (em, if is_superuser)

<h3>Profile</h3>       <!-- profile form -->
<h3>Permissions</h3>   <!-- permissions form -->
<h3>Reset password</h3><!-- password reset form -->
<h3>Account status</h3><!-- activate/deactivate button -->
```

**State (Svelte 5 runes):**

```javascript
const { params = {} } = $props();

let user = $state(null);
let loading = $state(true);
let loadError = $state(null);

// Profile form
let profileForm = $state({ username: '', email: '', first_name: '', last_name: '' });
let profileErrors = $state({});
let profileMessage = $state('');
let profileSaving = $state(false);

// Permissions form
let permForm = $state({ permissions: [] });  // list of atom codenames
let permErrors = $state({});
let permMessage = $state('');
let permSaving = $state(false);

// Reset password form
let pwForm = $state({ password: '', password_confirm: '' });
let pwErrors = $state({});
let pwMessage = $state('');
let pwSaving = $state(false);

// Account status action
let statusErrors = $state({});
let statusMessage = $state('');
let statusSaving = $state(false);

// Current (logged-in) admin — for self-lockout hints
import { user as currentUser } from '../../stores/auth.js';
```

**Atom list and labels** (hardcoded in the component):

```javascript
const ATOMS = [
  { codename: 'can_manage_jobs', label: 'Can manage jobs' },
  { codename: 'can_manage_financials', label: 'Can manage financials' },
  { codename: 'can_manage_time', label: 'Can manage time entries' },
  { codename: 'can_approve_expenses', label: 'Can approve expenses' },
  { codename: 'can_manage_config', label: 'Can manage configuration (user admin)' },
];
```

**Data flow:**
- On mount: `api.get('/api/users/' + params.id + '/')` populates `user`, seeds `profileForm` from `user`, seeds `permForm.permissions` from `user.permissions`.
- Each save handler calls its specific endpoint. On success, the response body replaces `user`, and the relevant sub-form is re-seeded from the new `user`.

**Self-lockout client hints:**
- Computed: `let isSelf = $derived($currentUser && user && $currentUser.id === user.id);`
- Deactivate button: if `isSelf && user.is_active`, render disabled with text like "Deactivate (cannot deactivate yourself)".
- `can_manage_config` checkbox: if `isSelf && permForm.permissions.includes('can_manage_config')`, render the checkbox disabled with a note.
- D3 (last admin) is NOT mirrored on the client — the client has no count. Server authoritative; the user sees the error message if they trigger it.

**Profile sub-form:** PATCH `/api/users/:id/` with `profileForm`. On success, `user = response; profileMessage = 'Saved.';`.

**Permissions sub-form:** PUT `/api/users/:id/permissions/` with `{permissions: permForm.permissions}`. Checkboxes: each atom shown as `<input type="checkbox" value={atom.codename} checked={permForm.permissions.includes(atom.codename)} />`. On change, toggle the codename in `permForm.permissions`. On submit, send the full list.

**Reset password sub-form:** POST `/api/users/:id/reset-password/` with `pwForm`. On success, clear the form fields and show `pwMessage = 'Password reset.';`. Password inputs use `autocomplete="new-password"`.

**Account status sub-form:** a single button, text "Deactivate" or "Reactivate" depending on `user.is_active`. On click, POST to `/api/users/:id/deactivate/` or `/activate/`. On success, `user = response; statusMessage = '...';`.

### Sidebar label derivation (note)

After the rewrite, both `showSettings` and the new Users link gate on the same permission. Collapse to a single derivation:

```javascript
let showAdminLabel = $derived(hasPerm('can_manage_config'));
```

Both the `/settings` link and the `/users` link use `hasPerm('can_manage_config')` inline in their `{#if}` blocks. This removes the old `showSettings`/`showManage` flags that added indirection without benefit. If a future admin feature needs a different gating atom, add a flag at that point, not speculatively now.

## Error handling

Standard DRF 400 shapes throughout. Frontend reads `err.data` (populated by `api.js:34-35`) into the relevant `*Errors` state block, then renders via `fieldErrors(errors, fieldName)`. Non-field errors render under the `non_field_errors` key (DRF default).

Specific error cases:

| Scenario | Status | Body shape |
|---|---|---|
| Create: duplicate username | 400 | `{"username": ["A user with that username already exists."]}` |
| Create: invalid email | 400 | `{"email": ["Enter a valid email address."]}` |
| Create: password too short/common | 400 | `{"password": ["..."]}` |
| Create: password mismatch | 400 | `{"password_confirm": ["Passwords do not match."]}` |
| Update: any validation | 400 | field-keyed |
| Deactivate self | 400 | `{"non_field_errors": ["You cannot deactivate yourself."]}` |
| Deactivate last admin | 400 | `{"non_field_errors": ["Cannot deactivate the last user who can manage config."]}` |
| Remove own can_manage_config | 400 | `{"non_field_errors": ["You cannot remove your own can_manage_config permission."]}` |
| Remove last admin's can_manage_config | 400 | `{"non_field_errors": ["Cannot remove can_manage_config from the last user who has it."]}` |
| Permissions: unknown codename | 400 | `{"permissions": ["'foo' is not a valid permission atom."]}` |
| Non-admin accessing any endpoint | 403 | `{"detail": "You do not have permission to perform this action."}` |
| Not authenticated | 403 | (DRF default for SessionAuthentication) |
| Hard delete attempt | 405 | `{"detail": "Method \"DELETE\" not allowed."}` |

## Testing

TDD. New file `tests/test_api_users.py`. Multiple `BaseTestCase` subclasses for organization. Fixture users from `unit_test_data.json`; create additional users in `setUp` as needed for multi-user scenarios (last-admin tests).

**Backend test matrix** (minimum set):

### Permission gating
1. `test_list_unauthenticated_returns_403`
2. `test_list_as_non_admin_returns_403` (use johnq)
3. `test_list_as_admin_returns_200` (create a user with `can_manage_config`)

### List
4. `test_list_returns_all_users_including_inactive`
5. `test_list_orders_active_first`
6. `test_list_response_includes_is_superuser_flag`

### Retrieve
7. `test_retrieve_user_returns_full_detail_including_permissions`

### Create
8. `test_create_user_happy_path`
9. `test_create_user_hashes_password`
10. `test_create_user_sets_is_active_true_by_default`
11. `test_create_user_duplicate_username_returns_400`
12. `test_create_user_invalid_email_returns_400`
13. `test_create_user_password_too_short_returns_400`
14. `test_create_user_password_mismatch_returns_400`
15. `test_create_user_ignores_is_staff_in_body` (serializer allowlist)

### Update
16. `test_patch_user_updates_allowed_fields`
17. `test_patch_user_ignores_password`
18. `test_patch_user_ignores_is_active`
19. `test_patch_user_ignores_is_superuser`
20. `test_patch_user_ignores_user_permissions`
21. `test_patch_user_admin_can_edit_username`

### Activate / deactivate
22. `test_deactivate_user_sets_is_active_false`
23. `test_deactivate_closes_open_bleps` (create a blep, deactivate, assert end_time set)
24. `test_deactivate_does_not_touch_already_closed_bleps` (regression guard)
25. `test_deactivate_kills_target_session` (log in as target via client.login, then deactivate via a second client, then first client's me/ request fails)
26. `test_deactivate_self_returns_400` (D1)
27. `test_deactivate_last_admin_returns_400` (D3, with only one admin)
28. `test_deactivate_non_last_admin_succeeds` (happy path D3 with two admins)
29. `test_activate_user_sets_is_active_true`
30. `test_activate_user_has_no_side_effects`

### Reset password
31. `test_reset_password_hashes_new_password`
32. `test_reset_password_old_password_no_longer_works`
33. `test_reset_password_invalidates_target_existing_sessions` (same pattern as deactivate)
34. `test_reset_password_mismatch_returns_400`

### Set permissions
35. `test_set_permissions_replaces_user_permissions_m2m`
36. `test_set_permissions_empty_list_clears_all_atoms`
37. `test_set_permissions_unknown_codename_returns_400`
38. `test_set_permissions_remove_own_can_manage_config_returns_400` (D2)
39. `test_set_permissions_remove_last_admin_can_manage_config_returns_400` (D3)
40. `test_set_permissions_remove_non_last_admin_can_manage_config_succeeds`

### Hard delete
41. `test_delete_user_returns_405`

### Regression guards on existing behavior
42. `test_assignee_dropdown_excludes_deactivated_user` (via `/api/auth/users/` — the existing assignee endpoint already filters; confirm this holds)
43. `test_board_available_workers_excludes_deactivated_user` (via board service queries at `apps/jobs/services.py:828`, `:922`)

**Total: 43 backend tests.**

### Frontend testing

No new test infra. Manual browser verification for the final verification task, following the checklist in Section 3.7 of the brainstorming (covered in the implementation plan's final task).

## Known follow-ups (out of scope for this feature)

1. **Visual indicator for deactivated assignees** — wherever a username/assignee is rendered (task cards, detail pages, work order task lists, history feed, search results), show an "(deactivated)" or greyed style when the assignee's `is_active=False`. Separate design, separate plan, audit of all assignee-rendering components.
2. **User-to-Contact association on create/update** — let the owner link a new user to an existing Contact or create a Contact from the user form. Not needed for V1; the `User.contact` field is already nullable.
3. **History logging of admin actions** — audit trail for who created/deactivated/reset/re-permissioned whom. HistoryEntry model already supports this; implementation is straightforward but out of scope for V1.
4. **Expense approvals and blep admin** — future user-adjacent admin features that may live under the Admin nav area alongside `/users`.
5. **"Forgot password" email flow** — requires email-sending infra that isn't wired for this use case.
6. **Group-based permission presets** — if the atom-checkbox UI proves tedious, bring back Django Groups as presets. V2 at earliest.
7. **Fix stale `LOGIN_URL = '/admin/login/'`** in `minibini/settings.py:202` — still a tech debt item from the previous feature.

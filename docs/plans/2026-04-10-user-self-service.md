# User Self-Service Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a logged-in user view and update their own User record (email, name, password) via the Svelte profile page backed by DRF endpoints.

**Architecture:** Two DRF endpoints on the existing `/api/auth/` module — extend `me_view` to handle `PATCH` for profile fields, add a new `change_password_view` at `me/password/` that reuses Django's password-validation and session-hash utilities. Rewrite the mostly-empty `ProfilePage.svelte` with two independent forms and the existing view-mode toggle.

**Tech Stack:** Django 5.2, DRF (SessionAuthentication), Svelte 5 runes, existing `api` client in `frontend/src/lib/api.js`.

**Design doc:** `docs/designs/2026-04-10-user-self-service-design.md`

---

## File Structure

**Backend:**
- Modify: `apps/api/auth/serializers.py` — add `MeUpdateSerializer` and `PasswordChangeSerializer`
- Modify: `apps/api/auth/views.py` — extend `me_view` to handle `PATCH`; add `change_password_view`
- Modify: `apps/api/auth/urls.py` — register `me/password/`
- Create: `tests/test_api_auth_me.py` — 13 test cases

**Frontend:**
- Modify: `frontend/src/routes/ProfilePage.svelte` — rewrite as full profile page
- Modify: `frontend/src/stores/auth.js` — add a helper to update the stored user after a PATCH (or inline the `.set()` in the page; see Task 3)

No new files for the frontend — `lib/api.js` already exposes `patch` and `post`, and `stores/auth.js` already exports `user` as a writable store.

---

## Task 1: Backend — profile PATCH endpoint

**Files:**
- Modify: `apps/api/auth/serializers.py`
- Modify: `apps/api/auth/views.py:36-39` (`me_view`)
- Create: `tests/test_api_auth_me.py`

**Context for the engineer:**
- `User` is our custom `AbstractUser` subclass at `apps/core/models.py`. Import as `from apps.core.models import User` (project convention — `apps/api/auth/views.py:46` and `apps/api/bleps/views.py:65` follow this pattern).
- `BaseTestCase` in `tests/base.py` loads `unit_test_data.json` and gives you an `admin` user. That user is a superuser, which is fine for most tests. For the privilege-escalation test (#6) we want a non-superuser so we can assert the flags don't move. Fixture provides `johnq` for that (see `tests/test_core_models_with_fixtures.py:29` — `is_superuser=False`, `is_staff=False`, `is_active=True`).
- DRF returns **403** (not 401) when `SessionAuthentication` has no authenticated user. See `tests/test_api_auth.py:45` for precedent.
- `@api_view` with multiple methods is already used in the codebase — change `['GET']` to `['GET', 'PATCH']` on the existing `me_view`.
- The existing `UserSerializer` in `apps/api/auth/serializers.py` is a plain `serializers.Serializer` with all read-only fields and a `get_permissions` SerializerMethodField. Do not modify it — we'll add a separate `ModelSerializer` for the update path.
- `ModelSerializer` on `User` with an explicit `fields` allowlist will silently drop any field not in that list. This is the privilege-escalation guard: a client that sends `{"is_superuser": true}` gets a 200 but `is_superuser` is not touched.

### Task 1 steps

- [ ] **Step 1.1: Create the test file with all six profile tests**

Create `tests/test_api_auth_me.py` with the following content:

```python
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User


class MeUpdateAPITest(BaseTestCase):
    """Tests for PATCH /api/auth/me/ — self-service profile update."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        # johnq is a non-superuser, non-staff, active user in the fixture.
        # Using a non-superuser lets us meaningfully assert that privilege
        # flags don't move in the privilege-escalation test.
        self.user = User.objects.get(username='johnq')
        self.user.set_password('testpass123')
        self.user.save()

    def test_patch_me_unauthenticated_returns_403(self):
        response = self.client.patch(
            '/api/auth/me/',
            {'first_name': 'Nope'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_patch_me_updates_all_three_fields(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            '/api/auth/me/',
            {
                'email': 'newemail@example.com',
                'first_name': 'NewFirst',
                'last_name': 'NewLast',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'newemail@example.com')
        self.assertEqual(self.user.first_name, 'NewFirst')
        self.assertEqual(self.user.last_name, 'NewLast')
        # Response body should be the full UserSerializer shape
        self.assertEqual(response.data['email'], 'newemail@example.com')
        self.assertEqual(response.data['first_name'], 'NewFirst')
        self.assertEqual(response.data['username'], 'johnq')

    def test_patch_me_partial_update_leaves_other_fields(self):
        original_email = self.user.email
        original_last = self.user.last_name
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            '/api/auth/me/',
            {'first_name': 'OnlyFirst'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'OnlyFirst')
        self.assertEqual(self.user.email, original_email)
        self.assertEqual(self.user.last_name, original_last)

    def test_patch_me_invalid_email_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            '/api/auth/me/',
            {'email': 'not-an-email'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.data)

    def test_patch_me_ignores_username(self):
        original_username = self.user.username
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            '/api/auth/me/',
            {'username': 'hacker', 'first_name': 'Legit'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, original_username)
        self.assertEqual(self.user.first_name, 'Legit')

    def test_patch_me_ignores_privilege_flags(self):
        """Privilege-escalation guard.

        Sending is_staff, is_superuser, or is_active in the PATCH body
        must not mutate those fields. The serializer's fields allowlist
        (only email, first_name, last_name) is what enforces this.
        """
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertTrue(self.user.is_active)
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            '/api/auth/me/',
            {
                'is_staff': True,
                'is_superuser': True,
                'is_active': False,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertTrue(self.user.is_active)
```

- [ ] **Step 1.2: Run tests to verify they all fail**

Run: `python manage.py test tests.test_api_auth_me.MeUpdateAPITest -v 2`

Expected: 5 failures (405 "Method Not Allowed" or similar, because `me_view` doesn't accept PATCH yet) and 1 pass (the unauthenticated test — DRF returns 403 before the view runs).

If you see 6 failures or 6 passes, stop and investigate; something is off.

- [ ] **Step 1.3: Add `MeUpdateSerializer` to the serializers module**

Edit `apps/api/auth/serializers.py`. Add the import and the new class. The file becomes:

```python
from rest_framework import serializers
from apps.core.models import User


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField(source='pk', read_only=True)
    username = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
    permissions = serializers.SerializerMethodField()

    def get_permissions(self, obj):
        """Return list of custom permission codenames the user has."""
        return sorted(
            perm.split('.')[1]
            for perm in obj.get_all_permissions()
            if perm.startswith('core.can_')
        )


class MeUpdateSerializer(serializers.ModelSerializer):
    """Self-service profile update. Deliberately omits username, password,
    and all privilege flags — see docs/designs/2026-04-10-user-self-service-design.md
    """
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name']
```

- [ ] **Step 1.4: Extend `me_view` to handle PATCH**

Edit `apps/api/auth/views.py`. Change the `me_view` decorator and body:

```python
@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def me_view(request):
    if request.method == 'PATCH':
        serializer = MeUpdateSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
    return Response(UserSerializer(request.user).data)
```

Add `MeUpdateSerializer` to the serializer import at the top of the file:

```python
from .serializers import LoginSerializer, UserSerializer, MeUpdateSerializer
```

- [ ] **Step 1.5: Run the tests and verify all six pass**

Run: `python manage.py test tests.test_api_auth_me.MeUpdateAPITest -v 2`

Expected: `OK` with 6 tests passing.

- [ ] **Step 1.6: Commit**

```bash
git add apps/api/auth/serializers.py apps/api/auth/views.py tests/test_api_auth_me.py
git commit -m "feat(api): add PATCH /api/auth/me/ for self-service profile updates

Lets an authenticated user update their own email, first_name, and
last_name. The ModelSerializer's fields allowlist is the
privilege-escalation guard — username, password, is_staff,
is_superuser, and is_active are silently ignored.
"
```

---

## Task 2: Backend — password change endpoint

**Files:**
- Modify: `apps/api/auth/serializers.py`
- Modify: `apps/api/auth/views.py`
- Modify: `apps/api/auth/urls.py`
- Modify: `tests/test_api_auth_me.py`

**Context for the engineer:**
- `AUTH_PASSWORD_VALIDATORS` in `minibini/settings.py:146` includes `MinimumLengthValidator` (default minimum: 8 characters) and `CommonPasswordValidator`. So `'abc'` fails length and `'password'` fails common-list — both are usable in tests.
- `django.contrib.auth.password_validation.validate_password` raises `django.core.exceptions.ValidationError` (not the DRF one). Catch and re-raise as `rest_framework.serializers.ValidationError(list(e.messages))` to get clean per-field error output.
- `django.contrib.auth.update_session_auth_hash(request, user)` re-hashes the current session so calling `set_password` doesn't log the user out of their own browser. Without this line, the password change would instantly kill the current session and test #13 (session survives) would fail.
- Per project convention, every API response has a JSON body — return `{'detail': 'Password changed.'}`, never 204.
- The serializer needs access to the request user inside `validate_*` methods. Pass it via `context={'request': request}` from the view, then read `self.context['request'].user`.

### Task 2 steps

- [ ] **Step 2.1: Add the password-change test class to the existing test file**

Append the following to `tests/test_api_auth_me.py` (keep the existing `MeUpdateAPITest` class untouched):

```python
class PasswordChangeAPITest(BaseTestCase):
    """Tests for POST /api/auth/me/password/ — self-service password change."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='johnq')
        self.old_password = 'OldPassword!99'
        self.user.set_password(self.old_password)
        self.user.save()

    def _body(self, **overrides):
        body = {
            'current_password': self.old_password,
            'new_password': 'NewPassword!88',
            'new_password_confirm': 'NewPassword!88',
        }
        body.update(overrides)
        return body

    def test_password_change_unauthenticated_returns_403(self):
        response = self.client.post(
            '/api/auth/me/password/', self._body(), format='json'
        )
        self.assertEqual(response.status_code, 403)

    def test_password_change_happy_path(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            '/api/auth/me/password/', self._body(), format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('detail', response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewPassword!88'))
        self.assertFalse(self.user.check_password(self.old_password))

    def test_password_change_wrong_current(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            '/api/auth/me/password/',
            self._body(current_password='WrongPassword!1'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('current_password', response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_password_change_confirm_mismatch(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            '/api/auth/me/password/',
            self._body(new_password_confirm='DifferentPassword!88'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('new_password_confirm', response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_password_change_fails_length_validator(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            '/api/auth/me/password/',
            self._body(new_password='abc', new_password_confirm='abc'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('new_password', response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_password_change_fails_common_password_validator(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            '/api/auth/me/password/',
            self._body(new_password='password', new_password_confirm='password'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('new_password', response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_password_change_missing_field(self):
        self.client.force_authenticate(user=self.user)
        body = self._body()
        del body['current_password']
        response = self.client.post(
            '/api/auth/me/password/', body, format='json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('current_password', response.data)

    def test_password_change_keeps_session_alive(self):
        """After a successful change the same client should still be
        authenticated (update_session_auth_hash)."""
        self.client.login(username='johnq', password=self.old_password)
        response = self.client.post(
            '/api/auth/me/password/', self._body(), format='json'
        )
        self.assertEqual(response.status_code, 200)
        # The exact same client (same session cookie) should still hit /me/
        me_response = self.client.get('/api/auth/me/')
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.data['username'], 'johnq')
```

Note: test 12 from the design (missing-field) is covered by `test_password_change_missing_field`. The design's "fails validators" case (test 11) is split into two tests here (length and common-password) so each assertion is single-purpose and the failure mode is obvious.

- [ ] **Step 2.2: Run tests to verify they all fail**

Run: `python manage.py test tests.test_api_auth_me.PasswordChangeAPITest -v 2`

Expected: all 8 tests fail with 404 Not Found. (Django URL resolution happens before DRF's auth/permission layer, so even the unauthenticated test gets 404 instead of its expected 403 — that's a fail, which is what we want in the red phase.)

- [ ] **Step 2.3: Add `PasswordChangeSerializer` to serializers**

Edit `apps/api/auth/serializers.py`. Add the imports at the top and the new class at the bottom:

```python
from django.contrib.auth.password_validation import (
    validate_password as django_validate_password,
)
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from apps.core.models import User
```

```python
class PasswordChangeSerializer(serializers.Serializer):
    """Self-service password change. Requires the current password; runs
    the new password through Django's configured AUTH_PASSWORD_VALIDATORS.
    """
    current_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, required=True)
    new_password_confirm = serializers.CharField(write_only=True, required=True)

    def validate_current_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect.')
        return value

    def validate_new_password(self, value):
        user = self.context['request'].user
        try:
            django_validate_password(value, user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate(self, attrs):
        if attrs.get('new_password') != attrs.get('new_password_confirm'):
            raise serializers.ValidationError(
                {'new_password_confirm': ['Passwords do not match.']}
            )
        return attrs

    def save(self, **kwargs):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user
```

- [ ] **Step 2.4: Add `change_password_view` to views**

Edit `apps/api/auth/views.py`. Add the imports at the top:

```python
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
```

(Amend the existing `from django.contrib.auth import authenticate, login, logout` line — do not add a duplicate import.)

Extend the serializer import:

```python
from .serializers import (
    LoginSerializer,
    UserSerializer,
    MeUpdateSerializer,
    PasswordChangeSerializer,
)
```

Add the view at the end of the file (or next to `me_view`):

```python
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password_view(request):
    serializer = PasswordChangeSerializer(
        data=request.data, context={'request': request}
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()
    update_session_auth_hash(request, request.user)
    return Response({'detail': 'Password changed.'})
```

- [ ] **Step 2.5: Register the URL**

Edit `apps/api/auth/urls.py`. The file becomes:

```python
from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='auth-login'),
    path('logout/', views.logout_view, name='auth-logout'),
    path('me/', views.me_view, name='auth-me'),
    path('me/password/', views.change_password_view, name='auth-password-change'),
    path('users/', views.users_list, name='auth-users'),
    path('refresh/', views.refresh_stub, name='auth-refresh'),
]
```

- [ ] **Step 2.6: Run the password-change tests**

Run: `python manage.py test tests.test_api_auth_me.PasswordChangeAPITest -v 2`

Expected: `OK` with 8 tests passing.

- [ ] **Step 2.7: Run the full test module to confirm nothing regressed**

Run: `python manage.py test tests.test_api_auth_me tests.test_api_auth -v 2`

Expected: 14+ tests pass. `test_api_auth.py` should still be green (we only extended `me_view`, not changed its GET behavior).

- [ ] **Step 2.8: Commit**

```bash
git add apps/api/auth/serializers.py apps/api/auth/views.py apps/api/auth/urls.py tests/test_api_auth_me.py
git commit -m "feat(api): add POST /api/auth/me/password/ for self-service password change

Requires the current password, runs new password through
AUTH_PASSWORD_VALIDATORS, and calls update_session_auth_hash so the
user's current browser session survives the change.
"
```

---

## Task 3: Frontend — rewrite ProfilePage with profile form

**Files:**
- Modify: `frontend/src/routes/ProfilePage.svelte`

**Context for the engineer:**
- Svelte 5 runes: use `$state`, `$derived`, `$effect`. Do not use old `$:` syntax.
- The page is already routed at `/profile` (`frontend/src/App.svelte:54`) and linked from the sidebar (`frontend/src/components/Sidebar.svelte:75`). No routing changes required.
- `stores/auth.js` exports `user` as a writable Svelte store. The current page uses `$user?.username` — you can do the same.
- `lib/api.js` already has `api.patch` and `api.post`. URLs include the `/api/` prefix (see `ContactFormPage.svelte:34`).
- On a 400 response, `api.js` throws an `Error` with `.data` set to the parsed JSON body — see `api.js:34-35`. Read `e.data` to get field errors.
- The existing `viewMode` store and `toggleViewMode` function must be preserved in the Preferences section.
- No CSS framework — semantic HTML only. Match the form pattern in `CLAUDE.md` (`<p><label><strong>...</strong></label><br><input></p>`).

### Task 3 steps

- [ ] **Step 3.1: Rewrite `ProfilePage.svelte` with the profile form only (no password form yet)**

Replace the full content of `frontend/src/routes/ProfilePage.svelte` with:

```svelte
<script>
  import { api } from '../lib/api.js';
  import { user } from '../stores/auth.js';
  import { viewMode, toggleViewMode } from '../stores/viewMode.js';

  let profileForm = $state({
    email: '',
    first_name: '',
    last_name: '',
  });
  let profileErrors = $state({});
  let profileMessage = $state('');
  let profileSaving = $state(false);
  let initialized = $state(false);

  // Initialize form from the store once, after the user is loaded.
  $effect(() => {
    if (!initialized && $user) {
      profileForm.email = $user.email || '';
      profileForm.first_name = $user.first_name || '';
      profileForm.last_name = $user.last_name || '';
      initialized = true;
    }
  });

  async function saveProfile(e) {
    e.preventDefault();
    profileErrors = {};
    profileMessage = '';
    profileSaving = true;
    try {
      const updated = await api.patch('/api/auth/me/', {
        email: profileForm.email,
        first_name: profileForm.first_name,
        last_name: profileForm.last_name,
      });
      user.set(updated);
      profileMessage = 'Saved.';
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        profileErrors = err.data;
      } else {
        profileErrors = { non_field: ['Could not save. Please try again.'] };
      }
    } finally {
      profileSaving = false;
    }
  }

  function fieldErrors(errors, field) {
    const v = errors[field];
    if (!v) return [];
    return Array.isArray(v) ? v : [v];
  }
</script>

<h2>Profile</h2>

<h3>Account info</h3>

{#if !$user}
  <p>Loading...</p>
{:else}
  <form onsubmit={saveProfile}>
    <p>
      <strong>Username:</strong> {$user.username}
    </p>

    <p>
      <label for="profile-email"><strong>Email</strong></label><br>
      <input
        type="email"
        id="profile-email"
        bind:value={profileForm.email}
      >
    </p>
    {#each fieldErrors(profileErrors, 'email') as msg}
      <p>{msg}</p>
    {/each}

    <p>
      <label for="profile-first-name"><strong>First name</strong></label><br>
      <input
        type="text"
        id="profile-first-name"
        bind:value={profileForm.first_name}
      >
    </p>
    {#each fieldErrors(profileErrors, 'first_name') as msg}
      <p>{msg}</p>
    {/each}

    <p>
      <label for="profile-last-name"><strong>Last name</strong></label><br>
      <input
        type="text"
        id="profile-last-name"
        bind:value={profileForm.last_name}
      >
    </p>
    {#each fieldErrors(profileErrors, 'last_name') as msg}
      <p>{msg}</p>
    {/each}

    {#each fieldErrors(profileErrors, 'non_field') as msg}
      <p>{msg}</p>
    {/each}

    <p>
      <button type="submit" disabled={profileSaving}>
        {profileSaving ? 'Saving...' : 'Save'}
      </button>
    </p>
    {#if profileMessage}
      <p>{profileMessage}</p>
    {/if}
  </form>
{/if}

<h3>Preferences</h3>
<p>
  View mode: <strong>{$viewMode}</strong>
  — <a href="#" onclick={(e) => { e.preventDefault(); toggleViewMode(); }}>
    Switch to {$viewMode === 'full' ? 'lite' : 'full'} view
  </a>
</p>
```

- [ ] **Step 3.2: Manually verify the profile form in a browser**

In one terminal: `python manage.py runserver` (from the repo root).
In another: `cd frontend && npm run dev`.
Visit `http://localhost:9000/?autologin#/profile`.

Check each of these paths manually:

1. Fields are pre-filled with the current user's email / first / last name.
2. Changing `first_name` and clicking Save shows "Saved.", the sidebar updates the displayed name (if it shows the first name), and reloading the page keeps the change.
3. Entering `not-an-email` in the email field and saving shows the DRF email error message below the email field, status stays at "Save" (not "Saved.").
4. The Preferences view-mode toggle still works.

- [ ] **Step 3.3: Commit**

```bash
git add frontend/src/routes/ProfilePage.svelte
git commit -m "feat(frontend): profile form on /profile backed by PATCH /api/auth/me/

Pre-fills from the auth store, updates the store on success, shows
per-field validation errors. Preserves the existing view-mode toggle.
"
```

---

## Task 4: Frontend — password form on the profile page

**Files:**
- Modify: `frontend/src/routes/ProfilePage.svelte`

### Task 4 steps

- [ ] **Step 4.1: Add the password form and its state to `ProfilePage.svelte`**

Add this state block inside the existing `<script>`, after the `profileSaving` declaration:

```javascript
  let pwForm = $state({
    current_password: '',
    new_password: '',
    new_password_confirm: '',
  });
  let pwErrors = $state({});
  let pwMessage = $state('');
  let pwSaving = $state(false);

  async function changePassword(e) {
    e.preventDefault();
    pwErrors = {};
    pwMessage = '';
    pwSaving = true;
    try {
      await api.post('/api/auth/me/password/', pwForm);
      pwForm.current_password = '';
      pwForm.new_password = '';
      pwForm.new_password_confirm = '';
      pwMessage = 'Password changed.';
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        pwErrors = err.data;
      } else {
        pwErrors = { non_field: ['Could not change password. Please try again.'] };
      }
    } finally {
      pwSaving = false;
    }
  }
```

Then add this markup between the `</form>` (end of profile form) and the `<h3>Preferences</h3>` line:

```svelte
<h3>Change password</h3>
<form onsubmit={changePassword}>
  <p>
    <label for="pw-current"><strong>Current password</strong></label><br>
    <input
      type="password"
      id="pw-current"
      autocomplete="current-password"
      bind:value={pwForm.current_password}
    >
  </p>
  {#each fieldErrors(pwErrors, 'current_password') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <label for="pw-new"><strong>New password</strong></label><br>
    <input
      type="password"
      id="pw-new"
      autocomplete="new-password"
      bind:value={pwForm.new_password}
    >
  </p>
  {#each fieldErrors(pwErrors, 'new_password') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <label for="pw-new-confirm"><strong>Confirm new password</strong></label><br>
    <input
      type="password"
      id="pw-new-confirm"
      autocomplete="new-password"
      bind:value={pwForm.new_password_confirm}
    >
  </p>
  {#each fieldErrors(pwErrors, 'new_password_confirm') as msg}
    <p>{msg}</p>
  {/each}

  {#each fieldErrors(pwErrors, 'non_field_errors') as msg}
    <p>{msg}</p>
  {/each}
  {#each fieldErrors(pwErrors, 'non_field') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <button type="submit" disabled={pwSaving}>
      {pwSaving ? 'Changing...' : 'Change password'}
    </button>
  </p>
  {#if pwMessage}
    <p>{pwMessage}</p>
  {/if}
</form>
```

`fieldErrors` was defined in Task 3 and is reused as-is.

- [ ] **Step 4.2: Manually verify the password form**

With the dev servers running, visit `http://localhost:9000/?autologin#/profile`. Test each case:

1. **Happy path:** `dev_password` / `NewDevPass!99` / `NewDevPass!99`. Expect "Password changed.", form clears, you stay logged in (the page doesn't redirect to login). Change it back immediately so the dev environment still works: `NewDevPass!99` / `dev_password` / `dev_password`.
2. **Wrong current password:** any-wrong / `NewDevPass!99` / `NewDevPass!99`. Expect an error under the `current_password` field. No password change in the DB.
3. **Confirm mismatch:** `dev_password` / `NewDevPass!99` / `Different!99`. Expect "Passwords do not match." under the confirm field.
4. **Too short:** `dev_password` / `abc` / `abc`. Expect a length validator message under `new_password`.
5. **Common password:** `dev_password` / `password` / `password`. Expect a common-password message under `new_password`.
6. **Missing field:** leave Current empty and submit. Expect "This field is required." under `current_password`.

After the happy-path test, confirm you're still logged in by navigating to `/#/` (home). No redirect to login.

- [ ] **Step 4.3: Commit**

```bash
git add frontend/src/routes/ProfilePage.svelte
git commit -m "feat(frontend): password-change form on /profile

Separate form from the profile-info form with its own state and
error display. Uses autocomplete=\"current-password\" and
\"new-password\" so browsers offer to update saved credentials.
"
```

---

## Task 5: Final verification

**Files:** none — this is a pure verification task.

### Task 5 steps

- [ ] **Step 5.1: Run the full backend test suite for `test_api_auth_me` one more time**

Run: `python manage.py test tests.test_api_auth_me -v 2`

Expected: 14 tests passing. If anything is red, fix before moving on.

- [ ] **Step 5.2: Sanity-check neighboring tests**

Run: `python manage.py test tests.test_api_auth -v 2`

Expected: OK. This is the existing auth test module. We extended `me_view` so it's worth confirming the GET behavior is untouched.

- [ ] **Step 5.3: Verify frontend build**

Run: `cd frontend && npm run build`

Expected: build completes without errors. No new build config was added, so a pre-existing failure would be a regression elsewhere — investigate if it happens.

- [ ] **Step 5.4: Verify the git log is clean**

Run: `git log --oneline main..HEAD`

Expected: four commits — the two backend commits, the profile-form commit, and the password-form commit. If a commit is missing, something wasn't committed.

- [ ] **Step 5.5: Invoke the requesting-code-review skill**

At this point the feature is functionally complete. Hand off to `superpowers:requesting-code-review` with a pointer to the design doc (`docs/designs/2026-04-10-user-self-service-design.md`) and this plan.

---

## Out of scope (confirmed with user in design review)

- Owner-side user management (create/list/deactivate users) — next session.
- Syncing profile edits to the linked `Contact` record.
- History/audit logging of profile or password changes.
- Fixing the stale `LOGIN_URL = '/admin/login/'` — separate tech-debt fix.
- Deleting `apps/estimates/admin.py` (empty file) — cosmetic, separate.

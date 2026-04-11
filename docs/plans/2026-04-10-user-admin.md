# Owner-Side User Administration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users with `can_manage_config` create, view, edit, permission, activate, deactivate, and reset-password for any user, via a new `/users` SPA area backed by a new `/api/users/` DRF viewset.

**Architecture:** A new Django app directory `apps/api/users/` (viewset, serializers, service, urls) mounted at `/api/users/`. All business logic lives in `UserAdminService` — views are thin wrappers. Three self-lockout rules enforced in the service. Side effects of deactivation (close bleps, kill sessions) delegated to helpers. New Svelte routes `/users`, `/users/new`, `/users/:id` in the SPA with four independent sub-forms on the detail page, matching the self-service ProfilePage pattern.

**Tech Stack:** Django 5.2, DRF `ModelViewSet` with custom actions, Django `Group`/`Permission` models for atom storage, Svelte 5 runes, existing `api` client.

**Design doc:** `docs/designs/2026-04-10-user-admin-design.md`

---

## File Structure

**Backend — new files:**
- `apps/api/users/__init__.py` — empty
- `apps/api/users/serializers.py` — `UserListSerializer`, `UserDetailSerializer`, `UserCreateSerializer`, `UserUpdateSerializer`, `PasswordResetSerializer`, `PermissionsUpdateSerializer`
- `apps/api/users/views.py` — `UserViewSet` with custom actions
- `apps/api/users/urls.py` — `DefaultRouter` registration
- `apps/api/users/services.py` — `UserAdminService`
- `tests/test_api_users.py` — 43 tests

**Backend — modified files:**
- `apps/api/urls.py` — register `UserViewSet` on the root router
- `apps/jobs/services.py` — add `BlepService.close_user_open_bleps(user, now=None)` public wrapper around the existing `_close_open`

**Frontend — new files:**
- `frontend/src/lib/formErrors.js` — shared `fieldErrors(errors, field)` helper
- `frontend/src/routes/users/UserListPage.svelte`
- `frontend/src/routes/users/UserCreatePage.svelte`
- `frontend/src/routes/users/UserDetailPage.svelte`

**Frontend — modified files:**
- `frontend/src/lib/api.js` — add one-line `put` helper
- `frontend/src/App.svelte` — register three new routes and import the new pages
- `frontend/src/components/Sidebar.svelte` — drop the `showManage` block, add the `Users` link gated on `can_manage_config`, collapse admin-label derivation
- `frontend/src/routes/ProfilePage.svelte` — import `fieldErrors` from the new shared module instead of defining it locally

---

## Task 1: Backend scaffolding and Blep wrapper

**Files:**
- Create: `apps/api/users/__init__.py`
- Create: `apps/api/users/urls.py`
- Create: `apps/api/users/views.py` (minimal skeleton)
- Create: `apps/api/users/serializers.py` (empty)
- Create: `apps/api/users/services.py` (empty)
- Modify: `apps/api/urls.py`
- Modify: `apps/jobs/services.py`
- Test: `tests/test_api_users.py`

**Context for the engineer:**
- The project already has multiple DRF viewset apps under `apps/api/`. Copy the shape of `apps/api/contacts/views.py` for the viewset skeleton and `apps/api/urls.py` for how to hook it up via `DefaultRouter`.
- `BaseTestCase` in `tests/base.py` loads `unit_test_data.json` which contains four users: `admin` (superuser), `manager1` (non-superuser, is_staff=True), `johnq` (non-superuser, regular), plus one more.
- `CanManageConfig` permission class already exists in `apps/api/permissions.py`. Import from there.
- DRF returns 403 (not 401) for unauthenticated `SessionAuthentication` requests — that's the project convention and what our tests should expect.
- **NEVER run `python manage.py migrate`** — tests auto-create their DB. Only `python manage.py test`.
- **Only one agent at a time runs the test suite** (shared MySQL test DB).

### Task 1 steps

- [ ] **Step 1.1: Create the empty scaffolding files**

Create `apps/api/users/__init__.py` as an empty file.

Create `apps/api/users/serializers.py` with only this:

```python
# Serializers for /api/users/ — populated in later tasks.
```

Create `apps/api/users/services.py` with only this:

```python
# UserAdminService — populated in later tasks.
```

- [ ] **Step 1.2: Write a failing test for the Blep public wrapper**

Append to a new test file `tests/test_api_users.py`:

```python
from datetime import timedelta
from django.utils import timezone
from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Task, Blep, Job, WorkOrder
from apps.jobs.services import BlepService


class BlepPublicWrapperTest(BaseTestCase):
    """BlepService.close_user_open_bleps is a public wrapper around the
    existing _close_open helper, added so other apps can close a user's
    open bleps without reaching into a pseudo-private method.
    """

    def setUp(self):
        super().setUp()
        self.user = User.objects.get(username='johnq')
        # Grab any existing task from the fixture
        self.task = Task.objects.first()
        self.assertIsNotNone(self.task, 'Fixture must provide at least one Task')

    def test_close_user_open_bleps_closes_open_blep(self):
        open_blep = Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=timezone.now(),
            end_time=None,
        )
        BlepService.close_user_open_bleps(self.user)
        open_blep.refresh_from_db()
        self.assertIsNotNone(open_blep.end_time)

    def test_close_user_open_bleps_leaves_closed_blep_alone(self):
        earlier = timezone.now() - timedelta(hours=2)
        closed_blep = Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=earlier,
            end_time=earlier + timedelta(hours=1),
        )
        original_end = closed_blep.end_time
        BlepService.close_user_open_bleps(self.user)
        closed_blep.refresh_from_db()
        self.assertEqual(closed_blep.end_time, original_end)

    def test_close_user_open_bleps_leaves_other_users_bleps_alone(self):
        other_user = User.objects.get(username='admin')
        open_blep = Blep.objects.create(
            user=other_user,
            task=self.task,
            start_time=timezone.now(),
            end_time=None,
        )
        BlepService.close_user_open_bleps(self.user)
        open_blep.refresh_from_db()
        self.assertIsNone(open_blep.end_time)
```

- [ ] **Step 1.3: Run the test to verify it fails**

Run: `python manage.py test tests.test_api_users.BlepPublicWrapperTest -v 2`

Expected: 3 failures with `AttributeError: type object 'BlepService' has no attribute 'close_user_open_bleps'`.

- [ ] **Step 1.4: Add the public wrapper to BlepService**

Edit `apps/jobs/services.py`. Find the `BlepService` class (around line 70) and add this static method immediately after `_close_open`:

```python
    @staticmethod
    def close_user_open_bleps(user, now=None):
        """Close all open bleps for the given user.

        Public wrapper around _close_open — used by UserAdminService when
        deactivating a user. Returns the number of bleps that were closed.
        """
        return BlepService._close_open(user=user, now=now)
```

- [ ] **Step 1.5: Run the Blep wrapper tests to verify they pass**

Run: `python manage.py test tests.test_api_users.BlepPublicWrapperTest -v 2`

Expected: 3 tests pass.

- [ ] **Step 1.6: Write a failing test for the URL mount**

Append to `tests/test_api_users.py`:

```python
from rest_framework.test import APIClient


class UserApiMountTest(BaseTestCase):
    """Smoke test: /api/users/ is mounted and rejects unauthenticated requests."""

    def test_users_list_url_is_mounted(self):
        client = APIClient()
        response = client.get('/api/users/')
        # With IsAuthenticated + CanManageConfig, unauth gets 403
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 1.7: Run to verify 404 (URL not mounted yet)**

Run: `python manage.py test tests.test_api_users.UserApiMountTest -v 2`

Expected: 1 failure — status code is 404 (URL not mounted), not 403.

- [ ] **Step 1.8: Create the minimal UserViewSet + urls + mount**

Create `apps/api/users/views.py`:

```python
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from apps.core.models import User
from apps.api.permissions import CanManageConfig


class UserViewSet(viewsets.ModelViewSet):
    """Owner-side user administration."""

    queryset = User.objects.all().order_by('-is_active', 'username')
    lookup_field = 'pk'
    pagination_class = None  # small lists, no pagination needed

    def get_permissions(self):
        return [IsAuthenticated(), CanManageConfig()]

    def get_serializer_class(self):
        # Populated in later tasks
        from rest_framework import serializers

        class _Placeholder(serializers.Serializer):
            pass
        return _Placeholder
```

Create `apps/api/users/urls.py`:

```python
from rest_framework.routers import DefaultRouter
from .views import UserViewSet

router = DefaultRouter()
router.register(r'', UserViewSet, basename='user')

urlpatterns = router.urls
```

Edit `apps/api/urls.py`. Add the include near the other `path(..., include(...))` entries (around line 88 next to the `qbo` include):

```python
    path('users/', include('apps.api.users.urls')),
```

- [ ] **Step 1.9: Run the mount test**

Run: `python manage.py test tests.test_api_users.UserApiMountTest -v 2`

Expected: 1 pass.

- [ ] **Step 1.10: Run the full test file to confirm nothing regressed**

Run: `python manage.py test tests.test_api_users -v 2`

Expected: 4 tests pass (3 Blep + 1 mount).

- [ ] **Step 1.11: Commit**

```bash
git add apps/api/users/ apps/api/urls.py apps/jobs/services.py tests/test_api_users.py
git commit -m "feat(api): scaffold /api/users/ namespace and add BlepService.close_user_open_bleps

Adds empty UserViewSet scaffold mounted at /api/users/, plus a public
wrapper on BlepService.close_user_open_bleps so the user admin service
can close a deactivated user's open bleps without reaching into a
pseudo-private helper.
"
```

---

## Task 2: Read endpoints (list + retrieve) and permission gating

**Files:**
- Modify: `apps/api/users/serializers.py`
- Modify: `apps/api/users/views.py`
- Test: `tests/test_api_users.py`

**Context for the engineer:**
- `UserListSerializer` fields: `id, username, first_name, last_name, email, is_active, is_superuser` — all read-only.
- `UserDetailSerializer` = list fields + `permissions` (SerializerMethodField returning a list of atom codenames) + `date_joined`.
- `get_permissions` returns the user's atom codenames by filtering `user.user_permissions` (direct grants — we're not using groups). Note: the self-service `UserSerializer` in `apps/api/auth/serializers.py` uses `obj.get_all_permissions()` which includes group-granted permissions too. For the admin surface, we want to show atoms that are **directly granted** (or the intersection of granted-plus-effective is fine either way since groups aren't used). Use `obj.user_permissions.filter(codename__startswith='can_').values_list('codename', flat=True)`.
- The existing `admin` fixture user is a superuser — its permissions come from `is_superuser=True`, not from `user_permissions` rows. So for an admin we'd return an empty list of explicit permissions but the is_superuser badge conveys that. Workable; tests will assert on `johnq` (regular user) for specific permission assertions.
- For the permission gating tests we need a user with `can_manage_config`. Fixture users don't have it. Create one in `setUp` by granting the permission directly.

### Task 2 steps

- [ ] **Step 2.1: Write failing tests for list + retrieve + gating**

Append to `tests/test_api_users.py`:

```python
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType


class UserListRetrieveTest(BaseTestCase):
    """Tests for GET /api/users/ and GET /api/users/:id/"""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        # Grab an admin-capable user by granting can_manage_config to johnq
        ct = ContentType.objects.get(app_label='core', model='user')
        self.manage_config_perm = Permission.objects.get(
            codename='can_manage_config', content_type=ct
        )
        self.admin = User.objects.get(username='johnq')
        self.admin.user_permissions.add(self.manage_config_perm)
        # A non-admin for gating tests
        self.non_admin = User.objects.get(username='manager1')
        # Remove any direct can_manage_config grant from manager1 just in case
        self.non_admin.user_permissions.remove(self.manage_config_perm)
        self.non_admin.is_superuser = False
        self.non_admin.save()

    def test_list_unauthenticated_returns_403(self):
        response = self.client.get('/api/users/')
        self.assertEqual(response.status_code, 403)

    def test_list_as_non_admin_returns_403(self):
        self.client.force_authenticate(user=self.non_admin)
        response = self.client.get('/api/users/')
        self.assertEqual(response.status_code, 403)

    def test_list_as_admin_returns_200(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/users/')
        self.assertEqual(response.status_code, 200)

    def test_list_is_not_paginated(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/users/')
        # Plain array, not a paginated wrapper
        self.assertIsInstance(response.data, list)

    def test_list_returns_all_users_including_inactive(self):
        # Deactivate one fixture user
        target = User.objects.get(username='admin')
        target.is_active = False
        target.save()
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/users/')
        usernames = [u['username'] for u in response.data]
        self.assertIn('admin', usernames)
        self.assertIn('johnq', usernames)

    def test_list_orders_active_first(self):
        target = User.objects.get(username='admin')
        target.is_active = False
        target.save()
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/users/')
        # All active users should come before all inactive users
        active_flags = [u['is_active'] for u in response.data]
        # A sorted-descending-by-is_active list has all True before all False
        self.assertEqual(active_flags, sorted(active_flags, reverse=True))

    def test_list_fields(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/users/')
        row = next(u for u in response.data if u['username'] == 'johnq')
        expected_keys = {'id', 'username', 'first_name', 'last_name', 'email', 'is_active', 'is_superuser'}
        self.assertEqual(set(row.keys()), expected_keys)

    def test_retrieve_returns_detail_fields(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(f'/api/users/{self.non_admin.pk}/')
        self.assertEqual(response.status_code, 200)
        expected_keys = {
            'id', 'username', 'first_name', 'last_name', 'email',
            'is_active', 'is_superuser', 'permissions', 'date_joined',
        }
        self.assertEqual(set(response.data.keys()), expected_keys)

    def test_retrieve_includes_permission_codenames(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(f'/api/users/{self.admin.pk}/')
        self.assertIn('can_manage_config', response.data['permissions'])
```

- [ ] **Step 2.2: Run the tests to verify they fail**

Run: `python manage.py test tests.test_api_users.UserListRetrieveTest -v 2`

Expected: most tests fail. The gating tests (403) may pass by accident because the placeholder serializer doesn't render anything coherent. That's fine — we're about to replace it.

- [ ] **Step 2.3: Implement the list + detail serializers**

Replace the contents of `apps/api/users/serializers.py` with:

```python
from rest_framework import serializers
from apps.core.models import User


class UserListSerializer(serializers.ModelSerializer):
    """Row shape for GET /api/users/."""
    id = serializers.IntegerField(source='pk', read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name',
            'email', 'is_active', 'is_superuser',
        ]
        read_only_fields = fields


class UserDetailSerializer(serializers.ModelSerializer):
    """Row shape for GET /api/users/:id/."""
    id = serializers.IntegerField(source='pk', read_only=True)
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'email',
            'is_active', 'is_superuser', 'permissions', 'date_joined',
        ]
        read_only_fields = fields

    def get_permissions(self, obj):
        """Return directly-granted atom codenames (groups not used)."""
        return sorted(
            obj.user_permissions.filter(
                codename__startswith='can_',
                content_type__app_label='core',
            ).values_list('codename', flat=True)
        )
```

- [ ] **Step 2.4: Update the viewset to use the real serializers**

Replace the contents of `apps/api/users/views.py` with:

```python
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from apps.core.models import User
from apps.api.permissions import CanManageConfig
from .serializers import UserListSerializer, UserDetailSerializer


class UserViewSet(viewsets.ModelViewSet):
    """Owner-side user administration."""

    queryset = User.objects.all().order_by('-is_active', 'username')
    lookup_field = 'pk'
    pagination_class = None

    def get_permissions(self):
        return [IsAuthenticated(), CanManageConfig()]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return UserDetailSerializer
        return UserListSerializer
```

- [ ] **Step 2.5: Run the list + retrieve tests**

Run: `python manage.py test tests.test_api_users.UserListRetrieveTest -v 2`

Expected: 10 tests pass.

- [ ] **Step 2.6: Run the full file to confirm no regressions**

Run: `python manage.py test tests.test_api_users -v 2`

Expected: 14 tests pass (3 Blep + 1 mount + 10 list/retrieve).

- [ ] **Step 2.7: Commit**

```bash
git add apps/api/users/serializers.py apps/api/users/views.py tests/test_api_users.py
git commit -m "feat(api): list and retrieve users with can_manage_config gating

Adds UserListSerializer and UserDetailSerializer. The list endpoint
returns every user (active first, then inactive) without pagination.
The detail endpoint includes directly-granted permission codenames.
"
```

---

## Task 3: Create user endpoint

**Files:**
- Modify: `apps/api/users/serializers.py`
- Modify: `apps/api/users/views.py`
- Test: `tests/test_api_users.py`

**Context for the engineer:**
- `UserCreateSerializer` is a `ModelSerializer` with `fields = ['username', 'email', 'first_name', 'last_name', 'password', 'password_confirm']`.
- Override `first_name` and `last_name` as explicit `CharField(required=True)` to defeat Django's default `blank=True`.
- `password` and `password_confirm` are both `CharField(write_only=True, required=True)`.
- Use `django.contrib.auth.password_validation.validate_password` (aliased to avoid collision with DRF's). Catch `django.core.exceptions.ValidationError` and re-raise as `serializers.ValidationError(list(e.messages))` — same pattern as the self-service feature's `PasswordChangeSerializer`.
- `validate` method checks `password == password_confirm`; if not, raise `{'password_confirm': ['Passwords do not match.']}`.
- `create` calls `User.objects.create_user(username=..., email=..., first_name=..., last_name=...)` then `user.set_password(...)` then `user.save()`. (Or `create_user(password=...)` which does the hashing internally — that's cleaner; use it.)
- The `UserViewSet` needs `perform_create` overridden to pipe validated data through the create serializer, returning the new instance.
- Response body for a successful create: render via `UserDetailSerializer` so the frontend gets the full detail shape. DRF's default `CreateModelMixin.create` re-serializes with `self.get_serializer_class()`, which currently returns `UserListSerializer` for the create action — we need to branch by action.

### Task 3 steps

- [ ] **Step 3.1: Write failing tests for create**

Append to `tests/test_api_users.py`:

```python
class UserCreateTest(BaseTestCase):
    """Tests for POST /api/users/."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        ct = ContentType.objects.get(app_label='core', model='user')
        self.manage_config_perm = Permission.objects.get(
            codename='can_manage_config', content_type=ct
        )
        self.admin = User.objects.get(username='johnq')
        self.admin.user_permissions.add(self.manage_config_perm)
        self.client.force_authenticate(user=self.admin)

    def _body(self, **overrides):
        body = {
            'username': 'newbie',
            'email': 'newbie@example.com',
            'first_name': 'New',
            'last_name': 'Bie',
            'password': 'StrongPass!123',
            'password_confirm': 'StrongPass!123',
        }
        body.update(overrides)
        return body

    def test_create_user_happy_path(self):
        response = self.client.post('/api/users/', self._body(), format='json')
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username='newbie')
        self.assertEqual(created.email, 'newbie@example.com')
        self.assertEqual(created.first_name, 'New')
        self.assertEqual(created.last_name, 'Bie')

    def test_create_user_response_uses_detail_shape(self):
        response = self.client.post('/api/users/', self._body(), format='json')
        self.assertEqual(response.status_code, 201)
        # Detail shape: includes permissions + date_joined
        self.assertIn('permissions', response.data)
        self.assertIn('date_joined', response.data)
        # Password NEVER in response
        self.assertNotIn('password', response.data)
        self.assertNotIn('password_confirm', response.data)

    def test_create_user_hashes_password(self):
        self.client.post('/api/users/', self._body(), format='json')
        created = User.objects.get(username='newbie')
        self.assertTrue(created.check_password('StrongPass!123'))
        self.assertNotEqual(created.password, 'StrongPass!123')

    def test_create_user_sets_is_active_true_by_default(self):
        self.client.post('/api/users/', self._body(), format='json')
        created = User.objects.get(username='newbie')
        self.assertTrue(created.is_active)

    def test_create_user_duplicate_username_returns_400(self):
        response = self.client.post('/api/users/', self._body(username='johnq'), format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('username', response.data)

    def test_create_user_invalid_email_returns_400(self):
        response = self.client.post('/api/users/', self._body(email='not-an-email'), format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.data)

    def test_create_user_password_too_short_returns_400(self):
        response = self.client.post(
            '/api/users/',
            self._body(password='abc', password_confirm='abc'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('password', response.data)

    def test_create_user_password_common_returns_400(self):
        response = self.client.post(
            '/api/users/',
            self._body(password='password', password_confirm='password'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('password', response.data)

    def test_create_user_password_mismatch_returns_400(self):
        response = self.client.post(
            '/api/users/',
            self._body(password_confirm='Different!123'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('password_confirm', response.data)

    def test_create_user_ignores_is_staff_in_body(self):
        body = self._body()
        body['is_staff'] = True
        body['is_superuser'] = True
        body['is_active'] = False
        response = self.client.post('/api/users/', body, format='json')
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username='newbie')
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)
        self.assertTrue(created.is_active)

    def test_create_user_missing_required_field_returns_400(self):
        body = self._body()
        del body['first_name']
        response = self.client.post('/api/users/', body, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('first_name', response.data)

    def test_create_user_as_non_admin_returns_403(self):
        manager = User.objects.get(username='manager1')
        manager.user_permissions.remove(self.manage_config_perm)
        manager.is_superuser = False
        manager.save()
        self.client.force_authenticate(user=manager)
        response = self.client.post('/api/users/', self._body(), format='json')
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 3.2: Run to verify failures**

Run: `python manage.py test tests.test_api_users.UserCreateTest -v 2`

Expected: most tests fail — the viewset doesn't have a create serializer yet.

- [ ] **Step 3.3: Add `UserCreateSerializer` to serializers**

Edit `apps/api/users/serializers.py`. Add imports at the top:

```python
from django.contrib.auth.password_validation import (
    validate_password as django_validate_password,
)
from django.core.exceptions import ValidationError as DjangoValidationError
```

Add this class at the end of the file:

```python
class UserCreateSerializer(serializers.ModelSerializer):
    """Input shape for POST /api/users/."""
    first_name = serializers.CharField(required=True)
    last_name = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True)
    password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = [
            'username', 'email', 'first_name', 'last_name',
            'password', 'password_confirm',
        ]

    def validate_password(self, value):
        # Can't pass the user here because it doesn't exist yet.
        try:
            django_validate_password(value, user=None)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate(self, attrs):
        if attrs.get('password') != attrs.get('password_confirm'):
            raise serializers.ValidationError(
                {'password_confirm': ['Passwords do not match.']}
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = User.objects.create_user(password=password, **validated_data)
        return user
```

- [ ] **Step 3.4: Wire create into the viewset and return detail shape**

Edit `apps/api/users/views.py`. Replace the imports and class with:

```python
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from apps.core.models import User
from apps.api.permissions import CanManageConfig
from .serializers import (
    UserListSerializer,
    UserDetailSerializer,
    UserCreateSerializer,
)


class UserViewSet(viewsets.ModelViewSet):
    """Owner-side user administration."""

    queryset = User.objects.all().order_by('-is_active', 'username')
    lookup_field = 'pk'
    pagination_class = None

    def get_permissions(self):
        return [IsAuthenticated(), CanManageConfig()]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return UserDetailSerializer
        if self.action == 'create':
            return UserCreateSerializer
        return UserListSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        # Return the detail shape, not the create-input shape
        return Response(
            UserDetailSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )
```

- [ ] **Step 3.5: Run the create tests**

Run: `python manage.py test tests.test_api_users.UserCreateTest -v 2`

Expected: 12 tests pass.

- [ ] **Step 3.6: Run the full file to confirm no regressions**

Run: `python manage.py test tests.test_api_users -v 2`

Expected: 26 tests pass (14 from Tasks 1-2 + 12 new).

- [ ] **Step 3.7: Commit**

```bash
git add apps/api/users/serializers.py apps/api/users/views.py tests/test_api_users.py
git commit -m "feat(api): add user create endpoint with password validation

POST /api/users/ creates a user via create_user (hashes password),
validates against AUTH_PASSWORD_VALIDATORS, enforces password confirm
match, and returns the UserDetailSerializer shape. Privilege flags
and is_active in the body are silently ignored (serializer allowlist).
"
```

---

## Task 4: Update user endpoint (PATCH)

**Files:**
- Modify: `apps/api/users/serializers.py`
- Modify: `apps/api/users/views.py`
- Test: `tests/test_api_users.py`

**Context:**
- `UserUpdateSerializer` is a `ModelSerializer` with `fields = ['username', 'email', 'first_name', 'last_name']` — all optional via partial update.
- Same "fields allowlist is the guard" pattern used in Task 1's profile PATCH from the self-service feature.
- Admin CAN edit username here (unlike self-service, which blocks it).
- No password handling — that's a dedicated endpoint (Task 6).
- Viewset's `get_serializer_class` branches for `partial_update`.
- Viewset overrides `partial_update` (and/or `update`) to return the `UserDetailSerializer` shape on success.
- `hard delete` disable: override `destroy` to raise `MethodNotAllowed` from `rest_framework.exceptions`.

### Task 4 steps

- [ ] **Step 4.1: Write failing tests for update + delete**

Append to `tests/test_api_users.py`:

```python
class UserUpdateTest(BaseTestCase):
    """Tests for PATCH /api/users/:id/ and DELETE /api/users/:id/."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        ct = ContentType.objects.get(app_label='core', model='user')
        self.manage_config_perm = Permission.objects.get(
            codename='can_manage_config', content_type=ct
        )
        self.admin = User.objects.get(username='johnq')
        self.admin.user_permissions.add(self.manage_config_perm)
        self.client.force_authenticate(user=self.admin)
        self.target = User.objects.get(username='manager1')

    def test_patch_updates_allowed_fields(self):
        response = self.client.patch(
            f'/api/users/{self.target.pk}/',
            {
                'email': 'newmanager@example.com',
                'first_name': 'NewFirst',
                'last_name': 'NewLast',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.email, 'newmanager@example.com')
        self.assertEqual(self.target.first_name, 'NewFirst')
        self.assertEqual(self.target.last_name, 'NewLast')

    def test_patch_admin_can_edit_username(self):
        response = self.client.patch(
            f'/api/users/{self.target.pk}/',
            {'username': 'managerX'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.username, 'managerX')

    def test_patch_response_uses_detail_shape(self):
        response = self.client.patch(
            f'/api/users/{self.target.pk}/',
            {'first_name': 'Renamed'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('permissions', response.data)
        self.assertIn('date_joined', response.data)

    def test_patch_ignores_password(self):
        original_pw = self.target.password
        response = self.client.patch(
            f'/api/users/{self.target.pk}/',
            {'password': 'TryingToHack!1'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.password, original_pw)

    def test_patch_ignores_is_active(self):
        self.assertTrue(self.target.is_active)
        response = self.client.patch(
            f'/api/users/{self.target.pk}/',
            {'is_active': False},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)

    def test_patch_ignores_is_superuser(self):
        self.assertFalse(self.target.is_superuser)
        response = self.client.patch(
            f'/api/users/{self.target.pk}/',
            {'is_superuser': True},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_superuser)

    def test_patch_ignores_user_permissions(self):
        self.assertEqual(self.target.user_permissions.count(), 0)
        response = self.client.patch(
            f'/api/users/{self.target.pk}/',
            {'user_permissions': [self.manage_config_perm.pk]},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.user_permissions.count(), 0)

    def test_delete_returns_405(self):
        response = self.client.delete(f'/api/users/{self.target.pk}/')
        self.assertEqual(response.status_code, 405)
        self.assertTrue(User.objects.filter(pk=self.target.pk).exists())
```

- [ ] **Step 4.2: Run to verify failures**

Run: `python manage.py test tests.test_api_users.UserUpdateTest -v 2`

Expected: most fail — no update serializer, delete likely deletes the user.

- [ ] **Step 4.3: Add `UserUpdateSerializer` to serializers**

Edit `apps/api/users/serializers.py` and append:

```python
class UserUpdateSerializer(serializers.ModelSerializer):
    """Input shape for PATCH /api/users/:id/. Profile fields only.

    Fields allowlist is the privilege-escalation guard — password, flags,
    groups, and permissions are handled via dedicated endpoints.
    """
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']
```

- [ ] **Step 4.4: Wire update + delete into the viewset**

Edit `apps/api/users/views.py`. Update the serializer import to include `UserUpdateSerializer`:

```python
from .serializers import (
    UserListSerializer,
    UserDetailSerializer,
    UserCreateSerializer,
    UserUpdateSerializer,
)
```

Add `MethodNotAllowed` to the rest_framework exceptions import:

```python
from rest_framework.exceptions import MethodNotAllowed
```

Update `get_serializer_class`:

```python
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return UserDetailSerializer
        if self.action == 'create':
            return UserCreateSerializer
        if self.action in ('update', 'partial_update'):
            return UserUpdateSerializer
        return UserListSerializer
```

Add these methods to the viewset:

```python
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        instance.refresh_from_db()
        return Response(UserDetailSerializer(instance).data)

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed('DELETE', detail='Users cannot be hard-deleted. Use deactivate instead.')
```

- [ ] **Step 4.5: Run the update tests**

Run: `python manage.py test tests.test_api_users.UserUpdateTest -v 2`

Expected: 8 tests pass.

- [ ] **Step 4.6: Run the full file to confirm no regressions**

Run: `python manage.py test tests.test_api_users -v 2`

Expected: 34 tests pass (26 from earlier tasks + 8 new).

- [ ] **Step 4.7: Commit**

```bash
git add apps/api/users/serializers.py apps/api/users/views.py tests/test_api_users.py
git commit -m "feat(api): add user update endpoint and disable hard delete

PATCH /api/users/:id/ updates profile fields via a fields-allowlisted
ModelSerializer. DELETE returns 405 — deactivation is the only removal
path. Response body uses UserDetailSerializer shape.
"
```

---

## Task 5: UserAdminService + activate/deactivate endpoints

**Files:**
- Modify: `apps/api/users/services.py`
- Modify: `apps/api/users/views.py`
- Test: `tests/test_api_users.py`

**Context:**
- `UserAdminService` is a class with static methods. Pattern matches `BlepService` and other services in the codebase.
- `deactivate_user(actor, target)` runs lockout checks, then flips `is_active=False`, then closes open bleps, then kills sessions. Returns the target.
- `activate_user(actor, target)` just flips `is_active=True`. No side effects.
- Lockout checks raise `rest_framework.exceptions.ValidationError` so DRF formats them as 400 automatically.
- `_kill_sessions_for_user(user)` iterates `django.contrib.sessions.models.Session`, decodes each, deletes the ones matching the user's pk.
- D1: can't deactivate self.
- D3 for deactivate: can't deactivate the last active user with `can_manage_config`.
- "Last active admin" query: `User.objects.filter(is_active=True, user_permissions__codename='can_manage_config', user_permissions__content_type__app_label='core').distinct().count() == 1`. Only blocks if the *target* is that user.
- Viewset custom actions use `@action(detail=True, methods=['post'])`.

### Task 5 steps

- [ ] **Step 5.1: Write failing tests for activate/deactivate**

Append to `tests/test_api_users.py`:

```python
from django.contrib.sessions.models import Session


class UserActivateDeactivateTest(BaseTestCase):
    """Tests for POST /api/users/:id/activate/ and /deactivate/."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        ct = ContentType.objects.get(app_label='core', model='user')
        self.manage_config_perm = Permission.objects.get(
            codename='can_manage_config', content_type=ct
        )
        # Two admins so "last admin" checks have room to breathe
        self.admin1 = User.objects.get(username='johnq')
        self.admin1.user_permissions.add(self.manage_config_perm)
        self.admin2 = User.objects.get(username='manager1')
        self.admin2.is_superuser = False
        self.admin2.user_permissions.add(self.manage_config_perm)
        self.admin2.save()
        # A non-admin target
        self.target = User.objects.get(username='admin')
        self.target.is_superuser = False
        self.target.save()
        self.client.force_authenticate(user=self.admin1)

    def test_deactivate_sets_is_active_false(self):
        response = self.client.post(f'/api/users/{self.target.pk}/deactivate/')
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertFalse(response.data['is_active'])

    def test_deactivate_closes_open_bleps(self):
        task = Task.objects.first()
        open_blep = Blep.objects.create(
            user=self.target, task=task,
            start_time=timezone.now(), end_time=None,
        )
        self.client.post(f'/api/users/{self.target.pk}/deactivate/')
        open_blep.refresh_from_db()
        self.assertIsNotNone(open_blep.end_time)

    def test_deactivate_does_not_touch_already_closed_bleps(self):
        task = Task.objects.first()
        earlier = timezone.now() - timedelta(hours=2)
        closed_blep = Blep.objects.create(
            user=self.target, task=task,
            start_time=earlier,
            end_time=earlier + timedelta(hours=1),
        )
        original_end = closed_blep.end_time
        self.client.post(f'/api/users/{self.target.pk}/deactivate/')
        closed_blep.refresh_from_db()
        self.assertEqual(closed_blep.end_time, original_end)

    def test_deactivate_kills_target_session(self):
        # Log the target in with a real session
        self.target.set_password('TargetPass!99')
        self.target.save()
        target_client = APIClient()
        target_client.login(username=self.target.username, password='TargetPass!99')
        # Target confirms they're authenticated
        me = target_client.get('/api/auth/me/')
        self.assertEqual(me.status_code, 200)
        # Admin deactivates target via a separate client
        self.client.post(f'/api/users/{self.target.pk}/deactivate/')
        # Target's existing session should be gone
        me_after = target_client.get('/api/auth/me/')
        self.assertEqual(me_after.status_code, 403)

    def test_deactivate_self_returns_400(self):
        response = self.client.post(f'/api/users/{self.admin1.pk}/deactivate/')
        self.assertEqual(response.status_code, 400)
        self.admin1.refresh_from_db()
        self.assertTrue(self.admin1.is_active)

    def test_deactivate_last_admin_returns_400(self):
        """D3: can't deactivate the only user with can_manage_config.

        Setup: admin2 is the only user with can_manage_config (strip it
        from admin1). admin1 becomes a superuser so they can still call
        the admin endpoint (is_superuser bypasses the CanManageConfig
        permission class). Then admin1 tries to deactivate admin2 — the
        last permission-holder — and D3 must fire.
        """
        self.admin1.user_permissions.remove(self.manage_config_perm)
        self.admin1.is_superuser = True
        self.admin1.save()
        # admin2 already has can_manage_config from setUp; confirm it.
        self.assertTrue(
            self.admin2.user_permissions.filter(codename='can_manage_config').exists()
        )
        self.client.force_authenticate(user=self.admin1)
        response = self.client.post(f'/api/users/{self.admin2.pk}/deactivate/')
        self.assertEqual(response.status_code, 400)
        self.admin2.refresh_from_db()
        self.assertTrue(self.admin2.is_active)

    def test_activate_sets_is_active_true(self):
        self.target.is_active = False
        self.target.save()
        response = self.client.post(f'/api/users/{self.target.pk}/activate/')
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)

    def test_activate_has_no_side_effects(self):
        self.target.is_active = False
        self.target.save()
        task = Task.objects.first()
        closed_blep = Blep.objects.create(
            user=self.target, task=task,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
        )
        original_end = closed_blep.end_time
        self.client.post(f'/api/users/{self.target.pk}/activate/')
        closed_blep.refresh_from_db()
        # Bleps are not reopened
        self.assertEqual(closed_blep.end_time, original_end)
```

- [ ] **Step 5.2: Run to verify failures**

Run: `python manage.py test tests.test_api_users.UserActivateDeactivateTest -v 2`

Expected: 8 failures (404 for the custom actions that don't exist yet).

- [ ] **Step 5.3: Implement UserAdminService**

Replace the contents of `apps/api/users/services.py` with:

```python
"""Owner-side user administration service.

All business logic (lockout checks, side effects) lives here so the
viewset stays a thin wrapper.
"""
from django.contrib.sessions.models import Session
from rest_framework import serializers as drf_serializers
from apps.core.models import User
from apps.jobs.services import BlepService


class UserAdminService:

    # ── deactivate ─────────────────────────────────────────────

    @staticmethod
    def deactivate_user(actor, target):
        UserAdminService._check_not_self(actor, target, action='deactivate')
        UserAdminService._check_not_last_admin_by_flag(target)
        target.is_active = False
        target.save(update_fields=['is_active'])
        BlepService.close_user_open_bleps(target)
        UserAdminService._kill_sessions_for_user(target)
        return target

    # ── activate ───────────────────────────────────────────────

    @staticmethod
    def activate_user(actor, target):
        target.is_active = True
        target.save(update_fields=['is_active'])
        return target

    # ── helpers ────────────────────────────────────────────────

    @staticmethod
    def _check_not_self(actor, target, action):
        if actor.pk == target.pk:
            raise drf_serializers.ValidationError(
                f'You cannot {action} yourself.'
            )

    @staticmethod
    def _check_not_last_admin_by_flag(target):
        """Block deactivation if target is the only active user with
        can_manage_config. Only runs if target currently has the permission.
        """
        if not UserAdminService._target_has_can_manage_config(target):
            return
        count = UserAdminService._count_active_admins()
        if count <= 1:
            raise drf_serializers.ValidationError(
                'Cannot deactivate the last user who can manage config.'
            )

    @staticmethod
    def _target_has_can_manage_config(target):
        return target.user_permissions.filter(
            codename='can_manage_config',
            content_type__app_label='core',
        ).exists()

    @staticmethod
    def _count_active_admins():
        return User.objects.filter(
            is_active=True,
            user_permissions__codename='can_manage_config',
            user_permissions__content_type__app_label='core',
        ).distinct().count()

    @staticmethod
    def _kill_sessions_for_user(user):
        """Delete any Django sessions whose _auth_user_id matches this user.

        Django's default DB session store has no index on decoded user ID,
        so we iterate. Fine for small shops.
        """
        target_pk = str(user.pk)
        for session in Session.objects.all():
            data = session.get_decoded()
            if data.get('_auth_user_id') == target_pk:
                session.delete()
```

- [ ] **Step 5.4: Wire activate/deactivate into the viewset**

Edit `apps/api/users/views.py`. Add `action` to the imports:

```python
from rest_framework.decorators import action
```

Add the service import:

```python
from .services import UserAdminService
```

Add these methods to `UserViewSet`:

```python
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        target = self.get_object()
        UserAdminService.deactivate_user(request.user, target)
        return Response(UserDetailSerializer(target).data)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        target = self.get_object()
        UserAdminService.activate_user(request.user, target)
        return Response(UserDetailSerializer(target).data)
```

- [ ] **Step 5.5: Run the activate/deactivate tests**

Run: `python manage.py test tests.test_api_users.UserActivateDeactivateTest -v 2`

Expected: 8 tests pass.

- [ ] **Step 5.6: Run the full file to confirm no regressions**

Run: `python manage.py test tests.test_api_users -v 2`

Expected: 42 tests pass (34 from earlier + 8 new).

- [ ] **Step 5.7: Commit**

```bash
git add apps/api/users/services.py apps/api/users/views.py tests/test_api_users.py
git commit -m "feat(api): add activate/deactivate endpoints with side effects

Deactivation closes any open bleps for the target user, kills their
active Django sessions, and enforces self-deactivate (D1) plus
last-admin (D3) lockout rules. Activate has no side effects.
"
```

---

## Task 6: Reset-password endpoint

**Files:**
- Modify: `apps/api/users/serializers.py`
- Modify: `apps/api/users/views.py`
- Test: `tests/test_api_users.py`

**Context:**
- `PasswordResetSerializer` is a pure `serializers.Serializer` (not ModelSerializer).
- Two fields, both `write_only=True, required=True`: `password`, `password_confirm`.
- Validates `password` via `django_validate_password(value, user=None)` — same pattern as create.
- `validate` checks match, attaches mismatch error to `password_confirm`.
- `save()` calls `target.set_password(new)` and `target.save()`. No `update_session_auth_hash` — we WANT the target's existing sessions invalidated.
- Custom viewset action `reset_password`. URL: `POST /api/users/:id/reset-password/`. DRF's `@action` with a hyphenated name uses `url_path='reset-password'`.
- No lockout check — admin resetting their own password is allowed (they forgot it).

### Task 6 steps

- [ ] **Step 6.1: Write failing tests**

Append to `tests/test_api_users.py`:

```python
class UserResetPasswordTest(BaseTestCase):
    """Tests for POST /api/users/:id/reset-password/."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        ct = ContentType.objects.get(app_label='core', model='user')
        self.manage_config_perm = Permission.objects.get(
            codename='can_manage_config', content_type=ct
        )
        self.admin = User.objects.get(username='johnq')
        self.admin.user_permissions.add(self.manage_config_perm)
        self.target = User.objects.get(username='manager1')
        self.target.set_password('OldPass!99')
        self.target.save()
        self.client.force_authenticate(user=self.admin)

    def _body(self, **overrides):
        body = {'password': 'NewPass!88', 'password_confirm': 'NewPass!88'}
        body.update(overrides)
        return body

    def test_reset_password_happy_path(self):
        response = self.client.post(
            f'/api/users/{self.target.pk}/reset-password/',
            self._body(),
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password('NewPass!88'))
        self.assertFalse(self.target.check_password('OldPass!99'))

    def test_reset_password_mismatch_returns_400(self):
        response = self.client.post(
            f'/api/users/{self.target.pk}/reset-password/',
            self._body(password_confirm='Different!88'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('password_confirm', response.data)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password('OldPass!99'))

    def test_reset_password_too_short_returns_400(self):
        response = self.client.post(
            f'/api/users/{self.target.pk}/reset-password/',
            self._body(password='abc', password_confirm='abc'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('password', response.data)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password('OldPass!99'))

    def test_reset_password_common_returns_400(self):
        response = self.client.post(
            f'/api/users/{self.target.pk}/reset-password/',
            self._body(password='password', password_confirm='password'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_reset_password_invalidates_target_session(self):
        target_client = APIClient()
        target_client.login(username='manager1', password='OldPass!99')
        # Confirm target is initially authenticated
        me = target_client.get('/api/auth/me/')
        self.assertEqual(me.status_code, 200)
        # Admin resets via separate client
        self.client.post(
            f'/api/users/{self.target.pk}/reset-password/',
            self._body(),
            format='json',
        )
        # Target's session should be invalid
        me_after = target_client.get('/api/auth/me/')
        self.assertEqual(me_after.status_code, 403)

    def test_reset_password_self_is_allowed(self):
        # Admin resets their own password
        self.client.post(
            f'/api/users/{self.admin.pk}/reset-password/',
            self._body(),
            format='json',
        )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('NewPass!88'))

    def test_reset_password_missing_field_returns_400(self):
        body = self._body()
        del body['password']
        response = self.client.post(
            f'/api/users/{self.target.pk}/reset-password/',
            body,
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('password', response.data)
```

- [ ] **Step 6.2: Run to verify failures**

Run: `python manage.py test tests.test_api_users.UserResetPasswordTest -v 2`

Expected: 7 failures (404).

- [ ] **Step 6.3: Add `PasswordResetSerializer`**

Edit `apps/api/users/serializers.py` and append:

```python
class PasswordResetSerializer(serializers.Serializer):
    """Input shape for POST /api/users/:id/reset-password/.

    Pure Serializer (not ModelSerializer) — it's a pure input validator
    that calls set_password in save(), not a model-backed CRUD serializer.
    """
    password = serializers.CharField(write_only=True, required=True)
    password_confirm = serializers.CharField(write_only=True, required=True)

    def validate_password(self, value):
        try:
            django_validate_password(value, user=None)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate(self, attrs):
        if attrs.get('password') != attrs.get('password_confirm'):
            raise serializers.ValidationError(
                {'password_confirm': ['Passwords do not match.']}
            )
        return attrs

    def save(self, **kwargs):
        target = self.context['target']
        target.set_password(self.validated_data['password'])
        target.save(update_fields=['password'])
        return target
```

- [ ] **Step 6.4: Add the reset-password action to the viewset**

Edit `apps/api/users/views.py`. Update the serializer import to include `PasswordResetSerializer`:

```python
from .serializers import (
    UserListSerializer,
    UserDetailSerializer,
    UserCreateSerializer,
    UserUpdateSerializer,
    PasswordResetSerializer,
)
```

Add this action to `UserViewSet`:

```python
    @action(detail=True, methods=['post'], url_path='reset-password')
    def reset_password(self, request, pk=None):
        target = self.get_object()
        serializer = PasswordResetSerializer(
            data=request.data, context={'target': target}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'detail': 'Password reset.'})
```

- [ ] **Step 6.5: Run the reset-password tests**

Run: `python manage.py test tests.test_api_users.UserResetPasswordTest -v 2`

Expected: 7 tests pass.

- [ ] **Step 6.6: Run the full file to confirm no regressions**

Run: `python manage.py test tests.test_api_users -v 2`

Expected: 49 tests pass (42 from earlier + 7 new).

- [ ] **Step 6.7: Commit**

```bash
git add apps/api/users/serializers.py apps/api/users/views.py tests/test_api_users.py
git commit -m "feat(api): add admin password reset endpoint

POST /api/users/:id/reset-password/ sets a new password on any user.
Runs the new password through AUTH_PASSWORD_VALIDATORS. Does NOT call
update_session_auth_hash — target's existing sessions become invalid
on their next request (desirable).
"
```

---

## Task 7: Permissions endpoint

**Files:**
- Modify: `apps/api/users/serializers.py`
- Modify: `apps/api/users/services.py`
- Modify: `apps/api/users/views.py`
- Test: `tests/test_api_users.py`

**Context:**
- `PermissionsUpdateSerializer` has one field: `permissions = ListField(child=CharField(), allow_empty=True)`.
- Known atom codenames derived from `User._meta.permissions` — gives one source of truth.
- `validate_permissions` rejects unknown codenames.
- `save()` delegates to `UserAdminService.set_permissions(actor, target, codenames)`.
- `set_permissions` runs D2 (no self-demote) and D3 (no last-admin strip) then replaces `user_permissions` M2M via `set()`.
- URL: `PUT /api/users/:id/permissions/` (use `url_path='permissions'`, `methods=['put']`).

### Task 7 steps

- [ ] **Step 7.1: Write failing tests**

Append to `tests/test_api_users.py`:

```python
class UserPermissionsTest(BaseTestCase):
    """Tests for PUT /api/users/:id/permissions/."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        ct = ContentType.objects.get(app_label='core', model='user')
        self.manage_config_perm = Permission.objects.get(
            codename='can_manage_config', content_type=ct
        )
        self.manage_jobs_perm = Permission.objects.get(
            codename='can_manage_jobs', content_type=ct
        )
        # Two admins so D3 has room
        self.admin1 = User.objects.get(username='johnq')
        self.admin1.user_permissions.add(self.manage_config_perm)
        self.admin2 = User.objects.get(username='manager1')
        self.admin2.is_superuser = False
        self.admin2.user_permissions.add(self.manage_config_perm)
        self.admin2.save()
        self.target = User.objects.get(username='admin')
        self.target.is_superuser = False
        self.target.save()
        self.client.force_authenticate(user=self.admin1)

    def test_set_permissions_replaces_m2m(self):
        response = self.client.put(
            f'/api/users/{self.target.pk}/permissions/',
            {'permissions': ['can_manage_jobs', 'can_approve_expenses']},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        codenames = set(
            self.target.user_permissions.values_list('codename', flat=True)
        )
        self.assertEqual(codenames, {'can_manage_jobs', 'can_approve_expenses'})

    def test_set_permissions_empty_list_clears_all_atoms(self):
        self.target.user_permissions.add(self.manage_jobs_perm)
        response = self.client.put(
            f'/api/users/{self.target.pk}/permissions/',
            {'permissions': []},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.user_permissions.count(), 0)

    def test_set_permissions_unknown_codename_returns_400(self):
        response = self.client.put(
            f'/api/users/{self.target.pk}/permissions/',
            {'permissions': ['can_hack_everything']},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('permissions', response.data)

    def test_set_permissions_response_uses_detail_shape(self):
        response = self.client.put(
            f'/api/users/{self.target.pk}/permissions/',
            {'permissions': ['can_manage_jobs']},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('permissions', response.data)
        self.assertIn('date_joined', response.data)
        self.assertEqual(response.data['permissions'], ['can_manage_jobs'])

    def test_set_permissions_remove_own_can_manage_config_returns_400(self):
        # admin1 tries to remove their own can_manage_config
        response = self.client.put(
            f'/api/users/{self.admin1.pk}/permissions/',
            {'permissions': ['can_manage_jobs']},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.admin1.refresh_from_db()
        self.assertTrue(
            self.admin1.user_permissions.filter(codename='can_manage_config').exists()
        )

    def test_set_permissions_remove_last_admin_can_manage_config_returns_400(self):
        """D3: a superuser actor cannot strip can_manage_config from the
        only user who has it. D2 (self-demote) would also fire if the
        actor were the target, so we use a separate is_superuser actor.
        """
        # Strip admin2's can_manage_config so admin1 is the only holder.
        self.admin2.user_permissions.remove(self.manage_config_perm)
        # Create a superuser who can call the endpoint via is_superuser
        # bypass (they don't need can_manage_config themselves).
        other = User.objects.create_superuser(
            username='supe', email='supe@example.com', password='SuperPass!99',
            first_name='Supe', last_name='Rman',
        )
        self.client.force_authenticate(user=other)
        # admin1 is the only user with can_manage_config
        response = self.client.put(
            f'/api/users/{self.admin1.pk}/permissions/',
            {'permissions': []},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.admin1.refresh_from_db()
        self.assertTrue(
            self.admin1.user_permissions.filter(codename='can_manage_config').exists()
        )

    def test_set_permissions_remove_non_last_admin_succeeds(self):
        # Both admin1 and admin2 have can_manage_config. Remove from admin2.
        # admin1 still has it, so D3 should NOT fire.
        # But admin1 is acting; admin2 is target. D2 only fires if actor==target.
        response = self.client.put(
            f'/api/users/{self.admin2.pk}/permissions/',
            {'permissions': ['can_manage_jobs']},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.admin2.refresh_from_db()
        self.assertFalse(
            self.admin2.user_permissions.filter(codename='can_manage_config').exists()
        )
```

- [ ] **Step 7.2: Run to verify failures**

Run: `python manage.py test tests.test_api_users.UserPermissionsTest -v 2`

Expected: 7 failures (404).

- [ ] **Step 7.3: Add `set_permissions` method to UserAdminService**

Edit `apps/api/users/services.py`. Add to the imports at the top:

```python
from django.contrib.auth.models import Permission
```

Add this method inside `UserAdminService`, after `activate_user`:

```python
    @staticmethod
    def set_permissions(actor, target, atom_codenames):
        """Replace target's user_permissions M2M with the given atom set."""
        UserAdminService._check_not_remove_own_manage_config(
            actor, target, atom_codenames
        )
        UserAdminService._check_not_remove_last_admin_manage_config(
            target, atom_codenames
        )
        perms = Permission.objects.filter(
            codename__in=atom_codenames,
            content_type__app_label='core',
        )
        target.user_permissions.set(perms)
        return target

    @staticmethod
    def _check_not_remove_own_manage_config(actor, target, new_codenames):
        if actor.pk != target.pk:
            return
        if 'can_manage_config' in new_codenames:
            return
        if UserAdminService._target_has_can_manage_config(target):
            raise drf_serializers.ValidationError(
                'You cannot remove your own can_manage_config permission.'
            )

    @staticmethod
    def _check_not_remove_last_admin_manage_config(target, new_codenames):
        if 'can_manage_config' in new_codenames:
            return
        if not UserAdminService._target_has_can_manage_config(target):
            return
        count = UserAdminService._count_active_admins()
        if count <= 1:
            raise drf_serializers.ValidationError(
                'Cannot remove can_manage_config from the last user who has it.'
            )
```

- [ ] **Step 7.4: Add `PermissionsUpdateSerializer`**

Edit `apps/api/users/serializers.py` and append:

```python
# Derive the known atom codenames from the User model's declared permissions.
_KNOWN_ATOMS = {codename for codename, _name in User._meta.permissions}


class PermissionsUpdateSerializer(serializers.Serializer):
    """Input shape for PUT /api/users/:id/permissions/."""
    permissions = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=True,
    )

    def validate_permissions(self, value):
        unknown = [c for c in value if c not in _KNOWN_ATOMS]
        if unknown:
            raise serializers.ValidationError(
                f'Unknown permission codename(s): {", ".join(sorted(unknown))}'
            )
        return value
```

- [ ] **Step 7.5: Add the permissions action to the viewset**

Edit `apps/api/users/views.py`. Update the serializer import to include `PermissionsUpdateSerializer`:

```python
from .serializers import (
    UserListSerializer,
    UserDetailSerializer,
    UserCreateSerializer,
    UserUpdateSerializer,
    PasswordResetSerializer,
    PermissionsUpdateSerializer,
)
```

Add this action to `UserViewSet`:

```python
    @action(detail=True, methods=['put'], url_path='permissions')
    def permissions(self, request, pk=None):
        target = self.get_object()
        serializer = PermissionsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        UserAdminService.set_permissions(
            request.user, target, serializer.validated_data['permissions']
        )
        target.refresh_from_db()
        return Response(UserDetailSerializer(target).data)
```

- [ ] **Step 7.6: Run the permissions tests**

Run: `python manage.py test tests.test_api_users.UserPermissionsTest -v 2`

Expected: 7 tests pass.

- [ ] **Step 7.7: Run the full file to confirm no regressions**

Run: `python manage.py test tests.test_api_users -v 2`

Expected: 56 tests pass (49 from earlier + 7 new).

- [ ] **Step 7.8: Commit**

```bash
git add apps/api/users/serializers.py apps/api/users/services.py apps/api/users/views.py tests/test_api_users.py
git commit -m "feat(api): add set-permissions endpoint with D2/D3 lockout checks

PUT /api/users/:id/permissions/ replaces the user's permission atoms.
Derives the known-atom set from User._meta.permissions so a future
atom addition flows through automatically. Enforces D2 (no removing
your own can_manage_config) and D3 (no removing it from the last
admin).
"
```

---

## Task 8: Regression guards for existing assignee-excluding-deactivated behavior

**Files:**
- Test: `tests/test_api_users.py`

**Context:**
- Per the design, three existing endpoints already filter out deactivated users from assignment dropdowns: `/api/auth/users/` (users_list view), and the two `BoardService` queries. This task adds regression tests to protect that behavior, NOT to change code.
- The `/api/auth/users/` test is straightforward. The BoardService tests go through the board API — check `apps/api/jobs/board_views.py` for the entry points.

### Task 8 steps

- [ ] **Step 8.1: Write regression tests**

Append to `tests/test_api_users.py`:

```python
class AssigneeExclusionRegressionTest(BaseTestCase):
    """Guard: deactivated users must not appear in assignee dropdowns.

    These tests protect existing behavior — not new code. If they fail,
    someone removed an is_active filter and needs to put it back.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.caller = User.objects.get(username='johnq')
        self.deactivated = User.objects.get(username='manager1')
        self.deactivated.is_active = False
        self.deactivated.save()

    def test_auth_users_list_excludes_deactivated(self):
        self.client.force_authenticate(user=self.caller)
        response = self.client.get('/api/auth/users/')
        self.assertEqual(response.status_code, 200)
        usernames = [u['username'] for u in response.data]
        self.assertNotIn('manager1', usernames)
        self.assertIn('johnq', usernames)
```

- [ ] **Step 8.2: Run to verify the regression guard passes (existing behavior)**

Run: `python manage.py test tests.test_api_users.AssigneeExclusionRegressionTest -v 2`

Expected: 1 test passes immediately — the existing `apps/api/auth/views.py:70` code already filters on `is_active=True`.

- [ ] **Step 8.3: Run the full file**

Run: `python manage.py test tests.test_api_users -v 2`

Expected: 57 tests pass.

- [ ] **Step 8.4: Commit**

```bash
git add tests/test_api_users.py
git commit -m "test: add regression guard for assignee-dropdown deactivation filter

Protects the existing /api/auth/users/ is_active=True filter so a
future refactor can't silently drop deactivated users back into
assignment dropdowns.
"
```

---

## Task 9: Frontend — extract fieldErrors helper, add api.put

**Files:**
- Create: `frontend/src/lib/formErrors.js`
- Modify: `frontend/src/lib/api.js`
- Modify: `frontend/src/routes/ProfilePage.svelte`

**Context:**
- `fieldErrors(errors, field)` is currently defined inline at the bottom of `ProfilePage.svelte`. Extract it to `frontend/src/lib/formErrors.js` and import from both places.
- `api.js` exports `{ get, post, patch, delete }`. Add `put: (url, data) => request('PUT', url, data)` — the underlying `request` function already supports PUT via its method whitelist.

### Task 9 steps

- [ ] **Step 9.1: Create the shared helper**

Create `frontend/src/lib/formErrors.js` with:

```javascript
/**
 * Read DRF-style field errors from an error-bag object, always
 * returning an array (so `{#each}` works cleanly). Returns [] if
 * the field isn't present.
 */
export function fieldErrors(errors, field) {
  const v = errors?.[field];
  if (!v) return [];
  return Array.isArray(v) ? v : [v];
}
```

- [ ] **Step 9.2: Add put to api.js**

Edit `frontend/src/lib/api.js`. Update the exported `api` object (at the bottom of the file) to include `put`:

```javascript
export const api = {
  get: (url) => request('GET', url),
  post: (url, data) => request('POST', url, data),
  patch: (url, data) => request('PATCH', url, data),
  put: (url, data) => request('PUT', url, data),
  delete: (url) => request('DELETE', url),
};
```

- [ ] **Step 9.3: Update ProfilePage.svelte to import the shared helper**

Edit `frontend/src/routes/ProfilePage.svelte`. At the top of the `<script>` block, add:

```javascript
  import { fieldErrors } from '../lib/formErrors.js';
```

Then find the local `function fieldErrors(errors, field) { ... }` declaration (near the bottom of the `<script>` block, after `changePassword`) and **delete** the function entirely. The imported version replaces it.

- [ ] **Step 9.4: Build-check**

Run: `cd /Users/drshiny/Documents/konbini/Minibini/frontend && npm run build`

Expected: build completes without errors.

- [ ] **Step 9.5: Commit**

```bash
git add frontend/src/lib/formErrors.js frontend/src/lib/api.js frontend/src/routes/ProfilePage.svelte
git commit -m "refactor(frontend): extract fieldErrors helper and add api.put

Moves the DRF field-error reader from ProfilePage.svelte into a shared
lib/formErrors.js so the upcoming user admin pages can reuse it
without copy-paste. Also adds a one-line put helper to api.js for
the permissions endpoint.
"
```

---

## Task 10: Frontend — sidebar replacement (drop /manage, add /users)

**Files:**
- Modify: `frontend/src/components/Sidebar.svelte`

**Context:**
- The current sidebar has a `showManage` derivation and a `<a href="/manage">Manage</a>` link. Neither the route nor any page exists — this is a complete stub.
- Replace with a `Users` link gated on `can_manage_config`.
- Both the existing `showSettings` and the new Users link gate on `can_manage_config` — collapse the admin-label derivation into a single expression.

### Task 10 steps

- [ ] **Step 10.1: Edit the Sidebar script block**

Edit `frontend/src/components/Sidebar.svelte`. Find this block (near line 28):

```javascript
  let showManage = $derived(hasPerm('can_manage_time') || hasPerm('can_approve_expenses'));
  let showSettings = $derived(hasPerm('can_manage_config'));
  let showAdminLabel = $derived(showManage || showSettings);
```

Replace it with:

```javascript
  let showAdminLabel = $derived(hasPerm('can_manage_config'));
```

- [ ] **Step 10.2: Edit the Sidebar markup**

In the same file, find this block (near lines 54-62):

```svelte
    {#if showAdminLabel}
      <div class="section-label">Admin</div>
    {/if}
    {#if showManage}
      <a href="/manage" use:link>Manage</a>
    {/if}
    {#if showSettings}
      <a href="/settings" use:link>Settings</a>
    {/if}
```

Replace it with:

```svelte
    {#if showAdminLabel}
      <div class="section-label">Admin</div>
    {/if}
    {#if hasPerm('can_manage_config')}
      <a href="/users" use:link>Users</a>
    {/if}
    {#if hasPerm('can_manage_config')}
      <a href="/settings" use:link>Settings</a>
    {/if}
```

- [ ] **Step 10.3: Build-check**

Run: `cd /Users/drshiny/Documents/konbini/Minibini/frontend && npm run build`

Expected: build completes without errors.

- [ ] **Step 10.4: Commit**

```bash
git add frontend/src/components/Sidebar.svelte
git commit -m "refactor(frontend): replace Manage placeholder with Users link

The Manage link pointed at /manage which had no route or page — a
dead placeholder. Replaces it with the Users link gated on
can_manage_config (the atom that actually governs user admin) and
collapses the redundant admin-label derivation.
"
```

---

## Task 11: Frontend — UserListPage

**Files:**
- Create: `frontend/src/routes/users/UserListPage.svelte`
- Modify: `frontend/src/App.svelte`

**Context:**
- Plain HTML table, no framework classes, no pagination, no search — per the design.
- Order: whatever the backend returns (active first, then inactive).
- Deactivated rows render with an `<em>` wrapping the status; superusers get a "(superuser)" badge next to the name.
- Loading state, error state, links to New user and to each user detail.

### Task 11 steps

- [ ] **Step 11.1: Create the list page**

Create directory and file `frontend/src/routes/users/UserListPage.svelte`:

```svelte
<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';

  let users = $state([]);
  let loading = $state(true);
  let loadError = $state('');

  async function load() {
    loading = true;
    loadError = '';
    try {
      users = await api.get('/api/users/');
    } catch (err) {
      loadError = err.message || 'Could not load users.';
    } finally {
      loading = false;
    }
  }

  load();
</script>

<h2>Users</h2>

<p><a href="/users/new" use:link>New user</a></p>

{#if loading}
  <p>Loading...</p>
{:else if loadError}
  <p>{loadError}</p>
{:else if users.length === 0}
  <p>No users found.</p>
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

- [ ] **Step 11.2: Register the route in App.svelte**

Edit `frontend/src/App.svelte`. Add the import near the other route imports:

```javascript
  import UserListPage from './routes/users/UserListPage.svelte';
```

Add the route to the `routes` object (before the `/profile` line is fine):

```javascript
    '/users': UserListPage,
```

- [ ] **Step 11.3: Build-check**

Run: `cd /Users/drshiny/Documents/konbini/Minibini/frontend && npm run build`

Expected: build completes without errors.

- [ ] **Step 11.4: Commit**

```bash
git add frontend/src/routes/users/UserListPage.svelte frontend/src/App.svelte
git commit -m "feat(frontend): add user list page at /users

Plain HTML table, no pagination, no search. Active users first, then
deactivated ones flagged with <em>Deactivated</em>. Superusers get a
(superuser) badge. Links to /users/new and /users/:id.
"
```

---

## Task 12: Frontend — UserCreatePage

**Files:**
- Create: `frontend/src/routes/users/UserCreatePage.svelte`
- Modify: `frontend/src/App.svelte`

**Context:**
- Form fields: username, email, first_name, last_name, password, password_confirm.
- Password inputs use `autocomplete="new-password"`.
- On success, redirect to `/users/:id` for the newly-created user.
- On failure, display per-field errors via `fieldErrors`.
- Cancel button returns to `/users`.

### Task 12 steps

- [ ] **Step 12.1: Create the page**

Create `frontend/src/routes/users/UserCreatePage.svelte`:

```svelte
<script>
  import { link, push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { fieldErrors } from '../../lib/formErrors.js';

  let form = $state({
    username: '',
    email: '',
    first_name: '',
    last_name: '',
    password: '',
    password_confirm: '',
  });
  let errors = $state({});
  let saving = $state(false);

  async function handleSubmit(e) {
    e.preventDefault();
    errors = {};
    saving = true;
    try {
      const created = await api.post('/api/users/', form);
      push(`/users/${created.id}`);
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        errors = err.data;
      } else {
        errors = { non_field_errors: ['Could not create user. Please try again.'] };
      }
    } finally {
      saving = false;
    }
  }
</script>

<h2>New user</h2>

<form onsubmit={handleSubmit}>
  <p>
    <label for="new-username"><strong>Username *</strong></label><br>
    <input type="text" id="new-username" bind:value={form.username} required>
  </p>
  {#each fieldErrors(errors, 'username') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <label for="new-email"><strong>Email *</strong></label><br>
    <input type="email" id="new-email" bind:value={form.email} required>
  </p>
  {#each fieldErrors(errors, 'email') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <label for="new-first-name"><strong>First name *</strong></label><br>
    <input type="text" id="new-first-name" bind:value={form.first_name} required>
  </p>
  {#each fieldErrors(errors, 'first_name') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <label for="new-last-name"><strong>Last name *</strong></label><br>
    <input type="text" id="new-last-name" bind:value={form.last_name} required>
  </p>
  {#each fieldErrors(errors, 'last_name') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <label for="new-password"><strong>Password *</strong></label><br>
    <input
      type="password"
      id="new-password"
      autocomplete="new-password"
      bind:value={form.password}
      required
    >
  </p>
  {#each fieldErrors(errors, 'password') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <label for="new-password-confirm"><strong>Confirm password *</strong></label><br>
    <input
      type="password"
      id="new-password-confirm"
      autocomplete="new-password"
      bind:value={form.password_confirm}
      required
    >
  </p>
  {#each fieldErrors(errors, 'password_confirm') as msg}
    <p>{msg}</p>
  {/each}

  {#each fieldErrors(errors, 'non_field_errors') as msg}
    <p>{msg}</p>
  {/each}

  <p>
    <button type="submit" disabled={saving}>
      {saving ? 'Creating...' : 'Create user'}
    </button>
    <a href="/users" use:link>Cancel</a>
  </p>
</form>
```

- [ ] **Step 12.2: Register the route in App.svelte**

Edit `frontend/src/App.svelte`. Add the import:

```javascript
  import UserCreatePage from './routes/users/UserCreatePage.svelte';
```

Add the route (before the `/users/:id` route if it's already there, otherwise just before `/profile`):

```javascript
    '/users/new': UserCreatePage,
```

- [ ] **Step 12.3: Build-check**

Run: `cd /Users/drshiny/Documents/konbini/Minibini/frontend && npm run build`

Expected: build completes without errors.

- [ ] **Step 12.4: Commit**

```bash
git add frontend/src/routes/users/UserCreatePage.svelte frontend/src/App.svelte
git commit -m "feat(frontend): add user create page at /users/new

Form with username/email/name/password fields. Password validated
server-side via AUTH_PASSWORD_VALIDATORS. Redirects to detail page
on success so the owner can immediately set permissions.
"
```

---

## Task 13: Frontend — UserDetailPage (four independent sub-forms)

**Files:**
- Create: `frontend/src/routes/users/UserDetailPage.svelte`
- Modify: `frontend/src/App.svelte`

**Context:**
- This is the most complex page. Four independent sub-forms: profile edit, permissions checkboxes, reset password, activate/deactivate button.
- Mirrors the self-service `ProfilePage.svelte` pattern of "multiple independent forms on one page" with its own state block per form.
- Client-side lockout hints: disable Deactivate and the `can_manage_config` checkbox when viewing your own user.
- After each successful sub-action, replace the local `user` state with the response body so the UI stays in sync.

### Task 13 steps

- [ ] **Step 13.1: Create the page**

Create `frontend/src/routes/users/UserDetailPage.svelte`:

```svelte
<script>
  import { link, push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as currentUser } from '../../stores/auth.js';
  import { fieldErrors } from '../../lib/formErrors.js';

  const { params = {} } = $props();

  const ATOMS = [
    { codename: 'can_manage_jobs', label: 'Can manage jobs' },
    { codename: 'can_manage_financials', label: 'Can manage financials' },
    { codename: 'can_manage_time', label: 'Can manage time entries' },
    { codename: 'can_approve_expenses', label: 'Can approve expenses' },
    { codename: 'can_manage_config', label: 'Can manage configuration (user admin)' },
  ];

  let user = $state(null);
  let loading = $state(true);
  let loadError = $state('');

  let profileForm = $state({ username: '', email: '', first_name: '', last_name: '' });
  let profileErrors = $state({});
  let profileMessage = $state('');
  let profileSaving = $state(false);

  let permForm = $state({ permissions: [] });
  let permErrors = $state({});
  let permMessage = $state('');
  let permSaving = $state(false);

  let pwForm = $state({ password: '', password_confirm: '' });
  let pwErrors = $state({});
  let pwMessage = $state('');
  let pwSaving = $state(false);

  let statusErrors = $state({});
  let statusMessage = $state('');
  let statusSaving = $state(false);

  let isSelf = $derived(
    $currentUser && user && $currentUser.id === user.id
  );

  async function load() {
    loading = true;
    loadError = '';
    try {
      user = await api.get(`/api/users/${params.id}/`);
      seedFormsFromUser();
    } catch (err) {
      loadError = err.message || 'Could not load user.';
    } finally {
      loading = false;
    }
  }

  function seedFormsFromUser() {
    profileForm.username = user.username || '';
    profileForm.email = user.email || '';
    profileForm.first_name = user.first_name || '';
    profileForm.last_name = user.last_name || '';
    permForm.permissions = [...(user.permissions || [])];
  }

  async function saveProfile(e) {
    e.preventDefault();
    profileErrors = {};
    profileMessage = '';
    profileSaving = true;
    try {
      const updated = await api.patch(`/api/users/${user.id}/`, profileForm);
      user = updated;
      profileMessage = 'Saved.';
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        profileErrors = err.data;
      } else {
        profileErrors = { non_field_errors: ['Could not save. Please try again.'] };
      }
    } finally {
      profileSaving = false;
    }
  }

  function togglePerm(codename) {
    if (permForm.permissions.includes(codename)) {
      permForm.permissions = permForm.permissions.filter((c) => c !== codename);
    } else {
      permForm.permissions = [...permForm.permissions, codename];
    }
  }

  async function savePermissions(e) {
    e.preventDefault();
    permErrors = {};
    permMessage = '';
    permSaving = true;
    try {
      const updated = await api.put(
        `/api/users/${user.id}/permissions/`,
        { permissions: permForm.permissions }
      );
      user = updated;
      permForm.permissions = [...(user.permissions || [])];
      permMessage = 'Permissions saved.';
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        permErrors = err.data;
      } else {
        permErrors = { non_field_errors: ['Could not save permissions.'] };
      }
    } finally {
      permSaving = false;
    }
  }

  async function resetPassword(e) {
    e.preventDefault();
    pwErrors = {};
    pwMessage = '';
    pwSaving = true;
    try {
      await api.post(`/api/users/${user.id}/reset-password/`, pwForm);
      pwForm.password = '';
      pwForm.password_confirm = '';
      pwMessage = 'Password reset.';
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        pwErrors = err.data;
      } else {
        pwErrors = { non_field_errors: ['Could not reset password.'] };
      }
    } finally {
      pwSaving = false;
    }
  }

  async function toggleStatus() {
    statusErrors = {};
    statusMessage = '';
    statusSaving = true;
    const actionUrl = user.is_active ? 'deactivate' : 'activate';
    try {
      const updated = await api.post(`/api/users/${user.id}/${actionUrl}/`);
      user = updated;
      statusMessage = user.is_active ? 'User activated.' : 'User deactivated.';
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        statusErrors = err.data;
      } else {
        statusErrors = { non_field_errors: ['Could not change status.'] };
      }
    } finally {
      statusSaving = false;
    }
  }

  $effect(() => {
    // Re-load if the route param changes
    void params.id;
    load();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if loadError}
  <p>{loadError}</p>
  <p><a href="/users" use:link>← Back to users</a></p>
{:else if user}
  <h2>User: {user.username}</h2>
  <p>
    <a href="/users" use:link>← Back to users</a>
  </p>

  <p>
    Status:
    {#if user.is_active}
      <strong>Active</strong>
    {:else}
      <em>Deactivated</em>
    {/if}
    {#if user.is_superuser}
      <em>(superuser — managed via command line)</em>
    {/if}
  </p>

  <h3>Profile</h3>
  <form onsubmit={saveProfile}>
    <p>
      <label for="prof-username"><strong>Username</strong></label><br>
      <input type="text" id="prof-username" bind:value={profileForm.username}>
    </p>
    {#each fieldErrors(profileErrors, 'username') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="prof-email"><strong>Email</strong></label><br>
      <input type="email" id="prof-email" bind:value={profileForm.email}>
    </p>
    {#each fieldErrors(profileErrors, 'email') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="prof-first"><strong>First name</strong></label><br>
      <input type="text" id="prof-first" bind:value={profileForm.first_name}>
    </p>
    {#each fieldErrors(profileErrors, 'first_name') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="prof-last"><strong>Last name</strong></label><br>
      <input type="text" id="prof-last" bind:value={profileForm.last_name}>
    </p>
    {#each fieldErrors(profileErrors, 'last_name') as msg}<p>{msg}</p>{/each}

    {#each fieldErrors(profileErrors, 'non_field_errors') as msg}<p>{msg}</p>{/each}

    <p>
      <button type="submit" disabled={profileSaving}>
        {profileSaving ? 'Saving...' : 'Save profile'}
      </button>
    </p>
    {#if profileMessage}<p>{profileMessage}</p>{/if}
  </form>

  <h3>Permissions</h3>
  <form onsubmit={savePermissions}>
    {#each ATOMS as atom (atom.codename)}
      <p>
        <label>
          <input
            type="checkbox"
            checked={permForm.permissions.includes(atom.codename)}
            onchange={() => togglePerm(atom.codename)}
            disabled={
              isSelf
                && atom.codename === 'can_manage_config'
                && permForm.permissions.includes('can_manage_config')
            }
          >
          <strong>{atom.label}</strong>
        </label>
      </p>
    {/each}
    {#each fieldErrors(permErrors, 'permissions') as msg}<p>{msg}</p>{/each}
    {#each fieldErrors(permErrors, 'non_field_errors') as msg}<p>{msg}</p>{/each}
    <p>
      <button type="submit" disabled={permSaving}>
        {permSaving ? 'Saving...' : 'Save permissions'}
      </button>
    </p>
    {#if permMessage}<p>{permMessage}</p>{/if}
  </form>

  <h3>Reset password</h3>
  <form onsubmit={resetPassword}>
    <p>
      <label for="reset-pw"><strong>New password</strong></label><br>
      <input
        type="password"
        id="reset-pw"
        autocomplete="new-password"
        bind:value={pwForm.password}
      >
    </p>
    {#each fieldErrors(pwErrors, 'password') as msg}<p>{msg}</p>{/each}

    <p>
      <label for="reset-pw-confirm"><strong>Confirm new password</strong></label><br>
      <input
        type="password"
        id="reset-pw-confirm"
        autocomplete="new-password"
        bind:value={pwForm.password_confirm}
      >
    </p>
    {#each fieldErrors(pwErrors, 'password_confirm') as msg}<p>{msg}</p>{/each}

    {#each fieldErrors(pwErrors, 'non_field_errors') as msg}<p>{msg}</p>{/each}

    <p>
      <button type="submit" disabled={pwSaving}>
        {pwSaving ? 'Resetting...' : 'Reset password'}
      </button>
    </p>
    {#if pwMessage}<p>{pwMessage}</p>{/if}
  </form>

  <h3>Account status</h3>
  <p>
    <button
      type="button"
      onclick={toggleStatus}
      disabled={statusSaving || (isSelf && user.is_active)}
    >
      {#if user.is_active}
        {isSelf ? 'Deactivate (cannot deactivate yourself)' : (statusSaving ? 'Deactivating...' : 'Deactivate')}
      {:else}
        {statusSaving ? 'Activating...' : 'Reactivate'}
      {/if}
    </button>
  </p>
  {#each fieldErrors(statusErrors, 'non_field_errors') as msg}<p>{msg}</p>{/each}
  {#if statusMessage}<p>{statusMessage}</p>{/if}
{/if}
```

- [ ] **Step 13.2: Register the route in App.svelte**

Edit `frontend/src/App.svelte`. Add the import:

```javascript
  import UserDetailPage from './routes/users/UserDetailPage.svelte';
```

Add the route:

```javascript
    '/users/:id': UserDetailPage,
```

Make sure this route is registered AFTER `/users/new` in the routes object, otherwise `/users/new` will match `/users/:id` with `id='new'`.

- [ ] **Step 13.3: Build-check**

Run: `cd /Users/drshiny/Documents/konbini/Minibini/frontend && npm run build`

Expected: build completes without errors.

- [ ] **Step 13.4: Commit**

```bash
git add frontend/src/routes/users/UserDetailPage.svelte frontend/src/App.svelte
git commit -m "feat(frontend): add user detail page with four sub-forms

/users/:id shows: profile editor, permission checkboxes, password
reset form, and activate/deactivate button. Each sub-form has its
own independent state. Client-side lockout hints disable the
Deactivate button and the can_manage_config checkbox when viewing
your own user; server-side checks are authoritative.
"
```

---

## Task 14: Final verification

**Files:** none — pure verification.

### Task 14 steps

- [ ] **Step 14.1: Run the full backend test module**

Run: `python manage.py test tests.test_api_users -v 2`

Expected: 57 tests pass.

- [ ] **Step 14.2: Run the self-service auth tests to confirm no regressions**

Run: `python manage.py test tests.test_api_auth_me tests.test_api_auth -v 2`

Expected: all pass (we modified `ProfilePage.svelte` frontend — backend tests should be untouched).

- [ ] **Step 14.3: Run the broader test suite as a sanity check**

Run: `python manage.py test -v 1`

Expected: no regressions. This catches any test elsewhere that relied on the `showManage` derivation or the `/manage` link (none should — `/manage` had no page and the sidebar only imports it as a string).

- [ ] **Step 14.4: Frontend build**

Run: `cd /Users/drshiny/Documents/konbini/Minibini/frontend && npm run build`

Expected: clean build.

- [ ] **Step 14.5: Check the commit log**

Run: `git log --oneline main..HEAD`

Expected: approximately 13 commits from this feature (tasks 1-13 plus earlier work from the self-service feature). The most recent 13 should be the user admin feature.

- [ ] **Step 14.6: Manual browser verification checklist**

Start both dev servers: `python manage.py runserver` and `cd frontend && npm run dev`.

Use dev_user (superuser — bypasses atom checks) for initial access. Then create a second admin via the UI and test lockout checks with that user.

1. Visit `http://localhost:9000/?autologin#/users`. Confirm the Users link appears in the sidebar under Admin. Confirm the list renders.
2. Click "New user". Create a user with a real-looking name and a password like `TestPass!99`. Confirm redirect to the detail page.
3. On the detail page, check one or two permission boxes (e.g., `can_manage_jobs`) and save. Confirm "Permissions saved." message.
4. Edit the profile fields, save. Confirm "Saved." message and the list page shows the update.
5. Reset the new user's password to something different. Confirm "Password reset." message.
6. Deactivate the new user. Confirm: the list shows them as "Deactivated" (italicized), and the detail page button now says "Reactivate".
7. Reactivate. Confirm it flips back.
8. Try to deactivate yourself (dev_user). Confirm the button is disabled with "(cannot deactivate yourself)".
9. Grant the new user `can_manage_config` and log in as them in a private window. Confirm they can reach `/users`.
10. Log in as the new admin, remove your own `can_manage_config`. Confirm: the checkbox is disabled (client hint) AND if you somehow bypass the client hint, the server returns 400.
11. Open a second browser tab logged in as the new user. From your first tab (as dev_user), deactivate the new user. In the second tab, navigate anywhere — expect to be logged out or redirected.
12. Start a blep as the new user, deactivate them, confirm the blep's `end_time` is set (check in the Django shell or in a DB GUI).
13. Try `DELETE http://localhost:8000/api/users/2/` via curl with a session cookie — confirm 405.

- [ ] **Step 14.7: Invoke the requesting-code-review skill for the final whole-feature review**

At this point the feature is functionally complete. Hand off to a final code review.

---

## Out of scope (confirmed in design review)

- Owner-side user-to-Contact association.
- Email-based password reset.
- History/audit logging of admin actions.
- Hard-delete users — DELETE intentionally returns 405.
- Visual indicators for deactivated assignees in task/board views — separate follow-up plan.
- Pagination and search on the user list — small-shop assumption.
- `is_superuser` editable in the UI — read-only badge only.
- Django `Group` model — we use atoms directly.
- Fixing stale `LOGIN_URL = '/admin/login/'` — separate tech debt item.

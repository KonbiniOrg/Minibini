# Permissions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILLS: Use superpowers:test-driven-development for all implementation work. Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the permission system from `docs/plans/2026-03-07-permissions-design.md` — permission atoms on the User model, DRF permission classes for API views, Django permission checks for HTML views, and default group fixtures.

**Architecture:** 7 custom permission atoms defined on `core.User.Meta.permissions`. A factory function in `apps/api/permissions.py` creates DRF permission classes that call `has_perm()`. API viewsets override `get_permissions()` to return the appropriate class based on action. HTML views use `@login_required` + `@permission_required` decorators. Default groups (Worker, Manager, Bookkeeper, Admin) are populated via data migration.

**Tech Stack:** Django 5.2, Django REST Framework, MySQL

**Design doc:** `docs/plans/2026-03-07-permissions-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `apps/core/models.py` | Modify | Add `Meta.permissions` to User model |
| `apps/core/migrations/NNNN_add_permission_atoms.py` | Create (auto) | Migration for new permissions |
| `apps/core/migrations/NNNN_create_default_groups.py` | Create | Data migration to create groups with permissions |
| `apps/api/permissions.py` | Modify | `atom_permission()` factory + permission class constants |
| `apps/api/jobs/views.py` | Modify | Add `get_permissions()` |
| `apps/api/contacts/views.py` | Modify | Add `get_permissions()` |
| `apps/api/estimates/views.py` | Modify | Add `get_permissions()` |
| `apps/api/worksheets/views.py` | Modify | Add `get_permissions()` |
| `apps/api/work_orders/views.py` | Modify | Add `get_permissions()` |
| `apps/api/invoicing/views.py` | Modify | Add `get_permissions()` |
| `apps/api/purchasing/views.py` | Modify | Add `get_permissions()` |
| `apps/api/inventory/views.py` | Modify | Add `get_permissions()` |
| `apps/api/templates_config/views.py` | Modify | Add `get_permissions()` / update decorator |
| `apps/api/email/views.py` | Modify | Update `@permission_classes` decorators |
| `apps/api/search/views.py` | Modify | Update `@permission_classes` decorator |
| `apps/jobs/views.py` | Modify | Add `@login_required` + `@permission_required` |
| `apps/contacts/views.py` | Modify | Add `@login_required` + `@permission_required` |
| `apps/core/views.py` | Modify | Add `@login_required` + `@permission_required` |
| `apps/invoicing/views.py` | Modify | Add `@login_required` + `@permission_required` |
| `apps/purchasing/views.py` | Modify | Add `@login_required` + `@permission_required` |
| `fixtures/unit_test_data.json` | Modify | Add permissions + update groups |
| `tests/test_permissions.py` | Create | Permission atom tests |
| `tests/test_api_permissions.py` | Create | API permission enforcement tests |

---

## Task 1: Add Permission Atoms to User Model

**Files:**
- Modify: `apps/core/models.py`
- Create: `apps/core/migrations/NNNN_add_permission_atoms.py` (auto-generated)
- Test: `tests/test_permissions.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_permissions.py`:

```python
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from tests.base import BaseTestCase

User = get_user_model()


class PermissionAtomsTest(BaseTestCase):
    """Verify custom permission atoms exist after migration."""

    EXPECTED_ATOMS = [
        'can_manage_jobs',
        'can_view_jobs',
        'can_manage_invoicing',
        'can_manage_purchasing',
        'can_manage_time',
        'can_approve_expenses',
        'can_manage_config',
    ]

    def test_all_permission_atoms_exist(self):
        """All 7 permission atoms should exist in auth_permission table."""
        for codename in self.EXPECTED_ATOMS:
            with self.subTest(codename=codename):
                self.assertTrue(
                    Permission.objects.filter(
                        codename=codename,
                        content_type__app_label='core',
                    ).exists(),
                    f"Permission '{codename}' not found"
                )

    def test_user_can_be_assigned_permission(self):
        """A permission atom can be assigned to a user and checked via has_perm."""
        user = User.objects.get(username='johnq')
        perm = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
        user.user_permissions.add(perm)
        # Clear cached permissions
        user = User.objects.get(pk=user.pk)
        self.assertTrue(user.has_perm('core.can_manage_jobs'))
        self.assertFalse(user.has_perm('core.can_manage_invoicing'))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_permissions.PermissionAtomsTest -v2`
Expected: FAIL — permissions don't exist yet

- [ ] **Step 3: Add permissions to User model Meta**

In `apps/core/models.py`, add `permissions` to the User model's `Meta`:

```python
class User(AbstractUser):
    """Custom user model extending Django's AbstractUser with business-specific fields."""

    contact = models.OneToOneField(
        'contacts.Contact',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text='Associated contact record for this user'
    )

    class Meta:
        db_table = 'auth_user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        permissions = [
            ('can_manage_jobs', 'Can manage jobs, estimates, worksheets, work orders, tasks'),
            ('can_view_jobs', 'Read-only access to all jobs and related documents'),
            ('can_manage_invoicing', 'Can manage invoices, price list, send/payment'),
            ('can_manage_purchasing', 'Can manage POs, bills, send/receive'),
            ('can_manage_time', "Can edit/delete anyone's time entries"),
            ('can_approve_expenses', 'Can approve/reject expenses over threshold'),
            ('can_manage_config', 'Can manage settings, templates, user admin'),
        ]
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations core`
Expected: creates a migration that adds the custom permissions

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_permissions.PermissionAtomsTest -v2`
Expected: PASS — test database applies migration automatically

- [ ] **Step 6: Commit**

```bash
git add apps/core/models.py apps/core/migrations/ tests/test_permissions.py
git commit -m "feat: add permission atoms to User model"
```

---

## Task 2: Create DRF Permission Classes

**Files:**
- Modify: `apps/api/permissions.py`
- Test: `tests/test_permissions.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_permissions.py`:

```python
from apps.api.permissions import (
    atom_permission, CanManageJobs, CanViewJobs,
    CanManageInvoicing, CanManagePurchasing,
    CanManageTime, CanApproveExpenses, CanManageConfig,
)


class AtomPermissionFactoryTest(BaseTestCase):
    """Test the DRF permission class factory."""

    def _make_request(self, user):
        """Create a fake request object with the given user."""
        from rest_framework.test import APIRequestFactory
        factory = APIRequestFactory()
        request = factory.get('/')
        request.user = user
        return request

    def test_factory_creates_permission_class(self):
        """atom_permission returns a class with has_permission method."""
        PermClass = atom_permission('can_manage_jobs')
        self.assertTrue(hasattr(PermClass, 'has_permission'))

    def test_permission_denied_without_perm(self):
        """User without the permission is denied."""
        user = User.objects.get(username='johnq')
        request = self._make_request(user)
        perm = CanManageJobs()
        self.assertFalse(perm.has_permission(request, None))

    def test_permission_granted_with_direct_perm(self):
        """User with direct permission is allowed."""
        user = User.objects.get(username='johnq')
        perm_obj = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
        user.user_permissions.add(perm_obj)
        user = User.objects.get(pk=user.pk)  # clear cache
        request = self._make_request(user)
        perm = CanManageJobs()
        self.assertTrue(perm.has_permission(request, None))

    def test_superuser_has_all_permissions(self):
        """Superuser passes all permission checks."""
        user = User.objects.get(username='admin')
        request = self._make_request(user)
        self.assertTrue(CanManageJobs().has_permission(request, None))
        self.assertTrue(CanManageInvoicing().has_permission(request, None))
        self.assertTrue(CanManageConfig().has_permission(request, None))

    def test_all_constants_are_defined(self):
        """All 7 permission class constants are importable and functional."""
        classes = [
            CanManageJobs, CanViewJobs, CanManageInvoicing,
            CanManagePurchasing, CanManageTime, CanApproveExpenses,
            CanManageConfig,
        ]
        self.assertEqual(len(classes), 7)
        for cls in classes:
            self.assertTrue(hasattr(cls, 'has_permission'))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_permissions.AtomPermissionFactoryTest -v2`
Expected: FAIL — ImportError, classes don't exist yet

- [ ] **Step 3: Implement the permission classes**

Replace contents of `apps/api/permissions.py`:

```python
from rest_framework.permissions import BasePermission


def atom_permission(perm_codename):
    """Create a DRF permission class for a given permission atom."""
    class AtomPermission(BasePermission):
        def has_permission(self, request, view):
            return request.user.has_perm(f'core.{perm_codename}')
    AtomPermission.__name__ = perm_codename
    return AtomPermission


CanManageJobs = atom_permission('can_manage_jobs')
CanViewJobs = atom_permission('can_view_jobs')
CanManageInvoicing = atom_permission('can_manage_invoicing')
CanManagePurchasing = atom_permission('can_manage_purchasing')
CanManageTime = atom_permission('can_manage_time')
CanApproveExpenses = atom_permission('can_approve_expenses')
CanManageConfig = atom_permission('can_manage_config')
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_permissions.AtomPermissionFactoryTest -v2`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/api/permissions.py tests/test_permissions.py
git commit -m "feat: add DRF permission class factory and constants"
```

---

## Task 3: Create Default Groups via Data Migration

**Files:**
- Create: `apps/core/migrations/NNNN_create_default_groups.py` (manually written data migration)
- Modify: `fixtures/unit_test_data.json` (update groups with permissions)
- Test: `tests/test_permissions.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_permissions.py`:

```python
from django.contrib.auth.models import Group


class DefaultGroupsTest(BaseTestCase):
    """Verify default groups have correct permissions after data migration."""

    def test_worker_group_permissions(self):
        group = Group.objects.get(name='Worker')
        codenames = set(group.permissions.values_list('codename', flat=True))
        self.assertEqual(codenames, {'can_view_jobs'})

    def test_manager_group_permissions(self):
        group = Group.objects.get(name='Manager')
        codenames = set(group.permissions.values_list('codename', flat=True))
        self.assertEqual(codenames, {
            'can_view_jobs', 'can_manage_jobs',
            'can_manage_time', 'can_approve_expenses',
        })

    def test_bookkeeper_group_permissions(self):
        group = Group.objects.get(name='Bookkeeper')
        codenames = set(group.permissions.values_list('codename', flat=True))
        self.assertEqual(codenames, {
            'can_view_jobs', 'can_manage_invoicing',
            'can_manage_purchasing', 'can_approve_expenses',
        })

    def test_admin_group_permissions(self):
        group = Group.objects.get(name='Admin')
        codenames = set(group.permissions.values_list('codename', flat=True))
        expected = {
            'can_manage_jobs', 'can_view_jobs', 'can_manage_invoicing',
            'can_manage_purchasing', 'can_manage_time',
            'can_approve_expenses', 'can_manage_config',
        }
        self.assertEqual(codenames, expected)

    def test_group_permissions_propagate_to_user(self):
        """User in Manager group should have can_manage_jobs via group."""
        user = User.objects.get(username='johnq')
        user.groups.clear()
        manager_group = Group.objects.get(name='Manager')
        user.groups.add(manager_group)
        user = User.objects.get(pk=user.pk)  # clear cache
        self.assertTrue(user.has_perm('core.can_manage_jobs'))
        self.assertFalse(user.has_perm('core.can_manage_invoicing'))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_permissions.DefaultGroupsTest -v2`
Expected: FAIL — groups don't exist or have no permissions

- [ ] **Step 3: Write the data migration**

Run: `python manage.py makemigrations core --empty -n create_default_groups`

Then edit the generated migration file:

```python
from django.db import migrations


def create_default_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    # Get the content type for our User model
    ct = ContentType.objects.get(app_label='core', model='user')

    def get_perms(*codenames):
        return Permission.objects.filter(codename__in=codenames, content_type=ct)

    groups_config = {
        'Worker': ['can_view_jobs'],
        'Manager': ['can_view_jobs', 'can_manage_jobs', 'can_manage_time', 'can_approve_expenses'],
        'Bookkeeper': ['can_view_jobs', 'can_manage_invoicing', 'can_manage_purchasing', 'can_approve_expenses'],
        'Admin': [
            'can_manage_jobs', 'can_view_jobs', 'can_manage_invoicing',
            'can_manage_purchasing', 'can_manage_time',
            'can_approve_expenses', 'can_manage_config',
        ],
    }

    for group_name, perm_codenames in groups_config.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        group.permissions.set(get_perms(*perm_codenames))


def remove_default_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name__in=['Worker', 'Manager', 'Bookkeeper', 'Admin']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', 'PREVIOUS_MIGRATION'),  # Update to actual previous migration name
    ]

    operations = [
        migrations.RunPython(create_default_groups, remove_default_groups),
    ]
```

- [ ] **Step 4: Update test fixture**

Update `fixtures/unit_test_data.json`:
- Rename existing groups: "Administrator" → "Admin", "Employee" → "Worker"
- Add "Bookkeeper" group
- Add permission entries for each group matching the design doc
- Update user group assignments to use new group names

**Important:** The fixture groups must match the migration group names. Users in fixtures:
- `admin` (superuser) → Admin group
- `manager1` → Manager group
- `johnq` → Worker group

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_permissions.DefaultGroupsTest -v2`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/core/migrations/ fixtures/unit_test_data.json tests/test_permissions.py
git commit -m "feat: create default permission groups via data migration"
```

---

## Task 4: Wire Permissions into API Viewsets

**Files:**
- Modify: `apps/api/jobs/views.py`
- Modify: `apps/api/contacts/views.py`
- Modify: `apps/api/estimates/views.py`
- Modify: `apps/api/worksheets/views.py`
- Modify: `apps/api/work_orders/views.py`
- Modify: `apps/api/invoicing/views.py`
- Modify: `apps/api/purchasing/views.py`
- Modify: `apps/api/inventory/views.py`
- Modify: `apps/api/templates_config/views.py`
- Modify: `apps/api/email/views.py`
- Modify: `apps/api/search/views.py`
- Test: `tests/test_api_permissions.py`

### Permission Mapping

| Viewset / View | Read actions | Write actions |
|---|---|---|
| JobViewSet | `CanViewJobs` | `CanManageJobs` |
| ContactViewSet, BusinessViewSet, PaymentTermsViewSet | `IsAuthenticated` | `CanManageJobs` |
| EstimateViewSet | `CanViewJobs` | `CanManageJobs` |
| EstWorksheetViewSet | `CanViewJobs` | `CanManageJobs` |
| WorkOrderViewSet | `CanViewJobs` | `CanManageJobs` |
| InvoiceViewSet | `CanViewJobs` | `CanManageInvoicing` |
| PurchaseOrderViewSet, BillViewSet | `CanViewJobs` | `CanManagePurchasing` |
| PriceListItemViewSet | `IsAuthenticated` | `CanManageInvoicing` |
| WorkOrderTemplateViewSet, TaskTemplateViewSet, LineItemTypeViewSet | `IsAuthenticated` | `CanManageConfig` |
| settings_view (FBV) | `CanManageConfig` | `CanManageConfig` |
| email views (FBVs) | `IsAuthenticated` | `CanManageJobs` |
| search_view (FBV) | `IsAuthenticated` | N/A |

- [ ] **Step 1: Write failing tests for API permission enforcement**

Create `tests/test_api_permissions.py`:

```python
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient
from tests.base import BaseTestCase

User = get_user_model()


class APIPermissionTestBase(BaseTestCase):
    """Base class for API permission tests."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

        # Worker: can_view_jobs only
        self.worker = User.objects.get(username='johnq')
        self.worker.set_password('testpass')
        self.worker.save()

        # Manager: can_view_jobs, can_manage_jobs, can_manage_time, can_approve_expenses
        self.manager = User.objects.get(username='manager1')
        self.manager.set_password('testpass')
        self.manager.save()

        # Superuser: everything
        self.admin = User.objects.get(username='admin')
        self.admin.set_password('testpass')
        self.admin.save()


class JobViewSetPermissionTest(APIPermissionTestBase):
    """Test permission enforcement on JobViewSet."""

    def test_worker_can_list_jobs(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/jobs/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_create_job(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post('/api/jobs/', {'customer': 1})
        self.assertEqual(response.status_code, 403)

    def test_manager_can_create_job(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.post('/api/jobs/', {'customer': 1})
        # Should not be 403 (may be 400 for missing fields, that's fine)
        self.assertNotEqual(response.status_code, 403)

    def test_unauthenticated_denied(self):
        response = self.client.get('/api/jobs/')
        self.assertIn(response.status_code, [401, 403])


class InvoiceViewSetPermissionTest(APIPermissionTestBase):
    """Test permission enforcement on InvoiceViewSet."""

    def test_worker_can_view_invoices(self):
        """Worker has can_view_jobs, should be able to list invoices."""
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/invoices/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_create_invoice(self):
        """Worker lacks can_manage_invoicing, should be denied."""
        self.client.force_authenticate(user=self.worker)
        response = self.client.post('/api/invoices/', {})
        self.assertEqual(response.status_code, 403)


class PurchaseOrderPermissionTest(APIPermissionTestBase):
    """Test permission enforcement on PurchaseOrderViewSet."""

    def test_worker_cannot_create_po(self):
        """Worker lacks can_manage_purchasing, should be denied."""
        self.client.force_authenticate(user=self.worker)
        response = self.client.post('/api/purchase-orders/', {})
        self.assertEqual(response.status_code, 403)


class SettingsPermissionTest(APIPermissionTestBase):
    """Test permission enforcement on settings view."""

    def test_worker_cannot_access_settings(self):
        """Worker lacks can_manage_config, should be denied."""
        self.client.force_authenticate(user=self.worker)
        response = self.client.get('/api/settings/')
        self.assertEqual(response.status_code, 403)

    def test_admin_can_access_settings(self):
        """Admin superuser can access settings."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/settings/')
        self.assertEqual(response.status_code, 200)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_api_permissions -v2`
Expected: FAIL — worker can create jobs, access settings, etc.

- [ ] **Step 3: Add `get_permissions()` to viewsets**

The pattern for each viewset is the same. Example for `apps/api/jobs/views.py`:

```python
from rest_framework.permissions import IsAuthenticated
from apps.api.permissions import CanManageJobs, CanViewJobs

class JobViewSet(...):
    # ... existing code ...

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated(), CanViewJobs()]
        return [IsAuthenticated(), CanManageJobs()]
```

**Note:** Always include `IsAuthenticated()` first — `has_perm()` returns `False` for anonymous users but won't return the right HTTP status code (401 vs 403) without it.

Apply the same pattern to each viewset per the permission mapping table above.

For function-based views, update the decorator. Example for `apps/api/templates_config/views.py`:

```python
from apps.api.permissions import CanManageConfig

@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated, CanManageConfig])
def settings_view(request):
    ...
```

For email FBVs that do write operations (like `link_to_job`, `create_job_from_email`), use `CanManageJobs`. Read-only email views stay `IsAuthenticated`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_api_permissions -v2`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `python manage.py test -v2`
Expected: All existing tests still pass. Some may fail if test users lack required permissions — fix by ensuring test setUp assigns appropriate groups/permissions.

- [ ] **Step 6: Fix any test regressions**

Existing API tests use `force_authenticate()` with users from fixtures. If those users lack the required permissions, tests will start getting 403s. Fix by:
- Using the `admin` superuser in tests that need write access
- Or assigning the appropriate group to the test user in setUp

- [ ] **Step 7: Commit**

```bash
git add apps/api/ tests/test_api_permissions.py tests/
git commit -m "feat: wire permission classes into API viewsets"
```

---

## Task 5: Add Login and Permission Checks to HTML Views

**Files:**
- Modify: `apps/jobs/views.py`
- Modify: `apps/contacts/views.py`
- Modify: `apps/core/views.py`
- Modify: `apps/invoicing/views.py`
- Modify: `apps/purchasing/views.py`
- Modify: `minibini/settings.py` (add LOGIN_URL)
- Test: `tests/test_permissions.py` (append)

### HTML Permission Mapping

| App | View functions | Permission |
|---|---|---|
| `apps/jobs/views.py` | all views | `core.can_manage_jobs` (write), `core.can_view_jobs` (read) |
| `apps/contacts/views.py` | all views | `core.can_manage_jobs` (contacts are part of job management) |
| `apps/core/views.py` | email views | `core.can_manage_jobs` |
| `apps/core/views.py` | settings, line_item_type, user views | `core.can_manage_config` |
| `apps/invoicing/views.py` | all views | `core.can_manage_invoicing` |
| `apps/purchasing/views.py` | all views | `core.can_manage_purchasing` |

- [ ] **Step 1: Write failing tests for HTML view permissions**

Append to `tests/test_permissions.py`:

```python
from django.test import Client


class HTMLViewPermissionTest(BaseTestCase):
    """Test that HTML views require login and correct permissions."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.worker = User.objects.get(username='johnq')
        self.worker.set_password('testpass')
        self.worker.save()
        self.manager = User.objects.get(username='manager1')
        self.manager.set_password('testpass')
        self.manager.save()

    def test_unauthenticated_redirects_to_login(self):
        """Unauthenticated user is redirected from job list."""
        response = self.client.get('/jobs/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_worker_can_view_job_list(self):
        """Worker with can_view_jobs can see job list."""
        self.client.login(username='johnq', password='testpass')
        response = self.client.get('/jobs/')
        self.assertEqual(response.status_code, 200)

    def test_worker_cannot_access_settings(self):
        """Worker without can_manage_config gets 403 on settings."""
        self.client.login(username='johnq', password='testpass')
        response = self.client.get('/settings/')
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_permissions.HTMLViewPermissionTest -v2`
Expected: FAIL — no redirects, no 403s

- [ ] **Step 3: Add LOGIN_URL to settings**

In `minibini/settings.py`, add:

```python
LOGIN_URL = '/api/auth/login/'  # Update when login page exists
```

**Note:** This URL is a placeholder. The frontend handles login via the SPA — the `LOGIN_URL` is primarily for Django's `@login_required` redirect behavior. Update this when a proper login page/route exists.

- [ ] **Step 4: Add decorators to HTML views**

Apply `@login_required` and `@permission_required` to each view function. The pattern:

```python
from django.contrib.auth.decorators import login_required, permission_required

@login_required
@permission_required('core.can_manage_jobs', raise_exception=True)
def job_create(request):
    ...

@login_required
@permission_required('core.can_view_jobs', raise_exception=True)
def job_list(request):
    ...
```

**Important:** Always pass `raise_exception=True` so Django returns 403 instead of redirecting to login (the user IS logged in, they just lack the permission).

Apply to all HTML view functions per the mapping table above.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_permissions.HTMLViewPermissionTest -v2`
Expected: PASS

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `python manage.py test -v2`
Expected: All tests pass. Fix any regressions — existing HTML view tests may need `client.login()` calls added since views now require authentication.

- [ ] **Step 7: Commit**

```bash
git add apps/jobs/views.py apps/contacts/views.py apps/core/views.py apps/invoicing/views.py apps/purchasing/views.py minibini/settings.py tests/test_permissions.py
git commit -m "feat: add login and permission checks to HTML views"
```

---

## Task 6: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md Development Features and Code Conventions**

Add to the Code Conventions section:

```markdown
**Permissions:** Always check permissions in views:
- API viewsets: override `get_permissions()` returning `[IsAuthenticated(), CanXxx()]`
- API function views: `@permission_classes([IsAuthenticated, CanXxx])`
- HTML views: `@login_required` + `@permission_required('core.can_xxx', raise_exception=True)`
```

Add the permission atoms to the Core models section documentation.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add permissions guidance to CLAUDE.md"
```

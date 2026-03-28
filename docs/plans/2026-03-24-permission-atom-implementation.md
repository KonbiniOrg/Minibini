# Permission Atom Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize permission atoms per the redesign spec — drop 3 old atoms, add 2 new ones, update all viewsets, fixtures, and tests.

**Architecture:** Update the User model's Meta.permissions, create a migration for the schema change plus a data migration to clean up old groups, update the DRF permission classes, then update every viewset's `get_permissions()` to match the new endpoint-to-atom map. Finally update fixtures (remove groups, since groups move to test setUp) and existing tests.

**Tech Stack:** Django 5.2, Django REST Framework, Python 3.12

**Spec:** `docs/plans/2026-03-24-permission-atom-redesign.md`
**Test plan (executed after this):** `docs/plans/2026-03-24-permission-atom-tests.md`

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `apps/core/models.py` | Modify | Update `User.Meta.permissions` — remove 3 atoms, add 2 |
| `apps/core/migrations/0006_*.py` | Create (via makemigrations) | Schema migration for new permission atoms |
| `apps/core/migrations/0007_cleanup_old_groups.py` | Create (manual) | Data migration: delete old groups created by 0005 |
| `apps/api/permissions.py` | Modify | Remove 3 old classes, add 2 new classes |
| `apps/api/jobs/views.py` | Modify | JobViewSet: read `CanViewJobs` → `IsAuthenticated`, notes → `IsAuthenticated` |
| `apps/api/estimates/views.py` | Modify | EstimateViewSet: read `CanViewJobs` → `IsAuthenticated` |
| `apps/api/worksheets/views.py` | Modify | EstWorksheetViewSet: read `CanViewJobs` → `IsAuthenticated` |
| `apps/api/work_orders/views.py` | Modify | WorkOrderViewSet: read `CanViewJobs` → `IsAuthenticated`, tasks POST → `IsAuthenticated` |
| `apps/api/contacts/views.py` | Modify | ContactViewSet/BusinessViewSet: notes → `IsAuthenticated` |
| `apps/api/invoicing/views.py` | Modify | InvoiceViewSet: read `CanViewJobs` → `CanViewFinancials`, write `CanManageInvoicing` → `CanManageFinancials` |
| `apps/api/purchasing/views.py` | Modify | PO/Bill: read `CanViewJobs` → `CanViewFinancials`, write `CanManagePurchasing` → `CanManageFinancials` |
| `apps/api/inventory/views.py` | Modify | PriceListItem: write `CanManageInvoicing` → `CanManageFinancials` |
| `apps/api/email/views.py` | Modify | email_list/email_detail: `IsAuthenticated` → `CanManageJobs` |
| `apps/jobs/views.py` | Modify | Remove `@permission_required('core.can_view_jobs')` decorators |
| `apps/invoicing/views.py` | Modify | Replace `can_manage_invoicing` → `can_manage_financials` in decorators |
| `apps/purchasing/views.py` | Modify | Replace `can_manage_purchasing` → `can_manage_financials` in decorators |
| `apps/core/views.py` | Modify | Check for any removed atom references in decorators |
| `fixtures/unit_test_data.json` | Modify | Remove group entries (pk 1-4), remove group refs from users |
| `fixtures/core_base_data.json` | Modify | Same as above |
| `tests/test_permissions.py` | Modify | Update atom list, factory tests, group tests |
| `tests/test_api_permissions.py` | Keep for now | Deleted later per test plan |
| `CLAUDE.md` | Modify | Update atoms, groups, permission guidance |

---

## Task 1: Update User.Meta.permissions and generate migration

**Files:**
- Modify: `apps/core/models.py:23-31`

- [ ] **Step 1: Update the permissions list**

Replace the current 7-atom list with the new 6-atom list:

```python
        permissions = [
            ('can_view_financials', 'Read-only access to invoices, POs, bills'),
            ('can_manage_jobs', 'Can manage jobs, estimates, worksheets, work orders, tasks, contacts'),
            ('can_manage_financials', 'Can manage invoices, POs, bills, price list'),
            ('can_manage_time', "Can edit/delete anyone's time entries"),
            ('can_approve_expenses', 'Can approve/reject expenses over threshold'),
            ('can_manage_config', 'Can manage settings, templates, user admin'),
        ]
```

- [ ] **Step 2: Generate the migration**

Run: `python manage.py makemigrations core`
Expected: Creates a migration that alters `User.Meta.permissions`.

- [ ] **Step 3: Commit**

```bash
git add apps/core/models.py apps/core/migrations/0006_*.py
git commit -m "feat: update permission atoms — drop 3, add 2 new"
```

---

## Task 2: Data migration to clean up old groups and stale permission refs

**Files:**
- Create: `apps/core/migrations/0007_cleanup_old_groups.py`

- [ ] **Step 1: Create the data migration**

```python
from django.db import migrations


OLD_GROUPS = ['Worker', 'Manager', 'Bookkeeper', 'Admin']
OLD_ATOMS = ['can_view_jobs', 'can_manage_invoicing', 'can_manage_purchasing']


def cleanup_old_data(apps, schema_editor):
    """Delete groups created by migration 0005 and remove stale
    user-permission M2M entries for the 3 dropped atoms.
    Groups are now managed via fixtures/test setUp, not migrations.
    """
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')

    # Delete old groups (cascades group-permission M2M)
    Group.objects.filter(name__in=OLD_GROUPS).delete()

    # Remove stale user_permissions entries for dropped atoms
    old_perms = Permission.objects.filter(codename__in=OLD_ATOMS)
    if old_perms.exists():
        User = apps.get_model('core', 'User')
        for user in User.objects.filter(user_permissions__in=old_perms).distinct():
            user.user_permissions.remove(*old_perms)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_alter_user_options'),  # adjust name to match generated migration
    ]

    operations = [
        migrations.RunPython(cleanup_old_data, noop),
    ]
```

**Note:** The `dependencies` must reference the actual name of the migration created in Task 1. Check `apps/core/migrations/` for the exact filename and adjust accordingly.

- [ ] **Step 2: Verify the migration file is syntactically valid**

Run: `python manage.py showmigrations core`
Expected: Shows all core migrations including 0007 as unapplied. No errors.

- [ ] **Step 3: Commit**

```bash
git add apps/core/migrations/0007_cleanup_old_groups.py
git commit -m "feat: data migration to remove old groups from migration 0005"
```

---

## Task 3: Update DRF permission classes (with transition aliases)

**Files:**
- Modify: `apps/api/permissions.py`

Add the new classes and keep the old names as temporary aliases so viewsets that haven't been updated yet don't break. The aliases will be removed in Task 12 after all viewsets are updated.

- [ ] **Step 1: Update the file**

Replace the entire file contents with:

```python
from rest_framework.permissions import BasePermission


def atom_permission(perm_codename):
    """Create a DRF permission class for a given permission atom."""
    class AtomPermission(BasePermission):
        def has_permission(self, request, view):
            return request.user.has_perm(f'core.{perm_codename}')
    AtomPermission.__name__ = perm_codename
    return AtomPermission


# Current atoms
CanViewFinancials = atom_permission('can_view_financials')
CanManageJobs = atom_permission('can_manage_jobs')
CanManageFinancials = atom_permission('can_manage_financials')
CanManageTime = atom_permission('can_manage_time')
CanApproveExpenses = atom_permission('can_approve_expenses')
CanManageConfig = atom_permission('can_manage_config')

# Temporary aliases — viewsets still import these until updated in Tasks 4-11.
# Remove after all viewsets are migrated (Task 12).
CanViewJobs = atom_permission('can_view_financials')  # approximate — read-gating is removed
CanManageInvoicing = CanManageFinancials
CanManagePurchasing = CanManageFinancials
```

- [ ] **Step 2: Verify the app loads**

Run: `python manage.py test tests.test_api_auth -v2`
Expected: PASS — the aliases keep all imports working.

- [ ] **Step 3: Commit**

```bash
git add apps/api/permissions.py
git commit -m "feat: add new permission classes with transition aliases"
```

---

## Task 4: Update JobViewSet permissions

**Files:**
- Modify: `apps/api/jobs/views.py:1-23`

The current `get_permissions()` uses `CanViewJobs` for reads and `CanManageJobs` for all writes. Changes needed:
- Read actions → `IsAuthenticated` only (drop `CanViewJobs`)
- `notes` action → `IsAuthenticated` only (any user can add notes)
- All other writes → `CanManageJobs` (unchanged)

- [ ] **Step 1: Update the import line**

Remove `CanViewJobs` from the import. The import should be:

```python
from apps.api.permissions import CanManageJobs
```

- [ ] **Step 2: Update `get_permissions()`**

```python
    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'history', 'notes'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobs()]
```

- [ ] **Step 3: Run existing tests to check for import errors**

Run: `python manage.py test tests.test_api_auth -v2`
Expected: PASS (this just verifies the app loads without import errors).

- [ ] **Step 4: Commit**

```bash
git add apps/api/jobs/views.py
git commit -m "feat: JobViewSet — read+notes to IsAuthenticated, drop CanViewJobs"
```

---

## Task 5: Update ContactViewSet and BusinessViewSet permissions

**Files:**
- Modify: `apps/api/contacts/views.py`

ContactViewSet (line 22-25): `notes` action needs to move to `IsAuthenticated`. Currently all writes use `CanManageJobs`.
BusinessViewSet (line 116-119): same — `notes` action to `IsAuthenticated`.

- [ ] **Step 1: Update ContactViewSet.get_permissions()**

```python
    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'history', 'notes'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobs()]
```

- [ ] **Step 2: Update BusinessViewSet.get_permissions()**

```python
    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'history', 'notes'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobs()]
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/contacts/views.py
git commit -m "feat: Contact/BusinessViewSet — notes action to IsAuthenticated"
```

---

## Task 6: Update EstimateViewSet and EstWorksheetViewSet permissions

**Files:**
- Modify: `apps/api/estimates/views.py:1-22`
- Modify: `apps/api/worksheets/views.py:1-25`

Both currently use `CanViewJobs` for reads. Change to `IsAuthenticated` only.

- [ ] **Step 1: Update EstimateViewSet**

Update the import to remove `CanViewJobs`:
```python
from apps.api.permissions import CanManageJobs
```

Update `get_permissions()`:
```python
    def get_permissions(self):
        read_actions = ('list', 'retrieve')
        mixed_actions = ('line_items',)
        if self.action in read_actions:
            return [IsAuthenticated()]
        if self.action in mixed_actions and self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobs()]
```

- [ ] **Step 2: Update EstWorksheetViewSet**

Update the import to remove `CanViewJobs`:
```python
from apps.api.permissions import CanManageJobs
```

Update `get_permissions()`:
```python
    def get_permissions(self):
        read_actions = ('list', 'retrieve')
        mixed_actions = ('tasks', 'bundles')
        if self.action in read_actions:
            return [IsAuthenticated()]
        if self.action in mixed_actions and self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobs()]
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/estimates/views.py apps/api/worksheets/views.py
git commit -m "feat: Estimate/WorksheetViewSet — read to IsAuthenticated, drop CanViewJobs"
```

---

## Task 7: Update WorkOrderViewSet permissions

**Files:**
- Modify: `apps/api/work_orders/views.py:1-23`

Changes:
- Read actions → `IsAuthenticated` (drop `CanViewJobs`)
- `tasks` action: GET → `IsAuthenticated`, **POST → `IsAuthenticated`** (any user can add tasks to work orders), PATCH/DELETE → `CanManageJobs`
- `bundles` action: GET → `IsAuthenticated`, POST/PATCH/DELETE → `CanManageJobs`
- All other writes → `CanManageJobs`

- [ ] **Step 1: Update the import**

Remove `CanViewJobs`:
```python
from apps.api.permissions import CanManageJobs
```

- [ ] **Step 2: Update `get_permissions()`**

```python
    def get_permissions(self):
        read_actions = ('list', 'retrieve', 'task_bleps')
        mixed_read_actions = ('bundles',)
        if self.action in read_actions:
            return [IsAuthenticated()]
        if self.action == 'tasks':
            # GET and POST are open to any authenticated user;
            # PATCH and DELETE on individual tasks require can_manage_jobs
            if self.request.method in ('GET', 'POST'):
                return [IsAuthenticated()]
            return [IsAuthenticated(), CanManageJobs()]
        if self.action in mixed_read_actions and self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageJobs()]
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/work_orders/views.py
git commit -m "feat: WorkOrderViewSet — read+task-add to IsAuthenticated, drop CanViewJobs"
```

---

## Task 8: Update InvoiceViewSet permissions

**Files:**
- Modify: `apps/api/invoicing/views.py:1-21`

Changes:
- Read → `CanViewFinancials` (was `CanViewJobs`)
- Write → `CanManageFinancials` (was `CanManageInvoicing`)

- [ ] **Step 1: Update imports**

```python
from apps.api.permissions import CanViewFinancials, CanManageFinancials
```

Remove any import of `CanViewJobs` or `CanManageInvoicing`.

- [ ] **Step 2: Update `get_permissions()`**

```python
    def get_permissions(self):
        read_actions = ('list', 'retrieve')
        mixed_actions = ('line_items',)
        if self.action in read_actions:
            return [IsAuthenticated(), CanViewFinancials()]
        if self.action in mixed_actions and self.request.method == 'GET':
            return [IsAuthenticated(), CanViewFinancials()]
        return [IsAuthenticated(), CanManageFinancials()]
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/invoicing/views.py
git commit -m "feat: InvoiceViewSet — CanViewFinancials/CanManageFinancials"
```

---

## Task 9: Update PurchaseOrderViewSet and BillViewSet permissions

**Files:**
- Modify: `apps/api/purchasing/views.py`

Changes (both viewsets):
- Read → `CanViewFinancials` (was `CanViewJobs`)
- Write → `CanManageFinancials` (was `CanManagePurchasing`)

- [ ] **Step 1: Update imports**

```python
from apps.api.permissions import CanViewFinancials, CanManageFinancials
```

Remove any import of `CanViewJobs` or `CanManagePurchasing`.

- [ ] **Step 2: Update PurchaseOrderViewSet.get_permissions()**

```python
    def get_permissions(self):
        read_actions = ('list', 'retrieve')
        mixed_actions = ('line_items',)
        if self.action in read_actions:
            return [IsAuthenticated(), CanViewFinancials()]
        if self.action in mixed_actions and self.request.method == 'GET':
            return [IsAuthenticated(), CanViewFinancials()]
        return [IsAuthenticated(), CanManageFinancials()]
```

- [ ] **Step 3: Update BillViewSet.get_permissions()**

Same pattern as PurchaseOrderViewSet above.

- [ ] **Step 4: Commit**

```bash
git add apps/api/purchasing/views.py
git commit -m "feat: PO/BillViewSet — CanViewFinancials/CanManageFinancials"
```

---

## Task 10: Update PriceListItemViewSet permissions

**Files:**
- Modify: `apps/api/inventory/views.py:1-17`

Changes:
- Read → `IsAuthenticated` (unchanged)
- Write → `CanManageFinancials` (was `CanManageInvoicing`)

- [ ] **Step 1: Update import**

```python
from apps.api.permissions import CanManageFinancials
```

- [ ] **Step 2: Update `get_permissions()`**

```python
    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), CanManageFinancials()]
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/inventory/views.py
git commit -m "feat: PriceListItemViewSet — write to CanManageFinancials"
```

---

## Task 11: Update email view permissions

**Files:**
- Modify: `apps/api/email/views.py:11-23`

Changes:
- `email_list` and `email_detail` → `[IsAuthenticated, CanManageJobs]` (was `[IsAuthenticated]`)

- [ ] **Step 1: Update email_list decorator**

```python
@api_view(['GET'])
@permission_classes([IsAuthenticated, CanManageJobs])
def email_list(request):
```

- [ ] **Step 2: Update email_detail decorator**

```python
@api_view(['GET'])
@permission_classes([IsAuthenticated, CanManageJobs])
def email_detail(request, pk):
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/email/views.py
git commit -m "feat: email list/detail now require can_manage_jobs"
```

---

## Task 12: Remove transition aliases and verify no stale imports

**Files:**
- Modify: `apps/api/permissions.py`

- [ ] **Step 1: Remove the temporary aliases from `apps/api/permissions.py`**

Delete these lines from the bottom of the file:

```python
# Temporary aliases — viewsets still import these until updated in Tasks 4-11.
# Remove after all viewsets are migrated (Task 12).
CanViewJobs = atom_permission('can_view_financials')  # approximate — read-gating is removed
CanManageInvoicing = CanManageFinancials
CanManagePurchasing = CanManageFinancials
```

- [ ] **Step 2: Search for removed permission class names in `apps/`**

Run: `grep -rn 'CanViewJobs\|CanManageInvoicing\|CanManagePurchasing' apps/`

Expected: Zero hits in `apps/` (all viewsets updated in Tasks 4-11). If any remain, fix them.

- [ ] **Step 3: Search for old atom codenames in permission checks**

Run: `grep -rn "can_view_jobs\|can_manage_invoicing\|can_manage_purchasing" apps/ --include='*.py' | grep -v migrations/`

Expected: Zero hits. Hits in `migrations/` are historical and fine.

- [ ] **Step 4: Verify the app loads cleanly**

Run: `python manage.py test tests.test_api_auth -v2`
Expected: PASS — no import errors anywhere.

- [ ] **Step 5: Commit**

```bash
git add apps/api/permissions.py
git commit -m "feat: remove transition aliases from permissions.py"
```

---

## Task 13: Update HTML view decorators for removed atoms

**Files:**
- Modify: `apps/jobs/views.py`
- Modify: `apps/invoicing/views.py`
- Modify: `apps/purchasing/views.py`
- Modify: `apps/core/views.py`

HTML views are legacy and will be replaced by the Svelte SPA, but the decorators must reference atoms that exist. All `@permission_required('core.can_view_jobs', ...)` decorators need to be removed (replaced with just `@login_required`) since `can_view_jobs` no longer exists and read access is now `IsAuthenticated`.

- [ ] **Step 1: Find all HTML view references to removed atoms**

Run: `grep -rn "can_view_jobs\|can_manage_invoicing\|can_manage_purchasing" apps/ --include='*.py' | grep -v migrations/ | grep -v api/`

This shows only non-API, non-migration Python files — the HTML views.

- [ ] **Step 2: Replace `can_view_jobs` decorators**

In every file found, remove `@permission_required('core.can_view_jobs', raise_exception=True)` lines. The `@login_required` decorator above it is sufficient (matches the new `IsAuthenticated` policy for reads).

- [ ] **Step 3: Replace `can_manage_invoicing` decorators**

Replace `@permission_required('core.can_manage_invoicing', raise_exception=True)` with `@permission_required('core.can_manage_financials', raise_exception=True)`.

- [ ] **Step 4: Replace `can_manage_purchasing` decorators**

Replace `@permission_required('core.can_manage_purchasing', raise_exception=True)` with `@permission_required('core.can_manage_financials', raise_exception=True)`.

- [ ] **Step 5: Verify no stale references remain**

Run: `grep -rn "can_view_jobs\|can_manage_invoicing\|can_manage_purchasing" apps/ --include='*.py' | grep -v migrations/`

Expected: Zero hits.

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/views.py apps/invoicing/views.py apps/purchasing/views.py apps/core/views.py
git commit -m "fix: update HTML view decorators for removed permission atoms"
```

---

## Task 14: Update fixtures

**Files:**
- Modify: `fixtures/unit_test_data.json`
- Modify: `fixtures/core_base_data.json`

Remove group definitions from both fixtures. Remove group references from user entries. Groups are now created in test setUp methods, not fixtures.

- [ ] **Step 1: Remove group entries from `fixtures/unit_test_data.json`**

Delete all `auth.group` entries (pk 1-4). Update user entries to remove `"groups": [N]` — set to `"groups": []`.

- [ ] **Step 2: Remove group entries from `fixtures/core_base_data.json`**

Same changes as Step 1.

- [ ] **Step 3: Verify fixtures load**

Run: `python manage.py loaddata unit_test_data.json --verbosity=2`
Expected: Loads without errors. (This only checks the fixture is valid JSON that matches the schema — it does not write to the dev database because we use a test runner.)

Actually, verify by running a simple test:

Run: `python manage.py test tests.test_api_auth -v2`
Expected: PASS — fixtures load and auth tests still work (they don't depend on groups).

- [ ] **Step 4: Commit**

```bash
git add fixtures/unit_test_data.json fixtures/core_base_data.json
git commit -m "feat: remove group definitions from main fixtures"
```

---

## Task 15: Update test_permissions.py

**Files:**
- Modify: `tests/test_permissions.py`

This file has 4 test classes that need updating:
1. `PermissionAtomsTest` — update atom list (6 not 7)
2. `AtomPermissionFactoryTest` — update imports and class references
3. `DefaultGroupsTest` — remove entirely (groups are no longer in migrations)
4. `HTMLViewPermissionTest` — update setUp to use direct permission assignment instead of fixture groups

- [ ] **Step 1: Update PermissionAtomsTest**

```python
class PermissionAtomsTest(BaseTestCase):
    """Verify custom permission atoms exist after migration."""

    EXPECTED_ATOMS = [
        'can_view_financials',
        'can_manage_jobs',
        'can_manage_financials',
        'can_manage_time',
        'can_approve_expenses',
        'can_manage_config',
    ]

    def test_all_permission_atoms_exist(self):
        """All 6 permission atoms should exist in auth_permission table."""
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
        user = User.objects.create_user(username='testuser', password='testpass')
        perm = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
        user.user_permissions.add(perm)
        user = User.objects.get(pk=user.pk)
        self.assertTrue(user.has_perm('core.can_manage_jobs'))
        self.assertFalse(user.has_perm('core.can_manage_financials'))
```

Note: `test_user_can_be_assigned_permission` previously used fixture user `johnq` who was in the Worker group. Since groups are removed from fixtures, create a fresh user instead.

- [ ] **Step 2: Update AtomPermissionFactoryTest**

Update the imports and class references:

```python
from apps.api.permissions import (
    atom_permission, CanManageJobs, CanViewFinancials,
    CanManageFinancials, CanManageTime, CanApproveExpenses, CanManageConfig,
)
```

Update `test_permission_denied_without_perm` and `test_permission_granted_with_direct_perm` to use a freshly created user instead of fixture user `johnq`:

```python
    def test_permission_denied_without_perm(self):
        user = User.objects.create_user(username='testuser', password='testpass')
        request = self._make_request(user)
        perm = CanManageJobs()
        self.assertFalse(perm.has_permission(request, None))

    def test_permission_granted_with_direct_perm(self):
        user = User.objects.create_user(username='testuser', password='testpass')
        perm_obj = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
        user.user_permissions.add(perm_obj)
        user = User.objects.get(pk=user.pk)
        request = self._make_request(user)
        perm = CanManageJobs()
        self.assertTrue(perm.has_permission(request, None))
```

Update `test_superuser_has_all_permissions`:

```python
    def test_superuser_has_all_permissions(self):
        user = User.objects.create_superuser(username='supertest', password='testpass')
        request = self._make_request(user)
        self.assertTrue(CanManageJobs().has_permission(request, None))
        self.assertTrue(CanManageFinancials().has_permission(request, None))
        self.assertTrue(CanManageConfig().has_permission(request, None))
```

Update `test_all_constants_are_defined`:

```python
    def test_all_constants_are_defined(self):
        """All 6 permission class constants are importable and functional."""
        classes = [
            CanManageJobs, CanViewFinancials, CanManageFinancials,
            CanManageTime, CanApproveExpenses, CanManageConfig,
        ]
        self.assertEqual(len(classes), 6)
        for cls in classes:
            self.assertTrue(hasattr(cls, 'has_permission'))
```

- [ ] **Step 3: Remove DefaultGroupsTest class entirely**

Delete the `DefaultGroupsTest` class and its import of `Group`. Groups are data, not code — they are no longer tested here.

- [ ] **Step 4: Update HTMLViewPermissionTest**

This class creates users from fixtures and tests HTML view decorators. Since groups are removed from fixtures, the test users no longer have permissions via groups. Update the setUp to assign permissions directly:

```python
class HTMLViewPermissionTest(BaseTestCase):
    """Test that HTML views require login and correct permissions."""

    def setUp(self):
        super().setUp()
        self.client = Client()

        # Worker-equivalent: no atoms, just authenticated
        self.worker = User.objects.create_user(username='worker', password='testpass')

        # Manager-equivalent: can_manage_jobs
        self.manager = User.objects.create_user(username='manager', password='testpass')
        perm = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
        self.manager.user_permissions.add(perm)
        self.manager = User.objects.get(pk=self.manager.pk)  # clear cache
```

Update tests that use `self.worker` and `self.manager` — the login calls change to use the new usernames and password `'testpass'`. Review each test method and update accordingly. The test logic stays the same, just the user references change.

- [ ] **Step 5: Run tests**

Run: `python manage.py test tests.test_permissions -v2`
Expected: All tests pass. HTML view decorators were already updated in Task 13.

- [ ] **Step 6: Commit**

```bash
git add tests/test_permissions.py
git commit -m "test: update test_permissions.py for new atom names and no fixture groups"
```

---

## Task 16: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the User model description**

In the "Key Models > Core" section, update the User description to say "Has 6 custom permission atoms" and reference the new atoms.

- [ ] **Step 2: Update the Permissions section**

Replace references to the old atoms with the new ones. Update the permission atoms list:
- `can_view_financials` — Read-only access to invoices, POs, bills
- `can_manage_jobs` — Full CRUD on jobs, estimates, worksheets, work orders, tasks, contacts; read+write emails
- `can_manage_financials` — Full CRUD on invoices, POs, bills, price list items
- `can_manage_time` — Edit/delete anyone's time entries
- `can_approve_expenses` — Approve/reject expenses over threshold
- `can_manage_config` — Settings, templates, line item types, user admin

Update the guidance about which permission to use in views:
- API viewsets: `[IsAuthenticated(), CanXxx()]`
- Mention that notes and WO task creation are `IsAuthenticated` only
- Mention that email viewing requires `CanManageJobs`

- [ ] **Step 3: Update the group table**

Replace the old 4-group table with the new 5-group table. Note that groups are defined in fixtures/test setUp, not migrations.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for permission atom redesign"
```

---

## Task 17: Final verification

- [ ] **Step 1: Run the full test suite**

Run: `python manage.py test -v2`

Expected: All tests pass. Some tests in `test_api_permissions.py` may fail because they reference old atoms via fixture groups — this is expected and will be resolved when the test plan (`2026-03-24-permission-atom-tests.md`) is executed next.

If `test_api_permissions.py` failures block the suite, temporarily skip them:

Run: `python manage.py test --exclude-tag=legacy_permissions -v2`

Or run everything except that file:

Run: `python manage.py test tests.test_permissions tests.test_api_auth -v2`

- [ ] **Step 2: Verify no stale references**

Run: `grep -rn 'CanViewJobs\|CanManageInvoicing\|CanManagePurchasing' apps/`
Expected: Zero hits.

Run: `grep -rn 'can_view_jobs\|can_manage_invoicing\|can_manage_purchasing' apps/ --include='*.py' | grep -v migrations/`
Expected: Zero hits.

- [ ] **Step 3: Commit any remaining fixes**

---

## Next Steps

After this plan is complete, execute the test plan at `docs/plans/2026-03-24-permission-atom-tests.md` which:
1. Creates `tests/test_atom_api_permissions.py` with exhaustive atom-level endpoint tests
2. Deletes the old `tests/test_api_permissions.py`

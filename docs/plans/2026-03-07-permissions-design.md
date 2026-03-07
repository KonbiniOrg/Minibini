# Permissions Design

**Date:** 2026-03-07
**Status:** Approved
**Scope:** App-wide — applies to both HTML views and API

---

## Overview

Permissions for Minibini using Django's built-in groups and permissions system. No custom role field on User — groups are convenient bundles of permission atoms. The owner can assign individual permissions to any user beyond their group defaults.

---

## Permission Atoms

Defined as custom permissions on the User model's `Meta`:

```python
class Meta:
    permissions = [
        ("can_manage_jobs", "Can manage jobs, estimates, worksheets, work orders, tasks"),
        ("can_view_jobs", "Read-only access to all jobs and related documents"),
        ("can_manage_invoicing", "Can manage invoices, price list, send/payment"),
        ("can_manage_purchasing", "Can manage POs, bills, send/receive"),
        ("can_manage_time", "Can edit/delete anyone's time entries"),
        ("can_approve_expenses", "Can approve/reject expenses over threshold"),
        ("can_manage_config", "Can manage settings, templates, user admin"),
    ]
```

After migration, these exist as rows in Django's `auth_permission` table. Assignable to groups or individual users via standard Django machinery.

### Coverage

| Permission | Covers |
|---|---|
| `can_manage_jobs` | Full CRUD on jobs, estimates, worksheets, work orders, tasks, bundles |
| `can_view_jobs` | Read-only access to all jobs and related documents |
| `can_manage_invoicing` | Invoices, price list, send/payment actions |
| `can_manage_purchasing` | POs, bills, send/receive actions |
| `can_manage_time` | Edit/delete anyone's time entries (shifts + bleps) |
| `can_approve_expenses` | Approve/reject expenses over threshold |
| `can_manage_config` | Settings, templates, line item types, user admin |

### Implicit (no permission needed)

All authenticated users can:
- Track their own time (clock in/out, start/stop bleps)
- Submit expenses
- View their own time entries

---

## DRF Permission Classes

A factory function creates DRF permission classes from atoms:

```python
# apps/api/permissions.py

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

`has_perm()` checks both direct user permissions and group permissions — a user in the "Manager" group automatically gets `can_manage_jobs` without it being assigned individually.

### Usage on Viewsets

```python
class JobViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [CanViewJobs()]
        return [CanManageJobs()]
```

### HTML Views

Same atoms, checked via Django's standard mechanisms:

```python
# In a view function
if not request.user.has_perm('core.can_manage_jobs'):
    raise PermissionDenied
```

Or via decorator:

```python
@permission_required('core.can_manage_jobs')
def estimate_create(request, job_id):
    ...
```

---

## Default Groups

Created via data fixture or migration:

| Group | Permissions |
|---|---|
| Worker | `can_view_jobs` |
| Manager | `can_view_jobs`, `can_manage_jobs`, `can_manage_time`, `can_approve_expenses` |
| Bookkeeper | `can_view_jobs`, `can_manage_invoicing`, `can_manage_purchasing`, `can_approve_expenses` |
| Admin | all atoms |

Groups are starter bundles, not rigid roles. A user can belong to multiple groups and/or have individual permissions added directly.

---

## Implementation Notes

- The `app_label` in `has_perm(f'core.{perm_codename}')` depends on which app the User model lives in. Currently `core`. Will need updating if User moves during app reorganization.
- The API uses `IsAuthenticated` only during initial implementation. Permission classes are wired in as a follow-up.
- Django's auto-generated per-model permissions (`add_`, `change_`, `delete_`, `view_`) still exist but are unused. The custom atoms are coarser by design.

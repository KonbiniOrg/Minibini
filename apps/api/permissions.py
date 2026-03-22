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

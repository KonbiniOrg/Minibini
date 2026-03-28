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

# Temporary aliases — viewsets still import these until updated.
# Remove after all viewsets are migrated.
CanViewJobs = atom_permission('can_view_financials')  # approximate — read-gating is removed
CanManageInvoicing = CanManageFinancials
CanManagePurchasing = CanManageFinancials

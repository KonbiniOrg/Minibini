from rest_framework.permissions import BasePermission, SAFE_METHODS


def atom_permission(perm_codename):
    """Create a DRF permission class for a given permission atom."""
    class AtomPermission(BasePermission):
        def has_permission(self, request, view):
            return request.user.has_perm(f'core.{perm_codename}')
    AtomPermission.__name__ = perm_codename
    return AtomPermission


# Current atoms
CanManageJobs = atom_permission('can_manage_jobs')
CanManageFinancials = atom_permission('can_manage_financials')
CanManageTime = atom_permission('can_manage_time')
CanManageConfig = atom_permission('can_manage_config')


class CanManageTimeOrFinancials(BasePermission):
    def has_permission(self, request, view):
        return (request.user.has_perm('core.can_manage_time')
                or request.user.has_perm('core.can_manage_financials'))


class CanManageFinancialsOrConfig(BasePermission):
    """Inventory items are owned by both the money role (financials) and the
    admin role (config) — either atom grants full CRUD + write-off/merge."""
    def has_permission(self, request, view):
        return (request.user.has_perm('core.can_manage_financials')
                or request.user.has_perm('core.can_manage_config'))


class CanManageJobsOrConfig(BasePermission):
    """The saved-work (ServiceItem) catalog is built by plan-builders (jobs) and
    config admins alike — either atom grants create. (The catalog is expected to
    leave the config-only area, like Inventory; this is the first step.)"""
    def has_permission(self, request, view):
        return (request.user.has_perm('core.can_manage_jobs')
                or request.user.has_perm('core.can_manage_config'))


class CanManageJobsOrFinancialsOrConfig(BasePermission):
    """The catalog (ServiceItems) is shared workshop vocabulary: plan-builders
    (jobs), the money role (financials), and config admins may all manage it."""
    def has_permission(self, request, view):
        return (request.user.has_perm('core.can_manage_jobs')
                or request.user.has_perm('core.can_manage_financials')
                or request.user.has_perm('core.can_manage_config'))


class CanManageJobOrPM(BasePermission):
    """can_manage_jobs atom OR being the target job's project_manager.

    Authoritative at the view level: for a non-atom user we resolve the
    request's target Job (looked-up instance, job-nested URL kwarg, or the
    create body's parent-Job field) and PM-check it. We do NOT rely on
    has_object_permission firing, because custom @actions don't all call
    get_object(); has_object_permission stays as defense-in-depth for the
    standard update/destroy path.
    """
    def has_permission(self, request, view):
        from apps.jobs.services import JobService
        if request.method in SAFE_METHODS:
            return True
        if request.user.has_perm('core.can_manage_jobs'):
            return True
        job = view.get_permission_target_job(request)
        return job is not None and JobService.user_can_manage(request.user, job)

    def has_object_permission(self, request, view, obj):
        from apps.jobs.services import JobService
        if request.user.has_perm('core.can_manage_jobs'):
            return True
        job = view.get_object_job(obj)
        return JobService.user_can_manage(request.user, job)


class CanManageJobsOrFinancials(BasePermission):
    """Purchasing acts that start a PO (create, order a material or stock, PO
    from email) belong to the money role and the plan-builders alike — NOT
    config: purchasing is not an admin act (PO order flow §6)."""
    def has_permission(self, request, view):
        return (request.user.has_perm('core.can_manage_jobs')
                or request.user.has_perm('core.can_manage_financials'))


class CanManageFinancialsOrJobOrPM(BasePermission):
    """The financials atom, else CanManageJobOrPM (jobs atom, or PM of the
    request's target job via view.get_permission_target_job). Gates ordering
    a material: its job's PM may buy for that job."""
    def has_permission(self, request, view):
        if request.user.has_perm('core.can_manage_financials'):
            return True
        return CanManageJobOrPM().has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        if request.user.has_perm('core.can_manage_financials'):
            return True
        return CanManageJobOrPM().has_object_permission(request, view, obj)


class CanManageFinancialsOrJobsOrLinkedPM(BasePermission):
    """PO-level writes (RM 2026-10-15): the financials atom, the jobs atom, or
    the project_manager of ANY job linked to a line on the PO the URL names
    (a Material whose po_line_item is on it, or a task-attributed line whose
    task is on the job). Resolved per request from view.get_permission_target_po
    — no stored flag, so the access lasts exactly as long as the link."""
    def has_permission(self, request, view):
        from apps.purchasing.services import PurchaseOrderService
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if user.has_perm('core.can_manage_financials') or user.has_perm('core.can_manage_jobs'):
            return True
        po = view.get_permission_target_po(request)
        return po is not None and PurchaseOrderService.user_can_manage(user, po)

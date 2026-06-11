from rest_framework.permissions import BasePermission


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

from tests.base import BaseTestCase
from django.contrib.auth.models import Permission
from apps.core.models import User
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.jobs.services import JobService


def grant_manage_jobs(user):
    perm = Permission.objects.get(
        codename='can_manage_jobs', content_type__app_label='core'
    )
    user.user_permissions.add(perm)
    return User.objects.get(pk=user.pk)  # re-fetch to clear perm cache


class UserCanManagePredicateTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(username='pm_p', password='x')
        self.other = User.objects.create_user(username='other_p', password='x')
        self.atom = grant_manage_jobs(
            User.objects.create_user(username='atom_p', password='x')
        )
        self.job = Job.objects.create(
            job_number='JOB-CAN-0001', name='Pred', status=Job.STATUS_DRAFT,
            contact=self.contact, project_manager=self.pm,
        )

    def test_atom_holder_can_manage_any_job(self):
        self.assertTrue(JobService.user_can_manage(self.atom, self.job))

    def test_pm_can_manage_own_job(self):
        self.assertTrue(JobService.user_can_manage(self.pm, self.job))

    def test_non_pm_non_atom_cannot(self):
        self.assertFalse(JobService.user_can_manage(self.other, self.job))

    def test_pm_cannot_manage_unmanaged_job(self):
        other_job = Job.objects.create(
            job_number='JOB-CAN-0002', name='NotMine', status=Job.STATUS_DRAFT,
            contact=self.contact,
        )
        self.assertFalse(JobService.user_can_manage(self.pm, other_job))

    def test_tolerates_none_job(self):
        self.assertFalse(JobService.user_can_manage(self.pm, None))


class PermissionBuildingBlocksTest(BaseTestCase):
    def test_imports_exist(self):
        from apps.api.permissions import CanManageJobOrPM
        from apps.api.mixins import JobScopedPermissionMixin
        self.assertTrue(hasattr(JobScopedPermissionMixin, 'get_object_job'))
        self.assertTrue(hasattr(JobScopedPermissionMixin, 'get_permission_target_job'))
        # default object-path resolution maps obj.job -> Job
        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        job = Job.objects.create(
            job_number='JOB-MIX-0001', name='Mix', status=Job.STATUS_DRAFT,
            contact=Contact.objects.first(),
        )
        mixin = JobScopedPermissionMixin()
        mixin.job_object_path = 'self'
        self.assertEqual(mixin.get_object_job(job), job)

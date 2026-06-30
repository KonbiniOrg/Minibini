from tests.base import BaseTestCase
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient
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


class JobViewSetPMAccessTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(username='pm_v', password='x')
        self.other = User.objects.create_user(username='other_v', password='x')
        self.job = Job.objects.create(
            job_number='JOB-VS-0001', name='VS', status=Job.STATUS_DRAFT,
            contact=self.contact, project_manager=self.pm,
        )
        self.unmanaged = Job.objects.create(
            job_number='JOB-VS-0002', name='VS2', status=Job.STATUS_DRAFT,
            contact=self.contact,
        )

    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_pm_can_patch_own_job(self):
        resp = self._client(self.pm).patch(
            f'/api/jobs/{self.job.pk}/', {'name': 'Renamed by PM'}, format='json'
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.job.refresh_from_db()
        self.assertEqual(self.job.name, 'Renamed by PM')

    def test_pm_cannot_patch_unmanaged_job(self):
        resp = self._client(self.pm).patch(
            f'/api/jobs/{self.unmanaged.pk}/', {'name': 'Nope'}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_non_pm_non_atom_cannot_patch(self):
        resp = self._client(self.other).patch(
            f'/api/jobs/{self.job.pk}/', {'name': 'Nope'}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_non_atom_cannot_create_job(self):
        resp = self._client(self.pm).post(
            '/api/jobs/', {'name': 'New', 'contact': self.contact.pk}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_serializer_can_manage_true_for_pm(self):
        resp = self._client(self.pm).get(f'/api/jobs/{self.job.pk}/')
        self.assertTrue(resp.data['can_manage'])

    def test_serializer_can_manage_false_for_other(self):
        resp = self._client(self.other).get(f'/api/jobs/{self.job.pk}/')
        self.assertFalse(resp.data['can_manage'])


from apps.estimates.models import EstWorksheet


from apps.estimates.models import Estimate


class EstimatePMAccessTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(username='pm_est', password='x')
        self.other = User.objects.create_user(username='other_est', password='x')
        self.job = Job.objects.create(
            job_number='JOB-EST-0001', name='EST', status=Job.STATUS_DRAFT,
            contact=self.contact, project_manager=self.pm,
        )
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-PM-0001',
            status=Estimate.STATUS_DRAFT,
        )

    def _client(self, user):
        c = APIClient(); c.force_authenticate(user=user); return c

    def test_pm_patch_estimate_not_forbidden(self):
        resp = self._client(self.pm).patch(
            f'/api/estimates/{self.est.pk}/', {}, format='json'
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_other_patch_estimate_forbidden(self):
        resp = self._client(self.other).patch(
            f'/api/estimates/{self.est.pk}/', {}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_pm_add_line_item_not_forbidden(self):
        resp = self._client(self.pm).post(
            f'/api/estimates/{self.est.pk}/line-items/', {}, format='json'
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_other_add_line_item_forbidden(self):
        resp = self._client(self.other).post(
            f'/api/estimates/{self.est.pk}/line-items/', {}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_serializer_can_manage(self):
        resp = self._client(self.pm).get(f'/api/estimates/{self.est.pk}/')
        self.assertTrue(resp.data['can_manage'])




from apps.estimates.models import ChangeOrder


class ChangeOrderPMAccessTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(username='pm_co', password='x')
        self.other = User.objects.create_user(username='other_co', password='x')
        self.job = Job.objects.create(
            job_number='JOB-CO-0001', name='CO', status=Job.STATUS_DRAFT,
            contact=self.contact, project_manager=self.pm,
        )
        # ChangeOrder.estimate is required (PROTECT); save() derefs it.
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-CO-PM-0001',
            status=Estimate.STATUS_DRAFT,
        )
        self.co = ChangeOrder.objects.create(
            job=self.job, estimate=self.est, status=ChangeOrder.STATUS_DRAFT,
        )

    def _client(self, user):
        c = APIClient(); c.force_authenticate(user=user); return c

    def test_pm_patch_co_not_forbidden(self):
        resp = self._client(self.pm).patch(
            f'/api/change-orders/{self.co.pk}/', {}, format='json'
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_other_patch_co_forbidden(self):
        resp = self._client(self.other).patch(
            f'/api/change-orders/{self.co.pk}/', {}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_pm_add_co_line_item_not_forbidden(self):
        resp = self._client(self.pm).post(
            f'/api/change-orders/{self.co.pk}/line-items/', {}, format='json'
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_other_add_co_line_item_forbidden(self):
        resp = self._client(self.other).post(
            f'/api/change-orders/{self.co.pk}/line-items/', {}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_serializer_can_manage(self):
        resp = self._client(self.pm).get(f'/api/change-orders/{self.co.pk}/')
        self.assertTrue(resp.data['can_manage'])


from apps.deliverables.models import Deliverable


class DeliverablePMAccessTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(username='pm_dl', password='x')
        self.other = User.objects.create_user(username='other_dl', password='x')
        self.job = Job.objects.create(
            job_number='JOB-DL-0001', name='DL', status=Job.STATUS_DRAFT,
            contact=self.contact, project_manager=self.pm,
        )

    def _client(self, user):
        c = APIClient(); c.force_authenticate(user=user); return c

    def test_pm_create_deliverable_not_forbidden(self):
        resp = self._client(self.pm).post(
            f'/api/jobs/{self.job.pk}/deliverables/', {}, format='json'
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_other_create_deliverable_forbidden(self):
        resp = self._client(self.other).post(
            f'/api/jobs/{self.job.pk}/deliverables/', {}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

    def test_serializer_can_manage(self):
        from decimal import Decimal
        Deliverable.objects.create(
            job=self.job, description='Stool', qty_ordered=Decimal('1'),
            units='ea', sort_order=10,
        )
        resp = self._client(self.pm).get(f'/api/jobs/{self.job.pk}/deliverables/')
        self.assertTrue(resp.data[0]['can_manage'])


from apps.jobs.models import Task


class TaskAndContactGuardTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from decimal import Decimal
        from apps.jobs.models import RateScheme
        from apps.core.models import AccountingCategory
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(username='pm_tk', password='x')
        self.other = User.objects.create_user(username='other_tk', password='x')
        self.job = Job.objects.create(
            job_number='JOB-TK-0001', name='TK', status=Job.STATUS_DRAFT,
            contact=self.contact, project_manager=self.pm,
        )
        # Task.rate_scheme is NOT NULL at the DB level; supply one.
        self.cat = AccountingCategory.objects.create(code='LAB-tk', name='Labor TK')
        self.scheme = RateScheme.objects.create(
            name='Hourly TK', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50.00'), unit_label='hour',
            accounting_category=self.cat,
        )
        self.task = Task.objects.create(
            job=self.job, name='Mill', rate_scheme=self.scheme, sort_order=1,
        )

    def _client(self, user):
        c = APIClient(); c.force_authenticate(user=user); return c

    def test_task_serializer_can_manage_for_pm(self):
        resp = self._client(self.pm).get(f'/api/tasks/{self.task.pk}/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data['can_manage'])

    def test_task_serializer_can_manage_false_for_other(self):
        resp = self._client(self.other).get(f'/api/tasks/{self.task.pk}/')
        self.assertFalse(resp.data['can_manage'])

    def test_job_payload_with_tasks_still_renders(self):
        # Nested TaskSerializer has no request context -> can_manage False there,
        # but the Job payload must not crash and the job-level can_manage is the
        # authoritative gate for the task tree.
        resp = self._client(self.pm).get(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data['can_manage'])
        self.assertTrue(len(resp.data['tasks']) >= 1)

    def test_pm_cannot_edit_contacts(self):
        # PM holds no can_manage_jobs atom -> contacts stay forbidden.
        resp = self._client(self.pm).patch(
            f'/api/contacts/{self.contact.pk}/', {'first_name': 'X'}, format='json'
        )
        self.assertEqual(resp.status_code, 403)


class TaskAssignPMAccessTest(BaseTestCase):
    """Manual task assignment (/api/tasks/{id}/assign/) is manager-or-PM.
    Auto-assignment on Blep start is separate and stays open to any worker."""

    def setUp(self):
        super().setUp()
        from apps.jobs.models import Task, RateScheme
        from apps.core.models import AccountingCategory
        from decimal import Decimal
        self.contact = Contact.objects.first()
        self.pm = User.objects.create_user(username='pm_asg', password='x')
        self.other = User.objects.create_user(username='other_asg', password='x')
        self.job = Job.objects.create(
            job_number='JOB-ASG-0001', name='ASG', status=Job.STATUS_DRAFT,
            contact=self.contact, project_manager=self.pm,
        )
        ac = AccountingCategory.objects.create(code='ASG-AC', name='ASG AC')
        scheme = RateScheme.objects.create(
            name='ASG-S', algorithm='entered_qty', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        self.task = Task.objects.create(
            job=self.job, name='T', rate_scheme=scheme, sort_order=1,
        )

    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_pm_can_assign_on_own_job(self):
        resp = self._client(self.pm).post(
            f'/api/tasks/{self.task.pk}/assign/', {'assignee': None}, format='json'
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_non_pm_non_atom_cannot_assign(self):
        resp = self._client(self.other).post(
            f'/api/tasks/{self.task.pk}/assign/', {'assignee': None}, format='json'
        )
        self.assertEqual(resp.status_code, 403)

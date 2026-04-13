from decimal import Decimal
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth.models import Permission
from django.test import TestCase
from tests.base import BaseTestCase
from apps.core.models import User, HistoryEntry, AccountingCategory
from apps.contacts.models import Contact
from apps.jobs.models import Job, Task, PlanTask
from apps.estimates.models import (
    Estimate, EstWorksheet, WorkTemplate, TaskTemplate,
    TemplateTaskAssociation,
)
from apps.inventory.models import PlanMaterial


def _make_admin(username='admin_jobapi'):
    user = User.objects.create_user(username=username, password='pass')
    perm = Permission.objects.get(codename='can_manage_jobs')
    user.user_permissions.add(perm)
    return User.objects.get(pk=user.pk)


class WorkOrderRoutesGoneTest(BaseTestCase):
    """Phase C1: /api/work-orders/ routes are gone."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_work_orders_list_is_404(self):
        response = self.client.get('/api/work-orders/')
        self.assertEqual(response.status_code, 404)

    def test_work_orders_detail_is_404(self):
        response = self.client.get('/api/work-orders/1/')
        self.assertEqual(response.status_code, 404)


class JobAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def _get_approved_job(self):
        """Get or create a job in Job.STATUS_APPROVED status (draft→submitted→approved)."""
        job = Job.objects.filter(status=Job.STATUS_APPROVED).first()
        if not job:
            job = Job.objects.first()
            # Walk through valid transitions
            job.status = Job.STATUS_SUBMITTED
            job.save()
            job.status = Job.STATUS_APPROVED
            job.save()
        return job

    def test_list_jobs(self):
        response = self.client.get('/api/jobs/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)

    def test_create_job(self):
        from apps.contacts.models import Contact
        contact = Contact.objects.first()
        response = self.client.post('/api/jobs/', {
            'name': 'Test API Job',
            'contact': contact.pk,
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['name'], 'Test API Job')
        self.assertIn('job_number', response.data)

    def test_retrieve_job(self):
        job = Job.objects.first()
        response = self.client.get(f'/api/jobs/{job.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['job_id'], job.pk)

    def test_update_job(self):
        job = Job.objects.first()
        response = self.client.patch(f'/api/jobs/{job.pk}/', {
            'name': 'Updated Name',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Updated Name')

    def test_delete_job(self):
        # Create a standalone job with no related objects
        from apps.contacts.models import Contact
        contact = Contact.objects.first()
        response = self.client.post('/api/jobs/', {
            'name': 'Delete Me',
            'contact': contact.pk,
        }, format='json')
        job_id = response.data['job_id']
        response = self.client.delete(f'/api/jobs/{job_id}/')
        self.assertEqual(response.status_code, 204)

    def test_complete_job(self):
        job = self._get_approved_job()
        # Must walk: approved -> work_complete -> completed
        job.status = Job.STATUS_WORK_COMPLETE
        job.save()
        response = self.client.post(f'/api/jobs/{job.pk}/complete/')
        self.assertEqual(response.status_code, 200)

    def test_cancel_job_requires_reason(self):
        job = self._get_approved_job()
        response = self.client.post(f'/api/jobs/{job.pk}/cancel/', {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_cancel_job_with_reason(self):
        job = self._get_approved_job()
        response = self.client.post(f'/api/jobs/{job.pk}/cancel/', {
            'reason': 'Customer withdrew',
        }, format='json')
        self.assertEqual(response.status_code, 200)

    def test_cancel_job_creates_history(self):
        job = self._get_approved_job()
        self.client.post(f'/api/jobs/{job.pk}/cancel/', {
            'reason': 'Customer withdrew',
        }, format='json')
        entry = HistoryEntry.objects.filter(
            entry_type='audit', object_type='job', object_id=job.pk,
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.text, 'Customer withdrew')
        self.assertEqual(entry.user, self.user)


# ------- Phase C2: Job-scoped task sub-resource --------

class JobTaskSubResourceTest(TestCase):
    """Phase C2: POST/PATCH/DELETE /api/jobs/{id}/tasks/..."""

    def setUp(self):
        self.client = APIClient()
        self.user = _make_admin('jobtask_admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='T', last_name='C')
        self.job = Job.objects.create(
            job_number='C2-T-001', name='Task Job', contact=self.contact,
        )

    def test_list_tasks_on_job(self):
        Task.objects.create(job=self.job, name='First task')
        response = self.client.get(f'/api/jobs/{self.job.pk}/tasks/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'First task')

    def test_create_task_on_job(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/tasks/',
            {'name': 'New task', 'units': 'hours', 'rate': '25.00', 'est_qty': '3.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['name'], 'New task')
        t = Task.objects.get(pk=response.data['task_id'])
        self.assertEqual(t.job_id, self.job.pk)

    def test_update_task_on_job(self):
        task = Task.objects.create(job=self.job, name='Original')
        response = self.client.patch(
            f'/api/jobs/{self.job.pk}/tasks/{task.pk}/',
            {'name': 'Renamed'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        task.refresh_from_db()
        self.assertEqual(task.name, 'Renamed')

    def test_delete_task_on_job(self):
        task = Task.objects.create(job=self.job, name='Goner')
        response = self.client.delete(f'/api/jobs/{self.job.pk}/tasks/{task.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('message', response.data)
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())

    def test_update_task_wrong_job_404(self):
        other_job = Job.objects.create(
            job_number='C2-T-002', name='Other', contact=self.contact,
        )
        task = Task.objects.create(job=other_job, name='Theirs')
        response = self.client.patch(
            f'/api/jobs/{self.job.pk}/tasks/{task.pk}/',
            {'name': 'nope'},
            format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_create_task_requires_can_manage_jobs(self):
        worker = User.objects.create_user(username='jt_worker', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/tasks/',
            {'name': 'Nope'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_list_tasks_any_authenticated(self):
        Task.objects.create(job=self.job, name='Read me')
        worker = User.objects.create_user(username='jt_reader', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.get(f'/api/jobs/{self.job.pk}/tasks/')
        self.assertEqual(response.status_code, 200)


class JobSerializerNestingTest(TestCase):
    """Phase C2: GET /api/jobs/{id}/ nests tasks and template."""

    def setUp(self):
        self.client = APIClient()
        self.user = _make_admin('jobnest_admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='T', last_name='C')
        self.template = WorkTemplate.objects.create(
            template_name='Basic Template', is_active=True,
        )
        self.job = Job.objects.create(
            job_number='C2-N-001', name='Nesting Job', contact=self.contact,
            template=self.template,
        )
        Task.objects.create(job=self.job, name='A task')
        Task.objects.create(job=self.job, name='B task')

    def test_retrieve_nests_tasks_and_template(self):
        response = self.client.get(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('tasks', response.data)
        self.assertEqual(len(response.data['tasks']), 2)
        self.assertIn('template', response.data)
        self.assertIsNotNone(response.data['template'])
        self.assertEqual(response.data['template']['template_name'], 'Basic Template')

    def test_retrieve_template_null_when_absent(self):
        job = Job.objects.create(
            job_number='C2-N-002', name='No template', contact=self.contact,
        )
        response = self.client.get(f'/api/jobs/{job.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['template'])

    def test_update_template_via_template_id(self):
        job = Job.objects.create(
            job_number='C2-N-003', name='Will link', contact=self.contact,
        )
        response = self.client.patch(
            f'/api/jobs/{job.pk}/',
            {'template_id': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        job.refresh_from_db()
        self.assertEqual(job.template_id, self.template.pk)


class JobListQueryCountTest(TestCase):
    """GET /api/jobs/ should not fire N+1 queries for tasks/template."""

    def setUp(self):
        self.client = APIClient()
        self.user = _make_admin('jobqc_admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='Q', last_name='C')
        self.template = WorkTemplate.objects.create(
            template_name='QC Template', is_active=True,
        )

    def _make_jobs(self, count):
        existing = Job.objects.count()
        for i in range(existing, existing + count):
            job = Job.objects.create(
                job_number=f'QC-{i:03d}',
                name=f'QC Job {i}',
                contact=self.contact,
                template=self.template,
            )
            Task.objects.create(job=job, name=f'Task A {i}')
            Task.objects.create(job=job, name=f'Task B {i}')

    def _list_query_count(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get('/api/jobs/')
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries), len(response.data['results'])

    def test_list_query_count_does_not_scale_with_jobs(self):
        # Measure with 2 jobs.
        self._make_jobs(2)
        q2, n2 = self._list_query_count()
        self.assertEqual(n2, 2)

        # Add 3 more jobs (total 5) and measure again.
        self._make_jobs(3)
        q5, n5 = self._list_query_count()
        self.assertEqual(n5, 5)

        self.assertEqual(
            q2, q5,
            f'Query count grew with jobs: 2 jobs -> {q2}, 5 jobs -> {q5}',
        )


class JobWorkCompleteTest(TestCase):
    """Phase C2: POST /api/jobs/{id}/work-complete/."""

    def setUp(self):
        self.client = APIClient()
        self.user = _make_admin('workcomplete_admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='T', last_name='C')

    def _approved_job(self):
        job = Job.objects.create(
            job_number='C2-WC-001', name='WC Job', contact=self.contact,
        )
        job.status = Job.STATUS_SUBMITTED
        job.save()
        job.status = Job.STATUS_APPROVED
        job.save()
        return job

    def test_work_complete_transitions_job(self):
        job = self._approved_job()
        response = self.client.post(f'/api/jobs/{job.pk}/work-complete/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_WORK_COMPLETE)

    def test_work_complete_requires_can_manage_jobs(self):
        job = self._approved_job()
        worker = User.objects.create_user(username='wc_worker', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(f'/api/jobs/{job.pk}/work-complete/', {}, format='json')
        self.assertEqual(response.status_code, 403)


class JobPopulateFromTemplateTest(TestCase):
    """Phase C2: POST /api/jobs/{id}/populate-from-template/."""

    def setUp(self):
        self.client = APIClient()
        self.user = _make_admin('poptpl_admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='T', last_name='C')
        self.job = Job.objects.create(
            job_number='C2-PT-001', name='PT Job', contact=self.contact,
        )
        self.template = WorkTemplate.objects.create(
            template_name='Kitchen', is_active=True,
        )
        cat = AccountingCategory.objects.create(name='Labor')
        self.task_template = TaskTemplate.objects.create(
            template_name='Countertop', is_active=True,
            units='each', rate=100, accounting_category=cat,
        )
        TemplateTaskAssociation.objects.create(
            work_template=self.template,
            task_template=self.task_template,
            est_qty=2, sort_order=1,
        )

    def test_populate_from_template_success(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/populate-from-template/',
            {'template_id': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.job.refresh_from_db()
        self.assertEqual(self.job.template_id, self.template.pk)
        self.assertEqual(self.job.tasks.count(), 1)
        self.assertEqual(self.job.tasks.first().name, 'Countertop')

    def test_populate_from_template_missing(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/populate-from-template/',
            {},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_populate_from_template_inactive(self):
        self.template.is_active = False
        self.template.save()
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/populate-from-template/',
            {'template_id': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_populate_from_template_requires_can_manage_jobs(self):
        worker = User.objects.create_user(username='pt_worker', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/populate-from-template/',
            {'template_id': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 403)


class JobPopulateFromEstimateTest(TestCase):
    """Phase C2: POST /api/jobs/{id}/populate-from-estimate/."""

    def setUp(self):
        self.client = APIClient()
        self.user = _make_admin('popest_admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='T', last_name='C')
        self.job = Job.objects.create(
            job_number='C2-PE-001', name='PE Job', contact=self.contact,
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-PE-001',
            status=Estimate.STATUS_ACCEPTED,
        )

    def test_populate_from_accepted_estimate(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/populate-from-estimate/',
            {'estimate_id': self.estimate.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_populate_from_draft_estimate_400(self):
        draft = Estimate.objects.create(
            job=self.job, estimate_number='EST-PE-002',
            status=Estimate.STATUS_DRAFT,
        )
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/populate-from-estimate/',
            {'estimate_id': draft.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_populate_from_estimate_missing(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/populate-from-estimate/',
            {},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_populate_from_estimate_requires_can_manage_jobs(self):
        worker = User.objects.create_user(username='pe_worker', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/populate-from-estimate/',
            {'estimate_id': self.estimate.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 403)


class JobCopyFromWorksheetTest(TestCase):
    """Phase C2: POST /api/jobs/{id}/copy-from-worksheet/."""

    def setUp(self):
        self.client = APIClient()
        self.user = _make_admin('copyws_admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='T', last_name='C')
        self.job = Job.objects.create(
            job_number='C2-CW-001', name='CW Job', contact=self.contact,
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Build cabinet',
            units='each', rate=200, est_qty=1,
        )
        PlanMaterial.objects.create(
            plan_task=self.plan_task,
            description='Plywood sheet',
            quantity=2, unit_cost=40, sell_price=60,
        )

    def test_copy_from_worksheet_success(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/copy-from-worksheet/',
            {'worksheet_id': self.worksheet.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.job.refresh_from_db()
        self.assertEqual(self.job.tasks.count(), 1)
        task = self.job.tasks.first()
        self.assertEqual(task.name, 'Build cabinet')
        self.assertEqual(task.materials.count(), 1)

    def test_copy_from_worksheet_missing(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/copy-from-worksheet/',
            {},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_copy_from_worksheet_not_found(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/copy-from-worksheet/',
            {'worksheet_id': 99999},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_copy_from_worksheet_requires_can_manage_jobs(self):
        worker = User.objects.create_user(username='cw_worker', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/copy-from-worksheet/',
            {'worksheet_id': self.worksheet.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 403)


class JobReorderTasksTest(TestCase):
    """Phase C2: POST /api/jobs/{id}/reorder-tasks/."""

    def setUp(self):
        self.client = APIClient()
        self.user = _make_admin('reord_admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='T', last_name='C')
        self.job = Job.objects.create(
            job_number='C2-R-001', name='R Job', contact=self.contact,
        )
        self.a = Task.objects.create(job=self.job, name='A', sort_order=0)
        self.b = Task.objects.create(job=self.job, name='B', sort_order=1)
        self.c = Task.objects.create(job=self.job, name='C', sort_order=2)

    def test_reorder_down(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/reorder-tasks/',
            {'task_id': self.a.pk, 'direction': 'down'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertEqual(self.a.sort_order, 1)
        self.assertEqual(self.b.sort_order, 0)

    def test_reorder_missing_task_id(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/reorder-tasks/',
            {'direction': 'up'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_reorder_invalid_direction(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/reorder-tasks/',
            {'task_id': self.a.pk, 'direction': 'sideways'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_reorder_requires_can_manage_jobs(self):
        worker = User.objects.create_user(username='r_worker', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/reorder-tasks/',
            {'task_id': self.a.pk, 'direction': 'down'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)


class JobAddFromTemplateTest(TestCase):
    """Phase C2: POST /api/jobs/{id}/add-from-template/."""

    def setUp(self):
        self.client = APIClient()
        self.user = _make_admin('aft_admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='T', last_name='C')
        self.job = Job.objects.create(
            job_number='C2-AFT-001', name='AFT Job', contact=self.contact,
        )
        self.template = TaskTemplate.objects.create(
            template_name='Paint room',
            description='Paint all walls',
            units='sqft',
            rate=Decimal('2.50'),
            is_active=True,
        )

    def test_add_from_template_success(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/add-from-template/',
            {'template_id': self.template.pk, 'est_qty': '100.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['name'], 'Paint room')
        self.assertEqual(Task.objects.filter(job=self.job).count(), 1)

    def test_add_from_template_default_qty(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/add-from-template/',
            {'template_id': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_add_from_template_missing(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/add-from-template/',
            {},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_add_from_template_not_found(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/add-from-template/',
            {'template_id': 99999},
            format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_add_from_template_requires_auth(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/add-from-template/',
            {'template_id': self.template.pk},
            format='json',
        )
        self.assertIn(response.status_code, [401, 403])


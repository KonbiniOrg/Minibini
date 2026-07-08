from decimal import Decimal
from apps.core.models import JobHistory
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth.models import Permission
from django.test import TestCase
from tests.base import BaseTestCase
from apps.core.models import User, AccountingCategory, Configuration, AppState
from apps.contacts.models import Contact
from apps.jobs.models import Job, Task, RateScheme
from apps.estimates.models import (
    WorkTemplate, ServiceItem,
    TemplateTaskAssociation,
)
from apps.inventory.models import Material


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

    def test_open_filter_excludes_dead_jobs(self):
        """?open=true drops completed/cancelled/rejected (PO-line job picker);
        work_complete stays — still billable/adjustable until fully completed."""
        from apps.contacts.models import Contact
        contact = Contact.objects.first()
        # Walk each job through VALID transitions to its target status.
        PATHS = {
            Job.STATUS_REJECTED: [Job.STATUS_REJECTED],
            Job.STATUS_APPROVED: [Job.STATUS_SUBMITTED, Job.STATUS_APPROVED],
            Job.STATUS_CANCELLED: [
                Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_CANCELLED],
            Job.STATUS_WORK_COMPLETE: [
                Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                Job.STATUS_IN_PROGRESS, Job.STATUS_WORK_COMPLETE],
            Job.STATUS_COMPLETED: [
                Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                Job.STATUS_IN_PROGRESS, Job.STATUS_WORK_COMPLETE,
                Job.STATUS_COMPLETED],
        }
        dead_ids, kept_ids = [], []
        for status_value, bucket in (
            (Job.STATUS_COMPLETED, dead_ids),
            (Job.STATUS_CANCELLED, dead_ids),
            (Job.STATUS_REJECTED, dead_ids),
            (Job.STATUS_WORK_COMPLETE, kept_ids),
            (Job.STATUS_APPROVED, kept_ids),
        ):
            job = Job.objects.create(
                contact=contact, name=f'openfilter-{status_value}',
                job_number=f'JOB-OPEN-{status_value[:4].upper()}',
            )
            for step in PATHS[status_value]:
                job.status = step
                job.save()
            bucket.append(job.pk)
        resp = self.client.get('/api/jobs/?open=true&page_size=100')
        ids = [r['job_id'] for r in resp.data['results']]
        for pk in dead_ids:
            self.assertNotIn(pk, ids)
        for pk in kept_ids:
            self.assertIn(pk, ids)
        # Without the param, everything is listed.
        resp = self.client.get('/api/jobs/?page_size=100')
        ids = [r['job_id'] for r in resp.data['results']]
        for pk in dead_ids + kept_ids:
            self.assertIn(pk, ids)

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
        self.assertEqual(response.status_code, 200)
        self.assertIn('message', response.data)

    def test_complete_job(self):
        job = self._get_approved_job()
        # Must walk: approved -> in_progress -> work_complete -> completed
        job.status = Job.STATUS_IN_PROGRESS
        job.save()
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
        entry = JobHistory.objects.filter(
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
        from apps.jobs.models import RateScheme
        ac = AccountingCategory.objects.create(code='JT-AC', name='Job Task AC')
        self.scheme = RateScheme.objects.create(
            name='Job Task Scheme', algorithm='entered_qty',
            rate=Decimal('25.00'), unit_label='ea', accounting_category=ac,
        )

    def test_list_tasks_on_job(self):
        Task.objects.create(job=self.job, name='First task', rate_scheme=self.scheme)
        response = self.client.get(f'/api/jobs/{self.job.pk}/tasks/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'First task')

    def test_create_task_on_job(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/tasks/',
            {'name': 'New task', 'rate_scheme': self.scheme.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['name'], 'New task')
        t = Task.objects.get(pk=response.data['task_id'])
        self.assertEqual(t.job_id, self.job.pk)
        # rate_scheme set directly on Task (no TaskCharge)
        self.assertEqual(t.rate_scheme_id, self.scheme.pk)

    def test_update_task_on_job(self):
        task = Task.objects.create(job=self.job, name='Original', rate_scheme=self.scheme)
        response = self.client.patch(
            f'/api/jobs/{self.job.pk}/tasks/{task.pk}/',
            {'name': 'Renamed'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        task.refresh_from_db()
        self.assertEqual(task.name, 'Renamed')

    def test_delete_task_on_job(self):
        task = Task.objects.create(job=self.job, name='Goner', rate_scheme=self.scheme)
        response = self.client.delete(f'/api/jobs/{self.job.pk}/tasks/{task.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('message', response.data)
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())

    def test_update_task_wrong_job_404(self):
        other_job = Job.objects.create(
            job_number='C2-T-002', name='Other', contact=self.contact,
        )
        task = Task.objects.create(job=other_job, name='Theirs', rate_scheme=self.scheme)
        response = self.client.patch(
            f'/api/jobs/{self.job.pk}/tasks/{task.pk}/',
            {'name': 'nope'},
            format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_create_task_any_authenticated(self):
        worker = User.objects.create_user(username='jt_worker', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/tasks/',
            {'name': 'Worker task', 'rate_scheme': self.scheme.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_update_task_allowed_for_worker(self):
        # Editing a task is open to any authenticated user.
        task = Task.objects.create(job=self.job, name='Original', rate_scheme=self.scheme)
        worker = User.objects.create_user(username='jt_worker_edit', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.patch(
            f'/api/jobs/{self.job.pk}/tasks/{task.pk}/',
            {'name': 'Reworded'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        task.refresh_from_db()
        self.assertEqual(task.name, 'Reworded')

    def test_delete_task_allowed_for_worker_without_bleps(self):
        # Deleting a blep-less, not-started task is open to any authenticated user.
        task = Task.objects.create(job=self.job, name='Goner', rate_scheme=self.scheme)
        worker = User.objects.create_user(username='jt_worker_del', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.delete(f'/api/jobs/{self.job.pk}/tasks/{task.pk}/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())

    def test_delete_task_with_bleps_blocked(self):
        # The no-Bleps rule (TaskService.delete_task) still applies to everyone:
        # a worker deleting a task that has time entries gets a 400.
        from apps.jobs.models import Blep
        from django.utils import timezone
        task = Task.objects.create(job=self.job, name='Worked', rate_scheme=self.scheme)
        Blep.objects.create(task=task, user=self.user, start_time=timezone.now())
        worker = User.objects.create_user(username='jt_worker_blep', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.delete(f'/api/jobs/{self.job.pk}/tasks/{task.pk}/')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertTrue(Task.objects.filter(pk=task.pk).exists())

    def test_list_tasks_any_authenticated(self):
        Task.objects.create(job=self.job, name='Read me', rate_scheme=self.scheme)
        worker = User.objects.create_user(username='jt_reader', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.get(f'/api/jobs/{self.job.pk}/tasks/')
        self.assertEqual(response.status_code, 200)

    def test_work_complete_still_denied_for_worker(self):
        # Opening task_detail must NOT open work-complete: it stays manager-or-PM.
        worker = User.objects.create_user(username='jt_worker_wc', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(f'/api/jobs/{self.job.pk}/work-complete/', {}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_reorder_tasks_still_denied_for_worker(self):
        # reorder-tasks also stays manager-or-PM via the fall-through.
        task = Task.objects.create(job=self.job, name='Reorder me', rate_scheme=self.scheme)
        worker = User.objects.create_user(username='jt_worker_ro', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/reorder-tasks/',
            {'task_id': task.pk, 'direction': 'up'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)


class JobSerializerNestingTest(TestCase):
    """Phase C2: GET /api/jobs/{id}/ nests tasks."""

    def setUp(self):
        self.client = APIClient()
        self.user = _make_admin('jobnest_admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='T', last_name='C')
        self.job = Job.objects.create(
            job_number='C2-N-001', name='Nesting Job', contact=self.contact,
        )
        ac = AccountingCategory.objects.create(code='NEST-AC', name='Nest AC')
        self.scheme = RateScheme.objects.create(
            name='S-nest', algorithm='entered_qty',
            rate=Decimal('1'), unit_label='ea', accounting_category=ac,
        )
        Task.objects.create(job=self.job, name='A task', rate_scheme=self.scheme)
        Task.objects.create(job=self.job, name='B task', rate_scheme=self.scheme)

    def test_retrieve_nests_tasks(self):
        response = self.client.get(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('tasks', response.data)
        self.assertEqual(len(response.data['tasks']), 2)
        self.assertNotIn('template', response.data)


class JobListQueryCountTest(TestCase):
    """GET /api/jobs/ should not fire N+1 queries for tasks."""

    def setUp(self):
        self.client = APIClient()
        self.user = _make_admin('jobqc_admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='Q', last_name='C')
        self.template = WorkTemplate.objects.create(
            template_name='QC Template',
        )
        ac = AccountingCategory.objects.create(code='QC-AC', name='QC AC')
        self.scheme = RateScheme.objects.create(
            name='S-qc', algorithm='entered_qty',
            rate=Decimal('1'), unit_label='ea', accounting_category=ac,
        )

    def _make_jobs(self, count):
        existing = Job.objects.count()
        for i in range(existing, existing + count):
            job = Job.objects.create(
                job_number=f'QC-{i:03d}',
                name=f'QC Job {i}',
                contact=self.contact,
            )
            Task.objects.create(job=job, name=f'Task A {i}', rate_scheme=self.scheme)
            Task.objects.create(job=job, name=f'Task B {i}', rate_scheme=self.scheme)

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
            template_name='Kitchen',
        )
        cat = AccountingCategory.objects.create(name='Labor')
        self.scheme = RateScheme.objects.create(
            name='S-poptpl', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('1'), unit_label='ea', accounting_category=cat,
        )
        self.service_item = ServiceItem.objects.create(
            template_name='Countertop', is_active=True,
            rate_scheme=self.scheme,
        )
        TemplateTaskAssociation.objects.create(
            work_template=self.template,
            service_item=self.service_item,
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
        self.assertEqual(self.job.tasks.count(), 1)
        self.assertEqual(self.job.tasks.first().name, 'Countertop')

    def test_populate_from_template_missing(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/populate-from-template/',
            {},
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
        ac = AccountingCategory.objects.create(code='REORD-AC', name='reord-ac')
        self.scheme = RateScheme.objects.create(
            name='S-reord', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('1'), unit_label='ea', accounting_category=ac,
        )
        self.a = Task.objects.create(job=self.job, name='A', sort_order=0, rate_scheme=self.scheme)
        self.b = Task.objects.create(job=self.job, name='B', sort_order=1, rate_scheme=self.scheme)
        self.c = Task.objects.create(job=self.job, name='C', sort_order=2, rate_scheme=self.scheme)

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


class JobPatchValidationErrorTest(TestCase):
    """PATCH /api/jobs/{id}/ with a service-layer ValidationError returns 400, not 500."""

    def setUp(self):
        self.client = APIClient()
        self.user = _make_admin('patchval_admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='T', last_name='C')
        ac = AccountingCategory.objects.create(code='PV-AC', name='pv-ac')
        from apps.jobs.models import RateScheme
        self.scheme = RateScheme.objects.create(
            name='S-pv', algorithm='entered_qty',
            rate=Decimal('25.00'), unit_label='ea', accounting_category=ac,
        )

    def _in_progress_job(self):
        job = Job.objects.create(
            job_number='PV-001', name='PV Job', contact=self.contact,
        )
        job.status = Job.STATUS_SUBMITTED
        job.save()
        job.status = Job.STATUS_APPROVED
        job.save()
        job.status = Job.STATUS_IN_PROGRESS
        job.save()
        return job

    def test_hold_with_open_blep_returns_400(self):
        """POST hold while a worker has an open blep must return 400, not 500."""
        from apps.jobs.models import Blep
        from django.utils import timezone

        job = self._in_progress_job()
        task = Task.objects.create(job=job, name='Active task', rate_scheme=self.scheme)
        # Create an open blep (no end_time)
        Blep.objects.create(task=task, user=self.user, start_time=timezone.now())

        response = self.client.post(
            f'/api/jobs/{job.pk}/hold/', {'reason': 'pausing'}, format='json')

        self.assertEqual(response.status_code, 400)
        body = response.data
        message = body.get('detail') or ''
        self.assertIn('open time entry', message)

    def test_hold_without_reason_returns_400(self):
        job = self._in_progress_job()
        response = self.client.post(f'/api/jobs/{job.pk}/hold/', {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_hold_and_release_round_trip(self):
        """POST hold sets the flag (status untouched); POST release clears it."""
        job = self._in_progress_job()

        response = self.client.post(
            f'/api/jobs/{job.pk}/hold/', {'reason': 'customer rethink'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['on_hold'])
        self.assertEqual(response.data['hold_reason'], 'customer rethink')
        job.refresh_from_db()
        self.assertTrue(job.on_hold)
        self.assertEqual(job.status, Job.STATUS_IN_PROGRESS)

        response = self.client.post(f'/api/jobs/{job.pk}/release/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['on_hold'])
        job.refresh_from_db()
        self.assertFalse(job.on_hold)
        self.assertEqual(job.hold_reason, '')

    def test_patch_status_on_hold_returns_400(self):
        """'on_hold' is no longer a status — a PATCH must 400."""
        job = self._in_progress_job()
        response = self.client.patch(
            f'/api/jobs/{job.pk}/', {'status': 'on_hold'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_patch_status_blocked_while_held(self):
        """A held job's status is parked (cancel excepted)."""
        job = self._in_progress_job()
        self.client.post(f'/api/jobs/{job.pk}/hold/', {'reason': 'wait'}, format='json')
        response = self.client.patch(
            f'/api/jobs/{job.pk}/', {'status': 'work_complete'}, format='json')
        self.assertEqual(response.status_code, 400)


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
        ac = AccountingCategory.objects.create(code='AFT-AC', name='aft-ac')
        self.scheme = RateScheme.objects.create(
            name='S-aft', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('1'), unit_label='ea', accounting_category=ac,
        )
        self.template = ServiceItem.objects.create(
            template_name='Paint room',
            description='Paint all walls',
            is_active=True,
            rate_scheme=self.scheme,
        )

    def test_add_from_template_success(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/add-from-template/',
            {'service_item_id': self.template.pk, 'est_qty': '100.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['name'], 'Paint room')
        self.assertEqual(Task.objects.filter(job=self.job).count(), 1)

    def test_add_from_template_default_qty(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/add-from-template/',
            {'service_item_id': self.template.pk},
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
        self.assertIn('service_item_id', response.data)

    def test_add_from_template_not_found(self):
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/add-from-template/',
            {'service_item_id': 99999},
            format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_add_from_template_requires_auth(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/add-from-template/',
            {'service_item_id': self.template.pk},
            format='json',
        )
        self.assertIn(response.status_code, [401, 403])


class JobDetailInvoiceFieldTest(TestCase):
    """Task/material atoms nested in GET /api/jobs/{id}/ carry an 'invoice' field."""

    def setUp(self):
        self.client = APIClient()
        self.user = _make_admin('invfld_admin')
        self.client.force_authenticate(user=self.user)
        self.contact = Contact.objects.create(first_name='T', last_name='C')
        self.job = Job.objects.create(
            job_number='INV-F-001', name='Invoice Field Job', contact=self.contact,
        )
        ac = AccountingCategory.objects.create(code='INVF-AC', name='invf-ac')
        # Required for Invoice.save() to generate invoice numbers
        Configuration.objects.get_or_create(
            key='invoice_number_sequence',
            defaults={'value': 'INV-{year}-{counter:04d}'},
        )
        AppState.objects.get_or_create(key='invoice_counter', defaults={'value': '0'})
        self.scheme = RateScheme.objects.create(
            name='S-invf', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='ea', accounting_category=ac,
        )
        self.task = Task.objects.create(
            job=self.job, name='Invoiceable Task', rate_scheme=self.scheme,
        )
        self.material = Material.objects.create(
            job=self.job,
            description='Test Material',
            quantity=Decimal('2.00'),
            sell_price=Decimal('5.00'),
            accounting_category=ac,
        )

    def _invoice_task(self, task):
        """Create a draft Invoice with a line item sourced from a task."""
        from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
        inv = Invoice.objects.create(job=task.job, status=Invoice.STATUS_DRAFT)
        li = InvoiceLineItem.objects.create(
            invoice=inv, description='t', qty=Decimal('1'),
            units='none', price=Decimal('10.00'),
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=li,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=task.pk,
        )
        return inv

    def _invoice_material(self, material):
        """Create a draft Invoice with a line item sourced from a material."""
        from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
        inv = Invoice.objects.create(job=material.job, status=Invoice.STATUS_DRAFT)
        li = InvoiceLineItem.objects.create(
            invoice=inv, description='m', qty=material.quantity,
            units='none', price=material.sell_price,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=li,
            source_type=InvoiceLineItemSource.SOURCE_MATERIAL,
            source_pk=material.pk,
        )
        return inv

    def _get_job_detail(self):
        resp = self.client.get(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_job_detail_marks_invoiced_task(self):
        inv = self._invoice_task(self.task)
        data = self._get_job_detail()
        task_row = next(t for t in data['tasks'] if t['task_id'] == self.task.pk)
        self.assertIsNotNone(task_row['invoice'])
        self.assertEqual(set(task_row['invoice'].keys()), {'id', 'number'})
        self.assertEqual(task_row['invoice']['id'], inv.pk)

    def test_job_detail_uninvoiced_task_has_null_invoice(self):
        data = self._get_job_detail()
        task_row = next(t for t in data['tasks'] if t['task_id'] == self.task.pk)
        self.assertIsNone(task_row['invoice'])

    def test_job_detail_marks_invoiced_material(self):
        inv = self._invoice_material(self.material)
        data = self._get_job_detail()
        mat_row = next(m for m in data['materials'] if m['material_id'] == self.material.pk)
        self.assertIsNotNone(mat_row['invoice'])
        self.assertEqual(set(mat_row['invoice'].keys()), {'id', 'number'})
        self.assertEqual(mat_row['invoice']['id'], inv.pk)

    def test_job_detail_uninvoiced_material_has_null_invoice(self):
        data = self._get_job_detail()
        mat_row = next(m for m in data['materials'] if m['material_id'] == self.material.pk)
        self.assertIsNone(mat_row['invoice'])

    def test_job_detail_invoice_claims_single_query(self):
        """Claims are built in one query regardless of how many invoiced atoms the job has.

        Empirically derived: run once without the second atom to pin the baseline,
        then assert adding a second invoiced atom does NOT increase the count.
        """
        from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        # Create one invoice with a task source (one invoiced atom)
        inv = self._invoice_task(self.task)

        # Measure baseline with one invoiced task
        with CaptureQueriesContext(connection) as ctx_one:
            resp = self.client.get(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(resp.status_code, 200)
        count_one = len(ctx_one.captured_queries)

        # Add a second invoiced atom to the same invoice (material) — same job,
        # same invoice avoids the one-draft-per-job constraint.
        li2 = InvoiceLineItem.objects.create(
            invoice=inv, description='m2', qty=self.material.quantity,
            units='none', price=self.material.sell_price,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=li2,
            source_type=InvoiceLineItemSource.SOURCE_MATERIAL,
            source_pk=self.material.pk,
        )

        with CaptureQueriesContext(connection) as ctx_two:
            resp = self.client.get(f'/api/jobs/{self.job.pk}/')
        self.assertEqual(resp.status_code, 200)
        count_two = len(ctx_two.captured_queries)

        # The claim map is built once per job — adding a second invoiced atom
        # must not fire an extra query.
        self.assertEqual(
            count_one, count_two,
            f'Query count grew when a second invoiced atom was added: '
            f'1 atom → {count_one} queries, 2 atoms → {count_two} queries',
        )

        # Absolute pin: guard against flat per-request regressions that the
        # comparative assertion above cannot catch.  N=18 (was 13 before Task 3.4):
        # +1 for the `fees` prefetch query, +1 for EstimateClaimService.claimed_set_for_job
        # (one query per job-detail to build the estimate-claim set),
        # +3 for `nav_targets` (latest estimate / invoice / PO for the job nav
        # rail, 2026-07-08; detail-only, skipped in list context).
        # If the jobs viewset gains new prefetches/annotations this number may need
        # updating — update it together with a comment explaining why the count changed.
        self.assertEqual(
            count_one, 18,
            f'Absolute query count for job-detail changed: expected 18, got {count_one}. '
            f'Update this pin if the viewset legitimately changed (add a comment explaining why).',
        )

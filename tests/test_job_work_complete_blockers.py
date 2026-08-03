"""Hand-marking a job work-complete requires everything final (plan B4).

POST /api/jobs/{id}/work-complete/ mutates nothing and returns the
blocker list while any non-terminal task or pending material exists;
with no blockers it advances the job as before. The SPA renders the
blockers as a "resolve these first" modal ("Check Complete").
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import User, AccountingCategory
from apps.inventory.models import Material
from apps.jobs.models import Job, Task, Blep, RateScheme
from tests.base import grant_atoms


class WorkCompleteBlockersTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.manager = User.objects.create_user(
            username='wcmgr', password='testpass',
        )
        self.manager = grant_atoms(self.manager, 'can_manage_jobs')
        self.client.force_authenticate(user=self.manager)

        self.contact = Contact.objects.create(first_name='W', last_name='C')
        self.job = Job.objects.create(
            job_number='WCB-001', name='WC Job', contact=self.contact,
        )
        for status in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
                       Job.STATUS_IN_PROGRESS):
            self.job.status = status
            self.job.save()
        self.ac = AccountingCategory.objects.create(code='WCB', name='WC AC')
        self.scheme = RateScheme.objects.create(
            name='S-wc', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('45'), unit_label='hour', accounting_category=self.ac,
        )

    def _task(self, name, status=Task.STATUS_PENDING):
        task = Task(
            job=self.job, name=name,
        )
        task.stamp_from_scheme(self.scheme)
        task.save()
        if status != Task.STATUS_PENDING:
            Task.objects.filter(pk=task.pk).update(status=status)
            task.refresh_from_db()
        return task

    def _post(self):
        return self.client.post(f'/api/jobs/{self.job.pk}/work-complete/')

    def test_open_task_blocks_and_mutates_nothing(self):
        task = self._task('Open task')
        response = self._post()
        self.assertEqual(response.status_code, 200)
        blockers = response.data.get('blockers')
        self.assertIsNotNone(blockers)
        self.assertEqual(
            [t['task_id'] for t in blockers['tasks']], [task.pk])
        self.assertEqual(blockers['materials'], [])
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)

    def test_blocked_task_is_a_blocker(self):
        self._task('Stuck', status=Task.STATUS_BLOCKED)
        response = self._post()
        self.assertEqual(len(response.data['blockers']['tasks']), 1)
        self.assertEqual(
            response.data['blockers']['tasks'][0]['status'], 'blocked')

    def test_pending_task_material_blocks(self):
        task = self._task('Done', status=Task.STATUS_COMPLETE)
        material = Material.objects.create(
            job=self.job, task=task, description='Unused stock',
            quantity=Decimal('2'), accounting_category=self.ac,
        )
        response = self._post()
        blockers = response.data['blockers']
        self.assertEqual(blockers['tasks'], [])
        self.assertEqual(
            [m['material_id'] for m in blockers['materials']],
            [material.pk])
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)

    def test_loose_pending_material_blocks(self):
        self._task('Done', status=Task.STATUS_COMPLETE)
        material = Material.objects.create(
            job=self.job, description='Loose stock', quantity=Decimal('1'),
            accounting_category=self.ac,
        )
        response = self._post()
        self.assertEqual(
            [m['material_id'] for m in response.data['blockers']['materials']],
            [material.pk])

    def test_consumed_material_is_not_a_blocker(self):
        task = self._task('Done', status=Task.STATUS_COMPLETE)
        Material.objects.create(
            job=self.job, task=task, description='Used stock',
            quantity=Decimal('2'), accounting_category=self.ac,
            consumption_state=Material.CONSUMPTION_STATE_CONSUMED,
        )
        response = self._post()
        self.assertNotIn('blockers', response.data)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_WORK_COMPLETE)

    def test_clean_job_advances(self):
        self._task('Done', status=Task.STATUS_COMPLETE)
        self._task('Killed', status=Task.STATUS_CANCELLED)
        response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('blockers', response.data)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_WORK_COMPLETE)

    def test_approved_job_with_blockers_stays_approved(self):
        # The approved -> in_progress walk must not fire when blockers exist.
        job = Job.objects.create(
            job_number='WCB-002', name='Approved job', contact=self.contact,
        )
        for status in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
            job.status = status
            job.save()
        t = Task(job=job, name='Open')
        t.stamp_from_scheme(self.scheme)
        t.save()
        response = self.client.post(f'/api/jobs/{job.pk}/work-complete/')
        self.assertIsNotNone(response.data.get('blockers'))
        job.refresh_from_db()
        self.assertEqual(job.status, Job.STATUS_APPROVED)

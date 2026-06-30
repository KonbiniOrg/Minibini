"""Task 2.1: Direct Task creation on a Job at any non-terminal status.

Tests that:
  - TaskService.create_direct succeeds on a DRAFT job (no status gate).
  - TaskService.create_direct succeeds on a SUBMITTED job (non-terminal, pre-approval).
  - TaskService.create_direct succeeds on an APPROVED job (no regression).
  - POST /api/jobs/{id}/tasks/ returns 201 for a DRAFT job.
  - The on_hold guard still rejects Task creation on an on-hold job.
  - materialize_worksheet_onto_job STILL gates on approved/in_progress
    (regression: the worksheet-copy path must not silently lose its guard).

Note on state-bypass in test setUp:
  Job.objects.create(status=X) bypasses the state-machine check (self.pk is
  None at creation time, so full_clean skips the transition guard). This is the
  established test pattern — see test_materialize_worksheet.py.
"""

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import User, AccountingCategory
from apps.contacts.models import Contact
from apps.estimates.models import EstWorksheet
from apps.jobs.models import Job, Task, RateScheme
from apps.jobs.services import JobService, TaskService


def _make_scheme(name_suffix=''):
    """Create a minimal flat-fee RateScheme for tests that don't need billing."""
    code = f'DT{name_suffix[:5]}'.upper()
    ac, _ = AccountingCategory.objects.get_or_create(
        code=code, defaults={'name': f'Direct Task AC {name_suffix}'},
    )
    return RateScheme.objects.create(
        name=f'S-dt-{name_suffix}',
        algorithm=RateScheme.ENTERED_QTY,
        rate=Decimal('50'),
        unit_label='ea',
        accounting_category=ac,
    )


class DirectTaskCreateServiceTest(TestCase):
    """Unit tests for TaskService.create_direct on draft/pre-approval jobs."""

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Direct', last_name='Test')
        self.scheme = _make_scheme('svc1')

    def _draft_job(self, suffix=''):
        return Job.objects.create(
            job_number=f'DT-SVC-{suffix or "001"}',
            name='Draft Job',
            contact=self.contact,
            status=Job.STATUS_DRAFT,
        )

    def test_create_direct_on_draft_job(self):
        """TaskService.create_direct succeeds on a DRAFT job."""
        job = self._draft_job('draft')
        task = TaskService.create_direct(
            job=job,
            name='CAD',
            rate_scheme_id=self.scheme.pk,
            est_qty=Decimal('2'),
        )
        self.assertIsNotNone(task.pk)
        self.assertEqual(task.job, job)
        self.assertEqual(task.name, 'CAD')
        self.assertEqual(task.est_qty, Decimal('2'))
        self.assertEqual(task.rate_scheme, self.scheme)

    def test_create_direct_on_submitted_job(self):
        """TaskService.create_direct succeeds on a SUBMITTED job."""
        job = Job.objects.create(
            job_number='DT-SVC-sub', name='Submitted Job',
            contact=self.contact, status=Job.STATUS_SUBMITTED,
        )
        task = TaskService.create_direct(
            job=job,
            name='Design',
            rate_scheme_id=self.scheme.pk,
        )
        self.assertIsNotNone(task.pk)
        self.assertEqual(task.job, job)

    def test_create_direct_on_approved_job(self):
        """TaskService.create_direct still works on APPROVED jobs (no regression)."""
        job = Job.objects.create(
            job_number='DT-SVC-app', name='Approved Job',
            contact=self.contact, status=Job.STATUS_APPROVED,
        )
        task = TaskService.create_direct(
            job=job,
            name='Build',
            rate_scheme_id=self.scheme.pk,
        )
        self.assertIsNotNone(task.pk)

    def test_create_direct_rejected_on_on_hold_job(self):
        """TaskService.create_direct raises ValidationError on an on_hold job."""
        job = Job.objects.create(
            job_number='DT-SVC-hold', name='On Hold Job',
            contact=self.contact, status=Job.STATUS_ON_HOLD,
        )
        with self.assertRaises(ValidationError):
            TaskService.create_direct(
                job=job,
                name='Blocked',
                rate_scheme_id=self.scheme.pk,
            )

    def test_create_direct_requires_rate_scheme(self):
        """TaskService.create_direct raises ValidationError when rate_scheme_id is missing."""
        job = self._draft_job('nors')
        with self.assertRaises(ValidationError):
            TaskService.create_direct(
                job=job,
                name='No Scheme',
                rate_scheme_id=None,
            )

    def test_task_is_attached_to_job(self):
        """The created task is queryable via job.tasks (FK)."""
        job = self._draft_job('fk')
        TaskService.create_direct(
            job=job,
            name='Attach Test',
            rate_scheme_id=self.scheme.pk,
        )
        self.assertEqual(Task.objects.filter(job=job).count(), 1)


class DirectTaskCreateAPITest(TestCase):
    """API tests for POST /api/jobs/{id}/tasks/ on a draft job."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='dtworker', password='testpass')
        self.client.force_authenticate(user=self.user)

        self.contact = Contact.objects.create(first_name='API', last_name='Test')
        self.job = Job.objects.create(
            job_number='DT-API-001', name='Draft API Job',
            contact=self.contact, status=Job.STATUS_DRAFT,
        )
        self.scheme = _make_scheme('api1')

    def test_post_task_on_draft_job_returns_201(self):
        """POST /api/jobs/{id}/tasks/ on a DRAFT job returns 201."""
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/tasks/',
            {'name': 'CAD Work', 'rate_scheme': self.scheme.pk, 'est_qty': '2.00'},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['name'], 'CAD Work')
        self.assertEqual(Task.objects.filter(job=self.job).count(), 1)

    def test_post_task_on_draft_job_unauthenticated_returns_403(self):
        """Unauthenticated POST is rejected."""
        self.client.force_authenticate(user=None)
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/tasks/',
            {'name': 'Sneaky', 'rate_scheme': self.scheme.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_post_task_on_draft_job_any_authenticated_user(self):
        """Any authenticated user may add a Task to a job (IsAuthenticated only)."""
        other = User.objects.create_user(username='dtother', password='testpass')
        self.client.force_authenticate(user=other)
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/tasks/',
            {'name': 'Worker Task', 'rate_scheme': self.scheme.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_post_task_missing_rate_scheme_returns_400(self):
        """POST without rate_scheme returns 400."""
        response = self.client.post(
            f'/api/jobs/{self.job.pk}/tasks/',
            {'name': 'No Scheme'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_get_tasks_on_draft_job_returns_200(self):
        """GET /api/jobs/{id}/tasks/ on a DRAFT job returns the task list."""
        response = self.client.get(f'/api/jobs/{self.job.pk}/tasks/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])


class MaterializeWorksheetGateRegressionTest(TestCase):
    """Regression: materialize_worksheet_onto_job still gates on approved/in_progress.

    Ensures that relaxing create_direct did NOT accidentally remove the gate
    from the worksheet-copy path.
    """

    def setUp(self):
        self.contact = Contact.objects.create(first_name='Gate', last_name='Test')
        self.job = Job.objects.create(
            job_number='DT-GATE-001', name='Gate Test Job',
            contact=self.contact, status=Job.STATUS_DRAFT,
        )
        # EstWorksheet has no 'name' field — create with job only.
        self.worksheet = EstWorksheet.objects.create(job=self.job)

    def test_materialize_worksheet_onto_draft_job_is_rejected(self):
        """materialize_worksheet_onto_job raises ValidationError on a DRAFT job."""
        with self.assertRaises(ValidationError) as ctx:
            JobService.materialize_worksheet_onto_job(self.job, self.worksheet)
        self.assertIn('approved', str(ctx.exception).lower())

    def test_materialize_worksheet_onto_submitted_job_is_rejected(self):
        """materialize_worksheet_onto_job raises ValidationError on a SUBMITTED job."""
        job = Job.objects.create(
            job_number='DT-GATE-002', name='Submitted Gate',
            contact=self.contact, status=Job.STATUS_SUBMITTED,
        )
        ws = EstWorksheet.objects.create(job=job)
        with self.assertRaises(ValidationError):
            JobService.materialize_worksheet_onto_job(job, ws)

    def test_materialize_worksheet_onto_approved_job_succeeds(self):
        """materialize_worksheet_onto_job works on an APPROVED job (no regression)."""
        job = Job.objects.create(
            job_number='DT-GATE-003', name='Approved Gate',
            contact=self.contact, status=Job.STATUS_APPROVED,
        )
        ws = EstWorksheet.objects.create(job=job)
        # No PlanTasks to copy — should return 0 created, no error.
        result = JobService.materialize_worksheet_onto_job(job, ws)
        self.assertEqual(result['tasks_created'], 0)
        self.assertEqual(result['materials_created'], 0)

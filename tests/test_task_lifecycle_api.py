from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient
from apps.jobs.models import Task, Blep
from tests.base import BaseTestCase


class TaskLifecycleAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        from apps.core.models import User
        self.client = APIClient()
        self.user = User.objects.first()
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
            self.job.status = s
            self.job.save()
        self.task = Task.objects.create(
            job=self.job, name="Test task", rate_scheme_id=1,
        )

    def _create_user(self, username):
        from apps.core.models import User
        return User.objects.create_user(username=username, password='test')

    def test_complete_task(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        now = timezone.now()
        Blep.objects.create(
            task=self.task, user=self.user, start_time=now - timedelta(hours=1), end_time=now,
        )
        url = f'/api/tasks/{self.task.pk}/complete/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_COMPLETE)

    def test_complete_entered_qty_task_without_value_signals_needs_qty(self):
        # rate_scheme 2 in the fixture is entered_qty
        eq_task = Task.objects.create(
            job=self.job, name='CNC', rate_scheme_id=2,
        )
        resp = self.client.post(f'/api/tasks/{eq_task.pk}/complete/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.get('needs_actual_qty'))
        self.assertEqual(resp.data.get('unit_label'), 'minute')
        self.assertIsNone(resp.data.get('current_qty'))
        eq_task.refresh_from_db()
        self.assertNotEqual(eq_task.status, Task.STATUS_COMPLETE)

    def test_complete_entered_qty_task_with_add_qty_completes(self):
        eq_task = Task.objects.create(
            job=self.job, name='CNC', rate_scheme_id=2,
        )
        resp = self.client.post(
            f'/api/tasks/{eq_task.pk}/complete/',
            {'add_qty': '7'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data.get('status'), Task.STATUS_COMPLETE)
        eq_task.refresh_from_db()
        self.assertEqual(eq_task.status, Task.STATUS_COMPLETE)
        from decimal import Decimal
        self.assertEqual(eq_task.actual_qty, Decimal('7'))

    def test_complete_prompt_carries_running_total(self):
        """A task with qty on record still prompts (settle-up) and reports
        the accumulated total for the modal."""
        from decimal import Decimal
        eq_task = Task.objects.create(
            job=self.job, name='CNC', rate_scheme_id=2,
        )
        Task.objects.filter(pk=eq_task.pk).update(actual_qty=Decimal('9'))
        resp = self.client.post(f'/api/tasks/{eq_task.pk}/complete/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.get('needs_actual_qty'))
        self.assertEqual(Decimal(resp.data['current_qty']), Decimal('9'))
        eq_task.refresh_from_db()
        self.assertNotEqual(eq_task.status, Task.STATUS_COMPLETE)

    def test_complete_add_qty_increments_running_total(self):
        from decimal import Decimal
        eq_task = Task.objects.create(
            job=self.job, name='CNC', rate_scheme_id=2,
        )
        Task.objects.filter(pk=eq_task.pk).update(actual_qty=Decimal('9'))
        resp = self.client.post(
            f'/api/tasks/{eq_task.pk}/complete/',
            {'add_qty': '5'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        eq_task.refresh_from_db()
        self.assertEqual(eq_task.actual_qty, Decimal('14'))

    def test_complete_zero_add_qty_settles_positive_total(self):
        from decimal import Decimal
        eq_task = Task.objects.create(
            job=self.job, name='CNC', rate_scheme_id=2,
        )
        Task.objects.filter(pk=eq_task.pk).update(actual_qty=Decimal('3'))
        resp = self.client.post(
            f'/api/tasks/{eq_task.pk}/complete/',
            {'add_qty': '0'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data.get('status'), Task.STATUS_COMPLETE)

    def test_complete_invalid_add_qty_returns_400(self):
        eq_task = Task.objects.create(
            job=self.job, name='CNC', rate_scheme_id=2,
        )
        resp = self.client.post(
            f'/api/tasks/{eq_task.pk}/complete/',
            {'add_qty': 'garbage'}, format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_complete_elapsed_task_without_time_signals_needs_time(self):
        # self.task is rate_scheme 1 (elapsed_time) with no bleps logged.
        resp = self.client.post(f'/api/tasks/{self.task.pk}/complete/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.get('needs_time_logged'))
        self.task.refresh_from_db()
        self.assertNotEqual(self.task.status, Task.STATUS_COMPLETE)

    def test_block_task(self):
        url = f'/api/tasks/{self.task.pk}/block/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_BLOCKED)

    def test_block_task_with_reason(self):
        url = f'/api/tasks/{self.task.pk}/block/'
        resp = self.client.post(url, {'reason': 'Waiting on parts'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.blocked_reason, 'Waiting on parts')

    def test_block_task_reason_in_response(self):
        url = f'/api/tasks/{self.task.pk}/block/'
        resp = self.client.post(url, {'reason': 'Waiting on parts'}, format='json')
        self.assertEqual(resp.data['blocked_reason'], 'Waiting on parts')

    def test_block_with_own_open_session_closes_it_and_blocks(self):
        """The requester's own session never vetoes a block (elapsed-time:
        no settle prompt, the blep just closes)."""
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        blep = Blep.objects.create(
            task=self.task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        resp = self.client.post(
            f'/api/tasks/{self.task.pk}/block/',
            {'reason': 'saw down'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('conflict', resp.data)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_BLOCKED)
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)

    def test_block_own_entered_qty_session_settles_first(self):
        eq_task = Task.objects.create(
            job=self.job, name='CNC', rate_scheme_id=2,
        )
        Task.objects.filter(pk=eq_task.pk).update(status=Task.STATUS_IN_PROGRESS)
        Blep.objects.create(
            task=eq_task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        url = f'/api/tasks/{eq_task.pk}/block/'
        resp = self.client.post(url, {'reason': 'jam'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data.get('conflict'), 'prior_session_qty')
        eq_task.refresh_from_db()
        self.assertEqual(eq_task.status, Task.STATUS_IN_PROGRESS)
        # Flagged re-post proceeds.
        resp = self.client.post(
            url, {'reason': 'jam', 'prior_qty_handled': True}, format='json')
        self.assertEqual(resp.status_code, 200)
        eq_task.refresh_from_db()
        self.assertEqual(eq_task.status, Task.STATUS_BLOCKED)
        self.assertEqual(eq_task.blocked_reason, 'jam')

    def test_block_with_other_workers_session_returns_conflict(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        other = self._create_user('blk_other')
        Blep.objects.create(
            task=self.task, user=other,
            start_time=timezone.now() - timedelta(minutes=5),
        )
        resp = self.client.post(
            f'/api/tasks/{self.task.pk}/block/', {'reason': 'x'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data.get('conflict'), 'active_workers')
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)

    def test_unblock_task(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_BLOCKED)
        url = f'/api/tasks/{self.task.pk}/unblock/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)

    def test_cancel_task(self):
        url = f'/api/tasks/{self.task.pk}/cancel/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_CANCELLED)

    def test_cancel_prompts_for_own_open_entered_qty_session(self):
        from decimal import Decimal
        eq_task = Task.objects.create(
            job=self.job, name='CNC', rate_scheme_id=2,
        )
        Task.objects.filter(pk=eq_task.pk).update(
            status=Task.STATUS_IN_PROGRESS, actual_qty=Decimal('9'))
        Blep.objects.create(
            task=eq_task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        url = f'/api/tasks/{eq_task.pk}/cancel/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data.get('conflict'), 'prior_session_qty')
        eq_task.refresh_from_db()
        self.assertNotEqual(eq_task.status, Task.STATUS_CANCELLED)
        # Re-post with the flag: session closes, task cancels.
        resp2 = self.client.post(url, {'prior_qty_handled': True}, format='json')
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.data.get('status'), Task.STATUS_CANCELLED)
        eq_task.refresh_from_db()
        self.assertEqual(eq_task.status, Task.STATUS_CANCELLED)

    def test_start_work(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        url = f'/api/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('blep_id', resp.data)
        self.assertTrue(Blep.objects.filter(task=self.task, user=self.user).exists())

    def test_start_work_on_pending_task_auto_promotes(self):
        # Task is pending by default; start-work should transition it to
        # in_progress and create a Blep in one step.
        self.assertEqual(self.task.status, Task.STATUS_PENDING)
        url = f'/api/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('blep_id', resp.data)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)
        self.assertTrue(Blep.objects.filter(task=self.task, user=self.user).exists())

    def test_stop_work(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        # Over-minimum so stop-work CLOSES it (a sub-minimum blep is cancelled).
        Blep.objects.create(
            task=self.task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        url = f'/api/tasks/{self.task.pk}/stop-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        blep = Blep.objects.get(task=self.task, user=self.user)
        self.assertIsNotNone(blep.end_time)

    def _eq_task_with_open_blep(self, actual_qty=None, user=None):
        from decimal import Decimal
        eq_task = Task.objects.create(
            job=self.job, name='CNC', rate_scheme_id=2,
        )
        fields = {'status': Task.STATUS_IN_PROGRESS}
        if actual_qty is not None:
            fields['actual_qty'] = Decimal(actual_qty)
        Task.objects.filter(pk=eq_task.pk).update(**fields)
        blep = Blep.objects.create(
            task=eq_task, user=user or self.user,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        return eq_task, blep

    def test_stop_work_settles_first_on_entered_qty_session(self):
        """Own explicit stop on an ENTERED_QTY task returns the settle
        conflict and mutates NOTHING — the session keeps running until the
        prompt resolves (tracking the count is part of the work)."""
        from decimal import Decimal
        eq_task, blep = self._eq_task_with_open_blep(actual_qty='9')
        resp = self.client.post(f'/api/tasks/{eq_task.pk}/stop-work/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data.get('conflict'), 'prior_session_qty')
        self.assertEqual(resp.data['prior_task']['task_id'], eq_task.pk)
        self.assertEqual(resp.data.get('unit_label'), 'minute')
        self.assertEqual(Decimal(resp.data['current_qty']), Decimal('9'))
        blep.refresh_from_db()
        self.assertIsNone(blep.end_time)

    def test_stop_work_conflict_current_qty_null_when_unset(self):
        eq_task, blep = self._eq_task_with_open_blep()
        resp = self.client.post(f'/api/tasks/{eq_task.pk}/stop-work/')
        self.assertEqual(resp.data.get('conflict'), 'prior_session_qty')
        self.assertIsNone(resp.data.get('current_qty'))

    def test_stop_work_flag_with_add_qty_settles_atomically(self):
        """The flagged re-post carries the session count: one call applies
        the increment and closes the blep in the same transaction."""
        from decimal import Decimal
        eq_task, blep = self._eq_task_with_open_blep(actual_qty='9')
        resp = self.client.post(
            f'/api/tasks/{eq_task.pk}/stop-work/',
            {'prior_qty_handled': True, 'add_qty': '5'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('conflict', resp.data)
        eq_task.refresh_from_db()
        self.assertEqual(eq_task.actual_qty, Decimal('14'))
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)

    def test_stop_work_flag_without_add_qty_skips_the_entry(self):
        from decimal import Decimal
        eq_task, blep = self._eq_task_with_open_blep(actual_qty='9')
        resp = self.client.post(
            f'/api/tasks/{eq_task.pk}/stop-work/',
            {'prior_qty_handled': True}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        eq_task.refresh_from_db()
        self.assertEqual(eq_task.actual_qty, Decimal('9'))
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)

    def test_stop_work_invalid_add_qty_leaves_session_running(self):
        """A bad increment must not half-run: 400, no add, blep open."""
        from decimal import Decimal
        eq_task, blep = self._eq_task_with_open_blep(actual_qty='9')
        resp = self.client.post(
            f'/api/tasks/{eq_task.pk}/stop-work/',
            {'prior_qty_handled': True, 'add_qty': '-99'}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        eq_task.refresh_from_db()
        self.assertEqual(eq_task.actual_qty, Decimal('9'))
        blep.refresh_from_db()
        self.assertIsNone(blep.end_time)

    def test_stop_work_no_conflict_for_elapsed_task(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        Blep.objects.create(
            task=self.task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        resp = self.client.post(f'/api/tasks/{self.task.pk}/stop-work/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('conflict', resp.data)
        blep = Blep.objects.get(task=self.task, user=self.user)
        self.assertIsNotNone(blep.end_time)

    def test_stop_work_on_behalf_never_conflicts(self):
        """The manager stopping a worker's timer doesn't know the count."""
        worker = self._create_user('ob_eq_target')
        eq_task, blep = self._eq_task_with_open_blep(user=worker)
        resp = self.client.post(
            f'/api/tasks/{eq_task.pk}/stop-work/', {'on_behalf_of': worker.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('conflict', resp.data)
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)

    def test_start_work_on_behalf_attributes_blep_to_target(self):
        # self.user (admin/superuser) bypasses atom checks → acts as manager.
        worker = self._create_user('ob_target')
        url = f'/api/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url, {'on_behalf_of': worker.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'ok')
        blep = Blep.objects.get(task=self.task, end_time__isnull=True)
        self.assertEqual(blep.user, worker)
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee, worker)

    def test_start_work_on_behalf_without_manage_time_is_forbidden(self):
        plain = self._create_user('ob_plain_api')
        worker = self._create_user('ob_target2')
        client = APIClient()
        client.force_authenticate(user=plain)
        url = f'/api/tasks/{self.task.pk}/start-work/'
        resp = client.post(url, {'on_behalf_of': worker.pk})
        self.assertEqual(resp.status_code, 403)

    def test_stop_work_on_behalf_closes_targets_blep(self):
        worker = self._create_user('ob_stop_target')
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        # Over-minimum so the on-behalf stop CLOSES it (not cancels).
        Blep.objects.create(
            task=self.task, user=worker,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        url = f'/api/tasks/{self.task.pk}/stop-work/'
        resp = self.client.post(url, {'on_behalf_of': worker.pk})
        self.assertEqual(resp.status_code, 200)
        blep = Blep.objects.get(task=self.task, user=worker)
        self.assertIsNotNone(blep.end_time)

    def test_stop_work_on_behalf_without_manage_time_is_forbidden(self):
        plain = self._create_user('ob_plain_stop')
        worker = self._create_user('ob_stop_target2')
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        Blep.objects.create(task=self.task, user=worker, start_time=timezone.now())
        client = APIClient()
        client.force_authenticate(user=plain)
        url = f'/api/tasks/{self.task.pk}/stop-work/'
        resp = client.post(url, {'on_behalf_of': worker.pk})
        self.assertEqual(resp.status_code, 403)

    def test_start_work_conflict_response(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        other_user = self._create_user('otherworker')
        Blep.objects.create(task=self.task, user=other_user, start_time=timezone.now())
        url = f'/api/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('conflict', resp.data)

    def test_start_work_join(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        other_user = self._create_user('otherworker')
        Blep.objects.create(task=self.task, user=other_user, start_time=timezone.now())
        url = f'/api/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url, {'action': 'join'})
        self.assertEqual(resp.status_code, 200)
        # Both users should have open bleps
        self.assertEqual(
            Blep.objects.filter(task=self.task, end_time__isnull=True).count(), 2
        )

    def test_start_work_takeover(self):
        from datetime import timedelta
        from apps.core.models import Shift
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        other_user = self._create_user('otherworker')
        now = timezone.now()
        # Enclosing shift + over-minute displaced blep so takeover CLOSES (real
        # work), rather than cancelling a sub-minute accidental start.
        Shift.objects.create(user=other_user, start_time=now - timedelta(days=1))
        Blep.objects.create(
            task=self.task, user=other_user,
            start_time=now - timedelta(minutes=30),
        )
        url = f'/api/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url, {'action': 'takeover'})
        self.assertEqual(resp.status_code, 200)
        # Other user's real-work blep should be closed (still exists)
        other_blep = Blep.objects.get(task=self.task, user=other_user)
        self.assertIsNotNone(other_blep.end_time)
        # Current user should have open blep
        my_blep = Blep.objects.get(task=self.task, user=self.user)
        self.assertIsNone(my_blep.end_time)

    def test_start_work_prior_session_conflict_and_flag(self):
        from decimal import Decimal
        eq_task = Task.objects.create(
            job=self.job, name='CNC', rate_scheme_id=2,
        )
        Task.objects.filter(pk=eq_task.pk).update(
            status=Task.STATUS_IN_PROGRESS, actual_qty=Decimal('9'))
        Blep.objects.create(
            task=eq_task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        url = f'/api/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data.get('conflict'), 'prior_session_qty')
        self.assertEqual(resp.data['prior_task']['task_id'], eq_task.pk)
        # Re-post with the flag: prior session closes, new blep starts.
        resp2 = self.client.post(url, {'prior_qty_handled': True}, format='json')
        self.assertEqual(resp2.status_code, 200)
        self.assertIn('blep_id', resp2.data)
        blep = Blep.objects.get(task=eq_task, user=self.user)
        self.assertIsNotNone(blep.end_time)

    def test_invalid_transition_returns_400(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_COMPLETE)
        url = f'/api/tasks/{self.task.pk}/start-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.data)

    def test_wrong_task_returns_404(self):
        url = f'/api/tasks/99999/start-work/'
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)


class TaskSerializerStatusTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from apps.core.models import User
        from apps.jobs.models import Job
        self.client = APIClient()
        self.user = User.objects.first()
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.first()
        for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
            self.job.status = s
            self.job.save()
        self.task = Task.objects.create(
            job=self.job, name="Test task", rate_scheme_id=1,
        )

    def test_task_list_includes_status(self):
        url = f'/api/jobs/{self.job.pk}/tasks/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('status', resp.data[0])
        self.assertEqual(resp.data[0]['status'], Task.STATUS_PENDING)

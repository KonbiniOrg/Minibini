from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, Shift


class ShiftAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.create_user(username='api_shift_u', password='x')
        self.client.force_authenticate(user=self.user)

    def test_clock_in_then_active_then_clock_out(self):
        r = self.client.post('/api/shifts/clock-in/', {}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        a = self.client.get('/api/shifts/active/')
        self.assertEqual(a.status_code, 200)
        self.assertIsNotNone(a.data['shift'])
        r2 = self.client.post('/api/shifts/clock-out/', {}, format='json')
        self.assertEqual(r2.status_code, 200, r2.data)
        a2 = self.client.get('/api/shifts/active/')
        self.assertIsNone(a2.data['shift'])

    def _open_entered_qty_session(self, user):
        """Open a shift + an open blep on an ENTERED_QTY task for `user`.
        Fixture rate scheme 2 is entered_qty (unit 'minute')."""
        from decimal import Decimal
        from apps.jobs.models import Job, Task, Blep
        from apps.core.models import Shift
        job = Job.objects.first()
        task = Task.objects.create(name='CNC', job=job, rate_scheme_id=2)
        Task.objects.filter(pk=task.pk).update(
            status=Task.STATUS_IN_PROGRESS, actual_qty=Decimal('9'))
        Shift.objects.create(
            user=user, start_time=timezone.now() - timedelta(hours=2))
        blep = Blep.objects.create(
            task=task, user=user,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        return task, blep

    def test_clock_out_prompts_for_open_entered_qty_session(self):
        from decimal import Decimal
        task, blep = self._open_entered_qty_session(self.user)
        r = self.client.post('/api/shifts/clock-out/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data.get('conflict'), 'prior_session_qty')
        self.assertEqual(r.data['prior_task']['task_id'], task.pk)
        self.assertEqual(Decimal(r.data['current_qty']), Decimal('9'))
        # Nothing mutated: shift and blep still open.
        blep.refresh_from_db()
        self.assertIsNone(blep.end_time)
        a = self.client.get('/api/shifts/active/')
        self.assertIsNotNone(a.data['shift'])

    def test_clock_out_with_flag_closes_blep_and_shift(self):
        task, blep = self._open_entered_qty_session(self.user)
        r = self.client.post(
            '/api/shifts/clock-out/', {'prior_qty_handled': True},
            format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertNotIn('conflict', r.data)
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)
        a = self.client.get('/api/shifts/active/')
        self.assertIsNone(a.data['shift'])

    def test_clock_out_no_prompt_for_elapsed_session(self):
        from apps.jobs.models import Job, Task, Blep
        from apps.core.models import Shift
        job = Job.objects.first()
        task = Task.objects.create(name='Labor', job=job, rate_scheme_id=1)
        Task.objects.filter(pk=task.pk).update(status=Task.STATUS_IN_PROGRESS)
        Shift.objects.create(
            user=self.user, start_time=timezone.now() - timedelta(hours=2))
        Blep.objects.create(
            task=task, user=self.user,
            start_time=timezone.now() - timedelta(minutes=30),
        )
        r = self.client.post('/api/shifts/clock-out/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertNotIn('conflict', r.data)

    def test_manager_clock_out_other_user_never_prompts(self):
        from django.contrib.auth.models import Permission
        mgr = User.objects.create_user(username='api_shift_mgr2', password='x')
        mgr.user_permissions.add(Permission.objects.get(
            codename='can_manage_time', content_type__app_label='core'))
        mgr = User.objects.get(pk=mgr.pk)
        task, blep = self._open_entered_qty_session(self.user)
        self.client.force_authenticate(user=mgr)
        r = self.client.post(
            '/api/shifts/clock-out/', {'user': self.user.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertNotIn('conflict', r.data)
        blep.refresh_from_db()
        self.assertIsNotNone(blep.end_time)

    def test_double_clock_in_400(self):
        self.client.post('/api/shifts/clock-in/', {}, format='json')
        r = self.client.post('/api/shifts/clock-in/', {}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_list_own_shifts_with_since(self):
        Shift.objects.create(user=self.user, start_time=timezone.now() - timedelta(hours=2),
                             end_time=timezone.now() - timedelta(hours=1))
        since = (timezone.now() - timedelta(days=1)).isoformat()
        r = self.client.get(f'/api/shifts/?user=me&since={since}')
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.data.get('results', r.data)), 1)

    def test_patch_recent_own_shift(self):
        s = Shift.objects.create(user=self.user, start_time=timezone.now() - timedelta(hours=3),
                                 end_time=timezone.now() - timedelta(hours=1))
        new_start = (timezone.now() - timedelta(hours=4)).isoformat()
        r = self.client.patch(f'/api/shifts/{s.pk}/',
                              {'start_time': new_start,
                               'end_time': s.end_time.isoformat()}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_manager_clock_unknown_user_404(self):
        from django.contrib.auth.models import Permission
        mgr = User.objects.create_user(username='api_shift_mgr', password='x')
        mgr.user_permissions.add(Permission.objects.get(
            codename='can_manage_time', content_type__app_label='core'))
        mgr = User.objects.get(pk=mgr.pk)
        self.client.force_authenticate(user=mgr)
        r = self.client.post('/api/shifts/clock-in/', {'user': 99999999}, format='json')
        self.assertEqual(r.status_code, 404, r.data)

    def test_invalid_since_is_ignored(self):
        r = self.client.get('/api/shifts/?user=me&since=not-a-date')
        self.assertEqual(r.status_code, 200, r.data)

    def test_since_returns_overnight_shift_started_before_since(self):
        """A shift that STARTED before `since` but is still active at/after it
        (e.g. an overnight / multi-day shift) must be returned. `since` means
        'shifts not yet ended as of this time', not 'shifts starting after it'.
        Regression: the filter used start_time__gte, hiding such shifts and
        falsely blocking blep entry with 'no shift covers this time'."""
        now = timezone.now()
        Shift.objects.create(
            user=self.user,
            start_time=now - timedelta(days=2),   # started 2 days ago
            end_time=now - timedelta(hours=1),    # ended an hour ago
        )
        since = (now - timedelta(days=1)).isoformat()  # after the start
        r = self.client.get(f'/api/shifts/?user=me&since={since}')
        self.assertEqual(r.status_code, 200, r.data)
        rows = r.data.get('results', r.data)
        self.assertEqual(len(rows), 1)

    def test_since_returns_open_shift_started_before_since(self):
        """An open (end_time=None) shift started before `since` is still running,
        so it must be returned regardless of how long ago it started."""
        now = timezone.now()
        Shift.objects.create(
            user=self.user,
            start_time=now - timedelta(days=3),
            end_time=None,
        )
        since = (now - timedelta(days=1)).isoformat()
        r = self.client.get(f'/api/shifts/?user=me&since={since}')
        self.assertEqual(r.status_code, 200, r.data)
        rows = r.data.get('results', r.data)
        self.assertEqual(len(rows), 1)

    def test_since_excludes_shift_that_ended_before_since(self):
        """A shift that both started AND ended before `since` is not active in
        the window and must be excluded."""
        now = timezone.now()
        Shift.objects.create(
            user=self.user,
            start_time=now - timedelta(days=3),
            end_time=now - timedelta(days=2),   # ended before `since`
        )
        since = (now - timedelta(days=1)).isoformat()
        r = self.client.get(f'/api/shifts/?user=me&since={since}')
        self.assertEqual(r.status_code, 200, r.data)
        rows = r.data.get('results', r.data)
        self.assertEqual(len(rows), 0)

    def test_patch_open_shift_without_end_does_not_500(self):
        """Regression: PATCHing an open (end_time=None) shift without supplying
        an end_time passes end_time=None into ShiftService.update. The enclosure
        check used to crash on max(None, datetime). Should succeed and keep the
        shift open."""
        s = Shift.objects.create(
            user=self.user, start_time=timezone.now() - timedelta(hours=2),
            end_time=None)
        new_start = (timezone.now() - timedelta(hours=3)).isoformat()
        r = self.client.patch(f'/api/shifts/{s.pk}/',
                              {'start_time': new_start}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        s.refresh_from_db()
        self.assertIsNone(s.end_time)  # still open

    def test_unenclosed_bleps_handles_open_shift_end(self):
        """The pure helper must treat a None shift end as an unbounded upper
        bound (open/ongoing shift) rather than crashing."""
        from apps.core.time_integrity import unenclosed_bleps_for_shift
        now = timezone.now()
        start = now - timedelta(hours=2)
        # New end None, old span closed (the exact server-error scenario).
        self.assertEqual(
            unenclosed_bleps_for_shift(self.user, start, None,
                                       also_span=(start, now)), [])
        # Both ends open (defensive).
        self.assertEqual(
            unenclosed_bleps_for_shift(self.user, start, None,
                                       also_span=(start, None)), [])

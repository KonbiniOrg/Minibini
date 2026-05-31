from django.contrib.auth.models import Permission
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, Shift, ShiftChangeRequest


class ChangeRequestAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.worker = User.objects.create_user(username='cr_api_w', password='x')
        self.mgr = User.objects.create_user(username='cr_api_m', password='x')
        self.mgr.user_permissions.add(Permission.objects.get(
            codename='can_manage_time', content_type__app_label='core'))
        self.mgr = User.objects.get(pk=self.mgr.pk)
        self.now = timezone.now().replace(microsecond=0)

    def test_worker_files_shift_request(self):
        self.client.force_authenticate(user=self.worker)
        r = self.client.post('/api/shift-change-requests/', {
            'requested_start': (self.now - timedelta(hours=40)).isoformat(),
            'requested_end': (self.now - timedelta(hours=32)).isoformat(),
            'reason': 'forgot to clock in',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['status'], 'pending')

    def test_reason_required(self):
        self.client.force_authenticate(user=self.worker)
        r = self.client.post('/api/shift-change-requests/', {
            'requested_start': self.now.isoformat(),
            'requested_end': self.now.isoformat(), 'reason': '',
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_manager_approves(self):
        req = ShiftChangeRequest.objects.create(
            requester=self.worker,
            requested_start=self.now - timedelta(hours=40),
            requested_end=self.now - timedelta(hours=32), reason='x')
        self.client.force_authenticate(user=self.mgr)
        r = self.client.post(f'/api/shift-change-requests/{req.pk}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')

    def test_worker_cannot_approve(self):
        req = ShiftChangeRequest.objects.create(
            requester=self.worker, requested_start=self.now, requested_end=self.now, reason='x')
        self.client.force_authenticate(user=self.worker)
        r = self.client.post(f'/api/shift-change-requests/{req.pk}/approve/', {}, format='json')
        self.assertIn(r.status_code, (403, 401))

    def test_blep_create_request_requires_task(self):
        self.client.force_authenticate(user=self.worker)
        r = self.client.post('/api/blep-change-requests/', {
            'requested_start': (self.now - timedelta(hours=40)).isoformat(),
            'requested_end': (self.now - timedelta(hours=39)).isoformat(),
            'reason': 'missing entry',
        }, format='json')
        self.assertEqual(r.status_code, 400, r.data)

    def test_worker_cannot_target_another_users_shift(self):
        from apps.core.models import Shift
        other = User.objects.create_user(username='cr_api_other', password='x')
        s = Shift.objects.create(user=other,
                                 start_time=self.now - timedelta(hours=40),
                                 end_time=self.now - timedelta(hours=39))
        self.client.force_authenticate(user=self.worker)
        r = self.client.post('/api/shift-change-requests/', {
            'shift': s.shift_id,
            'requested_start': (self.now - timedelta(hours=40)).isoformat(),
            'requested_end': (self.now - timedelta(hours=38)).isoformat(),
            'reason': 'not mine',
        }, format='json')
        self.assertEqual(r.status_code, 403, r.data)

    def test_worker_files_conflicting_blep_request_is_allowed(self):
        # A request whose new time no shift covers must still be ALLOWED
        # (warn-and-flag) — the worker can't widen the shift; the manager
        # reconciles it on review. This is the agreed warn-and-allow contract.
        from apps.jobs.models import Job, Task, Blep
        job = Job.objects.first()
        task = Task.objects.create(name='T', job=job, rate_scheme_id=1)
        blep = Blep.objects.create(
            task=task, user=self.worker,
            start_time=self.now - timedelta(hours=3),
            end_time=self.now - timedelta(hours=2))
        self.client.force_authenticate(user=self.worker)
        r = self.client.post('/api/blep-change-requests/', {
            'blep': blep.blep_id,
            'task': task.pk,
            'requested_start': (self.now - timedelta(hours=50)).isoformat(),
            'requested_end': (self.now - timedelta(hours=49)).isoformat(),
            'reason': 'logged on the wrong day',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['has_known_conflict'])
        self.assertEqual(r.data['status'], 'pending')

    def test_shift_request_conflict_surfaces_offending_blep(self):
        from apps.jobs.models import Job, Task, Blep
        job = Job.objects.first()
        task = Task.objects.create(name='Demo', job=job, rate_scheme_id=1)
        shift = Shift.objects.create(user=self.worker,
                                     start_time=self.now - timedelta(hours=5),
                                     end_time=self.now - timedelta(hours=1))
        blep = Blep.objects.create(task=task, user=self.worker,
                                   start_time=self.now - timedelta(hours=4),
                                   end_time=self.now - timedelta(hours=3))
        req = ShiftChangeRequest.objects.create(
            requester=self.worker, shift=shift,
            requested_start=self.now - timedelta(hours=5),
            requested_end=self.now - timedelta(hours=3, minutes=30),  # drops the blep
            reason='left early')
        self.client.force_authenticate(user=self.mgr)
        r = self.client.get('/api/shift-change-requests/?status=pending')
        rows = r.data.get('results', r.data)
        row = next(x for x in rows if x['request_id'] == req.pk)
        self.assertTrue(any(c['type'] == 'blep' and c['id'] == blep.blep_id
                            for c in row['conflicts']), row['conflicts'])

    def test_blep_request_conflict_surfaces_overlapping_shift(self):
        from apps.jobs.models import Job, Task, Blep, BlepChangeRequest
        job = Job.objects.first()
        task = Task.objects.create(name='Demo2', job=job, rate_scheme_id=1)
        shift = Shift.objects.create(user=self.worker,
                                     start_time=self.now - timedelta(hours=3),
                                     end_time=self.now - timedelta(hours=1))
        blep = Blep.objects.create(task=task, user=self.worker,
                                   start_time=self.now - timedelta(hours=2, minutes=30),
                                   end_time=self.now - timedelta(hours=2))
        req = BlepChangeRequest.objects.create(
            requester=self.worker, blep=blep, task=task,
            requested_start=self.now - timedelta(hours=2, minutes=30),
            requested_end=self.now - timedelta(minutes=30),  # past shift end -> not enclosed
            reason='ran later')
        self.client.force_authenticate(user=self.mgr)
        r = self.client.get('/api/blep-change-requests/?status=pending')
        rows = r.data.get('results', r.data)
        row = next(x for x in rows if x['request_id'] == req.pk)
        self.assertTrue(any(c['type'] == 'shift' and c['id'] == shift.shift_id
                            for c in row['conflicts']), row['conflicts'])

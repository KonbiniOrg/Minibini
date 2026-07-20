"""Per-user shift no-overlap rule.

You can't be clocked in twice at the same time: two shifts of one user may
never overlap. Spans are half-open — a shift ending exactly when the next
starts (split shifts) is legal. A null end_time (open shift) is unbounded.
Enforced in ShiftService.create / update / clock_in, which also covers the
change-request approve path (apply_requested routes through create/update).
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.core.models import Shift, ShiftChangeRequest, User
from apps.core.services import ShiftService, TimeChangeRequestService


class ShiftOverlapTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Permission
        self.mgr = User.objects.create_user(username='ovl_mgr', password='x')
        self.mgr.user_permissions.add(
            Permission.objects.get(codename='can_manage_time'))
        self.mgr = User.objects.get(pk=self.mgr.pk)  # fresh perm cache
        self.worker = User.objects.create_user(username='ovl_w', password='x')
        self.now = timezone.now().replace(second=0, microsecond=0)

    def _shift(self, user, start_h_ago, end_h_ago=None):
        return Shift.objects.create(
            user=user,
            start_time=self.now - timedelta(hours=start_h_ago),
            end_time=(self.now - timedelta(hours=end_h_ago))
            if end_h_ago is not None else None,
        )

    # ── create ───────────────────────────────────────────────────
    def test_create_enclosed_shift_rejected(self):
        self._shift(self.worker, 8, 1)
        with self.assertRaises(ValidationError):
            ShiftService.create(self.worker, actor=self.mgr,
                                start_time=self.now - timedelta(hours=6),
                                end_time=self.now - timedelta(hours=3))

    def test_create_partial_overlap_rejected(self):
        self._shift(self.worker, 8, 4)
        with self.assertRaises(ValidationError):
            ShiftService.create(self.worker, actor=self.mgr,
                                start_time=self.now - timedelta(hours=5),
                                end_time=self.now - timedelta(hours=2))

    def test_create_overlapping_open_shift_rejected(self):
        self._shift(self.worker, 2)  # open
        with self.assertRaises(ValidationError):
            ShiftService.create(self.worker, actor=self.mgr,
                                start_time=self.now - timedelta(hours=1),
                                end_time=self.now)

    def test_create_adjacent_shift_allowed(self):
        # Half-open spans: ending exactly when the next starts is a split
        # shift, not an overlap.
        self._shift(self.worker, 8, 4)
        ShiftService.create(self.worker, actor=self.mgr,
                            start_time=self.now - timedelta(hours=4),
                            end_time=self.now - timedelta(hours=2))
        self.assertEqual(self.worker.shifts.count(), 2)

    def test_create_disjoint_shift_allowed(self):
        self._shift(self.worker, 8, 6)
        ShiftService.create(self.worker, actor=self.mgr,
                            start_time=self.now - timedelta(hours=4),
                            end_time=self.now - timedelta(hours=2))
        self.assertEqual(self.worker.shifts.count(), 2)

    def test_other_users_shifts_do_not_conflict(self):
        self._shift(self.mgr, 8, 1)
        ShiftService.create(self.worker, actor=self.mgr,
                            start_time=self.now - timedelta(hours=6),
                            end_time=self.now - timedelta(hours=3))
        self.assertEqual(self.worker.shifts.count(), 1)

    # ── update ───────────────────────────────────────────────────
    def test_edit_widening_over_open_shift_rejected(self):
        open_shift = self._shift(self.worker, 2)  # open
        closed = self._shift(self.worker, 5, 4)
        with self.assertRaises(ValidationError):
            ShiftService.update(closed, actor=self.mgr,
                                start_time=self.now - timedelta(hours=5),
                                end_time=self.now)
        closed.refresh_from_db()
        self.assertEqual(closed.end_time, self.now - timedelta(hours=4))
        self.assertIsNone(open_shift.end_time)

    def test_edit_excludes_self(self):
        s = self._shift(self.worker, 5, 4)
        ShiftService.update(s, actor=self.mgr,
                            start_time=self.now - timedelta(hours=5),
                            end_time=self.now - timedelta(hours=3))
        s.refresh_from_db()
        self.assertEqual(s.end_time, self.now - timedelta(hours=3))

    # ── clock_in ─────────────────────────────────────────────────
    def test_clock_in_inside_closed_shift_rejected(self):
        # A closed shift already covers "now" (manager pre-entered it).
        self._shift(self.worker, 1, None)
        # close it in the future relative to now
        s = self.worker.shifts.first()
        s.end_time = self.now + timedelta(hours=1)
        s.save()
        with self.assertRaises(ValidationError):
            ShiftService.clock_in(self.worker)

    # ── change-request approve path ──────────────────────────────
    def test_approve_create_request_that_overlaps_rejected(self):
        self._shift(self.worker, 8, 1)
        req = ShiftChangeRequest.objects.create(
            requester=self.worker,
            requested_start=self.now - timedelta(hours=6),
            requested_end=self.now - timedelta(hours=3),
            reason='forgot to clock in',
        )
        with self.assertRaises(ValidationError):
            TimeChangeRequestService.approve(req, reviewer=self.mgr)
        req.refresh_from_db()
        self.assertEqual(req.status, ShiftChangeRequest.STATUS_PENDING)

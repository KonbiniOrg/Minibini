from django.utils import timezone
from datetime import timedelta

from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.jobs.models import Job, Task, Blep
from apps.jobs.services import BlepService
from apps.core.timeutils import floor_to_minute


class BlepServicePrimitivesTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='Task', job=self.job, rate_scheme_id=1)
        self.other_task = Task.objects.create(name='Other', job=self.job, rate_scheme_id=1)
        self.user = User.objects.get(username='admin')
        self.other_user = User.objects.create_user(username='worker2', password='x')

    def test_create_returns_open_blep(self):
        blep = BlepService._create(self.task, self.user)
        self.assertIsNotNone(blep.start_time)
        self.assertIsNone(blep.end_time)
        self.assertEqual(blep.user, self.user)
        self.assertEqual(blep.task, self.task)

    def test_create_with_explicit_times(self):
        start = timezone.now() - timedelta(hours=2)
        end = timezone.now() - timedelta(hours=1)
        blep = BlepService._create(self.task, self.user, start_time=start, end_time=end)
        self.assertEqual(blep.start_time, floor_to_minute(start))
        self.assertEqual(blep.end_time, floor_to_minute(end))

    def test_close_open_by_user_closes_all_user_bleps(self):
        # Backdate well past the minimum so these are CLOSED (not cancelled).
        past = timezone.now() - timedelta(minutes=30)
        b1 = Blep.objects.create(task=self.task, user=self.user, start_time=past)
        b2 = Blep.objects.create(task=self.other_task, user=self.user, start_time=past)
        # Another user's blep should NOT be closed.
        other = Blep.objects.create(task=self.task, user=self.other_user, start_time=past)
        BlepService._close_open(user=self.user)
        b1.refresh_from_db(); b2.refresh_from_db(); other.refresh_from_db()
        self.assertIsNotNone(b1.end_time)
        self.assertIsNotNone(b2.end_time)
        self.assertIsNone(other.end_time)

    def test_close_open_by_user_and_task_scoped(self):
        past = timezone.now() - timedelta(minutes=30)
        on_task = Blep.objects.create(task=self.task, user=self.user, start_time=past)
        other_task_blep = Blep.objects.create(task=self.other_task, user=self.user, start_time=past)
        BlepService._close_open(user=self.user, task=self.task)
        on_task.refresh_from_db(); other_task_blep.refresh_from_db()
        self.assertIsNotNone(on_task.end_time)
        self.assertIsNone(other_task_blep.end_time)

    def test_close_open_by_task_closes_all_workers(self):
        past = timezone.now() - timedelta(minutes=30)
        mine = Blep.objects.create(task=self.task, user=self.user, start_time=past)
        theirs = Blep.objects.create(task=self.task, user=self.other_user, start_time=past)
        BlepService._close_open(task=self.task)
        mine.refresh_from_db(); theirs.refresh_from_db()
        self.assertIsNotNone(mine.end_time)
        self.assertIsNotNone(theirs.end_time)

    def test_close_open_requires_filter(self):
        with self.assertRaises(ValueError):
            BlepService._close_open()


from django.core.exceptions import ValidationError
from apps.jobs.services import BlepPermissionError


class CreateHistoricalTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
            self.job.status = s
            self.job.save()
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1)
        self.user = User.objects.create_user(username='worker1_historical', password='x')
        self.manager = User.objects.create_user(username='m', password='x')
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(codename='can_manage_time', content_type__app_label='core')
        self.manager.user_permissions.add(perm)
        self.manager = User.objects.get(pk=self.manager.pk)
        self.other_user = User.objects.create_user(username='worker2', password='x')
        now = timezone.now()
        for u in (self.user, self.manager, self.other_user):
            Shift.objects.create(
                user=u,
                start_time=now - timedelta(days=3),
                end_time=now + timedelta(days=1),
            )

    def _times(self, hours_ago_start, hours_ago_end):
        now = timezone.now()
        return (now - timedelta(hours=hours_ago_start),
                now - timedelta(hours=hours_ago_end))

    def test_create_for_self_within_30h(self):
        start, end = self._times(2, 1)
        blep = BlepService.create_historical(self.user, self.task, start, end)
        self.assertEqual(blep.user, self.user)
        self.assertEqual(blep.start_time, floor_to_minute(start))
        self.assertEqual(blep.end_time, floor_to_minute(end))

    def test_create_for_self_25h_old_is_within_window(self):
        # 25h is inside the 30h self-edit window (was outside the old 24h window).
        start, end = self._times(25, 24)
        blep = BlepService.create_historical(self.user, self.task, start, end)
        self.assertEqual(blep.user, self.user)

    def test_create_for_self_older_than_30h_requires_manage_time(self):
        start, end = self._times(48, 47)
        with self.assertRaises(BlepPermissionError):
            BlepService.create_historical(self.user, self.task, start, end)

    def test_create_for_self_older_than_30h_manager_allowed(self):
        start, end = self._times(48, 47)
        blep = BlepService.create_historical(self.manager, self.task, start, end)
        self.assertEqual(blep.user, self.manager)

    def test_create_for_other_user_requires_manage_time(self):
        start, end = self._times(2, 1)
        with self.assertRaises(BlepPermissionError):
            BlepService.create_historical(
                self.user, self.task, start, end, target_user=self.other_user,
            )

    def test_create_for_other_user_as_manager(self):
        start, end = self._times(2, 1)
        blep = BlepService.create_historical(
            self.manager, self.task, start, end, target_user=self.other_user,
        )
        self.assertEqual(blep.user, self.other_user)

    # Obsolete post-split: Blep.task is type-enforced to Task (WO-only).

    def test_create_rejects_end_before_start(self):
        start, end = self._times(1, 2)  # end < start
        with self.assertRaises(ValidationError):
            BlepService.create_historical(self.user, self.task, start, end)

    def test_create_rejects_overlap_with_existing_user_blep(self):
        now = timezone.now()
        Blep.objects.create(
            task=self.task, user=self.user,
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(hours=1),
        )
        overlap_start = now - timedelta(hours=2)
        overlap_end = now - timedelta(minutes=30)
        with self.assertRaises(ValidationError):
            BlepService.create_historical(
                self.user, self.task, overlap_start, overlap_end,
            )

    def test_create_allows_overlap_across_different_users(self):
        now = timezone.now()
        Blep.objects.create(
            task=self.task, user=self.other_user,
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(hours=1),
        )
        start = now - timedelta(hours=2)
        end = now - timedelta(minutes=30)
        blep = BlepService.create_historical(self.user, self.task, start, end)
        self.assertIsNotNone(blep)

    def test_create_historical_promotes_pending_task(self):
        self.assertEqual(self.task.status, Task.STATUS_PENDING)
        start, end = self._times(2, 1)
        BlepService.create_historical(self.user, self.task, start, end)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)

    def test_create_historical_leaves_in_progress_task_unchanged(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        start, end = self._times(2, 1)
        BlepService.create_historical(self.user, self.task, start, end)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_IN_PROGRESS)

    def test_create_historical_does_not_reopen_complete_task(self):
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_COMPLETE)
        start, end = self._times(2, 1)
        BlepService.create_historical(self.user, self.task, start, end)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_COMPLETE)

    def test_create_historical_consumes_materials_on_pending_task(self):
        from decimal import Decimal
        from apps.inventory.models import InventoryItem, Material
        from apps.core.models import AccountingCategory
        cat = AccountingCategory.objects.first()
        # Established + stocked: consume() now refuses provisional materials, so
        # the sweep can only consume a material with a received lot.
        pli = InventoryItem.objects.create(
            code='BLEP-H1', accounting_category=cat, qty_on_hand=Decimal('5'),
        )
        mat = Material.objects.create(
            job=self.job, task=self.task, description='Test Material',
            inventory_item=pli, quantity=Decimal('2'),
            accounting_category=cat,
        )
        self.assertEqual(mat.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        start, end = self._times(2, 1)
        BlepService.create_historical(self.user, self.task, start, end)
        mat.refresh_from_db()
        self.assertEqual(mat.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)

    def test_create_historical_on_in_progress_task_sweeps_pending_materials(self):
        # A blep means work is happening — a hand-added blep on a started task
        # consumes the task's pending materials (the blep-start sweep), the
        # same as a live start.
        from decimal import Decimal
        from apps.inventory.models import InventoryItem, Material
        from apps.core.models import AccountingCategory
        cat = AccountingCategory.objects.first()
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        # Established + stocked: the blep-start sweep can only consume a material
        # with a received lot (consume() refuses provisional materials).
        pli = InventoryItem.objects.create(
            code='BLEP-H2', accounting_category=cat, qty_on_hand=Decimal('5'),
        )
        mat = Material.objects.create(
            job=self.job, task=self.task, description='M',
            inventory_item=pli, quantity=Decimal('2'),
            accounting_category=cat,
        )
        start, end = self._times(2, 1)
        BlepService.create_historical(self.user, self.task, start, end)
        mat.refresh_from_db()
        self.assertEqual(mat.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)

    def test_create_historical_assigns_unassigned_pending_task(self):
        # Mirrors start_work: the first worker whose blep promotes the task
        # becomes its assignee.
        self.assertIsNone(self.task.assignee_id)
        start, end = self._times(2, 1)
        BlepService.create_historical(self.user, self.task, start, end)
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee_id, self.user.pk)

    def test_create_historical_for_other_assigns_target_not_actor(self):
        start, end = self._times(2, 1)
        BlepService.create_historical(
            self.manager, self.task, start, end, target_user=self.other_user,
        )
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee_id, self.other_user.pk)

    def test_create_historical_keeps_existing_assignee(self):
        Task.objects.filter(pk=self.task.pk).update(assignee=self.other_user)
        self.task.refresh_from_db()
        start, end = self._times(2, 1)
        BlepService.create_historical(self.user, self.task, start, end)
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee_id, self.other_user.pk)

    def test_create_historical_on_in_progress_task_does_not_assign(self):
        # Assignment rides the pending→in_progress promotion only — a blep on
        # an already-started task is "helping" (same rule as start_work).
        Task.objects.filter(pk=self.task.pk).update(status=Task.STATUS_IN_PROGRESS)
        self.task.refresh_from_db()
        start, end = self._times(2, 1)
        BlepService.create_historical(self.user, self.task, start, end)
        self.task.refresh_from_db()
        self.assertIsNone(self.task.assignee_id)


class UpdateBlepTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1)
        self.user = User.objects.create_user(username='worker1_update', password='x')
        from django.contrib.auth.models import Permission
        self.manager = User.objects.create_user(username='m', password='x')
        perm = Permission.objects.get(codename='can_manage_time', content_type__app_label='core')
        self.manager.user_permissions.add(perm)
        self.manager = User.objects.get(pk=self.manager.pk)
        self.other = User.objects.create_user(username='w2', password='x')
        now = timezone.now()
        for u in (self.user, self.manager, self.other):
            Shift.objects.create(
                user=u,
                start_time=now - timedelta(days=3),
                end_time=now + timedelta(days=1),
            )

    def _blep(self, user, hours_ago_start=2, hours_ago_end=1):
        now = timezone.now()
        return Blep.objects.create(
            task=self.task, user=user,
            start_time=now - timedelta(hours=hours_ago_start),
            end_time=now - timedelta(hours=hours_ago_end),
        )

    def test_update_own_recent_blep(self):
        blep = self._blep(self.user)
        new_end = blep.end_time + timedelta(minutes=15)
        updated = BlepService.update(blep, self.user, end_time=new_end)
        self.assertEqual(updated.end_time, new_end)

    def test_update_own_25h_old_blep_is_within_window(self):
        # 25h is inside the 30h self-edit window (was outside the old 24h window).
        blep = self._blep(self.user, hours_ago_start=25, hours_ago_end=24)
        new_end = blep.end_time + timedelta(minutes=5)
        updated = BlepService.update(blep, self.user, end_time=new_end)
        self.assertEqual(updated.end_time, new_end)

    def test_update_own_old_blep_requires_manage_time(self):
        blep = self._blep(self.user, hours_ago_start=48, hours_ago_end=47)
        with self.assertRaises(BlepPermissionError):
            BlepService.update(
                blep, self.user,
                end_time=blep.end_time + timedelta(minutes=5),
            )

    def test_update_own_old_blep_as_manager_ok(self):
        blep = self._blep(self.user, hours_ago_start=48, hours_ago_end=47)
        new_end = blep.end_time + timedelta(minutes=5)
        updated = BlepService.update(blep, self.manager, end_time=new_end)
        self.assertEqual(updated.end_time, new_end)

    def test_update_other_users_blep_requires_manage_time(self):
        blep = self._blep(self.other)
        with self.assertRaises(BlepPermissionError):
            BlepService.update(
                blep, self.user,
                end_time=blep.end_time + timedelta(minutes=5),
            )

    def test_update_user_as_manager(self):
        blep = self._blep(self.user)
        updated = BlepService.update(blep, self.manager, user=self.other)
        self.assertEqual(updated.user, self.other)

    def test_update_user_without_manage_time_rejected(self):
        blep = self._blep(self.user)
        with self.assertRaises(ValidationError):
            BlepService.update(blep, self.user, user=self.other)

    def test_update_user_checks_overlap_for_new_user(self):
        now = timezone.now()
        # other already has a blep in this window
        Blep.objects.create(
            task=self.task, user=self.other,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
        )
        blep = self._blep(self.user)  # same time window
        with self.assertRaises(ValidationError):
            BlepService.update(blep, self.manager, user=self.other)

    def test_update_rejects_overlap(self):
        now = timezone.now()
        Blep.objects.create(
            task=self.task, user=self.user,
            start_time=now - timedelta(hours=5),
            end_time=now - timedelta(hours=4),
        )
        target = self._blep(self.user, hours_ago_start=3, hours_ago_end=2)
        with self.assertRaises(ValidationError):
            BlepService.update(
                target, self.user,
                start_time=now - timedelta(hours=4, minutes=30),
            )


class DeleteBlepTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1)
        self.user = User.objects.create_user(username='worker1_delete', password='x')
        from django.contrib.auth.models import Permission
        self.manager = User.objects.create_user(username='m', password='x')
        perm = Permission.objects.get(codename='can_manage_time', content_type__app_label='core')
        self.manager.user_permissions.add(perm)
        self.manager = User.objects.get(pk=self.manager.pk)
        self.other = User.objects.create_user(username='w2', password='x')

    def _blep(self, user, hours_ago_start=2):
        now = timezone.now()
        return Blep.objects.create(
            task=self.task, user=user,
            start_time=now - timedelta(hours=hours_ago_start),
            end_time=now - timedelta(hours=hours_ago_start - 0.5),
        )

    def test_delete_own_recent(self):
        blep = self._blep(self.user)
        BlepService.delete(blep, self.user)
        self.assertFalse(Blep.objects.filter(pk=blep.blep_id).exists())

    def test_delete_own_25h_old_is_within_window(self):
        # 25h is inside the 30h self-edit window (was outside the old 24h window).
        blep = self._blep(self.user, hours_ago_start=25)
        BlepService.delete(blep, self.user)
        self.assertFalse(Blep.objects.filter(pk=blep.blep_id).exists())

    def test_delete_own_old_without_manage_time_denied(self):
        blep = self._blep(self.user, hours_ago_start=48)
        with self.assertRaises(BlepPermissionError):
            BlepService.delete(blep, self.user)

    def test_delete_other_without_manage_time_denied(self):
        blep = self._blep(self.other)
        with self.assertRaises(BlepPermissionError):
            BlepService.delete(blep, self.user)

    def test_delete_other_as_manager(self):
        blep = self._blep(self.other)
        BlepService.delete(blep, self.manager)
        self.assertFalse(Blep.objects.filter(pk=blep.blep_id).exists())

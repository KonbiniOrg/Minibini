from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Task, Blep, Job, WorkOrder
from apps.jobs.services import BlepService


class BlepPublicWrapperTest(BaseTestCase):
    """BlepService.close_user_open_bleps is a public wrapper around the
    existing _close_open helper, added so other apps can close a user's
    open bleps without reaching into a pseudo-private method.
    """

    def setUp(self):
        super().setUp()
        self.user = User.objects.get(username='johnq')
        # Grab any existing task from the fixture
        self.task = Task.objects.first()
        self.assertIsNotNone(self.task, 'Fixture must provide at least one Task')

    def test_close_user_open_bleps_closes_open_blep(self):
        open_blep = Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=timezone.now(),
            end_time=None,
        )
        BlepService.close_user_open_bleps(self.user)
        open_blep.refresh_from_db()
        self.assertIsNotNone(open_blep.end_time)

    def test_close_user_open_bleps_leaves_closed_blep_alone(self):
        earlier = timezone.now() - timedelta(hours=2)
        closed_blep = Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=earlier,
            end_time=earlier + timedelta(hours=1),
        )
        original_end = closed_blep.end_time
        BlepService.close_user_open_bleps(self.user)
        closed_blep.refresh_from_db()
        self.assertEqual(closed_blep.end_time, original_end)

    def test_close_user_open_bleps_leaves_other_users_bleps_alone(self):
        other_user = User.objects.get(username='admin')
        open_blep = Blep.objects.create(
            user=other_user,
            task=self.task,
            start_time=timezone.now(),
            end_time=None,
        )
        BlepService.close_user_open_bleps(self.user)
        open_blep.refresh_from_db()
        self.assertIsNone(open_blep.end_time)


class UserApiMountTest(BaseTestCase):
    """Smoke test: /api/users/ is mounted and rejects unauthenticated requests."""

    def test_users_list_url_is_mounted(self):
        client = APIClient()
        response = client.get('/api/users/')
        # With IsAuthenticated + CanManageConfig, unauth gets 403
        self.assertEqual(response.status_code, 403)

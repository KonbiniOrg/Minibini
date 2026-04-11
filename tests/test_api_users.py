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


from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType


class UserListRetrieveTest(BaseTestCase):
    """Tests for GET /api/users/ and GET /api/users/:id/"""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        # Grab an admin-capable user by granting can_manage_config to johnq
        ct = ContentType.objects.get(app_label='core', model='user')
        self.manage_config_perm = Permission.objects.get(
            codename='can_manage_config', content_type=ct
        )
        self.admin = User.objects.get(username='johnq')
        self.admin.user_permissions.add(self.manage_config_perm)
        # A non-admin for gating tests
        self.non_admin = User.objects.get(username='manager1')
        # Remove any direct can_manage_config grant from manager1 just in case
        self.non_admin.user_permissions.remove(self.manage_config_perm)
        self.non_admin.is_superuser = False
        self.non_admin.save()

    def test_list_unauthenticated_returns_403(self):
        response = self.client.get('/api/users/')
        self.assertEqual(response.status_code, 403)

    def test_list_as_non_admin_returns_403(self):
        self.client.force_authenticate(user=self.non_admin)
        response = self.client.get('/api/users/')
        self.assertEqual(response.status_code, 403)

    def test_list_as_admin_returns_200(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/users/')
        self.assertEqual(response.status_code, 200)

    def test_list_is_not_paginated(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/users/')
        # Plain array, not a paginated wrapper
        self.assertIsInstance(response.data, list)

    def test_list_returns_all_users_including_inactive(self):
        # Deactivate one fixture user
        target = User.objects.get(username='admin')
        target.is_active = False
        target.save()
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/users/')
        usernames = [u['username'] for u in response.data]
        self.assertIn('admin', usernames)
        self.assertIn('johnq', usernames)

    def test_list_orders_active_first(self):
        target = User.objects.get(username='admin')
        target.is_active = False
        target.save()
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/users/')
        # All active users should come before all inactive users
        active_flags = [u['is_active'] for u in response.data]
        # A sorted-descending-by-is_active list has all True before all False
        self.assertEqual(active_flags, sorted(active_flags, reverse=True))

    def test_list_fields(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/users/')
        row = next(u for u in response.data if u['username'] == 'johnq')
        expected_keys = {'id', 'username', 'first_name', 'last_name', 'email', 'is_active', 'is_superuser'}
        self.assertEqual(set(row.keys()), expected_keys)

    def test_retrieve_returns_detail_fields(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(f'/api/users/{self.non_admin.pk}/')
        self.assertEqual(response.status_code, 200)
        expected_keys = {
            'id', 'username', 'first_name', 'last_name', 'email',
            'is_active', 'is_superuser', 'permissions', 'date_joined',
        }
        self.assertEqual(set(response.data.keys()), expected_keys)

    def test_retrieve_includes_permission_codenames(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(f'/api/users/{self.admin.pk}/')
        self.assertIn('can_manage_config', response.data['permissions'])

from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Task, Blep, Job
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
        # Over-minimum so it is CLOSED (a sub-minimum blep would be cancelled).
        open_blep = Blep.objects.create(
            user=self.user,
            task=self.task,
            start_time=timezone.now() - timedelta(minutes=30),
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
        expected_keys = {
            'id', 'username', 'first_name', 'last_name', 'email',
            'is_active', 'is_superuser', 'permissions',
        }
        self.assertEqual(set(row.keys()), expected_keys)

    def test_list_includes_permission_codenames(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/users/')
        row = next(u for u in response.data if u['username'] == 'johnq')
        self.assertIn('can_manage_config', row['permissions'])

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


class UserCreateTest(BaseTestCase):
    """Tests for POST /api/users/."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        ct = ContentType.objects.get(app_label='core', model='user')
        self.manage_config_perm = Permission.objects.get(
            codename='can_manage_config', content_type=ct
        )
        self.admin = User.objects.get(username='johnq')
        self.admin.user_permissions.add(self.manage_config_perm)
        self.client.force_authenticate(user=self.admin)

    def _body(self, **overrides):
        body = {
            'username': 'newbie',
            'email': 'newbie@example.com',
            'first_name': 'New',
            'last_name': 'Bie',
            'password': 'StrongPass!123',
            'password_confirm': 'StrongPass!123',
        }
        body.update(overrides)
        return body

    def test_create_user_happy_path(self):
        response = self.client.post('/api/users/', self._body(), format='json')
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username='newbie')
        self.assertEqual(created.email, 'newbie@example.com')
        self.assertEqual(created.first_name, 'New')
        self.assertEqual(created.last_name, 'Bie')

    def test_create_user_response_uses_detail_shape(self):
        response = self.client.post('/api/users/', self._body(), format='json')
        self.assertEqual(response.status_code, 201)
        # Detail shape: includes permissions + date_joined
        self.assertIn('permissions', response.data)
        self.assertIn('date_joined', response.data)
        # Password NEVER in response
        self.assertNotIn('password', response.data)
        self.assertNotIn('password_confirm', response.data)

    def test_create_user_hashes_password(self):
        self.client.post('/api/users/', self._body(), format='json')
        created = User.objects.get(username='newbie')
        self.assertTrue(created.check_password('StrongPass!123'))
        self.assertNotEqual(created.password, 'StrongPass!123')

    def test_create_user_sets_is_active_true_by_default(self):
        self.client.post('/api/users/', self._body(), format='json')
        created = User.objects.get(username='newbie')
        self.assertTrue(created.is_active)

    def test_create_user_duplicate_username_returns_400(self):
        response = self.client.post('/api/users/', self._body(username='johnq'), format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('username', response.data)

    def test_create_user_invalid_email_returns_400(self):
        response = self.client.post('/api/users/', self._body(email='not-an-email'), format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.data)

    def test_create_user_password_too_short_returns_400(self):
        response = self.client.post(
            '/api/users/',
            self._body(password='abc', password_confirm='abc'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('password', response.data)

    def test_create_user_password_common_returns_400(self):
        response = self.client.post(
            '/api/users/',
            self._body(password='password', password_confirm='password'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('password', response.data)

    def test_create_user_password_mismatch_returns_400(self):
        response = self.client.post(
            '/api/users/',
            self._body(password_confirm='Different!123'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('password_confirm', response.data)

    def test_create_user_ignores_is_staff_in_body(self):
        body = self._body()
        body['is_staff'] = True
        body['is_superuser'] = True
        body['is_active'] = False
        response = self.client.post('/api/users/', body, format='json')
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username='newbie')
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)
        self.assertTrue(created.is_active)

    def test_create_user_missing_required_field_returns_400(self):
        body = self._body()
        del body['first_name']
        response = self.client.post('/api/users/', body, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('first_name', response.data)

    def test_create_user_as_non_admin_returns_403(self):
        manager = User.objects.get(username='manager1')
        manager.user_permissions.remove(self.manage_config_perm)
        manager.is_superuser = False
        manager.save()
        self.client.force_authenticate(user=manager)
        response = self.client.post('/api/users/', self._body(), format='json')
        self.assertEqual(response.status_code, 403)


class UserUpdateTest(BaseTestCase):
    """Tests for PATCH /api/users/:id/ and DELETE /api/users/:id/."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        ct = ContentType.objects.get(app_label='core', model='user')
        self.manage_config_perm = Permission.objects.get(
            codename='can_manage_config', content_type=ct
        )
        self.admin = User.objects.get(username='johnq')
        self.admin.user_permissions.add(self.manage_config_perm)
        self.client.force_authenticate(user=self.admin)
        self.target = User.objects.get(username='manager1')

    def test_patch_updates_allowed_fields(self):
        response = self.client.patch(
            f'/api/users/{self.target.pk}/',
            {
                'email': 'newmanager@example.com',
                'first_name': 'NewFirst',
                'last_name': 'NewLast',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.email, 'newmanager@example.com')
        self.assertEqual(self.target.first_name, 'NewFirst')
        self.assertEqual(self.target.last_name, 'NewLast')

    def test_patch_admin_can_edit_username(self):
        response = self.client.patch(
            f'/api/users/{self.target.pk}/',
            {'username': 'managerX'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.username, 'managerX')

    def test_patch_response_uses_detail_shape(self):
        response = self.client.patch(
            f'/api/users/{self.target.pk}/',
            {'first_name': 'Renamed'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('permissions', response.data)
        self.assertIn('date_joined', response.data)

    def test_patch_ignores_password(self):
        original_pw = self.target.password
        response = self.client.patch(
            f'/api/users/{self.target.pk}/',
            {'password': 'TryingToHack!1'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.password, original_pw)

    def test_patch_ignores_is_active(self):
        self.assertTrue(self.target.is_active)
        response = self.client.patch(
            f'/api/users/{self.target.pk}/',
            {'is_active': False},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)

    def test_patch_ignores_is_superuser(self):
        self.assertFalse(self.target.is_superuser)
        response = self.client.patch(
            f'/api/users/{self.target.pk}/',
            {'is_superuser': True},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_superuser)

    def test_patch_ignores_user_permissions(self):
        self.assertEqual(self.target.user_permissions.count(), 0)
        response = self.client.patch(
            f'/api/users/{self.target.pk}/',
            {'user_permissions': [self.manage_config_perm.pk]},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.user_permissions.count(), 0)

    def test_delete_returns_405(self):
        response = self.client.delete(f'/api/users/{self.target.pk}/')
        self.assertEqual(response.status_code, 405)
        self.assertTrue(User.objects.filter(pk=self.target.pk).exists())


from django.contrib.sessions.models import Session


class UserActivateDeactivateTest(BaseTestCase):
    """Tests for POST /api/users/:id/activate/ and /deactivate/."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        ct = ContentType.objects.get(app_label='core', model='user')
        self.manage_config_perm = Permission.objects.get(
            codename='can_manage_config', content_type=ct
        )
        # Two admins so "last admin" checks have room to breathe
        self.admin1 = User.objects.get(username='johnq')
        self.admin1.user_permissions.add(self.manage_config_perm)
        self.admin2 = User.objects.get(username='manager1')
        self.admin2.is_superuser = False
        self.admin2.user_permissions.add(self.manage_config_perm)
        self.admin2.save()
        # A non-admin target
        self.target = User.objects.get(username='admin')
        self.target.is_superuser = False
        self.target.save()
        self.client.force_authenticate(user=self.admin1)

    def test_deactivate_sets_is_active_false(self):
        response = self.client.post(f'/api/users/{self.target.pk}/deactivate/')
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertFalse(response.data['is_active'])

    def test_deactivate_closes_open_bleps(self):
        task = Task.objects.first()
        # Over-minimum so it is CLOSED (a sub-minimum blep would be cancelled).
        open_blep = Blep.objects.create(
            user=self.target, task=task,
            start_time=timezone.now() - timedelta(minutes=30), end_time=None,
        )
        self.client.post(f'/api/users/{self.target.pk}/deactivate/')
        open_blep.refresh_from_db()
        self.assertIsNotNone(open_blep.end_time)

    def test_deactivate_does_not_touch_already_closed_bleps(self):
        task = Task.objects.first()
        earlier = timezone.now() - timedelta(hours=2)
        closed_blep = Blep.objects.create(
            user=self.target, task=task,
            start_time=earlier,
            end_time=earlier + timedelta(hours=1),
        )
        original_end = closed_blep.end_time
        self.client.post(f'/api/users/{self.target.pk}/deactivate/')
        closed_blep.refresh_from_db()
        self.assertEqual(closed_blep.end_time, original_end)

    def test_deactivate_kills_target_session(self):
        # Log the target in with a real session
        self.target.set_password('TargetPass!99')
        self.target.save()
        target_client = APIClient()
        target_client.login(username=self.target.username, password='TargetPass!99')
        # Target confirms they're authenticated
        me = target_client.get('/api/auth/me/')
        self.assertEqual(me.status_code, 200)
        # Admin deactivates target via a separate client
        self.client.post(f'/api/users/{self.target.pk}/deactivate/')
        # Target's existing session should be gone
        me_after = target_client.get('/api/auth/me/')
        self.assertEqual(me_after.status_code, 403)

    def test_deactivate_self_returns_400(self):
        response = self.client.post(f'/api/users/{self.admin1.pk}/deactivate/')
        self.assertEqual(response.status_code, 400)
        self.admin1.refresh_from_db()
        self.assertTrue(self.admin1.is_active)

    def test_deactivate_last_admin_returns_400(self):
        """D3: can't deactivate the only user with can_manage_config.

        Setup: admin2 is the only user with can_manage_config (strip it
        from admin1). admin1 becomes a superuser so they can still call
        the admin endpoint (is_superuser bypasses the CanManageConfig
        permission class). Then admin1 tries to deactivate admin2 — the
        last permission-holder — and D3 must fire.
        """
        self.admin1.user_permissions.remove(self.manage_config_perm)
        self.admin1.is_superuser = True
        self.admin1.save()
        # admin2 already has can_manage_config from setUp; confirm it.
        self.assertTrue(
            self.admin2.user_permissions.filter(codename='can_manage_config').exists()
        )
        self.client.force_authenticate(user=self.admin1)
        response = self.client.post(f'/api/users/{self.admin2.pk}/deactivate/')
        self.assertEqual(response.status_code, 400)
        self.admin2.refresh_from_db()
        self.assertTrue(self.admin2.is_active)

    def test_activate_sets_is_active_true(self):
        self.target.is_active = False
        self.target.save()
        response = self.client.post(f'/api/users/{self.target.pk}/activate/')
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)

    def test_activate_has_no_side_effects(self):
        self.target.is_active = False
        self.target.save()
        task = Task.objects.first()
        closed_blep = Blep.objects.create(
            user=self.target, task=task,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
        )
        original_end = closed_blep.end_time
        self.client.post(f'/api/users/{self.target.pk}/activate/')
        closed_blep.refresh_from_db()
        # Bleps are not reopened
        self.assertEqual(closed_blep.end_time, original_end)


class UserResetPasswordTest(BaseTestCase):
    """Tests for POST /api/users/:id/reset-password/."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        ct = ContentType.objects.get(app_label='core', model='user')
        self.manage_config_perm = Permission.objects.get(
            codename='can_manage_config', content_type=ct
        )
        self.admin = User.objects.get(username='johnq')
        self.admin.user_permissions.add(self.manage_config_perm)
        self.target = User.objects.get(username='manager1')
        self.target.set_password('OldPass!99')
        self.target.save()
        self.client.force_authenticate(user=self.admin)

    def _body(self, **overrides):
        body = {'password': 'NewPass!88', 'password_confirm': 'NewPass!88'}
        body.update(overrides)
        return body

    def test_reset_password_happy_path(self):
        response = self.client.post(
            f'/api/users/{self.target.pk}/reset-password/',
            self._body(),
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password('NewPass!88'))
        self.assertFalse(self.target.check_password('OldPass!99'))

    def test_reset_password_mismatch_returns_400(self):
        response = self.client.post(
            f'/api/users/{self.target.pk}/reset-password/',
            self._body(password_confirm='Different!88'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('password_confirm', response.data)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password('OldPass!99'))

    def test_reset_password_too_short_returns_400(self):
        response = self.client.post(
            f'/api/users/{self.target.pk}/reset-password/',
            self._body(password='abc', password_confirm='abc'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('password', response.data)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password('OldPass!99'))

    def test_reset_password_common_returns_400(self):
        response = self.client.post(
            f'/api/users/{self.target.pk}/reset-password/',
            self._body(password='password', password_confirm='password'),
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_reset_password_invalidates_target_session(self):
        target_client = APIClient()
        target_client.login(username='manager1', password='OldPass!99')
        # Confirm target is initially authenticated
        me = target_client.get('/api/auth/me/')
        self.assertEqual(me.status_code, 200)
        # Admin resets via separate client
        self.client.post(
            f'/api/users/{self.target.pk}/reset-password/',
            self._body(),
            format='json',
        )
        # Target's session should be invalid
        me_after = target_client.get('/api/auth/me/')
        self.assertEqual(me_after.status_code, 403)

    def test_reset_password_self_is_allowed(self):
        # Admin resets their own password
        self.client.post(
            f'/api/users/{self.admin.pk}/reset-password/',
            self._body(),
            format='json',
        )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('NewPass!88'))

    def test_reset_password_missing_field_returns_400(self):
        body = self._body()
        del body['password']
        response = self.client.post(
            f'/api/users/{self.target.pk}/reset-password/',
            body,
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('password', response.data)


class UserPermissionsTest(BaseTestCase):
    """Tests for PUT /api/users/:id/permissions/."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        ct = ContentType.objects.get(app_label='core', model='user')
        self.manage_config_perm = Permission.objects.get(
            codename='can_manage_config', content_type=ct
        )
        self.manage_jobs_perm = Permission.objects.get(
            codename='can_manage_jobs', content_type=ct
        )
        # Two admins so D3 has room
        self.admin1 = User.objects.get(username='johnq')
        self.admin1.user_permissions.add(self.manage_config_perm)
        self.admin2 = User.objects.get(username='manager1')
        self.admin2.is_superuser = False
        self.admin2.user_permissions.add(self.manage_config_perm)
        self.admin2.save()
        self.target = User.objects.get(username='admin')
        self.target.is_superuser = False
        self.target.save()
        self.client.force_authenticate(user=self.admin1)

    def test_set_permissions_replaces_m2m(self):
        response = self.client.put(
            f'/api/users/{self.target.pk}/permissions/',
            {'permissions': ['can_manage_jobs', 'can_manage_time']},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        codenames = set(
            self.target.user_permissions.values_list('codename', flat=True)
        )
        self.assertEqual(codenames, {'can_manage_jobs', 'can_manage_time'})

    def test_set_permissions_empty_list_clears_all_atoms(self):
        self.target.user_permissions.add(self.manage_jobs_perm)
        response = self.client.put(
            f'/api/users/{self.target.pk}/permissions/',
            {'permissions': []},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.user_permissions.count(), 0)

    def test_set_permissions_unknown_codename_returns_400(self):
        response = self.client.put(
            f'/api/users/{self.target.pk}/permissions/',
            {'permissions': ['can_hack_everything']},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('permissions', response.data)

    def test_set_permissions_response_uses_detail_shape(self):
        response = self.client.put(
            f'/api/users/{self.target.pk}/permissions/',
            {'permissions': ['can_manage_jobs']},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('permissions', response.data)
        self.assertIn('date_joined', response.data)
        self.assertEqual(response.data['permissions'], ['can_manage_jobs'])

    def test_set_permissions_remove_own_can_manage_config_returns_400(self):
        # admin1 tries to remove their own can_manage_config
        response = self.client.put(
            f'/api/users/{self.admin1.pk}/permissions/',
            {'permissions': ['can_manage_jobs']},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.admin1.refresh_from_db()
        self.assertTrue(
            self.admin1.user_permissions.filter(codename='can_manage_config').exists()
        )

    def test_set_permissions_remove_last_admin_can_manage_config_returns_400(self):
        """D3: a superuser actor cannot strip can_manage_config from the
        only user who has it. D2 (self-demote) would also fire if the
        actor were the target, so we use a separate is_superuser actor.
        """
        # Strip admin2's can_manage_config so admin1 is the only holder.
        self.admin2.user_permissions.remove(self.manage_config_perm)
        # Create a superuser who can call the endpoint via is_superuser
        # bypass (they don't need can_manage_config themselves).
        other = User.objects.create_superuser(
            username='supe', email='supe@example.com', password='SuperPass!99',
            first_name='Supe', last_name='Rman',
        )
        self.client.force_authenticate(user=other)
        # admin1 is the only user with can_manage_config
        response = self.client.put(
            f'/api/users/{self.admin1.pk}/permissions/',
            {'permissions': []},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.admin1.refresh_from_db()
        self.assertTrue(
            self.admin1.user_permissions.filter(codename='can_manage_config').exists()
        )

    def test_set_permissions_remove_non_last_admin_succeeds(self):
        # Both admin1 and admin2 have can_manage_config. Remove from admin2.
        # admin1 still has it, so D3 should NOT fire.
        # But admin1 is acting; admin2 is target. D2 only fires if actor==target.
        response = self.client.put(
            f'/api/users/{self.admin2.pk}/permissions/',
            {'permissions': ['can_manage_jobs']},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.admin2.refresh_from_db()
        self.assertFalse(
            self.admin2.user_permissions.filter(codename='can_manage_config').exists()
        )


class AssigneeExclusionRegressionTest(BaseTestCase):
    """Guard: deactivated users must not appear in assignee dropdowns.

    These tests protect existing behavior — not new code. If they fail,
    someone removed an is_active filter and needs to put it back.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.caller = User.objects.get(username='johnq')
        self.deactivated = User.objects.get(username='manager1')
        self.deactivated.is_active = False
        self.deactivated.save()

    def test_auth_users_list_excludes_deactivated(self):
        self.client.force_authenticate(user=self.caller)
        response = self.client.get('/api/auth/users/')
        self.assertEqual(response.status_code, 200)
        usernames = [u['username'] for u in response.data]
        self.assertNotIn('manager1', usernames)
        self.assertIn('johnq', usernames)

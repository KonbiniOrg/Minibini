from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User


class MeUpdateAPITest(BaseTestCase):
    """Tests for PATCH /api/auth/me/ — self-service profile update."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        # johnq is a non-superuser, non-staff, active user in the fixture.
        # Using a non-superuser lets us meaningfully assert that privilege
        # flags don't move in the privilege-escalation test.
        self.user = User.objects.get(username='johnq')
        self.user.set_password('testpass123')
        self.user.save()

    def test_patch_me_unauthenticated_returns_403(self):
        response = self.client.patch(
            '/api/auth/me/',
            {'first_name': 'Nope'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_patch_me_updates_all_three_fields(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            '/api/auth/me/',
            {
                'email': 'newemail@example.com',
                'first_name': 'NewFirst',
                'last_name': 'NewLast',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'newemail@example.com')
        self.assertEqual(self.user.first_name, 'NewFirst')
        self.assertEqual(self.user.last_name, 'NewLast')
        # Response body should be the full UserSerializer shape
        self.assertEqual(response.data['email'], 'newemail@example.com')
        self.assertEqual(response.data['first_name'], 'NewFirst')
        self.assertEqual(response.data['username'], 'johnq')

    def test_patch_me_partial_update_leaves_other_fields(self):
        original_email = self.user.email
        original_last = self.user.last_name
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            '/api/auth/me/',
            {'first_name': 'OnlyFirst'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'OnlyFirst')
        self.assertEqual(self.user.email, original_email)
        self.assertEqual(self.user.last_name, original_last)

    def test_patch_me_invalid_email_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            '/api/auth/me/',
            {'email': 'not-an-email'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.data)

    def test_patch_me_ignores_username(self):
        original_username = self.user.username
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            '/api/auth/me/',
            {'username': 'hacker', 'first_name': 'Legit'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, original_username)
        self.assertEqual(self.user.first_name, 'Legit')

    def test_patch_me_ignores_privilege_flags(self):
        """Privilege-escalation guard.

        Sending is_staff, is_superuser, or is_active in the PATCH body
        must not mutate those fields. The serializer's fields allowlist
        (only email, first_name, last_name) is what enforces this.
        """
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertTrue(self.user.is_active)
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(
            '/api/auth/me/',
            {
                'is_staff': True,
                'is_superuser': True,
                'is_active': False,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertTrue(self.user.is_active)

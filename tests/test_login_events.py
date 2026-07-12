"""Login tracking: LoginEvent rows record every successful login.

Recording is a `user_logged_in` signal handler, so every auth path that
goes through django.contrib.auth.login() writes a row. Failed attempts
write nothing.
"""

from django.contrib.auth import login as auth_login
from django.test import RequestFactory

from tests.base import BaseTestCase
from apps.core.models import LoginEvent, User


class LoginEventRecordingTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.user = User.objects.get(username='admin')
        self.user.set_password('testpass123')
        self.user.save()

    def test_successful_login_creates_event(self):
        self.assertEqual(LoginEvent.objects.count(), 0)
        response = self.client.post('/api/auth/login/', {
            'username': 'admin', 'password': 'testpass123',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        event = LoginEvent.objects.get()
        self.assertEqual(event.user, self.user)
        self.assertIsNotNone(event.timestamp)

    def test_failed_login_creates_no_event(self):
        self.client.post('/api/auth/login/', {
            'username': 'admin', 'password': 'wrong',
        }, content_type='application/json')
        self.assertEqual(LoginEvent.objects.count(), 0)

    def test_captures_ip_and_truncated_user_agent(self):
        self.client.post('/api/auth/login/', {
            'username': 'admin', 'password': 'testpass123',
        }, content_type='application/json',
            REMOTE_ADDR='192.0.2.10', HTTP_USER_AGENT='x' * 600)
        event = LoginEvent.objects.get()
        self.assertEqual(event.ip_address, '192.0.2.10')
        self.assertEqual(len(event.user_agent), 500)

    def test_x_forwarded_for_wins_over_remote_addr(self):
        self.client.post('/api/auth/login/', {
            'username': 'admin', 'password': 'testpass123',
        }, content_type='application/json',
            REMOTE_ADDR='10.0.0.1',
            HTTP_X_FORWARDED_FOR='192.0.2.77, 10.0.0.1')
        event = LoginEvent.objects.get()
        self.assertEqual(event.ip_address, '192.0.2.77')

    def test_programmatic_login_without_meta_does_not_crash(self):
        # Bare request (no META middleware decoration beyond the factory's)
        # must still record; request=None paths are covered by the handler's
        # guard but can't reach auth_login, which requires a request.
        request = RequestFactory().get('/')
        request.session = self.client.session
        auth_login(request, self.user,
                   backend='django.contrib.auth.backends.ModelBackend')
        self.assertEqual(LoginEvent.objects.filter(user=self.user).count(), 1)

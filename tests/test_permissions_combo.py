from django.contrib.auth.models import Permission
from tests.base import BaseTestCase
from apps.core.models import User
from apps.api.permissions import CanManageTimeOrFinancials


class _Req:
    def __init__(self, user): self.user = user


class ComboPermTest(BaseTestCase):
    def _user(self, codename=None):
        u = User.objects.create_user(username=f'combo_{codename}', password='x')
        if codename:
            u.user_permissions.add(Permission.objects.get(
                codename=codename, content_type__app_label='core'))
            u = User.objects.get(pk=u.pk)
        return u

    def test_time_allowed(self):
        self.assertTrue(CanManageTimeOrFinancials().has_permission(
            _Req(self._user('can_manage_time')), None))

    def test_financials_allowed(self):
        self.assertTrue(CanManageTimeOrFinancials().has_permission(
            _Req(self._user('can_manage_financials')), None))

    def test_neither_denied(self):
        self.assertFalse(CanManageTimeOrFinancials().has_permission(
            _Req(self._user()), None))

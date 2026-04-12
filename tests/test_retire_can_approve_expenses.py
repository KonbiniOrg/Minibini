from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from apps.api.users.serializers import PermissionsUpdateSerializer

User = get_user_model()


class CanApproveExpensesRetirementTest(TestCase):
    """Guards against the retired can_approve_expenses atom re-appearing."""

    def test_atom_is_not_in_user_meta_permissions(self):
        codenames = [codename for codename, _label in User._meta.permissions]
        self.assertNotIn('can_approve_expenses', codenames)

    def test_permissions_serializer_rejects_retired_atom(self):
        serializer = PermissionsUpdateSerializer(
            data={'permissions': ['can_approve_expenses']}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('permissions', serializer.errors)

    def test_permissions_serializer_accepts_remaining_atoms(self):
        serializer = PermissionsUpdateSerializer(
            data={'permissions': [
                'can_manage_jobs',
                'can_manage_financials',
                'can_manage_time',
                'can_manage_config',
            ]}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_no_django_permission_row_for_retired_atom(self):
        self.assertFalse(
            Permission.objects.filter(
                codename='can_approve_expenses',
                content_type__app_label='core',
            ).exists()
        )

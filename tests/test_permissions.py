from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from tests.base import BaseTestCase

User = get_user_model()


class PermissionAtomsTest(BaseTestCase):
    """Verify custom permission atoms exist after migration."""

    EXPECTED_ATOMS = [
        'can_manage_jobs',
        'can_view_jobs',
        'can_manage_invoicing',
        'can_manage_purchasing',
        'can_manage_time',
        'can_approve_expenses',
        'can_manage_config',
    ]

    def test_all_permission_atoms_exist(self):
        """All 7 permission atoms should exist in auth_permission table."""
        for codename in self.EXPECTED_ATOMS:
            with self.subTest(codename=codename):
                self.assertTrue(
                    Permission.objects.filter(
                        codename=codename,
                        content_type__app_label='core',
                    ).exists(),
                    f"Permission '{codename}' not found"
                )

    def test_user_can_be_assigned_permission(self):
        """A permission atom can be assigned to a user and checked via has_perm."""
        user = User.objects.get(username='johnq')
        perm = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
        user.user_permissions.add(perm)
        # Clear cached permissions
        user = User.objects.get(pk=user.pk)
        self.assertTrue(user.has_perm('core.can_manage_jobs'))
        self.assertFalse(user.has_perm('core.can_manage_invoicing'))

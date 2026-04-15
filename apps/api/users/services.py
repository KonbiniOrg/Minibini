"""Owner-side user administration service.

All business logic (lockout checks, side effects) lives here so the
viewset stays a thin wrapper.
"""
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from rest_framework import serializers as drf_serializers
from apps.core.models import User
from apps.jobs.services import BlepService


class UserAdminService:

    # ── deactivate ─────────────────────────────────────────────

    @staticmethod
    def deactivate_user(actor, target):
        UserAdminService._check_not_self(actor, target, action='deactivate')
        UserAdminService._check_not_last_admin_by_flag(target)
        target.is_active = False
        target.save(update_fields=['is_active'])
        BlepService.close_user_open_bleps(target)
        UserAdminService._kill_sessions_for_user(target)
        return target

    # ── activate ───────────────────────────────────────────────

    @staticmethod
    def activate_user(actor, target):
        target.is_active = True
        target.save(update_fields=['is_active'])
        return target

    # ── set permissions ────────────────────────────────────────

    @staticmethod
    def set_permissions(actor, target, atom_codenames):
        """Replace target's user_permissions M2M with the given atom set."""
        UserAdminService._check_not_remove_own_manage_config(
            actor, target, atom_codenames
        )
        UserAdminService._check_not_remove_last_admin_manage_config(
            target, atom_codenames
        )
        perms = Permission.objects.filter(
            codename__in=atom_codenames,
            content_type__app_label='core',
        )
        target.user_permissions.set(perms)
        return target

    @staticmethod
    def _check_not_remove_own_manage_config(actor, target, new_codenames):
        if actor.pk != target.pk:
            return
        if 'can_manage_config' in new_codenames:
            return
        if UserAdminService._target_has_can_manage_config(target):
            raise drf_serializers.ValidationError(
                'You cannot remove your own can_manage_config permission.'
            )

    @staticmethod
    def _check_not_remove_last_admin_manage_config(target, new_codenames):
        if 'can_manage_config' in new_codenames:
            return
        if not UserAdminService._target_has_can_manage_config(target):
            return
        count = UserAdminService._count_active_admins()
        if count <= 1:
            raise drf_serializers.ValidationError(
                'Cannot remove can_manage_config from the last user who has it.'
            )

    # ── helpers ────────────────────────────────────────────────

    @staticmethod
    def _check_not_self(actor, target, action):
        if actor.pk == target.pk:
            raise drf_serializers.ValidationError(
                f'You cannot {action} yourself.'
            )

    @staticmethod
    def _check_not_last_admin_by_flag(target):
        """Block deactivation if target is the only active user with
        can_manage_config. Only runs if target currently has the permission.
        """
        if not UserAdminService._target_has_can_manage_config(target):
            return
        count = UserAdminService._count_active_admins()
        if count <= 1:
            raise drf_serializers.ValidationError(
                'Cannot deactivate the last user who can manage config.'
            )

    @staticmethod
    def _target_has_can_manage_config(target):
        return target.user_permissions.filter(
            codename='can_manage_config',
            content_type__app_label='core',
        ).exists()

    @staticmethod
    def _count_active_admins():
        return User.objects.filter(
            is_active=True,
            user_permissions__codename='can_manage_config',
            user_permissions__content_type__app_label='core',
        ).distinct().count()

    @staticmethod
    def _kill_sessions_for_user(user):
        """Delete any Django sessions whose _auth_user_id matches this user.

        Django's default DB session store has no index on decoded user ID,
        so we iterate. Fine for small shops.
        """
        target_pk = str(user.pk)
        for session in Session.objects.all():
            data = session.get_decoded()
            if data.get('_auth_user_id') == target_pk:
                session.delete()

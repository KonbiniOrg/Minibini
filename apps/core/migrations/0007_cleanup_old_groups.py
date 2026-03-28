from django.db import migrations


OLD_GROUPS = ['Worker', 'Manager', 'Bookkeeper', 'Admin']
OLD_ATOMS = ['can_view_jobs', 'can_manage_invoicing', 'can_manage_purchasing']


def cleanup_old_data(apps, schema_editor):
    """Delete groups created by migration 0005 and remove stale
    user-permission M2M entries for the 3 dropped atoms.
    Groups are now managed via fixtures/test setUp, not migrations.
    """
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')

    # Delete old groups (cascades group-permission M2M)
    Group.objects.filter(name__in=OLD_GROUPS).delete()

    # Remove stale user_permissions entries for dropped atoms
    old_perms = Permission.objects.filter(codename__in=OLD_ATOMS)
    if old_perms.exists():
        User = apps.get_model('core', 'User')
        for user in User.objects.filter(user_permissions__in=old_perms).distinct():
            user.user_permissions.remove(*old_perms)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_alter_user_options'),
    ]

    operations = [
        migrations.RunPython(cleanup_old_data, noop),
    ]

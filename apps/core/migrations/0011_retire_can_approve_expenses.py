from django.db import migrations


def remove_atom(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')

    perms = Permission.objects.filter(
        codename='can_approve_expenses',
        content_type__app_label='core',
    )
    for group in Group.objects.filter(name__in=('Bookkeeper', 'Manager', 'Owner')):
        for perm in perms:
            group.permissions.remove(perm)
    perms.delete()


def restore_atom(apps, schema_editor):
    from django.contrib.contenttypes.models import ContentType
    Permission = apps.get_model('auth', 'Permission')
    User = apps.get_model('core', 'User')
    ct = ContentType.objects.get_for_model(User)
    Permission.objects.get_or_create(
        codename='can_approve_expenses',
        content_type=ct,
        defaults={'name': 'Can approve/reject expenses over threshold'},
    )


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0010_alter_user_options'),
    ]
    operations = [
        migrations.AlterModelOptions(
            name='user',
            options={
                'verbose_name': 'User',
                'verbose_name_plural': 'Users',
                'permissions': [
                    ('can_manage_jobs', 'Can manage jobs, estimates, worksheets, work orders, tasks, contacts'),
                    ('can_manage_financials', 'Can manage invoices, POs, bills, price list'),
                    ('can_manage_time', "Can edit/delete anyone's time entries"),
                    ('can_manage_config', 'Can manage settings, templates, user admin'),
                ],
            },
        ),
        migrations.RunPython(remove_atom, reverse_code=restore_atom),
    ]

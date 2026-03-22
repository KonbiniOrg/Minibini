from django.db import migrations


PERMISSION_DEFINITIONS = [
    ('can_manage_jobs', 'Can manage jobs, estimates, worksheets, work orders, tasks'),
    ('can_view_jobs', 'Read-only access to all jobs and related documents'),
    ('can_manage_invoicing', 'Can manage invoices, price list, send/payment'),
    ('can_manage_purchasing', 'Can manage POs, bills, send/receive'),
    ('can_manage_time', "Can edit/delete anyone's time entries"),
    ('can_approve_expenses', 'Can approve/reject expenses over threshold'),
    ('can_manage_config', 'Can manage settings, templates, user admin'),
]

GROUPS_CONFIG = {
    'Admin': [
        'can_manage_jobs', 'can_view_jobs', 'can_manage_invoicing',
        'can_manage_purchasing', 'can_manage_time',
        'can_approve_expenses', 'can_manage_config',
    ],
    'Manager': ['can_view_jobs', 'can_manage_jobs', 'can_manage_time', 'can_approve_expenses'],
    'Worker': ['can_view_jobs'],
    'Bookkeeper': ['can_view_jobs', 'can_manage_invoicing', 'can_manage_purchasing', 'can_approve_expenses'],
}


def create_default_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    ct, _ = ContentType.objects.get_or_create(app_label='core', model='user')

    # Ensure permission objects exist (post_migrate signal hasn't fired yet)
    for codename, name in PERMISSION_DEFINITIONS:
        Permission.objects.get_or_create(
            codename=codename,
            content_type=ct,
            defaults={'name': name},
        )

    def get_perms(*codenames):
        return Permission.objects.filter(codename__in=codenames, content_type=ct)

    for group_name, perm_codenames in GROUPS_CONFIG.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        group.permissions.set(get_perms(*perm_codenames))


def remove_default_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name__in=['Worker', 'Manager', 'Bookkeeper', 'Admin']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_alter_user_options'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(create_default_groups, remove_default_groups),
    ]

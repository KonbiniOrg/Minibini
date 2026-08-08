# Data-only migration (better-fees spec §3): flatten every subtask to
# top-level. Task.parent_task goes DORMANT — the field stays in the schema
# (a possible third redesign of this area may want the shape back) but no
# code reads or writes it after this point. NULLing the existing rows is
# not just tidiness: the FK is on_delete=CASCADE, so a stale child pointer
# would let deleting a former parent silently cascade-delete tasks the UI
# no longer shows as related. validate_data's check_no_parent_task guards
# the NULL invariant from here on.
#
# QuerySet.update() is safe here: parent_task has no save()-time
# normalization or side effects, and historical models carry no custom
# save() anyway.
from django.db import migrations


def flatten_subtasks(apps, schema_editor):
    Task = apps.get_model('jobs', 'Task')
    Task.objects.filter(parent_task__isnull=False).update(parent_task=None)


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0060_alter_task_est_qty'),
    ]

    operations = [
        migrations.RunPython(flatten_subtasks, migrations.RunPython.noop),
    ]

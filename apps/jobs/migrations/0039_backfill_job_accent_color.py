from django.db import migrations


PALETTE = (
    '#f97066', '#f59e0b', '#14b8a6', '#8b5cf6',
    '#38bdf8', '#fb7185', '#84cc16', '#f97316',
)


def backfill(apps, schema_editor):
    Job = apps.get_model('jobs', 'Job')
    counts = dict.fromkeys(PALETTE, 0)
    # Seed counts with whatever colors are already set (defensive — partial
    # re-application or human-edited rows).
    for job in Job.objects.exclude(accent_color__isnull=True):
        if job.accent_color in counts:
            counts[job.accent_color] += 1
    for job in Job.objects.filter(accent_color__isnull=True).order_by('pk'):
        color = min(PALETTE, key=lambda c: (counts[c], PALETTE.index(c)))
        job.accent_color = color
        job.save(update_fields=['accent_color'])
        counts[color] += 1


def reverse(apps, schema_editor):
    Job = apps.get_model('jobs', 'Job')
    Job.objects.update(accent_color=None)


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0038_job_accent_color'),
    ]

    operations = [
        migrations.RunPython(backfill, reverse),
    ]

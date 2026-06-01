import secrets
from django.db import migrations, models


def backfill_tokens(apps, schema_editor):
    Estimate = apps.get_model('estimates', 'Estimate')
    for est in Estimate.objects.filter(public_token__isnull=True):
        est.public_token = secrets.token_urlsafe(32)
        est.save(update_fields=['public_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('estimates', '0021_changeorder_changeorderlineitem'),
    ]

    operations = [
        migrations.AddField(
            model_name='estimate',
            name='public_token',
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
        migrations.RunPython(backfill_tokens, migrations.RunPython.noop),
    ]

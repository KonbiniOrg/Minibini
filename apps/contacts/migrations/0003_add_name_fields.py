# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0002_rename_term_id_business_terms'),
    ]

    operations = [
        migrations.AddField(
            model_name='contact',
            name='first_name',
            field=models.CharField(max_length=100, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='contact',
            name='middle_initial',
            field=models.CharField(max_length=10, blank=True),
        ),
        migrations.AddField(
            model_name='contact',
            name='last_name',
            field=models.CharField(max_length=100, null=True, blank=True),
        ),
    ]

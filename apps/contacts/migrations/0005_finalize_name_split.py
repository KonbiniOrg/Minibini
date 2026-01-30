# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0004_split_existing_names'),
    ]

    operations = [
        # Make first_name and last_name non-nullable
        migrations.AlterField(
            model_name='contact',
            name='first_name',
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name='contact',
            name='last_name',
            field=models.CharField(max_length=100),
        ),
        # Remove the old name field
        migrations.RemoveField(
            model_name='contact',
            name='name',
        ),
    ]
